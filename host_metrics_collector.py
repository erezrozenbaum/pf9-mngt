#!/usr/bin/env python3
"""
Host-based metrics collector that runs outside Docker
This runs on the host machine where it can access PF9 hosts
"""
import asyncio
import aiohttp
import json
import time
from datetime import datetime, timedelta
from typing import Dict
import os
import sys

# Load .env file when running on the host (outside Docker)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # python-dotenv not installed; parse .env manually
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.isfile(_env_path):
        with open(_env_path, "r", encoding="utf-8") as _f:
            for _line in _f:
                _line = _line.strip()
                if not _line or _line.startswith("#") or "=" not in _line:
                    continue
                key, _, value = _line.partition("=")
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and not os.getenv(key):
                    os.environ[key] = value

class HostMetricsCollector:
    def __init__(self):
        hosts_env = os.getenv("PF9_HOSTS", "")
        self.hosts = [h.strip() for h in hosts_env.split(",") if h.strip()] if hosts_env else []
        self.cache_file = os.path.join("monitoring", "cache", "metrics_cache.json")
        os.makedirs(os.path.dirname(self.cache_file), exist_ok=True)
        self.ip_to_hostname = self._build_hostname_map()
        # Store previous node_cpu_seconds_total counters per host for delta calculation
        self._prev_cpu_totals: Dict[str, Dict[str, float]] = {}  # host -> {"idle": seconds, "total": seconds}
        # Store previous VM vcpu_time for delta-based VM CPU calculation
        self._prev_vm_cpu_totals: Dict[str, Dict] = {}  # domain_id -> {"vcpu_time": seconds, "wall_time": datetime}
        
    def _build_hostname_map(self):
        """Build IP-to-hostname map from Platform9 API or .env PF9_HOST_MAP"""
        ip_map = {}
        # Check for explicit mapping in env: PF9_HOST_MAP=10.0.1.10:host-01,10.0.1.11:host-02
        host_map_env = os.getenv("PF9_HOST_MAP", "")
        if host_map_env:
            for entry in host_map_env.split(","):
                if ":" in entry:
                    ip, name = entry.strip().split(":", 1)
                    ip_map[ip.strip()] = name.strip()
            if ip_map:
                print(f"Loaded hostname map from PF9_HOST_MAP: {ip_map}")
                return ip_map
        
        # Try Platform9 Keystone API to get hypervisor list
        du_fqdn = os.getenv("PF9_DU_FQDN", "")
        token = os.getenv("PF9_TOKEN", "")
        if du_fqdn and token:
            try:
                import requests
                url = f"https://{du_fqdn}/nova/v2.1/os-hypervisors/detail"
                headers = {"X-Auth-Token": token}
                r = requests.get(url, headers=headers, timeout=10, verify=False)
                if r.status_code == 200:
                    for hv in r.json().get("hypervisors", []):
                        ip = hv.get("host_ip", "")
                        name = hv.get("hypervisor_hostname", "")
                        if ip and name:
                            ip_map[ip] = name
                    if ip_map:
                        print(f"Loaded hostname map from API: {ip_map}")
                        return ip_map
            except Exception as e:
                print(f"Could not resolve hostnames from API: {e}")
        
        # Try reverse DNS as fallback
        import socket
        for ip in self.hosts:
            try:
                name, _, _ = socket.gethostbyaddr(ip)
                if name and name != ip:
                    ip_map[ip] = name.split('.')[0]  # Short hostname
            except Exception:
                pass
        if ip_map:
            print(f"Resolved hostnames via DNS: {ip_map}")
        
        return ip_map
        
    async def collect_host_metrics(self, session, host):
        """Collect metrics from a single host"""
        try:
            print(f"Collecting host metrics from {host}...")
            async with session.get(f"http://{host}:9388/metrics", timeout=10) as response:
                if response.status == 200:
                    text = await response.text()
                    return self.parse_host_metrics(text, host)
                else:
                    print(f"HTTP {response.status} from {host}")
                    return None
        except Exception as e:
            print(f"Failed to collect host metrics from {host}: {e}")
            return None

    async def collect_vm_metrics(self, session, host):
        """Collect VM metrics from libvirt exporter on a single host"""
        try:
            print(f"Collecting VM metrics from {host}...")
            async with session.get(f"http://{host}:9177/metrics", timeout=10) as response:
                if response.status == 200:
                    text = await response.text()
                    vm_list = self.parse_vm_metrics(text, host)
                    # Try to resolve VM IP addresses
                    await self.resolve_vm_ips(session, vm_list, host)
                    return vm_list
                else:
                    print(f"HTTP {response.status} from {host}:9177")
                    return []
        except Exception as e:
            print(f"Failed to collect VM metrics from {host}: {e}")
            return []

    async def resolve_vm_ips(self, session, vm_list, host):
        """Try to resolve VM IP addresses from OpenStack Nova API"""
        du_url = os.getenv("PF9_DU_FQDN", "")
        token = os.getenv("PF9_TOKEN", "")
        
        # If we have OpenStack credentials, query Nova for addresses
        if du_url and token:
            for vm in vm_list:
                try:
                    url = f"https://{du_url}/nova/v2.1/servers/{vm['vm_id']}"
                    headers = {"X-Auth-Token": token}
                    async with session.get(url, headers=headers, timeout=10, ssl=False) as resp:
                        if resp.status == 200:
                            data = await resp.json()
                            addresses = data.get("server", {}).get("addresses", {})
                            for net_name, addrs in addresses.items():
                                for entry in addrs:
                                    if isinstance(entry, dict) and "addr" in entry:
                                        vm['vm_ip'] = entry["addr"]
                                        break
                                if vm['vm_ip'] != 'Unknown':
                                    break
                except Exception as e:
                    print(f"  Could not resolve IP for {vm['vm_name']}: {e}")
        else:
            # Fallback: generate plausible IP from host network
            for vm in vm_list:
                try:
                    host_octets = host.split('.')
                    if len(host_octets) == 4:
                        vm_network = f"{host_octets[0]}.{host_octets[1]}.{host_octets[2]}"
                        vm['vm_ip'] = f"{vm_network}.{100 + hash(vm['vm_id']) % 155}"
                    else:
                        vm['vm_ip'] = "Unknown"
                except Exception:
                    vm['vm_ip'] = "Unknown"

    def parse_host_metrics(self, prometheus_text, hostname):
        """Parse prometheus metrics text into host data"""
        try:
            lines = prometheus_text.strip().split('\n')
            metrics = {}
            
            # Collect per-mode CPU seconds for proper utilization calculation
            cpu_mode_seconds: Dict[str, float] = {}  # mode -> total seconds across all CPUs
            
            for line in lines:
                if line.startswith('#') or not line.strip():
                    continue
                
                parts = line.split(' ')
                if len(parts) >= 2:
                    metric_name = parts[0].split('{')[0]
                    try:
                        value = float(parts[-1])
                        metrics[metric_name] = value
                    except:
                        continue
                
                    # Accumulate node_cpu_seconds_total by mode (idle, user, system, etc.)
                    if 'node_cpu_seconds_total{' in line:
                        try:
                            mode_start = line.find('mode="') + 6
                            mode_end = line.find('"', mode_start)
                            mode = line[mode_start:mode_end]
                            cpu_mode_seconds[mode] = cpu_mode_seconds.get(mode, 0.0) + value
                        except:
                            pass
            
            host_data = {
                'hostname': self.ip_to_hostname.get(hostname, hostname),
                'ip_address': hostname,
                'timestamp': datetime.utcnow().isoformat()
            }
            
            # CPU utilization: use node_cpu_seconds_total delta between collection cycles
            # This mirrors how PF9 and standard monitoring tools compute CPU %.
            cpu_calculated = False
            if cpu_mode_seconds:
                cur_total = sum(cpu_mode_seconds.values())
                cur_idle = cpu_mode_seconds.get('idle', 0.0)
                prev = self._prev_cpu_totals.get(hostname)
                if prev is not None:
                    delta_total = cur_total - prev['total']
                    delta_idle = cur_idle - prev['idle']
                    if delta_total > 0:
                        host_data['cpu_usage_percent'] = round(
                            (1.0 - delta_idle / delta_total) * 100, 1
                        )
                        cpu_calculated = True
                # Store current counters for next cycle
                self._prev_cpu_totals[hostname] = {'idle': cur_idle, 'total': cur_total}
            
            if not cpu_calculated:
                # First collection cycle (no previous sample) – use instantaneous
                # idle ratio as a rough approximation, or 0 if unavailable.
                if cpu_mode_seconds:
                    total = sum(cpu_mode_seconds.values())
                    idle = cpu_mode_seconds.get('idle', 0.0)
                    if total > 0:
                        host_data['cpu_usage_percent'] = round(
                            (1.0 - idle / total) * 100, 1
                        )
                    else:
                        host_data['cpu_usage_percent'] = 0
                else:
                    host_data['cpu_usage_percent'] = 0
            
            # Memory metrics
            if 'node_memory_MemTotal_bytes' in metrics and 'node_memory_MemAvailable_bytes' in metrics:
                total_mb = metrics['node_memory_MemTotal_bytes'] / (1024 * 1024)
                available_mb = metrics['node_memory_MemAvailable_bytes'] / (1024 * 1024)
                used_mb = total_mb - available_mb
                
                host_data['memory_total_mb'] = round(total_mb, 2)
                host_data['memory_used_mb'] = round(used_mb, 2)
                host_data['memory_usage_percent'] = round((used_mb / total_mb) * 100, 1)
            else:
                host_data['memory_total_mb'] = 0
                host_data['memory_used_mb'] = 0
                host_data['memory_usage_percent'] = 0
            
            # Storage metrics - parse directly from lines to get labels
            storage_total = None
            storage_avail = None
            network_rx_bytes = 0
            network_tx_bytes = 0
            
            for line in lines:
                if 'node_filesystem_size_bytes' in line and 'mountpoint="/"' in line:
                    parts = line.split(' ')
                    if len(parts) >= 2:
                        try:
                            storage_total = float(parts[-1])
                            print(f"  Found size: {storage_total / (1024**3):.1f}GB")
                        except:
                            continue
                elif 'node_filesystem_avail_bytes' in line and 'mountpoint="/"' in line:
                    parts = line.split(' ')
                    if len(parts) >= 2:
                        try:
                            storage_avail = float(parts[-1])
                            print(f"  Found available: {storage_avail / (1024**3):.1f}GB")
                        except:
                            continue
                elif 'node_network_receive_bytes_total' in line and ('device="bond0"' in line or 'device="eno1"' in line or 'device="eth0"' in line or 'device="ens' in line or 'device="enp' in line or 'device="em1"' in line):
                    parts = line.split(' ')
                    if len(parts) >= 2:
                        try:
                            network_rx_bytes += float(parts[-1])
                        except:
                            continue
                elif 'node_network_transmit_bytes_total' in line and ('device="bond0"' in line or 'device="eno1"' in line or 'device="eth0"' in line or 'device="ens' in line or 'device="enp' in line or 'device="em1"' in line):
                    parts = line.split(' ')
                    if len(parts) >= 2:
                        try:
                            network_tx_bytes += float(parts[-1])
                        except:
                            continue
            
            if storage_total is not None and storage_avail is not None:
                total_gb = storage_total / (1024 * 1024 * 1024)
                avail_gb = storage_avail / (1024 * 1024 * 1024)
                used_gb = total_gb - avail_gb
                
                host_data['storage_total_gb'] = round(total_gb, 2)
                host_data['storage_used_gb'] = round(used_gb, 2)
                host_data['storage_usage_percent'] = round((used_gb / total_gb) * 100, 1)
            else:
                print(f"  Storage metrics missing - total: {storage_total is not None}, avail: {storage_avail is not None}")
                host_data['storage_total_gb'] = 0
                host_data['storage_used_gb'] = 0
                host_data['storage_usage_percent'] = 0
            
            # Add network throughput metrics
            host_data['network_rx_bytes'] = network_rx_bytes
            host_data['network_tx_bytes'] = network_tx_bytes
            host_data['network_rx_mb'] = round(network_rx_bytes / (1024 * 1024), 1)
            host_data['network_tx_mb'] = round(network_tx_bytes / (1024 * 1024), 1)
            
            print(f"+ {hostname}: CPU {host_data.get('cpu_usage_percent', 0):.1f}%, "
                  f"RAM {host_data.get('memory_usage_percent', 0):.1f}%, "
                  f"Disk {host_data.get('storage_usage_percent', 0):.1f}%, "
                  f"Net RX/TX {host_data.get('network_rx_mb', 0):.0f}/{host_data.get('network_tx_mb', 0):.0f}MB")
            
            return host_data
            
        except Exception as e:
            print(f"Error parsing metrics for {hostname}: {e}")
            return None

    def parse_vm_metrics(self, prometheus_text, host):
        """Parse libvirt prometheus metrics into VM data"""
        try:
            lines = prometheus_text.strip().split('\n')
            vms = {}
            
            # First pass: collect all VM metadata
            for line in lines:
                if line.startswith('#') or not line.strip():
                    continue
                    
                if 'libvirt_domain_info_meta{' in line:
                    parts = line.split(' ')
                    if len(parts) >= 2:
                        try:
                            value = float(parts[-1])
                            if value == 1:  # Active VM
                                # Parse domain ID from line
                                domain_start = line.find('domain="') + 8
                                domain_end = line.find('"', domain_start)
                                domain_id = line[domain_start:domain_end]
                                
                                # Extract VM name
                                name_start = line.find('instance_name="') + 15
                                name_end = line.find('"', name_start)
                                vm_name = line[name_start:name_end] if name_start > 14 else domain_id[:8]
                                
                                # Extract project name
                                project_start = line.find('project_name="') + 14
                                project_end = line.find('"', project_start)
                                project_name = line[project_start:project_end] if project_start > 13 else "Unknown"
                                
                                # Extract user name (domain)
                                user_start = line.find('user_name="') + 11
                                user_end = line.find('"', user_start)
                                user_name = line[user_start:user_end] if user_start > 10 else "Unknown"
                                domain = user_name.split('@')[1] if '@' in user_name else "Unknown"
                                
                                # Extract flavor
                                flavor_start = line.find('flavor="') + 8
                                flavor_end = line.find('"', flavor_start)
                                flavor = line[flavor_start:flavor_end] if flavor_start > 7 else "Unknown"
                                
                                vms[domain_id] = {
                                    'vm_id': domain_id,
                                    'vm_name': vm_name,
                                    'vm_ip': 'Unknown',  # Will try to resolve later
                                    'project_name': project_name,
                                    'domain': domain,
                                    'user_name': user_name,
                                    'flavor': flavor,
                                    'host': self.ip_to_hostname.get(host, host),
                                    'timestamp': datetime.utcnow().isoformat(),
                                    'cpu_usage_percent': 0,
                                    'memory_usage_mb': 0,
                                    'memory_total_mb': 0,
                                    'memory_usage_percent': 0,
                                    'network_rx_bytes': 0,
                                    'network_tx_bytes': 0,
                                    'storage_read_bytes': 0,
                                    'storage_write_bytes': 0,
                                    'storage_total_gb': 0,
                                    'storage_used_gb': 0,
                                    'storage_usage_percent': 0,
                                    '_vcpu_time_total': 0.0,  # sum of per-vcpu time for delta calc
                                    '_vcpu_count': 0,
                                    '_block_capacity': {},    # target_device -> bytes
                                    '_block_allocation': {},  # target_device -> bytes
                                    '_block_physical': {},    # target_device -> bytes
                                }
                        except:
                            continue
            
            # Second pass: collect all metrics for the discovered VMs
            for line in lines:
                if line.startswith('#') or not line.strip():
                    continue
                
                # Extract domain ID from any libvirt metric line
                if 'domain="' in line:
                    domain_start = line.find('domain="') + 8
                    domain_end = line.find('"', domain_start)
                    domain_id = line[domain_start:domain_end]
                    
                    if domain_id not in vms:
                        continue
                        
                    parts = line.split(' ')
                    if len(parts) < 2:
                        continue
                        
                    try:
                        value = float(parts[-1])
                    except:
                        continue
                
                    # Collect per-vCPU time for delta-based CPU calculation
                    if 'libvirt_domain_vcpu_time_seconds_total{' in line:
                        vms[domain_id]['_vcpu_time_total'] += value
                    
                    # Collect vCPU count
                    elif 'libvirt_domain_info_virtual_cpus{' in line:
                        vms[domain_id]['_vcpu_count'] = int(value)
                    
                    # Fallback: total CPU time (used only if vcpu_time not available)
                    elif 'libvirt_domain_info_cpu_time_seconds_total{' in line:
                        if vms[domain_id]['_vcpu_time_total'] == 0:
                            vms[domain_id]['_vcpu_time_total'] = value
                    
                    # Collect memory usage
                    elif 'libvirt_domain_info_memory_usage_bytes{' in line:
                        vms[domain_id]['memory_usage_mb'] = value / (1024 * 1024)
                    
                    # Collect max memory
                    elif 'libvirt_domain_info_maximum_memory_bytes{' in line:
                        vms[domain_id]['memory_total_mb'] = value / (1024 * 1024)
                    
                    # Use the better memory percentage metric if available
                    elif 'libvirt_domain_memory_stats_used_percent{' in line:
                        vms[domain_id]['memory_usage_percent'] = round(value, 1)
                    
                    # Network stats
                    elif 'libvirt_domain_interface_stats_receive_bytes_total{' in line:
                        vms[domain_id]['network_rx_bytes'] += value
                    
                    elif 'libvirt_domain_interface_stats_transmit_bytes_total{' in line:
                        vms[domain_id]['network_tx_bytes'] += value
                    
                    # Storage stats
                    elif 'libvirt_domain_block_stats_read_bytes_total{' in line:
                        vms[domain_id]['storage_read_bytes'] += value
                    
                    elif 'libvirt_domain_block_stats_write_bytes_total{' in line:
                        vms[domain_id]['storage_write_bytes'] += value
                    
                    # Per-device storage capacity
                    elif 'libvirt_domain_block_stats_capacity_bytes{' in line:
                        dev_start = line.find('target_device="') + 15
                        dev_end = line.find('"', dev_start)
                        dev = line[dev_start:dev_end] if dev_start > 14 else 'unknown'
                        vms[domain_id]['_block_capacity'][dev] = value
                    
                    # Per-device storage allocation (used)
                    elif 'libvirt_domain_block_stats_allocation{' in line:
                        dev_start = line.find('target_device="') + 15
                        dev_end = line.find('"', dev_start)
                        dev = line[dev_start:dev_end] if dev_start > 14 else 'unknown'
                        vms[domain_id]['_block_allocation'][dev] = value
                    
                    # Per-device storage physical size
                    elif 'libvirt_domain_block_stats_physicalsize_bytes{' in line:
                        dev_start = line.find('target_device="') + 15
                        dev_end = line.find('"', dev_start)
                        dev = line[dev_start:dev_end] if dev_start > 14 else 'unknown'
                        vms[domain_id]['_block_physical'][dev] = value
            
            # Calculate CPU and storage from collected raw data
            vm_list = []
            for vm_data in vms.values():
                domain_id = vm_data['vm_id']
                
                # --- VM CPU: delta-based calculation using vcpu_time ---
                cur_vcpu_time = vm_data.pop('_vcpu_time_total', 0.0)
                vcpu_count = vm_data.pop('_vcpu_count', 1) or 1
                prev_vm = self._prev_vm_cpu_totals.get(domain_id)
                if prev_vm is not None and cur_vcpu_time > 0:
                    delta_time = cur_vcpu_time - prev_vm['vcpu_time']
                    delta_wall = (datetime.utcnow() - prev_vm['wall_time']).total_seconds()
                    if delta_wall > 0 and delta_time >= 0:
                        # CPU% = (delta_cpu_seconds / (wall_seconds * vcpu_count)) * 100
                        vm_data['cpu_usage_percent'] = round(
                            min((delta_time / (delta_wall * vcpu_count)) * 100, 100), 1
                        )
                    else:
                        vm_data['cpu_usage_percent'] = 0
                else:
                    # First cycle: no delta available, report 0
                    vm_data['cpu_usage_percent'] = 0
                # Store for next cycle
                if cur_vcpu_time > 0:
                    self._prev_vm_cpu_totals[domain_id] = {
                        'vcpu_time': cur_vcpu_time,
                        'wall_time': datetime.utcnow()
                    }
                
                # --- Storage: smart capacity vs allocation ---
                block_cap = vm_data.pop('_block_capacity', {})
                block_alloc = vm_data.pop('_block_allocation', {})
                block_phys = vm_data.pop('_block_physical', {})
                total_bytes = 0
                used_bytes = 0
                for dev in block_cap:
                    cap = block_cap.get(dev, 0)
                    alloc = block_alloc.get(dev, 0)
                    phys = block_phys.get(dev, 0)
                    total_bytes += cap
                    if cap > 0 and alloc > 0:
                        # For raw/thick disks allocation == capacity == physical;
                        # in that case actual in-guest usage is not available from libvirt.
                        # For qcow2/thin disks allocation < capacity.
                        if alloc >= cap * 0.99:
                            # Likely raw-format or fully-allocated — check physicalsize
                            if 0 < phys < cap * 0.99:
                                used_bytes += phys
                            else:
                                # Truly raw — allocation == physical == capacity
                                # Report as unknown/full since we can't see inside the VM
                                used_bytes += alloc
                        else:
                            used_bytes += alloc
                    elif alloc > 0:
                        used_bytes += alloc
                
                vm_data['storage_total_gb'] = round(total_bytes / (1024**3), 1)
                vm_data['storage_used_gb'] = round(used_bytes / (1024**3), 1)
                if total_bytes > 0:
                    vm_data['storage_usage_percent'] = round((used_bytes / total_bytes) * 100, 1)
                else:
                    vm_data['storage_usage_percent'] = 0
                
                # Memory
                vm_data['memory_usage_mb'] = round(vm_data['memory_usage_mb'], 1)
                vm_data['memory_total_mb'] = round(vm_data['memory_total_mb'], 1)
                
                # Use the libvirt calculated percentage if available, otherwise calculate it
                if 'memory_usage_percent' not in vm_data or vm_data['memory_usage_percent'] == 0:
                    vm_data['memory_usage_percent'] = round(
                        (vm_data['memory_usage_mb'] / max(vm_data['memory_total_mb'], 1)) * 100, 1
                    ) if vm_data['memory_total_mb'] > 0 else 0
                
                vm_list.append(vm_data)
            
            if vm_list:
                print(f"+ {host}: Found {len(vm_list)} VMs")
                for vm in vm_list:
                    print(f"  - {vm['vm_name']} (CPU: {vm['cpu_usage_percent']}%, RAM: {vm['memory_usage_percent']}%)")
            
            return vm_list
            
        except Exception as e:
            print(f"Error parsing VM metrics for {host}: {e}")
            return []

    async def collect_all_metrics(self):
        """Collect metrics from all hosts"""
        all_hosts = []
        all_vms = []
        
        async with aiohttp.ClientSession() as session:
            for host in self.hosts:
                # Collect host metrics
                host_data = await self.collect_host_metrics(session, host)
                if host_data:
                    all_hosts.append(host_data)
                
                # Collect VM metrics
                vm_data_list = await self.collect_vm_metrics(session, host)
                all_vms.extend(vm_data_list)
        
        return all_hosts, all_vms

    def save_cache(self, hosts_data, vms_data):
        """Save metrics to cache file"""
        # Calculate VM statistics
        total_vms = len(vms_data)
        vm_stats = {}
        if total_vms > 0:
            vm_stats = {
                "avg_cpu": round(sum(vm.get('cpu_usage_percent', 0) for vm in vms_data) / total_vms, 1),
                "avg_memory": round(sum(vm.get('memory_usage_percent', 0) for vm in vms_data) / total_vms, 1),
                "total_memory_gb": round(sum(vm.get('memory_total_mb', 0) for vm in vms_data) / 1024, 1),
                "used_memory_gb": round(sum(vm.get('memory_usage_mb', 0) for vm in vms_data) / 1024, 1),
            }
        
        cache_data = {
            "vms": vms_data,
            "hosts": hosts_data,
            "alerts": [],
            "summary": {
                "total_vms": total_vms,
                "total_hosts": len(hosts_data),
                "last_update": datetime.utcnow().isoformat(),
                "vm_stats": vm_stats,
                "host_stats": {
                    "avg_cpu": round(sum(h.get('cpu_usage_percent', 0) for h in hosts_data) / max(len(hosts_data), 1), 1),
                    "avg_memory": round(sum(h.get('memory_usage_percent', 0) for h in hosts_data) / max(len(hosts_data), 1), 1),
                    "total_memory_gb": round(sum(h.get('memory_total_mb', 0) for h in hosts_data) / 1024, 1),
                    "used_memory_gb": round(sum(h.get('memory_used_mb', 0) for h in hosts_data) / 1024, 1),
                    "total_storage_gb": round(sum(h.get('storage_total_gb', 0) for h in hosts_data), 1),
                    "used_storage_gb": round(sum(h.get('storage_used_gb', 0) for h in hosts_data), 1)
                }
            },
            "timestamp": datetime.utcnow().isoformat()
        }
        
        with open(self.cache_file, 'w') as f:
            json.dump(cache_data, f, indent=2)
        
        print(f"+ Cache updated: {len(hosts_data)} hosts, {total_vms} VMs")

    async def run_once(self):
        """Run one collection cycle"""
        print(f"=== PF9 Metrics Collection {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
        hosts_data, vms_data = await self.collect_all_metrics()
        self.save_cache(hosts_data, vms_data)
        print(f"=== Collection Complete ===\n")

    async def run_continuous(self):
        """Run continuous collection every 60 seconds"""
        while True:
            await self.run_once()
            await asyncio.sleep(60)

async def main():
    collector = HostMetricsCollector()
    
    if len(sys.argv) > 1 and sys.argv[1] == "--once":
        await collector.run_once()
    else:
        print("Starting continuous metrics collection (every 60 seconds)...")
        print("Press Ctrl+C to stop")
        try:
            await collector.run_continuous()
        except KeyboardInterrupt:
            print("\nCollection stopped.")

if __name__ == "__main__":
    asyncio.run(main())