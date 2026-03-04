from pydantic import BaseModel


class ClaimSystemAdapterRequest(BaseModel):
    external_id: str
    amount_cents: int
