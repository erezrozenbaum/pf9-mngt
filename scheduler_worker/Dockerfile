FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY scheduler_worker/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy the scheduler entrypoint
COPY scheduler_worker/main.py ./

# Copy root-level scripts that this worker executes
COPY pf9_rvtools.py p9_common.py db_writer.py host_metrics_collector.py ./

CMD ["python", "main.py"]
