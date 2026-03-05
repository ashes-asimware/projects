| Core components |
| --- |
| Email Ingestion System (3rd party) – extracts docs + fields, sends JSON to you |
| Intake Function – Azure Function receiving JSON, validates payload, producing Kafka |
| Enrichment Consumer Service – persists docs + fields, produces calculation message |
| Calculation Service – computes billing + fuel advance, produces billing/advance messages |
| Invoicing Service – runs ACH flow, publishes carrier payment events |
| Advance Service – runs EFT flow for fuel advance, publishes fuel card events |
| Ledger Service (placeholder) – offsets fuel advance vs invoice (out of scope) |
| Azure Blob Storage – document storage |
| Operational DB – carrier/load/invoice records |
