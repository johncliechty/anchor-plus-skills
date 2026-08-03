"""v11 Wave 2 — research→plan advance, the WORKTREE-ONLY live flow over HTTP.

THE user-facing fix. Clicking **Advance to Planning** on a LIVE research session
must (a) PERSIST the research session's produced docs into the MAIN project, and
(b) open the planning session with a REAL prompt naming the actual persisted doc
paths + "read these first" + load Crucible, and (c) write a HANDOFF.md + a
NEXT-PROMPT.md into the planning worktree, and (d) link the sessions.

THE v11 LESSON (non-negotiable): this test is WORKTREE-ONLY. We start a LIVE
research session and write ``research/run-1/REPORT.md`` into its WORKTREE ONLY
(NO ``eh.record_effort`` pre-persist, NO ``kill``), then POST
``/api/rnd/advance_session`` (research→plan), then assert the docs were PERSISTED
into the project AND referenced in the prompt + HANDOFF.md. A test that
pre-persists the effort (``test_advance_artifacts_v10.py:130-133`` /
``test_advance_paste_ui_v10.py:102-106``) is prompt-building coverage, NOT
live-flow coverage.

NON-VACUITY: this MUST FAIL against the pre-W2 code (the bespoke advance_session
that never persisted the live research docs → ``research_set_for_session`` returns
None → ``build_next_stage_prompt`` falls to the bare "load Crucible" fallback with
NO real path → the ``rel in pending_paste`` assertion fails AND the report never
reaches the main folder).

Hermetic: NO real claude/gemini, NO real PTY — ``ANCHOR_PTY_BACKEND=stub``, a
temp git repo for the worktree, tmp data + tmp worktree base, the server binds a
FREE port (asserted != 8777). ``ANCHOR_PROACTIVE_SUMMARY`` OFF (default) so no
live-claude summary spawn — the keystone still persists + builds. NEVER binds
``:8777`` / touches real data / network.
"""
import importlib
import json
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

FAKE = (Path(__file__).resolve().parent / "fake_claude.py").as_posix()


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


@pytest.fixture
def gui_env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", f"python {FAKE}")
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.delenv("ANCHOR_TERMINAL_SEED", raising=False)
    monkeypatch.delenv("ANCHOR_PROACTIVE_SUMMARY", raising=False)
    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "session_registry", "worktrees", "lanes", "effort_history",
                "sessions", "summarizer", "gate_adapter", "handoff",
                "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    import rnd_registry
    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    import terminal_session
    import session_registry
    import effort_history
    import handoff
    bundle = {
        "gui": gui, "ts": terminal_session, "reg": session_registry,
        "handoff": handoff, "eh": effort_history, "rnd": rnd_registry,
        "repo": repo, "pid": proj["id"],
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


@pytest.fixture
def server(gui_env):
    gui = gui_env["gui"]
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield gui_env, f"http://127.0.0.1:{port}", port
    finally:
        time.sleep(0.1)
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass
        t.join(timeout=5)


def _post(base, path, payload):
    req = urllib.request.Request(
        base + path, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def _write_in_worktree(worktree_path, rel, body="# Report\n## Findings\nOK.\n"):
    """Write a produced doc into the session's WORKTREE ONLY (no record_effort)."""
    wt = Path(worktree_path)
    p = wt / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return rel


def _committed_in_repo(repo, rel):
    return _git(repo, "ls-files", "--error-unmatch", rel).returncode == 0


# ════════════════════════════════════════════════════════════════════════════
# THE TRUTH TEST — live research session, docs in WORKTREE ONLY, over HTTP.
#   MUST FAIL pre-W2 (no persist → bare prompt, no path in pending_paste).
# ════════════════════════════════════════════════════════════════════════════

def test_advance_live_research_persists_and_primes_planning(server):
    ts, reg, repo, pid, eh = (server[0]["ts"], server[0]["reg"],
                              server[0]["repo"], server[0]["pid"],
                              server[0]["eh"])
    base = server[1]

    # A LIVE research session; write the report into its WORKTREE ONLY.
    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    rel = _write_in_worktree(rsess["worktree_path"], "research/run-1/REPORT.md")

    # Pre-condition (proves the live flow): doc lives ONLY in the worktree.
    assert not (repo / rel).is_file(), "pre-condition: doc must NOT be in main yet"
    store_lane = eh._resolve_subdir("research")
    assert eh.efforts_for_session_id(repo, pid, store_lane, rsid) == []

    status, data = _post(base, "/api/rnd/advance_session",
                         {"project_id": pid, "source_session": rsid,
                          "to_lane": "planning"})
    assert status == 200, data
    assert data.get("ok") is True, data
    new_rec = data["session"]
    new_sid = new_rec["session_id"]
    new_wt = new_rec["worktree_path"]

    # (i) the report is now PERSISTED + committed into the MAIN project.
    assert (repo / rel).is_file(), "REPORT.md was not persisted into the main project"
    assert _committed_in_repo(repo, rel), "REPORT.md was not committed to the repo"
    assert rel in (data.get("persisted") or []), data.get("persisted")

    # (ii) the new planning session's pending_paste names the real path + read-first
    #      + Crucible (NOT the bare fallback).
    prec = reg.get_session(new_sid)
    paste = prec.get("pending_paste") or ""
    assert paste, "advanced planning session has no pending paste"
    assert rel in paste, f"pending paste missing the real report path: {paste!r}"
    assert re.search(r"[Rr]ead these", paste), f"no read-first in paste: {paste!r}"
    assert "Crucible" in paste
    assert prec.get("paste_flushed") is False

    # (ii.5) THE LOAD-BEARING ON-DISK CHECK (the v11 lesson; mirrors the v8
    #        standard test_doc_persistence_v8.py:238 → assert (bwt / docs[...])
    #        .is_file() for the BUILD worktree). The research report must exist in
    #        the PLANNING CHECKOUT itself — the directory the Crucible session would
    #        OPEN it from — not merely in main. The planning worktree is created off
    #        the freshly-committed main HEAD (which the keystone just committed the
    #        report to), so the file rides into the checkout. This is a GENUINE
    #        filesystem read of the planning worktree. It would FAIL if the planning
    #        worktree were branched off a STALE ref lacking the persist commit:
    #        HANDOFF.md/the prompt would then name a path that resolves in MAIN but
    #        is ABSENT here — exactly the regression this guards (every other W2
    #        assert would still pass green while Crucible hits "file not found").
    assert (Path(new_wt) / rel).is_file(), (
        "the persisted research report is NOT present in the PLANNING worktree "
        "checkout (Crucible would hit file-not-found) — the planning worktree was "
        "likely created off a HEAD lacking the persist commit")

    # (iii) HANDOFF.md EXISTS in the planning worktree and references the real path.
    handoff_md = Path(new_wt) / "HANDOFF.md"
    assert handoff_md.is_file(), "HANDOFF.md was not written into the planning worktree"
    ho_text = handoff_md.read_text(encoding="utf-8")
    assert rel in ho_text, f"HANDOFF.md does not reference the real path: {ho_text!r}"
    assert "Crucible" in ho_text

    # (iv) NEXT-PROMPT.md exists in the planning worktree.
    next_md = Path(new_wt) / "NEXT-PROMPT.md"
    assert next_md.is_file(), "NEXT-PROMPT.md was not written"
    assert rel in next_md.read_text(encoding="utf-8")

    # (v) the sessions are linked (parent_session_id + shared chain_id).
    assert prec.get("parent_session_id") == rsid
    rrec = reg.get_session(rsid)
    assert prec.get("chain_id") == rrec.get("chain_id"), \
        "planning session did not inherit the research chain_id"

    # Also: the doc is recorded as a research effort tagged with rsid (the keystone).
    tagged = [(e.get("artifact_path") or "").replace("\\", "/")
              for e in eh.efforts_for_session_id(repo, pid, store_lane, rsid)]
    assert rel in tagged, f"no research effort tagged with rsid: {tagged}"

    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════════════
# NEGATIVE — a research session with NO docs → honest minimal prompt, no crash,
#   no fabricated path.
# ════════════════════════════════════════════════════════════════════════════

def test_advance_live_research_no_docs_is_honest(server):
    ts, reg, repo, pid = (server[0]["ts"], server[0]["reg"],
                          server[0]["repo"], server[0]["pid"])
    base = server[1]

    rsess = ts.start_session(pid, "research", backend="claude")
    rsid = rsess["session_id"]
    # Write NOTHING into the worktree.

    status, data = _post(base, "/api/rnd/advance_session",
                         {"project_id": pid, "source_session": rsid,
                          "to_lane": "planning"})
    assert status == 200, data
    assert data.get("ok") is True, data
    assert (data.get("persisted") or []) == []

    new_sid = data["session"]["session_id"]
    prec = reg.get_session(new_sid)
    paste = prec.get("pending_paste") or ""
    # Honest minimal: names Crucible, fabricates NO research/.../REPORT.md path.
    assert "Crucible" in paste
    assert not re.search(r"research/\S+\.md", paste), \
        f"fabricated research doc path in honest-empty paste: {paste!r}"
    # Still linked.
    assert prec.get("parent_session_id") == rsid

    for r in reg.list_sessions(project_id=pid):
        try:
            ts.kill(r["session_id"])
        except Exception:
            pass


# ════════════════════════════════════════════════════════════════════════════
# HONESTY GUARD — an UNRESOLVABLE source session (bogus id) → honest error, NO
#   orphan planning session minted. prepare_stage_handoff returns ok=False (no
#   record), so the handler must NOT start a planning session with an empty paste.
# ════════════════════════════════════════════════════════════════════════════

def test_advance_unresolvable_source_returns_error_no_orphan(server):
    reg, pid = server[0]["reg"], server[0]["pid"]
    base = server[1]

    before = {r["session_id"] for r in reg.list_sessions(project_id=pid)}

    # The handler returns HTTP 400 (urllib raises HTTPError on 4xx) — read the
    # body off the error so we can assert on the honest JSON.
    try:
        status, data = _post(base, "/api/rnd/advance_session",
                             {"project_id": pid,
                              "source_session": "does-not-exist",
                              "to_lane": "planning"})
    except urllib.error.HTTPError as exc:
        status = exc.code
        data = json.loads(exc.read().decode("utf-8"))
    # Honest error — NOT a 200/ok with an orphan session.
    assert status == 400, (status, data)
    assert data.get("ok") is False, data
    assert "session" in (data.get("error") or "").lower(), data
    assert "session" not in data, "an orphan planning session was returned"

    # No NEW session was minted (the registry is unchanged).
    after = {r["session_id"] for r in reg.list_sessions(project_id=pid)}
    assert after == before, f"an orphan session was created: {after - before}"


# ════════════════════════════════════════════════════════════════════════════
# (UI) NON-Playwright rendered-DOM leg — the advance affordance + pending-paste
#   hint render POSITIVELY; the advance JS does NOT auto-submit (NEGATIVE).
#   The W2 fix is server-side wiring; this asserts the unchanged UI contract
#   stands so the paste-NOT-submit semantics still hold over the new flow.
# ════════════════════════════════════════════════════════════════════════════

def test_render_advance_affordance_and_unsent_hint(gui_env):
    gui, pid = gui_env["gui"], gui_env["pid"]
    html = gui.render_project_window_html(pid)
    # Isolate the project-window JS for the negative leg.
    import re as _re
    js = "".join(_re.findall(r"<script>([\s\S]*?)</script>", html))

    # POSITIVE — the advance control + pending-paste hint render.
    assert ".pendpaste-hint" in html, "pending-paste hint CSS class missing"
    assert "Advance to Planning" in js, "research advance control missing"
    assert "advbtn" in js
    assert "function _flashPendingPasteHint(" in js, "hint helper missing"

    # NEGATIVE — the hint advertises UNSENT and the advance JS does NOT auto-submit
    # the paste (no term_input write in advanceSession's body).
    assert _re.search(r"review\s*&\s*press\s*Enter", js, _re.I), \
        "hint must tell the user to review & press Enter (unsent)"
    assert _re.search(r"nothing was submitted", js, _re.I), \
        "hint must state nothing was submitted on the user's behalf"
    fm = _re.search(r"async function advanceSession\(([\s\S]*?)\n\}", js)
    assert fm, "advanceSession not found in rendered JS"
    body = fm.group(1)
    assert "term_input" not in body, \
        "advance must NOT auto-submit the prompt via term_input (it is a paste)"
