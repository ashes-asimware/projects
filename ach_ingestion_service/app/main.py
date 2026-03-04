from contextlib import asynccontextmanager
import hashlib
import json

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from shared.events.schemas import EFTReceived
from shared.servicebus.client import publish

from .db import Base, SessionLocal, engine
from .models import ProcessingRecord
from .schemas import AchIngestionServiceRequest, ParsedAchSettlementData


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="ach_ingestion_service", lifespan=lifespan)


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

    parsed_pairs: dict[str, str] = {}
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
        parsed_pairs[key.strip()] = value.strip()

    return ParsedAchSettlementData(**parsed_pairs)


def _build_correlation_id(parsed_data: ParsedAchSettlementData) -> str:
    correlation_source = (
        f"{parsed_data.trace_number}|{parsed_data.payer_id}|"
        f"{parsed_data.provider_id}|{parsed_data.amount_cents}"
    )
    return hashlib.sha256(correlation_source.encode("utf-8")).hexdigest()


@app.post("/ingest-ach")
async def ingest_ach(payload: AchIngestionServiceRequest, db: Session = Depends(get_db)) -> EFTReceived:
    parsed_data = _parse_ach_settlement_data(payload.settlement_data)
    correlation_id = _build_correlation_id(parsed_data)

    record = ProcessingRecord(external_id=parsed_data.trace_number, amount_cents=parsed_data.amount_cents)
    db.add(record)
    db.commit()
    db.refresh(record)

    event = EFTReceived(
        correlation_id=correlation_id,
        trace_number=parsed_data.trace_number,
        payer_id=parsed_data.payer_id,
        provider_id=parsed_data.provider_id,
    )

    await publish(
        topic_name="eft-received",
        payload=event.model_dump(mode="json"),
        correlation_id=event.correlation_id,
    )

    return event
