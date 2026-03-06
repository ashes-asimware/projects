import { NestFactory } from '@nestjs/core';
import { AppModule } from './app.module';
import { correlationIdMiddleware, requestLoggingMiddleware, setupTracing, createLogger, GlobalErrorFilter, errorHandlingMiddleware } from '@shared/observability';

async function bootstrap() {
  const serviceName = process.env.SERVICE_NAME || 'batch-builder-service';
  setupTracing(serviceName);
  const app = await NestFactory.create(AppModule, { logger: false });
  app.use(correlationIdMiddleware, requestLoggingMiddleware);
  app.useGlobalFilters(new GlobalErrorFilter());
  const logger = createLogger(serviceName);
  app.useLogger(logger as any);
  await app.init(); // register routes before attaching Express error handler
  app.use(errorHandlingMiddleware);
  const port = process.env.PORT || 3000;
  await app.listen(port);
  logger.info({ port }, 'Service listening');
}
bootstrap();
