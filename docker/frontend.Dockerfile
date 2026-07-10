# Frontend image — Next.js production server.
#
# Uses Next's "standalone" output so the runtime image carries only the server
# bundle + the node_modules it actually needs (much smaller on an SD card).
#
# NEXT_PUBLIC_API_URL is baked in at BUILD time (the browser calls it directly),
# so it must be the address your phone/laptop can reach, e.g. http://<pi-ip>:8000

FROM node:20-bookworm-slim AS builder
WORKDIR /app

ENV NEXT_TELEMETRY_DISABLED=1

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./

ARG NEXT_PUBLIC_API_URL=http://localhost:8000
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
RUN npm run build


FROM node:20-bookworm-slim AS runner
WORKDIR /app

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

# Run unprivileged — the base image's `node` user (uid 1000, matches the
# backend services' compose user).
USER node

EXPOSE 3000
CMD ["node", "server.js"]
