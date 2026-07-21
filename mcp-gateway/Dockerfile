FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
COPY src/ ./src/
COPY migrations/ ./migrations/
RUN pip install --no-cache-dir .
USER 65532
EXPOSE 8080
CMD ["python", "-m", "src.main"]
