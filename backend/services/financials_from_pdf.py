import logging
import json
from groq import Groq
from config import GROQ_API_KEY, GROQ_PARSING_MODEL
from backend.models.parsed_financials import RawFinancialExtraction
from backend.services.pdf_text_extractor import extract_all_text
from pydantic import ValidationError

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = SYSTEM_PROMPT = """You are a financial data extraction assistant for SEC 10-K and 10-Q filings.

STATEMENT STRUCTURE — always identify which statement a line item comes from:
- Income Statement: revenue, operatingIncome, incomeTaxExpense, incomeBeforeTax
- Cash Flow Statement: changeInWorkingCapital, depreciationAndAmortization, 
  investmentsInPropertyPlantAndEquipment, acquisitionsNet
- Balance Sheet: accountsReceivable, inventory, accountsPayable, 
  cashAndCashEquivalents, shortTermDebt, longTermDebt

NEVER cross-contaminate: do not pull income statement values from the balance sheet 
or vice versa. Revenue is always the TOP line of the income statement — if the number 
you found for revenue is smaller than operatingIncome, you have made an error.

CRITICAL - Period Selection Rules:
- For 10-K filings: extract annual figures only
- For 10-Q filings: prefer "Year to Date" or longest available period (e.g. "Nine Months Ended" over "Three Months Ended"). NEVER mix quarterly and annual figures in the same array.
- For 10-Q Filings: If using "6 Months Ended Figures" multiply the revenue values by two before returning the JSON. 
- If only quarterly figures are available, use those consistently but note they are quarterly. IF THIS IS THE CASE, MULTIPLY EACH REVENUE VALUE BY 4 BEFORE RETURNING THE OUTPUT. 
- NEVER extract both quarterly AND year-to-date columns as separate periods

Extract ONLY raw numeric line items from the provided document text.
Return ONLY valid JSON matching the requested schema. No markdown, no explanation.
Everything MUST be in USD

Monetary values (revenue, income, expenses, debt, cash):
- Expand unit footnotes exactly once: "(in millions)" → multiply by 1,000,000; "(in thousands)" → multiply by 1,000.
- If values are already in full dollars, do NOT multiply.

sharesOutstanding (and ONLY sharesOutstanding):
- This is a share count, NOT a monetary value. NEVER apply any unit expansion to it.
- Return the raw number exactly as it appears in the filing (e.g. 24,400,000,000).
- If the filing states shares in millions (e.g. "24,400" with an "(in millions)" note), still expand it by 1,000,000 to get the full share count.

Lists must be ordered most recent period first, up to 5 periods.
Use null for missing array elements when a line item is not reported for that period.
"""

USER_PROMPT_TEMPLATE = """Extract raw financial line items from this filing text.

Return JSON with exactly these keys:
{{
  "revenue": [number, ...],
  "operatingIncome": [number, ...],
  "incomeTaxExpense": [number, ...],
  "incomeBeforeTax": [number, ...],
  "changeInWorkingCapital": [number, ...],
  "investmentsInPropertyPlantAndEquipment": [number, ...],
  "acquisitionsNet": [number, ...],
  "depreciationAndAmortization": [number, ...],
  "accountsReceivable": [number, ...],
  "inventory": [number, ...],
  "accountsPayable": [number, ...],
  "cashAndCashEquivalents": number,
  "shortTermDebt": number,
  "longTermDebt": number,
  "sharesOutstanding": number
}}

Rules:
- Up to 5 periods, most recent first, all period arrays same length.
- changeInWorkingCapital: from cash flow statement (changes in operating assets/liabilities).
- If missing, still populate accountsReceivable, inventory, accountsPayable per period for balance sheet fallback.
- cashAndCashEquivalents, shortTermDebt, longTermDebt: most recent period only.
- sharesOutstanding: weighted-average diluted shares from cover/EPS section (basic if diluted unavailable); 0 if not found.
- For 10-Q Filings: If using "6 Months Ended Figures" multiply the revenue values by two before returning the JSON. 
- If only quarterly figures are available, use those consistently but note they are quarterly. IF THIS IS THE CASE, MULTIPLY EACH REVENUE VALUE BY 4 BEFORE RETURNING THE OUTPUT. 
- All numeric values in the JSON must be plain numbers with no commas, currency symbols, 
or formatting (e.g. 416161000000, not 416,161,000,000 and not "$416B").

CRITICAL LINE ITEM DEFINITIONS — read before extracting (General Guidelines, not strict rules):
- "revenue": ONLY "Net sales", "Net revenue", "Total net revenue", "Total revenues", 
  or "Total net sales". NEVER use "Operating income", "Gross profit", "Total assets", 
  "Total liabilities", or any balance sheet item as revenue.
- "operatingIncome": The line explicitly labeled "Operating income" or "Income from operations".
  NEVER use revenue or gross profit as operating income.
- "incomeBeforeTax": The line labeled "Income before provision for income taxes", 
  "Earnings before income taxes", or equivalent. Must appear AFTER operating income on the 
  income statement.
- "incomeTaxExpense": The line labeled "Provision for income taxes" or "Income tax expense".
- "changeInWorkingCapital": From the CASH FLOW statement only — if it is here it will be under OPERATING ACTIVITIES.
   NOT from the balance sheet.
- "investmentsInPropertyPlantAndEquipment": From the CASH FLOW statement only, under the investment section, it could be labeled as
 "Investment in long term assets", "Capital expenditures", or "Investments in Plant Property and Equipment" 
 (it may not be these exactly but close to one of these)
 - "acquisitionsNet": From the CASH FLOW statement, under the investment section
- "depreciationAndAmortization": From the CASH FLOW statement, in the operating activities 
  section, labeled "Depreciation and amortization" or "Depreciation, depletion and amortization".
- "accountsReceivable", "inventory", "accountsPayable": From the BALANCE SHEET only.
- "cashAndCashEquivalents": From the BALANCE SHEET, most recent period only.
- "shortTermDebt": Current portion of long-term debt or short-term borrowings from the 
  BALANCE SHEET. Use 0 if not present.
- "longTermDebt": Long-term debt or long-term notes payable from the BALANCE SHEET, 
  most recent period only. Exclude current portion.
- "sharesOutstanding": Weighted-average DILUTED shares from the EPS section or cover page.

--- FINANCIAL STATEMENTS ---
{statement_text}

--- COVER / SHARES SECTION ---
{cover_text}
"""

ARRAY_FIELDS = [
    "revenue", "operatingIncome", "incomeTaxExpense", "incomeBeforeTax",
    "changeInWorkingCapital", "investmentsInPropertyPlantAndEquipment",
    "acquisitionsNet", "depreciationAndAmortization",
    "accountsReceivable", "inventory", "accountsPayable",
]

def _normalize_arrays(data: dict) -> dict:
    """Coerce any array field that came back as a scalar or None into a list."""
    for field in ARRAY_FIELDS:
        val = data.get(field)
        if val is None:
            data[field] = [None]
        elif not isinstance(val, list):
            data[field] = [val]
    return data

def extract_raw_financials(statement_text: str, cover_text: str) -> dict:
    if not GROQ_API_KEY:
        raise ValueError("GROQ_API_KEY is not set")

    client = Groq(api_key=GROQ_API_KEY)
    user_content = USER_PROMPT_TEMPLATE.format(
        statement_text=statement_text,
        cover_text=cover_text or "(no cover text extracted)",
    )

    logger.info("pdf_extraction_llm_request", extra={
        "event": "pdf_extraction_llm_request",
        "model": GROQ_PARSING_MODEL,
        "statement_text_chars": len(statement_text),
        "cover_text_chars": len(cover_text) if cover_text else 0,
    })

    response = client.chat.completions.create(
        model=GROQ_PARSING_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    )

    raw_content = response.choices[0].message.content
    finish_reason = response.choices[0].finish_reason

    logger.info("pdf_extraction_llm_response_received", extra={
        "event": "pdf_extraction_llm_response_received",
        "finish_reason": finish_reason,
        "response_chars": len(raw_content) if raw_content else 0,
        "raw_content_snippet": (raw_content or "")[:1000],
    })

    if finish_reason != "stop":
        logger.warning("pdf_extraction_unexpected_finish", extra={
            "event": "pdf_extraction_unexpected_finish",
            "finish_reason": finish_reason,
        })

    if not raw_content:
        logger.error("pdf_extraction_empty_response", extra={
            "event": "pdf_extraction_empty_response",
            "model": GROQ_PARSING_MODEL,
        })
        raise ValueError("LLM returned empty response")

    try:
        data = json.loads(raw_content)
    except json.JSONDecodeError as e:
        logger.error("pdf_extraction_json_parse_failed", extra={
            "event": "pdf_extraction_json_parse_failed",
            "error": str(e),
            "raw_content_snippet": raw_content[:500],
        })
        raise ValueError(f"LLM returned unparseable JSON: {e}") from e
    
    data = _normalize_arrays(data)

    logger.info("pdf_extraction_json_parsed", extra={
        "event": "pdf_extraction_json_parsed",
        "keys_present": list(data.keys()),
        "revenue_periods": len(data.get("revenue") or []),
        "shares_outstanding_raw": data.get("sharesOutstanding"),
        "cash_raw": data.get("cashAndCashEquivalents"),
    })

    try:
        validated = RawFinancialExtraction.model_validate(data)
    except ValidationError as e:
        try:
            raw_errors = e.errors()
            if isinstance(raw_errors, list):
                field_errors = "; ".join(
                    f"{'.'.join(str(l) for l in err['loc'])}: {err['msg']}"
                    for err in raw_errors if isinstance(err, dict) and 'loc' in err and 'msg' in err
                )
            else:
                field_errors = "Pydantic validation error format unexpected."
        except Exception:
            field_errors = "Could not cleanly stringify Pydantic validation payload."

        logger.error("pdf_extraction_validation_failed", extra={
            "event": "pdf_extraction_validation_failed",
            "validation_errors": str(e),  
            "keys_present": list(data.keys()),
            "field_errors_summary": field_errors,
        })
        raise ValueError(f"Extracted data failed validation — {field_errors}") from e

    logger.info("pdf_extraction_success", extra={
        "event": "pdf_extraction_success",
        "model": GROQ_PARSING_MODEL,
        "revenue_periods": len(validated.revenue or []),
        "revenue_most_recent": (validated.revenue or [None])[0],
        "shares_outstanding": validated.sharesOutstanding,
        "has_operating_income": validated.operatingIncome is not None,
        "has_cash": validated.cashAndCashEquivalents is not None,
    })

    return validated.model_dump()

def parse_financials_from_pdf(file) -> dict:
    result = extract_all_text(file)

    if not result or isinstance(result, bool):
        logger.error(
            "pdf_text_extraction_failed_at_source",
            extra={"event": "pdf_extraction_empty_or_boolean"}
        )
        raise ValueError("Could not extract text from the PDF. The file may be corrupt or empty.")

    statement_text, cover_text = result

    logger.info("pdf_text_extracted", extra={
        "event": "pdf_text_extracted",
        "statement_chars": len(statement_text),
        "cover_chars": len(cover_text),
        "statement_sample": statement_text[:2000],
        "cover_sample": cover_text[:500],
    })
    
    return extract_raw_financials(statement_text, cover_text)