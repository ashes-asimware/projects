4. Failure, retry, and compensation strategy (per step)
Intake Function → EnrichedPayloadSent

Failure modes: HTTP failure from 3rd party, document download failure, Kafka publish failure.

Strategy:

Retries: transient failures with backoff.

If unrecoverable: emit a StartLoadSaga with status=FAILED_INTAKE or log to DLQ; Orchestrator marks saga as FAILED.

Enrichment Service

Failure modes: Blob upload failure, DB write failure, Kafka publish failure.

Strategy:

Retries: local retries for Blob/DB/Kafka.

If unrecoverable: write to DLQ; Orchestrator sees absence of EnrichedPayloadReceived beyond SLA and can mark saga as FAILED or emit a timeout event.

Calculation Service

Failure modes: DB failure, calculation module failure, Kafka publish failure.

Strategy:

Retries: local.

If unrecoverable: DLQ; Orchestrator can:

Mark saga FAILED_CALCULATION.

Optionally emit RecalculateInvoice command later when issue is resolved.

Invoicing Service / ACH

Failure modes: ACH call failure, reconciliation failure, DB failure, Kafka publish failure.

Strategy:

Retries: for transient ACH/DB/Kafka issues.

If ACH permanently fails: mark invoice as failed, emit CancelInvoice or MarkSagaFailed to T_OrchCtrl.

Compensation: If fuel advance already processed, Orchestrator can:

Emit ReverseFuelAdvance (logical compensation via Ledger / next invoice offset).

Advance Service / EFT

Failure modes: EFT call failure, DB failure, Kafka publish failure.

Strategy:

Retries: for transient EFT/DB/Kafka issues.

If EFT permanently fails: mark advance as failed, emit ReverseFuelAdvance or MarkSagaFailed.

Compensation: If invoice already paid, ledger can record a corrective entry (e.g., credit carrier or adjust next invoice).

Orchestrator Service

Responsibilities:

Maintain saga state in OrchestratorDB.

Correlate events by loadId / sagaId.

Apply timeouts (e.g., no BillingInvoicePrepared within X minutes → mark FAILED_TIMEOUT).

Emit control/compensation commands:

CancelInvoice

ReverseFuelAdvance

RecalculateInvoice

MarkSagaFailed

Retries:  
If Orchestrator fails to update its DB, it retries; if it fails to publish control events, it retries or logs to DLQ and can be replayed.

5. Final step 10: Orchestrator consuming final messages
You asked specifically to wire step 9 into the Orchestrator:

CarrierPaymentIssued → Orchestrator

Orchestrator sets ACH_COMPLETED / CARRIER_PAYMENT_ISSUED.

FuelCardDispatched → Orchestrator

Orchestrator sets FUEL_ADVANCE_COMPLETED / FUEL_CARD_DISPATCHED.

When both required branches for a given load are in a terminal success state, Orchestrator marks saga COMPLETED. If any branch emits a failure/control event, Orchestrator transitions to FAILED and triggers compensations.