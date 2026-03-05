import json
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from shared.events.topics import PROVIDER_BALANCE_UPDATED_TOPIC
_TEST_DATABASE_URL = "sqlite:///:memory:"


def _make_test_app():
    import provider_ledger_service.app.db as db_module
    import provider_ledger_service.app.main as main_module

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

    from provider_ledger_service.app.db import Base
    import provider_ledger_service.app.models  # noqa: F401

    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestSessionLocal()
        try:
            yield db
        finally:
            db.close()

    from provider_ledger_service.app.main import app, get_db

    app.dependency_overrides[get_db] = override_get_db
    return app, TestSessionLocal, test_engine


class ProviderLedgerServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.app, self.SessionLocal, self.engine = _make_test_app()
        self.client = TestClient(self.app, raise_server_exceptions=True)

    def tearDown(self) -> None:
        from provider_ledger_service.app.db import Base
        from provider_ledger_service.app.main import app, get_db

        app.dependency_overrides.pop(get_db, None)
        Base.metadata.drop_all(bind=self.engine)

    def test_get_balance_returns_zero_when_absent(self) -> None:
        response = self.client.get("/provider/provider-x/balance")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"provider_id": "provider-x", "balance_cents": 0})

    async def test_handle_queue_message_updates_balance_and_publishes(self) -> None:
        from provider_ledger_service.app.main import _handle_queue_message
        from provider_ledger_service.app.models import ProviderBalance

        event = {
            "provider_id": "provider-abc",
            "claims": [
                {"claim_id": "c1", "amount_cents": 3000},
                {"claim_id": "c2", "amount_cents": 7000},
            ],
        }

        with patch("provider_ledger_service.app.main.publisher.send", return_value=True) as send_mock:
            balance = await _handle_queue_message(json.dumps(event))

        self.assertEqual(balance.balance_cents, 10000)
        send_mock.assert_called_once()
        _, kwargs = send_mock.call_args
        self.assertEqual(kwargs["queue_name"], PROVIDER_BALANCE_UPDATED_TOPIC)
        payload = json.loads(kwargs["message"])
        self.assertEqual(payload["provider_id"], "provider-abc")

        db = self.SessionLocal()
        try:
            stored = db.query(ProviderBalance).filter_by(provider_id="provider-abc").first()
            self.assertIsNotNone(stored)
            self.assertEqual(stored.balance_cents, 10000)
        finally:
            db.close()


if __name__ == "__main__":
    unittest.main()
