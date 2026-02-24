import psycopg2
import os
from pathlib import Path

# Load .env file if present (so this script works standalone on the host)
env_path = Path(__file__).resolve().parent / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            key, val = key.strip(), val.strip().strip('"').strip("'")
            os.environ.setdefault(key, val)

try:
    c = psycopg2.connect(
        host=os.getenv('PF9_DB_HOST', 'localhost'),
        port=int(os.getenv('PF9_DB_PORT', '5432')),
        dbname=os.getenv('PF9_DB_NAME', 'pf9_mgmt'),
        user=os.getenv('PF9_DB_USER', 'pf9'),
        password=os.getenv('PF9_DB_PASSWORD', os.getenv('POSTGRES_PASSWORD', ''))
    )
    cur = c.cursor()
    cur.execute("SELECT COUNT(*) FROM networks WHERE status IS NOT NULL")
    print(f"NET_STATUS_COUNT={cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM ports WHERE status IS NOT NULL")
    print(f"PORT_STATUS_COUNT={cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM subnets WHERE enable_dhcp IS NOT NULL")
    print(f"SUBNET_DHCP_COUNT={cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM volumes WHERE server_id IS NOT NULL")
    print(f"VOL_SERVER_COUNT={cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM drift_rules")
    print(f"DRIFT_RULES={cur.fetchone()[0]}")
    cur.execute("SELECT COUNT(*) FROM drift_events")
    print(f"DRIFT_EVENTS={cur.fetchone()[0]}")
    c.close()
except Exception as e:
    print(f"ERROR: {e}")
