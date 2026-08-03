#!/usr/bin/env python3
"""Anchor durable settings store — model/engine prefs (stdlib only).

Single source of truth for the interactive default CLI and the coding/review
model families. Written under ``paths.WRITE_LOCK`` with atomic primary + mirror
writes so concurrent ThreadingHTTPServer writers and non-Anchor agents (VS Code,
Claude Code, Grok Build) share the same prefs.

Primary: ``paths.data_dir() / "settings.json"``
Mirror:  ``~/.anchor/model_prefs.json`` (discoverable without ANCHOR_DATA_DIR)

Never raises on load — corrupt/missing store falls back to defaults.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import paths as _paths

VALID_CLIS = frozenset({"claude", "gemini", "grok"})
VALID_FAMILIES = VALID_CLIS

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


def settings_path() -> Path:
    """Absolute path to the primary settings JSON under the Anchor data dir."""
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
    out["updated_at"] = _now_iso()
    if not isinstance(raw, dict):
        return out
    for key in ("default_cli", "coding_family", "review_family"):
        val = raw.get(key)
        if isinstance(val, str) and val.strip() in VALID_CLIS:
            out[key] = val.strip()
    stew = raw.get("steward_type")
    if isinstance(stew, str) and stew.strip() in VALID_STEWARDS:
        out["steward_type"] = stew.strip()
    ts = raw.get("updated_at")
    if isinstance(ts, str) and ts.strip():
        out["updated_at"] = ts.strip()
    return out


def load_settings() -> dict:
    """Load settings; always complete, never raises (falls back to defaults)."""
    p = settings_path()
    try:
        if not p.exists():
            return _normalize(None)
        data = json.loads(p.read_text(encoding="utf-8"))
        return _normalize(data)
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return _normalize(None)


def _atomic_write_json(path: Path, obj: dict) -> None:
    """Atomic JSON write (tmp + os.replace). Caller holds WRITE_LOCK."""
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=2, ensure_ascii=False) + "\n"
    _paths.atomic_write_text(path, text)


def save_settings(**kwargs) -> dict:
    """Merge partial updates into settings, validate, write primary + mirror.

    Only recognized keys (``default_cli``, ``coding_family``, ``review_family``)
    are applied; invalid values raise :class:`ValueError`. Returns the full
    settings dict after write. Always stamps a fresh ``updated_at``.
    """
    current = load_settings()
    for key in ("default_cli", "coding_family", "review_family"):
        if key not in kwargs:
            continue
        val = kwargs[key]
        if not isinstance(val, str) or val.strip() not in VALID_CLIS:
            raise ValueError(
                "invalid %s %r (expected one of %s)"
                % (key, val, "|".join(sorted(VALID_CLIS)))
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
    current["updated_at"] = _now_iso()

    primary = settings_path()
    mirror = mirror_path()
    mirror_payload = dict(current)
    mirror_payload["source"] = "anchor"
    mirror_payload["primary_path"] = str(primary.resolve())

    with _paths.WRITE_LOCK:
        _atomic_write_json(primary, current)
        try:
            _atomic_write_json(mirror, mirror_payload)
        except OSError:
            # Mirror is best-effort — primary is the source of truth.
            pass
    return dict(current)


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
    """Descriptive tier label for UI/docs — NOT a hard product model id.

    ``tier`` is ``heavy`` | ``standard`` | ``regular``:
      - heavy → ``"<family>:frontier (top tier of family)"``
      - standard/regular → ``"<family>:one-notch-below-frontier"``
    """
    fam = (family or "").strip() or "unknown"
    t = (tier or "").strip().lower()
    if t == "heavy":
        return "%s:frontier (top tier of family)" % fam
    # standard / regular / anything else treated as one-notch-below
    return "%s:one-notch-below-frontier" % fam


def export_env_overrides() -> dict:
    """Env vars agents/engines should honor for the current settings."""
    s = load_settings()
    coding = s["coding_family"]
    review = s["review_family"]
    cross = "true" if coding != review else "false"
    return {
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
