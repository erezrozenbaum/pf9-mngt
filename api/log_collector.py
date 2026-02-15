#!/usr/bin/env python3
"""
PF9 Log Collector Service
Securely collects logs from Platform9 compute hosts via SSH
"""

import paramiko
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import asyncio
import aiofiles
from dotenv import load_dotenv

load_dotenv()

class PF9LogCollector:
    def __init__(self):
        # SSH configuration from environment
        self.ssh_user = os.getenv('PF9_SSH_USER', 'pf9')
        self.ssh_password = os.getenv('PF9_SSH_PASSWORD')
        self.ssh_key_path = os.getenv('PF9_SSH_KEY_PATH')
        
        # ONLY use SSH_PF9_HOSTS for logs - both display and SSH connections
        ssh_hosts_str = os.getenv('SSH_PF9_HOSTS', '')
        self.hosts = [host.strip() for host in ssh_hosts_str.split(',')]
        
        print(f"Log collector initialized with SSH hosts: {self.hosts}")  # Debug
        
        # Log file paths on compute hosts
        self.log_paths = {
            'hostagent': '/var/log/pf9/hostagent.log',
            'neutron-agent': '/var/log/pf9/neutron-agent.log',
            'nova-compute': '/var/log/pf9/nova-compute.log',
            'pf9-virt': '/var/log/pf9/pf9-virt.log',
            'qemu': '/var/log/pf9/qemu.log'
        }
    
    async def get_ssh_connection(self, ssh_host: str) -> Optional[paramiko.SSHClient]:
        """Establish SSH connection directly to SSH host"""
        print(f"Connecting to SSH host: {ssh_host}")
        
        try:
            client = paramiko.SSHClient()
            # Load system known hosts; reject unknown hosts to prevent MITM attacks
            known_hosts_path = os.getenv('SSH_KNOWN_HOSTS', os.path.expanduser('~/.ssh/known_hosts'))
            if os.path.isfile(known_hosts_path):
                client.load_host_keys(known_hosts_path)
                client.set_missing_host_key_policy(paramiko.WarningPolicy())
            else:
                import warnings
                warnings.warn(
                    f"SSH known_hosts file not found at {known_hosts_path}. "
                    "Using WarningPolicy — set SSH_KNOWN_HOSTS env var for production.",
                    stacklevel=2,
                )
                client.set_missing_host_key_policy(paramiko.WarningPolicy())
            
            # Connect directly to SSH host (no mapping needed)
            if self.ssh_password:
                client.connect(
                    hostname=ssh_host,
                    username=self.ssh_user,
                    password=self.ssh_password,
                    timeout=10
                )
            elif self.ssh_key_path:
                client.connect(
                    hostname=ssh_host,
                    username=self.ssh_user,
                    key_filename=self.ssh_key_path,
                    timeout=10
                )
            else:
                raise Exception("No SSH authentication method configured (password or key)")
            
            print(f"SSH connection successful to {ssh_host}")
            return client
        except Exception as e:
            print(f"SSH connection failed to {ssh_host}: {e}")
            return None
    
    async def get_log_tail(self, ssh_host: str, log_type: str, lines: int = 100) -> Dict:
        """Get last N lines from a specific log file"""
        log_path = self.log_paths.get(log_type)
        if not log_path:
            return {"error": f"Unknown log type: {log_type}"}
        
        client = await self.get_ssh_connection(ssh_host)
        if not client:
            return {"error": f"Cannot connect to {ssh_host}"}
        
        try:
            # Use sudo to read log files as they may require root access
            command = f"sudo tail -n {lines} {log_path}"
            stdin, stdout, stderr = client.exec_command(command)
            
            content = stdout.read().decode('utf-8', errors='replace')
            error = stderr.read().decode('utf-8', errors='replace')
            
            if error and "No such file" in error:
                return {"error": f"Log file not found: {log_path}"}
            
            return {
                "host": ssh_host,
                "log_type": log_type,
                "log_path": log_path,
                "content": content,
                "lines": len(content.split('\n')) if content else 0,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"error": f"Failed to read log: {str(e)}"}
        finally:
            client.close()
    
    async def get_log_range(self, host: str, log_type: str, start_time: str, end_time: str) -> Dict:
        """Get log entries within a time range"""
        # This would require more complex parsing based on log format
        # For now, return recent logs with time filtering
        client = await self.get_ssh_connection(host)
        if not client:
            return {"error": f"Cannot connect to {host}"}
        
        log_path = self.log_paths.get(log_type)
        try:
            # Get logs from last 24 hours and filter by time range
            command = f"grep -n '{start_time[:10]}' {log_path} | tail -500"
            stdin, stdout, stderr = client.exec_command(command)
            
            content = stdout.read().decode('utf-8', errors='replace')
            
            return {
                "host": host,
                "log_type": log_type,
                "content": content,
                "filtered": True,
                "start_time": start_time,
                "end_time": end_time,
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"error": f"Failed to read log range: {str(e)}"}
        finally:
            client.close()
    
    async def list_available_logs(self, ssh_host: str) -> Dict:
        """List all available log files on a host"""
        client = await self.get_ssh_connection(ssh_host)
        if not client:
            return {"error": f"Cannot connect to {ssh_host}"}
        
        try:
            # Use sudo to access log directory as it may require root access
            command = "sudo ls -la /var/log/pf9/ 2>/dev/null || echo 'Directory not found'"
            stdin, stdout, stderr = client.exec_command(command)
            
            content = stdout.read().decode('utf-8', errors='replace')
            
            # Parse ls output to get file info
            log_files = []
            for line in content.split('\n'):
                if line.strip() and not line.startswith('total'):
                    parts = line.split()
                    if len(parts) >= 9 and parts[0].startswith('-'):  # Regular file
                        log_files.append({
                            "name": parts[8],
                            "size": parts[4],
                            "modified": " ".join(parts[5:8]),
                            "path": f"/var/log/pf9/{parts[8]}"
                        })
            
            return {
                "host": host,
                "log_files": log_files,
                "count": len(log_files),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"error": f"Failed to list logs: {str(e)}"}
        finally:
            client.close()

    async def search_logs(self, ssh_host: str, log_type: str, search_term: str, lines: int = 50) -> Dict:
        """Search for a term in log files"""
        log_path = self.log_paths.get(log_type)
        if not log_path:
            return {"error": f"Unknown log type: {log_type}"}
        
        client = await self.get_ssh_connection(ssh_host)
        if not client:
            return {"error": f"Cannot connect to {ssh_host}"}
        
        try:
            # Use sudo to search log files as they may require root access
            command = f"sudo grep -n -C 2 '{search_term}' {log_path} | tail -{lines}"
            stdin, stdout, stderr = client.exec_command(command)
            
            content = stdout.read().decode('utf-8', errors='replace')
            error = stderr.read().decode('utf-8', errors='replace')
            
            return {
                "host": host,
                "log_type": log_type,
                "search_term": search_term,
                "content": content,
                "matches": len([l for l in content.split('\n') if search_term in l]),
                "timestamp": datetime.now().isoformat()
            }
        except Exception as e:
            return {"error": f"Failed to search logs: {str(e)}"}
        finally:
            client.close()

# CLI interface for testing
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="PF9 Log Collector")
    parser.add_argument("--host", required=True, help="Compute host IP")
    parser.add_argument("--log", required=True, choices=['hostagent', 'neutron-agent', 'nova-compute', 'pf9-virt', 'qemu'], help="Log type")
    parser.add_argument("--lines", type=int, default=50, help="Number of lines to retrieve")
    parser.add_argument("--search", help="Search term")
    parser.add_argument("--list", action="store_true", help="List available log files")
    
    args = parser.parse_args()
    
    collector = PF9LogCollector()
    
    async def main():
        if args.list:
            result = await collector.list_available_logs(args.host)
        elif args.search:
            result = await collector.search_logs(args.host, args.log, args.search, args.lines)
        else:
            result = await collector.get_log_tail(args.host, args.log, args.lines)
        
        print(json.dumps(result, indent=2))
    
    asyncio.run(main())