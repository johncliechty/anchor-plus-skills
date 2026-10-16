"""Skills immutability seal for Shareable installs (W4).

Post-onboard checksum/manifest of the vendored skill tree. Local edits yield a
**degraded forked** status and **block feedback export** until re-vendor.

Does not claim Foundry sleep is live. Stdlib only.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

SEAL_SCHEMA = "share-skill-seal/v1"
SEAL_SCHEMA_VERSION = 1
SEAL_FILENAME = "SKILLS-SEAL.json"

# Skip noise while hashing skill trees.
_SKIP_DIR_NAMES = {
    ".git", "__pycache__", ".pytest_cache", "node_modules", ".anchor",
    "side",  # droppable journal side-channel
}
_SKIP_FILE_SUFFIXES = (".pyc", ".pyo", ".tmp")
_SKIP_FILE_NAMES = {SEAL_FILENAME, ".DS_Store"}


class SkillSealError(Exception):
    """Raised when seal build/verify refuses."""


def _iter_skill_files(skills_root: Path):
    root = Path(skills_root)
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        # prune in-place
        dirnames[:] = [
            d for d in sorted(dirnames)
            if d not in _SKIP_DIR_NAMES and not d.startswith(".")
        ]
        for name in sorted(filenames):
            if name in _SKIP_FILE_NAMES:
                continue
            if name.startswith("."):
                continue
            if any(name.endswith(suf) for suf in _SKIP_FILE_SUFFIXES):
                continue
            full = Path(dirpath) / name
            try:
                rel = full.relative_to(root).as_posix()
            except ValueError:
                continue
            yield rel, full


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def build_seal_manifest(skills_root, *, seal_id: str | None = None) -> dict:
    """Build a seal manifest over ``skills_root`` (checksum of each file)."""
    root = Path(skills_root)
    if not root.is_dir():
        raise SkillSealError("skills-root-missing:%s" % root)
    files = {}
    for rel, full in _iter_skill_files(root):
        try:
            files[rel] = _file_sha256(full)
        except OSError as exc:
            raise SkillSealError("hash-failed:%s:%s" % (rel, exc)) from exc
    # Stable aggregate fingerprint.
    agg = hashlib.sha256()
    for rel in sorted(files):
        agg.update(rel.encode("utf-8"))
        agg.update(b"\0")
        agg.update(files[rel].encode("ascii"))
        agg.update(b"\n")
    return {
        "schema": SEAL_SCHEMA,
        "schema_version": SEAL_SCHEMA_VERSION,
        "seal_id": seal_id or ("seal-" + agg.hexdigest()[:12]),
        "skills_root_name": root.name,
        "file_count": len(files),
        "aggregate_sha256": agg.hexdigest(),
        "files": files,
    }


def write_seal(skills_root, manifest=None, *, dest=None) -> Path:
    """Write seal manifest next to (or under) the skills root.

    Default path: ``<skills_root>/../SKILLS-SEAL.json`` if skills_root is a
    ``skills`` folder, else ``<skills_root>/SKILLS-SEAL.json``.
    """
    root = Path(skills_root)
    if manifest is None:
        manifest = build_seal_manifest(root)
    if dest is None:
        dest = root / SEAL_FILENAME
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return dest


def load_seal(path) -> dict:
    raw = Path(path).read_text(encoding="utf-8")
    doc = json.loads(raw)
    if not isinstance(doc, dict):
        raise SkillSealError("seal-not-an-object")
    return doc


def verify_seal(skills_root, manifest=None, *, seal_path=None) -> dict:
    """Compare live tree to a stored/provided manifest.

    Returns a result dict::

        {
          "ok": bool,
          "status": "sealed" | "forked" | "missing_seal" | "missing_root",
          "reason_codes": [...],  # may include skill_tree_forked
          "changed": [rel, ...],
          "added": [...],
          "removed": [...],
        }
    """
    root = Path(skills_root)
    if not root.is_dir():
        return {
            "ok": False,
            "status": "missing_root",
            "reason_codes": ["skill_tree_forked"],
            "changed": [],
            "added": [],
            "removed": [],
        }
    if manifest is None:
        path = Path(seal_path) if seal_path else (root / SEAL_FILENAME)
        if not path.is_file():
            return {
                "ok": False,
                "status": "missing_seal",
                "reason_codes": ["skill_tree_forked"],
                "changed": [],
                "added": [],
                "removed": [],
            }
        manifest = load_seal(path)

    live = build_seal_manifest(root)
    expected = manifest.get("files") or {}
    if not isinstance(expected, dict):
        expected = {}
    live_files = live.get("files") or {}

    expected_set = set(expected)
    live_set = set(live_files)
    added = sorted(live_set - expected_set)
    removed = sorted(expected_set - live_set)
    changed = sorted(
        rel for rel in (expected_set & live_set)
        if expected.get(rel) != live_files.get(rel)
    )

    if added or removed or changed:
        return {
            "ok": False,
            "status": "forked",
            "reason_codes": ["skill_tree_forked"],
            "changed": changed,
            "added": added,
            "removed": removed,
        }
    return {
        "ok": True,
        "status": "sealed",
        "reason_codes": [],
        "changed": [],
        "added": [],
        "removed": [],
    }


def is_forked(skills_root, manifest=None, *, seal_path=None) -> bool:
    """True when the tree fails the immutability seal (local edits)."""
    result = verify_seal(
        skills_root, manifest=manifest, seal_path=seal_path
    )
    return not result.get("ok")


def feedback_export_allowed(skills_root, manifest=None, *, seal_path=None) -> bool:
    """False when forked — block feedback export until re-vendor."""
    return not is_forked(skills_root, manifest=manifest, seal_path=seal_path)


def seal_status_for_readiness(
    skills_root, manifest=None, *, seal_path=None
) -> list:
    """Return readiness reason codes from seal verification (0 or 1 codes)."""
    result = verify_seal(
        skills_root, manifest=manifest, seal_path=seal_path
    )
    return list(result.get("reason_codes") or [])
