FROM node:20-alpine
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/batch-builder-service/package.json ./services/batch-builder-service/
COPY services/batch-builder-service/tsconfig.json ./services/batch-builder-service/
COPY services/batch-builder-service/prisma ./services/batch-builder-service/prisma
COPY services/batch-builder-service/src ./services/batch-builder-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @services/batch-builder-service
ENV NODE_ENV=production
CMD ["sh", "-c", "npm run migrate --workspace @services/batch-builder-service || true; npm run start --workspace @services/batch-builder-service"]
