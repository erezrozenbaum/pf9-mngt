"""Run migrate_multicluster.sql inside the API container."""
import os
import sys
import psycopg2

conn = psycopg2.connect(
    host=os.environ["PF9_DB_HOST"],
    port=int(os.environ.get("PF9_DB_PORT", 5432)),
    dbname=os.environ["PF9_DB_NAME"],
    user=os.environ["PF9_DB_USER"],
    password=os.environ["PF9_DB_PASSWORD"],
)
conn.autocommit = True
cur = conn.cursor()

sql_path = "/app/run_migration_sql.sql"
with open(sql_path, encoding="utf-8") as f:
    sql = f.read()

stmts = [s.strip() for s in sql.split(";")]
ok = 0
errors = []
for stmt in stmts:
    lines = [l for l in stmt.splitlines() if l.strip() and not l.strip().startswith("--")]
    if not lines:
        continue
    try:
        cur.execute(stmt)
        ok += 1
        print(f"OK: {lines[0][:80]}")
    except Exception as e:
        msg = str(e).strip()
        if "already exists" in msg or "duplicate" in msg.lower():
            ok += 1
            print(f"SKIP (exists): {lines[0][:80]}")
        else:
            errors.append((lines[0][:80], msg[:200]))
            print(f"ERR: {lines[0][:80]}")
            print(f"     {msg[:200]}")

conn.close()
print(f"\nDone — OK: {ok}  Errors: {len(errors)}")
sys.exit(0 if not errors else 1)
