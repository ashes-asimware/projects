from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from shared.events.schemas import ServiceEvent
from shared.servicebus.client import ServiceBusPublisher

from .db import Base, SessionLocal, engine
from .models import ProcessingRecord
from .schemas import LedgerServiceRequest


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="ledger_service", lifespan=lifespan)
publisher = ServiceBusPublisher()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ledger_service"}


@app.post("/process")
def process(payload: LedgerServiceRequest, db: Session = Depends(get_db)) -> ServiceEvent:
    record = ProcessingRecord(external_id=payload.external_id, amount_cents=payload.amount_cents)
    db.add(record)
    db.commit()
    db.refresh(record)
    event = ServiceEvent(
        event_type="ledger_service.received",
        source_service="ledger_service",
        payload={"external_id": payload.external_id, "amount_cents": payload.amount_cents},
    )
    publisher.send(queue_name="ledger_service", message=event.model_dump_json())
    return event
