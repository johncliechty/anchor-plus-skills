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
            lim = 320 if label == "Doing" else 280
            v = compact_line(value, limit=lim) or "—"
        else:
            v = one_line(value, limit=400 if label == "ETA" else 280) or "—"
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


_HEX_HASH_TOKEN_RE = re.compile(r"\b(?:sha256[:_-])?[0-9a-f]{40,64}\b", re.I)
_INTERNAL_ID_TOKEN_RE = re.compile(
    r"\(\s*code\s+job\s+[A-Za-z0-9_.:-]+\s*\)"
    r"|\[\s*code\s+job\s+[A-Za-z0-9_.:-]+\s*\]"
    r"|\bcode\s+job\s+\d{8}[A-Za-z0-9_.:-]*\b"
    r"|\b(?:rev|pres|prod|slice|job)[_-][0-9a-f]{8,64}\b",
    re.I,
)
_DELIV_PREFIX_STRIP_RE = re.compile(
    r"^(?:[\u2605\u2b50]\s*|"
    r"(?:START\s+HERE|FOR\s+REVIEW|AWAITING\s+REVIEW|NEEDS\s+REVIEW|CURRENT|"
    r"Primary\s+Deliverable(?:\s+\d+(?:\s+of\s+\d+)?)?|"
    r"Approved\s*[\u2014\u2013\-:]\s*Finalized|FINAL(?:IZED)?|APPROVED(?:\s+VISUAL\s+DIRECTION)?|"
    r"ACCEPTED|IN[\s_-]+PROGRESS|DRAFTING|WORKING|PENDING|"
    r"SUPPORTING|SUPPLEMENTAL|COMPANION|ARCHIVE(?:D)?|SUPERSEDED)"
    r"\s*(?:\([^)]*\)\s*)?(?:[\u2014\u2013\-:]\s*|\s+))",
    re.I,
)
_KNOWN_FILE_EXT_RE = re.compile(
    r"\.(?:pdf|pptx|ppt|docx|doc|xlsx|xls|md|markdown|html|htm|csv|txt|r|rmd|qmd|py|ipynb|json|zip|png|jpg|jpeg|svg|log)$",
    re.I,
)
_SAFE_EXT_RE = re.compile(r"^\.[a-z0-9]{1,10}$")
_SUPPORTING_OR_ARCHIVE_RE = re.compile(
    r"^(?:SUPPORTING|SUPPLEMENTAL|REFERENCE|COMPANION|HISTORICAL|SUPERSEDED|ARCHIVED|EARLIER|PREVIOUS)\b"
    r"|^Existing\s+(?:Earlier|Prior|Historical)\b"
    r"|\b(?:gandalf[-_\s]+(?:read|report|analysis|review|audit)|beta[-_\s]*reader[-_\s]+(?:report|panel|review|audit)|"
    r"verification[-_\s]+log|audit[-_\s]+receipt|smoke[-_\s]+test|working[-_\s]+notes|journal\s+\d+|kept\s*\(not\s+landed\))\b",
    re.I,
)


def _extract_ext(path_or_ext: Any) -> str:
    raw = str(path_or_ext or "").strip()
    if not raw:
        return ""
    raw = raw.split("?", 1)[0].split("#", 1)[0].replace("\\", "/").strip()
    if raw.startswith(".") and "/" not in raw and _SAFE_EXT_RE.match(raw.lower()):
        return raw.lower()
    base = raw.rsplit("/", 1)[-1]
    if "." in base:
        cand = "." + base.rsplit(".", 1)[-1].lower()
        if _SAFE_EXT_RE.match(cand):
            return cand
    return ""


def clean_human_deliverable_title(
    raw_title: Any = "",
    fallback_path: Any = "",
    *,
    path: Any = "",
    fallback: Any = "",
) -> str:
    """Return a clean human-readable deliverable title stripped of status prefixes, hashes, and internal IDs."""
    if not fallback_path and path:
        fallback_path = path
    raw = str(raw_title or "").replace("**", "").replace("`", "").strip()
    s = raw
    for _ in range(6):
        nxt = _DELIV_PREFIX_STRIP_RE.sub("", s).strip()
        if nxt == s:
            break
        s = nxt
    s = _INTERNAL_ID_TOKEN_RE.sub("", s)
    s = _HEX_HASH_TOKEN_RE.sub("", s)
    s = re.sub(r"[\r\n\t]+", " ", s).strip(" \t\u2014\u2013-:|")

    # If empty or reduced to punctuation, fall back to non-hash path segments
    if not s and fallback_path:
        p_norm = str(fallback_path or "").split("?", 1)[0].replace("\\", "/").strip("/")
        parts = [seg for seg in p_norm.split("/") if seg]
        fname = parts[-1] if parts else ""
        stem = _KNOWN_FILE_EXT_RE.sub("", fname)
        stem = _HEX_HASH_TOKEN_RE.sub("", _INTERNAL_ID_TOKEN_RE.sub("", stem)).strip(" -_.")
        if not stem and len(parts) >= 2:
            parent = parts[-2]
            if parent.lower() not in ("deliverables", "revisions", ".ecgberht", "final deliverables", "finished deliverables"):
                stem = _HEX_HASH_TOKEN_RE.sub("", parent).strip(" -_.")
        s = stem

    s = re.sub(r"\(\s*\)", "", s)
    s = re.sub(r"\s+(\.[A-Za-z0-9]{1,10})$", r"\1", s)
    # Strip trailing known file extension when present on a filename/title
    if _KNOWN_FILE_EXT_RE.search(s):
        if " " not in s and ("/" in s or "\\" in s):
            s = s.replace("\\", "/").rsplit("/", 1)[-1]
        s = _KNOWN_FILE_EXT_RE.sub("", s)

    # Convert slug-shaped identifiers and underscore runs into clean words
    if s and " " not in s and ("-" in s or "_" in s):
        s = re.sub(r"[-_]+", " ", s)
    elif "_" in s:
        s = re.sub(r"_+", " ", s)

    s = re.sub(r"\s+", " ", s).strip(" \t\u2014\u2013-:|")
    if not s and fallback:
        fb = _HEX_HASH_TOKEN_RE.sub("", _INTERNAL_ID_TOKEN_RE.sub("", str(fallback or ""))).strip(" \t\u2014\u2013-:|._")
        if fb and " " not in fb and ("-" in fb or "_" in fb):
            fb = re.sub(r"[-_]+", " ", fb)
        s = re.sub(r"\s+", " ", fb).strip(" \t\u2014\u2013-:|")
    return s or "Deliverable"


def sanitize_download_filename(raw_filename: Any, fallback_ext: str = "") -> str:
    """Sanitize a suggested download filename for Content-Disposition while preserving extension and stripping hashes/IDs."""
    ext = _extract_ext(fallback_ext)
    raw = str(raw_filename or "")
    # Strip CR/LF/NUL/control chars, quotes, and path separators immediately
    cleaned = re.sub(r'[\x00-\x1f\x7f"\\\r\n/]+', " ", raw)
    cleaned = cleaned.replace("'", "")
    if not ext:
        ext = _extract_ext(cleaned)
    if ext and cleaned.lower().endswith(ext):
        stem = cleaned[: -len(ext)]
    else:
        stem = _KNOWN_FILE_EXT_RE.sub("", cleaned) if ext else cleaned

    for _ in range(4):
        nxt = _DELIV_PREFIX_STRIP_RE.sub("", stem).strip()
        if nxt == stem:
            break
        stem = nxt
    stem = _INTERNAL_ID_TOKEN_RE.sub("", stem)
    stem = _HEX_HASH_TOKEN_RE.sub("", stem)
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]+', " ", stem)
    stem = re.sub(r"\(\s*\)", "", stem)
    stem = re.sub(r"\s+", " ", stem).strip(" ._-")
    if not stem:
        stem = "Deliverable"
    if len(stem) > 140:
        stem = stem[:140].rstrip(" ._-") or "Deliverable"
    return f"{stem}{ext}" if ext else stem


def suggested_deliverable_filename(human_title: Any, path_or_ext: Any = "") -> str:
    """Build `<Clean Human Title>.<ext>` for a deliverable item."""
    ext = _extract_ext(path_or_ext)
    title = clean_human_deliverable_title(human_title, fallback_path=path_or_ext)
    return sanitize_download_filename(title, fallback_ext=ext)


def classify_deliverable_buckets(
    items: Iterable[Dict[str, Any]] | None,
    approved: Iterable[Dict[str, Any]] | None = None,
) -> Dict[str, Any]:
    """Deterministically partition deliverables into server-computed `buckets` and `key_deliverables` with NO age/2-day eviction."""
    buckets: Dict[str, List[Dict[str, Any]]] = {
        "for_review": [],
        "final": [],
        "in_progress": [],
        "archive": [],
    }
    seen_keys = set()

    def _item_key(d: Dict[str, Any]) -> tuple:
        p = str(d.get("open_path") or d.get("path") or d.get("route") or "").replace("\\", "/").strip().lower()
        rev = str(d.get("revision_id") or d.get("hash") or "").strip().lower()
        w = str(d.get("what") or d.get("human_title") or "").strip().lower()
        return (p, rev) if p else ("", rev, w)

    def _decorate(d: Dict[str, Any], bucket_name: str) -> Dict[str, Any]:
        row = dict(d)
        p_ref = row.get("open_path") or row.get("path") or ""
        ht = str(row.get("human_title") or "").strip()
        if not ht or _HEX_HASH_TOKEN_RE.search(ht) or _INTERNAL_ID_TOKEN_RE.search(ht):
            ht = clean_human_deliverable_title(row.get("what") or row.get("title") or row.get("product_id") or "", p_ref)
        row["human_title"] = ht
        sf = str(row.get("suggested_filename") or "").strip()
        if not sf or _HEX_HASH_TOKEN_RE.search(sf) or _INTERNAL_ID_TOKEN_RE.search(sf):
            sf = suggested_deliverable_filename(ht, p_ref)
        else:
            sf = sanitize_download_filename(sf, fallback_ext=_extract_ext(p_ref))
        row["suggested_filename"] = sf
        row["bucket"] = bucket_name
        return row

    for it in items or []:
        if not isinstance(it, dict):
            continue
        what = str(it.get("what") or it.get("title") or "").strip()
        phase = str(it.get("phase") or "").strip().lower()
        tier = str(it.get("tier") or "").strip().lower()
        explicit_bucket = str(it.get("bucket") or "").strip().lower()
        disp = str(it.get("disposition") or "").strip().lower()
        is_inter = bool(it.get("is_intermediate")) or (
            tier in ("supporting", "supplemental", "archive", "archived")
        ) or bool(_SUPPORTING_OR_ARCHIVE_RE.search(what)) or bool(it.get("auto"))

        if explicit_bucket in buckets:
            b = explicit_bucket
        elif (
            it.get("final_promoted")
            or tier == "final"
            or it.get("accepted") is True
            or it.get("accepted_current") is True
            or phase in ("accepted", "done", "closed", "final")
            or (it.get("reviewed_done") and disp in ("", "approved") and not is_inter)
            or bool(re.match(r"^(?:[\u2605\u2b50]\s*)?(?:FINAL(?:IZED)?|APPROVED|ACCEPTED)\b", what, re.I))
        ) and not (it.get("dismissed") and disp in ("dismissed", "archived", "superseded", "revision_requested")):
            b = "final"
        elif not it.get("reviewed_done") and not it.get("dismissed") and not is_inter and (
            it.get("is_current") is True
            or tier == "for_review"
            or phase in ("awaiting_review", "review", "for_review", "blocked")
            or bool(re.match(r"^(?:[\u2605\u2b50]\s*)?(?:START\s+HERE|FOR\s+REVIEW|AWAITING\s+REVIEW|NEEDS\s+REVIEW|READY\s+FOR\s+REVIEW|CURRENT)\b", what, re.I))
        ):
            b = "for_review"
        elif not it.get("reviewed_done") and not it.get("dismissed") and not is_inter and (
            it.get("provisional") is True
            or tier == "in_progress"
            or phase in ("working", "drafting", "in_progress", "running", "pending")
            or bool(re.match(r"^(?:IN[\s_-]+PROGRESS|DRAFTING|WORKING|PENDING|BUILDING)\b", what, re.I))
        ):
            b = "in_progress"
        else:
            b = "archive"

        k = _item_key(it)
        seen_keys.add(k)
        buckets[b].append(_decorate(it, b))

    for ap in approved or []:
        if not isinstance(ap, dict):
            continue
        k = _item_key(ap)
        if k in seen_keys:
            continue
        seen_keys.add(k)
        what_ap = str(ap.get("what") or ap.get("title") or "").strip()
        is_inter_ap = bool(ap.get("is_intermediate")) or bool(_SUPPORTING_OR_ARCHIVE_RE.search(what_ap))
        b_ap = "archive" if is_inter_ap else "final"
        buckets[b_ap].append(_decorate(ap, b_ap))

    key_deliverables: List[Dict[str, Any]] = []
    for b_key in ("for_review", "in_progress", "final"):
        for entry in buckets[b_key]:
            kd = dict(entry)
            kd.setdefault("status", b_key)
            key_deliverables.append(kd)

    return {
        "buckets": buckets,
        "key_deliverables": key_deliverables,
    }

