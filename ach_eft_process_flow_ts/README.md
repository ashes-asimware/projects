# ACH / EFT Process Flow (TypeScript)

Event-driven NestJS services model the ACH + ERA lifecycle using Kafka topics and shared utilities for schema validation, observability, and messaging safety.

## Architecture Overview
- **Event-driven microservices**: Services publish and subscribe to Kafka topics for every state change (no direct service-to-service HTTP calls).
- **Shared libraries**:
  - `@shared/events`: Kafka topic names plus Zod schemas for every event type.
  - `@shared/kafka`: Kafkajs publisher/consumer helpers with DLQ fallback, correlation IDs, and tracing spans.
  - `@shared/observability`: Pino logging, correlation ID propagation, Nest exception filter + Express error middleware, and OpenTelemetry tracing bootstrap.
- **Runtime**: Each service runs as a NestJS app; `docker-compose.yml` provisions Kafka/ZooKeeper and Postgres containers for local persistence scaffolding.
- **Configuration**: `.env.example` lists the per-service database URLs, API keys, and Kafka broker settings expected at runtime.

## Service Responsibilities
| Service | HTTP ingress | Consumes topics | Publishes topics | Purpose |
| --- | --- | --- | --- | --- |
| ach-ingestion-service | `POST /eft` | — | `eft.received.v1` | Accept inbound ACH/EFT payloads and emit receipt events. |
| remittance-ingestion-service | `POST /remittance` | — | `remittance.received.v1` | Accept ERA/remittance files and emit receipt events. |
| pairing-service | `POST /pair` | `eft.received.v1`, `remittance.received.v1` | `eft.matched.v1` | Pair EFTs to remittances and emit match events. |
| ledger-service | `POST /payout` | `eft.matched.v1` | `payout.initiated.v1` | Payout initiation stub invoked after matches (service name reflects intended ledger ownership). |
| provider-ledger-service | `POST /provider-payout` | `payout.initiated.v1` | `payout.sent.v1` | Emits payout sent confirmations when provider ledger updates are applied. |
| batch-builder-service | `POST /batch` | `payout.initiated.v1` | `payout.sent.v1` | Builds outbound payout batches and emits payout sent confirmations. |
| payout-service | `POST /payout`, `POST /ach-return`, `POST /noc` | `payout.initiated.v1` | `payout.sent.v1`, `ach.return.v1`, `noc.received.v1` | Simulate bank disbursement, ACH returns, and NOCs. |
| bank-statement-service | `POST /statement` | `payout.sent.v1` | `bank.statement.v1` | Ingest bank statements tied to sent payouts. |
| reconciliation-service | `POST /reconcile` | `bank.statement.v1`, `payout.sent.v1` | `reconciliation.completed.v1` | Reconcile statements and payouts, emitting reconciliation results. |
| claim-system-adapter | `POST /claim` | `reconciliation.completed.v1` | `claim.payment.posted.v1` | Push posted claim payments to downstream claim systems. |

_Note: This scaffold intentionally allows both provider-ledger-service and batch-builder-service to publish `payout.sent.v1` to illustrate multiple producers; pick a single owner topic in production designs._

Every service also exposes `GET /health` for readiness checks and applies shared logging, tracing, correlation IDs, and global error handling middleware.

## Kafka Topics
Centralized in `shared/events/src/index.ts`:
- Ingestion & pairing: `eft.received.v1`, `remittance.received.v1`, `eft.matched.v1`
- Ledger & payouts: `payout.initiated.v1`, `payout.sent.v1`, `ledger.settled.v1`, `provider.ledger.updated.v1`
- Reconciliation: `bank.statement.v1`, `reconciliation.completed.v1`
- Downstream/returns: `claim.payment.posted.v1`, `ach.return.v1`, `noc.received.v1`, `ledger.posted.v1`

## Event Schemas
All events share the same validated shape (Zod schemas in `shared/events/src/index.ts`):

```ts
{
  eventType: "<EventName>V1",
  eventVersion: "1",
  correlationId: string,
  traceNumber: string,
  payerId: string,
  providerId: string,
  amount: number,
  claims?: Array<{ claimId: string; amount: number }>,
  timestamp: string
}
```

Schema exports (e.g., `EFTReceivedV1Schema`, `ProviderPayoutSentV1Schema`) plus a `validateEvent` helper enforce payload correctness before publish/consume.

## API Endpoints
Service HTTP entry points mirror the table above. Typical usage:
- `POST /eft` or `/remittance` with payload fields matching the schemas to start the flow.
- `POST /payout` (payout-service) to simulate sending funds; `POST /ach-return` and `POST /noc` to emit returns/NOCs.
- Every service: `GET /health` returns `{ status: "ok", service: "<name>" }`.

Requests may include `x-correlation-id` to propagate tracing across events.

## How to run locally
1. Install dependencies: `npm install`.
2. Copy environment: `cp .env.example .env` and fill service DB URLs/API keys.
3. Start infrastructure and services: `docker-compose up --build`.
   - Kafka brokers default to `kafka:9092`; override via `KAFKA_BROKERS` if needed.
4. Develop a single service locally with hot reload: `npm run dev --workspace services/<service-name>`.

## How to run tests
- Full suite (unit + integration harness): `npm test`.
- Unit only (amount validation helper): `npm run test:unit`.
- Integration flow (in-memory Kafka harness): `npm run test:integration`.
