FROM python:3.11-slim AS base

WORKDIR /app

# Install system deps for asyncpg build
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy shared library first (layer caching)
COPY ../shared /tmp/shared
RUN pip install --no-cache-dir /tmp/shared && rm -rf /tmp/shared

# Copy project files
COPY pyproject.toml ./
RUN pip install --no-cache-dir .

COPY src/ ./src/

# Runtime stage
FROM python:3.11-slim AS runtime

WORKDIR /app

COPY --from=base /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=base /usr/local/bin /usr/local/bin
COPY --from=base /app/src ./src

ENV PYTHONUNBUFFERED=1
EXPOSE 8001

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8001"]
