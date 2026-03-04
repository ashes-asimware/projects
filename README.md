# projects

Python monorepo scaffold for a multi-service healthcare ACH/EFT processing system.

Services:
- ach_ingestion_service
- ledger_service
- remittance_ingestion_service
- pairing_service
- provider_ledger_service
- payout_service
- batch_builder_service
- reconciliation_service
- claim_system_adapter

Shared modules:
- shared/events
- shared/servicebus
