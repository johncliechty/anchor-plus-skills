"""Observe code jobs without imposing deadlines or controlling their processes."""

import math
import time
from pathlib import Path


INSPECTION_INTERVAL = 300.0
_WRITES = {"Write", "Edit", "NotebookEdit"}
_PENDING_LIMIT = 64


def _number(value):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if math.isfinite(value) else None
    return None


def _latest(*values):
    values = [value for value in map(_number, values) if value is not None]
    return max(values) if values else None


def _text(value):
    if isinstance(value, list):
        value = " ".join(str(part.get("text", "")) for part in value if isinstance(part, dict))
    return " ".join(str(value or "").split())[:300]


def _count(value):
    return max(0, int(value)) if _number(value) is not None else 0


def _paths(details):
    if not isinstance(details, dict):
        return
    for key in ("file_path", "notebook_path", "path"):
        if isinstance(details.get(key), str):
            yield details[key]
    for key in ("paths", "changes"):
        values = details.get(key, [])
        if isinstance(values, dict):
            values = list(values)
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str):
                    yield value
                elif isinstance(value, dict) and isinstance(value.get("path"), str):
                    yield value["path"]


def _qualifies(binding, raw):
    if not isinstance(binding, dict) or not binding.get("worktree"):
        return False
    # Import lazily: code_jobs also uses this observer for its running jobs.
    from . import code_jobs as cj

    try:
        worktree = Path(binding["worktree"])
        if not worktree.is_dir():
            return False
        relative = cj._rel_in(worktree, raw)
        if not relative or cj.scope_error(binding, worktree, [relative]):
            return False
        if cj._runtime(relative) or cj.never_lands(relative):
            return False
        if cj.is_document(relative) or Path(relative).suffix.lower() in {".log", ".tmp", ".temp"}:
            declared = {cj._rel_in(worktree, path) for path in binding.get("outputs", []) if isinstance(path, str)}
            return relative in declared
        return True
    except (OSError, TypeError, ValueError):
        return False


def sample(job, worker, native=None, now=None):
    """Return a JSON-safe observation; do not mutate inputs or act on a job.

    Timestamps are epoch seconds. Producer failure counts describe actual error
    events: observing the same stored error again does not create another failure.
    """
    now = time.time() if now is None else float(now)
    worker = worker or {}
    native = native or {}
    attempt = job.get("attempt", 1)
    old = job.get("supervision") or {}
    if old.get("attempt", 1) != attempt:
        old = {}
    phase = job.get("phase", "")
    phase_at = _number(job.get("phase_at"))
    progress_at = _number(old.get("progress_at"))
    progress_token = old.get("progress_token")
    advanced = False

    if phase_at is not None and (old.get("phase") != phase or progress_at is None):
        advanced = progress_at is None or phase_at > progress_at
        progress_at = _latest(progress_at, phase_at)

    verified_at = _number(worker.get("progress_at"))
    if verified_at is not None and (progress_at is None or verified_at > progress_at):
        progress_at = verified_at
        advanced = True

    source = native if native.get("progress_token") is not None else worker
    token = source.get("progress_token")
    if token is not None and token != progress_token:
        progress_token = token
        token_at = _number(source.get("progress_at"))
        progress_at = _latest(progress_at, now if token_at is None else token_at)
        advanced = True

    activity_at = _latest(old.get("activity_at"), worker.get("last_activity"), native.get("observed_at"))
    waiting_source = native if "waiting" in native else worker if "waiting" in worker else old
    waiting = _text(waiting_source.get("waiting"))
    if old.get("phase") != phase and "waiting" not in native and "waiting" not in worker:
        waiting = ""
    error_source = native if "error" in native else worker if "error" in worker else old
    error = _text(error_source.get("error"))
    repeat_errors = 0
    if error:
        repeat_errors = max(1, _count(error_source.get("repeat_errors")))
        if error == old.get("error"):
            repeat_errors = max(repeat_errors, _count(old.get("repeat_errors")))
    new_failure = error and (error != old.get("error") or repeat_errors > _count(old.get("repeat_errors")))
    if advanced and not new_failure:
        error, repeat_errors = "", 0

    liveness = worker.get("state", "unknown")
    if liveness not in {"active", "completed", "dead", "unknown"}:
        liveness = "unknown"
    interval = _number(job.get("inspection_interval"))
    if interval is None or interval <= 0:
        interval = INSPECTION_INTERVAL
    last_evidence = _latest(activity_at, progress_at, phase_at)
    status = job.get("status", "running")

    if status == "done":
        state = "complete" if job.get("landed") is True else "kept"
        reason = "Job completed and landed." if state == "complete" else "Job completed; outputs were kept."
        action = ""
    elif status in {"failed", "stopped"}:
        state = status
        reason = _text(job.get("error")) or error or f"Job {status}."
        action = "Inspect the original job and its saved outputs."
    elif liveness == "dead":
        state, reason = "dead", "The original process is verified to have exited."
        action = "Inspect the original job and recover its saved outputs."
    elif liveness == "completed":
        state, reason = "observing", "Worker completed; final checks or disposition remain."
        action = "Inspect the original job outcome."
    elif waiting:
        state, reason = "waiting", waiting
        action = "Resolve the reported wait for the original job."
    elif liveness == "unknown":
        state, reason = "visibility_lost", "The original process cannot be verified."
        action = "Inspect the original job's process identity and saved evidence."
    elif repeat_errors >= 3:
        state, reason = "needs_attention", f"Repeated failure without verified advancement: {error}"
        action = "Inspect the repeated failure in the original job."
    elif last_evidence is not None and now - last_evidence > interval:
        state, reason = "needs_inspection", "Process is alive; recent activity or progress has not been observed."
        action = "Inspect the original job; quiet time does not establish a hang."
    elif progress_at is not None and now - progress_at > interval:
        state, reason = "needs_inspection", "Activity continues, but advancement has not been observed recently."
        action = "Inspect the original job's current operation; activity alone does not establish progress or a hang."
    elif progress_at is not None and now - progress_at <= interval:
        state, reason, action = "progressing", "Verified progress was observed recently.", "Observe the original job."
    elif activity_at is not None and now - activity_at <= interval:
        state, reason, action = "active", "Recent activity is visible; it does not establish advancement.", "Observe the original job."
    else:
        state, reason, action = "observing", "Process is alive; progress evidence is limited.", "Observe the original job."

    return {
        "attempt": attempt, "observed_at": now, "phase": phase,
        "liveness": liveness, "state": state, "reason": reason, "action": action,
        "activity_at": activity_at, "progress_at": progress_at, "progress_token": progress_token,
        "waiting": waiting, "error": error, "repeat_errors": repeat_errors,
    }


def note_event(engine, ev, now=None):
    """Update bounded, in-memory evidence from actual provider events only."""
    if not isinstance(ev, dict):
        return
    now = time.time() if now is None else float(now)
    observation = getattr(engine, "job_observation", None)
    if not isinstance(observation, dict):
        observation = {}
        engine.job_observation = observation
    pending = observation.setdefault("pending_tools", {})

    def activity():
        observation["last_activity"] = _latest(observation.get("last_activity"), now)

    def progress():
        activity()
        observation["progress_at"] = _latest(observation.get("progress_at"), now)
        observation["progress_token"] = _count(observation.get("progress_token")) + 1
        observation["error"] = ""
        observation["repeat_errors"] = 0

    def failure(content):
        message = _text(content) or "Tool reported an error."
        observation["repeat_errors"] = _count(observation.get("repeat_errors")) + 1 if message == observation.get("error") else 1
        observation["error"] = message

    def completed_change(event, details=None):
        activity()
        if not any(_qualifies(getattr(engine, "code_job", None), path) for path in _paths(event if details is None else details)):
            return
        identity = event.get("id")
        seen = observation.setdefault("completed_changes", [])
        if identity and identity in seen:
            return
        if identity:
            seen.append(identity)
            del seen[:-_PENDING_LIMIT]
        progress()

    def visit(event):
        if not isinstance(event, dict):
            return
        kind = event.get("type")
        if kind == "stream_event":
            visit(event.get("event"))
        elif kind in {"assistant", "user"}:
            if kind == "assistant":
                activity()
            message = event.get("message") or {}
            content = message.get("content", []) if isinstance(message, dict) else []
            if isinstance(content, list):
                for block in content:
                    visit(block)
        elif kind == "content_block_start":
            visit(event.get("content_block"))
        elif kind == "content_block_delta":
            if (event.get("delta") or {}).get("type") == "text_delta":
                activity()
        elif kind in {"text", "text_delta"}:
            activity()
        elif kind == "tool_use":
            activity()
            identity = event.get("id")
            tool_input = event.get("input") or {}
            if identity:
                name = event.get("name", "")
                qualified = name in _WRITES and any(_qualifies(getattr(engine, "code_job", None), path) for path in _paths(tool_input))
                pending[identity] = {"id": identity, "name": name, "qualified": qualified}
                while len(pending) > _PENDING_LIMIT:
                    pending.pop(next(iter(pending)))
            if event.get("name") == "file_change" and isinstance(tool_input, dict) and tool_input.get("status") == "completed":
                completed_change(event, tool_input)
                pending.pop(identity, None)
        elif kind == "tool_result":
            activity()
            identity = event.get("tool_use_id")
            seen = observation.setdefault("completed_results", [])
            if identity:
                if identity in seen:
                    return
                seen.append(identity)
                del seen[:-_PENDING_LIMIT]
            tool = pending.pop(identity, {})
            if event.get("is_error"):
                failure(event.get("content"))
            elif tool.get("name") in _WRITES and tool.get("qualified"):
                progress()
        elif kind == "file_change" and event.get("status") == "completed":
            completed_change(event)
        elif kind == "item.completed":
            item = event.get("item") or {}
            if isinstance(item, dict) and item.get("type") == "file_change" and item.get("status") == "completed":
                completed_change(item)
        elif kind == "job_wait":
            activity()
            observation["waiting"] = _text(event.get("reason"))

    visit(ev)
