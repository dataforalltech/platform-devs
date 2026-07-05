# Authorization Server (OAuth 2.1 core) — auth-mcp
# Build a partir da RAIZ do repo (precisa de shared/):
#   docker build -f auth-mcp-server/Dockerfile.as -t auth-mcp-as .
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir \
    "fastapi>=0.104.0" "uvicorn[standard]>=0.24.0" "python-multipart>=0.0.6" \
    "pyjwt>=2.8.0" "cryptography>=42.0.0" "bcrypt>=4.1.0"
COPY shared/ ./shared/
COPY auth-mcp-server/authorization_server.py ./authorization_server.py
COPY auth-mcp-server/oidc_upstream.py ./oidc_upstream.py
ENV PYTHONPATH=/app
EXPOSE 7103
# Produção: injete AS_PRIVATE_KEY_PEM e AS_CLIENTS_JSON via secrets manager.
CMD ["python", "-m", "uvicorn", "authorization_server:app", "--host", "0.0.0.0", "--port", "7103"]
