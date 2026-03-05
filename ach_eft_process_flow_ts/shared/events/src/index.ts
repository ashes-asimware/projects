import { z } from "zod";

const claimItemSchema = z.object({
  claimId: z.string(),
  amount: z.number(),
});

const baseFields = {
  eventVersion: z.literal("1"),
  correlationId: z.string(),
  traceNumber: z.string(),
  payerId: z.string(),
  providerId: z.string(),
  amount: z.number(),
  claims: z.array(claimItemSchema).optional(),
  timestamp: z.string(),
};

const createEventSchema = <T extends string>(eventType: T) =>
  z.object({
    ...baseFields,
    eventType: z.literal(eventType),
  });

export const EFTReceivedV1Schema = createEventSchema("EFTReceivedV1");
export type EFTReceivedV1 = z.infer<typeof EFTReceivedV1Schema>;

export const RemittanceReceivedV1Schema = createEventSchema("RemittanceReceivedV1");
export type RemittanceReceivedV1 = z.infer<typeof RemittanceReceivedV1Schema>;

export const EFTMatchedToRemittanceV1Schema = createEventSchema("EFTMatchedToRemittanceV1");
export type EFTMatchedToRemittanceV1 = z.infer<typeof EFTMatchedToRemittanceV1Schema>;

export const ProviderPayoutInitiatedV1Schema = createEventSchema("ProviderPayoutInitiatedV1");
export type ProviderPayoutInitiatedV1 = z.infer<typeof ProviderPayoutInitiatedV1Schema>;

export const ProviderPayoutSentV1Schema = createEventSchema("ProviderPayoutSentV1");
export type ProviderPayoutSentV1 = z.infer<typeof ProviderPayoutSentV1Schema>;

export const BankStatementReceivedV1Schema = createEventSchema("BankStatementReceivedV1");
export type BankStatementReceivedV1 = z.infer<typeof BankStatementReceivedV1Schema>;

export const ReconciliationCompletedV1Schema = createEventSchema("ReconciliationCompletedV1");
export type ReconciliationCompletedV1 = z.infer<typeof ReconciliationCompletedV1Schema>;

export const ClaimPaymentPostedV1Schema = createEventSchema("ClaimPaymentPostedV1");
export type ClaimPaymentPostedV1 = z.infer<typeof ClaimPaymentPostedV1Schema>;

export const ACHReturnReceivedV1Schema = createEventSchema("ACHReturnReceivedV1");
export type ACHReturnReceivedV1 = z.infer<typeof ACHReturnReceivedV1Schema>;

export const NOCReceivedV1Schema = createEventSchema("NOCReceivedV1");
export type NOCReceivedV1 = z.infer<typeof NOCReceivedV1Schema>;

export type EventSchemas =
  | EFTReceivedV1
  | RemittanceReceivedV1
  | EFTMatchedToRemittanceV1
  | ProviderPayoutInitiatedV1
  | ProviderPayoutSentV1
  | BankStatementReceivedV1
  | ReconciliationCompletedV1
  | ClaimPaymentPostedV1
  | ACHReturnReceivedV1
  | NOCReceivedV1;

export type EventEnvelope<T> = {
  metadata: {
    correlationId: string;
    traceNumber: string;
    eventType: string;
    eventVersion: string;
    timestamp: string;
  };
  payload: T;
};

export const KafkaTopics = {
  eftReceived: "eft.received.v1",
  remittanceReceived: "remittance.received.v1",
  eftMatched: "eft.matched.v1",
  payoutInitiated: "payout.initiated.v1",
  payoutSent: "payout.sent.v1",
  bankStatement: "bank.statement.v1",
  reconciliationCompleted: "reconciliation.completed.v1",
  claimPaymentPosted: "claim.payment.posted.v1",
  achReturn: "ach.return.v1",
  nocReceived: "noc.received.v1",
} as const;

export const validators = {
  EFTReceivedV1: EFTReceivedV1Schema,
  RemittanceReceivedV1: RemittanceReceivedV1Schema,
  EFTMatchedToRemittanceV1: EFTMatchedToRemittanceV1Schema,
  ProviderPayoutInitiatedV1: ProviderPayoutInitiatedV1Schema,
  ProviderPayoutSentV1: ProviderPayoutSentV1Schema,
  BankStatementReceivedV1: BankStatementReceivedV1Schema,
  ReconciliationCompletedV1: ReconciliationCompletedV1Schema,
  ClaimPaymentPostedV1: ClaimPaymentPostedV1Schema,
  ACHReturnReceivedV1: ACHReturnReceivedV1Schema,
  NOCReceivedV1: NOCReceivedV1Schema,
};

export function validateEvent<T extends keyof typeof validators>(
  schemaKey: T,
  payload: unknown
): z.infer<(typeof validators)[T]> {
  return validators[schemaKey].parse(payload);
}
