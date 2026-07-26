FROM python:3.11-slim

WORKDIR /app

# Install shared library first (cache-friendly layering)
COPY services/shared /opt/webuild-shared
RUN pip install --no-cache-dir /opt/webuild-shared

# Install hub dependencies
COPY services/hub/pyproject.toml ./pyproject.toml
COPY services/hub/src ./src
RUN pip install --no-cache-dir .

EXPOSE 8003

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8003"]
