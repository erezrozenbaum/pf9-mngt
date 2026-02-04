#!/bin/bash

# Enhanced entrypoint that automatically triggers monitoring setup
echo "Starting PF9 Monitoring Service..."

# Check if cache file exists, create empty one if not
if [ ! -f "/tmp/metrics_cache.json" ]; then
    echo "Creating empty metrics cache file..."
    cat > /tmp/metrics_cache.json << EOF
{
  "vms": [],
  "hosts": [],
  "alerts": [],
  "summary": {
    "total_vms": 0,
    "total_hosts": 0,
    "last_update": null,
    "vm_stats": {},
    "host_stats": {
      "avg_cpu": 0.0,
      "avg_memory": 0.0,
      "total_memory_gb": 0.0,
      "used_memory_gb": 0.0,
      "total_storage_gb": 0,
      "used_storage_gb": 0
    }
  },
  "timestamp": "$(date -Iseconds)"
}
EOF
fi

# Create auto-setup flag file that will trigger host-side setup
echo "Creating auto-setup trigger file..."
touch /tmp/need_monitoring_setup

echo "Cache file ready. Starting monitoring service..."
exec uvicorn main:app --host 0.0.0.0 --port 8001