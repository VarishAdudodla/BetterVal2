from fastapi import HTTPException, Request, UploadFile, status
import os
import re

MAX_PDF_BYTES = 10 * 1024 * 1024
_CHUNK_SIZE = 256 * 1024
_SIZE_ERROR_DETAIL = "File must be under 10MB. Please upload a smaller 10-K, preferably just the financials."
_DISABLE_SIZE_LIMIT = os.environ.get("DISABLE_SIZE_LIMIT", "false").lower() == "true"


def _too_large() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        detail=_SIZE_ERROR_DETAIL,
    )


def check_content_length(request: Request, max_bytes: int = MAX_PDF_BYTES) -> None:
    if _DISABLE_SIZE_LIMIT:
        return
    cl = request.headers.get("content-length")
    if cl and int(cl) > max_bytes:
        raise _too_large()


async def read_capped(file: UploadFile, max_bytes: int = MAX_PDF_BYTES) -> bytes:
    if _DISABLE_SIZE_LIMIT:
        return await file.read()
    
    chunks: list[bytes] = []
    total = 0

    while True:
        chunk = await file.read(_CHUNK_SIZE)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise _too_large()
        chunks.append(chunk)

    return b"".join(chunks)

def _is_toc_page(text: str) -> bool:
    # TOC pages have keywords but content is mostly tabs/page numbers, not financial data
    # A real financial statement page will have many numeric values
    number_count = len(re.findall(r'\b\d{2,}\b', text))
    return number_count < 10  # tune this threshold as needed