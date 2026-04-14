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
# Remove default nginx config
RUN rm /etc/nginx/conf.d/default.conf

# Simple SPA serving config — nginx just serves static files and
# falls back to /index.html for client-side routing
COPY nginx.conf /etc/nginx/conf.d/tenant-ui.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
