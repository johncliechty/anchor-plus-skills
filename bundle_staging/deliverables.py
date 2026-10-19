#!/usr/bin/env python3
"""Anchor deliverable runner — run a project's deliverable via the launch+watch
primitive with a per-type success contract (Wave 9).

A *deliverable* is an artifact a project produces that Anchor can run/read on
``gwl-server`` and report status for (Master Plan C8 / "Deliverables"). There are
three TYPES, each with its own success contract (frozen design — MASTER-PLAN
"Deliverables" + IMPLEMENTATION-PLAN Wave 9 AC1):

- **doc**       — read/rendered. Success = the doc file EXISTS and is NONEMPTY.
                  No process is spawned (you may render it with ``report_viewer``).
- **script** / **skill**
                — run it. Success = exit 0 / result-has-no-error.
- **program** (standalone)
                — run it. Success = exit 0 WITHIN the timeout.

Execution discipline (shared by script/skill/program — the same discipline the
``job_runner`` enforces, reused here):

- **stdin closed** (``DEVNULL``) — the process can never block on input.
- **non-interactive** — no console is attached; an interactive deliverable that
  waits for input simply makes no progress and is reaped by the timeout.
- **execution TIMEOUT** — a long-running/interactive deliverable TIMES OUT
  CLEANLY: the whole process tree is reaped (``job_runner._tree_kill``, taskkill
  /T /F on Windows — spike-proven, no orphan), status → ``timed-out``, and the
  gate never hangs.

Status is reported back as a small JSON **status record** (the dashboard can show
it) persisted under ``ANCHOR_DATA_DIR`` via ``paths`` — never a hard-coded path.
All mutations run under ``paths.WRITE_LOCK``.

Stdlib only. No third-party imports. (``report_viewer`` / ``rnd_registry`` /
``job_runner`` are sibling Anchor modules, also stdlib-only.)
"""

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

import paths as _paths
import rnd_registry as _rnd
import job_runner as _jr
import report_viewer as _rv
import effort_history as _eh
import journal as _journal

# ── Deliverable types ───────────────────────────────────────────────────────

TYPE_DOC = "doc"
TYPE_SCRIPT = "script"
TYPE_SKILL = "skill"
TYPE_PROGRAM = "program"
#: v4 Wave 7 added two launch-by-type kinds:
#:   - ``tool``    — an agent tool; launch VERIFIES availability (no spawn).
#:   - ``service`` — a long-running server; launch runs it as a persistent
#:                   ``preview_server`` preview (free port != 8777, isolated temp
#:                   data dir) and pulls up the running one on a second launch.
TYPE_TOOL = "tool"
TYPE_SERVICE = "service"

#: Types that are EXECUTED as a subprocess (vs. ``doc`` which is read/rendered).
EXECUTABLE_TYPES = frozenset((TYPE_SCRIPT, TYPE_SKILL, TYPE_PROGRAM))
#: Types whose launch is a STATUS VERIFICATION only — never a process spawn
#: (skill/tool are "available if present / loaded at runtime"; for a deliverable
#: we verify by existence/registry — NO spawn, per IMPLEMENTATION-PLAN Wave 7).
VERIFY_TYPES = frozenset((TYPE_SKILL, TYPE_TOOL))
VALID_TYPES = (frozenset((TYPE_DOC, TYPE_SERVICE)) | EXECUTABLE_TYPES
               | VERIFY_TYPES)

# ── Status values (the dashboard shows these) ───────────────────────────────

STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_TIMED_OUT = "timed-out"

#: Default execution timeout (seconds) for an executed deliverable. Injectable
#: per-run so a test can use a tiny value; never 0 in production.
DEFAULT_TIMEOUT = 120.0

#: Sub-directory (under a project's ``deliverables/`` lane dir) holding the
#: per-deliverable status records the dashboard reads.
STATUS_DIRNAME = "status"
STATUS_SUFFIX = ".status.json"


# ── Persistence (status records under the project's deliverables store) ─────

def _deliverables_dir(folder_path, project_id: str) -> Path:
    """``<folder>/.anchor/projects/<id>/deliverables/`` (not created)."""
    return _rnd.project_store_dir(folder_path, project_id) / "deliverables"


def _status_dir(folder_path, project_id: str) -> Path:
    return _deliverables_dir(folder_path, project_id) / STATUS_DIRNAME


def _status_path(folder_path, project_id: str, deliverable_id: str) -> Path:
    return _status_dir(folder_path, project_id) / f"{deliverable_id}{STATUS_SUFFIX}"


def _write_status(folder_path, project_id: str, record: dict) -> Path:
    """Persist a deliverable status record under ``paths.WRITE_LOCK``."""
    with _paths.WRITE_LOCK:
        d = _status_dir(folder_path, project_id)
        d.mkdir(parents=True, exist_ok=True)
        p = _status_path(folder_path, project_id, record["deliverable_id"])
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
        return p


def load_status(folder_path, project_id: str, deliverable_id: str):
    """Return a persisted deliverable status record dict, or ``None``."""
    p = _status_path(folder_path, project_id, deliverable_id)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def list_status(folder_path, project_id: str) -> list:
    """All deliverable status records for a project (best-effort)."""
    d = _status_dir(folder_path, project_id)
    if not d.exists():
        return []
    out = []
    for p in sorted(d.glob(f"*{STATUS_SUFFIX}")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out


# ── doc contract: exists + nonempty (read/rendered) ─────────────────────────

def _run_doc(target: Path) -> dict:
    """Success = the doc file EXISTS and is NONEMPTY. Optionally rendered.

    Returns the contract outcome fields. Rendering reuses ``report_viewer``'s
    stdlib markdown→HTML for ``.md`` so "read/rendered" is demonstrable, but the
    success contract is purely exists+nonempty (no process / exit code).
    """
    exists = target.exists() and target.is_file()
    size = target.stat().st_size if exists else 0
    nonempty = exists and size > 0
    rendered = None
    if nonempty:
        try:
            text = target.read_text(encoding="utf-8")
            if target.suffix.lower() in (".md", ".markdown"):
                rendered = _rv.markdown_to_html(text)
            else:
                rendered = text
        except OSError:
            rendered = None
    return {
        "status": STATUS_SUCCESS if nonempty else STATUS_FAILED,
        "exists": exists,
        "size_bytes": size,
        "rendered_chars": len(rendered) if rendered is not None else 0,
        "exit_code": None,
    }


# ── script/skill/program contract: run with timeout + stdin-closed ──────────

def _spawn(argv, cwd, env):
    """Spawn an executed deliverable: stdin CLOSED, non-interactive, own group.

    Mirrors ``job_runner.launch``'s spawn discipline: ``stdin=DEVNULL`` (can
    never block on input), stdout/stderr captured, and a new process group on
    Windows so the whole tree is reapable via ``taskkill /T /F``.
    """
    full_env = dict(os.environ)
    if env:
        full_env.update(env)
    creationflags = 0
    if os.name == "nt":
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(
        argv,
        cwd=str(cwd) if cwd else None,
        stdin=subprocess.DEVNULL,        # non-interactive: input is closed
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=full_env,
        text=True,
        creationflags=creationflags | _paths.NO_WINDOW,
    )


def _run_executable(argv, cwd, env, timeout: float, dtype: str) -> dict:
    """Run an executable deliverable under the timeout + stdin-closed discipline.

    Contract:
    - **program**: success = exit 0 within ``timeout``.
    - **script/skill**: success = exit 0 (result-has-no-error). A stream-json
      ``result`` envelope with ``is_error: true`` is treated as a failure even
      if the exit code is 0 (result-no-error contract).

    On timeout the FULL process tree is tree-killed (no orphan), the captured
    output is collected, and status = ``timed-out``. Never hangs the caller.
    """
    proc = _spawn(argv, cwd, env)
    output_box = {"text": ""}

    def _drain():
        try:
            output_box["text"] = proc.stdout.read() or ""
        except (ValueError, OSError):
            output_box["text"] = output_box.get("text", "")

    reader = threading.Thread(target=_drain, daemon=True)
    reader.start()

    timed_out = False
    try:
        exit_code = proc.wait(timeout=max(0.0, float(timeout)))
    except subprocess.TimeoutExpired:
        timed_out = True
        # Reap the whole tree (children + grandchildren) — no orphan.
        _jr._tree_kill(proc.pid)
        try:
            exit_code = proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            exit_code = None

    # Join the reader so we have the captured output (and no dangling thread).
    reader.join(timeout=5)
    try:
        proc.stdout.close()
    except Exception:
        pass

    output = output_box.get("text", "")

    if timed_out:
        return {"status": STATUS_TIMED_OUT, "exit_code": exit_code,
                "timed_out": True, "output_tail": output[-2000:]}

    result_error = _result_has_error(output)
    if dtype in (TYPE_SCRIPT, TYPE_SKILL):
        ok = (exit_code == 0) and not result_error
    else:  # program
        ok = (exit_code == 0)
    return {
        "status": STATUS_SUCCESS if ok else STATUS_FAILED,
        "exit_code": exit_code,
        "timed_out": False,
        "result_error": result_error,
        "output_tail": output[-2000:],
    }


def _result_has_error(output: str) -> bool:
    """True if a stream-json ``result`` line in ``output`` signals an error.

    The script/skill contract is "exit 0 / result-no-error": a skill driven via
    the stream-json primitive ends with a ``{"type":"result", ...}`` envelope; if
    that envelope has ``is_error: true`` (or ``subtype`` == ``error``) the
    deliverable failed even with exit 0. Plain scripts emit no such envelope, so
    this returns False and the exit code alone decides.
    """
    for line in (output or "").splitlines():
        s = line.strip()
        if not s.startswith("{") or '"result"' not in s:
            continue
        try:
            obj = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(obj, dict) or obj.get("type") != "result":
            continue
        if obj.get("is_error") is True:
            return True
        if obj.get("subtype") == "error":
            return True
    return False


# ── Public entry: run a deliverable, report status to the dashboard ─────────

def run_deliverable(dtype: str, target=None, argv=None, cwd=None, env=None,
                    timeout: float = DEFAULT_TIMEOUT,
                    folder_path=None, project_id: str = None,
                    deliverable_id: str = None, name: str = None) -> dict:
    """Run a deliverable per its type contract and persist a status record.

    ``dtype`` is one of doc / script / skill / program.
      - **doc**: pass ``target`` (the doc file). Success = exists + nonempty.
      - **script/skill/program**: pass ``argv`` (the command to run) — or
        ``target`` (a single executable/script path, wrapped as ``[target]``).
        Runs with stdin CLOSED + non-interactive + ``timeout``; a long-running/
        interactive deliverable TIMES OUT CLEANLY (tree reaped, status
        ``timed-out``).

    When ``folder_path`` + ``project_id`` are given, the status record is
    persisted under the project's ``deliverables/`` store so the dashboard can
    show it (status reported to the dashboard — AC1). Returns the status record.
    """
    if dtype not in VALID_TYPES:
        raise ValueError(f"unknown deliverable type: {dtype!r}")
    deliverable_id = deliverable_id or uuid.uuid4().hex

    started = time.time()
    if dtype == TYPE_DOC:
        if target is None:
            raise ValueError("doc deliverable requires a target file")
        outcome = _run_doc(Path(target))
    else:
        cmd = list(argv) if argv else None
        if cmd is None:
            if target is None:
                raise ValueError(f"{dtype} deliverable requires argv or target")
            cmd = [str(target)]
        outcome = _run_executable(cmd, cwd, env, timeout, dtype)
    finished = time.time()

    record = {
        "deliverable_id": deliverable_id,
        "name": name or (str(target) if target else (argv[0] if argv else "")),
        "type": dtype,
        "target": str(target) if target is not None else None,
        "argv": list(argv) if argv else None,
        "started_at": started,
        "finished_at": finished,
        "duration_ms": int((finished - started) * 1000),
        "project_id": project_id,
        "folder_path": str(folder_path) if folder_path is not None else None,
    }
    record.update(outcome)

    if folder_path is not None and project_id is not None:
        _write_status(folder_path, project_id, record)
    return record


# ── Deliverable declare (Anchor.md marker) + pin (Wave 2) ───────────────────
#
# Today a deliverable is only DISCOVERED when it sits under a ``deliverables/``
# directory. The real deliverable (e.g. the running ``anchor_gui.py`` web app)
# lives at the repo root, so it is never found. Two new paths fix that:
#   - DECLARE: an ``Anchor.md`` marker block lists deliverables explicitly.
#   - PIN: a manual pin records ANY path as a deliverable.
# Both surface the deliverable as a DELIVERABLES-lane effort (so it shows up in
# the project window's Deliverables lane), tagged ``source="declared"`` /
# ``source="pinned"`` so it is honestly distinguished from an Anchor-run effort.

#: The Anchor.md heading whose list items declare deliverables. The block is a
#: markdown list; each item is ``- `<rel-path>` — <type> — <description>`` where
#: type and description are optional. Type defaults to inference from the suffix.
_DELIV_HEADING_RE = re.compile(
    r"^#{1,6}\s+Deliverables\b.*$", re.IGNORECASE)
_HEADING_RE = re.compile(r"^#{1,6}\s+")
#: A declared/pinned deliverable list item: a backticked path, optional
#: ``— type`` and ``— description`` (em-dash or hyphen separated).
_DELIV_ITEM_RE = re.compile(
    r"^\s*[-*]\s+`(?P<path>[^`]+)`"
    r"(?:\s*[—-]\s*(?P<type>[A-Za-z]+))?"
    r"(?:\s*[—-]\s*(?P<desc>.+))?\s*$")

#: Marker placed on a deliverables-lane effort that was declared/pinned (vs.
#: brownfield-discovered under ``deliverables/`` or Anchor-run).
SOURCE_DECLARED = "declared"
SOURCE_PINNED = "pinned"


def infer_type(path) -> str:
    """Infer a deliverable type from a path suffix (best-effort).

    ``.md``/``.markdown``/``.txt``/``.pdf`` → ``doc``; ``.py``/``.sh``/``.ps1``/
    ``.js`` → ``script``; anything else → ``program``. The caller may always
    override; this is only the default when none is declared.
    """
    suf = Path(str(path)).suffix.lower()
    if suf in (".md", ".markdown", ".txt", ".pdf", ".rst"):
        return TYPE_DOC
    if suf in (".py", ".sh", ".ps1", ".bat", ".js", ".rb", ".pl"):
        return TYPE_SCRIPT
    return TYPE_PROGRAM


def parse_anchor_md_deliverables(folder_path) -> list:
    """Parse the ``## Deliverables`` declaration block from ``Anchor.md``.

    Returns a list of ``{"path","type","description"}`` dicts (folder-relative
    paths). The block is the markdown list under the first heading whose text
    starts with "Deliverables"; parsing stops at the next heading. Best-effort:
    a missing/unreadable ``Anchor.md`` or absent block yields ``[]`` (never
    raises). ``type`` is inferred from the suffix when not declared.
    """
    md = Path(folder_path) / "Anchor.md"
    try:
        if not md.is_file():
            return []
        text = md.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    in_block = False
    for line in text.splitlines():
        if _DELIV_HEADING_RE.match(line):
            in_block = True
            continue
        if in_block and _HEADING_RE.match(line):
            break  # next heading ends the block
        if not in_block:
            continue
        m = _DELIV_ITEM_RE.match(line)
        if not m:
            continue
        rel = (m.group("path") or "").strip()
        if not rel:
            continue
        dtype = (m.group("type") or "").strip().lower()
        if dtype not in VALID_TYPES:
            dtype = infer_type(rel)
        out.append({
            "path": rel,
            "type": dtype,
            "description": (m.group("desc") or "").strip(),
        })
    return out


def pin_deliverable(folder_path, project_id: str, path: str,
                    name: str = None, dtype: str = None,
                    description: str = "", source: str = SOURCE_PINNED) -> dict:
    """Pin ``path`` as a deliverable → a DELIVERABLES-lane effort record.

    Records a pointer-record in the project's ``deliverables`` lane (via
    ``effort_history``) so the pinned file (e.g. ``anchor_gui.py``) surfaces as
    a deliverables-lane session/effort even though it is NOT under a
    ``deliverables/`` directory. The job_id is content-addressed from the path
    so pinning the same file twice is idempotent (no duplicate effort).

    ``path`` is stored folder-relative when it lives under the folder. ``dtype``
    defaults to ``infer_type(path)``. Returns the stored effort record.

    All writes run under ``paths.WRITE_LOCK`` (via ``effort_history``).
    """
    rel = _relpath(folder_path, path)
    dtype = (dtype or "").strip().lower() or infer_type(rel)
    if dtype not in VALID_TYPES:
        dtype = infer_type(rel)
    jid = _eh.discovered_job_id("deliverables", f"pin::{rel}")
    extra = {
        "source": source,
        "kind": f"deliverable-{dtype}",
        "deliverable_type": dtype,
        "title": name or Path(rel).name,
        "artifact_path": rel,
        "description": description or "",
        "status": "pinned",
    }
    with _journal.journaled(project_id, _journal.EV_DELIVERABLE_PINNED,
                            correlation_id=project_id, folder_path=folder_path,
                            payload={"path": path}):
        return _eh.record_effort(folder_path, project_id, "deliverables", jid,
                                 extra=extra)


def _relpath(folder_path, path: str) -> str:
    """Folder-relative POSIX path for a deliverable, traversal-safe.

    Reuses the same containment discipline as the ``/artifact`` file route
    (``report_viewer.resolve_project_artifact`` / ``katex_asset``): resolve the
    candidate against the folder and require it to stay *inside* the folder.

    - An in-folder RELATIVE path → returned folder-relative (POSIX), unchanged
      semantics.
    - An ABSOLUTE path UNDER the folder → relativized (existing behavior, kept).
    - A path (relative OR absolute) that ESCAPES the folder — ``..`` traversal,
      an absolute path outside the folder, or a symlink-escape — is REJECTED
      with a ``ValueError`` so :func:`pin_deliverable` never stores an
      out-of-folder artifact path. (Mirrors the route's "reject" branch, which
      reads zero bytes.)
    """
    p = Path(str(path))
    try:
        folder = Path(folder_path).resolve()
        target = (folder / p).resolve()
    except OSError as e:
        raise ValueError(f"unresolvable deliverable path: {path!r}") from e
    # Containment: target must stay within the folder (same as the /artifact
    # route's ``target.relative_to(folder.resolve())`` check).
    try:
        return target.relative_to(folder).as_posix()
    except ValueError:
        raise ValueError(
            f"deliverable path escapes project folder: {path!r}") from None


def declare_deliverables_from_marker(folder_path, project_id: str) -> dict:
    """Pin every deliverable declared in ``Anchor.md`` (declare path).

    Parses the marker block (:func:`parse_anchor_md_deliverables`) and pins each
    entry as a ``source="declared"`` deliverables-lane effort. Idempotent
    (job_id-keyed). Returns ``{"declared": n, "items": [...]}``.
    """
    items = parse_anchor_md_deliverables(folder_path)
    pinned = []
    with _paths.WRITE_LOCK:
        for it in items:
            rec = pin_deliverable(folder_path, project_id, it["path"],
                                  dtype=it.get("type"),
                                  description=it.get("description", ""),
                                  source=SOURCE_DECLARED)
            pinned.append(rec)
    return {"declared": len(pinned), "items": pinned}


def list_pinned_deliverables(folder_path, project_id: str) -> list:
    """Return the declared/pinned deliverable efforts for a project.

    These are the deliverables-lane effort records whose ``source`` is
    ``declared`` or ``pinned`` (newest-first, as ``effort_history`` returns).
    """
    out = []
    for rec in _eh.list_efforts(folder_path, project_id, "deliverables"):
        if rec.get("source") in (SOURCE_DECLARED, SOURCE_PINNED):
            out.append(rec)
    return out


def get_pinned_deliverable(folder_path, project_id: str, deliverable_id: str):
    """Return the pinned/declared deliverable effort whose ``job_id`` matches.

    Deliverables are surfaced as deliverables-lane effort records keyed by a
    content-addressed ``job_id`` (see :func:`pin_deliverable`). ``launch_*`` and
    the launch endpoint identify a deliverable by that id. Returns the record
    dict or ``None`` (unknown id → the endpoint answers 404).
    """
    for rec in list_pinned_deliverables(folder_path, project_id):
        if rec.get("job_id") == deliverable_id:
            return rec
    return None


# ── v5 Wave 4: deliverable PER FOREMAN BUILD (resolve · backfill) ────────────
#
# Every Build (Foreman) session resolves a DELIVERABLE — the artifact that build
# produced. The cardinal rule (Master Plan Risk R4) is **never guess**: a
# deliverable is resolved ONLY from explicit signals, in a fixed priority order,
# and when no explicit signal exists the result is ``resolved=False`` with an
# honest reason — NEVER a fabricated path.
#
# Signal priority (strongest first), all explicit:
#   1. the build session's ``deliverable`` DOC-ROLE — summarizer.session_doc_roles
#      resolves the build lane's ``deliverable`` role (the project's pinned/linked
#      deliverable, already grounded). This is the strongest "what this build
#      produced" signal.
#   2. a PRODUCT member file of the build session — a session member with an
#      ``artifact_path`` that is a real product artifact (NOT a plan/log doc:
#      north-star / execution-log / master-plan / implementation-plan).
#   3. an already-PINNED / DECLARED deliverable (list_pinned_deliverables) — the
#      newest. (A prior build's auto-pin re-resolves to itself → idempotent.)
#   4. a DECLARED ``Anchor.md`` ``## Deliverables`` marker entry.
#   5. (WEAK / opt-in) a ``foreman.config`` entry that CLEARLY names a product
#      artifact. ``foreman.config``'s ``docs`` block lists PLAN docs (description /
#      plan / execution_log), NOT the product, so it is treated as a weak signal
#      and only used when ``allow_config`` is set AND the entry is not a plan doc.
#
# AMBIGUOUS (e.g. several unrelated candidate members with no role/pin) → left
# UNRESOLVED rather than guessing.

#: Basenames (lowercased, prefix-matched) that are trio PLAN/LOG/CONFIG docs,
#: never the product artifact a build delivers. Used to reject these as a build's
#: deliverable (a foreman build session's discovered members ARE these trio files
#: — the product is named by a pin/marker/doc-role, not by a config/log member).
_PLAN_DOC_PREFIXES = (
    "north-star", "master-plan", "implementation-plan", "execution-log",
    "decision-log", "handoff", "readme", "claude.md", "anchor.md",
    "foreman.config", "foreman-checkpoint", "foreman.checkpoint",
)


def _is_plan_doc(rel: str) -> bool:
    """True if ``rel``'s basename is a trio plan/log/config doc (not a product)."""
    base = Path(str(rel).replace("\\", "/")).name.lower()
    return any(base.startswith(p) for p in _PLAN_DOC_PREFIXES)


def _deliverable_view(folder_path, project_id, name, rel, dtype, source,
                      href=None):
    """Build the structured ``deliverable`` view dict, traversal-guarded.

    ``rel`` is run through :func:`_relpath` (the same containment guard the pin
    path uses) so a surfaced path can NEVER escape the project folder. A path
    that fails the guard yields ``None`` (the caller then reports unresolved —
    never a fabricated/out-of-folder path).
    """
    rel = (rel or "").strip().replace("\\", "/")
    if not rel:
        return None
    try:
        safe_rel = _relpath(folder_path, rel)
    except ValueError:
        return None
    if not dtype or dtype not in VALID_TYPES:
        dtype = infer_type(safe_rel)
    if href is None:
        href = _doc_href(project_id, safe_rel)
    return {
        "name": name or Path(safe_rel).name,
        "path": safe_rel,
        "rel": safe_rel,
        "type": dtype,
        "source": source,
        "href": href,
    }


def _is_effort_subject(bs: dict) -> bool:
    """True iff ``bs`` is a v12 EFFORT subject (carries stage fields), not a
    legacy discovered build_session.

    An effort carries ``stage_history`` and/or ``current_stage`` (set by the v12
    record + advance path) plus a ``session_id``/``effort_id``. A legacy
    discovered build session from ``sessions.list_sessions`` has neither stage
    field, so this is False for it — preserving the existing behavior exactly.
    """
    if not isinstance(bs, dict):
        return False
    if "stage_history" not in bs and "current_stage" not in bs:
        return False
    return bool(bs.get("session_id") or bs.get("effort_id"))


def resolve_build_deliverable(folder_path, project_id: str,
                              build_session: dict,
                              allow_config: bool = False) -> dict:
    """Resolve the artifact a BUILD session produced — EXPLICIT signals only.

    Returns ``{"resolved": bool, "deliverable": {...}|None, "reason": str,
    "signal": str}``. ``deliverable`` (when resolved) carries
    ``{name, path, rel, type, source, href}`` with a traversal-guarded path. When
    no explicit signal resolves an artifact → ``resolved=False`` with an honest
    ``reason`` and ``deliverable=None`` (NEVER a fabricated path; see Risk R4).

    Resolution is SESSION-SCOPED (Risk R4 — never attribute one build's product to
    another): (1) the build session's OWN product member file (a non-plan/log
    member; >1 candidate → ambiguous unless a pin matches exactly one); (2) a
    pinned/declared deliverable whose path is a MEMBER of THIS session; (3) ONLY
    when the project has a SINGLE build session, the project-level newest pin /
    ``Anchor.md`` marker / [opt-in] ``foreman.config`` product. With multiple
    builds and no session-scoped signal → honest unresolved. Stdlib only; never
    raises (any failure → unresolved with a reason).
    """
    bs = build_session or {}

    # v12 Wave 3 — EFFORT subject (carries stage fields): feed the resolver ONLY
    # the BUILD-stage doc set, so a plan-stage MASTER-PLAN.md can never be
    # mis-resolved as the build product (Shark C6). An effort subject is one that
    # carries ``stage_history`` (or ``current_stage``) + a ``session_id``; a
    # legacy (non-effort) discovered build_session from ``sessions.list_sessions``
    # has neither, so its existing behavior is untouched.
    if _is_effort_subject(bs):
        cur = (bs.get("current_stage") or "").strip()
        if cur != "build":
            return {"resolved": False, "deliverable": None, "signal": "none",
                    "reason": ("effort is at stage %r, not build — no build "
                               "deliverable yet" % (cur or "?"))}
        sid = bs.get("session_id") or bs.get("effort_id") or ""
        try:
            build_efforts = _eh.efforts_for_session_stage(
                folder_path, project_id, sid, "build")
        except Exception:
            build_efforts = []
        if not build_efforts:
            return {"resolved": False, "deliverable": None, "signal": "none",
                    "reason": "no build-stage docs persisted for this effort yet"}
        # Re-shape the build-stage efforts into the member_files the
        # session-scoped resolver below understands, then fall through.
        bs = dict(bs)
        bs["member_files"] = build_efforts

    members = bs.get("member_files", []) or []

    # SESSION-SCOPED resolution (v5 Wave 4 fix). The ONLY honest "what THIS build
    # produced" signal is the build session's own files. A project-level pin /
    # marker / config is attributed to a build ONLY when it is session-tied OR the
    # project has a SINGLE build (unambiguous). With several builds we refuse to
    # guess which build a project-level deliverable belongs to (Risk R4) — earlier
    # this used the PROJECT-scoped `deliverable` doc-role / newest pin, so EVERY
    # build panel falsely claimed the same artifact regardless of what it produced.
    product_members = []
    for m in members:
        rel = (m.get("artifact_path") or "").strip()
        if not rel or _is_plan_doc(rel):
            continue
        product_members.append(m)

    try:
        pinned = list_pinned_deliverables(folder_path, project_id)
    except Exception:
        pinned = []
    pinned_by_rel = {}
    for rec in pinned:
        pr = (rec.get("artifact_path") or "").strip().replace("\\", "/")
        if pr and pr not in pinned_by_rel:
            pinned_by_rel[pr] = rec

    def _norm(r):
        return (r or "").strip().replace("\\", "/")

    def _member_view(m, rec=None):
        rel = m.get("artifact_path") or ""
        return _deliverable_view(
            folder_path, project_id,
            name=(rec.get("title") if rec else None)
                 or m.get("title") or Path(_norm(rel)).name,
            rel=rel,
            dtype=(((rec.get("deliverable_type") if rec else "") or "")
                   .strip().lower() or None),
            source=(rec.get("source") if rec else None) or "build-output")

    def _pin_view(rec):
        return _deliverable_view(
            folder_path, project_id, name=rec.get("title"),
            rel=rec.get("artifact_path") or "",
            dtype=(rec.get("deliverable_type") or "").strip().lower() or None,
            source=rec.get("source") or SOURCE_PINNED)

    # (1) The build session's OWN product member(s) — authoritative.
    if len(product_members) == 1:
        m = product_members[0]
        rec = pinned_by_rel.get(_norm(m.get("artifact_path")))
        view = _member_view(m, rec)
        if view:
            return {"resolved": True, "deliverable": view,
                    "signal": ("pinned" if rec else "build-output"),
                    "reason": ("resolved from this build's pinned product file"
                               if rec else
                               "resolved from the build session's product file")}
    elif len(product_members) > 1:
        # Several candidate products: a pin matching EXACTLY ONE disambiguates;
        # otherwise genuinely ambiguous → unresolved (never a guess; Risk R4).
        matched = [m for m in product_members
                   if _norm(m.get("artifact_path")) in pinned_by_rel]
        if len(matched) == 1:
            m = matched[0]
            view = _member_view(m, pinned_by_rel.get(_norm(m.get("artifact_path"))))
            if view:
                return {"resolved": True, "deliverable": view, "signal": "pinned",
                        "reason": "resolved from this build's pinned product file"}
        return {"resolved": False, "deliverable": None, "signal": "ambiguous",
                "reason": ("ambiguous — %d candidate build artifacts; pin one"
                           % len(product_members))}

    # (2) No clear product member: a pinned/declared deliverable whose path is a
    # MEMBER of THIS session (session-tied — safe even with multiple builds).
    member_rels = {_norm(m.get("artifact_path")) for m in members}
    for pr, rec in pinned_by_rel.items():
        if pr in member_rels:
            view = _pin_view(rec)
            if view:
                return {"resolved": True, "deliverable": view, "signal": "pinned",
                        "reason": "resolved from this build's pinned product file"}

    # v12 — an EFFORT subject is resolved ONLY from its own build-stage docs (a
    # member product, or a pin matching a build-stage member). It NEVER falls
    # through to a project-level pin/marker/config (which could be a plan-stage
    # MASTER-PLAN.md) — honest unresolved instead (Shark C6).
    if _is_effort_subject(build_session or {}):
        return {"resolved": False, "deliverable": None, "signal": "none",
                "reason": "no build-stage deliverable signal for this effort yet"}

    # (3) Project-level fallback (newest pin / declared marker / [opt-in] config)
    # ONLY when this is the project's SOLE build session → attribution is
    # unambiguous. With MORE THAN ONE build, refuse to guess (Risk R4) → honest
    # unresolved so the user pins this build's deliverable explicitly.
    try:
        import sessions as _sessions
        build_count = len(_sessions.list_sessions(folder_path, project_id,
                                                  "build"))
    except Exception:
        build_count = 1
    if build_count <= 1:
        if pinned:
            view = _pin_view(pinned[0])
            if view:
                return {"resolved": True, "deliverable": view, "signal": "pinned",
                        "reason": "resolved from the project's pinned deliverable"}
        try:
            marker = parse_anchor_md_deliverables(folder_path)
        except Exception:
            marker = []
        if marker:
            it = marker[0]
            view = _deliverable_view(
                folder_path, project_id, name=Path(it["path"]).name,
                rel=it["path"], dtype=it.get("type"), source=SOURCE_DECLARED)
            if view:
                return {"resolved": True, "deliverable": view, "signal": "marker",
                        "reason": "resolved from an Anchor.md Deliverables marker"}
        if allow_config:
            view = _resolve_from_foreman_config(folder_path, project_id)
            if view:
                return {"resolved": True, "deliverable": view, "signal": "config",
                        "reason": "resolved from a foreman.config product entry"}
        reason = "no deliverable pinned yet"
    else:
        reason = ("no deliverable for this build yet — multiple builds; "
                  "pin this build's deliverable")
    return {"resolved": False, "deliverable": None, "signal": "none",
            "reason": reason}


def _rel_from_artifact_href(href: str) -> str:
    """Recover the ``path`` rel from an ``/artifact/<pid>?path=<rel>`` href."""
    try:
        from urllib.parse import urlparse, parse_qs, unquote
        q = parse_qs(urlparse(href).query)
        return unquote((q.get("path", [""])[0]) or "")
    except Exception:
        return ""


def _resolve_from_foreman_config(folder_path, project_id):
    """[Weak] resolve a PRODUCT artifact named in ``foreman.config(.json)``.

    ``foreman.config``'s ``docs`` block lists PLAN docs (description / plan /
    execution_log), which are NOT the product — those are rejected by
    :func:`_is_plan_doc`. Only a non-plan-doc product path under a ``deliverable``/
    ``product``/``artifact`` key (or an explicit ``deliverable`` value) is used.
    Returns a deliverable view or ``None``. Best-effort, never raises.
    """
    for nm in ("foreman.config.json", "foreman.config"):
        p = Path(folder_path) / nm
        try:
            if not p.is_file():
                continue
            cfg = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(cfg, dict):
            continue
        # Explicit product keys only — never the ``docs`` (plan) block.
        candidates = []
        for key in ("deliverable", "product", "artifact"):
            v = cfg.get(key)
            if isinstance(v, str) and v.strip():
                candidates.append(v.strip())
        for rel in candidates:
            if _is_plan_doc(rel):
                continue
            view = _deliverable_view(folder_path, project_id,
                                     name=Path(rel).name, rel=rel,
                                     dtype=None, source="config")
            if view:
                return view
    return None


def backfill_build_deliverables(folder_path, project_id: str,
                                allow_config: bool = False) -> dict:
    """Scan a project's BUILD sessions and AUTO-PIN unambiguously resolved
    deliverables so they surface in the Deliverables lane (v5 Wave 4 backfill).

    For each build session (``sessions.list_sessions(.., 'build')``),
    :func:`resolve_build_deliverable` is run; where it resolves an artifact from
    an EXPLICIT, unambiguous signal, that artifact is pinned via
    :func:`pin_deliverable` (content-addressed → IDEMPOTENT: re-running backfill
    never duplicates). A build whose deliverable is UNRESOLVED/ambiguous is left
    UNPINNED (never fabricated). Returns
    ``{"pinned": [...records], "unresolved": [{session_id, reason}], "scanned": n}``.

    A pin whose source is already a pinned/declared deliverable (signal
    ``"pinned"`` / ``"marker"``) is NOT re-pinned (it is already in the lane) — so
    backfill only adds NEW build outputs / doc-role artifacts. Stdlib only; never
    raises (a per-session failure is recorded as unresolved).
    """
    import sessions as _sessions
    pinned_out = []
    unresolved = []
    scanned = 0
    try:
        build_sessions = _sessions.list_sessions(folder_path, project_id, "build")
    except Exception:
        build_sessions = []
    try:
        already = {(r.get("artifact_path") or "").strip().replace("\\", "/")
                   for r in list_pinned_deliverables(folder_path, project_id)}
    except Exception:
        already = set()
    for bs in build_sessions:
        scanned += 1
        sid = bs.get("session_id") or ""
        try:
            res = resolve_build_deliverable(folder_path, project_id, bs,
                                            allow_config=allow_config)
        except Exception as e:  # never let one session break the scan
            unresolved.append({"session_id": sid, "reason": f"error: {e}"})
            continue
        if not res.get("resolved"):
            unresolved.append({"session_id": sid,
                               "reason": res.get("reason", "unresolved")})
            continue
        signal = res.get("signal")
        deliv = res.get("deliverable") or {}
        # A "pinned" signal is ALREADY a deliverables-lane pin record → no new
        # pin (the ``already`` guard below also covers re-runs). A "marker" /
        # "doc-role" / "build-output" signal names a real product that may not
        # yet be a pin record, so it IS pinned (idempotent via ``already``).
        if signal == "pinned":
            continue
        rel = deliv.get("rel") or deliv.get("path") or ""
        if not rel:
            unresolved.append({"session_id": sid,
                               "reason": "resolved without a path"})
            continue
        if rel.replace("\\", "/") in already:
            continue  # already in the lane — idempotent, no disk churn
        # A marker-resolved deliverable is honestly recorded as DECLARED; any
        # other auto-resolved product (doc-role / build-output) as PINNED.
        src = (SOURCE_DECLARED if deliv.get("source") == SOURCE_DECLARED
               else SOURCE_PINNED)
        try:
            rec = pin_deliverable(
                folder_path, project_id, rel,
                name=deliv.get("name"),
                dtype=deliv.get("type"),
                description=f"auto-pinned from build session {sid}",
                source=src)
            pinned_out.append(rec)
            already.add(rel.replace("\\", "/"))
        except ValueError as e:  # traversal guard rejected — never fabricate
            unresolved.append({"session_id": sid, "reason": str(e)})
    return {"pinned": pinned_out, "unresolved": unresolved, "scanned": scanned}


# ── v4 Wave 7: type-aware launch ────────────────────────────────────────────
#
# Every Foreman run auto-pins one deliverable. Clicking *launch* adapts to the
# deliverable TYPE (canonical UI: the "📦 Deliverable" Extras card):
#   - skill / tool → VERIFY status only (available | loaded | missing). NO spawn.
#   - service      → launch a PERSISTENT preview (reuses preview_server's
#                    discipline: free port != 8777, isolated temp data dir,
#                    loopback bind, health-check). A SECOND launch pulls up the
#                    already-running one instead of double-spawning.
#   - program      → run in a window: run-to-result via run_deliverable (captured
#                    output / exit-0 contract).
#   - doc          → return the rendered view href (the existing /artifact route;
#                    report_viewer renders markdown).
#
# Reuses preview_server + report_viewer + the deliverables run/pin primitives —
# nothing is forked. Every spawned port is OS-assigned + HARD-guarded != 8777
# with an isolated temp data dir; nothing touches the live :8777 or real data.

#: Verify-status values returned for skill/tool launches (no process spawn).
VERIFY_AVAILABLE = "available"
VERIFY_LOADED = "loaded"
VERIFY_MISSING = "missing"

#: The user's agent-skills root (``~/.claude/skills/<name>``). Overridable via
#: ``ANCHOR_SKILLS_DIR`` so tests verify against a temp dir — NEVER the live one.
_SKILLS_ENV = "ANCHOR_SKILLS_DIR"
#: The user's agent-tools root, if configured (``ANCHOR_TOOLS_DIR``). Tools have
#: no single canonical on-disk home, so tool verification is registry/dir-based
#: and overridable for tests; absent → the tool is reported ``missing`` honestly.
_TOOLS_ENV = "ANCHOR_TOOLS_DIR"


def _skills_root() -> Path:
    """The agent-skills directory (``$ANCHOR_SKILLS_DIR`` else ``~/.claude/skills``)."""
    override = os.environ.get(_SKILLS_ENV)
    if override:
        return Path(override)
    return Path.home() / ".claude" / "skills"


def _tools_root():
    """The agent-tools directory if configured (``$ANCHOR_TOOLS_DIR``), else None."""
    override = os.environ.get(_TOOLS_ENV)
    return Path(override) if override else None


def _verify_name(rec: dict) -> str:
    """The skill/tool identifier to verify — the title, else the artifact stem."""
    name = (rec.get("title") or "").strip()
    if name:
        return name
    rel = rec.get("artifact_path") or ""
    return Path(rel).stem or rel


def verify_skill_or_tool(dtype: str, rec: dict) -> dict:
    """Verify a skill/tool deliverable's STATUS by existence — NO process spawn.

    A skill is "available" if present on disk under the skills root; a tool is
    "available" if present under the (configured) tools root. We deliberately do
    NOT spawn anything: a deliverable's skill/tool is verified by
    existence/registry only (IMPLEMENTATION-PLAN Wave 7 — "verify available /
    loaded; NO spawn"). ``loaded`` (runtime-active) is reported when a presence
    marker indicates an active load; absent the marker we report ``available``
    for a present skill/tool. Returns ``{kind, status, detail, name}``.
    """
    name = _verify_name(rec)
    if dtype == TYPE_SKILL:
        root = _skills_root()
        sdir = root / name
        # A skill is "available" if its directory (or a SKILL.md) is present.
        present = sdir.is_dir() or (root / f"{name}.md").is_file() \
            or (sdir / "SKILL.md").is_file()
        if present:
            return {"kind": TYPE_SKILL, "status": VERIFY_AVAILABLE,
                    "name": name,
                    "detail": f"skill {name!r} present at {sdir}"}
        return {"kind": TYPE_SKILL, "status": VERIFY_MISSING, "name": name,
                "detail": f"skill {name!r} not found under {root}"}
    # tool
    root = _tools_root()
    if root is not None:
        tdir = root / name
        present = tdir.exists() or (root / f"{name}.py").is_file() \
            or (root / f"{name}.json").is_file()
        if present:
            return {"kind": TYPE_TOOL, "status": VERIFY_AVAILABLE, "name": name,
                    "detail": f"tool {name!r} present under {root}"}
        return {"kind": TYPE_TOOL, "status": VERIFY_MISSING, "name": name,
                "detail": f"tool {name!r} not found under {root}"}
    return {"kind": TYPE_TOOL, "status": VERIFY_MISSING, "name": name,
            "detail": "no tools registry configured (set ANCHOR_TOOLS_DIR)"}


def _doc_href(project_id: str, rel: str) -> str:
    """The rendered-view href for a ``doc`` deliverable (the /artifact route).

    Reuses the existing traversal-safe ``GET /artifact/<pid>?path=<rel>`` route,
    which serves a discovered artifact (markdown is rendered by report_viewer).
    """
    from urllib.parse import quote
    return f"/artifact/{quote(project_id, safe='')}?path={quote(rel, safe='')}"


def launch_deliverable(folder_path, project_id: str, deliverable_id: str,
                       preview_mod=None, health_timeout: float = None,
                       timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Type-aware launch of a pinned deliverable. Dispatches on its type.

    Resolves the pinned deliverable by ``deliverable_id`` (its content-addressed
    ``job_id``) and adapts:

    - **skill / tool** → VERIFY status only (``available`` | ``loaded`` |
      ``missing``); returns ``{ok, kind, type, status, detail}``. NO spawn.
    - **service** → launch a PERSISTENT preview (``preview_server.start_preview``
      — free port != 8777, isolated temp ``ANCHOR_DATA_DIR``, loopback bind,
      health-check before returning the URL). If a RUNNING preview for this
      deliverable's target already exists, PULL IT UP (return its URL) instead
      of double-spawning. Returns ``{ok, type, url, port, preview_id, pulled_up}``.
    - **program** → run-to-result via :func:`run_deliverable` (captured output /
      exit-0 contract, stdin closed, tree-kill on timeout). Returns
      ``{ok, type, status, record}``.
    - **doc** → return the rendered-view href (existing ``/artifact`` route).
      Returns ``{ok, type, href}``.

    ``preview_mod`` lets a test inject a stubbed ``preview_server`` (so the gate
    never spawns a real long-running server bound to a real port). Unknown id →
    ``{ok: False, reason: "unknown deliverable"}`` (the endpoint maps that to a
    404).
    """
    rec = get_pinned_deliverable(folder_path, project_id, deliverable_id)
    if rec is None:
        return {"ok": False, "reason": "unknown deliverable",
                "deliverable_id": deliverable_id}

    _journal.emit_safe(project_id, _journal.EV_DELIVERABLE_LAUNCHED,
                       correlation_id=(deliverable_id or project_id),
                       folder_path=folder_path,
                       payload={"deliverable_id": deliverable_id})

    dtype = (rec.get("deliverable_type") or "").strip().lower()
    if dtype not in VALID_TYPES:
        dtype = infer_type(rec.get("artifact_path") or "")
    rel = rec.get("artifact_path") or ""

    # skill / tool → verify only, never spawn.
    if dtype in VERIFY_TYPES:
        res = verify_skill_or_tool(dtype, rec)
        return {"ok": True, "type": dtype, "deliverable_id": deliverable_id,
                **res}

    # doc → rendered view href (no process).
    if dtype == TYPE_DOC:
        if not rel:
            return {"ok": False, "reason": "doc deliverable has no path",
                    "deliverable_id": deliverable_id}
        return {"ok": True, "type": TYPE_DOC, "deliverable_id": deliverable_id,
                "href": _doc_href(project_id, rel)}

    # service → persistent preview; pull up the running one if present.
    if dtype == TYPE_SERVICE:
        pv = preview_mod
        if pv is None:
            import preview_server as pv  # lazy: only services need it
        # Pull-up-if-running: a live preview for this target is reused, not
        # double-spawned.
        for prev in pv.list_previews(project_id):
            if (prev.get("status") == pv.STATUS_RUNNING
                    and (prev.get("target") or "") == rel):
                return {"ok": True, "type": TYPE_SERVICE,
                        "deliverable_id": deliverable_id,
                        "url": prev.get("url"), "port": prev.get("port"),
                        "preview_id": prev.get("preview_id"),
                        "pulled_up": True}
        kw = {}
        if health_timeout is not None:
            kw["health_timeout"] = health_timeout
        res = pv.start_preview(folder_path, project_id, target=rel, **kw)
        if not res.get("ok"):
            return {"ok": False, "type": TYPE_SERVICE,
                    "deliverable_id": deliverable_id,
                    "reason": res.get("reason", "preview did not start"),
                    "port": res.get("port")}
        return {"ok": True, "type": TYPE_SERVICE,
                "deliverable_id": deliverable_id,
                "url": res.get("url"), "port": res.get("port"),
                "preview_id": res.get("preview_id"), "pulled_up": False}

    # program (or script) → run-to-result with the per-type contract.
    target_path = rel
    try:
        abs_target = (Path(folder_path) / rel).as_posix() if rel else None
    except Exception:
        abs_target = rel
    record = run_deliverable(
        TYPE_PROGRAM if dtype == TYPE_PROGRAM else TYPE_SCRIPT,
        argv=[sys.executable, abs_target] if (abs_target and
              Path(str(abs_target)).suffix.lower() == ".py") else None,
        target=abs_target,
        cwd=folder_path,
        timeout=timeout,
        folder_path=folder_path,
        project_id=project_id,
        deliverable_id=deliverable_id,
        name=rec.get("title") or rel,
    )
    return {"ok": record.get("status") == STATUS_SUCCESS, "type": dtype,
            "deliverable_id": deliverable_id, "status": record.get("status"),
            "record": record}
