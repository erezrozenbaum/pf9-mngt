import requests

r = requests.post('http://localhost:8000/auth/login', json={'username':'admin@ccc.co.il', 'password':'r#1kajun'})
token = r.json()['access_token']
hdrs = {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'}

res = requests.get('http://localhost:8000/api/vm-provisioning/resources',
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
             'os_username': 'ubuntu', 'os_password': 'Ch@ngeMe123!'}]
}

# Create
r2 = requests.post('http://localhost:8000/api/vm-provisioning/batches', headers=hdrs, json=batch)
bid = r2.json()['batch_id']
print('Created batch:', bid)

# Dry-run
r3 = requests.post('http://localhost:8000/api/vm-provisioning/batches/' + str(bid) + '/dry-run', headers=hdrs, timeout=60)
print('Dry-run:', r3.json().get('status'))

# Submit for approval
r4 = requests.post('http://localhost:8000/api/vm-provisioning/batches/' + str(bid) + '/submit', headers=hdrs)
print('Submit:', r4.status_code, r4.json())

# Approve
r5 = requests.post('http://localhost:8000/api/vm-provisioning/batches/' + str(bid) + '/decision',
    headers=hdrs, json={'decision': 'approve', 'comment': 'Looks good'})
print('Approve:', r5.status_code, r5.json())

# Verify state
r6 = requests.get('http://localhost:8000/api/vm-provisioning/batches/' + str(bid), headers=hdrs)
b = r6.json()
print('Status:', b.get('status'), '| Approval:', b.get('approval_status'))

# Try reject on already approved (should still work)
r7 = requests.post('http://localhost:8000/api/vm-provisioning/batches/' + str(bid) + '/decision',
    headers=hdrs, json={'decision': 'reject', 'comment': 'Changed my mind'})
print('Re-reject:', r7.status_code, r7.json())

# Delete
requests.delete('http://localhost:8000/api/vm-provisioning/batches/' + str(bid), headers=hdrs)
print('Cleanup done')
