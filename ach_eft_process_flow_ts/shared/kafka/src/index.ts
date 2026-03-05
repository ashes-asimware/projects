import { Kafka, Message } from "kafkajs";
import { context, trace } from "@opentelemetry/api";
import pino from "pino";
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

async function ensureProducer() {
  if (!producer["__connected"]) {
    await producer.connect();
    // @ts-ignore
    producer["__connected"] = true;
  }
}

export async function publish<T extends keyof typeof validators>(
  topic: keyof typeof KafkaTopics | string,
  payload: unknown,
  eventType: T
): Promise<void> {
  const correlationId =
    (payload as any)?.correlationId ||
    getCorrelationId() ||
    `corr-${Date.now()}-${Math.random()}`;

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
    await sendToDeadLetter(topic, envelope);
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
  await ensureProducer();
  await producer.send({
    topic: dlq,
    messages: [{ value: JSON.stringify(envelope) }],
  });
}

export async function subscribe<T>(
  topic: keyof typeof KafkaTopics | string,
  handler: EventHandler<T>
): Promise<void> {
  const consumer = kafka.consumer({
    groupId: `group-${typeof topic === "string" ? topic : KafkaTopics[topic]}`,
  });
  await consumer.connect();
  await consumer.subscribe({
    topic: typeof topic === "string" ? topic : KafkaTopics[topic],
    fromBeginning: false,
  });

  await consumer.run({
    eachMessage: async ({ message }) => {
      const envelope = parseEnvelope<T>(message);
      const correlationId =
        envelope?.metadata?.correlationId ||
        message.headers?.["x-correlation-id"]?.toString() ||
        `corr-${Date.now()}`;

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
            await sendToDeadLetter(topic, envelope ?? { metadata: { correlationId, traceNumber: "", eventType: "unknown", eventVersion: "1", timestamp: new Date().toISOString() }, payload: {} });
          } finally {
            const currentSpan = trace.getSpan(ctx);
            currentSpan?.end();
          }
        });
      });
    },
  });
}

function parseEnvelope<T>(message: Message): EventEnvelope<T> | null {
  if (!message.value) return null;
  try {
    return JSON.parse(message.value.toString());
  } catch (err) {
    logger.warn({ err }, "Failed to parse message");
    return null;
  }
}

export { KafkaTopics };
