"""Wave 5 — CLI mirror of the v7 "Integrated Board" data seam (anchor.py rnd ...).

Proves IMPLEMENTATION-PLAN.md "## Wave 5 — CLI mirror": the new read subcommand
DELEGATES to the shared v7 seam (no forked logic):

  - rnd blurb <pid> --lane <lane> --session <id>  → summarizer.session_blurb

It is read-only (never runs the model / starts a PTY) and HONEST when the session
summary is uncached ("(no summary yet)"). Hermetic: tmp ANCHOR_DATA_DIR, stub PTY
backend, ANCHOR_RUNNER_CMD → tests/fake_claude.py (NEVER live claude / real PTY /
:8777). A cached summary is written DIRECTLY via the summarizer cache writer so the
test needs no git worktree — it exercises the blurb read + normalize seam only.
"""
import importlib
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(tmp_path / "wt"))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    for name in ("job_runner", "rnd_registry", "effort_history", "sessions",
                 "session_registry", "worktrees", "pty_manager",
                 "terminal_session", "summarizer", "anchor_marker", "anchor"):
        importlib.reload(importlib.import_module(name))
    import anchor
    import rnd_registry
    import summarizer
    import effort_history
    yield {"tmp": tmp_path, "anchor": anchor, "rnd": rnd_registry,
           "summarizer": summarizer, "eh": effort_history}
    try:
        import pty_manager
        for sid in list(pty_manager.live_sessions()):
            try:
                pty_manager.kill(sid)
            except Exception:
                pass
    except Exception:
        pass


def _mkproject(env, name="Anchor"):
    folder = env["tmp"] / "proj"
    folder.mkdir(parents=True, exist_ok=True)
    return env["rnd"].add_project(name, str(folder)), folder


def _cache_session_summary(env, folder, pid, lane, session_id, claims):
    """Write a session summary cache DIRECTLY (no model run) for the blurb read."""
    summ = env["summarizer"]
    eh = env["eh"]
    store_lane = eh._resolve_subdir(lane)
    structured = {
        "session_id": session_id,
        "lane": lane,
        "kind": "session",
        "claims": list(claims),
        "skill": "researchPrime",
        "prompts": [],
        "actions": [],
        "what_was_asked": "",
        "title": "hc v7 session",
    }
    summ._write_cache(str(folder), pid, store_lane, session_id, structured)


# ── rnd_blurb mirror ─────────────────────────────────────────────────────────

def test_rnd_blurb_returns_short_clean_line(env):
    anchor, summarizer = env["anchor"], env["summarizer"]
    proj, folder = _mkproject(env)
    pid = proj["id"]
    sid = "sess-1"
    # A glyph/markdown-laden claim — the blurb must come back clean + capped.
    _cache_session_summary(env, folder, pid, "research", sid,
                           ["**Goal:** ship X — handle ## edge `cases` ✓ done"])
    out = anchor.rnd_blurb(pid, "research", sid)
    assert out, "blurb should be non-empty for a cached summary"
    for glyph in ("**", "##", "`", "✓", "—"):
        assert glyph not in out, f"blurb leaked a {glyph!r} glyph"
    # The mirror agrees with the shared summarizer seam directly.
    assert out == summarizer.session_blurb(str(folder), pid, "research", sid)


def test_rnd_blurb_honest_absent_when_uncached(env):
    """No cached summary → honest empty string (never fabricated)."""
    anchor = env["anchor"]
    proj, _ = _mkproject(env)
    out = anchor.rnd_blurb(proj["id"], "research", "no-such-session")
    assert out == ""


def test_rnd_blurb_unknown_project_raises_keyerror(env):
    anchor = env["anchor"]
    with pytest.raises(KeyError):
        anchor.rnd_blurb("deadbeef-not-real", "research", "x")


# ── the _rnd_cli dispatcher (argv path) ──────────────────────────────────────

def test_cli_blurb_prints_clean_line(env, capsys):
    anchor = env["anchor"]
    proj, folder = _mkproject(env)
    pid = proj["id"]
    sid = "sess-cli"
    _cache_session_summary(env, folder, pid, "research", sid,
                           ["Ship the integrated board and handle edge cases"])
    anchor._rnd_cli(["blurb", pid, "--lane", "research", "--session", sid])
    out = capsys.readouterr().out
    assert sid in out
    assert "integrated board" in out
    assert "(no summary yet)" not in out


def test_cli_blurb_honest_absent(env, capsys):
    anchor = env["anchor"]
    proj, _ = _mkproject(env)
    anchor._rnd_cli(["blurb", proj["id"], "--lane", "research",
                     "--session", "nope"])
    out = capsys.readouterr().out
    assert "(no summary yet)" in out


def test_cli_blurb_usage_when_missing_args(env, capsys):
    anchor = env["anchor"]
    proj, _ = _mkproject(env)
    anchor._rnd_cli(["blurb", proj["id"]])
    out = capsys.readouterr().out
    assert "Usage: anchor.py rnd blurb" in out


def test_cli_blurb_unknown_project_clean(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli(["blurb", "deadbeef-not-real", "--lane", "research",
                     "--session", "x"])
    out = capsys.readouterr().out
    assert "Unknown project" in out


def test_cli_rnd_usage_lists_blurb(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli([])
    out = capsys.readouterr().out
    assert "blurb" in out
