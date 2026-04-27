# ---------- build stage ----------
FROM node:22.14.0-alpine AS build
WORKDIR /app

COPY package.json package-lock.json* ./
# Use ci if lockfile exists, otherwise install (generates lockfile on first build)
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .
RUN npm run build

# ---------- production stage ----------
FROM nginx:1.27.5-alpine AS prod

# Configure nginx for non-root (uid 101 / nginx user) operation.
#
# The temp directory paths (client_temp, proxy_temp, etc.) are compiled-in
# defaults in the nginx binary — they cannot be overridden by sed on nginx.conf.
# The correct approach is to pre-create those directories during the build and
# chown them to the nginx user (uid 101), keeping them at their expected paths.
#
# Additionally:
#   - Pre-create and own /run/nginx.pid so the master can write its PID
#   - Own /var/log/nginx so worker access logs can be written
#   - Own /etc/nginx/conf.d so entrypoint scripts can mutate it
#   - Add USER nginx so Kubernetes runAsNonRoot admission is satisfied
#     even without an explicit securityContext override
RUN rm /etc/nginx/conf.d/default.conf \
    && mkdir -p \
        /var/cache/nginx/client_temp \
        /var/cache/nginx/fastcgi_temp \
        /var/cache/nginx/proxy_temp \
        /var/cache/nginx/scgi_temp \
        /var/cache/nginx/uwsgi_temp \
    && chown -R nginx:nginx \
        /var/cache/nginx \
        /var/log/nginx \
        /etc/nginx/conf.d \
    && touch /run/nginx.pid \
    && chown nginx:nginx /run/nginx.pid

# Simple SPA serving config — nginx just serves static files and
# falls back to /index.html for client-side routing.
# nginx.conf uses TENANT_PORTAL_UPSTREAM placeholder which is substituted
# at container startup via envsubst so the same image works in both
# Docker Compose (tenant_portal:8010) and Kubernetes (pf9-tenant-portal:8010).
COPY nginx.conf /etc/nginx/templates/tenant-ui.conf.template
COPY --from=build /app/dist /usr/share/nginx/html

USER nginx
EXPOSE 8080
# envsubst replaces TENANT_PORTAL_UPSTREAM then starts nginx.
# Default value is "tenant_portal:8010" (Docker Compose) so no env var
# is needed in docker-compose; Kubernetes deployments set it to
# "pf9-tenant-portal:8010" via the Helm template.
CMD ["/bin/sh", "-c", "TENANT_PORTAL_UPSTREAM=${TENANT_PORTAL_UPSTREAM:-tenant_portal:8010} envsubst '${TENANT_PORTAL_UPSTREAM}' < /etc/nginx/templates/tenant-ui.conf.template > /etc/nginx/conf.d/tenant-ui.conf && nginx -g 'daemon off;'"]
