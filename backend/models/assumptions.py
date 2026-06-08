from pydantic import BaseModel, Field, model_validator
from typing import Self
from typing import Optional

class Assumptions(BaseModel):
    sterm_rev_g: float = Field(ge=-0.5, le=2.0)
    lterm_rev_g: float = Field(ge=-0.05, le=0.1)
    ending_op_marg: float = Field(ge=0, le=0.8)
    reinvestment_r: float = Field(ge=0, le=1)
    industry: str

    @model_validator(mode="after")
    def check_growth_rate_ordering(self) -> Self:
        if self.lterm_rev_g > self.sterm_rev_g:
            raise ValueError(
                f"lterm_rev_g ({self.lterm_rev_g}) cannot exceed sterm_rev_g ({self.sterm_rev_g})"
            )
        return self
    
class GenerateAssumptionsRequest(BaseModel):
    parsed: dict                                        
    description: Optional[str] = Field(default="")
    industry: str = Field(min_length=1)