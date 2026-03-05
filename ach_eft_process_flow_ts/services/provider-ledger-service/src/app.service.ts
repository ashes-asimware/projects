import { randomUUID } from 'crypto';
import { Injectable, OnModuleInit } from '@nestjs/common';
import { KafkaTopics, validateEvent } from '@shared/events';
import { publish, subscribe } from '@shared/kafka';
import { createLogger } from '@shared/observability';

const PUBLISH_EVENT_TYPE = 'ProviderPayoutSentV1';
const PUBLISH_TOPIC = KafkaTopics.payoutSent;
const CONSUME_TOPICS = [KafkaTopics.payoutInitiated];

@Injectable()
export class AppService implements OnModuleInit {
  private readonly logger = createLogger('provider-ledger-service');

  async onModuleInit() {
    for (const topic of CONSUME_TOPICS) {
      await subscribe(topic as any, async (envelope) => {
        this.logger.info({ topic, eventType: envelope.metadata.eventType }, 'Event consumed');
      });
    }
  }

  async publishEvent(body: any) {
    const payload = this.buildPayload(body);
    validateEvent(PUBLISH_EVENT_TYPE as any, payload);
    await publish(PUBLISH_TOPIC as any, payload, PUBLISH_EVENT_TYPE as any);
    this.logger.info({ eventType: PUBLISH_EVENT_TYPE, correlationId: payload.correlationId }, 'Event published');
    return { correlationId: payload.correlationId, eventType: payload.eventType };
  }

  private buildPayload(body: any) {
    return {
      eventType: PUBLISH_EVENT_TYPE,
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
