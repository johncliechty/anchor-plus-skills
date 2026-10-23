"""gui_ingress_routes.py — Stage 1 · Get-Data ("Peel") HTTP & Upload Ingress Helpers.

Wave 14 Anvil Best-in-Class Refactoring (`1. Cockpit HTTP, Auth & File-Drop Ingress`):
Extracts pure HTTP request path/query parsing, loopback/Tailscale/bearer authentication
extraction, path-traversal guards, and file-drop ingress validation from `anchor_gui.py`.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping
from urllib.parse import parse_qs, urlparse


def unsafe_path_seg(seg: str | None) -> bool:
    """Return True when a single path segment attempts traversal (`..`, `/`, `\\`)."""
    if seg is None:
        return False
    return "/" in seg or "\\" in seg or ".." in seg


def normalize_route_path(raw_path: str | None) -> str:
    """Strip query string and fragment from a raw HTTP request path."""
    if not raw_path:
        return "/"
    parsed = urlparse(str(raw_path))
    path = parsed.path or "/"
    if len(path) > 1 and path.endswith("/"):
        return path.rstrip("/")
    return path


def parse_query_dict(raw_path: str | None) -> Dict[str, str]:
    """Extract single-valued query parameters from a raw HTTP request URL."""
    if not raw_path:
        return {}
    parsed = urlparse(str(raw_path))
    q = parse_qs(parsed.query, keep_blank_values=True)
    return {k: (v[0] if v else "") for k, v in q.items()}


def extract_bearer_token(
    headers: Mapping[str, Any] | None,
    query_params: Mapping[str, Any] | None = None,
) -> str:
    """Extract the Anchor authentication token from Authorization header, X-Anchor-Token, or query params."""
    hdrs = headers or {}
    auth = ""
    for k, v in hdrs.items():
        kl = str(k).lower()
        if kl == "authorization":
            auth = str(v or "").strip()
            break
        if kl in ("x-anchor-token", "x-steward-token"):
            tok = str(v or "").strip()
            if tok:
                return tok
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    if query_params:
        t = query_params.get("token")
        if isinstance(t, list):
            return str(t[0] if t else "").strip()
        if isinstance(t, str):
            return t.strip()
    return ""


def is_loopback_address(host: str | None) -> bool:
    """Return True if `host` is a loopback IPv4/IPv6 address or localhost."""
    h = str(host or "").strip().lower()
    if not h:
        return False
    if h.startswith("[") and "]" in h:
        h = h[1:h.index("]")]
    elif ":" in h and h.count(":") == 1:
        h = h.split(":", 1)[0]
    if h in ("localhost", "127.0.0.1", "::1", "::ffff:127.0.0.1"):
        return True
    try:
        return ipaddress.ip_address(h).is_loopback
    except ValueError:
        return False


def is_tailscale_host(host: str | None) -> bool:
    """Return True if `host` is a Tailscale MagicDNS hostname (`.ts.net`) or CGNAT 100.64.0.0/10 address."""
    h = str(host or "").strip().lower()
    if not h:
        return False
    if h.startswith("[") and "]" in h:
        h = h[1:h.index("]")]
    elif ":" in h and h.count(":") == 1:
        h = h.split(":", 1)[0]
    if h.endswith(".ts.net"):
        return True
    try:
        ip = ipaddress.ip_address(h)
        return ip in ipaddress.ip_network("100.64.0.0/10")
    except ValueError:
        return False


def parse_json_body(raw_bytes: bytes | str | None) -> tuple[Dict[str, Any], str | None]:
    """Parse an HTTP JSON request body safely into a dict, returning `(payload, error)`."""
    if not raw_bytes:
        return {}, None
    try:
        text = raw_bytes.decode("utf-8") if isinstance(raw_bytes, (bytes, bytearray)) else str(raw_bytes)
        if not text.strip():
            return {}, None
        obj = json.loads(text)
        if not isinstance(obj, dict):
            return {}, "JSON body must be an object"
        return obj, None
    except Exception as exc:
        return {}, f"invalid JSON: {exc}"


def validate_upload_meta(
    filename: str | None,
    size_bytes: int,
    max_bytes: int = 250_000_000,
    deny_ext: Iterable[str] = (),
) -> tuple[bool, str]:
    """Validate an uploaded file's basename, extension, and byte size before staging."""
    name = str(filename or "").strip()
    if not name or unsafe_path_seg(name) or name in (".", ".."):
        return False, "bad file name"
    ext = Path(name).suffix.lower()
    if ext and ext in {e.lower() for e in deny_ext}:
        return False, "that file type can't be loaded in"
    if size_bytes < 0:
        return False, "bad file size"
    if size_bytes > max_bytes:
        return False, "over 250 MB"
    return True, "ok"
