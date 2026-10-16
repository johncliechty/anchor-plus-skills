"""Repair as a proposal — the cockpit's half (W4 of the steward revision, 2026-09-28; his answer Q2: "propose the
tidying too"). After he accepts a presentation, the engine composes the correction set from the records and appends
it as a ``repair_proposal`` (nothing changes); the tile says "proposed: N corrections"; on his word the engine
appends ``repair_resolve`` and, when accepted, the corrections as ordinary receipted ``step_set`` events. Both calls go
through the engine's closed verb; this module only spawns it. Best-effort; never a write of its own."""
import json
import subprocess
import threading
from pathlib import Path

import paths as _paths

#: the engine verb the two calls ride on (one place to change if the verb is renamed)
VERB = "update"


def _call(record_dir, args, timeout=25.0):
    try:
        from . import engine_cli as _ecli
        deps = _ecli.resolve()          # the LIVE engine, never the vendored bundle (the 2026-09-28 live look)
        if not isinstance(deps, tuple):
            return deps
        node, cli = deps
        completed = subprocess.run([node, cli, VERB, "--project", str(record_dir)] + list(args),
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                   errors="replace", timeout=timeout, creationflags=getattr(_paths, "NO_WINDOW", 0))
        out = (completed.stdout or "").strip()
        return json.loads(out.splitlines()[-1]) if out else {"ok": False, "error": "no_output", "message": (completed.stderr or "")[:300]}
    except Exception as exc:
        return {"ok": False, "error": "repair_failed", "message": str(exc)[:300]}


def propose(record_dir, step_id, presentation_id=None, background=True):
    """After an acceptance on ``step_id``: ask the engine to compose and append the proposal. Background by default."""
    if not record_dir or not (Path(str(record_dir)) / "roadmap.json").is_file() or not step_id:
        return {"ok": False, "error": "no_record"}
    args = ["--repair-propose", "--after-step", str(step_id)] + (["--after-presentation", str(presentation_id)] if presentation_id else [])
    if not background:
        return _call(record_dir, args)
    threading.Thread(target=_call, args=(record_dir, args), name="repair-propose", daemon=True).start()
    return {"ok": True, "queued": True}


def resolve(record_dir, proposal_id, disposition, who="john"):
    """His word on a proposal: ``accepted`` applies its corrections as receipted step events; ``dismissed`` closes
    it. Foreground: the route answers with the engine's result."""
    if disposition not in ("accepted", "dismissed"):
        return {"ok": False, "error": "bad_disposition"}
    if not record_dir or not proposal_id:
        return {"ok": False, "error": "no_record"}
    return _call(record_dir, ["--repair-resolve", str(proposal_id), "--disposition", disposition, "--who", str(who or "john")])


def open_proposals(events):
    """The open proposals in a roadmap's events: every repair_proposal with no repair_resolve naming it (the same rule
    as the engine's ``openRepairProposals``)."""
    evs = [e for e in (events or []) if isinstance(e, dict)]
    resolved = {str(e.get("proposal_id")) for e in evs if e.get("kind") == "repair_resolve"}
    return [e for e in evs if e.get("kind") == "repair_proposal" and str(e.get("proposal_id")) not in resolved]
