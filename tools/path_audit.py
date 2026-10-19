#!/usr/bin/env python3
"""W11 (C6) — data-dir migration path audit + rewrite (stdlib only).

When the live Anchor data dir is relocated OUT of the repo (``ANCHOR_DATA_DIR``
set to a folder outside ``C:\\dev\\Anchor``), every durable store that recorded a
**repo-rooted absolute path** while the data dir *was* the code dir now points at
the OLD location. Those stale absolutes must be rewritten to the new root or the
service silently loses track of worktrees / job logs / project folders after the
move.

This module is the audit + rewrite keystone of the scripted migration unit:

* :func:`audit_data_dir` — scan every durable store under a data-dir ``root``
  (``rnd_registry.json``, ``.anchor/sessions.json``, ``rnd_jobs/*.json``, the
  per-project ``.anchor/projects/*/discovery.json`` and per-project job records)
  for string values that are absolute paths at/under ``old_root``, and emit a
  **rewrite map**: ``{store_rel: [{pointer, old, new}, ...]}`` — a pure,
  side-effect-free report (writes nothing);
* :func:`apply_rewrites` — apply that rewrite map in place, atomically and under
  ``paths.WRITE_LOCK`` (tmp-write + ``os.replace``), returning what changed;
* :func:`remaining_repo_rooted` — the post-migration verification predicate: zero
  values still under ``old_root`` (used by the migration unit's verify step).

The path match is separator- and case-normalized (Windows paths are stored with
backslashes and are case-insensitive), but the REWRITTEN value preserves the
original tail casing and only swaps the root prefix — no path is ever lowercased.

Stdlib only. Never spawns a process, never reads the environment, never touches
the live ``:8777`` service.
"""

import json
import os
from pathlib import Path

import paths as _paths

#: The durable stores an audit walks, as globs relative to the data-dir root.
#: Order is deterministic so the emitted rewrite map is stable/diffable.
STORE_GLOBS = (
    "rnd_registry.json",
    ".anchor/sessions.json",
    "rnd_jobs/*.json",
    ".anchor/projects/*/discovery.json",
    ".anchor/projects/*/jobs/*.json",
    ".anchor/projects/*/**/jobs/*.json",
)

_WIN = os.name == "nt"

#: The data subtrees that ACTUALLY relocate when ``ANCHOR_DATA_DIR`` moves (the
#: migration copies these into the new root). A stored absolute path is only
#: SAFELY auto-rewritten when its tail falls inside one of these — because a
#: project's ``folder_path`` (its own git repo) and any planning-doc path live in
#: the project's tree, which stays put; only the runtime stores move. The audit
#: still REPORTS every repo-rooted path (``segments=None``) for human review; the
#: migration's apply/verify use this safe subset.
RELOCATED_SEGMENTS = (".anchor", "rnd_jobs", "logs", "health_reports",
                      "domains", "rnd_registry.json")


def _unify(sep_path: str) -> str:
    """Normalize path separators to ``os.sep`` (compare/slice domain)."""
    return str(sep_path).replace("/", os.sep).replace("\\", os.sep)


def _cmp(sep_unified: str) -> str:
    """Case-fold ONLY on Windows (paths there are case-insensitive)."""
    return sep_unified.casefold() if _WIN else sep_unified


def rewrite_string(value, old_root, new_root, segments=None):
    """Rewrite one string IF it is an absolute path at/under ``old_root``.

    Returns the rewritten string, or ``None`` when ``value`` is not a string, is
    not rooted under ``old_root``, or (when ``segments`` is given) does not fall
    inside one of the relocated data subtrees (so ``folder_path`` pointing at a
    project's own repo is left untouched by a data-dir move). The root prefix is
    swapped; the tail (including its casing) is preserved verbatim.
    """
    if not isinstance(value, str) or not value:
        return None
    v = _unify(value).rstrip("\\/")
    o = _unify(old_root).rstrip("\\/")
    n = _unify(new_root).rstrip("\\/")
    if not o:
        return None
    vc, oc = _cmp(v), _cmp(o)
    if vc == oc:
        tail = ""
    elif vc.startswith(oc + os.sep):
        tail = v[len(o):]          # from the sep-unified original: leading sep + tail
    else:
        return None
    if segments is not None:
        first = tail.lstrip("\\/").split(os.sep, 1)[0] if tail else ""
        if first not in segments:
            return None            # a kept path (repo root / project tree) — skip
    return n + tail


def _walk(obj, old_root, new_root, pointer="", changes=None, segments=None):
    """Recursively rewrite path strings; collect changes as a flat list.

    Returns ``(new_obj, changes)`` where ``changes`` is a list of
    ``{"pointer", "old", "new"}`` (JSON-pointer-ish path into the structure).
    The structure is rebuilt (never mutated in place) so an audit-only call can
    discard the result and keep the source object pristine.
    """
    if changes is None:
        changes = []
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            out[k] = _walk(v, old_root, new_root, f"{pointer}/{k}", changes,
                           segments)[0]
        return out, changes
    if isinstance(obj, list):
        out = []
        for i, v in enumerate(obj):
            out.append(_walk(v, old_root, new_root, f"{pointer}/{i}", changes,
                             segments)[0])
        return out, changes
    if isinstance(obj, str):
        new = rewrite_string(obj, old_root, new_root, segments)
        if new is not None and new != obj:
            changes.append({"pointer": pointer or "/", "old": obj, "new": new})
            return new, changes
    return obj, changes


def _iter_store_files(root: Path):
    """Yield the existing store files under ``root`` (deduped, deterministic)."""
    seen = set()
    for glob in STORE_GLOBS:
        for p in sorted(root.glob(glob)):
            if p.is_file():
                rp = p.resolve()
                if rp not in seen:
                    seen.add(rp)
                    yield p


def _load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def audit_data_dir(root, old_root, new_root, segments=None):
    """Scan every durable store under ``root`` for repo-rooted absolute paths.

    Returns a **rewrite map** keyed by the store's path RELATIVE to ``root``
    (posix separators for stable diffs)::

        {".anchor/sessions.json": [{"pointer": "/0/worktree_path",
                                     "old": "C:\\dev\\Anchor\\.anchor\\...",
                                     "new": "D:\\anchor-data\\.anchor\\..."}],
         "rnd_jobs/ab12.json": [...], ...}

    ``segments=None`` (the default) reports EVERY repo-rooted path for review;
    pass :data:`RELOCATED_SEGMENTS` to restrict to the safely-relocatable subset.
    Only stores with at least one change appear. Pure — writes nothing.
    """
    root = Path(root).resolve()
    rewrite_map = {}
    for path in _iter_store_files(root):
        obj = _load_json(path)
        if obj is None:
            continue
        _new, changes = _walk(obj, old_root, new_root, segments=segments)
        if changes:
            rel = path.resolve().relative_to(root).as_posix()
            rewrite_map[rel] = changes
    return rewrite_map


def audit_change_count(rewrite_map) -> int:
    """Total number of individual path rewrites across all stores."""
    return sum(len(v) for v in rewrite_map.values())


def apply_rewrites(root, old_root, new_root, segments=RELOCATED_SEGMENTS):
    """Rewrite every relocated-data absolute path under ``root`` in place.

    Atomic per store (tmp-write + ``os.replace``) under ``paths.WRITE_LOCK`` so a
    concurrent read never sees a torn file. Returns a report::

        {"stores": {rel: n_changes, ...}, "total": int, "map": <rewrite_map>}

    Defaults to the SAFE :data:`RELOCATED_SEGMENTS` subset (never touches a
    ``folder_path`` pointing at a project's own repo). Idempotent: a second run
    finds nothing to change. Never raises for a corrupt/missing store — skipped.
    """
    root = Path(root).resolve()
    rewrite_map = audit_data_dir(root, old_root, new_root, segments=segments)
    report = {"stores": {}, "total": 0, "map": rewrite_map}
    if not rewrite_map:
        return report
    with _paths.WRITE_LOCK:
        for rel, changes in rewrite_map.items():
            path = root / rel
            obj = _load_json(path)
            if obj is None:
                continue
            new_obj, applied = _walk(obj, old_root, new_root, segments=segments)
            if not applied:
                continue
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(
                json.dumps(new_obj, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            os.replace(str(tmp), str(path))
            report["stores"][rel] = len(applied)
            report["total"] += len(applied)
    return report


def remaining_repo_rooted(root, old_root, segments=RELOCATED_SEGMENTS):
    """Post-migration verification: relocated values still under ``old_root``.

    Returns the same rewrite-map shape as :func:`audit_data_dir` but reporting
    only that a value is STILL under the old root. Restricted to
    :data:`RELOCATED_SEGMENTS` by default (a kept ``folder_path`` == repo root is
    NOT a failure). Empty ⇒ the rewrite pass is complete. Pure — writes nothing.
    """
    # Rewrite against a sentinel new root that can never equal old_root, so any
    # value still under old_root produces a (spurious) change we can count.
    sentinel = str(old_root).rstrip("\\/") + "__MOVED__"
    stale = audit_data_dir(root, old_root, sentinel, segments=segments)
    return {rel: [{"pointer": c["pointer"], "old": c["old"]} for c in changes]
            for rel, changes in stale.items()}


if __name__ == "__main__":  # pragma: no cover - operator convenience
    import argparse

    ap = argparse.ArgumentParser(
        description="Audit/rewrite repo-rooted absolute paths in Anchor stores")
    ap.add_argument("root", help="the data-dir root to scan")
    ap.add_argument("old_root", help="the OLD (pre-move) absolute root prefix")
    ap.add_argument("new_root", help="the NEW absolute root prefix")
    ap.add_argument("--apply", action="store_true",
                    help="apply the rewrites (default: audit/report only)")
    args = ap.parse_args()
    if args.apply:
        rep = apply_rewrites(args.root, args.old_root, args.new_root)
        print(json.dumps({"applied": rep["total"], "stores": rep["stores"]},
                         indent=2))
    else:
        rm = audit_data_dir(args.root, args.old_root, args.new_root)
        print(json.dumps({"would_rewrite": audit_change_count(rm),
                          "stores": {k: len(v) for k, v in rm.items()}},
                         indent=2))
