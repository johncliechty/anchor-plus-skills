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
import math
import os
import re
import time
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
            steps.append({
                "id": s.get("id") or s.get("step_id") or "",
                "name": s.get("name") or "(unnamed)",
                "status": s.get("status") or "proposed",
                "done_when": s.get("done_when") or "",
                "waiting_on": s.get("waiting_on"),
                "commissioned_as": s.get("commissioned_as"),
                "part": part,
                "gate": gate,
            })
        goal_flips = [ev for ev in (roadmap.get("roadmap_events") or [])
                      if ev.get("kind") == "goal_flip"]

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
    }
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
    # No close yet → nothing to re-read. A close without a matching goal_flip
    # is the Math Review hole (goal frozen after the slice that falsified it).
    goal_reread = (not last_done_id) or (
        bool(last_flip) and last_flip_step == last_done_id)

    return {
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
        "goal_reread": goal_reread,
        "heartbeat": heartbeat,
        "human_wait_face": human_wait_face,
        "grasscatch": grasscatch,
        "attention": attention,
        "freshness": freshness,
        "history": {"started": started, "days": days, "history_md": history_md},
        "gaps": gaps,
    }


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
        st = " ".join(str(ev.get(k) or "") for k in ("status", "to", "kind")).lower()
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
    return "" if t.lower().rstrip(".") in ("", "none", "nothing", "-", "\u2014", "n/a") else t


def slice_of(m):
    """The current slice: the active roadmap step, its position, and its
    done-when in one short line."""
    steps = m.get("steps") or []
    active = next((s for s in steps if s.get("status") == "active"), None)
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
    active = next((s for s in m["steps"] if s["status"] == "active"), None)
    look = status_lookthrough(campaign_dir)
    now_lines = []
    running = None
    # THE LOOK-THROUGH: the commissioned skill is what is happening;
    # "steward working" is the whole story only when nothing else runs.
    if look and not look["final"]:
        running = {"kind": "skill", "label": look["label"], "skill": look["skill"],
                   "source": look["source"], "age": look["age"]}
        now_lines.append(look["label"])
    elif m["attention"]["state"] == "working":
        run = (m["attention"]["reason"] or "").strip() \
            or "commissioned work in flight"
        if active and active.get("commissioned_as"):
            run += " \u00b7 as " + str(active["commissioned_as"])
        running = {"kind": "commissioned", "label": run,
                   "skill": str((active or {}).get("commissioned_as") or ""),
                   "source": ".ecgberht/attention.json", "age": ""}
        now_lines.append(run)
    if st.get("busy"):
        line = "steward working"
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
    if halt and not waiting:
        # the run's stop is the thing waiting on him — a limit above all
        waiting = (("model session limit (" + halt["limit"] + "): ") if halt["limit"]
                   else (halt["skill"] + " stopped: ")) + halt["reason"]
        waiting = waiting if len(waiting) <= 220 else waiting[:219].rsplit(" ", 1)[0] + "\u2026"
    plan = {
        "step": plan_step,
        "steps_done": m["steps_done"],
        "steps_total": m["steps_total"],
        "waiting_on_you": waiting,
        "next": next_text,
        "attention": m["attention"]["state"],
        "goal_reread": m.get("goal_reread", True),
    }
    if not m.get("goal_reread", True):
        now_lines.append("goal not re-read since last close")
    if active and active.get("part") in ("slice", "rigor", "integrate", "harden") \
            and not active.get("gate") and active.get("commissioned_as"):
        now_lines.append("commissioned without a gate command")
    slice_ = slice_of(m)
    started = _slice_started_epoch(campaign_dir, slice_["id"]) if slice_ else None
    live_skill = bool(look and not look["final"])
    out = {"at": time.strftime("%Y-%m-%d %H:%M"),
           "status_id": f"{time.time_ns():020d}",
           "effort": m["name"],
           "now": now_lines,
           "running": running,
           "slice": slice_,
           "eta": estimate_eta(slice_, look, started),
           "tests": (look.get("tests") or "") if live_skill else "",
           "next_bullets": next_bullets(next_text),
           "project": project_line(m),
           "lookthrough": ({"source": look["source"], "age": look["age"],
                            "final": look["final"]} if look else None),
           "halt": halt,
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
        return d
    except Exception:
        return None


def read_deliverables(campaign_dir: str):
    """Parse ``<cdir>/DELIVERABLES.md`` — THE campaign deliverables register (the
    steward's OWN convention, campaign journal 0010: one table row per thing a
    human would open; standing rule = a step producing a human-facing artifact is
    not done until listed here). Disk-true, zero-model, one source of truth — the
    cockpit never keeps a second registry.

    Returns ``{"exists": bool, "items": [{"what", "where_text", "path", "date",
    "openable"}]}``. ``path`` is the first backticked span of the Where cell,
    resolved against the campaign dir; ``openable`` is True ONLY when the resolved
    real path stays INSIDE the campaign dir (containment — entries pointing
    outside, e.g. ``../…``, render as text, never as links)."""
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
            path_rel, openable = None, False
            m_bt = re.search(r"`([^`]+)`", where_text)
            # (2026-09-04) a register row written without backticks (the
            # Fractal Orthogonal Basis effort: "report/DRAFT-v1.md") must still
            # open: fall back to the cell's first token that names a file.
            cand_plain = None
            if not m_bt:
                for tok in where_text.replace(",", " ").split():
                    tok = tok.strip().strip("()[]")
                    if "/" in tok or "." in tok:
                        cand_plain = tok
                        break
            if m_bt or cand_plain:
                cand = (m_bt.group(1).strip() if m_bt else cand_plain)
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
                          "date": date,
                          # optional 4th column (John, 2026-08-26): which
                          # roadmap step produced it — a step NUMBER or a
                          # name fragment; the map embeds the link there
                          "step": cells[3].strip() if len(cells) > 3 else "",
                          "openable": openable})
        return {"exists": True, "items": items + _plan_doc_rows(campaign_dir, items)}
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
                         "path": relp, "date": date, "step": "",
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
    for rel in ("ECGBERHT.md", "roadmap.json", "strip.json",
                ".ecgberht/attention.json"):
        try:
            stamp.append((root / rel).stat().st_mtime_ns)
        except OSError:
            stamp.append(0)
    return "-".join(map(str, stamp))
