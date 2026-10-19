"""Shared Playwright UI helpers for the project-window suites.

DEV-ONLY (like every Playwright asset here): never imported by product code.
"""


def expand_workbench(pg):
    """Expand the project window's Workbench tile.

    (2026-07-30) The tile now opens COLLAPSED — a project window lands on the
    chamber + summary rather than a wall of lanes, and the summary carries a
    click-to-expand / click-to-collapse affordance. Every flow that drives the
    lane board, the session bar, or the panel stack therefore has to make the
    same one click a user makes before those elements are visible.

    Idempotent and defensive: a no-op when the tile is already open, absent
    (an older shell / a non-project page), or when the click cannot land.
    """
    try:
        if pg.query_selector("#tile-workbench") is None:
            return
        already = pg.evaluate(
            "()=>{var t=document.getElementById('tile-workbench');"
            "return !!(t&&t.open);}")
        if already:
            return
        pg.click("#tile-workbench > summary")
        pg.wait_for_selector("#tile-workbench[open]", timeout=5000)
    except Exception:
        pass
