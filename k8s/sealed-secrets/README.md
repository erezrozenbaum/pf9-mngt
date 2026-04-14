# Sealed Secrets — Production Secret Management

This directory contains **example commands and documentation** for creating
Bitnami Sealed Secrets that safely store credentials in the public git repo.

---

## Why Sealed Secrets?

A Sealed Secret is a Kubernetes `SealedSecret` CRD resource encrypted with
the cluster's public key.  The encrypted blob can be committed to a public
repository — only the Sealed Secrets controller running **inside your cluster**
can decrypt it.

---

## Prerequisites

```bash
# 1. Install the Sealed Secrets controller (once per cluster)
helm install sealed-secrets \
  oci://registry-1.docker.io/bitnamicharts/sealed-secrets \
  --namespace kube-system \
  --set fullnameOverride=sealed-secrets-controller

# 2. Install the kubeseal CLI
# macOS:   brew install kubeseal
# Linux:   https://github.com/bitnami-labs/sealed-secrets/releases
# Windows: scoop install kubeseal
```

---

## Creating Sealed Secrets

Run these commands **once** before the first `helm install`.

Replace every placeholder value (`<CHANGE_ME>`) with your real credentials.
The resulting `*.yaml` files in this directory are safe to commit.

### pf9-db-credentials

```bash
kubectl create secret generic pf9-db-credentials \
  --namespace pf9-mngt \
  --from-literal=password=<CHANGE_ME> \
  --dry-run=client -o yaml \
  | kubeseal --format yaml \
  > k8s/sealed-secrets/pf9-db-credentials.yaml
```

### pf9-jwt-secret

```bash
kubectl create secret generic pf9-jwt-secret \
  --namespace pf9-mngt \
  --from-literal=jwt-secret-key=<CHANGE_ME_min_32_chars> \
  --dry-run=client -o yaml \
  | kubeseal --format yaml \
  > k8s/sealed-secrets/pf9-jwt-secret.yaml
```

### pf9-admin-credentials

```bash
kubectl create secret generic pf9-admin-credentials \
  --namespace pf9-mngt \
  --from-literal=admin-password=<CHANGE_ME> \
  --dry-run=client -o yaml \
  | kubeseal --format yaml \
  > k8s/sealed-secrets/pf9-admin-credentials.yaml
```

### pf9-ldap-secrets

```bash
kubectl create secret generic pf9-ldap-secrets \
  --namespace pf9-mngt \
  --from-literal=admin-password=<CHANGE_ME> \
  --from-literal=config-password=<CHANGE_ME> \
  --from-literal=readonly-password=<CHANGE_ME> \
  --from-literal=sync-key=<CHANGE_ME> \
  --dry-run=client -o yaml \
  | kubeseal --format yaml \
  > k8s/sealed-secrets/pf9-ldap-secrets.yaml
```

### pf9-smtp-secrets (optional)

```bash
kubectl create secret generic pf9-smtp-secrets \
  --namespace pf9-mngt \
  --from-literal=password=<CHANGE_ME> \
  --dry-run=client -o yaml \
  | kubeseal --format yaml \
  > k8s/sealed-secrets/pf9-smtp-secrets.yaml
```

### pf9-pf9-credentials (OpenStack/Platform9 password)

```bash
kubectl create secret generic pf9-pf9-credentials \
  --namespace pf9-mngt \
  --from-literal=password=<CHANGE_ME> \
  --dry-run=client -o yaml \
  | kubeseal --format yaml \
  > k8s/sealed-secrets/pf9-pf9-credentials.yaml
```

### pf9-snapshot-creds (optional — only if snapshot worker is used)

```bash
kubectl create secret generic pf9-snapshot-creds \
  --namespace pf9-mngt \
  --from-literal=service-user-email=<CHANGE_ME> \
  --from-literal=password-key=<CHANGE_ME> \
  --from-literal=user-password-encrypted=<CHANGE_ME> \
  --from-literal=service-user-password=<CHANGE_ME> \
  --dry-run=client -o yaml \
  | kubeseal --format yaml \
  > k8s/sealed-secrets/pf9-snapshot-creds.yaml
```

### pf9-provision-creds (optional — only if VM provisioning is used)

```bash
kubectl create secret generic pf9-provision-creds \
  --namespace pf9-mngt \
  --from-literal=service-user-email=<CHANGE_ME> \
  --from-literal=password-key=<CHANGE_ME> \
  --from-literal=user-password-encrypted=<CHANGE_ME> \
  --dry-run=client -o yaml \
  | kubeseal --format yaml \
  > k8s/sealed-secrets/pf9-provision-creds.yaml
```

### pf9-tenant-portal-db-credentials (tenant portal DB role password — v1.84.0+)

```bash
kubectl create secret generic pf9-tenant-portal-db-credentials \
  --namespace pf9-mngt \
  --from-literal=password=<CHANGE_ME> \
  --dry-run=client -o yaml \
  | kubeseal --format yaml \
  > k8s/sealed-secrets/pf9-tenant-portal-db-credentials.yaml
```

> **Important:** The `<CHANGE_ME>` value must match the password set on the
> `tenant_portal_role` Postgres role via:
> `ALTER ROLE tenant_portal_role WITH PASSWORD '<CHANGE_ME>'`

### pf9-encryption-secrets (at-rest encryption keys)

This secret holds all Fernet keys used to encrypt data persisted to the
database.  Create it (or patch an existing secret) with the three keys below.

```bash
# Generate random keys
VM_PROVISION_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
SMTP_CONFIG_KEY=$(python3  -c "import secrets; print(secrets.token_hex(32))")
INTEGRATION_KEY=$(python3  -c "import secrets; print(secrets.token_hex(32))")

# Create / seal the secret
kubectl create secret generic pf9-encryption-secrets \
  --namespace pf9-mngt \
  --from-literal=vm-provision-key="$VM_PROVISION_KEY" \
  --from-literal=smtp-config-key="$SMTP_CONFIG_KEY" \
  --from-literal=integration-key="$INTEGRATION_KEY" \
  --dry-run=client -o yaml \
  | kubeseal --format yaml \
  > k8s/sealed-secrets/pf9-encryption-secrets.yaml
```

**Patching an existing live cluster** (adds `integration-key` to an already
deployed `pf9-encryption-secrets` without touching the other keys):

```bash
INTEGRATION_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
kubectl patch secret pf9-encryption-secrets -n pf9-mngt \
  --type='json' \
  -p="[{\"op\":\"add\",\"path\":\"/data/integration-key\",\"value\":\"$(printf '%s' "$INTEGRATION_KEY" | base64 | tr -d '\n')\"}]"

# Restart the API deployment to pick up the new env var
kubectl rollout restart deployment/pf9-api -n pf9-mngt

# Store the key value securely (e.g. in your password manager / private repo)
echo "integration-key: $INTEGRATION_KEY"
```

---

## Applying Sealed Secrets

```bash
# Apply all sealed secrets before helm install
kubectl apply -f k8s/sealed-secrets/

# Verify they were decrypted into regular Secrets by the controller
kubectl get secrets -n pf9-mngt
```

---

## Rotating a Secret

```bash
# Re-run the kubeseal command with the new value, then commit the updated yaml
# ArgoCD will pick up the change and controller will rotate the Secret
kubectl create secret generic pf9-db-credentials \
  --namespace pf9-mngt \
  --from-literal=password=<NEW_PASSWORD> \
  --dry-run=client -o yaml \
  | kubeseal --format yaml \
  > k8s/sealed-secrets/pf9-db-credentials.yaml

git add k8s/sealed-secrets/pf9-db-credentials.yaml
git commit -m "chore: rotate db credentials"
git push
```

---

## Sealed Secret YAML placement

The generated `*.yaml` files in **this directory** (`k8s/sealed-secrets/`) are
applied directly with `kubectl apply -f`, **not** managed by the Helm chart.
This is a deliberate choice: it keeps the sealed blobs independent of Helm
lifecycle hooks and avoids CRD availability ordering issues.

If you prefer ArgoCD to manage them too, add this directory as a second source
in `k8s/argocd/application.yaml` using the `sources:` multi-source syntax.
