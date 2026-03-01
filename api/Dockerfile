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

# Copy API sources and shared p9_common module into the image
COPY api/ ./
COPY p9_common.py ./

# Run FastAPI via gunicorn with 2 uvicorn workers for concurrency
CMD ["gunicorn", "main:app", "-w", "2", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "--timeout", "300", "--graceful-timeout", "60"]

