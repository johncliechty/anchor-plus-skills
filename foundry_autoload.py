"""Skill Foundry v2 — Wave 8: auto-load registration — map.json v2 drives
Anchor's CLICKABLE skill set.

The North Star's clause: every foundry skill is auto-available/clickable
inside Anchor. Wave 8 makes that a REGENERATED projection of the Wave-5
knowledge graph — never a hand-wired list:

* :func:`build_registrations` derives one registration per map.json-v2 skill:
  identity from the map (ref / name / version / status / tier / source),
  runnability from the skill's OWN on-disk Wave-3 manifest (present +
  schema-valid ⇒ ``runnable`` with its declared panel title; absent/broken ⇒
  an honest reason, still listed). Nothing is copied or forked — a
  registration is a POINTER at the canonical skill dir (the single-source
  invariant), and building it executes no skill code.
* :func:`sync_registrations` (the ``foundry.register_autoload`` op body)
  REGENERATES ``registered.json`` under the Anchor data dir from the map
  alone — a skill added to the map appears, a skill dropped from the map
  disappears; an invalid map refuses without touching the registry.
* :func:`clickable_skills` is the READ side the GUI waves (9-10) render:
  Anchor's clickable set IS this projection, nothing else.

Stdlib only (Anchor's no-dep rule) + the product seams ``paths`` /
``foundry_decisions`` / ``foundry_map`` / ``foundry_map_gates`` /
``skill_runner``.
"""

import json
import os
from pathlib import Path

import paths as _paths
import foundry_decisions as _fd
import foundry_map as _fm
import foundry_map_gates as _fg
import skill_runner as _sr


# ── Constants ────────────────────────────────────────────────────────────────

AUTOLOAD_SCHEMA_ID = "foundry-autoload/v1"
AUTOLOAD_DIRNAME = "foundry_autoload"
REGISTRY_FILENAME = "registered.json"

#: Wave-1 anti-drift convention.
TRACES_TO_NORTH_STAR = (_fd.NS_GUI_DRIVES_REAL_MACHINERY,
                        _fd.NS_KNOWLEDGE_GRAPH)


def autoload_home() -> Path:
    """The skill-registration state home (under the data dir, never the repo
    — the DR-01 write scope for ``foundry.register_autoload``)."""
    home = _paths.data_dir() / AUTOLOAD_DIRNAME
    home.mkdir(parents=True, exist_ok=True)
    return home


def registry_path(home=None) -> Path:
    return (Path(home) if home else autoload_home()) / REGISTRY_FILENAME


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


# ── Build (pure projection of the map) ───────────────────────────────────────

def build_registrations(map_doc, *, root=None):
    """map.json v2 → the registration list — ``(registrations, problems)``.

    An invalid map yields ``(None, problems)`` — an invalid graph is never
    projected (the Wave-6 consumption discipline). Each registration is a
    SAFE pointer: map identity + on-disk manifest facts, no skill code run."""
    problems = _fm.validate_map(map_doc)
    if problems:
        return None, problems
    base = _fg._foundry_root(root)
    regs = []
    for skill in sorted(map_doc["skills"], key=lambda s: str(s.get("ref"))):
        d = _fg._source_dir(skill.get("source") or "", base)
        entry = {
            "ref": skill["ref"],
            "name": skill["name"],
            "version": skill["version"],
            "status": skill["status"],
            "tier": skill["tier"],
            "source": str(skill["source"]),
            "clickable": True,
            "runnable": False,
            "manifest_path": None,
            "panel": {"title": str(skill["name"]).replace("-", " ").title()},
            "reason": None,
        }
        mf = d / _sr.MANIFEST_FILENAME
        if not d.is_dir():
            entry["reason"] = "source-dir-missing"
        elif not mf.is_file():
            entry["reason"] = "manifest-missing"
        else:
            try:
                manifest = _sr.load_skill_manifest(d)
            except ValueError:
                manifest = None
                entry["reason"] = "manifest-unparseable"
            if manifest is not None:
                errs = _sr.validate_manifest(manifest)
                if errs:
                    entry["reason"] = ("manifest-invalid:"
                                       + "; ".join(errs))[:200]
                else:
                    entry["runnable"] = True
                    entry["manifest_path"] = mf.as_posix()
                    title = (manifest.get("panel") or {}).get("title")
                    if isinstance(title, str) and title.strip():
                        entry["panel"] = {"title": title}
        regs.append(entry)
    return regs, []


# ── Sync (the op body) + the read side ───────────────────────────────────────

def sync_registrations(map_doc=None, *, map_path=None, home=None,
                       root=None) -> dict:
    """REGENERATE the registry from the map — the ``register_autoload`` body.

    The whole file is rebuilt from map.json v2 each run (never merged, never
    hand-edited), so the clickable set can only ever say what the graph
    says. An unreadable or invalid map refuses WITHOUT touching the
    registry."""
    if map_doc is None:
        try:
            map_doc = _fm.load_map(map_path)
        except (OSError, ValueError) as exc:
            return {"ok": False, "reason": "map-unreadable:%s" % exc}
    regs, problems = build_registrations(map_doc, root=root)
    if problems:
        return {"ok": False,
                "reason": "map-invalid:" + "; ".join(problems)[:300]}
    target = registry_path(home)
    target.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": AUTOLOAD_SCHEMA_ID,
        "generated_from": {"schema": _fm.MAP_SCHEMA_ID,
                           "map_version": _fm.MAP_VERSION,
                           "skill_count": len(regs)},
        "skills": regs,
    }
    _atomic_write(target, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    return {"ok": True, "count": len(regs),
            "registered": [r["name"] for r in regs],
            "runnable": [r["name"] for r in regs if r["runnable"]],
            "path": target.as_posix()}


def clickable_skills(home=None) -> list:
    """The READ side: Anchor's clickable set (``[]`` before any sync).

    A present-but-unparseable registry raises ``ValueError`` loudly — a
    corrupted registration state must break its reader, never render as an
    honest-looking empty set."""
    p = registry_path(home)
    if not p.is_file():
        return []
    doc = json.loads(p.read_text(encoding="utf-8"))
    skills = doc.get("skills") if isinstance(doc, dict) else None
    return list(skills) if isinstance(skills, list) else []


def is_clickable(name, home=None) -> bool:
    """True iff ``name`` (a skill name or its stable ref) is registered."""
    n = str(name)
    return any(r.get("name") == n or r.get("ref") == n
               for r in clickable_skills(home) if isinstance(r, dict))
