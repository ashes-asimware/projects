# Message responsibilities and payload hints

1) EnrichedPayloadSent (Intake Function → Kafka)
Purpose: Move from external JSON + public links to internal, self-contained message.
Contains (example):
Header: messageId, sourceSystem, createdAt
Carrier: carrierId, carrierName, address, dotId, mcRegId, afmlClearanceId
Load: descriptionOfGoods, truckType, totalWeight, additionalInfo
Invoice: lineItems[], totalAmountBilled
Documents: embedded or encoded blobs (BOL, invoice, insurance, etc.) or signed URLs with short TTL

2) EnrichedPayloadReceived (Enrichment Service → Kafka)
Purpose: Persist docs, then reference them by internal URIs for downstream services.
Contains:
All invoicing fields (carrier, load, invoice)
Blob URIs: internal URIs for each document
Internal IDs: carrierRecordId, loadId, invoiceId

3) BillingInvoicePrepared (Calculation → Invoicing)
Purpose: Provide final billing numbers for ACH.
Contains:
loadId, carrierId, shipperId
grossAmount, factoringFees, netAmountToCarrier
currency, dueDate, invoiceNumber
references to Blob URIs if needed

4) FuelAdvanceRequested (Calculation → Advance)
Purpose: Drive fuel advance EFT.
Contains:
carrierId, loadId
advanceAmount, method (card/EFT), constraints
correlationId to tie back to invoice/ledger

5) CarrierPaymentIssued (Invoicing → Kafka)
Purpose: Signal successful ACH + reconciliation.
Contains:
carrierId, loadId, invoiceId
paymentAmount, paymentDate, achTraceId
reconciliationStatus

6) FuelCardDispatched (Advance → Kafka)
Purpose: Signal successful fuel advance.
Contains:
carrierId, loadId
advanceAmount, dispatchTime
card/account reference, eftTraceId