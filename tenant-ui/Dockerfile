# ---------- build stage ----------
FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json* ./
# Use ci if lockfile exists, otherwise install (generates lockfile on first build)
RUN if [ -f package-lock.json ]; then npm ci; else npm install; fi

COPY . .
RUN npm run build

# ---------- production stage ----------
FROM nginx:1.27-alpine AS prod

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
# falls back to /index.html for client-side routing
COPY nginx.conf /etc/nginx/conf.d/tenant-ui.conf
COPY --from=build /app/dist /usr/share/nginx/html

USER nginx
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
