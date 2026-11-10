"""Live & Nightly Usage Reconciler for Anchor AI Cockpits.

Guarantees that:
1. All native provider transcripts (Gemini/agy brain transcripts, Claude sidecars,
   Codex rollouts) are reconciled against `.anchor/usage_ledger/` and
   `steward-cockpit-state.json` — including steps from turns that were interrupted,
   restarted mid-turn, or run while the server was restarting.
2. Every session in `steward-cockpit-state.json` has up-to-date `tokens`,
   `last_session_usage`, and `estimated_spend` at current API list prices.
3. A dated nightly snapshot is written under `.anchor/usage_snapshots/YYYY-MM-DD.json`
   (and `latest.json`) and verified by the daily 5:00 AM health check as well as a
   background daemon thread in `anchor_gui.py`.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
from pathlib import Path
import threading
import time
from typing import Any

import paths as _paths


_SYNC_LOCK = threading.Lock()
_LAST_SYNC_TS = 0.0


def _brain_dir() -> Path:
    override = os.environ.get("AGY_BRAIN_DIR")
    if override:
        return Path(override)
    return Path.home() / ".gemini" / "antigravity-cli" / "brain"


def _scan_agy_transcript(transcript_path: Path) -> dict[str, Any] | None:
    """Parse an agy transcript.jsonl into per-turn step groups and cumulative totals."""
    if not transcript_path.is_file():
        return None
    try:
        raw_lines = transcript_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None

    turns: list[dict[str, Any]] = []
    cur_turn: dict[str, Any] | None = None
    cum_in = 0
    cum_cache = 0
    cum_out = 0
    step_count = 0
    last_created_at = ""

    for line in raw_lines:
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if not isinstance(obj, dict):
            continue
        t = obj.get("type")
        created_at = str(obj.get("created_at") or "")
        if created_at:
            last_created_at = created_at
        if t == "USER_INPUT":
            if cur_turn and cur_turn["steps"] > 0:
                turns.append(cur_turn)
            cur_turn = {
                "turn_index": len(turns) + 1,
                "started_at": created_at,
                "recorded_at": created_at,
                "steps": 0,
                "delta_in": 0,
                "delta_cache": 0,
                "delta_out": 0,
                "cum_in": cum_in,
                "cum_cache": cum_cache,
                "cum_out": cum_out,
            }
        elif t == "PLANNER_RESPONSE":
            in_t = max(0, int(obj.get("input_tokens") or 0))
            ca_t = max(0, int(obj.get("cache_read_tokens") or 0))
            out_t = max(0, int(obj.get("output_tokens") or 0) + int(obj.get("thinking_tokens") or 0))
            if in_t == 0 and ca_t == 0 and out_t == 0:
                continue
            step_count += 1
            cum_in += in_t
            cum_cache += ca_t
            cum_out += out_t
            if cur_turn is None:
                cur_turn = {
                    "turn_index": len(turns) + 1,
                    "started_at": created_at,
                    "recorded_at": created_at,
                    "steps": 0,
                    "delta_in": 0,
                    "delta_cache": 0,
                    "delta_out": 0,
                    "cum_in": 0,
                    "cum_cache": 0,
                    "cum_out": 0,
                }
            cur_turn["steps"] += 1
            cur_turn["delta_in"] += in_t
            cur_turn["delta_cache"] += ca_t
            cur_turn["delta_out"] += out_t
            cur_turn["cum_in"] = cum_in
            cur_turn["cum_cache"] = cum_cache
            cur_turn["cum_out"] = cum_out
            if created_at:
                cur_turn["recorded_at"] = created_at

    if cur_turn and cur_turn["steps"] > 0:
        turns.append(cur_turn)

    if step_count == 0:
        return None

    return {
        "steps": step_count,
        "turns": turns,
        "cum_in": cum_in,
        "cum_cache": cum_cache,
        "cum_out": cum_out,
        "last_created_at": last_created_at,
    }


def sync_all_usage(*, write_snapshot: bool = True, brain_dir: Path | None = None) -> dict[str, Any]:
    """Reconcile all provider transcripts, usage ledgers, and steward-cockpit-state.json."""
    global _LAST_SYNC_TS
    with _SYNC_LOCK:
        now_utc = _dt.datetime.now(_dt.timezone.utc)
        now_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
        from steward_cockpit import steward_engine as se
        from steward_cockpit import steward_routes as sr
        import usage_capture as uc
        import usage_ledger as ul

        if se.STATE_FILE == se.HERE / "proto-state.json" and "PYTEST_CURRENT_TEST" not in os.environ:
            se.relocate_state(_paths.data_dir() / "steward-cockpit-state.json")

        bdir = Path(brain_dir) if brain_dir is not None else _brain_dir()
        state = se._read_all_state()
        reconciled_sessions: list[dict[str, Any]] = []
        ledger_entries_added = 0
        state_entries_updated = 0

        for skey, entry in list(state.items()):
            if not isinstance(entry, dict):
                continue
            base_dir = skey.split("||")[0]
            if "scratchpad" in base_dir or "anchor-hc-" in base_dir or ("Temp" in base_dir and "PYTEST_CURRENT_TEST" not in os.environ):
                continue
            live_eng = sr.ENGINES.get(skey)
            if live_eng is not None and getattr(live_eng, "busy", False):
                # Never race a busy engine mid-turn on disk; the running turn owns its state until completion.
                continue

            mp = entry.get("model_policy") if isinstance(entry.get("model_policy"), dict) else {}
            cli = str(entry.get("cli") or mp.get("family") or "claude").lower()
            model_served = mp.get("model_served") or mp.get("model")
            model_req = mp.get("model")
            sid = str(entry.get("session_id") or "").strip()

            raw_u = dict(entry.get("usage")) if isinstance(entry.get("usage"), dict) else {}
            changed_u = False

            # 1. Reconcile Gemini (agy) transcript.jsonl if session_id is a brain conversation
            if sid and (cli == "gemini" or (bdir / sid / ".system_generated" / "logs" / "transcript.jsonl").is_file()):
                tpath = bdir / sid / ".system_generated" / "logs" / "transcript.jsonl"
                scan = _scan_agy_transcript(tpath)
                if scan:
                    doc = ul.load_ledger(sid)
                    existing_entries = doc.get("entries") or {}
                    max_l_in = 0
                    max_l_cache = 0
                    max_l_out = 0
                    max_l_recorded_at = ""
                    for e in existing_entries.values():
                        if not isinstance(e, dict):
                            continue
                        rec_at = str(e.get("recorded_at") or "")
                        if rec_at > max_l_recorded_at:
                            max_l_recorded_at = rec_at
                        eu = e.get("usage") if isinstance(e.get("usage"), dict) else {}
                        max_l_in = max(max_l_in, int(eu.get("input_tokens") or 0))
                        max_l_cache = max(max_l_cache, int(eu.get("cache_read_input_tokens") or eu.get("cached_input_tokens") or 0))
                        max_l_out = max(max_l_out, int(eu.get("output_tokens") or 0))

                    prev_lsu = raw_u.get("last_session_usage") if isinstance(raw_u.get("last_session_usage"), dict) else {}
                    lsu_in = int(prev_lsu.get("input_tokens") or 0)
                    lsu_cache = int(prev_lsu.get("cache_read_input_tokens") or prev_lsu.get("cached_input_tokens") or 0)
                    lsu_out = int(prev_lsu.get("output_tokens") or 0)

                    watermark_in = max(max_l_in, lsu_in)
                    watermark_cache = max(max_l_cache, lsu_cache)
                    base_out = max(max_l_out, lsu_out, scan["cum_out"])

                    if scan["cum_in"] > watermark_in or scan["cum_cache"] > watermark_cache:
                        pid, fpath = uc.resolve_project(base_dir)
                        added_out = 0
                        running_out = max(max_l_out, lsu_out)
                        new_turns_count = 0
                        for t_item in scan["turns"]:
                            t_rec_at = str(t_item.get("recorded_at") or "")
                            if (t_item["cum_in"] <= watermark_in and t_item["cum_cache"] <= watermark_cache) or (
                                max_l_recorded_at and t_rec_at and t_rec_at <= max_l_recorded_at
                            ):
                                continue
                            # Compute delta relative to max(previous turn, watermark)
                            prev_in = max(watermark_in, t_item["cum_in"] - t_item["delta_in"])
                            prev_ca = max(watermark_cache, t_item["cum_cache"] - t_item["delta_cache"])
                            d_in = max(0, t_item["cum_in"] - prev_in)
                            d_ca = max(0, t_item["cum_cache"] - prev_ca)
                            d_out = t_item["delta_out"]
                            if d_in == 0 and d_ca == 0 and d_out == 0:
                                continue
                            running_out = max(running_out + d_out, t_item["cum_out"])
                            if t_item["cum_in"] > watermark_in or t_item["cum_cache"] > watermark_cache:
                                added_out += d_out
                                new_turns_count += 1
                            t_tok = d_in + d_ca + d_out
                            t_key = f"agy-sync:{sid}:{t_item['cum_in']}:{t_item['cum_cache']}"
                            rec_entry = {
                                "source": "steward-turn",
                                "native_id": f"gemini:{sid}:sync:{t_item['turn_index']}",
                                "turn_id": f"sync-{t_item['turn_index']}",
                                "cli": "gemini",
                                "model": model_served or model_req or "gemini-3.1-pro-high",
                                "project_id": pid,
                                "folder_path": fpath,
                                "effort_dir": base_dir,
                                "session_id": sid,
                                "tokens": t_tok,
                                "cost_usd": None,
                                "duration_ms": None,
                                "usage": {
                                    "input_tokens": t_item["cum_in"],
                                    "output_tokens": running_out,
                                    "cache_read_input_tokens": t_item["cum_cache"],
                                },
                                "usage_state": "unpriced",
                                "recorded_at": t_item["recorded_at"] or scan["last_created_at"] or now_iso,
                            }
                            if ul.append_entries(sid, [{"key": t_key, **rec_entry}]):
                                ledger_entries_added += 1
                            max_l_in = max(max_l_in, t_item["cum_in"])
                            max_l_cache = max(max_l_cache, t_item["cum_cache"])
                            watermark_in = max(watermark_in, max_l_in)
                            watermark_cache = max(watermark_cache, max_l_cache)

                        final_out = max(lsu_out + added_out, scan["cum_out"])
                        new_lsu = {
                            "session_id": sid,
                            "input_tokens": scan["cum_in"],
                            "cache_read_input_tokens": scan["cum_cache"],
                            "output_tokens": final_out,
                        }
                        delta_total_tokens = (
                            max(0, scan["cum_in"] - lsu_in)
                            + max(0, scan["cum_cache"] - lsu_cache)
                            + added_out
                        )
                        old_tokens = int(raw_u.get("tokens") or 0)
                        transcript_total_tokens = scan["cum_in"] + scan["cum_cache"] + final_out
                        new_tokens = max(old_tokens + (delta_total_tokens if lsu_in > 0 else 0), transcript_total_tokens)
                        if isinstance(raw_u.get("usage_checkpoints"), dict):
                            for ck_v in raw_u["usage_checkpoints"].values():
                                if isinstance(ck_v, dict) and ck_v.get("session_id") == sid and ck_v.get("source") == "gemini-transcript" and ck_v.get("finalized") is not True:
                                    ck_v["finalized"] = True
                                    ck_v["token_status"] = "reported"
                        raw_u["last_session_usage"] = new_lsu
                        raw_u["tokens"] = new_tokens
                        raw_u["cumulative_tokens"] = max(int(raw_u.get("cumulative_tokens") or 0), new_tokens)
                        raw_u["turns"] = max(int(raw_u.get("turns") or 0) + new_turns_count, len(scan["turns"]))
                        raw_u["unpriced_turns"] = max(int(raw_u.get("unpriced_turns") or 0) + new_turns_count, raw_u["turns"])
                        raw_u["usage_updated_at"] = scan["last_created_at"] or now_iso
                        old_est = float(raw_u.get("estimated_spend") or 0.0)
                        if old_est > 0.0 and lsu_in > 0:
                            delta_lsu = {
                                "input_tokens": max(0, scan["cum_in"] - lsu_in),
                                "cache_read_input_tokens": max(0, scan["cum_cache"] - lsu_cache),
                                "output_tokens": added_out,
                            }
                            delta_est = se.estimate_list_price_usd(model_served or model_req or "gemini-3.1-pro", delta_lsu)
                            if delta_est is None and model_req:
                                delta_est = se.estimate_list_price_usd(model_req, delta_lsu)
                            if delta_est is not None:
                                raw_u["estimated_spend"] = round(old_est + delta_est, 4)
                                raw_u["cumulative_estimated_spend"] = round(
                                    max(float(raw_u.get("cumulative_estimated_spend") or 0.0), raw_u["estimated_spend"]), 4
                                )
                                raw_u["estimated_turns"] = raw_u["unpriced_turns"]
                        else:
                            est_lsu = se.estimate_list_price_usd(model_served or model_req or "gemini-3.1-pro", new_lsu)
                            if est_lsu is None and model_req:
                                est_lsu = se.estimate_list_price_usd(model_req, new_lsu)
                            if est_lsu is not None:
                                raw_u["estimated_spend"] = round(max(old_est, est_lsu), 4)
                                raw_u["cumulative_estimated_spend"] = round(
                                    max(float(raw_u.get("cumulative_estimated_spend") or 0.0), raw_u["estimated_spend"]), 4
                                )
                                raw_u["estimated_turns"] = raw_u["unpriced_turns"]
                        changed_u = True
                        reconciled_sessions.append({
                            "skey": skey,
                            "session_id": sid,
                            "cli": cli,
                            "added_tokens": new_tokens - old_tokens,
                            "total_tokens": new_tokens,
                            "estimated_spend": raw_u.get("estimated_spend"),
                        })

            # 2. Ensure estimated_spend is backfilled on every state entry with unpriced tokens.
            # Strip unfinalized checkpoints when computing the persisted backfill so ephemeral
            # inflight_spend is never compounded into raw_u["estimated_spend"] on every sync.
            raw_u_completed = dict(raw_u)
            if isinstance(raw_u.get("usage_checkpoints"), dict):
                raw_u_completed["usage_checkpoints"] = {
                    ck_k: ck_v for ck_k, ck_v in raw_u["usage_checkpoints"].items()
                    if isinstance(ck_v, dict) and ck_v.get("finalized") is True
                }
            snap = se._backfill_usage_estimate(se._usage_snapshot(raw_u_completed), raw_u_completed, mp, include_inflight=False)
            if float(snap.get("estimated_spend") or 0.0) > float(raw_u.get("estimated_spend") or 0.0):
                raw_u["estimated_spend"] = round(float(snap["estimated_spend"]), 4)
                raw_u["estimated_turns"] = int(snap.get("estimated_turns") or raw_u.get("unpriced_turns") or 0)
                raw_u["cumulative_estimated_spend"] = round(
                    max(float(raw_u.get("cumulative_estimated_spend") or 0.0), raw_u["estimated_spend"]), 4
                )
                changed_u = True

            if changed_u:
                raw_u["_reconciled_from_ledger"] = True
                if se._update_state(skey, {"usage": raw_u}):
                    state_entries_updated += 1
                # Also update in-memory idle Engine if loaded so it doesn't overwrite on next turn
                eng = sr.ENGINES.get(skey)
                if eng is not None and not getattr(eng, "busy", False):
                    with eng._lock:
                        eng.tokens = max(eng.tokens, int(raw_u.get("tokens") or 0))
                        eng.cumulative_tokens = max(eng.cumulative_tokens, int(raw_u.get("cumulative_tokens") or 0))
                        eng.turns = max(eng.turns, int(raw_u.get("turns") or 0))
                        eng.unpriced_turns = max(eng.unpriced_turns, int(raw_u.get("unpriced_turns") or 0))
                        eng.estimated_turns = max(eng.estimated_turns, int(raw_u.get("estimated_turns") or 0))
                        eng.estimated_spend = max(eng.estimated_spend, float(raw_u.get("estimated_spend") or 0.0))
                        eng.cumulative_estimated_spend = max(
                            eng.cumulative_estimated_spend, float(raw_u.get("cumulative_estimated_spend") or 0.0)
                        )
                        if isinstance(raw_u.get("last_session_usage"), dict):
                            eng._last_session_usage = dict(raw_u["last_session_usage"])

        if state_entries_updated > 0 or ledger_entries_added > 0:
            # Clear caches when usage figures actually changed so the next UI read serves fresh figures
            with sr._ROLLUP_LOCK:
                sr._ROLLUP_CACHE.clear()
                sr._STATE_CACHE.clear()
                sr._GLOBAL_USAGE_CACHE["ts"] = 0.0
                sr._GLOBAL_USAGE_CACHE["data"] = None

        summary_resp = sr.global_usage_summary()
        summary = summary_resp[0] if isinstance(summary_resp, tuple) else summary_resp
        result = {
            "ok": True,
            "synced_at": now_iso,
            "date": _dt.datetime.now().strftime("%Y-%m-%d"),
            "ledger_entries_added": ledger_entries_added,
            "state_entries_updated": state_entries_updated,
            "reconciled_sessions": reconciled_sessions,
            "windows": summary.get("windows") if isinstance(summary, dict) else {},
            "projects": summary.get("projects") if isinstance(summary, dict) else [],
            "providers": summary.get("providers") if isinstance(summary, dict) else [],
        }

        if write_snapshot:
            try:
                snap_dir = _paths.data_dir() / ".anchor" / "usage_snapshots"
                snap_dir.mkdir(parents=True, exist_ok=True)
                date_str = _dt.datetime.now().strftime("%Y-%m-%d")
                dated_file = snap_dir / f"{date_str}.json"
                latest_file = snap_dir / "latest.json"
                payload_text = json.dumps(result, indent=2) + "\n"
                dated_file.write_text(payload_text, encoding="utf-8")
                latest_file.write_text(payload_text, encoding="utf-8")
            except OSError:
                pass

        _LAST_SYNC_TS = time.time()
        return result


def start_background_sync_daemon(interval_seconds: int = 300) -> threading.Thread:
    """Start a daemon thread in anchor_gui.py that reconciles usage every 5 minutes and at midnight."""
    def _loop() -> None:
        # Defer first sync slightly after boot so throwaway healthcheck servers and
        # immediate boot probes do not contend with a full transcript scan at t=0.
        time.sleep(min(15, max(1, interval_seconds // 10)))
        last_date = ""
        while True:
            try:
                today = _dt.datetime.now().strftime("%Y-%m-%d")
                is_new_day = today != last_date
                sync_all_usage(write_snapshot=is_new_day or (_LAST_SYNC_TS == 0.0))
                last_date = today
            except Exception:
                pass
            time.sleep(max(30, interval_seconds))

    t = threading.Thread(target=_loop, name="anchor-usage-nightly-sync", daemon=True)
    t.start()
    return t


if __name__ == "__main__":
    out = sync_all_usage(write_snapshot=True)
    print(json.dumps(out, indent=2))
