FROM python:3.11-slim
WORKDIR /app
COPY archzilla-mcp-server/pyproject.toml .
COPY archzilla-mcp-server/src/ ./src/
COPY shared/ ./shared/
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app:$PYTHONPATH
EXPOSE 7100
CMD ["archzilla-mcp-server"]
