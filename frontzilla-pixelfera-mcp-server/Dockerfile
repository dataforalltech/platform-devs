FROM node:20-alpine AS build-stage

WORKDIR /build

# Build shared lib
WORKDIR /build/shared
COPY shared/package*.json ./
RUN npm ci
COPY shared/src ./src
COPY shared/tsconfig.json ./
RUN npm run build

# Build zilla app
WORKDIR /build/app
COPY frontzilla-pixelfera-mcp-server/package*.json ./
RUN npm ci

COPY frontzilla-pixelfera-mcp-server/dist ./dist

# Create the package structure as if shared is a proper dependency
RUN mkdir -p node_modules/@platform/mcp-client && \
    cp -r /build/shared/dist/* node_modules/@platform/mcp-client/ && \
    cp -r /build/shared/node_modules/* node_modules/ 2>/dev/null || true

# Final stage
FROM node:20-alpine

WORKDIR /app

# Copy everything from build
COPY --from=build-stage /build/app/node_modules ./node_modules
COPY --from=build-stage /build/app/dist ./dist
COPY --from=build-stage /build/app/package.json ./

EXPOSE 7100

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD node -e "require('http').get('http://localhost:7100/health', (r) => {if (r.statusCode !== 200) throw new Error(r.statusCode)})"

CMD ["node", "dist/server.js"]
