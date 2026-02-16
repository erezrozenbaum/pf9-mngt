"""
Database Writer Module for PF9 RVTools Integration
Handles all database operations for storing inventory data
"""

import os
import json
import hashlib
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import psycopg2
from psycopg2.extras import execute_values, RealDictCursor


# Database configuration from environment
DB_HOST = os.getenv("PF9_DB_HOST", "localhost")
DB_PORT = int(os.getenv("PF9_DB_PORT", "5432"))
DB_NAME = os.getenv("PF9_DB_NAME", os.getenv("POSTGRES_DB", "pf9_mgmt"))
DB_USER = os.getenv("PF9_DB_USER", os.getenv("POSTGRES_USER", "pf9"))
DB_PASSWORD = os.getenv("PF9_DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", ""))


def db_connect():
    """Create and return a database connection"""
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
    )


def start_inventory_run(conn, source: str = "pf9_rvtools") -> int:
    """Start a new inventory run and return its ID"""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO inventory_runs (source, status, started_at)
            VALUES (%s, 'running', NOW())
            RETURNING id
        """, (source,))
        run_id = cur.fetchone()[0]
        conn.commit()
        return run_id


def finish_inventory_run(conn, run_id: int, status: str = "success", notes: Optional[str] = None):
    """Mark an inventory run as finished"""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE inventory_runs
            SET finished_at = NOW(),
                status = %s,
                notes = %s,
                duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at))::INTEGER
            WHERE id = %s
        """, (status, notes, run_id))
        conn.commit()


def _compute_change_hash(record: Dict[str, Any], exclude_fields: List[str] = None) -> str:
    """Compute a hash of the record for change detection"""
    exclude = exclude_fields or ['last_seen_at', 'created_at', 'updated_at']
    filtered = {k: v for k, v in record.items() if k not in exclude}
    content = json.dumps(filtered, sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()


def _load_drift_rules(cur, resource_type: str) -> List[Dict[str, Any]]:
    """Load enabled drift rules for a given resource type (cached per connection)."""
    try:
        cur.execute(
            "SELECT id, field_name, severity, description FROM drift_rules "
            "WHERE resource_type = %s AND enabled = TRUE",
            (resource_type,),
        )
        return [dict(r) for r in cur.fetchall()]
    except Exception:
        return []


def _detect_drift(cur, table_name: str, record_id: str, old_row: Dict[str, Any],
                   new_record: Dict[str, Any], rules: List[Dict[str, Any]]):
    """Compare old vs new fields and insert drift_events for any matching rules."""
    if not rules or not old_row:
        return
    for rule in rules:
        field = rule["field_name"]
        old_val = str(old_row.get(field, "")) if old_row.get(field) is not None else None
        new_val = str(new_record.get(field, "")) if new_record.get(field) is not None else None
        if old_val == new_val:
            continue
        # Field changed — emit drift event
        try:
            cur.execute("""
                INSERT INTO drift_events
                    (rule_id, resource_type, resource_id, resource_name,
                     project_id, project_name, domain_id, domain_name,
                     severity, field_changed, old_value, new_value, description)
                VALUES (%s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s)
            """, (
                rule["id"],
                table_name,
                record_id,
                new_record.get("name") or new_record.get("hostname") or str(record_id),
                new_record.get("project_id") or old_row.get("project_id"),
                new_record.get("project_name") or old_row.get("project_name"),
                new_record.get("domain_id") or old_row.get("domain_id"),
                new_record.get("domain_name") or old_row.get("domain_name"),
                rule["severity"],
                field,
                old_val,
                new_val,
                rule["description"],
            ))
        except Exception as drift_err:
            # Non-fatal — log but don't break inventory sync
            import logging
            logging.getLogger("db_writer").warning(
                "Drift event insert failed for %s/%s field %s: %s",
                table_name, record_id, field, drift_err,
            )


def _upsert_with_history(
    conn,
    table_name: str,
    records: List[Dict[str, Any]],
    id_field: str = "id",
    run_id: Optional[int] = None
) -> int:
    """
    Generic upsert function with history tracking and drift detection.
    Updates the main table, inserts into history table if changed,
    and emits drift events for field-level changes matching enabled rules.
    """
    if not records:
        return 0

    # Get the column names from the first record
    columns = list(records[0].keys())
    
    # Build upsert query
    placeholders = ", ".join(["%s"] * len(columns))
    update_set = ", ".join([f"{col} = EXCLUDED.{col}" for col in columns if col != id_field])
    
    insert_query = f"""
        INSERT INTO {table_name} ({", ".join(columns)})
        VALUES %s
        ON CONFLICT ({id_field}) DO UPDATE SET
            {update_set},
            last_seen_at = NOW()
    """
    
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        # ---- Load drift rules for this resource type ----
        drift_rules = _load_drift_rules(cur, table_name)

        # ---- Snapshot old rows BEFORE the upsert (for drift detection) ----
        old_rows: Dict[str, Dict] = {}
        if drift_rules:
            record_ids = [r[id_field] for r in records if r.get(id_field)]
            if record_ids:
                cur.execute(
                    f"SELECT * FROM {table_name} WHERE {id_field} = ANY(%s)",
                    (record_ids,),
                )
                for row in cur.fetchall():
                    old_rows[str(row[id_field])] = dict(row)

        # ---- Perform the upsert ----
        values = [[record.get(col) for col in columns] for record in records]
        execute_values(cur, insert_query, values)
        
        # ---- History tracking + drift detection ----
        history_table = f"{table_name}_history"
        try:
            for record in records:
                change_hash = _compute_change_hash(record)
                
                # Check if this exact record already exists in history
                cur.execute(f"""
                    SELECT 1 FROM {history_table}
                    WHERE {id_field.replace('id', table_name[:-1] + '_id')} = %s
                    AND change_hash = %s
                    LIMIT 1
                """, (record[id_field], change_hash))
                
                if not cur.fetchone():
                    # Record has changed, insert into history
                    history_cols = [col for col in columns if col != 'last_seen_at']
                    history_cols.append('change_hash')
                    history_cols.append('recorded_at')
                    
                    # Map id to {table}_id for history table
                    history_values = {col: record.get(col) for col in history_cols if col not in ['change_hash', 'recorded_at']}
                    if id_field in history_values:
                        history_values[f"{table_name[:-1]}_id"] = history_values.pop(id_field)
                    
                    history_values['change_hash'] = change_hash
                    history_values['recorded_at'] = datetime.now(timezone.utc)
                    
                    hist_cols = list(history_values.keys())
                    hist_vals = [history_values[col] for col in hist_cols]
                    
                    cur.execute(f"""
                        INSERT INTO {history_table} ({", ".join(hist_cols)})
                        VALUES ({", ".join(["%s"] * len(hist_vals))})
                    """, hist_vals)

                    # ---- Drift detection ----
                    rid = str(record[id_field])
                    old_row = old_rows.get(rid)
                    if old_row and drift_rules:
                        _detect_drift(cur, table_name, rid, old_row, record, drift_rules)

        except psycopg2.errors.UndefinedTable:
            # History table doesn't exist, skip
            pass
    
    return len(records)


def upsert_domains(conn, domains: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Upsert domains into the database"""
    if not domains:
        return 0
    
    records = []
    for d in domains:
        records.append({
            'id': d.get('id'),
            'name': d.get('name'),
            'raw_json': json.dumps(d) if isinstance(d, dict) else d,
        })
    
    return _upsert_with_history(conn, 'domains', records, 'id', run_id)


def upsert_projects(conn, projects: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Upsert projects into the database"""
    if not projects:
        return 0
    
    records = []
    for p in projects:
        records.append({
            'id': p.get('id'),
            'name': p.get('name'),
            'domain_id': p.get('domain_id'),
            'raw_json': json.dumps(p) if isinstance(p, dict) else p,
        })
    
    return _upsert_with_history(conn, 'projects', records, 'id', run_id)


def upsert_hypervisors(conn, hypervisors: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Upsert hypervisors into the database"""
    if not hypervisors:
        return 0
    
    records = []
    for h in hypervisors:
        records.append({
            'id': str(h.get('id')),
            'hostname': h.get('hypervisor_hostname'),
            'hypervisor_type': h.get('hypervisor_type'),
            'vcpus': h.get('vcpus'),
            'memory_mb': h.get('memory_mb'),
            'local_gb': h.get('local_gb'),
            'state': h.get('state'),
            'status': h.get('status'),
            'raw_json': json.dumps(h) if isinstance(h, dict) else h,
        })
    
    return _upsert_with_history(conn, 'hypervisors', records, 'id', run_id)


def upsert_servers(conn, servers: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Upsert servers (instances) into the database"""
    if not servers:
        return 0
    
    # Get valid project IDs for foreign key validation
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM projects")
        valid_project_ids = set(row[0] for row in cur.fetchall())
    
    records = []
    for s in servers:
        created_at = s.get('created')
        if created_at and isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except:
                created_at = None
        
        # Validate foreign key
        project_id = s.get('tenant_id')
        if not project_id or project_id not in valid_project_ids:
            project_id = None
        
        records.append({
            'id': s.get('id'),
            'name': s.get('name'),
            'project_id': project_id,
            'status': s.get('status'),
            'vm_state': s.get('OS-EXT-STS:vm_state'),
            'flavor_id': s.get('flavor', {}).get('id') if isinstance(s.get('flavor'), dict) else s.get('flavor'),
            'hypervisor_hostname': s.get('OS-EXT-SRV-ATTR:hypervisor_hostname'),
            'created_at': created_at,
            'raw_json': json.dumps(s) if isinstance(s, dict) else s,
        })
    
    return _upsert_with_history(conn, 'servers', records, 'id', run_id)


def upsert_volumes(conn, volumes: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Upsert volumes into the database"""
    if not volumes:
        return 0
    
    # Get valid project IDs for foreign key validation
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM projects")
        valid_project_ids = set(row[0] for row in cur.fetchall())
    
    records = []
    for v in volumes:
        created_at = v.get('created_at')
        if created_at and isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except:
                created_at = None
        
        # Validate foreign key
        project_id = v.get('os-vol-tenant-attr:tenant_id') or v.get('tenant_id')
        if not project_id or project_id not in valid_project_ids:
            project_id = None
        
        records.append({
            'id': v.get('id'),
            'name': v.get('name'),
            'project_id': project_id,
            'size_gb': v.get('size'),
            'status': v.get('status'),
            'volume_type': v.get('volume_type'),
            'bootable': v.get('bootable') == 'true' or v.get('bootable') == True,
            'created_at': created_at,
            'raw_json': json.dumps(v) if isinstance(v, dict) else v,
        })
    
    return _upsert_with_history(conn, 'volumes', records, 'id', run_id)


def upsert_networks(conn, networks: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Upsert networks into the database"""
    if not networks:
        return 0
    
    # Get valid project IDs for foreign key validation
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM projects")
        valid_project_ids = set(row[0] for row in cur.fetchall())
    
    records = []
    for n in networks:
        # Validate foreign key
        project_id = n.get('tenant_id') or n.get('project_id')
        if not project_id or project_id not in valid_project_ids:
            project_id = None
        
        records.append({
            'id': n.get('id'),
            'name': n.get('name'),
            'project_id': project_id,
            'is_shared': n.get('shared', False),
            'is_external': n.get('router:external', False),
            'raw_json': json.dumps(n) if isinstance(n, dict) else n,
        })
    
    return _upsert_with_history(conn, 'networks', records, 'id', run_id)


def upsert_subnets(conn, subnets: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Upsert subnets into the database"""
    if not subnets:
        return 0
    
    records = []
    for s in subnets:
        records.append({
            'id': s.get('id'),
            'name': s.get('name'),
            'network_id': s.get('network_id'),
            'cidr': s.get('cidr'),
            'gateway_ip': s.get('gateway_ip'),
            'raw_json': json.dumps(s) if isinstance(s, dict) else s,
        })
    
    return _upsert_with_history(conn, 'subnets', records, 'id', run_id)


def upsert_ports(conn, ports: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Upsert ports into the database"""
    if not ports:
        return 0
    
    # Get valid IDs for foreign key validation
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM projects")
        valid_project_ids = set(row[0] for row in cur.fetchall())
        cur.execute("SELECT id FROM networks")
        valid_network_ids = set(row[0] for row in cur.fetchall())
    
    records = []
    for p in ports:
        # Validate foreign keys - handle None and empty strings
        project_id = p.get('tenant_id') or p.get('project_id')
        if not project_id or project_id not in valid_project_ids:
            project_id = None
        
        network_id = p.get('network_id')
        if not network_id or network_id not in valid_network_ids:
            network_id = None
        
        records.append({
            'id': p.get('id'),
            'name': p.get('name'),
            'network_id': network_id,
            'project_id': project_id,
            'device_id': p.get('device_id'),
            'device_owner': p.get('device_owner'),
            'mac_address': p.get('mac_address'),
            'ip_addresses': json.dumps(p.get('fixed_ips', [])),
            'raw_json': json.dumps(p) if isinstance(p, dict) else p,
        })
    
    return _upsert_with_history(conn, 'ports', records, 'id', run_id)


def upsert_routers(conn, routers: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Upsert routers into the database"""
    if not routers:
        return 0
    
    # Get valid project IDs for foreign key validation
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM projects")
        valid_project_ids = set(row[0] for row in cur.fetchall())
    
    records = []
    for r in routers:
        ext_gw = r.get('external_gateway_info', {})
        ext_net_id = ext_gw.get('network_id') if isinstance(ext_gw, dict) else None
        
        # Validate foreign key
        project_id = r.get('tenant_id') or r.get('project_id')
        if not project_id or project_id not in valid_project_ids:
            project_id = None
        
        records.append({
            'id': r.get('id'),
            'name': r.get('name'),
            'project_id': project_id,
            'external_net_id': ext_net_id,
            'raw_json': json.dumps(r) if isinstance(r, dict) else r,
        })
    
    return _upsert_with_history(conn, 'routers', records, 'id', run_id)


def upsert_floating_ips(conn, floating_ips: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Upsert floating IPs into the database"""
    if not floating_ips:
        return 0
    
    # Get valid IDs for foreign key validation
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM projects")
        valid_project_ids = set(row[0] for row in cur.fetchall())
        cur.execute("SELECT id FROM ports")
        valid_port_ids = set(row[0] for row in cur.fetchall())
        cur.execute("SELECT id FROM routers")
        valid_router_ids = set(row[0] for row in cur.fetchall())
    
    records = []
    for f in floating_ips:
        # Validate foreign keys
        project_id = f.get('tenant_id') or f.get('project_id')
        if not project_id or project_id not in valid_project_ids:
            project_id = None
        
        port_id = f.get('port_id')
        if not port_id or port_id not in valid_port_ids:
            port_id = None
        
        router_id = f.get('router_id')
        if not router_id or router_id not in valid_router_ids:
            router_id = None
        
        records.append({
            'id': f.get('id'),
            'floating_ip': f.get('floating_ip_address'),
            'fixed_ip': f.get('fixed_ip_address'),
            'port_id': port_id,
            'project_id': project_id,
            'router_id': router_id,
            'status': f.get('status'),
            'raw_json': json.dumps(f) if isinstance(f, dict) else f,
        })
    
    return _upsert_with_history(conn, 'floating_ips', records, 'id', run_id)


def upsert_flavors(conn, flavors: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Upsert flavors into the database"""
    if not flavors:
        return 0
    
    def safe_int(value, default=0):
        """Convert value to int, handling None and empty strings"""
        if value is None or value == '':
            return default
        try:
            return int(value)
        except (ValueError, TypeError):
            return default
    
    records = []
    for f in flavors:
        records.append({
            'id': f.get('id'),
            'name': f.get('name'),
            'vcpus': safe_int(f.get('vcpus')),
            'ram_mb': safe_int(f.get('ram')),
            'disk_gb': safe_int(f.get('disk')),
            'ephemeral_gb': safe_int(f.get('OS-FLV-EXT-DATA:ephemeral'), 0),
            'swap_mb': safe_int(f.get('swap'), 0),
            'is_public': f.get('os-flavor-access:is_public', True),
            'raw_json': json.dumps(f) if isinstance(f, dict) else f,
        })
    
    return _upsert_with_history(conn, 'flavors', records, 'id', run_id)


def upsert_images(conn, images: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Upsert images into the database"""
    if not images:
        return 0
    
    records = []
    for i in images:
        created_at = i.get('created_at')
        updated_at = i.get('updated_at')
        
        if created_at and isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except:
                created_at = None
        
        if updated_at and isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            except:
                updated_at = None
        
        records.append({
            'id': i.get('id'),
            'name': i.get('name'),
            'status': i.get('status'),
            'visibility': i.get('visibility'),
            'protected': i.get('protected', False),
            'size_bytes': i.get('size'),
            'disk_format': i.get('disk_format'),
            'container_format': i.get('container_format'),
            'checksum': i.get('checksum'),
            'created_at': created_at,
            'updated_at': updated_at,
            'raw_json': json.dumps(i) if isinstance(i, dict) else i,
        })
    
    return _upsert_with_history(conn, 'images', records, 'id', run_id)


def upsert_snapshots(conn, snapshots: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Upsert snapshots into the database"""
    if not snapshots:
        return 0
    
    records = []
    for s in snapshots:
        created_at = s.get('created_at')
        updated_at = s.get('updated_at')
        
        if created_at and isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except:
                created_at = None
        
        if updated_at and isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            except:
                updated_at = None
        
        records.append({
            'id': s.get('id'),
            'name': s.get('name'),
            'description': s.get('description'),
            'project_id': s.get('tenant_id') or s.get('project_id'),
            'project_name': s.get('project_name'),
            'tenant_name': s.get('tenant_name'),
            'domain_name': s.get('domain_name'),
            'domain_id': s.get('domain_id'),
            'volume_id': s.get('volume_id'),
            'size_gb': s.get('size'),
            'status': s.get('status'),
            'created_at': created_at,
            'updated_at': updated_at,
            'raw_json': json.dumps(s) if isinstance(s, dict) else s,
        })
    
    return _upsert_with_history(conn, 'snapshots', records, 'id', run_id)


def write_users(conn, users: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Write users to the database"""
    if not users:
        return 0
    
    # Get existing domain IDs and project IDs to validate foreign keys
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM domains")
        valid_domain_ids = set(row[0] for row in cur.fetchall())
        
        cur.execute("SELECT id FROM projects")
        valid_project_ids = set(row[0] for row in cur.fetchall())
    
    records = []
    for u in users:
        created_at = u.get('created_at')
        password_expires_at = u.get('password_expires_at')
        
        if created_at and isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except:
                created_at = None
        
        if password_expires_at and isinstance(password_expires_at, str):
            try:
                password_expires_at = datetime.fromisoformat(password_expires_at.replace('Z', '+00:00'))
            except:
                password_expires_at = None
        
        # Validate foreign keys - set to NULL if not found
        domain_id = u.get('domain_id')
        if not domain_id or domain_id not in valid_domain_ids:
            domain_id = None
        
        default_project_id = u.get('default_project_id')
        if not default_project_id or default_project_id not in valid_project_ids:
            default_project_id = None
        
        records.append({
            'id': u.get('id'),
            'name': u.get('name'),
            'email': u.get('email'),
            'enabled': u.get('enabled', True),
            'domain_id': domain_id,
            'description': u.get('description'),
            'default_project_id': default_project_id,
            'password_expires_at': password_expires_at,
            'created_at': created_at,
            'raw_json': json.dumps(u) if isinstance(u, dict) else u,
        })
    
    return _upsert_with_history(conn, 'users', records, 'id', run_id)


def write_roles(conn, roles: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Write roles to the database"""
    if not roles:
        return 0
    
    # Get existing domain IDs to validate foreign keys
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM domains")
        valid_domain_ids = set(row[0] for row in cur.fetchall())
    
    records = []
    for r in roles:
        # Validate foreign keys - set to NULL if not found
        domain_id = r.get('domain_id')
        if not domain_id or domain_id not in valid_domain_ids:
            domain_id = None
        
        records.append({
            'id': r.get('id'),
            'name': r.get('name'),
            'description': r.get('description'),
            'domain_id': domain_id,
            'raw_json': json.dumps(r) if isinstance(r, dict) else r,
        })
    
    return _upsert_with_history(conn, 'roles', records, 'id', run_id)


def write_role_assignments(conn, role_assignments: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Write role assignments to the database"""
    if not role_assignments:
        return 0
    
    # Role assignments don't have a simple unique ID, so we handle them differently
    with conn.cursor() as cur:
        # Get valid IDs for foreign key validation
        cur.execute("SELECT id FROM roles")
        valid_role_ids = set(row[0] for row in cur.fetchall())
        
        cur.execute("SELECT id FROM users")
        valid_user_ids = set(row[0] for row in cur.fetchall())
        
        cur.execute("SELECT id FROM projects")
        valid_project_ids = set(row[0] for row in cur.fetchall())
        
        cur.execute("SELECT id FROM domains")
        valid_domain_ids = set(row[0] for row in cur.fetchall())
        
        # First, delete all existing role assignments to ensure clean state
        cur.execute("DELETE FROM role_assignments")
        
        # Now insert all current role assignments using savepoints
        inserted = 0
        for idx, ra in enumerate(role_assignments):
            scope = ra.get('scope', {})
            role = ra.get('role', {})
            user = ra.get('user', {})
            group = ra.get('group', {})
            
            role_id = role.get('id')
            user_id = user.get('id')
            project_id = scope.get('project', {}).get('id') if 'project' in scope else None
            domain_id = scope.get('domain', {}).get('id') if 'domain' in scope else None
            
            # Skip if required foreign keys don't exist
            if not role_id or role_id not in valid_role_ids:
                continue
            if user_id and user_id not in valid_user_ids:
                continue
            if project_id and project_id not in valid_project_ids:
                project_id = None  # Set to None instead of skipping
            if domain_id and domain_id not in valid_domain_ids:
                domain_id = None  # Set to None instead of skipping
            
            # Skip if BOTH project_id and domain_id are None (violates scope check)
            if project_id is None and domain_id is None:
                continue
            
            # Use savepoint for each insert to allow rollback on error without aborting entire transaction
            try:
                savepoint_name = f"sp_{idx}"
                cur.execute(f"SAVEPOINT {savepoint_name}")
                
                cur.execute("""
                    INSERT INTO role_assignments (
                        role_id, user_id, group_id, project_id, domain_id,
                        inherited, user_name, role_name, project_name, domain_name, raw_json
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (role_id, user_id, project_id, domain_id, group_id) DO UPDATE SET
                        user_name = EXCLUDED.user_name,
                        role_name = EXCLUDED.role_name,
                        project_name = EXCLUDED.project_name,
                        domain_name = EXCLUDED.domain_name,
                        raw_json = EXCLUDED.raw_json,
                        last_seen_at = NOW()
                """, (
                    role_id,
                    user_id,
                    group.get('id'),
                    project_id,
                    domain_id,
                    ra.get('inherited', False),
                    user.get('name'),
                    role.get('name'),
                    scope.get('project', {}).get('name'),
                    scope.get('domain', {}).get('name'),
                    json.dumps(ra)
                ))
                
                cur.execute(f"RELEASE SAVEPOINT {savepoint_name}")
                inserted += 1
            except Exception as e:
                # Rollback to savepoint to clear the error
                try:
                    cur.execute(f"ROLLBACK TO SAVEPOINT {savepoint_name}")
                except:
                    pass
                # Skip invalid role assignments
                # print(f"Warning: Failed to insert role assignment: {e}")
                continue
    
    return inserted


def write_groups(conn, groups: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Write groups to the database"""
    if not groups:
        return 0
    
    records = []
    for g in groups:
        records.append({
            'id': g.get('id'),
            'name': g.get('name'),
            'domain_id': g.get('domain_id'),
            'description': g.get('description'),
            'raw_json': json.dumps(g) if isinstance(g, dict) else g,
        })
    
    return _upsert_with_history(conn, 'groups', records, 'id', run_id)


def upsert_security_groups(conn, security_groups: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Upsert security groups into the database"""
    if not security_groups:
        return 0

    # Get valid project IDs for foreign key validation
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM projects")
        valid_project_ids = set(row[0] for row in cur.fetchall())

    records = []
    for sg in security_groups:
        created_at = sg.get('created_at')
        updated_at = sg.get('updated_at')

        if created_at and isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except Exception:
                created_at = None

        if updated_at and isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            except Exception:
                updated_at = None

        project_id = sg.get('tenant_id') or sg.get('project_id')
        if not project_id or project_id not in valid_project_ids:
            project_id = None

        records.append({
            'id': sg.get('id'),
            'name': sg.get('name'),
            'description': sg.get('description'),
            'project_id': project_id,
            'project_name': sg.get('project_name'),
            'tenant_name': sg.get('tenant_name'),
            'domain_id': sg.get('domain_id'),
            'domain_name': sg.get('domain_name'),
            'created_at': created_at,
            'updated_at': updated_at,
            'raw_json': json.dumps(sg) if isinstance(sg, dict) else sg,
        })

    return _upsert_with_history(conn, 'security_groups', records, 'id', run_id)


def upsert_security_group_rules(conn, rules: List[Dict[str, Any]], run_id: Optional[int] = None) -> int:
    """Upsert security group rules into the database"""
    if not rules:
        return 0

    # Get valid security group IDs for foreign key validation
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM security_groups")
        valid_sg_ids = set(row[0] for row in cur.fetchall())

    records = []
    for r in rules:
        sg_id = r.get('security_group_id')
        if not sg_id or sg_id not in valid_sg_ids:
            continue  # Skip rules for unknown security groups

        created_at = r.get('created_at')
        updated_at = r.get('updated_at')

        if created_at and isinstance(created_at, str):
            try:
                created_at = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            except Exception:
                created_at = None

        if updated_at and isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at.replace('Z', '+00:00'))
            except Exception:
                updated_at = None

        records.append({
            'id': r.get('id'),
            'security_group_id': sg_id,
            'direction': r.get('direction'),
            'ethertype': r.get('ethertype'),
            'protocol': r.get('protocol'),
            'port_range_min': r.get('port_range_min'),
            'port_range_max': r.get('port_range_max'),
            'remote_ip_prefix': r.get('remote_ip_prefix'),
            'remote_group_id': r.get('remote_group_id'),
            'description': r.get('description'),
            'project_id': r.get('tenant_id') or r.get('project_id'),
            'created_at': created_at,
            'updated_at': updated_at,
            'raw_json': json.dumps(r) if isinstance(r, dict) else r,
        })

    if not records:
        return 0

    return _upsert_with_history(conn, 'security_group_rules', records, 'id', run_id)
