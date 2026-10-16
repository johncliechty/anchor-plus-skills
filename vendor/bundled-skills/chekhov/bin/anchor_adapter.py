"""Chekhov facts -> installed Anchor APIs; no copied readers or register writer.

commission_session.finish_run additionally calls a model, auto-continues and
commits campaign state. This bounded CLI uses that module's actual persistence
helpers and RUN_RECORD_SCHEMA, then its real readers. It does not impersonate
finish_run's ingest/raise/handback workflow. See the source-cited contract.
"""
import contextlib
from datetime import datetime
import importlib
import inspect
import json
from pathlib import Path
import re
import subprocess
import sys

KINDS = frozenset(("ledger-report", "verdicts", "render", "lock-receipt"))


def modules(anchor_dir):
    directory = Path(anchor_dir).resolve(strict=True)
    sys.path.insert(0, str(directory))
    names = ("commission_session", "deliverables_register",
             "steward_cockpit.steward_campaign", "foundry_skills")
    loaded = [importlib.import_module(name) for name in names]
    for module in loaded:
        Path(module.__file__).resolve().relative_to(directory)
    return loaded


def identity(request):
    for key in ("project_id", "session_id"):
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}", request.get(key, "")):
            raise ValueError("invalid " + key)
    folder = Path(request["folder"])
    if not folder.is_absolute() or not folder.is_dir():
        raise ValueError("existing absolute folder required")
    return folder.resolve(strict=True)


def read_surfaces(folder, commission, campaign):
    return {"runs": commission.list_runs(str(folder)),
            "deliverables": campaign.read_deliverables(str(folder)),
            "map": campaign.read_map(str(folder))}


def publish_session_attention(folder, request, commission):
    record = commission.load_run_record(str(folder), request["session_id"])
    payload = json.dumps({"folder": str(folder), "project_id": request["project_id"], "record": record}, ensure_ascii=False)
    if len(payload.encode("utf-8")) > 1024 * 1024:
        raise ValueError("attention input exceeds one MiB")
    completed = subprocess.run(
        ["node", str(Path(__file__).with_name("attention_adapter.mjs"))],
        input=payload, text=True, encoding="utf-8", capture_output=True,
        timeout=30, check=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    if len(completed.stdout.encode("utf-8")) > 65536:
        raise ValueError("attention response exceeds 64 KiB")
    try:
        result = json.loads(completed.stdout)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid attention response: " + completed.stderr[-2000:]) from exc
    if completed.returncode != 0 or not isinstance(result, dict) or result.get("ok") is not True:
        raise ValueError("attention publication refused: " + json.dumps(result, ensure_ascii=False)[:4000])
    return result


def record_session(request, commission, registrar, campaign):
    folder = identity(request)
    session_id = request["session_id"]
    target = commission._run_record_path(str(folder), session_id)
    if target.exists():
        raise ValueError("session_id already recorded; never overwrite a prior session")
    report = request["report"]
    start = datetime.fromisoformat(report["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(report["end"].replace("Z", "+00:00"))
    if start.tzinfo is None or end.tzinfo is None or end < start:
        raise ValueError("invalid observed session interval")
    if request["outcome"] not in ("asked", "produced", "died"):
        raise ValueError("invalid commission outcome")
    # list_runs deliberately drops arbitrary top-level details. Its report
    # field retains these facts and say is the existing human renderer input.
    record = {"schema": commission.RUN_RECORD_SCHEMA,
              "session_id": session_id, "commission_id": request.get("commission_id"),
              "skill": "chekhov", "step_id": request.get("step_id"), "lane": None,
              "outcome": request["outcome"], "ran": True,
              "elapsed_s": (end - start).total_seconds(), "at": report["end"],
              "watch_count": 1, "report": report, "prior_reports": []}
    # Persist stopped state before optional registration; a registrar refusal
    # must not erase the fact that this session ran and is waiting on John.
    commission._atomic_write_json(target, record)
    registrations, errors = [], list(request.get("integration_errors") or [])
    try:
        effort = registrar.effort_dir_for(str(folder), str(folder))
        declarations = request.get("deliverables", [])
        if not isinstance(declarations, list) or len(declarations) > 66:
            raise ValueError("invalid deliverables list")
        seen = set()
        for item in declarations:
            kind, relative = item["kind"], item["path"]
            if kind not in KINDS or not isinstance(relative, str) or Path(relative).is_absolute():
                raise ValueError("invalid artifact declaration")
            if ".." in Path(relative).parts or any(c in relative for c in (":", "\r", "\n", "\x00", "`", "|")):
                raise ValueError("invalid artifact path")
            supplied = folder / relative
            cursor = folder
            for part in Path(relative).parts:
                cursor = cursor / part
                if cursor.is_symlink() or getattr(cursor, "is_junction", lambda: False)():
                    raise ValueError("linked artifact refused")
            artifact = supplied.resolve(strict=True)
            artifact.relative_to(folder)
            if not artifact.is_file():
                raise ValueError("artifact is not a produced file")
            if str(artifact) in seen:
                continue
            seen.add(str(artifact))
            where = registrar.where_for(effort, str(folder), request["project_id"], abs_path=str(artifact))
            registered = registrar.register(effort, "Chekhov " + kind, where,
                                            date=report["end"][:10], step=request.get("step_id"),
                                            project_folder=str(folder))
            registrations.append({"kind": kind, "path": relative, **registered})
            if not registered.get("written") and registered.get("reason") != "dup":
                errors.append(registered.get("reason") or "registration refused")
    except Exception as exc:
        errors.append(str(exc))
    try:
        publish_session_attention(folder, request, commission)
    except Exception as exc:
        errors.append(str(exc))
    surfaces = read_surfaces(folder, commission, campaign)
    if not any(row.get("session_id") == session_id for row in surfaces["runs"]):
        errors.append("commission list_runs did not expose this session")
    visible = surfaces["deliverables"].get("items", [])
    for item in registrations:
        if not any(row.get("what") == "Chekhov " + item["kind"]
                   and row.get("path") == item["path"] and row.get("openable") for row in visible):
            errors.append("deliverable not openable through actual reader: " + item["path"])
    heartbeat = surfaces["map"].get("heartbeat") or {}
    expected = (report.get("heartbeat") or {}).get("fields") or {}
    for key, value in expected.items():
        if heartbeat.get(key) != value:
            errors.append("read_map heartbeat mismatch: " + key)
    waiting = report.get("human_wait")
    if waiting and waiting != "none":
        attention = surfaces["map"].get("attention") or {}
        if attention.get("state") != "needs_you" or attention.get("reason") != waiting:
            errors.append("read_map attention does not expose the current human wait")
    if errors:
        record["report"] = {**report, "integration_errors": errors,
                            "say": report["say"] + "\nAnchor registration: " + "; ".join(errors)}
        commission._atomic_write_json(target, record)
    return {"ok": not errors, "error": "; ".join(errors) or None,
            "record": commission.load_run_record(str(folder), session_id),
            "registrations": registrations, **read_surfaces(folder, commission, campaign)}


def run(request):
    commission, registrar, campaign, foundry = modules(request["anchor_dir"])
    action = request.get("action")
    if action == "record_session":
        return record_session(request, commission, registrar, campaign)
    if action == "read":
        folder = identity(request)
        return {"ok": True, **read_surfaces(folder, commission, campaign)}
    if action == "dispatch_fixture":
        folder = identity(request["payload"])
        skill_dir = Path(request["skill_dir"]).resolve(strict=True)
        # Explicit subset is Anchor's documented hermetic registry seam.
        # Keep the real Chekhov manifest, host command and text contract.
        manifest = foundry.chekhov_manifest(skill_dir=str(skill_dir))
        if manifest["host_cmd"] != "node {skill_dir}/bin/chekhov.mjs":
            raise ValueError("fixture requires the canonical Chekhov host command; clear ANCHOR_CHEKHOV_HOST_CMD")
        dispatch = foundry.build_registry_dispatch([manifest])
        result = foundry.run_skill(dispatch, "chekhov", payload=request["payload"])
        source_locations = [{"file": inspect.getsourcefile(fn),
                             "line": inspect.getsourcelines(fn)[1], "symbol": fn.__name__}
                            for fn in (foundry.chekhov_manifest, foundry.build_registry_dispatch,
                                       foundry.run_skill, commission.list_runs,
                                       registrar.register, campaign.read_deliverables, campaign.read_map)]
        return {"ok": True, "dispatch_result": result,
                "argv": dispatch["chekhov"]["argv"],
                "source_locations": source_locations,
                "record": commission.load_run_record(str(folder), request["payload"]["session_id"]),
                **read_surfaces(folder, commission, campaign)}
    raise ValueError("unsupported adapter action")


if __name__ == "__main__":
    try:
        raw = sys.stdin.read(262145)
        if len(raw) > 262144:
            raise ValueError("adapter input too large")
        # Imported diagnostics must not corrupt the one JSON transport object.
        with contextlib.redirect_stdout(sys.stderr):
            response = run(json.loads(raw))
    except Exception as exc:
        response = {"ok": False, "error": type(exc).__name__ + ": " + str(exc)}
    sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
    sys.exit(0 if response.get("ok") else 1)
