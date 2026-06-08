import pandas as pd

_df: pd.DataFrame | None = None
_lookup: dict[str, dict] | None = None

COLUMNS = [
    "industry", "num_firms", "beta", "cost_of_equity", "e_weight", "std_dev",
    "cost_of_debt", "tax_rate", "after_tax_cost_of_debt", "d_weight", "wacc",
]

def _load_data():
    global _df, _lookup
    if _lookup is None:
        _df = pd.read_excel(
            "data/wacc.xls",
            sheet_name="Industry Averages",
            engine="xlrd",
            header=18,
            usecols=range(11),   # skip wacc_local at load time
        )
        _df.columns = COLUMNS
        _df = _df.dropna(subset=["industry"])

        # build case-insensitive lookup once
        _lookup = {
            row["industry"].lower(): row.to_dict()
            for _, row in _df.iterrows()
        }
    return _df, _lookup


def get_wacc_by_industry(industry: str) -> dict:
    _, lookup = _load_data()
    row = lookup.get(industry.lower())
    if row is None:
        raise ValueError(f"No WACC data found for industry: {industry}")
    return row


def get_industries() -> list[str]:
    _, lookup = _load_data()
    return [v["industry"] for v in lookup.values()]