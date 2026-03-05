from pydantic import BaseModel


class ProviderBalanceResponse(BaseModel):
    provider_id: str
    balance_cents: int
