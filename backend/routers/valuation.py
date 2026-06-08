import logging
from fastapi import Request, APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from backend.models.assumptions import Assumptions
from backend.models.dcf_inputs import DCFInputs
from backend.services.dcf import DCF
from backend.services.wacc_lookup import get_wacc_by_industry
from config import DEFAULT_TERM_G, DEFAULT_RISKF_R, DEFAULT_NUM_YEARS
from backend.dependencies.rate_limit import limiter

logger = logging.getLogger(__name__)

router = APIRouter(tags=["valuation"])


class ParsedFinancials(BaseModel):
    """Subset of computed fields from /parse-pdf that the DCF model requires."""

    revenue: list[float] = Field(..., min_length=1)
    operatingMargin: list[float] = Field(..., min_length=1)
    taxRate: list[float] = Field(..., min_length=1)
    cash: float
    totalDebt: float
    sharesOutstanding: float


class ValuationRequest(BaseModel):
    """
    Body for POST /value.

    Pass the `parsed` dict from /parse-pdf and the `assumptions` dict
    from /generate-assumptions directly — no transformation required.
    """

    parsed: ParsedFinancials
    assumptions: Assumptions


class ValuationResponse(BaseModel):
    enterprise_value: float
    equity_value: float
    equity_value_per_share: float


@router.post(
    "/value",
    response_model=ValuationResponse,
    summary="Run DCF valuation",
    description=(
        "Combines the parsed financials from /parse-pdf and the LLM-generated "
        "assumptions from /generate-assumptions to produce an intrinsic value "
        "estimate via discounted cash flow analysis."
    ),
)
@limiter.limit("5/minute")
async def compute_valuation(request: Request, body: ValuationRequest) -> ValuationResponse:
    parsed = body.parsed
    assumptions = body.assumptions

    logger.info(
        "Valuation request received | industry=%s shares=%.0f rev_i=%.2f",
        assumptions.industry,
        parsed.sharesOutstanding,
        parsed.revenue[0],
    )

    # --- WACC lookup --------------------------------------------------------
    try:
        wacc_row = get_wacc_by_industry(assumptions.industry)
    except KeyError:
        logger.warning("WACC lookup failed | industry=%s", assumptions.industry)
        raise HTTPException(
            status_code=422,
            detail=f"Industry '{assumptions.industry}' not found in WACC dataset.",
        )

    logger.debug("WACC resolved | industry=%s wacc=%.4f", assumptions.industry, wacc_row["wacc"])

    # --- Assemble DCFInputs -------------------------------------------------
    try:
        inputs = DCFInputs(
            rev_i=parsed.revenue[0],
            beg_op_marg=parsed.operatingMargin[0],
            tax_r=parsed.taxRate[0],
            cash=parsed.cash,
            total_debt=parsed.totalDebt,
            shares_outstanding=parsed.sharesOutstanding,
            sterm_rev_g=assumptions.sterm_rev_g,
            lterm_rev_g=assumptions.lterm_rev_g,
            ending_op_marg=assumptions.ending_op_marg,
            reinvestment_r=assumptions.reinvestment_r,
            discount_r=wacc_row["wacc"],
            term_g=DEFAULT_TERM_G,
            riskf_r=DEFAULT_RISKF_R,
            num_years=DEFAULT_NUM_YEARS,
        )
    except ValueError as exc:
        logger.warning("DCFInputs validation failed | error=%s", exc)
        raise HTTPException(status_code=422, detail=str(exc))

    # --- Run DCF model ------------------------------------------------------
    try:
        result = DCF(inputs)
    except ValueError as exc:
        logger.warning("DCF model rejected inputs | error=%s", exc)
        raise HTTPException(status_code=422, detail=str(exc))
    except Exception as exc:
        logger.exception("Unexpected error during DCF computation")
        raise HTTPException(status_code=500, detail=f"DCF computation failed: {exc}")

    logger.info(
        "Valuation complete | ev=%.2f equity=%.2f per_share=%.4f",
        result["enterprise_value"],
        result["equity_value"],
        result["equity_value_per_share"],
    )

    return ValuationResponse(
        enterprise_value=result["enterprise_value"],
        equity_value=result["equity_value"],
        equity_value_per_share=result["equity_value_per_share"],
    )