FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for python-ldap and other packages
RUN apt-get update && apt-get install -y \
    gcc \
    libldap2-dev \
    libsasl2-dev \
    libssl-dev \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY api/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy API sources, shared module, and DB migration scripts into the image
COPY api/ ./
COPY p9_common.py ./
COPY db/ ./db/

# C7: 4 workers; max-requests restarts workers after 1000 requests to prevent memory leaks
CMD ["gunicorn", "main:app", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "300", "--graceful-timeout", "60", "--max-requests", "1000", "--max-requests-jitter", "100"]

