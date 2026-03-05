import hashlib
import json
import logging
import xml.etree.ElementTree as ET
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from shared.middleware import apply_common_middleware
from shared.events.schemas import BankStatementReceivedV1, ClaimReference
from shared.events.topics import BANK_STATEMENT_TOPIC
from shared.servicebus.client import ServiceBusPublisher

from .db import Base, SessionLocal, engine
from .models import BankStatementRecord
from .schemas import Bai2IngestRequest, Camt053IngestRequest, ParsedBankStatement

logger = logging.getLogger(__name__)

BANK_STATEMENT_QUEUE = BANK_STATEMENT_TOPIC
publisher = ServiceBusPublisher()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="bank_statement_ingestion_service", lifespan=lifespan)
apply_common_middleware(app)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _amount_to_cents(value: float | int | str) -> int:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0
    return int(round(numeric))


def _build_correlation_id(parsed: ParsedBankStatement) -> str:
    source = f"{parsed.trace_number}|{parsed.payer_id}|{parsed.provider_id}|{parsed.amount_cents}"
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _parse_bai2(data: str) -> ParsedBankStatement:
    try:
        parsed = json.loads(data)
        if isinstance(parsed, dict):
            return ParsedBankStatement(**parsed)
    except (json.JSONDecodeError, ValidationError):
        pass

    statement_id = ""
    trace_number = ""
    payer_id = ""
    provider_id = ""
    total_cents = 0
    direction = "CREDIT"

    for raw_line in data.splitlines():
        line = raw_line.strip().strip("/")
        if not line:
            continue
        parts = [p.strip() for p in line.split(",") if p.strip()]
        code = parts[0]
        if code == "01" and len(parts) > 1:
            statement_id = parts[1]
            trace_number = parts[1]
        elif code == "02" and len(parts) > 2:
            payer_id = parts[1]
            provider_id = parts[2]
        elif code == "16" and len(parts) > 2:
            amount_val = _amount_to_cents(parts[2])
            total_cents += amount_val
            if amount_val < 0:
                direction = "DEBIT"

    if not trace_number:
        trace_number = statement_id or "bai2-trace"
    if not payer_id:
        payer_id = "unknown_payer"
    if not provider_id:
        provider_id = "unknown_provider"

    return ParsedBankStatement(
        statement_id=statement_id or trace_number,
        trace_number=trace_number,
        payer_id=payer_id,
        provider_id=provider_id,
        amount_cents=total_cents,
        direction=direction,
    )


def _parse_camt053(data: str) -> ParsedBankStatement:
    try:
        parsed = json.loads(data)
        if isinstance(parsed, dict):
            return ParsedBankStatement(**parsed)
    except (json.JSONDecodeError, ValidationError):
        pass

    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:  # pragma: no cover - validation error path
        raise HTTPException(status_code=422, detail="Invalid CAMT.053 XML") from exc

    def _find_text(xpath: str) -> str:
        node = root.find(xpath)
        return node.text.strip() if node is not None and node.text else ""

    statement_id = _find_text(".//Stmt/Id") or _find_text(".//Id")
    trace_number = _find_text(".//TxId") or statement_id or "camt-trace"
    payer_id = _find_text(".//Cdtr/Nm") or "unknown_payer"
    provider_id = _find_text(".//CdtrAcct/Id/IBAN") or _find_text(".//Dbtr/Nm") or "unknown_provider"
    amount_text = _find_text(".//Amt")
    direction_code = _find_text(".//CdtDbtInd")

    amount_cents = _amount_to_cents(amount_text or 0)
    direction = "DEBIT" if direction_code.upper().startswith("D") else "CREDIT"

    return ParsedBankStatement(
        statement_id=statement_id or trace_number,
        trace_number=trace_number,
        payer_id=payer_id,
        provider_id=provider_id,
        amount_cents=amount_cents,
        direction=direction,
    )


def _persist_record(db: Session, parsed: ParsedBankStatement, correlation_id: str, source_format: str) -> BankStatementRecord:
    record = BankStatementRecord(
        statement_id=parsed.statement_id,
        correlation_id=correlation_id,
        payer_id=parsed.payer_id,
        provider_id=parsed.provider_id,
        amount_cents=parsed.amount_cents,
        direction=parsed.direction,
        source_format=source_format,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _publish_event(parsed: ParsedBankStatement, correlation_id: str) -> BankStatementReceivedV1:
    event = BankStatementReceivedV1(
        correlation_id=correlation_id,
        trace_number=parsed.trace_number,
        payer_id=parsed.payer_id,
        provider_id=parsed.provider_id,
        claims=[ClaimReference(claim_id="BANK_STMT", amount_cents=parsed.amount_cents)],
    )
    publisher.send(queue_name=BANK_STATEMENT_QUEUE, message=event.model_dump_json())
    return event


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "bank_statement_ingestion_service"}


@app.post("/ingest-bai2", response_model=BankStatementReceivedV1)
def ingest_bai2(payload: Bai2IngestRequest, db: Session = Depends(get_db)) -> BankStatementReceivedV1:
    try:
        parsed = _parse_bai2(payload.bai2_data)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "Invalid BAI2 data", "errors": exc.errors()},
        ) from exc

    correlation_id = _build_correlation_id(parsed)
    _persist_record(db, parsed, correlation_id, "BAI2")
    return _publish_event(parsed, correlation_id)


@app.post("/ingest-camt053", response_model=BankStatementReceivedV1)
def ingest_camt053(payload: Camt053IngestRequest, db: Session = Depends(get_db)) -> BankStatementReceivedV1:
    try:
        parsed = _parse_camt053(payload.camt053_xml)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "Invalid CAMT.053 data", "errors": exc.errors()},
        ) from exc

    correlation_id = _build_correlation_id(parsed)
    _persist_record(db, parsed, correlation_id, "CAMT053")
    return _publish_event(parsed, correlation_id)
