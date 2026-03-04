# projects

Python monorepo for a multi-service healthcare ACH/EFT processing system. Each service is a FastAPI app with shared middleware for correlation IDs, structured JSON logging, optional API key enforcement, and OpenTelemetry spans.

## Services and responsibilities
- **ach_ingestion_service**: Parses ACH settlement files and emits `EFTReceived` events.
- **remittance_ingestion_service**: Parses 835/X12 remittances and emits `RemittanceReceived`.
- **pairing_service**: Matches ACH receipts to 835 remittances and emits `EFTMatchedToRemittance`.
- **ledger_service**: Journals events into debit/credit lines.
- **provider_ledger_service**: Maintains provider balances and emits `provider_balance_updates`.
- **payout_service**: Triggers payouts when balances exceed a threshold and emits `ProviderPayoutInitiated`.
- **batch_builder_service**: Batches payouts into NACHA-style payloads and emits `ProviderPayoutSent`.
- **bank_statement_ingestion_service**: Ingests BAI2 or CAMT.053 statements and emits `BankStatementReceived`.
- **reconciliation_service**: Compares bank statements to payouts/EFTs and emits `ReconciliationCompleted` or `RemittanceException`.
- **claim_system_adapter**: Posts paid claims to an external claim system and emits `ClaimPaymentPosted`.

## Event flows (happy path)
1. **ACH ingestion** → publishes `EFTReceived` (`topic: eft-received`, queue consumer: `eft_received_queue`).
2. **Ledger** records EFT receipt from `eft_received_queue`.
3. **835 ingestion** → publishes `RemittanceReceived` (`queue: remittance_received_queue`).
4. **Pairing** consumes `eft_received_queue` + `remittance_received_queue` → emits `eft_matched_queue`.
5. **Provider ledger** consumes `eft_matched_queue` → emits `provider_balance_updates_queue`.
6. **Payout** consumes `provider_balance_updates_queue` → emits `payout_initiated_queue`.
7. **Batch builder** consumes `payout_initiated_queue` → emits `payout_sent_queue`.
8. **Ledger** consumes `payout_sent_queue`.
9. **Bank statements** → `bank_statement_queue`.
10. **Reconciliation** consumes `bank_statement_queue` + `payout_sent_queue` (+ `eft_received_queue`) → emits `reconciliation_queue`.
11. **Claim posting** consumes `claim_payment_queue` → emits `claim_payment_posted_queue`.

Queue/topic names are defined in code; see each service’s `SUBSCRIBED_QUEUE`/publisher calls.

## API endpoints (manual triggers)
- `POST /ingest-ach` (ach_ingestion_service) – Trigger ACH ingestion.
- `POST /ingest-835` (remittance_ingestion_service) – Trigger 835 ingestion.
- `POST /process` and `POST /flush/{payer_id}` (batch_builder_service) – Manually enqueue/flush payouts.
- `POST /trigger-payout/{provider_id}` and `GET /provider/{provider_id}/balance` (payout_service).
- `GET /provider/{provider_id}/balance` (provider_ledger_service).
- `POST /ingest-bai2`, `POST /ingest-camt053` (bank_statement_ingestion_service).
- `POST /post-entry` (ledger_service) – Manual journal entry.
- `POST /process` (reconciliation_service) – Manual reconciliation ingest.
- `POST /process` (claim_system_adapter) – Manual claim posting.
- `GET /health` on every service.

All endpoints accept/return Pydantic schemas defined in `shared/events/schemas.py` and each service’s `schemas.py`.

## Middleware, auth, tracing
Shared middleware (`shared/middleware.py`) is attached to every FastAPI app:
- Propagates/creates `X-Correlation-ID` (also echoed in responses).
- Structured JSON logs with correlation_id, method, path, status, and duration.
- API key enforcement when `API_KEY` or `SERVICE_API_KEY` is set (header: `X-API-Key`).
- OpenTelemetry spans per request (Console exporter by default) with `correlation_id` attributes.

## Local development
```bash
pip install -r requirements.txt
python -m unittest
```

### Docker Compose
Bring up all services, Postgres, and the Service Bus emulator:
```bash
docker-compose up --build
```
Environment defaults:
- `DATABASE_URL=postgresql+psycopg2://postgres:postgres@postgres:5432/platform`
- `SERVICEBUS_CONNECTION_STRING=Endpoint=sb://servicebus.local/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=local`
- `API_KEY=local-dev-key` (add `X-API-Key` header when calling services)

Each service listens on a unique host port (8010–8019). The Service Bus emulator exposes AMQP ports 5671/5672 and dashboard on 8081. Postgres exposes 5432 with persisted volume `postgres_data`.

## Tests
- Unit tests per service under `tests/`.
- `tests/test_integration_full_flow.py` simulates the ACH → 835 → pairing → provider balance → payout → batch → bank statement → reconciliation path with in-memory mocks for Service Bus.

## Event schemas
Key payloads are defined in `shared/events/schemas.py`:
- `EFTReceived`, `RemittanceReceived`, `EFTMatchedToRemittance`
- `ProviderPayoutInitiated`, `ProviderPayoutSent`
- `BankStatementReceived`, `ReconciliationCompleted`, `RemittanceException`
- `ClaimPaymentPosted`
