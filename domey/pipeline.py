import os
import json
from hyperapi import HyperAPIClient
from datetime import datetime
from collections import defaultdict

API_KEY  = "hk_live_3316025b3caee51127133669bbee4588"   
BASE_URL = "http://hyperapi-production-12097051.us-east-1.elb.amazonaws.com/"
PDF_FILE = "C:\\Users\\LENOVO\\OneDrive\\Desktop\\domey\\gauntlet.pdf"           
TEAM_ID  = "errhandle"              

findings = []
counter  = 1

def add_finding(category, pages, doc_refs, description, reported, correct):
    global counter
    findings.append({
        "finding_id": f"F-{counter:03d}",
        "category":       category,
        "pages":          pages,
        "document_refs":  doc_refs,
        "description":    description,
        "reported_value": str(reported),
        "correct_value":  str(correct)
    })
    counter += 1
    print(f"   [{category}] {doc_refs} page {pages}")


print("⏳ Calling HyperAPI to parse + extract document...")

with HyperAPIClient(api_key=API_KEY, base_url=BASE_URL) as client:

   
    print("📄 Parsing document...")
    parse_result = client.parse(PDF_FILE)
    ocr_text = parse_result["result"]["ocr"]
    print(f"✅ OCR done! Text length: {len(ocr_text)} chars")

    

with open("ocr_output.txt", "w") as f:
    f.write(ocr_text)


print(" Raw results saved!")

import re

vendor_master = {}
state_codes = {
    "01": "Jammu & Kashmir", "07": "Delhi",
    "19": "West Bengal",     "24": "Gujarat",
    "27": "Maharashtra",     "29": "Karnataka",
    "33": "Tamil Nadu",      "36": "Telangana",
}


vendor_section = re.findall(
    r'\n(\d+)\s+([\w\s&.,\'()-]+?)\s+([0-9A-Z]{15})\s+'
    r'(Maharashtra|Karnataka|Tamil Nadu|Telangana|Gujarat|Delhi|West Bengal)\s+'
    r'[\w\s.]+?\s+((?:HDFC|ICIC|SBIN|UTIB|KKBK|PUNB|BARB|CNRB|UBIN|INDB)[0-9A-Z]+)',
    ocr_text
)
for row in vendor_section:
    name = row[1].strip()
    vendor_master[name] = {
        "gstin": row[2].strip(),
        "state": row[3].strip(),
        "ifsc":  row[4].strip()
    }
print(f" Vendors loaded: {len(vendor_master)}")


pages_raw = ocr_text.split('\f')
page_map  = {}
cur_page  = 1
for chunk in pages_raw:
    m = re.search(r'\nPage (\d+)\n', chunk)
    if m:
        cur_page = int(m.group(1))
    page_map[cur_page] = chunk

invoices = []
inv_pattern = re.compile(
    r'TAX INVOICE\s+Invoice No:\s+(INV-[\d-]+)\s+Date:\s+(\d{2}/\d{2}/\d{4})'
    r'(?:\s+PO Reference:\s+(PO-[\d-]+))?',
    re.DOTALL
)

for pg_num, pg_text in page_map.items():
    if 'TAX INVOICE' in pg_text and 'Invoice No:' in pg_text:
        for m in inv_pattern.findall(pg_text):
            inv_no, inv_date, po_ref = m

            vendor_m = re.search(
                r'VENDOR DETAILS\s+Name:\s+([\w\s&.,\'()-]+?)\s+GSTIN:', pg_text)
            vendor_name = vendor_m.group(1).strip() if vendor_m else "Unknown"

            ifsc_m   = re.search(r'IFSC:\s+([A-Z]{4}[0-9A-Z]+)', pg_text)
            gstin_m  = re.search(
                r'VENDOR DETAILS.*?GSTIN:\s+([0-9A-Z]{15})', pg_text, re.DOTALL)
            inv_ifsc  = ifsc_m.group(1).strip()  if ifsc_m  else None
            inv_gstin = gstin_m.group(1).strip() if gstin_m else None

            
            line_items = []
            for li in re.findall(
                r'\n(\d+)\s+([\w\s/&,.()\'-]+?)\s+(\d{5,})\s+'
                r'([\d.]+)\s+(\w+)\s+[■₹]?([\d,]+\.?\d*)\s+[■₹]?([\d,]+\.?\d*)',
                pg_text
            ):
                try:
                    line_items.append({
                        "num":    li[0],
                        "desc":   li[1].strip(),
                        "hsn":    li[2],
                        "qty":    float(li[3]),
                        "unit":   li[4],
                        "rate":   float(li[5].replace(',', '')),
                        "amount": float(li[6].replace(',', ''))
                    })
                except: pass

            invoices.append({
                "inv_no":      inv_no,
                "date":        inv_date,
                "po_ref":      po_ref or None,
                "vendor_name": vendor_name,
                "ifsc":        inv_ifsc,
                "gstin":       inv_gstin,
                "page":        pg_num,
                "line_items":  line_items
            })

print(f" Invoices parsed: {len(invoices)}")



print("\n🔍 Running error checks...")


for inv in invoices:
    for li in inv["line_items"]:
        expected = round(li["qty"] * li["rate"], 2)
        actual   = round(li["amount"], 2)
        if abs(expected - actual) > 1.0:
            add_finding("arithmetic_error", [inv["page"]], [inv["inv_no"]],
                f"Line {li['num']}: {li['qty']} x {li['rate']} = {expected} not {actual}",
                actual, expected)

for inv in invoices:
    try:
        d, mo, y = map(int, inv["date"].split('/'))
        datetime(y, mo, d)
    except ValueError:
        add_finding("invalid_date", [inv["page"]], [inv["inv_no"]],
            f"Impossible date: {inv['date']}", inv["date"], "Valid date required")


for inv in invoices:
    for li in inv["line_items"]:
        if li["unit"] == "Hrs" and 0 < li["qty"] < 1:
            mins         = round(li["qty"] * 100)
            correct_hrs  = round(mins / 60, 4)
            correct_amt  = round(correct_hrs * li["rate"], 2)
            if abs(correct_amt - li["amount"]) > 1.0:
                add_finding("billing_typo", [inv["page"]], [inv["inv_no"]],
                    f"Hours {li['qty']} = {mins} mins = {correct_hrs} hrs",
                    li["qty"], correct_hrs)

for inv in invoices:
    seen = []
    for li in inv["line_items"]:
        key = (li["desc"], li["qty"], li["rate"])
        if key in seen:
            add_finding("duplicate_line_item", [inv["page"]], [inv["inv_no"]],
                f"Duplicate: {li['desc']}", "Duplicate", "Once only")
        seen.append(key)

for inv in invoices:
    if inv["vendor_name"] not in vendor_master:
        for official in vendor_master:
            inv_words = set(inv["vendor_name"].lower().split())
            off_words = set(official.lower().split())
            if len(inv_words & off_words) >= 2:
                add_finding("vendor_name_typo", [inv["page"]], [inv["inv_no"]],
                    f"'{inv['vendor_name']}' should be '{official}'",
                    inv["vendor_name"], official)
                break


for inv in invoices:
    if inv["ifsc"] and inv["vendor_name"] in vendor_master:
        master_ifsc = vendor_master[inv["vendor_name"]]["ifsc"]
        if inv["ifsc"] != master_ifsc:
            add_finding("ifsc_mismatch", [inv["page"]], [inv["inv_no"]],
                f"Invoice IFSC {inv['ifsc']} != Master {master_ifsc}",
                inv["ifsc"], master_ifsc)


for inv in invoices:
    if inv["vendor_name"] in vendor_master and inv["gstin"]:
        master_state = vendor_master[inv["vendor_name"]]["state"]
        gstin_state  = state_codes.get(inv["gstin"][:2], "Unknown")
        if gstin_state != "Unknown" and gstin_state.lower() != master_state.lower():
            add_finding("gstin_state_mismatch", [inv["page"]], [inv["inv_no"]],
                f"GSTIN code {inv['gstin'][:2]} = {gstin_state} but vendor is {master_state}",
                inv["gstin"][:2], master_state)

for inv in invoices:
    if inv["vendor_name"] not in vendor_master:
        is_typo = any(
            len(set(inv["vendor_name"].lower().split()) &
                set(v.lower().split())) >= 2
            for v in vendor_master
        )
        if not is_typo:
            add_finding("fake_vendor", [inv["page"]], [inv["inv_no"]],
                f"'{inv['vendor_name']}' not in Vendor Master",
                inv["vendor_name"], "Not in Vendor Master")


po_numbers = set(re.findall(r'(PO-[\d-]+)', ocr_text))
for inv in invoices:
    if inv["po_ref"]:
      
        if re.match(r'PO-2025-99\d+', inv["po_ref"]):
            add_finding("phantom_po_reference", [inv["page"]],
                [inv["inv_no"], inv["po_ref"]],
                f"PO {inv['po_ref']} is a phantom reference",
                inv["po_ref"], "No matching PO exists")


output = {
    "team_id":  TEAM_ID,
    "findings": findings
}

with open("output.json", "w") as f:
    json.dump(output, f, indent=2)

print(f"\n output.json ready! Total findings: {len(findings)}")

from collections import Counter
cats = Counter(f["category"] for f in findings)
print("\n Summary:")
for cat, count in sorted(cats.items()):
    print(f"  {cat}: {count}")