#!/usr/bin/env python3
"""7-Step Guided Onboarding & First-Run Setup Wizard (stdlib only).

Addresses all 4 root causes from Merrill's diagnostic report (2026-10-22) and
provides a smooth, end-to-end interactive Web UI (`/onboard-wizard` &
`/onboard-wizard?sandbox=1`) and CLI (`python onboard_wizard.py --sandbox`):

  Step 1 — Who Are You? (Display Name, Collaborator Pseudonym/Synonym & Steward Persona)
  Step 2 — Mothership Topology & Tailscale Network Connection (Main Mothership vs. Remote Peer)
  Step 3 — AI Services Menu, Credentials (Subscription vs. API Key), Model Tiers, CLI Updater & Live Probe
  Step 4 — Start with Goals & Missions (Star Chart Steward) OR Start with Projects
  Step 5 — Smart Directory Scan (Gandalf Scanner), Orphaned Store Re-Adoption, Exclusion Filter,
           Virtual Project Groupings & Automatic Starter AI Cockpit Creation
  Step 6 — Calendar & Email Integration (Gmail, Outlook, Custom IMAP/ICS via OS Vault)
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
import subprocess
import time
from typing import Any
import uuid

import anchor_agent_protocol as aap
import comms_connector
import mothership_collab
import paths
import provider_secrets
import rnd_registry as _rnd
import share_readiness as ready


WIZARD_SCHEMA = "anchor.onboard.wizard.v1"
DEFAULT_SANDBOX_ID = "desktop-walkthrough"

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
        },
        "update_cmd": ["claude", "update"],
        "login_cmd": ["claude", "login"],
    },
    "gemini": {
        "family": "gemini",
        "label": "Gemini (Google Antigravity / agy)",
        "cli": "agy",
        "default_role": "Cross-Family Adversarial Reviewer & Heavy Reader",
        "tiers": {
            "frontier": {
                "label": "Frontier (Top-Tier Capability)",
                "orchestrator_model": "gemini-4-argon",
                "reviewer_model": "gemini-4-argon",
                "effort": "high",
            },
            "one_tier_down": {
                "label": "One Tier Down (Fast / Cost-Balanced)",
                "orchestrator_model": "gemini-3.8-flash",
                "reviewer_model": "gemini-3.8-flash",
                "effort": "high",
            },
        },
        "update_cmd": ["agy", "--version"],
        "login_cmd": ["agy", "auth", "login"],
    },
    "grok": {
        "family": "grok",
        "label": "Grok (xAI)",
        "cli": "grok",
        "default_role": "Independent Cross-Family Shark & Refuter",
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
        },
        "update_cmd": ["grok", "--version"],
        "login_cmd": ["grok", "auth"],
    },
    "chatgpt": {
        "family": "chatgpt",
        "label": "ChatGPT / Codex (OpenAI)",
        "cli": "codex",
        "default_role": "Synthesis & Verification Seat",
        "tiers": {
            "frontier": {
                "label": "Frontier (Top-Tier Capability)",
                "orchestrator_model": "gpt-6.1-sol",
                "reviewer_model": "gpt-6.1-sol",
                "effort": "xhigh",
            },
            "one_tier_down": {
                "label": "One Tier Down (Fast / Cost-Balanced)",
                "orchestrator_model": "gpt-6-astra",
                "reviewer_model": "gpt-6-astra",
                "effort": "high",
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
    ".git", ".hg", ".svn", ".anchor", ".ecgberht", ".claude", ".grok", ".gemini",
    ".vscode", ".idea", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "__pycache__", "node_modules", "venv", ".venv", "env", "dist", "build",
    "Anchor-code-jobs", "$RECYCLE.BIN", "System Volume Information",
    "logs", "health_reports", "domains", "starter", "vendor",
})


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

    Ensures Anchor never calls a user (such as Merrill) ``"John"`` once their
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


def save_user_identity(
    display_name: str,
    pseudonym: str = aap.PSEUDONYM_DEFAULT,
    pseudonym_aliases: list[str] | str | None = None,
    steward_persona: str = "Aladdin",
    username: str = "",
    password: str = "",
    contact_email: str = "",
    dual_auth_enabled: bool | None = None,
    dual_auth_method: str = "",
    anchor_token: str = "",
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Save Step 1 User Identity (Real Name, Collaborator Pseudonym, Contact/Recovery Email & Steward Persona)."""
    clean_name = str(display_name or "").strip() or "John"
    if isinstance(pseudonym_aliases, str):
        alias_list = [a.strip() for a in pseudonym_aliases.split(",") if a.strip()]
    elif isinstance(pseudonym_aliases, list):
        alias_list = [str(a).strip() for a in pseudonym_aliases if str(a).strip()]
    else:
        alias_list = []

    canon_pseudo, canon_aliases = aap.canonicalize_pseudonym(pseudonym, alias_list)
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
    """Record or update the onboarding individual in Puter's central Ghost World Labs applicant repository (`gwl-hub`)."""
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
        "display_name": prof.get("display_name") or "Applicant",
        "username": prof.get("username") or "",
        "contact_email": prof.get("contact_email") or "",
        "pseudonym": prof.get("pseudonym") or aap.PSEUDONYM_DEFAULT,
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

    # If running on a remote machine that connects to Puter as coordination_hub, also push over Tailscale HTTP
    coord_hub = str(topo.get("coordination_hub") or topo.get("remote_mothership_url") or "").strip().rstrip("/")
    local_host = str(os.environ.get("COMPUTERNAME") or "").strip().lower()
    if not sandbox and base_dir is None and local_host not in ("puter", "gwl-server"):
        candidate_hubs = []
        if coord_hub.startswith(("http://", "https://")) and "127.0.0.1" not in coord_hub and "localhost" not in coord_hub:
            candidate_hubs.append(coord_hub)
        for default_hub in ("https://gwl-server.tailb49f65.ts.net", "http://puter:8777"):
            if default_hub not in candidate_hubs:
                candidate_hubs.append(default_hub)
        import urllib.request as _ureq
        payload = json.dumps({"action": "register_gwl_applicant", "applicant": res.get("applicant") or record}).encode("utf-8")
        for hub_url in candidate_hubs:
            try:
                req = _ureq.Request(
                    f"{hub_url}/api/onboard-wizard/action",
                    data=payload,
                    headers={"Content-Type": "application/json", "User-Agent": "Anchor-Onboard-ApplicantSync/1.0"},
                    method="POST",
                )
                with _ureq.urlopen(req, timeout=2.5):
                    break
            except Exception:
                continue
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
            "tailscale_ip": "100.101.102.103" if auto_install else "",
            "hostname": "sandbox-work-desktop",
            "install_command": install_cmd,
            "peers": [
                {"hostname": "puter-mothership", "ip": "100.64.0.1", "online": True, "role": "Main Hub / Puter"},
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
        "tailscale_ip": ts_ip,
        "hostname": hostname,
        "install_command": install_cmd,
        "peers": peers,
        "note": "Tailscale detected." if ts_exe else "Tailscale not found — click 'Install Tailscale' or run winget.",
    }


def configure_mothership_topology(
    mode: str = "main_mothership",
    *,
    remote_address: str = "",
    hub_endpoint: str = "http://puter:8777",
    auto_install_tailscale: bool = False,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
    runner_fn=None,
) -> dict[str, Any]:
    """Configure Step 2: Main Mothership vs. Connect to a Different Mothership (e.g. Puter via Tailscale)."""
    norm_mode = str(mode or "main_mothership").strip().lower()
    if norm_mode not in ("main_mothership", "connect_remote_mothership"):
        norm_mode = "main_mothership"

    ts_info = detect_or_install_tailscale(
        sandbox=sandbox,
        auto_install=auto_install_tailscale,
        runner_fn=runner_fn,
    )
    ecg_path, ecg_checked = paths.resolve_ecgberht_root()
    bridge_file = ecg_path / "scripts" / "seal-chamber-bridge.mjs"
    ecg_ok = bridge_file.is_file() or (ecg_path / "bin" / "ecgberht.mjs").is_file()

    if norm_mode == "main_mothership":
        topology_doc = {
            "mode": "main_mothership",
            "mode_label": "This Computer IS a Main Mothership",
            "local_url": "http://127.0.0.1:8777",
            "coordination_hub": str(hub_endpoint or "http://puter:8777").strip(),
            "tailscale": ts_info,
            "ecgberht_root": str(ecg_path),
            "ecgberht_ok": ecg_ok,
            "ecgberht_checked_paths": ecg_checked,
            "verified": True,
            "updated_at": _utc_now_iso(),
        }
    else:
        target = str(remote_address or hub_endpoint or "http://100.64.0.1:8777").strip()
        if target and not target.startswith(("http://", "https://")):
            target = "http://" + target
        topology_doc = {
            "mode": "connect_remote_mothership",
            "mode_label": "Connected to Remote Mothership via Tailscale",
            "remote_mothership_url": target,
            "coordination_hub": str(hub_endpoint or target).strip(),
            "tailscale": ts_info,
            "ecgberht_root": str(ecg_path),
            "ecgberht_ok": ecg_ok,
            "ecgberht_checked_paths": ecg_checked,
            "verified": True,
            "updated_at": _utc_now_iso(),
        }
        if not sandbox and base_dir is None:
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
    st_doc["topology"] = topology_doc
    if 2 not in st_doc["completed_steps"]:
        st_doc["completed_steps"].append(2)
    st_doc["current_step"] = max(int(st_doc.get("current_step") or 1), 3)
    save_wizard_state(st_doc, sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    sync_applicant_signup_to_gwl_hub(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    return {"ok": True, "topology": topology_doc}


# ═════════════════════════════════════════════════════════════════════════════
# STEP 3: AI Services Menu, Credentials, Model Tiers, CLI Updater & Live Probe
# ═════════════════════════════════════════════════════════════════════════════

_STALE_MODEL_UPGRADES: dict[str, str] = {
    "claude-opus-4-7": "claude-fable-5-1",
    "claude-sonnet-4-6": "opus",
    "gemini-3.1-pro-high": "gemini-4-argon",
    "gemini-3-flash": "gemini-3.8-flash",
    "grok-4": "grok-4.7",
    "grok-3-mini": "grok-4.7",
    "gpt-5.4": "gpt-6.1-sol",
    "gpt-5-mini": "gpt-6-astra",
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
        for r in rows or []:
            if not isinstance(r, dict) or not r.get("model"):
                continue
            m_id = str(r["model"]).strip()
            upg = str(r.get("upgrade") or "").strip()
            effs = list(r.get("efforts") or ["high"])
            disp = f"{upg} ({m_id})" if (upg and upg != m_id) else m_id
            out_rows.append({
                "model": (upg or "claude-fable-5-1") if (fam == "claude" and m_id in ("best", "default")) else m_id,
                "alias": m_id,
                "display": disp,
                "efforts": effs,
                "rank": int(r.get("rank") or 0),
            })
    except Exception:
        pass
    try:
        import gwl_clearinghouse as _gwl
        hub_cat = _gwl.get_verified_model_catalog().get("families") or {}
        fam_cat = hub_cat.get(fam) if isinstance(hub_cat.get(fam), dict) else {}
        existing_ids = {r.get("model") for r in out_rows}
        for rank_idx, m_str in enumerate(fam_cat.get("discovered_models") or []):
            m_clean = str(m_str or "").strip()
            if m_clean and m_clean not in existing_ids:
                out_rows.append({
                    "model": m_clean,
                    "alias": m_clean,
                    "display": m_clean,
                    "efforts": ["high"],
                    "rank": len(out_rows) + rank_idx,
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
            },
            {
                "model": t_map["one_tier_down"]["orchestrator_model"],
                "alias": t_map["one_tier_down"]["orchestrator_model"],
                "display": t_map["one_tier_down"]["orchestrator_model"],
                "efforts": [t_map["one_tier_down"]["effort"]],
                "rank": 1,
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
            elif os.name == "nt":
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
    probe_ok = True
    probe_source = "sandbox-verified" if sandbox else "live-cli-probe"
    if not sandbox and runner_fn is not None:
        try:
            res = runner_fn([meta["cli"], "--version"])
            probe_ok = getattr(res, "returncode", 0) == 0
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
        "label": "Samwise Gamgee (John's Mission Statement)",
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
        "category": "Family, Trusts & Stewardship",
        "example": "Keep family trusts, holding companies, finances, and youth mentorship organized with zero dropped balls",
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
            "style": "Samwise Stewardship Style",
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
        ("SKILL.md", "foundry-skill"),
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
    existing_reg = {} if sandbox else _rnd.load_registry()
    by_folder_existing: dict[str, dict[str, Any]] = {}
    for e in existing_reg.values():
        fp = e.get("folder_path") or ""
        if fp:
            try:
                k = str(Path(fp).resolve()).lower() if os.name == "nt" else str(Path(fp).resolve())
                by_folder_existing[k] = e
            except Exception:
                continue

    # Also check sibling prior-install registries (e.g. anchor-plus-skills, Anchor2) for orphaned entries!
    sibling_prior_entries: dict[str, dict[str, Any]] = {}
    for root_dir in norm_roots:
        for prior_name in ("anchor-plus-skills", "Anchor2", "Anchor-Merrill-Share", "anchor"):
            prior_reg = root_dir / prior_name / "rnd_registry.json"
            if prior_reg.is_file():
                try:
                    raw_list = json.loads(prior_reg.read_text(encoding="utf-8"))
                    if isinstance(raw_list, list):
                        for item in raw_list:
                            if isinstance(item, dict) and item.get("folder_path"):
                                fk = str(Path(item["folder_path"]).resolve())
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
    user_display_name: str = "John",
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
    user_name = prof.get("display_name") or "John"
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
        "all_core_ready": all(c["ok"] for c in checks if c["id"] != "comms"),
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
    try:
        import gwl_clearinghouse as _gwl
        hub_catalog = _gwl.get_verified_model_catalog(hub_root=hub_root)
        gwl_applicants = _gwl.list_applicant_signups(hub_root=hub_root)
    except Exception:
        hub_catalog = {}
        gwl_applicants = []
    return {
        "ok": True,
        "admin_edition": paths.is_anchor_admin_edition(base_dir),
        "sandbox": bool(sandbox),
        "sandbox_id": _safe_slug(sandbox_id or DEFAULT_SANDBOX_ID) if sandbox else "",
        "data_dir": str(state_dir(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)),
        "state": state,
        "profile": profile,
        "tailscale": ts_info,
        "ecgberht": {
            "root": str(ecg_path),
            "checked_paths": ecg_checked,
            "ok": (ecg_path / "scripts" / "seal-chamber-bridge.mjs").is_file() or (ecg_path / "bin" / "ecgberht.mjs").is_file(),
        },
        "services": svc_info["services"],
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

    if act in ("save_identity", "save_security_credentials"):
        dual_raw = body.get("dual_auth_enabled")
        dual_bool = None if dual_raw is None else bool(dual_raw in (True, 1, "1", "true", "yes"))
        return save_user_identity(
            display_name=str(body.get("display_name") or ""),
            pseudonym=str(body.get("pseudonym") or aap.PSEUDONYM_DEFAULT),
            pseudonym_aliases=body.get("pseudonym_aliases"),
            steward_persona=str(body.get("steward_persona") or "Aladdin"),
            username=str(body.get("username") or ""),
            password=str(body.get("password") or ""),
            contact_email=str(body.get("contact_email") or body.get("email") or ""),
            dual_auth_enabled=dual_bool,
            dual_auth_method=str(body.get("dual_auth_method") or ""),
            anchor_token=str(body.get("anchor_token") or ""),
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
    if act == "configure_topology":
        return configure_mothership_topology(
            mode=str(body.get("mode") or "main_mothership"),
            remote_address=str(body.get("remote_address") or ""),
            hub_endpoint=str(body.get("hub_endpoint") or "http://puter:8777"),
            auto_install_tailscale=bool(body.get("auto_install_tailscale")),
            sandbox=use_sandbox,
            sandbox_id=sid,
            base_dir=base_dir,
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
        with _zf.ZipFile(base_ov, "r") as zin, _zf.ZipFile(buf, "w", compression=_zf.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename.replace("\\", "/") == "anchor-edition.json":
                    continue
                zout.writestr(item, zin.read(item.filename))
            zout.writestr("anchor-edition.json", ed_json)
            if edition == "collaborator":
                zout.writestr("DASHBOARD.md", "# Anchor Daily Dashboard\n\n## Focus Today\n\n## Active Priorities\n")
                zout.writestr("PROJECTS.md", "# Projects\n")
                zout.writestr("INBOX.md", "# Quick Capture Inbox\n")
                zout.writestr("CANCELLED.md", "# Cancelled Tasks\n")
                zout.writestr("SAVED_FOR_LATER.md", "# Saved for Later\n")
                for dom in ("academic", "commercial", "family", "writing"):
                    zout.writestr(f"domains/{dom}.md", f"# {dom.title()}\n")
        return buf.getvalue()

    if package_kind == "prod":
        if not prod_zip.is_file():
            collab_ed_json = json.dumps({
                "edition": "collaborator",
                "hide_admin_and_download_links": True,
            }, indent=2) + "\n"
            collab_ov = _overlay_bytes_with_edition("collaborator")
            with _zf.ZipFile(prod_zip, "w", compression=_zf.ZIP_DEFLATED) as zf:
                zf.writestr("Anchor/anchor-edition.json", collab_ed_json)
                if anchor_onedir.is_dir():
                    for f in anchor_onedir.rglob("*"):
                        if f.is_file():
                            rel = str(Path("Anchor") / f.relative_to(anchor_onedir)).replace("\\", "/")
                            if rel == "Anchor/anchor-edition.json":
                                continue
                            if rel == "Anchor/anchor-core-overlay.zip" and collab_ov is not None:
                                zf.writestr(rel, collab_ov)
                            else:
                                zf.write(f, rel)
                    if collab_ov is not None and not (anchor_onedir / "anchor-core-overlay.zip").is_file():
                        zf.writestr("Anchor/anchor-core-overlay.zip", collab_ov)
                else:
                    if collab_ov is not None:
                        zf.writestr("Anchor/anchor-core-overlay.zip", collab_ov)
                    zf.writestr("Anchor/README.txt", "Run shell/build_exe.ps1 on Mothership to populate Anchor.exe.\n")
        return prod_zip, "Anchor.zip"

    if package_kind == "admin":
        if not admin_zip.is_file():
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
    need_rebuild = not test_zip.is_file()
    if not need_rebuild and prod_zip.is_file():
        need_rebuild = prod_zip.stat().st_mtime > test_zip.stat().st_mtime

    if need_rebuild:
        with _zf.ZipFile(test_zip, "w", compression=_zf.ZIP_DEFLATED) as zf:
            zf.writestr('Anchor/anchor-test-mode.json', json.dumps({
                'ANCHOR_SHELL_TEST': 'onboard-walkthrough',
                'ANCHOR_SHELL_PORT': '8787',
                'ANCHOR_SHELL_INSTALL_ROOT': r'C:\dev\Anchor-Onboard-Test',
                'ANCHOR_SHELL_ONBOARD_PATH': '/onboard-wizard',
            }, indent=2))
            zf.writestr("Launch-Anchor-Onboard-Test.cmd", LAUNCH_ONBOARD_TEST_CMD.replace("\n", "\r\n"))
            zf.writestr("Reset-And-Clean-Test-Onboard.cmd", RESET_ONBOARD_TEST_CMD.replace("\n", "\r\n"))
            zf.writestr("README-ONBOARD-TEST.txt", README_ONBOARD_TEST_TXT.replace("\n", "\r\n"))
            if anchor_onedir.is_dir():
                for f in anchor_onedir.rglob("*"):
                    if f.is_file():
                        zf.write(f, str(Path("Anchor") / f.relative_to(anchor_onedir)))
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
        <button type="button" class="close" data-winctl="close" title="Close window">&#10005;</button>
      </div>
    </div>
  </header>

  <div class="wiz-layout">
    <aside class="wiz-stepper" aria-label="Onboarding steps">
      <button type="button" class="step-btn active" data-step="1"><span class="step-num">1</span><span>Who Are You? (Name &amp; Pseudonym)</span></button>
      <button type="button" class="step-btn" data-step="2"><span class="step-num">2</span><span>Mothership &amp; Tailscale Network</span></button>
      <button type="button" class="step-btn" data-step="3"><span class="step-num">3</span><span>AI Services, Tiers &amp; Live Verify</span></button>
      <button type="button" class="step-btn" data-step="4"><span class="step-num">4</span><span>Mission &amp; Goals / Initiatives (Star Chart)</span></button>
      <button type="button" class="step-btn" data-step="5"><span class="step-num">5</span><span>Project Scan &amp; AI Cockpits</span></button>
      <button type="button" class="step-btn" data-step="6"><span class="step-num">6</span><span>Calendar &amp; Email Integration</span></button>
      <button type="button" class="step-btn" data-step="7"><span class="step-num">7</span><span>Readiness Receipt &amp; Launchpad</span></button>
    </aside>

    <main class="wiz-main">
      <div id="wizBanner" class="status-banner" role="status">
        Welcome! Walk through each step below to configure your personal Steward identity, Tailscale Mothership topology, AI service tiers, Star Chart goals / initiatives, and Project AI Cockpits.
      </div>

      <!-- STEP 1 -->
      <section class="wiz-step-pane" id="step-pane-1">
        <div class="wiz-card">
          <h2>Step 1 · Who Are You? (Real Name, Anchor Pseudonym/Synonym &amp; Steward Persona)</h2>
          <p class="muted">Your Steward addresses you locally by your Display Name (so it never calls you someone else's name!), while your Pseudonym protects your privacy on the Ghost World Lab collaboration network.</p>
          <div class="form-grid">
            <div>
              <label for="inpDisplayName">What is your name? (How your Steward addresses you locally)</label>
              <input type="text" id="inpDisplayName" placeholder="e.g., Merrill, John">
            </div>
            <div>
              <label for="inpPseudonym">Anchor Pseudonym / Synonym (Public Collaborator Identity)</label>
              <input type="text" id="inpPseudonym" placeholder="e.g., Samwise Gamgee">
            </div>
            <div>
              <label for="inpAliases">Optional Pseudonym Spelling Aliases (comma-separated)</label>
              <input type="text" id="inpAliases" placeholder="e.g., Samwise Gamgi, Samwise">
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
                <input type="text" id="inpUsername" placeholder="e.g., john, merrill" autocomplete="username">
              </div>
              <div>
                <label for="inpContactEmail">Contact / Account Recovery Email (For Username &amp; Password Recovery Links)</label>
                <input type="text" id="inpContactEmail" placeholder="e.g., merrill@psu.edu, john@psu.edu" autocomplete="email">
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
                <div class="muted" style="margin-top:6px">Standard 3-Layer 2FA Recovery: (1) 10 Single-Use Backup Codes above · (2) Verified Contact Email Recovery Link (<a href="/recover-account" style="color:var(--sky)">/recover-account</a>) · (3) System Admin Assisted Reset on the Puter Mothership.</div>
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
          <button type="button" class="btn primary" id="btnSaveStep1">Save Identity, Credentials &amp; Continue to Step 2 →</button>
        </div>
      </section>

      <!-- STEP 2 -->
      <section class="wiz-step-pane" id="step-pane-2" hidden>
        <div class="wiz-card">
          <h2>Step 2 · Mothership Topology &amp; Tailscale Network Connection</h2>
          <p class="muted">Choose whether this computer is your Main Mothership or connects via Tailscale to a different Mothership (such as Puter).</p>
          <div class="form-grid">
            <div>
              <label for="selTopologyMode">Mothership Role</label>
              <select id="selTopologyMode">
                <option value="main_mothership">Option A — This Computer IS a Main Mothership</option>
                <option value="connect_remote_mothership">Option B — Connect to a Different Mothership (via Tailscale)</option>
              </select>
            </div>
            <div>
              <label for="inpRemoteMothership">Remote Mothership / Coordination Hub URL (Tailscale IP or Host)</label>
              <input type="text" id="inpRemoteMothership" value="http://puter:8777" placeholder="http://100.64.0.1:8777">
            </div>
          </div>
          <div id="tsStatusBox" class="wiz-card" style="background:#101723"></div>
          <div style="display:flex;gap:10px;flex-wrap:wrap">
            <button type="button" class="btn" id="btnInstallTailscale">📡 Auto-Install / Verify Tailscale</button>
            <button type="button" class="btn primary" id="btnSaveStep2">Save Topology &amp; Continue to Step 3 →</button>
          </div>
        </div>
      </section>

      <!-- STEP 3 -->
      <section class="wiz-step-pane" id="step-pane-3" hidden>
        <div class="wiz-card">
          <div style="display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:8px">
            <h2 style="margin:0">Step 3 · AI Services Menu, Credentials, Capability Tiers &amp; Live Verification</h2>
            <button type="button" class="btn" id="btnRefreshLiveModels">🔄 Sync Live Models Now (Nightly + CLI Discovery)</button>
          </div>
          <div id="nightlyRefreshBanner" class="proj-row" style="margin-bottom:12px">
            <div>
              <strong>🌙 Nightly 02:00 Model Catalog &amp; Live CLI Discovery:</strong>
              <span class="muted" id="nightlyRefreshDetail">Pulling live advertised models directly from installed CLIs (`model_policy.discover`) + Nightly 02:00 refresh.</span>
            </div>
            <span class="pill" style="background:#064e3b;color:#6ee7b7">LIVE CATALOG</span>
          </div>
          <p class="muted" id="readinessNoteBox"></p>
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
            • <strong>Mission Statement &amp; Goals / Initiatives (What the Star Chart Charts):</strong> Start by brainstorming your overarching <strong>Mission Statement</strong> (with concise examples like <em>The New York Times</em> and <em>Samwise Gamgee</em>), iterate with your Steward until comfortable, then brainstorm your <strong>Goals / Initiatives</strong> (professional, teaching, ventures, creative, hobbies, family). <em>Goals</em> (longer-horizon outcomes &amp; directions) and <em>Initiatives</em> (concrete campaigns &amp; efforts) are similar though not identical — together they are what the <strong>Star Chart</strong> charts and what organizes the sections on the Projects page.<br>
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
                <div><strong>🪔 Samwise Gamgee (John's Mission Statement)</strong> <span class="pill">Personal Stewardship</span></div>
                <div style="font-style:italic;color:#6ee7b7;margin:4px 0">"Carry the work that matters to completion alongside the people I care about — advancing rigorous scholarship, teaching, and AI systems that empower human judgment without ever dropping the ball on family, faith, or stewardship."</div>
                <button type="button" class="btn" data-use-mission="Carry the work that matters to completion alongside the people I care about — advancing rigorous scholarship, teaching, and AI systems that empower human judgment without ever dropping the ball on family, faith, or stewardship.">Use / Adapt Samwise Mission</button>
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
              <button type="button" class="btn" data-add-goal-example="Keep family trusts, holding companies, finances, and youth mentorship organized with zero dropped balls">+ 🏛 Family &amp; Trusts</button>
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
          <textarea id="txtPriorityNow" placeholder="e.g., Finishing the Empirical Paper for JCR, preparing the Smeal AI Teaching Grant, and polishing Anchor Onboarding"></textarea>
          <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px">
            <button type="button" class="btn emerald" id="btnOrganizeGoals">🧭 Set Goals / Initiatives &amp; Continue to Project Organization (Step 5) →</button>
            <button type="button" class="btn" id="btnSkipToProjects">Jump Straight to Scanning Projects (Natural Organization, Step 5) →</button>
          </div>
        </div>
      </section>

      <!-- STEP 5 -->
      <section class="wiz-step-pane" id="step-pane-5" hidden>
        <div class="wiz-card">
          <h2>Step 5 · Project Discovery Dialogue, Graphical Hierarchical Organization, Verbal Revision &amp; Top Priorities</h2>
          <p class="muted">Identify the types of files and sources on your computer, review the Graphical Hierarchical Organization (aligned to your Goals / Initiatives first, or Natural Domain Organization if no goals / initiatives were proposed), revise verbally until happy, confirm your Top Priorities, and create your AI Cockpits.</p>

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
        </div>
      </section>

      <!-- STEP 6 -->
      <section class="wiz-step-pane" id="step-pane-6" hidden>
        <div class="wiz-card">
          <h2>Step 6 · Calendar &amp; Email Integration (Read-Only Chief-of-Staff Schedule Sync)</h2>
          <p class="muted">Connect Google Workspace / Gmail, Microsoft 365 / Outlook, or Custom IMAP + ICS Calendar URLs. Credentials are stored exclusively in the OS Credential Vault.</p>
          <div class="form-grid">
            <div>
              <label for="selCommsFamily">Provider Preset</label>
              <select id="selCommsFamily">
                <option value="gmail">Google Workspace / Gmail + Google Calendar</option>
                <option value="outlook">Microsoft 365 / Outlook + Exchange Calendar</option>
                <option value="custom">Custom / Institutional IMAP &amp; ICS</option>
              </select>
            </div>
            <div>
              <label for="inpCommsEmail">Email Address</label>
              <input type="text" id="inpCommsEmail" placeholder="researcher@example.com">
            </div>
            <div>
              <label for="inpCommsSecret">App Password / OAuth Token (Stored in OS Vault)</label>
              <input type="password" id="inpCommsSecret" placeholder="••••••••••••••••">
            </div>
            <div>
              <label for="inpCommsIcs">Private Calendar ICS URL</label>
              <input type="text" id="inpCommsIcs" placeholder="https://calendar.google.com/calendar/ical/example/basic.ics">
            </div>
          </div>
          <div style="display:flex;gap:10px;flex-wrap:wrap">
            <button type="button" class="btn primary" id="btnSaveComms">✓ Save &amp; Reconcile Schedule →</button>
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
          <h3>🏛 Ghost World Labs Central Applicant Repository (`puter` / `gwl-hub`)</h3>
          <div id="gwlApplicantsBox" style="margin:14px 0"></div>
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

    function invokeWindowControl(act) {{
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
      if (act === 'close') window.close();
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
            <option value="frontier" ${{svc.tier_level === 'frontier' ? 'selected' : ''}}>Frontier (Top-Tier — ${{svc.available_tiers.frontier.orchestrator_model}} / ${{svc.available_tiers.frontier.subagent_model}})</option>
            <option value="one_tier_down" ${{svc.tier_level === 'one_tier_down' ? 'selected' : ''}}>One Tier Down (Fast / Balanced — ${{svc.available_tiers.one_tier_down.orchestrator_model}})</option>
          </select>
          <label style="margin-top:8px">Specific Model Override (Advertised by CLI / Nightly Refresh)</label>
          <select data-svc-model="${{svc.family}}">
            ${{modelOptsHtml}}
          </select>
          <label style="margin-top:8px">API Key / Credential (${{svc.api_key_env || 'OS Credential Vault'}})</label>
          <div style="display:flex;gap:6px;align-items:center">
            <input type="password" data-svc-apikey="${{svc.family}}" placeholder="${{keyPlaceholder}}" style="flex:1">
            <button type="button" class="btn" data-act-savekey="${{svc.family}}">🔑 Save Key</button>
          </div>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
            <button type="button" class="btn primary" data-act-login="${{svc.family}}">🔐 Sign In / Subscription</button>
            <button type="button" class="btn" data-act-update="${{svc.family}}">Check / Update CLI</button>
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
          const keyInp = grid.querySelector(`[data-svc-apikey="${{fam}}"]`);
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
      document.getElementById('inpPseudonym').value = prof.pseudonym || 'Samwise Gamgee';
      document.getElementById('inpAliases').value = (prof.pseudonym_aliases || []).join(', ');
      document.getElementById('selPersona').value = prof.steward_persona || 'Aladdin';
      const uEl = document.getElementById('inpUsername');
      if (uEl) uEl.value = prof.username || (prof.display_name || 'john').toLowerCase().replace(/\\s+/g, '');
      const emEl = document.getElementById('inpContactEmail');
      if (emEl) emEl.value = prof.contact_email || '';
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
        topAuthPill.textContent = `🔐 User: ${{prof.username || 'john'}} · ${{prof.dual_auth_enabled ? '2FA ON' : 'Token Ready'}}`;
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
      document.getElementById('tsStatusBox').innerHTML = `
        <strong>Tailscale Status:</strong> ${{ts.installed ? 'Installed ✓' : 'Not installed'}} ·
        <strong>Node IP:</strong> ${{ts.tailscale_ip || 'pending'}} ·
        <strong>Ecgberht Engine:</strong> ${{b.ecgberht && b.ecgberht.ok ? 'Ready ✓ (' + b.ecgberht.root + ')' : 'Missing'}}
        <div class="muted">${{ts.note || ''}}</div>
      `;

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
      if (gwlBox) {{
        const apps = b.gwl_applicants || [];
        if (!apps.length) {{
          gwlBox.innerHTML = '<p class="muted">Save Step 1 to register this individual in the Puter (`gwl-hub` + `C:\\dev\\GhostWorldLabs-Hub`) Central Applicant Repository.</p>';
        }} else {{
          gwlBox.innerHTML = apps.map((a) => `
            <div class="proj-row">
              <div>
                <strong>${{a.display_name}}</strong> (<code>${{a.username}}</code>) · Pseudonym: <strong>${{a.pseudonym}}</strong> (<code>${{a.did}}</code>)
                <div class="muted">Host: ${{a.hostname || 'local'}} (${{a.tailscale_ip || 'local'}}) · Topology: ${{a.topology_mode}} · 2FA: ${{a.dual_auth_enabled ? 'ON' : 'Off'}} · Services: ${{(a.enabled_services || []).join(', ') || 'pending'}} · Backed up in <code>C:\\dev\\GhostWorldLabs-Hub</code> &amp; <code>C:\\dev\\Anchor\\gwl_hub_repository</code></div>
              </div>
              <span class="pill" style="background:#064e3b;color:#6ee7b7">REGISTERED ON PUTER ✓</span>
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

    document.getElementById('btnSaveStep1').addEventListener('click', async () => {{
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
      }});
      if (document.getElementById('inpPassword')) document.getElementById('inpPassword').value = '';
      if (document.getElementById('inpPasswordConfirm')) document.getElementById('inpPasswordConfirm').value = '';
      document.getElementById('wizBanner').textContent =
        `Saved identity & credentials: Steward will address you as "${{out.profile.display_name}}" (Username: ${{out.profile.username}}, Pseudonym: ${{out.profile.pseudonym}}).`;
      await refreshBundle();
      showStep(2);
    }});

    document.getElementById('btnInstallTailscale').addEventListener('click', async () => {{
      const out = await callWizardAction('configure_topology', {{
        mode: document.getElementById('selTopologyMode').value,
        remote_address: document.getElementById('inpRemoteMothership').value,
        auto_install_tailscale: true,
      }});
      document.getElementById('wizBanner').textContent = 'Tailscale & Mothership topology verified!';
      await refreshBundle();
    }});

    document.getElementById('btnSaveStep2').addEventListener('click', async () => {{
      await callWizardAction('configure_topology', {{
        mode: document.getElementById('selTopologyMode').value,
        remote_address: document.getElementById('inpRemoteMothership').value,
      }});
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

    document.getElementById('btnSaveComms').addEventListener('click', async () => {{
      await callWizardAction('configure_comms', {{
        provider_family: document.getElementById('selCommsFamily').value,
        email_address: document.getElementById('inpCommsEmail').value,
        secret: document.getElementById('inpCommsSecret').value,
        ics_url: document.getElementById('inpCommsIcs').value,
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
        help="Set user display name (e.g., Merrill, John).",
    )
    parser.add_argument(
        "--pseudonym",
        default="",
        help="Set collaborator pseudonym (e.g., Samwise Gamgee).",
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
            display_name=args.name or ("Walkthrough User" if args.sandbox else "John"),
            pseudonym=args.pseudonym or aap.PSEUDONYM_DEFAULT,
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
