import asyncio
import json
import os
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from ach_ingestion_service.app import main as ach_main
from ach_ingestion_service.app.schemas import AchIngestionServiceRequest
from bank_statement_ingestion_service.app import main as bank_main
from bank_statement_ingestion_service.app.schemas import Bai2IngestRequest
from batch_builder_service.app import main as batch_main
from pairing_service.app import main as pairing_main
from payout_service.app import main as payout_main
from provider_ledger_service.app import main as provider_main
from reconciliation_service.app import main as recon_main
from remittance_ingestion_service.app import main as rem_main
from remittance_ingestion_service.app.schemas import RemittanceIngest835Request
from shared.events.schemas import ProviderPayoutInitiatedV1
from shared.events.topics import (
    BANK_STATEMENT_TOPIC,
    EFT_MATCHED_TOPIC,
    EFT_RECEIVED_TOPIC,
    PAYOUT_SENT_TOPIC,
    REMITTANCE_RECEIVED_TOPIC,
)


class FullFlowIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_happy_path_flow(self) -> None:
        os.environ["PAYOUT_THRESHOLD_CENTS"] = "0"
        os.environ["BATCH_BUILDER_BATCH_SIZE"] = "1"
        service_db = Path(__file__).resolve().parent.parent / "service.db"
        if service_db.exists():
            service_db.unlink()

        published: list[tuple[str, str]] = []

        async def fake_publish(topic_name: str, payload, **kwargs):
            published.append((topic_name, kwargs.get("correlation_id") or ""))

        def fake_send(queue_name: str, message: str) -> bool:
            published.append((queue_name, message))
            return True

        with (
            patch("shared.servicebus.client.publish", new=AsyncMock(side_effect=fake_publish)),
            patch("ach_ingestion_service.app.main.publish", new=AsyncMock(side_effect=fake_publish)),
            patch("shared.servicebus.client.ServiceBusPublisher.send", side_effect=fake_send),
        ):
            ach_main.Base.metadata.create_all(bind=ach_main.engine)
            rem_main.Base.metadata.create_all(bind=rem_main.engine)
            pairing_main.Base.metadata.create_all(bind=pairing_main.engine)
            provider_main.Base.metadata.create_all(bind=provider_main.engine)
            payout_main.Base.metadata.create_all(bind=payout_main.engine)
            batch_main.Base.metadata.create_all(bind=batch_main.engine)
            bank_main.Base.metadata.create_all(bind=bank_main.engine)
            recon_main.Base.metadata.create_all(bind=recon_main.engine)

            ach_request = AchIngestionServiceRequest(
                settlement_data=(
                    "trace_number=trace-123,payer_id=payer-abc,provider_id=provider-xyz,amount_cents=10000"
                )
            )
            ach_event = await ach_main.ingest_ach(ach_request, db=ach_main.SessionLocal())

            rem_request = RemittanceIngest835Request(
                raw_835=json.dumps(
                    {
                        "trace_number": "trace-123",
                        "payer_id": "payer-abc",
                        "provider_id": "provider-xyz",
                        "claims": [{"claim_id": "c1", "amount_cents": 10000}],
                    }
                )
            )
            rem_event = rem_main.ingest_835(rem_request, db=rem_main.SessionLocal())

            await pairing_main._handle_queue_message(EFT_RECEIVED_TOPIC, ach_event.model_dump_json())
            matched_event = await pairing_main._handle_queue_message(
                REMITTANCE_RECEIVED_TOPIC, rem_event.model_dump_json()
            )
            self.assertIsNotNone(matched_event)

            provider_balance = await provider_main._handle_queue_message(
                json.dumps(matched_event.model_dump(mode="json"))
            )
            payout_db = payout_main.SessionLocal()
            payout_event = payout_main._process_balance_update(
                payout_db, provider_balance.provider_id, provider_balance.balance_cents
            )
            self.assertIsInstance(payout_event, ProviderPayoutInitiatedV1)

            sent_events = batch_main._enqueue_payout(payout_event, batch_main.SessionLocal())
            if not sent_events:
                sent_events = batch_main._flush_batch(payout_event.payer_id, batch_main.SessionLocal())

            bank_request = Bai2IngestRequest(
                bai2_data="01,trace-123\n02,payer-abc,provider-xyz\n16,123,10000"
            )
            bank_event = bank_main.ingest_bai2(bank_request, db=bank_main.SessionLocal())
            bank_event.correlation_id = payout_event.correlation_id

            await recon_main._handle_queue_message(BANK_STATEMENT_TOPIC, bank_event.model_dump_json())
            if sent_events:
                await recon_main._handle_queue_message(PAYOUT_SENT_TOPIC, sent_events[0].model_dump_json())

        self.assertGreaterEqual(len(published), 3)


if __name__ == "__main__":
    unittest.main()
