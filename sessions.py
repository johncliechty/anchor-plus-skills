#!/usr/bin/env python3
"""Anchor R&D session model (v2, Wave 1).

A *session* is the set of artifacts from ONE trio run. ``effort_history`` records
an append-only pointer-record per artifact; for DISCOVERED (brownfield) efforts a
single Crucible/researchPrime/Foreman run shows up as N separate per-file records
(e.g. one Crucible plan run = 7 planning files). This module WRAPS
``effort_history`` (it does not fork its storage) and groups those efforts into
sessions so the surface reads as "one run = one session" (MASTER-PLAN §A).

Grouping rules (frozen design, MASTER-PLAN "Architecture → A. Session model"):

- **RUN efforts** (``effort_history.is_discovered(e) is False``): each effort is
  its own session; group key = its ``job_id`` (run job → output_dir is already
  1:1 with a session).
- **DISCOVERED efforts** (``source == "discovered"``): group by the *parent
  directory* of the effort's ``artifact_path`` (a folder-relative POSIX path). All
  discovered files sharing a parent dir = ONE session
  (``planning/brownfield-discovery/`` is one session, ``planning/rnd-v1/`` another).
- **Fallback** for discovered efforts with no usable parent dir (flat / top-level
  files): group key = ``skill`` + a coarse timestamp cluster (same skill within a
  small time window collapses into one session).

Per session:
- ``provenance`` = ``"imported"`` if the members are discovered, else ``"run"``.
- ``timestamp`` = ``max(created_at)`` across members; sessions sort NEWEST-FIRST.
- ``title`` = a master-plan-like member's title if present (kind/title contains
  "master"), else the parent-dir basename, else the first member's title.
- ``member_files`` = the effort records belonging to the session.

A small **escape hatch** — ``merge_sessions`` / ``split_session`` — lets the user
fix mis-grouped discovered files. Overrides survive in a tiny sidecar JSON
(``sessions-overrides.json``) under the lane store; that is a small JSON pointer,
trackable under the C9/C10 policy.

Stdlib only. Reuses ``effort_history`` helpers; never forks its storage.
"""

import hashlib
import json
import time
from pathlib import PurePosixPath

import effort_history as _eh
import paths as _paths

#: Sidecar (under the lane store dir) holding manual merge/split overrides.
OVERRIDES_NAME = "sessions-overrides.json"

#: Default time window (seconds) for the fallback skill+timestamp clustering of
#: discovered efforts that have no usable parent directory. Files of the same
#: skill whose timestamps fall within this window collapse into one session.
FALLBACK_CLUSTER_WINDOW_S = 3600.0

#: Provenance values.
PROV_RUN = "run"
PROV_IMPORTED = "imported"


# ── Session record ──────────────────────────────────────────────────────────

def make_session(session_id, lane, skill, timestamp, title, member_files,
                 provenance, summary_ref=None):
    """Build a session record dict (the canonical shape, MASTER-PLAN §A).

    Fields: ``session_id``, ``lane``, ``skill``, ``timestamp``, ``title``,
    ``member_files`` (list of effort records), ``provenance`` (``"run"`` |
    ``"imported"``), ``summary_ref`` (default ``None``).
    """
    return {
        "session_id": session_id,
        "lane": lane,
        "skill": skill,
        "timestamp": timestamp,
        "title": title,
        "member_files": list(member_files),
        "provenance": provenance,
        "summary_ref": summary_ref,
    }


# ── Override sidecar (merge/split persistence) ──────────────────────────────

def _overrides_path(folder_path, project_id, lane):
    return _eh.lane_dir(folder_path, project_id, lane) / OVERRIDES_NAME


def _load_overrides(folder_path, project_id, lane):
    """Load the merge/split override map for a lane.

    Shape::

        {
          "merge":  {"<canonical_sid>": ["<sid>", "<sid>", ...]},
          "split":  {"<sid>": {"<job_id>": "<new_sid>", ...}}
        }

    ``merge`` maps a canonical session_id to the set of computed group keys that
    should be folded into it. ``split`` maps a computed session_id to a per-member
    (job_id) reassignment to a new session_id.
    """
    p = _overrides_path(folder_path, project_id, lane)
    if not p.exists():
        return {"merge": {}, "split": {}}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"merge": {}, "split": {}}
    if not isinstance(raw, dict):
        return {"merge": {}, "split": {}}
    raw.setdefault("merge", {})
    raw.setdefault("split", {})
    return raw


def _save_overrides(folder_path, project_id, lane, overrides):
    p = _overrides_path(folder_path, project_id, lane)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(overrides, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    tmp.replace(p)


# ── Grouping ─────────────────────────────────────────────────────────────────

def _created_at(rec):
    try:
        return float(rec.get("created_at", 0.0) or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _parent_dir(rec):
    """The folder-relative POSIX parent dir of a discovered effort, or ``""``.

    A top-level file (e.g. ``PLAN.md`` with no directory) has no usable parent
    dir → returns ``""`` so the caller routes it to the fallback clusterer.
    """
    rel = (rec.get("artifact_path") or "").strip()
    if not rel:
        return ""
    parent = PurePosixPath(rel.replace("\\", "/")).parent
    s = parent.as_posix()
    if s in (".", "", "/"):
        return ""
    return s


def _is_master_like(rec):
    """True if a member looks like a MASTER-PLAN (kind/title contains 'master')."""
    blob = f"{rec.get('kind', '')} {rec.get('title', '')}".lower()
    return "master" in blob


def _session_title(group_key, members):
    """Title preference: master-plan member → parent-dir basename → first title."""
    for m in members:
        if _is_master_like(m):
            t = (m.get("title") or "").strip()
            if t:
                return t
    # Parent-dir basename (group_key is the parent dir for discovered sessions).
    if group_key:
        base = PurePosixPath(group_key).name
        if base:
            return base
    for m in members:
        t = (m.get("title") or "").strip()
        if t:
            return t
    return members[0].get("job_id", "") if members else ""


def _run_fallback_id(rec):
    """A STABLE per-record identity for a run effort lacking a usable job_id.

    The frozen rule is "one run effort = one session". A run job_id is normally
    1:1 with a session, but a record with a missing/empty ``job_id`` must NOT
    collapse with every other empty-job_id run into a single ("run", "") group.
    We derive a deterministic per-record key from the record's own stable fields
    (the same record always yields the same key across repeated ``list_sessions``
    calls — determinism matters for Wave 6 cache keying), so two distinct empty-
    job_id run efforts yield two distinct sessions.
    """
    parts = [
        str(rec.get("artifact_path") or ""),
        str(rec.get("created_at") or ""),
        str(rec.get("skill") or ""),
        str(rec.get("kind") or ""),
        str(rec.get("title") or ""),
        str(rec.get("prompt_seed") or ""),
    ]
    h = hashlib.sha1("\x00".join(parts).encode("utf-8")).hexdigest()
    return f"nojob::{h[:16]}"


def _compute_group_key(rec):
    """Compute the natural (pre-override) group key for one effort.

    - run effort  → ``("run", job_id)`` (or a stable per-record fallback id when
      ``job_id`` is missing/empty, so one run effort = one session).
    - discovered w/ parent dir → ``("dir", parent_dir)``
    - discovered w/o parent dir → fallback marker ``("fallback", skill)`` (the
      timestamp cluster is applied as a second pass).
    """
    if not _eh.is_discovered(rec):
        job_id = (rec.get("job_id") or "").strip()
        if not job_id:
            return ("run", _run_fallback_id(rec))
        return ("run", job_id)
    parent = _parent_dir(rec)
    if parent:
        return ("dir", parent)
    return ("fallback", rec.get("skill") or "")


def _cluster_fallback(records, window_s):
    """Cluster discovered, parent-dir-less efforts by skill + timestamp window.

    Records of the SAME skill whose ``created_at`` falls within ``window_s`` of
    the running cluster anchor collapse into one cluster. Returns a list of
    ``(cluster_key, [records])`` where ``cluster_key`` is stable per cluster.
    """
    by_skill = {}
    for r in records:
        by_skill.setdefault(r.get("skill") or "", []).append(r)
    clusters = []
    for skill, recs in by_skill.items():
        recs_sorted = sorted(recs, key=_created_at)
        anchor = None
        bucket = []
        idx = 0
        for r in recs_sorted:
            ts = _created_at(r)
            if anchor is None or ts - anchor <= window_s:
                if anchor is None:
                    anchor = ts
                bucket.append(r)
            else:
                clusters.append((f"fallback::{skill}::{idx}", bucket))
                idx += 1
                anchor = ts
                bucket = [r]
        if bucket:
            clusters.append((f"fallback::{skill}::{idx}", bucket))
    return clusters


def _group_keystr(group_key):
    """A stable string form of a computed group key (used as session_id base)."""
    kind, val = group_key
    return f"{kind}::{val}"


def list_sessions(folder_path, project_id, lane, cluster_window_s=None):
    """Group a lane's efforts into sessions, NEWEST-FIRST (MASTER-PLAN §A).

    Reads the lane's efforts via ``effort_history.list_efforts`` (already
    newest-first), groups them per the frozen rules, applies any manual
    merge/split overrides, and returns session records sorted newest-first by
    ``timestamp`` (= ``max(created_at)`` across members).

    Returns ``[]`` for an empty lane.
    """
    if cluster_window_s is None:
        cluster_window_s = FALLBACK_CLUSTER_WINDOW_S
    efforts = _eh.list_efforts(folder_path, project_id, lane)
    if not efforts:
        return []

    # The store-lane this call resolves to (research/planning/build/...). The
    # BUILD lane's session_ids are LANE-QUALIFIED (a ``build::`` prefix on the
    # keystr) so a discovered build session never collides with the planning
    # session that shares its source directory — the Foreman EXECUTION-LOG lives
    # under ``planning/<version>/`` alongside the plan docs, so both lanes group
    # by the SAME parent dir and would otherwise mint the IDENTICAL ``dir::…`` id
    # (a duplicate DOM ``data-session`` → the wrong tile/panel opens). A session
    # is per-lane anyway, so qualifying is the correct, stable identity. Only
    # build is qualified (it is the sole cross-lane same-dir case + has no
    # pre-existing cached summaries to orphan); other lanes are unchanged.
    store_lane = _eh._resolve_subdir(lane)
    _id_prefix = f"{store_lane}::" if store_lane == "build" else ""

    def _keystr(group_key):
        return _id_prefix + _group_keystr(group_key)

    # 1. Compute natural group keys. Defer parent-dir-less discovered efforts to
    #    the fallback clusterer.
    groups = {}        # keystr -> {"key": group_key, "members": [...]}
    fallback_pool = []
    for rec in efforts:
        gk = _compute_group_key(rec)
        if gk[0] == "fallback":
            fallback_pool.append(rec)
            continue
        ks = _keystr(gk)
        groups.setdefault(ks, {"key": gk, "members": []})["members"].append(rec)

    # 2. Fallback clustering for parent-dir-less discovered efforts.
    for cluster_key, members in _cluster_fallback(fallback_pool, cluster_window_s):
        gk = ("fallback", cluster_key)
        ks = _keystr(gk)
        groups.setdefault(ks, {"key": gk, "members": []})["members"].extend(members)

    # 3. Apply manual overrides (merge/split escape hatch).
    overrides = _load_overrides(folder_path, project_id, lane)
    groups = _apply_overrides(groups, overrides)

    # 4. Materialize session records. (``store_lane`` resolved above.)
    sessions = []
    for ks, info in groups.items():
        members = info["members"]
        if not members:
            continue
        gk = info["key"]
        group_val = gk[1] if isinstance(gk, tuple) else gk
        discovered = all(_eh.is_discovered(m) for m in members)
        provenance = PROV_IMPORTED if discovered else PROV_RUN
        ts = max(_created_at(m) for m in members)
        # skill: first member carrying one.
        skill = ""
        for m in members:
            if m.get("skill"):
                skill = m["skill"]
                break
        title_key = group_val if (isinstance(gk, tuple) and gk[0] == "dir") else ""
        title = _session_title(title_key, members)
        sessions.append(make_session(
            session_id=ks,
            lane=store_lane,
            skill=skill,
            timestamp=ts,
            title=title,
            member_files=members,
            provenance=provenance,
        ))

    # 5. Sort newest-first (ties broken by session_id for determinism).
    sessions.sort(key=lambda s: (s["timestamp"], s["session_id"]), reverse=True)
    return sessions


def _apply_overrides(groups, overrides):
    """Fold/split the computed ``groups`` per the manual override map.

    ``split`` first: reassign individual members (by job_id) of a computed session
    to a new session_id. ``merge`` second: fold a set of computed session_ids into
    one canonical session_id.
    """
    # SPLIT: move members out of their computed group into new groups.
    split_map = overrides.get("split") or {}
    if split_map:
        for src_ks, member_map in split_map.items():
            src = groups.get(src_ks)
            if not src:
                continue
            keep = []
            for m in src["members"]:
                target = member_map.get(m.get("job_id", ""))
                if target:
                    g = groups.setdefault(target, {"key": ("manual", target),
                                                    "members": []})
                    g["members"].append(m)
                else:
                    keep.append(m)
            src["members"] = keep

    # MERGE: fold each listed source group into its canonical group.
    merge_map = overrides.get("merge") or {}
    if merge_map:
        for canonical_ks, source_kss in merge_map.items():
            canon = groups.setdefault(canonical_ks,
                                      {"key": ("manual", canonical_ks),
                                       "members": []})
            for src_ks in source_kss:
                if src_ks == canonical_ks:
                    continue
                src = groups.get(src_ks)
                if not src:
                    continue
                canon["members"].extend(src["members"])
                src["members"] = []

    # Drop now-empty groups.
    return {ks: info for ks, info in groups.items() if info["members"]}


# ── Merge / split escape hatch ──────────────────────────────────────────────

def merge_sessions(folder_path, project_id, lane, session_ids):
    """Merge ``session_ids`` into one session (persisted override).

    The FIRST id in ``session_ids`` becomes the canonical session_id; the rest are
    folded into it. Survives via the ``sessions-overrides.json`` sidecar. Returns
    the canonical session record (recomputed), or ``None`` if fewer than two ids.
    """
    if not session_ids or len(session_ids) < 2:
        return None
    canonical = session_ids[0]
    rest = [s for s in session_ids[1:] if s != canonical]
    if not rest:
        return None
    with _paths.WRITE_LOCK:
        overrides = _load_overrides(folder_path, project_id, lane)
        merge_map = overrides.setdefault("merge", {})
        existing = set(merge_map.get(canonical, []))
        existing.update(rest)
        merge_map[canonical] = sorted(existing)
        _save_overrides(folder_path, project_id, lane, overrides)
    for s in list_sessions(folder_path, project_id, lane):
        if s["session_id"] == canonical:
            return s
    return None


def split_session(folder_path, project_id, lane, session_id, grouping):
    """Split one session's members into new sessions (persisted override).

    ``grouping`` maps a member ``job_id`` → the new ``session_id`` it should move
    to. Members not named stay in the original session. Survives via the
    ``sessions-overrides.json`` sidecar. Returns the recomputed list of sessions
    for the lane.
    """
    if not session_id or not grouping:
        return list_sessions(folder_path, project_id, lane)
    with _paths.WRITE_LOCK:
        overrides = _load_overrides(folder_path, project_id, lane)
        split_map = overrides.setdefault("split", {})
        member_map = split_map.setdefault(session_id, {})
        member_map.update({str(k): str(v) for k, v in grouping.items()})
        _save_overrides(folder_path, project_id, lane, overrides)
    return list_sessions(folder_path, project_id, lane)
