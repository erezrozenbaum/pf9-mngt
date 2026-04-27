FROM python:3.11.12-slim

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
COPY --chown=1000:1000 api/ ./
COPY --chown=1000:1000 p9_common.py ./
COPY --chown=1000:1000 run_migration.py ./
COPY --chown=1000:1000 db/ ./db/
COPY --chown=1000:1000 docs/ ./docs/

# Ensure runtime-writable directories exist; owned by app user (chown only these
# dirs — not all of /app, which would recursively chown thousands of pip package
# files and is extremely slow under QEMU ARM64 emulation on GitHub Actions).
RUN mkdir -p /app/logs /app/static && chown 1000:1000 /app/logs /app/static
USER 1000

# C7: 4 workers; max-requests restarts workers after 1000 requests to prevent memory leaks
CMD ["gunicorn", "main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "300", "--graceful-timeout", "60", "--max-requests", "1000", "--max-requests-jitter", "100"]

