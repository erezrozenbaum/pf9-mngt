from __future__ import annotations

import json
import os
import sys
import types
from types import SimpleNamespace

# Ensure api/ directory is importable
_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)


def _make_stub(name: str, **attrs):
    m = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(m, key, value)
    return m


class _FakeRedis:
    def __init__(self):
        self.store = {}

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, _ttl, value):
        self.store[key] = value


class _FakeCursor:
    def __init__(self, row=None):
        self._row = row
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, cursor_factory=None):  # noqa: ARG002
        return self._cursor


# Stub heavy dependencies before importing module under test
class _APIRouter:
    def __init__(self, *args, **kwargs):
        _ = (args, kwargs)

    def _decorator(self, *args, **kwargs):
        _ = (args, kwargs)
        return lambda fn: fn

    get = _decorator
    post = _decorator
    patch = _decorator
    delete = _decorator


class _HTTPException(Exception):
    def __init__(self, status_code, detail):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class _BaseModel:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

    def model_dump(self, exclude_unset=False):
        _ = exclude_unset
        return dict(self.__dict__)


def _Field(default=None, default_factory=None, **kwargs):
    _ = kwargs
    if default_factory is not None:
        return default_factory()
    return default


sys.modules.setdefault(
    "fastapi",
    _make_stub(
        "fastapi",
        APIRouter=_APIRouter,
        Depends=lambda x: x,
        HTTPException=_HTTPException,
        status=SimpleNamespace(
            HTTP_201_CREATED=201,
            HTTP_204_NO_CONTENT=204,
            HTTP_400_BAD_REQUEST=400,
            HTTP_403_FORBIDDEN=403,
            HTTP_404_NOT_FOUND=404,
            HTTP_422_UNPROCESSABLE_ENTITY=422,
        ),
    ),
)
sys.modules.setdefault("pydantic", _make_stub("pydantic", BaseModel=_BaseModel, Field=_Field))
sys.modules.setdefault("psycopg2", _make_stub("psycopg2"))
sys.modules.setdefault("psycopg2.extras", _make_stub("psycopg2.extras", RealDictCursor=object))

sys.modules.setdefault("auth", _make_stub("auth", User=dict, require_authentication=lambda: {"role": "admin"}))
sys.modules.setdefault("db_pool", _make_stub("db_pool", get_connection=lambda: None))
sys.modules.setdefault("cache", _make_stub("cache", _get_client=lambda: None))

import maintenance_routes as mw  # noqa: E402


def test_get_active_maintenance_window_returns_db_match(monkeypatch):
    row = {
        "id": 7,
        "title": "Planned migration",
        "starts_at": __import__("datetime").datetime(2026, 1, 1, 0, 0),
        "ends_at": __import__("datetime").datetime(2026, 1, 1, 4, 0),
        "scope": {"project_ids": ["proj-a"]},
        "suppress_clea": True,
        "suppress_sla_defense": True,
        "suppress_notifications": False,
        "created_by": "ops",
        "created_at": __import__("datetime").datetime(2026, 1, 1, 0, 0),
        "updated_at": __import__("datetime").datetime(2026, 1, 1, 0, 0),
    }
    cur = _FakeCursor(row=row)
    conn = _FakeConn(cur)
    redis = _FakeRedis()

    monkeypatch.setattr(mw, "get_connection", lambda: conn)
    monkeypatch.setitem(sys.modules, "cache", _make_stub("cache", _get_client=lambda: redis))

    result = mw.get_active_maintenance_window("proj-a", None, suppress_for="clea")

    assert result is not None
    assert result["id"] == 7
    assert any("FROM ops_maintenance_windows" in sql for sql, _ in cur.executed)


def test_get_active_maintenance_window_uses_cache(monkeypatch):
    redis = _FakeRedis()
    cache_key = "pf9:maint:clea:proj-a:*"
    redis.store[cache_key] = json.dumps({"id": 9, "title": "Cached"})

    monkeypatch.setitem(sys.modules, "cache", _make_stub("cache", _get_client=lambda: redis))
    monkeypatch.setattr(mw, "get_connection", lambda: (_ for _ in ()).throw(RuntimeError("db should not be called")))

    result = mw.get_active_maintenance_window("proj-a", None, suppress_for="clea")

    assert result is not None
    assert result["id"] == 9
