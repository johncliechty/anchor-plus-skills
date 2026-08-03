"""Wave 8 — clean main-dashboard rows + cost rollup + Option B branding.

Covers the Wave 8 contract (IMPLEMENTATION-PLAN lines 190-208):
  - The R&D project view renders a FLAT one-line ROW list with NO per-folder
    directory/path header line (the old ``rnd-folder``/``rnd-folder-head``
    grouping markup is gone — the path now lives on the project-window header).
  - Each row shows a cost/tokens/time rollup (``Σ ... tok · $... · ...``) and the
    R&D view carries a single global lifetime/30-day toggle hook.
  - The main dashboard masthead renders the Option B lockup: the Anchor title, a
    vertical divider, the GWL mark + "Ghost World Labs" wordmark, and a "Powered
    by NextGen Nuclear ☢" pill.
  - Every brand-mark ``<img>`` references the SINGLE vendored
    ``/vendor/brand/gwl-m-icon.svg`` (no second asset).

Hermetic: temp ANCHOR_DATA_DIR + reload, no live claude, no network.
"""
import importlib
import re

import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(tmp_path))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    import paths
    importlib.reload(paths)
    paths.ensure_data_dirs()
    import rnd_registry
    importlib.reload(rnd_registry)
    import effort_history
    importlib.reload(effort_history)
    import sessions
    importlib.reload(sessions)
    import anchor_gui
    importlib.reload(anchor_gui)
    return anchor_gui, rnd_registry, effort_history, sessions


# ── (a) flat rows, NO directory/path header line ─────────────────────────────

def test_view_renders_flat_rows_no_folder_header(env, tmp_path):
    """v9 Wave 3: three UNGROUPED projects render as thin rows nested under the
    single collapsible "Ungrouped" folder (the v9 folders replace the v8 flat
    list, but each row keeps its thin one-line form)."""
    gui, rnd, eh, _sess = env
    for i in range(3):
        folder = tmp_path / f"proj{i}"
        folder.mkdir()
        rnd.add_project(f"P{i}", str(folder))

    view = gui.render_projects_view_html()
    # Thin rows still present, one per project.
    assert "rnd-row" in view
    assert view.count('data-project-id="') == 3
    # v9: ungrouped projects live under a single "Ungrouped" collapsible folder
    # (NOT a per-on-disk-folder header — three distinct folders, but one group).
    assert 'class="rnd-folder"' in view
    assert "rnd-folder-head" in view
    assert "Ungrouped" in view
    # Exactly ONE folder (Ungrouped) — distinct on-disk dirs do NOT split groups.
    assert view.count('class="rnd-folder"') == 1
    # The old per-folder COUNT-class header is still gone.
    assert "rnd-folder-count" not in view


def test_no_directory_text_on_rows(env, tmp_path):
    """A single ungrouped project's on-disk dir is NOT shown anywhere: not on the
    thin project ROW, and not on the Ungrouped folder header (the catch-all
    bucket suppresses its path block)."""
    gui, rnd, eh, _sess = env
    folder = tmp_path / "a-distinctive-folder-name"
    folder.mkdir()
    rnd.add_project("RowProj", str(folder))
    view = gui.render_projects_view_html()
    assert "a-distinctive-folder-name" not in view


# ── (b) per-row rollup + the lifetime/30d toggle hook ────────────────────────

def test_row_shows_rollup(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("RollProj", str(folder))["id"]
    row = gui.render_project_tile_html(rnd.get_project(pid))
    # The per-row rollup element is present, carrying the pid for the toggle.
    assert "rnd-row-roll" in row
    assert f'data-pid="{pid}"' in row
    # With no run sessions yet it still renders the zeroed Σ rollup text
    # (run-only totals; never fabricated, but the Σ scaffold is shown).
    assert "&#931;" in row or "Σ" in row or "tok" in row


def test_row_rollup_reflects_run_costs(env, tmp_path):
    """A RUN session with cost records surfaces real totals in the row rollup
    (reusing the Wave-3 project_effort_rollup, not a recompute)."""
    gui, rnd, eh, sessions = env
    folder = tmp_path / "proj"
    folder.mkdir()
    pid = rnd.add_project("RollProj", str(folder))["id"]
    # Record a real run effort carrying a cost record.
    eh.record_effort(folder, pid, "build", "job-1", skill="foreman",
                     extra={"cost": {"total_tokens": 12000,
                                     "total_cost_usd": 1.25,
                                     "duration_ms": 65000}})
    roll = eh.project_effort_rollup(pid, window=eh.WINDOW_LIFETIME)
    expected = gui._fmt_rollup_line(roll)
    row = gui.render_project_tile_html(rnd.get_project(pid))
    # The row's rollup text equals the shared formatter's output (no fork).
    import html as _html
    assert _html.escape(expected) in row
    assert "12k tok" in row  # 12000 tokens → "12k tok"


def test_view_has_global_window_toggle(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    rnd.add_project("RollProj", str(folder))
    view = gui.render_projects_view_html()
    # A single global lifetime/30-day toggle hook for the rows.
    assert "rnd-rows-rolltog" in view
    assert 'data-window="lifetime"' in view
    assert 'data-window="30d"' in view
    assert "rndRowsRollupWindow(" in view


def test_toggle_js_present_in_home_page(env):
    """The toggle's JS handler is shipped on the served home page (re-fetches
    the read-only /api/rnd/project_rollup for the chosen window)."""
    gui, rnd, eh, _sess = env
    html = gui.generate_html(*gui.gather_all())
    assert "function rndRowsRollupWindow(" in html
    assert "/api/rnd/project_rollup?pid=" in html


# ── (c) Option B masthead lockup ─────────────────────────────────────────────

def test_masthead_renders_option_b_lockup(env):
    gui, rnd, eh, _sess = env
    html = gui.generate_html(*gui.gather_all())
    # The masthead container + its Option B parts.
    assert 'class="masthead"' in html
    assert "mh-title" in html          # Anchor title
    assert "mh-vdiv" in html           # vertical divider
    assert "mh-lock" in html           # GWL mark + wordmark lockup
    assert "mh-pill" in html           # NextGen Nuclear pill (far right)
    # The Anchor title text and the GWL wordmark + green "Labs".
    assert "Anchor" in html
    assert "Ghost World" in html and "Labs" in html
    # The NextGen Nuclear credit with the radiation trefoil. It is rendered as an
    # inline SVG (green fill) rather than the ☢ emoji glyph (&#9762;) so it stays
    # green on platforms — notably iOS — that force-color the emoji presentation.
    assert "Powered by NextGen Nuclear" in html
    assert 'aria-label="radiation"' in html
    assert 'fill="#22c55e"' in html


def test_masthead_pill_is_to_the_right_of_lock(env):
    """Option B layout order: title · divider · lock · spacer · pill."""
    gui, rnd, eh, _sess = env
    html = gui.generate_html(*gui.gather_all())
    i_title = html.find("mh-title")
    i_div = html.find("mh-vdiv")
    i_lock = html.find("mh-lock")
    i_spacer = html.find("mh-spacer")
    i_pill = html.find("mh-pill")
    assert -1 < i_title < i_div < i_lock < i_spacer < i_pill


# ── (d) single vendored brand-mark source ────────────────────────────────────

def test_every_brand_img_uses_single_vendored_svg(env):
    """Every brand-mark <img> references the ONE vendored gwl-m-icon.svg — no
    second brand asset is introduced."""
    gui, rnd, eh, _sess = env
    html = gui.generate_html(*gui.gather_all())
    # Find every <img> whose alt is the GWL brand.
    imgs = re.findall(r'<img[^>]*alt="Ghost World Labs"[^>]*>', html)
    assert imgs, "expected at least one GWL brand-mark <img>"
    for tag in imgs:
        m = re.search(r'src="([^"]+)"', tag)
        assert m is not None, tag
        # Strip the ?v=cache-buster query.
        src = m.group(1).split("?", 1)[0]
        assert src == "/vendor/brand/gwl-m-icon.svg", src
    # And the masthead specifically carries one such mark.
    assert html.count('/vendor/brand/gwl-m-icon.svg') >= 1
    # The GWL brand MARK is a single vendored svg (asserted per-tag above). The
    # home page may also reference other DOCUMENTED, non-brand-mark feature icons
    # under /vendor/brand/ (e.g. the Zombie Hunter radar photo-icon, a real
    # shipped asset on disk). Allow only that documented set — a random/duplicate
    # brand asset is still forbidden.
    ALLOWED_BRAND_SRCS = {
        "/vendor/brand/gwl-m-icon.svg",
        "/vendor/brand/zombie-hunter-radar.jpg",
        # Skill Foundry v2 launch button — a real shipped feature icon on disk
        # (vendor/brand/skill-foundry-icon.jpg), the documented sibling of the
        # Zombie Hunter radar icon; not a duplicate brand MARK.
        "/vendor/brand/skill-foundry-icon.jpg",
        # Ecgberht High Seat — the seal on the first dashboard tile's summary
        # (vendor/brand/ecgberht-portfolio-high-seat.jpg), same documented
        # feature-icon class as the two above; not a duplicate brand MARK.
        "/vendor/brand/ecgberht-portfolio-high-seat.jpg",
    }
    srcs = set(
        s.split("?", 1)[0]
        for s in re.findall(r'src="(/vendor/brand/[^"]+)"', html)
    )
    assert "/vendor/brand/gwl-m-icon.svg" in srcs
    unexpected = srcs - ALLOWED_BRAND_SRCS
    assert not unexpected, "undocumented brand asset(s): %r" % (unexpected,)


def test_no_leaked_fstring_braces_in_view_and_home(env, tmp_path):
    gui, rnd, eh, _sess = env
    folder = tmp_path / "proj"
    folder.mkdir()
    rnd.add_project("P", str(folder))
    view = gui.render_projects_view_html()
    assert "{{" not in view and "}}" not in view
    html = gui.generate_html(*gui.gather_all())
    assert "{{" not in html and "}}" not in html
