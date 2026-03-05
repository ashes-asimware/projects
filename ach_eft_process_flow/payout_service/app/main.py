import asyncio
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy.orm import Session

from shared.middleware import apply_common_middleware
from shared.events.schemas import ClaimReference, ProviderPayoutInitiated
from shared.servicebus.client import ServiceBusPublisher

from .db import Base, SessionLocal, engine
from .models import PayoutRecord, ProviderBalance
from .schemas import PayoutInitiatedResponse, ProviderBalanceResponse

logger = logging.getLogger(__name__)

SUBSCRIBED_QUEUE = "provider_balance_updates_queue"


def _payout_threshold_cents() -> int:
    try:
        return int(os.getenv("PAYOUT_THRESHOLD_CENTS", "500000"))
    except ValueError:
        return 500000


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _set_balance(db: Session, provider_id: str, balance_cents: int) -> ProviderBalance:
    record = db.query(ProviderBalance).filter_by(provider_id=provider_id).first()
    if record is None:
        record = ProviderBalance(provider_id=provider_id, balance_cents=balance_cents)
        db.add(record)
    else:
        record.balance_cents = balance_cents
    record.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(record)
    return record


def _initiate_payout(db: Session, balance: ProviderBalance, amount_cents: int) -> ProviderPayoutInitiated:
    correlation_id = f"payout-{balance.provider_id}-{uuid.uuid4().hex}"
    payout_record = PayoutRecord(
        provider_id=balance.provider_id,
        amount_cents=amount_cents,
        correlation_id=correlation_id,
    )
    db.add(payout_record)
    balance.balance_cents = max(balance.balance_cents - amount_cents, 0)
    balance.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(balance)
    event = ProviderPayoutInitiated(
        correlation_id=correlation_id,
        trace_number=balance.provider_id,
        payer_id="platform",
        provider_id=balance.provider_id,
        claims=[ClaimReference(claim_id="payout", amount_cents=amount_cents)],
    )
    publisher.send(queue_name="payout_initiated_queue", message=event.model_dump_json())
    return event


def _process_balance_update(db: Session, provider_id: str, balance_cents: int) -> ProviderPayoutInitiated | None:
    balance = _set_balance(db, provider_id, balance_cents)
    threshold = _payout_threshold_cents()
    if balance.balance_cents >= threshold:
        return _initiate_payout(db, balance, balance.balance_cents)
    return None


async def _handle_queue_message(body: str) -> ProviderPayoutInitiated | None:
    data = json.loads(body)
    db = SessionLocal()
    try:
        return _process_balance_update(
            db,
            data.get("provider_id", ""),
            int(data.get("balance_cents", 0)),
        )
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


app = FastAPI(title="payout_service", lifespan=lifespan)
apply_common_middleware(app)
publisher = ServiceBusPublisher()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "payout_service"}


@app.get("/provider/{provider_id}/balance", response_model=ProviderBalanceResponse)
def get_balance(provider_id: str, db: Session = Depends(get_db)) -> ProviderBalanceResponse:
    balance = db.query(ProviderBalance).filter_by(provider_id=provider_id).first()
    if balance is None:
        balance = ProviderBalance(provider_id=provider_id, balance_cents=0)
        db.add(balance)
        db.commit()
        db.refresh(balance)
    return ProviderBalanceResponse(provider_id=balance.provider_id, balance_cents=balance.balance_cents)


@app.post("/trigger-payout/{provider_id}", response_model=PayoutInitiatedResponse)
def trigger_payout(provider_id: str, db: Session = Depends(get_db)) -> PayoutInitiatedResponse:
    balance = db.query(ProviderBalance).filter_by(provider_id=provider_id).first()
    if balance is None:
        raise HTTPException(status_code=404, detail="Provider balance not found")
    if balance.balance_cents <= 0:
        raise HTTPException(status_code=400, detail="No available balance for payout")
    event = _initiate_payout(db, balance, balance.balance_cents)
    return PayoutInitiatedResponse(
        provider_id=provider_id,
        amount_cents=event.claims[0].amount_cents if event.claims else 0,
        correlation_id=event.correlation_id,
    )
