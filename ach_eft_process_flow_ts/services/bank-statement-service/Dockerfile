FROM node:20-alpine
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/bank-statement-service/package.json ./services/bank-statement-service/
COPY services/bank-statement-service/tsconfig.json ./services/bank-statement-service/
COPY services/bank-statement-service/prisma ./services/bank-statement-service/prisma
COPY services/bank-statement-service/src ./services/bank-statement-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @services/bank-statement-service
ENV NODE_ENV=production
CMD ["sh", "-c", "npm run migrate --workspace @services/bank-statement-service || true; npm run start --workspace @services/bank-statement-service"]
