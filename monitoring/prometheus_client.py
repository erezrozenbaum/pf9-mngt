import asyncio
import aiohttp
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
import logging
from urllib.parse import urljoin

from models import VMMetrics, HostMetrics

logger = logging.getLogger(__name__)


class PrometheusClient:
    """Client for collecting metrics from Platform9 PCD Prometheus endpoints"""
    
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
            
        # Update cache
        self.vm_cache = {vm.vm_id: vm for vm in vm_metrics}
        self.host_cache = {host.hostname: host for host in host_metrics}
        self.last_update = datetime.utcnow()
        
        logger.info(f"Updated cache: {len(vm_metrics)} VMs, {len(host_metrics)} hosts")
        
    async def _collect_host_metrics(self, host: str) -> tuple:
        """Collect metrics from a single host"""
        vm_metrics = []
        host_metrics = []
        
        try:
            # Collect VM metrics from libvirt exporter
            vm_data = await self._scrape_metrics(host, self.libvirt_port)
            vm_metrics = self._parse_vm_metrics(vm_data, host)
            
            # Collect host metrics from node exporter
            node_data = await self._scrape_metrics(host, self.node_exporter_port)
            host_metrics = [self._parse_host_metrics(node_data, host)]
            
        except Exception as e:
            logger.error(f"Error collecting from {host}: {e}")
            
        return vm_metrics, host_metrics
        
    async def _scrape_metrics(self, host: str, port: int) -> Dict[str, Any]:
        """Scrape metrics from Prometheus endpoint"""
        url = f"http://{host}:{port}/metrics"
        
        async with self.session.get(url) as response:
            if response.status != 200:
                raise Exception(f"HTTP {response.status} from {url}")
                
            text = await response.text()
            return self._parse_prometheus_text(text)
            
    def _parse_prometheus_text(self, text: str) -> Dict[str, Any]:
        """Parse Prometheus text format into structured data"""
        metrics = {}
        
        for line in text.split('\n'):
            line = line.strip()
            if not line or line.startswith('#'):
                continue
                
            try:
                metric_name, value = line.split(' ', 1)
                # Handle labels if present
                if '{' in metric_name:
                    name, labels_str = metric_name.split('{', 1)
                    labels_str = labels_str.rstrip('}')
                    labels = self._parse_labels(labels_str)
                else:
                    name = metric_name
                    labels = {}
                    
                if name not in metrics:
                    metrics[name] = []
                    
                metrics[name].append({
                    'labels': labels,
                    'value': float(value)
                })
                
            except (ValueError, IndexError):
                continue  # Skip malformed lines
                
        return metrics
        
    def _parse_labels(self, labels_str: str) -> Dict[str, str]:
        """Parse Prometheus label string"""
        labels = {}
        
        for label_pair in labels_str.split(','):
            if '=' in label_pair:
                key, value = label_pair.split('=', 1)
                labels[key.strip()] = value.strip('"')
                
        return labels
        
    def _parse_vm_metrics(self, metrics: Dict[str, Any], host: str) -> List[VMMetrics]:
        """Convert raw metrics to VM metrics objects"""
        vms = {}
        
        # Group metrics by VM (domain)
        for metric_name, metric_data in metrics.items():
            if metric_name.startswith('pcd:vm_'):
                for data_point in metric_data:
                    labels = data_point['labels']
                    vm_id = labels.get('domain', labels.get('instance', 'unknown'))
                    
                    if vm_id not in vms:
                        vms[vm_id] = {
                            'vm_id': vm_id,
                            'vm_name': labels.get('name', vm_id),
                            'host': host,
                            'timestamp': datetime.utcnow()
                        }
                        
                    # Map metric to VM attribute
                    self._map_vm_metric(vms[vm_id], metric_name, data_point['value'])
                    
        return [VMMetrics(**vm_data) for vm_data in vms.values()]
        
    def _map_vm_metric(self, vm_data: dict, metric_name: str, value: float):
        """Map Prometheus metric to VM data field"""
        mapping = {
            'pcd:vm_cpu_total': 'cpu_total',
            'pcd:vm_cpu_usage': 'cpu_usage_percent',
            'pcd:vm_mem_total': 'memory_total_mb',
            'pcd:vm_mem_allocated': 'memory_allocated_mb',
            'pcd:vm_mem_usage': 'memory_used_mb',
            'pcd:vm_mem_usage_percent': 'memory_usage_percent',
            'pcd:vm_total_storage': 'storage_total_gb',
            'pcd:vm_allocated_storage': 'storage_allocated_gb',
            'pcd:vm_used_storage': 'storage_used_gb',
            'pcd:vm_read_iops': 'storage_read_iops',
            'pcd:vm_write_iops': 'storage_write_iops',
            'pcd:vm_rx_bytes': 'network_rx_bytes',
            'pcd:vm_tx_bytes': 'network_tx_bytes'
        }
        
        field = mapping.get(metric_name)
        if field:
            vm_data[field] = value
            
    def _parse_host_metrics(self, metrics: Dict[str, Any], hostname: str) -> HostMetrics:
        """Convert raw metrics to host metrics object"""
        host_data = {
            'hostname': hostname,
            'timestamp': datetime.utcnow()
        }
        
        # Map host metrics
        for metric_name, metric_data in metrics.items():
            if metric_name.startswith('pcd:hyp_'):
                if metric_data:
                    value = metric_data[0]['value']
                    self._map_host_metric(host_data, metric_name, value)
                    
        return HostMetrics(**host_data)
        
    def _map_host_metric(self, host_data: dict, metric_name: str, value: float):
        """Map Prometheus metric to host data field"""
        mapping = {
            'pcd:hyp_cpu_total': 'cpu_total',
            'pcd:hyp_cpu_usage': 'cpu_usage_percent',
            'pcd:hyp_mem_total': 'memory_total_mb',
            'pcd:hyp_mem_usage': 'memory_used_mb',
            'pcd:hyp_disk_space': 'storage_total_gb',
            'pcd:hyp_disk_usage': 'storage_used_gb',
            'pcd:hyp_net_rx_throughput': 'network_rx_throughput',
            'pcd:hyp_net_tx_throughput': 'network_tx_throughput'
        }
        
        field = mapping.get(metric_name)
        if field:
            host_data[field] = value
            
    # Public API methods
    async def get_vm_metrics(
        self, 
        domain_filter: Optional[str] = None,
        host_filter: Optional[str] = None,
        limit: int = 100
    ) -> List[VMMetrics]:
        """Get cached VM metrics with optional filtering"""
        if not self.vm_cache:
            await self._collect_all_metrics()
            
        vms = list(self.vm_cache.values())
        
        # Apply filters
        if domain_filter:
            vms = [vm for vm in vms if domain_filter.lower() in vm.vm_name.lower()]
        if host_filter:
            vms = [vm for vm in vms if host_filter.lower() in vm.host.lower()]
            
        return vms[:limit]
        
    async def get_host_metrics(
        self, 
        host_filter: Optional[str] = None,
        limit: int = 50
    ) -> List[HostMetrics]:
        """Get cached host metrics with optional filtering"""
        if not self.host_cache:
            await self._collect_all_metrics()
            
        hosts = list(self.host_cache.values())
        
        if host_filter:
            hosts = [host for host in hosts if host_filter.lower() in host.hostname.lower()]
            
        return hosts[:limit]
        
    async def get_alerts(self, severity_filter: Optional[str] = None) -> List[Dict[str, Any]]:
        """Generate alerts based on thresholds"""
        alerts = []
        
        # Check VM alerts
        for vm in self.vm_cache.values():
            if hasattr(vm, 'cpu_usage_percent') and vm.cpu_usage_percent > 90:
                alerts.append({
                    'type': 'vm_cpu_high',
                    'severity': 'high',
                    'resource': vm.vm_name,
                    'message': f'VM CPU usage {vm.cpu_usage_percent:.1f}% > 90%',
                    'value': vm.cpu_usage_percent
                })
                
            if hasattr(vm, 'memory_usage_percent') and vm.memory_usage_percent > 85:
                alerts.append({
                    'type': 'vm_memory_high',
                    'severity': 'medium',
                    'resource': vm.vm_name,
                    'message': f'VM memory usage {vm.memory_usage_percent:.1f}% > 85%',
                    'value': vm.memory_usage_percent
                })
                
        # Check host alerts
        for host in self.host_cache.values():
            if hasattr(host, 'cpu_usage_percent') and host.cpu_usage_percent > 80:
                alerts.append({
                    'type': 'host_cpu_high',
                    'severity': 'critical',
                    'resource': host.hostname,
                    'message': f'Host CPU usage {host.cpu_usage_percent:.1f}% > 80%',
                    'value': host.cpu_usage_percent
                })
                
        # Filter by severity if requested
        if severity_filter:
            alerts = [a for a in alerts if a['severity'] == severity_filter]
            
        return alerts
        
    async def get_summary_metrics(self) -> Dict[str, Any]:
        """Get high-level summary for dashboard"""
        if not self.vm_cache or not self.host_cache:
            await self._collect_all_metrics()
            
        return {
            'total_vms': len(self.vm_cache),
            'total_hosts': len(self.host_cache),
            'last_update': self.last_update,
            'vm_stats': self._calculate_vm_stats(),
            'host_stats': self._calculate_host_stats()
        }
        
    def _calculate_vm_stats(self) -> Dict[str, Any]:
        """Calculate aggregate VM statistics"""
        vms = list(self.vm_cache.values())
        if not vms:
            return {}
            
        cpu_usage = [vm.cpu_usage_percent for vm in vms if hasattr(vm, 'cpu_usage_percent')]
        memory_usage = [vm.memory_usage_percent for vm in vms if hasattr(vm, 'memory_usage_percent')]
        
        return {
            'avg_cpu_usage': sum(cpu_usage) / len(cpu_usage) if cpu_usage else 0,
            'max_cpu_usage': max(cpu_usage) if cpu_usage else 0,
            'avg_memory_usage': sum(memory_usage) / len(memory_usage) if memory_usage else 0,
            'max_memory_usage': max(memory_usage) if memory_usage else 0,
        }
        
    def _calculate_host_stats(self) -> Dict[str, Any]:
        """Calculate aggregate host statistics"""
        hosts = list(self.host_cache.values())
        if not hosts:
            return {}
            
        cpu_usage = [host.cpu_usage_percent for host in hosts if hasattr(host, 'cpu_usage_percent')]
        memory_usage = [host.memory_used_mb / host.memory_total_mb * 100 for host in hosts 
                       if hasattr(host, 'memory_used_mb') and hasattr(host, 'memory_total_mb') and host.memory_total_mb > 0]
        
        return {
            'avg_cpu_usage': sum(cpu_usage) / len(cpu_usage) if cpu_usage else 0,
            'max_cpu_usage': max(cpu_usage) if cpu_usage else 0,
            'avg_memory_usage': sum(memory_usage) / len(memory_usage) if memory_usage else 0,
            'max_memory_usage': max(memory_usage) if memory_usage else 0,
        }
        
    async def force_refresh(self):
        """Force immediate refresh of metrics cache"""
        await self._collect_all_metrics()