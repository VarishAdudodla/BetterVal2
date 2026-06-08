import math
from backend.models.dcf_inputs import DCFInputs

def linear_steps(beg, end, i, N):

    if N == 1:
        return end
    else:
        return beg + (end - beg) * ((i - 1) / (N-1))
    
def DCF(inputs: DCFInputs):

    if inputs.term_g > inputs.riskf_r:
        raise ValueError("Terminal Growth rate is too large, it must be less than the risk free rate!")
    
    dcash_flow = []
    revenues = []
    sterm_year_end = math.floor((inputs.num_years) / 2)
    
    for i in range(1, sterm_year_end + 1):

        operating_marg = linear_steps(inputs.beg_op_marg,
                                      inputs.ending_op_marg,
                                      i,
                                      sterm_year_end)
        revenue_growth = linear_steps(inputs.sterm_rev_g, 
                                      inputs.lterm_rev_g,
                                      i,
                                      sterm_year_end)
        if i == 1:
            revenue = inputs.rev_i * (1 + revenue_growth)
            revenues.append(revenue)
        else:
            revenue_last_year = revenues[i-2]
            revenue = revenue_last_year * (1+revenue_growth) 
            revenues.append(revenue)
        
        fcf = revenue * operating_marg * (1-inputs.tax_r) * (1-inputs.reinvestment_r)
        dfcf = fcf / (1 + inputs.discount_r) ** i
        dcash_flow.append(dfcf)
    
    fcf_final = None

    for i in range(sterm_year_end + 1, inputs.num_years + 1):

        revenue_last_year = revenues[-1] 
        revenue = revenue_last_year * (1+inputs.lterm_rev_g)
        revenues.append(revenue)
        
        fcf = revenue * inputs.ending_op_marg * (1 - inputs.tax_r) * (1-inputs.reinvestment_r)
        dfcf = fcf / (1 + inputs.discount_r) ** i
        dcash_flow.append(dfcf)

        if i == inputs.num_years:
            fcf_final = fcf
    
    TV = (fcf_final * (1 + inputs.term_g) / (inputs.discount_r - inputs.term_g)) / (1 + inputs.discount_r) ** inputs.num_years

    enterprise_value =  TV + sum(dcash_flow)
    equity_value = enterprise_value - inputs.total_debt + inputs.cash
    equity_value_per_share = equity_value / inputs.shares_outstanding

    return {
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "equity_value_per_share": equity_value_per_share
    }

