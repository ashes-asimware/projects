import asyncio
import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.events.topics import ACH_RETURN_TOPIC, EFT_MATCHED_TOPIC, EFT_RECEIVED_TOPIC, PAYOUT_SENT_TOPIC
# Use an in-memory SQLite database with StaticPool so all sessions share the same connection
_TEST_DATABASE_URL = "sqlite:///:memory:"


def _make_test_app():
    """Create a fresh FastAPI test app backed by an in-memory SQLite database."""
    import ledger_service.app.db as db_module
    import ledger_service.app.main as main_module

    test_engine = create_engine(
        _TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    # Patch the module-level engine and SessionLocal used by the app
    db_module.engine = test_engine
    db_module.SessionLocal = TestSessionLocal
    main_module.engine = test_engine
    main_module.SessionLocal = TestSessionLocal

    from ledger_service.app.db import Base
    import ledger_service.app.models  # noqa: F401 - registers ORM classes with Base

    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    from ledger_service.app.main import app, get_db

    app.dependency_overrides[get_db] = override_get_db
    return app, TestSessionLocal, test_engine


class LedgerServiceEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.app, self.SessionLocal, self.engine = _make_test_app()
        self.client = TestClient(self.app, raise_server_exceptions=True)

    def tearDown(self) -> None:
        from ledger_service.app.main import app, get_db

        app.dependency_overrides.pop(get_db, None)
        from ledger_service.app.db import Base

        Base.metadata.drop_all(bind=self.engine)

    # ------------------------------------------------------------------
    # Health check
    # ------------------------------------------------------------------

    def test_health_returns_ok(self) -> None:
        response = self.client.get("/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok", "service": "ledger_service"})

    # ------------------------------------------------------------------
    # POST /post-entry
    # ------------------------------------------------------------------

    def test_post_entry_creates_journal_entry_with_lines(self) -> None:
        payload = {
            "correlation_id": "corr-abc",
            "entry_type": "EFT_RECEIVED",
            "lines": [
                {"line_type": "DEBIT", "account_code": "1010-CASH-CLEARING", "amount_cents": 5000},
                {"line_type": "CREDIT", "account_code": "2010-EFT-SUSPENSE", "amount_cents": 5000},
            ],
        }
        response = self.client.post("/post-entry", json=payload)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["correlation_id"], "corr-abc")
        self.assertEqual(data["entry_type"], "EFT_RECEIVED")
        self.assertEqual(data["source_queue"], "")
        self.assertIn("created_at", data)
        self.assertEqual(len(data["lines"]), 2)
        line_types = {line["line_type"] for line in data["lines"]}
        self.assertEqual(line_types, {"DEBIT", "CREDIT"})

    def test_post_entry_persists_to_database(self) -> None:
        payload = {
            "correlation_id": "corr-persist",
            "entry_type": "PAYOUT_SENT",
            "lines": [
                {"line_type": "DEBIT", "account_code": "2020-CLAIMS-PAYABLE", "amount_cents": 1000},
                {"line_type": "CREDIT", "account_code": "1010-CASH-CLEARING", "amount_cents": 1000},
            ],
        }
        self.client.post("/post-entry", json=payload)

        from ledger_service.app.models import JournalEntry, JournalLine

        db = self.SessionLocal()
        try:
            entry = db.query(JournalEntry).filter_by(correlation_id="corr-persist").first()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.entry_type, "PAYOUT_SENT")
            lines = db.query(JournalLine).filter_by(journal_entry_id=entry.id).all()
            self.assertEqual(len(lines), 2)
        finally:
            db.close()

    def test_post_entry_returns_all_line_fields(self) -> None:
        payload = {
            "correlation_id": "corr-fields",
            "entry_type": "ACH_RETURN",
            "lines": [
                {"line_type": "DEBIT", "account_code": "2010-EFT-SUSPENSE", "amount_cents": 250},
                {"line_type": "CREDIT", "account_code": "2030-ACH-RETURNS", "amount_cents": 250},
            ],
        }
        response = self.client.post("/post-entry", json=payload)
        lines = response.json()["lines"]
        for line in lines:
            self.assertIn("id", line)
            self.assertIn("line_type", line)
            self.assertIn("account_code", line)
            self.assertIn("amount_cents", line)

    def test_post_entry_missing_required_fields_returns_422(self) -> None:
        response = self.client.post("/post-entry", json={"correlation_id": "only-id"})
        self.assertEqual(response.status_code, 422)

    def test_post_entry_invalid_line_type_returns_422(self) -> None:
        payload = {
            "correlation_id": "corr-bad",
            "entry_type": "EFT_RECEIVED",
            "lines": [
                {"line_type": "INVALID", "account_code": "1010", "amount_cents": 100},
            ],
        }
        response = self.client.post("/post-entry", json=payload)
        self.assertEqual(response.status_code, 422)


class LedgerServiceQueueHandlerTests(unittest.IsolatedAsyncioTestCase):
    """Tests for the queue message handler that creates journal entries."""

    def setUp(self) -> None:
        self.app, self.SessionLocal, self.engine = _make_test_app()

    def tearDown(self) -> None:
        from ledger_service.app.db import Base

        Base.metadata.drop_all(bind=self.engine)

    async def test_handle_eft_received_queue_message(self) -> None:
        from ledger_service.app.main import _handle_queue_message
        from ledger_service.app.models import JournalEntry, JournalLine

        event = {
            "correlation_id": "corr-eft",
            "trace_number": "trace-1",
            "payer_id": "payer-1",
            "provider_id": "provider-1",
            "claims": [{"claim_id": "c1", "amount_cents": 3000}],
        }
        await _handle_queue_message(EFT_RECEIVED_TOPIC, json.dumps(event))

        db = self.SessionLocal()
        try:
            entry = db.query(JournalEntry).filter_by(correlation_id="corr-eft").first()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.entry_type, "EFT_RECEIVED")
            self.assertEqual(entry.source_queue, EFT_RECEIVED_TOPIC)
            lines = db.query(JournalLine).filter_by(journal_entry_id=entry.id).all()
            self.assertEqual(len(lines), 2)
            debit = next(l for l in lines if l.line_type == "DEBIT")
            credit = next(l for l in lines if l.line_type == "CREDIT")
            self.assertEqual(debit.account_code, "1010-CASH-CLEARING")
            self.assertEqual(credit.account_code, "2010-EFT-SUSPENSE")
            self.assertEqual(debit.amount_cents, 3000)
            self.assertEqual(credit.amount_cents, 3000)
        finally:
            db.close()

    async def test_handle_eft_matched_queue_message(self) -> None:
        from ledger_service.app.main import _handle_queue_message
        from ledger_service.app.models import JournalEntry, JournalLine

        event = {
            "correlation_id": "corr-matched",
            "trace_number": "t2",
            "payer_id": "p2",
            "provider_id": "pr2",
            "claims": [{"claim_id": "c2", "amount_cents": 8000}],
        }
        await _handle_queue_message(EFT_MATCHED_TOPIC, json.dumps(event))

        db = self.SessionLocal()
        try:
            entry = db.query(JournalEntry).filter_by(correlation_id="corr-matched").first()
            self.assertEqual(entry.entry_type, "EFT_MATCHED")
            lines = db.query(JournalLine).filter_by(journal_entry_id=entry.id).all()
            debit = next(l for l in lines if l.line_type == "DEBIT")
            credit = next(l for l in lines if l.line_type == "CREDIT")
            self.assertEqual(debit.account_code, "2010-EFT-SUSPENSE")
            self.assertEqual(credit.account_code, "2020-CLAIMS-PAYABLE")
        finally:
            db.close()

    async def test_handle_provider_payout_sent_queue_message(self) -> None:
        from ledger_service.app.main import _handle_queue_message
        from ledger_service.app.models import JournalEntry, JournalLine

        event = {
            "correlation_id": "corr-payout",
            "trace_number": "t3",
            "payer_id": "p3",
            "provider_id": "pr3",
            "claims": [{"claim_id": "c3", "amount_cents": 4500}],
        }
        await _handle_queue_message(PAYOUT_SENT_TOPIC, json.dumps(event))

        db = self.SessionLocal()
        try:
            entry = db.query(JournalEntry).filter_by(correlation_id="corr-payout").first()
            self.assertEqual(entry.entry_type, "PAYOUT_SENT")
            lines = db.query(JournalLine).filter_by(journal_entry_id=entry.id).all()
            debit = next(l for l in lines if l.line_type == "DEBIT")
            credit = next(l for l in lines if l.line_type == "CREDIT")
            self.assertEqual(debit.account_code, "2020-CLAIMS-PAYABLE")
            self.assertEqual(credit.account_code, "1010-CASH-CLEARING")
        finally:
            db.close()

    async def test_handle_ach_return_queue_message(self) -> None:
        from ledger_service.app.main import _handle_queue_message
        from ledger_service.app.models import JournalEntry, JournalLine

        event = {
            "correlation_id": "corr-ach",
            "trace_number": "t4",
            "payer_id": "p4",
            "provider_id": "pr4",
            "claims": [{"claim_id": "c4", "amount_cents": 2000}],
        }
        await _handle_queue_message(ACH_RETURN_TOPIC, json.dumps(event))

        db = self.SessionLocal()
        try:
            entry = db.query(JournalEntry).filter_by(correlation_id="corr-ach").first()
            self.assertEqual(entry.entry_type, "ACH_RETURN")
            lines = db.query(JournalLine).filter_by(journal_entry_id=entry.id).all()
            debit = next(l for l in lines if l.line_type == "DEBIT")
            credit = next(l for l in lines if l.line_type == "CREDIT")
            self.assertEqual(debit.account_code, "2010-EFT-SUSPENSE")
            self.assertEqual(credit.account_code, "2030-ACH-RETURNS")
        finally:
            db.close()

    async def test_handle_queue_message_with_no_claims_uses_zero_amount(self) -> None:
        from ledger_service.app.main import _handle_queue_message
        from ledger_service.app.models import JournalEntry, JournalLine

        event = {"correlation_id": "corr-zero", "claims": []}
        await _handle_queue_message(EFT_RECEIVED_TOPIC, json.dumps(event))

        db = self.SessionLocal()
        try:
            entry = db.query(JournalEntry).filter_by(correlation_id="corr-zero").first()
            lines = db.query(JournalLine).filter_by(journal_entry_id=entry.id).all()
            for line in lines:
                self.assertEqual(line.amount_cents, 0)
        finally:
            db.close()


class LedgerServiceConsumerTests(unittest.IsolatedAsyncioTestCase):
    """Tests for the background queue consumer lifecycle."""

    async def test_consume_queue_exits_gracefully_without_connection_string(self) -> None:
        from ledger_service.app.main import _consume_queue

        with patch.dict("os.environ", {}, clear=True):
            # Should return without error when no connection string is configured
            await asyncio.wait_for(_consume_queue(EFT_RECEIVED_TOPIC), timeout=1.0)


if __name__ == "__main__":
    unittest.main()
