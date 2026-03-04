from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from shared.events.schemas import ServiceEvent
from shared.servicebus.client import ServiceBusPublisher

from .db import Base, SessionLocal, engine
from .models import ProcessingRecord
from .schemas import ProviderLedgerServiceRequest

app = FastAPI(title="provider_ledger_service")
publisher = ServiceBusPublisher()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.on_event("startup")
def startup() -> None:
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "provider_ledger_service"}


@app.post("/process")
def process(payload: ProviderLedgerServiceRequest, db: Session = Depends(get_db)) -> ServiceEvent:
    record = ProcessingRecord(external_id=payload.external_id, amount_cents=payload.amount_cents)
    db.add(record)
    db.commit()
    event = ServiceEvent(
        event_type="provider_ledger_service.received",
        source_service="provider_ledger_service",
        payload={"external_id": payload.external_id, "amount_cents": payload.amount_cents},
    )
    publisher.send(queue_name="provider_ledger_service", message=event.model_dump_json())
    return event
