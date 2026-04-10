import os
import json
import pytest
import requests

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_PF9_LIVE"),
    reason="requires TEST_PF9_LIVE=1 and a live PF9 endpoint",
)


def test_vmp():
    _user = os.environ["TEST_ADMIN_EMAIL"]
    _pass = os.environ["TEST_ADMIN_PASS"]
    _base = os.environ.get("TEST_BASE_URL", "http://localhost:8000")

    r = requests.post(f'{_base}/auth/login', json={'username': _user, 'password': _pass})
    token = r.json()['access_token']
    hdrs = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

    res = requests.get(f'{_base}/api/vm-provisioning/resources',
        params={'domain_name': 'Default', 'project_name': 'service'}, headers=hdrs, timeout=30).json()
    img = res['images'][0]
    fl = res['flavors'][0]
    net = res['networks'][0]
    print('image:', img['name'], '| flavor:', fl['name'], '| net:', net['name'])

    batch = {
        'name': 'Dry-run Test',
        'domain_name': 'Default',
        'project_name': 'service',
        'require_approval': True,
        'vms': [{
            'vm_name_suffix': 'web',
            'count': 1,
            'image_id': img['id'], 'image_name': img['name'],
            'flavor_id': fl['id'],  'flavor_name': fl['name'],
            'volume_gb': 20,
            'network_id': net['id'], 'network_name': net['name'],
            'security_groups': ['default'],
            'os_username': 'ubuntu',
            'os_password': os.environ.get('TEST_VM_OS_PASSWORD', 'ChangeMe')
        }]
    }
    r2 = requests.post(f'{_base}/api/vm-provisioning/batches', headers=hdrs, json=batch)
    bid = r2.json().get('batch_id')
    print('Batch ID:', bid)

    r3 = requests.post(f'{_base}/api/vm-provisioning/batches/' + str(bid) + '/dry-run', headers=hdrs, timeout=60)
    print('Dry-run HTTP:', r3.status_code)
    dr = r3.json()
    print('Dry-run result:', dr.get('status'))
    for vm in dr.get('results', {}).get('per_vm', []):
        print('  VM', vm['vm_name_suffix'])
        for ck in vm['checks']:
            sym = 'OK' if ck['status'] == 'ok' else ('WARN' if ck['status'] == 'warning' else 'ERR')
            print('   ', sym, ck['check'], ':', ck['detail'])
    for q in dr.get('results', {}).get('quota', []):
        print('  Quota', q['resource'], ': need', q['needed'], 'free', q['free'], '->', q['status'])

    # clean up
    requests.delete(f'{_base}/api/vm-provisioning/batches/' + str(bid), headers=hdrs)
    print('Cleaned up batch', bid)
