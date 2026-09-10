#!/usr/bin/env python3
"""Anchor durable settings store — model/engine prefs (stdlib only).

Single source of truth for the interactive default CLI and the coding/review
model families. Written under ``paths.WRITE_LOCK`` with atomic primary + mirror
writes so concurrent ThreadingHTTPServer writers and non-Anchor agents (VS Code,
Claude Code, Grok Build) share the same prefs.

Primary: ``paths.data_dir() / "settings.json"``
Mirror:  ``~/.anchor/model_prefs.json`` (discoverable without ANCHOR_DATA_DIR)

Display reads remain available during configuration errors. Model launches use
get_launch_settings(), which refuses corrupt or missing authoritative settings.
"""

from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import paths as _paths
from model_policy import DEFAULT_POLICY, validate_policy

VALID_CLIS = frozenset({"claude", "gemini", "grok", "chatgpt"})
VALID_FAMILIES = VALID_CLIS
# (John, 2026-09-05) ChatGPT reviews and judges: the Codex transport attests the
# family, not the served model, so its verdicts carry a model-unattested stamp.
VALID_REVIEW_FAMILIES = frozenset({"claude", "gemini", "grok", "chatgpt"})
# (John, 2026-09-05) ChatGPT drives the interactive terminal too — the Codex TUI
# in the cockpit PTY — so every family is a valid default terminal CLI.
VALID_DEFAULT_CLIS = VALID_CLIS

# ── Steward personas (2026-07-29) ────────────────────────────────────────────
# One steward engine, selectable livery. The HIGH SEAT icon fronts the
# portfolio steward on the main dashboard; the SEAL icon fronts each project
# (the Projects tile + future per-project chamber). Icon files live in
# vendor/brand/ and ship with the bundle.
STEWARDS = {
    "ecgberht": {
        "label": "Ecgberht",
        "desc": "The royal steward — stone high seat and wax seal (the original).",
        "high_seat": "ecgberht-portfolio-high-seat.jpg",
        "seal": "ecgberht-project-seal.jpg",
        # Persona-consistent NAMING (2026-07-30): the portfolio surface and
        # the project mark are called by the persona's OWN names everywhere
        # (tile titles, hints, tooltips) — never a mixed livery.
        "high_seat_name": "High Seat",
        "seal_name": "Seal",
        "projects_hint": "each under Ecgberht&rsquo;s seal",
    },
    "aladdin": {
        "label": "Aladdin",
        "desc": "The genie-lamp world — the opened treasure cave and the watchful lamp.",
        "high_seat": "aladdin-high-seat-cave.jpg",
        "seal": "aladdin-seal-lamp.jpg",
        "high_seat_name": "Cave of Wonders",
        "seal_name": "Lamp",
        "projects_hint": "each kept under the Lamp&rsquo;s watch",
    },
    "jarvis": {
        "label": "Jarvis",
        "desc": "The unseen English butler — the tipped bowler and the silver server.",
        "high_seat": "jarvis-high-seat-hat.jpg",
        "seal": "jarvis-seal-salver.jpg",
        "high_seat_name": "Tip of the Hat",
        # (2026-07-30, John) The tray is called the SERVER, not the "salver" —
        # at a glance that word reads as "slaver", which is not a thing this
        # dashboard should ever appear to say. The image filename keeps its
        # original slug (asset identity + ship manifest); only the human-facing
        # label changed.
        "seal_name": "Server",
        "projects_hint": "each served on the Server",
    },
}
VALID_STEWARDS = frozenset(STEWARDS)

DEFAULTS = {
    "default_cli": "grok",
    "coding_family": "claude",
    "review_family": "gemini",
    "steward_type": "ecgberht",
}

SETTINGS_NAME = "settings.json"
MIRROR_DIRNAME = ".anchor"
MIRROR_NAME = "model_prefs.json"


class SettingsInvalid(ValueError):
    """Display may continue, but no model may launch from invalid authority."""


@contextmanager
def _settings_write_lock():
    """Serialize UI and standalone writers across processes, not just threads."""
    with _paths.WRITE_LOCK:
        lock_path = settings_path().with_name(".settings.lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a+b") as stream:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            deadline = time.monotonic() + 5
            while True:
                try:
                    stream.seek(0)
                    if os.name == "nt":
                        import msvcrt
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise SettingsInvalid("Settings are busy; try saving again")
                    time.sleep(0.05)
            try:
                yield
            finally:
                stream.seek(0)
                if os.name == "nt":
                    import msvcrt
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def settings_path() -> Path:
    """Return the fixed primary settings path for this Anchor checkout/data dir.

    Mirror content is never path authority.  In particular, its informational
    ``primary_path`` field cannot redirect a later save to another host path.
    """
    return _paths.data_dir() / SETTINGS_NAME


def mirror_path() -> Path:
    """Absolute path to ``~/.anchor/model_prefs.json`` (agent-discoverable mirror)."""
    return Path.home() / MIRROR_DIRNAME / MIRROR_NAME


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _normalize(raw) -> dict:
    """Return a complete, validated settings dict from arbitrary input.

    Unknown / invalid field values fall back to :data:`DEFAULTS`. Always returns
    a new dict with every schema key present (including ``updated_at``).
    """
    out = dict(DEFAULTS)
    out["model_policy"] = dict(DEFAULT_POLICY)
    out["settings_revision"] = 0
    out["updated_at"] = _now_iso()
    if not isinstance(raw, dict):
        return out
    cli = raw.get("default_cli")
    if isinstance(cli, str) and cli.strip() in VALID_DEFAULT_CLIS:
        out["default_cli"] = cli.strip()
    fam = raw.get("coding_family")
    if isinstance(fam, str) and fam.strip() in VALID_CLIS:
        out["coding_family"] = fam.strip()
    review = raw.get("review_family")
    if isinstance(review, str) and review.strip() in VALID_REVIEW_FAMILIES:
        out["review_family"] = review.strip()
    stew = raw.get("steward_type")
    if isinstance(stew, str) and stew.strip() in VALID_STEWARDS:
        out["steward_type"] = stew.strip()
    ts = raw.get("updated_at")
    if isinstance(ts, str) and ts.strip():
        out["updated_at"] = ts.strip()
    if isinstance(raw.get("settings_revision"), int) and not isinstance(raw["settings_revision"], bool):
        out["settings_revision"] = raw["settings_revision"]
    if "model_policy" in raw:
        try:
            out["model_policy"] = validate_policy(raw["model_policy"])
        except ValueError:
            pass  # Display normalization only; read_settings_state rejects it for launch.
    return out


def _read_settings_dict(path: Path) -> dict | None:
    """Read one settings object, returning ``None`` on any invalid input."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return None


def _prefer_valid_values(preferred, fallback) -> dict:
    """Overlay valid preference values without letting junk mask fallbacks."""
    merged = dict(fallback) if isinstance(fallback, dict) else {}
    if not isinstance(preferred, dict):
        return merged
    cli = preferred.get("default_cli")
    if isinstance(cli, str) and cli.strip() in VALID_DEFAULT_CLIS:
        merged["default_cli"] = cli.strip()
    fam = preferred.get("coding_family")
    if isinstance(fam, str) and fam.strip() in VALID_CLIS:
        merged["coding_family"] = fam.strip()
    review = preferred.get("review_family")
    if isinstance(review, str) and review.strip() in VALID_REVIEW_FAMILIES:
        merged["review_family"] = review.strip()
    steward = preferred.get("steward_type")
    if isinstance(steward, str) and steward.strip() in VALID_STEWARDS:
        merged["steward_type"] = steward.strip()
    updated_at = preferred.get("updated_at")
    if isinstance(updated_at, str) and updated_at.strip():
        merged["updated_at"] = updated_at.strip()
    return merged


def read_settings_state() -> dict:
    """Primary wins. Corrupt primary cannot be hidden by mirror or defaults."""
    primary_path = settings_path()
    try:
        primary_exists = primary_path.exists()
        selected_path = primary_path
        if not primary_exists:
            if mirror_path().exists():
                selected_path = mirror_path()
        if not selected_path.exists():
            return {"settings": _normalize(None), "valid": False, "missing": True,
                    "error": "Model preferences are not configured", "source": str(primary_path)}
        raw = json.loads(selected_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("expected a settings object")
        for key, allowed in (("default_cli", VALID_DEFAULT_CLIS), ("coding_family", VALID_CLIS),
                             ("review_family", VALID_REVIEW_FAMILIES)):
            if key not in raw or raw[key] not in allowed:
                raise ValueError(f"missing or invalid {key}")
        validate_policy(raw.get("model_policy", DEFAULT_POLICY))
        revision = raw.get("settings_revision", 0)
        if not isinstance(revision, int) or isinstance(revision, bool) or revision < 0:
            raise ValueError("invalid settings_revision")
        result = _normalize(raw)
        mirror = _read_settings_dict(mirror_path())
        if selected_path == primary_path and mirror is not None:
            if any(mirror.get(key, DEFAULT_POLICY if key == "model_policy" else 0 if key == "settings_revision" else None)
                   != result[key] for key in ("default_cli", "coding_family", "review_family", "steward_type",
                                             "model_policy", "settings_revision")):
                result["mirror_out_of_sync"] = True
        return {"settings": result, "valid": True, "missing": False,
                "error": None, "source": str(selected_path)}
    except (OSError, ValueError, TypeError) as error:
        return {"settings": _normalize(None), "valid": False, "missing": False,
                "error": f"Model preferences are invalid ({type(error).__name__}); repair settings before launching AI",
                "source": str(primary_path)}


def load_settings() -> dict:
    """Non-raising display contract; invalid values are explicitly NOT launchable."""
    state = read_settings_state()
    result = dict(state["settings"])
    if not state["valid"]:
        result["settings_error"] = state["error"]
    return result


def get_launch_settings() -> dict:
    state = read_settings_state()
    if not state["valid"]:
        raise SettingsInvalid(state["error"])
    return dict(state["settings"])


def _atomic_write_json(path: Path, obj: dict) -> None:
    """Atomic JSON write (tmp + os.replace). Caller holds WRITE_LOCK."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    _paths.atomic_write_text(path, text)


def save_settings(**kwargs) -> dict:
    """Read/merge/write one revision under the stable cross-process lock."""
    with _settings_write_lock():
        return _save_settings_locked(**kwargs)


def _save_settings_locked(**kwargs) -> dict:
    """Merge partial updates into settings, validate, write primary + mirror.

    Only recognized keys (``default_cli``, ``coding_family``, ``review_family``)
    are applied; invalid values raise :class:`ValueError`. Returns the full
    settings dict after write. Always stamps a fresh ``updated_at``.
    """
    state = read_settings_state()
    if not state["valid"] and not state["missing"]:
        raise SettingsInvalid(state["error"])
    current = dict(state["settings"])
    current.pop("mirror_out_of_sync", None)
    expected = kwargs.get("expected_revision")
    if expected is not None and (type(expected) is not int or expected < 0):
        raise ValueError("expected_revision must be a nonnegative integer")
    if expected is not None and expected != current["settings_revision"]:
        raise SettingsInvalid("Model settings changed; reload before saving")
    for key in ("default_cli", "coding_family", "review_family"):
        if key not in kwargs:
            continue
        val = kwargs[key]
        allowed = (VALID_REVIEW_FAMILIES if key == "review_family"
                   else VALID_DEFAULT_CLIS if key == "default_cli"
                   else VALID_CLIS)
        if not isinstance(val, str) or val.strip() not in allowed:
            raise ValueError(
                "invalid %s %r (expected one of %s)"
                % (key, val, "|".join(sorted(allowed)))
            )
        current[key] = val.strip()
    if "steward_type" in kwargs:
        val = kwargs["steward_type"]
        if not isinstance(val, str) or val.strip() not in VALID_STEWARDS:
            raise ValueError(
                "invalid steward_type %r (expected one of %s)"
                % (val, "|".join(sorted(VALID_STEWARDS)))
            )
        current["steward_type"] = val.strip()
    if "model_policy" in kwargs:
        current["model_policy"] = validate_policy(kwargs["model_policy"])
    current["settings_revision"] += 1
    current["updated_at"] = _now_iso()

    primary = settings_path()
    mirror = mirror_path()
    mirror_payload = dict(current)
    mirror_payload["source"] = "anchor"
    mirror_payload["primary_path"] = str(primary.resolve())

    with _paths.WRITE_LOCK:
        _atomic_write_json(primary, current)
        mirror_write_ok = True
        try:
            _atomic_write_json(mirror, mirror_payload)
        except OSError:
            # Primary stays authoritative. Report the incomplete mirror without
            # rolling back or letting stale mirror values undo the saved choice.
            mirror_write_ok = False
    result = load_settings()
    if not mirror_write_ok or any(
        result.get(k) != current.get(k)
        for k in ("default_cli", "coding_family", "review_family", "steward_type", "model_policy", "settings_revision")
    ):
        result = dict(result)
        result["mirror_out_of_sync"] = True
    return result


def get_default_cli() -> str:
    return load_settings()["default_cli"]


def get_coding_family() -> str:
    return load_settings()["coding_family"]


def get_review_family() -> str:
    return load_settings()["review_family"]


def families_are_cross_model() -> bool:
    """True when coding and review families differ (cross-model verification)."""
    s = load_settings()
    return s["coding_family"] != s["review_family"]


def resolve_tier_label(family: str, tier: str) -> str:
    """Workflow depth never lowers the shared latest/highest model policy."""
    fam = (family or "").strip() or "unknown"
    return "%s:latest-supported / highest-supported effort" % fam


def export_env_overrides() -> dict:
    """Env vars agents/engines should honor for the current settings."""
    s = load_settings()
    coding = s["coding_family"]
    review = s["review_family"]
    cross = "true" if coding != review else "false"
    return {
        "ANCHOR_DATA_DIR": str(settings_path().parent),
        "ANCHOR_DEFAULT_CLI": s["default_cli"],
        "ANCHOR_CODING_FAMILY": coding,
        "ANCHOR_REVIEW_FAMILY": review,
        "CODING_FAMILY": coding,
        "REVIEW_FAMILY": review,
        "CROSS_MODEL": cross,
    }


def steward_profile(settings: dict | None = None) -> dict:
    """The ACTIVE steward persona: {key, label, desc, high_seat, seal}.

    Total — an unknown/corrupt stored value falls back to the Ecgberht
    default, so callers can always render an icon pair.
    """
    s = settings if isinstance(settings, dict) else load_settings()
    key = s.get("steward_type") or DEFAULTS["steward_type"]
    if key not in STEWARDS:
        key = DEFAULTS["steward_type"]
    prof = dict(STEWARDS[key])
    prof["key"] = key
    return prof
