from __future__ import annotations

import os
import sys
import types
import importlib


# Ensure api/ directory is importable
_API_DIR = os.path.join(os.path.dirname(__file__), "..", "api")
if _API_DIR not in sys.path:
    sys.path.insert(0, _API_DIR)


def _make_stub(name: str, **attrs):
    m = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(m, key, value)
    return m


class _APIRouter:
    def __init__(self, *args, **kwargs):
        _ = (args, kwargs)

    def _decorator(self, *args, **kwargs):
        _ = (args, kwargs)
        return lambda fn: fn

    get = _decorator
    post = _decorator
    put = _decorator
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


def _Field(default=None, default_factory=None, **kwargs):
    _ = kwargs
    if default_factory is not None:
        return default_factory()
    return default


def _field_validator(*args, **kwargs):
    _ = (args, kwargs)

    def _wrap(fn):
        return fn

    return _wrap


class _Limiter:
    def limit(self, _spec):
        return lambda fn: fn


class _Cursor:
    def __init__(self, rows):
        self._rows = list(rows)
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchone(self):
        if self._rows:
            return self._rows.pop(0)
        return None


class _Conn:
    def __init__(self, rows):
        self.cursor_obj = _Cursor(rows)
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def cursor(self, cursor_factory=None):  # noqa: ARG002
        return self.cursor_obj

    def commit(self):
        self.committed = True


# Stub dependencies before import
_fastapi_mod = sys.modules.get("fastapi")
if _fastapi_mod is None:
    _fastapi_mod = _make_stub(
        "fastapi",
        APIRouter=_APIRouter,
        Depends=lambda x: x,
        Header=lambda default=None, alias=None: default,
        HTTPException=_HTTPException,
        Request=object,
        status=_make_stub(
            "status",
            HTTP_200_OK=200,
            HTTP_201_CREATED=201,
            HTTP_204_NO_CONTENT=204,
            HTTP_401_UNAUTHORIZED=401,
            HTTP_403_FORBIDDEN=403,
            HTTP_404_NOT_FOUND=404,
            HTTP_422_UNPROCESSABLE_ENTITY=422,
        ),
    )
    sys.modules["fastapi"] = _fastapi_mod
else:
    if not hasattr(_fastapi_mod, "APIRouter"):
        setattr(_fastapi_mod, "APIRouter", _APIRouter)
    if not hasattr(_fastapi_mod, "Depends"):
        setattr(_fastapi_mod, "Depends", lambda x: x)
    if not hasattr(_fastapi_mod, "Header"):
        setattr(_fastapi_mod, "Header", lambda default=None, alias=None: default)
    if not hasattr(_fastapi_mod, "HTTPException"):
        setattr(_fastapi_mod, "HTTPException", _HTTPException)
    if not hasattr(_fastapi_mod, "Request"):
        setattr(_fastapi_mod, "Request", object)
    if not hasattr(_fastapi_mod, "status"):
        setattr(_fastapi_mod, "status", _make_stub("status"))

    _status = getattr(_fastapi_mod, "status")
    if not hasattr(_status, "HTTP_200_OK"):
        setattr(_status, "HTTP_200_OK", 200)
    if not hasattr(_status, "HTTP_201_CREATED"):
        setattr(_status, "HTTP_201_CREATED", 201)
    if not hasattr(_status, "HTTP_204_NO_CONTENT"):
        setattr(_status, "HTTP_204_NO_CONTENT", 204)
    if not hasattr(_status, "HTTP_401_UNAUTHORIZED"):
        setattr(_status, "HTTP_401_UNAUTHORIZED", 401)
    if not hasattr(_status, "HTTP_403_FORBIDDEN"):
        setattr(_status, "HTTP_403_FORBIDDEN", 403)
    if not hasattr(_status, "HTTP_404_NOT_FOUND"):
        setattr(_status, "HTTP_404_NOT_FOUND", 404)
    if not hasattr(_status, "HTTP_422_UNPROCESSABLE_ENTITY"):
        setattr(_status, "HTTP_422_UNPROCESSABLE_ENTITY", 422)

sys.modules.setdefault("fastapi.responses", _make_stub("fastapi.responses", JSONResponse=lambda *args, **kwargs: None))
_pydantic_mod = sys.modules.get("pydantic")
if _pydantic_mod is None:
    sys.modules["pydantic"] = _make_stub("pydantic", BaseModel=_BaseModel, Field=_Field, field_validator=_field_validator)
else:
    if not hasattr(_pydantic_mod, "BaseModel"):
        setattr(_pydantic_mod, "BaseModel", _BaseModel)
    if not hasattr(_pydantic_mod, "Field"):
        setattr(_pydantic_mod, "Field", _Field)
    if not hasattr(_pydantic_mod, "field_validator"):
        setattr(_pydantic_mod, "field_validator", _field_validator)

sys.modules.setdefault("psycopg2", _make_stub("psycopg2"))
sys.modules.setdefault("psycopg2.extras", _make_stub("psycopg2.extras", RealDictCursor=object))
# Some tests preload a partial auth stub; add missing symbols for deterministic import.
_auth_mod = sys.modules.get("auth")
if _auth_mod is None:
    sys.modules["auth"] = _make_stub(
        "auth",
        User=dict,
        require_permission=lambda *_args, **_kwargs: {"username": "admin"},
        require_authentication=lambda: {"role": "admin", "username": "admin"},
    )
else:
    if not hasattr(_auth_mod, "User"):
        setattr(_auth_mod, "User", dict)
    if not hasattr(_auth_mod, "require_permission"):
        setattr(_auth_mod, "require_permission", lambda *_args, **_kwargs: {"username": "admin"})
    if not hasattr(_auth_mod, "require_authentication"):
        setattr(_auth_mod, "require_authentication", lambda: {"role": "admin", "username": "admin"})

sys.modules.setdefault("db_pool", _make_stub("db_pool", get_connection=lambda: None))
sys.modules.setdefault("crypto_helper", _make_stub("crypto_helper", fernet_encrypt=lambda *_args, **_kwargs: "enc", fernet_decrypt=lambda *_args, **_kwargs: "token-ok"))
sys.modules.setdefault("event_bus", _make_stub("event_bus", emit_event=lambda **kwargs: None))

# Force a clean import so prior tests cannot leave psa_routes decorated with mocks.
_prev_rate_limit_mod = sys.modules.get("rate_limit")
sys.modules["rate_limit"] = _make_stub("rate_limit", limiter=_Limiter())
sys.modules.pop("psa_routes", None)
psa = importlib.import_module("psa_routes")  # noqa: E402
if _prev_rate_limit_mod is None:
    del sys.modules["rate_limit"]
else:
    sys.modules["rate_limit"] = _prev_rate_limit_mod


def test_map_inbound_status_from_status_map():
    mapped = psa._map_inbound_status("Done", {"Done": "resolved"})
    assert mapped == "resolved"


def test_psa_inbound_rejects_invalid_token(monkeypatch):
    conn = _Conn([
        {"id": 1, "inbound_enabled": True, "inbound_token": "enc", "status_map": {"Done": "resolved"}},
    ])
    monkeypatch.setattr(psa, "get_connection", lambda: conn)
    monkeypatch.setattr(psa, "fernet_decrypt", lambda *_args, **_kwargs: "token-ok")

    body = psa.PsaInboundPayload(ticket_id="T-1", status="Done")

    try:
        psa.psa_inbound_status_webhook(
            request=object(),
            config_id=1,
            body=body,
            x_psa_token="wrong-token",
        )
        assert False, "Expected HTTPException"
    except Exception as exc:
        assert getattr(exc, "status_code", None) == 401


def test_psa_inbound_returns_unmatched_for_unknown_ticket(monkeypatch):
    conn = _Conn([
        {"id": 1, "inbound_enabled": True, "inbound_token": "enc", "status_map": {"Done": "resolved"}},
        None,
    ])
    monkeypatch.setattr(psa, "get_connection", lambda: conn)
    monkeypatch.setattr(psa, "fernet_decrypt", lambda *_args, **_kwargs: "token-ok")

    body = psa.PsaInboundPayload(ticket_id="T-404", status="Done")
    result = psa.psa_inbound_status_webhook(
        request=object(),
        config_id=1,
        body=body,
        x_psa_token="token-ok",
    )

    assert result["matched"] is False
    assert result["insight_id"] is None


def test_psa_inbound_maps_status_and_updates_insight(monkeypatch):
    emitted = []
    conn = _Conn([
        {"id": 1, "inbound_enabled": True, "inbound_token": "enc", "status_map": {"Done": "resolved"}},
        {
            "id": 42,
            "type": "risk_security",
            "entity_type": "server",
            "entity_id": "srv-1",
            "entity_name": "srv-1",
            "metadata": {"psa_ticket_id": "T-1"},
        },
    ])

    monkeypatch.setattr(psa, "get_connection", lambda: conn)
    monkeypatch.setattr(psa, "fernet_decrypt", lambda *_args, **_kwargs: "token-ok")
    monkeypatch.setattr(psa, "emit_event", lambda **kwargs: emitted.append(kwargs))

    body = psa.PsaInboundPayload(ticket_id="T-1", status="Done", resolution_note="Fixed")
    result = psa.psa_inbound_status_webhook(
        request=object(),
        config_id=1,
        body=body,
        x_psa_token="token-ok",
    )

    assert result == {"matched": True, "insight_id": 42}
    assert conn.committed is True
    assert any("UPDATE operational_insights" in sql for sql, _ in conn.cursor_obj.executed)
    assert emitted
