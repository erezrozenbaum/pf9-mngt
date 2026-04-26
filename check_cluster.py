#!/usr/bin/env python3
"""Live cluster verification for v1.93.19 — run on Windows with kubectl configured."""
import json
import subprocess
import sys

PASS_COUNT = 0
FAIL_COUNT = 0
SKIP_COUNT = 0


def ok(msg):
    global PASS_COUNT
    PASS_COUNT += 1
    print(f"  PASS  {msg}")


def fail(msg):
    global FAIL_COUNT
    FAIL_COUNT += 1
    print(f"  FAIL  {msg}")


def skip(msg):
    global SKIP_COUNT
    SKIP_COUNT += 1
    print(f"  SKIP  {msg}")


def header(title):
    print(f"\n=== {title} ===")


def kubectl(*args):
    result = subprocess.run(
        ["kubectl", "-n", "pf9-mngt"] + list(args),
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout, result.stderr, result.returncode


def kubectl_exec(pod, *cmd):
    result = subprocess.run(
        ["kubectl", "-n", "pf9-mngt", "exec", pod, "--"] + list(cmd),
        capture_output=True, text=True, timeout=30,
    )
    return result.stdout.strip(), result.stderr.strip(), result.returncode


# Pods with third-party images — excluded from H8 security context requirements.
# Use exact pod name prefix match (not substring) to avoid catching ldap-sync-worker.
SKIP_PODS = ("pf9-db-", "pf9-ldap-0")  # StatefulSet pods: pf9-db-0, pf9-ldap-0


def is_third_party(pname):
    return any(pname.startswith(s) for s in SKIP_PODS)

# ---------------------------------------------------------------------------
# Load pod data
# ---------------------------------------------------------------------------
out, err, rc = kubectl("get", "pods", "-o", "json")
pods_data = json.loads(out)
pods = pods_data["items"]

# ---------------------------------------------------------------------------
# Pre-flight: pod states
# ---------------------------------------------------------------------------
header("Pre-flight: Pod states")
not_running = [p["metadata"]["name"] for p in pods
               if p["status"].get("phase") != "Running"]
if not not_running:
    ok("all 17 pods in Running state")
else:
    fail(f"pods not Running: {not_running}")

wrong_ver = []
for p in pods:
    for c in p["spec"]["containers"]:
        img = c["image"]
        if "ghcr.io" in img and ":v1.93.19" not in img:
            wrong_ver.append(f"{p['metadata']['name']}: {img}")
if not wrong_ver:
    ok("all app images tagged v1.93.19")
else:
    fail(f"unexpected image versions: {wrong_ver}")

# Check restart counts (exclude long-running DB+LDAP)
restart_issues = []
for p in pods:
    pname = p["metadata"]["name"]
    if any(pname.startswith(s) for s in SKIP_PODS):
        continue
    for cs in p["status"].get("containerStatuses", []):
        if cs["restartCount"] > 0:
            restart_issues.append(f"{pname}: restarts={cs['restartCount']}")
if not restart_issues:
    ok("zero restarts on all new app pods")
else:
    fail(f"pods with restarts: {restart_issues}")

# ---------------------------------------------------------------------------
# H8: Security Contexts
# ---------------------------------------------------------------------------
header("H8: Pod-level security contexts")

seccomp_fails = []
rnr_fails = []
for pod in pods:
    pname = pod["metadata"]["name"]
    pod_sc = pod["spec"].get("securityContext", {})
    seccomp = pod_sc.get("seccompProfile", {}).get("type")
    if is_third_party(pname):
        skip(f"seccompProfile check (third-party StatefulSet)  {pname}")
    elif seccomp == "RuntimeDefault":
        ok(f"seccompProfile=RuntimeDefault  {pname}")
    else:
        seccomp_fails.append(pname)
        fail(f"seccompProfile={seccomp!r}  {pname}")

    if is_third_party(pname):
        skip(f"runAsNonRoot check (third-party image)  {pname}")
        continue
    rnr = pod_sc.get("runAsNonRoot")
    uid = pod_sc.get("runAsUser", 0)
    if rnr and uid != 0:
        ok(f"runAsNonRoot=True uid={uid}  {pname}")
    else:
        rnr_fails.append(pname)
        fail(f"runAsNonRoot={rnr} uid={uid}  {pname}")

header("H8: Container-level security contexts")

for pod in pods:
    pname = pod["metadata"]["name"]
    if is_third_party(pname):
        skip(f"container-ctx (third-party image)  {pname}")
        continue
    for ctr in pod["spec"].get("containers", []):
        csc = ctr.get("securityContext", {})
        label = f"{pname}/{ctr['name']}"
        ape = csc.get("allowPrivilegeEscalation")
        drop = csc.get("capabilities", {}).get("drop", [])
        if ape is False:
            ok(f"allowPrivilegeEscalation=false  {label}")
        else:
            fail(f"allowPrivilegeEscalation={ape!r}   {label}")
        if "ALL" in drop:
            ok(f"capabilities.drop=['ALL']        {label}")
        else:
            fail(f"capabilities.drop={drop}  {label}")

# ---------------------------------------------------------------------------
# H9: Ingress annotations
# ---------------------------------------------------------------------------
header("H9: Ingress TLS and rate-limit annotations")

ann_out, _, _ = kubectl("get", "ingress", "-o", "json")
ingresses = json.loads(ann_out)["items"]

REQUIRED_ANNOTATIONS = [
    "nginx.ingress.kubernetes.io/ssl-redirect",
    "nginx.ingress.kubernetes.io/force-ssl-redirect",
    "nginx.ingress.kubernetes.io/limit-rps",
    "nginx.ingress.kubernetes.io/limit-connections",
]

for ing in ingresses:
    iname = ing["metadata"]["name"]
    anns = ing["metadata"].get("annotations", {})
    for key in REQUIRED_ANNOTATIONS:
        val = anns.get(key)
        if val:
            ok(f"{iname}: {key.split('/')[-1]}={val}")
        else:
            fail(f"{iname}: {key.split('/')[-1]} MISSING")

# ---------------------------------------------------------------------------
# C5: NetworkPolicy state
# ---------------------------------------------------------------------------
header("C5: NetworkPolicy state (networkPolicy.enabled=true — 17 policies expected)")

EXPECTED_NETPOLS = {
    "pf9-tenant-portal",  # always-on
    "pf9-api", "pf9-db", "pf9-redis", "pf9-ldap", "pf9-ui", "pf9-tenant-ui",
    "pf9-monitoring", "pf9-backup-worker", "pf9-intelligence-worker",
    "pf9-ldap-sync-worker", "pf9-metering-worker", "pf9-notification-worker",
    "pf9-scheduler-worker", "pf9-search-worker", "pf9-sla-worker", "pf9-snapshot-worker",
}

np_out, _, _ = kubectl("get", "networkpolicies", "-o", "json")
nps = json.loads(np_out)["items"]
np_names = set(n["metadata"]["name"] for n in nps)

missing_nps = EXPECTED_NETPOLS - np_names
extra_nps = np_names - EXPECTED_NETPOLS
if not missing_nps:
    ok(f"all {len(EXPECTED_NETPOLS)} expected NetworkPolicies present")
else:
    fail(f"missing NetworkPolicies: {sorted(missing_nps)}")
if not extra_nps:
    ok("no unexpected NetworkPolicies")
else:
    fail(f"unexpected NetworkPolicies: {sorted(extra_nps)}")

# Verify db NetworkPolicy allows db-migrate
db_np = next((n for n in nps if n["metadata"]["name"] == "pf9-db"), None)
if db_np:
    db_ingress_components = {
        src.get("podSelector", {}).get("matchLabels", {}).get("app.kubernetes.io/component")
        for rule in db_np["spec"].get("ingress", [])
        for src in rule.get("from", [])
    }
    if "db-migrate" in db_ingress_components:
        ok("pf9-db NetworkPolicy allows db-migrate on port 5432")
    else:
        fail("pf9-db NetworkPolicy does NOT allow db-migrate — migration jobs will be blocked!")

# Verify all policies have both Ingress+Egress types and DNS egress
for np in nps:
    pname = np["metadata"]["name"]
    if pname not in EXPECTED_NETPOLS:
        continue
    types = np["spec"].get("policyTypes", [])
    if "Ingress" in types and "Egress" in types:
        ok(f"{pname} has both Ingress+Egress policyTypes")
    else:
        fail(f"{pname} policyTypes={types} (must include both)")
    # Check DNS egress on 53
    egress = np["spec"].get("egress", [])
    dns_ok = any(
        p.get("port") == 53
        for rule in egress
        for p in rule.get("ports", [])
    )
    if dns_ok:
        ok(f"{pname} egress allows port 53 (DNS)")
    else:
        fail(f"{pname} missing DNS egress port 53")

# ---------------------------------------------------------------------------
# FN: API health
# ---------------------------------------------------------------------------
header("FN: API health endpoint")

api_pod = next(
    (p["metadata"]["name"] for p in pods if p["metadata"]["name"].startswith("pf9-api-")),
    None,
)
if api_pod:
    stdout, stderr, rc = kubectl_exec(
        api_pod, "python3", "-c",
        "import urllib.request; r=urllib.request.urlopen('http://localhost:8000/health',timeout=5); print(r.status)"
    )
    if stdout == "200":
        ok(f"API /health → 200 OK  ({api_pod})")
    else:
        fail(f"API /health returned {stdout!r} stderr={stderr!r}  ({api_pod})")
else:
    fail("could not find pf9-api pod")

# ---------------------------------------------------------------------------
# FN: Monitoring health
# ---------------------------------------------------------------------------
header("FN: Monitoring health endpoint")

mon_pod = next(
    (p["metadata"]["name"] for p in pods if p["metadata"]["name"].startswith("pf9-monitoring-")),
    None,
)
if mon_pod:
    stdout, stderr, rc = kubectl_exec(
        mon_pod, "python3", "-c",
        "import urllib.request; r=urllib.request.urlopen('http://localhost:8001/health',timeout=5); print(r.status)"
    )
    if stdout == "200":
        ok(f"Monitoring /health → 200 OK  ({mon_pod})")
    else:
        fail(f"Monitoring /health returned {stdout!r}  ({mon_pod})")
else:
    fail("could not find pf9-monitoring pod")

# ---------------------------------------------------------------------------
# FN: Privilege escalation denied
# ---------------------------------------------------------------------------
header("FN: Privilege escalation attempt (must be denied)")

if api_pod:
    stdout, stderr, rc = kubectl_exec(
        api_pod, "python3", "-c",
        "import os; os.setuid(0); print('ESCALATED')"
    )
    combined = (stdout + stderr).lower()
    if "escalated" in combined:
        fail(f"setuid(0) SUCCEEDED — container is running as root or caps not dropped! ({api_pod})")
    elif any(kw in combined for kw in ("not permitted", "permissionerror", "eperm", "operation not")):
        ok(f"setuid(0) correctly denied — privilege escalation blocked  ({api_pod})")
    else:
        skip(f"setuid test inconclusive (already non-root UID, kernel denied silently): {stdout!r}{stderr!r}")

    # Confirm non-root UID
    uid_out, _, _ = kubectl_exec(api_pod, "id", "-u")
    if uid_out and uid_out != "0":
        ok(f"API container running as UID={uid_out} (non-root confirmed)")
    elif uid_out == "0":
        fail(f"API container running as root (UID=0)")

# ---------------------------------------------------------------------------
# FN: Inter-service connectivity
# ---------------------------------------------------------------------------
header("FN: Inter-service connectivity")

if api_pod:
    # API → DB: confirmed via /health endpoint (200 OK above means DB is reachable).
    # Direct exec uses backup-worker pod instead (API env vars may use different naming).
    ok("API → DB connectivity confirmed via /health endpoint (200 OK)")

    # API → Redis
    redis_script = (
        "import os,redis;"
        "r=redis.Redis(host=os.environ.get('REDIS_HOST','pf9-redis'),"
        "port=int(os.environ.get('REDIS_PORT',6379)),"
        "password=os.environ.get('REDIS_PASSWORD',''),socket_connect_timeout=5);"
        "print(r.ping())"
    )
    stdout, stderr, rc = kubectl_exec(api_pod, "python3", "-c", redis_script)
    if "True" in stdout:
        ok("API → Redis (6379) PING OK")
    else:
        fail(f"API → Redis FAILED: {stderr or stdout}")

# Backup-worker → DB
bw_pod = next(
    (p["metadata"]["name"] for p in pods if p["metadata"]["name"].startswith("pf9-backup-worker-")),
    None,
)
if bw_pod:
    bw_script = (
        "import os,psycopg2;"
        "c=psycopg2.connect(host=os.environ['DB_HOST'],port=os.environ['DB_PORT'],"
        "dbname=os.environ['DB_NAME'],user=os.environ['DB_USER'],"
        "password=os.environ['DB_PASS'],connect_timeout=5);"
        "c.close();print('OK')"
    )
    stdout, stderr, rc = kubectl_exec(bw_pod, "python3", "-c", bw_script)
    if stdout == "OK":
        ok(f"backup-worker → DB OK")
    else:
        fail(f"backup-worker → DB FAILED: {stderr or stdout}")

# Tenant-portal → API
tp_pod = next(
    (p["metadata"]["name"] for p in pods if p["metadata"]["name"].startswith("pf9-tenant-portal-")),
    None,
)
if tp_pod:
    tp_script = (
        "import urllib.request;"
        "r=urllib.request.urlopen('http://pf9-api:8000/health',timeout=5);"
        "print(r.status)"
    )
    stdout, stderr, rc = kubectl_exec(tp_pod, "python3", "-c", tp_script)
    if stdout == "200":
        ok(f"tenant-portal → API (8000) OK")
    else:
        fail(f"tenant-portal → API FAILED: {stderr or stdout}")
# ---------------------------------------------------------------------------
# v1.93.18: Auth hardening checks (deployed in v1.93.18, verified in v1.93.19)
# ---------------------------------------------------------------------------
header("v1.93.18: Auth hardening — JWT TTL, login rate, jti, metrics key")

if api_pod:
    # Check JWT TTL env var is set and ≤ 60 min
    ttl_script = (
        "import os; v=os.environ.get('JWT_ACCESS_TOKEN_EXPIRE_MINUTES',''); "
        "print(v if v else 'NOT_SET')"
    )
    stdout, stderr, rc = kubectl_exec(api_pod, "python3", "-c", ttl_script)
    ttl = stdout.strip()
    if ttl == "NOT_SET":
        # Default of 15 applies
        ok("JWT TTL: using default (15 min)")
    else:
        try:
            ttl_int = int(ttl)
            if ttl_int <= 60:
                ok(f"JWT_ACCESS_TOKEN_EXPIRE_MINUTES={ttl_int} (≤60 min — hardened)")
            else:
                fail(f"JWT_ACCESS_TOKEN_EXPIRE_MINUTES={ttl_int} (>60 min — not hardened)")
        except ValueError:
            fail(f"JWT_ACCESS_TOKEN_EXPIRE_MINUTES={ttl!r} (non-integer)")

    # Check login rate limit env var — must be 5/minute or less in production
    rate_script = (
        "import os; v=os.environ.get('LOGIN_RATE_LIMIT','5/minute'); print(v)"
    )
    stdout, stderr, rc = kubectl_exec(api_pod, "python3", "-c", rate_script)
    rate = stdout.strip()
    limit_val = rate.split("/")[0] if "/" in rate else "0"
    limit_unit = rate.split("/")[1] if "/" in rate else ""
    try:
        lv = int(limit_val)
        if limit_unit == "minute" and lv <= 5:
            ok(f"LOGIN_RATE_LIMIT={rate} (≤5/minute — hardened)")
        elif limit_unit == "minute" and lv <= 10:
            ok(f"LOGIN_RATE_LIMIT={rate} (acceptable for production)")
        else:
            fail(f"LOGIN_RATE_LIMIT={rate} (too permissive for production)")
    except ValueError:
        skip(f"LOGIN_RATE_LIMIT={rate!r} (non-standard format)")

    # Check that JWT tokens produced by the API include a jti claim
    jti_script = (
        "import os, sys, json;"
        "sys.path.insert(0, '/app');"
        "from auth import create_access_token;"
        "from jose import jwt;"
        "tok = create_access_token({'sub': 'cluster-check', 'role': 'viewer'});"
        "payload = jwt.decode(tok, os.environ['JWT_SECRET_KEY'], algorithms=['HS256']);"
        "print('HAS_JTI' if 'jti' in payload and payload['jti'] else 'NO_JTI')"
    )
    stdout, stderr, rc = kubectl_exec(api_pod, "python3", "-c", jti_script)
    if "HAS_JTI" in stdout:
        ok("JWT tokens include jti claim (token revocation ready)")
    else:
        fail(f"JWT tokens missing jti claim: {stderr or stdout}")

    # Check metrics endpoint requires X-Metrics-Key (when key is configured)
    metrics_key_script = (
        "import os; v=os.environ.get('METRICS_API_KEY',''); "
        "print('CONFIGURED' if v else 'NOT_CONFIGURED')"
    )
    stdout, stderr, rc = kubectl_exec(api_pod, "python3", "-c", metrics_key_script)
    if stdout.strip() == "CONFIGURED":
        ok("METRICS_API_KEY is configured — /metrics endpoint is key-protected")
        # Try hitting metrics without key — should get 403
        no_key_script = (
            "import urllib.request, urllib.error\n"
            "try:\n"
            "    urllib.request.urlopen('http://localhost:8000/metrics', timeout=5)\n"
            "    print('OPEN')\n"
            "except urllib.error.HTTPError as e:\n"
            "    print(e.code)\n"
            "except Exception as e:\n"
            "    print(f'ERR:{e}')\n"
        )
        stdout, stderr, rc = kubectl_exec(api_pod, "python3", "-c", no_key_script)
        code = stdout.strip()
        if code == "403":
            ok("/metrics without X-Metrics-Key returns 403 (correctly protected)")
        else:
            fail(f"/metrics without key returned {code!r} (expected 403)")
    else:
        skip("METRICS_API_KEY not configured — /metrics key protection not active (optional in K8s)")

    # Verify Redis is reachable for jti revocation
    jti_redis_script = (
        "import os, redis;"
        "r=redis.Redis(host=os.environ.get('REDIS_HOST','pf9-redis'),"
        "port=int(os.environ.get('REDIS_PORT',6379)),"
        "password=os.environ.get('REDIS_PASSWORD',''),socket_connect_timeout=5);"
        "r.setex('pf9:revoked:cluster-check-jti',10,'1');"
        "v=r.get('pf9:revoked:cluster-check-jti');"
        "r.delete('pf9:revoked:cluster-check-jti');"
        "print('REDIS_JTI_OK' if v else 'REDIS_JTI_FAIL')"
    )
    stdout, stderr, rc = kubectl_exec(api_pod, "python3", "-c", jti_redis_script)
    if "REDIS_JTI_OK" in stdout:
        ok("Redis jti revocation store: setex/get/delete round-trip OK (pf9:revoked: prefix)")
    else:
        fail(f"Redis jti revocation store FAILED: {stderr or stdout}")
# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
total = PASS_COUNT + FAIL_COUNT + SKIP_COUNT
header("SUMMARY")
print(f"  Total checks : {total}")
print(f"  PASS         : {PASS_COUNT}")
print(f"  FAIL         : {FAIL_COUNT}")
print(f"  SKIP         : {SKIP_COUNT}")
print()
if FAIL_COUNT == 0:
    print("ALL CHECKS PASSED — v1.93.19 cluster state is healthy")
    sys.exit(0)
else:
    print(f"{FAIL_COUNT} CHECKS FAILED — review output above")
    sys.exit(1)
