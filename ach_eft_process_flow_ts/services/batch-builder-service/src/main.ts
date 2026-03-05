import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { correlationIdMiddleware, requestLoggingMiddleware, setupTracing, createLogger, errorHandlingMiddleware } from '@shared/observability';

async function bootstrap() {
  const serviceName = process.env.SERVICE_NAME || 'batch-builder-service';
  setupTracing(serviceName);
  const app = await NestFactory.create(AppModule, { logger: false });
  app.use(correlationIdMiddleware, requestLoggingMiddleware);
  app.use(errorHandlingMiddleware);
  const logger = createLogger(serviceName);
  app.useLogger(logger as any);
  const port = process.env.PORT || 3000;
  await app.listen(port);
  logger.info({ port }, 'Service listening');
}
bootstrap();
