"""Wave 3 oracle: interactive AI Cockpit THE PLAN rail, tools/steward_plan.py CLI + cross-process
serialization, Turn-1 EFFORT_RULES + plan capsule, Deliverable/Wave auto-completion into Cave's
reactive watcher, AGENTS.md embedded Cave tile & readable managed review link contracts, BA 815
hack purge, clean human deliverable titles/filenames, and the 5-state failure contract."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import textwrap

import pytest

import comms_connector as comms
import deliverables_register
import distro
import paths
from steward_cockpit import code_jobs
from steward_cockpit import steward_campaign as campaign
from steward_cockpit import steward_core as core
from steward_cockpit import steward_engine as engine
from steward_cockpit import steward_routes as routes
from tools import steward_plan


REPO_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def isolated_w3(tmp_path, monkeypatch):
    data_root = tmp_path / "anchor_data"
    data_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_root))
    monkeypatch.setenv("ANCHOR_COMMS_HERMETIC", "1")
    monkeypatch.setattr(engine, "STATE_FILE", data_root / "steward-cockpit-state.json")
    campaign._JSON_FILE_CACHE.clear()
    routes._DELIV_CACHE.clear()
    routes._STATE_CACHE.clear()
    return tmp_path


def _make_campaign(base: Path, name: str = "effort_alpha", *, with_face: bool = True) -> Path:
    cdir = base / name
    cdir.mkdir(parents=True, exist_ok=True)
    if with_face:
        (cdir / "ECGBERHT.md").write_text(
            "# Effort Alpha\n\nShip clean Functional Core plan and deliverables.\n",
            encoding="utf-8",
        )
    return cdir


def test_steward_plan_cli_all_verbs_idempotence_containment_and_200_cap(isolated_w3, capsys):
    # 1. Verify dist_manifest.txt registers tools/steward_plan.py for shipping
    manifest_text = (REPO_ROOT / "dist_manifest.txt").read_text(encoding="utf-8")
    assert "tools/steward_plan.py" in manifest_text
    shipped = {
        (p.relative_to(REPO_ROOT).as_posix() if hasattr(p, "relative_to") else str(p).replace("\\", "/"))
        for p in distro.select_shippable(REPO_ROOT)
    }
    assert "tools/steward_plan.py" in shipped

    cdir = _make_campaign(isolated_w3, "cli_campaign")

    # 2. Empty-but-valid status via CLI
    rc = steward_plan.main(["--dir", str(cdir), "status"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["ok"] is True
    assert out["failure_state"] == "empty-but-valid"
    assert out["steps"] == []
    assert out["message"] == steward_plan.MSG_EMPTY_VALID

    # 3. init via CLI
    init_steps = [
        {"id": "s1", "title": "Draft Architecture", "goal": "Write spec", "status": "active"},
        {"id": "s2", "title": "Implement Engine", "goal": "Pass unit tests", "status": "planned"},
    ]
    rc = steward_plan.main([
        "--dir", str(cdir),
        "init",
        "--goal", "Deliver Wave 3 Cockpit Overhaul",
        "--steps-json", json.dumps(init_steps),
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["counts"]["total"] == 2
    assert out["focus"]["step_id"] == "s1"
    assert out["goal"] == "Deliver Wave 3 Cockpit Overhaul"

    # 4. add-step + set-next via CLI
    rc = steward_plan.main([
        "--dir", str(cdir),
        "add-step",
        "--id", "s3",
        "--title", "Verify Live Surface",
        "--goal", "Zero regressions",
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert [s["id"] for s in out["steps"]] == ["s1", "s2", "s3"]

    rc = steward_plan.main([
        "--dir", str(cdir),
        "set-next",
        "--step-id", "s2",
        "--next-move", "Run full concurrency verification",
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["focus"]["step_id"] == "s2"
    assert out["focus"]["next_move"] == "Run full concurrency verification"

    # 5. reorder (direction + explicit order-json)
    rc = steward_plan.main(["--dir", str(cdir), "reorder", "--id", "s3", "--direction", "up"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert [s["id"] for s in out["steps"]] == ["s1", "s3", "s2"]

    rc = steward_plan.main([
        "--dir", str(cdir),
        "reorder",
        "--order-json", json.dumps(["s1", "s2", "s3"]),
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert [s["id"] for s in out["steps"]] == ["s1", "s2", "s3"]

    # 6. park & unpark + repeat-invocation idempotence
    rc = steward_plan.main(["--dir", str(cdir), "park", "--id", "s3", "--reason", "Defer to Wave 4"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["counts"]["parked"] == 1
    # Repeat park invocation is idempotent
    rc_dup = steward_plan.main(["--dir", str(cdir), "park", "--id", "s3", "--reason", "Defer to Wave 4"])
    out_dup = json.loads(capsys.readouterr().out)
    assert rc_dup == 0
    assert out_dup["counts"]["parked"] == 1
    assert len(out_dup["steps"]) == 3

    rc = steward_plan.main(["--dir", str(cdir), "park", "--id", "s3", "--unpark"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["counts"]["parked"] == 0

    # 7. set-step + complete-and-next (and repeat set-step idempotence)
    rc = steward_plan.main([
        "--dir", str(cdir),
        "set-step",
        "--id", "s1",
        "--title", "Draft Architecture v2",
        "--goal", "Approved spec",
        "--status", "active",
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["steps"][0]["title"] == "Draft Architecture v2"

    rc = steward_plan.main(["--dir", str(cdir), "complete-and-next", "--id", "s1"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["steps"][0]["done"] is True
    assert out["focus"]["step_id"] == "s2"

    # Repeat set-step done on s1 does not duplicate or corrupt focus
    rc = steward_plan.main(["--dir", str(cdir), "set-step", "--id", "s1", "--status", "done"])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["counts"]["done"] == 1
    assert out["focus"]["step_id"] == "s2"

    # 8. propose -> dismiss-proposal, then propose -> accept-proposal
    rc = steward_plan.main([
        "--dir", str(cdir),
        "propose",
        "--summary", "Add security review step",
        "--reason", "Gate before release",
        "--ops-json", json.dumps([{"op": "add_step", "id": "s4", "title": "Run Aegis Audit", "goal": "0 HIGH"}]),
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["proposal"] is not None
    prop_id = out["proposal"]["id"]

    rc = steward_plan.main(["--dir", str(cdir), "dismiss-proposal", "--proposal-id", prop_id])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["proposal"] is None
    assert [s["id"] for s in out["steps"]] == ["s1", "s2", "s3"]

    rc = steward_plan.main([
        "--dir", str(cdir),
        "propose",
        "--summary", "Add security review step (v2)",
        "--ops-json", json.dumps([{"op": "add_step", "id": "s4", "title": "Run Aegis Audit", "goal": "0 HIGH"}]),
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    prop_id_2 = out["proposal"]["id"]

    rc = steward_plan.main(["--dir", str(cdir), "accept-proposal", "--proposal-id", prop_id_2])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    assert out["proposal"] is None
    assert [s["id"] for s in out["steps"]] == ["s1", "s2", "s3", "s4"]

    # 9. register-deliverable writes DELIVERABLES.md + attaches to step + rejects path escape
    deliv_file = cdir / "deliverables" / "Engine_Spec.pdf"
    deliv_file.parent.mkdir(parents=True, exist_ok=True)
    deliv_file.write_bytes(b"%PDF-1.4 spec\n")

    rc = steward_plan.main([
        "--dir", str(cdir),
        "register-deliverable",
        "--path", "deliverables/Engine_Spec.pdf",
        "--title", "Engine Architecture Spec",
        "--step-id", "s2",
        "--status", "for_review",
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    s2_obj = next(s for s in out["steps"] if s["id"] == "s2")
    assert len(s2_obj["deliverables"]) == 1
    assert s2_obj["deliverables"][0]["title"] == "Engine Architecture Spec"
    assert (cdir / "DELIVERABLES.md").is_file()
    assert "Engine Architecture Spec" in (cdir / "DELIVERABLES.md").read_text(encoding="utf-8")

    # Repeat register-deliverable is idempotent (no duplicate entry on step or DELIVERABLES.md)
    rc = steward_plan.main([
        "--dir", str(cdir),
        "register-deliverable",
        "--path", "deliverables/Engine_Spec.pdf",
        "--title", "Engine Architecture Spec",
        "--step-id", "s2",
        "--status", "for_review",
    ])
    out = json.loads(capsys.readouterr().out)
    assert rc == 0
    s2_obj_again = next(s for s in out["steps"] if s["id"] == "s2")
    assert len(s2_obj_again["deliverables"]) == 1

    # Containment: traversal path "../outside.pdf" is refused with exit code 2 (400 validation error)
    rc_escape = steward_plan.main([
        "--dir", str(cdir),
        "register-deliverable",
        "--path", "../outside.pdf",
        "--title", "Escape Attempt",
        "--step-id", "s2",
    ])
    err_escape = json.loads(capsys.readouterr().out)
    assert rc_escape == 2
    assert err_escape["ok"] is False
    assert err_escape["failure_state"] == "dependency-returns-garbage"

    # 10. Boundedness: MAX_PLAN_STEPS = 200 allowed, 201st step refused across CLI and HTTP route
    cap_dir = _make_campaign(isolated_w3, "cap_campaign")
    steps_200 = [{"id": f"st-{i:03d}", "title": f"Step {i}"} for i in range(1, steward_plan.MAX_PLAN_STEPS + 1)]
    res_200 = steward_plan.mutate_plan_state(cap_dir, "init", {"steps": steps_200, "replace": True})
    assert res_200["ok"] is True
    assert len(res_200["steps"]) == 200

    rc_201 = steward_plan.main(["--dir", str(cap_dir), "add-step", "--title", "Step 201 Overflow"])
    out_201 = json.loads(capsys.readouterr().out)
    assert rc_201 == 2
    assert out_201["ok"] is False
    assert out_201["failure_state"] == "dependency-returns-garbage"
    assert out_201["message"] == steward_plan.MSG_DEPENDENCY_GARBAGE

    http_201, code_201 = routes.handle_post(str(cap_dir), "plan", {"op": "add_step", "title": "HTTP 201 Overflow"})
    assert code_201 == 400
    assert http_201["failure_state"] == "dependency-returns-garbage"
    assert http_201["message"] == steward_plan.MSG_DEPENDENCY_GARBAGE
    assert len(steward_plan.read_plan_state(cap_dir)["steps"]) == 200


def test_two_process_cli_and_http_plan_concurrency(isolated_w3):
    cdir = _make_campaign(isolated_w3, "concurrent_campaign")
    steward_plan.mutate_plan_state(cdir, "init", {"steps": [], "replace": True})

    n_per_worker = 10
    cli_worker_code = textwrap.dedent(
        """
        import sys
        from tools import steward_plan
        cdir = sys.argv[1]
        count = int(sys.argv[2])
        for i in range(count):
            rc = steward_plan.main([
                "--dir", cdir,
                "add-step",
                "--id", f"cli-{i:02d}",
                "--title", f"CLI Concurrent Step {i}",
                "--goal", f"CLI goal {i}",
            ])
            if rc != 0:
                sys.exit(rc)
        """
    )
    http_worker_code = textwrap.dedent(
        """
        import sys
        from steward_cockpit import steward_routes
        cdir = sys.argv[1]
        count = int(sys.argv[2])
        for i in range(count):
            body, status = steward_routes.handle_post(
                cdir,
                "plan",
                {
                    "op": "add_step",
                    "id": f"http-{i:02d}",
                    "title": f"HTTP Concurrent Step {i}",
                    "goal": f"HTTP goal {i}",
                },
            )
            if status != 200 or not body.get("ok"):
                sys.stderr.write(f"HTTP worker failed: {status} {body}\\n")
                sys.exit(3)
        """
    )

    env = dict(os.environ)
    env["PYTHONPATH"] = str(REPO_ROOT)
    env["ANCHOR_DATA_DIR"] = str(isolated_w3 / "anchor_data")
    env["ANCHOR_COMMS_HERMETIC"] = "1"

    p_cli = subprocess.Popen(
        [sys.executable, "-c", cli_worker_code, str(cdir), str(n_per_worker)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    p_http = subprocess.Popen(
        [sys.executable, "-c", http_worker_code, str(cdir), str(n_per_worker)],
        cwd=str(REPO_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    out_cli, err_cli = p_cli.communicate(timeout=45)
    out_http, err_http = p_http.communicate(timeout=45)
    assert p_cli.returncode == 0, f"CLI worker failed: {err_cli}\n{out_cli}"
    assert p_http.returncode == 0, f"HTTP worker failed: {err_http}\n{out_http}"

    # Verify zero lost updates and clean valid JSON on disk
    roadmap_disk = json.loads((cdir / "roadmap.json").read_text(encoding="utf-8"))
    strip_disk = json.loads((cdir / "strip.json").read_text(encoding="utf-8"))
    assert isinstance(roadmap_disk, dict)
    assert isinstance(strip_disk, dict)

    state = steward_plan.read_plan_state(cdir)
    ids = {s["id"] for s in state["steps"]}
    expected_ids = {f"cli-{i:02d}" for i in range(n_per_worker)} | {f"http-{i:02d}" for i in range(n_per_worker)}
    assert len(state["steps"]) == 2 * n_per_worker
    assert ids == expected_ids


def test_steward_engine_fence_turn1_effort_rules_and_plan_state_capsule(isolated_w3):
    # 1. Fence whitelist includes steward_plan.py and ecgberht.mjs
    assert any("tools/steward_plan.py" in entry for entry in engine.FENCE_ALLOWED_TOOLS)
    assert any("ecgberht.mjs" in entry for entry in engine.FENCE_ALLOWED_TOOLS)
    assert "steward_plan.py" in engine.FENCE_NOTE
    assert "ecgberht.mjs" in engine.FENCE_NOTE
    assert "tools/steward_plan.py" in engine.EFFORT_RULES

    # 2. Turn-1 EFFORT_RULES enabled on dedicated project cockpits even before roadmap.json exists
    fresh_cdir = _make_campaign(isolated_w3, "turn1_cockpit", with_face=False)
    assert not (fresh_cdir / "roadmap.json").exists()

    eng_dedicated = engine.Engine(str(fresh_cdir), fake=True)
    contract_dedicated = eng_dedicated._contract()
    assert "tools/steward_plan.py" in contract_dedicated
    assert "[PROJECT PLAN & DELIVERABLES CAPSULE]" in contract_dedicated
    assert "No plan steps yet" in contract_dedicated

    # General terminal, one-conversation cockpit, and code_job sessions omit EFFORT_RULES
    eng_general = engine.Engine(str(fresh_cdir), fake=True, general=True)
    assert "tools/steward_plan.py" not in eng_general._contract()

    eng_one = engine.Engine(str(fresh_cdir), fake=True)
    eng_one.one_conversation = True
    assert "tools/steward_plan.py" not in eng_one._contract()

    eng_code = engine.Engine(str(fresh_cdir), fake=True)
    eng_code.code_job = {"id": "cj-1"}
    assert "tools/steward_plan.py" not in eng_code._contract()

    # 3. _plan_state_capsule reflects focus, counts, pending proposal, and unaccepted review deliverables
    steward_plan.mutate_plan_state(
        fresh_cdir,
        "init",
        {
            "steps": [
                {"id": "w1", "title": "Build Core", "goal": "Core ready", "status": "done", "done": True},
                {"id": "w2", "title": "Build UI", "goal": "UI verified", "status": "active"},
                {"id": "w3", "title": "Optional Stretch", "goal": "Later", "status": "parked", "parked": True},
            ],
            "replace": True,
        },
    )
    steward_plan.mutate_plan_state(
        fresh_cdir,
        "propose",
        {
            "summary": "Insert Wave 2b accessibility check",
            "ops": [{"op": "add_step", "title": "Run keyboard check"}],
        },
    )
    rev_doc = fresh_cdir / "deliverables" / "UI_Mockup.pdf"
    rev_doc.parent.mkdir(parents=True, exist_ok=True)
    rev_doc.write_bytes(b"%PDF-1.4 ui\n")
    steward_plan.mutate_plan_state(
        fresh_cdir,
        "register_deliverable",
        {
            "path": "deliverables/UI_Mockup.pdf",
            "title": "Cockpit UI Mockup",
            "step_id": "w2",
            "status": "for_review",
        },
    )

    capsule = engine._plan_state_capsule(fresh_cdir)
    assert "1/2 done, 1 parked" in capsule
    assert "Build UI" in capsule
    assert "awaiting approval" in capsule
    assert "Insert Wave 2b accessibility check" in capsule
    assert "Cockpit UI Mockup" in capsule

    # Missing dir & unreadable roadmap.json report UNKNOWN, never empty
    missing_capsule = engine._plan_state_capsule(isolated_w3 / "does_not_exist")
    assert "UNKNOWN" in missing_capsule
    (fresh_cdir / "roadmap.json").write_text("{corrupt json", encoding="utf-8")
    corrupt_capsule = engine._plan_state_capsule(fresh_cdir)
    assert "UNKNOWN" in corrupt_capsule
    assert steward_plan.MSG_STORE_UNREADABLE in corrupt_capsule


def test_full_cockpit_plan_ui_contract_and_dual_auto_completion_into_cave_list(isolated_w3, monkeypatch):
    # 1. Static HTML / JS / CSS contract checks for full-cockpit THE PLAN rail
    v1_html = (REPO_ROOT / "steward_cockpit" / "static" / "v1.html").read_text(encoding="utf-8")
    shared_js = (REPO_ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    shared_css = (REPO_ROOT / "steward_cockpit" / "static" / "shared.css").read_text(encoding="utf-8")

    for attr in (
        "data-plan-head",
        "data-plan-count",
        "data-plan-error",
        "data-plan-focus",
        "data-plan-proposal",
        "data-plan-add",
        "data-plan-add-title",
        "data-plan-add-goal",
        "data-plan-add-submit",
        "data-steps",
    ):
        assert attr in v1_html

    for js_marker in (
        "Complete & Next",
        'op: "complete_and_next"',
        "Steward Proposed Plan Update",
        "Accept Update",
        'op: "accept_proposal"',
        "Dismiss",
        'op: "dismiss_proposal"',
        'op: "add_step"',
        'op: "set_step"',
        'op: "focus"',
        'op: "reorder"',
        'op: "park"',
        "step-deliv-pills",
        "data-step-deliverables",
    ):
        assert js_marker in shared_js

    for css_selector in (
        ".plan-focus-card",
        ".plan-complete-next-btn",
        ".plan-proposal-banner",
        ".plan-prop-accept-btn",
        ".plan-prop-dismiss-btn",
        ".plan-add-bar",
        ".step-interactive-bar",
        ".step-deliv-pills",
    ):
        assert css_selector in shared_css

    # 2. Seed Cave Working List ("The List") linked to our cockpit effort to verify reactive notifications
    cdir = _make_campaign(isolated_w3, "reactive_effort")
    observed_cave_events: list[dict] = []
    orig_reconcile = comms.reconcile_working_list_activity

    def _spy_reconcile(*, cockpit_events=None, **kwargs):
        if cockpit_events:
            observed_cave_events.extend(cockpit_events)
        return orig_reconcile(cockpit_events=cockpit_events, **kwargs)

    monkeypatch.setattr(comms, "reconcile_working_list_activity", _spy_reconcile)

    wl = comms.load_working_list_spine()
    wl["tiles"] = [
        {
            "id": "tile-reactive",
            "title": "Reactive Effort Initiative",
            "priority": 1,
            "prio": "1",
            "category": "Business",
            "cockpitName": "reactive_effort",
            "cockpit_dir": str(cdir),
            "steps": [
                {"id": "wl-s1", "text": "Step 1: Spec Deliverable", "done": False, "cockpit_step_id": "step-1"},
                {"id": "wl-s2", "text": "Wave 2: Engine Build", "done": False, "cockpit_step_id": "step-2"},
            ],
        }
    ]
    comms.save_working_list_spine(wl)

    # Initialize 3-step plan via HTTP route api_post / handle_post
    init_body, init_code = routes.api_post(
        str(cdir),
        "plan",
        {
            "op": "init",
            "replace": True,
            "steps": [
                {"id": "step-1", "title": "Spec Deliverable", "goal": "Approve spec PDF", "status": "active"},
                {"id": "step-2", "title": "Wave 2 — Engine Build", "goal": "Pass Wave 2 gate", "status": "planned"},
                {"id": "step-3", "title": "Final Polish", "goal": "Ship v1", "status": "planned"},
            ],
        },
    )
    assert init_code == 200
    assert init_body["focus"]["step_id"] == "step-1"

    # Register a For-Review deliverable linked to step-1
    spec_pdf = cdir / "deliverables" / "Spec_v1.pdf"
    spec_pdf.parent.mkdir(parents=True, exist_ok=True)
    spec_pdf.write_bytes(b"%PDF-1.4 spec v1\n")
    reg_body, reg_code = routes.handle_post(
        str(cdir),
        "plan",
        {
            "op": "register_deliverable",
            "path": "deliverables/Spec_v1.pdf",
            "title": "Architecture Spec v1",
            "step_id": "step-1",
            "status": "for_review",
        },
    )
    assert reg_code == 200
    assert any(ev.get("kind") == "deliverable_for_review" for ev in observed_cave_events)

    # 3. Auto-Completion Path A: Approving Deliverable (For Review -> Final) auto-checks step-1,
    # advances focus in strip.json to step-2, promotes bucket to Final, and notifies Cave's The List!
    observed_cave_events.clear()
    app_res, app_code = routes.handle_post(
        str(cdir),
        "approve-deliverable",
        {"path": "deliverables/Spec_v1.pdf", "what": "FOR REVIEW — Architecture Spec v1", "step_id": "step-1"},
    )
    assert app_code == 200
    assert app_res["ok"] is True
    assert app_res["disposition"] == "approved"

    plan_after_deliv = steward_plan.read_plan_state(cdir)
    st1 = next(s for s in plan_after_deliv["steps"] if s["id"] == "step-1")
    assert st1["done"] is True
    assert st1["status"] == "done"
    assert plan_after_deliv["focus"]["step_id"] == "step-2"
    strip_after_deliv = json.loads((cdir / "strip.json").read_text(encoding="utf-8"))
    assert strip_after_deliv["current_step_id"] == "step-2"

    deliv_after = campaign.read_deliverables(str(cdir))
    assert any(it["path"] == "deliverables/Spec_v1.pdf" for it in deliv_after["buckets"]["final"])
    assert not any(it["path"] == "deliverables/Spec_v1.pdf" for it in deliv_after["buckets"]["for_review"])
    assert any(ev.get("kind") in ("step_completed", "deliverable_final") for ev in observed_cave_events)

    # Also exercise campaign.approve_deliverable helper directly (idempotent)
    direct_app = campaign.approve_deliverable(str(cdir), path="deliverables/Spec_v1.pdf", step_id="step-1")
    assert direct_app["ok"] is True

    # 4. Auto-Completion Path B: code_jobs Wave GO completion auto-checks step-2, advances focus to step-3,
    # and notifies Cave's reactive watcher!
    observed_cave_events.clear()
    wave_res = code_jobs.reconcile_wave_completion(
        str(cdir),
        {"id": "job-wave2", "goal": "Wave 2 — Engine Build"},
        wave_n=2,
    )
    assert wave_res["ok"] is True
    assert "step-2" in wave_res["completed_step_ids"]
    plan_after_wave = steward_plan.read_plan_state(cdir)
    st2 = next(s for s in plan_after_wave["steps"] if s["id"] == "step-2")
    assert st2["done"] is True
    assert plan_after_wave["focus"]["step_id"] == "step-3"
    assert any(ev.get("kind") == "step_completed" for ev in observed_cave_events)

    # Verify _reconcile_foreman_waves with a Foreman .foreman/run-record.json GO verdict on Wave 3
    routes.handle_post(
        str(cdir),
        "plan",
        {"op": "set_step", "id": "step-3", "title": "Wave 3 — Final Polish"},
    )
    wt_dir = isolated_w3 / "foreman_wt"
    (wt_dir / ".foreman").mkdir(parents=True, exist_ok=True)
    (wt_dir / ".foreman" / "run-record.json").write_text(
        json.dumps({"waves": [{"wave": 3, "status": "done", "verdict": "GO"}]}),
        encoding="utf-8",
    )
    code_jobs._reconcile_foreman_waves(str(cdir), {"id": "job-wave3"}, str(wt_dir), set())
    plan_after_w3 = steward_plan.read_plan_state(cdir)
    st3 = next(s for s in plan_after_w3["steps"] if s["id"] == "step-3")
    assert st3["done"] is True

    # 5. Auto-Completion Path C: Conversational reconcile_review_on_feedback()
    fb_dir = _make_campaign(isolated_w3, "feedback_effort")
    steward_plan.mutate_plan_state(
        fb_dir,
        "init",
        {
            "replace": True,
            "steps": [
                {"id": "fb-1", "title": "Draft Chapter 1", "goal": "John approves Ch 1", "status": "waiting", "waiting_on": "Review Ch 1"},
                {"id": "fb-2", "title": "Draft Chapter 2", "goal": "Outline Ch 2", "status": "planned"},
            ],
        },
    )
    ch1_file = fb_dir / "chapters" / "Chapter_01.docx"
    ch1_file.parent.mkdir(parents=True, exist_ok=True)
    ch1_file.write_bytes(b"PK\x03\x04fake docx")
    steward_plan.mutate_plan_state(
        fb_dir,
        "register_deliverable",
        {
            "path": "chapters/Chapter_01.docx",
            "title": "Chapter 1 Manuscript",
            "step_id": "fb-1",
            "status": "for_review",
        },
    )

    # Revision request does NOT auto-complete the step
    rev_fb = campaign.reconcile_review_on_feedback(str(fb_dir), "Please revise the opening scene and tighten pacing.")
    assert rev_fb["reconciled"] >= 1
    assert rev_fb["kind"] == "revision_requested"
    assert steward_plan.read_plan_state(fb_dir)["steps"][0]["done"] is False

    # Re-stage a fresh For-Review revision and send explicit approval in dialogue
    ch1_v2 = fb_dir / "chapters" / "Chapter_01_v2.docx"
    ch1_v2.write_bytes(b"PK\x03\x04fake docx v2")
    steward_plan.mutate_plan_state(
        fb_dir,
        "register_deliverable",
        {
            "path": "chapters/Chapter_01_v2.docx",
            "title": "Chapter 1 Manuscript v2",
            "step_id": "fb-1",
            "status": "for_review",
        },
    )
    ok_fb = campaign.reconcile_review_on_feedback(str(fb_dir), "Approved, looks good — ship it!")
    assert ok_fb["reconciled"] >= 1
    assert ok_fb["kind"] == "approved"
    fb_plan = steward_plan.read_plan_state(fb_dir)
    assert fb_plan["steps"][0]["done"] is True
    assert fb_plan["focus"]["step_id"] == "fb-2"
    fb_strip = json.loads((fb_dir / "strip.json").read_text(encoding="utf-8"))
    assert fb_strip["current_step_id"] == "fb-2"
    assert not fb_strip.get("waiting_on")


def test_embedded_cave_initiative_tile_agents_md_contract(isolated_w3):
    proot = _make_campaign(isolated_w3, "proj_root")
    effort_sub = _make_campaign(proot, "effort_sub")

    # 1. Exact full_cockpit_url binding to /steward/v1 with exact pid + dir
    direct_url = routes.full_cockpit_url("pid-alpha", "effort_sub", token="tok-123")
    assert direct_url == "/steward/v1?pid=pid-alpha&dir=effort_sub&token=tok-123"

    map_body, map_code = routes.api_get(str(proot), "map", {"pid": "pid-alpha", "dir": "effort_sub"})
    assert map_code == 200
    assert map_body["full_cockpit_url"] == "/steward/v1?pid=pid-alpha&dir=effort_sub"
    assert "plan_state" in map_body

    # 2. serve_page_doc("v1", embed=True, view="tile") & serve_cockpit_doc inject embedded tile flags
    tile_html = routes.serve_page_doc("v1", pid="pid-alpha", effort_dir="effort_sub", embed=True, view="tile")
    assert tile_html is not None
    assert "window.STEWARD_EMBED=true;" in tile_html
    assert 'window.STEWARD_EFFORT_DIR="effort_sub";' in tile_html
    assert 'window.STEWARD_PID = "pid-alpha";' in tile_html
    assert (
        "window.STEWARD_FULL_COCKPIT_URL='/steward/v1?pid='+encodeURIComponent(_PAGE_PID)+'&dir='+encodeURIComponent(_PAGE_DIR)"
        in tile_html
    )

    cockpit_embed_html = routes.serve_cockpit_doc(pid="pid-alpha", effort_dir="effort_sub", embed=True, view="tile")
    assert cockpit_embed_html is not None
    assert "window.STEWARD_EMBED=true;" in cockpit_embed_html

    full_html = routes.serve_page_doc("v1", pid="pid-alpha", effort_dir="effort_sub", embed=False, view="")
    assert "window.STEWARD_EMBED=false;" in full_html

    # 3. Verify v1.html, shared.js, and shared.css strictly suppress Plan/Status/Goal/Header chrome
    # in embedded Cave tiles even on wide screens (>=1200px), resize, or saved localStorage statusopen!
    v1_src = (REPO_ROOT / "steward_cockpit" / "static" / "v1.html").read_text(encoding="utf-8")
    js_src = (REPO_ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    css_src = (REPO_ROOT / "steward_cockpit" / "static" / "shared.css").read_text(encoding="utf-8")

    assert "const isEmbeddedTile = window.STEWARD_EMBED === true ||" in v1_src
    assert 'document.documentElement.classList.add("is-embed-tile")' in v1_src
    assert 'app.classList.add("embed-tile", "railhide")' in v1_src
    assert 'app.classList.remove("statusopen")' in v1_src
    assert 'if (isEmbeddedTile || app.classList.contains("tileview") || app.classList.contains("talkview"))' in v1_src
    assert "if(isEmbeddedTile||app.classList.contains('tileview')||app.classList.contains('talkview'))" in v1_src
    assert "window.addEventListener('resize',fitConversation);" in v1_src

    # shared.js skips loadPlan() / wirePlanAddBar() when TILE is true, preserves composer + resize + deliverables
    assert 'const EMBED = PARAMS.get("embed") === "1" || window.STEWARD_EMBED === true;' in js_src
    assert 'const TILE = EMBED || VIEW_MODE === "tile" || TALK;' in js_src
    assert "const wantPanes = !TALK && !TILE;" in js_src
    assert "if (TILE || TALK) return null;" in js_src
    assert 'a.classList.add("embed-tile", "railhide")' in js_src
    assert 'a.classList.remove("statusopen")' in js_src

    # shared.css hides .leftcol, [data-plan-*], .rightcol, .goalbar, .bar even inside @media (min-width: 1200px)
    assert "html.is-embed-tile .app .leftcol" in css_src
    assert ".app.tileview [data-plan-focus]" in css_src
    assert ".app.tileview .rightcol" in css_src
    assert ".app.tileview .goalbar" in css_src
    assert ".app.tileview .bar" in css_src
    assert "@media (min-width: 1200px)" in css_src

    # Deliverables remain openable for the embedded effort via handle_get("deliverable-file")
    note_md = effort_sub / "deliverables" / "Brief_Note.md"
    note_md.parent.mkdir(parents=True, exist_ok=True)
    note_md.write_text("# Embedded Deliverable\n\nReadable from Cave tile.\n", encoding="utf-8")
    steward_plan.mutate_plan_state(
        effort_sub,
        "register_deliverable",
        {"path": "deliverables/Brief_Note.md", "title": "Brief Note", "status": "for_review"},
    )
    rendered, status = routes.handle_get(
        str(effort_sub),
        "deliverable-file",
        {"pid": "pid-alpha", "dir": "effort_sub", "path": "deliverables/Brief_Note.md", "render": "1"},
    )
    assert status == 200
    assert "Embedded Deliverable" in rendered["__html__"]


def test_ba815_purge_canonical_buckets_readable_managed_links_md_js_and_distro_clean(isolated_w3):
    # 1. Zero occurrences of BA 815 / Einstein course hacks or withinRecentBatch 2-day eviction
    for rel_path in (
        "steward_cockpit/steward_campaign.py",
        "steward_cockpit/steward_routes.py",
        "steward_cockpit/static/shared.js",
        "steward_cockpit/static/md.js",
    ):
        src = (REPO_ROOT / rel_path).read_text(encoding="utf-8")
        assert "BA 815" not in src, f"Found BA 815 in {rel_path}"
        assert "hasCourseLecture9Final" not in src, f"Found hasCourseLecture9Final in {rel_path}"
        assert "withinRecentBatch" not in src, f"Found withinRecentBatch in {rel_path}"

    # 2. md.js LINKABLE includes /steward/report
    md_js = (REPO_ROOT / "steward_cockpit" / "static" / "md.js").read_text(encoding="utf-8")
    assert "/steward/report" in md_js

    # 3. Clean human titles, sanitized filenames, and canonical 4-bucket classification with ZERO 2-day eviction
    fake_hash = hashlib.sha256(b"managed-artifact-payload").hexdigest()
    cleaned_title = core.clean_human_deliverable_title(
        f"FOR REVIEW — Quantitative_Factor_Report rev_99881122 ({fake_hash}).pdf",
        fallback_path=f".ecgberht/revisions/{fake_hash}.pdf",
    )
    assert "FOR REVIEW" not in cleaned_title
    assert fake_hash not in cleaned_title
    assert "rev_99881122" not in cleaned_title
    assert "Quantitative Factor Report" in cleaned_title

    # Keyword fallback compatibility (used by code_jobs.py)
    kw_title = core.clean_human_deliverable_title("", path="deliverables/market_study.pdf", fallback="market_study")
    assert kw_title == "market study"

    sanitized_fn = core.sanitize_download_filename(
        f'START HERE — Board Deck\r\n"Injected"/{fake_hash}.pptx',
        fallback_ext=".pptx",
    )
    assert "\r" not in sanitized_fn and "\n" not in sanitized_fn and '"' not in sanitized_fn
    assert "/" not in sanitized_fn and "\\" not in sanitized_fn
    assert fake_hash not in sanitized_fn
    assert sanitized_fn == "Board Deck Injected.pptx"
    assert core.suggested_deliverable_filename("FINAL — Capital Model", "models/cap.xlsx") == "Capital Model.xlsx"

    # Zero 2-day eviction: 60-day-old For Review & Final deliverables stay in their buckets!
    cdir = _make_campaign(isolated_w3, "aged_deliverables_effort")
    (cdir / "deliverables").mkdir(parents=True, exist_ok=True)
    (cdir / "deliverables" / "Old_Review_Paper.pdf").write_bytes(b"%PDF-1.4 review\n")
    (cdir / "deliverables" / "Old_Review_Memo.docx").write_bytes(b"PK\x03\x04memo")
    (cdir / "deliverables" / "Old_Final_Paper.pdf").write_bytes(b"%PDF-1.4 final\n")
    (cdir / "deliverables" / "Audit_Notes.md").write_text("# Supporting audit\n", encoding="utf-8")
    (cdir / "DELIVERABLES.md").write_text(
        "# Deliverables\n\n"
        "| What | Where | Date | Step |\n"
        "|---|---|---|---|\n"
        "| FOR REVIEW — Longitudinal Econometric Paper | `deliverables/Old_Review_Paper.pdf` | 2026-08-01 | s1 |\n"
        "| FOR REVIEW — Longitudinal Econometric Memo | `deliverables/Old_Review_Memo.docx` | 2026-08-02 | s1 |\n"
        "| FINAL — Baseline Literature Synthesis | `deliverables/Old_Final_Paper.pdf` | 2026-07-15 | s0 |\n"
        "| Supporting — Internal Diagnostic Audit | `deliverables/Audit_Notes.md` | 2026-11-12 | s1 |\n",
        encoding="utf-8",
    )

    deliv_res, deliv_code = routes.handle_get(
        str(cdir),
        "deliverables",
        {"pid": "proj-1", "dir": "aged_deliverables_effort"},
    )
    assert deliv_code == 200
    assert deliv_res["ok"] is True
    buckets = deliv_res["buckets"]
    assert set(buckets.keys()) == {"for_review", "final", "in_progress", "archive"}
    assert any(i["human_title"] == "Longitudinal Econometric Paper" for i in buckets["for_review"])
    assert any(i["human_title"] == "Longitudinal Econometric Memo" for i in buckets["for_review"])
    assert any(i["human_title"] == "Baseline Literature Synthesis" for i in buckets["final"])
    assert any("Internal Diagnostic Audit" in i["human_title"] for i in buckets["archive"])
    kd_titles = {k["human_title"] for k in deliv_res["key_deliverables"]}
    assert "Longitudinal Econometric Paper" in kd_titles
    assert "Longitudinal Econometric Memo" in kd_titles
    assert "Baseline Literature Synthesis" in kd_titles

    rev_item = next(i for i in buckets["for_review"] if i["human_title"] == "Longitudinal Econometric Paper")
    assert rev_item["reading"]["read"] is not None
    rev_docx = next(i for i in buckets["for_review"] if i["human_title"] == "Longitudinal Econometric Memo")
    assert "filename=Longitudinal%20Econometric%20Memo.docx" in rev_docx["download_url"]

    # Direct Wave 3 delta-coverage checks across core, deliverables_register, campaign, routes, and steward_plan
    cls_direct = core.classify_deliverable_buckets(deliv_res["items"], deliv_res.get("approved") or [])
    assert len(cls_direct["buckets"]["for_review"]) >= 2
    assert deliverables_register._suggested_download_filename(rev_docx, "deliverables/Old_Review_Memo.docx") == "Longitudinal Econometric Memo.docx"
    rt_direct = deliverables_register.reading_target(
        rev_docx,
        pid="proj-1",
        effort_rel="aged_deliverables_effort",
        effort_dir=str(cdir),
    )
    assert "filename=Longitudinal%20Econometric%20Memo.docx" in (rt_direct["download"] or "")
    assert campaign._human_filename_for_item(
        f".ecgberht/revisions/{fake_hash}.pdf",
        "FOR REVIEW — Quantitative Factor Report",
        "",
    ) == "Quantitative Factor Report.pdf"
    assert campaign._deliverables_backing_store_error(str(cdir)) == ""
    assert routes._resolve_plan_cdir(str(isolated_w3), "aged_deliverables_effort") == str(cdir)
    assert routes._resolve_plan_cdir(str(isolated_w3), "../escape") is None
    assert (
        routes._resolve_clean_download_filename(
            str(cdir),
            "deliverables/Old_Review_Memo.docx",
            str(cdir / "deliverables" / "Old_Review_Memo.docx"),
            ".docx",
            {},
        )
        == "Longitudinal Econometric Memo.docx"
    )
    dis_res = campaign.dismiss_deliverable(
        str(cdir),
        path="deliverables/Audit_Notes.md",
        disposition="dismissed",
        auto_complete=False,
        notify_cave=False,
    )
    assert dis_res["ok"] is True
    auto_noop = steward_plan.auto_complete_linked_step(cdir, step_id="nonexistent-step", notify_cave=False)
    assert auto_noop["ok"] is True
    assert auto_noop["completed_step_ids"] == []

    # 4. AGENTS.md Readable Managed Review Links:
    # `contained readable copy` review: `immutable revision path` served ONLY through original hash check!
    managed_bytes = b"%PDF-1.4 immutable managed revision payload\n"
    managed_sha = hashlib.sha256(managed_bytes).hexdigest()
    imm_rel = f".ecgberht/revisions/{managed_sha}.pdf"
    imm_file = cdir / ".ecgberht" / "revisions" / f"{managed_sha}.pdf"
    imm_file.parent.mkdir(parents=True, exist_ok=True)
    imm_file.write_bytes(managed_bytes)

    readable_rel = "deliverables/Readable_Board_Packet_v2.pdf"
    readable_file = cdir / readable_rel
    readable_file.write_bytes(managed_bytes)

    deliverables_register.register(
        cdir,
        "FOR REVIEW — Board Packet Round 1",
        f"`{readable_rel}` review: `{imm_rel}`",
        step="s2",
        notify=False,
    )
    parsed_reg = campaign._read_deliverables(str(cdir))
    assert any(
        it.get("path") == imm_rel or it.get("readable_path") == readable_rel or it.get("path") == readable_rel
        for it in (parsed_reg.get("items") or [])
    )
    routes._DELIV_CACHE.clear()
    campaign._JSON_FILE_CACHE.clear()

    # Valid hash serves readable file with clean sanitized Content-Disposition (never 64-hex hash!)
    dl_resp, dl_status = routes.handle_get(
        str(cdir),
        "deliverable-file",
        {
            "pid": "proj-1",
            "dir": "aged_deliverables_effort",
            "path": readable_rel,
            "hash": managed_sha,
            "download": "1",
            "filename": 'Board Packet Round 1\r\n"evil".pdf',
        },
    )
    assert dl_status == 200
    assert dl_resp["__disposition__"] == "attachment"
    assert dl_resp["__filename__"] == "Board Packet Round 1 evil.pdf"
    assert dl_resp["__content_disposition__"] == 'attachment; filename="Board Packet Round 1 evil.pdf"'
    assert managed_sha not in dl_resp["__filename__"]

    # Tampered hash is rejected with HTTP 409 artifact-hash-mismatch
    wrong_sha = hashlib.sha256(b"different-bytes").hexdigest()
    bad_resp, bad_status = routes.handle_get(
        str(cdir),
        "deliverable-file",
        {
            "pid": "proj-1",
            "dir": "aged_deliverables_effort",
            "path": readable_rel,
            "hash": wrong_sha,
            "download": "1",
        },
    )
    assert bad_status == 409
    assert bad_resp["error"] == "artifact-hash-mismatch"

    # 5. tools/steward_plan.py stdlib-only check (IMPLEMENTATION-PLAN.md:137)
    w3_plan_cli = [("tools/steward_plan.py", REPO_ROOT / "tools/steward_plan.py")]
    assert distro.scan_third_party_imports(w3_plan_cli, root=REPO_ROOT) == []


def test_wave3_five_failure_states_unknown_not_equal_empty(isolated_w3, monkeypatch):
    # 1. dependency-missing -> HTTP 404 "Campaign directory not found"
    missing = isolated_w3 / "nonexistent_campaign"
    body_404_get, code_404_get = routes.api_get(str(missing), "plan", {})
    assert code_404_get == 404
    assert body_404_get["ok"] is False
    assert body_404_get["failure_state"] == "dependency-missing"
    assert body_404_get["message"] == "Campaign directory not found"

    body_404_post, code_404_post = routes.api_post(str(missing), "plan", {"op": "add_step", "title": "X"})
    assert code_404_post == 404
    assert body_404_post["failure_state"] == "dependency-missing"
    assert body_404_post["message"] == "Campaign directory not found"

    # 2. empty-but-valid -> HTTP 200 "No plan steps yet — add a step or ask Steward to draft The Plan"
    empty_cdir = _make_campaign(isolated_w3, "empty_valid_campaign")
    body_200, code_200 = routes.api_get(str(empty_cdir), "plan", {})
    assert code_200 == 200
    assert body_200["ok"] is True
    assert body_200["failure_state"] == "empty-but-valid"
    assert body_200["steps"] == []
    assert body_200["message"] == "No plan steps yet — add a step or ask Steward to draft The Plan"

    # 3. dependency-returns-garbage -> HTTP 400 "Invalid plan mutation or step cap (>200) exceeded"
    body_400_op, code_400_op = routes.handle_post(str(empty_cdir), "plan", {"op": "not_a_real_op"})
    assert code_400_op == 400
    assert body_400_op["ok"] is False
    assert body_400_op["failure_state"] == "dependency-returns-garbage"
    assert body_400_op["message"] == "Invalid plan mutation or step cap (>200) exceeded"

    body_400_nondict, code_400_nondict = routes.handle_post(str(empty_cdir), "plan", "garbage-payload")
    assert code_400_nondict == 400
    assert body_400_nondict["failure_state"] == "dependency-returns-garbage"
    assert body_400_nondict["message"] == "Invalid plan mutation or step cap (>200) exceeded"

    # 4. dependency-slow-or-killed -> HTTP 504 "Plan state lock busy (>2.0s) — retry"
    # Hold the real cross_process_lock in a child Python process and assert HTTP 504 refusal!
    lock_holder_code = textwrap.dedent(
        """
        import sys, time
        import paths
        lock_file = sys.argv[1]
        with paths.cross_process_lock(lock_file, timeout_sec=5.0):
            sys.stdout.write("LOCKED\\n")
            sys.stdout.flush()
            time.sleep(2.5)
        """
    )
    lock_path = empty_cdir / ".ecgberht" / "plan.lock"
    holder = subprocess.Popen(
        [sys.executable, "-c", lock_holder_code, str(lock_path)],
        cwd=str(REPO_ROOT),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready_line = holder.stdout.readline().strip()
        assert ready_line == "LOCKED"
        monkeypatch.setattr(steward_plan, "PLAN_LOCK_TIMEOUT_SEC", 0.2)
        body_504, code_504 = routes.handle_post(
            str(empty_cdir),
            "plan",
            {"op": "add_step", "title": "Blocked by busy lock"},
        )
        assert code_504 == 504
        assert body_504["ok"] is False
        assert body_504["failure_state"] == "dependency-slow-or-killed"
        assert body_504["message"] == "Plan state lock busy (>2.0s) — retry"
    finally:
        holder.terminate()
        holder.communicate(timeout=10)

    # 5. backing-store-unreadable -> HTTP 500 "Plan/Deliverables unreadable (unknown) — inspect roadmap.json"
    corrupt_cdir = _make_campaign(isolated_w3, "corrupt_store_campaign")
    (corrupt_cdir / "roadmap.json").write_text("{corrupt_json: [1, 2", encoding="utf-8")
    campaign._JSON_FILE_CACHE.clear()
    routes._DELIV_CACHE.clear()

    plan_500, plan_code_500 = routes.handle_get(str(corrupt_cdir), "plan", {})
    assert plan_code_500 == 500
    assert plan_500["ok"] is False
    assert plan_500["failure_state"] == "backing-store-unreadable"
    assert plan_500["message"] == "Plan/Deliverables unreadable (unknown) — inspect roadmap.json"

    deliv_500, deliv_code_500 = routes.handle_get(str(corrupt_cdir), "deliverables", {})
    assert deliv_code_500 == 500
    assert deliv_500["ok"] is False
    assert deliv_500["failure_state"] == "backing-store-unreadable"
    assert deliv_500["message"] == "Plan/Deliverables unreadable (unknown) — inspect roadmap.json"


def test_key_deliverables_subdir_version_agnostic_fallback_and_inline_accept_controls(isolated_w3):
    cdir = _make_campaign(isolated_w3, "version_fallback_effort")
    kd_dir = cdir / "Key Deliverables"
    kd_dir.mkdir(parents=True, exist_ok=True)
    v5_bytes = b"%PDF-1.4 superseded v5 deck payload\n"
    (kd_dir / "Strategy_Deck (v5).pdf").write_bytes(v5_bytes)
    (cdir / "DELIVERABLES.md").write_text(
        "# Deliverables\n\n"
        "| What | Where | Date | Step |\n"
        "|---|---|---|---|\n"
        "| FINAL — Strategy Deck | `Key Deliverables/Strategy_Deck (v5).pdf` | 2026-11-16 | s1 |\n",
        encoding="utf-8",
    )
    routes._DELIV_CACHE.clear()
    campaign._JSON_FILE_CACHE.clear()

    # Requesting an older `(v4).pdf` link resolves cleanly to the registered `(v5).pdf` inside `Key Deliverables/`
    resp, status = routes.handle_get(
        str(cdir),
        "deliverable-file",
        {
            "pid": "proj-1",
            "dir": "version_fallback_effort",
            "path": "Strategy_Deck (v4).pdf",
        },
    )
    assert status == 200
    assert Path(resp["__file__"]).name == "Strategy_Deck (v5).pdf"

    # Inline For Review `✓ Accept` button and `✓ Review Done` top-bar button exist in shared.js
    shared_js = (REPO_ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    assert "deliv-unit-accept-btn" in shared_js
    assert 'post("/api/approve-deliverable"' in shared_js
    assert "review-done-btn" in shared_js

