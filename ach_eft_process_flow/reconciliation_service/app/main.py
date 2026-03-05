import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from shared.middleware import apply_common_middleware
from shared.events.schemas import (
    ClaimReference,
    ReconciliationCompletedV1,
    RemittanceExceptionV1,
)
from shared.events.topics import (
    BANK_STATEMENT_TOPIC,
    EFT_MATCHED_TOPIC,
    EFT_RECEIVED_TOPIC,
    PAYOUT_SENT_TOPIC,
    RECONCILIATION_TOPIC,
    REMITTANCE_RECEIVED_TOPIC,
)
from shared.servicebus.client import ServiceBusPublisher

from .db import Base, SessionLocal, engine
from .models import BankTransaction, ReconciliationResult
from .schemas import ReconciliationServiceRequest

logger = logging.getLogger(__name__)

SUBSCRIBED_QUEUES = [
    BANK_STATEMENT_TOPIC,
    EFT_RECEIVED_TOPIC,
    EFT_MATCHED_TOPIC,
    REMITTANCE_RECEIVED_TOPIC,
    PAYOUT_SENT_TOPIC,
]
publisher = ServiceBusPublisher()


def _claims_total(claims: list[dict]) -> int:
    return sum(int(c.get("amount_cents", 0)) for c in claims)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _persist_transaction(
    db: Session,
    correlation_id: str,
    trace_number: str,
    payer_id: str,
    provider_id: str,
    amount_cents: int,
    direction: str,
    source_queue: str,
    claims: list[dict],
) -> BankTransaction:
    txn = BankTransaction(
        correlation_id=correlation_id,
        trace_number=trace_number,
        payer_id=payer_id,
        provider_id=provider_id,
        amount_cents=amount_cents,
        direction=direction,
        source_queue=source_queue,
        claims_json=json.dumps(claims),
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def _publish_result(txn: BankTransaction, status: str, message: str) -> None:
    if status == "COMPLETED":
        event = ReconciliationCompletedV1(
            correlation_id=txn.correlation_id,
            trace_number=txn.trace_number,
            payer_id=txn.payer_id,
            provider_id=txn.provider_id,
            claims=[ClaimReference(**c) for c in json.loads(txn.claims_json)],
        )
    else:
        event = RemittanceExceptionV1(
            correlation_id=txn.correlation_id,
            trace_number=txn.trace_number,
            payer_id=txn.payer_id,
            provider_id=txn.provider_id,
            claims=[ClaimReference(**c) for c in json.loads(txn.claims_json)],
            reason=message,
        )
    publisher.send(queue_name=RECONCILIATION_TOPIC, message=event.model_dump_json())


def _reconcile(db: Session, correlation_id: str) -> ReconciliationResult | None:
    existing = db.query(ReconciliationResult).filter_by(correlation_id=correlation_id).first()
    if existing:
        return existing

    txns = db.query(BankTransaction).filter_by(correlation_id=correlation_id).all()
    if len(txns) < 2:
        return None

    amounts = {t.amount_cents for t in txns}
    if len(amounts) == 1:
        status = "COMPLETED"
        message = "Amounts matched across sources"
    else:
        status = "EXCEPTION"
        message = "amount mismatch across sources"

    result = ReconciliationResult(
        correlation_id=correlation_id,
        status=status,
        message=message,
    )
    db.add(result)
    db.commit()
    db.refresh(result)
    _publish_result(txns[0], status, message)
    return result


async def _handle_queue_message(queue_name: str, body: str) -> ReconciliationResult | None:
    data = json.loads(body)
    claims = data.get("claims") or []
    correlation_id = data.get("correlation_id", "")
    amount_cents = _claims_total(claims)
    direction = data.get("direction") or ("DEBIT" if queue_name == PAYOUT_SENT_TOPIC else "CREDIT")
    trace_number = data.get("trace_number", "")
    payer_id = data.get("payer_id", "")
    provider_id = data.get("provider_id", "")

    db = SessionLocal()
    try:
        txn = _persist_transaction(
            db,
            correlation_id=correlation_id,
            trace_number=trace_number,
            payer_id=payer_id,
            provider_id=provider_id,
            amount_cents=amount_cents,
            direction=direction,
            source_queue=queue_name,
            claims=claims,
        )
        return _reconcile(db, txn.correlation_id)
    finally:
        db.close()


async def _consume_queue(queue_name: str) -> None:
    conn_str = os.getenv("AZURE_SERVICEBUS_CONNECTION_STRING") or os.getenv("SERVICEBUS_CONNECTION_STRING")
    if not conn_str:
        logger.warning(
            "No Service Bus connection string configured; queue consumer for %s disabled",
            queue_name,
        )
        return
    try:
        from azure.servicebus.aio import ServiceBusClient as AsyncServiceBusClient  # type: ignore[import]
    except ImportError:  # pragma: no cover
        logger.warning("azure-servicebus not installed; queue consumer for %s disabled", queue_name)
        return

    while True:
        try:
            async with AsyncServiceBusClient.from_connection_string(conn_str) as sb_client:
                async with sb_client.get_queue_receiver(queue_name=queue_name, max_wait_time=5) as receiver:
                    async for message in receiver:
                        body = b"".join(message.body).decode("utf-8")
                        try:
                            await _handle_queue_message(queue_name, body)
                            await receiver.complete_message(message)
                        except Exception as exc:  # pragma: no cover
                            logger.error("Failed to process message from %s: %s", queue_name, exc)
                            await receiver.dead_letter_message(
                                message,
                                reason="processing_failed",
                                error_description=str(exc),
                            )
        except asyncio.CancelledError:
            return
        except Exception as exc:  # pragma: no cover
            logger.error("Queue consumer error for %s: %s", queue_name, exc)
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    tasks = [asyncio.create_task(_consume_queue(q)) for q in SUBSCRIBED_QUEUES]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="reconciliation_service", lifespan=lifespan)
apply_common_middleware(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "reconciliation_service"}


@app.post("/process", response_model=dict)
def process(payload: ReconciliationServiceRequest, db: Session = Depends(get_db)) -> dict:
    txn = _persist_transaction(
        db,
        correlation_id=payload.correlation_id,
        trace_number=payload.trace_number,
        payer_id=payload.payer_id,
        provider_id=payload.provider_id,
        amount_cents=payload.amount_cents,
        direction=payload.direction,
        source_queue=payload.source_queue,
        claims=[claim.model_dump() for claim in payload.claims],
    )
    result = _reconcile(db, txn.correlation_id)
    if result:
        return {"status": result.status, "correlation_id": result.correlation_id, "message": result.message}
    return {"status": "PENDING", "correlation_id": txn.correlation_id}
