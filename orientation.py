"""Read-only plan-mode ORIENTATION one-shot job (telemetry-resume W6).

The Phase-0 **orientation fork** (LOCKED, ``NORTH-STAR-AMENDMENT.md`` →
"Orientation fork"): when a user escalates a parked/done/discovered tile to a live
session, the read-only orientation narration AUTO-EXECUTES as a **read-only
plan-mode one-shot job** through :mod:`job_runner` (the Gandalf-shard substrate,
VERIFIED enforceable in ``W1-GROUND-TRUTH.md`` §2) — *never* a seeded turn on the
live interactive PTY. Any mutating/ACTION prompt stays v10 **paste-NOT-submit**;
nothing is ever auto-submitted on the user's behalf.

Why a separate job rather than a PTY seed:
  * ``--permission-mode plan`` (claude) / ``--readonly`` (gemini) makes the
    orientation read physically unable to edit the analyzed tree — so an
    auto-executed orientation can never mutate state from a read gesture (the
    strict-literal-reading rejection's concern (a)).
  * The live PTY session the user escalates into is left CLEAN — its input line
    is free for the user, and any ACTION prompt sits there UNSENT (paste-NOT-
    submit), so orientation and action never race on the same stdin.

Lifecycle tag: :func:`orient_session` stamps the origin session record with an
``orientation_owned_until`` window (``ORIENTATION_OWNERSHIP_SECS``), so the
zombie-hunter live-owner computation (:func:`reaper.build_snapshot`) treats the
session as OWNED while the orientation read is in flight, then the window
auto-expires — no cleanup daemon required.

Stdlib only; :mod:`job_runner` / :mod:`narration` / :mod:`session_registry` are
imported lazily so the pure helpers (prompt builder, ownership math) can be tested
with no live registry. Never raises out of :func:`orient_session` — an honest
error dict is returned instead.
"""
from __future__ import annotations

import os
import time

#: The orientation-origin ownership window (seconds). While ``now <
#: orientation_owned_until`` the origin session is OWNED (never a zombie). Env
#: ``ANCHOR_ORIENTATION_OWNERSHIP_SECS`` overrides (tests set a tiny/zero window).
ORIENTATION_OWNERSHIP_SECS_ENV = "ANCHOR_ORIENTATION_OWNERSHIP_SECS"
ORIENTATION_OWNERSHIP_SECS_DEFAULT = 300.0  # 5 minutes

#: The read-only permission mode the orientation job MUST run under. ``plan`` is
#: read-only for claude (``--permission-mode plan``); job_runner maps it to
#: ``--readonly`` for gemini. NEVER ``acceptEdits``/``bypassPermissions``.
ORIENTATION_PERMISSION_MODE = "plan"

#: The lane the orientation job launches under. ``research`` is non-gated and
#: takes its prompt on argv (a one-shot read), exactly like a Gandalf shard.
ORIENTATION_LANE = "research"


def ownership_secs(env=None) -> float:
    """The orientation-ownership window in seconds (env override or default)."""
    e = os.environ if env is None else env
    raw = (e.get(ORIENTATION_OWNERSHIP_SECS_ENV) or "").strip()
    if raw:
        try:
            v = float(raw)
            if v >= 0:
                return v
        except (TypeError, ValueError):
            pass
    return ORIENTATION_OWNERSHIP_SECS_DEFAULT


def build_orientation_prompt(view, *, lane="", session_id="") -> str:
    """The read-only orientation prompt from a narration view (PURE, no I/O).

    ``view`` is a :func:`narration.build_narration` projection (or ``None``). The
    prompt instructs the model — running READ-ONLY under plan mode — to read the
    session's produced documents and print a concise orientation: what was done,
    what was produced, and what comes next. It carries the durable facts inline
    (doc paths + the next-step) so the read is grounded and never fabricates.

    It is explicitly a READ-ONLY briefing prompt: it asks only to READ and
    SUMMARIZE; it never instructs an edit/run. (The ACTION prompt, if any, is
    delivered separately as v10 paste-NOT-submit — never folded in here.)
    """
    view = view if isinstance(view, dict) else {}
    lane = (lane or view.get("lane") or "").strip()
    done = (view.get("done") or "").strip()
    produced = view.get("produced") or []
    nxt = (view.get("next") or {})
    next_text = (nxt.get("text") or "").strip() if isinstance(nxt, dict) else ""

    lines = [
        "You are resuming a prior work session. This is a READ-ONLY orientation "
        "briefing — do NOT edit, create, run, or modify anything; only read and "
        "summarize.",
        "",
        "Print a short orientation for the user, in three parts:",
        "  1. What was done — the work this session accomplished.",
        "  2. What was produced — the documents/artifacts it left behind.",
        "  3. What comes next — the natural next step.",
        "",
        "Durable context for this session"
        + (f" (lane: {lane})" if lane else "") + ":",
    ]
    if done:
        lines.append(f"- Prior summary: {done}")
    if produced:
        lines.append("- Documents produced:")
        for p in produced:
            if not isinstance(p, dict):
                continue
            label = (p.get("label") or p.get("href") or "").strip()
            role = (p.get("role") or "").strip()
            tag = f"{role}: " if role else ""
            if label:
                lines.append(f"    - {tag}{label}")
    else:
        lines.append("- No recoverable documents on disk; orient from the "
                     "summary above and the project context.")
    if next_text:
        lines.append(f"- Suggested next step: {next_text}")
    lines.append("")
    lines.append("Read the RESTART.md document if present to get oriented quickly. Do NOT read the full raw transcripts unless specifically needed to clarify an ambiguous point in the RESTART.md summary. Then print the three-part orientation. Take no other action.")
    return "\n".join(lines)


def orient_session(project_id, lane, session_id, *, folder_path=None,
                   record=None, launch=None, env=None, now=None):
    """Launch the read-only plan-mode orientation one-shot job (W6, never raises).

    Resolves the session's Layer-1 narration view (read-only, cache-only via
    :func:`narration.narrate_session`), builds the orientation prompt, and launches
    a **plan-mode** (``permission_mode='plan'`` → read-only) one-shot job through
    :func:`job_runner.launch` in the session's worktree (or the project folder).
    It then stamps the origin session record with an ``orientation_owned_until``
    window so the zombie-hunter never flags/kills it mid-read.

    ``launch`` (a callable with :func:`job_runner.launch`'s signature) is an
    injectable seam for tests. Returns
    ``{ok, job_id, permission_mode, owned_until, prompt}`` or, on failure, an
    honest ``{ok: False, reason}`` — the orientation is best-effort and never
    breaks the escalation.
    """
    now = time.time() if now is None else now
    # Resolve the record + narration view (read-only; both degrade gracefully).
    if record is None:
        try:
            import session_registry as _sr
            record = _sr.get_session(session_id) or {}
        except Exception:
            record = {}
    if not isinstance(record, dict):
        record = {}
    if folder_path is None:
        try:
            import rnd_registry as _rnd
            folder_path = (_rnd.get_project(project_id) or {}).get(
                "folder_path", "")
        except Exception:
            folder_path = ""
    try:
        import narration as _narr
        view = _narr.narrate_session(project_id, lane, session_id,
                                     folder_path=folder_path, record=record)
    except Exception:
        view = {}
    prompt = build_orientation_prompt(view, lane=lane, session_id=session_id)

    # The read runs in the session's worktree when it survives, else the project
    # folder. An evicted worktree ("") falls back to the folder (docs persisted).
    cwd = (record.get("worktree_path") or "").strip() or (folder_path or "")
    if not cwd:
        return {"ok": False, "reason": "no-working-dir"}

    if launch is None:
        try:
            import job_runner as _jr
            launch = _jr.launch
        except Exception:
            return {"ok": False, "reason": "job-runner-unavailable"}

    try:
        rec = launch(ORIENTATION_LANE, cwd=cwd, prompt=prompt,
                     output_dir=cwd, permission_mode=ORIENTATION_PERMISSION_MODE,
                     project_id=project_id, folder_path=folder_path)
    except Exception as exc:
        return {"ok": False, "reason": "launch-failed", "detail": str(exc)}
    job_id = (rec or {}).get("job_id") or ""
    if not job_id:
        return {"ok": False, "reason": "launch-failed"}

    owned_until = now + ownership_secs(env)
    # Stamp the origin session so the hunter treats it as owned-for-N-minutes.
    try:
        import session_registry as _sr
        _sr.update_session(session_id, orientation_job_id=job_id,
                           orientation_owned_until=owned_until)
    except Exception:
        pass  # best-effort — the job still runs; ownership is a safety belt

    return {"ok": True, "job_id": job_id,
            "permission_mode": ORIENTATION_PERMISSION_MODE,
            "owned_until": owned_until, "prompt": prompt}
