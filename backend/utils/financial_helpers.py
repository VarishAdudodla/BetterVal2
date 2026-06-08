def safe_tax_rate(tax_expense, pretax_income):
    if pretax_income <= 0:
        return 0.25
    else:
        return tax_expense / pretax_income
    
#Safely handles LLM values and turns into list, n revenue periods
def _get_list(raw: dict, key: str, n: int) -> list:
    val = raw.get(key) or []
    if not isinstance(val, list):
        return [0.0] * n
    out = []
    for i in range(n):
        if i < len(val) and val[i] is not None:
            out.append(float(val[i]))
        else:
            out.append(0.0)
    return out

#Safely handles LLM values and turns into list, n revenue periods
def _get_optional_list(raw: dict, key: str, n: int) -> list:
    val = raw.get(key) or []
    if not isinstance(val, list):
        return [None] * n
    out = []
    for i in range(n):
        if i < len(val) and val[i] is not None:
            out.append(float(val[i]))
        else:
            out.append(None)
    return out

#Working capital calculations safely
def _working_capital(ar, inv, ap):
    if ar is None and inv is None and ap is None:
        return None
    return (ar or 0.0) + (inv or 0.0) - (ap or 0.0)

#Change in working capital calculations safely // backup if output failed
def _resolve_change_in_wc(idx, change_in_wc, ar, inv, ap):
    if idx < len(change_in_wc) and change_in_wc[idx] is not None:
        return change_in_wc[idx]
    wc_curr = _working_capital(
        ar[idx] if idx < len(ar) else None,
        inv[idx] if idx < len(inv) else None,
        ap[idx] if idx < len(ap) else None,
    )
    wc_prev = _working_capital(
        ar[idx + 1] if idx + 1 < len(ar) else None,
        inv[idx + 1] if idx + 1 < len(inv) else None,
        ap[idx + 1] if idx + 1 < len(ap) else None,
    )
    if wc_curr is None or wc_prev is None:
        return 0.0
    return wc_curr - wc_prev

def latest_value(parsed: dict, key: str, default=0):
    value = parsed.get(key)
    if isinstance(value, list):
        return value[0] if value and value[0] is not None else default
    return value if value is not None else default