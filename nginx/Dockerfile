FROM nginx:1.27.5-alpine
COPY nginx.conf /etc/nginx/nginx.conf
# certs/ is bind-mounted at runtime from ./nginx/certs/ — see docker-compose.yml
EXPOSE 80 443
CMD ["nginx", "-g", "daemon off;"]
