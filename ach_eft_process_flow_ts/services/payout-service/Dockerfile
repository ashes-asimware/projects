FROM node:20-alpine
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/payout-service/package.json ./services/payout-service/
COPY services/payout-service/tsconfig.json ./services/payout-service/
COPY services/payout-service/prisma ./services/payout-service/prisma
COPY services/payout-service/src ./services/payout-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @services/payout-service
ENV NODE_ENV=production
CMD ["sh", "-c", "npm run migrate --workspace @services/payout-service || true; npm run start --workspace @services/payout-service"]
