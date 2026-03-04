from pydantic import BaseModel


class RemittanceIngestionServiceRequest(BaseModel):
    external_id: str
    amount_cents: int
