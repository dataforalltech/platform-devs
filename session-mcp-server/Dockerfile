FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi==0.104.1 uvicorn[standard]==0.24.0 pydantic==2.4.2
COPY session_mcp.py .
EXPOSE 7102
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:7102/health')" || exit 1
CMD ["python3", "-m", "uvicorn", "session_mcp:app", "--host", "0.0.0.0", "--port", "7102"]
