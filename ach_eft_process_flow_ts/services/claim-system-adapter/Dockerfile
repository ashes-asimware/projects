FROM node:20-alpine AS builder
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/claim-system-adapter/package.json ./services/claim-system-adapter/
COPY services/claim-system-adapter/tsconfig.json ./services/claim-system-adapter/
COPY services/claim-system-adapter/prisma ./services/claim-system-adapter/prisma
COPY services/claim-system-adapter/src ./services/claim-system-adapter/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @shared/observability && npm run build --workspace @shared/events && npm run build --workspace @shared/kafka
RUN npm run build --workspace @services/claim-system-adapter
RUN npm prune --omit=dev --workspaces --include-workspace-root

FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/node_modules ./node_modules
COPY --from=builder /app/package*.json ./
COPY --from=builder /app/tsconfig.base.json ./
COPY --from=builder /app/shared ./shared
COPY --from=builder /app/services/claim-system-adapter/package.json ./services/claim-system-adapter/
COPY --from=builder /app/services/claim-system-adapter/prisma ./services/claim-system-adapter/prisma
COPY --from=builder /app/services/claim-system-adapter/dist ./services/claim-system-adapter/dist
CMD ["sh", "-c", "npm run migrate --workspace @services/claim-system-adapter || true; npm run start --workspace @services/claim-system-adapter"]
