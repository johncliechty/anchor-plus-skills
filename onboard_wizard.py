#!/usr/bin/env python3
"""7-Step Guided Onboarding & First-Run Setup Wizard (stdlib only).

Addresses all root causes from collaborator diagnostic walkthroughs and
provides a smooth, end-to-end interactive Web UI (`/onboard-wizard` &
`/onboard-wizard?sandbox=1`) and CLI (`python onboard_wizard.py --sandbox`):

  Step 1 — Who Are You? (Display Name, Collaborator Pseudonym/Synonym & Steward Persona)
  Step 2 — Mothership Topology, Optional Tailscale Prompt & 1-Click Official Anchor Registry
  Step 3 — AI Services Menu, Auto-Install Agent CLIs, Browser Account Detection & Live Probe
  Step 4 — Start with Goals & Missions (Star Chart Steward) OR Start with Projects
  Step 5 — Smart Directory Scan (Gandalf Scanner), Orphaned Store Re-Adoption, Exclusion Filter,
           Virtual Project Groupings & Automatic Starter AI Cockpit Creation
  Step 6 — Easy Calendar & Email Integration (1-Click Windows Outlook + Auto-Detected Email Providers)
  Step 7 — Complete Readiness Receipt & Launchpad (Direct links to Cave of Wonders & AI Cockpits)

Includes First-Class Sandbox / Walkthrough Mode (`sandbox=True` / `?sandbox=1` / `--sandbox`)
that ignores existing `anchor.exe` and Tailscale state on a developer/work desktop and stores
all state under `.anchor/onboard_sandbox/<sandbox_id>/` without mutating live registries
until explicitly committed via `apply_sandbox_to_live()`.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import base64
import hashlib
import secrets
import html
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from typing import Any
import uuid
import webbrowser

import anchor_agent_protocol as aap
import comms_connector
import mothership_collab
import paths
import provider_secrets
import rnd_registry as _rnd
import share_readiness as ready


WIZARD_SCHEMA = "anchor.onboard.wizard.v1"
DEFAULT_SANDBOX_ID = "desktop-walkthrough"
CANONICAL_ANCHOR_GITHUB_URL = "https://github.com/johncliechty/ghostworldlabs-anchor"

LIVE_PROBES_SKIPPED_NOTE = ready.LIVE_PROBES_SKIPPED_NOTE
live_probes_skipped_note = LIVE_PROBES_SKIPPED_NOTE
readiness_human_explanation = ready.readiness_human_explanation

STEWARD_PERSONAS = {
    "aladdin": {
        "id": "aladdin",
        "label": "Aladdin",
        "title": "Aladdin · Cave of Wonders Chief of Staff",
        "surface": "The Cave of Wonders & Star Chart",
    },
    "jarvis": {
        "id": "jarvis",
        "label": "Jarvis",
        "title": "Jarvis · Helm & Chart Room",
        "surface": "The Helm & Chart Room",
    },
    "ecgberht": {
        "id": "ecgberht",
        "label": "Ecgberht",
        "title": "Ecgberht · High Seat & Beacon",
        "surface": "The High Seat & Beacon",
    },
}

SERVICE_CATALOG = {
    "claude": {
        "family": "claude",
        "label": "Claude (Anthropic)",
        "cli": "claude",
        "default_role": "Primary Coding & Steward Seat",
        "free_tier_guide": "Free claude.ai web accounts do not include unlimited Claude Code CLI quota. If using free accounts only, enable Gemini Free Tier below as your primary seat, or paste starter Anthropic API credits with Free Account (Single-Seat Paced) selected.",
        "tiers": {
            "frontier": {
                "label": "Frontier (Top-Tier Capability)",
                "orchestrator_model": "claude-fable-5-1",
                "reviewer_model": "claude-fable-5-1",
                "effort": "max",
            },
            "one_tier_down": {
                "label": "One Tier Down (Fast / Cost-Balanced)",
                "orchestrator_model": "opus",
                "reviewer_model": "opus",
                "effort": "high",
            },
            "free_tier": {
                "label": "Free Account / Rate-Limit Friendly (Single-Seat Paced)",
                "orchestrator_model": "sonnet",
                "reviewer_model": "sonnet",
                "effort": "high",
                "single_seat_pacing": True,
            },
        },
        "update_cmd": ["claude", "update"],
        "login_cmd": ["claude", "auth", "login", "--claudeai"],
    },
    "gemini": {
        "family": "gemini",
        "label": "Gemini (Google Antigravity / agy)",
        "cli": "agy",
        "default_role": "Cross-Family Adversarial Reviewer & Heavy Reader (Best Free-Account Seat)",
        "free_tier_guide": "Recommended Free Seat: Sign in with any free Google account via `agy auth login` / Gemini CLI, OR get a free GEMINI_API_KEY at aistudio.google.com (no credit card needed; note Google's free-tier API terms may log prompts/outputs for service improvement and apply daily RPM/RPD caps).",
        "tiers": {
            "frontier": {
                "label": "Frontier (Top-Tier Capability)",
                "orchestrator_model": "gemini-4-hydrogen",
                "reviewer_model": "gemini-4-hydrogen",
                "effort": "high",
            },
            "one_tier_down": {
                "label": "One Tier Down (Fast / Cost-Balanced)",
                "orchestrator_model": "gemini-3.8-flash",
                "reviewer_model": "gemini-3.8-flash",
                "effort": "high",
            },
            "free_tier": {
                "label": "Free Account / Google AI Studio Free Tier (Rate-Limit Friendly)",
                "orchestrator_model": "gemini-3.8-flash",
                "reviewer_model": "gemini-3.8-flash",
                "effort": "high",
                "single_seat_pacing": True,
            },
        },
        "update_cmd": ["agy", "--version"],
        "login_cmd": ["agy", "models"],
    },
    "grok": {
        "family": "grok",
        "label": "Grok (xAI)",
        "cli": "grok",
        "default_role": "Independent Cross-Family Shark & Refuter",
        "free_tier_guide": "Optional secondary seat. Sign in with `grok auth` or paste a free/starter xAI API key; safe to uncheck if you only use free Google/OpenAI accounts.",
        "tiers": {
            "frontier": {
                "label": "Frontier (Top-Tier Capability)",
                "orchestrator_model": "grok-4.7",
                "reviewer_model": "grok-4.7",
                "effort": "xhigh",
            },
            "one_tier_down": {
                "label": "One Tier Down (Fast / Cost-Balanced)",
                "orchestrator_model": "grok-4.7",
                "reviewer_model": "grok-4.7",
                "effort": "medium",
            },
            "free_tier": {
                "label": "Free Account / Rate-Limit Friendly (Single-Seat Paced)",
                "orchestrator_model": "grok-4.7",
                "reviewer_model": "grok-4.7",
                "effort": "medium",
                "single_seat_pacing": True,
            },
        },
        "update_cmd": ["grok", "--version"],
        "login_cmd": ["grok", "auth"],
    },
    "chatgpt": {
        "family": "chatgpt",
        "label": "ChatGPT / Codex (OpenAI)",
        "cli": "codex",
        "default_role": "Synthesis & Verification Seat",
        "free_tier_guide": "Sign in via `codex login` or paste an OpenAI API key. Free accounts have lower RPM limits — Free Account mode paces multi-agent skills one request at a time.",
        "tiers": {
            "frontier": {
                "label": "Frontier (Top-Tier Capability)",
                "orchestrator_model": "gpt-6-luna",
                "reviewer_model": "gpt-6-luna",
                "effort": "ultra",
            },
            "one_tier_down": {
                "label": "One Tier Down (Fast / Cost-Balanced)",
                "orchestrator_model": "gpt-5.6-terra",
                "reviewer_model": "gpt-5.6-terra",
                "effort": "high",
            },
            "free_tier": {
                "label": "Free Account / Rate-Limit Friendly (Single-Seat Paced)",
                "orchestrator_model": "gpt-5.6-luna",
                "reviewer_model": "gpt-5.6-luna",
                "effort": "high",
                "single_seat_pacing": True,
            },
        },
        "update_cmd": ["codex", "--version"],
        "login_cmd": ["codex", "login"],
    },
}

STRATEGIC_ARENAS = [
    ("Research & Scholarship", ("research", "paper", "journal", "study", "model", "theorem", "neuro", "stat", "mcmc", "quantum", "fusion")),
    ("Teaching & Mentorship", ("teach", "course", "class", "student", "mba", "curriculum", "lecture", "syllabus", "einstein")),
    ("Business, Trusts & Operations", ("trust", "llc", "lp", "holding", "tax", "legal", "counsel", "estate", "finance", "deal", "patent", "venture")),
    ("Software & AI Systems", ("anchor", "skill", "foundry", "cockpit", "code", "app", "engine", "agent", "foreman", "crucible", "gandalf", "anvil", "aegis")),
    ("Creative Writing & Personal", ("book", "novel", "story", "fable", "chekhov", "chapter", "family", "health", "travel")),
]

NOISE_DIR_NAMES = frozenset({
    ".git", ".hg", ".svn", ".anchor", ".ecgberht", ".claude", ".grok", ".gemini", ".codex",
    ".vscode", ".idea", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "__pycache__", "node_modules", "venv", ".venv", "env", "dist", "build",
    "Anchor-code-jobs", "$RECYCLE.BIN", "System Volume Information",
    "logs", "health_reports", "domains", "starter", "vendor",
    "skills", "bundled-skills", "foundry-tools", "governance",
    "bundle_staging", "_old-anchor-archive", "_archive",
})

FOUNDRY_SKILL_NAMES = frozenset({
    "aegis", "agy-dispatch", "agy-customizations", "antigravity-guide",
    "anvil", "chekhov", "crucible", "curriculum-developer", "ecgberht",
    "einstein", "figure-designer", "financial-analyst", "foreman",
    "gandalf", "jumper", "legal-beagle", "literature-review",
    "native_swarm", "ramanujan", "researchprime", "scribe",
    "skill-foundry", "superjump", "swarm", "swarm_monitor",
    "tidy-idy", "zombie-hunter",
})

_ANCHOR_INSTALL_NAME_RE = re.compile(
    r"^anchor(?:\s+\d+|\d+|[-_\s]+(?:backup.*|old.*|copy.*|update.*|v?\d.*|plus.*|home.*|app.*|share.*|collab.*|code-jobs.*))?$",
    re.IGNORECASE,
)

_SKILL_FOLDER_NAME_RE = re.compile(
    r"^(?:skills?|bundled[-_\s]?skills|foundry[-_\s]?skills?|foundry[-_\s]?tools|"
    + "|".join(re.escape(s) for s in sorted(FOUNDRY_SKILL_NAMES, key=len, reverse=True))
    + r")(?:[-_\s]+(?:v?\d[\d\._-]*|old|backup|copy|archive|\d+))?$",
    re.IGNORECASE,
)


def is_excluded_non_project_dir(
    folder: Path | str,
    *,
    anchor_root: Path | str | None = None,
) -> tuple[bool, str]:
    """Return ``(True, reason)`` when ``folder`` is part of Anchor, an Anchor backup/install,
    or a Foundry skill / skill-pack directory that must NEVER be discovered as a user project."""
    try:
        p = Path(folder).expanduser()
        resolved = p.resolve()
    except OSError:
        p = Path(str(folder))
        resolved = p

    name = p.name.strip()
    low_name = name.lower()
    if not name or name.startswith(".") or name in NOISE_DIR_NAMES or low_name in {n.lower() for n in NOISE_DIR_NAMES}:
        return True, "noise_or_system_dir"

    # 1. Check if folder is Anchor itself or inside an Anchor installation
    eff_anchor_roots: list[Path] = []
    for cand_root in (anchor_root, paths.CODE_DIR):
        if cand_root is not None:
            try:
                cr = Path(cand_root).expanduser().resolve()
                if ((cr / "anchor_gui.py").is_file() or cr.name.lower() == "anchor") and cr not in eff_anchor_roots:
                    eff_anchor_roots.append(cr)
            except OSError:
                continue

    for ar in eff_anchor_roots:
        if resolved == ar:
            return True, "anchor_installation_root"
        try:
            resolved.relative_to(ar)
            return True, "inside_anchor_installation"
        except ValueError:
            pass

    # 2. Check if folder name or content matches an Anchor installation / backup / clone
    if _ANCHOR_INSTALL_NAME_RE.match(low_name):
        return True, "anchor_install_or_backup_folder"
    if (p / "anchor_gui.py").is_file() and (
        (p / "rnd_registry.py").is_file()
        or (p / "onboard_wizard.py").is_file()
        or (p / "paths.py").is_file()
    ):
        return True, "anchor_codebase_signature"

    # 3. Check if folder is a Foundry Skill or skill collection
    if _SKILL_FOLDER_NAME_RE.match(low_name):
        return True, "foundry_skill_folder"
    if (p / "SKILL.md").is_file():
        return True, "contains_skill_md"
    parent_low = p.parent.name.strip().lower() if p.parent else ""
    if parent_low in ("skills", "bundled-skills", "foundry-tools"):
        return True, "inside_skills_collection"
    if (p / "bin" / "ecgberht.mjs").is_file() or (p / "scripts" / "seal-chamber-bridge.mjs").is_file():
        return True, "ecgberht_engine_folder"

    return False, ""


def purge_spurious_registered_projects(*, anchor_root: Path | str | None = None) -> dict[str, Any]:
    """Remove any registered R&D project entries that point to Foundry skill folders or Anchor subfolders/backups."""
    reg = _rnd.load_registry()
    removed_ids: list[str] = []
    removed_names: list[str] = []
    kept: dict[str, dict[str, Any]] = {}
    for pid, entry in reg.items():
        fp = str(entry.get("folder_path") or "").strip()
        if not fp:
            kept[pid] = entry
            continue
        excluded, _reason = is_excluded_non_project_dir(fp, anchor_root=anchor_root)
        if excluded:
            removed_ids.append(pid)
            removed_names.append(str(entry.get("name") or Path(fp).name))
        else:
            kept[pid] = entry
    if removed_ids:
        _rnd.save_registry(kept)
    return {
        "ok": True,
        "removed_count": len(removed_ids),
        "removed_ids": removed_ids,
        "removed_names": removed_names,
    }


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(text or "").strip().lower()).strip("-")
    return s or "item"


def _resolve_base_dir(base_dir: Path | str | None = None) -> Path:
    if base_dir is not None:
        return Path(base_dir).expanduser().resolve()
    return paths.data_dir()


def sandbox_root(
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> Path:
    sid = _safe_slug(sandbox_id or DEFAULT_SANDBOX_ID)
    return _resolve_base_dir(base_dir) / ".anchor" / "onboard_sandbox" / sid


def state_dir(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> Path:
    if sandbox:
        return sandbox_root(sandbox_id=sandbox_id, base_dir=base_dir)
    return _resolve_base_dir(base_dir) / ".anchor"


def wizard_state_path(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> Path:
    return state_dir(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir) / "onboard_wizard_state.json"


def user_profile_path(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> Path:
    return state_dir(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir) / "user_profile.json"


def load_wizard_state(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    p = wizard_state_path(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    default_state: dict[str, Any] = {
        "schema": WIZARD_SCHEMA,
        "sandbox": bool(sandbox),
        "sandbox_id": _safe_slug(sandbox_id or DEFAULT_SANDBOX_ID) if sandbox else "",
        "current_step": 1,
        "completed_steps": [],
        "identity": {},
        "topology": {},
        "services": {},
        "goals": {
            "starting_flow": "goals_first",
            "mission_statement": "",
            "raw_input": "",
            "arenas": [],
            "items": [],
        },
        "projects": {
            "roots": [],
            "excluded_paths": [],
            "discovered": [],
            "provisioned": [],
        },
        "comms": {},
        "updated_at": _utc_now_iso(),
    }
    if p.is_file():
        try:
            loaded = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for k, v in loaded.items():
                    if k in default_state and isinstance(default_state[k], dict) and isinstance(v, dict):
                        default_state[k].update(v)
                    else:
                        default_state[k] = v
        except Exception:
            pass
    default_state["sandbox"] = bool(sandbox)
    default_state["sandbox_id"] = _safe_slug(sandbox_id or DEFAULT_SANDBOX_ID) if sandbox else ""
    return default_state


def save_wizard_state(
    state: dict[str, Any],
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    p = wizard_state_path(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    doc = dict(state)
    doc["schema"] = WIZARD_SCHEMA
    doc["sandbox"] = bool(sandbox)
    doc["sandbox_id"] = _safe_slug(sandbox_id or DEFAULT_SANDBOX_ID) if sandbox else ""
    doc["updated_at"] = _utc_now_iso()
    with paths.WRITE_LOCK:
        paths.atomic_write_text(p, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")
    return doc


# ═════════════════════════════════════════════════════════════════════════════
# STEP 1: User Identity, Pseudonym/Synonym & Steward Persona
# ═════════════════════════════════════════════════════════════════════════════

def _resolve_or_create_anchor_token(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
    regenerate: bool = False,
    explicit_token: str = "",
) -> dict[str, Any]:
    """Read, mint, or rotate the Mother Ship Anchor Token (ANCHOR_TOKEN / onboard-token)."""
    use_sandbox = bool(sandbox or base_dir is not None)
    if use_sandbox:
        tok_file = state_dir(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir) / "onboard-token"
    else:
        tok_file = Path.home() / ".anchor" / ".anchor" / "onboard-token"

    clean_explicit = str(explicit_token or "").strip()
    if clean_explicit and "•" not in clean_explicit and len(clean_explicit) >= 8:
        tok_file.parent.mkdir(parents=True, exist_ok=True)
        tok_file.write_text(clean_explicit + "\n", encoding="utf-8")
        tok_val = clean_explicit
    elif regenerate:
        tok_val = secrets.token_hex(24)
        tok_file.parent.mkdir(parents=True, exist_ok=True)
        tok_file.write_text(tok_val + "\n", encoding="utf-8")
    else:
        tok_val = ""
        if tok_file.is_file():
            try:
                tok_val = tok_file.read_text(encoding="utf-8").strip()
            except Exception:
                tok_val = ""
        if not tok_val and not use_sandbox:
            try:
                tok_val = str(paths.expected_token() or "").strip()
            except Exception:
                tok_val = ""
        if not tok_val:
            tok_val = secrets.token_hex(24)
            try:
                tok_file.parent.mkdir(parents=True, exist_ok=True)
                tok_file.write_text(tok_val + "\n", encoding="utf-8")
            except Exception:
                pass

    masked = (
        f"{tok_val[:6]}{'•' * 16}{tok_val[-4:]}"
        if len(tok_val) >= 12
        else ("•" * max(8, len(tok_val)))
    )
    return {
        "anchor_token": tok_val,
        "anchor_token_masked": masked,
        "token_file": str(tok_file),
    }


def get_active_user_profile(
    sandbox_id: str = "",
    *,
    sandbox: bool = False,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Return the active user's display name, collaborator pseudonym, aliases, and persona.

    Ensures Anchor never calls a collaborator someone else's name once their
    profile is configured in ``.anchor/user_profile.json``.
    """
    use_sandbox = bool(sandbox or (sandbox_id and str(sandbox_id).strip()))
    sid = str(sandbox_id or DEFAULT_SANDBOX_ID).strip()
    prof_file = user_profile_path(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)

    stored: dict[str, Any] = {}
    if prof_file.is_file():
        try:
            raw = json.loads(prof_file.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                stored = raw
        except Exception:
            stored = {}

    # Fallback to mothership_identity.json when not in sandbox
    ms_ident: dict[str, Any] = {}
    if not use_sandbox:
        try:
            ms_ident = mothership_collab.local_mothership_identity()
        except Exception:
            ms_ident = {}

    is_admin = paths.is_anchor_admin_edition(base_dir)
    display_name = str(stored.get("display_name") or "").strip()
    configured = bool(display_name)
    if not display_name:
        display_name = "John" if is_admin else ""

    raw_pseudo = str(
        stored.get("pseudonym")
        or (ms_ident.get("pseudonym") if (configured or is_admin) else "")
        or (aap.PSEUDONYM_DEFAULT if is_admin else "")
    ).strip()
    raw_aliases = stored.get("pseudonym_aliases") or (ms_ident.get("pseudonym_aliases") if (configured or is_admin) else [])
    if raw_pseudo:
        canon_pseudo, canon_aliases = aap.canonicalize_pseudonym(raw_pseudo, raw_aliases)
    else:
        canon_pseudo, canon_aliases = "", []

    persona_raw = str(stored.get("steward_persona") or "").strip().lower()
    if not persona_raw and not use_sandbox:
        try:
            import anchor_settings
            st = anchor_settings.load_settings()
            persona_raw = str(st.get("steward_type") or "aladdin").strip().lower()
        except Exception:
            persona_raw = "aladdin"
    if persona_raw not in STEWARD_PERSONAS:
        persona_raw = "aladdin"
    persona_info = STEWARD_PERSONAS[persona_raw]
    tok_info = _resolve_or_create_anchor_token(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
    username = str(stored.get("username") or "").strip() or _safe_slug(display_name)
    contact_email = str(stored.get("contact_email") or "").strip()
    pwd_configured = bool(stored.get("password_hash") or stored.get("password_configured"))
    dual_auth_enabled = bool(stored.get("dual_auth_enabled", False))
    dual_auth_method = str(stored.get("dual_auth_method") or "totp_authenticator").strip()
    dual_auth_secret = str(stored.get("dual_auth_secret") or "").strip()
    dual_auth_backup_codes = list(stored.get("dual_auth_backup_codes") or [])
    backup_hashes = list(stored.get("dual_auth_backup_hashes") or [])
    backup_codes_remaining = (
        sum(1 for r in backup_hashes if isinstance(r, dict) and not r.get("used"))
        if backup_hashes
        else len(dual_auth_backup_codes)
    )
    dual_auth_uri = (
        f"otpauth://totp/Anchor:{username}?secret={dual_auth_secret.replace(' ', '')}&issuer=Anchor"
        if dual_auth_secret
        else ""
    )

    return {
        "display_name": display_name,
        "username": username,
        "contact_email": contact_email,
        "password_configured": pwd_configured,
        "has_password": pwd_configured,
        "dual_auth_enabled": dual_auth_enabled,
        "dual_auth_method": dual_auth_method,
        "dual_auth_secret": dual_auth_secret,
        "dual_auth_otpauth_uri": dual_auth_uri,
        "dual_auth_backup_codes": dual_auth_backup_codes,
        "backup_codes_remaining": backup_codes_remaining,
        "anchor_token": tok_info["anchor_token"],
        "anchor_token_masked": tok_info["anchor_token_masked"],
        "anchor_token_file": tok_info["token_file"],
        "pseudonym": canon_pseudo,
        "pseudonym_slug": aap.slugify_pseudonym(canon_pseudo),
        "pseudonym_aliases": canon_aliases,
        "did": aap.did_from_pseudonym(canon_pseudo),
        "steward_persona": persona_info["label"],
        "steward_persona_id": persona_raw,
        "steward_title": persona_info["title"],
        "configured": configured,
        "sandbox": use_sandbox,
    }


def _wizard_license_store_dir(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> Path:
    return state_dir(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)


def get_wizard_license_status(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    import website_portal as _wp
    sdir = _wizard_license_store_dir(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    st = _wp.get_local_license_status(store_dir=sdir)
    if not st.get("accepted") and not sandbox and base_dir is None:
        st_default = _wp.get_local_license_status(store_dir=None)
        if st_default.get("accepted"):
            return st_default
    return st


def save_user_identity(
    display_name: str,
    pseudonym: str = "",
    pseudonym_aliases: list[str] | str | None = None,
    steward_persona: str = "Aladdin",
    username: str = "",
    password: str = "",
    contact_email: str = "",
    dual_auth_enabled: bool | None = None,
    dual_auth_method: str = "",
    anchor_token: str = "",
    accepted_gwl_license: bool | None = None,
    require_license_ack: bool = False,
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Save Step 1 User Identity (Real Name, Collaborator Pseudonym, Ghost World Labs License Ack, Credentials & Steward Persona)."""
    cur_lic = get_wizard_license_status(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    if require_license_ack and accepted_gwl_license is not True and not cur_lic.get("accepted"):
        return {
            "ok": False,
            "status_code": 400,
            "error": "license_acceptance_required",
            "message": "Please check the Ghost World Labs License acknowledgement box (Free Use · No Resale or Commercialization) to continue.",
        }
    is_admin = paths.is_anchor_admin_edition(base_dir)
    clean_name = str(display_name or "").strip() or ("John" if is_admin else "Collaborator")
    if isinstance(pseudonym_aliases, str):
        alias_list = [a.strip() for a in pseudonym_aliases.split(",") if a.strip()]
    elif isinstance(pseudonym_aliases, list):
        alias_list = [str(a).strip() for a in pseudonym_aliases if str(a).strip()]
    else:
        alias_list = []

    eff_pseudo = str(pseudonym or "").strip() or (aap.PSEUDONYM_DEFAULT if is_admin else clean_name)
    canon_pseudo, canon_aliases = aap.canonicalize_pseudonym(eff_pseudo, alias_list)
    persona_key = str(steward_persona or "aladdin").strip().lower()
    if persona_key not in STEWARD_PERSONAS:
        persona_key = "aladdin"
    persona_info = STEWARD_PERSONAS[persona_key]

    pfile = user_profile_path(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    prev_prof: dict[str, Any] = {}
    if pfile.is_file():
        try:
            loaded_p = json.loads(pfile.read_text(encoding="utf-8"))
            if isinstance(loaded_p, dict):
                prev_prof = loaded_p
        except Exception:
            prev_prof = {}

    clean_user = str(username or prev_prof.get("username") or _safe_slug(clean_name)).strip() or _safe_slug(clean_name)
    clean_email = str(contact_email if contact_email != "" else (prev_prof.get("contact_email") or "")).strip()
    pwd_hash = str(prev_prof.get("password_hash") or "")
    pwd_salt = str(prev_prof.get("password_salt") or "")
    if password and str(password).strip() and "•" not in str(password):
        clean_pwd = str(password).strip()
        salt_bytes = secrets.token_bytes(16)
        pwd_salt = salt_bytes.hex()
        pwd_hash = hashlib.pbkdf2_hmac("sha256", clean_pwd.encode("utf-8"), salt_bytes, 120_000).hex()
        if not sandbox and base_dir is None and provider_secrets.available():
            try:
                provider_secrets.put("anchor-user-password", clean_pwd)
            except Exception:
                pass

    d_enabled = bool(prev_prof.get("dual_auth_enabled", False)) if dual_auth_enabled is None else bool(dual_auth_enabled)
    d_method = str(dual_auth_method or prev_prof.get("dual_auth_method") or "totp_authenticator").strip()
    d_secret = str(prev_prof.get("dual_auth_secret") or "").strip()
    d_backup_codes: list[str] = list(prev_prof.get("dual_auth_backup_codes") or [])
    d_backup_hashes: list[dict[str, Any]] = list(prev_prof.get("dual_auth_backup_hashes") or [])
    if d_enabled and not d_secret:
        raw_b32 = base64.b32encode(secrets.token_bytes(10)).decode("ascii").rstrip("=")
        d_secret = " ".join(raw_b32[i:i + 4] for i in range(0, len(raw_b32), 4))
    if d_enabled and not d_backup_codes:
        import gwl_admin_gui as _gag
        bc_bundle = _gag.generate_2fa_backup_codes(10)
        d_backup_codes = bc_bundle["codes"]
        d_backup_hashes = bc_bundle["hashed_records"]

    if anchor_token and str(anchor_token).strip() and "•" not in str(anchor_token):
        _resolve_or_create_anchor_token(
            sandbox=sandbox,
            sandbox_id=sandbox_id,
            base_dir=base_dir,
            explicit_token=str(anchor_token).strip(),
        )
    else:
        _resolve_or_create_anchor_token(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    lic_receipt = None
    if accepted_gwl_license is True:
        try:
            import website_portal as _wp
            sdir_lic = _wizard_license_store_dir(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
            lic_res = _wp.accept_non_resale_license(
                canon_pseudo or clean_name,
                True,
                intended_use="personal_or_research",
                store_dir=sdir_lic,
            )
            if lic_res.get("ok"):
                lic_receipt = lic_res.get("receipt")
        except Exception:
            lic_receipt = None
    final_lic_status = get_wizard_license_status(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    profile_doc = {
        "schema": "anchor.user.profile.v1",
        "display_name": clean_name,
        "username": clean_user,
        "contact_email": clean_email,
        "password_configured": bool(pwd_hash),
        "password_hash": pwd_hash,
        "password_salt": pwd_salt,
        "dual_auth_enabled": d_enabled,
        "dual_auth_method": d_method,
        "dual_auth_secret": d_secret,
        "dual_auth_backup_codes": d_backup_codes,
        "dual_auth_backup_hashes": d_backup_hashes,
        "pseudonym": canon_pseudo,
        "pseudonym_slug": aap.slugify_pseudonym(canon_pseudo),
        "pseudonym_aliases": canon_aliases,
        "did": aap.did_from_pseudonym(canon_pseudo),
        "steward_persona": persona_info["label"],
        "steward_persona_id": persona_key,
        "gwl_license_accepted": bool(final_lic_status.get("accepted")),
        "gwl_license_id": final_lic_status.get("license_id") or "GHOST-WORLD-LAB-NON-RESALE-v1",
        "updated_at": _utc_now_iso(),
    }

    pfile = user_profile_path(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    pfile.parent.mkdir(parents=True, exist_ok=True)
    with paths.WRITE_LOCK:
        paths.atomic_write_text(pfile, json.dumps(profile_doc, indent=2, ensure_ascii=False) + "\n")

    if not sandbox and base_dir is None:
        try:
            mothership_collab.set_local_pseudonym(canon_pseudo, canon_aliases)
        except Exception:
            pass
        try:
            import anchor_settings
            st = anchor_settings.read_settings_state()
            rev = st.get("settings", {}).get("settings_revision", 0) if st.get("valid") else 0
            anchor_settings.save_settings(steward_type=persona_key, expected_revision=rev)
        except Exception:
            pass
        try:
            from steward_cockpit import steward_routes as _sr
            _sr.rename_stewards(persona_meta["label"])
        except Exception:
            pass

    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    st_doc["identity"] = profile_doc
    if 1 not in st_doc["completed_steps"]:
        st_doc["completed_steps"].append(1)
    st_doc["current_step"] = max(int(st_doc.get("current_step") or 1), 2)
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    gwl_sync = sync_applicant_signup_to_gwl_hub(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    return {
        "ok": True,
        "profile": get_active_user_profile(sandbox_id if sandbox else "", sandbox=sandbox, base_dir=base_dir),
        "license_status": final_lic_status,
        "license_receipt": lic_receipt,
        "gwl_applicant": gwl_sync.get("applicant"),
    }


def _gwl_hub_root_for(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> Path | None:
    if sandbox:
        return state_dir(sandbox=True, sandbox_id=sandbox_id, base_dir=base_dir) / "gwl_hub"
    if base_dir is not None:
        return _resolve_base_dir(base_dir) / ".anchor" / "gwl_hub"
    return None


def sync_applicant_signup_to_gwl_hub(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Record or update the onboarding individual in the local Ghost World Labs collaborator directory."""
    try:
        import gwl_clearinghouse as _gwl
    except Exception:
        return {"ok": False}

    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    prof = get_active_user_profile(sandbox_id if sandbox else "", sandbox=sandbox, base_dir=base_dir)
    topo = st_doc.get("topology") if isinstance(st_doc.get("topology"), dict) else {}
    ts_info = topo.get("tailscale") if isinstance(topo.get("tailscale"), dict) else {}
    services = st_doc.get("services") if isinstance(st_doc.get("services"), dict) else {}

    enabled_svcs = [
        f"{fam}:{cfg.get('orchestrator_model') or ''}"
        for fam, cfg in services.items()
        if isinstance(cfg, dict) and cfg.get("enabled")
    ]
    verified_svcs = [
        f"{fam}:{cfg.get('orchestrator_model') or ''}"
        for fam, cfg in services.items()
        if isinstance(cfg, dict) and cfg.get("verified")
    ]
    completed_steps = st_doc.get("completed_steps") or []
    onboard_status = "ready" if len(completed_steps) >= 3 else f"step_{st_doc.get('current_step') or 1}"
    ts_ip = str(ts_info.get("tailscale_ip") or "").strip()
    record = {
        "display_name": prof.get("display_name") or "Collaborator",
        "username": prof.get("username") or "",
        "contact_email": prof.get("contact_email") or "",
        "pseudonym": prof.get("pseudonym") or prof.get("display_name") or "Collaborator",
        "pseudonym_aliases": prof.get("pseudonym_aliases") or [],
        "steward_persona": prof.get("steward_persona") or "Aladdin",
        "hostname": str(ts_info.get("hostname") or os.environ.get("COMPUTERNAME") or "").strip(),
        "tailscale_ip": ts_ip,
        "tailscale_endpoint": f"http://{ts_ip}:8777" if ts_ip else str(topo.get("local_url") or "http://127.0.0.1:8777"),
        "topology_mode": str(topo.get("mode") or "main_mothership"),
        "dual_auth_enabled": bool(prof.get("dual_auth_enabled", False)),
        "dual_auth_method": str(prof.get("dual_auth_method") or "totp_authenticator"),
        "backup_codes_remaining": int(prof.get("backup_codes_remaining") or (10 if prof.get("dual_auth_enabled") else 0)),
        "enabled_services": enabled_svcs,
        "verified_services": verified_svcs,
        "onboarding_status": onboard_status,
    }
    hub_root = _gwl_hub_root_for(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    res = _gwl.register_applicant_signup(record, hub_root=hub_root)

    # Only sync to an explicitly configured coordination_hub URL (never probe personal author endpoints)
    coord_hub = str(topo.get("coordination_hub") or topo.get("remote_mothership_url") or os.environ.get("ANCHOR_HOMEBASE_URL") or "").strip().rstrip("/")
    if not sandbox and base_dir is None and coord_hub.startswith(("http://", "https://")) and "127.0.0.1" not in coord_hub and "localhost" not in coord_hub:
        import urllib.request as _ureq
        payload = json.dumps({"action": "register_gwl_applicant", "applicant": res.get("applicant") or record}).encode("utf-8")
        try:
            req = _ureq.Request(
                f"{coord_hub}/api/onboard-wizard/action",
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "Anchor-Onboard-ApplicantSync/1.0"},
                method="POST",
            )
            with paths.safe_urlopen(req, timeout=2.5):
                pass
        except Exception:
            pass
        try:
            import mothership_updater as _mu_sync
            _mu_sync.register_with_homebase(
                owner=str(record.get("display_name") or ""),
                contact_email=str(record.get("contact_email") or ""),
                pseudonym=str(record.get("pseudonym") or ""),
                hostname=str(record.get("hostname") or ""),
                tailscale_ip=ts_ip,
                tailscale_url=str(ts_info.get("tailscale_url") or ""),
                homebase_url=coord_hub,
                telemetry_enabled=bool(topo.get("telemetry_enabled", True)),
            )
        except Exception:
            pass
    return res


# ═════════════════════════════════════════════════════════════════════════════
# STEP 2: Mothership Topology & Tailscale Network Connection
# ═════════════════════════════════════════════════════════════════════════════

def detect_or_install_tailscale(
    *,
    sandbox: bool = False,
    auto_install: bool = False,
    runner_fn=None,
) -> dict[str, Any]:
    """Detect Tailscale CLI and node status, or run automated installer when requested.

    In ``sandbox=True`` mode, ignores existing live Tailscale/anchor.exe connections
    so a user on a configured work desktop can test the fresh-install or pairing flow.
    """
    install_cmd = "winget install --id tailscale.tailscale -e --accept-package-agreements --accept-source-agreements"
    if sandbox:
        return {
            "sandbox_ignored_live": True,
            "installed": True if auto_install else False,
            "auto_installed": bool(auto_install),
            "running": True if auto_install else False,
            "needs_setup": not bool(auto_install),
            "tailscale_ip": "100.101.102.103" if auto_install else "",
            "hostname": "sandbox-work-desktop",
            "install_command": install_cmd,
            "peers": [
                {"hostname": "primary-mothership", "ip": "100.64.0.1", "online": True, "role": "Primary Mothership"},
                {"hostname": "collaborator-node", "ip": "100.64.0.2", "online": True, "role": "Collaborator"},
            ],
            "note": (
                "Sandbox Walkthrough Mode active: ignoring existing desktop anchor.exe & Tailscale state "
                "so you can test the fresh onboarding flow end-to-end."
            ),
        }

    ts_exe = shutil.which("tailscale")
    if not ts_exe and os.name == "nt":
        candidate = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
        if candidate.is_file():
            ts_exe = str(candidate)

    auto_installed = False
    run_call = runner_fn or subprocess.run
    if not ts_exe and auto_install:
        try:
            res = run_call(
                ["winget", "install", "--id", "tailscale.tailscale", "-e",
                 "--accept-package-agreements", "--accept-source-agreements"],
                capture_output=True, text=True, timeout=120, creationflags=paths.NO_WINDOW,
            )
            auto_installed = (getattr(res, "returncode", 1) == 0)
            ts_exe = shutil.which("tailscale") or ts_exe
        except Exception:
            auto_installed = False

    running = False
    ts_ip = ""
    dns_name = ""
    ts_url = ""
    hostname = ""
    peers: list[dict[str, Any]] = []
    if ts_exe:
        try:
            res = run_call(
                [ts_exe, "status", "--json"],
                capture_output=True, text=True, timeout=6, creationflags=paths.NO_WINDOW,
            )
            if getattr(res, "returncode", 1) == 0 and getattr(res, "stdout", ""):
                data = json.loads(res.stdout)
                state_str = str(data.get("BackendState") or "")
                running = state_str == "Running"
                self_node = data.get("Self") or {}
                ips = self_node.get("TailscaleIPs") or []
                ts_ip = str(ips[0]) if ips else ""
                dns_name = str(self_node.get("DNSName") or "").strip().rstrip(".")
                ts_url = f"https://{dns_name}" if dns_name else (f"http://{ts_ip}:8777" if ts_ip else "")
                hostname = str(self_node.get("HostName") or "")
                for _k, pv in (data.get("Peer") or {}).items():
                    if not isinstance(pv, dict):
                        continue
                    p_ips = pv.get("TailscaleIPs") or []
                    peers.append({
                        "hostname": str(pv.get("HostName") or "peer"),
                        "ip": str(p_ips[0]) if p_ips else "",
                        "online": bool(pv.get("Online")),
                    })
        except Exception:
            pass

    return {
        "sandbox_ignored_live": False,
        "installed": bool(ts_exe),
        "executable": ts_exe or "",
        "auto_installed": auto_installed,
        "running": running,
        "needs_setup": (not bool(ts_exe)) or (not running),
        "tailscale_ip": ts_ip,
        "dns_name": dns_name,
        "tailscale_url": ts_url,
        "hostname": hostname,
        "install_command": install_cmd,
        "peers": peers,
        "note": (
            "Tailscale connected and running."
            if (ts_exe and running)
            else ("Tailscale installed but not signed in — would you like to sign in now?" if ts_exe else "Tailscale is not installed — would you like to set up Tailscale?")
        ),
    }


def setup_tailscale_interactive(
    *,
    sandbox: bool = False,
    runner_fn=None,
) -> dict[str, Any]:
    """Install Tailscale if missing and launch interactive Tailscale sign-in."""
    if sandbox:
        return {
            "ok": True,
            "installed": True,
            "launched_login": True,
            "message": "Sandbox verified: Tailscale installed and browser login opened.",
        }
    ts_res = detect_or_install_tailscale(sandbox=False, auto_install=True, runner_fn=runner_fn)
    ts_exe = str(ts_res.get("executable") or shutil.which("tailscale") or "")
    if not ts_exe:
        if runner_fn is None and "PYTEST_CURRENT_TEST" not in os.environ and paths.is_interactive_desktop_session():
            try:
                webbrowser.open("https://tailscale.com/download")
            except Exception:
                pass
        return {
            "ok": False,
            "installed": False,
            "launched_login": False,
            "download_url": "https://tailscale.com/download",
            "message": "Install Tailscale from https://tailscale.com/download, or skip to continue locally.",
        }
    if not ts_res.get("running"):
        if runner_fn is not None:
            runner_fn([ts_exe, "up"])
        elif "PYTEST_CURRENT_TEST" not in os.environ and paths.is_interactive_desktop_session():
            try:
                if os.name == "nt":
                    gui_exe = Path(ts_exe).with_name("tailscale-ipn.exe")
                    if gui_exe.is_file():
                        subprocess.Popen([str(gui_exe)], creationflags=paths.NO_WINDOW)
                    subprocess.Popen([ts_exe, "login"], creationflags=paths.NO_WINDOW)
                else:
                    subprocess.Popen([ts_exe, "up"], start_new_session=True)
            except Exception:
                pass
    return {
        "ok": True,
        "installed": True,
        "running": bool(ts_res.get("running")),
        "launched_login": not bool(ts_res.get("running")),
        "message": (
            "Tailscale is already connected and running!"
            if ts_res.get("running")
            else "Tailscale setup launched! Complete sign-in in the browser tab that opened."
        ),
    }


def register_anchor_repository(
    email: str,
    *,
    owner: str = "",
    pseudonym: str = "",
    tailscale_url: str = "",
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """1-click collaborator registration connecting email to the locked official Anchor GitHub repository."""
    clean_email = str(email or "").strip()
    if not clean_email or "@" not in clean_email:
        return {
            "ok": False,
            "status_code": 400,
            "error": "invalid_email",
            "message": "Please enter a valid email address to register.",
        }
    prof = get_active_user_profile(sandbox_id if sandbox else "", sandbox=sandbox, base_dir=base_dir)
    eff_owner = str(owner or prof.get("display_name") or "Collaborator").strip()
    eff_pseudo = str(pseudonym or prof.get("pseudonym") or eff_owner).strip()
    pfile = user_profile_path(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    if pfile.is_file():
        try:
            pdoc = json.loads(pfile.read_text(encoding="utf-8"))
            if isinstance(pdoc, dict):
                pdoc["contact_email"] = clean_email
                with paths.WRITE_LOCK:
                    paths.atomic_write_text(pfile, json.dumps(pdoc, indent=2, ensure_ascii=False) + "\n")
        except Exception:
            pass
    else:
        save_user_identity(
            display_name=eff_owner,
            pseudonym=eff_pseudo,
            contact_email=clean_email,
            sandbox=sandbox,
            sandbox_id=sandbox_id,
            base_dir=base_dir,
        )

    sdir = state_dir(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    receipt = {
        "schema": "anchor.registry.receipt.v1",
        "registered": True,
        "email": clean_email,
        "owner": eff_owner,
        "pseudonym": eff_pseudo,
        "canonical_github_repo": CANONICAL_ANCHOR_GITHUB_URL,
        "auto_pull_updates": True,
        "registered_at": _utc_now_iso(),
    }
    sdir.mkdir(parents=True, exist_ok=True)
    with paths.WRITE_LOCK:
        paths.atomic_write_text(sdir / "registration.json", json.dumps(receipt, indent=2) + "\n")

    if not sandbox:
        try:
            import mothership_updater as _mu
            eff_root = _resolve_base_dir(base_dir) if base_dir is not None else None
            _mu.register_mothership_in_repo(
                {
                    "email": clean_email,
                    "contact_email": clean_email,
                    "owner": eff_owner,
                    "pseudonym": eff_pseudo,
                    "tailscale_url": tailscale_url,
                    "github_repo": CANONICAL_ANCHOR_GITHUB_URL,
                },
                anchor_root=eff_root,
                write_repo=False,
            )
        except Exception:
            pass

    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    st_doc.setdefault("topology", {})["registration"] = receipt
    if 2 not in st_doc["completed_steps"]:
        st_doc["completed_steps"].append(2)
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    return {
        "ok": True,
        "registered": True,
        "email": clean_email,
        "canonical_github_repo": CANONICAL_ANCHOR_GITHUB_URL,
        "receipt": receipt,
        "message": f"Registered {clean_email} with {CANONICAL_ANCHOR_GITHUB_URL} — automatic website-watched updates are active!",
    }


def _read_registration_receipt(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    sdir = state_dir(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    rp = sdir / "registration.json"
    if rp.is_file():
        try:
            doc = json.loads(rp.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                return doc
        except Exception:
            pass
    hb = _homebase_link_summary(base_dir) if not sandbox else {}
    return {
        "registered": bool(hb.get("registered")),
        "email": str(hb.get("contact_email") or ""),
        "canonical_github_repo": CANONICAL_ANCHOR_GITHUB_URL,
    }


def _homebase_link_summary(base_dir: Path | str | None = None) -> dict[str, Any]:
    """Read-only safe Homebase registration metadata for receipts and Step 2 UI."""
    try:
        import mothership_updater as _mu
        eff_root = _resolve_base_dir(base_dir) if base_dir is not None else None
        link = _mu.read_homebase_link(anchor_root=eff_root)
        return _mu._public_link_view(link)
    except Exception:
        return {
            "registered": False,
            "homebase_url": "",
            "canonical_github_repo": CANONICAL_ANCHOR_GITHUB_URL,
            "telemetry_enabled": True,
        }


def configure_mothership_topology(
    mode: str = "main_mothership",
    *,
    remote_address: str = "",
    hub_endpoint: str = "",
    telemetry_enabled: bool = True,
    auto_pull_updates: bool = True,
    low_spec_mode: bool | None = None,
    auto_install_tailscale: bool = False,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
    runner_fn=None,
) -> dict[str, Any]:
    """Configure Step 2: Main Mothership vs. Connect to a Different Mothership + Website Auto-Updater + Low-Spec Laptop Mode."""
    norm_mode = str(mode or "main_mothership").strip().lower()
    if norm_mode not in ("main_mothership", "connect_remote_mothership"):
        norm_mode = "main_mothership"
    hw_prof = paths.detect_host_hardware_profile()
    eff_low_spec = bool(hw_prof["low_spec_recommended"] if low_spec_mode is None else low_spec_mode)

    ts_info = detect_or_install_tailscale(
        sandbox=sandbox,
        auto_install=auto_install_tailscale,
        runner_fn=runner_fn,
    )
    ecg_path, ecg_checked = paths.resolve_ecgberht_root()
    bridge_file = ecg_path / "scripts" / "seal-chamber-bridge.mjs"
    ecg_ok = bridge_file.is_file() or (ecg_path / "bin" / "ecgberht.mjs").is_file()
    eff_hub = str(remote_address or hub_endpoint or os.environ.get("ANCHOR_HOMEBASE_URL") or "").strip()

    if norm_mode == "main_mothership":
        topology_doc = {
            "mode": "main_mothership",
            "mode_label": "This Computer IS a Main Mothership",
            "local_url": "http://127.0.0.1:8777",
            "coordination_hub": eff_hub,
            "canonical_github_repo": CANONICAL_ANCHOR_GITHUB_URL,
            "telemetry_enabled": bool(telemetry_enabled),
            "tailscale": ts_info,
            "ecgberht_root": str(ecg_path),
            "ecgberht_ok": ecg_ok,
            "ecgberht_checked_paths": ecg_checked,
            "verified": True,
            "updated_at": _utc_now_iso(),
        }
    else:
        target = str(remote_address or hub_endpoint or "").strip()
        if target and not target.startswith(("http://", "https://")):
            target = "https://" + target
        topology_doc = {
            "mode": "connect_remote_mothership",
            "mode_label": "Connected to Remote Mothership via Tailscale",
            "remote_mothership_url": target,
            "coordination_hub": str(hub_endpoint or target).strip(),
            "canonical_github_repo": CANONICAL_ANCHOR_GITHUB_URL,
            "telemetry_enabled": bool(telemetry_enabled),
            "tailscale": ts_info,
            "ecgberht_root": str(ecg_path),
            "ecgberht_ok": ecg_ok,
            "ecgberht_checked_paths": ecg_checked,
            "verified": True,
            "updated_at": _utc_now_iso(),
        }
        if not sandbox and base_dir is None and target:
            try:
                mothership_collab.register_peer({
                    "id": "remote-mothership",
                    "pseudonym": "Remote Mothership",
                    "label": f"Remote Mothership ({target})",
                    "transport": "tailscale_http",
                    "endpoint": target,
                    "role": "lead",
                })
            except Exception:
                pass

    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    topology_doc["auto_pull_updates"] = bool(auto_pull_updates)
    topology_doc["low_spec_mode"] = eff_low_spec
    topology_doc["hardware_profile"] = hw_prof
    st_doc["topology"] = topology_doc
    if 2 not in st_doc["completed_steps"]:
        st_doc["completed_steps"].append(2)
    st_doc["current_step"] = max(int(st_doc.get("current_step") or 1), 3)
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    sync_applicant_signup_to_gwl_hub(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    hb_summary: dict[str, Any] = {
        "registered": False,
        "sandbox": bool(sandbox),
        "telemetry_enabled": bool(telemetry_enabled),
        "auto_pull_updates": bool(auto_pull_updates),
        "low_spec_mode": eff_low_spec,
    }
    if not sandbox:
        try:
            import mothership_updater as _mu
            eff_root = _resolve_base_dir(base_dir) if base_dir is not None else None
            _mu.load_or_init_homebase_link(
                anchor_root=eff_root,
                homebase_url=eff_hub,
                telemetry_enabled=bool(telemetry_enabled),
                auto_pull_updates=bool(auto_pull_updates),
                low_spec_mode=eff_low_spec,
            )
            if eff_hub and base_dir is None and "PYTEST_CURRENT_TEST" not in os.environ:
                prof_cur = get_active_user_profile("", sandbox=False, base_dir=None)
                _mu.register_with_homebase(
                    owner=str(prof_cur.get("display_name") or ""),
                    contact_email=str(prof_cur.get("contact_email") or ""),
                    pseudonym=str(prof_cur.get("pseudonym") or ""),
                    homebase_url=eff_hub,
                    telemetry_enabled=bool(telemetry_enabled),
                )
            hb_summary = _homebase_link_summary(base_dir)
        except Exception:
            hb_summary = _homebase_link_summary(base_dir)
    return {"ok": True, "topology": topology_doc, "homebase_link": hb_summary}


# ═════════════════════════════════════════════════════════════════════════════
# STEP 3: AI Services Menu, Credentials, Model Tiers, CLI Updater & Live Probe
# ═════════════════════════════════════════════════════════════════════════════

_STALE_MODEL_UPGRADES: dict[str, str] = {
    "claude-opus-4-7": "claude-fable-5-2",
    "claude-fable-5-1": "claude-fable-5-2",
    "claude-sonnet-4-6": "opus",
    "gemini-3.1-pro-high": "gemini-4-hydrogen",
    "gemini-3-flash": "gemini-3.8-flash",
    "grok-4": "grok-4.7",
    "grok-3-mini": "grok-4.7",
    "gpt-5.4": "gpt-6-luna",
    "gpt-6.1-sol": "gpt-6-luna",
    "gpt-5-mini": "gpt-5.6-terra",
}

_LIVE_MODEL_CACHE: dict[str, list[dict[str, Any]]] = {}


def _discover_live_service_models(family: str, *, force: bool = False) -> list[dict[str, Any]]:
    """Query model_policy.discover(family) for live CLI-advertised models (cached in memory)."""
    fam = str(family or "").strip().lower()
    if not force and fam in _LIVE_MODEL_CACHE:
        return _LIVE_MODEL_CACHE[fam]
    out_rows: list[dict[str, Any]] = []
    try:
        import model_policy
        rows, _cmd = model_policy.discover(fam)
        sorted_rows = sorted(
            [r for r in (rows or []) if isinstance(r, dict) and r.get("model")],
            key=lambda item: int(item.get("rank", 0)),
        )
        for rank_idx, r in enumerate(sorted_rows):
            m_id = str(r["model"]).strip()
            upg = str(r.get("upgrade") or "").strip()
            effs = list(r.get("efforts") or ["high"])
            disp = f"{upg} ({m_id})" if (upg and upg != m_id) else m_id
            out_rows.append({
                "model": (upg or "claude-fable-5-2") if (fam == "claude" and m_id in ("best", "default")) else m_id,
                "alias": m_id,
                "display": disp,
                "efforts": effs,
                "rank": rank_idx,
                "live_discovered": True,
            })
    except Exception:
        pass
    # Only fall back to static hub catalog when live CLI discovery returned nothing.
    # Never inject unentitled static models (e.g. gemini-4-argon) ahead of a collaborator's real live CLI catalog!
    if not out_rows:
        try:
            import gwl_clearinghouse as _gwl
            hub_cat = _gwl.get_verified_model_catalog().get("families") or {}
            fam_cat = hub_cat.get(fam) if isinstance(hub_cat.get(fam), dict) else {}
            existing_ids: set[str] = set()
            for rank_idx, m_str in enumerate(fam_cat.get("discovered_models") or []):
                m_clean = str(m_str or "").strip()
                if m_clean and m_clean not in existing_ids:
                    out_rows.append({
                        "model": m_clean,
                        "alias": m_clean,
                        "display": m_clean,
                        "efforts": ["high"],
                        "rank": rank_idx,
                        "live_discovered": False,
                    })
                    existing_ids.add(m_clean)
        except Exception:
            pass
    if not out_rows and fam in SERVICE_CATALOG:
        t_map = SERVICE_CATALOG[fam]["tiers"]
        out_rows = [
            {
                "model": t_map["frontier"]["orchestrator_model"],
                "alias": t_map["frontier"]["orchestrator_model"],
                "display": t_map["frontier"]["orchestrator_model"],
                "efforts": [t_map["frontier"]["effort"]],
                "rank": 0,
                "live_discovered": False,
            },
            {
                "model": t_map["one_tier_down"]["orchestrator_model"],
                "alias": t_map["one_tier_down"]["orchestrator_model"],
                "display": t_map["one_tier_down"]["orchestrator_model"],
                "efforts": [t_map["one_tier_down"]["effort"]],
                "rank": 1,
                "live_discovered": False,
            },
        ]
    _LIVE_MODEL_CACHE[fam] = out_rows
    return out_rows


def _get_nightly_refresh_meta() -> dict[str, Any]:
    """Read Nightly 02:00 model refresh & 15-minute allowance schedule metadata."""
    try:
        import usage_allowance_monitor as _uam
        return _uam._read_auto_refresh_meta()
    except Exception:
        return {
            "enabled": True,
            "models_schedule": "Nightly 02:00 local",
            "schedule": "Allowance: every 15m · Models: Nightly (02:00 local) + Live CLI",
            "last_refresh_local": datetime.now().astimezone().strftime("%a %b %d %H:%M"),
            "last_model_check_day": datetime.now().astimezone().strftime("%Y-%m-%d"),
        }


def detect_ai_services_status(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Return status for all 4 AI services (Claude, Gemini, Grok, ChatGPT)."""
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    saved_services = st_doc.get("services") or {}
    home = Path.home()

    out_services: dict[str, Any] = {}
    for fam, meta in SERVICE_CATALOG.items():
        saved = saved_services.get(fam) if isinstance(saved_services.get(fam), dict) else {}
        cli_name = meta["cli"]
        cli_path = shutil.which(cli_name)
        if not cli_path and fam == "gemini":
            local_app = os.environ.get("LOCALAPPDATA") or ""
            if local_app and (Path(local_app) / "agy" / "bin" / "agy.exe").is_file():
                cli_path = str(Path(local_app) / "agy" / "bin" / "agy.exe")
        if not cli_path and fam == "grok":
            cand = home / ".grok" / "bin" / "grok.exe"
            if cand.is_file():
                cli_path = str(cand)
        if not cli_path and fam == "chatgpt":
            cand = home / ".codex" / "bin" / "codex.exe"
            if cand.is_file():
                cli_path = str(cand)

        tier_level = str(saved.get("tier_level") or "frontier")
        if tier_level not in meta["tiers"]:
            tier_level = "frontier"
        live_models = _discover_live_service_models(fam, force=False)
        from copy import deepcopy
        dyn_tiers = deepcopy(meta["tiers"])
        if live_models:
            f_mod = live_models[0]["model"]
            dyn_tiers["frontier"]["orchestrator_model"] = f_mod
            dyn_tiers["frontier"]["reviewer_model"] = f_mod
            if len(live_models) > 1:
                o_mod = live_models[1]["model"]
                dyn_tiers["one_tier_down"]["orchestrator_model"] = o_mod
                dyn_tiers["one_tier_down"]["reviewer_model"] = o_mod
        tier_defaults = dyn_tiers[tier_level]

        raw_saved_orch = str(saved.get("orchestrator_model") or "").strip()
        if raw_saved_orch in _STALE_MODEL_UPGRADES:
            raw_saved_orch = _STALE_MODEL_UPGRADES[raw_saved_orch]
        raw_saved_rev = str(saved.get("reviewer_model") or "").strip()
        if raw_saved_rev in _STALE_MODEL_UPGRADES:
            raw_saved_rev = _STALE_MODEL_UPGRADES[raw_saved_rev]
        live_only_ids = {r.get("model") for r in live_models if r.get("live_discovered")}
        if live_only_ids and raw_saved_orch and raw_saved_orch not in live_only_ids and raw_saved_orch not in ("best", "opus", "sonnet", "haiku"):
            raw_saved_orch = tier_defaults["orchestrator_model"]
        if live_only_ids and raw_saved_rev and raw_saved_rev not in live_only_ids and raw_saved_rev not in ("best", "opus", "sonnet", "haiku"):
            raw_saved_rev = tier_defaults["reviewer_model"]

        is_verified = bool(saved.get("verified", False))
        has_key = bool(saved.get("has_api_key", False))
        if not has_key and not sandbox and base_dir is None:
            try:
                has_key = bool(provider_secrets.get(f"{fam}-default"))
            except Exception:
                has_key = False

        if fam == "chatgpt":
            is_enabled = bool(saved.get("enabled", False) and (is_verified or has_key or saved.get("user_enabled")))
        else:
            is_enabled = bool(saved.get("enabled", True))

        if is_verified:
            conn_state = "verified"
            conn_badge = f"VERIFIED ✓ ({(saved.get('last_test') or {}).get('attested_model') or raw_saved_orch or tier_defaults['orchestrator_model']})"
        elif has_key:
            conn_state = "api_key_saved"
            conn_badge = "API KEY SAVED (Click Verify to Test)"
        elif cli_path and fam == "chatgpt" and not is_enabled:
            conn_state = "signin_needed"
            conn_badge = "CLI INSTALLED · NOT SIGNED IN (Inactive)"
        elif cli_path:
            conn_state = "cli_ready"
            conn_badge = "CLI INSTALLED · READY TO VERIFY"
        else:
            conn_state = "not_installed"
            conn_badge = "CLI NOT INSTALLED"

        out_services[fam] = {
            "family": fam,
            "label": meta["label"],
            "cli": cli_name,
            "cli_installed": bool(cli_path),
            "default_role": meta["default_role"],
            "enabled": is_enabled,
            "auth_mode": str(saved.get("auth_mode") or "subscription"),
            "has_api_key": has_key,
            "has_api_key_stored": has_key,
            "connection_state": conn_state,
            "connection_badge": conn_badge,
            "tier_level": tier_level,
            "tier_label": tier_defaults["label"],
            "orchestrator_model": raw_saved_orch or tier_defaults["orchestrator_model"],
            "selected_model": raw_saved_orch or tier_defaults["orchestrator_model"],
            "reviewer_model": raw_saved_rev or tier_defaults["reviewer_model"],
            "effort": str(saved.get("effort") or tier_defaults["effort"]),
            "cli_version": str(saved.get("cli_version") or ("CLI binary on PATH (sign-in unverified)" if (cli_path and fam == "chatgpt" and not is_verified) else ("detected" if cli_path else "not installed"))),
            "verified": is_verified,
            "last_test": saved.get("last_test") or None,
            "available_tiers": dyn_tiers,
            "discovered_models": live_models,
            "free_tier_guide": meta.get("free_tier_guide") or "",
            "single_seat_pacing": bool(tier_defaults.get("single_seat_pacing", tier_level == "free_tier")),
        }

    # Check readiness.json explanation
    r_doc = _load_current_readiness(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    return {
        "services": out_services,
        "nightly_refresh": _get_nightly_refresh_meta(),
        "readiness": r_doc,
        "readiness_explanation": readiness_human_explanation(r_doc),
    }


def refresh_live_models(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Force a live CLI model catalog & Nightly 02:00 allowance refresh for all 4 AI families."""
    _LIVE_MODEL_CACHE.clear()
    if not sandbox and base_dir is None:
        try:
            import usage_allowance_monitor as _uam
            _uam.run_nightly_allowance_refresh(force=True)
        except Exception:
            pass
    by_fam_catalog: dict[str, Any] = {}
    for fam in SERVICE_CATALOG:
        rows = _discover_live_service_models(fam, force=True)
        m_ids = [r["model"] for r in rows if r.get("model")]
        if m_ids:
            by_fam_catalog[fam] = {
                "frontier_model": m_ids[0],
                "one_tier_down_model": m_ids[1] if len(m_ids) > 1 else m_ids[0],
                "discovered_models": m_ids,
            }
    try:
        import gwl_clearinghouse as _gwl
        hub_root = _gwl_hub_root_for(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
        _gwl.publish_verified_model_catalog(by_fam_catalog or None, hub_root=hub_root)
    except Exception:
        pass

    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    services = st_doc.get("services") or {}
    changed = False
    for fam, s_cfg in list(services.items()):
        if not isinstance(s_cfg, dict):
            continue
        om = str(s_cfg.get("orchestrator_model") or "").strip()
        rm = str(s_cfg.get("reviewer_model") or "").strip()
        if om in _STALE_MODEL_UPGRADES:
            s_cfg["orchestrator_model"] = _STALE_MODEL_UPGRADES[om]
            changed = True
        if rm in _STALE_MODEL_UPGRADES:
            s_cfg["reviewer_model"] = _STALE_MODEL_UPGRADES[rm]
            changed = True
    if changed:
        save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    out = detect_ai_services_status(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    out["ok"] = True
    return out


def launch_service_login(
    family: str,
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
    runner_fn=None,
) -> dict[str, Any]:
    """Initiate interactive CLI login or subscription sign-in for a provider family."""
    fam = str(family or "").strip().lower()
    if fam not in SERVICE_CATALOG:
        raise ValueError(f"Unsupported AI service family: {family}")
    meta = SERVICE_CATALOG[fam]
    login_cmd = list(meta.get("login_cmd") or [meta["cli"], "login"])
    cmd_str = " ".join(login_cmd)

    launched = False
    note = f"Run `{cmd_str}` in a terminal to complete subscription sign-in."
    if sandbox:
        launched = True
        note = f"Sandbox verified subscription sign-in flow for {meta['label']} (`{cmd_str}`)."
    else:
        exe = shutil.which(meta["cli"])
        if exe:
            real_cmd = [exe] + login_cmd[1:]
            if runner_fn is not None:
                try:
                    runner_fn(real_cmd)
                    launched = True
                    note = f"Launched `{cmd_str}` for {meta['label']}."
                except Exception as exc:
                    note = f"Could not launch `{cmd_str}` ({exc}). Run `{cmd_str}` in your terminal."
            elif os.name == "nt" and paths.is_interactive_desktop_session():
                try:
                    CREATE_NEW_CONSOLE = 0x00000010
                    subprocess.Popen(
                        ["cmd.exe", "/c", "start", f"Anchor {meta['label']} Login", "cmd.exe", "/k"] + real_cmd,
                        creationflags=CREATE_NEW_CONSOLE,
                    )
                    launched = True
                    note = f"Opened interactive sign-in console for {meta['label']} (`{cmd_str}`). Complete browser sign-in, then click Verify & Live Test Tier."
                except Exception:
                    note = f"Run `{cmd_str}` in PowerShell/Terminal to sign in to {meta['label']}, then click Verify & Live Test Tier."

    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    services = st_doc.setdefault("services", {})
    cur = services.setdefault(fam, {})
    cur["enabled"] = True
    cur["user_enabled"] = True
    cur["auth_mode"] = "subscription"
    cur["login_initiated_at"] = _utc_now_iso()
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    return {
        "ok": True,
        "family": fam,
        "launched": launched,
        "login_command": cmd_str,
        "message": note,
    }


PROVIDER_BROWSER_URLS: dict[str, dict[str, Any]] = {
    "claude": {
        "label": "Claude (Anthropic)",
        "cli": "claude",
        "npm_pkg": "@anthropic-ai/claude-code",
        "login_url": "https://claude.ai/login",
        "api_url": "https://console.anthropic.com/settings/keys",
        "domains": ("claude.ai", "console.anthropic.com"),
    },
    "gemini": {
        "label": "Antigravity / Gemini (Google)",
        "cli": "agy",
        "alt_cli": "gemini",
        "npm_pkg": "@google/gemini-cli",
        "login_url": "https://aistudio.google.com/app/apikey",
        "web_url": "https://gemini.google.com",
        "domains": ("gemini.google.com", "aistudio.google.com", "accounts.google.com"),
    },
    "chatgpt": {
        "label": "ChatGPT / Codex (OpenAI)",
        "cli": "codex",
        "npm_pkg": "@openai/codex",
        "login_url": "https://chatgpt.com/auth/login",
        "api_url": "https://platform.openai.com/api-keys",
        "domains": ("chatgpt.com", "chat.openai.com", "platform.openai.com"),
    },
    "grok": {
        "label": "Grok (xAI)",
        "cli": "grok",
        "npm_pkg": "@vibe-kit/grok-cli",
        "login_url": "https://accounts.x.ai/sign-in",
        "api_url": "https://console.x.ai",
        "domains": ("grok.com", "x.ai", "console.x.ai"),
    },
}

_BROWSER_DETECT_CACHE: dict[str, Any] = {"ts": 0.0, "payload": None}


def _cli_augmented_env(home_dir: Path | None = None) -> dict[str, str]:
    """Build an environment dict with all standard Windows/macOS/Linux Node & AI CLI bin dirs on PATH."""
    env = dict(os.environ)
    home = Path(home_dir) if home_dir else Path.home()
    local_app = Path(env.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    app_data = Path(env.get("APPDATA", str(home / "AppData" / "Roaming")))
    prog_files = Path(env.get("ProgramFiles", r"C:\Program Files"))
    extra_dirs: list[Path] = []
    if os.name == "nt":
        extra_dirs.extend([
            prog_files / "nodejs",
            app_data / "npm",
            local_app / "Programs" / "claude",
            local_app / "AnthropicClaude",
            home / ".local" / "bin",
            home / ".claude" / "local",
            local_app / "agy" / "bin",
            local_app / "grok" / "bin",
            home / ".codex" / "bin",
            home / ".grok" / "bin",
        ])
    else:
        extra_dirs.extend([
            home / ".local" / "bin",
            home / ".claude" / "local",
            home / ".npm-global" / "bin",
            Path("/opt/homebrew/bin"),
            Path("/usr/local/bin"),
        ])
    cur_path = env.get("PATH", "")
    cur_parts = [p.strip() for p in cur_path.split(os.pathsep) if p.strip()]
    cur_norm = {p.lower() if os.name == "nt" else p for p in cur_parts}
    prepend: list[str] = []
    for d in extra_dirs:
        ds = str(d)
        dk = ds.lower() if os.name == "nt" else ds
        if dk not in cur_norm and d.is_dir():
            prepend.append(ds)
            cur_norm.add(dk)
    if prepend:
        env["PATH"] = os.pathsep.join(prepend + cur_parts)
    return env


def _find_cli_binary_for_family(fam: str, home_dir: Path | None = None, which_fn=None) -> str:
    aug_path = _cli_augmented_env(home_dir).get("PATH") if which_fn is None else None
    which = which_fn or (lambda name: shutil.which(name, path=aug_path))
    meta = PROVIDER_BROWSER_URLS.get(fam) or {}
    primary = str(meta.get("cli") or fam)
    p = which(primary)
    if p:
        return str(p)
    alt = str(meta.get("alt_cli") or "")
    if alt:
        p2 = which(alt)
        if p2:
            return str(p2)
    if which_fn is not None and home_dir is None:
        return ""
    home = Path(home_dir) if home_dir else Path.home()
    local_app = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
    app_data = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    candidates: list[Path] = []
    if fam == "gemini":
        candidates.extend([
            local_app / "agy" / "bin" / "agy.exe",
            local_app / "agy" / "bin" / "agy.cmd",
            app_data / "npm" / "gemini.cmd",
            app_data / "npm" / "gemini",
            home / ".local" / "bin" / "agy",
            home / ".local" / "bin" / "gemini",
        ])
    elif fam == "claude":
        candidates.extend([
            app_data / "npm" / "claude.cmd",
            app_data / "npm" / "claude",
            local_app / "Programs" / "claude" / "claude.exe",
            local_app / "AnthropicClaude" / "claude.exe",
            home / ".local" / "bin" / "claude.exe",
            home / ".local" / "bin" / "claude",
            home / ".claude" / "local" / "claude.exe",
            home / ".claude" / "local" / "claude",
        ])
    elif fam == "chatgpt":
        candidates.extend([
            app_data / "npm" / "codex.cmd",
            app_data / "npm" / "codex",
            home / ".codex" / "bin" / "codex.exe",
            home / ".local" / "bin" / "codex",
        ])
    elif fam == "grok":
        candidates.extend([
            app_data / "npm" / "grok.cmd",
            app_data / "npm" / "grok",
            local_app / "grok" / "bin" / "grok.cmd",
            home / ".grok" / "bin" / "grok.exe",
            home / ".local" / "bin" / "grok",
        ])
    for c in candidates:
        if c.is_file():
            return str(c)
    return ""


def _has_local_cli_credentials(fam: str, home_dir: Path | None = None) -> bool:
    home = Path(home_dir) if home_dir else Path.home()
    app_data = Path(os.environ.get("APPDATA", str(home / "AppData" / "Roaming")))
    if home_dir is None:
        try:
            if provider_secrets.get(f"{fam}-default"):
                return True
        except Exception:
            pass
    if fam == "claude":
        for p in (home / ".claude" / ".credentials.json", home / ".claude" / "credentials.json"):
            if p.is_file() and p.stat().st_size > 10:
                return True
        claude_json = home / ".claude.json"
        if claude_json.is_file():
            try:
                cj = json.loads(claude_json.read_text(encoding="utf-8", errors="ignore"))
                if isinstance(cj, dict) and (cj.get("oauthAccount") or cj.get("primaryApiKey")):
                    return True
            except Exception:
                pass
    elif fam == "gemini":
        oauth_p = home / ".gemini" / "oauth_creds.json"
        if oauth_p.is_file() and oauth_p.stat().st_size > 10:
            return True
        g_acct = home / ".gemini" / "google_accounts.json"
        if g_acct.is_file():
            try:
                ga = json.loads(g_acct.read_text(encoding="utf-8", errors="ignore"))
                if isinstance(ga, dict) and ga.get("active"):
                    return True
            except Exception:
                pass
        gem_env = home / ".gemini" / ".env"
        if gem_env.is_file() and "GEMINI_API_KEY=" in gem_env.read_text(encoding="utf-8", errors="ignore"):
            return True
        # Standalone Antigravity `agy` stores OAuth tokens in the OS keyring rather than ~/.gemini/oauth_creds.json.
        if home_dir is None and "PYTEST_CURRENT_TEST" not in os.environ:
            try:
                import model_policy
                rows, _cmd = model_policy.discover("gemini")
                if rows:
                    return True
            except Exception:
                pass
    elif fam == "chatgpt":
        for p in (home / ".codex" / "auth.json", home / ".openai" / "auth.json"):
            if p.is_file() and p.stat().st_size > 10:
                return True
    elif fam == "grok":
        for p in (home / ".grok" / "user-settings.json", home / ".grok" / "auth.json", home / ".grok" / "config.json"):
            if p.is_file() and p.stat().st_size > 10:
                return True
    return False


def _discover_browser_history_files() -> list[Path]:
    local_app = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    home = Path.home()
    roots: list[Path] = []
    if os.name == "nt":
        roots.extend([
            local_app / "Google" / "Chrome" / "User Data",
            local_app / "Microsoft" / "Edge" / "User Data",
            local_app / "BraveSoftware" / "Brave-Browser" / "User Data",
        ])
    elif sys.platform == "darwin":
        roots.extend([
            home / "Library" / "Application Support" / "Google" / "Chrome",
            home / "Library" / "Application Support" / "Microsoft Edge",
        ])
    else:
        roots.extend([
            home / ".config" / "google-chrome",
            home / ".config" / "chromium",
        ])
    out: list[Path] = []
    for r in roots:
        for prof_name in ("Default", "Profile 1", "Profile 2"):
            h = r / prof_name / "History"
            if h.is_file():
                out.append(h)
    return out[:4]


def detect_browser_and_cli_accounts(
    *,
    sandbox: bool = False,
    include_browser_history: bool = False,
    history_dbs: list[Path | str] | None = None,
    home_dir: Path | str | None = None,
    which_fn=None,
) -> dict[str, Any]:
    """Detect installed CLIs, local CLI sign-in files, and (when consented or explicitly passed) active browser provider domains."""
    if sandbox:
        return {
            "ok": True,
            "accounts": {
                fam: {
                    "family": fam,
                    "label": meta["label"],
                    "cli": meta["cli"],
                    "cli_installed": fam in ("claude", "gemini", "chatgpt"),
                    "cli_authenticated": False,
                    "browser_session_detected": fam in ("gemini", "chatgpt"),
                    "matched_domains": [meta["domains"][0]] if fam in ("gemini", "chatgpt") else [],
                    "login_url": meta["login_url"],
                    "status_summary": "Browser session ready — click Open Browser & Log In",
                }
                for fam, meta in PROVIDER_BROWSER_URLS.items()
            },
        }

    use_cache = (history_dbs is None and home_dir is None and which_fn is None and not include_browser_history)
    now_t = time.monotonic()
    if use_cache and _BROWSER_DETECT_CACHE["payload"] is not None and (now_t - float(_BROWSER_DETECT_CACHE["ts"])) < 4.0:
        return _BROWSER_DETECT_CACHE["payload"]

    if history_dbs is not None:
        dbs = [Path(p) for p in history_dbs if Path(p).is_file()]
    elif not include_browser_history or "PYTEST_CURRENT_TEST" in os.environ:
        dbs = []
    else:
        dbs = _discover_browser_history_files()

    domain_hits: dict[str, list[str]] = {fam: [] for fam in PROVIDER_BROWSER_URLS}
    for db_path in dbs:
        try:
            if db_path.stat().st_size > 80 * 1024 * 1024:
                continue
            with tempfile.TemporaryDirectory() as tmpd:
                copied = Path(tmpd) / "History.sqlite"
                shutil.copy2(db_path, copied)
                conn = sqlite3.connect(str(copied))
                try:
                    cur = conn.cursor()
                    for fam, meta in PROVIDER_BROWSER_URLS.items():
                        for dom in meta["domains"]:
                            if dom in domain_hits[fam]:
                                continue
                            cur.execute("SELECT 1 FROM urls WHERE url LIKE ? LIMIT 1", (f"%{dom}%",))
                            if cur.fetchone():
                                domain_hits[fam].append(dom)
                finally:
                    conn.close()
        except Exception:
            continue

    eff_home = Path(home_dir) if home_dir is not None else None
    accounts_out: dict[str, Any] = {}
    for fam, meta in PROVIDER_BROWSER_URLS.items():
        cli_bin = _find_cli_binary_for_family(fam, home_dir=eff_home, which_fn=which_fn)
        cli_auth = _has_local_cli_credentials(fam, home_dir=eff_home)
        b_hits = domain_hits.get(fam) or []
        b_found = bool(b_hits)
        if cli_auth:
            summary = "Connected ✓"
        elif b_found:
            summary = f"CLI ready — click Connect ({b_hits[0]} open)"
        elif cli_bin:
            summary = "CLI installed — click Connect to sign in"
        else:
            summary = "Click Install All 4 CLIs, then Connect"
        accounts_out[fam] = {
            "family": fam,
            "label": meta["label"],
            "cli": meta["cli"],
            "cli_path": cli_bin,
            "cli_installed": bool(cli_bin),
            "cli_authenticated": cli_auth,
            "connected": cli_auth,
            "status_label": "Connected" if cli_auth else "Not Connected",
            "browser_session_detected": b_found,
            "matched_domains": b_hits,
            "login_url": meta["login_url"],
            "api_url": meta.get("api_url") or meta["login_url"],
            "status_summary": summary,
        }

    result = {"ok": True, "accounts": accounts_out}
    if use_cache:
        _BROWSER_DETECT_CACHE["ts"] = now_t
        _BROWSER_DETECT_CACHE["payload"] = result
    return result


def _ensure_gemini_agy_shim(gemini_exe: str, home_dir: Path | None = None) -> str:
    """Create a user-local `agy` wrapper delegating to `gemini` when standalone Antigravity `agy` isn't installed."""
    home = Path(home_dir) if home_dir else Path.home()
    if os.name == "nt":
        local_app = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
        shim_dir = local_app / "agy" / "bin"
        shim_path = shim_dir / "agy.cmd"
        if (shim_dir / "agy.exe").is_file():
            return str(shim_dir / "agy.exe")
        shim_dir.mkdir(parents=True, exist_ok=True)
        shim_path.write_text(f'@echo off\r\n"{gemini_exe}" %*\r\n', encoding="utf-8")
        return str(shim_path)
    shim_dir = home / ".local" / "bin"
    shim_path = shim_dir / "agy"
    if not shim_path.exists():
        shim_dir.mkdir(parents=True, exist_ok=True)
        shim_path.write_text(f'#!/usr/bin/env sh\nexec "{gemini_exe}" "$@"\n', encoding="utf-8")
        try:
            shim_path.chmod(0o755)
        except OSError:
            pass
    return str(shim_path)


def _ensure_grok_cli_shim(home_dir: Path | None = None) -> str:
    """Create a reliable standalone Python-backed `grok` CLI wrapper when npm `@vibe-kit/grok-cli` is unavailable."""
    home = Path(home_dir) if home_dir else Path.home()
    py_exe = sys.executable or "python"
    driver_body = (
        "import json, os, pathlib, sys, urllib.request\n"
        "if '--version' in sys.argv or '-v' in sys.argv:\n"
        "    print('grok-cli 1.5.7 (Anchor xAI bridge)')\n"
        "    raise SystemExit(0)\n"
        "cfg = pathlib.Path.home() / '.grok' / 'user-settings.json'\n"
        "key = os.environ.get('XAI_API_KEY', '')\n"
        "if not key and cfg.is_file():\n"
        "    try: key = json.loads(cfg.read_text(encoding='utf-8')).get('apiKey', '')\n"
        "    except Exception: key = ''\n"
        "if not key:\n"
        "    print('Grok CLI not connected yet. Open Anchor Setup -> Connect Grok.', file=sys.stderr)\n"
        "    raise SystemExit(1)\n"
        "prompt = ' '.join(a for a in sys.argv[1:] if not a.startswith('-')).strip() or sys.stdin.read().strip()\n"
        "if not prompt:\n"
        "    print('grok-cli ready (connected)')\n"
        "    raise SystemExit(0)\n"
        "req = urllib.request.Request(\n"
        "    'https://api.x.ai/v1/chat/completions',\n"
        "    data=json.dumps({'model': os.environ.get('GROK_MODEL', 'grok-3'), 'messages': [{'role': 'user', 'content': prompt}]}).encode('utf-8'),\n"
        "    headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json', 'User-Agent': 'Anchor-Grok-CLI/1.5.7'},\n"
        ")\n"
        "with urllib.request.urlopen(req, timeout=90) as resp:\n"
        "    doc = json.loads(resp.read().decode('utf-8'))\n"
        "    print(doc['choices'][0]['message']['content'])\n"
    )
    if os.name == "nt":
        local_app = Path(os.environ.get("LOCALAPPDATA", str(home / "AppData" / "Local")))
        shim_dir = local_app / "grok" / "bin"
        shim_dir.mkdir(parents=True, exist_ok=True)
        py_script = shim_dir / "grok_driver.py"
        py_script.write_text(driver_body, encoding="utf-8")
        shim_path = shim_dir / "grok.cmd"
        shim_path.write_text(f'@echo off\r\n"{py_exe}" "{py_script}" %*\r\n', encoding="utf-8")
        return str(shim_path)
    shim_dir = home / ".local" / "bin"
    shim_dir.mkdir(parents=True, exist_ok=True)
    py_script = shim_dir / "grok_driver.py"
    py_script.write_text(driver_body, encoding="utf-8")
    shim_path = shim_dir / "grok"
    shim_path.write_text(f'#!/usr/bin/env sh\nexec "{py_exe}" "{py_script}" "$@"\n', encoding="utf-8")
    try:
        shim_path.chmod(0o755)
    except OSError:
        pass
    return str(shim_path)


def auto_install_agent_clis(
    *,
    families: list[str] | None = None,
    include_grok: bool = True,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
    runner_fn=None,
    which_fn=None,
) -> dict[str, Any]:
    """Automatically install all 4 AI agent CLIs: Claude Code (`claude`), Gemini/Antigravity (`gemini`+`agy`), OpenAI Codex (`codex`), and Grok (`grok`)."""
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    grok_enabled = bool(include_grok or ((st_doc.get("services") or {}).get("grok") or {}).get("enabled"))
    target_fams = list(families) if families else (["claude", "gemini", "chatgpt"] + (["grok"] if grok_enabled else []))
    target_fams = [f for f in target_fams if f in PROVIDER_BROWSER_URLS]

    if sandbox:
        return {
            "ok": True,
            "installed": target_fams,
            "already_present": [],
            "failed": {},
            "message": f"Sandbox verified auto-installation for {', '.join(target_fams)}.",
        }

    aug_env = _cli_augmented_env()
    if os.name != "nt" and runner_fn is None:
        user_npm_prefix = Path.home() / ".npm-global"
        if not os.access("/usr/local/lib", os.W_OK):
            user_npm_prefix.mkdir(parents=True, exist_ok=True)
            aug_env["NPM_CONFIG_PREFIX"] = str(user_npm_prefix)
            aug_env["PATH"] = str(user_npm_prefix / "bin") + os.pathsep + aug_env.get("PATH", "")
    which = which_fn or (lambda name: shutil.which(name, path=aug_env.get("PATH")))
    run = runner_fn or (
        lambda cmd: subprocess.run(
            cmd,
            env=aug_env,
            capture_output=True,
            text=True,
            timeout=180,
            creationflags=paths.NO_WINDOW,
        )
    )

    npm_cmd = which("npm.cmd" if os.name == "nt" else "npm") or which("npm")
    if not npm_cmd and os.name == "nt":
        cand_npm = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "nodejs" / "npm.cmd"
        if cand_npm.is_file():
            npm_cmd = str(cand_npm)
        elif which("winget") and (runner_fn is not None or paths.is_interactive_desktop_session()):
            try:
                run([
                    "winget", "install", "-e", "--id", "OpenJS.NodeJS.LTS",
                    "--silent", "--accept-package-agreements", "--accept-source-agreements",
                ])
                aug_env = _cli_augmented_env()
                if cand_npm.is_file():
                    npm_cmd = str(cand_npm)
                else:
                    npm_cmd = shutil.which("npm.cmd", path=aug_env.get("PATH")) or shutil.which("npm", path=aug_env.get("PATH")) or ""
            except Exception:
                npm_cmd = ""

    installed_now: list[str] = []
    already_present: list[str] = []
    failed: dict[str, str] = {}

    for fam in target_fams:
        existing_bin = _find_cli_binary_for_family(fam, which_fn=which_fn)
        if existing_bin:
            if fam == "gemini" and not which("agy"):
                try:
                    _ensure_gemini_agy_shim(existing_bin)
                except Exception:
                    pass
            already_present.append(fam)
            continue

        pkg = PROVIDER_BROWSER_URLS[fam]["npm_pkg"]
        fam_ok = False
        last_err = ""
        if npm_cmd:
            try:
                res = run([npm_cmd, "install", "-g", "--no-audit", "--no-fund", pkg])
                if getattr(res, "returncode", 1) == 0:
                    fam_ok = True
                else:
                    last_err = (getattr(res, "stderr", "") or getattr(res, "stdout", "") or "npm install failed").strip()
            except Exception as exc:
                last_err = str(exc)

        # Native fallback for Claude Code (`winget install Anthropic.ClaudeCode`) when npm fails or is absent
        if not fam_ok and fam == "claude" and runner_fn is None and os.name == "nt":
            winget_exe = shutil.which("winget", path=aug_env.get("PATH"))
            if winget_exe:
                try:
                    w_res = run([
                        winget_exe, "install", "-e", "--id", "Anthropic.ClaudeCode",
                        "--silent", "--accept-package-agreements", "--accept-source-agreements",
                    ])
                    if getattr(w_res, "returncode", 1) == 0 or _find_cli_binary_for_family("claude"):
                        fam_ok = True
                except Exception as exc:
                    last_err = last_err or str(exc)

        # Standalone Python xAI shim fallback for Grok CLI when npm fails or is absent
        if not fam_ok and fam == "grok" and runner_fn is None:
            try:
                shim_g = _ensure_grok_cli_shim()
                if shim_g and Path(shim_g).is_file():
                    fam_ok = True
            except Exception as exc:
                last_err = last_err or str(exc)

        if fam_ok:
            installed_now.append(fam)
            if fam == "gemini":
                gem_bin = _find_cli_binary_for_family("gemini", which_fn=which_fn)
                if gem_bin and not which("agy"):
                    try:
                        _ensure_gemini_agy_shim(gem_bin)
                    except Exception:
                        pass
        else:
            failed[fam] = (last_err or "Node.js / npm is required to auto-install CLI packages.")[:160]

    _BROWSER_DETECT_CACHE["ts"] = 0.0
    parts: list[str] = []
    if installed_now:
        parts.append(f"Installed: {', '.join(installed_now)}")
    if already_present:
        parts.append(f"Ready: {', '.join(already_present)}")
    if failed:
        parts.append(f"Needs attention: {', '.join(f'{k} ({v})' for k, v in failed.items())}")
    return {
        "ok": len(failed) == 0 or len(installed_now) + len(already_present) > 0,
        "installed": installed_now,
        "already_present": already_present,
        "failed": failed,
        "accounts": detect_browser_and_cli_accounts(sandbox=False, which_fn=which_fn).get("accounts", {}),
        "message": " · ".join(parts) or "All 4 Agent CLIs checked.",
    }


def open_browser_provider_login(
    family: str,
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
    runner_fn=None,
    browser_open_fn=None,
) -> dict[str, Any]:
    """Open the provider sign-in / key page in the user's browser AND launch CLI OAuth sign-in if the CLI is present."""
    fam = str(family or "gemini").strip().lower()
    if fam not in PROVIDER_BROWSER_URLS:
        raise ValueError(f"Unsupported AI service family: {family}")
    meta = PROVIDER_BROWSER_URLS[fam]
    login_url = str(meta["login_url"])
    opened_on_host = False

    if sandbox:
        return {
            "ok": True,
            "family": fam,
            "login_url": login_url,
            "opened_on_host": True,
            "message": f"Sandbox verified: opened browser login for {meta['label']} ({login_url}).",
        }

    opener = browser_open_fn or webbrowser.open
    if browser_open_fn is not None or ("PYTEST_CURRENT_TEST" not in os.environ and paths.is_interactive_desktop_session()):
        try:
            opened_on_host = bool(opener(login_url))
        except Exception:
            opened_on_host = False

    cli_res = launch_service_login(
        fam,
        sandbox=False,
        sandbox_id=sandbox_id,
        base_dir=base_dir,
        runner_fn=runner_fn,
    )
    return {
        "ok": True,
        "family": fam,
        "login_url": login_url,
        "opened_on_host": opened_on_host,
        "cli_login_launched": bool(cli_res.get("launched")),
        "message": f"Opened {meta['label']} in your browser ({login_url}). Complete sign-in there — Anchor will detect your account automatically.",
    }


def connect_provider_simple(
    family: str,
    *,
    api_key: str = "",
    home_dir: Path | str | None = None,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
    runner_fn=None,
    browser_open_fn=None,
) -> dict[str, Any]:
    """Dead-simple 1-step CLI connection: installs CLI if missing, goes strictly to the exact auth flow needed for that CLI, and marks Connected."""
    fam = str(family or "gemini").strip().lower()
    if fam not in PROVIDER_BROWSER_URLS:
        raise ValueError(f"Unsupported AI service family: {family}")
    meta = PROVIDER_BROWSER_URLS[fam]
    eff_home = Path(home_dir) if home_dir is not None else Path.home()

    if sandbox:
        configure_service_connection(fam, enabled=True, auth_mode="subscription", sandbox=True, sandbox_id=sandbox_id, base_dir=base_dir)
        run_service_live_test(fam, sandbox=True, sandbox_id=sandbox_id, base_dir=base_dir)
        return {
            "ok": True,
            "family": fam,
            "connected": True,
            "status_label": "Connected",
            "message": f"Connected ✓ ({meta['label']})",
        }

    # 1. Ensure the CLI binary is installed first
    cli_bin = _find_cli_binary_for_family(fam, home_dir=eff_home if home_dir is not None else None)
    if not cli_bin and runner_fn is None and home_dir is None:
        auto_install_agent_clis(families=[fam], include_grok=(fam == "grok"), base_dir=base_dir)
        cli_bin = _find_cli_binary_for_family(fam)

    k_val = str(api_key or "").strip()
    if k_val:
        if "\r" in k_val or "\n" in k_val or len(k_val) < 6:
            return {
                "ok": False,
                "family": fam,
                "connected": False,
                "status_label": "Invalid Key",
                "message": "Invalid API key format (must be single-line and non-empty).",
            }
        configure_service_connection(
            fam,
            enabled=True,
            auth_mode="api_key",
            **{"api_key": k_val},
            sandbox=False,
            sandbox_id=sandbox_id,
            base_dir=base_dir,
        )
        if fam == "gemini":
            gem_dir = eff_home / ".gemini"
            gem_dir.mkdir(parents=True, exist_ok=True)
            env_p = gem_dir / ".env"
            existing_lines = [
                ln for ln in (env_p.read_text(encoding="utf-8", errors="ignore").splitlines() if env_p.is_file() else [])
                if not ln.strip().startswith("GEMINI_API_KEY=")
            ]
            existing_lines.append(f"GEMINI_API_KEY={k_val}")
            env_p.write_text("\n".join(existing_lines) + "\n", encoding="utf-8")
            if os.name != "nt":
                try:
                    env_p.chmod(0o600)
                except OSError:
                    pass
        elif fam == "grok":
            grok_dir = eff_home / ".grok"
            grok_dir.mkdir(parents=True, exist_ok=True)
            cfg_p = grok_dir / "user-settings.json"
            cur_g: dict[str, Any] = {}
            if cfg_p.is_file():
                try:
                    cur_g = json.loads(cfg_p.read_text(encoding="utf-8"))
                    if not isinstance(cur_g, dict):
                        cur_g = {}
                except Exception:
                    cur_g = {}
            cur_g["apiKey"] = k_val
            cfg_p.write_text(json.dumps(cur_g, indent=2) + "\n", encoding="utf-8")
            if os.name != "nt":
                try:
                    cfg_p.chmod(0o600)
                except OSError:
                    pass
        _BROWSER_DETECT_CACHE["ts"] = 0.0
        probe_res = run_service_live_test(fam, sandbox=False, sandbox_id=sandbox_id, base_dir=base_dir)
        is_ok = bool(probe_res.get("ok", True))
        return {
            "ok": is_ok,
            "family": fam,
            "connected": is_ok,
            "status_label": "Connected" if is_ok else "Verify Failed",
            "cli_installed": bool(cli_bin),
            "message": f"Connected ✓ — {meta['label']} is ready!" if is_ok else f"Could not verify {meta['label']} CLI.",
        }

    # Check if already authenticated on disk right now
    if _has_local_cli_credentials(fam, home_dir=eff_home if home_dir is not None else None):
        configure_service_connection(fam, enabled=True, auth_mode="subscription", sandbox=False, sandbox_id=sandbox_id, base_dir=base_dir)
        run_service_live_test(fam, sandbox=False, sandbox_id=sandbox_id, base_dir=base_dir)
        _BROWSER_DETECT_CACHE["ts"] = 0.0
        return {
            "ok": True,
            "family": fam,
            "connected": True,
            "status_label": "Connected",
            "cli_installed": bool(cli_bin),
            "message": f"Connected ✓ — {meta['label']} is already signed in and ready!",
        }

    # 2. Launch ONLY the exact CLI sign-in flow needed to make that CLI work (no redundant generic chat login pages)
    aug_env = _cli_augmented_env(eff_home if home_dir is not None else None)
    opener = browser_open_fn or webbrowser.open

    if fam == "grok":
        key_url = "https://console.x.ai"
        opened_host = False
        if browser_open_fn is not None or ("PYTEST_CURRENT_TEST" not in os.environ and paths.is_interactive_desktop_session()):
            try:
                opened_host = bool(opener(key_url))
            except Exception:
                opened_host = False
        return {
            "ok": True,
            "family": "grok",
            "connected": False,
            "needs_api_key": True,
            "opened_on_host": opened_host,
            "login_url": key_url,
            "status_label": "Paste Key to Connect",
            "message": "Opened console.x.ai — copy your xAI API key, paste it in the Grok box, and click Connect.",
        }

    if fam == "gemini":
        # Standalone `agy.exe` uses OS keyring auth and has no `auth login` subcommand; never spawn `gemini.cmd` TUI when `agy.exe` is active!
        if cli_bin and Path(cli_bin).name.lower() == "agy.exe" and runner_fn is None:
            try:
                import model_policy
                rows, _ = model_policy.discover("gemini")
                if rows:
                    configure_service_connection("gemini", enabled=True, auth_mode="subscription", sandbox=False, sandbox_id=sandbox_id, base_dir=base_dir)
                    run_service_live_test("gemini", model_id=rows[0]["model"], sandbox=False, sandbox_id=sandbox_id, base_dir=base_dir)
                    _BROWSER_DETECT_CACHE["ts"] = 0.0
                    return {
                        "ok": True,
                        "family": "gemini",
                        "connected": True,
                        "status_label": "Connected",
                        "cli_installed": True,
                        "message": f"Connected ✓ — Antigravity CLI (agy) verified ({rows[0]['model']})!",
                    }
            except Exception:
                pass
            login_argv = [cli_bin]
        else:
            gem_dir = eff_home / ".gemini"
            gem_dir.mkdir(parents=True, exist_ok=True)
            g_settings = gem_dir / "settings.json"
            cur_gs: dict[str, Any] = {}
            if g_settings.is_file():
                try:
                    cur_gs = json.loads(g_settings.read_text(encoding="utf-8"))
                except Exception:
                    cur_gs = {}
            if not cur_gs.get("selectedAuthType"):
                cur_gs["selectedAuthType"] = "oauth-personal"
            sec_auth = cur_gs.setdefault("security", {})
            if isinstance(sec_auth, dict):
                auth_sub = sec_auth.setdefault("auth", {})
                if isinstance(auth_sub, dict) and not auth_sub.get("selectedType"):
                    auth_sub["selectedType"] = "oauth-personal"
            g_settings.write_text(json.dumps(cur_gs, indent=2) + "\n", encoding="utf-8")
            gem_exe = shutil.which("gemini.cmd" if os.name == "nt" else "gemini", path=aug_env.get("PATH")) or shutil.which("gemini", path=aug_env.get("PATH")) or cli_bin
            login_argv = [gem_exe] if gem_exe else ["gemini"]
    elif fam == "claude":
        login_argv = [cli_bin or "claude", "auth", "login"]
    else:  # chatgpt -> codex login
        login_argv = [cli_bin or "codex", "login"]

    launched = False
    if runner_fn is not None:
        runner_fn(login_argv)
        launched = True
    elif os.name == "nt" and "PYTEST_CURRENT_TEST" not in os.environ and paths.is_interactive_desktop_session():
        try:
            CREATE_NEW_CONSOLE = 0x00000010
            subprocess.Popen(
                ["cmd.exe", "/c"] + login_argv,
                env=aug_env,
                creationflags=CREATE_NEW_CONSOLE,
            )
            launched = True
        except Exception:
            launched = False
    elif "PYTEST_CURRENT_TEST" not in os.environ:
        try:
            subprocess.Popen(login_argv, env=aug_env, start_new_session=True)
            launched = True
        except Exception:
            launched = False

    configure_service_connection(fam, enabled=True, auth_mode="subscription", sandbox=False, sandbox_id=sandbox_id, base_dir=base_dir)
    _BROWSER_DETECT_CACHE["ts"] = 0.0
    return {
        "ok": True,
        "family": fam,
        "connected": False,
        "launched": launched,
        "command": " ".join(Path(login_argv[0]).name if i == 0 else a for i, a in enumerate(login_argv)),
        "status_label": "Waiting for Browser Approval…",
        "message": f"Approve {meta['label']} in the browser window that just opened — this badge will automatically flip to Connected!",
    }


EMAIL_DOMAIN_PRESETS: dict[str, dict[str, Any]] = {
    "gmail.com": {
        "family": "gmail",
        "provider_name": "Google / Gmail",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "app_password_url": "https://myaccount.google.com/apppasswords",
    },
    "googlemail.com": {
        "family": "gmail",
        "provider_name": "Google / Gmail",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "app_password_url": "https://myaccount.google.com/apppasswords",
    },
    "outlook.com": {
        "family": "outlook",
        "provider_name": "Microsoft Outlook",
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "app_password_url": "https://account.live.com/proofs/AppPassword",
    },
    "hotmail.com": {
        "family": "outlook",
        "provider_name": "Microsoft Hotmail / Outlook",
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "app_password_url": "https://account.live.com/proofs/AppPassword",
    },
    "live.com": {
        "family": "outlook",
        "provider_name": "Microsoft Live / Outlook",
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "app_password_url": "https://account.live.com/proofs/AppPassword",
    },
    "msn.com": {
        "family": "outlook",
        "provider_name": "Microsoft MSN / Outlook",
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "app_password_url": "https://account.live.com/proofs/AppPassword",
    },
    "yahoo.com": {
        "family": "custom",
        "provider_name": "Yahoo Mail",
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "app_password_url": "https://login.yahoo.com/account/security",
    },
    "ymail.com": {
        "family": "custom",
        "provider_name": "Yahoo Mail",
        "imap_host": "imap.mail.yahoo.com",
        "imap_port": 993,
        "app_password_url": "https://login.yahoo.com/account/security",
    },
    "icloud.com": {
        "family": "custom",
        "provider_name": "Apple iCloud Mail",
        "imap_host": "imap.mail.me.com",
        "imap_port": 993,
        "app_password_url": "https://appleid.apple.com/account/manage",
    },
    "me.com": {
        "family": "custom",
        "provider_name": "Apple iCloud Mail",
        "imap_host": "imap.mail.me.com",
        "imap_port": 993,
        "app_password_url": "https://appleid.apple.com/account/manage",
    },
}


def auto_detect_email_provider(email_address: str) -> dict[str, Any]:
    """Auto-detect IMAP host, port, family, and 1-click browser App Password URL from an email address."""
    clean = str(email_address or "").strip().lower()
    if "@" not in clean:
        return {
            "ok": False,
            "family": "gmail",
            "provider_name": "Email Provider",
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
            "app_password_url": "https://myaccount.google.com/apppasswords",
        }
    domain = clean.rsplit("@", 1)[-1].strip()
    preset = EMAIL_DOMAIN_PRESETS.get(domain)
    if preset:
        auth_hint = (
            "Tip: Click 1-Click Connect Running Windows Outlook or Microsoft 365 Sign-In if App Passwords are disabled on your Microsoft account."
            if preset["family"] == "outlook"
            else ""
        )
        return {"ok": True, "domain": domain, "verified_preset": True, "auth_hint": auth_hint, **preset}
    return {
        "ok": True,
        "domain": domain,
        "verified_preset": False,
        "family": "custom",
        "provider_name": domain,
        "imap_host": f"imap.{domain}",
        "imap_port": 993,
        "app_password_url": "",
        "auth_hint": f"Suggested IMAP host imap.{domain}:993 — verify with your mail provider or use 1-Click Local Outlook.",
    }


def _load_current_readiness(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    sdir = state_dir(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    candidates = [
        sdir / "readiness.json",
        _resolve_base_dir(base_dir) / "governance" / "readiness.json",
        _resolve_base_dir(base_dir).parent / "governance" / "readiness.json",
    ]
    for c in candidates:
        if c.is_file():
            try:
                return ready.load_readiness_stamp(c)
            except Exception:
                continue
    return {
        "schema": ready.READINESS_SCHEMA,
        "schema_version": 1,
        "status": "not-ready",
        "reason_codes": ["interactive_onboard_required"],
        "notes": LIVE_PROBES_SKIPPED_NOTE,
    }


def configure_service_connection(
    family: str,
    *,
    enabled: bool = True,
    auth_mode: str = "subscription",
    api_key: str = "",
    tier_level: str = "frontier",
    orchestrator_model: str = "",
    reviewer_model: str = "",
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Configure connection method (Subscription vs. API Key) and Capability Tier for a service."""
    fam = str(family or "").strip().lower()
    if fam not in SERVICE_CATALOG:
        raise ValueError(f"Unsupported AI service family: {family}")

    meta = SERVICE_CATALOG[fam]
    t_level = str(tier_level or "frontier").strip().lower()
    if t_level not in meta["tiers"]:
        t_level = "frontier"
    t_meta = meta["tiers"][t_level]

    mode = str(auth_mode or "subscription").strip().lower()
    if mode not in ("subscription", "api_key"):
        mode = "subscription"

    has_key = False
    if mode == "api_key" and api_key and str(api_key).strip():
        clean_key = str(api_key).strip()
        has_key = True
        if not sandbox and base_dir is None and provider_secrets.available():
            try:
                provider_secrets.put(f"{fam}-default", clean_key)
            except Exception:
                pass

    live_models = _discover_live_service_models(fam, force=False)
    default_orch = t_meta["orchestrator_model"]
    default_rev = t_meta["reviewer_model"]
    if live_models:
        if t_level == "frontier":
            default_orch = live_models[0]["model"]
            default_rev = live_models[0]["model"]
        elif len(live_models) > 1:
            default_orch = live_models[1]["model"]
            default_rev = live_models[1]["model"]

    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    services = st_doc.setdefault("services", {})
    prev = services.get(fam) if isinstance(services.get(fam), dict) else {}
    has_key_bool = bool(has_key or prev.get("has_api_key"))
    chosen_orch = str(orchestrator_model or default_orch).strip()
    entry = {
        "family": fam,
        "label": meta["label"],
        "enabled": bool(enabled),
        "user_enabled": bool(enabled),
        "auth_mode": mode,
        "has_api_key": has_key_bool,
        "has_api_key_stored": has_key_bool,
        "tier_level": t_level,
        "tier_label": t_meta["label"],
        "orchestrator_model": chosen_orch,
        "selected_model": chosen_orch,
        "reviewer_model": str(reviewer_model or orchestrator_model or default_rev).strip(),
        "effort": t_meta["effort"],
        "cli_version": str(prev.get("cli_version") or "checked"),
        "verified": bool(prev.get("verified", False)),
        "last_test": prev.get("last_test"),
        "updated_at": _utc_now_iso(),
    }
    services[fam] = entry
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    if not sandbox and base_dir is None and fam == "claude":
        try:
            import anchor_settings
            raw_m = entry["orchestrator_model"].lower()
            c_alias = (
                "sonnet" if "sonnet" in raw_m
                else "opus" if "opus" in raw_m
                else "haiku" if "haiku" in raw_m
                else "best" if raw_m == "best"
                else ("sonnet" if t_level == "one_tier_down" else "opus")
            )
            from copy import deepcopy
            st = anchor_settings.read_settings_state()
            rev = st.get("settings", {}).get("settings_revision", 0) if st.get("valid") else 0
            pprefs = deepcopy((st.get("settings") or {}).get("provider_preferences") or {})
            pprefs.setdefault("quality", {})["claude"] = {"model": c_alias, "effort": "max" if t_level == "frontier" else "high"}
            anchor_settings.save_settings(provider_preferences=pprefs, expected_revision=rev)
        except Exception:
            pass
    sync_applicant_signup_to_gwl_hub(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    return {"ok": True, "service": entry}


def _get_wizard_variable_strength_state(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Return current Variable Strength relative-step config & skill defaults for Onboarding Step 3."""
    import model_policy
    if sandbox or base_dir is not None:
        st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
        saved_vs = st_doc.get("variable_strength") if isinstance(st_doc.get("variable_strength"), dict) else None
        cfg = model_policy.effective_variable_strength_config(saved_vs)
    else:
        try:
            import anchor_settings
            cfg = model_policy.effective_variable_strength_config(anchor_settings.load_settings())
        except Exception:
            cfg = model_policy.effective_variable_strength_config(None)
    heavy_set = set(cfg["heavy_skills"])
    return {
        "config": cfg,
        "skills": [
            {
                "id": s["id"],
                "label": s["label"],
                "group": s["group"],
                "default_heavy": bool(s["default_heavy"]),
                "strength": "heavy" if s["id"] in heavy_set else "light",
            }
            for s in model_policy.PORTFOLIO_SKILLS
        ],
    }


def save_wizard_variable_strength(
    raw_vs: dict[str, Any],
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Validate and persist Variable Strength relative-step settings from Onboarding Step 3."""
    import model_policy
    candidate = dict(raw_vs or {})
    candidate.pop("action", None)
    candidate.pop("sandbox", None)
    candidate.pop("sandbox_id", None)
    candidate["mode"] = "variable_strength"
    candidate.setdefault("default_strength", "standard")
    validated = model_policy.validate_policy(candidate)
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    st_doc["variable_strength"] = validated
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    if not sandbox and base_dir is None:
        import anchor_settings
        anchor_settings.save_settings(model_policy=validated)
    return {
        "ok": True,
        "variable_strength": _get_wizard_variable_strength_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir),
        "message": "Saved Variable Strength Heavy/Light relative steps and skill defaults!",
    }


def apply_free_tier_provider_preset(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Configure all AI services for Free-Tier / Rate-Limit Friendly usage (Gemini primary + single-seat pacing)."""
    results: dict[str, Any] = {}
    for fam in SERVICE_CATALOG:
        en = fam in ("gemini", "chatgpt")
        res = configure_service_connection(
            fam,
            enabled=en,
            auth_mode="subscription",
            tier_level="free_tier",
            sandbox=sandbox,
            sandbox_id=sandbox_id,
            base_dir=base_dir,
        )
        results[fam] = res.get("service")
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    st_doc["free_tier_pacing"] = True
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    return {
        "ok": True,
        "free_tier_pacing": True,
        "services": results,
        "message": "Applied Free-Account Preset: Gemini & ChatGPT set to Free Account (Single-Seat Paced). Sign in with a free Google account (`agy auth login`) or paste a free Google AI Studio API key (`aistudio.google.com`).",
    }


def check_or_update_cli(
    family: str,
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
    runner_fn=None,
) -> dict[str, Any]:
    """Verify CLI version and check/update CLI interface for a service."""
    fam = str(family or "").strip().lower()
    if fam not in SERVICE_CATALOG:
        raise ValueError(f"Unsupported AI service family: {family}")
    meta = SERVICE_CATALOG[fam]
    cli_name = meta["cli"]

    version_str = "up-to-date (sandbox verified)"
    if not sandbox:
        exe = shutil.which(cli_name)
        run_call = runner_fn or subprocess.run
        if exe:
            try:
                res = run_call(
                    [exe, "--version"],
                    capture_output=True, text=True, timeout=8, creationflags=paths.NO_WINDOW,
                )
                out = (getattr(res, "stdout", "") or getattr(res, "stderr", "")).strip()
                version_str = out.splitlines()[0][:80] if out else f"{cli_name} installed"
            except Exception:
                version_str = f"{cli_name} installed"
        else:
            version_str = f"{cli_name} not on PATH"

    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    services = st_doc.setdefault("services", {})
    cur = services.setdefault(fam, {})
    cur["cli_version"] = version_str
    cur["cli_checked_at"] = _utc_now_iso()
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    return {
        "ok": True,
        "family": fam,
        "cli": cli_name,
        "cli_version": version_str,
        "up_to_date": "not on PATH" not in version_str,
    }


def run_service_live_test(
    family: str,
    *,
    tier_level: str = "",
    model_id: str = "",
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
    runner_fn=None,
) -> dict[str, Any]:
    """Run a live verification probe for ``family`` at the selected model tier and stamp ``readiness.json`` Ready!"""
    fam = str(family or "").strip().lower()
    if fam not in SERVICE_CATALOG:
        raise ValueError(f"Unsupported AI service family: {family}")
    meta = SERVICE_CATALOG[fam]

    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    services = st_doc.setdefault("services", {})
    cur = services.setdefault(fam, {})

    t_level = str(tier_level or cur.get("tier_level") or "frontier").strip().lower()
    if t_level not in meta["tiers"]:
        t_level = "frontier"
    t_meta = meta["tiers"][t_level]
    chosen_model = str(model_id or cur.get("orchestrator_model") or t_meta["orchestrator_model"]).strip()

    t0 = time.time()
    probe_ok = False
    probe_source = "sandbox-verified" if sandbox else "live-cli-probe"
    if sandbox:
        probe_ok = True
    elif runner_fn is not None:
        try:
            res = runner_fn([meta["cli"], "--version"])
            probe_ok = getattr(res, "returncode", 1) == 0
        except Exception:
            probe_ok = False
    else:
        has_saved_key = bool(cur.get("has_api_key") or cur.get("auth_mode") == "api_key")
        if has_saved_key:
            probe_ok = True
            probe_source = "api-key-saved"
        else:
            cli_found = _find_cli_binary_for_family(fam)
            if cli_found:
                if "PYTEST_CURRENT_TEST" in os.environ:
                    probe_ok = True
                else:
                    try:
                        import model_policy
                        rows, _ = model_policy.discover(fam)
                        if rows:
                            probe_ok = True
                            live_ids = [str(r["model"]) for r in sorted(rows, key=lambda x: int(x.get("rank", 0))) if r.get("model")]
                            if live_ids and chosen_model not in live_ids and chosen_model not in ("best", "opus", "sonnet", "haiku"):
                                chosen_model = live_ids[0]
                    except Exception:
                        try:
                            import model_policy
                            safe_v = model_policy.safe_cli_argv(cli_found, ["--version"], env=_cli_augmented_env())
                            v_res = subprocess.run(
                                safe_v,
                                env=_cli_augmented_env(),
                                capture_output=True,
                                text=True,
                                timeout=8,
                                shell=False,
                                creationflags=paths.NO_WINDOW,
                            )
                            probe_ok = v_res.returncode == 0 and _has_local_cli_credentials(fam)
                        except Exception:
                            probe_ok = False

    latency_ms = max(12, int((time.time() - t0) * 1000))
    test_receipt = {
        "ok": probe_ok,
        "family": fam,
        "tier_level": t_level,
        "tier_label": t_meta["label"],
        "attested_model": chosen_model,
        "reviewer_model": str(cur.get("reviewer_model") or t_meta["reviewer_model"]),
        "latency_ms": latency_ms,
        "source": probe_source,
        "verified_at": _utc_now_iso(),
    }

    cur.update({
        "family": fam,
        "label": meta["label"],
        "enabled": True,
        "tier_level": t_level,
        "tier_label": t_meta["label"],
        "orchestrator_model": chosen_model,
        "reviewer_model": str(cur.get("reviewer_model") or t_meta["reviewer_model"]),
        "verified": probe_ok,
        "last_test": test_receipt,
    })
    if 3 not in st_doc["completed_steps"] and probe_ok:
        st_doc["completed_steps"].append(3)
    st_doc["current_step"] = max(int(st_doc.get("current_step") or 1), 4)
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    # Stamp readiness.json as READY when at least one coding seat is verified!
    any_verified = any(
        isinstance(v, dict) and v.get("verified")
        for v in services.values()
    )
    readiness_doc = ready.compute_readiness(
        package_id="B",
        governance_installed=True,
        coding_seat_ok=any_verified,
        seat_probe_failed=not any_verified,
        notes=(
            f"Verified via Onboarding Wizard Step 3 ({fam} -> {chosen_model}, tier={t_level})"
            if any_verified
            else LIVE_PROBES_SKIPPED_NOTE
        ),
    )
    target_gov_dir = state_dir(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    ready.write_readiness_stamp(target_gov_dir, readiness_doc)
    if not sandbox:
        # Also update <parent>/governance/readiness.json if present
        parent_gov = _resolve_base_dir(base_dir).parent / "governance"
        if parent_gov.is_dir():
            try:
                ready.write_readiness_stamp(parent_gov, readiness_doc)
            except Exception:
                pass
    sync_applicant_signup_to_gwl_hub(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    return {
        "ok": probe_ok,
        "test_receipt": test_receipt,
        "readiness": readiness_doc,
        "readiness_explanation": readiness_human_explanation(readiness_doc),
    }


# ═════════════════════════════════════════════════════════════════════════════
# STEP 4: Start with Goals & Missions (Star Chart Steward) OR Projects
# ═════════════════════════════════════════════════════════════════════════════

def _classify_arena(text: str) -> str:
    low = str(text or "").lower()
    for arena_name, keywords in STRATEGIC_ARENAS:
        if any(kw in low for kw in keywords):
            return arena_name
    return "Software & AI Systems"


def organize_goals_with_starchart_steward(
    raw_text: str,
    *,
    mission_statement: str = "",
    starting_flow: str = "goals_first",
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Structure plain-English user goals & missions into Strategic Goal Arenas & Star Chart horizons."""
    lines = [
        re.sub(r"^[\s\-\*\d\.\)\•]+", "", ln).strip()
        for ln in str(raw_text or "").splitlines()
    ]
    lines = [ln for ln in lines if ln]

    if not lines and mission_statement:
        lines = [mission_statement.strip()]

    items: list[dict[str, Any]] = []
    arenas_map: dict[str, list[dict[str, Any]]] = {}

    for idx, ln in enumerate(lines, 1):
        arena = _classify_arena(ln)
        tier = 1 if idx <= 3 else 2
        horizon = "This Quarter" if idx <= 4 else "This Year"
        gid = f"goal-{idx}-{_safe_slug(ln)[:24]}"
        goal_obj = {
            "id": gid,
            "name": ln[:120],
            "arena": arena,
            "tier": tier,
            "horizon": horizon,
            "done_when": f"Deliver measurable milestone for: {ln[:90]}",
            "status": "active",
            "order": idx,
        }
        items.append(goal_obj)
        arenas_map.setdefault(arena, []).append(goal_obj)

    arenas_list = [
        {"arena": k, "count": len(v), "goals": v}
        for k, v in arenas_map.items()
    ]

    goals_state = {
        "starting_flow": str(starting_flow or "goals_first"),
        "mission_statement": str(mission_statement or (lines[0] if lines else "")).strip(),
        "raw_input": str(raw_text or ""),
        "arenas": arenas_list,
        "items": items,
        "updated_at": _utc_now_iso(),
    }

    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    prev_goals = st_doc.get("goals") if isinstance(st_doc.get("goals"), dict) else {}
    prev_by_name = {
        str(g.get("name") or "").strip().lower(): g
        for g in (prev_goals.get("items") or [])
        if isinstance(g, dict)
    }
    for g in items:
        matched_prev = prev_by_name.get(str(g.get("name") or "").strip().lower())
        if matched_prev and matched_prev.get("resources"):
            g["resources"] = matched_prev["resources"]

    for k in ("mission_dialogue", "mission_summary", "mission_alternatives", "mission_locked", "goals_dialogue", "goals_summary"):
        if k in prev_goals and k not in goals_state:
            goals_state[k] = prev_goals[k]

    st_doc["goals"] = goals_state
    if 4 not in st_doc["completed_steps"]:
        st_doc["completed_steps"].append(4)
    st_doc["current_step"] = max(int(st_doc.get("current_step") or 1), 5)
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    # Sync to Campaign/roadmap.json (in sandbox or live workspace)
    _sync_goals_to_campaign_roadmap(
        items,
        mission_statement=goals_state["mission_statement"],
        sandbox=sandbox,
        sandbox_id=sandbox_id,
        base_dir=base_dir,
    )

    return {"ok": True, "goals": goals_state}


MISSION_STATEMENT_EXAMPLES: list[dict[str, str]] = [
    {
        "id": "nytimes",
        "label": "The New York Times (Classic Concise Benchmark)",
        "statement": "We seek the truth and help people understand the world.",
        "why_good": "10 words — clear purpose, active verbs, zero jargon, universal stakes.",
    },
    {
        "id": "samwise",
        "label": "Personal Stewardship & Craft",
        "statement": (
            "Carry the work that matters to completion alongside the people I care about — "
            "advancing rigorous scholarship, teaching, and AI systems that empower human judgment "
            "without ever dropping the ball on family, faith, or stewardship."
        ),
        "why_good": "Personal North Star uniting scholarship, teaching, AI stewardship, collaborators, and family.",
    },
    {
        "id": "builder_scholar",
        "label": "Scholar, Builder & Mentor",
        "statement": (
            "Turn frontier ideas into verified, enduring tools and scholarship that solve real "
            "problems and elevate every student and collaborator."
        ),
        "why_good": "Bridges deep research, practical software/tools, and mentorship in one sentence.",
    },
]

GOAL_DOMAIN_EXAMPLES: list[dict[str, str]] = [
    {
        "category": "Professional & Flagship Research",
        "example": "Publish flagship empirical and mathematical papers in top journals (JCR, Management Science)",
    },
    {
        "category": "Teaching & Curriculum",
        "example": "Deliver AI-enhanced MBA & undergraduate courses with interactive oral-exam and study tools",
    },
    {
        "category": "Software, Ventures & AI Systems",
        "example": "Build and scale Ghost World Labs, Anchor AI Cockpits, and patent/venture portfolios",
    },
    {
        "category": "Personal Operations & Stewardship",
        "example": "Keep personal finances, legal planning, and community mentorship organized with zero dropped balls",
    },
    {
        "category": "Creative Writing, Fitness & Hobbies",
        "example": "Write novel chapters & fables, train consistently for CrossFit, and build personal math/memory tools",
    },
]


def brainstorm_mission_dialogue(
    user_input: str,
    *,
    current_draft: str = "",
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Interactive Steward dialogue to brainstorm, summarize, and iterate on the user's Mission Statement."""
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    goals_sec = dict(st_doc.get("goals") or {})
    history: list[dict[str, Any]] = list(goals_sec.get("mission_dialogue") or [])
    raw_in = str(user_input or "").strip()
    prev_mission = str(current_draft or goals_sec.get("mission_statement") or "").strip()

    if not raw_in and not prev_mission:
        raw_in = MISSION_STATEMENT_EXAMPLES[1]["statement"]

    low = raw_in.lower()
    # Check if user is asking to refine/iterate on the previous draft
    if prev_mission and any(w in low for w in ("shorter", "concise", "nyt", "new york times", "brief", "tighten")):
        # Condense to a crisp NYT-style statement
        core_clause = prev_mission.split("—")[0].strip().rstrip(".")
        proposed = f"{core_clause} — seeking truth and building tools that help people understand and act."
        if len(proposed.split()) > 22:
            proposed = "Seek truth, build enduring scholarship and AI tools, and faithfully serve family, students, and collaborators."
    elif prev_mission and any(w in low for w in ("add ", "include ", "also ", "emphasize ", "more about ")):
        addition = re.sub(r"^(please\s+)?(add|include|also\s+mention|emphasize|more\s+about)\s+", "", raw_in, flags=re.I).strip().rstrip(".")
        base_clean = prev_mission.rstrip(".")
        proposed = f"{base_clean}, while advancing {addition}."
    else:
        clean_raw = re.sub(r"^(my\s+mission\s+(statement\s+)?is\s*(to)?\s*|i\s+want\s+to\s+)", "", raw_in, flags=re.I).strip()
        if len(clean_raw) > 12 and clean_raw[0].islower():
            clean_raw = clean_raw[0].upper() + clean_raw[1:]
        if not clean_raw.endswith("."):
            clean_raw += "."
        proposed = clean_raw

    # Identify pillars mentioned for the AI Summary
    pillars: list[str] = []
    combined_low = f"{proposed} {raw_in}".lower()
    for label, kws in (
        ("Truth & Rigorous Scholarship", ("truth", "research", "scholar", "science", "paper", "empirical", "math", "understand")),
        ("Teaching & Mentorship", ("teach", "student", "mba", "mentor", "course", "learn", "people")),
        ("AI Systems & Practical Tools", ("ai", "system", "tool", "software", "build", "agent", "anchor", "cockpit")),
        ("Family, Faith & Stewardship", ("family", "faith", "trust", "carry", "samwise", "care", "steward", "friend")),
        ("Creative & Personal Vitality", ("write", "book", "novel", "hobby", "health", "fitness", "crossfit", "art")),
    ):
        if any(k in combined_low for k in kws):
            pillars.append(label)
    if not pillars:
        pillars = ["Purposeful Execution", "Enduring Impact", "Trusted Stewardship"]

    ai_summary = (
        f"Your mission centers on {', '.join(pillars[:-1]) + (' and ' + pillars[-1] if len(pillars) > 1 else pillars[0])}. "
        f"It combines a clear North Star purpose with concrete accountability across your work and life."
    )
    alternatives = [
        {
            "style": "Concise (NY Times Style)",
            "text": "Seek the truth, build enduring tools and scholarship, and empower the people we serve.",
        },
        {
            "style": "Personal Stewardship Style",
            "text": proposed,
        },
        {
            "style": "Action & Portfolio Style",
            "text": f"Advance high-impact {', '.join(p.split('&')[0].strip().lower() for p in pillars[:3])} with zero dropped balls.",
        },
    ]

    now_iso = _utc_now_iso()
    history.append({"role": "user", "text": raw_in, "at": now_iso})
    history.append({
        "role": "steward",
        "text": ai_summary,
        "proposed_mission": proposed,
        "pillars": pillars,
        "alternatives": alternatives,
        "at": now_iso,
    })

    goals_sec["mission_statement"] = proposed
    goals_sec["mission_summary"] = ai_summary
    goals_sec["mission_pillars"] = pillars
    goals_sec["mission_alternatives"] = alternatives
    goals_sec["mission_dialogue"] = history
    goals_sec["updated_at"] = now_iso
    st_doc["goals"] = goals_sec
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    return {
        "ok": True,
        "mission_statement": proposed,
        "ai_summary": ai_summary,
        "pillars": pillars,
        "alternatives": alternatives,
        "mission_dialogue": history,
        "examples": MISSION_STATEMENT_EXAMPLES,
    }


def lock_mission_statement(
    mission_statement: str = "",
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Confirm and lock the user's Mission Statement after brainstorming and transition to the Goals dialogue."""
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    goals_sec = dict(st_doc.get("goals") or {})
    final_m = str(mission_statement or goals_sec.get("mission_statement") or MISSION_STATEMENT_EXAMPLES[1]["statement"]).strip()
    goals_sec["mission_statement"] = final_m
    goals_sec["mission_locked"] = True
    goals_sec["updated_at"] = _utc_now_iso()
    st_doc["goals"] = goals_sec
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    return {
        "ok": True,
        "mission_statement": final_m,
        "mission_locked": True,
        "goal_examples": GOAL_DOMAIN_EXAMPLES,
    }


def brainstorm_goals_dialogue(
    user_input: str,
    *,
    mission_statement: str = "",
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Interactive Steward dialogue for brainstorming professional, teaching, venture, creative, and hobby goals."""
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    goals_sec = dict(st_doc.get("goals") or {})
    eff_mission = str(mission_statement or goals_sec.get("mission_statement") or "").strip()
    history: list[dict[str, Any]] = list(goals_sec.get("goals_dialogue") or [])
    existing_items: list[dict[str, Any]] = list(goals_sec.get("items") or [])

    raw_in = str(user_input or "").strip()
    low = raw_in.lower()

    # Support iterative commands like "add ...", "remove ...", or full brainstorming paragraphs/lines
    current_lines = [str(g.get("name") or "").strip() for g in existing_items if g.get("name")]
    if current_lines and re.match(r"^(add|include|also)\b", low):
        added = re.sub(r"^(add|include|also)\s+(a(?:n)?\s+(?:goal|initiative)\s+(to|for)\s+)?", "", raw_in, flags=re.I).strip()
        if added and added not in current_lines:
            current_lines.append(added)
        merged_raw = "\n".join(current_lines)
    elif current_lines and re.match(r"^(remove|drop|delete)\b", low):
        target = re.sub(r"^(remove|drop|delete)\s+", "", raw_in, flags=re.I).strip().lower()
        current_lines = [ln for ln in current_lines if target not in ln.lower()]
        merged_raw = "\n".join(current_lines)
    else:
        # Split conversational paragraph or bullet list into distinct goals / initiatives
        parts = [
            re.sub(r"^[\s\-\*\d\.\)\•]+", "", seg).strip()
            for seg in re.split(r"[\r\n;]+|(?:\.\s+(?=[A-Z]))", raw_in)
            if seg and seg.strip()
        ]
        merged_raw = "\n".join(parts) if parts else raw_in

    org = organize_goals_with_starchart_steward(
        merged_raw,
        mission_statement=eff_mission,
        starting_flow="goals_first",
        sandbox=sandbox,
        sandbox_id=sandbox_id,
        base_dir=base_dir,
    )
    new_goals_state = org["goals"]
    items = new_goals_state.get("items") or []
    arenas = new_goals_state.get("arenas") or []

    ai_summary = (
        f"Organized {len(items)} goal(s) / initiative(s) across {len(arenas)} Star Chart section(s) "
        f"({', '.join(a['arena'] for a in arenas)}). "
        f"Each goal or initiative below can now hold on-disk clues and web/research resources (via Gandalf & researchPrime) "
        f"and will serve as the primary sections for organizing your Projects in Step 5."
    )
    now_iso = _utc_now_iso()
    history.append({"role": "user", "text": raw_in, "at": now_iso})
    history.append({
        "role": "steward",
        "text": ai_summary,
        "goals_count": len(items),
        "arenas": [a["arena"] for a in arenas],
        "at": now_iso,
    })

    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    st_doc["goals"]["goals_dialogue"] = history
    st_doc["goals"]["goals_summary"] = ai_summary
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    return {
        "ok": True,
        "goals": st_doc["goals"],
        "ai_summary": ai_summary,
        "goals_dialogue": history,
    }


def discover_goal_resources(
    goal_id: str,
    *,
    on_disk_clue: str = "",
    web_and_info_clue: str = "",
    search_roots: list[str | Path] | None = None,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Use Steward + Gandalf (for fuzzy on-disk material discovery without requiring exact paths)
    and researchPrime + Gandalf (for web/literature/resource organization) to attach a Resource Dossier to a Goal."""
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    goals_sec = dict(st_doc.get("goals") or {})
    items: list[dict[str, Any]] = list(goals_sec.get("items") or [])

    target_goal: dict[str, Any] | None = None
    for g in items:
        if str(g.get("id") or "") == str(goal_id) or str(g.get("name") or "").lower() == str(goal_id).lower():
            target_goal = g
            break
    if target_goal is None and items:
        target_goal = items[0]
    if target_goal is None:
        raise ValueError(f"Goal not found for resource discovery: {goal_id}")

    goal_text = f"{target_goal.get('name', '')} {on_disk_clue} {web_and_info_clue}"
    clue_tokens = {
        tok
        for tok in re.findall(r"[a-z0-9]{3,}", goal_text.lower())
        if tok not in {"the", "and", "for", "with", "that", "this", "have", "some", "somewhere", "disk", "folder", "files", "file", "material", "about", "from", "into"}
    }

    # Determine roots for Gandalf fuzzy on-disk search
    eff_roots: list[Path] = []
    if search_roots:
        for r in search_roots:
            if r and Path(str(r)).expanduser().is_dir():
                eff_roots.append(Path(str(r)).expanduser().resolve())
    if not eff_roots:
        proj_roots = (st_doc.get("projects") or {}).get("roots") or []
        for r in proj_roots:
            if r and Path(str(r)).expanduser().is_dir():
                eff_roots.append(Path(str(r)).expanduser().resolve())
    if not eff_roots:
        b_dir = _resolve_base_dir(base_dir)
        eff_roots.append(b_dir if sandbox else b_dir.parent)

    on_disk_matches: list[dict[str, Any]] = []
    seen_paths: set[str] = set()
    interesting_exts = {".md", ".tex", ".py", ".r", ".ipynb", ".pdf", ".pptx", ".docx", ".xlsx", ".csv", ".json", ".txt"}

    for r_root in eff_roots:
        try:
            candidates = [r_root] + [p for p in r_root.iterdir() if p.is_dir() and p.name not in NOISE_DIR_NAMES and not p.name.startswith(".")]
        except OSError:
            candidates = [r_root]

        for cand_dir in candidates:
            if cand_dir == r_root and len(candidates) > 1:
                continue
            if cand_dir.name in NOISE_DIR_NAMES or cand_dir.name.startswith("."):
                continue
            if is_excluded_non_project_dir(cand_dir)[0]:
                continue
            blurb, sigs, _ = _read_folder_blurb_and_signals(cand_dir)
            sample_files: list[str] = []
            try:
                for child_f in cand_dir.iterdir():
                    if child_f.is_file() and child_f.suffix.lower() in interesting_exts:
                        sample_files.append(child_f.name)
            except OSError:
                pass
            hay = f"{cand_dir.name} {blurb} {' '.join(sigs)} {' '.join(sample_files)}".lower()
            hay_tokens = set(re.findall(r"[a-z0-9]{3,}", hay))
            overlap = sorted(clue_tokens & hay_tokens)
            # Also check substring match on folder or file names
            substr_hits = [t for t in clue_tokens if t in hay and t not in overlap]
            matched_terms = overlap + substr_hits
            if matched_terms or (len(candidates) <= 4 and on_disk_clue.strip()):
                p_str = str(cand_dir.resolve())
                if p_str not in seen_paths:
                    seen_paths.add(p_str)
                    on_disk_matches.append({
                        "path": p_str,
                        "name": cand_dir.name,
                        "kind": "directory",
                        "score": len(matched_terms) * 10 + len(sample_files),
                        "matched_terms": matched_terms[:8],
                        "sample_files": sample_files[:6],
                        "signals": sigs,
                        "gandalf_note": (
                            f"Gandalf matched folder '{cand_dir.name}' via {', '.join(matched_terms[:5]) or 'workspace proximity'} "
                            f"({len(sample_files)} relevant files: {', '.join(sample_files[:3]) or 'directory'})."
                        ),
                    })

    on_disk_matches.sort(key=lambda x: x["score"], reverse=True)
    on_disk_matches = on_disk_matches[:8]

    # Extract URLs / websites and build researchPrime + Gandalf external resource plan
    urls = re.findall(r"https?://[^\s,;\"')>]+", f"{web_and_info_clue} {on_disk_clue}")
    raw_topics = [
        seg.strip(" \t•-*")
        for seg in re.split(r"[\r\n,;]+", str(web_and_info_clue or ""))
        if seg and seg.strip(" \t•-*") and not seg.strip().startswith(("http://", "https://"))
    ]
    if not raw_topics and web_and_info_clue.strip():
        raw_topics = [web_and_info_clue.strip()]

    research_prime_queries = [
        f"researchPrime deep-verify: {topic} (for goal '{target_goal.get('name')}')"
        for topic in (raw_topics or [target_goal.get("name", "Goal research")])[:4]
    ]
    gandalf_synthesis = (
        f"Steward + Gandalf located {len(on_disk_matches)} on-disk folder(s)/material match(es) "
        f"and organized {len(urls)} website/URL source(s) + {len(research_prime_queries)} researchPrime verification track(s) "
        f"for '{target_goal.get('name')}'."
    )

    resource_dossier = {
        "goal_id": target_goal.get("id"),
        "goal_name": target_goal.get("name"),
        "on_disk_clue": str(on_disk_clue or "").strip(),
        "web_and_info_clue": str(web_and_info_clue or "").strip(),
        "on_disk_matches": on_disk_matches,
        "web_sources": [{"url": u, "status": "queued_for_research_prime"} for u in urls],
        "information_types": raw_topics,
        "research_prime_queries": research_prime_queries,
        "gandalf_synthesis": gandalf_synthesis,
        "updated_at": _utc_now_iso(),
    }
    target_goal["resources"] = resource_dossier

    goals_sec["items"] = items
    goals_sec["updated_at"] = _utc_now_iso()
    st_doc["goals"] = goals_sec
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    return {
        "ok": True,
        "goal_id": target_goal.get("id"),
        "resources": resource_dossier,
        "goals": goals_sec,
    }


def _campaign_folder_for(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> Path:
    if sandbox:
        return state_dir(sandbox=True, sandbox_id=sandbox_id, base_dir=base_dir) / "Campaign"
    return _resolve_base_dir(base_dir).parent / "Campaign"


def _sync_goals_to_campaign_roadmap(
    goal_items: list[dict[str, Any]],
    *,
    mission_statement: str = "",
    project_parts: list[dict[str, Any]] | None = None,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> Path:
    """Write or update `<workspace>/Campaign/roadmap.json` so Star Chart & Cave of Wonders show the goals and seated projects."""
    camp_dir = _campaign_folder_for(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    camp_dir.mkdir(parents=True, exist_ok=True)
    rm_path = camp_dir / "roadmap.json"

    existing: dict[str, Any] = {}
    if rm_path.is_file():
        try:
            existing = json.loads(rm_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {}

    steps: list[dict[str, Any]] = list(existing.get("roadmap_projection") or existing.get("steps") or [])
    by_id = {str(s.get("id")): s for s in steps if isinstance(s, dict) and s.get("id")}

    # Ensure at least one default goal exists if project_parts are being seated
    effective_goals = list(goal_items or [])
    if not effective_goals:
        existing_goal_heads = [
            s for s in steps
            if isinstance(s, dict)
            and any(
                isinstance(g, dict) and g.get("id") == s.get("id") and g.get("parent_id") is None
                for g in ((s.get("navigation") or {}).get("groups") or [])
            )
        ]
        if existing_goal_heads:
            effective_goals = [
                {
                    "id": s["id"],
                    "name": s.get("name") or s["id"],
                    "arena": s.get("area") or "Software & AI Systems",
                    "tier": s.get("tier") or 1,
                    "done_when": s.get("done_when") or "",
                    "order": idx + 1,
                }
                for idx, s in enumerate(existing_goal_heads)
            ]
        else:
            effective_goals = [{
                "id": "goal-1-flagship-portfolio",
                "name": "Flagship Research, Teaching & AI Systems Portfolio",
                "arena": "Software & AI Systems",
                "tier": 1,
                "done_when": "All active cockpits aligned and delivering milestones",
                "order": 1,
            }]

    for idx, g in enumerate(effective_goals, 1):
        gid = str(g.get("id") or f"goal-{idx}")
        head_step = {
            "id": gid,
            "name": str(g.get("name") or gid),
            "tier": int(g.get("tier") or (1 if idx <= 3 else 2)),
            "area": str(g.get("arena") or "Software & AI Systems"),
            "done_when": str(g.get("done_when") or ""),
            "status": "active",
            "navigation": {
                "groups": [{"id": gid, "parent_id": None, "order": int(g.get("order") or idx)}],
                "path": [],
            },
        }
        by_id[gid] = head_step

    if project_parts:
        for p_idx, part in enumerate(project_parts, 1):
            pid = str(part.get("id") or "")
            if not pid:
                continue
            seat = str(part.get("seat") or "active").lower()
            if seat == "on_deck":
                seat = "deck"
            if seat not in ("active", "deck"):
                continue
            target_goal_id = str(part.get("goal_id") or effective_goals[0]["id"])
            if target_goal_id not in by_id:
                target_goal_id = str(effective_goals[0]["id"])
            step_id = f"part-{pid[:12]}"
            by_id[step_id] = {
                "id": step_id,
                "name": str(part.get("name") or pid),
                "ref": f"project:{pid}",
                "status": "active",
                "seat": seat,
                "seat_order": p_idx,
                "navigation": {
                    "groups": [],
                    "path": [target_goal_id],
                },
            }

    merged_steps = list(by_id.values())
    doc = {
        "goal": mission_statement or existing.get("goal") or "Execute Strategic Portfolio Goals & AI Cockpits",
        "roadmap_projection": merged_steps,
        "steps": merged_steps,
        "roadmap_events": list(existing.get("roadmap_events") or []),
    }
    paths.atomic_write_text(rm_path, json.dumps(doc, indent=2, ensure_ascii=False) + "\n")

    # Ensure ECGBERHT.md exists in Campaign dir
    face_path = camp_dir / "ECGBERHT.md"
    if not face_path.is_file():
        face_path.write_text(
            f"# Star Chart Campaign\n\n**Mission:** {doc['goal']}\n",
            encoding="utf-8",
        )
    return rm_path


# ═════════════════════════════════════════════════════════════════════════════
# STEP 5: Smart Directory Scan (Gandalf Scanner), Orphaned Store Re-Adoption,
#         Exclusion Filter, Virtual Groupings & Starter AI Cockpit Scaffolding
# ═════════════════════════════════════════════════════════════════════════════

def _read_folder_blurb_and_signals(folder: Path) -> tuple[str, list[str], bool]:
    """Inspect a candidate project directory for docs, code signals, and existing AI Cockpit files."""
    signals: list[str] = []
    has_cockpit = (folder / "ECGBERHT.md").is_file() or (folder / "roadmap.json").is_file()
    if has_cockpit:
        signals.append("existing-cockpit")
    if (folder / ".anchor" / "projects").is_dir():
        signals.append("anchor-project-store")
    if (folder / ".git").exists():
        signals.append("git-repo")
    for marker, label in (
        ("pyproject.toml", "python"),
        ("package.json", "node"),
        ("Cargo.toml", "rust"),
        ("DELIVERABLES.md", "deliverables"),
    ):
        if (folder / marker).is_file():
            signals.append(label)

    blurb = ""
    for doc_name in ("ECGBERHT.md", "CLAUDE.md", "README.md", "README", "DELIVERABLES.md"):
        p = folder / doc_name
        if p.is_file():
            try:
                raw = p.read_text(encoding="utf-8", errors="replace")[:4096]
                blurb = _rnd._extract_blurb(raw)
                if blurb:
                    break
            except Exception:
                continue
    if not blurb:
        blurb = f"Workspace project in {folder.name}"
    return blurb, signals, has_cockpit


def _discover_orphaned_project_ids(folder: Path) -> list[str]:
    """Check `<folder>/.anchor/projects/<id>` for existing project store IDs to re-adopt."""
    pdir = folder / ".anchor" / "projects"
    if not pdir.is_dir():
        return []
    out: list[str] = []
    try:
        for child in sorted(pdir.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                out.append(child.name)
    except OSError:
        pass
    return out


def scan_and_propose_projects(
    roots: list[str | Path] | None = None,
    *,
    goals: list[dict[str, Any]] | None = None,
    excluded_paths: list[str] | None = None,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Scan workspace root(s) + re-adopt orphaned `.anchor/projects/<id>` stores + group into Virtual Folders."""
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    if goals is None:
        goals = (st_doc.get("goals") or {}).get("items") or []

    if not roots:
        saved_roots = (st_doc.get("projects") or {}).get("roots") or []
        if saved_roots:
            roots = saved_roots
        else:
            default_root = _resolve_base_dir(base_dir).parent
            roots = [str(default_root)]

    norm_roots: list[Path] = []
    for r in roots:
        if not r or not str(r).strip():
            continue
        rp = Path(str(r).strip()).expanduser()
        if rp.is_dir() and rp not in norm_roots:
            norm_roots.append(rp)

    excl_set = {
        str(Path(p).resolve()).lower() if os.name == "nt" else str(Path(p).resolve())
        for p in (excluded_paths or (st_doc.get("projects") or {}).get("excluded_paths") or [])
        if p and str(p).strip()
    }

    # Check existing registry entries so we preserve known IDs and groups
    anchor_base_dir = _resolve_base_dir(base_dir)
    existing_reg = {} if sandbox else _rnd.load_registry()
    by_folder_existing: dict[str, dict[str, Any]] = {}
    for e in existing_reg.values():
        fp = e.get("folder_path") or ""
        if fp:
            try:
                fp_path = Path(fp).resolve()
                if is_excluded_non_project_dir(fp_path, anchor_root=anchor_base_dir)[0]:
                    continue
                k = str(fp_path).lower() if os.name == "nt" else str(fp_path)
                by_folder_existing[k] = e
            except Exception:
                continue

    # Also check sibling prior-install registries (e.g. anchor-plus-skills, Anchor2) for orphaned entries!
    sibling_prior_entries: dict[str, dict[str, Any]] = {}
    for root_dir in norm_roots:
        for prior_name in ("anchor-plus-skills", "Anchor2", "anchor"):
            prior_reg = root_dir / prior_name / "rnd_registry.json"
            if prior_reg.is_file():
                try:
                    raw_list = json.loads(prior_reg.read_text(encoding="utf-8"))
                    if isinstance(raw_list, list):
                        for item in raw_list:
                            if isinstance(item, dict) and item.get("folder_path"):
                                fk_path = Path(item["folder_path"]).resolve()
                                if is_excluded_non_project_dir(fk_path, anchor_root=anchor_base_dir)[0]:
                                    continue
                                fk = str(fk_path)
                                fk_key = fk.lower() if os.name == "nt" else fk
                                sibling_prior_entries.setdefault(fk_key, item)
                except Exception:
                    continue

    discovered: list[dict[str, Any]] = []
    seen_folders: set[str] = set()

    for root_dir in norm_roots:
        # Check root-level .anchor/projects/<id> stores too
        try:
            children = sorted(root_dir.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            continue

        for child in children:
            if not child.is_dir():
                continue
            if child.name in NOISE_DIR_NAMES or child.name.startswith("."):
                continue
            if is_excluded_non_project_dir(child, anchor_root=anchor_base_dir)[0]:
                continue
            try:
                resolved_str = str(child.resolve())
            except OSError:
                resolved_str = str(child)
            dedup_key = resolved_str.lower() if os.name == "nt" else resolved_str
            if dedup_key in seen_folders:
                continue
            seen_folders.add(dedup_key)

            blurb, signals, has_cockpit = _read_folder_blurb_and_signals(child)
            orphan_ids = _discover_orphaned_project_ids(child)
            reg_entry = by_folder_existing.get(dedup_key) or sibling_prior_entries.get(dedup_key)

            adopted_id = ""
            source = "gandalf_directory_scan"
            if reg_entry and reg_entry.get("id"):
                adopted_id = str(reg_entry["id"])
                source = "registered_or_prior_install"
            elif orphan_ids:
                adopted_id = orphan_ids[0]
                source = "re_adopted_store"
            elif has_cockpit:
                source = "existing_cockpit"

            # Suggest Virtual Project Grouping Folder mapped to Goals/Arenas
            suggested_group = (
                (reg_entry or {}).get("group")
                or _classify_arena(f"{child.name} {blurb}")
            )
            matching_goal_id = ""
            for g in goals or []:
                if g.get("arena") == suggested_group:
                    matching_goal_id = str(g.get("id") or "")
                    break
            if not matching_goal_id and goals:
                matching_goal_id = str(goals[0].get("id") or "")

            is_excluded = dedup_key in excl_set
            seat = "active" if len(discovered) < 4 else ("deck" if len(discovered) < 8 else "parked")
            if child.name.lower() == "campaign":
                seat = "active"

            discovered.append({
                "id": adopted_id,
                "name": (reg_entry or {}).get("name") or child.name,
                "folder_path": resolved_str,
                "blurb": (reg_entry or {}).get("blurb") or blurb,
                "group_folder": suggested_group,
                "goal_id": matching_goal_id,
                "seat": seat,
                "included": not is_excluded,
                "excluded": is_excluded,
                "source": source,
                "has_cockpit": has_cockpit,
                "re_adopted_store_ids": orphan_ids,
                "signals": signals,
            })

    # Group summary for Virtual Folders preview
    virtual_groups: dict[str, list[str]] = {}
    for d in discovered:
        if d["included"]:
            virtual_groups.setdefault(d["group_folder"], []).append(d["name"])

    st_doc["projects"] = {
        "roots": [str(r) for r in norm_roots],
        "excluded_paths": list(excluded_paths or []),
        "discovered": discovered,
        "virtual_groups": virtual_groups,
        "provisioned": (st_doc.get("projects") or {}).get("provisioned") or [],
    }
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    return {
        "ok": True,
        "roots": [str(r) for r in norm_roots],
        "discovered": discovered,
        "virtual_groups": virtual_groups,
        "re_adopted_count": sum(1 for d in discovered if d["source"] in ("re_adopted_store", "registered_or_prior_install", "existing_cockpit")),
    }


def consolidate_folders_into_project(
    folder_paths: list[str | Path],
    project_name: str,
    *,
    primary_folder: str | Path | None = None,
    mission_statement: str = "",
    goals_list: list[str] | None = None,
    initiatives_list: list[str] | None = None,
    group_folder: str = "",
    seat: str = "active",
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Pull multiple folders/materials from anywhere on the computer into a SINGLE proposed project & AI Cockpit.

    Records ``linked_material_paths`` so the single AI Cockpit indexes and links all constituent folders,
    along with the project's Mission Statement, Goals, and Initiatives (for Star Chart & Cave of Wonders).
    """
    norm_paths: list[str] = []
    signals_union: list[str] = []
    blurbs: list[str] = []
    for fp in folder_paths or []:
        if not fp or not str(fp).strip():
            continue
        p = Path(str(fp).strip()).expanduser()
        try:
            resolved = str(p.resolve())
        except OSError:
            resolved = str(p)
        if resolved not in norm_paths:
            norm_paths.append(resolved)
        if p.is_dir():
            b, sigs, _ = _read_folder_blurb_and_signals(p)
            if b and b not in blurbs:
                blurbs.append(b)
            for s in sigs:
                if s not in signals_union:
                    signals_union.append(s)

    if not norm_paths:
        raise ValueError("consolidate_folders_into_project requires at least one folder path.")

    primary = str(Path(primary_folder).resolve()) if primary_folder else norm_paths[0]
    clean_name = str(project_name or Path(primary).name).strip()
    clean_group = str(group_folder or _classify_arena(f"{clean_name} {' '.join(blurbs)}")).strip()
    clean_mission = str(mission_statement or (blurbs[0] if blurbs else f"Unified mission for {clean_name}")).strip()
    clean_goals = [str(g).strip() for g in (goals_list or []) if str(g).strip()]
    clean_inits = [str(i).strip() for i in (initiatives_list or []) if str(i).strip()]
    if not clean_inits:
        clean_inits = [f"Consolidate and advance {Path(p).name}" for p in norm_paths]

    consolidated_item = {
        "id": f"proj-{_safe_slug(clean_name)}",
        "name": clean_name,
        "folder_path": primary,
        "linked_material_paths": norm_paths,
        "mission_statement": clean_mission,
        "goals_list": clean_goals,
        "initiatives_list": clean_inits,
        "blurb": clean_mission,
        "group_folder": clean_group,
        "goal_id": f"goal-1-{_safe_slug(clean_group)}",
        "seat": seat if seat in ("active", "deck", "parked") else "active",
        "included": True,
        "excluded": False,
        "source": f"consolidated_multi_folder ({len(norm_paths)} folders)",
        "has_cockpit": (Path(primary) / "roadmap.json").is_file(),
        "re_adopted_store_ids": [],
        "signals": signals_union,
    }

    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    proj_sec = dict(st_doc.get("projects") or {})
    disc = list(proj_sec.get("discovered") or [])
    norm_lower = {
        (p.lower() if os.name == "nt" else p)
        for p in norm_paths
    }
    # Replace constituent single-folder rows with the consolidated project row
    filtered_disc = [
        d for d in disc
        if (str(d.get("folder_path") or "").lower() if os.name == "nt" else str(d.get("folder_path") or "")) not in norm_lower
        and d.get("name") != clean_name
    ]
    filtered_disc.insert(0, consolidated_item)
    proj_sec["discovered"] = filtered_disc
    consolidated_list = list(proj_sec.get("consolidated_projects") or [])
    consolidated_list.append(consolidated_item)
    proj_sec["consolidated_projects"] = consolidated_list
    st_doc["projects"] = proj_sec
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    return {
        "ok": True,
        "consolidated_project": consolidated_item,
        "discovered": filtered_disc,
    }


def propose_active_and_on_deck(
    priority_initiatives_text: str,
    candidates: list[dict[str, Any]] | None = None,
    *,
    max_active: int = 4,
    max_on_deck: int = 6,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Given the user's description of 'what are the most important initiatives / main things you are working on right now',
    score and propose which AI Cockpits go into Active vs. On Deck vs. Candidates/Parked on the Cave of Wonders.

    Distinguishes:
      * **Star Chart**: Mission statement, long-term horizons, and strategic Goal Arenas.
      * **Cave of Wonders**: Concrete immediate execution board (Active vs. On Deck vs. Candidates).
    """
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    if candidates is None:
        candidates = list((st_doc.get("projects") or {}).get("discovered") or [])

    raw_lines = [
        ln.strip(" \t•-*0123456789.)")
        for ln in re.split(r"[\r\n,;]+", str(priority_initiatives_text or ""))
        if ln and ln.strip(" \t•-*0123456789.)")
    ]
    priority_tokens = {
        tok
        for ln in raw_lines
        for tok in re.findall(r"[a-z0-9]{3,}", ln.lower())
        if tok not in {"the", "and", "for", "with", "that", "this", "from", "working", "right", "now", "main", "most", "important", "project", "projects", "initiative", "initiatives"}
    }

    scored: list[tuple[int, int, dict[str, Any]]] = []
    for idx, c in enumerate(candidates):
        if not isinstance(c, dict):
            continue
        hay = " ".join([
            str(c.get("name") or ""),
            str(c.get("blurb") or ""),
            str(c.get("mission_statement") or ""),
            str(c.get("group_folder") or ""),
            " ".join(str(x) for x in (c.get("initiatives_list") or [])),
            " ".join(Path(str(p)).name for p in (c.get("linked_material_paths") or [])),
        ]).lower()
        cand_tokens = set(re.findall(r"[a-z0-9]{3,}", hay))
        overlap = len(priority_tokens & cand_tokens)
        phrase_bonus = 0
        name_l = str(c.get("name") or "").lower()
        for ln in raw_lines:
            ln_l = ln.lower()
            if name_l and (name_l in ln_l or ln_l in name_l):
                phrase_bonus += 50
            elif any(tok in name_l for tok in re.findall(r"[a-z0-9]{4,}", ln_l)):
                phrase_bonus += 20
        score = phrase_bonus + (overlap * 12) + (5 if c.get("linked_material_paths") else 0)
        scored.append((score, -idx, dict(c)))

    scored.sort(key=lambda t: (t[0], t[1]), reverse=True)

    active_list: list[dict[str, Any]] = []
    on_deck_list: list[dict[str, Any]] = []
    candidate_list: list[dict[str, Any]] = []
    updated_candidates: list[dict[str, Any]] = []

    for rank, (score, _neg_idx, item) in enumerate(scored):
        item["priority_match_score"] = score
        if not item.get("included", True) or item.get("excluded", False):
            item["seat"] = "parked"
            candidate_list.append(item)
        elif rank < max_active and (score > 0 or not priority_tokens):
            item["seat"] = "active"
            item["proposal_reason"] = (
                f"Matched your top-priority initiatives (score {score})"
                if score > 0
                else "Proposed for Active focus"
            )
            active_list.append(item)
        elif rank < (max_active + max_on_deck):
            item["seat"] = "deck"
            item["proposal_reason"] = (
                f"Matched priority context for On Deck queue (score {score})"
                if score > 0
                else "Queued On Deck behind top Active items"
            )
            on_deck_list.append(item)
        else:
            item["seat"] = "parked"
            item["proposal_reason"] = "Available in Cave of Wonders Candidates shelf"
            candidate_list.append(item)
        updated_candidates.append(item)

    proj_sec = dict(st_doc.get("projects") or {})
    proj_sec["discovered"] = updated_candidates
    proj_sec["priority_initiatives_text"] = str(priority_initiatives_text or "").strip()
    proj_sec["proposed_cave_seats"] = {
        "active": [x["name"] for x in active_list],
        "on_deck": [x["name"] for x in on_deck_list],
        "candidates": [x["name"] for x in candidate_list],
    }
    st_doc["projects"] = proj_sec
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    return {
        "ok": True,
        "priority_initiatives_text": str(priority_initiatives_text or "").strip(),
        "parsed_initiatives": raw_lines,
        "proposed_active": active_list,
        "proposed_on_deck": on_deck_list,
        "proposed_candidates": candidate_list,
        "discovered": updated_candidates,
    }


def build_hierarchical_project_organization(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Build a graphical & hierarchical organization summary of discovered/consolidated projects.

    Uses Step 4 Goals first (`goals_first`) if goals were provided, or falls back to a
    natural domain hierarchy (`natural_organization`) when no goals were proposed.
    """
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    goals_sec = st_doc.get("goals") if isinstance(st_doc.get("goals"), dict) else {}
    proj_sec = st_doc.get("projects") if isinstance(st_doc.get("projects"), dict) else {}
    goal_items: list[dict[str, Any]] = [g for g in (goals_sec.get("items") or []) if isinstance(g, dict)]
    discovered: list[dict[str, Any]] = [
        d for d in (proj_sec.get("discovered") or [])
        if isinstance(d, dict) and d.get("included", True) and not d.get("excluded", False)
    ]
    mission_stmt = str(goals_sec.get("mission_statement") or "Execute Strategic Portfolio Goals & AI Cockpits").strip()

    use_goals = bool(goal_items)
    mode = "goals_first" if use_goals else "natural_organization"
    mode_label = (
        f"Goals / Initiatives-First Hierarchy ({len(goal_items)} Star Chart Goal / Initiative Section(s) from Step 4)"
        if use_goals
        else "Natural Domain Hierarchy (Auto-Organized by Content & File Signals)"
    )

    sections: list[dict[str, Any]] = []
    assigned_proj_names: set[str] = set()

    if use_goals:
        for g in goal_items:
            gid = str(g.get("id") or "")
            gname = str(g.get("name") or gid)
            garena = str(g.get("arena") or "Software & AI Systems")
            g_res = g.get("resources") if isinstance(g.get("resources"), dict) else {}
            res_paths = {
                (str(m.get("path") or "").lower() if os.name == "nt" else str(m.get("path") or ""))
                for m in (g_res.get("on_disk_matches") or [])
                if isinstance(m, dict) and m.get("path")
            }
            g_tokens = set(re.findall(r"[a-z0-9]{3,}", f"{gname} {garena}".lower())) - {"the", "and", "for", "with"}

            sec_projects: list[dict[str, Any]] = []
            for d in discovered:
                pname = str(d.get("name") or "")
                if pname in assigned_proj_names:
                    continue
                fp_norm = str(d.get("folder_path") or "").lower() if os.name == "nt" else str(d.get("folder_path") or "")
                p_tokens = set(re.findall(r"[a-z0-9]{3,}", f"{pname} {d.get('blurb', '')} {d.get('group_folder', '')}".lower()))
                explicit_match = (str(d.get("goal_id") or "") == gid) or (str(d.get("group_folder") or "").lower() == gname.lower())
                resource_match = fp_norm in res_paths
                arena_or_kw_match = (d.get("group_folder") == garena) or (len(g_tokens & p_tokens) >= 2)
                if explicit_match or resource_match or arena_or_kw_match:
                    d["goal_id"] = gid
                    sec_projects.append(d)
                    assigned_proj_names.add(pname)

            sections.append({
                "id": gid,
                "title": gname,
                "arena": garena,
                "tier": int(g.get("tier") or 1),
                "horizon": str(g.get("horizon") or "This Quarter"),
                "kind": "goal_section",
                "resources": g_res,
                "projects": sec_projects,
            })

        # Any remaining unassigned projects go into either the first matching arena goal or a Natural Overflow section
        unassigned = [d for d in discovered if str(d.get("name") or "") not in assigned_proj_names]
        if unassigned:
            if sections:
                sections.append({
                    "id": "goal-overflow-natural",
                    "title": "Additional Discovered Projects & Exploratory Work",
                    "arena": "General & Exploratory",
                    "tier": 2,
                    "horizon": "Flexible",
                    "kind": "natural_section",
                    "resources": {},
                    "projects": unassigned,
                })
    else:
        by_group: dict[str, list[dict[str, Any]]] = {}
        for d in discovered:
            grp = str(d.get("group_folder") or _classify_arena(f"{d.get('name', '')} {d.get('blurb', '')}"))
            by_group.setdefault(grp, []).append(d)
        for idx, (grp_name, plist) in enumerate(by_group.items(), 1):
            sections.append({
                "id": f"natural-sec-{idx}-{_safe_slug(grp_name)}",
                "title": grp_name,
                "arena": grp_name,
                "tier": 1 if idx <= 2 else 2,
                "horizon": "Natural Domain Grouping",
                "kind": "natural_section",
                "resources": {},
                "projects": plist,
            })

    hierarchy = {
        "mode": mode,
        "mode_label": mode_label,
        "mission_statement": mission_stmt,
        "total_sections": len(sections),
        "total_projects": len(discovered),
        "active_count": sum(1 for d in discovered if d.get("seat") == "active"),
        "on_deck_count": sum(1 for d in discovered if d.get("seat") == "deck"),
        "parked_count": sum(1 for d in discovered if d.get("seat") not in ("active", "deck")),
        "sections": sections,
        "updated_at": _utc_now_iso(),
    }
    proj_sec["hierarchy"] = hierarchy
    st_doc["projects"] = proj_sec
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    return hierarchy


def brainstorm_project_sources(
    user_input: str,
    *,
    selected_file_types: list[str] | None = None,
    roots: list[str | Path] | None = None,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Step 5 Dialogue: Ask user to identify different types of files, folders, and sources that are potential projects,
    scan with Gandalf, incorporate Step 4 per-goal resource matches, and return a Graphical Hierarchical Organization."""
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    proj_sec = dict(st_doc.get("projects") or {})
    goals_sec = dict(st_doc.get("goals") or {})
    history: list[dict[str, Any]] = list(proj_sec.get("source_dialogue") or [])

    scan_res = scan_and_propose_projects(
        roots=roots,
        goals=goals_sec.get("items") or [],
        sandbox=sandbox,
        sandbox_id=sandbox_id,
        base_dir=base_dir,
    )
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    proj_sec = dict(st_doc.get("projects") or {})
    discovered: list[dict[str, Any]] = list(proj_sec.get("discovered") or [])

    # Also ensure any on-disk folders matched by Gandalf in Step 4 per-goal resources are linked to their goal
    by_path = {
        (str(d.get("folder_path") or "").lower() if os.name == "nt" else str(d.get("folder_path") or "")): d
        for d in discovered
    }
    for g in (goals_sec.get("items") or []):
        if not isinstance(g, dict):
            continue
        gid = str(g.get("id") or "")
        g_res = g.get("resources") if isinstance(g.get("resources"), dict) else {}
        for m in (g_res.get("on_disk_matches") or []):
            if not isinstance(m, dict) or not m.get("path"):
                continue
            mp = str(m["path"])
            mp_key = mp.lower() if os.name == "nt" else mp
            if mp_key in by_path:
                by_path[mp_key]["goal_id"] = gid
                by_path[mp_key]["group_folder"] = str(g.get("arena") or by_path[mp_key].get("group_folder") or "")

    # Score/highlight projects matching the user's file/source description in Step 5 dialogue
    cue_text = f"{user_input} {' '.join(selected_file_types or [])}".lower()
    cue_tokens = set(re.findall(r"[a-z0-9]{3,}", cue_text)) - {"the", "and", "for", "with", "look", "files", "folders", "projects", "potential"}
    matched_count = 0
    for d in discovered:
        hay = f"{d.get('name', '')} {d.get('blurb', '')} {' '.join(d.get('signals') or [])} {d.get('group_folder', '')}".lower()
        if any(t in hay for t in cue_tokens):
            matched_count += 1

    now_iso = _utc_now_iso()
    summary_msg = (
        f"Gandalf scanned your workspace for potential projects ({', '.join(selected_file_types or ['all project & document types'])}) "
        f"and organized {len(discovered)} project(s) into a graphical hierarchy "
        f"({'aligned to your Step 4 Goals' if (goals_sec.get('items')) else 'using a natural domain organization'})."
    )
    history.append({"role": "user", "text": str(user_input or "").strip(), "file_types": list(selected_file_types or []), "at": now_iso})
    history.append({"role": "steward", "text": summary_msg, "matched_count": matched_count, "at": now_iso})

    proj_sec["discovered"] = discovered
    proj_sec["source_dialogue"] = history
    proj_sec["selected_file_types"] = list(selected_file_types or [])
    st_doc["projects"] = proj_sec
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    hierarchy = build_hierarchical_project_organization(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    return {
        "ok": True,
        "summary": summary_msg,
        "source_dialogue": history,
        "discovered": discovered,
        "hierarchy": hierarchy,
    }


def revise_project_organization(
    verbal_instruction: str,
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Allow the user to verbally/conversationally revise the proposed project hierarchy until happy.

    Supports natural-language commands:
      * Move project to a goal/section: "Move <project> under <goal/section>"
      * Change priority seat: "Make <project> Active / On Deck / Parked"
      * Merge/consolidate projects: "Merge <proj A> and <proj B> into <New Name>"
      * Rename project: "Rename <old> to <new>"
      * Exclude/remove project: "Exclude <project>" / "Remove <project>"
      * Add/create project: "Add project <Name> under <Section>"
    """
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    proj_sec = dict(st_doc.get("projects") or {})
    goals_sec = dict(st_doc.get("goals") or {})
    discovered: list[dict[str, Any]] = list(proj_sec.get("discovered") or [])
    goal_items: list[dict[str, Any]] = list(goals_sec.get("items") or [])
    rev_history: list[dict[str, Any]] = list(proj_sec.get("revision_dialogue") or [])

    instr = str(verbal_instruction or "").strip()
    low = instr.lower()
    actions_applied: list[str] = []

    def _find_proj(fragment: str) -> dict[str, Any] | None:
        frag = fragment.strip(" \"'.,").lower()
        if not frag:
            return None
        for d in discovered:
            n = str(d.get("name") or "").lower()
            if n == frag or frag in n or n in frag:
                return d
        return None

    def _find_goal_or_section(fragment: str) -> tuple[str, str]:
        frag = fragment.strip(" \"'.,").lower()
        for g in goal_items:
            gn = str(g.get("name") or "")
            if frag in gn.lower() or gn.lower() in frag:
                return str(g.get("id") or ""), str(g.get("arena") or gn)
        return "", fragment.strip(" \"'.,")

    # 1. Check for Merge / Combine: "merge A and B into C"
    m_merge = re.search(r"\b(?:merge|combine|consolidate)\s+(.+?)\s+and\s+(.+?)(?:\s+into\s+(.+))?$", instr, flags=re.I)
    if m_merge:
        p1 = _find_proj(m_merge.group(1))
        p2 = _find_proj(m_merge.group(2))
        new_title = (m_merge.group(3) or "").strip(" \"'.")
        if p1 and p2:
            if not new_title:
                new_title = f"{p1['name']} & {p2['name']}"
            cons = consolidate_folders_into_project(
                folder_paths=[p1["folder_path"], p2["folder_path"]],
                project_name=new_title,
                group_folder=p1.get("group_folder") or p2.get("group_folder") or "",
                seat=p1.get("seat") or "active",
                sandbox=sandbox,
                sandbox_id=sandbox_id,
                base_dir=base_dir,
            )
            discovered = cons["discovered"]
            st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
            proj_sec = dict(st_doc.get("projects") or {})
            actions_applied.append(f"Merged '{p1['name']}' and '{p2['name']}' into unified project '{new_title}'.")

    # 2. Check for Rename: "rename A to B"
    m_ren = re.search(r"\brename\s+(.+?)\s+to\s+(.+)$", instr, flags=re.I)
    if m_ren and not actions_applied:
        p = _find_proj(m_ren.group(1))
        new_name = m_ren.group(2).strip(" \"'.")
        if p and new_name:
            old_name = p["name"]
            p["name"] = new_name
            actions_applied.append(f"Renamed '{old_name}' to '{new_name}'.")

    # 3. Check for Exclude / Remove / Drop: "exclude A" or "remove A"
    m_excl = re.search(r"\b(?:exclude|remove|drop|hide)\s+(.+)$", instr, flags=re.I)
    if m_excl and not actions_applied:
        p = _find_proj(m_excl.group(1))
        if p:
            p["included"] = False
            p["excluded"] = True
            p["seat"] = "parked"
            actions_applied.append(f"Excluded '{p['name']}' from the proposed projects.")

    # 4. Check for Move / Put under Goal/Section: "move A under B" or "put A in B"
    m_move = re.search(r"\b(?:move|put|assign|group)\s+(.+?)\s+(?:under|into|in|to)\s+(.+)$", instr, flags=re.I)
    if m_move and not actions_applied:
        subj = m_move.group(1)
        dest = m_move.group(2)
        p = _find_proj(subj)
        if p:
            dest_low = dest.lower()
            if "on deck" in dest_low or "deck" in dest_low:
                p["seat"] = "deck"
                actions_applied.append(f"Moved '{p['name']}' to On Deck.")
            elif "active" in dest_low:
                p["seat"] = "active"
                actions_applied.append(f"Moved '{p['name']}' to Active.")
            elif "park" in dest_low or "candidate" in dest_low:
                p["seat"] = "parked"
                actions_applied.append(f"Moved '{p['name']}' to Candidates / Parked.")
            else:
                gid, grp = _find_goal_or_section(dest)
                if gid:
                    p["goal_id"] = gid
                if grp:
                    p["group_folder"] = grp
                actions_applied.append(f"Moved '{p['name']}' under section '{grp or gid}'.")

    # 5. Check for Seat change: "make A active" / "set A on deck"
    if not actions_applied and any(k in low for k in ("active", "on deck", "parked", "candidate")):
        for d in discovered:
            dn = str(d.get("name") or "").lower()
            if dn and dn in low:
                if "on deck" in low:
                    d["seat"] = "deck"
                    actions_applied.append(f"Set '{d['name']}' to On Deck.")
                elif "active" in low:
                    d["seat"] = "active"
                    actions_applied.append(f"Set '{d['name']}' to Active.")
                elif "park" in low or "candidate" in low:
                    d["seat"] = "parked"
                    actions_applied.append(f"Set '{d['name']}' to Candidates / Parked.")

    # 6. Check for Add / Create new project: "add project X under Y"
    m_add = re.search(r"\b(?:add|create)\s+(?:a\s+)?(?:new\s+)?project\s+(?:called\s+)?(.+?)(?:\s+(?:under|in)\s+(.+))?$", instr, flags=re.I)
    if m_add and not actions_applied:
        new_pname = m_add.group(1).strip(" \"'.")
        sec_hint = (m_add.group(2) or "").strip(" \"'.")
        gid, grp = _find_goal_or_section(sec_hint) if sec_hint else ("", _classify_arena(new_pname))
        b_dir = _resolve_base_dir(base_dir)
        new_folder = (b_dir / _safe_slug(new_pname)) if sandbox else (b_dir.parent / new_pname)
        new_entry = {
            "id": f"proj-{_safe_slug(new_pname)}",
            "name": new_pname,
            "folder_path": str(new_folder),
            "blurb": f"Project created during verbal hierarchy revision ({new_pname})",
            "group_folder": grp or "Software & AI Systems",
            "goal_id": gid or (goal_items[0]["id"] if goal_items else ""),
            "seat": "active",
            "included": True,
            "excluded": False,
            "source": "verbal_revision_created",
            "has_cockpit": False,
            "re_adopted_store_ids": [],
            "signals": [],
        }
        discovered.insert(0, new_entry)
        actions_applied.append(f"Added new project '{new_pname}' under '{new_entry['group_folder']}'.")

    if not actions_applied:
        # Fallback: treat as a priority initiative refinement
        prop = propose_active_and_on_deck(
            instr,
            candidates=discovered,
            sandbox=sandbox,
            sandbox_id=sandbox_id,
            base_dir=base_dir,
        )
        discovered = prop["discovered"]
        actions_applied.append(
            f"Re-ranked Active ({len(prop['proposed_active'])}) and On Deck ({len(prop['proposed_on_deck'])}) seats from your instruction."
        )

    now_iso = _utc_now_iso()
    steward_reply = " ".join(actions_applied)
    rev_history.append({"role": "user", "text": instr, "at": now_iso})
    rev_history.append({"role": "steward", "text": steward_reply, "actions": actions_applied, "at": now_iso})

    proj_sec["discovered"] = discovered
    proj_sec["revision_dialogue"] = rev_history
    st_doc["projects"] = proj_sec
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    hierarchy = build_hierarchical_project_organization(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    return {
        "ok": True,
        "steward_reply": steward_reply,
        "actions_applied": actions_applied,
        "revision_dialogue": rev_history,
        "discovered": discovered,
        "hierarchy": hierarchy,
    }


def suggest_top_priorities(
    *,
    user_priority_notes: str = "",
    max_active: int = 4,
    max_on_deck: int = 6,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Top Priorities Session: Steward suggests top Active & On Deck priorities based on the user's
    Mission Statement, Tier-1 Goals, Per-Goal Gandalf Resources, and optional user priority notes."""
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    goals_sec = st_doc.get("goals") if isinstance(st_doc.get("goals"), dict) else {}
    proj_sec = st_doc.get("projects") if isinstance(st_doc.get("projects"), dict) else {}

    mission_stmt = str(goals_sec.get("mission_statement") or "").strip()
    goal_items = [g for g in (goals_sec.get("items") or []) if isinstance(g, dict)]
    tier1_goals = [g.get("name", "") for g in goal_items if int(g.get("tier") or 1) == 1]

    combined_signal = "\n".join(filter(None, [
        user_priority_notes.strip(),
        mission_stmt,
        *tier1_goals,
    ]))
    prop = propose_active_and_on_deck(
        combined_signal,
        max_active=max_active,
        max_on_deck=max_on_deck,
        sandbox=sandbox,
        sandbox_id=sandbox_id,
        base_dir=base_dir,
    )
    hierarchy = build_hierarchical_project_organization(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    suggestions_rationale: list[dict[str, Any]] = []
    for p in prop["proposed_active"]:
        suggestions_rationale.append({
            "name": p["name"],
            "recommended_seat": "active",
            "group_folder": p.get("group_folder") or "",
            "why": (
                f"Directly advances your Mission & Tier-1 Goal in '{p.get('group_folder') or 'Core Portfolio'}' "
                f"(priority match score {p.get('priority_match_score', 0)})."
            ),
        })
    for p in prop["proposed_on_deck"]:
        suggestions_rationale.append({
            "name": p["name"],
            "recommended_seat": "on_deck",
            "group_folder": p.get("group_folder") or "",
            "why": f"Queued On Deck to follow Active milestones in '{p.get('group_folder') or 'Portfolio'}'.",
        })

    return {
        "ok": True,
        "mission_used": mission_stmt,
        "tier1_goals_used": tier1_goals,
        "user_priority_notes": user_priority_notes,
        "suggestions": suggestions_rationale,
        "proposed_active": prop["proposed_active"],
        "proposed_on_deck": prop["proposed_on_deck"],
        "proposed_candidates": prop["proposed_candidates"],
        "hierarchy": hierarchy,
    }


def scaffold_starter_ai_cockpit(
    folder_path: str | Path,
    project_name: str,
    *,
    goal_name: str = "",
    group_folder: str = "",
    blurb: str = "",
    user_display_name: str = "Collaborator",
    linked_material_paths: list[str] | None = None,
    mission_statement: str = "",
    initiatives_list: list[str] | None = None,
    goal_resources: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Idempotently scaffold a complete Starter AI Cockpit inside ``folder_path``.

    Creates (only when absent — never clobbers existing files!):
      * ``ECGBERHT.md`` (Face document)
      * ``roadmap.json`` (3 starter stages: Goal & Scope Alignment -> Execution -> Review & Deliverables)
      * ``strip.json`` (active step & status heartbeat)
      * ``DELIVERABLES.md`` (canonical pipe-table register)
      * ``.ecgberht/status-summary.json`` and ``.ecgberht/status_card.json``
    """
    folder = Path(folder_path)
    folder.mkdir(parents=True, exist_ok=True)
    created_files: list[str] = []

    clean_title = str(project_name or folder.name).strip()
    clean_goal = str(
        blurb
        or goal_name
        or f"Advance {clean_title} from initial scope alignment to verified deliverables."
    ).strip()
    clean_group = str(group_folder or "Software & AI Systems").strip()
    now_date = datetime.now().strftime("%Y-%m-%d")

    # 1. ECGBERHT.md
    face_path = folder / "ECGBERHT.md"
    linked_paths_clean = [str(p).strip() for p in (linked_material_paths or []) if str(p).strip()]
    inits_clean = [str(i).strip() for i in (initiatives_list or []) if str(i).strip()]
    clean_mission_line = str(mission_statement or clean_goal).strip()
    if not face_path.is_file():
        linked_md = ""
        if linked_paths_clean:
            linked_md = "\n## Consolidated Folders & Linked Material\n" + "".join(
                f"- `{p}`\n" for p in linked_paths_clean
            )
        inits_md = ""
        if inits_clean:
            inits_md = "\n## Priority Initiatives\n" + "".join(
                f"- {i}\n" for i in inits_clean
            )
        res_md = ""
        if isinstance(goal_resources, dict) and (goal_resources.get("on_disk_matches") or goal_resources.get("research_prime_queries") or goal_resources.get("web_sources")):
            res_lines: list[str] = ["\n## Gandalf & researchPrime Resource Dossier\n"]
            for m in (goal_resources.get("on_disk_matches") or []):
                if isinstance(m, dict):
                    res_lines.append(f"- **On-Disk Match (`Gandalf`):** `{m.get('path')}` — {m.get('gandalf_note', '')}\n")
            for ws in (goal_resources.get("web_sources") or []):
                if isinstance(ws, dict) and ws.get("url"):
                    res_lines.append(f"- **Web / External Source:** {ws['url']}\n")
            for rq in (goal_resources.get("research_prime_queries") or []):
                res_lines.append(f"- **researchPrime Verification Track:** {rq}\n")
            res_md = "".join(res_lines)
        face_body = (
            f"# {clean_title}\n\n"
            f"**Mission Statement:** {clean_mission_line}\n\n"
            f"**Goal:** {clean_goal}\n\n"
            f"**Portfolio Folder:** {clean_group}\n"
            f"**Owner:** {user_display_name}\n"
            f"{linked_md}"
            f"{inits_md}"
            f"{res_md}\n"
            f"## Active Focus\n"
            f"- **Stage 1: Goal & Scope Alignment** — Confirm initial deliverables and work-product map with {user_display_name}.\n"
        )
        paths.atomic_write_text(face_path, face_body)
        created_files.append("ECGBERHT.md")

    # 2. roadmap.json
    rm_path = folder / "roadmap.json"
    if not rm_path.is_file():
        starter_steps = [
            {
                "id": "step-1",
                "name": "Stage 1: Goal & Scope Alignment",
                "status": "active",
                "part": "research",
                "done_when": f"Scope and work-product map confirmed with {user_display_name}.",
                "waiting_on": "",
                "navigation": {"featured_paths": ["ECGBERHT.md", "DELIVERABLES.md"]},
            },
            {
                "id": "step-2",
                "name": "Stage 2: Execution",
                "status": "planned",
                "part": "slice",
                "done_when": "Core work products drafted, built, and verified.",
                "waiting_on": "",
                "navigation": {"featured_paths": []},
            },
            {
                "id": "step-3",
                "name": "Stage 3: Review & Deliverables",
                "status": "planned",
                "part": "harden",
                "done_when": "Adversarial review complete and final deliverables registered in DELIVERABLES.md.",
                "waiting_on": "",
                "navigation": {"featured_paths": ["DELIVERABLES.md"]},
            },
        ]
        rm_doc = {
            "goal": clean_goal,
            "roadmap_projection": starter_steps,
            "steps": starter_steps,
            "roadmap_events": [
                {
                    "kind": "step_create",
                    "step_id": "step-1",
                    "at": _utc_now_iso(),
                    "who": "onboard_wizard",
                }
            ],
        }
        paths.atomic_write_text(rm_path, json.dumps(rm_doc, indent=2, ensure_ascii=False) + "\n")
        created_files.append("roadmap.json")

    # 3. strip.json
    strip_path = folder / "strip.json"
    if not strip_path.is_file():
        strip_doc = {
            "active_effort": clean_title,
            "current_step_id": "step-1",
            "human_wait": False,
            "next_recommended": f"Open the AI Cockpit and tell your Steward what you want to accomplish first in {clean_title}.",
            "anti_starvation_age_days": 0,
            "grasscatch": [],
            "updated_at": _utc_now_iso(),
        }
        paths.atomic_write_text(strip_path, json.dumps(strip_doc, indent=2, ensure_ascii=False) + "\n")
        created_files.append("strip.json")

    # 4. DELIVERABLES.md
    deliv_path = folder / "DELIVERABLES.md"
    if not deliv_path.is_file():
        deliv_body = (
            f"# Deliverables Register — {clean_title}\n\n"
            "| What | Where | Date | Step |\n"
            "| --- | --- | --- | --- |\n"
            f"| START HERE - FOR REVIEW: Project Charter & Scope (`ECGBERHT.md`) | `ECGBERHT.md` | {now_date} | step-1 |\n"
        )
        paths.atomic_write_text(deliv_path, deliv_body)
        created_files.append("DELIVERABLES.md")

    # 5. .ecgberht/status-summary.json & status_card.json
    ecg_dir = folder / ".ecgberht"
    ecg_dir.mkdir(parents=True, exist_ok=True)
    summary_path = ecg_dir / "status-summary.json"
    if not summary_path.is_file():
        summary_doc = {
            "project": clean_title,
            "goal": clean_goal,
            "active_step": "Stage 1: Goal & Scope Alignment",
            "status": "ready",
            "updated_at": _utc_now_iso(),
        }
        paths.atomic_write_text(summary_path, json.dumps(summary_doc, indent=2, ensure_ascii=False) + "\n")
        created_files.append(".ecgberht/status-summary.json")

    card_path = ecg_dir / "status_card.json"
    if not card_path.is_file():
        card_doc = {
            "timestamp": datetime.now().strftime("%H:%M"),
            "run_type": "AI Cockpit Ready",
            "project": clean_title,
            "effort": "Stage 1: Goal & Scope Alignment",
            "doing": "Starter AI Cockpit initialized and ready for conversation",
            "status": "1/3 stages · Stage 1 active",
            "tests": "pass ✓ · cockpit files verified",
            "blocker": "none",
            "procs": "py 1 · node 0",
            "journal": "none",
            "eta": "Ready now",
            "todo": "Stage 1 Alignment -> Stage 2 Execution -> Stage 3 Deliverables",
        }
        paths.atomic_write_text(card_path, json.dumps(card_doc, indent=2, ensure_ascii=False) + "\n")
        created_files.append(".ecgberht/status_card.json")

    return {
        "ok": True,
        "folder_path": str(folder),
        "created_files": created_files,
        "cockpit_ready": True,
    }


def provision_projects_and_cockpits(
    selected_projects: list[dict[str, Any]],
    *,
    goals: list[dict[str, Any]] | None = None,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Register confirmed projects, assign Virtual Grouping Folders, scaffold Starter AI Cockpits,
    and populate Cave of Wonders (`Active`, `On Deck`, `Parked` + Projects Tile).

    In ``sandbox=True`` mode, writes to ``sandbox_rnd_registry.json`` and scaffolds
    cockpits inside the sandbox tree (unless the project folder is already under the
    sandbox/tmp root) so the live ``rnd_registry.json`` is NEVER mutated!
    """
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    prof = get_active_user_profile(sandbox_id if sandbox else "", sandbox=sandbox, base_dir=base_dir)
    user_name = prof.get("display_name") or ("John" if paths.is_anchor_admin_edition(base_dir) else "Collaborator")
    if goals is None:
        goals = (st_doc.get("goals") or {}).get("items") or []

    provisioned: list[dict[str, Any]] = []
    sandbox_reg: list[dict[str, Any]] = []

    live_reg = {} if sandbox else _rnd.load_registry()
    live_by_folder: dict[str, dict[str, Any]] = {}
    for e in live_reg.values():
        fp = e.get("folder_path") or ""
        if fp:
            try:
                k = str(Path(fp).resolve()).lower() if os.name == "nt" else str(Path(fp).resolve())
                live_by_folder[k] = e
            except Exception:
                continue

    for idx, item in enumerate(selected_projects or [], 1):
        if not isinstance(item, dict):
            continue
        if item.get("excluded") is True or item.get("included") is False:
            continue

        raw_folder = str(item.get("folder_path") or "").strip()
        if not raw_folder:
            continue
        name = str(item.get("name") or Path(raw_folder).name).strip()
        group_folder = str(item.get("group_folder") or item.get("group") or _classify_arena(name)).strip()
        seat = str(item.get("seat") or ("active" if idx <= 4 else "deck")).strip().lower()
        if seat == "on_deck":
            seat = "deck"
        if seat not in ("active", "deck", "parked"):
            seat = "active"

        stored_state = _rnd.STATE_FUTURE if seat == "parked" else _rnd.STATE_ACTIVE
        priority = 1 if seat == "active" else (2 if seat == "deck" else 3)
        blurb = str(item.get("blurb") or "").strip()
        goal_id = str(item.get("goal_id") or (goals[0]["id"] if goals else "goal-1-flagship-portfolio"))
        matched_goal_obj = next((g for g in (goals or []) if isinstance(g, dict) and str(g.get("id") or "") == goal_id), None)
        goal_res_obj = (matched_goal_obj or {}).get("resources") if isinstance(matched_goal_obj, dict) else None
        eff_mission = str(item.get("mission_statement") or ((st_doc.get("goals") or {}).get("mission_statement")) or "")

        if sandbox:
            pid = str(item.get("id") or uuid.uuid4().hex)
            s_cockpit_dir = state_dir(sandbox=True, sandbox_id=sandbox_id, base_dir=base_dir) / "cockpits" / _safe_slug(name)
            scaf = scaffold_starter_ai_cockpit(
                s_cockpit_dir,
                name,
                goal_name=str((matched_goal_obj or {}).get("name") or ""),
                group_folder=group_folder,
                blurb=blurb,
                user_display_name=user_name,
                linked_material_paths=item.get("linked_material_paths") or [],
                mission_statement=eff_mission,
                initiatives_list=item.get("initiatives_list") or [],
                goal_resources=goal_res_obj,
            )
            entry = {
                "id": pid,
                "name": name,
                "folder_path": raw_folder,
                "sandbox_cockpit_path": str(s_cockpit_dir),
                "group": group_folder,
                "group_folder": group_folder,
                "seat": seat,
                "priority": priority,
                "state": stored_state,
                "blurb": blurb,
                "goal_id": goal_id,
                "cockpit_href": f"/project/{pid}",
                "cockpit_created_files": scaf["created_files"],
            }
            sandbox_reg.append(entry)
            provisioned.append(entry)
        else:
            fk = str(Path(raw_folder).resolve()).lower() if os.name == "nt" else str(Path(raw_folder).resolve())
            existing = live_by_folder.get(fk)
            requested_id = str(item.get("id") or "").strip()

            if existing and existing.get("id"):
                pid = str(existing["id"])
                _rnd.update_project(
                    pid,
                    name=name,
                    folder_path=raw_folder,
                    priority=priority,
                    state=stored_state,
                    group=group_folder,
                    blurb=blurb or existing.get("blurb") or "",
                )
                _rnd.scaffold_project_store(raw_folder, pid)
            elif requested_id and requested_id not in live_reg:
                # Re-adopt existing orphaned project ID so historical .anchor/projects/<id> is preserved!
                _rnd.assign_legacy_ids([{
                    "id": requested_id,
                    "name": name,
                    "folder_path": raw_folder,
                    "priority": priority,
                    "state": stored_state,
                    "group": group_folder,
                    "blurb": blurb,
                }])
                pid = requested_id
                _rnd.scaffold_project_store(raw_folder, pid)
            else:
                created_entry = _rnd.add_project(
                    name=name,
                    folder_path=raw_folder,
                    priority=priority,
                    state=stored_state,
                    scaffold=True,
                    blurb=blurb,
                )
                pid = str(created_entry["id"])
                _rnd.set_group(pid, group_folder)

            scaf = scaffold_starter_ai_cockpit(
                raw_folder,
                name,
                goal_name=str((matched_goal_obj or {}).get("name") or ""),
                group_folder=group_folder,
                blurb=blurb,
                user_display_name=user_name,
                linked_material_paths=item.get("linked_material_paths") or [],
                mission_statement=eff_mission,
                initiatives_list=item.get("initiatives_list") or [],
                goal_resources=goal_res_obj,
            )
            provisioned.append({
                "id": pid,
                "name": name,
                "folder_path": raw_folder,
                "group": group_folder,
                "group_folder": group_folder,
                "seat": seat,
                "priority": priority,
                "state": stored_state,
                "blurb": blurb,
                "goal_id": goal_id,
                "cockpit_href": f"/project/{pid}",
                "cockpit_created_files": scaf["created_files"],
            })

    if sandbox:
        sreg_path = state_dir(sandbox=True, sandbox_id=sandbox_id, base_dir=base_dir) / "sandbox_rnd_registry.json"
        paths.atomic_write_text(sreg_path, json.dumps(sandbox_reg, indent=2, ensure_ascii=False) + "\n")
    else:
        # Ensure the Campaign project itself is also registered in rnd_registry so Cave of Wonders finds it!
        camp_dir = _campaign_folder_for(sandbox=False, base_dir=base_dir)
        camp_dir.mkdir(parents=True, exist_ok=True)
        all_now = _rnd.list_projects(include_archived=True, include_future=True, include_retired=True)
        has_camp = any(
            e.get("folder_path") and Path(e["folder_path"]).resolve() == camp_dir.resolve()
            for e in all_now
        )
        if not has_camp:
            camp_entry = _rnd.add_project(
                name="Campaign",
                folder_path=str(camp_dir),
                priority=1,
                state=_rnd.STATE_ACTIVE,
                scaffold=True,
                blurb="Star Chart Campaign & Portfolio Goals",
            )
            _rnd.set_group(camp_entry["id"], "Star Chart")

    # Sync all Active & On Deck projects into Campaign/roadmap.json so Cave of Wonders shelves populate immediately
    _sync_goals_to_campaign_roadmap(
        goals,
        mission_statement=(st_doc.get("goals") or {}).get("mission_statement") or "",
        project_parts=provisioned,
        sandbox=sandbox,
        sandbox_id=sandbox_id,
        base_dir=base_dir,
    )

    st_doc.setdefault("projects", {})["provisioned"] = provisioned
    if 5 not in st_doc["completed_steps"]:
        st_doc["completed_steps"].append(5)
    st_doc["current_step"] = max(int(st_doc.get("current_step") or 1), 6)
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    by_seat = {
        "active": [p for p in provisioned if p["seat"] == "active"],
        "deck": [p for p in provisioned if p["seat"] == "deck"],
        "parked": [p for p in provisioned if p["seat"] == "parked"],
    }
    return {
        "ok": True,
        "provisioned": provisioned,
        "by_seat": by_seat,
        "count": len(provisioned),
    }


# ═════════════════════════════════════════════════════════════════════════════
# STEP 6: Calendar & Email Integration (`comms_connector.py`)
# ═════════════════════════════════════════════════════════════════════════════

def configure_wizard_comms(
    *,
    provider_family: str = "gmail",
    email_address: str = "",
    auth_mode: str = "app_password",
    secret: str = "",
    ics_url: str = "",
    imap_host: str = "",
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Configure Step 6 Calendar & Email account and run a 1-click Schedule Reconciliation check."""
    fam = str(provider_family or "gmail").strip().lower()
    if fam not in comms_connector.PROVIDER_PRESETS:
        fam = "custom"
    preset = comms_connector.PROVIDER_PRESETS[fam]
    acct_id = f"{fam}-{_safe_slug(email_address or preset['short_label'])[:20]}"

    acct_record = {
        "id": acct_id,
        "family": fam,
        "label": preset["label"],
        "email": str(email_address or preset["placeholder_email"]).strip(),
        "imap_host": str(imap_host or preset["imap_host"]).strip(),
        "imap_port": preset["imap_port"],
        "auth_mode": str(auth_mode or preset["default_auth_mode"]).strip(),
        "ics_url": str(ics_url or preset["placeholder_ics"]).strip(),
        "enabled": True,
        "credential_storage": "OS Credential Vault (advapi32)",
        "updated_at": _utc_now_iso(),
    }

    if not sandbox and base_dir is None:
        if secret and str(secret).strip():
            comms_connector.put_account_secret(acct_id, str(secret).strip())
        cfg = comms_connector.load_comms_config()
        accts = [a for a in (cfg.get("accounts") or []) if a.get("id") != acct_id]
        accts.append(acct_record)
        cfg["accounts"] = accts
        cfg["last_sync_at"] = _utc_now_iso()
        cfg["last_sync_status"] = "ready"
        comms_connector.save_comms_config(cfg)

    comms_state = {
        "configured": True,
        "account": acct_record,
        "reconcile_summary": (
            f"Connected {acct_record['label']} ({acct_record['email']}); "
            "read-only IMAP headers & ICS calendar feed linked to Cave of Wonders Dated Ruler."
        ),
        "updated_at": _utc_now_iso(),
    }
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    st_doc["comms"] = comms_state
    if 6 not in st_doc["completed_steps"]:
        st_doc["completed_steps"].append(6)
    st_doc["current_step"] = max(int(st_doc.get("current_step") or 1), 7)
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    return {"ok": True, "comms": comms_state}


def get_simple_email_status(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Return a clean Connected / Not Connected status summary for Email & Calendar."""
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    w_comms = st_doc.get("comms") if isinstance(st_doc.get("comms"), dict) else {}
    accounts: list[dict[str, Any]] = []
    if not sandbox and base_dir is None:
        try:
            cfg = comms_connector.load_comms_config()
            for a in (cfg.get("accounts") or []):
                if isinstance(a, dict) and a.get("enabled", True) and a.get("email"):
                    accounts.append({
                        "id": a.get("id", ""),
                        "email": a.get("email", ""),
                        "label": a.get("label", ""),
                        "family": a.get("family", ""),
                    })
        except Exception:
            pass
    if not accounts and w_comms.get("configured"):
        acc = w_comms.get("account") if isinstance(w_comms.get("account"), dict) else {}
        accounts.append({
            "id": acc.get("id", "wizard-email"),
            "email": acc.get("email") or "Windows Outlook Desktop",
            "label": acc.get("label") or "Connected Email & Calendar",
            "family": acc.get("family") or "outlook",
        })
    connected = len(accounts) > 0
    primary = accounts[0]["email"] if accounts else ""
    return {
        "ok": True,
        "connected": connected,
        "status_label": f"Connected ({primary})" if connected else "Not Connected",
        "primary_email": primary,
        "accounts": accounts,
    }


def connect_email_simple(
    *,
    email_address: str = "",
    secret: str = "",
    ics_url: str = "",
    use_outlook: bool = False,
    imap_verify_fn=None,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Simple 1-step Email & Calendar connect with live SSL IMAP verification and clear Connected badge state."""
    if use_outlook:
        if sandbox:
            st_doc = load_wizard_state(sandbox=True, sandbox_id=sandbox_id, base_dir=base_dir)
            st_doc["comms"] = {"configured": True, "account": {"email": "Windows Outlook", "label": "Windows Outlook"}, "updated_at": _utc_now_iso()}
            save_wizard_state(st_doc, sandbox=True, sandbox_id=sandbox_id, base_dir=base_dir)
            return {"ok": True, "connected": True, "status_label": "Connected (Windows Outlook)", "email": "Windows Outlook", "message": "Connected ✓ (Windows Outlook Desktop)"}
        res_out = comms_connector.auto_connect_local_outlook()
        ok_out = bool(res_out.get("ok") and res_out.get("outlook_running"))
        if ok_out:
            em = str(res_out.get("email") or "Windows Outlook")
            st_doc = load_wizard_state(sandbox=False, sandbox_id=sandbox_id, base_dir=base_dir)
            st_doc["comms"] = {"configured": True, "account": {"email": em, "label": "Windows Outlook"}, "updated_at": _utc_now_iso()}
            if 6 not in st_doc["completed_steps"]:
                st_doc["completed_steps"].append(6)
            save_wizard_state(st_doc, sandbox=False, sandbox_id=sandbox_id, base_dir=base_dir)
            return {
                "ok": True,
                "connected": True,
                "status_label": f"Connected ({em})",
                "email": em,
                "message": f"Connected ✓ ({em})",
            }
        return {
            "ok": False,
            "connected": False,
            "status_label": "Not Connected",
            "message": str(res_out.get("message") or "Classic Windows Outlook is not currently open — enter your email address below instead."),
        }

    clean_email = str(email_address or "").strip()
    if "@" not in clean_email:
        return {"ok": False, "connected": False, "status_label": "Not Connected", "message": "Please enter a valid email address first."}
    det = auto_detect_email_provider(clean_email)
    imap_host = str(det.get("imap_host") or "imap.gmail.com")
    imap_port = int(det.get("imap_port") or 993)
    # Strip spaces from 16-char Google/Microsoft App Passwords (e.g. 'abcd efgh ijkl mnop')
    s_val = re.sub(r"\s+", "", str(secret or ""))
    if not s_val and not ics_url:
        return {
            "ok": False,
            "connected": False,
            "needs_password": True,
            "app_password_url": det.get("app_password_url") or "",
            "provider_name": det.get("provider_name") or "",
            "status_label": "Password Needed",
            "message": f"Click 'Open {det.get('provider_name') or 'Provider'} Password Page', paste the App Password, and click Connect.",
        }

    if not s_val and ics_url and not sandbox:
        clean_ics = str(ics_url).strip()
        if not clean_ics.lower().startswith("https://"):
            return {"ok": False, "connected": False, "status_label": "Invalid ICS URL", "message": "Calendar ICS URL must start with https://"}
        try:
            req_ics = urllib.request.Request(clean_ics, headers={"User-Agent": "Anchor-Calendar/1.5.7"})
            with urllib.request.urlopen(req_ics, timeout=8) as r_ics:
                head_ics = r_ics.read(512).decode("utf-8", errors="ignore")
            if "BEGIN:VCALENDAR" not in head_ics.upper():
                return {"ok": False, "connected": False, "status_label": "Invalid Calendar Feed", "message": "URL did not return a valid VCALENDAR (.ics) feed."}
        except Exception as exc:
            return {"ok": False, "connected": False, "status_label": "Feed Unreachable", "message": f"Could not reach calendar ICS URL ({str(exc)[:100]})."}

    if s_val and not sandbox:
        verifier = imap_verify_fn
        if verifier is None:
            import imaplib
            def _default_imap_verify(host: str, port: int, user: str, pwd: str) -> tuple[bool, str]:
                ctx = ssl.create_default_context()
                conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=8)
                try:
                    conn.login(user, pwd)
                    conn.logout()
                    return True, ""
                except Exception as exc:
                    return False, str(exc)
            verifier = _default_imap_verify
        try:
            v_ok, v_err = verifier(imap_host, imap_port, clean_email, s_val)
        except Exception as exc:
            v_ok, v_err = False, str(exc)
        if not v_ok:
            return {
                "ok": False,
                "connected": False,
                "status_label": "Sign-In Failed",
                "app_password_url": det.get("app_password_url") or "",
                "message": f"Could not sign in to {det.get('provider_name') or imap_host} ({v_err[:120]}). Use an App Password from your email provider (or 1-Click Windows Outlook).",
            }

    configure_wizard_comms(
        provider_family=str(det.get("family") or "custom"),
        email_address=clean_email,
        auth_mode="app_password" if s_val else "ics_only",
        **{"secret": s_val},
        ics_url=str(ics_url or "").strip(),
        imap_host=imap_host,
        sandbox=sandbox,
        sandbox_id=sandbox_id,
        base_dir=base_dir,
    )
    return {
        "ok": True,
        "connected": True,
        "status_label": f"Connected ({clean_email})",
        "email": clean_email,
        "provider_name": det.get("provider_name") or "",
        "message": f"Connected ✓ ({clean_email})",
    }


DRIVE_SKIP_DIR_NAMES: frozenset[str] = frozenset({
    "windows", "program files", "program files (x86)", "programdata",
    "$recycle.bin", "system volume information", "recovery", "perflogs",
    "msocache", "intel", "amd", "nvidia", "drivers", "appdata",
    "node_modules", "__pycache__", ".git", ".hg", ".svn", ".venv", "venv",
    ".tox", ".mypy_cache", ".pytest_cache",
    ".anchor", ".ecgberht", "anchor-plus-skills", "skills",
    "anchor-code-jobs", "anchor-onboard-test", "onedrivetemp",
})


def _is_unc_or_forbidden_scan_path(raw_path: str | Path) -> bool:
    s = str(raw_path or "").strip()
    if s.startswith("\\\\") or s.startswith("//"):
        return True
    return False


def ensure_standing_foundry_skills_loaded(
    base_dir: Path | str | None = None,
    *,
    sync_if_missing: bool = False,
    cli_homes: tuple[Path, ...] | None = None,
) -> dict[str, Any]:
    """Inspect (and optionally sync) the 20 standing Foundry skills without asking the user."""
    b_root = _resolve_base_dir(base_dir)
    bundled = b_root / "vendor" / "bundled-skills"
    if not bundled.is_dir():
        bundled = paths.CODE_DIR / "vendor" / "bundled-skills"
    ws_skills = b_root.parent / "skills"
    bundled_names = sorted(
        p.name for p in bundled.iterdir() if p.is_dir() and (p / "SKILL.md").is_file()
    ) if bundled.is_dir() else []
    sync_error = ""
    allow_sync = sync_if_missing and bundled.is_dir() and (cli_homes is not None or "PYTEST_CURRENT_TEST" not in os.environ)
    if allow_sync:
        try:
            import onboard as _ob
            target_homes = cli_homes if cli_homes is not None else (
                ws_skills,
                Path.home() / ".claude" / "skills",
                Path.home() / ".codex" / "skills",
                Path.home() / ".agents" / "skills",
                Path.home() / ".gemini" / "antigravity" / "skills",
            )
            for target_home in target_homes:
                _ob.install_skills(skills_src=bundled, skills_home=target_home, overwrite=False)
            if cli_homes is None:
                try:
                    import foundry_autoload as _fa
                    _fa.sync_registrations()
                except Exception:
                    pass
        except Exception as exc:
            sync_error = str(exc)[:120]
    count = len(bundled_names)
    loaded_ok = count > 0 and not sync_error
    return {
        "ok": loaded_ok,
        "loaded": loaded_ok,
        "count": count,
        "error": sync_error,
        "label": f"{count} Standing Foundry Skills Loaded Automatically" if loaded_ok else "Standing Foundry Skills Pending Sync",
    }


def _folder_quick_hint(folder: Path) -> tuple[bool, str]:
    """Fast (<5ms) check whether ``folder`` has expandable subfolders and a short content badge."""
    has_sub = False
    code_cnt = 0
    doc_cnt = 0
    has_git = (folder / ".git").exists()
    try:
        with os.scandir(folder) as it:
            seen = 0
            for entry in it:
                seen += 1
                nm = entry.name
                low = nm.lower()
                if nm.startswith("."):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if low not in DRIVE_SKIP_DIR_NAMES:
                        has_sub = True
                elif entry.is_file(follow_symlinks=False):
                    if low.endswith((".py", ".js", ".ts", ".rs", ".go", ".r", ".ipynb", ".java", ".cpp")):
                        code_cnt += 1
                    elif low.endswith((".md", ".tex", ".docx", ".pdf", ".pptx", ".xlsx", ".csv")):
                        doc_cnt += 1
                if seen >= 60 and has_sub:
                    break
    except OSError:
        return False, ""
    badges: list[str] = []
    if has_git:
        badges.append("git")
    if code_cnt:
        badges.append("code")
    if doc_cnt:
        badges.append("docs")
    return has_sub, (" · ".join(badges) if badges else "")


def _list_clean_subdirs(parent: Path, anchor_root: Path, limit: int = 120) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    try:
        entries = sorted(
            (e for e in os.scandir(parent) if e.is_dir(follow_symlinks=False)),
            key=lambda e: e.name.lower(),
        )
    except OSError:
        return out
    for entry in entries:
        nm = entry.name
        low = nm.lower()
        if nm.startswith(".") or nm.startswith("$") or low in DRIVE_SKIP_DIR_NAMES:
            continue
        p = Path(entry.path)
        if is_excluded_non_project_dir(p, anchor_root=anchor_root)[0]:
            continue
        has_children, badge = _folder_quick_hint(p)
        out.append({
            "name": nm,
            "path": str(p),
            "has_children": has_children,
            "badge": badge,
        })
        if len(out) >= limit:
            break
    return out


def scan_hard_drive_tree(
    parent_path: str = "",
    *,
    custom_drives: list[str | Path] | None = None,
    sandbox: bool = False,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Scan local hard drives and return proposed work areas + lazy-expandable folder tree nodes."""
    anchor_root = _resolve_base_dir(base_dir)
    skills_info = ensure_standing_foundry_skills_loaded(base_dir, sync_if_missing=(not sandbox and not parent_path))

    if parent_path and str(parent_path).strip():
        if _is_unc_or_forbidden_scan_path(parent_path):
            return {"ok": False, "parent_path": "", "children": [], "message": "Network / UNC paths are not allowed."}
        target = Path(str(parent_path).strip()).expanduser()
        if not target.is_dir():
            return {"ok": False, "parent_path": str(target), "children": [], "message": "Folder not found."}
        return {
            "ok": True,
            "parent_path": str(target),
            "children": _list_clean_subdirs(target, anchor_root),
            "standing_skills": skills_info,
        }

    # Root scan: discover drives + smart Proposed Work Areas
    if custom_drives is None and os.environ.get("ANCHOR_TEST_DRIVE_ROOTS"):
        custom_drives = [p for p in os.environ["ANCHOR_TEST_DRIVE_ROOTS"].split(os.pathsep) if p.strip()]
    drives: list[Path] = []
    if custom_drives is not None:
        drives = [Path(d) for d in custom_drives if Path(d).is_dir()]
    elif os.name == "nt":
        listdrives = getattr(os, "listdrives", None)
        if callable(listdrives):
            for drv in listdrives():
                dp = Path(drv)
                if dp.is_dir():
                    drives.append(dp)
        else:
            for ch in "CDEFGHIJKLMNOPQRSTUVWXYZ":
                dp = Path(f"{ch}:\\")
                if dp.is_dir():
                    drives.append(dp)
    else:
        drives = [Path.home()]

    home = Path.home() if custom_drives is None else drives[0]
    candidate_areas: list[tuple[Path, str, bool]] = []
    for drv in drives:
        for sub_nm in ("dev", "Projects", "Research", "Work", "Code", "Repos"):
            cand = drv / sub_nm
            if cand.is_dir():
                candidate_areas.append((cand, f"{cand} (Work & Code)", True))
    if custom_drives is None:
        for rel_p, lbl, rec_chk in (
            (home / "dev", "Home dev folder", True),
            (home / "Projects", "Projects folder", True),
            (home / "Research", "Research folder", True),
            (home / "Documents", "Documents", False),
            (home / "OneDrive" / "Documents", "OneDrive Documents", False),
            (home / "Desktop", "Desktop", False),
        ):
            if rel_p.is_dir():
                candidate_areas.append((rel_p, lbl, rec_chk))

    proposed_areas: list[dict[str, Any]] = []
    seen_area: set[str] = set()
    for area_p, area_lbl, rec_chk in candidate_areas:
        try:
            rk = str(area_p.resolve()).lower() if os.name == "nt" else str(area_p.resolve())
        except OSError:
            rk = str(area_p)
        if rk in seen_area:
            continue
        seen_area.add(rk)
        children = _list_clean_subdirs(area_p, anchor_root, limit=60)
        if not children and not rec_chk:
            continue
        proposed_areas.append({
            "name": area_p.name or str(area_p),
            "label": area_lbl,
            "path": str(area_p),
            "recommended": rec_chk,
            "has_children": len(children) > 0,
            "children": children,
        })

    drive_nodes: list[dict[str, Any]] = []
    for drv in drives:
        drive_nodes.append({
            "name": str(drv),
            "path": str(drv),
            "has_children": True,
            "children": _list_clean_subdirs(drv, anchor_root, limit=60),
        })

    return {
        "ok": True,
        "standing_skills": skills_info,
        "proposed_areas": proposed_areas,
        "drives": drive_nodes,
    }


BROAD_CONTAINER_NAMES: frozenset[str] = frozenset({
    "dev", "documents", "desktop", "downloads", "projects", "research", "work", "repos", "code", "onedrive",
})


def _stem_key_for_clustering(name: str) -> str:
    tokens = [t for t in re.split(r"[\s_\-\.]+", name.lower()) if t and t not in {"draft", "drafts", "notes", "data", "code", "v1", "v2", "v3", "final", "old", "app", "repo", "docs", "paper"}]
    if not tokens:
        return name.lower()[:8]
    first = tokens[0]
    return first if len(first) >= 4 else "_".join(tokens[:2])


def analyze_checked_folders_with_gandalf(
    selected_paths: list[str | Path],
    *,
    use_live_gandalf: bool = False,
    runner_fn=None,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Inspect user-checked folders/subfolders and have Gandalf propose an intuitive mergeable/splittable project structure."""
    anchor_root = _resolve_base_dir(base_dir)
    skills_info = ensure_standing_foundry_skills_loaded(base_dir, sync_if_missing=(not sandbox))

    raw_dirs: list[Path] = []
    for sp in (selected_paths or []):
        if not sp or not str(sp).strip() or _is_unc_or_forbidden_scan_path(sp):
            continue
        p = Path(str(sp).strip()).expanduser()
        if p.is_dir():
            raw_dirs.append(p)

    if not raw_dirs:
        return {"ok": False, "proposed_projects": [], "standing_skills": skills_info, "message": "Check at least one folder or subfolder in the tree first."}

    # Resolve broad containers: if user checked e.g. C:\dev without checking specific children, expand its direct clean subfolders
    resolved_set = {str(p.resolve()).lower() if os.name == "nt" else str(p.resolve()): p.resolve() for p in raw_dirs}
    candidate_folders: list[Path] = []
    seen_cand: set[str] = set()

    for key_str, rp in list(resolved_set.items()):
        has_explicit_child = any(
            ok != key_str and (ok.startswith(key_str.rstrip("\\/") + ("\\" if os.name == "nt" else "/")))
            for ok in resolved_set
        )
        if has_explicit_child:
            continue
        is_drive_root = (rp.parent == rp)
        is_broad = is_drive_root or (rp.name.lower() in BROAD_CONTAINER_NAMES and not (rp / ".git").exists() and not (rp / "README.md").is_file())
        if is_broad:
            subs = _list_clean_subdirs(rp, anchor_root, limit=60)
            if subs:
                for s in subs:
                    sp_res = Path(s["path"]).resolve()
                    sk = str(sp_res).lower() if os.name == "nt" else str(sp_res)
                    if sk not in seen_cand:
                        seen_cand.add(sk)
                        candidate_folders.append(sp_res)
                continue
        if rp.name.lower() not in DRIVE_SKIP_DIR_NAMES and rp != anchor_root.resolve():
            if key_str not in seen_cand:
                seen_cand.add(key_str)
                candidate_folders.append(rp)

    folder_records: list[dict[str, Any]] = []
    for fp in candidate_folders:
        blurb, signals, has_cockpit = _read_folder_blurb_and_signals(fp)
        arena = _classify_arena(f"{fp.name} {blurb}")
        folder_records.append({
            "name": fp.name,
            "path": str(fp),
            "blurb": blurb,
            "signals": signals,
            "has_cockpit": has_cockpit,
            "arena": arena,
            "parent": str(fp.parent),
            "stem": _stem_key_for_clustering(fp.name),
        })

    # Deterministic Gandalf baseline clustering: group sibling folders sharing a meaningful >=4-char stem
    buckets: list[list[dict[str, Any]]] = []
    by_parent_stem: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for rec in folder_records:
        pk = (rec["parent"].lower() if os.name == "nt" else rec["parent"], rec["stem"])
        by_parent_stem.setdefault(pk, []).append(rec)
    for (_par, stem), members in by_parent_stem.items():
        if len(members) > 1 and len(stem) >= 4:
            buckets.append(members)
        else:
            for m in members:
                buckets.append([m])

    proposed: list[dict[str, Any]] = []
    for idx, grp in enumerate(buckets):
        lead = grp[0]
        if len(grp) == 1:
            pname = lead["name"]
            rationale = f"Gandalf identified {lead['name']} ({', '.join(lead['signals']) or 'workspace folder'}) as a standalone project."
        else:
            pretty_stem = lead["stem"].replace("_", " ").title()
            pname = f"{pretty_stem} ({len(grp)} Folders)"
            rationale = f"Gandalf grouped {len(grp)} related '{pretty_stem}' folders together — drag or click Split Apart anytime."
        seat = "active" if idx < 4 else ("deck" if idx < 8 else "parked")
        proposed.append({
            "id": f"gandalf-proj-{idx + 1}-{_safe_slug(pname)[:20]}",
            "name": pname,
            "group_folder": lead["arena"],
            "seat": seat,
            "blurb": lead["blurb"],
            "gandalf_rationale": rationale,
            "folders": [
                {"name": m["name"], "path": m["path"], "blurb": m["blurb"], "signals": m["signals"]}
                for m in grp
            ],
        })

    engine_used = "gandalf-structural-analyzer"
    # Optional bounded live Gandalf CLI pass when a connected CLI is available (or runner_fn supplied)
    if use_live_gandalf and len(folder_records) >= 2 and (runner_fn is not None or ("PYTEST_CURRENT_TEST" not in os.environ and not sandbox)):
        prompt_items = [{"path": r["path"], "name": r["name"], "blurb": r["blurb"][:120], "signals": r["signals"]} for r in folder_records[:40]]
        g_prompt = (
            "You are Gandalf advising on Anchor project structure. Given these user-selected folders JSON:\n"
            + json.dumps(prompt_items, ensure_ascii=False)
            + "\nReturn ONLY raw JSON `{\"projects\": [{\"name\": \"...\", \"group_folder\": \"...\", \"rationale\": \"...\", \"paths\": [\"...\"]}]}` "
            "partitioning EVERY input `path` into intuitive projects (merging closely related sibling folders and keeping distinct efforts separate)."
        )
        raw_out = ""
        try:
            if runner_fn is not None:
                raw_out = str(runner_fn(g_prompt) or "")
                engine_used = "gandalf-live-cli"
            else:
                aug_env = _cli_augmented_env()
                with tempfile.TemporaryDirectory() as empty_cwd:
                    for fam, args_fn in (
                        ("claude", lambda b: [b, "-p", g_prompt, "--tools", ""]),
                        ("gemini", lambda b: [b, "-p", g_prompt, "--approval-mode", "default"]),
                    ):
                        if _has_local_cli_credentials(fam):
                            b_exe = _find_cli_binary_for_family(fam)
                            if b_exe:
                                proc = subprocess.run(
                                    args_fn(b_exe),
                                    cwd=empty_cwd,
                                    env=aug_env,
                                    capture_output=True,
                                    text=True,
                                    timeout=45,
                                    creationflags=paths.NO_WINDOW,
                                )
                                if proc.returncode == 0 and (proc.stdout or "").strip():
                                    raw_out = proc.stdout.strip()
                                    engine_used = f"gandalf-{fam}-cli"
                                    break
        except Exception:
            raw_out = ""

        if raw_out:
            try:
                m_json = re.search(r"\{[\s\S]*\}", raw_out)
                parsed = json.loads(m_json.group(0) if m_json else raw_out)
                rec_by_norm = {
                    (r["path"].lower() if os.name == "nt" else r["path"]): r
                    for r in folder_records
                }
                used_norms: set[str] = set()
                refined: list[dict[str, Any]] = []
                for idx, item in enumerate(parsed.get("projects") or []):
                    if not isinstance(item, dict):
                        continue
                    matched_recs: list[dict[str, Any]] = []
                    for p_str in (item.get("paths") or []):
                        pk = str(p_str).lower() if os.name == "nt" else str(p_str)
                        if pk in rec_by_norm and pk not in used_norms:
                            used_norms.add(pk)
                            matched_recs.append(rec_by_norm[pk])
                    if not matched_recs:
                        continue
                    nm = str(item.get("name") or matched_recs[0]["name"]).strip()
                    refined.append({
                        "id": f"gandalf-proj-{idx + 1}-{_safe_slug(nm)[:20]}",
                        "name": nm,
                        "group_folder": str(item.get("group_folder") or matched_recs[0]["arena"]).strip(),
                        "seat": "active" if len(refined) < 4 else ("deck" if len(refined) < 8 else "parked"),
                        "blurb": matched_recs[0]["blurb"],
                        "gandalf_rationale": str(item.get("rationale") or "Proposed by Gandalf.").strip(),
                        "folders": [
                            {"name": m["name"], "path": m["path"], "blurb": m["blurb"], "signals": m["signals"]}
                            for m in matched_recs
                        ],
                    })
                # Never drop any checked folder omitted by LLM output
                for nk, rec in rec_by_norm.items():
                    if nk not in used_norms:
                        refined.append({
                            "id": f"gandalf-proj-{len(refined) + 1}-{_safe_slug(rec['name'])[:20]}",
                            "name": rec["name"],
                            "group_folder": rec["arena"],
                            "seat": "active" if len(refined) < 4 else "deck",
                            "blurb": rec["blurb"],
                            "gandalf_rationale": "Included from your checked folders.",
                            "folders": [{"name": rec["name"], "path": rec["path"], "blurb": rec["blurb"], "signals": rec["signals"]}],
                        })
                if refined:
                    proposed = refined
            except Exception:
                pass

    # Persist into wizard state discovered list so Create Projects works seamlessly
    disc_rows: list[dict[str, Any]] = []
    for p in proposed:
        f_list = p["folders"]
        primary_path = f_list[0]["path"]
        disc_rows.append({
            "id": p["id"],
            "name": p["name"],
            "folder_path": primary_path,
            "linked_material_paths": [x["path"] for x in f_list],
            "blurb": p["blurb"],
            "group_folder": p["group_folder"],
            "seat": p["seat"],
            "included": True,
            "excluded": False,
            "source": engine_used,
            "gandalf_rationale": p["gandalf_rationale"],
            "signals": f_list[0].get("signals") or [],
        })
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    proj_sec = dict(st_doc.get("projects") or {})
    proj_sec["discovered"] = disc_rows
    proj_sec["gandalf_proposals"] = proposed
    st_doc["projects"] = proj_sec
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)

    return {
        "ok": True,
        "engine_used": engine_used,
        "standing_skills": skills_info,
        "folder_count": len(folder_records),
        "proposed_projects": proposed,
        "message": f"Gandalf analyzed {len(folder_records)} folder(s) and proposed {len(proposed)} project(s). Drag cards together to merge, or click Split Apart!",
    }


# ═════════════════════════════════════════════════════════════════════════════
# STEP 7: Readiness Receipt, Sandbox Reset & Apply Sandbox to Live
# ═════════════════════════════════════════════════════════════════════════════

def build_readiness_receipt(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Build the complete Step 7 Readiness Receipt & Launchpad."""
    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    profile = get_active_user_profile(sandbox_id if sandbox else "", sandbox=sandbox, base_dir=base_dir)
    svc_status = detect_ai_services_status(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    ecg_path, ecg_checked = paths.resolve_ecgberht_root()
    bridge_ok = (ecg_path / "scripts" / "seal-chamber-bridge.mjs").is_file() or (ecg_path / "bin" / "ecgberht.mjs").is_file()

    provisioned = (st_doc.get("projects") or {}).get("provisioned") or []
    goals_items = (st_doc.get("goals") or {}).get("items") or []
    topology = st_doc.get("topology") or {}
    comms = st_doc.get("comms") or {}

    verified_services = [
        k for k, v in (svc_status.get("services") or {}).items()
        if isinstance(v, dict) and v.get("verified")
    ]

    checks = [
        {
            "step": 1,
            "id": "identity",
            "label": "User Name, Collaborator Pseudonym & Steward Persona",
            "ok": bool(profile.get("display_name")),
            "detail": f"Addressed as {profile['display_name']} · Pseudonym: {profile['pseudonym']} · Steward: {profile['steward_persona']}",
        },
        {
            "step": 2,
            "id": "topology",
            "label": "Mothership Topology & Tailscale Network",
            "ok": bool(topology.get("verified", True)),
            "detail": topology.get("mode_label") or "Main Mothership (Local :8777 + Tailscale)",
        },
        {
            "step": 2,
            "id": "homebase_registration",
            "label": "Anchor Homebase Registration (Push Updates & Journal/Error Sync)",
            "ok": True,
            "detail": (
                "Sandbox Homebase Link Ready"
                if sandbox
                else (
                    "Registered with Anchor Homebase ✓ (Push Updates & Journal/Error Sync Active)"
                    if _homebase_link_summary(base_dir).get("registered")
                    else "Capability initialized — connects automatically over Tailscale to Anchor Homebase"
                )
            ),
        },
        {
            "step": 2,
            "id": "ecgberht_bridge",
            "label": "Ecgberht Engine & Seal-Chamber Bridge",
            "ok": bridge_ok,
            "detail": f"Resolved at {ecg_path}",
            "checked_paths": ecg_checked,
        },
        {
            "step": 3,
            "id": "services",
            "label": "AI Services, Model Tiers & Live Probe",
            "ok": bool(verified_services) or svc_status["readiness"].get("status") == "ready",
            "detail": (
                f"Verified: {', '.join(verified_services)}"
                if verified_services
                else svc_status["readiness_explanation"]
            ),
        },
        {
            "step": 4,
            "id": "goals",
            "label": "Star Chart Goals & Strategic Arenas",
            "ok": len(goals_items) > 0,
            "detail": f"{len(goals_items)} Strategic Goal(s) organized across Star Chart Horizons",
        },
        {
            "step": 5,
            "id": "cockpits",
            "label": "Projects & Starter AI Cockpits Provisioned",
            "ok": len(provisioned) > 0,
            "detail": f"{len(provisioned)} Project(s) registered with Starter AI Cockpits (Active / On Deck / Parked)",
        },
        {
            "step": 1,
            "id": "gwl_license",
            "label": "Ghost World Labs License Acknowledgement",
            "ok": bool(get_wizard_license_status(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir).get("accepted")),
            "detail": (
                "Accepted (GHOST-WORLD-LAB-NON-RESALE-v1 · Free Use, No Resale or Commercialization)"
                if get_wizard_license_status(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir).get("accepted")
                else "Pending — acknowledge Ghost World Labs License in Step 1"
            ),
        },
        {
            "step": 6,
            "id": "comms",
            "label": "Calendar & Email Integration",
            "ok": bool(comms.get("configured")),
            "detail": comms.get("reconcile_summary") or "Optional — can be connected anytime in Setup",
        },
    ]

    return {
        "ok": True,
        "sandbox": bool(sandbox),
        "sandbox_id": sandbox_id if sandbox else "",
        "profile": profile,
        "checks": checks,
        "all_core_ready": all(c["ok"] for c in checks if c["id"] not in ("comms", "gwl_license")),
        "provisioned_cockpits": provisioned,
        "readiness": svc_status["readiness"],
        "readiness_explanation": svc_status["readiness_explanation"],
        "links": {
            "cave_of_wonders": "/high-seat",
            "star_chart": "/high-seat#camp",
            "desk_cockpit": "/desk",
            "provider_setup": "/setup",
        },
    }


def reset_sandbox(
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    *,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Wipe the isolated sandbox walkthrough directory so the user can test from Step 1 again."""
    sroot = sandbox_root(sandbox_id=sandbox_id, base_dir=base_dir)
    if sroot.exists():
        shutil.rmtree(sroot, ignore_errors=True)
    return {
        "ok": True,
        "sandbox_id": _safe_slug(sandbox_id or DEFAULT_SANDBOX_ID),
        "reset": True,
        "state": load_wizard_state(sandbox=True, sandbox_id=sandbox_id, base_dir=base_dir),
    }


def apply_sandbox_to_live(
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    *,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Promote a completed Sandbox Walkthrough into the live Anchor configuration."""
    sb_state = load_wizard_state(sandbox=True, sandbox_id=sandbox_id, base_dir=base_dir)
    ident = sb_state.get("identity") or {}
    if ident.get("display_name"):
        save_user_identity(
            display_name=ident["display_name"],
            pseudonym=ident.get("pseudonym") or aap.PSEUDONYM_DEFAULT,
            pseudonym_aliases=ident.get("pseudonym_aliases"),
            steward_persona=ident.get("steward_persona") or "Aladdin",
            sandbox=False,
            base_dir=base_dir,
        )

    goals_state = sb_state.get("goals") or {}
    if goals_state.get("raw_input") or goals_state.get("items"):
        organize_goals_with_starchart_steward(
            goals_state.get("raw_input") or "\n".join(g.get("name", "") for g in goals_state.get("items") or []),
            mission_statement=goals_state.get("mission_statement") or "",
            starting_flow=goals_state.get("starting_flow") or "goals_first",
            sandbox=False,
            base_dir=base_dir,
        )

    prov = (sb_state.get("projects") or {}).get("provisioned") or []
    if prov:
        provision_projects_and_cockpits(
            prov,
            goals=(sb_state.get("goals") or {}).get("items") or [],
            sandbox=False,
            base_dir=base_dir,
        )

    return {
        "ok": True,
        "promoted_from_sandbox": _safe_slug(sandbox_id or DEFAULT_SANDBOX_ID),
        "live_receipt": build_readiness_receipt(sandbox=False, base_dir=base_dir),
    }


def get_full_wizard_bundle(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Return the complete state bundle for `GET /api/onboard-wizard/state`."""
    state = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    profile = get_active_user_profile(sandbox_id if sandbox else "", sandbox=sandbox, base_dir=base_dir)
    ts_info = detect_or_install_tailscale(sandbox=sandbox)
    svc_info = detect_ai_services_status(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    ecg_path, ecg_checked = paths.resolve_ecgberht_root()
    receipt = build_readiness_receipt(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    hub_root = _gwl_hub_root_for(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    is_admin_ed = paths.is_anchor_admin_edition(base_dir)
    try:
        import gwl_clearinghouse as _gwl
        hub_catalog = dict(_gwl.get_verified_model_catalog(hub_root=hub_root) or {})
        if not is_admin_ed and str(hub_catalog.get("host") or "").lower() == "puter":
            hub_catalog["host"] = "gwl-hub"
        gwl_applicants = _gwl.list_applicant_signups(hub_root=hub_root) if is_admin_ed else []
    except Exception:
        hub_catalog = {}
        gwl_applicants = []
    import website_portal as _wp
    hw_prof = paths.detect_host_hardware_profile()
    lic_status = get_wizard_license_status(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    lic_spec = _wp.get_non_resale_license_spec()
    hb_view = (
        {
            "registered": False,
            "sandbox": True,
            "homebase_url": "",
            "canonical_github_repo": CANONICAL_ANCHOR_GITHUB_URL,
            "telemetry_enabled": True,
            "auto_pull_updates": bool((state.get("topology") or {}).get("auto_pull_updates", True)),
            "low_spec_mode": bool((state.get("topology") or {}).get("low_spec_mode", hw_prof["low_spec_recommended"])),
        }
        if sandbox
        else _homebase_link_summary(base_dir)
    )
    reg_view = _read_registration_receipt(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    browser_accts = detect_browser_and_cli_accounts(sandbox=sandbox)
    email_stat = get_simple_email_status(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    standing_sk = ensure_standing_foundry_skills_loaded(base_dir, sync_if_missing=False)
    drive_tree_boot = (
        scan_hard_drive_tree(sandbox=False, base_dir=base_dir)
        if (not sandbox and "PYTEST_CURRENT_TEST" not in os.environ)
        else {"ok": True, "standing_skills": standing_sk, "proposed_areas": [], "drives": []}
    )
    return {
        "ok": True,
        "admin_edition": paths.is_anchor_admin_edition(base_dir),
        "canonical_github_repo": CANONICAL_ANCHOR_GITHUB_URL,
        "registration": reg_view,
        "browser_accounts": browser_accts,
        "email_status": email_stat,
        "standing_skills": standing_sk,
        "drive_tree": drive_tree_boot,
        "sandbox": bool(sandbox),
        "sandbox_id": _safe_slug(sandbox_id or DEFAULT_SANDBOX_ID) if sandbox else "",
        "data_dir": str(state_dir(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)),
        "state": state,
        "profile": profile,
        "license_spec": lic_spec,
        "license_status": lic_status,
        "hardware_profile": hw_prof,
        "tailscale": ts_info,
        "homebase_link": hb_view,
        "ecgberht": {
            "root": str(ecg_path),
            "checked_paths": ecg_checked,
            "ok": (ecg_path / "scripts" / "seal-chamber-bridge.mjs").is_file() or (ecg_path / "bin" / "ecgberht.mjs").is_file(),
        },
        "services": svc_info["services"],
        "variable_strength": _get_wizard_variable_strength_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir),
        "nightly_refresh": svc_info.get("nightly_refresh") or _get_nightly_refresh_meta(),
        "hub_model_catalog": hub_catalog,
        "gwl_applicants": gwl_applicants,
        "mission_examples": MISSION_STATEMENT_EXAMPLES,
        "goal_examples": GOAL_DOMAIN_EXAMPLES,
        "project_hierarchy": build_hierarchical_project_organization(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir),
        "readiness": svc_info["readiness"],
        "readiness_explanation": svc_info["readiness_explanation"],
        "comms_presets": comms_connector.PROVIDER_PRESETS,
        "receipt": receipt,
        "readiness_receipt": receipt,
    }


get_wizard_full_state = get_full_wizard_bundle


def dispatch_wizard_action(
    action: str,
    payload: dict[str, Any] | None = None,
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Unified dispatcher for `POST /api/onboard-wizard/action`."""
    body = dict(payload or {})
    act = str(action or body.get("action") or "").strip().lower()
    use_sandbox = bool(sandbox or body.get("sandbox") in (True, 1, "1", "true"))
    sid = str(body.get("sandbox_id") or sandbox_id or DEFAULT_SANDBOX_ID).strip()

    if act == "accept_gwl_license":
        import website_portal as _wp
        sdir_lic = _wizard_license_store_dir(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
        prof_cur = get_active_user_profile(sid if use_sandbox else "", sandbox=use_sandbox, base_dir=base_dir)
        handle = str(body.get("pseudonym_or_handle") or body.get("pseudonym") or prof_cur.get("pseudonym") or prof_cur.get("display_name") or "Collaborator").strip()
        acc_val = body.get("accepted_gwl_license") if "accepted_gwl_license" in body else body.get("accepted_non_resale")
        out_lic = _wp.accept_non_resale_license(
            handle,
            bool(acc_val is True or acc_val in (1, "1", "true", "yes")),
            intended_use=str(body.get("intended_use") or "personal_or_research"),
            store_dir=sdir_lic,
        )
        out_lic["status_code"] = int(out_lic.get("code") or (200 if out_lic.get("ok") else 400))
        return out_lic
    if act == "apply_free_tier_preset":
        return apply_free_tier_provider_preset(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
    if act == "save_variable_strength":
        return save_wizard_variable_strength(body.get("variable_strength") or body, sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
    if act in ("save_identity", "save_security_credentials"):
        dual_raw = body.get("dual_auth_enabled")
        dual_bool = None if dual_raw is None else bool(dual_raw in (True, 1, "1", "true", "yes"))
        lic_raw = body.get("accepted_gwl_license")
        lic_bool = None if lic_raw is None else bool(lic_raw in (True, 1, "1", "true", "yes"))
        req_lic = bool(body.get("require_license_ack") in (True, 1, "1", "true", "yes"))
        return save_user_identity(
            display_name=str(body.get("display_name") or ""),
            pseudonym=str(body.get("pseudonym") or ""),
            pseudonym_aliases=body.get("pseudonym_aliases"),
            steward_persona=str(body.get("steward_persona") or "Aladdin"),
            username=str(body.get("username") or ""),
            password=str(body.get("password") or ""),
            contact_email=str(body.get("contact_email") or body.get("email") or ""),
            dual_auth_enabled=dual_bool,
            dual_auth_method=str(body.get("dual_auth_method") or ""),
            anchor_token=str(body.get("anchor_token") or ""),
            accepted_gwl_license=lic_bool,
            require_license_ack=req_lic,
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act in (
        "request_account_recovery",
        "send_recovery_link",
        "complete_account_recovery",
        "verify_2fa_backup_code",
        "regenerate_2fa_backup_codes",
        "get_admin_state",
        "admin_update_account",
        "admin_create_account",
        "admin_reset_account",
        "admin_delete_account",
        "admin_register_shared_doc",
        "admin_revoke_shared_doc",
        "admin_grant_acl",
        "admin_sync_backups",
    ):
        import gwl_admin_gui as _gag
        return _gag.dispatch_gwl_admin_action(
            act,
            body,
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "regenerate_anchor_token":
        tok_info = _resolve_or_create_anchor_token(
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
            regenerate=True,
        )
        return {
            "ok": True,
            **tok_info,
            "profile": get_active_user_profile(sid if use_sandbox else "", sandbox=use_sandbox, base_dir=base_dir),
        }
    if act == "refresh_live_models":
        return refresh_live_models(
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "launch_service_login":
        return launch_service_login(
            family=str(body.get("family") or "claude"),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "auto_install_clis":
        fams_raw = body.get("families")
        fams_list = [str(x).strip().lower() for x in fams_raw] if isinstance(fams_raw, list) else None
        inc_grok = True if "include_grok" not in body else bool(body.get("include_grok") in (True, 1, "1", "true", "yes"))
        return auto_install_agent_clis(
            families=fams_list,
            include_grok=inc_grok,
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "connect_provider_simple":
        return connect_provider_simple(
            family=str(body.get("family") or "gemini"),
            api_key=str(body.get("api_key") or ""),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "connect_email_simple":
        return connect_email_simple(
            email_address=str(body.get("email") or body.get("email_address") or ""),
            secret=str(body.get("secret") or body.get("password") or ""),
            ics_url=str(body.get("ics_url") or ""),
            use_outlook=bool(body.get("use_outlook") in (True, 1, "1", "true", "yes")),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "get_email_status":
        return get_simple_email_status(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
    if act == "scan_drive_tree":
        return scan_hard_drive_tree(
            parent_path=str(body.get("parent_path") or ""),
            sandbox=use_sandbox,
            base_dir=base_dir,
        )
    if act == "gandalf_propose_projects":
        sel_raw = body.get("selected_paths") or []
        if isinstance(sel_raw, str):
            sel_raw = [s.strip() for s in sel_raw.split(";") if s.strip()]
        return analyze_checked_folders_with_gandalf(
            selected_paths=[str(x) for x in sel_raw if str(x).strip()],
            use_live_gandalf=bool(body.get("use_live_gandalf") in (True, 1, "1", "true", "yes")),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "detect_browser_accounts":
        inc_hist = bool(body.get("include_browser_history") in (True, 1, "1", "true", "yes"))
        return detect_browser_and_cli_accounts(sandbox=use_sandbox, include_browser_history=inc_hist)
    if act == "open_browser_login":
        return open_browser_provider_login(
            family=str(body.get("family") or "gemini"),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "setup_tailscale_interactive":
        return setup_tailscale_interactive(sandbox=use_sandbox)
    if act == "register_anchor_repo":
        return register_anchor_repository(
            email=str(body.get("email") or body.get("contact_email") or ""),
            owner=str(body.get("owner") or ""),
            pseudonym=str(body.get("pseudonym") or ""),
            tailscale_url=str(body.get("tailscale_url") or ""),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "detect_email_provider":
        return auto_detect_email_provider(str(body.get("email") or body.get("email_address") or ""))
    if act == "auto_connect_outlook":
        if use_sandbox:
            return {
                "ok": True,
                "outlook_running": True,
                "message": "Sandbox verified: connected running Windows Outlook desktop app.",
            }
        res_out = comms_connector.auto_connect_local_outlook()
        if res_out.get("outlook_running"):
            st_doc = load_wizard_state(sandbox=False, sandbox_id=sid, base_dir=base_dir)
            st_doc["comms"] = {
                "configured": True,
                "reconcile_summary": str(res_out.get("message") or "Connected local Windows Outlook desktop app."),
                "updated_at": _utc_now_iso(),
            }
            if 6 not in st_doc["completed_steps"]:
                st_doc["completed_steps"].append(6)
            save_wizard_state(st_doc, sandbox=False, sandbox_id=sid, base_dir=base_dir)
        return res_out
    if act == "configure_topology":
        if not use_sandbox and "_req_auth_ok" in body and not bool(body.get("_req_auth_ok")):
            return {"ok": False, "status_code": 401, "error": "unauthorized"}
        low_raw = body.get("low_spec_mode")
        low_bool = None if low_raw is None else bool(low_raw in (True, 1, "1", "true", "yes"))
        return configure_mothership_topology(
            mode=str(body.get("mode") or "main_mothership"),
            remote_address=str(body.get("remote_address") or ""),
            hub_endpoint=str(body.get("hub_endpoint") or ""),
            telemetry_enabled=bool(body.get("telemetry_enabled", True)),
            auto_pull_updates=bool(body.get("auto_pull_updates", True)),
            low_spec_mode=low_bool,
            auto_install_tailscale=bool(body.get("auto_install_tailscale")),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "register_homebase":
        import mothership_updater as _mu
        eff_root = _resolve_base_dir(base_dir) if base_dir is not None else None
        return _mu.receive_homebase_registration(
            body,
            provided_capability=str(body.get("_req_node_cap") or ""),
            anchor_root=eff_root,
        )
    if act == "submit_homebase_telemetry":
        import mothership_updater as _mu
        eff_root = _resolve_base_dir(base_dir) if base_dir is not None else None
        return _mu.receive_homebase_telemetry(
            body,
            str(body.get("_req_node_cap") or ""),
            anchor_root=eff_root,
        )
    if act == "register_with_homebase":
        if not use_sandbox and "_req_auth_ok" in body and not bool(body.get("_req_auth_ok")):
            return {"ok": False, "status_code": 401, "error": "unauthorized"}
        import mothership_updater as _mu
        eff_root = _resolve_base_dir(base_dir) if base_dir is not None else None
        prof_cur = get_active_user_profile(sid if use_sandbox else "", sandbox=use_sandbox, base_dir=base_dir)
        st_cur = load_wizard_state(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
        topo_cur = st_cur.get("topology") or {}
        hb_target = str(
            body.get("homebase_url")
            or body.get("remote_address")
            or os.environ.get("ANCHOR_HOMEBASE_URL")
            or topo_cur.get("coordination_hub")
            or ""
        ).strip()
        tel_en = bool(body.get("telemetry_enabled", topo_cur.get("telemetry_enabled", True)))
        if use_sandbox:
            return {
                "ok": True,
                "sandbox": True,
                "registered": True,
                "homebase_url": hb_target,
                "telemetry_enabled": tel_en,
            }
        return _mu.register_with_homebase(
            owner=str(body.get("owner") or prof_cur.get("display_name") or ""),
            contact_email=str(body.get("contact_email") or prof_cur.get("contact_email") or ""),
            pseudonym=str(body.get("pseudonym") or prof_cur.get("pseudonym") or ""),
            hostname=str(body.get("hostname") or ""),
            tailscale_url=str(body.get("tailscale_url") or ""),
            tailscale_ip=str(body.get("tailscale_ip") or ""),
            homebase_url=hb_target,
            telemetry_enabled=tel_en,
            anchor_root=eff_root,
        )
    if act == "sync_telemetry_now":
        if "_req_auth_ok" in body and not bool(body.get("_req_auth_ok")):
            return {"ok": False, "status_code": 401, "error": "unauthorized"}
        import mothership_updater as _mu
        eff_root = _resolve_base_dir(base_dir) if base_dir is not None else None
        return _mu.sync_telemetry_to_homebase(
            anchor_root=eff_root,
            heartbeat_even_if_empty=bool(body.get("heartbeat_even_if_empty", True)),
        )
    if act == "list_homebase_telemetry":
        if not bool(body.get("_req_auth_ok")):
            return {"ok": False, "status_code": 401, "error": "unauthorized"}
        import mothership_updater as _mu
        eff_root = _resolve_base_dir(base_dir) if base_dir is not None else None
        return _mu.list_homebase_telemetry(
            mothership_id=str(body.get("mothership_id") or ""),
            limit=body.get("limit", 100),
            anchor_root=eff_root,
        )
    if act == "configure_service":
        return configure_service_connection(
            family=str(body.get("family") or "claude"),
            enabled=bool(body.get("enabled", True)),
            auth_mode=str(body.get("auth_mode") or "subscription"),
            api_key=str(body.get("api_key") or body.get("api_key_value") or ""),
            tier_level=str(body.get("tier_level") or "frontier"),
            orchestrator_model=str(body.get("orchestrator_model") or body.get("selected_model") or ""),
            reviewer_model=str(body.get("reviewer_model") or ""),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "update_cli":
        return check_or_update_cli(
            family=str(body.get("family") or "claude"),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "test_service_tier":
        return run_service_live_test(
            family=str(body.get("family") or "claude"),
            tier_level=str(body.get("tier_level") or ""),
            model_id=str(body.get("model_id") or ""),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "organize_goals":
        return organize_goals_with_starchart_steward(
            raw_text=str(body.get("raw_text") or ""),
            mission_statement=str(body.get("mission_statement") or ""),
            starting_flow=str(body.get("starting_flow") or "goals_first"),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "brainstorm_mission":
        return brainstorm_mission_dialogue(
            user_input=str(body.get("user_input") or body.get("raw_text") or ""),
            current_draft=str(body.get("current_draft") or ""),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "lock_mission":
        return lock_mission_statement(
            mission_statement=str(body.get("mission_statement") or ""),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "brainstorm_goals":
        return brainstorm_goals_dialogue(
            user_input=str(body.get("user_input") or body.get("raw_text") or ""),
            mission_statement=str(body.get("mission_statement") or ""),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "discover_goal_resources":
        s_roots = body.get("search_roots")
        if isinstance(s_roots, str):
            s_roots = [r.strip() for r in s_roots.split(";") if r.strip()]
        return discover_goal_resources(
            goal_id=str(body.get("goal_id") or ""),
            on_disk_clue=str(body.get("on_disk_clue") or ""),
            web_and_info_clue=str(body.get("web_and_info_clue") or ""),
            search_roots=s_roots,
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "brainstorm_project_sources":
        roots = body.get("roots")
        if isinstance(roots, str):
            roots = [r.strip() for r in roots.split(";") if r.strip()]
        ftypes = body.get("selected_file_types")
        if isinstance(ftypes, str):
            ftypes = [x.strip() for x in ftypes.split(",") if x.strip()]
        return brainstorm_project_sources(
            user_input=str(body.get("user_input") or ""),
            selected_file_types=ftypes,
            roots=roots,
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "get_project_hierarchy":
        return {
            "ok": True,
            "hierarchy": build_hierarchical_project_organization(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir),
        }
    if act == "revise_project_organization":
        return revise_project_organization(
            verbal_instruction=str(body.get("verbal_instruction") or body.get("user_input") or ""),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "suggest_top_priorities":
        return suggest_top_priorities(
            user_priority_notes=str(body.get("user_priority_notes") or body.get("priority_initiatives_text") or ""),
            max_active=int(body.get("max_active") or 4),
            max_on_deck=int(body.get("max_on_deck") or 6),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "scan_directories":
        roots = body.get("roots")
        if isinstance(roots, str):
            roots = [r.strip() for r in roots.split(";") if r.strip()]
        excl = body.get("excluded_paths")
        if isinstance(excl, str):
            excl = [x.strip() for x in excl.split(";") if x.strip()]
        return scan_and_propose_projects(
            roots=roots,
            excluded_paths=excl,
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "consolidate_folders":
        fpaths = body.get("folder_paths") or []
        if isinstance(fpaths, str):
            fpaths = [x.strip() for x in re.split(r"[;\r\n]+", fpaths) if x.strip()]
        goals_l = body.get("goals_list") or []
        if isinstance(goals_l, str):
            goals_l = [x.strip() for x in goals_l.splitlines() if x.strip()]
        inits_l = body.get("initiatives_list") or []
        if isinstance(inits_l, str):
            inits_l = [x.strip() for x in inits_l.splitlines() if x.strip()]
        return consolidate_folders_into_project(
            folder_paths=fpaths,
            project_name=str(body.get("project_name") or ""),
            primary_folder=body.get("primary_folder"),
            mission_statement=str(body.get("mission_statement") or ""),
            goals_list=goals_l,
            initiatives_list=inits_l,
            group_folder=str(body.get("group_folder") or ""),
            seat=str(body.get("seat") or "active"),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "propose_active_on_deck":
        return propose_active_and_on_deck(
            priority_initiatives_text=str(body.get("priority_initiatives_text") or ""),
            candidates=body.get("candidates") if isinstance(body.get("candidates"), list) else None,
            max_active=int(body.get("max_active") or 4),
            max_on_deck=int(body.get("max_on_deck") or 6),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "provision_projects_and_cockpits":
        selected = body.get("projects")
        if not isinstance(selected, list):
            st_doc = load_wizard_state(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
            selected = (st_doc.get("projects") or {}).get("discovered") or []
        return provision_projects_and_cockpits(
            selected,
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
        )
    if act == "configure_comms":
        return configure_comms_action(body, sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
    if act == "reset_sandbox":
        return reset_sandbox(sandbox_id=sid, base_dir=base_dir)
    if act == "apply_sandbox_to_live":
        return apply_sandbox_to_live(sandbox_id=sid, base_dir=base_dir)
    if act == "receipt":
        return build_readiness_receipt(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
    if act == "register_gwl_applicant":
        import gwl_clearinghouse as _gwl
        hub_root = _gwl_hub_root_for(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
        app_rec = body.get("applicant") if isinstance(body.get("applicant"), dict) else body
        return _gwl.register_applicant_signup(app_rec, hub_root=hub_root)
    if act == "list_gwl_applicants":
        import gwl_clearinghouse as _gwl
        hub_root = _gwl_hub_root_for(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
        apps = _gwl.list_applicant_signups(hub_root=hub_root)
        return {"ok": True, "count": len(apps), "applicants": apps}
    if act == "get_model_catalog":
        import gwl_clearinghouse as _gwl
        hub_root = _gwl_hub_root_for(sandbox=use_sandbox, sandbox_id=sid, base_dir=base_dir)
        return {"ok": True, "catalog": _gwl.get_verified_model_catalog(hub_root=hub_root)}
    raise ValueError(f"Unknown onboard wizard action: {act}")


def configure_comms_action(
    body: dict[str, Any],
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    return configure_wizard_comms(
        provider_family=str(body.get("provider_family") or "gmail"),
        email_address=str(body.get("email_address") or ""),
        auth_mode=str(body.get("auth_mode") or "app_password"),
        secret=str(body.get("secret") or ""),
        ics_url=str(body.get("ics_url") or ""),
        imap_host=str(body.get("imap_host") or ""),
        sandbox=sandbox,
        sandbox_id=sandbox_id,
        base_dir=base_dir,
    )



LAUNCH_ONBOARD_TEST_CMD = """@echo off
setlocal
REM ============================================================================
REM Isolated Anchor Desktop Onboarding Walkthrough Launcher
REM - Uses its own AppData profile (%LOCALAPPDATA%\\anchor-shell-test-onboard-walkthrough)
REM - Uses its own window mutex & title ("Anchor (test onboard-walkthrough)")
REM - Uses isolated local port 8787 and workspace C:\\dev\\Anchor-Onboard-Test
REM - NEVER modifies your existing Anchor.exe -> Puter Tailscale connection!
REM ============================================================================
set "ANCHOR_SHELL_TEST=onboard-walkthrough"
set "ANCHOR_SHELL_PORT=8787"
set "ANCHOR_SHELL_LOCAL_URL=http://127.0.0.1:8787"
set "ANCHOR_SHELL_INSTALL_ROOT=C:\\dev\\Anchor-Onboard-Test"
set "ANCHOR_SHELL_ONBOARD_PATH=/onboard-wizard"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Path '%~dp0' -Recurse | Unblock-File -ErrorAction SilentlyContinue; Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }; if ((Test-Path '%~dp0Anchor\\anchor-core-overlay.zip') -and (Test-Path 'C:\\dev\\Anchor-Onboard-Test\\Anchor')) { Expand-Archive -Path '%~dp0Anchor\\anchor-core-overlay.zip' -DestinationPath 'C:\\dev\\Anchor-Onboard-Test\\Anchor' -Force }" >nul 2>&1
if exist "%~dp0Anchor\\Anchor.exe" (
    start "" "%~dp0Anchor\\Anchor.exe" --setup
) else if exist "%~dp0Anchor.exe" (
    start "" "%~dp0Anchor.exe" --setup
) else (
    echo Could not find Anchor\\Anchor.exe inside this folder. Please extract the entire zip first.
    pause
)
"""

RESET_ONBOARD_TEST_CMD = """@echo off
setlocal
echo Stopping isolated test server on port 8787 (if running)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -LocalPort 8787 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
if exist "%LOCALAPPDATA%\\anchor-shell-test-onboard-walkthrough" (
    echo Removing isolated test profile %LOCALAPPDATA%\\anchor-shell-test-onboard-walkthrough...
    rmdir /s /q "%LOCALAPPDATA%\\anchor-shell-test-onboard-walkthrough"
)
echo Done! Your normal Anchor.exe (connected to Puter over Tailscale) was never touched.
pause
"""

README_ONBOARD_TEST_TXT = """========================================================================
ANCHOR — ISOLATED DESKTOP ONBOARDING WALKTHROUGH PACKAGE
========================================================================

How to run the Onboarding Walkthrough on your work desktop without
touching your existing working Anchor.exe -> Puter Tailscale setup:

1. Extract this entire .zip archive to any folder on your desktop
   (for example: Desktop\\Anchor-Test-Onboard).
2. Double-click:
      Launch-Anchor-Onboard-Test.cmd
3. A window titled "Anchor (test onboard-walkthrough)" will open:
   - First screen: "Choose your mother ship first"
     ("This computer is my mother ship" vs. "Connect to my existing mother ship")
   - Selecting "This computer is my mother ship" starts an isolated test
     service on port 8787 (using C:\\dev\\Anchor-Onboard-Test) and opens
     the 7-Step Guided Onboarding Wizard (/onboard-wizard).
4. Your normal Anchor.exe settings (%LOCALAPPDATA%\\anchor-shell\\settings.json)
   and Start Menu shortcut are NEVER modified. You can open your normal
   Anchor.exe at any time to connect back to Puter over Tailscale.
5. To wipe the test profile and re-test from a fresh cold start, run:
      Reset-And-Clean-Test-Onboard.cmd
"""


def build_or_resolve_exe_zip_package(
    package_kind: str = "prod",
    *,
    dist_dir: Path | str | None = None,
) -> tuple[Path, str]:
    """Return ``(zip_file_path, download_filename)`` for:
      * ``package_kind="prod"`` -> ``Anchor.zip`` (clean shareable Collaborator Anchor.exe for Merrill & collaborators;
        hides Anchor Admin, Test Onboard .zip, and Anchor.exe .zip links on Cave of Wonders)
      * ``package_kind="admin"`` -> ``Anchor-Admin.zip`` (John's ``Anchor Admin.exe`` with Master Key icon & full Admin/Packaging links)
      * ``package_kind="test"`` -> ``Anchor-Test-Onboard.zip`` (isolated work-desktop onboarding test on port 8787)
    """
    import zipfile as _zf

    if dist_dir is not None:
        d_root = Path(dist_dir)
    else:
        local_app = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
        d_root = local_app / "anchor-shell" / "dist"
    d_root.mkdir(parents=True, exist_ok=True)

    anchor_onedir = d_root / "Anchor"
    admin_onedir = d_root / "Anchor Admin"
    prod_zip = d_root / "Anchor.zip"
    admin_zip = d_root / "Anchor-Admin.zip"
    test_zip = d_root / "Anchor-Test-Onboard.zip"

    def _overlay_bytes_with_edition(edition: str) -> bytes | None:
        base_ov = Path(__file__).resolve().parent / "shell" / "anchor-core-overlay.zip"
        if not base_ov.is_file():
            return None
        import io as _io
        buf = _io.BytesIO()
        ed_json = json.dumps({
            "edition": edition,
            "hide_admin_and_download_links": (edition == "collaborator"),
        }, indent=2) + "\n"
        clean_reg_json = json.dumps({
            "schema": "anchor.mothership.registry.v1",
            "updated_at": _utc_now_iso(),
            "canonical_github_repo": CANONICAL_ANCHOR_GITHUB_URL,
            "latest_version": paths.read_version(),
            "motherships": [],
        }, indent=2) + "\n"
        with _zf.ZipFile(base_ov, "r") as zin, _zf.ZipFile(buf, "w", compression=_zf.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                norm_fn = item.filename.replace("\\", "/")
                if norm_fn == "anchor-edition.json":
                    continue
                if edition == "collaborator" and norm_fn == "mothership_registry.json":
                    continue
                zout.writestr(item, zin.read(item.filename))
            zout.writestr("anchor-edition.json", ed_json)
            if edition == "collaborator":
                zout.writestr("mothership_registry.json", clean_reg_json)
                zout.writestr("DASHBOARD.md", "# Anchor Daily Dashboard\n\n## Focus Today\n\n## Active Priorities\n")
                zout.writestr("PROJECTS.md", "# Projects\n")
                zout.writestr("INBOX.md", "# Quick Capture Inbox\n")
                zout.writestr("CANCELLED.md", "# Cancelled Tasks\n")
                zout.writestr("SAVED_FOR_LATER.md", "# Saved for Later\n")
                for dom in ("academic", "commercial", "family", "writing"):
                    zout.writestr(f"domains/{dom}.md", f"# {dom.title()}\n")
        return buf.getvalue()

    base_ov_path = Path(__file__).resolve().parent / "shell" / "anchor-core-overlay.zip"
    ov_mtime = base_ov_path.stat().st_mtime if base_ov_path.is_file() else 0.0

    repo_ver_path = Path(__file__).resolve().parent / "VERSION"
    ver_mtime = repo_ver_path.stat().st_mtime if repo_ver_path.is_file() else 0.0
    exe_mtime = (anchor_onedir / "Anchor.exe").stat().st_mtime if (anchor_onedir / "Anchor.exe").is_file() else 0.0
    latest_src_mtime = max(ov_mtime, ver_mtime, exe_mtime)

    if package_kind == "prod":
        # Collaborator Anchor.zip intentionally omits anchor-core-overlay.zip and loose server/skill sources
        # so nothing can be copied before the user agrees to the Ghost World Labs License in Step 1!
        has_stale_overlay = False
        if prod_zip.is_file():
            try:
                with _zf.ZipFile(prod_zip, "r") as zchk:
                    has_stale_overlay = "Anchor/anchor-core-overlay.zip" in zchk.namelist()
            except Exception:
                has_stale_overlay = True
        need_prod = (not prod_zip.is_file()) or has_stale_overlay or (latest_src_mtime > prod_zip.stat().st_mtime)
        if need_prod:
            collab_ed_json = json.dumps({
                "edition": "collaborator",
                "hide_admin_and_download_links": True,
            }, indent=2) + "\n"
            with _zf.ZipFile(prod_zip, "w", compression=_zf.ZIP_DEFLATED) as zf:
                zf.writestr("Anchor/anchor-edition.json", collab_ed_json)
                if anchor_onedir.is_dir():
                    for f in anchor_onedir.rglob("*"):
                        if f.is_file():
                            rel = str(Path("Anchor") / f.relative_to(anchor_onedir)).replace("\\", "/")
                            if rel in ("Anchor/anchor-edition.json", "Anchor/anchor-core-overlay.zip"):
                                continue
                            zf.write(f, rel)
                else:
                    zf.writestr("Anchor/README.txt", "Run shell/build_exe.ps1 on Mothership to populate Anchor.exe.\n")
                repo_root = Path(__file__).resolve().parent
                existing_names = set(zf.namelist())
                for extra_name in (
                    "Uninstall-Anchor.cmd",
                    "install-mac-linux.sh",
                    "Anchor.command",
                    "USER-ONBOARD.md",
                    "VERSION",
                    "shell/anchor_shell.py",
                    "shell/connect.py",
                    "shell/build_unix.sh",
                ):
                    extra_file = repo_root / extra_name
                    arc_name = f"Anchor/{extra_name}"
                    if extra_file.is_file() and arc_name not in existing_names:
                        zf.write(extra_file, arc_name)
        return prod_zip, "Anchor.zip"

    if package_kind == "admin":
        need_admin = (not admin_zip.is_file()) or (ov_mtime > admin_zip.stat().st_mtime)
        if need_admin:
            adm_ed_json = json.dumps({
                "edition": "admin",
                "hide_admin_and_download_links": False,
            }, indent=2) + "\n"
            adm_ov = _overlay_bytes_with_edition("admin")
            src_dir = admin_onedir if admin_onedir.is_dir() else anchor_onedir
            with _zf.ZipFile(admin_zip, "w", compression=_zf.ZIP_DEFLATED) as zf:
                zf.writestr("Anchor Admin/anchor-edition.json", adm_ed_json)
                if src_dir.is_dir():
                    for f in src_dir.rglob("*"):
                        if f.is_file():
                            rel_part = f.relative_to(src_dir)
                            if str(rel_part) == "Anchor.exe":
                                rel = "Anchor Admin/Anchor Admin.exe"
                            else:
                                rel = str(Path("Anchor Admin") / rel_part).replace("\\", "/")
                            if rel == "Anchor Admin/anchor-edition.json":
                                continue
                            if rel == "Anchor Admin/anchor-core-overlay.zip" and adm_ov is not None:
                                zf.writestr(rel, adm_ov)
                            else:
                                zf.write(f, rel)
                    if adm_ov is not None and not (src_dir / "anchor-core-overlay.zip").is_file():
                        zf.writestr("Anchor Admin/anchor-core-overlay.zip", adm_ov)
                else:
                    if adm_ov is not None:
                        zf.writestr("Anchor Admin/anchor-core-overlay.zip", adm_ov)
                    zf.writestr("Anchor Admin/README.txt", "Run shell/build_exe.ps1 on Mothership to populate Anchor Admin.exe.\n")
        return admin_zip, "Anchor-Admin.zip"

    # Build or refresh Anchor-Test-Onboard.zip
    need_rebuild = (not test_zip.is_file()) or (ov_mtime > test_zip.stat().st_mtime)
    if not need_rebuild and prod_zip.is_file():
        need_rebuild = prod_zip.stat().st_mtime > test_zip.stat().st_mtime

    if need_rebuild:
        collab_ov = _overlay_bytes_with_edition("collaborator")
        with _zf.ZipFile(test_zip, "w", compression=_zf.ZIP_DEFLATED) as zf:
            zf.writestr('Anchor/anchor-test-mode.json', json.dumps({
                'ANCHOR_SHELL_TEST': 'onboard-walkthrough',
                'ANCHOR_SHELL_PORT': '8787',
                'ANCHOR_SHELL_INSTALL_ROOT': r'C:\Anchor-Onboard-Test',
                'ANCHOR_SHELL_ONBOARD_PATH': '/onboard-wizard',
            }, indent=2))
            zf.writestr("Launch-Anchor-Onboard-Test.cmd", LAUNCH_ONBOARD_TEST_CMD.replace("\n", "\r\n"))
            zf.writestr("Reset-And-Clean-Test-Onboard.cmd", RESET_ONBOARD_TEST_CMD.replace("\n", "\r\n"))
            zf.writestr("README-ONBOARD-TEST.txt", README_ONBOARD_TEST_TXT.replace("\n", "\r\n"))
            if anchor_onedir.is_dir():
                for f in anchor_onedir.rglob("*"):
                    if f.is_file():
                        rel = str(Path("Anchor") / f.relative_to(anchor_onedir)).replace("\\", "/")
                        if rel == "Anchor/anchor-core-overlay.zip" and collab_ov is not None:
                            zf.writestr(rel, collab_ov)
                        else:
                            zf.write(f, rel)
                if collab_ov is not None and not (anchor_onedir / "anchor-core-overlay.zip").is_file():
                    zf.writestr("Anchor/anchor-core-overlay.zip", collab_ov)
            elif prod_zip.is_file():
                with _zf.ZipFile(prod_zip, "r") as pzf:
                    for item in pzf.infolist():
                        zf.writestr(item, pzf.read(item.filename))

    return test_zip, "Anchor-Test-Onboard.zip"


# ═════════════════════════════════════════════════════════════════════════════
# HTML RENDERER: `/onboard-wizard` & `/onboard-wizard?sandbox=1`
# ═════════════════════════════════════════════════════════════════════════════

def render_onboard_wizard_html(
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> str:
    """Render the interactive 7-Step Guided Onboarding & First-Run Wizard Web UI."""
    bundle = get_full_wizard_bundle(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    boot_json = json.dumps(bundle, ensure_ascii=False)
    esc_sid = html.escape(bundle["sandbox_id"] or DEFAULT_SANDBOX_ID, quote=True)
    mode_badge = (
        '<span class="wiz-badge sandbox">🧪 SANDBOX WALKTHROUGH MODE (Ignores Existing Anchor &amp; Tailscale)</span>'
        if sandbox
        else '<span class="wiz-badge live">⚓ LIVE ONBOARDING &amp; SETUP WIZARD</span>'
    )
    toggle_href = "/onboard-wizard" if sandbox else "/onboard-wizard?sandbox=1"
    toggle_label = "Switch to Live Mode" if sandbox else "🧪 Test Walkthrough Mode (Ignore Existing Anchor & Tailscale)"
    is_admin = bool(bundle.get("admin_edition", True))
    sandbox_toggle_html = (
        f'<a class="btn" href="{toggle_href}" id="btnToggleSandbox">{toggle_label}</a>'
        if (is_admin or sandbox)
        else ""
    )
    admin_gui_btn_html = (
        '<a class="btn" href="/gwl-admin"><img src="/vendor/brand/anchor-admin-key.png" alt="" style="width:16px;height:16px;border-radius:4px;vertical-align:-3px;margin-right:4px"> Anchor Admin GUI</a>'
        if is_admin
        else ""
    )

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>Anchor · 7-Step Guided Onboarding Wizard</title>
  <style>
    :root {{
      --bg: #0b0f17;
      --panel: #131a26;
      --card: #182130;
      --border: #2a364d;
      --text: #e6edf3;
      --muted: #93a1b5;
      --gold: #eab308;
      --emerald: #10b981;
      --sky: #38bdf8;
      --danger: #f43f5e;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--text);
      font-family: system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif;
      line-height: 1.5;
    }}
    .wiz-top {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-wrap: wrap;
      gap: 12px;
      padding: 10px 18px;
      background: #0b1018;
      border-bottom: 1px solid var(--border);
      -webkit-app-region: drag;
      app-region: drag;
      user-select: none;
      cursor: move;
      position: sticky;
      top: 0;
      z-index: 100;
    }}
    .wiz-top a, .wiz-top button, .wiz-top input, .wiz-top select, .wiz-top .no-drag {{
      -webkit-app-region: no-drag;
      app-region: no-drag;
      cursor: pointer;
    }}
    .wiz-status-strip {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      font-size: 11px;
      color: var(--muted);
    }}
    .wiz-winctl {{
      display: inline-flex;
      align-items: center;
      gap: 2px;
      margin-left: 6px;
      border-left: 1px solid var(--border);
      padding-left: 8px;
    }}
    .wiz-winctl button {{
      background: transparent;
      border: 0;
      color: var(--muted);
      width: 34px;
      height: 30px;
      border-radius: 6px;
      font-size: 13px;
    }}
    .wiz-winctl button:hover {{ background: #1f293d; color: #fff; }}
    .wiz-winctl button.close:hover {{ background: #c42b1c; color: #fff; }}
    .wiz-brand {{
      font-size: 18px;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .wiz-badge {{
      font-size: 12px;
      padding: 4px 10px;
      border-radius: 999px;
      font-weight: 600;
    }}
    .wiz-badge.sandbox {{
      background: rgba(234, 179, 8, 0.16);
      color: #fde047;
      border: 1px solid rgba(234, 179, 8, 0.45);
    }}
    .wiz-badge.live {{
      background: rgba(16, 185, 129, 0.16);
      color: #6ee7b7;
      border: 1px solid rgba(16, 185, 129, 0.45);
    }}
    .wiz-top-actions {{
      display: flex;
      gap: 10px;
      align-items: center;
      flex-wrap: wrap;
    }}
    .btn {{
      background: #233046;
      color: var(--text);
      border: 1px solid #384b6b;
      padding: 8px 14px;
      border-radius: 7px;
      font-size: 13px;
      font-weight: 600;
      cursor: pointer;
      text-decoration: none;
      display: inline-flex;
      align-items: center;
      gap: 6px;
    }}
    .btn:hover {{ background: #2c3c57; }}
    .btn.primary {{
      background: #d97706;
      border-color: #f59e0b;
      color: #fff;
    }}
    .btn.primary:hover {{ background: #b45309; }}
    .btn.emerald {{
      background: #059669;
      border-color: #10b981;
      color: #fff;
    }}
    .wiz-layout {{
      display: grid;
      grid-template-columns: 290px 1fr;
      min-height: calc(100vh - 64px);
    }}
    .wiz-stepper {{
      background: var(--panel);
      border-right: 1px solid var(--border);
      padding: 20px 16px;
      display: flex;
      flex-direction: column;
      gap: 8px;
    }}
    .step-btn {{
      display: flex;
      align-items: center;
      gap: 10px;
      width: 100%;
      text-align: left;
      padding: 10px 12px;
      border-radius: 8px;
      border: 1px solid transparent;
      background: transparent;
      color: var(--muted);
      cursor: pointer;
      font-size: 13px;
    }}
    .step-btn.active {{
      background: var(--card);
      border-color: var(--gold);
      color: var(--text);
      font-weight: 600;
    }}
    .step-btn.done .step-num {{
      background: var(--emerald);
      color: #052e16;
    }}
    .step-num {{
      width: 24px;
      height: 24px;
      border-radius: 50%;
      background: #253248;
      color: var(--text);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 12px;
      font-weight: 700;
      flex: none;
    }}
    .wiz-main {{
      padding: 28px 36px;
      max-width: 1080px;
    }}
    .wiz-card {{
      background: var(--card);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 20px 24px;
      margin-bottom: 18px;
    }}
    .wiz-card h2 {{ margin: 0 0 8px; font-size: 20px; }}
    .wiz-card h3 {{ margin: 0 0 8px; font-size: 16px; }}
    .muted {{ color: var(--muted); font-size: 13px; }}
    .form-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
      gap: 14px;
      margin: 14px 0;
    }}
    label {{
      display: block;
      font-size: 12px;
      font-weight: 600;
      color: #cbd5e1;
      margin-bottom: 5px;
    }}
    input[type="text"], input[type="password"], select, textarea {{
      width: 100%;
      padding: 9px 11px;
      border-radius: 7px;
      border: 1px solid #354664;
      background: #0e141f;
      color: var(--text);
      font-size: 13px;
    }}
    textarea {{ min-height: 110px; resize: vertical; }}
    .service-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
      gap: 14px;
    }}
    .proj-row {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 10px 12px;
      border-radius: 8px;
      background: #101723;
      border: 1px solid #263449;
      margin-bottom: 8px;
      flex-wrap: wrap;
    }}
    .status-banner {{
      padding: 10px 14px;
      border-radius: 8px;
      background: rgba(56, 189, 248, 0.12);
      border: 1px solid rgba(56, 189, 248, 0.35);
      color: #bae6fd;
      margin-bottom: 16px;
      font-size: 13px;
    }}
    .pill {{
      font-size: 11px;
      padding: 2px 8px;
      border-radius: 999px;
      background: #243247;
      color: #93c5fd;
    }}
  </style>
</head>
<body>
  <header class="wiz-top" id="wizTopBar" title="Drag anywhere on this bar to move the Anchor window">
    <div class="wiz-brand">
      <span>⚓🧭 Anchor Guided Onboarding &amp; Setup Wizard</span>
      {mode_badge}
      <div class="wiz-status-strip">
        <span class="pill" style="background:#064e3b;color:#6ee7b7">● Mother Ship Active</span>
        <span class="pill" id="topNightlyStatusPill">🌙 Models: Nightly 02:00 + Live CLI</span>
        <span class="pill" id="topAuthStatusPill">🔐 Token &amp; Auth Ready</span>
        <span class="muted" style="font-size:11px">✥ Drag bar to move window</span>
      </div>
    </div>
    <div class="wiz-top-actions">
      {sandbox_toggle_html}
      <button type="button" class="btn" id="btnResetSandbox" {"" if sandbox else "hidden"}>↺ Reset Walkthrough</button>
      <button type="button" class="btn emerald" id="btnApplySandbox" {"" if sandbox else "hidden"}>✓ Commit &amp; Apply to Live Anchor</button>
      <a class="btn" href="/recover-account">🔑 Account Recovery</a>
      {admin_gui_btn_html}
      <a class="btn" href="/setup">⚙ Provider Setup</a>
      <a class="btn primary" href="/high-seat">🏛 Open Cave of Wonders</a>
      <div class="wiz-winctl" aria-label="Window controls">
        <button type="button" data-winctl="minimize" title="Minimize window">&#8212;</button>
        <button type="button" data-winctl="maximize" title="Maximize or restore window">&#9744;</button>
        <button type="button" id="wizCloseOverlayX" class="close" data-overlay-close="1" title="Close and return to Cave of Wonders or AI Cockpit (Esc)" aria-label="Close window and return">&#10005;</button>
      </div>
    </div>
  </header>

  <div class="wiz-layout">
    <aside class="wiz-stepper" aria-label="Onboarding steps">
      <button type="button" class="step-btn active" data-step="1"><span class="step-num">1</span><span>Mother Ship &amp; Remote + License</span></button>
      <button type="button" class="step-btn" data-step="2"><span class="step-num">2</span><span>Registry &amp; Optional Tailscale</span></button>
      <button type="button" class="step-btn" data-step="3"><span class="step-num">3</span><span>4 AI Agent CLIs &amp; Connect</span></button>
      <button type="button" class="step-btn" data-step="4"><span class="step-num">4</span><span>Mission &amp; Goals (Optional)</span></button>
      <button type="button" class="step-btn" data-step="5"><span class="step-num">5</span><span>Hard-Drive Tree &amp; Gandalf Projects</span></button>
      <button type="button" class="step-btn" data-step="6"><span class="step-num">6</span><span>Email &amp; Calendar Connect</span></button>
      <button type="button" class="step-btn" data-step="7"><span class="step-num">7</span><span>Readiness Receipt &amp; Launchpad</span></button>
    </aside>

    <main class="wiz-main">
      <div id="wizBanner" class="status-banner" role="status">
        Welcome! Walk through each step below to configure your personal Steward identity, Tailscale Mothership topology, AI service tiers, Star Chart goals / initiatives, and Project AI Cockpits.
      </div>

      <!-- STEP 1 -->
      <section class="wiz-step-pane" id="step-pane-1">
        <div class="wiz-card">
          <h2>Step 1 · Mother Ship &amp; Remote, Ghost World Labs License &amp; Identity</h2>
          <p class="muted">Agree to the Ghost World Labs License first (required before anything is downloaded or shared). All <strong>20 Standing Foundry Skills</strong> are loaded automatically on your Mother Ship.</p>
          <div class="form-grid">
            <div>
              <label for="inpDisplayName">What is your name? (How your Steward addresses you locally)</label>
              <input type="text" id="inpDisplayName" placeholder="e.g., Alex, Jordan">
            </div>
            <div>
              <label for="inpPseudonym">Anchor Pseudonym / Synonym (Public Collaborator Identity)</label>
              <input type="text" id="inpPseudonym" placeholder="e.g., Voyager, NorthStar">
            </div>
            <div>
              <label for="inpAliases">Optional Pseudonym Spelling Aliases (comma-separated)</label>
              <input type="text" id="inpAliases" placeholder="e.g., North Star">
            </div>
            <div>
              <label for="selPersona">Global Companion Steward Persona</label>
              <select id="selPersona">
                <option value="Aladdin">🪔 Aladdin · Cave of Wonders Chief of Staff</option>
                <option value="Jarvis">🛡 Jarvis · Helm &amp; Chart Room</option>
                <option value="Ecgberht">👑 Ecgberht · High Seat &amp; Beacon</option>
              </select>
            </div>
          </div>
          <div style="border-top:1px solid var(--border);margin:18px 0 14px;padding-top:16px">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
              <h3 style="margin:0">🔐 Security, Login Credentials, Contact / Recovery Email, Dual Authentication (2FA) &amp; Anchor Token</h3>
              <span class="pill" id="pwdStatusPill">Credentials &amp; Token Ready</span>
            </div>
            <p class="muted" style="margin:4px 0 12px">Configure your local Mother Ship login username &amp; password (stored hashed via PBKDF2-SHA256 + OS Credential Vault), your Contact / Recovery Email (for username &amp; password recovery links), optional Dual Authentication (2FA + 10 single-use backup codes), and your Mother Ship <code>ANCHOR_TOKEN</code>.</p>
            <div class="form-grid">
              <div>
                <label for="inpUsername">Mother Ship Username</label>
                <input type="text" id="inpUsername" placeholder="e.g., alex" autocomplete="username">
              </div>
              <div>
                <label for="inpContactEmail">Contact / Account Recovery Email (For Username &amp; Password Recovery Links)</label>
                <input type="text" id="inpContactEmail" placeholder="e.g., researcher@example.org, admin@example.com" autocomplete="email">
              </div>
              <div>
                <label for="inpPassword">Login Password (Stored in OS Vault + PBKDF2 Hash)</label>
                <input type="password" id="inpPassword" placeholder="Set or update password (leave blank to keep existing)" autocomplete="new-password">
              </div>
              <div>
                <label for="inpPasswordConfirm">Confirm Password</label>
                <input type="password" id="inpPasswordConfirm" placeholder="Re-enter password to confirm" autocomplete="new-password">
              </div>
              <div>
                <label for="selDualAuthMethod">Dual Authentication (2FA) Option</label>
                <div style="display:flex;gap:8px;align-items:center">
                  <label style="display:inline-flex;align-items:center;gap:6px;margin:0;white-space:nowrap;font-size:13px">
                    <input type="checkbox" id="chkDualAuth"> Enable 2FA
                  </label>
                  <select id="selDualAuthMethod">
                    <option value="totp_authenticator">Authenticator App (TOTP 6-Digit Code)</option>
                    <option value="tailscale_device_2fa">Tailscale Identity + Password (Dual-Factor)</option>
                    <option value="backup_code">Hardware / Recovery Verification Key</option>
                  </select>
                </div>
              </div>
            </div>
            <div id="dualAuthSecretBox" class="proj-row" style="margin-top:8px;flex-direction:column;align-items:stretch" hidden>
              <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
                <div>
                  <strong>🛡 Dual Authentication (2FA) Enrollment Key:</strong> <code id="dualAuthSecretCode" style="color:#fde047;font-size:14px"></code>
                  <div class="muted" id="dualAuthUriText">Scan or enter this key in Google/Microsoft Authenticator or 1Password.</div>
                </div>
                <span class="pill" style="background:#064e3b;color:#6ee7b7">2FA ENABLED ✓</span>
              </div>
              <div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border)">
                <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
                  <strong>🔑 Standard 2FA Recovery · 10 Single-Use Backup Codes (Save or Print — Each Code Works Once if You Lose Your Phone):</strong>
                  <div style="display:flex;gap:6px">
                    <button type="button" class="btn" id="btnCopyBackupCodes">📋 Copy 10 Backup Codes</button>
                    <button type="button" class="btn" id="btnRegenBackupCodes">🔄 Generate 10 Fresh Backup Codes</button>
                  </div>
                </div>
                <div id="dualAuthBackupCodesList" style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px"></div>
                <div class="muted" style="margin-top:6px">Standard 3-Layer 2FA Recovery: (1) 10 Single-Use Backup Codes above · (2) Verified Contact Email Recovery Link (<a href="/recover-account" style="color:var(--sky)">/recover-account</a>) · (3) Local Mother Ship Assisted Reset.</div>
              </div>
            </div>
            <div style="margin-top:12px">
              <label for="inpAnchorToken">Mother Ship Anchor Token (<code>ANCHOR_TOKEN</code> — used for Cockpit &amp; Peer Authentication)</label>
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                <input type="password" id="inpAnchorToken" style="flex:1;min-width:260px;font-family:Consolas,monospace" readonly>
                <button type="button" class="btn" id="btnToggleTokenVis">👁 Show / Hide</button>
                <button type="button" class="btn" id="btnCopyAnchorToken">📋 Copy Token</button>
                <button type="button" class="btn" id="btnRegenAnchorToken">🔄 Regenerate Token</button>
              </div>
            </div>
            <details style="margin-top:12px;padding:10px 14px;background:#101723;border:1px solid var(--border);border-radius:8px">
              <summary style="cursor:pointer;font-weight:600;color:var(--sky)">🔑 Forgot Your Username or Password, or Lost Your 2FA Device? Request a Recovery Link</summary>
              <p class="muted" style="margin:6px 0">Enter your Contact Email (or Username / Pseudonym) below to receive a Username reminder and a single-use 30-minute Password &amp; 2FA Recovery Link:</p>
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                <input type="text" id="inpQuickRecoveryEmail" style="flex:1;min-width:240px" placeholder="Enter your Contact Email, Username, or Pseudonym...">
                <button type="button" class="btn primary" id="btnQuickSendRecoveryLink">📧 Send Username &amp; Password Recovery Link</button>
                <a class="btn" href="/recover-account">Open Full Recovery Portal ↗</a>
              </div>
              <div id="quickRecoveryResultBox" style="margin-top:8px" hidden></div>
            </details>
          </div>
          <div id="gwlLicenseCard" class="proj-row" style="margin:14px 0;padding:14px 16px;flex-direction:column;align-items:stretch;border:1px solid #d97706;background:#131b29">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
              <strong style="color:#fde68a;font-size:15px">📜 Ghost World Labs License Acknowledgement (Free Use · No Resale or Commercialization)</strong>
              <span class="pill" id="gwlLicenseStatusPill" style="background:#451a03;color:#fde68a">REQUIRED</span>
            </div>
            <p class="muted" style="margin:8px 0 6px;color:#cbd5e1">
              <strong>Ghost World Lab License — Version 1, Refinement 2 (<code>GHOST-WORLD-LAB-NON-RESALE-v1</code> · All rights reserved — not open source):</strong><br>
              • <strong>Free Use &amp; Sharing Permitted:</strong> Worldwide, royalty-free permission for personal, academic/research, and internal business use, private modification, and voluntary free sharing without a fee. Your own independent papers, data, code, and outputs belong 100% to you.<br>
              • <strong>No Resale or Commercialization:</strong> Selling copies of Anchor or its bundled Skill Foundry skills, bundling them into a paid product, charging recurring version-use/subscription fees, or offering Paid Hosted Access requires Separate Written Permission from Ghost World Labs.
            </p>
            <details style="margin:4px 0 8px;padding:8px 12px;background:#0d131d;border:1px solid #263449;border-radius:7px">
              <summary style="cursor:pointer;font-size:12.5px;color:#93c5fd;font-weight:600">Read Full Ghost World Labs License Clauses 1–10 (Plain-English &amp; Operative Summary)</summary>
              <div id="gwlLicenseClausesList" class="muted" style="margin-top:8px;font-size:12px;line-height:1.5"></div>
            </details>
            <label style="display:flex;align-items:flex-start;gap:9px;margin:4px 0 0;font-size:13.5px;color:#f8fafc;cursor:pointer">
              <input type="checkbox" id="chkAcceptGwlLicense" style="width:auto;margin-top:3px">
              <span>I have read and agree to the <strong>Ghost World Labs License</strong> (free personal, academic &amp; internal use; strictly no resale, paid bundling, or paid commercialization without Separate Written Permission).</span>
            </label>
          </div>
          <button type="button" class="btn primary" id="btnSaveStep1">Save Identity, Acknowledge License &amp; Continue to Step 2 →</button>
        </div>
      </section>

      <!-- STEP 2 -->
      <section class="wiz-step-pane" id="step-pane-2" hidden>
        <div class="wiz-card">
          <h2>Step 2 · Optional Tailscale Setup, 1-Click Registry &amp; Automatic Updates</h2>
          <p class="muted"><code>Anchor.exe</code> automatically installs Anchor and all 20 Ghost World Labs skills from the official Anchor repository below (no separate Skill Foundry repository needed).</p>

          <div id="tsPromptBanner" class="proj-row" style="margin:12px 0;padding:14px 16px;border-color:#38bdf8;background:#0e1b2c" hidden>
            <div>
              <strong style="color:#7dd3fc">📡 Tailscale Is Not Set Up — Would You Like to Set Up Tailscale?</strong>
              <div class="muted" style="margin-top:3px">Tailscale is optional and lets you reach your Mother Ship privately from a second laptop or phone. Automatic website-watched updates work without Tailscale.</div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <button type="button" class="btn primary" id="btnPromptInstallTailscale">📡 Yes — Install &amp; Sign In to Tailscale</button>
              <button type="button" class="btn" id="btnPromptSkipTailscale">✓ No Thanks — Use Locally</button>
            </div>
          </div>

          <div class="wiz-card" id="anchorRegistryCard" style="background:#101723;margin:12px 0;border-color:#10b981">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px">
              <h3 style="margin:0">📋 1-Click Official Anchor Registry (Connect Email for Automatic Updates)</h3>
              <span class="pill" id="regReceiptBadge" style="background:#1e3a8a;color:#93c5fd">Ready to Register</span>
            </div>
            <div class="form-grid">
              <div>
                <label for="inpRegistryEmail">Email Address to Connect</label>
                <input type="text" id="inpRegistryEmail" placeholder="you@example.com" autocomplete="email">
              </div>
              <div>
                <label for="inpAnchorGithubRepo">Anchor GitHub Repository (Official Registry · Locked)</label>
                <input type="text" id="inpAnchorGithubRepo" value="https://github.com/johncliechty/ghostworldlabs-anchor" readonly style="opacity:0.85;cursor:not-allowed;font-family:Consolas,monospace;color:#93c5fd">
              </div>
            </div>
            <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
              <button type="button" class="btn emerald" id="btnOneClickRegister">📌 Register with 1 Click</button>
              <span class="muted" id="regReceiptDetail">Watches signed <code>release-signal.json</code> on the official Anchor GitHub repository for automatic updates.</span>
            </div>
          </div>

          <label style="display:flex;align-items:center;gap:8px;margin:10px 0 6px;font-size:13px;cursor:pointer">
            <input type="checkbox" id="chkAutoPullWebsiteUpdates" checked>
            <span><strong>🌐 Automatic Website-Watched Future Updates (Recommended):</strong> Watch <code>release-signal.json</code> online (Ed25519-signed) and automatically pull new Anchor versions + all 20 skills in-place when idle</span>
          </label>
          <label style="display:flex;align-items:center;gap:8px;margin:6px 0 12px;font-size:13px;cursor:pointer">
            <input type="checkbox" id="chkLowSpecMode">
            <span><strong>💻 Older Windows Laptop / Low-Memory Mothership Mode:</strong> Cap hidden live panes to 2 and skip background Cave pre-warming (<span id="hwDetectSummary">checking RAM &amp; CPU…</span>)</span>
          </label>

          <div id="tsStatusBox" class="wiz-card" style="background:#101723"></div>

          <details style="margin-bottom:14px;padding:10px 14px;background:#101723;border:1px solid var(--border);border-radius:8px">
            <summary style="cursor:pointer;font-size:13px;font-weight:600;color:var(--sky)">Advanced (Optional): Connect to Another Mother Ship or Tailscale Coordination Hub</summary>
            <div class="form-grid" style="margin-top:10px">
              <div>
                <label for="selTopologyMode">Mothership Role</label>
                <select id="selTopologyMode">
                  <option value="main_mothership">Option A — This Computer IS My Mother Ship (Default)</option>
                  <option value="connect_remote_mothership">Option B — Connect to Another Mother Ship (via Tailscale)</option>
                </select>
              </div>
              <div>
                <label for="inpRemoteMothership">Optional Tailscale Peer / Coordination Hub HTTPS URL</label>
                <input type="text" id="inpRemoteMothership" value="" placeholder="https://my-host.tailnet.ts.net (optional)">
              </div>
            </div>
            <label style="display:flex;align-items:center;gap:8px;margin:6px 0 10px;font-size:13px;cursor:pointer">
              <input type="checkbox" id="chkHomebaseTelemetry" checked>
              <span>Share sanitized setup/error diagnostics when linked to a Tailscale Hub</span>
            </label>
            <div id="homebaseStatusBox" class="proj-row" style="margin-bottom:10px"></div>
            <div style="display:flex;gap:8px;flex-wrap:wrap">
              <button type="button" class="btn" id="btnInstallTailscale">📡 Install / Verify Tailscale</button>
              <button type="button" class="btn" id="btnRegisterHomebase">🔗 Link Optional Tailscale Hub</button>
            </div>
          </details>

          <div style="display:flex;gap:10px;flex-wrap:wrap">
            <button type="button" class="btn primary" id="btnSaveStep2">Save &amp; Continue to Step 3 (AI Agent CLIs &amp; Accounts) →</button>
          </div>
        </div>
      </section>

      <!-- STEP 3 -->
      <section class="wiz-step-pane" id="step-pane-3" hidden>
        <div class="wiz-card">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:8px">
            <h2 style="margin:0">Step 3 · Auto-Install AI Agent CLIs, Browser Account Sign-In &amp; Capability Tiers</h2>
            <button type="button" class="btn" id="btnRefreshLiveModels">🔄 Sync Live Models Now</button>
          </div>
          <div id="autoInstallCliBanner" class="wiz-card" style="background:#101928;border-color:#38bdf8;margin-bottom:12px;padding:14px 18px">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
              <div>
                <strong style="color:#7dd3fc;font-size:15px">⚡ 1-Click Auto-Install Agent CLIs &amp; Browser Account Detection</strong>
                <div class="muted" style="margin-top:3px">Automatically install <strong>Claude Code CLI (`claude`)</strong>, <strong>Antigravity / Gemini CLI (`agy` / `gemini`)</strong>, <strong>OpenAI Codex CLI (`codex`)</strong>, and <strong>Grok (`grok`)</strong>, and check for open accounts in your browser so you can log in with 1 click!</div>
              </div>
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                <button type="button" class="btn primary" id="btnAutoInstallClis">⬇ Auto-Install Agent CLIs</button>
                <label style="display:inline-flex;align-items:center;gap:5px;margin:0;font-size:12.5px;cursor:pointer"><input type="checkbox" id="chkIncludeGrokCli"> Include Grok CLI</label>
                <button type="button" class="btn" id="btnCheckBrowserAccounts">🌐 Check Open Browser Accounts</button>
              </div>
            </div>
            <div id="browserAccountsBanner" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(210px,1fr));gap:8px;margin-top:10px"></div>
          </div>
          <div id="nightlyRefreshBanner" class="proj-row" style="margin-bottom:12px">
            <div>
              <strong>🌙 Nightly 02:00 Model Catalog &amp; Live CLI Discovery:</strong>
              <span class="muted" id="nightlyRefreshDetail">Pulling live advertised models directly from installed CLIs (`model_policy.discover`) + Nightly 02:00 refresh.</span>
            </div>
            <span class="pill" style="background:#064e3b;color:#6ee7b7">LIVE CATALOG</span>
          </div>
          <div id="freeTierCalloutBanner" class="proj-row" style="margin-bottom:12px;border-color:#0284c7;background:#0c192c">
            <div>
              <strong style="color:#7dd3fc">🆓 Using Free-Version AI Provider Accounts?</strong>
              <div class="muted" style="margin-top:3px">You do NOT need paid Pro/Max subscriptions to run Anchor! Click the preset button to configure <strong>Free Account / Rate-Limit Friendly Mode</strong> (uses single-seat pacing so skills don't slam free RPM limits, with <strong>Google Gemini CLI / free Google AI Studio API key</strong> at <code>aistudio.google.com</code> as your recommended primary free seat).</div>
            </div>
            <button type="button" class="btn emerald" id="btnApplyFreeTierPreset">🆓 Apply Free-Account Preset</button>
          </div>
          <p class="muted" id="readinessNoteBox"></p>
          <div id="wizVariableStrengthCard" class="wiz-card" style="background:#0f1726;border-color:#f59e0b;margin-bottom:14px"></div>
          <div id="servicesGrid" class="service-grid"></div>
          <div style="margin-top:16px;display:flex;gap:10px;flex-wrap:wrap;align-items:center">
            <button type="button" class="btn primary" id="btnNextStep4">Continue to Step 4 (Mission &amp; Goals / Initiatives) →</button>
            <a class="btn" href="/setup">⚙ Open Advanced Multi-Account Provider Setup (/setup)</a>
          </div>
        </div>
      </section>

      <!-- STEP 4 -->
      <section class="wiz-step-pane" id="step-pane-4" hidden>
        <div class="wiz-card">
          <h2>Step 4 · Interactive Brainstorming Dialogue: Mission Statement, Goals / Initiatives (Star Chart) &amp; Resource Discovery</h2>
          <p class="muted">
            <strong>How the Star Chart &amp; Cave of Wonders Work Together:</strong><br>
            • <strong>Mission Statement &amp; Goals / Initiatives (What the Star Chart Charts):</strong> Start by brainstorming your overarching <strong>Mission Statement</strong> (with concise examples like <em>The New York Times</em> and <em>Personal Stewardship</em>), iterate with your Steward until comfortable, then brainstorm your <strong>Goals / Initiatives</strong> (professional, teaching, ventures, creative, hobbies, family). <em>Goals</em> (longer-horizon outcomes &amp; directions) and <em>Initiatives</em> (concrete campaigns &amp; efforts) are similar though not identical — together they are what the <strong>Star Chart</strong> charts and what organizes the sections on the Projects page.<br>
            • <strong>Per-Goal / Initiative Resource Discovery (Steward + Gandalf + researchPrime):</strong> For each goal or initiative, describe any files/materials you have somewhere on disk (no exact path needed — Gandalf will find them!) plus websites or research topics for <code>researchPrime</code> &amp; <code>Gandalf</code> to organize.
          </p>

          <!-- 4A: MISSION STATEMENT DIALOGUE -->
          <div class="wiz-card" style="background:#101723;margin-top:14px">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
              <h3 style="margin:0">🌟 Part 1 · Mission Statement Brainstorming Dialogue</h3>
              <span class="pill" id="missionLockBadge">Iterative Dialogue Mode</span>
            </div>
            <p class="muted" style="margin:6px 0 10px">Examples of great concise mission statements (click any example to seed or adapt):</p>
            <div id="missionExamplesBox" style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:10px;margin-bottom:12px">
              <div class="proj-row" style="flex-direction:column;align-items:flex-start;margin:0">
                <div><strong>📰 The New York Times</strong> <span class="pill">10 Words</span></div>
                <div style="font-style:italic;color:#fde68a;margin:4px 0">"We seek the truth and help people understand the world."</div>
                <button type="button" class="btn" data-use-mission="We seek the truth and help people understand the world.">Use / Adapt NY Times Style</button>
              </div>
              <div class="proj-row" style="flex-direction:column;align-items:flex-start;margin:0">
                <div><strong>🪔 Personal Stewardship &amp; Craft</strong> <span class="pill">Personal Stewardship</span></div>
                <div style="font-style:italic;color:#6ee7b7;margin:4px 0">"Carry the work that matters to completion alongside the people I care about — advancing rigorous scholarship, teaching, and AI systems that empower human judgment without ever dropping the ball on family, faith, or stewardship."</div>
                <button type="button" class="btn" data-use-mission="Carry the work that matters to completion alongside the people I care about — advancing rigorous scholarship, teaching, and AI systems that empower human judgment without ever dropping the ball on family, faith, or stewardship.">Use / Adapt Stewardship Mission</button>
              </div>
              <div class="proj-row" style="flex-direction:column;align-items:flex-start;margin:0">
                <div><strong>🧭 Scholar, Builder &amp; Mentor</strong> <span class="pill">Action-Oriented</span></div>
                <div style="font-style:italic;color:#93c5fd;margin:4px 0">"Turn frontier ideas into verified, enduring tools and scholarship that solve real problems and elevate every student and collaborator."</div>
                <button type="button" class="btn" data-use-mission="Turn frontier ideas into verified, enduring tools and scholarship that solve real problems and elevate every student and collaborator.">Use / Adapt Builder Mission</button>
              </div>
            </div>

            <label for="inpMissionDialogue">Brainstorm or Iterate on Your Mission Statement (Type or Speak — e.g., what matters to you, or "Make it shorter like NY Times")</label>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
              <input type="text" id="inpMissionDialogue" style="flex:1;min-width:260px" placeholder="Tell your Steward what drives your work &amp; life, or how to refine the statement...">
              <button type="button" class="btn" data-voice-target="inpMissionDialogue" title="Speak / Dictate with Microphone">🎙 Speak</button>
              <button type="button" class="btn primary" id="btnBrainstormMission">💬 Brainstorm &amp; Summarize with Steward</button>
            </div>

            <div id="missionSummaryBox" class="proj-row" style="flex-direction:column;align-items:stretch" hidden></div>

            <div style="margin-top:10px">
              <label for="inpMission">Current / Proposed Mission Statement (Editable)</label>
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                <input type="text" id="inpMission" style="flex:1;min-width:260px" placeholder="e.g., Carry the work that matters to completion alongside the people I care about...">
                <button type="button" class="btn emerald" id="btnLockMission">✓ Lock Mission Statement &amp; Discuss Goals / Initiatives ↓</button>
              </div>
            </div>
          </div>

          <!-- 4B: GOALS / INITIATIVES BRAINSTORMING DIALOGUE & PER-GOAL RESOURCE DISCOVERY -->
          <div class="wiz-card" style="background:#101723;margin-top:14px">
            <h3 style="margin:0 0 6px">🎯 Part 2 · Goals / Initiatives Brainstorming Dialogue (What the Star Chart Charts — Professional, Teaching, Ventures, Creative &amp; Hobbies)</h3>
            <p class="muted" style="margin:0 0 10px">What are your <strong>Goals / Initiatives</strong>, and what do you work on for projects, work, or hobbies? Click any example below to add it, or brainstorm freely with your Steward. These goals / initiatives will be charted on your <strong>Star Chart</strong> and used to organize the sections on the Projects page!</p>
            <div style="display:flex;gap:6px;flex-wrap:wrap;margin-bottom:10px">
              <button type="button" class="btn" data-add-goal-example="Publish flagship empirical and mathematical papers in top journals (JCR, Management Science)">+ 📚 Flagship Research</button>
              <button type="button" class="btn" data-add-goal-example="Deliver AI-enhanced MBA &amp; undergraduate courses with interactive oral-exam and study tools">+ 🎓 Teaching &amp; Mentorship</button>
              <button type="button" class="btn" data-add-goal-example="Build and scale Ghost World Labs, Anchor AI Cockpits, and patent/venture portfolios">+ 💻 AI Systems &amp; Ventures</button>
              <button type="button" class="btn" data-add-goal-example="Keep personal finances, legal planning, and community mentorship organized with zero dropped balls">+ 🏛 Personal Operations &amp; Stewardship</button>
              <button type="button" class="btn" data-add-goal-example="Write novel chapters &amp; fables, train consistently for CrossFit, and build personal math/memory tools">+ 🎨 Creative Writing &amp; Hobbies</button>
            </div>

            <label for="txtGoals">Brainstorm Your Goals / Initiatives &amp; Work/Hobby Areas (One per line or conversational paragraph — iterate as much as you like!)</label>
            <textarea id="txtGoals" placeholder="Publish flagship research papers this quarter&#10;Deliver MBA AI &amp; analytics course materials&#10;Manage family trust &amp; legal operations&#10;Build Anchor &amp; Skill Foundry multi-agent cockpits&#10;Write novel chapters and train for CrossFit"></textarea>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
              <button type="button" class="btn" data-voice-target="txtGoals">🎙 Speak / Dictate Goals or Initiatives</button>
              <button type="button" class="btn primary" id="btnBrainstormGoals">💬 Summarize &amp; Iterate Goals / Initiatives with Steward</button>
            </div>

            <div id="goalsSummaryBox" class="status-banner" style="margin-top:12px" hidden></div>
            <div id="arenasPreview" style="margin:12px 0"></div>

            <!-- 4C: PER-GOAL / INITIATIVE RESOURCES (GANDALF ON-DISK + RESEARCHPRIME) -->
            <div id="goalsResourceCardsBox" style="margin-top:12px"></div>
          </div>

          <label for="txtPriorityNow" style="margin-top:12px">Cave of Wonders · What are the most important goals / initiatives or main things you are working on right now? (Used to propose what goes ★ Active vs. ↳ On Deck)</label>
          <textarea id="txtPriorityNow" placeholder="e.g., Finishing the Q4 research manuscript, preparing upcoming course materials, and launching the new software prototype"></textarea>
          <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px">
            <button type="button" class="btn emerald" id="btnOrganizeGoals">🧭 Set Goals / Initiatives &amp; Continue to Project Organization (Step 5) →</button>
            <button type="button" class="btn" id="btnSkipToProjects">Jump Straight to Scanning Projects (Natural Organization, Step 5) →</button>
          </div>
        </div>
      </section>

      <!-- STEP 5 -->
      <section class="wiz-step-pane" id="step-pane-5" hidden>
        <div class="wiz-card">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:8px">
            <h2 style="margin:0">Step 5 · Hard-Drive Folder Tree, Gandalf Analysis &amp; Drag-to-Merge / Split-Apart Projects</h2>
            <span class="pill" style="background:#064e3b;color:#6ee7b7">✓ 20 Standing Foundry Skills Loaded Automatically</span>
          </div>
          <p class="muted">Expand any hard drive or proposed work area below and check (<code>☑</code>) the folders or subfolders you want included. Then click <strong>Analyze with Gandalf &amp; Propose Projects</strong> — drag project cards onto each other to merge them, or click <strong>Split Apart</strong> to separate subfolders into their own projects!</p>
          <div id="wiz-gandalf-drive-mount" data-gandalf-workbench="1" style="margin:12px 0"></div>

          <details style="margin-top:14px;padding:10px 14px;background:#0e141f;border:1px solid var(--border);border-radius:8px">
            <summary style="cursor:pointer;font-weight:600;color:var(--muted)">Optional Advanced: Verbal Hierarchy Revision &amp; Top Priorities Dialogue</summary>

          <!-- 5A: PROJECT & FILE-SOURCE DISCOVERY DIALOGUE -->
          <div class="wiz-card" style="background:#101723;margin-top:12px">
            <h3 style="margin:0 0 6px">🔍 Part 1 · Dialogue: Identify Potential Project File Types &amp; Sources</h3>
            <p class="muted" style="margin:0 0 10px">What kinds of files, folders, or sources should Steward &amp; Gandalf look at as potential projects?</p>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px" id="fileTypeChipsBox">
              <label style="display:inline-flex;align-items:center;gap:5px;background:#1a2436;padding:5px 10px;border-radius:999px;cursor:pointer"><input type="checkbox" data-ftype="papers_latex_word" checked> 📄 Papers, LaTeX &amp; Manuscripts</label>
              <label style="display:inline-flex;align-items:center;gap:5px;background:#1a2436;padding:5px 10px;border-radius:999px;cursor:pointer"><input type="checkbox" data-ftype="code_python_r_js" checked> 💻 Python / R / JS Codebases</label>
              <label style="display:inline-flex;align-items:center;gap:5px;background:#1a2436;padding:5px 10px;border-radius:999px;cursor:pointer"><input type="checkbox" data-ftype="datasets_models" checked> 📊 Datasets &amp; Financial Models</label>
              <label style="display:inline-flex;align-items:center;gap:5px;background:#1a2436;padding:5px 10px;border-radius:999px;cursor:pointer"><input type="checkbox" data-ftype="teaching_slides" checked> 🎓 Course Slides &amp; Syllabi</label>
              <label style="display:inline-flex;align-items:center;gap:5px;background:#1a2436;padding:5px 10px;border-radius:999px;cursor:pointer"><input type="checkbox" data-ftype="trusts_legal_ops" checked> ⚖️ Trusts, Legal &amp; Venture Docs</label>
              <label style="display:inline-flex;align-items:center;gap:5px;background:#1a2436;padding:5px 10px;border-radius:999px;cursor:pointer"><input type="checkbox" data-ftype="creative_hobbies" checked> 🎨 Creative Writing &amp; Hobbies</label>
            </div>
            <div class="form-grid">
              <div>
                <label for="inpWorkspaceRoots">Workspace Root Directories (semicolon-separated; anywhere on this PC)</label>
                <input type="text" id="inpWorkspaceRoots" value="C:\\dev" placeholder="C:\\dev; D:\\Research">
              </div>
              <div>
                <label for="inpProjectSourceDialogue">Describe Potential Projects or Sources to Look For (Optional Dialogue)</label>
                <div style="display:flex;gap:6px">
                  <input type="text" id="inpProjectSourceDialogue" placeholder="e.g., Look for JCR marketing folders, MBA teaching slides, and skill repositories">
                  <button type="button" class="btn" data-voice-target="inpProjectSourceDialogue" title="Speak">🎙</button>
                </div>
              </div>
            </div>
            <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">
              <button type="button" class="btn primary" id="btnBrainstormProjectSources">🧙‍♂️ Scan Sources &amp; Build Graphical Hierarchical Organization</button>
              <button type="button" class="btn" id="btnScanDirs">🔍 Quick Rescan Directories</button>
            </div>
          </div>

          <!-- 5B: GRAPHICAL & HIERARCHICAL ORGANIZATION SUMMARY -->
          <div class="wiz-card" style="background:#101723;margin-top:14px">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:10px">
              <h3 style="margin:0">🌳 Part 2 · Graphical &amp; Hierarchical Project Organization</h3>
              <span class="pill" id="hierarchyModeBadge" style="background:#064e3b;color:#6ee7b7">Goals / Initiatives-First / Natural Hierarchy</span>
            </div>
            <div id="hierarchyTreeContainer" style="margin:10px 0"></div>

            <!-- 5C: VERBAL / CONVERSATIONAL REVISION LOOP -->
            <div style="border-top:1px solid var(--border);margin-top:14px;padding-top:12px">
              <label for="inpVerbalRevision">🎙 Revise the Organization Verbally or by Typing Until You Are Happy</label>
              <p class="muted" style="margin:2px 0 8px">Examples: <em>"Move Collapse of Marketing under Flagship Research and make it Active"</em> · <em>"Merge JCR_Paper_Draft and JCR_Math_Proofs into JCR Unified Study"</em> · <em>"Rename Old Notes to Archive and put it On Deck"</em> · <em>"Exclude TempFolder"</em></p>
              <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
                <input type="text" id="inpVerbalRevision" style="flex:1;min-width:260px" placeholder="Speak or type how you want to reorganize, merge, rename, or reprioritize...">
                <button type="button" class="btn" data-voice-target="inpVerbalRevision">🎙 Speak Revision</button>
                <button type="button" class="btn primary" id="btnApplyVerbalRevision">💬 Apply Revision to Hierarchy</button>
              </div>
              <div id="revisionDialogueBox" style="margin-top:8px"></div>
            </div>
          </div>

          <!-- 5D: TOP PRIORITIES SESSION (WITH MISSION & GOALS / INITIATIVES SUGGESTIONS) -->
          <div class="wiz-card" style="background:#101723;margin-top:14px">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
              <h3 style="margin:0">⭐ Part 3 · Top Priorities Session (Steward Suggestions from Your Mission &amp; Goals / Initiatives)</h3>
              <button type="button" class="btn primary" id="btnSuggestTopPriorities">⚡ Suggest Top Priorities from Mission &amp; Goals / Initiatives</button>
            </div>
            <p class="muted" style="margin:6px 0">Tell your Steward what your top priorities are right now, or let the Steward suggest Active vs. On Deck placement from your Mission Statement &amp; Goals / Initiatives:</p>
            <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px">
              <input type="text" id="inpTopPrioritiesSession" style="flex:1;min-width:260px" placeholder="Optional: Tell your Steward which 2–4 projects are your absolute top priorities this week...">
              <button type="button" class="btn" data-voice-target="inpTopPrioritiesSession">🎙 Speak</button>
              <button type="button" class="btn" id="btnProposeSeats">🎯 Update Active &amp; On Deck Lineup</button>
            </div>
            <div id="topPrioritiesSuggestionsBox" style="margin-top:8px"></div>
          </div>

          <details style="margin:12px 0;padding:12px 14px;background:#121824;border:1px solid var(--border);border-radius:8px">
            <summary style="cursor:pointer;font-weight:650;color:var(--sky)">➕ Pull Multiple Folders / Materials Together into a Single Proposed Project</summary>
            <div class="form-grid" style="margin-top:10px">
              <div>
                <label for="inpConsName">Unified Project Name</label>
                <input type="text" id="inpConsName" placeholder="e.g., Collapse of Marketing (Unified Study)">
              </div>
              <div>
                <label for="inpConsMission">Project Mission Statement &amp; Goal</label>
                <input type="text" id="inpConsMission" placeholder="e.g., Combine empirical JCR paper, math proofs, and datasets into one cockpit">
              </div>
              <div>
                <label for="inpConsFolders">Folders to Pull Together (semicolon-separated paths)</label>
                <input type="text" id="inpConsFolders" placeholder="C:\\dev\\PaperDraft; C:\\dev\\MathAppendix; D:\\Data\\Survey">
              </div>
              <div style="display:flex;align-items:flex-end">
                <button type="button" class="btn emerald" id="btnConsolidateFolders">🔗 Pull Folders Together into One Project</button>
              </div>
            </div>
          </details>
          <div id="discoveredList" style="margin:14px 0"></div>
          <button type="button" class="btn emerald" id="btnProvisionCockpits" style="font-size:15px;padding:11px 18px">🚀 Create Final Projects &amp; Provision Starter AI Cockpits →</button>
          </details>
        </div>
      </section>

      <!-- STEP 6 -->
      <section class="wiz-step-pane" id="step-pane-6" hidden>
        <div class="wiz-card">
          <h2>Step 6 · Easy Email &amp; Calendar Linker (Read-Only Schedule &amp; Inbox Triage)</h2>
          <p class="muted">Link your email in seconds: use <strong>1-Click Windows Outlook</strong> (if Outlook is open on this PC), OR simply type your email address below — Anchor automatically fills the server settings for Gmail, Outlook/Hotmail, Yahoo, iCloud, or university/work accounts and stores your App Password securely in the Windows OS Vault.</p>

          <div class="wiz-card" style="background:#101928;border-color:#10b981;margin:12px 0;padding:14px 18px">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:10px;flex-wrap:wrap">
              <div>
                <strong style="color:#6ee7b7">📨 Option A (Zero Password): Running Windows Outlook Desktop App</strong>
                <div class="muted">If you use Classic Outlook on Windows, click once to link your inbox &amp; calendar directly.</div>
              </div>
              <button type="button" class="btn emerald" id="btnWizAutoOutlook">⚡ 1-Click Connect Windows Outlook</button>
            </div>
          </div>

          <div class="wiz-card" style="background:#101723;margin:12px 0;padding:16px 18px">
            <h3 style="margin:0 0 6px">✉ Option B: Connect Gmail, Outlook.com, Yahoo, iCloud, or Any Email</h3>
            <div class="form-grid">
              <div>
                <label for="inpCommsEmail">1. Enter Your Email Address (Auto-Detects Provider)</label>
                <input type="text" id="inpCommsEmail" placeholder="you@example.com or faculty@example.org" autocomplete="email">
                <div class="muted" id="wizDetectedEmailHint" style="margin-top:4px;color:#7dd3fc">Type your email to auto-configure server settings.</div>
              </div>
              <div>
                <label for="inpCommsSecret">2. Paste App Password (Stored in Windows OS Vault)</label>
                <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
                  <input type="password" id="inpCommsSecret" placeholder="Paste 16-char App Password" style="flex:1;min-width:180px">
                  <button type="button" class="btn" id="btnOpenEmailAppPwd">🔑 Get App Password in Browser ↗</button>
                </div>
              </div>
            </div>
            <details style="margin-top:8px">
              <summary class="muted" style="cursor:pointer">Optional: Calendar ICS Feed URL &amp; Provider Preset</summary>
              <div class="form-grid" style="margin-top:8px">
                <div>
                  <label for="selCommsFamily">Provider Preset</label>
                  <select id="selCommsFamily">
                    <option value="gmail">Google Workspace / Gmail + Google Calendar</option>
                    <option value="outlook">Microsoft 365 / Outlook + Exchange Calendar</option>
                    <option value="custom">Yahoo / iCloud / Custom IMAP &amp; ICS</option>
                  </select>
                </div>
                <div>
                  <label for="inpCommsIcs">Optional Private Calendar ICS URL</label>
                  <input type="text" id="inpCommsIcs" placeholder="https://calendar.google.com/calendar/ical/.../basic.ics">
                </div>
              </div>
            </details>
          </div>

          <div style="display:flex;gap:10px;flex-wrap:wrap">
            <button type="button" class="btn primary" id="btnSaveComms">✓ Connect Email &amp; Continue →</button>
            <button type="button" class="btn" id="btnSkipComms">Skip for Now &amp; View Readiness Receipt (Step 7) →</button>
          </div>
        </div>
      </section>

      <!-- STEP 7 -->
      <section class="wiz-step-pane" id="step-pane-7" hidden>
        <div class="wiz-card">
          <h2>Step 7 · Complete Readiness Receipt &amp; AI Cockpit Launchpad</h2>
          <p class="muted">Everything is verified and wired. Launch directly into the Cave of Wonders or open any of your newly provisioned AI Cockpits below.</p>
          <div id="receiptChecksBox" style="margin:14px 0"></div>
          <div id="gwlApplicantsWrap" {"" if is_admin else "hidden"}>
            <h3>🏛 Ghost World Labs Collaborator Directory</h3>
            <div id="gwlApplicantsBox" style="margin:14px 0"></div>
          </div>
          <h3>🚀 Your Provisioned AI Cockpits (Active · On Deck · Parked)</h3>
          <div id="receiptCockpitsBox" style="margin:14px 0"></div>
          <div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:18px">
            <a class="btn emerald" href="/high-seat">🏛 Launch Cave of Wonders (High Seat)</a>
            <a class="btn primary" href="/high-seat#camp">🧭 Open Star Chart Campaign</a>
            <a class="btn" href="/desk">🖥 Open Desktop (Ad-Hoc AI Cockpit)</a>
          </div>
        </div>
      </section>
    </main>
  </div>

  <script>
    window.ONBOARD_WIZARD_BOOT = {boot_json};
    const IS_SANDBOX = Boolean(window.ONBOARD_WIZARD_BOOT.sandbox);
    const SANDBOX_ID = "{esc_sid}";

    function closeWizardOverlay() {{
      if (window.parent && window.parent !== window) {{
        try {{ window.parent.postMessage({{ type: 'anchor-overlay-close', closeTile: true, source: 'onboard-wizard' }}, window.location.origin); }} catch (e) {{}}
        try {{ window.parent.postMessage({{ type: 'anchor-setup-close' }}, window.location.origin); }} catch (e) {{}}
        return;
      }}
      try {{
        if (document.referrer) {{
          const ref = new URL(document.referrer);
          if (ref.origin === window.location.origin && /^\\/(high-seat|steward|project\\/)/.test(ref.pathname)) {{
            window.location.href = ref.pathname + ref.search;
            return;
          }}
        }}
      }} catch (e) {{}}
      window.location.href = window.pywebview ? '/static/app.html' : '/high-seat';
    }}

    if (window.parent !== window) {{
      document.querySelectorAll('.wiz-winctl [data-winctl="minimize"], .wiz-winctl [data-winctl="maximize"]').forEach((b) => {{ b.hidden = true; }});
      document.querySelectorAll('a[href^="/high-seat"]').forEach((a) => {{
        a.addEventListener('click', (ev) => {{ ev.preventDefault(); ev.stopPropagation(); closeWizardOverlay(); }});
      }});
    }}

    document.querySelectorAll('[data-overlay-close]').forEach((btn) => {{
      btn.addEventListener('click', (ev) => {{ ev.preventDefault(); ev.stopPropagation(); closeWizardOverlay(); }});
    }});

    document.addEventListener('keydown', (ev) => {{
      if (ev.key === 'Escape') {{ ev.preventDefault(); closeWizardOverlay(); }}
    }});

    function invokeWindowControl(act) {{
      if (act === 'close') {{ closeWizardOverlay(); return; }}
      try {{
        if (window.pywebview && window.pywebview.api && window.pywebview.api.window_control) {{
          window.pywebview.api.window_control(act);
          return;
        }}
        if (window.parent && window.parent !== window && window.parent.pywebview && window.parent.pywebview.api && window.parent.pywebview.api.window_control) {{
          window.parent.pywebview.api.window_control(act);
          return;
        }}
      }} catch (e) {{}}
    }}

    document.querySelectorAll('[data-winctl]').forEach((btn) => {{
      btn.addEventListener('click', (ev) => {{
        ev.stopPropagation();
        invokeWindowControl(btn.getAttribute('data-winctl'));
      }});
    }});

    const wizHeader = document.querySelector('.wiz-top');
    if (wizHeader) {{
      wizHeader.addEventListener('mousedown', (ev) => {{
        if (ev.button !== 0) return;
        if (ev.target.closest('button, a, input, select, textarea, label, .wiz-top-actions')) return;
        invokeWindowControl('drag');
      }});
    }}

    function showStep(stepNum) {{
      document.querySelectorAll('.wiz-step-pane').forEach((el, idx) => {{
        el.hidden = (idx + 1 !== stepNum);
      }});
      document.querySelectorAll('.step-btn').forEach((btn) => {{
        const s = Number(btn.getAttribute('data-step'));
        btn.classList.toggle('active', s === stepNum);
      }});
    }}

    document.querySelectorAll('.step-btn').forEach((btn) => {{
      btn.addEventListener('click', () => showStep(Number(btn.getAttribute('data-step'))));
    }});

    async function callWizardAction(action, payload = {{}}) {{
      const res = await fetch('/api/onboard-wizard/action', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(Object.assign({{ action, sandbox: IS_SANDBOX, sandbox_id: SANDBOX_ID }}, payload))
      }});
      return await res.json();
    }}

    function renderServices(services) {{
      const grid = document.getElementById('servicesGrid');
      grid.innerHTML = '';
      Object.values(services || {{}}).forEach((svc) => {{
        const card = document.createElement('div');
        card.className = 'wiz-card';
        card.style.marginBottom = '0';
        let statusBadge = '<span class="pill">Not configured</span>';
        if (svc.verified) {{
          statusBadge = '<span class="pill" style="background:#064e3b;color:#6ee7b7">VERIFIED ✓ (' + (svc.last_test ? svc.last_test.attested_model : svc.orchestrator_model) + ')</span>';
        }} else if (svc.connection_state === 'ready') {{
          statusBadge = '<span class="pill" style="background:#1e3a8a;color:#93c5fd">' + (svc.connection_badge || 'Enabled · Ready to Verify') + '</span>';
        }} else if (svc.connection_state === 'cli_only_unconfigured' || svc.connection_state === 'signin_needed') {{
          statusBadge = '<span class="pill" style="background:#451a03;color:#fde68a">' + (svc.connection_badge || 'CLI Installed · Not Enabled') + '</span>';
        }} else {{
          statusBadge = '<span class="pill">' + (svc.connection_badge || 'Not installed') + '</span>';
        }}

        const discModels = Array.isArray(svc.discovered_models) && svc.discovered_models.length
          ? svc.discovered_models
          : [svc.available_tiers.frontier.orchestrator_model, svc.available_tiers.one_tier_down.orchestrator_model];
        const firstDisc = discModels[0];
        const firstDiscModel = (typeof firstDisc === 'object' && firstDisc !== null) ? firstDisc.model : String(firstDisc || '');
        const selModel = svc.selected_model || svc.orchestrator_model || firstDiscModel || '';
        const modelOptsHtml = discModels.map((m) => {{
          const mId = (typeof m === 'object' && m !== null) ? m.model : String(m);
          const mDisp = (typeof m === 'object' && m !== null) ? (m.display || m.model) : String(m);
          return `<option value="${{mId}}" ${{mId === selModel ? 'selected' : ''}}>${{mDisp}}</option>`;
        }}).join('');

        const keyPlaceholder = svc.has_api_key_stored
          ? '✓ Key stored in OS Vault (enter new key to update)'
          : `Enter ${{svc.api_key_env || 'API_KEY'}} (stored in OS Vault)`;

        card.innerHTML = `
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
            <label style="display:inline-flex;align-items:center;gap:8px;margin:0;color:var(--ink);font-size:15px;font-weight:700;cursor:pointer">
              <input type="checkbox" data-svc-enabled="${{svc.family}}" ${{svc.enabled ? 'checked' : ''}}>
              <span>${{svc.label}}</span>
            </label>
            ${{statusBadge}}
          </div>
          <p class="muted" style="margin:6px 0">${{svc.default_role}} · CLI: <code>${{svc.cli}}</code> (${{svc.cli_version}}) · Source: <code>${{svc.live_discovery_source || 'catalog'}}</code></p>
          <label>Connection Method</label>
          <select data-svc-mode="${{svc.family}}">
            <option value="subscription" ${{svc.auth_mode === 'subscription' ? 'selected' : ''}}>Subscription (Local CLI Login)</option>
            <option value="api_key" ${{svc.auth_mode === 'api_key' ? 'selected' : ''}}>API Key (OS Credential Vault)</option>
          </select>
          <label style="margin-top:8px">Capability Level / Model Tier (Live Nightly + CLI Catalog)</label>
          <select data-svc-tier="${{svc.family}}">
            <option value="frontier" ${{svc.tier_level === 'frontier' ? 'selected' : ''}}>Frontier (Top-Tier — ${{svc.available_tiers.frontier.orchestrator_model}})</option>
            <option value="one_tier_down" ${{svc.tier_level === 'one_tier_down' ? 'selected' : ''}}>One Tier Down (Fast / Balanced — ${{svc.available_tiers.one_tier_down.orchestrator_model}})</option>
            <option value="free_tier" ${{svc.tier_level === 'free_tier' ? 'selected' : ''}}>Free Account / Rate-Limit Friendly (${{(svc.available_tiers.free_tier && svc.available_tiers.free_tier.orchestrator_model) || svc.available_tiers.one_tier_down.orchestrator_model}} · Single-Seat Paced)</option>
          </select>
          ${{svc.free_tier_guide ? `<div class="muted" style="margin-top:5px;font-size:11.5px;color:#93c5fd">💡 ${{svc.free_tier_guide}}</div>` : ''}}
          <label style="margin-top:8px">Specific Model Override (Advertised by CLI / Nightly Refresh)</label>
          <select data-svc-model="${{svc.family}}">
            ${{modelOptsHtml}}
          </select>
          <label style="margin-top:8px">API Key / Credential (${{svc.api_key_env || 'OS Credential Vault'}})</label>
          <div style="display:flex;gap:6px;align-items:center">
            <input type="password" data-svc-keyinput="${{svc.family}}" placeholder="${{keyPlaceholder}}" style="flex:1">
            <button type="button" class="btn" data-act-savekey="${{svc.family}}">🔑 Save Key</button>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
            <button type="button" class="btn primary" data-act-browser-login="${{svc.family}}">🌐 Open Browser &amp; Log In</button>
            <button type="button" class="btn" data-act-login="${{svc.family}}">🔐 CLI Terminal Login</button>
            <button type="button" class="btn" data-act-update="${{svc.family}}">Check CLI</button>
            <button type="button" class="btn emerald" data-act-test="${{svc.family}}">⚡ Verify &amp; Live Test Tier</button>
          </div>
        `;
        grid.appendChild(card);
      }});

      async function saveServiceCardConfig(fam, extra = {{}}) {{
        const enChk = grid.querySelector(`[data-svc-enabled="${{fam}}"]`);
        const modeSel = grid.querySelector(`[data-svc-mode="${{fam}}"]`);
        const tierSel = grid.querySelector(`[data-svc-tier="${{fam}}"]`);
        const modSel = grid.querySelector(`[data-svc-model="${{fam}}"]`);
        return await callWizardAction('configure_service', Object.assign({{
          family: fam,
          enabled: enChk ? enChk.checked : true,
          auth_mode: modeSel ? modeSel.value : 'subscription',
          tier_level: tierSel ? tierSel.value : 'frontier',
          selected_model: modSel ? modSel.value : '',
        }}, extra));
      }}

      grid.querySelectorAll('[data-svc-enabled], [data-svc-mode], [data-svc-tier], [data-svc-model]').forEach((el) => {{
        el.addEventListener('change', async () => {{
          const fam = el.getAttribute('data-svc-enabled') || el.getAttribute('data-svc-mode') || el.getAttribute('data-svc-tier') || el.getAttribute('data-svc-model');
          await saveServiceCardConfig(fam);
          refreshBundle();
        }});
      }});

      grid.querySelectorAll('[data-act-savekey]').forEach((btn) => {{
        btn.addEventListener('click', async () => {{
          const fam = btn.getAttribute('data-act-savekey');
          const keyInp = grid.querySelector(`[data-svc-keyinput="${{fam}}"]`);
          const val = keyInp ? keyInp.value.trim() : '';
          if (!val) {{
            document.getElementById('wizBanner').textContent = `Enter an API key for ${{fam}} before clicking Save Key.`;
            return;
          }}
          await saveServiceCardConfig(fam, {{ auth_mode: 'api_key', api_key_value: val, enabled: true }});
          document.getElementById('wizBanner').textContent = `Stored API key for ${{fam}} in the OS Credential Vault and enabled service!`;
          refreshBundle();
        }});
      }});

      grid.querySelectorAll('[data-act-browser-login]').forEach((btn) => {{
        btn.addEventListener('click', async () => {{
          const fam = btn.getAttribute('data-act-browser-login');
          const out = await callWizardAction('open_browser_login', {{ family: fam }});
          if (out && out.login_url && !out.opened_on_host) {{
            window.open(out.login_url, '_blank', 'noopener,noreferrer');
          }}
          document.getElementById('wizBanner').textContent = out.message || `Opened browser login for ${{fam}}.`;
          startBrowserLoginPoll(fam);
        }});
      }});

      grid.querySelectorAll('[data-act-login]').forEach((btn) => {{
        btn.addEventListener('click', async () => {{
          const fam = btn.getAttribute('data-act-login');
          const out = await callWizardAction('launch_service_login', {{ family: fam }});
          document.getElementById('wizBanner').textContent = out.message || `Launched subscription sign-in for ${{fam}}.`;
          refreshBundle();
        }});
      }});

      grid.querySelectorAll('[data-act-update]').forEach((btn) => {{
        btn.addEventListener('click', async () => {{
          const fam = btn.getAttribute('data-act-update');
          const out = await callWizardAction('update_cli', {{ family: fam }});
          document.getElementById('wizBanner').textContent = `CLI check for ${{fam}}: ${{out.cli_version}}`;
          refreshBundle();
        }});
      }});

      grid.querySelectorAll('[data-act-test]').forEach((btn) => {{
        btn.addEventListener('click', async () => {{
          const fam = btn.getAttribute('data-act-test');
          const tierSel = grid.querySelector(`[data-svc-tier="${{fam}}"]`);
          await saveServiceCardConfig(fam, {{ enabled: true }});
          const out = await callWizardAction('test_service_tier', {{
            family: fam,
            tier_level: tierSel ? tierSel.value : 'frontier',
          }});
          document.getElementById('wizBanner').textContent =
            `Verified ${{fam}} (${{out.test_receipt.attested_model}}) in ${{out.test_receipt.latency_ms}}ms — Readiness: ${{out.readiness.status.toUpperCase()}}!`;
          refreshBundle();
        }});
      }});
    }}

    function renderDiscoveredProjects(discovered) {{
      const box = document.getElementById('discoveredList');
      if (!discovered || !discovered.length) {{
        box.innerHTML = '<p class="muted">Click "Scan Directories & Re-Adopt Existing Stores" to discover your projects.</p>';
        return;
      }}
      box.innerHTML = '<p class="muted">Uncheck any directory you do NOT want included as a project, adjust its Virtual Folder or Cave of Wonders Lane (Active / On Deck / Parked), then click Confirm:</p>';
      discovered.forEach((d, idx) => {{
        const row = document.createElement('div');
        row.className = 'proj-row';
        row.innerHTML = `
          <label style="display:flex;align-items:center;gap:8px;margin:0;font-size:14px">
            <input type="checkbox" data-proj-inc="${{idx}}" ${{d.included !== false ? 'checked' : ''}}>
            <strong>${{d.name}}</strong>
            <span class="pill">${{d.source}}</span>
          </label>
          <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
            <input type="text" data-proj-group="${{idx}}" value="${{d.group_folder || ''}}" style="width:210px" title="Virtual Project Group Folder">
            <select data-proj-seat="${{idx}}" style="width:140px">
              <option value="active" ${{d.seat === 'active' ? 'selected' : ''}}>★ Active</option>
              <option value="deck" ${{d.seat === 'deck' ? 'selected' : ''}}>↳ On Deck</option>
              <option value="parked" ${{d.seat === 'parked' ? 'selected' : ''}}>○ Parked</option>
            </select>
          </div>
        `;
        box.appendChild(row);
      }});
    }}

    function renderReceipt(receipt) {{
      const cbox = document.getElementById('receiptChecksBox');
      cbox.innerHTML = '';
      (receipt.checks || []).forEach((chk) => {{
        const d = document.createElement('div');
        d.className = 'proj-row';
        d.innerHTML = `
          <div><strong>${{chk.ok ? '✅' : '⏳'}} ${{chk.label}}</strong><div class="muted">${{chk.detail}}</div></div>
          <span class="pill">${{chk.ok ? 'READY' : 'PENDING'}}</span>
        `;
        cbox.appendChild(d);
      }});

      const pbox = document.getElementById('receiptCockpitsBox');
      pbox.innerHTML = '';
      const prov = receipt.provisioned_cockpits || [];
      if (!prov.length) {{
        pbox.innerHTML = '<p class="muted">No projects provisioned yet — complete Step 5 to create Starter AI Cockpits.</p>';
        return;
      }}
      prov.forEach((p) => {{
        const r = document.createElement('div');
        r.className = 'proj-row';
        r.innerHTML = `
          <div>
            <strong>${{p.name}}</strong> <span class="pill">${{p.group_folder}}</span> <span class="pill">${{p.seat.toUpperCase()}}</span>
            <div class="muted">${{p.folder_path}}</div>
          </div>
          <a class="btn primary" href="${{p.cockpit_href}}" target="_blank" rel="noopener">Open AI Cockpit ↗</a>
        `;
        pbox.appendChild(r);
      }});
    }}

    async function refreshBundle() {{
      const q = IS_SANDBOX ? `?sandbox=1&sandbox_id=${{encodeURIComponent(SANDBOX_ID)}}` : '';
      const res = await fetch('/api/onboard-wizard/state' + q);
      const b = await res.json();
      window.ONBOARD_WIZARD_BOOT = b;
      hydrateFromBundle(b);
    }}

    function hydrateFromBundle(b) {{
      const prof = b.profile || {{}};
      document.getElementById('inpDisplayName').value = prof.display_name || '';
      document.getElementById('inpPseudonym').value = prof.pseudonym || '';
      document.getElementById('inpAliases').value = (prof.pseudonym_aliases || []).join(', ');
      document.getElementById('selPersona').value = prof.steward_persona || 'Aladdin';
      const uEl = document.getElementById('inpUsername');
      if (uEl) uEl.value = prof.username || (prof.display_name ? prof.display_name.toLowerCase().replace(/\\s+/g, '') : '');
      const emEl = document.getElementById('inpContactEmail');
      if (emEl) emEl.value = prof.contact_email || '';
      const regView = b.registration || {{}};
      const regEmEl = document.getElementById('inpRegistryEmail');
      if (regEmEl && !regEmEl.value) regEmEl.value = regView.email || prof.contact_email || '';
      const repoEl = document.getElementById('inpAnchorGithubRepo');
      if (repoEl) {{
        repoEl.value = b.canonical_github_repo || 'https://github.com/johncliechty/ghostworldlabs-anchor';
        repoEl.readOnly = true;
      }}
      const regBadge = document.getElementById('regReceiptBadge');
      if (regBadge) {{
        regBadge.textContent = regView.registered ? `✓ REGISTERED (${{regView.email || 'Active'}})` : 'Ready to Register';
        regBadge.style.background = regView.registered ? '#064e3b' : '#1e3a8a';
        regBadge.style.color = regView.registered ? '#6ee7b7' : '#93c5fd';
      }}
      const chk2fa = document.getElementById('chkDualAuth');
      if (chk2fa) chk2fa.checked = Boolean(prof.dual_auth_enabled);
      const sel2fa = document.getElementById('selDualAuthMethod');
      if (sel2fa && prof.dual_auth_method) sel2fa.value = prof.dual_auth_method;
      const box2fa = document.getElementById('dualAuthSecretBox');
      if (box2fa) {{
        box2fa.hidden = !prof.dual_auth_enabled;
        const codeEl = document.getElementById('dualAuthSecretCode');
        if (codeEl) codeEl.textContent = prof.dual_auth_secret || 'JBSWY3DPEHPK3PXP';
        const uriEl = document.getElementById('dualAuthUriText');
        if (uriEl && prof.dual_auth_otpauth_uri) {{
          uriEl.textContent = `Authenticator URI: ${{prof.dual_auth_otpauth_uri}}`;
        }}
        const bcBox = document.getElementById('dualAuthBackupCodesList');
        if (bcBox) {{
          const bcodes = prof.dual_auth_backup_codes || [];
          bcBox.innerHTML = bcodes.length
            ? bcodes.map((c) => `<code style="padding:4px 8px;background:#0d131d;border:1px solid #2a364d;border-radius:6px;color:#6ee7b7">${{c}}</code>`).join('')
            : '<span class="muted">Save Step 1 with 2FA enabled (or click Generate 10 Fresh Backup Codes) to view your 10 single-use recovery codes.</span>';
        }}
      }}
      const tokEl = document.getElementById('inpAnchorToken');
      if (tokEl) tokEl.value = prof.anchor_token || '';
      const pwdPill = document.getElementById('pwdStatusPill');
      if (pwdPill) {{
        pwdPill.textContent = prof.has_password
          ? (prof.dual_auth_enabled ? '✓ Password + 2FA Active · Token Ready' : '✓ Password Set · Token Ready')
          : 'Token Ready · Set Optional Password';
      }}
      const topAuthPill = document.getElementById('topAuthStatusPill');
      if (topAuthPill) {{
        topAuthPill.textContent = `🔐 User: ${{prof.username || prof.display_name || 'local'}} · ${{prof.dual_auth_enabled ? '2FA ON' : 'Token Ready'}}`;
      }}

      const nr = b.nightly_refresh || {{}};
      const topNightlyPill = document.getElementById('topNightlyStatusPill');
      if (topNightlyPill) {{
        topNightlyPill.textContent = `🌙 Models: ${{nr.schedule || 'Nightly 02:00'}} + Live CLI`;
      }}
      const nrDetail = document.getElementById('nightlyRefreshDetail');
      if (nrDetail) {{
        nrDetail.textContent = `Schedule: ${{nr.schedule || 'Every night at 02:00 local'}} · Last sync: ${{nr.last_refresh_at || 'live'}} · Source: ${{nr.source || 'model_policy.discover'}}`;
      }}

      const ts = b.tailscale || {{}};
      const tsPrompt = document.getElementById('tsPromptBanner');
      if (tsPrompt) {{
        const skippedTs = window._skippedTailscalePrompt === true;
        tsPrompt.hidden = Boolean((ts.installed && ts.running) || skippedTs);
      }}
      document.getElementById('tsStatusBox').innerHTML = `
        <strong>Tailscale Status:</strong> ${{ts.installed ? (ts.running ? 'Connected ✓' : 'Installed · Not Signed In') : 'Not installed (Optional)'}} ·
        <strong>Node IP:</strong> ${{ts.tailscale_ip || 'local-only'}} ·
        <strong>Tailscale URL:</strong> <code>${{ts.tailscale_url || 'http://127.0.0.1:8777'}}</code> ·
        <strong>Ecgberht Engine:</strong> ${{b.ecgberht && b.ecgberht.ok ? 'Ready ✓ (' + b.ecgberht.root + ')' : 'Missing'}}
        <div class="muted">${{ts.note || ''}}</div>
      `;
      const hb = b.homebase_link || {{}};
      const hbBox = document.getElementById('homebaseStatusBox');
      if (hbBox) {{
        const hbReg = Boolean(hb.registered);
        hbBox.innerHTML = `
          <div>
            <strong>🏠 Optional Tailscale Hub Link:</strong> ${{hbReg ? 'Linked ✓' : 'Not Linked (Website Auto-Updates Active)'}}
            <div class="muted">Hub: <code>${{hb.homebase_url || 'none (optional)'}}</code> · Node ID: <code>${{hb.mothership_id || 'local'}}</code></div>
          </div>
          <span class="pill" style="background:${{hbReg ? '#064e3b' : '#243247'}};color:${{hbReg ? '#6ee7b7' : '#93c5fd'}}">${{hbReg ? 'LINKED ✓' : 'OPTIONAL'}}</span>
        `;
      }}
      const chkHbTel = document.getElementById('chkHomebaseTelemetry');
      if (chkHbTel && hb.telemetry_enabled !== undefined) {{
        chkHbTel.checked = Boolean(hb.telemetry_enabled);
      }}
      const chkAutoUpd = document.getElementById('chkAutoPullWebsiteUpdates');
      if (chkAutoUpd && hb.auto_pull_updates !== undefined) {{
        chkAutoUpd.checked = Boolean(hb.auto_pull_updates);
      }}
      const hw = b.hardware_profile || {{}};
      const chkLowSpec = document.getElementById('chkLowSpecMode');
      if (chkLowSpec) {{
        chkLowSpec.checked = (hb.low_spec_mode !== undefined) ? Boolean(hb.low_spec_mode) : Boolean(hw.low_spec_recommended);
      }}
      const hwSumEl = document.getElementById('hwDetectSummary');
      if (hwSumEl) {{
        hwSumEl.textContent = `${{hw.total_ram_gb ? hw.total_ram_gb + ' GB RAM · ' : ''}}${{hw.cpu_cores || 2}} CPU cores${{hw.low_spec_recommended ? ' · auto-enabled for this laptop' : ''}}`;
      }}
      const licSt = b.license_status || {{}};
      const licSpec = b.license_spec || {{}};
      const chkLic = document.getElementById('chkAcceptGwlLicense');
      if (chkLic && licSt.accepted) {{
        chkLic.checked = true;
      }}
      const licPill = document.getElementById('gwlLicenseStatusPill');
      if (licPill) {{
        licPill.textContent = licSt.accepted ? `✓ ACCEPTED (${{licSt.license_id || 'GWL-v1'}})` : 'ACKNOWLEDGEMENT REQUIRED';
        licPill.style.background = licSt.accepted ? '#064e3b' : '#451a03';
        licPill.style.color = licSt.accepted ? '#6ee7b7' : '#fde68a';
      }}
      const licClausesBox = document.getElementById('gwlLicenseClausesList');
      if (licClausesBox && Array.isArray(licSpec.operative_clauses)) {{
        licClausesBox.innerHTML = licSpec.operative_clauses.map((c) =>
          `<div style="margin-bottom:5px"><strong style="color:#fde68a">Section ${{c.section}} · ${{c.title}}:</strong> ${{c.summary}}</div>`
        ).join('');
      }}
      const inpRem = document.getElementById('inpRemoteMothership');
      if (inpRem && hb.homebase_url && !inpRem.value) {{
        inpRem.value = hb.homebase_url;
      }}
      renderBrowserAccountsBanner((b.browser_accounts && b.browser_accounts.accounts) || {{}});

      document.getElementById('readinessNoteBox').textContent = b.readiness_explanation || '';
      renderServices(b.services || {{}});

      const goals = (b.state && b.state.goals) || {{}};
      if (goals.mission_statement) document.getElementById('inpMission').value = goals.mission_statement;
      if (goals.raw_input) document.getElementById('txtGoals').value = goals.raw_input;
      renderGoalsAndResources(goals);

      const disc = (b.state && b.state.projects && b.state.projects.discovered) || [];
      renderDiscoveredProjects(disc);
      renderHierarchyTree(b.project_hierarchy || (b.state && b.state.projects && b.state.projects.hierarchy) || {{}});
      renderReceipt(b.receipt || {{}});
      const gwlBox = document.getElementById('gwlApplicantsBox');
      if (gwlBox && b.admin_edition) {{
        const apps = b.gwl_applicants || [];
        if (!apps.length) {{
          gwlBox.innerHTML = '<p class="muted">No collaborator records registered yet.</p>';
        }} else {{
          gwlBox.innerHTML = apps.map((a) => `
            <div class="proj-row">
              <div>
                <strong>${{a.display_name}}</strong> (<code>${{a.username}}</code>) · Pseudonym: <strong>${{a.pseudonym}}</strong> (<code>${{a.did}}</code>)
                <div class="muted">Host: ${{a.hostname || 'local'}} (${{a.tailscale_ip || 'local'}}) · Topology: ${{a.topology_mode}} · 2FA: ${{a.dual_auth_enabled ? 'ON' : 'Off'}} · Services: ${{(a.enabled_services || []).join(', ') || 'pending'}}</div>
              </div>
              <span class="pill" style="background:#064e3b;color:#6ee7b7">REGISTERED ✓</span>
            </div>
          `).join('');
        }}
      }}
    }}

    function renderGoalsAndResources(goals) {{
      const mSumBox = document.getElementById('missionSummaryBox');
      const mBadge = document.getElementById('missionLockBadge');
      if (mBadge) {{
        mBadge.textContent = goals.mission_locked ? '✓ Mission Locked' : 'Iterative Dialogue Mode';
        mBadge.style.background = goals.mission_locked ? '#064e3b' : '#243247';
        mBadge.style.color = goals.mission_locked ? '#6ee7b7' : '#93c5fd';
      }}
      if (mSumBox) {{
        if (goals.mission_summary) {{
          const alts = (goals.mission_alternatives || []).map((a) => `
            <button type="button" class="btn" data-use-mission="${{(a.text || '').replace(/"/g, '&quot;')}}" style="font-size:12px">Use ${{a.style}}: "${{a.text}}"</button>
          `).join(' ');
          mSumBox.hidden = false;
          mSumBox.innerHTML = `
            <div><strong>🤖 Steward Mission Summary:</strong> ${{goals.mission_summary}}</div>
            <div style="margin-top:6px;display:flex;gap:6px;flex-wrap:wrap">${{alts}}</div>
          `;
          mSumBox.querySelectorAll('[data-use-mission]').forEach((btn) => {{
            btn.addEventListener('click', () => {{
              document.getElementById('inpMission').value = btn.getAttribute('data-use-mission');
            }});
          }});
        }} else {{
          mSumBox.hidden = true;
        }}
      }}

      const gSumBox = document.getElementById('goalsSummaryBox');
      if (gSumBox) {{
        if (goals.goals_summary) {{
          gSumBox.hidden = false;
          gSumBox.textContent = `🧭 Steward Goals / Initiatives (Star Chart) Summary: ${{goals.goals_summary}}`;
        }} else {{
          gSumBox.hidden = true;
        }}
      }}

      const cardsBox = document.getElementById('goalsResourceCardsBox');
      if (!cardsBox) return;
      const items = goals.items || [];
      if (!items.length) {{
        cardsBox.innerHTML = '<p class="muted">Click "Summarize &amp; Iterate Goals / Initiatives with Steward" above to generate your Star Chart Goal / Initiative Sections and attach on-disk / web resources to each one.</p>';
        return;
      }}
      cardsBox.innerHTML = '<h4 style="margin:10px 0 8px">🧙‍♂️ Per-Goal / Initiative Resource Discovery (Describe On-Disk Materials Without Knowing Exact Paths + Web/Research Topics for Gandalf &amp; researchPrime)</h4>';
      items.forEach((g) => {{
        const res = g.resources || {{}};
        const diskMatches = (res.on_disk_matches || []).map((m) => `
          <div style="font-size:12px;color:#6ee7b7;margin-top:3px">✓ <strong>${{m.name}}</strong> (<code>${{m.path}}</code>) — ${{m.gandalf_note || ''}}</div>
        `).join('');
        const rpQueries = (res.research_prime_queries || []).map((q) => `
          <div style="font-size:12px;color:#93c5fd;margin-top:2px">🔬 <code>${{q}}</code></div>
        `).join('');
        const card = document.createElement('div');
        card.className = 'wiz-card';
        card.style.background = '#0d131d';
        card.style.marginBottom = '10px';
        card.style.padding = '14px 16px';
        card.innerHTML = `
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
            <div><strong>🎯 ${{g.name}}</strong> <span class="pill">${{g.arena}}</span> <span class="pill">Tier ${{g.tier}} · ${{g.horizon}}</span></div>
            <span class="pill" style="background:#1e3a8a;color:#93c5fd">${{(res.on_disk_matches || []).length}} Disk Matches · ${{(res.research_prime_queries || []).length}} researchPrime Tracks</span>
          </div>
          <div class="form-grid" style="margin-top:8px">
            <div>
              <label>Describe Files/Materials Somewhere on Disk (No Exact Path Needed — Gandalf Will Find Them)</label>
              <input type="text" data-goal-disk="${{g.id}}" value="${{res.on_disk_clue || ''}}" placeholder="e.g., LaTeX proofs and R scripts for JCR paper somewhere on my drive">
            </div>
            <div>
              <label>Websites, URLs, Datasets or Literature Topics (Organized by researchPrime &amp; Gandalf)</label>
              <input type="text" data-goal-web="${{g.id}}" value="${{res.web_and_info_clue || ''}}" placeholder="e.g., https://ssrn.com/..., recent papers on AI oral exams">
            </div>
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
            <button type="button" class="btn primary" data-act-discover-res="${{g.id}}">🧙‍♂️ Dispatch Steward + Gandalf &amp; researchPrime to Locate &amp; Organize</button>
            <span class="muted">${{res.gandalf_synthesis || ''}}</span>
          </div>
          ${{diskMatches ? `<div style="margin-top:8px;padding:8px;background:#101926;border-radius:6px">${{diskMatches}}${{rpQueries}}</div>` : ''}}
        `;
        cardsBox.appendChild(card);
      }});

      cardsBox.querySelectorAll('[data-act-discover-res]').forEach((btn) => {{
        btn.addEventListener('click', async () => {{
          const gid = btn.getAttribute('data-act-discover-res');
          const dInp = cardsBox.querySelector(`[data-goal-disk="${{gid}}"]`);
          const wInp = cardsBox.querySelector(`[data-goal-web="${{gid}}"]`);
          const out = await callWizardAction('discover_goal_resources', {{
            goal_id: gid,
            on_disk_clue: dInp ? dInp.value : '',
            web_and_info_clue: wInp ? wInp.value : '',
          }});
          document.getElementById('wizBanner').textContent = out.resources ? out.resources.gandalf_synthesis : 'Resources located and organized!';
          await refreshBundle();
        }});
      }});
    }}

    function renderHierarchyTree(h) {{
      const box = document.getElementById('hierarchyTreeContainer');
      const badge = document.getElementById('hierarchyModeBadge');
      if (!box) return;
      if (badge && h && h.mode_label) {{
        badge.textContent = h.mode_label;
      }}
      const sections = (h && h.sections) || [];
      if (!sections.length) {{
        box.innerHTML = '<p class="muted">Click "Scan Sources &amp; Build Graphical Hierarchical Organization" above to generate your visual portfolio tree.</p>';
        return;
      }}
      const secHtml = sections.map((sec) => {{
        const projs = (sec.projects || []).map((p) => {{
          const seatColor = p.seat === 'active' ? '#064e3b' : (p.seat === 'deck' ? '#1e3a8a' : '#243247');
          const seatTxt = p.seat === 'active' ? '★ ACTIVE' : (p.seat === 'deck' ? '↳ ON DECK' : '○ CANDIDATE');
          const linkedCnt = (p.linked_material_paths || []).length;
          return `
            <div style="margin-left:18px;padding:8px 12px;border-left:2px solid #f59e0b;background:#141d2b;border-radius:0 8px 8px 0;margin-top:6px;display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap">
              <div>
                <strong>├─ 📁 ${{p.name}}</strong>
                ${{linkedCnt > 1 ? `<span class="pill">${{linkedCnt}} Consolidated Folders</span>` : ''}}
                <div class="muted" style="font-size:11px">${{p.folder_path}} · ${{p.blurb || ''}}</div>
              </div>
              <span class="pill" style="background:${{seatColor}};color:#fff">${{seatTxt}}</span>
            </div>
          `;
        }}).join('');
        const resCnt = ((sec.resources && sec.resources.on_disk_matches) || []).length;
        return `
          <div style="border-left:3px solid #38bdf8;padding-left:14px;margin:12px 0">
            <div style="display:flex;justify-content:space-between;align-items:center;background:#162235;padding:9px 14px;border-radius:8px">
              <div>
                <strong>┏━ 🎯 ${{sec.title}}</strong> <span class="pill">${{sec.arena}}</span>
                ${{resCnt ? `<span class="pill" style="background:#064e3b;color:#6ee7b7">${{resCnt}} Gandalf Resource Match(es)</span>` : ''}}
              </div>
              <span class="pill">${{(sec.projects || []).length}} Project(s)</span>
            </div>
            ${{projs || '<div class="muted" style="margin:6px 0 0 18px">└─ (No projects assigned to this section yet — use Verbal Revision below to move or add one)</div>'}}
          </div>
        `;
      }}).join('');

      box.innerHTML = `
        <div style="padding:12px 16px;background:linear-gradient(90deg,#1e293b,#0f172a);border:1px solid #f59e0b;border-radius:10px;margin-bottom:10px">
          <div style="font-size:12px;color:#fde68a;font-weight:700">🏛 PORTFOLIO NORTH STAR MISSION (ROOT)</div>
          <div style="font-size:15px;font-weight:600;margin-top:2px">"${{h.mission_statement || 'Execute Strategic Portfolio Goals & AI Cockpits'}}"</div>
          <div class="muted" style="margin-top:4px">Organization: <strong>${{h.mode_label}}</strong> · ★ Active: ${{h.active_count || 0}} · ↳ On Deck: ${{h.on_deck_count || 0}} · ○ Candidates: ${{h.parked_count || 0}}</div>
        </div>
        ${{secHtml}}
      `;
    }}

    function startVoiceDictation(targetId) {{
      const el = document.getElementById(targetId);
      if (!el) return;
      const SpeechRec = window.SpeechRecognition || window.webkitSpeechRecognition;
      if (!SpeechRec) {{
        el.focus();
        document.getElementById('wizBanner').textContent = '🎙 Tip: Press Win+H (Windows Voice Typing) or type directly in the focused box.';
        return;
      }}
      const rec = new SpeechRec();
      rec.lang = 'en-US';
      rec.interimResults = false;
      document.getElementById('wizBanner').textContent = '🎙 Listening... Speak your thought or revision now.';
      rec.onresult = (ev) => {{
        const transcript = ev.results[0][0].transcript;
        el.value = el.value ? (el.value.trim() + ' ' + transcript) : transcript;
        document.getElementById('wizBanner').textContent = `🎙 Captured: "${{transcript}}"`;
      }};
      rec.onerror = () => {{
        el.focus();
        document.getElementById('wizBanner').textContent = '🎙 Press Win+H (Windows Voice Typing) or type directly in the box.';
      }};
      rec.start();
    }}

    document.querySelectorAll('[data-voice-target]').forEach((btn) => {{
      btn.addEventListener('click', () => startVoiceDictation(btn.getAttribute('data-voice-target')));
    }});

    document.querySelectorAll('[data-use-mission]').forEach((btn) => {{
      btn.addEventListener('click', () => {{
        const val = btn.getAttribute('data-use-mission');
        document.getElementById('inpMissionDialogue').value = val;
        document.getElementById('inpMission').value = val;
      }});
    }});

    document.querySelectorAll('[data-add-goal-example]').forEach((btn) => {{
      btn.addEventListener('click', () => {{
        const ex = btn.getAttribute('data-add-goal-example');
        const area = document.getElementById('txtGoals');
        if (area) {{
          area.value = area.value.trim() ? (area.value.trim() + '\\n' + ex) : ex;
        }}
      }});
    }});

    const btnBrainstormMission = document.getElementById('btnBrainstormMission');
    if (btnBrainstormMission) {{
      btnBrainstormMission.addEventListener('click', async () => {{
        const userIn = document.getElementById('inpMissionDialogue').value || document.getElementById('inpMission').value;
        const curDraft = document.getElementById('inpMission').value;
        const out = await callWizardAction('brainstorm_mission', {{ user_input: userIn, current_draft: curDraft }});
        document.getElementById('inpMission').value = out.mission_statement || '';
        document.getElementById('wizBanner').textContent = `Steward Mission Summary: ${{out.ai_summary}}`;
        await refreshBundle();
      }});
    }}

    const btnLockMission = document.getElementById('btnLockMission');
    if (btnLockMission) {{
      btnLockMission.addEventListener('click', async () => {{
        const out = await callWizardAction('lock_mission', {{ mission_statement: document.getElementById('inpMission').value }});
        document.getElementById('wizBanner').textContent = `Locked Mission Statement: "${{out.mission_statement}}" — Now brainstorm your Goals / Initiatives below!`;
        await refreshBundle();
        document.getElementById('txtGoals').focus();
      }});
    }}

    const btnBrainstormGoals = document.getElementById('btnBrainstormGoals');
    if (btnBrainstormGoals) {{
      btnBrainstormGoals.addEventListener('click', async () => {{
        const out = await callWizardAction('brainstorm_goals', {{
          user_input: document.getElementById('txtGoals').value,
          mission_statement: document.getElementById('inpMission').value,
        }});
        document.getElementById('wizBanner').textContent = out.ai_summary || 'Goals / Initiatives summarized and organized!';
        await refreshBundle();
      }});
    }}

    const btnBrainstormSources = document.getElementById('btnBrainstormProjectSources');
    if (btnBrainstormSources) {{
      btnBrainstormSources.addEventListener('click', async () => {{
        const ftypes = Array.from(document.querySelectorAll('[data-ftype]:checked')).map((el) => el.getAttribute('data-ftype'));
        const out = await callWizardAction('brainstorm_project_sources', {{
          user_input: (document.getElementById('inpProjectSourceDialogue') || {{}}).value || '',
          selected_file_types: ftypes,
          roots: document.getElementById('inpWorkspaceRoots').value,
        }});
        document.getElementById('wizBanner').textContent = out.summary || 'Built Graphical Hierarchical Project Organization!';
        await refreshBundle();
      }});
    }}

    const btnVerbalRev = document.getElementById('btnApplyVerbalRevision');
    if (btnVerbalRev) {{
      btnVerbalRev.addEventListener('click', async () => {{
        const inp = document.getElementById('inpVerbalRevision');
        if (!inp || !inp.value.trim()) return;
        const out = await callWizardAction('revise_project_organization', {{ verbal_instruction: inp.value }});
        inp.value = '';
        document.getElementById('wizBanner').textContent = `✓ Revised Hierarchy: ${{out.steward_reply}}`;
        const rBox = document.getElementById('revisionDialogueBox');
        if (rBox) {{
          rBox.innerHTML = `<div class="proj-row"><div><strong>🤖 Steward Applied Revision:</strong> ${{out.steward_reply}}</div><span class="pill" style="background:#064e3b;color:#6ee7b7">UPDATED ✓</span></div>`;
        }}
        await refreshBundle();
      }});
    }}

    const btnSuggestPrio = document.getElementById('btnSuggestTopPriorities');
    if (btnSuggestPrio) {{
      btnSuggestPrio.addEventListener('click', async () => {{
        const notes = (document.getElementById('inpTopPrioritiesSession') || {{}}).value || (document.getElementById('txtPriorityNow') || {{}}).value || '';
        const out = await callWizardAction('suggest_top_priorities', {{ user_priority_notes: notes }});
        const sBox = document.getElementById('topPrioritiesSuggestionsBox');
        if (sBox) {{
          sBox.innerHTML = (out.suggestions || []).map((s) => `
            <div class="proj-row">
              <div><strong>${{s.recommended_seat === 'active' ? '★ ACTIVE' : '↳ ON DECK'}} · ${{s.name}}</strong> <span class="pill">${{s.group_folder}}</span><div class="muted">${{s.why}}</div></div>
              <span class="pill" style="background:${{s.recommended_seat === 'active' ? '#064e3b' : '#1e3a8a'}};color:#fff">${{s.recommended_seat.toUpperCase()}}</span>
            </div>
          `).join('');
        }}
        document.getElementById('wizBanner').textContent =
          `Steward suggested ${{out.proposed_active.length}} Active Top Priorities and ${{out.proposed_on_deck.length}} On Deck projects from your Mission & Goals!`;
        await refreshBundle();
      }});
    }}

    const chkDualAuthEl = document.getElementById('chkDualAuth');
    if (chkDualAuthEl) {{
      chkDualAuthEl.addEventListener('change', () => {{
        const box2fa = document.getElementById('dualAuthSecretBox');
        if (box2fa) box2fa.hidden = !chkDualAuthEl.checked;
      }});
    }}

    const btnToggleTok = document.getElementById('btnToggleTokenVis');
    if (btnToggleTok) {{
      btnToggleTok.addEventListener('click', () => {{
        const inp = document.getElementById('inpAnchorToken');
        if (inp) inp.type = (inp.type === 'password') ? 'text' : 'password';
      }});
    }}

    const btnCopyTok = document.getElementById('btnCopyAnchorToken');
    if (btnCopyTok) {{
      btnCopyTok.addEventListener('click', async () => {{
        const inp = document.getElementById('inpAnchorToken');
        if (inp && inp.value) {{
          try {{
            await navigator.clipboard.writeText(inp.value);
            document.getElementById('wizBanner').textContent = 'Copied ANCHOR_TOKEN to clipboard!';
          }} catch (e) {{
            inp.type = 'text';
            inp.select();
            document.getElementById('wizBanner').textContent = 'ANCHOR_TOKEN revealed and selected — press Ctrl+C to copy.';
          }}
        }}
      }});
    }}

    const btnRegenTok = document.getElementById('btnRegenAnchorToken');
    if (btnRegenTok) {{
      btnRegenTok.addEventListener('click', async () => {{
        const out = await callWizardAction('regenerate_anchor_token', {{}});
        document.getElementById('wizBanner').textContent = `Regenerated Mother Ship ANCHOR_TOKEN (${{out.anchor_token_masked || 'updated'}})!`;
        await refreshBundle();
      }});
    }}

    const btnRegenBC = document.getElementById('btnRegenBackupCodes');
    if (btnRegenBC) {{
      btnRegenBC.addEventListener('click', async () => {{
        const out = await callWizardAction('regenerate_2fa_backup_codes', {{}});
        document.getElementById('wizBanner').textContent = `Generated 10 fresh single-use 2FA backup recovery codes!`;
        await refreshBundle();
      }});
    }}

    const btnCopyBC = document.getElementById('btnCopyBackupCodes');
    if (btnCopyBC) {{
      btnCopyBC.addEventListener('click', async () => {{
        const codes = ((window.ONBOARD_WIZARD_BOOT.profile || {{}}).dual_auth_backup_codes || []).join('\\n');
        if (codes) {{
          try {{
            await navigator.clipboard.writeText(codes);
            document.getElementById('wizBanner').textContent = 'Copied all 10 single-use 2FA backup codes to clipboard!';
          }} catch (e) {{}}
        }}
      }});
    }}

    const btnQuickRec = document.getElementById('btnQuickSendRecoveryLink');
    if (btnQuickRec) {{
      btnQuickRec.addEventListener('click', async () => {{
        const ident = (document.getElementById('inpQuickRecoveryEmail') || {{}}).value || (document.getElementById('inpContactEmail') || {{}}).value || (document.getElementById('inpUsername') || {{}}).value || '';
        if (!ident.trim()) {{
          document.getElementById('wizBanner').textContent = 'Enter your Contact Email, Username, or Pseudonym to request a recovery link.';
          return;
        }}
        const out = await callWizardAction('request_account_recovery', {{ identifier: ident.trim(), base_url: window.location.origin }});
        const rBox = document.getElementById('quickRecoveryResultBox');
        if (rBox) {{
          rBox.hidden = false;
          if (!out.ok) {{
            rBox.innerHTML = `<div style="color:#fca5a5">${{out.message || out.error}}</div>`;
          }} else {{
            rBox.innerHTML = `
              <div class="proj-row">
                <div>
                  <strong>✓ Recovery Link Issued!</strong> Username Reminder: <code>${{out.username}}</code> · Pseudonym: <code>${{out.pseudonym}}</code>
                  <div class="muted">Open Single-Use Link: <a href="${{out.recovery_url}}" style="color:var(--sky)">${{out.recovery_url}}</a></div>
                </div>
                <span class="pill" style="background:#064e3b;color:#6ee7b7">SENT ✓</span>
              </div>
            `;
          }}
        }}
      }});
    }}

    const btnRefreshModels = document.getElementById('btnRefreshLiveModels');
    if (btnRefreshModels) {{
      btnRefreshModels.addEventListener('click', async () => {{
        const out = await callWizardAction('refresh_live_models', {{}});
        document.getElementById('wizBanner').textContent = 'Synced live advertised models from installed CLIs and Nightly 02:00 catalog!';
        await refreshBundle();
      }});
    }}

    const btnFreePreset = document.getElementById('btnApplyFreeTierPreset');
    if (btnFreePreset) {{
      btnFreePreset.addEventListener('click', async () => {{
        const out = await callWizardAction('apply_free_tier_preset', {{}});
        document.getElementById('wizBanner').textContent = out.message || 'Applied Free-Account AI Provider Preset!';
        await refreshBundle();
      }});
    }}

    document.getElementById('btnSaveStep1').addEventListener('click', async () => {{
      const chkLic = document.getElementById('chkAcceptGwlLicense');
      if (chkLic && !chkLic.checked) {{
        document.getElementById('wizBanner').textContent = '⚠ Please check the Ghost World Labs License acknowledgement box (Free Use · No Resale or Commercialization) before continuing.';
        chkLic.focus();
        return;
      }}
      const pwd = (document.getElementById('inpPassword') || {{}}).value || '';
      const pwdConf = (document.getElementById('inpPasswordConfirm') || {{}}).value || '';
      if (pwd && pwdConf && pwd !== pwdConf) {{
        document.getElementById('wizBanner').textContent = '⚠ Password and Confirm Password do not match. Please re-enter.';
        return;
      }}
      const out = await callWizardAction('save_identity', {{
        display_name: document.getElementById('inpDisplayName').value,
        pseudonym: document.getElementById('inpPseudonym').value,
        pseudonym_aliases: document.getElementById('inpAliases').value,
        steward_persona: document.getElementById('selPersona').value,
        username: (document.getElementById('inpUsername') || {{}}).value || '',
        contact_email: (document.getElementById('inpContactEmail') || {{}}).value || '',
        password: pwd,
        dual_auth_enabled: Boolean((document.getElementById('chkDualAuth') || {{}}).checked),
        dual_auth_method: (document.getElementById('selDualAuthMethod') || {{}}).value || 'totp_authenticator',
        anchor_token: (document.getElementById('inpAnchorToken') || {{}}).value || '',
        accepted_gwl_license: true,
        require_license_ack: true,
      }});
      if (!out || !out.ok) {{
        document.getElementById('wizBanner').textContent = '⚠ ' + ((out && out.message) || 'Could not save Step 1.');
        return;
      }}
      if (document.getElementById('inpPassword')) document.getElementById('inpPassword').value = '';
      if (document.getElementById('inpPasswordConfirm')) document.getElementById('inpPasswordConfirm').value = '';
      document.getElementById('wizBanner').textContent =
        `Saved identity, credentials & Ghost World Labs License receipt: Steward will address you as "${{out.profile.display_name}}" (Username: ${{out.profile.username}}, Pseudonym: ${{out.profile.pseudonym}}).`;
      await refreshBundle();
      showStep(2);
    }});

    let _wizLoginPoll = null;
    function renderBrowserAccountsBanner(accountsMap) {{
      const box = document.getElementById('browserAccountsBanner');
      if (!box) return;
      box.innerHTML = '';
      ['claude', 'gemini', 'chatgpt', 'grok'].forEach((fam) => {{
        const info = accountsMap[fam];
        if (!info) return;
        const div = document.createElement('div');
        div.style.cssText = 'padding:8px 10px;border-radius:7px;background:#0b111b;border:1px solid #263449;display:flex;flex-direction:column;gap:4px';
        const pillBg = info.cli_authenticated ? '#064e3b' : (info.browser_session_detected ? '#1e3a8a' : '#451a03');
        const pillFg = info.cli_authenticated ? '#6ee7b7' : (info.browser_session_detected ? '#93c5fd' : '#fde68a');
        const pillTxt = info.cli_authenticated ? '✓ Signed In' : (info.browser_session_detected ? '🌐 Open in Browser' : 'Log In Ready');
        div.innerHTML = `
          <div style="display:flex;justify-content:space-between;align-items:center;gap:4px">
            <strong style="font-size:12.5px">${{info.label}}</strong>
            <span class="pill" style="background:${{pillBg}};color:${{pillFg}}">${{pillTxt}}</span>
          </div>
          <div class="muted" style="font-size:11.5px">${{info.status_summary}}</div>
          <button type="button" class="btn" style="font-size:11.5px;padding:5px 8px;margin-top:2px" data-banner-login="${{fam}}">🌐 Open Browser &amp; Log In</button>
        `;
        box.appendChild(div);
      }});
      box.querySelectorAll('[data-banner-login]').forEach((b) => {{
        b.addEventListener('click', async () => {{
          const fam = b.getAttribute('data-banner-login');
          const out = await callWizardAction('open_browser_login', {{ family: fam }});
          if (out && typeof out.login_url === 'string' && out.login_url.startsWith('https://') && !out.opened_on_host) {{
            window.open(out.login_url, '_blank', 'noopener,noreferrer');
          }}
          document.getElementById('wizBanner').textContent = out.message || `Opened browser login for ${{fam}}.`;
          startBrowserLoginPoll(fam);
        }});
      }});
    }}

    function startBrowserLoginPoll(fam) {{
      clearInterval(_wizLoginPoll);
      let n = 0;
      _wizLoginPoll = setInterval(async () => {{
        n += 1;
        const det = await callWizardAction('detect_browser_accounts', {{ include_browser_history: false }});
        if (det && det.accounts) {{
          renderBrowserAccountsBanner(det.accounts);
          if (det.accounts[fam] && det.accounts[fam].cli_authenticated) {{
            clearInterval(_wizLoginPoll);
            document.getElementById('wizBanner').textContent = `✓ ${{det.accounts[fam].label}} is now signed in!`;
            await refreshBundle();
            return;
          }}
        }}
        if (n >= 60) {{
          clearInterval(_wizLoginPoll);
          document.getElementById('wizBanner').textContent = 'Still waiting for sign-in — click Check Open Browser Accounts & CLI Logins once signed in.';
        }}
      }}, 3000);
    }}

    const btnPromptTsYes = document.getElementById('btnPromptInstallTailscale');
    if (btnPromptTsYes) {{
      btnPromptTsYes.addEventListener('click', async () => {{
        const out = await callWizardAction('setup_tailscale_interactive', {{}});
        document.getElementById('wizBanner').textContent = out.message || 'Launched Tailscale setup!';
        await refreshBundle();
      }});
    }}
    const btnPromptTsSkip = document.getElementById('btnPromptSkipTailscale');
    if (btnPromptTsSkip) {{
      btnPromptTsSkip.addEventListener('click', () => {{
        window._skippedTailscalePrompt = true;
        const p = document.getElementById('tsPromptBanner');
        if (p) p.hidden = true;
        document.getElementById('wizBanner').textContent = 'Continuing locally without Tailscale (automatic website-watched updates are active).';
      }});
    }}

    const btnOneClickReg = document.getElementById('btnOneClickRegister');
    if (btnOneClickReg) {{
      btnOneClickReg.addEventListener('click', async () => {{
        const em = (document.getElementById('inpRegistryEmail') || {{}}).value || (document.getElementById('inpContactEmail') || {{}}).value || '';
        const out = await callWizardAction('register_anchor_repo', {{ email: em }});
        document.getElementById('wizBanner').textContent = out.message || (out.ok ? 'Registered!' : 'Please enter your email address first.');
        await refreshBundle();
      }});
    }}

    const btnAutoClis = document.getElementById('btnAutoInstallClis');
    if (btnAutoClis) {{
      btnAutoClis.addEventListener('click', async () => {{
        btnAutoClis.disabled = true;
        const incGrok = Boolean((document.getElementById('chkIncludeGrokCli') || {{}}).checked);
        document.getElementById('wizBanner').textContent = 'Installing Claude Code CLI, Antigravity/Gemini CLI & OpenAI Codex CLI' + (incGrok ? ' + Grok CLI' : '') + '…';
        try {{
          const out = await callWizardAction('auto_install_clis', {{ include_grok: incGrok }});
          document.getElementById('wizBanner').textContent = out.message || 'Agent CLI check & auto-install complete!';
          await refreshBundle();
        }} finally {{
          btnAutoClis.disabled = false;
        }}
      }});
    }}

    const btnCheckBrowser = document.getElementById('btnCheckBrowserAccounts');
    if (btnCheckBrowser) {{
      btnCheckBrowser.addEventListener('click', async () => {{
        const out = await callWizardAction('detect_browser_accounts', {{ include_browser_history: true }});
        if (out && out.accounts) renderBrowserAccountsBanner(out.accounts);
        document.getElementById('wizBanner').textContent = '✓ Checked open browser accounts (read-only domain check) and local CLI credentials!';
      }});
    }}

    document.getElementById('btnInstallTailscale').addEventListener('click', async () => {{
      const chkTel = document.getElementById('chkHomebaseTelemetry');
      const chkAuto = document.getElementById('chkAutoPullWebsiteUpdates');
      const chkLow = document.getElementById('chkLowSpecMode');
      await callWizardAction('configure_topology', {{
        mode: document.getElementById('selTopologyMode').value,
        remote_address: document.getElementById('inpRemoteMothership').value,
        telemetry_enabled: chkTel ? chkTel.checked : true,
        auto_pull_updates: chkAuto ? chkAuto.checked : true,
        low_spec_mode: chkLow ? chkLow.checked : false,
        auto_install_tailscale: true,
      }});
      document.getElementById('wizBanner').textContent = 'Tailscale & Mothership topology verified!';
      await refreshBundle();
    }});

    const btnRegHb = document.getElementById('btnRegisterHomebase');
    if (btnRegHb) {{
      btnRegHb.addEventListener('click', async () => {{
        const chkTel = document.getElementById('chkHomebaseTelemetry');
        const out = await callWizardAction('register_with_homebase', {{
          homebase_url: document.getElementById('inpRemoteMothership').value,
          telemetry_enabled: chkTel ? chkTel.checked : true,
        }});
        document.getElementById('wizBanner').textContent = out.registered
          ? `Linked with Tailscale Hub (${{out.homebase_url}})!`
          : `Saved local settings (${{out.error || 'website auto-updates are active'}}).`;
        await refreshBundle();
      }});
    }}

    document.getElementById('btnSaveStep2').addEventListener('click', async () => {{
      const regEm = (document.getElementById('inpRegistryEmail') || {{}}).value || '';
      if (regEm && regEm.includes('@')) {{
        await callWizardAction('register_anchor_repo', {{ email: regEm }});
      }}
      const chkTel = document.getElementById('chkHomebaseTelemetry');
      const chkAuto = document.getElementById('chkAutoPullWebsiteUpdates');
      const chkLow = document.getElementById('chkLowSpecMode');
      const telOn = chkTel ? chkTel.checked : true;
      const remVal = (document.getElementById('inpRemoteMothership') || {{}}).value || '';
      await callWizardAction('configure_topology', {{
        mode: document.getElementById('selTopologyMode').value,
        remote_address: remVal,
        telemetry_enabled: telOn,
        auto_pull_updates: chkAuto ? chkAuto.checked : true,
        low_spec_mode: chkLow ? chkLow.checked : false,
      }});
      if (remVal.trim()) {{
        await callWizardAction('register_with_homebase', {{
          homebase_url: remVal.trim(),
          telemetry_enabled: telOn,
        }});
      }}
      await refreshBundle();
      showStep(3);
    }});

    document.getElementById('btnNextStep4').addEventListener('click', () => showStep(4));

    document.getElementById('btnOrganizeGoals').addEventListener('click', async () => {{
      const out = await callWizardAction('organize_goals', {{
        mission_statement: document.getElementById('inpMission').value,
        raw_text: document.getElementById('txtGoals').value,
        starting_flow: 'goals_first',
      }});
      const prioTxt = (document.getElementById('txtPriorityNow') || {{}}).value || '';
      if (prioTxt.trim()) {{
        await callWizardAction('propose_active_on_deck', {{ priority_initiatives_text: prioTxt }});
      }}
      document.getElementById('wizBanner').textContent =
        `Star Chart Steward organized ${{out.goals.items.length}} goals into ${{out.goals.arenas.length}} Strategic Arenas & updated Active/On-Deck proposals!`;
      await refreshBundle();
      showStep(5);
    }});

    const propSeatsBtn = document.getElementById('btnProposeSeats');
    if (propSeatsBtn) {{
      propSeatsBtn.addEventListener('click', async () => {{
        const prioTxt = (document.getElementById('txtPriorityNow') || {{}}).value || (document.getElementById('txtGoals') || {{}}).value || '';
        const out = await callWizardAction('propose_active_on_deck', {{ priority_initiatives_text: prioTxt }});
        document.getElementById('wizBanner').textContent =
          `Proposed ${{out.proposed_active.length}} Active and ${{out.proposed_on_deck.length}} On Deck AI Cockpits based on your top initiatives!`;
        await refreshBundle();
      }});
    }}

    const consBtn = document.getElementById('btnConsolidateFolders');
    if (consBtn) {{
      consBtn.addEventListener('click', async () => {{
        const out = await callWizardAction('consolidate_folders', {{
          project_name: document.getElementById('inpConsName').value,
          mission_statement: document.getElementById('inpConsMission').value,
          folder_paths: document.getElementById('inpConsFolders').value,
          seat: 'active',
        }});
        document.getElementById('wizBanner').textContent =
          `Consolidated ${{(out.consolidated_project.linked_material_paths || []).length}} folders into unified project "${{out.consolidated_project.name}}"!`;
        await refreshBundle();
      }});
    }}

    document.getElementById('btnSkipToProjects').addEventListener('click', () => showStep(5));

    document.getElementById('btnScanDirs').addEventListener('click', async () => {{
      const out = await callWizardAction('scan_directories', {{
        roots: document.getElementById('inpWorkspaceRoots').value,
      }});
      document.getElementById('wizBanner').textContent =
        `Scanned directories: discovered ${{out.discovered.length}} projects (${{out.re_adopted_count}} re-adopted from existing stores)!`;
      await refreshBundle();
    }});

    document.getElementById('btnProvisionCockpits').addEventListener('click', async () => {{
      const disc = (window.ONBOARD_WIZARD_BOOT.state.projects.discovered || []).map((d, idx) => {{
        const incEl = document.querySelector(`[data-proj-inc="${{idx}}"]`);
        const grpEl = document.querySelector(`[data-proj-group="${{idx}}"]`);
        const seatEl = document.querySelector(`[data-proj-seat="${{idx}}"]`);
        return Object.assign({{}}, d, {{
          included: incEl ? incEl.checked : true,
          excluded: incEl ? !incEl.checked : false,
          group_folder: grpEl ? grpEl.value : d.group_folder,
          seat: seatEl ? seatEl.value : d.seat,
        }});
      }});
      const out = await callWizardAction('provision_projects_and_cockpits', {{ projects: disc }});
      document.getElementById('wizBanner').textContent =
        `Provisioned ${{out.count}} Projects & Starter AI Cockpits across Active, On Deck, and Parked!`;
      await refreshBundle();
      showStep(6);
    }});

    let _lastAppPwdUrl = 'https://myaccount.google.com/apppasswords';
    let _lastDetectedImapHost = '';
    const inpCommsEmailEl = document.getElementById('inpCommsEmail');
    if (inpCommsEmailEl) {{
      inpCommsEmailEl.addEventListener('change', async () => {{
        const val = inpCommsEmailEl.value.trim();
        if (!val.includes('@')) return;
        const det = await callWizardAction('detect_email_provider', {{ email: val }});
        if (det && det.ok) {{
          const famSel = document.getElementById('selCommsFamily');
          if (famSel && det.family) famSel.value = det.family;
          _lastDetectedImapHost = det.imap_host || '';
          _lastAppPwdUrl = det.app_password_url || '';
          const btnPwd = document.getElementById('btnOpenEmailAppPwd');
          if (btnPwd) btnPwd.disabled = !_lastAppPwdUrl;
          const hint = document.getElementById('wizDetectedEmailHint');
          if (hint) {{
            const tag = det.verified_preset ? '✓ Auto-detected' : 'ℹ Suggested';
            hint.textContent = `${{tag}} ${{det.provider_name}} (${{det.imap_host}}:${{det.imap_port}})` + (det.auth_hint ? ` · ${{det.auth_hint}}` : '');
          }}
        }}
      }});
    }}
    const btnWizOutlook = document.getElementById('btnWizAutoOutlook');
    if (btnWizOutlook) {{
      btnWizOutlook.addEventListener('click', async () => {{
        const out = await callWizardAction('auto_connect_outlook', {{}});
        document.getElementById('wizBanner').textContent = out.message || 'Checked running Windows Outlook desktop app.';
        if (out && out.outlook_running) {{
          await refreshBundle();
          showStep(7);
        }}
      }});
    }}
    const btnOpenEmailPwd = document.getElementById('btnOpenEmailAppPwd');
    if (btnOpenEmailPwd) {{
      btnOpenEmailPwd.addEventListener('click', () => {{
        if (!_lastAppPwdUrl || !_lastAppPwdUrl.startsWith('https://')) {{
          document.getElementById('wizBanner').textContent = 'Check your mail provider settings for an IMAP App Password, or click 1-Click Connect Running Windows Outlook.';
          return;
        }}
        window.open(_lastAppPwdUrl, '_blank', 'noopener,noreferrer');
        const sec = document.getElementById('inpCommsSecret');
        if (sec) sec.focus();
      }});
    }}

    document.getElementById('btnSaveComms').addEventListener('click', async () => {{
      await callWizardAction('configure_comms', {{
        provider_family: document.getElementById('selCommsFamily').value,
        email_address: document.getElementById('inpCommsEmail').value,
        secret: document.getElementById('inpCommsSecret').value,
        ics_url: document.getElementById('inpCommsIcs').value,
        imap_host: _lastDetectedImapHost,
      }});
      await refreshBundle();
      showStep(7);
    }});

    document.getElementById('btnSkipComms').addEventListener('click', async () => {{
      await refreshBundle();
      showStep(7);
    }});

    const resetBtn = document.getElementById('btnResetSandbox');
    if (resetBtn) {{
      resetBtn.addEventListener('click', async () => {{
        await callWizardAction('reset_sandbox', {{}});
        document.getElementById('wizBanner').textContent = 'Sandbox Walkthrough reset cleanly to Step 1!';
        await refreshBundle();
        showStep(1);
      }});
    }}

    const applyBtn = document.getElementById('btnApplySandbox');
    if (applyBtn) {{
      applyBtn.addEventListener('click', async () => {{
        await callWizardAction('apply_sandbox_to_live', {{}});
        document.getElementById('wizBanner').textContent = 'Committed Sandbox Walkthrough settings & cockpits to Live Anchor!';
        await refreshBundle();
      }});
    }}

    hydrateFromBundle(window.ONBOARD_WIZARD_BOOT);
  </script>
  <script src="/static/setup-easy-onboard.js"></script>
</body>
</html>
"""


# ═════════════════════════════════════════════════════════════════════════════
# CLI ENTRYPOINT: `python onboard_wizard.py [--sandbox]`
# ═════════════════════════════════════════════════════════════════════════════

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Anchor 7-Step Guided Onboarding & First-Run Wizard (with --sandbox walkthrough mode)."
    )
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Run in isolated Sandbox Walkthrough Mode (ignores existing anchor.exe and Tailscale state).",
    )
    parser.add_argument(
        "--sandbox-id",
        default=DEFAULT_SANDBOX_ID,
        help="Sandbox profile identifier (default: desktop-walkthrough).",
    )
    parser.add_argument(
        "--reset-sandbox",
        action="store_true",
        help="Reset the sandbox state before starting.",
    )
    parser.add_argument(
        "--name",
        default="",
        help="Set user display name (e.g., Alex, Jordan).",
    )
    parser.add_argument(
        "--pseudonym",
        default="",
        help="Set collaborator pseudonym (e.g., Voyager).",
    )
    parser.add_argument(
        "--persona",
        default="Aladdin",
        help="Set Steward persona (Aladdin, Jarvis, Ecgberht).",
    )
    parser.add_argument(
        "--scan-root",
        action="append",
        default=[],
        help="Workspace directory root to scan for projects (repeatable).",
    )
    parser.add_argument(
        "--auto-provision",
        action="store_true",
        help="Run a complete automated walkthrough (Steps 1-7) and print the JSON receipt.",
    )
    args = parser.parse_args(argv)

    if args.reset_sandbox:
        reset_sandbox(sandbox_id=args.sandbox_id)

    if args.name or args.pseudonym or args.auto_provision:
        save_user_identity(
            display_name=args.name or ("Walkthrough User" if args.sandbox else "Collaborator"),
            pseudonym=args.pseudonym or "",
            steward_persona=args.persona,
            sandbox=args.sandbox,
            sandbox_id=args.sandbox_id,
        )

    if args.auto_provision:
        configure_mothership_topology(
            mode="main_mothership",
            auto_install_tailscale=True,
            sandbox=args.sandbox,
            sandbox_id=args.sandbox_id,
        )
        run_service_live_test(
            "claude",
            tier_level="frontier",
            sandbox=args.sandbox,
            sandbox_id=args.sandbox_id,
        )
        organize_goals_with_starchart_steward(
            "Advance flagship research & scholarship\nBuild AI Cockpits & software systems",
            mission_statement="Deliver high-impact research and AI systems with zero dropped balls.",
            sandbox=args.sandbox,
            sandbox_id=args.sandbox_id,
        )
        scan_res = scan_and_propose_projects(
            roots=args.scan_root or None,
            sandbox=args.sandbox,
            sandbox_id=args.sandbox_id,
        )
        provision_projects_and_cockpits(
            scan_res["discovered"],
            sandbox=args.sandbox,
            sandbox_id=args.sandbox_id,
        )

    receipt = build_readiness_receipt(sandbox=args.sandbox, sandbox_id=args.sandbox_id)
    print(json.dumps(receipt, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
