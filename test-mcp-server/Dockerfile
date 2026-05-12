FROM python:3.11-slim
WORKDIR /app
COPY test-mcp-server/pyproject.toml .
COPY test-mcp-server/src/ ./src/
COPY shared/ ./shared/
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app:$PYTHONPATH
EXPOSE 7100
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:7100/health || exit 1
CMD ["test-mcp-server"]
