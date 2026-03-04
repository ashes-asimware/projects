from pydantic import BaseModel


class BatchBuilderServiceRequest(BaseModel):
    external_id: str
    amount_cents: int
