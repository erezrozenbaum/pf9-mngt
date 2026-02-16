FROM postgres:16

# Install Python + pip inside the postgres image
RUN apt-get update && \
    apt-get install -y --no-install-recommends python3 python3-pip python3-venv && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN python3 -m venv /app/venv && \
    /app/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENV PATH="/app/venv/bin:$PATH"

# Run the Python scheduler (which calls pg_dump / pg_restore)
CMD ["python3", "main.py"]
