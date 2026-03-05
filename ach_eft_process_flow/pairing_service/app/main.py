import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from shared.middleware import apply_common_middleware
from shared.events.schemas import ClaimReference, EFTMatchedToRemittance
from shared.servicebus.client import ServiceBusPublisher

from .db import Base, SessionLocal, engine
from .models import EFTReceipt, RemittanceReceipt

logger = logging.getLogger(__name__)

SUBSCRIBED_QUEUES = ("eft_received_queue", "remittance_received_queue")


def _total_amount_from_claims(claims: list[dict] | None) -> int:
    if not claims:
        return 0
    return sum(int(c.get("amount_cents", 0)) for c in claims)


def _attempt_match(db: Session, eft: EFTReceipt | None, remittance: RemittanceReceipt | None) -> EFTMatchedToRemittance | None:
    if not eft or not remittance:
        return None
    if eft.matched and remittance.matched:
        return None

    eft.matched = True
    remittance.matched = True
    db.commit()
    db.refresh(eft)
    db.refresh(remittance)

    event = EFTMatchedToRemittance(
        correlation_id=eft.correlation_id or remittance.correlation_id,
        trace_number=eft.trace_number,
        payer_id=eft.payer_id,
        provider_id=eft.provider_id,
        claims=[ClaimReference(**claim) for claim in remittance.claims],
    )
    publisher.send(queue_name="eft_matched_queue", message=event.model_dump_json())
    return event


def _get_match_key(data: dict) -> tuple[str, str, str, int]:
    claims = data.get("claims", [])
    return (
        data.get("trace_number", ""),
        data.get("payer_id", ""),
        data.get("provider_id", ""),
        int(data.get("amount_cents", _total_amount_from_claims(claims))),
    )


def _handle_eft_payload(db: Session, data: dict) -> EFTMatchedToRemittance | None:
    trace_number, payer_id, provider_id, amount_cents = _get_match_key(data)
    existing = (
        db.query(EFTReceipt)
        .filter_by(trace_number=trace_number, payer_id=payer_id, provider_id=provider_id, amount_cents=amount_cents)
        .first()
    )
    if existing is None:
        existing = EFTReceipt(
            correlation_id=data.get("correlation_id", ""),
            trace_number=trace_number,
            payer_id=payer_id,
            provider_id=provider_id,
            amount_cents=amount_cents,
            claims=data.get("claims") or [],
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)

    remittance = (
        db.query(RemittanceReceipt)
        .filter_by(trace_number=trace_number, payer_id=payer_id, provider_id=provider_id, amount_cents=amount_cents)
        .first()
    )
    return _attempt_match(db, existing, remittance)


def _handle_remittance_payload(db: Session, data: dict) -> EFTMatchedToRemittance | None:
    trace_number, payer_id, provider_id, amount_cents = _get_match_key(data)
    claims = data.get("claims") or []
    existing = (
        db.query(RemittanceReceipt)
        .filter_by(trace_number=trace_number, payer_id=payer_id, provider_id=provider_id, amount_cents=amount_cents)
        .first()
    )
    if existing is None:
        existing = RemittanceReceipt(
            correlation_id=data.get("correlation_id", ""),
            trace_number=trace_number,
            payer_id=payer_id,
            provider_id=provider_id,
            amount_cents=amount_cents,
            claims=claims,
        )
        db.add(existing)
        db.commit()
        db.refresh(existing)

    eft = (
        db.query(EFTReceipt)
        .filter_by(trace_number=trace_number, payer_id=payer_id, provider_id=provider_id, amount_cents=amount_cents)
        .first()
    )
    return _attempt_match(db, eft, existing)


async def _handle_queue_message(queue_name: str, body: str) -> EFTMatchedToRemittance | None:
    data = json.loads(body)
    db = SessionLocal()
    try:
        if queue_name == "eft_received_queue":
            return _handle_eft_payload(db, data)
        if queue_name == "remittance_received_queue":
            return _handle_remittance_payload(db, data)
    finally:
        db.close()
    return None


async def _consume_queue(queue_name: str) -> None:
    conn_str = os.getenv("AZURE_SERVICEBUS_CONNECTION_STRING") or os.getenv("SERVICEBUS_CONNECTION_STRING")
    if not conn_str:
        logger.warning("No Service Bus connection string configured; queue consumer for %s disabled", queue_name)
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
                        except Exception as exc:  # pragma: no cover - defensive
                            logger.error("Failed to process message from %s: %s", queue_name, exc)
                            await receiver.dead_letter_message(
                                message,
                                reason="processing_failed",
                                error_description=str(exc),
                            )
        except asyncio.CancelledError:
            return
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("Queue consumer error for %s: %s", queue_name, exc)
            await asyncio.sleep(5)


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    tasks = [asyncio.create_task(_consume_queue(queue)) for queue in SUBSCRIBED_QUEUES]
    yield
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


app = FastAPI(title="pairing_service", lifespan=lifespan)
apply_common_middleware(app)
publisher = ServiceBusPublisher()


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "pairing_service"}
