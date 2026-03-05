FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/reconciliation-service/package.json ./services/reconciliation-service/
COPY services/reconciliation-service/tsconfig.json ./services/reconciliation-service/
COPY services/reconciliation-service/prisma ./services/reconciliation-service/prisma
COPY services/reconciliation-service/src ./services/reconciliation-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @shared/observability && npm run build --workspace @shared/events && npm run build --workspace @shared/kafka
RUN npm run build --workspace @services/reconciliation-service
RUN npm prune --omit=dev --workspaces --include-workspace-root

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/tsconfig.base.json ./
COPY --from=builder /app/shared ./shared
COPY --from=builder /app/services/reconciliation-service/package.json ./services/reconciliation-service/
COPY --from=builder /app/services/reconciliation-service/prisma ./services/reconciliation-service/prisma
COPY --from=builder /app/services/reconciliation-service/dist ./services/reconciliation-service/dist
CMD ["sh", "-c", "npm run migrate --workspace @services/reconciliation-service || true; npm run start --workspace @services/reconciliation-service"]
