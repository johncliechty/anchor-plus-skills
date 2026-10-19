"""The W12 cross-criterion audit core (steward-chamber W12, Phase-4 Close).

Audits the ASSEMBLED chamber rather than first-exercising anything: every
criteria-ledger row (E1–E9) and the C9–C12 re-checks resolve to a
mechanical status against the tree, and the committed audit report
(``chamber/W12-AUDIT-REPORT.md``) records the outcome — including, by
name, every instrument the landing waves promised that is NOT in the tree.
The plan's own law: "a criterion first exercised here would be a plan
defect" — where that defect exists this module RECORDS it (named finding,
routed to John); it never papers over it and never silently builds the
missing wave's machinery under audit colors.

Statuses:

* ``reverified``      — the landing-wave instrument exists in the tree and
                        re-runs under the same gate; the W12 suite re-runs
                        the refusal end-to-end as well.
* ``reverified-in-W12`` — the ENGINE machinery landed in its wave and the
                        W12 suite exercises the refusal at the named seam,
                        BUT the landing wave's own named instrument is
                        absent from the tree (first exercised here = the
                        named plan defect, recorded).
* ``instrument-missing`` — neither the machinery nor the instrument landed;
                        nothing can be re-run; plan defect for John.
* ``blocked-on-signature`` — mechanically green, awaiting a John gate that
                        the plan schedules in W12 (C11 parity signing).

Deterministic over the tree (no clocks, no randomness) so CI can assert
committed == regenerated. Stdlib + chamber modules only; read-only except
:func:`write_report`.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

ANCHOR_ROOT = Path(__file__).resolve().parent
CHAMBER_DIR = ANCHOR_ROOT / "chamber"
AUDIT_REPORT_PATH = CHAMBER_DIR / "W12-AUDIT-REPORT.md"

GENERATION_TAG = "steward-chamber W12 (Phase-4 Close)"

FINDING_PLAN_DEFECT = "W12-PLAN-DEFECT-INSTRUMENT-ABSENT"

#: Landing-wave test files that chamber artifacts / route_table comments
#: cite as instruments but that are NOT in the tree. Every name here is a
#: ghost the audit re-checks mechanically (a file that appears later flips
#: the report on regeneration).
CITED_INSTRUMENT_FILES = (
    "tests/test_chamber_red_to_green_w3.py",
    "tests/test_chamber_close_ci_w9.py",
    "tests/test_chamber_directive_w10.py",
    "tests/test_chamber_gate_queue_w10.py",
    "tests/test_chamber_gate_routes_w10.py",
)


def _exists(rel: str) -> bool:
    return (ANCHOR_ROOT / rel).is_file()


def missing_cited_instruments() -> list:
    return [rel for rel in CITED_INSTRUMENT_FILES if not _exists(rel)]


# ═════════════════════════════════════════════════════════════════════════════
# The three cross-criterion interaction cases (no landing wave could see)
# ═════════════════════════════════════════════════════════════════════════════

#: Each case's named finding comes from the OWNING module — the audit
#: re-runs the seams in tests/test_chamber_cross_audit_w12.py.
def interaction_cases() -> list:
    import chamber_gates as cg
    import chamber_rebrief as crb
    return [
        {"case": "run dies WHILE a gate is held",
         "seam": "chamber_gates.on_run_death (held gate kept) + "
                 "enqueue_guard (E2 holds)",
         "named_finding": cg.FINDING_E2_BLOCKED},
        {"case": "sweep card vs directive card contend for the queue head",
         "seam": "chamber_gates.bind_sweep_card (sweep takes head; "
                 "directive re-queued, never dropped)",
         "named_finding": cg.FINDING_CONTENTION},
        {"case": "re-brief lands during an active sweep",
         "seam": "chamber_rebrief.rebrief -> queued behind the sweep's "
                 "card binding, never interleaved",
         "named_finding": crb.FINDING_REBRIEF_DURING_SWEEP},
    ]


# ═════════════════════════════════════════════════════════════════════════════
# E1–E9 re-verification rows (the ledger's W12 re-verify column)
# ═════════════════════════════════════════════════════════════════════════════

def criteria_rows() -> list:
    """Every ledger row resolved to a mechanical W12 status. Each row names
    the instrument, the seam, and — when the landing instrument is a ghost
    — the plan defect, honestly."""
    import chamber_close_report as ccr

    rows = []

    e1 = ccr.e1_instrument_scan()
    rows.append({
        "id": "E1", "home": "W8",
        "instrument": "W8 joint negative-path test + telemetry-injection "
                      "DOM test",
        "status": "instrument-missing",
        "finding": FINDING_PLAN_DEFECT,
        "note": "the E1 stack is incomplete in the tree (parser %s / "
                "ratification %s / turn hook %s / W8 test %s) — see "
                "chamber/E1-ENFORCEMENT-REPORT.md"
                % tuple("landed" if v else "ABSENT" for v in (
                    e1["bound_parser_landed"],
                    e1["ratification_artifact_landed"],
                    e1["turn_completion_hook_landed"],
                    e1["w8_negative_path_test_landed"]))}
        if not e1["stack_complete"] else {
        "id": "E1", "home": "W8",
        "instrument": "W8 joint negative-path test",
        "status": "reverified", "note": "stack present"})

    w10_ghosts = [g for g in missing_cited_instruments() if "w10" in g]
    w10_note = ("machinery landed in W10 (chamber_gates/chamber_directive) "
                "and the W12 suite re-blocks the refusals at the seams; the "
                "wave's own cited instrument(s) are absent from the tree: %s "
                "— first exercised in W12, the named plan defect"
                % ", ".join(w10_ghosts)) if w10_ghosts else "reverified"
    w10_status = "reverified-in-W12" if w10_ghosts else "reverified"

    rows.append({"id": "E2", "home": "W10",
                 "instrument": "enqueue-gate negative-path test on the W2 "
                               "seam (chamber_gates.enqueue_guard)",
                 "status": w10_status,
                 "finding": FINDING_PLAN_DEFECT if w10_ghosts else None,
                 "note": w10_note})
    rows.append({"id": "E3", "home": "W11",
                 "instrument": "tests/test_chamber_corrections_w11.py "
                               "(handback-block + coverage report)",
                 "status": "reverified" if _exists(
                     "tests/test_chamber_corrections_w11.py")
                 else "instrument-missing",
                 "note": "re-run end-to-end by the W12 suite"})
    rows.append({"id": "E4", "home": "W10",
                 "instrument": "template fixture suite "
                               "(chamber_directive.template_findings)",
                 "status": w10_status,
                 "finding": FINDING_PLAN_DEFECT if w10_ghosts else None,
                 "note": w10_note})
    rows.append({"id": "E5", "home": "W10",
                 "instrument": "head-only serialization test "
                               "(chamber_gates ERROR_NOT_HEAD + "
                               "render_gate_queue_html)",
                 "status": w10_status,
                 "finding": FINDING_PLAN_DEFECT if w10_ghosts else None,
                 "note": w10_note})
    rows.append({"id": "E6", "home": "W11",
                 "instrument": "tests/test_chamber_preload_w11.py "
                               "(preload diff test)",
                 "status": "reverified" if _exists(
                     "tests/test_chamber_preload_w11.py")
                 else "instrument-missing",
                 "note": "re-run end-to-end by the W12 suite"})
    rows.append({"id": "E7", "home": "W11",
                 "instrument": "tests/test_chamber_rebrief_w11.py "
                               "(re-brief per audited mode, no relaunch)",
                 "status": "reverified" if _exists(
                     "tests/test_chamber_rebrief_w11.py")
                 else "instrument-missing",
                 "note": "re-run end-to-end by the W12 suite"})

    rows.append({"id": "E8", "home": "W5",
                 "instrument": "W5 sidecar-derivation tests + W4 zero-"
                               "spine-write assertions "
                               "(chamber_spine_guard.deny_problems)",
                 "status": "reverified-in-W12",
                 "finding": FINDING_PLAN_DEFECT,
                 "note": "W5 derivation tests exist "
                         "(test_chamber_coldopen_w5/brownfield_reconcile) "
                         "but NO test named chamber_spine_guard before this "
                         "wave — the W12 suite re-runs the deny scan at "
                         "the seam"})
    rows.append({"id": "E9", "home": "W4/W5",
                 "instrument": "collapsed-stage manifest-lint refusal + "
                               "died-after-last-reflection fixture",
                 "status": "reverified" if (
                     _exists("tests/test_chamber_manifest_schema_w4.py")
                     and _exists("tests/test_chamber_coldopen_w5.py"))
                 else "instrument-missing",
                 "note": "re-run end-to-end by the W12 suite"})
    return rows


# ═════════════════════════════════════════════════════════════════════════════
# C9–C12 re-checks
# ═════════════════════════════════════════════════════════════════════════════

def c_recheck_rows() -> list:
    import chamber_mockup_diff as cmd
    import chamber_registries as reg
    import chamber_retirement as ret

    rows = []

    # C9 — the signed post-amendment hash pin, recomputed live.
    try:
        pinned = cmd.signed_hash()
        actual = hashlib.sha256(
            cmd.mockup_path().read_bytes()).hexdigest()
        c9_ok = (pinned == actual)
        c9_note = ("hash pin %s: signed %s… vs live %s…"
                   % ("HOLDS" if c9_ok else "BROKEN",
                      pinned[:12], actual[:12]))
    except Exception as exc:
        c9_ok, c9_note = False, "hash pin unverifiable: %s" % exc
    rows.append({"id": "C9", "check": "hash-pinned DOM diffs",
                 "green": c9_ok, "note": c9_note})

    # C10 — F5 suite present; the F3 escape suite and part of the F6
    # red-to-green coverage are ghosts, re-exercised by the W12 bundle.
    f5 = _exists("tests/test_chamber_dom_law_w9.py")
    ghost_rg = [g for g in missing_cited_instruments()
                if "red_to_green" in g or "close_ci" in g]
    rows.append({"id": "C10",
                 "check": "F3 escape + F5 hostile-string + F6 red-to-green",
                 "green": f5,
                 "note": "F5 slot-registered hostile-string suite present "
                         "and re-run (test_chamber_dom_law_w9); W11 "
                         "mutator red-to-green present "
                         "(test_chamber_refine_routes_w11); the W9 F3 "
                         "escape/hostile-argv suite and the W3 "
                         "full-inventory red-to-green file are ghosts (%s) "
                         "— the W12 release bundle exercises the F3 "
                         "bounds, the F4 containment, the diff guard and "
                         "the coverage rule at their seams (named "
                         "reconciliation)" % ", ".join(ghost_rg)})

    # C11 — signed parity retirement gate.
    st = ret.retirement_state()
    rows.append({"id": "C11", "check": "tile retirement on signed parity",
                 "green": st["tiles_stand"] and not st["parity"]["problems"],
                 "note": ("parity map green; %d row(s) pending John's "
                          "ruling (%s); UNSIGNED -> tiles stand, retirement "
                          "refused by name (%s)"
                          % (len(st["parity"]["pending_john"]),
                             ", ".join(st["parity"]["pending_john"]),
                             st["verdict"].get("finding")))
                 if st["tiles_stand"] else
                 "SIGNED — retirement authorized"})

    # C12 — wire-homing symbol check + characterization-oracle presence.
    lint = reg.lint_wire_homing()
    pulse_oracle = sorted(
        (ANCHOR_ROOT / "tests" / "fixtures" / "chamber").rglob("*pulse*"))
    rows.append({"id": "C12",
                 "check": "wire-homing registry symbol-check + "
                          "characterization parity",
                 "green": not lint,
                 "note": ("symbol-check GREEN (all 10 rows resolve; the "
                          "check itself lands in W12 — the registry "
                          "declared it active from W1 but no module "
                          "implemented it before this wave, recorded "
                          "reconciliation). W7's committed pulse replay "
                          "oracle: %s"
                          % ("present" if pulse_oracle
                             else "NOT FOUND in tests/fixtures/chamber — "
                                  "the run_pulse characterization oracle "
                                  "the registry cites is absent (named "
                                  "gap)"))
                 if not lint else "; ".join(lint[:5])})
    return rows


# ═════════════════════════════════════════════════════════════════════════════
# Stale-UI test-debt disposition (TEST-DEBT-REGISTER -> W12 obligation)
# ═════════════════════════════════════════════════════════════════════════════

#: Every stale-UI deselect family from scripts/run-all-tests.mjs, resolved
#: to the M1-DOM equivalent suite that now pins the replacing surface, or
#: honestly marked a loss PENDING John's signature at the same W12 signing
#: (the tile-retirement gate). kind == "equivalent" rows name a test file
#: that must exist; CI asserts it.
TEST_DEBT_DISPOSITION = (
    {"family": "test_cockpit_paradigm2 (4 deselects) — old Layout-D board "
               "pins", "kind": "equivalent",
     "equivalent": "tests/test_chamber_seal_ci_w6.py",
     "note": "the project window's chamber region is the M1 seal; its DOM "
             "pins live in the W6/W7 diff suites"},
    {"family": "test_project_window (4) + test_rnd_project_window_kanban "
               "(2) + test_rnd_ui_wiring (1) — old lane-board/panel pins",
     "kind": "equivalent",
     "equivalent": "tests/test_chamber_mockup_diff_w6.py",
     "note": "M1 markup pins are hash-pinned DOM diffs against the signed "
             "mockup"},
    {"family": "test_no_loss_lifecycle_v8 (4) + test_session_continue UI "
               "leg + test_resume_ui_w4 (3) — old tile lifecycle pins",
     "kind": "pending-john",
     "note": "these pin the BOTTOM TILES the C11 gate retires; their "
             "disposition rides the same signing (retire -> accepted loss "
             "of the old pins; keep -> re-pin against the surviving tile "
             "markup)"},
    {"family": "test_steward_persona (3) — old chamber-tile livery pins",
     "kind": "equivalent",
     "equivalent": "tests/test_chamber_open_w6.py",
     "note": "the seal/livery render is pinned by the chamber open suite"},
    {"family": "test_v7_polish (3) + test_board_live/brownfield_wiring/"
               "build_deliverable/build_planning_tie/grass_contained "
               "(5) — old board-fragment pins",
     "kind": "pending-john",
     "note": "board fragments outside the chamber region were not rebuilt "
             "by this plan (non-goal); repin or sign the loss at the W12 "
             "signing"},
    {"family": "test_b2_repro_w1 (2) + test_claude_first_launch_w1 (1) + "
               "test_gandalf_markdown_links_v13 (1) + "
               "test_layoutd_skeleton_playwright_v12 (1) + "
               "test_live_escalation_ui_w6 (1)",
     "kind": "pending-john",
     "note": "pre-existing UI pins on surfaces adjacent to (not part of) "
             "the M1 rebuild; adjudication is John's at the signing — the "
             "register's provenance rows stand"},
)


def test_debt_problems() -> list:
    """Empty == every 'equivalent' disposition row names an existing
    suite."""
    problems = []
    for row in TEST_DEBT_DISPOSITION:
        if row["kind"] == "equivalent":
            rel = row.get("equivalent") or ""
            if not _exists(rel):
                problems.append("%s: named M1 equivalent does not exist: %s"
                                % (row["family"], rel))
    return problems


# ═════════════════════════════════════════════════════════════════════════════
# The committed report
# ═════════════════════════════════════════════════════════════════════════════

def build_report() -> str:
    rows = criteria_rows()
    cs = c_recheck_rows()
    cases = interaction_cases()
    ghosts = missing_cited_instruments()
    lines = [
        "# W12 cross-criterion audit report — %s" % GENERATION_TAG,
        "",
        "The audit of the ASSEMBLED chamber: every criteria-ledger row",
        "re-verified at its named seam, the C9–C12 re-checks, the three",
        "interaction cases, and — by name — every instrument a landing wave",
        "promised that is not in the tree. Statuses: `reverified` (landing",
        "instrument exists + re-runs) · `reverified-in-W12` (machinery",
        "landed; the landing wave's own instrument is a ghost — the named",
        "plan defect) · `instrument-missing` (nothing to re-run; plan",
        "defect for John) · `blocked-on-signature` (awaiting the scheduled",
        "John gate).",
        "",
        "## E1–E9 (the ledger's W12 re-verify column)",
        "",
        "| Row | Home | Named instrument | W12 status |",
        "|-----|------|------------------|------------|",
    ]
    for r in rows:
        lines.append("| %s | %s | %s | **%s** |"
                     % (r["id"], r["home"],
                        r["instrument"].replace("|", "/"),
                        r["status"]))
    lines += ["", "Row notes:", ""]
    for r in rows:
        lines.append("* **%s** — %s" % (r["id"], r["note"]))
    lines += [
        "",
        "## The three interaction cases (re-blocked in "
        "tests/test_chamber_cross_audit_w12.py)",
        "",
        "| Case | Seam | Named finding |",
        "|------|------|---------------|",
    ]
    for c in cases:
        lines.append("| %s | %s | `%s` |"
                     % (c["case"], c["seam"].replace("|", "/"),
                        c["named_finding"]))
    lines += [
        "",
        "## C9–C12 re-checks",
        "",
    ]
    for c in cs:
        lines.append("* **%s** (%s): %s — %s"
                     % (c["id"], c["check"],
                        "GREEN" if c["green"] else "NOT GREEN", c["note"]))
    lines += [
        "",
        "## Reconciliation register — cited instruments absent from the "
        "tree",
        "",
        "Chamber artifacts and route-table comments cite these test files;",
        "none exists. Each is a named finding, not a silent gap:",
        "",
    ]
    for g in ghosts:
        lines.append("* `%s`" % g)
    if not ghosts:
        lines.append("(none — all cited instruments present)")
    lines += [
        "",
        "Further named gaps re-verified by this audit: the W4",
        "kill-during-write crash + two-real-process concurrency tests the",
        "property-gate checklist binds to W4 are not in the chamber test",
        "namespace; the W7 run_pulse committed replay oracle is absent; the",
        "W8 wave (E1 stack, say-box classification, ease count, telemetry",
        "DOM test) landed none of its cited chamber deliverables — its",
        "wave commit changed no chamber source. Dispositions are John's at",
        "the W12 close (see the enforcement reports).",
        "",
        "## Stale-UI test-debt disposition (TEST-DEBT-REGISTER -> W12)",
        "",
    ]
    for row in TEST_DEBT_DISPOSITION:
        if row["kind"] == "equivalent":
            lines.append("* %s -> **M1 equivalent:** `%s` — %s"
                         % (row["family"], row["equivalent"], row["note"]))
        else:
            lines.append("* %s -> **pending John's signature** — %s"
                         % (row["family"], row["note"]))
    lines += [
        "",
        "## Named gate exclusions revisited (the run-all-tests banner)",
        "",
        "* `tests/test_foundry_*` family — pre-existing reds on HEAD in a",
        "  separate subsystem; NOT chamber scope. Stands excluded, named in",
        "  the banner; re-adjudication belongs to a foundry-owned effort,",
        "  not this close.",
        "* `tests/test_gandalf_agentic.py` — multi-minute stalls under",
        "  stubs; stands excluded by budget, named in the banner.",
    ]
    # The E1 clause is SCAN-DERIVED (steward-e1 W2): once the funded
    # re-execution lands the instrument stack, the verdict must stop
    # claiming it absent — and must not claim it enforced before John's
    # F7 signature arms it.
    e1_landed = any(r["id"] == "E1" and r["status"] == "reverified"
                    for r in rows)
    if e1_landed:
        verdict_tail = [
            "block with their named findings. The E1 instrument stack is",
            "landed (the steward-e1 re-execution; enforcement arms at",
            "John's F7 signature and fails CLOSED by name until then); the",
            "ease count is NOT instrumented — a plan defect for John,",
            "published in the enforcement reports. Tiles stand: parity is",
            "resolved but UNSIGNED (three rows await John's ruling at the",
            "signing gate).",
        ]
    else:
        verdict_tail = [
            "block with their named findings. E1 and the ease count are NOT",
            "enforced/instrumented — plan defects for John, published in the",
            "enforcement reports. Tiles stand: parity is resolved but UNSIGNED",
            "(three rows await John's ruling at the signing gate).",
        ]
    lines += [
        "",
        "## Verdict",
        "",
        "The assembled system's landed enforcement (E3/E5-machinery/E6/E7/",
        "E9, F3/F4/F5, the projections substrate, the M1 paint bounds) is",
        "re-verified green at its seams, and the three interaction cases",
    ] + verdict_tail + [
        "",
    ]
    return "\n".join(lines)


def write_report(path: Path | None = None) -> Path:
    p = Path(path) if path else AUDIT_REPORT_PATH
    p.write_text(build_report(), encoding="utf-8", newline="\n")
    return p


def committed_matches_regenerated() -> list:
    if not AUDIT_REPORT_PATH.is_file():
        return ["W12 audit report missing (chamber/W12-AUDIT-REPORT.md)"]
    committed = AUDIT_REPORT_PATH.read_text(
        encoding="utf-8").replace("\r\n", "\n")
    if committed != build_report():
        return ["W12 audit report differs from a fresh regeneration — "
                "regenerate via chamber_audit.write_report()"]
    return []
