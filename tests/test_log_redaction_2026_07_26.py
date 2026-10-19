"""Access-log secret-redaction tests (2026-07-26 hardening, P0.4).

Every authed GET used to write the LIVE capability token verbatim into
``logs/nssm-stdout.log`` — tens of thousands of lines — in the very directory
the collaborator install email tells people to inspect when something breaks.
The GET-with-``?token=`` transport is by design; leaking it to disk was not.

Redaction happens at the single place request lines are written, so no call
site can forget it.
"""
import importlib.util
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def _redactor():
    """Pull the classmethod off anchor_gui WITHOUT importing it (it boots a server)."""
    src = (REPO / "anchor_gui.py").read_text(encoding="utf-8", errors="replace")
    start = src.index("_LOG_REDACT_PARAMS")
    end = src.index("def log_message", start)
    snippet = "class _P:\n    " + src[start:end].strip().replace("\n    ", "\n    ")
    ns = {}
    exec(compile(snippet, "<redactor>", "exec"), ns)  # noqa: S102 - test harness
    return ns["_P"]._redact_request_line


@pytest.mark.parametrize("raw,must_not_contain", [
    ("GET /api/rnd/orphan_check?token=kKWUVEG4UocROdfBpY8ydm0S2qZgLH7XAyLKfnBkk HTTP/1.1",
     "kKWUVEG4UocROdfBpY8ydm0S2qZgLH7XAyLKfnBkk"),
    ("GET /api/rnd/term_ws?session=abc&token=SEKRIT123&since=5 HTTP/1.1", "SEKRIT123"),
    ("GET /x?capability=CAP987 HTTP/1.1", "CAP987"),
    ("GET /y?nonce=NONCE55 HTTP/1.1", "NONCE55"),
])
def test_secrets_never_reach_the_log_line(raw, must_not_contain):
    out = _redactor()(raw)
    assert must_not_contain not in out, f"secret survived redaction: {out}"
    assert "<redacted>" in out


def test_the_rest_of_the_line_is_preserved_for_debugging():
    """Redaction must not destroy the log's usefulness."""
    out = _redactor()("GET /api/rnd/term_ws?session=abc123&token=SEKRIT&since=42 HTTP/1.1")
    assert "session=abc123" in out, "the session id must survive"
    assert "since=42" in out, "other params must survive"
    assert "/api/rnd/term_ws" in out and "HTTP/1.1" in out


def test_lines_without_secrets_are_unchanged():
    plain = "GET /api/version HTTP/1.1"
    assert _redactor()(plain) == plain


def test_redaction_is_case_insensitive_and_covers_every_param():
    out = _redactor()("GET /x?TOKEN=AAA&Secret=BBB&KEY=CCC HTTP/1.1")
    for leaked in ("AAA", "BBB", "CCC"):
        assert leaked not in out, f"{leaked} leaked: {out}"


def test_the_writer_actually_uses_the_redactor():
    """A redactor nothing calls is the exact class of defect this review exists for."""
    src = (REPO / "anchor_gui.py").read_text(encoding="utf-8", errors="replace")
    writer = src.split("def log_message", 1)[1].split("\n    def ", 1)[0]
    assert "_redact_request_line" in writer, (
        "log_message must route the request line through the redactor")
