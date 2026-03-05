from contextlib import asynccontextmanager
import hashlib
import json

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.orm import Session

from shared.middleware import apply_common_middleware
from shared.events.schemas import ClaimReference, EFTReceivedV1
from shared.events.topics import EFT_RECEIVED_TOPIC
from shared.servicebus.client import publish

from .db import Base, SessionLocal, engine
from .models import ProcessingRecord
from .schemas import AchIngestionServiceRequest, ParsedAchSettlementData


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="ach_ingestion_service", lifespan=lifespan)
apply_common_middleware(app)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ach_ingestion_service"}


def _parse_ach_settlement_data(settlement_data: str) -> ParsedAchSettlementData:
    try:
        parsed = json.loads(settlement_data)
        if isinstance(parsed, dict):
            return ParsedAchSettlementData(**parsed)
    except json.JSONDecodeError:
        pass

    parsed_pairs: dict[str, str | int] = {}
    for pair in settlement_data.split(","):
        segment = pair.strip()
        if not segment:
            continue
        if "=" in segment:
            key, value = segment.split("=", 1)
        elif ":" in segment:
            key, value = segment.split(":", 1)
        else:
            continue
        normalized_key = key.strip()
        normalized_value = value.strip()
        if normalized_key == "amount_cents":
            try:
                parsed_pairs[normalized_key] = int(normalized_value)
            except ValueError:
                parsed_pairs[normalized_key] = normalized_value
        else:
            parsed_pairs[normalized_key] = normalized_value

    return ParsedAchSettlementData(**parsed_pairs)


def _build_correlation_id(parsed_data: ParsedAchSettlementData) -> str:
    correlation_source = (
        f"{parsed_data.trace_number}|{parsed_data.payer_id}|"
        f"{parsed_data.provider_id}|{parsed_data.amount_cents}"
    )
    return hashlib.sha256(correlation_source.encode("utf-8")).hexdigest()


def _extract_settlement_payload(
    request_body: AchIngestionServiceRequest | None,
    settlement_file: UploadFile | None,
    settlement_data: str | None,
) -> str:
    if request_body and request_body.settlement_data:
        return request_body.settlement_data
    if settlement_data:
        return settlement_data
    if settlement_file is not None:
        file_bytes = settlement_file.file.read()
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return file_bytes.decode("utf-8", errors="ignore")
    raise HTTPException(
        status_code=422,
        detail={"message": "Invalid ACH settlement data", "errors": [{"type": "missing", "loc": ["settlement_data"]}]},
    )


@app.post("/ingest-ach")
async def ingest_ach(
    payload: AchIngestionServiceRequest | None = Body(None),
    settlement_file: UploadFile | None = File(None),
    settlement_data: str | None = Form(None),
    db: Session = Depends(get_db),
) -> EFTReceivedV1:
    try:
        settlement_text = _extract_settlement_payload(payload, settlement_file, settlement_data)
        parsed_data = _parse_ach_settlement_data(settlement_text)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422,
            detail={"message": "Invalid ACH settlement data", "errors": exc.errors()},
        ) from exc
    correlation_id = _build_correlation_id(parsed_data)

    record = ProcessingRecord(
        external_id=parsed_data.trace_number,
        amount_cents=parsed_data.amount_cents,
        raw_data=settlement_text,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    event = EFTReceivedV1(
        correlation_id=correlation_id,
        trace_number=parsed_data.trace_number,
        payer_id=parsed_data.payer_id,
        provider_id=parsed_data.provider_id,
        claims=[ClaimReference(claim_id="EFT_TOTAL", amount_cents=parsed_data.amount_cents)],
    )

    await publish(
        topic_name=EFT_RECEIVED_TOPIC,
        payload=event.model_dump(mode="json"),
        correlation_id=event.correlation_id,
    )

    return event
