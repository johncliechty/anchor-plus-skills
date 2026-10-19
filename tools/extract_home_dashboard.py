"""Mechanical home-dashboard extractor (rearch W6b).

Executes the W6a extraction map for ``generate_html``: moves the home
dashboard's CSS/JS/HTML shell out of the ``generate_html`` return f-string
into static assets served through the traversal-safe static root, exactly the
way :mod:`tools.extract_project_window_js` (W4) moved ``_PROJECT_WINDOW_JS``
and the W5 shell extractor moved the project-window shell — one level up: the
home f-string carries markup-emitting interpolations that stay SERVER-RENDERED
behind the W6a include-slot substrate (:mod:`tools.slot_renderer`).

This module is the ONE mechanical bridge. It never hand-transcribes the ~2,280
line blob: it reconstructs the return f-string from its AST and derives, BY
CONSTRUCTION, three byte-faithful pieces plus the slotted shell:

* :func:`home_artifacts` walks the DIRECT children of ``generate_html``'s
  return ``JoinedStr`` (never recursing into a nested f-string's own
  interpolations). Each literal part contributes its verbatim, already
  brace-de-escaped text; each interpolation is mapped — through the explicit,
  reviewable :data:`SLOT_NAMES` table — to a ``<!--ANCHOR:SLOT:<name>-->``
  placeholder (the W6a substrate marker). An interpolation with NO table entry
  raises :class:`ExtractionError` LOUDLY, so an under-covered map fails the
  gate rather than silently dropping server state.
* the head ``<style>…</style>`` (zero interpolations) is carved to
  ``static/home.css``; the main application ``<script>…</script>`` (whose only
  interpolations are the two ``window.ANCHOR_*`` bootstrap values + the fixed
  ``toggleAddTask`` aliases) is carved to ``static/home.js`` with the bootstrap
  values re-sourced from ``window.ANCHOR_BOOT`` and the fixed aliases baked —
  so ``home.js`` is a pure static asset, exactly like ``project-window.js``;
* the remaining shell — HTML body with its fine markup slots plus the two
  ``home_css`` / ``home_js`` block slots — is the ``static/home.html`` template
  the render fills.

Byte-parity is provable by construction: assembling the shell with the
EMBEDDED-mode slot values (``home_css`` = the inline ``<style>`` block,
``home_js`` = the inline ``<script>`` block, every fine slot = its runtime
value) via :func:`tools.slot_renderer.render_slots` reproduces the pre-wave
``generate_html`` emission byte-for-byte. STATIC mode diverges only in the
documented ``home_css`` / ``home_js`` / ANCHOR_BOOT injection blocks.

Stdlib only (``ast``, ``pathlib`` + the anchors). CLI:
``python tools/extract_home_dashboard.py [path] [--write DIR] [--check]``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tools.anchors import REPO_ROOT, locate_anchor_nodes

STATIC_DIR = REPO_ROOT / "static"
HOME_CSS_ASSET = "home.css"
HOME_JS_ASSET = "home.js"
HOME_SHELL_ASSET = "home.html"

# The two block slots that carry the whole extracted <style> / <script>.
SLOT_HOME_CSS = "home_css"
SLOT_HOME_JS = "home_js"

# The bootstrap values + the fixed alias block that live INSIDE the carved
# <script> (so they never appear as fine shell slots — they are consumed by the
# home.js carving, below).
SLOT_AUTH_REQUIRED = "auth_required_js"
SLOT_ANCHOR_BOOT = "anchor_boot_js"
SLOT_TOGGLE_FNS = "toggle_add_task_fns"

# The fixed domain order the ``toggleAddTask`` alias block is generated from
# (a module-level constant in ``anchor_gui.generate_html``; its expansion is a
# compile-time constant, so it is baked into the static ``home.js`` verbatim).
DOMAIN_ORDER = ("academic", "writing", "family", "commercial", "personal")

# ── the explicit interpolation → slot-name map ───────────────────────────────
# Every DIRECT interpolation of ``generate_html``'s return f-string, keyed by
# its whitespace-normalized source text. Reviewable and hand-consistent with
# the slots dict ``anchor_gui.generate_html`` builds in its static branch.
# An interpolation absent here raises :class:`ExtractionError` (the map must be
# provably complete — a census/source drift fails the gate, never re-baselines
# silently). Identical source text de-dupes to one slot (the value is the same,
# e.g. ``today_str`` rendered in six places).
SLOT_NAMES = {
    "BUILD_ID": "build_id",
    "len(inbox)": "inbox_count",
    "nav_items": "nav_items",
    "balance_rows": "balance_rows",
    "auth_token_btn_display": "auth_token_btn_display",
    "health_banner_html": "health_banner_html",
    "len(done_tasks)": "done_count",
    "len(cancelled_tasks)": "cancelled_count",
    "len(saved_tasks)": "saved_count",
    "render_model_flex_badge()": "model_flex_badge",
    "today_str": "today_str",
    "top_done": "top_done",
    "len(top_tasks)": "top_total",
    '"".join(top_task_row(t) for t in top_tasks)': "top_task_rows",
    "rnd_projects_html": "rnd_projects_html",
    '"".join(project_card(p) for p in p1_projects)': "p1_cards",
    'len([p for p in projects if p["status"]=="active"])': "active_projects",
    "len(active)": "open_tasks",
    '"".join(task_item(t) for t in other_tasks)': "other_task_items",
    '"".join(project_card(p) for p in p2_projects)': "p2_cards",
    "completed_items": "completed_items",
    "cancelled_items": "cancelled_items",
    "saved_items": "saved_items",
    "inbox_items": "inbox_items",
    "rnd_archive_html": "rnd_archive_html",
    "domain_views": "domain_views",
    "cache_bust_script()": "cache_bust",
    "_ORPHAN_ALERT_JS": "orphan_alert",
    # block-internal (consumed by the home.js carving; never a fine shell slot):
    "auth_required_js": SLOT_AUTH_REQUIRED,
    "anchor_boot_js": SLOT_ANCHOR_BOOT,
    '" ".join(f"function toggleAddTask_{d}() {{ toggleAddTask_(\'{d}\'); }}"'
    " for d in domain_order)": SLOT_TOGGLE_FNS,
}

# The set of fine slot names that remain in the assembled shell (i.e. NOT the
# three consumed inside the <script>, but PLUS the two block slots). Used by the
# render + the gate to assert the built slots dict matches exactly.
FINE_SLOTS = frozenset(
    v for v in SLOT_NAMES.values()
    if v not in (SLOT_AUTH_REQUIRED, SLOT_ANCHOR_BOOT, SLOT_TOGGLE_FNS)
) | {SLOT_HOME_CSS, SLOT_HOME_JS}


class ExtractionError(RuntimeError):
    """The home-dashboard extraction is not provably faithful — an
    unmapped interpolation, a missing structural landmark (``<style>`` /
    the application ``<script>`` / the bootstrap lines), or a leftover slot
    marker in a supposedly-static asset. Raised LOUDLY so a drifted source
    never silently ships a corrupted or under-covered extraction."""


def _marker(name):
    return f"<!--ANCHOR:SLOT:{name}-->"


def _norm(src):
    """Whitespace-normalize an expression's source text for table lookup."""
    return " ".join(src.split())


def _return_joinedstr(func_node, source_text):
    """The single ``return f'''…'''`` JoinedStr of ``generate_html``.

    Requires exactly one ``Return`` whose value is a ``JoinedStr`` (the home
    page emission); raises otherwise so an unexpected control-flow shape fails
    loudly instead of extracting the wrong node.
    """
    returns = [
        n for n in ast.walk(func_node)
        if isinstance(n, ast.Return) and isinstance(n.value, ast.JoinedStr)
    ]
    if len(returns) != 1:
        raise ExtractionError(
            f"generate_html must have exactly ONE f-string return; found "
            f"{len(returns)} — refusing to guess which is the page emission."
        )
    return returns[0].value


def _reconstruct_shell(joined, source_text):
    """Reconstruct the full page as a single-braced shell with slot markers.

    Iterates ONLY the direct children of the return ``JoinedStr`` (a nested
    f-string inside an interpolation is taken whole via its source segment —
    never descended, so its own ``{…}`` are not mistaken for page slots).
    """
    parts = []
    for part in joined.values:
        if isinstance(part, ast.Constant) and isinstance(part.value, str):
            parts.append(part.value)
        elif isinstance(part, ast.FormattedValue):
            if part.conversion not in (-1, None) or part.format_spec is not None:
                seg = ast.get_source_segment(source_text, part.value) or "?"
                raise ExtractionError(
                    f"interpolation {{{seg}}} uses a conversion/format spec — "
                    f"the byte-faithful extractor handles only plain {{expr}}."
                )
            seg = ast.get_source_segment(source_text, part.value)
            if seg is None:
                raise ExtractionError(
                    "could not read an interpolation's source segment.")
            name = SLOT_NAMES.get(_norm(seg))
            if name is None:
                raise ExtractionError(
                    f"UNMAPPED interpolation {{{_norm(seg)}}} in generate_html's "
                    f"return f-string — add it to SLOT_NAMES (the extraction "
                    f"map must be provably complete)."
                )
            parts.append(_marker(name))
        else:  # pragma: no cover - JoinedStr children are Constant|FormattedValue
            raise ExtractionError(
                f"unexpected f-string part {type(part).__name__}.")
    return "".join(parts)


def _baked_toggle_fns():
    """The compile-time-constant ``toggleAddTask`` alias block (verbatim)."""
    return " ".join(
        f"function toggleAddTask_{d}() {{ toggleAddTask_('{d}'); }}"
        for d in DOMAIN_ORDER
    )


def _carve(shell, open_tag, close_tag, *, after=0, landmark=None):
    """Return (start, inner_start, inner, end) for the first ``open_tag`` at/after
    ``after`` (optionally the one preceding ``landmark``) and its ``close_tag``."""
    if landmark is not None:
        lm = shell.find(landmark)
        if lm < 0:
            raise ExtractionError(f"landmark {landmark!r} not found in shell.")
        start = shell.rfind(open_tag, 0, lm)
    else:
        start = shell.find(open_tag, after)
    if start < 0:
        raise ExtractionError(f"opening {open_tag!r} not found in shell.")
    inner_start = start + len(open_tag)
    close = shell.find(close_tag, inner_start)
    if close < 0:
        raise ExtractionError(f"closing {close_tag!r} not found in shell.")
    return start, inner_start, shell[inner_start:close], close + len(close_tag)


def home_artifacts(source=None, path=None):
    """Derive every home-dashboard static artifact from the live source.

    Returns a dict with:

    * ``shell`` — ``static/home.html`` template (single-braced, fine markup
      slots + the ``home_css`` / ``home_js`` block slots);
    * ``css`` — ``static/home.css`` body (the head ``<style>`` inner text);
    * ``js`` — ``static/home.js`` body (the application ``<script>`` inner
      text, bootstrap values re-sourced from ANCHOR_BOOT, aliases baked, no
      leftover slot markers);
    * ``css_block`` / ``js_block`` — the EMBEDDED-mode values of the two block
      slots (``<style>…</style>`` / ``<script>…</script>``), for the byte-parity
      gate;
    * ``fine_slots`` — the frozenset of slot names the shell still carries.

    Propagates :class:`tools.anchors.AnchorError` on stale anchors. Raises
    :class:`ExtractionError` on any unmapped interpolation / missing landmark.
    """
    source_text, structural = locate_anchor_nodes(source=source, path=path)
    func_node = structural["generate_html_def"]["node"]
    joined = _return_joinedstr(func_node, source_text)
    full = _reconstruct_shell(joined, source_text)

    # ── carve the head <style> (zero interpolations) → home.css
    c_start, _c_inner_start, css_inner, c_end = _carve(full, "<style>", "</style>")
    if "<!--ANCHOR:SLOT:" in css_inner:
        raise ExtractionError("head <style> unexpectedly carries a slot marker.")
    css_block = full[c_start:c_end]  # <style>…</style> (embedded value)
    shell = full[:c_start] + _marker(SLOT_HOME_CSS) + full[c_end:]

    # ── carve the application <script> (the one with the heartbeat comment)
    j_start, _j_inner_start, js_inner, j_end = _carve(
        shell, "<script>", "</script>", landmark="// Heartbeat disabled")
    js_block = shell[j_start:j_end]  # <script>…</script> (embedded value)
    shell = shell[:j_start] + _marker(SLOT_HOME_JS) + shell[j_end:]

    # ── build the pure-static home.js from the carved <script> inner ──
    auth_line = f"window.ANCHOR_AUTH_REQUIRED = {_marker(SLOT_AUTH_REQUIRED)};"
    boot_line = f"window.ANCHOR_BOOT = {_marker(SLOT_ANCHOR_BOOT)};"
    for needed in (auth_line, boot_line, _marker(SLOT_TOGGLE_FNS)):
        if needed not in js_inner:
            raise ExtractionError(
                f"expected bootstrap fragment {needed!r} not found in the "
                f"application <script> — source drifted.")
    js_static = (
        js_inner
        # ANCHOR_BOOT is set by the inline bootstrap that precedes home.js.
        .replace(boot_line, "// window.ANCHOR_BOOT is set by the inline bootstrap")
        # Auth flag derived from the ANCHOR_BOOT bootstrap (server→client state).
        .replace(
            auth_line,
            "window.ANCHOR_AUTH_REQUIRED = "
            "!!(window.ANCHOR_BOOT && window.ANCHOR_BOOT.auth_required);")
        # The toggleAddTask aliases are a compile-time constant → bake verbatim.
        .replace(_marker(SLOT_TOGGLE_FNS), _baked_toggle_fns())
    )
    if "<!--ANCHOR:SLOT:" in js_static:
        raise ExtractionError(
            "static home.js still carries a slot marker — an unhandled "
            "interpolation is inside the application <script>.")

    return {
        "shell": shell,
        "css": css_inner,
        "js": js_static,
        "css_block": css_block,
        "js_block": js_block,
        "fine_slots": FINE_SLOTS,
    }


def _write_if_changed(path, data_bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.read_bytes() == data_bytes:
            return path
    except OSError:
        pass
    path.write_bytes(data_bytes)
    return path


def write_home_assets(out_dir=None, source=None, path=None):
    """Mint/refresh ``home.css`` / ``home.js`` / ``home.html`` from the source.

    Raw UTF-8 bytes (LF, no platform newline translation — byte parity is the
    gate), skipping unchanged rewrites so gate re-runs are no-ops. Returns the
    list of paths.
    """
    out = Path(out_dir) if out_dir is not None else STATIC_DIR
    art = home_artifacts(source=source, path=path)
    return [
        _write_if_changed(out / HOME_CSS_ASSET, art["css"].encode("utf-8")),
        _write_if_changed(out / HOME_JS_ASSET, art["js"].encode("utf-8")),
        _write_if_changed(out / HOME_SHELL_ASSET, art["shell"].encode("utf-8")),
    ]


def main(argv=None):  # pragma: no cover - thin CLI shim
    import argparse
    import sys as _sys

    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("path", nargs="?", default=None,
                    help="target source file (default: anchor_gui.py)")
    ap.add_argument("--write", metavar="DIR", default=None,
                    help=f"write the home static assets into DIR "
                         f"(default: {STATIC_DIR})")
    ap.add_argument("--check", action="store_true",
                    help="exit non-zero if the checked-in assets have drifted")
    args = ap.parse_args(argv)
    try:
        art = home_artifacts(path=args.path)
    except ExtractionError as e:
        print(f"EXTRACTION FAILED: {e}", file=_sys.stderr)
        return 1
    if args.write is not None:
        for p in write_home_assets(out_dir=args.write or None, path=args.path):
            print(f"wrote {p}")
    if args.check:
        out = STATIC_DIR
        drift = []
        for name, key in ((HOME_CSS_ASSET, "css"), (HOME_JS_ASSET, "js"),
                          (HOME_SHELL_ASSET, "shell")):
            p = out / name
            if not p.exists() or p.read_bytes() != art[key].encode("utf-8"):
                drift.append(name)
        if drift:
            print(f"DRIFT: {', '.join(drift)} — re-mint via write_home_assets()",
                  file=_sys.stderr)
            return 1
        print(f"OK: home static assets byte-identical "
              f"({len(art['fine_slots'])} shell slots)")
        return 0
    print(f"OK: reconstructed home shell with {len(art['fine_slots'])} slots; "
          f"css={len(art['css'])}B js={len(art['js'])}B")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
