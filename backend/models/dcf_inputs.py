from dataclasses import dataclass

@dataclass
class DCFInputs:
    rev_i: float
    sterm_rev_g: float
    lterm_rev_g: float
    beg_op_marg: float
    ending_op_marg: float
    tax_r: float
    term_g: float
    discount_r: float
    riskf_r: float
    num_years: int
    reinvestment_r: float
    cash: float
    total_debt: float
    shares_outstanding: float
    
    def __post_init__(self):
        if(self.shares_outstanding <= 0):
            raise ValueError("Number of shares outstanding must be greater than zero")