# Platform9 Management System — Backup Guide

**Version**: 1.0  
**Last Updated**: March 2026  
**Status**: Production Ready

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Prerequisites](#prerequisites)
4. [Enabling Backup](#enabling-backup)
5. [NFS Server Requirements](#nfs-server-requirements)
6. [Docker Network Requirement](#docker-network-requirement)
7. [Environment Variables](#environment-variables)
8. [Configuring via the UI](#configuring-via-the-ui)
9. [Manual Backups](#manual-backups)
10. [LDAP Backups](#ldap-backups)
11. [Backup Status & History](#backup-status--history)
12. [Restore from Backup](#restore-from-backup)
13. [Retention Policy](#retention-policy)
14. [Troubleshooting](#troubleshooting)

---

## Overview

The platform includes a fully containerised backup system that automates:

- **Database backups** — compressed `pg_dump` exports (`.sql.gz`) of the PostgreSQL database
- **LDAP backups** — compressed `ldapsearch` exports (`.ldif.gz`) of all directory entries (users, groups, OUs)

Backups are written to an **NFS-mounted volume** and managed by the `pf9_backup_worker` container. Schedule, retention, and manual triggers are all configured from the **💾 Backup & Restore** tab in the management UI. No cron jobs or external schedulers are required.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│ Docker Host                                             │
│                                                         │
│  ┌──────────────────┐       ┌──────────────────────┐   │
│  │  pf9_backup_     │       │  pf9_db              │   │
│  │  worker          │──────▶│  PostgreSQL 16        │   │
│  │  (pg_dump /      │       │  :5432               │   │
│  │   ldapsearch)    │       └──────────────────────┘   │
│  │                  │                                   │
│  │  /backups        │──── Docker volume                 │
│  └──────────────────┘      pf9-mngt_nfs_backups         │
│                                    │                    │
└────────────────────────────────────┼────────────────────┘
                                     │ NFS v3 (port 2049)
                              ┌──────▼──────────────┐
                              │  NFS Server          │
                              │  /pf9-nfs            │
                              │  (your NAS/file      │
                              │   server)            │
                              └─────────────────────┘
```

**Key facts:**
- Backup worker is only started when `COMPOSE_PROFILES=backup` is set in `.env`
- The NFS volume (`pf9-mngt_nfs_backups`) is declared in `docker-compose.yml` and only mounted when the `backup` profile is active
- Database files: `/backups/pf9_mgmt_YYYYMMDD_HHMMSS.sql.gz`
- LDAP files: `/backups/ldap/pf9_ldap_YYYYMMDD_HHMMSS.ldif.gz`
- The backup worker polls for pending jobs every `BACKUP_JOB_POLL_INTERVAL` seconds (default: 30), and checks the schedule every `BACKUP_POLL_INTERVAL` seconds (default: 3600)

---

## Prerequisites

| Requirement | Details |
|---|---|
| NFS server | Accessible from the Docker host on port 2049 |
| NFS export | Read/write access for the Docker host's IP |
| Docker Desktop | v4.x+ (WSL 2 engine recommended) |
| Free TCP port | 2049 reachable from Docker containers (see [Docker Network Requirement](#docker-network-requirement)) |

---

## Enabling Backup

1. Open `.env` and set:

```dotenv
# Enable the backup worker and NFS volume
COMPOSE_PROFILES=backup

# NFS server connection
NFS_BACKUP_SERVER=<your-nfs-server-ip>
NFS_BACKUP_DEVICE=/pf9-nfs        # exported path on the NFS server
NFS_VERSION=3                      # always use 3 for Docker Desktop

# Poll intervals
BACKUP_JOB_POLL_INTERVAL=30        # seconds between pending-job checks
BACKUP_POLL_INTERVAL=3600          # seconds between schedule checks
```

2. Run `./startup.ps1` — the script performs a pre-flight TCP check to `NFS_BACKUP_SERVER:2049` before starting Docker services. If the NFS server is unreachable it will ask whether to start without backup for this run.

3. Verify:
```powershell
docker logs pf9_backup_worker --tail 20
# Expected:
# Backup worker starting  (poll every 30 s, NFS → /backups)
# Storage health check passed – backup path is writable.
```

To **disable** backup, set `COMPOSE_PROFILES=` (empty) in `.env` and restart. The NFS volume definition in `docker-compose.yml` is harmless when the backup profile is inactive.

---

## NFS Server Requirements

### Export configuration (on the NFS server)

```
/pf9-nfs   <docker-host-ip>(rw,sync,no_subtree_check,no_root_squash)
```

- Write access is required (`rw`)
- `no_root_squash` is recommended so that container processes writing as root can create files
- NFSv3 is required (`no_root_squash` ensures it works with Docker's Linux VM)

### Verify from Windows before starting:

```powershell
# Check TCP connectivity to NFS port
Test-NetConnection -ComputerName <NFS_IP> -Port 2049

# Or using tcping
tcping <NFS_IP> 2049
```

### Verify from inside Docker after starting:

```powershell
docker run --rm alpine sh -c "nc -zv <NFS_IP> 2049"
# Expected: open
```

---

## Docker Network Requirement

> **Important for Docker Desktop on Windows**: Docker's default `docker0` bridge network uses `172.17.0.0/16`. If your NFS server's IP falls within that range (e.g. `172.17.x.x`), Docker will route traffic internally and never reach the real LAN — resulting in `no route to host`.

**Fix**: Change Docker's bridge subnet in **Docker Desktop → Settings → Docker Engine**:

```json
{
  "builder": {"gc": {"defaultKeepStorage": "20GB", "enabled": true}},
  "experimental": false,
  "bip": "192.168.200.1/24",
  "default-address-pools": [{"base": "192.168.201.0/24", "size": 24}]
}
```

Click **Apply & restart**. All container data and volumes are preserved.

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `COMPOSE_PROFILES` | *(empty)* | Set to `backup` to enable the backup worker and NFS volume |
| `NFS_BACKUP_SERVER` | *(required)* | IP address of the NFS server |
| `NFS_BACKUP_DEVICE` | `/pf9-nfs` | Exported path on the NFS server |
| `NFS_VERSION` | `3` | NFS protocol version (use `3` for Docker Desktop) |
| `BACKUP_JOB_POLL_INTERVAL` | `30` | Seconds between checks for pending manual/restore jobs |
| `BACKUP_POLL_INTERVAL` | `3600` | Seconds between schedule checks (automated backup frequency window) |

---

## Configuring via the UI

Navigate to **💾 Backup & Restore** in the management portal.

### Status tab

Shows two side-by-side panels — one for Database, one for LDAP — each displaying:

| Field | Description |
|---|---|
| Schedule badge | `Scheduled` (automated on), `Manual` (manual-only), `Running` (job in progress) |
| Schedule | Human-readable schedule: `Daily at 02:00 UTC`, `Weekly (Sunday) at 02:00 UTC`, or `Manual only` |
| Backups Stored | Count and total size of completed backups for this target |
| Last Backup | Relative time since last completed backup |
| Last File | Filename of the most recent backup |
| Last Size / Duration | File size and pg_dump duration |

The top summary bar shows overall state (Idle / Running), total backup count, total size, and last backup time across both targets.

### Settings tab

| Setting | Description |
|---|---|
| **Automated Backups** | Toggle to enable/disable scheduled DB backups |
| **Schedule Type** | `Manual Only`, `Daily`, or `Weekly` |
| **Time (UTC)** | Time of day for the scheduled backup |
| **Day of Week** | *(Weekly only)* Day to run the backup |
| **Keep Last N Backups** | Maximum number of completed DB backups to retain |
| **Retention Days** | Delete DB backups older than this many days |
| **NFS Backup Path** | Mount point inside the backup worker container (default: `/backups`) |
| **LDAP Scheduled Backup** | Toggle to also export LDAP on the same schedule |
| **Keep Last N LDAP Backups** | Maximum number of LDAP backup files to retain |
| **LDAP Retention Days** | Delete LDAP backups older than this many days |

Click **💾 Save Configuration** to apply. Changes take effect on the next poll cycle.

---

## Manual Backups

From the **Status** tab:

- Click **🚀 Database Backup** to immediately queue a database backup job
- Click **📁 LDAP Backup** to immediately queue an LDAP backup job

The backup worker picks up pending jobs within `BACKUP_JOB_POLL_INTERVAL` seconds (default: 30 s). Refresh the **History** tab to see progress.

---

## LDAP Backups

LDAP backups export **all directory entries** (users, groups, OUs) under the configured base DN using `ldapsearch`, compressed with gzip. Files are written to `/backups/ldap/` inside the container (i.e. in the `ldap/` subdirectory of your NFS share).

LDAP backups follow the **same schedule** as database backups when **LDAP Scheduled Backup** is enabled in Settings. They can also be triggered manually at any time regardless of the schedule toggle.

LDAP retention (count + days) is configured separately from database retention.

---

## Backup Status & History

The **History** tab shows a paginated table of all backup and restore jobs:

| Column | Description |
|---|---|
| ID | Sequential job ID |
| Status | `pending`, `running`, `completed`, `failed`, `deleted` |
| Target | `🗄️ DB` or `📁 LDAP` |
| Type | `manual`, `scheduled`, or `restore` |
| File | Filename written to NFS |
| Size | Compressed file size |
| Duration | Wall-clock time for pg_dump / ldapsearch + gzip |
| Integrity | `✔ valid` if post-backup integrity check passed |
| Initiated By | `admin`, `scheduler`, or username |
| Started / Completed | Timestamps |
| Actions | ♻️ Restore (superadmin) · 🗑️ Delete |

Filter by status or target using the dropdowns at the top.

---

## Restore from Backup

> **Requires**: Superadmin role

From the **History** tab, click **♻️ Restore** on any `completed` database backup. A confirmation dialog will appear; confirm to queue the restore job.

The backup worker will:
1. Stop accepting other jobs while restoring
2. Decompress the `.sql.gz` file using `gunzip`
3. Pipe the SQL through `psql` into the live database
4. Mark the restore job `completed` or `failed`

> ⚠️ **Restoring overwrites the current database.** All data changed after the backup was taken will be lost. This operation cannot be undone. Only run in an emergency or as part of a planned disaster recovery event.

For point-in-time VM restore (snapshot → new VM), see [RESTORE_GUIDE.md](RESTORE_GUIDE.md).

---

## Retention Policy

After each successful backup, the worker automatically enforces the retention policy:

1. Fetch all `completed` backups for the target, ordered newest-first
2. Keep up to `retention_count` backups
3. Delete any backup older than `retention_days` days
4. For deleted backups: removes the file from NFS **and** marks the history row as `deleted`

Deletion is logged in the **History** tab with status `deleted`.

---

## Troubleshooting

### Backup stays `pending` forever

The worker polls for pending jobs every `BACKUP_JOB_POLL_INTERVAL` seconds. Check the worker is running:

```powershell
docker ps | Select-String "backup"
docker logs pf9_backup_worker --tail 30
```

If the container is not running, check `COMPOSE_PROFILES=backup` is set and restart with `./startup.ps1`.

### `no route to host` mounting NFS volume

Docker's default bridge (`172.17.0.0/16`) conflicts with your NFS server IP. See [Docker Network Requirement](#docker-network-requirement) above.

### `protocol not supported` mounting NFS volume

The Docker Desktop Linux VM kernel does not support NFSv4. Set `NFS_VERSION=3` in `.env`.

### `permission denied` writing to NFS

Check the NFS server export has `rw` and `no_root_squash`. Verify from Windows:

```powershell
docker run --rm -v pf9-mngt_nfs_backups:/mnt alpine sh -c "touch /mnt/test && echo OK"
```

### Volume config mismatch prompt

If you change NFS settings, `startup.ps1` automatically removes the stale `pf9-mngt_nfs_backups` volume before starting. If you run `docker compose up -d` manually and see `Recreate (data will be lost)?`, type `y` — the NFS volume holds no local data.

### NFS pre-flight check fails at startup

`startup.ps1` will offer to start **without** the backup worker for this run only (`.env` is not modified). This is safe — no data is at risk. Investigate NFS connectivity and restart when ready.

### Backup worker starts but `storage health check FAILED`

NFS is mounted but not writable. Check:
1. NFS export permissions (`rw`, `no_root_squash`)
2. Whether `pf9-mngt_nfs_backups` volume was created correctly: `docker volume inspect pf9-mngt_nfs_backups`
3. Whether another process has a stale lock on the NFS path

### LDAP backup fails with `Can't contact LDAP server`

The `pf9_ldap` container must be running. Check:
```powershell
docker ps | Select-String "ldap"
docker logs pf9_ldap --tail 20
```

---

**Related Documentation**:
- [Deployment Guide](DEPLOYMENT_GUIDE.md) — Full environment configuration
- [Restore Guide](RESTORE_GUIDE.md) — VM snapshot restore (separate from DB backup)
- [Architecture](ARCHITECTURE.md) — Service communication and data flows
- [Admin Guide](ADMIN_GUIDE.md) — Day-to-day administration
