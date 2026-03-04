from pydantic import BaseModel


class ReconciliationServiceRequest(BaseModel):
    external_id: str
    amount_cents: int
