FROM node:20-alpine
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/pairing-service/package.json ./services/pairing-service/
COPY services/pairing-service/tsconfig.json ./services/pairing-service/
COPY services/pairing-service/prisma ./services/pairing-service/prisma
COPY services/pairing-service/src ./services/pairing-service/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @services/pairing-service
ENV NODE_ENV=production
CMD ["sh", "-c", "npm run migrate --workspace @services/pairing-service || true; npm run start --workspace @services/pairing-service"]
