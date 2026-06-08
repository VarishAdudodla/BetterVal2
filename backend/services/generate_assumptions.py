import json
import logging
import os
from groq import AsyncGroq  
from pydantic import ValidationError
from backend.models.assumptions import Assumptions
from backend.services.wacc_lookup import get_industries
from config import GROQ_ASSUMPTIONS_MODEL

_api_key = os.getenv("GROQ_API_KEY")
if not _api_key:
    raise RuntimeError("GROQ_API_KEY is not set")

client = AsyncGroq(api_key=_api_key)
_INDUSTRIES = get_industries()
_INDUSTRIES_SET = {i.lower() for i in _INDUSTRIES}

logger = logging.getLogger(__name__)

async def get_assumptions(parsed: dict, description: str, industry: str) -> dict:

    user_content = f"""
            Company description: {description}
            Industry: {industry}
            Historical financials (First numbers in each list are the most recent):
            {json.dumps(parsed, indent=2)}

            Available industries (you MUST pick the single closest match exactly as written, no explanations):
            {_INDUSTRIES}

            Generate 10-year forward assumptions in this exact schema:
            {{
            "sterm_rev_g": <short term revenue growth rate, e.g. 0.12>,
            "lterm_rev_g": <long term revenue growth rate, e.g. 0.05>,
            "ending_op_marg": <target operating margin at the final year of the forcast, e.g. 0.20>,
            "reinvestment_r": <reinvestment rate, e.g. 0.30>,
            "industry": "<exact industry name from the list above>"
            }}
            """

    logger.info("assumptions_llm_request", extra={
        "event": "assumptions_llm_request",
        "model": GROQ_ASSUMPTIONS_MODEL,
        "industry": industry,
        "has_description": bool(description),
        "parsed_keys": list(parsed.keys()),
    })

    response = await client.chat.completions.create(
        model=GROQ_ASSUMPTIONS_MODEL,
        temperature=0.5,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": """You are a financial analyst performing a DCF valuation.

            You must:
            - Return ONLY valid JSON
            - No markdown
            - No explanation
            - Follow the schema exactly
            - For companies in tech / semiconductor be moderately agressive with your assumptions (High growth, High reinvestment, High Margin)
            - If a non-empty description is provided below, it represents critical qualitative context that must override or modify your standard extraction and calculation rules. Read this description carefully and factor it into your output assumptions:
            - Normalization & Adjustments: If the description notes one-off, non-recurring items (e.g., restructuring costs, legal settlements, or asset sales), normalize the relevant line items (like `operatingIncome`) by backing out these one-off figures.
            - Contextual Scaling: If the description clarifies specific period details, unit oddities, or corporate events (such as stock splits impacting `sharesOutstanding`), use this information to resolve ambiguities in the raw text.
            - Only use a negative reinvestment rate if you believe the company is declining and will be forever (This happens in cases where a company / industry is shrinking), this will usually accompany a negative long-term revenue growth rate
            - If you project that a company is growing (lterm_rev_g > 0) it MUST a positive reinvestment rate (reinvestment_r > 0)
            """
            },
            {
                "role": "user",
                "content": user_content,
            }
        ],
    )

    raw = response.choices[0].message.content
    finish_reason = response.choices[0].finish_reason

    logger.info("assumptions_llm_response_received", extra={
        "event": "assumptions_llm_response_received",
        "finish_reason": finish_reason,
        "response_chars": len(raw) if raw else 0,
        "raw_content_snippet": (raw or "")[:500],
    })

    if finish_reason != "stop":
        logger.warning("assumptions_truncated_response", extra={
            "event": "assumptions_truncated_response",
            "finish_reason": finish_reason,
        })

    if not raw or not raw.strip():
        logger.error("assumptions_empty_response", extra={
            "event": "assumptions_empty_response",
            "model": GROQ_ASSUMPTIONS_MODEL,
            "industry": industry,
        })
        raise ValueError("LLM returned empty response for assumptions")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.error("assumptions_json_parse_failed", extra={
            "event": "assumptions_json_parse_failed",
            "error": str(e),
            "raw_content_snippet": raw[:500],
        })
        raise ValueError(f"LLM returned unparseable JSON for assumptions: {e}") from e

    logger.info("assumptions_json_parsed", extra={
        "event": "assumptions_json_parsed",
        "keys_present": list(data.keys()),
        "industry_returned": data.get("industry"),
        "sterm_rev_g": data.get("sterm_rev_g"),
        "lterm_rev_g": data.get("lterm_rev_g"),
        "ending_op_marg": data.get("ending_op_marg"),
        "reinvestment_r": data.get("reinvestment_r"),
    })

    returned_industry = data.get("industry", "")
    if returned_industry.lower() not in _INDUSTRIES_SET:
        logger.error("assumptions_invalid_industry", extra={
            "event": "assumptions_invalid_industry",
            "industry_returned": returned_industry,
        })
        raise ValueError(f"LLM returned unknown industry: '{returned_industry}'")

    try:
        validated = Assumptions.model_validate(data)
    except ValidationError as e:
        field_errors = "; ".join(
            f"{'.'.join(str(l) for l in err['loc'])}: {err['msg']}"
            for err in e.errors()
        )
        logger.error("assumptions_validation_failed", extra={
            "event": "assumptions_validation_failed",
            "validation_errors": e.errors(),
            "keys_present": list(data.keys()),
            "field_errors_summary": field_errors,
        })
        raise ValueError(f"Assumptions failed validation — {field_errors}") from e

    logger.info("assumptions_success", extra={
        "event": "assumptions_success",
        "model": GROQ_ASSUMPTIONS_MODEL,
        "industry": validated.industry,
        "sterm_rev_g": validated.sterm_rev_g,
        "lterm_rev_g": validated.lterm_rev_g,
        "ending_op_marg": validated.ending_op_marg,
        "reinvestment_r": validated.reinvestment_r,
    })

    return validated.model_dump()