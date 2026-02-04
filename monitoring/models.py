from typing import List, Optional, Generic, TypeVar
from datetime import datetime
from pydantic import BaseModel, Field

T = TypeVar('T')


class VMMetrics(BaseModel):
    """VM resource metrics model"""
    vm_id: str
    vm_name: str
    host: str
    timestamp: datetime
    
    # CPU metrics
    cpu_total: Optional[float] = Field(None, description="Total CPU cores")
    cpu_usage_percent: Optional[float] = Field(None, description="CPU usage percentage")
    
    # Memory metrics (in MB)
    memory_total_mb: Optional[float] = Field(None, description="Total memory in MB")
    memory_allocated_mb: Optional[float] = Field(None, description="Allocated memory in MB")
    memory_used_mb: Optional[float] = Field(None, description="Used memory in MB")
    memory_usage_percent: Optional[float] = Field(None, description="Memory usage percentage")
    
    # Storage metrics (in GB)
    storage_total_gb: Optional[float] = Field(None, description="Total storage in GB")
    storage_allocated_gb: Optional[float] = Field(None, description="Allocated storage in GB")
    storage_used_gb: Optional[float] = Field(None, description="Used storage in GB")
    storage_read_iops: Optional[float] = Field(None, description="Storage read IOPS")
    storage_write_iops: Optional[float] = Field(None, description="Storage write IOPS")
    
    # Network metrics (in bytes)
    network_rx_bytes: Optional[float] = Field(None, description="Network receive bytes")
    network_tx_bytes: Optional[float] = Field(None, description="Network transmit bytes")
    
    @property
    def storage_usage_percent(self) -> Optional[float]:
        """Calculate storage usage percentage"""
        if self.storage_total_gb and self.storage_used_gb:
            return (self.storage_used_gb / self.storage_total_gb) * 100
        return None
    
    @property
    def memory_allocation_percent(self) -> Optional[float]:
        """Calculate memory allocation percentage"""
        if self.memory_total_mb and self.memory_allocated_mb:
            return (self.memory_allocated_mb / self.memory_total_mb) * 100
        return None


class HostMetrics(BaseModel):
    """Host/hypervisor resource metrics model"""
    hostname: str
    timestamp: datetime
    
    # CPU metrics
    cpu_total: Optional[float] = Field(None, description="Total CPU cores")
    cpu_usage_percent: Optional[float] = Field(None, description="CPU usage percentage")
    
    # Memory metrics (in MB)
    memory_total_mb: Optional[float] = Field(None, description="Total memory in MB")
    memory_used_mb: Optional[float] = Field(None, description="Used memory in MB")
    
    # Storage metrics (in GB)
    storage_total_gb: Optional[float] = Field(None, description="Total storage in GB")
    storage_used_gb: Optional[float] = Field(None, description="Used storage in GB")
    
    # Network metrics (throughput)
    network_rx_throughput: Optional[float] = Field(None, description="Network receive throughput")
    network_tx_throughput: Optional[float] = Field(None, description="Network transmit throughput")
    
    @property
    def memory_usage_percent(self) -> Optional[float]:
        """Calculate memory usage percentage"""
        if self.memory_total_mb and self.memory_used_mb:
            return (self.memory_used_mb / self.memory_total_mb) * 100
        return None
    
    @property
    def storage_usage_percent(self) -> Optional[float]:
        """Calculate storage usage percentage"""
        if self.storage_total_gb and self.storage_used_gb:
            return (self.storage_used_gb / self.storage_total_gb) * 100
        return None
    
    @property
    def available_memory_mb(self) -> Optional[float]:
        """Calculate available memory"""
        if self.memory_total_mb and self.memory_used_mb:
            return self.memory_total_mb - self.memory_used_mb
        return None
    
    @property
    def available_storage_gb(self) -> Optional[float]:
        """Calculate available storage"""
        if self.storage_total_gb and self.storage_used_gb:
            return self.storage_total_gb - self.storage_used_gb
        return None


class MetricsResponse(BaseModel, Generic[T]):
    """Generic response wrapper for metrics data"""
    data: List[T]
    count: int
    timestamp: datetime
    

class AlertModel(BaseModel):
    """Alert/threshold model"""
    type: str = Field(..., description="Alert type (vm_cpu_high, host_memory_low, etc.)")
    severity: str = Field(..., description="Alert severity (low, medium, high, critical)")
    resource: str = Field(..., description="Resource name (VM name, host name)")
    message: str = Field(..., description="Human-readable alert message")
    value: float = Field(..., description="Current metric value")
    threshold: Optional[float] = Field(None, description="Threshold that triggered alert")
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class MetricsSummary(BaseModel):
    """High-level metrics summary for dashboard"""
    total_vms: int
    total_hosts: int
    last_update: Optional[datetime]
    
    vm_stats: dict = Field(default_factory=dict)
    host_stats: dict = Field(default_factory=dict)
    
    alerts_count: int = 0
    critical_alerts_count: int = 0