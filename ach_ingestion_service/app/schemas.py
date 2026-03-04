from pydantic import BaseModel


class AchIngestionServiceRequest(BaseModel):
    external_id: str
    amount_cents: int
