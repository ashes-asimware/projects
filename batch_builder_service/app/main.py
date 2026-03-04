import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from shared.events.schemas import ClaimReference, ProviderPayoutInitiated, ProviderPayoutSent
from shared.servicebus.client import ServiceBusPublisher

from .db import Base, SessionLocal, engine
from .models import PayoutBatch, PayoutBatchItem
from .schemas import BatchBuilderServiceRequest

logger = logging.getLogger(__name__)

SUBSCRIBED_QUEUE = "payout_initiated_queue"
publisher = ServiceBusPublisher()
_batch_buffer: dict[str, list[ProviderPayoutInitiated]] = {}


def _batch_size() -> int:
    try:
        return int(os.getenv("BATCH_BUILDER_BATCH_SIZE", "5"))
    except ValueError:
        return 5


def _to_claims(amount_cents: int, claims: list[ClaimReference]) -> list[ClaimReference]:
    if claims:
        return claims
    return [ClaimReference(claim_id="payout", amount_cents=amount_cents)]


def _to_ach_entry(event: ProviderPayoutInitiated) -> dict:
    amount_cents = sum(c.amount_cents for c in event.claims) if event.claims else 0
    return {
        "trace_number": event.trace_number,
        "provider_id": event.provider_id,
        "payer_id": event.payer_id,
        "amount_cents": amount_cents,
    }


def _send_to_mock_bank_adapter(batch_id: str, nacha_payload: dict) -> dict:
    logger.info("Sending NACHA batch %s to mock bank adapter with %d entries", batch_id, len(nacha_payload["entries"]))
    return {"batch_id": batch_id, "status": "accepted", "entries": len(nacha_payload["entries"])}


def _persist_batch(db: Session, payer_id: str, batch_id: str, events: list[ProviderPayoutInitiated]) -> None:
    total_cents = sum(sum(c.amount_cents for c in e.claims) for e in events)
    batch = PayoutBatch(
        batch_id=batch_id,
        payer_id=payer_id,
        total_cents=total_cents,
        item_count=len(events),
        status="SENT",
    )
    db.add(batch)
    for event in events:
        item_amount = sum(c.amount_cents for c in event.claims)
        db.add(
            PayoutBatchItem(
                batch_id=batch_id,
                correlation_id=event.correlation_id,
                provider_id=event.provider_id,
                trace_number=event.trace_number,
                amount_cents=item_amount,
                status="SENT",
            )
        )
    db.commit()


def _flush_batch(payer_id: str, db: Session) -> list[ProviderPayoutSent]:
    events = _batch_buffer.pop(payer_id, [])
    if not events:
        return []
    batch_id = f"nacha-{uuid.uuid4().hex[:10]}"
    nacha_entries = [_to_ach_entry(evt) for evt in events]
    nacha_payload = {"batch_id": batch_id, "entries": nacha_entries}
    _persist_batch(db, payer_id, batch_id, events)
    _send_to_mock_bank_adapter(batch_id, nacha_payload)

    sent_events: list[ProviderPayoutSent] = []
    for evt in events:
        payout_sent = ProviderPayoutSent(
            correlation_id=evt.correlation_id,
            trace_number=evt.trace_number,
            payer_id=evt.payer_id,
            provider_id=evt.provider_id,
            claims=evt.claims,
        )
        publisher.send(queue_name="payout_sent_queue", message=payout_sent.model_dump_json())
        sent_events.append(payout_sent)
    return sent_events


def _enqueue_payout(event: ProviderPayoutInitiated, db: Session) -> list[ProviderPayoutSent]:
    buffer = _batch_buffer.setdefault(event.payer_id, [])
    buffer.append(event)
    if len(buffer) >= _batch_size():
        return _flush_batch(event.payer_id, db)
    return []


def _from_request(payload: BatchBuilderServiceRequest) -> ProviderPayoutInitiated:
    correlation_id = payload.correlation_id or f"payout-{payload.provider_id}-{uuid.uuid4().hex}"
    trace_number = payload.trace_number or payload.provider_id
    claims = _to_claims(payload.amount_cents, payload.claims)
    return ProviderPayoutInitiated(
        correlation_id=correlation_id,
        trace_number=trace_number,
        payer_id=payload.payer_id,
        provider_id=payload.provider_id,
        claims=claims,
    )


async def _handle_queue_message(body: str) -> list[ProviderPayoutSent]:
    data = json.loads(body)
    try:
        event = ProviderPayoutInitiated.model_validate(data)
    except Exception:
        event = _from_request(BatchBuilderServiceRequest(**data))
    db = SessionLocal()
    try:
        return _enqueue_payout(event, db)
    finally:
        db.close()


async def _consume_queue() -> None:
    conn_str = os.getenv("AZURE_SERVICEBUS_CONNECTION_STRING") or os.getenv("SERVICEBUS_CONNECTION_STRING")
    if not conn_str:
        logger.warning("No Service Bus connection string configured; queue consumer for %s disabled", SUBSCRIBED_QUEUE)
        return
    try:
        from azure.servicebus.aio import ServiceBusClient as AsyncServiceBusClient  # type: ignore[import]
    except ImportError:  # pragma: no cover
        logger.warning("azure-servicebus not installed; queue consumer for %s disabled", SUBSCRIBED_QUEUE)
        return

    while True:
        try:
            async with AsyncServiceBusClient.from_connection_string(conn_str) as sb_client:
                async with sb_client.get_queue_receiver(queue_name=SUBSCRIBED_QUEUE, max_wait_time=5) as receiver:
                    async for message in receiver:
                        body = b"".join(message.body).decode("utf-8")
                        try:
                            await _handle_queue_message(body)
                            await receiver.complete_message(message)
                        except Exception as exc:  # pragma: no cover
                            logger.error("Failed to process message from %s: %s", SUBSCRIBED_QUEUE, exc)
                            await receiver.dead_letter_message(
                                message,
                                reason="processing_failed",
                                error_description=str(exc),
                            )
        except asyncio.CancelledError:
            return
        except Exception as exc:  # pragma: no cover
            logger.error("Queue consumer error for %s: %s", SUBSCRIBED_QUEUE, exc)
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    task = asyncio.create_task(_consume_queue())
    yield
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="batch_builder_service", lifespan=lifespan)


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "batch_builder_service"}


@app.post("/process", response_model=list[ProviderPayoutSent])
def process(payload: BatchBuilderServiceRequest, db: Session = Depends(get_db)) -> list[ProviderPayoutSent]:
    event = _from_request(payload)
    sent_events = _enqueue_payout(event, db)
    return sent_events


@app.post("/flush/{payer_id}", response_model=list[ProviderPayoutSent])
def flush_batch(payer_id: str, db: Session = Depends(get_db)) -> list[ProviderPayoutSent]:
    return _flush_batch(payer_id, db)
