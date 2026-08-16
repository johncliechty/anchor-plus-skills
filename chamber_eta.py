"""Per-skill rolling-median ETA module (steward-chamber W7, C2).

The plan's words: *per-skill rolling-median ETA module over the project's own
run records, n>=3 guard, drawn 'no history yet' fallback, labeled basis.*

* **The data** — the project's OWN run records (``.anchor/commission-runs``):
  each TERMINAL record with a numeric ``elapsed_s`` contributes one duration
  to its skill's history. Nothing external, nothing guessed.
* **Rolling median** — per skill, the median of the most recent
  :data:`ROLLING_WINDOW` durations (recency-ordered by the record's ``at``).
* **The n>=3 guard** — a skill with fewer than :data:`MIN_RUNS` recorded
  durations gets the DRAWN zero-history presentation (AG-ZERO-HISTORY-ETA,
  signed in the W1 batched amendment gate): ``first run — no ETA yet`` at
  n==0, ``gathering history (N of 3 runs)`` at n in {1,2} — never a
  one-record extrapolation.
* **Labeled basis** — every rendered estimate names its basis
  (``median of N runs``); the campaign line is labeled ``per-skill
  medians``. An unlabeled number is a defect by plan.

Deterministic (no wall clock — the Seal-open view must compare equal across
two opens) and read-bounded: callers on the open path hand in rows they
already read plus an explicit remaining read budget; this module never reads
past it (the W6 200-read backstop stays whole-open).

Stdlib only. Read-only.
"""
from __future__ import annotations

import json
from pathlib import Path

import chamber_reconcile as cr

#: The n>=3 guard (AG-ZERO-HISTORY-ETA: "gathering history (N of 3 runs)").
MIN_RUNS = 3

#: Rolling window: the median runs over at most this many most-recent
#: durations per skill (rolling, not lifetime — old runs age out).
ROLLING_WINDOW = 8

STATE_OK = "ok"
STATE_NO_HISTORY = "no-history"

#: The signed drawn presentation this module's fallback maps to.
ZERO_HISTORY_AMENDMENT_REF = "AG-ZERO-HISTORY-ETA"

#: Drawn zero-history texts (mockups.html §amendments, AG-ZERO-HISTORY-ETA).
LABEL_FIRST_RUN = "first run — no ETA yet"


def _label_gathering(n: int) -> str:
    return "gathering history (%d of %d runs)" % (n, MIN_RUNS)


# ── Durations ────────────────────────────────────────────────────────────────

def _norm_skill(skill) -> str | None:
    s = str(skill or "").strip().lower()
    return s or None


def durations_from_rows(rows) -> dict:
    """``{skill_lower: [elapsed_s, ...]}`` (recency-ascending) from normalized
    run-record rows (the ``chamber_reconcile.read_run_records`` /
    ``chamber_open.read_run_records_capped`` shape). Only TERMINAL records
    with a numeric ``elapsed_s`` count — a live run has no duration yet."""
    by_skill: dict = {}
    ordered = sorted((r for r in rows if isinstance(r, dict)),
                     key=lambda r: (str(r.get("at") or ""),
                                    str(r.get("session_id") or "")))
    for r in ordered:
        skill = _norm_skill(r.get("skill"))
        el = r.get("elapsed_s")
        if not skill or r.get("outcome") == cr.OUTCOME_LIVE:
            continue
        if not isinstance(el, (int, float)) or isinstance(el, bool) or el < 0:
            continue
        by_skill.setdefault(skill, []).append(float(el))
    return by_skill


def collect_durations(folder, *, already_rows=None, read_budget=None) -> dict:
    """Durations for a project, read-BOUNDED.

    ``already_rows`` are run-record rows the caller already read (the open
    path's capped candidates) — reused, never re-read. ``read_budget`` is how
    many ADDITIONAL record files this call may read (``None`` = unbounded,
    for off-open callers like the CLI/tests); files newest-first so the
    rolling window fills from recency. Returns::

        {"by_skill": {skill: [s, ...]}, "extra_reads": int,
         "skipped_for_budget": int}
    """
    rows = list(already_rows or [])
    seen = {str(r.get("session_id")) for r in rows if isinstance(r, dict)}
    root = Path(folder) / cr.RUN_RECORDS_REL
    files = sorted(root.glob("*.json"), reverse=True) if root.is_dir() else []
    extra, skipped = 0, 0
    for f in files:
        if f.stem in seen:
            continue
        if read_budget is not None and extra >= read_budget:
            skipped += 1
            continue
        extra += 1
        try:
            rec = json.loads(f.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        if not isinstance(rec, dict):
            continue
        rows.append({
            "session_id": rec.get("session_id") or f.stem,
            "skill": rec.get("skill"),
            "outcome": rec.get("outcome"),
            "at": rec.get("at") or "",
            "elapsed_s": (rec.get("elapsed_s")
                          if isinstance(rec.get("elapsed_s"), (int, float))
                          else None),
        })
    return {"by_skill": durations_from_rows(rows), "extra_reads": extra,
            "skipped_for_budget": skipped}


# ── Medians ──────────────────────────────────────────────────────────────────

def _median(values: list) -> float:
    vals = sorted(values)
    n = len(vals)
    mid = n // 2
    if n % 2:
        return float(vals[mid])
    return (vals[mid - 1] + vals[mid]) / 2.0


def skill_eta(by_skill: dict, skill) -> dict:
    """The rolling-median ETA for one skill, guarded at n>=3.

    Returns::

        {"skill", "n", "state": "ok"|"no-history", "eta_s"|None,
         "basis"|None, "label", "amendment_ref"?}

    ``label`` is ALWAYS render-ready: the labeled basis at n>=3 (e.g.
    ``est ~18m (median of 6 runs)``), the drawn zero-history text below it.
    """
    key = _norm_skill(skill)
    history = list((by_skill or {}).get(key) or []) if key else []
    window = history[-ROLLING_WINDOW:]
    n = len(window)
    if key is None or n == 0:
        # No skill resolved, or a first run: the drawn first-run face.
        return {"skill": key, "n": 0, "state": STATE_NO_HISTORY,
                "eta_s": None, "basis": None, "label": LABEL_FIRST_RUN,
                "amendment_ref": ZERO_HISTORY_AMENDMENT_REF}
    if n < MIN_RUNS:
        return {"skill": key, "n": n, "state": STATE_NO_HISTORY,
                "eta_s": None, "basis": None, "label": _label_gathering(n),
                "amendment_ref": ZERO_HISTORY_AMENDMENT_REF}
    eta = _median(window)
    basis = "median of %d runs" % n
    return {"skill": key, "n": n, "state": STATE_OK, "eta_s": eta,
            "basis": basis,
            "label": "est %s (%s)" % (format_duration(eta), basis)}


def campaign_eta(steps, by_skill: dict) -> dict:
    """The campaign ETA over the REMAINING (not-done) rail steps.

    Honest by construction: the summed estimate renders ONLY when every
    remaining step resolves a skill with n>=3 history; any gap degrades the
    WHOLE line to the drawn zero-history presentation (never a partial sum
    passed off as the campaign). Returns::

        {"state": "ok"|"no-history"|"idle", "total_s"|None, "label",
         "per_step": {step_id: skill_eta-dict}, "basis"?}
    """
    remaining = [s for s in (steps or [])
                 if isinstance(s, dict) and s.get("status") != "done"]
    if not remaining:
        return {"state": "idle", "total_s": None, "per_step": {},
                "label": "campaign complete"}
    per_step: dict = {}
    total = 0.0
    best_n = 0
    all_ok = True
    for s in remaining:
        row = skill_eta(by_skill, s.get("skill"))
        per_step[s.get("id")] = row
        best_n = max(best_n, row["n"])
        if row["state"] == STATE_OK:
            total += row["eta_s"]
        else:
            all_ok = False
    if all_ok:
        return {"state": STATE_OK, "total_s": total, "per_step": per_step,
                "basis": "per-skill medians",
                "label": "campaign est ~%s left (per-skill medians)"
                         % format_duration(total).lstrip("~")}
    label = ("campaign est — gathering history (%d of %d runs)"
             % (best_n, MIN_RUNS)) if best_n else \
        "campaign est — gathering history"
    return {"state": STATE_NO_HISTORY, "total_s": None, "per_step": per_step,
            "label": label, "amendment_ref": ZERO_HISTORY_AMENDMENT_REF}


# ── Formatting ───────────────────────────────────────────────────────────────

def format_duration(seconds) -> str:
    """``~45s`` / ``~18m`` / ``~1h`` / ``~2h05m`` — the mockup's idiom."""
    try:
        s = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        return "~?"
    if s < 60:
        return "~%ds" % s
    minutes = int(round(s / 60.0))
    if minutes < 60:
        return "~%dm" % minutes
    h, m = divmod(minutes, 60)
    if m == 0:
        return "~%dh" % h
    return "~%dh%02dm" % (h, m)
