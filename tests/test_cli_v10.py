"""Wave 8 — CLI mirror of the v10 "Live Handoff & Boneyard" read seams.

Proves IMPLEMENTATION-PLAN.md "## Wave 8 — CLI mirror": the new read subcommands
DELEGATE to the shared v10 seams (no forked logic):

  - rnd boneyard <pid> [--search <q>]  → boneyard.list_entries / boneyard.search
  - rnd next-prompt <pid> --session <id> → the generated NEXT-PROMPT.md body
                                           (pending_paste / worktree NEXT-PROMPT.md)

Both are READ-ONLY (never delete/remove anything / start a PTY / run a model /
hit the network) and HONEST when absent (a project with no discards → "No
discarded material"; a session with no handoff → "(no handoff prompt)").
Hermetic: tmp ANCHOR_DATA_DIR, stub PTY backend, ANCHOR_RUNNER_CMD →
tests/fake_claude.py (NEVER live claude / real PTY / :8777). The Boneyard
entries + session records are seeded DIRECTLY via the shared modules so the test
needs no live session — it exercises the read mirror only.
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
                 "terminal_session", "summarizer", "anchor_marker", "handoff",
                 "boneyard", "anchor"):
        importlib.reload(importlib.import_module(name))
    import anchor
    import rnd_registry
    import effort_history
    import session_registry
    import boneyard
    yield {"tmp": tmp_path, "anchor": anchor, "rnd": rnd_registry,
           "eh": effort_history, "sreg": session_registry, "bone": boneyard}
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
    folder = env["tmp"] / f"proj-{name.lower().replace(' ', '-')}"
    folder.mkdir(parents=True, exist_ok=True)
    return env["rnd"].add_project(name, str(folder)), folder


# ── usage string lists the new subcommands ─────────────────────────────────

def test_cli_rnd_usage_lists_boneyard_and_next_prompt(env, capsys):
    """`anchor.py rnd` (no subcommand) prints a usage line naming the new seams."""
    anchor = env["anchor"]
    anchor._rnd_cli([])
    out = capsys.readouterr().out
    assert "boneyard" in out
    assert "next-prompt" in out


# ── rnd boneyard mirror ────────────────────────────────────────────────────

def test_rnd_boneyard_honest_empty(env):
    """A project with nothing discarded → empty list (never fabricated)."""
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "Empty")
    assert anchor.rnd_boneyard(proj["id"]) == []


def test_cli_boneyard_honest_empty_message(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "EmptyP")
    anchor._rnd_cli(["boneyard", proj["id"]])
    out = capsys.readouterr().out
    assert "No discarded material" in out


def test_rnd_boneyard_lists_recorded_entry(env):
    """With data: a recorded boneyard entry surfaces in the read mirror."""
    anchor, bone = env["anchor"], env["bone"]
    proj, folder = _mkproject(env, "Discarded")
    pid = proj["id"]
    rec = bone.record_entry(str(folder), pid, {
        "source": bone.SOURCE_KILLED,
        "session_id": "sess-killed-1",
        "lane": "build",
        "title": "widget cache service",
        "summary_excerpt": "Built the cache layer prototype.",
        "doc_rels": ["build/run-1/DELIVERABLE.md"],
    })
    assert rec.get("entry_id")

    entries = anchor.rnd_boneyard(pid)
    assert len(entries) == 1
    e = entries[0]
    # SAFE projection: source badge / title / lane / doc refs.
    assert e["source"] == bone.SOURCE_KILLED
    assert e["title"] == "widget cache service"
    assert e["lane"] == "build"
    assert "build/run-1/DELIVERABLE.md" in e["doc_rels"]
    # SAFE keys only — never an absolute path / worktree / branch.
    assert set(e.keys()) == set(bone._SAFE_KEYS)


def test_cli_boneyard_prints_entry(env, capsys):
    anchor, bone = env["anchor"], env["bone"]
    proj, folder = _mkproject(env, "BoneCLI")
    pid = proj["id"]
    bone.record_entry(str(folder), pid, {
        "source": bone.SOURCE_DELETED,
        "session_id": "sess-del-1",
        "lane": "planning",
        "title": "abandoned migration plan",
        "doc_rels": ["planning/old/MASTER-PLAN.md"],
    })
    anchor._rnd_cli(["boneyard", pid])
    out = capsys.readouterr().out
    assert "discarded item(s)" in out
    assert "[deleted]" in out                       # source badge
    assert "abandoned migration plan" in out        # title
    assert "planning/old/MASTER-PLAN.md" in out     # doc ref


def test_rnd_boneyard_search_filters_to_match(env):
    """--search filters to the matching entry (and a non-match returns nothing)."""
    anchor, bone = env["anchor"], env["bone"]
    proj, folder = _mkproject(env, "Search")
    pid = proj["id"]
    bone.record_entry(str(folder), pid, {
        "source": bone.SOURCE_KILLED, "session_id": "k-cache",
        "lane": "build", "title": "cache prefetch experiment",
        "doc_rels": ["build/cache/NOTES.md"],
    })
    bone.record_entry(str(folder), pid, {
        "source": bone.SOURCE_KILLED, "session_id": "k-ui",
        "lane": "build", "title": "ui polish spike",
        "doc_rels": ["build/ui/NOTES.md"],
    })
    # Both exist unfiltered.
    assert len(anchor.rnd_boneyard(pid)) == 2
    # Filter to the matching one.
    hits = anchor.rnd_boneyard(pid, search="cache")
    assert len(hits) == 1
    assert hits[0]["session_id"] == "k-cache"
    # A non-matching term → honest empty (no fabrication).
    assert anchor.rnd_boneyard(pid, search="zzz-no-such-term") == []


def test_cli_boneyard_search_match_and_no_match(env, capsys):
    anchor, bone = env["anchor"], env["bone"]
    proj, folder = _mkproject(env, "SearchCLI")
    pid = proj["id"]
    bone.record_entry(str(folder), pid, {
        "source": bone.SOURCE_KILLED, "session_id": "k-cache",
        "lane": "build", "title": "cache prefetch experiment",
        "doc_rels": ["build/cache/NOTES.md"],
    })
    anchor._rnd_cli(["boneyard", pid, "--search", "cache"])
    out = capsys.readouterr().out
    assert "matching 'cache'" in out
    assert "cache prefetch experiment" in out

    anchor._rnd_cli(["boneyard", pid, "--search", "zzz-no-such-term"])
    out2 = capsys.readouterr().out
    assert "No discarded material matching 'zzz-no-such-term'" in out2


def test_rnd_boneyard_is_read_only(env):
    """Listing / searching the boneyard NEVER deletes an entry (read-only)."""
    anchor, bone = env["anchor"], env["bone"]
    proj, folder = _mkproject(env, "Persist")
    pid = proj["id"]
    rec = bone.record_entry(str(folder), pid, {
        "source": bone.SOURCE_GRASS_DELETED, "idea_id": "idea-1",
        "lane": "grass", "title": "a discarded idea",
        "idea_text": "a discarded idea",
    })
    eid = rec["entry_id"]
    anchor.rnd_boneyard(pid)
    anchor.rnd_boneyard(pid, search="discarded")
    # The entry is STILL there — the mirror only read it.
    assert bone.get_entry(str(folder), pid, eid) is not None
    assert len(anchor.rnd_boneyard(pid)) == 1


def test_cli_boneyard_usage_when_missing_args(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli(["boneyard"])
    out = capsys.readouterr().out
    assert "Usage: anchor.py rnd boneyard" in out


def test_rnd_boneyard_unknown_project_raises_keyerror(env):
    anchor = env["anchor"]
    with pytest.raises(KeyError):
        anchor.rnd_boneyard("deadbeef-not-real")


def test_cli_boneyard_unknown_project_clean(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli(["boneyard", "deadbeef-not-real"])
    out = capsys.readouterr().out
    assert "Unknown project" in out


# ── rnd next-prompt mirror ─────────────────────────────────────────────────

def test_rnd_next_prompt_honest_absent_unknown_session(env):
    """A session with no record → honest empty string (no fabrication)."""
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "NoSession")
    assert anchor.rnd_next_prompt(proj["id"], "no-such-session") == ""


def test_cli_next_prompt_honest_absent_message(env, capsys):
    anchor, sreg = env["anchor"], env["sreg"]
    proj, _folder = _mkproject(env, "NoHandoff")
    pid = proj["id"]
    # A real session record but with NO pending_paste / NEXT-PROMPT.md / parent.
    rec = sreg.register_session(pid, "build", label="no handoff",
                                status=sreg.STATUS_DONE)
    anchor._rnd_cli(["next-prompt", pid, "--session", rec["session_id"]])
    out = capsys.readouterr().out
    assert "(no handoff prompt)" in out


def test_rnd_next_prompt_returns_pending_paste(env):
    """A session carrying a pending_paste surfaces it verbatim (read-only)."""
    anchor, sreg = env["anchor"], env["sreg"]
    proj, _folder = _mkproject(env, "Pending")
    pid = proj["id"]
    prompt = "PLAN FROM THE RESEARCH REPORT: read planning/x/MASTER-PLAN.md first."
    rec = sreg.register_session(pid, "planning", label="pending paste",
                                status=sreg.STATUS_RUNNING)
    sreg.update_session(rec["session_id"], pending_paste=prompt)
    got = anchor.rnd_next_prompt(pid, rec["session_id"])
    assert got == prompt


def test_cli_next_prompt_prints_pending_paste(env, capsys):
    anchor, sreg = env["anchor"], env["sreg"]
    proj, _folder = _mkproject(env, "PendingCLI")
    pid = proj["id"]
    prompt = "BUILD FROM THE PLAN: read planning/y/IMPLEMENTATION-PLAN.md."
    rec = sreg.register_session(pid, "build", label="pending build",
                                status=sreg.STATUS_RUNNING)
    sreg.update_session(rec["session_id"], pending_paste=prompt)
    anchor._rnd_cli(["next-prompt", pid, "--session", rec["session_id"]])
    out = capsys.readouterr().out
    assert "Next-stage handoff prompt" in out
    assert prompt in out


def test_rnd_next_prompt_reads_next_prompt_md(env, tmp_path):
    """When no pending_paste, the durable NEXT-PROMPT.md in the worktree is read."""
    anchor, sreg = env["anchor"], env["sreg"]
    import handoff as _handoff
    proj, _folder = _mkproject(env, "NextMd")
    pid = proj["id"]
    wt = tmp_path / "wt-next"
    wt.mkdir(parents=True, exist_ok=True)
    body = "BUILD FROM THE PLAN SET\n\nRead these docs, then proceed.\n"
    (wt / _handoff.NEXT_PROMPT_FILENAME).write_text(body, encoding="utf-8")
    rec = sreg.register_session(pid, "build", label="md handoff",
                                status=sreg.STATUS_RUNNING)
    # No pending_paste, but a real worktree_path holding NEXT-PROMPT.md.
    sreg.update_session(rec["session_id"], worktree_path=str(wt))
    got = anchor.rnd_next_prompt(pid, rec["session_id"])
    assert "BUILD FROM THE PLAN SET" in got


def test_rnd_next_prompt_is_read_only(env):
    """Reading the next prompt never mutates / removes the session record."""
    anchor, sreg = env["anchor"], env["sreg"]
    proj, _folder = _mkproject(env, "ReadOnlyNP")
    pid = proj["id"]
    rec = sreg.register_session(pid, "planning", status=sreg.STATUS_RUNNING)
    sreg.update_session(rec["session_id"], pending_paste="X")
    anchor.rnd_next_prompt(pid, rec["session_id"])
    # Still present + unchanged.
    after = sreg.get_session(rec["session_id"])
    assert after is not None
    assert after.get("pending_paste") == "X"


def test_cli_next_prompt_usage_when_missing_args(env, capsys):
    anchor = env["anchor"]
    proj, _folder = _mkproject(env, "UsageNP")
    # Missing --session.
    anchor._rnd_cli(["next-prompt", proj["id"]])
    out = capsys.readouterr().out
    assert "Usage: anchor.py rnd next-prompt" in out


def test_rnd_next_prompt_unknown_project_raises_keyerror(env):
    anchor = env["anchor"]
    with pytest.raises(KeyError):
        anchor.rnd_next_prompt("deadbeef-not-real", "any-session")


def test_cli_next_prompt_unknown_project_clean(env, capsys):
    anchor = env["anchor"]
    anchor._rnd_cli(["next-prompt", "deadbeef-not-real", "--session", "s1"])
    out = capsys.readouterr().out
    assert "Unknown project" in out
