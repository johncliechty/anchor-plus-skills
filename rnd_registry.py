#!/usr/bin/env python3
"""Anchor R&D project registry — thin, id-keyed (stdlib only).

Wave 3 of the R&D control surface. This is a NEW, parallel registry distinct
from the existing life-domain projects in ``PROJECTS.md`` (Master Plan D5).

Frozen design (MASTER-PLAN.md "Architecture (frozen)" + D5):
- An R&D project = ``{id, name, folder_path, priority, state}``.
- The registry is keyed by **id**; ``folder_path`` is **NOT** unique, so N
  projects may share one folder. The view groups projects by folder.
- Persisted as JSON under ``ANCHOR_DATA_DIR`` (resolved via ``paths``), never a
  hard-coded location. Every mutation runs under ``paths.WRITE_LOCK`` so
  concurrent ``ThreadingHTTPServer`` writers cannot lose an update.
- Per-project artifacts live under ``<folder>/.anchor/projects/<id>/`` =
  ``research/ planning/ build/ deliverables/ jobs/`` so folder-sharing projects
  never collide.
- Lifecycle states (C7): priority change, archive, future-work are **retained,
  not deleted**. A folder that has gone missing yields a ``path-missing`` state
  (best-effort, surfaced on read — not a crash).

Stdlib only. No third-party imports.
"""

import json
import uuid
from pathlib import Path

import paths as _paths
import journal as _journal

# Registry JSON filename, stored at the data-dir root.
REGISTRY_NAME = "rnd_registry.json"

# Lane subdirectories scaffolded under each project's namespace. ``grass`` is
# the Grass Catchers lane (v2 Wave 4 structure; content feeds land in Wave 5).
LANE_DIRS = ("research", "planning", "build", "deliverables", "grass", "jobs")

# Canonical lifecycle states. ``active`` is the default; ``archived`` and
# ``future`` are retained (not deleted); ``path-missing`` is computed on read
# when a project's folder has disappeared.
STATE_ACTIVE = "active"
STATE_ARCHIVED = "archived"
STATE_FUTURE = "future"
STATE_RETIRED = "retired"          # cancelled / done-with (kept, reviewable)
STATE_PATH_MISSING = "path-missing"

VALID_STORED_STATES = {STATE_ACTIVE, STATE_ARCHIVED, STATE_FUTURE, STATE_RETIRED}
#: States that are NOT active (shown on the Archive/Inactive view, not the main one).
INACTIVE_STATES = {STATE_ARCHIVED, STATE_FUTURE, STATE_RETIRED}

# The four R&D lanes shown on the project status line (UX design: 4-state
# status line for Research / Planning / Build / Deliverables).
STATUS_LANES = ("research", "planning", "build", "deliverables")
STATUS_NONE_YET = "none-yet"


# ── Persistence ─────────────────────────────────────────────────────────

def registry_path() -> Path:
    """Absolute path to the registry JSON file under ANCHOR_DATA_DIR."""
    return _paths.data_dir() / REGISTRY_NAME


def _new_id() -> str:
    """Generate a fresh, stable, collision-resistant id (stdlib uuid4 hex)."""
    return uuid.uuid4().hex


def load_registry() -> dict:
    """Load the registry as a dict ``{id: entry}``.

    Returns an empty dict if the file does not exist or is unreadable/corrupt
    (best-effort — a corrupt registry must not crash the dashboard). The JSON
    on disk is a list of entries; this returns them keyed by id for O(1) lookup.
    """
    p = registry_path()
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out = {}
    if isinstance(raw, list):
        for e in raw:
            if isinstance(e, dict) and e.get("id"):
                out[e["id"]] = _normalize(e)
    elif isinstance(raw, dict):
        # Tolerate an already-keyed dict form too.
        for k, e in raw.items():
            if isinstance(e, dict):
                e = dict(e)
                e.setdefault("id", k)
                out[e["id"]] = _normalize(e)
    return out


def _normalize(entry: dict) -> dict:
    """Coerce an entry to the canonical ``{id,name,folder_path,priority,state}``."""
    folder = entry.get("folder_path", "")
    try:
        folder_path = str(Path(folder)) if folder else ""
    except (TypeError, ValueError):
        folder_path = str(folder)
    state = entry.get("state", STATE_ACTIVE)
    if state not in VALID_STORED_STATES and state != STATE_PATH_MISSING:
        state = STATE_ACTIVE
    try:
        priority = int(entry.get("priority", 2))
    except (TypeError, ValueError):
        priority = 2
    return {
        "id": entry.get("id"),
        "name": entry.get("name", ""),
        "folder_path": folder_path,
        "priority": priority,
        "state": state,
        "notes": (entry.get("notes") or ""),
        "blurb": (entry.get("blurb") or ""),
        # v8 Wave 3 — GitHub remote linking + auto-push opt-in (offsite layer).
        "remote_url": (entry.get("remote_url") or ""),
        "auto_push": bool(entry.get("auto_push")),
        # v9 Wave 3 — dashboard folder/group field (organization-only; NO disk
        # move this wave). "" means Ungrouped (back-compat: a record without a
        # "group" field reads as "").
        "group": (entry.get("group") or ""),
    }


def _save_registry(reg: dict) -> None:
    """Persist the registry (dict keyed by id) as a JSON list, under the lock."""
    with _paths.WRITE_LOCK:
        _paths.data_dir().mkdir(parents=True, exist_ok=True)
        items = [reg[k] for k in reg]
        _paths.atomic_write_text(
            registry_path(),
            json.dumps(items, indent=2, ensure_ascii=False),
        )


# ── Per-project store scaffold ──────────────────────────────────────────

def project_store_dir(folder_path, project_id: str) -> Path:
    """Return ``<folder>/.anchor/projects/<id>/`` (not created)."""
    return Path(folder_path) / ".anchor" / "projects" / project_id


def scaffold_project_store(folder_path, project_id: str) -> Path:
    """Create ``<folder>/.anchor/projects/<id>/{lanes}/`` + the tracking policy.

    Idempotent. Returns the project store dir. Writes a minimal ``.gitignore``
    + ``README`` at the ``.anchor/`` root that reconciles C9 (git-trackable
    pointer-records) with C10 (no personal-data leak): pointer-record JSON is
    trackable, but heavy/raw artifacts and any logs are ignored.
    """
    with _paths.WRITE_LOCK:
        store = project_store_dir(folder_path, project_id)
        for lane in LANE_DIRS:
            (store / lane).mkdir(parents=True, exist_ok=True)
        _write_tracking_policy(Path(folder_path) / ".anchor")
        return store


_GITIGNORE_BODY = """# Anchor R&D per-project store — tracking policy (reconciles C9 + C10).
#
# C9 (durable/git-trackable): the lightweight JSON *pointer-records* that index
#   each project's efforts ARE meant to be committed so history survives.
# C10 (no personal-data leak / shareable distro): raw run logs, large engine
#   outputs, and anything that may carry absolute paths / tokens / personal
#   data are git-IGNORED here and excluded by the distribution scan (Wave 8).
#
# Default: ignore the heavy/volatile artifacts; allow-list the pointer records.

projects/*/jobs/
projects/*/**/*.log
projects/*/**/*.pdf
projects/*/**/raw/

# rearch W12 (C3): the per-project append-only event journal is a RUNTIME,
# volatile mutation-of-record log (may carry absolute paths / personal data) —
# ignored like the job logs above, never a committed pointer record.
projects/*/journal.jsonl
projects/*/**/journal.jsonl

# Re-include the small pointer-record JSON index files (git-trackable).
!projects/*/**/index.json
!projects/*/**/*.pointer.json
"""

_README_BODY = """# .anchor/ — Anchor R&D per-project store

This directory is created and managed by Anchor's R&D control surface. Each
registered project gets an isolated namespace at:

    .anchor/projects/<project-id>/
        research/      planning/      build/      deliverables/      jobs/

Multiple projects may share one folder; each has its own `<project-id>` subtree,
so their stores never collide.

## Tracking policy (C9 git-trackable vs C10 no-leak)

- **Tracked (C9):** small JSON *pointer-records* that index efforts/versions —
  these are committed so effort history is durable across restarts.
- **Ignored (C10):** raw job logs, large generated artifacts (PDF), and any
  `raw/` payloads that could carry absolute paths, tokens, or personal data.
  The distribution build (Wave 8) additionally scans for and refuses to ship
  anything under `.anchor/`.

See the sibling `.gitignore` for the exact rules.
"""


def _write_tracking_policy(anchor_dir: Path) -> None:
    """Write the .anchor/.gitignore + .anchor/README if absent (idempotent)."""
    anchor_dir.mkdir(parents=True, exist_ok=True)
    gi = anchor_dir / ".gitignore"
    if not gi.exists():
        gi.write_text(_GITIGNORE_BODY, encoding="utf-8")
    rd = anchor_dir / "README"
    if not rd.exists():
        rd.write_text(_README_BODY, encoding="utf-8")


# ── CRUD ────────────────────────────────────────────────────────────────

def add_project(name: str, folder_path, priority: int = 2,
                state: str = STATE_ACTIVE, scaffold: bool = True,
                notes: str = "", blurb: str = "") -> dict:
    """Register a new project with a FRESH id. Returns the stored entry.

    ``folder_path`` is non-unique — adding another project for an
    already-registered folder is allowed (1 folder : N projects). When
    ``scaffold`` is true, the per-project ``.anchor/projects/<id>/`` tree is
    created.
    """
    with _paths.WRITE_LOCK:
        reg = load_registry()
        pid = _new_id()
        while pid in reg:  # astronomically unlikely; cheap safety
            pid = _new_id()
        entry = _normalize({
            "id": pid,
            "name": name,
            "folder_path": str(folder_path),
            "priority": priority,
            "state": state,
            "notes": notes,
            "blurb": blurb,
        })
        reg[pid] = entry
        with _journal.journaled(pid, _journal.EV_PROJECT_CREATED,
                                correlation_id=pid, folder_path=folder_path,
                                payload={"project_id": pid, "name": name}):
            _save_registry(reg)
        if scaffold:
            scaffold_project_store(entry["folder_path"], pid)
        return entry


def get_project(project_id: str):
    """Return the entry for ``project_id`` or ``None``."""
    if project_id == "__dashboard__":
        return {
            "id": "__dashboard__",
            "name": "Workspace Root (dev)",
            "folder_path": str(_paths.data_dir().parent),
            "state": "active",
            "priority": 1,
            "group": "",
            "notes": "Global general terminal and grasscatcher."
        }
    if project_id == "__doctor__":
        # Doctor V3 Wave 2: reserved pseudo-project for THE /doctor agentic
        # diagnostic session (same idiom as __dashboard__ above). Synthetic —
        # never a registry row, so it can never surface on the dashboard
        # project list; the session-listing surfaces filter it explicitly too.
        # folder_path = the Anchor root (data_dir() == CODE_DIR in the live
        # layout; the temp data dir in tests, keeping the gate hermetic) — the
        # doctor session's cwd, held read-only by the engine's plan mode.
        return {
            "id": "__doctor__",
            "name": "Anchor Doctor",
            "folder_path": str(_paths.data_dir()),
            "state": "active",
            "priority": 1,
            "group": "",
            "notes": "Reserved pseudo-project for the /doctor diagnostic "
                     "session; filtered from every dashboard surface.",
        }
    return load_registry().get(project_id)


def update_project(project_id: str, **fields) -> dict:
    """Update allowed fields (name, folder_path, priority, state). Returns entry.

    Raises ``KeyError`` if the id is unknown.
    """
    allowed = {"name", "folder_path", "priority", "state", "notes", "blurb",
               "remote_url", "auto_push", "group"}
    with _paths.WRITE_LOCK:
        reg = load_registry()
        if project_id not in reg:
            raise KeyError(project_id)
        entry = dict(reg[project_id])
        for k, v in fields.items():
            if k in allowed and v is not None:
                entry[k] = v
        entry = _normalize(entry)
        entry["id"] = project_id
        reg[project_id] = entry
        _save_registry(reg)
        return entry


def set_priority(project_id: str, priority: int) -> dict:
    """Change a project's priority (lifecycle op C7)."""
    _journal.emit_safe(project_id, _journal.EV_PROJECT_LIFECYCLE,
                       correlation_id=project_id, folder_path=None,
                       payload={"project_id": project_id, "action": "set_priority"})
    return update_project(project_id, priority=int(priority))


def archive_project(project_id: str) -> dict:
    """Archive a project — RETAINED in the registry, not deleted (C7)."""
    _journal.emit_safe(project_id, _journal.EV_PROJECT_LIFECYCLE,
                       correlation_id=project_id, folder_path=None,
                       payload={"project_id": project_id, "action": "archive"})
    return update_project(project_id, state=STATE_ARCHIVED)


def mark_future(project_id: str) -> dict:
    """Mark a project as future-work — RETAINED, not deleted (C7)."""
    return update_project(project_id, state=STATE_FUTURE)


def retire_project(project_id: str) -> dict:
    """Retire/cancel a project — RETAINED in the registry, not deleted (C7)."""
    _journal.emit_safe(project_id, _journal.EV_PROJECT_LIFECYCLE,
                       correlation_id=project_id, folder_path=None,
                       payload={"project_id": project_id, "action": "retire"})
    return update_project(project_id, state=STATE_RETIRED)


def reactivate_project(project_id: str) -> dict:
    """Move an archived/future/retired project back to active."""
    _journal.emit_safe(project_id, _journal.EV_PROJECT_LIFECYCLE,
                       correlation_id=project_id, folder_path=None,
                       payload={"project_id": project_id, "action": "reactivate"})
    return update_project(project_id, state=STATE_ACTIVE)


def set_notes(project_id: str, notes: str) -> dict:
    """Set the free-text notes for a project (like a task's Notes field)."""
    _journal.emit_safe(project_id, _journal.EV_PROJECT_LIFECYCLE,
                       correlation_id=project_id, folder_path=None,
                       payload={"project_id": project_id, "action": "set_notes"})
    return update_project(project_id, notes=("" if notes is None else str(notes)))


# ── Dashboard folder/group (v9 Wave 3 — organization-only, NO disk move) ──

#: The display name for the empty-group ("") bucket on the dashboard.
UNGROUPED_LABEL = "Ungrouped"


def set_group(project_id: str, group: str) -> dict:
    """Set a project's dashboard ``group`` (folder) — organization only.

    ``""`` means Ungrouped. This does NOT move anything on disk (that is the
    v9 Wave 4 guarded on-disk move); it only re-labels which collapsible
    folder the project renders under on the home dashboard. Returns the entry.
    """
    _journal.emit_safe(project_id, _journal.EV_PROJECT_LIFECYCLE,
                       correlation_id=project_id, folder_path=None,
                       payload={"project_id": project_id, "action": "set_group"})
    return update_project(
        project_id, group=("" if group is None else str(group).strip()))


# ── GitHub remote linking + auto-push opt-in (v8 Wave 3) ─────────────────

def set_remote(project_id: str, remote_url: str) -> dict:
    """Persist a project's linked GitHub remote url (offsite layer)."""
    return update_project(
        project_id, remote_url=("" if remote_url is None else str(remote_url)))


def set_auto_push(project_id: str, enabled: bool) -> dict:
    """Persist a project's auto-push-on-finish opt-in flag (default off)."""
    return update_project(project_id, auto_push=bool(enabled))


# ── Project blurb ("what this project is") — Wave 3 ──────────────────────

#: Source files probed (in order) to SEED a project blurb, best-effort.
BLURB_SEED_FILES = ("CLAUDE.md", "README.md", "README", "Anchor.md")
#: Max chars read from a seed file (bounded read — never slurp a huge file).
_BLURB_SEED_MAX_READ = 8192
#: Max chars kept for the seeded blurb itself.
_BLURB_MAX_LEN = 400


def set_blurb(project_id: str, blurb: str) -> dict:
    """Set the user-editable project blurb (what the project is). Returns entry."""
    _journal.emit_safe(project_id, _journal.EV_PROJECT_LIFECYCLE,
                       correlation_id=project_id, folder_path=None,
                       payload={"project_id": project_id, "action": "set_blurb"})
    return update_project(project_id, blurb=("" if blurb is None else str(blurb)))


def _extract_blurb(text: str) -> str:
    """Best-effort: first meaningful heading-or-paragraph from a seed doc.

    Skips a leading ``# Title`` heading and blockquote/badge lines, returns the
    first non-empty prose paragraph (or, failing that, the title text), bounded
    to ``_BLURB_MAX_LEN`` chars. Never raises.
    """
    title = ""
    para = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            if para:
                break  # end of the first paragraph
            continue
        if line.startswith("#"):
            if not title:
                title = line.lstrip("#").strip()
            continue
        if line.startswith(">") or line.startswith("|") or line.startswith("---"):
            continue
        para.append(line)
    blurb = " ".join(para).strip() or title
    if len(blurb) > _BLURB_MAX_LEN:
        blurb = blurb[:_BLURB_MAX_LEN].rstrip() + "…"
    return blurb


def seed_blurb(project_id: str, *, force: bool = False) -> dict:
    """Seed a project's blurb ONCE from its folder docs, if currently empty.

    Reads (bounded, best-effort) the first of ``BLURB_SEED_FILES`` that exists in
    the project's ``folder_path`` and extracts the first heading-or-paragraph as
    the blurb. A no-op if the blurb is already set (unless ``force``) or nothing
    usable is found. Never crashes on a missing/unreadable folder.

    Returns the (possibly updated) entry, or ``None`` if the id is unknown.
    """
    proj = get_project(project_id)
    if proj is None:
        return None
    if (proj.get("blurb") or "").strip() and not force:
        return proj
    folder = proj.get("folder_path", "")
    if not folder:
        return proj
    text = ""
    for name in BLURB_SEED_FILES:
        try:
            p = Path(folder) / name
            if p.is_file():
                text = p.read_text(encoding="utf-8", errors="replace")[
                    :_BLURB_SEED_MAX_READ]
                break
        except (OSError, ValueError):
            continue
    blurb = _extract_blurb(text)
    if not blurb:
        return proj
    return update_project(project_id, blurb=blurb)


def remove_project(project_id: str) -> bool:
    """Hard-delete an entry (NOT used by archive/future ops). Returns success.

    Provided for completeness; lifecycle ops use archive/future which retain.
    """
    with _paths.WRITE_LOCK:
        reg = load_registry()
        if project_id in reg:
            del reg[project_id]
            _save_registry(reg)
            return True
        return False


# ── Read / view helpers ─────────────────────────────────────────────────

def _effective_state(entry: dict) -> str:
    """Compute the surfaced state: ``path-missing`` overrides if folder is gone.

    Archived/future are retained states and are reported as-is even if the
    folder is also missing; only otherwise-live entries flip to path-missing.
    """
    fp = entry.get("folder_path", "")
    if entry.get("state") in INACTIVE_STATES:
        return entry["state"]
    if fp and not Path(fp).exists():
        return STATE_PATH_MISSING
    return entry.get("state", STATE_ACTIVE)


def list_projects(include_archived: bool = True, include_future: bool = True,
                  include_retired: bool = True,
                  with_effective_state: bool = True) -> list:
    """Return entries as a list. ``state`` reflects path-missing when applicable.

    Archived/future/retired entries are included by default (retained,
    reviewable); the active dashboard passes all three flags False to show only
    live projects, while the Archive view shows only the inactive ones.
    """
    reg = load_registry()
    out = []
    for e in reg.values():
        e = dict(e)
        if with_effective_state:
            e["state"] = _effective_state(e)
        stored = reg[e["id"]]["state"]
        if not include_archived and stored == STATE_ARCHIVED:
            continue
        if not include_future and stored == STATE_FUTURE:
            continue
        if not include_retired and stored == STATE_RETIRED:
            continue
        out.append(e)
    out.sort(key=lambda x: (x.get("priority", 2), x.get("name", "").lower()))
    return out


def list_inactive_projects() -> list:
    """Return ONLY archived/future/retired projects (for the Archive view)."""
    reg = load_registry()
    out = []
    for e in reg.values():
        if reg[e["id"]]["state"] in INACTIVE_STATES:
            e = dict(e)
            e["state"] = _effective_state(e)
            out.append(e)
    out.sort(key=lambda x: (x.get("state", ""), x.get("name", "").lower()))
    return out


def group_by_folder(include_archived: bool = True,
                    include_future: bool = True,
                    include_retired: bool = True) -> dict:
    """Group projects by ``folder_path`` → list of entries (ordered).

    The projects view renders this: a collapsible folder header → its tiles.
    Two projects sharing a folder appear under the same key with distinct ids.
    """
    groups = {}
    for e in list_projects(include_archived=include_archived,
                           include_future=include_future,
                           include_retired=include_retired):
        groups.setdefault(e["folder_path"], []).append(e)
    return groups


def group_by_group(include_archived: bool = True,
                   include_future: bool = True,
                   include_retired: bool = True) -> dict:
    """Group projects by their dashboard ``group`` → list of entries (v9 W3).

    The home dashboard renders this as collapsible folders. Projects whose
    ``group`` is ``""`` (or absent — back-compat) bucket under the
    ``UNGROUPED_LABEL`` ("Ungrouped") key. Within a group, entries keep the
    ``list_projects`` ordering (priority, then name). The returned dict is
    ordered: named groups (alphabetical, case-insensitive) first, with
    ``Ungrouped`` always last.
    """
    named = {}
    ungrouped = []
    for e in list_projects(include_archived=include_archived,
                           include_future=include_future,
                           include_retired=include_retired):
        g = (e.get("group") or "").strip()
        if g:
            named.setdefault(g, []).append(e)
        else:
            ungrouped.append(e)
    out = {}
    for g in sorted(named, key=lambda s: s.lower()):
        out[g] = named[g]
    out[UNGROUPED_LABEL] = ungrouped  # always present, always last
    return out


#: Legacy lane-state strings (kept as named constants for back-compat; the
#: Wave 3 ``status_line`` no longer returns these — see ``lane_counts`` below).
STATUS_IMPORTED = "imported"   # a session whose members are discovered (brownfield)
STATUS_HAS_RUNS = "has-runs"   # >=1 real (Anchor-run) session
STATUS_RUNNING = "running"     # a live job in this lane

#: The per-lane count keys returned by ``status_line`` (Wave 3 contract).
LANE_COUNT_KEYS = ("count", "imported", "running")


def _empty_lane_counts() -> dict:
    """A zeroed per-lane counts dict (the default when a lane is empty/unread)."""
    return {k: 0 for k in LANE_COUNT_KEYS}


def status_line(project_id: str) -> dict:
    """Return per-lane SESSION COUNTS + PROVENANCE for a project (Wave 3 contract).

    The unit is now a **session** (one trio run = one session, MASTER-PLAN §A),
    NOT a raw effort: 7 discovered planning files that group into 2 planning
    sessions count as ``planning.count == 2``. This REPLACES the old
    ``has-runs``/``imported``/``none-yet`` masquerade — imported provenance is now
    a count, not the lane's whole state, so a lane with sessions never renders as
    ``import`` or ``none-yet``.

    Shape (one entry per ``STATUS_LANES`` lane)::

        {"research":     {"count": 1, "imported": 1, "running": 0},
         "planning":     {"count": 2, "imported": 2, "running": 0},
         "build":        {"count": 1, "imported": 0, "running": 1},
         "deliverables": {"count": 0, "imported": 0, "running": 0}}

    - ``count``    = number of sessions in the lane.
    - ``imported`` = how many of those are brownfield-imported (provenance
      ``imported``); the rest are real Anchor runs.
    - ``running``  = how many sessions have a live (``running``) job.

    Best-effort: never crashes if a lane is unread or a dependency import fails;
    a failing lane yields a zeroed counts dict.
    """
    proj = get_project(project_id)
    folder = (proj or {}).get("folder_path", "")
    out = {lane: _empty_lane_counts() for lane in STATUS_LANES}

    # Local imports to avoid hard import cycles (effort_history/sessions import
    # this module). Resolved lazily, per call.
    try:
        import sessions as _sessions
    except Exception:
        return out
    # Resolve "running" from ONLY this project's session jobs, via targeted
    # load_record lookups — NOT a full scan of the global rnd_jobs/ dir.
    # status_line is rendered for EVERY project on the dashboard; the old
    # list_records() full scan made GET / O(projects x all-jobs) and, once
    # rnd_jobs/ grew to ~1k records, pushed the dashboard past the health check's
    # 5s timeout (the red banner). We only ever need the status of the handful of
    # jobs this project's sessions reference.
    try:
        import job_runner as _jr
    except Exception:
        _jr = None

    _running_cache = {}

    def _job_is_running(job_id):
        if not job_id or _jr is None:
            return False
        if job_id in _running_cache:
            return _running_cache[job_id]
        try:
            rec = _jr.load_record(job_id)
            running = bool(rec) and rec.get("status") == _jr.STATUS_RUNNING
        except Exception:
            running = False
        _running_cache[job_id] = running
        return running

    for lane in STATUS_LANES:
        try:
            sess = _sessions.list_sessions(folder, project_id, lane)
        except Exception:
            sess = []
        counts = _empty_lane_counts()
        for s in sess:
            counts["count"] += 1
            if s.get("provenance") == _sessions.PROV_IMPORTED:
                counts["imported"] += 1
            members = s.get("member_files") or []
            if any(_job_is_running(m.get("job_id") or "") for m in members):
                counts["running"] += 1
        out[lane] = counts
    return out


# ── Folder-history unification: reconcile (Wave 2) ───────────────────────

def _same_folder_ids(active_id: str):
    """Return ``(active_entry, [sibling_entries])`` for the active id's folder.

    Siblings are OTHER registered projects whose ``folder_path`` matches the
    active project's folder EXACTLY (normalized via ``Path``). A project on a
    DIFFERENT folder (e.g. the unrelated "BF Test" temp-folder id) is never a
    sibling here, so ``reconcile_folder`` can never fold/delete it.
    """
    reg = load_registry()
    active = reg.get(active_id)
    if active is None:
        return None, []
    target = active.get("folder_path", "")
    try:
        target_norm = str(Path(target)) if target else ""
    except (TypeError, ValueError):
        target_norm = str(target)
    siblings = []
    for e in reg.values():
        if e["id"] == active_id:
            continue
        fp = e.get("folder_path", "")
        try:
            fp_norm = str(Path(fp)) if fp else ""
        except (TypeError, ValueError):
            fp_norm = str(fp)
        if fp_norm and fp_norm == target_norm:
            siblings.append(e)
    siblings.sort(key=lambda x: (x.get("priority", 2), x.get("name", "").lower()))
    return active, siblings


def reconcile_folder(active_id: str, apply: bool = False) -> dict:
    """Fold same-folder sibling ids into ``active_id``, then hard-delete them.

    This is the EXPLICIT, REVIEWABLE folder-history unification (MASTER-PLAN
    §D). It is **NOT** run silently on every rescan — a caller invokes it on
    purpose, first as a preview, then (separately) to apply.

    Two-step contract:

    - **Preview** (``apply=False``, the default): returns a PLAN of exactly what
      it WOULD do — which sibling ids (for the SAME folder only) would be folded
      into ``active_id``, how many real sessions/efforts each holds, and which
      ids would then be hard-deleted — WITHOUT mutating anything. So it can
      never silently destroy history.
    - **Apply** (``apply=True``): folds each sibling's REAL effort history into
      ``active_id`` (via ``effort_history.adopt_sibling_sessions``), then
      HARD-DELETES the folded sibling ids from the registry
      (``remove_project``). A sibling that holds nothing is still deleted (it is
      an empty same-folder duplicate). Ids on a DIFFERENT folder are never
      touched.

    Returns a report dict::

        {"ok": bool, "active_id": ..., "folder_path": ...,
         "applied": bool,
         "fold": [{"id","name","priority","efforts": {lane: n, ...},
                   "total_efforts": n}],
         "to_delete": [ids],
         "imported": n,            # apply only
         "deleted": [ids]}         # apply only

    Every registry mutation runs under ``paths.WRITE_LOCK`` (matching the
    module's existing pattern). Best-effort/honesty: an unknown ``active_id``
    yields ``{"ok": False, "reason": "unknown-active"}``.
    """
    import effort_history as _eh  # lazy: effort_history imports this module

    with _paths.WRITE_LOCK:
        active, siblings = _same_folder_ids(active_id)
        if active is None:
            return {"ok": False, "reason": "unknown-active",
                    "active_id": active_id}
        folder = active.get("folder_path", "")

        fold_plan = []
        for sib in siblings:
            sid = sib["id"]
            per_lane = {}
            total = 0
            # Fold ALL content lanes (incl. grass ideas), not just the cost
            # rollup lanes — otherwise grass ideas under a folded sibling are
            # destroyed by the subsequent hard-delete instead of migrated.
            for lane in _eh.FOLD_LANES:
                try:
                    n = len(_eh.list_efforts(folder, sid, lane))
                except Exception:
                    n = 0
                if n:
                    per_lane[lane] = n
                    total += n
            fold_plan.append({
                "id": sid,
                "name": sib.get("name", ""),
                "priority": sib.get("priority", 2),
                "state": sib.get("state", ""),
                "efforts": per_lane,
                "total_efforts": total,
            })
        to_delete = [p["id"] for p in fold_plan]

        report = {
            "ok": True,
            "active_id": active_id,
            "folder_path": folder,
            "applied": False,
            "fold": fold_plan,
            "to_delete": to_delete,
        }
        if not apply:
            return report

        # APPLY: fold each sibling's real sessions into the active id, then
        # hard-delete the sibling from the registry.
        source_ids = to_delete
        adopt = _eh.adopt_sibling_sessions(folder, active_id,
                                           source_ids=source_ids)
        deleted = []
        for sid in source_ids:
            if remove_project(sid):
                deleted.append(sid)
        report["applied"] = True
        report["imported"] = adopt.get("imported", 0)
        report["imported_by_lane"] = adopt.get("by_lane", {})
        report["deleted"] = deleted
        return report


# ── Legacy id assignment (idempotent) ───────────────────────────────────

def assign_legacy_ids(legacy_entries) -> list:
    """Assign stable ids to legacy R&D project records, idempotently.

    ``legacy_entries`` is an iterable of dicts that may lack an ``id``. Any
    entry missing/blank ``id`` gets a fresh uuid; entries that already have an
    id are left UNCHANGED. Running twice produces the same ids (idempotent) —
    because once persisted, the ids are already present on re-read.

    Returns the list of normalized entries and persists them. Existing
    registry entries are preserved (merged by id).
    """
    with _paths.WRITE_LOCK:
        reg = load_registry()
        result = []
        for raw in legacy_entries:
            e = dict(raw)
            pid = e.get("id")
            if not pid:
                pid = _new_id()
                while pid in reg:
                    pid = _new_id()
                e["id"] = pid
            entry = _normalize(e)
            reg[entry["id"]] = entry
            result.append(entry)
        _save_registry(reg)
        return result
