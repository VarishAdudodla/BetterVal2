import logging
import io
import time
from fastapi import APIRouter, HTTPException, status, UploadFile, File, Request
from groq import GroqError
from backend.models.assumptions import GenerateAssumptionsRequest
from backend.services.financials_from_pdf import parse_financials_from_pdf
from backend.services.generate_assumptions import get_assumptions
from backend.dependencies.rate_limit import limiter


logger = logging.getLogger(__name__)

router = APIRouter(tags=["assumptions"])

@router.post("/generate-assumptions")
@limiter.limit("5/minute")
async def generate_assumptions(request: Request, body: GenerateAssumptionsRequest):
    start = time.monotonic()

    try:
        assumptions = await get_assumptions(
            parsed=body.parsed,
            description=body.description or "",
            industry=body.industry,
        )

        logger.info(
            "generate_assumptions_success",
            extra={
                "event": "assumptions_success",
                "industry": body.industry,
                "duration_ms": round((time.monotonic() - start) * 1000),
            },
        )
        return {"assumptions": assumptions}

    except ValueError as e:
        logger.warning(
            "generate_assumptions_value_error",
            extra={
                "event": "assumptions_value_error",
                "error": str(e),
                "duration_ms": round((time.monotonic() - start) * 1000),
            },
        )
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    except GroqError as e:
        logger.error(
            "generate_assumptions_upstream_failure",
            extra={
                "event": "assumptions_upstream_error",
                "error": str(e),
                "duration_ms": round((time.monotonic() - start) * 1000),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="The AI failed to generate assumptions. Please try again.",
        )

    except Exception as e:
        logger.error(
            "generate_assumptions_unexpected_error",
            extra={
                "event": "assumptions_system_error",
                "error": str(e),
                "duration_ms": round((time.monotonic() - start) * 1000),
            },
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected internal server error occurred while generating assumptions.",
        )