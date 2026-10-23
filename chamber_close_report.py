"""Campaign-close reports (steward-chamber W12): the honestly-bounded E1
and E3 enforcement reports + the ease close report (C8).

Law — HONESTY OVER FLATTERY, mechanically:

* Every number in these reports derives from a COMMITTED input (the
  correction-triage record, the master-plan baseline, the instrument scans
  below). Nothing is estimated, tuned, or fabricated at generation time; a
  fact the tree cannot ground is reported ABSENT by name, never invented.
* The builders are DETERMINISTIC over the tree (no clocks, no randomness),
  so `tests/test_chamber_close_reports_w12.py` can assert the committed
  artifacts equal a fresh regeneration — a drifted report fails CI.
* The E1 report is honestly VACUOUS: the W3/W8 E1 instrument stack (the
  pre-registered bound parser, the F7 ratification artifact, the steward
  turn-completion hook, the W8 joint negative-path test) was recorded
  absent from the tree by W10's traceability note, and the scans below
  re-verify that absence mechanically. "Agreed out-of-bound misses of the
  ratified parse" cannot exist without a ratified parse — the report says
  exactly that and names the gap as a plan defect for John.
* The ease report ships the C8 fallback the plan itself pre-authorizes:
  with no frozen classifier of record and no in-tree reference-session
  transcript, the 5->0 numeric comparison is DESCRIPTIVE ONLY and the
  verdict falls back to John's one-pass audit alone.

Stdlib only. Read-only except :func:`write_reports` (which writes the three
committed artifacts under ``chamber/``).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ANCHOR_ROOT = Path(__file__).resolve().parent
CHAMBER_DIR = ANCHOR_ROOT / "chamber"

E1_REPORT_PATH = CHAMBER_DIR / "E1-ENFORCEMENT-REPORT.md"
E3_REPORT_PATH = CHAMBER_DIR / "E3-ENFORCEMENT-REPORT.md"
EASE_REPORT_PATH = CHAMBER_DIR / "EASE-CLOSE-REPORT.md"
TRIAGE_RECORD_PATH = CHAMBER_DIR / "correction-triage.json"

#: The Stage-2 baseline the master plan locks (C8): John's interface-caused
#: overhead messages in the Fable-driver reference session, trending 5->0.
STAGE2_BASELINE = "5->0"

GENERATION_TAG = "steward-chamber W12 (Phase-4 Close)"


def _ecgberht_root() -> Path:
    import paths as _paths
    return _paths.ecgberht_root()


# ═════════════════════════════════════════════════════════════════════════════
# Instrument scans (mechanical presence probes — never a guess)
# ═════════════════════════════════════════════════════════════════════════════

def _chamber_sources() -> list:
    return sorted(ANCHOR_ROOT.glob("chamber_*.py"))


def _any_source_contains(tokens, files=None) -> bool:
    for p in (files if files is not None else _chamber_sources()):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if any(tok in text for tok in tokens):
            return True
    return False


def e1_instrument_scan(root: Path | None = None,
                       ecg_root: Path | None = None) -> dict:
    """Mechanical probes for every leg of the E1 stack. Each probe answers
    present/absent from the tree — the report cites these, never a vibe."""
    root = Path(root) if root else ANCHOR_ROOT
    ecg = Path(ecg_root) if ecg_root else _ecgberht_root()
    self_name = Path(__file__).name
    sources = [p for p in sorted(root.glob("chamber_*.py"))
               if p.name != self_name]

    parser_present = _any_source_contains(
        ("answer_reference", "answer-reference", "parse_direct_questions"),
        files=sources)

    ratification_files = [p.name for p in sorted(CHAMBER_DIR.iterdir())
                          if p.is_file() and re.search(
                              r"(e1[-_]bound|ratif)", p.name, re.IGNORECASE)]

    # John's F7 signature, read through the bound's own fail-closed reader
    # (steward-e1 W1). Absent module or artifact -> unsigned, never
    # permissive.
    ratification_signed = False
    try:
        import chamber_e1_bound as _e1b
        ratification_signed = bool(_e1b.ratification_state().get("signed"))
    except Exception:
        ratification_signed = False

    hook_present = False
    conv = ecg / "engine" / "steward-conversation.mjs"
    if conv.is_file():
        try:
            text = conv.read_text(encoding="utf-8", errors="replace")
            hook_present = ("answer_reference" in text
                            or "unanswered question" in text)
        except OSError:
            pass

    w8_tests = [p.name for p in sorted((root / "tests").glob(
        "test_chamber_*w8*.py"))]

    return {
        "bound_parser_landed": parser_present,
        "ratification_artifact_files": ratification_files,
        "ratification_artifact_landed": bool(ratification_files),
        "ratification_signed": ratification_signed,
        "turn_completion_hook_landed": hook_present,
        "w8_negative_path_test_files": w8_tests,
        "w8_negative_path_test_landed": bool(w8_tests),
        "stack_complete": (parser_present and bool(ratification_files)
                           and hook_present and bool(w8_tests)),
    }


def ease_instrument_scan(root: Path | None = None) -> dict:
    """Mechanical probes for the C8 ease stack: the pre-registered frozen
    classifier (W3), the live say-box classification ledger (W8), the V6
    per-turn latency log, and an in-tree reference-session transcript."""
    root = Path(root) if root else ANCHOR_ROOT
    self_name = Path(__file__).name
    sources = [p for p in sorted(root.glob("chamber_*.py"))
               if p.name != self_name]

    classifier_present = _any_source_contains(
        ("classify_ease", "EASE_RULES", "ease_classifier"), files=sources)
    ledger_present = _any_source_contains(
        ("ease_event", "ease_ledger", "record_ease", '"ease"'),
        files=[root / "chamber_projections.py"])
    latency_log_present = _any_source_contains(
        ("spoken_turn_latency", "say_latency"), files=sources)
    fixtures = root / "tests" / "fixtures" / "chamber"
    transcript_candidates = []
    if fixtures.is_dir():
        transcript_candidates = [str(p.relative_to(root)).replace("\\", "/")
                                 for p in fixtures.rglob("*transcript*")]
    return {
        "frozen_classifier_landed": classifier_present,
        "live_ease_ledger_landed": ledger_present,
        "latency_log_landed": latency_log_present,
        "reference_transcript_in_tree": bool(transcript_candidates),
        "reference_transcript_candidates": transcript_candidates,
    }


# ═════════════════════════════════════════════════════════════════════════════
# E1 — enforcement report (honestly vacuous while the stack is absent)
# ═════════════════════════════════════════════════════════════════════════════

def build_e1_report(root: Path | None = None,
                    ecg_root: Path | None = None) -> str:
    scan = e1_instrument_scan(root=root, ecg_root=ecg_root)
    lines = [
        "# E1 enforcement report — %s" % GENERATION_TAG,
        "",
        "**Criterion (E1):** a steward turn structurally CANNOT close while",
        "a ratified direct question id lacks a typed answer-reference; the",
        "status table + footer inject on the telemetry clock with zero model",
        "involvement.",
        "",
        "## Instrument scan (mechanical, re-runnable)",
        "",
        "| Leg (home wave) | Present in tree |",
        "|-----------------|-----------------|",
        "| W3 pre-registered E1 bound parser | %s |"
        % ("YES" if scan["bound_parser_landed"] else "NO"),
        "| F7 ratification artifact (John's bound) | %s |"
        % ("YES: " + ", ".join(scan["ratification_artifact_files"])
           if scan["ratification_artifact_landed"] else "NO"),
        "| F7 ratification SIGNED by John | %s |"
        % ("YES" if scan["ratification_signed"] else "NO"),
        "| W8 steward turn-completion hook (engine seam) | %s |"
        % ("YES" if scan["turn_completion_hook_landed"] else "NO"),
        "| W8 joint negative-path test | %s |"
        % ("YES: " + ", ".join(scan["w8_negative_path_test_files"])
           if scan["w8_negative_path_test_landed"] else "NO"),
        "",
    ]
    if scan["stack_complete"] and scan["ratification_signed"]:
        # steward-e1 W2, post-signature: the RATIFIED bound is the
        # enforcement bound — its agreed out-of-bound misses enumerate
        # from the signed F7 disposition table (never re-guessed here).
        try:
            import chamber_e1_bound as _e1b
            dispositions = _e1b.ratification_state().get("dispositions", {})
        except Exception:
            dispositions = {}
        misses = sorted(rid for rid, label in dispositions.items()
                        if label == "KNOWN-MISS")
        lines += [
            "## Enforcement bound — RATIFIED and ENGINE-ENFORCED",
            "",
            "All four legs are present and John's F7 signature is on disk:",
            "the turn-completion hook structurally blocks a steward turn",
            "from closing while a ratified direct question id lacks a typed",
            "answer-reference (finding E1-TURN-CLOSE-BLOCKED). The agreed",
            "out-of-bound misses of the ratified parse, from the signed F7",
            "disposition table:",
            "",
        ]
        lines += ["* `%s`" % rid for rid in misses] \
            or ["(none recorded — regenerate after verifying the artifact)"]
        lines += [
            "",
            "The telemetry half (the ⏱ table + campaign footer injecting on",
            "the telemetry clock from the re-homed run_pulse emitter, zero",
            "model involvement) is proven at its seam by the same W8 suite",
            "with a zero-model-call trace.",
        ]
    elif scan["stack_complete"]:
        # steward-e1 W2 state: all four instrument legs are in the tree;
        # John's F7 signature is not yet on disk — enforcement is ARMED but
        # fails CLOSED by name until the signature exists.
        lines += [
            "## Enforcement bound — LANDED, ARMED AT THE SIGNATURE",
            "",
            "All four instrument legs are present (scan above): the",
            "deterministic bound parser, the F7 ratification artifact, the",
            "steward turn-completion hook on the W2-proven converse seam",
            "(both legs: the engine's enforceTurnCompletion and the",
            "bridge-boundary enforce_bridge_result), and the joint",
            "negative-path test. The bound is NOT yet ratified — John's",
            "signature is not on disk — so the hook fails CLOSED by name",
            "(E1-BOUND-UNRATIFIED / E1-F7-ARTIFACT-MISSING): every",
            "turn-close verdict carries the named finding, no turn is",
            "blocked against an unsigned bound, and an unenforceable bound",
            "never degrades to permissive (never silently open).",
            "",
            "**Consequence, stated plainly:** the machinery that",
            "structurally blocks a steward turn from closing on an",
            "unanswered ratified question is in the tree and proven at its",
            "seam; it ENFORCES only once chamber/E1-BOUND-RATIFICATION.md",
            "carries John's signature. The telemetry half (the ⏱ table +",
            "campaign footer injecting on the telemetry clock from the",
            "re-homed run_pulse emitter, zero model involvement) is proven",
            "at its seam by the same W8 suite with a zero-model-call trace.",
            "",
            "**Disposition:** John's F7 signature arms enforcement; the",
            "agreed out-of-bound misses then become this report's",
            "enforcement bound (regenerate on signing). The V5 blocked-turn",
            "drawn state + the ordered transcript-link row await his ONE",
            "batched signature in chamber/MOCKUP-AMENDMENT-GATE-W2.md; the",
            "C9 re-pin follows that signature, never precedes it.",
        ]
    elif scan["bound_parser_landed"] and scan["ratification_artifact_landed"]:
        # steward-e1 W1 state: the parser + F7 artifact are in the tree,
        # the signature and the Wave-2 enforcement legs are not.
        lines += [
            "## Enforcement bound — HONESTLY VACUOUS",
            "",
            "There are ZERO agreed out-of-bound misses because there is NO",
            "ratified parse YET: the steward-e1 W1 legs are in the tree",
            "(the deterministic bound parser + the F7 ratification",
            "artifact, prepared UNSIGNED), but John's signature is not on",
            "disk and the Wave-2 enforcement legs (the steward",
            "turn-completion hook, the joint negative-path test) are",
            "absent (scan above). W10's traceability note recorded the",
            "original all-absent gap; the W12 audit named it a plan defect",
            "for John; steward-e1 is the funded re-execution of exactly",
            "that defect.",
            "",
            "**Consequence, stated plainly:** E1 is NOT engine-enforced in",
            "the assembled system. A steward turn CAN close on an",
            "unanswered direct question today. Convention (the seat",
            "prompt's one-question rule) is the only cover until Wave 2",
            "wires the RATIFIED bound structural.",
            "",
            "**Disposition:** Wave 1 ends AT the F7 ratification HALT by",
            "design — the bound is in front of John in",
            "chamber/E1-BOUND-RATIFICATION.md. Wave 2 may enforce ONLY a",
            "bound that record carries SIGNED; unsigned or absent, the",
            "turn-completion hook fails CLOSED by name",
            "(E1-BOUND-UNRATIFIED / E1-F7-ARTIFACT-MISSING).",
        ]
    else:
        lines += [
            "## Enforcement bound — HONESTLY VACUOUS",
            "",
            "There are ZERO agreed out-of-bound misses because there is NO",
            "ratified parse: the E1 instrument stack never landed. W10's",
            "traceability note recorded the gap first (chamber/",
            "traceability-matrix.json :: w3_note); the W12 audit re-verified",
            "it mechanically (scan above). The F7 ratification HALT never",
            "fired because the parser it ratifies does not exist.",
            "",
            "**Consequence, stated plainly:** E1 is NOT engine-enforced in",
            "the assembled system. A steward turn CAN close on an unanswered",
            "direct question today. Convention (the seat prompt's",
            "one-question rule) is the only cover — exactly the failure",
            "class the master plan's Enforcement-Honesty table warns about.",
            "",
            "**Disposition:** plan defect, routed to John with the W12",
            "close (chamber/W12-AUDIT-REPORT.md carries the named finding).",
            "Building the stack now would first-exercise a criterion in the",
            "close-out wave, which the plan itself defines as a defect —",
            "the decision (fund an E1 wave / re-scope E1 / accept the loss)",
            "is John's, not this audit's.",
        ]
    lines.append("")
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
# E3 — enforcement report (real numbers from the committed triage record)
# ═════════════════════════════════════════════════════════════════════════════

def load_triage_record(path: Path | None = None) -> dict:
    p = Path(path) if path else TRIAGE_RECORD_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def build_e3_report(root: Path | None = None) -> str:
    import chamber_corrections as cc
    record = load_triage_record()
    threshold = cc.PREDICATE_COVERAGE_THRESHOLD
    lines = [
        "# E3 enforcement report — %s" % GENERATION_TAG,
        "",
        "**Criterion (E3):** a resumed/re-briefed rewrite that regresses a",
        "predicate-bearing correction CANNOT hand back; unassertable entries",
        "are honestly demoted in every report.",
        "",
        "## Published predicate-coverage threshold",
        "",
        "`PREDICATE_COVERAGE_THRESHOLD = %s` (code-owned in"
        % ("%g" % threshold),
        "`chamber_corrections.py`; the committed record",
        "`chamber/correction-triage.json` must match — divergence fails the",
        "W11 suite).",
        "",
        "## The one-time triage: every unassertable NAMED",
        "",
    ]
    if record.get("published_threshold") != threshold:
        lines += ["**MISMATCH:** the committed record's threshold (%r) does"
                  % record.get("published_threshold"),
                  "not equal the code-owned value — fix before trusting the",
                  "numbers below.", ""]
    for src in record.get("triaged_sources", []):
        lines.append("### %s" % src.get("source"))
        lines.append("")
        outcomes = src.get("outcomes")
        if outcomes:
            lines.append("| Entry | Outcome | Why |")
            lines.append("|-------|---------|-----|")
            for o in outcomes:
                lines.append("| %s | %s | %s |"
                             % (o.get("id"), o.get("outcome"),
                                str(o.get("why") or "").replace("|", "/")))
            lines.append("")
            lines.append("kept %s · derived %s · demoted %s · coverage %s"
                         % (src.get("kept"), src.get("derived"),
                            src.get("demoted"), src.get("coverage")))
        else:
            lines.append(str(src.get("note") or "(no outcome rows)"))
        lines.append("")
    lines += [
        "## The live guard (engine-enforced from W11 forward)",
        "",
        "* `chamber_corrections.record_correction` REFUSES an entry with",
        "  neither a machine predicate nor the explicit mark",
        "  `%s` — the store only gains assertable entries."
        % cc.UNASSERTABLE_MARK,
        "* `chamber_corrections.handback_guard` blocks a handback whose",
        "  rewrite regresses any predicate-bearing correction (named",
        "  finding), FAILS CLOSED on an unreadable store, and lists the",
        "  demoted remainder in EVERY report — never silently blessed.",
        "* Re-verified end-to-end in this wave:",
        "  `tests/test_chamber_cross_audit_w12.py` re-runs the W11",
        "  handback-block negative path against the live seams.",
        "",
        "**Honesty line:** legacy coverage is %s — all %d pre-existing"
        % (record.get("triaged_sources", [{}])[0].get("coverage", "0.0"),
           int(record.get("triaged_sources", [{}])[0].get("demoted", 0) or 0)),
        "fix-item entries are prose and stand DEMOTED by name above. The",
        "threshold binds the live store going forward, not the demoted",
        "remainder.",
        "",
    ]
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
# C8 — the ease close report (frozen-classifier law, honest fallback)
# ═════════════════════════════════════════════════════════════════════════════

def build_ease_report(root: Path | None = None) -> str:
    scan = ease_instrument_scan(root=root)
    lines = [
        "# Campaign-close ease report — %s" % GENERATION_TAG,
        "",
        "**Criterion (C8):** the chamber counts John's interface-caused",
        "overhead messages per session with the pre-registered FROZEN",
        "classifier of record, from the first input-taking surface (the W8",
        "say box) onward, and reports the count at campaign close against",
        "the Stage-2 baseline (%s) on the same ruler." % STAGE2_BASELINE,
        "",
        "## Instrument scan (mechanical, re-runnable)",
        "",
        "| Leg (home wave) | Present in tree |",
        "|-----------------|-----------------|",
        "| W3 pre-registered frozen classifier | %s |"
        % ("YES" if scan["frozen_classifier_landed"] else "NO"),
        "| W8 live say-box classification ledger | %s |"
        % ("YES" if scan["live_ease_ledger_landed"] else "NO"),
        "| V6 per-turn spoken-latency log | %s |"
        % ("YES" if scan["latency_log_landed"] else "NO"),
        "| Reference-session transcript in tree | %s |"
        % ("YES" if scan["reference_transcript_in_tree"] else "NO"),
        "",
        "## The count since the W8 say box",
        "",
        "**UNAVAILABLE, by name:** no classifier of record was ever",
        "registered and no say-box message was ever classified or logged —",
        "the W3/W8 ease legs did not land (W10's traceability note recorded",
        "the gap; the scan above re-verifies it). There are no classified",
        "excerpts and no error bars because there is no count; presenting",
        "any number here would be fabrication, which this system refuses.",
        "",
        "## The Stage-2 baseline (same-ruler protocol)",
        "",
        "The reference feel is John's Stage-2 Fable-driver session",
        "('MBA Teaching with AI', 2026-08-08): interface-caused overhead",
        "trending %s across the session. The same-ruler re-score" %
        STAGE2_BASELINE,
        "protocol (run the frozen classifier of record over the",
        "reference-session transcript) CANNOT run: there is no classifier",
        "of record, and the session's journal lives outside this tree (the",
        "run-ownership law kept it in John's own project). Per the plan's",
        "own C8 fallback, the %s comparison is therefore" % STAGE2_BASELINE,
        "**DESCRIPTIVE ONLY** and the verdict falls back to John's audit",
        "alone.",
        "",
        "## V6 — spoken-turn latency",
        "",
        "**On the table, as absence:** no per-turn say-box latency was",
        "logged (the V6 measurement leg did not land with a say-box",
        "classification path). An unmeasured regression is a V6 violation —",
        "recorded here by name rather than papered over.",
        "",
        "## VERDICT — HALT for John's one-pass audit",
        "",
        "Per the pre-registration law there is no post-hoc tuning and no",
        "number above is the verdict until John's one-pass audit rules on",
        "this report. Given the instrument gaps, the audit question is not",
        "'is the count credible' but 'fund the ease stack, re-scope C8, or",
        "accept the loss' — the same plan-defect disposition the E1 report",
        "carries (chamber/W12-AUDIT-REPORT.md, named findings).",
        "",
    ]
    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════════════════════
# Writers + committed-artifact equality (the determinism seam CI asserts)
# ═════════════════════════════════════════════════════════════════════════════

REPORTS = (
    ("e1", E1_REPORT_PATH, build_e1_report),
    ("e3", E3_REPORT_PATH, build_e3_report),
    ("ease", EASE_REPORT_PATH, build_ease_report),
)


def write_reports(chamber_dir: Path | None = None) -> dict:
    """Regenerate all three reports to disk. Returns {name: path}."""
    out = {}
    for name, default_path, builder in REPORTS:
        path = (Path(chamber_dir) / default_path.name) if chamber_dir \
            else default_path
        path.write_text(builder(), encoding="utf-8", newline="\n")
        out[name] = path
    return out


def committed_matches_regenerated() -> list:
    """Empty list == every committed report equals a fresh regeneration
    (deterministic builders over the tree). A drifted report is named."""
    problems = []
    for name, path, builder in REPORTS:
        if not path.is_file():
            problems.append("%s: committed report missing (%s)"
                            % (name, path.name))
            continue
        committed = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        if committed != builder():
            problems.append("%s: committed report differs from a fresh "
                            "regeneration — regenerate via "
                            "chamber_close_report.write_reports()" % name)
    return problems
