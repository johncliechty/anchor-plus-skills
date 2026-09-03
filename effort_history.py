#!/usr/bin/env python3
"""Anchor effort history + cost rollup + per-effort auto-commit (Wave 7).

An *effort* is one research/plan/build run for a project lane. Wave 6 records a
launch pointer-record per lane dir; Wave 7 turns efforts into **job-id-scoped
pointer-records** so a lane accumulates a *versioned history* (D5 — iterative,
nothing lost): re-running a lane appends a new effort record and NEVER deletes a
prior one. History reads return records **NEWEST-FIRST** (index 0 = most recent;
"current on top" — C5).

Storage layout (under the per-project store from ``rnd_registry``):

    <folder>/.anchor/projects/<id>/<lane-subdir>/
        efforts/
            <job_id>.pointer.json     ← one pointer-record per effort
        index.json                    ← ordered list of job_ids (append-only)

The pointer-record is a small JSON dict carrying the effort's identity, its
artifact filenames (``report.md`` / ``report.pdf`` when present), and — once the
job completes — the cost/usage/duration captured from the job's stream-json
``result`` envelope (``total_cost_usd`` / tokens / ``duration_ms``).

Cost rolls up: per-effort → per-lane → per-project (C — the tile + dashboard
rollup).

C9 backup: when an effort is *finalized*, its ``.anchor/`` pointer-record is
**auto-committed** (one commit per effort) in the PROJECT'S OWN folder repo,
reconciled with the ``.gitignore`` tracking policy (track small pointer-records;
ignore raw logs / PDFs / jobs). The commit is scoped strictly to the project's
folder path — NEVER the Anchor repo itself.

All writes run under ``paths.WRITE_LOCK``. Stdlib only (``git`` invoked as a
subprocess is allowed; it is a system tool, not a Python dependency).
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path, PurePosixPath

import paths as _paths
import rnd_registry as _rnd
import journal as _journal

#: Marker on a pointer-record that was DISCOVERED from a pre-existing on-disk
#: artifact (brownfield), as opposed to an Anchor-RUN effort. Discovered records
#: carry real metadata only (rel path, mtime->created_at, title, kind) and NEVER
#: fabricated cost/tokens/session_id. They are derived (reconcilable): a rescan
#: PRUNES a discovered record whose artifact no longer exists on disk.
SOURCE_DISCOVERED = "discovered"
SOURCE_RUN = "run"

#: job_id prefix for discovered records (a stable, content-addressed hash of the
#: artifact's lane + relative path, so rescans are idempotent — no duplicates).
DISCOVERED_PREFIX = "disc-"

# Map the trio lane names → the per-project store subdir they write into. This
# mirrors ``lanes.LaneDef.output_subdir`` but is kept here so effort_history has
# no import dependency on the lanes module (which imports job_runner). Both the
# trio lane name ("plan") and the store subdir name ("planning") are accepted.
LANE_SUBDIR = {
    "research": "research",
    "plan": "planning",
    "planning": "planning",
    "build": "build",
    "deliverables": "deliverables",
    "grass": "grass",
}

#: Every CONTENT lane that holds effort records (cost-bearing rollup lanes PLUS
#: the cost-free ``grass`` ideas lane). This is the set used when MOVING/FOLDING
#: a project's full effort history (sibling adoption + the destructive
#: ``rnd_registry.reconcile_folder`` fold-then-delete), so grass ideas are never
#: silently lost when a folded sibling id is hard-deleted. NOTE: grass is
#: deliberately EXCLUDED from :data:`ROLLUP_LANES` (the COST rollup) because
#: grass ideas carry no cost — only the fold/adopt iteration uses this set.
FOLD_LANES = ("research", "planning", "build", "deliverables", "grass")

#: Subdirectory under a lane dir holding the per-effort pointer-records.
EFFORTS_DIRNAME = "efforts"
#: The append-only ordered index of effort job_ids for a lane.
INDEX_NAME = "index.json"
#: Pointer-record filename suffix (matches the .gitignore allow-list).
POINTER_SUFFIX = ".pointer.json"

#: Canonical report artifact filenames the viewer looks for.
REPORT_MD = "report.md"
REPORT_PDF = "report.pdf"


# ── Path helpers ────────────────────────────────────────────────────────────

def _resolve_subdir(lane: str) -> str:
    """Resolve a lane name (trio or store form) to its store subdir name."""
    return LANE_SUBDIR.get(lane, lane)


def lane_dir(folder_path, project_id: str, lane: str) -> Path:
    """``<folder>/.anchor/projects/<id>/<lane-subdir>/`` (not created)."""
    return _rnd.project_store_dir(folder_path, project_id) / _resolve_subdir(lane)


def efforts_dir(folder_path, project_id: str, lane: str) -> Path:
    """The ``efforts/`` dir holding per-effort pointer-records (not created)."""
    return lane_dir(folder_path, project_id, lane) / EFFORTS_DIRNAME


def _index_path(folder_path, project_id: str, lane: str) -> Path:
    return lane_dir(folder_path, project_id, lane) / INDEX_NAME


def _pointer_path(folder_path, project_id: str, lane: str, job_id: str) -> Path:
    # The on-disk FILENAME must be filesystem-safe: a run-cost job_id embeds the
    # session_id (``run-cost-<sid>``) and a managed/lane-qualified session id can
    # contain ``::`` (e.g. ``build::sess-XYZ``) — illegal in a Windows filename.
    # Sanitize the filename with the SAME transform the summaries dir uses so the
    # write and every later read resolve to the identical path; the stored
    # ``job_id`` field and the append-only index keep the RAW value (lookups are
    # index-driven, never derived from the filename), so this is a pure
    # filename-safety mapping and a no-op for ordinary (special-char-free) ids.
    return efforts_dir(folder_path, project_id, lane) / (
        f"{_safe_session_segment(job_id)}{POINTER_SUFFIX}")


# ── Index (append-only, preserves order; newest-first is computed on read) ──

def _load_index(folder_path, project_id: str, lane: str) -> list:
    """Load the ordered list of effort job_ids (oldest-first on disk)."""
    p = _index_path(folder_path, project_id, lane)
    if not p.exists():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw]
    return []


def _save_index(folder_path, project_id: str, lane: str, order: list) -> None:
    p = _index_path(folder_path, project_id, lane)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    # Explicit open + flush + fsync (not Path.write_text) so the temp file's
    # bytes reach stable storage BEFORE the atomic rename — a crash between the
    # write and the replace can never leave a torn effort index (W2 durability
    # substrate). The write stays attributed to effort_history (the write-tripwire
    # mutation-of-record inventory) and the tmp→target replace keeps the atomic
    # idiom.
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(json.dumps(list(order), indent=2))
        f.flush()
        os.fsync(f.fileno())
    # The final rename goes through the shared bounded retry: on Windows,
    # os.replace raises a transient PermissionError (WinError 5) while a
    # concurrent lock-free reader (_load_index runs outside WRITE_LOCK)
    # briefly holds index.json open — the same sharing-violation race class
    # already tolerated by paths.atomic_write_text and job_runner._write_record.
    _paths._replace_with_retry(str(tmp), str(p))


# ── Effort pointer-record CRUD (append/version — never delete; D5) ──────────

def record_effort(folder_path, project_id: str, lane: str, job_id: str,
                  skill: str = None, prompt_seed: str = None,
                  extra: dict = None) -> dict:
    """Create (or update-in-place) the pointer-record for an effort.

    APPEND semantics (D5): a *new* job_id appends a new effort to the lane's
    history and never disturbs prior efforts. Calling again with the SAME job_id
    updates that one record in place (e.g. to stamp cost on completion) without
    creating a duplicate or re-ordering history. Returns the stored record.

    All writes under ``paths.WRITE_LOCK``.
    """
    with _paths.WRITE_LOCK, _journal.pairing():
        ed = efforts_dir(folder_path, project_id, lane)
        ed.mkdir(parents=True, exist_ok=True)
        ppath = _pointer_path(folder_path, project_id, lane, job_id)
        if ppath.exists():
            try:
                rec = json.loads(ppath.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                rec = {}
        else:
            rec = {}
        rec.setdefault("job_id", job_id)
        rec.setdefault("project_id", project_id)
        rec.setdefault("lane", _resolve_subdir(lane))
        rec.setdefault("created_at", time.time())
        if skill is not None:
            rec["skill"] = skill
        if prompt_seed is not None:
            rec["prompt_seed"] = prompt_seed
        if extra:
            rec.update(extra)
        _paths.atomic_write_text(
            ppath, json.dumps(rec, indent=2, ensure_ascii=False))
        # Append to the index iff this job_id is new (preserve prior order).
        order = _load_index(folder_path, project_id, lane)
        if job_id not in order:
            order.append(job_id)
            _save_index(folder_path, project_id, lane, order)
        return rec


def load_effort(folder_path, project_id: str, lane: str, job_id: str):
    """Return one effort's pointer-record dict, or ``None``."""
    p = _pointer_path(folder_path, project_id, lane, job_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def list_efforts(folder_path, project_id: str, lane: str) -> list:
    """Return the lane's effort pointer-records, **NEWEST-FIRST** (AC1).

    index 0 == the most recent effort ("current on top", C5). Nothing is ever
    deleted by reads or re-runs — the index is append-only and reversed here.
    Pointer-records that are missing/corrupt are skipped (best-effort).
    """
    order = _load_index(folder_path, project_id, lane)
    out = []
    seen = set()
    for job_id in reversed(order):  # newest-first
        rec = load_effort(folder_path, project_id, lane, job_id)
        if rec is not None:
            seen.add(job_id)
            out.append(rec)
    # INDEX-LOSS REPAIR (2026-07-26). The index is a load→append→save
    # read-modify-write guarded only by an IN-PROCESS lock (paths.WRITE_LOCK),
    # so a second process (CLI, healthcheck, rebuild_summaries, a preview
    # server) clobbers it. Observed live: general/efforts/ held 17 pointer
    # records while index.json listed 13 — and BOTH run-cost records were among
    # the missing, so real measured usage was invisible. The index remains the
    # ordering authority; the directory is the completeness authority. Recovered
    # records are appended after the indexed ones (unknown relative age).
    try:
        eff_dir = efforts_dir(folder_path, project_id, lane)
        if os.path.isdir(eff_dir):
            for name in sorted(os.listdir(eff_dir)):
                if not name.endswith(POINTER_SUFFIX):
                    continue
                job_id = name[: -len(POINTER_SUFFIX)]
                if job_id in seen:
                    continue
                rec = load_effort(folder_path, project_id, lane, job_id)
                if rec is not None:
                    out.append(rec)
    except Exception:
        pass  # best-effort repair: never fail a read over recovery
    return out


def latest_effort(folder_path, project_id: str, lane: str):
    """Return the most-recent effort pointer-record (index 0), or ``None``."""
    efforts = list_efforts(folder_path, project_id, lane)
    return efforts[0] if efforts else None


def efforts_for_session_id(folder_path, project_id: str, lane: str,
                           session_id: str) -> list:
    """Return the lane's effort pointer-records tagged with ``session_id``.

    The v8 Wave 2 ``persist_session_docs`` keystone stamps each persisted
    DISCOVERED doc effort with the originating managed terminal ``session_id``
    (in ``extra``). Those docs group (in ``sessions.list_sessions``) under their
    common parent directory — NOT under the bare managed session id — so a kill's
    durable summary/detail (which keys to the managed session id) needs a way to
    recover the EXACT docs THIS session produced. This is that join: every lane
    effort whose stored ``session_id`` equals ``session_id``, newest-first.

    Returns ``[]`` for an empty/unmatched lane. Never raises.
    """
    if not session_id:
        return []
    try:
        return [e for e in list_efforts(folder_path, project_id, lane)
                if (e.get("session_id") or "") == session_id]
    except Exception:
        return []


# ── Grass Catchers content feeds (Wave 5) ───────────────────────────────────

#: job_id prefix for an Anchor-CREATED grass idea (manual add / inbox promote).
#: Distinct from the discovered prefix so an idea card is honestly an Anchor
#: artifact, NOT a brownfield-discovered one.
IDEA_PREFIX = "idea-"

#: The Grass idea lifecycle (v5 Wave 5). An idea is captured RAW; developing it
#: with a tool (research/plan in the workbench terminal) yields a saved
#: refinement and marks it REFINED; promoting it into a lane marks it PROMOTED
#: and links the idea to the run it became. The legacy stored value ``"idea"``
#: is normalized to RAW so pre-v5 records keep working.
GRASS_RAW = "raw"
GRASS_REFINED = "refined"
GRASS_PROMOTED = "promoted"
GRASS_STATUSES = (GRASS_RAW, GRASS_REFINED, GRASS_PROMOTED)

#: Allowed status transitions. A forward walk (raw->refined->promoted) plus the
#: idempotent self-transition and the practical back-steps (re-refining a
#: promoted idea, or re-developing a refined one) — but never an unknown status.
_GRASS_TRANSITIONS = {
    GRASS_RAW: {GRASS_RAW, GRASS_REFINED, GRASS_PROMOTED},
    GRASS_REFINED: {GRASS_RAW, GRASS_REFINED, GRASS_PROMOTED},
    GRASS_PROMOTED: {GRASS_REFINED, GRASS_PROMOTED},
}

#: Subdir under the grass lane dir holding per-idea versioned refinements.
GRASS_REFINEMENTS_DIRNAME = "refinements"


def grass_status(rec: dict) -> str:
    """Normalize a grass idea record's lifecycle status to a GRASS_STATUSES value.

    Maps the legacy ``"idea"`` (and any missing/unknown value) to :data:`GRASS_RAW`
    so pre-v5 idea cards render with an honest status.
    """
    st = (rec or {}).get("status", "") or ""
    return st if st in GRASS_STATUSES else GRASS_RAW


def _new_idea_job_id() -> str:
    """A fresh, unique job_id for a manual/promoted grass idea."""
    return f"{IDEA_PREFIX}{hashlib.sha1(f'{time.time_ns()}'.encode()).hexdigest()[:16]}"


def grass_short_id(idea_id: str) -> str:
    """A short, stable, display-friendly id for an idea (mockup ``grass-1a2b``).

    Derived deterministically from the idea's stored job_id so the same idea
    always shows the same short id. The canonical ``idea_id`` (the stored
    ``job_id``) remains the lookup key; this is purely cosmetic.
    """
    raw = (idea_id or "").strip()
    if not raw:
        return "grass-0000"
    h = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:4]
    return f"grass-{h}"


def add_idea(folder_path, project_id: str, text: str, notes: str = "") -> dict:
    """Record a manual Grass Catchers idea as a grass-lane effort card (Wave 5).

    A real Anchor-CREATED idea (``source=SOURCE_RUN``, ``kind="idea"``) — NOT a
    brownfield-discovered artifact. It carries the user's ``text`` as its title
    and an optional ``notes`` blob; it has NO cost / tokens / session_id (it is
    not a trio run). Appends a new grass effort, newest-first; nothing is
    overwritten. Returns the stored pointer-record. All writes under WRITE_LOCK
    (via :func:`record_effort`).
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("idea text required")
    jid = _new_idea_job_id()
    extra = {
        "source": SOURCE_RUN,
        "kind": "idea",
        "title": text,
        "notes": (notes or "").strip(),
        # v5 Wave 5: ideas carry a raw->refined->promoted lifecycle status. A
        # freshly captured idea is RAW. (The legacy value ``"idea"`` is treated
        # as RAW by :func:`grass_status` so old records keep working.)
        "status": GRASS_RAW,
    }
    with _journal.journaled(project_id, _journal.EV_GRASS_IDEA_ADDED,
                            correlation_id=(jid or project_id),
                            folder_path=folder_path,
                            payload={"idea_id": jid, "title": text}):
        return record_effort(folder_path, project_id, "grass", jid, extra=extra)


def promote_inbox(folder_path, project_id: str, inbox_item_text: str,
                  inbox_items=None) -> dict:
    """Promote an EXISTING INBOX.md item into a project's Grass Catchers (Wave 5).

    Reads the existing inbox (the caller supplies ``inbox_items`` parsed by the
    GUI/CLI's existing ``parse_inbox_from_md`` — no new inbox format is invented)
    and creates a grass card from the matching item. Matching is by exact text,
    then case-insensitive, then substring (first match wins).

    COPY-BY-DEFAULT (non-destructive): the inbox item is NOT removed from
    INBOX.md — the idea is COPIED into the project's grass lane so the inbox
    remains the user's untouched capture log. (The frozen plan does not direct a
    move/remove; copy is the safe default, leaving INBOX.md as the source of
    truth.) Returns the stored grass pointer-record.

    Raises ``ValueError`` if the item is not found in the supplied inbox.
    """
    want = (inbox_item_text or "").strip()
    if not want:
        raise ValueError("inbox item text required")
    items = inbox_items or []
    match = None
    for it in items:
        if (it.get("text") or "").strip() == want:
            match = it
            break
    if match is None:
        low = want.lower()
        for it in items:
            if (it.get("text") or "").strip().lower() == low:
                match = it
                break
    if match is None:
        low = want.lower()
        for it in items:
            if low in (it.get("text") or "").strip().lower():
                match = it
                break
    if match is None:
        raise ValueError(f"inbox item not found: {inbox_item_text}")

    jid = _new_idea_job_id()
    note_bits = []
    if match.get("date"):
        note_bits.append(f"from INBOX {match['date']}")
    if match.get("domain"):
        note_bits.append(f"[{match['domain']}]")
    extra = {
        "source": SOURCE_RUN,
        "kind": "idea",
        "title": (match.get("text") or "").strip(),
        "notes": " ".join(note_bits),
        "status": GRASS_RAW,
        "promoted_from": "inbox",
    }
    with _journal.journaled(project_id, _journal.EV_EFFORT_PROMOTED,
                            correlation_id=(jid or project_id),
                            folder_path=folder_path,
                            payload={"source": "inbox", "job_id": jid}):
        return record_effort(folder_path, project_id, "grass", jid, extra=extra)


#: The lanes a grass idea may be promoted into (v4 Wave 6). Only the two TRIO
#: starting lanes — a Research run or a Plan run — make sense as a seeded launch.
PROMOTE_LANES = ("research", "plan")

#: v8 Wave 6 — a develop session started from the grass workbench is CONTAINED:
#: it lives only in the workbench pane, never in the top live-strip or a board
#: lane column. Its registry record's ``label`` carries this stable prefix so the
#: board bridge (``anchor_gui._gather_project_sessions``) can recognize and
#: EXCLUDE it even though its lane is ``research``/``plan`` (it must keep that
#: lane so the trio skill seeds correctly). ``is_grass_dev_label`` is the
#: predicate the bridge uses.
GRASS_DEV_LABEL_PREFIX = "[grass-dev] "


def is_grass_dev_label(label) -> bool:
    """True iff ``label`` marks a CONTAINED grass-workbench develop session (W6).

    A develop session keeps lane ``research``/``plan`` (so its trio skill seeds),
    but is contained — it must NOT render as a top-strip chip or a board lane
    tile. The board bridge calls this on each managed session's label to skip it.
    """
    return str(label or "").startswith(GRASS_DEV_LABEL_PREFIX)


def get_grass_idea(folder_path, project_id: str, idea_id: str):
    """Return ONE grass idea pointer-record by its ``job_id``, or ``None``.

    Matches against the grass lane's effort records (manual adds, INBOX
    promotions, discovered idea-docs). Best-effort: an unknown id returns
    ``None`` (never raises).
    """
    want = (idea_id or "").strip()
    if not want:
        return None
    for rec in list_efforts(folder_path, project_id, "grass"):
        if (rec.get("job_id") or "") == want:
            return rec
    return None


def promote_grass_to_lane(project_id: str, idea_id: str, lane: str,
                          folder_path=None, backend=None) -> dict:
    """Promote a Grass Catcher idea into a NEW seeded session in ``lane`` (Wave 6).

    Looks up the grass idea by ``idea_id``, then starts a brand-new terminal
    session in the target lane (``research`` | ``plan``) **seeded with the idea
    text** by REUSING the Wave-1 seed path: it delegates to
    ``terminal_session.start_session(..., seed_context=<idea text>)``, so the
    single opening turn loads the lane's trio skill (researchPrime / Crucible)
    AND carries the idea as the thing to work on. The Wave-1 seed-once /
    no-re-emit discipline is inherited unchanged.

    COPY, NEVER DESTROY: the idea record is left untouched in the grass lane (a
    promotion is a copy). Returns the NEW session's registry record.

    Raises ``ValueError`` for an invalid lane (not research/plan) or an idea that
    is not found in the project's grass lane.
    """
    lane = (lane or "").strip()
    if lane not in PROMOTE_LANES:
        raise ValueError(
            "promote lane must be one of %s, got %r"
            % (", ".join(PROMOTE_LANES), lane))
    if folder_path is None:
        proj = _rnd.get_project(project_id)
        if proj is None:
            raise ValueError("unknown project: %s" % (project_id,))
        folder_path = proj.get("folder_path", "")

    idea = get_grass_idea(folder_path, project_id, idea_id)
    if idea is None:
        raise ValueError("grass idea not found: %s" % (idea_id,))
    idea_text = (idea.get("title") or "").strip()
    if not idea_text:
        raise ValueError("grass idea has no text: %s" % (idea_id,))

    # Reuse the Wave-1 seed path (do NOT fork seed logic): start_session writes
    # the lane skill seed + the idea exactly once. Lazy import to keep
    # effort_history free of a hard dependency on the terminal stack.
    import terminal_session as _ts
    label = "from grass: " + (idea_text[:40])
    kwargs = {"label": label, "seed_context": idea_text}
    if backend is not None:
        kwargs["backend"] = backend
    with _journal.journaled(project_id, _journal.EV_EFFORT_PROMOTED,
                            correlation_id=(idea_id or project_id),
                            folder_path=folder_path,
                            payload={"idea_id": idea_id, "lane": lane}):
        record = _ts.start_session(project_id, lane, **kwargs)
        # The idea REMAINS in grass — promotion copies, never moves. We only
        # ANNOTATE the idea record in place (status -> promoted + a link to the run
        # it became); nothing here deletes or rewrites the idea's identity/title.
        try:
            set_grass_status(folder_path, project_id, idea_id, GRASS_PROMOTED,
                             promoted_to_session=record.get("session_id"),
                             promoted_to_lane=lane)
        except Exception:
            # A failed annotation must never tear down a live, seeded session.
            pass
    return record


# ── Grass idea lifecycle: status + versioned refinements + develop/pull (W5) ─

def set_grass_status(folder_path, project_id: str, idea_id: str, status: str,
                     promoted_to_session: str = None,
                     promoted_to_lane: str = None) -> dict:
    """Set a grass idea's lifecycle status (raw/refined/promoted), validated.

    Rejects an unknown target status and an illegal transition (see
    :data:`_GRASS_TRANSITIONS`) with ``ValueError`` — so an idea can never land
    in a bogus state. When promoting, ``promoted_to_session`` / ``promoted_to_lane``
    are stored on the idea so a PROMOTED idea LINKS to the run it became.

    Updates the idea's pointer-record IN PLACE (same job_id) — the idea's
    identity/title/history are untouched (COPY-never-destroy). Returns the
    updated record. Raises ``ValueError`` for an unknown idea or status.
    """
    status = (status or "").strip()
    if status not in GRASS_STATUSES:
        raise ValueError(
            "grass status must be one of %s, got %r"
            % (", ".join(GRASS_STATUSES), status))
    idea = get_grass_idea(folder_path, project_id, idea_id)
    if idea is None:
        raise ValueError("grass idea not found: %s" % (idea_id,))
    cur = grass_status(idea)
    if status not in _GRASS_TRANSITIONS.get(cur, set()):
        raise ValueError(
            "illegal grass status transition %s -> %s" % (cur, status))
    extra = {"status": status}
    if status == GRASS_PROMOTED:
        if promoted_to_session:
            extra["promoted_to_session"] = promoted_to_session
        if promoted_to_lane:
            extra["promoted_to_lane"] = promoted_to_lane
    with _journal.journaled(project_id, _journal.EV_GRASS_IDEA_STATUS,
                            correlation_id=(idea_id or project_id),
                            folder_path=folder_path,
                            payload={"idea_id": idea_id, "status": status}):
        return record_effort(folder_path, project_id, "grass",
                             idea.get("job_id", idea_id), extra=extra)


def _refinements_dir(folder_path, project_id: str, idea_id: str) -> Path:
    """``<grass-lane>/refinements/<sanitized-idea-id>/`` (not created)."""
    safe = "".join(c if (c.isalnum() or c in "-_") else "_"
                   for c in (idea_id or "x"))
    return (lane_dir(folder_path, project_id, "grass")
            / GRASS_REFINEMENTS_DIRNAME / safe)


def _refinement_id(idea_id: str, n: int) -> str:
    """The logical, display id for refinement version ``n`` (``grass-<id>/dev-N``)."""
    return "%s/dev-%d" % (grass_short_id(idea_id), n)


def list_grass_refinements(folder_path, project_id: str, idea_id: str) -> list:
    """Return an idea's versioned refinements, **NEWEST-FIRST** (highest dev-N).

    Each refinement is a small JSON record:
    ``{refinement_id, idea_id, version, label, text, artifacts, session_id,
       created_at}``. Best-effort: a missing dir / corrupt file yields ``[]`` /
    is skipped. Never raises.
    """
    d = _refinements_dir(folder_path, project_id, idea_id)
    if not d.exists():
        return []
    out = []
    try:
        entries = list(d.glob("dev-*.json"))
    except OSError:
        return []
    for p in entries:
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if isinstance(rec, dict):
            out.append(rec)
    out.sort(key=lambda r: int(r.get("version", 0) or 0), reverse=True)
    return out


def save_grass_refinement(folder_path, project_id: str, idea_id: str,
                          text: str = "", label: str = "",
                          artifacts=None, session_id: str = None) -> dict:
    """Append a NEW versioned refinement (``grass-<id>/dev-N``) for an idea (W5).

    The version ``N`` auto-increments (1-based) over the idea's existing
    refinements — nothing is overwritten (append-only history, newest-first on
    read). The refinement references produced ``text`` and/or ``artifacts`` (a
    list of folder-relative paths) and, when developed live, the ``session_id``
    that produced it. Saving a refinement marks the idea REFINED (raw->refined).

    Returns the stored refinement record. Raises ``ValueError`` for an unknown
    idea. All writes under WRITE_LOCK.
    """
    idea = get_grass_idea(folder_path, project_id, idea_id)
    if idea is None:
        raise ValueError("grass idea not found: %s" % (idea_id,))
    jid = idea.get("job_id", idea_id)
    with _paths.WRITE_LOCK, _journal.journaled(
            project_id, _journal.EV_GRASS_IDEA_REFINED,
            correlation_id=(idea_id or project_id),
            folder_path=folder_path, payload={"idea_id": idea_id}):
        d = _refinements_dir(folder_path, project_id, jid)
        d.mkdir(parents=True, exist_ok=True)
        existing = list_grass_refinements(folder_path, project_id, jid)
        version = (max((int(r.get("version", 0) or 0) for r in existing),
                       default=0) + 1)
        rec = {
            "refinement_id": _refinement_id(jid, version),
            "idea_id": jid,
            "version": version,
            "label": (label or "").strip(),
            "text": (text or "").strip(),
            "artifacts": list(artifacts or []),
            "session_id": session_id or "",
            "created_at": time.time(),
        }
        p = d / ("dev-%d.json" % version)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(rec, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
    # Mark the idea refined (idempotent if already refined; promoted stays
    # promoted — a promoted idea can still gain refinements without demotion).
    if grass_status(idea) == GRASS_RAW:
        try:
            set_grass_status(folder_path, project_id, jid, GRASS_REFINED)
        except ValueError:
            pass
    return rec


def _grass_develop_seed(idea: dict, refinements) -> str:
    """Build the seed_context for a develop/pull session: the idea text + its
    latest refinement(s), so the workbench session resumes from prior work."""
    bits = []
    title = (idea.get("title") or "").strip()
    if title:
        bits.append("Idea: " + title)
    notes = (idea.get("notes") or "").strip()
    if notes:
        bits.append("Notes: " + notes)
    for r in (refinements or [])[:3]:  # newest-first; cap context size
        rid = r.get("refinement_id", "")
        txt = (r.get("text") or "").strip()
        if txt:
            bits.append("Prior refinement %s: %s" % (rid, txt))
    return "\n".join(bits)


def _grass_dev_sessions(idea: dict) -> dict:
    """The idea record's ``(lane -> session_id)`` develop-session map (W6).

    Stored on the idea pointer-record under ``dev_sessions`` so a re-click can
    RESOLVE and FOCUS the existing contained develop session instead of starting
    a new one. Best-effort: a missing/garbled value yields ``{}``.
    """
    m = (idea or {}).get("dev_sessions")
    return dict(m) if isinstance(m, dict) else {}


def _live_grass_dev_session(session_id: str):
    """Return the registry record for ``session_id`` iff it is a LIVE (running)
    contained develop session, else ``None`` (W6 dedupe gate).

    A develop session is "live" while its registry status is RUNNING — a killed/
    done/failed one is reaped and a re-click must start fresh. Lazy import keeps
    ``effort_history`` free of a hard ``session_registry`` dependency.
    """
    if not session_id:
        return None
    try:
        import session_registry as _sr
        rec = _sr.get_session(session_id)
        if rec is None:
            return None
        return rec if rec.get("status") == _sr.STATUS_RUNNING else None
    except Exception:
        return None


def develop_grass_idea(project_id: str, idea_id: str, lane: str,
                       folder_path=None, backend=None) -> dict:
    """DEVELOP a grass idea in ONE contained, seeded workbench session (W6).

    v8 Wave 6 — one contained session per ``(idea, lane)``:

      * **Dedupe / focus.** Before starting, RESOLVE an existing develop session
        for this ``(idea_id, lane)`` from the idea record's ``dev_sessions`` map.
        If one is still LIVE (registry status RUNNING) its record is RETURNED
        (the workbench re-focuses it) — a re-click NEVER starts a second session.
        Only when none is live is a NEW session started and the map updated.
      * **Contained.** The new session keeps lane ``research``/``plan`` (so its
        trio skill seeds correctly) but its registry ``label`` is stamped with
        :data:`GRASS_DEV_LABEL_PREFIX`, so the board bridge EXCLUDES it from the
        top strip and the lane columns (see :func:`is_grass_dev_label`). It lives
        only in the workbench pane.

    Seeds (``seed_context``) the idea text PLUS its latest refinements (reuses the
    Wave-1 seed path via ``terminal_session.start_session`` — never forks seed
    logic). The idea STAYS in grass (copy, never destroy). Returns the develop
    session's registry record (the workbench terminal attaches to it).

    Unlike :func:`promote_grass_to_lane`, develop keeps the idea available for
    further iteration; a *saved refinement* (via :func:`save_grass_refinement`) is
    what marks it REFINED.

    Raises ``ValueError`` for an invalid lane or an unknown idea.
    """
    lane = (lane or "").strip()
    if lane not in PROMOTE_LANES:
        raise ValueError(
            "develop lane must be one of %s, got %r"
            % (", ".join(PROMOTE_LANES), lane))
    if folder_path is None:
        proj = _rnd.get_project(project_id)
        if proj is None:
            raise ValueError("unknown project: %s" % (project_id,))
        folder_path = proj.get("folder_path", "")
    idea = get_grass_idea(folder_path, project_id, idea_id)
    if idea is None:
        raise ValueError("grass idea not found: %s" % (idea_id,))
    jid = idea.get("job_id", idea_id)

    # ── Dedupe / focus: a live (idea, lane) develop session is REUSED ──────────
    dev_map = _grass_dev_sessions(idea)
    existing_sid = dev_map.get(lane)
    live = _live_grass_dev_session(existing_sid)
    if live is not None:
        return live

    refinements = list_grass_refinements(folder_path, project_id, jid)
    seed = _grass_develop_seed(idea, refinements)
    if not seed.strip():
        raise ValueError("grass idea has no text: %s" % (idea_id,))
    import terminal_session as _ts
    # CONTAINED: the label marker keeps this session out of the board/top-strip.
    label = GRASS_DEV_LABEL_PREFIX + ("develop: " + ((idea.get("title") or "")[:40]))
    kwargs = {"label": label, "seed_context": seed}
    if backend is not None:
        kwargs["backend"] = backend
    record = _ts.start_session(project_id, lane, **kwargs)

    # Persist the (idea, lane) -> session_id map on the idea record so a re-click
    # focuses THIS session. Best-effort: a failed annotation never tears down a
    # live, seeded session. The idea's identity/title/status are untouched.
    try:
        dev_map[lane] = record.get("session_id")
        record_effort(folder_path, project_id, "grass", jid,
                      extra={"dev_sessions": dev_map})
    except Exception:
        pass
    return record


#: v12 Wave 11 — the SINGLE-session grass workbench key. The one-session-per-idea
#: workbench (the approved ``_mockups/grass_2_workbench.html``) keeps ONE
#: stage-carrying ``effort_managed`` grass-dev session per idea under this key in
#: the idea record's ``dev_sessions`` map (so it never collides with the legacy
#: per-lane ``research``/``plan`` keys a pre-v12 idea may carry, and the
#: back-compat resolver can find it). It advances research→plan IN-SESSION via
#: :func:`terminal_session.advance_stage` — it does NOT mint a second grass
#: session (the grass second-advance is retired for ``effort_managed`` ideas, W7).
GRASS_WORKBENCH_KEY = "workbench"


def _grass_workbench_session(idea: dict):
    """Resolve the idea's SINGLE workbench session record (v12 Wave 11).

    Returns ``(session_id, registry_record)`` for the idea's one-session
    workbench, or ``(None, None)`` when none is live. Resolution order
    (back-compat — A10):

      1. the explicit v12 single-session key (``dev_sessions['workbench']``);
      2. a pre-v12 idea with two ``dev_sessions`` ``{research, plan}`` → the
         MOST-ADVANCED live one (``plan`` over ``research``) is surfaced as THE
         single workbench session (a stage history; no orphan).

    A session is only surfaced when it is LIVE (registry RUNNING); a reaped one
    yields ``(None, None)`` so the workbench re-mints/focuses cleanly.
    """
    dev_map = _grass_dev_sessions(idea)
    # 1) The v12 single-session key wins when live.
    wsid = dev_map.get(GRASS_WORKBENCH_KEY) or ""
    live = _live_grass_dev_session(wsid)
    if live is not None:
        return wsid, live
    # 2) Back-compat: a pre-v12 idea's most-advanced live lane session.
    for lane in ("plan", "research"):
        sid = dev_map.get(lane) or ""
        rec = _live_grass_dev_session(sid)
        if rec is not None:
            return sid, rec
    return None, None


def _grass_workbench_session_view(idea: dict):
    """SAFE single-session projection for :func:`grass_workbench_data` (W11).

    Returns ``{session_id, lane, current_stage, status, label}`` for the idea's
    one live workbench session (the v12 key or a back-compat most-advanced lane
    session), or ``None`` when none is live. NEVER carries worktree/branch (the
    SAFE-projection rule). Best-effort; never raises.
    """
    try:
        sid, rec = _grass_workbench_session(idea)
    except Exception:
        sid, rec = None, None
    if not sid or rec is None:
        return None
    return {
        "session_id": sid,
        "lane": rec.get("lane", ""),
        "current_stage": rec.get("current_stage", "") or rec.get("lane", ""),
        "status": rec.get("status", ""),
        "label": rec.get("label", ""),
    }


def develop_grass_workbench(project_id: str, idea_id: str,
                            folder_path=None, backend=None) -> dict:
    """Open the idea's SINGLE one-session workbench (v12 Wave 11; SC5).

    The v12 grass model: ONE stage-carrying ``effort_managed`` grass-dev session
    per idea (no Research/Plan split). It starts at the ``research`` lane (so the
    researchPrime skill seeds) and ADVANCES research→plan IN-SESSION via
    :func:`terminal_session.advance_stage` — it never mints a second grass session
    (the legacy grass second-advance is gated off for ``effort_managed`` ideas, W7).

    Dedupe/focus + back-compat (A10):
      * If the idea already has a LIVE workbench session (the v12 key OR — for a
        pre-v12 idea — its most-advanced ``{research,plan}`` dev session) it is
        RETURNED (re-focused), never re-minted.
      * Only when none is live is a NEW ``effort_managed`` grass-dev session
        started and the ``dev_sessions['workbench']`` key recorded.

    Seeds the idea text + its refinements (reuses :func:`_grass_develop_seed`).
    The idea STAYS in grass (copy, never destroy). Returns the workbench session's
    registry record. Raises ``ValueError`` for an unknown idea.
    """
    if folder_path is None:
        proj = _rnd.get_project(project_id)
        if proj is None:
            raise ValueError("unknown project: %s" % (project_id,))
        folder_path = proj.get("folder_path", "")
    idea = get_grass_idea(folder_path, project_id, idea_id)
    if idea is None:
        raise ValueError("grass idea not found: %s" % (idea_id,))
    jid = idea.get("job_id", idea_id)

    # Atomic check-then-mint (W11-R2-02): hold WRITE_LOCK across the dedupe check,
    # start_session, AND the dev_sessions['workbench'] record so two near-simultaneous
    # opens can't both pass the "no live session" check and double-mint a session for
    # one idea (parity with advance_stage; WRITE_LOCK is a re-entrant RLock, so the
    # nested acquisitions in start_session/record_effort are safe).
    with _paths.WRITE_LOCK:
        # Re-fetch under the lock so the dedupe check sees a key a concurrent open
        # may have just recorded.
        idea = get_grass_idea(folder_path, project_id, idea_id) or idea
        _wsid, live = _grass_workbench_session(idea)
        if live is not None:
            return live

        refinements = list_grass_refinements(folder_path, project_id, jid)
        seed = _grass_develop_seed(idea, refinements)
        if not seed.strip():
            raise ValueError("grass idea has no text: %s" % (idea_id,))
        import terminal_session as _ts
        label = GRASS_DEV_LABEL_PREFIX + ("idea: " + ((idea.get("title") or "")[:40]))
        kwargs = {"label": label, "seed_context": seed, "effort_managed": True}
        if backend is not None:
            kwargs["backend"] = backend
        record = _ts.start_session(project_id, "research", **kwargs)

        # Record the single-session key so a re-click focuses THIS session.
        # Best-effort — a failed annotation never tears down the live session.
        try:
            dev_map = _grass_dev_sessions(idea)
            dev_map[GRASS_WORKBENCH_KEY] = record.get("session_id")
            record_effort(folder_path, project_id, "grass", jid,
                          extra={"dev_sessions": dev_map})
        except Exception:
            pass
        return record


def _materialize_handoff_into_plan_worktree(folder_path, plan_record, hk):
    """Make the upstream handoff docs READABLE from a grass plan dev worktree.

    v11.1 Wave 2 BLOCKER fix. ``advance_grass_research_to_plan`` snapshots +
    persists the research session's transcript into the MAIN project (committed
    on main HEAD) and delivers a prompt naming ``research/<sid>-transcript.md``.
    For a FRESH-MINT plan session the worktree is cut off main HEAD AFTER the
    commit → the file is already present. But for a FOCUSED-EXISTING (the user
    developed "Plan" FIRST) plan session, its worktree was created BEFORE the
    transcript commit → the named file is ABSENT from its checkout, so Crucible
    would hit file-not-found.

    This makes the named docs PRESENT on disk in the plan worktree for BOTH
    orderings and writes the same durable artifacts the non-grass advance writes
    (HANDOFF.md + NEXT-PROMPT.md), so the named doc is always reachable:

      - For each persisted upstream doc rel (``hk['doc_rels']`` / ``hk['persisted']``)
        COPY ``<folder>/<rel>`` → ``<plan_wt>/<rel>`` (creating parent dirs),
        skipping a byte-identical copy (idempotent — a no-op for the fresh-mint
        case where the file is already there off main HEAD).
      - Write ``HANDOFF.md`` + ``NEXT-PROMPT.md`` into the plan worktree.

    Best-effort: ANY failure is swallowed so it NEVER breaks the advance. Stays
    within contained-grass semantics — it only materializes docs + handoff files,
    it does NOT touch the session record / dedup / linkage / grass_origin.
    """
    try:
        if not isinstance(hk, dict) or not isinstance(plan_record, dict):
            return
        plan_wt = (plan_record.get("worktree_path") or "").strip()
        if not plan_wt:
            return
        wt = Path(plan_wt)
        if not wt.is_dir():
            return
        main = Path(folder_path) if folder_path else None

        # Union of the named upstream doc rels (doc_rels + persisted), deduped.
        rels = []
        for key in ("doc_rels", "persisted"):
            for r in (hk.get(key) or []):
                r = str(r).strip().replace("\\", "/")
                if r and r not in rels:
                    rels.append(r)

        # Materialize each rel into the plan worktree from the MAIN project copy.
        if main is not None and main.exists():
            for rel in rels:
                try:
                    # Guard against traversal: the rel must resolve UNDER the wt.
                    dst = (wt / rel).resolve()
                    if not str(dst).startswith(str(wt.resolve())):
                        continue
                    src = main / rel
                    if not src.is_file():
                        continue
                    if dst.is_file():
                        try:
                            if src.read_bytes() == dst.read_bytes():
                                continue  # already present + identical → no-op
                        except OSError:
                            pass
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(str(src), str(dst))
                except OSError:
                    continue

        # Write the durable handoff artifacts INTO the plan worktree, matching the
        # non-grass /api/rnd/advance_session path (the safety net so the named doc
        # is always reachable via HANDOFF.md / NEXT-PROMPT.md too).
        try:
            import handoff as _hk
            _hk.write_handoff_md(plan_wt, hk.get("doc_rels", []),
                                 hk.get("skill", "") or "Crucible",
                                 hk.get("summary_text", ""))
            prompt = (hk.get("prompt") or "").strip()
            if prompt:
                _hk.write_next_prompt(plan_wt, prompt)
        except Exception:
            pass
    except Exception:
        pass


def advance_grass_research_to_plan(project_id: str, idea_id: str,
                                   folder_path=None, backend=None) -> dict:
    """Push a grass idea's RESEARCH dev session → a linked grass PLAN dev session.

    v10 Wave 5 (Pillar 2 #2). The grass-workbench analog of the project-level
    research→plan advance (``/api/rnd/advance_session``): it reuses the SAME
    paste-NOT-submit seeded handoff (Wave 1/2) but stays INSIDE the grass
    workbench, linked. Steps:

      1. Resolve the idea's RESEARCH dev session from the idea record's
         ``dev_sessions`` map (the contained ``(idea, 'research')`` session
         started by :func:`develop_grass_idea`). HONEST: with no research dev
         session → ``{"ok": False, "reason": "no-research-session"}`` (nothing
         minted).
      2. PERSIST that research session's produced docs into the main project (the
         v8 keystone, best-effort) so :func:`handoff.build_next_stage_prompt`
         resolves the REAL research doc paths.
      3. Build the reviewable next-stage prompt via the v11 keystone
         ``terminal_session.prepare_stage_handoff(pid, rsid, 'planning')`` — the
         research→plan body (real research doc paths + "read these first, then
         plan" + Crucible). v11.1 Wave 2 (D1): this advance NO LONGER refuses on
         "no written doc". The keystone (W1) ALWAYS produces material — it
         snapshots the research session's PTY transcript when no file was written
         (naming ``research/<sid>-transcript.md`` in the prompt), or returns the
         honest-minimal "create the materials" prompt for a genuinely zero-output
         session — so the old ``no-research-material`` hard-refusal is removed and
         the path ALWAYS opens the next session, exactly like the non-grass advance.
      4. Start (or FOCUS — dedupe like :func:`develop_grass_idea`) the idea's
         CONTAINED ``(idea, 'plan')`` dev session (GRASS_DEV_LABEL_PREFIX label →
         excluded from the board + top strip; keyed in ``dev_sessions``) with
         ``paste_prompt=<prompt>`` (held UNSENT until the user presses Enter),
         ``parent_session_id=<research_dev_sid>`` (so the chain links
         research-dev → plan-dev and shares the chain id), and
         ``grass_origin=idea_id`` (so the lineage traces back to the idea).
      5. Record the ``research->plan`` stage edge
         (:func:`handoff.record_stage_link`, rescan-durable).

    The idea STAYS in grass (copy, never destroy). Returns
    ``{"ok": bool, "session": <plan record>|None, "reason": str,
    "research_session_id": str}``. Raises ``ValueError`` for an unknown project or
    idea.
    """
    if folder_path is None:
        proj = _rnd.get_project(project_id)
        if proj is None:
            raise ValueError("unknown project: %s" % (project_id,))
        folder_path = proj.get("folder_path", "")
    idea = get_grass_idea(folder_path, project_id, idea_id)
    if idea is None:
        raise ValueError("grass idea not found: %s" % (idea_id,))
    jid = idea.get("job_id", idea_id)

    # 1) Resolve the contained RESEARCH dev session. Honest if absent.
    dev_map = _grass_dev_sessions(idea)
    rsid = dev_map.get("research") or ""
    # v12 Wave 11: a one-session workbench idea keeps its single session under the
    # ``workbench`` key (no per-lane ``research`` key). Resolve it as the research
    # source so the W7 effort_managed retirement gate below catches it (the gate
    # then early-returns — a v12 effort advances IN-SESSION, never via a second
    # grass session). A legacy idea (per-lane keys, effort_managed==False) is
    # unchanged.
    if not rsid:
        rsid = dev_map.get(GRASS_WORKBENCH_KEY) or ""
    if not rsid:
        return {"ok": False, "session": None, "research_session_id": "",
                "reason": "no-research-session"}

    # v12 Wave 7 — RETIREMENT MAP (Shark C4/C3): the grass SECOND-ADVANCE is
    # retired for a v12 EFFORT. A grass-dev effort (effort_managed==True)
    # advances IN-SESSION via terminal_session.advance_stage (one session per
    # idea, W11); this legacy grass research→plan path must mint NO second grass
    # plan session for it. Gate on the RESEARCH dev session's ``effort_managed``
    # ONLY (never kind/lane — a legacy grass-dev record carries kind=='grass-dev'
    # too). A legacy idea (effort_managed==False) falls through to the full v10/
    # v11 grass-advance path below, unchanged, so those healthcheck walks pass.
    try:
        import session_registry as _sr
        _rrec = _sr.get_session(rsid)
    except Exception:
        _rrec = None
    if _rrec is not None and _rrec.get("effort_managed"):
        return {"ok": False, "session": None, "research_session_id": rsid,
                "reason": "effort-managed-use-advance-stage"}

    # 2+3) v11 Wave 3 — route the PERSIST + PROMPT through the SHARED keystone
    #    (:func:`terminal_session.prepare_stage_handoff`), unifying this grass
    #    research→plan variant with the project-level advance paths so the
    #    persist+prompt logic is no longer DUPLICATED here. The keystone PERSISTS
    #    the research dev session's produced docs into the main project (best-effort,
    #    idempotent, works on the LIVE dev session) and BUILDS the real research→plan
    #    prompt (Crucible + the persisted research doc paths + "read these first").
    #    SAFE/PARTIAL unification (per the wave plan's CAUTION): only the persist +
    #    prompt builder + doc_rels are shared; the CONTAINED-grass session wiring
    #    (GRASS_DEV_LABEL_PREFIX label, dev_sessions dedup/focus, queue_paste,
    #    grass_origin) stays grass-specific below so the v10 W5 behavior is preserved
    #    exactly (these contained-session semantics do NOT fit the keystone and must
    #    not be forced through it).
    import terminal_session as _ts
    import handoff as _handoff
    hk = _ts.prepare_stage_handoff(project_id, rsid, "planning")
    prompt = (hk.get("prompt") or "") if isinstance(hk, dict) else ""

    # v11.1 Wave 2 (D1) — the grass advance NO LONGER refuses on "no written doc".
    # The v10 W5 ``no-research-material`` early-return that used to live here (it
    # required the keystone's prompt to name a persisted research doc, else it
    # returned ``{"ok": False, "reason": "no-research-material"}`` BEFORE any
    # ``start_session``) is REMOVED. It refused the CONVERSATION-ONLY case (a
    # research session that was a dialogue, no file written) — exactly John's
    # reported failure — and it diverged from the non-grass advance path which has
    # no such guard. The v11.1 keystone (W1) now ALWAYS produces material: it
    # snapshots the research session's PTY transcript to ``research/<sid>-transcript.md``
    # when no document was written and references it in the prompt, or — for a
    # genuinely zero-output session — returns the honest-minimal "create the
    # materials" prompt. Either way we fall through to the existing contained-grass
    # mint/focus/link machinery below (UNCHANGED from v10 W5) and OPEN the plan
    # session. The only legitimate refusal remaining is ``no-research-session``
    # (there is no research dev session at all to advance FROM — handled above).
    if not prompt.strip():
        # Belt-and-suspenders: the keystone is best-effort and should never hand back
        # an empty prompt after W1, but if it somehow did, build the honest-minimal
        # fallback ourselves so we STILL open the session (never refuse).
        try:
            prompt = _handoff.build_next_stage_prompt(
                folder_path, project_id, rsid, "planning")
        except Exception:
            prompt = ""

    # 4) Start (or FOCUS) the contained (idea, 'plan') dev session, seeded with the
    #    pending paste, linked to the research dev session, carrying grass_origin.
    existing_psid = dev_map.get("plan") or ""
    live_plan = _live_grass_dev_session(existing_psid)
    if live_plan is not None:
        # Dedupe: a live (idea, 'plan') dev session already exists → FOCUS it (no
        # second plan session minted). Record/refresh the stage edge so the link
        # is durable even on a re-advance.
        try:
            _handoff.record_stage_link(folder_path, project_id, rsid,
                                       existing_psid, kind="research->plan")
        except Exception:
            pass
        # DEFECT-1 FIX (develop-plan-first → advance must still deliver the
        # handoff). If the user clicked "Plan"/Develop FIRST, the existing plan
        # dev session is BARE — seeded with only the idea text, carrying NO
        # handoff (``pending_paste == ''`` AND ``paste_flushed`` False). In that
        # case DELIVER the generated research→plan prompt onto it as a fresh
        # pending paste (``terminal_session.queue_paste``); the session already
        # greeted, so the greet-marker-count guard is satisfied → it flushes
        # UNSENT on the next read. The guard in ``queue_paste`` refuses to deliver
        # a SECOND paste, so advance→advance (re-advance) NEVER double-delivers and
        # a session the user is mid-handoff on is left untouched.
        delivered = False
        if (not (live_plan.get("pending_paste") or "")
                and not live_plan.get("paste_flushed")):
            try:
                delivered = _ts.queue_paste(existing_psid, prompt)
            except Exception:
                delivered = False
        # v11.1 W2 BLOCKER FIX — the FOCUSED-EXISTING (develop-plan-FIRST) case.
        # This plan worktree was created BEFORE the transcript commit, so the doc
        # named in the prompt is ABSENT from its checkout. Materialize the named
        # upstream docs into THIS worktree + write HANDOFF.md/NEXT-PROMPT.md, so
        # Crucible can READ the transcript. Best-effort — never breaks the advance.
        _materialize_handoff_into_plan_worktree(folder_path, live_plan, hk)
        return {"ok": True, "session": live_plan,
                "research_session_id": rsid, "reason": "focused-existing",
                "paste_delivered": delivered}

    label = GRASS_DEV_LABEL_PREFIX + (
        "advance→plan: " + ((idea.get("title") or "")[:34]))
    kwargs = {"label": label, "paste_prompt": prompt,
              "parent_session_id": rsid, "grass_origin": jid}
    if backend is not None:
        kwargs["backend"] = backend
    record = _ts.start_session(project_id, "plan", **kwargs)
    psid = record.get("session_id", "")

    # v11.1 W2 BLOCKER FIX — the FRESH-MINT case. The new worktree IS cut off main
    # HEAD after the transcript commit, so the named doc is already present; this
    # call is then idempotent (byte-identical → no-op) but STILL writes the durable
    # HANDOFF.md/NEXT-PROMPT.md into the plan worktree, matching the non-grass
    # advance path. Best-effort — never breaks the advance.
    _materialize_handoff_into_plan_worktree(folder_path, record, hk)

    # Persist the (idea, 'plan') -> session_id map so a re-click focuses THIS
    # session (best-effort; a failed annotation never tears down a live session).
    try:
        dev_map["plan"] = psid
        record_effort(folder_path, project_id, "grass", jid,
                      extra={"dev_sessions": dev_map})
    except Exception:
        pass

    # 5) Record the research->plan stage edge (rescan-durable).
    try:
        _handoff.record_stage_link(folder_path, project_id, rsid, psid,
                                   kind="research->plan")
    except Exception:
        pass

    return {"ok": True, "session": record, "research_session_id": rsid,
            "reason": "advanced", "paste_delivered": True}


def pull_grass_refinement(project_id: str, idea_id: str, refinement_id: str,
                          lane: str, folder_path=None, backend=None) -> dict:
    """PULL a chosen refinement version into a NEW seeded session (v5 Wave 5).

    Seeds a fresh ``research`` | ``plan`` session with the chosen refinement's
    content (reuses the Wave-1 seed path) — "pull a refinement into another
    effort". The idea + refinement are left untouched. Returns the NEW session
    record.

    Raises ``ValueError`` for an invalid lane, unknown idea, or unknown
    refinement id.
    """
    lane = (lane or "").strip()
    if lane not in PROMOTE_LANES:
        raise ValueError(
            "pull lane must be one of %s, got %r"
            % (", ".join(PROMOTE_LANES), lane))
    if folder_path is None:
        proj = _rnd.get_project(project_id)
        if proj is None:
            raise ValueError("unknown project: %s" % (project_id,))
        folder_path = proj.get("folder_path", "")
    idea = get_grass_idea(folder_path, project_id, idea_id)
    if idea is None:
        raise ValueError("grass idea not found: %s" % (idea_id,))
    jid = idea.get("job_id", idea_id)
    want = (refinement_id or "").strip()
    chosen = None
    for r in list_grass_refinements(folder_path, project_id, jid):
        if r.get("refinement_id") == want or str(r.get("version")) == want:
            chosen = r
            break
    if chosen is None:
        raise ValueError("refinement not found: %s" % (refinement_id,))
    title = (idea.get("title") or "").strip()
    rtext = (chosen.get("text") or "").strip()
    seed_bits = []
    if title:
        seed_bits.append("Idea: " + title)
    seed_bits.append("Pulled refinement %s: %s"
                     % (chosen.get("refinement_id", want), rtext or "(no text)"))
    seed = "\n".join(seed_bits)
    import terminal_session as _ts
    label = "pull %s" % (chosen.get("refinement_id", want))
    kwargs = {"label": label, "seed_context": seed}
    if backend is not None:
        kwargs["backend"] = backend
    return _ts.start_session(project_id, lane, **kwargs)


def grass_workbench_data(folder_path, project_id: str) -> list:
    """Aggregate the project's grass ideas for the workbench UI (read-only, W5).

    Returns a list (the grass lane order, newest-first) of dicts:
    ``{idea_id, short_id, title, notes, status, source, promoted_to_session,
       promoted_to_lane, refinements:[…newest-first…]}``. Best-effort; never
    raises.
    """
    out = []
    try:
        efforts = list_efforts(folder_path, project_id, "grass")
    except Exception:
        efforts = []
    for eff in efforts:
        jid = eff.get("job_id", "") or ""
        refs = list_grass_refinements(folder_path, project_id, jid)
        if is_discovered(eff):
            source = "discovered"
        elif (eff.get("promoted_from") or "") == "inbox":
            source = "inbox"
        else:
            source = "manual"
        out.append({
            "idea_id": jid,
            "short_id": grass_short_id(jid),
            "title": (eff.get("title") or "").strip(),
            "notes": (eff.get("notes") or "").strip(),
            "status": grass_status(eff),
            "source": source,
            "promoted_to_session": eff.get("promoted_to_session", ""),
            "promoted_to_lane": eff.get("promoted_to_lane", ""),
            # v8 Wave 6: the contained develop sessions ((lane -> session_id)) and
            # the Export-to-project link (the real lane sessions this idea's work
            # became). Both empty until the idea is developed / exported.
            "dev_sessions": _grass_dev_sessions(eff),
            # v12 Wave 11: the SINGLE-session workbench shape (SC5). A SAFE
            # projection (session_id · stage · status — never worktree/branch) of
            # the idea's one live workbench session: the v12 ``workbench`` key, or
            # — for a pre-v12 idea with ``{research,plan}`` dev_sessions — its
            # MOST-ADVANCED live one (back-compat A10; no orphan). ``None`` when
            # no workbench session is live.
            "workbench_session": _grass_workbench_session_view(eff),
            "exported_to": list((eff.get("exported_to") or [])),
            # v10 Wave 4: per-idea ARCHIVE bundles (persisted dev docs + summary
            # ref tied to this idea), newest-first. Empty until the idea is
            # archived. Distinct from ``refinements`` (text snapshots).
            "archives": list_grass_archives(folder_path, project_id, jid),
            "refinements": refs,
        })
    return out


def delete_grass_idea(folder_path, project_id: str, idea_id: str) -> dict:
    """Permanently delete ONE grass idea + all its grass-side stores (v9 Wave 2).

    Project-scoped, BEST-EFFORT, IDEMPOTENT, never raises. For ``idea_id`` in the
    project's grass lane this removes:

      1. the idea **pointer-record** + its **grass index.json** entry (reuses the
         :func:`_delete_effort_record` pointer+index removal pattern);
      2. the idea's **refinements dir** (``refinements/<id>/`` with all its
         ``dev-N.json`` versions) — recursive remove;
      3. its **dev_sessions** map — the CONTAINED develop sessions are best-effort
         deleted/forgotten (``terminal_session.delete_session`` if available, else
         the registry record is dropped via ``session_registry.remove_session``);
         a failure here never raises and never blocks the idea removal.

    Only this project's grass lane is touched — sibling ideas and other projects
    are untouched (the pointer/index/refinements paths are all idea-id-scoped).
    Returns ``{"ok": True, "deleted": bool, "idea_id", "refinements_removed":
    bool, "dev_sessions_cleared": [session_id...]}`` where ``deleted`` is whether a
    grass pointer-record was removed (False if the id was already unknown).
    """
    want = (idea_id or "").strip()
    cleared_sessions = []
    refinements_removed = False
    deleted = False
    if not want:
        return {"ok": True, "deleted": False, "idea_id": want,
                "refinements_removed": False, "dev_sessions_cleared": []}

    # Resolve the idea (best-effort) so we can clean its contained dev sessions
    # BEFORE we drop the pointer-record. An unknown id → a clean no-op.
    idea = get_grass_idea(folder_path, project_id, want)
    jid = (idea.get("job_id", want) if idea else want)

    # v10 Wave 6 (D3 source "grass-deleted") — CAPTURE the idea text + any dev/
    # refinement doc rels into the project's Boneyard BEFORE we purge the idea
    # (after which the pointer/index/refinements are gone forever). BEST-EFFORT —
    # a Boneyard failure must NEVER block the idea removal.
    if idea is not None:
        try:
            import boneyard as _boneyard
            entry = _boneyard.build_grass_entry(folder_path, project_id, idea)
            _boneyard.record_entry(folder_path, project_id, entry)
        except Exception:
            pass

    # 1) Best-effort clean the CONTAINED develop sessions (kill/forget, never raise).
    if idea is not None:
        for _lane, sid in _grass_dev_sessions(idea).items():
            sid = (sid or "").strip()
            if not sid:
                continue
            try:
                import terminal_session as _ts
                _ts.delete_session(sid, project_id=project_id)
                cleared_sessions.append(sid)
            except Exception:
                try:
                    import session_registry as _sr
                    _sr.remove_session(sid)
                    cleared_sessions.append(sid)
                except Exception:
                    pass

    # 2) Drop the idea pointer-record + its grass index entry (reuse the W1 pattern).
    with _journal.journaled(project_id, _journal.EV_GRASS_IDEA_DELETED,
                            correlation_id=(want or project_id),
                            folder_path=folder_path,
                            payload={"idea_id": want}):
        try:
            deleted = bool(_delete_effort_record(folder_path, project_id, "grass", jid))
        except Exception:
            deleted = False

    # 3) Remove the refinements dir (the dev-N versions) — recursive, tolerant.
    try:
        rdir = _refinements_dir(folder_path, project_id, jid)
        if rdir.is_dir():
            shutil.rmtree(str(rdir), ignore_errors=True)
            refinements_removed = not rdir.exists()
    except Exception:
        refinements_removed = False

    return {
        "ok": True,
        "deleted": deleted,
        "idea_id": jid,
        "refinements_removed": refinements_removed,
        "dev_sessions_cleared": cleared_sessions,
    }


# ── Grass → project export (v8 Wave 6, Option B: copy up, idea stays) ────────

def export_grass_to_project(project_id: str, idea_id: str,
                            folder_path=None) -> dict:
    """Export an idea's research/plan WORK up into REAL lane tiles (W6, Option B).

    The locked "Export to project" behavior: the idea's contained develop work is
    COPIED up into the real Research/Plan lane columns as durable, board-visible
    sessions — AND the idea STAYS in grass, marked ``promoted`` with a link to the
    new project sessions (copy, never destroy).

    For each lane (research/plan) in which this idea has a develop session
    (``dev_sessions``), this:

      1. PERSISTS that develop session's produced docs into the main project (so
         the work survives), reusing the Wave-2 keystone
         :func:`persist_session_docs` (best-effort; a still-live session whose
         docs aren't yet written simply persists nothing).
      2. Records a REAL (run-source) lane effort — a board-visible session — that
         CARRIES the develop session's persisted docs (``artifacts``, resolved via
         the Wave-5 :func:`efforts_for_session_id` join) and LINKS back to the
         idea (``from_grass_idea``).
      3. Collects ``{lane, session_id, export_effort_id}`` link records.

    Then it marks the idea PROMOTED (via :func:`set_grass_status`) with a link to
    the first exported session, and stores the full ``exported_to`` link list on
    the idea record. The idea is never destroyed.

    Returns ``{"ok": bool, "exported": [{lane, session_id, export_effort_id,
    docs:[rel,...]}, ...], "reason": str}``. Raises ``ValueError`` for an unknown
    project or idea. Idempotent per (idea, develop-session): a content-addressed
    export effort id means re-exporting the same develop work does not duplicate.
    """
    if folder_path is None:
        proj = _rnd.get_project(project_id)
        if proj is None:
            raise ValueError("unknown project: %s" % (project_id,))
        folder_path = proj.get("folder_path", "")
    idea = get_grass_idea(folder_path, project_id, idea_id)
    if idea is None:
        raise ValueError("grass idea not found: %s" % (idea_id,))
    jid = idea.get("job_id", idea_id)
    title = (idea.get("title") or "").strip()

    raw_map = _grass_dev_sessions(idea)
    # v12 Wave 11: the one-session workbench keeps a SINGLE session under the
    # ``workbench`` key (NOT a per-lane key). Build the per-lane export map from the
    # legacy per-lane keys PLUS the workbench session filed under the lane matching
    # its current stage (research → research lane; plan/build → plan lane) so the
    # one-session model exports just like the legacy per-lane sessions. The
    # session's per-stage docs persist under their own store lanes; the export
    # effort carries the joined docs for the chosen lane.
    dev_map = {k: v for k, v in raw_map.items() if k in PROMOTE_LANES}
    wsid, wrec = _grass_workbench_session(idea)
    if wsid:
        wstage = (wrec or {}).get("current_stage", "") if isinstance(wrec, dict) else ""
        wlane = "plan" if wstage in ("plan", "build") else "research"
        dev_map.setdefault(wlane, wsid)
    exported = []
    for lane in PROMOTE_LANES:
        sid = dev_map.get(lane)
        if not sid:
            continue
        # 1) Persist the develop session's produced docs into the main project
        #    (Wave-2 keystone) so the exported tile carries durable artifacts.
        #    Resolve the develop session's worktree from the registry when live.
        try:
            import session_registry as _sr
            rec = _sr.get_session(sid)
        except Exception:
            rec = None
        if rec is not None and rec.get("worktree_path"):
            try:
                persist_session_docs(folder_path, project_id, lane, sid,
                                     rec.get("worktree_path"))
            except Exception:
                pass

        # 2) The develop session's persisted docs in this lane (Wave-5 join).
        doc_efforts = efforts_for_session_id(folder_path, project_id, lane, sid)
        artifacts = [e.get("artifact_path", "") for e in doc_efforts
                     if e.get("artifact_path")]

        # 3) Record a REAL (run-source) board-visible lane session carrying those
        #    docs + a link back to the idea. Content-addressed id → idempotent.
        export_eid = "export-" + hashlib.sha1(
            ("%s|%s|%s" % (jid, lane, sid)).encode("utf-8")).hexdigest()[:16]
        extra = {
            "source": SOURCE_RUN,
            "kind": "export",
            "title": ("Exported from grass: " + title) if title else "Exported idea",
            "from_grass_idea": jid,
            "from_dev_session": sid,
            # v10 Wave 4 lineage (D8): stamp the originating grass idea on the
            # exported lane effort so every downstream project session in this
            # chain can trace back to the idea (the chain inheritance is wired in
            # terminal_session.start_session via grass_origin).
            "grass_origin": jid,
            "artifacts": list(artifacts),
            "status": "imported",
        }
        try:
            record_effort(folder_path, project_id, lane, export_eid, extra=extra)
        except Exception:
            continue
        # v10 Wave 4 (D8): stamp ``grass_origin`` on the dev session's registry
        # record so that any session started LATER with this session as its
        # ``parent_session_id`` INHERITS the origin (terminal_session.start_session
        # propagates a parent's grass_origin onto the child). Best-effort — a
        # failed stamp never blocks the export.
        try:
            import session_registry as _sr2
            if _sr2.get_session(sid) is not None:
                _sr2.update_session(sid, grass_origin=jid)
        except Exception:
            pass
        exported.append({
            "lane": lane,
            "session_id": sid,
            "export_effort_id": export_eid,
            "docs": list(artifacts),
        })

    if not exported:
        return {"ok": False, "exported": [], "reason": "no-develop-work"}

    # Mark the idea PROMOTED + store the export links on the idea record. The idea
    # stays in grass (copy, never destroy). Best-effort status set (a refined idea
    # → promoted is legal; an already-promoted one stays promoted).
    first = exported[0]
    try:
        set_grass_status(folder_path, project_id, jid, GRASS_PROMOTED,
                         promoted_to_session=first["session_id"],
                         promoted_to_lane=first["lane"])
    except Exception:
        pass
    with _journal.journaled(project_id, _journal.EV_GRASS_IDEA_EXPORTED,
                            correlation_id=(idea_id or project_id),
                            folder_path=folder_path,
                            payload={"idea_id": idea_id}):
        try:
            record_effort(folder_path, project_id, "grass", jid,
                          extra={"exported_to": exported})
        except Exception:
            pass
    return {"ok": True, "exported": exported, "reason": "ok"}


# ── Grass ARCHIVE: persist a dev session's docs + summary per-idea (v10 W4) ──
#
# D7 (locked): "archive" is a NEW VERB, DISTINCT from ``save_grass_refinement``
# (a versioned TEXT snapshot). Archiving a grass research/plan dev session:
#   1. PERSISTS the dev session's produced docs into the MAIN project (the v8
#      keystone :func:`persist_session_docs` — copy + commit), so the work
#      SURVIVES a session kill and is on disk + git;
#   2. captures/attaches the dev session's CACHED summary reference (read-only —
#      it never BLOCKS on a model run; a missing cache simply records no summary);
#   3. records a per-idea ARCHIVE BUNDLE on the idea record under ``archives``
#      (``[{lane, session_id, docs:[rel...], summary_ref, when}, ...]``; append,
#      newest-first on read), keyed to THAT idea.
# The idea STAYS in grass (copy, never destroy).


def list_grass_archives(folder_path, project_id: str, idea_id: str) -> list:
    """Return an idea's ARCHIVE bundles, **NEWEST-FIRST** (v10 Wave 4).

    Each bundle is ``{lane, session_id, docs:[rel...], summary_ref, when}``.
    Read off the idea pointer-record's ``archives`` list. Best-effort: a missing
    idea / field yields ``[]``. Never raises.
    """
    idea = get_grass_idea(folder_path, project_id, idea_id)
    if idea is None:
        return []
    arr = idea.get("archives")
    if not isinstance(arr, list):
        return []
    out = [a for a in arr if isinstance(a, dict)]
    out.sort(key=lambda a: float(a.get("when", 0) or 0), reverse=True)
    return out


def archive_grass_session(project_id: str, idea_id: str, lane: str,
                          folder_path=None) -> dict:
    """Archive a grass dev session's produced docs + summary into a per-idea bundle.

    The v10 Wave 4 "archive" verb (D7). For the idea's live/most-recent
    ``(idea, lane)`` develop session (from ``dev_sessions``) this:

      1. PERSISTS its produced docs into the MAIN project via
         :func:`persist_session_docs` (the v8 keystone: copy + commit — survives a
         later session kill) when the session's worktree is resolvable;
      2. resolves the session's now-persisted docs in this lane (the Wave-5
         :func:`efforts_for_session_id` join);
      3. attaches the session's CACHED summary reference if present (READ-ONLY —
         it does NOT block on a model run; a background summary may be triggered by
         the caller). The bundle records ``summary_ref`` =
         ``{"lane", "session_id"}`` so the UI can link
         ``/summary/<pid>/<lane>/<sid>``; ``has_summary`` reflects whether a cache
         exists right now;
      4. APPENDS a per-idea archive bundle (``{lane, session_id, docs, summary_ref,
         has_summary, when}``) to the idea record's ``archives`` list.

    The idea STAYS in grass (copy, never destroy). HONEST: when there is no dev
    session for this lane, or it produced no docs, returns
    ``{"ok": False, "reason": ...}`` and records nothing (no fabrication).

    Returns ``{"ok": bool, "archive": {...}|None, "reason": str}``. Raises
    ``ValueError`` for an unknown project, idea, or invalid lane.
    """
    lane = (lane or "").strip()
    if lane not in PROMOTE_LANES:
        raise ValueError(
            "archive lane must be one of %s, got %r"
            % (", ".join(PROMOTE_LANES), lane))
    if folder_path is None:
        proj = _rnd.get_project(project_id)
        if proj is None:
            raise ValueError("unknown project: %s" % (project_id,))
        folder_path = proj.get("folder_path", "")
    idea = get_grass_idea(folder_path, project_id, idea_id)
    if idea is None:
        raise ValueError("grass idea not found: %s" % (idea_id,))
    jid = idea.get("job_id", idea_id)

    dev_map = _grass_dev_sessions(idea)
    sid = dev_map.get(lane)
    if not sid:
        # v12 Wave 11: the one-session workbench keeps a SINGLE session under the
        # ``workbench`` key (it advances research→plan in-session, so it is not
        # filed under a per-lane key). Fall back to it for the Archive snapshot —
        # the session's docs persist under whichever stage's store lane they were
        # written in, but archiving records the bundle under the requested lane and
        # the doc-join resolves the actual persisted docs (so an empty join → the
        # honest "no-docs" path below). Only archive against the workbench session
        # for the lane matching its current stage (avoids a duplicate archive under
        # both research+plan for the same single session).
        wsid, wrec = _grass_workbench_session(idea)
        if wsid:
            cur = (wrec or {}).get("current_stage", "") if isinstance(wrec, dict) else ""
            if not cur or _resolve_subdir(lane) == _resolve_subdir(cur or "research"):
                sid = wsid
    if not sid:
        return {"ok": False, "archive": None, "reason": "no-dev-session"}

    # 1) Persist the dev session's produced docs into the main project (keystone).
    #    Resolve its worktree from the registry when live.
    try:
        import session_registry as _sr
        rec = _sr.get_session(sid)
    except Exception:
        rec = None
    if rec is not None and rec.get("worktree_path"):
        try:
            persist_session_docs(folder_path, project_id, lane, sid,
                                 rec.get("worktree_path"))
        except Exception:
            pass

    # 2) The session's now-persisted docs in this lane (the Wave-5 join).
    doc_efforts = efforts_for_session_id(folder_path, project_id, lane, sid)
    docs = [e.get("artifact_path", "") for e in doc_efforts
            if e.get("artifact_path")]
    if not docs:
        # Honest: nothing produced to archive — record nothing, no fabrication.
        return {"ok": False, "archive": None, "reason": "no-docs"}

    # 3) Attach the cached summary reference (read-only; never blocks on a model
    #    run). ``has_summary`` reflects whether a cache exists right now.
    has_summary = False
    try:
        import summarizer as _summ
        has_summary = (_summ.load_cached(folder_path, project_id, lane, sid)
                       is not None)
    except Exception:
        has_summary = False
    summary_ref = {"lane": _resolve_subdir(lane), "session_id": sid}

    archive = {
        "lane": _resolve_subdir(lane),
        "session_id": sid,
        "docs": list(docs),
        "summary_ref": summary_ref,
        "has_summary": bool(has_summary),
        "when": time.time(),
    }

    # 4) UPSERT the bundle on the idea record's ``archives`` list. v10 Wave 4
    #    FIX 4 — IDEMPOTENT on identical content: an archive is content-addressed
    #    by (lane, session_id, sorted(docs)). If a bundle with the SAME key already
    #    exists, we UPDATE it in place (refresh ``when`` + ``has_summary``) instead
    #    of appending a duplicate — so clicking Archive twice on the same unchanged
    #    session leaves exactly ONE bundle. A genuinely-different doc set (the
    #    session produced more docs) is a NEW key → appended (append-only history of
    #    distinct archives is preserved). The idea STAYS in grass.
    arch_key = (archive["lane"], archive["session_id"], tuple(sorted(docs)))
    try:
        existing = idea.get("archives")
        bundles = list(existing) if isinstance(existing, list) else []
        replaced = False
        for i, b in enumerate(bundles):
            if not isinstance(b, dict):
                continue
            bkey = (b.get("lane"), b.get("session_id"),
                    tuple(sorted(b.get("docs") or [])))
            if bkey == arch_key:
                # Same content → update in place (refresh when/summary), no dup.
                merged = dict(b)
                merged.update(archive)
                bundles[i] = merged
                archive = merged
                replaced = True
                break
        if not replaced:
            bundles.append(archive)
        with _journal.journaled(project_id, _journal.EV_GRASS_IDEA_ARCHIVED,
                                correlation_id=(idea_id or project_id),
                                folder_path=folder_path,
                                payload={"idea_id": idea_id, "lane": lane}):
            record_effort(folder_path, project_id, "grass", jid,
                          extra={"archives": bundles})
    except Exception:
        return {"ok": False, "archive": None, "reason": "record-failed"}

    return {"ok": True, "archive": archive, "reason": "ok"}


# ── Honest brownfield discovery: adopt + reconcile (Wave 2) ─────────────────

def discovered_job_id(lane: str, rel: str) -> str:
    """Stable, content-addressed job_id for a discovered artifact.

    Derived purely from the (store) lane + the artifact's folder-relative path,
    so adopting the same artifact twice yields the SAME job_id (idempotent
    rescans — no duplicates). Never random.
    """
    h = hashlib.sha1(f"{_resolve_subdir(lane)}::{rel}".encode("utf-8")).hexdigest()
    return f"{DISCOVERED_PREFIX}{h[:16]}"


def is_discovered(rec: dict) -> bool:
    """True iff a pointer-record was discovered (brownfield), not Anchor-run."""
    return bool(rec) and rec.get("source") == SOURCE_DISCOVERED


def _delete_effort_record(folder_path, project_id: str, lane: str,
                          job_id: str) -> bool:
    """Remove ONE pointer-record + drop its id from the index (under lock).

    Only ever called for DISCOVERED records during reconciliation — real efforts
    are never pruned. Returns True if a record was removed.
    """
    with _paths.WRITE_LOCK:
        ppath = _pointer_path(folder_path, project_id, lane, job_id)
        removed = False
        try:
            if ppath.exists():
                ppath.unlink()
                removed = True
        except OSError:
            pass
        order = _load_index(folder_path, project_id, lane)
        if job_id in order:
            order = [j for j in order if j != job_id]
            _save_index(folder_path, project_id, lane, order)
            removed = True
        return removed


#: Subdir under a lane store dir holding per-session cached summaries. Mirrors
#: ``summarizer.SUMMARIES_DIRNAME`` (kept here so :func:`delete_session_efforts`
#: can remove the cached summary dir WITHOUT importing ``summarizer`` — which
#: would create an import cycle, since summarizer imports this module).
SUMMARIES_DIRNAME = "summaries"


def _safe_session_segment(seg: str) -> str:
    """Filesystem-safe form of a session_id for the summaries dir name.

    MUST match ``summarizer._safe_segment`` so the summary dir this computes is
    the SAME one summarizer writes (a managed session id can contain ``::``)."""
    import re as _re
    return _re.sub(r"[^A-Za-z0-9._-]+", "_", str(seg or "")) or "session"


def session_summary_dir(folder_path, project_id: str, lane: str,
                        session_id: str) -> Path:
    """``<lane>/summaries/<safe-session-id>/`` — the cached-summary dir.

    The same path ``summarizer.summary_dir`` resolves to; recomputed here to
    avoid an import cycle (summarizer → effort_history)."""
    return (lane_dir(folder_path, project_id, lane)
            / SUMMARIES_DIRNAME / _safe_session_segment(session_id))


def delete_session_efforts(folder_path, project_id: str, lane: str,
                           session_id: str) -> dict:
    """TRUE session delete (v9 Wave 1) — remove a session's Anchor-side stores.

    For ``session_id`` in ``lane`` this removes, BEST-EFFORT + IDEMPOTENT:

      1. every effort **pointer-record** tagged with this session_id (the v8
         join, :func:`efforts_for_session_id`) AND its **index.json** entry
         (via :func:`_delete_effort_record`);
      2. the cached **summary dir** ``<lane>/summaries/<sid>/``.

    It deliberately **does NOT remove the produced documents** (Option A): the
    persisted plan/research/build files stay in the project folder/git — only the
    Anchor effort *pointer-records* (which reference them) and the cached summary
    are dropped. So ``list_efforts``/``sessions.list_sessions`` no longer surface
    the session, but the committed work on disk is untouched.

    Never raises. Returns ``{"ok", "removed_efforts": [job_id...],
    "summary_removed": bool}``.
    """
    removed = []
    summary_removed = False
    try:
        store_lane = _resolve_subdir(lane)
        # 1) Drop every session-tagged effort pointer-record + its index entry.
        try:
            tagged = efforts_for_session_id(folder_path, project_id, store_lane,
                                            session_id)
        except Exception:
            tagged = []
        for eff in tagged:
            jid = (eff.get("job_id") or "").strip()
            if not jid:
                continue
            try:
                if _delete_effort_record(folder_path, project_id, store_lane, jid):
                    removed.append(jid)
            except Exception:
                pass
        # 2) Remove the cached summary dir (best-effort; tolerate already-gone).
        try:
            sdir = session_summary_dir(folder_path, project_id, store_lane,
                                       session_id)
            if sdir.is_dir():
                shutil.rmtree(str(sdir), ignore_errors=True)
                summary_removed = not sdir.exists()
        except Exception:
            summary_removed = False
    except Exception:
        pass
    return {
        "ok": True,
        "removed_efforts": removed,
        "summary_removed": summary_removed,
    }


def adopt_discovered(folder_path, project_id: str, scan_result) -> dict:
    """Create/update DISCOVERED pointer-records for a folder's scanned artifacts.

    For every adoptable artifact in ``scan_result.by_lane`` (research / planning /
    build / deliverables) this upserts a pointer-record with:
      - a STABLE path-hash ``job_id`` (idempotent: rescans never duplicate),
      - ``source="discovered"``,
      - ``created_at`` = the artifact's mtime,
      - real ``title`` / ``kind`` / ``artifact_path`` (folder-relative),
      - NO cost / tokens / session_id (honesty contract).

    Then RECONCILES: any *previously discovered* record in those lanes whose
    artifact is no longer present in this scan is PRUNED (discovered records are
    derived). Real (run) efforts are NEVER touched. Returns a small report.

    All writes run under ``paths.WRITE_LOCK``.
    """
    adopted = []
    pruned = []
    with _paths.WRITE_LOCK:
        by_lane = getattr(scan_result, "by_lane", None) or {}
        for store_lane, artifacts in by_lane.items():
            # Desired discovered job_ids for this lane after this scan.
            desired = {}
            for art in artifacts:
                rel = art.get("rel", "")
                if not rel:
                    continue
                jid = discovered_job_id(store_lane, rel)
                desired[jid] = art
            # Upsert each desired discovered record.
            for jid, art in desired.items():
                extra = {
                    "source": SOURCE_DISCOVERED,
                    "kind": art.get("kind", ""),
                    "title": art.get("title", ""),
                    "artifact_path": art.get("rel", ""),
                    "status": "imported",
                }
                # created_at from the artifact mtime (real metadata only).
                rec = record_effort(folder_path, project_id, store_lane, jid,
                                    extra=extra)
                # Force created_at to the artifact mtime (record_effort defaults
                # to now() only when absent; ensure it reflects on-disk reality).
                mtime = art.get("mtime")
                if mtime:
                    rec = _set_created_at(folder_path, project_id, store_lane,
                                          jid, float(mtime))
                adopted.append(rec)
            # Reconcile: prune discovered records in this lane not in `desired`.
            for existing in list_efforts(folder_path, project_id, store_lane):
                if not is_discovered(existing):
                    continue  # never touch real efforts
                ejid = existing.get("job_id", "")
                if ejid and ejid not in desired:
                    if _delete_effort_record(folder_path, project_id,
                                             store_lane, ejid):
                        pruned.append(ejid)
        # Reconcile lanes that had discovered records but appear with ZERO
        # artifacts in this scan (handled by the loop above only if the lane key
        # is present in by_lane; ensure all standard lanes are reconciled).
        scanned_lanes = set(by_lane.keys())
        for store_lane in ROLLUP_LANES:
            if store_lane in scanned_lanes:
                continue
            for existing in list_efforts(folder_path, project_id, store_lane):
                if is_discovered(existing):
                    ejid = existing.get("job_id", "")
                    if ejid and _delete_effort_record(folder_path, project_id,
                                                      store_lane, ejid):
                        pruned.append(ejid)
    return {"adopted": len(adopted), "pruned": len(pruned),
            "pruned_ids": pruned}


def _set_created_at(folder_path, project_id: str, lane: str, job_id: str,
                    ts: float) -> dict:
    """Stamp ``created_at`` on an existing pointer-record (under lock)."""
    with _paths.WRITE_LOCK:
        ppath = _pointer_path(folder_path, project_id, lane, job_id)
        if not ppath.exists():
            return {}
        try:
            rec = json.loads(ppath.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        rec["created_at"] = ts
        _paths.atomic_write_text(
            ppath, json.dumps(rec, indent=2, ensure_ascii=False))
        return rec


def reconcile_discovered(folder_path, project_id: str) -> dict:
    """Prune DISCOVERED records whose on-disk artifact no longer exists.

    Independent of a fresh scan: checks each discovered record's
    ``artifact_path`` against the folder and removes the record if the file is
    gone. Real efforts are never touched. Returns ``{"pruned": n,
    "pruned_ids": [...]}``.
    """
    pruned = []
    folder = Path(folder_path)
    with _paths.WRITE_LOCK:
        for store_lane in ROLLUP_LANES:
            for existing in list_efforts(folder_path, project_id, store_lane):
                if not is_discovered(existing):
                    continue
                rel = existing.get("artifact_path", "")
                exists = False
                if rel:
                    try:
                        exists = (folder / rel).exists()
                    except OSError:
                        exists = False
                if not exists:
                    ejid = existing.get("job_id", "")
                    if ejid and _delete_effort_record(folder_path, project_id,
                                                      store_lane, ejid):
                        pruned.append(ejid)
    return {"pruned": len(pruned), "pruned_ids": pruned}


# ── Sibling-store adoption (Wave 2: folder-history unification) ──────────────

def _projects_root(folder_path) -> Path:
    """``<folder>/.anchor/projects/`` — the parent of every per-project store."""
    return Path(folder_path) / ".anchor" / "projects"


def sibling_store_ids(folder_path, exclude_id: str = None) -> list:
    """Project-ids that have an on-disk store under THIS folder's ``.anchor``.

    Reads ``<folder>/.anchor/projects/*`` directory names — these are the
    project-ids whose effort stores physically live alongside ``exclude_id`` for
    the SAME folder. ``exclude_id`` (typically the target/active id) is omitted.

    This is how sibling adoption finds same-folder stores: trio runs recorded
    under one project-id's store are invisible to a sibling id for the same
    folder until they are adopted across. Best-effort: a missing/unreadable
    ``.anchor`` yields ``[]``. Returns sorted ids for determinism.
    """
    root = _projects_root(folder_path)
    out = []
    try:
        if not root.is_dir():
            return []
        for child in root.iterdir():
            try:
                if child.is_dir() and child.name and child.name != exclude_id:
                    out.append(child.name)
            except OSError:
                continue
    except OSError:
        return []
    return sorted(out)


def _import_record_into(folder_path, target_id: str, lane: str,
                        rec: dict) -> dict:
    """Upsert ONE sibling effort-record into ``target_id``'s lane store.

    The record is imported as a DISCOVERED (imported) effort so it never
    fabricates cost into the target's real-effort rollup (honesty contract).
    Its identity (``job_id``) is preserved so re-importing is idempotent — the
    same sibling effort never duplicates under the target. Real run-cost is kept
    as readable metadata but the record is flagged discovered for rollups.
    Returns the stored record.
    """
    jid = (rec.get("job_id") or "").strip()
    if not jid:
        # Stable fallback id from the record's identity so re-import is idempotent.
        h = hashlib.sha1(
            "\x00".join(str(rec.get(k, "")) for k in
                        ("artifact_path", "created_at", "skill", "kind",
                         "title")).encode("utf-8")).hexdigest()
        jid = f"{DISCOVERED_PREFIX}sib-{h[:16]}"
    extra = {k: v for k, v in rec.items()
             if k not in ("job_id", "project_id", "lane")}
    # Mark as imported (folded-in) history; preserve the original provenance and
    # owning id so the move is auditable and rollups stay honest.
    extra.setdefault("imported_from", rec.get("project_id", ""))
    extra["source"] = SOURCE_DISCOVERED
    stored = record_effort(folder_path, target_id, lane, jid, extra=extra)
    ca = rec.get("created_at")
    if ca:
        try:
            stored = _set_created_at(folder_path, target_id, lane, jid,
                                     float(ca))
        except (TypeError, ValueError):
            pass
    return stored


def adopt_sibling_sessions(folder_path, target_id: str,
                           source_ids=None) -> dict:
    """Fold sibling project-ids' real efforts into ``target_id`` as imported.

    For each sibling id (default: every OTHER on-disk store under this folder),
    every effort in every CONTENT lane (:data:`FOLD_LANES` — the rollup lanes
    PLUS the cost-free ``grass`` ideas lane) is upserted into ``target_id``'s
    matching lane store via :func:`_import_record_into`. Folding the grass lane
    too means manually-added / adopted grass IDEAS are migrated before any
    hard-delete and are never silently lost. The target therefore SEES trio
    work that was originally recorded under a different project-id for the SAME
    folder — fixing the bug where research run under one id is invisible to a
    sibling id for the same folder.

    Idempotent: importing the same sibling effort twice does not duplicate it
    (job_id-keyed upsert). The sibling stores are NOT modified or deleted here —
    that hard-delete is the explicit, reviewable :func:`rnd_registry.reconcile_folder`
    step. Returns ``{"imported": n, "from": [...], "by_lane": {...}}``.

    All writes run under ``paths.WRITE_LOCK``.
    """
    if source_ids is None:
        source_ids = sibling_store_ids(folder_path, exclude_id=target_id)
    else:
        source_ids = [s for s in source_ids if s and s != target_id]
    imported = 0
    by_lane = {lane: 0 for lane in FOLD_LANES}
    used_sources = []
    with _paths.WRITE_LOCK:
        for sid in source_ids:
            touched = False
            for store_lane in FOLD_LANES:
                for rec in list_efforts(folder_path, sid, store_lane):
                    _import_record_into(folder_path, target_id, store_lane, rec)
                    imported += 1
                    by_lane[store_lane] += 1
                    touched = True
            if touched:
                used_sources.append(sid)
    return {"imported": imported, "from": used_sources, "by_lane": by_lane}


# ── Attaching cost from a completed job's result envelope ───────────────────

def attach_cost(folder_path, project_id: str, lane: str, job_id: str,
                job_record: dict) -> dict:
    """Stamp the completed job's cost/usage/duration onto its effort record.

    ``job_record`` is the durable record from ``job_runner`` (which captured the
    stream-json ``result`` envelope into ``record["cost"]``). The cost block —
    ``total_cost_usd`` / tokens / ``duration_ms`` — is copied onto the effort
    pointer-record and the report-artifact presence (report.md / report.pdf) is
    refreshed. Returns the updated effort record.
    """
    cost = (job_record or {}).get("cost") or {}
    raw_total = cost.get("total_cost_usd")
    preserves_unknown_cost = (
        raw_total is None and
        cost.get("cost_state") in ("subscription_covered", "no_seat_started")
    )
    if preserves_unknown_cost:
        total_cost = None
    else:
        try:
            total_cost = float(raw_total or 0.0)
        except (TypeError, ValueError):
            total_cost = 0.0
    cost_block = {
        "total_cost_usd": total_cost,
        "duration_ms": int(cost.get("duration_ms", 0) or 0),
        "input_tokens": int(cost.get("input_tokens", 0) or 0),
        "cached_input_tokens": int(cost.get("cached_input_tokens", 0) or 0),
        "output_tokens": int(cost.get("output_tokens", 0) or 0),
        "total_tokens": int(cost.get("total_tokens", 0) or 0),
    }
    for key in ("billing_mode", "cost_state"):
        if isinstance(cost.get(key), str) and cost[key]:
            cost_block[key] = cost[key]
    extra = {
        "status": (job_record or {}).get("status"),
        "cost": cost_block,
        "session_id": (job_record or {}).get("session_id"),
        "finished_at": (job_record or {}).get("finished_at"),
        "artifacts": detect_artifacts(folder_path, project_id, lane, job_id),
    }
    return record_effort(folder_path, project_id, lane, job_id, extra=extra)


def detect_artifacts(folder_path, project_id: str, lane: str,
                     job_id: str = None) -> dict:
    """Report which report artifacts exist for an effort's lane dir.

    The viewer's PDF-default detection keys off this. Artifacts for an effort
    live either directly in the lane dir (single-effort convenience) or under an
    effort-scoped ``efforts/<job_id>/`` dir. Both are checked; the effort-scoped
    location wins when present.

    Returns ``{"report_md": bool, "report_pdf": bool, "md_path": str|None,
    "pdf_path": str|None}``.
    """
    ld = lane_dir(folder_path, project_id, lane)
    candidates = []
    if job_id:
        candidates.append(efforts_dir(folder_path, project_id, lane) / job_id)
    candidates.append(ld)
    md_path = None
    pdf_path = None
    for base in candidates:
        m = base / REPORT_MD
        p = base / REPORT_PDF
        if md_path is None and m.exists():
            md_path = m
        if pdf_path is None and p.exists():
            pdf_path = p
    return {
        "report_md": md_path is not None,
        "report_pdf": pdf_path is not None,
        "md_path": str(md_path) if md_path else None,
        "pdf_path": str(pdf_path) if pdf_path else None,
    }


# ── Cost rollups: per-effort → per-lane → per-project ───────────────────────

def _empty_rollup() -> dict:
    return {
        "total_cost_usd": 0.0,
        "duration_ms": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "effort_count": 0,
        # Discovered (brownfield-imported) efforts are counted SEPARATELY and
        # NEVER contribute to effort_count / cost (honesty contract). They carry
        # no real cost, so discovered_cost is always 0.
        "discovered_count": 0,
        "discovered_cost": 0.0,
    }


def _add_cost(acc: dict, cost: dict) -> None:
    raw_total = cost.get("total_cost_usd")
    billing_mode = cost.get("billing_mode")
    cost_state = cost.get("cost_state")
    is_unpriced_subscription = (
        raw_total is None and
        cost_state == "subscription_covered"
    )
    if raw_total is not None:
        try:
            if acc.get("total_cost_usd") is None:
                acc["total_cost_usd"] = 0.0
            acc["total_cost_usd"] += float(raw_total)
            acc["_priced_cost_count"] = acc.get("_priced_cost_count", 0) + 1
        except (TypeError, ValueError):
            pass
    if billing_mode or cost_state:
        for plural, value in (("billing_modes", billing_mode),
                              ("cost_states", cost_state)):
            if isinstance(value, str) and value:
                values = acc.setdefault(plural, [])
                if value not in values:
                    values.append(value)
                    values.sort()
    if is_unpriced_subscription:
        acc["unpriced_subscription_count"] = \
            acc.get("unpriced_subscription_count", 0) + 1
    acc["duration_ms"] += int(cost.get("duration_ms", 0) or 0)
    acc["input_tokens"] += int(cost.get("input_tokens", 0) or 0)
    acc["output_tokens"] += int(cost.get("output_tokens", 0) or 0)
    acc["total_tokens"] += int(cost.get("total_tokens", 0) or 0)


def _finalize_cost_metadata(acc: dict) -> dict:
    """Finish optional cost-state metadata without changing legacy shapes."""
    priced = int(acc.pop("_priced_cost_count", 0) or 0)
    unpriced = int(acc.get("unpriced_subscription_count", 0) or 0)
    classified = bool(acc.get("billing_modes") or acc.get("cost_states") or unpriced)
    if classified:
        acc["priced_cost_count"] = priced
    if unpriced and priced == 0:
        acc["total_cost_usd"] = None
    return acc


def effort_cost(effort: dict) -> dict:
    """Return one effort's cost block (zero-filled if it has none yet)."""
    cost = (effort or {}).get("cost") or {}
    out = _empty_rollup()
    out["effort_count"] = 1
    _add_cost(out, cost)
    return _finalize_cost_metadata(out)


def lane_rollup(folder_path, project_id: str, lane: str) -> dict:
    """Aggregate cost across the REAL efforts in a lane (per-lane rollup).

    Honesty contract: DISCOVERED (brownfield-imported) efforts are EXCLUDED from
    ``effort_count`` and cost; they are tallied separately in
    ``discovered_count`` (and ``discovered_cost`` is always 0). ``list_efforts``
    still returns them for rendering — only this rollup excludes them.
    """
    acc = _empty_rollup()
    for effort in list_efforts(folder_path, project_id, lane):
        if is_discovered(effort):
            acc["discovered_count"] += 1
            continue
        cost = effort.get("cost") or {}
        _add_cost(acc, cost)
        acc["effort_count"] += 1
    return _finalize_cost_metadata(acc)


#: The lanes whose efforts roll up into the project total.
#:
#: 2026-07-26: ``general`` (the bare "Open terminal" lane — the DAILY driver),
#: ``zombie`` and ``gandalf`` were missing, so every run-cost record written in
#: those lanes was structurally unreachable by every rollup FOREVER. Real
#: measured usage sat on disk (one general-lane record: 2,757,886 tokens /
#: 444,813 ms) while the UI reported zero. ``grass`` stays out: grass ideas
#: carry no cost of their own (their dev sessions live in research/planning).
ROLLUP_LANES = ("research", "planning", "build", "deliverables",
                "general", "zombie", "gandalf")


def project_rollup(project_id: str, folder_path=None) -> dict:
    """Aggregate cost across every lane of a project (per-project rollup).

    Returns ``{"total": <rollup>, "lanes": {lane: <rollup>}}`` so the tile can
    show the project total and the dashboard can show the per-lane breakdown.
    If ``folder_path`` is omitted it is resolved from the registry.
    """
    if folder_path is None:
        proj = _rnd.get_project(project_id)
        folder_path = (proj or {}).get("folder_path", "")
    total = _empty_rollup()
    lanes_out = {}
    for lane in ROLLUP_LANES:
        lr = lane_rollup(folder_path, project_id, lane)
        lanes_out[lane] = lr
        if lr.get("total_cost_usd") is not None:
            if total.get("total_cost_usd") is None:
                total["total_cost_usd"] = 0.0
            total["total_cost_usd"] += float(lr.get("total_cost_usd") or 0.0)
            if lr.get("effort_count"):
                total["_priced_cost_count"] = total.get("_priced_cost_count", 0) + \
                    int(lr.get("priced_cost_count", lr.get("effort_count", 0)) or 0)
        for plural in ("billing_modes", "cost_states"):
            for value in (lr.get(plural) or []):
                values = total.setdefault(plural, [])
                if value not in values:
                    values.append(value)
                    values.sort()
        if lr.get("unpriced_subscription_count"):
            total["unpriced_subscription_count"] = \
                total.get("unpriced_subscription_count", 0) + \
                int(lr.get("unpriced_subscription_count") or 0)
        total["duration_ms"] += lr["duration_ms"]
        total["input_tokens"] += lr["input_tokens"]
        total["output_tokens"] += lr["output_tokens"]
        total["total_tokens"] += lr["total_tokens"]
        total["effort_count"] += lr["effort_count"]
        total["discovered_count"] += lr["discovered_count"]
    return {"total": _finalize_cost_metadata(total), "lanes": lanes_out}


# ── Project cost/tokens/time rollup over RUN sessions (v4 Wave 3) ───────────
#
# The v4 cockpit shows a per-project ``Σ tokens · $ · time`` rollup with a
# lifetime / 30-day toggle. Unlike :func:`project_rollup` (which sums every real
# effort), this rollup is SESSION-SCOPED and honesty-bounded:
#
#   - It sums ``job_runner`` COST RECORDS for the project's RUN-PROVENANCE
#     sessions ONLY (``sessions.list_sessions`` groups efforts into sessions and
#     tags each ``provenance`` = "run" | "imported"). IMPORTED / DISCOVERED
#     sessions contribute ZERO — never fabricated.
#   - ``window='30d'`` excludes cost records older than 30 days relative to
#     ``now`` (injectable for deterministic tests; defaults to real ``time``).
#
# Returns ``{"tokens", "cost_usd", "wall_clock_ms", "sessions"}`` where
# ``sessions`` is the count of RUN sessions that contributed at least one
# in-window member. Stdlib only.

#: Seconds in the 30-day rolling window.
WINDOW_30D_SECONDS = 30 * 24 * 60 * 60.0

#: Accepted ``window`` values for :func:`project_effort_rollup`.
WINDOW_LIFETIME = "lifetime"
WINDOW_30D = "30d"


def _member_when(member: dict) -> float:
    """A member's cost timestamp for windowing: ``finished_at`` else ``created_at``.

    ``attach_cost`` stamps ``finished_at`` (job completion) alongside the cost
    block; we prefer it as the "when this cost was incurred" time and fall back
    to the effort's ``created_at`` (launch time) when a finish time is absent.
    Returns 0.0 when neither is parseable.
    """
    for key in ("finished_at", "created_at"):
        val = member.get(key)
        if val in (None, ""):
            continue
        try:
            return float(val)
        except (TypeError, ValueError):
            continue
    return 0.0


def project_effort_rollup(project_id: str, window: str = WINDOW_LIFETIME,
                          now=None, folder_path=None) -> dict:
    """Per-project cost/tokens/time rollup over RUN sessions (v4 Wave 3).

    Sums ``job_runner`` cost records for the project's RUN-provenance sessions
    only (imported/discovered sessions contribute 0 — never fabricated). With
    ``window='30d'`` only cost records whose timestamp is within the last 30 days
    of ``now`` are counted; ``window='lifetime'`` (default) counts all of them.

    ``now`` is injectable (a float epoch) for deterministic tests; it defaults to
    the real clock. ``folder_path`` is resolved from the registry when omitted
    (mirrors :func:`project_rollup`).

    Returns ``{"tokens": int, "cost_usd": float, "wall_clock_ms": int,
    "sessions": int}`` where ``sessions`` is the number of RUN sessions that
    contributed at least one in-window cost record. Stdlib only; never raises.
    """
    if folder_path is None:
        proj = _rnd.get_project(project_id)
        folder_path = (proj or {}).get("folder_path", "")
    cutoff = None
    if window == WINDOW_30D:
        ref = float(now) if now is not None else time.time()
        cutoff = ref - WINDOW_30D_SECONDS

    # Lazy import to avoid the sessions↔effort_history cycle at module load.
    import sessions as _sessions

    tokens = 0
    cost_usd = 0.0
    wall_clock_ms = 0
    session_count = 0
    billing_modes = set()
    cost_states = set()
    priced_cost_count = 0
    unpriced_subscription_count = 0
    seen_cost_records = set()
    for lane in ROLLUP_LANES:
        try:
            lane_sessions = _sessions.list_sessions(folder_path, project_id, lane)
        except Exception:
            lane_sessions = []
        for sess in lane_sessions:
            # RUN-provenance only — imported/discovered sessions add nothing.
            if (sess.get("provenance") or "") != _sessions.PROV_RUN:
                continue
            contributed = False
            for member in (sess.get("member_files", []) or []):
                # Defensive: skip any discovered member inside a run session
                # (it carries no real cost — honesty contract).
                if is_discovered(member):
                    continue
                if cutoff is not None and _member_when(member) < cutoff:
                    continue
                member_key = (lane, str(member.get("job_id") or ""))
                if member_key[1]:
                    if member_key in seen_cost_records:
                        continue
                    seen_cost_records.add(member_key)
                cost = member.get("cost") or {}
                m_tokens = int(cost.get("total_tokens", 0) or 0)
                if not m_tokens:
                    m_tokens = (int(cost.get("input_tokens", 0) or 0)
                                + int(cost.get("output_tokens", 0) or 0))
                m_wall = int(cost.get("duration_ms", 0) or 0)
                # Count wall-clock-only unmeasured rows (Grok / no sidecar) as
                # contributing sessions even when tokens stay 0.
                if not m_tokens and not m_wall:
                    continue
                tokens += m_tokens
                wall_clock_ms += m_wall
                billing_mode = cost.get("billing_mode")
                cost_state = cost.get("cost_state")
                if isinstance(billing_mode, str) and billing_mode:
                    billing_modes.add(billing_mode)
                if isinstance(cost_state, str) and cost_state:
                    cost_states.add(cost_state)
                raw_cost = cost.get("total_cost_usd")
                if raw_cost is None and cost_state == "subscription_covered":
                    unpriced_subscription_count += 1
                elif raw_cost is not None:
                    try:
                        cost_usd += float(raw_cost)
                        priced_cost_count += 1
                    except (TypeError, ValueError):
                        pass
                contributed = True
            if contributed:
                session_count += 1
    out = {
        "tokens": tokens,
        "cost_usd": (None if unpriced_subscription_count and not priced_cost_count
                     else round(cost_usd, 6)),
        "wall_clock_ms": wall_clock_ms,
        "sessions": session_count,
    }
    if billing_modes or cost_states or unpriced_subscription_count:
        out.update(
            billing_modes=sorted(billing_modes),
            cost_states=sorted(cost_states),
            priced_cost_count=priced_cost_count,
            unpriced_subscription_count=unpriced_subscription_count,
        )
    return out


# ── C9: per-effort auto-commit of the .anchor/ pointer-record ───────────────

def _git(folder: Path, *args, check=False, timeout=30) -> subprocess.CompletedProcess:
    """Run a git subcommand scoped to ``folder`` (``-C <folder>``).

    Never touches any repo other than ``folder``. ``check`` raises on non-zero.
    """
    cmd = ["git", "-C", str(folder), *args]
    return subprocess.run(cmd, capture_output=True, text=True,
                          check=check, timeout=timeout,
                          creationflags=_paths.NO_WINDOW)


def _is_git_repo(folder: Path) -> bool:
    return (folder / ".git").exists()


def _is_anchor_repo(folder: Path, code: Path) -> bool:
    """True if ``folder`` is the Anchor code repo root (must not be committed).

    Compares the resolved path equality and, when both exist, also uses
    ``os.path.samefile`` to catch path aliasing (case differences, short paths,
    symlinks) so the guard cannot be sidestepped by an alternate spelling.
    """
    try:
        if folder.resolve() == code:
            return True
    except OSError:
        pass
    try:
        import os
        if folder.exists() and code.exists() and os.path.samefile(folder, code):
            return True
    except OSError:
        pass
    return False


def auto_commit_effort(folder_path, project_id: str, lane: str, job_id: str,
                       allow_init: bool = False) -> dict:
    """Auto-commit ONE effort's ``.anchor/`` pointer-record (C9, AC4).

    Commits exactly the effort's pointer-record + the lane index (the small,
    git-trackable files) in the PROJECT'S OWN folder repo — one commit per
    finalized effort. The ``.anchor/.gitignore`` tracking policy keeps raw
    logs / PDFs / jobs OUT of the commit (they are ignored), so only the
    pointer-records land in git (reconciling C9 git-trackable with C10 no-leak).

    SCOPE GUARANTEE: every git invocation is ``git -C <folder_path> ...`` — the
    commit is scoped strictly to the project's folder. This function must only
    ever be pointed at a project folder (a tmp repo in tests), NEVER the Anchor
    repo. It does NOT init a repo unless ``allow_init`` is explicitly set, and it
    never pushes.

    Returns ``{"committed": bool, "reason": str, "commit": <sha>|None}``.
    """
    folder = Path(folder_path)
    if not folder.exists():
        return {"committed": False, "reason": "folder-missing", "commit": None}

    # SCOPE GUARD (C9): never auto-commit the Anchor code repo itself. If the
    # project folder resolves to the Anchor code dir (e.g. Anchor dogfood-
    # registered with folder_path == C:\dev\Anchor), refuse outright — do not
    # stage or commit anything.
    code = _paths.CODE_DIR.resolve()
    if _is_anchor_repo(folder, code):
        return {"committed": False, "reason": "refused-anchor-repo",
                "commit": None}

    if not _is_git_repo(folder):
        if not allow_init:
            return {"committed": False, "reason": "not-a-git-repo", "commit": None}
        try:
            _git(folder, "init", check=True)
        except (OSError, subprocess.SubprocessError):
            return {"committed": False, "reason": "init-failed", "commit": None}

    # Paths to stage: this effort's pointer-record + the lane index. Both are
    # small git-trackable pointer files (the .gitignore allow-list re-includes
    # *.pointer.json and index.json even though jobs/logs/pdf are ignored).
    ppath = _pointer_path(folder, project_id, lane, job_id)
    ipath = _index_path(folder, project_id, lane)
    rel_targets = []
    for p in (ppath, ipath):
        if p.exists():
            try:
                rel_targets.append(str(p.relative_to(folder)))
            except ValueError:
                rel_targets.append(str(p))
    if not rel_targets:
        return {"committed": False, "reason": "nothing-to-commit", "commit": None}

    with _paths.WRITE_LOCK:
        # Stage only the pointer-record + index (respecting .gitignore via -f only
        # where the allow-list re-includes them; they are NOT ignored, so a plain
        # add suffices and ignored siblings are never staged).
        try:
            _git(folder, "add", "--", *rel_targets, check=True)
        except (OSError, subprocess.SubprocessError):
            return {"committed": False, "reason": "add-failed", "commit": None}

        # If nothing is actually staged (e.g. unchanged), report no-op rather
        # than producing an empty commit.
        diff = _git(folder, "diff", "--cached", "--name-only")
        if not (diff.stdout or "").strip():
            return {"committed": False, "reason": "no-staged-changes",
                    "commit": None}

        msg = f"anchor: effort {lane}/{job_id} ({project_id})"
        # Identity is set locally on the project repo so the commit never depends
        # on global git config (and never touches the Anchor repo's config).
        env_args = [
            "-c", "user.name=Anchor",
            "-c", "user.email=anchor@localhost",
            "-c", "commit.gpgsign=false",
        ]
        try:
            r = subprocess.run(
                ["git", "-C", str(folder), *env_args, "commit",
                 "--no-verify", "-m", msg, "--", *rel_targets],
                capture_output=True, text=True, timeout=30,
                creationflags=_paths.NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            return {"committed": False, "reason": "commit-failed", "commit": None}
        if r.returncode != 0:
            return {"committed": False, "reason": "commit-nonzero",
                    "commit": None, "stderr": r.stderr}

        sha = _git(folder, "rev-parse", "HEAD")
        return {"committed": True, "reason": "ok",
                "commit": (sha.stdout or "").strip()}


def finalize_effort(folder_path, project_id: str, lane: str, job_id: str,
                    job_record: dict, auto_commit: bool = True,
                    allow_init: bool = False) -> dict:
    """Finalize a completed effort: attach cost, then auto-commit (one commit).

    The single entry point a caller uses when a job reaches a terminal status:
    1. Attach the job's result-envelope cost/usage/duration onto the effort
       pointer-record (and refresh artifact presence).
    2. Auto-commit that pointer-record (C9, AC4) — scoped to the project folder.

    Returns ``{"effort": <record>, "commit": <auto_commit_effort result>}``.
    """
    effort = attach_cost(folder_path, project_id, lane, job_id, job_record)
    commit = {"committed": False, "reason": "skipped", "commit": None}
    if auto_commit:
        commit = auto_commit_effort(folder_path, project_id, lane, job_id,
                                    allow_init=allow_init)
    return {"effort": effort, "commit": commit}


# ── Session document persistence (v8 Wave 2 — THE KEYSTONE) ──────────────────
#
# Trio sessions run in a throwaway git WORKTREE; Anchor historically committed
# only the tiny ``.pointer.json`` metadata, so the actual documents a session
# produced (MASTER-PLAN.md, the research report, EXECUTION-LOG, …) were DELETED
# when the worktree was reaped on kill — the build worktree (off main HEAD)
# couldn't find the plan, ``discover_recent_plan_set`` (reads the main folder)
# came up empty, and killing a session lost the work.
#
# ``persist_session_docs`` closes that gap: BEFORE the worktree is reaped it
# collects the documents the session produced in its worktree, COPIES them into
# the MAIN project folder at the same relative paths, COMMITS them (scoped — only
# the produced docs + the effort pointer/index, NEVER ``git add -A`` and never the
# user's unrelated changes) in the project's OWN repo, and records a per-doc
# DISCOVERED effort whose ``artifact_path`` is the main-folder-relative path so
# ``list_efforts`` / ``sessions.list_sessions`` / ``discover_recent_plan_set``
# resolve them in the main folder. Idempotent (content-addressed effort ids +
# git's "nothing staged" no-op) and best-effort (never raises into the kill path).

#: Top-level worktree directories whose produced docs we persist into the main
#: project. The trio writes its docs under these lane output dirs. ``general`` is
#: included (2026-07-07) so a bare "Open terminal" general session's produced docs
#: — its autosaved transcript + RESTART.md, and any .md it writes under general/ —
#: are persisted like any trio lane's; without it a general session (John's
#: runaway case) stranded everything it generated. The sweep is git-diff-scoped to
#: the session's own isolated worktree, so only session-produced general/ docs match.
_DOC_DIRS = ("planning", "research", "build", "deliverables", "general")

#: Directories we NEVER sweep, even if git reports changes under them — Anchor's
#: own per-project store, git internals, dependency trees, and managed worktrees.
_DOC_EXCLUDE_DIRS = (".anchor", ".git", "node_modules", "__pycache__",
                     ".venv", "venv", "rnd_jobs")

#: Bare trio doc filenames we persist even when they sit at the project root (not
#: under a lane dir) — the canonical plan/report/log artifacts.
_DOC_ROOT_NAMES = ("master-plan.md", "implementation-plan.md",
                   "execution-log.md", "report.md", "handoff.md",
                   # (2026-08-06, found live) Crucible's Stage-0 artifact and
                   # the decision log are trio docs too — a commissioned run
                   # wrote NORTH-STAR.md at the worktree root and the kill-path
                   # persist dropped it as "no-docs". The run loop's PRODUCED
                   # patterns already recognize both names.
                   "north-star.md", "decision-log.md")

#: Document extensions we consider persistable produced artifacts.
_DOC_EXTS = (".md", ".pdf")

#: Output dirs a BUILD PRODUCT commonly lives under (v12 Wave 3). Retained for
#: reference; the build-stage accept is now a JUNK DENYLIST (below), not a dir
#: allowlist, so a root-level product (e.g. anchor_gui.py — the canonical Anchor
#: deliverable, NOT under any of these) is captured too (Reviewer W3-R2).
_BUILD_PRODUCT_DIRS = ("build", "deliverables", "dist", "bin", "out")

#: Build INTERMEDIATES / junk we must NEVER sweep+commit into the main repo
#: (Reviewer W3-R1): compiled bytecode, shared libs, object files, coverage/lock/
#: log/tmp/debug artifacts. A rare native-lib deliverable can be pinned explicitly.
_BUILD_JUNK_EXT = frozenset((
    ".pyc", ".pyo", ".pyd", ".so", ".dll", ".dylib", ".o", ".obj", ".a", ".lib",
    ".class", ".coverage", ".lock", ".log", ".tmp", ".temp", ".swp", ".pdb",
    ".cache", ".egg-link",
))

#: A build stage producing more than this many NON-doc products is a bundle sweep
#: (PyInstaller/webpack/etc.), not a deliverable — we persist docs only and rely on
#: the EXPLICIT pin/marker signal for the deliverable (Reviewer W3-R1 cap).
_MAX_BUILD_PRODUCTS = 25


def _empty_tree_sha(worktree_path) -> str:
    """The git empty-tree object id (a stable diff base when no earlier commit
    exists). Computed at runtime via ``git hash-object -t tree`` rather than
    hard-coded, so the constant never trips the distro high-entropy-token scan.
    Returns ``""`` if git can't produce it."""
    try:
        r = subprocess.run(
            ["git", "-C", str(worktree_path), "hash-object", "-t", "tree",
             "--stdin"],
            input="", capture_output=True, text=True, timeout=30,
            creationflags=_paths.NO_WINDOW)
    except (OSError, subprocess.SubprocessError):
        return ""
    return (r.stdout or "").strip() if r.returncode == 0 else ""


def _is_document_rel(rel: str) -> bool:
    """True iff ``rel`` (a forward-slash repo-relative path) is a produced doc.

    Inclusive of the lane output dirs (``planning/**``, ``research/**``,
    ``build/**``, ``deliverables/**``) AND the bare trio doc names at the root,
    restricted to ``.md`` / ``.pdf`` — but it NEVER sweeps ``.anchor/``,
    ``.git/``, ``node_modules``, ``__pycache__``, ``rnd_jobs`` or unrelated files.
    """
    rel = (rel or "").strip().replace("\\", "/").lstrip("/")
    if not rel:
        return False
    parts = PurePosixPath(rel).parts
    if not parts:
        return False
    # Hard exclusions: anything whose first segment (or any segment) is excluded.
    for seg in parts:
        if seg in _DOC_EXCLUDE_DIRS:
            return False
    ext = PurePosixPath(rel).suffix.lower()
    if ext not in _DOC_EXTS:
        return False
    top = parts[0]
    if top in _DOC_DIRS:
        return True
    # A bare trio doc at the project root is also persistable.
    if len(parts) == 1 and PurePosixPath(rel).name.lower() in _DOC_ROOT_NAMES:
        return True
    return False


def _produced_doc_rels(worktree_path) -> list:
    """Repo-relative POSIX paths of the document-like files the session produced.

    Asks git in the worktree for new/changed files two ways and unions them:
      - ``git status --porcelain`` → untracked + modified (uncommitted work);
      - ``git diff --name-only HEAD`` → files changed vs the worktree's HEAD
        (committed-in-worktree work).
    The union is filtered through :func:`_is_document_rel`. Best-effort: a git
    failure or a non-repo worktree yields ``[]`` (never raises).
    """
    wt = Path(worktree_path)
    if not worktree_path or not wt.is_dir():
        return []
    rels = set()
    # Untracked + modified (porcelain v1: 'XY <path>', rename 'R  old -> new').
    # ``-uall`` so untracked DIRECTORIES are expanded to their individual files
    # (the default collapses a new dir to just ``dir/``, losing the doc names).
    try:
        r = _git(wt, "status", "--porcelain", "-uall")
        if r.returncode == 0:
            for line in (r.stdout or "").splitlines():
                if len(line) < 4:
                    continue
                path = line[3:]
                if " -> " in path:          # rename → take the destination
                    path = path.split(" -> ", 1)[1]
                path = path.strip().strip('"')
                if path:
                    rels.add(path.replace("\\", "/"))
    except (OSError, subprocess.SubprocessError):
        pass
    # Tracked changes vs HEAD (anything committed inside the worktree).
    try:
        r = _git(wt, "diff", "--name-only", "HEAD")
        if r.returncode == 0:
            for line in (r.stdout or "").splitlines():
                p = line.strip().strip('"')
                if p:
                    rels.add(p.replace("\\", "/"))
    except (OSError, subprocess.SubprocessError):
        pass
    return sorted(r for r in rels if _is_document_rel(r))


def _doc_kind_title(rel: str):
    """Classify a produced doc by filename → ``(kind, title)`` for grouping.

    The ``kind``/``title`` carry the master/impl signal ``sessions`` and
    ``handoff`` look for (so a persisted MASTER-PLAN.md is recognized as a plan
    set's master doc), with a sensible humanized fallback title otherwise.
    """
    name = PurePosixPath(rel).name
    low = name.lower()
    if "master-plan" in low or "master plan" in low or "masterplan" in low:
        return "master-plan", "Master Plan"
    if ("implementation-plan" in low or "implementation plan" in low
            or "impl-plan" in low):
        return "impl-plan", "Implementation Plan"
    if "execution-log" in low or "exec-log" in low or "execution log" in low:
        return "exec-log", "Execution Log"
    if low.startswith("report"):
        return "report", "Report"
    # Humanize the stem for an honest fallback title.
    stem = PurePosixPath(rel).stem.replace("-", " ").replace("_", " ").strip()
    return "doc", (stem.title() if stem else name)


def persist_session_docs(folder_path, project_id: str, lane: str,
                         session_id: str, worktree_path) -> dict:
    """Persist a session's produced documents into the MAIN project (the keystone).

    Called on session finish/kill **BEFORE the worktree is reaped**. Steps:

      1. Detect the documents the session PRODUCED in its worktree — the
         new/changed document-like files (lane output dirs + the trio doc names),
         via git in the worktree (:func:`_produced_doc_rels`).
      2. COPY each into the MAIN project folder at the SAME relative path
         (creating parent dirs), skipping a copy that is already byte-identical.
      3. Record a per-doc DISCOVERED effort in the lane whose ``artifact_path`` is
         the MAIN-folder-relative path (content-addressed id → idempotent), so the
         doc resolves in the main folder for ``list_efforts`` /
         ``sessions.list_sessions`` / ``handoff.discover_recent_plan_set``.
      4. COMMIT in the MAIN project repo, staging ONLY those produced doc paths +
         their effort pointer-records + the lane index — never ``git add -A``,
         never the user's unrelated changes. Idempotent: re-persisting unchanged
         docs stages nothing → no empty commit.

    Returns ``{"ok": bool, "persisted": [rel, ...], "committed": bool,
    "commit": <sha|None>, "reason": str}``. **Best-effort — never raises** so a
    persistence failure can never break the kill path.
    """
    out = {"ok": False, "persisted": [], "committed": False, "commit": None,
           "reason": "ok"}
    try:
        main = Path(folder_path)
        if not folder_path or not main.exists():
            out["reason"] = "folder-missing"
            return out

        doc_rels = _produced_doc_rels(worktree_path)
        if not doc_rels:
            out["ok"] = True
            out["reason"] = "no-docs"
            return out

        wt = Path(worktree_path)
        persisted = []
        for rel in doc_rels:
            src = wt / rel
            if not src.is_file():
                continue
            dst = main / rel
            try:
                # Skip an identical re-copy so a re-persist is a true no-op.
                if dst.is_file():
                    try:
                        if (src.read_bytes() == dst.read_bytes()):
                            persisted.append(rel)
                            continue
                    except OSError:
                        pass
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                persisted.append(rel)
            except OSError:
                continue

        if not persisted:
            out["ok"] = True
            out["reason"] = "nothing-copied"
            return out

        # Record a per-doc DISCOVERED effort so the persisted docs are visible in
        # the MAIN folder's lane history (content-addressed → idempotent re-runs).
        # ``created_at`` is left to ``record_effort``'s first-write default so a
        # re-persist does NOT rewrite the pointer-record (otherwise an ever-moving
        # timestamp would re-stage the pointer and break idempotency). The doc's
        # mtime is the honest creation marker we stamp once on first record.
        pointer_rels = []
        with _journal.journaled(project_id, _journal.EV_DOC_PERSISTED,
                                correlation_id=(session_id or project_id),
                                folder_path=folder_path,
                                payload={"lane": lane}):
            for rel in persisted:
                kind, title = _doc_kind_title(rel)
                jid = discovered_job_id(lane, rel)
                try:
                    existing = load_effort(main, project_id, lane, jid)
                    extra = {"source": SOURCE_DISCOVERED, "kind": kind,
                             "title": title, "artifact_path": rel,
                             "status": "imported", "session_id": session_id}
                    if existing is None:
                        # First record: stamp created_at from the doc's on-disk mtime.
                        try:
                            extra["created_at"] = (main / rel).stat().st_mtime
                        except OSError:
                            pass
                        record_effort(main, project_id, lane, jid, skill=None,
                                      extra=extra)
                    # else: already recorded with this exact content-addressed id —
                    # leave the pointer-record untouched (idempotent; no re-stage).
                    pp = _pointer_path(main, project_id, lane, jid)
                    if pp.exists():
                        pointer_rels.append(_rel_to_folder(main, pp))
                except (OSError, ValueError):
                    continue
            ipath = _index_path(main, project_id, lane)
            if ipath.exists():
                pointer_rels.append(_rel_to_folder(main, ipath))

        out["persisted"] = persisted
        commit = _commit_session_docs(main, project_id, lane, session_id,
                                      persisted, pointer_rels)
        out["committed"] = bool(commit.get("committed"))
        out["commit"] = commit.get("commit")
        out["reason"] = commit.get("reason", "ok")
        out["ok"] = True
        return out
    except Exception:  # keystone is best-effort: NEVER raise into the kill path
        out["reason"] = "error"
        return out


# ── v12 Wave 3: per-stage baseline commit + stage-scoped persist ─────────────
#
# The doc-attribution crux (Risk R1 / Shark B1/B2): the LEGACY ``persist_session
# _docs`` uses ``_produced_doc_rels`` — a WHOLE-WORKTREE diff (``git diff
# --name-only HEAD`` ∪ ``git status --porcelain``). When research, plan and build
# all run in ONE shared worktree, that whole-tree diff attributes EVERY produced
# file to EVERY stage — a plan persist would wrongly grab the research ``r.md``,
# and ``backfill`` could pin a plan-stage ``MASTER-PLAN.md`` as a build product.
#
# v12 fixes this with a per-stage **baseline commit**: at each stage START we
# record the current HEAD as the stage's ``baseline_ref``. A stage's produced set
# is then computed with EXACT git commands measured against THAT baseline (never
# the vague "porcelain since baseline", which is not a real git construct), and
# any path already attributed to a CLOSED prior stage is subtracted. The legacy
# ``persist_session_docs`` + ``_produced_doc_rels`` are untouched (non-effort /
# legacy callers keep their exact behavior).


def record_stage_baseline(worktree_path) -> str:
    """Capture a stage-START baseline ref (the worktree's current HEAD commit).

    Returned by value as a ``baseline_ref`` string to store on the stage_history
    entry. A subsequent :func:`persist_session_stage_docs` diffs the stage's
    produced docs against THIS ref (committed-since ∪ working-tree-vs-baseline ∪
    untracked), so a stage attributes only the files it produced — even when
    research/plan/build share one worktree.

    Best-effort: a non-repo worktree, a missing git binary, an empty repo (no
    commits yet → no HEAD) all degrade to ``""`` (never raises). When the
    baseline is ``""`` the persist helper falls back to the legacy whole-tree
    diff for that stage (honest — the first stage of a brand-new repo has nothing
    earlier to exclude anyway).
    """
    wt = Path(worktree_path) if worktree_path else None
    if not wt or not wt.is_dir():
        return ""
    # Guard against git's ancestor-repo discovery: `git rev-parse HEAD` run in a
    # NON-repo dir walks UP the tree and can return an unrelated ANCESTOR repo's
    # SHA (e.g. the pytest tmp dir living under some git checkout). The docstring
    # promises a non-repo worktree degrades to "" — so require this dir to be a
    # real git repo root (its own .git) BEFORE trusting rev-parse.
    if not _is_git_repo(wt):
        return ""
    try:
        r = _git(wt, "rev-parse", "HEAD")
    except (OSError, subprocess.SubprocessError):
        return ""
    if r.returncode != 0:
        return ""
    return (r.stdout or "").strip()


def _is_stage_artifact_rel(rel: str, stage: str) -> bool:
    """True iff ``rel`` is a persistable artifact for ``stage``.

    Research/plan stages persist DOCUMENTS only (:func:`_is_document_rel` —
    ``.md``/``.pdf`` under the lane dirs / trio root names), matching the legacy
    persist. The **build** stage ALSO persists its PRODUCT (e.g. ``build/app.py``,
    ``dist/app.exe``) — a build's deliverable is code/binary, not a doc — so for
    build we accept any non-excluded file under a lane/dist/product dir in
    addition to documents. (This is the v12 keystone's reason for being: the
    build deliverable resolver feeds on the build-stage doc set.)
    """
    if _is_document_rel(rel):
        return True
    if stage != "build":
        return False
    r = (rel or "").strip().replace("\\", "/").lstrip("/")
    if not r:
        return False
    parts = PurePosixPath(r).parts
    for seg in parts:
        if seg in _DOC_EXCLUDE_DIRS:
            return False
    name = parts[-1]
    # Never sweep build intermediates / dotfiles into the main repo (W3-R1).
    if name.startswith("."):
        return False
    if PurePosixPath(name).suffix.lower() in _BUILD_JUNK_EXT:
        return False
    # A build PRODUCT can live at the repo ROOT (e.g. anchor_gui.py — the canonical
    # Anchor deliverable) or any depth. The baseline diff already scopes this to
    # what the BUILD stage produced, and prior-stage subtraction removes the
    # research/plan docs — so accept any remaining non-junk produced file (W3-R2).
    return True


def _stage_produced_rels(worktree_path, baseline_ref, stage="") -> list:
    """Repo-relative POSIX paths a stage produced SINCE ``baseline_ref``.

    Computed with the EXACT git commands (Shark B2 — no vague "porcelain since
    baseline"):

      - ``committed = git diff --name-only <baseline_ref>..HEAD``  (committed
        since the baseline);
      - ``working   = git diff --name-only <baseline_ref> --``     (working-tree
        vs the baseline — uncommitted edits to tracked files);
      - ``untracked = git status --porcelain -uall`` additions     (brand-new
        files not yet tracked).

    The union is filtered through :func:`_is_stage_artifact_rel` (docs for
    research/plan; docs + build products for build). When ``baseline_ref`` is
    falsy (no earlier commit) this degrades to the legacy whole-tree set
    (:func:`_produced_doc_rels`) for documents, plus build products for the build
    stage. Best-effort — a git failure yields ``[]``.
    """
    wt = Path(worktree_path)
    if not worktree_path or not wt.is_dir():
        return []
    if not baseline_ref:
        # No earlier commit to diff against (the first stage of a fresh repo has
        # nothing prior to exclude). research/plan → the legacy whole-tree DOC
        # set. build → fall through to the whole-tree scan against the git
        # EMPTY-TREE so build PRODUCTS are swept too (filtered by stage below).
        if stage != "build":
            return _produced_doc_rels(worktree_path)
        baseline_ref = _empty_tree_sha(worktree_path)
        if not baseline_ref:
            return _produced_doc_rels(worktree_path)

    rels = set()

    def _emit_diff(*args):
        try:
            r = _git(wt, *args)
        except (OSError, subprocess.SubprocessError):
            return
        if r.returncode != 0:
            return
        for line in (r.stdout or "").splitlines():
            p = line.strip().strip('"')
            if p:
                rels.add(p.replace("\\", "/"))

    # committed-since the baseline.
    _emit_diff("diff", "--name-only", f"{baseline_ref}..HEAD")
    # working-tree vs the baseline (uncommitted edits to tracked files).
    _emit_diff("diff", "--name-only", baseline_ref, "--")
    # untracked additions (brand-new files) via porcelain.
    try:
        r = _git(wt, "status", "--porcelain", "-uall")
        if r.returncode == 0:
            for line in (r.stdout or "").splitlines():
                if len(line) < 4:
                    continue
                # porcelain XY: an untracked file is '?? <path>'. We also accept
                # added entries 'A  <path>' (in case a stage staged its work).
                code = line[:2]
                path = line[3:]
                if " -> " in path:          # rename → take the destination
                    path = path.split(" -> ", 1)[1]
                path = path.strip().strip('"')
                if not path:
                    continue
                if code == "??" or "A" in code:
                    rels.add(path.replace("\\", "/"))
    except (OSError, subprocess.SubprocessError):
        pass

    kept = sorted(r for r in rels if _is_stage_artifact_rel(r, stage))
    if stage == "build":
        # Bundle-sweep guard (W3-R1): if the build produced an unreasonable number
        # of NON-doc products, it's an artifact tree, not a deliverable — persist
        # the docs only and let the EXPLICIT pin/marker resolve the deliverable.
        products = [r for r in kept if not _is_document_rel(r)]
        if len(products) > _MAX_BUILD_PRODUCTS:
            kept = [r for r in kept if _is_document_rel(r)]
    return kept


def efforts_for_session_stage(folder_path, project_id: str, session_id: str,
                              stage: str) -> list:
    """Return the persisted-doc efforts tagged with BOTH ``session_id`` + ``stage``.

    The v12 Wave-3 stage-scoped persist (:func:`persist_session_stage_docs`)
    stamps each produced-doc effort with the originating managed ``session_id``
    AND the producing ``stage`` (in ``extra``). This join recovers the EXACT docs
    one stage of one effort produced — used to (a) exclude a prior closed stage's
    paths from a later stage's produced set, and (b) feed the build deliverable
    resolver ONLY the build-stage docs.

    Scans the stage's STORE-lane subdir (research→research / plan→planning /
    build→build), newest-first. Returns ``[]`` for an empty/unmatched lane or
    missing args. Never raises.
    """
    if not session_id or not stage:
        return []
    store_lane = _STORE_LANE_FOR_STAGE.get(stage, stage)
    try:
        return [e for e in list_efforts(folder_path, project_id, store_lane)
                if (e.get("session_id") or "") == session_id
                and (e.get("stage") or "") == stage]
    except Exception:
        return []


def persist_session_stage_docs(folder_path, project_id: str, session_id: str,
                               stage: str, store_lane: str, worktree_path,
                               baseline_ref) -> dict:
    """Persist ONE stage's produced docs into the MAIN project (the v12 keystone).

    Unlike the legacy :func:`persist_session_docs` (a whole-worktree diff that
    grabs everything since the worktree was cut), this attributes docs to
    ``stage`` only:

      produced = (committed-since ∪ working-vs-baseline ∪ untracked-additions)
                 MINUS any path already attributed to a CLOSED PRIOR stage of
                 THIS session (looked up via :func:`efforts_for_session_stage`
                 for the earlier trio stages).

    Each persisted effort is tagged ``(session_id, stage)`` (so
    ``efforts_for_session_stage`` can recover it). The docs are copied into the
    MAIN folder at the same rel path (byte-identical skip → idempotent), recorded
    as per-doc DISCOVERED efforts in ``store_lane``, and committed scoped to ONLY
    those paths (+ pointer/index) — never ``git add -A``.

    Returns ``{"ok", "persisted":[rel,...], "committed", "commit", "reason"}``.
    Best-effort — NEVER raises (a persistence failure can't break a stage
    boundary or a kill).
    """
    out = {"ok": False, "persisted": [], "committed": False, "commit": None,
           "reason": "ok"}
    try:
        main = Path(folder_path)
        if not folder_path or not main.exists():
            out["reason"] = "folder-missing"
            return out

        produced = _stage_produced_rels(worktree_path, baseline_ref, stage)

        # Subtract paths already attributed to a CLOSED prior stage of THIS
        # session (the stages that come BEFORE ``stage`` in the trio order).
        prior_rels = set()
        for prior in _STAGES_BEFORE.get(stage, ()):  # () for unknown stages
            for e in efforts_for_session_stage(main, project_id, session_id,
                                               prior):
                ap = (e.get("artifact_path") or "").strip().replace("\\", "/")
                if ap:
                    prior_rels.add(ap)
        doc_rels = [r for r in produced if r not in prior_rels]

        if not doc_rels:
            out["ok"] = True
            out["reason"] = "no-docs"
            return out

        wt = Path(worktree_path)
        persisted = []
        for rel in doc_rels:
            src = wt / rel
            if not src.is_file():
                continue
            dst = main / rel
            try:
                if dst.is_file():
                    try:
                        if src.read_bytes() == dst.read_bytes():
                            persisted.append(rel)
                            continue
                    except OSError:
                        pass
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(str(src), str(dst))
                persisted.append(rel)
            except OSError:
                continue

        if not persisted:
            out["ok"] = True
            out["reason"] = "nothing-copied"
            return out

        # Per-doc DISCOVERED efforts in the STORE lane, tagged (session, stage).
        pointer_rels = []
        for rel in persisted:
            kind, title = _doc_kind_title(rel)
            jid = discovered_job_id(store_lane, rel)
            try:
                existing = load_effort(main, project_id, store_lane, jid)
                extra = {"source": SOURCE_DISCOVERED, "kind": kind,
                         "title": title, "artifact_path": rel,
                         "status": "imported", "session_id": session_id,
                         "stage": stage}
                if existing is None:
                    try:
                        extra["created_at"] = (main / rel).stat().st_mtime
                    except OSError:
                        pass
                    record_effort(main, project_id, store_lane, jid, skill=None,
                                  extra=extra)
                elif (existing.get("stage") or "") != stage:
                    # Same content-addressed id but no stage tag yet (or a
                    # legacy persist) — stamp the producing stage in place so
                    # ``efforts_for_session_stage`` recovers it. Keep created_at.
                    record_effort(main, project_id, store_lane, jid, skill=None,
                                  extra={"stage": stage,
                                         "session_id": session_id})
                pp = _pointer_path(main, project_id, store_lane, jid)
                if pp.exists():
                    pointer_rels.append(_rel_to_folder(main, pp))
            except (OSError, ValueError):
                continue
        ipath = _index_path(main, project_id, store_lane)
        if ipath.exists():
            pointer_rels.append(_rel_to_folder(main, ipath))

        out["persisted"] = persisted
        commit = _commit_session_docs(main, project_id, store_lane, session_id,
                                      persisted, pointer_rels)
        out["committed"] = bool(commit.get("committed"))
        out["commit"] = commit.get("commit")
        out["reason"] = commit.get("reason", "ok")
        out["ok"] = True
        return out
    except Exception:  # keystone is best-effort: NEVER raise into the boundary
        out["reason"] = "error"
        return out


#: Per-stage store-lane (mirrors session_registry._STAGE_STORE_LANE, kept here so
#: effort_history has no import dependency on the registry for this map).
_STORE_LANE_FOR_STAGE = {
    "research": "research",
    "plan": "planning",
    "build": "build",
}

#: The trio stages that come BEFORE a given stage (closed prior stages whose
#: produced paths are excluded from a later stage's set).
_STAGES_BEFORE = {
    "research": (),
    "plan": ("research",),
    "build": ("research", "plan"),
}


def _rel_to_folder(folder: Path, p: Path) -> str:
    """Folder-relative POSIX path of ``p`` (or its str() if not under folder)."""
    try:
        return str(p.relative_to(folder)).replace("\\", "/")
    except ValueError:
        return str(p)


def _commit_session_docs(folder: Path, project_id: str, lane: str,
                         session_id: str, doc_rels, pointer_rels) -> dict:
    """Commit ONLY the produced docs (+ pointer/index) in the MAIN project repo.

    Scoped + safe: refuses the Anchor code repo, requires an existing git repo
    (never inits here — Wave 1 bootstrap owns that), stages ONLY the explicit
    paths (no ``git add -A``), and produces no empty commit (a re-persist of
    unchanged docs stages nothing → ``no-staged-changes``). Returns the same
    shape as :func:`auto_commit_effort`.
    """
    if not folder.exists():
        return {"committed": False, "reason": "folder-missing", "commit": None}
    code = _paths.CODE_DIR.resolve()
    if _is_anchor_repo(folder, code):
        return {"committed": False, "reason": "refused-anchor-repo",
                "commit": None}
    if not _is_git_repo(folder):
        return {"committed": False, "reason": "not-a-git-repo", "commit": None}

    # The explicit, scoped set of paths to stage: the produced docs + their
    # pointer-records + the lane index. NEVER ``git add -A``.
    rel_targets = []
    for rel in list(doc_rels) + list(pointer_rels):
        if rel and rel not in rel_targets:
            rel_targets.append(rel)
    if not rel_targets:
        return {"committed": False, "reason": "nothing-to-commit", "commit": None}

    with _paths.WRITE_LOCK:
        try:
            _git(folder, "add", "--", *rel_targets, check=True)
        except (OSError, subprocess.SubprocessError):
            return {"committed": False, "reason": "add-failed", "commit": None}

        diff = _git(folder, "diff", "--cached", "--name-only")
        if not (diff.stdout or "").strip():
            return {"committed": False, "reason": "no-staged-changes",
                    "commit": None}

        sid8 = (str(session_id) or "")[:8]
        msg = f"anchor: {lane} session {sid8} docs ({project_id})"
        env_args = [
            "-c", "user.name=Anchor",
            "-c", "user.email=anchor@localhost",
            "-c", "commit.gpgsign=false",
        ]
        try:
            r = subprocess.run(
                ["git", "-C", str(folder), *env_args, "commit",
                 "--no-verify", "-m", msg, "--", *rel_targets],
                capture_output=True, text=True, timeout=30,
                creationflags=_paths.NO_WINDOW,
            )
        except (OSError, subprocess.SubprocessError):
            return {"committed": False, "reason": "commit-failed", "commit": None}
        if r.returncode != 0:
            return {"committed": False, "reason": "commit-nonzero",
                    "commit": None, "stderr": r.stderr}
        sha = _git(folder, "rev-parse", "HEAD")
        return {"committed": True, "reason": "ok",
                "commit": (sha.stdout or "").strip()}
