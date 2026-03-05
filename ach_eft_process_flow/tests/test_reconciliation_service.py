import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.events.topics import (
    BANK_STATEMENT_TOPIC,
    EFT_MATCHED_TOPIC,
    EFT_RECEIVED_TOPIC,
    PAYOUT_SENT_TOPIC,
    RECONCILIATION_TOPIC,
)

_TEST_DATABASE_URL = "sqlite:///:memory:"


def _setup_test_db():
    import reconciliation_service.app.db as db_module
    import reconciliation_service.app.main as main_module

    test_engine = create_engine(
        _TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

    db_module.engine = test_engine
    db_module.SessionLocal = TestSessionLocal
    main_module.engine = test_engine
    main_module.SessionLocal = TestSessionLocal

    from reconciliation_service.app.db import Base
    import reconciliation_service.app.models  # noqa: F401

    Base.metadata.create_all(bind=test_engine)
    return TestSessionLocal, test_engine


class ReconciliationServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.SessionLocal, self.engine = _setup_test_db()

    def tearDown(self) -> None:
        from reconciliation_service.app.db import Base

        Base.metadata.drop_all(bind=self.engine)

    async def test_matching_events_publish_completion(self) -> None:
        from reconciliation_service.app.main import _handle_queue_message

        bank_statement = {
            "correlation_id": "corr-1",
            "trace_number": "trace-1",
            "payer_id": "payer-a",
            "provider_id": "prov-a",
            "claims": [{"claim_id": "BANK_STMT", "amount_cents": 1000}],
        }
        payout_sent = {
            "correlation_id": "corr-1",
            "trace_number": "trace-1",
            "payer_id": "payer-a",
            "provider_id": "prov-a",
            "claims": [{"claim_id": "payout", "amount_cents": 1000}],
            "direction": "DEBIT",
        }

        with patch("reconciliation_service.app.main.publisher.send", return_value=True) as send_mock:
            await _handle_queue_message(BANK_STATEMENT_TOPIC, json.dumps(bank_statement))
            result = await _handle_queue_message(PAYOUT_SENT_TOPIC, json.dumps(payout_sent))

        self.assertIsNotNone(result)
        _, kwargs = send_mock.call_args
        self.assertEqual(kwargs["queue_name"], RECONCILIATION_TOPIC)
        payload = json.loads(kwargs["message"])
        self.assertEqual(payload["correlation_id"], "corr-1")

    async def test_mismatched_amounts_raise_exception_event(self) -> None:
        from reconciliation_service.app.main import _handle_queue_message

        eft_received = {
            "correlation_id": "corr-2",
            "trace_number": "trace-2",
            "payer_id": "payer-b",
            "provider_id": "prov-b",
            "claims": [{"claim_id": "eft", "amount_cents": 1200}],
        }
        bank_statement = {
            "correlation_id": "corr-2",
            "trace_number": "trace-2",
            "payer_id": "payer-b",
            "provider_id": "prov-b",
            "claims": [{"claim_id": "BANK_STMT", "amount_cents": 1000}],
        }

        with patch("reconciliation_service.app.main.publisher.send", return_value=True) as send_mock:
            await _handle_queue_message(EFT_RECEIVED_TOPIC, json.dumps(eft_received))
            result = await _handle_queue_message(BANK_STATEMENT_TOPIC, json.dumps(bank_statement))

        self.assertIsNotNone(result)
        _, kwargs = send_mock.call_args
        payload = json.loads(kwargs["message"])
        self.assertEqual(payload["correlation_id"], "corr-2")
        self.assertIn("amount", payload.get("reason", ""))

    async def test_eft_matched_and_payout_sent_reconcile(self) -> None:
        from reconciliation_service.app.main import _handle_queue_message

        eft_matched = {
            "correlation_id": "corr-3",
            "trace_number": "trace-3",
            "payer_id": "payer-c",
            "provider_id": "prov-c",
            "claims": [{"claim_id": "eft", "amount_cents": 4200}],
        }
        payout_sent = {
            "correlation_id": "corr-3",
            "trace_number": "trace-3",
            "payer_id": "payer-c",
            "provider_id": "prov-c",
            "claims": [{"claim_id": "payout", "amount_cents": 4200}],
            "direction": "DEBIT",
        }

        with patch("reconciliation_service.app.main.publisher.send", return_value=True) as send_mock:
            await _handle_queue_message(EFT_MATCHED_TOPIC, json.dumps(eft_matched))
            result = await _handle_queue_message(PAYOUT_SENT_TOPIC, json.dumps(payout_sent))

        self.assertIsNotNone(result)
        payload = json.loads(send_mock.call_args.kwargs["message"])
        self.assertEqual(payload["correlation_id"], "corr-3")
        self.assertEqual(send_mock.call_args.kwargs["queue_name"], RECONCILIATION_TOPIC)


if __name__ == "__main__":
    unittest.main()
