import psycopg2
import json

conn = psycopg2.connect(
    host='localhost',
    port=5432,
    dbname='pf9_mgmt',
    user='pf9',
    password='pf9_password_change_me'
)
cur = conn.cursor()
cur.execute("SELECT volume_id, policies::text, retention_map::text FROM snapshot_assignments LIMIT 5")
rows = cur.fetchall()
for row in rows:
    print(row)
cur.close()
conn.close()
