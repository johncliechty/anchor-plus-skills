"""Verbatim extractor for ``_PROJECT_WINDOW_JS`` → ``static/`` (rearch W4).

C1 Extraction Increment 1 (frozen plan: ``IMPLEMENTATION-PLAN.md``, W4) moves
the census-confirmed ZERO-interpolation ``_PROJECT_WINDOW_JS`` raw string to a
static file — ``static/project-window.js`` — served by the existing
traversal-safe asset-route idiom behind the byte-parity gate.

This module is the ONE mechanical bridge between the two copies:

* :func:`extracted_js` locates the ``_PROJECT_WINDOW_JS`` assignment through
  the W1 structural anchors (:mod:`tools.anchors` — stale/ambiguous anchors
  refuse loudly, exactly like the census) and returns the string value
  VERBATIM. It refuses anything that is not a plain string constant, so the
  extraction can never silently ship a mutated body.
* :func:`write_project_window_js` mints/refreshes the checked-in static file
  from that value — written as raw UTF-8 BYTES (LF newlines, no platform
  translation) so the byte-parity gate's byte-for-byte diff is meaningful.
  Like ``pillar_flags.write_matrix_doc`` / the W1 census artifacts, the file
  is a MECHANICAL artifact: the W4 gate refreshes it and fails on drift; it
  is never hand-edited. Until W6 removes the embedded blob, the raw string
  in ``anchor_gui.py`` remains the single source of truth and this file is
  its derived, byte-identical mirror.

Stdlib only (``ast`` via :mod:`tools.anchors`, ``pathlib``).
CLI: ``python tools/extract_project_window_js.py [--check]``.
"""

from __future__ import annotations

import ast
from pathlib import Path

from tools.anchors import REPO_ROOT, locate_anchor_nodes

STATIC_DIR = REPO_ROOT / "static"
PROJECT_WINDOW_JS_NAME = "project-window.js"
DEFAULT_OUT = STATIC_DIR / PROJECT_WINDOW_JS_NAME


class ExtractionError(RuntimeError):
    """``_PROJECT_WINDOW_JS`` is no longer a plain string constant — the
    verbatim move is not safe and the extractor refuses (never guesses)."""


def extracted_js(source=None, path=None) -> str:
    """The VERBATIM ``_PROJECT_WINDOW_JS`` string value from the source.

    Located through the W1 anchor-freshness gate (``AnchorError`` propagates
    on a stale/ambiguous anchor). Raises :class:`ExtractionError` unless the
    assignment value is a plain string constant — the same zero-interpolation
    contract the census enforces.
    """
    _source_text, structural = locate_anchor_nodes(source=source, path=path)
    value = structural["project_window_js_assign"]["node"].value
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return value.value  # pre-extraction: the in-source raw string is the source of truth
    if isinstance(value, ast.Call):
        # C1 COMPLETE (2026-07-05): W6 removed the embedded blob — the constant now
        # loads its verbatim body from static/project-window.js via read_text(), so
        # the CHECKED-IN STATIC FILE is now the source of truth (exactly the handoff
        # the W4 docstring anticipated). Return its bytes; re-mint is a no-op.
        return DEFAULT_OUT.read_text(encoding="utf-8")
    raise ExtractionError(
        "_PROJECT_WINDOW_JS is neither a plain string constant nor an extraction "
        "read_text() load — the W4 verbatim extraction cannot classify it."
    )


def write_project_window_js(out_path=None, source=None, path=None) -> Path:
    """Mint/refresh ``static/project-window.js`` from the source string.

    Written as raw UTF-8 bytes (no newline translation — byte parity is the
    W4 gate), skipping an unchanged rewrite so gate re-runs are no-ops.
    Returns the path written.
    """
    out = Path(out_path) if out_path is not None else DEFAULT_OUT
    out.parent.mkdir(parents=True, exist_ok=True)
    data = extracted_js(source=source, path=path).encode("utf-8")
    try:
        if out.exists() and out.read_bytes() == data:
            return out
    except OSError:
        pass
    out.write_bytes(data)
    return out


def main(argv=None):  # pragma: no cover - thin CLI shim
    import sys as _sys

    argv = list(_sys.argv[1:] if argv is None else argv)
    if "--check" in argv:
        data = extracted_js().encode("utf-8")
        if DEFAULT_OUT.exists() and DEFAULT_OUT.read_bytes() == data:
            print(f"OK: {DEFAULT_OUT} is byte-identical to "
                  f"_PROJECT_WINDOW_JS ({len(data)} bytes)")
            return 0
        print(f"DRIFT: {DEFAULT_OUT} does not match _PROJECT_WINDOW_JS "
              f"— re-mint via write_project_window_js()", file=_sys.stderr)
        return 1
    print(f"wrote {write_project_window_js()}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
