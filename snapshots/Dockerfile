FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1

COPY snapshots/requirements.txt /app/snapshots/requirements.txt
RUN pip install --no-cache-dir -r /app/snapshots/requirements.txt

COPY . /app

CMD ["python", "snapshots/snapshot_scheduler.py"]
