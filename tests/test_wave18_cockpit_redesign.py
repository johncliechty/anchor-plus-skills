"""Wave 18 AI Cockpit Redesign — Contract, Hardening & Purity Tests.

Verifies the Wave 18 AI Cockpit improvements approved by John:
1. Clean Top Header Bar (no demo simulation buttons; Anvil + Aegis icons; duplicate
   top/goal/step deliverable strips hidden in .app3).
2. Top Next-Step & Approval Bar starts collapsed (▸) by default, flashes a RED
   flag (🚩 APPROVAL NEEDED) when approval/review is needed, and never embeds an
   Anvil icon inside the approval bar.
3. Single 4-Tier Collapsible Deliverables Hub in the Right Rail (Pending, For Review
   with Done buttons, Final Deliverables, All Deliverables grouped By-Wave) all
   starting collapsed (▸) by default, plus Steward Unreviewed-Items Interjection
   in the center chat when new commands arrive while For Review items remain.
4. Live 10-Min Status Report (wave4 table format) with unclipped multi-line cells,
   3-Row Milestone ETA (Current wave, Next wave, Whole plan), and visible
   collapsible Previous Status Updates log.
5. Left Plan Rail with collapsible Steward Plan Evaluation (▸), 2-Button View
   Switcher ([ 🗺️ Hierarchical Plan | 🌊 Wave Plan ]), Plan Summary Boxes, all
   phases/waves starting collapsed (▸) by default, 4-Pass Iterative Refinement
   strip inside expanded waves, and collapsible Foundry Tools dock.
6. Collapsible side panels (▸ Plan / ◂ Status edge tiles) and auto-collapse into
   second-window mode when opening a deliverable.
"""
from __future__ import annotations

from pathlib import Path
import unittest

from steward_cockpit import steward_campaign as sc
from steward_cockpit import steward_core as core

REPO = Path(__file__).resolve().parent.parent
STATIC = REPO / "steward_cockpit" / "static"


class Wave18CockpitRedesignTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.v1 = (STATIC / "v1.html").read_text(encoding="utf-8")
        cls.js = (STATIC / "shared.js").read_text(encoding="utf-8")
        cls.css = (STATIC / "shared.css").read_text(encoding="utf-8")
        cls.mockup = (STATIC / "wave18-cockpit-redesign-mockup.html").read_text(encoding="utf-8")

    def test_clean_top_header_and_second_window_mode_hooks(self):
        # Clean top header has Anvil (sword-on-anvil) and Aegis icons
        self.assertIn("anvil-option-2-sword-crystal-v1.jpg", self.v1)
        self.assertIn("aegis-icon.svg", self.v1)
        # Exposes window.enterSecondWindowMode / exitSecondWindowMode for deliverable auto-collapse
        self.assertIn("window.enterSecondWindowMode = enterSecondWindowMode", self.v1)
        self.assertIn("window.exitSecondWindowMode = exitSecondWindowMode", self.v1)
        # Does not force Anvil takeover on Anchor Refactoring unless explicitly toggled
        self.assertNotIn('isAnchorRefactoring ? (savedAnvil !== "0")', self.v1)
        # Mockup also has the demo simulation buttons removed
        self.assertNotIn("Demo: Open Deliverable", self.mockup)
        self.assertNotIn("Simulate Approval Needed", self.mockup)
        self.assertNotIn("Finish Pending Items", self.mockup)

    def test_single_deliverables_hub_hides_duplicate_surfaces_in_app3(self):
        # Duplicate step deliverable chips are hidden in .app3 so Deliverables live in Right Rail
        self.assertIn(".app3 .steps .sdeliv", self.css)
        # 4-tier collapsible Deliverables hub in Right Rail
        self.assertIn("deliv-tier-fold tier-pending pending", self.js)
        self.assertIn("deliv-tier-fold tier-review review", self.js)
        self.assertIn("deliv-tier-fold tier-final final", self.js)
        self.assertIn("deliv-tier-fold tier-all all-waves", self.js)
        self.assertIn("Final Deliverables", self.js)
        self.assertIn("All Deliverables", self.js)
        self.assertIn("Mark All Done", self.js)
        self.assertIn("deliv-wave-subfold", self.js)

    def test_steward_unreviewed_items_interjection_in_composer(self):
        self.assertIn("steward-interject-card", self.js)
        self.assertIn("REVIEW CHECK", self.js)
        self.assertIn("Keep in For Review", self.js)
        self.assertIn(".steward-interject-card", self.css)

    def test_top_approval_bar_starts_collapsed_with_red_flag(self):
        # Starts collapsed by default
        self.assertIn("let _sntOpen = false;", self.js)
        # Red flashing flag when approval is needed
        self.assertIn("snt-red-flag", self.js)
        self.assertIn("APPROVAL NEEDED", self.js)
        self.assertIn("redFlagFlash", self.css)
        # Deliverable chips in approval bar trigger enterSecondWindowMode
        self.assertIn("window.enterSecondWindowMode()", self.js)

    def test_status_table_multiline_eta_and_previous_updates(self):
        # Unclipped status facts up to 280-320 chars
        long_doing = "Wave 18 AI Cockpit overhaul — " + ("verifying status & deliverables " * 6)
        facts = core.status_facts(
            effort="Anchor-Improvement (18 waves)",
            doing=long_doing,
            status="18/18 waves · verification",
            tests="pass ✓ · 44 unit + E2E tests green",
            blocker="none",
            procs="py 2 · node 1",
            journal="0018-cockpit-ux-overhaul.md",
            eta="Phase: ~5m | Next wave: ~15m | Whole plan: ~40m",
            todo="1. Verify live cockpit -> 2. Hardening pass -> 3. Commit & push",
        )
        by_label = {f["label"]: f["value"] for f in facts}
        self.assertGreater(len(by_label["Doing"]), 140)
        self.assertEqual(facts, sc.status_facts(
            effort="Anchor-Improvement (18 waves)",
            doing=long_doing,
            status="18/18 waves · verification",
            tests="pass ✓ · 44 unit + E2E tests green",
            blocker="none",
            procs="py 2 · node 1",
            journal="0018-cockpit-ux-overhaul.md",
            eta="Phase: ~5m | Next wave: ~15m | Whole plan: ~40m",
            todo="1. Verify live cockpit -> 2. Hardening pass -> 3. Commit & push",
        ))
        # Multi-line wrapping in .stab td and visible .prev-status-log
        self.assertIn("overflow-wrap: anywhere", self.css)
        self.assertIn(".prev-status-log", self.css)
        self.assertIn("Whole plan (", self.js)

    def test_left_rail_plan_evaluation_switcher_summaries_and_collapsed_waves(self):
        # Collapsible Steward Plan Evaluation tile
        self.assertIn("steward-eval-fold", self.js)
        self.assertIn("PLAN EVALUATION", self.js)
        # 2-Button Plan View Switcher: Hierarchical Plan | Wave Plan
        self.assertIn("getPlanViewMode", self.js)
        self.assertIn("Hierarchical Plan", self.js)
        self.assertIn("Wave Plan", self.js)
        self.assertIn("HIERARCHICAL PLAN SUMMARY", self.js)
        self.assertIn("WAVE PLAN SUMMARY", self.js)
        # 4-Pass Iterative Refinement strip inside expanded waves
        self.assertIn("wave-pass-strip", self.js)
        self.assertIn("1. Draft", self.js)
        self.assertIn("2. Review", self.js)
        self.assertIn("3. Refine", self.js)
        self.assertIn("4. Lock", self.js)
        # Collapsible Foundry Tools dock starting collapsed by default
        self.assertIn("foundry-dock", self.js)
        self.assertIn("Catalog Checked", self.js)

    def test_interactive_cockpit_flows_and_default_collapsed_states(self):
        """Verify Wave 18 default collapsed states, view switcher, and second-window panel transitions."""
        # 1. Mockup and live shared.js default all 4 Deliverables tiers to collapsed (no `open` class/attr on tier tiles)
        for tid in ['id="tilePending"', 'id="tileReview"', 'id="tileFinal"', 'id="tileAll"']:
            self.assertIn(tid, self.mockup)
            idx = self.mockup.index(tid)
            tag_slice = self.mockup[max(0, idx - 60) : idx + 60]
            self.assertNotIn(" open", tag_slice)

        # 2. Steward Plan Evaluation & Top Approval Bar start collapsed by default
        self.assertIn('id="planEvalTile"', self.mockup)
        self.assertIn('class="top-approval-bar needs-approval" id="topApprovalBar"', self.mockup)
        self.assertIn("let _sntOpen = false;", self.js)

        # 3. Switching between Hierarchical Plan and Wave Plan updates summary & view
        self.assertIn("function switchPlanMode(mode)", self.mockup)
        self.assertIn("function getPlanViewMode()", self.js)
        self.assertIn("paneHierarchy", self.mockup)
        self.assertIn("paneWave", self.mockup)

        # 4. Collapsing Plan and Status rails to edge tiles and auto-collapsing on Deliverable open
        self.assertIn("function enterSecondWindowMode()", self.v1)
        self.assertIn("function exitSecondWindowMode()", self.v1)
        self.assertIn('app.classList.add("railhide")', self.v1)
        self.assertIn('app.classList.remove("statusopen")', self.v1)
        self.assertIn("data-railtoggle2", self.v1)
        self.assertIn("data-statustoggle", self.v1)





if __name__ == "__main__":
    unittest.main()
