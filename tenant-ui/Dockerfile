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

# Configure nginx for non-root (uid 101 / nginx user) operation:
#   - Remove 'user nginx;' directive: master is already uid 101, cannot setuid
#   - Redirect PID file from root-owned /var/run to /tmp
#   - Redirect all cache/temp dirs from root-owned /var/cache/nginx to /tmp
#   - Pre-create temp dirs and hand ownership to nginx (uid 101)
RUN sed -i \
        -e '/^user /d' \
        -e 's|/var/run/nginx.pid|/tmp/nginx.pid|' \
        -e 's|/var/cache/nginx|/tmp/nginx-cache|g' \
        /etc/nginx/nginx.conf \
    && mkdir -p \
        /tmp/nginx-cache/client_temp \
        /tmp/nginx-cache/fastcgi_temp \
        /tmp/nginx-cache/proxy_temp \
        /tmp/nginx-cache/scgi_temp \
        /tmp/nginx-cache/uwsgi_temp \
    && chown -R nginx:nginx /tmp/nginx-cache \
    && rm /etc/nginx/conf.d/default.conf

# Simple SPA serving config — nginx just serves static files and
# falls back to /index.html for client-side routing
COPY nginx.conf /etc/nginx/conf.d/tenant-ui.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
