FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/ledger-service/package.json ./services/ledger-service/
COPY services/ledger-service/tsconfig.json ./services/ledger-service/
COPY services/ledger-service/prisma ./services/ledger-service/prisma
COPY services/ledger-service/src ./services/ledger-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @shared/observability && npm run build --workspace @shared/events && npm run build --workspace @shared/kafka
RUN npm run build --workspace @services/ledger-service
RUN npm prune --omit=dev --workspaces --include-workspace-root

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/tsconfig.base.json ./
COPY --from=builder /app/shared ./shared
COPY --from=builder /app/services/ledger-service/package.json ./services/ledger-service/
COPY --from=builder /app/services/ledger-service/prisma ./services/ledger-service/prisma
COPY --from=builder /app/services/ledger-service/dist ./services/ledger-service/dist
CMD ["sh", "-c", "npm run migrate --workspace @services/ledger-service || true; npm run start --workspace @services/ledger-service"]
