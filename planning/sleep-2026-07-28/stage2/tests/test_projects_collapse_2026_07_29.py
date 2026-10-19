"""W19 — Projects collapsed by default + remembered preference (dual-profile).

Exercises every W19 deliverable under one scoped gate:

* ``anchor/ui/projects_tree.py``
* ``static/js/projects_tree.js``
* ``artifacts/root-cause-projects-collapse.md``
* ``artifacts/failure-states/projects-collapse.md``

Gate: pytest -v tests/test_projects_collapse_2026_07_29.py

GWTs (frozen plan):

* First-ever load for profile A → all folders collapsed; node --check passes
  on the tree script block.
* Profile A expands two folders and profile B expands none → each reload
  restores that profile's state — no cross-profile bleed.
* Preference store unreadable → fallback collapsed + named unknown preference
  (never silent user choice).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from anchor.ui.named_state import NamedState
from anchor.ui.projects_tree import (
    COLLAPSED_CLASS,
    CONTROL_ID,
    DUAL_PROFILES,
    FOLDER_CLASS,
    JS_RELPATH_POSIX,
    PREFERENCE_KEY,
    PROFILE_A,
    PROFILE_B,
    SURFACE_ID,
    WAVE_ID,
    CollapsePreference,
    InMemoryPreferenceStore,
    PathPreferenceStore,
    ProjectFolder,
    ProjectList,
    ProjectsTreeContext,
    assert_all_folders_collapsed,
    dual_profile_fixture_store,
    empty_project_list,
    expand_folders_for_profile,
    folder_collapsed_map,
    generate_html,
    generate_html_for_fixture,
    load_preference,
    make_preference_store,
    node_check_projects_tree_scripts,
    reload_after_expand,
    render_for_profile,
    render_projects_tree,
    sample_project_list,
    save_preference,
    static_tree_script_path,
    unreadable_project_list,
)
from tests.conformance.html_assert import (
    assert_visible_text_contains,
    node_check_scripts,
    visible_text_nodes,
)
from tests.conformance.table_validator import validate_failure_state_table
from tests.conformance.tri_state import assert_tri_state

CONTAINMENT_ROOT = Path(__file__).resolve().parents[1]
FAILURE_TABLE_PATH = (
    CONTAINMENT_ROOT / "artifacts" / "failure-states" / "projects-collapse.md"
)
ROOT_CAUSE_PATH = (
    CONTAINMENT_ROOT / "artifacts" / "root-cause-projects-collapse.md"
)
STATIC_JS_PATH = CONTAINMENT_ROOT / "static" / "js" / "projects_tree.js"


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------


def _parse_failure_table(text: str) -> list:
    rows = []
    in_table = False
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("| hardening"):
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 4:
                continue
            if cells[0] in ("hardening",):
                continue
            rows.append(
                {
                    "hardening": cells[0],
                    "state": cells[1],
                    "user_visible": cells[2],
                    "trigger": cells[3],
                }
            )
        elif in_table and not line.startswith("|"):
            break
    return rows


def _pref_panel(html: str) -> str:
    m = re.search(
        r'<div class="projects-preference"[^>]*>.*?</div>',
        html,
        re.DOTALL,
    )
    return m.group(0) if m else html


def _list_panel(html: str) -> str:
    m = re.search(
        r'<div class="projects-list"[^>]*>.*?</div>\s*(?=<section|</main|$)',
        html,
        re.DOTALL,
    )
    return m.group(0) if m else html


# --------------------------------------------------------------------------
# Acceptance: modules + artifacts present
# --------------------------------------------------------------------------


def test_w19_modules_importable_and_callable():
    assert WAVE_ID == "W19"
    assert SURFACE_ID == "projects_collapse"
    assert CONTROL_ID == "projects_collapse"
    assert PROFILE_A == "profile_A"
    assert PROFILE_B == "profile_B"
    assert set(DUAL_PROFILES) == {PROFILE_A, PROFILE_B}
    assert PREFERENCE_KEY == "projects.collapse.v1"
    assert callable(generate_html)
    assert callable(generate_html_for_fixture)
    assert callable(render_projects_tree)
    assert callable(reload_after_expand)
    assert callable(node_check_projects_tree_scripts)
    assert callable(assert_all_folders_collapsed)
    assert STATIC_JS_PATH.is_file()
    assert static_tree_script_path().is_file()
    assert ROOT_CAUSE_PATH.is_file()
    assert FAILURE_TABLE_PATH.is_file()


def test_root_cause_names_real_defect_and_fix_path():
    text = ROOT_CAUSE_PATH.read_text(encoding="utf-8")
    assert "C:\\Users" not in text
    assert "/Users/" not in text
    low = text.lower()
    assert "absent" in low
    assert "projects_tree.js" in text or "static/js/projects_tree.js" in text
    assert "collapsed" in low
    assert "preference" in low
    assert "projects_tree.py" in text or "anchor/ui/projects_tree" in text
    # Must name the real mechanism, not a vague "styling" only claim.
    assert "first-paint" in low or "first paint" in low or "server-rendered" in low


# --------------------------------------------------------------------------
# GWT: first-ever load — all folders collapsed
# --------------------------------------------------------------------------


def test_first_load_all_folders_collapsed_class():
    """GWT: first-ever load → rendered HTML shows all folders collapsed."""
    ctx = ProjectsTreeContext(
        profile_id=PROFILE_A,
        projects=sample_project_list(),
        preference_store=InMemoryPreferenceStore(),
    )
    result = render_projects_tree(ctx)
    html = result.html
    n = assert_all_folders_collapsed(html)
    assert n == 3
    assert result.projects_named_state is NamedState.ok
    assert result.preference_named_state is NamedState.ok
    assert set(result.collapsed_folder_ids()) == {
        "folder-alpha",
        "folder-beta",
        "folder-gamma",
    }
    assert result.expanded_folder_ids() == []
    # class collapsed present on each folder tag
    for tag in re.findall(
        r'<div class="[^"]*\bproject-folder\b[^"]*"[^>]*>', html
    ):
        assert COLLAPSED_CLASS in tag
        assert 'data-collapsed="true"' in tag


def test_generate_html_first_load_collapsed():
    html = generate_html(
        ProjectsTreeContext(
            profile_id=PROFILE_A,
            projects=sample_project_list(),
            preference_store=InMemoryPreferenceStore(),
        )
    )
    assert_all_folders_collapsed(html)
    assert 'data-surface="projects_collapse"' in html
    assert 'data-wave="W19"' in html
    assert JS_RELPATH_POSIX in html or "projects_tree.js" in html


# --------------------------------------------------------------------------
# GWT: dual-profile persistence — no cross-profile bleed
# --------------------------------------------------------------------------


def test_dual_profile_persistence_no_bleed():
    """GWT: A expands two, B expands none → reload restores each; no bleed."""
    store = InMemoryPreferenceStore()
    projects = sample_project_list()

    # Profile A expands alpha + gamma.
    a_after = reload_after_expand(
        store,
        PROFILE_A,
        ["folder-alpha", "folder-gamma"],
        projects=projects,
    )
    a_map = folder_collapsed_map(a_after.html)
    assert a_map["folder-alpha"] is False
    assert a_map["folder-gamma"] is False
    assert a_map["folder-beta"] is True
    assert set(a_after.expanded_folder_ids()) == {
        "folder-alpha",
        "folder-gamma",
    }

    # Profile B expands none (default / empty preference).
    b_after = render_for_profile(
        PROFILE_B, store=store, projects=projects
    )
    b_map = folder_collapsed_map(b_after.html)
    assert b_map["folder-alpha"] is True
    assert b_map["folder-beta"] is True
    assert b_map["folder-gamma"] is True
    assert b_after.expanded_folder_ids() == []

    # Re-load profile A — still has its two expanded (no bleed from B).
    a_reload = render_for_profile(
        PROFILE_A, store=store, projects=projects
    )
    a2 = folder_collapsed_map(a_reload.html)
    assert a2["folder-alpha"] is False
    assert a2["folder-gamma"] is False
    assert a2["folder-beta"] is True

    # Store isolation: profile keys independent.
    pref_a = load_preference(store, PROFILE_A)
    pref_b = load_preference(store, PROFILE_B)
    assert set(pref_a.expanded) == {"folder-alpha", "folder-gamma"}
    assert pref_b.expanded == []
    assert pref_a.named_state is NamedState.ok
    assert pref_b.named_state is NamedState.ok


def test_dual_profile_fixture_helper():
    store = dual_profile_fixture_store(
        profile_a_expanded=["folder-beta"],
        profile_b_expanded=[],
    )
    a = render_for_profile(PROFILE_A, store=store)
    b = render_for_profile(PROFILE_B, store=store)
    assert folder_collapsed_map(a.html)["folder-beta"] is False
    assert folder_collapsed_map(a.html)["folder-alpha"] is True
    assert_all_folders_collapsed(b.html)


def test_path_preference_store_roundtrip(tmp_path: Path):
    path = tmp_path / "prefs.json"
    store = PathPreferenceStore(path)
    save_preference(store, PROFILE_A, ["folder-alpha"])
    save_preference(store, PROFILE_B, [])
    a = load_preference(store, PROFILE_A)
    b = load_preference(store, PROFILE_B)
    assert a.expanded == ["folder-alpha"]
    assert b.expanded == []
    # Reload via path store after re-open.
    store2 = PathPreferenceStore(path)
    a2 = load_preference(store2, PROFILE_A)
    assert a2.expanded == ["folder-alpha"]


# --------------------------------------------------------------------------
# GWT: unreadable preference store → collapsed + unknown
# --------------------------------------------------------------------------


def test_unreadable_preference_store_collapsed_and_unknown():
    """GWT: preference store unreadable → collapsed + named unknown preference."""
    store = InMemoryPreferenceStore(unreadable=True)
    # Even if we try to "remember" expands, load path is unknown.
    result = render_for_profile(
        PROFILE_A,
        store=store,
        projects=sample_project_list(),
    )
    assert result.preference_named_state is NamedState.unknown
    assert result.preference.readable is False
    assert result.preference.reason == "preference_store_unreadable"
    assert_all_folders_collapsed(result.html)
    pref = _pref_panel(result.html)
    assert_visible_text_contains(pref, "unknown")
    assert 'data-named-state="unknown"' in pref
    assert "preference store unreadable" in pref
    # Must not look like an empty project list.
    assert result.projects_named_state is NamedState.ok
    assert 'data-named-state="empty"' not in pref


def test_force_preference_unreadable_flag():
    result = render_projects_tree(
        ProjectsTreeContext(
            profile_id=PROFILE_A,
            projects=sample_project_list(),
            force_preference_unreadable=True,
        )
    )
    assert result.preference_named_state is NamedState.unknown
    assert_all_folders_collapsed(result.html)
    pref = _pref_panel(result.html)
    assert_visible_text_contains(pref, "unknown")
    assert "preference store unreadable" in pref
    assert "preference store unreadable" in result.html


def test_path_store_unreadable_file(tmp_path: Path):
    bad = tmp_path / "broken.json"
    bad.write_text("{not-json", encoding="utf-8")
    store = PathPreferenceStore(bad)
    pref = load_preference(store, PROFILE_A)
    assert pref.named_state is NamedState.unknown
    assert pref.readable is False
    result = render_for_profile(
        PROFILE_A, store=store, projects=sample_project_list()
    )
    assert_all_folders_collapsed(result.html)
    assert result.preference_named_state is NamedState.unknown


def test_make_preference_store_dict_and_unreadable():
    store = make_preference_store({"profile_A": {"key": PREFERENCE_KEY, "expanded": ["folder-beta"]}})
    pref = load_preference(store, PROFILE_A)
    assert pref.expanded == ["folder-beta"]
    bad = make_preference_store(unreadable=True)
    pref2 = load_preference(bad, PROFILE_A)
    assert pref2.named_state is NamedState.unknown


# --------------------------------------------------------------------------
# Empty project list ≠ unknown (list unreadable)
# --------------------------------------------------------------------------


def test_empty_project_list_is_empty_not_unknown():
    result = render_projects_tree(
        ProjectsTreeContext(
            profile_id=PROFILE_A,
            projects=empty_project_list(),
            preference_store=InMemoryPreferenceStore(),
        )
    )
    assert result.projects_named_state is NamedState.empty
    assert result.projects_named_state is not NamedState.unknown
    panel = _list_panel(result.html)
    assert_visible_text_contains(panel, "empty")
    assert "no projects" in panel
    assert 'data-named-state="empty"' in panel
    assert 'data-named-state="unknown"' not in panel


def test_unreadable_project_list_is_unknown_not_empty():
    result = render_projects_tree(
        ProjectsTreeContext(
            profile_id=PROFILE_A,
            projects=unreadable_project_list(),
            preference_store=InMemoryPreferenceStore(),
        )
    )
    assert result.projects_named_state is NamedState.unknown
    panel = _list_panel(result.html)
    assert_visible_text_contains(panel, "unknown")
    assert "could not be read" in panel
    assert "no projects" not in panel
    assert 'data-named-state="unknown"' in panel
    assert 'data-named-state="empty"' not in panel


def test_empty_and_unknown_list_distinct_visible():
    empty_html = generate_html(
        ProjectsTreeContext(
            projects=empty_project_list(),
            preference_store=InMemoryPreferenceStore(),
        )
    )
    unknown_html = generate_html(
        ProjectsTreeContext(
            projects=unreadable_project_list(),
            preference_store=InMemoryPreferenceStore(),
        )
    )
    e = _list_panel(empty_html)
    u = _list_panel(unknown_html)
    assert_visible_text_contains(e, "empty")
    assert_visible_text_contains(u, "unknown")
    assert 'data-named-state="empty"' in e
    assert 'data-named-state="unknown"' in u
    assert 'data-named-state="empty"' not in u
    assert 'data-named-state="unknown"' not in e


# --------------------------------------------------------------------------
# Stale preference key ignored
# --------------------------------------------------------------------------


def test_stale_preference_key_ignored_defaults_collapsed():
    store = InMemoryPreferenceStore(
        {
            PROFILE_A: {
                "key": "projects.collapse.v0",
                "expanded": ["folder-alpha", "folder-beta", "folder-gamma"],
            }
        }
    )
    pref = load_preference(store, PROFILE_A)
    assert pref.stale_key is True
    assert pref.expanded == []
    assert pref.named_state is NamedState.ok
    result = render_for_profile(PROFILE_A, store=store)
    assert_all_folders_collapsed(result.html)


# --------------------------------------------------------------------------
# node --check on tree script
# --------------------------------------------------------------------------


def test_node_check_tree_script_block():
    """GWT: node --check passes on the tree script block."""
    html = generate_html(
        ProjectsTreeContext(
            profile_id=PROFILE_A,
            projects=sample_project_list(),
            preference_store=InMemoryPreferenceStore(),
        )
    )
    blocks = node_check_projects_tree_scripts(html, require_node=True)
    assert isinstance(blocks, list)
    assert len(blocks) >= 1
    # Static file content is among checked bodies (real JS path).
    static_body = STATIC_JS_PATH.read_text(encoding="utf-8")
    assert any(
        "initProjectsTree" in b or "AnchorProjectsTree" in b for b in blocks
    )
    assert "collapsed" in static_body
    assert PREFERENCE_KEY in static_body or "projects.collapse.v1" in static_body
    # Shared conformance helper also accepts the document.
    node_check_scripts(html)


def test_static_js_is_real_collapse_path():
    body = STATIC_JS_PATH.read_text(encoding="utf-8")
    assert "C:\\Users" not in body
    assert FOLDER_CLASS in body or "project-folder" in body
    assert COLLAPSED_CLASS in body
    assert "initProjectsTree" in body
    assert "data-collapsed" in body or "collapsed" in body


# --------------------------------------------------------------------------
# Tri-state + failure-state table
# --------------------------------------------------------------------------


def test_projects_collapse_tri_state_conformance():
    assert_tri_state(
        generate_html_for_fixture,
        call_site="anchor.ui.projects_tree.generate_html_for_fixture",
    )


def test_failure_state_table_exists_unknown_empty_separate():
    assert FAILURE_TABLE_PATH.is_file()
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    assert "C:\\Users" not in text
    assert "/Users/" not in text
    rows = _parse_failure_table(text)
    assert rows, "projects-collapse.md machine table produced no rows"
    states = {r["state"] for r in rows}
    assert "unknown" in states
    assert "empty" in states
    assert "unknown/empty" not in text.lower().replace(" ", "")
    report = validate_failure_state_table(rows, surface="projects_collapse")
    assert report["ok"] is True


def test_failure_state_table_surface_native_projects_language():
    text = FAILURE_TABLE_PATH.read_text(encoding="utf-8")
    low = text.lower()
    assert "project" in low
    assert "collapse" in low or "preference" in low
    head = low.split("## enumerated")[0]
    for verb in ("index", "rebuild", "reconcile"):
        assert not re.search(r"\b%s\b" % verb, head)


# --------------------------------------------------------------------------
# Structural HTML shape
# --------------------------------------------------------------------------


def test_render_includes_preference_key_and_profile():
    html = generate_html(
        ProjectsTreeContext(
            profile_id=PROFILE_A,
            projects=sample_project_list(),
        )
    )
    assert PREFERENCE_KEY in html
    assert 'data-profile="profile_A"' in html
    assert CONTROL_ID in html or "projects_collapse" in html
    nodes = visible_text_nodes(html)
    assert nodes or "ok" in html


def test_custom_project_list_renders_labels():
    projects = ProjectList(
        folders=[
            ProjectFolder("f1", "One"),
            ProjectFolder("f2", "Two"),
        ]
    )
    result = render_projects_tree(
        ProjectsTreeContext(
            profile_id=PROFILE_B,
            projects=projects,
            preference_store=InMemoryPreferenceStore(),
        )
    )
    assert "One" in result.html
    assert "Two" in result.html
    assert_all_folders_collapsed(result.html)
    n = assert_all_folders_collapsed(result.html)
    assert n == 2


def test_expand_folders_for_profile_api():
    store = InMemoryPreferenceStore()
    pref = expand_folders_for_profile(store, PROFILE_A, ["folder-beta"])
    assert isinstance(pref, CollapsePreference)
    assert pref.expanded == ["folder-beta"]
    loaded = load_preference(store, PROFILE_A)
    assert loaded.expanded == ["folder-beta"]


def test_preference_unknown_fixture():
    html = generate_html_for_fixture("preference_unknown")
    assert_all_folders_collapsed(html)
    pref = _pref_panel(html)
    assert_visible_text_contains(pref, "unknown")
