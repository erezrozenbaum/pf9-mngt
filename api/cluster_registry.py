"""
api/cluster_registry.py — Registry of all configured PF9 control planes and regions.

Replaces the global singleton get_client() pattern with a two-level registry:

  ControlPlane  — one per PF9 installation (one Keystone endpoint)
  Region        — one per OpenStack region within a control plane (one Pf9Client)

Backward compatible:
  * get_client() in pf9_control.py is preserved as a shim that calls
    get_registry().get_default_region().
  * All existing single-region deployments work unchanged.

Synchronous by design — matches db_pool.py (psycopg2 ThreadedConnectionPool).
Do NOT convert to async without also converting db_pool.

MultiClusterQuery:
  Runs Pf9Client method calls against multiple regions in parallel using
  asyncio + run_in_executor (thread pool), since Pf9Client uses synchronous
  requests. Returns {"results": [...], "errors": [...]} so partial failures
  are visible to callers, never silently discarded.
"""

import asyncio
import logging
import os
import threading
from typing import Callable, Dict, List, Optional

from fastapi import HTTPException
from psycopg2.extras import RealDictCursor

from db_pool import get_connection
from pf9_control import Pf9Client
from secret_helper import read_secret

logger = logging.getLogger("pf9.cluster_registry")


# ---------------------------------------------------------------------------
# ClusterRegistry
# ---------------------------------------------------------------------------

class ClusterRegistry:
    """
    Two-level registry: control planes → regions.

    - Keystone calls (domains, projects, users) → get_control_plane()
    - Compute / network / storage calls         → get_region()
    - Default region (backward compat)          → get_default_region()

    Thread-safe: _lock guards writes; reads are safe after initialize().
    The registry is a process singleton — use get_registry() to obtain it.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._regions: Dict[str, Pf9Client] = {}          # region_id → client
        self._region_configs: Dict[str, dict] = {}        # region_id → DB row
        self._control_planes: Dict[str, Pf9Client] = {}   # control_plane_id → client
        self._initialized = False

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """
        Load all enabled control planes and regions from the DB and build
        Pf9Client instances for each. Idempotent — safe to call multiple times.

        Falls back to an env-var client if the DB has no rows yet (first-run
        safety net so startup never leaves the system with zero configured clients).
        """
        with self._lock:
            if self._initialized:
                return
            self._load_from_db()
            if not self._regions:
                logger.warning(
                    "ClusterRegistry: no regions found in DB — using env-var fallback"
                )
                self._bootstrap_from_env()
            self._initialized = True
            logger.info(
                "ClusterRegistry initialized: %d region(s), %d control plane(s)",
                len(self._regions),
                len(self._control_planes),
            )

    def _load_from_db(self) -> None:
        """Query pf9_regions JOIN pf9_control_planes and build one Pf9Client per row."""
        try:
            with get_connection() as conn:
                with conn.cursor(cursor_factory=RealDictCursor) as cur:
                    cur.execute(
                        """
                        SELECT
                            r.id              AS region_id,
                            r.region_name,
                            r.display_name,
                            r.is_default,
                            r.priority,
                            r.latency_threshold_ms,
                            cp.id             AS control_plane_id,
                            cp.auth_url,
                            cp.username,
                            cp.password_enc,
                            cp.user_domain,
                            cp.project_name,
                            cp.project_domain
                        FROM pf9_regions r
                        JOIN pf9_control_planes cp ON cp.id = r.control_plane_id
                        WHERE r.is_enabled = TRUE AND cp.is_enabled = TRUE
                        ORDER BY r.priority ASC, r.id ASC
                        """
                    )
                    rows = cur.fetchall()

            for row in rows:
                password = self._resolve_password(row)
                region_client = Pf9Client(
                    auth_url=row["auth_url"],
                    username=row["username"],
                    password=password,
                    user_domain=row["user_domain"],
                    project_name=row["project_name"],
                    project_domain=row["project_domain"],
                    region_name=row["region_name"],
                    region_id=row["region_id"],
                )
                self._regions[row["region_id"]] = region_client
                self._region_configs[row["region_id"]] = dict(row)

                # One control-plane client per distinct control_plane_id.
                # Uses the same credentials but is conceptually scoped to Keystone
                # rather than a specific region's compute/network/storage endpoints.
                cp_id = row["control_plane_id"]
                if cp_id not in self._control_planes:
                    cp_client = Pf9Client(
                        auth_url=row["auth_url"],
                        username=row["username"],
                        password=password,
                        user_domain=row["user_domain"],
                        project_name=row["project_name"],
                        project_domain=row["project_domain"],
                        region_name=row["region_name"],
                        region_id=cp_id,
                    )
                    self._control_planes[cp_id] = cp_client

            logger.debug(
                "ClusterRegistry._load_from_db: loaded %d region row(s)", len(rows)
            )

        except Exception as exc:
            # Non-fatal — caller falls back to env-var bootstrap
            logger.error("ClusterRegistry: DB load failed: %s", exc)

    def _resolve_password(self, row: dict) -> str:
        """
        Resolve the stored password_enc value to a plaintext password.

        Storage prefix conventions:
          "env:<name>"    → read from Docker secret file / env var (default cluster)
          "fernet:<blob>" → Fernet-encrypted using JWT_SECRET key (admin-added clusters)
          anything else   → treated as plaintext with a warning (legacy/unknown)
        """
        enc = (row.get("password_enc") or "").strip()

        if enc.startswith("env:"):
            return read_secret("pf9_password", env_var="PF9_PASSWORD", default="")

        if enc.startswith("fernet:"):
            return self._fernet_decrypt(enc[7:], row.get("control_plane_id", "unknown"))

        # Unknown/legacy format — log warning and fall back to env-var password
        logger.warning(
            "password_enc for control_plane '%s' has unrecognized prefix — "
            "treating as plaintext. Expected 'env:' or 'fernet:' prefix.",
            row.get("control_plane_id"),
        )
        return enc if enc else read_secret("pf9_password", env_var="PF9_PASSWORD", default="")

    @staticmethod
    def _fernet_decrypt(ciphertext: str, cp_id: str) -> str:
        """Decrypt a Fernet-encrypted password (key = SHA-256 of JWT_SECRET)."""
        try:
            import base64 as _b64
            import hashlib as _hl
            from cryptography.fernet import Fernet, InvalidToken
            secret = os.getenv("JWT_SECRET", "") or os.getenv("JWT_SECRET_KEY", "")
            if not secret:
                raise RuntimeError("JWT_SECRET / JWT_SECRET_KEY is not set")
            key = _b64.urlsafe_b64encode(_hl.sha256(secret.encode()).digest())
            return Fernet(key).decrypt(ciphertext.encode()).decode()
        except ImportError:
            logger.error(
                "Cannot decrypt password for control_plane '%s': "
                "cryptography library not installed (pip install cryptography)",
                cp_id,
            )
            return ""
        except Exception as exc:
            logger.error(
                "Failed to decrypt password for control_plane '%s': %s — "
                "JWT_SECRET may have changed since the credential was stored.",
                cp_id, exc,
            )
            return ""

    def _bootstrap_from_env(self) -> None:
        """
        Emergency fallback: build a single client from env vars.
        Identical to the old get_client() behavior — ensures zero-downtime
        when the registry is used before the DB is seeded.
        """
        try:
            client = Pf9Client.from_env()
            self._regions["default"] = client
            self._control_planes["default"] = client
            self._region_configs["default"] = {
                "is_default": True,
                "priority": 100,
                "region_id": "default",
                "control_plane_id": "default",
                "region_name": os.getenv("PF9_REGION_NAME", "region-one"),
                "display_name": "Default Region",
            }
            logger.info("ClusterRegistry: bootstrapped from env vars (fallback mode)")
        except Exception as exc:
            logger.error("ClusterRegistry: env-var bootstrap failed: %s", exc)

    # ------------------------------------------------------------------
    # Client accessors
    # ------------------------------------------------------------------

    def get_region(self, region_id: str) -> Pf9Client:
        """Return a region-scoped Pf9Client (Nova / Neutron / Cinder / Glance calls)."""
        self._ensure_initialized()
        client = self._regions.get(region_id)
        if client is None:
            raise HTTPException(
                status_code=404,
                detail=f"Region '{region_id}' not found or not enabled",
            )
        return client

    def get_control_plane(self, control_plane_id: str) -> Pf9Client:
        """Return a control-plane-scoped Pf9Client (Keystone identity calls)."""
        self._ensure_initialized()
        client = self._control_planes.get(control_plane_id)
        if client is None:
            raise HTTPException(
                status_code=404,
                detail=f"Control plane '{control_plane_id}' not found or not enabled",
            )
        return client

    def get_default_region(self) -> Pf9Client:
        """
        Return the default region client.
        Preserves all existing single-cluster behavior for the 100+ get_client() callers.
        """
        self._ensure_initialized()
        # Prefer the row marked is_default in DB
        for rid, cfg in self._region_configs.items():
            if cfg.get("is_default"):
                return self._regions[rid]
        # Fall back to first entry (sorted by priority ASC at load time)
        if self._regions:
            return next(iter(self._regions.values()))
        raise HTTPException(
            status_code=503,
            detail="No Platform9 regions are configured or reachable",
        )

    def get_default_control_plane(self) -> Pf9Client:
        """Return the default control-plane client (for Keystone identity calls)."""
        self._ensure_initialized()
        if self._control_planes:
            return next(iter(self._control_planes.values()))
        raise HTTPException(
            status_code=503,
            detail="No Platform9 control planes are configured",
        )

    def get_all_enabled_regions(self) -> List[Pf9Client]:
        """Return all enabled region clients in priority order."""
        self._ensure_initialized()
        return list(self._regions.values())

    def get_region_config(self, region_id: str) -> dict:
        """Return the raw DB config row for a region (latency_threshold_ms, priority, etc.)."""
        return self._region_configs.get(region_id, {})

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def reload(self) -> None:
        """
        Discard all cached clients and re-read from the DB.
        Call this after Phase 4 admin CRUD modifies pf9_control_planes / pf9_regions.
        """
        with self._lock:
            self._regions.clear()
            self._control_planes.clear()
            self._region_configs.clear()
            self._initialized = False
        self.initialize()
        logger.info("ClusterRegistry reloaded")

    def shutdown(self) -> None:
        """
        Close the underlying requests.Session for every registered client.
        Called from FastAPI shutdown_event so connections are released cleanly.
        Each client owns one Session (created in Pf9Client.__init__) that is
        reused for all HTTP calls — this is where we close it.
        """
        with self._lock:
            # Deduplicate clients (a control-plane client may share identity with
            # a region client when only the default cluster exists)
            seen: set = set()
            all_clients = list(self._regions.values()) + list(self._control_planes.values())
            for client in all_clients:
                cid = id(client)
                if cid in seen:
                    continue
                seen.add(cid)
                try:
                    client.session.close()
                except Exception as exc:
                    logger.debug(
                        "ClusterRegistry.shutdown: error closing session for %s: %s",
                        client.region_id,
                        exc,
                    )
        logger.info("ClusterRegistry: %d client session(s) closed", len(seen))

    def _ensure_initialized(self) -> None:
        """Auto-initialize on first accessor call (safe for use before startup_event)."""
        if not self._initialized:
            self.initialize()


# ---------------------------------------------------------------------------
# Module-level singleton — one registry per process
# ---------------------------------------------------------------------------

_registry: Optional[ClusterRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> ClusterRegistry:
    """
    Return the process-level ClusterRegistry singleton.

    Auto-initializes on first call.  It is safe to call this before
    startup_event fires — the registry will build itself from the DB
    (or fall back to env vars) on demand.
    """
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ClusterRegistry()
                _registry.initialize()
    return _registry


# ---------------------------------------------------------------------------
# FastAPI dependency helpers
# ---------------------------------------------------------------------------

def get_region_client(
    region_id: Optional[str] = None,
) -> Pf9Client:
    """
    FastAPI dependency: returns a region-scoped Pf9Client.

    Usage:
        @router.get("/servers")
        async def list_servers(client: Pf9Client = Depends(get_region_client)):
            ...
    """
    registry = get_registry()
    return registry.get_region(region_id) if region_id else registry.get_default_region()


def get_keystone_client(
    control_plane_id: Optional[str] = None,
) -> Pf9Client:
    """
    FastAPI dependency: returns a control-plane-scoped Pf9Client (Keystone calls).

    Usage:
        @router.get("/domains")
        async def list_domains(client: Pf9Client = Depends(get_keystone_client)):
            ...
    """
    registry = get_registry()
    return (
        registry.get_control_plane(control_plane_id)
        if control_plane_id
        else registry.get_default_control_plane()
    )


# ---------------------------------------------------------------------------
# MultiClusterQuery — parallel fan-out across regions
# ---------------------------------------------------------------------------

class MultiClusterQuery:
    """
    Runs a Pf9Client method call across multiple regions in parallel.

    Because Pf9Client uses synchronous requests, parallelism is achieved via
    asyncio + run_in_executor (thread pool) — not native async calls.

    Concurrency is bounded by MAX_PARALLEL_REGIONS (default 3) to prevent
    connection explosion against PF9 endpoints.  Each call is wrapped in
    asyncio.wait_for(timeout=REGION_REQUEST_TIMEOUT_SEC) so a slow or
    unreachable region cannot hold a semaphore slot indefinitely.

    Returns {"results": [...], "errors": [...]} so callers always know which
    regions succeeded and which failed — partial failures are never silently
    discarded.

    Usage:
        result = await MultiClusterQuery(registry).gather("list_servers")
        # → {"results": [{"region_id": "...", "data": [...]}, ...],
        #    "errors":  [{"region_id": "...", "error": "..."}, ...]}

        result = await MultiClusterQuery(registry).gather_and_merge(
            "list_servers", merge_flat
        )
    """

    def __init__(
        self,
        registry: ClusterRegistry,
        region_ids: Optional[List[str]] = None,
    ) -> None:
        if region_ids:
            self.regions = [registry.get_region(rid) for rid in region_ids]
        else:
            self.regions = registry.get_all_enabled_regions()
        self._registry = registry

    async def gather(self, fn_name: str, *args, **kwargs) -> dict:
        """
        Call fn_name(*args, **kwargs) on every region concurrently.

        Concurrency cap:   MAX_PARALLEL_REGIONS env var (default 3)
        Per-region timeout: REGION_REQUEST_TIMEOUT_SEC env var (default 30)
        """
        max_parallel = int(os.getenv("MAX_PARALLEL_REGIONS", "3"))
        timeout_sec = int(os.getenv("REGION_REQUEST_TIMEOUT_SEC", "30"))
        semaphore = asyncio.Semaphore(max_parallel)
        loop = asyncio.get_event_loop()

        async def call_one(region: Pf9Client) -> dict:
            async with semaphore:
                try:
                    # run_in_executor dispatches the sync call to a thread pool worker.
                    # wait_for enforces the hard timeout — without this, a hung region
                    # would hold its semaphore slot until the OS TCP timeout fires (often
                    # several minutes), starving all other regions.
                    data = await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda r=region: getattr(r, fn_name)(*args, **kwargs),
                        ),
                        timeout=timeout_sec,
                    )
                    return {"region_id": region.region_id, "data": data}
                except asyncio.TimeoutError:
                    logger.warning(
                        "MultiClusterQuery: region '%s' timed out after %ds calling %s",
                        region.region_id,
                        timeout_sec,
                        fn_name,
                    )
                    raise
                except Exception as exc:
                    logger.warning(
                        "MultiClusterQuery: region '%s' failed calling %s: %s",
                        region.region_id,
                        fn_name,
                        exc,
                    )
                    raise

        tasks = [asyncio.ensure_future(call_one(r)) for r in self.regions]
        raw = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        errors = []
        for i, r in enumerate(raw):
            if isinstance(r, Exception):
                errors.append({
                    "region_id": self.regions[i].region_id,
                    "error": str(r),
                })
            else:
                results.append(r)

        return {"results": results, "errors": errors}

    async def gather_and_merge(
        self,
        fn_name: str,
        merge_fn: Callable[[List[dict]], List[dict]],
        *args,
        **kwargs,
    ) -> dict:
        """
        Call gather() then apply merge_fn to the successful results.
        merge_fn is responsible for flattening, tagging, deduplication, or sorting.
        Errors are preserved unchanged — callers always see which regions failed.
        """
        raw = await self.gather(fn_name, *args, **kwargs)
        if raw["results"]:
            raw["results"] = merge_fn(raw["results"])
        return raw


# ---------------------------------------------------------------------------
# Standard merge functions — used by api routes in Phase 6
# ---------------------------------------------------------------------------

def merge_flat(results: List[dict]) -> List[dict]:
    """Flatten per-region lists into a single list, tagging each item with _region_id."""
    merged = []
    for r in results:
        for item in r["data"]:
            item["_region_id"] = r["region_id"]
            merged.append(item)
    return merged


def merge_aggregate(results: List[dict], key: str = "count") -> dict:
    """Sum a numeric key across all regions — useful for dashboard totals."""
    return {
        "total": sum(r["data"].get(key, 0) for r in results),
        "by_region": {r["region_id"]: r["data"].get(key, 0) for r in results},
    }
