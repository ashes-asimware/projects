from typing import Literal

from pydantic import BaseModel


class Bai2IngestRequest(BaseModel):
    bai2_data: str


class Camt053IngestRequest(BaseModel):
    camt053_xml: str


class ParsedBankStatement(BaseModel):
    statement_id: str
    trace_number: str
    payer_id: str
    provider_id: str
    amount_cents: int
    direction: Literal["CREDIT", "DEBIT"] = "CREDIT"
