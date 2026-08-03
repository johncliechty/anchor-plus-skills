"""rearch W18 (C7) — Closure: Hybrid Hardening + North-Star Scorecard.

Covers the frozen Wave-20 deliverables + acceptance, in the honest hermetic
form (the one-sitting LIVE sign-offs WITH John are the ``CLOSURE-SIGNOFF.md``
execution cells, marked PENDING until run):

  * the **North-Star scorecard** (``tools/north_star_scorecard.py`` →
    ``NORTH-STAR-SCORECARD.md`` / ``.json``) — C1–C7 each ``met`` /
    ``narrowed`` / ``unmet`` with its proving gate artifact linked; the closure
    bar (every criterion met OR narrowed-by-recorded-amendment; zero unresolved)
    is DEMONSTRATED, not narrated. C1's status reads the census amendment file;
    C4's reads the runbook execution cell (both computed, never asserted);
  * the **Appendix-A reconciliation** (``APPENDIX-A-RECONCILIATION.md``) — every
    integrated idea 1–52 lands, every mitigation 1–20 resolves to a wave or a
    documented amendment (M-9), zero silently dropped — parsed from the W3
    ledger tables, so it stays faithful to the frozen plan;
  * the **finalized hybrid-state matrix** (``pillar_flags.MATRIX_FINALIZED`` +
    ``assert_matrix_finalized``) — every named combination carries a one-line
    support statement;
  * the **four-walk soak-gated join** (``anchor_healthcheck``) — the four new
    walks (journal parity · supervisor probes · cookie/auth · relocated-data-dir)
    and the ``soak_ready`` gate that joins the two still-soaking walks to the
    5AM run only after 20 consecutive green nightly repetitions;
  * the **relocated-data-dir walk** (C6) — proves runtime state relocates
    outside the repo, hermetically;
  * the **C4 runbook re-confirmation** — the phased CLI (``--phase
    launch/verify/rollback``) that makes the runbook's live commands executable,
    fixing the two open findings (invalid ``--simulate-restart:$false`` syntax;
    a rollback that started a new demo instead of cleaning the live job).

Hermetic: temp dirs + a seeded soak ledger; never real claude / port 8777 /
real data. Every artifact test REFRESHES the checked-in doc first (the gate is
its producer, like the W1 census + W3 pillar-matrix artifacts).
"""
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
ARTIFACT_DIR = REPO / "planning" / "rearch-2026-07"

sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "tools"))

import pillar_flags as pf                                   # noqa: E402
from tools import north_star_scorecard as sc               # noqa: E402


# ══════════════════════════════════════════════════════════════════════════
# 1) North-Star scorecard — C1–C7 demonstrated
# ══════════════════════════════════════════════════════════════════════════

class TestScorecardCriteria:
    def test_all_seven_criteria_present_and_ordered(self):
        ids = [c["id"] for c in sc.criteria()]
        assert ids == ["C1", "C2", "C3", "C4", "C5", "C6", "C7"]

    def test_every_criterion_has_a_status_and_a_proving_artifact(self):
        for c in sc.criteria():
            assert c["status"] in (sc.STATUS_MET, sc.STATUS_NARROWED,
                                   sc.STATUS_UNMET), c["id"]
            assert c["proving_artifacts"], f"{c['id']} links no proving artifact"
            assert c["evidence"].strip(), f"{c['id']} has no evidence"

    def test_no_criterion_is_bare_unmet_the_done_when_bar(self):
        """The done-when: every C1–C7 is met OR narrowed-by-recorded-amendment.
        ``unresolved_criteria`` returns anything that is neither — empty at
        closure."""
        assert sc.unresolved_criteria() == []
        for c in sc.criteria():
            assert c["status"] != sc.STATUS_UNMET, c["id"]

    def test_every_narrowing_links_a_recorded_amendment(self):
        for c in sc.criteria():
            if c["status"] == sc.STATUS_NARROWED:
                assert c.get("amendment"), \
                    f"{c['id']} is narrowed but links no amendment artifact"

    def test_c1_is_narrowed_while_the_census_amendment_stands(self):
        """C1's status is COMPUTED from the census amendment file — narrowed
        while it exists (the include-layer amendment), met when it is gone."""
        amend = ARTIFACT_DIR / sc.C1_AMENDMENT
        expected = sc.STATUS_NARROWED if amend.exists() else sc.STATUS_MET
        assert sc.c1_status() == expected
        c1 = next(c for c in sc.criteria() if c["id"] == "C1")
        assert c1["status"] == expected

    def test_c4_live_half_is_narrowed_until_the_runbook_runs(self):
        """C4's status is COMPUTED from the runbook execution cell — narrowed
        while it reads NOT YET RUN, met once the live cell is filled in."""
        md = (ARTIFACT_DIR / sc.C4_RUNBOOK).read_text(encoding="utf-8")
        expected = (sc.STATUS_NARROWED if sc.C4_NOT_RUN_SENTINEL in md
                    else sc.STATUS_MET)
        assert sc.c4_live_status() == expected

    def test_proving_artifact_paths_exist(self):
        """Each linked proving artifact that is a real path (not a symbol like
        ``module::Class`` or ``foo.bar``) resolves in the repo — the scorecard
        cannot link a phantom gate."""
        for c in sc.criteria():
            for art in c["proving_artifacts"]:
                head = art.split("::")[0].split(" ")[0]
                if "/" not in head:
                    continue                       # a symbol, not a file path
                assert (REPO / head).exists(), f"{c['id']} → missing {head}"

    def test_scorecard_json_reports_the_closure_bar(self):
        j = sc.scorecard_json()
        assert j["done_when_satisfied"] is True
        assert j["unresolved"] == []
        assert len(j["criteria"]) == 7
        assert j["pending_signoffs"]        # the live sign-offs are carried


class TestScorecardArtifacts:
    def test_scorecard_md_is_gate_refreshed_and_faithful(self, tmp_path):
        # a stale copy is repaired to the mechanical rendering
        stale = tmp_path / sc.SCORECARD_MD
        stale.write_text("# drift\n", encoding="utf-8")
        sc._write(sc.SCORECARD_MD, sc.render_scorecard_md(), out_dir=tmp_path)
        assert stale.read_text(encoding="utf-8") == sc.render_scorecard_md()
        # refresh the CHECKED-IN artifacts and hold them faithful
        paths = sc.write_all()
        md = paths[sc.SCORECARD_MD].read_text(encoding="utf-8")
        assert md == sc.render_scorecard_md()
        for cid in ("C1", "C2", "C3", "C4", "C5", "C6", "C7"):
            assert cid in md
        assert "SATISFIED" in md

    def test_signoff_doc_carries_the_four_live_signoffs_pending(self):
        sc.write_all()
        md = (ARTIFACT_DIR / sc.SIGNOFF_MD).read_text(encoding="utf-8")
        for so in ("SO-C4", "SO-C2", "SO-C6", "SO-SMOKE"):
            assert so in md
        assert "PENDING" in md
        assert "nssm restart anchor" in md      # the C4 re-confirmation


# ══════════════════════════════════════════════════════════════════════════
# 2) Appendix-A reconciliation (ideas 1–52 + mitigations 1–20, M-9)
# ══════════════════════════════════════════════════════════════════════════

class TestAppendixAReconciliation:
    def test_every_idea_lands_zero_silently_dropped(self):
        r = sc.appendix_a_reconciliation()
        assert r["ideas_total"] == 52
        assert len(r["ideas_landed"]) == 52
        assert r["ideas_dropped"] == []

    def test_mitigations_resolve_with_m9_as_documented_amendment(self):
        r = sc.appendix_a_reconciliation()
        assert r["mitigations_total"] == 20
        assert r["mitigations_amended"] == [9]      # M-9 only, by design
        assert set(r["mitigations_landed"]) == set(range(1, 21)) - {9}
        assert r["ok"] is True

    def test_m9_resolution_is_a_documented_amendment_not_a_silent_drop(self):
        r = sc.appendix_a_reconciliation()
        res = r["m9_resolution"]
        assert "documented amendment" in res
        assert "never a silent drop" in res.lower()

    def test_reconciliation_doc_is_gate_refreshed(self):
        sc.write_all()
        md = (ARTIFACT_DIR / sc.RECONCILIATION_MD).read_text(encoding="utf-8")
        assert md == sc.render_reconciliation_md()
        assert "Mitigation 9 — resolved" in md
        assert "CLEAN" in md


class TestScaffoldingRetirement:
    def test_named_debt_is_carried_not_a_silent_zero(self):
        s = sc.scaffolding_retirement()
        assert s["legacy_arm_counter"] == len(s["named_debt"])
        assert s["named_debt"], "residual scaffolding must be named, not hidden"
        # the merge freeze is formally lifted at the W6 exit gate
        assert s["merge_freeze"]["lifted"] is True
        assert "W6" in s["merge_freeze"]["lifted_at"]

    def test_retirement_doc_is_gate_refreshed(self):
        sc.write_all()
        md = (ARTIFACT_DIR / sc.RETIREMENT_MD).read_text(encoding="utf-8")
        assert md == sc.render_retirement_md()
        assert "Merge freeze" in md
        assert "read-only" in md.lower()


# ══════════════════════════════════════════════════════════════════════════
# 3) Finalized hybrid-state matrix
# ══════════════════════════════════════════════════════════════════════════

class TestMatrixFinalized:
    def test_matrix_is_marked_finalized(self):
        assert pf.MATRIX_FINALIZED is True

    def test_every_named_combination_has_a_one_line_support_statement(self):
        pf.assert_matrix_finalized()             # raises loudly on any gap
        for row in pf.HYBRID_STATE_MATRIX:
            assert (row.get("support") or "").strip(), row["name"]

    def test_finalize_invariant_fails_loudly_on_a_missing_support(self, monkeypatch):
        broken = tuple(dict(r) for r in pf.HYBRID_STATE_MATRIX)
        broken[0]["support"] = "   "
        monkeypatch.setattr(pf, "HYBRID_STATE_MATRIX", broken)
        with pytest.raises(pf.PillarStateError):
            pf.assert_matrix_finalized()


# ══════════════════════════════════════════════════════════════════════════
# 4) The four new walks + the soak-gated 5AM join
# ══════════════════════════════════════════════════════════════════════════

@pytest.fixture
def hc(monkeypatch, tmp_path):
    """anchor_healthcheck with a clean env (no live service touched)."""
    monkeypatch.delenv("ANCHOR_DATA_DIR", raising=False)
    import anchor_healthcheck as _hc
    return _hc


class TestFourNewWalks:
    def test_registry_names_exactly_the_four_process_rails_walks(self, hc):
        names = [n for (n, _) in hc.four_new_walks()]
        assert names == [
            "journal parity gate (classify + recover)",
            "supervisor live probes (W16)",
            "cookie/auth walk (W9)",
            "relocated data-dir walk (W11/W18)",
        ]

    def test_the_two_soak_gated_walks_are_the_not_yet_joined_pair(self, hc):
        names = [n for (n, _) in hc.SOAK_GATED_WALKS]
        assert names == ["cookie/auth walk (W9)",
                         "relocated data-dir walk (W11/W18)"]
        # soak_candidate_walks (the --soak pipeline) is exactly this pair
        assert hc.soak_candidate_walks() == hc.SOAK_GATED_WALKS

    def test_relocated_data_dir_walk_passes_hermetically(self, hc):
        report = hc.Report()
        hc.check_relocated_data_dir(report)
        name, ok, detail = report.checks[-1]
        assert "relocated data-dir" in name
        assert ok, detail
        assert not report.has_issues

    def test_relocated_data_dir_walk_restores_the_env(self, hc, monkeypatch):
        monkeypatch.setenv("ANCHOR_DATA_DIR", "C:/some/original")
        hc.check_relocated_data_dir(hc.Report())
        import os
        assert os.environ["ANCHOR_DATA_DIR"] == "C:/some/original"

    def test_cookie_auth_walk_passes_hermetically(self, hc):
        report = hc.Report()
        hc.check_cookie_auth_walk(report)
        _, ok, detail = report.checks[-1]
        assert ok, detail


class TestSoakGatedJoin:
    def _seed(self, ledger, hc, name, n, passed=True):
        for _ in range(n):
            hc.record_soak_result(name, passed, ledger_path=ledger)

    def test_join_is_empty_on_a_fresh_ledger(self, hc, tmp_path):
        ledger = tmp_path / "soak.jsonl"
        assert hc.joined_soak_walks(ledger_path=ledger) == ()

    def test_a_walk_joins_only_after_twenty_green(self, hc, tmp_path):
        ledger = tmp_path / "soak.jsonl"
        name = "cookie/auth walk (W9)"
        self._seed(ledger, hc, name, hc.SOAK_TARGET_REPETITIONS - 1)
        assert not hc.soak_ready(name, ledger_path=ledger)
        assert name not in [n for (n, _) in
                            hc.joined_soak_walks(ledger_path=ledger)]
        self._seed(ledger, hc, name, 1)             # the 20th green
        assert hc.soak_ready(name, ledger_path=ledger)
        assert name in [n for (n, _) in
                        hc.joined_soak_walks(ledger_path=ledger)]

    def test_a_red_repetition_breaks_the_streak(self, hc, tmp_path):
        ledger = tmp_path / "soak.jsonl"
        name = "relocated data-dir walk (W11/W18)"
        self._seed(ledger, hc, name, hc.SOAK_TARGET_REPETITIONS)
        assert hc.soak_ready(name, ledger_path=ledger)
        self._seed(ledger, hc, name, 1, passed=False)   # a red night
        assert not hc.soak_ready(name, ledger_path=ledger)

    def test_all_four_join_the_5am_run_when_both_soaks_complete(self, hc, tmp_path):
        """The acceptance GWT: once BOTH soak-gated walks reach 20× green, the
        four new walks all run in the 5AM sequence (the two already-promoted
        journal/supervisor walks + the two now-joined)."""
        ledger = tmp_path / "soak.jsonl"
        for name, _ in hc.SOAK_GATED_WALKS:
            self._seed(ledger, hc, name, hc.SOAK_TARGET_REPETITIONS)
        joined = hc.run_joined_soak_walks(hc.Report(), ledger_path=ledger)
        assert set(joined) == {n for (n, _) in hc.SOAK_GATED_WALKS}


# ══════════════════════════════════════════════════════════════════════════
# 5) C4 runbook re-confirmation — the phased CLI (the two open findings)
# ══════════════════════════════════════════════════════════════════════════

class TestC4RunbookPhasedCLI:
    def _parser(self):
        from tools import c4_live_demo
        return c4_live_demo._build_parser()

    def test_phase_accepts_the_four_phases(self):
        p = self._parser()
        for phase in ("demo", "launch", "verify", "rollback"):
            assert p.parse_args(["--phase", phase]).phase == phase

    def test_verify_and_rollback_take_job_and_project_ids(self):
        ns = self._parser().parse_args(
            ["--phase", "verify", "--job-id", "j1", "--project-id", "p1"])
        assert ns.phase == "verify" and ns.job_id == "j1" and ns.project_id == "p1"

    def test_simulate_restart_is_a_bare_flag_not_a_valued_option(self):
        """The open finding: the runbook's ``--simulate-restart:$false`` is
        invalid — the flag is store_true, so a valued form must not parse."""
        p = self._parser()
        assert p.parse_args([]).simulate_restart is False
        assert p.parse_args(["--simulate-restart"]).simulate_restart is True
        with pytest.raises(SystemExit):
            p.parse_args(["--simulate-restart:$false"])

    def test_runbook_uses_the_phased_commands_not_the_broken_ones(self):
        """The runbook artifact no longer prescribes the two failing commands
        and does prescribe the phased forms (the two findings closed)."""
        md = (ARTIFACT_DIR / "C4-RUNBOOK.md").read_text(encoding="utf-8")
        assert "--simulate-restart:$false" not in md      # finding 1 closed
        assert "--phase launch" in md
        assert "--phase verify --job-id" in md
        assert "--phase rollback --job-id" in md          # finding 2 closed
        # the rollback command targets a job id, never re-runs a bare demo
        rollback_line = next(
            ln for ln in md.splitlines()
            if "--phase rollback" in ln and "c4_live_demo.py" in ln)
        assert "--job-id" in rollback_line
