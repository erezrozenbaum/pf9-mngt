"""
pf9_telemetry.py — Platform9 Gnocchi (OpenStack Telemetry) integration.

Fetches real-time per-VM metrics (CPU %, memory MB, disk IOPS, network MB/s)
from the Platform9 Gnocchi API using the same Keystone credentials already
configured for the admin API (PF9_AUTH_URL / PF9_USERNAME / PF9_PASSWORD).

Fallback chain for the Current Usage tab (in priority order):
  1. Shared monitoring cache file    — Docker Compose + Prometheus exporters
  2. pf9-monitoring HTTP API         — K8s, Prometheus available
  3. This module / Gnocchi           — K8s, no Prometheus; real P9 telemetry
  4. DB allocation estimate          — last resort (vCPU/RAM share of hypervisor)

Gnocchi metrics queried (5-minute granularity):
  cpu_util                    → cpu_usage_percent  (0–100 %)
  memory.usage                → memory_usage_mb    (MB resident)
  disk.read.requests.rate     → iops_read          (req/s)
  disk.write.requests.rate    → iops_write         (req/s)
  network.incoming.bytes.rate → network_rx_mbps    (converted from bytes/s)
  network.outgoing.bytes.rate → network_tx_mbps    (converted from bytes/s)
"""

import asyncio
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger("tenant_portal.pf9_telemetry")

# ---------------------------------------------------------------------------
# Metric map — (gnocchi_metric_name, internal_field_name)
# ---------------------------------------------------------------------------
_METRIC_MAP: List[Tuple[str, str]] = [
    ("cpu_util",                    "cpu_usage_percent"),
    ("memory.usage",                "memory_usage_mb"),
    ("disk.read.requests.rate",     "iops_read"),
    ("disk.write.requests.rate",    "iops_write"),
    ("network.incoming.bytes.rate", "_rx_bytes_per_sec"),
    ("network.outgoing.bytes.rate", "_tx_bytes_per_sec"),
]

# ---------------------------------------------------------------------------
# Module-level Keystone token cache (thread-safe)
# ---------------------------------------------------------------------------
_auth_lock = threading.Lock()
_cached_token: Optional[str] = None
_cached_token_expires: float = 0.0  # time.monotonic() timestamp
_cached_gnocchi_url: Optional[str] = None


def _read_pf9_password() -> Optional[str]:
    """Read PF9 password from env var or Docker secret file."""
    val = os.getenv("PF9_PASSWORD")
    if val:
        return val
    secret_path = os.path.join(os.getenv("SECRETS_DIR", "/run/secrets"), "pf9_password")
    if os.path.isfile(secret_path):
        try:
            with open(secret_path) as fh:  # nosec B108
                v = fh.read().strip()
            if v:
                return v
        except OSError:
            pass
    return None


def _refresh_gnocchi_auth() -> Optional[Tuple[str, str]]:
    """
    Authenticate to Keystone and discover the Gnocchi (metric) endpoint.
    Returns (token, gnocchi_base_url) or None if credentials are absent or
    the Gnocchi service is not in the service catalog.
    Must be called while holding _auth_lock.
    """
    global _cached_token, _cached_token_expires, _cached_gnocchi_url

    auth_url = os.getenv("PF9_AUTH_URL", "").rstrip("/")
    username = os.getenv("PF9_USERNAME", "")
    password = _read_pf9_password() or ""
    if not (auth_url and username and password):
        return None

    try:
        payload = {
            "auth": {
                "identity": {
                    "methods": ["password"],
                    "password": {
                        "user": {
                            "name": username,
                            "domain": {"name": os.getenv("PF9_USER_DOMAIN", "Default")},
                            "password": password,
                        }
                    },
                },
                "scope": {
                    "project": {
                        "name": os.getenv("PF9_PROJECT_NAME", "service"),
                        "domain": {"name": os.getenv("PF9_PROJECT_DOMAIN", "Default")},
                    }
                },
            }
        }
        resp = httpx.post(f"{auth_url}/auth/tokens", json=payload, timeout=10.0)
        resp.raise_for_status()
        token = resp.headers["X-Subject-Token"]
        catalog = resp.json().get("token", {}).get("catalog", [])
        region = os.getenv("PF9_REGION_NAME", "region-one")

        gnocchi_url: Optional[str] = None
        for svc in catalog:
            if svc.get("type") == "metric":
                # Prefer region-matched public endpoint
                for ep in svc.get("endpoints", []):
                    if ep.get("interface") == "public" and (
                        ep.get("region_id") == region or ep.get("region") == region
                    ):
                        gnocchi_url = ep["url"].rstrip("/")
                        break
                # Fallback: any public endpoint (single-region deployments)
                if not gnocchi_url:
                    for ep in svc.get("endpoints", []):
                        if ep.get("interface") == "public":
                            gnocchi_url = ep["url"].rstrip("/")
                            break
            if gnocchi_url:
                break

        if not gnocchi_url:
            logger.debug("Gnocchi (metric) endpoint not found in Keystone service catalog")
            return None

        _cached_token = token
        _cached_token_expires = time.monotonic() + 3000  # refresh well before 1-hour expiry
        _cached_gnocchi_url = gnocchi_url
        logger.info("Platform9 Gnocchi endpoint discovered: %s", gnocchi_url)
        return token, gnocchi_url

    except Exception as exc:
        logger.debug("Gnocchi Keystone authentication failed: %s", exc)
        return None


def _get_gnocchi_auth() -> Optional[Tuple[str, str]]:
    """Return a valid (token, gnocchi_url) pair, refreshing the token if expired."""
    with _auth_lock:
        if _cached_token and time.monotonic() < _cached_token_expires and _cached_gnocchi_url:
            return _cached_token, _cached_gnocchi_url
        return _refresh_gnocchi_auth()


# ---------------------------------------------------------------------------
# Async Gnocchi query helpers
# ---------------------------------------------------------------------------

async def _fetch_latest_measure(
    client: httpx.AsyncClient,
    gnocchi_url: str,
    token: str,
    vm_uuid: str,
    metric_name: str,
    start_iso: str,
) -> Optional[float]:
    """Return the most recent Gnocchi measure value for one metric on one VM."""
    url = (
        f"{gnocchi_url}/v1/resource/instance/{vm_uuid}"
        f"/metric/{metric_name}/measures"
        f"?aggregation=mean&granularity=300&start={start_iso}"
    )
    try:
        r = await client.get(url, headers={"X-Auth-Token": token}, timeout=8.0)
        if r.status_code == 404:
            return None  # metric not collected for this VM — expected, not an error
        r.raise_for_status()
        measures = r.json()
        if measures:
            return float(measures[-1][2])  # measures = [[ts, granularity, value], ...]
    except Exception as exc:
        logger.debug("Gnocchi %s / VM %s: %s", metric_name, vm_uuid, exc)
    return None


async def _fetch_vm_all_metrics(
    client: httpx.AsyncClient,
    gnocchi_url: str,
    token: str,
    vm_uuid: str,
    ram_mb_total: Optional[int],
    start_iso: str,
) -> Dict[str, Any]:
    """Fetch all tracked Gnocchi metrics for a single VM, fully concurrently."""
    coros = [
        _fetch_latest_measure(client, gnocchi_url, token, vm_uuid, metric_name, start_iso)
        for metric_name, _ in _METRIC_MAP
    ]
    values = await asyncio.gather(*coros, return_exceptions=True)

    result: Dict[str, Any] = {}
    for (_, field), value in zip(_METRIC_MAP, values):
        result[field] = None if isinstance(value, Exception) else value

    # Convert bytes/s → MB/s for network fields
    rx_bps = result.pop("_rx_bytes_per_sec", None)
    tx_bps = result.pop("_tx_bytes_per_sec", None)
    result["network_rx_mbps"] = round(rx_bps / 1_000_000, 4) if rx_bps is not None else None
    result["network_tx_mbps"] = round(tx_bps / 1_000_000, 4) if tx_bps is not None else None

    # Derive memory_usage_percent from memory.usage (MB) / flavor RAM total
    mem_mb = result.get("memory_usage_mb")
    if mem_mb is not None and ram_mb_total and ram_mb_total > 0:
        result["memory_usage_percent"] = round(float(mem_mb) / float(ram_mb_total) * 100, 1)
    else:
        result["memory_usage_percent"] = None

    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def fetch_gnocchi_vm_metrics(
    owned_ids: List[str],
    vm_info: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """
    Fetch real-time Platform9 Gnocchi telemetry for all tenant VMs.

    Args:
        owned_ids: VM UUIDs scoped to this tenant.
        vm_info:   {vm_uuid: {"name": str, "ram_mb": int, "vcpus": int, "disk_gb": int}}

    Returns:
        Metrics-cache-compatible dict {"vms": [...], "source": "gnocchi", "timestamp": ...}
        or None when Gnocchi is not configured, unreachable, or returns all-null data
        (indicating Ceilometer/Gnocchi is not collecting for this environment).
    """
    if not owned_ids:
        return None

    auth = _get_gnocchi_auth()
    if auth is None:
        return None
    token, gnocchi_url = auth

    # Query last 10 minutes at 5-minute (300 s) granularity
    start_iso = (
        datetime.now(timezone.utc) - timedelta(minutes=10)
    ).strftime("%Y-%m-%dT%H:%M:%SZ")

    async with httpx.AsyncClient() as client:
        tasks = [
            _fetch_vm_all_metrics(
                client, gnocchi_url, token, vm_uuid,
                vm_info.get(vm_uuid, {}).get("ram_mb"),
                start_iso,
            )
            for vm_uuid in owned_ids
        ]
        raw_results = await asyncio.gather(*tasks, return_exceptions=True)

    now_iso = datetime.now(timezone.utc).isoformat()
    vms = []
    for vm_uuid, raw in zip(owned_ids, raw_results):
        if isinstance(raw, Exception):
            logger.debug("Gnocchi VM %s exception: %s", vm_uuid, raw)
            continue
        info = vm_info.get(vm_uuid, {})
        vms.append({
            "vm_id":                vm_uuid,
            "vm_name":              info.get("name", "unknown"),
            "cpu_usage_percent":    raw.get("cpu_usage_percent"),
            "memory_usage_percent": raw.get("memory_usage_percent"),
            "memory_usage_mb":      raw.get("memory_usage_mb"),
            "memory_total_mb":      info.get("ram_mb"),
            "storage_total_gb":     info.get("disk_gb"),
            "iops_read":            raw.get("iops_read"),
            "iops_write":           raw.get("iops_write"),
            "network_rx_mbps":      raw.get("network_rx_mbps"),
            "network_tx_mbps":      raw.get("network_tx_mbps"),
            "vcpus":                info.get("vcpus"),
            "last_updated":         now_iso,
        })

    if not vms:
        logger.debug("Gnocchi: no data returned for any of %d VMs", len(owned_ids))
        return None

    # Only use Gnocchi data when at least one VM has real metric values.
    # All-null indicates Ceilometer isn't actively collecting for this environment.
    has_real_data = any(
        v.get("cpu_usage_percent") is not None or v.get("memory_usage_percent") is not None
        for v in vms
    )
    if not has_real_data:
        logger.debug("Gnocchi returned all-null metrics — falling back to DB allocation")
        return None

    logger.info("Gnocchi: real telemetry fetched for %d / %d VMs", len(vms), len(owned_ids))
    return {
        "vms": vms,
        "timestamp": now_iso,
        "source": "gnocchi",
    }
