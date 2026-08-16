"""One-time cold-open rebuild command (steward-chamber W5, C1/C3/E8).

Campaigns PREDATING the chamber projectors have no sidecar at all — no
pipeline manifest, no projection store, no precomputed brief. The first Seal
open after a deploy binds ONE drawn behavior (C1: drawn-degraded-until-
rebuilt): the chamber paints the drawn degraded state and surfaces THIS
command as the explicit rebuild affordance. Running it derives the FULL
chamber projection from the campaign's existing ledger:

    manifest     — the W5 brownfield derivation (``chamber_brownfield``):
                   derive-or-drawn-degraded, never a guess. A DECLARED
                   (scaffold-time / hand-authored) manifest is KEPT, never
                   clobbered.
    projections  — the W4 event-time projection store REBUILT from the run
                   records: produced -> ``step_yield``, died/quiet/timeout ->
                   ``run_death``, and a ``commission_start`` whenever the
                   start instant is honestly derivable (record ``at`` minus
                   ``elapsed_s``). Every rebuilt event is tagged ``derived``
                   with its run-record cite — a reader can always tell
                   rebuilt-derived history from live-observed events. No
                   ``deliverable_landing`` is ever derived (a brownfield
                   ledger never declared a deliverable; fabricating a landing
                   would be a guess).
    brief        — the W5 situation-brief precompute (``chamber_reconcile``):
                   stand / running / next move / goal-guard, run records
                   last-writer-wins over reflection claims (E9). Pre-emission
                   reflections (real campaigns today) derive deterministically
                   from what exists, else paint the DRAWN degraded brief
                   (AG-PRE-EMISSION-OPEN) — never a synthesized narrative.

LAWS:

* **One-time in purpose, re-runnable in fact** — the derivation is a pure
  function of the ledger bytes: rebuilding twice yields byte-identical
  sidecar files. "One-time" means it migrates campaigns that predate the
  projectors; nothing breaks if it runs again.
* **Zero spine writes (E8)** — every write lands under the chamber sidecar
  (``.anchor/chamber/``). ``roadmap.json``, the ``.ecgberht/`` stores and the
  run records are READ, never written.
* **An observed live store is never clobbered** — a projection store carrying
  live-observed events (no ``rebuilt`` provenance) is a NAMED refusal
  (``live-projection-store``), not an overwrite. A CORRUPT store is the one
  exception: the rebuild is that failure's documented cure
  (``chamber_projections.load_store``'s own error text names this command).
* **Degraded is honest, refusal is different** — an underivable campaign maps
  to the drawn degraded-rail / degraded-brief state (a valid outcome; the
  command still "works"); only a refusal or an unreadable foreign manifest
  makes the command report ``ok: False``.

Command form::

    python chamber_coldopen.py rebuild <project-folder>

Stdlib only. Atomic writes + the cross-process lock ride
``chamber_projections`` (one sidecar durability discipline).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import chamber_brownfield as cb
import chamber_manifest as cm
import chamber_projections as _cp
import chamber_reconcile as cr

#: Provenance key stamped on a REBUILT store document. Its absence on a
#: non-empty store means the events were live-observed — never clobbered.
REBUILT_KEY = "rebuilt"
REBUILT_BY = "chamber_coldopen"

ROUTE_REBUILT = "rebuilt"
ROUTE_KEPT_MANIFEST = "kept-declared-manifest"
ROUTE_REFUSED = "refused"
ROUTE_PRECOMPUTED = "precomputed"

REFUSAL_LIVE_STORE = "live-projection-store"

_TS_FMT = "%Y-%m-%dT%H:%M:%S"


# ── Event-time derivation from the run records (reads only) ─────────────────

def _derived_start_at(at, elapsed_s):
    """The commission's start instant, derived as record ``at`` minus
    ``elapsed_s`` — deterministic arithmetic on ledger data, or None when the
    inputs cannot honestly yield it (no synthesized timestamps)."""
    if not at or not isinstance(elapsed_s, (int, float)) or elapsed_s < 0:
        return None
    try:
        finished = datetime.strptime(at, _TS_FMT)
    except ValueError:
        return None
    return (finished - timedelta(seconds=int(elapsed_s))).strftime(_TS_FMT)


def derive_projection_events(folder) -> list:
    """The W4 projection events honestly derivable from the run records, in
    deterministic event-time order (``at``, start-before-terminal, session).
    Outcomes that map to none of the four kinds (e.g. ``asked``) derive no
    event — the record is not erased, it simply is not a projection fact."""
    derived = []
    for r in cr.read_run_records(folder):
        cite = "run-record:%s" % r["session_id"]
        start_at = _derived_start_at(r["at"], r.get("elapsed_s"))
        if start_at and r.get("commission_id"):
            derived.append((start_at, 0, str(r["session_id"]), {
                "kind": _cp.KIND_COMMISSION_START,
                "at": start_at,
                "commission_id": r["commission_id"],
                "session_id": r["session_id"],
                "step_id": r["step_id"],
                "skill": r["skill"],
                "lane": r["lane"],
                "derived": True,
                "derived_from": cite + " (at - elapsed_s)",
            }))
        if r["outcome"] in cr.SUCCESS_OUTCOMES:
            yield_line = r.get("report_say") or (
                "produced by %s on %s" % (r["skill"] or "a run",
                                          r["step_id"] or "a step"))
            derived.append((r["at"], 1, str(r["session_id"]), {
                "kind": _cp.KIND_STEP_YIELD,
                "at": r["at"],
                "commission_id": r["commission_id"],
                "step_id": r["step_id"],
                "yield": str(yield_line)[:300],
                "report_link": cite,
                "session_id": r["session_id"],
                "derived": True,
                "derived_from": cite,
            }))
        elif r["outcome"] in cr.DEATH_OUTCOMES:
            derived.append((r["at"], 1, str(r["session_id"]), {
                "kind": _cp.KIND_RUN_DEATH,
                "at": r["at"],
                "commission_id": r["commission_id"],
                "session_id": r["session_id"],
                "outcome": r["outcome"],
                "detail": None,
                "derived": True,
                "derived_from": cite,
            }))
    derived.sort(key=lambda row: (row[0], row[1], row[2]))
    return [{"seq": i + 1, **e} for i, (_, _, _, e) in enumerate(derived)]


# ── The three rebuild parts ─────────────────────────────────────────────────

def rebuild_projection_store(folder) -> dict:
    """Rebuild the chamber projection store from the run records.

    Missing / empty / own-rebuilt / CORRUPT stores rebuild; a store carrying
    live-observed events is a NAMED refusal — rebuilt history must never
    silently replace observation history."""
    target = _cp.store_path(folder)
    was_corrupt = False
    if target.exists():
        try:
            store = _cp.load_store(folder)
            if store.get("events") and REBUILT_KEY not in store:
                return {
                    "ok": False, "route": ROUTE_REFUSED,
                    "reason": REFUSAL_LIVE_STORE,
                    "message": "the projection store carries live-observed "
                               "events (no rebuilt provenance) — the cold-open"
                               " rebuild never clobbers observation history; "
                               "it exists for campaigns predating the "
                               "projectors and for corrupt stores",
                }
        except _cp.ProjectionStoreError:
            # The documented cure: an unreadable store is exactly what the
            # rebuild re-derives.
            was_corrupt = True

    events = derive_projection_events(folder)
    doc = {
        "schema": _cp.SCHEMA,
        "events": events,
        REBUILT_KEY: {
            "by": REBUILT_BY,
            "source": "run-records (event-time derivation)",
            "law": "rebuildable derived data (never source of truth); a "
                   "live-observed store is never clobbered",
        },
    }
    with _cp.file_lock(_cp.lock_path(folder)):
        _cp.atomic_write_json(target, doc)
    return {"ok": True, "route": ROUTE_REBUILT, "event_count": len(events),
            "was_corrupt": was_corrupt, "store_rel": _cp.PROJECTIONS_REL}


def rebuild_manifest(folder) -> dict:
    """The manifest leg: brownfield derive-or-degraded, except a DECLARED
    manifest (scaffold-derived or hand-authored — no ``brownfield``
    provenance) is kept untouched. An unreadable existing manifest stays
    ``chamber_brownfield``'s named refusal."""
    existing = cm.load_manifest(folder)
    if existing is not None and "_unparseable" not in existing \
            and "brownfield" not in existing:
        return {"ok": True, "route": ROUTE_KEPT_MANIFEST,
                "message": "a declared sidecar manifest already exists — "
                           "kept, never clobbered by the rebuild"}
    return cb.apply_brownfield_derivation(folder)


# ── The command ─────────────────────────────────────────────────────────────

def cold_open_rebuild(folder) -> dict:
    """Derive the FULL chamber projection (manifest + projection store +
    situation brief) from the campaign's existing ledger. Deterministic and
    re-runnable; every write lands under ``.anchor/chamber/``; a drawn
    degraded outcome is a success, a refusal is not."""
    manifest_part = rebuild_manifest(folder)
    store_part = rebuild_projection_store(folder)

    brief_doc = cr.precompute_brief(folder, persist=True)
    brief_part = {"ok": True, "route": ROUTE_PRECOMPUTED,
                  "brief_rel": cr.BRIEF_REL,
                  "pre_emission": brief_doc["pre_emission"],
                  "degraded": brief_doc["degraded"]}

    parts = {"manifest": manifest_part, "projections": store_part,
             "brief": brief_part}
    degraded_parts = [
        name for name, p in parts.items()
        if p.get("route") == cb.ROUTE_DEGRADED or p.get("degraded")]
    refused_parts = [
        name for name, p in parts.items()
        if not p.get("ok") and p.get("route") != cb.ROUTE_DEGRADED]

    return {
        "ok": not refused_parts,
        "parts": parts,
        "degraded_parts": degraded_parts,
        "refused_parts": refused_parts,
        # Factual, testable claim: the rebuild's writes all land here.
        "writes_under": _cp.CHAMBER_SIDECAR_REL,
    }


def _cli(argv) -> int:
    """``python chamber_coldopen.py rebuild <project-folder>`` — the one-time
    cold-open rebuild command (the affordance W6 surfaces on a degraded
    first open). Prints the honest per-part outcome as JSON."""
    if len(argv) != 2 or argv[0] != "rebuild":
        print("usage: chamber_coldopen.py rebuild <project-folder>")
        return 2
    out = cold_open_rebuild(argv[1])
    print(json.dumps(out, indent=2))
    return 0 if out["ok"] else 1


if __name__ == "__main__":
    import sys
    sys.exit(_cli(sys.argv[1:]))
