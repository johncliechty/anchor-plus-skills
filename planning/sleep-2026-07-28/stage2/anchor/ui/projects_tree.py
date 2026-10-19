"""Projects tree — collapsed-by-default + dual-profile preference (W19).

Fixes criterion 7 at the **real** JS/CSS path (``static/js/projects_tree.js``),
not by a cosmetic CSS override. Server-rendered first paint stamps every
folder with class ``collapsed`` / ``data-collapsed="true"`` unless a readable
per-profile preference expands specific folders.

Preference store is injectable (in-memory dict or filesystem path). Profiles
``profile_A`` / ``profile_B`` are first-class dual-profile helpers. When the
preference store is unreadable the panel falls back to collapsed and shows
``NamedState.unknown`` for the preference (never a silent user choice). An
empty project list is ``NamedState.empty``, distinct from list-unreadable
``NamedState.unknown``.

``generate_html`` returns a full document with a syntax-valid ``<script>``
block suitable for ``node --check``, plus a ``src`` reference to the real
tree script path.
"""
from __future__ import annotations

import html
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import (
    Any,
    Dict,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Union,
)

from anchor.ui.named_state import NamedState, render_state

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

SURFACE_ID = "projects_collapse"
WAVE_ID = "W19"
CONTROL_ID = "projects_collapse"

PROFILE_A = "profile_A"
PROFILE_B = "profile_B"
DUAL_PROFILES: tuple = (PROFILE_A, PROFILE_B)

#: Version-stamped preference key — stale keys are ignored on load.
PREFERENCE_KEY = "projects.collapse.v1"

FOLDER_CLASS = "project-folder"
COLLAPSED_CLASS = "collapsed"
TREE_CLASS = "projects-tree"
LIST_CLASS = "projects-list"
PREF_CLASS = "projects-preference"

JS_RELPATH = os.path.join("static", "js", "projects_tree.js")
JS_RELPATH_POSIX = "static/js/projects_tree.js"

ROOT_DIR = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# Project list model
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectFolder:
    """One project folder node in the tree."""

    folder_id: str
    label: str
    children: Sequence[str] = field(default_factory=tuple)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "folder_id": self.folder_id,
            "label": self.label,
            "children": list(self.children),
        }


@dataclass
class ProjectList:
    """Project inventory for the panel.

    * ``readable=True`` + empty folders → **empty**
    * ``readable=False`` → **unknown** (list could not be read)
    * ``readable=True`` + folders → **ok**
    """

    folders: List[ProjectFolder] = field(default_factory=list)
    readable: bool = True
    reason: str = ""

    @property
    def named_state(self) -> NamedState:
        if not self.readable:
            return NamedState.unknown
        if not self.folders:
            return NamedState.empty
        return NamedState.ok

    def as_dict(self) -> Dict[str, Any]:
        return {
            "readable": self.readable,
            "reason": self.reason,
            "named_state": self.named_state.value,
            "folders": [f.as_dict() for f in self.folders],
        }


def sample_project_list() -> ProjectList:
    """Canonical multi-folder list for dual-profile tests."""
    return ProjectList(
        folders=[
            ProjectFolder("folder-alpha", "Alpha", ("a1.py", "a2.py")),
            ProjectFolder("folder-beta", "Beta", ("b1.py",)),
            ProjectFolder("folder-gamma", "Gamma", ("g1.py", "g2.py", "g3.py")),
        ],
        readable=True,
    )


def empty_project_list() -> ProjectList:
    return ProjectList(folders=[], readable=True, reason="no_projects")


def unreadable_project_list() -> ProjectList:
    return ProjectList(
        folders=[],
        readable=False,
        reason="project_list_unreadable",
    )


# --------------------------------------------------------------------------
# Preference store (injectable: dict or path)
# --------------------------------------------------------------------------


class PreferenceStoreError(RuntimeError):
    """Preference store could not be read or written."""


@dataclass
class CollapsePreference:
    """Loaded collapse preference for one profile."""

    profile_id: str
    expanded: List[str] = field(default_factory=list)
    named_state: NamedState = NamedState.ok
    preference_key: str = PREFERENCE_KEY
    readable: bool = True
    reason: str = ""
    stale_key: bool = False

    @property
    def is_unknown(self) -> bool:
        return self.named_state is NamedState.unknown or not self.readable

    def as_dict(self) -> Dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "expanded": list(self.expanded),
            "named_state": self.named_state.value,
            "preference_key": self.preference_key,
            "readable": self.readable,
            "reason": self.reason,
            "stale_key": self.stale_key,
        }


def _normalize_profile_id(profile_id: str) -> str:
    text = (profile_id or "").strip()
    if not text:
        raise ValueError("profile_id must be non-blank")
    return text


def _normalize_expanded(expanded: Optional[Sequence[str]]) -> List[str]:
    if not expanded:
        return []
    out: List[str] = []
    seen = set()
    for item in expanded:
        fid = str(item).strip()
        if not fid or fid in seen:
            continue
        seen.add(fid)
        out.append(fid)
    return out


class InMemoryPreferenceStore:
    """Dict-backed preference store (injectable for dual-profile tests)."""

    def __init__(
        self,
        data: Optional[MutableMapping[str, Any]] = None,
        *,
        unreadable: bool = False,
        write_fail: bool = False,
    ) -> None:
        self._data: MutableMapping[str, Any] = data if data is not None else {}
        self.unreadable = bool(unreadable)
        self.write_fail = bool(write_fail)

    def load(self, profile_id: str) -> CollapsePreference:
        pid = _normalize_profile_id(profile_id)
        if self.unreadable:
            return CollapsePreference(
                profile_id=pid,
                expanded=[],
                named_state=NamedState.unknown,
                readable=False,
                reason="preference_store_unreadable",
            )
        raw = self._data.get(pid)
        if raw is None:
            return CollapsePreference(
                profile_id=pid,
                expanded=[],
                named_state=NamedState.ok,
                readable=True,
                reason="no_stored_preference",
            )
        if not isinstance(raw, Mapping):
            return CollapsePreference(
                profile_id=pid,
                expanded=[],
                named_state=NamedState.unknown,
                readable=False,
                reason="preference_payload_garbage",
            )
        key = str(raw.get("key") or raw.get("preference_key") or PREFERENCE_KEY)
        if key != PREFERENCE_KEY:
            # Version stamp mismatch — ignore stale expand set (plan I31).
            return CollapsePreference(
                profile_id=pid,
                expanded=[],
                named_state=NamedState.ok,
                readable=True,
                reason="stale_preference_key",
                stale_key=True,
            )
        expanded = _normalize_expanded(raw.get("expanded") or [])
        return CollapsePreference(
            profile_id=pid,
            expanded=expanded,
            named_state=NamedState.ok,
            readable=True,
            reason="ok" if expanded else "all_collapsed",
        )

    def save(
        self,
        profile_id: str,
        expanded: Optional[Sequence[str]] = None,
    ) -> CollapsePreference:
        pid = _normalize_profile_id(profile_id)
        if self.unreadable or self.write_fail:
            raise PreferenceStoreError(
                "preference store unreadable — cannot save for profile %r" % pid
            )
        ids = _normalize_expanded(expanded)
        self._data[pid] = {
            "key": PREFERENCE_KEY,
            "expanded": ids,
            "profile_id": pid,
        }
        return CollapsePreference(
            profile_id=pid,
            expanded=ids,
            named_state=NamedState.ok,
            readable=True,
            reason="saved",
        )

    def as_dict(self) -> Dict[str, Any]:
        return dict(self._data)


class PathPreferenceStore:
    """Filesystem JSON preference store (path-injectable)."""

    def __init__(
        self,
        path: Union[str, Path],
        *,
        unreadable: bool = False,
    ) -> None:
        self.path = Path(path)
        self.unreadable = bool(unreadable)

    def _read_all(self) -> Dict[str, Any]:
        if self.unreadable:
            raise PreferenceStoreError("preference store forced unreadable")
        if not self.path.is_file():
            return {}
        try:
            raw = self.path.read_text(encoding="utf-8")
            data = json.loads(raw) if raw.strip() else {}
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise PreferenceStoreError(
                "preference store unreadable: %s" % exc
            ) from exc
        if not isinstance(data, dict):
            raise PreferenceStoreError("preference store payload is not an object")
        return data

    def _write_all(self, data: Mapping[str, Any]) -> None:
        if self.unreadable:
            raise PreferenceStoreError("preference store forced unreadable")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Atomic-ish: write temp then replace (containment-local).
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(dict(data), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)

    def load(self, profile_id: str) -> CollapsePreference:
        pid = _normalize_profile_id(profile_id)
        try:
            data = self._read_all()
        except PreferenceStoreError:
            return CollapsePreference(
                profile_id=pid,
                expanded=[],
                named_state=NamedState.unknown,
                readable=False,
                reason="preference_store_unreadable",
            )
        # Support either flat profile map or {"profiles": {...}}.
        profiles = data.get("profiles") if "profiles" in data else data
        if not isinstance(profiles, Mapping):
            return CollapsePreference(
                profile_id=pid,
                expanded=[],
                named_state=NamedState.unknown,
                readable=False,
                reason="preference_payload_garbage",
            )
        mem = InMemoryPreferenceStore(dict(profiles))
        return mem.load(pid)

    def save(
        self,
        profile_id: str,
        expanded: Optional[Sequence[str]] = None,
    ) -> CollapsePreference:
        pid = _normalize_profile_id(profile_id)
        try:
            data = self._read_all()
        except PreferenceStoreError:
            raise PreferenceStoreError(
                "preference store unreadable — cannot save for profile %r" % pid
            )
        if "profiles" in data:
            profiles = dict(data.get("profiles") or {})
            mem = InMemoryPreferenceStore(profiles)
            pref = mem.save(pid, expanded)
            data = dict(data)
            data["profiles"] = mem.as_dict()
            data["key"] = PREFERENCE_KEY
            self._write_all(data)
            return pref
        mem = InMemoryPreferenceStore(dict(data))
        pref = mem.save(pid, expanded)
        self._write_all(mem.as_dict())
        return pref


PreferenceStore = Union[InMemoryPreferenceStore, PathPreferenceStore, Any]


def make_preference_store(
    source: Optional[Union[MutableMapping[str, Any], str, Path]] = None,
    *,
    unreadable: bool = False,
) -> PreferenceStore:
    """Build an injectable preference store from a dict or path."""
    if source is None or isinstance(source, MutableMapping):
        return InMemoryPreferenceStore(source, unreadable=unreadable)
    return PathPreferenceStore(source, unreadable=unreadable)


def load_preference(
    store: PreferenceStore,
    profile_id: str,
) -> CollapsePreference:
    """Load collapse preference; never raises — unreadable → unknown."""
    try:
        return store.load(profile_id)
    except PreferenceStoreError:
        return CollapsePreference(
            profile_id=_normalize_profile_id(profile_id),
            expanded=[],
            named_state=NamedState.unknown,
            readable=False,
            reason="preference_store_unreadable",
        )
    except Exception:
        return CollapsePreference(
            profile_id=_normalize_profile_id(profile_id),
            expanded=[],
            named_state=NamedState.unknown,
            readable=False,
            reason="preference_store_unreadable",
        )


def save_preference(
    store: PreferenceStore,
    profile_id: str,
    expanded: Optional[Sequence[str]] = None,
) -> CollapsePreference:
    """Save expanded folder ids for *profile_id*."""
    return store.save(profile_id, expanded)


# --------------------------------------------------------------------------
# Dual-profile helpers
# --------------------------------------------------------------------------


def expand_folders_for_profile(
    store: PreferenceStore,
    profile_id: str,
    folder_ids: Sequence[str],
) -> CollapsePreference:
    """User expands named folders under *profile_id* (persists preference)."""
    return save_preference(store, profile_id, folder_ids)


def dual_profile_fixture_store(
    *,
    profile_a_expanded: Optional[Sequence[str]] = None,
    profile_b_expanded: Optional[Sequence[str]] = None,
) -> InMemoryPreferenceStore:
    """Ready-made dual-profile store for tests (no cross-profile bleed)."""
    store = InMemoryPreferenceStore()
    if profile_a_expanded is not None:
        store.save(PROFILE_A, profile_a_expanded)
    if profile_b_expanded is not None:
        store.save(PROFILE_B, profile_b_expanded)
    return store


# --------------------------------------------------------------------------
# View context / result
# --------------------------------------------------------------------------


@dataclass
class ProjectsTreeContext:
    """Inputs that drive the projects-collapse surface render."""

    profile_id: str = PROFILE_A
    projects: Optional[ProjectList] = None
    preference_store: Optional[PreferenceStore] = None
    preference: Optional[CollapsePreference] = None
    #: When True, force preference path to unreadable unknown.
    force_preference_unreadable: bool = False
    title: str = "Projects"
    #: Relative path to the real tree script (src= attribute).
    script_src: str = JS_RELPATH_POSIX
    #: Embed full tree script body in a second <script> for node --check.
    embed_tree_script: bool = True


@dataclass
class ProjectsTreeResult:
    """Structured render outcome for tests and dual-profile reloads."""

    html: str
    profile_id: str
    projects: ProjectList
    preference: CollapsePreference
    projects_named_state: NamedState
    preference_named_state: NamedState
    folder_states: Dict[str, bool] = field(default_factory=dict)
    #: folder_id → True when collapsed on this render

    def collapsed_folder_ids(self) -> List[str]:
        return [fid for fid, col in self.folder_states.items() if col]

    def expanded_folder_ids(self) -> List[str]:
        return [fid for fid, col in self.folder_states.items() if not col]


# --------------------------------------------------------------------------
# Rendering
# --------------------------------------------------------------------------


def _escape_attr(value: str) -> str:
    return html.escape(str(value), quote=True)


def _escape_text(value: str) -> str:
    return html.escape(str(value), quote=False)


def _resolve_projects(ctx: ProjectsTreeContext) -> ProjectList:
    if ctx.projects is not None:
        return ctx.projects
    return sample_project_list()


def _resolve_preference(ctx: ProjectsTreeContext) -> CollapsePreference:
    if ctx.preference is not None:
        return ctx.preference
    if ctx.force_preference_unreadable:
        return CollapsePreference(
            profile_id=_normalize_profile_id(ctx.profile_id),
            expanded=[],
            named_state=NamedState.unknown,
            readable=False,
            reason="preference_store_unreadable",
        )
    store = ctx.preference_store
    if store is None:
        # First-ever load: no store → all collapsed, preference ok (default).
        return CollapsePreference(
            profile_id=_normalize_profile_id(ctx.profile_id),
            expanded=[],
            named_state=NamedState.ok,
            readable=True,
            reason="default_collapsed",
        )
    return load_preference(store, ctx.profile_id)


def render_folder(
    folder: ProjectFolder,
    *,
    collapsed: bool = True,
) -> str:
    """One project folder node with collapsed class on first-paint default."""
    col = bool(collapsed)
    classes = FOLDER_CLASS
    if col:
        classes = "%s %s" % (FOLDER_CLASS, COLLAPSED_CLASS)
    children_html = ""
    if folder.children:
        lis = "\n".join(
            '<li class="project-child" data-child-id="%s">%s</li>'
            % (_escape_attr(c), _escape_text(c))
            for c in folder.children
        )
        children_html = (
            '<ul class="folder-children" data-folder-children="%s">%s</ul>'
            % (_escape_attr(folder.folder_id), lis)
        )
    return (
        '<div class="%s" data-folder-id="%s" data-collapsed="%s" '
        'aria-expanded="%s">'
        '<button type="button" class="folder-toggle" data-folder-toggle="%s" '
        'aria-label="Toggle %s">%s</button> '
        '<span class="folder-label">%s</span>'
        "%s"
        "</div>"
        % (
            classes,
            _escape_attr(folder.folder_id),
            "true" if col else "false",
            "false" if col else "true",
            _escape_attr(folder.folder_id),
            _escape_attr(folder.label),
            _escape_text("▸" if col else "▾"),
            _escape_text(folder.label),
            children_html,
        )
    )


def render_preference_panel(pref: CollapsePreference) -> str:
    """Preference honesty panel — unknown when store unreadable."""
    ns = pref.named_state
    state_html = render_state(ns)
    detail: str
    if ns is NamedState.unknown or not pref.readable:
        detail = "preference store unreadable — collapse default applied"
    elif pref.stale_key:
        detail = "stale preference key ignored — collapsed default applied"
    elif pref.expanded:
        detail = "preference restored: %d expanded" % len(pref.expanded)
    else:
        detail = "preference: all collapsed (default or stored)"
    return (
        '<div class="%s" data-surface="projects-preference" '
        'data-named-state="%s" data-preference-readable="%s" '
        'data-preference-key="%s" data-profile="%s" data-reason="%s">'
        "%s "
        '<span class="preference-detail">%s</span>'
        ' <span class="preference-key-label">key:%s</span>'
        "</div>"
        % (
            PREF_CLASS,
            _escape_attr(ns.value),
            "true" if pref.readable else "false",
            _escape_attr(pref.preference_key),
            _escape_attr(pref.profile_id),
            _escape_attr(pref.reason or ""),
            state_html,
            _escape_text(detail),
            _escape_text(pref.preference_key),
        )
    )


def render_projects_list_panel(
    projects: ProjectList,
    *,
    expanded_ids: Optional[Sequence[str]] = None,
    force_all_collapsed: bool = False,
) -> tuple:
    """Render the project list panel.

    Returns ``(html, folder_states)`` where folder_states maps folder_id →
    collapsed bool.
    """
    ns = projects.named_state
    state_html = render_state(ns)
    expanded = set(_normalize_expanded(expanded_ids))
    folder_states: Dict[str, bool] = {}
    parts: List[str] = [state_html]

    if ns is NamedState.unknown:
        parts.append(
            ' <span class="unknown-detail">project list could not be read</span>'
        )
    elif ns is NamedState.empty:
        parts.append(
            ' <span class="empty-detail">no projects</span>'
        )
    else:
        rows: List[str] = []
        for folder in projects.folders:
            if force_all_collapsed:
                collapsed = True
            else:
                collapsed = folder.folder_id not in expanded
            folder_states[folder.folder_id] = collapsed
            rows.append(render_folder(folder, collapsed=collapsed))
        parts.append(
            ' <div class="%s" data-folder-count="%d">%s</div>'
            % (TREE_CLASS, len(projects.folders), "\n".join(rows))
        )

    body = "".join(parts)
    html_out = (
        '<div class="%s" data-surface="projects-list" '
        'data-named-state="%s" data-list-readable="%s" data-reason="%s" '
        'data-folder-count="%d">'
        "%s</div>"
        % (
            LIST_CLASS,
            _escape_attr(ns.value),
            "true" if projects.readable else "false",
            _escape_attr(projects.reason or ""),
            len(projects.folders) if projects.readable else 0,
            body,
        )
    )
    return html_out, folder_states


def _load_tree_script_body() -> str:
    """Read the real static/js/projects_tree.js body for embedding / checks."""
    path = ROOT_DIR / JS_RELPATH
    if path.is_file():
        return path.read_text(encoding="utf-8")
    # Fallback bootstrap if file not yet written (should not happen in gate).
    return (
        "(function (global) {\n"
        "  'use strict';\n"
        "  global.initProjectsTree = function () { return { ok: false }; };\n"
        "})(typeof window !== 'undefined' ? window : globalThis);\n"
    )


def _inline_bootstrap_script(
    *,
    profile_id: str,
    preference_ok: bool,
    expanded: Sequence[str],
) -> str:
    """Syntax-valid inline bootstrap that calls initProjectsTree."""
    exp_json = json.dumps(list(expanded))
    return (
        "(function () {\n"
        "  var root = document.querySelector("
        "'[data-surface=\"projects_collapse\"]');\n"
        "  if (!root) { return; }\n"
        "  var opts = {\n"
        "    root: root,\n"
        "    profileId: %s,\n"
        "    preferenceOk: %s,\n"
        "    expanded: %s,\n"
        "    applyDefault: true\n"
        "  };\n"
        "  if (typeof window.initProjectsTree === 'function') {\n"
        "    window.initProjectsTree(opts);\n"
        "  } else if (window.AnchorProjectsTree &&\n"
        "      typeof window.AnchorProjectsTree.initProjectsTree === 'function') {\n"
        "    window.AnchorProjectsTree.initProjectsTree(opts);\n"
        "  }\n"
        "})();\n"
        % (
            json.dumps(profile_id),
            "true" if preference_ok else "false",
            exp_json,
        )
    )


def render_projects_tree(
    ctx: Optional[ProjectsTreeContext] = None,
) -> ProjectsTreeResult:
    """Render the full projects-collapse surface for one profile."""
    c = ctx or ProjectsTreeContext()
    profile_id = _normalize_profile_id(c.profile_id)
    projects = _resolve_projects(c)
    preference = _resolve_preference(c)

    # Preference unknown → force collapsed (never silent user choice).
    force_collapsed = preference.is_unknown
    expanded_for_render: List[str] = (
        [] if force_collapsed else list(preference.expanded)
    )

    pref_html = render_preference_panel(preference)
    list_html, folder_states = render_projects_list_panel(
        projects,
        expanded_ids=expanded_for_render,
        force_all_collapsed=force_collapsed,
    )

    preference_ok = not preference.is_unknown
    body = "\n".join(
        [
            pref_html,
            list_html,
            _render_state_legend(),
        ]
    )

    tree_script = _load_tree_script_body() if c.embed_tree_script else ""
    bootstrap = _inline_bootstrap_script(
        profile_id=profile_id,
        preference_ok=preference_ok,
        expanded=expanded_for_render,
    )

    script_tags: List[str] = []
    # Real path reference (inventory-identified JS path).
    script_tags.append(
        '  <script src="%s"></script>\n' % _escape_attr(c.script_src)
    )
    if c.embed_tree_script and tree_script.strip():
        # Embed body so node --check exercises the real collapse logic.
        script_tags.append("  <script>\n%s\n  </script>\n" % tree_script)
    script_tags.append("  <script>\n%s  </script>\n" % bootstrap)

    doc = (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n'
        "<head>\n"
        '  <meta charset="utf-8"/>\n'
        "  <title>%s</title>\n"
        "  <style>\n"
        "    .project-folder.collapsed > .folder-children { display: none; }\n"
        "    .project-folder[data-collapsed=\"true\"] > .folder-children "
        "{ display: none; }\n"
        "  </style>\n"
        "</head>\n"
        "<body>\n"
        '  <main class="projects-collapse-surface" '
        'data-surface="%s" data-wave="%s" data-profile="%s" '
        'data-preference-ok="%s" data-preference-key="%s" '
        'data-control="%s">\n'
        "%s\n"
        "  </main>\n"
        "%s"
        "</body>\n"
        "</html>\n"
        % (
            _escape_text(c.title),
            SURFACE_ID,
            WAVE_ID,
            _escape_attr(profile_id),
            "true" if preference_ok else "false",
            _escape_attr(PREFERENCE_KEY),
            CONTROL_ID,
            body,
            "".join(script_tags),
        )
    )

    return ProjectsTreeResult(
        html=doc,
        profile_id=profile_id,
        projects=projects,
        preference=preference,
        projects_named_state=projects.named_state,
        preference_named_state=preference.named_state,
        folder_states=folder_states,
    )


def _render_state_legend() -> str:
    rows = []
    for ns in (
        NamedState.ok,
        NamedState.unknown,
        NamedState.empty,
    ):
        rows.append(
            '<div class="legend-row" data-legend-state="%s">%s</div>'
            % (_escape_attr(ns.value), render_state(ns))
        )
    return (
        '<section class="projects-legend" data-surface="projects-legend">'
        "\n%s\n</section>" % ("\n".join(rows),)
    )


# --------------------------------------------------------------------------
# Dual-profile reload helper
# --------------------------------------------------------------------------


def render_for_profile(
    profile_id: str,
    *,
    store: Optional[PreferenceStore] = None,
    projects: Optional[ProjectList] = None,
    force_preference_unreadable: bool = False,
) -> ProjectsTreeResult:
    """Render (or re-render after preference save) for one profile."""
    return render_projects_tree(
        ProjectsTreeContext(
            profile_id=profile_id,
            projects=projects if projects is not None else sample_project_list(),
            preference_store=store,
            force_preference_unreadable=force_preference_unreadable,
        )
    )


def reload_after_expand(
    store: PreferenceStore,
    profile_id: str,
    expand_ids: Sequence[str],
    *,
    projects: Optional[ProjectList] = None,
) -> ProjectsTreeResult:
    """Expand folders, persist preference, reload — dual-profile GWT helper."""
    expand_folders_for_profile(store, profile_id, expand_ids)
    return render_for_profile(
        profile_id,
        store=store,
        projects=projects if projects is not None else sample_project_list(),
    )


# --------------------------------------------------------------------------
# generate_html + node --check
# --------------------------------------------------------------------------

_SCRIPT_RE = re.compile(
    r"<script\b[^>]*>(.*?)</script>", re.IGNORECASE | re.DOTALL
)


def node_check_projects_tree_scripts(
    html_text: str,
    *,
    require_node: bool = True,
    also_check_static_file: bool = True,
) -> List[str]:
    """Run ``node --check`` on every inline ``<script>`` block (+ static file)."""
    blocks: List[str] = []
    for m in _SCRIPT_RE.finditer(html_text or ""):
        body = m.group(1)
        if body is None:
            continue
        tag_open = (html_text or "")[m.start() : m.start(1)]
        if "src=" in tag_open and not str(body).strip():
            continue
        if str(body).strip():
            blocks.append(body)

    static_path = ROOT_DIR / JS_RELPATH
    if also_check_static_file and static_path.is_file():
        static_body = static_path.read_text(encoding="utf-8")
        if static_body.strip() and static_body not in blocks:
            blocks.append(static_body)

    if not blocks:
        return []

    node = shutil.which("node")
    if not node:
        if require_node:
            raise RuntimeError(
                "node binary not on PATH — projects tree requires "
                "node --check on the tree script block"
            )
        return blocks

    with tempfile.TemporaryDirectory(prefix="projects_tree_node_check_") as tmp:
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
                    "node --check failed for projects_tree script block %d:\n%s\n%s"
                    % (idx, proc.stdout, proc.stderr)
                )
    return blocks


def generate_html(
    ctx: Optional[ProjectsTreeContext] = None,
    *,
    require_node_check: Optional[bool] = None,
) -> str:
    """Return the projects-collapse surface HTML document."""
    doc = render_projects_tree(ctx).html
    node = shutil.which("node")
    if node:
        node_check_projects_tree_scripts(doc, require_node=True)
    elif require_node_check is True:
        node_check_projects_tree_scripts(doc, require_node=True)
    return doc


def generate_html_for_fixture(fixture: str) -> str:
    """Tri-state harness entry: unknown / empty / zero_measured.

    * ``unknown`` — project list unreadable **or** preference store unreadable
    * ``empty`` — project list read succeeded; no projects
    * ``zero_measured`` — not primary for this surface; emits zero_measured tile
    """
    key = (fixture or "").strip().lower().replace("-", "_")
    if key == "unknown":
        # Prefer list-unreadable for the primary projects named-state unknown.
        ctx = ProjectsTreeContext(
            profile_id=PROFILE_A,
            projects=unreadable_project_list(),
            preference_store=InMemoryPreferenceStore(),
        )
        return render_projects_tree(ctx).html
    if key in ("empty",):
        ctx = ProjectsTreeContext(
            profile_id=PROFILE_A,
            projects=empty_project_list(),
            preference_store=InMemoryPreferenceStore(),
        )
        return render_projects_tree(ctx).html
    if key in ("zero", "zero_measured", "measured_zero"):
        return (
            "<!DOCTYPE html><html><body>"
            '<main data-surface="projects_collapse">'
            "%s"
            "</main>"
            "<script>(function(){})();</script>"
            "</body></html>"
            % render_state(NamedState.zero_measured)
        )
    if key in ("preference_unknown", "unknown_preference"):
        ctx = ProjectsTreeContext(
            profile_id=PROFILE_A,
            projects=sample_project_list(),
            force_preference_unreadable=True,
        )
        return render_projects_tree(ctx).html
    if key in ("ok", "first_load", "collapsed"):
        ctx = ProjectsTreeContext(
            profile_id=PROFILE_A,
            projects=sample_project_list(),
            preference_store=InMemoryPreferenceStore(),
        )
        return render_projects_tree(ctx).html
    raise ValueError("unknown projects_collapse fixture %r" % fixture)


# --------------------------------------------------------------------------
# HTML helpers for tests
# --------------------------------------------------------------------------


_FOLDER_RE = re.compile(
    r'<div class="[^"]*\bproject-folder\b[^"]*"[^>]*>',
    re.IGNORECASE,
)


def folders_have_collapsed_class(html_text: str) -> List[str]:
    """Return folder opening tags; caller asserts collapsed class on each."""
    return _FOLDER_RE.findall(html_text or "")


def assert_all_folders_collapsed(html_text: str) -> int:
    """Assert every project-folder element is collapsed on first paint.

    Accepts either class ``collapsed`` or ``data-collapsed="true"``.
    Returns the number of folders checked.
    """
    tags = folders_have_collapsed_class(html_text)
    if not tags:
        # Also accept data-folder-id nodes with collapsed markers.
        alt = re.findall(
            r'<div[^>]*data-folder-id="[^"]+"[^>]*>',
            html_text or "",
            flags=re.IGNORECASE,
        )
        tags = alt
    if not tags:
        raise AssertionError(
            "no project-folder elements found in rendered HTML"
        )
    for tag in tags:
        has_class = re.search(r'\bclass="[^"]*\bcollapsed\b', tag) is not None
        has_data = 'data-collapsed="true"' in tag
        if not (has_class or has_data):
            raise AssertionError(
                "folder not collapsed on first load: %s" % tag[:200]
            )
    return len(tags)


def folder_collapsed_map(html_text: str) -> Dict[str, bool]:
    """Map folder_id → collapsed from rendered HTML attributes."""
    out: Dict[str, bool] = {}
    for m in re.finditer(
        r'<div[^>]*class="[^"]*\bproject-folder\b[^"]*"[^>]*>',
        html_text or "",
        flags=re.IGNORECASE,
    ):
        tag = m.group(0)
        id_m = re.search(r'data-folder-id="([^"]+)"', tag)
        if not id_m:
            continue
        fid = id_m.group(1)
        has_class = re.search(r'\bclass="[^"]*\bcollapsed\b', tag) is not None
        data_m = re.search(r'data-collapsed="(true|false)"', tag)
        if data_m:
            out[fid] = data_m.group(1) == "true"
        else:
            out[fid] = has_class
    return out


def static_tree_script_path() -> Path:
    return ROOT_DIR / JS_RELPATH


__all__ = [
    "SURFACE_ID",
    "WAVE_ID",
    "CONTROL_ID",
    "PROFILE_A",
    "PROFILE_B",
    "DUAL_PROFILES",
    "PREFERENCE_KEY",
    "FOLDER_CLASS",
    "COLLAPSED_CLASS",
    "JS_RELPATH",
    "JS_RELPATH_POSIX",
    "PreferenceStoreError",
    "ProjectFolder",
    "ProjectList",
    "CollapsePreference",
    "InMemoryPreferenceStore",
    "PathPreferenceStore",
    "ProjectsTreeContext",
    "ProjectsTreeResult",
    "sample_project_list",
    "empty_project_list",
    "unreadable_project_list",
    "make_preference_store",
    "load_preference",
    "save_preference",
    "expand_folders_for_profile",
    "dual_profile_fixture_store",
    "render_folder",
    "render_preference_panel",
    "render_projects_list_panel",
    "render_projects_tree",
    "render_for_profile",
    "reload_after_expand",
    "generate_html",
    "generate_html_for_fixture",
    "node_check_projects_tree_scripts",
    "folders_have_collapsed_class",
    "assert_all_folders_collapsed",
    "folder_collapsed_map",
    "static_tree_script_path",
]
