"""Subscription-CLI model capabilities; no dated model IDs or API-key calls.

The durable choice is latest-supported / highest-supported. Exact model IDs
belong only to short-lived capability records and per-launch receipts.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time

POLICY_VERSION = 1
DEFAULT_POLICY = {"mode": "latest_supported", "effort": "highest_supported"}
FAMILIES = frozenset({"chatgpt", "claude", "grok", "gemini"})
EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
CAPABILITY_TTL_SECONDS = 300
_LOCK = threading.RLock()
_MEMORY = {}


class PolicyUnavailable(RuntimeError):
    def __init__(self, family, reason, *, code="capability_unavailable"):
        self.family, self.code = family, code
        super().__init__(f"{family}: {reason}")


def validate_policy(value):
    if not isinstance(value, dict) or value != DEFAULT_POLICY:
        raise ValueError("model_policy must select latest_supported / highest_supported")
    return dict(DEFAULT_POLICY)


def highest_effort(levels):
    """Reject unknown semantics instead of silently choosing a lower effort."""
    values = []
    if not isinstance(levels, list):
        raise ValueError("No supported, understood reasoning-effort ordering")
    for level in levels:
        if not isinstance(level, (str, dict)):
            raise ValueError("Invalid reasoning-effort metadata")
        value = level if isinstance(level, str) else (
            level.get("effort") or level.get("reasoningEffort")
            or level.get("value") or level.get("id"))
        if value:
            values.append(str(value).lower())
    if not values or any(value not in EFFORT_ORDER for value in values):
        raise ValueError("No supported, understood reasoning-effort ordering")
    return max(values, key=EFFORT_ORDER.index)


def normalize_catalog(family, raw):
    """Keep capability fields only; never persist prompts, headers or secrets."""
    rows = []
    if not isinstance(raw, dict):
        raise PolicyUnavailable(family, "invalid capability catalog")
    def hidden(entry):
        return (entry.get("hidden") is True or entry.get("isHidden") is True
                or entry.get("selectable") is False
                or entry.get("visibility") in ("hide", "hidden", "none"))
    def row(model, levels, rank, upgrade, evidence):
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model):
            raise PolicyUnavailable(family, "catalog model identity has unsupported characters")
        if type(rank) not in (int, float) or not math.isfinite(rank):
            raise PolicyUnavailable(family, "invalid catalog priority")
        try:
            highest_effort(levels)
        except ValueError as exc:
            raise PolicyUnavailable(family, str(exc), code="unsupported_effort") from exc
        rows.append({"model": model, "efforts": levels, "rank": rank,
                     "upgrade": upgrade, "evidence": evidence})
    if family == "chatgpt":
        entries = raw.get("models", raw.get("data", []))
        if not isinstance(entries, list):
            raise PolicyUnavailable(family, "invalid capability catalog")
        explicit_priority = bool(entries) and all(isinstance(e, dict) and type(e.get("priority")) in (int, float) for e in entries)
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise PolicyUnavailable(family, "invalid model metadata")
            model = entry.get("slug") or entry.get("model") or entry.get("id")
            if hidden(entry):
                continue
            levels = entry.get("supported_reasoning_levels", entry.get("supportedReasoningEfforts", []))
            row(model, levels, entry["priority"] if explicit_priority else index,
                entry.get("upgrade"), "provider_priority" if explicit_priority else "provider_catalog_order")
    elif family == "grok":
        entries = raw.get("models", {})
        if isinstance(entries, dict):
            entries = list(entries.values())
        if not isinstance(entries, list):
            raise PolicyUnavailable(family, "invalid capability catalog")
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise PolicyUnavailable(family, "invalid model metadata")
            info = entry.get("info", entry)
            if not isinstance(info, dict):
                raise PolicyUnavailable(family, "invalid model metadata")
            model = info.get("model") or info.get("id")
            if hidden(info):
                continue
            row(model, info.get("reasoning_efforts", []), index, None, "provider_catalog_order")
    elif family == "claude":
        # `best` is the provider's moving frontier alias, not a product-name pin.
        rows.append({"model": "best", "efforts": raw.get("efforts", []), "rank": 0,
                     "upgrade": None, "evidence": "provider_moving_alias"})
    else:
        raise PolicyUnavailable(family, "the installed transport does not expose verified model capabilities")
    if not rows:
        raise PolicyUnavailable(family, "no visible subscription models were advertised")
    return rows


def select_model(family, catalog):
    if family not in FAMILIES:
        raise PolicyUnavailable(str(family), "unknown model family")
    rows = sorted(catalog, key=lambda item: item["rank"])
    if not rows:
        raise PolicyUnavailable(family, "no available model")
    chosen = rows[0]
    initial_model = chosen["model"]
    initial_evidence = chosen["evidence"]
    by_name = {row["model"]: row for row in rows}
    visited = set()
    while chosen.get("upgrade"):
        target = chosen["upgrade"]
        if isinstance(target, dict):
            target = target.get("model") or target.get("id")
        if target in visited:
            raise PolicyUnavailable(family, "cyclic catalog upgrade metadata")
        visited.add(chosen["model"])
        if target not in by_name:
            raise PolicyUnavailable(family, "recommended model upgrade is unavailable")
        chosen = by_name[target]
    try:
        effort = highest_effort(chosen["efforts"])
    except ValueError as error:
        raise PolicyUnavailable(family, str(error), code="unsupported_effort") from error
    result = {"policy_version": POLICY_VERSION, "requested_policy": dict(DEFAULT_POLICY),
              "family": family, "model": chosen["model"], "effort": effort,
              "selection_evidence": initial_evidence + ("+provider_upgrade" if initial_model != chosen["model"] else ""), "model_attested": False}
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", result["model"]):
        raise PolicyUnavailable(family, "catalog model identity has unsupported characters")
    if initial_evidence == "provider_catalog_order":
        result["warning"] = "Provider-recommended catalog order; frontier ranking is not explicitly attested."
    return result


def policy_environment(env=None):
    """Ignore stale model-only pins; preserve credentials and permission policy."""
    out = dict(os.environ if env is None else env)
    for key in list(out):
        if (key.startswith("ANTHROPIC_DEFAULT_") and key.endswith("_MODEL")) or key in {
            "ANTHROPIC_MODEL", "CLAUDE_MODEL", "CLAUDE_CODE_EFFORT_LEVEL", "GROK_DEFAULT_MODEL",
            "GROK_MODEL", "CODEX_MODEL", "CHATGPT_MODEL", "CODEX_REASONING_EFFORT",
            "OPENAI_API_KEY", "CODEX_API_KEY", "XAI_API_KEY", "GROK_API_KEY",
            "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
            "OPENAI_BASE_URL", "OPENAI_API_BASE", "ANTHROPIC_BASE_URL",
            "XAI_BASE_URL", "GROK_BASE_URL", "GEMINI_API_KEY", "GOOGLE_API_KEY",
            "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
        }:
            out.pop(key, None)
    return out


def _run(argv, env):
    try:
        completed = subprocess.run(argv, env=env, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=25,
                                   shell=False, creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"CLI discovery {type(error).__name__}") from error
    if completed.returncode:
        # Provider stderr can contain credentials/login URLs. Never return it.
        raise RuntimeError(f"CLI discovery exited {completed.returncode}; check subscription login")
    return completed.stdout


def discover(family, *, env=None, runner=_run):
    env = policy_environment(env)
    binary = {"chatgpt": "codex", "claude": "claude", "grok": "grok", "gemini": "agy"}.get(family)
    if binary is None:
        raise PolicyUnavailable(str(family), "unknown model family")
    command = shutil.which(binary + (".exe" if os.name == "nt" else ""), path=env.get("PATH"))
    if not command:
        raise PolicyUnavailable(family, "subscription CLI is not installed", code="cli_missing")
    try:
        if family == "chatgpt":
            raw = json.loads(runner([command, "debug", "models"], env))
        elif family == "grok":
            version_text = runner([command, "--version"], env)
            version_match = re.search(r"\b\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.]+)?\b", version_text)
            runner([command, "models"], env)
            grok_root = Path(env.get("GROK_HOME") or Path(env.get("USERPROFILE") or env.get("HOME") or Path.home()) / ".grok")
            cache = json.loads((grok_root / "models_cache.json").read_text(encoding="utf-8"))
            from datetime import datetime, timezone
            fetched = datetime.fromisoformat(cache["fetched_at"].replace("Z", "+00:00"))
            # The subscription CLI renews unchanged catalogs after an etag
            # check without changing their original content-fetch timestamp.
            renewed = cache.get("renewed_at")
            fresh = (datetime.fromisoformat(renewed.replace("Z", "+00:00"))
                     if renewed is not None else fetched)
            if fresh < fetched:
                raise RuntimeError("Grok catalog renewal predates its content")
            age = (datetime.now(timezone.utc) - fresh).total_seconds()
            if not 0 <= age < CAPABILITY_TTL_SECONDS:
                raise RuntimeError("Grok catalog is stale; refresh subscription capability discovery")
            if cache.get("auth_method") != "session":
                raise RuntimeError("Grok capability catalog is not from subscription authentication")
            if not version_match or cache.get("grok_version") != version_match.group(0):
                raise RuntimeError("Grok capability catalog belongs to another CLI version")
            if cache.get("origin") != "https://cli-chat-proxy.grok.com/v1/models":
                raise RuntimeError("Grok capability catalog has an unverified subscription origin")
            raw = cache
        elif family == "claude":
            help_text = runner([command, "--help"], env)
            match = re.search(r"--effort\s+<[^>]+>[\s\S]{0,180}?\(([^)]+)\)", help_text)
            if not match:
                raise RuntimeError("Installed Claude CLI does not advertise effort capabilities")
            raw = {"efforts": [part.strip() for part in match.group(1).split(",")]}
        else:
            raise RuntimeError("agy capability discovery is not supported; configure a verified transport")
        return normalize_catalog(family, raw), command
    except (RuntimeError, ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        raise PolicyUnavailable(family, str(error)) from error


def _cache_identity(family, env):
    """Invalidate on CLI/auth/config changes without reading credential values."""
    profile = Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())
    binary = {"chatgpt": "codex", "claude": "claude", "grok": "grok", "gemini": "agy"}.get(family, "")
    command = shutil.which(binary, path=env.get("PATH")) if binary else None
    provider_root = Path(env.get("CODEX_HOME") or profile / ".codex") if family == "chatgpt" else (
        Path(env.get("GROK_HOME") or profile / ".grok") if family == "grok" else profile / ".claude")
    paths = ([Path(command)] if command else []) + [provider_root / name for name in
             ("auth.json", "config.toml", "settings.json", ".credentials.json", "session.json")]
    stamps = []
    for path in paths:
        try:
            stat = path.stat()
            stamps.append((str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns))
        except OSError:
            stamps.append((str(path), None))
    return (family, str(profile), env.get("PATH"), str(provider_root), tuple(stamps))


def resolve(family, *, settings=None, force=False, env=None, discoverer=None):
    """Resolve for a new session/seat. This never changes an existing session."""
    discoverer = discoverer or discover
    if settings is not None:
        if settings.get("settings_error"):
            raise PolicyUnavailable(family, "Anchor settings are invalid", code="invalid_settings")
        validate_policy(settings.get("model_policy", DEFAULT_POLICY))
    active_env = os.environ if env is None else env
    identity = _cache_identity(family, active_env)
    with _LOCK:
        cached = _MEMORY.get(identity)
        if force or not cached or time.time() - cached["discovered_at"] >= CAPABILITY_TTL_SECONDS:
            catalog, command = discoverer(family, env=active_env)
            selected = select_model(family, catalog)
            cached = {**selected, "command": command, "discovered_at": time.time()}
            _MEMORY[identity] = cached
        result = dict(cached)
        result["requested_policy"] = dict(DEFAULT_POLICY)
    result["settings_revision"] = (settings or {}).get("settings_revision", 0)
    return result


def launch_args(selection, *, subagents=True):
    family, model, effort = selection["family"], selection["model"], selection["effort"]
    if (family not in FAMILIES or not isinstance(model, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model)
            or effort not in EFFORT_ORDER):
        raise PolicyUnavailable(family, "invalid frozen launch selection")
    if family == "chatgpt":
        args = ["--model", model, "-c", f'model_reasoning_effort="{effort}"',
                "-c", 'forced_login_method="chatgpt"']
        if subagents:
            args += ["-c", f'agents.default_subagent_model="{model}"',
                     "-c", f'agents.default_subagent_reasoning_effort="{effort}"']
        return args
    if family == "claude":
        return ["--model", model, "--effort", effort]
    if family == "grok":
        return ["--model", model, "--reasoning-effort", effort]
    raise PolicyUnavailable(family, "no supported highest-effort launch contract")
