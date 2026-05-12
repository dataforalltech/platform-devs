FROM python:3.11-slim
WORKDIR /app
COPY mcp-gateway/pyproject.toml .
COPY mcp-gateway/src/ ./src/
RUN pip install --no-cache-dir .
EXPOSE 8080
CMD ["mcp-gateway"]
