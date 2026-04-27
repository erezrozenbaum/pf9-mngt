FROM postgres:16.8-alpine

WORKDIR /app

# Install Python + pip + LDAP client tools (Alpine package manager)
RUN apk add --no-cache python3 py3-pip openldap-clients && \
    python3 -m venv /app/venv

COPY requirements.txt .
RUN /app/venv/bin/pip install --no-cache-dir -r requirements.txt

COPY main.py .

ENV PATH="/app/venv/bin:$PATH"

# Run the Python scheduler (which calls pg_dump / pg_restore)
CMD ["python3", "main.py"]
