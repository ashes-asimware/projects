FROM node:20-alpine
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/ach-ingestion-service/package.json ./services/ach-ingestion-service/
COPY services/ach-ingestion-service/tsconfig.json ./services/ach-ingestion-service/
COPY services/ach-ingestion-service/prisma ./services/ach-ingestion-service/prisma
COPY services/ach-ingestion-service/src ./services/ach-ingestion-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @services/ach-ingestion-service
ENV NODE_ENV=production
CMD ["sh", "-c", "npm run migrate --workspace @services/ach-ingestion-service || true; npm run start --workspace @services/ach-ingestion-service"]
