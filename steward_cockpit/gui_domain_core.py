"""gui_domain_core.py — Stage 2 · Do-Analysis ("Juice") Pure Domain Core for Anchor GUI.

Wave 14 Anvil Best-in-Class Refactoring (`2. Steward Session & Model Driver` + `3. Campaign Ledger & Star Chart`):
Extracts 100% pure, deterministic, zero-I/O state projections and domain calculations from `anchor_gui.py`:
  - Source fingerprint & build ID derivation (`compute_build_fingerprint`)
  - Versioned `window.ANCHOR_BOOT` bootstrap contract assembly (`assemble_anchor_boot`)
  - Layout-D effort zone routing (`effort_zone`)
  - Paradigm-2 lane session tile title projection (`session_tile_title`)
  - Compact capture-rate rollup formatting (`fmt_capture_rate_short`)
  - Starvation age & goal last-spoken date reductions (`compute_strip_ages_from_records`, `extract_goal_last_at_from_turns`)
  - Gandalf run timestamp formatting (`gandalf_ts_label`)
"""
from __future__ import annotations

from datetime import datetime
import hashlib
from typing import Any, Dict, Iterable, List


EFFORT_ZONE_RESEARCH = "research"
EFFORT_ZONE_PLAN_BUILD = "plan_build"
ANCHOR_BOOT_SCHEMA_VER = 1


def compute_build_fingerprint(
    head: str,
    stamps: Iterable[str],
    fallback_mtime: str = "0",
) -> str:
    """Derive a deterministic `<head>+<sha1[:7]>` build ID from git HEAD and sorted file stamps."""
    head_clean = str(head or "").strip()
    stamp_list = [str(s) for s in (stamps or ()) if s]
    if stamp_list:
        digest = hashlib.sha1("|".join(stamp_list).encode("utf-8")).hexdigest()[:7]
        return f"{head_clean}+{digest}" if head_clean else digest
    if head_clean:
        return head_clean
    return str(fallback_mtime or "0")


def assemble_anchor_boot(
    build_id: str,
    auth_required: bool,
    extra: Dict[str, Any] | None = None,
    schema_ver: int = ANCHOR_BOOT_SCHEMA_VER,
) -> Dict[str, Any]:
    """Assemble the versioned `window.ANCHOR_BOOT` server->client bootstrap dictionary."""
    out: Dict[str, Any] = {
        "schema_ver": int(schema_ver),
        "build": str(build_id or ""),
        "auth": bool(auth_required),
    }
    if isinstance(extra, dict):
        for k, v in extra.items():
            if k not in ("schema_ver", "build", "auth"):
                out[k] = v
    return out


def effort_zone(
    record: Any,
    zone_research: str = EFFORT_ZONE_RESEARCH,
    zone_plan_build: str = EFFORT_ZONE_PLAN_BUILD,
) -> str | None:
    """Return the Layout-D board zone for an effort record by `current_stage` / `kind`."""
    if not isinstance(record, dict):
        return None
    kind = (record.get("kind") or "").strip()
    if kind in ("general", "grass-dev"):
        return None
    stage = (record.get("current_stage") or "").strip()
    if stage == "research":
        return zone_research
    if stage in ("plan", "build"):
        return zone_plan_build
    return None


def session_tile_title(rep: Any) -> str:
    """Derive the visible title for a Paradigm-2 lane tile from a representative effort view."""
    if not rep or not isinstance(rep, dict):
        return "session"
    if rep.get("discovered"):
        return (rep.get("title") or rep.get("artifact_path") or "imported").strip()
    sub = (rep.get("sub") or "").strip()
    if sub:
        return sub
    return (rep.get("skill") or "session").strip() or "session"


def fmt_capture_rate_short(rate: Any) -> str:
    """Format a compact capture-rate note for project-row rollup (never raises)."""
    if not isinstance(rate, dict):
        return ""
    try:
        total = int(rate.get("total", 0) or 0)
        measured = int(rate.get("measured", 0) or 0)
        unm = int(rate.get("unmeasured", 0) or 0)
        failed = int(rate.get("capture-failed", 0) or rate.get("capture_failed", 0) or 0)
        if total <= 0:
            return ""
        parts = [f"measured {measured}/{total}"]
        if unm:
            parts.append(f"{unm} unmeasured")
        if failed:
            parts.append(f"{failed} capture-failed")
        return " \u00b7 ".join(parts)
    except Exception:
        return ""


def gandalf_ts_label(ts: Any) -> str:
    """Format a Gandalf run's unix timestamp as `YYYY-MM-DD HH:MM` (honest empty on error)."""
    try:
        val = float(ts)
        return datetime.fromtimestamp(val).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def compute_strip_ages_from_records(
    strip_by_pid: Dict[str, Dict[str, Any]] | None,
) -> Dict[str, int]:
    """Extract each project's `anti_starvation_age_days` from pre-loaded strip dicts."""
    out: Dict[str, int] = {}
    for pid, strip_obj in (strip_by_pid or {}).items():
        if not pid or not isinstance(strip_obj, dict):
            continue
        v = strip_obj.get("anti_starvation_age_days")
        out[str(pid)] = int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else 0
    return out


def extract_goal_last_at_from_turns(turns: Iterable[Dict[str, Any]] | None) -> Dict[str, str]:
    """Compute the latest `YYYY-MM-DD` date spoken on each goal from conversation turns."""
    out: Dict[str, str] = {}
    for t in turns or ():
        if not isinstance(t, dict):
            continue
        g = str(t.get("goal") or "")
        at = str(t.get("at") or "")[:10]
        if g and at:
            out[g] = max(out.get(g, ""), at)
    return out
