FROM python:3.11-slim
WORKDIR /app
COPY dev-twin-mcp-server/pyproject.toml .
COPY dev-twin-mcp-server/src/ ./src/
COPY shared/ ./shared/
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app:$PYTHONPATH
EXPOSE 7101
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:7101/v1/health || exit 1
CMD ["dev-twin-mcp-server"]
