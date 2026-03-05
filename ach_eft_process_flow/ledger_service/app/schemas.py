from datetime import datetime
from enum import Enum

from pydantic import BaseModel


class LineType(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"


class JournalLineRequest(BaseModel):
    line_type: LineType
    account_code: str
    amount_cents: int


class PostEntryRequest(BaseModel):
    correlation_id: str
    entry_type: str
    lines: list[JournalLineRequest]


class JournalLineResponse(BaseModel):
    id: int
    line_type: LineType
    account_code: str
    amount_cents: int

    model_config = {"from_attributes": True}


class JournalEntryResponse(BaseModel):
    id: int
    correlation_id: str
    entry_type: str
    source_queue: str
    created_at: datetime
    lines: list[JournalLineResponse]

    model_config = {"from_attributes": True}
