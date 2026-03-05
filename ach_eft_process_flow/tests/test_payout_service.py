import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.events.topics import PAYOUT_INITIATED_TOPIC
_TEST_DATABASE_URL = "sqlite:///:memory:"


def _make_test_app():
    import payout_service.app.db as db_module
    import payout_service.app.main as main_module

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

    from payout_service.app.db import Base
    import payout_service.app.models  # noqa: F401

    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    from payout_service.app.main import app, get_db

    app.dependency_overrides[get_db] = override_get_db
    return app, TestSessionLocal, test_engine


class PayoutServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.app, self.SessionLocal, self.engine = _make_test_app()
        self.client = TestClient(self.app, raise_server_exceptions=True)

    def tearDown(self) -> None:
        from payout_service.app.db import Base
        from payout_service.app.main import app, get_db

        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=self.engine)
        os.environ.pop("PAYOUT_THRESHOLD_CENTS", None)

    async def test_balance_update_triggers_payout_when_threshold_met(self) -> None:
        from payout_service.app.main import _handle_queue_message, _payout_threshold_cents
        from payout_service.app.models import ProviderBalance

        os.environ["PAYOUT_THRESHOLD_CENTS"] = "5000"

        message = {"provider_id": "prov-123", "balance_cents": 7500}
        with patch("payout_service.app.main.publisher.send", return_value=True) as send_mock:
            event = await _handle_queue_message(json.dumps(message))

        self.assertIsNotNone(event)
        self.assertEqual(event.provider_id, "prov-123")
        send_mock.assert_called_once()
        _, kwargs = send_mock.call_args
        self.assertEqual(kwargs["queue_name"], PAYOUT_INITIATED_TOPIC)
        self.assertEqual(_payout_threshold_cents(), 5000)

        db = self.SessionLocal()
        try:
            balance = db.query(ProviderBalance).filter_by(provider_id="prov-123").first()
            self.assertIsNotNone(balance)
            self.assertEqual(balance.balance_cents, 0)
        finally:
            db.close()

    def test_manual_trigger_payout_uses_current_balance(self) -> None:
        from payout_service.app.models import ProviderBalance

        db = self.SessionLocal()
        try:
            db.add(ProviderBalance(provider_id="prov-manual", balance_cents=3200))
            db.commit()
        finally:
            db.close()

        with patch("payout_service.app.main.publisher.send", return_value=True):
            response = self.client.post("/trigger-payout/prov-manual")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["provider_id"], "prov-manual")
        self.assertEqual(data["amount_cents"], 3200)


if __name__ == "__main__":
    unittest.main()
