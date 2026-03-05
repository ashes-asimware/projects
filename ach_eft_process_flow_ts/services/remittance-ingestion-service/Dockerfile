FROM node:20-alpine
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/remittance-ingestion-service/package.json ./services/remittance-ingestion-service/
COPY services/remittance-ingestion-service/tsconfig.json ./services/remittance-ingestion-service/
COPY services/remittance-ingestion-service/prisma ./services/remittance-ingestion-service/prisma
COPY services/remittance-ingestion-service/src ./services/remittance-ingestion-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @services/remittance-ingestion-service
ENV NODE_ENV=production
CMD ["sh", "-c", "npm run migrate --workspace @services/remittance-ingestion-service || true; npm run start --workspace @services/remittance-ingestion-service"]
