# ── Build stage ───────────────────────────────────────────────────────────────
FROM node:20-alpine AS build

WORKDIR /app
COPY package*.json ./
RUN npm ci

COPY . .
# VITE_MAPBOX_TOKEN and VITE_GATEWAY_URL are build-time args
ARG VITE_MAPBOX_TOKEN
ARG VITE_GATEWAY_URL=http://localhost:8080
ENV VITE_MAPBOX_TOKEN=$VITE_MAPBOX_TOKEN
ENV VITE_GATEWAY_URL=$VITE_GATEWAY_URL
RUN npm run build

# ── Runtime stage — nginx serves the static bundle ───────────────────────────
FROM nginx:alpine

COPY --from=build /app/dist /usr/share/nginx/html

# Rewrite all routes to index.html for React Router
RUN printf 'server {\n\
  listen 80;\n\
  root /usr/share/nginx/html;\n\
  index index.html;\n\
  location / { try_files $uri $uri/ /index.html; }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 80
