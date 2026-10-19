"""Chamber-local deliverable action registry (steward-chamber W9, C2/C10 — F3).

The type-aware deliverable action registry the M1 ◇ box runs on, with the F3
execution bounds ENFORCED IN CODE, not asserted in prose:

* **CODE-OWNED verb allow-list, frozen in source.** :data:`VERB_ALLOW_LIST`
  and :data:`TYPE_VERBS` are module literals wrapped read-only
  (``MappingProxyType`` over tuples) — never config, never a file an agent
  can write. This module reads NO configuration: the only file reads are the
  validated sidecar manifest and the projection store (both consulted for
  DATA, never for verbs or argv).
* **Symlink/junction-resolved containment.** :func:`resolve_contained`
  resolves the declared ``output_path`` (symlinks and Windows
  junctions/reparse points FIRST, via ``Path.resolve``) and refuses anything
  outside the project tree — plus '..' segments, absolute/drive/UNC paths,
  and any segment outside the conservative code-owned charset
  (:data:`_SAFE_SEGMENT`). Embedded quotes, spaces, '&', '|', ';', newlines
  and NUL all fall in the hostile class — each renders the action INERT, by
  construction, before any spawn machinery is even consulted.
* **shell:false + list-argv + pinned cwd.** An armed spawn action carries
  ``argv`` as a LIST built from the registry's fixed verb prefix plus the
  contained resolved path ONLY, ``shell: False`` recorded on the action, and
  ``cwd`` pinned to the resolved project folder. :func:`invoke_action` is the
  single execution path and refuses anything not armed.
* **Labeled inert fallback with a NAMED reason.** Every refusal maps to one
  of the ``INERT_*`` constants plus a user-visible label — unknown type,
  disallowed verb, hostile content, uncontained path, not-landed — never a
  silent no-op and never a crash.

The deliverable-landing side (C2): :func:`record_landing_if_present` is the
ENGINE-FED landing writer — called best-effort from the run-finish ingest
path (``commission_session.finish_run``), it appends the W4
``deliverable_landing`` projection event when the manifest-declared output
exists CONTAINED on disk (idempotent per output path; never model-remembered
— disk existence + the validated manifest are the only sources).
:func:`deliverable_state` is the read-only injection-clock payload the open
chamber polls to flip the ◇ box live with no reopen — a SAFE projection
(relative paths only; argv/cwd never serialized).

Stdlib only. ``subprocess`` is imported LAZILY inside the one invoke path;
the module import closure carries no spawn/network/model capability.
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from types import MappingProxyType

import chamber_manifest as cm
import chamber_projections as cproj

SCHEMA = "anchor-chamber-deliverable-action-v1"

# ── Named inert reasons (the labeled inert state; never a shrug) ─────────────
INERT_NOT_DECLARED = "no-declared-deliverable"
INERT_NO_OUTPUT_PATH = "no-output-path"
INERT_UNKNOWN_TYPE = "type-not-in-registry"
INERT_VERB_NOT_ALLOWED = "verb-not-allowed"
INERT_HOSTILE_PATH = "hostile-path-content"
INERT_ABSOLUTE_PATH = "absolute-path-refused"
INERT_PARENT_TRAVERSAL = "parent-traversal-refused"
INERT_OUTSIDE_TREE = "outside-project-tree"
INERT_NOT_LANDED = "not-landed-yet"
INERT_RUNNER_NOT_ALLOWED = "runner-not-allowed"
INERT_SERVICE_NOT_CHAMBER = "service-requires-preview-surface"

#: User-visible labels per named reason (the drawn inert face's text).
INERT_LABELS = MappingProxyType({
    INERT_NOT_DECLARED: "no deliverable is declared for this campaign",
    INERT_NO_OUTPUT_PATH: "the declared deliverable names no output path",
    INERT_UNKNOWN_TYPE: "deliverable type is not in the action registry",
    INERT_VERB_NOT_ALLOWED: "the action verb is outside the allow-list",
    INERT_HOSTILE_PATH: "the declared path carries content the registry "
                        "refuses (quotes, spaces, '&', '|', ';', control "
                        "bytes)",
    INERT_ABSOLUTE_PATH: "the declared path is absolute — only "
                         "project-relative paths can act",
    INERT_PARENT_TRAVERSAL: "the declared path climbs out of the project "
                            "('..')",
    INERT_OUTSIDE_TREE: "the declared path resolves outside the project "
                        "tree (symlinks and junctions are resolved first)",
    INERT_NOT_LANDED: "declared — not landed yet",
    INERT_RUNNER_NOT_ALLOWED: "no code-owned runner exists for this file "
                              "type",
    INERT_SERVICE_NOT_CHAMBER: "a service deliverable launches through the "
                               "preview surface, never from the chamber box",
})

# ── Action kinds + verbs (F3: the CODE-OWNED registry, frozen in source) ────
KIND_HREF = "href"      # no spawn: an internal, scheme-validated link
KIND_SPAWN = "spawn"    # subprocess with shell:false, list-argv, pinned cwd
KIND_INERT = "inert"

VERB_OPEN_REPORT = "open-report"
VERB_OPEN_FILE = "open-file"
VERB_RUN_COMMAND = "run-command"

#: The OS file-opener argv prefix (list-argv; shell never involved). Windows
#: opens through explorer (the association broker as an ARGUMENT, not a
#: shell); elsewhere xdg-open.
_OPENER_ARGV = ("explorer.exe",) if os.name == "nt" else ("xdg-open",)

#: THE verb allow-list — code-owned, frozen in source (F3). ``argv_prefix``
#: is the FIXED head of the spawned argv; the ONLY caller-varying element an
#: armed action ever appends is the contained resolved path. There is no
#: config file, env var, or data path that can add a verb or an argv element.
VERB_ALLOW_LIST = MappingProxyType({
    VERB_OPEN_REPORT: MappingProxyType({"kind": KIND_HREF}),
    VERB_OPEN_FILE: MappingProxyType({"kind": KIND_SPAWN,
                                      "argv_prefix": _OPENER_ARGV}),
    VERB_RUN_COMMAND: MappingProxyType({"kind": KIND_SPAWN,
                                        "argv_prefix": (sys.executable,)}),
})

#: type -> verb (the F2 manifest's deliverable.type enum, exactly). ``None``
#: is an HONEST refusal (service deliverables launch through the existing
#: preview machinery on a free port != 8777 — never from the chamber box).
TYPE_VERBS = MappingProxyType({
    "doc": VERB_OPEN_REPORT,
    "skill": VERB_OPEN_REPORT,
    "script": VERB_RUN_COMMAND,
    "program": VERB_OPEN_FILE,
    "service": None,
})

#: run-command only runs suffixes with a code-owned runner. Anything else is
#: the labeled ``runner-not-allowed`` inert state — never a guessed
#: interpreter, never the shell.
RUNNABLE_SUFFIXES = (".py",)

#: The conservative code-owned path-segment charset. Everything outside it —
#: including the hostile-argv set the plan names (embedded quotes, spaces,
#: '&', '|', ';', newline, NUL) — renders the action inert.
_SAFE_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")

_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def _inert(reason: str, detail: str | None = None) -> dict:
    return {"state": KIND_INERT, "kind": KIND_INERT, "reason": reason,
            "label": INERT_LABELS.get(reason, reason),
            "detail": (str(detail)[:200] if detail else None)}


# ═════════════════════════════════════════════════════════════════════════════
# F3 containment: '..' / absolute / hostile charset / symlink+junction resolve
# ═════════════════════════════════════════════════════════════════════════════

def resolve_contained(folder, rel):
    """Resolve a declared project-relative path under the F3 bounds.

    Returns ``(resolved_path, None)`` when contained, else
    ``(None, inert_dict)`` with the NAMED reason. Order of the checks is the
    security order: byte-level hostility first (so a NUL can never reach
    ``Path``), then shape (absolute / '..'), then the symlink- and
    junction-resolving containment check against the resolved project root.
    """
    if not isinstance(rel, str) or not rel.strip():
        return None, _inert(INERT_NO_OUTPUT_PATH)
    # Byte-level hostility: control bytes (newline, NUL, ESC …) anywhere.
    if any(ord(ch) < 0x20 or ch == "\x7f" for ch in rel):
        return None, _inert(INERT_HOSTILE_PATH, "control byte in path")
    # Shape: absolute, drive-lettered, or UNC paths never act.
    if rel.startswith(("/", "\\")) or _DRIVE_RE.match(rel):
        return None, _inert(INERT_ABSOLUTE_PATH, rel)
    segments = [s for s in re.split(r"[\\/]+", rel) if s and s != "."]
    if not segments:
        return None, _inert(INERT_NO_OUTPUT_PATH)
    if any(s == ".." for s in segments):
        return None, _inert(INERT_PARENT_TRAVERSAL, rel)
    for s in segments:
        if not _SAFE_SEGMENT.match(s):
            return None, _inert(INERT_HOSTILE_PATH, s)
    try:
        base = Path(folder).resolve()
        # Path.resolve() resolves symlinks AND Windows junction/reparse
        # points for every existing component — the plan's "resolves
        # (symlinks and Windows junctions/reparse points first)".
        real = base.joinpath(*segments).resolve()
    except (OSError, ValueError) as exc:
        return None, _inert(INERT_HOSTILE_PATH, str(exc))
    if real != base and base not in real.parents:
        return None, _inert(INERT_OUTSIDE_TREE, "/".join(segments))
    return real, None


def _rel_posix(base: Path, real: Path) -> str:
    return real.relative_to(base).as_posix()


# ═════════════════════════════════════════════════════════════════════════════
# The registry: declared deliverable -> armed action | labeled inert state
# ═════════════════════════════════════════════════════════════════════════════

def resolve_action(folder, deliverable, project_id=None) -> dict:
    """Resolve THE action for a declared deliverable, F3-bounded.

    ``deliverable`` is the manifest's deliverable object (``declared`` /
    ``type`` / ``output_path``). Returns an ARMED action::

        {"state": "armed", "kind": "href"|"spawn", "verb", "output_rel",
         "label", "landed", ("href") | ("argv", "cwd", "shell": False)}

    or the labeled INERT state (``{"state": "inert", "reason", "label"}``)
    with the named reason — never an exception for hostile data, never a
    spawn plan for anything out of bounds.
    """
    if not isinstance(deliverable, dict) or not deliverable.get("declared"):
        return _inert(INERT_NOT_DECLARED)
    dtype = deliverable.get("type")
    if dtype not in TYPE_VERBS:
        return _inert(INERT_UNKNOWN_TYPE, dtype)
    verb = TYPE_VERBS[dtype]
    if verb is None:
        return _inert(INERT_SERVICE_NOT_CHAMBER, dtype)
    if verb not in VERB_ALLOW_LIST:
        # Unreachable unless the source maps drift apart — still a labeled
        # refusal, never a KeyError.
        return _inert(INERT_VERB_NOT_ALLOWED, verb)

    real, refused = resolve_contained(folder, deliverable.get("output_path"))
    if refused is not None:
        return refused
    base = Path(folder).resolve()
    rel = _rel_posix(base, real)
    landed = real.is_file()
    if not landed:
        out = _inert(INERT_NOT_LANDED, rel)
        out["output_rel"] = rel
        out["verb"] = verb
        return out

    row = VERB_ALLOW_LIST[verb]
    if row["kind"] == KIND_HREF:
        href = None
        if project_id:
            from urllib.parse import quote
            href = "/artifact/%s?path=%s" % (quote(str(project_id), safe=""),
                                             quote(rel, safe="/"))
        return {"state": "armed", "kind": KIND_HREF, "verb": verb,
                "output_rel": rel, "landed": True, "href": href,
                "label": "open ▸"}
    # KIND_SPAWN — argv is a LIST: the fixed code-owned prefix + the
    # contained resolved path, nothing else. cwd pinned to the project.
    if verb == VERB_RUN_COMMAND and real.suffix.lower() not in \
            RUNNABLE_SUFFIXES:
        out = _inert(INERT_RUNNER_NOT_ALLOWED, real.suffix)
        out["output_rel"] = rel
        return out
    return {"state": "armed", "kind": KIND_SPAWN, "verb": verb,
            "output_rel": rel, "landed": True,
            "argv": list(row["argv_prefix"]) + [str(real)],
            "cwd": str(base), "shell": False,
            "label": ("run ▸" if verb == VERB_RUN_COMMAND
                      else "open ▸")}


def action_for_project(folder, project_id=None) -> dict:
    """THE action for the project's manifest-declared deliverable — the FULL
    server-side resolution (an armed spawn action carries ``argv``/``cwd``;
    that dict must never serialize to a client — see :func:`public_action`).
    The labeled inert state (named reason) when nothing is declared or the
    declaration is out of bounds."""
    d = _manifest_deliverable(folder)
    if d is None:
        return _inert(INERT_NOT_DECLARED)
    return resolve_action(folder, d, project_id=project_id)


def public_action(action: dict) -> dict:
    """The SAFE projection of an action for HTTP/DOM consumers: verbs,
    labels, relative path and the named inert reason ride; ``argv`` and
    ``cwd`` (absolute host paths) NEVER serialize."""
    if not isinstance(action, dict):
        return _inert(INERT_NOT_DECLARED)
    out = {k: action.get(k) for k in
           ("state", "kind", "verb", "output_rel", "landed", "label",
            "reason", "detail", "href")
           if action.get(k) is not None}
    out.setdefault("state", KIND_INERT)
    return out


def _default_spawn(argv, cwd):
    import subprocess
    creation = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.Popen(
        argv, shell=False, cwd=cwd,
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL, creationflags=creation).pid


def invoke_action(action: dict, spawn_fn=None) -> dict:
    """The ONE execution path. Refuses anything not armed (the inert state's
    named reason rides back; NOTHING executes). An armed href never spawns;
    an armed spawn goes through ``spawn_fn(argv, cwd)`` — default a
    ``shell=False`` list-argv ``Popen`` with the pinned cwd."""
    if not isinstance(action, dict) or action.get("state") != "armed":
        reason = (action or {}).get("reason") or INERT_NOT_DECLARED
        return {"ok": False, "invoked": False, "state": KIND_INERT,
                "reason": reason,
                "label": (action or {}).get("label")
                or INERT_LABELS.get(reason, reason)}
    if action["kind"] == KIND_HREF:
        return {"ok": True, "invoked": False, "kind": KIND_HREF,
                "href": action.get("href"), "output_rel": action["output_rel"]}
    argv = action.get("argv")
    cwd = action.get("cwd")
    if not isinstance(argv, list) or not argv or not cwd \
            or action.get("shell") is not False:
        # A malformed armed action never executes — labeled, not guessed.
        return {"ok": False, "invoked": False, "state": KIND_INERT,
                "reason": INERT_VERB_NOT_ALLOWED,
                "label": INERT_LABELS[INERT_VERB_NOT_ALLOWED]}
    spawn = spawn_fn or _default_spawn
    pid = spawn(argv, cwd)
    return {"ok": True, "invoked": True, "kind": KIND_SPAWN, "pid": pid,
            "verb": action["verb"], "output_rel": action["output_rel"]}


# ═════════════════════════════════════════════════════════════════════════════
# Deliverable state (the injection-clock read) + the engine-fed landing writer
# ═════════════════════════════════════════════════════════════════════════════

def _manifest_deliverable(folder):
    manifest = cm.load_manifest(folder)
    if not isinstance(manifest, dict) or "_unparseable" in manifest:
        return None
    d = manifest.get("deliverable")
    return d if isinstance(d, dict) and d.get("declared") else None


def deliverable_state(folder, project_id=None) -> dict:
    """The read-only injection-clock payload: everything the open chamber
    needs to flip the ◇ box live with NO reopen. SAFE projection — relative
    paths only, no argv/cwd, no model call, no spawn, no write."""
    d = _manifest_deliverable(folder)
    if d is None:
        return {"schema": SCHEMA, "ok": True, "declared": False,
                "landed": False, "action": _inert(INERT_NOT_DECLARED)}
    action = public_action(resolve_action(folder, d, project_id=project_id))
    landing_at = None
    store_note = None
    try:
        landing = cproj.latest(folder, cproj.KIND_DELIVERABLE_LANDING)
        if isinstance(landing, dict):
            landing_at = landing.get("at")
    except cproj.ProjectionStoreError as exc:
        store_note = exc.error  # honest: the landing RECORD is unreadable
    return {
        "schema": SCHEMA,
        "ok": True,
        "declared": True,
        "type": d.get("type"),
        "description": d.get("description"),
        "output_rel": action.get("output_rel"),
        "landed": bool(action.get("landed")),
        "landing_at": landing_at,
        "landing_store_error": store_note,
        "action": action,
    }


def record_landing_if_present(folder, record=None) -> dict:
    """ENGINE-FED landing detection (the run-finish ingest seam).

    When the manifest-declared deliverable's output exists CONTAINED on
    disk, append the W4 ``deliverable_landing`` projection event — keyed to
    the finishing run's commission/session when given. Idempotent per
    output path (a landing already recorded is never duplicated). Best
    effort by contract: every failure returns a labeled dict, never raises
    up the watcher. Never model-remembered: disk existence + the validated
    manifest are the only inputs.
    """
    try:
        d = _manifest_deliverable(folder)
        if d is None:
            return {"recorded": False, "reason": INERT_NOT_DECLARED}
        real, refused = resolve_contained(folder, d.get("output_path"))
        if refused is not None:
            return {"recorded": False, "reason": refused["reason"]}
        if not real.is_file():
            return {"recorded": False, "reason": INERT_NOT_LANDED}
        rel = _rel_posix(Path(folder).resolve(), real)
        for e in cproj.read_events(
                folder, kinds=(cproj.KIND_DELIVERABLE_LANDING,)):
            if e.get("output_path") == rel:
                return {"recorded": False, "reason": "already-recorded",
                        "at": e.get("at")}
        rec = record or {}
        event = cproj.record_deliverable_landing(
            folder, rec.get("commission_id"), output_path=rel,
            deliverable_type=d.get("type"),
            session_id=rec.get("session_id"))
        return {"recorded": True, "at": event.get("at"), "output_rel": rel}
    except Exception as exc:  # the watcher must never die on the sidecar
        return {"recorded": False, "reason": "landing-record-failed",
                "detail": str(exc)[:200]}


# ═════════════════════════════════════════════════════════════════════════════
# The M1 ◇ box render (mockups.html §M1 deliv structure, verbatim; C9-pinned)
# ═════════════════════════════════════════════════════════════════════════════

def _esc(value) -> str:
    import html as _html
    return _html.escape(str(value if value is not None else ""), quote=True)


#: The fixed internal prefixes an ARMED href may paint (the F5 link-scheme
#: law at the render layer). Mirrors chamber_dom_law.INTERNAL_HREF_PREFIXES
#: minus the in-page "#" (chamber_dom_law is CI-only, never imported by
#: product code); the browser wiring re-validates via _ecgSealHrefAllowed
#: before any navigation.
_ARMED_HREF_PREFIXES = ("/artifact/", "/report/", "/summary/")


def render_deliv_box(view: dict) -> str:
    """The declared-deliverable box for the FULL M1 mount (W9: the box goes
    LIVE when the deliverable lands; labeled inert text with the named
    reason otherwise). Structure is the signed §M1 deliv fragment verbatim
    (div.deliv > div.lab + text + button row); only slot VALUES vary and
    every value is escaped. Pure string render — no IO, no spawn."""
    d = view.get("deliverable")
    if not d:
        return ""
    desc = _esc(d.get("description") or "declared deliverable")
    action = d.get("action") or _inert(INERT_NOT_DECLARED)
    rel = action.get("output_rel") or ""
    where_btn = ('<button class="btn" title="%s">where it lands</button>'
                 % _esc(rel or "output path not resolvable"))
    if action.get("state") == "armed":
        href = action.get("href")
        if action.get("kind") == KIND_HREF and isinstance(href, str) \
                and href.startswith(_ARMED_HREF_PREFIXES):
            open_btn = ('<button class="btn gold" data-deliv-href="%s">%s'
                        '</button>' % (_esc(href),
                                       _esc(action.get("label") or "open ▸")))
        elif action.get("kind") == KIND_HREF:
            # No project id, or an href outside the fixed internal prefixes —
            # the landed line still shows, but no link target ever paints.
            open_btn = ""
        else:
            open_btn = ('<button class="btn gold" data-deliv-action="1">%s'
                        '</button>' % _esc(action.get("label") or "open ▸"))
        body = "%s — landed ✓" % desc
        buttons = open_btn + where_btn
    elif action.get("reason") == INERT_NOT_LANDED:
        body = "%s — %s" % (desc, _esc(INERT_LABELS[INERT_NOT_LANDED]))
        buttons = where_btn
    else:
        # The labeled inert state with its NAMED reason (F3): shown, and
        # nothing can execute (no action affordance renders at all).
        body = ("%s — action inert (%s): %s"
                % (desc, _esc(action.get("reason") or "unknown"),
                   _esc(action.get("label") or "")))
        buttons = ""
    return (
        '<div class="deliv">'
        '<div class="lab">Deliverable</div>'
        '%s'
        '<div style="margin-top:6px;display:flex;gap:6px">%s</div>'
        '</div>'
    ) % (body, buttons)
