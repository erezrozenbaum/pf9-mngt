# QEMU Guest Agent Troubleshooting

## Problem: Password Reset Fails with "QEMU guest agent is not enabled"

When running the password reset runbook, you may encounter:
```
HTTP 409: {"conflictingRequest": {"code": 409, "message": "QEMU guest agent is not enabled"}}
```

This error occurs because Nova's `changePassword` API requires the QEMU guest agent to be running inside the target VM.

## Solution Options

### Option 1: Install QEMU Guest Agent in the VM (Recommended)

**For Ubuntu/Debian VMs:**
```bash
# SSH into the VM and run:
sudo apt update
sudo apt install qemu-guest-agent
sudo systemctl enable qemu-guest-agent
sudo systemctl start qemu-guest-agent
```

**For RHEL/CentOS VMs:**
```bash
# SSH into the VM and run:
sudo yum install qemu-guest-agent
# or for newer versions:
sudo dnf install qemu-guest-agent

sudo systemctl enable qemu-guest-agent
sudo systemctl start qemu-guest-agent
```

**Verify installation:**
```bash
sudo systemctl status qemu-guest-agent
```

### Option 2: Alternative Password Reset Methods

If you cannot install the QEMU guest agent, use these alternatives:

1. **SSH access with sudo:**
   ```bash
   ssh user@vm-ip
   sudo passwd username
   ```

2. **Cloud-init user-data** (for new VMs):
   Ensure VMs are provisioned with proper cloud-init user-data that sets passwords

3. **Console access + single-user mode** (Ubuntu):
   - Use the console link from the runbook (even if password reset failed)
   - Reboot and enter GRUB recovery mode
   - Reset password from recovery shell

### Option 3: Configure VM Images with QEMU Guest Agent Pre-installed

For future VM provisioning, modify your base images to include qemu-guest-agent:

```bash
# In your image preparation workflow:
sudo apt install qemu-guest-agent
sudo systemctl enable qemu-guest-agent
```

## Technical Details

The password reset runbook ([api/runbook_routes.py](api/runbook_routes.py#L1829)) calls:
```python
pw_resp = client.session.post(pw_url, headers=headers,
                              json={"changePassword": {"adminPass": new_password}})
```

This Nova API endpoint requires bidirectional communication with the VM via the QEMU guest agent channel.

## Prevention

- Include qemu-guest-agent in your standard VM image builds
- Document this requirement in your VM provisioning procedures
- Consider adding a pre-flight check to the runbook to verify guest agent availability