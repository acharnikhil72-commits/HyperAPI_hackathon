"""
HyperAPI Client
"""

import os
import uuid
from pathlib import Path
from typing import Union, Optional

import httpx

from .exceptions import AuthenticationError, ParseError, ExtractError, ClassifyError, SplitError, DocumentUploadError


CONTENT_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".tiff": "image/tiff",
    ".tif": "image/tiff",
    ".pdf": "application/pdf",
}


class HyperAPIClient:
    """
    Client for interacting with HyperAPI.

    Usage:
        from hyperapi import HyperAPIClient

        client = HyperAPIClient(api_key="your-api-key")

        # Parse a document (uses presigned S3 upload by default)
        result = client.parse("invoice.png")
        print(result["result"]["ocr"])

        # Extract structured fields (entities + line items)
        fields = client.extract("invoice.png")
        print(fields["result"])
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: float = 120.0
    ):
        """
        Initialize HyperAPI client.

        Args:
            api_key: API key for authentication. If not provided, reads from
                     HYPERAPI_KEY environment variable.
            base_url: Base URL for the API. If not provided, reads from
                      HYPERAPI_URL environment variable.
            timeout: Request timeout in seconds (default: 120s).
        """
        self.api_key = api_key or os.environ.get("HYPERAPI_KEY") or "hk_live_9015f91550d87dbf23f73f5baea68d5d"
        if not self.api_key:
            raise AuthenticationError(
                "API key required. Pass api_key or set HYPERAPI_KEY environment variable."
            )

        self.base_url = (
            base_url
            or os.environ.get("HYPERAPI_URL")
            or "http://hyperapi-production-12097051.us-east-1.elb.amazonaws.com"
        )
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def _get_headers(self) -> dict:
        """Get request headers with API key and a unique request ID for tracing."""
        return {
            "X-API-Key": self.api_key,
            "X-Request-ID": str(uuid.uuid4()),
        }

    def upload_document(
        self,
        file_path: Union[str, Path],
        content_type: Optional[str] = None,
    ) -> str:
        """
        Upload a document to S3 via the presigned URL flow and return its document_key.

        This executes steps 1 and 2 of the 3-step upload flow:
          1. POST /v1/documents/upload  → {document_key, upload_url, expires_in}
          2. PUT {upload_url}           → file bytes direct to S3 (never through Kong)

        The returned document_key is then passed to parse() (step 3).

        Args:
            file_path: Path to the file to upload.
            content_type: MIME type. Auto-detected from file extension if not provided.

        Returns:
            document_key string (UUID) to use in subsequent parse/inference calls.

        Raises:
            FileNotFoundError: If the file does not exist.
            DocumentUploadError: If the presigned URL request or S3 PUT fails.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        if content_type is None:
            content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")

        # Step 1 — get presigned upload URL
        try:
            resp = self._client.post(
                f"{self.base_url}/v1/documents/upload",
                json={"filename": path.name, "content_type": content_type},
                headers=self._get_headers(),
            )
        except httpx.RequestError as e:
            raise DocumentUploadError(f"Failed to get upload URL: {str(e)}")

        if resp.status_code == 401:
            raise AuthenticationError("Invalid API key", status_code=401)
        if resp.status_code != 200:
            raise DocumentUploadError(
                f"Upload URL request failed: {resp.text}",
                status_code=resp.status_code,
            )

        upload_data = resp.json()
        document_key = upload_data["document_key"]
        upload_url = upload_data["upload_url"]

        # Step 2 — PUT file bytes directly to S3
        # The presigned URL signs x-amz-server-side-encryption — must be included or S3 returns 403.
        try:
            with open(path, "rb") as f:
                s3_resp = self._client.put(
                    upload_url,
                    content=f.read(),
                    headers={
                        "Content-Type": content_type,
                        "x-amz-server-side-encryption": "AES256",
                    },
                )
        except httpx.RequestError as e:
            raise DocumentUploadError(f"S3 upload failed: {str(e)}")

        if s3_resp.status_code != 200:
            raise DocumentUploadError(
                f"S3 PUT failed (status {s3_resp.status_code}). "
                "Ensure x-amz-server-side-encryption: AES256 is present — "
                "the presigned URL signs this header as required.",
                status_code=s3_resp.status_code,
            )

        return document_key

    def parse(
        self,
        file_path: Union[str, Path] = None,
        *,
        image_path: Union[str, Path] = None,
        use_presigned: bool = True,
    ) -> dict:
        """
        Parse a document using OCR.

        By default uses the presigned S3 upload flow (recommended — no Kong size limit):
          1. Uploads the file to S3 via upload_document().
          2. Calls POST /v1/parse with the returned document_key.

        Set use_presigned=False to send the file directly as multipart (max 50 MB,
        passes through Kong — use only for small files or local dev).

        Args:
            file_path: Path to the file (PDF, PNG, JPG, WEBP, TIFF, GIF).
            image_path: Deprecated alias for file_path (backward compatibility).
            use_presigned: If True (default), upload via S3 presigned URL flow.
                           If False, send file as multipart directly to /v1/parse.

        Returns:
            Full response envelope:
            {
                "status": "success",
                "request_id": "...",
                "task": "parse",
                "model_used": "hyperbots_vlm_ocr",
                "result": {"ocr": "<extracted text>"},
                "duration_ms": 1234,
                "metadata": {"filename": ..., "file_size": ..., "org_id": ..., "tier": ...}
            }

        Raises:
            FileNotFoundError: If file doesn't exist.
            AuthenticationError: If API key is invalid.
            DocumentUploadError: If presigned upload fails (use_presigned=True only).
            ParseError: If parsing fails or times out.
        """
        path = file_path or image_path
        if path is None:
            raise ValueError("file_path is required")

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        try:
            if use_presigned:
                # Preferred path: upload to S3 first, then parse with document_key
                content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
                document_key = self.upload_document(path, content_type=content_type)
                response = self._client.post(
                    f"{self.base_url}/v1/parse",
                    data={"document_key": document_key},
                    headers=self._get_headers(),
                )
            else:
                # Legacy path: multipart upload direct through Kong (50 MB cap)
                content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
                with open(path, "rb") as f:
                    files = {"file": (path.name, f, content_type)}
                    response = self._client.post(
                        f"{self.base_url}/v1/parse",
                        files=files,
                        headers=self._get_headers(),
                    )

            if response.status_code == 401:
                raise AuthenticationError("Invalid API key", status_code=401)

            if response.status_code != 200:
                raise ParseError(
                    f"Parse failed: {response.text}",
                    status_code=response.status_code,
                )

            return response.json()

        except (AuthenticationError, ParseError, DocumentUploadError):
            raise
        except httpx.TimeoutException:
            raise ParseError("Request timed out", status_code=504)
        except httpx.RequestError as e:
            raise ParseError(f"Request failed: {str(e)}")

    def extract(
        self,
        file_path: Union[str, Path],
        *,
        use_presigned: bool = True,
    ) -> dict:
        """
        Extract structured data from a document (entities + line items).

        Mirrors the parse() upload flow: uploads the file to S3 first, then
        calls POST /v1/extract with the returned document_key. The router runs
        its own OCR pipeline and returns both entities and line items in one call.

        Args:
            file_path: Path to the file (PDF, PNG, JPG, WEBP, TIFF).
            use_presigned: If True (default), upload via S3 presigned URL flow.
                           If False, send file as multipart directly to /v1/extract.

        Returns:
            Full response envelope with result.entities and result.line_items.

        Raises:
            FileNotFoundError: If file doesn't exist.
            AuthenticationError: If API key is invalid.
            DocumentUploadError: If presigned upload fails (use_presigned=True only).
            ExtractError: If extraction fails or times out.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        try:
            if use_presigned:
                content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
                document_key = self.upload_document(path, content_type=content_type)
                response = self._client.post(
                    f"{self.base_url}/v1/extract",
                    data={"document_key": document_key},
                    headers=self._get_headers(),
                    timeout=600.0,
                )
            else:
                content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
                with open(path, "rb") as f:
                    files = {"file": (path.name, f, content_type)}
                    response = self._client.post(
                        f"{self.base_url}/v1/extract",
                        files=files,
                        headers=self._get_headers(),
                        timeout=600.0,
                    )

            if response.status_code == 401:
                raise AuthenticationError("Invalid API key", status_code=401)

            if response.status_code != 200:
                raise ExtractError(
                    f"Extract failed: {response.text}",
                    status_code=response.status_code,
                )

            return response.json()

        except (AuthenticationError, ExtractError, DocumentUploadError):
            raise
        except httpx.TimeoutException:
            raise ExtractError("Request timed out", status_code=504)
        except httpx.RequestError as e:
            raise ExtractError(f"Request failed: {str(e)}")

    def classify(
        self,
        file_path: Union[str, Path],
        *,
        use_presigned: bool = True,
    ) -> dict:
        """
        Classify a document type (invoice, contract, ID, etc.).

        Uploads the file to S3 first, then calls POST /v1/classify with the
        returned document_key.

        Args:
            file_path: Path to the file (PDF, PNG, JPG, WEBP, TIFF).
            use_presigned: If True (default), upload via S3 presigned URL flow.
                           If False, send file as multipart directly to /v1/classify.

        Returns:
            Full response envelope with result.label, result.confidence, etc.

        Raises:
            FileNotFoundError: If file doesn't exist.
            AuthenticationError: If API key is invalid.
            DocumentUploadError: If presigned upload fails (use_presigned=True only).
            ClassifyError: If classification fails or times out.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        try:
            if use_presigned:
                content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
                document_key = self.upload_document(path, content_type=content_type)
                response = self._client.post(
                    f"{self.base_url}/v1/classify",
                    data={"document_key": document_key},
                    headers=self._get_headers(),
                )
            else:
                content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
                with open(path, "rb") as f:
                    files = {"file": (path.name, f, content_type)}
                    response = self._client.post(
                        f"{self.base_url}/v1/classify",
                        files=files,
                        headers=self._get_headers(),
                    )

            if response.status_code == 401:
                raise AuthenticationError("Invalid API key", status_code=401)

            if response.status_code != 200:
                raise ClassifyError(
                    f"Classify failed: {response.text}",
                    status_code=response.status_code,
                )

            return response.json()

        except (AuthenticationError, ClassifyError, DocumentUploadError):
            raise
        except httpx.TimeoutException:
            raise ClassifyError("Request timed out", status_code=504)
        except httpx.RequestError as e:
            raise ClassifyError(f"Request failed: {str(e)}")

    def split(
        self,
        file_path: Union[str, Path],
        *,
        use_presigned: bool = True,
    ) -> dict:
        """
        Split a multi-document binder into individual document segments.

        Uploads the file to S3 first, then calls POST /v1/split with the
        returned document_key.

        Args:
            file_path: Path to the file (PDF, PNG, JPG, WEBP, TIFF).
            use_presigned: If True (default), upload via S3 presigned URL flow.
                           If False, send file as multipart directly to /v1/split.

        Returns:
            Full response envelope with result.segments list.

        Raises:
            FileNotFoundError: If file doesn't exist.
            AuthenticationError: If API key is invalid.
            DocumentUploadError: If presigned upload fails (use_presigned=True only).
            SplitError: If splitting fails or times out.
        """
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        try:
            if use_presigned:
                content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
                document_key = self.upload_document(path, content_type=content_type)
                response = self._client.post(
                    f"{self.base_url}/v1/split",
                    data={"document_key": document_key},
                    headers=self._get_headers(),
                )
            else:
                content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
                with open(path, "rb") as f:
                    files = {"file": (path.name, f, content_type)}
                    response = self._client.post(
                        f"{self.base_url}/v1/split",
                        files=files,
                        headers=self._get_headers(),
                    )

            if response.status_code == 401:
                raise AuthenticationError("Invalid API key", status_code=401)

            if response.status_code != 200:
                raise SplitError(
                    f"Split failed: {response.text}",
                    status_code=response.status_code,
                )

            return response.json()

        except (AuthenticationError, SplitError, DocumentUploadError):
            raise
        except httpx.TimeoutException:
            raise SplitError("Request timed out", status_code=504)
        except httpx.RequestError as e:
            raise SplitError(f"Request failed: {str(e)}")

    def process(self, file_path: Union[str, Path] = None, *, image_path: Union[str, Path] = None) -> dict:
        """
        Parse and extract in one call. Uploads the document once and reuses
        the document_key for both operations.

        Args:
            file_path: Path to the file (PDF, PNG, JPG, etc.)
            image_path: Deprecated alias for file_path (backward compatibility)

        Returns:
            dict with keys:
                - ocr: Raw OCR text from parse
                - data: Extracted structured fields from extract
        """
        path = file_path or image_path
        if path is None:
            raise ValueError("file_path is required")

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        content_type = CONTENT_TYPES.get(path.suffix.lower(), "application/octet-stream")
        document_key = self.upload_document(path, content_type=content_type)

        parse_response = self._client.post(
            f"{self.base_url}/v1/parse",
            data={"document_key": document_key},
            headers=self._get_headers(),
        )
        if parse_response.status_code != 200:
            raise ParseError(f"Parse failed: {parse_response.text}", status_code=parse_response.status_code)

        extract_response = self._client.post(
            f"{self.base_url}/v1/extract",
            data={"document_key": document_key},
            headers=self._get_headers(),
            timeout=600.0,
        )
        if extract_response.status_code != 200:
            raise ExtractError(f"Extract failed: {extract_response.text}", status_code=extract_response.status_code)

        parse_result = parse_response.json()
        extract_result = extract_response.json()

        return {
            "ocr": parse_result["result"]["ocr"],
            "data": extract_result.get("result", {}),
        }

    def close(self):
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
