FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/batch-builder-service/package.json ./services/batch-builder-service/
COPY services/batch-builder-service/tsconfig.json ./services/batch-builder-service/
COPY services/batch-builder-service/prisma ./services/batch-builder-service/prisma
COPY services/batch-builder-service/src ./services/batch-builder-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @shared/observability && npm run build --workspace @shared/events && npm run build --workspace @shared/kafka
RUN npm run build --workspace @services/batch-builder-service
RUN npm prune --omit=dev --workspaces --include-workspace-root

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/tsconfig.base.json ./
COPY --from=builder /app/shared ./shared
COPY --from=builder /app/services/batch-builder-service/package.json ./services/batch-builder-service/
COPY --from=builder /app/services/batch-builder-service/prisma ./services/batch-builder-service/prisma
COPY --from=builder /app/services/batch-builder-service/dist ./services/batch-builder-service/dist
CMD ["sh", "-c", "npm run migrate --workspace @services/batch-builder-service || true; npm run start --workspace @services/batch-builder-service"]
