# syntax=docker/dockerfile:1.7
# Sparta web app: multi-stage build of the Next.js standalone output.
#
#   docker build -t sparta-web \
#     --build-arg NEXT_PUBLIC_API_BASE_URL=https://api.example.com \
#     --build-arg NEXT_PUBLIC_AUTH_MODE=dev .
#   docker run --rm -p 3000:3000 sparta-web
#
# NEXT_PUBLIC_* values are inlined into the browser bundle (and into the Content-Security-Policy) at BUILD time, so they are
# build arguments, not runtime environment variables. Never put a secret in a NEXT_PUBLIC_* variable.
ARG NODE_VERSION=22

FROM node:${NODE_VERSION}-alpine AS deps
WORKDIR /app
# Behind a corporate npm mirror: --build-arg NPM_REGISTRY=<mirror url> (npm rewrites the registry.npmjs.org URLs of the lock file to it).
ARG NPM_REGISTRY=https://registry.npmjs.org/
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund --registry="${NPM_REGISTRY}"

FROM node:${NODE_VERSION}-alpine AS build
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
ARG NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
ARG NEXT_PUBLIC_AUTH_MODE=dev
ARG NEXT_PUBLIC_OIDC_AUTHORITY=
ARG NEXT_PUBLIC_OIDC_CLIENT_ID=
ARG NEXT_PUBLIC_OIDC_SCOPE=
ENV NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_PUBLIC_AUTH_MODE=${NEXT_PUBLIC_AUTH_MODE} \
    NEXT_PUBLIC_OIDC_AUTHORITY=${NEXT_PUBLIC_OIDC_AUTHORITY} \
    NEXT_PUBLIC_OIDC_CLIENT_ID=${NEXT_PUBLIC_OIDC_CLIENT_ID} \
    NEXT_PUBLIC_OIDC_SCOPE=${NEXT_PUBLIC_OIDC_SCOPE}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:${NODE_VERSION}-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
RUN addgroup -S sparta && adduser -S sparta -G sparta
# The standalone output contains server.js and only the node_modules it needs; static files and public/ are copied beside it.
COPY --from=build --chown=sparta:sparta /app/.next/standalone ./
COPY --from=build --chown=sparta:sparta /app/.next/static ./.next/static
COPY --from=build --chown=sparta:sparta /app/public ./public
# Next copies its optional image-optimizer binaries (sharp/libvips, LGPL) even though images.unoptimized is on and there is no <Image>.
RUN rm -rf ./node_modules/sharp ./node_modules/@img
# The runtime never needs npm or corepack (CMD is `node server.js`): removing them drops the npm CLI's own bundled dependencies
# (brace-expansion, ip-address, pacote, picomatch, sigstore ...) and their CVEs from the image.
RUN rm -rf /usr/local/lib/node_modules/npm /usr/local/lib/node_modules/corepack /usr/local/bin/npm /usr/local/bin/npx /usr/local/bin/corepack
USER sparta
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:'+(process.env.PORT||3000)+'/').then((r)=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"
CMD ["node", "server.js"]
