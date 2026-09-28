# syntax=docker/dockerfile:1

FROM node:22-alpine AS build

WORKDIR /workspace
RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY apps/web/package.json ./apps/web/package.json
RUN pnpm install --frozen-lockfile

COPY apps/web ./apps/web
ENV NITRO_PRESET=node-server
RUN pnpm --filter @synapseos/web build

FROM node:22-alpine AS web

ENV NODE_ENV=production \
    HOST=0.0.0.0 \
    PORT=3000

WORKDIR /app
COPY --from=build --chown=node:node /workspace/apps/web/.output ./

USER node
EXPOSE 3000
STOPSIGNAL SIGTERM
CMD ["node", "server/index.mjs"]
