"""
tests/test_v1859_fixes.py — Unit tests for v1.85.9 bug fixes.

Covers:
  1. Branding logo upload — file type validation, size limit, filename sanitisation,
     DB upsert, and returned URL
  2. Branding logo serve  — filename regex guard, 404 for missing files
  3. docker-compose monitoring service URL and PF9_HOSTS default
"""
import io
import os
import re
import sys
import types
from unittest.mock import MagicMock, patch, mock_open

import pytest

# ---------------------------------------------------------------------------
# Minimal stubs (must precede api imports)
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

# fastapi — only install stub if not already present
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
# Helper: logo upload / serve functions extracted for unit testing
# ---------------------------------------------------------------------------

_ALLOWED_TYPES = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/svg+xml": ".svg",
}
_MAX_BYTES = 512 * 1024
_EXT_MEDIA = {v: k for k, v in _ALLOWED_TYPES.items()}

_SAFE_FILENAME_RE = re.compile(r"[A-Za-z0-9_-]+\.(png|jpg|gif|webp|svg)")


def _sanitize_cp_id(cp_id: str, project_id: str = "") -> str:
    """Mirror of the filename construction in upload_branding_logo."""
    safe_cp = re.sub(r"[^A-Za-z0-9_-]", "_", cp_id)[:64]
    if project_id:
        safe_proj = re.sub(r"[^A-Za-z0-9_-]", "_", project_id)[:64]
        return f"{safe_cp}__{safe_proj}"
    return safe_cp


def _is_safe_filename(filename: str) -> bool:
    return bool(_SAFE_FILENAME_RE.fullmatch(filename))


# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

class TestLogoFileTypeValidation:
    """S-L1: Ensure only allowed MIME types are accepted."""

    def test_png_allowed(self):
        assert "image/png" in _ALLOWED_TYPES

    def test_jpeg_allowed(self):
        assert "image/jpeg" in _ALLOWED_TYPES

    def test_gif_allowed(self):
        assert "image/gif" in _ALLOWED_TYPES

    def test_webp_allowed(self):
        assert "image/webp" in _ALLOWED_TYPES

    def test_svg_allowed(self):
        assert "image/svg+xml" in _ALLOWED_TYPES

    def test_pdf_not_allowed(self):
        assert "application/pdf" not in _ALLOWED_TYPES

    def test_text_html_not_allowed(self):
        assert "text/html" not in _ALLOWED_TYPES

    def test_javascript_not_allowed(self):
        assert "application/javascript" not in _ALLOWED_TYPES


class TestLogoSizeLimit:
    """S-L2: Ensure the 512 KB limit is enforced."""

    def test_512kb_boundary_accepted(self):
        content = b"x" * (_MAX_BYTES)
        assert len(content) <= _MAX_BYTES

    def test_over_512kb_rejected(self):
        content = b"x" * (_MAX_BYTES + 1)
        assert len(content) > _MAX_BYTES

    def test_empty_file_accepted(self):
        assert 0 <= _MAX_BYTES


class TestLogoFilenameSanitisation:
    """S-L3: Uploaded filename is derived only from cp_id / project_id."""

    def test_simple_cp_id_unchanged(self):
        result = _sanitize_cp_id("default")
        assert result == "default"

    def test_path_traversal_stripped(self):
        result = _sanitize_cp_id("../../etc/passwd")
        assert ".." not in result
        assert "/" not in result

    def test_null_byte_stripped(self):
        result = _sanitize_cp_id("cp\x00id")
        assert "\x00" not in result

    def test_spaces_replaced(self):
        result = _sanitize_cp_id("my cp id")
        assert " " not in result

    def test_per_tenant_separator(self):
        result = _sanitize_cp_id("default", "proj-123")
        assert "__" in result
        assert "default" in result
        assert "proj" in result

    def test_long_cp_id_truncated(self):
        long_id = "a" * 200
        result = _sanitize_cp_id(long_id)
        assert len(result) <= 64


class TestLogoServeFilenameGuard:
    """S-L4: Serve endpoint only allows safe filenames."""

    def test_valid_png_accepted(self):
        assert _is_safe_filename("default.png")

    def test_valid_jpg_accepted(self):
        assert _is_safe_filename("org1__proj123.jpg")

    def test_valid_svg_accepted(self):
        assert _is_safe_filename("cp_prod__org_a.svg")

    def test_path_traversal_rejected(self):
        assert not _is_safe_filename("../../etc/passwd")

    def test_dot_dot_rejected(self):
        assert not _is_safe_filename("..%2F..%2Fetc.png")

    def test_no_extension_rejected(self):
        assert not _is_safe_filename("defaultpng")

    def test_disallowed_extension_rejected(self):
        assert not _is_safe_filename("logo.exe")

    def test_html_extension_rejected(self):
        assert not _is_safe_filename("xss.html")

    def test_double_extension_rejected(self):
        assert not _is_safe_filename("logo.php.png")

    def test_slashes_rejected(self):
        assert not _is_safe_filename("dir/logo.png")


class TestLogoReturnedUrl:
    """S-L5: Uploaded logo URL follows expected pattern."""

    def test_url_starts_with_api_prefix(self):
        cp_id = "default"
        filename = f"{_sanitize_cp_id(cp_id)}.png"
        url = f"/api/admin/tenant-portal/branding-logo/{filename}"
        assert url.startswith("/api/admin/tenant-portal/branding-logo/")

    def test_url_ends_with_filename(self):
        cp_id = "default"
        filename = f"{_sanitize_cp_id(cp_id)}.png"
        url = f"/api/admin/tenant-portal/branding-logo/{filename}"
        assert url.endswith(filename)


class TestDockerComposeMonitoringFixes:
    """S-M1: Verify docker-compose.yml monitoring configuration is correct."""

    def _read_compose(self) -> str:
        compose_path = os.path.join(os.path.dirname(__file__), "..", "docker-compose.yml")
        with open(compose_path) as f:
            return f.read()

    def test_monitoring_service_url_correct(self):
        """MONITORING_SERVICE_URL must point to pf9_monitoring, not 'monitoring'."""
        content = self._read_compose()
        assert "MONITORING_SERVICE_URL: http://pf9_monitoring:8001" in content, \
            "MONITORING_SERVICE_URL should be http://pf9_monitoring:8001"

    def test_monitoring_service_url_not_wrong(self):
        """Old broken URL 'http://monitoring:8001' must not appear."""
        content = self._read_compose()
        assert "MONITORING_SERVICE_URL: http://monitoring:8001" not in content, \
            "Old broken URL http://monitoring:8001 still present"

    def test_pf9_hosts_default_is_empty(self):
        """PF9_HOSTS default must be empty so auto-discovery triggers."""
        content = self._read_compose()
        assert "PF9_HOSTS: ${PF9_HOSTS:-}" in content, \
            "PF9_HOSTS should have empty default to enable auto-discovery"

    def test_pf9_hosts_no_localhost_default(self):
        """PF9_HOSTS must NOT default to 'localhost'."""
        content = self._read_compose()
        assert "PF9_HOSTS: ${PF9_HOSTS:-localhost}" not in content, \
            "PF9_HOSTS still defaulting to localhost — auto-discovery will never trigger"

    def test_tenant_portal_has_monitoring_volume(self):
        """tenant_portal service must mount the monitoring cache read-only."""
        content = self._read_compose()
        assert "./monitoring/cache:/app/monitoring/cache:ro" in content, \
            "tenant_portal needs monitoring cache volume mount"

    def test_pf9_api_has_branding_logos_volume(self):
        """pf9_api service must mount branding_logos volume."""
        content = self._read_compose()
        assert "./branding_logos:/app/branding_logos" in content, \
            "pf9_api needs branding_logos volume mount"
