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
import os
import re
import time
from pathlib import Path

TAIL_TURNS = 40


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
            steps.append({
                "id": s.get("id") or s.get("step_id") or "",
                "name": s.get("name") or "(unnamed)",
                "status": s.get("status") or "proposed",
                "done_when": s.get("done_when") or "",
                "waiting_on": s.get("waiting_on"),
                "commissioned_as": s.get("commissioned_as"),
            })

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
    att, err = _read_json(root / ".ecgberht" / "attention.json")
    attention = {"state": "unknown", "reason": ""}
    if att:
        attention = {"state": att.get("state", "unknown"),
                     "reason": att.get("reason", "")}

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

    return {
        "dir": str(root),
        "name": root.name,
        "goal": goal,
        "goal_brief": _first_sentence(goal),
        "goal_md": goal_md,
        "steps": steps,
        "steps_done": done,
        "steps_total": len(steps),
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


def compose_status(campaign_dir: str, engine_state=None):
    """The deterministic TWO-PART 10-minute status (handoff 2026-08-25 #2b).

    Zero-model, disk-true — composed from the map + the engine's own state,
    never from the model's memory (the same law as the old ⏱ line, grown to
    carry commissioned runs). TOP (``now``): what is running at this moment —
    the steward's own turn, queued messages, and the commissioned/background
    run the attention flag + the active step's ``commissioned_as`` name.
    BOTTOM (``plan``): where the whole effort stands — active step, n/m done,
    what is waiting on John, the recommended next move.

    One shape, three consumers: the cockpit's right status pane (the
    ``status`` event / verb), the universal file
    ``<cdir>/.ecgberht/status-summary.json``, and the main-dashboard tile.
    """
    m = read_map(campaign_dir)
    st = engine_state or {}
    active = next((s for s in m["steps"] if s["status"] == "active"), None)
    now_lines = []
    if st.get("busy"):
        line = "steward working"
        if st.get("queued"):
            line += " · %d queued" % st["queued"]
        now_lines.append(line)
    if m["attention"]["state"] == "working":
        run = (m["attention"]["reason"] or "").strip() \
            or "commissioned work in flight"
        if active and active.get("commissioned_as"):
            run += " · as " + str(active["commissioned_as"])
        now_lines.append(run)
    if not now_lines:
        now_lines.append("nothing running - "
                         + ("waiting on you"
                            if m["attention"]["state"] == "needs_you"
                            else "quiet"))
    plan = {
        "step": active["name"] if active else "(no active step)",
        "steps_done": m["steps_done"],
        "steps_total": m["steps_total"],
        "waiting_on_you": (m["heartbeat"]["human_wait"] or "")
                          .split("·")[0].strip(),
        "next": (m["heartbeat"]["next_recommended"] or "").strip(),
        "attention": m["attention"]["state"],
    }
    out = {"at": time.strftime("%Y-%m-%d %H:%M"),
           "effort": m["name"],
           "now": now_lines,
           "plan": plan}
    # Deliverables count rides the universal status shape (2026-08-25, John's ask —
    # journal 0010: "where is the thing I paid for?"). Count only; the list itself
    # is the deliverables verb / tile.
    try:
        out["deliverables_count"] = len(read_deliverables(campaign_dir)["items"])
    except Exception:
        out["deliverables_count"] = 0
    return out


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
        return {"exists": False, "items": []}
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
            if m_bt:
                cand = m_bt.group(1).strip()
                try:
                    real = os.path.realpath(str(Path(campaign_dir) / cand))
                    if (real == cdir_real
                            or real.startswith(cdir_real + os.sep)) \
                            and os.path.isfile(real):
                        path_rel = os.path.relpath(real, cdir_real)
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
        return {"exists": True, "items": items}
    except Exception:
        return {"exists": True, "items": []}


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


def list_boneyard(root_dir: str):
    """Efforts resting in <root>/_boneyard, newest burial first."""
    yard = Path(root_dir) / BONEYARD_DIRNAME
    out = []
    if not yard.is_dir():
        return out
    for p in sorted(yard.iterdir()):
        if not (p / "ECGBERHT.md").is_file():
            continue
        m = read_map(str(p))
        try:
            when = time.strftime("%Y-%m-%d", time.localtime(p.stat().st_mtime))
        except OSError:
            when = ""
        out.append({"name": p.name, "goal_brief": m["goal_brief"],
                    "steps_done": m["steps_done"],
                    "steps_total": m["steps_total"], "boneyarded": when})
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
            stamp.append(int((root / rel).stat().st_mtime))
        except OSError:
            stamp.append(0)
    return "-".join(map(str, stamp))
