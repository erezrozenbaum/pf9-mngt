# CI/CD Pipeline Guide

This document describes the automated CI/CD pipeline for pf9-mngt — how tests run,
when images are published, and how to work with the pipeline as a contributor or operator.

---

## Overview

```
git push / PR  (dev or master branches only)
     │
     ▼
┌────────────────────────────────────────────┐
│  .github/workflows/ci.yml  (CI)            │
│                                            │
│  1. lint              (Python syntax+flake8)│
│  2. compose-validate  (YAML sanity check)  │
│  3. unit-tests        (no stack required)  │
│  4. dependency-audit  (pip-audit + npm)    │
│  5. security-scan     (Bandit SAST)        │
│  6. frontend-typecheck (tsc in Docker)     │
│  7. frontend-lint     (ESLint in Docker)   │
│  8. integration-tests (full live stack)    │
└──────────────────┬─────────────────────────┘
                   │  all jobs pass on master
                   ▼
┌────────────────────────────────────────────┐
│  .github/workflows/release.yml             │
│                                            │
│   9. release       (tag + GitHub Release)  │
│  10. publish-images → ghcr.io (Docker)     │
│  11. helm-package   → ghcr.io (OCI Helm)   │
│  12. update-values  → commits values.prod.yaml │
└────────────────────────────────────────────┘
```

**Key guarantee:** no release tag is created and no Docker image is published unless every
CI job — including the full integration test suite running against a live stack — passes.

---

## CI Workflow — `.github/workflows/ci.yml`

Triggers on every `push` and `pull_request` to the **`dev`** and **`master`** branches.

### Job 1 — Lint

| What | How |
|------|-----|
| Python syntax check | `python -m py_compile` across all `.py` files |
| Critical flake8 errors | `flake8 --select=E9,F63,F7,F82` (undefined names, syntax errors, import failures) |
| Runs on | `ubuntu-latest`, Python 3.12 |

### Job 2 — Compose Validate

| What | How |
|------|-----|
| Dev stack YAML | `docker compose -f docker-compose.yml config` |
| Prod overlay merge | `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` |
| Purpose | Catch YAML errors, missing env-var references, invalid image names before any container starts |

### Job 3 — Unit Tests (no live stack)

Runs two test classes that need no running containers:

| Test file | Class | Tests |
|-----------|-------|-------|
| `tests/test_auth.py` | `TestJWTHelpers` | 5 — valid token, expired, tampered, wrong secret, constant-time password check |
| `tests/test_container_alerts.py` | `TestWatchdogHealthEvaluation`, `TestWatchdogCooldown`, `TestWatchdogRecovery`, `TestWatchdogMissingSocket` | 9 — unhealthy detection, cooldown, recovery alert, missing socket |

**Total: 14 unit tests.** All pass in ~1 second on any machine with Python 3.11+.

### Job 4 — Dependency Vulnerability Audit

| What | How |
|------|-----|
| Python packages | `pip-audit -r api/requirements.txt` — fails CI on any CVE (except CVE-2024-23342, ecdsa side-channel, no fix available) |
| JavaScript/Node | `docker compose build pf9_ui` — validates `npm install` resolves cleanly inside `node:20-alpine` |
| Runs on | `ubuntu-latest`, Python 3.12 |

---

### Job 5 — SAST Security Scan (Bandit)

| What | How |
|------|-----|
| Python OWASP Top-10 scan | Bandit `-lll -iii` — fails CI on HIGH severity findings |
| Medium findings | Reported as warnings (non-blocking) |
| Runs on | `ubuntu-latest`, Python 3.12 |

---

### Job 6 — Frontend TypeScript Check

| What | How |
|------|-----|
| Type errors | `npm run typecheck` (tsc -b) inside `node:20-alpine` container |
| Heap | `NODE_OPTIONS=--max-old-space-size=4096` to avoid OOM on large codebase |
| Runs on | `ubuntu-latest` (Docker host), Node via container |

---

### Job 7 — Frontend ESLint

| What | How |
|------|-----|
| React hooks violations, unused vars, lint errors | `npm run lint` (ESLint 9) inside the `pf9_ui` container |
| Runs on | `ubuntu-latest` (Docker host), Node via container |
| Depends on | Job 6 (frontend-typecheck) |

---

### Job 8 — Integration Tests (full Docker stack)

Only runs after Jobs 1–7 all pass. Spins up the complete stack on the GitHub Actions runner.

**Step-by-step:**

1. Copies `.env.ci` → `.env` (stub credentials, safe to commit — see [`.env.ci`](../.env.ci))
2. Creates stub secret files in `secrets/` (`db_password`, `ldap_admin_password`, `pf9_password`, `jwt_secret`, `ldap_sync_key`, `vm_provision_key`, `smtp_config_key`, `integration_key`) required by Docker Compose's `secrets:` bind-mounts
3. `docker compose up --build -d`
4. Polls `pf9_api` container health every 10 s, up to 180 s
5. Polls `pf9_monitoring` container health, up to 90 s (non-fatal — monitoring may lag)
6. Runs `tests/seed_ci.py`:
   - Waits for `GET /health` → 200 on both services
   - Verifies `POST /auth/login` with the CI admin user succeeds and returns an `access_token`
   - Verifies `GET /api/tenants` returns 200 with the token
7. Runs full `pytest tests/` with CI env vars set
8. On any failure: dumps `docker compose logs` for all services
9. `docker compose down -v` in an `always()` cleanup step

**CI admin authentication** — no LDAP seeding is needed. `auth.py` checks `DEFAULT_ADMIN_USER`
/ `DEFAULT_ADMIN_PASSWORD` via `hmac.compare_digest` before performing any LDAP lookup.
`initialize_default_admin()` in `api/main.py` inserts the role into the database at startup.
The CI admin user exists only inside the ephemeral GitHub Actions container and is gone when
the job ends.

---

## Release Workflow — `.github/workflows/release.yml`

Triggers automatically when the CI workflow completes **successfully** on `master` or `main`
(uses the `workflow_run` trigger — so a release only fires when the full CI pipeline passes,
not just on a git push).

### Job 5 — Create Release Tag

1. Parses the latest version from `CHANGELOG.md` (e.g. `1.68.0`)
2. Checks if the tag `v1.68.0` already exists in git
3. If new: creates an annotated git tag and pushes it, then creates a GitHub Release with the
   changelog section as release notes

### Job 6 — Publish Docker Images

Runs only when Job 5 creates a new tag. Builds **nine service images** in parallel (matrix):

| Service | Build context | Dockerfile |
|---------|--------------|------------|
| `api` | `.` (repo root) | `api/Dockerfile` |
| `ui` | `./pf9-ui` | `pf9-ui/Dockerfile.prod` |
| `monitoring` | `./monitoring` | `monitoring/Dockerfile` |
| `backup-worker` | `./backup_worker` | `backup_worker/Dockerfile` |
| `metering-worker` | `./metering_worker` | `metering_worker/Dockerfile` |
| `scheduler-worker` | `.` (repo root) | `scheduler_worker/Dockerfile` |
| `search-worker` | `./search_worker` | `search_worker/Dockerfile` |
| `notification-worker` | `./notifications` | `notifications/Dockerfile` |
| `nginx` | `./nginx` | `nginx/Dockerfile` |

Each image is pushed with two tags:

```
ghcr.io/erezrozenbaum/pf9-mngt-<service>:v1.68.0   ← version pin
ghcr.io/erezrozenbaum/pf9-mngt-<service>:latest     ← floating latest
```

**Platforms:** `linux/amd64` and `linux/arm64` — built via QEMU emulation so the same image
runs on Intel/AMD servers and ARM hosts (AWS Graviton, Apple Silicon).

**Authentication:** uses `GITHUB_TOKEN` (automatically available in all Actions runs). No
extra secrets need to be configured.

---

### Job 7 — Helm Package (v1.82.0+)

Runs after `publish-images`. Packages the Helm chart and pushes it to the same ghcr.io
registry as an OCI artifact:

```
helm package k8s/helm/pf9-mngt --version <VERSION>
helm push pf9-mngt-<VERSION>.tgz oci://ghcr.io/erezrozenbaum/helm
```

The packaged chart is available as:
```
oci://ghcr.io/erezrozenbaum/helm/pf9-mngt:<VERSION>
```

ArgoCD points at this OCI registry as its Helm source.

**Authentication:** uses `GITHUB_TOKEN` to push to the `ghcr.io` OCI registry. No extra
secrets required.

---

### Job 8 — Update Values (v1.82.0+)

Runs after `helm-package`. Uses the `RELEASE_PAT` secret to patch `values.prod.yaml` and
commit the change back to the `master` branch:

```bash
# What the job does:
sed -i "s|^  imageTag:.*|  imageTag: v${VERSION}|" k8s/helm/pf9-mngt/values.prod.yaml
git commit -am "chore: update imageTag to v${VERSION} [skip ci]"
git push origin master
```

The `[skip ci]` annotation prevents a recursive CI run. This commit is what ArgoCD detects
to trigger an automated sync and rolling deployment.

**Required secret:** `RELEASE_PAT` — a GitHub Personal Access Token with `repo` and
`workflow` scopes. Set it in **Settings → Secrets and variables → Actions → Repository
secrets** with the name `RELEASE_PAT`.

---

## Using Pre-Built Images in Production

Production deployments can pull pre-built images instead of building from source:

```bash
# 1. Set the version in .env (or leave as 'latest')
echo "PF9_IMAGE_TAG=v1.68.0" >> .env

# 2. Pull images
docker compose -f docker-compose.yml -f docker-compose.prod.yml pull

# 3. Start the stack
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
# or use startup_prod.ps1 (which adds secrets preflight + health checks)
.\startup_prod.ps1
```

The `PF9_IMAGE_TAG` variable controls which version is pulled. It defaults to `latest` if
not set. Pin it to a specific release (e.g. `v1.68.0`) to prevent silent upgrades.

**Dev / local:** `docker-compose.yml` has no `image:` overrides — it always builds from
source. `startup.ps1` and `docker compose up --build` work exactly as before.

---

## The `.env.ci` File

`.env.ci` is committed to the repository and used exclusively by the GitHub Actions
integration-test job. It is safe to commit because:

- All credentials are stub values that only work inside the ephemeral CI stack
  (spun up for ~5 minutes per run)
- Platform9 URL points to `stub-pf9.example.com` — no real cluster is contacted
- SMTP is disabled (`SMTP_ENABLED=false`) — no emails are sent
- Snapshot and restore features are disabled
- The CI admin password grants access only to the CI stack, which is destroyed when
  the job ends

**Never copy values from `.env.ci` into a production `.env` file.**

---

## Running Tests Locally

### Unit tests (always fast, no Docker needed)

```bash
# Activate virtual environment first
.venv\Scripts\python.exe -m pytest tests/test_auth.py::TestJWTHelpers tests/test_container_alerts.py -k "not TestContainerAlertAPI" -v
# Expected: 14 passed in ~1 s
```

### Integration tests (requires a running stack)

```bash
# Start the dev stack
docker compose up -d

# Wait for healthy, then run
python tests/seed_ci.py
pytest tests/ -v
```

Or copy `.env.ci` → `.env` to run against the same stub-credential stack that CI uses:

```bash
copy .env.ci .env    # Windows
# cp .env.ci .env   # Linux/macOS
docker compose up --build -d
python tests/seed_ci.py
pytest tests/ -v
docker compose down -v
```

---

## Troubleshooting CI Failures

### lint fails
- Run `python -m py_compile <file>` locally on the failing file
- Run `flake8 --select=E9,F63,F7,F82 api/` to reproduce

### compose-validate fails
- Run `docker compose -f docker-compose.yml -f docker-compose.prod.yml config` locally
- Check for YAML syntax errors or missing required env vars

### unit-tests fail
- Run locally: `.venv\Scripts\python.exe -m pytest tests/test_auth.py::TestJWTHelpers tests/test_container_alerts.py -k "not TestContainerAlertAPI" -v`
- No live stack needed

### integration-tests timeout waiting for pf9_api
- Usually means the API container crashed on startup
- Check logs in the CI run: the "Dump logs on failure" step captures all container logs
- Common causes: missing migration SQL, DB connection failure, YAML syntax error in a route file

### release job skipped / not triggering
- The release job only fires when CI **fully passes** on `master`/`main`
- Confirm the CI workflow run that triggered the release attempt had `conclusion == success`
- Check that `CHANGELOG.md` has a `## [x.y.z]` header — the release job parses the version
  from there and will exit 1 if none is found

### publish-images fails for one service
- `fail-fast: false` is set on the matrix — other services will still publish
- Common cause: Dockerfile references a file that doesn't exist in the build context
- Check the failing service's `context:` and `dockerfile:` in `release.yml`

---

## Adding New Tests

**Unit tests** (no live stack) — add to or create a new class in `tests/test_*.py`.
Any test that doesn't need a running API should skip when the relevant env vars are absent:

```python
import os, pytest

SKIP = not os.getenv("TEST_API_URL")

@pytest.mark.skipif(SKIP, reason="No live stack")
def test_something():
    ...
```

**Integration tests** — add to `tests/test_*.py` guarded by `TEST_API_URL`. The CI
integration job sets `TEST_API_URL=http://localhost:8000` automatically.

**New services** — if you add a new Docker service with a custom Dockerfile, add it to the
matrix in `.github/workflows/release.yml` under the `publish-images` job.

---

## Related Files

| File | Purpose |
|------|---------|
| [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) | Full CI workflow (lint → unit tests → integration tests) |
| [`.github/workflows/release.yml`](../.github/workflows/release.yml) | Release tagging + ghcr.io image publishing + Helm package + values update |
| [`.env.ci`](../.env.ci) | Stub credentials for CI integration tests |
| [`tests/seed_ci.py`](../tests/seed_ci.py) | CI stack readiness check and smoke test |
| [`tests/test_auth.py`](../tests/test_auth.py) | JWT unit tests + auth integration tests |
| [`tests/test_container_alerts.py`](../tests/test_container_alerts.py) | Container watchdog unit tests |
| [`CHANGELOG.md`](../CHANGELOG.md) | Version history — parsed by release workflow to create tags |
| [`k8s/helm/pf9-mngt/values.yaml`](../k8s/helm/pf9-mngt/values.yaml) | Helm chart defaults — human-edited, no CI writes |
| [`k8s/helm/pf9-mngt/values.prod.yaml`](../k8s/helm/pf9-mngt/values.prod.yaml) | CI-managed image tag overrides — updated by `update-values` job |
| [`k8s/argocd/application.yaml`](../k8s/argocd/application.yaml) | ArgoCD Application manifest — apply once to bootstrap GitOps |
| [`k8s/sealed-secrets/README.md`](../k8s/sealed-secrets/README.md) | kubeseal commands for all nine required Kubernetes Secrets |
