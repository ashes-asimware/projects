import hashlib
import unittest
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from ach_ingestion_service.app.main import (
    _build_correlation_id,
    _parse_ach_settlement_data,
    ingest_ach,
)
from ach_ingestion_service.app.schemas import AchIngestionServiceRequest
from shared.events.topics import EFT_RECEIVED_TOPIC


class _FakeDB:
    def __init__(self):
        self.records = []

    def add(self, record):
        self.records.append(record)

    def commit(self):
        return None

    def refresh(self, _record):
        return None


class AchIngestionServiceTests(unittest.IsolatedAsyncioTestCase):
    def test_parse_ach_settlement_data_from_json(self) -> None:
        parsed = _parse_ach_settlement_data(
            '{"trace_number":"trace-123","payer_id":"payer-abc","provider_id":"provider-xyz","amount_cents":10000}'
        )

        self.assertEqual(parsed.trace_number, "trace-123")
        self.assertEqual(parsed.payer_id, "payer-abc")
        self.assertEqual(parsed.provider_id, "provider-xyz")
        self.assertEqual(parsed.amount_cents, 10000)

    def test_build_correlation_id_hash_is_deterministic(self) -> None:
        parsed = _parse_ach_settlement_data(
            "trace_number=trace-123,payer_id=payer-abc,provider_id=provider-xyz,amount_cents=10000"
        )
        correlation_id = _build_correlation_id(parsed)
        expected = hashlib.sha256(
            "trace-123|payer-abc|provider-xyz|10000".encode("utf-8")
        ).hexdigest()
        self.assertEqual(correlation_id, expected)

    async def test_ingest_ach_publishes_eft_received_event(self) -> None:
        fake_db = _FakeDB()
        request = AchIngestionServiceRequest(
            settlement_data=(
                "trace_number=trace-123,payer_id=payer-abc,"
                "provider_id=provider-xyz,amount_cents=10000"
            )
        )

        with patch("ach_ingestion_service.app.main.publish", new=AsyncMock()) as publish_mock:
            event = await ingest_ach(request, db=fake_db)

        self.assertEqual(event.trace_number, "trace-123")
        self.assertEqual(event.payer_id, "payer-abc")
        self.assertEqual(event.provider_id, "provider-xyz")
        self.assertEqual(fake_db.records[0].external_id, "trace-123")
        self.assertEqual(fake_db.records[0].amount_cents, 10000)

        publish_mock.assert_awaited_once()
        _, kwargs = publish_mock.await_args
        self.assertEqual(kwargs["topic_name"], EFT_RECEIVED_TOPIC)
        self.assertEqual(kwargs["correlation_id"], event.correlation_id)
        self.assertEqual(kwargs["payload"]["trace_number"], "trace-123")
        self.assertEqual(fake_db.records[0].raw_data, request.settlement_data)

    async def test_ingest_ach_rejects_invalid_settlement_data(self) -> None:
        fake_db = _FakeDB()
        request = AchIngestionServiceRequest(settlement_data="not-a-valid-settlement")

        with self.assertRaises(HTTPException) as context:
            await ingest_ach(request, db=fake_db)

        self.assertEqual(context.exception.status_code, 422)
        self.assertEqual(context.exception.detail["message"], "Invalid ACH settlement data")
        errors = context.exception.detail["errors"]
        self.assertTrue(errors)
        self.assertEqual(errors[0]["type"], "missing")


if __name__ == "__main__":
    unittest.main()
