#!/usr/bin/env python3
"""
Minimal tutorial for HyperAPI: parse, extract, classify, split.

No credentials needed — the SDK ships with default API key and endpoint.
Optionally override them via environment variables or --key / --url flags.

Usage:
    # Run all endpoints against a placeholder 1×1 PNG (just to confirm connectivity)
    python minimal_tutorial.py

    # Run against your own document
    python minimal_tutorial.py --doc path/to/invoice.pdf

    # Test a single endpoint
    python minimal_tutorial.py --doc invoice.pdf --endpoint parse

    # Override credentials if you have your own key
    python minimal_tutorial.py --key hk_live_... --url http://your-api-url

Endpoints tested:
    POST /v1/parse       — OCR document to text (S3 presigned upload)
    POST /v1/extract     — Structured field extraction from document file
    POST /v1/classify    — Document type classification
    POST /v1/split       — Multi-document binder splitting
"""

import argparse
import os
import sys
import json
import tempfile
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def section(title: str):
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def ok(msg: str):
    print(f"  [PASS] {msg}")


def fail(msg: str):
    print(f"  [FAIL] {msg}")


def info(msg: str):
    print(f"  [INFO] {msg}")


def pretty(data: dict, max_chars: int = 800) -> str:
    s = json.dumps(data, indent=2, default=str)
    if len(s) > max_chars:
        s = s[:max_chars] + "\n  ...(truncated)"
    return s


# ---------------------------------------------------------------------------
# Test functions
# ---------------------------------------------------------------------------

def test_parse(client, doc_path: Path) -> dict | None:
    """POST /v1/parse — upload document and get OCR text back."""
    section("1. PARSE  →  POST /v1/parse")
    info(f"Document: {doc_path}")

    from hyperapi.exceptions import ParseError, DocumentUploadError, AuthenticationError
    try:
        result = client.parse(doc_path)
        ok(f"Status: {result.get('status')}")
        ok(f"Task:   {result.get('task')}")
        ok(f"Model:  {result.get('model_used')}")
        ok(f"Time:   {result.get('duration_ms')} ms")
        ocr = result.get("result", {}).get("ocr", "")
        info(f"OCR preview (first 300 chars):\n{ocr[:300]}")
        return result
    except AuthenticationError as e:
        fail(f"Auth error — check your API key: {e}")
    except DocumentUploadError as e:
        fail(f"Upload failed: {e}")
    except ParseError as e:
        fail(f"Parse error (status {e.status_code}): {e}")
    except Exception as e:
        fail(f"Unexpected: {type(e).__name__}: {e}")
    return None


def test_extract(client, doc_path: Path) -> dict | None:
    """POST /v1/extract — structured field extraction from document file."""
    section("2. EXTRACT  →  POST /v1/extract")
    info(f"Document: {doc_path}")

    from hyperapi.exceptions import ExtractError, AuthenticationError
    try:
        result = client.extract(doc_path)
        ok(f"Status: {result.get('status')}")
        extraction = result.get("result", {})
        ok("Extracted result:")
        for k, v in extraction.items():
            print(f"    {k}: {v}")
        return result
    except AuthenticationError as e:
        fail(f"Auth error: {e}")
    except ExtractError as e:
        if e.status_code == 404:
            info("Endpoint not live yet. Skipping.")
        else:
            fail(f"Extract error (status {e.status_code}): {e}")
    except Exception as e:
        fail(f"Unexpected: {type(e).__name__}: {e}")
    return None


def test_classify(client, doc_path: Path) -> dict | None:
    """POST /v1/classify — identify document type."""
    section("3. CLASSIFY  →  POST /v1/classify")
    info(f"Document: {doc_path}")

    from hyperapi.exceptions import ClassifyError, AuthenticationError
    try:
        result = client.classify(doc_path)
        ok(f"Status: {result.get('status')}")
        ok(f"Document type: {result.get('result', {}).get('document_type')}")
        ok(f"Confidence:    {result.get('result', {}).get('confidence')}")
        info(pretty(result))
        return result
    except AuthenticationError as e:
        fail(f"Auth error: {e}")
    except ClassifyError as e:
        if e.status_code == 404:
            info("Endpoint not live yet. Skipping.")
        else:
            fail(f"Classify error (status {e.status_code}): {e}")
    except Exception as e:
        fail(f"Unexpected: {type(e).__name__}: {e}")
    return None


def test_split(client, doc_path: Path) -> dict | None:
    """POST /v1/split — split multi-document binder into individual docs."""
    section("4. SPLIT  →  POST /v1/split")
    info(f"Document: {doc_path}")

    from hyperapi.exceptions import SplitError, AuthenticationError
    try:
        result = client.split(doc_path)
        ok(f"Status:   {result.get('status')}")
        segments = result.get("result", {}).get("segments", [])
        ok(f"Segments: {len(segments)}")
        for i, seg in enumerate(segments):
            print(f"    [{i+1}] type={seg.get('document_type')}  pages={seg.get('pages')}")
        return result
    except AuthenticationError as e:
        fail(f"Auth error: {e}")
    except SplitError as e:
        if e.status_code == 404:
            info("Endpoint not live yet. Skipping.")
        else:
            fail(f"Split error (status {e.status_code}): {e}")
    except Exception as e:
        fail(f"Unexpected: {type(e).__name__}: {e}")
    return None


def test_health(client) -> bool:
    """GET /health — confirm the service is reachable."""
    section("0. HEALTH CHECK  →  GET /health")
    import httpx
    try:
        resp = client._client.get(f"{client.base_url}/health")
        if resp.status_code == 200:
            ok(f"Service reachable: {client.base_url}")
            info(pretty(resp.json()))
            return True
        else:
            fail(f"HTTP {resp.status_code}: {resp.text[:200]}")
    except httpx.RequestError as e:
        fail(f"Cannot reach {client.base_url}: {e}")
    return False


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="HyperAPI minimal tutorial")
    parser.add_argument(
        "--doc",
        default=None,
        help="Path to document (PDF/PNG/JPG). Defaults to a temp 1×1 PNG.",
    )
    parser.add_argument(
        "--skip-parse",
        action="store_true",
        help="Skip the parse test.",
    )
    parser.add_argument(
        "--endpoint",
        choices=["parse", "extract", "classify", "split", "all"],
        default="all",
        help="Which endpoint to test (default: all)",
    )
    parser.add_argument(
        "--key",
        default=None,
        help="Override the API key (optional — a default key is built in).",
    )
    parser.add_argument(
        "--url",
        default=None,
        help="Override the API base URL (optional — a default URL is built in).",
    )
    args = parser.parse_args()

    # --- SDK import ---
    try:
        from hyperapi import HyperAPIClient
    except ImportError:
        print("[ERROR] hyperapi-sdk not installed.")
        print("  Install: pip install -e /path/to/hyperapi-sdk")
        print("  Or:      pip install hyperapi")
        sys.exit(1)

    # --- Client ---
    # api_key and base_url fall back to built-in defaults when not provided.
    # Priority: --key/--url flag  >  HYPERAPI_KEY/HYPERAPI_URL env var  >  built-in default
    api_key = args.key or os.environ.get("HYPERAPI_KEY")
    base_url = args.url or os.environ.get("HYPERAPI_URL")

    client = HyperAPIClient(
        api_key=api_key if api_key else None,
        base_url=base_url if base_url else None,
    )

    print(f"\nHyperAPI Minimal Tutorial")
    print(f"  Base URL : {client.base_url}")
    print(f"  API Key  : {client.api_key[:12]}...")

    # --- Document ---
    if args.doc:
        doc_path = Path(args.doc)
        if not doc_path.exists():
            print(f"[ERROR] File not found: {doc_path}")
            sys.exit(1)
    else:
        # Create a tiny valid PNG (1×1 white pixel) as a fallback test file.
        # For real OCR quality tests, pass --doc invoice.pdf
        import struct, zlib
        def make_minimal_png() -> bytes:
            def chunk(name: bytes, data: bytes) -> bytes:
                c = name + data
                return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
            ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
            raw = b"\x00\xFF\xFF\xFF"
            idat = zlib.compress(raw)
            return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")

        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(make_minimal_png())
        tmp.close()
        doc_path = Path(tmp.name)
        info(f"No --doc provided. Using 1×1 placeholder PNG: {doc_path}")

    run_all = args.endpoint == "all"

    try:
        # Health check
        reachable = test_health(client)
        if not reachable:
            print("\n[WARN] Service unreachable. Network tests will fail.")

        # Parse
        if run_all or args.endpoint == "parse":
            if not args.skip_parse:
                test_parse(client, doc_path)

        # Extract
        if run_all or args.endpoint == "extract":
            test_extract(client, doc_path)

        # Classify
        if run_all or args.endpoint == "classify":
            test_classify(client, doc_path)

        # Split
        if run_all or args.endpoint == "split":
            test_split(client, doc_path)

    finally:
        client.close()
        # Clean up temp file if we created one
        if not args.doc and doc_path.exists():
            doc_path.unlink()

    section("Done")


if __name__ == "__main__":
    main()
