FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/payout-service/package.json ./services/payout-service/
COPY services/payout-service/tsconfig.json ./services/payout-service/
COPY services/payout-service/prisma ./services/payout-service/prisma
COPY services/payout-service/src ./services/payout-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @shared/observability && npm run build --workspace @shared/events && npm run build --workspace @shared/kafka
RUN npm run build --workspace @services/payout-service
RUN npm prune --omit=dev --workspaces --include-workspace-root

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/tsconfig.base.json ./
COPY --from=builder /app/shared ./shared
COPY --from=builder /app/services/payout-service/package.json ./services/payout-service/
COPY --from=builder /app/services/payout-service/prisma ./services/payout-service/prisma
COPY --from=builder /app/services/payout-service/dist ./services/payout-service/dist
CMD ["sh", "-c", "npm run migrate --workspace @services/payout-service || true; npm run start --workspace @services/payout-service"]
