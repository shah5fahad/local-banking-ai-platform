FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install common
COPY common/ /common/
RUN pip install --no-cache-dir /common/

# Install ai_service
COPY ai_service/pyproject.toml ai_service/
RUN pip install --no-cache-dir ai_service/
COPY ai_service/ ai_service/

WORKDIR /app/ai_service

CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8002"]

EXPOSE 8002
