"""Reconciliation + situation-brief precompute (steward-chamber W5, C3/E8/E9).

Two jobs, one read set (last reflection + roadmap + run records — the open
read set of the provenance table):

**1. The reconciliation pass** (:func:`reconcile`) — RUN RECORDS ARE
LAST-WRITER-WINS OVER REFLECTION CLAIMS (E9). A reflection is the steward's
narrative about the campaign at the moment it was composed; a run record is
what actually happened to a run. When a run DIED (died/quiet/timeout) at or
after the last reflection landed, the reconciled state says the run died and
cites the run record — the reflection text survives only as narrative color.
The same law applies against roadmap claims: a step's reconciled RUN state is
its latest run record's outcome, whatever the step status or the reflection
narrative implies.

**2. The brief precompute projector** (:func:`precompute_brief`, subscribed
at reflection-landing time via :func:`on_reflection_landing` — wired into
``commission_session.finish_run``) — derives the situation-brief fields the
M1 open paints (C3): ``stand`` / ``running``-and-doing-what / one
``next_move`` / the ``goal_guard`` line — into the CHAMBER SIDECAR
(``.anchor/chamber/brief.json``). E8: the brief lives in the steward-plane
chamber sidecar; ZERO spine writes (roadmap.json, ``.ecgberht/`` and the run
records are read, never written — the run records are not even chamber data
to touch).

PRE-EMISSION CAMPAIGNS (predating reflection emission — every real campaign
today): the brief derives DETERMINISTICALLY from what exists (roadmap steps,
run records, the attention cell, the Face's north star). Only when NOTHING
derivable exists does the brief paint the DRAWN degraded state
(AG-PRE-EMISSION-OPEN, the W1 amendment batch) — an honest degraded brief,
never a synthesized narrative.

DETERMINISM: pure function of the on-disk read set — no wall clock (``as_of``
is the max input timestamp), no model, no randomness. Rebuilding twice yields
byte-identical ``brief.json`` (the W5 cold-open rebuild relies on this).

Stdlib only. Atomic write + cross-process lock ride ``chamber_projections``
(one sidecar durability discipline).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import chamber_projections as _cp

SCHEMA = "anchor-chamber-brief-v1"

BRIEF_REL = os.path.join(_cp.CHAMBER_SIDECAR_REL, "brief.json")
BRIEF_LOCK_REL = BRIEF_REL + ".lock"

#: Anchor-side run records (the steward's own bookkeeping; READ here, never
#: written — mirrors commission_session.RUN_RECORDS_REL without importing the
#: heavy module).
RUN_RECORDS_REL = os.path.join(".anchor", "commission-runs")

#: Run-outcome vocabulary (commission_runner RUN_* + the live state).
OUTCOME_LIVE = "running"
DEATH_OUTCOMES = ("died", "quiet", "timeout")
SUCCESS_OUTCOMES = ("produced",)

#: The drawn degraded-brief state for a campaign with no derivable basis —
#: the pre-emission-open row of the W1 batched mockup-amendment gate.
DEGRADED_BRIEF_STATE = "degraded-brief"
PRE_EMISSION_AMENDMENT_REF = "AG-PRE-EMISSION-OPEN"
GOAL_UNREADABLE_AMENDMENT_REF = "AG-GOAL-UNREADABLE"

#: The E9 law, machine-readable (tests assert the words, renders may cite it).
LAST_WRITER_WINS_RULE = (
    "run records beat reflection claims (last-writer-wins, E9): a run "
    "record whose timestamp is >= the last reflection's overrides the "
    "reflection's narrative; reflection text is narrative color only")

_TEXT_CAP = 300


def brief_path(folder) -> Path:
    return Path(folder) / BRIEF_REL


# ── Reads (chamber-side, read-only, never a write) ──────────────────────────

def read_run_records(folder) -> list:
    """Normalized run records, ascending by (at, session_id) — a stable,
    deterministic order. Unreadable individual records are skipped (they
    cannot claim anything)."""
    root = Path(folder) / RUN_RECORDS_REL
    if not root.is_dir():
        return []
    rows = []
    for p in sorted(root.glob("*.json")):
        try:
            rec = json.loads(p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(rec, dict):
            continue
        outcome = rec.get("outcome")
        rows.append({
            "session_id": rec.get("session_id") or p.stem,
            "commission_id": rec.get("commission_id"),
            "step_id": rec.get("step_id"),
            "skill": rec.get("skill"),
            "lane": rec.get("lane"),
            "outcome": outcome,
            "at": rec.get("at") or "",
            "elapsed_s": (rec.get("elapsed_s")
                          if isinstance(rec.get("elapsed_s"), (int, float))
                          else None),
            "report_say": (_first_line((rec.get("report") or {}).get("say"))
                           if isinstance(rec.get("report"), dict) else ""),
            "terminal": outcome != OUTCOME_LIVE,
            "has_reflection": isinstance(rec.get("reflection"), dict),
            "reflection": (rec.get("reflection")
                           if isinstance(rec.get("reflection"), dict)
                           else None),
        })
    rows.sort(key=lambda r: (r["at"], str(r["session_id"])))
    return rows


def read_reflection_receipts(folder) -> list:
    """``reflection_receipt`` roadmap events (the engine's emitted receipts —
    engine/handback-ingest.mjs :: emitReflectionReceipt), read-only, ledger
    order. Real campaigns today PREDATE emission; fixtures and future
    campaigns carry them."""
    p = Path(folder) / "roadmap.json"
    if not p.exists():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    events = doc.get("roadmap_events")
    if not isinstance(events, list):
        return []
    return [e for e in events
            if isinstance(e, dict) and e.get("kind") == "reflection_receipt"]


def read_roadmap_steps(folder) -> list:
    """``[{id, name, status}]`` from roadmap_projection, ledger order.
    Unreadable roadmap → honest empty (the brief derives from what remains)."""
    p = Path(folder) / "roadmap.json"
    if not p.exists():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return []
    steps = doc.get("roadmap_projection")
    if not isinstance(steps, list):
        return []
    out = []
    for s in steps:
        if isinstance(s, dict) and isinstance(s.get("id"), str) and s["id"]:
            out.append({"id": s["id"],
                        "name": (s.get("name") if isinstance(s.get("name"), str)
                                 else s["id"]),
                        "status": (s.get("status")
                                   if isinstance(s.get("status"), str)
                                   else None)})
    return out


def read_attention(folder) -> dict | None:
    p = Path(folder) / ".ecgberht" / "attention.json"
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else None
    except (ValueError, OSError):
        return None


_NORTH_STAR_RE = re.compile(
    r"##\s+North star\s*\r?\n([\s\S]*?)(?=\r?\n##\s+|$)", re.IGNORECASE)


def read_goal_guard(folder) -> dict:
    """The goal-guard line: the Face's ``## North star`` section (the same
    locked-heading rule engine/face-strip.mjs parses), flattened to one
    capped line. Unreadable/absent → the DRAWN AG-GOAL-UNREADABLE state
    (honest degraded field), never a guessed goal."""
    p = Path(folder) / "ECGBERHT.md"
    degraded = {"text": None, "source": None,
                "degraded": {"amendment_ref": GOAL_UNREADABLE_AMENDMENT_REF,
                             "reason": "north-star-unreadable"}}
    if not p.exists():
        return degraded
    try:
        body = p.read_text(encoding="utf-8")
    except OSError:
        return degraded
    m = _NORTH_STAR_RE.search(body)
    if not m:
        return degraded
    lines = []
    for raw in m.group(1).splitlines():
        line = raw.strip()
        if not line:
            if lines:
                break  # first paragraph only — the north-star LINE
            continue
        lines.append(line.lstrip("> ").strip())
    text = " ".join(lines).replace("**", "").strip()
    if not text:
        return degraded
    return {"text": text[:_TEXT_CAP], "source": "ECGBERHT.md :: North star"}


def last_reflection(folder, runs=None) -> dict | None:
    """The LAST reflection to land, across run-record reflections and emitted
    reflection_receipt events, by timestamp (ISO-8601 strings compare
    lexicographically). None on a pre-emission campaign."""
    candidates = []
    for r in (runs if runs is not None else read_run_records(folder)):
        if r["has_reflection"]:
            candidates.append({"at": r["at"],
                               "source": "run-record:%s" % r["session_id"],
                               "reflection": r["reflection"]})
    for e in read_reflection_receipts(folder):
        candidates.append({"at": str(e.get("at") or ""),
                           "source": "roadmap-event:reflection_receipt:%s"
                                     % e.get("seq"),
                           "reflection": e})
    if not candidates:
        return None
    candidates.sort(key=lambda c: c["at"])
    return candidates[-1]


# ── The reconciliation pass ─────────────────────────────────────────────────

def reconcile(folder) -> dict:
    """Reconcile the reflection + roadmap + run-record read set with run
    records LAST-WRITER-WINS. Pure read; deterministic."""
    runs = read_run_records(folder)
    steps = read_roadmap_steps(folder)
    refl = last_reflection(folder, runs=runs)

    # Per-step reconciled RUN state: the latest run record on the step wins
    # over any roadmap/reflection claim about the RUN (the step's own status
    # stays reported as the roadmap's claim, honestly side by side).
    last_run_by_step: dict = {}
    for r in runs:
        if r.get("step_id"):
            last_run_by_step[r["step_id"]] = r  # ascending order → last wins
    step_rows = []
    for s in steps:
        run = last_run_by_step.get(s["id"])
        step_rows.append({
            **s,
            "reconciled_run_state": (run["outcome"] if run else None),
            "run_cite": ("run-record:%s" % run["session_id"]) if run else None,
        })

    # The died-after-last-reflection override (E9's acceptance case): a run
    # that died AT OR AFTER the last reflection landed. On an equal timestamp
    # the record still wins — the law is last-WRITER-wins and the record is
    # the writer of record for run state.
    died_after = None
    overrides = []
    if refl is not None:
        deaths = [r for r in runs
                  if r["outcome"] in DEATH_OUTCOMES and r["at"] >= refl["at"]]
        if deaths:
            d = deaths[-1]
            died_after = {
                "run": d,
                "cites": "run-record:%s" % d["session_id"],
                "reflection_at": refl["at"],
                "reflection_source": refl["source"],
                "rule": LAST_WRITER_WINS_RULE,
            }
            overrides.append({
                "claim_source": refl["source"],
                "claim": "reflection narrative (composed %s)" % refl["at"],
                "record_cite": died_after["cites"],
                "record_outcome": d["outcome"],
                "winner": "run-record",
                "rule": LAST_WRITER_WINS_RULE,
            })

    counts: dict = {}
    for s in steps:
        key = s["status"] or "unknown"
        counts[key] = counts.get(key, 0) + 1

    stamps = [r["at"] for r in runs if r["at"]]
    if refl:
        stamps.append(refl["at"])
    att = read_attention(folder)
    if att and att.get("at"):
        stamps.append(str(att["at"]))
    return {
        "ok": True,
        "runs": runs,
        "steps": step_rows,
        "step_status_counts": counts,
        "last_reflection": refl,
        "died_after_last_reflection": died_after,
        "overrides": overrides,
        "attention": att,
        "as_of": max(stamps) if stamps else None,
    }


# ── The brief precompute projector (E8: steward-plane chamber sidecar) ──────

def _first_line(text, cap=_TEXT_CAP) -> str:
    line = str(text or "").strip().splitlines()
    return (line[0].strip()[:cap]) if line else ""


def _stand_field(rec: dict) -> dict:
    steps = rec["steps"]
    done = sum(1 for s in steps if s["status"] == "done")
    produced = [r for r in rec["runs"] if r["outcome"] in SUCCESS_OUTCOMES]
    bits = []
    if steps:
        bits.append("%d of %d steps done." % (done, len(steps)))
    if produced:
        p = produced[-1]
        bits.append("Last landed: %s on %s (produced %s)."
                    % (p["skill"] or "a run", p["step_id"] or "a step",
                       p["at"] or "unknown time"))
    field = {
        "text": " ".join(bits) or None,
        "source": "roadmap_projection + run-records",
    }
    refl = rec["last_reflection"]
    if refl:
        impact = (refl["reflection"] or {}).get("impact")
        if impact:
            # E9: reflection prose enters the brief ONLY as labeled color,
            # in its own slot — never as the grounded text.
            field["color"] = {"text": str(impact).strip()[:_TEXT_CAP],
                              "source": refl["source"],
                              "role": "narrative color only (E9)"}
    return field


def _running_field(rec: dict) -> dict:
    live = [r for r in rec["runs"] if r["outcome"] == OUTCOME_LIVE]
    if live:
        r = live[-1]
        return {"text": "Running: %s on %s (since %s)."
                        % (r["skill"] or "a run", r["step_id"] or "a step",
                           r["at"] or "unknown time"),
                "source": "run-records",
                "cites": "run-record:%s" % r["session_id"]}
    died = rec["died_after_last_reflection"]
    if died:
        r = died["run"]
        return {"text": "The last run — %s on %s — %s at %s; no run is live."
                        % (r["skill"] or "a run", r["step_id"] or "a step",
                           r["outcome"], r["at"] or "unknown time"),
                "source": "run-records (last-writer-wins over the %s "
                          "reflection, E9)" % died["reflection_at"],
                "cites": died["cites"],
                "rule": LAST_WRITER_WINS_RULE}
    terminal = [r for r in rec["runs"] if r["terminal"]]
    if terminal:
        r = terminal[-1]
        return {"text": "No run is live. Last run: %s on %s — %s at %s."
                        % (r["skill"] or "a run", r["step_id"] or "a step",
                           r["outcome"], r["at"] or "unknown time"),
                "source": "run-records",
                "cites": "run-record:%s" % r["session_id"]}
    return {"text": "No run has been commissioned yet.",
            "source": "run-records (none on disk)"}


def _next_move_field(rec: dict) -> dict:
    refl = rec["last_reflection"]
    if refl:
        nxt = (refl["reflection"] or {}).get("next")
        directive = (nxt or {}).get("directive") if isinstance(nxt, dict) \
            else None
        if directive:
            return {"text": _first_line(directive),
                    "source": "reflection.next (the existing reflection "
                              "output this projector subscribes to)",
                    "cites": refl["source"]}
    att = rec["attention"]
    if att:
        briefing = att.get("briefing")
        if isinstance(briefing, dict) and briefing.get("next"):
            return {"text": _first_line(briefing["next"]),
                    "source": "attention.briefing.next"}
    for s in rec["steps"]:
        if s["status"] != "done":
            return {"text": "Advance step '%s'." % s["name"],
                    "source": "roadmap_projection (first not-done step)"}
    if rec["steps"]:
        return {"text": "All roadmap steps are done — close or extend the "
                        "campaign.",
                "source": "roadmap_projection"}
    return {"text": None, "source": None}


def precompute_brief(folder, persist: bool = True) -> dict:
    """Derive the situation-brief fields from the reconciled read set and
    (by default) land them in the chamber sidecar. Deterministic; zero spine
    writes; the ONLY write is ``.anchor/chamber/brief.json``."""
    rec = reconcile(folder)
    goal = read_goal_guard(folder)

    fields = {
        "stand": _stand_field(rec),
        "running": _running_field(rec),
        "next_move": _next_move_field(rec),
        "goal_guard": goal,
    }

    pre_emission = rec["last_reflection"] is None
    derivable = bool(rec["steps"] or rec["runs"] or rec["attention"]
                     or rec["last_reflection"])
    degraded = None
    if not derivable:
        # NOTHING to derive from: paint the DRAWN degraded brief — the
        # pre-emission-open row of the W1 amendment batch — never a
        # synthesized narrative.
        degraded = {"state": DEGRADED_BRIEF_STATE,
                    "amendment_ref": PRE_EMISSION_AMENDMENT_REF,
                    "reason": "no-derivable-brief-basis"}
        for key in ("stand", "running", "next_move"):
            fields[key] = {"text": None, "source": None,
                           "degraded": degraded["amendment_ref"]}

    doc = {
        "schema": SCHEMA,
        "as_of": rec["as_of"],
        "pre_emission": pre_emission,
        "degraded": degraded,
        "fields": fields,
        "reconciliation": {
            "rule": LAST_WRITER_WINS_RULE,
            "died_after_last_reflection": rec["died_after_last_reflection"],
            "overrides": rec["overrides"],
            "step_status_counts": rec["step_status_counts"],
        },
    }
    if persist:
        target = brief_path(folder)
        with _cp.file_lock(Path(folder) / BRIEF_LOCK_REL):
            _cp.atomic_write_json(target, doc)
    return doc


def load_brief(folder) -> dict | None:
    """The cached precomputed brief (the open path's read). Missing → None;
    corrupt → a named error dict — readers never write, never repair."""
    p = brief_path(folder)
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {"error": "brief-unreadable"}
    except (ValueError, OSError):
        return {"error": "brief-unreadable"}


def on_reflection_landing(folder) -> dict | None:
    """The reflection-landing subscription (wired into
    ``commission_session.finish_run``): precompute the brief NOW, so the next
    Seal open paints it with zero model calls. Best-effort — a projector
    hiccup never blocks a run finishing; the cold-open rebuild is the cure."""
    try:
        return precompute_brief(folder, persist=True)
    except Exception:
        return None
