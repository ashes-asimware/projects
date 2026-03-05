1. Assumptions for the SAGA and orchestration
Orchestrator-centric saga:  
A dedicated Orchestrator Service owns the end-to-end state machine for a LoadSaga (per load/shipment).

Event-driven, decoupled services:  
Each service has its own DB and only communicates via Kafka topics (no shared DB).

State model (per load / per saga instance):  
Orchestrator tracks something like:
INTAKE_RECEIVED
ENRICHED_STORED
CALCULATION_DONE
BILLING_INVOICE_PREPARED
FUEL_ADVANCE_REQUESTED (optional branch)
ACH_COMPLETED
FUEL_ADVANCE_COMPLETED (optional)
CARRIER_PAYMENT_ISSUED
FUEL_CARD_DISPATCHED
COMPLETED / FAILED

Retries & compensations:
Retries are local to each service (with backoff, DLQ).

Orchestrator handles global saga outcome and triggers compensating actions via events (e.g., reverse advance, mark invoice as cancelled, etc.), not DB rollbacks.

2. Updated components and topics (with Orchestrator)
New/clarified components:

Orchestrator Service
Owns saga state per loadId.
Listens to domain events and updates saga state.
Emits command-like events to drive next steps or compensations.

Per-service DBs:
EnrichmentDB, CalcDB, InvoicingDB, AdvanceDB, OrchestratorDB, LedgerDB.

Key topics (events/commands):

Domain events (already defined):

EnrichedPayloadSent

EnrichedPayloadReceived

BillingInvoicePrepared

FuelAdvanceRequested

CarrierPaymentIssued

FuelCardDispatched

Orchestrator commands / control events (examples):

StartLoadSaga

RecalculateInvoice

CancelInvoice

ReverseFuelAdvance

MarkSagaFailed