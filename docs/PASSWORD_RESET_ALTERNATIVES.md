# Password Reset Alternatives When QEMU Guest Agent is Missing

## The Problem
The password reset runbook requires QEMU guest agent running inside the VM, but you can't install it because you don't have access to the VM (that's why you need to reset the password!).

## Solution 1: Console Access (Immediate)
Even if password reset fails, the runbook still provides a console URL. Use this for direct access:
1. Run the password reset runbook anyway
2. It will fail with "QEMU guest agent not enabled"  
3. But you'll get a noVNC/SPICE console link
4. Use that link to access the VM console directly
5. At the login prompt, use single-user mode to reset password

## Solution 2: Cloud-Init Password Reset (Next Boot)
For VMs that support cloud-init, you can inject a password reset script that runs on next boot:

```bash
# Create user-data script
cat > reset-password-user-data.yaml << 'EOF'
#cloud-config
users:
  - name: ubuntu  # or your username
    plain_text_passwd: 'NewSecurePassword123!'
    lock_passwd: false
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL

# Alternative: run a script to reset password
runcmd:
  - echo 'ubuntu:NewSecurePassword123!' | chpasswd
  - passwd -u ubuntu  # unlock account if locked
EOF

# Inject this user-data and reboot the VM via Nova API
```

## Solution 3: Create New SSH Key User
If the VM has cloud-init but password auth is disabled, create a new user with SSH keys:

```bash
cat > add-ssh-user-data.yaml << 'EOF'
#cloud-config
users:
  - name: recovery
    ssh_authorized_keys:
      - ssh-rsa AAAAB3NzaC... your-public-key-here
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
EOF
```

## Solution 4: Hypervisor Console Access
If the VM is on a hypervisor you can access:
1. Connect to the hypervisor host
2. Use `virsh console <vm-name>` (KVM) or equivalent
3. This bypasses the Nova console entirely

## Prevention
For future VMs, include qemu-guest-agent in your base images:
```bash
# Ubuntu/Debian
apt install qemu-guest-agent
systemctl enable qemu-guest-agent

# RHEL/CentOS  
yum install qemu-guest-agent
systemctl enable qemu-guest-agent
```

## Emergency Script (Advanced)
If you have Nova admin access, you can create a recovery script that:
1. Takes a snapshot of the broken VM
2. Launches a recovery VM with the snapshot as secondary disk
3. Mounts the snapshot, resets password via chroot
4. Creates new snapshot with fixed password
5. Launches new VM from fixed snapshot