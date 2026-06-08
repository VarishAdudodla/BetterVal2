import logging
from services.financials_from_pdf import extract_raw_financials
from services.pdf_text_extractor import extract_all_text
from services.financials_from_pdf import parse_financials_from_pdf as _parse_pdf
from utils.financial_helpers import _get_list, _get_optional_list, safe_tax_rate, _resolve_change_in_wc

logger = logging.getLogger(__name__)

def compute_from_raw(raw: dict) -> dict:
    revenues = raw.get("revenue") or []
    n = min(len(revenues), 5)
    if n == 0:
        raise ValueError("No revenue periods extracted from filing")
    
    shares = float(raw.get("sharesOutstanding") or 0)
    if shares > 0 and revenues:
        implied_rev_per_share = revenues[0] / shares
        if implied_rev_per_share > 100000:
            
            raise ValueError(
                 f"Unit mismatch detected: revenue={revenues[0]:,.0f}, "
                 f"shares={shares:,.0f}, implied rev/share=${implied_rev_per_share:,.2f}. "
                 "Check that shares and monetary values use consistent units."
            )

    revenues = _get_list(raw, "revenue", n)
    operating_incs = _get_list(raw, "operatingIncome", n)
    tax_expenses = _get_list(raw, "incomeTaxExpense", n)
    pretax_incomes = _get_list(raw, "incomeBeforeTax", n)

    capex = _get_optional_list(raw, "investmentsInPropertyPlantAndEquipment", n)
    acquisitions = _get_optional_list(raw, "acquisitionsNet", n)
    depreciation = _get_optional_list(raw, "depreciationAndAmortization", n)
    ar = _get_optional_list(raw, "accountsReceivable", n)
    inv = _get_optional_list(raw, "inventory", n)
    ap = _get_optional_list(raw, "accountsPayable", n)

    operating_margs = [
        op / rev if rev else 0.0
        for op, rev in zip(operating_incs, revenues)
    ]
    rev_gs = [
        (revenues[i] - revenues[i + 1]) / revenues[i + 1]
        for i in range(len(revenues) - 1)
        if revenues[i + 1]
    ]
    tax_rs = [safe_tax_rate(tax_expenses[i], pretax_incomes[i]) for i in range(n)]

    reinvestment_rates = []
    for i in range(n):
        wc_change = _resolve_change_in_wc(i, ar, inv, ap)
        cap = capex[i] if i < len(capex) and capex[i] is not None else 0.0
        acq = acquisitions[i] if i < len(acquisitions) and acquisitions[i] is not None else 0.0
        dep = depreciation[i] if i < len(depreciation) and depreciation[i] is not None else 0.0
        numerator = wc_change - cap - acq - dep
        denom = operating_incs[i] * (1 - tax_rs[i])
        reinvestment_rates.append(numerator / denom if denom > 0 else 0.0)

    return {
        "revenue": revenues,
        "operatingIncome": operating_incs,
        "operatingMargin": operating_margs,
        "revenueGrowth": rev_gs,
        "taxRate": tax_rs,
        "reinvestmentRate": reinvestment_rates,
        "cash": float(raw.get("cashAndCashEquivalents") or 0),
        "totalDebt": float(raw.get("shortTermDebt") or 0) + float(raw.get("longTermDebt") or 0),
        "sharesOutstanding": float(raw.get("sharesOutstanding") or 0),
    }

def parse_financials_from_pdf(file) -> dict:
    raw = _parse_pdf(file)
    return compute_from_raw(raw)