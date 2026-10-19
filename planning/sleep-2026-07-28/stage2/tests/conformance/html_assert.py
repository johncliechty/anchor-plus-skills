"""Visible-text-node assertions + node --check over generate_html output — W8.

Pattern mirrors the W6 named-state gate and the historical auth-reprompt
script-check style: extract ``<script>`` blocks from rendered HTML and run
``node --check`` when a node binary is on PATH.

Usage::

    from tests.conformance.html_assert import (
        assert_visible_text_contains,
        extract_script_blocks,
        node_check_scripts,
        visible_text_nodes,
    )

    html = generate_html([NamedState.unknown])
    assert_visible_text_contains(html, "unknown")
    node_check_scripts(html)
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Union

_SCRIPT_RE = re.compile(r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL)
_TAG_RE = re.compile(r"<[^>]+>")
_NAMED_STATE_RE = re.compile(
    r'data-named-state="([^"]+)"[^>]*>([^<]*)</',
    re.IGNORECASE,
)
_TEXT_NODE_RE = re.compile(r">([^<]+)<")


class HtmlAssertError(AssertionError):
    """Raised when a visible-text or node --check assertion fails."""


def visible_text_nodes(html: str) -> List[str]:
    """Return non-empty visible text nodes from HTML (approximate).

    Prefers ``data-named-state`` span contents (``render_state`` output), then
    generic text nodes between tags, then a tag-stripped fallback.
    """
    if html is None:
        return []
    text = str(html)
    nodes: List[str] = []

    for _token, content in _NAMED_STATE_RE.findall(text):
        t = (content or "").strip()
        if t:
            nodes.append(t)
        elif _token:
            nodes.append(_token)

    if nodes:
        return nodes

    for m in _TEXT_NODE_RE.finditer(text):
        t = m.group(1).strip()
        if t and not t.startswith("<!"):
            nodes.append(t)
    if nodes:
        return nodes

    stripped = _TAG_RE.sub(" ", text)
    return [p for p in stripped.split() if p]


def assert_visible_text_contains(
    html: str,
    expected: Union[str, Sequence[str]],
    *,
    msg: Optional[str] = None,
) -> List[str]:
    """Assert that every ``expected`` string appears as a visible text node.

    Matching is substring against the joined visible text *and* exact-token
    membership of individual nodes, so both ``"unknown"`` labels and longer
    sentences that include the token pass.
    """
    nodes = visible_text_nodes(html)
    joined = " ".join(nodes)
    if isinstance(expected, str):
        wanted = [expected]
    else:
        wanted = list(expected)
    missing = []
    for exp in wanted:
        if exp in nodes or exp in joined:
            continue
        # Also accept data-named-state token presence as a visible label.
        if 'data-named-state="%s"' % exp in (html or ""):
            continue
        missing.append(exp)
    if missing:
        raise HtmlAssertError(
            msg
            or (
                "visible text missing %r — nodes=%r"
                % (missing, nodes)
            )
        )
    return nodes


def assert_visible_texts_distinct(
    html_by_key: dict,
    *,
    msg: Optional[str] = None,
) -> dict:
    """Assert each key's HTML primary visible label is pairwise distinct."""
    labels = {}
    for key, html in html_by_key.items():
        nodes = visible_text_nodes(html)
        labels[key] = nodes[0] if nodes else ""
    values = list(labels.values())
    if len(set(values)) != len(values) or any(not v for v in values):
        raise HtmlAssertError(
            msg
            or (
                "visible texts not distinct or blank: %r" % labels
            )
        )
    return labels


def extract_script_blocks(html: str) -> List[str]:
    """Extract raw contents of every ``<script>`` block (no src= external)."""
    if not html:
        return []
    blocks = []
    for m in _SCRIPT_RE.finditer(html):
        # Skip external script tags with empty bodies that only set src=
        tag_open = html[m.start() : m.start() + 64].lower()
        body = m.group(1)
        if "src=" in tag_open and not (body or "").strip():
            continue
        blocks.append(body)
    return blocks


def node_check_scripts(
    html: str,
    *,
    work_dir: Optional[Union[str, Path]] = None,
    require_node: bool = False,
) -> List[str]:
    """Run ``node --check`` on every extracted ``<script>`` block.

    Returns the list of script bodies checked. If ``node`` is not on PATH:
    * ``require_node=False`` (default) → skip check, return bodies
    * ``require_node=True`` → raise :class:`HtmlAssertError`

    A non-zero ``node --check`` exit always raises.
    """
    blocks = extract_script_blocks(html)
    if not blocks:
        return []

    node = shutil.which("node")
    if not node:
        if require_node:
            raise HtmlAssertError(
                "node binary not on PATH — cannot node --check script blocks"
            )
        return blocks

    if work_dir is not None:
        base = Path(work_dir)
        base.mkdir(parents=True, exist_ok=True)
        cleanup_dir = None
    else:
        cleanup_dir = tempfile.TemporaryDirectory(prefix="html_assert_node_")
        base = Path(cleanup_dir.name)

    try:
        for idx, body in enumerate(blocks):
            out = base / ("script_check_%d.js" % idx)
            out.write_text(body, encoding="utf-8")
            proc = subprocess.run(
                [node, "--check", str(out)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if proc.returncode != 0:
                raise HtmlAssertError(
                    "node --check failed for script block %d:\n%s\n%s"
                    % (idx, proc.stdout, proc.stderr)
                )
    finally:
        if cleanup_dir is not None:
            cleanup_dir.cleanup()

    return blocks


def assert_generate_html_shape(
    html: str,
    *,
    required_labels: Optional[Iterable[str]] = None,
) -> None:
    """Light structural checks on a generate_html-style document."""
    if not html or "<html" not in html.lower():
        raise HtmlAssertError("generate_html output missing <html>")
    if required_labels:
        assert_visible_text_contains(html, list(required_labels))


__all__ = [
    "HtmlAssertError",
    "assert_generate_html_shape",
    "assert_visible_text_contains",
    "assert_visible_texts_distinct",
    "extract_script_blocks",
    "node_check_scripts",
    "visible_text_nodes",
]
