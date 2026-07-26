FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy shared library first for layer caching
COPY services/shared /app/services/shared

# Copy relay service
COPY services/relay /app/services/relay

# Install shared library then relay service
RUN pip install --no-cache-dir /app/services/shared
RUN pip install --no-cache-dir /app/services/relay

WORKDIR /app/services/relay

EXPOSE 8002

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8002"]
