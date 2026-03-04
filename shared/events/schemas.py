from datetime import datetime, timezone

from pydantic import BaseModel, Field


class ServiceEvent(BaseModel):
    event_type: str
    source_service: str
    payload: dict
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ClaimReference(BaseModel):
    claim_id: str
    amount_cents: int


class InterServiceEvent(BaseModel):
    correlation_id: str
    trace_number: str
    payer_id: str
    provider_id: str
    claims: list[ClaimReference] = Field(default_factory=list)
    event_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class EFTReceived(InterServiceEvent):
    pass


class RemittanceReceived(InterServiceEvent):
    pass


class EFTMatchedToRemittance(InterServiceEvent):
    pass


class ProviderPayoutInitiated(InterServiceEvent):
    pass


class ProviderPayoutSent(InterServiceEvent):
    pass


class BankStatementReceived(InterServiceEvent):
    pass


class ReconciliationCompleted(InterServiceEvent):
    pass


class ClaimPaymentPosted(InterServiceEvent):
    pass


class ACHReturnReceived(InterServiceEvent):
    pass


class NOCReceived(InterServiceEvent):
    pass
