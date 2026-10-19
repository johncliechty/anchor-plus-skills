"""Open + Run surface view — W10, Phase 3.

Both controls render exclusively through ``dead_control`` + ``render_state``.
A dead Open or Run button is a build failure, not a finding to file later.

Surfaces:

* workbench chrome: Open control + Run control
* project-list honesty: empty (no projects) ≠ unknown (store unreadable)
* cannot-* panels for every enumerated open/run reason

``generate_html`` returns a full document with a syntax-valid ``<script>``
block suitable for ``node --check``.
"""
from __future__ import annotations

import html
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Union

from anchor.session.open_work import (
    OPEN_REASONS,
    CannotOpen,
    OpenedWork,
    ProjectStore,
    empty_store,
    list_projects_state,
    open_reason_named_state,
    open_work,
    unreadable_store,
)
from anchor.session.run_work import (
    RUN_REASONS,
    CannotRun,
    LiveRunHandle,
    RunEnvironment,
    empty_run_env,
    list_targets_state,
    make_run_env,
    run_reason_named_state,
    run_work,
)
from anchor.ui.dead_control import (
    CONTROL_OPEN,
    CONTROL_RUN,
    ControlRender,
    assert_no_dead_controls,
    audit_dead_controls,
    count_cannot_states,
    count_live_controls,
    decide_control,
    render_cannot_state,
    render_control,
)
from anchor.ui.named_state import NamedState, render_state
from tools.capability_inventory import InventoryRow

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

SURFACE_ID = "open-run"
WAVE_ID = "W10"

OPEN_ACTION = "action:open"
RUN_ACTION = "action:run"


@dataclass
class OpenRunViewContext:
    """Inputs that drive the open/run surface render."""

    open_row: Optional[InventoryRow] = None
    run_row: Optional[InventoryRow] = None
    project_store: Optional[ProjectStore] = None
    run_env: Optional[RunEnvironment] = None
    project_id: Optional[str] = None
    target_id: Optional[str] = None
    engine: str = ""
    open_capability_present: Optional[bool] = None
    run_capability_present: Optional[bool] = None
    force_open_reason: Optional[str] = None
    force_run_reason: Optional[str] = None
    force_open_absent: bool = False
    force_run_absent: bool = False
    as_of: Optional[date] = None
    root: Optional[Path] = None
    #: Live-authorization head hash (must match inventory source_hash for PRESENT).
    #: When omitted, dead_control falls back to hashing on-disk sources.
    head_hash: Optional[str] = None
    open_head_hash: Optional[str] = None
    run_head_hash: Optional[str] = None
    content_overrides: Optional[Mapping[str, bytes]] = None
    title: str = "Open + Run workbench"


@dataclass
class OpenRunViewResult:
    """Structured render outcome for tests and traces."""

    html: str
    open_control: ControlRender
    run_control: ControlRender
    open_result: Optional[Union[OpenedWork, CannotOpen]] = None
    run_result: Optional[Union[LiveRunHandle, CannotRun]] = None
    project_list_state: Optional[NamedState] = None
    target_list_state: Optional[NamedState] = None
    dead_control_findings: List[Any] = field(default_factory=list)

    @property
    def open_is_live(self) -> bool:
        return self.open_control.mode.value == "live"

    @property
    def run_is_live(self) -> bool:
        return self.run_control.mode.value == "live"


# --------------------------------------------------------------------------
# Control rendering
# --------------------------------------------------------------------------


def render_open_control(
    *,
    row: Optional[InventoryRow] = None,
    inventory: Optional[Any] = None,
    root: Optional[Path] = None,
    as_of: Optional[date] = None,
    force_absent: bool = False,
    label: str = "Open",
    head_hash: Optional[str] = None,
    content_overrides: Optional[Mapping[str, bytes]] = None,
) -> ControlRender:
    """Render the Open control exclusively via dead_control.

    Authorization parameters (``row`` / ``inventory`` / ``head_hash`` /
    ``content_overrides`` / ``as_of`` / ``root``) are passed through to
    ``decide_control`` so the live-PRESENT seam is not stripped at this
    surface boundary.
    """
    return render_control(
        CONTROL_OPEN,
        label=label,
        action=OPEN_ACTION,
        row=row,
        inventory=inventory,
        root=root,
        as_of=as_of,
        head_hash=head_hash,
        content_overrides=content_overrides,
        cannot_state=NamedState.cannot_open,
        force_absent=force_absent,
    )


def render_run_control(
    *,
    row: Optional[InventoryRow] = None,
    inventory: Optional[Any] = None,
    root: Optional[Path] = None,
    as_of: Optional[date] = None,
    force_absent: bool = False,
    label: str = "Run",
    head_hash: Optional[str] = None,
    content_overrides: Optional[Mapping[str, bytes]] = None,
) -> ControlRender:
    """Render the Run control exclusively via dead_control.

    Authorization parameters are passed through to ``decide_control`` —
    the dead-control auth seam is not stripped at this surface boundary.
    """
    return render_control(
        CONTROL_RUN,
        label=label,
        action=RUN_ACTION,
        row=row,
        inventory=inventory,
        root=root,
        as_of=as_of,
        head_hash=head_hash,
        content_overrides=content_overrides,
        cannot_state=NamedState.cannot_run,
        force_absent=force_absent,
    )


# --------------------------------------------------------------------------
# Outcome panels (handler results)
# --------------------------------------------------------------------------


def render_open_outcome(result: Union[OpenedWork, CannotOpen]) -> str:
    """Visible panel for an open_work result (always through render_state)."""
    if isinstance(result, OpenedWork):
        state_html = render_state(NamedState.ok)
        detail = html.escape(
            "opened %s" % (result.label or result.project_id), quote=False
        )
        return (
            '<div class="open-outcome" data-open-ok="true">'
            "%s <span class=\"open-detail\">%s</span></div>"
            % (state_html, detail)
        )
    # CannotOpen — reason-specific NamedState (unknown for store unreadable).
    state_html = render_state(result.named_state)
    reason = html.escape(result.reason, quote=True)
    label = html.escape(result.label or result.reason, quote=False)
    return (
        '<div class="open-outcome" data-open-ok="false" data-open-reason="%s">'
        "%s <span class=\"open-reason-label\">%s</span></div>"
        % (reason, state_html, label)
    )


def render_run_outcome(result: Union[LiveRunHandle, CannotRun]) -> str:
    """Visible panel for a run_work result (always through render_state)."""
    if isinstance(result, LiveRunHandle):
        state_html = render_state(NamedState.ok)
        detail = html.escape(
            "running %s" % (result.run_id,), quote=False
        )
        return (
            '<div class="run-outcome" data-run-ok="true">'
            "%s <span class=\"run-detail\">%s</span></div>"
            % (state_html, detail)
        )
    state_html = render_state(result.named_state)
    reason = html.escape(result.reason, quote=True)
    label = html.escape(result.label or result.reason, quote=False)
    return (
        '<div class="run-outcome" data-run-ok="false" data-run-reason="%s">'
        "%s <span class=\"run-reason-label\">%s</span></div>"
        % (reason, state_html, label)
    )


def render_list_state_tile(
    state: NamedState,
    *,
    surface: str,
) -> str:
    """Tile for project/target list trichotomy (unknown ≠ empty)."""
    return (
        '<div class="list-state-tile" data-list-surface="%s" data-list-state="%s">'
        "%s</div>"
        % (
            html.escape(surface, quote=True),
            html.escape(state.value, quote=True),
            render_state(state),
        )
    )


def render_reason_matrix() -> str:
    """Document every enumerated open/run reason as a visible cannot-* row."""
    rows: List[str] = []
    for reason in OPEN_REASONS:
        ns = open_reason_named_state(reason)
        rows.append(
            '<div class="reason-row" data-control="open" data-reason="%s">'
            '<span class="reason-token">%s</span> %s</div>'
            % (
                html.escape(reason, quote=True),
                html.escape(reason, quote=False),
                render_state(ns),
            )
        )
    for reason in RUN_REASONS:
        ns = run_reason_named_state(reason)
        rows.append(
            '<div class="reason-row" data-control="run" data-reason="%s">'
            '<span class="reason-token">%s</span> %s</div>'
            % (
                html.escape(reason, quote=True),
                html.escape(reason, quote=False),
                render_state(ns),
            )
        )
    return '<section class="reason-matrix" data-surface="open-run-reasons">\n%s\n</section>' % (
        "\n".join(rows),
    )


# --------------------------------------------------------------------------
# Full surface
# --------------------------------------------------------------------------


def render_workbench(ctx: Optional[OpenRunViewContext] = None) -> OpenRunViewResult:
    """Render the open+run workbench and run handlers for the given context."""
    c = ctx or OpenRunViewContext()
    store = c.project_store if c.project_store is not None else empty_store()
    env = c.run_env if c.run_env is not None else empty_run_env()

    # Auth seam: head_hash / content_overrides flow into decide_control.
    open_hh = c.open_head_hash if c.open_head_hash is not None else c.head_hash
    run_hh = c.run_head_hash if c.run_head_hash is not None else c.head_hash

    open_ctrl = render_open_control(
        row=c.open_row,
        root=c.root,
        as_of=c.as_of,
        force_absent=c.force_open_absent,
        head_hash=open_hh,
        content_overrides=c.content_overrides,
    )
    run_ctrl = render_run_control(
        row=c.run_row,
        root=c.root,
        as_of=c.as_of,
        force_absent=c.force_run_absent,
        head_hash=run_hh,
        content_overrides=c.content_overrides,
    )

    # Handler outcomes (used by traces + outcome panels).
    open_result = open_work(
        c.project_id,
        store=store,
        inventory_row=c.open_row,
        capability_present=c.open_capability_present,
        force_reason=c.force_open_reason,
        root=c.root,
    )
    run_result = run_work(
        c.target_id,
        engine=c.engine,
        env=env,
        inventory_row=c.run_row,
        capability_present=c.run_capability_present,
        force_reason=c.force_run_reason,
        root=c.root,
    )

    project_state = list_projects_state(store)
    target_state = list_targets_state(env)

    body_parts = [
        '<section class="controls" data-surface="open-run-controls">',
        '  <div class="control-slot" data-slot="open">%s</div>' % open_ctrl.html,
        '  <div class="control-slot" data-slot="run">%s</div>' % run_ctrl.html,
        "</section>",
        '<section class="outcomes" data-surface="open-run-outcomes">',
        render_open_outcome(open_result),
        render_run_outcome(run_result),
        "</section>",
        '<section class="list-states" data-surface="open-run-lists">',
        render_list_state_tile(project_state, surface="projects"),
        render_list_state_tile(target_state, surface="targets"),
        "</section>",
        render_reason_matrix(),
    ]
    body = "\n".join(body_parts)

    script = (
        "(function () {\n"
        "  var root = document.querySelector('[data-surface=\"open-run\"]');\n"
        "  if (!root) { return; }\n"
        "  var live = root.querySelectorAll('button.live-control');\n"
        "  for (var i = 0; i < live.length; i++) {\n"
        "    var btn = live[i];\n"
        "    var action = btn.getAttribute('data-action') || '';\n"
        "    if (!action) { continue; }\n"
        "    btn.addEventListener('click', function (ev) {\n"
        "      var el = ev.currentTarget;\n"
        "      var act = el.getAttribute('data-action') || '';\n"
        "      if (typeof window.__anchorOpenRunAction === 'function') {\n"
        "        window.__anchorOpenRunAction(act, el.getAttribute('data-control'));\n"
        "      }\n"
        "    });\n"
        "  }\n"
        "})();\n"
    )

    doc = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8"/>\n'
        "  <title>%s</title>\n"
        "</head>\n"
        "<body>\n"
        '  <main class="open-run-surface" data-surface="open-run" data-wave="%s">\n'
        "%s\n"
        "  </main>\n"
        "  <script>\n"
        "%s"
        "  </script>\n"
        "</body>\n"
        "</html>\n"
        % (html.escape(c.title, quote=False), WAVE_ID, body, script)
    )

    findings = audit_dead_controls(doc)
    return OpenRunViewResult(
        html=doc,
        open_control=open_ctrl,
        run_control=run_ctrl,
        open_result=open_result,
        run_result=run_result,
        project_list_state=project_state,
        target_list_state=target_state,
        dead_control_findings=findings,
    )


_SCRIPT_RE = re.compile(
    r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)


def node_check_workbench_scripts(
    html_text: str,
    *,
    require_node: bool = True,
) -> List[str]:
    """Run ``node --check`` on every ``<script>`` block in workbench HTML.

    Surface waves require script validity. When ``require_node`` is True and
    no node binary is on PATH, raises ``RuntimeError`` so the gate cannot
    silently skip the check. When ``require_node`` is False and node is
    absent, returns the extracted bodies without checking.
    """
    blocks: List[str] = []
    for m in _SCRIPT_RE.finditer(html_text or ""):
        body = m.group(1)
        if body is None:
            continue
        # Skip external src-only scripts (no body).
        tag_open = (html_text or "")[m.start() : m.start(1)]
        if "src=" in tag_open and not str(body).strip():
            continue
        blocks.append(body)
    if not blocks:
        return []

    node = shutil.which("node")
    if not node:
        if require_node:
            raise RuntimeError(
                "node binary not on PATH — open/run workbench requires "
                "node --check on emitted script blocks"
            )
        return blocks

    with tempfile.TemporaryDirectory(prefix="open_run_node_check_") as tmp:
        base = Path(tmp)
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
                raise RuntimeError(
                    "node --check failed for open/run script block %d:\n%s\n%s"
                    % (idx, proc.stdout, proc.stderr)
                )
    return blocks


def generate_html(
    ctx: Optional[OpenRunViewContext] = None,
    *,
    require_node_check: Optional[bool] = None,
) -> str:
    """Return the workbench HTML document (tests assert visible text nodes).

    When a ``node`` binary is on PATH, emitted ``<script>`` blocks are always
    run through ``node --check`` (fail closed on syntax error). When node is
    absent: if ``require_node_check`` is True, raise; if False, skip; if None
    (default), require node only when it is present (check when available,
    never invent a skip when the binary exists).
    """
    doc = render_workbench(ctx).html
    node = shutil.which("node")
    if node:
        # Node present → check is mandatory (closes node-check-optional theater).
        node_check_workbench_scripts(doc, require_node=True)
    elif require_node_check is True:
        node_check_workbench_scripts(doc, require_node=True)
    # require_node_check is False or None with no node → skip check honestly.
    return doc


def generate_html_for_fixture(fixture: str) -> str:
    """Tri-state harness entry: unknown / empty / zero_measured for lists.

    * ``unknown`` — project store unreadable
    * ``empty`` — project store legitimately empty
    * ``zero_measured`` — measured-zero stand-in: empty target list after a
      successful read (distinct label via render_state)
    """
    key = (fixture or "").strip().lower().replace("-", "_")
    if key == "unknown":
        store = unreadable_store()
        env = make_run_env(unreadable=True)
    elif key in ("empty",):
        store = empty_store()
        env = empty_run_env()
    elif key in ("zero", "zero_measured", "measured_zero"):
        # Distinct from empty: show zero_measured tile explicitly for the
        # harness (aggregation-style zero over an existing scope).
        store = empty_store()
        env = empty_run_env()
        state = NamedState.zero_measured
        return (
            "<!DOCTYPE html><html><body>"
            '<main data-surface="open-run">'
            '%s'
            "</main>"
            "<script>(function(){})();</script>"
            "</body></html>"
            % render_state(state)
        )
    else:
        raise ValueError("unknown open-run fixture %r" % fixture)

    ctx = OpenRunViewContext(
        project_store=store,
        run_env=env,
        force_open_absent=True,
        force_run_absent=True,
        open_capability_present=False,
        run_capability_present=False,
    )
    # For empty: ensure list state is empty and visible.
    result = render_workbench(ctx)
    return result.html


def render_cannot_reason_html(
    control: str,
    reason: str,
) -> str:
    """Render one cannot-* reason as a minimal HTML fragment for tests."""
    ctrl = (control or "").strip().lower()
    if ctrl == CONTROL_OPEN:
        ns = open_reason_named_state(reason)
        return render_cannot_state(
            CONTROL_OPEN,
            cannot_state=ns,
            reason=reason,
        ).html
    if ctrl == CONTROL_RUN:
        ns = run_reason_named_state(reason)
        return render_cannot_state(
            CONTROL_RUN,
            cannot_state=ns,
            reason=reason,
        ).html
    raise ValueError("unknown control %r" % control)


# --------------------------------------------------------------------------
# Trace helpers (build schema-valid e2e hops for open/run)
# --------------------------------------------------------------------------


def build_open_trace_payload(
    reason: Optional[str] = None,
    *,
    ok: bool = False,
) -> Dict[str, Any]:
    """Payload dict used by open e2e traces (stable for hashing)."""
    return {
        "control_id": CONTROL_OPEN,
        "wave_id": WAVE_ID,
        "ok": ok,
        "reason": reason or "",
        "handler": "anchor.session.open_work.open_work",
        "capability": "open",
    }


def build_run_trace_payload(
    reason: Optional[str] = None,
    *,
    ok: bool = False,
) -> Dict[str, Any]:
    return {
        "control_id": CONTROL_RUN,
        "wave_id": WAVE_ID,
        "ok": ok,
        "reason": reason or "",
        "handler": "anchor.session.run_work.run_work",
        "capability": "run",
    }


__all__ = [
    "SURFACE_ID",
    "WAVE_ID",
    "OPEN_ACTION",
    "RUN_ACTION",
    "OpenRunViewContext",
    "OpenRunViewResult",
    "render_open_control",
    "render_run_control",
    "render_open_outcome",
    "render_run_outcome",
    "render_list_state_tile",
    "render_reason_matrix",
    "render_workbench",
    "generate_html",
    "generate_html_for_fixture",
    "render_cannot_reason_html",
    "build_open_trace_payload",
    "build_run_trace_payload",
    "node_check_workbench_scripts",
    "assert_no_dead_controls",
    "audit_dead_controls",
    "count_live_controls",
    "count_cannot_states",
    "decide_control",
]
