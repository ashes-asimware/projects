import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from shared.middleware import apply_common_middleware
from shared.servicebus.client import ServiceBusPublisher

from .db import Base, SessionLocal, engine
from .models import ProviderBalance
from .schemas import ProviderBalanceResponse

logger = logging.getLogger(__name__)

SUBSCRIBED_QUEUE = "eft_matched_queue"


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _add_to_provider_balance(db: Session, provider_id: str, delta_cents: int) -> ProviderBalance:
    record = db.query(ProviderBalance).filter_by(provider_id=provider_id).first()
    if record is None:
        record = ProviderBalance(provider_id=provider_id, balance_cents=0)
        db.add(record)
        db.flush()
    record.balance_cents += delta_cents
    record.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(record)
    return record


def _publish_balance_update(balance: ProviderBalance) -> None:
    payload = {
        "provider_id": balance.provider_id,
        "balance_cents": balance.balance_cents,
        "updated_at": balance.updated_at.isoformat(),
    }
    publisher.send(queue_name="provider_balance_updates_queue", message=json.dumps(payload))


async def _handle_queue_message(body: str) -> ProviderBalance:
    data = json.loads(body)
    claims = data.get("claims") or []
    total_cents = sum(int(c.get("amount_cents", 0)) for c in claims)
    db = SessionLocal()
    try:
        balance = _add_to_provider_balance(db, data.get("provider_id", ""), total_cents)
        _publish_balance_update(balance)
        return balance
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


app = FastAPI(title="provider_ledger_service", lifespan=lifespan)
apply_common_middleware(app)
publisher = ServiceBusPublisher()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "provider_ledger_service"}


@app.get("/provider/{provider_id}/balance", response_model=ProviderBalanceResponse)
def get_balance(provider_id: str, db: Session = Depends(get_db)) -> ProviderBalanceResponse:
    balance = db.query(ProviderBalance).filter_by(provider_id=provider_id).first()
    if balance is None:
        balance = ProviderBalance(provider_id=provider_id, balance_cents=0)
        db.add(balance)
        db.commit()
        db.refresh(balance)
    return ProviderBalanceResponse(provider_id=balance.provider_id, balance_cents=balance.balance_cents)
