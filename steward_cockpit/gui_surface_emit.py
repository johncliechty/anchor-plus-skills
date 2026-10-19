"""gui_surface_emit.py — Stage 3 · Create-Output ("Peel") HTML, Script & SSE Surface Emitters.

Wave 14 Anvil Best-in-Class Refactoring (`4. Cave of Wonders` + `5. Skill Foundry & Anvil Workbench`):
Extracts HTML/JSON/SSE response emission helpers, cache-bust script formatting, `window.ANCHOR_BOOT`
script rendering, and deliverable approval stream rendering from `anchor_gui.py`.
"""
from __future__ import annotations

import html
import json
from typing import Any, Callable, Dict, Iterable, List, Tuple


def render_cache_bust_script(template: str, build_id: str) -> str:
    """Substitute `__ANCHOR_BUILD_ID__` in the cache-bust JS template."""
    return str(template or "").replace("__ANCHOR_BUILD_ID__", str(build_id or ""))


def render_anchor_boot_script(boot_dict: Dict[str, Any]) -> str:
    """Serialize `window.ANCHOR_BOOT` into a safe inline `<script>` tag (`</` escaped)."""
    raw = json.dumps(boot_dict or {}, separators=(",", ":"), sort_keys=True)
    safe_json = raw.replace("</", "<\\/")
    return f"<script>window.ANCHOR_BOOT={safe_json};</script>"


def render_deliv_approved_html(
    items: List[Any],
    project_id: str,
    item_renderer: Callable[[Any, str], str],
) -> str:
    """Render the `<details class='deliv-stream'>` collapsible approved deliverables block."""
    rows = "".join(item_renderer(it, project_id) for it in (items or ())) or (
        "<div class='navempty'>No explicitly approved deliverables yet.</div>"
    )
    return (
        "<details class='deliv-stream'>"
        f"<summary>Approved deliverables \u00b7 {len(items or ())}</summary>"
        f"<div class='deliv-stream-body'>{rows}</div></details>"
    )


def format_sse_frame(payload: Dict[str, Any] | str, event_name: str | None = None) -> bytes:
    """Format an SSE `data:` frame (with optional `event:`) as UTF-8 bytes."""
    lines: List[str] = []
    if event_name:
        clean_ev = str(event_name).replace("\r", "").replace("\n", "")
        lines.append(f"event: {clean_ev}")
    body = payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False)
    for part in str(body).splitlines() or [""]:
        lines.append(f"data: {part}")
    return ("\n".join(lines) + "\n\n").encode("utf-8")


def build_response_headers(
    content_type: str,
    content_length: int | None = None,
    cache: str = "no-store",
    cookie: str | None = None,
) -> List[Tuple[str, str]]:
    """Construct standard HTTP response headers for Anchor GUI HTML/JSON/static responses."""
    hdrs: List[Tuple[str, str]] = [
        ("Content-Type", str(content_type or "text/plain; charset=utf-8")),
        ("Cache-Control", str(cache or "no-store")),
        ("X-Content-Type-Options", "nosniff"),
    ]
    if content_length is not None:
        hdrs.append(("Content-Length", str(int(content_length))))
    if cookie:
        hdrs.append(("Set-Cookie", str(cookie)))
    return hdrs
