from pydantic import BaseModel


class PairingServiceRequest(BaseModel):
    external_id: str
    amount_cents: int
