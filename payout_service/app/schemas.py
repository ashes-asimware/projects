from pydantic import BaseModel


class PayoutServiceRequest(BaseModel):
    external_id: str
    amount_cents: int
