"""Machine-local home config root for Shareable installs (W4).

The recipient-chosen home directory becomes the base for projects, skills, and
Anchor data — **without** embedding author host paths in shipped trees.

Config is relative to the chosen home (or uses well-known user-relative
tokens like ``~``). Stdlib only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

HOME_CONFIG_SCHEMA = "share-home-config/v1"
HOME_CONFIG_SCHEMA_VERSION = 1
HOME_CONFIG_FILENAME = "home_config.json"

# Subdir names under the chosen home (no absolute author paths).
PROJECTS_SUBDIR = "projects"
SKILLS_SUBDIR = "skills"
ANCHOR_SUBDIR = "anchor"
GOVERNANCE_SUBDIR = "governance"
JOURNAL_ROOT_SUBDIR = "skill-journals"

DEFAULT_WINDOWS_HOME_RECOMMENDATION = r"C:\dev"


class HomeConfigError(Exception):
    """Raised when home config is invalid or refuses a write."""


def recommend_home_dir(platform: str | None = None) -> str:
    """Plain-English default recommendation (Windows → C:\\dev).

    Returns a **string recommendation**, not a path that embeds the author
    machine. Recipients may override.
    """
    plat = (platform or os.name or "").lower()
    if plat in ("nt", "windows") or (os.name == "nt" and platform is None):
        return DEFAULT_WINDOWS_HOME_RECOMMENDATION
    return str(Path.home() / "dev")


def resolve_home_root(home=None, *, env=None) -> Path:
    """Resolve the machine-local home root.

    Order: explicit ``home`` → env ``ANCHOR_SHARE_HOME`` → ``Path.home()/dev``
    on non-Windows recommendation fallback is not auto-created here.
    """
    if home is not None:
        return Path(home).expanduser().resolve()
    env = env if env is not None else os.environ
    raw = (env.get("ANCHOR_SHARE_HOME") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    # Prefer the Windows recommendation when on Windows; else ~/dev.
    if os.name == "nt":
        return Path(DEFAULT_WINDOWS_HOME_RECOMMENDATION)
    return (Path.home() / "dev").resolve()


def layout_for_home(home=None) -> dict:
    """Return relative + absolute layout paths for a home root.

    Absolute paths are computed from the *recipient* home argument only —
    never from baked-in author paths. Relative keys are what ship in config.
    """
    root = resolve_home_root(home)
    rel = {
        "projects": PROJECTS_SUBDIR,
        "skills": SKILLS_SUBDIR,
        "anchor": ANCHOR_SUBDIR,
        "governance": GOVERNANCE_SUBDIR,
        "skill_journals": JOURNAL_ROOT_SUBDIR,
    }
    abs_paths = {k: str(root / v) for k, v in rel.items()}
    return {
        "home": str(root),
        "relative": rel,
        "absolute": abs_paths,
    }


def build_home_config_doc(home=None, *, extra=None) -> dict:
    """Build a machine-local home config document (no author path literals)."""
    root = resolve_home_root(home)
    layout = layout_for_home(root)
    doc = {
        "schema": HOME_CONFIG_SCHEMA,
        "schema_version": HOME_CONFIG_SCHEMA_VERSION,
        "home_root": str(root),
        "relative_layout": layout["relative"],
        "notes": (
            "Machine-local paths only. Shipped trees must not embed author "
            "host paths; this file is written on the recipient machine at onboard."
        ),
    }
    if extra and isinstance(extra, dict):
        for k, v in extra.items():
            if k not in doc:
                doc[k] = v
    return doc


def validate_home_config_doc(doc) -> list:
    """Return problem list (empty = valid)."""
    if not isinstance(doc, dict):
        return ["home-config-not-an-object"]
    problems = []
    for key in ("schema", "schema_version", "home_root", "relative_layout"):
        if key not in doc:
            problems.append("missing-key:%s" % key)
    if doc.get("schema") != HOME_CONFIG_SCHEMA:
        problems.append("schema-mismatch:%r" % (doc.get("schema"),))
    if doc.get("schema_version") != HOME_CONFIG_SCHEMA_VERSION:
        problems.append(
            "schema_version-mismatch:%r" % (doc.get("schema_version"),)
        )
    layout = doc.get("relative_layout")
    if not isinstance(layout, dict):
        problems.append("relative_layout-not-an-object")
    else:
        for k in (
            "projects", "skills", "anchor", "governance", "skill_journals"
        ):
            if k not in layout:
                problems.append("relative_layout-missing:%s" % k)
            elif not isinstance(layout[k], str) or not layout[k].strip():
                problems.append("relative_layout-empty:%s" % k)
            elif Path(layout[k]).is_absolute():
                problems.append("relative_layout-absolute-forbidden:%s" % k)
    home = doc.get("home_root")
    if isinstance(home, str) and home:
        # Shipped trees must not claim a fixed author path; runtime docs may
        # hold the recipient path. No further check here.
        pass
    return problems


def write_home_config(home=None, *, dest_dir=None, extra=None) -> Path:
    """Write ``home_config.json`` under governance (or ``dest_dir``).

    Returns the written path. Creates parent dirs.
    """
    root = resolve_home_root(home)
    if dest_dir is None:
        dest_dir = root / GOVERNANCE_SUBDIR
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    doc = build_home_config_doc(root, extra=extra)
    problems = validate_home_config_doc(doc)
    if problems:
        raise HomeConfigError("invalid home config: " + ";".join(problems))
    out = dest / HOME_CONFIG_FILENAME
    out.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return out


def ensure_home_layout(home=None) -> dict:
    """Create relative subdirs under the home root; return layout dict."""
    layout = layout_for_home(home)
    root = Path(layout["home"])
    for rel in layout["relative"].values():
        (root / rel).mkdir(parents=True, exist_ok=True)
    return layout
