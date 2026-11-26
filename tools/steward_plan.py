"""steward_plan — Atomic Plan & Deliverable Spine for Anchor AI Cockpits.

Provides both importable Python functions (`read_plan_state`, `mutate_plan_state`,
`auto_complete_linked_step`) and a standalone CLI (`tools/steward_plan.py`) so the
AI Cockpit Steward and HTTP routes (`/api/steward/plan`) read and mutate
`<cdir>/roadmap.json`, `<cdir>/strip.json`, and `<cdir>/plan-proposal.json`
through one cross-process lock and one 5-state failure contract.

Usage from any Steward / Cockpit:
  python C:\\dev\\Anchor\\tools\\steward_plan.py status
  python C:\\dev\\Anchor\\tools\\steward_plan.py init --steps-json "[{\\"title\\": \\"Scope architecture\\", \\"done_when\\": \\"Spec approved\\"}]"
  python C:\\dev\\Anchor\\tools\\steward_plan.py add-step --title "Draft report" --done-when "PDF registered for review"
  python C:\\dev\\Anchor\\tools\\steward_plan.py set-step --id step-1 --status done
  python C:\\dev\\Anchor\\tools\\steward_plan.py set-next --id step-2
  python C:\\dev\\Anchor\\tools\\steward_plan.py reorder --id step-3 --direction up
  python C:\\dev\\Anchor\\tools\\steward_plan.py park --id step-4
  python C:\\dev\\Anchor\\tools\\steward_plan.py propose --summary "Add validation wave" --steps-json "[...]"
  python C:\\dev\\Anchor\\tools\\steward_plan.py accept-proposal
  python C:\\dev\\Anchor\\tools\\steward_plan.py dismiss-proposal
  python C:\\dev\\Anchor\\tools\\steward_plan.py register-deliverable --step-id step-2 --title "Final Report" --path "deliverables/report.pdf"
"""
from __future__ import annotations

import argparse
import copy
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

ANCHOR_ROOT = Path(__file__).resolve().parent.parent
if str(ANCHOR_ROOT) not in sys.path:
    sys.path.insert(0, str(ANCHOR_ROOT))

import paths  # noqa: E402
from steward_cockpit import steward_core  # noqa: E402

MAX_PLAN_STEPS = 200
PLAN_LOCK_TIMEOUT_SEC = 2.0

MSG_DEPENDENCY_MISSING = "Campaign directory not found"
MSG_DEPENDENCY_SLOW = "Plan state lock busy (>2.0s) \u2014 retry"
MSG_DEPENDENCY_GARBAGE = "Invalid plan mutation or step cap (>200) exceeded"
MSG_STORE_UNREADABLE = "Plan/Deliverables unreadable (unknown) \u2014 inspect roadmap.json"
MSG_EMPTY_VALID = "No plan steps yet \u2014 add a step or ask Steward to draft The Plan"

_ALLOWED_INPUT_STATUSES = {
    "proposed": "proposed",
    "planned": "proposed",
    "todo": "proposed",
    "open": "proposed",
    "pending": "proposed",
    "upcoming": "proposed",
    "active": "active",
    "in_progress": "in_progress",
    "in-progress": "in_progress",
    "working": "in_progress",
    "waiting": "waiting",
    "blocked": "blocked",
    "done": "done",
    "complete": "done",
    "completed": "done",
    "parked": "parked",
}


class PlanError(Exception):
    """Base error carrying the canonical Wave 3 5-state failure contract."""

    failure_state = "dependency-returns-garbage"
    http_status = 400
    default_message = MSG_DEPENDENCY_GARBAGE

    def __init__(self, message: str | None = None, *, detail: str = "") -> None:
        msg = str(message or self.default_message)
        super().__init__(msg)
        self.message = msg
        self.detail = detail

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "ok": False,
            "failure_state": self.failure_state,
            "error": self.message,
            "message": self.message,
        }
        if self.detail:
            out["detail"] = self.detail
        return out


class PlanMissingDirError(PlanError):
    failure_state = "dependency-missing"
    http_status = 404
    default_message = MSG_DEPENDENCY_MISSING


class PlanLockTimeoutError(PlanError, TimeoutError):
    failure_state = "dependency-slow-or-killed"
    http_status = 504
    default_message = MSG_DEPENDENCY_SLOW


class PlanValidationError(PlanError):
    failure_state = "dependency-returns-garbage"
    http_status = 400
    default_message = MSG_DEPENDENCY_GARBAGE


class PlanStoreUnreadableError(PlanError):
    failure_state = "backing-store-unreadable"
    http_status = 500
    default_message = MSG_STORE_UNREADABLE


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _today_iso() -> str:
    return time.strftime("%Y-%m-%d", time.localtime())


def _resolve_cdir(cdir: str | Path | None) -> Path:
    if cdir is None:
        raise PlanMissingDirError(MSG_DEPENDENCY_MISSING)
    raw = str(cdir).strip()
    if not raw or not os.path.isdir(raw):
        raise PlanMissingDirError(MSG_DEPENDENCY_MISSING)
    return Path(os.path.abspath(raw))


def _plan_lock_path(root: Path) -> Path:
    return root / ".ecgberht" / "plan.lock"


def _read_strict_json_dict(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    if not path.is_file():
        raise PlanStoreUnreadableError(MSG_STORE_UNREADABLE, detail=f"Not a regular file: {path.name}")
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except OSError as exc:
        raise PlanStoreUnreadableError(MSG_STORE_UNREADABLE, detail=str(exc)) from exc
    if not raw.strip():
        raise PlanStoreUnreadableError(MSG_STORE_UNREADABLE, detail=f"Empty JSON file: {path.name}")
    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise PlanStoreUnreadableError(MSG_STORE_UNREADABLE, detail=f"{path.name}: {exc}") from exc
    if not isinstance(parsed, dict):
        raise PlanStoreUnreadableError(MSG_STORE_UNREADABLE, detail=f"{path.name} root must be a JSON object")
    return parsed


def _slugify_step_id(title: str, index: int, used_ids: set[str]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(title or "").lower()).strip("-")
    if slug:
        slug = slug[:40].rstrip("-")
    base = f"step-{index + 1}" if not slug else slug
    cand = base
    n = 2
    while cand in used_ids:
        cand = f"{base}-{n}"
        n += 1
    used_ids.add(cand)
    return cand


def _normalize_deliverable_links(raw_delivs: Any) -> list[dict[str, Any]]:
    if raw_delivs is None:
        return []
    if not isinstance(raw_delivs, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for entry in raw_delivs:
        if isinstance(entry, str):
            p = entry.strip()
            if not p:
                continue
            ht = steward_core.clean_human_deliverable_title("", p)
            key = (p.lower(), ht.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "id": p,
                "title": ht,
                "path": p,
                "status": "linked",
            })
        elif isinstance(entry, dict):
            p = str(entry.get("path") or entry.get("open_path") or "").replace("\\", "/").strip()
            raw_t = str(entry.get("title") or entry.get("human_title") or entry.get("what") or "").strip()
            did = str(entry.get("id") or entry.get("deliverable_id") or p or raw_t).strip()
            if not (did or raw_t or p):
                continue
            ht = steward_core.clean_human_deliverable_title(raw_t or did, p)
            st = str(entry.get("status") or "linked").strip().lower() or "linked"
            key = (did.lower(), p.lower())
            if key in seen:
                continue
            seen.add(key)
            out.append({
                "id": did or ht,
                "title": ht,
                "path": p,
                "status": st,
            })
    return out


def _coerce_wave(raw_wave: Any, *, strict: bool = False) -> int | None:
    if raw_wave is None or raw_wave == "" or isinstance(raw_wave, bool):
        return None
    if isinstance(raw_wave, int):
        if raw_wave < 0:
            if strict:
                raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
            return None
        return raw_wave
    s = str(raw_wave).strip()
    if not s:
        return None
    m = re.match(r"^(?:wave[-_\s]*)?(\d+)$", s, re.I)
    if m:
        return int(m.group(1))
    if strict:
        raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
    return None


def _normalize_step(
    raw_item: Any,
    index: int,
    used_ids: set[str],
    *,
    strict_input: bool = False,
) -> dict[str, Any]:
    if isinstance(raw_item, str):
        title = raw_item.strip()
        if not title:
            if strict_input:
                raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
            title = f"Step {index + 1}"
        sid = _slugify_step_id(f"step-{index + 1}", index, used_ids)
        return {
            "id": sid,
            "name": title,
            "title": title,
            "status": "proposed",
            "done": False,
            "parked": False,
            "done_when": "",
            "goal": "",
            "deliverables": [],
            "wave": None,
        }

    if not isinstance(raw_item, dict):
        if strict_input:
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        raise PlanStoreUnreadableError(MSG_STORE_UNREADABLE, detail="Step entry must be an object or string")

    preserved = copy.deepcopy(raw_item)
    raw_title = preserved.get("title") if preserved.get("title") is not None else preserved.get("name")
    title = str(raw_title or "").strip()
    if not title:
        if strict_input:
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        title = str(preserved.get("id") or f"Step {index + 1}").strip()

    raw_id = str(preserved.get("id") or preserved.get("step_id") or "").strip()
    if raw_id:
        if strict_input and raw_id in used_ids:
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        if raw_id in used_ids:
            sid = _slugify_step_id(raw_id, index, used_ids)
        else:
            used_ids.add(raw_id)
            sid = raw_id
    else:
        sid = _slugify_step_id(f"step-{index + 1}", index, used_ids)

    has_explicit_status = "status" in preserved and preserved.get("status") is not None and str(preserved.get("status")).strip() != ""
    raw_status = str(preserved.get("status") or "").strip().lower()
    if has_explicit_status:
        mapped = _ALLOWED_INPUT_STATUSES.get(raw_status)
        if mapped is None:
            if strict_input:
                raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
            mapped = "proposed"
        status = mapped
    else:
        status = "proposed"

    if "done" in preserved and preserved.get("done") is not None:
        if bool(preserved.get("done")):
            status = "done"
        elif status == "done" and not has_explicit_status:
            status = "proposed"

    if "parked" in preserved and preserved.get("parked") is not None:
        if bool(preserved.get("parked")):
            status = "parked"
        elif status == "parked" and not has_explicit_status:
            status = "proposed"

    is_done = status == "done"
    is_parked = status == "parked"

    done_when = str(preserved.get("done_when") or "").strip()
    goal = str(preserved.get("goal") or preserved.get("summary") or "").strip()
    wave = _coerce_wave(preserved.get("wave"), strict=strict_input)

    raw_delivs = preserved.get("deliverables")
    if raw_delivs is None and isinstance(preserved.get("navigation"), dict):
        fp = preserved["navigation"].get("featured_paths")
        if isinstance(fp, list):
            raw_delivs = fp
    if strict_input and raw_delivs is not None and not isinstance(raw_delivs, list):
        raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
    deliverables = _normalize_deliverable_links(raw_delivs)

    preserved.update({
        "id": sid,
        "name": title,
        "title": title,
        "status": status,
        "done": is_done,
        "parked": is_parked,
        "done_when": done_when,
        "goal": goal,
        "deliverables": deliverables,
        "wave": wave,
    })

    if is_done:
        preserved.pop("waiting_on", None)
        if isinstance(preserved.get("refinement"), dict):
            ref_d = dict(preserved["refinement"])
            if str(ref_d.get("phase") or "").lower() in ("awaiting_review", "blocked", "working", "in_progress"):
                ref_d["phase"] = "done"
            preserved["refinement"] = ref_d
    if isinstance(preserved.get("navigation"), dict):
        nav_d = dict(preserved["navigation"])
        nav_d["label"] = title
        preserved["navigation"] = nav_d

    return preserved


def _extract_raw_steps(roadmap_data: dict[str, Any] | None) -> list[Any]:
    if roadmap_data is None:
        return []
    has_steps = "steps" in roadmap_data and roadmap_data["steps"] is not None
    has_proj = "roadmap_projection" in roadmap_data and roadmap_data["roadmap_projection"] is not None
    if has_steps and not isinstance(roadmap_data["steps"], list):
        raise PlanStoreUnreadableError(MSG_STORE_UNREADABLE, detail="roadmap.json 'steps' must be a list")
    if has_proj and not isinstance(roadmap_data["roadmap_projection"], list):
        raise PlanStoreUnreadableError(MSG_STORE_UNREADABLE, detail="roadmap.json 'roadmap_projection' must be a list")
    if has_steps and len(roadmap_data["steps"]) > 0:
        return list(roadmap_data["steps"])
    if has_proj:
        return list(roadmap_data["roadmap_projection"])
    if has_steps:
        return list(roadmap_data["steps"])
    return []


def _compute_counts(steps: list[dict[str, Any]]) -> dict[str, int]:
    total = len(steps)
    done = sum(1 for s in steps if s.get("done") or s.get("status") == "done")
    parked = sum(1 for s in steps if s.get("parked") or s.get("status") == "parked")
    active = sum(
        1
        for s in steps
        if not s.get("done")
        and not s.get("parked")
        and s.get("status") in ("active", "in_progress", "waiting", "blocked")
    )
    remaining = max(0, total - done - parked)
    return {
        "total": total,
        "done": done,
        "active": active,
        "parked": parked,
        "remaining": remaining,
    }


def _compute_focus(steps: list[dict[str, Any]], strip_data: dict[str, Any] | None = None) -> dict[str, Any] | None:
    if not steps:
        return None
    preferred_id = ""
    next_rec = ""
    if isinstance(strip_data, dict):
        inner = strip_data.get("strip") if isinstance(strip_data.get("strip"), dict) else strip_data
        preferred_id = str(inner.get("current_step_id") or inner.get("now_step_id") or strip_data.get("current_step_id") or "").strip()
        next_rec = str(inner.get("next_recommended") or strip_data.get("next_recommended") or "").strip()

    def _decorate_focus(step_dict: dict[str, Any], idx: int) -> dict[str, Any]:
        out = copy.deepcopy(step_dict)
        out["index"] = idx
        out["step_id"] = str(out.get("id") or "")
        out["next_move"] = str(next_rec or out.get("goal") or out.get("done_when") or out.get("title") or "")
        return out

    if preferred_id:
        for idx, s in enumerate(steps):
            if s.get("id") == preferred_id and not s.get("done") and not s.get("parked"):
                return _decorate_focus(s, idx)
    for idx, s in enumerate(steps):
        if not s.get("done") and not s.get("parked") and s.get("status") in ("active", "in_progress", "waiting", "blocked"):
            return _decorate_focus(s, idx)
    for idx, s in enumerate(steps):
        if not s.get("done") and not s.get("parked"):
            return _decorate_focus(s, idx)
    return None


def _load_disk_state_unlocked(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any], dict[str, Any] | None]:
    rm_path = root / "roadmap.json"
    rm_alt = root / ".ecgberht" / "roadmap.json"
    roadmap_data = _read_strict_json_dict(rm_path)
    if roadmap_data is None and rm_alt.exists():
        roadmap_data = _read_strict_json_dict(rm_alt)

    st_path = root / "strip.json"
    st_alt = root / ".ecgberht" / "strip.json"
    strip_data = _read_strict_json_dict(st_path)
    if strip_data is None and st_alt.exists():
        strip_data = _read_strict_json_dict(st_alt)

    prop_path = root / "plan-proposal.json"
    prop_alt = root / ".ecgberht" / "plan-proposal.json"
    prop_data = _read_strict_json_dict(prop_path)
    if prop_data is None and prop_alt.exists():
        prop_data = _read_strict_json_dict(prop_alt)

    raw_steps = _extract_raw_steps(roadmap_data)
    used_ids: set[str] = set()
    steps = [_normalize_step(item, idx, used_ids, strict_input=False) for idx, item in enumerate(raw_steps)]

    return (
        dict(roadmap_data) if isinstance(roadmap_data, dict) else {},
        steps,
        dict(strip_data) if isinstance(strip_data, dict) else {},
        dict(prop_data) if isinstance(prop_data, dict) else None,
    )


def _active_proposal_view(prop_data: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(prop_data, dict):
        return None
    status = str(prop_data.get("status") or "").strip().lower()
    is_pending = prop_data.get("pending") is True or (prop_data.get("pending") is None and status == "pending")
    if not is_pending or status in ("accepted", "dismissed"):
        return None
    out = copy.deepcopy(prop_data)
    out["pending"] = True
    out.setdefault("status", "pending")
    return out


def _build_plan_response(
    steps: list[dict[str, Any]],
    strip_data: dict[str, Any] | None,
    prop_data: dict[str, Any] | None,
    *,
    roadmap_data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    focus = _compute_focus(steps, strip_data)
    counts = _compute_counts(steps)
    proposal = _active_proposal_view(prop_data)
    is_empty = len(steps) == 0
    resp: dict[str, Any] = {
        "ok": True,
        "failure_state": "empty-but-valid" if is_empty else "ok",
        "steps": [copy.deepcopy(s) for s in steps],
        "focus": focus,
        "proposal": proposal,
        "counts": counts,
    }
    if is_empty:
        resp["message"] = MSG_EMPTY_VALID
    else:
        resp["message"] = f"{counts['done']}/{counts['total']} steps completed"
    if isinstance(roadmap_data, dict) and roadmap_data.get("goal"):
        resp["goal"] = str(roadmap_data.get("goal") or "")
    return resp


def _invalidate_in_process_caches(root: Path | None = None) -> None:
    sc = sys.modules.get("steward_cockpit.steward_campaign")
    if sc is not None:
        try:
            lock = getattr(sc, "_JSON_FILE_CACHE_LOCK", None)
            cache = getattr(sc, "_JSON_FILE_CACHE", None)
            if lock is not None and isinstance(cache, dict):
                with lock:
                    cache.clear()
            elif isinstance(cache, dict):
                cache.clear()
        except Exception:
            pass
        for attr in ("_PLAN_PROPOSAL_CACHE", "_PLAN_HISTORY_CACHE", "_RAW_DELIVERABLES_CACHE", "_DISCOVER_EFFORTS_CACHE"):
            try:
                d = getattr(sc, attr, None)
                if isinstance(d, dict):
                    d.clear()
            except Exception:
                pass
    sr = sys.modules.get("steward_cockpit.steward_routes")
    if sr is not None:
        for cache_name, lock_name in (("_DELIV_CACHE", "_DELIV_LOCK"), ("_STATE_CACHE", "_STATE_LOCK")):
            try:
                rlock = getattr(sr, lock_name, None)
                rcache = getattr(sr, cache_name, None)
                if rlock is not None and isinstance(rcache, dict):
                    with rlock:
                        rcache.clear()
                elif isinstance(rcache, dict):
                    rcache.clear()
            except Exception:
                pass


def _sync_strip_with_steps(
    strip_data: dict[str, Any],
    steps: list[dict[str, Any]],
    *,
    preferred_focus_id: str = "",
    next_move_override: str | None = None,
) -> dict[str, Any]:
    out = dict(strip_data) if isinstance(strip_data, dict) else {}
    if preferred_focus_id:
        out["current_step_id"] = preferred_focus_id
        out["now_step_id"] = preferred_focus_id
    focus = _compute_focus(steps, out)
    if focus is not None:
        fid = str(focus.get("id") or "")
        ftitle = str(focus.get("title") or focus.get("name") or "")
        fdw = str(focus.get("done_when") or "").strip()
        out["current_step_id"] = fid
        out["now_step_id"] = fid
        out["active_effort"] = ftitle + (f" \u2014 {fdw}" if fdw else "")
        out["active_effort_as_of"] = _today_iso()
        if next_move_override is not None and str(next_move_override).strip():
            out["next_recommended"] = str(next_move_override).strip()
        else:
            next_open = [
                s for s in steps
                if s.get("id") != fid and not s.get("done") and not s.get("parked")
            ]
            if next_open:
                out["next_recommended"] = str(next_open[0].get("title") or next_open[0].get("name") or "")
            else:
                out["next_recommended"] = f"Complete {ftitle}"
    else:
        out["current_step_id"] = ""
        out["now_step_id"] = ""
        if next_move_override is not None and str(next_move_override).strip():
            out["next_recommended"] = str(next_move_override).strip()
        elif steps and all(s.get("done") or s.get("parked") for s in steps):
            out["active_effort"] = "All planned steps completed"
            out["active_effort_as_of"] = _today_iso()
            out["next_recommended"] = "Await next objective"
            if str(out.get("human_wait") or "").strip().lower() not in ("", "none"):
                out["human_wait"] = "none"
    out["updated_at"] = _now_iso()
    return out


def _persist_plan_files_locked(
    root: Path,
    roadmap_base: dict[str, Any],
    steps: list[dict[str, Any]],
    strip_base: dict[str, Any],
    *,
    preferred_focus_id: str = "",
    goal_override: str | None = None,
    next_move_override: str | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if len(steps) > MAX_PLAN_STEPS:
        raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)

    # Ensure active step alignment when a preferred focus step is chosen
    focus_probe = dict(strip_base) if isinstance(strip_base, dict) else {}
    if preferred_focus_id:
        focus_probe["current_step_id"] = preferred_focus_id
    focus = _compute_focus(steps, focus_probe)
    focus_id = str(focus.get("id") or "") if focus else ""

    normalized_steps: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for idx, s in enumerate(steps):
        ns = _normalize_step(s, idx, used_ids, strict_input=False)
        if focus_id and ns["id"] == focus_id and ns["status"] == "proposed":
            ns["status"] = "active"
        if isinstance(ns.get("navigation"), dict):
            nav_d = dict(ns["navigation"])
            nav_d["current"] = bool(focus_id and ns["id"] == focus_id)
            ns["navigation"] = nav_d
        normalized_steps.append(ns)

    rm_out = dict(roadmap_base) if isinstance(roadmap_base, dict) else {}
    if goal_override is not None and str(goal_override).strip():
        rm_out["goal"] = str(goal_override).strip()
    rm_out["steps"] = [copy.deepcopy(s) for s in normalized_steps]
    rm_out["roadmap_projection"] = [copy.deepcopy(s) for s in normalized_steps]
    rm_out["now_step_id"] = focus_id or None
    rm_out["updated_at"] = _now_iso()

    strip_out = _sync_strip_with_steps(
        strip_base,
        normalized_steps,
        preferred_focus_id=focus_id,
        next_move_override=next_move_override,
    )

    paths.atomic_write_json(root / "roadmap.json", rm_out)
    if (root / ".ecgberht" / "roadmap.json").is_file():
        paths.atomic_write_json(root / ".ecgberht" / "roadmap.json", rm_out)

    paths.atomic_write_json(root / "strip.json", strip_out)
    if (root / ".ecgberht" / "strip.json").is_file():
        paths.atomic_write_json(root / ".ecgberht" / "strip.json", strip_out)

    _invalidate_in_process_caches(root)
    return rm_out, strip_out


def _notify_cave_activity(root: Path, events: list[dict[str, Any]]) -> None:
    if not events:
        return
    try:
        import comms_connector as cc
        decorated: list[dict[str, Any]] = []
        for ev in events:
            row = dict(ev)
            row.setdefault("cockpit_name", root.name)
            decorated.append(row)
        cc.reconcile_working_list_activity(cockpit_events=decorated)
    except Exception:
        pass


def read_plan_state(cdir: str | Path | None) -> dict[str, Any]:
    """Read `<cdir>/roadmap.json`, `strip.json`, and `plan-proposal.json` under `plan.lock`
    and return the canonical 5-state plan envelope."""
    root = _resolve_cdir(cdir)
    try:
        with paths.cross_process_lock(_plan_lock_path(root), timeout_sec=PLAN_LOCK_TIMEOUT_SEC):
            roadmap_data, steps, strip_data, prop_data = _load_disk_state_unlocked(root)
    except TimeoutError as exc:
        raise PlanLockTimeoutError(MSG_DEPENDENCY_SLOW) from exc
    return _build_plan_response(steps, strip_data, prop_data, roadmap_data=roadmap_data)


def _apply_single_op_in_memory(
    op_norm: str,
    payload: dict[str, Any],
    steps: list[dict[str, Any]],
    strip_data: dict[str, Any],
) -> tuple[list[dict[str, Any]], str, list[dict[str, Any]]]:
    """Apply one step mutation in memory and return `(new_steps, preferred_focus_id, completed_steps)`."""
    completed: list[dict[str, Any]] = []
    preferred_focus_id = str(strip_data.get("current_step_id") or strip_data.get("now_step_id") or "").strip()

    if op_norm == "init":
        raw_list = payload.get("steps")
        if not isinstance(raw_list, list):
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        if len(raw_list) > MAX_PLAN_STEPS:
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        used_ids: set[str] = set()
        new_steps = [_normalize_step(item, idx, used_ids, strict_input=True) for idx, item in enumerate(raw_list)]
        first_open = next((s["id"] for s in new_steps if not s.get("done") and not s.get("parked")), "")
        return new_steps, first_open, completed

    if op_norm == "add_step":
        if len(steps) + 1 > MAX_PLAN_STEPS:
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        step_obj = payload.get("step") if isinstance(payload.get("step"), dict) else payload
        if not isinstance(step_obj, dict):
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        used_ids = {str(s["id"]) for s in steps}
        new_step = _normalize_step(step_obj, len(steps), used_ids, strict_input=True)
        new_steps = [copy.deepcopy(s) for s in steps]
        after_id = str(payload.get("after_id") or step_obj.get("after_id") or "").strip()
        pos = payload.get("index") if payload.get("index") is not None else payload.get("position")
        if after_id:
            idx_after = next((i for i, s in enumerate(new_steps) if s["id"] == after_id), None)
            if idx_after is None:
                raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
            new_steps.insert(idx_after + 1, new_step)
        elif pos is not None:
            try:
                pos_i = int(pos)
            except (TypeError, ValueError) as exc:
                raise PlanValidationError(MSG_DEPENDENCY_GARBAGE) from exc
            pos_i = max(0, min(len(new_steps), pos_i))
            new_steps.insert(pos_i, new_step)
        else:
            new_steps.append(new_step)
        if new_step.get("done"):
            completed.append(new_step)
        return new_steps, preferred_focus_id or new_step["id"], completed

    if op_norm == "set_step":
        target_id = str(payload.get("id") or payload.get("step_id") or "").strip()
        if not target_id:
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        idx_target = next((i for i, s in enumerate(steps) if s["id"] == target_id), None)
        if idx_target is None:
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        cur = copy.deepcopy(steps[idx_target])
        was_done = bool(cur.get("done") or cur.get("status") == "done")

        if "title" in payload or "name" in payload:
            raw_t = payload.get("title") if "title" in payload else payload.get("name")
            new_t = str(raw_t or "").strip()
            if not new_t:
                raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
            cur["title"] = new_t
            cur["name"] = new_t

        if "status" in payload and payload.get("status") is not None:
            st_raw = str(payload.get("status") or "").strip().lower()
            mapped = _ALLOWED_INPUT_STATUSES.get(st_raw)
            if mapped is None:
                raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
            cur["status"] = mapped
            cur["done"] = mapped == "done"
            cur["parked"] = mapped == "parked"

        if "done" in payload and payload.get("done") is not None:
            if not isinstance(payload.get("done"), bool) and str(payload.get("done")).lower() not in ("true", "false", "1", "0"):
                raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
            d_flag = payload.get("done") is True or str(payload.get("done")).lower() in ("true", "1")
            cur["done"] = d_flag
            if d_flag:
                cur["status"] = "done"
                cur["parked"] = False
            elif cur.get("status") == "done":
                cur["status"] = "proposed"

        if "parked" in payload and payload.get("parked") is not None:
            p_flag = payload.get("parked") is True or str(payload.get("parked")).lower() in ("true", "1")
            cur["parked"] = p_flag
            if p_flag:
                cur["status"] = "parked"
                cur["done"] = False
            elif cur.get("status") == "parked":
                cur["status"] = "proposed"

        if "done_when" in payload and payload.get("done_when") is not None:
            cur["done_when"] = str(payload.get("done_when") or "").strip()
        if "goal" in payload and payload.get("goal") is not None:
            cur["goal"] = str(payload.get("goal") or "").strip()
        if "wave" in payload:
            cur["wave"] = _coerce_wave(payload.get("wave"), strict=True)
        if "deliverables" in payload and payload.get("deliverables") is not None:
            if not isinstance(payload.get("deliverables"), list):
                raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
            cur["deliverables"] = _normalize_deliverable_links(payload.get("deliverables"))

        used_ids = {str(s["id"]) for i, s in enumerate(steps) if i != idx_target}
        norm_cur = _normalize_step(cur, idx_target, used_ids, strict_input=True)
        new_steps = [copy.deepcopy(s) for s in steps]
        new_steps[idx_target] = norm_cur

        if norm_cur.get("done") and not was_done:
            completed.append(norm_cur)
            if preferred_focus_id == target_id:
                preferred_focus_id = ""
        elif norm_cur.get("status") == "active":
            preferred_focus_id = target_id
            for i, s in enumerate(new_steps):
                if i != idx_target and s.get("status") == "active":
                    s["status"] = "proposed"
        return new_steps, preferred_focus_id, completed

    if op_norm == "complete_and_next":
        target_id = str(payload.get("id") or payload.get("step_id") or "").strip()
        if not target_id:
            foc = _compute_focus(steps, strip_data)
            if foc is None:
                raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
            target_id = str(foc["id"])
        idx_target = next((i for i, s in enumerate(steps) if s["id"] == target_id), None)
        if idx_target is None:
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        new_steps = [copy.deepcopy(s) for s in steps]
        cur = new_steps[idx_target]
        was_done = bool(cur.get("done"))
        cur["status"] = "done"
        cur["done"] = True
        cur["parked"] = False
        used_ids = {str(s["id"]) for i, s in enumerate(new_steps) if i != idx_target}
        new_steps[idx_target] = _normalize_step(cur, idx_target, used_ids, strict_input=False)
        if not was_done:
            completed.append(new_steps[idx_target])

        next_id = ""
        for cand in new_steps[idx_target + 1 :] + new_steps[:idx_target]:
            if not cand.get("done") and not cand.get("parked"):
                next_id = str(cand["id"])
                break
        if next_id:
            for s in new_steps:
                if s["id"] == next_id and s["status"] == "proposed":
                    s["status"] = "active"
                elif s["id"] != next_id and s["status"] == "active":
                    s["status"] = "proposed"
        return new_steps, next_id, completed

    if op_norm in ("focus", "set_next"):
        target_id = str(payload.get("id") or payload.get("step_id") or "").strip()
        if not target_id:
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        idx_target = next((i for i, s in enumerate(steps) if s["id"] == target_id), None)
        if idx_target is None:
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        new_steps = [copy.deepcopy(s) for s in steps]
        target = new_steps[idx_target]
        if target.get("parked"):
            target["parked"] = False
            target["status"] = "active"
        elif not target.get("done"):
            target["status"] = "active"
        for i, s in enumerate(new_steps):
            if i != idx_target and s.get("status") == "active":
                s["status"] = "proposed"
        return new_steps, target_id, completed

    if op_norm == "reorder":
        new_steps = [copy.deepcopy(s) for s in steps]
        order = payload.get("order")
        if order is not None:
            if not isinstance(order, list) or not order:
                raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
            order_ids = [str(x or "").strip() for x in order]
            by_id = {s["id"]: s for s in new_steps}
            if any(not oid or oid not in by_id for oid in order_ids):
                raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
            if len(set(order_ids)) != len(order_ids):
                raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
            placed = [by_id[oid] for oid in order_ids]
            placed_set = set(order_ids)
            remainder = [s for s in new_steps if s["id"] not in placed_set]
            return placed + remainder, preferred_focus_id, completed

        target_id = str(payload.get("id") or payload.get("step_id") or "").strip()
        direction = str(payload.get("direction") or "").strip().lower()
        if not target_id or direction not in ("up", "down"):
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        idx_target = next((i for i, s in enumerate(new_steps) if s["id"] == target_id), None)
        if idx_target is None:
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        swap_idx = idx_target - 1 if direction == "up" else idx_target + 1
        if 0 <= swap_idx < len(new_steps):
            new_steps[idx_target], new_steps[swap_idx] = new_steps[swap_idx], new_steps[idx_target]
        return new_steps, preferred_focus_id, completed

    if op_norm == "park":
        target_id = str(payload.get("id") or payload.get("step_id") or "").strip()
        if not target_id:
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        idx_target = next((i for i, s in enumerate(steps) if s["id"] == target_id), None)
        if idx_target is None:
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
        new_steps = [copy.deepcopy(s) for s in steps]
        cur = new_steps[idx_target]
        if "parked" in payload and payload.get("parked") is not None:
            make_parked = bool(payload.get("parked"))
        else:
            make_parked = not bool(cur.get("parked") or cur.get("status") == "parked")
        if make_parked:
            cur["status"] = "parked"
            cur["parked"] = True
            cur["done"] = False
            if preferred_focus_id == target_id:
                preferred_focus_id = ""
        else:
            cur["parked"] = False
            if cur.get("status") == "parked":
                cur["status"] = "proposed"
        return new_steps, preferred_focus_id, completed

    raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)


def mutate_plan_state(
    cdir: str | Path | None,
    op: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Mutate `<cdir>/roadmap.json`, `strip.json`, or `plan-proposal.json` atomically under `plan.lock`."""
    root = _resolve_cdir(cdir)
    if payload is None:
        payload_d: dict[str, Any] = {}
    elif isinstance(payload, dict):
        payload_d = dict(payload)
    else:
        raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)

    op_norm = str(op or payload_d.get("op") or "").strip().lower().replace("-", "_")
    if not op_norm:
        raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
    if op_norm == "status":
        return read_plan_state(root)

    allowed_ops = {
        "init",
        "add_step",
        "set_step",
        "complete_and_next",
        "focus",
        "set_next",
        "reorder",
        "park",
        "propose",
        "accept_proposal",
        "dismiss_proposal",
        "register_deliverable",
    }
    if op_norm not in allowed_ops:
        raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)

    cave_events: list[dict[str, Any]] = []
    reg_deliv_args: dict[str, Any] | None = None

    try:
        with paths.cross_process_lock(_plan_lock_path(root), timeout_sec=PLAN_LOCK_TIMEOUT_SEC):
            roadmap_data, steps, strip_data, prop_data = _load_disk_state_unlocked(root)

            if op_norm == "propose":
                summary = str(payload_d.get("summary") or payload_d.get("title") or "").strip()
                reason = str(payload_d.get("reason") or payload_d.get("why") or "").strip()
                raw_prop_steps = payload_d.get("proposed_steps")
                if raw_prop_steps is None and "steps" in payload_d:
                    raw_prop_steps = payload_d.get("steps")
                raw_ops = payload_d.get("ops")

                norm_prop_steps: list[dict[str, Any]] | None = None
                if raw_prop_steps is not None:
                    if not isinstance(raw_prop_steps, list) or len(raw_prop_steps) > MAX_PLAN_STEPS:
                        raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
                    p_ids: set[str] = set()
                    norm_prop_steps = [
                        _normalize_step(it, idx, p_ids, strict_input=True)
                        for idx, it in enumerate(raw_prop_steps)
                    ]

                norm_ops: list[dict[str, Any]] = []
                if raw_ops is not None:
                    if not isinstance(raw_ops, list):
                        raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
                    for o_item in raw_ops:
                        if not isinstance(o_item, dict) or not str(o_item.get("op") or "").strip():
                            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
                        norm_ops.append(copy.deepcopy(o_item))
                    # Dry-run ops on a copy to validate and enforce <= 200 cap at propose time
                    sim_steps = [copy.deepcopy(s) for s in steps]
                    sim_strip = copy.deepcopy(strip_data)
                    for o_item in norm_ops:
                        sub_op = str(o_item.get("op") or "").strip().lower().replace("-", "_")
                        sim_steps, pref_id, _ = _apply_single_op_in_memory(sub_op, o_item, sim_steps, sim_strip)
                        if len(sim_steps) > MAX_PLAN_STEPS:
                            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
                        if pref_id:
                            sim_strip["current_step_id"] = pref_id

                if norm_prop_steps is None and not norm_ops:
                    raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
                if not summary:
                    summary = "Proposed update to The Plan"

                prop_id = str(payload_d.get("id") or f"prop-{int(time.time() * 1000)}").strip()
                new_prop = {
                    "id": prop_id,
                    "pending": True,
                    "status": "pending",
                    "summary": summary,
                    "reason": reason,
                    "ops": norm_ops,
                    "proposed_steps": norm_prop_steps if norm_prop_steps is not None else [],
                    "created_at": _now_iso(),
                }
                paths.atomic_write_json(root / "plan-proposal.json", new_prop)
                if (root / ".ecgberht").is_dir():
                    paths.atomic_write_json(root / ".ecgberht" / "plan-proposal.json", new_prop)
                _invalidate_in_process_caches(root)
                return _build_plan_response(steps, strip_data, new_prop, roadmap_data=roadmap_data)

            if op_norm == "accept_proposal":
                active_prop = _active_proposal_view(prop_data)
                if active_prop is None:
                    raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
                req_id = str(payload_d.get("id") or payload_d.get("proposal_id") or "").strip()
                if req_id and active_prop.get("id") and req_id != str(active_prop.get("id")):
                    raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)

                prop_ops = active_prop.get("ops") if isinstance(active_prop.get("ops"), list) else []
                prop_steps = active_prop.get("proposed_steps") if isinstance(active_prop.get("proposed_steps"), list) else []
                preferred_focus_id = str(strip_data.get("current_step_id") or "").strip()
                completed_steps: list[dict[str, Any]] = []

                if prop_steps:
                    if len(prop_steps) > MAX_PLAN_STEPS:
                        raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
                    p_ids = set()
                    new_steps = [_normalize_step(it, idx, p_ids, strict_input=True) for idx, it in enumerate(prop_steps)]
                    preferred_focus_id = next((s["id"] for s in new_steps if not s.get("done") and not s.get("parked")), "")
                elif prop_ops:
                    new_steps = [copy.deepcopy(s) for s in steps]
                    sim_strip = copy.deepcopy(strip_data)
                    for o_item in prop_ops:
                        sub_op = str(o_item.get("op") or "").strip().lower().replace("-", "_")
                        new_steps, pref_id, comp = _apply_single_op_in_memory(sub_op, o_item, new_steps, sim_strip)
                        completed_steps.extend(comp)
                        if pref_id:
                            preferred_focus_id = pref_id
                            sim_strip["current_step_id"] = pref_id
                else:
                    raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)

                if len(new_steps) > MAX_PLAN_STEPS:
                    raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)

                rm_out, strip_out = _persist_plan_files_locked(
                    root, roadmap_data, new_steps, strip_data, preferred_focus_id=preferred_focus_id
                )
                resolved_prop = dict(active_prop)
                resolved_prop["pending"] = False
                resolved_prop["status"] = "accepted"
                resolved_prop["resolved_at"] = _now_iso()
                paths.atomic_write_json(root / "plan-proposal.json", resolved_prop)
                if (root / ".ecgberht" / "plan-proposal.json").is_file():
                    paths.atomic_write_json(root / ".ecgberht" / "plan-proposal.json", resolved_prop)
                _invalidate_in_process_caches(root)
                for cs in completed_steps:
                    cave_events.append({
                        "kind": "step_completed",
                        "step_id": cs["id"],
                        "title": cs["title"],
                    })
                resp = _build_plan_response(rm_out["steps"], strip_out, resolved_prop, roadmap_data=rm_out)
                resp["accepted_proposal_id"] = resolved_prop.get("id")
            elif op_norm == "dismiss_proposal":
                active_prop = _active_proposal_view(prop_data)
                if active_prop is None and not isinstance(prop_data, dict):
                    raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
                base_prop = dict(active_prop or prop_data or {})
                req_id = str(payload_d.get("id") or payload_d.get("proposal_id") or "").strip()
                if req_id and base_prop.get("id") and req_id != str(base_prop.get("id")):
                    raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
                base_prop["pending"] = False
                base_prop["status"] = "dismissed"
                base_prop["resolved_at"] = _now_iso()
                paths.atomic_write_json(root / "plan-proposal.json", base_prop)
                if (root / ".ecgberht" / "plan-proposal.json").is_file():
                    paths.atomic_write_json(root / ".ecgberht" / "plan-proposal.json", base_prop)
                _invalidate_in_process_caches(root)
                return _build_plan_response(steps, strip_data, base_prop, roadmap_data=roadmap_data)
            elif op_norm == "register_deliverable":
                raw_title = str(payload_d.get("title") or payload_d.get("what") or "").strip()
                raw_path_in = str(payload_d.get("path") or "").strip()
                if raw_path_in:
                    if raw_path_in.startswith(("/", "\\")) or ":" in raw_path_in:
                        raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
                    raw_path = raw_path_in.replace("\\", "/").strip("/")
                    if not raw_path or any(seg in ("", ".", "..") for seg in raw_path.split("/")):
                        raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
                    try:
                        resolved_target = (root / raw_path).resolve()
                        if not resolved_target.is_relative_to(root.resolve()):
                            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
                    except PlanValidationError:
                        raise
                    except Exception as exc:
                        raise PlanValidationError(MSG_DEPENDENCY_GARBAGE) from exc
                else:
                    raw_path = ""
                if not raw_title and not raw_path:
                    raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
                clean_title = steward_core.clean_human_deliverable_title(raw_title, raw_path)
                deliv_status = str(payload_d.get("status") or "for_review").strip().lower() or "for_review"
                deliv_id = str(payload_d.get("deliverable_id") or payload_d.get("id") or raw_path or clean_title).strip()

                target_step_id = str(payload_d.get("step_id") or payload_d.get("step") or "").strip()
                new_steps = [copy.deepcopy(s) for s in steps]
                idx_target: int | None = None
                if target_step_id:
                    idx_target = next((i for i, s in enumerate(new_steps) if s["id"] == target_step_id), None)
                    if idx_target is None:
                        raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
                elif new_steps:
                    foc = _compute_focus(new_steps, strip_data)
                    if foc is not None:
                        idx_target = next((i for i, s in enumerate(new_steps) if s["id"] == foc["id"]), None)

                linked_step_id = ""
                if idx_target is not None:
                    st_row = new_steps[idx_target]
                    linked_step_id = str(st_row["id"])
                    cur_links = list(st_row.get("deliverables") or [])
                    cur_links.append({
                        "id": deliv_id,
                        "title": clean_title,
                        "path": raw_path,
                        "status": deliv_status,
                    })
                    st_row["deliverables"] = _normalize_deliverable_links(cur_links)

                rm_out, strip_out = _persist_plan_files_locked(
                    root,
                    roadmap_data,
                    new_steps,
                    strip_data,
                    preferred_focus_id=str(strip_data.get("current_step_id") or ""),
                )
                reg_deliv_args = {
                    "title": clean_title,
                    "raw_what": raw_title,
                    "path": raw_path,
                    "status": deliv_status,
                    "step_id": linked_step_id,
                    "deliverable_id": deliv_id,
                }
                resp = _build_plan_response(rm_out["steps"], strip_out, prop_data, roadmap_data=rm_out)
            else:
                new_steps, preferred_focus_id, completed_steps = _apply_single_op_in_memory(
                    op_norm, payload_d, steps, strip_data
                )
                goal_override = (
                    str(payload_d["goal"]).strip()
                    if op_norm == "init" and "goal" in payload_d and payload_d.get("goal") is not None
                    else (
                        str(payload_d["campaign_goal"]).strip()
                        if payload_d.get("campaign_goal") is not None
                        else None
                    )
                )
                next_move_override = (
                    str(payload_d["next_move"]).strip()
                    if payload_d.get("next_move") is not None and str(payload_d["next_move"]).strip()
                    else None
                )
                rm_out, strip_out = _persist_plan_files_locked(
                    root,
                    roadmap_data,
                    new_steps,
                    strip_data,
                    preferred_focus_id=preferred_focus_id,
                    goal_override=goal_override,
                    next_move_override=next_move_override,
                )
                for cs in completed_steps:
                    cave_events.append({
                        "kind": "step_completed",
                        "step_id": cs["id"],
                        "title": cs["title"],
                    })
                resp = _build_plan_response(rm_out["steps"], strip_out, prop_data, roadmap_data=rm_out)
    except TimeoutError as exc:
        if isinstance(exc, PlanLockTimeoutError):
            raise
        raise PlanLockTimeoutError(MSG_DEPENDENCY_SLOW) from exc

    if reg_deliv_args is not None:
        _register_in_deliverables_md(root, reg_deliv_args, cave_events)

    if cave_events:
        _notify_cave_activity(root, cave_events)

    return resp


def _register_in_deliverables_md(
    root: Path,
    reg_args: dict[str, Any],
    cave_events: list[dict[str, Any]],
) -> None:
    raw_path = str(reg_args.get("path") or "").strip()
    clean_title = str(reg_args.get("title") or "Deliverable").strip()
    status = str(reg_args.get("status") or "for_review").strip().lower()
    step_id = str(reg_args.get("step_id") or "").strip()

    prefix = "FOR REVIEW \u2014 " if status in ("for_review", "review", "awaiting_review") else (
        "FINAL \u2014 " if status in ("final", "approved", "accepted") else ""
    )
    what_label = f"{prefix}{clean_title}" if prefix else clean_title

    registered_via_api = False
    if raw_path:
        cand = root / raw_path
        try:
            import deliverables_register as dr
            reg_res = dr.register(
                root,
                what_label,
                f"`{raw_path}`",
                step=step_id,
                notify=False,
            )
            if isinstance(reg_res, dict) and (reg_res.get("written") or reg_res.get("reason") == "dup"):
                _invalidate_in_process_caches(root)
        except Exception:
            pass

    if status in ("for_review", "review", "awaiting_review"):
        cave_events.append({
            "kind": "deliverable_for_review",
            "deliverable_id": str(reg_args.get("deliverable_id") or raw_path or clean_title),
            "title": clean_title,
            "step_id": step_id,
        })


def auto_complete_linked_step(
    cdir: str | Path | None,
    *,
    step_id: str | None = None,
    deliverable_id: str | None = None,
    deliverable_path: str | None = None,
    deliverable_title: str | None = None,
    wave_n: int | None = None,
    notify_cave: bool = True,
) -> dict[str, Any]:
    """Automatically mark a linked open step `done` in `roadmap.json` and advance focus in `strip.json`.

    Called when:
      1. A Key Deliverable transitions `For Review -> Final` (accepted by John), or
      2. A Foreman / code_jobs wave reaches `GO` / `GREEN` completion.
    """
    root = _resolve_cdir(cdir)
    sid_norm = str(step_id or "").strip()
    did_norm = str(deliverable_id or "").replace("\\", "/").strip().lower()
    dpath_norm = str(deliverable_path or "").replace("\\", "/").strip().lower()
    dtitle_clean = (
        steward_core.clean_human_deliverable_title(deliverable_title, deliverable_path or "")
        if deliverable_title
        else ""
    ).lower()
    wave_int = _coerce_wave(wave_n, strict=False)

    matched_step: dict[str, Any] | None = None

    try:
        with paths.cross_process_lock(_plan_lock_path(root), timeout_sec=PLAN_LOCK_TIMEOUT_SEC):
            roadmap_data, steps, strip_data, prop_data = _load_disk_state_unlocked(root)
            if not steps:
                return {
                    "ok": True,
                    "completed": False,
                    "step_id": None,
                    "completed_step_id": None,
                    "completed_step_ids": [],
                    "focus": None,
                }

            idx_match: int | None = None

            # 1. Exact step_id match
            if sid_norm:
                for i, s in enumerate(steps):
                    if str(s.get("id") or "").strip().lower() == sid_norm.lower():
                        idx_match = i
                        break
                if idx_match is None and sid_norm.isdigit():
                    one_based = int(sid_norm) - 1
                    if 0 <= one_based < len(steps):
                        idx_match = one_based

            # 2. Deliverable link / featured_paths match
            if idx_match is None and (did_norm or dpath_norm or dtitle_clean):
                for i, s in enumerate(steps):
                    if s.get("done"):
                        continue
                    links = s.get("deliverables") or []
                    nav_paths = (
                        s.get("navigation", {}).get("featured_paths")
                        if isinstance(s.get("navigation"), dict)
                        else []
                    ) or []
                    matched_here = False
                    for lk in links:
                        if isinstance(lk, dict):
                            lk_id = str(lk.get("id") or "").replace("\\", "/").strip().lower()
                            lk_p = str(lk.get("path") or "").replace("\\", "/").strip().lower()
                            lk_t = str(lk.get("title") or "").strip().lower()
                            if (did_norm and did_norm in (lk_id, lk_p)) or (dpath_norm and dpath_norm in (lk_p, lk_id)):
                                matched_here = True
                                break
                            if dtitle_clean and lk_t and dtitle_clean == lk_t:
                                matched_here = True
                                break
                    if not matched_here and dpath_norm and isinstance(nav_paths, list):
                        for np_item in nav_paths:
                            if str(np_item or "").replace("\\", "/").strip().lower() == dpath_norm:
                                matched_here = True
                                break
                    if matched_here:
                        idx_match = i
                        break

            # 3. Wave number match (for Foreman / code_jobs wave completion)
            if idx_match is None and wave_int is not None:
                wave_pat = re.compile(rf"\bwave[-_\s]*0*{wave_int}\b", re.I)
                for i, s in enumerate(steps):
                    if s.get("done") or s.get("parked"):
                        continue
                    if s.get("wave") == wave_int or wave_pat.search(f"{s.get('id', '')} {s.get('title', '')}"):
                        idx_match = i
                        break

            # 4. Title / step fragment match against open steps
            if idx_match is None and sid_norm:
                frag = sid_norm.lower()
                for i, s in enumerate(steps):
                    if s.get("done") or s.get("parked"):
                        continue
                    if frag in str(s.get("id") or "").lower() or frag in str(s.get("title") or "").lower():
                        idx_match = i
                        break

            if idx_match is None:
                foc = _compute_focus(steps, strip_data)
                return {
                    "ok": True,
                    "completed": False,
                    "step_id": None,
                    "completed_step_id": None,
                    "completed_step_ids": [],
                    "focus": foc,
                }

            new_steps = [copy.deepcopy(s) for s in steps]
            target = new_steps[idx_match]
            already_done = bool(target.get("done") or target.get("status") == "done")
            target["status"] = "done"
            target["done"] = True
            target["parked"] = False
            if dpath_norm or did_norm:
                for lk in target.get("deliverables") or []:
                    if isinstance(lk, dict):
                        lk_id = str(lk.get("id") or "").replace("\\", "/").strip().lower()
                        lk_p = str(lk.get("path") or "").replace("\\", "/").strip().lower()
                        if (did_norm and did_norm in (lk_id, lk_p)) or (dpath_norm and dpath_norm in (lk_p, lk_id)):
                            lk["status"] = "final"

            used_ids = {str(s["id"]) for i, s in enumerate(new_steps) if i != idx_match}
            new_steps[idx_match] = _normalize_step(target, idx_match, used_ids, strict_input=False)
            matched_step = copy.deepcopy(new_steps[idx_match])

            next_id = ""
            if already_done:
                cur_focus = str((strip_data or {}).get("current_step_id") or "").strip()
                if cur_focus and any(s["id"] == cur_focus and not s.get("done") and not s.get("parked") for s in new_steps):
                    next_id = cur_focus
            if not next_id:
                for cand in new_steps[idx_match + 1 :] + new_steps[:idx_match]:
                    if not cand.get("done") and not cand.get("parked"):
                        next_id = str(cand["id"])
                        break
            if next_id and not already_done:
                for s in new_steps:
                    if s["id"] == next_id and s["status"] == "proposed":
                        s["status"] = "active"
                    elif s["id"] != next_id and s["status"] == "active":
                        s["status"] = "proposed"

            rm_out, strip_out = _persist_plan_files_locked(
                root, roadmap_data, new_steps, strip_data, preferred_focus_id=next_id
            )
            plan_resp = _build_plan_response(rm_out["steps"], strip_out, prop_data, roadmap_data=rm_out)
    except TimeoutError as exc:
        if isinstance(exc, PlanLockTimeoutError):
            raise
        raise PlanLockTimeoutError(MSG_DEPENDENCY_SLOW) from exc

    if notify_cave and matched_step is not None and not already_done:
        _notify_cave_activity(
            root,
            [{
                "kind": "step_completed",
                "step_id": matched_step["id"],
                "title": matched_step["title"],
                "wave": wave_int,
            }],
        )

    comp_id = matched_step["id"] if (matched_step and not already_done) else None
    return {
        "ok": True,
        "completed": bool(matched_step is not None and not already_done),
        "already_done": bool(matched_step is not None and already_done),
        "step_id": matched_step["id"] if matched_step else None,
        "completed_step_id": comp_id,
        "completed_step_ids": [comp_id] if comp_id else [],
        "step": matched_step,
        "focus": plan_resp.get("focus"),
        "counts": plan_resp.get("counts"),
    }


def _parse_json_arg(raw: str, *, expected_type: type) -> Any:
    try:
        val = json.loads(raw)
    except (ValueError, TypeError) as exc:
        raise PlanValidationError(MSG_DEPENDENCY_GARBAGE, detail=f"Invalid JSON argument: {exc}") from exc
    if not isinstance(val, expected_type):
        raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
    return val


def _build_cli_parser() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument(
        "--cdir",
        "--dir",
        dest="cdir",
        default=None,
        help="Effort/campaign directory (defaults to ANCHOR_EFFORT_DIR, STEWARD_CAMPAIGN_DIR, or cwd)",
    )

    parser = argparse.ArgumentParser(
        prog="steward_plan.py",
        description="Anchor Steward Atomic Plan & Deliverable Spine",
        parents=[common],
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", parents=[common], help="Read current plan state, focus step, and pending proposal")

    p_init = sub.add_parser("init", parents=[common], help="Initialize or replace plan steps (<=200)")
    p_init.add_argument("--steps-json", default="", help="JSON array of step objects or title strings")
    p_init.add_argument("--step", action="append", default=[], help="Repeatable step title")
    p_init.add_argument("--goal", default=None, help="Optional effort goal summary")

    p_add = sub.add_parser("add-step", parents=[common], help="Append or insert a step (<=200)")
    p_add.add_argument("--id", default="", help="Optional step ID")
    p_add.add_argument("--title", "--name", dest="title", default="", help="Step title")
    p_add.add_argument("--status", default="proposed", help="Initial status (proposed|active|done|parked)")
    p_add.add_argument("--done-when", default="", help="Completion criterion")
    p_add.add_argument("--goal", default="", help="Step goal")
    p_add.add_argument("--wave", default=None, help="Optional wave number")
    p_add.add_argument("--after-id", default="", help="Insert immediately after this step ID")
    p_add.add_argument("--index", type=int, default=None, help="Optional 0-based insertion index")

    p_set = sub.add_parser("set-step", parents=[common], help="Update fields or status on an existing step")
    p_set.add_argument("--id", "--step-id", dest="id", required=True, help="Target step ID")
    p_set.add_argument("--title", "--name", dest="title", default=None, help="Updated step title")
    p_set.add_argument("--status", default=None, help="Updated status (proposed|active|in_progress|waiting|blocked|done|parked)")
    p_set.add_argument("--done", choices=["true", "false"], default=None, help="Explicit done boolean")
    p_set.add_argument("--parked", choices=["true", "false"], default=None, help="Explicit parked boolean")
    p_set.add_argument("--done-when", default=None, help="Updated completion criterion")
    p_set.add_argument("--goal", default=None, help="Updated step goal")
    p_set.add_argument("--wave", default=None, help="Updated wave number")

    p_comp = sub.add_parser("complete-and-next", parents=[common], help="Mark step done and advance focus to next open step")
    p_comp.add_argument("--id", "--step-id", dest="id", default="", help="Step ID (defaults to current focused step)")

    p_next = sub.add_parser("set-next", parents=[common], help="Focus an existing step as current active step")
    p_next.add_argument("--id", "--step-id", dest="id", required=True, help="Step ID to focus")
    p_next.add_argument("--next-move", default=None, help="Optional recommended next move note")

    p_reord = sub.add_parser("reorder", parents=[common], help="Move a step up/down or supply full step ID order")
    p_reord.add_argument("--id", "--step-id", dest="id", default="", help="Step ID to move")
    p_reord.add_argument("--direction", choices=["up", "down"], default="", help="Move direction when --id is given")
    p_reord.add_argument("--order", "--order-json", dest="order", default="", help="Comma-separated or JSON array of step IDs")

    p_park = sub.add_parser("park", parents=[common], help="Park or unpark an existing step")
    p_park.add_argument("--id", "--step-id", dest="id", required=True, help="Step ID to park/unpark")
    p_park.add_argument("--unpark", action="store_true", help="Explicitly unpark instead of parking")
    p_park.add_argument("--reason", default="", help="Optional reason for parking")

    p_prop = sub.add_parser("propose", parents=[common], help="Write a pending Steward plan proposal")
    p_prop.add_argument("--id", default="", help="Optional proposal ID")
    p_prop.add_argument("--summary", default="", help="Human-readable summary of proposed plan changes")
    p_prop.add_argument("--reason", default="", help="Why this plan update is recommended")
    p_prop.add_argument("--steps-json", default="", help="JSON array of proposed full step list")
    p_prop.add_argument("--ops-json", default="", help="JSON array of mutation op objects")

    p_acc = sub.add_parser("accept-proposal", parents=[common], help="Accept pending plan proposal into roadmap.json")
    p_acc.add_argument("--id", "--proposal-id", dest="id", default="", help="Optional proposal ID check")

    p_dis = sub.add_parser("dismiss-proposal", parents=[common], help="Dismiss pending plan proposal")
    p_dis.add_argument("--id", "--proposal-id", dest="id", default="", help="Optional proposal ID check")

    p_reg = sub.add_parser("register-deliverable", parents=[common], help="Link a deliverable to a plan step and register it")
    p_reg.add_argument("--step-id", "--id", dest="step_id", default="", help="Step ID to link (defaults to focused step)")
    p_reg.add_argument("--deliverable-id", default="", help="Optional deliverable identifier")
    p_reg.add_argument("--title", "--what", dest="title", default="", help="Human-readable deliverable title")
    p_reg.add_argument("--path", default="", help="Relative path inside campaign directory")
    p_reg.add_argument("--status", default="for_review", help="Deliverable status (for_review|in_progress|final)")

    p_cur = sub.add_parser("curate-deliverables", parents=[common], help="Update Steward hierarchical Final Deliverables summary, groups, supersession & recent instruction presentation")
    p_cur.add_argument("--headline", default=None, help="Concise executive headline for Final Deliverables hierarchy")
    p_cur.add_argument("--summary", default=None, help="Steward hierarchical summary narrative for Final Deliverables")
    p_cur.add_argument("--groups-json", default="", help='JSON array of Final groups: [{"title":"...","summary":"...","paths":["..."]}]')
    p_cur.add_argument("--supersedes-json", default="", help='JSON object mapping winning path -> [superseded paths]')
    p_cur.add_argument("--recent-paths", default="", help="Comma-separated primary deliverable paths to present for the latest instruction")
    p_cur.add_argument("--instruction", default="", help="Optional user instruction summary for --recent-paths")

    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    # Allow `--cdir` / `--dir` either before or after the subcommand seamlessly
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    extracted_cdir: str | None = None
    cleaned_argv: list[str] = []
    i = 0
    while i < len(raw_argv):
        tok = raw_argv[i]
        if tok in ("--cdir", "--dir") and i + 1 < len(raw_argv):
            extracted_cdir = raw_argv[i + 1]
            i += 2
            continue
        if tok.startswith("--cdir="):
            extracted_cdir = tok.split("=", 1)[1]
            i += 1
            continue
        if tok.startswith("--dir="):
            extracted_cdir = tok.split("=", 1)[1]
            i += 1
            continue
        cleaned_argv.append(tok)
        i += 1

    parser = _build_cli_parser()
    try:
        args = parser.parse_args(cleaned_argv)
    except SystemExit as exc:
        code = int(exc.code) if isinstance(exc.code, int) else 2
        return code

    cdir = (
        extracted_cdir
        if extracted_cdir is not None
        else (
            args.cdir
            if args.cdir is not None
            else (os.environ.get("ANCHOR_EFFORT_DIR") or os.environ.get("STEWARD_CAMPAIGN_DIR") or os.getcwd())
        )
    )

    try:
        cmd = args.cmd
        if cmd == "status":
            res = read_plan_state(cdir)
        elif cmd == "init":
            if args.steps_json:
                steps_list = _parse_json_arg(args.steps_json, expected_type=list)
            elif args.step:
                steps_list = list(args.step)
            else:
                steps_list = []
            payload: dict[str, Any] = {"steps": steps_list}
            if args.goal is not None:
                payload["goal"] = args.goal
            res = mutate_plan_state(cdir, "init", payload)
        elif cmd == "add-step":
            payload = {
                "title": args.title,
                "status": args.status,
                "done_when": args.done_when,
                "goal": args.goal,
            }
            if args.id:
                payload["id"] = args.id
            if args.wave is not None:
                payload["wave"] = args.wave
            if args.after_id:
                payload["after_id"] = args.after_id
            if args.index is not None:
                payload["index"] = args.index
            res = mutate_plan_state(cdir, "add-step", payload)
        elif cmd == "set-step":
            payload = {"id": args.id}
            if args.title is not None:
                payload["title"] = args.title
            if args.status is not None:
                payload["status"] = args.status
            if args.done is not None:
                payload["done"] = args.done == "true"
            if args.parked is not None:
                payload["parked"] = args.parked == "true"
            if args.done_when is not None:
                payload["done_when"] = args.done_when
            if args.goal is not None:
                payload["goal"] = args.goal
            if args.wave is not None:
                payload["wave"] = args.wave
            res = mutate_plan_state(cdir, "set-step", payload)
        elif cmd == "complete-and-next":
            res = mutate_plan_state(cdir, "complete-and-next", {"id": args.id})
        elif cmd == "set-next":
            payload_next: dict[str, Any] = {"id": args.id}
            if args.next_move is not None:
                payload_next["next_move"] = args.next_move
            res = mutate_plan_state(cdir, "set-next", payload_next)
        elif cmd == "reorder":
            payload = {}
            if args.order:
                raw_o = args.order.strip()
                if raw_o.startswith("["):
                    payload["order"] = _parse_json_arg(raw_o, expected_type=list)
                else:
                    payload["order"] = [x.strip() for x in raw_o.split(",") if x.strip()]
            else:
                payload["id"] = args.id
                payload["direction"] = args.direction
            res = mutate_plan_state(cdir, "reorder", payload)
        elif cmd == "park":
            payload = {"id": args.id, "parked": not bool(args.unpark)}
            if args.reason:
                payload["reason"] = args.reason
            res = mutate_plan_state(cdir, "park", payload)
        elif cmd == "propose":
            payload = {
                "summary": args.summary,
                "reason": args.reason,
            }
            if args.id:
                payload["id"] = args.id
            if args.steps_json:
                payload["proposed_steps"] = _parse_json_arg(args.steps_json, expected_type=list)
            if args.ops_json:
                payload["ops"] = _parse_json_arg(args.ops_json, expected_type=list)
            res = mutate_plan_state(cdir, "propose", payload)
        elif cmd == "accept-proposal":
            res = mutate_plan_state(cdir, "accept-proposal", {"id": args.id} if args.id else {})
        elif cmd == "dismiss-proposal":
            res = mutate_plan_state(cdir, "dismiss-proposal", {"id": args.id} if args.id else {})
        elif cmd == "register-deliverable":
            res = mutate_plan_state(
                cdir,
                "register-deliverable",
                {
                    "step_id": args.step_id,
                    "deliverable_id": args.deliverable_id,
                    "title": args.title,
                    "path": args.path,
                    "status": args.status,
                },
            )
        elif cmd == "curate-deliverables":
            from steward_cockpit import deliverable_shelves as _ds
            root = _resolve_cdir(cdir)
            cur_body: dict[str, Any] = {}
            if args.headline is not None:
                cur_body["headline"] = args.headline
            if args.summary is not None:
                cur_body["summary"] = args.summary
            if args.groups_json:
                cur_body["final_groups"] = _parse_json_arg(args.groups_json, expected_type=list)
            if args.supersedes_json:
                cur_body["supersedes"] = _parse_json_arg(args.supersedes_json, expected_type=dict)
            if args.recent_paths:
                cur_body["recent_paths"] = [p.strip() for p in args.recent_paths.split(",") if p.strip()]
            if args.instruction:
                cur_body["instruction"] = args.instruction
            res = _ds.update_curation(root, cur_body)
            _invalidate_in_process_caches(root)
        else:
            raise PlanValidationError(MSG_DEPENDENCY_GARBAGE)
    except PlanValidationError as exc:
        print(json.dumps(exc.to_dict(), indent=2, ensure_ascii=False))
        return 2
    except PlanError as exc:
        print(json.dumps(exc.to_dict(), indent=2, ensure_ascii=False))
        return 1

    print(json.dumps(res, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
