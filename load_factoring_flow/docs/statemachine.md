. Core identifiers and invariants
Saga keying:

Saga ID: sagaId (UUID)

Business key: loadId

Orchestrator correlates all events by loadId (and/or sagaId if you propagate it).

Terminal states:

COMPLETED

FAILED

Once in a terminal state, no further transitions except idempotent re-processing of duplicate events.

2. State list
Here’s the full set of states:

NEW

INTAKE_RECEIVED

ENRICHED_STORED

CALCULATION_DONE

BILLING_INVOICE_PREPARED

FUEL_ADVANCE_REQUESTED (optional branch)

ACH_COMPLETED

FUEL_ADVANCE_COMPLETED (optional)

COMPLETED

FAILED

You can treat CALCULATION_DONE as implicit if you only care about BILLING_INVOICE_PREPARED and FUEL_ADVANCE_REQUESTED, but I’ll keep it explicit for clarity.

3. Events that drive the saga
Domain events (from other services):

EnrichedPayloadSent

EnrichedPayloadReceived

BillingInvoicePrepared

FuelAdvanceRequested

CarrierPaymentIssued

FuelCardDispatched

Control/compensation events (from services back to Orchestrator):

CancelInvoice

ReverseFuelAdvance

MarkSagaFailed (generic failure notification)

(Optional) RecalculateInvoice

Internal timers:

Timeout(Intake)

Timeout(Enrichment)

Timeout(Calculation)

Timeout(ACH)

Timeout(FuelAdvance)

4. State machine (transitions table)
State: NEW
On: EnrichedPayloadSent

Action:

Create saga row with loadId, sagaId.

Persist state INTAKE_RECEIVED.

Next: INTAKE_RECEIVED

State: INTAKE_RECEIVED
On: EnrichedPayloadReceived

Guard: loadId matches.

Action: update saga with enrichment metadata.

Next: ENRICHED_STORED

On: Timeout(Enrichment)

Action: mark saga as failed (reason: enrichment timeout).

Next: FAILED

State: ENRICHED_STORED
On: BillingInvoicePrepared

Action:

Record billing info (gross, net, fees).

Mark calculation as done.

Next: BILLING_INVOICE_PREPARED

On: Timeout(Calculation)

Action: mark saga as failed (reason: calculation timeout).

Next: FAILED

(You may also accept BillingInvoicePrepared directly from INTAKE_RECEIVED if enrichment and calc are tightly coupled; then you’d allow that transition from both states.)

State: BILLING_INVOICE_PREPARED
On: FuelAdvanceRequested

Action:

Record that fuel advance is part of this saga.

Next: FUEL_ADVANCE_REQUESTED

On: CarrierPaymentIssued (no fuel advance path)

Action:

Record ACH completion.

Next: ACH_COMPLETED → then evaluate completion (see below).

On: Timeout(ACH)

Action: mark saga as failed (reason: ACH timeout).

Next: FAILED

(If no fuel advance is requested, saga can complete after ACH.)

State: FUEL_ADVANCE_REQUESTED
On: CarrierPaymentIssued

Action: mark ACH completed.

Next: ACH_COMPLETED (but saga not done until fuel advance branch completes or fails).

On: FuelCardDispatched

Action: mark fuel advance completed.

Next: FUEL_ADVANCE_COMPLETED (but saga not done until ACH branch completes or fails).

On: Timeout(ACH) or Timeout(FuelAdvance)

Action: mark saga as failed (reason: timeout).

Next: FAILED

State: ACH_COMPLETED
On entry: check if fuel advance is part of saga.

If no fuel advance requested:

Action: mark saga COMPLETED.

Next: COMPLETED

If fuel advance requested but not yet completed:

Stay in: ACH_COMPLETED (waiting for FuelCardDispatched or failure).

On: FuelCardDispatched

Action: mark fuel advance completed.

Next: FUEL_ADVANCE_COMPLETED → then evaluate completion.

On: ReverseFuelAdvance / CancelInvoice / MarkSagaFailed

Action: mark saga failed, record reason.

Next: FAILED

State: FUEL_ADVANCE_COMPLETED
On entry: check if ACH is completed.

If ACH already completed:

Action: mark saga COMPLETED.

Next: COMPLETED

If ACH not yet completed:

Stay in: FUEL_ADVANCE_COMPLETED (waiting for CarrierPaymentIssued or failure).

On: CarrierPaymentIssued

Action: mark ACH completed.

Next: ACH_COMPLETED → then evaluate completion (which will now be true).

On: CancelInvoice / MarkSagaFailed

Action: mark saga failed, record reason.

Next: FAILED

State: COMPLETED
On any duplicate event (CarrierPaymentIssued, FuelCardDispatched, etc.)

Action: idempotent no-op (log and ignore).

Next: COMPLETED

State: FAILED
On any further event

Action: no-op or log; optionally trigger alerts.

Next: FAILED

5. Compensation hooks (how Orchestrator reacts to failures)
The state machine above defines when saga is failed; here’s what Orchestrator can do when it transitions to FAILED:

If failure before billing (e.g., enrichment/calc):

No financial side effects yet.

Orchestrator may emit:

RecalculateInvoice (if transient)

Or just mark as permanently failed.

If failure after fuel advance but before ACH:

Orchestrator can emit:

ReverseFuelAdvance to Advance Service (logical compensation via Ledger).

CancelInvoice to Invoicing Service (if invoice exists but unpaid).

If failure after ACH but before fuel advance:

Orchestrator can emit:

CancelFuelAdvance (don’t process advance).

Any ledger adjustments needed (e.g., mark that carrier was paid but advance not granted).

If both ACH and fuel advance completed but some downstream reconciliation fails:

Saga can still be COMPLETED from a payment perspective, but you might track a separate reconciliation status outside the saga.