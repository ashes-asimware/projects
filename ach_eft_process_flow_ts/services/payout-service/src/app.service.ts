import { Injectable, OnModuleInit } from '@nestjs/common';
import { KafkaTopics, validateEvent } from '@shared/events';
import { publish, subscribe } from '@shared/kafka';
import { createLogger } from '@shared/observability';

@Injectable()
export class AppService implements OnModuleInit {
  private readonly logger = createLogger('payout-service');

  async onModuleInit() {
    await subscribe(KafkaTopics.payoutInitiated, async (envelope) => {
      this.logger.info({ eventType: envelope.metadata.eventType }, 'Outbound payout processing');
    });
  }

  async publishPayout(body: any) {
    const payload = this.buildPayload('ProviderPayoutSentV1', body);
    validateEvent('ProviderPayoutSentV1', payload);
    await publish(KafkaTopics.payoutSent, payload, 'ProviderPayoutSentV1');
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
      correlationId: body?.correlationId || 'corr-' + Date.now(),
      traceNumber: body?.traceNumber || 'trace-' + Date.now(),
      payerId: body?.payerId || 'payer-default',
      providerId: body?.providerId || 'provider-default',
      amount: Number(body?.amount || 0),
      claims: body?.claims || [],
      timestamp: body?.timestamp || new Date().toISOString(),
    };
  }
}
