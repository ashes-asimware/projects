FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/pairing-service/package.json ./services/pairing-service/
COPY services/pairing-service/tsconfig.json ./services/pairing-service/
COPY services/pairing-service/prisma ./services/pairing-service/prisma
COPY services/pairing-service/src ./services/pairing-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @shared/observability && npm run build --workspace @shared/events && npm run build --workspace @shared/kafka
RUN npm run build --workspace @services/pairing-service
RUN npm prune --omit=dev --workspaces --include-workspace-root

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/tsconfig.base.json ./
COPY --from=builder /app/shared ./shared
COPY --from=builder /app/services/pairing-service/package.json ./services/pairing-service/
COPY --from=builder /app/services/pairing-service/prisma ./services/pairing-service/prisma
COPY --from=builder /app/services/pairing-service/dist ./services/pairing-service/dist
CMD ["sh", "-c", "npm run migrate --workspace @services/pairing-service || true; npm run start --workspace @services/pairing-service"]
