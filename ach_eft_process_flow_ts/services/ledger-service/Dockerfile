FROM node:20-alpine
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/ledger-service/package.json ./services/ledger-service/
COPY services/ledger-service/tsconfig.json ./services/ledger-service/
COPY services/ledger-service/prisma ./services/ledger-service/prisma
COPY services/ledger-service/src ./services/ledger-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @services/ledger-service
ENV NODE_ENV=production
CMD ["sh", "-c", "npm run migrate --workspace @services/ledger-service || true; npm run start --workspace @services/ledger-service"]
