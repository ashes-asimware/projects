from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from shared.events.schemas import ServiceEvent
from shared.servicebus.client import ServiceBusPublisher

from .db import Base, SessionLocal, engine
from .models import ProcessingRecord
from .schemas import RemittanceIngestionServiceRequest


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="remittance_ingestion_service", lifespan=lifespan)
publisher = ServiceBusPublisher()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "remittance_ingestion_service"}


@app.post("/process")
def process(payload: RemittanceIngestionServiceRequest, db: Session = Depends(get_db)) -> ServiceEvent:
    record = ProcessingRecord(external_id=payload.external_id, amount_cents=payload.amount_cents)
    db.add(record)
    db.commit()
    db.refresh(record)
    event = ServiceEvent(
        event_type="remittance_ingestion_service.received",
        source_service="remittance_ingestion_service",
        payload={"external_id": payload.external_id, "amount_cents": payload.amount_cents},
    )
    publisher.send(queue_name="remittance_ingestion_service", message=event.model_dump_json())
    return event
