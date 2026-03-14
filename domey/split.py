from pypdf import PdfReader, PdfWriter

def split_pdf(input_pdf, output_pdf, start_page, end_page):
    reader = PdfReader(input_pdf)
    writer = PdfWriter()
    for page_num in range(start_page - 1, end_page):
        writer.add_page(reader.pages[page_num])
    with open(output_pdf, "wb") as f:
        writer.write(f)
    print(f" {output_pdf} created! (pages {start_page}-{end_page})")

split_pdf("gauntlet.pdf", "vendor_master.pdf",  1,   4)
split_pdf("gauntlet.pdf", "invoices.pdf",        5,   650)
split_pdf("gauntlet.pdf", "purchase_orders.pdf", 651, 750)
split_pdf("gauntlet.pdf", "bank_statements.pdf", 751, 850)
split_pdf("gauntlet.pdf", "expense_reports.pdf", 851, 1000)

print("\n All splits done!")