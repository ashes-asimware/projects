FROM node:20-alpine
WORKDIR /app
COPY package*.json tsconfig.base.json ./
COPY shared ./shared
COPY services/claim-system-adapter/package.json ./services/claim-system-adapter/
COPY services/claim-system-adapter/tsconfig.json ./services/claim-system-adapter/
COPY services/claim-system-adapter/prisma ./services/claim-system-adapter/prisma
COPY services/claim-system-adapter/src ./services/claim-system-adapter/src
RUN npm install --workspaces --include-workspace-root --legacy-peer-deps
RUN npm run build --workspace @services/claim-system-adapter
ENV NODE_ENV=production
CMD ["sh", "-c", "npm run migrate --workspace @services/claim-system-adapter || true; npm run start --workspace @services/claim-system-adapter"]
