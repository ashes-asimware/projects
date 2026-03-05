import json
import unittest
from unittest.mock import AsyncMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.events.topics import CLAIM_PAYMENT_POSTED_TOPIC
_TEST_DATABASE_URL = "sqlite:///:memory:"


def _setup_test_db():
    import claim_system_adapter.app.db as db_module
    import claim_system_adapter.app.main as main_module

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

    from claim_system_adapter.app.db import Base
    import claim_system_adapter.app.models  # noqa: F401

    Base.metadata.create_all(bind=test_engine)
    return TestSessionLocal, test_engine


class ClaimSystemAdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.SessionLocal, self.engine = _setup_test_db()

    def tearDown(self) -> None:
        from claim_system_adapter.app.db import Base

        Base.metadata.drop_all(bind=self.engine)

    async def test_claim_payment_processed_and_published(self) -> None:
        from claim_system_adapter.app.main import _handle_queue_message
        from claim_system_adapter.app.models import ClaimPaymentRecord

        message = {
            "claim_id": "claim-123",
            "provider_id": "prov-1",
            "amount_cents": 2500,
            "patient_responsibility_cents": 200,
        }

        with patch(
            "claim_system_adapter.app.main._call_claim_system_api",
            new=AsyncMock(return_value={"status": "mocked"}),
        ) as api_mock, patch("claim_system_adapter.app.main.publisher.send", return_value=True) as send_mock:
            await _handle_queue_message(json.dumps(message))

        api_mock.assert_awaited_once()
        send_mock.assert_called_once()
        _, kwargs = send_mock.call_args
        self.assertEqual(kwargs["queue_name"], CLAIM_PAYMENT_POSTED_TOPIC)

        db = self.SessionLocal()
        try:
            record = db.query(ClaimPaymentRecord).filter_by(claim_id="claim-123").first()
            self.assertIsNotNone(record)
            self.assertEqual(record.status, "PAID")
            self.assertEqual(record.patient_responsibility_cents, 200)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
