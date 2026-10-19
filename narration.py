"""Deterministic narration floor + Layer-1 warm view data (telemetry-resume W3).

The narration FLOOR that makes 'clicking ANY session tile reliably opens a warm
terminal that narrates' true on day one — with **zero PTY, zero synchronous model
calls, zero network**. Cites the North Star amendment
(``planning/telemetry-resume-2026-07/NORTH-STAR-AMENDMENT.md``): the click
contract, the first-click sentence, the click-path ruling, the narration floor +
three-way evaluation, and the endpoint auth rule.

Two layers:

  * :func:`build_narration` — the PURE, TOTAL, never-raises deterministic template
    over registry facts + doc-roles + a durable next-step artifact. It is total
    over EVERY record class (running, done, failed, parked-idle, evicted-parked,
    reaped-orphan, cancelled, general, discovered/brownfield, finished one-shot
    job) and cannot render blank: its floor is 'ran <skill/lane> in <lane>
    (<dates>, <status>); produced: <doc-role links | no recoverable documents>;
    next: <NEXT-PROMPT.md / pending_paste (paste-NOT-submit) / stage-derived>'.
    It performs NO I/O — the caller feeds it the already-resolved doc-roles,
    cached summary, and next-step string.

  * :func:`narrate_session` / :func:`narrate_effort` — thin orchestrators that
    gather those inputs through the EXISTING read-only accessors
    (``summarizer.session_doc_roles`` / ``summarizer.load_cached`` /
    ``handoff``) and call :func:`build_narration`. Read-only, cache-only — they
    NEVER run the model, spawn a PTY, or touch the network.

Lazy enrichment (the narration-floor lock, CHOSEN middle path): the FLOOR renders
immediately; when a cached summary exists it replaces the 'what was done' line
(``enrichment='cached'``); a summary-less tile is served the floor with an
``enrichment='generating'`` badge while the EXISTING background summary path runs
(the route triggers it — this module never does); a failed generation leaves the
floor standing (``enrichment='floor'``). No batch backfill, ever.

Stdlib only (no third-party imports); :func:`build_narration` imports nothing at
call time so the property test can exercise it over captured registry-state
fixtures with no live registry.
"""
from __future__ import annotations

import time
from urllib.parse import quote as _q

# ── Tile classes (TOTAL — every record maps to exactly one) ──────────────────
CLASS_RUNNING = "running"
CLASS_DONE = "done"
CLASS_FAILED = "failed"
CLASS_PARKED_IDLE = "parked-idle"
CLASS_EVICTED_PARKED = "evicted-parked"
CLASS_REAPED_ORPHAN = "reaped-orphan"
CLASS_CANCELLED = "cancelled"
CLASS_GENERAL = "general"
CLASS_DISCOVERED = "discovered"
CLASS_ONE_SHOT_JOB = "one-shot-job"

#: Every tile class the template is TOTAL over.
TILE_CLASSES = (
    CLASS_RUNNING, CLASS_DONE, CLASS_FAILED, CLASS_PARKED_IDLE,
    CLASS_EVICTED_PARKED, CLASS_REAPED_ORPHAN, CLASS_CANCELLED,
    CLASS_GENERAL, CLASS_DISCOVERED, CLASS_ONE_SHOT_JOB,
)

# ── Enrichment states (the lazy narration-floor lock) ────────────────────────
ENRICH_CACHED = "cached"        # a validated summary exists → enriched 'done' line
ENRICH_GENERATING = "generating"  # summary-less; background gen in flight → badge
ENRICH_FLOOR = "floor"          # summary-less; deterministic floor only
ENRICH_FAILED = "failed"        # a prior generation failed; floor stands, no loop

#: The honest interim badge (a badge OVER content, never a spinner instead of it).
GENERATING_BADGE = "summary generating…"
#: The evicted-parked class badge (worktree reaped; renders from main-persisted docs).
EVICTED_BADGE = "evicted"

# ── Status strings (mirror session_registry; hardcoded to keep this module pure) ─
_ST_RUNNING = "running"
_ST_DONE = "done"
_ST_FAILED = "failed"
_ST_IDLE = "idle"
_ST_CANCELLED = "cancelled"
_ST_PARKED_WARM = "parked-warm"
_ST_REAPED_ORPHAN = "reaped-orphan"
_ST_NEEDS_ATTENTION = "needs-attention"

#: Non-running statuses that KEEP a worktree when one is present (parked WARM).
_PARKED_STATUSES = frozenset((_ST_PARKED_WARM, _ST_IDLE))

#: Lane → the trio skill it runs (research→researchPrime, plan→Crucible,
#: build→Foreman). Mirrors ``lanes`` SKILL_* constants. ``general`` has no skill.
_LANE_SKILL = {
    "research": "researchPrime",
    "plan": "crucible",
    "planning": "crucible",
    "build": "foreman",
}

#: Scrubbed-fixture / empty sentinels for worktree_path (an evicted worktree is "").
_EMPTY_WORKTREE = ("", None)


def _is_reaped_worktree(subject) -> bool:
    """True iff the record's managed worktree has been reaped (empty path).

    An evicted-parked tile carries ``worktree_path == ''`` (the worktree was
    reclaimed; the docs were persisted to main). A retained parked tile carries a
    real path. The anonymized fixtures use ``''`` for reaped and a
    ``<scrubbed-worktree>/…`` placeholder for retained, so a non-empty value —
    scrubbed or real — reads as retained.
    """
    wt = subject.get("worktree_path")
    if wt in _EMPTY_WORKTREE:
        return True
    return not str(wt).strip()


def classify_tile(subject, is_effort: bool = False) -> str:
    """Map a session/effort record to exactly ONE tile class (TOTAL, never raises).

    ``is_effort`` → a finished one-shot job (durable ``job_runner`` effort with a
    cost block, no PTY record). Otherwise classified by status, with the
    parked-warm/idle split keyed on worktree retention: a reaped worktree is
    EVICTED-parked (renders from main-persisted docs), a retained one is
    parked-idle. An unrecognized status falls through to ``done`` (never blank).
    """
    if not isinstance(subject, dict):
        return CLASS_DONE
    if is_effort:
        return CLASS_ONE_SHOT_JOB
    status = (subject.get("status") or "").strip()
    lane = (subject.get("lane") or "").strip().lower()
    if status == _ST_RUNNING or status == _ST_NEEDS_ATTENTION:
        return CLASS_RUNNING
    if status == _ST_FAILED:
        return CLASS_FAILED
    if status in _PARKED_STATUSES:
        return (CLASS_EVICTED_PARKED if _is_reaped_worktree(subject)
                else CLASS_PARKED_IDLE)
    if status == _ST_REAPED_ORPHAN:
        return CLASS_REAPED_ORPHAN
    if status == _ST_CANCELLED:
        return CLASS_CANCELLED
    # Discovered/brownfield records carry a provenance marker and no live status.
    prov = (subject.get("provenance") or subject.get("source") or "").strip()
    if prov == "discovered" and status != _ST_DONE:
        return CLASS_DISCOVERED
    if status == _ST_DONE and lane == "general":
        return CLASS_GENERAL
    # Done, or anything unrecognized → done (the total, never-blank fallback).
    return CLASS_DONE


def _fmt_date(ts) -> str:
    """Format an epoch timestamp to ``YYYY-MM-DD`` (UTC, deterministic), or ''."""
    try:
        t = float(ts)
    except (TypeError, ValueError):
        return ""
    if t <= 0:
        return ""
    try:
        return time.strftime("%Y-%m-%d", time.gmtime(t))
    except (ValueError, OSError):
        return ""


def _href_valid(href) -> bool:
    """A produced/link href is valid iff it uses an EXISTING doc route."""
    h = str(href or "")
    return h.startswith("/report/") or h.startswith("/artifact/")


def _report_href(project_id, lane, job_id) -> str:
    """``/report/<pid>/<lane>/<job_id>`` — the existing run-report route."""
    return (f"/report/{_q(str(project_id), safe='')}/"
            f"{_q(str(lane), safe='')}/{_q(str(job_id), safe='')}")


def _skill_for(lane: str) -> str:
    return _LANE_SKILL.get((lane or "").strip().lower(), "")


def _floor_done(subject, is_effort: bool) -> str:
    """The deterministic 'what was done' floor line (never empty).

    'ran <skill|lane> in <lane> (<date>, <status>)'. Falls back to 'ran session'
    when a record carries neither lane nor skill — the template can never be blank.
    """
    lane = (subject.get("lane") or "").strip()
    skill = _skill_for(lane)
    status = (subject.get("status") or "").strip()
    if not status and is_effort:
        status = _ST_DONE
    date = _fmt_date(subject.get("created_at"))
    who = skill or lane or "session"
    seg = f"ran {who}"
    if lane and who != lane:
        seg += f" in {lane}"
    meta = [m for m in (date, status) if m]
    if meta:
        seg += " (" + ", ".join(meta) + ")"
    return seg


def _enriched_done(cached) -> str:
    """The 'what was done' line from a cached summary, or '' (mirror session_blurb).

    Prefers the first grounded claim, then ``what_was_asked``, then ``title``.
    Never fabricates — returns '' when the cache carries no usable short text.
    """
    if not isinstance(cached, dict):
        return ""
    for c in (cached.get("claims") or []):
        if c and str(c).strip():
            return str(c).strip()
    for key in ("what_was_asked", "title"):
        v = (cached.get(key) or "").strip()
        if v:
            return v
    return ""


def _produced(subject, doc_roles, cached, is_effort, project_id) -> list:
    """Link-valid list of produced docs: ``[{role, label, href}]`` (may be empty).

    Sources, in order, deduped by href: a finished one-shot job's own /report
    link; the per-role doc-role links (``summarizer.session_doc_roles`` shape:
    ``{role: {label, href}}``); the cached summary's member_links. Every href
    uses an EXISTING route (/report or /artifact); an invalid href is dropped
    (never surfaced) so :func:`build_narration` stays link-valid by construction.
    """
    out = []
    seen = set()

    def _add(role, label, href):
        h = str(href or "")
        if not _href_valid(h) or h in seen:
            return
        seen.add(h)
        out.append({"role": role or "", "label": str(label or h), "href": h})

    if is_effort:
        jid = (subject.get("job_id") or subject.get("session_id") or "").strip()
        lane = (subject.get("lane") or "").strip()
        if jid and lane:
            _add("report", subject.get("skill") or jid,
                 _report_href(project_id, lane, jid))

    if isinstance(doc_roles, dict):
        for role, info in doc_roles.items():
            if not isinstance(info, dict):
                continue
            _add(role, info.get("label") or role, info.get("href"))

    if isinstance(cached, dict):
        for lk in (cached.get("member_links") or []):
            if isinstance(lk, dict):
                _add("", lk.get("label"), lk.get("href"))

    return out


def _next_step(subject, next_step, is_effort) -> dict:
    """The 'next' spine element — ALWAYS a dict, ALWAYS ``submit=False``.

    Resolution order (paste-NOT-submit throughout):
      1. an unflushed ``pending_paste`` on the record (the exact unsent prompt);
      2. a durable next-step string the caller resolved (NEXT-PROMPT.md / rebuild);
      3. a deterministic stage-derived next step from the lane/status.
    ``submit`` is ALWAYS ``False`` — nothing is ever auto-submitted on the user's
    behalf (the v10 paste-NOT-submit contract; a test pins this).
    """
    pending = (subject.get("pending_paste") or "").strip()
    flushed = bool(subject.get("paste_flushed"))
    if pending and not flushed:
        return {"text": pending, "source": "pending_paste", "submit": False}
    durable = (next_step or "").strip() if isinstance(next_step, str) else ""
    if durable:
        return {"text": durable, "source": "next_prompt", "submit": False}
    lane = (subject.get("lane") or "").strip().lower()
    status = (subject.get("status") or "").strip()
    if status == _ST_RUNNING:
        text = ("This session is live — click ▶ Resume live to "
                "continue it.")
    elif lane == "research":
        text = "Advance to planning to turn this research into a plan."
    elif lane in ("plan", "planning"):
        text = "Advance to build to execute this plan."
    elif lane == "build":
        text = "Review the produced deliverable and execution log."
    else:
        text = "Resume this session to continue where it left off."
    return {"text": text, "source": "stage_derived", "submit": False}


def build_narration(subject, *, doc_roles=None, cached_summary=None,
                    next_step=None, enrichment=None, project_id="",
                    is_effort=False) -> dict:
    """The PURE, TOTAL, never-raises deterministic narration over ONE record.

    ``subject`` is a session-registry record dict OR a one-shot-job effort dict
    (``is_effort=True``). All inputs are pre-resolved by the caller — this
    function does NO I/O (no model, no PTY, no network, no filesystem), so a
    fixture record with no live registry still narrates from its own facts.

    Returns a JSON-safe dict with the narration spine:
      ``session_id``, ``tile_class``, ``lane``, ``title``, ``done`` (the
      what-was-done line — enriched from cache when present, else the floor),
      ``produced`` (link-valid ``[{role,label,href}]``), ``produced_note`` ('' or
      'no recoverable documents'), ``next`` ({text, source, submit:False}),
      ``badges`` (['evicted'] / ['summary generating…'] …), ``enrichment``
      (cached|generating|floor|failed), and ``links_valid`` (True by construction).

    The 'done' line is NEVER blank and ``next`` is NEVER None — the template is
    total, so Layer 1 is structurally-never-blank for every tile class.
    """
    subject = subject if isinstance(subject, dict) else {}
    doc_roles = doc_roles if isinstance(doc_roles, dict) else {}
    cached = (cached_summary
              if isinstance(cached_summary, dict) and not cached_summary.get("error")
              else None)
    tile_class = classify_tile(subject, is_effort=is_effort)
    lane = (subject.get("lane") or "").strip()
    sid = (subject.get("session_id") or subject.get("job_id") or "").strip()
    skill = _skill_for(lane)
    title = (f"{lane} · {skill}" if skill else (lane or "session"))

    if cached is not None:
        # A cached summary exists → it REPLACES the floor's 'what was done' line.
        # ``enrichment`` is 'cached' regardless of any passed hint (a live cache
        # is never 'generating').
        done = _enriched_done(cached) or _floor_done(subject, is_effort)
        enrich = ENRICH_CACHED
    else:
        done = _floor_done(subject, is_effort)
        # Summary-less: the caller decides 'generating' (background gen in flight)
        # vs 'floor'/'failed'; default to the plain floor.
        enrich = enrichment if enrichment in (
            ENRICH_GENERATING, ENRICH_FLOOR, ENRICH_FAILED) else ENRICH_FLOOR

    produced = _produced(subject, doc_roles, cached, is_effort, project_id)
    nxt = _next_step(subject, next_step, is_effort)

    badges = []
    if tile_class == CLASS_EVICTED_PARKED:
        badges.append(EVICTED_BADGE)
    if enrich == ENRICH_GENERATING:
        badges.append(GENERATING_BADGE)

    links_valid = (all(_href_valid(p.get("href")) for p in produced)
                   and nxt.get("submit") is False)

    return {
        "session_id": sid,
        "tile_class": tile_class,
        "lane": lane,
        "title": title,
        "done": done,
        "produced": produced,
        "produced_note": "" if produced else "no recoverable documents",
        "next": nxt,
        "badges": badges,
        "enrichment": enrich,
        "links_valid": bool(links_valid),
    }


# ── Orchestrators (read-only I/O → build_narration) ──────────────────────────

def _resolve_folder(project_id, folder_path):
    if folder_path is not None:
        return folder_path
    try:
        import rnd_registry as _rnd
        return (_rnd.get_project(project_id) or {}).get("folder_path", "")
    except Exception:
        return ""


def _resolve_next_prompt(folder_path, project_id, record) -> str:
    """The durable next-step prompt for a session (NEXT-PROMPT.md / rebuild), or ''.

    Read-only; NEVER starts a session or runs a model. Mirrors
    ``anchor.rnd_next_prompt`` step 2/3 (step 1, ``pending_paste``, is handled
    purely inside :func:`build_narration`). Best-effort — any failure yields ''.
    """
    if not isinstance(record, dict):
        return ""
    try:
        wt = (record.get("worktree_path") or "").strip()
        if wt:
            import handoff as _h
            from pathlib import Path
            np = Path(wt) / _h.NEXT_PROMPT_FILENAME
            if np.is_file():
                body = np.read_text(encoding="utf-8")
                if body.strip():
                    return body.rstrip("\r\n")
    except Exception:
        pass
    try:
        parent = (record.get("parent_session_id") or "").strip()
        if parent:
            import handoff as _h
            text = _h.build_next_stage_prompt(
                folder_path, project_id, parent, record.get("lane") or "")
            if text and text.strip():
                return text.rstrip("\r\n")
    except Exception:
        pass
    return ""


def narrate_session(project_id, lane, session_id, *, folder_path=None,
                    record=None, enrichment=None) -> dict:
    """Layer-1 narration for a managed/registry session (read-only, cache-only).

    Gathers doc-roles + the cached summary + the durable next-step through the
    EXISTING read-only accessors and calls :func:`build_narration`. NEVER runs the
    model, spawns a PTY, or touches the network. ``enrichment`` (e.g.
    ``ENRICH_GENERATING`` when the caller just triggered background generation) is
    forwarded; a live cache always wins ('cached'). Never raises.
    """
    import summarizer as _s
    import effort_history as _eh
    folder_path = _resolve_folder(project_id, folder_path)
    if record is None:
        try:
            import session_registry as _sr
            record = _sr.get_session(session_id) or {}
        except Exception:
            record = {}
    if not isinstance(record, dict):
        record = {}
    # The registry record may omit lane; prefer the passed lane, else the record's.
    if not record.get("lane") and lane:
        record = dict(record)
        record["lane"] = lane
    store_lane = lane
    try:
        store_lane = _eh._resolve_subdir(lane) if lane else lane
    except Exception:
        store_lane = lane
    try:
        roles = _s.session_doc_roles(project_id, store_lane or lane, session_id,
                                     folder_path=folder_path)
    except Exception:
        roles = {}
    try:
        cached = _s.load_cached(folder_path, project_id, store_lane or lane,
                                session_id)
    except Exception:
        cached = None
    next_step = _resolve_next_prompt(folder_path, project_id, record)
    return build_narration(record, doc_roles=roles, cached_summary=cached,
                           next_step=next_step, enrichment=enrichment,
                           project_id=project_id)


def narrate_effort(project_id, lane, effort, *, folder_path=None) -> dict:
    """Layer-1 narration for a finished one-shot job (durable effort record).

    A one-shot job has no PTY/registry record: Layer 1 renders the effort record
    + its /report link. Read-only; never raises.
    """
    subject = dict(effort) if isinstance(effort, dict) else {}
    subject.setdefault("lane", lane)
    subject.setdefault("status", _ST_DONE)
    return build_narration(subject, is_effort=True, project_id=project_id)


# ── Two-number coverage report (W3 done-when: template coverage MUST be 100%) ─

def coverage_report(sessions, efforts=None, *, project_id="",
                    enrichment_lookup=None) -> dict:
    """The honest TWO-number narration coverage report over a set of records.

    * ``template_coverage`` — the fraction of records for which the deterministic
      template yields a non-empty, link-valid narrated view. Because the template
      is TOTAL, this MUST be 1.0 (the W3 done-when); a value < 1.0 is a real bug.
    * ``enrichment_coverage`` — the fraction whose 'what was done' line is served
      from a cached model summary (the rest render the honest floor). This is an
      environment fact, reported as-is (never inflated).

    ``sessions`` is an iterable of registry record dicts; ``efforts`` an iterable
    of finished one-shot-job effort dicts. ``enrichment_lookup`` (optional) maps a
    record → an enrichment hint / cached summary; unused for the pure fixture run
    (cache resolution happens in the live tool). Never raises.
    """
    efforts = list(efforts or [])
    total = 0
    template_ok = 0
    enriched = 0
    per_class = {}

    def _tally(view):
        nonlocal total, template_ok, enriched
        total += 1
        ok = bool(view.get("done")) and bool(view.get("links_valid"))
        if ok:
            template_ok += 1
        if view.get("enrichment") == ENRICH_CACHED:
            enriched += 1
        cls = view.get("tile_class", "?")
        per_class[cls] = per_class.get(cls, 0) + 1

    for rec in (sessions or []):
        if not isinstance(rec, dict):
            continue
        cached = None
        if callable(enrichment_lookup):
            try:
                cached = enrichment_lookup(rec)
            except Exception:
                cached = None
        _tally(build_narration(rec, cached_summary=cached,
                               project_id=project_id))
    for eff in efforts:
        if not isinstance(eff, dict):
            continue
        _tally(build_narration(dict(eff), is_effort=True,
                               project_id=project_id))

    return {
        "template_total": total,
        "template_covered": template_ok,
        "template_coverage": (template_ok / total) if total else 1.0,
        "enrichment_covered": enriched,
        "enrichment_coverage": (enriched / total) if total else 0.0,
        "per_class": per_class,
    }
