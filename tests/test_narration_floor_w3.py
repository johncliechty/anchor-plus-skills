"""Deterministic narration FLOOR + Layer-1 warm view — telemetry-resume W3.

Cites the North Star amendment (``planning/telemetry-resume-2026-07/
NORTH-STAR-AMENDMENT.md``): the click contract, the first-click sentence, the
narration floor + three-way evaluation. This suite pins the W3 done-when:

  * the deterministic template is TOTAL and link-valid for EVERY session in the
    captured registry-state fixture AND for the finished one-shot job (the
    property test);
  * the two-number coverage report over the real captured fixture shows template
    coverage = 100%;
  * lazy enrichment: a cached summary replaces the 'what was done' line; a
    summary-less tile renders the floor + a 'summary generating…' badge (a badge
    OVER content); a failed generation leaves the floor standing (no loop);
  * per tile-class render definitions incl. evicted-parked ('evicted' badge, from
    main-persisted docs) and the finished one-shot job (effort + /report link);
  * paste-NOT-submit: the 'next' element is NEVER auto-submitted;
  * Layer 1 is a PURE render — build_narration performs NO model / PTY / network
    / filesystem I/O (structurally-never-blank in <200ms);
  * the client Layer-1 view + '▶ Resume live' control + reuse-not-sibling are
    wired in the session-window terminal chrome.

Pure-Python + deterministic; runs in the standard ``pytest tests/ -v`` gate with
NO skip/xfail. Never touches the live :8777 service or the real ~/.anchor store.
"""
import inspect
import json
import time
from pathlib import Path

import narration

REPO = Path(__file__).resolve().parent.parent
FIX = Path(__file__).resolve().parent / "fixtures" / "registry_state"
JS = (REPO / "static" / "project-window.js").read_text(encoding="utf-8")


def _load_sessions():
    return json.loads((FIX / "sessions.json").read_text(encoding="utf-8"))


def _load_efforts():
    data = json.loads((FIX / "efforts" / "proj-0000_build.json").read_text(
        encoding="utf-8"))
    return data.get("efforts", [])


def _href_ok(href):
    h = str(href or "")
    return h.startswith("/report/") or h.startswith("/artifact/")


# ── The property test: TOTAL + link-valid over every captured record ─────────
def test_template_total_and_link_valid_for_every_session():
    """Every session record in the captured fixture renders a non-empty,
    link-valid Layer-1 narrated view — the template is TOTAL (never blank)."""
    sessions = _load_sessions()
    assert sessions, "fixture must carry session records"
    for sid, rec in sessions.items():
        view = narration.build_narration(rec, project_id="proj-0000")
        # non-empty narration spine
        assert view["done"], f"{sid}: 'what was done' must never be blank"
        assert view["tile_class"] in narration.TILE_CLASSES, sid
        # 'next' is always present and NEVER auto-submitted
        assert isinstance(view["next"], dict), sid
        assert view["next"]["submit"] is False, sid
        # every produced link uses an existing route
        for p in view["produced"]:
            assert _href_ok(p["href"]), f"{sid}: bad produced href {p['href']!r}"
        assert view["links_valid"] is True, sid
        # no docs in the bare fixture → the honest 'no recoverable documents'
        if not view["produced"]:
            assert view["produced_note"] == "no recoverable documents", sid


def test_finished_one_shot_job_narrates_with_report_link():
    """The finished one-shot job (no PTY record) renders the effort + a /report
    link — the locked one-shot-job tile-class definition."""
    efforts = _load_efforts()
    assert efforts, "fixture must carry the one-shot job effort"
    eff = efforts[0]
    view = narration.narrate_effort("proj-0000", "build", eff)
    assert view["tile_class"] == narration.CLASS_ONE_SHOT_JOB
    assert view["done"]
    hrefs = [p["href"] for p in view["produced"]]
    assert any(h.startswith("/report/proj-0000/build/") for h in hrefs), hrefs
    assert view["links_valid"] is True


# ── Tile-class render definitions ────────────────────────────────────────────
def test_tile_classes_match_the_captured_manifest():
    s = _load_sessions()
    C = narration
    assert C.classify_tile(s["sess-0001"]) == C.CLASS_RUNNING
    assert C.classify_tile(s["sess-0002"]) == C.CLASS_DONE
    # evicted-parked: parked-warm with a REAPED (empty) worktree.
    assert C.classify_tile(s["sess-0003"]) == C.CLASS_EVICTED_PARKED
    assert C.classify_tile(s["sess-0004"]) == C.CLASS_FAILED
    # parked-idle: parked-warm WITH a retained worktree (distinct from evicted).
    assert C.classify_tile(s["sess-0005"]) == C.CLASS_PARKED_IDLE
    assert C.classify_tile(s["sess-0006"]) == C.CLASS_REAPED_ORPHAN
    assert C.classify_tile(s["sess-0007"]) == C.CLASS_GENERAL


def test_evicted_parked_carries_evicted_badge():
    """An evicted-parked tile renders an explicit 'evicted' badge (locked
    evicted-tile sub-contract — renders from main-persisted docs)."""
    s = _load_sessions()
    view = narration.build_narration(s["sess-0003"], project_id="proj-0000")
    assert view["tile_class"] == narration.CLASS_EVICTED_PARKED
    assert narration.EVICTED_BADGE in view["badges"]


# ── Lazy enrichment (the narration-floor lock) ───────────────────────────────
def test_cached_summary_replaces_the_done_line():
    s = _load_sessions()
    cached = {"claims": ["Migrated the C2 route table cleanly"],
              "schema_version": 1}
    view = narration.build_narration(s["sess-0002"], project_id="proj-0000",
                                     cached_summary=cached)
    assert view["enrichment"] == narration.ENRICH_CACHED
    assert view["done"] == "Migrated the C2 route table cleanly"
    assert narration.GENERATING_BADGE not in view["badges"]


def test_live_cache_wins_over_a_generating_hint():
    """A live cache is never 'generating' even if the caller passes the hint."""
    s = _load_sessions()
    cached = {"what_was_asked": "plan the telemetry work", "schema_version": 1}
    view = narration.build_narration(
        s["sess-0002"], project_id="proj-0000", cached_summary=cached,
        enrichment=narration.ENRICH_GENERATING)
    assert view["enrichment"] == narration.ENRICH_CACHED
    assert narration.GENERATING_BADGE not in view["badges"]


def test_summary_less_generating_shows_badge_over_floor():
    s = _load_sessions()
    view = narration.build_narration(
        s["sess-0002"], project_id="proj-0000",
        enrichment=narration.ENRICH_GENERATING)
    assert view["enrichment"] == narration.ENRICH_GENERATING
    assert narration.GENERATING_BADGE in view["badges"]
    # The floor 'what was done' still renders UNDER the badge (never a spinner
    # instead of content).
    assert view["done"]
    assert "crucible" in view["done"] or "planning" in view["done"]


def test_failed_generation_leaves_the_floor_standing():
    s = _load_sessions()
    view = narration.build_narration(
        s["sess-0002"], project_id="proj-0000",
        enrichment=narration.ENRICH_FAILED)
    assert view["enrichment"] == narration.ENRICH_FAILED
    assert narration.GENERATING_BADGE not in view["badges"]
    assert view["done"]  # floor stands — never blank


# ── Paste-NOT-submit (v10 contract; a test pins no auto-submit) ──────────────
def test_pending_paste_is_the_next_step_and_never_submitted():
    rec = {"session_id": "x", "lane": "build", "status": "parked-warm",
           "worktree_path": "wt/x", "pending_paste": "load Foreman and continue",
           "paste_flushed": False}
    view = narration.build_narration(rec, project_id="proj-0000")
    assert view["next"]["source"] == "pending_paste"
    assert view["next"]["text"] == "load Foreman and continue"
    assert view["next"]["submit"] is False


def test_flushed_paste_is_not_resurfaced_as_next():
    rec = {"session_id": "x", "lane": "research", "status": "done",
           "pending_paste": "already sent", "paste_flushed": True}
    view = narration.build_narration(rec, project_id="proj-0000")
    assert view["next"]["source"] != "pending_paste"
    assert view["next"]["submit"] is False


def test_no_narration_ever_auto_submits():
    """Across every fixture record, the 'next' element is paste-NOT-submit."""
    for rec in _load_sessions().values():
        view = narration.build_narration(rec, project_id="proj-0000")
        assert view["next"]["submit"] is False


# ── Coverage report: template coverage MUST be 100% ──────────────────────────
def test_coverage_report_template_is_100_percent():
    sessions = list(_load_sessions().values())
    efforts = _load_efforts()
    rep = narration.coverage_report(sessions, efforts, project_id="proj-0000")
    assert rep["template_total"] == len(sessions) + len(efforts)
    assert rep["template_covered"] == rep["template_total"]
    assert rep["template_coverage"] == 1.0
    # enrichment coverage is honest (0.0 here — the bare fixture has no caches).
    assert rep["enrichment_coverage"] == 0.0


def test_coverage_report_counts_enrichment_when_cached():
    sessions = list(_load_sessions().values())

    def _lookup(rec):
        if rec.get("session_id") == "sess-0002":
            return {"claims": ["did the thing"], "schema_version": 1}
        return None

    rep = narration.coverage_report(sessions, [], project_id="proj-0000",
                                    enrichment_lookup=_lookup)
    assert rep["template_coverage"] == 1.0
    assert rep["enrichment_covered"] == 1


# ── Layer 1 is a PURE render: NO model / PTY / network / filesystem I/O ───────
def test_build_narration_is_pure_no_io():
    """The floor render imports nothing and calls no model/PTY/network/fs — so a
    click can never spawn a PTY, run a model synchronously, or hit the network."""
    src = inspect.getsource(narration.build_narration)
    for forbidden in ("import ", "subprocess", "socket", "urlopen", "requests",
                      "read_since", "pty_manager", "job_runner", "open("):
        assert forbidden not in src, f"build_narration must not use {forbidden!r}"


def test_layer1_render_is_fast_under_200ms_budget():
    """Rendering every fixture record's Layer-1 view is well under the <200ms
    per-click budget (pure Python, no I/O)."""
    sessions = list(_load_sessions().values())
    t0 = time.perf_counter()
    for _ in range(50):
        for rec in sessions:
            narration.build_narration(rec, project_id="proj-0000")
    elapsed = time.perf_counter() - t0
    # 50 * 7 = 350 renders; a single render is the click budget and must be tiny.
    assert (elapsed / 350.0) < 0.2


# ── Client Layer-1 wiring (source inspection; Playwright sign-off is W6) ──────
def test_client_renders_layer1_in_terminal_chrome():
    assert "_mountLayer1Narration" in JS
    assert "/api/rnd/session_narration" in JS
    # The '▶ Resume live' escalation control is rendered (fully wired in W6).
    assert "resume-live" in JS
    assert "_resumeLive" in JS


def test_client_next_is_paste_not_submit():
    """The client renders the 'next' block as paste-NOT-submit (data-submit)."""
    assert 'data-submit="false"' in JS


def test_client_reuse_not_sibling_focuses_existing_live_session():
    """A '▶ Resume live' on an effort with an already-live session focuses that
    window instead of spawning a sibling (reuse-not-sibling)."""
    assert "_RESUMED_FROM" in JS
    assert "_RESUMED_FROM[sessionId] = sid" in JS
    # _resumeLive focuses an already-live session/dock rather than spawning.
    assert "function _resumeLive(sessionId, lane)" in JS
