"""Re-architecture ground-truth tooling (W1 — census · anchors · tripwire).

Stdlib-only helper package for the 2026-07 Anchor re-architecture effort.
These are BUILD/GATE tools, not product runtime code: nothing in the product
imports this package unconditionally (the healthcheck/conftest hooks import it
only behind the ``ANCHOR_WRITE_TRIPWIRE`` env seam, best-effort).
"""
