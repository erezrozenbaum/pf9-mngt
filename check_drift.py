import psycopg2
try:
    c = psycopg2.connect(host='localhost', port=5432, dbname='pf9_mgmt', user='pf9', password='pf9_password_change_me')
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
