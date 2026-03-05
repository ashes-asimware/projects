import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from shared.middleware import apply_common_middleware
from shared.events.topics import (
    ACH_RETURN_TOPIC,
    EFT_MATCHED_TOPIC,
    EFT_RECEIVED_TOPIC,
    PAYOUT_SENT_TOPIC,
)
from .db import Base, SessionLocal, engine
from .models import JournalEntry, JournalLine
from .schemas import JournalEntryResponse, PostEntryRequest

logger = logging.getLogger(__name__)

# Queues this service subscribes to
SUBSCRIBED_QUEUES = [
    EFT_RECEIVED_TOPIC,
    EFT_MATCHED_TOPIC,
    PAYOUT_SENT_TOPIC,
    ACH_RETURN_TOPIC,
]

# Maps each queue to a ledger entry type
_QUEUE_ENTRY_TYPES: dict[str, str] = {
    EFT_RECEIVED_TOPIC: "EFT_RECEIVED",
    EFT_MATCHED_TOPIC: "EFT_MATCHED",
    PAYOUT_SENT_TOPIC: "PAYOUT_SENT",
    ACH_RETURN_TOPIC: "ACH_RETURN",
}

# Maps each queue to (debit_account, credit_account) codes
_QUEUE_ACCOUNTS: dict[str, tuple[str, str]] = {
    EFT_RECEIVED_TOPIC: ("1010-CASH-CLEARING", "2010-EFT-SUSPENSE"),
    EFT_MATCHED_TOPIC: ("2010-EFT-SUSPENSE", "2020-CLAIMS-PAYABLE"),
    PAYOUT_SENT_TOPIC: ("2020-CLAIMS-PAYABLE", "1010-CASH-CLEARING"),
    ACH_RETURN_TOPIC: ("2010-EFT-SUSPENSE", "2030-ACH-RETURNS"),
}


def get_db() -> Session:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _persist_entry(
    db: Session,
    correlation_id: str,
    entry_type: str,
    source_queue: str,
    lines: list[dict],
) -> JournalEntry:
    """Insert an immutable JournalEntry with its debit/credit lines."""
    entry = JournalEntry(
        correlation_id=correlation_id,
        entry_type=entry_type,
        source_queue=source_queue,
    )
    db.add(entry)
    db.flush()  # populate entry.id before inserting lines
    for line in lines:
        db.add(
            JournalLine(
                journal_entry_id=entry.id,
                line_type=line["line_type"],
                account_code=line["account_code"],
                amount_cents=line["amount_cents"],
            )
        )
    db.commit()
    db.refresh(entry)
    return entry


async def _handle_queue_message(queue_name: str, body: str) -> None:
    """Parse an inter-service event and record the corresponding journal entry."""
    data = json.loads(body)
    correlation_id = data.get("correlation_id", "")
    claims = data.get("claims", [])
    total_cents = sum(c.get("amount_cents", 0) for c in claims)
    debit_account, credit_account = _QUEUE_ACCOUNTS[queue_name]
    lines = [
        {"line_type": "DEBIT", "account_code": debit_account, "amount_cents": total_cents},
        {"line_type": "CREDIT", "account_code": credit_account, "amount_cents": total_cents},
    ]
    db = SessionLocal()
    try:
        _persist_entry(db, correlation_id, _QUEUE_ENTRY_TYPES[queue_name], queue_name, lines)
    finally:
        db.close()


async def _consume_queue(queue_name: str) -> None:
    """Background loop: receive messages from a Service Bus queue and journal them."""
    conn_str = os.getenv("AZURE_SERVICEBUS_CONNECTION_STRING") or os.getenv(
        "SERVICEBUS_CONNECTION_STRING"
    )
    if not conn_str:
        logger.warning(
            "No Service Bus connection string configured; queue consumer for %s disabled",
            queue_name,
        )
        return
    try:
        from azure.servicebus.aio import ServiceBusClient as AsyncServiceBusClient  # type: ignore[import]
    except ImportError:  # pragma: no cover
        logger.warning(
            "azure-servicebus not installed; queue consumer for %s disabled", queue_name
        )
        return

    while True:
        try:
            async with AsyncServiceBusClient.from_connection_string(conn_str) as sb_client:
                async with sb_client.get_queue_receiver(
                    queue_name=queue_name, max_wait_time=5
                ) as receiver:
                    async for message in receiver:
                        body = b"".join(message.body).decode("utf-8")
                        try:
                            await _handle_queue_message(queue_name, body)
                            await receiver.complete_message(message)
                        except Exception as exc:
                            logger.error(
                                "Failed to process message from %s: %s", queue_name, exc
                            )
                            await receiver.dead_letter_message(
                                message,
                                reason="processing_failed",
                                error_description=str(exc),
                            )
        except asyncio.CancelledError:
            return
        except Exception as exc:
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


app = FastAPI(title="ledger_service", lifespan=lifespan)
apply_common_middleware(app)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "ledger_service"}


@app.post("/post-entry", response_model=JournalEntryResponse)
def post_entry(payload: PostEntryRequest, db: Session = Depends(get_db)) -> JournalEntryResponse:
    entry = _persist_entry(
        db,
        correlation_id=payload.correlation_id,
        entry_type=payload.entry_type,
        source_queue="",
        lines=[line.model_dump() for line in payload.lines],
    )
    return JournalEntryResponse.model_validate(entry)
