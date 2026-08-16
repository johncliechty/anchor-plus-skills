"""The E3 resurrection guard: predicate-required corrections, the one-time
correction-ledger triage, and the handback-blocking positive-containment
diff (steward-chamber W11, C6 — E3; wire-homing row ``findings_ledger``).

**The correction-recording contract (W11 forward):** a correction entry
MUST carry a MACHINE PREDICATE — ``grep`` (regex must/must-not match),
``length`` (min/max bounds), or ``structural`` (required lines / required
JSON keys) — or the EXPLICIT mark :data:`UNASSERTABLE_MARK`
('unassertable — manual review'). :func:`record_correction` REFUSES an
entry with neither (:data:`ERROR_PREDICATE_REQUIRED`): an unassertable
correction is honest by declaration, never by omission.

**The one-time triage (:func:`triage_entries` / the committed record
``chamber/correction-triage.json``):** every EXISTING correction-ledger
entry is classified — an explicit predicate is kept; an entry carrying
mechanical ``must_contain``/``must_not_contain`` text derives a grep
predicate; everything else is DEMOTED to unassertable with the mark. The
predicate-coverage threshold is PUBLISHED
(:data:`PREDICATE_COVERAGE_THRESHOLD`) and every report carries the
demoted remainder by name — never silently blessed.

**The E3 handback interception (:func:`handback_guard`)** sits on the
W2-proven seam: ``commission_session.finish_run`` calls it BEFORE the
ingest bridge reaches Ecgberht ``engine/handback-ingest.mjs ::
ingestHandback / ingestValidatedHandbackBody`` (the seam symbols; the
engine spine is untouched — the guard is chamber code AT the call site).
It evaluates every predicate-bearing correction as a POSITIVE ASSERTION
against the artifact it names in the project tree: a predicate that fails
is a REGRESSION and the handback is BLOCKED with the named finding
:data:`FINDING_E3_REGRESSION`. The unassertable remainder is DEMOTED in
the same report — listed, excluded from the positive count, never counted
as passing.

**The findings-ledger wire (wire-homing row ``findings_ledger``, W11):**
Ecgberht ``engine/step-findings.mjs`` (``appendStepFindings`` /
``findingsForStep``) OWNS the per-step findings store
(``.ecgberht/step-findings.json``, schema ``ecgberht-step-findings-v0``).
This module only READS that store (:func:`read_step_findings_ledger` /
:func:`findings_triage_input`) as the chamber findings surface + E3 triage
input — same schema, same location, characterized against the committed
ledger fixture; nothing is reimplemented and nothing here writes it.

Failure states: corrections store unreadable → the guard FAILS CLOSED
(:data:`ERROR_STORE_UNREADABLE` — a resurrection guard that cannot read
its ledger refuses the handback rather than blessing it blind); a named
artifact missing on disk → that predicate FAILS with the named detail
(absence is a regression of a containment assertion, not a pass);
empty-but-valid → zero corrections guard trivially ``ok`` with an honest
zero-count report.

Stdlib only; no model call, no spawn, no network; the only write is the
chamber-sidecar corrections store.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import chamber_projections as _cp

SCHEMA = "anchor-chamber-corrections-v1"

ANCHOR_ROOT = Path(__file__).resolve().parent

CORRECTIONS_REL = os.path.join(_cp.CHAMBER_SIDECAR_REL, "corrections.json")
CORRECTIONS_LOCK_REL = CORRECTIONS_REL + ".lock"

#: The committed one-time triage record (living artifact).
TRIAGE_RECORD_PATH = ANCHOR_ROOT / "chamber" / "correction-triage.json"
TRIAGE_SCHEMA_VERSION = 1

#: The published predicate-coverage threshold: NEW corrections recorded
#: through the W11 contract must keep predicate coverage at or above this
#: fraction; the legacy remainder rides every report as DEMOTED entries.
PREDICATE_COVERAGE_THRESHOLD = 0.5

PREDICATE_KINDS = ("grep", "length", "structural")

UNASSERTABLE_MARK = "unassertable — manual review"

#: Named findings / errors.
FINDING_E3_REGRESSION = "E3-CORRECTION-REGRESSED-HANDBACK-BLOCKED"
ERROR_PREDICATE_REQUIRED = "predicate-required"
ERROR_STORE_UNREADABLE = "corrections-store-unreadable"
ERROR_BAD_PREDICATE = "predicate-malformed"

#: The Ecgberht findings ledger (OWNED by engine/step-findings.mjs — read
#: here only; the rel path and schema are the owner's constants).
STEP_FINDINGS_REL = os.path.join(".ecgberht", "step-findings.json")
STEP_FINDINGS_SCHEMA = "ecgberht-step-findings-v0"


class CorrectionsStoreError(RuntimeError):
    def __init__(self, error: str, message: str):
        super().__init__(message)
        self.error = error


def store_path(folder) -> Path:
    return Path(folder) / CORRECTIONS_REL


def _lock_path(folder) -> Path:
    return Path(folder) / CORRECTIONS_LOCK_REL


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _empty_store() -> dict:
    return {"schema": SCHEMA, "corrections": []}


def _load(folder) -> dict:
    p = store_path(folder)
    if not p.exists():
        return _empty_store()
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise CorrectionsStoreError(
            ERROR_STORE_UNREADABLE,
            "corrections store unreadable at %s: %s" % (CORRECTIONS_REL, exc))
    if not isinstance(doc, dict) or doc.get("schema") != SCHEMA:
        raise CorrectionsStoreError(
            ERROR_STORE_UNREADABLE,
            "corrections store carries no %r schema" % SCHEMA)
    doc.setdefault("corrections", [])
    return doc


def _save(folder, doc: dict) -> None:
    _cp.atomic_write_json(store_path(folder), doc)


# ═════════════════════════════════════════════════════════════════════════════
# The predicate contract
# ═════════════════════════════════════════════════════════════════════════════

def predicate_problems(pred) -> list:
    """Mechanical validity of ONE predicate. Empty == well-formed."""
    if not isinstance(pred, dict):
        return ["predicate is not an object"]
    kind = pred.get("kind")
    problems = []
    if kind not in PREDICATE_KINDS:
        return ["predicate.kind must be one of %s (got %r)"
                % (", ".join(PREDICATE_KINDS), kind)]
    if kind == "grep":
        pat = pred.get("pattern")
        if not pat or not isinstance(pat, str):
            problems.append("grep predicate needs a non-empty 'pattern'")
        else:
            try:
                re.compile(pat)
            except re.error as exc:
                problems.append("grep pattern does not compile: %s" % exc)
        if not isinstance(pred.get("must_match"), bool):
            problems.append("grep predicate needs boolean 'must_match'")
    elif kind == "length":
        lo, hi = pred.get("min"), pred.get("max")
        if lo is None and hi is None:
            problems.append("length predicate needs 'min' and/or 'max'")
        for name, v in (("min", lo), ("max", hi)):
            if v is not None and not isinstance(v, int):
                problems.append("length.%s must be an integer" % name)
    elif kind == "structural":
        lines = pred.get("required_lines")
        keys = pred.get("required_keys")
        if not lines and not keys:
            problems.append("structural predicate needs 'required_lines' "
                            "and/or 'required_keys'")
        if lines is not None and (
                not isinstance(lines, list)
                or not all(isinstance(x, str) and x.strip() for x in lines)):
            problems.append("structural.required_lines must be non-empty "
                            "strings")
        if keys is not None and (
                not isinstance(keys, list)
                or not all(isinstance(x, str) and x.strip() for x in keys)):
            problems.append("structural.required_keys must be non-empty "
                            "strings")
    return problems


def describe_predicate(pred) -> str:
    kind = (pred or {}).get("kind")
    if kind == "grep":
        return "grep %s /%s/" % (
            "matches" if pred.get("must_match") else "does-not-match",
            pred.get("pattern"))
    if kind == "length":
        return "length in [%s, %s]" % (pred.get("min"), pred.get("max"))
    if kind == "structural":
        bits = []
        if pred.get("required_lines"):
            bits.append("%d required line(s)" % len(pred["required_lines"]))
        if pred.get("required_keys"):
            bits.append("keys %s" % ",".join(pred["required_keys"]))
        return "structural: %s" % "; ".join(bits)
    return "malformed predicate"


def evaluate_predicate(pred, text) -> dict:
    """TOTAL evaluation of one predicate against artifact text →
    ``{holds, detail}``. Deterministic; a malformed predicate never holds
    (it FAILS with the named reason — never a silent pass)."""
    problems = predicate_problems(pred)
    if problems:
        return {"holds": False, "detail": "%s: %s"
                % (ERROR_BAD_PREDICATE, "; ".join(problems))}
    body = str(text if text is not None else "")
    kind = pred["kind"]
    if kind == "grep":
        hit = re.search(pred["pattern"], body) is not None
        holds = hit if pred["must_match"] else not hit
        return {"holds": holds,
                "detail": "pattern %s (%s expected)"
                          % ("matched" if hit else "did not match",
                             "match" if pred["must_match"] else "no match")}
    if kind == "length":
        n = len(body)
        lo, hi = pred.get("min"), pred.get("max")
        holds = (lo is None or n >= lo) and (hi is None or n <= hi)
        return {"holds": holds, "detail": "length %d vs [%s, %s]"
                                          % (n, lo, hi)}
    # structural
    missing_lines = [ln for ln in (pred.get("required_lines") or [])
                     if ln not in body.splitlines()]
    missing_keys = []
    if pred.get("required_keys"):
        try:
            parsed = json.loads(body)
        except ValueError:
            missing_keys = list(pred["required_keys"])
        else:
            top = parsed if isinstance(parsed, dict) else {}
            missing_keys = [k for k in pred["required_keys"] if k not in top]
    holds = not missing_lines and not missing_keys
    detail = "structure intact" if holds else (
        "missing line(s): %s; missing key(s): %s"
        % (missing_lines[:3], missing_keys[:6]))
    return {"holds": holds, "detail": detail}


def correction_problems(entry) -> list:
    """The recording contract on ONE entry. Empty == recordable."""
    if not isinstance(entry, dict):
        return ["correction is not an object"]
    problems = []
    if not str(entry.get("id") or "").strip():
        problems.append("correction needs an 'id'")
    if not str(entry.get("text") or "").strip():
        problems.append("correction needs the correction 'text'")
    pred = entry.get("predicate")
    unassertable = entry.get("unassertable") is True
    if pred is None and not unassertable:
        problems.append(
            "%s: a correction carries a machine predicate (grep/length/"
            "structural) or the explicit mark %r — neither is present"
            % (ERROR_PREDICATE_REQUIRED, UNASSERTABLE_MARK))
    if unassertable and entry.get("mark") != UNASSERTABLE_MARK:
        problems.append("an unassertable correction must carry mark == %r"
                        % UNASSERTABLE_MARK)
    if pred is not None:
        problems.extend(predicate_problems(pred))
        if not str(entry.get("artifact_rel") or "").strip():
            problems.append("a predicate-bearing correction names the "
                            "'artifact_rel' it asserts over")
    return problems


def record_correction(folder, entry: dict) -> dict:
    """Record one correction UNDER THE CONTRACT — refused by name when the
    predicate is absent and the unassertable mark is not explicit."""
    problems = correction_problems(entry)
    if problems:
        return {"ok": False, "error": ERROR_PREDICATE_REQUIRED
                if any(ERROR_PREDICATE_REQUIRED in p for p in problems)
                else "correction-malformed",
                "problems": problems}
    row = dict(entry)
    row["recorded_at"] = _now()
    with _cp.file_lock(_lock_path(folder)):
        try:
            doc = _load(folder)
        except CorrectionsStoreError as exc:
            return {"ok": False, "error": exc.error, "message": str(exc)}
        doc["corrections"] = [c for c in doc["corrections"]
                              if c.get("id") != row["id"]] + [row]
        _save(folder, doc)
    return {"ok": True, "correction": row}


def list_corrections(folder) -> list:
    try:
        doc = _load(folder)
    except CorrectionsStoreError:
        return []
    return [dict(c) for c in doc.get("corrections") or []]


# ═════════════════════════════════════════════════════════════════════════════
# The one-time triage (existing entries → kept / derived / demoted)
# ═════════════════════════════════════════════════════════════════════════════

def triage_entries(entries) -> dict:
    """Classify EVERY existing correction-ledger entry, mechanically:

    * an explicit well-formed ``predicate`` is KEPT;
    * an entry carrying ``must_contain`` / ``must_not_contain`` text
      DERIVES a grep predicate (the two mechanical derivation rules);
    * everything else is DEMOTED to unassertable with the explicit mark.

    Returns the triage record: per-entry outcomes + the coverage numbers
    against the PUBLISHED threshold. Never silent: every demotion is a
    named row."""
    kept, derived, demoted = [], [], []
    out_entries = []
    for e in entries or []:
        e = dict(e or {})
        eid = str(e.get("id") or "unidentified")
        pred = e.get("predicate")
        if pred is not None and not predicate_problems(pred):
            kept.append(eid)
            out_entries.append(e)
            continue
        mc, mnc = e.get("must_contain"), e.get("must_not_contain")
        if isinstance(mc, str) and mc.strip():
            e["predicate"] = {"kind": "grep", "pattern": re.escape(mc),
                              "must_match": True}
            e["predicate_derived_by"] = "triage-rule:must_contain"
            derived.append(eid)
            out_entries.append(e)
            continue
        if isinstance(mnc, str) and mnc.strip():
            e["predicate"] = {"kind": "grep", "pattern": re.escape(mnc),
                              "must_match": False}
            e["predicate_derived_by"] = "triage-rule:must_not_contain"
            derived.append(eid)
            out_entries.append(e)
            continue
        e.pop("predicate", None)
        e["unassertable"] = True
        e["mark"] = UNASSERTABLE_MARK
        demoted.append(eid)
        out_entries.append(e)
    total = len(out_entries)
    bearing = len(kept) + len(derived)
    coverage = (bearing / total) if total else 1.0
    return {
        "schema": SCHEMA,
        "total": total,
        "predicate_bearing": bearing,
        "kept": kept,
        "derived": derived,
        "demoted_unassertable": demoted,
        "coverage": round(coverage, 4),
        "threshold": PREDICATE_COVERAGE_THRESHOLD,
        "meets_threshold": coverage >= PREDICATE_COVERAGE_THRESHOLD,
        "entries": out_entries,
    }


def load_triage_record(path=None) -> dict:
    p = Path(path) if path else TRIAGE_RECORD_PATH
    return json.loads(p.read_text(encoding="utf-8"))


# ═════════════════════════════════════════════════════════════════════════════
# The E3 handback guard (the interception on the W2-proven seam)
# ═════════════════════════════════════════════════════════════════════════════

def _artifact_text(folder, rel) -> tuple:
    """→ ``(text, error)``. Containment first: '..', absolute, and drive
    paths are refused; a missing artifact is a NAMED absence (a positive
    containment assertion over a vanished artifact has regressed)."""
    r = str(rel or "").strip()
    if not r or r.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", r) \
            or ".." in re.split(r"[\\/]+", r):
        return None, "artifact_rel refused (containment): %r" % r[:120]
    p = Path(folder) / r
    if not p.is_file():
        return None, "named artifact absent: %s" % r
    try:
        return p.read_text(encoding="utf-8", errors="replace"), None
    except OSError as exc:
        return None, "named artifact unreadable: %s (%s)" % (r, exc)


def coverage_report(folder) -> dict:
    """The honest E3 report shape EVERY surface uses: the positive
    assertions with their current holds, and the unassertable remainder
    DEMOTED BY NAME — present in every report, never blessed."""
    try:
        doc = _load(folder)
    except CorrectionsStoreError as exc:
        return {"ok": False, "error": exc.error}
    assertions, demoted = [], []
    for c in doc.get("corrections") or []:
        if c.get("predicate") is not None:
            text, err = _artifact_text(folder, c.get("artifact_rel"))
            if err is not None:
                verdict = {"holds": False, "detail": err}
            else:
                verdict = evaluate_predicate(c["predicate"], text)
            assertions.append({
                "id": c.get("id"),
                "artifact_rel": c.get("artifact_rel"),
                "asserted": describe_predicate(c["predicate"]),
                "holds": bool(verdict["holds"]),
                "detail": verdict["detail"],
            })
        else:
            demoted.append({"id": c.get("id"),
                            "mark": c.get("mark") or UNASSERTABLE_MARK})
    total = len(assertions) + len(demoted)
    coverage = (len(assertions) / total) if total else 1.0
    return {
        "ok": True,
        "schema": SCHEMA,
        "total": total,
        "assertions": assertions,
        "demoted_unassertable": demoted,
        "coverage": round(coverage, 4),
        "threshold": PREDICATE_COVERAGE_THRESHOLD,
        "meets_threshold": coverage >= PREDICATE_COVERAGE_THRESHOLD,
    }


def handback_guard(folder) -> dict:
    """THE E3 INTERCEPTION — called by ``commission_session.finish_run``
    BEFORE the ingest bridge (the W2-proven ``ingestHandback`` /
    ``ingestValidatedHandbackBody`` seam) on every resumed/re-briefed
    rewrite's handback.

    Every predicate-bearing correction is a POSITIVE ASSERTION evaluated
    against the artifact it names in the project tree. Any assertion that
    FAILS is a regression: ``{"ok": False, "finding":
    FINDING_E3_REGRESSION, "regressions": [...]}`` — the handback is
    BLOCKED with the named finding. FAILS CLOSED on an unreadable store.
    Zero corrections → trivially ok with the honest zero report."""
    report = coverage_report(folder)
    if not report.get("ok"):
        return {"ok": False, "blocked": True,
                "finding": FINDING_E3_REGRESSION,
                "error": report.get("error"),
                "message": "the corrections store is unreadable — the E3 "
                           "guard fails CLOSED rather than bless a "
                           "handback blind"}
    regressions = [a for a in report["assertions"] if not a["holds"]]
    if regressions:
        return {
            "ok": False, "blocked": True,
            "finding": FINDING_E3_REGRESSION,
            "regressions": regressions,
            "report": report,
            "message": "handback blocked: %d positive containment "
                       "assertion(s) regressed (%s) — fix the regression "
                       "or re-record the correction; the unassertable "
                       "remainder stays demoted, not blessed"
                       % (len(regressions),
                          ", ".join(str(r["id"]) for r in regressions[:5])),
        }
    return {"ok": True, "blocked": False, "report": report}


# ═════════════════════════════════════════════════════════════════════════════
# The findings-ledger READ wire (owner: engine/step-findings.mjs)
# ═════════════════════════════════════════════════════════════════════════════

def step_findings_path(project_path) -> Path:
    return Path(project_path) / STEP_FINDINGS_REL


def read_step_findings_ledger(project_path) -> dict:
    """READ the owner's store — same rel path, same schema envelope as
    ``engine/step-findings.mjs :: readStepFindings`` (missing →
    empty-but-valid; corrupt → honest named unknown). Never writes."""
    p = step_findings_path(project_path)
    if not p.is_file():
        return {"ok": True, "exists": False, "steps": {}}
    try:
        parsed = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return {"ok": False, "error": "step_findings_unreadable",
                "detail": str(exc)[:200], "steps": {}}
    return {"ok": True, "exists": True,
            "schema": parsed.get("schema"),
            "steps": parsed.get("steps") or {}}


def findings_for_step(project_path, step_id) -> list:
    """Mirror of the owner's ``findingsForStep`` READ contract (newest
    last; empty when none/unreadable) — the chamber findings surface."""
    read = read_step_findings_ledger(project_path)
    if not read.get("ok"):
        return []
    rows = read["steps"].get(str(step_id))
    return list(rows) if isinstance(rows, list) else []


def findings_triage_input(project_path) -> list:
    """The E3 triage input off the findings ledger: every finding row
    flattened to a triage-shaped entry (id, text, source) — corrections
    recorded as step findings ride the same one-time triage."""
    read = read_step_findings_ledger(project_path)
    out = []
    for step_id, rows in sorted((read.get("steps") or {}).items()):
        for i, r in enumerate(rows if isinstance(rows, list) else []):
            out.append({"id": "%s/%d" % (step_id, i),
                        "text": (r or {}).get("finding"),
                        "source": (r or {}).get("source"),
                        "step_id": step_id})
    return out
