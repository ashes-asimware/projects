import json
import os
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.events.topics import PAYOUT_SENT_TOPIC
_TEST_DATABASE_URL = "sqlite:///:memory:"


def _setup_test_db():
    import batch_builder_service.app.db as db_module
    import batch_builder_service.app.main as main_module

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

    from batch_builder_service.app.db import Base
    import batch_builder_service.app.models  # noqa: F401

    Base.metadata.create_all(bind=test_engine)
    return TestSessionLocal, test_engine


class BatchBuilderServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        os.environ["BATCH_BUILDER_BATCH_SIZE"] = "2"
        self.SessionLocal, self.engine = _setup_test_db()

    def tearDown(self) -> None:
        from batch_builder_service.app.db import Base

        Base.metadata.drop_all(bind=self.engine)
        os.environ.pop("BATCH_BUILDER_BATCH_SIZE", None)

    async def test_batch_flushes_and_publishes_payout_sent(self) -> None:
        from batch_builder_service.app.main import _handle_queue_message
        from batch_builder_service.app.models import PayoutBatch

        payout_message = {
            "correlation_id": "payout-1",
            "trace_number": "trace-1",
            "payer_id": "platform",
            "provider_id": "prov-1",
            "claims": [{"claim_id": "c1", "amount_cents": 5000}],
        }
        payout_message_2 = {
            "correlation_id": "payout-2",
            "trace_number": "trace-2",
            "payer_id": "platform",
            "provider_id": "prov-2",
            "claims": [{"claim_id": "c2", "amount_cents": 3000}],
        }

        with patch(
            "batch_builder_service.app.main._send_to_mock_bank_adapter",
            return_value={"status": "ok"},
        ) as bank_mock, patch("batch_builder_service.app.main.publisher.send", return_value=True) as send_mock:
            await _handle_queue_message(json.dumps(payout_message))
            result = await _handle_queue_message(json.dumps(payout_message_2))

        self.assertEqual(len(result), 2)
        bank_mock.assert_called_once()
        self.assertEqual(send_mock.call_count, 2)
        for _args, kwargs in send_mock.call_args_list:
            self.assertEqual(kwargs["queue_name"], PAYOUT_SENT_TOPIC)

        db = self.SessionLocal()
        try:
            batch = db.query(PayoutBatch).first()
            self.assertIsNotNone(batch)
            self.assertEqual(batch.item_count, 2)
            self.assertEqual(batch.total_cents, 8000)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
