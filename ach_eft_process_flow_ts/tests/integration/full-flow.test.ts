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

  async publish(topic: string, payload: any) {
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

  private async handlePayout(payload: any) {
    await this.bus.publish(KafkaTopics.payoutSent, {
      ...asObject(payload),
      eventType: "ProviderPayoutSentV1",
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
    const bank = new MockBankAdapter(bus);
    const claimSystem = new MockClaimSystem(bus);

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
      validateEvent("EFTReceivedV1", payload);
      await bus.publish(KafkaTopics.eftMatched, {
        ...asObject(payload),
        eventType: "EFTMatchedToRemittanceV1",
      });
    });

    bus.subscribe(KafkaTopics.remittanceReceived, (payload) => {
      validateEvent("RemittanceReceivedV1", payload);
    });

    bus.subscribe(KafkaTopics.eftMatched, async (payload) => {
      validateEvent("EFTMatchedToRemittanceV1", payload);
      await bus.publish(KafkaTopics.payoutInitiated, {
        ...asObject(payload),
        eventType: "ProviderPayoutInitiatedV1",
      });
    });

    bus.subscribe(KafkaTopics.payoutSent, (payload) => {
      validateEvent("ProviderPayoutSentV1", payload);
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
      claimSystem.receivedClaims.length > 0,
      "Claim system received posted claim"
    );

    const topicsInOrder = bus.observed.map((e) => e.topic);
    assert.deepStrictEqual(topicsInOrder, [
      KafkaTopics.eftReceived,
      KafkaTopics.eftMatched,
      KafkaTopics.remittanceReceived,
      KafkaTopics.payoutInitiated,
      KafkaTopics.payoutSent,
      KafkaTopics.bankStatement,
      KafkaTopics.reconciliationCompleted,
      KafkaTopics.claimPaymentPosted,
    ]);
  });
});
