import unittest
from datetime import datetime, timezone

from shared.events.schemas import (
    ACHReturnReceived,
    ACHReturnReceivedV1,
    BankStatementReceived,
    BankStatementReceivedV1,
    ClaimPaymentPosted,
    ClaimPaymentPostedV1,
    ClaimReference,
    EFTMatchedToRemittance,
    EFTMatchedToRemittanceV1,
    EFTReceived,
    EFTReceivedV1,
    NOCReceived,
    NOCReceivedV1,
    ProviderPayoutInitiated,
    ProviderPayoutInitiatedV1,
    ProviderPayoutSent,
    ProviderPayoutSentV1,
    ReconciliationCompleted,
    ReconciliationCompletedV1,
    RemittanceReceived,
    RemittanceReceivedV1,
    RemittanceExceptionV1,
    RemittanceException,
)


class SharedEventSchemaTests(unittest.TestCase):
    def test_event_models_include_required_common_fields(self) -> None:
        event_classes = [
            EFTReceived,
            EFTReceivedV1,
            RemittanceReceived,
            RemittanceReceivedV1,
            EFTMatchedToRemittance,
            EFTMatchedToRemittanceV1,
            ProviderPayoutInitiated,
            ProviderPayoutInitiatedV1,
            ProviderPayoutSent,
            ProviderPayoutSentV1,
            BankStatementReceived,
            BankStatementReceivedV1,
            ReconciliationCompleted,
            ReconciliationCompletedV1,
            ClaimPaymentPosted,
            ClaimPaymentPostedV1,
            ACHReturnReceived,
            ACHReturnReceivedV1,
            NOCReceived,
            NOCReceivedV1,
            RemittanceException,
            RemittanceExceptionV1,
        ]

        for event_class in event_classes:
            with self.subTest(event_class=event_class.__name__):
                event = event_class(
                    correlation_id="corr-123",
                    trace_number="trace-456",
                    payer_id="payer-789",
                    provider_id="provider-001",
                    claims=[ClaimReference(claim_id="claim-1", amount_cents=5000)],
                )
                self.assertEqual(event.correlation_id, "corr-123")
                self.assertEqual(event.trace_number, "trace-456")
                self.assertEqual(event.payer_id, "payer-789")
                self.assertEqual(event.provider_id, "provider-001")
                self.assertEqual(len(event.claims), 1)
                self.assertIsInstance(event.event_timestamp, datetime)
                self.assertIsInstance(event.created_at, datetime)
                self.assertEqual(event.event_timestamp.tzinfo, timezone.utc)
                self.assertEqual(event.created_at.tzinfo, timezone.utc)

    def test_claim_list_uses_safe_default_factory(self) -> None:
        first = EFTReceived(
            correlation_id="a",
            trace_number="b",
            payer_id="c",
            provider_id="d",
        )
        second = EFTReceived(
            correlation_id="e",
            trace_number="f",
            payer_id="g",
            provider_id="h",
        )

        first.claims.append(ClaimReference(claim_id="claim-2", amount_cents=100))
        self.assertEqual(len(first.claims), 1)
        self.assertEqual(second.claims, [])


if __name__ == "__main__":
    unittest.main()
