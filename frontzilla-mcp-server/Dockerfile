FROM python:3.11-slim
WORKDIR /app
COPY frontzilla-mcp-server/pyproject.toml .
COPY frontzilla-mcp-server/src/ ./src/
COPY shared/ ./shared/
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app:$PYTHONPATH
EXPOSE 7100
CMD ["frontzilla-mcp-server"]
