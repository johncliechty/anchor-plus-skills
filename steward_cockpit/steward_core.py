"""steward_core.py — Pure Essential Core ("Juice" / Do-Analysis) for Steward Cockpit & Campaigns.

Wave 13 Anvil Best-in-Class Refactoring:
Isolates 100% pure, deterministic, zero-I/O domain functions extracted from
`steward_campaign.py` and `steward_routes.py`:
  - Attention state normalization (`normalize_attention`)
  - Relative age humanization (`humanize_age`)
  - ECGBERHT.md Face markdown section parsing & unwrapping (`parse_face_sections`, `strip_markdown`, `format_goal_md`, `first_sentence`)
  - Locked status table & single-line telemetry formatting (`one_line`, `compact_line`, `status_facts`)
  - Managed refinement item folding (`fold_refinement_items`)
  - Lightweight roadmap step projection & product map derivation (`project_work_map_step`, `work_product_map`, `derive_product_map`)
  - Zero-model effort name suggestion (`suggest_effort_name`)
  - Deliverables offered-path extraction (`extract_offered_paths`)

Zero disk, network, thread, or subprocess side effects — directly verifiable via
Hypothesis property-based differential equivalence tests.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List

ATTENTION_STATES = frozenset({
    "working", "needs_you", "deliverable_ready", "blocked", "idle", "quiet",
})

PART_TAGS = ("research", "slice", "rigor", "integrate", "harden")

PART_LABELS = {
    "research": "Background",
    "slice": "The product",
    "rigor": "Prove it",
    "integrate": "Join",
    "harden": "Finish",
}

NAME_STOP = frozenset("""
a an the and or of for to in on with that which not are is was it its this
those these be been being from by as at we our your his her their into over
under between merely can cannot could should would will what when how why
do does did done more most other some such only also than then there
""".split())


def normalize_attention(raw: Any, error: str = "") -> Dict[str, Any]:
    """Normalize a raw `.ecgberht/attention.json` payload into a deterministic attention dict."""
    if raw is None and error == "absent":
        return {"state": "quiet", "reason": "", "source_state": "absent"}
    if not isinstance(raw, dict):
        return {
            "state": "unknown",
            "reason": error or "invalid attention record",
            "source_state": "unknown",
        }
    state = str(raw.get("state") or "quiet").strip().lower()
    if state not in ATTENTION_STATES:
        return {
            "state": "unknown",
            "reason": "invalid attention state: " + state,
            "source_state": state,
        }
    return {
        "state": state,
        "reason": str(raw.get("reason") or ""),
        "source_state": state,
        "state_since": raw.get("state_since"),
        "updated_at": raw.get("updated_at") or raw.get("at"),
        "failure_code": raw.get("failure_code"),
        "schema": raw.get("schema"),
        "provenance": (
            raw.get("provenance")
            if isinstance(raw.get("provenance"), list)
            else []
        ),
    }


def humanize_age(secs: float | int | None) -> str:
    """Format an elapsed age in seconds into a concise human string (`just now`, `5m ago`, `2h ago`, `3d ago`)."""
    if secs is None:
        return "never"
    if secs < 90:
        return "just now"
    n = int(secs // 86400)
    if n >= 1:
        return f"{n}d ago"
    n = int(secs // 3600)
    if n >= 1:
        return f"{n}h ago"
    return f"{int(secs // 60)}m ago"


def parse_face_sections(text: str) -> Dict[str, str]:
    """Split `ECGBERHT.md` (the Face) into its narrative sections by `## ` heading."""
    sections: Dict[str, str] = {}
    current = None
    buf: List[str] = []
    for line in (text or "").splitlines():
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


def strip_markdown(text: str) -> str:
    """Strip blockquote and bold markers while preserving words."""
    out: List[str] = []
    for line in (text or "").splitlines():
        line = re.sub(r"^\s*>\s?", "", line)
        line = line.replace("**", "")
        if re.fullmatch(r"\s*-{3,}\s*", line):
            continue
        out.append(line)
    return "\n".join(out).strip()


def first_sentence(text: str) -> str:
    """Extract the first sentence (up to 220 chars) from a text block."""
    flat = " ".join((text or "").split())
    m = re.search(r"^(.+?[.!?])(\s|$)", flat)
    return (m.group(1) if m else flat)[:220]


def one_line(text: Any, limit: int = 110) -> str:
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


def compact_line(text: Any, limit: int = 180) -> str:
    """Single-line status value that preserves multi-clause telemetry without cutting at the first period."""
    flat = re.sub(r"\s+", " ", str(text or "")).strip()
    if not flat:
        return ""
    if len(flat) <= limit:
        return flat
    clipped = flat[:limit - 1].rsplit(" ", 1)[0]
    return (clipped or flat[:limit - 1]) + "\u2026"


def status_facts(
    effort: str = "",
    summary: str = "",
    doing: str = "",
    status: str = "",
    tests: str = "",
    blocker: str = "",
    procs: str = "",
    journal: str = "",
    eta: str = "",
    todo: str = "",
) -> List[Dict[str, str]]:
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
    out: List[Dict[str, str]] = []
    for label, value in rows:
        if label in ("Doing", "Status", "Procs"):
            lim = 180 if label == "Doing" else 140
            v = compact_line(value, limit=lim) or "—"
        else:
            v = one_line(value, limit=400 if label == "ETA" else 110) or "—"
        out.append({"label": label, "value": v})
    return out


def format_goal_md(text: str) -> str:
    """Goal section with markdown bold kept: blockquote markers and horizontal rules removed, soft wraps unwrapped."""
    lines: List[str] = []
    for line in (text or "").splitlines():
        line = re.sub(r"^\s*>\s?", "", line)
        if re.fullmatch(r"\s*-{3,}\s*", line):
            continue
        lines.append(line)
    paragraphs = re.split(r"\n\s*\n", "\n".join(lines).strip())
    unwrapped: List[str] = []
    for para in paragraphs:
        if re.match(r"\s*[-*]\s", para):
            items: List[str] = []
            cur = None
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


def fold_refinement_items(campaign_dir: str, state: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Pure fold of opening deliverable metadata from the verified refinement state."""
    items: List[Dict[str, Any]] = []
    for step_id, s in (state or {}).get("slices", {}).items():
        for product_id, revision_id in s.get("candidate", {}).items():
            rev = s["revisions"][revision_id]
            imported = [
                r for r in s["revisions"].values()
                if r["product_id"] == product_id and r.get("source_history")
            ]
            base = max((r["source_history"]["iteration"] for r in imported), default=-1)
            presentations = [
                p for p in s.get("presentations", [])
                if any(m["product_id"] == product_id for m in p["members"])
            ]
            offset = 0
            if imported and presentations:
                first = presentations[0]
                first_member = next(m for m in first["members"] if m["product_id"] == product_id)
                first_source = s["revisions"][first_member["revision_id"]].get("source_history")
                offset = (first_source["iteration"] if first_source else base + 1) - first["round"]
            displayed_round = (
                rev["source_history"]["iteration"]
                if rev.get("source_history")
                else s["round"] + offset if presentations or not imported else base + 1
            )
            item: Dict[str, Any] = {
                "what": product_id,
                "path": rev["path"],
                "where_text": rev["path"],
                "step": step_id,
                "date": rev.get("at", state.get("last_event_at", "")),
                "route": None,
                "run": None,
                "openable": True,
                "managed": True,
                "revision_id": revision_id,
                "product_id": product_id,
                "hash": rev["hash"],
                "round": displayed_round,
                "provisional": rev.get("provisional"),
                "visual_companion": rev.get("visual_companion"),
                "phase": s["phase"],
                "history": [],
            }
            for p in s.get("presentations", []):
                for member in p["members"]:
                    if member["product_id"] != product_id:
                        continue
                    shown_round = p["round"] + offset
                    entry = {
                        "what": ("Initial draft" if shown_round == 0 else "Refinement %s" % shown_round),
                        "path": member["path"],
                        "hash": member["hash"],
                        "step": step_id,
                        "product_id": product_id,
                        "revision_id": member["revision_id"],
                        "presentation_id": p["id"],
                        "round": p["round"],
                        "date": p.get("at", ""),
                        "accepted": p["id"] == s.get("accepted_presentation"),
                        "visual_companion": (s["revisions"].get(member["revision_id"]) or {}).get("visual_companion"),
                        "managed": True,
                        "openable": True,
                    }
                    item["history"].append(entry)
                    if member["revision_id"] == revision_id:
                        item["presentation_id"] = p["id"]
                        item["product_id"] = product_id
            presented_ids = {v["revision_id"] for v in item["history"]}
            for old in imported:
                if old["revision_id"] in presented_ids or old["revision_id"] == revision_id:
                    continue
                origin = old["source_history"]
                n = origin["iteration"]
                item["history"].append({
                    "what": ("Initial draft" if n == 0 else f"Refinement {n}"),
                    "path": old["path"],
                    "hash": old["hash"],
                    "step": step_id,
                    "product_id": product_id,
                    "revision_id": old["revision_id"],
                    "date": origin["at"],
                    "managed": True,
                    "openable": True,
                    "visual_companion": old.get("visual_companion"),
                    "source_history": origin,
                })
            items.append(item)
    return items


def project_work_map_step(s: Any) -> Any:
    """Lightweight projection of a roadmap step for `work_product_map` and `status-summary.json`."""
    if not isinstance(s, dict):
        return s
    out = {k: v for k, v in s.items() if k != "refinement"}
    ref = s.get("refinement")
    if isinstance(ref, dict):
        out["refinement"] = {
            "round": ref.get("round"),
            "display_round": ref.get("display_round"),
            "phase": ref.get("phase"),
            "work_phase": ref.get("work_phase"),
        }
    return out


def work_product_map(steps: Iterable[Dict[str, Any]] | None) -> List[Dict[str, Any]]:
    """Backbone of the deliverable (Patton: flow across, detail down)."""
    step_list = list(steps or [])
    groups: List[Dict[str, Any]] = []
    seen = set()
    for tag in PART_TAGS:
        items = [project_work_map_step(s) for s in step_list if s.get("part") == tag]
        if not items:
            continue
        for s in items:
            seen.add(s.get("id"))
        done = sum(1 for s in items if s.get("status") == "done")
        groups.append({
            "tag": tag,
            "label": PART_LABELS.get(tag, tag),
            "done": done,
            "total": len(items),
            "steps": items,
        })
    rest = [project_work_map_step(s) for s in step_list if s.get("id") not in seen]
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


def derive_product_map(steps: Iterable[Dict[str, Any]] | None) -> List[str]:
    """Product map = tagged roadmap steps."""
    step_list = list(steps or [])
    lines: List[str] = []
    seen = set()
    for tag in PART_TAGS:
        for s in step_list:
            if s.get("part") == tag:
                seen.add(s.get("id"))
                bit = tag + ": " + (s.get("name") or "(unnamed)")
                bit += " (" + (s.get("status") or "") + ")"
                if s.get("gate"):
                    bit += " · gate"
                elif tag in ("slice", "rigor", "integrate", "harden"):
                    bit += " · no gate"
                lines.append(bit)
    for s in step_list:
        if s.get("id") not in seen:
            lines.append(
                "untagged: " + (s.get("name") or "(unnamed)")
                + " (" + (s.get("status") or "") + ")"
            )
    return lines


def suggest_effort_name(goal_brief: Any, limit: int = 4) -> str:
    """Derive a short human effort name from the goal's salient words (zero-model, instant)."""
    words = re.findall(r"[A-Za-z][\w\-]*", str(goal_brief or ""))
    picked = [w for w in words if w.lower() not in NAME_STOP][:limit]
    name = " ".join(picked).strip()[:40].strip()
    return name if len(name) >= 3 else ""


def extract_offered_paths(data: Dict[str, Any] | None) -> List[str]:
    """Every in-effort path the deliverables payload offers (items, approved, history, acts, and companions)."""
    if not isinstance(data, dict):
        return []
    out = set()

    def take(it: Any) -> None:
        if isinstance(it, dict) and it.get("path"):
            out.add(str(it["path"]))
            for old in it.get("history") or []:
                if isinstance(old, dict) and old.get("path"):
                    out.add(str(old["path"]))

    for coll in (data.get("items") or [], data.get("approved") or []):
        for it in coll:
            take(it)
    for a in data.get("acts") or []:
        if isinstance(a, dict):
            take(a.get("item"))
            for c in a.get("companions") or []:
                if isinstance(c, dict):
                    take(c.get("item"))
    return sorted(out)
