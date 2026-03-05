import { randomUUID } from 'crypto';
import { Injectable, OnModuleInit } from '@nestjs/common';
import { KafkaTopics, validateEvent } from '@shared/events';
import { publish, subscribe } from '@shared/kafka';
import { createLogger } from '@shared/observability';

const PAYOUT_SENT_EVENT = 'ProviderPayoutSentV1';

@Injectable()
export class AppService implements OnModuleInit {
  private readonly logger = createLogger('payout-service');

  async onModuleInit() {
    await subscribe(KafkaTopics.payoutInitiated, async (envelope) => {
      this.logger.info({ eventType: envelope.metadata.eventType }, 'Outbound payout processing');
    });
  }

  async publishPayout(body: any) {
    const payload = this.buildPayload(PAYOUT_SENT_EVENT, body);
    validateEvent(PAYOUT_SENT_EVENT, payload);
    await publish(KafkaTopics.payoutSent, payload, PAYOUT_SENT_EVENT);
    return { correlationId: payload.correlationId, eventType: payload.eventType };
  }

  async publishAchReturn(body: any) {
    const payload = this.buildPayload('ACHReturnReceivedV1', body);
    validateEvent('ACHReturnReceivedV1', payload);
    await publish(KafkaTopics.achReturn, payload, 'ACHReturnReceivedV1');
    return { correlationId: payload.correlationId, eventType: payload.eventType };
  }

  async publishNoc(body: any) {
    const payload = this.buildPayload('NOCReceivedV1', body);
    validateEvent('NOCReceivedV1', payload);
    await publish(KafkaTopics.nocReceived, payload, 'NOCReceivedV1');
    return { correlationId: payload.correlationId, eventType: payload.eventType };
  }

  private buildPayload(eventType: string, body: any) {
    return {
      eventType,
      eventVersion: '1',
      correlationId: body?.correlationId || randomUUID(),
      traceNumber: body?.traceNumber || randomUUID(),
      payerId: body?.payerId || 'payer-default',
      providerId: body?.providerId || 'provider-default',
      amount: Number(body?.amount || 0),
      claims: body?.claims || [],
      timestamp: body?.timestamp || new Date().toISOString(),
    };
  }
}
