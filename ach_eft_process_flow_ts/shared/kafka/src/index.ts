import { randomUUID } from "crypto";
import { Kafka, Message } from "kafkajs";
import { context, trace } from "@opentelemetry/api";
import { z } from "zod";
import {
  EventEnvelope,
  KafkaTopics,
  validators,
} from "@shared/events";
import {
  createLogger,
  withCorrelationId,
  getCorrelationId,
  getTracer,
} from "@shared/observability";

export type EventHandler<T> = (envelope: EventEnvelope<T>) => Promise<void> | void;

const logger = createLogger("shared-kafka");
const tracer = getTracer();
const envelopeSchema = z.object({
  metadata: z.object({
    correlationId: z.string(),
    traceNumber: z.string(),
    eventType: z.string(),
    eventVersion: z.string(),
    timestamp: z.string(),
  }),
  payload: z.any(),
});

const kafka = new Kafka({
  clientId: "ach-eft-platform",
  brokers: (process.env.KAFKA_BROKERS || "kafka:9092").split(","),
  logCreator: () => (entry) => {
    logger.info(
      {
        namespace: "kafkajs",
        severity: entry.level,
      },
      entry.log.message
    );
  },
});

const producer = kafka.producer();
let producerConnected = false;
let producerReadyPromise: Promise<void> | null = null;

async function ensureProducer() {
  if (producerConnected) return;
  if (!producerReadyPromise) {
    producerReadyPromise = producer.connect().then(() => {
      producerConnected = true;
    });
  }
  await producerReadyPromise;
}

function resolveCorrelationId(
  ...candidates: Array<string | undefined | null>
): string {
  for (const candidate of candidates) {
    if (candidate) return candidate;
  }
  return randomUUID();
}

export async function publish<T extends keyof typeof validators>(
  topic: keyof typeof KafkaTopics | string,
  payload: unknown,
  eventType: T
): Promise<void> {
  const correlationId =
    resolveCorrelationId((payload as any)?.correlationId, getCorrelationId());

  const parsed = validators[eventType].parse(payload);
  const envelope: EventEnvelope<typeof parsed> = {
    metadata: {
      correlationId,
      traceNumber: parsed.traceNumber,
      eventType: parsed.eventType,
      eventVersion: parsed.eventVersion,
      timestamp: parsed.timestamp,
    },
    payload: parsed,
  };

  const span = tracer.startSpan(`publish ${eventType}`, {
    attributes: {
      "messaging.system": "kafka",
      "messaging.destination": topic,
      "messaging.kafka.message_key": correlationId,
    },
  });

  try {
    await ensureProducer();
    await producer.send({
      topic: typeof topic === "string" ? topic : KafkaTopics[topic],
      messages: [
        {
          key: correlationId,
          value: JSON.stringify(envelope),
          headers: { "x-correlation-id": correlationId },
        },
      ],
    });
    logger.info({ topic, eventType, correlationId }, "Event published");
  } catch (err) {
    logger.error({ err, topic, eventType }, "Failed to publish event");
    try {
      await sendToDeadLetter(topic, envelope);
      logger.warn({ topic, eventType, correlationId }, "Event redirected to DLQ after publish failure");
    } catch (dlqError) {
      logger.error({ dlqError, topic }, "Failed to send to DLQ after publish error");
    }
    throw err;
  } finally {
    span.end();
  }
}

async function sendToDeadLetter(
  topic: string | keyof typeof KafkaTopics,
  envelope: EventEnvelope<unknown>
) {
  const dlq = `${typeof topic === "string" ? topic : KafkaTopics[topic]}.DLQ`;
  try {
    await ensureProducer();
    await producer.send({
      topic: dlq,
      messages: [{ value: JSON.stringify(envelope) }],
    });
  } catch (err) {
    logger.error({ err, topic: dlq }, "Failed to send message to DLQ");
  }
}

export async function subscribe<T>(
  topic: keyof typeof KafkaTopics | string,
  handler: EventHandler<T>
): Promise<void> {
  const consumer = kafka.consumer({
    groupId: `group-${typeof topic === "string" ? topic : KafkaTopics[topic]}`,
  });
  const subscribeFromBeginning =
    process.env.KAFKA_SUBSCRIBE_FROM_BEGINNING === "true";
  await consumer.connect();
  await consumer.subscribe({
    topic: typeof topic === "string" ? topic : KafkaTopics[topic],
    fromBeginning: subscribeFromBeginning,
  });

  await consumer.run({
    eachMessage: async ({ message }) => {
      const envelope = parseEnvelope<T>(message);
      const correlationId = resolveCorrelationId(
        envelope?.metadata?.correlationId,
        message.headers?.["x-correlation-id"]?.toString()
      );

      await withCorrelationId(correlationId, async () => {
        const ctx = trace.setSpan(
          context.active(),
          tracer.startSpan(`consume ${envelope?.metadata?.eventType || "event"}`)
        );
        await context.with(ctx, async () => {
          try {
            if (envelope) {
              await handler(envelope);
              logger.info(
                { topic, correlationId },
                "Event consumed successfully"
              );
            }
          } catch (err) {
            logger.error(
              { err, topic, correlationId },
              "Error during event handling"
            );
            await sendToDeadLetter(
              topic,
              envelope ?? buildFallbackEnvelope(correlationId)
            );
          } finally {
            const currentSpan = trace.getSpan(ctx);
            currentSpan?.end();
          }
        });
      });
    },
  });

  const disconnect = async () => {
    try {
      await consumer.disconnect();
    } catch (err) {
      logger.error({ err }, "Error disconnecting Kafka consumer");
    }
  };
  process.once("SIGINT", disconnect);
  process.once("SIGTERM", disconnect);
}

function parseEnvelope<T>(message: Message): EventEnvelope<T> | null {
  if (!message.value) return null;
  try {
    const parsedJson = JSON.parse(message.value.toString());
    const validated = envelopeSchema.safeParse(parsedJson);
    if (!validated.success) {
      logger.warn({ issues: validated.error.format() }, "Invalid envelope received");
      return null;
    }
    return validated.data as EventEnvelope<T>;
  } catch (err) {
    logger.warn({ err }, "Failed to parse message");
    return null;
  }
}

function buildFallbackEnvelope(
  correlationId: string
): EventEnvelope<unknown> {
  return {
    metadata: {
      correlationId,
      traceNumber: "",
      eventType: "unknown",
      eventVersion: "1",
      timestamp: new Date().toISOString(),
    },
    payload: {},
  };
}

export { KafkaTopics };
