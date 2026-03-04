import hashlib
import json
import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from remittance_ingestion_service.app.main import (
    _build_correlation_id,
    _parse_835,
    ingest_835,
)
from remittance_ingestion_service.app.schemas import (
    ClaimDetail,
    Parsed835Data,
    RemittanceIngest835Request,
)


class _FakeDB:
    def __init__(self):
        self.records = []

    def add(self, record):
        self.records.append(record)

    def commit(self):
        return None

    def refresh(self, _record):
        return None


_SAMPLE_X12_835 = (
    "ISA*00*          *00*          *ZZ*PAYER001       *ZZ*PROVIDER002    "
    "*20240101*1200*^*00501*000000001*0*T*:~"
    "GS*HP*PAYER001*PROVIDER002*20240101*1200*1*X*005010X221A1~"
    "ST*835*0001~"
    "BPR*I*280.00*C*ACH~"
    "TRN*1*TRACE-ABC*1234567890~"
    "N1*PR*Big Insurance Co*XX*PAYER001~"
    "N1*PE*Happy Clinic*XX*PROVIDER002~"
    "CLP*CLAIM-001*1*100.00*80.00**MC*111111111~"
    "SVC*HC:99213*100.00*80.00**1~"
    "CLP*CLAIM-002*1*250.00*200.00**MC*222222222~"
    "SVC*HC:99214*250.00*200.00**1~"
    "SE*12*0001~"
    "GE*1*1~"
    "IEA*1*000000001~"
)


class Parse835Tests(unittest.TestCase):
    def test_parse_x12_835_extracts_trace_number(self) -> None:
        parsed = _parse_835(_SAMPLE_X12_835)
        self.assertEqual(parsed.trace_number, "TRACE-ABC")

    def test_parse_x12_835_extracts_payer_id(self) -> None:
        parsed = _parse_835(_SAMPLE_X12_835)
        self.assertEqual(parsed.payer_id, "PAYER001")

    def test_parse_x12_835_extracts_provider_id(self) -> None:
        parsed = _parse_835(_SAMPLE_X12_835)
        self.assertEqual(parsed.provider_id, "PROVIDER002")

    def test_parse_x12_835_extracts_claims(self) -> None:
        parsed = _parse_835(_SAMPLE_X12_835)
        self.assertEqual(len(parsed.claims), 2)
        self.assertEqual(parsed.claims[0].claim_id, "CLAIM-001")
        self.assertEqual(parsed.claims[0].amount_cents, 8000)
        self.assertEqual(parsed.claims[1].claim_id, "CLAIM-002")
        self.assertEqual(parsed.claims[1].amount_cents, 20000)

    def test_parse_json_835(self) -> None:
        json_payload = json.dumps(
            {
                "trace_number": "TRACE-JSON",
                "payer_id": "PAYER-JSON",
                "provider_id": "PROVIDER-JSON",
                "claims": [{"claim_id": "CL-1", "amount_cents": 5000}],
            }
        )
        parsed = _parse_835(json_payload)
        self.assertEqual(parsed.trace_number, "TRACE-JSON")
        self.assertEqual(parsed.payer_id, "PAYER-JSON")
        self.assertEqual(parsed.provider_id, "PROVIDER-JSON")
        self.assertEqual(len(parsed.claims), 1)
        self.assertEqual(parsed.claims[0].claim_id, "CL-1")
        self.assertEqual(parsed.claims[0].amount_cents, 5000)

    def test_parse_invalid_data_raises_validation_error(self) -> None:
        from pydantic import ValidationError

        with self.assertRaises(ValidationError):
            _parse_835("not-valid-835-or-json")


class BuildCorrelationIdTests(unittest.TestCase):
    def test_correlation_id_is_deterministic(self) -> None:
        parsed = Parsed835Data(
            trace_number="TRACE-ABC",
            payer_id="PAYER001",
            provider_id="PROVIDER002",
            claims=[],
        )
        correlation_id = _build_correlation_id(parsed)
        expected = hashlib.sha256(
            "TRACE-ABC|PAYER001|PROVIDER002".encode("utf-8")
        ).hexdigest()
        self.assertEqual(correlation_id, expected)

    def test_correlation_id_differs_for_different_inputs(self) -> None:
        parsed_a = Parsed835Data(
            trace_number="T1", payer_id="P1", provider_id="PR1", claims=[]
        )
        parsed_b = Parsed835Data(
            trace_number="T2", payer_id="P1", provider_id="PR1", claims=[]
        )
        self.assertNotEqual(_build_correlation_id(parsed_a), _build_correlation_id(parsed_b))


class Ingest835EndpointTests(unittest.TestCase):
    def test_ingest_835_publishes_remittance_received_event(self) -> None:
        fake_db = _FakeDB()
        request = RemittanceIngest835Request(raw_835=_SAMPLE_X12_835)

        with patch(
            "remittance_ingestion_service.app.main.publisher"
        ) as mock_publisher:
            mock_publisher.send = MagicMock(return_value=True)
            event = ingest_835(request, db=fake_db)

        self.assertEqual(event.trace_number, "TRACE-ABC")
        self.assertEqual(event.payer_id, "PAYER001")
        self.assertEqual(event.provider_id, "PROVIDER002")
        self.assertEqual(len(event.claims), 2)
        self.assertEqual(event.claims[0].claim_id, "CLAIM-001")
        self.assertEqual(event.claims[0].amount_cents, 8000)
        self.assertEqual(event.claims[1].claim_id, "CLAIM-002")
        self.assertEqual(event.claims[1].amount_cents, 20000)

        mock_publisher.send.assert_called_once()
        call_kwargs = mock_publisher.send.call_args
        self.assertEqual(call_kwargs.kwargs["queue_name"], "remittance_received_queue")
        sent_payload = json.loads(call_kwargs.kwargs["message"])
        self.assertEqual(sent_payload["trace_number"], "TRACE-ABC")

    def test_ingest_835_persists_processing_record(self) -> None:
        fake_db = _FakeDB()
        request = RemittanceIngest835Request(raw_835=_SAMPLE_X12_835)

        with patch("remittance_ingestion_service.app.main.publisher"):
            ingest_835(request, db=fake_db)

        self.assertEqual(len(fake_db.records), 1)
        self.assertEqual(fake_db.records[0].external_id, "TRACE-ABC")
        self.assertEqual(fake_db.records[0].amount_cents, 28000)

    def test_ingest_835_from_json_payload(self) -> None:
        fake_db = _FakeDB()
        json_payload = json.dumps(
            {
                "trace_number": "TRACE-JSON",
                "payer_id": "PAYER-JSON",
                "provider_id": "PROVIDER-JSON",
                "claims": [{"claim_id": "CL-1", "amount_cents": 5000}],
            }
        )
        request = RemittanceIngest835Request(raw_835=json_payload)

        with patch("remittance_ingestion_service.app.main.publisher"):
            event = ingest_835(request, db=fake_db)

        self.assertEqual(event.trace_number, "TRACE-JSON")
        self.assertEqual(len(event.claims), 1)

    def test_ingest_835_rejects_invalid_data(self) -> None:
        fake_db = _FakeDB()
        request = RemittanceIngest835Request(raw_835="not-valid-835-or-json")

        with self.assertRaises(HTTPException) as context:
            ingest_835(request, db=fake_db)

        self.assertEqual(context.exception.status_code, 422)
        self.assertEqual(context.exception.detail["message"], "Invalid 835 data")

    def test_ingest_835_correlation_id_included_in_event(self) -> None:
        fake_db = _FakeDB()
        request = RemittanceIngest835Request(raw_835=_SAMPLE_X12_835)

        with patch("remittance_ingestion_service.app.main.publisher"):
            event = ingest_835(request, db=fake_db)

        expected_correlation_id = hashlib.sha256(
            "TRACE-ABC|PAYER001|PROVIDER002".encode("utf-8")
        ).hexdigest()
        self.assertEqual(event.correlation_id, expected_correlation_id)


if __name__ == "__main__":
    unittest.main()
