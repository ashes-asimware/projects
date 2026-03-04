from pydantic import BaseModel


class ProviderLedgerServiceRequest(BaseModel):
    external_id: str
    amount_cents: int
