# ACH / EFT Process Flow (TypeScript)

This workspace contains ten NestJS services and shared libraries that model the end-to-end ACH and ERA payment lifecycle. Services communicate exclusively through Kafka topics with versioned schemas and share common observability, authentication, and error-handling middleware.

## Architecture Overview
- **Event-driven microservices** with Kafka topics for domain events.
- **Shared libraries**: `@shared/observability` (Pino logging, OpenTelemetry tracing, correlation IDs, error middleware), `@shared/events` (schemas and topics), `@shared/kafka` (publish/subscribe helpers).
- **Data**: Each service owns its own Postgres database managed via Prisma migrations.
- **Deployment**: Each service ships with a multi-stage Dockerfile that builds shared libraries and the service, runs migrations, then starts the compiled app.

## Service Responsibilities
- **ach-ingestion-service**: Accepts ACH/EFT payloads and emits `eft.received.v1`.
- **remittance-ingestion-service**: Accepts ERA/remittance files and emits `remittance.received.v1`.
- **pairing-service**: Pairs EFT and remittance data; emits `eft.matched.v1`.
- **ledger-service**: Posts financial ledger movements driven by matched EFTs.
- **provider-ledger-service**: Maintains provider-level balances.
- **payout-service**: Initiates provider payouts and emits `payout.initiated.v1`.
- **batch-builder-service**: Groups payouts into outbound batches.
- **bank-statement-service**: Ingests bank statements and emits `bank.statement.v1`.
- **reconciliation-service**: Reconciles statements and emits `reconciliation.completed.v1`.
- **claim-system-adapter**: Posts claim payment updates downstream.

## Kafka Topics
Topics are versioned and centralized in `@shared/events`:
- `eft.received.v1`, `remittance.received.v1`, `eft.matched.v1`
- `ledger.posted.v1`, `provider.ledger.updated.v1`, `ledger.settled.v1`
- `payout.initiated.v1`, `payout.sent.v1`
- `bank.statement.v1`, `reconciliation.completed.v1`
- `claim.payment.posted.v1`, `ach.return.v1`, `noc.received.v1`

## Event Schemas
All event payloads are validated with Zod. Core fields:
- `eventType`, `eventVersion`, `correlationId`, `traceNumber`, `payerId`, `providerId`, `amount`, optional `claims[]`, and `timestamp`.
Schemas live in `shared/events/src/index.ts` and are exported per event type (e.g., `EFTReceivedV1Schema`, `ProviderPayoutInitiatedV1Schema`).

## API Endpoints
Every service exposes:
- `POST /ingest` (where applicable) to accept source data and publish events.
- `GET /health` for readiness probes.

Cross-cutting middleware applied to all services:
- API key validation via `ApiKeyMiddleware`.
- Correlation ID + structured request logging.
- OpenTelemetry tracing initialization.
- Error-handling middleware returning JSON with correlation IDs.

## Running Locally
1. Install dependencies: `npm install --workspaces --include-workspace-root`.
2. Start infra and services: `docker-compose up --build`.
3. Services read configuration from `.env` (see `.env.example` for required DB URLs and API keys).

## Running Tests
- Run TypeScript builds/lint: `npm run build` / `npm run lint`.
- Integration flow test (Kafka harness with mocked adapters): `npm test` or `npm run test:integration`.
