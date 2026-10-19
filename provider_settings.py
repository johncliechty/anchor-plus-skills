"""Non-secret provider metadata in Anchor's existing settings store.

Native CLIs own subscription credentials. Connections identify fixed native
homes; callers cannot nominate a credential path or an execution environment.
"""
from __future__ import annotations

from copy import deepcopy
import re
import uuid

FAMILIES = ("claude", "chatgpt", "gemini", "grok")
LABELS = {"claude": "Claude", "chatgpt": "ChatGPT", "gemini": "Gemini", "grok": "Grok"}
DEFAULT_PREFERENCES = {"family": None, "accounts": {}, "quality": {},
                       "warning_threshold": 20, "warning_policy": "warn"}


def default_connections():
    return [{"id": family + "-default", "family": family, "mode": "subscription",
             "name": "Existing native sign-in", "native_default": True} for family in FAMILIES]


def validate_connections(value):
    if not isinstance(value, list) or len(value) > 40:
        raise ValueError("Invalid provider connections")
    result, ids = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) != {"id", "family", "mode", "name", "native_default"}:
            raise ValueError("Only non-secret connection metadata is accepted")
        family, mode, identity = item["family"], item["mode"], item["id"]
        if family not in FAMILIES or mode not in ("subscription", "api") or type(item["native_default"]) is not bool:
            raise ValueError("Invalid provider or billing mode")
        default = item["native_default"]
        if default:
            if identity != family + "-default" or mode != "subscription":
                raise ValueError("Invalid default connection")
        elif not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{32}", identity):
            raise ValueError("Invalid connection identity")
        name = item["name"]
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 70 or any(ord(c) < 32 for c in name):
            raise ValueError("Use a nickname of 1 to 70 characters")
        if identity in ids:
            raise ValueError("Duplicate connection")
        ids.add(identity)
        result.append({**item, "name": name.strip()})
    if not all(family + "-default" in ids for family in FAMILIES):
        raise ValueError("Existing native connections must be retained")
    return result


def validate_preferences(value, connections):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_PREFERENCES):
        raise ValueError("Invalid provider preferences")
    if value["family"] not in (*FAMILIES, None):
        raise ValueError("Invalid provider")
    if type(value["warning_threshold"]) is not int or not 1 <= value["warning_threshold"] <= 50:
        raise ValueError("Warning threshold must be between 1 and 50 percent")
    if value["warning_policy"] not in ("warn", "manual", "offer"):
        raise ValueError("Warnings require an explicit quality or route choice")
    accounts, quality = value["accounts"], value["quality"]
    if not isinstance(accounts, dict) or not isinstance(quality, dict) or set(accounts) - set(FAMILIES) or set(quality) - set(FAMILIES):
        raise ValueError("Invalid account choices")
    rows = {c["id"]: c for c in connections}
    for family, identity in accounts.items():
        if not isinstance(identity, str) or identity not in rows or rows[identity]["family"] != family:
            raise ValueError("Account belongs to a different provider")
        if rows[identity]["mode"] != "subscription":
            raise ValueError("API execution is not supported by subscription seats")
    for family, choice in quality.items():
        if not isinstance(choice, dict) or set(choice) != {"model", "effort"}:
            raise ValueError("Invalid quality choice")
        if not isinstance(choice["model"], str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", choice["model"]):
            raise ValueError("Invalid model identity")
        if choice["effort"] not in ("highest_supported", "none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"):
            raise ValueError("Invalid reasoning effort")
    return deepcopy(value)


def new_connection(family, name, mode="subscription"):
    item = {"id": uuid.uuid4().hex, "family": family, "mode": mode, "name": name, "native_default": False}
    return validate_connections(default_connections() + [item])[-1]


def find_connection(settings, identity):
    for connection in settings.get("provider_connections", default_connections()):
        if connection["id"] == identity:
            return dict(connection)
    raise ValueError("Unknown provider connection")


def selected_connection(settings, family):
    prefs = settings.get("provider_preferences", DEFAULT_PREFERENCES)
    return find_connection(settings, prefs["accounts"].get(family, family + "-default"))
