from pydantic import BaseModel


class ClaimSystemAdapterRequest(BaseModel):
    claim_id: str
    provider_id: str
    amount_cents: int
    patient_responsibility_cents: int = 0
