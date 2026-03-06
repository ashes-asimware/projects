FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/bank-statement-service/package.json ./services/bank-statement-service/
COPY services/bank-statement-service/tsconfig.json ./services/bank-statement-service/
COPY services/bank-statement-service/prisma ./services/bank-statement-service/prisma
COPY services/bank-statement-service/src ./services/bank-statement-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @shared/observability && npm run build --workspace @shared/events && npm run build --workspace @shared/kafka
RUN npm run build --workspace @services/bank-statement-service
RUN npm prune --omit=dev --workspaces --include-workspace-root

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/tsconfig.base.json ./
COPY --from=builder /app/shared ./shared
COPY --from=builder /app/services/bank-statement-service/package.json ./services/bank-statement-service/
COPY --from=builder /app/services/bank-statement-service/prisma ./services/bank-statement-service/prisma
COPY --from=builder /app/services/bank-statement-service/dist ./services/bank-statement-service/dist
CMD ["sh", "-c", "npm run migrate --workspace @services/bank-statement-service || true; npm run start --workspace @services/bank-statement-service"]
