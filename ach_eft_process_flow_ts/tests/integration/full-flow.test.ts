import assert from "node:assert";
import { describe, it } from "node:test";
import { KafkaTopics, validateEvent } from "../../shared/events/src";

type Handler = (payload: unknown) => Promise<void> | void;

const asObject = (value: unknown) =>
  typeof value === "object" && value !== null ? value : {};

class KafkaTestHarness {
  private subscribers = new Map<string, Handler[]>();
  public readonly observed: Array<{ topic: string; payload: unknown }> = [];

  subscribe(topic: string, handler: Handler) {
    const handlers = this.subscribers.get(topic) || [];
    handlers.push(handler);
    this.subscribers.set(topic, handlers);
  }

  async publish(topic: string, payload: unknown) {
    this.observed.push({ topic, payload });
    const handlers = this.subscribers.get(topic) || [];
    for (const handler of handlers) {
      await handler(payload);
    }
  }
}

class MockBankAdapter {
  private readonly bus: KafkaTestHarness;

  constructor(bus: KafkaTestHarness) {
    this.bus = bus;
    this.bus.subscribe(KafkaTopics.payoutInitiated, (payload) =>
      this.handlePayout(payload)
    );
  }

  private async handlePayout(payload: unknown) {
    await this.bus.publish(KafkaTopics.payoutSent, {
      ...asObject(payload),
      eventType: "ProviderPayoutSentV1",
      timestamp: new Date().toISOString(),
    });
    await this.bus.publish(KafkaTopics.ledgerSettled, {
      ...asObject(payload),
      eventType: "LedgerSettlementPostedV1",
      timestamp: new Date().toISOString(),
    });
    await this.bus.publish(KafkaTopics.bankStatement, {
      ...asObject(payload),
      eventType: "BankStatementReceivedV1",
      timestamp: new Date().toISOString(),
    });
  }
}

class MockClaimSystem {
  private readonly bus: KafkaTestHarness;
  public receivedClaims: unknown[] = [];

  constructor(bus: KafkaTestHarness) {
    this.bus = bus;
    this.bus.subscribe(KafkaTopics.claimPaymentPosted, (payload) => {
      this.receivedClaims.push(payload);
    });
  }
}

describe("ACH to payout happy-path integration", () => {
  it("simulates full event flow across services", async () => {
    const bus = new KafkaTestHarness();
    // Instantiation registers mock handlers on the in-memory bus.
    const mockBankAdapter = new MockBankAdapter(bus);
    const mockClaimSystem = new MockClaimSystem(bus);
    let lastEft: unknown = null;
    let lastRemittance: unknown = null;

    const attemptPairing = async () => {
      if (!lastEft || !lastRemittance) return;
      await bus.publish(KafkaTopics.eftMatched, {
        ...asObject(lastEft),
        ...asObject(lastRemittance),
        eventType: "EFTMatchedToRemittanceV1",
      });
    };

    const baseEvent = {
      eventVersion: "1",
      correlationId: "corr-123",
      traceNumber: "trace-abc",
      payerId: "payer-1",
      providerId: "provider-9",
      amount: 1250,
      claims: [{ claimId: "clm-1", amount: 1250 }],
      timestamp: new Date().toISOString(),
    };

    bus.subscribe(KafkaTopics.eftReceived, async (payload) => {
      lastEft = validateEvent("EFTReceivedV1", payload);
      await bus.publish(KafkaTopics.ledgerPosted, {
        ...asObject(payload),
        eventType: "LedgerEntryPostedV1",
      });
      await attemptPairing();
    });

    bus.subscribe(KafkaTopics.ledgerPosted, (payload) => {
      validateEvent("LedgerEntryPostedV1", payload);
    });

    bus.subscribe(KafkaTopics.remittanceReceived, (payload) => {
      lastRemittance = validateEvent("RemittanceReceivedV1", payload);
      return attemptPairing();
    });

    bus.subscribe(KafkaTopics.eftMatched, async (payload) => {
      validateEvent("EFTMatchedToRemittanceV1", payload);
      await bus.publish(KafkaTopics.providerLedgerUpdated, {
        ...asObject(payload),
        eventType: "ProviderLedgerUpdatedV1",
      });
    });

    bus.subscribe(KafkaTopics.providerLedgerUpdated, async (payload) => {
      validateEvent("ProviderLedgerUpdatedV1", payload);
      await bus.publish(KafkaTopics.payoutInitiated, {
        ...asObject(payload),
        eventType: "ProviderPayoutInitiatedV1",
      });
    });

    bus.subscribe(KafkaTopics.payoutSent, (payload) => {
      validateEvent("ProviderPayoutSentV1", payload);
    });

    bus.subscribe(KafkaTopics.ledgerSettled, (payload) => {
      validateEvent("LedgerSettlementPostedV1", payload);
    });

    bus.subscribe(KafkaTopics.bankStatement, async (payload) => {
      validateEvent("BankStatementReceivedV1", payload);
      await bus.publish(KafkaTopics.reconciliationCompleted, {
        ...asObject(payload),
        eventType: "ReconciliationCompletedV1",
      });
    });

    bus.subscribe(KafkaTopics.reconciliationCompleted, async (payload) => {
      validateEvent("ReconciliationCompletedV1", payload);
      await bus.publish(KafkaTopics.claimPaymentPosted, {
        ...asObject(payload),
        eventType: "ClaimPaymentPostedV1",
      });
    });

    await bus.publish(KafkaTopics.eftReceived, {
      ...baseEvent,
      eventType: "EFTReceivedV1",
    });
    await bus.publish(KafkaTopics.remittanceReceived, {
      ...baseEvent,
      eventType: "RemittanceReceivedV1",
    });

    assert.ok(
      mockClaimSystem.receivedClaims.length > 0,
      'Claim system received posted claim'
    );

    const topicsInOrder = bus.observed.map((e) => e.topic);
    assert.deepStrictEqual(topicsInOrder, [
      KafkaTopics.eftReceived,
      KafkaTopics.ledgerPosted,
      KafkaTopics.remittanceReceived,
      KafkaTopics.eftMatched,
      KafkaTopics.providerLedgerUpdated,
      KafkaTopics.payoutInitiated,
      KafkaTopics.payoutSent,
      KafkaTopics.ledgerSettled,
      KafkaTopics.bankStatement,
      KafkaTopics.reconciliationCompleted,
      KafkaTopics.claimPaymentPosted,
    ]);
  });
});
