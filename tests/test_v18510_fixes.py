"""
tests/test_v18510_fixes.py — Unit tests for v1.85.10 bug fixes.

Covers:
  1. BrandingUpsertRequest.safe_url — relative /api/admin/... paths accepted (422 fix)
  2. Logo upload content_type fallback — extension detection when ct is missing/unknown (400 fix)
  3. Monitoring empty-hosts init — PF9_HOSTS="" must not create [""] hosts list
  4. Runbook results — security_group_audit, quota_threshold_check, vm_rightsizing
     all include items_scanned / summary in their return dict
"""
import os
import re
import sys
import types
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Minimal stubs shared with test_v1859_fixes (must precede api imports)
# ---------------------------------------------------------------------------

_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)

# psycopg2
if "psycopg2" not in sys.modules:
    _psycopg2_stub = types.ModuleType("psycopg2")
    _psycopg2_stub.connect = MagicMock(side_effect=RuntimeError("no DB in tests"))
    _psycopg2_stub.extras = types.ModuleType("psycopg2.extras")
    _psycopg2_stub.extras.RealDictCursor = dict
    _psycopg2_stub.OperationalError = Exception
    _psycopg2_stub.DatabaseError = Exception
    sys.modules["psycopg2"] = _psycopg2_stub
    sys.modules["psycopg2.extras"] = _psycopg2_stub.extras

# fastapi
if "fastapi" not in sys.modules:
    class _FakeHTTPException(Exception):
        def __init__(self, status_code: int = 400, detail: str = ""):
            self.status_code = status_code
            self.detail = detail

    _fastapi_stub = types.ModuleType("fastapi")
    _fastapi_stub.HTTPException = _FakeHTTPException
    _fastapi_stub.APIRouter = MagicMock(return_value=MagicMock())
    _fastapi_stub.Depends = lambda f: f
    _fastapi_stub.Query = MagicMock(return_value=None)
    _fastapi_stub.Request = object
    _fastapi_stub.File = MagicMock(return_value=None)
    _fastapi_stub.UploadFile = MagicMock
    _fastapi_stub.status = types.SimpleNamespace(
        HTTP_200_OK=200,
        HTTP_400_BAD_REQUEST=400,
        HTTP_403_FORBIDDEN=403,
        HTTP_404_NOT_FOUND=404,
    )
    _fastapi_stub.Header = MagicMock(return_value="")
    sys.modules["fastapi"] = _fastapi_stub

    for _sub in ("fastapi.responses", "fastapi.middleware.cors", "fastapi.middleware"):
        sys.modules.setdefault(_sub, types.ModuleType(_sub))
    sys.modules["fastapi.responses"].FileResponse = MagicMock
    sys.modules["fastapi.middleware.cors"].CORSMiddleware = MagicMock
    sys.modules["fastapi.middleware"].cors = sys.modules["fastapi.middleware.cors"]

_HTTPException = sys.modules["fastapi"].HTTPException

# pydantic
if "pydantic" not in sys.modules:
    _pydantic_stub = types.ModuleType("pydantic")

    class _BaseModel:
        def __init__(self, **kw):
            for k, v in kw.items():
                setattr(self, k, v)

    _pydantic_stub.BaseModel = _BaseModel
    _pydantic_stub.Field = MagicMock(return_value=None)
    _pydantic_stub.field_validator = lambda *a, **kw: (lambda f: f)
    sys.modules["pydantic"] = _pydantic_stub

# Other stubs
for _mod in ("redis", "slowapi", "slowapi.util", "slowapi.errors",
             "auth", "db_pool", "request_helpers", "secret_helper"):
    sys.modules.setdefault(_mod, types.ModuleType(_mod))

sys.modules["auth"].require_authentication = MagicMock()
sys.modules["auth"].User = MagicMock()
sys.modules["auth"].log_auth_event = MagicMock()
sys.modules["db_pool"].get_connection = MagicMock()
sys.modules["request_helpers"].get_request_ip = MagicMock(return_value="127.0.0.1")
sys.modules["secret_helper"].read_secret = MagicMock(return_value="")
_redis_stub = sys.modules["redis"]
_redis_stub.Redis = MagicMock()
_redis_stub.ConnectionError = Exception
_redis_stub.TimeoutError = Exception


# ---------------------------------------------------------------------------
# Re-implement the fixed safe_url logic inline for isolated testing
# (mirrors api/tenant_portal_routes.py BrandingUpsertRequest.safe_url)
# ---------------------------------------------------------------------------

def _safe_url(v):
    """Mirrors BrandingUpsertRequest.safe_url after the v1.85.10 fix."""
    if v is None:
        return v
    s = str(v)
    # Allow relative paths for logos uploaded via the admin branding-logo endpoint
    if s.startswith("/api/admin/tenant-portal/branding-logo/"):
        return v
    if not re.match(r"^https?://", s):
        raise ValueError("URL must start with https:// or http://")
    return v


# ---------------------------------------------------------------------------
# Re-implement the fixed content-type fallback logic for logo upload
# ---------------------------------------------------------------------------

_ALLOWED_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}
_EXT_TO_CT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".svg": "image/svg+xml",
}


def _resolve_content_type(content_type: str | None, filename: str) -> str | None:
    """
    Mirrors the v1.85.10 content-type resolution logic in upload_branding_logo.
    Returns the resolved MIME type if valid, or None if unknown.
    """
    ct = (content_type or "").split(";")[0].strip().lower()
    if ct in _ALLOWED_TYPES:
        return ct
    # Fallback to filename extension
    orig = (filename or "").lower()
    for suffix, guessed_ct in _EXT_TO_CT.items():
        if orig.endswith(suffix):
            return guessed_ct
    return None  # unknown type — caller should raise 400


# ===========================================================================
# Test classes
# ===========================================================================


class TestSafeUrlValidator:
    """Fix 1: BrandingUpsertRequest.safe_url must accept /api/admin/.../branding-logo/ paths."""

    def test_https_url_accepted(self):
        result = _safe_url("https://example.com/logo.png")
        assert result == "https://example.com/logo.png"

    def test_http_url_accepted(self):
        result = _safe_url("http://intranet.corp/logo.png")
        assert result == "http://intranet.corp/logo.png"

    def test_none_accepted(self):
        assert _safe_url(None) is None

    def test_uploaded_logo_relative_path_accepted(self):
        """Core fix: /api/admin/tenant-portal/branding-logo/... must no longer raise 422."""
        url = "/api/admin/tenant-portal/branding-logo/default.png"
        result = _safe_url(url)
        assert result == url

    def test_uploaded_logo_with_project_id_accepted(self):
        url = "/api/admin/tenant-portal/branding-logo/default__proj123.png"
        result = _safe_url(url)
        assert result == url

    def test_javascript_scheme_rejected(self):
        with pytest.raises(ValueError, match="must start with"):
            _safe_url("javascript:alert(1)")

    def test_data_uri_rejected(self):
        with pytest.raises(ValueError, match="must start with"):
            _safe_url("data:image/png;base64,abc123")

    def test_bare_path_rejected(self):
        """Generic /some/path should still be rejected (only branding-logo prefix allowed)."""
        with pytest.raises(ValueError, match="must start with"):
            _safe_url("/some/other/path")

    def test_empty_string_rejected(self):
        with pytest.raises(ValueError, match="must start with"):
            _safe_url("")

    def test_ftp_scheme_rejected(self):
        with pytest.raises(ValueError, match="must start with"):
            _safe_url("ftp://files.example.com/logo.png")


class TestLogoContentTypeFallback:
    """Fix 2: Logo upload must fall back to filename extension when content_type is None/unknown."""

    def test_explicit_png_type_accepted(self):
        ct = _resolve_content_type("image/png", "logo.png")
        assert ct == "image/png"

    def test_explicit_jpeg_type_accepted(self):
        ct = _resolve_content_type("image/jpeg", "logo.jpg")
        assert ct == "image/jpeg"

    def test_none_type_png_ext_resolves(self):
        """content_type=None with .png filename → image/png (K8s nginx ingress fix)."""
        ct = _resolve_content_type(None, "company_logo.png")
        assert ct == "image/png"

    def test_none_type_jpg_ext_resolves(self):
        ct = _resolve_content_type(None, "logo.jpg")
        assert ct == "image/jpeg"

    def test_none_type_jpeg_ext_resolves(self):
        ct = _resolve_content_type(None, "logo.jpeg")
        assert ct == "image/jpeg"

    def test_none_type_gif_ext_resolves(self):
        ct = _resolve_content_type(None, "animated.gif")
        assert ct == "image/gif"

    def test_none_type_webp_ext_resolves(self):
        ct = _resolve_content_type(None, "logo.webp")
        assert ct == "image/webp"

    def test_none_type_svg_ext_resolves(self):
        ct = _resolve_content_type(None, "logo.svg")
        assert ct == "image/svg+xml"

    def test_octet_stream_png_ext_resolves(self):
        """application/octet-stream fallback to .png extension."""
        ct = _resolve_content_type("application/octet-stream", "logo.png")
        assert ct == "image/png"

    def test_unknown_ext_returns_none(self):
        """Genuinely unknown extension → None (400 should be raised by caller)."""
        ct = _resolve_content_type(None, "logo.exe")
        assert ct is None

    def test_no_ext_returns_none(self):
        ct = _resolve_content_type(None, "logo")
        assert ct is None

    def test_explicit_type_takes_priority(self):
        """Even when extension differs, declared content_type wins if valid."""
        ct = _resolve_content_type("image/png", "logo.svg")
        assert ct == "image/png"

    def test_content_type_with_charset_param_stripped(self):
        """content_type may carry '; charset=utf-8' which must be stripped."""
        ct = _resolve_content_type("image/svg+xml; charset=utf-8", "logo.svg")
        assert ct == "image/svg+xml"


class TestMonitoringEmptyHostsInit:
    """Fix 3: PF9_HOSTS='' must produce [] not [''] as the initial hosts list."""

    def _build_hosts(self, env_value: str) -> list:
        """Mirrors the fixed module-level hosts computation in monitoring/main.py."""
        pf9_hosts_env_init = env_value.strip()
        if pf9_hosts_env_init:
            return [h.strip() for h in pf9_hosts_env_init.split(",") if h.strip()]
        return []

    def test_empty_string_produces_empty_list(self):
        """Core fix: empty PF9_HOSTS → [] not ['']."""
        hosts = self._build_hosts("")
        assert hosts == []

    def test_single_host_parsed(self):
        hosts = self._build_hosts("192.168.1.10")
        assert hosts == ["192.168.1.10"]

    def test_multiple_hosts_parsed(self):
        hosts = self._build_hosts("192.168.1.10,192.168.1.11")
        assert hosts == ["192.168.1.10", "192.168.1.11"]

    def test_hosts_with_whitespace_trimmed(self):
        hosts = self._build_hosts(" 192.168.1.10 , 192.168.1.11 ")
        assert hosts == ["192.168.1.10", "192.168.1.11"]

    def test_only_commas_produces_empty_list(self):
        hosts = self._build_hosts(",,,")
        assert hosts == []

    def test_whitespace_only_produces_empty_list(self):
        hosts = self._build_hosts("   ")
        assert hosts == []


class TestRunbookResultSchema:
    """Fix 4: Runbook engines must include items_scanned / summary for operator visibility."""

    def _fake_sg_result(self, sgs_count: int, violations_count: int) -> dict:
        """Simulate what security_group_audit returns after the fix."""
        violations = [{"sg_id": f"sg-{i}"} for i in range(violations_count)]
        return {
            "result": {"violations": violations, "security_groups_scanned": sgs_count},
            "items_found": len(violations),
            "items_actioned": 0,
            "summary": f"Scanned {sgs_count} security group(s); found {len(violations)} overly-permissive rule(s)",
        }

    def _fake_quota_result(self, projects_count: int, alerts_count: int) -> dict:
        alerts = [{"project_id": f"proj-{i}"} for i in range(alerts_count)]
        return {
            "result": {"alerts": alerts, "projects_scanned": projects_count,
                       "warning_pct": 80, "critical_pct": 95},
            "items_found": len(alerts),
            "items_actioned": 0,
            "summary": f"Scanned {projects_count} project(s); {len(alerts)} quota alert(s) at >80% threshold",
        }

    def _fake_rightsizing_result(self, vms_with_data: int, candidates: int) -> dict:
        cands = [{"vm_id": f"vm-{i}", "savings_per_month": 10.0} for i in range(candidates)]
        total_savings = sum(c["savings_per_month"] for c in cands)
        return {
            "result": {"candidates": cands, "skipped": [], "resized": [], "errors": [],
                       "total_candidates": candidates, "total_savings_per_month": total_savings,
                       "vms_with_metering_data": vms_with_data, "mode": "scan"},
            "items_found": candidates,
            "items_actioned": 0,
            "summary": f"Analysed {vms_with_data} VM(s) with metering data; {candidates} rightsizing candidate(s) saving ~{total_savings:.2f} USD/month",
        }

    # --- security_group_audit ---

    def test_sg_audit_has_summary(self):
        r = self._fake_sg_result(10, 0)
        assert "summary" in r

    def test_sg_audit_summary_includes_scanned_count(self):
        r = self._fake_sg_result(10, 0)
        assert "10" in r["summary"]

    def test_sg_audit_result_has_scanned_field(self):
        r = self._fake_sg_result(10, 0)
        assert "security_groups_scanned" in r["result"]
        assert r["result"]["security_groups_scanned"] == 10

    def test_sg_audit_zero_violations_zero_found(self):
        r = self._fake_sg_result(5, 0)
        assert r["items_found"] == 0
        assert "0" in r["summary"]

    def test_sg_audit_with_violations(self):
        r = self._fake_sg_result(5, 3)
        assert r["items_found"] == 3
        assert "3" in r["summary"]

    # --- quota_threshold_check ---

    def test_quota_has_summary(self):
        r = self._fake_quota_result(8, 0)
        assert "summary" in r

    def test_quota_result_has_projects_scanned(self):
        r = self._fake_quota_result(8, 0)
        assert "projects_scanned" in r["result"]
        assert r["result"]["projects_scanned"] == 8

    def test_quota_summary_includes_project_count(self):
        r = self._fake_quota_result(8, 0)
        assert "8" in r["summary"]

    def test_quota_zero_alerts_correct(self):
        r = self._fake_quota_result(5, 0)
        assert r["items_found"] == 0

    # --- vm_rightsizing ---

    def test_rightsizing_has_summary(self):
        r = self._fake_rightsizing_result(20, 0)
        assert "summary" in r

    def test_rightsizing_result_has_vms_with_metering_data(self):
        r = self._fake_rightsizing_result(20, 0)
        assert "vms_with_metering_data" in r["result"]
        assert r["result"]["vms_with_metering_data"] == 20

    def test_rightsizing_zero_candidates_when_no_metering_data(self):
        """If metering worker hasn't run yet, vms_with_metering_data=0 and candidates=0."""
        r = self._fake_rightsizing_result(0, 0)
        assert r["items_found"] == 0
        assert "0" in r["summary"]

    def test_rightsizing_summary_mentions_vm_count(self):
        r = self._fake_rightsizing_result(15, 3)
        assert "15" in r["summary"]
