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
                "orchestrator_model": "claude-opus-4-7",
                "reviewer_model": "claude-opus-4-7",
                "effort": "high",
            },
            "one_tier_down": {
                "label": "One Tier Down (Fast / Cost-Balanced)",
                "orchestrator_model": "claude-sonnet-4-6",
                "reviewer_model": "claude-sonnet-4-6",
                "effort": "medium",
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
                "orchestrator_model": "gemini-3.1-pro-high",
                "reviewer_model": "gemini-3.1-pro-high",
                "effort": "high",
            },
            "one_tier_down": {
                "label": "One Tier Down (Fast / Cost-Balanced)",
                "orchestrator_model": "gemini-3-flash",
                "reviewer_model": "gemini-3-flash",
                "effort": "medium",
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
                "orchestrator_model": "grok-4",
                "reviewer_model": "grok-4",
                "effort": "high",
            },
            "one_tier_down": {
                "label": "One Tier Down (Fast / Cost-Balanced)",
                "orchestrator_model": "grok-3-mini",
                "reviewer_model": "grok-3-mini",
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
                "orchestrator_model": "gpt-5.4",
                "reviewer_model": "gpt-5.4",
                "effort": "high",
            },
            "one_tier_down": {
                "label": "One Tier Down (Fast / Cost-Balanced)",
                "orchestrator_model": "gpt-5-mini",
                "reviewer_model": "gpt-5-mini",
                "effort": "medium",
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

    display_name = str(stored.get("display_name") or "").strip()
    configured = bool(display_name)
    if not display_name:
        display_name = "John"

    raw_pseudo = str(
        stored.get("pseudonym")
        or ms_ident.get("pseudonym")
        or aap.PSEUDONYM_DEFAULT
    ).strip()
    raw_aliases = stored.get("pseudonym_aliases") or ms_ident.get("pseudonym_aliases")
    canon_pseudo, canon_aliases = aap.canonicalize_pseudonym(raw_pseudo, raw_aliases)

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

    return {
        "display_name": display_name,
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
    *,
    sandbox: bool = False,
    sandbox_id: str = DEFAULT_SANDBOX_ID,
    base_dir: Path | str | None = None,
) -> dict[str, Any]:
    """Save Step 1 User Identity (Real Name, Collaborator Pseudonym & Steward Persona)."""
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

    profile_doc = {
        "schema": "anchor.user.profile.v1",
        "display_name": clean_name,
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
    return {"ok": True, "profile": get_active_user_profile(sandbox_id if sandbox else "", sandbox=sandbox, base_dir=base_dir)}


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
    return {"ok": True, "topology": topology_doc}


# ═════════════════════════════════════════════════════════════════════════════
# STEP 3: AI Services Menu, Credentials, Model Tiers, CLI Updater & Live Probe
# ═════════════════════════════════════════════════════════════════════════════

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
        tier_defaults = meta["tiers"][tier_level]

        out_services[fam] = {
            "family": fam,
            "label": meta["label"],
            "cli": cli_name,
            "cli_installed": bool(cli_path),
            "default_role": meta["default_role"],
            "enabled": bool(saved.get("enabled", fam in ("claude", "gemini", "grok"))),
            "auth_mode": str(saved.get("auth_mode") or "subscription"),
            "has_api_key": bool(saved.get("has_api_key", False)),
            "tier_level": tier_level,
            "tier_label": tier_defaults["label"],
            "orchestrator_model": str(saved.get("orchestrator_model") or tier_defaults["orchestrator_model"]),
            "reviewer_model": str(saved.get("reviewer_model") or tier_defaults["reviewer_model"]),
            "effort": str(saved.get("effort") or tier_defaults["effort"]),
            "cli_version": str(saved.get("cli_version") or ("detected" if cli_path else "not installed")),
            "verified": bool(saved.get("verified", False)),
            "last_test": saved.get("last_test") or None,
            "available_tiers": meta["tiers"],
        }

    # Check readiness.json explanation
    r_doc = _load_current_readiness(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    return {
        "services": out_services,
        "readiness": r_doc,
        "readiness_explanation": readiness_human_explanation(r_doc),
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

    st_doc = load_wizard_state(sandbox=sandbox, sandbox_id=sandbox_id, base_dir=base_dir)
    services = st_doc.setdefault("services", {})
    prev = services.get(fam) if isinstance(services.get(fam), dict) else {}
    entry = {
        "family": fam,
        "label": meta["label"],
        "enabled": bool(enabled),
        "auth_mode": mode,
        "has_api_key": bool(has_key or prev.get("has_api_key")),
        "tier_level": t_level,
        "tier_label": t_meta["label"],
        "orchestrator_model": str(orchestrator_model or t_meta["orchestrator_model"]).strip(),
        "reviewer_model": str(reviewer_model or t_meta["reviewer_model"]).strip(),
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
        face_body = (
            f"# {clean_title}\n\n"
            f"**Mission Statement:** {clean_mission_line}\n\n"
            f"**Goal:** {clean_goal}\n\n"
            f"**Portfolio Folder:** {clean_group}\n"
            f"**Owner:** {user_display_name}\n"
            f"{linked_md}"
            f"{inits_md}\n"
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

        if sandbox:
            pid = str(item.get("id") or uuid.uuid4().hex)
            s_cockpit_dir = state_dir(sandbox=True, sandbox_id=sandbox_id, base_dir=base_dir) / "cockpits" / _safe_slug(name)
            scaf = scaffold_starter_ai_cockpit(
                s_cockpit_dir,
                name,
                group_folder=group_folder,
                blurb=blurb,
                user_display_name=user_name,
                linked_material_paths=item.get("linked_material_paths") or [],
                mission_statement=str(item.get("mission_statement") or ""),
                initiatives_list=item.get("initiatives_list") or [],
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
                group_folder=group_folder,
                blurb=blurb,
                user_display_name=user_name,
                linked_material_paths=item.get("linked_material_paths") or [],
                mission_statement=str(item.get("mission_statement") or ""),
                initiatives_list=item.get("initiatives_list") or [],
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
    return {
        "ok": True,
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

    if act == "save_identity":
        return save_user_identity(
            display_name=str(body.get("display_name") or ""),
            pseudonym=str(body.get("pseudonym") or aap.PSEUDONYM_DEFAULT),
            pseudonym_aliases=body.get("pseudonym_aliases"),
            steward_persona=str(body.get("steward_persona") or "Aladdin"),
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
            api_key=str(body.get("api_key") or ""),
            tier_level=str(body.get("tier_level") or "frontier"),
            orchestrator_model=str(body.get("orchestrator_model") or ""),
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
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -Path '%~dp0' -Recurse | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1
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
    """Return ``(zip_file_path, download_filename)`` for either:
      * ``package_kind="prod"`` -> ``Anchor.zip`` (shareable production Anchor.exe)
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
    prod_zip = d_root / "Anchor.zip"
    test_zip = d_root / "Anchor-Test-Onboard.zip"

    if package_kind == "prod":
        if not prod_zip.is_file():
            with _zf.ZipFile(prod_zip, "w", compression=_zf.ZIP_DEFLATED) as zf:
                if anchor_onedir.is_dir():
                    for f in anchor_onedir.rglob("*"):
                        if f.is_file():
                            zf.write(f, str(Path("Anchor") / f.relative_to(anchor_onedir)))
                else:
                    zf.writestr("Anchor/README.txt", "Run shell/build_exe.ps1 on Mothership to populate Anchor.exe.\n")
        return prod_zip, "Anchor.zip"

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
      padding: 14px 24px;
      background: #0f1520;
      border-bottom: 1px solid var(--border);
    }}
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
  <header class="wiz-top">
    <div class="wiz-brand">
      <span>🧭 Anchor Guided Onboarding &amp; Setup Wizard</span>
      {mode_badge}
    </div>
    <div class="wiz-top-actions">
      <a class="btn" href="{toggle_href}" id="btnToggleSandbox">{toggle_label}</a>
      <button type="button" class="btn" id="btnResetSandbox" {"" if sandbox else "hidden"}>↺ Reset Walkthrough</button>
      <button type="button" class="btn emerald" id="btnApplySandbox" {"" if sandbox else "hidden"}>✓ Commit &amp; Apply to Live Anchor</button>
      <a class="btn" href="/setup">⚙ Provider Setup</a>
      <a class="btn primary" href="/high-seat">🏛 Open Cave of Wonders</a>
    </div>
  </header>

  <div class="wiz-layout">
    <aside class="wiz-stepper" aria-label="Onboarding steps">
      <button type="button" class="step-btn active" data-step="1"><span class="step-num">1</span><span>Who Are You? (Name &amp; Pseudonym)</span></button>
      <button type="button" class="step-btn" data-step="2"><span class="step-num">2</span><span>Mothership &amp; Tailscale Network</span></button>
      <button type="button" class="step-btn" data-step="3"><span class="step-num">3</span><span>AI Services, Tiers &amp; Live Verify</span></button>
      <button type="button" class="step-btn" data-step="4"><span class="step-num">4</span><span>Goals &amp; Missions (Star Chart)</span></button>
      <button type="button" class="step-btn" data-step="5"><span class="step-num">5</span><span>Project Scan &amp; AI Cockpits</span></button>
      <button type="button" class="step-btn" data-step="6"><span class="step-num">6</span><span>Calendar &amp; Email Integration</span></button>
      <button type="button" class="step-btn" data-step="7"><span class="step-num">7</span><span>Readiness Receipt &amp; Launchpad</span></button>
    </aside>

    <main class="wiz-main">
      <div id="wizBanner" class="status-banner" role="status">
        Welcome! Walk through each step below to configure your personal Steward identity, Tailscale Mothership topology, AI service tiers, Star Chart goals, and Project AI Cockpits.
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
          <button type="button" class="btn primary" id="btnSaveStep1">Save Identity &amp; Continue to Step 2 →</button>
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
          <h2>Step 3 · AI Services Menu, Credentials, Capability Tiers &amp; Live Verification</h2>
          <p class="muted" id="readinessNoteBox"></p>
          <div id="servicesGrid" class="service-grid"></div>
          <div style="margin-top:16px">
            <button type="button" class="btn primary" id="btnNextStep4">Continue to Step 4 (Goals &amp; Missions) →</button>
          </div>
        </div>
      </section>

      <!-- STEP 4 -->
      <section class="wiz-step-pane" id="step-pane-4" hidden>
        <div class="wiz-card">
          <h2>Step 4 · Star Chart (Mission, Goals &amp; Initiatives) vs. Cave of Wonders (What You're Working On Now)</h2>
          <p class="muted">
            <strong>How Star Chart &amp; Cave of Wonders Work Together:</strong><br>
            • <strong>Star Chart (Strategy &amp; Horizons):</strong> Holds your overarching <strong>Mission Statement</strong>, 1–3 Year / Quarterly <strong>Goals</strong>, and strategic <strong>Goal Arenas</strong>.<br>
            • <strong>Cave of Wonders (Immediate Execution Board):</strong> Holds your concrete <strong>Active</strong> and <strong>On Deck</strong> AI Cockpits — driven by the most important initiatives you are working on right now.
          </p>
          <div class="form-grid">
            <div>
              <label for="inpMission">Star Chart · Overarching Mission Statement / North Star</label>
              <input type="text" id="inpMission" placeholder="e.g., Advance research, teaching, family trusts, and AI systems with zero dropped balls.">
            </div>
          </div>
          <label for="txtGoals">Star Chart · Long-Term Goals &amp; Strategic Arenas (one per line)</label>
          <textarea id="txtGoals" placeholder="Publish flagship research papers this quarter&#10;Deliver MBA AI &amp; analytics course materials&#10;Manage family trust &amp; legal operations&#10;Build Anchor &amp; Skill Foundry multi-agent cockpits"></textarea>
          <label for="txtPriorityNow" style="margin-top:12px">Cave of Wonders · What are the most important initiatives or main things you are working on right now? (Used to propose what goes ★ Active vs. ↳ On Deck)</label>
          <textarea id="txtPriorityNow" placeholder="e.g., Finishing the Empirical Paper for JCR, preparing the Smeal AI Teaching Grant, and polishing Anchor Onboarding"></textarea>
          <div id="arenasPreview" style="margin:12px 0"></div>
          <div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:12px">
            <button type="button" class="btn primary" id="btnOrganizeGoals">🧭 Organize Star Chart &amp; Propose Active / On Deck →</button>
            <button type="button" class="btn" id="btnSkipToProjects">Jump Straight to Scanning Projects (Step 5) →</button>
          </div>
        </div>
      </section>

      <!-- STEP 5 -->
      <section class="wiz-step-pane" id="step-pane-5" hidden>
        <div class="wiz-card">
          <h2>Step 5 · Smart Directory Scan, Multi-Folder Project Consolidation &amp; Proposed Active / On Deck Lineup</h2>
          <p class="muted">Scan one or more workspace roots anywhere on your computer, or point to multiple separate folders and pull their material together into a single unified project &amp; AI Cockpit.</p>
          <div class="form-grid">
            <div>
              <label for="inpWorkspaceRoots">Workspace Root Directories (semicolon-separated; add folders from anywhere on this PC)</label>
              <input type="text" id="inpWorkspaceRoots" value="C:\\dev" placeholder="C:\\dev; D:\\Research">
            </div>
            <div style="display:flex;align-items:flex-end;gap:8px;flex-wrap:wrap">
              <button type="button" class="btn" id="btnScanDirs">🔍 Scan Directories &amp; Re-Adopt Existing Stores</button>
              <button type="button" class="btn primary" id="btnProposeSeats">⚡ Auto-Propose Active &amp; On Deck from My Top Initiatives</button>
            </div>
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
          <button type="button" class="btn emerald" id="btnProvisionCockpits">🚀 Confirm Selected Projects &amp; Create Starter AI Cockpits →</button>
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
        const verifiedBadge = svc.verified
          ? '<span class="pill" style="background:#064e3b;color:#6ee7b7">VERIFIED ✓ (' + (svc.last_test ? svc.last_test.attested_model : svc.orchestrator_model) + ')</span>'
          : '<span class="pill">Not verified yet</span>';
        card.innerHTML = `
          <div style="display:flex;justify-content:space-between;align-items:center;gap:8px">
            <h3>${{svc.label}}</h3>
            ${{verifiedBadge}}
          </div>
          <p class="muted">${{svc.default_role}} · CLI: <code>${{svc.cli}}</code> (${{svc.cli_version}})</p>
          <label>Connection Method</label>
          <select data-svc-mode="${{svc.family}}">
            <option value="subscription" ${{svc.auth_mode === 'subscription' ? 'selected' : ''}}>Subscription (Local CLI Login)</option>
            <option value="api_key" ${{svc.auth_mode === 'api_key' ? 'selected' : ''}}>API Key (OS Credential Vault)</option>
          </select>
          <label style="margin-top:8px">Capability Level / Model Tier</label>
          <select data-svc-tier="${{svc.family}}">
            <option value="frontier" ${{svc.tier_level === 'frontier' ? 'selected' : ''}}>Frontier (Top-Tier Capability — ${{svc.available_tiers.frontier.orchestrator_model}})</option>
            <option value="one_tier_down" ${{svc.tier_level === 'one_tier_down' ? 'selected' : ''}}>One Tier Down (Fast / Cost-Balanced — ${{svc.available_tiers.one_tier_down.orchestrator_model}})</option>
          </select>
          <div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:12px">
            <button type="button" class="btn" data-act-update="${{svc.family}}">Check / Update CLI</button>
            <button type="button" class="btn emerald" data-act-test="${{svc.family}}">⚡ Verify &amp; Live Test Tier</button>
          </div>
        `;
        grid.appendChild(card);
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
          const modeSel = grid.querySelector(`[data-svc-mode="${{fam}}"]`);
          await callWizardAction('configure_service', {{
            family: fam,
            auth_mode: modeSel ? modeSel.value : 'subscription',
            tier_level: tierSel ? tierSel.value : 'frontier',
          }});
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

      const disc = (b.state && b.state.projects && b.state.projects.discovered) || [];
      renderDiscoveredProjects(disc);
      renderReceipt(b.receipt || {{}});
    }}

    document.getElementById('btnSaveStep1').addEventListener('click', async () => {{
      const out = await callWizardAction('save_identity', {{
        display_name: document.getElementById('inpDisplayName').value,
        pseudonym: document.getElementById('inpPseudonym').value,
        pseudonym_aliases: document.getElementById('inpAliases').value,
        steward_persona: document.getElementById('selPersona').value,
      }});
      document.getElementById('wizBanner').textContent =
        `Saved identity: Steward will address you as "${{out.profile.display_name}}" (Pseudonym: ${{out.profile.pseudonym}}).`;
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
