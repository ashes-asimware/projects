from typing import Literal

from pydantic import BaseModel, Field

from shared.events.schemas import ClaimReference


class ReconciliationServiceRequest(BaseModel):
    correlation_id: str
    trace_number: str
    payer_id: str
    provider_id: str
    amount_cents: int
    direction: Literal["CREDIT", "DEBIT"] = "CREDIT"
    source_queue: str = "manual"
    claims: list[ClaimReference] = Field(default_factory=list)
