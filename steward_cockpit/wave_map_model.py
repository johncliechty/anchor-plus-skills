"""Pure derivation & atomic state persistence for the AI Cockpit Simplified Wave Map (stdlib-only)."""
from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import time
from typing import Any
import paths

WAVE_STATE_REL = ".ecgberht/wave-state.json"
WAVE_STATE_SCHEMA = "anchor-wave-state-v1"
MIN_ROUND, MAX_ROUND = 1, 99
ALLOWED_ACTIONS = frozenset({"iterate", "advance"})

class WaveStateValidationError(ValueError):
    """Raised when a wave-state mutation violates round or action bounds (HTTP 400)."""

def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

def _human_ago(ts_val: Any, now_epoch: float | None = None) -> str:
    now = float(now_epoch if now_epoch is not None else time.time())
    if isinstance(ts_val, (int, float)) and not isinstance(ts_val, bool) and ts_val > 0:
        secs = max(0.0, now - float(ts_val))
    elif isinstance(ts_val, str) and ts_val.strip():
        s = ts_val.strip()
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
            return s
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
            secs = max(0.0, now - (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp())
        except ValueError:
            return s[:16]
    else:
        return "Recently"
    if secs < 90:
        return "Just now"
    return f"{int(secs // 60)}m ago" if secs < 3600 else (f"{int(secs // 3600)}h ago" if secs < 86400 else f"{int(secs // 86400)}d ago")

def _one_line(text: Any, limit: int = 120) -> str:
    flat = re.sub(r"\s+", " ", str(text or "").replace("**", "")).strip()
    return flat if len(flat) <= limit else ((flat[: limit - 1].rsplit(" ", 1)[0] or flat[: limit - 1]) + "\u2026")

def validate_step_id(raw: Any) -> str:
    if not isinstance(raw, str):
        raise WaveStateValidationError("step_id must be a non-empty string")
    s = raw.strip()
    if not s or len(s) > 120 or "/" in s or "\\" in s or "\x00" in s or ".." in s:
        raise WaveStateValidationError("invalid step_id")
    return s

def validate_round(raw: Any) -> int:
    if isinstance(raw, bool) or raw is None:
        raise WaveStateValidationError("round must be an integer between 1 and 99")
    if isinstance(raw, int):
        n = raw
    elif isinstance(raw, str) and re.fullmatch(r"[+-]?\d+", raw.strip()):
        n = int(raw.strip())
    else:
        raise WaveStateValidationError("round must be an integer between 1 and 99")
    if n < MIN_ROUND or n > MAX_ROUND:
        raise WaveStateValidationError(f"round {n} out of bounds (must be {MIN_ROUND}..{MAX_ROUND})")
    return n

def validate_recommended_action(raw: Any) -> str | None:
    if raw is None or raw == "":
        return None
    if not isinstance(raw, str) or raw.strip().lower() not in ALLOWED_ACTIONS:
        raise WaveStateValidationError("recommended_action must be 'iterate', 'advance', or null")
    return raw.strip().lower()

def read_wave_state(cdir: str | Path) -> dict[str, Any]:
    fp = Path(cdir) / WAVE_STATE_REL
    base: dict[str, Any] = {"schema": WAVE_STATE_SCHEMA, "waves": {}, "recent_moves": []}
    if not fp.is_file():
        return base
    try:
        parsed = json.loads(fp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return base
    if not isinstance(parsed, dict):
        return base
    waves_out: dict[str, dict[str, Any]] = {}
    for k, v in (parsed.get("waves") or {}).items() if isinstance(parsed.get("waves"), dict) else ():
        if not isinstance(k, str) or not isinstance(v, dict):
            continue
        try:
            r = validate_round(v.get("round", 1))
        except WaveStateValidationError:
            r = 1
        act = v.get("recommended_action")
        act_norm = act.strip().lower() if isinstance(act, str) and act.strip().lower() in ALLOWED_ACTIONS else None
        waves_out[k] = {"round": r, "recommended_action": act_norm, "recommendation_note": _one_line(v.get("recommendation_note") or "", 220), "updated_at": str(v.get("updated_at") or "")}
    moves = [m for m in (parsed.get("recent_moves") or []) if isinstance(m, dict)][:12]
    return {"schema": WAVE_STATE_SCHEMA, "waves": waves_out, "recent_moves": moves}

def write_wave_state(cdir: str | Path, state_doc: dict[str, Any]) -> dict[str, Any]:
    fp = Path(cdir) / WAVE_STATE_REL
    payload = {"schema": WAVE_STATE_SCHEMA, "updated_at": _now_iso(), "waves": dict((state_doc or {}).get("waves") or {}), "recent_moves": list((state_doc or {}).get("recent_moves") or [])[:12]}
    with paths.WRITE_LOCK:
        fp.parent.mkdir(parents=True, exist_ok=True)
        paths.atomic_write_text(fp, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return payload

def _clean_wave_title(step: dict[str, Any], wave_num: int) -> str:
    raw = str((step.get("navigation") or {}).get("label") or step.get("title") or step.get("name") or f"Wave {wave_num}")
    clean = re.sub(rf"^(?:wave|step)\s*{wave_num}\s*[:\u00b7\u2014\u2013\-]\s*", "", raw.replace("**", "").strip(), flags=re.I).strip()
    return clean or f"Wave {wave_num}"

def _step_is_done(step: dict[str, Any]) -> bool:
    ref = step.get("refinement")
    if isinstance(ref, dict):
        if ref.get("phase") == "done":
            return True
        if ref.get("phase") in ("awaiting_review", "blocked"):
            return False
    return bool(step.get("done") is True or step.get("status") == "done")

def derive_wave_map(map_data: dict[str, Any] | None, wave_state: dict[str, Any] | None = None, *, deliverables_items: list[dict[str, Any]] | None = None, history_turns: list[dict[str, Any]] | None = None, now_epoch: float | None = None) -> dict[str, Any]:
    m = map_data if isinstance(map_data, dict) else {}
    ws_waves = ((wave_state or {}).get("waves") or {}) if isinstance(wave_state, dict) else {}
    ws_moves = ((wave_state or {}).get("recent_moves") or []) if isinstance(wave_state, dict) else []
    active_pool = [s for s in (m.get("steps") or []) if isinstance(s, dict) and not (s.get("parked") is True or s.get("status") == "parked")]
    total_waves, done_waves = len(active_pool), sum(1 for s in active_pool if _step_is_done(s))
    hb = m.get("heartbeat") if isinstance(m.get("heartbeat"), dict) else {}
    focus_id = str(m.get("now_step_id") or hb.get("current_step_id") or "").strip()

    cur_idx = next((i for i, s in enumerate(active_pool) if focus_id and str(s.get("id") or "") == focus_id and not _step_is_done(s)), None)
    if cur_idx is None:
        cur_idx = next((i for i, s in enumerate(active_pool) if not _step_is_done(s) and str(s.get("status") or "") in ("active", "in_progress", "waiting", "blocked")), None)
    if cur_idx is None:
        cur_idx = next((i for i, s in enumerate(active_pool) if not _step_is_done(s)), None)

    current_wave: dict[str, Any] | None = None
    coming_next: list[dict[str, Any]] = []
    if cur_idx is not None:
        cur_step, w_num = active_pool[cur_idx], cur_idx + 1
        sid = str(cur_step.get("id") or f"wave-{w_num}")
        entry = ws_waves.get(sid) if isinstance(ws_waves.get(sid), dict) else {}
        ref = cur_step.get("refinement") if isinstance(cur_step.get("refinement"), dict) else {}
        fallback_r = ref.get("display_round") or ref.get("round") or 1
        try:
            round_num = validate_round(entry.get("round") if entry.get("round") is not None else max(1, int(fallback_r)))
        except (WaveStateValidationError, TypeError, ValueError):
            round_num = 1
        rec_action = entry.get("recommended_action") if entry.get("recommended_action") in ALLOWED_ACTIONS else None
        rec_note, hb_rec = _one_line(entry.get("recommendation_note") or "", 200), _one_line(hb.get("next_recommended") or "", 200)
        if rec_action == "iterate":
            rec_text = rec_note or f"\u2605 Recommended: Iterate Round {min(MAX_ROUND, round_num + 1)} on Wave {w_num}."
        elif rec_action == "advance":
            rec_text = rec_note or f"\u2605 Recommended: Mark Wave {w_num} Done and advance to the next wave."
        else:
            rec_text = rec_note or hb_rec or ""
        next_round = min(MAX_ROUND, round_num + 1)
        current_wave = {
            "step_id": sid, "wave_num": w_num, "total_waves": total_waves, "round": round_num, "can_iterate": round_num < MAX_ROUND,
            "badge": f"WAVE {w_num} \u00b7 ACTIVE", "iter_badge": f"\u21bb Iterating \u00b7 Round {round_num}",
            "progress_badge": f"Wave {w_num} of {total_waves} \u00b7 Round {round_num}", "title": _clean_wave_title(cur_step, w_num),
            "goal": _one_line(cur_step.get("goal") or cur_step.get("done_when") or hb.get("active_effort") or "", 200),
            "recommended_action": rec_action, "recommendation_text": rec_text,
            "iterate_label": f"\u21bb Iterate Wave {w_num} (Round {next_round})", "done_label": f"\u2713 Wave {w_num} Done \u2192 Next",
        }
        for q_idx, (orig_i, up_s) in enumerate((i, s) for i, s in enumerate(active_pool) if i != cur_idx and not _step_is_done(s)):
            up_num = orig_i + 1
            coming_next.append({"step_id": str(up_s.get("id") or f"wave-{up_num}"), "wave_num": up_num, "title": _clean_wave_title(up_s, up_num), "note": _one_line(up_s.get("goal") or up_s.get("done_when") or "Queued wave", 140), "next_up": q_idx == 0, "badge": "\u2605 Next Up" if q_idx == 0 else ""})

    history: list[dict[str, Any]] = []
    seen_texts: set[str] = set()
    def _push_hist(ago: str, txt: str, kind: str) -> None:
        clean_t = _one_line(txt, 140)
        if clean_t and clean_t.lower() not in seen_texts and len(history) < 3:
            seen_texts.add(clean_t.lower())
            history.append({"ago": ago or "Recently", "text": clean_t, "kind": kind})

    for mv in ws_moves:
        _push_hist(_human_ago(mv.get("epoch_s") or mv.get("ts"), now_epoch), mv.get("text") or "", str(mv.get("kind") or "wave"))
    for w_n, ds in reversed([(i + 1, s) for i, s in enumerate(active_pool) if _step_is_done(s)]):
        ds_sub = _one_line(ds.get("goal") or ds.get("done_when") or "", 80)
        _push_hist("Done", f"Completed Wave {w_n} \u2014 {_clean_wave_title(ds, w_n)}" + (f" ({ds_sub})" if ds_sub else ""), "step_done")
    for dit in (deliverables_items or [])[:4]:
        if isinstance(dit, dict) and not dit.get("auto"):
            lbl = _one_line(dit.get("human_title") or dit.get("what") or dit.get("path") or "", 90)
            if lbl:
                _push_hist(_human_ago(dit.get("date"), now_epoch), f"Delivered {lbl}", "deliverable")
    for turn in reversed(history_turns or []):
        if isinstance(turn, dict) and turn.get("role") == "steward" and turn.get("text"):
            raw_t = str(turn.get("text") or "").strip()
            if raw_t and not raw_t.startswith(("**Anchor**", "Anchor \u00b7")):
                _push_hist(_human_ago(turn.get("at"), now_epoch), raw_t.splitlines()[0], "turn")

    return {"ok": True, "steps_flat": True, "counts": {"done": done_waves, "total": total_waves}, "recent_history": history[:3], "current_wave": current_wave, "coming_next": coming_next, "all_done": bool(total_waves > 0 and current_wave is None)}

def build_wave_map_payload(cdir: str | Path) -> dict[str, Any]:
    from steward_cockpit import steward_campaign as campaign
    root = Path(cdir)
    m = campaign.read_map(str(root), include_plan_history=False, include_overview=False)
    if m.get("failure_state") == "backing-store-unreadable":
        return {"ok": False, "failure_state": "backing-store-unreadable", "error": m.get("roadmap_error") or "unreadable"}
    ws = read_wave_state(root)
    derived = derive_wave_map(m, ws, deliverables_items=(campaign._read_deliverables(str(root)) or {}).get("items") or [], history_turns=(campaign.read_history(str(root), tail=8) or {}).get("turns") or [])
    derived["wave_state"] = ws.get("waves") or {}
    derived["folder_path"] = str(root.resolve())
    derived["goal_brief"] = str(m.get("goal_brief") or "").strip()
    return derived

def mutate_wave_state(cdir: str | Path, body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise WaveStateValidationError("request body must be a JSON object")
    op = str(body.get("op") or body.get("action") or "set").strip().lower()
    if op not in ("set", "update", "iterate", "done_next", "advance"):
        raise WaveStateValidationError(f"unsupported wave-state op: {op}")
    from steward_cockpit import steward_campaign as campaign
    root = Path(cdir)
    cur_wave = build_wave_map_payload(root).get("current_wave") or {}
    raw_sid = body.get("step_id") if body.get("step_id") is not None else body.get("id")
    if raw_sid is None and op in ("iterate", "done_next", "advance") and cur_wave.get("step_id"):
        raw_sid = cur_wave["step_id"]
    sid = validate_step_id(raw_sid)
    w_label = f"Wave {cur_wave['wave_num']} ({cur_wave['title']})" if cur_wave.get("step_id") == sid else sid
    with paths.WRITE_LOCK:
        doc = read_wave_state(root)
        waves, moves = doc.setdefault("waves", {}), doc.setdefault("recent_moves", [])
        prev, now_s, now_ep = dict(waves.get(sid) or {}), _now_iso(), time.time()
        if op == "iterate":
            base_r = int(prev.get("round") or cur_wave.get("round") or 1)
            next_r = validate_round(body["round"]) if body.get("round") is not None else validate_round(base_r + 1)
            rec_act = validate_recommended_action(body["recommended_action"]) if "recommended_action" in body else prev.get("recommended_action")
            note = _one_line(body.get("recommendation_note") if "recommendation_note" in body else prev.get("recommendation_note") or "", 220)
            waves[sid] = {"round": next_r, "recommended_action": rec_act, "recommendation_note": note, "updated_at": now_s}
            moves.insert(0, {"ts": now_s, "epoch_s": now_ep, "step_id": sid, "kind": "iterate", "text": f"{w_label} \u00b7 Iterated to Round {next_r}."})
            write_wave_state(root, doc)
        elif op in ("done_next", "advance"):
            from tools import steward_plan
            done_r = int(prev.get("round") or cur_wave.get("round") or 1)
            plan_res = steward_plan.mutate_plan_state(root, "complete_and_next", {"id": sid})
            nxt_id = str(((plan_res or {}).get("focus") or {}).get("step_id") or "").strip()
            if nxt_id and nxt_id != sid and nxt_id not in waves:
                waves[nxt_id] = {"round": 1, "recommended_action": None, "recommendation_note": "", "updated_at": now_s}
            moves.insert(0, {"ts": now_s, "epoch_s": now_ep, "step_id": sid, "kind": "wave_done", "text": f"Completed {w_label} after Round {done_r}."})
            write_wave_state(root, doc)
            campaign._JSON_FILE_CACHE.clear()
        else:
            r_val = validate_round(body["round"]) if "round" in body else validate_round(prev.get("round", 1))
            rec_act = validate_recommended_action(body["recommended_action"]) if "recommended_action" in body else prev.get("recommended_action")
            note = _one_line(body.get("recommendation_note") if "recommendation_note" in body else prev.get("recommendation_note") or "", 220)
            waves[sid] = {"round": r_val, "recommended_action": rec_act, "recommendation_note": note, "updated_at": now_s}
            write_wave_state(root, doc)
    out = build_wave_map_payload(root)
    out["step_id"], out["wave_entry"] = sid, (out.get("wave_state") or {}).get(sid)
    return out
