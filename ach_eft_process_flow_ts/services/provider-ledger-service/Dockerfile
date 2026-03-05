FROM node:20-alpine
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/provider-ledger-service/package.json ./services/provider-ledger-service/
COPY services/provider-ledger-service/tsconfig.json ./services/provider-ledger-service/
COPY services/provider-ledger-service/prisma ./services/provider-ledger-service/prisma
COPY services/provider-ledger-service/src ./services/provider-ledger-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @services/provider-ledger-service
ENV NODE_ENV=production
CMD ["sh", "-c", "npm run migrate --workspace @services/provider-ledger-service || true; npm run start --workspace @services/provider-ledger-service"]
