from pydantic import BaseModel, field_validator


class RemittanceIngestionServiceRequest(BaseModel):
    external_id: str
    amount_cents: int


class ClaimDetail(BaseModel):
    claim_id: str
    amount_cents: int


class Parsed835Data(BaseModel):
    trace_number: str
    payer_id: str
    provider_id: str
    claims: list[ClaimDetail]

    @field_validator("trace_number", "payer_id", "provider_id")
    @classmethod
    def must_be_non_empty(cls, v: str) -> str:
        if not v:
            raise ValueError("field must not be empty")
        return v


class RemittanceIngest835Request(BaseModel):
    raw_835: str
