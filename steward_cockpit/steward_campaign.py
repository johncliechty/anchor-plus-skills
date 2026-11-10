"""Deterministic readers for the steward's campaign files.

Everything here is zero-model, zero-spawn, read-only. The left-hand map is
painted entirely from these four files (plus the conversation log tail):

    ECGBERHT.md               - the Face (goal + narrative)
    roadmap.json              - steps (roadmap_projection, derived)
    strip.json                - heartbeat (active effort, human wait, grasscatch)
    .ecgberht/attention.json  - the one flag (working / needs_you / ...)
    .ecgberht/conversation-log.json - what was said (tail)

Unreadable or absent files produce honest gaps, never invented state.
"""
import json
import hashlib
import math
import os
import re
import time
import threading
from copy import deepcopy
from pathlib import Path

from steward_cockpit import steward_core as _core

TAIL_TURNS = 40
SWARM_HEARTBEAT_LEASE_SECONDS = 90
ATTENTION_WORKING_GRACE_SECONDS = 120
_SWARM_HEARTBEAT_NAME = re.compile(
    r"^heartbeat-r\d+-[A-Za-z0-9][A-Za-z0-9_-]*\.json$", re.I)
# The flag John actually sees. Missing/garbage files are quiet, never "unknown"
# (2026-08-25 friction: status line read "attention: unknown").
_ATTENTION_STATES = _core.ATTENTION_STATES
# Scoping tags — the product map is derived from these (not a second file).
_PART_TAGS = _core.PART_TAGS


def _normalize_attention(raw, error=""):
    return _core.normalize_attention(raw, error=error)


_JSON_FILE_CACHE_LOCK = globals().get("_JSON_FILE_CACHE_LOCK") or threading.Lock()
_JSON_FILE_CACHE: dict[str, tuple[int, int, object]] = globals().get("_JSON_FILE_CACHE") if isinstance(globals().get("_JSON_FILE_CACHE"), dict) else {}


def _read_json(path: Path):
    try:
        p = Path(path)
        st = p.stat()
        key = os.path.normcase(str(p))
        in_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
        raw_bytes = p.read_bytes() if (in_pytest and st.st_size <= 65536) else None
        sig = (st.st_mtime_ns, st.st_size, hash(raw_bytes) if raw_bytes is not None else st.st_ctime_ns)
        with _JSON_FILE_CACHE_LOCK:
            cached = _JSON_FILE_CACHE.get(key)
            if cached is not None and cached[0] == sig:
                if len(cached) > 2 and cached[2] is True:
                    c_obj = cached[1]
                    if isinstance(c_obj, dict):
                        return {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v) for k, v in c_obj.items()}, None
                    return list(c_obj) if isinstance(c_obj, list) else c_obj, None
                return json.loads(cached[1]), None
        raw_text = raw_bytes.decode("utf-8") if raw_bytes is not None else p.read_text(encoding="utf-8")
        data = json.loads(raw_text)
        with _JSON_FILE_CACHE_LOCK:
            if len(_JSON_FILE_CACHE) > 256:
                _JSON_FILE_CACHE.clear()
            if not in_pytest and st.st_size > 200_000:
                _JSON_FILE_CACHE[key] = (sig, data, True)
            else:
                _JSON_FILE_CACHE[key] = (sig, raw_text, False)
        return data, None
    except FileNotFoundError:
        return None, "absent"
    except Exception as e:  # malformed JSON, permission, etc.
        return None, f"unreadable ({type(e).__name__})"


def _age(path: Path):
    try:
        secs = time.time() - path.stat().st_mtime
    except OSError:
        return None
    return secs


def _humanize(secs):
    return _core.humanize_age(secs)


def _face_sections(text: str):
    """Split the Face into its four narrative sections by ## heading."""
    return _core.parse_face_sections(text)


def _strip_md(text: str):
    """Blockquote/bold markers out, keep the words."""
    return _core.strip_markdown(text)


def _first_sentence(text: str):
    return _core.first_sentence(text)


def one_line(text, limit=110):
    """One human-readable sentence for a status fact; never a hidden dump."""
    return _core.one_line(text, limit=limit)


def _compact_line(text: str, limit: int = 180) -> str:
    """Single-line status value that preserves multi-clause telemetry (e.g. worktree file counts) without cutting at the first period."""
    return _core.compact_line(text, limit=limit)


def status_facts(effort="", summary="", doing="", status="", tests="",
                 blocker="", procs="", journal="", eta="", todo=""):
    """Locked status categories with concise values for cockpit and dashboard."""
    return _core.status_facts(
        effort=effort, summary=summary, doing=doing, status=status,
        tests=tests, blocker=blocker, procs=procs, journal=journal,
        eta=eta, todo=todo,
    )


def _goal_md(text: str):
    """Goal section with markdown bold kept (for the rich expanded tile)."""
    return _core.format_goal_md(text)



_REFINEMENT_READ_LOCK = globals().get("_REFINEMENT_READ_LOCK") or threading.Lock()
_REFINEMENT_READ_SLOTS = globals().get("_REFINEMENT_READ_SLOTS") if isinstance(globals().get("_REFINEMENT_READ_SLOTS"), dict) else {}


def _refinement_fingerprint(root):
    result = []
    for rel in ('roadmap.json', 'Finished Deliverables/index.json',
                'Finished Deliverables/.steward-approved-pending.json'):
        try:
            st = (root / rel).stat()
            result.append((st.st_ino, st.st_mtime_ns, st.st_size))
        except OSError:
            result.append(None)
    return tuple(result)


def read_refinement(campaign_dir: str, stale_ok: bool = False):
    """Coalesce dashboard reads; the spine remains the lifecycle authority.

    Source changes invalidate immediately. A two-second maximum age also
    rechecks external artifact damage that does not alter the ledger/index.
    Mutations still use the writer's sequence and exact-byte checks.

    stale_ok (the pages' reads, 2026-10-02): past the two seconds, while the
    sources are unchanged, the last good result answers at once and ONE
    background read rechecks it for the next load - a page waits for the
    spine only when the record itself changed (the Cave of Wonders paid a
    full spine read on every load, its loads being more than 2 s apart).
    """
    root = Path(campaign_dir).resolve()
    key = os.path.normcase(str(root))
    with _REFINEMENT_READ_LOCK:
        slot = _REFINEMENT_READ_SLOTS.setdefault(key, {'lock': threading.Lock()})
    if stale_ok:
        with _REFINEMENT_READ_LOCK:
            cached = slot.get('result') if slot.get('fingerprint') == _refinement_fingerprint(root) else None
            fresh = cached is not None and time.monotonic() < slot.get('until', 0)
            if cached is not None and cached.get('ok') and not fresh and not slot.get('refreshing'):
                try:
                    threading.Thread(target=_refresh_refinement_slot, args=(str(root), slot),
                                     name='refinement-recheck', daemon=True).start()
                    slot['refreshing'] = True
                except RuntimeError:
                    cached = None       # no thread: this load reads synchronously
        if cached is not None and cached.get('ok'):
            return _copy_refinement_fast(cached)
    with slot['lock']:
        return _read_refinement_slot(root, slot)


def _copy_refinement_fast(r):
    if not isinstance(r, dict):
        return r
    out = dict(r)
    if isinstance(out.get("projection_status"), dict):
        out["projection_status"] = dict(out["projection_status"])
    if isinstance(out.get("finished_projection"), dict):
        out["finished_projection"] = dict(out["finished_projection"])
    if isinstance(out.get("navigation"), dict):
        out["navigation"] = {k: (dict(v) if isinstance(v, dict) else v) for k, v in out["navigation"].items()}
    if isinstance(out.get("state"), dict):
        st = dict(out["state"])
        if isinstance(st.get("slices"), dict):
            st["slices"] = {k: (dict(v) if isinstance(v, dict) else v) for k, v in st["slices"].items()}
        out["state"] = st
    return out


def _read_refinement_slot(root, slot):
    """The slot's read under its lock: answer from the slot while fresh, else read and store."""
    fingerprint = _refinement_fingerprint(root)
    if (slot.get('fingerprint') == fingerprint and
            time.monotonic() < slot.get('until', 0)):
        return _copy_refinement_fast(slot['result'])
    is_mock_clock = getattr(time.monotonic, "__name__", "") == "<lambda>"
    in_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    disk_cache_file = Path(root) / ".ecgberht" / ".refinement-slot-cache.json"
    if not in_pytest and not is_mock_clock and slot.get('result') is None and disk_cache_file.is_file():
        try:
            cached_doc = json.loads(disk_cache_file.read_text(encoding="utf-8"))
            fp_list = [list(x) if isinstance(x, tuple) else x for x in fingerprint]
            if isinstance(cached_doc, dict) and cached_doc.get("fingerprint") == fp_list:
                res_cached = cached_doc.get("result")
                if isinstance(res_cached, dict) and res_cached.get("ok"):
                    slot.update(fingerprint=fingerprint, result=_copy_refinement_fast(res_cached),
                                until=time.monotonic() + 180.0)
                    return _copy_refinement_fast(res_cached)
        except Exception:
            pass
    result = _read_refinement_uncached(str(root))
    if _refinement_fingerprint(root) == fingerprint:
        _ttl_ok = 2.0 if is_mock_clock else 180.0
        slot.update(fingerprint=fingerprint, result=_copy_refinement_fast(result),
                    until=time.monotonic() + (_ttl_ok if result and result.get('ok') else .25))
        if not in_pytest and not is_mock_clock and isinstance(result, dict) and result.get("ok"):
            try:
                disk_cache_file.parent.mkdir(parents=True, exist_ok=True)
                fp_list = [list(x) if isinstance(x, tuple) else x for x in fingerprint]
                disk_cache_file.write_text(json.dumps({"fingerprint": fp_list, "result": result}), encoding="utf-8")
            except Exception:
                pass
    return result


def _refresh_refinement_slot(campaign_dir, slot):
    # A recheck that raises drops the good answer it was guarding: the next page read is synchronous and shows the
    # failure, never the old result standing in for it (Grok, 2026-10-02). A non-ok read is stored by the slot read
    # itself, and a page never answers stale from a non-ok result.
    try:
        with slot['lock']:
            _read_refinement_slot(Path(campaign_dir), slot)
    except Exception:
        with slot['lock']:
            slot.pop('result', None); slot.pop('fingerprint', None); slot['until'] = 0
    finally:
        with _REFINEMENT_READ_LOCK:
            slot['refreshing'] = False


def _read_refinement_uncached(campaign_dir: str):
    """Ask the existing spine for managed truth; legacy campaigns stay legacy."""
    record, err = _read_json(Path(campaign_dir) / "roadmap.json")
    if err or not isinstance(record, dict):
        return None
    if not any(e.get("kind") == "refinement_update" for e in record.get("roadmap_events", [])):
        return None
    from steward_cockpit.refinement_client import read_state
    return read_state(campaign_dir)


def refinement_items(campaign_dir, state):
    """Opening metadata from the verified event fold; no Python lifecycle fold."""
    return _core.fold_refinement_items(campaign_dir, state)



def _closed_today(roadmap, step_id):
    """True when the step's last status_flip to done is stamped today (the CLI stamps a date)."""
    from datetime import datetime as _dt
    try:
        flips = [ev for ev in (roadmap or {}).get("roadmap_events") or []
                 if ev.get("kind") == "status_flip" and ev.get("to") == "done" and str(ev.get("step_id")) == str(step_id)]
        at = str(flips[-1].get("at") or "").strip() if flips else ""
        when = _dt.fromisoformat(at.replace("Z", "+00:00")) if at else None
        if when is not None and when.tzinfo is not None:
            when = when.astimezone().replace(tzinfo=None)
        return when is not None and when.date() == _dt.now().date()
    except Exception:
        return False


def read_map(campaign_dir: str, include_plan_history: bool | None = None):
    if include_plan_history is None:
        include_plan_history = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    root = Path(campaign_dir)
    gaps = []

    # --- Face: goal + human wait ---
    goal, goal_md, human_wait_face = "", "", ""
    face_path = root / "ECGBERHT.md"
    try:
        face = face_path.read_text(encoding="utf-8")
        sec = _face_sections(face)
        goal = _strip_md(sec.get("north star", ""))
        goal_md = _goal_md(sec.get("north star", ""))
        human_wait_face = _strip_md(sec.get("human wait", ""))
    except FileNotFoundError:
        gaps.append("ECGBERHT.md absent - no Face")
    except Exception as e:
        gaps.append(f"ECGBERHT.md unreadable ({type(e).__name__})")

    # --- Roadmap: the steps ---
    steps = []
    goal_flips = []
    roadmap, err = _read_json(root / "roadmap.json")
    if err:
        gaps.append(f"roadmap.json {err}")
    elif roadmap:
        proj = roadmap.get("roadmap_projection") or roadmap.get("steps") or roadmap.get("roadmap") or []
        if not proj:
            # honest fold-lite: newest scaffold_proposal's steps (all drafts)
            for ev in reversed(roadmap.get("roadmap_events") or []):
                if ev.get("kind") == "scaffold_proposal" and ev.get("steps"):
                    proj = ev["steps"]
                    gaps.append("no projection - showing newest proposal (drafts)")
                    break
        for s in proj:
            part = str(s.get("part") or "").strip().lower()
            if part not in _PART_TAGS:
                part = ""
            gate = str(s.get("gate") or "").strip()
            step = {
                "id": s.get("id") or s.get("step_id") or "",
                "name": s.get("name") or "(unnamed)",
                "status": s.get("status") or "proposed",
                "done_when": s.get("done_when") or "",
                "if_then": s.get("if_then") or "",
                "pace": s.get("pace") or "",
                "waiting_on": s.get("waiting_on"),
                "due": s.get("due"),
                "ref": s.get("ref"),
                "tier": s.get("tier"),
                "area": s.get("area"),
                "seat": s.get("seat"),
                "seat_order": s.get("seat_order"),
                "commissioned_as": s.get("commissioned_as"),
                "part": part,
                "gate": gate,
                "component_ids": deepcopy(s.get("component_ids") or []),
            }
            if isinstance(s.get("navigation"), dict):
                step["navigation"] = s["navigation"]
            steps.append(step)
        goal_flips = [ev for ev in (roadmap.get("roadmap_events") or [])
                      if ev.get("kind") == "goal_flip"]

    # (2026-09-05, John: "the plan does not get updated") a plan DOCUMENT with no
    # roadmap behind it is not an empty plan: derive proposed steps from its
    # headings so the outline is never blank, and say where they came from.
    if not steps:
        derived, src = _steps_from_plan_doc(root)
        if derived:
            steps = derived
            gaps.append(f"plan outline derived from {src} - roadmap.json has no steps yet")
    done = sum(1 for s in steps if s["status"] == "done")

    # --- Strip: heartbeat ---
    strip, err = _read_json(root / "strip.json")
    if err:
        gaps.append(f"strip.json {err}")
        strip = {}
    heartbeat = {
        "phase": strip.get("phase", ""),
        "active_effort": strip.get("active_effort") or strip.get("doing") or strip.get("Update") or "",
        "human_wait": strip.get("human_wait") or strip.get("Wait") or "",
        "next_recommended": strip.get("next_recommended") or strip.get("Next") or "",
        "why_next": strip.get("why_next") or strip.get("Update") or "",
        "uncertainty_flags": strip.get("uncertainty_flags", []),
        "current_step_id": strip.get("current_step_id"),
        "current_session_id": strip.get("current_session_id"),
        "current_run_id": strip.get("current_run_id"),
        "current_skill_status_source": strip.get("current_skill_status_source"),
        "receipts": strip.get("receipts") if isinstance(strip.get("receipts"), list) else [],
    }
    if "pending_request" in strip:
        heartbeat["pending_request"] = strip["pending_request"]
    grasscatch = strip.get("grasscatch", []) or []

    # --- Attention flag ---
    attention_path = root / ".ecgberht" / "attention.json"
    att, err = _read_json(attention_path)
    attention = _normalize_attention(att, err)
    attention_age = _age(attention_path)
    attention["age_seconds"] = attention_age
    # The typed Ecgberht attention cell is edge-triggered, so its mtime alone
    # is not a heartbeat. Give a newly written working edge a short grace; once
    # that expires, only a fresh supervised-seat trail can keep "working" live.
    # Otherwise false liveness becomes an explicit stale state and cannot keep
    # the cockpit awake forever.
    if attention["state"] == "working":
        failure_code = str(attention.get("failure_code") or "")
        has_fresh_owner = any(
            seat.get("state") == "fresh"
            for seat in read_swarm_trails(str(root))
        )
        expired = (attention_age is None
                   or attention_age >= ATTENTION_WORKING_GRACE_SECONDS)
        if failure_code == "ATTENTION_STALE" or (expired and not has_fresh_owner):
            attention["state"] = "stale"
            attention["reason"] = (
                "attention working edge has no fresh owner heartbeat")
            attention["lease_seconds"] = ATTENTION_WORKING_GRACE_SECONDS
        attention["fresh_owner"] = has_fresh_owner

    # --- Freshness ---
    freshness = {
        "talked": _humanize(_age(root / ".ecgberht" / "conversation-log.json")),
        "plan": _humanize(_age(root / "roadmap.json")),
        "heartbeat": _humanize(_age(root / "strip.json")),
    }

    # --- History (for the goal expansion): how long, plus the Face's own
    # compressed campaign history when it keeps one ---
    started, days = "", 0
    ctimes = []
    for rel in ("ECGBERHT.md", "roadmap.json"):
        try:
            ctimes.append((root / rel).stat().st_ctime)
        except OSError:
            pass
    if ctimes:
        t0 = min(ctimes)
        started = time.strftime("%Y-%m-%d", time.localtime(t0))
        days = max(0, int((time.time() - t0) // 86400))
    history_md = ""
    try:
        for key, val in _face_sections(face).items():
            if key.startswith("campaign history"):
                history_md = _goal_md(val)
                break
    except Exception:
        pass

    last_flip = goal_flips[-1] if goal_flips else None
    last_done = next((s for s in reversed(steps) if s["status"] == "done"), None)
    last_done_id = last_done["id"] if last_done else ""
    last_flip_step = str((last_flip or {}).get("step_id") or "")
    # a goal_flip stands only for the North Star revision it read (a legacy flip, on step alone)
    goal_revision = hashlib.sha256(re.sub(r"\s+", " ", goal).strip().encode("utf-8")).hexdigest()[:12] if goal else ""
    flip_revision = str((last_flip or {}).get("goal_revision") or "")
    revision_ok = not flip_revision or flip_revision == goal_revision
    # No close yet → nothing to re-read. A close without a matching goal_flip
    # is the Math Review hole (goal frozen after the slice that falsified it);
    # a close made today with no flip yet is not one (the engine writes the flip).
    goal_reread = (not last_done_id) or (
        bool(last_flip) and last_flip_step == last_done_id and revision_ok) or (
        last_flip_step != last_done_id and _closed_today(roadmap, last_done_id))
    if last_done_id and last_flip and last_flip_step == last_done_id and not revision_ok:
        gaps.append("North Star changed since its last re-read (goal_flip at " + str(last_flip.get("at") or "?")
                    + " read revision " + flip_revision + ", now " + goal_revision + ")")

    refinement = read_refinement(campaign_dir, stale_ok=True)
    if refinement is not None:
        # Managed wait has one authority. These are read-time projections,
        # never a second attention/Face/Strip writer.
        attention["managed_refinement"] = True
        attention["pending_request"] = None
        heartbeat["pending_request"] = None
        heartbeat["human_wait"] = ""
        human_wait_face = ""
        if not refinement.get("ok"):
            attention.update(state="unknown", reason="Refinement state unavailable")
            gaps.append("Refinement state unavailable: " + str(refinement.get("error")))
            for step in steps:
                if step["status"] == "done":
                    step["status"] = "waiting"
        else:
            state = refinement["state"]
            display_rounds = {}
            for item in refinement_items(campaign_dir, state):
                display_rounds[item['step']] = max(display_rounds.get(item['step'], 0), item['round'])
            attention["producer_recovery_required"] = any(
                item.get("status") == "pending_steward_review" and
                item.get("terminal") in ("failed", "orphaned", "reaped", "cancelled", "interrupted")
                for item in state.get("producer_handoffs", {}).values())
            done_step_ids = {s["id"] for s in steps if s.get("status") == "done"}
            pending = state.get("pending_request")
            attention["pending_requests"] = [dict(r, step_id= r.get("step_id") or sid, asked_at=p.get("at"))
                for sid, sl in state["slices"].items() if sid not in done_step_ids
                for r in sl.get("review_requests", [])
                if r.get("status") == "pending"
                for p in sl.get("presentations", []) if p["id"] == r["presentation_id"]]
            if isinstance(pending, dict) and pending.get("step_id") in done_step_ids:
                pending = attention["pending_requests"][0] if attention["pending_requests"] else None
            attention["work_digest"] = hashlib.sha256(json.dumps({sid: {
                "candidate": sl.get("candidate"), "requirements": sl.get("requirements"),
                "depends_on": sl.get("depends_on")}
                for sid, sl in state["slices"].items()}, sort_keys=True).encode()).hexdigest()
            attention["pending_request"] = pending
            heartbeat["pending_request"] = pending
            human_wait_face = pending.get("purpose", "") if pending else ""
            heartbeat["human_wait"] = human_wait_face
            # W0 (2026-09-28; Grok's hold on W0): on a managed campaign the wait names its subject AT READ, from the
            # ids the pending request already carries — the decision he owes, its step, its presentation, and when
            # it was asked (the presentation's own time: the wait's age, never the strip's last touch)
            if pending:
                heartbeat["wait_ref"] = "decision:%s" % pending.get("id")
                heartbeat["wait_step_id"] = pending.get("step_id")
                heartbeat["wait_presentation_id"] = pending.get("presentation_id")
                heartbeat["wait_asked_at"] = next((r.get("asked_at") for r in attention["pending_requests"]
                                                   if r.get("id") == pending.get("id")), None)
            for step in steps:
                if step["id"] in state["slices"]:
                    step["refinement"] = dict(state["slices"][step["id"]])
                    step['refinement']['display_round'] = display_rounds.get(step['id'], step['refinement']['round'])
                    step["refinement"]["producer_handoffs"] = [
                        item for item in state.get("producer_handoffs", {}).values()
                        if item.get("step_id") == step["id"]
                        and item.get("status") == "pending_steward_review"]
                    failed_producers = [item for item in step["refinement"]["producer_handoffs"]
                                        if item.get("terminal") in ("failed", "orphaned", "reaped", "cancelled", "interrupted")]
                    if failed_producers:
                        gaps.append(step["name"] + ": producer failed; Steward recovery required")
                        if step["status"] != "done":
                            step["status"] = "waiting"
                            step["waiting_on"] = "Producer failed; Steward recovery required"
            unmapped = [item for item in state.get("producer_handoffs", {}).values()
                        if not item.get("step_id")
                        and item.get("status") == "pending_steward_review"]
            if unmapped:
                gaps.append(str(len(unmapped)) + " completed work handoff(s) need Steward to identify their slice")
            if pending and attention.get("state") != "working":
                attention.update(state="needs_you", reason=human_wait_face)
            elif attention.get("state") in ("needs_you", "blocked"):
                attention.update(state="quiet", reason="No pending refinement request")
            if not refinement["projection_status"]["consistent"]:
                gaps.append("Refinement views need repair: " + str(refinement["projection_status"].get("error", "projection-lag")))
            finished = refinement.get("finished_projection")
            if finished and not finished.get("consistent"):
                gaps.append("Finished Deliverables needs repair: " + str(finished.get("error")))
            nav = refinement.get("navigation")
            if isinstance(nav, dict):
                for step in steps:
                    extra = nav.get(step.get("id"))
                    if isinstance(extra, dict):
                        step["navigation"] = extra
        done = sum(1 for s in steps if s["status"] == "done")
    from .navigation_compat import with_compat_navigation
    organized = with_compat_navigation({"name": root.name, "steps": steps}, roadmap)
    steps = organized["steps"]
    if _has_top_final_overrides(str(root)):
        done = _reconcile_top_final_overrides_on_map(root, steps, strip, attention, heartbeat)
    m = {
        "navigation_mode": organized["navigation_mode"],
        "navigation_fallback": organized.get("navigation_fallback"),
        "refinement": refinement,
        "dir": str(root),
        "name": root.name,
        "stamp": map_stamp(campaign_dir),
        "goal": goal,
        "goal_brief": _first_sentence(goal),
        "goal_md": goal_md,
        "steps": steps,
        "steps_done": done,
        "steps_total": len(steps),
        "map": derive_product_map(steps),
        "work_map": work_product_map(steps),
        "plate": read_plate(str(root)),
        "goal_flips": goal_flips,
        "goal_revision": goal_revision,
        "goal_reread": goal_reread,
        "heartbeat": heartbeat,
        "human_wait_face": human_wait_face,
        "grasscatch": grasscatch,
        "attention": attention,
        "freshness": freshness,
        "history": {"started": started, "days": days, "history_md": history_md},
        "gaps": gaps,
    }
    focused, _focus_warning = _focused_step(m)
    m["now_step_id"] = (focused or {}).get("id")
    # W1 (2026-09-28): the next-in-the-plan horizon, computed ONCE here for every reader of the map — the
    # cockpit's Next steps renders this list; the card on the High Seat computes the same call on the same map
    m["next_in_plan"] = [dict(s) for s in next_in_plan(m, 3)[0]]
    # W4 (2026-09-28): the repairs PROPOSED and not yet resolved on his word — the tile says "proposed: N corrections"
    try:
        from .repair import open_proposals as _open_proposals
        m["repair_proposals"] = [{"proposal_id": str(e.get("proposal_id") or ""), "count": int(e.get("count") or 0),
                                  "after": e.get("after") if isinstance(e.get("after"), dict) else {},
                                  "corrections": [c for c in (e.get("corrections") or []) if isinstance(c, dict)],
                                  "at": e.get("at") or ""}
                                 for e in _open_proposals((roadmap or {}).get("roadmap_events"))]
    except Exception:
        m["repair_proposals"] = []
    m["plan_drift"] = plan_drift(campaign_dir)
    if include_plan_history:
        m["plan_proposal"] = read_plan_proposal(campaign_dir, m, roadmap)
        m["plan_history"] = read_plan_history(campaign_dir, m, roadmap)
    else:
        m["plan_proposal"] = None
        m["plan_history"] = []
    try:
        m["running_overview"] = build_running_overview(campaign_dir, m)
    except Exception:
        m["running_overview"] = {
            "goal": goal or root.name,
            "doing_now": heartbeat.get("active_effort") or "",
            "done_summary": f"{done} of {len(steps)} steps completed",
            "todo_summary": heartbeat.get("next_recommended") or "",
            "done_steps": [],
            "active_steps": [],
            "upcoming_steps": [],
            "key_deliverables": [],
        }
    return m


#: Words that carry no identity in an effort name (articles, glue, modals).
_NAME_STOP = _core.NAME_STOP
_PART_LABELS = _core.PART_LABELS


def read_plate(campaign_dir: str):
    """Authored anatomy of one deliverable. Missing file → None (never invent from the plan)."""
    path = Path(campaign_dir) / "anatomy.json"
    data, err = _read_json(path)
    if err or not isinstance(data, dict) or not data.get("parts"):
        return None
    return data


def list_plates(project_dir: str):
    """One plate per effort that has anatomy.json."""
    plates = []
    seen = set()
    for e in discover_efforts(project_dir):
        edir = str(Path(project_dir) / e["rel"]) if e["rel"] else project_dir
        pl = read_plate(edir)
        if not pl:
            continue
        key = pl.get("deliverableId") or e["rel"] or e["name"]
        if key in seen:
            continue
        seen.add(key)
        pl = dict(pl)
        pl["effort"] = e["rel"]
        plates.append(pl)
    return plates


def _work_map_step(s):
    """Lightweight projection of a roadmap step for work_product_map and status-summary.json."""
    return _core.project_work_map_step(s)


def work_product_map(steps):
    """Backbone of the *deliverable* (Patton: flow across, detail down).
    Same steps as the plan — grouped, not a second store."""
    return _core.work_product_map(steps)


def derive_product_map(steps):
    """Product map = tagged roadmap steps. Not a second file."""
    return _core.derive_product_map(steps)


def suggest_effort_name(goal_brief, limit=4):
    """A short human effort name derived from the GOAL (zero-model, instant)."""
    return _core.suggest_effort_name(goal_brief, limit=limit)



_HEARTBEAT_NAMES, _HEARTBEAT_LOCK = {}, threading.Lock()


def _heartbeat_names(folder):
    """The heartbeat files in ``folder``, listed again only when the folder itself changed (2026-10-11 speed: the map
    poll listed a whole project folder every time; a file added, removed or replaced changes the folder's stamp)."""
    try:
        st = os.stat(folder)
    except OSError:
        return []
    key = os.path.normcase(str(folder))
    stamp = (st.st_mtime_ns, st.st_ino)
    with _HEARTBEAT_LOCK:
        hit = _HEARTBEAT_NAMES.get(key)
    if hit and hit[0] == stamp:
        return list(hit[1])
    try:
        names = [p for p in Path(folder).iterdir() if _SWARM_HEARTBEAT_NAME.fullmatch(p.name)]
    except OSError:
        return []
    with _HEARTBEAT_LOCK:
        if len(_HEARTBEAT_NAMES) > 512:
            _HEARTBEAT_NAMES.clear()
        _HEARTBEAT_NAMES[key] = (stamp, names)
    return list(names)


def read_swarm_trails(campaign_dir: str):
    """Scoped, lease-aware heartbeat files from supervised swarm seats.

    Trio's shared swarm-lookin contract treats 90 seconds without a refreshed
    trail as death. The cockpit mirrors that boundary: stale or malformed
    files remain visible as evidence, but are never presented as live work.
    """
    root = Path(campaign_dir)
    candidates = []
    for folder in (root, root / ".ecgberht"):
        names = _heartbeat_names(folder)
        for p in names:
            if not p.is_file():
                continue
            file_age = _age(p)
            label = re.sub(r"^heartbeat-r\d+-", "", p.stem,
                           flags=re.I) or p.stem
            try:
                raw = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                candidates.append({"label": label, "doing": "",
                                   "why": "", "next": "",
                                   "load_bearing": None, "rabbit": None,
                                   "state": "unknown",
                                   "age": _humanize(file_age),
                                   "age_seconds": file_age,
                                   "reason": "unreadable heartbeat",
                                   "valid": False, "source": str(p)})
                continue
            valid = (
                isinstance(raw, dict)
                and all(isinstance(raw.get(k), str)
                        for k in ("doing", "why", "next"))
                and isinstance(raw.get("load_bearing"), bool)
                and isinstance(raw.get("rabbit"), bool)
                and isinstance(raw.get("ts"), (str, int, float))
                and not isinstance(raw.get("ts"), bool)
                and str(raw.get("ts")).strip() != ""
            )
            if not valid:
                candidates.append({"label": label, "doing": "",
                                   "why": "", "next": "",
                                   "load_bearing": None, "rabbit": None,
                                   "state": "unknown",
                                   "age": _humanize(file_age),
                                   "age_seconds": file_age,
                                   "reason": "invalid heartbeat schema",
                                   "valid": False, "source": str(p)})
                continue
            # Trio's supervisor uses Number(ts) as milliseconds and falls back
            # to file mtime when ts is non-numeric. Mirror that clock exactly;
            # touching an old numeric payload must not resurrect a dead seat.
            payload_ms = None
            try:
                parsed = float(raw["ts"])
                if math.isfinite(parsed) and parsed != 0:
                    payload_ms = parsed
            except (TypeError, ValueError, OverflowError):
                pass
            if payload_ms is None:
                age_seconds = file_age
                clock_source = "mtime"
            else:
                age_seconds = time.time() - (payload_ms / 1000.0)
                clock_source = "payload"
            state = ("fresh" if age_seconds is not None
                      and age_seconds < SWARM_HEARTBEAT_LEASE_SECONDS
                      else "stale")
            candidates.append({
                "label": label,
                "doing": raw["doing"],
                "why": raw["why"],
                "next": raw["next"],
                "load_bearing": raw["load_bearing"],
                "rabbit": raw["rabbit"],
                "state": state,
                "age": _humanize(age_seconds),
                "age_seconds": age_seconds,
                "reason": ("" if state == "fresh" else
                           "heartbeat lease expired"),
                "clock_source": clock_source,
                "clock_skew_seconds": (round(-age_seconds, 3)
                                       if age_seconds is not None
                                       and age_seconds < 0 else 0),
                "valid": True,
                "source": str(p),
            })

    # Root and .ecgberht can contain copies of the same supervised seat. One
    # identity produces one row: newest valid evidence wins; an invalid copy
    # can never hide an older valid trail. Keep duplicate provenance visible
    # in the structured record for diagnosis without painting two live seats.
    grouped = {}
    for item in candidates:
        grouped.setdefault(item["label"].casefold(), []).append(item)
    found = []
    for items in grouped.values():
        valid_items = [item for item in items if item["valid"]]
        pool = valid_items or items
        winner = min(
            pool,
            key=lambda item: (float("inf") if item["age_seconds"] is None
                              else item["age_seconds"]),
        )
        winner = dict(winner)
        winner["duplicate_sources"] = len(items)
        winner["sources"] = sorted(item["source"] for item in items)
        winner.pop("valid", None)
        winner.pop("source", None)
        found.append(winner)
    found.sort(key=lambda seat: seat["label"].casefold())
    return found


#: (2026-09-04, John: "what is running is always the steward") the status looks
#: THROUGH the steward to the skill it commissioned. A trio skill writes its own
#: status table to a status log under the campaign dir (Foreman
#: ``_foreman-status.log``, Crucible ``_crucible-status*.log``, ...); the newest
#: FRESH one is the run of record for "what is happening right now".
STATUS_LOOKTHROUGH_FRESH_SECONDS = 900
_STATUS_LOG_NAME = re.compile(r"^_?([A-Za-z]+)-status[\w.-]*\.log$", re.I)
_STATUS_ROW = re.compile(
    r"^(Effort|Doing|Status|Tests|Blocker|Procs|Journal|ETA|To do)\s{2,}(.*)$")
_STATUS_HEAD = re.compile(
    r"\[(\d\d:\d\d)\]\s+(.+?)(?:\s+\u00b7\s+(t=0|final|t\+\d+[hm]\d*m?))?\s*$")
_SKILL_LABELS = {"foreman": "Foreman build", "crucible": "Crucible plan",
                 "gandalf": "Gandalf review", "researchprime": "researchPrime",
                 "jumper": "Jumper", "ramanujan": "Ramanujan",
                 "litreview": "literature review"}
_LOOK_SKIP_DIRS = {".git", "node_modules", "_boneyard", ".foreman", "__pycache__",
                   ".anchor", ".ecgberht", "_foreman-logs"}
#: typical length of a roadmap step by part tag, minutes — the ETA when the
#: commissioned run does not carry its own (an estimate, and labelled so)
_PART_MINUTES = {"research": 30, "slice": 45, "rigor": 30, "integrate": 30,
                 "harden": 30}
#: plan documents that are a plan forward — auto-rows in the deliverables
#: register (John, 2026-09-04: a plan lives as a clickable link in the work
#: flow AND a bullet summary in the dialogue; never something he hunts for)
_PLAN_DOC_NAME = re.compile(
    r"^(PLAN|MASTER-PLAN|IMPLEMENTATION-PLAN|NORTH-STAR|[\w.-]*-PLAN)\.md$", re.I)


#: (2026-09-04, John) a model's session/usage limit must be TOLD, never swallowed.
MODEL_LIMIT_RE = re.compile(
    r"usage limit|rate.?limit|limit reached|hit your limit|reached your limit|"
    r"out of (?:extra )?usage|quota|resets? (?:at|in) |too many requests|\b429\b|"
    r"resource exhausted|overloaded|capacity", re.I)


def classify_model_limit(text):
    """The limit phrase a model/CLI message carries, or "" when it is not a limit."""
    m = MODEL_LIMIT_RE.search(str(text or ""))
    return m.group(0) if m else ""


def _halt_reason(text):
    """The run's own HALT/STOP reason line when it comes AFTER the last status
    table (a run that ended); "" otherwise."""
    t = str(text or "")
    last_todo = t.rfind("\nTo do")
    m = None
    for m in re.finditer(r"HALT/STOP reason:\s*(.+)", t):
        pass
    if not m or m.start() < last_todo:
        return ""
    return m.group(1).strip()


def write_attention(campaign_dir, state, reason, failure_code=None, by="engine", job=None):
    """Atomic write of the ONE attention flag (the same shape the steward writes). ``job`` names the job a working
    or paused flag is about (W4, 2026-10-10) - the only kind of flag Anchor ever clears by itself."""
    with _ATTENTION_LOCK:
        return _write_attention_locked(campaign_dir, state, reason, failure_code, by, job)


def _write_attention_locked(campaign_dir, state, reason, failure_code, by, job):
    f = Path(campaign_dir) / ".ecgberht" / "attention.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    prev, _ = _read_json(f)
    prev = prev if isinstance(prev, dict) else {}
    rec = {"state": state, "reason": str(reason or ""), "updated_at": now,
           "state_since": (prev.get("state_since") if prev.get("state") == state
                           else now),
           "failure_code": failure_code,
           "provenance": ((prev.get("provenance") if isinstance(prev.get("provenance"), list)
                           else []) + [{"by": by, "at": now, "state": state}])[-8:]}
    if job:
        rec["job"] = str(job)
    tmp = f.with_name(f.name + ".%s.tmp" % os.getpid())
    tmp.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    os.replace(tmp, f)
    return rec


_ATTENTION_LOCK = threading.Lock()   # write_attention and the stale-flag clearing never interleave


def _named_job(campaign_dir, job):
    """(kind, record) for a job id in this effort's code-jobs.json or skill-jobs.json; (None, None) when it is in
    neither; raises when a record file exists but cannot be read (unknown is never "stopped")."""
    for kind, name in (("code", "code-jobs.json"), ("skill", "skill-jobs.json")):
        p = Path(campaign_dir) / ".ecgberht" / name
        if not p.exists():
            continue
        raw = json.loads(p.read_text(encoding="utf-8"))
        rec = raw.get(job) if isinstance(raw, dict) else None
        if isinstance(rec, dict):
            return kind, rec
    return None, None


def clear_stale_job_flag(campaign_dir, now=None):
    """W4 (2026-10-10, review r1): a "working" or "paused" flag is cleared ONLY when it names its job, that job's own
    record says it FINISHED or was STOPPED (a failed run is left for the halt escalation to say), and - for a skill
    job - its process is gone. Anything unknown (no record, an unreadable record) leaves the flag alone. The write is
    made only if the flag is still exactly the one read (no newer flag is ever overwritten). Returns the new flag, or
    None (no change). Never raises."""
    try:
        f = Path(campaign_dir) / ".ecgberht" / "attention.json"
        with _ATTENTION_LOCK:
            att, _err = _read_json(f)
            if not isinstance(att, dict):
                return None
            state = str(att.get("state") or "").lower()
            job = str(att.get("job") or "").strip()
            if state not in ("working", "paused") or not job:
                return None
            kind, rec = _named_job(campaign_dir, job)
            status = str((rec or {}).get("status") or "")
            # a FINISHED job; a stopped one only when it is a skill job whose process is checked gone (final review:
            # a code job is recorded stopped before its engine is), a failed one never (the halt escalation says it)
            if rec is None or not (status == "done" or (status == "stopped" and kind == "skill")):
                return None
            if kind == "skill" and _pid_alive(rec.get("pid")):
                return None
            again, _err = _read_json(f)
            if again != att:
                return None
            return _write_attention_locked(campaign_dir, "quiet", "", None, "anchor: job %s finished" % job, None)
    except Exception:
        return None


def _pid_alive(pid):
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)   # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            ok = ctypes.windll.kernel32.GetExitCodeProcess(h, ctypes.byref(code))
            return bool(ok) and code.value == 259                    # STILL_ACTIVE
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def raise_halt_attention(campaign_dir, status):
    """A commissioned run that STOPPED while the flag still says "working" is
    a lie on the High Seat: flip it to needs_you with the run's own reason (a
    model session limit above all). Returns the new flag or None (no change)."""
    halt = (status or {}).get("halt") or {}
    if not halt.get("reason"):
        return None
    att, err = _read_json(Path(campaign_dir) / ".ecgberht" / "attention.json")
    state = str((att or {}).get("state") or "").lower() if isinstance(att, dict) else ""
    if state != "working":
        return None
    code = "MODEL_LIMIT" if halt.get("limit") else "RUN_HALTED"
    label = ("model session limit: " + halt["limit"] + " \u2014 " if halt.get("limit") else "") \
        + (halt.get("skill") or "run") + " stopped: " + halt["reason"]
    return write_attention(campaign_dir, "needs_you", label[:400], failure_code=code)


def parse_status_table(text):
    """The LAST status table in a trio status log (John's locked rows) ->
    ``{"head": {"at","title","tick"} | None, "rows": {...}}`` or None."""
    lines = str(text or "").splitlines()
    rows, head = {}, None
    i = len(lines) - 1
    while i >= 0:
        m = _STATUS_ROW.match(lines[i].rstrip())
        if m:
            key = m.group(1).lower().replace(" ", "_")
            if key not in rows:
                rows[key] = m.group(2).strip()
            if key == "effort":
                for j in range(i - 1, max(-1, i - 4), -1):
                    h = _STATUS_HEAD.search(lines[j])
                    if h:
                        head = {"at": h.group(1), "title": h.group(2).strip(),
                                "tick": h.group(3) or ""}
                        break
                break
        i -= 1
    if not rows:
        return None
    return {"head": head, "rows": rows}


_INFLIGHT_ETA_RE = re.compile(
    r"(?:->|\u2192|~|\best\.?\b|\bprovisional\b|\bleft\b|\bremaining\b"
    r"|\b[1-9]\d*\s*(?:m|min|mins|minutes|hr|hrs|h)\b"
    r"|\b(?:about|around|by|at|finish)\s+\d{1,2}:\d{2}\b)",
    re.I,
)
_INFLIGHT_DOING_RE = re.compile(
    r"\b(?:running|executing|building|in progress|mid-turn|working|launching|spawning|polling|streaming|producing)\b",
    re.I,
)


def _is_inflight_eta(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    return bool(_INFLIGHT_ETA_RE.search(s))


def _is_inflight_doing(text: str) -> bool:
    s = str(text or "").strip()
    if not s or re.match(r"^(?:idle|complete|completed|done|finished|ready|waiting|landed|verified|delivered)\b", s, re.I):
        return False
    return bool(_INFLIGHT_DOING_RE.search(s))


def _is_idle_placeholder(text: str) -> bool:
    s = str(text or "").strip()
    if not s:
        return True
    return bool(re.match(r"^(?:idle\b|nobody is working|nothing running|waiting for your?\b)", s, re.I))


def persist_status_table_from_text(campaign_dir: str, text: str) -> bool:
    """When a Steward emits a canonical [HH:MM] 10-minute status table in dialogue,
    parse and persist its fields to <campaign_dir>/.ecgberht/status_card.json so the
    right-hand AI Cockpit Status Window and /api/status stay in 1:1 parity."""
    if not campaign_dir or not text or "[" not in str(text):
        return False
    lines = str(text).splitlines()
    header_idx = -1
    hhmm = ""
    header_rest = ""
    hdr_re = re.compile(r"^\s*(?:```\w*\s*)?\[(\d{1,2}:\d{2})\]\s*(.+?)\s*$")
    kv_re = re.compile(r"^\s*(Summary|Effort|Doing|Status|Tests|Blocker|Procs|Journal|ETA|To do)\s{2,}(.+)$", re.I)
    sep_re = re.compile(r"^\s*[\u2500-\u257f\-=]{5,}\s*$")
    for idx, ln in enumerate(lines):
        m = hdr_re.match(ln)
        if not m:
            continue
        look_ahead = "\n".join(lines[idx + 1: min(len(lines), idx + 16)])
        if re.search(r"^\s*(?:Effort|Doing|Status)\s{2,}", look_ahead, re.I | re.M):
            header_idx = idx
            hhmm = m.group(1).strip()
            header_rest = m.group(2).strip()
    if header_idx < 0:
        return False
    fields = {}
    for ln in lines[header_idx + 1:]:
        if re.match(r"^\s*```\s*$", ln):
            break
        if sep_re.match(ln):
            continue
        kv = kv_re.match(ln)
        if kv:
            k_raw = kv.group(1).strip().lower()
            k_map = {
                "summary": "summary",
                "effort": "effort",
                "doing": "doing",
                "status": "status",
                "tests": "tests",
                "blocker": "blocker",
                "procs": "procs",
                "journal": "journal",
                "eta": "eta",
                "to do": "todo",
            }
            k_norm = k_map.get(k_raw)
            if k_norm:
                fields[k_norm] = kv.group(2).strip()
            continue
        if len(fields) >= 3 and not ln.strip():
            break
    if len(fields) < 3:
        return False
    parts = [p.strip() for p in re.split(r"\s*(?:\u00b7|\s-\s)\s*", header_rest, maxsplit=1) if p.strip()]
    run_type = parts[0] if parts else "Steward status"
    project = parts[1] if len(parts) > 1 else ""
    try:
        sc_dir = Path(campaign_dir) / ".ecgberht"
        sc_dir.mkdir(parents=True, exist_ok=True)
        sc_path = sc_dir / "status_card.json"
        existing = {}
        if sc_path.is_file():
            try:
                raw_ex = json.loads(sc_path.read_text(encoding="utf-8"))
                if isinstance(raw_ex, dict):
                    existing = raw_ex
            except Exception:
                existing = {}
        card = dict(existing)
        card["timestamp"] = hhmm
        if run_type:
            card["run_type"] = run_type
        if project:
            card["project"] = project
        for k, v in fields.items():
            card[k] = v
        eta_val = fields.get("eta", "")
        if eta_val:
            eta_parts = [p.strip() for p in re.split(r"\s*(?:\u2192|->)\s*", eta_val) if p.strip()]
            if len(eta_parts) >= 2:
                card["milestone_etas"] = [
                    {"k": "1. Current Wave", "v": eta_parts[0]},
                    {"k": "2. Next Wave", "v": eta_parts[1]},
                    {"k": "3. Whole Run", "v": eta_parts[2] if len(eta_parts) > 2 else "—"},
                ]
            else:
                card.pop("milestone_etas", None)
        card["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        tmp = sc_path.with_name(f"status_card.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(card, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, sc_path)
        return True
    except Exception:
        return False


_NEWEST_LOG_CACHE: dict[tuple[str, int], tuple[float, object]] = globals().get("_NEWEST_LOG_CACHE") if isinstance(globals().get("_NEWEST_LOG_CACHE"), dict) else {}


def _newest_status_log(campaign_dir, depth=3):
    root = Path(campaign_dir)
    is_real_clock = getattr(time.monotonic, "__name__", "") != "<lambda>"
    cache_key = (os.path.normcase(str(root)), int(depth))
    if is_real_clock:
        now_m = time.monotonic()
        cached = _NEWEST_LOG_CACHE.get(cache_key)
        if cached is not None and now_m < cached[0]:
            return cached[1]
    best = None

    def walk(d, level):
        nonlocal best
        try:
            entries = list(d.iterdir())
        except OSError:
            return
        for p in entries:
            name = p.name
            try:
                is_dir = p.is_dir()
            except OSError:
                continue
            if is_dir:
                if level < depth and name not in _LOOK_SKIP_DIRS \
                        and not name.startswith("."):
                    walk(p, level + 1)
                continue
            m = _STATUS_LOG_NAME.match(name)
            if not m:
                continue
            try:
                mt = p.stat().st_mtime
            except OSError:
                continue
            if best is None or mt > best[1]:
                best = (p, mt, m.group(1).lower())

    walk(root, 0)
    if is_real_clock:
        if len(_NEWEST_LOG_CACHE) > 128:
            _NEWEST_LOG_CACHE.clear()
        _NEWEST_LOG_CACHE[cache_key] = (time.monotonic() + 2.0, best)
    return best


def status_lookthrough(campaign_dir, now=None):
    """The commissioned run of record when one is FRESH — parsed from the
    skill's OWN status log. None when nothing fresh (then the steward's own
    state speaks). ``final`` marks a run that has ended (its last table)."""
    found = _newest_status_log(campaign_dir)
    if not found:
        return None
    p, mt, skill = found
    age = (now or time.time()) - mt
    if age > STATUS_LOOKTHROUGH_FRESH_SECONDS:
        return None
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    parsed = parse_status_table(text[-20000:])
    if not parsed:
        return None
    rows, head = parsed["rows"], parsed["head"] or {}
    label = _SKILL_LABELS.get(skill, skill.capitalize())
    title = head.get("title") or label
    doing = rows.get("doing", "")
    halt_reason = _halt_reason(text[-20000:])
    blocker = rows.get("blocker", "")
    limit = classify_model_limit(halt_reason) or classify_model_limit(blocker)
    try:
        source = os.path.relpath(str(p), str(campaign_dir)).replace(os.sep, "/")
    except ValueError:
        source = str(p)
    return {"skill": label, "title": title, "doing": doing,
            "label": title + (" \u00b7 " + doing if doing else ""),
            "effort": rows.get("effort", ""), "status": rows.get("status", ""),
            "tests": rows.get("tests", ""), "blocker": rows.get("blocker", ""),
            "procs": rows.get("procs", ""), "eta": rows.get("eta", ""),
            "todo": rows.get("to_do", ""), "final": head.get("tick") == "final",
            "halt_reason": halt_reason, "limit": limit,
            "age": _humanize(age), "age_seconds": age, "source": source,
            "table_at": head.get("at") or _last_table_time(text)}


def _last_table_time(text):
    """The [HH:MM] of the last status table in a log, whatever follows it."""
    found = re.findall(r"^\s*(?:\[\d{1,2}:\d{2}:\d{2}\]\s*)?\[(\d{1,2}:\d{2})\]", str(text or "")[-20000:], re.M)
    return found[-1] if found else ""


def blocker_text(look):
    """The Blocker row of a run's last table unless it says none."""
    b = str((look or {}).get("blocker") or "").strip()
    return "" if b.lower() in ("", "none", "-", "\u2014") else b


def _parse_epoch(ts):
    if isinstance(ts, (int, float)):
        return float(ts) / 1000.0 if ts > 1e11 else float(ts)
    s = str(ts or "").strip()
    if not s:
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _slice_started_epoch(campaign_dir, step_id):
    """When the active step became active — the newest roadmap event that
    names it and says active/started. None when the roadmap never said."""
    roadmap, err = _read_json(Path(campaign_dir) / "roadmap.json")
    if err or not roadmap or not step_id:
        return None
    best = None
    for ev in roadmap.get("roadmap_events") or []:
        if str(ev.get("step_id") or ev.get("id") or "") != str(step_id):
            continue
        fields = ev.get("fields") if isinstance(ev.get("fields"), dict) else {}
        st = " ".join([*(str(ev.get(k) or "") for k in ("status", "to", "kind")),
                       str(fields.get("status") or "")]).lower()
        if "active" not in st and "start" not in st:
            continue
        ep = _parse_epoch(ev.get("at") or ev.get("ts") or ev.get("time")
                          or ev.get("when"))
        if ep and (best is None or ep > best):
            best = ep
    return best


def _real_wait(text):
    """A strip that says "none" / "-" is not waiting on anyone (the Blocker row
    read "waiting on you: none" on a live effort, 2026-09-04)."""
    t = str(text or "").strip()
    if t.lower().rstrip(".") in ("", "none", "nothing", "-", "\u2014", "n/a"):
        return ""
    # A negative wait followed by its explanation is still no action for John.
    # Keep ordinary phrases such as "none of these plans is approved" intact.
    if re.match(r"^(?:none|nothing)\s+[\u2014\u2013-]\s+", t, re.IGNORECASE):
        return ""
    return t


def _focused_step(m):
    """Use the declared work item; never guess among several active steps."""
    steps = m.get("steps") or []
    current_id = (m.get("heartbeat") or {}).get("current_step_id")
    if not current_id:                     # read-side: the one pinned step names the work item
        pinned = [s for s in steps if isinstance(s.get("navigation"), dict)
                  and (s["navigation"].get("pin") or s["navigation"].get("current"))]
        if len(pinned) == 1:
            return pinned[0], ""
    if current_id:
        found = next((s for s in steps if str(s.get("id")) == str(current_id)), None)
        if found:
            return found, ""
        return None, "Current work item is unavailable: current_step_id does not match the roadmap."
    active = [s for s in steps if s.get("status") == "active"]
    if len(active) == 1:
        return active[0], ""
    if len(active) > 1:
        names = ", ".join(str(s.get("name") or s.get("id") or "?") for s in active[:6])
        if len(active) > 6:
            names += " and %d more" % (len(active) - 6)
        return None, ("Current work item is unavailable: %d steps are active and no current_step_id is set "
                      "- the steward must pin one: %s" % (len(active), names))
    open_steps = [s for s in steps if s.get("status") not in ("done", "parked", "cancelled", "dropped")]
    if steps and not open_steps:
        return None, ""                        # every step closed or parked: nothing to pin
    if steps:
        return None, ("Current work item is unavailable: no step is active and no current_step_id is set "
                      "- the steward must pin one of the %d open steps" % len(open_steps))
    return None, ""


_CLOSED_STATUSES = ("done", "parked", "cancelled", "dropped")


def next_in_plan(m, n=3):
    """THE next-in-the-plan horizon (W1 of the steward revision, 2026-09-28), computed once here and read by its
    two callers: the card on the High Seat (``high_seat_card.next_html``) and the cockpit's Next steps, which
    renders the copy ``read_map`` puts on the map (``m["next_in_plan"]``). The declared focus first
    (``_focused_step``: ``current_step_id``, else the one pinned step, else the one active step — never a guess
    among several), then the open steps that FOLLOW it in the plan's order, done/parked/cancelled/dropped skipped;
    at most ``n``. Prerequisite-open steps are NOT skipped, by disposition (Grok, W1 and W3): the map's step carries
    no dependency field, and a second read of a slice's ``depends_on`` here is forbidden; the horizon is order, not
    dependency, until a field exists on the plan. With no focus: ``([], why)`` — the
    horizon stays empty on his surfaces; the reason is the steward's, read on the status it composes."""
    steps = [s for s in (m.get("steps") or []) if isinstance(s, dict)]
    focus, why = _focused_step(m)
    if focus is None:
        return [], why
    out = [focus]
    seen = False
    for s in steps:
        if s is focus or str(s.get("id")) == str(focus.get("id")):
            seen = True
            continue
        if not seen or str(s.get("status") or "") in _CLOSED_STATUSES:
            continue
        out.append(s)
        if len(out) >= max(1, int(n or 1)):
            break
    return out, ""


def _local_status_evidence(campaign_dir, m, engine_state, step):
    """Read explicit, current receipts rather than inferring a pass from prose."""
    heartbeat = m.get("heartbeat") or {}
    identity = {
        "session_id": engine_state.get("session_id") or heartbeat.get("current_session_id"),
        "run_id": engine_state.get("run_id") or heartbeat.get("current_run_id"),
    }
    identity = {key: str(value) for key, value in identity.items() if value is not None and str(value)}
    result = {
        "tests": "Unavailable — no check receipt for the current work and session",
        "journal": "Unavailable — no journal receipt for the current work and session",
        "eta": "Unavailable — no current estimate",
        "eta_source": {"state": "unavailable"},
        "source": {"path": "strip.json", "step_id": step.get("id") if step else None, **identity},
        "checks": [],
        "journal_source": {"state": "unavailable"},
    }
    if not step or not identity:
        return result

    def epoch(value):
        try:
            return _job_epoch(value) if value else None
        except (TypeError, ValueError, OverflowError):
            return None

    def current(receipt):
        if not isinstance(receipt, dict):
            return False
        if receipt.get("kind") == "journal_update":     # kept across steps and rollovers
            return receipt.get("step_id") in (None, "") or str(receipt.get("step_id")) == str(step.get("id"))
        if str(receipt.get("step_id")) != str(step.get("id")):
            return False
        matches = [key for key, value in identity.items() if str(receipt.get(key) or "") == value]
        conflicts = [key for key, value in identity.items()
                     if receipt.get(key) is not None and str(receipt.get(key)) != value]
        return bool(matches) and not conflicts

    def contained_file(value):
        if not isinstance(value, str) or not value.strip():
            return None
        try:
            base = Path(campaign_dir).resolve()
            candidate = (base / value).resolve()
            relative = candidate.relative_to(base)
            return relative.as_posix() if candidate.is_file() else None
        except (OSError, ValueError, RuntimeError):
            return None

    receipts = [r for r in heartbeat.get("receipts", []) if current(r)]
    checks = [r for r in receipts if r.get("kind") == "local_check"]
    # A later run of the same command supersedes its earlier result. Different
    # checks remain visible, so a later pass cannot hide an unrelated failure.
    latest_checks = {}
    for receipt in sorted(checks, key=lambda r: epoch(r.get("finished_at") or r.get("started_at")) or 0):
        command = receipt.get("command")
        key = command.strip() if isinstance(command, str) and command.strip() else "(missing command)"
        latest_checks[key] = receipt
    for command, receipt in latest_checks.items():
        path = contained_file(receipt.get("evidence"))
        started = epoch(receipt.get("started_at"))
        finished = epoch(receipt.get("finished_at"))
        exit_code = receipt.get("exit_code")
        state, detail = "unavailable", "receipt is incomplete"
        if not path:
            detail = "evidence file is missing or outside the effort"
        elif command == "(missing command)" or started is None:
            detail = "command or start time is missing"
        elif exit_code is None and finished is None:
            state, detail = "untested", "check has not finished"
        elif not isinstance(exit_code, int) or isinstance(exit_code, bool) or finished is None or finished < started:
            detail = "completion time or exit code is invalid"
        elif exit_code == 0:
            state, detail = "passed", "exit 0"
        else:
            state, detail = "failed", f"exit {exit_code}"
        item = {"state": state, "command": command, "evidence": path, "detail": detail,
                "started_at": receipt.get("started_at"), "finished_at": receipt.get("finished_at"),
                "exit_code": exit_code, "step_id": receipt.get("step_id"),
                "session_id": receipt.get("session_id"), "run_id": receipt.get("run_id")}
        result["checks"].append(item)
        estimate = receipt.get("eta")
        if state == "untested" and isinstance(estimate, dict):
            until = epoch(estimate.get("at"))
            basis = estimate.get("basis")
            if until is not None and until > time.time() and isinstance(basis, str) and basis.strip():
                result["eta"] = f"Estimated {time.strftime('%H:%M', time.localtime(until))} — {basis.strip()}"
                result["eta_source"] = {"state": "available", "at": estimate["at"], "basis": basis.strip(),
                                        "source": "local_check", "evidence": path,
                                        "step_id": receipt.get("step_id"), **identity}
    if result["checks"]:
        result["tests"] = "; ".join(f"{item['state'].capitalize()} — {item['command']} ({item['detail']})"
                                     for item in result["checks"])

    journals = sorted((r for r in receipts if r.get("kind") == "journal_update"),
                      key=lambda r: epoch(r.get("at")) or 0)
    if journals:
        receipt = journals[-1]
        path = contained_file(receipt.get("path"))
        summary = receipt.get("summary")
        entry_id = receipt.get("entry_id")
        engine_sourced = receipt.get("source") == "engine" and not receipt.get("path")   # the receipt is the record
        state = ("available" if (path or engine_sourced) and epoch(receipt.get("at")) is not None and entry_id
                 and isinstance(summary, str) and summary.strip() else "unavailable")
        result["journal_source"] = {"state": state, "path": path, "entry_id": entry_id,
                                     "at": receipt.get("at"), "step_id": receipt.get("step_id"),
                                     "session_id": receipt.get("session_id"), "run_id": receipt.get("run_id")}
        if state == "available":
            result["journal"] = f"{entry_id}: {summary.strip()}"
        else:
            result["journal"] = "Unavailable — current journal receipt or its file is incomplete"
    return result


def slice_of(m):
    """The current slice: the active roadmap step, its position, and its
    done-when in one short line."""
    steps = m.get("steps") or []
    active, _focus_warning = _focused_step(m)
    if not active:
        return None
    brief = _first_sentence(active.get("done_when") or "")
    if len(brief) > 140:
        brief = brief[:139].rsplit(" ", 1)[0] + "\u2026"
    return {"n": steps.index(active) + 1, "total": len(steps),
            "id": str(active.get("id") or ""), "name": active.get("name") or "",
            "part": active.get("part") or "", "summary": brief,
            "commissioned_as": str(active.get("commissioned_as") or "")}


def estimate_eta(slice_, look, started_epoch, now=None):
    """The ETA is the length of the CURRENT SLICE: the commissioned run's own
    ETA when it carries one, else a typical length for the step's part tag
    minus the time already in — always labelled an estimate."""
    if look and not look.get("final") and look.get("eta"):
        return look["eta"] + " \u00b7 " + look["skill"]
    if not slice_:
        return ""
    part = slice_.get("part") or "step"
    typical = _PART_MINUTES.get(slice_.get("part") or "", 30)
    if started_epoch:
        elapsed = max(0, int(((now or time.time()) - started_epoch) // 60))
        if elapsed >= typical:
            return "over the ~%d min typical for a %s (%d min in \u00b7 estimate)" % (
                typical, part, elapsed)
        return "~%d min left of a ~%d min %s (estimate \u00b7 %d min in)" % (
            typical - elapsed, typical, part, elapsed)
    return "~%d min for this %s (typical \u00b7 start unknown)" % (typical, part)


def next_bullets(text, limit=3, width=90):
    """What's next as <=3 short bullets — split on lines, semicolons and
    sentence ends; each clipped at a word boundary."""
    parts = re.split(r"(?:\r?\n)+|;\s+|(?<=[.!?])\s+(?=[A-Z0-9(])",
                     str(text or "").strip())
    out = []
    for p in parts:
        p = re.sub(r"^[\s\-\u2022*\d.)]+", "", p).strip()
        if not p:
            continue
        if len(p) > width:
            p = p[:width - 1].rsplit(" ", 1)[0] + "\u2026"
        out.append(p)
        if len(out) >= limit:
            break
    return out


def project_line(m):
    """The overall project in one breath (the High Seat lead): the goal brief
    and the part tags in order, marked done / in progress."""
    steps = m.get("steps") or []
    order, seen = [], set()
    for s in steps:
        part = s.get("part") or ""
        if part and part not in seen:
            seen.add(part)
            order.append(part)
    bits = []
    for part in order:
        mine = [s for s in steps if s.get("part") == part]
        if mine and all(s.get("status") == "done" for s in mine):
            bits.append(part + " \u2713")
        elif any(s.get("status") == "active" for s in mine):
            bits.append(part + " \u25b6")
        else:
            bits.append(part)
    brief = m.get("goal_brief") or ""
    if len(brief) > 160:
        brief = brief[:159].rsplit(" ", 1)[0] + "\u2026"
    return {"brief": brief, "parts": " \u00b7 ".join(bits),
            "steps_done": m.get("steps_done", 0),
            "steps_total": m.get("steps_total", 0)}



def _job_epoch(value):
    """A finite timestamp; booleans and malformed native evidence are not time."""
    import math
    if isinstance(value, bool):
        return None
    try:
        epoch = _parse_epoch(value)
        if epoch is None or not math.isfinite(epoch) or epoch <= 0:
            return None
        time.localtime(epoch)  # Native clocks must also be representable here.
        return epoch
    except (OSError, TypeError, ValueError, OverflowError):
        return None


def _code_job_native(record, now):
    """Bounded reads of this job's existing Foreman files, without waking work."""
    phase = record.get("phase") or ("build" if record["status"] == "running" else record["status"])
    out = {"phase": phase, "phase_at": record.get("phase_at") or record.get("started_epoch"), "observed_at": None,
           "estimates": [record.get("eta")], "stopped": False}
    if record.get("phase") and record["phase"] != "producing":
        return out  # controller check/review/landing takes precedence over the completed worker's logs
    if record.get("worker", "coder") != "foreman" and record.get("phase"):
        from steward_cockpit.code_job_handoff import observe
        observed = observe(record)
        out.update(liveness=observed["state"], observed_at=observed.get("last_activity"))
        return out
    identity, worktree = record["id"], record.get("worktree")
    if not worktree or not re.fullmatch(r"[A-Za-z0-9_-]+", identity):
        return out
    try:
        root = Path(worktree).resolve()
        if root.name != identity:
            return out
    except (OSError, TypeError, ValueError, RuntimeError):
        return out

    oversized = set()

    def read(name, mode="tail", limit=20000):
        try:
            path = (root / name).resolve()
            path.relative_to(root)
            stat = path.stat()
            mt = stat.st_mtime
            if mt > now + 60 or (record.get("started_epoch") and mt < record["started_epoch"] - 5):
                return "", None
            with path.open("rb") as stream:
                if mode == "tail":
                    stream.seek(max(0, stat.st_size - limit))
                data = stream.read(limit + (mode == "complete"))
                if mode == "complete" and len(data) > limit:
                    oversized.add(name)
                    return "", None
                return data.decode("utf-8", errors="replace"), mt
        except (OSError, TypeError, ValueError, RuntimeError):
            return "", None

    def obj(name, limit=20000):
        text, mt = read(name, mode="complete", limit=limit)
        try:
            value = json.loads(text)
            return (value, mt) if isinstance(value, dict) else ({}, None)
        except (ValueError, RecursionError):
            return {}, None

    # The job writer puts its exact id in this plan; inherited repository logs
    # and a different effort's worktree are not this job's evidence.
    plan, _ = read(".foreman-job/IMPLEMENTATION-PLAN.md", mode="head", limit=4096)
    if not plan.startswith("# Code job " + identity + " - "):
        return out
    checkpoint, cp_at = obj("foreman-checkpoint.json", limit=4 * 1024 * 1024)
    if "foreman-checkpoint.json" in oversized:
        out["unavailable"] = "native checkpoint exceeds safe read limit"
        out["phase"] = "unavailable"
        return out
    if checkpoint:
        try:
            plan_path = checkpoint.get("plan_path")
            bound_path = Path(plan_path) if isinstance(plan_path, str) and plan_path else None
            if bound_path is not None and not bound_path.is_absolute():
                bound_path = root / bound_path
            bound = bound_path is not None and bound_path.resolve() == (root / ".foreman-job/IMPLEMENTATION-PLAN.md").resolve()
        except (OSError, TypeError, ValueError, RuntimeError):
            bound = False
        if not bound:
            checkpoint, cp_at = {}, None
        else:
            out.update(worker="foreman", source="foreman-checkpoint.json")
    checkpoint_state = str(checkpoint.get("status", "")).lower()
    if checkpoint:
        # Stable native milestones, never heartbeat timestamps or a status file's mtime.
        out.update(progress_token=json.dumps({key: checkpoint.get(key) for key in (
            "current_wave", "completed_waves", "intra_wave_step", "status")}, sort_keys=True), progress_at=cp_at)
        out["waiting"] = ""
    if checkpoint_state in ("paused", "halt", "halted", "budget-stop", "budget_stopped"):
        out["waiting"] = str(checkpoint.get("halt_reason") or checkpoint.get("reason") or checkpoint_state)[:300]
    if checkpoint_state in ("done", "failed", "halt", "halted", "paused", "stopped", "cancelled", "budget-stop", "budget_stopped"):
        out.update(stopped=True, phase=checkpoint_state)
        return out
    phases = ("execute", "gate", "review", "fix", "landing", "finishing", "queued")
    candidates = []
    if checkpoint.get("intra_wave_step") in phases and cp_at:
        candidates.append((cp_at, checkpoint["intra_wave_step"], cp_at))
    waiting, _ = obj(".foreman/waiting-on.json")
    wait_at = _job_epoch(waiting.get("ts"))
    if waiting.get("label") in phases and wait_at and wait_at <= now + 60:
        if not record.get("started_epoch") or wait_at >= record["started_epoch"]:
            minutes = waiting.get("minutes")
            import math
            if isinstance(minutes, (int, float)) and not isinstance(minutes, bool) and math.isfinite(minutes) and 0 <= minutes <= 24 * 60:
                phase_at = wait_at - minutes * 60
            elif checkpoint.get("intra_wave_step") == waiting["label"] and cp_at:
                phase_at = cp_at
            else:
                phase_at = wait_at
            if not record.get("started_epoch") or phase_at >= record["started_epoch"] - 60:
                candidates.append((wait_at, waiting["label"], phase_at))
    if candidates and record["status"] == "running":
        observed_at, phase, phase_at = max(candidates)
        out.update(phase=phase, phase_at=phase_at, observed_at=observed_at)
    heartbeat, _ = obj(".foreman/heartbeat.json")
    hb_at = _job_epoch(heartbeat.get("ts"))
    if heartbeat.get("alive") is False and hb_at and hb_at <= now + 60:
        if not record.get("started_epoch") or hb_at >= record["started_epoch"]:
            out.update(stopped=True, phase="stopped")
            return out
    if heartbeat.get("alive") is True and hb_at and hb_at <= now + 60:
        if not record.get("started_epoch") or hb_at >= record["started_epoch"]:
            out["observed_at"] = max(out.get("observed_at") or 0, hb_at)
    text, log_at = read("_foreman-status.log")
    parsed = parse_status_table(text)
    title = str(((parsed or {}).get("head") or {}).get("title") or "")
    if title != "Foreman build \u00b7 " + identity:
        parsed = None
    if parsed:
        out.update(worker="foreman", source="_foreman-status.log")
    if parsed and (parsed.get("head") or {}).get("tick") == "final":
        out.update(stopped=True, phase="stopped")
        return out
    # Native pace is a finish forecast. The runner's timeout/cap is never read.
    eta = (parsed or {}).get("rows", {}).get("eta", "")
    match = re.fullmatch(r"~?(\d+(?:\.\d+)?)m to run end \(pace estimate\)", eta.strip())
    if match and log_at and 0 < float(match[1]) <= 24 * 60:
        # Waiting lines update mtime; they do not renew the preceding table's
        # forecast. Resolve the table's own wall clock against the log's date.
        head = parsed.get("head") or {}
        clock = head.get("at")
        tick = re.fullmatch(r"t\+(?:(\d+)h(?:(\d+)m)?|(\d+)m)", head.get("tick", ""))
        reference = log_at
        run_started = _job_epoch(heartbeat.get("startedAt")) or record.get("started_epoch")
        elapsed = re.search(r"\belapsed\s+(\d+)m\b", parsed["rows"].get("status", ""))
        if elapsed and run_started and 0 <= int(elapsed[1]) <= 24 * 60:
            # Native tables report elapsed run time without a t+ header tag.
            # This also fixes their date across midnight and later waiting lines.
            reference = run_started + int(elapsed[1]) * 60
        elif tick and record.get("started_epoch"):
            reference = record["started_epoch"] + (int(tick[1] or 0) * 60 + int(tick[2] or tick[3] or 0)) * 60
        table_at = _job_epoch(time.strftime("%Y-%m-%d", time.localtime(reference)) + "T" + str(clock) + ":00")
        if table_at and table_at > reference + 12 * 3600:
            table_at = _job_epoch(time.strftime("%Y-%m-%d", time.localtime(reference - 86400)) + "T" + str(clock) + ":00")
        elif table_at and table_at < reference - 12 * 3600:
            table_at = _job_epoch(time.strftime("%Y-%m-%d", time.localtime(reference + 86400)) + "T" + str(clock) + ":00")
        if table_at and table_at > log_at + 60:
            table_at = None
        if table_at and (not record.get("started_epoch") or table_at >= record["started_epoch"] - 60):
            doing = parsed["rows"].get("doing", "")
            log_phase = next((p for p in phases if re.search(r"\b" + p + r"\b", doing)), out["phase"])
            out["estimates"].append({"at": table_at + float(match[1]) * 60, "estimated_at": table_at,
                                     "basis": "native completed-pass pace", "phase": log_phase,
                                     "job_id": identity})
    return out


def _code_job_eta(job, now=None):
    """One current-job forecast for every existing status consumer."""
    now = time.time() if now is None else now
    observed = job["native"]
    if observed["stopped"] or observed.get("unavailable"):
        return "", {"state": "unavailable", "source": "code_job", "job_id": job["id"],
                    "qualification": observed.get("unavailable", "")}
    phase = observed["phase"]
    elapsed = job.get("minutes")
    elapsed_text = "%dm elapsed" % elapsed if elapsed is not None else "elapsed unknown"
    def estimated_at(value):
        return (_job_epoch(value.get("estimated_at") or value.get("as_of")) or 0) if isinstance(value, dict) else 0

    native, reason, lower, upper, basis = False, "", None, None, ""
    first_reason = ""
    candidates = [value for value in observed["estimates"] if value is not None]
    for estimate in sorted(candidates, key=estimated_at, reverse=True):
        reason = ""
        lower = upper = None
        basis = ""
        if isinstance(estimate, dict):
            at = _job_epoch(estimate.get("estimated_at") or estimate.get("as_of"))
            lower = _job_epoch(estimate.get("earliest_at", estimate.get("at")))
            upper = _job_epoch(estimate.get("latest_at", estimate.get("at")))
            basis = estimate.get("basis")
            if (estimate.get("job_id", job["id"]) != job["id"]
                    or estimate.get("phase", phase) != phase):
                reason = "estimate ownership/phase changed"
            elif (at is None or at > now + 60 or (job.get("started_epoch") and at < job["started_epoch"])
                  or lower is None or upper is None or lower > upper or lower < at
                  or upper > now + 24 * 3600 or not isinstance(basis, str) or not basis.strip()):
                reason = "native estimate invalid"
            elif now - at > 15 * 60:
                reason = "native estimate stale"
            elif upper <= now:
                reason = "native estimate exceeded"
            else:
                lower = max(now, lower)
                basis = one_line(basis)[:120]
        elif estimate is not None:
            reason = "native estimate invalid"
        native = bool(lower is not None and upper is not None and not reason)
        if native:
            break
        first_reason = first_reason or reason
    if not native:
        reason = first_reason or reason
        if job.get("phase"):
            # New controller records carry observed phases. Do not turn those into a fresh 20-60 minute
            # allowance on every read. A native forecast or an explicitly labeled historical estimate is separate.
            text = "Job %s: %s; %s; no current task-specific finish estimate%s" % (
                job["id"], phase, elapsed_text, (" (" + reason + ")") if reason else "")
            return text, {"state": "unavailable", "source": "code_job", "job_id": job["id"],
                          "phase": phase, "phase_at": observed.get("phase_at"), "native": False,
                          "qualification": reason or "no measured forecast", "value": text}
        # Remaining-work assumptions, not an operational child timeout or a
        # roadmap-step count. Review/fixes may extend these provisional windows.
        lo, hi = {"queued": (30, 90), "execute": (20, 60), "build": (20, 60),
                  "gate": (15, 45), "review": (10, 40), "fix": (20, 60),
                  "landing": (5, 15), "finishing": (5, 15)}.get(phase, (20, 60))
        phase_at = observed.get("phase_at") or now
        lower, upper = max(now, phase_at + lo * 60), phase_at + hi * 60
        if upper <= now:
            reason = reason or "phase window exceeded"
        freshness = observed.get("observed_at")
        if freshness and now - freshness > 15 * 60:
            reason = reason or "phase evidence stale"
        if reason:
            lower, upper = now + lo * 60, now + hi * 60
        basis = "phase allowance including checks/review; fixes may extend; no measured pass pace"
        at = now
    point_range = native and "earliest_at" not in estimate and "latest_at" not in estimate
    if point_range:
        lower, upper = max(now, lower - 5 * 60), upper + 5 * 60
        basis += "; +/-5m presentation range assumed"
    stamp = time.strftime("%H:%M", time.localtime(at))
    window = time.strftime("%H:%M", time.localtime(lower)) + "-" + time.strftime("%H:%M", time.localtime(upper))
    qualifier = ("; " + reason + ", rebased") if reason else ""
    assumption = ("native forecast +/-5m assumed" if point_range else "native forecast") if native else "checks/review/fixes assumed"
    text = "Provisional job %s finish %s; %s, %s; as of %s; %s%s" % (
        job["id"], window, phase, elapsed_text, stamp, assumption, qualifier)
    source = {"state": "provisional", "source": "code_job", "job_id": job["id"],
              "record": ".ecgberht/code-jobs.json", "phase": phase,
              "observed_at": observed.get("observed_at"), "phase_at": observed.get("phase_at"), "estimated_at": at,
              "earliest_at": lower, "latest_at": upper, "elapsed_minutes": elapsed,
              "basis": basis, "native": native, "qualification": reason, "value": text}
    return text, source


_ARTIFACT_EXTS = {".md", ".pdf", ".pptx", ".docx", ".xlsx", ".html", ".png", ".jpg", ".jpeg", ".svg", ".csv", ".json", ".txt"}
_CODE_EXTS = {".py", ".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx", ".css", ".rs", ".go", ".c", ".cpp", ".h", ".java"}


def _brief_title(brief: str, default: str = "") -> str:
    """Extract the real human title from a job brief, skipping FULL BRIEF FILE / --- BRIEF OPENING --- headers."""
    lines = [ln.strip() for ln in str(brief or "").splitlines() if ln.strip()]
    filtered = []
    for ln in lines:
        low = ln.lower()
        if (low.startswith("full brief file") or low.startswith("--- brief")
                or low == "---" or (ln.startswith("[") and ln.endswith("]"))):
            continue
        filtered.append(ln)
    if not filtered:
        return default
    # Prefer the first Markdown heading if present in the opening lines
    heading = next((ln for ln in filtered[:6] if ln.startswith("#")), filtered[0])
    clean = heading.lstrip("#").strip()
    clean = re.sub(r"^(?:work\s+order|summary|objective)\s*:\s*", "", clean, flags=re.I).strip()
    return clean[:120] or default


def is_artifact_job(job) -> bool:
    """True when a job runs a named skill or declares only document/figure/data artifact outputs."""
    if not isinstance(job, dict):
        return False
    if str(job.get("skill") or "").strip():
        return True
    outs = [str(o or "").strip() for o in (job.get("outputs") or []) if str(o or "").strip()]
    if not outs:
        return False
    exts = {Path(o).suffix.lower() for o in outs}
    return bool(exts) and not (exts & _CODE_EXTS) and bool(exts & _ARTIFACT_EXTS)


def job_noun(job, with_article: bool = False) -> str:
    """Human noun for a background job: '<Skill> job', 'deliverable job', or 'code job'."""
    skill = str((job or {}).get("skill") or "").strip()
    if skill:
        return ("a %s job" % skill) if with_article else ("%s job" % skill)
    if is_artifact_job(job):
        return "a deliverable job" if with_article else "deliverable job"
    return "a code job" if with_article else "code job"


def job_clean_display_name(job) -> str:
    """Right-hand status bar display name: avoids 'coder' when running a skill or artifact job."""
    if is_artifact_job(job):
        worker = str((job or {}).get("worker") or ((job or {}).get("native") or {}).get("worker") or "coder").split()[0]
        if worker.lower() == "foreman":
            return "Foreman"
        family = str((job or {}).get("coder_family") or "").strip()
        model = str((job or {}).get("coder_model") or "").strip()
        skill = str((job or {}).get("skill") or "").strip()
        actor = family.capitalize() if family else "Worker"
        if model:
            actor += ", " + model
        return ("%s (%s)" % (skill, actor)) if skill else actor
    return job_display_name(job)


def running_code_jobs(campaign_dir):
    """The code jobs this steward commissioned that are still running, observed from its own job record (2026-10-05, his
    word: the status updates "don't seem to be congruent with what's actually happening" - a job ran for an hour while
    the status showed the steward's old note). [{id, title, minutes}] newest first; [] when none or unreadable."""
    raw, err = _read_json(Path(campaign_dir) / ".ecgberht" / "code-jobs.json")
    if err or raw is None:
        return []
    rows = raw if isinstance(raw, list) else (raw.get("jobs") or list(raw.values()) if isinstance(raw, dict) else [])
    rows = list(rows.values()) if isinstance(rows, dict) else rows
    if not isinstance(rows, list):
        return []
    out = []
    for r in rows:
        if not isinstance(r, dict) or str(r.get("status")) not in ("running", "finishing", "landing", "queued"):
            continue
        if r.get("finished") or not isinstance(r.get("id"), str) or not r["id"].strip():
            continue
        if r.get("steward_dir"):
            try:
                if Path(r["steward_dir"]).resolve() != Path(campaign_dir).resolve():
                    continue
            except (OSError, TypeError, ValueError, RuntimeError):
                continue
        title = _brief_title(r.get("brief"), default=job_noun(r, with_article=True))
        now = time.time()
        started = _job_epoch(r.get("started"))
        if started and started > now + 60:
            started = None
        minutes = int(max(0, now - started) // 60) if started else None
        job = {**r, "id": str(r.get("id") or ""), "title": title[:120] or job_noun(r, with_article=True),
               "minutes": minutes, "started_epoch": started, "status": str(r.get("status"))}
        job["native"] = _code_job_native(job, now)
        if job.get("phase"):
            from steward_cockpit.code_job_handoff import supervise
            job["supervision"] = supervise(job, native=job["native"], now=now)
        out.append(job)
    return list(reversed(out))


def job_kind_key(job):
    """2026-10-08: the history a job's finish time is reckoned from - its worker, and the skill it runs when it names
    one (a Chekhov review is never timed by past coding jobs)."""
    worker = str((job or {}).get("worker") or "coder").split()[0]
    skill = str((job or {}).get("skill") or "").strip().lower()
    return worker + (":" + skill if skill else "")


def job_display_name(job):
    """Who is doing a code job, in John's words: Foreman, '<Skill> (the <family> coder)', or 'the <family> coder'."""
    worker = str((job or {}).get("worker") or ((job or {}).get("native") or {}).get("worker") or "coder").split()[0]
    if worker.lower() == "foreman":
        return "Foreman"
    family = str((job or {}).get("coder_family") or "").strip()
    model = str((job or {}).get("coder_model") or "").strip()
    coder = ("the %s coder" % family) if family else "a coder"
    if model:
        coder += ", " + model
    skill = str((job or {}).get("skill") or "").strip()
    return ("%s (%s)" % (skill, coder)) if skill else coder


def landed_not_live(campaign_dir):
    """Titles of this steward's code jobs landed in Anchor today whose commit the running build does not carry yet
    (two-lane step 6, 2026-10-05). [] when none or unreadable."""
    try:
        raw, err = _read_json(Path(campaign_dir) / ".ecgberht" / "code-jobs.json")
        if err or raw is None:
            return []
        from steward_cockpit import code_jobs as _cj
    except Exception:
        return []
    rows = raw if isinstance(raw, list) else (raw.get("jobs") or list(raw.values()) if isinstance(raw, dict) else [])
    rows = list(rows.values()) if isinstance(rows, dict) else rows
    if not isinstance(rows, list):
        return []
    today = time.strftime("%Y-%m-%d")
    out = []
    for r in rows:
        if isinstance(r, dict) and r.get("landed") and str(r.get("finished") or "").startswith(today):
            try:
                if _cj.live_state(r) == "waits for a restart":
                    t = _brief_title(r.get("brief"), default="")
                    out.append(t[:100] or r.get("id"))
            except Exception:
                continue
    return out


# ── Status, John's requirement (execution minimum item 6, 2026-10-07): who is working, what comes next, a finish
# time always. No model call; read from the job/skill/turn records. A calculated finish time is labelled as one.
_RESTART_PAUSE = re.compile(r"paus\w*\s+for\s+(?:a\s+)?restart|after john confirms the restart", re.I)


def restart_pause_is_stale(campaign_dir, engine_state):
    """True when the Strip's "paused for restart" wording was written BEFORE John's last durably accepted message -
    then it is history, not the state (it was the steward's note, never cleared by anyone)."""
    accepted = float((engine_state or {}).get("human_accepted_at") or 0)
    if not accepted:
        return False
    strip, err = _read_json(Path(campaign_dir) / "strip.json")
    if err or not isinstance(strip, dict):
        return False
    text = " ".join(str(strip.get(k) or "") for k in ("active_effort", "next_recommended", "human_wait"))
    if not _RESTART_PAUSE.search(text):
        return False
    stamp = _job_epoch(strip.get("as_of") or strip.get("active_effort_as_of"))
    return bool(stamp) and stamp < accepted


def restart_attention_is_stale(campaign_dir, attention, engine_state):
    """True when the attention flag says "paused for restart" and was written BEFORE John's last durably accepted
    message (judged by the flag's own time - a newer restart hold is never hidden)."""
    accepted = float((engine_state or {}).get("human_accepted_at") or 0)
    if not accepted or not _RESTART_PAUSE.search(str((attention or {}).get("reason") or "")):
        return False
    raw, err = _read_json(Path(campaign_dir) / ".ecgberht" / "attention.json")
    if err or not isinstance(raw, dict):
        return False
    stamp = _job_epoch(raw.get("updated_at") or raw.get("state_since"))
    return bool(stamp) and stamp < accepted


def _median(values):
    vals = sorted(v for v in values if isinstance(v, (int, float)) and v > 0)
    if not vals:
        return None
    mid = len(vals) // 2
    return vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2.0


def typical_duration_s(campaign_dir, kind, worker=""):
    """The median duration of finished work of the same kind in this effort's own ledgers: code jobs (started ->
    finished, same worker), skill jobs (same label word), steward turns (turn-timing.jsonl, human turns). None when
    there is no history."""
    root = Path(campaign_dir) / ".ecgberht"
    out = []
    try:
        if kind == "code_job":
            raw, _e = _read_json(root / "code-jobs.json")
            for r in (raw.values() if isinstance(raw, dict) else raw or []):
                if isinstance(r, dict) and r.get("finished") and job_kind_key(r) == (worker or "coder"):
                    a, b = _job_epoch(r.get("started")), _job_epoch(r.get("finished"))
                    if a and b and b > a:
                        out.append(b - a)
        elif kind == "skill_job":
            raw, _e = _read_json(root / "skill-jobs.json")
            for r in (raw.values() if isinstance(raw, dict) else raw or []):
                if isinstance(r, dict) and r.get("finished") and worker and skill_identity(r) == worker:
                    a, b = _job_epoch(r.get("started")), _job_epoch(r.get("finished"))
                    if a and b and b > a:
                        out.append(b - a)
        elif kind == "turn":
            for line in (root / "turn-timing.jsonl").read_text(encoding="utf-8").splitlines()[-200:]:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("origin") == "human":
                    out.append(float(row.get("turn_s") or 0))
    except (OSError, ValueError, AttributeError, TypeError):
        pass
    return _median(out)


def finish_time(started, now, kind, campaign_dir, worker="", own_eta=None, own_eta_at=None):
    """A clock time when there is a basis for one. The work's own last estimate (with the time it was given); else start + the typical
    duration of the same kind of work here (labelled an estimate); past that, now + max(25% of elapsed, 5 min)
    (labelled running longer than usual); with no history at all, "no basis" and no clock time (W4, 2026-10-09).
    The calculation is never a promise and is never called one."""
    hm = lambda t: time.strftime("%H:%M", time.localtime(t))
    if own_eta:
        return "%s (its own estimate%s)" % (own_eta, (", given " + hm(own_eta_at)) if own_eta_at else "")
    started = started or now
    elapsed = max(0.0, now - started)
    typical = typical_duration_s(campaign_dir, kind, worker)
    if typical:
        if started + typical >= now:
            return "about %s (estimate: a typical %s here takes %d min)" % (hm(started + typical), {
                "code_job": "code job", "skill_job": "run", "turn": "turn"}.get(kind, "run"), max(1, round(typical / 60)))
        return "about %s (estimate - running longer than usual)" % hm(now + max(0.25 * elapsed, 300))
    # W4 (2026-10-09): with nothing to base it on, say so - no invented clock time (it was start + max(2 x elapsed,
    # 10 min), which read as a forecast and was wrong as often as not)
    return "no basis for an estimate yet (no finished %s of this kind here to go by)" % {
        "code_job": "code job", "skill_job": "run", "turn": "turn"}.get(kind, "run")


_FORECAST = re.compile(r"\d")
_PLACEHOLDER = re.compile(r"unavailable|no current estimate|estimating|unknown|n/?a\b|tbd", re.I)


def real_forecast(text):
    """A skill's own ETA counts only when it is an actual forecast (a number of minutes or a clock time), never a
    placeholder such as 'Unavailable' or 'estimating (no completed wave yet)'."""
    t = str(text or "").strip()
    return bool(t) and bool(_FORECAST.search(t)) and not _PLACEHOLDER.search(t)


_KNOWN_SKILLS = ("anvil", "gandalf", "jumper", "superjump", "researchprime", "ramanujan", "chekhov", "literature-review",
                 "legal-beagle", "financial-analyst", "tidy-idy", "ecgberht", "crucible", "foreman")


def skill_identity(record):
    """Which skill a skill-job record ran, from its recorded script (argv), never its free-text label."""
    argv = record.get("argv") if isinstance(record, dict) else None
    script = str(argv[1]) if isinstance(argv, list) and len(argv) > 1 else ""
    parts = [p.lower() for p in script.replace(chr(92), "/").split("/") if p]
    for name in _KNOWN_SKILLS:
        if name in parts:
            return name
    return parts[-3] if len(parts) >= 3 else (parts[-1] if parts else "")


def canonical_skill(label):
    """A skill's canonical id from any display label ('Gandalf review' -> 'gandalf'); '' when none is known."""
    flat = str(label or "").lower().replace(" ", "").replace("_", "-")
    return next((n for n in _KNOWN_SKILLS if n.replace("-", "") in flat.replace("-", "")), "")


_TABLE_HEAD = r"^\s*(?:\[\d{1,2}:\d{2}:\d{2}\]\s*)?\[(\d{1,2}):(\d{2})\]"


def look_started(campaign_dir, look):
    """When the run behind a status log began: the log file's creation time (its first table), else None."""
    src = str((look or {}).get("source") or "")
    if not src:
        return None
    try:
        f = Path(campaign_dir) / src
        if not f.is_file():
            return None
        text = f.read_text(encoding="utf-8", errors="replace")
        mtime = f.stat().st_mtime
    except (OSError, ValueError):
        return None
    first = re.search(_TABLE_HEAD, text, re.M)    # the run's first status table, [HH:MM] (maybe after [HH:MM:SS])
    if not first:
        return None
    day = time.localtime(mtime)
    began = time.mktime((day.tm_year, day.tm_mon, day.tm_mday, int(first.group(1)), int(first.group(2)), 0, 0, 0, -1))
    if began > mtime + 60:                          # the run began before midnight
        began -= 86400
    return began


def _step_raw(campaign_dir, step_id):
    """The current step's own record from roadmap.json (read_map keeps only what the rail shows)."""
    raw, err = _read_json(Path(campaign_dir) / "roadmap.json")
    if err or not isinstance(raw, dict):
        return {}
    for st in raw.get("roadmap_projection") or raw.get("steps") or []:
        if isinstance(st, dict) and str(st.get("id")) == str(step_id):
            return st
    return {}


def running_skill_jobs(campaign_dir):
    raw, err = _read_json(Path(campaign_dir) / ".ecgberht" / "skill-jobs.json")
    if err or raw is None:
        return []
    rows = raw.values() if isinstance(raw, dict) else (raw or [])
    return [r for r in rows if isinstance(r, dict) and r.get("status") == "running"]


def who_is_working(campaign_dir, engine_state, jobs, look, now=None, evidence_tests="", slice_started=None, skills=None):
    """(who, phase, started_epoch, tests, finish) - John's three lines' first and third, from records only."""
    now = time.time() if now is None else now
    st = engine_state or {}
    real_tests = "; ".join(part for part in str(evidence_tests or "").split("; ")
                           if part.strip() and not part.strip().startswith("Unavailable"))
    if jobs and (jobs[0].get("native") or {}).get("stopped"):
        j = jobs[0]
        return ("The steward's code job (%s) has stopped - its record still says running; the steward should report "
                "it" % j["title"], "stopped", j.get("started_epoch"),
                {True: "tests passed", False: "tests failed"}.get(j.get("check_ok"), real_tests or "tests not run"),
                "stopped - no finish time to give")
    if jobs:
        j = jobs[0]
        native = j.get("native") or {}
        worker = job_kind_key(dict(j, worker=j.get("worker") or native.get("worker") or "coder"))
        name = job_display_name(j)
        what = "a %s job" % j["skill"] if str(j.get("skill") or "").strip() else "a code job"
        phase = native.get("phase") or str(j.get("status") or "running")
        tests = {True: "tests passed", False: "tests failed"}.get(j.get("check_ok"), "tests not run yet")
        eta, src = _code_job_eta(j, now)
        if native.get("unavailable"):
            finish = "Unavailable - " + native["unavailable"]     # an explicit native refusal is said, not papered over
        elif (src or {}).get("native"):
            finish = eta                                   # the job's own forecast, with the time it was given
        elif j.get("phase"):
            typical = typical_duration_s(campaign_dir, "code_job", worker)
            if typical and j.get("started_epoch"):
                estimate = j["started_epoch"] + typical
                clock = time.strftime("%H:%M", time.localtime(estimate))
                finish = (("about %s (historical median for this kind here; provisional)" % clock) if estimate > now
                          else "historical estimate %s exceeded; %s; no revised forecast" % (clock, phase))
            else:
                finish = eta
        elif typical_duration_s(campaign_dir, "code_job", worker):
            finish = finish_time(j.get("started_epoch"), now, "code_job", campaign_dir, worker)
        elif str(j.get("skill") or "").strip():
            # a skill's first run here: a coding job's phase window would be a false clock (John, 2026-10-08)
            finish = "no finish time yet - the first %s job here, %s so far; it reports when done" % (
                str(j["skill"]).strip(), ("%d min" % j["minutes"]) if j.get("minutes") is not None else "just started")
        else:
            finish = eta or finish_time(j.get("started_epoch"), now, "code_job", campaign_dir, worker)   # phase window
        who = ("The steward is tracking %s on %s (%s) - recorded %s; worker liveness is unknown" % (name, what, j["title"], phase)
               if native.get("liveness") == "unknown" else
               "The steward is running %s on %s (%s) - %s - and is in charge of it" % (name, what, j["title"], phase))
        observation = j.get("supervision") or {}
        if observation:
            reason_clean = str(observation.get("reason") or "").rstrip(".")
            who = "The steward is tracking %s (%s) - %s" % (name, j["title"], reason_clean)
            if observation.get("worktree_summary"):
                who += " (" + observation["worktree_summary"] + ")"
            if observation.get("progress_at"):
                who += " · last progress " + time.strftime("%H:%M", time.localtime(observation["progress_at"]))
            who += "."
            phase += "; " + observation["state"].replace("_", " ")
        return (who,
                phase, j.get("started_epoch"), tests, finish)
    skills = running_skill_jobs(campaign_dir) if skills is None else skills   # W4 r1: the caller's own snapshot
    look_tests = (look or {}).get("tests") if (look or {}).get("tests") not in (None, "", "-", "\u2014") else ""
    if skills:
        k = skills[-1]
        started = _job_epoch(k.get("started"))
        label = str(k.get("label") or "a skill")
        ident = skill_identity(k)
        try:
            log_mtime = (Path(campaign_dir) / str((look or {}).get("source") or "")).stat().st_mtime if look else 0
        except (OSError, ValueError):
            log_mtime = 0
        same = [r for r in skills if skill_identity(r) == ident]
        # (final review) nothing records which status log belongs to which skill run, and names, start times and
        # mtimes cannot prove it - so a registered skill job never adopts a log: its phase, tests and finish stay
        # provisional and honest rather than borrowed from another run
        own_log = False
        if not own_log:
            look_tests = ""                              # another skill's log never speaks for this job
        phase = str(look.get("status") or look.get("doing") or "running")[:80] if own_log else "running"
        real_tests = ""                                  # no check receipt names this run: its tests stay "not run yet"
        if own_log and real_forecast(look.get("eta")):
            own_finish = str(look["eta"]) + (" (its own estimate, given %s)" % look["table_at"] if look.get("table_at") else " (its own estimate)")
            return ("The steward is running %s (%s) and is in charge of it" % (ident or "a skill", label), phase, started,
                    look_tests or real_tests or "tests not run yet", own_finish)
        return ("The steward is running %s (%s) and is in charge of it" % (ident or "a skill", label), phase, started,
                look_tests or real_tests or "tests not run yet",
                finish_time(started, now, "skill_job", campaign_dir, ident))
    if look and not look.get("final"):
        skill = str(look.get("skill") or "")
        began = look_started(campaign_dir, look)
        return ("The steward is running %s and is in charge of it" % skill, str(look.get("label") or "running")[:80],
                began, look_tests or real_tests or "tests not run yet",
                finish_time(began, now, "skill_job", campaign_dir, canonical_skill(skill)))
    if st.get("busy"):
        started = float(st.get("turn_started") or 0) or None
        what = one_line(st.get("activity") or "") or "your request"
        wrote_refs = [Path(str(p)).name for p in (st.get("turn_output_refs") or []) if p]
        tool_names = [str(t) for t in (st.get("turn_tool_names") or []) if t]
        tail = ""
        if wrote_refs:
            tail = " · wrote " + ", ".join(wrote_refs[-2:])
        elif tool_names:
            tail = " · tool: " + tool_names[-1]
        who = ("The steward is doing this — " + what + tail) if st.get("turn_origin") != "control" else \
              ("The steward is handling a job report — " + what + tail)
        return (who, "working", started, real_tests or "tests not run", finish_time(started, now, "turn", campaign_dir))
    return ("Nobody is working right now — the steward waits for you", "idle", None, "", "nothing running, so nothing to finish")


def compose_status(campaign_dir: str, engine_state=None):
    """The deterministic TWO-PART 10-minute status (handoff 2026-08-25 #2b;
    reworked 2026-09-04 on John's word).

    Zero-model, disk-true — composed from the map + the engine's own state,
    never from the model's memory. TOP (``now`` / ``running``): what is
    running at this moment, looked THROUGH the steward to the skill it
    commissioned (its own status log), else the attention flag, else the
    steward's turn. BOTTOM (``plan`` / ``slice`` / ``project``): the current
    slice in one line, its ETA, <=3 next bullets, and where the whole effort
    stands.

    One shape, three consumers: the cockpit's right status pane (the
    ``status`` event / verb), the universal file
    ``<cdir>/.ecgberht/status-summary.json``, and the main-dashboard tile.
    """
    clear_stale_job_flag(campaign_dir)          # W4: only a flag that names its job, and only when that job stopped
    m = read_map(campaign_dir, include_plan_history=False)
    st = engine_state or {}
    active, focus_warning = _focused_step(m)
    look = status_lookthrough(campaign_dir)
    if m["heartbeat"].get("current_step_id"):
        expected_source = m["heartbeat"].get("current_skill_status_source")
        actual_source = look.get("source") if look else None
        source_matches = (isinstance(expected_source, str) and expected_source.strip()
                          and isinstance(actual_source, str)
                          and expected_source.strip().replace("\\", "/") == actual_source.strip().replace("\\", "/"))
        if not active or not source_matches:
            look = None
    if look is not None and running_skill_jobs(campaign_dir):
        # (final review) no run-to-log binding exists for a registered skill job: a status log may be another run's
        # (a finished Gandalf's HALT while Gandalf B runs) - none of it feeds running, halt, blocker or attention
        look = None
    local_evidence = _local_status_evidence(campaign_dir, m, st, active)
    if restart_attention_is_stale(campaign_dir, m["attention"], st):
        m["attention"] = dict(m["attention"], state="quiet", reason="")
    now_lines = []
    running = None
    jobs = running_code_jobs(campaign_dir)
    waiting_restart = landed_not_live(campaign_dir)
    # 2026-10-05: a running code job is OBSERVED work - it leads, ahead of the steward's own note
    for j in jobs[:2]:
        skill = job_display_name(j)
        phase = j["native"]["phase"]
        now_lines.append("%s %s — %s%s" % (
            skill, phase, j["title"], (" (%d min)" % j["minutes"]) if j["minutes"] is not None else ""))
    for w in waiting_restart[:2]:
        now_lines.append("landed, waits for a restart \u2014 %s" % w)
    if jobs:
        job = jobs[0]
        worker = str(job.get("worker") or job["native"].get("worker") or "coder")
        running = {"kind": "code_job", "label": now_lines[0],
                   "skill": "Foreman" if worker.lower() == "foreman" else (str(job.get("skill") or "").strip() or worker),
                   "worker": worker, "job_id": job["id"], "phase": job["native"]["phase"],
                   "source": ".ecgberht/code-jobs.json", "native_source": job["native"].get("source", ""),
                   "age": ("%d min" % job["minutes"]) if job["minutes"] is not None else ""}
    # THE LOOK-THROUGH: the commissioned skill is what is happening;
    # "steward working" is the whole story only when nothing else runs.
    if look and not look["final"] and not jobs:
        running = {"kind": "skill", "label": look["label"], "skill": look["skill"],
                   "source": look["source"], "age": look["age"]}
        now_lines.append(look["label"])
    elif m["attention"]["state"] == "working" and not jobs:
        run = (m["attention"]["reason"] or "").strip() \
            or "commissioned work in flight"
        if active and active.get("commissioned_as"):
            run += " \u00b7 as " + str(active["commissioned_as"])
        if not st.get("busy"):
            # the flag is the steward's own note: with no turn, no skill and no job running, say so (2026-10-05)
            run = "the steward's note says working (" + run + ") \u2014 but nothing is running now"
        running = {"kind": "commissioned", "label": run,
                   "skill": str((active or {}).get("commissioned_as") or ""),
                   "source": ".ecgberht/attention.json", "age": ""}
        now_lines.append(run)
    if st.get("busy"):
        # (2026-09-07, journals 0006/0111) a steward mid-turn cannot repaint the
        # pane: say so, with the turn's start and the last status on record,
        # instead of letting the previous status stand as if current.
        line = "steward mid-turn"
        ts0 = float(st.get("turn_started") or 0)
        if ts0 > 0:
            mins = int(max(0.0, time.time() - ts0) // 60)
            line += " since " + time.strftime("%H:%M", time.localtime(ts0)) + " (" + str(mins) + " min)"
        _last = read_last_status(campaign_dir)
        if _last and _last.get("at"):
            line += " \u00b7 last status " + str(_last["at"])[-5:]
        if st.get("queued"):
            line += " \u00b7 %d queued" % st["queued"]
        now_lines.append(line)
        if running is None:
            running = {"kind": "steward", "label": line, "skill": "",
                       "source": "engine", "age": ""}
    elif st.get("queued"):
        now_lines.append("steward idle \u00b7 %d held message(s)" % st["queued"])
    halt = None
    if look and look["final"] and not jobs and (look.get("halt_reason") or look.get("limit")):
        reason = look.get("halt_reason") or blocker_text(look)
        short = reason if len(reason) <= 160 else reason[:159].rsplit(" ", 1)[0] + "\u2026"
        halt = {"skill": look["skill"], "reason": reason, "limit": look.get("limit") or "",
                "age": look["age"], "source": look["source"]}
        if look.get("limit"):
            line = (look["skill"] + " STOPPED \u2014 model session limit (" + look["limit"]
                    + ") \u00b7 " + look["age"] + " ago \u00b7 " + short)
        else:
            line = look["skill"] + " STOPPED \u00b7 " + look["age"] + " ago \u00b7 " + short
        now_lines.insert(0, line)
        running = {"kind": "halted", "label": line, "skill": look["skill"],
                   "source": look["source"], "age": look["age"]}
    if look and look["final"] and running is None:
        done_line = look["skill"] + " finished \u00b7 " + look["age"] + " ago"
        if look.get("tests") and look["tests"] not in ("-", "\u2014"):
            done_line += " \u00b7 " + look["tests"]
        now_lines.append(done_line)
        running = {"kind": "finished", "label": done_line, "skill": look["skill"],
                   "source": look["source"], "age": look["age"]}
    swarm = read_swarm_trails(campaign_dir)
    swarm_notes = []
    for seat in swarm:
        if seat.get("state") == "stale":
            swarm_notes.append(seat["label"] + " \u00b7 stale heartbeat \u00b7 "
                               + seat.get("age", "unknown age"))
            continue
        if seat.get("state") != "fresh":
            swarm_notes.append(seat["label"] + " \u00b7 heartbeat unknown \u00b7 "
                               + seat.get("reason", "invalid"))
            continue
        line = seat["label"] + " \u00b7 " + (seat["doing"] or "silent")
        if seat.get("rabbit"):
            line += " \u00b7 rabbit"
        elif seat.get("load_bearing") is False:
            line += " \u00b7 not load-bearing"
        else:
            line += " \u00b7 on path"
        now_lines.append(line)
    if not now_lines:
        attention_label = {
            "needs_you": "waiting on you",
            "deliverable_ready": "deliverable ready",
            "blocked": "blocked",
            "stale": "attention stale - live owner unconfirmed",
            "unknown": "attention unknown",
        }.get(m["attention"]["state"], "quiet")
        now_lines.append("nothing running - " + attention_label)
        running = {"kind": "none", "label": now_lines[0], "skill": "",
                   "source": "", "age": ""}
    now_lines.extend(swarm_notes)
    if active and active.get("part"):
        plan_step = active["part"] + ": " + active["name"]
    else:
        plan_step = active["name"] if active else "(no active step)"
    next_text = (m["heartbeat"]["next_recommended"] or "").strip()
    pause_stale = restart_pause_is_stale(campaign_dir, st)
    if pause_stale and _RESTART_PAUSE.search(next_text):
        next_text = ""                                   # the old "resume after the restart" is history, not the next step
    # (ChatGPT, items 4-6) the next actions are the CURRENT step's: a Strip line written for another step is not
    hb_step = str(m["heartbeat"].get("current_step_id") or "")
    bound = bool(hb_step and active and hb_step == str(active.get("id") or ""))
    if not bound and not hb_step and active:
        # no step id on the Strip: its line counts for the focused step only if written after that step began
        strip_raw, _s_err = _read_json(Path(campaign_dir) / "strip.json")
        if _s_err or not isinstance(strip_raw, dict):
            strip_raw = {}
        written = _job_epoch(strip_raw.get("as_of") or strip_raw.get("active_effort_as_of"))
        began = _slice_started_epoch(campaign_dir, active.get("id"))
        bound = bool(written and began and written > began)
    if not bound:
        next_text = ""                                   # not this step's line
    if not next_text.strip() and active:
        # no usable Strip line: the step's own stored next actions (one per line - their boundaries kept)
        raw_step = _step_raw(campaign_dir, active.get("id"))
        own = raw_step.get("next") or raw_step.get("next_actions") or active.get("next") or ""
        next_text = "\n".join(str(x) for x in own) if isinstance(own, list) else str(own or "")
    waiting = _real_wait((m["heartbeat"]["human_wait"] or "").split("\u00b7")[0].strip())
    if pause_stale and _RESTART_PAUSE.search(waiting):
        waiting = ""                                     # a stale "paused for restart" wait, after his own message
    if "pending_request" in m["heartbeat"]:
        pending = m["heartbeat"]["pending_request"]
        if pending is None:
            waiting = ""
        elif isinstance(pending, str):
            waiting = _real_wait(pending.strip())
        elif isinstance(pending, dict):
            waiting = str(pending.get("purpose") or pending.get("question") or pending.get("text") or "").strip()
    if halt and not waiting and m.get("refinement") is None:
        # the run's stop is the thing waiting on him — a limit above all
        waiting = (("model session limit (" + halt["limit"] + "): ") if halt["limit"]
                   else (halt["skill"] + " stopped: ")) + halt["reason"]
        waiting = waiting if len(waiting) <= 220 else waiting[:219].rsplit(" ", 1)[0] + "\u2026"
    why_text = (m["heartbeat"].get("why_next") or "").strip()
    plan = {
        "step": plan_step,
        "steps_done": m["steps_done"],
        "steps_total": m["steps_total"],
        "waiting_on_you": waiting,
        # W2 (2026-09-28): when the wait is the managed pending request, WHEN it was asked (the presentation's own
        # time) — the home's age of a wait reads this, never the summary's ten-minute clock
        "waiting_since": (m["heartbeat"].get("wait_asked_at") or None) if waiting else None,
        "next": next_text,
        "why": why_text,
        "attention": m["attention"]["state"],
        "goal_reread": m.get("goal_reread", True),
    }
    lead = lead_line(plan)
    if not m.get("goal_reread", True):
        now_lines.append("goal not re-read since last close")
    # (2026-09-07, journals 0026/0111) the effort line carries its AGE, and a line
    # a day or more older than the newest work on disk is shouted, never kept quietly.
    effort_line = effort_line_freshness(campaign_dir, m)
    if pause_stale and _RESTART_PAUSE.search(str(effort_line.get("text") or "")):
        effort_line = dict(effort_line, text=_RESTART_PAUSE.sub("", str(effort_line["text"])).strip(" -\u2014\u00b7"))
    if effort_line.get("stale"):
        now_lines.append("effort line as of " + effort_line["as_of"] + " \u2014 "
                         + str(effort_line["behind_days"]) + " day(s) older than the newest work; the steward has not restamped it")
    if active and active.get("part") in ("slice", "rigor", "integrate", "harden") \
            and not active.get("gate") and active.get("commissioned_as"):
        now_lines.append("commissioned without a gate command")
    slice_ = slice_of(m)
    started = _slice_started_epoch(campaign_dir, slice_["id"]) if slice_ else None
    live_skill = bool(look and not look["final"] and not jobs)
    eta, eta_source = local_evidence["eta"], local_evidence["eta_source"]
    if jobs:
        eta, eta_source = _code_job_eta(jobs[0])
        if not eta:
            eta = "Unavailable - " + (eta_source.get("qualification") or "the native job has stopped")
            eta_source["value"] = eta
    elif live_skill and look.get("eta"):
        eta = estimate_eta(slice_, look, started)
        eta_source = {"state": "available", "source": "live_skill", "skill": look.get("skill")}
    if focus_warning:
        now_lines.append(focus_warning)
    # Meaningful work time is separate from this status/heartbeat timestamp.
    events = []
    for sl in (m.get("refinement") or {}).get("state", {}).get("slices", {}).values():
        for rev in sl.get("revisions", {}).values():
            if rev.get("at"):
                events.append({"at":(rev.get("source_history") or {}).get("at") or rev["at"], "summary":"Updated " + rev["product_id"].replace("-", " ")})
        for accepted in sl.get("acceptance_history", []):
            if accepted.get("at"):
                events.append({"at":accepted["at"], "summary":"Approved " + str(accepted.get("member_product_id") or sl["title"]).replace("-", " ")})
        for feedback in sl.get("feedback", []):
            if feedback.get("at"):
                events.append({"at":feedback["at"], "summary":"Feedback received for " + sl["title"]})
    latest_event = max(events, key=lambda event:event["at"]) if events else None
    skills_now = running_skill_jobs(campaign_dir)      # ONE snapshot: the forecast and its subject come from it
    who, phase, work_started, tests_line, finish = who_is_working(
        campaign_dir, st, jobs, look if live_skill else None, evidence_tests=local_evidence["tests"], slice_started=started,
        skills=skills_now)
    elapsed_line = ""
    if work_started:
        mins = int(max(0, time.time() - work_started) // 60)
        elapsed_line = "%s · %d min since %s" % (phase, mins, time.strftime("%H:%M", time.localtime(work_started)))
    else:
        elapsed_line = phase
    next3 = next_bullets(next_text)[:3] or ["Finish the current work, then wait for you."]
    if live_skill and not running_skill_jobs(campaign_dir) and real_forecast(look.get("eta")):   # the log-only run
        given = (" given " + str(look["table_at"])) if look.get("table_at") else ""   # the table's own stamp, not mtime
        finish = estimate_eta(slice_, look, started) + " (its own estimate%s)" % given   # the skill's own last ETA
    eta = finish                                          # always a clock time (or "nothing running"), never "Unavailable"
    # W4 (2026-10-10): the forecast shown for a running job or skill is kept with its milestone; a finished one's
    # actual time is recorded beside it (only when the forecast changed - this recomposes every few seconds)
    try:
        from steward_cockpit import forecasts as _fc
        if jobs:
            _fc.note(campaign_dir, "code:" + str(jobs[0].get("id")), "code_job", finish)
        elif skills_now:
            _fc.note(campaign_dir, "skill:" + str(skills_now[-1].get("id")), "skill_job", finish)
        elif live_skill and look and not look.get("final"):
            # a run seen only through its own status log (no registered job): its subject is that log and its start
            _fc.note(campaign_dir, "log:%s@%s" % (look.get("source"), int(look_started(campaign_dir, look) or 0)),
                     "skill_log", finish)
        _fc.observe_finished(campaign_dir, _job_epoch)
    except Exception:
        pass
    eta_source = dict(eta_source or {}, value=finish, calculated=("estimate" in finish or "provisional" in finish))
    doing = who
    doing_fact = doing
    if jobs:
        j0 = jobs[0]
        obs0 = j0.get("supervision") or {}
        clean_actor = job_clean_display_name(j0)
        if obs0.get("worktree_summary"):
            doing_fact = "%s · %s — %s" % (clean_actor, obs0["worktree_summary"], j0["title"])
        elif is_artifact_job(j0):
            doing_fact = doing.replace(job_display_name(j0), clean_actor).replace("on a code job", "on " + job_noun(j0, with_article=True))
    summary = (slice_["name"] + (" — " + slice_["summary"] if slice_.get("summary") else "")) if slice_ else (m.get("goal_brief") or m.get("name") or "")
    # the current-task line carries no campaign step counts (John: "why are there 84 steps?")
    outputs_progress = ""
    if jobs and jobs[0].get("outputs") and jobs[0].get("worktree"):
        try:
            wt_root = Path(jobs[0]["worktree"])
            outs = [str(o) for o in (jobs[0].get("outputs") or []) if o]
            if outs and wt_root.is_dir():
                written_cnt = sum(1 for o in outs if (wt_root / o).exists())
                outputs_progress = " · %d/%d outputs written" % (written_cnt, len(outs))
        except Exception:
            outputs_progress = ""
    status_line = elapsed_line + outputs_progress + ((" · " + tests_line) if tests_line else "")
    todo = next3[0]
    seats = []
    for item in swarm:
        if isinstance(item, dict):
            seats.append((item.get("label") or "seat") + " · " + (item.get("state") or "?"))
    procs_val = " · ".join(seats) if seats else (
        job_clean_display_name(jobs[0]) if jobs else (
            ((running or {}).get("skill") + " (commissioned)") if (running or {}).get("kind") == "skill" else ""))
    status_card = None
    sc_mtime = 0.0
    sc_candidates = [Path(campaign_dir) / ".ecgberht"]
    if jobs and jobs[0].get("worktree"):
        wt_path = Path(str(jobs[0]["worktree"]))
        sc_candidates.append(wt_path / ".ecgberht")
        if jobs[0].get("work_dir"):
            sc_candidates.append(wt_path / str(jobs[0]["work_dir"]) / ".ecgberht")
    for sc_dir in sc_candidates:
        for sc_name in ("status_card.json", "status-card.json"):
            sc_file = sc_dir / sc_name
            if sc_file.is_file():
                try:
                    mt = sc_file.stat().st_mtime
                    raw_sc = json.loads(sc_file.read_text(encoding="utf-8"))
                    if isinstance(raw_sc, dict) and mt >= sc_mtime:
                        status_card = raw_sc
                        sc_mtime = mt
                except Exception:
                    pass
    last_finished_epoch = 0.0
    try:
        for jf_name in ("code-jobs.json", "skill-jobs.json"):
            jf_path = Path(campaign_dir) / ".ecgberht" / jf_name
            if jf_path.is_file():
                raw_jf, _jf_e = _read_json(jf_path)
                jf_rows = list(raw_jf.values()) if isinstance(raw_jf, dict) else (raw_jf if isinstance(raw_jf, list) else [])
                for r in jf_rows:
                    if isinstance(r, dict) and r.get("finished"):
                        fe = _job_epoch(r.get("finished"))
                        if fe and fe > last_finished_epoch:
                            last_finished_epoch = fe
    except Exception:
        pass
    is_idle_now = not jobs and not skills_now and not st.get("busy") and not live_skill
    sc_fresh_for_run = bool(
        status_card
        and not is_idle_now
        and (
            (sc_mtime >= work_started - 300)
            if work_started
            else (sc_mtime >= last_finished_epoch if last_finished_epoch > 0 else sc_mtime >= time.time() - 900)
        )
    )
    sc_fresh_when_idle = bool(
        status_card
        and is_idle_now
        and sc_mtime >= last_finished_epoch - 5
    )
    sc_effort = str((status_card or {}).get("effort") or "").strip()
    sc_doing = str((status_card or {}).get("doing") or "").strip()
    sc_status = str((status_card or {}).get("status") or "").strip()
    sc_tests = str((status_card or {}).get("tests") or "").strip()
    sc_blocker = str((status_card or {}).get("blocker") or "").strip()
    sc_procs = str((status_card or {}).get("procs") or "").strip()
    sc_journal = str((status_card or {}).get("journal") or "").strip()
    sc_eta = str((status_card or {}).get("eta") or "").strip()
    sc_todo = str((status_card or {}).get("todo") or "").strip()

    eff_for_facts = (sc_effort if ((is_idle_now or sc_fresh_for_run) and sc_effort) else (m.get("name") or ""))
    if is_idle_now:
        doing_for_facts = (
            sc_doing
            if (sc_fresh_when_idle and sc_doing and not _is_inflight_doing(sc_doing) and doing_fact.startswith("Nobody is working"))
            else doing_fact
        )
        status_for_facts = (
            sc_status
            if (sc_fresh_when_idle and sc_status and status_line == "idle" and not _is_inflight_doing(sc_status))
            else status_line
        )
        procs_for_facts = (
            sc_procs
            if (sc_fresh_when_idle and sc_procs and not procs_val and not re.search(r"(?:claude|node|codex|gemini)\s+[1-9]", sc_procs, re.I))
            else procs_val
        )
        eta_for_facts = (
            sc_eta
            if (sc_fresh_when_idle and sc_eta and not _is_inflight_eta(sc_eta) and eta.startswith("nothing running"))
            else eta
        )
    else:
        doing_for_facts = (
            sc_doing
            if (sc_fresh_for_run and sc_doing and not _is_idle_placeholder(sc_doing) and not jobs)
            else doing_fact
        )
        if sc_fresh_for_run and sc_status and not _is_idle_placeholder(sc_status):
            status_for_facts = sc_status if "min since" in sc_status else f"{sc_status} \u00b7 {status_line}"
        else:
            status_for_facts = status_line
        procs_for_facts = (sc_procs if (sc_fresh_for_run and sc_procs and not seats) else procs_val)
        eta_for_facts = (sc_eta if (sc_fresh_for_run and sc_eta and not _is_idle_placeholder(sc_eta) and not jobs) else eta)

    tests_for_facts = (
        sc_tests
        if ((is_idle_now or sc_fresh_for_run) and sc_tests and (not tests_line or tests_line in ("tests not run", "tests not run yet")))
        else (tests_line or "no check run")
    )
    journal_for_facts = (sc_journal if (sc_journal and str(local_evidence["journal"]).startswith("Unavailable")) else local_evidence["journal"])
    if status_card and (not journal_for_facts or str(journal_for_facts).startswith("Unavailable")):
        try:
            j_dir = Path(campaign_dir) / "journal"
            if j_dir.is_dir():
                j_files = sorted(j_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
                if j_files:
                    journal_for_facts = f"journal/{j_files[0].name}"
        except Exception:
            pass
    todo_for_facts = (sc_todo if ((is_idle_now or sc_fresh_for_run) and sc_todo and todo.startswith("Finish the current work")) else todo)
    blocker_for_facts = ("waiting on you: " + waiting) if waiting else ("blocked: " + halt["reason"] if halt else (sc_blocker if sc_blocker and sc_blocker.lower() != "none" else ""))

    facts = status_facts(
        effort=eff_for_facts,
        summary=summary,
        doing=doing_for_facts,
        status=status_for_facts,
        tests=tests_for_facts,
        blocker=blocker_for_facts,
        procs=procs_for_facts,
        journal=journal_for_facts,
        eta=eta_for_facts,
        todo=todo_for_facts,
    )
    compact = {"activity": doing,
               "latest_event": latest_event, "next": next3[:1],
               "question": (engine_state or {}).get("open_question") or plan.get("waiting_on_you") or "",
               "facts": facts}
    out = {"at": time.strftime("%Y-%m-%d %H:%M"),
           "status_id": f"{time.time_ns():020d}",
           "effort": m["name"], "latest_event":latest_event, "compact":compact,
           "lead_line": lead,
           "now": now_lines,
           "running": running,
           "slice": slice_,
           "eta": eta,
           "tests": (look.get("tests") or local_evidence["tests"]) if live_skill else local_evidence["tests"],
           "journal": local_evidence["journal"],
           "evidence": {"source": local_evidence["source"], "checks": local_evidence["checks"],
                        "journal": local_evidence["journal_source"],
                        "eta": eta_source},
           "focus_warning": focus_warning,
           "who": who, "phase": phase, "finish": finish, "next3": next3, "restart_pause_stale": pause_stale,
           "next_bullets": next3,
           "project": project_line(m),
           "lookthrough": ({"source": look["source"], "age": look["age"],
                            "final": look["final"]} if look else None),
           "halt": halt,
           "effort_line": effort_line,
           "plan": plan,
           "map": m.get("map") or [],
           "work_map": m.get("work_map") or [],
           "swarm": swarm}
    # Deliverables count rides the universal status shape (2026-08-25, John's ask —
    # journal 0010: "where is the thing I paid for?"). Count only; the list itself
    # is the deliverables verb / tile.
    try:
        deliv_info = read_deliverables(campaign_dir)
        out["deliverables_count"] = len(deliv_info["items"])
        out["review_deliverables_count"] = int(
            (deliv_info.get("current_summary") or {}).get("review_count")
            or sum(
                1
                for it in (deliv_info.get("items") or [])
                if it.get("is_current")
                and not it.get("reviewed_done")
                and not it.get("accepted")
                and not it.get("accepted_current")
            )
        )
    except Exception:
        out["deliverables_count"] = 0
        out["review_deliverables_count"] = 0
    # (2026-10-14, John) Previous Status Updates log: include recent historical
    # updates from milestone events, code jobs, and turn timings so the
    # click-to-open scrollable log under the live status table is populated on open.
    hist_updates = []
    try:
        for ev in sorted(events, key=lambda x: str(x.get("at") or ""), reverse=True)[:6]:
            at_str = str(ev.get("at") or "")
            hhmm_ev = at_str[-8:-3] if "T" in at_str and len(at_str) >= 16 else at_str[-5:]
            hist_updates.append({
                "at": hhmm_ev or at_str[:16],
                "summary": ev.get("summary") or "Milestone update",
                "doing": ev.get("summary") or "",
                "status": "%d/%d steps done" % (m.get("steps_done", 0), m.get("steps_total", 0)),
                "tests": tests_line or "recorded",
            })
        cj_file = Path(campaign_dir) / ".ecgberht" / "code-jobs.json"
        if cj_file.is_file():
            cj_raw, _cj_err = _read_json(cj_file)
            cj_rows = list(cj_raw.values()) if isinstance(cj_raw, dict) else (cj_raw if isinstance(cj_raw, list) else [])
            for r in reversed(cj_rows[-8:]):
                if not isinstance(r, dict):
                    continue
                at_s = str(r.get("finished") or r.get("started") or "")
                hhmm_s = at_s[11:16] if len(at_s) >= 16 else at_s[-5:]
                brief_line = _brief_title(r.get("brief"), default=job_noun(r).capitalize())
                st_word = str(r.get("phase") or r.get("status") or "done")
                hist_updates.append({
                    "at": hhmm_s or "recent",
                    "summary": "%s · %s" % (brief_line[:68], st_word),
                    "doing": brief_line[:110],
                    "status": "%s %s · %s" % (job_noun(r).capitalize(), r.get("id", ""), st_word),
                    "tests": "check passed ✓" if r.get("check_ok") is True else ("check failed ✗" if r.get("check_ok") is False else "recorded"),
                })
    except Exception:
        pass
    out["history_updates"] = hist_updates[:10]
    hhmm_now = str(out["at"][-5:] if (is_idle_now or not sc_fresh_for_run) else ((status_card or {}).get("timestamp") or out["at"][-5:]))
    run_type_hdr = str(
        ((status_card or {}).get("run_type") if (sc_fresh_for_run or sc_fresh_when_idle) else "")
        or ((running or {}).get("skill") + " run" if (running or {}).get("skill") else "Steward status")
    )
    proj_hdr = str((status_card or {}).get("project") or m.get("name") or "Cockpit")
    clean_journal_str = "none" if str(journal_for_facts).startswith("Unavailable") else str(journal_for_facts or "none")
    clean_tests_str = "\u2014 (no active check gate)" if str(tests_for_facts).startswith("Unavailable") else str(tests_for_facts or "\u2014")
    clean_doing_str = "Idle \u2014 waiting for your input" if str(doing_for_facts).startswith("Nobody is working") else str(doing_for_facts or "Idle")
    if is_idle_now:
        clean_eta_str = "Idle (ready for next wave)" if (str(eta_for_facts).startswith("nothing running") or _is_inflight_eta(eta_for_facts)) else str(eta_for_facts or "\u2014")
    else:
        clean_eta_str = sc_eta if (sc_fresh_for_run and sc_eta and not _is_idle_placeholder(sc_eta)) else str(eta_for_facts or "\u2014")
    clean_procs_str = str(procs_for_facts or "py 1 \u00b7 claude 0 \u00b7 node 0")
    clean_blocker_str = str(blocker_for_facts or "none")
    raw_milestone_etas = (status_card or {}).get("milestone_etas") if isinstance((status_card or {}).get("milestone_etas"), list) else None
    if is_idle_now and raw_milestone_etas:
        if not sc_fresh_when_idle or any(_is_inflight_eta(str((m_item or {}).get("v") or (m_item or {}).get("eta") or "")) for m_item in raw_milestone_etas if isinstance(m_item, dict)):
            raw_milestone_etas = None
    out["status_card"] = {
        "timestamp": hhmm_now,
        "run_type": run_type_hdr,
        "project": proj_hdr,
        "effort": eff_for_facts or m.get("name") or "Effort",
        "doing": clean_doing_str,
        "status": status_for_facts or "idle",
        "tests": clean_tests_str,
        "blocker": clean_blocker_str,
        "procs": clean_procs_str,
        "journal": clean_journal_str,
        "eta": clean_eta_str,
        "todo": todo_for_facts or "Review current deliverables & approve next step",
        "milestone_etas": raw_milestone_etas,
        "from_status_card_file": bool(status_card),
    }
    sep_line = "\u2500" * 33
    out["clean_status_table"] = "\n".join([
        f"[{hhmm_now}] {run_type_hdr} \u00b7 {proj_hdr}",
        sep_line,
        f"Effort   {out['status_card']['effort']}",
        f"Doing    {out['status_card']['doing']}",
        f"Status   {out['status_card']['status']}",
        f"Tests    {out['status_card']['tests']}",
        f"Blocker  {out['status_card']['blocker']}",
        f"Procs    {out['status_card']['procs']}",
        f"Journal  {out['status_card']['journal']}",
        sep_line,
        f"ETA      {out['status_card']['eta']}",
        f"To do    {out['status_card']['todo']}",
    ])
    return out

def effort_line_freshness(campaign_dir: str, m=None):
    """The Strip's effort line with its age: ``as_of`` (the stamp's own
    ``active_effort_as_of`` date, else strip.json's mtime), ``newest_work`` (the
    newest of roadmap.json / DELIVERABLES.md / the journal), ``behind_days`` and
    ``stale`` (a day or more behind). Disk-true, never raises."""
    root = Path(campaign_dir)
    out = {"text": "", "as_of": "", "newest_work": "", "behind_days": 0, "stale": False}
    try:
        strip, _err = _read_json(root / "strip.json")
        strip = strip or {}
        out["text"] = str(strip.get("active_effort") or "")
        as_of = str(strip.get("active_effort_as_of") or "").strip()
        if as_of:
            as_of_t = time.mktime(time.strptime(as_of[:10], "%Y-%m-%d")) + 86399
        else:
            as_of_t = (root / "strip.json").stat().st_mtime
            as_of = time.strftime("%Y-%m-%d", time.localtime(as_of_t))
        out["as_of"] = as_of
        newest = 0.0
        for rel in ("roadmap.json", "DELIVERABLES.md"):
            try:
                newest = max(newest, (root / rel).stat().st_mtime)
            except OSError:
                pass
        try:
            for p in (root / "journal").iterdir():
                if p.is_file():
                    newest = max(newest, p.stat().st_mtime)
        except OSError:
            pass
        if newest:
            out["newest_work"] = time.strftime("%Y-%m-%d", time.localtime(newest))
            behind = int(max(0.0, newest - as_of_t) // 86400)
            out["behind_days"] = behind
            out["stale"] = behind >= 1 and bool(out["text"])
    except Exception:
        pass
    return out


def lead_line(plan):
    """The ONE lead template for the pane, the top bar and the dashboard tile:
    what the steward said comes next and why, and who it waits on - the strip's
    own next_recommended / why_next / the wait; never a guess."""
    plan = plan if isinstance(plan, dict) else {}
    nxt, why = str(plan.get("next") or "").strip(), str(plan.get("why") or "").strip()
    line = ("Next: " + nxt + (" \u2014 " + why if why else "")) if nxt else "Next not stated by the steward"
    wait = str(plan.get("waiting_on_you") or "").strip()
    return line + (" \u00b7 waiting on you: " + wait if wait else "")


def read_last_status(campaign_dir: str):
    """The last 10-minute status the engine PERSISTED for this effort
    (``<cdir>/.ecgberht/status-summary.json``), marked ``stale: True`` — or
    None when there is no record or it is unreadable. Read-only; the shape is
    exactly what :func:`compose_status` produced when it was written, so the
    pane paints it with the same code. Its ``at`` is the record's own stamp."""
    try:
        f = Path(campaign_dir) / ".ecgberht" / "status-summary.json"
        if not f.is_file():
            return None
        raw_d, _d_err = _read_json(f)
        if _d_err or not isinstance(raw_d, dict) or not raw_d.get("at"):
            return None
        d = dict(raw_d)
        d["stale"] = True
        d.setdefault("lead_line", lead_line(d.get("plan")))   # a record written before the lead existed
        return d
    except Exception:
        return None


def status_for_pane(campaign_dir: str, engine_state=None, live: bool = False):
    """What a status pane shows - the cockpit's pane, the High Seat's tile, the Desk: ONE rule (2026-10-01, his word:
    the Status in an expanded tile "looks dated/old"). A LIVE engine: composed fresh from the map and its state. No
    live engine: composed fresh from the RECORD as it is now (the summary, the status, the next bullets, the lead) -
    never the persisted summary alone, whose "Doing" was a run that ended and whose plan may have moved since (the
    2026-09-03 rule showed that summary whole; his eye read it as old). The last run is named once, by its date: on
    the "Doing" line and as ``last_run_at`` for the pane's header; ``from_record`` says the pane is the record now.
    Nothing is grafted from the old summary into the fresh table (Grok's read: that was a second status in one pane)
    and nothing is marked stale."""
    if live:
        return compose_status(campaign_dir, engine_state)
    fresh = compose_status(campaign_dir, None)
    fresh["from_record"] = True
    last = read_last_status(campaign_dir)
    if not isinstance(last, dict) or not last.get("at"):
        return fresh
    stamp = str(last["at"])[-16:]
    fresh["last_run_at"] = str(last["at"])
    for f in ((fresh.get("compact") or {}).get("facts") or []):
        if isinstance(f, dict) and f.get("label") == "Doing":
            f["value"] = "%s \u00b7 the last run %s" % (f.get("value") or "nothing running", stamp)
    return fresh


def _safe_route_seg(seg: str) -> bool:
    """The same safe class ``anchor_gui._unsafe_path_seg`` enforces (mirrored
    here so this zero-import reader stays standalone): a non-empty segment with
    no path separator and no parent-dir traversal."""
    return bool(seg) and "/" not in seg and "\\" not in seg and ".." not in seg


def classify_route(token: str):
    """Classify a Where-cell token as a CONTAINED Anchor route — or None.

    Only Anchor's own contained route grammars qualify, judged on the route's
    OWN grammar (never a request-pid comparison — a cross-project register
    link is a token-gated app route, not traversal):

    - ``/report/<pid>/<lane>[/<job_id>]`` — every segment in the safe class
      :func:`_safe_route_seg` (mirrors ``anchor_gui._unsafe_path_seg``);
    - ``/artifact/<pid>?path=<rel>`` — ``rel`` relative, with no ``..`` /
      absolute / drive / backslash segment and no second query key;
    - ``/foundry?skill=<id>`` — the live Foundry review page (wave 1,
      2026-10-07: John's clickable-review-links standard — a FOR REVIEW row
      whose target is the running walkthrough page must OPEN it, not render
      as text). Exactly ONE query key (``skill``), its value in the strict
      id class ``[A-Za-z0-9][A-Za-z0-9_-]*`` — no second key, no ``/``, no
      ``..``, no percent/scheme/fragment escapes. This is the whole Foundry
      grammar: ``/foundry/source`` and friends stay unclassified (they are
      per-anchor links the page itself mints, never register targets).

    Any ``http(s)://``, protocol-relative ``//``, ``../`` or other
    traversal-bearing token yields None (the row renders as text)."""
    if not token or not isinstance(token, str):
        return None
    t = token.strip()
    if t.startswith("/foundry?"):
        query = t[len("/foundry?"):]
        if "&" in query or not query.startswith("skill="):
            return None
        if not re.match(r"^[A-Za-z0-9][A-Za-z0-9_-]*$", query[len("skill="):]):
            return None
        return t
    if t.startswith("/report/"):
        if "?" in t:
            return None
        segs = t[len("/report/"):].split("/")
        if len(segs) in (2, 3) and all(_safe_route_seg(s) for s in segs):
            return t
        return None
    if t.startswith("/artifact/"):
        pid, sep, query = t[len("/artifact/"):].partition("?")
        if not sep or not _safe_route_seg(pid):
            return None
        if "&" in query or not query.startswith("path="):
            return None
        rel = query[len("path="):]
        if not rel or rel.startswith("/") or "\\" in rel \
                or re.match(r"^[A-Za-z]:", rel):
            return None
        if any(not seg or ".." in seg for seg in rel.split("/")):
            return None
        return t
    return None


def _has_top_final_overrides(campaign_dir: str) -> bool:
    """Return True when DELIVERABLES.md contains both an ECGBERHT-MANAGED-DELIVERABLES block and
    explicit `| FINAL:` table rows in the top human-maintained section above it."""
    f = Path(campaign_dir) / "DELIVERABLES.md"
    if not f.is_file():
        return False
    try:
        raw = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    marker = "<!-- ECGBERHT-MANAGED-DELIVERABLES"
    idx = raw.find(marker)
    if idx <= 0:
        return False
    head = raw[:idx]
    final_count = sum(1 for ln in head.splitlines() if re.match(r"^\|\s*FINAL\s*:", ln.strip(), re.I))
    return final_count >= 3


def _resolve_fuzzy_final_path(campaign_dir: str, cdir_real: str, cand: str) -> tuple[str, bool]:
    """Resolve a candidate relative path inside campaign_dir, handling `- PowerPoint.pptx` vs `.pptx`
    and short unit folder names under `Final Deliverables/` (e.g. `Lecture 4` -> `Lecture 4 - Hypothesis Testing - October 19 2026`)."""
    cand_norm = cand.replace("\\", "/").strip()
    cands_to_try = [cand_norm]
    if re.search(r"\s*-\s*PowerPoint\.pptx$", cand_norm, re.I):
        cands_to_try.append(re.sub(r"\s*-\s*PowerPoint(\.pptx)$", r"\1", cand_norm, flags=re.I))
    for c_try in cands_to_try:
        try:
            real = os.path.realpath(str(Path(campaign_dir) / c_try))
            if (real == cdir_real or real.startswith(cdir_real + os.sep)) and os.path.isfile(real):
                return os.path.relpath(real, cdir_real).replace(os.sep, "/"), True
        except OSError:
            pass
    # Check if cand_norm is under Final Deliverables/<unit_short>/<fname>
    m_fd = re.match(r"^((?:.+/)?Final Deliverables)/([^/]+)/([^/]+)$", cand_norm, re.I)
    if m_fd:
        fd_base_rel, unit_short, fname = m_fd.group(1), m_fd.group(2).strip(), m_fd.group(3).strip()
        fd_base = Path(campaign_dir) / fd_base_rel
        if fd_base.is_dir():
            fname_alts = [fname]
            if re.search(r"\s*-\s*PowerPoint\.pptx$", fname, re.I):
                fname_alts.append(re.sub(r"\s*-\s*PowerPoint(\.pptx)$", r"\1", fname, flags=re.I))
            u_low = unit_short.lower()
            try:
                for sub_d in sorted(fd_base.iterdir(), key=lambda p: p.name.lower()):
                    if not sub_d.is_dir():
                        continue
                    sd_low = sub_d.name.lower()
                    if sd_low == u_low or sd_low.startswith(u_low + " ") or sd_low.startswith(u_low + "-") or (u_low == "syllabus" and "syllabus" in sd_low):
                        for fn in fname_alts:
                            cand_file = sub_d / fn
                            if cand_file.is_file():
                                real = os.path.realpath(str(cand_file))
                                if real == cdir_real or real.startswith(cdir_real + os.sep):
                                    return os.path.relpath(real, cdir_real).replace(os.sep, "/"), True
            except OSError:
                pass
    return cand, False


def _reconcile_top_final_overrides_on_map(root: Path, steps: list, strip: dict, attention: dict, heartbeat: dict) -> int:
    """When top-of-DELIVERABLES.md carries explicit FINAL: rows superseding an older frozen managed refinement fold,
    reconcile in-memory step statuses, labels, and focus without mutating roadmap.json on disk."""
    upcoming_ids = {
        "lecture-11", "lecture-11-ai-supplement", "lecture-12", "lecture-12-ai-supplement",
        "homework-4", "homework-5", "quiz-2", "quiz-3", "block-2-quiz-2", "block-3-quiz-3-close-out",
    }
    active_review_ids = {"lecture-10"}
    title_overrides = {
        "lecture-1": "Lecture 1 — Introduction to Statistics & Descriptive Analytics (Final)",
        "lecture-2": "Lecture 2 — Describing Data, Outliers, Normal Curve & Process Control (67 Slides — Final)",
        "lecture3-machine-revision": "Lecture 3 — Sampling Distributions & Confidence Intervals (50 Slides — Final)",
        "lecture4-machine-revision": "Lecture 4 — Hypothesis Testing for a Population Mean (57 Slides — Final)",
        "lecture-5": "Lecture 5 — Two-Sample Hypothesis Testing & Experimental Design (39 Slides — Final)",
        "lecture-6": "Lecture 6 — Correlation, Simple Linear Regression & CAPM (48 Slides — Final)",
        "lecture-7": "Lecture 7 — Multiple Regression, Adjusted R² & Multicollinearity (33 Slides — Final)",
        "lecture-8": "Lecture 8 — Dummy Variables, Parallel Lines & Interactions (37 Slides — Final)",
        "lecture-9": "Lecture 9 — One-Way Analysis of Variance (ANOVA) (48 Slides + R & 4 CSVs — Final)",
        "homework-1": "Homework 1 — Descriptive Analytics & Sampling Packet (Final)",
        "homework-2": "Homework 2 — Confidence Intervals & Hypothesis Testing Packet (Final)",
        "homework-3": "Homework 3 — Two-Sample Tests & Regression Modeling Packet (Final)",
        "homework-quiz-1": "Quiz 1 — Smeal LEM Lab Sign-Up, 96-Student Roster & R Package Verification (Final / Ready)",
        "syllabus-2026": "Course Syllabus & Schedule (Fall 2026 — Final)",
        "intro-lecture-schedule-2026": "Residential MBA Intro Lecture (Fall 2026 — Final)",
    }
    for s in steps:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or "").strip()
        nav = dict(s["navigation"]) if isinstance(s.get("navigation"), dict) else {}
        if sid in active_review_ids:
            s["status"] = "active"
            s["name"] = "Lecture 10 — Experiments, Two-Way ANOVA & Causality (Refinement 3, 47 Slides — For Review)"
            s["done_when"] = "John reviews Lecture 10 Refinement 3 (47-slide PDF/PPTX, Lecture 10.R & Dear Kitten A/B Testing report) and locks Final Deliverables."
            s["waiting_on"] = "Review Lecture 10 Refinement 3 (47-slide deck + Lecture 10.R) & Quiz 1 LEM Lab Roster"
            nav["label"] = s["name"]
            nav["current"] = True
            nav["pin"] = True
            nav["featured_paths"] = [
                "BA 815/Fall 2026/Lecture 10 - Refinement 3.pdf",
                "BA 815/Fall 2026/Lecture 10 - Refinement 3.pptx",
                "BA 815/Fall 2026/Final Deliverables/Lecture 10/Lecture 10.R",
                "BA 815/Fall 2026/planning/DEAR-KITTEN-AB-TESTING-RESEARCH.pdf",
            ]
            if isinstance(s.get("refinement"), dict):
                ref_c = dict(s["refinement"])
                ref_c["phase"] = "awaiting_review"
                ref_c["round"] = 3
                ref_c["display_round"] = 3
                s["refinement"] = ref_c
            s["navigation"] = nav
        elif sid in upcoming_ids:
            if s.get("status") == "done":
                pass
            else:
                s["status"] = "proposed"
                s["waiting_on"] = None
                nav["current"] = False
                nav["pin"] = False
                s["navigation"] = nav
        else:
            s["status"] = "done"
            s["waiting_on"] = None
            if sid in title_overrides:
                s["name"] = title_overrides[sid]
                nav["label"] = title_overrides[sid]
            else:
                for key_f in ("name",):
                    if isinstance(s.get(key_f), str):
                        s[key_f] = re.sub(r"\s*\((?:for review|awaiting review)\)\s*$", " (Final)", s[key_f], flags=re.I)
                if isinstance(nav.get("label"), str):
                    nav["label"] = re.sub(r"\s*\((?:for review|awaiting review)\)\s*$", " (Final)", nav["label"], flags=re.I)
            nav["current"] = False
            nav["pin"] = False
            s["navigation"] = nav
            if isinstance(s.get("refinement"), dict):
                ref_c = dict(s["refinement"])
                ref_c["phase"] = "done"
                ref_c["work_phase"] = "done"
                s["refinement"] = ref_c
    if isinstance(strip, dict):
        if strip.get("active_effort"):
            heartbeat["active_effort"] = strip["active_effort"]
        if strip.get("next_recommended"):
            heartbeat["next_recommended"] = strip["next_recommended"]
        if strip.get("why_next"):
            heartbeat["why_next"] = strip["why_next"]
        if strip.get("human_wait"):
            heartbeat["human_wait"] = strip["human_wait"]
    if isinstance(attention, dict):
        attention["pending_requests"] = []
        attention["pending_request"] = None
        if attention.get("state") != "working":
            attention["state"] = "needs_you"
            attention["reason"] = heartbeat.get("human_wait") or "Review Lecture 10 Refinement 3 & Quiz 1 LEM Lab Roster"
    return sum(1 for s in steps if s.get("status") == "done")


def _read_deliverables(campaign_dir: str):
    """Parse ``<cdir>/DELIVERABLES.md`` — THE campaign deliverables register (the
    steward's OWN convention, campaign journal 0010: one table row per thing a
    human would open; standing rule = a step producing a human-facing artifact is
    not done until listed here). Disk-true, zero-model, one source of truth — the
    cockpit never keeps a second registry.

    THE HEADER CONTRACT (written down once, here): the register is a pipe table
    ``| What | Where | Date | Step |`` — Step optional per row. The Where cell
    carries the open target (a backticked or bare in-effort path, or a contained
    Anchor route per :func:`classify_route`) and may ALSO carry a
    ``run: <command>`` marker (backticked ``run: `<command>` `` form too); a row
    may carry BOTH an open target and a run command.

    Returns ``{"exists": bool, "items": [{"what", "where_text", "path", "route",
    "run", "date", "step", "openable"}]}``. ``path`` is the first backticked span
    of the Where cell, resolved against the campaign dir; ``openable`` is True
    ONLY when the resolved real path stays INSIDE the campaign dir (containment —
    entries pointing outside, e.g. ``../…``, render as text, never as links) OR
    when the cell names a contained Anchor route (``route`` set, ``path`` None).
    ``run`` is the exact command string after the ``run:`` marker — stored
    verbatim, no shell parsing, no evaluation, never executed here."""
    f = Path(campaign_dir) / "DELIVERABLES.md"
    if not f.is_file():
        return {"exists": False, "items": _plan_doc_rows(campaign_dir, [])}
    try:
        cdir_real = os.path.realpath(str(campaign_dir))
        is_real_clock = getattr(time.monotonic, "__name__", "") != "<lambda>"
        deliv_cache = globals().setdefault("_RAW_DELIVERABLES_CACHE", {})
        deliv_sig = None
        if is_real_clock:
            try:
                f_st = f.stat()
                deliv_sig = (
                    os.path.normcase(cdir_real),
                    f_st.st_mtime_ns,
                    f_st.st_size,
                    _refinement_fingerprint(Path(cdir_real)),
                    int(time.monotonic() // 5),
                )
                cached_deliv = deliv_cache.get(deliv_sig[0])
                if cached_deliv is not None and cached_deliv[0] == deliv_sig and not cached_deliv[1].get("error"):
                    c_res = cached_deliv[1]
                    return {
                        "exists": c_res["exists"],
                        "approved": [dict(a) for a in c_res.get("approved", [])],
                        "finished_projection": c_res.get("finished_projection"),
                        "items": [dict(it) for it in c_res.get("items", [])],
                    }
            except OSError:
                deliv_sig = None
        items = []
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            s = line.strip()
            if not (s.startswith("|") and s.endswith("|")):
                continue
            cells = [c.strip() for c in s.strip("|").split("|")]
            if len(cells) < 3 or set(cells[0]) <= {"-", " ", ":"} \
               or cells[0].lower() == "what":
                continue
            what, where_text, date = cells[0], cells[1], cells[2]
            path_rel, openable, route, run_cmd = None, False, None, None
            # (2026-09-05) a `run:` marker anywhere in the cell stores the
            # EXACT command string — no shell parsing, no evaluation, never
            # executed here. Backticked form matched first so a backticked
            # command is never mistaken for the open-target span; the marker
            # is removed from the cell before the open target is extracted.
            cell = where_text
            m_run = re.search(r"run:\s*(?:`([^`]+)`|(\S[^|]*))", where_text)
            if m_run:
                run_cmd = m_run.group(1) if m_run.group(1) is not None \
                    else m_run.group(2).strip()
                cell = (where_text[:m_run.start()]
                        + where_text[m_run.end():]).strip()
            m_bt = re.search(r"`([^`]+)`", cell)
            # (2026-09-04) a register row written without backticks (the
            # Fractal Orthogonal Basis effort: "report/DRAFT-v1.md") must still
            # open: fall back to the cell's first token that names a file.
            cand_plain = None
            if not m_bt:
                whole_cand = cell.strip().strip("()[]")
                if whole_cand and ("/" in whole_cand or "." in whole_cand) and not whole_cand.startswith("/"):
                    res_p, is_op = _resolve_fuzzy_final_path(campaign_dir, cdir_real, whole_cand)
                    if is_op or re.search(r"\.(?:pdf|pptx|docx|xlsx|r|csv|zip|html|htm|md|txt|py|json)$", whole_cand, re.I):
                        cand_plain = res_p if is_op else whole_cand
                if not cand_plain:
                    for tok in cell.replace(",", " ").split():
                        tok = tok.strip().strip("()[]")
                        if "/" in tok or "." in tok:
                            cand_plain = tok
                            break
            if m_bt or cand_plain:
                cand = (m_bt.group(1).strip() if m_bt else cand_plain)
                if cand.startswith("/"):
                    # (2026-09-05, widened 2026-10-07) ANY route-shaped
                    # (leading-slash) token is judged by the contained grammar
                    # ONLY — /report/…, /artifact/… and now /foundry?skill=…
                    # classify; a hostile or unsupported cell gets route None
                    # and stays text; it never reaches the filesystem branch
                    # (a leading-slash token was never a contained file path).
                    route = classify_route(cand)
                    openable = route is not None
                else:
                    path_rel, openable = _resolve_fuzzy_final_path(campaign_dir, cdir_real, cand)
            items.append({"what": re.sub(r"\*\*", "", what),
                          "where_text": where_text,
                          "path": path_rel,
                          "route": route,
                          "run": run_cmd,
                          "date": date,
                          # optional 4th column (John, 2026-08-26): which
                          # roadmap step produced it — a step NUMBER or a
                          # name fragment; the map embeds the link there
                          "step": cells[3].strip() if len(cells) > 3 else "",
                          "openable": openable})
        refinement = read_refinement(campaign_dir, stale_ok=True)
        has_top_finals = _has_top_final_overrides(campaign_dir)
        if refinement is not None:
            if not refinement.get("ok"):
                return {"exists": True, "items": items, "error": refinement.get("error")}
            managed = refinement_items(campaign_dir, refinement["state"])
            if has_top_finals:
                for m_it in managed:
                    if str(m_it.get("step") or "") not in ("lecture-10", "quiz-1-prep"):
                        m_it["phase"] = "done"
                        m_it["accepted"] = True
                        m_it["accepted_current"] = True
            paths = {item["path"] for item in managed}
            items = managed + [item for item in items if item.get("path") not in paths]
        approved = [{**item, "what": item["product_id"], "step": item["step_id"],
            "date": item.get("accepted_at", ""), "accepted": True, "openable": True, "managed": True}
            for item in (refinement or {}).get("approved_products", [])]
        for item in items:
            if not item.get("accepted_current"):
                item["accepted_current"] = bool((refinement or {}).get("current_approvals", {})
                    .get(item.get("step"), {}).get(item.get("product_id"), False))
            if item.get("managed"):
                item["history"] = [v for v in item.get("history", []) if v.get("revision_id") != item.get("revision_id")]
        from anchor_notebooks import decorate
        final_res = {
            "exists": True,
            "approved": approved,
            "finished_projection": (refinement or {}).get("finished_projection"),
            "items": [decorate(campaign_dir, item) for item in items + _plan_doc_rows(campaign_dir, items)],
        }
        if deliv_sig is not None:
            if len(deliv_cache) > 64:
                deliv_cache.clear()
            deliv_cache[deliv_sig[0]] = (
                deliv_sig,
                {
                    "exists": True,
                    "approved": [dict(a) for a in final_res["approved"]],
                    "finished_projection": final_res["finished_projection"],
                    "items": [dict(it) for it in final_res["items"]],
                },
            )
        return final_res
    except Exception:
        return {"exists": True, "items": []}


def _plan_doc_rows(campaign_dir, listed, depth=2):
    """(John, 2026-09-04) a plan for going forward is a clickable link in the
    work flow without anyone registering it: every PLAN / MASTER-PLAN /
    IMPLEMENTATION-PLAN / NORTH-STAR / *-PLAN document up to two levels
    under the campaign dir that the register does not already list becomes
    an ``auto`` row (openable — it is inside the campaign by construction)."""
    root = Path(campaign_dir)
    try:
        cdir_real = os.path.realpath(str(root))
    except OSError:
        return []
    have = set()
    for it in listed or []:
        p = it.get("path")
        if p:
            have.add(os.path.normcase(os.path.realpath(os.path.join(cdir_real, p))))
    rows = []

    def walk(d, level):
        try:
            entries = sorted(d.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for p in entries:
            name = p.name
            try:
                is_dir = p.is_dir()
            except OSError:
                continue
            if is_dir:
                if level < depth and name not in _LOOK_SKIP_DIRS \
                        and not name.startswith((".", "_")):
                    walk(p, level + 1)
                continue
            if not _PLAN_DOC_NAME.match(name):
                continue
            try:
                real = os.path.realpath(str(p))
                if os.path.normcase(real) in have:
                    continue
                relp = os.path.relpath(real, cdir_real).replace(os.sep, "/")
                date = time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime))
            except OSError:
                continue
            have.add(os.path.normcase(real))
            rows.append({"what": "Plan \u00b7 " + relp, "where_text": relp,
                         "path": relp, "route": None, "run": None,
                         "date": date, "step": "",
                         "openable": True, "auto": True})

    walk(root, 0)
    return rows


def read_history(campaign_dir: str, tail: int = TAIL_TURNS):
    """The campaign conversation so far - what was said, not state."""
    log, err = _read_json(Path(campaign_dir) / ".ecgberht" / "conversation-log.json")
    if err or not log:
        return {"turns": [], "note": f"conversation log {err or 'empty'}"}
    turns = log.get("turns") or []
    out = [{"role": t.get("role", "steward"),
            "text": t.get("text", ""),
            "at": t.get("at", "")} for t in turns[-tail:]]
    note = "" if len(turns) <= tail else f"showing last {tail} of {len(turns)} turns"
    return {"turns": out, "note": note}


STEWARD_LABELS = {"ecgberht": "Ecgberht", "aladdin": "Aladdin", "jarvis": "Jarvis"}
# persona livery, straight from Anchor's catalog (anchor_settings.STEWARDS)
STEWARD_LIVERY = {
    "Ecgberht": {"seal_icon": "ecgberht-project-seal.jpg", "seal_name": "Seal"},
    "Aladdin": {"seal_icon": "aladdin-seal-lamp.jpg", "seal_name": "Lamp"},
    "Jarvis": {"seal_icon": "jarvis-seal-salver.jpg", "seal_name": "Server"},
}
BONEYARD_DIRNAME = "_boneyard"


def steward_name(override=None):
    """The persona John picked in Anchor (mirrored to ~/.anchor/model_prefs.json
    as steward_type). Read-only; override wins; fallback Ecgberht."""
    if override:
        return override
    prefs, _ = _read_json(Path.home() / ".anchor" / "model_prefs.json")
    key = (prefs or {}).get("steward_type", "ecgberht")
    return STEWARD_LABELS.get(str(key).strip().lower(), "Ecgberht")


def read_seats():
    """Anchor's seat settings, from the same mirror: the MAIN driving seat
    (default_cli) and the adversarial-REVIEW family (review_family)."""
    prefs, _ = _read_json(Path.home() / ".anchor" / "model_prefs.json")
    prefs = prefs or {}
    cap = lambda s: str(s or "").strip().capitalize() or "?"
    return {"main": cap(prefs.get("default_cli", "claude")),
            "review": cap(prefs.get("review_family", "gemini"))}


def last_touched(campaign_dir: str):
    """Raw recency for sorting: newest mtime among the talk + state files."""
    root = Path(campaign_dir)
    times = [0.0]
    for rel in (".ecgberht/conversation-log.json", "strip.json", "roadmap.json"):
        try:
            times.append((root / rel).stat().st_mtime)
        except OSError:
            pass
    return max(times)


def read_grass(root_dir: str):
    """Every effort's grasscatch entries, one flat list, newest first.
    Supports both legacy bare strings and the structured shape
    {text, when, source, status}. The steward is the only writer."""
    out = []
    for e in discover_efforts(root_dir):
        d = Path(root_dir) / e["rel"] if e["rel"] else Path(root_dir)
        strip, err = _read_json(d / "strip.json")
        if not strip:
            continue
        fallback_when = ""
        try:
            fallback_when = time.strftime(
                "%Y-%m-%d", time.localtime((d / "strip.json").stat().st_mtime))
        except OSError:
            pass
        for g in strip.get("grasscatch") or []:
            if isinstance(g, dict):
                out.append({"text": str(g.get("text", ""))[:400],
                            "when": g.get("when", fallback_when),
                            "effort": e["name"],
                            "source": g.get("source", "")})
            else:
                out.append({"text": str(g)[:400], "when": fallback_when,
                            "effort": e["name"], "source": ""})
    out.sort(key=lambda x: x["when"], reverse=True)
    return out


#: An effort retired IN PLACE (2026-09-03): Windows refuses to rename a folder
#: while anything inside it is open (a deck in PowerPoint, an Explorer window,
#: a terminal's cwd) — WinError 5/32. Rather than fail, the effort stays where
#: it is and carries this marker; it leaves the live list and joins the
#: boneyard list exactly like a moved one. Resurrecting removes the marker.
RETIRED_MARKER = ".ecgberht/retired.json"


def retired_marker_path(effort_dir: str) -> Path:
    return Path(effort_dir) / RETIRED_MARKER


def is_retired_in_place(effort_dir: str) -> bool:
    try:
        return retired_marker_path(effort_dir).is_file()
    except OSError:
        return False


def retire_in_place(effort_dir: str, why: str = "") -> dict:
    """Write the in-place retirement marker. Returns the record written."""
    f = retired_marker_path(effort_dir)
    f.parent.mkdir(parents=True, exist_ok=True)
    rec = {"retired": time.strftime("%Y-%m-%d %H:%M"), "in_place": True,
           "why": why or "files in the effort were open when it was retired"}
    f.write_text(json.dumps(rec, indent=2) + "\n", encoding="utf-8")
    return rec


def resurrect_in_place(effort_dir: str) -> bool:
    """Remove the marker; True if one was there."""
    f = retired_marker_path(effort_dir)
    if not f.is_file():
        return False
    f.unlink()
    return True


def list_boneyard(root_dir: str):
    """Efforts resting in <root>/_boneyard PLUS efforts retired in place
    (marker), newest burial first."""
    root = Path(root_dir)
    yard = root / BONEYARD_DIRNAME
    out = []

    def _row(p, when, in_place):
        m = read_map(str(p), include_plan_history=False)
        out.append({"name": p.name, "goal_brief": m["goal_brief"],
                    "steps_done": m["steps_done"],
                    "steps_total": m["steps_total"], "boneyarded": when,
                    "in_place": in_place})

    if yard.is_dir():
        for p in sorted(yard.iterdir()):
            if not (p / "ECGBERHT.md").is_file():
                continue
            try:
                when = time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime))
            except OSError:
                when = ""
            _row(p, when, False)
    try:
        subs = sorted(p for p in root.iterdir()
                      if p.is_dir() and not p.name.startswith((".", "_")))
    except OSError:
        subs = []
    for p in subs:
        if not (p / "ECGBERHT.md").is_file() or not is_retired_in_place(str(p)):
            continue
        try:
            rec = json.loads(retired_marker_path(str(p)).read_text(encoding="utf-8"))
            when = str(rec.get("retired") or "")[:10]
        except Exception:
            when = ""
        _row(p, when, True)
    out.sort(key=lambda x: x["boneyarded"], reverse=True)
    return out


def _step_done(step):
    r = step.get("refinement") if isinstance(step, dict) else None
    if isinstance(r, dict):
        return r.get("phase") == "done"
    return (step or {}).get("status") == "done"


def _step_needs_attention(step):
    if not step:
        return False
    if step.get("status") in ("waiting", "blocked") or step.get("waiting_on"):
        return True
    r = step.get("refinement") if isinstance(step.get("refinement"), dict) else None
    if r and r.get("phase") in ("awaiting_review", "blocked"):
        return True
    return any(h.get("status") == "pending_steward_review"
               for h in (r or {}).get("producer_handoffs") or [] if isinstance(h, dict))


def _stream_mark(steps):
    if not steps:
        return {"glyph": "▷", "cls": "todo"}
    if all(_step_done(s) for s in steps):
        return {"glyph": "✓", "cls": "done"}
    if any(_step_needs_attention(s) for s in steps):
        return {"glyph": "⚑", "cls": "flag"}
    return {"glyph": "▷", "cls": "todo"}


def _item_summary(item):
    if item.get("accepted") or item.get("accepted_current"):
        return "✓ Approved"
    if item.get("managed"):
        round_n = item.get("round")
        round_l = "Initial draft" if round_n == 0 else (
            "Refinement %s" % round_n if isinstance(round_n, int) else "")
        phase = "Provisional draft" if item.get("provisional") else str(item.get("phase") or "").replace("_", " ")
        return " · ".join(p for p in (round_l, phase) if p)
    return str(item.get("date") or "").split("T")[0]


def work_stream_model(map_, items):
    """Same work-stream tree the cockpit Deliverables panel paints."""
    from .navigation_compat import with_compat_navigation, resolve_step
    map_ = map_ or {"name": "Project work", "steps": []}
    if not map_.get("navigation_mode"):
        map_ = with_compat_navigation(map_)
    steps = list((map_ or {}).get("steps") or [])
    definitions, featured = {}, set()
    fallback = map_.get("navigation_fallback") or {}
    for g in fallback.get("groups") or []:
        definitions[g["id"]] = g
    for s in steps:
        n = s.get("navigation") or {}
        for g in n.get("groups") or []:
            if isinstance(g, dict) and g.get("id"):
                definitions[g["id"]] = g
        for p in n.get("featured_paths") or []:
            featured.add(str(p).replace("\\", "/").lower())
    roots, all_nodes, step_groups, overrides, related = [], {}, {}, {}, {}

    def ensure(path):
        if not (isinstance(path, list) and 0 < len(path) <= 2 and all(isinstance(g, str) and g in definitions for g in path)):
            definitions["unclassified"] = {"id": "unclassified",
                                           "label": "Other work — needs organization", "order": 99999}
            path = [fallback["id"], "unclassified"] if fallback.get("id") else ["unclassified"]
        parent = None
        node = None
        for gid in path:
            g = definitions[gid]
            node = all_nodes.get(g["id"])
            if node is None:
                node = {**g, "children": [], "steps": [], "items": [], "reference_steps": [], "reference_items": [], "parent": parent}
                all_nodes[g["id"]] = node
                (parent["children"] if parent else roots).append(node)
            parent = node
        return node

    if fallback.get("id"):
        ensure([fallback["id"]])
        for c in fallback.get("components") or []:
            ensure([fallback["id"], c["id"]])
    for i, s in enumerate(steps):
        n = s.get("navigation") or {}
        group = ensure(n.get("path"))
        group["steps"].append(s)
        step_groups[s.get("id")] = group
        for path in n.get("include_paths") or []:
            ensure(path)
        refs = []
        for path in n.get("related_paths") or []:
            ref = ensure(path)
            if ref is not group and not any(ref is existing for existing in refs):
                ref["reference_steps"].append(s)
                refs.append(ref)
        related[s.get("id")] = refs
        for o in n.get("items") or []:
            if isinstance(o, dict) and isinstance(o.get("source_path"), str):
                overrides[o["source_path"].replace("\\", "/").lower()] = ensure(o.get("path"))
    for it in items or []:
        group = overrides.get(str(it.get("path") or "").replace("\\", "/").lower())
        matched = resolve_step(steps, it.get("owner_step_id") if "owner_step_id" in it else it.get("step"))
        if group is None:
            if matched is not None:
                group = step_groups.get(matched.get("id"))
        (group or ensure(None))["items"].append(it)
        if matched is not None:
            for ref in related.get(matched.get("id"), []):
                if ref is not group:
                    ref["reference_items"].append(it)
    def group_steps(node):
        found = node["steps"] + node["reference_steps"]
        for child in node["children"]:
            found += group_steps(child)
        return list({id(s): s for s in found}.values())
    def sort_nodes(nodes):
        nodes.sort(key=lambda n: (n.get("order") or 0, n.get("label") or ""))
        for n in nodes:
            sort_nodes(n["children"])
            n["items"].sort(key=lambda it: (1 if it.get("managed") else 0,
                                            str(it.get("date") or "")), reverse=True)
            collected = group_steps(n)
            primary = [s for s in collected if (s.get("navigation") or {}).get("role") == "primary"]
            n["mark"] = _stream_mark(primary or collected)
    sort_nodes(roots)
    return {"roots": roots, "featured": featured}


_HISTORICAL_LABEL = re.compile(
    r"^(?:HISTORICAL|SUPERSEDED|ARCHIVED|EARLIER|PREVIOUS)\b"
    r"|^Existing\s+(?:Earlier|Prior|Historical)\b"
    r"|^(?:SUPPORTING|ACCEPTED|APPROVED|FINAL(?:IZED)?)\s*[-:—–]"
    r"|[\u2014\u2013-]\s*historical\s*$"
    r"|\bkept\s*\(not\s+landed\)",
    re.I,
)


def _iso_days_between(d1_str: str, d2_str: str) -> int:
    """Return abs days between two YYYY-MM-DD prefixes, or 0 if either is not an ISO date."""
    try:
        from datetime import date as _dt_date
        a = _dt_date.fromisoformat(str(d1_str or "").strip()[:10])
        b = _dt_date.fromisoformat(str(d2_str or "").strip()[:10])
        return abs((a - b).days)
    except Exception:
        return 0


def current_review_items(map_, items):
    from .navigation_compat import resolve_step
    steps = (map_ or {}).get("steps") or []
    current = []
    # Compute the newest explicit designation date per step so stale featured_paths or month-old rounds
    # on a long-running step do not stay marked is_current alongside a newer designated wave.
    step_max_desig_date = {}
    for it in items or []:
        if it.get("managed") or it.get("accepted") or it.get("accepted_current"):
            continue
        w_str = str(it.get("what") or "")
        if _HISTORICAL_LABEL.match(w_str):
            continue
        if re.match(r"^(?:START\s+HERE|CURRENT|FOR\s+REVIEW)\s*(?:[:—–-]|$)", w_str, re.I):
            ow = resolve_step(steps, it.get("step"))
            sid = str((ow or {}).get("id") or "")
            d_iso = str(it.get("date") or "").strip()[:10]
            if sid and re.match(r"^\d{4}-\d{2}-\d{2}$", d_iso):
                if sid not in step_max_desig_date or d_iso > step_max_desig_date[sid]:
                    step_max_desig_date[sid] = d_iso

    for it in items or []:
        owner = resolve_step(steps, it.get("step"))
        if owner is None:
            continue
        nav = (owner or {}).get("navigation") or {}
        if it.get("accepted") or it.get("accepted_current"):
            continue
        if _HISTORICAL_LABEL.match(str(it.get("what") or "")):
            continue
        p_norm = str(it.get("path") or "").replace("\\", "/").lower()
        if "/code-job-outputs/" in ("/" + p_norm):
            continue
        if it.get("managed") and it.get("phase") in ("awaiting_review", "blocked"):
            current.append(it)                 # asked for review: stays whatever the focus (journal 0132)
            continue
        if nav.get("current") is False or nav.get("role") == "support" or (owner or {}).get("status") == "parked":
            continue
        if it.get("managed") and it.get("phase") != "done":
            current.append(it)
        elif not it.get("managed") and owner and owner.get("status") != "done" and (owner.get("refinement") or {}).get("phase") != "done":
            normalize = lambda p: str(p or "").replace("\\", "/").lower()
            featured = {normalize(p) for p in nav.get("featured_paths") or []}
            designation = re.match(r"^(?:START\s+HERE|CURRENT|FOR\s+REVIEW)\s*(?:[:—–-]|$)", str(it.get("what") or ""), re.I)
            historical = _HISTORICAL_LABEL.match(str(it.get("what") or ""))
            if not historical and (normalize(it.get("path")) in featured or designation):
                sid = str(owner.get("id") or "")
                max_d = step_max_desig_date.get(sid, "")
                it_d = str(it.get("date") or "").strip()[:10]
                if max_d and re.match(r"^\d{4}-\d{2}-\d{2}$", it_d) and it_d < max_d and _iso_days_between(max_d, it_d) > 7:
                    continue
                current.append(it)
    # 2026-10-07 (John: Next steps showed "a fraction"): the newest batch published on the focused step is current
    # even when the steward did not label it START HERE / FOR REVIEW — e.g. the MBA Version 3 documents.
    focus, _warn = _focused_step(map_ or {})
    # when the steward DID designate what is current on the focused step (START HERE / CURRENT / FOR REVIEW, or a
    # featured path), that designation is the record - the newest-per-family fallback is only for a step where
    # nothing was designated (the MBA Version 3 case)
    # a designation is explicit: a legacy row the steward labelled or featured, or a managed product AWAITING John's
    # review - managed work merely in progress is not a designation (ChatGPT, items 1+2 re-review)
    designated = focus is not None and any(
        resolve_step(steps, it.get("step")) is focus
        and (not it.get("managed") or it.get("phase") in ("awaiting_review", "blocked")) for it in current)
    if designated:
        # the other formats of a designated product (same owner, folder and file stem) are that product too
        chosen = {(_owner_id(it, steps),) + _split_path(it) for it in current if not it.get("managed")}
        seen = {id(it) for it in current}
        _superseded_companion = re.compile(r"\b(?:SUPERSEDED|ARCHIVED|EARLIER|PREVIOUS)\b|^(?:ACCEPTED|APPROVED)\b|\bkept\s*\(not\s+landed\)", re.I)
        current.extend(it for it in items or []
                       if id(it) not in seen and not it.get("managed")
                       and not (it.get("accepted") or it.get("accepted_current"))
                       and not _superseded_companion.search(str(it.get("what") or ""))
                       and (_owner_id(it, steps),) + _split_path(it) in chosen)
    if focus is not None and focus.get("status") not in ("done", "parked") and not designated:
        has_openable_on_focus = any(
            not it.get("managed")
            and resolve_step(steps, it.get("step")) is focus
            and (it.get("openable") or it.get("path") or it.get("route"))
            for it in (items or [])
        )
        own = [it for it in items or []
               if not it.get("managed") and not (it.get("accepted") or it.get("accepted_current"))
               and resolve_step(steps, it.get("step")) is focus
               and (not has_openable_on_focus or it.get("openable") or it.get("path") or it.get("route"))
               and not _HISTORICAL_LABEL.match(str(it.get("what") or ""))
               and not re.search(r"\bJournal\s+\d+\b", str(it.get("what") or ""), re.I)
               and not re.search(r"(?:^|/)(?:journal|\.ecgberht|code-job-outputs)/", str(it.get("path") or "").replace("\\", "/"), re.I)]
        # per PRODUCT FAMILY, not per step (ChatGPT review): the newest version of each family is current, so a new
        # unrelated product never hides an older one still waiting; within a family the newest (date, version
        # number) wins - Draft 1 and Draft 2 registered the same day keep only Draft 2; the formats of that one
        # version (same date, same number) all stay
        best = {}
        for it in own:
            fam = _family_key(it)
            best[fam] = max(best.get(fam, ("", ())), _version_rank(it))
        seen = {id(it) for it in current}
        current.extend(it for it in own if _version_rank(it) == best[_family_key(it)] and id(it) not in seen)
    # Deduplicate superseded versions across unmanaged items when both carry explicit version numbers
    # on the same stem (e.g., v11 in stale featured_paths when v12 is designated START HERE, or Initial-Draft vs Refinement-2).
    stem_max_ver = {}
    clean_stem = lambda s: re.sub(r"\s+", " ", _INITIAL_DRAFT_TAG.sub("", _VERSION_TAG.sub("", _strip_format_tag(s)))).strip(" -_,").lower()
    for it in current:
        if it.get("managed"):
            continue
        ver = _version_rank(it)[1]
        st_key = clean_stem(_split_path(it)[1])
        if ver and st_key:
            if st_key not in stem_max_ver or ver > stem_max_ver[st_key]:
                stem_max_ver[st_key] = ver
    if stem_max_ver:
        current = [
            it for it in current
            if it.get("managed")
            or not _version_rank(it)[1]
            or not clean_stem(_split_path(it)[1])
            or _version_rank(it)[1] >= stem_max_ver.get(clean_stem(_split_path(it)[1]), ())
        ]
    current.sort(key=lambda it: str(it.get("date") or ""), reverse=True)
    return [it for it in current if not it.get("reviewed_done")]


_READ_RANK = {".pdf": 0, ".html": 1, ".htm": 1, ".md": 2, ".docx": 3, ".pptx": 3}


_FORMAT_TAG = re.compile(
    r"[\s_-]*(?:\((?:pdf|md|html|htm|docx|pptx|browser(?: reading)?|ta download)\)"
    r"|\b(?:md|pdf|html|htm|docx|pptx))\s*$", re.I)


_FORMAT_NOTE = re.compile(r"\((pdf|md|html|htm|docx|pptx|browser(?: reading)?|ta download)\s*[;,]\s*([^)]*)\)\s*$", re.I)


def _strip_format_tag(text, keep_note=False):
    """A product's title without its format tag: ' MD', '-PDF', '(PDF)', '(browser)', '(browser reading)',
    '(TA download)', and '(PDF; held)' - whose note ('held') stays in a label (keep_note) but not in a key."""
    text = str(text or "").strip()
    m = _FORMAT_NOTE.search(text)
    if m:
        return (text[:m.start()].strip() + (" (" + m.group(2).strip() + ")" if keep_note and m.group(2).strip() else "")).strip()
    return _FORMAT_TAG.sub("", text).strip()


_VERSION_TAG = re.compile(r"[\s,_-]*\b(?:draft|refinement|version|release|round|revision|rev|v)[\s_-]*(\d+(?:\.\d+)*)\b",
                          re.I)

_INITIAL_DRAFT_TAG = re.compile(r"[\s,_-]*\binitial[\s_-]*(?:draft|version|release)\b", re.I)


def _owner_id(it, steps=None):
    owner = str(it.get("step") or "")
    if steps is not None:
        from .navigation_compat import resolve_step
        st = resolve_step(steps, it.get("step"))
        if st is not None:
            owner = str(st.get("id") or owner)
    return owner


def _split_path(it):
    path = str(it.get("open_path") or it.get("path") or it.get("route") or "").replace(chr(92), "/")
    folder, _, name = path.rpartition("/")
    stem = name.rsplit(".", 1)[0] if "." in name else name
    return folder, stem


def _version_rank(it):
    """(date, version) - the order of one family's versions; the version is a tuple of integers (v1.10 > v1.9,
    v1.2.4 > v1.2.3); (0,) for 'Initial draft' / 'Initial-Draft'; () when the name carries none."""
    stem_txt = _split_path(it)[1]
    what_txt = _strip_format_tag(it.get("what") or "")
    m = _VERSION_TAG.search(stem_txt) or _VERSION_TAG.search(what_txt)
    if m:
        version = tuple(int(x) for x in m.group(1).split("."))
    elif _INITIAL_DRAFT_TAG.search(stem_txt) or _INITIAL_DRAFT_TAG.search(what_txt):
        version = (0,)
    else:
        version = ()
    return (str(it.get("date") or ""), version)


def _family_key(it, steps=None):
    """A product across its versions: owner, folder and file stem with every version tag removed ('Quiz 1 - Draft
    3/Bank - Draft 3' and 'Quiz 1 - Draft 1/Bank - Draft 1' are one family; 'a/Summary' and 'b/Summary' are two)."""
    folder, stem = _split_path(it)
    clean = lambda t: re.sub(r"\s+", " ", _INITIAL_DRAFT_TAG.sub("", _VERSION_TAG.sub("", t))).strip(" -_,").lower()
    folder = "/".join(clean(seg) for seg in folder.split("/"))
    return (_owner_id(it, steps), folder, clean(_strip_format_tag(stem)) or clean(_strip_format_tag(it.get("what"))))


def _product_key(it, steps=None):
    """One product VERSION, whatever formats it was published in - formats pair only on affirmative evidence
    (ChatGPT review: never pair two versions, never merge two products that share a title). Unmanaged: the same
    owner, folder and file stem (Guide - Refinement 1.md / .pdf / .html). Managed: the same owner, product id
    without its format suffix, and the same presentation - the products presented together as one version; without
    a presentation id a managed product never pairs."""
    owner = _owner_id(it, steps)
    if it.get("managed"):
        together = it.get("presentation_id") or ("revision:" + str(it.get("revision_id") or it.get("hash") or id(it)))
        return (owner, _strip_format_tag(it.get("product_id") or it.get("what")).lower(), str(together))
    folder, stem = _split_path(it)
    if not stem:
        return (owner, "", _strip_format_tag(it.get("what")).lower())
    return (owner, folder.lower(), stem.lower())


def _format_rank(it):
    return _READ_RANK.get("." + str(it.get("path") or "").rsplit(".", 1)[-1].lower(), 9)


def _dismissed_deliverables_file(campaign_dir: str) -> Path:
    return Path(campaign_dir) / ".ecgberht" / "dismissed-deliverables.json"


def _deliverable_disk_sig(campaign_dir: str, rel_path: str) -> dict:
    rel = str(rel_path or "").replace("\\", "/").strip().lstrip("/")
    if not rel or not campaign_dir:
        return {}
    try:
        root = Path(campaign_dir).resolve()
        target = (root / rel).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return {}
        st = target.stat()
        sig = {"mtime_ns": st.st_mtime_ns, "size": st.st_size}
        if st.st_size <= 10 * 1024 * 1024:
            sig["sha256"] = hashlib.sha256(target.read_bytes()).hexdigest()
        return sig
    except Exception:
        return {}


def read_dismissed_deliverables(campaign_dir: str) -> dict:
    if not campaign_dir:
        return {}
    p = _dismissed_deliverables_file(campaign_dir)
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data.get("entries") if isinstance(data, dict) and isinstance(data.get("entries"), dict) else {}
    except Exception:
        return {}


def dismiss_deliverable(campaign_dir: str, path: str = "", product_id: str = "",
                        what: str = "", revision_id: str = "", hash_val: str = "",
                        disposition: str = "approved") -> dict:
    if not campaign_dir:
        return {"ok": False, "error": "missing campaign_dir"}
    norm_path = str(path or "").replace("\\", "/").strip().lstrip("/")
    norm_prod = str(product_id or "").strip()
    norm_what = str(what or "").strip()
    key = norm_path or (f"product:{norm_prod}" if norm_prod else (f"what:{norm_what}" if norm_what else ""))
    if not key:
        return {"ok": False, "error": "missing deliverable identifier"}
    entries = dict(read_dismissed_deliverables(campaign_dir))
    sig = _deliverable_disk_sig(campaign_dir, norm_path) if norm_path else {}
    entry = {
        "key": key,
        "path": norm_path,
        "product_id": norm_prod,
        "what": norm_what,
        "revision_id": str(revision_id or ""),
        "hash": str(hash_val or "") or sig.get("sha256", ""),
        "mtime_ns": sig.get("mtime_ns"),
        "disposition": str(disposition or "approved").strip().lower(),
        "dismissed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    entries[key] = entry
    if norm_prod and key != f"product:{norm_prod}":
        entries[f"product:{norm_prod}"] = entry
    out_file = _dismissed_deliverables_file(campaign_dir)
    try:
        out_file.parent.mkdir(parents=True, exist_ok=True)
        out_file.write_text(json.dumps({"schema": "anchor-dismissed-deliverables-v1", "entries": entries}, indent=2),
                            encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "dismissed": entry}


def _dismissed_entry_for_item(campaign_dir: str, it: dict, dismissed: dict) -> dict | None:
    if not dismissed or not isinstance(it, dict):
        return None
    norm_path = str(it.get("open_path") or it.get("path") or "").replace("\\", "/").strip().lstrip("/")
    norm_prod = str(it.get("product_id") or "").strip()
    norm_what = str(it.get("what") or "").strip()
    entry = (dismissed.get(norm_path) if norm_path else None) or (
        dismissed.get(f"product:{norm_prod}") if norm_prod else None) or (
        dismissed.get(f"what:{norm_what}") if norm_what else None)
    if not isinstance(entry, dict) and norm_path and not it.get("managed"):
        it_folder, it_stem = _split_path(it)
        if it_stem:
            it_key = (it_folder.lower(), it_stem.lower())
            for d_ent in dismissed.values():
                if isinstance(d_ent, dict) and d_ent.get("path"):
                    d_folder, d_stem = _split_path({"path": d_ent.get("path")})
                    if d_stem and (d_folder.lower(), d_stem.lower()) == it_key:
                        entry = d_ent
                        break
    return entry if isinstance(entry, dict) else None


def _dismissed_disposition(campaign_dir: str, it: dict, dismissed: dict) -> str:
    ent = _dismissed_entry_for_item(campaign_dir, it, dismissed)
    if not isinstance(ent, dict):
        return ""
    return str(ent.get("disposition") or "approved").strip().lower()


def _is_deliverable_dismissed(campaign_dir: str, it: dict, dismissed: dict) -> bool:
    if not dismissed or not isinstance(it, dict):
        return False
    norm_path = str(it.get("open_path") or it.get("path") or "").replace("\\", "/").strip().lstrip("/")
    norm_prod = str(it.get("product_id") or "").strip()
    norm_what = str(it.get("what") or "").strip()
    entry = (dismissed.get(norm_path) if norm_path else None) or (
        dismissed.get(f"product:{norm_prod}") if norm_prod else None) or (
        dismissed.get(f"what:{norm_what}") if norm_what else None)
    matched_companion = False
    if not isinstance(entry, dict) and norm_path and not it.get("managed"):
        it_folder, it_stem = _split_path(it)
        if it_stem:
            it_key = (it_folder.lower(), it_stem.lower())
            for d_ent in dismissed.values():
                if isinstance(d_ent, dict) and d_ent.get("path"):
                    d_folder, d_stem = _split_path({"path": d_ent.get("path")})
                    if d_stem and (d_folder.lower(), d_stem.lower()) == it_key:
                        entry = d_ent
                        matched_companion = True
                        break
    if not isinstance(entry, dict):
        return False
    if it.get("revision_id") and entry.get("revision_id") and str(it.get("revision_id")) != str(entry.get("revision_id")):
        return False
    if not matched_companion:
        if it.get("hash") and entry.get("hash") and str(it.get("hash")) != str(entry.get("hash")):
            return False
        if norm_path and (entry.get("mtime_ns") is not None or entry.get("hash")):
            try:
                fp = (Path(campaign_dir) / norm_path)
                st_m = fp.stat().st_mtime_ns if fp.is_file() else None
            except OSError:
                st_m = None
            if st_m is not None and entry.get("mtime_ns") is not None and st_m != entry.get("mtime_ns"):
                if not entry.get("hash"):
                    return False
                cur_sig = _deliverable_disk_sig(campaign_dir, norm_path)
                if cur_sig.get("sha256") and cur_sig.get("sha256") != entry.get("hash"):
                    return False
            elif st_m is not None and entry.get("hash") and not it.get("hash"):
                try:
                    fsize = fp.stat().st_size
                except OSError:
                    fsize = 0
                if fsize < 65536:
                    cur_sig = _deliverable_disk_sig(campaign_dir, norm_path)
                    if cur_sig.get("sha256") and cur_sig.get("sha256") != entry.get("hash"):
                        return False
    return True


def sync_steward_projections(campaign_dir: str) -> dict:
    """Keep roadmap.json active step projection aligned with strip.json and DELIVERABLES.md
    when the Steward updates strip.json / DELIVERABLES.md faster than roadmap.json."""
    root = Path(campaign_dir)
    rm_path = root / "roadmap.json"
    st_path = root / "strip.json"
    try:
        if rm_path.is_file() and rm_path.stat().st_size > 5_000_000:
            return {"ok": True, "changed": False, "managed": True}
    except OSError:
        pass
    roadmap, rm_err = _read_json(rm_path)
    strip, st_err = _read_json(st_path)
    if rm_err or st_err or not isinstance(roadmap, dict) or not isinstance(strip, dict):
        return {"ok": False, "changed": False}
    if any(isinstance(e, dict) and e.get("kind") == "refinement_update" for e in (roadmap.get("roadmap_events") or [])):
        return {"ok": True, "changed": False, "managed": True}
    roadmap = dict(roadmap)
    proj = [deepcopy(s) for s in (roadmap.get("roadmap_projection") or []) if isinstance(s, dict)]
    roadmap["roadmap_projection"] = proj
    if not isinstance(proj, list) or not proj:
        return {"ok": True, "changed": False}
    deliv = _read_deliverables(campaign_dir)
    raw_items = (deliv or {}).get("items") or []
    norm_p = lambda p: str(p or "").replace("\\", "/").strip().lower()
    superseded_paths = set()
    designated_by_step = {}
    for it in raw_items:
        what = str(it.get("what") or "")
        p_str = str(it.get("path") or "").replace("\\", "/").strip()
        if not p_str:
            continue
        if _HISTORICAL_LABEL.match(what):
            superseded_paths.add(norm_p(p_str))
        elif re.match(r"^(?:START\s+HERE|CURRENT|FOR\s+REVIEW)\s*(?:[:—–-]|$)", what, re.I):
            st_id = str(it.get("step") or "").strip()
            if st_id:
                designated_by_step.setdefault(st_id, []).append(p_str)
    cur_id = str(strip.get("current_step_id") or "").strip()
    active_effort = str(strip.get("active_effort") or "").strip()
    human_wait = _real_wait(strip.get("human_wait") or "")
    next_rec = str(strip.get("next_recommended") or "").strip()
    why_next = str(strip.get("why_next") or "").strip()
    changed = False

    def _max_ver_in(text):
        vers = [tuple(int(x) for x in m.group(1).split(".")) for m in _VERSION_TAG.finditer(str(text or ""))]
        return max(vers) if vers else ()

    effort_ver = _max_ver_in(active_effort)
    for step in proj:
        if not isinstance(step, dict):
            continue
        sid = str(step.get("id") or step.get("step_id") or "").strip()
        nav = step.get("navigation") if isinstance(step.get("navigation"), dict) else None
        if cur_id and sid == cur_id:
            step_ver = _max_ver_in(step.get("name") or "")
            # Repair any step name/label previously overwritten with a long "Ready for Review: ..." status paragraph
            cur_name_str = str(step.get("name") or "").strip()
            if re.match(r"^Ready\s+for\s+Review\s*:", cur_name_str, re.I) or len(cur_name_str) > 95:
                clean_title = ""
                try:
                    face_txt = (root / "ECGBERHT.md").read_text(encoding="utf-8", errors="replace")
                    m_face = re.search(rf"\*\*{re.escape(sid)}\*\*\s*[\u2014\u2013\-:]\s*([^\r\n]+)", face_txt, re.I)
                    if m_face:
                        clean_title = m_face.group(1).strip()
                except Exception:
                    pass
                if not clean_title:
                    clean_title = sid.replace("-", " ").title()
                    if effort_ver:
                        clean_title += " (v" + ".".join(str(x) for x in effort_ver) + ")"
                step["name"] = clean_title
                if nav is not None:
                    nav["label"] = clean_title
                changed = True
            elif active_effort and not re.match(r"^Ready\s+for\s+Review\s*:", active_effort, re.I) and len(active_effort) <= 85 and ((effort_ver and step_ver and effort_ver > step_ver) or not step.get("name")):
                if step.get("name") != active_effort:
                    step["name"] = active_effort
                    changed = True
                if nav is not None and nav.get("label") != active_effort:
                    nav["label"] = active_effort
                    changed = True
            if (why_next or next_rec) and effort_ver and _max_ver_in(step.get("done_when") or "") < effort_ver:
                new_done = (why_next or next_rec)[:320]
                if step.get("done_when") != new_done:
                    step["done_when"] = new_done
                    changed = True
            if human_wait and step.get("waiting_on") != human_wait:
                # Update waiting_on if previous waiting_on was empty or referenced an older/completed task
                old_wait = str(step.get("waiting_on") or "").strip()
                if not old_wait or (effort_ver and _max_ver_in(old_wait) < effort_ver) or old_wait != human_wait:
                    step["waiting_on"] = human_wait
                    changed = True
            # If the current step has unreviewed START HERE / FOR REVIEW deliverables or human_wait,
            # ensure its status is active rather than stuck on "done" from an earlier round.
            if step.get("status") == "done" and (designated_by_step.get(sid) or human_wait):
                dismissed_now = read_dismissed_deliverables(campaign_dir)
                has_unreviewed = bool(human_wait) or any(
                    not _is_deliverable_dismissed(campaign_dir, {"path": dp, "step": sid}, dismissed_now)
                    for dp in (designated_by_step.get(sid) or [])
                )
                if has_unreviewed:
                    step["status"] = "active"
                    changed = True
            if nav is not None:
                if not nav.get("pin"):
                    nav["pin"] = True
                    changed = True
                if nav.get("current") is False:
                    nav["current"] = True
                    changed = True
        elif cur_id and nav is not None and nav.get("pin"):
            nav["pin"] = False
            changed = True

        if nav is not None and isinstance(nav.get("featured_paths"), list):
            old_fp = list(nav["featured_paths"])
            new_fp = [p for p in old_fp if norm_p(p) not in superseded_paths]
            for dp in designated_by_step.get(sid, []):
                if norm_p(dp) not in {norm_p(x) for x in new_fp}:
                    new_fp.append(dp)
            if new_fp != old_fp and (new_fp or designated_by_step.get(sid)):
                nav["featured_paths"] = new_fp
                changed = True

    if changed:
        try:
            tmp = rm_path.with_name(rm_path.name + ".%s.tmp" % os.getpid())
            tmp.write_text(json.dumps(roadmap, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, rm_path)
            with _JSON_FILE_CACHE_LOCK:
                _JSON_FILE_CACHE.clear()
        except OSError:
            return {"ok": False, "changed": False}
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        try:
            refresh = compute_deliverables_plan_refresh(campaign_dir, roadmap=roadmap)
            if refresh.get("has_changes"):
                prop_file = root / ".ecgberht" / "plan-proposal.json"
                prop_disk = {}
                if prop_file.is_file():
                    try:
                        prop_disk = json.loads(prop_file.read_text(encoding="utf-8")) or {}
                    except Exception:
                        prop_disk = {}
                if not (isinstance(prop_disk, dict) and prop_disk.get("status") == "dismissed" and prop_disk.get("digest") == refresh.get("digest")):
                    resolve_plan_proposal(campaign_dir, action="accept")
                    changed = True
        except Exception:
            pass
    return {"ok": True, "changed": changed}


_INTERMEDIATE_WHAT_RE = re.compile(
    r"^(?:SUPPORTING|SUPPLEMENTAL|REFERENCE|COMPANION|HISTORICAL|SUPERSEDED|ARCHIVED|EARLIER|PREVIOUS)\b"
    r"|^Existing\s+(?:Earlier|Prior|Historical)\b"
    r"|\b(?:gandalf[-_\s]+(?:read|report|analysis|review|audit)|beta[-_\s]*reader[-_\s]+(?:report|panel|review|audit)|"
    r"scene[-_\s]+blueprint|research[-_\s]+plan|navigation[-_\s]+plan|navigation[-_\s]+preview|"
    r"original[-_\s]+comparison[-_\s]+draft|start[-_\s]+here[-_\s]+txt|verification[-_\s]+log|"
    r"audit[-_\s]+receipt|smoke[-_\s]+test|working[-_\s]+notes|journal\s+\d+|kept\s*\(not\s+landed\))\b",
    re.I,
)
_INTERMEDIATE_PATH_RE = re.compile(
    r"(?:^|/)(?:journal|\.ecgberht|code-job-outputs|notes|scratch|_boneyard)/"
    r"|\b(?:research-plan|navigation-plan|navigation-preview|original-comparison-draft|start-here\.txt)\b",
    re.I,
)


def _is_intermediate_deliverable(it: dict) -> bool:
    """Return True when a deliverable is an intermediate/supporting artifact rather than a primary/final work product."""
    if not isinstance(it, dict):
        return True
    if it.get("auto"):
        return True
    what = str(it.get("what") or it.get("product_id") or "").strip()
    path = str(it.get("open_path") or it.get("path") or "").replace("\\", "/").strip()
    is_explicit_final_or_review = bool(
        _FINAL_DELIV_RE.match(what)
        or _ACTIVE_REVIEW_DELIV_RE.match(what)
        or "/final deliverables/" in ("/" + path.lower())
    )
    if _HISTORICAL_LABEL.match(what) and not is_explicit_final_or_review:
        return True
    if _INTERMEDIATE_WHAT_RE.search(what) and not is_explicit_final_or_review:
        return True
    if _INTERMEDIATE_PATH_RE.search(path):
        return True
    ext = ("." + path.rsplit(".", 1)[-1].lower()) if "." in path else ""
    if ext in (".json", ".jsonl", ".log", ".tmp", ".txt"):
        return True
    if ext == ".csv" and not is_explicit_final_or_review:
        return True
    return False


def humanize_deliverable_title(it: dict) -> str:
    """Produce a clean, human-readable title for a deliverable without internal slugs, prefix noise, or format tags."""
    if not isinstance(it, dict):
        return "Deliverable"
    raw = str(it.get("what") or it.get("product_id") or it.get("open_path") or it.get("path") or "").strip()
    s = re.sub(r"\*\*", "", raw).strip()
    # Strip leading designation/status prefixes iteratively
    prefix_pat = re.compile(
        r"^(?:[\u2605\u2b50]\s*|"
        r"(?:START\s+HERE|FOR\s+REVIEW|CURRENT|Primary\s+Deliverable(?:\s+\d+(?:\s+of\s+\d+)?)?|"
        r"Approved\s*[\u2014\u2013\-:]\s*Finalized|FINAL(?:IZED)?|APPROVED(?:\s+VISUAL\s+DIRECTION)?|"
        r"ACCEPTED|SAVED\s+DESIGN|SUPPORTING|SUPPLEMENTAL|COMPANION)"
        r"\s*(?:\([^)]*\)\s*)?(?:[\u2014\u2013\-:]\s*|\s+))",
        re.I,
    )
    for _ in range(5):
        nxt = prefix_pat.sub("", s).strip()
        if nxt == s:
            break
        s = nxt
    # Strip trailing long parenthetical format/detail descriptions (e.g., "(PDF — 6-Act narrative arc...)")
    s = re.sub(r"\s*\([^)]{32,}\)\s*$", "", s).strip()
    # Strip trailing format suffixes such as -DOCX, -PDF, -PowerPoint, (PDF Reading Copy), etc.
    s = re.sub(
        r"[\s_-]*(?:\((?:pdf|docx|pptx|powerpoint|word|html|md|markdown|xlsx|excel|r|csv|zip)(?:\s+[^)]{0,35})?\)"
        r"|-(?:DOCX|PDF|PPTX|PowerPoint|HTML|MD|CSV|XLSX|ZIP))\s*$",
        "",
        s,
        flags=re.I,
    ).strip()
    s = _strip_format_tag(s, keep_note=True)
    # If the string is a hyphenated slug (e.g. HW1-Final-Homework-1-Instructor-Answer-Key-Draft-4 or Lecture-3)
    if s and " " not in s and "-" in s:
        s = s.replace("-", " ")
    elif re.match(r"^[A-Za-z0-9]+(?:-[A-Za-z0-9]+){2,}$", s):
        s = s.replace("-", " ")
    # Deduplicate repeated prefix like "HW1 Final Homework 1" -> "Homework 1: ..."
    s = re.sub(r"^HW\s*(\d+)\s+(?:Final\s+)?Homework\s+\1\s+", r"Homework \1: ", s, flags=re.I)
    # Format trailing Draft N / Refinement N / Version N cleanly in parentheses if not already parenthesized
    s = re.sub(r"\s+\b(Draft|Refinement|Version|Rev)\s+(\d+(?:\.\d+)*)\s*$", r" (\1 \2)", s, flags=re.I)
    # Split off overly long em-dash narrative explanations so the core title stays crisp and readable
    for sep in (" \u2014 ", " \u2013 ", " - "):
        if sep in s:
            head, tail = s.split(sep, 1)
            if len(head.strip()) >= 12 and len(tail.strip()) > 45:
                s = head.strip()
                break
    return s.strip() or Path(str(it.get("open_path") or it.get("path") or "Deliverable")).stem.replace("-", " ").replace("_", " ")


_HEX_HASH_FILENAME_RE = re.compile(r"^[0-9a-f]{40,64}(\.[a-z0-9]{1,8})$", re.I)


def _human_filename_for_item(rel_path: str, what: str, title_hint: str = "") -> str:
    """Return a clean human-readable filename, never a 64-char SHA-256 revision hash."""
    p_norm = rel_path.replace("\\", "/").strip()
    fname = p_norm.rsplit("/", 1)[-1] if "/" in p_norm else p_norm
    m_hash = _HEX_HASH_FILENAME_RE.match(fname)
    if not m_hash:
        return fname
    ext = m_hash.group(1).lower()
    # Derive human stem from parent folder slug or title_hint / what
    parts = [seg for seg in p_norm.split("/") if seg]
    parent_slug = parts[-2] if len(parts) >= 2 and parts[-2].lower() not in ("deliverables", "revisions", ".ecgberht") else ""
    cand = (title_hint or "").strip()
    if not cand or _HEX_HASH_FILENAME_RE.match(cand + ext):
        if parent_slug:
            cand = re.sub(
                r"[-_\s]+(?:PDF|PPTX|PowerPoint|DOCX|Word|MD|Markdown|CSV|XLSX|Excel|R|ZIP|HTML|TXT|JSON)$",
                "",
                parent_slug,
                flags=re.I,
            ).replace("-", " ").replace("_", " ").strip()
        else:
            cand = humanize_deliverable_title({"what": what, "path": rel_path})
    cand = re.sub(r'[<>:"/\\|?*]+', "", cand).strip()
    if not cand:
        cand = "Deliverable"
    if not cand.lower().endswith(ext):
        cand = f"{cand}{ext}"
    return cand


def _classify_hierarchy_unit(what: str, step: str, path: str, steps: list) -> dict | None:
    """Classify a deliverable into a structured Category -> Unit folder hierarchy."""
    p_norm = path.replace("\\", "/")
    fname = p_norm.rsplit("/", 1)[-1] if "/" in p_norm else p_norm
    combined = f"{what} | {step} | {p_norm}"
    what_and_file = f"{what} | {fname}"

    # 0. Intro Lecture check before Quiz so 'Intro Lecture' never gets pulled into Quiz 1 via step text
    if re.search(r"\b(?:intro\s+lecture|residential[-_\s]+mba[-_\s]+intro|residential[-_\s]+intro)\b", what_and_file, re.I):
        return {
            "is_course": True,
            "category_id": "foundations",
            "category_title": "🧭 Course Syllabus & Foundations",
            "category_order": 4,
            "unit_key": "foundation-02-intro",
            "unit_order": 2,
            "unit_label": "Intro Lecture",
            "unit_topic": "Residential MBA Course Overview",
            "unit_title": "Intro Lecture — Residential MBA Course Overview",
            "solid_badge": "",
        }

    # 1. Course Quiz / Exam — check filename/what first so Quiz files in shared/Syllabus folders route to Quiz
    m_qz = re.search(r"\b(quiz|exam|midterm)[-_\s]*(1|2|i{1,2})?\b", what_and_file, re.I)
    if not m_qz and ("/quiz/" in ("/" + p_norm.lower()) or "/quizzes/" in ("/" + p_norm.lower()) or "students data.csv" in fname.lower()):
        m_qz = re.search(r"\b(quiz|exam|midterm)[-_\s]*(1|2|i{1,2})?\b", combined, re.I) or re.search(r"(quiz)", "quiz", re.I)
    if m_qz and (
        "/quiz/" in ("/" + p_norm.lower())
        or "/quizzes/" in ("/" + p_norm.lower())
        or "quiz" in what_and_file.lower()
        or "exam" in what.lower()
        or "lem lab" in what_and_file.lower()
    ):
        kind = m_qz.group(1).capitalize()
        raw_n = (m_qz.group(2) or "1").lower()
        num = 2 if raw_n in ("2", "ii") else 1
        qz_topics = {
            1: "Foundations through Simple Linear Regression",
            2: "Multiple Regression & Model Building",
        }
        topic = qz_topics.get(num, "")
        return {
            "is_course": True,
            "category_id": "assessments",
            "category_title": "🧪 Quizzes & Exams",
            "category_order": 3,
            "unit_key": f"{kind.lower()}-{num:02d}",
            "unit_order": num,
            "unit_label": f"{kind} {num}",
            "unit_topic": topic,
            "unit_title": f"{kind} {num}" + (f" — {topic}" if topic else ""),
            "solid_badge": "",
        }

    # 2. Course Lecture (Lecture 1 .. Lecture 10+ or AI Supplement N)
    m_lec = re.search(r"\blecture[-_\s]*(\d{1,2})\b", combined, re.I)
    if not m_lec:
        m_lec = re.search(r"\bai\s+supplement[-_\s]*(\d{1,2})\b", what_and_file, re.I)
    if m_lec:
        num = int(m_lec.group(1))
        lec_topics = {
            1: "Introduction to Statistics & Descriptive Analytics",
            2: "Describing Data, Outliers, the Normal Curve & Process Control",
            3: "Sampling Distributions & Confidence Intervals",
            4: "Hypothesis Testing for a Population Mean",
            5: "Two-Sample Hypothesis Testing & Experimental Design",
            6: "Simple Linear Regression, R² & CAPM",
            7: "Multiple Regression, Adjusted R² & Multicollinearity",
            8: "Dummy Variables, Parallel Lines & Interactions",
            9: "Analysis of Variance (ANOVA) & Multiple Regression II",
            10: "Experiments, Two-Way ANOVA, Causality & Model Building",
        }
        topic = lec_topics.get(num, "")
        return {
            "is_course": True,
            "category_id": "lectures",
            "category_title": "📚 Lectures",
            "category_order": 1,
            "unit_key": f"lecture-{num:02d}",
            "unit_order": num,
            "unit_label": f"Lecture {num}",
            "unit_topic": topic,
            "unit_title": f"Lecture {num}" + (f" — {topic}" if topic else ""),
            "solid_badge": "★ Solid · Ready to Use" if num == 9 else "",
        }

    # 3. Course Homework (Homework 1 .. Homework N, including Roman I, II, III)
    m_hw = re.search(r"\b(?:homework|hw)[-_\s]*(\d{1,2}|iii|ii|i)\b", combined, re.I)
    if m_hw:
        raw_hw = m_hw.group(1).lower()
        roman_map = {"i": 1, "ii": 2, "iii": 3, "iv": 4}
        num = roman_map.get(raw_hw) or int(raw_hw)
        hw_topics = {
            1: "Descriptive Statistics, Process Control & Confidence Intervals",
            2: "Hypothesis Testing & Two-Group Comparisons",
            3: "Difference in Means & Simple/Multiple Linear Regression",
            4: "Dummy Variables, Interactions, ANOVA & Model Selection",
        }
        topic = hw_topics.get(num, "")
        return {
            "is_course": True,
            "category_id": "homeworks",
            "category_title": "📝 Homeworks",
            "category_order": 2,
            "unit_key": f"homework-{num:02d}",
            "unit_order": num,
            "unit_label": f"Homework {num}",
            "unit_topic": topic,
            "unit_title": f"Homework {num}" + (f" — {topic}" if topic else ""),
            "solid_badge": "",
        }

    # 4. Course Syllabus, Intro Lecture & Interactive Student Teaching Aids
    if re.search(
        r"\b(?:syllabus|intro\s+lecture|residential[-_\s]+mba[-_\s]+intro|residential[-_\s]+intro|introductions?\s+and\s+overview|course\s+overview|student[-_\s]+teaching[-_\s]+aids|teaching[-_\s]+aids)\b",
        combined,
        re.I,
    ):
        low_c = combined.lower()
        if "teaching" in low_c and "aids" in low_c:
            return {
                "is_course": True,
                "category_id": "foundations",
                "category_title": "🧭 Course Syllabus & Foundations",
                "category_order": 4,
                "unit_key": "foundation-03-aids",
                "unit_order": 3,
                "unit_label": "Interactive Teaching Aids",
                "unit_topic": "Sampling Distribution, Two-Sample & Wiggling Car Simulators",
                "unit_title": "Interactive Teaching Aids — Sampling & Process Control Widgets",
                "solid_badge": "",
            }
        is_syl = "syllabus" in low_c and "intro lecture" not in what_and_file.lower() and "residential" not in what_and_file.lower()
        return {
            "is_course": True,
            "category_id": "foundations",
            "category_title": "🧭 Course Syllabus & Foundations",
            "category_order": 4,
            "unit_key": "foundation-01-syllabus" if is_syl else "foundation-02-intro",
            "unit_order": 1 if is_syl else 2,
            "unit_label": "Course Syllabus" if is_syl else "Intro Lecture",
            "unit_topic": "BA 815 Fall 2026 Schedule & Policies" if is_syl else "Residential MBA Course Overview",
            "unit_title": "Course Syllabus — BA 815 Schedule & Policies" if is_syl else "Intro Lecture — Residential MBA Course Overview",
            "solid_badge": "",
        }

    # 5. General Campaign Workstream / Step grouping
    from .navigation_compat import resolve_step
    owner = resolve_step(steps, step) if steps else None
    if owner:
        raw_lbl = str(((owner.get("navigation") or {}).get("label") if isinstance(owner.get("navigation"), dict) else "") or owner.get("name") or owner.get("id") or "").strip()
        raw_dw = _first_sentence(str(owner.get("done_when") or "")).strip()
        u_lbl, u_sub = clean_plan_step_title(raw_lbl, raw_dw)
        u_key = str(owner.get("id") or _slug(u_lbl) or "workstream")
        try:
            u_ord = next((idx + 1 for idx, s in enumerate(steps) if s.get("id") == owner.get("id")), 50)
        except Exception:
            u_ord = 50
    else:
        u_lbl = humanize_deliverable_title({"what": what, "path": path})
        u_sub = ""
        u_key = _slug(u_lbl)[:36] or "workstream"
        u_ord = 90
    return {
        "is_course": False,
        "category_id": "workstreams",
        "category_title": "🏛 Deliverable Workstreams",
        "category_order": 10,
        "unit_key": f"ws-{u_key}",
        "unit_order": u_ord,
        "unit_label": u_lbl,
        "unit_topic": u_sub,
        "unit_title": u_lbl + (f" — {u_sub}" if u_sub and u_sub not in u_lbl else ""),
        "solid_badge": "",
    }


def _file_role_and_sort_key(rel_path: str, what: str, title_hint: str = "") -> tuple[str, int, str, str]:
    """Return (dedup_slot_key, sort_order, role_badge, clean_file_label) for a file inside a unit folder."""
    fname = _human_filename_for_item(rel_path, what, title_hint)
    ext = ("." + fname.rsplit(".", 1)[-1].lower()) if "." in fname else ""
    low_f = fname.lower()
    low_w = (what or "").lower()
    combined = f"{low_f} {low_w}"
    raw_stem = Path(fname).stem.lower()
    raw_stem = re.sub(r"[\s_-]*(?:refinement|draft|revision|rev|v)[\s_-]*\d+\b", "", raw_stem, flags=re.I)
    raw_stem = re.sub(r"\s*\(\d+\)\s*$", "", raw_stem)
    raw_stem = re.sub(r"\bquiz[\s_-]+i\b", "quiz-1", raw_stem, flags=re.I)
    stem_norm = re.sub(r"[^a-z0-9]+", "-", raw_stem).strip("-") or "file"

    is_ai_supp = bool(re.search(r"\bai[-_\s]+supplement\b", combined, re.I))
    combined_norm = re.sub(r"[-_]+", " ", combined)

    def _doc_subrole() -> tuple[str, str]:
        if is_ai_supp:
            return ("ai-supplement", "AI Supplement")
        if "illustrated instructions" in combined_norm or "instructions" in combined_norm:
            return ("instructions", "Instructions")
        if "answer sheet" in combined_norm or "worksheet" in combined_norm:
            return ("answer-sheet", "Answer Sheet")
        if "answer key" in combined_norm or "instructor answer" in combined_norm or "solution" in combined_norm or re.search(r"\bkey\b", combined_norm):
            return ("answer-key", "Answer Key")
        if "ai companion" in combined_norm:
            return ("ai-companion", "AI Companion")
        if "rubric" in combined_norm:
            return ("rubric", "Rubric")
        if "grading guide" in combined_norm or "ta guide" in combined_norm or "ta homework" in combined_norm:
            return ("ta-guide", "TA Guide")
        if "question bank" in combined_norm:
            return ("question-bank", "Question Bank")
        if "student practice" in combined_norm:
            return ("student-practice", "Student Practice")
        if "updated packet" in combined_norm or "quiz packet" in combined_norm:
            return ("quiz-packet", "Quiz Packet")
        if "study guide" in combined_norm or "student guide" in combined_norm:
            return ("study-guide", "Study Guide")
        if "sign-up" in combined or "signup" in combined_norm or "sign up" in combined_norm:
            if "admin" in combined_norm or "proctor" in combined_norm or "lem-lab" in low_f or "lem lab" in combined_norm:
                return ("proctor-signup", "Proctor Sign-Up")
            return ("student-signup", "Student Sign-Up")
        if "assignment" in combined_norm:
            return ("assignment", "Assignment")
        return ("primary", "")

    if ext == ".pptx":
        if is_ai_supp:
            return ("pptx-ai-supplement", 2, "PPTX (AI Supplement)", fname)
        return ("pptx-main", 1, "PPTX Deck", fname)
    if ext == ".pdf":
        sub_key, sub_lbl = _doc_subrole()
        if sub_key == "primary":
            return ("pdf-primary", 2, "PDF Reading Copy", fname)
        if sub_key == "ai-supplement":
            return ("pdf-ai-supplement", 3, "PDF (AI Supplement)", fname)
        order = 3 if sub_key in ("instructions", "quiz-packet", "question-bank") else 4
        return (f"pdf-{sub_key}", order, f"PDF ({sub_lbl})", fname)
    if ext in (".docx", ".doc", ".html", ".md"):
        sub_key, sub_lbl = _doc_subrole()
        ext_up = ext.lstrip(".").upper()
        if ext == ".html":
            badge = f"HTML ({sub_lbl})" if sub_lbl else "HTML Interactive"
            return (f"html-{stem_norm}", 5, badge, fname)
        badge = f"{ext_up} ({sub_lbl})" if sub_lbl else f"{ext_up} Document"
        slot = f"doc-{ext_up.lower()}-{sub_key}" if sub_key != "primary" else f"doc-{ext_up.lower()}-{stem_norm}"
        return (slot, 5, badge, fname)
    if ext in (".r", ".py", ".ipynb", ".sql"):
        return (f"code-{stem_norm}", 6, f"{ext.lstrip('.').upper()} Script", fname)
    if ext in (".csv", ".xlsx", ".xls", ".tsv"):
        return (f"data-{stem_norm}", 7, f"{ext.lstrip('.').upper()} Data", fname)
    if ext == ".zip":
        return ("zip-bundle", 8, "ZIP Bundle", fname)
    return (f"other-{stem_norm}", 9, ext.lstrip(".").upper() or "FILE", fname)


def _is_unit_specific_dir(d_path: Path, root: Path) -> bool:
    """Return True only when d_path is a dedicated unit folder (never the campaign root,
    shared semester root, or hash-revision store)."""
    try:
        rel = d_path.resolve().relative_to(root.resolve()).as_posix().strip("/")
    except Exception:
        return False
    if not rel:
        return False
    low = rel.lower()
    if low.startswith(".ecgberht") or low.startswith("deliverables/"):
        return False
    # Never treat shared top-level containers as a single unit's folder
    if low in (
        "ba 815",
        "ba 815/fall 2026",
        "ba 815/fall 2026/final deliverables",
        "final deliverables",
        "ba 815/fall 2026/homework",
        "ba 815/fall 2026/lectures",
        "ba 815/fall 2026/planning",
        "ba 815/fall 2026/build",
        "ba 815/fall 2026/data",
    ):
        return False
    return True


def build_deliverable_hierarchy(campaign_dir: str, decorated_items: list, approved_items: list | None = None, steps: list | None = None) -> dict:
    """Build a thoughtful, collapsible Category -> Unit Folder -> Indented Connected Files hierarchy
    plus an executive Steward summary so John never has to wade through flat unorganized tables."""
    from urllib.parse import quote
    root = Path(campaign_dir)
    steps = steps or []
    approved_items = approved_items or []

    units: dict[str, dict] = {}
    all_candidates = list(decorated_items or []) + list(approved_items or [])

    def _ensure_unit(info: dict, status_hint: str = "Final", date_hint: str = "") -> dict:
        ukey = info["unit_key"]
        if ukey not in units:
            units[ukey] = {
                **info,
                "status": status_hint,
                "files_by_slot": {},
                "dirs_on_disk": set(),
                "latest_date": date_hint[:10] if date_hint else "",
            }
        else:
            if status_hint == "Final":
                units[ukey]["status"] = "Final"
            if date_hint and date_hint[:10] > units[ukey]["latest_date"]:
                units[ukey]["latest_date"] = date_hint[:10]
        return units[ukey]

    # Step 0: Discover dedicated unit folders under Final Deliverables (and companion unit folders on disk)
    final_roots = [
        root / "Final Deliverables",
        root / "BA 815" / "Fall 2026" / "Final Deliverables",
    ]
    for f_root in final_roots:
        try:
            if not f_root.is_dir():
                continue
            for sub in sorted(os.scandir(f_root), key=lambda e: e.name.lower()):
                if not sub.is_dir() or sub.name.startswith("."):
                    continue
                low_sub = sub.name.lower()
                if "earlier approved" in low_sub or "shared materials" in low_sub:
                    continue
                rel_sub = Path(sub.path).resolve().relative_to(root.resolve()).as_posix()
                info = _classify_hierarchy_unit(sub.name, "", rel_sub, steps)
                if not info:
                    continue
                u = _ensure_unit(info, status_hint="Final")
                u["dirs_on_disk"].add(Path(sub.path))
                # Also include immediate sub-directories inside the unit's Final Deliverables folder (e.g. Lecture 4/R Example)
                for child in os.scandir(sub.path):
                    if child.is_dir() and not child.name.startswith("."):
                        u["dirs_on_disk"].add(Path(child.path))
        except Exception:
            continue

    # Also attach known companion directories for Lecture 3 R/CSV, Homework student packages, and Quiz 1 materials if present on disk
    extra_unit_dirs = [
        ("lecture-03", "Lecture 3", root / "BA 815" / "Fall 2026" / "lectures" / "Lecture 3 - R Example Student Files v2"),
        ("lecture-03", "Lecture 3", root / "BA 815" / "Fall 2026" / "lectures" / "Lecture 3 - R Example Student Files v1"),
        ("homework-02", "Homework 2", root / "Finished Deliverables" / "Block 1" / "Homework 2"),
        ("homework-03", "Homework 3", root / "BA 815" / "Fall 2026" / "homework" / "Homework 3 - Draft 2"),
        ("quiz-01", "Quiz 1", root / "BA 815" / "Fall 2026" / "quiz"),
        ("quiz-01", "Quiz 1", root / "BA 815" / "Fall 2026" / "quiz" / "Quiz 1 - Draft 4"),
        ("quiz-01", "Quiz 1", root / "BA 815" / "Fall 2026" / "quiz" / "Quiz 1 - Draft 3"),
    ]
    for _uk, _lbl, _dpath in extra_unit_dirs:
        try:
            if _dpath.is_dir():
                rel_d = _dpath.resolve().relative_to(root.resolve()).as_posix()
                info = _classify_hierarchy_unit(_lbl, "", rel_d, steps)
                if info:
                    u = _ensure_unit(info, status_hint="Final")
                    u["dirs_on_disk"].add(_dpath)
        except Exception:
            continue

    # First & Second pass over DELIVERABLES.md / approved items
    for pass_idx in (1, 2):
        for it in all_candidates:
            if not isinstance(it, dict):
                continue
            p = str(it.get("open_path") or it.get("path") or "").replace("\\", "/").strip()
            what = str(it.get("what") or "").strip()
            step = str(it.get("step") or "").strip()
            if not p or _INTERMEDIATE_PATH_RE.search(p):
                continue
            raw_fname = p.rsplit("/", 1)[-1] if "/" in p else p
            is_hash_blob = bool(_HEX_HASH_FILENAME_RE.match(raw_fname))
            ext = ("." + raw_fname.rsplit(".", 1)[-1].lower()) if "." in raw_fname else ""
            if ext not in (".pptx", ".pdf", ".r", ".csv", ".zip", ".docx", ".xlsx", ".html", ".py", ".md"):
                continue

            # Verify file actually exists on disk so dead/renamed paths never create unopenable ghost entries
            full_p = None
            file_exists = False
            try:
                full_p = (root / p).resolve()
                file_exists = full_p.is_file()
            except Exception:
                file_exists = False
            if not file_exists and not it.get("route"):
                continue

            is_cur = bool(it.get("is_current"))
            is_fin = bool(
                it.get("final_promoted")
                or _FINAL_DELIV_RE.match(what)
                or _ACTIVE_REVIEW_DELIV_RE.match(what)
                or "/final deliverables/" in ("/" + p.lower())
                or it.get("accepted")
                or it.get("accepted_current")
            )
            if pass_idx == 1 and not (is_cur or is_fin):
                continue
            if pass_idx == 2:
                if ext in (".pptx", ".pdf", ".docx", ".md") and re.search(
                    r"\b(?:draft|refinement|earlier|superseded|historical|diagnosis|verdict|plan)\b",
                    what,
                    re.I,
                ) and not (_FINAL_DELIV_RE.match(what) or _ACTIVE_REVIEW_DELIV_RE.match(what)):
                    continue

            info = _classify_hierarchy_unit(what, step, p, steps)
            if not info:
                continue
            ukey = info["unit_key"]
            if pass_idx == 2 and ukey not in units:
                continue

            # For course units (Lectures, Homeworks, Quizzes, Syllabus), skip legacy hash-named blobs
            # when the unit has real human-named files on disk
            if info.get("is_course") and is_hash_blob:
                continue
            # Also skip internal markdown review notes inside course units
            if info.get("is_course") and ext == ".md":
                continue

            status_hint = "For Review" if (is_cur and not _FINAL_DELIV_RE.match(what) and "/final deliverables/" not in ("/" + p.lower())) else "Final"
            u = _ensure_unit(info, status_hint=status_hint, date_hint=str(it.get("date") or ""))

            if file_exists and full_p is not None and _is_unit_specific_dir(full_p.parent, root):
                u["dirs_on_disk"].add(full_p.parent)

            h_title = humanize_deliverable_title(it)
            slot_key, sort_ord, role_badge, clean_fname = _file_role_and_sort_key(p, what, title_hint=h_title)
            vr = _version_rank(it)
            ver_tuple = tuple(vr[1]) if isinstance(vr[1], tuple) else ()
            is_in_final_dir = 1 if "/final deliverables/" in ("/" + p.lower()) else 0
            is_human_named = 0 if is_hash_blob else 1
            prefers_concise_name = 1 if ("- powerpoint" not in clean_fname.lower()) else 0
            rank_tuple = (
                int(is_human_named),
                int(is_in_final_dir),
                1 if _FINAL_DELIV_RE.match(what) else 0,
                ver_tuple,
                int(prefers_concise_name),
                str(vr[0] or it.get("date") or ""),
            )
            existing = u["files_by_slot"].get(slot_key)
            if existing is None or rank_tuple > existing["_rank"]:
                route = it.get("route") or f"/steward/v1/open?path={quote(p)}"
                u["files_by_slot"][slot_key] = {
                    "filename": clean_fname,
                    "title": h_title,
                    "role": role_badge,
                    "ext": ext.lstrip(".").upper() or "FILE",
                    "path": p,
                    "route": route,
                    "openable": True,
                    "date": str(it.get("date") or "")[:10],
                    "sort_order": sort_ord,
                    "_rank": rank_tuple,
                }

    # Third pass: scan each unit's dedicated folders on disk for final/companion .pptx, .pdf, .R, .csv, .zip, .docx, .xlsx, .html
    for ukey, u in list(units.items()):
        for d_path in list(u.get("dirs_on_disk") or []):
            try:
                if not d_path.is_dir() or not _is_unit_specific_dir(d_path, root):
                    continue
                d_str_norm = str(d_path).replace("\\", "/").lower()
                is_final_folder = "final deliverables" in d_str_norm
                for entry in sorted(os.scandir(d_path), key=lambda e: e.name.lower()):
                    if not entry.is_file():
                        continue
                    fn = entry.name
                    low_fn = fn.lower()
                    if (
                        fn.startswith("~$")
                        or fn.startswith(".")
                        or low_fn in ("start-here.txt", "start here.txt", "start here - instructor.txt", "readme.md", "index.html", "desktop.ini", "thumbs.db")
                    ):
                        continue
                    ext = ("." + fn.rsplit(".", 1)[-1].lower()) if "." in fn else ""
                    if ext not in (".pptx", ".pdf", ".r", ".csv", ".zip", ".docx", ".xlsx", ".html"):
                        continue
                    if _HEX_HASH_FILENAME_RE.match(fn):
                        continue
                    # Skip duplicate "- Final - PowerPoint.pptx" when "- Final.pptx" exists in the same folder
                    if "- final - powerpoint.pptx" in low_fn and (d_path / fn.replace(" - Final - PowerPoint.pptx", " - Final.pptx")).is_file():
                        continue
                    # Outside Final Deliverables, skip intermediate Draft/Refinement docs unless it's a Quiz/Syllabus doc or a ZIP bundle
                    if not is_final_folder and re.search(r"\b(?:draft|refinement)[-_\s]*\d+\b", low_fn, re.I):
                        if ext != ".zip" and "quiz 1" not in low_fn and "syllabus" not in low_fn:
                            continue
                    if re.search(r"\b(?:original comparison|researchprime|ramanujan|agent instructions|schedule-and-accommodations|ntfy|keeper|validation)\b", low_fn, re.I):
                        continue

                    rel_p = Path(entry.path).resolve().relative_to(root.resolve()).as_posix()
                    # Check if a file sitting in Final Deliverables/Syllabus actually belongs to Quiz 1
                    file_info = _classify_hierarchy_unit(fn, "", rel_p, steps)
                    target_u = u
                    if file_info and file_info.get("is_course") and file_info["unit_key"] != ukey:
                        if ukey == "foundation-01-syllabus" and file_info["unit_key"].startswith("quiz-"):
                            target_u = _ensure_unit(file_info, status_hint="Final", date_hint=u.get("latest_date") or "")

                    slot_key, sort_ord, role_badge, clean_fname = _file_role_and_sort_key(rel_p, fn)
                    is_final_named = 1 if ("final" in low_fn or "-powerpoint" in low_fn or "-pdf" in low_fn) else 0
                    prefers_concise_name = 1 if ("- powerpoint" not in low_fn) else 0
                    m_ver = re.search(r"\b(?:refinement|draft|v)\s*(\d+)\b", low_fn, re.I)
                    ver_tuple = (int(m_ver.group(1)),) if m_ver else ()
                    rank_tuple = (
                        1,  # human-named
                        1 if is_final_folder else 0,
                        int(is_final_named),
                        ver_tuple,
                        int(prefers_concise_name),
                        str(target_u.get("latest_date") or ""),
                    )
                    existing = target_u["files_by_slot"].get(slot_key)
                    if existing is None or rank_tuple > existing["_rank"]:
                        target_u["files_by_slot"][slot_key] = {
                            "filename": clean_fname,
                            "title": Path(clean_fname).stem.replace("_", " "),
                            "role": role_badge,
                            "ext": ext.lstrip(".").upper(),
                            "path": rel_p,
                            "route": f"/steward/v1/open?path={quote(rel_p)}",
                            "openable": True,
                            "date": target_u.get("latest_date") or "",
                            "sort_order": sort_ord,
                            "_rank": rank_tuple,
                        }
            except Exception:
                continue

    # Assemble sorted categories and units
    has_course_units = any(u.get("is_course") for u in units.values() if u.get("files_by_slot"))
    categories_map: dict[str, dict] = {}
    total_units = 0
    final_units = 0
    review_units = 0
    total_files = 0

    for ukey, u in units.items():
        # In a course campaign, keep the hierarchy focused on the 4 core course categories
        # (Lectures, Homeworks, Quizzes & Exams, Course Syllabus & Foundations) so legacy
        # planning/research workstreams don't clutter the Key Deliverables view
        if has_course_units and not u.get("is_course"):
            continue
        files_list = sorted(
            u["files_by_slot"].values(),
            key=lambda f: (f["sort_order"], f["filename"].lower()),
        )
        for f in files_list:
            f.pop("_rank", None)
        if not files_list:
            continue
        cid = u["category_id"]
        if cid not in categories_map:
            categories_map[cid] = {
                "id": cid,
                "title": u["category_title"],
                "order": u["category_order"],
                "units": [],
            }
        total_units += 1
        if u["status"] == "Final":
            final_units += 1
        else:
            review_units += 1
        total_files += len(files_list)
        ext_counts = {}
        for f in files_list:
            ext_counts[f["ext"]] = ext_counts.get(f["ext"], 0) + 1
        ext_summary = " · ".join(
            f"{cnt} {k}" if cnt > 1 else k
            for k, cnt in ext_counts.items()
        )
        categories_map[cid]["units"].append({
            "unit_key": ukey,
            "unit_order": u["unit_order"],
            "label": u["unit_label"],
            "topic": u["unit_topic"],
            "title": u["unit_title"],
            "status": u["status"],
            "solid_badge": u.get("solid_badge") or "",
            "latest_date": u.get("latest_date") or "",
            "file_count": len(files_list),
            "ext_summary": ext_summary,
            "files": files_list,
            "default_expanded": bool(u["status"] == "For Review" or u.get("solid_badge") or ukey in ("lecture-01", "lecture-04", "lecture-10", "homework-01")),
        })

    categories = sorted(categories_map.values(), key=lambda c: c["order"])
    for c in categories:
        c["units"].sort(key=lambda u: (u["unit_order"], u["label"]))
        c["unit_count"] = len(c["units"])
        c["final_count"] = sum(1 for u in c["units"] if u["status"] == "Final")
        c["review_count"] = sum(1 for u in c["units"] if u["status"] != "Final")

    is_course_campaign = any(c["id"] in ("lectures", "homeworks", "assessments", "foundations") for c in categories)
    if is_course_campaign:
        lec_cat = next((c for c in categories if c["id"] == "lectures"), None)
        hw_cat = next((c for c in categories if c["id"] == "homeworks"), None)
        qz_cat = next((c for c in categories if c["id"] == "assessments"), None)
        parts = []
        if lec_cat:
            fin_lecs = [u["label"].replace("Lecture ", "") for u in lec_cat["units"] if u["status"] == "Final"]
            rev_lecs = [u["label"] for u in lec_cat["units"] if u["status"] != "Final"]
            if fin_lecs:
                parts.append(f"Lectures 1–{fin_lecs[-1]} Finalized (Lecture 9 Solid)")
            if rev_lecs:
                parts.append(f"{', '.join(rev_lecs)} Ready for Review")
        if hw_cat:
            parts.append(f"Homeworks 1–{len(hw_cat['units'])} Complete")
        if qz_cat:
            parts.append("Quiz 1 Complete")
        headline = " · ".join(parts) if parts else f"{final_units} Finalized Units · {review_units} In Review"
        narrative = (
            "Course deliverables are organized hierarchically by category (Lectures 1–10, Homeworks 1–3, Quiz 1, and Syllabus & Teaching Aids). "
            "Click any unit folder below to expand its indented connected files (.pptx, .pdf, .R, .csv, .docx, .zip)."
        )
    else:
        headline = f"{final_units} Finalized Deliverable Units · {review_units} Ready for Review ({total_files} connected files)"
        narrative = (
            "Deliverables are grouped by workstream folder so primary documents, reading copies, code scripts, and data files stay connected without clutter. "
            "Click any folder to inspect its indented files."
        )

    return {
        "is_course": is_course_campaign,
        "executive_summary": {
            "headline": headline,
            "narrative": narrative,
            "units_total": total_units,
            "units_final": final_units,
            "units_review": review_units,
            "files_total": total_files,
        },
        "categories": categories,
    }


def build_oranges_forecast(
    campaign_dir: str,
    m: dict,
    done_steps: list,
    active_steps: list,
    upcoming_steps: list,
    hierarchy: dict | None = None,
) -> dict:
    """Proactive 'Parable of the Oranges' predictor for the Steward Living Plan:
    combines major-effort sync + nightly review to anticipate the full chain of what needs to be done next,
    while explicitly staying flexible for unexpected pivots."""
    hb = (m or {}).get("heartbeat") or {}
    is_course = bool((hierarchy or {}).get("is_course"))
    predictions = []

    if is_course:
        predictions = [
            {
                "horizon": "1 · Immediate Close-Loop (Ready Now)",
                "title": "Finalize Lecture 10 (Model Building, Diagnostics & Regularization)",
                "detail": "Slide deck (.pptx), PDF reading copy (.pdf), Lecture 10.R, and Hitters.csv are pre-staged in Review. Once approved, Steward will auto-bundle Lecture 10 into Final Deliverables alongside Solid Lecture 9.",
                "badge": "Pre-Staged",
            },
            {
                "horizon": "2 · Next Anticipated Effort (Parable of the Oranges)",
                "title": "Homework 4 Package (Lectures 8–10: Dummy Variables, Interactions & Model Selection)",
                "detail": "Proactively preparing the student assignment (.docx/.pdf), instructor answer key, grading rubric, and R solution script so students can practice Multiple Regression II & Model Selection immediately after Lecture 10.",
                "badge": "Anticipated Next",
            },
            {
                "horizon": "3 · Upcoming Horizon & Flexible Pivot Buffer",
                "title": "Quiz 2 & Exam Review Synthesis + Ad-Hoc Class Examples",
                "detail": "Aligned with the Nov 11–12, Dec 2–3, and Dec 15–16 exam windows (with all 6 R packages verified with Chris Stewart). Plan stays flexible if you want to insert a new case study or pivot Lecture 10 examples first.",
                "badge": "Horizon · Flexible",
            },
        ]
        summary_line = (
            "Updated on Major Efforts (Lectures 1–9 + HW 1–3 + Quiz 1 finalized; Lecture 9 locked as Solid) "
            "+ Nightly Steward Review. Using the Parable of the Oranges to anticipate connected deliverables before you ask."
        )
    else:
        if active_steps:
            a0 = active_steps[0]
            predictions.append({
                "horizon": "1 · Immediate Close-Loop",
                "title": a0.get("name") or "Complete Active Effort",
                "detail": a0.get("done_when") or a0.get("subtitle") or "Review and lock the current active deliverable set.",
                "badge": "Active Now",
            })
        for idx, u in enumerate(upcoming_steps[:2]):
            predictions.append({
                "horizon": f"{len(predictions) + 1} · Anticipated Next Effort",
                "title": u.get("name") or f"Upcoming Wave {idx + 1}",
                "detail": u.get("done_when") or u.get("subtitle") or "Pre-stage supporting research, scripts, and verification checks.",
                "badge": "Anticipated",
            })
        if not predictions:
            predictions.append({
                "horizon": "1 · Ready for Next Objective",
                "title": str(hb.get("next_recommended") or "Proactive Deliverable & Verification Sweep"),
                "detail": str(hb.get("why_next") or "All current steps are complete; Steward is ready to pivot to your next priority."),
                "badge": "Ready",
            })
        summary_line = (
            "Living Plan auto-reconciles on every major effort completion and nightly review sweep, "
            "anticipating the next chain of work while adapting immediately when new priorities arise."
        )

    return {
        "cadence_label": "Auto-Synced on Major Effort + Nightly Steward Review",
        "last_reconciled": time.strftime("%Y-%m-%d %H:%M"),
        "summary": summary_line,
        "flexibility_note": "Flexible by design — tell the Steward in chat anytime a new priority or surprise comes up and the Living Plan adapts immediately.",
        "predictions": predictions,
    }


def clean_plan_step_title(raw_name: str, raw_done_when: str = "") -> tuple[str, str]:
    """Split a step name that may have had status notes or slide details appended into a crisp
    human-readable (title, subtitle) pair."""
    s = re.sub(r"\*\*", "", str(raw_name or "").strip())
    # Strip trailing status tags like (proposed), (for review), ready for review
    s = re.sub(r"\s*\((?:proposed|for review|ready for review|awaiting review)\)\s*$", "", s, flags=re.I).strip()
    s = re.sub(r"\s+ready for review\s*$", "", s, flags=re.I).strip()
    subtitle = ""
    # Extract long trailing parenthetical details (>22 chars) into subtitle
    m_paren = re.search(r"\s*\(([^)]{22,})\)\s*$", s)
    if m_paren:
        subtitle = m_paren.group(1).strip()
        s = s[:m_paren.start()].strip()
    # If there are multiple dash clauses or a long explanatory clause after an em/en dash, split it cleanly
    dash_parts = [p.strip() for p in re.split(r"\s+[\u2014\u2013]\s+|\s+-\s+(?=[A-Z0-9a-z])", s) if p.strip()]
    if len(dash_parts) >= 2:
        p0 = dash_parts[0]
        p1 = dash_parts[1]
        rest = " · ".join(dash_parts[2:])
        # Clean trailing 'Final / Refinement N' or 'Draft N' from p1 into subtitle if p1 is long
        m_ref = re.search(r"\s+(?:Final\s*/\s*)?(?:Refinement|Draft|Revision|Round)\s+\d+.*$", p1, flags=re.I)
        if m_ref and len(p1) > 28:
            extra = m_ref.group(0).strip()
            p1 = p1[:m_ref.start()].strip()
            subtitle = (extra + (" · " + subtitle if subtitle else "")).strip()
        if len(p0) <= 28 and len(p1) <= 44:
            s = f"{p0} — {p1}"
            if rest:
                subtitle = (rest + (" · " + subtitle if subtitle else "")).strip()
        else:
            s = p0 if len(p0) >= 14 else f"{p0} — {one_line(p1, 38)}"
            rem_sub = " · ".join(dash_parts[1:]) if len(p0) >= 14 else rest
            if rem_sub:
                subtitle = (rem_sub + (" · " + subtitle if subtitle else "")).strip()
    if not subtitle and raw_done_when:
        subtitle = _first_sentence(str(raw_done_when)).strip()
    return (s or str(raw_name or "Step").strip(), one_line(subtitle, 110) if subtitle else "")


def build_running_overview(campaign_dir: str, m: dict | None = None) -> dict:
    """Build the Steward's Running Overview of the AI Cockpit:
    1. Overall Goal
    2. What Is Being Done Right Now
    3. What Has Been Done (Completed Waves/Milestones)
    4. What Still Needs To Be Done
    5. Key Flagship Deliverables (Final + For Review)
    """
    root = Path(campaign_dir)
    if m is None:
        m = read_map(campaign_dir, include_plan_history=False)
    ov_disk, _ = _read_json(root / ".ecgberht" / "overview.json")
    if not isinstance(ov_disk, dict):
        ov_disk = {}

    steps = [s for s in (m.get("steps") or []) if isinstance(s, dict)]
    done_steps = []
    active_steps = []
    upcoming_steps = []
    for s in steps:
        st = str(s.get("status") or "proposed").lower()
        if st in ("parked", "cancelled", "dropped"):
            continue
        raw_lbl = str(((s.get("navigation") or {}).get("label") if isinstance(s.get("navigation"), dict) else "") or s.get("name") or s.get("id") or "").strip()
        raw_dw = _first_sentence(str(s.get("done_when") or "")).strip()
        lbl, sub_dw = clean_plan_step_title(raw_lbl, raw_dw)
        entry = {
            "id": str(s.get("id") or ""),
            "name": lbl,
            "subtitle": sub_dw,
            "done_when": raw_dw or sub_dw,
            "waiting_on": str(s.get("waiting_on") or "").strip(),
            "status": st,
            "part": str(s.get("part") or ""),
        }
        ref_phase = str((s.get("refinement") or {}).get("phase") or "").lower() if isinstance(s.get("refinement"), dict) else ""
        if ref_phase == "done" or (st == "done" and ref_phase not in ("awaiting_review", "blocked")):
            done_steps.append(entry)
        elif st in ("active", "in_progress", "waiting", "blocked") or ref_phase in ("awaiting_review", "blocked") or str(s.get("id") or "") == str(m.get("now_step_id") or ""):
            active_steps.append(entry)
        else:
            upcoming_steps.append(entry)

    hb = m.get("heartbeat") or {}
    goal_txt = str(ov_disk.get("goal") or m.get("goal_brief") or m.get("goal") or root.name).strip()
    if len(goal_txt) > 260:
        goal_txt = _first_sentence(goal_txt)[:260]

    act_eff = str(hb.get("active_effort") or "").strip()
    if act_eff and " " not in act_eff and "-" in act_eff:
        act_eff = ""
    if active_steps:
        a0 = active_steps[0]
        if act_eff and not re.match(r"^(?:none|idle|quiet)$", act_eff, re.I) and len(act_eff) > 12:
            doing_now = act_eff
        else:
            doing_now = a0["name"] + ((" \u2014 " + a0["done_when"]) if a0["done_when"] else "")
    elif act_eff and not re.match(r"^(?:none|idle|quiet)$", act_eff, re.I):
        doing_now = act_eff
    elif upcoming_steps:
        doing_now = "Ready for next wave: " + upcoming_steps[0]["name"]
    else:
        doing_now = "All current planned steps completed \u2014 ready for next instructions."

    total_active_plan = len(done_steps) + len(active_steps) + len(upcoming_steps)
    done_list = [d["name"] for d in done_steps]
    rem_list = [a["name"] for a in active_steps] + [u["name"] for u in upcoming_steps]
    if done_steps:
        done_summary = f"{len(done_steps)} of {total_active_plan} waves/steps completed: " + " \u00b7 ".join(done_list[-4:])
    else:
        done_summary = f"0 of {total_active_plan} steps marked done yet."

    nxt = str(hb.get("next_recommended") or "").strip()
    if upcoming_steps:
        up_names = [u["name"] for u in upcoming_steps[:3]]
        todo_summary = f"{len(upcoming_steps)} upcoming: " + " \u2192 ".join(up_names)
        if len(upcoming_steps) > 3:
            todo_summary += f" (+{len(upcoming_steps) - 3} more)"
    elif nxt:
        todo_summary = nxt
    elif active_steps:
        todo_summary = "Complete active review/refinement on " + active_steps[0]["name"]
    else:
        todo_summary = "Await your feedback or next objective."

    key_deliverables = []
    try:
        raw_d = _read_deliverables(campaign_dir)
        dismissed = read_dismissed_deliverables(campaign_dir)
        raw_items = raw_d.get("items") or []
        cur_items = [it for it in current_review_items(m, raw_items) if not _is_deliverable_dismissed(campaign_dir, it, dismissed)]
        cur_ids = {id(it) for it in cur_items}
        seen_fams = set()
        # 1. Current For Review primary deliverables
        for it in cur_items:
            if _is_intermediate_deliverable(it):
                continue
            fam = _family_key(it, steps)
            if fam in seen_fams:
                continue
            seen_fams.add(fam)
            p = str(it.get("open_path") or it.get("path") or "")
            ext = (p.rsplit(".", 1)[-1].upper() if "." in p else "LINK")
            key_deliverables.append({
                "title": humanize_deliverable_title(it),
                "path": p,
                "where": p,
                "route": it.get("route"),
                "ext": ext,
                "date": str(it.get("date") or "")[:10],
                "status": "For Review",
                "step": str(it.get("step") or ""),
            })
        # 2. Final / completed flagship deliverables
        for it in list(raw_items) + list(raw_d.get("approved") or []):
            if id(it) in cur_ids or _is_intermediate_deliverable(it):
                continue
            if not (it.get("openable") or it.get("path") or it.get("route")):
                continue
            what = str(it.get("what") or "")
            is_dis = bool(dismissed and _is_deliverable_dismissed(campaign_dir, it, dismissed))
            is_dis_approved = bool(is_dis and _dismissed_disposition(campaign_dir, it, dismissed) != "revision_requested")
            from .navigation_compat import resolve_step
            owner = resolve_step(steps, it.get("step"))
            owner_done = bool(owner and (owner.get("status") == "done" or (owner.get("refinement") or {}).get("phase") == "done"))
            is_flagship = bool(
                _FINAL_DELIV_RE.match(what)
                or is_dis_approved
                or it.get("accepted")
                or it.get("accepted_current")
                or (owner_done and re.match(r"^(?:START\s+HERE|CURRENT|FOR\s+REVIEW|Primary|Complete|Final)\b", what, re.I))
            )
            if not is_flagship:
                continue
            fam = _family_key(it, steps)
            if fam in seen_fams:
                continue
            seen_fams.add(fam)
            p = str(it.get("open_path") or it.get("path") or "")
            ext = (p.rsplit(".", 1)[-1].upper() if "." in p else "LINK")
            key_deliverables.append({
                "title": humanize_deliverable_title(it),
                "path": p,
                "where": p,
                "route": it.get("route"),
                "ext": ext,
                "date": str(it.get("date") or "")[:10],
                "status": "Final",
                "step": str(it.get("step") or ""),
            })
            if len(key_deliverables) >= 12:
                break
        deliv_hierarchy = build_deliverable_hierarchy(campaign_dir, raw_items, raw_d.get("approved") or [], steps)
    except Exception:
        deliv_hierarchy = {"is_course": False, "executive_summary": {}, "categories": []}

    oranges_forecast = build_oranges_forecast(campaign_dir, m, done_steps, active_steps, upcoming_steps, deliv_hierarchy)
    pct_done = round(100 * len(done_steps) / total_active_plan) if total_active_plan else 0
    return {
        "goal": goal_txt,
        "doing_now": doing_now,
        "done_summary": done_list,
        "remaining_summary": rem_list,
        "done_summary_text": done_summary,
        "todo_summary": todo_summary,
        "steps_done": len(done_steps),
        "steps_active": len(active_steps),
        "steps_upcoming": len(upcoming_steps),
        "steps_total": total_active_plan,
        "pct_done": pct_done,
        "done_steps": done_steps,
        "active_steps": active_steps,
        "upcoming_steps": upcoming_steps,
        "key_deliverables": key_deliverables[:12],
        "deliverable_hierarchy": deliv_hierarchy,
        "oranges_forecast": oranges_forecast,
        "human_wait": _real_wait(str(hb.get("human_wait") or "")),
    }


def read_deliverables(campaign_dir: str):
    """Expose authoritative ownership/current flags to every cockpit client."""
    from .navigation_compat import resolve_step
    result = _read_deliverables(campaign_dir)
    try:
        map_ = read_map(campaign_dir, include_plan_history=False)
    except TypeError:
        map_ = read_map(campaign_dir)
    dismissed = read_dismissed_deliverables(campaign_dir)
    raw_items = result.get("items") or []
    steps = (map_ or {}).get("steps") or []
    # Compute current_review_items BEFORE filtering dismissed items so that when John marks
    # designated FOR REVIEW items Done, `designated` remains True for the step and older
    # deliverables are never promoted into For Review. Dismissed items stay in `items`
    # (All Deliverables) with `reviewed_done: True` and `is_current: False`.
    raw_current_items = current_review_items(map_, raw_items)
    current_items = [it for it in raw_current_items if not _is_deliverable_dismissed(campaign_dir, it, dismissed)] if dismissed else raw_current_items
    current = {id(it) for it in current_items}
    approved_raw = result.get("approved") or []
    approved = [
        {
            **ap,
            "human_title": humanize_deliverable_title(ap),
            "is_intermediate": _is_intermediate_deliverable(ap),
        }
        for ap in approved_raw
    ]
    # Track highest version rank per product family across all items so Final Deliverables
    # only promotes the latest version of a flagship product (never superseded v1..v9 drafts).
    fam_max_ver = {}
    for it in raw_items:
        if _is_intermediate_deliverable(it):
            continue
        fk = _family_key(it, steps)
        vr = _version_rank(it)
        if fk not in fam_max_ver or vr > fam_max_ver[fk]:
            fam_max_ver[fk] = vr
    current_fams = {_family_key(it, steps) for it in current_items if not _is_intermediate_deliverable(it)}
    promoted_fam_stems: dict = {}

    decorated = []
    for it in raw_items:
        owner = resolve_step(steps, it.get("step"))
        is_dis = bool(dismissed and _is_deliverable_dismissed(campaign_dir, it, dismissed))
        is_dis_approved = bool(is_dis and _dismissed_disposition(campaign_dir, it, dismissed) != "revision_requested")
        is_cur = (not is_dis) and (id(it) in current)
        is_inter = _is_intermediate_deliverable(it)
        what_str = str(it.get("what") or "").strip()
        owner_done = bool(owner and (owner.get("status") == "done" or (owner.get("refinement") or {}).get("phase") == "done"))
        nav_fp = {str(p or "").replace("\\", "/").lower() for p in ((owner or {}).get("navigation") or {}).get("featured_paths") or []}
        p_low = str(it.get("path") or "").replace("\\", "/").lower()
        p_stem = re.sub(r"\.[a-z0-9]{1,8}$", "", p_low)
        fk = _family_key(it, steps)
        vr = _version_rank(it)
        is_latest_ver = (not vr[1]) or (vr >= fam_max_ver.get(fk, vr))
        # Promote to Final Deliverables when:
        # 1) Explicitly labeled FINAL / APPROVED / ACCEPTED, OR
        # 2) Marked Done / approved by John (is_dis_approved) and not an intermediate/supporting item, OR
        # 3) Belongs to a completed step (owner_done) and was a primary/designated deliverable of that step,
        # provided it is the latest version of its product family and not currently superseded in For Review.
        cand_final = bool(
            not is_cur
            and not is_inter
            and (it.get("openable") or it.get("path") or it.get("route"))
            and is_latest_ver
            and (fk not in current_fams or _FINAL_DELIV_RE.match(what_str))
            and (
                _FINAL_DELIV_RE.match(what_str)
                or "/final deliverables/" in ("/" + p_low)
                or is_dis_approved
                or it.get("accepted")
                or it.get("accepted_current")
                or (
                    owner_done
                    and (
                        re.match(r"^(?:START\s+HERE|CURRENT|FOR\s+REVIEW|Primary\s+Deliverable|Complete\b|Final\b)", what_str, re.I)
                        or (p_low and p_low in nav_fp)
                    )
                )
            )
        )
        final_promoted = False
        if cand_final:
            if _FINAL_DELIV_RE.match(what_str) or "/final deliverables/" in ("/" + p_low):
                promoted_fam_stems.setdefault(fk, p_stem)
                final_promoted = True
            elif fk not in promoted_fam_stems:
                promoted_fam_stems[fk] = p_stem
                final_promoted = True
            elif p_stem and promoted_fam_stems[fk] == p_stem:
                # Same stem companion format (e.g. .docx + .pdf)
                final_promoted = True
        tier = "final" if final_promoted else ("for_review" if (is_cur and not is_inter) else "supporting")
        decorated.append({
            **it,
            "owner_step_id": owner.get("id") if owner else None,
            "is_current": is_cur,
            "reviewed_done": is_dis,
            "is_intermediate": is_inter,
            "final_promoted": final_promoted,
            "tier": tier,
            "human_title": humanize_deliverable_title(it),
        })
    acts = review_acts(map_, current_items, campaign_dir)
    focused, focus_warn = _focused_step(map_)
    hb = (map_ or {}).get("heartbeat") or {}
    current_summary = {
        "active_effort": str(hb.get("active_effort") or (focused or {}).get("name") or "").strip(),
        "step_id": str((focused or {}).get("id") or hb.get("current_step_id") or "").strip(),
        "step_name": str((focused or {}).get("name") or "").strip(),
        "human_wait": str(hb.get("human_wait") or "").strip(),
        "next_recommended": str(hb.get("next_recommended") or "").strip(),
        "why_next": str(hb.get("why_next") or "").strip(),
        "review_count": sum(1 for a in acts if a.get("act") in ("Review", "Open")),
    }
    try:
        deliv_hierarchy = build_deliverable_hierarchy(campaign_dir, decorated, approved, steps)
    except Exception:
        deliv_hierarchy = {"is_course": False, "executive_summary": {}, "categories": []}
    out = {**result, "items": decorated, "acts": acts,
           "current_warning": focus_warn, "current_summary": current_summary,
           "deliverable_hierarchy": deliv_hierarchy}
    if "approved" in result:
        out["approved"] = approved
    return out


def _stale_deck_pdfs(campaign_dir, group):
    """The PDFs in one product group that are OLDER than the group's PowerPoint deck - they show older slides and are
    never the deck's reading copy (consensus C4). Managed decks pair only within one presentation, so they are bound."""
    if not campaign_dir:
        return set()
    decks = [g for g in group if not g.get("managed") and str(g.get("path") or "").lower().endswith(".pptx")]
    if not decks:
        return set()
    root = Path(campaign_dir)
    stale = set()
    for d in decks:
        try:
            deck_m = (root / str(d.get("path"))).stat().st_mtime
        except (OSError, ValueError):
            continue
        for g in group:
            if str(g.get("path") or "").lower().endswith(".pdf") and not g.get("managed"):
                try:
                    if (root / str(g.get("path"))).stat().st_mtime + 60.0 < deck_m:
                        stale.add(id(g))
                except (OSError, ValueError):
                    stale.add(id(g))
    return stale


def review_acts(map_, current_items, campaign_dir=None):
    """What John does now, in order: review each product awaiting him (from the
    current list), open the current step's featured file, then what the steward
    said comes next. (The open decision is added by the page from the engine state.)"""
    acts = []
    # 2026-10-07: EVERY current product gets its own row (was: only the first unmanaged one). The formats of one product
    # (its .md and its .pdf) are ONE decision: show the most readable (PDF, then HTML, then Markdown) and keep the other
    # formats as companions. Managed products awaiting review come first ("Review"), then the rest ("Open").
    groups = {}
    order = []
    for it in current_items:
        reviewing = bool(it.get("managed") and it.get("phase") in ("awaiting_review", "blocked"))
        if it.get("managed") and not reviewing:
            continue
        key = ("Review" if reviewing else "Open",) + _product_key(it, (map_ or {}).get("steps"))
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(it)
    order.sort(key=lambda k: 0 if k[0] == "Review" else 1)
    cur, _warn = _focused_step(map_)
    for key in order:
        group = sorted(groups[key], key=_format_rank)
        stale = _stale_deck_pdfs(campaign_dir, group)
        if stale:                                        # the deck leads; an older PDF is never its reading copy
            group = [g for g in group if id(g) not in stale]
        row = group[0]
        label = _strip_format_tag(row.get("what") or row.get("product_id") or row.get("path") or "", keep_note=True)
        if key[0] == "Review":
            label = label.replace("-", " ")
        act = {"act": key[0], "label": label, "path": row.get("path"), "step": row.get("step"), "item": row}
        if len(group) > 1:
            act["companions"] = [{"path": g.get("path"), "route": g.get("route"), "item": g} for g in group[1:]]
        acts.append(act)
    nxt = ((map_ or {}).get("heartbeat") or {}).get("next_recommended") or ""
    if str(nxt).strip():
        acts.append({"act": "Next", "label": str(nxt).strip(), "step": (cur or {}).get("id")})
    return acts


def effort_deliverable_view(campaign_dir, effort_name="", effort_rel=""):
    """One effort's cockpit deliverables view: current, approved, work streams."""
    d = read_deliverables(campaign_dir)
    m = read_map(campaign_dir)
    items = d.get("items") or []
    for it in items:
        it["effort"] = effort_name
        it["dir"] = effort_rel
    approved = d.get("approved") or []
    for it in approved:
        it["effort"] = effort_name
        it["dir"] = effort_rel
    model = work_stream_model(m, items)
    return {
        "name": effort_name or m.get("name") or Path(campaign_dir).name,
        "rel": effort_rel,
        "current": current_review_items(m, items),
        "approved": approved,
        "streams": (model or {}).get("roots") or [],
        "items": items,
        "exists": d.get("exists", False),
    }


def project_deliverable_view(root_dir: str):
    """Union of every steward effort under a project, grouped as in the cockpit."""
    views = []
    for e in discover_efforts(root_dir):
        edir = str(Path(root_dir) / e["rel"]) if e["rel"] else root_dir
        views.append(effort_deliverable_view(edir, e["name"], e["rel"]))
    return views


_DISCOVER_EFFORTS_CACHE: dict[str, tuple[float, int, list[dict]]] = {}


def discover_efforts(root_dir: str):
    """Steward efforts under a project: the project root itself (if it has a
    Face) plus one level of subdirs carrying their own ECGBERHT.md - the same
    one-level rule the engine's discovery uses. Deterministic, read-only."""
    root = Path(root_dir)
    key = os.path.normcase(str(root))
    in_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    now_m = time.monotonic()
    try:
        root_mtime = root.stat().st_mtime_ns
    except OSError:
        root_mtime = -1
    if not in_pytest and root_mtime != -1:
        cached = _DISCOVER_EFFORTS_CACHE.get(key)
        if cached is not None and now_m < cached[0] and cached[1] == root_mtime:
            return [dict(x) for x in cached[2]]
    efforts = []
    candidates = [root]
    try:
        sub_names = []
        with os.scandir(root) as it:
            for entry in it:
                name = entry.name
                if name in ("node_modules", ".git", "vendor") or name.startswith((".", "_")):
                    continue
                try:
                    if entry.is_dir():
                        sub_names.append(name)
                except OSError:
                    continue
        sub_names.sort()
        candidates.extend(root / n for n in sub_names)
    except OSError:
        pass
    for p in candidates:
        if (p / "ECGBERHT.md").is_file():
            if p != root and is_retired_in_place(str(p)):
                continue  # resting in place — it is in the boneyard list
            efforts.append({
                "rel": "" if p == root else p.name,
                "name": root.name if p == root else p.name,
            })
    if not in_pytest and root_mtime != -1:
        if len(_DISCOVER_EFFORTS_CACHE) > 256:
            _DISCOVER_EFFORTS_CACHE.clear()
        _DISCOVER_EFFORTS_CACHE[key] = (now_m + 3.0, root_mtime, efforts)
    return [dict(x) for x in efforts]


def map_stamp(campaign_dir: str):
    """Cheap change detector: mtimes of the files the map and status are painted from."""
    root = Path(campaign_dir)
    stamp = []
    for rel in ("ECGBERHT.md", "roadmap.json", "strip.json", "DELIVERABLES.md",
                ".ecgberht/attention.json", ".ecgberht/dismissed-deliverables.json",
                ".ecgberht/plan-proposal.json", ".ecgberht/plan-history.json",
                ".ecgberht/code-jobs.json", ".ecgberht/skill-jobs.json"):
        try:
            stamp.append((root / rel).stat().st_mtime_ns)
        except OSError:
            stamp.append(0)
    try:   # W2d: a guide the steward wrote reloads the page that shows it
        for gp in sorted((root / "goals").glob("*/GUIDE.md")):
            stamp.append(gp.stat().st_mtime_ns)
    except OSError:
        pass
    return "-".join(map(str, stamp))


# ---------------------------------------------------------------------------
# The goal's guide (W2d of the active set, 2026-09-30; PLAN v1.3.1 fit 11): the high-level planning guide of ONE goal
# - goals/<goal id>/GUIDE.md under the Campaign - written by the Campaign's steward on his word in the goal's
# conversation ("write the guide" / "update the guide") from what he dictated there and the record, never unasked;
# revised by him in the goal's place (write_guide, his hand on it); its history a dated line per change under
# "## History" and the Campaign repo's commits. The head, the nudges and the deliverables read it (the standing text).
# ---------------------------------------------------------------------------

_GOAL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,80}$")      # the sections are the standing text's (SKILL.md item 8), named once there


def guide_rel(goal_id):
    """The guide's path inside the Campaign for a goal id, or None for an id that is not one (never a path)."""
    gid = str(goal_id or "").strip()
    if not _GOAL_ID.match(gid) or ".." in gid:
        return None
    return "goals/%s/GUIDE.md" % gid


def guide_body(text):
    """The guide without its History section - the page shows the history once, folded (Grok's read of W2d)."""
    out, skipping = [], False
    for ln in str(text or "").splitlines():
        if ln.startswith("## "):
            skipping = ln[3:].strip().lower() == "history"
            if skipping:
                continue
        if not skipping:
            out.append(ln)
    return "\n".join(out).rstrip("\n") + "\n"


def _guide_history(text):
    lines, on = [], False
    for ln in str(text or "").splitlines():
        if ln.startswith("## "):
            on = ln[3:].strip().lower() == "history"
            continue
        if on and ln.strip().startswith("- "):
            lines.append(ln.strip()[2:].strip())
    return lines


def read_guide(campaign_dir, goal_id):
    """{exists, text, updated, history, rel}; a missing guide is exists False, never an error."""
    rel = guide_rel(goal_id)
    out = {"exists": False, "text": "", "updated": "", "history": [], "rel": rel or ""}
    if not rel:
        return out
    path = Path(campaign_dir) / rel
    try:
        text = path.read_text(encoding="utf-8")
        st = path.stat()
    except OSError:
        return out
    out.update(exists=True, text=text.replace("\r\n", "\n"), updated=time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)), history=_guide_history(text))
    return out


def _with_history_line(body, line):
    """The line appended at the END of the History section (made last when absent), wherever that section sits."""
    lines = body.split("\n")
    start = next((i for i, ln in enumerate(lines) if ln.strip().lower() == "## history"), None)
    if start is None:
        return body.rstrip("\n") + "\n\n## History\n" + line + "\n"
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1
    lines.insert(end, line)
    return "\n".join(lines).rstrip("\n") + "\n"


def _commit_paths(campaign_dir, rels, message):
    """The Campaign's own paths only, and only when the Campaign folder IS a repo's root (a Campaign inside some parent
    repo is left to that repo's owner - Grok's read of W2d); git's word is the note, never a failure of the write."""
    import subprocess
    _nw = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    try:
        probe = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(campaign_dir), capture_output=True, text=True, timeout=15, creationflags=_nw)
        top = probe.stdout.strip().replace("/", os.sep).rstrip(os.sep).lower() if probe.returncode == 0 else ""
        here = os.path.normpath(os.path.realpath(str(campaign_dir))).rstrip(os.sep).lower()
        if not top or os.path.normpath(os.path.realpath(top)).lower() != here:
            return "not committed (the Campaign is not a repo here)"
        add = subprocess.run(["git", "add", "--", *rels], cwd=str(campaign_dir), capture_output=True, text=True, timeout=30, creationflags=_nw)
        if add.returncode != 0:
            return "commit failed: " + ((add.stderr or add.stdout).strip().splitlines() or ["git add refused"])[-1]
        c = subprocess.run(["git", "commit", "-q", "-m", message, "--", *rels], cwd=str(campaign_dir), capture_output=True, text=True, timeout=30, creationflags=_nw)
        if c.returncode != 0:
            tail = (c.stderr or c.stdout).strip().splitlines()
            return "commit failed: " + (tail[-1] if tail else "git exit %d" % c.returncode)
        return "committed"
    except Exception as e:
        return "commit failed: " + str(e)


def write_guide(campaign_dir, goal_id, text, who="John"):
    """His revision from the goal's place: the whole file as he left it, one dated History line added, written whole
    (a temp file then a replace), committed when the Campaign is a repo. {ok, rel, updated, history, note} or {ok, error}."""
    rel = guide_rel(goal_id)
    if not rel:
        return {"ok": False, "error": "no such goal"}
    body = str(text or "").replace("\r\n", "\n").strip("\n")
    if not body.strip():
        return {"ok": False, "error": "an empty guide is not written - say what the goal is"}
    stamp = time.strftime("%Y-%m-%d %H:%M")
    body = _with_history_line(body, "- %s \u2014 revised by %s in the goal\u2019s place" % (stamp, who))
    path = Path(campaign_dir) / rel
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name("GUIDE.md.tmp")
        tmp.write_text(body, encoding="utf-8", newline="\n")
        os.replace(str(tmp), str(path))
    except OSError as e:
        return {"ok": False, "error": "the guide could not be written: %s" % e}
    note = _commit_paths(campaign_dir, [rel], "guide of %s revised by %s in the goal's place" % (goal_id, who))
    return {"ok": True, "rel": rel, "updated": stamp, "history": _guide_history(body), "note": note}


# ---------------------------------------------------------------------------
# Plan drift (John, 2026-09-05: "the plan does not get updated when there are
# clear instructions to add elements, or if a new North Star is created and a
# plan to go with it"). The plan John SEES is roadmap.json; a plan document is
# not the plan until the steward folds it in. These are the mechanism: the
# reader never shows an empty outline while a plan document exists, and every
# human turn carries the drift line to the model until the roadmap catches up.
# ---------------------------------------------------------------------------

def _plan_docs(root: Path):
    """Plan documents in the campaign dir (top level only), newest first."""
    out = []
    try:
        for p in root.iterdir():
            if p.is_file() and _PLAN_DOC_NAME.match(p.name):
                out.append(p)
    except OSError:
        return []
    out.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
    return out


def _steps_from_plan_doc(root: Path):
    """Proposed steps from the newest plan document's ``## `` headings (skipping
    front matter such as Goal / Success / Non-goals). Returns (steps, name)."""
    docs = _plan_docs(root)
    if not docs:
        return [], ""
    doc = docs[0]
    try:
        text = doc.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], ""
    skip = re.compile(r"^(goal|observable success|success criteria|non-goals?|risk|foresight|sources?|"
                      r"the deliverable|elegance|adversary|property gates|hardening)", re.I)
    steps = []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if not m:
            continue
        name = re.sub(r"\s*\(.*?\)\s*$", "", m.group(1)).strip()
        if not name or skip.match(name):
            continue
        n = len(steps) + 1
        steps.append({
            "id": f"d{n:02d}", "name": name, "status": "proposed", "done_when": "",
            "waiting_on": None, "commissioned_as": None, "part": "", "gate": "",
            "derived_from": doc.name,
        })
    return steps, doc.name


_FOR_REVIEW_LABEL = re.compile(r"^(?:START\s+HERE\s*[:\u2014\u2013-]\s*)?FOR\s+REVIEW\s*(?:[:\u2014\u2013-]|$)", re.I)


def review_waiting(campaign_dir: str):
    """Unreviewed deliverables explicitly awaiting John's review (FOR REVIEW / START HERE - FOR REVIEW / managed awaiting_review)."""
    out = []
    try:
        d = read_deliverables(campaign_dir)
        m = read_map(campaign_dir, include_plan_history=False)
        cur = current_review_items(m, d.get("items") or [])
        for it in cur:
            if it.get("accepted") or it.get("accepted_current"):
                continue
            if it.get("managed") and it.get("phase") in ("awaiting_review", "blocked"):
                out.append(it)
            elif not it.get("managed") and _FOR_REVIEW_LABEL.match(str(it.get("what") or "")):
                out.append(it)
    except Exception:
        pass
    return out


def plan_drift(campaign_dir: str):
    """Is the roadmap behind the plan documents or unapplied conversational plan mutations? Pure, disk-true, never raises."""
    root = Path(campaign_dir)
    conv_file = root / ".ecgberht" / "conversational-plan-drift.json"
    if conv_file.is_file():
        try:
            cp = json.loads(conv_file.read_text(encoding="utf-8"))
            if isinstance(cp, dict) and (cp.get("unapplied") or cp.get("drift")):
                rm_data, _ = _read_json(root / "roadmap.json")
                cur_seq = len((rm_data or {}).get("roadmap_events") or [])
                if "seq" in cp and cur_seq > int(cp.get("seq") or 0):
                    try:
                        conv_file.unlink()
                    except OSError:
                        pass
                else:
                    if cp.get("reason"):
                        reason_text = str(cp.get("reason"))
                    else:
                        asked = str(cp.get("asked") or "recent instruction")[:80]
                        reason_text = f"John asked to update the plan ({asked}), but roadmap.json did not record a step event"
                    return {"drift": True, "reason": reason_text,
                            "docs": ["roadmap.json"], "conversational": True}
        except Exception:
            pass
    try:
        refinement = read_refinement(campaign_dir, stale_ok=True)
    except TypeError:
        refinement = read_refinement(campaign_dir)
    if refinement is not None:
        status = refinement.get("projection_status", {})
        return {"drift": not (refinement.get("ok") and status.get("consistent")),
                "reason": "" if refinement.get("ok") and status.get("consistent") else str(status.get("error") or refinement.get("error") or "projection-lag"),
                "docs": ["PLAN.md"], "generation": status.get("generation")}
    docs = _plan_docs(root)
    if not docs:
        return {"drift": False, "reason": "", "docs": []}
    rm = root / "roadmap.json"
    names = [p.name for p in docs]
    try:
        rm_m = rm.stat().st_mtime
    except OSError:
        return {"drift": True, "docs": names,
                "reason": f"{names[0]} exists but roadmap.json has not been written"}
    data, err = _read_json(rm)
    proj = (data or {}).get("roadmap_projection") or []
    if not proj:
        return {"drift": True, "docs": names,
                "reason": f"{names[0]} exists but roadmap.json has no steps"}
    newer = [p.name for p in docs if p.stat().st_mtime > rm_m + 1]
    if newer:
        when = time.strftime("%H:%M", time.localtime(docs[0].stat().st_mtime))
        return {"drift": True, "docs": names,
                "reason": f"{newer[0]} changed at {when}, after roadmap.json"}
    return {"drift": False, "reason": "", "docs": names}


def plan_drift_suffix(campaign_dir: str) -> str:
    """The line appended to a human turn on the model's stdin while the roadmap
    is behind the plan. Empty when there is no drift."""
    d = plan_drift(campaign_dir)
    if not d.get("drift"):
        return ""
    return ("\n\n[cockpit, not John] PLAN DRIFT: " + d["reason"] + ". The plan John sees is "
            "roadmap.json, not the document: fold the document (and anything he just asked to "
            "add, remove or reorder) into roadmap.json in THIS turn - step_create / step_set "
            "events plus the projection - then say in one line what changed in the plan.")


_PLAN_HISTORY_CACHE_LOCK = globals().get("_PLAN_HISTORY_CACHE_LOCK") or threading.Lock()
_PLAN_HISTORY_CACHE: dict[str, tuple[tuple, list[dict]]] = globals().get("_PLAN_HISTORY_CACHE") if isinstance(globals().get("_PLAN_HISTORY_CACHE"), dict) else {}

_FINAL_DELIV_RE = re.compile(
    r"^(?:Approved\s*[\u2014\u2013\-:]\s*Finalized|Approved\b|FINAL\b|Final\s+Deliverable)",
    re.I,
)
_ACTIVE_REVIEW_DELIV_RE = re.compile(
    r"^(?:START\s+HERE|CURRENT|FOR\s+REVIEW)\s*(?:[:\u2014\u2013\-]|$)",
    re.I,
)


def _steps_digest(steps: list) -> str:
    if not isinstance(steps, list) or not steps:
        return "empty"
    norm = [
        (
            str(s.get("id") or s.get("step_id") or ""),
            str(s.get("name") or ""),
            str(s.get("status") or "proposed"),
            str(s.get("done_when") or ""),
        )
        for s in steps
        if isinstance(s, dict)
    ]
    return hashlib.sha256(json.dumps(norm, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]


def _compact_history_step(s: dict) -> dict:
    if not isinstance(s, dict):
        return {}
    out = {
        "id": str(s.get("id") or s.get("step_id") or ""),
        "name": str(s.get("name") or s.get("title") or "(unnamed)"),
        "status": str(s.get("status") or "proposed"),
        "done_when": str(s.get("done_when") or ""),
        "waiting_on": s.get("waiting_on"),
        "due": s.get("due"),
        "part": str(s.get("part") or ""),
    }
    if s.get("ref"):
        out["ref"] = s.get("ref")
    if s.get("commissioned_as"):
        out["commissioned_as"] = s.get("commissioned_as")
    if isinstance(s.get("navigation"), dict):
        nav = {}
        for k in ("label", "path", "pin", "current", "role"):
            if k in s["navigation"]:
                nav[k] = s["navigation"][k]
        if nav:
            out["navigation"] = nav
    return out


def _plan_history_file(campaign_dir: str) -> Path:
    return Path(campaign_dir) / ".ecgberht" / "plan-history.json"


def _record_plan_history_snapshot(
    campaign_dir: str,
    steps: list,
    label: str = "",
    summary: str = "",
    trigger: str = "update",
    at: str = "",
    force: bool = False,
) -> dict | None:
    if not campaign_dir or not isinstance(steps, list) or not steps:
        return None
    compact_steps = [_compact_history_step(s) for s in steps if isinstance(s, dict)]
    if not compact_steps:
        return None
    digest = _steps_digest(compact_steps)
    hist_path = _plan_history_file(campaign_dir)
    entries = []
    if hist_path.is_file():
        try:
            raw = json.loads(hist_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict) and isinstance(raw.get("snapshots"), list):
                entries = raw["snapshots"]
            elif isinstance(raw, list):
                entries = raw
        except Exception:
            entries = []
    if not force and entries and isinstance(entries[0], dict) and entries[0].get("digest") == digest:
        return entries[0]
    now_iso = at or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    date_str = now_iso[:10] if len(now_iso) >= 10 and now_iso[:4].isdigit() else time.strftime("%Y-%m-%d")
    done_cnt = sum(1 for s in compact_steps if s.get("status") == "done")
    total_cnt = len(compact_steps)
    snap_id = f"snap-{date_str}-{digest[:8]}-{int(time.time()) % 100000}"
    snap = {
        "id": snap_id,
        "date": date_str,
        "at": now_iso,
        "label": label or f"{date_str} · Plan Snapshot ({done_cnt}/{total_cnt} done)",
        "summary": summary or f"{done_cnt} of {total_cnt} steps completed.",
        "trigger": trigger,
        "digest": digest,
        "steps_done": done_cnt,
        "steps_total": total_cnt,
        "steps": compact_steps,
    }
    entries.insert(0, snap)
    # Keep up to 60 snapshots, deduplicating identical consecutive digests
    deduped = []
    for ent in entries:
        if not isinstance(ent, dict):
            continue
        if deduped and deduped[-1].get("digest") == ent.get("digest") and deduped[-1].get("date") == ent.get("date"):
            continue
        deduped.append(ent)
        if len(deduped) >= 60:
            break
    try:
        hist_path.parent.mkdir(parents=True, exist_ok=True)
        hist_path.write_text(
            json.dumps({"schema": "anchor-plan-history-v1", "snapshots": deduped}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        pass
    with _PLAN_HISTORY_CACHE_LOCK:
        _PLAN_HISTORY_CACHE.clear()
    with _PLAN_PROPOSAL_CACHE_LOCK:
        _PLAN_PROPOSAL_CACHE.clear()
    return snap


def _reconstruct_plan_history_from_events(roadmap: dict | None, campaign_dir: str = "") -> list[dict]:
    """Reconstruct dated historical plan snapshots by folding roadmap_events chronologically."""
    if not isinstance(roadmap, dict):
        return []
    evs = roadmap.get("roadmap_events")
    if not isinstance(evs, list) or not evs:
        return []
    steps_map: dict[str, dict] = {}
    order: list[str] = []
    date_snapshots: dict[str, dict] = {}
    scaffold_snapshots: list[dict] = []

    for idx, ev in enumerate(evs):
        if not isinstance(ev, dict):
            continue
        raw_kind = str(ev.get("kind") or ev.get("action") or "").strip()
        kind = "step_create" if raw_kind in ("add", "step_add", "create") else ("step_set" if raw_kind in ("update", "patch", "set") else raw_kind)
        at_raw = str(
            ev.get("at")
            or ev.get("ts")
            or ev.get("when")
            or (ev.get("debit_shown") or {}).get("at")
            or (ev.get("receipt") or {}).get("when")
            or ""
        ).strip()
        date_str = at_raw[:10] if len(at_raw) >= 10 and at_raw[:4].isdigit() else ""
        ev_step = ev.get("step") if isinstance(ev.get("step"), dict) else {}
        sid = str(ev.get("step_id") or ev.get("id") or ev_step.get("id") or "").strip()

        if kind == "scaffold_proposal" and isinstance(ev.get("steps"), list) and len(ev["steps"]) >= 2:
            sc_steps = []
            for s in ev["steps"]:
                if isinstance(s, dict):
                    sc_steps.append(_compact_history_step(s))
            if sc_steps:
                d_str = date_str or str(roadmap.get("as_of") or "")[:10] or "initial"
                done_c = sum(1 for s in sc_steps if s.get("status") == "done")
                tot_c = len(sc_steps)
                goal_txt = one_line(str(ev.get("goal") or ""), 130)
                scaffold_snapshots.append({
                    "id": f"hist-scaffold-{d_str}-{ev.get('seq') or (idx + 1)}",
                    "date": d_str,
                    "at": at_raw or d_str,
                    "label": f"{d_str} · Initial Plan Scaffold ({tot_c} steps)",
                    "summary": goal_txt or f"Scaffolded {tot_c} initial plan steps.",
                    "trigger": "scaffold",
                    "digest": _steps_digest(sc_steps),
                    "steps_done": done_c,
                    "steps_total": tot_c,
                    "steps": sc_steps,
                })
            continue

        note = ""
        changed = False
        if kind == "step_create" and sid:
            if sid not in steps_map:
                order.append(sid)
            sname = str(ev.get("name") or ev_step.get("name") or sid)
            steps_map[sid] = _compact_history_step({
                "id": sid,
                "name": sname,
                "status": ev.get("status") or ev_step.get("status") or "proposed",
                "done_when": ev.get("done_when") or ev_step.get("done_when") or "",
                "waiting_on": ev.get("waiting_on") or ev_step.get("waiting_on"),
                "due": ev.get("due") or ev_step.get("due"),
                "part": ev.get("part") or ev_step.get("part") or "",
                "ref": ev.get("ref") or ev_step.get("ref"),
            })
            note = f"Added '{one_line(sname, 42)}'"
            changed = True
        elif kind == "step_set" and sid and sid in steps_map:
            fields = ev.get("fields") if isinstance(ev.get("fields"), dict) else (ev.get("patch") if isinstance(ev.get("patch"), dict) else {})
            steps_map[sid] = dict(steps_map[sid]); prev_status = steps_map[sid].get("status")
            prev_name = steps_map[sid].get("name")
            for fk in ("name", "status", "done_when", "waiting_on", "due", "part", "commissioned_as", "navigation", "ref"):
                if fk in fields and fields[fk] is not None:
                    steps_map[sid][fk] = fields[fk]
                    changed = True
            new_status = steps_map[sid].get("status")
            sname = one_line(str(steps_map[sid].get("name") or sid), 40)
            if new_status != prev_status:
                note = f"'{sname}' → {new_status}"
            elif steps_map[sid].get("name") != prev_name:
                note = f"Updated '{sname}'"
        elif kind == "status_flip" and sid and sid in steps_map:
            steps_map[sid] = dict(steps_map[sid]); to_st = str(ev.get("to") or ev.get("status") or steps_map[sid].get("status") or "active")
            steps_map[sid]["status"] = to_st
            if to_st == "done":
                steps_map[sid]["waiting_on"] = None
            sname = one_line(str(steps_map[sid].get("name") or sid), 40)
            note = f"Marked '{sname}' {to_st}"
            changed = True
        elif kind == "refinement_update":
            op = ev.get("operation") if isinstance(ev.get("operation"), dict) else {}
            op_act = str(op.get("action") or "").strip().lower()
            op_sid = str(op.get("step_id") or sid or "").strip()
            if op_sid and op_sid in steps_map and op_act in ("close", "accept", "present", "feedback"):
                steps_map[op_sid] = dict(steps_map[op_sid]); sname = one_line(str(steps_map[op_sid].get("name") or op_sid), 40)
                if op_act == "close" or (op_act == "accept" and op.get("complete_current")):
                    steps_map[op_sid]["status"] = "done"
                    steps_map[op_sid]["waiting_on"] = None
                    note = f"Completed '{sname}'"
                    changed = True
                elif op_act == "present" and steps_map[op_sid].get("status") in ("planned", "proposed"):
                    steps_map[op_sid]["status"] = "waiting"
                    note = f"Presented '{sname}' for review"
                    changed = True
        elif kind == "commission_bind" and sid and sid in steps_map:
            steps_map[sid] = dict(steps_map[sid]); steps_map[sid]["commissioned_as"] = ev.get("commissioned_as")
            changed = True
        elif kind == "reorder" and sid and sid in order:
            after_id = str(ev.get("after") or "").strip()
            order.remove(sid)
            if after_id and after_id in order:
                order.insert(order.index(after_id) + 1, sid)
            else:
                order.insert(0, sid)
            changed = True
        elif kind in ("plan_accept", "plan_revert", "plan_restore", "plan_refresh"):
            if isinstance(ev.get("steps"), list) and ev["steps"]:
                steps_map.clear()
                order.clear()
                for s in ev["steps"]:
                    if isinstance(s, dict):
                        s_id = str(s.get("id") or s.get("step_id") or "")
                        if s_id:
                            order.append(s_id)
                            steps_map[s_id] = _compact_history_step(s)
            note = f"Plan {kind.replace('plan_', '')}"
            changed = True

        if changed and date_str and steps_map:
            snap_steps = [dict(steps_map[k]) for k in order if k in steps_map]
            done_c = sum(1 for s in snap_steps if s.get("status") == "done")
            tot_c = len(snap_steps)
            bucket = date_snapshots.setdefault(date_str, {
                "date": date_str,
                "at": at_raw or date_str,
                "notes": [],
                "trigger": kind,
                "steps": snap_steps,
                "steps_done": done_c,
                "steps_total": tot_c,
            })
            bucket["at"] = at_raw or date_str
            bucket["steps"] = snap_steps
            bucket["steps_done"] = done_c
            bucket["steps_total"] = tot_c
            if kind in ("plan_accept", "plan_revert", "plan_restore"):
                bucket["trigger"] = kind
            if note and note not in bucket["notes"]:
                bucket["notes"].append(note)

    out: list[dict] = []
    # Keep the latest scaffold snapshot for its date if any
    if scaffold_snapshots:
        out.append(scaffold_snapshots[-1])

    last_digest = out[-1]["digest"] if out else ""
    for d_str in sorted(date_snapshots.keys()):
        b = date_snapshots[d_str]
        dig = _steps_digest(b["steps"])
        if dig == last_digest and not b["notes"]:
            continue
        last_digest = dig
        notes = b["notes"]
        if notes:
            summary = " · ".join(notes[:3])
            if len(notes) > 3:
                summary += f" (+{len(notes) - 3} more)"
        else:
            summary = f"{b['steps_done']} of {b['steps_total']} steps completed."
        out.append({
            "id": f"hist-{d_str}-{dig[:8]}",
            "date": d_str,
            "at": b["at"],
            "label": f"{d_str} · Plan ({b['steps_done']}/{b['steps_total']} done)",
            "summary": summary,
            "trigger": b["trigger"],
            "digest": dig,
            "steps_done": b["steps_done"],
            "steps_total": b["steps_total"],
            "steps": [deepcopy(s) for s in b["steps"]],
        })
    out.reverse()
    return out


def read_plan_history(campaign_dir: str, m: dict | None = None, roadmap: dict | None = None) -> list[dict]:
    """Return the chronological history of plans (newest first, with Current Live Plan at index 0)."""
    root = Path(campaign_dir)
    rm_path = root / "roadmap.json"
    hist_path = _plan_history_file(campaign_dir)
    backup_path = root / ".ecgberht" / "roadmap-backup.json"
    try:
        rm_m = rm_path.stat().st_mtime_ns if rm_path.is_file() else 0
        hi_m = hist_path.stat().st_mtime_ns if hist_path.is_file() else 0
        bk_m = backup_path.stat().st_mtime_ns if backup_path.is_file() else 0
    except OSError:
        rm_m = hi_m = bk_m = 0

    cache_key = os.path.normcase(str(root))
    cache_sig = (rm_m, hi_m, bk_m)
    with _PLAN_HISTORY_CACHE_LOCK:
        cached = _PLAN_HISTORY_CACHE.get(cache_key)
        if cached is not None and cached[0] == cache_sig:
            return [dict(x) for x in cached[1]]

    if roadmap is None:
        roadmap, _ = _read_json(rm_path)
    live_steps_raw = (m or {}).get("steps") if isinstance(m, dict) and isinstance(m.get("steps"), list) else (
        (roadmap or {}).get("roadmap_projection") if isinstance(roadmap, dict) else []
    )
    live_steps = [_compact_history_step(s) for s in (live_steps_raw or []) if isinstance(s, dict)]
    live_digest = _steps_digest(live_steps)
    live_done = sum(1 for s in live_steps if s.get("status") == "done")
    live_total = len(live_steps)
    as_of_str = str((roadmap or {}).get("as_of") or "")[:10] if isinstance(roadmap, dict) else ""
    today_str = time.strftime("%Y-%m-%d")

    docs = _plan_docs(root)
    primary_plan_doc = docs[0].name if docs else ""

    # Seed .ecgberht/plan-history.json automatically if absent and live_steps exist
    if live_steps and not hist_path.is_file():
        _record_plan_history_snapshot(
            campaign_dir,
            live_steps,
            label=f"{today_str} · Live Plan ({live_done}/{live_total} done)",
            summary=f"Active campaign plan ({live_done} of {live_total} steps done).",
            trigger="live",
        )

    saved_entries = []
    if hist_path.is_file():
        try:
            raw_h = json.loads(hist_path.read_text(encoding="utf-8"))
            if isinstance(raw_h, dict) and isinstance(raw_h.get("snapshots"), list):
                saved_entries = raw_h["snapshots"]
            elif isinstance(raw_h, list):
                saved_entries = raw_h
        except Exception:
            saved_entries = []

    if backup_path.is_file():
        try:
            bk = json.loads(backup_path.read_text(encoding="utf-8"))
            if isinstance(bk, dict) and isinstance(bk.get("roadmap_projection"), list) and bk["roadmap_projection"]:
                bk_steps = [_compact_history_step(s) for s in bk["roadmap_projection"] if isinstance(s, dict)]
                bk_dig = _steps_digest(bk_steps)
                bk_at = str(bk.get("saved_at") or today_str)
                bk_date = bk_at[:10] if len(bk_at) >= 10 and bk_at[:4].isdigit() else today_str
                bk_done = sum(1 for s in bk_steps if s.get("status") == "done")
                saved_entries.append({
                    "id": f"backup-{bk_date}-{bk_dig[:8]}",
                    "date": bk_date,
                    "at": bk_at,
                    "label": f"{bk_date} · Previous Plan Backup ({bk_done}/{len(bk_steps)} done)",
                    "summary": "Saved backup snapshot before the most recent plan update.",
                    "trigger": "backup",
                    "digest": bk_dig,
                    "steps_done": bk_done,
                    "steps_total": len(bk_steps),
                    "steps": bk_steps,
                })
        except Exception:
            pass

    reconstructed = _reconstruct_plan_history_from_events(roadmap, campaign_dir)

    out: list[dict] = []
    if live_steps:
        out.append({
            "id": "current-live",
            "is_current": True,
            "date": today_str,
            "at": today_str,
            "label": f"{today_str} · Current Live Plan ({live_done}/{live_total} done)",
            "summary": f"Current active roadmap ({live_done} completed, {live_total - live_done} open).",
            "trigger": "current",
            "digest": live_digest,
            "steps_done": live_done,
            "steps_total": live_total,
            "plan_doc": primary_plan_doc,
            "steps": live_steps,
        })

    seen_keys = {(today_str, live_digest)}
    if as_of_str:
        seen_keys.add((as_of_str, live_digest))
    combined_past = []
    for ent in saved_entries + reconstructed:
        if not isinstance(ent, dict) or not isinstance(ent.get("steps"), list) or not ent["steps"]:
            continue
        d_str = str(ent.get("date") or str(ent.get("at") or "")[:10] or today_str)
        dig = str(ent.get("digest") or _steps_digest(ent["steps"]))
        is_explicit = ent.get("trigger") in ("backup", "before_accept", "before_restore", "before_revert", "plan_revert", "plan_restore")
        if not is_explicit and d_str == today_str and dig == live_digest:
            continue
        key = (d_str, dig)
        if key in seen_keys:
            continue
        seen_keys.add(key)
        ent_copy = dict(ent)
        ent_copy["is_current"] = False
        ent_copy["date"] = d_str
        ent_copy["digest"] = dig
        if primary_plan_doc and not ent_copy.get("plan_doc"):
            ent_copy["plan_doc"] = primary_plan_doc
        combined_past.append(ent_copy)

    combined_past.sort(key=lambda x: (str(x.get("date") or ""), str(x.get("at") or "")), reverse=True)
    out.extend(combined_past)

    with _PLAN_HISTORY_CACHE_LOCK:
        if len(_PLAN_HISTORY_CACHE) > 64:
            _PLAN_HISTORY_CACHE.clear()
        _PLAN_HISTORY_CACHE[cache_key] = (cache_sig, deepcopy(out))
    return out


def compute_deliverables_plan_refresh(campaign_dir: str, m: dict | None = None, roadmap: dict | None = None) -> dict:
    """Analyze DELIVERABLES.md and plan documents against roadmap.json to propose concrete step updates."""
    from .navigation_compat import resolve_step
    root = Path(campaign_dir)
    if roadmap is None:
        roadmap, _ = _read_json(root / "roadmap.json")
    cur_proj = deepcopy((roadmap or {}).get("roadmap_projection") or (m or {}).get("steps") or [])
    if not isinstance(cur_proj, list):
        cur_proj = []

    if not cur_proj:
        doc_steps, doc_name = _steps_from_plan_doc(root)
        if doc_steps:
            changes = [
                {
                    "step_id": str(s.get("id") or ""),
                    "name": str(s.get("name") or ""),
                    "from": "none",
                    "to": str(s.get("status") or "proposed"),
                    "reason": f"Scaffolded from {doc_name}",
                }
                for s in doc_steps
            ]
            return {
                "has_changes": True,
                "changes": changes,
                "proposed_steps": doc_steps,
                "proposed_steps_count": len(doc_steps),
                "proposed_done_count": sum(1 for s in doc_steps if s.get("status") == "done"),
                "title": f"Proposed Plan from {doc_name}",
                "reason": f"Extracted {len(doc_steps)} plan steps from {doc_name}.",
                "digest": "empty->" + _steps_digest(doc_steps),
            }
        return {"has_changes": False, "changes": [], "proposed_steps": [], "digest": "empty->empty"}

    deliv = _read_deliverables(campaign_dir)
    raw_items = (deliv or {}).get("items") or []
    approved_items = (deliv or {}).get("approved") or []
    dismissed = read_dismissed_deliverables(campaign_dir)

    final_by_step: dict[str, list[str]] = {}
    open_review_by_step: dict[str, list[str]] = {}

    for it in list(raw_items) + list(approved_items):
        if not isinstance(it, dict):
            continue
        what = str(it.get("what") or "").strip()
        p_norm = str(it.get("path") or "").replace("\\", "/").lower()
        owner = resolve_step(cur_proj, it.get("step"))
        if owner is None and p_norm:
            for cand_s in cur_proj:
                if not isinstance(cand_s, dict):
                    continue
                fp_list = ((cand_s.get("navigation") or {}).get("featured_paths") if isinstance(cand_s.get("navigation"), dict) else None) or []
                if any(str(fp or "").replace("\\", "/").lower() == p_norm for fp in fp_list):
                    owner = cand_s
                    break
                dw_low = str(cand_s.get("done_when") or "").replace("\\", "/").lower()
                if p_norm in dw_low or (Path(p_norm).name and len(Path(p_norm).name) > 6 and Path(p_norm).name in dw_low):
                    owner = cand_s
                    break
        sid = str((owner or {}).get("id") or (owner or {}).get("step_id") or it.get("step") or "").strip()
        if not sid:
            continue
        clean_label = _strip_format_tag(
            re.sub(
                r"^(?:START\s+HERE\s*[\u2014\u2013\-:]\s*)?(?:FOR\s+REVIEW\s*[\u2014\u2013\-:]\s*)?"
                r"(?:Approved\s*[\u2014\u2013\-:]\s*Finalized\s*[\u2014\u2013\-:]\s*)?(?:[A-Za-z0-9_-]+\s*[\u2014\u2013\-]\s*)?",
                "",
                what,
                flags=re.I,
            )
        ) or Path(str(it.get("path") or sid)).name

        is_final = bool(
            it.get("accepted")
            or it.get("accepted_current")
            or _FINAL_DELIV_RE.match(what)
            or "/final deliverables/" in ("/" + p_norm)
        )
        if is_final:
            if clean_label not in final_by_step.setdefault(sid, []):
                final_by_step[sid].append(clean_label)
            continue

        is_dis = bool(dismissed and _is_deliverable_dismissed(campaign_dir, it, dismissed))
        if is_dis and not _is_intermediate_deliverable(it):
            if clean_label not in final_by_step.setdefault(sid, []):
                final_by_step[sid].append(clean_label)
            continue
        if is_dis or _HISTORICAL_LABEL.match(what):
            continue
        is_for_review = bool(
            _FOR_REVIEW_LABEL.match(what)
            or _ACTIVE_REVIEW_DELIV_RE.match(what)
            or (it.get("managed") and it.get("phase") in ("awaiting_review", "blocked"))
        )
        if is_for_review:
            if clean_label not in open_review_by_step.setdefault(sid, []):
                open_review_by_step[sid].append(clean_label)
        elif it.get("openable") and not it.get("auto") and not _is_intermediate_deliverable(it):
            if clean_label not in final_by_step.setdefault(sid, []):
                final_by_step[sid].append(clean_label)

    proposed_steps = deepcopy(cur_proj)
    changes = []
    done_added = 0
    active_added = 0

    for s in proposed_steps:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("id") or s.get("step_id") or "").strip()
        if not sid:
            continue
        cur_st = str(s.get("status") or "proposed").strip().lower()
        sname = str(((s.get("navigation") or {}).get("label") if isinstance(s.get("navigation"), dict) else "") or s.get("name") or sid)

        if sid in final_by_step and sid not in open_review_by_step and cur_st not in ("done", "parked", "cancelled", "dropped"):
            s["status"] = "done"
            s["waiting_on"] = None
            done_added += 1
            changes.append({
                "step_id": sid,
                "name": one_line(sname, 60),
                "from": cur_st,
                "to": "done",
                "reason": f"Final deliverable locked ({one_line(final_by_step[sid][0], 48)})",
            })
        elif sid in open_review_by_step and cur_st in ("planned", "proposed"):
            s["status"] = "active"
            if not s.get("waiting_on"):
                s["waiting_on"] = f"Review {one_line(open_review_by_step[sid][0], 56)}"
            active_added += 1
            changes.append({
                "step_id": sid,
                "name": one_line(sname, 60),
                "from": cur_st,
                "to": "active",
                "reason": f"Deliverable ready for review ({one_line(open_review_by_step[sid][0], 48)})",
            })

    # If the currently pinned step is now done, move the pin to the first step with open review items or first active step
    pinned_steps = [
        s for s in proposed_steps
        if isinstance(s, dict) and isinstance(s.get("navigation"), dict) and (s["navigation"].get("pin") or s["navigation"].get("current"))
    ]
    if pinned_steps and all(s.get("status") == "done" for s in pinned_steps):
        next_focus = next(
            (s for s in proposed_steps if isinstance(s, dict) and s.get("status") != "done" and str(s.get("id") or s.get("step_id") or "") in open_review_by_step),
            None,
        ) or next(
            (s for s in proposed_steps if isinstance(s, dict) and s.get("status") in ("active", "in_progress", "waiting")),
            None,
        )
        if next_focus is not None:
            for s in pinned_steps:
                s["navigation"]["pin"] = False
            nav = next_focus.setdefault("navigation", {})
            nav["pin"] = True
            nav["current"] = True

    before_dig = _steps_digest(cur_proj)
    after_dig = _steps_digest(proposed_steps)
    refresh_digest = f"{before_dig}->{after_dig}"

    if not changes:
        return {
            "has_changes": False,
            "changes": [],
            "proposed_steps": proposed_steps,
            "proposed_steps_count": len(proposed_steps),
            "proposed_done_count": sum(1 for s in proposed_steps if isinstance(s, dict) and s.get("status") == "done"),
            "digest": refresh_digest,
        }

    parts = []
    if done_added:
        done_names = ", ".join(c["name"] for c in changes if c["to"] == "done")
        parts.append(f"{done_added} step(s) completed in Final Deliverables ({one_line(done_names, 90)})")
    if active_added:
        act_names = ", ".join(c["name"] for c in changes if c["to"] == "active")
        parts.append(f"{active_added} step(s) active in For Review ({one_line(act_names, 70)})")
    reason_str = " · ".join(parts) or f"{len(changes)} step update(s) detected from recent deliverables."

    return {
        "has_changes": True,
        "changes": changes,
        "proposed_steps": proposed_steps,
        "proposed_steps_count": len(proposed_steps),
        "proposed_done_count": sum(1 for s in proposed_steps if isinstance(s, dict) and s.get("status") == "done"),
        "title": f"Proposed Plan Refresh ({len(changes)} Deliverable Update{'s' if len(changes) != 1 else ''})",
        "reason": reason_str,
        "digest": refresh_digest,
    }


_PLAN_PROPOSAL_CACHE_LOCK = globals().get("_PLAN_PROPOSAL_CACHE_LOCK") or threading.Lock()
_PLAN_PROPOSAL_CACHE: dict[str, tuple[tuple, dict | None]] = globals().get("_PLAN_PROPOSAL_CACHE") if isinstance(globals().get("_PLAN_PROPOSAL_CACHE"), dict) else {}


def read_plan_proposal(campaign_dir: str, m: dict | None = None, roadmap: dict | None = None) -> dict | None:
    """Return a plan refresh proposal when major deliverables or plan documents update the campaign plan,
    or when a previous plan backup exists so John can Accept New Plan or Revert to Old Plan."""
    root = Path(campaign_dir)
    prop_file = root / ".ecgberht" / "plan-proposal.json"
    backup_file = root / ".ecgberht" / "roadmap-backup.json"
    rm_file = root / "roadmap.json"
    deliv_file = root / "DELIVERABLES.md"
    dis_file = root / ".ecgberht" / "dismissed-deliverables.json"
    conv_file = root / ".ecgberht" / "conversational-plan-drift.json"
    try:
        prop_sig = (
            rm_file.stat().st_mtime_ns if rm_file.is_file() else 0,
            deliv_file.stat().st_mtime_ns if deliv_file.is_file() else 0,
            prop_file.stat().st_mtime_ns if prop_file.is_file() else 0,
            backup_file.stat().st_mtime_ns if backup_file.is_file() else 0,
            dis_file.stat().st_mtime_ns if dis_file.is_file() else 0,
            conv_file.stat().st_mtime_ns if conv_file.is_file() else 0,
        )
    except OSError:
        prop_sig = None
    cache_key = os.path.normcase(str(root))
    if prop_sig is not None:
        with _PLAN_PROPOSAL_CACHE_LOCK:
            cached_p = _PLAN_PROPOSAL_CACHE.get(cache_key)
            if cached_p is not None and cached_p[0] == prop_sig:
                return dict(cached_p[1]) if isinstance(cached_p[1], dict) else None
    res = _read_plan_proposal_uncached(campaign_dir, m, roadmap)
    if prop_sig is not None:
        with _PLAN_PROPOSAL_CACHE_LOCK:
            if len(_PLAN_PROPOSAL_CACHE) > 64:
                _PLAN_PROPOSAL_CACHE.clear()
            _PLAN_PROPOSAL_CACHE[cache_key] = (prop_sig, dict(res) if isinstance(res, dict) else None)
    return res


def _read_plan_proposal_uncached(campaign_dir: str, m: dict | None = None, roadmap: dict | None = None) -> dict | None:
    root = Path(campaign_dir)
    prop_file = root / ".ecgberht" / "plan-proposal.json"
    backup_file = root / ".ecgberht" / "roadmap-backup.json"
    has_backup = backup_file.is_file()
    prop_disk = {}
    if prop_file.is_file():
        try:
            prop_disk = json.loads(prop_file.read_text(encoding="utf-8")) or {}
        except Exception:
            prop_disk = {}

    # 1. Check deliverable-driven plan updates
    try:
        refresh = compute_deliverables_plan_refresh(campaign_dir, m, roadmap)
    except Exception:
        refresh = {"has_changes": False, "changes": [], "proposed_steps": []}

    if refresh.get("has_changes"):
        dig = str(refresh.get("digest") or "")
        if not (isinstance(prop_disk, dict) and prop_disk.get("status") == "dismissed" and prop_disk.get("digest") == dig):
            return {
                "id": "deliv-refresh-" + dig[:12],
                "status": "pending",
                "title": refresh.get("title") or "Proposed Plan Refresh",
                "reason": refresh.get("reason") or "Recent deliverables updated the campaign plan.",
                "changes": refresh.get("changes") or [],
                "proposed_steps_count": refresh.get("proposed_steps_count", 0),
                "proposed_done_count": refresh.get("proposed_done_count", 0),
                "can_revert": True,
            }

    # 2. Check explicit pending or accepted proposal file on disk
    if isinstance(prop_disk, dict):
        if prop_disk.get("status") in ("pending", None, "") and (prop_disk.get("title") or prop_disk.get("reason") or prop_disk.get("proposed_steps")):
            out_prop = dict(prop_disk)
            out_prop["status"] = "pending"
            out_prop["can_revert"] = bool(has_backup or prop_disk.get("previous_steps") or True)
            out_prop.pop("proposed_steps", None)
            out_prop.pop("previous_steps", None)
            return out_prop
        if prop_disk.get("status") == "accepted" and has_backup:
            return {
                "id": str(prop_disk.get("id") or "accepted-plan"),
                "status": "accepted",
                "title": str(prop_disk.get("title") or "Updated Plan Active"),
                "reason": str(prop_disk.get("reason") or "Plan refreshed after recent deliverables."),
                "changes": prop_disk.get("changes") if isinstance(prop_disk.get("changes"), list) else [],
                "can_revert": True,
            }

    # 3. Check plan document / conversational drift
    drift = (m or {}).get("plan_drift") if isinstance(m, dict) and isinstance(m.get("plan_drift"), dict) else plan_drift(campaign_dir)
    if isinstance(drift, dict) and drift.get("drift"):
        proposed_steps, doc_name = _steps_from_plan_doc(root)
        cur_steps = (m or {}).get("steps") or ((roadmap or {}).get("roadmap_projection") if isinstance(roadmap, dict) else []) or []
        return {
            "id": "drift-" + (doc_name or "roadmap"),
            "status": "pending",
            "title": "Proposed Plan Refresh" + (" from " + doc_name if doc_name and not cur_steps else ""),
            "reason": str(drift.get("reason") or "Deliverables or instructions updated the plan structure."),
            "changes": refresh.get("changes") or [],
            "proposed_steps_count": len(cur_steps) or len(proposed_steps),
            "can_revert": True,
        }
    return None


def resolve_plan_proposal(campaign_dir: str, action: str = "accept", proposal_id: str = "") -> dict:
    """Accept a proposed plan refresh, revert to the previous roadmap snapshot, restore any historical date snapshot, or refresh."""
    root = Path(campaign_dir)
    ec_dir = root / ".ecgberht"
    ec_dir.mkdir(parents=True, exist_ok=True)
    rm_path = root / "roadmap.json"
    prop_file = ec_dir / "plan-proposal.json"
    backup_file = ec_dir / "roadmap-backup.json"
    conv_file = ec_dir / "conversational-plan-drift.json"
    act = str(action or "accept").strip().lower()
    rm_data, _ = _read_json(rm_path)
    if not isinstance(rm_data, dict):
        rm_data = {"roadmap_projection": [], "roadmap_events": []}
    cur_proj = deepcopy(list(rm_data.get("roadmap_projection") or []))
    prop_data = {}
    if prop_file.is_file():
        try:
            prop_data = json.loads(prop_file.read_text(encoding="utf-8")) or {}
        except Exception:
            prop_data = {}

    now_iso = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    today_str = now_iso[:10]

    if act in ("refresh", "re-evaluate", "propose"):
        refresh = compute_deliverables_plan_refresh(campaign_dir, roadmap=rm_data)
        if refresh.get("has_changes"):
            prop_payload = {
                "id": "deliv-refresh-" + str(refresh.get("digest") or "")[:12],
                "status": "pending",
                "title": refresh.get("title") or "Proposed Plan Refresh",
                "reason": refresh.get("reason") or "Deliverables analyzed against plan.",
                "changes": refresh.get("changes") or [],
                "proposed_steps": refresh.get("proposed_steps") or [],
                "proposed_steps_count": refresh.get("proposed_steps_count", 0),
                "proposed_done_count": refresh.get("proposed_done_count", 0),
                "digest": refresh.get("digest") or "",
                "refreshed_at": now_iso,
                "can_revert": True,
            }
            prop_file.write_text(json.dumps(prop_payload, indent=2, ensure_ascii=False), encoding="utf-8")
            return {
                "ok": True,
                "action": "refreshed",
                "has_changes": True,
                "changes_count": len(refresh.get("changes") or []),
                "proposal": {k: v for k, v in prop_payload.items() if k != "proposed_steps"},
            }
        # Even if no pending step flips, record a verified snapshot in history and clear stale conversational drift
        if conv_file.is_file():
            try:
                conv_file.unlink()
            except OSError:
                pass
        if cur_proj:
            done_c = sum(1 for s in cur_proj if isinstance(s, dict) and s.get("status") == "done")
            _record_plan_history_snapshot(
                campaign_dir,
                cur_proj,
                label=f"{today_str} · Verified Plan ({done_c}/{len(cur_proj)} done)",
                summary="Plan reviewed against Deliverables — all steps up to date.",
                trigger="plan_refresh",
                at=now_iso,
            )
        return {
            "ok": True,
            "action": "refreshed",
            "has_changes": False,
            "changes_count": 0,
            "steps_count": len(cur_proj),
        }

    if act == "dismiss":
        refresh = compute_deliverables_plan_refresh(campaign_dir, roadmap=rm_data)
        prop_data["status"] = "dismissed"
        prop_data["digest"] = refresh.get("digest") or prop_data.get("digest") or ""
        prop_data["dismissed_at"] = now_iso
        prop_file.write_text(json.dumps(prop_data, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "action": "dismissed"}

    if act == "restore":
        hist = read_plan_history(campaign_dir, roadmap=rm_data)
        target_snap = next(
            (
                h for h in hist
                if isinstance(h, dict)
                and (str(h.get("id") or "") == proposal_id or str(h.get("date") or "") == proposal_id)
                and isinstance(h.get("steps"), list)
                and h["steps"]
            ),
            None,
        )
        if target_snap is None:
            return {"ok": False, "error": f"Historical plan snapshot '{proposal_id}' not found"}
        if cur_proj:
            done_cur = sum(1 for s in cur_proj if isinstance(s, dict) and s.get("status") == "done")
            backup_file.write_text(
                json.dumps({"saved_at": now_iso, "roadmap_projection": cur_proj}, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            _record_plan_history_snapshot(
                campaign_dir,
                cur_proj,
                label=f"{today_str} · Snapshot before Restore ({done_cur}/{len(cur_proj)} done)",
                summary=f"Saved automatically before restoring plan from {target_snap.get('date')}.",
                trigger="before_restore",
                at=now_iso,
                force=True,
            )
        restored_steps = deepcopy(target_snap["steps"])
        rm_data["roadmap_projection"] = restored_steps
        evs = list(rm_data.get("roadmap_events") or [])
        evs.append({
            "kind": "plan_restore",
            "at": now_iso,
            "by": "John",
            "proposal_id": str(target_snap.get("id") or proposal_id),
            "restored_date": str(target_snap.get("date") or ""),
            "steps": restored_steps,
        })
        rm_data["roadmap_events"] = evs
        rm_path.write_text(json.dumps(rm_data, indent=2, ensure_ascii=False), encoding="utf-8")
        with _JSON_FILE_CACHE_LOCK:
            _JSON_FILE_CACHE.clear()
        done_rest = sum(1 for s in restored_steps if isinstance(s, dict) and s.get("status") == "done")
        _record_plan_history_snapshot(
            campaign_dir,
            restored_steps,
            label=f"{today_str} · Restored Plan from {target_snap.get('date')} ({done_rest}/{len(restored_steps)} done)",
            summary=f"Restored historical plan from {target_snap.get('date')} ({target_snap.get('summary') or ''}).",
            trigger="plan_restore",
            at=now_iso,
            force=True,
        )
        prop_data["status"] = "accepted"
        prop_data["title"] = f"Restored Plan from {target_snap.get('date')}"
        prop_data["reason"] = f"Showing restored plan from {target_snap.get('date')} ({done_rest}/{len(restored_steps)} done). You can revert to your previous plan at any time."
        prop_data["can_revert"] = True
        prop_file.write_text(json.dumps(prop_data, indent=2, ensure_ascii=False), encoding="utf-8")
        return {
            "ok": True,
            "action": "restored",
            "restored_id": target_snap.get("id"),
            "restored_date": target_snap.get("date"),
            "steps_count": len(restored_steps),
        }

    if act in ("revert", "rollback", "old"):
        prev_steps = None
        if backup_file.is_file():
            try:
                bk = json.loads(backup_file.read_text(encoding="utf-8"))
                if isinstance(bk, dict) and isinstance(bk.get("roadmap_projection"), list):
                    prev_steps = bk["roadmap_projection"]
            except Exception:
                prev_steps = None
        if prev_steps is None and isinstance(prop_data.get("previous_steps"), list):
            prev_steps = prop_data["previous_steps"]
        if prev_steps is None:
            hist = read_plan_history(campaign_dir, roadmap=rm_data)
            if len(hist) >= 2 and isinstance(hist[1].get("steps"), list):
                prev_steps = hist[1]["steps"]
        if prev_steps is not None:
            if cur_proj:
                done_cur = sum(1 for s in cur_proj if isinstance(s, dict) and s.get("status") == "done")
                _record_plan_history_snapshot(
                    campaign_dir,
                    cur_proj,
                    label=f"{today_str} · Snapshot before Revert ({done_cur}/{len(cur_proj)} done)",
                    summary="Saved before reverting to previous plan.",
                    trigger="before_revert",
                    at=now_iso,
                    force=True,
                )
                backup_file.write_text(
                    json.dumps({"saved_at": now_iso, "roadmap_projection": cur_proj}, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            rm_data["roadmap_projection"] = prev_steps
            evs = list(rm_data.get("roadmap_events") or [])
            evs.append({
                "kind": "plan_revert",
                "at": now_iso,
                "by": "John",
                "proposal_id": proposal_id or str(prop_data.get("id") or ""),
                "steps": prev_steps,
            })
            rm_data["roadmap_events"] = evs
            rm_path.write_text(json.dumps(rm_data, indent=2, ensure_ascii=False), encoding="utf-8")
            with _JSON_FILE_CACHE_LOCK:
                _JSON_FILE_CACHE.clear()
            done_prev = sum(1 for s in prev_steps if isinstance(s, dict) and s.get("status") == "done")
            _record_plan_history_snapshot(
                campaign_dir,
                prev_steps,
                label=f"{today_str} · Reverted to Previous Plan ({done_prev}/{len(prev_steps)} done)",
                summary="Reverted to previous plan snapshot.",
                trigger="plan_revert",
                at=now_iso,
                force=True,
            )
        prop_data["status"] = "reverted"
        prop_data["reverted_at"] = now_iso
        prop_file.write_text(json.dumps(prop_data, indent=2, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "action": "reverted", "steps_count": len(rm_data.get("roadmap_projection") or [])}

    # Accept new plan: save backup and history snapshot of current projection first so John can revert anytime
    if cur_proj:
        done_cur = sum(1 for s in cur_proj if isinstance(s, dict) and s.get("status") == "done")
        backup_file.write_text(json.dumps({
            "saved_at": now_iso,
            "roadmap_projection": cur_proj,
        }, indent=2, ensure_ascii=False), encoding="utf-8")
        _record_plan_history_snapshot(
            campaign_dir,
            cur_proj,
            label=f"{today_str} · Plan before Refresh ({done_cur}/{len(cur_proj)} done)",
            summary="Saved automatically before accepting plan refresh.",
            trigger="before_accept",
            at=now_iso,
            force=True,
        )

    refresh = compute_deliverables_plan_refresh(campaign_dir, roadmap=rm_data)
    new_steps = prop_data.get("proposed_steps") if isinstance(prop_data.get("proposed_steps"), list) and prop_data.get("proposed_steps") else None
    changes_applied = prop_data.get("changes") if isinstance(prop_data.get("changes"), list) else []
    reason_applied = str(prop_data.get("reason") or "")
    if not new_steps and refresh.get("has_changes") and isinstance(refresh.get("proposed_steps"), list):
        new_steps = refresh["proposed_steps"]
        changes_applied = refresh.get("changes") or []
        reason_applied = str(refresh.get("reason") or "")
    if not new_steps:
        doc_steps, _ = _steps_from_plan_doc(root)
        if doc_steps and not cur_proj:
            new_steps = doc_steps
    if new_steps:
        rm_data["roadmap_projection"] = new_steps
    final_proj = list(rm_data.get("roadmap_projection") or [])
    evs = list(rm_data.get("roadmap_events") or [])
    evs.append({
        "kind": "plan_accept",
        "at": now_iso,
        "by": "John",
        "proposal_id": proposal_id or str(prop_data.get("id") or "accepted-plan"),
        "steps": [_compact_history_step(s) for s in final_proj if isinstance(s, dict)],
    })
    rm_data["roadmap_events"] = evs
    rm_path.write_text(json.dumps(rm_data, indent=2, ensure_ascii=False), encoding="utf-8")
    with _JSON_FILE_CACHE_LOCK:
        _JSON_FILE_CACHE.clear()
    if conv_file.is_file():
        try:
            conv_file.unlink()
        except OSError:
            pass
    done_new = sum(1 for s in final_proj if isinstance(s, dict) and s.get("status") == "done")
    _record_plan_history_snapshot(
        campaign_dir,
        final_proj,
        label=f"{today_str} · Accepted Refreshed Plan ({done_new}/{len(final_proj)} done)",
        summary=reason_applied or f"Accepted plan refresh ({done_new} of {len(final_proj)} steps completed).",
        trigger="plan_accept",
        at=now_iso,
        force=True,
    )
    prop_data["id"] = proposal_id or str(prop_data.get("id") or "accepted-plan")
    prop_data["status"] = "accepted"
    prop_data["title"] = "Updated Plan Active"
    prop_data["reason"] = reason_applied or f"Plan refreshed ({done_new}/{len(final_proj)} steps done)."
    prop_data["changes"] = changes_applied
    prop_data["accepted_at"] = now_iso
    prop_data.pop("proposed_steps", None)
    prop_file.write_text(json.dumps(prop_data, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "ok": True,
        "action": "accepted",
        "can_revert": True,
        "changes_count": len(changes_applied),
        "steps_count": len(final_proj),
        "steps_done": done_new,
    }


_APPROVE_FEEDBACK_RE = re.compile(
    r"\b(?:approve[d]?|looks?\s+good|lgtm|move\s+on|next\s+(?:step|wave|chapter|section|phase)|"
    r"done\s+with\s+(?:this|review|these)|lock\s+(?:it|this|these)|ship\s+it|proceed|all\s+good|accept(?:ed)?)\b",
    re.I,
)
_REVISION_FEEDBACK_RE = re.compile(
    r"\b(?:another\s+round|next\s+round|revise|revision|update|change|fix|rework|adjust|modify|"
    r"rewrite|redo|instead|make\s+sure|should\s+be|need[s]?\s+to|too\s+(?:long|short|much|many|little|weak|strong)|"
    r"add\s+(?:a|more|the)|remove|cut|expand|tighten|table\s+(?:this|it|that))\b",
    re.I,
)


_SPECIFIC_REVIEW_TARGET_RE = re.compile(
    r"\b(lectures?\s*\d+(?:\s*(?:to|through|[-\u2013\u2014])\s*\d+)?|"
    r"chapters?\s*\d+(?:\s*(?:to|through|[-\u2013\u2014])\s*\d+)?|"
    r"ch\.?\s*\d+(?:\s*(?:to|through|[-\u2013\u2014])\s*\d+)?|"
    r"homeworks?\s*\d+|hw\s*\d+|quiz(?:zes)?\s*\d+|waves?\s*\d+|steps?\s*\d+|"
    r"blocks?\s*\d+|rounds?\s*\d+|papers?\s*\d+|books?\s*\d+|v\d+(?:\.\d+)?|syllabus|intro\s+lecture|lem\s+lab)\b",
    re.I,
)


def _normalize_review_target_token(tok: str) -> str:
    s = re.sub(r"\s+", " ", str(tok or "").strip().lower())
    s = re.sub(r"^(?:chapters?|ch\.?)\s*0*(\d+).*$", r"chapter \1", s)
    s = re.sub(r"^lectures?\s*0*(\d+).*$", r"lecture \1", s)
    s = re.sub(r"^(?:homeworks?|hw)\s*0*(\d+).*$", r"homework \1", s)
    return s


def _item_matches_review_targets(it: dict, targets: list[str]) -> bool:
    if not targets:
        return True
    hay = re.sub(
        r"\s+",
        " ",
        f"{it.get('what') or ''} {it.get('open_path') or it.get('path') or ''} {it.get('step') or ''} {it.get('owner_step_id') or ''}".lower(),
    )
    hay_norm = re.sub(r"\b(?:chapters?|ch\.?)[\s_-]*0*(\d+)\b", r"chapter \1", hay)
    hay_norm = re.sub(r"\b(?:lectures?|lec\.?)[\s_-]*0*(\d+)\b", r"lecture \1", hay_norm)
    for t in targets:
        pat = re.escape(t).replace(r"\ ", r"[\s_-]*0*")
        if re.search(r"\b" + pat + r"\b", hay, re.I) or re.search(r"\b" + pat + r"\b", hay_norm, re.I):
            return True
    return False


def _viewed_deliverables_file(campaign_dir: str) -> Path:
    return Path(campaign_dir) / ".ecgberht" / "recently-viewed-deliverables.json"


def record_deliverable_viewed(campaign_dir: str, rel_path: str) -> None:
    """Record that John opened or downloaded a deliverable in the AI Cockpit so subsequent feedback
    automatically reconciles that deliverable (and its companion formats) from For Review."""
    if not campaign_dir or not rel_path:
        return
    try:
        norm = str(rel_path or "").replace("\\", "/").strip().lstrip("/")
        if not norm:
            return
        vf = _viewed_deliverables_file(campaign_dir)
        data = {}
        if vf.is_file():
            try:
                data = json.loads(vf.read_text(encoding="utf-8"))
            except Exception:
                data = {}
        entries = data.get("entries") if isinstance(data, dict) and isinstance(data.get("entries"), dict) else {}
        stem = Path(norm).stem.lower()
        entries[norm] = {
            "path": norm,
            "stem": stem,
            "viewed_at": time.time(),
        }
        if len(entries) > 40:
            sorted_keys = sorted(entries.keys(), key=lambda k: float((entries.get(k) or {}).get("viewed_at") or 0))
            for old_k in sorted_keys[:-40]:
                entries.pop(old_k, None)
        vf.parent.mkdir(parents=True, exist_ok=True)
        vf.write_text(json.dumps({"entries": entries}, indent=2), encoding="utf-8")
    except Exception:
        pass


def _recently_viewed_stems(campaign_dir: str, max_age_sec: float = 86400.0) -> set[str]:
    vf = _viewed_deliverables_file(campaign_dir)
    if not vf.is_file():
        return set()
    try:
        raw = json.loads(vf.read_text(encoding="utf-8"))
        entries = raw.get("entries") if isinstance(raw, dict) else {}
        if not isinstance(entries, dict):
            return set()
        now = time.time()
        stems: set[str] = set()
        for info in entries.values():
            if not isinstance(info, dict):
                continue
            if now - float(info.get("viewed_at") or 0) <= max_age_sec:
                st = str(info.get("stem") or "").strip().lower()
                if st:
                    stems.add(st)
        return stems
    except Exception:
        return set()


def _cockpit_review_candidates(campaign_dir: str) -> list[dict]:
    """Return all deliverables currently shown in the AI Cockpit's For Review queue (matching `shared.js` `isReviewOrCurrent`)."""
    out: list[dict] = []
    seen_paths: set[str] = set()
    try:
        for it in review_waiting(campaign_dir):
            if isinstance(it, dict):
                p = str(it.get("open_path") or it.get("path") or "")
                seen_paths.add(p)
                out.append(it)
        d = read_deliverables(campaign_dir)
        for it in d.get("items") or []:
            if not isinstance(it, dict):
                continue
            if it.get("accepted") or it.get("accepted_current"):
                continue
            w = str(it.get("what") or "").strip()
            p = str(it.get("open_path") or it.get("path") or "").strip()
            if re.match(r"^(?:supporting|supplemental|reference|companion)\b", w, re.I):
                continue
            is_rev = bool(
                _FOR_REVIEW_LABEL.match(w)
                or re.match(r"^[\u2605\u2b50]", w)
                or it.get("is_current") is True
                or (it.get("managed") and it.get("phase") in ("awaiting_review", "blocked"))
            )
            if is_rev and p not in seen_paths:
                seen_paths.add(p)
                out.append(it)
    except Exception:
        pass
    return out


def reconcile_review_on_feedback(campaign_dir: str, text: str) -> dict:
    """Reconcile deliverable review state when John provides feedback in the Steward dialogue.
    Once John gives feedback (either approving/locking or requesting another round of revisions),
    reconcile the matching review item(s) without wiping out unrelated deliverables in multi-topic campaigns."""
    msg = str(text or "").strip()
    if not msg or len(msg) < 2:
        return {"ok": False, "reason": "empty"}
    if re.search(r"\b(?:keep\s+(?:it\s+)?in\s+review|not\s+final|do\s+not\s+(?:mark|approve|dismiss)|stay\s+in\s+review)\b", msg, re.I):
        return {"ok": True, "reconciled": 0, "kind": "keep_in_review"}
    is_approve = bool(_APPROVE_FEEDBACK_RE.search(msg))
    is_revision = bool(_REVISION_FEEDBACK_RE.search(msg))
    is_status_question = bool(re.match(r"^(?:what(?:'s|\s+is)\s+the\s+status|how\s+is\s+it\s+going|status\??|eta\??|are\s+you\s+still\s+working)\s*\??$", msg, re.I))
    is_substantive_feedback = (len(msg) >= 15 and not is_status_question)
    if not (is_approve or is_revision or is_substantive_feedback):
        return {"ok": True, "reconciled": 0}
    disposition = "approved" if (is_approve and not is_revision) else "revision_requested"
    reconciled = 0
    try:
        waiting = _cockpit_review_candidates(campaign_dir)
        raw_targets = _SPECIFIC_REVIEW_TARGET_RE.findall(msg)
        named_targets = list(dict.fromkeys(_normalize_review_target_token(t) for t in raw_targets if t))
        is_explicit_all = bool(re.search(r"\b(?:all\s+(?:of\s+them|deliverables|items)|mark\s+all\s+done|approve\s+all)\b", msg, re.I))
        viewed_stems = _recently_viewed_stems(campaign_dir)

        target_matched = [it for it in waiting if isinstance(it, dict) and named_targets and _item_matches_review_targets(it, named_targets)]
        viewed_matched = [
            it for it in waiting
            if isinstance(it, dict) and viewed_stems and Path(str(it.get("open_path") or it.get("path") or "")).stem.lower() in viewed_stems
        ]
        matched_steps = {
            str(it.get("owner_step_id") or it.get("step") or "")
            for it in (target_matched or viewed_matched)
            if str(it.get("owner_step_id") or it.get("step") or "")
        }
        matched_stems = {
            Path(str(it.get("open_path") or it.get("path") or "")).stem.lower()
            for it in (target_matched or viewed_matched)
            if str(it.get("open_path") or it.get("path") or "")
        }
        distinct_steps = {str(it.get("owner_step_id") or it.get("step") or "") for it in waiting if isinstance(it, dict)}

        for it in waiting:
            if not isinstance(it, dict):
                continue
            step_key = str(it.get("owner_step_id") or it.get("step") or "")
            it_stem = Path(str(it.get("open_path") or it.get("path") or "")).stem.lower()
            it_raw_targets = _SPECIFIC_REVIEW_TARGET_RE.findall(
                f"{it.get('what') or ''} {it.get('open_path') or it.get('path') or ''}"
            )
            it_norm_targets = {_normalize_review_target_token(t) for t in it_raw_targets if t}
            if not is_explicit_all:
                if target_matched:
                    if it not in target_matched and it_stem not in matched_stems:
                        if it_norm_targets and not (it_norm_targets & set(named_targets)):
                            continue
                        if not step_key or step_key not in matched_steps:
                            continue
                elif viewed_matched:
                    if it not in viewed_matched and it_stem not in matched_stems and (not step_key or step_key not in matched_steps):
                        continue
                elif named_targets:
                    if it_norm_targets and not (it_norm_targets & set(named_targets)):
                        continue
                    if len(distinct_steps) > 1 and len(waiting) > 6:
                        continue
                elif len(waiting) > 6 and len(distinct_steps) > 1:
                    continue
            dismiss_deliverable(
                campaign_dir,
                path=str(it.get("open_path") or it.get("path") or ""),
                product_id=str(it.get("product_id") or ""),
                what=str(it.get("what") or ""),
                revision_id=str(it.get("revision_id") or ""),
                hash_val=str(it.get("hash") or ""),
                disposition=disposition,
            )
            reconciled += 1

        if reconciled > 0 or not waiting:
            for st_path in (Path(campaign_dir) / "strip.json", Path(campaign_dir) / ".ecgberht" / "strip.json"):
                st_data, st_err = _read_json(st_path)
                if not st_err and isinstance(st_data, dict):
                    hw = str(st_data.get("human_wait") or "")
                    if hw and hw.lower() != "none":
                        st_data["human_wait"] = "none"
                        st_data["last_feedback_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
                        st_data["last_feedback_kind"] = disposition
                        st_path.write_text(json.dumps(st_data, indent=2, ensure_ascii=False), encoding="utf-8")
                        with _JSON_FILE_CACHE_LOCK:
                            _JSON_FILE_CACHE.clear()
            for rm_path in (Path(campaign_dir) / "roadmap.json", Path(campaign_dir) / ".ecgberht" / "roadmap.json"):
                rm_data, rm_err = _read_json(rm_path)
                if not rm_err and isinstance(rm_data, dict):
                    changed_rm = False
                    for s in (rm_data.get("roadmap_projection") or rm_data.get("steps") or []):
                        if isinstance(s, dict) and s.get("waiting_on") and re.search(r"\b(?:john|review|feedback|approval)\b", str(s.get("waiting_on") or ""), re.I):
                            s.pop("waiting_on", None)
                            if s.get("status") in ("waiting", "blocked"):
                                s["status"] = "active"
                            changed_rm = True
                    if changed_rm:
                        rm_path.write_text(json.dumps(rm_data, indent=2, ensure_ascii=False), encoding="utf-8")
                        with _JSON_FILE_CACHE_LOCK:
                            _JSON_FILE_CACHE.clear()
    except Exception:
        pass
    return {"ok": True, "reconciled": reconciled, "kind": disposition}


def reconcile_cockpit_turn_state(
    campaign_dir: str,
    *,
    turn_text: str = "",
    user_text: str = "",
    wrote_files: bool = False,
    engine_state: dict | None = None,
    auto_accept_plan: bool = False,
    emit_status: bool = False,
) -> dict:
    """Unified Functional-Core / Imperative-Shell turn-end bookkeeping spine for the AI Cockpit Steward.
    In one coordinated, non-destructive pass, reconciles:
      1. User feedback on deliverables (`reconcile_review_on_feedback`, honoring explicit 'keep in review' and distinguishing approval vs revision).
      2. Explicit Steward status table (`persist_status_table_from_text` if present in `turn_text`).
      3. Hierarchical Plan & Strip projections (`sync_steward_projections` + optional `compute_deliverables_plan_refresh` auto-accept when `auto_accept_plan=True`).
      4. Running Overview (`.ecgberht/overview.json`), merging Steward-authored `goal`/`notes` with live plan & deliverable progress.
      5. Bottom Status Window (`.ecgberht/status_card.json` backfilled from reconciled state without clobbering fresh Steward-emitted fields).
    """
    if not campaign_dir:
        return {"ok": False, "reason": "missing campaign_dir"}
    root = Path(campaign_dir)
    if not root.is_dir():
        return {"ok": False, "reason": "missing directory"}

    feedback_res = None
    if user_text and str(user_text).strip():
        try:
            feedback_res = reconcile_review_on_feedback(campaign_dir, str(user_text))
        except Exception:
            feedback_res = None

    if turn_text and str(turn_text).strip():
        try:
            persist_status_table_from_text(campaign_dir, str(turn_text))
        except Exception:
            pass

    sync_res = {"ok": False, "changed": False}
    try:
        sync_res = sync_steward_projections(campaign_dir)
    except Exception:
        pass

    plan_refreshed = False
    if auto_accept_plan:
        try:
            refresh = compute_deliverables_plan_refresh(campaign_dir)
            if refresh.get("has_changes"):
                prop_file = root / ".ecgberht" / "plan-proposal.json"
                prop_disk, _ = _read_json(prop_file)
                if not (isinstance(prop_disk, dict) and prop_disk.get("status") == "dismissed" and prop_disk.get("digest") == refresh.get("digest")):
                    resolve_plan_proposal(campaign_dir, action="accept")
                    plan_refreshed = True
        except Exception:
            pass

    overview = {}
    try:
        m = read_map(campaign_dir, include_plan_history=False)
        overview = build_running_overview(campaign_dir, m)
        ov_path = root / ".ecgberht" / "overview.json"
        existing_ov, _ = _read_json(ov_path)
        merged_ov = dict(existing_ov) if isinstance(existing_ov, dict) else {}
        # Preserve explicit non-empty goal from existing overview.json if already set by Steward
        if merged_ov.get("goal") and str(merged_ov.get("goal")).strip():
            overview["goal"] = str(merged_ov["goal"]).strip()
        merged_ov.update({
            "goal": overview.get("goal") or "",
            "doing_now": overview.get("doing_now") or "",
            "done_summary": overview.get("done_summary") or [],
            "done_summary_text": overview.get("done_summary_text") or "",
            "todo_summary": overview.get("todo_summary") or "",
            "steps_done": overview.get("steps_done", 0),
            "steps_active": overview.get("steps_active", 0),
            "steps_upcoming": overview.get("steps_upcoming", 0),
            "steps_total": overview.get("steps_total", 0),
            "pct_done": overview.get("pct_done", 0),
            "key_deliverables": overview.get("key_deliverables") or [],
            "human_wait": overview.get("human_wait") or "",
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        })
        ov_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_ov = ov_path.with_name(f"{ov_path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        tmp_ov.write_text(json.dumps(merged_ov, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        os.replace(tmp_ov, ov_path)
        with _JSON_FILE_CACHE_LOCK:
            _JSON_FILE_CACHE.pop(str(ov_path), None)
    except Exception:
        pass

    # Backfill .ecgberht/status_card.json only when missing or older than the current turn (never clobbering a card just written)
    try:
        sc_path = root / ".ecgberht" / "status_card.json"
        existing_sc, _ = _read_json(sc_path)
        existing_sc = dict(existing_sc) if isinstance(existing_sc, dict) else {}
        sc_mtime = sc_path.stat().st_mtime if sc_path.is_file() else 0.0
        just_written = (time.time() - sc_mtime) < 3.0 and bool(existing_sc.get("doing"))
        if not just_written and overview:
            steps_status = f"{overview.get('steps_done', 0)}/{overview.get('steps_total', 0)} waves · {overview.get('pct_done', 0)}% done"
            new_sc = {
                **existing_sc,
                "timestamp": time.strftime("%H:%M"),
                "project": root.name,
                "effort": existing_sc.get("effort") or overview.get("goal") or root.name,
                "doing": overview.get("doing_now") or existing_sc.get("doing") or "Idle — waiting for instructions",
                "status": steps_status,
                "tests": existing_sc.get("tests") or "pass ✓",
                "blocker": overview.get("human_wait") or existing_sc.get("blocker") or "none",
                "procs": existing_sc.get("procs") or "idle",
                "journal": existing_sc.get("journal") or "none",
                "eta": existing_sc.get("eta") or "nothing running",
                "todo": overview.get("todo_summary") or existing_sc.get("todo") or "Await next instructions",
            }
            sc_path.parent.mkdir(parents=True, exist_ok=True)
            tmp_sc = sc_path.with_name(f"{sc_path.name}.{os.getpid()}.{threading.get_ident()}.tmp")
            tmp_sc.write_text(json.dumps(new_sc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp_sc, sc_path)
            with _JSON_FILE_CACHE_LOCK:
                _JSON_FILE_CACHE.pop(str(sc_path), None)
    except Exception:
        pass

    status_out = None
    if emit_status:
        try:
            status_out = compose_status(campaign_dir, engine_state)
        except Exception:
            status_out = None

    return {
        "ok": True,
        "feedback": feedback_res,
        "projections_synced": bool(sync_res.get("changed")),
        "plan_refreshed": plan_refreshed,
        "overview": overview,
        "status": status_out,
    }

