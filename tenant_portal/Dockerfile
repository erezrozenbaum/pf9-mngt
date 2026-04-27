FROM python:3.11.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libssl-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY tenant_portal/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --chown=1000:1000 tenant_portal/ ./
COPY --chown=1000:1000 p9_common.py ./

# Create writable log dir owned by app user (chown only this dir — not all of /app,
# which would recursively chown thousands of pip package files under QEMU ARM64).
RUN mkdir -p /app/logs && chown 1000:1000 /app/logs
USER 1000

CMD ["gunicorn", "main:app", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8010", "--timeout", "120", "--graceful-timeout", "30", "--max-requests", "1000", "--max-requests-jitter", "100"]
