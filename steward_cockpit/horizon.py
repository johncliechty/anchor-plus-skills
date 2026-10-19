"""The after rule — the line under a project re-derived from the plan after every event that changes it (W3 of the
steward revision, 2026-09-28; the synthesis R3; his answer Q1: the line may be rewritten unattended, that line only).

``refresh(record_dir, reason)`` asks the engine to derive and write the horizon (``ecgberht update --horizon
--horizon-reason <reason>``): the step in hand, then what follows it — ONE shape at every moment, whatever the
trigger — stamped with the roadmap's last seq and the focus it was read from; unchanged since the stamp → the engine
writes nothing. The cockpit calls it on the events — accepted, produced (a run's handback), answered (a decision),
refined (the feedback turn, and again after the turn's reply so the turn's own sentence cannot stand over the
derivation). A close appends a roadmap event and is taken up by the tick. ``sweep(dirs)`` is the server tick's
half: with no seat awake, every record whose roadmap moved past its stamp is refreshed once (``reason="tick"``);
one sweep at a time. Best-effort, background, stdlib only; never a step, never a status."""
import json
import os
import subprocess
import threading
from pathlib import Path

import paths as _paths


#: A record the engine REFUSED (no focus: several active steps, none, or a current_step_id naming no step) is not
#: retried on every tick — only when its roadmap moves again. {record_dir: the last seq it refused at}
_REFUSED = {}
_REFUSED_LOCK = threading.Lock()


def _run(record_dir, reason, timeout=25.0):
    try:
        from . import engine_cli as _ecli
        deps = _ecli.resolve()          # the LIVE engine, never the vendored bundle (the 2026-09-28 live look)
        if not isinstance(deps, tuple):
            return deps
        node, cli = deps
        args = [node, cli, "update", "--project", str(record_dir), "--horizon"]
        if reason:
            args += ["--horizon-reason", str(reason)]
        completed = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                   errors="replace", timeout=timeout, creationflags=getattr(_paths, "NO_WINDOW", 0))
        out = (completed.stdout or "").strip()
        res = json.loads(out.splitlines()[-1]) if out else {"ok": False, "error": "no_output", "message": (completed.stderr or "")[:300]}
    except Exception as exc:
        res = {"ok": False, "error": "horizon_failed", "message": str(exc)[:300]}
    _note_refusal(record_dir, res)
    return res


def _note_refusal(record_dir, res):
    """Remember the engine's REFUSAL (``no_horizon``: no focus) at the roadmap's current seq so the tick does not
    spawn the engine for it again until the plan moves; a success clears it. A failed spawn (``horizon_failed``,
    ``no_output``) is not a refusal: the record stays stale and is retried (Grok W3)."""
    try:
        key = os.path.normcase(os.path.normpath(str(record_dir)))
        with _REFUSED_LOCK:
            if isinstance(res, dict) and res.get("ok") is False and res.get("error") == "no_horizon":
                _REFUSED[key] = _last_seq(record_dir)
            elif isinstance(res, dict) and res.get("ok") is not False:
                _REFUSED.pop(key, None)
    except Exception:
        pass


def refresh(record_dir, reason="", background=True):
    """Re-derive the line for ``record_dir`` after ``reason`` (accepted · produced · answered · refined · closed ·
    stalled · tick). Background by default so no route waits on the engine; returns the engine's JSON when run
    in the foreground. Never raises."""
    if not record_dir or not (Path(str(record_dir)) / "roadmap.json").is_file():
        return {"ok": False, "error": "no_record"}
    if not background:
        return _run(record_dir, reason)
    threading.Thread(target=_run, args=(record_dir, reason), name="horizon-refresh", daemon=True).start()
    return {"ok": True, "queued": True}


def _last_seq(record_dir):
    try:
        rm = json.loads((Path(record_dir) / "roadmap.json").read_text(encoding="utf-8"))
        ev = rm.get("roadmap_events") or []
        return int((ev[-1] or {}).get("seq") or 0) if ev else 0
    except Exception:
        return None


def _stamped_seq(record_dir):
    try:
        st = json.loads((Path(record_dir) / "strip.json").read_text(encoding="utf-8"))
        v = st.get("horizon_source_seq")
        return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None
    except Exception:
        return None


def stale(record_dir):
    """True when the roadmap has moved past the line's stamp (or the line was never derived), a strip exists, and
    the engine did not already refuse this record at this very seq."""
    last = _last_seq(record_dir)
    if last is None or not (Path(str(record_dir)) / "strip.json").is_file():
        return False
    with _REFUSED_LOCK:
        if _REFUSED.get(os.path.normcase(os.path.normpath(str(record_dir)))) == last:
            return False
    stamped = _stamped_seq(record_dir)
    return stamped is None or last > stamped


_SWEEP_LOCK = threading.Lock()
_SWEEP_RUNNING = {"on": False}


def sweep(dirs, runner=None, limit=8):
    """The tick's half (his Q1): refresh every stale record among ``dirs`` — at most ``limit`` per tick, oldest
    first in the given order — in ONE background thread; while a sweep is still running (a spawn can take up to its
    timeout) the tick starts none (Grok W3: the bound holds). Returns the dirs it will refresh. ``runner`` is
    injected by the tests."""
    with _SWEEP_LOCK:
        if _SWEEP_RUNNING["on"]:
            return []
        todo = [str(d) for d in dirs or () if stale(d)][: max(0, int(limit or 0))]
        if not todo:
            return []
        _SWEEP_RUNNING["on"] = True
    run = runner or (lambda d: _run(d, "tick"))

    def work():
        try:
            for d in todo:
                try:
                    res = run(d)
                    if runner is not None:
                        _note_refusal(d, res)     # an injected runner's refusal counts too
                except Exception:
                    pass
        finally:
            with _SWEEP_LOCK:
                _SWEEP_RUNNING["on"] = False
    threading.Thread(target=work, name="horizon-sweep", daemon=True).start()
    return todo


def record_dirs(roots):
    """Every steward record under the given project roots: the root when it has a Face, plus one level of efforts
    (the cockpit's own discovery). Never raises."""
    out = []
    try:
        from .steward_campaign import discover_efforts
    except Exception:
        return out
    for root in roots or ():
        try:
            for e in discover_efforts(str(root)) or []:
                rel = str((e or {}).get("rel") or "")
                out.append(str(Path(root) / rel) if rel else str(root))
        except Exception:
            continue
    return out
