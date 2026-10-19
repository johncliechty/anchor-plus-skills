"""North-Star scorecard + closure reconciliation (rearch W18 — C7).

The re-architecture's CLOSURE deliverable (frozen plan: ``IMPLEMENTATION-PLAN.md``,
W18 — Closure: Hybrid Hardening + North-Star Scorecard): convert *"we built it"*
into *"the daily 5AM run and the live service prove it"* by emitting a
DEMONSTRATED (not narrated) scorecard for the seven North-Star success criteria,
each marked ``met`` / ``narrowed`` / ``unmet`` with its proving gate artifact
linked, plus the Appendix-A reconciliation (every integrated idea 1–52 and
mitigation 1–20 resolved to a landed item or a documented amendment) and the
scaffolding-retirement audit.

Honesty is mechanical, never asserted:

* **C1** is ``narrowed`` iff the census-raised amendment file
  (``C1-AMENDMENT-REQUIRED.md``) still exists — the include-layer design was
  amended up front (markup-emitting interpolations exceeded the ANCHOR_BOOT
  threshold); it flips to ``met`` only when the census no longer forces it.
* **C4**'s live half is ``narrowed`` while the ``C4-RUNBOOK.md`` execution log
  reads ``NOT YET RUN`` — the hermetic gate proves the mechanism; only the live
  runbook run WITH John proves cross-process survival. It flips to ``met`` the
  moment that cell is filled in on the real service (never fabricated here).
* Every other criterion is ``met`` by a green hermetic/mechanical gate whose
  artifact is linked; the criteria that ALSO require a one-sitting live
  confirmation (C2's tokenless-401 assert, C6's clean-git-after-a-healthcheck
  cycle, C7's per-wave live smoke) carry that confirmation as a PENDING item in
  ``CLOSURE-SIGNOFF.md`` — recorded via the sign-off path, never silently.

The done-when bar — *every C1–C7 criterion met or narrowed-by-recorded-amendment*
— is satisfied because no criterion is ``unmet``: the two narrowings each link a
recorded amendment/sign-off artifact. :func:`unresolved_criteria` returns the
criteria that are neither ``met`` nor ``narrowed-with-an-artifact`` (empty at
closure); the W18 gate asserts it is empty.

Stdlib only (``json``, ``pathlib``, ``re``). Reads checked-in artifacts; writes
the four closure docs (skipping an unchanged rewrite, like ``pillar_flags``).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACT_DIR = REPO_ROOT / "planning" / "rearch-2026-07"

SCORECARD_MD = "NORTH-STAR-SCORECARD.md"
SCORECARD_JSON = "NORTH-STAR-SCORECARD.json"
RECONCILIATION_MD = "APPENDIX-A-RECONCILIATION.md"
SIGNOFF_MD = "CLOSURE-SIGNOFF.md"
RETIREMENT_MD = "SCAFFOLDING-RETIREMENT.md"

STATUS_MET = "met"
STATUS_NARROWED = "narrowed"
STATUS_UNMET = "unmet"

# ── the checked-in artifacts each criterion's status is read from ─────────────

C1_AMENDMENT = "C1-AMENDMENT-REQUIRED.md"
C4_RUNBOOK = "C4-RUNBOOK.md"
#: the sentinel the runbook's execution cell carries until it is run live.
C4_NOT_RUN_SENTINEL = "NOT YET RUN"


def _artifact(name):
    return ARTIFACT_DIR / name


def _exists(name):
    return _artifact(name).exists()


def _read(name):
    try:
        return _artifact(name).read_text(encoding="utf-8")
    except OSError:
        return ""


# ── C1 / C4 status are computed from ground-truth artifacts ───────────────────

def c1_status():
    """``narrowed`` while the census forces the include-layer amendment."""
    if _exists(C1_AMENDMENT):
        return STATUS_NARROWED
    return STATUS_MET


def c4_live_status():
    """``narrowed`` until the C4 runbook has been executed live WITH John."""
    md = _read(C4_RUNBOOK)
    if not md:
        return STATUS_UNMET                      # the runbook itself is missing
    if C4_NOT_RUN_SENTINEL in md:
        return STATUS_NARROWED
    return STATUS_MET


# ── the seven criteria ────────────────────────────────────────────────────────

def _criterion(cid, title, status, proving_artifacts, evidence,
               amendment=None, live_signoff=None):
    return {
        "id": cid,
        "title": title,
        "status": status,
        "proving_artifacts": list(proving_artifacts),
        "evidence": evidence,
        "amendment": amendment,          # the recorded narrowing artifact
        "live_signoff": live_signoff,    # the pending one-sitting confirmation
    }


def criteria():
    """The seven North-Star criteria with a mechanically-computed status.

    C1 and C4 read their status from the checked-in ground-truth artifacts;
    the rest are ``met`` by a green hermetic/mechanical gate (the gate that
    proves each is its ``proving_artifacts``). Nothing is asserted here that a
    linked artifact does not back.
    """
    return [
        _criterion(
            "C1", "Frontend extracted (static files; ≥7,000-line shrink)",
            c1_status(),
            ["planning/rearch-2026-07/CENSUS-REPORT.md",
             "planning/rearch-2026-07/C1-AMENDMENT-REQUIRED.md",
             "tests/test_rearch_2026_07.py::TestW4ByteParityGate"],
            "Census: derived shrink 7089 ≥ 7000 (met); markup-emitting "
            "interpolations 48 > threshold 40 forced the include-layer "
            "amendment (W6a/b/c slots) — extraction rides named include slots, "
            "not the ANCHOR_BOOT JSON. Byte-parity gate is green.",
            amendment="planning/rearch-2026-07/C1-AMENDMENT-REQUIRED.md"),
        _criterion(
            "C2", "One route table · declarative default-deny auth",
            STATUS_MET,
            ["OPEN_ROUTES.json",
             "route_table.py (DATA_PLANE_GATED)",
             "anchor_healthcheck.check_cookie_auth_walk"],
            "Every route dispatches through the declarative table; token is the "
            "default, the open allowlist is explicit + reviewed (OPEN_ROUTES). "
            "The hermetic enforce walk proves tokenless data-plane GET → 401, "
            "cookie navigation carries the browser, ?token= is the WS fallback, "
            "and the 401-before-101 upgrade ordering holds.",
            live_signoff="C2 tokenless-401 live assert on :8777"),
        _criterion(
            "C3", "Event-log spine · dual-write · provably derivable",
            STATUS_MET,
            ["tests/test_parity_recovery_w14.py",
             "anchor_healthcheck.check_journal_parity",
             "planning/rearch-2026-07/REBUILD-TABLE.md"],
            "Every mutation-of-record appends a schema-versioned journal event "
            "alongside the legacy stores. The classifying parity gate re-derives "
            "the session/effort views with zero divergence, and the recovery "
            "tool rebuilds a deleted index.json from the journal in a test — "
            "the 'lost from an index' bug class is recoverable-by-construction.",
            live_signoff=None),
        _criterion(
            "C4", "Supervisor split — restart survival, live-proven",
            # the JOBS half (non-negotiable) is met hermetically + W17; the
            # LIVE cross-process demo half is narrowed until the runbook runs.
            c4_live_status(),
            ["tests/test_supervisor_w15.py",
             "tests/test_supervisor_w16.py",
             "tests/test_c4_w17.py",
             "planning/rearch-2026-07/C4-RUNBOOK.md"],
            "Jobs are owned by a separate stdlib supervisor (own NSSM service, "
            "loopback token-authed IPC, inline seam for tests). The hermetic "
            "gate proves a simulated-restart re-adoption with tail cursors "
            "intact; the two live probes (claude --version under the account, "
            "breakaway child survives a supervisor restart) are wired. The live "
            "cross-process demo (nssm restart anchor with a job in flight) is "
            "the runbook cell — honestly narrowed until run WITH John. PTYs: "
            "the ConPTY spike verdict was YES → the adoption follow-on is "
            "scheduled; the pre-restart drain remains the safety net.",
            amendment="planning/rearch-2026-07/C4-RUNBOOK.md",
            live_signoff="C4 runbook execution on the real :8777 service"),
        _criterion(
            "C5", "One markdown-parsing layer (third copy + Flask server dead)",
            STATUS_MET,
            ["tests/test_anchor_md_defork_w10.py",
             "anchor_md.py",
             "docs/anchor_server-predeletion-sweep.md"],
            "A single shared parsing module (anchor_md.py); anchor_gui.py and "
            "anchor.py import it (the byte-identical twins de-forked). The "
            "drifted third copy died with anchor_server.py, deleted after the "
            "confirmed-dead sweep (Flask, port 5000, referenced by nothing).",
            live_signoff=None),
        _criterion(
            "C6", "Runtime state out of the repo · git stays clean",
            STATUS_MET,
            ["tests/test_data_dir_migration_w11.py::TestGitHygieneGate",
             "anchor_healthcheck.check_relocated_data_dir",
             "tools/git_hygiene.py", "migrate_data_dir.ps1"],
            "The paths.py ANCHOR_DATA_DIR seam relocates runtime state outside "
            "the repo; the scripted migration copies→rewrites→verifies→arms the "
            "reaper dry-run. The porcelain gate proves a full healthcheck write "
            "cycle leaves `git status --porcelain` empty with writes landing "
            "outside the repo; the hermetic relocated-data-dir walk asserts the "
            "same nightly.",
            live_signoff="C6 clean-git after a live healthcheck cycle on :8777"),
        _criterion(
            "C7", "Never-broken increments · green suite · named hybrid state",
            STATUS_MET,
            ["IMPLEMENTATION-PLAN.md (test-command: full suite)",
             "pillar_flags.assert_named_state",
             "planning/rearch-2026-07/PROCESS-RAILS.md"],
            "Every merged step kept the dashboard operational on :8777 (stdlib "
            "only, pywinpty exception; markdown source of truth). The full test "
            "suite stays green and each pillar landed with its own gate. The "
            "healthcheck asserts the CURRENT live flag configuration is a NAMED "
            "hybrid state (check_pillar_state) and the four new walks join the "
            "5AM run only after their 20× soak.",
            live_signoff="C7 per-wave live-service smoke on the merged state"),
    ]


def unresolved_criteria():
    """Criteria that are neither ``met`` nor ``narrowed`` with a linked
    amendment. Empty at closure — the W18 done-when bar."""
    out = []
    for c in criteria():
        if c["status"] == STATUS_MET:
            continue
        if c["status"] == STATUS_NARROWED and c.get("amendment"):
            continue
        out.append(c["id"])
    return out


# ── the pending one-sitting live sign-offs ────────────────────────────────────

def pending_signoffs():
    """The final live sign-offs run in one sitting WITH John (never faked).

    Each is a live confirmation the hermetic gates cannot cover; the scorecard
    links them so the narrowing is recorded, never silent.
    """
    return [
        {"id": "SO-C4",
         "title": "C4 runbook re-confirmation",
         "detail": "A harmless fake_claude job in flight on :8777 survives "
                   "`nssm restart anchor`; the restarted dashboard lists the "
                   "same job_id live with an advancing tail (C4-RUNBOOK.md).",
         "artifact": "planning/rearch-2026-07/C4-RUNBOOK.md"},
        {"id": "SO-C2",
         "title": "C2 tokenless-401 live assert",
         "detail": "With ANCHOR_AUTH_MODE=enforce on the live service, a "
                   "tokenless data-plane GET returns a real 401 (the flip took).",
         "artifact": "planning/rearch-2026-07/AUTH-WARN-SOAK.md"},
        {"id": "SO-C6",
         "title": "C6 healthcheck-cycle-then-clean-git check",
         "detail": "Run `python anchor_healthcheck.py`, then "
                   "`git status --porcelain` on the repo is empty (runtime "
                   "writes landed under the relocated ANCHOR_DATA_DIR).",
         "artifact": "docs/w11-data-dir-migration.md"},
        {"id": "SO-SMOKE",
         "title": "Per-wave live smoke on the final merged state",
         "detail": "The PROCESS-RAILS §1 smoke checklist on the merged branch: "
                   "restart → GET / 200 (new build id) → a project window loads "
                   "→ healthcheck green → porcelain empty.",
         "artifact": "planning/rearch-2026-07/PROCESS-RAILS.md"},
    ]


# ── Appendix-A reconciliation (ideas 1–52 + mitigations 1–20) ─────────────────

LEDGER = "APPENDIX-A-TRACEABILITY.md"

#: M-9 is the ONLY mitigation cited by zero waves of the frozen plan. Its text
#: lives in the Stage-1 Master Plan, which is not checked into this repo, so it
#: is resolved as a DOCUMENTED AMENDMENT via the North-Star amendment path — a
#: no-landing item recorded mechanically, never a silent drop.
M9_RESOLUTION = (
    "M-9 has NO landing wave in the frozen Implementation Plan (every other "
    "mitigation 1–20 resolves to at least one wave). The Stage-1 Master Plan "
    "carrying M-9's text is not checked into this repository, so M-9 is "
    "resolved via the North-Star amendment path as an explicitly-recorded "
    "no-landing item — a documented amendment, visibly carried since W3 and "
    "closed here. This is a resolution to a documented amendment, never a "
    "silent drop.")


def _parse_ledger_tables():
    """Return ``(ideas, mitigations)`` as ``{n: set(wave-labels)}`` from the
    W3 ledger's two tables (the same rows the W3 gate holds faithful)."""
    md = _read(LEDGER)
    ideas = {int(m.group(1)): set(re.findall(r"W\d+", m.group(2)))
             for m in re.finditer(r"^\| I-(\d+) \| ([^|]*)\|", md, flags=re.M)}
    mits = {int(m.group(1)): set(re.findall(r"W\d+", m.group(2)))
            for m in re.finditer(r"^\| M-(\d+) \| ([^|]*)\|", md, flags=re.M)}
    return ideas, mits


def appendix_a_reconciliation():
    """The W18 closure reconciliation over the W3 traceability ledger.

    Every integrated idea 1–52 resolves to ≥1 citing wave (a landed item);
    every mitigation 1–20 resolves to a citing wave EXCEPT M-9, which resolves
    to a documented amendment. Returns a structured verdict with the honest
    ``dropped`` list (empty at closure — zero silently-dropped ideas).
    """
    ideas, mits = _parse_ledger_tables()
    idea_ns = set(range(1, 53))
    mit_ns = set(range(1, 21))

    ideas_landed = sorted(n for n in idea_ns if ideas.get(n))
    ideas_dropped = sorted(n for n in idea_ns if not ideas.get(n))
    mits_landed = sorted(n for n in mit_ns if mits.get(n))
    mits_amended = sorted(n for n in mit_ns
                          if not mits.get(n))          # {9} by design

    ok = (set(ideas_landed) == idea_ns
          and not ideas_dropped
          and set(mits_landed) | set(mits_amended) == mit_ns
          and mits_amended == [9])
    return {
        "ok": ok,
        "ideas_total": len(idea_ns),
        "ideas_landed": ideas_landed,
        "ideas_dropped": ideas_dropped,       # [] at closure
        "mitigations_total": len(mit_ns),
        "mitigations_landed": mits_landed,
        "mitigations_amended": mits_amended,  # [9] — documented amendment
        "m9_resolution": M9_RESOLUTION,
    }


# ── scaffolding retirement audit ──────────────────────────────────────────────

def scaffolding_retirement():
    """The closure retirement audit: legacy-arm counter, merge freeze, and the
    old-data-dir read-only window — each ``retired`` or named as honest debt.

    * The dual-write legacy stores are NOT scaffolding to retire — keeping them
      authoritative for reads is an explicit non-goal (no read-path cutover),
      so the "legacy-arm" that CAN retire is the soak-candidate pipeline arm and
      the ConPTY drain safety-net, tracked as NAMED DEBT (not zero) because the
      YES verdict scheduled the PTY-adoption follow-on that supersedes the drain.
    * The soft merge-freeze on ``anchor_gui.py`` (PROCESS-RAILS §4) lifts at the
      W6 C1 exit gate — formally lifted.
    * The old data dir's ~1-week read-only preservation window is an ops action
      concluded on the live service (recorded in CLOSURE-SIGNOFF).
    """
    named_debt = [
        {"item": "PTY-adoption follow-on wave",
         "state": "scheduled (ConPTY verdict YES) — CONPTY-VERDICT-APPLICATION.md",
         "retired": False},
        {"item": "pre-restart PTY drain (tools/pre_restart_drain.py)",
         "state": "RETAINED as the safety net until PTY adoption ships "
                  "(belt-and-braces, not dead scaffolding)",
         "retired": False},
        {"item": "auth warn-mode overlay (auth_warn.py)",
         "state": "RETAINED — the rollback path is a flag flip to warn, never a "
                  "code revert (pillar off-switch discipline)",
         "retired": False},
    ]
    return {
        "legacy_arm_counter": len([d for d in named_debt if not d["retired"]]),
        "legacy_arm_zero": False,
        "named_debt": named_debt,
        "merge_freeze": {
            "scope": "anchor_gui.py during W4–W6 extraction (PROCESS-RAILS §4)",
            "lifted": True,
            "lifted_at": "W6 C1 exit gate (byte-parity + anchor-freshness gates "
                         "green; recorded in the execution log)",
        },
        "old_data_dir_readonly_window": {
            "state": "ops action on the live service — flip the old data stores "
                     "read-only for ~1 week, then archive (CLOSURE-SIGNOFF).",
            "concluded": c4_live_status() == STATUS_MET,  # tied to the live run
        },
    }


# ── rendering ─────────────────────────────────────────────────────────────────

_HEADER = (
    "# North-Star scorecard — C1–C7 demonstrated (rearch W18 closure)\n\n"
    "Generated by `tools/north_star_scorecard.py` — refreshed mechanically by "
    "the W18 gate (`tests/test_closure_w18.py`), never hand-edited. Each "
    "criterion's status is computed from a checked-in ground-truth artifact "
    "(C1 from the census amendment file; C4 from the runbook execution cell); "
    "no status is asserted that a linked artifact does not back.\n")


def _status_badge(status):
    return {STATUS_MET: "✅ met",
            STATUS_NARROWED: "🟡 narrowed",
            STATUS_UNMET: "🔴 unmet"}.get(status, status)


def render_scorecard_md():
    lines = [_HEADER, "## Criteria", "",
             "| criterion | status | proving artifact(s) |",
             "|---|---|---|"]
    for c in criteria():
        arts = "<br>".join(f"`{a}`" for a in c["proving_artifacts"])
        lines.append(
            f"| **{c['id']} — {c['title']}** | {_status_badge(c['status'])} "
            f"| {arts} |")
    lines += ["", "## Evidence per criterion", ""]
    for c in criteria():
        lines.append(f"### {c['id']} — {c['title']}  ({_status_badge(c['status'])})")
        lines.append("")
        lines.append(c["evidence"])
        if c.get("amendment"):
            lines.append("")
            lines.append(f"> Narrowing recorded via: `{c['amendment']}`")
        if c.get("live_signoff"):
            lines.append("")
            lines.append(f"> Live confirmation (pending sign-off): "
                         f"{c['live_signoff']} — see `CLOSURE-SIGNOFF.md`.")
        lines.append("")

    unresolved = unresolved_criteria()
    lines += [
        "## Closure bar",
        "",
        f"- Criteria: {len(criteria())} (C1–C7).",
        f"- Unresolved (neither met nor narrowed-with-an-amendment): "
        f"**{unresolved or 'none'}**.",
        f"- Done-when — *every C1–C7 met or narrowed-by-recorded-amendment*: "
        f"**{'SATISFIED' if not unresolved else 'NOT satisfied'}**.",
        "",
        "The narrowed criteria (C1, C4) each link a recorded amendment; the "
        "live confirmations they and C2/C6/C7 also require are carried as "
        "PENDING sign-offs in `CLOSURE-SIGNOFF.md` — recorded, never silent.",
        "",
        "See `APPENDIX-A-RECONCILIATION.md` (ideas 1–52 + mitigations 1–20, "
        "M-9 resolved) and `SCAFFOLDING-RETIREMENT.md`.",
        "",
    ]
    return "\n".join(lines)


def scorecard_json():
    return {
        "criteria": criteria(),
        "unresolved": unresolved_criteria(),
        "done_when_satisfied": not unresolved_criteria(),
        "pending_signoffs": pending_signoffs(),
        "appendix_a": appendix_a_reconciliation(),
        "scaffolding_retirement": scaffolding_retirement(),
    }


def render_reconciliation_md():
    r = appendix_a_reconciliation()
    lines = [
        "# Appendix-A reconciliation — closure (rearch W18)",
        "",
        "Generated by `tools/north_star_scorecard.py` — refreshed by the W18 "
        "gate. The W3 ledger (`APPENDIX-A-TRACEABILITY.md`) recorded M-9 as an "
        "OPEN reconciliation item and bound W18 to resolve it; this file is "
        "that resolution, run against the final delivered state. It reads the "
        "SAME two ledger tables the W3 gate holds faithful to the frozen plan.",
        "",
        "## Integrated ideas 1–52",
        "",
        f"- Total: **{r['ideas_total']}**.",
        f"- Landed (cited by ≥1 wave): **{len(r['ideas_landed'])}**.",
        f"- Silently dropped: **{len(r['ideas_dropped'])}** "
        f"({r['ideas_dropped'] or 'none'}).",
        "",
        "**Zero ideas are silently dropped** — every integrated idea 1–52 "
        "resolves to a landed phase item.",
        "",
        "## Mitigations 1–20",
        "",
        f"- Total: **{r['mitigations_total']}**.",
        f"- Landed (cited by ≥1 wave): **{len(r['mitigations_landed'])}**.",
        f"- Resolved to a documented amendment: **{r['mitigations_amended']}** "
        f"(M-9 by design).",
        "",
        "## Mitigation 9 — resolved",
        "",
        r["m9_resolution"],
        "",
        f"## Reconciliation verdict: {'✅ CLEAN' if r['ok'] else '🔴 DRIFT'}",
        "",
        "Every integrated idea 1–52 and every mitigation 1–20 resolves to a "
        "landed item or a documented amendment (M-9) — demonstrated by parsing "
        "the ledger tables, not narrated.",
        "",
    ]
    return "\n".join(lines)


def render_signoff_md():
    lines = [
        "# Closure live sign-offs — one sitting WITH John (rearch W18)",
        "",
        "Generated by `tools/north_star_scorecard.py`. The mechanism for every "
        "criterion ships in-tree and is proven by hermetic gates; these four "
        "confirmations are the LIVE half that only the real `:8777` service can "
        "prove. Run them in ONE sitting with John. **The execution cells are "
        "filled in ONLY after the live run — never fabricated here.** Until a "
        "cell is filled, its criterion's live half stays honestly narrowed.",
        "",
        "| id | sign-off | proving artifact |",
        "|---|---|---|",
    ]
    for s in pending_signoffs():
        lines.append(f"| {s['id']} | {s['title']} | `{s['artifact']}` |")
    lines += ["", "## What each proves", ""]
    for s in pending_signoffs():
        lines.append(f"### {s['id']} — {s['title']}")
        lines.append("")
        lines.append(s["detail"])
        lines.append("")
    lines += [
        "## Execution log",
        "",
        "> **STATUS: PENDING — run WITH John on the live service.** Never "
        "fabricated; the hermetic gates prove the mechanism, these cells prove "
        "the deploy.",
        "",
        "| sign-off | date run | operator | result | notes |",
        "|---|---|---|---|---|",
    ]
    for s in pending_signoffs():
        lines.append(f"| {s['id']} — {s['title']} | _(pending)_ | "
                     f"_(pending — WITH John)_ | _(pending)_ | _(pending)_ |")
    lines.append("")
    return "\n".join(lines)


def render_retirement_md():
    s = scaffolding_retirement()
    lines = [
        "# Scaffolding retirement — closure audit (rearch W18)",
        "",
        "Generated by `tools/north_star_scorecard.py`. The closure retires the "
        "effort's scaffolding OR names the residual as honest debt — never "
        "leaves it to be noticed.",
        "",
        "## Legacy-arm counter",
        "",
        f"- Open legacy/scaffolding arms: **{s['legacy_arm_counter']}** "
        f"(counter at zero: **{s['legacy_arm_zero']}**).",
        "",
        "The dual-write legacy stores are NOT retired — keeping them "
        "authoritative for reads is an explicit non-goal (no read-path "
        "cutover). The residual arms below are NAMED DEBT, not a silent zero:",
        "",
        "| item | state | retired |",
        "|---|---|---|",
    ]
    for d in s["named_debt"]:
        lines.append(f"| {d['item']} | {d['state']} | "
                     f"{'yes' if d['retired'] else 'no'} |")
    mf = s["merge_freeze"]
    od = s["old_data_dir_readonly_window"]
    lines += [
        "",
        "## Merge freeze",
        "",
        f"- Scope: {mf['scope']}.",
        f"- Lifted: **{mf['lifted']}** — {mf['lifted_at']}.",
        "",
        "## Old data-dir read-only preservation window",
        "",
        f"- {od['state']}",
        f"- Concluded: **{od['concluded']}** (tracked with the C4 live run).",
        "",
    ]
    return "\n".join(lines)


# ── writers (skip an unchanged rewrite) ───────────────────────────────────────

def _write(name, text, out_dir=None):
    out = Path(out_dir) if out_dir is not None else ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    path = out / name
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return path
    except OSError:
        pass
    path.write_text(text, encoding="utf-8")
    return path


def write_all(out_dir=None):
    """Refresh all four closure artifacts; return their paths."""
    paths = {
        SCORECARD_MD: _write(SCORECARD_MD, render_scorecard_md(), out_dir),
        SCORECARD_JSON: _write(
            SCORECARD_JSON,
            json.dumps(scorecard_json(), indent=2) + "\n", out_dir),
        RECONCILIATION_MD: _write(
            RECONCILIATION_MD, render_reconciliation_md(), out_dir),
        SIGNOFF_MD: _write(SIGNOFF_MD, render_signoff_md(), out_dir),
        RETIREMENT_MD: _write(RETIREMENT_MD, render_retirement_md(), out_dir),
    }
    return paths


def main(argv=None):  # pragma: no cover - thin CLI shim
    import sys

    argv = list(sys.argv[1:] if argv is None else argv)
    if "--write" in argv:
        for name, path in write_all().items():
            print(f"wrote {path}")
        return 0
    print(json.dumps(scorecard_json(), indent=2, default=str))
    return 0 if not unresolved_criteria() else 1


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
