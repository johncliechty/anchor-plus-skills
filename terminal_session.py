#!/usr/bin/env python3
"""Anchor live terminal session service — Wave 3 of v3 "Mission Control".

Ties together the three Wave-1/Wave-2 substrates into one live session service:

- ``pty_manager`` (Wave 1) — the real ConPTY / stub PTY child;
- ``session_registry`` (Wave 2) — the durable, restart-surviving registry;
- ``worktrees`` (Wave 2) — per-session git-worktree isolation.

The keystone flow (per the Wave-2 seam recorded in ``EXECUTION-LOG.md``):

    mint sid -> worktrees.create_worktree(pid, sid)
             -> pty_manager.start([backend], cwd=worktree_path)  (BARE shell —
                NO auto-seeded skill/prompt; that is a later wave's concern)
             -> session_registry.register_session(..., status=RUNNING,
                                                  session_id=sid)

The **same id** is used as both the pty_manager session id and the registry
``session_id`` — minted once, threaded through — so there is exactly ONE id per
session.

``attach`` REATTACHES by replaying the live screen buffer (``read_since`` from
cursor 0); detach is implicit (a client simply stops reading — NOTHING is killed
on detach, the process keeps running). ``kill`` reaps the PTY, marks the registry
record terminal, and removes the worktree.

Every entry point tolerates an unknown / already-dead session cleanly (clear
error dict, never a crash). Stdlib only; the native PTY dep is isolated in
``pty_manager`` and selected by ``ANCHOR_PTY_BACKEND`` (``stub`` in all tests).
"""

import json
import os
import sys
import re
import threading
import uuid
from pathlib import Path, PurePosixPath

import paths as _paths
import pty_manager as _pty
import session_registry as _reg
import worktrees as _wt
import rnd_registry as _rnd
import effort_history as _eh  # v8 Wave 2 keystone: persist_session_docs (no
#                              cycle: effort_history imports neither this module
#                              nor session_registry — only paths + rnd_registry)
import handoff as _handoff  # v6 Wave 6 auto-advance (no cycle: handoff imports
#                            neither terminal_session nor session_registry)
import journal as _journal  # rearch W12 (C3): the per-project event journal.
#                            The FIRST instrumented class — session lifecycle
#                            mutations dual-write journal-first (D1). No cycle:
#                            journal imports only paths + pillar_flags (lazily
#                            rnd_registry / tools.write_tripwire).
try:
    import boneyard as _boneyard  # v10 Wave 6 Boneyard capture (stdlib-only; no
    #                              cycle: boneyard imports only paths +
    #                              rnd_registry, lazily summarizer/effort_history)
except Exception:  # pragma: no cover - boneyard is always importable, defensive
    _boneyard = None

try:
    import lanes as _lanes
except Exception:  # pragma: no cover - lanes is always importable, defensive
    _lanes = None

try:
    import usage_capture as _usage  # Honest Telemetry W4: the ONE usage-capture
    #                                 finalize path (no cycle: usage_capture imports
    #                                 paths + session_registry + effort_history +
    #                                 usage_ledger, never this module).
except Exception:  # pragma: no cover - usage_capture is always importable
    _usage = None


def _finalize_usage_safe(session_id, project_id=None, record=None):
    """Eager end-path usage finalize — the ONE seam wired into kill / close-park /
    drain / finish / reconcile-dead. Idempotent (the W2 ``cost_final`` CAS) and
    BEST-EFFORT: a capture failure or a fail-closed sidecar root can NEVER break
    or halt the session end path. A no-op when the pipeline is unavailable."""
    if _usage is None:
        return None
    try:
        return _usage.finalize_session_usage(
            session_id, project_id=project_id, record=record)
    except Exception:
        return None


def finalize_usage(session_id, project_id=None, record=None):
    """Public passthrough for the eager end-path usage finalize (W4).

    The ``finish→build`` endpoint marks a planning session DONE via the registry
    WITHOUT reaping it (so no ``kill`` runs) — that terminal transition IS a
    'finish' end path, so it calls this to finalize the session's usage exactly
    like every other end path. Idempotent + best-effort."""
    return _finalize_usage_safe(session_id, project_id=project_id, record=record)


#: Backends this service accepts (mirrors session_registry.VALID_BACKENDS).
VALID_BACKENDS = set(_reg.VALID_BACKENDS)


def _default_engine() -> str:
    """Interactive default engine from durable settings (lazy; never raises).

    Falls back to the settings-schema default (``grok``) if ``anchor_settings``
    is unavailable. Job-layer launches keep ``job_runner.DEFAULT_BACKEND``
    (claude) separately.
    """
    try:
        from anchor_settings import get_default_cli
        return get_default_cli()
    except Exception:
        return _reg.BACKEND_GROK


#: Default engine when a project has never picked one (v4 Wave 2).
#: Resolved lazily via :func:`_default_engine` so settings changes apply without
#: re-import. Module attribute kept for callers/tests that read the name —
#: prefer :func:`_default_engine` / :func:`last_engine_for_project` at runtime.
DEFAULT_ENGINE = _reg.BACKEND_GROK  # settings default; see _default_engine()

#: Per-project last-used-engine pointer file, stored alongside the per-project
#: cache under ``<folder>/.anchor/projects/<id>/`` (the convention summarizer
#: uses for its project-summary.json). Persisted atomically under WRITE_LOCK.
ENGINE_POINTER_NAME = "engine.json"


# ── Per-project last-used engine persistence (v4 Wave 2) ─────────────────────
#
# The chosen engine (claude|gemini|grok) is selected ONCE per session, but a
# project "remembers" its last-used engine so a fresh session defaults to it.
# Persisted as ``{"last_engine": "<engine>"}`` in ``engine.json`` under the
# per-project store dir — the SAME ``<folder>/.anchor/projects/<id>/`` directory
# summarizer caches into. Atomic write (tmp + os.replace) under
# ``paths.WRITE_LOCK`` so a concurrent ThreadingHTTPServer writer / crash
# mid-write can't corrupt it.


def _engine_pointer_path(project_id) -> Path:
    """``<folder>/.anchor/projects/<id>/engine.json`` (not created).

    Returns ``None`` if the project (and thus its folder) cannot be resolved.
    """
    proj = _rnd.get_project(project_id)
    if proj is None:
        return None
    folder = proj.get("folder_path", "")
    if not folder:
        return None
    return _rnd.project_store_dir(folder, project_id) / ENGINE_POINTER_NAME


def last_engine_for_project(project_id) -> str:
    """Return the project's last-used engine, defaulting via settings when unset.

    Best-effort: a missing/corrupt/unreadable pointer (or an unknown project)
    returns the interactive default from :func:`_default_engine` (settings
    ``default_cli``, currently ``grok``). An out-of-range persisted value (not a
    known backend) also falls back to the default rather than propagating garbage.
    """
    fallback = _default_engine()
    p = _engine_pointer_path(project_id)
    if p is None or not p.exists():
        return fallback
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, ValueError):
        return fallback
    eng = data.get("last_engine") if isinstance(data, dict) else None
    if eng in VALID_BACKENDS:
        return eng
    return fallback


def set_last_engine_for_project(project_id, engine) -> bool:
    """Persist the project's last-used engine (atomic, under WRITE_LOCK).

    No-op (returns ``False``) for an unknown backend or an unresolvable project;
    otherwise writes ``{"last_engine": engine}`` and returns ``True``. A write
    failure is swallowed (returns ``False``) — remembering the engine is a
    convenience, never worth crashing a live session over.
    """
    if engine not in VALID_BACKENDS:
        return False
    p = _engine_pointer_path(project_id)
    if p is None:
        return False
    try:
        with _paths.WRITE_LOCK:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text(
                json.dumps({"last_engine": engine}, ensure_ascii=False),
                encoding="utf-8")
            os.replace(str(tmp), str(p))
        return True
    except OSError:
        return False


# ── Per-lane skill-seed map (v4 Wave 1) ──────────────────────────────────────
#
# Kill the repeating-prompt bug at the root: a brand-new cockpit terminal session
# auto-loads its lane's trio skill exactly ONCE, greets ONCE, then behaves like a
# normal interactive terminal. The seed is a SINGLE opening stdin turn written
# right after the PTY launches; ``seeded`` is recorded on the session record so it
# is NEVER re-sent on a later attach/input/read.
#
# Lane → skill (both the trio-lane key ``plan`` and the on-disk dir name
# ``planning`` map to Crucible so either naming convention is tolerated):
#   research          → researchPrime
#   plan / planning   → Crucible
#   build             → Foreman
LANE_SKILL = {
    "research": "researchPrime",
    "plan": "Crucible",
    "planning": "Crucible",
    "build": "Foreman",
}

#: A single global override env var (when set, used verbatim for EVERY lane —
#: tests assert deterministically against it). Per-lane overrides take the form
#: ``ANCHOR_SEED_PROMPT_<LANE-UPPER>`` and win over the global one for that lane.
SEED_ENV_GLOBAL = "ANCHOR_TERMINAL_SEED"
SEED_ENV_LANE_PREFIX = "ANCHOR_SEED_PROMPT_"

#: The marker substring the greet line ends with (see :func:`_default_seed_text`:
#: ``✓ <Skill> loaded — what would you like to do?``). The v10 pending-paste flush
#: waits until this appears in the PTY output buffer before pasting the task
#: prompt — that is the "the skill loaded and greeted" signal. Matched
#: case-insensitively on the stable, skill-independent tail of the greet line.
GREET_MARKER = "what would you like to do?"

#: telemetry-resume W6 (diag-B2 S3 attach-race fix) — the bounded FALLBACK for the
#: greet-gated pending-paste flush. The greet-count gate above can leave a paste
#: pending FOREVER when the model paraphrases/omits the greet marker (or an
#: env-overridden seed lacks it). This is the escape hatch: once a paste has been
#: pending longer than this many seconds AND the PTY has produced real model
#: output beyond the echoed seed, the paste is delivered anyway — still
#: paste-NOT-submit (trailing newline stripped; nothing is auto-submitted). Env
#: ``ANCHOR_PASTE_FLUSH_FALLBACK_SECS`` overrides (tests set 0 to force it).
PASTE_FLUSH_FALLBACK_SECS_ENV = "ANCHOR_PASTE_FLUSH_FALLBACK_SECS"
PASTE_FLUSH_FALLBACK_SECS_DEFAULT = 45.0


def _paste_flush_fallback_secs():
    raw = (os.environ.get(PASTE_FLUSH_FALLBACK_SECS_ENV) or "").strip()
    if raw:
        try:
            v = float(raw)
            if v >= 0:
                return v
        except (TypeError, ValueError):
            pass
    return PASTE_FLUSH_FALLBACK_SECS_DEFAULT

#: Neutral framing for an extra ``seed_context`` payload folded onto a lane seed.
#: Replaces the old hard-coded "promoted from Grass Catchers" wording, which was
#: WRONG for every non-grass use of ``seed_context`` — engine-switch handoffs
#: (v13 Wave 7), stage advances, etc. Callers that genuinely ARE a grass promote
#: (or want any other framing) pass their own ``context_label`` to
#: :func:`seed_for_lane`.
DEFAULT_SEED_CONTEXT_LABEL = "Here is the context to work on"


def _default_seed_text(skill):
    """The one-time opening instruction: load the skill, confirm, greet once.

    A single instruction string that tells the model to load the lane's skill,
    confirm it is ready, greet EXACTLY once with ``✓ <Skill> loaded — what would
    you like to do?`` and then wait for the user — nothing more. Ends with a
    newline so it is delivered as one submitted turn.
    """
    return (
        "Load the {skill} skill now. Once it is loaded and ready, greet me "
        "EXACTLY once with this single line and nothing else: "
        "\"✓ {skill} loaded — what would you like to do?\" "
        "Engine-enforced governance: the engine automatically emits a status block "
        "(timestamp, wave, budget, state) on a 10-minute cadence from existing telemetry; "
        "do NOT fabricate or emit your own status blocks. "
        "Then stop and wait for my next message. Do not repeat this greeting."
        "\n"
    ).format(skill=skill)


def seed_for_lane(lane, seed_context=None, context_label=None):
    """Return the one-time seed text for ``lane`` (env-overridable), or ``None``.

    Resolution order (so tests can pin a deterministic value):
      1. ``ANCHOR_SEED_PROMPT_<LANE-UPPER>`` — per-lane override;
      2. ``ANCHOR_TERMINAL_SEED`` — single global override (all lanes);
      3. the built-in :func:`_default_seed_text` for the lane's mapped skill.

    A lane with no mapped skill and no override returns ``None`` (no seed sent) —
    e.g. the ``grass`` future-ideas lane is a bare shell.

    ``seed_context`` (v4 Wave 6) is an optional extra payload appended to the
    chosen lane seed as the THING TO WORK ON — e.g. a Grass Catcher idea promoted
    into a Research/Plan session. It is folded onto whatever seed was resolved
    above (including an env override, so the promote path stays deterministic in
    tests) so the SINGLE opening turn loads the lane skill AND carries the idea.

    ``context_label`` (v13 Wave 7) is the framing prefix for that folded payload.
    When omitted it defaults to the neutral :data:`DEFAULT_SEED_CONTEXT_LABEL`
    ("Here is the context to work on") — NOT the old hard-coded "promoted from
    Grass Catchers" wording, which mislabeled every non-grass ``seed_context`` use
    (engine-switch handoffs, stage advances). A grass-promote caller (or any other)
    can pass an accurate label of its own.
    """
    base = None
    per_lane = os.environ.get(SEED_ENV_LANE_PREFIX + str(lane).upper())
    if per_lane is not None:
        base = per_lane
    else:
        glob = os.environ.get(SEED_ENV_GLOBAL)
        if glob is not None:
            base = glob
        else:
            skill = LANE_SKILL.get(lane)
            base = _default_seed_text(skill) if skill else None

    ctx = (seed_context or "").strip()
    if not ctx:
        return base
    # Fold the payload onto the lane seed as one combined opening turn. If the
    # lane had no skill seed (None), the context alone becomes the opening turn.
    # The framing is caller-supplied (``context_label``) and defaults to a neutral
    # label — never the old grass-specific wording for a non-grass payload.
    label = (context_label or DEFAULT_SEED_CONTEXT_LABEL).strip().rstrip(":")
    suffix = "{label}: {ctx}\n".format(label=label, ctx=ctx)
    if base is None:
        return suffix
    # Drop a trailing newline on the base so the two parts arrive as ONE turn.
    return base.rstrip("\n") + " " + suffix


def _valid_lanes():
    """Canonical set of lane names a terminal session may run.

    The terminal lane is threaded through ``lanes.check_engine_allowed``, so the
    authoritative names are the trio-lane keys (``research``/``plan``/``build``)
    plus the future-ideas ``grass`` lane and the v7 bare ``general`` lane. We also
    accept the ``rnd_registry`` on-disk lane DIR names (``planning``/
    ``deliverables``) so either naming convention is tolerated — but a typo like
    ``"planx"`` is rejected BEFORE any worktree/PTY is created.

    ``general`` (v7 Wave 4) is a deliberately BARE lane: it is NOT in
    :data:`LANE_SKILL` (so :func:`seed_for_lane` returns ``None`` → no seed → a
    bare PTY, like ``grass``), it is NOT a trio board column (excluded from
    ``anchor_gui._REGISTRY_LANE_TO_COLUMN``), and it is NOT a planning lane (so
    :func:`auto_advance_planning_to_build` never advances it).

    ``zombie`` (v13 Wave 1 / #12b) is the dashboard-scoped lane for the Zombie
    Hunter investigation terminal (``/api/rnd/zombie_terminal_start`` under the
    special ``__dashboard__`` project). Like ``general`` it is bare (NOT in
    :data:`LANE_SKILL` — its briefing is folded in via ``seed_context``), NOT a
    trio board column, and NOT a planning lane. Without it a dashboard zombie
    terminal launch was rejected as an unknown lane (HTTP 400).
    """
    lanes = set()
    try:
        lanes.update(_rnd.STATUS_LANES)
    except Exception:  # pragma: no cover - rnd_registry always defines it
        pass
    lanes.add("grass")
    lanes.add("general")
    lanes.add("zombie")
    if _lanes is not None:
        try:
            lanes.update(_lanes.LANES.keys())
        except Exception:  # pragma: no cover - defensive
            pass
    return lanes


class TerminalSessionError(RuntimeError):
    """A terminal-session operation failed for a clear, reportable reason."""


def _new_id() -> str:
    """Mint one fresh id used as BOTH the pty + registry session id."""
    return uuid.uuid4().hex


def _check_engine_allowed(lane, backend):
    """Enforce the lane/engine policy (Gemini = research-only) if available.

    Reuses ``lanes.check_engine_allowed`` when the lane name maps onto a known
    lane; otherwise it only validates the backend is a recognized engine. Raises
    :class:`TerminalSessionError` for a disallowed engine / unknown backend.
    """
    if backend not in VALID_BACKENDS:
        raise TerminalSessionError(
            "unknown backend %r (expected claude|gemini|grok)" % (backend,))
    if _lanes is not None:
        try:
            _lanes.check_engine_allowed(lane, backend)
        except getattr(_lanes, "EngineNotAllowedError", ()) as exc:
            raise TerminalSessionError(str(exc)) from exc


def _resolve_grass_origin_from_chain(parent_id, parent_rec):
    """Return the grass_origin a child should inherit from the chain it joins.

    v10 Wave 4 FIX 1 (D8): the stamp must reach the CHAIN ROOT, not just the
    direct parent. Prefer the direct parent's own stamp (cheapest, common case);
    otherwise walk the chain members ONCE (a single bounded ``chain_members``
    read — no parent-pointer recursion, so it is inherently cycle-safe) and adopt
    any non-empty ``grass_origin`` found among them. Returns ``""`` when no member
    carries one. Best-effort: any registry error degrades to ``""``.
    """
    direct = (parent_rec.get("grass_origin", "") or "") if parent_rec else ""
    if direct:
        return direct
    if not parent_id:
        return ""
    try:
        chain_id = _reg.chain_for(parent_id)
        if not chain_id:
            return ""
        for m in _reg.chain_members(chain_id):
            go = (m.get("grass_origin", "") or "") if isinstance(m, dict) else ""
            if go:
                return go
    except Exception:
        return ""
    return ""


#: Sentinel: ``backend`` not explicitly passed → default to the project's
#: last-used engine (v4 Wave 2).
_UNSET = object()


#: Test/deploy seam for the INTERACTIVE-terminal engine command — the PTY-path
#: mirror of ``ANCHOR_RUNNER_CMD`` (which only covers one-shot ``job_runner``
#: lanes). Before this existed, ``ANCHOR_PTY_BACKEND=stub`` was the SINGLE point
#: of failure protecting every terminal test from a real billable spawn
#: (2026-07-26 hardening; the suite once leaked 8,816 live sessions).
ENGINE_CMD_ENV = "ANCHOR_ENGINE_CMD"

#: Basenames that mean "a real, billable engine binary".
_LIVE_ENGINE_BASENAMES = frozenset({"claude", "gemini", "agy", "grok"})


def assert_not_live_engine_under_test(argv) -> None:
    """FAIL CLOSED: refuse to spawn a real engine while the test guard is on.

    The suite once leaked 8,816 billed sessions (tests/conftest.py). The guard
    is now defence-in-depth: even if every env seam is defeated, a real engine
    basename cannot be launched unless ``ANCHOR_TESTS_ALLOW_LIVE=1``. Inert in
    production — it only fires when pytest is actually loaded.
    """
    if "pytest" not in sys.modules:
        return
    if os.environ.get("ANCHOR_TESTS_ALLOW_LIVE", "").strip() == "1":
        return
    try:
        first = str((argv or [""])[0])
    except Exception:
        return
    base = os.path.basename(first).lower()
    for ext in (".exe", ".cmd", ".bat"):
        if base.endswith(ext):
            base = base[: -len(ext)]
    if base in _LIVE_ENGINE_BASENAMES:
        raise TerminalSessionError(
            "live-engine-spawn-refused: refusing to spawn %r under the test "
            "guard (it resolves to a real billable engine). Set "
            "ANCHOR_ENGINE_CMD to a stub (tests/conftest.py does this), or opt "
            "in deliberately with ANCHOR_TESTS_ALLOW_LIVE=1." % (first,)
        )


def _resolve_engine_cmd(engine: str) -> str:
    """Resolve the executable name/path for a given engine backend."""
    import shutil
    override = os.environ.get(ENGINE_CMD_ENV, "").strip()
    if override:
        return override
    if engine == _reg.BACKEND_GEMINI:
        if shutil.which("gemini"):
            return "gemini"
        if shutil.which("agy"):
            return "agy"
        agy_path = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "agy", "bin", "agy.exe")
        if os.path.exists(agy_path):
            return agy_path
        return "agy"
    if engine == _reg.BACKEND_GROK:
        which = shutil.which("grok")
        if which:
            return which
        grok_exe = Path.home() / ".grok" / "bin" / "grok.exe"
        if grok_exe.is_file():
            return str(grok_exe)
        return "grok"
    return engine


def _new_engine_session_id() -> str:
    """Mint a fresh engine-session UUID (dashed) — the value passed to
    ``claude --session-id`` so the sidecar filename is pinned AT LAUNCH (Honest
    Telemetry W4, W1-GROUND-TRUTH §1). Distinct from the hex Anchor session id."""
    return str(uuid.uuid4())


#: Env seam: the flag claude accepts to pin its session UUID at launch (so the
#: ``~/.claude/projects/<slug>/<uuid>.jsonl`` sidecar filename IS this uuid). Set
#: it EMPTY to disable UUID-at-launch injection entirely (falls back to an
#: honest ``uncorrelated`` usage state — never an mtime guess).
_SESSION_ID_FLAG_ENV = "ANCHOR_TERMINAL_SESSION_ID_FLAG"
_DEFAULT_SESSION_ID_FLAG = "--session-id"

#: Env seam: the flag Grok accepts for a session id at launch (``-s <uuid>``).
#: Set EMPTY to disable Grok session-id injection.
_GROK_SESSION_ID_FLAG_ENV = "ANCHOR_GROK_SESSION_ID_FLAG"
_DEFAULT_GROK_SESSION_ID_FLAG = "-s"


def _engine_launch_argv(cmd, backend, engine_uuid):
    """Build the PTY launch argv, injecting a session-id pin when the backend supports it.

    UUID-at-launch (W4): ``claude --session-id <uuid>`` pins the engine's sidecar
    filename deterministically at launch — the correlation the usage-capture
    pipeline reads by, never a fragile mtime/cwd-window guess. Grok gets
    ``-s <uuid>`` for the same interactive session pin. Gemini/agy has no
    equivalent pin (its segment stays honestly unmeasured per the RULED Option C).
    Flag names are test/deploy seams (``ANCHOR_TERMINAL_SESSION_ID_FLAG`` /
    ``ANCHOR_GROK_SESSION_ID_FLAG``); empty disables injection. Pure — returns
    the argv list.
    """
    argv = [cmd]
    if not engine_uuid:
        return argv
    if backend == _reg.BACKEND_CLAUDE:
        flag = os.environ.get(_SESSION_ID_FLAG_ENV)
        if flag is None:
            flag = _DEFAULT_SESSION_ID_FLAG
        flag = flag.strip()
        if not flag:
            return argv  # injection disabled by the seam
        return [cmd, flag, engine_uuid]
    if backend == _reg.BACKEND_GROK:
        flag = os.environ.get(_GROK_SESSION_ID_FLAG_ENV)
        if flag is None:
            flag = _DEFAULT_GROK_SESSION_ID_FLAG
        flag = flag.strip()
        if not flag:
            return argv
        return [cmd, flag, engine_uuid]
    return argv


def start_session(project_id, lane, backend=_UNSET, label="", seed_context=None,
                  parent_session_id=None, paste_prompt=None, grass_origin=None,
                  effort_id=None, effort_managed=False, actor=None,
                  extra_cli_args=None):
    """Start a live, worktree-isolated, registered terminal session.

    Resolves ``project_id`` in ``rnd_registry``, mints ONE session id, creates a
    git worktree for it, launches an interactive ``backend`` PTY in that worktree,
    registers the session as ``RUNNING``, and — for a lane with a mapped trio
    skill — writes **exactly one** opening stdin turn that loads the lane's skill
    and greets once (the v4 Wave-1 seed; recorded as ``seeded=True`` so it is
    never re-sent). The pty id IS the registry ``session_id``.

    v4 Wave 2: when ``backend`` is NOT explicitly passed it defaults to the
    project's **last-used engine** (:func:`last_engine_for_project`, ``claude``
    when unset); on a successful start the chosen engine is recorded as the
    project's last_engine so the next session inherits it.

    v4 Wave 6: ``seed_context`` (optional) is folded onto the lane seed (via
    :func:`seed_for_lane`) so the single opening turn loads the lane skill AND
    carries an extra payload — e.g. a Grass Catcher idea promoted into this
    Research/Plan session — as the thing to work on. It is recorded in
    ``seed_text`` and, like the base seed, is written exactly once.

    v6 Wave 2: ``parent_session_id`` (optional) links this session into an
    existing lineage. When given, the new session JOINS the parent's chain
    (``chain_id`` = the parent's chain_id, resolved via
    :func:`session_registry.chain_for`) and records ``parent_session_id``. When
    omitted, the new session starts its OWN chain (chain_id == its own id). The
    parent record is never mutated.

    v10 Wave 1: ``paste_prompt`` (optional) is the task prompt for a handoff that
    must be DELIVERED BUT NOT SUBMITTED. When provided, phase-1 (the lane
    load+greet seed, ending ``\\n``) is still written so the skill auto-loads and
    greets, but the ``paste_prompt`` is NOT written to the PTY at start — it is
    recorded on the session record as ``pending_paste`` (with
    ``paste_flushed=False``) and later written to the PTY input WITHOUT a trailing
    newline exactly once, after the greet is observed, by
    :func:`_flush_pending_paste` (wired into the first ``read_since``/``attach``).
    With no ``paste_prompt`` the behavior is exactly as v9 (the regression-guarded
    back-compat path) — ``seed_context`` continues to fold onto the seed and is
    auto-submitted as today.

    v10 Wave 4: ``grass_origin`` (optional) is the originating grass idea id for a
    grass→project lineage chain (D8). When passed it is stamped on the new
    session's registry record; when omitted it is INHERITED from the parent's
    record (so once a chain is grass-stamped — e.g. by ``export_grass_to_project``
    on the dev session — every downstream session in that chain carries the
    origin and can trace back to the idea). Empty for any non-grass chain (the
    default). It is just an idea id — SAFE to carry into the board / chain
    projections (never worktree_path/branch).

    v12 Wave 1: ``effort_id`` (optional) is the stable id of the EFFORT this
    session belongs to. When given the new record inherits it (a context-relief
    continuation joins the SAME effort); when omitted the record's
    ``effort_id`` defaults to its own session_id (a fresh effort). ``effort_managed``
    (default False) is the v12 discriminator — passed True ONLY by the v12
    entrypoints; every existing caller leaves it False, so there is NO behavior
    change for them (both default to today's behavior).

    Doctor V3 Wave 2: ``extra_cli_args`` (optional) is a list of extra engine
    CLI flags appended to the launch argv — e.g. the doctor session's read-only
    ``--permission-mode plan`` posture. Appended AFTER the session-uuid pin and
    BEFORE the gemini ``-i`` seed injection; every existing caller omits it
    (default ``None`` → argv unchanged).

    Returns the registry record (incl. ``session_id``). Raises
    :class:`TerminalSessionError` for an unknown project or a disallowed engine.
    On a worktree-creation failure it raises with the git reason (nothing is left
    registered / no PTY is leaked).
    """
    proj = _rnd.get_project(project_id)
    if proj is None:
        raise TerminalSessionError("unknown project: %s" % (project_id,))

    # v4 Wave 2: no explicit engine → inherit the project's last-used one.
    if backend is _UNSET:
        backend = last_engine_for_project(project_id)

    # Validate the lane BEFORE creating any worktree/PTY — a typo must not mint a
    # real session. (Reuses the canonical lane set; engine policy is checked next.)
    if lane not in _valid_lanes():
        raise TerminalSessionError(
            "unknown lane %r (expected one of: %s)"
            % (lane, ", ".join(sorted(_valid_lanes()))))

    _check_engine_allowed(lane, backend)

    sid = _new_id()

    # v6 Wave 2: resolve the chain this session joins. A parent links the new
    # session into the parent's chain; with no parent the session starts its own
    # singleton chain (chain_id defaults to its own sid in register_session). An
    # unknown parent id is ignored (the session simply starts its own chain).
    parent_id = parent_session_id or ""
    chain_id = None
    parent_rec = None
    if parent_id:
        parent_rec = _reg.get_session(parent_id)
        chain_id = _reg.chain_for(parent_id)
        if not chain_id:
            parent_id = ""  # unknown parent → start a fresh chain
            parent_rec = None

    # v10 Wave 4 (D8): grass→project lineage. The new session's ``grass_origin``
    # is the explicit value if passed, ELSE INHERITED from anywhere in the chain
    # it is joining (so once an exported/promoted grass chain is stamped, EVERY
    # downstream session in it traces back to the idea — even when the direct
    # parent's own record happens to carry an empty stamp but a chain ancestor
    # carries it). Empty for any non-grass chain. Cheap + cycle-safe: a single
    # bounded read of the chain members (no parent-pointer recursion).
    origin = (grass_origin or "")
    if not origin and parent_rec is not None:
        origin = _resolve_grass_origin_from_chain(parent_id, parent_rec)

    # 1) Isolated worktree first — if this fails we never start a PTY.
    wt = _wt.create_worktree(project_id, sid)
    if not wt.get("ok"):
        raise TerminalSessionError(
            "worktree creation failed (%s): %s"
            % (wt.get("reason", "unknown"), wt.get("detail", "")))
    worktree_path = wt["path"]
    branch = wt["branch"]

    cmd = _resolve_engine_cmd(backend)

    # Honest Telemetry W4: capture the engine session UUID AT LAUNCH. For claude
    # we pin it via ``--session-id <uuid>`` so the sidecar filename IS this uuid
    # (deterministic correlation, never an mtime guess); it is stored on the
    # registry record so finalize-on-every-end-path reads the right sidecar. A
    # backend/seam that can't pin leaves it "" → the session finalizes honestly
    # ``uncorrelated``.
    engine_uuid = _new_engine_session_id()
    launch_argv = _engine_launch_argv(cmd, backend, engine_uuid)
    stored_engine_uuid = engine_uuid if (len(launch_argv) > 1) else ""

    # Doctor V3 W2: caller-supplied extra engine flags (e.g. the doctor
    # session's read-only ``--permission-mode plan``). Appended AFTER the
    # uuid-pin check above so ``stored_engine_uuid`` stays honest.
    if extra_cli_args:
        launch_argv = launch_argv + [str(a) for a in extra_cli_args]

    # 1b) Resolve the lane seed ONCE before launch.
    seed_text = seed_for_lane(lane, seed_context=seed_context)
    seed_text_to_write = seed_text
    
    # 1c) For gemini/agy, inject the seed via --prompt-interactive (-i) so it
    # processes it safely instead of dropping stdin.
    if backend == _reg.BACKEND_GEMINI and seed_text:
        launch_argv.extend(["-i", seed_text.strip()])
        seed_text_to_write = None

    # 2) Launch a BARE interactive PTY in the worktree (no skill/prompt seeding).
    try:
        assert_not_live_engine_under_test(launch_argv)
        pty_sid = _pty.start(launch_argv, cwd=worktree_path)
    except Exception as exc:
        # Roll back the worktree so a failed launch leaves nothing behind.
        try:
            _wt.remove_worktree(sid, project_id=project_id)
        except Exception:
            pass
        raise TerminalSessionError(
            "failed to start PTY (%s): %s" % (backend, exc)) from exc

    # 3) Reuse the pty id AS the registry session_id (ONE id per session).
    #    pty_manager mints its own opaque id; rebind it to our chosen sid so the
    #    registry, worktree and PTY all key off a single id.
    child_pid = None
    child_proc_create_time = None
    child_crypt_token = ""
    with _pty._TABLE_LOCK:
        child = _pty._LIVE.pop(pty_sid, None)
        if child is not None:
            _pty._LIVE[sid] = child
            # zombie-hunter Phase 1: lift the spawn-captured process identity
            # off the PTY child so it persists into the registry record below.
            child_pid = getattr(child, "pid", None)
            child_proc_create_time = getattr(child, "proc_create_time", None)
            child_crypt_token = getattr(child, "crypt_token", "")

    # 4) Register the session. If THIS fails (after the PTY is started+rebound),
    #    roll back BOTH the PTY and the worktree so nothing is left as an orphan
    #    invisible to reconcile — the docstring's "nothing left registered / no
    #    PTY leaked" promise must hold for the registry-failure path too.
    try:
        # W12 (C3, D1): journal-first-then-legacy. The blessed dual-write emits
        # a ``session-started`` event (correlation_id = the chain/effort this
        # session joins; causation_id = the parent session that spawned it, or
        # None for a user-rooted start) BEFORE register_session writes the
        # legacy row — best-effort + honoring the ``journal`` off-switch, so with
        # the flag off (today's default) ONLY register_session runs, byte-
        # identical to pre-journal behavior.
        record = _journal.dual_write(
            project_id, _journal.EV_SESSION_STARTED,
            lambda: _reg.register_session(
                project_id=project_id,
                lane=lane,
                backend=backend,
                worktree_path=worktree_path,
                branch=branch,
                status=_reg.STATUS_RUNNING,
                label=label,
                session_id=sid,
                parent_session_id=parent_id,
                chain_id=chain_id,
                grass_origin=origin,
                # v12 Wave 1: inherit the effort id if given (a context-relief
                # continuation joins the SAME effort), else default to own sid;
                # ``effort_managed`` stored exactly as passed (v12 discriminator).
                effort_id=(effort_id or sid),
                effort_managed=bool(effort_managed),
                # zombie-hunter Phase 1: persist the spawn-captured identity.
                pid=child_pid,
                proc_create_time=child_proc_create_time,
                crypt_token=child_crypt_token,
                # Honest Telemetry W4: the engine session UUID captured at launch
                # ("" when the backend/seam could not pin it → uncorrelated).
                engine_session_uuid=stored_engine_uuid,
            ),
            correlation_id=(chain_id or sid),
            folder_path=proj.get("folder_path", ""),
            actor=actor,
            causation_id=(parent_id or None),
            payload={"session_id": sid, "lane": lane, "backend": backend},
        )
    except Exception as exc:
        try:
            _pty.kill(sid)
        except Exception:
            pass
        try:
            _wt.remove_worktree(sid, project_id=project_id)
        except Exception:
            pass
        raise TerminalSessionError(
            "failed to register session (%s); rolled back PTY + worktree"
            % (exc,)) from exc

    # Honest Telemetry W5 (RULED Option C): a session STARTED on the gemini/agy
    # backend carries an unmeasurable segment (gemini gets no --session-id pin), so
    # stamp the durable mixed-session marker at launch — a gemini-start session
    # that later switches to claude (and finalizes MEASURED on the claude segment)
    # is then still honestly flagged 'partial (gemini segment unmeasured)', never a
    # complete-looking Claude-only number. Best-effort; never breaks the launch.
    if backend == _reg.BACKEND_GEMINI:
        try:
            record = _reg.update_session(sid, usage_gemini_segment=True)
        except Exception:
            pass

    # 5) Seed the lane's skill EXACTLY ONCE. This is the only place the seed is
    #    ever written — it happens right after a successful launch+register and
    #    is recorded as ``seeded=True`` on the record, so no later attach/input/
    #    read can re-send it. A lane with no mapped skill (e.g. ``grass``) gets a
    #    bare shell (seed_text == None → nothing written). A write/persist failure
    #    is non-fatal: the session is already live and usable; we simply leave it
    #    un-seeded rather than tearing down a working terminal.
    if seed_text_to_write:
        try:
            _pty.write(sid, seed_text_to_write)
        except Exception:
            seed_text_to_write = None  # seed not delivered → don't claim it was
        if seed_text_to_write:
            try:
                record = _reg.update_session(
                    sid, seeded=True, seed_text=seed_text_to_write)
            except Exception:
                pass
    elif seed_text:
        # Seed was delivered via command line (-i) for gemini
        try:
            record = _reg.update_session(
                sid, seeded=True, seed_text=seed_text)
        except Exception:
            pass

    # v10 Wave 1: record the task prompt as a PENDING PASTE — held UNSENT in the
    # PTY input until the user presses Enter. It is NOT written here; it is
    # delivered exactly once, after the greet, by :func:`_flush_pending_paste`

    # W12 Status Emitter
    _start_status_emitter(project_id, sid, worktree_path)
    # (wired into the first read_since/attach). Recorded with paste_flushed=False
    # so the flush guard knows it is still pending. With no paste_prompt this is
    # skipped entirely (the v9 back-compat path is untouched).
    pending = (paste_prompt or "")
    if pending:
        try:
            record = _reg.update_session(
                sid, pending_paste=pending, paste_flushed=False)
            # W6: stamp when the paste began waiting so the greet-gate has a
            # bounded fallback flush (a separate call keeps the pending set above
            # a stable, byte-identical write the B2 repro pins).
            import time as _time
            record = _reg.update_session(
                sid, pending_paste_since=_time.time())
        except Exception:
            pass

    # v12 Wave 6 (the W5 forward note / R2-2 fix): for a v12 EFFORT, open the
    # FIRST stage entry at start — record the stage's baseline (the worktree's
    # current HEAD) and append an OPEN stage_history entry via set_current_stage —
    # so the first stage has a baseline + an active entry and per-stage doc
    # attribution / summaries work from stage one (otherwise the first stage's
    # finish would fall back to the legacy whole-tree diff). Legacy starts
    # (``effort_managed=False``) are UNCHANGED: no baseline, no stage entry.
    # Best-effort — a bookkeeping hiccup never tears down a working session.
    if effort_managed:
        try:
            init_stage = _initial_stage_for_lane(lane)
            if init_stage:
                store_lane = _store_lane_for_stage(init_stage)
                baseline = _eh.record_stage_baseline(worktree_path)
                record = _reg.set_current_stage(
                    sid, init_stage, store_lane, baseline)
        except Exception:
            pass

    # v4 Wave 2: remember the engine this session chose so the NEXT session for
    # this project defaults to it. Best-effort (never fails a live session).
    set_last_engine_for_project(project_id, backend)
    return record


# ── The doctor agentic session (doctor V3 Wave 2) ────────────────────────────

#: Reserved pseudo-project id for THE ``/doctor`` diagnostic session. Like
#: ``__dashboard__`` it is synthesized by ``rnd_registry.get_project`` (never a
#: registry row — so it can never surface on the dashboard project list) and
#: special-cased by ``worktrees.create_worktree`` (NO worktree — diagnostics run
#: against the live Anchor folder, held read-only by the engine's plan
#: permission mode). It is FILTERED from every session-listing surface (same
#: pattern as the ``__healthcheck__`` task filtering).
DOCTOR_PROJECT_ID = "__doctor__"

#: The doctor session runs the bare ``general`` lane: no trio skill seed (the
#: doctor briefing arrives via ``seed_context``, written exactly once by the
#: existing seed-once mechanism), Gemini-runnable on a Gemini-only host
#: (``lanes.GEMINI_RUNNABLE_LANES``), and never a planning lane (no advance).
DOCTOR_LANE = "general"
DOCTOR_LABEL = "doctor"

#: Read-only engine posture per backend (plan §W2: the engine CLI is launched
#: in READ-ONLY plan permission mode — diagnostics inspect the live folder but
#: can never mutate it). claude: ``--permission-mode plan`` (verified-real
#: interactive flag; same mode the read-only Gandalf/orientation jobs use).
#: gemini: ``--approval-mode plan`` (the gemini CLI's read-only approval
#: posture). Module-level so a test/deploy can inspect or tune it.
DOCTOR_READONLY_CLI_ARGS = {
    _reg.BACKEND_CLAUDE: ("--permission-mode", "plan"),
    _reg.BACKEND_GEMINI: ("--approval-mode", "plan"),
}


def live_doctor_session():
    """Return the LIVE doctor session's registry record, or ``None``.

    LIVE means the record is RUNNING **and** its PTY is actually attached in
    this process. A row that claims RUNNING with no live PTY is a stale
    leftover (e.g. from a prior server instance); it is honestly re-statused
    DONE here (best-effort) so a later start can never "attach" to a corpse.
    Never raises.
    """
    try:
        running = _reg.list_sessions(project_id=DOCTOR_PROJECT_ID,
                                     status=_reg.STATUS_RUNNING)
    except Exception:
        return None
    try:
        live = set(_pty.live_sessions())
    except Exception:
        live = set()
    for rec in running:
        sid = rec.get("session_id", "")
        if not sid:
            continue
        if sid in live:
            return rec
        try:  # stale RUNNING row, PTY gone → honest terminal status
            _reg.update_session(sid, status=_reg.STATUS_DONE)
        except Exception:
            pass
    return None


def start_doctor_session(seed_context=None, backend=None):
    """Start (or attach to) THE doctor agentic session (doctor V3 Wave 2).

    Returns ``(record, attached)``. Idempotent: while one doctor session is
    LIVE a second start ATTACHES to it — the existing record is returned with
    ``attached=True`` and a duplicate is never stacked. Otherwise a fresh
    session starts through the existing substrate (:func:`start_session`) under
    the reserved ``__doctor__`` pseudo-project: bare ``general`` lane (the
    briefing is the ``seed_context``, delivered once by the seed-once
    mechanism), cwd = the live Anchor folder (no worktree), and the engine CLI
    in READ-ONLY plan permission mode (:data:`DOCTOR_READONLY_CLI_ARGS`).
    Output/input ride the EXISTING term_ws / term_stream2 / term_input2 /
    term_kill transports keyed by the returned ``session_id`` — no new
    transport. The caller resolves ``backend`` honestly via
    ``lanes.select_engine_plan`` (default claude).
    """
    existing = live_doctor_session()
    if existing is not None:
        return existing, True
    backend = backend or _reg.BACKEND_CLAUDE
    rec = start_session(
        DOCTOR_PROJECT_ID, DOCTOR_LANE, backend=backend, label=DOCTOR_LABEL,
        seed_context=seed_context,
        extra_cli_args=list(DOCTOR_READONLY_CLI_ARGS.get(backend, ())))
    return rec, False


def _flush_pending_paste(session_id):
    """Write a session's PENDING task prompt to the PTY input, UNSENT, once (v10 W1).

    The v10 "paste-NOT-submit" handoff: a session started with ``paste_prompt``
    holds that prompt on its record as ``pending_paste`` (``paste_flushed=False``)
    without writing it. THIS function delivers it — exactly once, after the greet
    is observed — by writing it to the PTY **without a trailing newline** so it
    sits in the input line UNSENT until the user presses Enter.

    Trigger ("greet observed") — the SOUND test (fixes the premature-flush bug):
    the greet line ``✓ <Skill> loaded — what would you like to do?`` is quoted
    VERBATIM inside the seed text Anchor writes at start (see
    :func:`_default_seed_text`), and the PTY echoes stdin — so :data:`GREET_MARKER`
    is already in the buffer from the moment the seed is ECHOED, BEFORE the model
    loads the skill or actually greets. A plain substring/`in` test therefore
    flushes prematurely (Master-Plan R1). Instead we count marker OCCURRENCES and
    require MORE than the seed text itself contains:

      base    = number of marker occurrences in the recorded ``seed_text`` (the
                exact bytes written at start; the echo contributes exactly ``base``)
      greeted = the buffer's marker count is STRICTLY GREATER than ``base``
                (the MODEL's real greet adds at least one more occurrence)

    There is intentionally NO ``len(text) > len(seed_text)`` fallback — that fired
    on almost any output and was the second half of the premature-flush defect.
    If the seed was env-overridden (``ANCHOR_TERMINAL_SEED``) to a text with ZERO
    marker occurrences, then ``base == 0`` and any appearance of the marker (from a
    model greet) triggers — acceptable. If such an overridden seed ALSO omits the
    marker AND the model greet won't contain it, the paste simply STAYS pending
    (honest: we never fabricate a greet we didn't observe).

    Real-ConPTY caveat: stdin echo may carry interleaved ANSI control codes, so
    counting the stable, skill-independent marker SUBSTRING tolerates that far
    better than positional/line matching.

    IDEMPOTENT + cheap to call on every read/attach:
      - no record / no ``pending_paste`` / already ``paste_flushed`` → no-op;
      - the greet has NOT been observed yet → no-op (left pending for a later read);
      - on a successful CLAIM it sets ``paste_flushed=True`` and clears
        ``pending_paste`` (so a second call never re-emits).

    Concurrency (Defect 2 — TOCTOU): under ``ThreadingHTTPServer`` two concurrent
    ``read_since``/``attach`` calls could both pass the guard and both write a
    double paste. The check-and-claim is therefore done as a compare-and-set under
    the process-wide :data:`paths.WRITE_LOCK` (a reentrant ``RLock`` — the SAME
    lock ``session_registry.update_session`` takes, so re-acquiring it for the
    persist can't self-deadlock). The winning thread CLAIMS the paste (sets
    ``paste_flushed=True`` + clears ``pending_paste`` + persists) BEFORE releasing
    the lock and BEFORE writing the bytes to the PTY; a losing/late thread sees
    ``paste_flushed`` already True and no-ops. (Rare tradeoff: if the PTY write
    fails AFTER the claim, the paste is lost rather than re-emitted — once-only
    dominates; we log a best-effort warning.)

    Never raises — a missing/dead PTY or a persist failure simply leaves the paste
    pending (it can be retried on the next read) without disturbing the caller.
    Returns ``True`` iff the paste was claimed+written on THIS call, else ``False``.
    """
    try:
        rec = _reg.get_session(session_id)
    except Exception:
        return False
    if rec is None:
        return False
    if not (rec.get("pending_paste") or "") or rec.get("paste_flushed"):
        return False

    # Has the greet been observed? Read the live PTY output buffer (cursor 0).
    try:
        out = _pty.read_since(session_id, 0)
    except _pty.UnknownSession:
        return False  # no live PTY (e.g. after a restart) — leave it pending
    except Exception:
        return False
    text = (out.get("text") or "") if isinstance(out, dict) else ""

    # Distinguish the ECHOED seed from a REAL model greet by counting marker
    # occurrences beyond what the seed text itself contributes (see docstring).
    marker = GREET_MARKER.lower()
    seed_text = rec.get("seed_text") or ""
    base = seed_text.lower().count(marker)
    greeted = text.lower().count(marker) > base
    if not greeted:
        # diag-B2 S3 attach-race fix (telemetry-resume W6): a paraphrased/omitted
        # greet (or an env-overridden seed with no marker) would otherwise leave
        # this paste pending FOREVER. Bounded fallback: once the paste has been
        # pending longer than PASTE_FLUSH_FALLBACK_SECS *and* the PTY has produced
        # real model output beyond the echoed seed, deliver it anyway — still
        # paste-NOT-submit (the trailing newline is stripped below; nothing is
        # ever auto-submitted). If neither the greet nor real output has appeared,
        # stay pending (we never fabricate a greet we didn't observe).
        import time as _time
        since = rec.get("pending_paste_since")
        if since is None:
            since = rec.get("created_at")
        try:
            waited = _time.time() - float(since) if since is not None else 0.0
        except (TypeError, ValueError):
            waited = 0.0
        has_model_output = len(text.strip()) > len(seed_text.strip())
        if not (waited >= _paste_flush_fallback_secs() and has_model_output):
            return False  # still waiting on the greet (or its bounded fallback)

    # Compare-and-set the claim under WRITE_LOCK (reentrant; same lock
    # update_session takes). Re-load + re-check inside the lock so exactly ONE
    # concurrent thread wins; claim (persist paste_flushed=True + clear pending)
    # BEFORE releasing the lock and BEFORE the PTY write, so only the winner
    # proceeds to write.
    with _paths.WRITE_LOCK:
        try:
            rec = _reg.get_session(session_id)
        except Exception:
            return False
        if rec is None:
            return False
        pending = rec.get("pending_paste") or ""
        if not pending or rec.get("paste_flushed"):
            return False  # a concurrent thread already claimed it
        try:
            _reg.update_session(
                session_id, paste_flushed=True, pending_paste="")
        except Exception:
            return False  # couldn't claim → leave it for a later read

    # Strip a trailing newline so a prompt that itself ends in "\n"/"\r\n" (e.g. a
    # Wave-2 NEXT-PROMPT.md body) can NEVER auto-submit — the paste must land in
    # the input line UNSENT.
    pending = pending.rstrip("\r\n")

    # Deliver the prompt to the PTY input WITHOUT a trailing newline (UNSENT).
    # We have already claimed the paste, so a write failure here loses this paste
    # (accepted tradeoff: once-only dominates double-paste). Log best-effort.
    try:
        _pty.write(session_id, pending)
    except Exception as exc:
        try:
            import sys as _sys
            print("warning: pending-paste claimed but PTY write failed for "
                  "%s: %s" % (session_id, exc), file=_sys.stderr)
        except Exception:
            pass
        return False
    return True


def queue_paste(session_id, text):
    """Queue a PENDING task prompt onto an ALREADY-LIVE session (v10 W5).

    The v10 "paste-NOT-submit" handoff normally records ``pending_paste`` at
    :func:`start_session`. But when a *bare* develop session already exists (e.g.
    the user clicked "Plan"/Develop on a grass idea FIRST, minting a plan dev
    session with NO handoff), a later research→plan *advance* must still deliver
    the generated handoff prompt onto that existing session — WITHOUT re-starting
    it. This sets ``pending_paste=<text>`` + ``paste_flushed=False`` on the record
    (reusing the Wave-1 plumbing) so the SAME :func:`_flush_pending_paste` path
    delivers it UNSENT on the next read/attach. The session has already greeted, so
    the greet-marker-count guard is already satisfied → it flushes immediately,
    unsent.

    SAFETY (no double-paste): the CALLER must only invoke this on a session that
    has NEITHER a pending paste NOR an already-flushed one (``not pending_paste and
    not paste_flushed``) — a session that already carries a handoff (pending,
    pre-flush) or already received one (flushed) must NOT get a second. This helper
    re-checks that guard under the registry semantics and refuses otherwise.

    Returns ``True`` iff the paste was queued on THIS call, else ``False`` (unknown
    session, empty text, or the guard refused). Never raises.
    """
    text = (text or "")
    if not text.strip():
        return False
    try:
        rec = _reg.get_session(session_id)
    except Exception:
        return False
    if rec is None:
        return False
    # Guard against double-paste / re-advance: refuse if a handoff is already
    # pending (pre-flush) or already delivered (flushed).
    if (rec.get("pending_paste") or "") or rec.get("paste_flushed"):
        return False
    try:
        import time as _time
        _reg.update_session(
            session_id, pending_paste=text, paste_flushed=False,
            pending_paste_since=_time.time())  # W6: greet-gate fallback stamp
    except Exception:
        return False
    return True


# ── v13 Wave 7: model-switch handoff ────────────────────────────────────────

#: The git-ignored, ephemeral handoff doc written into the worktree on an engine
#: switch so the new engine opens with the prior engine's context.
SWITCH_HANDOFF_FILENAME = "SWITCH-HANDOFF.md"
#: Hard ceiling (seconds) on the best-effort source summary. A wedged source
#: engine MUST NOT block the swap, so the summary runs in a daemon thread joined
#: for at most this long; on timeout the summary is skipped and the swap proceeds.
SWITCH_SUMMARY_TIMEOUT = 5.0
#: Keep the carried-over digest a sane size for one opening turn.
SWITCH_SUMMARY_MAX_CHARS = 6000
#: Accurate framing for the switch handoff payload (NOT the old grass wording).
SWITCH_CONTEXT_LABEL = (
    "Here is a summary of the session so far, carried over from the previous "
    "engine — continue from here"
)


def _generate_switch_summary(session_id, record):
    """Best-effort context digest of the live session for an engine switch.

    Reads the source session's live PTY transcript (``read_since(sid, 0)``),
    cleans it, and returns a bounded digest (or ``""``). NEVER raises. This is the
    potentially-slow step :func:`switch_engine` runs UNDER A TIMEOUT (via
    :func:`_switch_handoff_summary`) so a wedged source engine can never block the
    swap. Kept as a module-level seam so tests can stub it (healthy / hanging).
    """
    try:
        worktree_path = (record or {}).get("worktree_path") or ""
        lane = (record or {}).get("lane") or ""
        if worktree_path and lane:
            import os
            restart_doc = os.path.join(worktree_path, lane, "RESTART.md")
            if os.path.exists(restart_doc):
                return f"Switching engines. Please read the {restart_doc} file to get oriented with the current state. Do NOT read the full raw transcripts unless specifically needed."
        try:
            out = _pty.read_since(session_id, 0)
        except _pty.UnknownSession:
            return ""  # no live PTY → nothing to carry over
        raw = (out.get("text") or "") if isinstance(out, dict) else ""
        seed_text = (record or {}).get("seed_text") or "" if isinstance(record, dict) else ""
        body = _clean_transcript_text(raw, seed_text=seed_text)
        if not body:
            return ""
        if len(body) > SWITCH_SUMMARY_MAX_CHARS:
            body = body[-SWITCH_SUMMARY_MAX_CHARS:]
        return body.strip()
    except Exception:
        return ""


def _switch_handoff_summary(session_id, record, timeout=SWITCH_SUMMARY_TIMEOUT):
    """Run :func:`_generate_switch_summary` bounded by ``timeout`` seconds.

    Generated in a DAEMON thread and joined for at most ``timeout`` — so a source
    engine wedged in summary generation NEVER blocks the engine switch: on timeout
    (or any error) this returns ``""`` and the caller proceeds with the swap.
    """
    result = {"text": ""}

    def _worker():
        try:
            result["text"] = _generate_switch_summary(session_id, record) or ""
        except Exception:
            result["text"] = ""

    t = threading.Thread(target=_worker, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive():
        # Wedged source engine → skip the summary, proceed with the swap.
        return ""
    return (result["text"] or "").strip()


def _gitignore_in_worktree(worktree_path, name):
    """Best-effort: ensure ``name`` is git-ignored within the worktree WITHOUT
    touching any tracked file.

    Appends ``name`` to the worktree's git ``info/exclude`` (resolved to the
    COMMON git dir for a linked worktree, which is where git reads exclude
    patterns from). Idempotent; never raises.
    """
    try:
        wt = Path(worktree_path)
        dotgit = wt / ".git"
        gitdir = None
        if dotgit.is_file():
            # Linked worktree: ``.git`` is a file ``gitdir: <path>``.
            txt = dotgit.read_text(encoding="utf-8", errors="replace").strip()
            if txt.lower().startswith("gitdir:"):
                ref = txt.split(":", 1)[1].strip()
                p = Path(ref)
                gitdir = p if p.is_absolute() else (wt / ref).resolve()
        elif dotgit.is_dir():
            gitdir = dotgit
        if gitdir is None or not gitdir.exists():
            return
        # For a linked worktree, exclude patterns live in the COMMON git dir.
        commondir_file = gitdir / "commondir"
        if commondir_file.is_file():
            cd = commondir_file.read_text(encoding="utf-8").strip()
            cp = Path(cd)
            gitdir = cp if cp.is_absolute() else (gitdir / cd).resolve()
        info = gitdir / "info"
        info.mkdir(parents=True, exist_ok=True)
        excl = info / "exclude"
        existing = excl.read_text(encoding="utf-8") if excl.exists() else ""
        if name not in existing.split():
            sep = "" if (not existing or existing.endswith("\n")) else "\n"
            excl.write_text(existing + sep + name + "\n", encoding="utf-8")
    except Exception:
        return


def _write_switch_handoff(worktree_path, text):
    """Write the git-ignored :data:`SWITCH_HANDOFF_FILENAME` into the worktree.

    Returns the absolute path written (str) or ``None`` (no worktree / failure).
    Never raises. The file is marked git-ignored within the worktree so it is
    never committed/persisted as a tracked artifact (it is ephemeral context).
    """
    try:
        wt = Path(worktree_path)
        if not wt.is_dir():
            return None
        dest = wt / SWITCH_HANDOFF_FILENAME
        header = (
            "# Engine-switch handoff\n\n"
            "_Ephemeral, git-ignored context carried into the new engine on a "
            "mid-session model switch._\n\n"
        )
        dest.write_text(header + (text or "").strip() + "\n", encoding="utf-8")
        _gitignore_in_worktree(wt, SWITCH_HANDOFF_FILENAME)
        return str(dest)
    except Exception:
        return None


def switch_engine(session_id, engine, seed_context=None):
    """Toggle a live session to the other engine, keeping its identity.

    Reaps the current session's PTY child (keeping the SAME ``session_id``,
    worktree, branch, lane, and label), launches a NEW PTY on ``engine`` in the
    SAME worktree, re-applies the lane's skill seed ONCE on the new engine (incorporating
    ``seed_context`` if provided), and updates the registry record's ``backend``
    (+ ``seeded``/``seed_text``). The project's last_engine is updated to ``engine``
    on success.

    Identity is preserved: the new PTY (which the manager mints under its own
    opaque id) is rebound under the EXISTING ``session_id`` (the same trick
    :func:`start_session` uses), so the registry, worktree and PTY keep keying
    off one id — no orphan PTY and no orphan worktree.

    v13 Wave 7 — MODEL-SWITCH HANDOFF: BEFORE reaping the source PTY, a
    best-effort, ``SWITCH_SUMMARY_TIMEOUT``-bounded context summary of the live
    session is generated (an explicit ``seed_context`` still wins). A wedged
    source engine cannot block the swap — on timeout the summary is skipped and
    the switch proceeds. The summary is written to a git-ignored
    :data:`SWITCH_HANDOFF_FILENAME` in the worktree and folded into the NEW
    engine's opening seed (labelled :data:`SWITCH_CONTEXT_LABEL`, NOT the old
    grass wording) so the new engine opens with the prior engine's context.

    On a relaunch FAILURE the record is rolled back to its prior, consistent
    state (original backend/seed restored, no half-killed live PTY left behind,
    the worktree untouched) and :class:`TerminalSessionError` is raised.

    Raises :class:`TerminalSessionError` for an unknown session / unknown
    backend / a disallowed lane+engine combination (engine policy is enforced
    BEFORE the old PTY is reaped, so a refused switch never disturbs the session).
    """
    if engine not in VALID_BACKENDS:
        raise TerminalSessionError(
            "unknown backend %r (expected claude|gemini|grok)" % (engine,))

    record = _reg.get_session(session_id)
    if record is None:
        raise TerminalSessionError("unknown session: %s" % (session_id,))

    lane = record.get("lane", "")
    worktree_path = record.get("worktree_path", "")
    project_id = record.get("project_id") or None
    prior_backend = record.get("backend", DEFAULT_ENGINE)
    prior_seeded = bool(record.get("seeded", False))
    prior_seed_text = record.get("seed_text", "") or ""

    if not worktree_path:
        raise TerminalSessionError(
            "session %s has no worktree to relaunch in" % (session_id,))

    # Enforce the lane/engine policy BEFORE touching the live PTY — a refused
    # switch (e.g. gemini on a plan/build lane) leaves the session exactly as-is.
    _check_engine_allowed(lane, engine)

    # v13 W7: BEFORE reaping the source PTY, capture a best-effort, time-bounded
    # handoff summary off the LIVE session (the PTY is still attached here). An
    # explicit caller ``seed_context`` wins; otherwise generate it from the live
    # transcript. A wedged source engine cannot block the swap — the generator is
    # joined for at most SWITCH_SUMMARY_TIMEOUT and skipped on timeout.
    handoff_text = (seed_context or "").strip()
    if not handoff_text:
        handoff_text = _switch_handoff_summary(
            session_id, record, timeout=SWITCH_SUMMARY_TIMEOUT)

    # Honest Telemetry W4: BEFORE reaping segment A's PTY, snapshot its usage into
    # the durable ledger (a non-finalizing ingest — the eager finalize on the
    # session's real end path is the sole cost-record writer). Segment A's engine
    # UUID is the record's current one. Best-effort.
    if _usage is not None:
        try:
            _usage.snapshot_session_usage(session_id, record=record)
        except Exception:
            pass

    # 1) Reap the current PTY child (tolerate an already-dead/unknown one).
    try:
        _pty.kill(session_id)
    except _pty.UnknownSession:
        pass

    cmd = _resolve_engine_cmd(engine)

    # Honest Telemetry W4: mint segment B's engine UUID and pin it at relaunch, so
    # the switched-to engine's sidecar is a distinct, correlatable segment. The
    # session accumulates BOTH uuids; finalize sums A + B, counted once.
    engine_uuid_b = _new_engine_session_id()
    relaunch_argv = _engine_launch_argv(cmd, engine, engine_uuid_b)
    stored_engine_uuid_b = engine_uuid_b if (len(relaunch_argv) > 1) else ""

    # 1b) Resolve the lane seed ONCE before launch, folding in the W7 handoff context.
    seed_text = seed_for_lane(
        lane, seed_context=(handoff_text or None),
        context_label=SWITCH_CONTEXT_LABEL)
    seed_text_to_write = seed_text
    
    # 1c) For gemini/agy, inject the seed via --prompt-interactive (-i) so it
    # processes it safely instead of dropping stdin.
    if engine == _reg.BACKEND_GEMINI and seed_text:
        relaunch_argv.extend(["-i", seed_text.strip()])
        seed_text_to_write = None

    # 2) Launch a NEW PTY on the other engine in the SAME worktree.
    try:
        assert_not_live_engine_under_test(relaunch_argv)
        pty_sid = _pty.start(relaunch_argv, cwd=worktree_path)
    except Exception as exc:
        # Relaunch failed: leave the record CONSISTENT. The old PTY is already
        # reaped, so mark the session IDLE (no live process) but keep its prior
        # backend/seed bookkeeping intact — no orphan PTY, worktree untouched.
        try:
            _reg.update_session(
                session_id, status=_reg.STATUS_IDLE, backend=prior_backend,
                seeded=prior_seeded, seed_text=prior_seed_text)
        except Exception:
            pass
        raise TerminalSessionError(
            "failed to relaunch on %s (%s); session left idle, worktree intact"
            % (engine, exc)) from exc

    # 3) Rebind the new PTY under the EXISTING session_id (one id per session).
    with _pty._TABLE_LOCK:
        child = _pty._LIVE.pop(pty_sid, None)
        if child is not None:
            _pty._LIVE[session_id] = child

    # 4) Update the registry record: new backend, RUNNING, seed reset (a fresh
    #    engine needs the skill re-loaded once).
    record = _reg.update_session(
        session_id, backend=engine, status=_reg.STATUS_RUNNING,
        seeded=False, seed_text="")

    # Honest Telemetry W4: append segment B's engine UUID to the session's history
    # (the current segment), so finalize on the eventual end path sums A + B.
    if stored_engine_uuid_b:
        try:
            record = _reg.add_engine_session_uuid(
                session_id, stored_engine_uuid_b)
        except Exception:
            pass
    else:
        # Honest Telemetry W5 (RULED Option C): segment B is NOT UUID-captured
        # (the gemini/agy engine gets no --session-id flag), so its usage is
        # unmeasurable. Stamp the durable mixed-session marker so the rollup
        # renders 'partial (gemini segment unmeasured)' even if the session later
        # switches back to claude and ends on the claude backend — never a
        # complete-looking Claude-only number. Best-effort; never blocks the swap.
        try:
            record = _reg.update_session(session_id, usage_gemini_segment=True)
        except Exception:
            pass

    # 4b) v13 W7: write the git-ignored SWITCH-HANDOFF.md and fold it into the new
    #     engine's opening seed so it carries the prior engine's context. Skipped
    #     cleanly when there was no summary (wedged/timed-out source engine).
    if handoff_text:
        _write_switch_handoff(worktree_path, handoff_text)

    # 5) Re-apply the lane seed ONCE on the new engine (same discipline as start),
    #    folding in the W7 handoff context under an accurate label.
    if seed_text_to_write:
        try:
            _pty.write(session_id, seed_text_to_write)
        except Exception:
            seed_text_to_write = None
        if seed_text_to_write:
            try:
                record = _reg.update_session(
                    session_id, seeded=True, seed_text=seed_text_to_write)
            except Exception:
                pass
    elif seed_text:
        # Seed was delivered via command line (-i) for gemini
        try:
            record = _reg.update_session(
                session_id, seeded=True, seed_text=seed_text)
        except Exception:
            pass

    # 6) Remember the now-current engine for the project.
    if project_id is not None:
        set_last_engine_for_project(project_id, engine)
    return record


def resume_parked_session(session_id):
    """Warm-REATTACH a PARKED-idle session by relaunching a PTY in its worktree (W6).

    The telemetry-resume Layer-2 escalation for a **parked-idle** tile (worktree
    RETAINED, PTY dead after a graceful ``close_session``): relaunch a fresh PTY on
    the session's own engine in the SAME retained worktree, rebound under the SAME
    ``session_id`` (the ``start_session``/``switch_engine`` rebind trick), flip the
    record back to RUNNING, and re-seed the lane skill ONCE. Its worktree, chain,
    summary, and finalized cost are all untouched — this is a genuine warm
    reattach, not a new sibling session.

    An **evicted-parked** tile (``worktree_path == ""`` — the worktree was
    reclaimed by the bounded-budget eviction) CANNOT be reattached: this returns
    ``{"ok": False, "reason": "evicted"}`` so the caller escalates via the W3/W4
    continue-seed path instead (a NEW seeded session on the SAME chain, with the
    honest 'resumed from persisted docs (worktree evicted)' line) — the UI NEVER
    claims a reattach it cannot perform (NORTH-STAR-AMENDMENT eviction sub-contract).

    Returns ``{"ok": True, "session": <record>, "mode": "reattach"}`` on success,
    else an honest ``{"ok": False, "reason": ...}``. Never raises.
    """
    try:
        record = _reg.get_session(session_id)
    except Exception:
        return {"ok": False, "reason": "lookup-failed"}
    if record is None:
        return {"ok": False, "reason": "unknown-session"}
    # An evicted worktree cannot host a reattach — signal the caller to continue.
    worktree_path = (record.get("worktree_path") or "").strip()
    if record.get("evicted") or not worktree_path:
        return {"ok": False, "reason": "evicted"}
    try:
        if not Path(worktree_path).is_dir():
            # The worktree is gone though the record wasn't marked evicted — treat
            # it as evicted (honest: no tree to reattach to).
            return {"ok": False, "reason": "evicted"}
    except (OSError, ValueError):
        return {"ok": False, "reason": "evicted"}
    # A still-live session needs no reattach — it is already running.
    if record.get("status") == _reg.STATUS_RUNNING and session_id in _pty._LIVE:
        return {"ok": True, "session": record, "mode": "already-live"}

    lane = record.get("lane", "")
    engine = record.get("backend", DEFAULT_ENGINE)
    cmd = _resolve_engine_cmd(engine)
    # Mint a fresh engine UUID for the resumed segment so its sidecar is a
    # distinct, correlatable segment (finalize sums over all segments, once).
    engine_uuid = _new_engine_session_id()
    relaunch_argv = _engine_launch_argv(cmd, engine, engine_uuid)
    stored_engine_uuid = engine_uuid if (len(relaunch_argv) > 1) else ""

    # Reap any stale PTY child (tolerate already-dead), then relaunch in-tree.
    try:
        _pty.kill(session_id)
    except _pty.UnknownSession:
        pass
    except Exception:
        pass
    try:
        assert_not_live_engine_under_test(relaunch_argv)
        pty_sid = _pty.start(relaunch_argv, cwd=worktree_path)
    except Exception as exc:
        return {"ok": False, "reason": "relaunch-failed", "detail": str(exc)}
    # Rebind the new PTY under the EXISTING session_id (one id per session).
    with _pty._TABLE_LOCK:
        child = _pty._LIVE.pop(pty_sid, None)
        if child is not None:
            _pty._LIVE[session_id] = child

    try:
        record = _reg.update_session(
            session_id, status=_reg.STATUS_RUNNING, seeded=False, seed_text="")
    except Exception:
        pass
    if stored_engine_uuid:
        try:
            record = _reg.add_engine_session_uuid(session_id, stored_engine_uuid)
        except Exception:
            pass
    # Re-seed the lane skill ONCE (loads the skill + one greet). No ACTION context
    # is auto-submitted — orientation (a read-only plan-mode job) narrates, and any
    # ACTION prompt stays v10 paste-NOT-submit.
    seed_text = seed_for_lane(lane)
    if seed_text:
        try:
            _pty.write(session_id, seed_text)
        except Exception:
            seed_text = None
        if seed_text:
            try:
                record = _reg.update_session(
                    session_id, seeded=True, seed_text=seed_text)
            except Exception:
                pass
    return {"ok": True, "session": record, "mode": "reattach"}


def suspend_session(session_id) -> str:
    """Gracefully suspend a live session: snapshot PTY transcript, persist, and summarize.

    Returns the generated summary text (or "" on failure). Never raises.
    """
    try:
        record = _reg.get_session(session_id)
        if record is None:
            return ""

        project_id = record.get("project_id")
        lane = record.get("lane")
        if not project_id or not lane:
            return ""

        proj = _rnd.get_project(project_id)
        if proj is None:
            return ""
        folder = proj.get("folder_path", "")
        if not folder:
            return ""

        # 1) Snapshot the current PTY transcript into the worktree.
        # This reads the live PTY buffer before it is reaped.
        _snapshot_transcript_doc(record, session_id)

        # 2) Persist the transcript doc to the main folder and record it as an effort.
        capture_session_docs(session_id, project_id=project_id, record=record)

        # Honest Telemetry W4: eager finalize on the DRAIN end path (idempotent
        # CAS; best-effort — never breaks the graceful suspend).
        _finalize_usage_safe(session_id, project_id=project_id, record=record)

        # 3) Load the session with aggregated member files.
        import summarizer as _sm
        store_lane = _eh._resolve_subdir(lane)
        session = _sm._find_session(folder, project_id, store_lane, session_id)
        if not session:
            return ""

        # 4) Run the summarizer (force=True to regenerate).
        summary = _sm.summarize_session(folder, project_id, store_lane, session, force=True)
        if not summary:
            return ""

        # 5) Extract the summary text.
        claims = summary.get("claims", [])
        if claims:
            return "Here is a summary of what was done so far:\n" + "\n".join("- " + c for c in claims)
        return summary.get("markdown", "") or ""
    except Exception:
        return ""


def attach(session_id):
    """Reattach to a session: replay the full live screen buffer + status.

    Returns ``{"ok": True, "session_id", "buffer", "cursor", "status",
    "record"}`` where ``buffer`` is the full retained PTY output (``read_since``
    from cursor 0) so a reconnecting client sees prior output, ``cursor`` is the
    next read cursor, and ``status`` is the PTY liveness (``running``/``dead``).
    Detach is implicit (the client simply stops reading) — NOTHING is killed.

    For an unknown session returns ``{"ok": False, "reason": "unknown-session"}``
    (never raises).
    """
    # v10 Wave 1: if a task prompt is pending for this session and the greet has
    # been observed, paste it (unsent) before replaying the buffer so the
    # reattaching client sees the prompt sitting in the input line. Idempotent +
    # cheap; a no-op when nothing is pending or the greet hasn't appeared yet.
    _flush_pending_paste(session_id)
    record = _reg.get_session(session_id)
    try:
        out = _pty.read_since(session_id, 0)
    except _pty.UnknownSession:
        # No live PTY (e.g. after a restart) — replay nothing but report the
        # registry record so the UI can still show the (idle) session.
        return {
            "ok": True,
            "session_id": session_id,
            "buffer": "",
            "cursor": 0,
            "dropped": 0,
            "truncated": False,
            "status": "dead",
            "record": record,
        }
    dropped = int(out.get("dropped", 0) or 0)
    return {
        "ok": True,
        "session_id": session_id,
        "buffer": out.get("text", ""),
        "cursor": out.get("next", 0),
        # Honest replay: how many older chars were discarded from the bounded
        # buffer, and a convenience bool a reattaching client can branch on.
        "dropped": dropped,
        "truncated": dropped > 0,
        "status": out.get("status"),
        "record": record,
    }


def input(session_id, data):
    """Write ``data`` (str/bytes) onto the session's PTY stdin.

    Returns ``{"ok": True}`` on success, or
    ``{"ok": False, "reason": "unknown-session"}`` for an unknown id (no raise).
    """
    try:
        _pty.write(session_id, data)
    except _pty.UnknownSession:
        return {"ok": False, "reason": "unknown-session"}
    return {"ok": True}


def resize(session_id, cols, rows):
    """Resize the session's PTY. Returns a status dict (no raise on unknown)."""
    try:
        _pty.resize(session_id, cols, rows)
    except _pty.UnknownSession:
        return {"ok": False, "reason": "unknown-session"}
    except (TypeError, ValueError) as exc:
        return {"ok": False, "reason": "bad-dimensions", "detail": str(exc)}
    return {"ok": True}


def read_since(session_id, cursor=0):
    """Thin wrapper over ``pty_manager.read_since`` (cursor-stable output read).

    Returns the manager's ``{"text", "next", "status"}`` on success, or
    ``{"ok": False, "reason": "unknown-session"}`` for an unknown id.
    """
    # v10 Wave 1: the first read that observes the greet flushes a pending task
    # prompt to the PTY input (unsent). Idempotent + cheap; a no-op when nothing
    # is pending. Done BEFORE the read so the freshly-pasted bytes (which the
    # stub echoes) surface in THIS read's output.
    _flush_pending_paste(session_id)
    try:
        return _pty.read_since(session_id, cursor)
    except _pty.UnknownSession:
        return {"ok": False, "reason": "unknown-session"}


# v12 Wave 6: the trio stage order. ``advance_stage`` resolves the NEXT stage and
# enforces idempotency (no-op if the current stage is already >= the target).
_STAGE_ORDER = ("research", "plan", "build")


def _stage_rank(stage):
    """Ordinal of a trio stage (research<plan<build); -1 for an unknown stage."""
    try:
        return _STAGE_ORDER.index(stage)
    except ValueError:
        return -1


def _next_stage(stage):
    """The trio stage AFTER ``stage`` (research→plan→build), or None at the end."""
    i = _stage_rank(stage)
    if i < 0 or i + 1 >= len(_STAGE_ORDER):
        return None
    return _STAGE_ORDER[i + 1]


def _initial_stage_for_lane(lane):
    """The starting trio ``current_stage`` for a lane.

    research → ``research``; plan/planning → ``plan``; build → ``build``; a
    grass-dev (``grass``) effort uses its lane's stage too (grass research/plan
    dev — defaults to ``research`` when the lane carries no trio stage). A bare
    ``general`` lane has no trio stage → ``""`` (no stage entry opened).
    """
    if lane == "research":
        return "research"
    if lane in _PLANNING_LANES:
        return "plan"
    if lane == "build":
        return "build"
    if lane == "grass":
        # A grass-dev effort runs a contained research/plan dev session; the
        # store_lane is "grass" but the stage maps onto the trio (research dev by
        # default). Wave 6 only needs an OPEN stage entry so per-stage attribution
        # works from stage one; the grass dev start passes its real lane.
        return "research"
    return ""


def _store_lane_for_stage(stage):
    """The on-disk store lane for a trio stage (plan stores under ``planning``)."""
    if stage == "plan":
        return "planning"
    return stage


def _active_stage_entry(record):
    """Return the OPEN (``ended_at is None``) ``stage_history`` entry, or None.

    A v12 effort carries an append-only ``stage_history``; the active stage is
    the (single) entry still open. Pure / read-only. Returns ``None`` for a
    legacy record (empty history) or when no entry is open.
    """
    if not isinstance(record, dict):
        return None
    found = None
    for ent in record.get("stage_history") or []:
        if isinstance(ent, dict) and ent.get("ended_at") is None:
            found = ent
    return found


def _persist_current_stage(session_id, project_id=None, record=None):
    """Persist the session's CURRENT-stage produced docs + schedule its summary.

    THE shared persist+summarize keystone path (v12 Wave 5) that both
    :func:`finish_stage` and :func:`kill` call, so a stage boundary and a kill
    persist+summarize identically. It runs against the LIVE worktree and does
    NOT reap / does NOT mark the record terminal — those are the caller's job.

    Behavior is split on whether this is a v12 EFFORT with a recorded active
    stage (an open ``stage_history`` entry carrying a ``store_lane``):

      - **v12 effort** — persist ONLY the active stage's produced docs via the
        Wave-3 :func:`effort_history.persist_session_stage_docs` (baseline-diffed,
        prior-stage-subtracted), bump the stage entry's ``doc_count``, and
        schedule the Wave-4 stage-keyed background summary
        (``summarize_session(stage=...)``).
      - **legacy / no active stage** — fall back to the EXACT pre-v12
        :func:`capture_session_docs` (whole-worktree ``persist_session_docs``),
        so :func:`kill`'s observable behavior on every existing (non-effort)
        session is byte-identical to before the refactor.

    Best-effort — NEVER raises. Returns the persist result dict in the SAME
    shape kill already returns/feeds to the Boneyard
    (``{"ok", "persisted":[rel,...], ...}``).
    """
    try:
        rec = record if record is not None else _reg.get_session(session_id)
        if rec is None:
            return {"ok": False, "reason": "unknown-session", "persisted": []}
        if project_id is None:
            project_id = rec.get("project_id") or None

        entry = _active_stage_entry(rec)
        # Stage-scoped path ONLY for a v12 effort with a recorded active stage.
        # Everything else (every legacy/non-effort session — i.e. every existing
        # kill test) keeps the exact legacy whole-tree capture, so kill is
        # unchanged.
        if not entry or not entry.get("store_lane"):
            return capture_session_docs(session_id, project_id=project_id,
                                        record=rec)

        worktree_path = rec.get("worktree_path", "")
        if not worktree_path:
            return {"ok": False, "reason": "no-worktree", "persisted": []}
        proj = _rnd.get_project(project_id) if project_id else None
        if proj is None:
            return {"ok": False, "reason": "unknown-project", "persisted": []}
        folder = proj.get("folder_path", "")
        if not folder:
            return {"ok": False, "reason": "no-folder", "persisted": []}

        stage = entry.get("stage") or (rec.get("current_stage") or "")
        store_lane = entry.get("store_lane") or stage
        baseline_ref = entry.get("baseline_ref") or ""

        # v12 Wave 6 (conversation-only case): if this stage wrote NO file but the
        # work lives entirely in the live PTY conversation, snapshot the transcript
        # into the worktree (the v11.1 transcript-snapshot path) so the stage-scoped
        # git diff below captures it as a produced doc, named + tagged (sid, stage).
        # No live PTY / no meaningful transcript (e.g. seed-only) → no file written
        # (honest), so a stage that DID write files is unaffected. Best-effort.
        try:
            _snapshot_transcript_doc(rec, session_id)
        except Exception:
            pass

        out = _eh.persist_session_stage_docs(
            folder, project_id, session_id, stage, store_lane,
            worktree_path, baseline_ref)

        # Bump the active stage entry's doc_count (best-effort bookkeeping).
        try:
            persisted = list((out or {}).get("persisted", []) or [])
            if persisted:
                _bump_stage_doc_count(session_id, stage, len(persisted))
        except Exception:
            pass

        # Schedule the Wave-4 stage-keyed background summary (gated on the same
        # proactive-summary signal; a hard NO-OP in tests/healthcheck).
        try:
            _trigger_background_stage_summary(folder, project_id, store_lane,
                                              session_id, stage)
        except Exception:
            pass

        # Stamp the OPEN stage entry's summary_ref with the stage-summary cache
        # locator, so the (about-to-close) entry references where its async
        # summary lands — satisfies MASTER-PLAN §4.3 "summary_ref on the closing
        # entry" without making generation synchronous (Reviewer W6-R2-01).
        try:
            _stamp_stage_summary_ref(session_id, stage, store_lane)
        except Exception:
            pass

        return out
    except Exception:
        return {"ok": False, "reason": "error", "persisted": []}


def _stamp_stage_summary_ref(session_id, stage, store_lane):
    """Set the OPEN ``stage`` entry's ``summary_ref`` to the stage-summary cache
    locator so the (about-to-close) entry references its async summary (the
    MASTER-PLAN §4.3 'summary_ref on the closing entry' contract, W6-R2-01)."""
    try:
        rec = _reg.get_session(session_id)
        if rec is None:
            return
        history = [dict(e) for e in (rec.get("stage_history") or [])
                   if isinstance(e, dict)]
        changed = False
        for ent in history:
            if ent.get("stage") == stage and ent.get("ended_at") is None:
                ent["summary_ref"] = {"lane": store_lane,
                                      "session_id": session_id, "stage": stage}
                changed = True
        if changed:
            _reg.update_session(session_id, stage_history=history)
    except Exception:
        pass


def _bump_stage_doc_count(session_id, stage, count):
    """Set the OPEN ``stage`` entry's ``doc_count`` (best-effort, in place)."""
    try:
        rec = _reg.get_session(session_id)
        if rec is None:
            return
        history = [dict(e) for e in (rec.get("stage_history") or [])
                   if isinstance(e, dict)]
        changed = False
        for ent in history:
            if (ent.get("stage") == stage and ent.get("ended_at") is None):
                ent["doc_count"] = int(count)
                changed = True
        if changed:
            _reg.update_session(session_id, stage_history=history)
    except Exception:
        return


def _trigger_background_stage_summary(folder, project_id, store_lane,
                                      session_id, stage):
    """Best-effort, NON-BLOCKING: schedule a stage-keyed (Wave-4) session summary.

    Mirrors :func:`_trigger_background_source_summary` (daemon thread + idempotent
    cache skip + the ``ANCHOR_PROACTIVE_SUMMARY`` gate read directly here so the
    keystone never imports ``anchor_gui`` — the module cycle). The difference is
    it threads the ``stage`` into ``summarize_session`` so the cache lands under
    ``<store_lane>/summaries/<sid>/<stage>/``. A hard NO-OP when proactive summary
    is disabled (the default in every unit-test / healthcheck context) — so a
    stubbed context NEVER spawns a live ``claude``.
    """
    if not (folder and project_id and store_lane and session_id and stage):
        return
    if (os.environ.get("ANCHOR_PROACTIVE_SUMMARY", "").strip().lower()
            not in ("1", "true", "yes", "on")):
        return

    def _run():
        try:
            import summarizer as _sm  # lazy: no cycle, optional at import time
            import effort_history as _eh_local
            try:
                if _sm.load_cached(folder, project_id, store_lane,
                                   session_id, stage=stage) is not None:
                    return
            except Exception:
                pass
            try:
                efforts = _eh_local.efforts_for_session_stage(
                    folder, project_id, session_id, stage)
            except Exception:
                efforts = []
            # KEY CONTRACT (fixed 2026-07-26): the summarizer reads
            # ``session["member_files"]`` (summarizer.py:291/:427/:456/:484/:1029).
            # This dict said "efforts", so EVERY summary saw zero members ⇒ empty
            # grounding corpus ⇒ "no grounded claims" + "0 tokens · 0.0s · 0 run(s)".
            # Both keys are carried: member_files for the readers, efforts for
            # any caller still expecting the old name.
            session = {"session_id": session_id, "lane": store_lane,
                       "member_files": efforts, "efforts": efforts}
            _sm.summarize_session(folder, project_id, store_lane, session,
                                  stage=stage)
        except Exception:
            pass

    try:
        import threading
        threading.Thread(target=_run, daemon=True).start()
    except Exception:
        pass


def _start_status_emitter(project_id, sid, worktree_path):
    """Best-effort, NON-BLOCKING: schedule a 10-minute status block emitter (W12)."""
    if os.environ.get("ANCHOR_STATUS_EMITTER", "").strip().lower() in ("0", "false", "no", "off"):
        return

    def _run():
        import time, json
        while True:
            time.sleep(600)  # 10 minute cadence
            try:
                rec = _reg.get_session(sid)
                if not rec or rec.get("status") != _reg.STATUS_RUNNING:
                    break
                
                wave = "?"
                budget = "?"
                state = rec.get("status", "running")
                
                cp_path = os.path.join(worktree_path, "foreman-checkpoint.json")
                if os.path.exists(cp_path):
                    try:
                        with open(cp_path, "r", encoding="utf-8") as f:
                            cp = json.load(f)
                        
                        w = str(cp.get("current_wave", "?"))
                        total = str(cp.get("total_waves", "?"))
                        wave = f"{w}/{total}" if total != "?" else w
                        
                        b = cp.get("budget_remaining", {})
                        bw = b.get("waves")
                        if bw is not None:
                            budget = f"{bw} waves"
                            
                        state = cp.get("status", state)
                    except Exception:
                        pass

                ts = time.strftime("%H:%M")
                msg = f"\n[STATUS {ts}] Wave: {wave} | Budget: {budget} | State: {state}\n"
                
                child = _pty._LIVE.get(sid)
                if child and hasattr(child, "_append"):
                    with getattr(child, "_lock", threading.RLock()):
                        child._append(msg)
            except Exception:
                pass

    try:
        import threading
        threading.Thread(target=_run, daemon=True).start()
    except Exception:
        pass


def finish_stage(session_id, stage=None, store_lane=None, project_id=None):
    """Persist+summarize a stage at a stage boundary — WITHOUT reaping (v12 W5).

    The non-reaping durability primitive (fixes SK-7). It runs the SAME
    persist+summarize keystone path :func:`kill` uses (:func:`_persist_current_stage`),
    against the LIVE worktree, but:

      - does **NOT** reap the PTY or remove the worktree,
      - does **NOT** mark the registry record terminal (the record stays
        ``RUNNING``),
      - records **NO** Boneyard entry (a stage boundary is not a discard).

    ``stage`` / ``store_lane`` are accepted for caller clarity but the
    authoritative source is the session's OPEN ``stage_history`` entry (so the
    baseline diff is correct); they are NOT required.

    Best-effort — NEVER raises / NEVER breaks a caller. Returns
    ``{"ok": True, "session_id", "docs": {...}}`` (``docs`` is the persist
    result), or an honest ``{"ok": False, "reason": ...}`` when the session can't
    be resolved.
    """
    try:
        record = _reg.get_session(session_id)
        if record is None:
            return {"ok": False, "reason": "unknown-session",
                    "session_id": session_id, "docs": {"ok": False,
                    "reason": "unknown-session", "persisted": []}}
        if project_id is None:
            project_id = record.get("project_id") or None
        docs_out = _persist_current_stage(session_id, project_id=project_id,
                                          record=record)
        return {"ok": True, "session_id": session_id, "docs": docs_out}
    except Exception:
        return {"ok": False, "reason": "error", "session_id": session_id,
                "docs": {"ok": False, "reason": "error", "persisted": []}}


# ── v12 Wave 8 — context-fullness heuristic (the warn/handoff trigger) ────────
#
# A stdlib-only "is the live context getting full?" signal. We have no token meter
# for the model running inside the PTY, so we use the live PTY OUTPUT BUFFER as a
# cheap, monotonically-growing proxy: a long-running session that has produced a
# lot of output is, to a useful approximation, a session whose conversation
# context is filling up. The ratio is ``observed_bytes / budget`` (capped at 1.0);
# ``over_threshold`` is ``ratio >= ANCHOR_CONTEXT_FULL_RATIO`` (default 0.8).
#
# This is deliberately a HEURISTIC — it never claims token-exactness. It exists to
# raise the UI warn banner / enable the one-click handoff (Wave 8), not to gate
# anything destructive. Best-effort: a dead/unknown session reports 0.0 (honest —
# we observed nothing), never an exception.

#: The byte budget the observed PTY output is measured against. A full Claude
#: context is ~200k tokens ≈ on the order of ~1 MB of conversational text; we size
#: the budget at ~1 MB (v13 Wave 1 / #7 — raised from the old 200 KB, which a big
#: skill seed alone could blow past on a fresh session, firing a false warning).
#: Overridable via env for tests (``ANCHOR_CONTEXT_FULL_BUDGET``) so a small seeded
#: buffer can push the ratio over the line deterministically without writing ~1 MB.
CONTEXT_FULL_BUDGET_BYTES = 1_000_000

#: Fraction of the budget at/above which ``over_threshold`` flips True. Overridable
#: via ``ANCHOR_CONTEXT_FULL_RATIO`` (a float in 0..1; a bad value falls back).
CONTEXT_FULL_RATIO = 0.8

#: A FIXED allowance (bytes) subtracted from the observed PTY output before the
#: fullness ratio is computed (v13 Wave 1 / #7). The first thing a fresh session
#: prints is its one-time SKILL SEED — that is not conversation growth, so we
#: discount a fixed slice of it. The warning then reflects REAL growth since the
#: seed, not the seed itself. Capped at the budget at use-time (you can never
#: subtract more than the whole budget). Overridable via
#: ``ANCHOR_CONTEXT_SEED_ALLOWANCE``.
CONTEXT_SEED_ALLOWANCE_BYTES = 300_000


def _context_budget_bytes():
    """The byte budget (env-overridable). Falls back to the module default."""
    raw = os.environ.get("ANCHOR_CONTEXT_FULL_BUDGET")
    if raw:
        try:
            v = int(float(raw))
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    return CONTEXT_FULL_BUDGET_BYTES


def _context_full_ratio():
    """The fullness threshold ratio (env-overridable). Falls back to the default."""
    raw = os.environ.get("ANCHOR_CONTEXT_FULL_RATIO")
    if raw:
        try:
            v = float(raw)
            if 0.0 < v <= 1.0:
                return v
        except (TypeError, ValueError):
            pass
    return CONTEXT_FULL_RATIO


def _context_seed_allowance_bytes():
    """The fixed seed allowance to discount (env-overridable, never negative).

    Falls back to :data:`CONTEXT_SEED_ALLOWANCE_BYTES`. A ``0`` value is honored
    (no allowance). Capping against the budget happens at the call site.
    """
    raw = os.environ.get("ANCHOR_CONTEXT_SEED_ALLOWANCE")
    if raw is not None and raw.strip():
        try:
            v = int(float(raw))
            if v >= 0:
                return v
        except (TypeError, ValueError):
            pass
    return CONTEXT_SEED_ALLOWANCE_BYTES


def context_fullness(session_id):
    """Estimate how "full" a live session's context is (v12 Wave 8).

    A stdlib heuristic over the session's LIVE PTY output buffer: the observed
    output size is a cheap, monotonically-growing proxy for how much conversation
    has accumulated. Returns ``{"ratio": float in 0..1, "over_threshold": bool,
    "observed_bytes": int, "growth_bytes": int, "budget": int}`` where:

      - ``observed_bytes`` = the live PTY buffer length (``read_since`` cursor 0);
      - ``growth_bytes`` = ``max(0, observed_bytes - seed_allowance)`` — the bytes
        printed BEYOND the one-time skill seed (v13 Wave 1 / #7): the seed is not
        conversation growth, so a fixed allowance (capped at the budget) is
        discounted before the ratio so a freshly-seeded session does not falsely
        read as "full";
      - ``ratio`` = ``min(1.0, growth_bytes / budget)``;
      - ``over_threshold`` = ``ratio >= ANCHOR_CONTEXT_FULL_RATIO`` (default 0.8);
      - ``budget`` = :data:`CONTEXT_FULL_BUDGET_BYTES` (env-overridable).

    BEST-EFFORT — never raises. A dead / unknown / un-resolvable session honestly
    reports ``{"ratio": 0.0, "over_threshold": False, ...}`` (we observed nothing,
    so we never claim it is full).
    """
    budget = _context_budget_bytes()
    out = {"ratio": 0.0, "over_threshold": False, "observed_bytes": 0,
           "growth_bytes": 0, "budget": budget}
    try:
        res = _pty.read_since(session_id, 0)
    except _pty.UnknownSession:
        return out
    except Exception:
        return out
    text = (res.get("text") or "") if isinstance(res, dict) else ""
    # Measure BYTES (utf-8) — a UTF-8 char can be >1 byte and the budget is a byte
    # budget; tolerate an encode failure by falling back to the char length.
    try:
        observed = len(text.encode("utf-8", "replace"))
    except Exception:
        observed = len(text)
    # Discount a FIXED seed allowance (#7): the first thing a fresh session prints
    # is its one-time skill seed, which is NOT conversation growth. Cap the
    # allowance at the budget so we never subtract more than the whole budget
    # (keeps tiny deterministic test budgets sane). The ratio is computed on the
    # REAL growth beyond the seed; observed_bytes is still reported raw.
    allowance = min(_context_seed_allowance_bytes(), budget) if budget else 0
    growth = observed - allowance
    if growth < 0:
        growth = 0
    ratio = min(1.0, growth / float(budget)) if budget else 0.0
    out["observed_bytes"] = observed
    out["growth_bytes"] = growth
    out["ratio"] = ratio
    out["over_threshold"] = ratio >= _context_full_ratio()
    return out


def advance_stage(session_id, to_stage=None, mode="manual", project_id=None,
                  load_skill=False, actor=None):
    """Advance an effort to the next stage IN THE SAME SESSION (v12 Wave 6).

    The continuity-first "Advance" = **relabel + save**: the effort keeps its ONE
    session, the SAME worktree, and the SAME PTY — Anchor merely persists +
    summarizes the stage just completed and flips the record to the next stage.
    **It spawns no new session and, by default, injects NOTHING into the PTY.**

    Mechanics (all under :data:`paths.WRITE_LOCK`, so a manual+auto race yields
    exactly ONE advance):

      1. Resolve + validate: the session must be a LIVE effort of
         ``kind in {'trio','grass-dev'}``. ``to_stage`` defaults to the NEXT trio
         stage after ``current_stage`` (research→plan→build).
      2. **Idempotent** — if the effort is already at/past ``to_stage``
         (``current_stage >= to_stage``), this is a NO-OP and returns the current
         record with ``advanced=False``. (So a manual Advance racing the auto
         poll under the lock advances once; the loser no-ops.)
      3. Mark ``effort_managed=True`` (Wave-1 discriminator; idempotent).
      4. **Finish the current stage** via :func:`finish_stage` (Wave-5: persist
         the stage-scoped docs + schedule the stage summary, **no reap**, the
         record stays RUNNING). The current stage entry is opened at effort start
         (Wave-6 start change) / on the prior advance; if it is somehow absent it
         is opened defensively here first so the persist is stage-scoped.
      5. **Record the new stage's baseline** (:func:`effort_history
         .record_stage_baseline`) + open its stage entry and flip
         ``current_stage`` + ``lane`` via :func:`session_registry.set_current_stage`.
      6. **Inject NOTHING into the PTY by default.** ``mode='manual'`` MAY pass
         ``load_skill=True`` to write ONE skill-load turn (explicit opt-in,
         default False). ``mode='auto'`` NEVER writes to the PTY.

    Returns the updated registry record (with ``advanced``/``ok`` markers). Never
    raises — an unknown/ineligible session returns an honest
    ``{"ok": False, "reason": ...}``.
    """
    with _paths.WRITE_LOCK:
        try:
            record = _reg.get_session(session_id)
        except Exception:
            return {"ok": False, "reason": "error", "session_id": session_id}
        if record is None:
            return {"ok": False, "reason": "unknown-session",
                    "session_id": session_id}

        # Validate: a LIVE trio/grass-dev effort only.
        if record.get("status") != _reg.STATUS_RUNNING:
            return {"ok": False, "reason": "not-live",
                    "session_id": session_id, "record": record}
        kind = record.get("kind") or ""
        if kind not in ("trio", "grass-dev"):
            return {"ok": False, "reason": "not-an-effort",
                    "session_id": session_id, "record": record}

        if project_id is None:
            project_id = record.get("project_id") or None

        current_stage = record.get("current_stage") or ""
        # Resolve the target stage (default = the next trio stage).
        if not to_stage:
            to_stage = _next_stage(current_stage)
        if not to_stage:
            return {"ok": False, "reason": "no-next-stage",
                    "session_id": session_id, "record": record}

        # Validate the target is a real trio stage — a garbage to_stage must be an
        # HONEST error, never a silent "already-advanced" no-op (Reviewer W6-R2-02).
        if _stage_rank(to_stage) < 0:
            return {"ok": False, "reason": "invalid-stage",
                    "session_id": session_id, "record": record}
        # Single-step only: the spec advances to the NEXT stage; skipping a stage
        # (e.g. research→build, omitting plan) is rejected (Reviewer W6-R2-03).
        if _stage_rank(to_stage) > _stage_rank(current_stage) + 1:
            return {"ok": False, "reason": "invalid-stage-skip",
                    "session_id": session_id, "record": record}

        # Idempotency: already at/past the target → no-op (the loser of a
        # manual+auto race). Compares by trio-stage rank.
        if _stage_rank(current_stage) >= _stage_rank(to_stage):
            return {"ok": True, "advanced": False, "reason": "already-advanced",
                    "session_id": session_id, "record": record}

        # Wave-1 discriminator: this effort is now v12-managed.
        if not record.get("effort_managed"):
            try:
                record = _reg.update_session(session_id, effort_managed=True)
            except Exception:
                pass

        # Defensive: ensure the CURRENT stage has an open entry so finish_stage is
        # stage-scoped (it should already, from the Wave-6 start change). Open it
        # over the live worktree with a fresh baseline only if missing.
        if _active_stage_entry(record) is None and current_stage:
            try:
                wt = record.get("worktree_path", "")
                baseline = _eh.record_stage_baseline(wt) if wt else ""
                record = _reg.set_current_stage(
                    session_id, current_stage,
                    _store_lane_for_stage(current_stage), baseline)
            except Exception:
                pass

        # Finish (persist + summarize) the CURRENT stage — NO reap (Wave 5).
        finished = finish_stage(session_id, current_stage,
                                _store_lane_for_stage(current_stage),
                                project_id=project_id)

        # Open the NEW stage: record its baseline + flip current_stage + lane.
        new_store_lane = _store_lane_for_stage(to_stage)
        try:
            wt = record.get("worktree_path", "")
            new_baseline = _eh.record_stage_baseline(wt) if wt else ""
        except Exception:
            new_baseline = ""
        try:
            # W12 (C3, D1): journal-first-then-legacy. Emit ``session-advanced``
            # (correlation_id = the effort/chain; causation_id = the chain parent)
            # BEFORE the legacy stage-flip write — best-effort, off-switch-gated,
            # so with the journal flag off ONLY set_current_stage runs.
            record = _journal.dual_write(
                project_id, _journal.EV_SESSION_ADVANCED,
                lambda: _reg.set_current_stage(
                    session_id, to_stage, new_store_lane, new_baseline),
                correlation_id=(record.get("chain_id")
                                or record.get("effort_id") or session_id),
                actor=actor,
                causation_id=(record.get("parent_session_id") or None),
                payload={"session_id": session_id, "lane": new_store_lane,
                         "from_stage": current_stage, "to_stage": to_stage},
            )
        except Exception as exc:
            return {"ok": False, "reason": "set-stage-failed",
                    "detail": str(exc), "session_id": session_id,
                    "finished": finished}

        # PTY injection policy: NOTHING by default. Only an explicit manual
        # opt-in (load_skill=True) writes ONE skill-load turn; auto NEVER writes.
        if mode == "manual" and load_skill:
            try:
                skill = LANE_SKILL.get(new_store_lane) or LANE_SKILL.get(to_stage)
                if skill:
                    _pty.write(session_id,
                               "Please load the %s skill and continue.\n" % skill)
                    try:
                        seeded = list(record.get("seeded_stages") or [])
                        if to_stage not in seeded:
                            seeded.append(to_stage)
                            record = _reg.update_session(
                                session_id, seeded_stages=seeded)
                    except Exception:
                        pass
            except Exception:
                pass

        return {"ok": True, "advanced": True, "session_id": session_id,
                "from_stage": current_stage, "to_stage": to_stage,
                "finished": finished, "record": record}


# ── v12 Wave 7 — on-disk-only stage-progress detection (NO PTY scrape) ────────

# Filename signals (basename, case-insensitive). research→plan requires the
# MASTER+IMPL pair; plan→build requires an execution log OR a build product.
_PLAN_SET_NAMES = ("master-plan.md", "implementation-plan.md")
_BUILD_SIGNAL_NAMES = ("execution-log.md",)


def _committed_since_baseline(worktree_path, baseline_ref):
    """Repo-relative POSIX paths COMMITTED into ``worktree_path`` SINCE
    ``baseline_ref`` (the HEAD captured at the stage's start). On-disk ONLY —
    reads the git history, never the PTY.

    This is the precise, clock-INDEPENDENT "newer than the stage start" signal:
    ``git diff --name-only <baseline_ref>..HEAD`` lists exactly the files whose
    state changed in commits made AFTER the baseline. Unlike a commit-TIME
    comparison it is unambiguous at sub-second resolution (a stage-start baseline
    and a file committed in the same wall-clock second are still correctly
    separated by the commit DAG), so a research/plan doc committed BEFORE the
    current stage's baseline is never mistaken for the current stage's product.

    Best-effort: a non-repo / missing-git worktree → empty set. A FALSY
    ``baseline_ref`` (the first stage of a brand-new repo, no earlier HEAD) →
    diff against the git EMPTY-TREE so the stage's first commits still register;
    if even that is unavailable, an empty set (honest — never fabricate).
    Only COMMITTED changes count (an uncommitted working-tree file is NOT a
    signal — the v11.1 isolation contract).
    """
    out = set()
    wt = Path(worktree_path) if worktree_path else None
    if not wt or not wt.is_dir():
        return out
    base = baseline_ref or _eh._empty_tree_sha(wt)
    if not base:
        return out
    try:
        r = _eh._git(wt, "diff", "--name-only", "%s..HEAD" % base)
    except Exception:
        return out
    if r.returncode != 0:
        return out
    for line in (r.stdout or "").splitlines():
        p = line.strip().strip('"')
        if p:
            out.add(p.replace("\\", "/"))
    return out


def _basenames(rels):
    """Lowercased basenames of an iterable of repo-relative paths."""
    names = set()
    for rel in rels:
        try:
            names.add(PurePosixPath(rel).name.lower())
        except Exception:
            continue
    return names


def detect_stage_progress(session_id, project_id=None):
    """Auto-advance an effort on a HIGH-PRECISION ON-DISK signal (v12 Wave 7).

    Called from the cockpit's ``term_sessions`` refresh for an ``effort_managed``
    effort. It reads **ZERO PTY bytes** — the decision is made entirely from the
    worktree's *committed* git history, NOT by scraping the terminal for a skill
    name (which caused the v11.1 seed-echo false-fire). The signal per current
    stage:

      - **research → plan** — a COMMITTED ``MASTER-PLAN.md`` **and**
        ``IMPLEMENTATION-PLAN.md`` pair whose commit-time is **newer than the
        research stage's start**.
      - **plan → build** — a committed ``EXECUTION-LOG.md`` (or a committed build
        PRODUCT — a non-doc artifact) whose commit-time is **newer than the plan
        stage's start**.

    A conversation-only stage (no committed plan files) does **NOT** auto-advance
    — that is the manual ``Advance →``'s job (W10). On a positive signal it calls
    :func:`advance_stage` with ``mode='auto'`` (which writes nothing to the PTY
    and persists+summarizes the closing stage). It is **idempotent**: re-polling
    after an advance is a no-op via ``advance_stage``'s ``current_stage >=
    to_stage`` guard, and the same on-disk signal simply re-passes harmlessly.

    Returns ``{"ok": bool, "advanced": bool, "reason": str, ...}``. Never raises
    — any failure (unknown session, non-effort, git error) is an honest no-op so
    the read-only refresh path is never broken. Gated OUT (``advanced=False``)
    for a legacy (``effort_managed==False``) record — the legacy auto-advance
    paths own those (the retirement map).
    """
    try:
        rec = _reg.get_session(session_id)
    except Exception:
        return {"ok": False, "advanced": False, "reason": "error",
                "session_id": session_id}
    if rec is None:
        return {"ok": False, "advanced": False, "reason": "unknown-session",
                "session_id": session_id}

    # ON-DISK detect is for v12 efforts ONLY. A legacy record is owned by the
    # legacy auto-advance paths (the retirement map keeps them live there).
    if not rec.get("effort_managed"):
        return {"ok": True, "advanced": False, "reason": "not-effort-managed",
                "session_id": session_id}

    # Must be a LIVE trio/grass-dev effort.
    if rec.get("status") != _reg.STATUS_RUNNING:
        return {"ok": True, "advanced": False, "reason": "not-live",
                "session_id": session_id}
    if (rec.get("kind") or "") not in ("trio", "grass-dev"):
        return {"ok": True, "advanced": False, "reason": "not-an-effort",
                "session_id": session_id}

    current_stage = rec.get("current_stage") or ""
    to_stage = _next_stage(current_stage)
    if not to_stage:
        return {"ok": True, "advanced": False, "reason": "no-next-stage",
                "session_id": session_id}

    entry = _active_stage_entry(rec)
    baseline_ref = (entry.get("baseline_ref")
                    if isinstance(entry, dict) else "") or ""
    worktree_path = rec.get("worktree_path", "")
    if not worktree_path:
        return {"ok": True, "advanced": False, "reason": "no-worktree",
                "session_id": session_id}
    # The empty-tree fallback in _committed_since_baseline is only legitimate for
    # the chain-root research stage; for plan/build an EMPTY baseline_ref would
    # diff the empty tree and over-report prior-stage commits → a false-fire. Treat
    # a missing plan/build baseline as no signal (W7-R2-03 / R1-W7-03).
    if not baseline_ref and current_stage != "research":
        return {"ok": True, "advanced": False, "reason": "no-baseline",
                "session_id": session_id}

    # On-disk signal: files COMMITTED since the current stage's baseline. ZERO
    # PTY. Clock-independent (committed-since-baseline, not commit-TIME) so a
    # sub-second test and a prior-stage doc are correctly separated.
    committed = _committed_since_baseline(worktree_path, baseline_ref)
    names = _basenames(committed)

    advance = False
    if current_stage == "research" and to_stage == "plan":
        # Require BOTH the master plan AND the implementation plan, committed
        # newer than the research stage start (a committed pair — never an
        # uncommitted working-tree file, never a PTY echo).
        advance = all(n in names for n in _PLAN_SET_NAMES)
    elif current_stage == "plan" and to_stage == "build":
        # A committed execution log OR a committed build PRODUCT (a non-doc
        # artifact newer than the plan stage start).
        has_log = any(n in names for n in _BUILD_SIGNAL_NAMES)
        has_product = any(
            not _eh._is_document_rel(rel) for rel in committed)
        advance = has_log or has_product
    else:
        return {"ok": True, "advanced": False, "reason": "stage-not-auto",
                "session_id": session_id}

    if not advance:
        return {"ok": True, "advanced": False, "reason": "no-disk-signal",
                "session_id": session_id}

    # High-precision signal present → advance IN-SESSION (mode='auto' writes
    # nothing to the PTY). advance_stage is idempotent under the lock, so a
    # re-poll after the flip is a clean no-op.
    res = advance_stage(session_id, to_stage, mode="auto",
                        project_id=project_id)
    return {"ok": bool(res.get("ok")),
            "advanced": bool(res.get("advanced")),
            "reason": res.get("reason", "advanced"),
            "session_id": session_id,
            "from_stage": current_stage, "to_stage": to_stage,
            "result": res}


# ── v12 Wave 8 — context-relief handoff + restart recovery ────────────────────


def _to_stage_for_handoff_lane(stage):
    """The TARGET lane a context-relief handoff continues the SAME stage in.

    A handoff does NOT advance the stage — it continues the effort's current
    stage in a fresh session. So the new session is started in the SAME stage's
    store-lane and :func:`prepare_stage_handoff` builds a prompt FOR that stage
    (research→research, plan/planning→plan, build→build). Defaults to ``research``
    for an effort with no recorded current stage (a bare/grass-dev start).
    """
    if stage == "plan":
        return "plan"
    if stage == "build":
        return "build"
    return "research"


def handoff_to_fresh(effort_id_or_sid, project_id=None):
    """Continue a full effort in a FRESH session that JOINS the same effort (W8).

    The **context-relief valve** (SC2): when the live context window fills (or the
    user clicks the warn banner), the effort continues in a brand-new session that
    carries the SAME ``effort_id`` (same tile / lineage), with the prior stage's
    docs + summary forward via the proven v11.1 machinery — and **nothing
    auto-submitted**. Mechanics:

      1. Resolve the OLD session (accepts either a ``session_id`` OR an
         ``effort_id`` — we take it as the source session to hand off from).
      2. :func:`finish_stage` the OLD session's current stage (Wave-5: persist the
         stage-scoped docs + schedule the summary, **NO reap** — the old worktree
         survives, the record stays as-is until we mark its stage done).
      3. :func:`prepare_stage_handoff` (v11.1) PERSISTS the produced docs (idempotent
         with the finish above) and BUILDS the REAL doc-referencing next prompt for
         the SAME stage.
      4. :func:`start_session` a FRESH session — inheriting ``effort_id`` (joins the
         same effort), ``effort_managed=True``, in the SAME stage's lane, linked as a
         child (``parent_session_id`` → the old sid, so it joins the chain), with the
         built prompt as a **PENDING PASTE** (held UNSENT until the user presses
         Enter — the v11.1 contract; NOTHING auto-submitted).
      5. Mark the OLD session's current stage entry CLOSED (``state='done'``). The
         OLD worktree is **NOT reaped** (close-keeps-record discipline).

    Returns ``{"ok", "old_session", "new_session", "effort_id", "prompt",
    "persisted"}`` (the records are the full registry records; the endpoint layer
    SAFE-projects them). Honest ``{"ok": False, "reason": ...}`` for an unknown /
    un-resolvable source. Best-effort on the bookkeeping (finish/mark-done) — a
    hiccup there never aborts the handoff itself.
    """
    # (1) Resolve the OLD/source session. ``effort_id_or_sid`` may be either id —
    # a record's effort_id defaults to its own sid for a fresh effort, so a direct
    # session_id lookup works for the common case. If it's an effort_id that is NOT
    # itself a session id, fall back to the newest RUNNING member of that effort.
    old_sid = effort_id_or_sid
    rec = None
    try:
        rec = _reg.get_session(old_sid)
    except Exception:
        rec = None
    if rec is None:
        # Treat the arg as an effort_id: find the live (or newest) member.
        try:
            members = [r for r in _reg.list_sessions()
                       if isinstance(r, dict)
                       and (r.get("effort_id") or r.get("session_id"))
                       == effort_id_or_sid]
        except Exception:
            members = []
        running = [r for r in members
                   if r.get("status") == _reg.STATUS_RUNNING]
        pick = running or members
        if pick:
            # newest by created_at (None sorts first → use a safe key)
            pick.sort(key=lambda r: (r.get("created_at") or 0))
            rec = pick[-1]
            old_sid = rec.get("session_id")
    if rec is None:
        return {"ok": False, "reason": "unknown-session",
                "session_id": effort_id_or_sid}

    if project_id is None:
        project_id = rec.get("project_id") or None
    if not project_id:
        return {"ok": False, "reason": "no-project", "session_id": old_sid}

    effort_id = rec.get("effort_id") or old_sid
    current_stage = rec.get("current_stage") or ""
    backend = rec.get("backend") or DEFAULT_ENGINE
    to_lane = _to_stage_for_handoff_lane(current_stage)

    # (2) Finish (persist + summarize) the OLD session's current stage — NO reap.
    # Best-effort: a finish hiccup must not abort the handoff (the prepare below
    # also persists, idempotently).
    try:
        finish_stage(old_sid, current_stage,
                     _store_lane_for_stage(current_stage) if current_stage
                     else None, project_id=project_id)
    except Exception:
        pass

    # (3) Build the REAL doc-referencing prompt for the SAME stage (v11.1).
    try:
        prep = prepare_stage_handoff(project_id, old_sid, to_lane)
    except Exception:
        prep = {"ok": False, "prompt": "", "persisted": []}
    prompt = (prep.get("prompt") or "") if isinstance(prep, dict) else ""
    persisted = list((prep.get("persisted") or [])
                     if isinstance(prep, dict) else [])

    # (4) Start a FRESH session that JOINS the same effort (inherits effort_id),
    # linked into the old session's chain, with the prompt held as a PENDING
    # PASTE (UNSENT — nothing auto-submitted, the v11.1 contract).
    try:
        new_rec = start_session(
            project_id, to_lane, backend=backend,
            parent_session_id=old_sid,
            paste_prompt=(prompt or None),
            effort_id=effort_id, effort_managed=True)
    except TerminalSessionError as exc:
        return {"ok": False, "reason": "start-failed", "detail": str(exc),
                "session_id": old_sid}

    # (5) Mark the OLD session's CURRENT stage entry closed (state 'done') WITHOUT
    # reaping the worktree (close-keeps-record). Best-effort, in place.
    try:
        _close_active_stage_entry(old_sid)
    except Exception:
        pass

    return {
        "ok": True,
        "old_session": _reg.get_session(old_sid),
        "new_session": new_rec,
        "effort_id": effort_id,
        "prompt": prompt,
        "persisted": persisted,
    }


def _close_active_stage_entry(session_id, state="done"):
    """Stamp the OPEN ``stage_history`` entry closed (``ended_at`` + ``state``).

    Used by the context-relief handoff (``state='done'``) and restart recovery
    (``state='interrupted'``). Does NOT reap / does NOT touch the worktree — it
    only closes the bookkeeping entry. Best-effort, in place; returns the updated
    record or None.
    """
    try:
        rec = _reg.get_session(session_id)
        if rec is None:
            return None
        import time as _time
        history = [dict(e) for e in (rec.get("stage_history") or [])
                   if isinstance(e, dict)]
        changed = False
        for ent in history:
            if ent.get("ended_at") is None:
                ent["ended_at"] = _time.time()
                ent["state"] = state
                changed = True
        if changed:
            return _reg.update_session(session_id, stage_history=history)
        return rec
    except Exception:
        return None


def recover_interrupted_efforts(live_session_ids=None):
    """Recover effort-managed efforts whose PTY died (boot/reconcile) (v12 W8).

    A crash / restart is NOT a "close": an ``effort_managed`` record whose status
    is RUNNING but whose PTY is GONE (not in :func:`pty_manager.live_sessions`)
    has had its work interrupted. For each such effort this:

      - PERSISTS whatever the active stage's worktree holds (Wave-5
        :func:`finish_stage` path — committed/working/untracked stage-scoped docs;
        **no reap**, the worktree survives so the stage is reopenable);
      - marks the active stage entry ``state='interrupted'`` — a literal DISTINCT
        from ``'done'`` (an orderly stage finish) and ``'failed'`` — and re-statuses
        the record IDLE (no live process) so it is honestly "not running";
      - leaves it **reopenable to continue the SAME stage** (a fresh session
        inheriting ``effort_id`` can be started later — but this NEVER auto-spawns
        one and NEVER auto-advances; the user reopens it).

    IDEMPOTENT: a stage already marked ``interrupted`` (or with no active entry) is
    not re-processed. BEST-EFFORT — never raises; a failure on one effort never
    blocks the others. Reads, never reaps, live members; does NOT touch the Anchor
    repo (it operates only on per-session worktrees via the persist seam). Returns
    ``{"ok": True, "recovered": [session_id, ...]}``.
    """
    recovered = []
    try:
        if live_session_ids is None:
            try:
                live = set(_pty.live_sessions())
            except Exception:
                live = set()
        else:
            live = set(live_session_ids)

        try:
            records = _reg.list_sessions()
        except Exception:
            records = []

        for rec in records:
            try:
                if not isinstance(rec, dict):
                    continue
                # ONLY v12 efforts — legacy records are owned by reconcile.
                if not rec.get("effort_managed"):
                    continue
                sid = rec.get("session_id")
                if not sid:
                    continue
                # RUNNING-but-PTY-gone is the reconcile-dead / restart state.
                if rec.get("status") != _reg.STATUS_RUNNING:
                    continue
                if sid in live:
                    continue  # PTY is alive — not interrupted

                entry = _active_stage_entry(rec)
                # No open stage entry, or already interrupted → idempotent skip.
                if entry is None:
                    continue
                if entry.get("state") == "interrupted":
                    continue

                project_id = rec.get("project_id") or None

                # Persist whatever the active stage's worktree holds — Wave-5
                # finish_stage path (NO reap, the worktree survives so the stage
                # stays reopenable). Best-effort.
                try:
                    finish_stage(sid, entry.get("stage"),
                                 entry.get("store_lane"), project_id=project_id)
                except Exception:
                    pass

                # Mark the active stage entry 'interrupted' (≠ done, ≠ failed) +
                # re-status the record IDLE (no live process). NEVER auto-spawn /
                # auto-advance — the effort is simply reopenable.
                try:
                    _close_active_stage_entry(sid, state="interrupted")
                except Exception:
                    pass
                try:
                    _reg.update_session(sid, status=_reg.STATUS_IDLE)
                except Exception:
                    pass

                recovered.append(sid)
            except Exception:
                continue
    except Exception:
        pass
    return {"ok": True, "recovered": recovered}


def kill(session_id, project_id=None, _record_boneyard=True, actor=None):
    """Kill a session: reap the PTY, mark terminal, PERSIST DOCS, remove worktree.

    Tolerant: an unknown/already-dead PTY still proceeds to re-status the registry
    record (``STATUS_DONE``) and remove the worktree. ``project_id`` is resolved
    from the registry record when not supplied so the worktree's owning repo can
    be located for a clean ``git worktree remove``. Other sessions are untouched.

    v8 Wave 2 (THE KEYSTONE): BEFORE the worktree is reaped, the session's
    produced documents are persisted into the MAIN project (copied + committed
    via :func:`capture_session_docs` → ``effort_history.persist_session_docs``)
    so they survive the kill, are discoverable from the main folder, and ride
    into later worktrees (which are checked out off main HEAD). This is
    best-effort — a persistence failure never blocks the kill.

    ``_record_boneyard`` (PRIVATE, default ``True``): when ``False`` the v10 W6
    ``killed`` Boneyard capture is SUPPRESSED. :func:`delete_session` passes
    ``False`` when it kills a still-live session as part of a delete — the
    ``deleted`` entry is the canonical record for a delete, so a kill-driven
    ``killed`` entry would be a spurious DUPLICATE. Doc PERSISTENCE
    (``capture_session_docs``) still runs regardless — only the Boneyard record is
    suppressed, so the subsequent ``deleted`` entry's ``doc_rels`` are populated.

    Returns ``{"ok": True, "session_id", "pty_killed", "docs": {...},
    "worktree": {...}}``.
    """
    record = _reg.get_session(session_id)
    if project_id is None and record:
        project_id = record.get("project_id") or None

    pty_killed = False
    try:
        _pty.kill(session_id)
        pty_killed = True
    except _pty.UnknownSession:
        pty_killed = False  # already dead / never had a live PTY — tolerate

    # ── zombie-hunter safe-to-arm, Wave 5: PERSIST-BEFORE-TERMINAL ORDERING ──
    #
    # THE invariant: the session's produced docs are captured/persisted to MAIN
    # and CONFIRMED *before* the registry record is marked DONE/terminal. The
    # historical order (mark DONE, then persist) meant a crash or a reaper sweep
    # racing between the two saw a terminal record whose docs had NOT yet reached
    # main — a doc-loss window. Persisting first closes it: if anything interrupts
    # the kill after this point, the record is still non-terminal (recoverable)
    # and the docs are already safe in main.
    #
    # v8 KEYSTONE: capture + persist BEFORE the worktree is reaped (after which
    # they'd be gone forever). v12 Wave 5: this routes through the SHARED
    # persist+summarize keystone (:func:`_persist_current_stage`) that
    # :func:`finish_stage` also calls — so a stage boundary and a kill persist
    # identically. For a v12 effort with a recorded active stage it persists ONLY
    # that stage's docs (Wave-3) and schedules the stage-keyed summary (Wave-4);
    # for every legacy/non-effort session it falls back to the EXACT pre-v12
    # whole-tree :func:`capture_session_docs`, so kill's observable persisted-doc
    # set (fed to the worktree-removal + the Boneyard below) is unchanged.
    # Best-effort (never blocks kill).
    docs_out = _persist_current_stage(session_id, project_id=project_id,
                                      record=record)

    # Honest Telemetry W4: eager finalize on the KILL end path — capture the
    # engine sidecar's usage into Anchor's own durable ``.anchor/`` store as the
    # session's single RUN cost record (idempotent CAS; never halts the kill).
    _finalize_usage_safe(session_id, project_id=project_id, record=record)

    # ── zombie-hunter safe-to-arm, Wave 6: teardown owns the PTY AND the jobs ──
    #
    # A dead session must NEVER leave its ``job_runner`` jobs alive — that is the
    # exact orphan-swarm the reaper exists to prevent. Reap every job THIS session
    # owns via a targeted per-``job_id`` cancel (never a full ``list_records``
    # scan), reference-counted so a job handed off to a live successor survives.
    # This runs BEFORE the record is marked terminal so the record stays HONEST
    # (visible/RUNNING) until the owned jobs are confirmed reaped — a hidden
    # (terminal) record whose jobs are still live is exactly the lie we forbid.
    # Best-effort: a teardown failure never blocks the kill.
    jobs_out = _teardown_owned_jobs(session_id, record=record,
                                    project_id=project_id)

    # Docs are now persisted + confirmed AND owned jobs reaped → NOW mark the
    # registry record terminal (DONE) — tolerate an unknown id.
    # W12 (C3, D1): journal-first — emit ``session-killed`` BEFORE the legacy
    # DONE write (best-effort, off-switch-gated: with the journal flag off ONLY
    # update_session runs, byte-identical to before).
    try:
        _journal.dual_write(
            project_id, _journal.EV_SESSION_KILLED,
            lambda: _reg.update_session(session_id, status=_reg.STATUS_DONE),
            correlation_id=((record or {}).get("chain_id") or session_id),
            actor=actor,
            causation_id=((record or {}).get("parent_session_id") or None),
            payload={"session_id": session_id,
                     "lane": (record or {}).get("lane", "")},
        )
    except KeyError:
        pass

    # Remove the per-session worktree (safety-checked, tolerant of already-gone).
    wt_out = _wt.remove_worktree(session_id, project_id=project_id)

    # v10 Wave 6 — Boneyard capture (D3 source "killed"). A hard-kill is the
    # deliberate "I'm done / discarding" action; if this session PRODUCED material
    # (persisted docs), index it in the project's Boneyard. This is purely ADDITIVE
    # — the session's normal finished tile/record is unaffected — and BEST-EFFORT:
    # a Boneyard failure must NEVER break the kill path. SUPPRESSED when this kill
    # is part of a delete_session (the canonical "deleted" entry is recorded there;
    # a "killed" entry too would be a spurious duplicate for ONE delete).
    if _record_boneyard:
        _capture_killed_to_boneyard(session_id, project_id, record, docs_out)

    return {
        "ok": True,
        "session_id": session_id,
        "pty_killed": pty_killed,
        "docs": docs_out,
        "jobs": jobs_out,
        "worktree": wt_out,
    }


# ── zombie-hunter safe-to-arm, Wave 6: reference-counted owned-job teardown ───

def _teardown_owned_jobs(session_id, record=None, *, project_id=None):
    """Reap every ``job_runner`` job ``session_id`` owns — reference-counted (W6).

    Closes the swarm-job leak: a session that dies must never leave its jobs
    alive. Two ownership sources are walked, BOTH off the SESSION registry so we
    NEVER do a full ``job_runner.list_records`` scan:

    1. **Explicit claims** — ``record["owned_job_ids"]`` (a successor claims a
       shared/handed-off job here).
    2. **Worktree-shared live swarm jobs** — every spawned ``job_runner`` job
       mints a ``SWARM_LANE`` session record keyed by its ``job_id`` with
       ``worktree_path == cwd``; a job running in THIS session's worktree is one
       this session owns. This is the real orphan-swarm.

    Ownership is REFERENCE-COUNTED: for each owned job, if a LIVE (RUNNING)
    successor still claims it, the job SURVIVES and this session's claim is
    released (an explicit ownership transfer to the successor). Otherwise this
    session is the last owner → a targeted per-``job_id``
    :func:`job_runner.cancel` (tree-kill + terminal status) reaps it.

    Best-effort + tolerant: an unknown job id, a cancel failure, or a missing job
    runner never raises. Returns ``{"cancelled": [...], "transferred": [...],
    "already_terminal": [...], "all_reaped": bool}``.
    """
    result = {"cancelled": [], "transferred": [], "already_terminal": [],
              "all_reaped": True}
    try:
        import job_runner as _jr
    except Exception:  # pragma: no cover - no job runner → nothing to reap
        return result

    rec = record if record is not None else _reg.get_session(session_id)

    # ONE registry snapshot for the whole teardown (the reference-count source).
    try:
        all_records = _reg.list_sessions()
    except Exception:
        all_records = []

    # (1) Explicit claims on this session's record.
    owned = list(_reg.owned_jobs(rec if rec is not None else session_id))

    # (2) Worktree-shared LIVE swarm jobs (the real orphan-swarm).
    wt = (rec or {}).get("worktree_path") if isinstance(rec, dict) else None
    if wt:
        try:
            wt_norm = str(Path(wt))
        except (TypeError, ValueError):
            wt_norm = str(wt)
        swarm_lane = getattr(_jr, "SWARM_LANE", "swarm")
        for r in all_records:
            if not isinstance(r, dict):
                continue
            if r.get("lane") != swarm_lane:
                continue
            if r.get("status") != _reg.STATUS_RUNNING:
                continue
            jid = r.get("session_id")
            if not jid or jid == session_id or jid in owned:
                continue
            try:
                r_wt = str(Path(r.get("worktree_path") or "")) if r.get(
                    "worktree_path") else ""
            except (TypeError, ValueError):
                r_wt = str(r.get("worktree_path") or "")
            if r_wt and r_wt == wt_norm:
                owned.append(jid)

    # (3) Reference-counted reap.
    for jid in owned:
        try:
            claimants = _reg.job_claimants(jid, records=all_records,
                                           exclude=session_id)
        except Exception:
            claimants = []
        live_claimant = None
        for c in claimants:
            if isinstance(c, dict) and c.get("status") == _reg.STATUS_RUNNING:
                live_claimant = c.get("session_id")
                break
        if live_claimant is not None:
            # Hand-off: a live successor is the sole remaining owner. Record the
            # explicit ownership transfer by releasing THIS session's claim.
            try:
                _reg.release_job(session_id, jid)
            except Exception:
                pass
            result["transferred"].append({"job_id": jid, "to": live_claimant})
            continue
        # No live claimant → last owner. Targeted per-job_id cancel/reap.
        try:
            crec = _jr.cancel(jid)
        except Exception:
            crec = None
        if crec is None:
            # Unknown / already-gone job id — nothing left to reap.
            result["already_terminal"].append(jid)
        else:
            status = crec.get("status")
            if status in getattr(_jr, "TERMINAL_STATUSES", frozenset()):
                result["cancelled"].append(jid)
            else:
                # Cancel did not confirm terminal — the record is NOT honest yet.
                result["all_reaped"] = False
                result["cancelled"].append(jid)
        # Drop our now-defunct claim so a stale record never re-lists it.
        try:
            _reg.release_job(session_id, jid)
        except Exception:
            pass

    return result


def _capture_killed_to_boneyard(session_id, project_id, record, docs_out):
    """Index a killed session in the Boneyard iff it produced material (W6).

    BEST-EFFORT — swallows every error so a Boneyard failure can never break the
    kill path. References the docs the v8 keystone just persisted (no copy).
    """
    if _boneyard is None:
        return
    try:
        rec = record if record is not None else _reg.get_session(session_id)
        if rec is None:
            return
        if project_id is None:
            project_id = rec.get("project_id") or None
        if not project_id:
            return
        proj = _rnd.get_project(project_id)
        folder = (proj or {}).get("folder_path", "") if proj else ""
        if not folder:
            return
        lane = rec.get("lane", "") or ""
        # Prefer the docs THIS kill just persisted; fall back to the v8 join.
        doc_rels = list((docs_out or {}).get("persisted", []) or [])
        entry = _boneyard.build_session_entry(
            folder, project_id, lane, session_id,
            source=_boneyard.SOURCE_KILLED, record=rec,
            doc_rels=(doc_rels or None))
        # Only record a killed entry when the session actually produced material.
        if entry.get("doc_rels"):
            _boneyard.record_entry(folder, project_id, entry)
    except Exception:
        return


def capture_session_docs(session_id, project_id=None, record=None):
    """Persist a session's produced docs into the MAIN project (before any reap).

    Generalizes the v6 ``capture_plan_set`` capture-before-reap discipline to ALL
    trio docs: resolves the session's registry record (its lane + worktree_path),
    then delegates to :func:`effort_history.persist_session_docs`, which copies
    the produced documents into the main folder, records per-doc efforts so they
    are discoverable, and commits them scoped to the project repo.

    Best-effort and never raises — returns the ``persist_session_docs`` result, or
    a ``{"ok": False, "reason": ...}`` dict when the session/worktree/project
    cannot be resolved (so a missing record can't break the kill path).
    """
    try:
        rec = record if record is not None else _reg.get_session(session_id)
        if rec is None:
            return {"ok": False, "reason": "unknown-session", "persisted": []}
        if project_id is None:
            project_id = rec.get("project_id") or None
        if not project_id:
            return {"ok": False, "reason": "no-project", "persisted": []}
        worktree_path = rec.get("worktree_path", "")
        if not worktree_path:
            return {"ok": False, "reason": "no-worktree", "persisted": []}
        proj = _rnd.get_project(project_id)
        if proj is None:
            return {"ok": False, "reason": "unknown-project", "persisted": []}
        folder = proj.get("folder_path", "")
        if not folder:
            return {"ok": False, "reason": "no-folder", "persisted": []}
        lane = rec.get("lane", "") or ""
        return _eh.persist_session_docs(
            folder, project_id, lane, session_id, worktree_path)
    except Exception:
        return {"ok": False, "reason": "error", "persisted": []}


# ── Incremental autosave — periodically persist a RUNNING session's work ─────
#
# The durability gap (2026-07-07): a session's produced docs + transcript were
# only ever persisted to the MAIN project at a BOUNDARY event (kill / close /
# finish / advance / suspend / boot-recover). A long-running session — notably a
# bare ``general`` session (``effort_managed=False``, which boot-recovery skips)
# — that HUNG lost everything it had generated: reconcile and the zombie sweep
# flip it RUNNING→IDLE WITHOUT persisting, so the work survived only as orphaned
# worktree files ("found and manually saved later"). This heartbeat closes the
# window: every AUTOSAVE_INTERVAL seconds it snapshots each live session's
# transcript and copies its produced docs into MAIN (the byte-identical skip in
# :func:`effort_history.persist_session_docs` makes an unchanged session a true
# no-op), and refreshes a mechanical ``RESTART.md`` resume aid. Combined with the
# boot-reconcile persist (anchor_gui boot), a hang can never strand work older
# than one interval, and any session is warm-restartable from MAIN.

#: Env seam: disable the autosave heartbeat entirely (``0``/``false``/``off``).
#: ON by default in production; tests exercise :func:`autosave_running_sessions`
#: / :func:`autosave_session` DIRECTLY (synchronously) and leave the daemon off.
AUTOSAVE_ENABLED_ENV = "ANCHOR_SESSION_AUTOSAVE"
#: Env seam: the heartbeat interval in seconds (default 120 — John 2026-07-07).
AUTOSAVE_INTERVAL_ENV = "ANCHOR_SESSION_AUTOSAVE_INTERVAL"
DEFAULT_AUTOSAVE_INTERVAL = 120.0

#: The restart/resume aid written into a session's worktree lane dir. It rides
#: into MAIN with the rest of the docs (a lane-dir ``.md`` → classified as a
#: produced doc), so a later resume can find it.
RESTART_DOC_FILENAME = "RESTART.md"

#: Single-start guard for the daemon (a repeated boot never stacks a 2nd loop).
_AUTOSAVE_STARTED = False
_AUTOSAVE_GUARD = threading.Lock()


def _autosave_enabled() -> bool:
    return (os.environ.get(AUTOSAVE_ENABLED_ENV, "1").strip().lower()
            not in ("0", "false", "no", "off"))


def _autosave_interval() -> float:
    raw = (os.environ.get(AUTOSAVE_INTERVAL_ENV) or "").strip()
    if not raw:
        return DEFAULT_AUTOSAVE_INTERVAL
    try:
        v = float(raw)
        return v if v > 0 else DEFAULT_AUTOSAVE_INTERVAL
    except ValueError:
        return DEFAULT_AUTOSAVE_INTERVAL


def _write_restart_seed(record, persisted_rels=None):
    """Write a mechanical ``RESTART.md`` resume aid into the session's worktree.

    Pure string assembly from the registry record + the produced-doc list — NO
    model call. A deterministic path (``<store_lane>/RESTART.md``) so a re-write
    overwrites the same file (idempotent), and the lane dir means
    :func:`effort_history.persist_session_docs` classifies + copies it into MAIN
    with the other docs. Skips an identical re-write so autosave stays a true
    no-op when nothing changed. Returns the repo-relative POSIX path written, or
    ``None`` on any failure. Never raises."""
    try:
        if not isinstance(record, dict):
            return None
        worktree_path = (record.get("worktree_path") or "").strip()
        lane = (record.get("lane") or "").strip()
        if not worktree_path or not lane:
            return None
        wt = Path(worktree_path)
        if not wt.is_dir():
            return None
        store_lane = _eh._resolve_subdir(lane)
        sid = record.get("session_id") or ""
        short_sid = sid[:12] or "session"
        engine = record.get("backend") or record.get("engine") or "?"
        seed = (record.get("seed_text") or "").strip()
        seed_line = (seed.splitlines()[0][:200] if seed
                     else "(bare session — no seed)")
        docs = sorted(d for d in (persisted_rels or [])
                      if d and not d.endswith("/" + RESTART_DOC_FILENAME)
                      and not d == "%s/%s" % (store_lane, RESTART_DOC_FILENAME))
        doc_block = ("\n".join("- %s" % d for d in docs) if docs
                     else "- (no documents produced yet)")
        body = (
            "# Session restart — %s (%s)\n\n"
            "This session is autosaved: its produced documents and latest "
            "transcript are copied into the main project so it can be resumed "
            "even if the live terminal is lost.\n\n"
            "- **Session id:** %s\n"
            "- **Lane:** %s\n"
            "- **Engine:** %s\n"
            "- **Skill / seed:** %s\n\n"
            "## Produced documents\n%s\n\n"
            "## To resume\n"
            "Reopen this session's tile in the Anchor project window, or use "
            "\"Continue in a live session\" — the resume seed loads the "
            "documents above.\n"
            % (lane.title(), short_sid, sid, lane, engine, seed_line, doc_block))
        rel = "%s/%s" % (store_lane, RESTART_DOC_FILENAME)
        dest = wt / store_lane / RESTART_DOC_FILENAME
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            if dest.is_file() and dest.read_text(encoding="utf-8") == body:
                return rel
        except OSError:
            pass
        dest.write_text(body, encoding="utf-8")
        return rel
    except Exception:
        return None


def autosave_session(session_id, record=None):
    """Persist ONE running session's work into MAIN (transcript + docs + RESTART).

    Best-effort, idempotent, never raises. A no-op for a session that is not
    RUNNING. Returns ``{"session_id", "persisted": [...], "ok": bool, "reason"?}``.
    """
    out = {"session_id": session_id, "persisted": [], "ok": False}
    try:
        rec = record if record is not None else _reg.get_session(session_id)
        if not isinstance(rec, dict):
            out["reason"] = "unknown-session"
            return out
        if rec.get("status") != _reg.STATUS_RUNNING:
            out["reason"] = "not-running"
            return out
        worktree_path = (rec.get("worktree_path") or "").strip()
        # 1. Snapshot the live PTY transcript into a worktree doc (best-effort; a
        #    session with no live PTY simply yields nothing to snapshot).
        _snapshot_transcript_doc(rec, session_id)
        # 2. Write the mechanical restart aid, listing the docs produced so far.
        try:
            doc_rels = (_eh._produced_doc_rels(worktree_path)
                        if worktree_path else [])
        except Exception:
            doc_rels = []
        _write_restart_seed(rec, persisted_rels=doc_rels)
        # 3. Copy the produced docs (transcript + RESTART.md + any docs) to MAIN.
        res = capture_session_docs(session_id, record=rec)
        if isinstance(res, dict):
            out["persisted"] = res.get("persisted", [])
            out["ok"] = bool(res.get("ok"))
        # 4. Honest Telemetry W4: piggyback a NON-finalizing usage snapshot on the
        #    existing 120s autosave heartbeat (no second timer) — ingest the live
        #    sidecar's usage into the durable ledger so a weeks-later reconcile of
        #    a crashed session reads Anchor's own accumulated snapshot, not the
        #    prunable home store. Does NOT flip the cost_final latch (the end-path
        #    finalize stays the sole cost-record writer). Best-effort.
        if _usage is not None:
            try:
                _usage.snapshot_session_usage(session_id, record=rec)
            except Exception:
                pass
        # 5. telemetry-resume W6 (diag-B2 S3 attach-race fix): the pending-paste
        #    flush is normally only evaluated on read_since/attach — an UNMOUNTED
        #    follow-on session (no open browser stream) would never check, leaving
        #    its paste pending forever. Evaluate it here on the heartbeat too, so
        #    the greet-gate (and its bounded fallback) still delivers the paste
        #    UNSENT even with no viewer. Best-effort; never auto-submits.
        try:
            _flush_pending_paste(session_id)
        except Exception:
            pass
        return out
    except Exception:
        out["reason"] = "error"
        return out


def autosave_running_sessions():
    """Autosave every RUNNING managed session (the heartbeat body).

    Directly callable + synchronous (the unit tests drive it without the daemon).
    Best-effort per session; never raises. Returns the number of sessions swept."""
    n = 0
    try:
        running = _reg.list_sessions(status=_reg.STATUS_RUNNING)
    except Exception:
        running = []
    for rec in running:
        try:
            sid = rec.get("session_id") if isinstance(rec, dict) else None
            if not sid:
                continue
            autosave_session(sid, record=rec)
            n += 1
        except Exception:
            continue
    return n


def start_autosave_daemon():
    """Launch the autosave heartbeat as ONE daemon thread (single-start guarded).

    ON by default; a hard NO-OP when ``ANCHOR_SESSION_AUTOSAVE`` is disabled.
    Owned by the main service process (never a disposable subagent). It spawns NO
    subprocess — only in-process file copies + git through the existing seam — so
    it can never pop a console window. Returns ``True`` if a loop was started,
    ``False`` if disabled / already running."""
    global _AUTOSAVE_STARTED
    if not _autosave_enabled():
        return False
    with _AUTOSAVE_GUARD:
        if _AUTOSAVE_STARTED:
            return False
        _AUTOSAVE_STARTED = True

    interval = _autosave_interval()

    def _loop():
        import time as _t
        while True:
            try:
                _t.sleep(interval)
            except Exception:
                return
            if not _autosave_enabled():
                continue
            try:
                autosave_running_sessions()
            except Exception:
                pass

    try:
        threading.Thread(target=_loop, daemon=True,
                         name="anchor-autosave").start()
        return True
    except Exception:
        with _AUTOSAVE_GUARD:
            _AUTOSAVE_STARTED = False
        return False


# ── Graceful CLOSE — park a session, resumable WARM (crucible-improve W6) ─────

def close_session(session_id, project_id=None, actor=None):
    """GRACEFUL CLOSE (the panel "×") — park a session so it resumes WARM (W6).

    DISTINCT from both :func:`kill` and :func:`delete_session`. The panel "×" is a
    NON-destructive close: it STOPS the live PTY but PRESERVES the worktree and
    KEEPS the registry record — re-statused ``STATUS_IDLE`` (parked / grey /
    reopenable) when it was RUNNING — so the session can be resumed later (W3/W4).
    No worktree removal, no record deletion, no auto-advance (a park is NOT a
    finish).

    W6 amendment — a bare "preserve the worktree" close would reopen COLD: the
    boot orphan-reaper deletes a no-live-PTY worktree on restart, and
    :func:`anchor_gui._build_continue_seed` reads cache / main-persisted docs ONLY
    (never the worktree). So before returning, close MUST PERSIST the session's
    produced docs into the MAIN project (:func:`capture_session_docs`, exactly like
    :func:`kill`) so they survive the boot reaper and feed the resume seed. The
    ``/api/rnd/term_close`` endpoint ALSO schedules the same best-effort background
    session-summary hook ``finish``/``kill`` use, so the resume opens WARM; and
    :func:`worktrees.reap_orphans` is taught to KEEP a ``STATUS_IDLE`` worktree.

    Tolerant + best-effort: an already-dead / never-live PTY, a missing record, or
    a persist failure never blocks the park. Returns ``{"ok": True, "session_id",
    "pty_killed", "status", "docs"}`` — or ``{"ok": False, "reason":
    "unknown-session"}`` when the id has no registry record (the panel close then
    just tears down its DOM).
    """
    record = _reg.get_session(session_id)
    if record is None:
        return {"ok": False, "session_id": session_id,
                "reason": "unknown-session"}
    if project_id is None:
        project_id = record.get("project_id") or None

    # Resume-warm fix (2026-07-08): a bare `general` (or any doc-less) session
    # produces no trio docs, so the git-diff `capture_session_docs` below finds
    # nothing and the resume seed / summarizer collapse to empty ("No grounded
    # claims…"). Snapshot the LIVE PTY transcript into a durable worktree doc
    # BEFORE the kill (a killed PTY can't be read) — mirroring `autosave_session`
    # — so the actual session log survives, gets persisted to MAIN by
    # `capture_session_docs`, becomes a groundable member doc for the summarizer,
    # and warms the reopen seed. Best-effort; never blocks the park.
    try:
        _snapshot_transcript_doc(record, session_id)
        worktree_path = (record.get("worktree_path") or "").strip()
        try:
            _doc_rels = (_eh._produced_doc_rels(worktree_path)
                         if worktree_path else [])
        except Exception:
            _doc_rels = []
        _write_restart_seed(record, persisted_rels=_doc_rels)
    except Exception:
        pass

    # Stop the live PTY (tolerant of an already-dead / never-live session).
    pty_killed = False
    try:
        _pty.kill(session_id)
        pty_killed = True
    except _pty.UnknownSession:
        pty_killed = False

    # W6 amendment: persist the produced docs into the MAIN project (like kill)
    # BEFORE anything could reap the worktree (the boot reaper / a later restart),
    # so they survive and the W3 resume seed (cache / main-only) can read them.
    # Best-effort — never blocks the park.
    docs_out = capture_session_docs(session_id, project_id=project_id,
                                    record=record)

    # Honest Telemetry W4: eager finalize on the CLOSE/PARK end path. A parked
    # session's worktree may later be evicted; the finalized cost record snapshots
    # its usage into ``.anchor/`` so the session stays MEASURED across eviction
    # (idempotent CAS; never blocks the park).
    _finalize_usage_safe(session_id, project_id=project_id, record=record)

    # KEEP the worktree (NO remove_worktree) and KEEP the registry record. Park a
    # still-RUNNING session at STATUS_IDLE (grey, reopenable); leave an already
    # terminal/idle record as-is — a historical panel close must never "un-finish"
    # a DONE/FAILED session.
    status = record.get("status")
    if status == _reg.STATUS_RUNNING:
        # W12 (C3, D1): journal-first — emit ``session-closed`` BEFORE the legacy
        # park (RUNNING→IDLE) write (best-effort, off-switch-gated).
        try:
            _journal.dual_write(
                project_id, _journal.EV_SESSION_CLOSED,
                lambda: _reg.update_session(
                    session_id, status=_reg.STATUS_IDLE),
                correlation_id=(record.get("chain_id") or session_id),
                actor=actor,
                causation_id=(record.get("parent_session_id") or None),
                payload={"session_id": session_id,
                         "lane": record.get("lane", "")},
            )
            status = _reg.STATUS_IDLE
        except KeyError:
            pass

    return {
        "ok": True,
        "session_id": session_id,
        "pty_killed": pty_killed,
        "status": status,
        "docs": docs_out,
    }


# ── True session delete (v9 Wave 1) ──────────────────────────────────────────
#
# DELETE is DISTINCT from KILL (v8). KILL ends a *running* session: it reaps the
# PTY, persists the produced docs into the main folder, removes the worktree, and
# marks the registry record DONE — the record (and its board tile) PERSIST so the
# work is resumable. DELETE *removes the session from Anchor entirely*: the
# registry record is hard-deleted (so it never re-surfaces on a reload), and the
# session's effort pointer-records / index entries / cached summary are removed.
#
# Option A (LOCKED): the produced DOCUMENTS are KEPT on disk — only Anchor's
# pointer-records + cache (which merely reference them) are dropped. So the
# committed plan/research/build files stay in the project folder/git.

def delete_session(session_id, project_id=None):
    """Permanently delete a managed session from Anchor (v9 Wave 1).

    Distinct from :func:`kill`: this REMOVES the registry record (so the tile is
    gone and STAYS gone across a reload — ``term_sessions``/the board read the
    registry, which no longer holds it) AND removes the session's lane effort
    pointer-records / index entries / cached summary
    (``effort_history.delete_session_efforts``). The produced DOCUMENTS are KEPT
    on disk (Option A) — only the Anchor pointer-records + cache are dropped.

    If the session is still LIVE it is :func:`kill`-ed first (reap PTY + persist
    docs + remove worktree), so a running session can be deleted safely.

    Best-effort, IDEMPOTENT (a second delete is a clean no-op), and never raises.
    Returns ``{"ok": True, "deleted": bool, "session_id", "killed": bool,
    "efforts": {...}}`` where ``deleted`` is whether a registry record was
    removed (False if the id was already unknown).
    """
    rec = _reg.get_session(session_id)
    if project_id is None and rec:
        project_id = rec.get("project_id") or None
    lane = (rec.get("lane") if rec else "") or ""

    killed = False
    # If the session is still live (a running PTY / RUNNING status), kill it first
    # so the PTY + worktree are reaped and its docs are persisted before we drop
    # the record. Tolerate any failure — delete must still proceed. We SUPPRESS the
    # kill's "killed" Boneyard capture (``_record_boneyard=False``): a delete of a
    # live session must yield exactly ONE Boneyard entry — the canonical "deleted"
    # entry recorded below — not a "killed" + "deleted" pair. Doc PERSISTENCE still
    # runs in kill, so the "deleted" entry's doc_rels are populated.
    try:
        if rec is not None and (
                session_id in set(_pty.live_sessions())
                or rec.get("status") == _reg.STATUS_RUNNING):
            kill(session_id, project_id=project_id, _record_boneyard=False)
            killed = True
    except Exception:
        killed = False

    # zombie-hunter safe-to-arm, Wave 6: term_delete tears down the jobs too. A
    # LIVE delete already reaped them inside kill() above; a NON-live delete (the
    # session was already terminal) still walks the reference-counted teardown so
    # any lingering owned job is cancelled/handed-off before the record — and its
    # claim set — is dropped below. Idempotent + best-effort (a second teardown
    # over an already-reaped set is a clean no-op).
    if not killed:
        try:
            _teardown_owned_jobs(session_id, record=rec, project_id=project_id)
        except Exception:
            pass

    # Hard-delete the registry record (the durability of "stays gone": the board
    # + term_sessions read the registry, so a removed record never re-surfaces).
    try:
        deleted = bool(_reg.remove_session(session_id))
    except Exception:
        deleted = False

    # Remove the lane effort pointer-records / index entries / cached summary —
    # but KEEP the produced documents on disk (Option A). Resolve the folder.
    efforts_out = {"ok": False, "reason": "unresolved"}
    try:
        if project_id and lane:
            proj = _rnd.get_project(project_id)
            folder = (proj or {}).get("folder_path", "") if proj else ""
            if folder:
                # v10 Wave 6 (D10) — CAPTURE the Boneyard entry BEFORE
                # delete_session_efforts drops the pointer-records: the entry is
                # built from efforts_for_session_id (the docs the session
                # produced) + the cached summary, which only exist WHILE the
                # pointer-records are still present. After this call the efforts
                # are gone — the Boneyard is the deleted session's ONLY remaining
                # home (the docs stay on disk, Option A). BEST-EFFORT.
                _capture_deleted_to_boneyard(folder, project_id, lane,
                                             session_id, rec)
                efforts_out = _eh.delete_session_efforts(
                    folder, project_id, lane, session_id)
    except Exception:
        efforts_out = {"ok": False, "reason": "error"}

    return {
        "ok": True,
        "deleted": deleted,
        "session_id": session_id,
        "killed": killed,
        "efforts": efforts_out,
    }


def _capture_deleted_to_boneyard(folder, project_id, lane, session_id, record):
    """Index a v9-DELETED session in the Boneyard (D3 source "deleted") — W6.

    MUST be called BEFORE ``effort_history.delete_session_efforts`` drops the
    pointer-records (D10): the entry's ``doc_rels`` are resolved from
    ``efforts_for_session_id`` (which only returns docs WHILE the pointer-records
    exist). Unlike a kill, the deleted session's tile + efforts are about to be
    gone, so the Boneyard is its ONLY remaining home — we record it even if the
    docs list is empty (the entry still preserves the session's identity/summary).
    BEST-EFFORT — swallows every error so it can never break the delete path.
    """
    if _boneyard is None:
        return
    try:
        entry = _boneyard.build_session_entry(
            folder, project_id, lane, session_id,
            source=_boneyard.SOURCE_DELETED, record=record)
        _boneyard.record_entry(folder, project_id, entry)
    except Exception:
        return


def cleanup_ghost_sessions(project_id):
    """Delete a project's empty GHOST sessions (v9 Wave 1).

    A *ghost* is a registry session record in a terminal/non-running state
    (DONE/FAILED/IDLE — never a live RUNNING one) that has NO effort pointer-
    records tied to it in its lane (it produced nothing Anchor recorded). These
    accumulate as phantom tiles. This sweeps them: for each candidate it confirms
    ``efforts_for_session_id`` is empty in its lane, then :func:`delete_session`-s
    it (record + any cache). RUNNING sessions and sessions WITH efforts are left
    untouched.

    Best-effort, never raises. Returns ``{"ok": True, "removed": [session_id...]}``.
    """
    removed = []
    try:
        proj = _rnd.get_project(project_id)
        folder = (proj or {}).get("folder_path", "") if proj else ""
        for rec in _reg.list_sessions(project_id=project_id):
            try:
                if rec.get("status") == _reg.STATUS_RUNNING:
                    continue  # never sweep a live session
                sid = rec.get("session_id")
                lane = (rec.get("lane") or "")
                has_efforts = False
                if folder and lane:
                    try:
                        has_efforts = bool(_eh.efforts_for_session_id(
                            folder, project_id, lane, sid))
                    except Exception:
                        has_efforts = False
                if has_efforts:
                    continue  # not a ghost — it produced recorded work
                delete_session(sid, project_id=project_id)
                removed.append(sid)
            except Exception:
                continue
    except Exception:
        pass
    return {"ok": True, "removed": removed}


# ── Auto advance planning → build (v6 Wave 6) ────────────────────────────────
#
# When a PLANNING session reaches a terminal/DONE state via a DELIBERATE
# hard-kill or a RECONCILE-DEAD transition (NOT a keep-alive close, NOT process
# self-exit), and a real MASTER+IMPL plan set is discoverable, the cockpit
# AUTOMATICALLY opens exactly ONE linked build session that executes on that plan.
#
# Trigger semantics are LOCKED (MASTER-PLAN Risks R1/R2):
#   - fires ONLY for a planning-lane session that is TERMINAL/DONE;
#   - exactly ONE build per planning session — IDEMPOTENT on
#     ``parent_session_id`` (a second reconcile/restart never duplicates);
#   - no plan set ⇒ no advance;
#   - the build worktree is PRIMED (HANDOFF.md → the plan docs) and the stage
#     edge is recorded, captured from the discovered plan set BEFORE the planning
#     worktree is reaped (callers pre-capture and pass ``plan_set`` to be safe).
#
# This lives here (not in ``session_registry``) so the registry stays free of a
# terminal_session/handoff import — no import cycle. ``handoff`` imports neither
# module, so importing it here is safe.

#: Planning lane aliases that qualify for the plan→build auto-advance (the trio
#: key ``plan`` and the on-disk dir name ``planning`` both map to a plan stage).
_PLANNING_LANES = frozenset(("plan", "planning"))


def _doc_paths_for_seed(doc_set):
    """Ordered, de-duplicated list of the REAL persisted doc paths in a set.

    Pulls the main-folder-relative POSIX paths a plan/research set carries —
    master + impl first (when present), then the rest of ``doc_rels`` — so the
    generated seed can name the ACTUAL documents the upstream session produced
    (which, after v8 Wave 2 persistence, physically exist in this checkout).
    """
    if not doc_set:
        return []
    primary = []
    for key in ("master_plan_rel", "impl_plan_rel", "report_rel"):
        v = (doc_set.get(key) or "").strip()
        if v and v not in primary:
            primary.append(v)
    ordered = list(primary)
    for r in (doc_set.get("doc_rels") or []):
        r = (r or "").strip()
        if r and r not in ordered:
            ordered.append(r)
    return ordered


def _build_seed_for_plan(plan_set):
    """A build seed listing the REAL plan-doc paths the build executes on.

    Generated from the persisted plan set (v8 Wave 2 — the docs now genuinely
    exist in the build checkout): names :data:`LANE_SKILL['build']` (Foreman),
    lists the actual ``planning/.../IMPLEMENTATION-PLAN.md`` + ``MASTER-PLAN.md``
    (and supporting doc) paths, and a short read-first instruction. ``prime_worktree``
    writes the same paths into HANDOFF.md, which is also referenced here.
    """
    skill = LANE_SKILL.get("build", "Foreman")
    title = (plan_set.get("title") or plan_set.get("plan_dir")
             or "the planning session's plan set")
    docs = _doc_paths_for_seed(plan_set)
    if docs:
        doc_lines = "\n".join("- " + d for d in docs)
        read_first = (
            "Read these documents first, then proceed to execute on them:\n"
            "%s" % doc_lines)
    else:
        read_first = ("The plan docs are referenced in HANDOFF.md in this "
                      "worktree.")
    return (
        "Load the %s skill. You are executing on the plan produced by the "
        "upstream planning session: %s.\n%s\nHANDOFF.md in this worktree also "
        "lists these plan documents." % (skill, title, read_first))


def _build_seed_for_research(research_set):
    """A planning seed listing the REAL research-doc paths the plan builds on.

    The research→plan analog of :func:`_build_seed_for_plan`: names
    :data:`LANE_SKILL['plan']` (Crucible), lists the actual persisted research
    report path(s), and a short read-first instruction. ``research_set`` is a
    plan-set-shaped dict (``doc_rels`` / ``report_rel`` / ``master_plan_rel``)
    or ``None``; with no docs it degrades to a bare Crucible seed reference.
    """
    skill = LANE_SKILL.get("plan", "Crucible")
    docs = _doc_paths_for_seed(research_set)
    if docs:
        doc_lines = "\n".join("- " + d for d in docs)
        read_first = (
            "Read these research documents first, then plan from them:\n%s"
            % doc_lines)
    else:
        read_first = ("The upstream research report is in this worktree "
                      "checkout.")
    return (
        "Load the %s skill. Plan from the upstream research session's findings."
        "\n%s" % (skill, read_first))


def auto_advance_planning_to_build(project_id, planning_session_id,
                                   planning_worktree_path=None, plan_set=None):
    """Auto-open one linked, primed build session from a DONE planning session.

    Fires only when ``planning_session_id`` is a planning-lane session in a
    terminal/DONE status (the deliberate hard-kill or reconcile-dead transition).
    Returns ``None`` (a clean no-op) in every gated-out case:

      - the session is unknown, not a planning lane, or not terminal/DONE;
      - a build session with ``parent_session_id == planning_session_id`` already
        exists (**idempotent** — survives reconcile/restart, never duplicates);
      - no MASTER+IMPL plan set is discoverable (``no plan ⇒ no advance``).

    Otherwise it:
      1. discovers the plan set (or uses the pre-captured ``plan_set`` passed by a
         caller that captured it BEFORE the planning worktree was reaped);
      2. starts a NEW linked build session (``start_session(lane='build',
         parent_session_id=planning_session_id, paste_prompt=<plan prompt>)``) — it
         inherits the planning session's ``chain_id``; the build prompt is delivered
         as a v10 PENDING PASTE (held unsent until the user looks), never
         auto-submitted, on this unattended path too;
      3. primes the build worktree with BOTH artifacts via
         :func:`handoff.prime_worktree` (HANDOFF.md → the plan docs) AND
         :func:`handoff.write_next_prompt` (NEXT-PROMPT.md → the reviewable prompt);
      4. records the generic stage edge ``plan->build`` via
         :func:`handoff.record_stage_link`.

    Returns the new build registry record on success. Never raises — any failure
    (no project, discovery error, start failure) returns ``None`` so it can be
    called best-effort from the kill / reconcile transition without breaking it.
    """
    try:
        record = _reg.get_session(planning_session_id)
        if record is None:
            return None
        # v12 Wave 7 — RETIREMENT MAP (Shark C1/C3). A v12 EFFORT
        # (effort_managed==True) advances IN-SESSION via advance_stage /
        # detect_stage_progress (no new session); the legacy auto-advance must
        # NEVER mint a second build for it. Gate keys on ``effort_managed`` ONLY
        # (NEVER on kind/current_stage — legacy records carry those too, and
        # gating on them would break the v6/v8/v10/v11 healthcheck walks). A
        # legacy (effort_managed==False) record falls through unchanged.
        if record.get("effort_managed"):
            return None
        lane = record.get("lane", "")
        if lane not in _PLANNING_LANES:
            return None
        # Only a TERMINAL/DONE planning session advances (the hard-kill /
        # reconcile-dead transition the cockpit owns — never a keep-alive close,
        # never a live/idle session).
        if record.get("status") != _reg.STATUS_DONE:
            return None

        proj = _rnd.get_project(project_id)
        if proj is None:
            return None
        folder = proj.get("folder_path", "")
        if not folder:
            return None

        # IDEMPOTENCY: one build per planning session. If a build already links to
        # this planning session as its parent, do nothing (a second reconcile /
        # restart re-running this must NOT create a duplicate).
        for s in _reg.list_sessions(project_id=project_id):
            if (s.get("lane") == "build"
                    and s.get("parent_session_id") == planning_session_id):
                return None

        # v11 Wave 3 — route the plan→build prompt + persist + handoff materials
        # through the SHARED keystone (:func:`prepare_stage_handoff`) so this path
        # is consistent with research→plan and equally verified, AND so the plan-set
        # DISCOVERY below sees the planning session's just-persisted docs. The
        # keystone is called BEFORE discovery because the persist is what makes the
        # plan set discoverable on the paths where the docs are NOT already on main
        # (notably the reconcile-dead transition, which marks the session DONE
        # WITHOUT running kill()'s persist; the hard-kill path already persisted in
        # kill() so this is an idempotent, content-addressed no-op re-capture). The
        # keystone:
        #   - PERSISTS the planning session's produced docs (best-effort, idempotent;
        #     no-ops safely if the worktree is already reaped — then the docs are
        #     already on main from kill());
        #   - BUILDS the build prompt via handoff.build_next_stage_prompt('build'),
        #     which discovers the plan set and reuses ``_build_seed_for_plan`` (the
        #     real plan-doc paths) AND applies ``clean_paste_opener`` — so the
        #     redundant "Load the Foreman skill." opener is already stripped;
        #   - RESOLVES doc_rels + skill (Foreman) + the planning session's cached
        #     summary for a shared HANDOFF.md.
        hk = prepare_stage_handoff(project_id, planning_session_id, "build")

        # Discover the plan set the build executes on. Prefer a pre-captured one
        # (the caller captured it BEFORE reaping the planning worktree); else
        # discover now — AFTER the keystone persisted the planning docs into main,
        # so they are discoverable on every path. ``prime_worktree`` below uses the
        # plan set for the richer plan-set-specific HANDOFF.md.
        if not plan_set:
            try:
                plan_set = _handoff.discover_recent_plan_set(
                    folder, project_id, source_session_id=planning_session_id)
            except Exception:
                plan_set = None
        if not plan_set:
            return None  # no plan ⇒ no advance
        # The task prompt is delivered as a PENDING PASTE (held in the build PTY
        # input UNSENT until the user presses Enter) — NOT folded into the
        # auto-submitted seed. The phase-1 load+greet seed still fires (Foreman
        # auto-loads + greets); the build prompt sits pending. This holds for the
        # UNATTENDED reconcile-dead path too: the build greets and waits — nothing
        # auto-submits — until the first attach flushes the paste unsent. Honest
        # fallback to the plan-set seed if the keystone prompt is empty (no docs).
        next_prompt = (hk.get("prompt") or "").strip()
        if not next_prompt:
            next_prompt = _handoff.clean_paste_opener(
                _build_seed_for_plan(plan_set))

        # Start the linked build session: skill auto-loads/greets (phase-1), the
        # build prompt is recorded as pending_paste (delivered unsent after greet).
        try:
            build_rec = start_session(
                project_id, "build",
                paste_prompt=next_prompt,
                parent_session_id=planning_session_id,
                label="auto · from plan",
                # W12: this is the machine advancing on John's behalf — the
                # ``session-started`` event is attributed ``auto-advance`` so
                # Butler story 2 can distinguish it from a user click.
                actor=_journal.auto_advance_actor())
        except TerminalSessionError:
            return None

        build_sid = build_rec.get("session_id", "")
        build_wt = build_rec.get("worktree_path", "")

        # Prime the (fresh, never-reaped) build worktree with BOTH artifacts BEFORE
        # anyone reaps anything: the structural HANDOFF.md (plan doc paths) and the
        # reviewable NEXT-PROMPT.md (the exact pending-paste prompt). Captured from
        # the discovered plan set. The plan→build HANDOFF.md is written by
        # ``prime_worktree`` (the RICHER plan-set-specific form: titled Master plan /
        # Implementation plan / supporting docs) — kept verbatim (no v10 regression);
        # the shared ``write_handoff_md`` generalizes ONLY the no-plan-set case
        # (research→plan), so it is NOT layered here where prime_worktree already
        # wrote the canonical plan-set HANDOFF.md (it would otherwise clobber it).
        # The shared keystone's persist (above) is what makes prime_worktree's
        # referenced plan docs genuinely exist in this checkout.
        if build_wt:
            try:
                _handoff.prime_worktree(build_wt, plan_set, project_id=project_id)
            except Exception:
                pass
            try:
                _handoff.write_next_prompt(build_wt, next_prompt)
            except Exception:
                pass
        # Record the generic plan→build stage edge (Wave 2; rescan-durable).
        try:
            _handoff.record_stage_link(
                folder, project_id, planning_session_id, build_sid,
                kind="plan->build")
        except Exception:
            pass
        # Also append the v3 handoff record (parallel list) for the inspection
        # surfaces — best-effort, never blocks the advance.
        try:
            _handoff.record_handoff(folder, project_id, build_sid, plan_set)
        except Exception:
            pass
        return build_rec
    except Exception:
        return None


def reconcile_and_advance(live_session_ids=None, worktree_exists=None,
                          mark_stale_status=_reg.STATUS_DONE):
    """Reconcile the registry, then auto-advance any newly-DONE planning session.

    The cockpit's reconcile-dead path (a managed session whose process is gone):
    re-status the stale sessions, then for each one that was a **planning** session
    just marked terminal/DONE, attempt :func:`auto_advance_planning_to_build`
    (idempotent on ``parent_session_id``, so re-running reconcile never
    duplicates; ``no plan ⇒ no advance``). Best-effort — an advance failure for
    one session never breaks the reconcile or the others.

    Reconcile here defaults ``mark_stale_status`` to ``STATUS_DONE`` (not the
    registry default ``STATUS_IDLE``) because a reconcile-dead transition for the
    cockpit IS the "this session finished" signal that gates the advance. Returns
    ``{"reconcile": <report>, "auto_builds": [<build_record>, ...]}``.
    """
    report = _reg.reconcile(
        live_session_ids=live_session_ids, worktree_exists=worktree_exists,
        mark_stale_status=mark_stale_status, apply=True)
    # Honest Telemetry W4: eager finalize on the RECONCILE-DEAD end path — every
    # session this reconcile just marked terminal gets its usage captured into the
    # durable ledger/cost record (idempotent CAS; best-effort). This runs for ALL
    # marked sessions (not just planning ones — every reconcile-dead session is a
    # real end path), so a crashed session that never hit kill/close is still
    # measured on the next reconcile.
    for sid in report.get("marked", []):
        _finalize_usage_safe(sid)

    auto_builds = []
    if mark_stale_status == _reg.STATUS_DONE:
        for sid in report.get("marked", []):
            rec = _reg.get_session(sid)
            if rec is None or rec.get("lane") not in _PLANNING_LANES:
                continue
            pid = rec.get("project_id") or None
            if not pid:
                continue
            try:
                build = auto_advance_planning_to_build(pid, sid)
            except Exception:
                build = None
            if build is not None:
                auto_builds.append(build)
    return {"reconcile": report, "auto_builds": auto_builds}


def capture_plan_set(project_id, planning_session_id):
    """Discover the planning session's plan set NOW (before any reap). or ``None``.

    Helper for the kill path: capture the plan set from the still-intact project
    state BEFORE :func:`kill` reaps the planning worktree, so the subsequent
    :func:`auto_advance_planning_to_build` primes from a known-good plan set even
    if discovery were ever to depend on the worktree. Never raises.
    """
    try:
        proj = _rnd.get_project(project_id)
        if proj is None:
            return None
        folder = proj.get("folder_path", "")
        if not folder:
            return None
        return _handoff.discover_recent_plan_set(
            folder, project_id, source_session_id=planning_session_id)
    except Exception:
        return None


def research_set_for_session(project_id, research_session_id):
    """Build a research-doc set (plan-set-shaped) for a research session, or None.

    The research→plan analog of :func:`capture_plan_set`: resolves the research
    session's persisted member docs (via ``sessions.list_sessions`` over the
    research lane) into a ``{report_rel, doc_rels, plan_dir, title}`` dict so
    :func:`_build_seed_for_research` can name the REAL report path(s). Prefers a
    member whose basename looks like a report; otherwise carries every member
    doc. Returns ``None`` when the session has no resolvable docs. Never raises.
    """
    try:
        proj = _rnd.get_project(project_id)
        if proj is None:
            return None
        folder = proj.get("folder_path", "")
        if not folder:
            return None
        from pathlib import PurePosixPath
        # Prefer the docs this exact session persisted (the effort pointer-records
        # carry the originating ``session_id`` in their ``extra``); fall back to
        # ALL research docs when no session-tagged ones resolve (e.g. brownfield).
        efforts = _eh.list_efforts(folder, project_id, "research")
        tagged = [e for e in efforts
                  if e.get("session_id") == research_session_id
                  and (e.get("artifact_path") or "").strip()]
        pool = tagged or [e for e in efforts
                          if (e.get("artifact_path") or "").strip()]
        doc_rels = []
        report_rel = ""
        for e in pool:
            rel = (e.get("artifact_path") or "").strip().replace("\\", "/")
            if not rel or rel in doc_rels:
                continue
            doc_rels.append(rel)
            name = PurePosixPath(rel).name.lower()
            if not report_rel and ("report" in name or rel.startswith("research/")):
                report_rel = rel
        if not doc_rels:
            return None
        if not report_rel:
            report_rel = doc_rels[0]
        plan_dir = PurePosixPath(report_rel).parent.as_posix()
        if plan_dir in (".", "/"):
            plan_dir = ""
        return {
            "research_session_id": research_session_id,
            "report_rel": report_rel,
            "doc_rels": doc_rels,
            "plan_dir": plan_dir,
            "title": "research findings",
        }
    except Exception:
        return None


def build_research_to_plan_seed(project_id, research_session_id):
    """The generated research→plan seed (Crucible + real report paths), or None.

    Wraps :func:`research_set_for_session` + :func:`_build_seed_for_research`.
    Returns ``None`` when no research docs resolve, so a caller can fall back to
    a summary-only seed. Never raises.
    """
    rset = research_set_for_session(project_id, research_session_id)
    if not rset:
        return None
    return _build_seed_for_research(rset)


# ── v11 Wave 1: the shared stage-handoff keystone ────────────────────────────
#
# THE BUG v11 fixes: ``advance_session`` (research→plan) never persisted the
# LIVE source research session's produced docs. Persistence
# (``effort_history.persist_session_docs`` via :func:`capture_session_docs`) ran
# ONLY in :func:`kill` and in ``finish_to_build`` (plan→build). So advancing a
# still-LIVE research session left its reports in the worktree, unpersisted →
# :func:`research_set_for_session` (reads only session-tagged persisted efforts)
# returned None → ``handoff.build_next_stage_prompt`` fell to the bare fallback
# with no doc paths, and no HANDOFF.md was written.
#
# ``prepare_stage_handoff`` is the ONE shared helper that fixes this at the root:
# it PERSISTS the source stage's produced docs FIRST (best-effort, idempotent,
# does NOT reap the worktree — works whether the source is live or done), THEN
# builds the real handoff prompt (which now finds the just-persisted,
# session-tagged docs), resolves the handoff materials (doc_rels + skill +
# upstream summary), and kicks off a non-blocking background source-stage summary.
# Wave 2/3 wire the advance/finish paths through it; this wave is backend-only.

def _summary_text_from_cached(cached):
    """A short plain-text digest from a cached structured summary, or ``""``.

    Prefers the cached ``markdown`` (rendered summary body); falls back to the
    joined grounded ``claims``; honest ``""`` when nothing is cached/usable.
    Never raises.
    """
    if not isinstance(cached, dict):
        return ""
    try:
        md = (cached.get("markdown") or "").strip()
        if md:
            return md
        claims = cached.get("claims") or []
        joined = "\n".join(
            str(c.get("text") if isinstance(c, dict) else c).strip()
            for c in claims
            if (c.get("text") if isinstance(c, dict) else c))
        return joined.strip()
    except Exception:
        return ""


def _trigger_background_source_summary(folder, project_id, lane, session_id):
    """Best-effort, NON-BLOCKING: spin a daemon thread to summarize the source
    session so the upstream digest is available, without blocking the advance.

    Mirrors the ``anchor_gui`` summarize-on-finish mechanism (daemon thread +
    idempotent cache skip) but lives here so the keystone never imports
    ``anchor_gui`` (which would be a module cycle: ``anchor_gui`` imports
    ``terminal_session``). Skips when a cache already exists; a failed generation
    never poisons the cache (the summarizer surfaces ``error`` without writing).
    Any failure — including a missing summarizer/runner — is swallowed; the
    digest is a nice-to-have, never a blocker.

    GATED on the SAME proactive-summary signal as ``anchor_gui`` (the
    ``ANCHOR_PROACTIVE_SUMMARY`` env flag) — read directly here so we never import
    ``anchor_gui`` (the cycle). When proactive summary is DISABLED (the default in
    every unit-test / healthcheck context), this is a hard NO-OP: no daemon thread
    is spawned, so a stubbed context NEVER spawns a live ``claude`` for the digest.
    The digest's absence does NOT change ``prepare_stage_handoff`` correctness —
    that function still persists docs + builds the real prompt regardless.
    """
    if not (folder and project_id and lane and session_id):
        return
    # No-op unless proactive generation is enabled (same gate anchor_gui uses;
    # read the env flag directly to avoid the anchor_gui import cycle). Tests and
    # the 5 AM healthcheck leave this OFF, so the background summary never runs and
    # no live claude is ever spawned from a stubbed context.
    if (os.environ.get("ANCHOR_PROACTIVE_SUMMARY", "").strip().lower()
            not in ("1", "true", "yes", "on")):
        return

    # Dedup at the root (v11.1 FIX): when the SOURCE session is already TERMINAL
    # (DONE / FAILED — i.e. it's being/was finished, e.g. a hard-killed planning
    # session that auto-advances to build), its summary is owned by the canonical
    # summarize-on-finish hook (``anchor_gui._trigger_session_summary_on_finish``).
    # The keystone background summary must NOT double up on it (two model calls
    # for the same session + racy idempotency). The keystone summary's value is for
    # a LIVE source being advanced from (the normal research→plan advance + the
    # v11.1 conversation-transcript case, where the research source stays RUNNING) —
    # there it remains the only trigger and fires as before. Best-effort: a status
    # read failure falls through to the prior behavior (fire the summary).
    try:
        _src_rec = _reg.get_session(session_id)
        if isinstance(_src_rec, dict):
            _src_status = (_src_rec.get("status") or "").strip().lower()
            if _src_status in (_reg.STATUS_DONE, _reg.STATUS_FAILED):
                return
    except Exception:
        pass

    def _run():
        try:
            import summarizer as _sm  # lazy: no cycle, optional at import time
            import effort_history as _eh_local
            # No os.environ mutation: the gate above means this only runs in
            # PRODUCTION (proactive enabled), where ANCHOR_RUNNER_CMD is already
            # the real configured value in the ambient process env. The summarizer
            # resolves the runner from that env, so the daemon thread relies on it
            # as-is — never writing process-global env from a daemon thread.
            store_lane = _eh_local._resolve_subdir(lane)
            # Idempotent: a session that already has a cache is left alone.
            try:
                if _sm.load_cached(folder, project_id, store_lane,
                                   session_id) is not None:
                    return
            except Exception:
                pass
            # Tie the summary to the docs the session PRODUCED (the keystone just
            # persisted them tagged with this session_id).
            try:
                efforts = _eh_local.efforts_for_session_id(
                    folder, project_id, store_lane, session_id)
            except Exception:
                efforts = []
            # Same key contract as above (2026-07-26).
            session = {"session_id": session_id, "lane": lane,
                       "member_files": efforts, "efforts": efforts}
            _sm.summarize_session(folder, project_id, store_lane, session)
        except Exception:
            pass

    try:
        import threading
        threading.Thread(target=_run, daemon=True).start()
    except Exception:
        pass


# v11.1 Wave 1 (D3/D4): snapshot a CONVERSATION-only research session.
#
# THE GAP v11.1 fixes: a research (or plan) session whose work lived only as a
# terminal CONVERSATION (the model answered in the PTY, wrote NO file) produces no
# document-classified doc → the handoff's ``doc_rels`` is empty → grass hard-
# refuses and the non-grass advance opens with a misleading prompt. The
# conversation is lost — only files survived.
#
# When the initial ``capture_session_docs`` persist yields ZERO docs (D4 — only
# the gap case), the keystone SYNCHRONOUSLY snapshots the source session's PTY
# transcript into ``<lane>/<short-sid>-transcript.md`` (an ``_is_document_rel``-
# valid ``.md`` under the lane dir), cleaned of the seed/greet boilerplate + ANSI
# control sequences and capped to a sane tail. Re-running ``capture_session_docs``
# then persists + session-tags it, so ``research_set_for_session`` finds it and
# the REAL doc-referencing prompt engages, and the transcript rides into the next
# worktree (off main HEAD). Best-effort + idempotent (deterministic filename,
# content-addressed persist); a snapshot failure NEVER breaks the advance.

#: Strip ANSI / control escape sequences (CSI / OSC / single-char escapes).
#:
#: A REAL ``claude`` ConPTY stream is a TUI: SGR colors, CSI cursor moves +
#: erase-line/screen, OSC title sequences, plus DEC private-mode toggles
#: (``\x1b[?25l`` etc.). The pre-v11.1 regex only covered the common CSI/OSC
#: forms; this one broadens to ALL CSI (any params/intermediates/final), both OSC
#: terminators (BEL ``\x07`` and ST ``\x1b\\``), the standalone ``\x1b(`` charset
#: selects, and stray control bytes (KEEP ``\t`` ``\n`` ``\r`` — ``\r`` is needed
#: for the in-place redraw collapse below, the others are real layout).
_ANSI_ESCAPE_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"        # CSI  \x1b[ ... final byte (incl. ?, =, >)
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC  \x1b] ... BEL / ST
    r"|\x1b[PX^_].*?(?:\x07|\x1b\\)"  # DCS/PM/APC/SOS strings ... ST/BEL
    r"|\x1b[()][0-9A-Za-z]"           # charset designation \x1b( B  etc.
    r"|\x1b[@-Z\\-_]"                 # other two-char escapes (RIS, IND, NEL…)
    r"|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]"  # stray control chars (keep \t \n \r)
)

#: The box-drawing input chrome ``claude`` draws around the prompt line
#: (``╭───╮`` ``│ > … │`` ``╰───╯``) plus the bottom status bar. A line that is
#: DOMINATED by box-drawing glyphs is interface chrome, not dialogue.
_BOX_DRAW_CHARS = "─━│┃┄┅┆┇┈┉┊┋┌┍┎┏┐┑┒┓└┕┖┗┘┙┚┛├┝┞┟┠┡┢┣┤┥┦┧┨┩┪┫┬┭┮┯┰┱┲┳┴┵┶┷┸┹┺┻┼┽┾┿╀╁╂╃╄╅╆╇╈╉╊╋╌╍╎╏═║╒╓╔╕╖╗╘╙╚╛╜╝╞╟╠╡╢╣╤╥╦╧╨╩╪╫╬╭╮╯╰"
_BOX_DRAW_SET = set(_BOX_DRAW_CHARS)

#: Spinner / status glyphs ``claude`` redraws on the working line (braille dots
#: + a few common spinner frames). A line that is only spinner chrome (a spinner
#: glyph + "esc to interrupt"-style text + tokens/elapsed) is transient status.
_SPINNER_CHARS = "⠀⠁⠂⠃⠄⠅⠆⠇⠈⠉⠊⠋⠌⠍⠎⠏⠐⠑⠒⠓⠔⠕⠖⠗⠘⠙⠚⠛⠜⠝⠞⠟⠠⠡⠢⠣⠤⠥⠦⠧⠨⠩⠪⠫⠬⠭⠮⠯⠰⠱⠲⠳⠴⠵⠶⠷⠸⠹⠺⠻⠼⠽⠾⠿⣀⣄⣆⣇⣦⣧⣷⣿◐◓◑◒◴◵◶◷⣾⣽⣻⢿⡿⣟⣯⣷✶✻✽✢·∗"
_SPINNER_SET = set(_SPINNER_CHARS)
#: Status-line phrases ``claude`` shows on the spinner / working line.
_STATUS_PHRASE_RE = re.compile(
    r"esc to interrupt|ctrl\+|tokens?\b|press up|\bthinking\b|\besc\b",
    re.IGNORECASE,
)

#: Cap the snapshot — keep a HEAD (the research framing/question) AND a TAIL (the
#: latest findings); the middle is what gets dropped when oversized.
_TRANSCRIPT_MAX_CHARS = 32768   # ~32 KB total budget
_TRANSCRIPT_HEAD_CHARS = 12288  # ~12 KB of the opening (the framing survives)
_TRANSCRIPT_TAIL_CHARS = 20480  # ~20 KB of the latest discussion


def _collapse_cr_redraws(text):
    """Collapse carriage-return in-place redraws to each line's FINAL frame.

    A real terminal stream redraws the status/spinner line hundreds of times by
    emitting ``...\\r...\\r...`` with NO newline — each ``\\r`` returns the cursor
    to column 0 so subsequent chars OVERWRITE the line in place. Naively
    ``text.replace("\\r", "\\n")`` would explode every redraw frame into its own
    line (the pre-fix bug). Instead, process line-by-line: within a logical line
    (split on ``\\n``), apply ``\\r`` as an in-place cursor reset and emit only the
    LAST rendered state. ``\\r\\n`` is normalized first so a real CRLF stays one
    line break. Stdlib only.
    """
    text = text.replace("\r\n", "\n")
    out_lines = []
    for logical in text.split("\n"):
        if "\r" not in logical:
            out_lines.append(logical)
            continue
        # Render the segments separated by \r as overwrites onto one line buffer.
        rendered = ""
        for seg in logical.split("\r"):
            if len(seg) >= len(rendered):
                rendered = seg
            else:
                # Shorter segment overwrites the prefix; the tail of the prior
                # frame remains (true terminal column semantics, no clear-line).
                rendered = seg + rendered[len(seg):]
        out_lines.append(rendered)
    return "\n".join(out_lines)


def _is_chrome_line(line):
    """True when ``line`` is terminal interface chrome (box / spinner / status).

    Conservative — only flags a line that is DOMINATED by box-drawing glyphs, or
    is a spinner/status frame (a spinner glyph and/or a known status phrase with
    little else). Real prose (even prose that mentions "esc") is kept because it
    has substantial non-chrome content.
    """
    s = line.strip()
    if not s:
        return False
    # Box-drawing chrome: the line is mostly box glyphs (the prompt frame).
    boxy = sum(1 for ch in s if ch in _BOX_DRAW_SET)
    nonspace = sum(1 for ch in s if not ch.isspace())
    if nonspace and boxy >= max(2, int(nonspace * 0.5)):
        return True
    # Spinner/status frame: starts with (or is mostly) a spinner glyph, and the
    # residual text is short status chrome.
    has_spinner = any(ch in _SPINNER_SET for ch in s)
    residual = "".join(ch for ch in s if ch not in _SPINNER_SET).strip()
    if has_spinner and (not residual or len(residual) <= 60
                        or _STATUS_PHRASE_RE.search(residual)):
        return True
    # A pure status line with no real content (e.g. a redrawn token counter).
    if _STATUS_PHRASE_RE.search(s) and len(s) <= 40:
        return True
    # The model's own greet line ("✓ <Skill> loaded — what would you like to
    # do?") — boilerplate, not dialogue. Dropped whether or not the seed echo was
    # already stripped (it survives as a separate real-output line).
    low = s.lower()
    if GREET_MARKER.lower() in low and "loaded" in low and len(s) <= 80:
        return True
    return False


def _strip_seed_greet(text, seed_text=""):
    """Remove the load+greet preamble from CLEANED text, robust to rendering.

    The seed Anchor writes ("Load the <Skill> skill now … greet me EXACTLY once …
    ✓ <Skill> loaded — what would you like to do?") is ECHOED by the PTY. On the
    STUB / a narrow terminal it echoes the seed VERBATIM (byte-exact); on a real
    ConPTY it comes back RENDERED (line-wrapped at terminal width, glyphs), so a
    byte-exact ``startswith`` won't match.

    Resolution order (byte-exact FIRST so we never under-strip a known seed — e.g.
    a grass develop seed that carries the idea text AS PART OF the seed must be
    removed WHOLE, not cut at the greet marker mid-seed):

      1. **byte-exact** full-seed strip (``startswith`` / ``find``) — removes the
         entire recorded seed including any idea-text suffix;
      2. **whitespace-normalized** full-seed match — handles a rendered seed whose
         only difference is collapsed/wrapped whitespace; cut the same span;
      3. **marker-based** cut — when the seed isn't recoverable as a whole (heavily
         re-flowed render), cut everything up to and INCLUDING the greet marker
         (``what would you like to do?``), the boilerplate↔dialogue boundary, but
         ONLY when the "Load the … skill" boilerplate genuinely precedes it.

    If none matches (env-overridden / absent seed), leave the text untouched
    (never over-strip real dialogue). Operates on the CLEANED text (post ANSI
    strip) so control codes don't defeat the match.
    """
    if not text:
        return text
    seed = (seed_text or "").strip()
    # 1) byte-exact whole-seed strip (stub echo + the grass idea-suffix seed).
    if seed_text and text.startswith(seed_text):
        return text[len(seed_text):]
    if seed:
        idx = text.find(seed)
        if idx != -1:
            return text[:idx] + text[idx + len(seed):]
    # 2) whitespace-normalized whole-seed match (rendered/re-flowed seed). Map the
    # normalized match span back to a raw cut by walking raw chars while skipping
    # the collapsed whitespace, so the WHOLE seed (incl. idea suffix) is removed.
    if seed and len(seed) > 20:
        norm_seed = re.sub(r"\s+", " ", seed).strip()
        # Build a normalized view of text + an index map back to raw offsets.
        norm_chars = []
        norm_to_raw = []
        prev_ws = False
        for i, ch in enumerate(text):
            if ch.isspace():
                if prev_ws:
                    continue
                norm_chars.append(" ")
                norm_to_raw.append(i)
                prev_ws = True
            else:
                norm_chars.append(ch)
                norm_to_raw.append(i)
                prev_ws = False
        norm_text = "".join(norm_chars)
        nidx = norm_text.find(norm_seed)
        if nidx != -1:
            raw_start = norm_to_raw[nidx]
            end_n = nidx + len(norm_seed) - 1
            raw_end = norm_to_raw[end_n] if end_n < len(norm_to_raw) else len(text) - 1
            return text[:raw_start] + text[raw_end + 1:]
    # 3) marker-based cut (heavily re-flowed render; no whole-seed recovery).
    low = text.lower()
    greet = GREET_MARKER.lower()  # "what would you like to do?"
    gpos = low.rfind(greet)
    if gpos != -1 and re.search(r"load the .{0,40}? skill", low):
        load_pos = low.find("load the")
        if 0 <= load_pos < gpos:
            cut = gpos + len(greet)
            nl = text.find("\n", cut)
            return text[nl + 1:] if nl != -1 else text[cut:]
    return text


def _clean_transcript_text(raw, seed_text=""):
    """Clean a raw PTY buffer into honest transcript markdown text, or ``""``.

    Real-ConPTY-robust. The pipeline (stdlib ``re`` only):

      1. **Collapse ``\\r`` in-place redraws** to each line's FINAL frame
         (:func:`_collapse_cr_redraws`) — a real status/spinner line is rewritten
         hundreds of times via carriage-return with no newline; we keep only the
         last render instead of exploding every frame into a line (the pre-fix
         bug that buried the Q&A under stale redraw frames).
      2. **Strip ANSI/CSI/OSC/DCS** escape sequences + stray control bytes
         (:data:`_ANSI_ESCAPE_RE`).
      3. **Strip the load+greet preamble** robustly (:func:`_strip_seed_greet`) —
         marker-based so a line-wrapped rendered seed is still removed.
      4. **Drop interface chrome** lines (box-drawing input frame + spinner/status
         frames) — :func:`_is_chrome_line`, conservative.
      5. **Collapse consecutive DUPLICATE content lines** to one (a spinner that
         survived as repeated identical lines folds to a single line) and collapse
         runs of blank lines.
      6. **Cap** keeping a HEAD + TAIL slice (the research framing AND the latest
         findings survive; the middle is marked truncated on a line boundary).

    Returns ``""`` when nothing meaningful remains. Never raises.
    """
    try:
        text = raw or ""
        # 1. Carriage-return in-place redraw collapse (BEFORE ANSI strip so the
        # \r boundaries are intact; the ANSI regex keeps \r).
        text = _collapse_cr_redraws(text)
        # 2. Strip ANSI / control sequences (now keeps \t \n only; \r consumed).
        text = _ANSI_ESCAPE_RE.sub("", text)
        text = text.replace("\r", "\n")  # any residual lone CR → newline
        # 3. Strip the load+greet preamble (rendered-robust, on cleaned text).
        text = _strip_seed_greet(text, seed_text=seed_text)
        # 4 + 5. Drop chrome lines; collapse consecutive duplicate content lines.
        kept = []
        prev = None
        blank_run = 0
        for line in text.split("\n"):
            if _is_chrome_line(line):
                continue
            stripped = line.rstrip()
            if not stripped.strip():
                blank_run += 1
                if blank_run <= 1:
                    kept.append("")
                continue
            blank_run = 0
            if stripped == prev:
                continue  # collapse a repeated identical content line
            prev = stripped
            kept.append(stripped)
        text = "\n".join(kept)
        text = re.sub(r"\n[ \t]*\n([ \t]*\n)+", "\n\n", text)
        text = text.strip()
        if not text:
            return ""
        # 6. Cap keeping HEAD + TAIL (the framing + the latest discussion).
        if len(text) > _TRANSCRIPT_MAX_CHARS:
            head = text[:_TRANSCRIPT_HEAD_CHARS]
            # End the head on a line boundary.
            hnl = head.rfind("\n")
            if hnl > 0:
                head = head[:hnl]
            tail = text[-_TRANSCRIPT_TAIL_CHARS:]
            tnl = tail.find("\n")
            if 0 <= tnl < 200:
                tail = tail[tnl + 1:]
            text = (head.rstrip() + "\n\n[… middle truncated …]\n\n"
                    + tail.strip())
        return text
    except Exception:
        return ""


def _snapshot_transcript_doc(record, source_session_id):
    """Snapshot the source session's PTY transcript into a lane doc (D3/D4).

    Reads the source session's full cumulative PTY output (``read_since(sid, 0)``),
    cleans it (:func:`_clean_transcript_text`), and writes it to
    ``<source_worktree>/<source_lane>/<short-sid>-transcript.md`` — a deterministic
    filename (so a re-advance overwrites the same path, idempotent) that
    ``_is_document_rel`` classifies as a produced doc. Creates the lane dir if
    missing. Returns the repo-relative POSIX path written, or ``None`` when there
    is no live PTY / no meaningful transcript / any failure. Never raises.
    """
    try:
        if not isinstance(record, dict):
            return None
        worktree_path = (record.get("worktree_path") or "").strip()
        lane = (record.get("lane") or "").strip()
        if not worktree_path or not lane:
            return None
        wt = Path(worktree_path)
        if not wt.is_dir():
            return None
        # Read the full cumulative output buffer (cursor 0).
        try:
            out = _pty.read_since(source_session_id, 0)
        except _pty.UnknownSession:
            return None  # no live PTY (e.g. reaped) → nothing to snapshot
        raw = (out.get("text") or "") if isinstance(out, dict) else ""
        body = _clean_transcript_text(raw, seed_text=record.get("seed_text") or "")
        if not body:
            return None
        store_lane = _eh._resolve_subdir(lane)
        short_sid = (source_session_id or "")[:12] or "session"
        rel = "%s/%s-transcript.md" % (store_lane, short_sid)
        dest = wt / store_lane / ("%s-transcript.md" % short_sid)
        dest.parent.mkdir(parents=True, exist_ok=True)
        header = "# %s session transcript (%s)\n\n" % (lane.title(), short_sid)
        dest.write_text(header + body + "\n", encoding="utf-8")
        return rel
    except Exception:
        return None


def prepare_stage_handoff(project_id, source_session_id, to_lane):
    """Persist the source stage's docs + build the real next-stage handoff (v11 W1).

    The ONE shared keystone for an advance/handoff. Given a SOURCE session (live
    or done) and the TARGET lane to advance into, it:

      (a) resolves the source session record (its lane + worktree) and maps
          ``to_lane`` → the next-stage skill (plan/planning→Crucible, build→Foreman);
      (b) **PERSISTS** the source session's produced docs via
          :func:`capture_session_docs` — copies + commits them into the main
          project AND records session-tagged DISCOVERED efforts. Best-effort and
          IDEMPOTENT (content-addressed, byte-identical skip); works whether the
          source is LIVE or done; does NOT reap the worktree. A persistence
          failure is swallowed (degrades to the honest minimal prompt) — it can
          NEVER raise out of this function;
      (c) **BUILDS** the next-stage prompt via
          ``handoff.build_next_stage_prompt`` — now that the docs are persisted +
          session-tagged, :func:`research_set_for_session` finds them → the REAL
          prompt naming the actual doc paths + a "read these first" instruction.
          For plan→build it discovers the plan set as today. Honest minimal,
          skill-correct prompt only when there are genuinely no docs;
      (d) **RESOLVES** the handoff materials: the real persisted ``doc_rels``
          (from :func:`effort_history.efforts_for_session_id` over the source
          lane; for plan→build also the discovered plan-set doc rels), the skill,
          and the source session's cached summary text (``""`` if absent);
      (e) **TRIGGERS** a NON-BLOCKING background source-stage summary (daemon
          thread; idempotent; failure swallowed) so the digest becomes available
          without blocking the advance.

    Returns ``{ok, prompt, doc_rels, skill, summary_text, persisted}``. ``ok`` is
    True when the source session resolved (even with no docs — an honest empty
    handoff is still a successful prepare). Never raises.
    """
    out = {"ok": False, "prompt": "", "doc_rels": [], "skill": "",
           "summary_text": "", "persisted": []}

    lane_key = (to_lane or "").strip().lower()
    skill = LANE_SKILL.get(lane_key, "")
    out["skill"] = skill

    # (a) Resolve the source session record + the project folder.
    rec = _reg.get_session(source_session_id)
    if rec is None:
        return out
    if not project_id:
        project_id = rec.get("project_id") or None
    if not project_id:
        return out
    source_lane = (rec.get("lane") or "").strip()
    proj = _rnd.get_project(project_id)
    if proj is None:
        return out
    folder = proj.get("folder_path", "")
    if not folder:
        return out
    # From here on the source resolved → an honest empty handoff is still ok.
    out["ok"] = True

    # (b) PERSIST the source session's produced docs — best-effort, idempotent,
    # NEVER raises out of prepare_stage_handoff (degrade to the honest prompt).
    try:
        persist_res = capture_session_docs(
            source_session_id, project_id=project_id, record=rec)
        if isinstance(persist_res, dict):
            out["persisted"] = list(persist_res.get("persisted") or [])
    except Exception:
        out["persisted"] = []

    # (b.2) v11.1 D3/D4: CONVERSATION-only capture. When the initial persist
    # produced ZERO document-classified docs (D4 — only the gap case), snapshot
    # the source session's PTY transcript into a lane doc and re-persist it so the
    # conversation is not lost and the REAL doc-referencing prompt engages. Wrapped
    # best-effort — on ANY failure leave ``persisted`` empty and fall through to
    # the honest-minimal prompt; NEVER raise out of prepare_stage_handoff.
    if not out["persisted"]:
        try:
            snap_rel = _snapshot_transcript_doc(rec, source_session_id)
            if snap_rel:
                persist_res2 = capture_session_docs(
                    source_session_id, project_id=project_id, record=rec)
                if isinstance(persist_res2, dict):
                    out["persisted"] = list(persist_res2.get("persisted") or [])
        except Exception:
            pass  # leave persisted as-is (empty) → honest-minimal prompt

    # (c) BUILD the next-stage prompt from the now-persisted, session-tagged docs.
    try:
        out["prompt"] = _handoff.build_next_stage_prompt(
            folder, project_id, source_session_id, lane_key) or ""
    except Exception:
        out["prompt"] = ""

    # (d) RESOLVE the handoff materials: the real persisted doc rels.
    doc_rels = []
    try:
        if source_lane:
            store_lane = _eh._resolve_subdir(source_lane)
            for e in _eh.efforts_for_session_id(
                    folder, project_id, store_lane, source_session_id):
                rel = (e.get("artifact_path") or "").strip().replace("\\", "/")
                if rel and rel not in doc_rels:
                    doc_rels.append(rel)
        # For plan→build also fold in the discovered plan-set doc rels (the
        # build's HANDOFF.md lists the plan documents, not the planning session's
        # own member docs only).
        if lane_key == "build":
            try:
                plan_set = _handoff.discover_recent_plan_set(
                    folder, project_id, source_session_id=source_session_id)
            except Exception:
                plan_set = None
            if plan_set:
                for r in _doc_paths_for_seed(plan_set):
                    if r and r not in doc_rels:
                        doc_rels.append(r)
    except Exception:
        pass
    out["doc_rels"] = doc_rels

    # (d cont.) the source session's cached summary text (honest "" if absent).
    try:
        import summarizer as _sm
        if source_lane:
            cached = _sm.load_cached(
                folder, project_id, _eh._resolve_subdir(source_lane),
                source_session_id)
            out["summary_text"] = _summary_text_from_cached(cached)
    except Exception:
        out["summary_text"] = ""

    # (e) TRIGGER a non-blocking background source-stage summary.
    try:
        _trigger_background_source_summary(
            folder, project_id, source_lane, source_session_id)
    except Exception:
        pass

    return out


def list_sessions(project_id=None, status=None):
    """Thin pass-through to ``session_registry.list_sessions`` (for UI/CLI)."""
    return _reg.list_sessions(project_id=project_id, status=status)


def get_session(session_id):
    """Return the registry record for ``session_id`` (or ``None``)."""
    return _reg.get_session(session_id)
