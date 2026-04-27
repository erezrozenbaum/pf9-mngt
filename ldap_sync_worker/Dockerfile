FROM python:3.11.12-slim

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libldap2-dev libsasl2-dev libssl-dev gcc \
        ldap-utils && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py .

CMD ["python", "-u", "main.py"]
