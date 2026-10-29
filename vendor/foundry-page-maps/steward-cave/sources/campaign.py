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

TAIL_TURNS = 40
SWARM_HEARTBEAT_LEASE_SECONDS = 90
ATTENTION_WORKING_GRACE_SECONDS = 120
_SWARM_HEARTBEAT_NAME = re.compile(
    r"^heartbeat-r\d+-[A-Za-z0-9][A-Za-z0-9_-]*\.json$", re.I)
# The flag John actually sees. Missing/garbage files are quiet, never "unknown"
# (2026-08-25 friction: status line read "attention: unknown").
_ATTENTION_STATES = frozenset({
    "working", "needs_you", "deliverable_ready", "blocked", "idle", "quiet",
})
# Scoping tags — the product map is derived from these (not a second file).
_PART_TAGS = ("research", "slice", "rigor", "integrate", "harden")


def _normalize_attention(raw, error=""):
    if raw is None and error == "absent":
        return {"state": "quiet", "reason": "", "source_state": "absent"}
    if not isinstance(raw, dict):
        return {"state": "unknown",
                "reason": error or "invalid attention record",
                "source_state": "unknown"}
    state = str(raw.get("state") or "quiet").strip().lower()
    if state not in _ATTENTION_STATES:
        return {"state": "unknown",
                "reason": "invalid attention state: " + state,
                "source_state": state}
    return {
        "state": state,
        "reason": str(raw.get("reason") or ""),
        "source_state": state,
        "state_since": raw.get("state_since"),
        "updated_at": raw.get("updated_at") or raw.get("at"),
        "failure_code": raw.get("failure_code"),
        "schema": raw.get("schema"),
        "provenance": (raw.get("provenance")
                       if isinstance(raw.get("provenance"), list) else []),
    }


def _read_json(path: Path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f), None
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
    if secs is None:
        return "never"
    if secs < 90:
        return "just now"
    for unit, span in (("m", 60), ("h", 3600), ("d", 86400)):
        if secs < span * (99 if unit == "d" else 60 if unit == "m" else 36):
            n = int(secs // span)
            if n >= 1:
                last = (unit, n)
    n = int(secs // 86400)
    if n >= 1:
        return f"{n}d ago"
    n = int(secs // 3600)
    if n >= 1:
        return f"{n}h ago"
    return f"{int(secs // 60)}m ago"


def _face_sections(text: str):
    """Split the Face into its four narrative sections by ## heading."""
    sections = {}
    current, buf = None, []
    for line in text.splitlines():
        m = re.match(r"^##\s+(.+?)\s*$", line)
        if m:
            if current:
                sections[current] = "\n".join(buf).strip()
            current = m.group(1).strip().lower()
            buf = []
        elif current:
            buf.append(line)
    if current:
        sections[current] = "\n".join(buf).strip()
    return sections


def _strip_md(text: str):
    """Blockquote/bold markers out, keep the words."""
    out = []
    for line in text.splitlines():
        line = re.sub(r"^\s*>\s?", "", line)
        line = line.replace("**", "")
        if re.fullmatch(r"\s*-{3,}\s*", line):
            continue
        out.append(line)
    return "\n".join(out).strip()


def _first_sentence(text: str):
    flat = " ".join(text.split())
    m = re.search(r"^(.+?[.!?])(\s|$)", flat)
    return (m.group(1) if m else flat)[:220]


def one_line(text, limit=110):
    """One human-readable sentence for a status fact; never a hidden dump."""
    flat = " ".join(str(text or "").split())
    if not flat:
        return ""
    match = re.search(r"^(.{20,}?)(?<!\d)[.!?](?:\s|$)", flat)
    sentence = match.group(0).strip() if match else flat
    if len(sentence) <= limit:
        return sentence
    clipped = sentence[:limit - 1].rsplit(" ", 1)[0]
    return (clipped or sentence[:limit - 1]) + "\u2026"


def status_facts(effort="", summary="", doing="", status="", tests="",
                 blocker="", procs="", journal="", eta="", todo=""):
    """Locked status categories with concise values for cockpit and dashboard."""
    rows = (
        ("Summary", summary),
        ("Effort", effort),
        ("Doing", doing),
        ("Status", status),
        ("Tests", tests),
        ("Blocker", blocker or "none"),
        ("Procs", procs or "none"),
        ("Journal", journal),
        ("ETA", eta),
        ("To do", todo),
    )
    return [{"label": label, "value": one_line(value) or "—"} for label, value in rows]


def _goal_md(text: str):
    """Goal section with markdown bold kept (for the rich expanded tile):
    blockquote markers and horizontal rules removed, and soft line-wraps
    unwrapped so **bold** pairs never straddle a line break."""
    lines = []
    for line in text.splitlines():
        line = re.sub(r"^\s*>\s?", "", line)
        if re.fullmatch(r"\s*-{3,}\s*", line):
            continue
        lines.append(line)
    paragraphs = re.split(r"\n\s*\n", "\n".join(lines).strip())
    unwrapped = []
    for para in paragraphs:
        if re.match(r"\s*[-*]\s", para):
            # bullet list: unwrap continuation lines into their bullet so
            # **bold** pairs never straddle a wrap
            items, cur = [], None
            for ln in para.splitlines():
                if re.match(r"\s*[-*]\s", ln):
                    if cur:
                        items.append(cur)
                    cur = ln.strip()
                elif cur:
                    cur += " " + ln.strip()
                else:
                    cur = ln.strip()
            if cur:
                items.append(cur)
            unwrapped.append("\n".join(items))
        else:
            unwrapped.append(" ".join(s.strip() for s in para.splitlines()))
    return "\n\n".join(unwrapped)


_REFINEMENT_READ_LOCK = threading.Lock()
_REFINEMENT_READ_SLOTS = {}


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
            return deepcopy(cached)
    with slot['lock']:
        return _read_refinement_slot(root, slot)


def _read_refinement_slot(root, slot):
    """The slot's read under its lock: answer from the slot while fresh, else read and store."""
    fingerprint = _refinement_fingerprint(root)
    if (slot.get('fingerprint') == fingerprint and
            time.monotonic() < slot.get('until', 0)):
        return deepcopy(slot['result'])
    result = _read_refinement_uncached(str(root))
    if _refinement_fingerprint(root) == fingerprint:
        slot.update(fingerprint=fingerprint, result=deepcopy(result),
                    until=time.monotonic() + (2.0 if result and result.get('ok') else .25))
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
    try:
        record = json.loads((Path(campaign_dir) / "roadmap.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not any(e.get("kind") == "refinement_update" for e in record.get("roadmap_events", [])):
        return None
    from steward_cockpit.refinement_client import read_state
    return read_state(campaign_dir)


def refinement_items(campaign_dir, state):
    """Opening metadata from the verified event fold; no Python lifecycle fold."""
    items = []
    for step_id, s in state.get("slices", {}).items():
        for product_id, revision_id in s.get("candidate", {}).items():
            rev = s["revisions"][revision_id]
            imported = [r for r in s['revisions'].values()
                        if r['product_id'] == product_id and r.get('source_history')]
            base = max((r['source_history']['iteration'] for r in imported), default=-1)
            presentations = [p for p in s.get('presentations', [])
                             if any(m['product_id'] == product_id for m in p['members'])]
            offset = 0
            if imported and presentations:
                first = presentations[0]
                first_member = next(m for m in first['members'] if m['product_id'] == product_id)
                first_source = s['revisions'][first_member['revision_id']].get('source_history')
                offset = (first_source['iteration'] if first_source else base + 1) - first['round']
            displayed_round = (rev['source_history']['iteration'] if rev.get('source_history')
                               else s['round'] + offset if presentations or not imported else base + 1)
            item = {"what": product_id, "path": rev["path"], "where_text": rev["path"],
                    "step": step_id, "date": rev.get("at", state.get("last_event_at", "")),
                    "route": None, "run": None, "openable": True, "managed": True,
                    "revision_id": revision_id, "product_id": product_id, "hash": rev["hash"], "round": displayed_round,
                    "provisional": rev.get("provisional"),
                    "phase": s["phase"], "history": []}
            for p in s.get("presentations", []):
                for member in p["members"]:
                    if member["product_id"] != product_id:
                        continue
                    shown_round = p['round'] + offset
                    entry = {"what": ("Initial draft" if shown_round == 0 else "Refinement %s" % shown_round),
                             "path": member["path"], "hash": member["hash"], "step": step_id,
                             "product_id": product_id, "revision_id": member["revision_id"],
                             "presentation_id": p["id"], "round": p["round"], "date": p.get("at", ""),
                             "accepted": p["id"] == s.get("accepted_presentation"),
                             "managed": True, "openable": True}
                    item["history"].append(entry)
                    if member["revision_id"] == revision_id:
                        item["presentation_id"] = p["id"]
                        item["product_id"] = product_id
            presented_ids = {v['revision_id'] for v in item['history']}
            for old in imported:
                if old['revision_id'] in presented_ids or old['revision_id'] == revision_id:
                    continue
                origin = old['source_history']; n = origin['iteration']
                item['history'].append({'what':('Initial draft' if n == 0 else f'Refinement {n}'),
                    'path':old['path'],'hash':old['hash'],'step':step_id,'product_id':product_id,
                    'revision_id':old['revision_id'],'date':origin['at'],'managed':True,'openable':True,
                    'source_history':origin})
            items.append(item)
    return items


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


def read_map(campaign_dir: str):
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
        proj = roadmap.get("roadmap_projection") or []
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
        "active_effort": strip.get("active_effort", ""),
        "human_wait": strip.get("human_wait", ""),
        "next_recommended": strip.get("next_recommended", ""),
        "why_next": strip.get("why_next", ""),
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
            pending = state.get("pending_request")
            attention["pending_requests"] = [dict(r, asked_at=p.get("at"))
                for sl in state["slices"].values() for r in sl.get("review_requests", [])
                if r.get("status") == "pending"
                for p in sl.get("presentations", []) if p["id"] == r["presentation_id"]]
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
    m = {
        "navigation_mode": organized["navigation_mode"],
        "navigation_fallback": organized.get("navigation_fallback"),
        "refinement": refinement,
        "dir": str(root),
        "name": root.name,
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
    return m


#: Words that carry no identity in an effort name (articles, glue, modals).
_NAME_STOP = frozenset("""
a an the and or of for to in on with that which not are is was it its this
those these be been being from by as at we our your his her their into over
under between merely can cannot could should would will what when how why
do does did done more most other some such only also than then there
""".split())


_PART_LABELS = {
    "research": "Background",
    "slice": "The product",
    "rigor": "Prove it",
    "integrate": "Join",
    "harden": "Finish",
}


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


def work_product_map(steps):
    """Backbone of the *deliverable* (Patton: flow across, detail down).
    Same steps as the plan — grouped, not a second store."""
    groups = []
    seen = set()
    for tag in _PART_TAGS:
        items = [s for s in (steps or []) if s.get("part") == tag]
        if not items:
            continue
        for s in items:
            seen.add(s.get("id"))
        done = sum(1 for s in items if s.get("status") == "done")
        groups.append({
            "tag": tag,
            "label": _PART_LABELS.get(tag, tag),
            "done": done,
            "total": len(items),
            "steps": items,
        })
    rest = [s for s in (steps or []) if s.get("id") not in seen]
    if rest:
        done = sum(1 for s in rest if s.get("status") == "done")
        groups.append({
            "tag": "",
            "label": "Outline",
            "done": done,
            "total": len(rest),
            "steps": rest,
        })
    return groups


def derive_product_map(steps):
    """Product map = tagged roadmap steps. Not a second file."""
    lines = []
    seen = set()
    for tag in _PART_TAGS:
        for s in steps or []:
            if s.get("part") == tag:
                seen.add(s.get("id"))
                bit = tag + ": " + (s.get("name") or "(unnamed)")
                bit += " (" + (s.get("status") or "") + ")"
                if s.get("gate"):
                    bit += " · gate"
                elif tag in ("slice", "rigor", "integrate", "harden"):
                    bit += " · no gate"
                lines.append(bit)
    for s in steps or []:
        if s.get("id") not in seen:
            lines.append("untagged: " + (s.get("name") or "(unnamed)")
                         + " (" + (s.get("status") or "") + ")")
    return lines


def suggest_effort_name(goal_brief, limit=4):
    """A short human effort name derived from the GOAL (zero-model, instant —
    John 2026-08-25: 'when I do the rename can the steward give a
    suggestion?'). Takes the goal's first few salient words; a SUGGESTION the
    rename prompt prefills and the user edits or replaces — never applied on
    its own. Empty string when the goal is too thin to suggest from."""
    words = re.findall(r"[A-Za-z][\w\-]*", str(goal_brief or ""))
    picked = [w for w in words if w.lower() not in _NAME_STOP][:limit]
    name = " ".join(picked).strip()[:40].strip()
    return name if len(name) >= 3 else ""


def read_swarm_trails(campaign_dir: str):
    """Scoped, lease-aware heartbeat files from supervised swarm seats.

    Trio's shared swarm-lookin contract treats 90 seconds without a refreshed
    trail as death. The cockpit mirrors that boundary: stale or malformed
    files remain visible as evidence, but are never presented as live work.
    """
    root = Path(campaign_dir)
    candidates = []
    for folder in (root, root / ".ecgberht"):
        if not folder.is_dir():
            continue
        try:
            names = list(folder.iterdir())
        except OSError:
            continue
        for p in names:
            if not p.is_file():
                continue
            if not _SWARM_HEARTBEAT_NAME.fullmatch(p.name):
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
    r"\[(\d\d:\d\d)\]\s+(.+?)\s+\u00b7\s+(t=0|final|t\+\d+[hm]\d*m?)\s*$")
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


def write_attention(campaign_dir, state, reason, failure_code=None, by="engine"):
    """Atomic write of the ONE attention flag (the same shape the steward writes)."""
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
    tmp = f.with_name(f.name + ".%s.tmp" % os.getpid())
    tmp.write_text(json.dumps(rec, indent=2), encoding="utf-8")
    os.replace(tmp, f)
    return rec


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
                                "tick": h.group(3)}
                        break
                break
        i -= 1
    if not rows:
        return None
    return {"head": head, "rows": rows}


def _newest_status_log(campaign_dir, depth=3):
    root = Path(campaign_dir)
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
            "age": _humanize(age), "age_seconds": age, "source": source}


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
            return _parse_epoch(value) if value else None
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


def running_code_jobs(campaign_dir):
    """The code jobs this steward commissioned that are still running, observed from its own job record (2026-10-05, his
    word: the status updates "don't seem to be congruent with what's actually happening" - a job ran for an hour while
    the status showed the steward's old note). [{id, title, minutes}] newest first; [] when none or unreadable."""
    try:
        raw = json.loads((Path(campaign_dir) / ".ecgberht" / "code-jobs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = raw if isinstance(raw, list) else (raw.get("jobs") or list(raw.values()) if isinstance(raw, dict) else [])
    out = []
    for r in rows:
        if not isinstance(r, dict) or str(r.get("status")) not in ("running", "landing", "queued"):
            continue
        title = ""
        for line in str(r.get("brief") or "").splitlines():
            line = line.strip().lstrip("#").strip()
            if line:
                title = line[len("Work order:"):].strip() if line.lower().startswith("work order:") else line
                break
        minutes = None
        try:
            minutes = int(max(0.0, time.time() - time.mktime(time.strptime(str(r.get("started"))[:19], "%Y-%m-%d %H:%M:%S"))) // 60)
        except (ValueError, OverflowError):
            pass
        out.append({"id": str(r.get("id") or ""), "title": title[:120] or "a code job", "minutes": minutes,
                    "status": str(r.get("status"))})
    return list(reversed(out))


def landed_not_live(campaign_dir):
    """Titles of this steward's code jobs landed in Anchor today whose commit the running build does not carry yet
    (two-lane step 6, 2026-10-05). [] when none or unreadable."""
    try:
        raw = json.loads((Path(campaign_dir) / ".ecgberht" / "code-jobs.json").read_text(encoding="utf-8"))
        from steward_cockpit import code_jobs as _cj
    except Exception:
        return []
    rows = raw if isinstance(raw, list) else (raw.get("jobs") or list(raw.values()) if isinstance(raw, dict) else [])
    today = time.strftime("%Y-%m-%d")
    out = []
    for r in rows:
        if isinstance(r, dict) and r.get("landed") and str(r.get("finished") or "").startswith(today):
            try:
                if _cj.live_state(r) == "waits for a restart":
                    t = next((ln.strip().lstrip("#").strip() for ln in str(r.get("brief") or "").splitlines() if ln.strip()), "")
                    out.append((t[len("Work order:"):].strip() if t.lower().startswith("work order:") else t)[:100] or r.get("id"))
            except Exception:
                continue
    return out


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
    m = read_map(campaign_dir)
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
    local_evidence = _local_status_evidence(campaign_dir, m, st, active)
    now_lines = []
    running = None
    jobs = running_code_jobs(campaign_dir)
    waiting_restart = landed_not_live(campaign_dir)
    # 2026-10-05: a running code job is OBSERVED work - it leads, ahead of the steward's own note
    for j in jobs[:2]:
        now_lines.append("code job %s — %s%s" % (j["status"], j["title"], (" (%d min)" % j["minutes"]) if j["minutes"] is not None else ""))
    for w in waiting_restart[:2]:
        now_lines.append("landed, waits for a restart \u2014 %s" % w)
    if jobs:
        running = {"kind": "code_job", "label": now_lines[0], "skill": "coder", "source": ".ecgberht/code-jobs.json",
                   "age": ("%d min" % jobs[0]["minutes"]) if jobs[0]["minutes"] is not None else ""}
    # THE LOOK-THROUGH: the commissioned skill is what is happening;
    # "steward working" is the whole story only when nothing else runs.
    if look and not look["final"]:
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
    if look and look["final"] and (look.get("halt_reason") or look.get("limit")):
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
    waiting = _real_wait((m["heartbeat"]["human_wait"] or "").split("\u00b7")[0].strip())
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
    if effort_line.get("stale"):
        now_lines.append("effort line as of " + effort_line["as_of"] + " \u2014 "
                         + str(effort_line["behind_days"]) + " day(s) older than the newest work; the steward has not restamped it")
    if active and active.get("part") in ("slice", "rigor", "integrate", "harden") \
            and not active.get("gate") and active.get("commissioned_as"):
        now_lines.append("commissioned without a gate command")
    slice_ = slice_of(m)
    started = _slice_started_epoch(campaign_dir, slice_["id"]) if slice_ else None
    live_skill = bool(look and not look["final"])
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
    doing = (running or {}).get("label") or (now_lines[0] if now_lines else "Idle")
    summary = (slice_["name"] + (" — " + slice_["summary"] if slice_.get("summary") else "")) if slice_ else (m.get("goal_brief") or m.get("name") or "")
    status_line = "%s · %s/%s done · %s" % (
        plan_step or "no active step", plan["steps_done"], plan["steps_total"],
        plan["attention"] or "quiet")
    todo = (next_bullets(next_text)[:1] or [""])[0]
    seats = []
    for item in swarm:
        if isinstance(item, dict):
            seats.append((item.get("label") or "seat") + " · " + (item.get("state") or "?"))
    facts = status_facts(
        effort=m.get("name") or "",
        summary=summary,
        doing=doing,
        status=status_line,
        tests=(look.get("tests") if live_skill and look else None) or local_evidence["tests"],
        blocker=("waiting on you: " + waiting) if waiting else ("blocked: " + halt["reason"] if halt else ""),
        procs=" · ".join(seats) if seats else (
            ((running or {}).get("skill") + " (commissioned)") if (running or {}).get("kind") == "skill" else ""),
        journal=local_evidence["journal"],
        eta=(look.get("eta") if live_skill and look and look.get("eta") else None) or local_evidence["eta"],
        todo=todo,
    )
    compact = {"activity": doing,
               "latest_event": latest_event, "next": next_bullets(next_text)[:1],
               "question": (engine_state or {}).get("open_question") or plan.get("waiting_on_you") or "",
               "facts": facts}
    out = {"at": time.strftime("%Y-%m-%d %H:%M"),
           "status_id": f"{time.time_ns():020d}",
           "effort": m["name"], "latest_event":latest_event, "compact":compact,
           "lead_line": lead,
           "now": now_lines,
           "running": running,
           "slice": slice_,
           "eta": estimate_eta(slice_, look, started) if live_skill and look.get("eta") else local_evidence["eta"],
           "tests": (look.get("tests") or local_evidence["tests"]) if live_skill else local_evidence["tests"],
           "journal": local_evidence["journal"],
           "evidence": {"source": local_evidence["source"], "checks": local_evidence["checks"],
                        "journal": local_evidence["journal_source"],
                        "eta": {"state": "available", "source": "live_skill", "skill": look.get("skill")}
                               if live_skill and look.get("eta") else local_evidence["eta_source"]},
           "focus_warning": focus_warning,
           "next_bullets": next_bullets(next_text),
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
        out["deliverables_count"] = len(read_deliverables(campaign_dir)["items"])
    except Exception:
        out["deliverables_count"] = 0
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
        d = json.loads(f.read_text(encoding="utf-8"))
        if not isinstance(d, dict) or not d.get("at"):
            return None
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
      absolute / drive / backslash segment and no second query key.

    Any ``http(s)://``, protocol-relative ``//``, ``../`` or other
    traversal-bearing token yields None (the row renders as text)."""
    if not token or not isinstance(token, str):
        return None
    t = token.strip()
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
                for tok in cell.replace(",", " ").split():
                    tok = tok.strip().strip("()[]")
                    if "/" in tok or "." in tok:
                        cand_plain = tok
                        break
            if m_bt or cand_plain:
                cand = (m_bt.group(1).strip() if m_bt else cand_plain)
                if cand.startswith("/report/") or cand.startswith("/artifact/"):
                    # (2026-09-05) a route-shaped token is judged by the
                    # contained grammar ONLY — a hostile cell gets route None
                    # and stays text; it never reaches the filesystem branch.
                    route = classify_route(cand)
                    openable = route is not None
                else:
                    try:
                        real = os.path.realpath(str(Path(campaign_dir) / cand))
                        if (real == cdir_real
                                or real.startswith(cdir_real + os.sep)) \
                                and os.path.isfile(real):
                            path_rel = os.path.relpath(real, cdir_real).replace(os.sep, "/")
                            openable = True
                        else:
                            path_rel = cand
                    except OSError:
                        path_rel = cand
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
        if refinement is not None:
            if not refinement.get("ok"):
                return {"exists": True, "items": items, "error": refinement.get("error")}
            managed = refinement_items(campaign_dir, refinement["state"])
            paths = {item["path"] for item in managed}
            items = managed + [item for item in items if item.get("path") not in paths]
        approved = [{**item, "what": item["product_id"], "step": item["step_id"],
            "date": item.get("accepted_at", ""), "accepted": True, "openable": True, "managed": True}
            for item in (refinement or {}).get("approved_products", [])]
        for item in items:
            item["accepted_current"] = bool((refinement or {}).get("current_approvals", {})
                .get(item.get("step"), {}).get(item.get("product_id"), False))
            if item.get("managed"):
                item["history"] = [v for v in item.get("history", []) if v.get("revision_id") != item.get("revision_id")]
        from anchor_notebooks import decorate
        return {"exists": True, "approved": approved,
                "finished_projection": (refinement or {}).get("finished_projection"),
                "items": [decorate(campaign_dir, item)
                for item in items + _plan_doc_rows(campaign_dir, items)]}
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
        m = read_map(str(p))
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


def current_review_items(map_, items):
    from .navigation_compat import resolve_step
    steps = (map_ or {}).get("steps") or []
    current = []
    for it in items or []:
        owner = resolve_step(steps, it.get("step"))
        if owner is None:
            continue
        nav = (owner or {}).get("navigation") or {}
        if it.get("accepted") or it.get("accepted_current"):
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
            historical = re.match(r"^(?:HISTORICAL|SUPERSEDED|ARCHIVED|EARLIER|PREVIOUS)\b", str(it.get("what") or ""), re.I)
            if not historical and (normalize(it.get("path")) in featured or designation):
                current.append(it)
    current.sort(key=lambda it: str(it.get("date") or ""), reverse=True)
    return current


def read_deliverables(campaign_dir: str):
    """Expose authoritative ownership/current flags to every cockpit client."""
    from .navigation_compat import resolve_step
    result = _read_deliverables(campaign_dir)
    map_ = read_map(campaign_dir)
    items = result.get("items") or []
    current_items = current_review_items(map_, items)
    current = {id(it) for it in current_items}
    decorated = []
    for it in items:
        owner = resolve_step(map_["steps"], it.get("step"))
        decorated.append({**it, "owner_step_id": owner.get("id") if owner else None,
                          "is_current": id(it) in current})
    return {**result, "items": decorated, "acts": review_acts(map_, current_items),
            "current_warning": _focused_step(map_)[1]}


def review_acts(map_, current_items):
    """What John does now, in order: review each product awaiting him (from the
    current list), open the current step's featured file, then what the steward
    said comes next. (The open decision is added by the page from the engine state.)"""
    acts = []
    for it in current_items:
        if it.get("managed") and it.get("phase") in ("awaiting_review", "blocked"):
            acts.append({"act": "Review", "label": str(it.get("what") or it.get("product_id") or it.get("path") or "").replace("-", " "),
                         "path": it.get("path"), "step": it.get("step"), "item": it})
    cur, _warn = _focused_step(map_)
    row = next((it for it in current_items if not it.get("managed")), None)   # the current step's own file (featured or designated)
    if row:
        acts.append({"act": "Open", "label": str(row.get("what") or row.get("path") or "").strip(),
                     "path": row.get("path"), "step": row.get("step"), "item": row})
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


def discover_efforts(root_dir: str):
    """Steward efforts under a project: the project root itself (if it has a
    Face) plus one level of subdirs carrying their own ECGBERHT.md - the same
    one-level rule the engine's discovery uses. Deterministic, read-only."""
    root = Path(root_dir)
    efforts = []
    candidates = [root]
    try:
        candidates += sorted(
            p for p in root.iterdir()
            if p.is_dir() and p.name not in ("node_modules", ".git", "vendor")
            and not p.name.startswith((".", "_"))
        )
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
    return efforts


def map_stamp(campaign_dir: str):
    """Cheap change detector: mtimes of the files the map is painted from."""
    root = Path(campaign_dir)
    stamp = []
    for rel in ("ECGBERHT.md", "roadmap.json", "strip.json", "DELIVERABLES.md",
                ".ecgberht/attention.json"):
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
    try:
        probe = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=str(campaign_dir), capture_output=True, text=True, timeout=15)
        top = probe.stdout.strip().replace("/", os.sep).rstrip(os.sep).lower() if probe.returncode == 0 else ""
        here = os.path.normpath(os.path.realpath(str(campaign_dir))).rstrip(os.sep).lower()
        if not top or os.path.normpath(os.path.realpath(top)).lower() != here:
            return "not committed (the Campaign is not a repo here)"
        add = subprocess.run(["git", "add", "--", *rels], cwd=str(campaign_dir), capture_output=True, text=True, timeout=30)
        if add.returncode != 0:
            return "commit failed: " + ((add.stderr or add.stdout).strip().splitlines() or ["git add refused"])[-1]
        c = subprocess.run(["git", "commit", "-q", "-m", message, "--", *rels], cwd=str(campaign_dir), capture_output=True, text=True, timeout=30)
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


def plan_drift(campaign_dir: str):
    """Is the roadmap behind the plan documents? Pure, disk-true, never raises."""
    refinement = read_refinement(campaign_dir)
    if refinement is not None:
        status = refinement.get("projection_status", {})
        return {"drift": not (refinement.get("ok") and status.get("consistent")),
                "reason": "" if refinement.get("ok") and status.get("consistent") else str(status.get("error") or refinement.get("error") or "projection-lag"),
                "docs": ["PLAN.md"], "generation": status.get("generation")}
    root = Path(campaign_dir)
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
