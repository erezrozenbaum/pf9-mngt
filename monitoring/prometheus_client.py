import asyncio
import aiohttp
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging
from urllib.parse import urljoin

from models import VMMetrics, HostMetrics

logger = logging.getLogger(__name__)

# NIC prefixes to exclude when summing host network throughput.
# Matches the exclusion list in host_metrics_collector.py.
_EXCL_NIC_PREFIXES = (
    'lo', 'virbr', 'tap', 'vnet', 'veth', 'br-', 'docker',
    'ovs', 'dummy', 'tunl', 'tun', 'sit', 'gre', 'flannel',
    'cali', 'cilium', 'weave',
)


class PrometheusClient:
    """Client for collecting metrics from PF9 KVM host Prometheus endpoints.

    Scrapes:
      - libvirt-exporter on port 9177  →  per-VM metrics
      - node-exporter   on port 9388  →  per-host metrics
    """

    def __init__(self, hosts: List[str], cache_ttl: int = 60):
        self.hosts = hosts
        self.cache_ttl = cache_ttl
        self.vm_cache = {}
        self.host_cache = {}
        self.last_update = None
        self.session = None
        self.collection_task = None

        # PCD metric endpoints
        self.libvirt_port = 9177
        self.node_exporter_port = 9388

        # Per-domain and per-host CPU counters for delta-based CPU calculation.
        # Keys: domain_id (for VMs) or '__host_<ip>' (for hosts).
        self._prev_cpu_totals: dict = {}

        # SSH configuration for direct virsh-based VM metrics collection.
        # Used when libvirt-exporter (port 9177) is not deployed on hypervisors.
        self.ssh_user = os.getenv('PF9_SSH_USER', 'root')
        self.ssh_key_file = os.getenv('PF9_SSH_KEY_FILE', '')

    async def start_collection(self):
        """Start background metrics collection"""
        self.session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=30)
        )
        self.collection_task = asyncio.create_task(self._collection_loop())
        logger.info(f"Started metrics collection for {len(self.hosts)} hosts")

    async def stop_collection(self):
        """Stop background collection and cleanup"""
        if self.collection_task:
            self.collection_task.cancel()
            try:
                await self.collection_task
            except asyncio.CancelledError:
                pass

        if self.session:
            await self.session.close()

    async def _collection_loop(self):
        """Background loop to collect metrics periodically"""
        while True:
            try:
                await self._collect_all_metrics()
                await asyncio.sleep(self.cache_ttl)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in collection loop: {e}")
                await asyncio.sleep(5)  # Short retry delay

    async def _collect_all_metrics(self):
        """Collect metrics from all hosts"""
        tasks = []
        for host in self.hosts:
            tasks.append(self._collect_host_metrics(host))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        vm_metrics = []
        host_metrics = []

        for host, result in zip(self.hosts, results):
            if isinstance(result, Exception):
                logger.error(f"Failed to collect from {host}: {result}")
                continue

            host_vm_metrics, host_host_metrics = result
            vm_metrics.extend(host_vm_metrics)
            host_metrics.extend(host_host_metrics)

        # Update in-memory cache
        self.vm_cache = {vm.vm_id: vm for vm in vm_metrics}
        self.host_cache = {host.hostname: host for host in host_metrics}
        self.last_update = datetime.utcnow()

        # Persist to disk so the API endpoints can serve the collected data.
        # Only write if we collected something — do NOT overwrite a good cache
        # with empty results from a failed collection cycle.
        if not vm_metrics and not host_metrics:
            logger.warning("No metrics collected this cycle; skipping cache update to preserve existing data")
            return

        try:
            import os, json as _json
            # Serialize VM list; Pydantic .dict() omits @property values so we add them manually
            vm_list = []
            for _vm in vm_metrics:
                _d = _vm.dict()
                _d['storage_usage_percent'] = _vm.storage_usage_percent
                _d['memory_allocation_percent'] = _vm.memory_allocation_percent
                vm_list.append(_d)
            host_list = []
            for _h in host_metrics:
                _d = _h.dict()
                _d['memory_usage_percent'] = _h.memory_usage_percent
                _d['storage_usage_percent'] = _h.storage_usage_percent
                host_list.append(_d)

            # Serialize datetime objects
            def _default(obj):
                if isinstance(obj, datetime):
                    return obj.isoformat()
                raise TypeError(f"Object of type {type(obj)} is not JSON serializable")

            # Compute summary averages (frontend reads vm_stats.avg_cpu / avg_memory)
            _vm_cpus = [d['cpu_usage_percent'] for d in vm_list if d.get('cpu_usage_percent') is not None]
            _vm_mems = [d['memory_usage_percent'] for d in vm_list if d.get('memory_usage_percent') is not None]
            _h_cpus  = [d['cpu_usage_percent'] for d in host_list if d.get('cpu_usage_percent') is not None]
            _h_mem_pcts = [
                d['memory_used_mb'] / d['memory_total_mb'] * 100
                for d in host_list
                if d.get('memory_used_mb') is not None and d.get('memory_total_mb')
            ]
            cache_payload = {
                "vms": vm_list,
                "hosts": host_list,
                "alerts": [],
                "summary": {
                    "total_vms": len(vm_list),
                    "total_hosts": len(host_list),
                    "vm_stats": {
                        "avg_cpu":    round(sum(_vm_cpus) / len(_vm_cpus), 1) if _vm_cpus else 0.0,
                        "max_cpu":    round(max(_vm_cpus), 1) if _vm_cpus else 0.0,
                        "avg_memory": round(sum(_vm_mems) / len(_vm_mems), 1) if _vm_mems else 0.0,
                        "max_memory": round(max(_vm_mems), 1) if _vm_mems else 0.0,
                    },
                    "host_stats": {
                        "avg_cpu":    round(sum(_h_cpus) / len(_h_cpus), 1) if _h_cpus else 0.0,
                        "max_cpu":    round(max(_h_cpus), 1) if _h_cpus else 0.0,
                        "avg_memory": round(sum(_h_mem_pcts) / len(_h_mem_pcts), 1) if _h_mem_pcts else 0.0,
                        "max_memory": round(max(_h_mem_pcts), 1) if _h_mem_pcts else 0.0,
                    },
                    "last_update": self.last_update.isoformat(),
                },
                "timestamp": self.last_update.isoformat(),
                "source": "monitoring",
            }
            os.makedirs("/tmp/cache", exist_ok=True)  # nosec B108 — fixed Docker volume path
            tmp_path = "/tmp/cache/metrics_cache.json.tmp"  # nosec B108
            with open(tmp_path, "w") as fh:
                _json.dump(cache_payload, fh, default=_default)
            os.replace(tmp_path, "/tmp/cache/metrics_cache.json")  # nosec B108
        except Exception as exc:
            logger.error(f"Failed to write metrics cache to disk: {exc}")

        logger.info(f"Updated cache: {len(vm_metrics)} VMs, {len(host_metrics)} hosts")

    async def _collect_host_metrics(self, host: str) -> tuple:
        """Collect metrics from a single host (libvirt + node-exporter)."""
        vm_metrics: List[VMMetrics] = []
        host_metrics: List[HostMetrics] = []

        # VM metrics collection strategy:
        #  1. SSH + virsh (direct libvirt on hypervisor) — primary when SSH key configured
        #  2. libvirt-exporter HTTP endpoint (port 9177) — used if SSH not configured
        #  In both cases the other method is tried as a fallback.
        if self._ssh_key_configured():
            try:
                vm_metrics = await self._collect_vm_metrics_virsh_ssh(host)
                logger.info(f"Collected {len(vm_metrics)} VM metrics via SSH virsh from {host}")
            except Exception as e:
                logger.warning(f"SSH virsh collection failed for {host}: {e}; trying libvirt-exporter")
                try:
                    vm_text = await self._scrape_raw(host, self.libvirt_port)
                    vm_metrics = self._parse_vm_metrics_libvirt(vm_text, host)
                except Exception as e2:
                    logger.warning(f"VM metrics unavailable for {host} (both methods failed): {e2}")
        else:
            try:
                vm_text = await self._scrape_raw(host, self.libvirt_port)
                vm_metrics = self._parse_vm_metrics_libvirt(vm_text, host)
            except Exception as e:
                logger.warning(
                    f"VM metrics via libvirt-exporter unavailable for {host}:{self.libvirt_port}: {e}. "
                    f"Set PF9_SSH_KEY_FILE to enable direct virsh collection."
                )
                try:
                    vm_metrics = await self._collect_vm_metrics_virsh_ssh(host)
                except Exception as e2:
                    logger.warning(f"SSH virsh fallback also failed for {host}: {e2}")

        # Host metrics from node exporter ————————————————————————————————
        try:
            node_text = await self._scrape_raw(host, self.node_exporter_port)
            host_metric = self._parse_host_metrics_node(node_text, host)
            if host_metric:
                host_metrics = [host_metric]
        except Exception as e:
            logger.warning(f"Host metrics unavailable for {host}:{self.node_exporter_port}: {e}")

        return vm_metrics, host_metrics

    # ------------------------------------------------------------------ #
    # SSH virsh direct collection (primary when PF9_SSH_KEY_FILE is set) #
    # ------------------------------------------------------------------ #

    def _ssh_key_configured(self) -> bool:
        """Return True when an SSH private key file is configured and readable."""
        return bool(self.ssh_key_file and os.path.exists(self.ssh_key_file))

    async def _collect_vm_metrics_virsh_ssh(self, host: str) -> List[VMMetrics]:
        """SSH into a hypervisor and collect per-VM metrics via virsh domstats.

        This is the authoritative real-time collection path when
        libvirt-exporter is not deployed on the hypervisor node.
        Requires PF9_SSH_KEY_FILE (path to an SSH private key readable by the
        monitoring container) and PF9_SSH_USER (default: root).

        Runs a single SSH session and two commands:
          1. ``virsh domstats --raw --state-running``  — CPU/net/block/balloon
          2. ``virsh list --state-running --name``     — confirm running list
        """
        try:
            import asyncssh  # optional dependency; imported lazily
        except ImportError:
            raise RuntimeError(
                "asyncssh is not installed. Add it to monitoring/requirements.txt "
                "to enable direct virsh collection."
            )

        if not self._ssh_key_configured():
            raise RuntimeError(
                f"SSH key not found at '{self.ssh_key_file}' (PF9_SSH_KEY_FILE)"
            )

        connect_opts = dict(
            username=self.ssh_user,
            client_keys=[self.ssh_key_file],
            known_hosts=None,   # nosec B106 — hypervisor IPs are admin-configured
            connect_timeout=10,
        )

        async with asyncssh.connect(host, **connect_opts) as conn:
            result = await conn.run(
                'virsh domstats --raw --state-running 2>/dev/null',
                timeout=30,
            )
        raw_output = result.stdout or ''
        if not raw_output.strip():
            logger.info(f"No running VMs reported by virsh on {host}")
            return []
        return self._parse_virsh_domstats(raw_output, host, datetime.utcnow())

    def _parse_virsh_domstats(
        self, text: str, host: str, now: datetime
    ) -> List[VMMetrics]:
        """Parse ``virsh domstats --raw --state-running`` output into VMMetrics.

        Key data extracted per domain
        ──────────────────────────────
        CPU    : cpu.time (nanoseconds, cumulative) + vcpu.current
        Memory : balloon.maximum / balloon.rss / balloon.unused / balloon.current
                 (all in KiB; rss is most accurate when balloon driver active)
        Network: net.N.rx.bytes / net.N.tx.bytes (cumulative, bytes)
        Storage: block.N.capacity / block.N.allocation / block.N.physical (bytes)
                 block.N.path  →  extract OpenStack instance UUID
        """
        import re

        # ---- split output into per-domain blocks ----
        blocks: List[tuple] = []   # [(domain_name, {key: val})]
        cur_name: Optional[str] = None
        cur_raw: dict = {}

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("Domain: '") and line.endswith("'"):
                if cur_name is not None:
                    blocks.append((cur_name, cur_raw))
                cur_name = line[9:-1]
                cur_raw = {}
            elif cur_name is not None and '=' in line:
                key, _, val = line.partition('=')
                cur_raw[key.strip()] = val.strip()

        if cur_name is not None:
            blocks.append((cur_name, cur_raw))

        vm_list: List[VMMetrics] = []

        for domain_name, raw in blocks:
            # Only process running (state 1) or paused (state 3) domains
            state = raw.get('state.state', '1')
            if state not in ('1', '2', '3', '4'):   # 1=running,2=blocked,3=paused,4=shutdown
                continue

            # ---- UUID from block device paths (OpenStack nova convention) ----
            vm_id = domain_name
            block_count = int(raw.get('block.count', 0) or 0)
            block_cap_total = 0.0
            block_alloc_total = 0.0
            block_phys_total = 0.0

            for i in range(block_count):
                path = raw.get(f'block.{i}.path', '') or ''
                if path and vm_id == domain_name:
                    # Nova stores disks under /var/lib/nova/instances/<UUID>/…
                    m = re.search(
                        r'([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})',
                        path, re.I,
                    )
                    if m:
                        vm_id = m.group(1).lower()
                cap   = float(raw.get(f'block.{i}.capacity',   0) or 0)
                alloc = float(raw.get(f'block.{i}.allocation', 0) or 0)
                phys  = float(raw.get(f'block.{i}.physical',   0) or 0)
                block_cap_total   += cap
                block_alloc_total += alloc
                # Physical size = actual bytes on disk for thin-provisioned images
                block_phys_total  += phys if phys > 0 else alloc

            # ---- Network (cumulative byte counters) ----
            net_count = int(raw.get('net.count', 0) or 0)
            net_rx = 0.0
            net_tx = 0.0
            for i in range(net_count):
                net_rx += float(raw.get(f'net.{i}.rx.bytes', 0) or 0)
                net_tx += float(raw.get(f'net.{i}.tx.bytes', 0) or 0)

            # ---- CPU (delta-based %) ----
            cpu_time_ns = float(raw.get('cpu.time', 0) or 0)
            vcpu_count  = int(raw.get('vcpu.current', 1) or 1)

            cpu_pct = 0.0
            prev = self._prev_cpu_totals.get(vm_id)
            if prev and cpu_time_ns > 0 and 'cpu_time_ns' in prev:
                delta_ns   = cpu_time_ns - prev['cpu_time_ns']
                delta_wall = (now - prev['ts']).total_seconds()
                if delta_wall > 0 and delta_ns >= 0:
                    # cpu.time is total nanoseconds across all vCPUs
                    cpu_pct = round(
                        min(delta_ns / (delta_wall * vcpu_count * 1e9) * 100, 100), 1
                    )
            if cpu_time_ns > 0:
                self._prev_cpu_totals[vm_id] = {'cpu_time_ns': cpu_time_ns, 'ts': now}

            # ---- Memory (virsh reports in KiB) ----
            mem_max_kib  = float(raw.get('balloon.maximum', 0) or 0)
            mem_rss_kib  = float(raw.get('balloon.rss',     0) or 0)
            mem_cur_kib  = float(raw.get('balloon.current', 0) or 0)
            mem_unused_kib = float(raw.get('balloon.unused', 0) or 0)

            mem_total_mb = round(mem_max_kib / 1024, 1) if mem_max_kib else None

            # Best estimate: RSS (balloon driver) > current-unused > current
            if mem_rss_kib > 0:
                mem_used_mb = round(mem_rss_kib / 1024, 1)
            elif mem_unused_kib > 0 and mem_cur_kib > 0:
                mem_used_mb = round(max(mem_cur_kib - mem_unused_kib, 0) / 1024, 1)
            elif mem_cur_kib > 0:
                mem_used_mb = round(mem_cur_kib / 1024, 1)
            else:
                mem_used_mb = None

            mem_pct: Optional[float] = None
            if mem_total_mb and mem_used_mb:
                mem_pct = round(mem_used_mb / mem_total_mb * 100, 1)

            # ---- Storage ----
            storage_total_gb = (
                round(block_cap_total   / (1024 ** 3), 1) if block_cap_total   else None
            )
            storage_used_gb  = (
                round(block_phys_total  / (1024 ** 3), 1) if block_cap_total   else None
            )
            storage_alloc_gb = (
                round(block_alloc_total / (1024 ** 3), 1) if block_alloc_total else None
            )

            try:
                vm_list.append(VMMetrics(
                    vm_id=vm_id,
                    vm_name=domain_name,
                    host=host,
                    timestamp=now,
                    cpu_usage_percent=cpu_pct,
                    cpu_total=float(vcpu_count),
                    memory_total_mb=mem_total_mb,
                    memory_used_mb=mem_used_mb,
                    memory_usage_percent=mem_pct,
                    network_rx_bytes=net_rx if net_rx > 0 else None,
                    network_tx_bytes=net_tx if net_tx > 0 else None,
                    storage_total_gb=storage_total_gb,
                    storage_used_gb=storage_used_gb,
                    storage_allocated_gb=storage_alloc_gb,
                ))
            except Exception as exc:
                logger.warning(f"Skipping VM {domain_name} ({vm_id}): {exc}")

        return vm_list

    # ------------------------------------------------------------------ #
    # Low-level scraping                                                   #
    # ------------------------------------------------------------------ #

    async def _scrape_raw(self, host: str, port: int) -> str:
        """Return raw Prometheus text from an endpoint."""
        url = f"http://{host}:{port}/metrics"
        async with self.session.get(url) as response:
            if response.status != 200:
                raise Exception(f"HTTP {response.status} from {url}")
            return await response.text()

    def _extract_label(self, line: str, key: str) -> Optional[str]:
        """Extract a label value from a Prometheus metric line."""
        search = f'{key}="'
        idx = line.find(search)
        if idx < 0:
            return None
        start = idx + len(search)
        end = line.find('"', start)
        return line[start:end] if end > start else None

    # ------------------------------------------------------------------ #
    # libvirt-exporter parser (port 9177)                                  #
    # ------------------------------------------------------------------ #

    def _parse_vm_metrics_libvirt(self, text: str, host: str) -> List[VMMetrics]:
        """Parse libvirt-exporter Prometheus text into VMMetrics objects.

        Handles the actual ``libvirt_domain_*`` metric family produced by
        libvirt-exporter.  Replaces the old stub that expected ``pcd:vm_*``
        metrics which never existed in this environment.
        """
        lines = text.strip().split('\n')
        vms: Dict[str, dict] = {}
        now = datetime.utcnow()

        # ——— First pass: discover active VMs from metadata metric ———————
        for line in lines:
            if 'libvirt_domain_info_meta{' not in line:
                continue
            try:
                val_str = line.rsplit(' ', 1)[-1]
                if float(val_str) != 1:
                    continue  # only active (value=1) domains
            except (ValueError, IndexError):
                continue

            domain = self._extract_label(line, 'domain')
            if not domain:
                continue

            vm_name = self._extract_label(line, 'instance_name') or domain[:12]
            project_name = self._extract_label(line, 'project_name') or 'Unknown'
            user_name = self._extract_label(line, 'user_name') or 'Unknown'
            domain_name = user_name.split('@')[1] if '@' in user_name else 'Unknown'

            vms[domain] = {
                'vm_id': domain,
                'vm_name': vm_name,
                'host': host,
                'timestamp': now,
                # OpenStack metadata extracted from libvirt exporter labels
                'project_name': project_name if project_name != 'Unknown' else None,
                'user_name': user_name if user_name != 'Unknown' else None,
                'domain': domain_name if domain_name != 'Unknown' else None,
                # raw accumulators (stripped before VMMetrics construction)
                '_vcpu_time': 0.0,
                '_vcpu_count': 1,
                '_block_cap': {},
                '_block_alloc': {},
                '_block_phys': {},
                # zero-initialised payload fields
                'network_rx_bytes': 0.0,
                'network_tx_bytes': 0.0,
                'memory_total_mb': None,
                'memory_used_mb': None,
                'memory_usage_percent': None,
                'cpu_usage_percent': 0.0,
                'cpu_total': 1,
            }

        if not vms:
            return []

        # ——— Second pass: populate metrics ——————————————————————————————
        for line in lines:
            if line.startswith('#') or not line.strip():
                continue
            if 'domain="' not in line:
                continue

            domain = self._extract_label(line, 'domain')
            if not domain or domain not in vms:
                continue

            try:
                value = float(line.rsplit(' ', 1)[-1])
            except (ValueError, IndexError):
                continue

            if 'libvirt_domain_vcpu_time_seconds_total{' in line:
                vms[domain]['_vcpu_time'] += value
            elif 'libvirt_domain_info_virtual_cpus{' in line:
                vms[domain]['_vcpu_count'] = int(value) or 1
            elif 'libvirt_domain_info_memory_usage_bytes{' in line:
                vms[domain]['memory_used_mb'] = round(value / (1024 * 1024), 1)
            elif 'libvirt_domain_info_maximum_memory_bytes{' in line:
                vms[domain]['memory_total_mb'] = round(value / (1024 * 1024), 1)
            elif 'libvirt_domain_memory_stats_used_percent{' in line:
                vms[domain]['memory_usage_percent'] = round(value, 1)
            elif 'libvirt_domain_interface_stats_receive_bytes_total{' in line:
                vms[domain]['network_rx_bytes'] += value
            elif 'libvirt_domain_interface_stats_transmit_bytes_total{' in line:
                vms[domain]['network_tx_bytes'] += value
            elif 'libvirt_domain_block_stats_capacity_bytes{' in line:
                dev = self._extract_label(line, 'target_device') or 'unknown'
                vms[domain]['_block_cap'][dev] = value
            elif 'libvirt_domain_block_stats_allocation{' in line:
                dev = self._extract_label(line, 'target_device') or 'unknown'
                vms[domain]['_block_alloc'][dev] = value
            elif 'libvirt_domain_block_stats_physicalsize_bytes{' in line:
                dev = self._extract_label(line, 'target_device') or 'unknown'
                vms[domain]['_block_phys'][dev] = value

        # ——— Build VMMetrics list ————————————————————————————————————————
        vm_list: List[VMMetrics] = []
        for domain_id, d in vms.items():
            # CPU: delta-based calculation
            cur_vcpu_time = d.pop('_vcpu_time', 0.0)
            vcpu_count = d.pop('_vcpu_count', 1)
            d['cpu_total'] = float(vcpu_count)
            prev = self._prev_cpu_totals.get(domain_id)
            if prev and cur_vcpu_time > 0:
                delta_cpu = cur_vcpu_time - prev['vcpu_time']
                delta_wall = (now - prev['ts']).total_seconds()
                if delta_wall > 0 and delta_cpu >= 0:
                    d['cpu_usage_percent'] = round(
                        min(delta_cpu / (delta_wall * vcpu_count) * 100, 100), 1
                    )
            if cur_vcpu_time > 0:
                self._prev_cpu_totals[domain_id] = {'vcpu_time': cur_vcpu_time, 'ts': now}

            # Storage: compute used from block device capacity/allocation
            block_cap = d.pop('_block_cap', {})
            block_alloc = d.pop('_block_alloc', {})
            block_phys = d.pop('_block_phys', {})
            total_bytes = sum(block_cap.values())
            used_bytes = 0.0
            for dev, cap in block_cap.items():
                alloc = block_alloc.get(dev, 0.0)
                phys = block_phys.get(dev, 0.0)
                if cap > 0 and alloc >= cap * 0.99:
                    # Raw/thick disk: physical size is actual usage if < capacity
                    used_bytes += phys if 0 < phys < cap * 0.99 else alloc
                elif alloc > 0:
                    used_bytes += alloc

            d['storage_total_gb'] = round(total_bytes / (1024 ** 3), 1) if total_bytes else None
            d['storage_used_gb'] = round(used_bytes / (1024 ** 3), 1) if total_bytes else None
            d['storage_allocated_gb'] = d['storage_total_gb']

            # Memory % fallback
            if d.get('memory_usage_percent') is None:
                total_mem = d.get('memory_total_mb') or 0
                used_mem = d.get('memory_used_mb') or 0
                if total_mem > 0:
                    d['memory_usage_percent'] = round(used_mem / total_mem * 100, 1)

            try:
                vm_list.append(VMMetrics(**d))
            except Exception as exc:
                logger.warning(f"Skipping VM {domain_id}: {exc}")

        return vm_list

    # ------------------------------------------------------------------ #
    # node-exporter parser (port 9388)                                     #
    # ------------------------------------------------------------------ #

    def _parse_host_metrics_node(self, text: str, host: str) -> Optional[HostMetrics]:
        """Parse node-exporter Prometheus text into a HostMetrics object.

        Handles the standard ``node_*`` metric family.  Replaces the old stub
        that expected ``pcd:hyp_*`` metrics which never existed.
        """
        lines = text.strip().split('\n')
        now = datetime.utcnow()

        cpu_idle = 0.0
        cpu_total_s = 0.0
        mem_total_bytes: Optional[float] = None
        mem_avail_bytes: Optional[float] = None
        storage_total_bytes: Optional[float] = None
        storage_avail_bytes: Optional[float] = None
        network_rx_bytes = 0.0
        network_tx_bytes = 0.0

        for line in lines:
            if line.startswith('#') or not line.strip():
                continue
            try:
                value = float(line.rsplit(' ', 1)[-1])
            except (ValueError, IndexError):
                continue

            if 'node_cpu_seconds_total{' in line:
                cpu_total_s += value
                if 'mode="idle"' in line:
                    cpu_idle += value
            elif line.startswith('node_memory_MemTotal_bytes '):
                mem_total_bytes = value
            elif line.startswith('node_memory_MemAvailable_bytes '):
                mem_avail_bytes = value
            elif 'node_filesystem_size_bytes{' in line and 'mountpoint="/"' in line:
                storage_total_bytes = value
            elif 'node_filesystem_avail_bytes{' in line and 'mountpoint="/"' in line:
                storage_avail_bytes = value
            elif 'node_network_receive_bytes_total{' in line:
                dev = self._extract_label(line, 'device') or ''
                if dev and not any(dev.startswith(p) for p in _EXCL_NIC_PREFIXES):
                    network_rx_bytes += value
            elif 'node_network_transmit_bytes_total{' in line:
                dev = self._extract_label(line, 'device') or ''
                if dev and not any(dev.startswith(p) for p in _EXCL_NIC_PREFIXES):
                    network_tx_bytes += value

        host_data: dict = {'hostname': host, 'timestamp': now}

        # CPU utilisation (delta-based)
        host_key = f'__host_{host}'
        prev = self._prev_cpu_totals.get(host_key)
        if prev and cpu_total_s > 0:
            d_total = cpu_total_s - prev['cpu_total']
            d_idle = cpu_idle - prev['cpu_idle']
            if d_total > 0:
                host_data['cpu_usage_percent'] = round((1.0 - d_idle / d_total) * 100, 1)
        elif cpu_total_s > 0:
            # First cycle: instantaneous approximation
            host_data['cpu_usage_percent'] = round((1.0 - cpu_idle / cpu_total_s) * 100, 1)
        self._prev_cpu_totals[host_key] = {
            'cpu_total': cpu_total_s, 'cpu_idle': cpu_idle, 'ts': now
        }

        # Memory
        if mem_total_bytes and mem_avail_bytes is not None:
            host_data['memory_total_mb'] = round(mem_total_bytes / (1024 ** 2), 1)
            host_data['memory_used_mb'] = round(
                (mem_total_bytes - mem_avail_bytes) / (1024 ** 2), 1
            )

        # Storage (root filesystem)
        if storage_total_bytes is not None and storage_avail_bytes is not None:
            host_data['storage_total_gb'] = round(storage_total_bytes / (1024 ** 3), 1)
            host_data['storage_used_gb'] = round(
                (storage_total_bytes - storage_avail_bytes) / (1024 ** 3), 1
            )

        # Network (cumulative byte counters; useful for trend display in the UI)
        if network_rx_bytes > 0 or network_tx_bytes > 0:
            host_data['network_rx_throughput'] = network_rx_bytes
            host_data['network_tx_throughput'] = network_tx_bytes

        try:
            return HostMetrics(**host_data)
        except Exception as exc:
            logger.warning(f"Could not build HostMetrics for {host}: {exc}")
            return None

    # ------------------------------------------------------------------ #
    # Public API methods                                                   #
    # ------------------------------------------------------------------ #

    async def get_vm_metrics(
        self,
        domain_filter=None,
        host_filter=None,
        limit: int = 100,
    ):
        if not self.vm_cache:
            await self._collect_all_metrics()
        vms = list(self.vm_cache.values())
        if domain_filter:
            vms = [vm for vm in vms if domain_filter.lower() in vm.vm_name.lower()]
        if host_filter:
            vms = [vm for vm in vms if host_filter.lower() in vm.host.lower()]
        return vms[:limit]

    async def get_host_metrics(
        self,
        host_filter=None,
        limit: int = 50,
    ):
        if not self.host_cache:
            await self._collect_all_metrics()
        hosts = list(self.host_cache.values())
        if host_filter:
            hosts = [h for h in hosts if host_filter.lower() in h.hostname.lower()]
        return hosts[:limit]

    async def get_alerts(self, severity_filter=None):
        alerts = []
        for vm in self.vm_cache.values():
            if vm.cpu_usage_percent is not None and vm.cpu_usage_percent > 90:
                alerts.append({"type": "vm_cpu_high", "severity": "high", "resource": vm.vm_name,
                    "message": f"VM CPU {vm.cpu_usage_percent:.1f}% > 90%", "value": vm.cpu_usage_percent})
            if vm.memory_usage_percent is not None and vm.memory_usage_percent > 85:
                alerts.append({"type": "vm_memory_high", "severity": "medium", "resource": vm.vm_name,
                    "message": f"VM memory {vm.memory_usage_percent:.1f}% > 85%", "value": vm.memory_usage_percent})
        for host in self.host_cache.values():
            if host.cpu_usage_percent is not None and host.cpu_usage_percent > 80:
                alerts.append({"type": "host_cpu_high", "severity": "critical", "resource": host.hostname,
                    "message": f"Host CPU {host.cpu_usage_percent:.1f}% > 80%", "value": host.cpu_usage_percent})
        if severity_filter:
            alerts = [a for a in alerts if a["severity"] == severity_filter]
        return alerts

    async def get_summary_metrics(self):
        if not self.vm_cache or not self.host_cache:
            await self._collect_all_metrics()
        vms = list(self.vm_cache.values())
        hosts = list(self.host_cache.values())
        vm_cpus = [v.cpu_usage_percent for v in vms if v.cpu_usage_percent is not None]
        vm_mems = [v.memory_usage_percent for v in vms if v.memory_usage_percent is not None]
        h_cpus = [h.cpu_usage_percent for h in hosts if h.cpu_usage_percent is not None]
        h_mems = [h.memory_used_mb / h.memory_total_mb * 100 for h in hosts
                  if h.memory_used_mb is not None and h.memory_total_mb]
        return {
            "total_vms": len(vms), "total_hosts": len(hosts), "last_update": self.last_update,
            "vm_stats": {
                "avg_cpu": round(sum(vm_cpus)/len(vm_cpus), 1) if vm_cpus else 0.0,
                "max_cpu": round(max(vm_cpus), 1) if vm_cpus else 0.0,
                "avg_memory": round(sum(vm_mems)/len(vm_mems), 1) if vm_mems else 0.0,
                "max_memory": round(max(vm_mems), 1) if vm_mems else 0.0,
            },
            "host_stats": {
                "avg_cpu": round(sum(h_cpus)/len(h_cpus), 1) if h_cpus else 0.0,
                "max_cpu": round(max(h_cpus), 1) if h_cpus else 0.0,
                "avg_memory": round(sum(h_mems)/len(h_mems), 1) if h_mems else 0.0,
                "max_memory": round(max(h_mems), 1) if h_mems else 0.0,
            },
        }

    async def force_refresh(self):
        await self._collect_all_metrics()
