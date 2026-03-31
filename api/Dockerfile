FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for python-ldap and postgresql-client (psql)
RUN apt-get update && apt-get install -y \
    gcc \
    libldap2-dev \
    libsasl2-dev \
    libssl-dev \
    build-essential \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy API sources, shared module, DB migration scripts, and docs into the image
COPY api/ ./
COPY p9_common.py ./
COPY run_migration.py ./
COPY db/ ./db/
COPY docs/ ./docs/

# Ensure runtime-writable directories exist before ownership transfer.
# Named volumes (app_logs → /app/logs) are initialised from the image layer;
# if the directory is absent the volume is created root-owned and UID 1000
# cannot write to it (logging.FileHandler fails → container never healthy).
RUN mkdir -p /app/logs /app/static

# Transfer ownership to UID 1000 so the pod (runAsUser: 1000) can write /app/static and other runtime dirs.
RUN chown -R 1000:1000 /app
USER 1000

# C7: 4 workers; max-requests restarts workers after 1000 requests to prevent memory leaks
CMD ["gunicorn", "main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "300", "--graceful-timeout", "60", "--max-requests", "1000", "--max-requests-jitter", "100"]

