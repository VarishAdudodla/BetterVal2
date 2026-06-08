import logging
import io
import time
from fastapi import APIRouter, HTTPException, status, UploadFile, File, Request
from groq import GroqError
from backend.services.financials_from_pdf import parse_financials_from_pdf
from backend.dependencies.rate_limit import limiter
from backend.utils.upload import check_content_length, read_capped

logger = logging.getLogger(__name__)

router = APIRouter(tags=["pdf"])

@router.post("/parse-pdf")
@limiter.limit("5/minute")
async def parse_pdf(request: Request, file: UploadFile = File(...)):
    start = time.monotonic()

    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File must be a PDF",
        )

    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="File must be a PDF",
        )

    check_content_length(request)
    contents = await read_capped(file)

    try:
        parsed = parse_financials_from_pdf(io.BytesIO(contents))

        logger.info(
            "pdf_parse_success",
            extra={
                "event": "pdf_success",
                "file_size_bytes": len(contents),
                "duration_ms": round((time.monotonic() - start) * 1000),
            },
        )
        return {"parsed": parsed}

    except ValueError as e:
        logger.warning(
            "pdf_parse_value_error",
            extra={
                "event": "pdf_value_error",
                "error": str(e),
                "duration_ms": round((time.monotonic() - start) * 1000),
            },
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    except GroqError as e:
        logger.error(
            "pdf_parse_upstream_failure",
            extra={
                "event": "pdf_upstream_error",
                "error": str(e),
                "duration_ms": round((time.monotonic() - start) * 1000),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI parser failed to extract structured data from the document. Please try again.",
        )

    except Exception as e:
        import traceback
        traceback.print_exc()
        logger.error(
            "pdf_parse_unexpected_error",
            extra={
                "event": "pdf_system_error",
                "error": str(e),
                "duration_ms": round((time.monotonic() - start) * 1000),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal server error occurred while analyzing the PDF structure.",
        )
