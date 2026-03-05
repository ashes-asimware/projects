from pydantic import BaseModel


class ProviderBalanceResponse(BaseModel):
    provider_id: str
    balance_cents: int


class PayoutInitiatedResponse(BaseModel):
    provider_id: str
    amount_cents: int
    correlation_id: str
