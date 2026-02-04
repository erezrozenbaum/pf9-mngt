import os
import json
import hashlib
import socket
from datetime import datetime, timezone

import psycopg2
from psycopg2.extras import execute_values, Json


# ----------------------------------------------------------------------
# Connection helpers
# ----------------------------------------------------------------------

def db_connect():
    """
    Connect from Windows host to Postgres container via localhost:5432.
    Uses env vars so we can override later if needed.
    """
    return psycopg2.connect(
        host=os.getenv("PF9_DB_HOST", "localhost"),
        port=int(os.getenv("PF9_DB_PORT", "5432")),
        dbname=os.getenv("PF9_DB_NAME", os.getenv("POSTGRES_DB", "pf9_mgmt")),
        user=os.getenv("PF9_DB_USER", os.getenv("POSTGRES_USER", "pf9")),
        password=os.getenv("PF9_DB_PASSWORD", os.getenv("POSTGRES_PASSWORD", "")),
    )


def start_inventory_run(conn, source="pf9_rvtools"):
    host_name = socket.gethostname()
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO inventory_runs (status, source, notes, host_name)
            VALUES (%s, %s, %s, %s)
            RETURNING id
            """,
            ("running", source, None, host_name),
        )
        run_id = cur.fetchone()[0]
    conn.commit()
    return run_id



def finish_inventory_run(conn, run_id, status="success", notes=None):
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE inventory_runs
               SET finished_at      = now(),
                   status           = %s,
                   notes            = %s,
                   duration_seconds = EXTRACT(EPOCH FROM (now() - created_at))::int
             WHERE id = %s
            """,
            (status, notes, run_id),
        )
    conn.commit()



# ----------------------------------------------------------------------
# Common helpers
# ----------------------------------------------------------------------

def _now_utc():
    return datetime.now(timezone.utc)


def _clean_project_id(val):
    """
    Normalize project_id values:
    - None, empty string, whitespace -> NULL
    - otherwise return as-is
    """
    if val is None:
        return None
    if isinstance(val, str) and not val.strip():
        return None
    return val


def _stable_hash(data: dict) -> str:
    """
    Stable SHA256 hash for a subset of fields we care about
    (used for history change detection).
    """
    payload = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ----------------------------------------------------------------------
# Deletion detection helpers
# ----------------------------------------------------------------------

def detect_and_record_deletions(conn, resource_type, current_ids, table_name, id_column, run_id=None):
    """
    Detect deletions by comparing current import with previous state.
    Records deleted resources in deletions_history table.
    """
    try:
        # Ensure current_ids contains only strings/UUIDs, not dict objects
        clean_current_ids = []
        if current_ids:
            for cid in current_ids:
                if isinstance(cid, str):
                    clean_current_ids.append(cid)
                elif isinstance(cid, dict):
                    if cid.get("id"):
                        clean_current_ids.append(str(cid["id"]))
                elif cid:  # any other truthy value, convert to string
                    clean_current_ids.append(str(cid))
        
        # Define name column based on table structure
        name_column_mapping = {
            'hypervisors': "COALESCE(hostname, raw_json->>'name', raw_json->>'display_name', raw_json->>'hostname')",
            'floating_ips': "COALESCE(floating_ip, raw_json->>'floating_ip_address', raw_json->>'name', raw_json->>'display_name')",
            'ports': "COALESCE(raw_json->>'name', raw_json->>'display_name', id)",
            # Default for tables with name column
            'default': "COALESCE(name, raw_json->>'name', raw_json->>'display_name')"
        }
        
        name_expression = name_column_mapping.get(table_name, name_column_mapping['default'])
        
        # Get previous resource IDs from current table that are NOT in the new import
        with conn.cursor() as cur:
            if clean_current_ids:
                # Verify all IDs are strings
                for idx, cid in enumerate(clean_current_ids):
                    if not isinstance(cid, str):
                        print(f"[DELETION ERROR] {resource_type}: clean_current_ids[{idx}] = {cid} (type={type(cid)})")
                        return 0
                
                # Find resources that existed before but are not in current import
                # AND haven't already been recorded as deleted
                placeholder = ','.join(['%s'] * len(clean_current_ids))
                sql_query = f"""
                    SELECT {id_column}, 
                           {name_expression} as resource_name,
                           raw_json,
                           last_seen_at
                    FROM {table_name}
                    WHERE {id_column} NOT IN ({placeholder})
                      AND {id_column} NOT IN (
                          SELECT DISTINCT resource_id 
                          FROM deletions_history 
                          WHERE resource_type = %s
                      )
                """
                cur.execute(sql_query, clean_current_ids + [resource_type])
            else:
                # If no current IDs, all existing resources are deleted
                # but only if not already recorded as deleted
                sql_query = f"""
                    SELECT {id_column}, 
                           {name_expression} as resource_name,
                           raw_json,
                           last_seen_at
                    FROM {table_name}
                    WHERE {id_column} NOT IN (
                        SELECT DISTINCT resource_id 
                        FROM deletions_history 
                        WHERE resource_type = %s
                    )
                """
                cur.execute(sql_query, [resource_type])
                
            deleted_resources = cur.fetchall()
            
            if deleted_resources:
                deletion_rows = []
                now = _now_utc()
                
                for resource in deleted_resources:
                    resource_id = resource[0]
                    resource_name = resource[1] or f"Unnamed-{resource_id[:8]}"
                    raw_json = resource[2] if resource[2] else {}
                    last_seen_at = resource[3] if len(resource) > 3 else now
                    
                    # Extract project/domain info from raw_json if available
                    project_name = raw_json.get('project_name') if raw_json else None
                    domain_name = raw_json.get('domain_name') or raw_json.get('tenant_name') if raw_json else None
                    
                    deletion_rows.append((
                        resource_type,
                        resource_id,
                        resource_name,
                        project_name,
                        domain_name,
                        last_seen_at,  # This becomes last_seen_before_deletion in DB
                        run_id,
                        Json(raw_json) if raw_json else Json({})
                    ))
                
                # Insert deletions using execute_values for better performance
                if deletion_rows:
                    from psycopg2.extras import execute_values
                    execute_values(
                        cur,
                        """INSERT INTO deletions_history 
                           (resource_type, resource_id, resource_name, project_name, domain_name, 
                            last_seen_before_deletion, detected_in_run_id, raw_json_snapshot)
                           VALUES %s""",
                        deletion_rows,
                        page_size=100
                    )
                    
                    print(f"[DELETION DETECTED] {len(deletion_rows)} {resource_type}(s) deleted")
                    return len(deletion_rows)
                    
                    print(f"[DELETION DETECTED] {len(deletion_rows)} {resource_type}(s) deleted")
                    return len(deletion_rows)
        
        return 0
    except Exception as e:
        print(f"[DELETION DETECTION ERROR] {resource_type}: {str(e)}")
        return 0


# ----------------------------------------------------------------------
# Upsert helpers with deletion detection
# ----------------------------------------------------------------------

def upsert_domains(conn, domains, run_id=None):
    """
    Upsert current domains AND append to domains_history
    when key fields change. Also detect domain deletions.
    """
    if not domains:
        domains = []
    
    now = _now_utc()
    
    # STEP 1: Detect and record deletions first
    current_domain_ids = []
    for d in domains:
        if isinstance(d, dict) and d.get("id"):
            current_domain_ids.append(str(d["id"]))
    deletions_count = detect_and_record_deletions(
        conn, 'domain', current_domain_ids, 'domains', 'id', run_id
    )
    
    current_rows = []
    history_rows = []
    current_ids = []

    for d in domains:
        if not isinstance(d, dict):
            continue
        did = d.get("id")
        if not did:
            continue
        
        current_ids.append(did)
        
        # Build change hash for history tracking
        hash_data = {
            "name": d.get("name"),
        }
        change_hash = _stable_hash(hash_data)
        
        current_rows.append((did, d.get("name"), Json(d), now))
        history_rows.append((
            did,
            d.get("name"),
            now,
            change_hash,
            Json(d),
        ))

    if not current_rows:
        # No new domains, but we might have detected deletions above
        return 0

    # 1) Current table upsert
    sql = """
    INSERT INTO domains (id, name, raw_json, last_seen_at)
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        name        = EXCLUDED.name,
        raw_json    = EXCLUDED.raw_json,
        last_seen_at = EXCLUDED.last_seen_at
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, current_rows, page_size=500)

    # 2) History table: Insert if change detected OR if no snapshot in the last 3 hours
    history_sql = """
    INSERT INTO domains_history (
        domain_id,
        name,
        recorded_at,
        change_hash,
        raw_json
    )
    SELECT
        v.domain_id,
        v.name,
        v.recorded_at,
        v.change_hash,
        v.raw_json::jsonb
    FROM (VALUES %s) AS v(
        domain_id,
        name,
        recorded_at,
        change_hash,
        raw_json
    )
    WHERE (
        -- Insert if this is a new change hash
        NOT EXISTS (
            SELECT 1 FROM domains_history h 
            WHERE h.domain_id = v.domain_id AND h.change_hash = v.change_hash
        )
    ) OR (
        -- OR insert if no snapshot in the last 3 hours (periodic snapshot)
        NOT EXISTS (
            SELECT 1 FROM domains_history h 
            WHERE h.domain_id = v.domain_id 
            AND h.recorded_at > (v.recorded_at - interval '3 hours')
        )
    )
    """

    with conn.cursor() as cur:
        execute_values(cur, history_sql, history_rows, page_size=500)

    conn.commit()
    return len(current_rows)



def upsert_projects(conn, projects, run_id=None):
    """
    Upsert current projects AND append to projects_history
    when key fields change.
    """
    if not projects:
        return 0
    now = _now_utc()
    
    # STEP 1: Detect and record deletions first
    current_project_ids = []
    for p in projects:
        if isinstance(p, dict) and p.get("id"):
            current_project_ids.append(str(p["id"]))
    deletions_count = detect_and_record_deletions(
        conn, 'project', current_project_ids, 'projects', 'id', run_id
    )

    current_rows = []
    history_rows = []

    for p in projects:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        if not pid:
            continue
        
        # Build change hash for history tracking
        hash_data = {
            "name": p.get("name"),
            "domain_id": p.get("domain_id"),
        }
        change_hash = _stable_hash(hash_data)
        
        current_rows.append((pid, p.get("name"), p.get("domain_id"), Json(p), now))
        history_rows.append((
            pid,
            p.get("name"),
            p.get("domain_id"),
            now,
            change_hash,
            Json(p),
        ))

    if not current_rows:
        return 0

    # 1) Current table upsert
    sql = """
    INSERT INTO projects (id, name, domain_id, raw_json, last_seen_at)
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        name        = EXCLUDED.name,
        domain_id   = EXCLUDED.domain_id,
        raw_json    = EXCLUDED.raw_json,
        last_seen_at = EXCLUDED.last_seen_at
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, current_rows, page_size=500)

    # 2) history table (insert only if hash is new)
    history_sql = """
    INSERT INTO projects_history (
        project_id,
        name,
        domain_id,
        recorded_at,
        change_hash,
        raw_json
    )
    SELECT
        v.project_id,
        v.name,
        v.domain_id,
        v.recorded_at,
        v.change_hash,
        v.raw_json::jsonb
    FROM (VALUES %s) AS v(
        project_id,
        name,
        domain_id,
        recorded_at,
        change_hash,
        raw_json
    )
    WHERE (
        -- Insert if this is a new change hash
        NOT EXISTS (
            SELECT 1 FROM projects_history h 
            WHERE h.project_id = v.project_id AND h.change_hash = v.change_hash
        )
    ) OR (
        -- OR insert if no snapshot in the last 3 hours (periodic snapshot)
        NOT EXISTS (
            SELECT 1 FROM projects_history h 
            WHERE h.project_id = v.project_id 
            AND h.recorded_at > (v.recorded_at - interval '3 hours')
        )
    )
    """

    with conn.cursor() as cur:
        execute_values(cur, history_sql, history_rows, page_size=500)

    conn.commit()
    return len(current_rows)


def upsert_flavors(conn, flavors, run_id=None):
    """
    Upsert current flavors AND append to flavors_history
    when key fields change.
    Store Nova flavors so we can show flavor_name, vcpus, ram, disk in views.
    Safely handles empty-string fields coming from the API.
    """
    if not flavors:
        return 0
    now = _now_utc()
    
    # STEP 1: Detect and record deletions first
    current_flavor_ids = []
    for f in flavors:
        if isinstance(f, dict) and f.get("id"):
            current_flavor_ids.append(str(f["id"]))
    deletions_count = detect_and_record_deletions(
        conn, 'flavor', current_flavor_ids, 'flavors', 'id', run_id
    )
    
    current_rows = []
    history_rows = []

    def _int_or_none(v):
        # Nova usually sends ints, but if it sends "" we convert to NULL
        if v is None or v == "":
            return None
        try:
            return int(v)
        except Exception:
            return None

    for f in flavors:
        if not isinstance(f, dict):
            continue
        fid = f.get("id")
        if not fid:
            continue

        vcpus = _int_or_none(f.get("vcpus"))
        ram_mb = _int_or_none(f.get("ram"))
        disk_gb = _int_or_none(f.get("disk"))
        swap_mb = _int_or_none(f.get("swap"))
        ephemeral_gb = _int_or_none(f.get("OS-FLV-EXT-DATA:ephemeral"))
        is_public = f.get("os-flavor-access:is_public")
        name = f.get("name")

        # Build change hash for history tracking
        hash_data = {
            "name": name,
            "vcpus": vcpus,
            "ram_mb": ram_mb,
            "disk_gb": disk_gb,
            "swap_mb": swap_mb,
            "ephemeral_gb": ephemeral_gb,
            "is_public": is_public,
        }
        change_hash = _stable_hash(hash_data)

        current_rows.append((
            fid,
            name,
            vcpus,
            ram_mb,
            disk_gb,
            swap_mb,
            ephemeral_gb,
            is_public,
            Json(f),
            now,
        ))
        
        history_rows.append((
            fid,
            name,
            vcpus,
            ram_mb,
            disk_gb,
            swap_mb,
            ephemeral_gb,
            is_public,
            now,
            change_hash,
            Json(f),
        ))

    if not current_rows:
        return 0

    # 1) Current table upsert
    sql = """
    INSERT INTO flavors (
      id, name, vcpus, ram_mb, disk_gb, swap_mb,
      ephemeral_gb, is_public, raw_json, last_seen_at
    )
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
      name         = EXCLUDED.name,
      vcpus        = EXCLUDED.vcpus,
      ram_mb       = EXCLUDED.ram_mb,
      disk_gb      = EXCLUDED.disk_gb,
      swap_mb      = EXCLUDED.swap_mb,
      ephemeral_gb = EXCLUDED.ephemeral_gb,
      is_public    = EXCLUDED.is_public,
      raw_json     = EXCLUDED.raw_json,
      last_seen_at = EXCLUDED.last_seen_at
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, current_rows, page_size=500)

    # 2) history table (insert only if hash is new)
    history_sql = """
    INSERT INTO flavors_history (
        flavor_id,
        name,
        vcpus,
        ram_mb,
        disk_gb,
        swap_mb,
        ephemeral_gb,
        is_public,
        recorded_at,
        change_hash,
        raw_json
    )
    SELECT
        v.flavor_id,
        v.name,
        v.vcpus::integer,
        v.ram_mb::integer,
        v.disk_gb::integer,
        v.swap_mb::integer,
        v.ephemeral_gb::integer,
        v.is_public::boolean,
        v.recorded_at::timestamptz,
        v.change_hash,
        v.raw_json::jsonb
    FROM (VALUES %s) AS v(
        flavor_id,
        name,
        vcpus,
        ram_mb,
        disk_gb,
        swap_mb,
        ephemeral_gb,
        is_public,
        recorded_at,
        change_hash,
        raw_json
    )
    WHERE (
        -- Insert if this is a new change hash
        NOT EXISTS (
            SELECT 1 FROM flavors_history h 
            WHERE h.flavor_id = v.flavor_id AND h.change_hash = v.change_hash
        )
    ) OR (
        -- OR insert if no snapshot in the last 3 hours (periodic snapshot)
        NOT EXISTS (
            SELECT 1 FROM flavors_history h 
            WHERE h.flavor_id = v.flavor_id 
            AND h.recorded_at > (v.recorded_at - interval '3 hours')
        )
    )
    """

    with conn.cursor() as cur:
        execute_values(cur, history_sql, history_rows, page_size=500)

    conn.commit()
    return len(current_rows)



def upsert_images(conn, images, run_id=None):
    """
    Upsert current images AND append to images_history
    when key fields change.
    Store Glance images so we can map image_id -> image_name.
    """
    if not images:
        return 0
    now = _now_utc()
    
    # STEP 1: Detect and record deletions first
    current_image_ids = []
    for i in images:
        if isinstance(i, dict) and i.get("id"):
            current_image_ids.append(str(i["id"]))
    deletions_count = detect_and_record_deletions(
        conn, 'image', current_image_ids, 'images', 'id', run_id
    )
    
    current_rows = []
    history_rows = []

    for img in images:
        if not isinstance(img, dict):
            continue
        iid = img.get("id")
        if not iid:
            continue

        name = img.get("name")
        status = img.get("status")
        visibility = img.get("visibility")
        protected = img.get("protected")
        size_bytes = img.get("size")

        # Build change hash for history tracking
        hash_data = {
            "name": name,
            "status": status,
            "visibility": visibility,
            "protected": protected,
            "size_bytes": size_bytes,
        }
        change_hash = _stable_hash(hash_data)

        current_rows.append((
            iid,
            name,
            status,
            visibility,
            protected,
            size_bytes,
            Json(img),
            now,
        ))
        
        history_rows.append((
            iid,
            name,
            status,
            visibility,
            size_bytes,
            img.get("disk_format"),
            img.get("container_format"),
            img.get("checksum"),
            img.get("created_at"),
            img.get("updated_at"),
            now,
            change_hash,
            Json(img),
        ))

    if not current_rows:
        return 0

    # 1) Current table upsert
    sql = """
    INSERT INTO images (
      id, name, status, visibility, protected,
      size_bytes, raw_json, last_seen_at
    )
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
      name       = EXCLUDED.name,
      status     = EXCLUDED.status,
      visibility = EXCLUDED.visibility,
      protected  = EXCLUDED.protected,
      size_bytes = EXCLUDED.size_bytes,
      raw_json   = EXCLUDED.raw_json,
      last_seen_at = EXCLUDED.last_seen_at
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, current_rows, page_size=500)

    # 2) history table (insert only if hash is new)
    history_sql = """
    INSERT INTO images_history (
        image_id,
        name,
        status,
        visibility,
        size_bytes,
        disk_format,
        container_format,
        checksum,
        created_at,
        updated_at,
        recorded_at,
        change_hash,
        raw_json
    )
    SELECT
        v.image_id,
        v.name,
        v.status,
        v.visibility,
        v.size_bytes::bigint,
        v.disk_format,
        v.container_format,
        v.checksum,
        v.created_at::timestamptz,
        v.updated_at::timestamptz,
        v.recorded_at::timestamptz,
        v.change_hash,
        v.raw_json::jsonb
    FROM (VALUES %s) AS v(
        image_id,
        name,
        status,
        visibility,
        size_bytes,
        disk_format,
        container_format,
        checksum,
        created_at,
        updated_at,
        recorded_at,
        change_hash,
        raw_json
    )
    WHERE (
        -- Insert if this is a new change hash
        NOT EXISTS (
            SELECT 1 FROM images_history h 
            WHERE h.image_id = v.image_id AND h.change_hash = v.change_hash
        )
    ) OR (
        -- OR insert if no snapshot in the last 3 hours (periodic snapshot)
        NOT EXISTS (
            SELECT 1 FROM images_history h 
            WHERE h.image_id = v.image_id 
            AND h.recorded_at > (v.recorded_at - interval '3 hours')
        )
    )
    """

    with conn.cursor() as cur:
        execute_values(cur, history_sql, history_rows, page_size=500)

    conn.commit()
    return len(current_rows)





def upsert_hypervisors(conn, hypervisors, run_id=None):
    """
    Upsert current hypervisors AND append to hypervisors_history
    when key fields change.
    """
    if not hypervisors:
        return 0
    now = _now_utc()
    
    # STEP 1: Detect and record deletions first
    current_hypervisor_ids = []
    for h in hypervisors:
        if isinstance(h, dict) and h.get("id"):
            current_hypervisor_ids.append(str(h["id"]))
    deletions_count = detect_and_record_deletions(
        conn, 'hypervisor', current_hypervisor_ids, 'hypervisors', 'id', run_id
    )

    current_rows = []
    history_rows = []
    
    for h in hypervisors:
        if not isinstance(h, dict):
            continue
        hid = h.get("id") or h.get("hypervisor_hostname")
        if not hid:
            continue

        hostname = h.get("hypervisor_hostname")
        hypervisor_type = h.get("hypervisor_type")
        vcpus = h.get("vcpus")
        memory_mb = h.get("memory_mb")
        local_gb = h.get("local_gb")
        state = h.get("state")
        status = h.get("status")

        # Build change hash for history tracking
        hash_data = {
            "hostname": hostname,
            "hypervisor_type": hypervisor_type,
            "vcpus": vcpus,
            "memory_mb": memory_mb,
            "local_gb": local_gb,
            "state": state,
            "status": status,
        }
        change_hash = _stable_hash(hash_data)

        current_rows.append((
            hid,
            hostname,
            hypervisor_type,
            vcpus,
            memory_mb,
            local_gb,
            state,
            status,
            Json(h),
            now,
        ))
        
        history_rows.append((
            hid,
            hostname,
            hypervisor_type,
            vcpus,
            memory_mb,
            local_gb,
            state,
            status,
            now,
            change_hash,
            Json(h),
        ))

    if not current_rows:
        return 0

    # 1) Current table upsert
    sql = """
    INSERT INTO hypervisors (
        id,
        hostname,
        hypervisor_type,
        vcpus,
        memory_mb,
        local_gb,
        state,
        status,
        raw_json,
        last_seen_at
    )
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        hostname        = EXCLUDED.hostname,
        hypervisor_type = EXCLUDED.hypervisor_type,
        vcpus           = EXCLUDED.vcpus,
        memory_mb       = EXCLUDED.memory_mb,
        local_gb        = EXCLUDED.local_gb,
        state           = EXCLUDED.state,
        status          = EXCLUDED.status,
        raw_json        = EXCLUDED.raw_json,
        last_seen_at    = EXCLUDED.last_seen_at
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, current_rows, page_size=200)

    # 2) history table (insert only if hash is new)
    history_sql = """
    INSERT INTO hypervisors_history (
        hypervisor_id,
        hostname,
        hypervisor_type,
        vcpus,
        memory_mb,
        local_gb,
        state,
        status,
        recorded_at,
        change_hash,
        raw_json
    )
    SELECT
        v.hypervisor_id,
        v.hostname,
        v.hypervisor_type,
        v.vcpus::integer,
        v.memory_mb::integer,
        v.local_gb::integer,
        v.state,
        v.status,
        v.recorded_at::timestamptz,
        v.change_hash,
        v.raw_json::jsonb
    FROM (VALUES %s) AS v(
        hypervisor_id,
        hostname,
        hypervisor_type,
        vcpus,
        memory_mb,
        local_gb,
        state,
        status,
        recorded_at,
        change_hash,
        raw_json
    )
    WHERE NOT EXISTS (
        SELECT 1
          FROM hypervisors_history h
         WHERE h.hypervisor_id = v.hypervisor_id::text
           AND h.change_hash   = v.change_hash
    )
    """

    with conn.cursor() as cur:
        execute_values(cur, history_sql, history_rows, page_size=200)
        
    conn.commit()
    return len(current_rows)


def upsert_servers(conn, servers, run_id=None):
    """
    Upsert current servers AND append to servers_history
    when key fields change (project, status, vm_state, flavor, hypervisor).
    """
    if not servers:
        return 0
    now = _now_utc()
    
    # STEP 1: Detect and record deletions first
    current_server_ids = []
    for s in servers:
        if isinstance(s, dict) and s.get("id"):
            current_server_ids.append(str(s["id"]))
    deletions_count = detect_and_record_deletions(
        conn, 'server', current_server_ids, 'servers', 'id', run_id
    )

    current_rows = []
    history_rows = []

    for s in servers:
        if not isinstance(s, dict):
            continue
        sid = s.get("id")
        if not sid:
            continue

        flavor = s.get("flavor")
        flavor_id = flavor.get("id") if isinstance(flavor, dict) else flavor

        hypervisor_hostname = (
            s.get("OS-EXT-SRV-ATTR:hypervisor_hostname")
            or s.get("OS-EXT-SRV-ATTR:host")
            or s.get("host")
        )

        project_id = _clean_project_id(s.get("project_id"))
        status = s.get("status")
        vm_state = s.get("OS-EXT-STS:vm_state")
        created_at = s.get("created")

        current_rows.append(
            (
                sid,
                s.get("name"),
                project_id,
                status,
                vm_state,
                flavor_id,
                hypervisor_hostname,
                created_at,
                Json(s),
                now,
            )
        )

        change_hash = _stable_hash(
            {
                "project_id": project_id,
                "status": status,
                "vm_state": vm_state,
                "flavor_id": flavor_id,
                "hypervisor_hostname": hypervisor_hostname,
            }
        )

        history_rows.append(
            (
                sid,
                project_id,
                status,
                vm_state,
                flavor_id,
                hypervisor_hostname,
                created_at,
                now,
                change_hash,
                Json(s),
            )
        )

    if not current_rows:
        return 0

    # 1) current table
    sql = """
    INSERT INTO servers (
        id,
        name,
        project_id,
        status,
        vm_state,
        flavor_id,
        hypervisor_hostname,
        created_at,
        raw_json,
        last_seen_at
    )
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        name                = EXCLUDED.name,
        project_id          = EXCLUDED.project_id,
        status              = EXCLUDED.status,
        vm_state            = EXCLUDED.vm_state,
        flavor_id           = EXCLUDED.flavor_id,
        hypervisor_hostname = EXCLUDED.hypervisor_hostname,
        created_at          = EXCLUDED.created_at,
        raw_json            = EXCLUDED.raw_json,
        last_seen_at        = EXCLUDED.last_seen_at
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, current_rows, page_size=500)

    # 2) history table (insert only if hash is new)
    history_sql = """
    INSERT INTO servers_history (
        server_id,
        project_id,
        status,
        vm_state,
        flavor_id,
        hypervisor_hostname,
        created_at,
        last_seen_at,
        change_hash,
        raw_json
    )
    SELECT
        v.server_id,
        v.project_id,
        v.status,
        v.vm_state,
        v.flavor_id,
        v.hypervisor_hostname,
        v.created_at::timestamptz,
        v.last_seen_at,
        v.change_hash,
        v.raw_json::jsonb
    FROM (VALUES %s) AS v(
        server_id,
        project_id,
        status,
        vm_state,
        flavor_id,
        hypervisor_hostname,
        created_at,
        last_seen_at,
        change_hash,
        raw_json
    )
    WHERE (
        -- Insert if this is a new change hash
        NOT EXISTS (
            SELECT 1 FROM servers_history h 
            WHERE h.server_id = v.server_id AND h.change_hash = v.change_hash
        )
    ) OR (
        -- OR insert if no snapshot in the last 3 hours (periodic snapshot)
        NOT EXISTS (
            SELECT 1 FROM servers_history h 
            WHERE h.server_id = v.server_id 
            AND h.last_seen_at > (v.last_seen_at - interval '3 hours')
        )
    )
    """

    with conn.cursor() as cur:
        execute_values(cur, history_sql, history_rows, page_size=500)

    conn.commit()
    return len(current_rows)


def upsert_volumes(conn, volumes, run_id=None):
    """
    Upsert current volumes AND append to volumes_history
    when key fields change.
    """
    if not volumes:
        return 0
    now = _now_utc()
    
    # STEP 1: Detect and record deletions first
    current_volume_ids = []
    for v in volumes:
        if isinstance(v, dict) and v.get("id"):
            current_volume_ids.append(str(v["id"]))
    deletions_count = detect_and_record_deletions(
        conn, 'volume', current_volume_ids, 'volumes', 'id', run_id
    )

    current_rows = []
    history_rows = []

    for v in volumes:
        if not isinstance(v, dict):
            continue
        vid = v.get("id")
        if not vid:
            continue

        project_id = _clean_project_id(v.get("project_id"))
        size_gb = v.get("size")
        status = v.get("status")
        volume_type = v.get("volume_type")
        bootable = str(v.get("bootable")).lower() == "true"
        created_at = v.get("created_at")

        # row for current "volumes" table
        current_rows.append(
            (
                vid,
                v.get("name"),
                project_id,
                size_gb,
                status,
                volume_type,
                bootable,
                created_at,
                Json(v),
                now,
            )
        )

        # hash for history change detection
        change_hash = _stable_hash(
            {
                "project_id": project_id,
                "size_gb": size_gb,
                "status": status,
                "volume_type": volume_type,
                "bootable": bootable,
            }
        )

        history_rows.append(
            (
                vid,
                project_id,
                size_gb,
                status,
                volume_type,
                bootable,
                created_at,
                now,
                change_hash,
                Json(v),
            )
        )

    if not current_rows:
        return 0

    # 1) current table upsert
    sql = """
    INSERT INTO volumes (
        id,
        name,
        project_id,
        size_gb,
        status,
        volume_type,
        bootable,
        created_at,
        raw_json,
        last_seen_at
    )
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        name        = EXCLUDED.name,
        project_id  = EXCLUDED.project_id,
        size_gb     = EXCLUDED.size_gb,
        status      = EXCLUDED.status,
        volume_type = EXCLUDED.volume_type,
        bootable    = EXCLUDED.bootable,
        created_at  = EXCLUDED.created_at,
        raw_json    = EXCLUDED.raw_json,
        last_seen_at = EXCLUDED.last_seen_at
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, current_rows, page_size=500)

    # 2) history table – note casts are ONLY in the SELECT,
    # not in the alias list.
    history_sql = """
    INSERT INTO volumes_history (
        volume_id,
        project_id,
        size_gb,
        status,
        volume_type,
        bootable,
        created_at,
        last_seen_at,
        change_hash,
        raw_json
    )
    SELECT
        v.volume_id,
        v.project_id,
        v.size_gb,
        v.status,
        v.volume_type,
        v.bootable,
        v.created_at::timestamptz,
        v.last_seen_at,
        v.change_hash,
        v.raw_json::jsonb
    FROM (VALUES %s) AS v(
        volume_id,
        project_id,
        size_gb,
        status,
        volume_type,
        bootable,
        created_at,
        last_seen_at,
        change_hash,
        raw_json
    )
    WHERE (
        -- Insert if this is a new change hash
        NOT EXISTS (
            SELECT 1 FROM volumes_history h 
            WHERE h.volume_id = v.volume_id AND h.change_hash = v.change_hash
        )
    ) OR (
        -- OR insert if no snapshot in the last 3 hours (periodic snapshot)
        NOT EXISTS (
            SELECT 1 FROM volumes_history h 
            WHERE h.volume_id = v.volume_id 
            AND h.last_seen_at > (v.last_seen_at - interval '3 hours')
        )
    )
    """
    with conn.cursor() as cur:
        execute_values(cur, history_sql, history_rows, page_size=500)

    conn.commit()
    return len(current_rows)



def upsert_networks(conn, networks, run_id=None):
    """
    Upsert current networks AND append to networks_history
    when key fields change.
    """
    if not networks:
        return 0
    now = _now_utc()

    # Validate project references to prevent FK violations
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM projects")
        valid_project_ids = {row[0] for row in cur.fetchall()}
    
    # STEP 1: Detect and record deletions first
    current_network_ids = []
    for n in networks:
        if isinstance(n, dict) and n.get("id"):
            current_network_ids.append(str(n["id"]))
    deletions_count = detect_and_record_deletions(
        conn, 'network', current_network_ids, 'networks', 'id', run_id
    )

    current_rows = []
    history_rows = []
    
    for n in networks:
        if not isinstance(n, dict):
            continue
        nid = n.get("id")
        if not nid:
            continue

        name = n.get("name")
        project_id = _clean_project_id(n.get("project_id"))
        if project_id and project_id not in valid_project_ids:
            print(
                f"[DB] Warning: Network {name or nid} references non-existent project {project_id}, setting to NULL"
            )
            project_id = None
        is_shared = bool(n.get("shared"))
        is_external = bool(n.get("router:external"))

        # Build change hash for history tracking
        hash_data = {
            "name": name,
            "project_id": project_id,
            "is_shared": is_shared,
            "is_external": is_external,
        }
        change_hash = _stable_hash(hash_data)

        current_rows.append((
            nid,
            name,
            project_id,
            is_shared,
            is_external,
            Json(n),
            now,
        ))
        
        history_rows.append((
            nid,
            name,
            project_id,
            is_shared,
            is_external,
            now,
            change_hash,
            Json(n),
        ))

    if not current_rows:
        return 0

    # 1) Current table upsert
    sql = """
    INSERT INTO networks (
        id,
        name,
        project_id,
        is_shared,
        is_external,
        raw_json,
        last_seen_at
    )
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        name        = EXCLUDED.name,
        project_id  = EXCLUDED.project_id,
        is_shared   = EXCLUDED.is_shared,
        is_external = EXCLUDED.is_external,
        raw_json    = EXCLUDED.raw_json,
        last_seen_at = EXCLUDED.last_seen_at
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, current_rows, page_size=500)

    # 2) history table (insert only if hash is new)
    history_sql = """
    INSERT INTO networks_history (
        network_id,
        name,
        project_id,
        is_shared,
        is_external,
        recorded_at,
        change_hash,
        raw_json
    )
    SELECT
        v.network_id,
        v.name,
        v.project_id,
        v.is_shared,
        v.is_external,
        v.recorded_at,
        v.change_hash,
        v.raw_json::jsonb
    FROM (VALUES %s) AS v(
        network_id,
        name,
        project_id,
        is_shared,
        is_external,
        recorded_at,
        change_hash,
        raw_json
    )
    WHERE (
        -- Insert if this is a new change hash
        NOT EXISTS (
            SELECT 1 FROM networks_history h 
            WHERE h.network_id = v.network_id AND h.change_hash = v.change_hash
        )
    ) OR (
        -- OR insert if no snapshot in the last 3 hours (periodic snapshot)
        NOT EXISTS (
            SELECT 1 FROM networks_history h 
            WHERE h.network_id = v.network_id 
            AND h.recorded_at > (v.recorded_at - interval '3 hours')
        )
    )
    """

    with conn.cursor() as cur:
        execute_values(cur, history_sql, history_rows, page_size=500)
        
    conn.commit()
    return len(current_rows)


def upsert_subnets(conn, subnets, run_id=None):
    """
    Upsert current subnets AND append to subnets_history
    when key fields change.
    """
    if not subnets:
        return 0
    now = _now_utc()
    
    # STEP 1: Detect and record deletions first
    current_subnet_ids = []
    for s in subnets:
        if isinstance(s, dict) and s.get("id"):
            current_subnet_ids.append(str(s["id"]))
    deletions_count = detect_and_record_deletions(
        conn, 'subnet', current_subnet_ids, 'subnets', 'id', run_id
    )

    current_rows = []
    history_rows = []
    
    for s in subnets:
        if not isinstance(s, dict):
            continue
        sid = s.get("id")
        if not sid:
            continue

        name = s.get("name")
        network_id = s.get("network_id")
        cidr = s.get("cidr")
        gateway_ip = s.get("gateway_ip")

        # Build change hash for history tracking
        hash_data = {
            "name": name,
            "network_id": network_id,
            "cidr": cidr,
            "gateway_ip": gateway_ip,
        }
        change_hash = _stable_hash(hash_data)

        current_rows.append((
            sid,
            name,
            network_id,
            cidr,
            gateway_ip,
            Json(s),
            now,
        ))
        
        history_rows.append((
            sid,
            name,
            network_id,
            cidr,
            gateway_ip,
            now,
            change_hash,
            Json(s),
        ))

    if not current_rows:
        return 0

    # 1) Current table upsert
    sql = """
    INSERT INTO subnets (
        id,
        name,
        network_id,
        cidr,
        gateway_ip,
        raw_json,
        last_seen_at
    )
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        name        = EXCLUDED.name,
        network_id  = EXCLUDED.network_id,
        cidr        = EXCLUDED.cidr,
        gateway_ip  = EXCLUDED.gateway_ip,
        raw_json    = EXCLUDED.raw_json,
        last_seen_at = EXCLUDED.last_seen_at
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, current_rows, page_size=500)

    # 2) history table (insert only if hash is new)
    history_sql = """
    INSERT INTO subnets_history (
        subnet_id,
        name,
        network_id,
        cidr,
        gateway_ip,
        recorded_at,
        change_hash,
        raw_json
    )
    SELECT
        v.subnet_id,
        v.name,
        v.network_id,
        v.cidr,
        v.gateway_ip,
        v.recorded_at,
        v.change_hash,
        v.raw_json::jsonb
    FROM (VALUES %s) AS v(
        subnet_id,
        name,
        network_id,
        cidr,
        gateway_ip,
        recorded_at,
        change_hash,
        raw_json
    )
    WHERE (
        -- Insert if this is a new change hash
        NOT EXISTS (
            SELECT 1 FROM subnets_history h 
            WHERE h.subnet_id = v.subnet_id AND h.change_hash = v.change_hash
        )
    ) OR (
        -- OR insert if no snapshot in the last 3 hours (periodic snapshot)
        NOT EXISTS (
            SELECT 1 FROM subnets_history h 
            WHERE h.subnet_id = v.subnet_id 
            AND h.recorded_at > (v.recorded_at - interval '3 hours')
        )
    )
    """

    with conn.cursor() as cur:
        execute_values(cur, history_sql, history_rows, page_size=500)
        
    conn.commit()
    return len(current_rows)


def upsert_routers(conn, routers, run_id=None):
    """
    Upsert current routers AND append to routers_history
    when key fields change.
    """
    if not routers:
        return 0
    now = _now_utc()
    
    # STEP 1: Detect and record deletions first
    current_router_ids = []
    for r in routers:
        if isinstance(r, dict) and r.get("id"):
            current_router_ids.append(str(r["id"]))
    deletions_count = detect_and_record_deletions(
        conn, 'router', current_router_ids, 'routers', 'id', run_id
    )

    current_rows = []
    history_rows = []
    
    for r in routers:
        if not isinstance(r, dict):
            continue
        rid = r.get("id")
        if not rid:
            continue

        ext_net = None
        egi = r.get("external_gateway_info")
        if isinstance(egi, dict):
            ext_net = egi.get("network_id")

        name = r.get("name")
        project_id = _clean_project_id(r.get("project_id"))

        # Build change hash for history tracking
        hash_data = {
            "name": name,
            "project_id": project_id,
            "external_net_id": ext_net,
        }
        change_hash = _stable_hash(hash_data)

        current_rows.append((
            rid,
            name,
            project_id,
            ext_net,
            Json(r),
            now,
        ))
        
        history_rows.append((
            rid,
            name,
            project_id,
            ext_net,
            now,
            change_hash,
            Json(r),
        ))

    if not current_rows:
        return 0

    # 1) Current table upsert
    sql = """
    INSERT INTO routers (
        id,
        name,
        project_id,
        external_net_id,
        raw_json,
        last_seen_at
    )
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        name           = EXCLUDED.name,
        project_id     = EXCLUDED.project_id,
        external_net_id = EXCLUDED.external_net_id,
        raw_json       = EXCLUDED.raw_json,
        last_seen_at   = EXCLUDED.last_seen_at
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, current_rows, page_size=500)

    # 2) history table (insert only if hash is new)
    history_sql = """
    INSERT INTO routers_history (
        router_id,
        name,
        project_id,
        external_net_id,
        recorded_at,
        change_hash,
        raw_json
    )
    SELECT
        v.router_id,
        v.name,
        v.project_id,
        v.external_net_id,
        v.recorded_at,
        v.change_hash,
        v.raw_json::jsonb
    FROM (VALUES %s) AS v(
        router_id,
        name,
        project_id,
        external_net_id,
        recorded_at,
        change_hash,
        raw_json
    )
    WHERE (
        -- Insert if this is a new change hash
        NOT EXISTS (
            SELECT 1 FROM routers_history h 
            WHERE h.router_id = v.router_id AND h.change_hash = v.change_hash
        )
    ) OR (
        -- OR insert if no snapshot in the last 3 hours (periodic snapshot)
        NOT EXISTS (
            SELECT 1 FROM routers_history h 
            WHERE h.router_id = v.router_id 
            AND h.recorded_at > (v.recorded_at - interval '3 hours')
        )
    )
    """

    with conn.cursor() as cur:
        execute_values(cur, history_sql, history_rows, page_size=500)
        
    conn.commit()
    return len(current_rows)


def upsert_ports(conn, ports, run_id=None):
    """
    Upsert current ports AND append to ports_history
    when key fields change.
    """
    if not ports:
        return 0
    now = _now_utc()

    # Validate project/network references to prevent FK violations
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM projects")
        valid_project_ids = {row[0] for row in cur.fetchall()}
        cur.execute("SELECT id FROM networks")
        valid_network_ids = {row[0] for row in cur.fetchall()}
    
    # STEP 1: Detect and record deletions first
    current_port_ids = []
    for p in ports:
        if isinstance(p, dict) and p.get("id"):
            current_port_ids.append(str(p["id"]))
    deletions_count = detect_and_record_deletions(
        conn, 'port', current_port_ids, 'ports', 'id', run_id
    )

    current_rows = []
    history_rows = []
    
    for p in ports:
        if not isinstance(p, dict):
            continue
        pid = p.get("id")
        if not pid:
            continue

        name = p.get("name")
        network_id = p.get("network_id")
        project_id = _clean_project_id(p.get("project_id"))
        if project_id and project_id not in valid_project_ids:
            print(
                f"[DB] Warning: Port {name or pid} references non-existent project {project_id}, setting to NULL"
            )
            project_id = None
        if network_id and network_id not in valid_network_ids:
            print(
                f"[DB] Warning: Port {name or pid} references non-existent network {network_id}, setting to NULL"
            )
            network_id = None
        device_id = p.get("device_id")
        device_owner = p.get("device_owner")
        mac_address = p.get("mac_address")
        ip_addresses = Json(p.get("fixed_ips"))

        # Build change hash for history tracking
        hash_data = {
            "name": name,
            "network_id": network_id,
            "project_id": project_id,
            "device_id": device_id,
            "device_owner": device_owner,
            "mac_address": mac_address,
        }
        change_hash = _stable_hash(hash_data)

        current_rows.append((
            pid,
            name,
            network_id,
            project_id,
            device_id,
            device_owner,
            mac_address,
            ip_addresses,
            Json(p),
            now,
        ))
        
        history_rows.append((
            pid,
            name,
            network_id,
            project_id,
            device_id,
            device_owner,
            mac_address,
            ip_addresses,
            now,
            change_hash,
            Json(p),
        ))

    if not current_rows:
        return 0

    # 1) Current table upsert
    sql = """
    INSERT INTO ports (
        id,
        name,
        network_id,
        project_id,
        device_id,
        device_owner,
        mac_address,
        ip_addresses,
        raw_json,
        last_seen_at
    )
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        name         = EXCLUDED.name,
        network_id   = EXCLUDED.network_id,
        project_id   = EXCLUDED.project_id,
        device_id    = EXCLUDED.device_id,
        device_owner = EXCLUDED.device_owner,
        mac_address  = EXCLUDED.mac_address,
        ip_addresses = EXCLUDED.ip_addresses,
        raw_json     = EXCLUDED.raw_json,
        last_seen_at = EXCLUDED.last_seen_at
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, current_rows, page_size=500)

    # 2) history table (insert only if hash is new)
    history_sql = """
    INSERT INTO ports_history (
        port_id,
        name,
        network_id,
        project_id,
        device_id,
        device_owner,
        mac_address,
        ip_addresses,
        recorded_at,
        change_hash,
        raw_json
    )
    SELECT
        v.port_id,
        v.name,
        v.network_id,
        v.project_id,
        v.device_id,
        v.device_owner,
        v.mac_address,
        v.ip_addresses::jsonb,
        v.recorded_at::timestamptz,
        v.change_hash,
        v.raw_json::jsonb
    FROM (VALUES %s) AS v(
        port_id,
        name,
        network_id,
        project_id,
        device_id,
        device_owner,
        mac_address,
        ip_addresses,
        recorded_at,
        change_hash,
        raw_json
    )
    WHERE (
        -- Insert if this is a new change hash
        NOT EXISTS (
            SELECT 1 FROM ports_history h 
            WHERE h.port_id = v.port_id AND h.change_hash = v.change_hash
        )
    ) OR (
        -- OR insert if no snapshot in the last 3 hours (periodic snapshot)
        NOT EXISTS (
            SELECT 1 FROM ports_history h 
            WHERE h.port_id = v.port_id 
            AND h.recorded_at > (v.recorded_at - interval '3 hours')
        )
    )
    """

    with conn.cursor() as cur:
        execute_values(cur, history_sql, history_rows, page_size=500)
        
    conn.commit()
    return len(current_rows)


def upsert_floating_ips(conn, floatingips, run_id=None):
    """
    Upsert current floating_ips AND append to floating_ips_history
    when key fields change.
    """
    if not floatingips:
        return 0
    now = _now_utc()
    
    # STEP 1: Detect and record deletions first
    current_fip_ids = []
    for f in floatingips:
        if isinstance(f, dict) and f.get("id"):
            current_fip_ids.append(str(f["id"]))
    deletions_count = detect_and_record_deletions(
        conn, 'floating_ip', current_fip_ids, 'floating_ips', 'id', run_id
    )

    current_rows = []
    history_rows = []
    
    for fip in floatingips:
        if not isinstance(fip, dict):
            continue
        fid = fip.get("id")
        if not fid:
            continue

        floating_ip = fip.get("floating_ip_address")
        fixed_ip = fip.get("fixed_ip_address")
        port_id = fip.get("port_id")
        project_id = _clean_project_id(fip.get("project_id"))
        router_id = fip.get("router_id")
        status = fip.get("status")

        # Build change hash for history tracking
        hash_data = {
            "floating_ip": floating_ip,
            "fixed_ip": fixed_ip,
            "port_id": port_id,
            "project_id": project_id,
            "router_id": router_id,
            "status": status,
        }
        change_hash = _stable_hash(hash_data)

        current_rows.append((
            fid,
            floating_ip,
            fixed_ip,
            port_id,
            project_id,
            router_id,
            status,
            Json(fip),
            now,
        ))
        
        history_rows.append((
            fid,
            floating_ip,
            fixed_ip,
            port_id,
            project_id,
            router_id,
            status,
            now,
            change_hash,
            Json(fip),
        ))

    if not current_rows:
        return 0

    # 1) Current table upsert
    sql = """
    INSERT INTO floating_ips (
        id,
        floating_ip,
        fixed_ip,
        port_id,
        project_id,
        router_id,
        status,
        raw_json,
        last_seen_at
    )
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        floating_ip = EXCLUDED.floating_ip,
        fixed_ip    = EXCLUDED.fixed_ip,
        port_id     = EXCLUDED.port_id,
        project_id  = EXCLUDED.project_id,
        router_id   = EXCLUDED.router_id,
        status      = EXCLUDED.status,
        raw_json    = EXCLUDED.raw_json,
        last_seen_at = EXCLUDED.last_seen_at
    """
    with conn.cursor() as cur:
        execute_values(cur, sql, current_rows, page_size=500)

    # 2) history table (insert only if hash is new)
    history_sql = """
    INSERT INTO floating_ips_history (
        floating_ip_id,
        floating_ip,
        fixed_ip,
        port_id,
        project_id,
        router_id,
        status,
        recorded_at,
        change_hash,
        raw_json
    )
    SELECT
        v.floating_ip_id,
        v.floating_ip,
        v.fixed_ip,
        v.port_id,
        v.project_id,
        v.router_id,
        v.status,
        v.recorded_at,
        v.change_hash,
        v.raw_json::jsonb
    FROM (VALUES %s) AS v(
        floating_ip_id,
        floating_ip,
        fixed_ip,
        port_id,
        project_id,
        router_id,
        status,
        recorded_at,
        change_hash,
        raw_json
    )
    WHERE (
        -- Insert if this is a new change hash
        NOT EXISTS (
            SELECT 1 FROM floating_ips_history h 
            WHERE h.floating_ip_id = v.floating_ip_id AND h.change_hash = v.change_hash
        )
    ) OR (
        -- OR insert if no snapshot in the last 3 hours (periodic snapshot)
        NOT EXISTS (
            SELECT 1 FROM floating_ips_history h 
            WHERE h.floating_ip_id = v.floating_ip_id 
            AND h.recorded_at > (v.recorded_at - interval '3 hours')
        )
    )
    """

    with conn.cursor() as cur:
        execute_values(cur, history_sql, history_rows, page_size=500)
        
    conn.commit()
    return len(current_rows)


def upsert_snapshots(conn, snapshots, run_id=None):
    if not snapshots:
        return 0
    now = _now_utc()
    
    # STEP 1: Detect and record deletions first
    current_snapshot_ids = []
    for s in snapshots:
        if isinstance(s, dict) and s.get("id"):
            current_snapshot_ids.append(str(s["id"]))
    deletions_count = detect_and_record_deletions(
        conn, 'snapshot', current_snapshot_ids, 'snapshots', 'id', run_id
    )

    # --- main table upsert rows ---
    main_values = []
    # --- history rows (only on change) ---
    hist_values = []

    for sn in snapshots:
        if not isinstance(sn, dict):
            continue
        sid = sn.get("id")
        if not sid:
            continue

        size_gb = sn.get("size")
        project_id = sn.get("project_id") or sn.get("os-extended-snapshot-attributes:project_id")
        volume_id = sn.get("volume_id")

        ch = _stable_hash(sn)

        main_values.append(
            (
                sid,
                sn.get("name"),
                sn.get("description"),
                sn.get("status"),
                size_gb,
                volume_id,
                project_id,
                sn.get("project_name"),
                sn.get("tenant_name"),
                sn.get("domain_name"),
                sn.get("domain_id"),
                sn.get("created_at"),
                sn.get("updated_at"),
                Json(sn),
                now,
            )
        )

        # History row (we’ll insert with ON CONFLICT DO NOTHING on (snapshot_id, change_hash))
        hist_values.append(
            (
                sid,
                run_id,
                project_id,
                volume_id,
                sn.get("status"),
                size_gb,
                sn.get("name"),
                sn.get("created_at"),
                sn.get("updated_at"),
                ch,
                Json(sn),
                now,
            )
        )

    if not main_values:
        return 0

    # Upsert current snapshot state
    main_sql = """
    INSERT INTO snapshots (
        id, name, description, status, size_gb, volume_id, project_id,
        project_name, tenant_name, domain_name, domain_id,
        created_at, updated_at, raw_json, last_seen_at
    )
    VALUES %s
    ON CONFLICT (id)
      DO UPDATE SET
        name         = EXCLUDED.name,
        description  = EXCLUDED.description,
        status       = EXCLUDED.status,
        size_gb      = EXCLUDED.size_gb,
        volume_id    = EXCLUDED.volume_id,
        project_id   = EXCLUDED.project_id,
        project_name = EXCLUDED.project_name,
        tenant_name  = EXCLUDED.tenant_name,
        domain_name  = EXCLUDED.domain_name,
        domain_id    = EXCLUDED.domain_id,
        created_at   = EXCLUDED.created_at,
        updated_at   = EXCLUDED.updated_at,
        raw_json     = EXCLUDED.raw_json,
        last_seen_at = EXCLUDED.last_seen_at
    """

    # Insert history only when hash is new
    hist_sql = """
    INSERT INTO snapshots_history (
        snapshot_id, run_id, project_id, volume_id,
        status, size_gb, name, created_at, updated_at,
        change_hash, raw_json, last_seen_at
    )
    VALUES %s
    ON CONFLICT (snapshot_id, change_hash) DO NOTHING
    """

    with conn.cursor() as cur:
        execute_values(cur, main_sql, main_values, page_size=500)
        execute_values(cur, hist_sql, hist_values, page_size=500)

    conn.commit()
    return len(main_values)


# ======================================================================
# User and Role Management Writers
# ======================================================================

def write_users(conn, users_data, run_id=None):
    """
    Write users data from Keystone API to users table.
    
    Args:
        conn: Database connection
        users_data: List of user dicts from Keystone API
        run_id: Optional inventory run ID
        
    Returns:
        Number of records processed
    """
    if not users_data:
        return 0

    # Get existing project IDs to validate foreign key references
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM projects")
        valid_project_ids = {row[0] for row in cur.fetchall()}

    # Detect deletions
    current_ids = [user["id"] for user in users_data]
    detect_and_record_deletions(conn, "user", current_ids, "users", "id", run_id)

    main_values = []
    hist_values = []
    now = _now_utc()

    for user in users_data:
        user_id = user["id"]
        name = user.get("name", "")
        email = user.get("email")
        enabled = user.get("enabled", True)
        domain_id = user.get("domain_id")
        description = user.get("description")
        default_project_id = user.get("default_project_id")
        
        # Validate default_project_id - set to None if project doesn't exist
        if default_project_id and default_project_id not in valid_project_ids:
            print(f"[DB] Warning: User {name} references non-existent project {default_project_id}, setting to NULL")
            default_project_id = None
        
        # Parse timestamps if present
        password_expires_at = None
        if user.get("password_expires_at"):
            try:
                password_expires_at = datetime.fromisoformat(user["password_expires_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
                
        created_at = None
        if user.get("created_at"):
            try:
                created_at = datetime.fromisoformat(user["created_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
        
        # Handle last_login_at field (if present in OpenStack extensions)
        last_login = None
        if user.get("last_login_at"):
            try:
                last_login = datetime.fromisoformat(user["last_login_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass
        elif user.get("last_activity_at"):
            try:
                last_login = datetime.fromisoformat(user["last_activity_at"].replace("Z", "+00:00"))
            except (ValueError, AttributeError):
                pass

        # Create change hash for history tracking
        core_fields = {
            "name": name,
            "email": email,
            "enabled": enabled,
            "domain_id": domain_id,
            "description": description,
            "default_project_id": default_project_id
        }
        change_hash = _stable_hash(core_fields)

        # Main table record
        main_values.append((
            user_id, name, email, enabled, domain_id, description,
            default_project_id, password_expires_at, created_at, last_login,
            Json(user), now
        ))

        # History table record  
        hist_values.append((
            user_id, run_id, name, email, enabled, domain_id, description,
            default_project_id, password_expires_at, created_at, last_login,
            change_hash, Json(user), now
        ))

    # Main table upsert
    main_sql = """
    INSERT INTO users (
        id, name, email, enabled, domain_id, description,
        default_project_id, password_expires_at, created_at, last_login,
        raw_json, last_seen_at
    )
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        name = EXCLUDED.name,
        email = EXCLUDED.email,
        enabled = EXCLUDED.enabled,
        domain_id = EXCLUDED.domain_id,
        description = EXCLUDED.description,
        default_project_id = EXCLUDED.default_project_id,
        password_expires_at = EXCLUDED.password_expires_at,
        created_at = EXCLUDED.created_at,
        last_login = EXCLUDED.last_login,
        raw_json = EXCLUDED.raw_json,
        last_seen_at = EXCLUDED.last_seen_at
    """

    # History table (skip duplicates based on change_hash)
    hist_sql = """
    INSERT INTO users_history (
        user_id, run_id, name, email, enabled, domain_id, description,
        default_project_id, password_expires_at, created_at, last_login,
        change_hash, raw_json, recorded_at
    )
    VALUES %s
    ON CONFLICT (user_id, change_hash) DO NOTHING
    """

    with conn.cursor() as cur:
        execute_values(cur, main_sql, main_values, page_size=500)
        execute_values(cur, hist_sql, hist_values, page_size=500)

    conn.commit()
    return len(main_values)


def write_roles(conn, roles_data, run_id=None):
    """
    Write roles data from Keystone API to roles table.
    
    Args:
        conn: Database connection
        roles_data: List of role dicts from Keystone API
        run_id: Optional inventory run ID
        
    Returns:
        Number of records processed
    """
    if not roles_data:
        return 0

    # Detect deletions
    current_ids = [role["id"] for role in roles_data]
    detect_and_record_deletions(conn, "role", current_ids, "roles", "id", run_id)

    main_values = []
    hist_values = []
    now = _now_utc()

    for role in roles_data:
        role_id = role["id"]
        name = role.get("name", "")
        description = role.get("description")
        domain_id = role.get("domain_id")

        # Create change hash for history tracking
        core_fields = {
            "name": name,
            "description": description,
            "domain_id": domain_id
        }
        change_hash = _stable_hash(core_fields)

        # Main table record
        main_values.append((
            role_id, name, description, domain_id, Json(role), now
        ))

        # History table record  
        hist_values.append((
            role_id, run_id, name, description, domain_id,
            change_hash, Json(role), now
        ))

    # Main table upsert
    main_sql = """
    INSERT INTO roles (
        id, name, description, domain_id, raw_json, last_seen_at
    )
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        name = EXCLUDED.name,
        description = EXCLUDED.description,
        domain_id = EXCLUDED.domain_id,
        raw_json = EXCLUDED.raw_json,
        last_seen_at = EXCLUDED.last_seen_at
    """

    # History table (skip duplicates based on change_hash)
    hist_sql = """
    INSERT INTO roles_history (
        role_id, run_id, name, description, domain_id,
        change_hash, raw_json, recorded_at
    )
    VALUES %s
    ON CONFLICT (role_id, change_hash) DO NOTHING
    """

    with conn.cursor() as cur:
        execute_values(cur, main_sql, main_values, page_size=500)
        execute_values(cur, hist_sql, hist_values, page_size=500)

    conn.commit()
    return len(main_values)


def write_role_assignments(conn, assignments_data, run_id=None):
    """
    Write role assignments data from Keystone API to role_assignments table.
    
    Args:
        conn: Database connection
        assignments_data: List of role assignment dicts from Keystone API
        run_id: Optional inventory run ID
        
    Returns:
        Number of records processed
    """
    if not assignments_data:
        return 0

    # For role assignments, we need to clear and rebuild since they don't have stable IDs
    # First, mark all current assignments as potentially stale
    with conn.cursor() as cur:
        cur.execute("DELETE FROM role_assignments WHERE last_seen_at < %s", (datetime.now(timezone.utc),))

    main_values = []
    now = _now_utc()

    # Load valid IDs to avoid FK violations
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM projects")
        valid_projects = {row[0] for row in cur.fetchall()}
        cur.execute("SELECT id FROM domains")
        valid_domains = {row[0] for row in cur.fetchall()}
        cur.execute("SELECT id FROM roles")
        valid_roles = {row[0] for row in cur.fetchall()}
        cur.execute("SELECT id FROM users")
        valid_users = {row[0] for row in cur.fetchall()}

    for assignment in assignments_data:
        # Extract assignment details from Keystone API response
        role = assignment.get("role", {})
        role_id = role.get("id")
        role_name = role.get("name")
        
        user = assignment.get("user", {})
        user_id = user.get("id") if user else None
        user_name = user.get("name") if user else None
        
        group = assignment.get("group", {})
        group_id = group.get("id") if group else None
        
        scope = assignment.get("scope", {})
        project = scope.get("project", {}) if scope else {}
        domain = scope.get("domain", {}) if scope else {}
        
        project_id = project.get("id") if project else None
        project_name = project.get("name") if project else None
        
        domain_id = domain.get("id") if domain else None
        domain_name = domain.get("name") if domain else None
        
        inherited = assignment.get("scope", {}).get("OS-INHERIT:inherited_to", "projects") == "projects"

        # Validate foreign keys; null invalid project/domain to avoid FK errors
        if project_id and project_id not in valid_projects:
            project_id = None
            project_name = None
        if domain_id and domain_id not in valid_domains:
            domain_id = None
            domain_name = None

        # Skip invalid assignments
        if (role_id and role_id not in valid_roles) or (user_id and user_id not in valid_users):
            continue
        if not role_id or not (user_id or group_id) or not (project_id or domain_id):
            continue

        # Main table record
        main_values.append((
            role_id, user_id, group_id, project_id, domain_id, inherited,
            user_name, role_name, project_name, domain_name,
            Json(assignment), now
        ))

    # Use INSERT with ON CONFLICT to handle unique constraint
    main_sql = """
    INSERT INTO role_assignments (
        role_id, user_id, group_id, project_id, domain_id, inherited,
        user_name, role_name, project_name, domain_name,
        raw_json, last_seen_at
    )
    VALUES %s
    ON CONFLICT (role_id, user_id, project_id, domain_id, group_id)
    DO UPDATE SET
        user_name = EXCLUDED.user_name,
        role_name = EXCLUDED.role_name,
        project_name = EXCLUDED.project_name,
        domain_name = EXCLUDED.domain_name,
        inherited = EXCLUDED.inherited,
        raw_json = EXCLUDED.raw_json,
        last_seen_at = EXCLUDED.last_seen_at
    """

    with conn.cursor() as cur:
        execute_values(cur, main_sql, main_values, page_size=500)

    conn.commit()
    return len(main_values)


def write_groups(conn, groups_data, run_id=None):
    """
    Write groups data from Keystone API to groups table.
    
    Args:
        conn: Database connection
        groups_data: List of group dicts from Keystone API
        run_id: Optional inventory run ID
        
    Returns:
        Number of records processed
    """
    if not groups_data:
        return 0

    # Detect deletions
    current_ids = [group["id"] for group in groups_data]
    detect_and_record_deletions(conn, "group", current_ids, "groups", "id", run_id)

    main_values = []
    now = _now_utc()

    for group in groups_data:
        group_id = group["id"]
        name = group.get("name", "")
        domain_id = group.get("domain_id")
        description = group.get("description")

        # Main table record
        main_values.append((
            group_id, name, domain_id, description, Json(group), now
        ))

    # Main table upsert
    main_sql = """
    INSERT INTO groups (
        id, name, domain_id, description, raw_json, last_seen_at
    )
    VALUES %s
    ON CONFLICT (id) DO UPDATE SET
        name = EXCLUDED.name,
        domain_id = EXCLUDED.domain_id,
        description = EXCLUDED.description,
        raw_json = EXCLUDED.raw_json,
        last_seen_at = EXCLUDED.last_seen_at
    """

    with conn.cursor() as cur:
        execute_values(cur, main_sql, main_values, page_size=500)

    conn.commit()
    return len(main_values)


def log_user_access(conn, user_id, user_name, action, resource_type=None, 
                   resource_id=None, project_id=None, success=True, 
                   ip_address=None, user_agent=None, details=None):
    """
    Log user access activity for monitoring and analytics.
    
    Args:
        conn: Database connection
        user_id: User ID from Keystone
        user_name: User display name
        action: Action type ('login', 'api_call', 'resource_access')
        resource_type: Type of resource accessed (optional)
        resource_id: ID of resource accessed (optional)
        project_id: Project context (optional)
        success: Whether the action was successful
        ip_address: Client IP address (optional)
        user_agent: Client user agent (optional)
        details: Additional details as dict (optional)
    """
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO user_access_logs (
                user_id, user_name, action, resource_type, resource_id,
                project_id, success, ip_address, user_agent, details
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id, user_name, action, resource_type, resource_id,
            project_id, success, ip_address, user_agent,
            Json(details) if details else None
        ))
    conn.commit()
