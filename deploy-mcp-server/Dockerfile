FROM python:3.11-slim
WORKDIR /app
COPY deploy-mcp-server/pyproject.toml .
COPY deploy-mcp-server/src/ ./src/
COPY shared/ ./shared/
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app:$PYTHONPATH
EXPOSE 7110
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:7110/v1/health || exit 1
CMD ["deploy-mcp-server"]
