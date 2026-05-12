FROM python:3.11-slim
WORKDIR /app
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir .
EXPOSE 8080
CMD ["python", "-m", "src.main"]
