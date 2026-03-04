from pydantic import BaseModel


class LedgerServiceRequest(BaseModel):
    external_id: str
    amount_cents: int
