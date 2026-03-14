
<p align="center">
<a href="https://apis.hyperbots.com/"><img src="https://images.g2crowd.com/uploads/vendor/image/1515319/9eadfb55dd882c428f4f82ee306dabcd.png" width="115"></a>
  <p align="center"><strong>HyperAPI: </strong>Stop Prompting, Start Programming Financial Intelligence.</p>
</p>
<p align="center">
  <a href="https://github.com/hyprbots/hyperapi-sdk"><img src="https://img.shields.io/badge/python-3.9+-blue.svg" alt="Python 3.9+"></a>
  <a href="https://github.com/hyprbots/hyperapi-sdk/blob/main/LICENSE"><img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License"></a>
</p>

---

**HyperAPI-SDK** is a document intelligence framework composed of Parse, Extract, Split(coming soon), Classify(coming soon), Layout(coming soon), Verify(coming soon), Omni(coming soon), Redact(coming soon), Summarise(coming soon), and Sheets(coming soon) APIs. Whether you are dealing with low-quality scans or complex multi-document binders, HyperAPI is engineered for production-grade reliability.

## Why Choose HyperAPI?

Commercial LLMs (GPT, Claude, Gemini) understand what they *see*. HyperAPI understands what's *correct*.

Real-World Case: The Billing Typo

```
Invoice Line Item:
  Date: 08/11/2025
  Activity: Hours
  Quantity: 0.15  ← Document shows "0.15" (typo for 0:15)
  Rate: 350.00
  Amount: 87.50

❌ Commercial LLMs: quantity = 0.15  (52.50 ≠ 87.50, math doesn't work)
✅ HyperAPI:        quantity = 0:15  (validates: 0.25 hrs × 350 = 87.50 ✓)
```

## Installation

```bash
pip install hyperapi
```

Or install from source:
```bash
git clone https://github.com/hyprbots/hyperapi-sdk
cd hyperapi-sdk
pip install -e .
```

## Quick Start

```python
from hyperapi import HyperAPIClient

# Works out of the box — default API key and URL are pre-configured
client = HyperAPIClient()

# Or supply your own key / URL explicitly:
# client = HyperAPIClient(api_key="your-key", base_url="https://your-hyperapi-url")

# You can also use environment variables:
#   export HYPERAPI_KEY="your-key"
#   export HYPERAPI_URL="https://your-hyperapi-url"

# Parse and extract a financial document in one call
result = client.process("invoice.png")

print(result["data"]["invoice_number"])  # e.g. "7816"
print(result["data"]["line_items"])      # Validated line items
print(result["data"]["total"])           # e.g. "$1,800.00"

# Always close the client when done (or use it as a context manager — see below)
client.close()
```

> **Tip:** Use `HyperAPIClient` as a context manager so it closes automatically:
> ```python
> with HyperAPIClient(api_key="your-key", base_url="https://your-hyperapi-url") as client:
>     result = client.process("invoice.png")
> ```

## Individual API Methods

For more control, call Parse, Extract, Classify, and Split separately.

### Parse — OCR a document to text

```python
result = client.parse("invoice.png")

# The response is an envelope — the OCR text is inside result["result"]["ocr"]
print(result["status"])              # "success"
print(result["task"])                # "parse"
print(result["model_used"])          # model name
print(result["duration_ms"])         # how long it took in milliseconds
print(result["result"]["ocr"])       # the extracted text from the document
```

### Extract — pull structured fields from a document

```python
result = client.extract("invoice.png")

# Structured fields are inside result["result"]
print(result["status"])
print(result["result"])              # dict with entities, line items, totals, etc.
```

### Classify — identify the document type

```python
result = client.classify("document.pdf")

print(result["result"]["document_type"])   # e.g. "invoice", "contract", "ID"
print(result["result"]["confidence"])      # confidence score
```

### Split — break a multi-document binder into segments

```python
result = client.split("binder.pdf")

segments = result["result"]["segments"]
for seg in segments:
    print(seg["document_type"], seg["pages"])
```

### Process — parse + extract in one call

`process()` uploads the file once and runs both Parse and Extract, saving a round-trip.

```python
result = client.process("invoice.png")

print(result["ocr"])    # raw OCR text (same as parse result["result"]["ocr"])
print(result["data"])   # structured fields (same as extract result["result"])
```

## API Reference

### `HyperAPIClient(api_key, base_url, timeout)`

| Parameter  | Type    | Default | Description |
|------------|---------|---------|-------------|
| `api_key`  | `str`   | pre-configured | Your HyperAPI key. Overrides the default if provided. Also reads `HYPERAPI_KEY` env var. |
| `base_url` | `str`   | pre-configured | API base URL. Overrides the default if provided. Also reads `HYPERAPI_URL` env var. |
| `timeout`  | `float` | `120.0` | Request timeout in seconds. |

### Methods

| Method | What you pass in | What you get back |
|--------|-----------------|-------------------|
| `parse(file_path)` | Path to a document file | Response envelope — OCR text at `result["result"]["ocr"]` |
| `extract(file_path)` | Path to a document file | Response envelope — structured fields at `result["result"]` |
| `classify(file_path)` | Path to a document file | Response envelope — document type at `result["result"]["document_type"]` |
| `split(file_path)` | Path to a document file | Response envelope — segments list at `result["result"]["segments"]` |
| `process(file_path)` | Path to a document file | `{"ocr": "...", "data": {...}}` — parse + extract combined |
| `close()` | — | Closes the HTTP connection. Call when done, or use `with` statement. |

### Response Envelope (parse, extract, classify, split)

Every method except `process()` returns the same envelope shape:

```python
{
    "status": "success",
    "request_id": "...",
    "task": "parse",           # "parse" | "extract" | "classify" | "split"
    "model_used": "...",
    "result": { ... },         # the actual output — differs per method
    "duration_ms": 1234,
    "metadata": {
        "filename": "...",
        "file_size": 12345,
        "org_id": "...",
        "tier": "..."
    }
}
```

### Supported File Formats

| Format | MIME type |
|--------|-----------|
| PNG | `image/png` |
| JPG / JPEG | `image/jpeg` |
| GIF | `image/gif` |
| WEBP | `image/webp` |
| TIFF / TIF | `image/tiff` |
| PDF | `application/pdf` |

### Exceptions

All exceptions live in `hyperapi.exceptions` and inherit from `HyperAPIError`.

| Exception | When it is raised |
|-----------|------------------|
| `AuthenticationError` | API key is missing or invalid (HTTP 401) |
| `DocumentUploadError` | The S3 presigned upload step failed |
| `ParseError` | `/v1/parse` returned an error or timed out |
| `ExtractError` | `/v1/extract` returned an error or timed out |
| `ClassifyError` | `/v1/classify` returned an error or timed out |
| `SplitError` | `/v1/split` returned an error or timed out |

```python
from hyperapi.exceptions import ParseError, AuthenticationError, DocumentUploadError

try:
    result = client.parse("invoice.png")
except AuthenticationError:
    print("Check your HYPERAPI_KEY")
except DocumentUploadError as e:
    print(f"Upload failed: {e}")
except ParseError as e:
    print(f"Parse failed (HTTP {e.status_code}): {e}")
```

## Tutorials

| Tutorial | Description |
|----------|-------------|
| [`tutorial/minimal_tutorial.py`](tutorial/minimal_tutorial.py) | Run parse, extract, classify, and split against the live API — no setup needed, default credentials built in |
| [`tutorial/The_Billing_Typo.ipynb`](tutorial/The_Billing_Typo.ipynb) | Compare HyperAPI vs GPT-4, Claude, Gemini on extraction task when typos are present |

## Papers

If you use **HyperAPI** or ideas related to its document intelligence and validation pipeline in your research, please cite the following papers:

```bibtex
@inproceedings{haq2026breaking,
  title={Breaking the annotation barrier with DocuLite: A scalable and privacy-preserving framework for financial document understanding},
  author={Haq, Saiful and Singh, Daman Deep and Bhat, Akshata A and Tamataam, Krishna Chaitanya Reddy and Khatri, Prashant and Nizami, Abdullah and Kaushik, Abhay and Chhaya, Niyati and Pandey, Piyush},
  booktitle={4th Deployable AI Workshop},
  year={2026}
}
```

```
@article{bhatsavior,
  title={SAVIOR: Sample-efficient Alignment of Vision-Language Models for OCR Representation},
  author={Bhat, Akshata A and Naganna, Sharath and Haq, Saiful and Khatri, Prashant and Arun, Neha and Chhaya, Niyati and Pandey, Piyush and Bhattacharyya, Pushpak}
}
```

## License

MIT License - see [LICENSE](LICENSE) for details.

## Links

- **GitHub**: [github.com/hyprbots/hyperapi-sdk](https://github.com/hyprbots/hyperapi-sdk)
