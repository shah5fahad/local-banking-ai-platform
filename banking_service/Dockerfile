FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy and install common package first (layer caching)
COPY common/ /common/
RUN pip install --no-cache-dir /common/

# Copy and install banking_service
COPY banking_service/pyproject.toml banking_service/
RUN pip install --no-cache-dir banking_service/
COPY banking_service/ banking_service/

WORKDIR /app/banking_service

# Run database migrations and seed then start the server
CMD ["sh", "-c", "alembic upgrade head && python -m app.seed && uvicorn app.main:app --host 0.0.0.0 --port 8001"]

EXPOSE 8001
