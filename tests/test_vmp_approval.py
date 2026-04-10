import os
import pytest
import requests

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_PF9_LIVE"),
    reason="requires TEST_PF9_LIVE=1 and a live PF9 endpoint",
)


def test_vmp_approval():
    _user = os.environ["TEST_ADMIN_EMAIL"]
    _pass = os.environ["TEST_ADMIN_PASS"]
    _base = os.environ.get("TEST_BASE_URL", "http://localhost:8000")

    r = requests.post(f'{_base}/auth/login', json={'username': _user, 'password': _pass})
    token = r.json()['access_token']
    hdrs = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

    res = requests.get(f'{_base}/api/vm-provisioning/resources',
        params={'domain_name': 'Default', 'project_name': 'service'}, headers=hdrs, timeout=30).json()
    img = res['images'][0]; fl = res['flavors'][0]; net = res['networks'][0]

    batch = {
        'name': 'Approval Flow Test',
        'domain_name': 'Default', 'project_name': 'service',
        'require_approval': True,
        'vms': [{'vm_name_suffix': 'flow', 'count': 1,
                 'image_id': img['id'], 'flavor_id': fl['id'],
                 'volume_gb': 20, 'network_id': net['id'],
                 'security_groups': ['default'],
                 'os_username': 'ubuntu', 'os_password': os.environ.get('TEST_VM_OS_PASSWORD', 'ChangeMe')}]
    }

    # Create
    r2 = requests.post(f'{_base}/api/vm-provisioning/batches', headers=hdrs, json=batch)
    bid = r2.json()['batch_id']
    print('Created batch:', bid)

    # Dry-run
    r3 = requests.post(f'{_base}/api/vm-provisioning/batches/' + str(bid) + '/dry-run', headers=hdrs, timeout=60)
    print('Dry-run:', r3.json().get('status'))

    # Submit for approval
    r4 = requests.post(f'{_base}/api/vm-provisioning/batches/' + str(bid) + '/submit', headers=hdrs)
    print('Submit:', r4.status_code, r4.json())

    # Approve
    r5 = requests.post(f'{_base}/api/vm-provisioning/batches/' + str(bid) + '/decision',
        headers=hdrs, json={'decision': 'approve', 'comment': 'Looks good'})
    print('Approve:', r5.status_code, r5.json())

    # Verify state
    r6 = requests.get(f'{_base}/api/vm-provisioning/batches/' + str(bid), headers=hdrs)
    b = r6.json()
    print('Status:', b.get('status'), '| Approval:', b.get('approval_status'))

    # Try reject on already approved (should still work)
    r7 = requests.post(f'{_base}/api/vm-provisioning/batches/' + str(bid) + '/decision',
        headers=hdrs, json={'decision': 'reject', 'comment': 'Changed my mind'})
    print('Re-reject:', r7.status_code, r7.json())

    # Delete
    requests.delete(f'{_base}/api/vm-provisioning/batches/' + str(bid), headers=hdrs)
    print('Cleanup done')
