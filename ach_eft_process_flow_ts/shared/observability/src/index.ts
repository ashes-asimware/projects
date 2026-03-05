import { AsyncLocalStorage } from "async_hooks";
import pino from "pino";
import { Request, Response, NextFunction } from "express";
import {
  NodeTracerProvider,
  SimpleSpanProcessor,
} from "@opentelemetry/sdk-trace-node";
import { ConsoleSpanExporter } from "@opentelemetry/sdk-trace-base";
import { OTLPTraceExporter } from "@opentelemetry/exporter-trace-otlp-http";
import { Resource } from "@opentelemetry/resources";
import { SemanticResourceAttributes } from "@opentelemetry/semantic-conventions";
import { diag, DiagConsoleLogger, DiagLogLevel, trace } from "@opentelemetry/api";

const asyncLocalStorage = new AsyncLocalStorage<{ correlationId: string }>();

export const getCorrelationId = () =>
  asyncLocalStorage.getStore()?.correlationId;

export const withCorrelationId = async <T>(
  correlationId: string,
  fn: () => Promise<T> | T
): Promise<T> => {
  return asyncLocalStorage.run({ correlationId }, fn);
};

export const correlationIdMiddleware = (
  req: Request,
  _res: Response,
  next: NextFunction
) => {
  const incoming =
    (req.headers["x-correlation-id"] as string) ||
    req.header("correlation-id") ||
    `corr-${Date.now()}`;
  asyncLocalStorage.run({ correlationId: incoming }, () => next());
};

export const requestLoggingMiddleware = (
  req: Request,
  res: Response,
  next: NextFunction
) => {
  const log = createLogger("http");
  const start = Date.now();
  res.on("finish", () => {
    log.info(
      {
        method: req.method,
        path: req.originalUrl,
        statusCode: res.statusCode,
        durationMs: Date.now() - start,
        correlationId: getCorrelationId(),
      },
      "request completed"
    );
  });
  next();
};

export const createLogger = (name: string) =>
  pino({
    name,
    level: process.env.LOG_LEVEL || "info",
    base: undefined,
    transport:
      process.env.NODE_ENV === "development"
        ? { target: "pino-pretty", options: { colorize: true } }
        : undefined,
    mixin() {
      return { correlationId: getCorrelationId() };
    },
  });

diag.setLogger(new DiagConsoleLogger(), DiagLogLevel.ERROR);

export const setupTracing = (serviceName: string) => {
  const provider = new NodeTracerProvider({
    resource: new Resource({
      [SemanticResourceAttributes.SERVICE_NAME]: serviceName,
    }),
  });

  provider.addSpanProcessor(new SimpleSpanProcessor(new ConsoleSpanExporter()));
  provider.addSpanProcessor(
    new SimpleSpanProcessor(
      new OTLPTraceExporter({
        url: process.env.OTEL_EXPORTER_OTLP_ENDPOINT || "http://localhost:4318/v1/traces",
      })
    )
  );

  provider.register();
};

export const getTracer = () => trace.getTracer("ach-eft-tracer");
