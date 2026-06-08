from pydantic import BaseModel, field_validator
from typing import Optional

class RawFinancialExtraction(BaseModel):
    revenue: list[Optional[float]]
    operatingIncome: list[Optional[float]]
    incomeTaxExpense: list[Optional[float]]
    incomeBeforeTax: list[Optional[float]]
    investmentsInPropertyPlantAndEquipment: list[Optional[float]]
    acquisitionsNet: list[Optional[float]]
    depreciationAndAmortization: list[Optional[float]]
    accountsReceivable: list[Optional[float]]
    inventory: list[Optional[float]]
    accountsPayable: list[Optional[float]]
    cashAndCashEquivalents: Optional[float] = 0
    shortTermDebt: Optional[float] = 0
    longTermDebt: Optional[float] = 0
    sharesOutstanding: Optional[float] = 0