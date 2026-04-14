FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    libssl-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY tenant_portal/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tenant_portal/ ./
COPY p9_common.py ./

RUN mkdir -p /app/logs
RUN chown -R 1000:1000 /app
USER 1000

CMD ["gunicorn", "main:app", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8010", "--timeout", "120", "--graceful-timeout", "30", "--max-requests", "1000", "--max-requests-jitter", "100"]
