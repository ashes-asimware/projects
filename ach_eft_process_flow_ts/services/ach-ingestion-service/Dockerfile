FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/ach-ingestion-service/package.json ./services/ach-ingestion-service/
COPY services/ach-ingestion-service/tsconfig.json ./services/ach-ingestion-service/
COPY services/ach-ingestion-service/prisma ./services/ach-ingestion-service/prisma
COPY services/ach-ingestion-service/src ./services/ach-ingestion-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @shared/observability && npm run build --workspace @shared/events && npm run build --workspace @shared/kafka
RUN npm run build --workspace @services/ach-ingestion-service
RUN npm prune --omit=dev --workspaces --include-workspace-root

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/tsconfig.base.json ./
COPY --from=builder /app/shared ./shared
COPY --from=builder /app/services/ach-ingestion-service/package.json ./services/ach-ingestion-service/
COPY --from=builder /app/services/ach-ingestion-service/prisma ./services/ach-ingestion-service/prisma
COPY --from=builder /app/services/ach-ingestion-service/dist ./services/ach-ingestion-service/dist
CMD ["sh", "-c", "npm run migrate --workspace @services/ach-ingestion-service || true; npm run start --workspace @services/ach-ingestion-service"]
