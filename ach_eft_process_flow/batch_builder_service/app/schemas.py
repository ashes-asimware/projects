from pydantic import BaseModel, Field

from shared.events.schemas import ClaimReference


class BatchBuilderServiceRequest(BaseModel):
    provider_id: str
    amount_cents: int
    payer_id: str = "platform"
    trace_number: str | None = None
    correlation_id: str | None = None
    claims: list[ClaimReference] = Field(default_factory=list)
