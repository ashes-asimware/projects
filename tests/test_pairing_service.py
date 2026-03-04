import json
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

_TEST_DATABASE_URL = "sqlite:///:memory:"


def _setup_test_db():
    import pairing_service.app.db as db_module
    import pairing_service.app.main as main_module

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

    from pairing_service.app.db import Base
    import pairing_service.app.models  # noqa: F401

    Base.metadata.create_all(bind=test_engine)
    return TestSessionLocal, test_engine


class PairingServiceMatchingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.SessionLocal, self.engine = _setup_test_db()

    def tearDown(self) -> None:
        from pairing_service.app.db import Base

        Base.metadata.drop_all(bind=self.engine)

    async def test_matches_eft_and_remittance_and_publishes_once(self) -> None:
        from pairing_service.app.main import _handle_queue_message

        eft_event = {
            "correlation_id": "corr-eft",
            "trace_number": "trace-123",
            "payer_id": "payer-1",
            "provider_id": "provider-1",
            "claims": [{"claim_id": "EFT_TOTAL", "amount_cents": 10000}],
        }
        remittance_event = {
            "correlation_id": "corr-remit",
            "trace_number": "trace-123",
            "payer_id": "payer-1",
            "provider_id": "provider-1",
            "claims": [
                {"claim_id": "c1", "amount_cents": 4000},
                {"claim_id": "c2", "amount_cents": 6000},
            ],
        }

        with patch("pairing_service.app.main.publisher.send", return_value=True) as send_mock:
            await _handle_queue_message("eft_received_queue", json.dumps(eft_event))
            result = await _handle_queue_message("remittance_received_queue", json.dumps(remittance_event))

        self.assertIsNotNone(result)
        send_mock.assert_called_once()
        _, kwargs = send_mock.call_args
        self.assertEqual(kwargs["queue_name"], "eft_matched_queue")
        payload = json.loads(kwargs["message"])
        self.assertEqual(payload["provider_id"], "provider-1")
        self.assertEqual(len(payload["claims"]), 2)

    async def test_matches_when_remittance_arrives_first(self) -> None:
        from pairing_service.app.main import _handle_queue_message

        eft_event = {
            "correlation_id": "corr-eft2",
            "trace_number": "trace-987",
            "payer_id": "payer-9",
            "provider_id": "provider-9",
            "claims": [{"claim_id": "EFT_TOTAL", "amount_cents": 5000}],
        }
        remittance_event = {
            "correlation_id": "corr-rem2",
            "trace_number": "trace-987",
            "payer_id": "payer-9",
            "provider_id": "provider-9",
            "claims": [{"claim_id": "claim-a", "amount_cents": 5000}],
        }

        with patch("pairing_service.app.main.publisher.send", return_value=True) as send_mock:
            await _handle_queue_message("remittance_received_queue", json.dumps(remittance_event))
            result = await _handle_queue_message("eft_received_queue", json.dumps(eft_event))

        self.assertIsNotNone(result)
        send_mock.assert_called_once()
        payload = json.loads(send_mock.call_args.kwargs["message"])
        self.assertEqual(payload["trace_number"], "trace-987")
        self.assertEqual(payload["claims"][0]["amount_cents"], 5000)


if __name__ == "__main__":
    unittest.main()
