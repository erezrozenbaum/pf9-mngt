# Platform9 Management System — Kubernetes Deployment Guide

**Version**: 4.0
**Last Updated**: March 2026
**Status**: Production Ready (v1.82.31)
**Minimum Kubernetes**: 1.28

> **This guide is written from real deployment experience.** Every warning in it
> hit us in production. Follow the steps in order — skipping ahead causes failures
> that are hard to diagnose.

---

## Table of Contents

1. [Before You Start — Know Your Cluster](#1-before-you-start--know-your-cluster)
2. [Cluster Add-ons](#2-cluster-add-ons)
3. [DNS Setup](#3-dns-setup)
4. [Generate Your Credential Values](#4-generate-your-credential-values)
5. [Create the Namespace](#5-create-the-namespace)
6. [Create All Secrets](#6-create-all-secrets)
7. [Deploy the App — Helm Install](#7-deploy-the-app--helm-install)
8. [Database Migration](#8-database-migration)
9. [Create the First LDAP Admin User](#9-create-the-first-ldap-admin-user)
10. [Verify and First Login](#10-verify-and-first-login)
11. [Optional: Monitoring Stack — Prometheus, Grafana, Loki](#11-optional-monitoring-stack)
12. [GitOps with ArgoCD](#12-gitops-with-argocd)
13. [Day-2 Operations](#13-day-2-operations)
14. [Common Issues & Fixes](#14-common-issues--fixes)
15. [Architecture Decision Records](#15-architecture-decision-records)

---

## 1. Before You Start — Know Your Cluster

**Do these checks first. Every problem that caused hours of debugging traces back to
skipping this step.**

### 1.1 What storage classes does your cluster have?

```bash
kubectl get storageclass
```

You will see output like:

```
NAME                 PROVISIONER            RECLAIMPOLICY   VOLUMEBINDINGMODE
standard (default)   rancher.io/local-path  Delete          WaitForFirstConsumer
nfs-pf9              nfs-provisioner        Delete          Immediate
```

**Write down the name of your storage class.** You will need it in two places:
- `helm upgrade ... --set postgresql.persistence.storageClass=<YOUR-CLASS>`
- `k8s/monitoring/prometheus-values.yaml` (for the monitoring stack PVCs)

> **If you skip this**, all your PVCs will stay in `Pending` forever and every pod
> will fail to start. This is the #1 silent killer for first-time installs.

> **NFS users**: NFS is fully supported but has one known issue — Grafana's
> `init-chown-data` init container runs `chown -R` on the volume, which fails on
> NFS because of a read-only `.snapshot` directory. See §11 for the fix.

### 1.2 Does your cluster support LoadBalancer services?

```bash
# Managed clusters (EKS, GKE, AKS): LoadBalancer works out of the box.
# Bare-metal / on-premises: you need MetalLB or you must switch to NodePort.
kubectl get nodes -o wide   # note your node IPs for NodePort fallback
```

If your cluster is bare-metal and has no LoadBalancer support, install MetalLB:
```bash
kubectl apply -f https://raw.githubusercontent.com/metallb/metallb/main/config/manifests/metallb-native.yaml
# Then configure an IPAddressPool with IPs from your network range.
# See https://metallb.universe.tf/configuration/
```

### 1.3 Cluster requirements checklist

| Requirement | Minimum |
|-------------|---------|
| Kubernetes version | 1.28+ |
| Helm | 3.12+ |
| Nodes | 3 (1 control-plane + 2 workers recommended) |
| RAM per worker node | 8 GB |
| CPU per worker node | 4 cores |
| Storage | PVC-capable StorageClass (see §1.1) |
| Tools on your workstation | `kubectl`, `helm`, `kubeseal`, `openssl`, `python3` |

---

## 2. Cluster Add-ons

Install these **before** the Helm chart. Check each one is healthy before moving on.

### 2.1 ingress-nginx (required)

```bash
helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
helm repo update
helm install ingress-nginx ingress-nginx/ingress-nginx \
  --namespace ingress-nginx --create-namespace

# Verify — wait until the controller pod is Running
kubectl get pods -n ingress-nginx
kubectl get svc -n ingress-nginx
```

You need to see a LoadBalancer service with an EXTERNAL-IP assigned. **Save that IP** — it is
the address you point all your DNS records at.

```
NAME                               TYPE           EXTERNAL-IP
ingress-nginx-controller           LoadBalancer   203.0.113.10   ← your cluster IP
```

### 2.2 cert-manager (required for HTTPS)

```bash
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml

# Wait for all 3 pods to be Running (takes ~30 seconds)
kubectl get pods -n cert-manager --watch
```

Create the Let's Encrypt ClusterIssuer — replace the email address:

```yaml
# letsencrypt-issuer.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: ops@your-domain.com          # ← change this
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
      - http01:
          ingress:
            class: nginx
```

```bash
kubectl apply -f letsencrypt-issuer.yaml
kubectl describe clusterissuer letsencrypt-prod   # should say "The ACME account was registered"
```

### 2.3 Sealed Secrets controller (required)

```bash
helm install sealed-secrets \
  oci://registry-1.docker.io/bitnamicharts/sealed-secrets \
  --namespace kube-system \
  --set fullnameOverride=sealed-secrets-controller

# Verify
kubectl get pods -n kube-system -l app.kubernetes.io/name=sealed-secrets

# Fetch the cluster's public key — store this file, you need it every time you create a secret
kubeseal --fetch-cert \
  --controller-name=sealed-secrets-controller \
  --controller-namespace=kube-system > sealed-secrets.pub
```

> Keep `sealed-secrets.pub` somewhere safe on your workstation. If you lose it you
> can always re-fetch it with the same command above (as long as the controller is running).

### 2.4 ArgoCD (optional — only for GitOps auto-sync)

```bash
kubectl create namespace argocd
kubectl apply -n argocd \
  -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml

# Wait for all pods Running
kubectl get pods -n argocd --watch

# Get initial admin password
kubectl -n argocd get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d; echo
```

---

## 3. DNS Setup

Point a DNS A record at the EXTERNAL-IP you noted in §2.1:

```
your-app.your-domain.com.   A   203.0.113.10
```

**Important**: The DNS record must be live and propagated **before** cert-manager can issue
a TLS certificate via the ACME HTTP-01 challenge.

To verify propagation from your workstation:
```bash
nslookup your-app.your-domain.com
# Should return the ingress-nginx EXTERNAL-IP
```

> **No public DNS?** For an internal cluster accessible only on your LAN, add the record
> to your internal DNS server (e.g. Windows DNS, Bind, or Pi-hole). You will need to use
> a self-signed certificate or skip TLS — set `ingress.tls.enabled: false` in values.

---

## 4. Generate Your Credential Values

Generate all secrets **before** creating any Kubernetes resources.
Keep these values in a local password manager — never commit them to git.

```bash
# PostgreSQL password (used by the DB and all services that connect to it)
openssl rand -base64 32
# → save as: DB_PASSWORD

# JWT signing key — minimum 32 characters, must be the same across all API replicas
openssl rand -base64 64
# → save as: JWT_SECRET_KEY

# LDAP admin password (for the OpenLDAP server admin bind)
openssl rand -base64 24
# → save as: LDAP_ADMIN_PASSWORD

# LDAP config password (phpLDAPadmin / olcRootPW for cn=config)
openssl rand -base64 24
# → save as: LDAP_CONFIG_PASSWORD

# LDAP readonly password (used by the API for LDAP searches)
openssl rand -base64 24
# → save as: LDAP_READONLY_PASSWORD

# LDAP sync key — encrypts bind passwords at rest in the DB (MUST be exactly 32 URL-safe base64 bytes)
python3 -c "import os, base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"
# → save as: LDAP_SYNC_KEY

# pf9-mngt first admin password (initial login to the web UI)
openssl rand -base64 24
# → save as: ADMIN_PASSWORD

# Platform9 / OpenStack service account password (the account pf9-mngt uses to call the APIs)
# → use the password of your Platform9 service account: save as PF9_PASSWORD
```

**What each secret is used for:**

| Secret | Used by | Notes |
|--------|---------|-------|
| `DB_PASSWORD` | PostgreSQL, API, all workers | All services share one DB user (`pf9`) |
| `JWT_SECRET_KEY` | API | Signs login tokens; changing it logs everyone out |
| `LDAP_ADMIN_PASSWORD` | OpenLDAP container, API admin bind | Used to create/manage LDAP users |
| `LDAP_CONFIG_PASSWORD` | OpenLDAP cn=config | Internal LDAP server config; rarely used directly |
| `LDAP_READONLY_PASSWORD` | API LDAP search bind | Read-only service account for auth lookups |
| `LDAP_SYNC_KEY` | ldap-sync-worker, API | AES encryption key for LDAP bind passwords stored in DB |
| `ADMIN_PASSWORD` | API first-run bootstrap | Password for the initial `admin` user in the web UI |
| `PF9_PASSWORD` | API, scheduler-worker | Calls Platform9 / OpenStack APIs |

---

## 5. Create the Namespace

The namespace must exist before you apply Sealed Secrets (they are namespace-scoped).

```bash
kubectl create namespace pf9-mngt
```

---

## 6. Create All Secrets

These commands seal your credentials with the cluster's public key.
The resulting `*.yaml` files are safe to commit to your (private) deploy repo.

> **Order matters.** Do not start the Helm install until all required secrets exist.
> The API and workers crash immediately if a required secret is missing.

### Required secrets (must create all of these)

**pf9-db-credentials** — PostgreSQL password
```bash
kubectl create secret generic pf9-db-credentials \
  --namespace pf9-mngt \
  --from-literal=password='<DB_PASSWORD>' \
  --dry-run=client -o yaml \
  | kubeseal --cert sealed-secrets.pub --format yaml \
  > k8s/sealed-secrets/pf9-db-credentials.yaml
kubectl apply -f k8s/sealed-secrets/pf9-db-credentials.yaml
```

**pf9-jwt-secret** — JWT signing key
```bash
kubectl create secret generic pf9-jwt-secret \
  --namespace pf9-mngt \
  --from-literal=jwt-secret-key='<JWT_SECRET_KEY>' \
  --dry-run=client -o yaml \
  | kubeseal --cert sealed-secrets.pub --format yaml \
  > k8s/sealed-secrets/pf9-jwt-secret.yaml
kubectl apply -f k8s/sealed-secrets/pf9-jwt-secret.yaml
```

**pf9-ldap-secrets** — all four LDAP credentials in one secret
```bash
kubectl create secret generic pf9-ldap-secrets \
  --namespace pf9-mngt \
  --from-literal=admin-password='<LDAP_ADMIN_PASSWORD>' \
  --from-literal=config-password='<LDAP_CONFIG_PASSWORD>' \
  --from-literal=readonly-password='<LDAP_READONLY_PASSWORD>' \
  --from-literal=sync-key='<LDAP_SYNC_KEY>' \
  --dry-run=client -o yaml \
  | kubeseal --cert sealed-secrets.pub --format yaml \
  > k8s/sealed-secrets/pf9-ldap-secrets.yaml
kubectl apply -f k8s/sealed-secrets/pf9-ldap-secrets.yaml
```

> **Missing sync-key is the #1 cause of worker CrashLoopBackOff.** If workers start
> crashing with `ldap_sync_key secret is not set`, this is why. The sync-key must be
> exactly the output of the python3 command in §4 — a URL-safe base64 string, 44 chars.

**pf9-admin-credentials** — first web UI admin password
```bash
kubectl create secret generic pf9-admin-credentials \
  --namespace pf9-mngt \
  --from-literal=admin-password='<ADMIN_PASSWORD>' \
  --dry-run=client -o yaml \
  | kubeseal --cert sealed-secrets.pub --format yaml \
  > k8s/sealed-secrets/pf9-admin-credentials.yaml
kubectl apply -f k8s/sealed-secrets/pf9-admin-credentials.yaml
```

**pf9-pf9-credentials** — Platform9 / OpenStack service account
```bash
kubectl create secret generic pf9-pf9-credentials \
  --namespace pf9-mngt \
  --from-literal=password='<PF9_PASSWORD>' \
  --dry-run=client -o yaml \
  | kubeseal --cert sealed-secrets.pub --format yaml \
  > k8s/sealed-secrets/pf9-pf9-credentials.yaml
kubectl apply -f k8s/sealed-secrets/pf9-pf9-credentials.yaml
```

### Optional secrets (create only if you use these features)

**pf9-smtp-secrets** — for email notifications
```bash
kubectl create secret generic pf9-smtp-secrets \
  --namespace pf9-mngt \
  --from-literal=password='<SMTP_PASSWORD>' \
  --dry-run=client -o yaml \
  | kubeseal --cert sealed-secrets.pub --format yaml \
  > k8s/sealed-secrets/pf9-smtp-secrets.yaml
kubectl apply -f k8s/sealed-secrets/pf9-smtp-secrets.yaml
```

**pf9-snapshot-creds** — for the snapshot worker

> **Why the email goes here, not in `values.yaml`:** The service user email identifies your
> organisation in public repository history. Storing it in a sealed secret keeps the repo clean
> and lets each environment use its own account without touching `values.yaml`.

```bash
kubectl create secret generic pf9-snapshot-creds \
  --namespace pf9-mngt \
  --from-literal=service-user-email='<SNAPSHOT_SERVICE_USER_EMAIL>' \
  --from-literal=password-key='<SNAPSHOT_PASSWORD_KEY>' \
  --from-literal=user-password-encrypted='<SNAPSHOT_USER_PASSWORD_ENCRYPTED>' \
  --from-literal=service-user-password='<SNAPSHOT_SERVICE_USER_PASSWORD>' \
  --dry-run=client -o yaml \
  | kubeseal --cert sealed-secrets.pub --format yaml \
  > k8s/sealed-secrets/pf9-snapshot-creds.yaml
kubectl apply -f k8s/sealed-secrets/pf9-snapshot-creds.yaml
```

**pf9-provision-creds** — for the VM provisioning service user

> **Why the email goes here, not in `values.yaml`:** The service user email identifies your
> organisation in public repository history. Storing it in a sealed secret keeps the repo clean
> and lets each environment use its own account without touching `values.yaml`.

```bash
kubectl create secret generic pf9-provision-creds \
  --namespace pf9-mngt \
  --from-literal=service-user-email='<PROVISION_SERVICE_USER_EMAIL>' \
  --from-literal=password-key='<PROVISION_PASSWORD_KEY>' \
  --from-literal=user-password-encrypted='<PROVISION_USER_PASSWORD_ENCRYPTED>' \
  --dry-run=client -o yaml \
  | kubeseal --cert sealed-secrets.pub --format yaml \
  > k8s/sealed-secrets/pf9-provision-creds.yaml
kubectl apply -f k8s/sealed-secrets/pf9-provision-creds.yaml
```

**pf9-copilot-secrets** — for the AI Copilot feature
```bash
kubectl create secret generic pf9-copilot-secrets \
  --namespace pf9-mngt \
  --from-literal=openai-api-key='<OPENAI_KEY>' \
  --from-literal=anthropic-api-key='<ANTHROPIC_KEY>' \
  --dry-run=client -o yaml \
  | kubeseal --cert sealed-secrets.pub --format yaml \
  > k8s/sealed-secrets/pf9-copilot-secrets.yaml
kubectl apply -f k8s/sealed-secrets/pf9-copilot-secrets.yaml
```

**pf9-metrics-secret** — API key for `/metrics` and `/worker-metrics` endpoints *(v1.93.18+)*
```bash
METRICS_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
kubectl create secret generic pf9-metrics-secret \
  --namespace pf9-mngt \
  --from-literal=metrics-api-key="${METRICS_KEY}" \
  --dry-run=client -o yaml \
  | kubeseal --cert sealed-secrets.pub --format yaml \
  > k8s/sealed-secrets/metrics-secret.yaml
kubectl apply -f k8s/sealed-secrets/metrics-secret.yaml
```
> Store the value of `$METRICS_KEY` securely — you will need it in the `X-Metrics-Key` header
> when querying `/metrics` or `/worker-metrics`. The sealed YAML is committed to the private
> deploy repo (`sealed-secrets/metrics-secret.yaml`).

### Verify all secrets exist before proceeding

```bash
kubectl get secrets -n pf9-mngt
# Must see: pf9-db-credentials, pf9-jwt-secret, pf9-ldap-secrets,
#           pf9-admin-credentials, pf9-pf9-credentials,
#           pf9-snapshot-creds, pf9-provision-creds
```

---

## 7. Deploy the App — Helm Install

```bash
helm upgrade --install pf9-mngt ./k8s/helm/pf9-mngt \
  --namespace pf9-mngt \
  --create-namespace \
  -f k8s/helm/pf9-mngt/values.yaml \
  --set ingress.host=your-app.your-domain.com \
  --set ingress.tls.enabled=true \
  --set ingress.tls.clusterIssuer=letsencrypt-prod \
  --set postgresql.persistence.storageClass=<YOUR-STORAGE-CLASS> \
  --set ldapService.persistence.data.storageClass=<YOUR-STORAGE-CLASS> \
  --set ldapService.persistence.config.storageClass=<YOUR-STORAGE-CLASS> \
  --set workers.backupWorker.persistence.storageClass=<YOUR-STORAGE-CLASS> \
  --set pf9.authUrl=https://your-cloud.platform9.net/keystone \
  --set pf9.username=service-account@your-domain.com \
  --wait --timeout 10m
```

> **`--set postgresql.persistence.storageClass`** is the single most important override.
> Without it, PVCs use the chart default which may not match your cluster and will stay
> in `Pending` forever. Set it to the value you found in §1.1.

### Watch the rollout

```bash
# Watch pods come up (Ctrl+C when all are Running)
kubectl get pods -n pf9-mngt --watch

# Expected final state
NAME                                        READY   STATUS      RESTARTS
pf9-mngt-api-xxxx                           1/1     Running     0
pf9-mngt-ui-xxxx                            1/1     Running     0
pf9-mngt-monitoring-xxxx                    1/1     Running     0
pf9-mngt-redis-xxxx                         1/1     Running     0
pf9-mngt-db-0                               1/1     Running     0
pf9-mngt-ldap-0                             1/1     Running     0
pf9-mngt-backup-worker-xxxx                 1/1     Running     0
pf9-mngt-ldap-sync-worker-xxxx              1/1     Running     0
pf9-mngt-metering-worker-xxxx               1/1     Running     0
pf9-mngt-notification-worker-xxxx           1/1     Running     0
pf9-mngt-scheduler-worker-xxxx              1/1     Running     0
pf9-mngt-search-worker-xxxx                 1/1     Running     0
pf9-mngt-snapshot-worker-xxxx               1/1     Running     0
pf9-mngt-db-migrate-xxxx                    0/1     Completed   0   ← this is correct
```

> If any pod is stuck in `Pending`, `CrashLoopBackOff`, or `Init:Error` — stop here and
> see §14 before continuing. Do not proceed to the database migration step until all pods
> are Running (or Completed for the db-migrate job).

---

## 8. Database Migration

### How it works

The `db-migrate` Job runs automatically as part of `helm install` and `helm upgrade`.
It uses the API container image to execute `run_migration.py`, which:

1. Connects to PostgreSQL using the credentials from `pf9-db-credentials`
2. Applies `db/init.sql` if it hasn't been applied yet (creates base tables)
3. Reads every `db/migrate_*.sql` file, sorted by name
4. Skips files already recorded in `schema_migrations` table (idempotent — safe to re-run)
5. Applies each new file and records it in `schema_migrations`

There are currently **~55 migration files**, all applied in alphabetical order.

### Watching the migration run

```bash
# Find the job name
kubectl get jobs -n pf9-mngt

# Stream the logs as it runs
kubectl logs -n pf9-mngt -l app.kubernetes.io/component=db-migrate -f

# When done, status should show Completed
kubectl get jobs -n pf9-mngt
```

The migration takes 20–60 seconds on first install (all 55 files). Subsequent upgrades
take a few seconds (only new files run).

### What success looks like

```
Applying db/init.sql ... OK
Applying db/migrate_activity_log.sql ... OK
Applying db/migrate_backup.sql ... OK
...
Applying db/migrate_v1_82_18.sql ... OK
All migrations applied. 55 files processed, 55 applied, 0 skipped.
```

### Common migration failures and fixes

**Job stuck in `Init:0/1` — database not ready yet**

The job has an init container (`wait-for-db`) that retries the PostgreSQL connection for up
to 5 minutes. During a first install on NFS, the PostgreSQL pod can take 2–3 minutes to
write its data directory, which is normal.

```bash
# Check if pf9-db is still starting
kubectl get pods -n pf9-mngt -l app.kubernetes.io/name=pf9-mngt-db

# Watch init container progress
kubectl logs -n pf9-mngt -l app.kubernetes.io/component=db-migrate -c wait-for-db -f
```

If the job times out (`DeadlineExceeded`) before the DB came up:
```bash
# 1. Delete the failed job
kubectl delete job -n pf9-mngt -l app.kubernetes.io/component=db-migrate

# 2. Trigger the job again (Helm hook re-runs on sync)
#    With ArgoCD:
argocd app sync pf9-mngt
#    Without ArgoCD (manual re-run):
helm upgrade pf9-mngt ./k8s/helm/pf9-mngt -n pf9-mngt --reuse-values
```

**`pf9-db-credentials` secret missing**

```
psycopg2.OperationalError: FATAL: password authentication failed for user "pf9"
```

Verify the secret exists and has the right key:
```bash
kubectl get secret pf9-db-credentials -n pf9-mngt -o jsonpath='{.data.password}' | base64 -d
# Should print your DB_PASSWORD
```

If missing, create it (see §6) then delete the failed job and re-run.

**Migration file fails halfway through**

All migration files use `CREATE TABLE IF NOT EXISTS` and `CREATE INDEX IF NOT EXISTS` —
they are safe to re-run. If a file fails:

```bash
# See exactly which SQL statement failed
kubectl logs -n pf9-mngt -l app.kubernetes.io/component=db-migrate | grep -A5 "ERROR"
```

Fix the underlying issue (e.g. missing secret, wrong DB user permissions), delete the job,
and re-run. Already-applied files are skipped automatically.

**The job ran on a broken state and now the schema is inconsistent**

```bash
# Connect directly to check what was applied
kubectl exec -it -n pf9-mngt pf9-mngt-db-0 -- \
  psql -U pf9 -d pf9_mgmt -c "SELECT filename, applied_at FROM schema_migrations ORDER BY applied_at;"
```

If you need a clean start (development only — destructive):
```bash
# Drop and recreate the database
kubectl exec -it -n pf9-mngt pf9-mngt-db-0 -- \
  psql -U pf9 -c "DROP DATABASE pf9_mgmt; CREATE DATABASE pf9_mgmt;"
# Then delete the job and re-run
kubectl delete job -n pf9-mngt -l app.kubernetes.io/component=db-migrate
helm upgrade pf9-mngt ./k8s/helm/pf9-mngt -n pf9-mngt --reuse-values
```

---

## 9. Create the First LDAP Admin User

After the pods are Running and the db-migrate job has Completed, create the initial admin
user. This user will be used to log in to the web UI for the first time.

```bash
# 1. Get the LDAP pod name
LDAP_POD=$(kubectl get pod -n pf9-mngt -l app.kubernetes.io/name=pf9-mngt-ldap \
  -o jsonpath='{.items[0].metadata.name}')

# 2. Check LDAP is running
kubectl exec -n pf9-mngt $LDAP_POD -- ldapsearch \
  -x -H ldap://localhost:389 \
  -D "cn=admin,dc=pf9mgmt,dc=local" \
  -w "$LDAP_ADMIN_PASSWORD" \
  -b "dc=pf9mgmt,dc=local" \
  "(objectClass=organizationalUnit)" dn 2>&1 | head -20
# Should return: dn: ou=users,dc=pf9mgmt,dc=local

# 3. Create a temporary ldif file inside the pod and add the admin user
kubectl exec -n pf9-mngt $LDAP_POD -- bash -c "cat > /tmp/admin_user.ldif << 'LDIF'
dn: cn=admin,ou=users,dc=pf9mgmt,dc=local
objectClass: person
objectClass: organizationalPerson
objectClass: inetOrgPerson
cn: admin
sn: admin
uid: admin
mail: admin@your-domain.com
userPassword: <YOUR_ADMIN_PASSWORD>
LDIF"

# 4. Add the user
kubectl exec -n pf9-mngt $LDAP_POD -- \
  ldapadd -x \
  -H ldap://localhost:389 \
  -D "cn=admin,dc=pf9mgmt,dc=local" \
  -w "<LDAP_ADMIN_PASSWORD>" \
  -f /tmp/admin_user.ldif
```

Expected output:
```
adding new entry "cn=admin,ou=users,dc=pf9mgmt,dc=local"
```

If you see `Already exists` — the user was created already (this is fine).

> **After you can log in**, go to Administration → Users in the web UI to manage users
> from there. The LDAP approach above is only needed for the very first login.

---

## 10. Verify and First Login

```bash
# All pods Running?
kubectl get pods -n pf9-mngt

# Ingress has an address?
kubectl get ingress -n pf9-mngt

# TLS certificate issued?
kubectl describe certificate -n pf9-mngt

# API health check
curl https://your-app.your-domain.com/health
# Expected: {"status": "ok", ...}
```

Open your browser: **`https://your-app.your-domain.com`**

- **Username**: `admin`
- **Password**: the `ADMIN_PASSWORD` you generated in §4

> Change the admin password immediately after first login via Profile → Change Password.

---

## 11. Optional: Monitoring Stack

These are installed separately as Helm charts in a dedicated `monitoring` namespace.
They are **not** managed by the `pf9-mngt` Helm chart.

### 11.1 Install kube-prometheus-stack (Prometheus + Grafana + AlertManager)

The values file `k8s/monitoring/prometheus-values.yaml` is pre-configured for this stack.
Edit it before installing:

```bash
# Check the file and set your storage class if it differs from nfs-pf9
grep storageClassName k8s/monitoring/prometheus-values.yaml
```

> **NFS users — critical**: The file already has `grafana.initChownData.enabled: false`.
> Do NOT remove this. On NFS clusters, the default Grafana init container runs
> `chown -R 472 /var/lib/grafana` which hits a read-only `.snapshot` directory
> and crashes. This setting disables that init container. Leave it in place.

```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

helm install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace \
  -f k8s/monitoring/prometheus-values.yaml \
  --set "grafana.ingress.hosts[0]=your-app.your-domain.com" \
  --set "grafana.env.GF_SERVER_ROOT_URL=https://your-app.your-domain.com/grafana" \
  --set "prometheus.ingress.hosts[0]=your-app.your-domain.com" \
  --set "alertmanager.ingress.hosts[0]=your-app.your-domain.com" \
  --timeout 10m
```

### 11.2 Install Loki + Promtail (log aggregation)

```bash
helm repo add grafana https://grafana.github.io/helm-charts
helm repo update

helm install loki grafana/loki-stack \
  -n monitoring \
  -f k8s/monitoring/loki-values.yaml \
  --timeout 5m
```

### 11.3 Verify all monitoring pods are Running

```bash
kubectl get pods -n monitoring
```

Expected (all Running):
```
alertmanager-kube-prometheus-stack-alertmanager-0     2/2   Running
kube-prometheus-stack-grafana-xxxx                    3/3   Running
kube-prometheus-stack-kube-state-metrics-xxxx         1/1   Running
kube-prometheus-stack-operator-xxxx                   1/1   Running
kube-prometheus-stack-prometheus-node-exporter-xxxx   1/1   Running   (one per node)
loki-0                                                 1/1   Running
loki-promtail-xxxx                                     1/1   Running   (one per node)
prometheus-kube-prometheus-stack-prometheus-0          2/2   Running
```

> **If Grafana is in `Init:CrashLoopBackOff`** on NFS — check that
> `initChownData.enabled: false` is in the values file and run:
> `helm upgrade kube-prometheus-stack ... --set grafana.initChownData.enabled=false`

### 11.4 Access Grafana and the other tools

The default values file exposes all three tools via subpaths on your existing domain.
No new DNS record is needed.

| Tool | URL | Default credentials |
|------|-----|---------------------|
| Grafana | `https://your-app.your-domain.com/grafana` | `admin` / set in values file |
| Prometheus | `https://your-app.your-domain.com/prometheus` | none (no auth) |
| AlertManager | `https://your-app.your-domain.com/alertmanager` | none (no auth) |

**Change the Grafana admin password immediately after first login.**

### 11.5 Verify Grafana data sources

1. Go to **Connections → Data Sources**
2. Both `Prometheus` and `Loki` should appear
3. Click each → **Save & Test** → both should show "Data source connected"

If Loki shows an error, check the URL in the datasource config matches
`http://loki.monitoring.svc.cluster.local:3100`.

### 11.7 Application alert rules

The Helm chart deploys a `PrometheusRule` resource (`pf9-mngt-alerts`) into the `pf9-mngt` namespace. It is gated by `alerting.enabled: true` (the default). The rules cover:

| Alert | Severity | Condition |
|-------|----------|-----------|
| `PodCrashLooping` | critical | Pod restarts > 3 in 1 hour |
| `DeploymentUnavailable` | critical | A deployment has 0 available replicas for > 2 min |
| `APIHighLatency` | warning | p99 API response time > 2 s for 5 min |
| `DBConnectionPoolNearExhaustion` | warning | > 80 % of DB connections in use for 5 min |
| `DBConnectionPoolExhausted` | critical | 100 % of DB connections in use for 2 min |
| `WorkerNotHeartbeating` | critical | A worker container not ready for 10 min |

To disable alert rules: set `alerting.enabled: false` in `values.prod.yaml`.

### 11.6 Upgrading the monitoring stack

```bash
# Copy updated values file to the cluster control plane, then:
helm upgrade kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  -n monitoring \
  -f ~/prometheus-values.yaml \
  --set "grafana.ingress.hosts[0]=your-app.your-domain.com" \
  --set "grafana.env.GF_SERVER_ROOT_URL=https://your-app.your-domain.com/grafana" \
  --set "prometheus.ingress.hosts[0]=your-app.your-domain.com" \
  --set "alertmanager.ingress.hosts[0]=your-app.your-domain.com" \
  --timeout 5m
```

---

## 12. GitOps with ArgoCD

GitOps uses two repos:

| Repo | Visibility | Contents |
|------|------------|----------|
| `pf9-mngt` (this repo) | Public | Helm chart, application code, CI workflows |
| `pf9-mngt-deploy` | **Private** | `values.prod.yaml`, sealed-secret blobs, ArgoCD manifests |

### Bootstrap (one time)

```bash
# Register the private deploy repo with ArgoCD
argocd repo add https://github.com/<your-org>/pf9-mngt-deploy \
  --username <github-user> \
  --password <GITHUB_PAT>

# Apply AppProject and Application from the init directory
kubectl apply -f k8s/deploy-repo-init/argocd-appproject.yaml -n argocd
kubectl apply -f k8s/deploy-repo-init/argocd-application.yaml -n argocd
```

### Fix: ArgoCD permanently OutOfSync on StatefulSets

After the first deploy you may notice `pf9-db` and `pf9-ldap` show as OutOfSync in ArgoCD.
This is a known Kubernetes limitation: `volumeClaimTemplates` in StatefulSets are immutable
after creation. ArgoCD sees a diff but cannot fix it.

The fix is already in `k8s/argocd/application.yaml` as `ignoreDifferences`:
```yaml
ignoreDifferences:
  - group: apps
    kind: StatefulSet
    jsonPointers:
      - /spec/volumeClaimTemplates
```

If your ArgoCD app was applied before this was added, patch it:
```bash
kubectl patch application pf9-mngt -n argocd \
  --type merge \
  --patch '{"spec":{"ignoreDifferences":[{"group":"apps","kind":"StatefulSet","jsonPointers":["/spec/volumeClaimTemplates"]}]}}'
```

### GitHub secrets required for CI

| Name | Type | Purpose |
|------|------|---------|
| `RELEASE_PAT` | Secret | GitHub Personal Access Token (repo scope) for pushing image tag updates to the private deploy repo |
| `DEPLOY_REPO` | Variable | Name of your private deploy repo (e.g. `pf9-mngt-deploy`) |

---

## 13. Day-2 Operations

### Upgrade a release

```bash
helm upgrade pf9-mngt ./k8s/helm/pf9-mngt \
  --namespace pf9-mngt \
  -f k8s/helm/pf9-mngt/values.yaml \
  --reuse-values \
  --wait --timeout 10m
```

The db-migrate job runs automatically before pods are replaced.

### Rollback

```bash
helm history pf9-mngt -n pf9-mngt
helm rollback pf9-mngt -n pf9-mngt        # rolls back one revision
helm rollback pf9-mngt 3 -n pf9-mngt      # rolls back to revision 3
```

> Helm rollback does NOT reverse database migrations. If a migration broke the schema,
> restore from a PostgreSQL backup first.

### Rotate a secret

```bash
# 1. Re-seal with new value
kubectl create secret generic pf9-jwt-secret \
  --namespace pf9-mngt \
  --from-literal=jwt-secret-key='<new-value>' \
  --dry-run=client -o yaml \
  | kubeseal --cert sealed-secrets.pub --format yaml \
  > k8s/sealed-secrets/pf9-jwt-secret.yaml

# 2. Apply
kubectl apply -f k8s/sealed-secrets/pf9-jwt-secret.yaml

# 3. Restart affected pods
kubectl rollout restart deployment pf9-mngt-api -n pf9-mngt
```

### Debug a pod

```bash
kubectl logs -n pf9-mngt -l app.kubernetes.io/name=pf9-mngt-api --follow
kubectl logs -n pf9-mngt deploy/pf9-mngt-api --previous   # logs from last crash
kubectl exec -it -n pf9-mngt deploy/pf9-mngt-api -- /bin/bash
```

### Uninstall (destructive)

```bash
helm uninstall pf9-mngt -n pf9-mngt
# To also delete all data:
kubectl delete pvc --all -n pf9-mngt
kubectl delete namespace pf9-mngt
```

---

## 14. Common Issues & Fixes

### PVCs stuck in Pending

**Symptom:** `kubectl get pvc -n pf9-mngt` shows `Pending` for all PVCs.  
**Cause:** The storageClass in values doesn't match any StorageClass on your cluster.  
**Fix:**
```bash
kubectl get storageclass                  # find the right name
helm upgrade pf9-mngt ./k8s/helm/pf9-mngt -n pf9-mngt --reuse-values \
  --set postgresql.persistence.storageClass=<correct-class> \
  --set ldapService.persistence.data.storageClass=<correct-class> \
  --set ldapService.persistence.config.storageClass=<correct-class>
```

### db-migrate job DeadlineExceeded

**Symptom:** Job shows `BackoffLimitExceeded` or `DeadlineExceeded` in `kubectl get jobs`.  
**Cause:** PostgreSQL wasn't ready in time (common on first NFS mount — can take 2–3 minutes).  
**Fix:**
```bash
kubectl delete job -n pf9-mngt -l app.kubernetes.io/component=db-migrate
helm upgrade pf9-mngt ./k8s/helm/pf9-mngt -n pf9-mngt --reuse-values
```

### Workers CrashLoopBackOff — missing sync-key

**Symptom:** `ldap_sync_key secret is not set. Worker cannot decrypt bind passwords.`  
**Cause:** `pf9-ldap-secrets` is missing the `sync-key` field.  
**Fix:** Recreate the secret with all four fields (see §6). The sync-key must be a
URL-safe base64 string from `python3 -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())"`.

### Grafana CrashLoopBackOff on NFS

**Symptom:** Grafana init container exits with `chown: changing ownership of /var/lib/grafana/.snapshot: Read-only file system`  
**Cause:** NFS provisioner exposes a read-only `.snapshot` directory that blocks `chown -R`.  
**Fix:** Ensure `k8s/monitoring/prometheus-values.yaml` contains:
```yaml
grafana:
  initChownData:
    enabled: false
```
Then re-run `helm upgrade`.

### ArgoCD permanently OutOfSync on pf9-db / pf9-ldap

**Symptom:** ArgoCD shows `OutOfSync` on the StatefulSets but sync doesn't fix it.  
**Cause:** StatefulSet `volumeClaimTemplates` are immutable in Kubernetes — ArgoCD
sees a diff it can never apply.  
**Fix:** See §12 for the `ignoreDifferences` patch.

### Ingress 404 or no EXTERNAL-IP

```bash
kubectl get svc -n ingress-nginx          # check EXTERNAL-IP is assigned
kubectl describe ingress pf9-mngt -n pf9-mngt  # check host + backend
kubectl describe clusterissuer letsencrypt-prod   # check cert-manager
```

Common causes:
- DNS not propagated yet — wait and retry
- ingress-nginx controller not running
- `ingress.host` in values doesn't match your DNS record exactly

### API pods in CrashLoopBackOff

```bash
kubectl logs deploy/pf9-mngt-api -n pf9-mngt --previous
kubectl get secrets -n pf9-mngt   # verify all required secrets exist
```

Common causes:
- A required secret is missing (see §6)
- `pf9-db` Service not yet running — wait for StatefulSet to be Ready
- JWT_SECRET_KEY is less than 32 characters

### Prometheus/AlertManager UI shows 404 in Grafana

**Cause:** Adding `routePrefix` to `prometheusSpec` makes Prometheus serve at `/prometheus`
internally, which breaks Grafana's datasource that calls the root API path.  
**Fix:** Do not set `routePrefix` or `externalUrl` in `prometheusSpec`. Use the nginx
`rewrite-target` annotation instead (already correct in the provided values file).

### Monitoring pod shows storage / memory / network as `None`

**Symptom:** The Monitoring tab shows `None` for `storage_used_gb`, `memory_used_mb`, and
`network_rx_bytes` / `network_tx_bytes` even though hypervisors are reachable.

**Root cause:** Kubernetes assigns the monitoring pod a pod-CIDR IP (e.g. `192.168.x.x`).
PF9 hypervisor firewalls typically DROP inbound connections from pod-CIDR ranges — only
connections from known node IPs (e.g. `172.17.30.x`) are permitted. The libvirt-exporter
on port 9177 therefore never responds, so all per-VM metrics arrive as `None`.

**Fix:** Flannel's masquerade rules NAT outbound pod traffic to the K8s node IP when
connecting to non-pod-CIDR destinations (such as the hypervisors at 172.17.95.x). No
`hostNetwork` change is needed — simply ensure `hostNetwork: false` (the default since
v1.93.46) and pin the pod to the node with the hypervisor route using `nodeSelector`.

```yaml
# k8s/helm/pf9-mngt/values.yaml
monitoring:
  hostNetwork: false   # Flannel masquerade NATSs outbound to node IP; no hostNetwork needed
  nodeSelector:
    kubernetes.io/hostname: pf9-worker01   # node with route to 172.17.95.0/24
```

> **Note:** `hostNetwork: true` was used prior to v1.93.46 but broke ClusterIP routing
> cross-node. `hostNetwork: false` is the correct setting and is the chart default.

### SSH + virsh fallback for VM metrics

When the libvirt-exporter is not installed on hypervisors, or is unreachable, the
monitoring service can collect VM metrics directly via SSH:

```yaml
# k8s/helm/pf9-mngt/values.yaml — or set via Helm --set flags
monitoring:
  sshUser: root                        # or the SSH user on your hypervisors
  sshKeyFile: /etc/pf9-ssh/id_rsa     # path inside the container
```

You must also mount the SSH private key as a Kubernetes secret. Create the secret:

```bash
kubectl create secret generic pf9-monitoring-ssh-key \
  --namespace pf9-mngt \
  --from-file=id_rsa=/path/to/your/private_key
```

Then reference it in `values.yaml` under `monitoring.sshKeySecret`. When configured, the
monitoring service runs `virsh domstats --raw --state-running` over SSH on each hypervisor
and parses CPU, memory, network I/O, and block device metrics per VM. OpenStack VM UUIDs
are extracted from block device paths to correlate metrics with `servers` table records.

> **Note:** SSH fallback and the libvirt-exporter scraper are complementary — the service
> tries the exporter first and falls back to SSH if the exporter is unreachable.

### Monitoring push-cache: live metrics delivery for disconnected pods *(v1.93.47+)*

If the monitoring pod and API pod are on different Kubernetes nodes and cross-node pod-to-pod
connectivity is unreliable, configure the monitoring service to push its metrics cache directly
to the API after each scrape cycle rather than waiting to be polled.

**How it works:**
- After each scrape cycle `monitoring/prometheus_client.py` POSTs the full metrics payload to
  `{API_BASE_URL}/internal/monitoring/push-cache`.
- The API stores it in Redis (`pf9:monitoring:vm_cache`, TTL 300 s).
- All consumers (`/monitoring/vm-metrics`, `/monitoring/host-metrics`, `dashboards.py`) read
  from this Redis key before falling back to the database.

**Required env vars** (both already present in the Helm chart defaults):

| Pod | Env var | Value |
|-----|---------|-------|
| `pf9-monitoring` | `API_BASE_URL` | `http://pf9-api:8000` |
| `pf9-monitoring` | `INTERNAL_SERVICE_SECRET` | value from `pf9-secrets` |

**Verify push is working** after the monitoring pod completes one scrape cycle (~60 s):

```bash
# 1. Redis key present
kubectl exec -n pf9-mngt <redis-pod> -- redis-cli EXISTS pf9:monitoring:vm_cache
# → (integer) 1

# 2. Monitoring pod logged a push
kubectl logs -n pf9-mngt -l app=pf9-monitoring --tail=20 | grep "Pushed metrics cache"
# → INFO: Pushed metrics cache to API: 12 VMs, 3 hosts
```

**Symptom if push is NOT working:** Live metrics revert to N/A / allocation-based data after
the Redis key expires. Check `pf9-monitoring` pod logs for `Could not push metrics cache to API`
warnings and verify `API_BASE_URL` resolves from within the monitoring pod.

### Tenant Portal "allocation-based usage" + cross-node metrics timeout

**Symptom:** Tenant Portal Current Usage shows the "allocation-based usage" banner even though
`pf9-worker01` has live libvirt metrics. Dashboard VM Hotspots Storage column shows N/A.
API pod and tenant-portal pod cannot reach the monitoring service.

**Root cause (v1.93.46):** `hostNetwork: true` on the monitoring pod caused its K8s Service
endpoint to be registered as the physical node IP `172.17.30.164` instead of a pod-CIDR IP.
When kube-proxy on `pf9-worker02` attempted to DNAT ClusterIP→monitoring traffic to that
node IP, connections failed with errno=11 (timeout) — kube-proxy cannot DNAT to a
host-network endpoint on a different node. All pods on `pf9-worker02` (including
tenant-portal and API pod) timed out on all TCP connections to monitoring.

An additional latent bug: three code locations in `main.py` and `dashboards.py` used
`http://pf9_monitoring:8001` (underscore) as the default fallback for
`MONITORING_SERVICE_URL`. Kubernetes DNS resolves hyphen names (`pf9-monitoring`) only, so
the default never resolved.

**Fix (v1.93.46):**

1. Disable `hostNetwork` in `values.yaml`:
   ```yaml
   monitoring:
     hostNetwork: false   # Flannel masquerades pod IP → node IP for non-pod-CIDR dests
     nodeSelector:
       kubernetes.io/hostname: pf9-worker01
   ```
   Flannel's masquerade rule NATs the monitoring pod's outbound connections to the node IP
   when reaching non-pod-CIDR addresses (hypervisors at 172.17.95.x), so scraping continues.

2. Tenant portal now routes all metrics through the main API:
   ```
   tenant-portal → pf9-api:8000/internal/monitoring/vm-metrics → pf9-monitoring:8001
   ```
   The API pod is the single gateway; no cross-node direct pod-to-pod routing.

3. API→monitoring:8001 egress is added to the `pf9-api` NetworkPolicy.

4. The default `MONITORING_SERVICE_URL` fallback is corrected to `http://pf9-monitoring:8001`
   (hyphen) in all three locations.

> **Note:** If you previously set `hostNetwork: true` to allow hypervisor scraping, that
> setting is no longer needed. Remove it or set it to `false`; Flannel masquerade handles
> the outbound NAT automatically.

### Monitoring pod scheduled to wrong node — all metrics N/A

**Symptom:** All per-VM metrics (`storage_used_gb`, `memory_used_mb`, `network_rx_bytes`) are
`None`. The monitoring cache reports `source: database` and `total_hosts: 0`. Dashboard VM
Hotspots, Inventory VM bars, Monitoring Resource Metrics, and Tenant Portal Current Usage all
show allocation-based estimates.

**Root cause:** The monitoring pod rescheduled to a K8s node that has no route to the
hypervisor subnet (172.17.95.0/24). Even with Flannel masquerade active, if the node's
routing table lacks a path to the hypervisors, all Prometheus scrapes time out silently.

**Fix (v1.93.45):** Add a `nodeSelector` to pin the monitoring pod to the specific node that
has the route:

```yaml
# k8s/helm/pf9-mngt/values.yaml
monitoring:
  nodeSelector:
    kubernetes.io/hostname: pf9-worker01   # the node with a route to 172.17.95.0/24
```

This is set by default in `values.yaml`. Verify the node name with `kubectl get nodes -o wide`
and confirm it can reach the hypervisors before changing it.

### Dashboard VM Hotspots / Host Utilization / Health Summary showing allocation data

**Symptom:** The Dashboard shows allocation-based estimates (vCPU count, provisioned GB)
instead of real Prometheus metrics in the VM Hotspots, Host Utilization, and Health Summary
avg CPU/memory widgets, even though `/metrics/vms` returns live data.

**Root cause:** `dashboards.py`'s `_load_metrics_cache()` only searched for a local cache
file written by the monitoring service. In Kubernetes, the API pod and monitoring pod have
separate filesystems — no shared volume — so the file is never found and all three widgets
fall back to DB allocation data.

**Fix (v1.93.44):** `_load_metrics_cache()` now falls back to calling `GET /metrics/vms`
and `GET /metrics/hosts` on the monitoring service via HTTP when no local cache file exists.
The API pod Helm deployment now sets `MONITORING_SERVICE_URL=http://pf9-monitoring:8001`
(same env var used by the tenant-portal pod and `/monitoring/vm-metrics`). No manual action
is required — this is included in the chart from v1.93.44.

---

## 15. Architecture Decision Records

### ADR-K001: Helm chart co-located in the application repository

**Decision:** The Helm chart lives in `k8s/helm/pf9-mngt/` inside the application repo.

**Rationale:** Chart and application code are versioned together. CI validates chart and
application in the same pipeline run. Developers check out one repo.

### ADR-K002: Bitnami Sealed Secrets over external secret store

**Decision:** Credentials are encrypted with kubeseal and committed to git as SealedSecret
resources. No cloud-specific secret store is used.

**Rationale:** Works identically on EKS, AKS, GKE, and self-hosted clusters — no vendor
lock-in. Sealed blobs are safe to commit publicly. Teams can add ExternalSecrets later
without changing application code.

### ADR-K003: db-migrate as a Helm post-install/post-upgrade hook

**Decision:** The database migration job runs as a `post-install,post-upgrade` Helm hook.

**Rationale:** The hook fires after all non-hook resources (including the PostgreSQL
StatefulSet) are applied and healthy. This ensures the DB is reachable when the migration
runs. `hook-delete-policy: before-hook-creation,hook-succeeded` cleans up old job pods.

### ADR-K004: StatefulSet for PostgreSQL and LDAP, Deployment for Redis

**Decision:** PostgreSQL and OpenLDAP use StatefulSets; Redis uses a plain Deployment.

**Rationale:** PostgreSQL and LDAP need stable network identities and ordered startup for
data integrity. Redis is a cache — losing in-flight data is acceptable; it self-warms
within one TTL cycle. StatefulSet adds unnecessary complexity for a pure cache.

### ADR-K005: Monitoring stack installed separately (not in the pf9-mngt Helm chart)

**Decision:** Prometheus, Grafana, Loki, and AlertManager are installed as separate Helm
charts in the `monitoring` namespace.

**Rationale:** kube-prometheus-stack is a cluster-wide concern — it monitors all workloads,
not just pf9-mngt. Bundling it in the app chart would force every pf9-mngt install to
deploy cluster-level monitoring even if the cluster already has it.

### ADR-K006: Grafana at /grafana subpath instead of a separate hostname

**Decision:** Grafana is exposed at `/grafana` on the same ingress host as the app.

**Rationale:** Avoids requiring an extra DNS A record. nginx `rewrite-target` strips the
prefix before forwarding to Grafana, so Grafana's internal datasource calls (to Prometheus
at ClusterIP) are unaffected. GF_SERVER_SERVE_FROM_SUB_PATH tells Grafana to set correct
relative URLs for its static assets.
