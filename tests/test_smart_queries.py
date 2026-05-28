import re
import sys
from pathlib import Path

# Allow importing api modules as top-level modules (same style used by existing tests)
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

import smart_queries as sq  # noqa: E402


class _FakeCursor:
    def __init__(self, rows):
        self._rows = rows

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, _sql, _params):
        return None

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self, cursor_factory=None):  # noqa: ARG002
        return _FakeCursor(self._rows)


def _mk_query(query_id: str, pattern: str):
    return sq.SmartQuery(
        id=query_id,
        title=query_id,
        pattern=re.compile(pattern, re.I),
        sql="SELECT 1 AS count",
        formatter=lambda rows, _params: {
            "card_type": "number",
            "title": "x",
            "value": rows[0]["count"] if rows else 0,
        },
        description=f"desc {query_id}",
    )


def test_regex_match_wins_without_llm(monkeypatch):
    fake_queries = [_mk_query("regex_q", r"hello")]
    monkeypatch.setattr(sq, "SMART_QUERIES", fake_queries)

    llm_calls = {"n": 0}

    def _fake_llm(_question, _smart_queries, _conn):
        llm_calls["n"] += 1
        return "regex_q"

    monkeypatch.setattr(sq, "_llm_classify_query", _fake_llm)

    result = sq.execute_smart_query("hello there", _FakeConn([{"count": 1}]))

    assert result is not None
    assert result["matched"] is True
    assert result["query_id"] == "regex_q"
    assert result["matched_via"] == "regex"
    assert llm_calls["n"] == 0


def test_llm_fallback_selects_query(monkeypatch):
    fake_queries = [_mk_query("llm_q", r"^nevermatch$")]
    monkeypatch.setattr(sq, "SMART_QUERIES", fake_queries)

    monkeypatch.setattr(sq, "_llm_classify_query", lambda *_args, **_kwargs: "llm_q")

    result = sq.execute_smart_query("what is idle compute", _FakeConn([{"count": 3}]))

    assert result is not None
    assert result["query_id"] == "llm_q"
    assert result["matched_via"] == "llm"
    assert result["value"] == 3


def test_no_regex_and_no_llm_match_returns_none(monkeypatch):
    fake_queries = [_mk_query("q1", r"^nevermatch$")]
    monkeypatch.setattr(sq, "SMART_QUERIES", fake_queries)
    monkeypatch.setattr(sq, "_llm_classify_query", lambda *_args, **_kwargs: None)

    result = sq.execute_smart_query("unrelated phrase", _FakeConn([{"count": 1}]))

    assert result is None


def test_llm_classifier_disabled_when_copilot_disabled(monkeypatch):
    monkeypatch.setenv("COPILOT_ENABLED", "false")

    # conn is unused when disabled
    result = sq._llm_classify_query("question", [_mk_query("x", r"x")], _FakeConn([]))

    assert result is None
