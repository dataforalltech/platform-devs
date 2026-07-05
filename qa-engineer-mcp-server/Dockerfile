FROM python:3.11-slim
WORKDIR /app
COPY qa-engineer-mcp-server/pyproject.toml .
COPY qa-engineer-mcp-server/src/ ./src/
COPY shared/ ./shared/
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app:$PYTHONPATH
EXPOSE 7100
CMD ["qa-engineer-mcp-server"]
