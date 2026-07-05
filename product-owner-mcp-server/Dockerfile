FROM python:3.11-slim
WORKDIR /app
COPY product-owner-mcp-server/pyproject.toml .
COPY product-owner-mcp-server/src/ ./src/
COPY shared/ ./shared/
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app:$PYTHONPATH
EXPOSE 7100
CMD ["product-owner-mcp-server"]
