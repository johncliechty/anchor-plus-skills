import json
import logging
import os
from pathlib import Path
import hashlib
import sys

_logger = logging.getLogger("foundry_integrity")

MANIFEST_FILENAME = "skill_manifest.json"

def get_manifest_path(root_dir=None):
    from paths import CODE_DIR as ANCHOR_DIR
    root = Path(root_dir) if root_dir else ANCHOR_DIR
    return root / MANIFEST_FILENAME

def sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None

def sha256_text(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()

def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))

def _get_skill_files(skill_dir: Path):
    """Yield all tracked files for a skill, avoiding history dirs."""
    for p in skill_dir.rglob("*"):
        if p.is_file() and "north-star-history" not in p.parts:
            yield p

def build_manifest(skills_root: Path):
    """Build the full manifest dict for all skills.

    Only skills that contribute at least one hashed file are included, so an
    empty ``{}`` means "nothing to ship" (truthy empty skill shells are not
    written into skill_manifest.json).
    """
    manifest = {}
    if not skills_root.exists():
        return manifest
    for skill_dir in skills_root.iterdir():
        if not skill_dir.is_dir():
            continue
        # Skip provenance-only / non-skill dirs under the bundle root.
        if skill_dir.name.startswith(".") or skill_dir.name in ("__pycache__",):
            continue
        skill_files = {}
        for f in _get_skill_files(skill_dir):
            # Do not hash the integrity manifest itself (would self-mutate).
            if f.name == MANIFEST_FILENAME:
                continue
            rel = f.relative_to(skill_dir).as_posix()
            digest = sha256_file(f)
            if digest:
                skill_files[rel] = digest
        if skill_files:
            manifest[skill_dir.name] = skill_files
    return manifest

def verify_at_boot(anchor_dir=None):
    from paths import CODE_DIR as ANCHOR_DIR
    import foundry_ops
    anchor_dir = Path(anchor_dir) if anchor_dir else ANCHOR_DIR
    manifest_path = get_manifest_path(anchor_dir)
    if not manifest_path.exists():
        return
        
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        _logger.error("Failed to parse skill_manifest.json")
        sys.exit(1)
        
    skills_root = foundry_ops._default_skills_root()
    
    # Check for skills on disk not in manifest
    if skills_root.exists():
        for skill_dir in skills_root.iterdir():
            if skill_dir.is_dir() and skill_dir.name not in manifest:
                _logger.error("Skill integrity drift detected! Skill %s has no manifest entry.", skill_dir.name)
                sys.exit(1)
                
    # Check each skill in the manifest
    for skill, files in manifest.items():
        skill_dir = skills_root / skill
        if not skill_dir.exists():
            _logger.error("Skill integrity drift detected! Skill %s is missing.", skill)
            sys.exit(1)
            
        # Verify hashes
        for rel, expected_hash in files.items():
            f = skill_dir / rel
            if not f.exists():
                _logger.error("Skill integrity drift detected! File %s is missing. Please use the sanctioned foundry path (e.g. foundry.edit_north_star) for edits.", f)
                sys.exit(1)
            actual_hash = sha256_file(f)
            if actual_hash != expected_hash:
                _logger.error("Skill integrity drift detected! File %s was edited outside the foundry path. Please use the sanctioned foundry path (e.g. foundry.edit_north_star) for edits.", f)
                sys.exit(1)

def update_manifest_entry(skill: str, rel_path: str, new_text: str, anchor_dir=None):
    """Update a specific file's hash in the manifest. Called by foundry_ops."""
    manifest_path = get_manifest_path(anchor_dir)
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return
        
    if skill not in manifest:
        manifest[skill] = {}
        
    manifest[skill][rel_path] = sha256_text(new_text)
    _atomic_write(manifest_path, json.dumps(manifest, indent=2) + "\n")

def register_skill(skill: str, anchor_dir=None):
    """Add a newly scaffolded skill to the manifest."""
    manifest_path = get_manifest_path(anchor_dir)
    if not manifest_path.exists():
        return
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception:
        return
        
    from paths import CODE_DIR as ANCHOR_DIR
    import foundry_ops
    skills_root = foundry_ops._default_skills_root()
    skill_dir = skills_root / skill
    if not skill_dir.exists():
        return
        
    manifest[skill] = {}
    for f in _get_skill_files(skill_dir):
        rel = f.relative_to(skill_dir).as_posix()
        manifest[skill][rel] = sha256_file(f)
        
    _atomic_write(manifest_path, json.dumps(manifest, indent=2) + "\n")
