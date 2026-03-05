import { randomUUID } from 'crypto';
import { Injectable, OnModuleInit } from '@nestjs/common';
import { KafkaTopics } from '@shared/events';
import { publish, subscribe } from '@shared/kafka';
import { createLogger } from '@shared/observability';

const PUBLISH_EVENT_TYPE = 'ProviderPayoutSentV1';
const ACH_RETURN_EVENT_TYPE = 'ACHReturnReceivedV1';
const NOC_EVENT_TYPE = 'NOCReceivedV1';

@Injectable()
export class AppService implements OnModuleInit {
  private readonly logger = createLogger('payout-service');

  async onModuleInit() {
    await subscribe(KafkaTopics.payoutInitiated, async (envelope) => {
      this.logger.info({ eventType: envelope.metadata.eventType }, 'Outbound payout processing');
    });
  }

  async publishPayout(body: any) {
    const payload = this.buildPayload(PUBLISH_EVENT_TYPE, body);
    await publish(KafkaTopics.payoutSent, payload, PUBLISH_EVENT_TYPE);
    return { correlationId: payload.correlationId, eventType: payload.eventType };
  }

  async publishAchReturn(body: any) {
    const payload = this.buildPayload(ACH_RETURN_EVENT_TYPE, body);
    await publish(KafkaTopics.achReturn, payload, ACH_RETURN_EVENT_TYPE);
    return { correlationId: payload.correlationId, eventType: payload.eventType };
  }

  async publishNoc(body: any) {
    const payload = this.buildPayload(NOC_EVENT_TYPE, body);
    await publish(KafkaTopics.nocReceived, payload, NOC_EVENT_TYPE);
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
