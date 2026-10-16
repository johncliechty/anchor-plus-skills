"""Wave 8 — Anvil Codebase Hygiene, Status-Summary De-Bloating & Collaborator-Sharing Readiness (2026-10-15)."""
from __future__ import annotations

import ast
import json
from pathlib import Path

from steward_cockpit import steward_campaign as sc
from steward_cockpit import high_seat_card as hsc
from steward_cockpit import campaign_acts as ca
from steward_cockpit import campaign_say as cs
import desk


REPO = Path(__file__).resolve().parents[1]


def test_work_product_map_projects_lightweight_steps_without_megabyte_refinement_blobs():
    steps = [
        {
            "id": "s1",
            "name": "Build Lecture 4",
            "status": "done",
            "part": "slice",
            "refinement": {
                "round": 2,
                "display_round": 2,
                "phase": "accepted",
                "work_phase": "done",
                "producer_handoffs": [{"blob": "x" * 100000}],
                "revisions": {"r1": {"blob": "y" * 100000}},
                "presentations": [{"id": "p1"}],
                "requirements": {"req": "z" * 50000},
            },
        }
    ]
    wmap = sc.work_product_map(steps)
    assert len(wmap) == 1
    st = wmap[0]["steps"][0]
    assert st["id"] == "s1"
    assert st["name"] == "Build Lecture 4"
    assert st["refinement"] == {
        "round": 2,
        "display_round": 2,
        "phase": "accepted",
        "work_phase": "done",
    }
    assert "producer_handoffs" not in st["refinement"]
    assert "revisions" not in st["refinement"]
    # Original step dict is untouched for /api/map
    assert "producer_handoffs" in steps[0]["refinement"]


def test_mba_teaching_ai_status_summary_is_debloated():
    p = REPO.parent / "MBA Teaching AI" / ".ecgberht" / "status-summary.json"
    if p.is_file():
        # Was 5,076,573 bytes (5.07 MB) before Wave 8; now ~130 KB (< 250 KB)
        assert p.stat().st_size < 250_000


def test_high_seat_card_status_html_unwraps_grouped_work_map_and_formats_dict_project(monkeypatch, tmp_path):
    fake_status = {
        "at": "2026-10-15 15:10",
        "lead_line": "Next: Review Lecture 5",
        "compact": {"facts": [{"label": "Effort", "value": "MBA Teaching AI"}]},
        "project": {"brief": "Design MBA AI course", "parts": "slice ▶", "steps_done": 4, "steps_total": 9},
        "work_map": [
            {
                "tag": "",
                "label": "Outline",
                "done": 4,
                "total": 9,
                "steps": [
                    {"id": "lecture-4", "name": "Build Lecture 4", "status": "done"},
                    {"id": "lecture-5", "name": "Build Lecture 5", "status": "waiting", "waiting_on": "Review plan"},
                ],
            }
        ],
    }
    monkeypatch.setattr(hsc, "_live_engine", lambda _cdir: None)
    monkeypatch.setattr(hsc.campaign, "status_for_pane", lambda *_a, **_k: fake_status)
    monkeypatch.setattr(hsc, "repairs_html", lambda *_a, **_k: "")

    html = hsc.status_html(str(tmp_path / "mba-project"), "pid123")
    assert "4/9 steps done · slice ▶" in html
    assert "{'brief':" not in html
    assert "Build Lecture 4" in html
    assert "Build Lecture 5" in html


def test_portable_workspace_paths_and_zero_personal_user_paths():
    # campaign_acts & campaign_say resolve Ecgberht dynamically without hardcoded workspace literals
    ca_src = (REPO / "steward_cockpit" / "campaign_acts.py").read_text(encoding="utf-8")
    cs_src = (REPO / "steward_cockpit" / "campaign_say.py").read_text(encoding="utf-8")
    legacy_win = "C:" + "\\dev\\" + "Ecgberht"
    legacy_posix = "C:" + "/dev/" + "Ecgberht"
    assert legacy_win not in ca_src
    assert legacy_posix not in ca_src
    assert legacy_posix not in cs_src
    assert ca.ECG.name == "ecgberht.mjs"
    assert cs.DIALOGUE.endswith("/engine/dialogue.mjs")
    assert desk.desk_dir().name == "Desk"

    # provider-setup.js and steward_routes.py have zero personal profile references
    ps_js = (REPO / "static" / "provider-setup.js").read_text(encoding="utf-8")
    sr_py = (REPO / "steward_cockpit" / "steward_routes.py").read_text(encoding="utf-8")
    prof_pat = "Users\\" + "john"
    assert prof_pat not in ps_js
    assert prof_pat not in sr_py


def test_campaign_page_lead_has_no_unreachable_code():
    src = (REPO / "campaign_page.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_lead":
            assert len(node.body) == 2  # docstring + return None
            break
    else:
        raise AssertionError("_lead function not found in campaign_page.py")


def test_dist_manifest_includes_all_active_first_party_modules():
    manifest = (REPO / "dist_manifest.txt").read_text(encoding="utf-8")
    for mod in (
        "foundry_page.py",
        "health_state.py",
        "home_rows.py",
        "desk.py",
        "desk_page.py",
        "campaign_page.py",
        "usage_allowance_monitor.py",
        "git_safety.py",
        "anchor_next.py",
        "usage_index.py",
        "steward_cockpit/campaign_acts.py",
        "steward_cockpit/campaign_parts.py",
        "steward_cockpit/campaign_say.py",
        "steward_cockpit/high_seat_card.py",
        "steward_cockpit/anvil_session.py",
    ):
        assert mod in manifest, f"{mod} missing from dist_manifest.txt"
