import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from shared.middleware import apply_common_middleware
from shared.events.schemas import ClaimPaymentPostedV1, ClaimReference
from shared.events.topics import CLAIM_PAYMENT_POSTED_TOPIC
from shared.servicebus.client import ServiceBusPublisher

from .db import Base, SessionLocal, engine
from .models import ClaimPaymentRecord
from .schemas import ClaimSystemAdapterRequest

logger = logging.getLogger(__name__)

SUBSCRIBED_QUEUE = CLAIM_PAYMENT_POSTED_TOPIC
publisher = ServiceBusPublisher()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


async def _call_claim_system_api(payload: ClaimSystemAdapterRequest) -> dict:
    base_url = os.getenv("CLAIM_SYSTEM_BASE_URL")
    if not base_url:
        logger.info("No CLAIM_SYSTEM_BASE_URL configured; using mock update for claim %s", payload.claim_id)
        return {"status": "mocked"}
    try:
        import httpx
    except ImportError:  # pragma: no cover
        logger.info("httpx not installed; skipping external call for claim %s", payload.claim_id)
        return {"status": "mocked"}

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{base_url}/claims/{payload.claim_id}/pay",
            json={
                "amount_cents": payload.amount_cents,
                "patient_responsibility_cents": payload.patient_responsibility_cents,
            },
            timeout=5,
        )
        response.raise_for_status()
        return response.json()


def _persist_claim_payment(db: Session, payload: ClaimSystemAdapterRequest) -> ClaimPaymentRecord:
    record = ClaimPaymentRecord(
        claim_id=payload.claim_id,
        provider_id=payload.provider_id,
        amount_cents=payload.amount_cents,
        patient_responsibility_cents=payload.patient_responsibility_cents,
        status="RECEIVED",
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _publish_claim_posted(record: ClaimPaymentRecord) -> ClaimPaymentPostedV1:
    event = ClaimPaymentPostedV1(
        correlation_id=record.claim_id,
        trace_number=record.claim_id,
        payer_id="platform",
        provider_id=record.provider_id,
        claims=[ClaimReference(claim_id=record.claim_id, amount_cents=record.amount_cents)],
    )
    publisher.send(queue_name=CLAIM_PAYMENT_POSTED_TOPIC, message=event.model_dump_json())
    return event


async def _handle_queue_message(body: str) -> ClaimPaymentRecord:
    data = json.loads(body)
    payload = ClaimSystemAdapterRequest(**data)
    db = SessionLocal()
    try:
        record = _persist_claim_payment(db, payload)
        await _call_claim_system_api(payload)
        record.status = "PAID"
        db.commit()
        db.refresh(record)
        _publish_claim_posted(record)
        return record
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


app = FastAPI(title="claim_system_adapter", lifespan=lifespan)
apply_common_middleware(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "claim_system_adapter"}


@app.post("/process", response_model=ClaimPaymentPostedV1)
async def process(payload: ClaimSystemAdapterRequest, db: Session = Depends(get_db)) -> ClaimPaymentPostedV1:
    record = _persist_claim_payment(db, payload)
    await _call_claim_system_api(payload)
    record.status = "PAID"
    db.commit()
    db.refresh(record)
    return _publish_claim_posted(record)
