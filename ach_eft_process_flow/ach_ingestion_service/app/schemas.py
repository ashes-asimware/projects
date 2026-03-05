from pydantic import BaseModel


class AchIngestionServiceRequest(BaseModel):
    settlement_data: str


class ParsedAchSettlementData(BaseModel):
    trace_number: str
    payer_id: str
    provider_id: str
    amount_cents: int
