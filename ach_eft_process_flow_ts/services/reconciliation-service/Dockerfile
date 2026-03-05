FROM node:20-alpine
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/reconciliation-service/package.json ./services/reconciliation-service/
COPY services/reconciliation-service/tsconfig.json ./services/reconciliation-service/
COPY services/reconciliation-service/prisma ./services/reconciliation-service/prisma
COPY services/reconciliation-service/src ./services/reconciliation-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @services/reconciliation-service
ENV NODE_ENV=production
CMD ["sh", "-c", "npm run migrate --workspace @services/reconciliation-service || true; npm run start --workspace @services/reconciliation-service"]
