# BetterVal Backend — LLM Context Document

## Overview

BetterVal is a DCF (Discounted Cash Flow) valuation web app. The backend is a **FastAPI** application deployed on **Railway**, written in Python. It exposes a REST API consumed by a React + Vite frontend deployed on **Vercel**.

The core user flow is:
1. User uploads a 10-K or 10-Q PDF → backend extracts financial data via LLM
2. Backend computes derived financial metrics from the raw extraction
3. User provides company description + industry → backend generates forward-looking DCF assumptions via LLM
4. Frontend assembles all inputs and sends them to the valuation endpoint → backend runs the DCF model and returns intrinsic value

---

## Project Structure

```
BetterVal2/
├── main.py                          # FastAPI app entry point
├── config.py                        # Env vars and constants
├── data/
│   └── wacc.xls                     # Damodaran industry WACC dataset
├── backend/
│   ├── routers/
│   │   ├── pdf.py                   # POST /parse-pdf
│   │   └── assumptions.py           # POST /generate-assumptions
│   ├── services/
│   │   ├── financials_from_pdf.py   # LLM extraction (OpenRouter)
│   │   ├── pdf_text_extractor.py    # PyMuPDF text extraction
│   │   ├── calculate_fperformance.py # Derived metric computation
│   │   ├── generate_assumptions.py  # LLM assumption generation (Groq)
│   │   ├── dcf.py                   # DCF model
│   │   └── wacc_lookup.py           # Damodaran WACC dataset lookup
│   ├── models/
│   │   ├── parsed_financials.py     # RawFinancialExtraction (Pydantic)
│   │   ├── assumptions.py           # Assumptions + GenerateAssumptionsRequest (Pydantic)
│   │   └── dcf_inputs.py            # DCFInputs (dataclass)
│   ├── dependencies/
│   │   └── rate_limit.py            # slowapi Limiter
│   └── utils/
│       ├── upload.py                # File size checks, _is_toc_page
│       └── financial_helpers.py     # _get_list, _get_optional_list, _resolve_change_in_wc, etc.
```

---

## Config (`config.py`)

All values loaded from environment variables via `python-dotenv`:

| Variable | Default | Purpose |
|---|---|---|
| `GROQ_API_KEY` | — | Groq API key (assumption generation) |
| `GROQ_ASSUMPTIONS_MODEL` | `llama-3.3-70b-versatile` | Model for assumption generation |
| `OPENROUTER_API_KEY` | — | OpenRouter key (PDF financial extraction) |
| `STATEMENT_TEXT_MAX_CHARS` | `20000` | Max chars sent to LLM from PDF |
| `COVER_PAGES_MAX` | `5` | Max pages scanned for shares/cover data |
| `DEFAULT_TERM_G` | `0.03` | Default terminal growth rate |
| `DEFAULT_RISKF_R` | `0.05` | Default risk-free rate |
| `DEFAULT_NUM_YEARS` | `10` | DCF projection years |
| `DEFAULT_TAX_RATE` | `0.25` | Fallback tax rate |

---

## Data Flow

### Endpoint 1 — `POST /parse-pdf`

**Router:** `backend/routers/pdf.py`  
**Rate limit:** 5/minute  
**Input:** `multipart/form-data` with a `.pdf` file (max 10MB)

```
User uploads PDF
    │
    ▼
pdf.py (router)
    │  validates extension + content-type
    │  check_content_length() — early reject if Content-Length header > 10MB
    │  read_capped() — streams file in 256KB chunks, hard-stops at 10MB
    │
    ▼
financials_from_pdf.parse_financials_from_pdf(file: BytesIO)
    │
    ├─► pdf_text_extractor.extract_all_text(file)
    │       PyMuPDF (fitz) opens the PDF stream
    │       Pages extracted in parallel (ThreadPoolExecutor) if > 15 pages
    │       Each page classified:
    │         - _is_toc_page(text): skips pages with < 10 numeric tokens (avoids TOC pages)
    │         - STATEMENT_KEYWORDS match → added to statement_text (up to STATEMENT_TEXT_MAX_CHARS)
    │         - COVER_KEYWORDS match in early pages → added to cover_text (up to 4000 chars)
    │       Returns: (statement_text: str, cover_text: str)
    │
    ├─► financials_from_pdf.extract_raw_financials(statement_text, cover_text)
    │       Calls OpenRouter API (model: configurable, currently openai/gpt-oss-20b:free)
    │       System prompt: instructs LLM on statement structure, period rules, unit expansion
    │       User prompt: injects statement_text + cover_text, requests JSON with 14 fields
    │       Response parsed with json.loads()
    │       _normalize_arrays(): coerces scalar/None fields to lists
    │       Validated against RawFinancialExtraction (Pydantic)
    │       Returns: validated.model_dump() — raw dict with 14 keys
    │
    ▼
calculate_fperformance.compute_from_raw(raw: dict)
    │   Computes derived metrics from the raw extraction:
    │     - operatingMargin = operatingIncome / revenue (per period)
    │     - revenueGrowth = (rev[i] - rev[i+1]) / rev[i+1] (YoY, up to 4 growth rates)
    │     - taxRate = incomeTaxExpense / incomeBeforeTax (safe_tax_rate handles edge cases)
    │     - reinvestmentRate = (ΔWC - capex - acquisitions - D&A) / NOPAT
    │         ΔWC always computed from balance sheet: AR + Inventory - AP (current vs prior period)
    │     - cash, totalDebt (shortTermDebt + longTermDebt), sharesOutstanding passed through
    │   Unit mismatch guard: if revenue[0] / sharesOutstanding > 100,000 → raises ValueError
    │
    ▼
Router returns: {"parsed": { ...computed metrics dict... }}
```

**Response shape (`parsed`):**
```json
{
  "revenue": [411000000000, 385000000000, ...],
  "operatingIncome": [114000000000, ...],
  "operatingMargin": [0.277, 0.266, ...],
  "revenueGrowth": [0.068, 0.12, ...],
  "taxRate": [0.147, 0.133, ...],
  "reinvestmentRate": [0.35, 0.41, ...],
  "cash": 29965000000,
  "totalDebt": 111000000000,
  "sharesOutstanding": 15441000000
}
```

---

### Endpoint 2 — `POST /generate-assumptions`

**Router:** `backend/routers/assumptions.py`  
**Rate limit:** 5/minute  
**Input:** JSON body (`GenerateAssumptionsRequest`)

```json
{
  "parsed": { ...output of /parse-pdf... },
  "description": "Optional qualitative context about the company",
  "industry": "Semiconductors"
}
```

**Note:** The `parsed` dict from `/parse-pdf` can be passed directly as `body.parsed` — no transformation needed. `get_assumptions` just `json.dumps` it into the LLM prompt.

```
assumptions.py (router)
    │
    ▼
generate_assumptions.get_assumptions(parsed, description, industry)
    │   Calls Groq API (model: GROQ_ASSUMPTIONS_MODEL)
    │   System prompt: financial analyst persona, normalization rules, growth/reinvestment constraints
    │   User prompt: injects parsed financials + description + industry + available industry list
    │   Response validated:
    │     1. Industry string must exist in wacc_lookup._INDUSTRIES_SET (case-insensitive)
    │     2. Validated against Assumptions (Pydantic) — field bounds + lterm_rev_g ≤ sterm_rev_g
    │
    ▼
Router returns: {"assumptions": { ...validated assumptions dict... }}
```

**Response shape (`assumptions`):**
```json
{
  "sterm_rev_g": 0.15,
  "lterm_rev_g": 0.05,
  "ending_op_marg": 0.30,
  "reinvestment_r": 0.35,
  "industry": "Semiconductors"
}
```

---

### Endpoint 3 — `POST /value` *(DCF valuation — to be wired up)*

**Service:** `backend/services/dcf.py`  
**Input:** `DCFInputs` dataclass

The DCF model is implemented but not yet exposed as a router endpoint. It takes a `DCFInputs` dataclass assembled by the frontend (or a future `/value` router) from the outputs of the two endpoints above plus WACC lookup.

**DCFInputs assembly:**
```python
from backend.services.wacc_lookup import get_wacc_by_industry
from backend.models.dcf_inputs import DCFInputs

wacc_row = get_wacc_by_industry(assumptions["industry"])

inputs = DCFInputs(
    rev_i=parsed["revenue"][0],
    beg_op_marg=parsed["operatingMargin"][0],
    tax_r=parsed["taxRate"][0],
    cash=parsed["cash"],
    total_debt=parsed["totalDebt"],
    shares_outstanding=parsed["sharesOutstanding"],
    sterm_rev_g=assumptions["sterm_rev_g"],
    lterm_rev_g=assumptions["lterm_rev_g"],
    ending_op_marg=assumptions["ending_op_marg"],
    reinvestment_r=assumptions["reinvestment_r"],
    discount_r=wacc_row["wacc"],
    term_g=DEFAULT_TERM_G,       # from config
    riskf_r=DEFAULT_RISKF_R,     # from config
    num_years=DEFAULT_NUM_YEARS, # from config (10)
)
```

**DCF model logic (`dcf.py`):**
- Years 1–5 (short-term): revenue growth and operating margin interpolate linearly from starting values to long-term targets via `linear_steps()`
- Years 6–10 (long-term): revenue grows at `lterm_rev_g`, margin held at `ending_op_marg`
- FCF per year = `revenue × operating_margin × (1 − tax_rate) × (1 − reinvestment_rate)`
- Terminal value = Gordon Growth Model on year-10 FCF, discounted back
- Enterprise value = PV of FCFs + TV
- Equity value = EV − total_debt + cash
- Equity value per share = equity_value / shares_outstanding

**Returns:**
```json
{
  "enterprise_value": 2850000000000,
  "equity_value": 2769000000000,
  "equity_value_per_share": 179.32
}
```

---

## Pydantic Models

### `RawFinancialExtraction` (`parsed_financials.py`)
LLM output schema — validated before `compute_from_raw` receives it.

| Field | Type | Source |
|---|---|---|
| `revenue` | `list[Optional[float]]` | Income Statement |
| `operatingIncome` | `list[Optional[float]]` | Income Statement |
| `incomeTaxExpense` | `list[Optional[float]]` | Income Statement |
| `incomeBeforeTax` | `list[Optional[float]]` | Income Statement |
| `investmentsInPropertyPlantAndEquipment` | `list[Optional[float]]` | Cash Flow (investing) |
| `acquisitionsNet` | `list[Optional[float]]` | Cash Flow (investing) |
| `depreciationAndAmortization` | `list[Optional[float]]` | Cash Flow (operating) |
| `accountsReceivable` | `list[Optional[float]]` | Balance Sheet |
| `inventory` | `list[Optional[float]]` | Balance Sheet |
| `accountsPayable` | `list[Optional[float]]` | Balance Sheet |
| `cashAndCashEquivalents` | `Optional[float]` | Balance Sheet (most recent) |
| `shortTermDebt` | `Optional[float]` | Balance Sheet (most recent) |
| `longTermDebt` | `Optional[float]` | Balance Sheet (most recent) |
| `sharesOutstanding` | `Optional[float]` | EPS section / cover page |

All arrays: up to 5 periods, most recent first. `changeInWorkingCapital` is intentionally excluded — ΔWC is always computed from AR/Inventory/AP balance sheet values.

### `Assumptions` (`assumptions.py`)

| Field | Bounds | Meaning |
|---|---|---|
| `sterm_rev_g` | [-0.5, 2.0] | Short-term revenue growth (years 1–5) |
| `lterm_rev_g` | [-0.05, 0.1] | Long-term revenue growth (years 6–10) |
| `ending_op_marg` | [0, 0.8] | Target operating margin at year 10 |
| `reinvestment_r` | [0, 1] | Reinvestment rate (fraction of NOPAT reinvested) |
| `industry` | string | Must match a Damodaran industry name exactly |

Validator: `lterm_rev_g` must not exceed `sterm_rev_g`.

### `DCFInputs` (`dcf_inputs.py`)
Dataclass (not Pydantic). `__post_init__` raises `ValueError` if `shares_outstanding <= 0`.

---

## Key Services

### `pdf_text_extractor.py`
- Uses `pymupdf` (`import pymupdf as fitz`)
- Parallel page extraction via `ThreadPoolExecutor` for PDFs > 15 pages
- `_is_toc_page(text)`: returns `True` if fewer than 10 numeric tokens found — filters out table-of-contents pages that match statement keywords but contain no actual data
- `STATEMENT_TEXT_MAX_CHARS` (default 20,000) caps total statement text sent to LLM
- Cover text capped at 4,000 chars, sourced from early pages only

### `financials_from_pdf.py`
- OpenRouter API called via `openai` SDK pointed at `https://openrouter.ai/api/v1`
- `_normalize_arrays()`: if LLM returns a scalar instead of a list for any array field, wraps it in a list
- Empty response → `ValueError("LLM returned empty response")` — this can happen with free-tier OpenRouter models on large prompts; switch model if it occurs consistently

### `calculate_fperformance.py`
- `compute_from_raw(raw)`: pure function, no I/O
- `_resolve_change_in_wc(idx, ar, inv, ap)`: computes `WC_curr - WC_prev` where `WC = AR + Inventory - AP`; returns `0.0` if balance sheet data is missing for either period
- `safe_tax_rate(tax_expense, pretax_income)`: returns `0.25` default if `pretax_income <= 0`

### `wacc_lookup.py`
- Loads `data/wacc.xls` (Damodaran dataset) once at startup, cached in module-level `_lookup` dict
- Case-insensitive lookup by industry string
- `get_industries()` → list of all valid industry strings (used to validate LLM output in `generate_assumptions.py`)

---

## Error Handling Pattern

All routers follow this exception hierarchy:

| Exception | HTTP Status | Meaning |
|---|---|---|
| `ValueError` | 422 Unprocessable Entity | Bad input, LLM parse failure, validation failure |
| `GroqError` | 502 Bad Gateway | Upstream LLM provider failure |
| `Exception` (catch-all) | 500 Internal Server Error | Unexpected system error |

---

## External Dependencies

| Service | Used for | Client |
|---|---|---|
| OpenRouter | PDF financial extraction LLM | `openai` SDK, `base_url` overridden |
| Groq | Assumption generation LLM | `groq.AsyncGroq` |
| Damodaran WACC dataset | Industry WACC lookup | Local `.xls` file, `pandas` + `xlrd` |

---

## Known Constraints and Gotchas

- **Free-tier OpenRouter models** (e.g. `gpt-oss-20b:free`) can silently return empty responses on large prompts. If this happens consistently, switch `OPENROUTER_MODEL` in `financials_from_pdf.py` to `google/gemini-2.0-flash-001`.
- **`changeInWorkingCapital` is deliberately not extracted from the cash flow statement.** ΔWC is always computed from balance sheet AR/Inventory/AP. Do not add it back to the LLM schema.
- **Shares outstanding must never have unit expansion applied** (the LLM is explicitly instructed this way). Monetary values use `(in millions)` → ×1,000,000 expansion; shares do not.
- **The `/value` DCF endpoint does not yet exist as a router.** `dcf.py` has the model; it needs a router and a request model that assembles `DCFInputs` from the parsed + assumptions outputs.
- **`calculate_fperformance.py` has stale imports** (`from services.financials_from_pdf import extract_raw_financials`, `from services.pdf_text_extractor import extract_all_text`) that are unused after the refactor. The active entry point is `parse_financials_from_pdf` which delegates to `_parse_pdf` (aliased from `financials_from_pdf.parse_financials_from_pdf`).
- **CORS** is configured via `CORS_ORIGINS` env var (comma-separated). Default: `http://localhost:5173`.
- **Rate limiting** via `slowapi` uses remote IP. Limits: 5/minute on `/parse-pdf`, 5/minute on `/generate-assumptions`.