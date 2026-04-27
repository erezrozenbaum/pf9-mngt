FROM python:3.11.12-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install additional packages for host collection
RUN pip install --no-cache-dir aiohttp aiofiles

# Copy monitoring service files  
COPY main.py prometheus_client.py models.py entrypoint.sh container_watchdog.py ./
RUN chmod +x entrypoint.sh

# Run monitoring service
ENTRYPOINT ["./entrypoint.sh"]