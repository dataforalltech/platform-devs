FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.104.1 uvicorn[standard]==0.24.0 pydantic==2.4.2
COPY config_mcp.py .
EXPOSE 7100
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:7100/health')" || exit 1
CMD ["python3", "-m", "uvicorn", "config_mcp:app", "--host", "0.0.0.0", "--port", "7100"]
