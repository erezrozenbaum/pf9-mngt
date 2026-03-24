# Platform9 Management System — Kubernetes Deployment Guide

**Version**: 3.1
**Last Updated**: March 2026
**Status**: Production Ready (v1.82.14)
**Minimum Kubernetes**: 1.28

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [Repository Layout](#repository-layout)
4. [Prerequisites](#prerequisites)
5. [First-Time Deployment](#first-time-deployment)
   - [Step 1 — Cluster Prerequisites](#step-1--cluster-prerequisites)
   - [Step 2 — Create Sealed Secrets](#step-2--create-sealed-secrets)
   - [Step 3 — Helm Install](#step-3--helm-install)
   - [Step 4 — Verify Rollout](#step-4--verify-rollout)
6. [GitOps with ArgoCD](#gitops-with-argocd)
7. [CI/CD Flow](#cicd-flow)
8. [Values Reference](#values-reference)
9. [Day-2 Operations](#day-2-operations)
   - [Upgrade a Release](#upgrade-a-release)
   - [Rollback](#rollback)
   - [Scale Replicas](#scale-replicas)
   - [Rotate a Secret](#rotate-a-secret)
10. [Troubleshooting](#troubleshooting)
11. [Architecture Decision Records](#architecture-decision-records)

---

## Overview

As of **v1.82.0**, pf9-mngt ships a complete, production-ready Helm chart for deploying every
service to **Kubernetes 1.28+**. The chart lives in `k8s/helm/pf9-mngt/` and covers all 14
services: API, UI, Monitoring, PostgreSQL, Redis, OpenLDAP, and seven background workers.

**Both deployment models are supported and maintained:**

| Model | When to use |
|-------|-------------|
| **Docker Compose** | Single-host, developer, or small-team deployments |
| **Kubernetes (Helm)** | Production with HA, rolling upgrades, and GitOps |

The Docker Compose stack is unchanged. The Helm chart adds a parallel production-grade path.

---

## Architecture

### Service Topology

```
                       ┌─────────────────────────────────┐
          Internet ──▶ │    nginx Ingress Controller      │
                       │  :443  (TLS via cert-manager)    │
                       └────────────┬────────────────────┘
                                    │
            ┌───────────────────────┼───────────────────────┐
            ▼                                               ▼
    ┌───────────────┐                               ┌────────────────┐
    │  pf9-ui       │                               │  pf9-api       │
    │  (ClusterIP)  │                               │  (ClusterIP)   │
    │   :5173       │                               │   :8000        │
    └───────────────┘                               └───────┬────────┘
                                                            │
           ┌────────────────────────────┬──────────────────┤
           ▼                            ▼                   ▼
    ┌────────────┐              ┌──────────────┐    ┌───────────────┐
    │  pf9-db    │              │  pf9-redis   │    │  pf9-ldap     │
    │ StatefulSet│              │  (ClusterIP) │    │  StatefulSet  │
    │  :5432     │              │   :6379      │    │   :389        │
    └────────────┘              └──────────────┘    └───────────────┘
           │
  ┌──────────────────────────────────────────────────────────────────┐
  │  Workers (Deployments, 1 replica each)                           │
  │  backup-worker · ldap-sync-worker · metering-worker             │
  │  notification-worker · scheduler-worker · search-worker         │
  │  snapshot-worker                                                 │
  └──────────────────────────────────────────────────────────────────┘
```

### What is deployed in the `pf9-mngt` namespace

| Resource type | Count | Services |
|---------------|-------|---------|
| Deployment | 5 | api, ui, monitoring, redis, + each worker (7) = 12 total |
| StatefulSet | 2 | postgresql, openldap |
| Job (hook) | 1 | db-migrate (pre-install + pre-upgrade) |
| Service | 7+ | one ClusterIP per service |
| Ingress | 1 | routes `/`, `/api`, `/auth`, `/health` |
| PVC (StatefulSet) | 3 | postgresql data, ldap data, ldap config |
| PVC (worker) | 1 | backup-worker `/backups` |

---

## Repository Layout

```
k8s/
├── argocd/
│   └── application.yaml         # Single-source reference template (dev/local use)
├── deploy-repo-init/            # Bootstrap content for the private pf9-mngt-deploy repo
│   ├── argocd-application.yaml  # Multi-source Application (copy to private repo at bootstrap)
│   ├── argocd-appproject.yaml   # AppProject scoping ArgoCD to pf9-mngt namespace only
│   ├── values.prod.yaml         # Production overrides: imageTag, host, TLS, storageClass
│   ├── README.md
│   └── sealed-secrets/
│       └── HOW_TO_SEAL.md       # kubeseal commands for all 9 required secrets
└── helm/
    └── pf9-mngt/
        ├── Chart.yaml            # chart metadata — version 1.82.2, kubeVersion >=1.28
        ├── values.yaml           # all defaults — no credentials
        ├── values.prod.yaml      # CI-managed image-tag overrides only
        └── templates/
            ├── _helpers.tpl
            ├── namespace.yaml
            ├── ingress.yaml
            ├── jobs/
            │   └── db-migrate.yaml      # Helm pre-install/pre-upgrade hook
            ├── api/
            │   ├── deployment.yaml
            │   └── service.yaml
            ├── ui/
            │   ├── deployment.yaml
            │   └── service.yaml
            ├── db/
            │   ├── statefulset.yaml
            │   └── service.yaml
            ├── redis/
            │   ├── deployment.yaml
            │   └── service.yaml
            ├── ldap/
            │   ├── statefulset.yaml
            │   └── service.yaml
            ├── monitoring/
            │   ├── deployment.yaml
            │   └── service.yaml
            └── workers/
                ├── backup-worker.yaml       # includes PVC
                ├── ldap-sync-worker.yaml
                ├── metering-worker.yaml
                ├── notification-worker.yaml
                ├── scheduler-worker.yaml
                ├── search-worker.yaml
                └── snapshot-worker.yaml
```

---

## Prerequisites

### Cluster

| Requirement | Minimum |
|-------------|---------|
| Kubernetes version | 1.28 |
| Helm | 3.12+ |
| Nodes | 3 (1 control-plane + 2 worker) |
| RAM per worker | 8 GB |
| CPU per worker | 4 cores |
| Storage | PVC-capable StorageClass (standard or fast SSD) |

### Cluster add-ons (must be installed before the Helm chart)

```bash
# 1. cert-manager (v1.14+) — manages TLS certificates
kubectl apply -f https://github.com/cert-manager/cert-manager/releases/latest/download/cert-manager.yaml

# 2. ingress-nginx (v1.9+) — Ingress controller
kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml

# 3. Sealed Secrets controller (v0.26+) — encrypts Secrets at rest in git
kubectl apply -f https://github.com/bitnami-labs/sealed-secrets/releases/latest/download/controller.yaml

# 4. ArgoCD (optional — needed only for GitOps auto-sync)
kubectl create namespace argocd
kubectl apply -n argocd -f https://raw.githubusercontent.com/argoproj/argo-cd/stable/manifests/install.yaml
```

### GitHub secrets and variables (needed by CI)

Set these in: GitHub → repo Settings → Secrets and variables

| Type | Name | Purpose |
|------|------|---------|
| Secret | `RELEASE_PAT` | Personal Access Token with `repo` scope; used by the `update-values` CI job to push `values.prod.yaml` to the private deploy repo |
| Variable | `DEPLOY_REPO` | Name of your private deploy repo (e.g. `pf9-mngt-deploy`); see top of `.github/workflows/release.yml` |

---

## First-Time Deployment

### Step 1 — Cluster Prerequisites

Verify the add-ons are healthy:

```bash
kubectl get pods -n cert-manager
kubectl get pods -n ingress-nginx
kubectl get pods -n kube-system -l app.kubernetes.io/name=sealed-secrets-controller
```

Create a `ClusterIssuer` for Let's Encrypt:

```yaml
# letsencrypt-issuer.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    server: https://acme-v02.api.letsencrypt.org/directory
    email: ops@your-domain.com
    privateKeySecretRef:
      name: letsencrypt-prod-key
    solvers:
      - http01:
          ingress:
            class: nginx
```

```bash
kubectl apply -f letsencrypt-issuer.yaml
```

### Step 2 — Create Sealed Secrets

All sensitive credentials are stored as SealedSecret resources. The file
`k8s/sealed-secrets/README.md` contains ready-to-customise `kubeseal` commands for
all nine required secrets. The basic pattern is:

```bash
# Fetch the controller's public key (one-time, any machine with cluster access)
kubeseal --fetch-cert --controller-name=sealed-secrets-controller \
  --controller-namespace=kube-system > sealed-secrets.pub

# Example — database password
kubectl create secret generic pf9-db-credentials \
  --namespace pf9-mngt \
  --from-literal=password='<your-db-password>' \
  --dry-run=client -o yaml \
  | kubeseal --cert sealed-secrets.pub --format yaml \
  > k8s/sealed-secrets/pf9-db-credentials.yaml

kubectl apply -f k8s/sealed-secrets/pf9-db-credentials.yaml
```

Repeat for each of the nine secrets listed in `k8s/sealed-secrets/README.md`:

| Secret name | Keys |
|-------------|------|
| `pf9-db-credentials` | `password` |
| `pf9-jwt-secret` | `jwt-secret-key` |
| `pf9-ldap-secrets` | `admin-password`, `config-password`, `readonly-password`, `sync-key` |
| `pf9-smtp-secrets` | `password` |
| `pf9-pf9-credentials` | `password` |
| `pf9-snapshot-creds` | `password-key`, `user-password-encrypted`, `service-user-password` |
| `pf9-provision-creds` | `password-key`, `user-password-encrypted` |
| `pf9-ssh-credentials` | `password` (optional) |
| `pf9-copilot-secrets` | `openai-api-key`, `anthropic-api-key` (optional) |

### Step 3 — Helm Install

```bash
# Add the Helm OCI registry (where CI pushes packaged charts)
helm registry login ghcr.io -u <github-user> -p <github-pat>

# Install from the local chart (or pull from OCI registry)
helm upgrade --install pf9-mngt ./k8s/helm/pf9-mngt \
  --namespace pf9-mngt \
  --create-namespace \
  -f k8s/helm/pf9-mngt/values.yaml \
  -f k8s/helm/pf9-mngt/values.prod.yaml \
  --set ingress.host=pf9-mngt.your-domain.com \
  --set pf9.authUrl=https://your-cloud.platform9.net/keystone \
  --set pf9.username=service-account@your-domain.com \
  --wait \
  --timeout 10m
```

The `db-migrate` Job runs automatically as a **post-install/post-upgrade hook** after the StatefulSets are ready.

To install from the OCI registry (as ArgoCD or CI would):

```bash
helm upgrade --install pf9-mngt \
  oci://ghcr.io/erezrozenbaum/helm/pf9-mngt \
  --version 1.82.2 \
  --namespace pf9-mngt \
  -f k8s/helm/pf9-mngt/values.yaml \
  -f k8s/helm/pf9-mngt/values.prod.yaml \
  --set ingress.host=pf9-mngt.your-domain.com \
  --wait
```

### Step 4 — Verify Rollout

```bash
# Check all pods are Running / Completed
kubectl get pods -n pf9-mngt

# Check the db-migrate job succeeded
kubectl get jobs -n pf9-mngt

# Check the Ingress has an address
kubectl get ingress -n pf9-mngt

# Smoke-test the API health endpoint
curl https://pf9-mngt.your-domain.com/health
```

Expected output for `kubectl get pods -n pf9-mngt`:

```
NAME                                        READY   STATUS      RESTARTS
pf9-mngt-api-XXXX                           1/1     Running     0
pf9-mngt-ui-XXXX                            1/1     Running     0
pf9-mngt-monitoring-XXXX                    1/1     Running     0
pf9-mngt-redis-XXXX                         1/1     Running     0
pf9-mngt-db-0                               1/1     Running     0
pf9-mngt-ldap-0                             1/1     Running     0
pf9-mngt-backup-worker-XXXX                 1/1     Running     0
pf9-mngt-ldap-sync-worker-XXXX              1/1     Running     0
pf9-mngt-metering-worker-XXXX               1/1     Running     0
pf9-mngt-notification-worker-XXXX           1/1     Running     0
pf9-mngt-scheduler-worker-XXXX              1/1     Running     0
pf9-mngt-search-worker-XXXX                 1/1     Running     0
pf9-mngt-snapshot-worker-XXXX               1/1     Running     0
pf9-mngt-db-migrate-XXXX                    0/1     Completed   0
```

---

## GitOps with ArgoCD

As of v1.82.1 the GitOps setup uses the **App Repo + Config Repo** pattern:

| Repo | Visibility | Contents |
|------|------------|----------|
| `pf9-mngt` (this repo) | Public | Helm chart, application code, CI workflows |
| `pf9-mngt-deploy` | **Private** | `values.prod.yaml`, sealed-secret blobs, ArgoCD manifests |

ArgoCD uses **multi-source** (v2.6+) to combine both repos at sync time:
- **Source 1** — public repo: Helm chart + `values.yaml` defaults
- **Source 2** — private deploy repo: `values.prod.yaml` (image tags, host, TLS, storageClass)

### One-time bootstrap

```bash
# 1. Register the private deploy repo with ArgoCD (needs RELEASE_PAT)
argocd repo add https://github.com/<your-org>/pf9-mngt-deploy \
  --username <github-user> \
  --password <RELEASE_PAT>

# 2. Apply the AppProject (scopes ArgoCD to pf9-mngt namespace only)
kubectl apply -f k8s/deploy-repo-init/argocd-appproject.yaml -n argocd

# 3. Apply the multi-source Application
kubectl apply -f k8s/deploy-repo-init/argocd-application.yaml -n argocd
```

> The files in `k8s/deploy-repo-init/` are the authoritative copies — copy them to the root of
> your `pf9-mngt-deploy` repo before applying.

### GitOps sync flow (steady state)

```
CI pipeline (release.yml)
        │
        │  1. Builds + pushes Docker images  → ghcr.io/<org>
        │  2. Packages + pushes Helm chart   → ghcr.io/<org>/helm
        │  3. update-values job:
        │       git clone pf9-mngt-deploy (using RELEASE_PAT)
        │       patches global.imageTag in values.prod.yaml
        │       git push → pf9-mngt-deploy main [skip ci]
        ▼
  pf9-mngt-deploy / values.prod.yaml updated
        │
        │  ArgoCD polls both repos every 3 minutes
        ▼
  ArgoCD detects drift in Source 2 → auto-syncs
        │
        │  helm upgrade --install
        │    (chart from Source 1 + values.prod.yaml from Source 2)
        ▼
  new pods roll out (RollingUpdate strategy)
  db-migrate pre-upgrade hook runs before pods start
```

### Manual sync / force sync

```bash
argocd app sync pf9-mngt
argocd app wait pf9-mngt --health
```

---

## CI/CD Flow

The release pipeline (`.github/workflows/release.yml`) has two Helm-specific jobs added in v1.82.0:

### Job: `helm-package`

Runs after `publish-images`. Packages the Helm chart and pushes it as an OCI artifact:

```
helm package k8s/helm/pf9-mngt --version <VERSION>
helm push pf9-mngt-<VERSION>.tgz oci://ghcr.io/erezrozenbaum/helm
```

The chart is then available as:
```
oci://ghcr.io/erezrozenbaum/helm/pf9-mngt:<VERSION>
```

### Job: `update-values`

Runs after `helm-package`. Uses `RELEASE_PAT` to push a single-line change to the **private
`pf9-mngt-deploy` repo** (configured via the `DEPLOY_REPO` repository variable):

```
global:
  imageTag: v<VERSION>    ← updated in pf9-mngt-deploy/values.prod.yaml [skip ci]
```

ArgoCD (Source 2) detects the change in the private repo and triggers `helm upgrade`.
The public repo (`pf9-mngt/master`) is **not touched** by this job.

---

## Values Reference

All configurable values are documented with inline comments in `k8s/helm/pf9-mngt/values.yaml`.
Key sections:

| Section | What it controls |
|---------|-----------------|
| `global.imageTag` | Image tag for all app services (overridden by CI in `values.prod.yaml`) |
| `global.imageRepo` | Base registry path (`ghcr.io/erezrozenbaum`) |
| `secrets.*` | Names of pre-existing Kubernetes Secrets — do **not** put credential values here |
| `api.*` | API replica count, resource limits, feature toggles (snapshot, provision, copilot) |
| `ui.*` | UI replica count and resources |
| `postgresql.*` | PVC size, storage class, resource limits |
| `ldapService.*` | OpenLDAP PVC sizes, storage class |
| `ingress.*` | `host`, TLS secret name, cert-manager `clusterIssuer` |
| `workers.*` | Per-worker resource limits and feature knobs |

### Overriding values at install time

```bash
# Change replica count and storage class
helm upgrade --install pf9-mngt ./k8s/helm/pf9-mngt \
  --set api.replicaCount=3 \
  --set postgresql.persistence.storageClass=fast-ssd \
  --set ldapService.persistence.data.storageClass=fast-ssd
```

---

## Day-2 Operations

### Upgrade a Release

Helm upgrades are handled automatically via ArgoCD in GitOps mode. For a manual upgrade:

```bash
helm upgrade pf9-mngt ./k8s/helm/pf9-mngt \
  --namespace pf9-mngt \
  -f k8s/helm/pf9-mngt/values.yaml \
  -f k8s/helm/pf9-mngt/values.prod.yaml \
  --set ingress.host=pf9-mngt.your-domain.com \
  --wait --timeout 10m
```

The `db-migrate` Job re-runs automatically as a `pre-upgrade` hook before any pod is replaced.

### Rollback

```bash
# List revision history
helm history pf9-mngt -n pf9-mngt

# Roll back to previous revision
helm rollback pf9-mngt -n pf9-mngt

# Roll back to a specific revision
helm rollback pf9-mngt 3 -n pf9-mngt --wait
```

> **Note:** Helm rollback reverts templates and values but does **not** reverse database migrations.
> If a migration broke the schema, restore from a PostgreSQL backup first.

### Scale Replicas

```bash
# Scale API to 3 replicas (via helm upgrade — preferred)
helm upgrade pf9-mngt ./k8s/helm/pf9-mngt -n pf9-mngt \
  --reuse-values --set api.replicaCount=3

# Or directly via kubectl (not persistent across helm upgrades)
kubectl scale deployment pf9-mngt-api -n pf9-mngt --replicas=3
```

### Rotate a Secret

1. Generate the new value locally.
2. Create an updated SealedSecret:
   ```bash
   kubectl create secret generic pf9-jwt-secret \
     --namespace pf9-mngt \
     --from-literal=jwt-secret-key='<new-secret>' \
     --dry-run=client -o yaml \
     | kubeseal --cert sealed-secrets.pub --format yaml \
     > k8s/sealed-secrets/pf9-jwt-secret.yaml
   ```
3. Apply the new SealedSecret:
   ```bash
   kubectl apply -f k8s/sealed-secrets/pf9-jwt-secret.yaml
   ```
4. Restart the affected pods to pick up the updated Secret:
   ```bash
   kubectl rollout restart deployment pf9-mngt-api -n pf9-mngt
   ```

### Inspect / debug a pod

```bash
# Tail API logs
kubectl logs -n pf9-mngt -l app.kubernetes.io/name=pf9-mngt-api --follow

# Shell into API pod
kubectl exec -it -n pf9-mngt deploy/pf9-mngt-api -- /bin/bash

# Check db-migrate job logs
kubectl logs -n pf9-mngt job/pf9-mngt-db-migrate
```

### Uninstall

```bash
helm uninstall pf9-mngt -n pf9-mngt

# To also remove PVCs (DESTRUCTIVE — deletes database data):
kubectl delete pvc -n pf9-mngt --all
kubectl delete namespace pf9-mngt
```

---

## Troubleshooting

### db-migrate job fails at startup

```bash
kubectl logs -n pf9-mngt -l app.kubernetes.io/component=db-migrate
# If pod was already cleaned up, describe the job:
kubectl describe job pf9-db-migrate-<revision> -n pf9-mngt
```

Common causes:
- `pf9-db` StatefulSet not yet Running — job init container waits up to `activeDeadlineSeconds: 300`; if db takes longer (e.g. first NFS mount), the job times out. Fix: delete the failed job and re-trigger sync.
- `pf9-db-credentials` Secret missing — verify: `kubectl get secret pf9-db-credentials -n pf9-mngt`
- Schema migration conflict — restore from backup and re-run with corrected migration
- **`DeadlineExceeded`** — the job's init container (`wait-for-db`) was waiting when `pf9-db` was still starting. Delete the failed job (`kubectl delete job <name> -n pf9-mngt`) and re-trigger the ArgoCD sync.

### Workers or API crash at startup — missing LDAP_SYNC_KEY

```
ldap_sync_key secret is not set. Worker cannot decrypt bind passwords.
```

The `pf9-ldap-secrets` Secret must contain a `sync-key` field (a 32-byte URL-safe base64 key). To generate and patch:

```bash
SYNC_KEY=$(python3 -c "import os,base64; print(base64.urlsafe_b64encode(os.urandom(32)).decode())")
kubectl patch secret pf9-ldap-secrets -n pf9-mngt \
  --type='json' -p="[{'op':'add','path':'/data/sync-key','value':'$(echo -n $SYNC_KEY | base64)']]}"
```

### nginx (UI) Permission denied on `/var/cache/nginx`

The UI pod runs as UID 1000 (non-root). If `emptyDir` volumes for `/var/cache/nginx` and `/var/run` are missing from the Deployment, nginx cannot create its temp directories and crashes. Verify the Deployment spec contains these volumes (present since v1.82.2).

### scheduler-worker `PermissionError: 'monitoring'`

`host_metrics_collector.py` writes `monitoring/cache/metrics_cache.json` relative to `/app`. This path is read-only in the container. An `emptyDir` volume mounted at `/app/monitoring` is required (present since v1.82.2).

### API pods in CrashLoopBackOff

```bash
kubectl describe pod <api-pod-name> -n pf9-mngt
kubectl logs <api-pod-name> -n pf9-mngt --previous
```

Common causes:
- Missing Sealed Secret — check `kubectl get secrets -n pf9-mngt`
- `POSTGRES_HOST` / connection refused — ensure `pf9-db` Service is running
- Wrong JWT_SECRET_KEY format

### Ingress not getting an external IP / URL returns 404

```bash
kubectl describe ingress pf9-mngt -n pf9-mngt
kubectl get svc -n ingress-nginx
```

Common causes:
- `ingress.host` in values doesn't match your DNS record
- cert-manager `ClusterIssuer` not ready — check: `kubectl describe clusterissuer letsencrypt-prod`
- ingress-nginx controller not running

### Workers restarting repeatedly

```bash
kubectl logs -n pf9-mngt deployment/pf9-mngt-<worker-name>
```

Workers use a `/tmp/alive` liveness probe (touch file written at startup). If the process dies
before writing the file the pod is restarted. Check for unhandled exceptions in the logs.

### ArgoCD shows OutOfSync after manual kubectl apply

ArgoCD with `selfHeal: true` will revert any manual changes to bring the cluster back in sync
with `master`. To make a config change permanent, modify `values.yaml` or `values.prod.yaml`
and push to `master`.

---

## Architecture Decision Records

### ADR-K001: Helm chart co-located in the application repository

**Decision:** The Helm chart lives in `k8s/helm/pf9-mngt/` inside the application repo.

**Rationale:**
- Chart and application code are versioned together — chart version always matches app version
- Developers only need one repo to check out
- CI can validate chart and application in the same pipeline run
- Release tagging (git tag → Helm version) is trivially automated

### ADR-K002: Bitnami Sealed Secrets over external secret store

**Decision:** Secrets are encrypted with kubeseal and committed to git as SealedSecret
resources. No cloud-specific secret store (AWS Secrets Manager, Azure Key Vault, etc.) is used
in the base chart.

**Rationale:**
- Works identically on EKS, AKS, GKE, and self-hosted clusters — no cloud lock-in
- Sealed Secret blobs are safe to commit; only the cluster's Sealed Secrets controller can decrypt them
- No per-environment cloud IAM setup required
- Teams can add ExternalSecrets operator later without changing application code

### ADR-K003: db-migrate as a Helm post-install/post-upgrade hook

**Decision:** The database migration job runs as a `helm.sh/hook: post-install,post-upgrade` Job (changed from `pre-install,pre-upgrade` in v1.82.2).

**Rationale:**
- PostgreSQL (StatefulSet) must be Running before the migration job can connect; `post-*` hooks fire after all non-hook resources are applied and healthy, ensuring the DB is available
- `hook-delete-policy: before-hook-creation,hook-succeeded` keeps the namespace clean
- The API Deployment's readiness probe prevents traffic until the API itself is healthy — by which time the migration has completed
- No init container needed in every pod; single job runs once per release

### ADR-K004: `values.prod.yaml` for CI-managed image tags

**Decision:** CI writes only `global.imageTag` (and per-service overrides) to a separate
`values.prod.yaml` file. All other configuration lives in `values.yaml`.

**Rationale:**
- `values.yaml` is a stable, human-edited file — no CI noise in its git history
- `values.prod.yaml` has a mechanical commit history from the `update-values` CI job
- ArgoCD detects the `values.prod.yaml` change and syncs automatically
- Developers never need to manually edit a version in a yaml file

### ADR-K005: StatefulSet for PostgreSQL, Deployment for Redis

**Decision:** PostgreSQL and OpenLDAP use StatefulSets; Redis uses a plain Deployment.

**Rationale:**
- PostgreSQL and LDAP need stable network identities and ordered pod numbering for data integrity
- Redis is used only as a cache layer — losing in-flight cache data is acceptable; the cache self-warms within one TTL cycle (60 s by default)
- Simplifies the Redis manifest significantly; no PVC needed

### ADR-K006: kubeVersion minimum set to 1.28

**Decision:** `Chart.yaml` specifies `kubeVersion: ">=1.28.0-0"`.

**Rationale:**
- Kubernetes 1.24 reached EOL in July 2023; 1.27 reached EOL in June 2024
- 1.28 is the oldest release still receiving security patches as of early 2026 on most managed services (GKE, EKS, AKS)
- All Ingress v1, StatefulSet, and Job APIs used by this chart are stable since 1.21; 1.28 is purely a security-support floor
- Setting this prevents accidental installations on EOL clusters that will not receive CVE patches

### ADR-K007: Separate private deploy repo for production GitOps config

**Decision:** Production-specific configuration (`values.prod.yaml`, sealed-secret blobs, ArgoCD
Application + AppProject manifests) lives in a separate private `pf9-mngt-deploy` repository.
The CI `update-values` job clones and pushes to this private repo using `RELEASE_PAT`.

**Rationale:**
- `values.prod.yaml` may contain environment-specific hostnames, IPs, and StorageClass names
  that are internal infrastructure details not suitable for a public repo
- Sealed Secret blobs are safe to commit (encrypted), but their presence in a public repo
  reveals which secrets exist and their namespace — leaking infrastructure topology
- ArgoCD `Application` and `AppProject` manifests reference the private repo URL and
  cluster-scoping rules — these are deployment-specific, not generic chart config
- The public repo remains a clean, forkable open-source project; forks get a working
  chart structure without any organisation-specific deployment details hardcoded

---

*This document reflects the v1.82.14 implementation. For Docker Compose deployment, see
[DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md). For the full CI/CD pipeline reference, see
[CI_CD_GUIDE.md](CI_CD_GUIDE.md). For Sealed Secrets creation commands, see
[k8s/deploy-repo-init/sealed-secrets/HOW_TO_SEAL.md](../k8s/deploy-repo-init/sealed-secrets/HOW_TO_SEAL.md).*
