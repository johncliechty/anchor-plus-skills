"""Current code-job ETA through production composition and the shared renderer."""
import json
import os
from pathlib import Path
import time
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright

from steward_cockpit import steward_campaign as campaign
from tests.test_provider_setup import AUTH, stack
from tests.test_provider_setup_browser import cave_server

REPO = Path(__file__).resolve().parents[1]


def write_json(path, value, at):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")
    os.utime(path, (at, at))


@pytest.fixture
def effort(tmp_path, monkeypatch):
    now = time.time()
    monkeypatch.setattr(campaign.time, "time", lambda: now)
    root = tmp_path / "effort"
    root.mkdir()
    (root / "ECGBERHT.md").write_text("# Provider setup\n\n## North Star\nIsolated named accounts.\n", encoding="utf-8")
    write_json(root / "roadmap.json", {
        "roadmap_projection": [{"id": "account", "name": "Provider setup", "status": "active",
                                "part": "slice", "done_when": "Accounts stay isolated."}]
        + [{"id": str(i), "name": "Later", "status": "proposed", "part": "slice"} for i in range(90)]
    }, now)
    write_json(root / "strip.json", {"current_step_id": "account"}, now)
    worktree = tmp_path / "job-1"
    plan = worktree / ".foreman-job" / "IMPLEMENTATION-PLAN.md"
    plan.parent.mkdir(parents=True)
    plan.write_text("# Code job job-1 - Implementation Plan\n", encoding="utf-8")
    os.utime(plan, (now - 600, now - 600))
    record = {"id": "job-1", "status": "running", "steward_dir": str(root),
              "worktree": str(worktree), "started": now - 600,
              "brief": "# Work order: Recover provider accounts"}
    write_json(root / ".ecgberht" / "code-jobs.json", {"job-1": record}, now)
    write_json(worktree / "foreman-checkpoint.json",
               {"plan_path": str(plan), "status": "running", "intra_wave_step": "execute",
                "current_wave": 1, "total_waves": 1, "last_verdict": None}, now - 60)
    write_json(worktree / ".foreman" / "heartbeat.json",
               {"alive": True, "startedAt": now - 600, "ts": now - 5}, now - 5)
    return root, worktree, record, now


def save_record(effort):
    root, _, record, now = effort
    write_json(root / ".ecgberht" / "code-jobs.json", {record["id"]: record}, now)


def compose(effort):
    return campaign.compose_status(str(effort[0]), {"busy": False})


def eta_fact(status):
    return next(row["value"] for row in status["compact"]["facts"] if row["label"] == "ETA")


def test_current_job_before_any_pass_has_scoped_provisional_range(effort):
    status = compose(effort)
    evidence = status["evidence"]["eta"]
    assert status["running"]["kind"] == "code_job"
    assert status["eta"].startswith("Provisional job job-1 finish ")
    assert "execute, 10m elapsed" in status["eta"] and "as of" in status["eta"]
    assert "checks/review/fixes assumed" in status["eta"]
    assert status["eta"] == eta_fact(status) == evidence["value"]
    assert evidence["job_id"] == "job-1" and evidence["source"] == "code_job"
    assert evidence["phase"] == "execute" and evidence["elapsed_minutes"] == 10
    assert evidence["earliest_at"] < evidence["latest_at"]
    assert not evidence["native"] and "no measured pass pace" in evidence["basis"]
    assert status["evidence"]["checks"] == [] and "Unavailable" in status["tests"]
    assert status["project"]["steps_total"] == 91
    assert evidence["latest_at"] <= effort[3] + 60 * 60
    assert {f["label"] for f in status["compact"]["facts"]} == {
        "Summary", "Effort", "Doing", "Status", "Tests", "Blocker", "Procs", "Journal", "ETA", "To do"}


def test_native_estimate_is_preferred_and_phase_change_rebases_it(effort):
    root, worktree, record, now = effort
    record["eta"] = {"earliest_at": now + 300, "latest_at": now + 900,
                     "estimated_at": now - 10, "basis": "Measured native build pace",
                     "phase": "execute", "job_id": "job-1"}
    save_record(effort)
    first = compose(effort)["evidence"]["eta"]
    assert first["native"] and first["latest_at"] == now + 900
    checkpoint = worktree / "foreman-checkpoint.json"
    value = json.loads(checkpoint.read_text())
    value["intra_wave_step"] = "review"
    write_json(checkpoint, value, now)
    second = compose(effort)
    assert not second["evidence"]["eta"]["native"]
    assert second["evidence"]["eta"]["phase"] == "review"
    assert "phase changed" in second["eta"] and "rebased" in second["eta"]
    assert eta_fact(second) == second["eta"]


@pytest.mark.parametrize("change, reason", [
    ({"at": "broken"}, "invalid"),
    ({"at": True}, "invalid"),
    ({"at": float("nan")}, "invalid"),
    ({"estimated_at": float("inf")}, "invalid"),
    ({"estimated_at": None}, "invalid"),
    ({"earliest_at": 1, "latest_at": 0}, "invalid"),
    ({"basis": ""}, "invalid"),
    ({"estimated_at": "stale"}, "stale"),
    ({"at": "expired"}, "exceeded"),
    ({"job_id": "another-job"}, "ownership"),
])
def test_bad_stale_expired_or_foreign_estimates_are_qualified(effort, change, reason):
    _, _, record, now = effort
    record["eta"] = {"at": now + 600, "estimated_at": now - 10,
                     "basis": "Native estimate", "phase": "execute", "job_id": "job-1"}
    if change.get("estimated_at") == "stale":
        change = {"estimated_at": now - 1200}
        record["started"] = now - 3600
    if change.get("at") == "expired":
        change = {"at": now - 60, "estimated_at": now - 120}
    record["eta"].update(change)
    save_record(effort)
    status = compose(effort)
    evidence = status["evidence"]["eta"]
    assert not evidence["native"] and reason in evidence["qualification"]
    assert "rebased" in status["eta"]
    assert now < evidence["earliest_at"] < evidence["latest_at"]
    assert status["eta"] == eta_fact(status) == evidence["value"]


def test_native_pace_log_and_waiting_phase_use_only_the_bound_worktree(effort):
    _, worktree, _, now = effort
    log = worktree / "_foreman-status.log"
    clock = time.strftime("%H:%M", time.localtime(now - 10))
    log.write_text(f"[{clock}] Foreman build \u00b7 job-1 \u00b7 t+10m\n"
                   "---------------------------------\nEffort   Provider build (1 wave)\nDoing    wave 1 gate\n"
                   "Status   0/1 waves\nETA      ~12m to run end (pace estimate)\nTo do    review\n", encoding="utf-8")
    os.utime(log, (now - 10, now - 10))
    write_json(worktree / ".foreman" / "waiting-on.json",
               {"label": "gate", "ts": now - 1}, now - 1)
    status = compose(effort)
    assert status["evidence"]["eta"]["native"]
    assert status["evidence"]["eta"]["phase"] == "gate"
    table_at = campaign._job_epoch(time.strftime("%Y-%m-%d", time.localtime(now - 10)) + "T" + clock + ":00")
    assert status["evidence"]["eta"]["latest_at"] == table_at + 17 * 60
    assert "+/-5m presentation range assumed" in status["evidence"]["eta"]["basis"]
    assert "Unavailable" in status["tests"], "A native ETA must not manufacture a test receipt"


def test_stale_phase_and_exceeded_phase_window_rebase_honestly(effort):
    _, worktree, record, now = effort
    record["started"] = now - 7200
    save_record(effort)
    checkpoint = json.loads((worktree / "foreman-checkpoint.json").read_text())
    write_json(worktree / "foreman-checkpoint.json", checkpoint, now - 4000)
    write_json(worktree / ".foreman" / "heartbeat.json", {"alive": True, "ts": now - 3600}, now - 3600)
    status = compose(effort)
    assert "phase window exceeded" in status["eta"] and "rebased" in status["eta"]
    assert status["evidence"]["eta"]["observed_at"] == now - 3600
    write_json(worktree / "foreman-checkpoint.json", checkpoint, now - 1100)
    status = compose(effort)
    assert "phase evidence stale" in status["eta"]
    assert status["evidence"]["eta"]["earliest_at"] > now


@pytest.mark.parametrize("state", ["done", "failed", "paused", "cancelled", "absent"])
def test_finished_failed_paused_and_absent_jobs_have_no_running_forecast(effort, state):
    root, _, record, now = effort
    record["status"] = state
    save_record(effort)
    if state == "absent":
        (root / ".ecgberht" / "code-jobs.json").unlink()
    status = compose(effort)
    assert not status["eta"].startswith("Provisional job ")
    assert status["evidence"]["eta"]["state"] == "unavailable"
    assert eta_fact(status) == status["eta"]


@pytest.mark.parametrize("state", ["done", "failed", "paused"])
def test_native_stopped_checkpoint_removes_forecast_even_if_owner_record_lags(effort, state):
    _, worktree, _, now = effort
    path = worktree / "foreman-checkpoint.json"
    checkpoint = json.loads(path.read_text())
    checkpoint["status"] = state
    write_json(path, checkpoint, now)
    status = compose(effort)
    assert "Provisional" not in status["eta"]
    assert status["evidence"]["eta"]["state"] == "unavailable"


def test_other_owner_other_worktree_and_unrelated_skill_cannot_supply_eta(effort, monkeypatch):
    root, _, record, now = effort
    record["steward_dir"] = str(root.parent / "another-effort")
    save_record(effort)
    assert campaign.running_code_jobs(str(root)) == []
    record["steward_dir"] = str(root)
    record["worktree"] = str(root.parent / "other-job")
    save_record(effort)
    monkeypatch.setattr(campaign, "status_lookthrough", lambda _: {
        "final": False, "eta": "another effort ETA", "label": "unrelated",
        "skill": "Foreman", "source": "wrong.log", "age": "0m"})
    status = compose(effort)
    assert "another effort" not in status["eta"]
    assert status["evidence"]["eta"]["phase"] == "build"
    assert not status["evidence"]["eta"]["native"]
    assert "Unavailable" in status["tests"]


@pytest.mark.parametrize("contents", ["invalid", "[]", '{"jobs": 1}', '{"jobs": "invalid"}'])
def test_malformed_owner_records_do_not_crash_or_invent_work(effort, contents):
    root, _, _, _ = effort
    (root / ".ecgberht" / "code-jobs.json").write_text(contents, encoding="utf-8")
    assert campaign.running_code_jobs(str(root)) == []
    assert "Provisional" not in compose(effort)["eta"]


def test_malformed_checkpoint_ignores_its_foreign_phase(effort):
    _, worktree, _, now = effort
    write_json(worktree / "foreman-checkpoint.json",
               {"plan_path": str(worktree.parent / "wrong" / "PLAN.md"), "status": "running",
                "intra_wave_step": "review"}, now)
    status = compose(effort)
    assert status["evidence"]["eta"]["phase"] == "build"
    assert "Unavailable" in status["tests"]


def test_status_eta_renders_repaints_rejects_old_event_and_clears_when_finished(cave_server, effort):
    """Fresh worktree browser proof; no live client or steward wake is touched."""
    origin, _, _ = cave_server
    initial = compose(effort)
    initial["status_id"] = "0001"
    root, worktree, record, now = effort
    checkpoint = json.loads((worktree / "foreman-checkpoint.json").read_text())
    checkpoint["intra_wave_step"] = "review"
    write_json(worktree / "foreman-checkpoint.json", checkpoint, now)
    reviewing = compose(effort)
    reviewing["status_id"] = "0002"
    record["status"] = "done"
    save_record(effort)
    finished = compose(effort)
    finished["status_id"] = "0003"
    pending, guarded, starts, errors = [], [], [], []
    static = REPO / "steward_cockpit" / "static"
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            context = browser.new_context(viewport={"width": 1440, "height": 1050})
            login = context.request.post(origin + "/api/auth/login", data={"token": AUTH})
            assert login.ok and any(cookie.get("httpOnly") for cookie in context.cookies(origin))
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            def guard(route):
                request = route.request
                path = urlsplit(request.url).path
                if request.method == "POST":
                    guarded.append(path)
                    if not path.endswith("status-ack"):
                        starts.append(path)
                    route.abort()
                elif path == "/steward/v1":
                    route.fulfill(path=str(static / "v1.html"))
                elif path.startswith("/static/") and (static / Path(path).name).is_file():
                    route.fulfill(path=str(static / Path(path).name))
                elif path in ("/api/events", "/api/steward/events"):
                    guarded.append(path)  # Both forms stop before GET soft-wake.
                    if pending:
                        route.fulfill(json={"events": pending[:], "state": {"alive": False, "busy": False}})
                        pending.clear()
                    else:
                        route.abort()
                elif path == "/api/status":
                    route.fulfill(json=initial)
                elif path == "/api/map":
                    route.fulfill(json=campaign.read_map(str(root)))
                elif path == "/api/history":
                    route.fulfill(json={"turns": []})
                elif path == "/api/deliverables":
                    route.fulfill(json={"items": [], "roots": []})
                elif path == "/api/state":
                    route.fulfill(json={"alive": False, "busy": False})
                elif path.startswith("/api/"):
                    route.abort()
                else:
                    route.continue_()
            page.route("**/*", guard)
            page.goto(origin + "/steward/v1?dir=eta-fixture")
            eta = page.locator('.blk.status.latest [data-status-fact="eta"]')
            expect(eta).to_have_text(initial["eta"])
            draft = page.locator("[data-say]")
            draft.fill("Keep this unfinished draft")
            draft.evaluate("e=>e._etaIdentity='preserved'")
            pending.append({"t": "status", "seq": 1, "status": reviewing})
            expect(eta).to_have_text(reviewing["eta"], timeout=10000)
            # The next since=2 poll proves that the renderer consumed the
            # replay before we assert it did not repaint an older forecast.
            with page.expect_request(lambda req: "/api/events?since=2" in req.url, timeout=10000):
                pending.append({"t": "status", "seq": 2, "status": initial})
            expect(eta).to_have_text(reviewing["eta"])
            pending.append({"t": "status", "seq": 3, "status": finished})
            expect(eta).to_have_text(finished["eta"], timeout=10000)
            expect(eta).not_to_contain_text("Provisional")
            expect(page.locator("[data-barlead]")).not_to_contain_text("Provisional job")
            expect(draft).to_have_value("Keep this unfinished draft")
            assert draft.evaluate("e=>e._etaIdentity") == "preserved"
            assert len(page.locator(".blk.status.latest tr").all()) == 10
            assert not errors and not starts
            assert "/api/events" in guarded
        finally:
            browser.close()


def native_log(worktree, now, title, clock_at, tick="t+10m", eta="~40m to run end (pace estimate)", phase="gate"):
    path = worktree / "_foreman-status.log"
    clock = time.strftime("%H:%M", time.localtime(clock_at))
    path.write_text(f"[{clock}] Foreman build \u00b7 {title} \u00b7 {tick}\n"
                    "---------------------------------\nEffort   Provider build (1 wave)\n"
                    f"Doing    wave 1 {phase}\nETA      {eta}\nTo do    review\n", encoding="utf-8")
    os.utime(path, (now, now))


def test_waiting_lines_cannot_renew_stale_native_estimate_and_fresh_owner_estimate_wins(effort):
    _, worktree, record, now = effort
    record["started"] = now - 7200
    save_record(effort)
    checkpoint_path = worktree / "foreman-checkpoint.json"
    checkpoint = json.loads(checkpoint_path.read_text())
    checkpoint["intra_wave_step"] = "gate"
    write_json(checkpoint_path, checkpoint, now - 1)
    native_log(worktree, now, "job-1", now - 1800, tick="t+90m")
    old = compose(effort)
    assert not old["evidence"]["eta"]["native"]
    assert "native estimate stale" in old["eta"] and "rebased" in old["eta"]
    record["eta"] = {"earliest_at": now + 300, "latest_at": now + 900, "estimated_at": now - 10,
                     "basis": "Fresh owning job forecast", "phase": "gate", "job_id": "job-1"}
    save_record(effort)
    fresh = compose(effort)["evidence"]["eta"]
    assert fresh["native"] and fresh["latest_at"] == now + 900
    assert fresh["basis"] == "Fresh owning job forecast"


def test_different_job_log_never_supplies_native_forecast(effort):
    _, worktree, _, now = effort
    native_log(worktree, now, "other-job", now - 10, phase="execute")
    status = compose(effort)
    assert not status["evidence"]["eta"]["native"]
    assert "checks/review/fixes assumed" in status["eta"]


@pytest.mark.parametrize("signal", ["final_log", "dead_heartbeat"])
def test_terminal_native_signal_removes_running_forecast(effort, signal):
    _, worktree, _, now = effort
    if signal == "final_log":
        native_log(worktree, now, "job-1", now, tick="final")
    else:
        write_json(worktree / ".foreman" / "heartbeat.json", {"alive": False, "ts": now}, now)
    status = compose(effort)
    assert "Provisional" not in status["eta"]
    assert status["evidence"]["eta"]["state"] == "unavailable"
    assert status["eta"] == eta_fact(status) == status["evidence"]["eta"]["value"]


def test_finishing_phase_and_operational_limit_are_kept_distinct(effort):
    _, _, record, now = effort
    record["status"] = "finishing"
    record["timeout_seconds"] = 45 * 60
    save_record(effort)
    status = compose(effort)
    eta = status["evidence"]["eta"]
    assert eta["phase"] == "finishing" and not eta["native"]
    assert "timeout" not in eta["basis"] and "no measured pass pace" in eta["basis"]
    assert eta["latest_at"] != record["started"] + record["timeout_seconds"]


@pytest.mark.parametrize("at", [True, float("nan"), float("inf"), 1e100, "invalid"])
def test_malformed_local_eta_and_foreign_receipt_do_not_hide_the_job_forecast(effort, at):
    root, _, _, now = effort
    evidence_file = root / "check.log"
    evidence_file.write_text("Disposable unfinished check", encoding="utf-8")
    receipt = {"kind": "local_check", "step_id": "account", "session_id": "current-session",
               "command": "python -m pytest disposable", "started_at": now - 60,
               "evidence": "check.log", "eta": {"at": at, "basis": "Unfinished check"}}
    write_json(root / "strip.json", {"current_step_id": "account", "current_session_id": "current-session",
                                    "receipts": [receipt]}, now)
    status = compose(effort)
    assert status["eta"].startswith("Provisional job job-1")
    assert len(status["evidence"]["checks"]) == 1
    assert status["evidence"]["checks"][0]["state"] == "untested"
    assert "check has not finished" in status["tests"]
    receipt["session_id"] = "another-session"
    write_json(root / "strip.json", {"current_step_id": "account", "current_session_id": "current-session",
                                    "receipts": [receipt]}, now)
    status = compose(effort)
    assert status["evidence"]["checks"] == [] and "Unavailable" in status["tests"]
    assert status["eta"] == eta_fact(status) == status["evidence"]["eta"]["value"]


def test_waiting_heartbeat_does_not_restart_the_phase_allowance(effort):
    _, worktree, record, now = effort
    record["started"] = now - 7200
    save_record(effort)
    write_json(worktree / ".foreman" / "waiting-on.json",
               {"label": "execute", "minutes": 80, "ts": now - 1}, now - 1)
    status = compose(effort)
    source = status["evidence"]["eta"]
    assert source["phase_at"] == now - 1 - 80 * 60
    assert source["observed_at"] == now - 1
    assert "phase window exceeded" in status["eta"] and "rebased" in status["eta"]
    assert source["earliest_at"] > now
