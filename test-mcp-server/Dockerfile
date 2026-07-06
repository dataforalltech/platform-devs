FROM python:3.11-slim
WORKDIR /app
COPY test-mcp-server/pyproject.toml .
COPY test-mcp-server/src/ ./src/
COPY shared/ ./shared/
RUN pip install --no-cache-dir .
ENV PYTHONPATH=/app:$PYTHONPATH
EXPOSE 7117
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:'+__import__('os').getenv('MCP_PORT','7117')+'/v1/health',timeout=4).status==200 else 1)"
CMD ["test-mcp-server"]
