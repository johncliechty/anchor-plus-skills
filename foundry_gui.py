"""Skill Foundry v2 — Wave 9: the Foundry GUI READ surface (stateless client).

The DESCRIPTION's load-bearing decision #1 ("one engine, many surfaces") made
concrete: the Foundry GUI is a STATELESS client over Anchor's REAL
job_runner / session / artifact machinery (the Wave-1 DR-01 native
read/execute contract). This module is the GUI's DATA layer — pure read
projections, launched from an Anchor dashboard button (the ``/foundry``
route in ``anchor_gui.py`` renders :func:`render_foundry_page`):

* :func:`library_view`  — browse the library: the autoload registry
  (``registered.json``, engine-regenerated from map.json v2 by the Wave-8
  ``foundry.register_autoload`` op) projected row by row.
* :func:`graph_view`    — browse the knowledge graph: typed nodes + edges
  from map.json v2, with the lockfile's resolved pins folded in and lock
  drift reported honestly (never a fabricated graph).
* :func:`runs_view`     — run/monitor skills: the job list read from
  job_runner's OWN durable records under the jobs dir.
* :func:`monitor_view`  — one job's LIVE state: ``job_runner.load_record``
  + ``job_runner.tail`` — job_runner state itself, never a copy of it.
* :func:`changes_view`  — see changes: a skill's host-enforced journal
  entries (the Wave-2 seam's skeleton artifacts), parsed newest-first.

THE ANTI-THEATER INVARIANT (gated by ``tests/test_foundry_gui_w9.py``):
every displayed value TRACES to an engine-written artifact — each view row
carries a ``trace`` naming the artifact file it was read from and the
engine accessor it came through — and there is NO parallel run/progress
store. :func:`anti_theater_check` enforces the second half structurally:
it flags any file-mutation primitive in this module's source and any
module-level mutable container (a mirror/cache/progress store) at runtime,
so introducing a parallel store fails the gate loudly.

This module reads via the engine's own accessors and never mutates
anything: no file creation, no caching, no registry of its own. Stdlib
only (Anchor's no-dep rule) + the product seams ``paths`` /
``foundry_decisions`` / ``foundry_autoload`` / ``foundry_journal`` /
``foundry_map`` / ``job_runner``.

Wave 10: the page additionally embeds the WRITE surface panel from
``foundry_gui_write`` — action cards whose every mutation is a confirm-
gated control-plane op invocation through job_runner (never a GUI-side
file mutation), plus the declared ``foundry.sleep_session`` seam with its
honest pending status. The read layer here stays pure.
"""

import html as _htmlmod
import re
import sys
import time
import types
from pathlib import Path

import paths as _paths
import foundry_autoload as _fa
import foundry_decisions as _fd
import foundry_journal as _fj
import foundry_gui_write as _fgw
import foundry_map as _fm
import job_runner as _jr


# ── Constants ────────────────────────────────────────────────────────────────

#: Wave-1 anti-drift convention: the GUI surface traces to the North Star.
TRACES_TO_NORTH_STAR = (_fd.NS_GUI_DRIVES_REAL_MACHINERY,
                        _fd.NS_KNOWLEDGE_GRAPH)

#: The engine accessors each trace names (``via``) — the audit vocabulary.
VIA_AUTOLOAD = "foundry_autoload.clickable_skills"
VIA_MAP = "foundry_map.load_map"
VIA_LOCK = "foundry_map.load_lockfile"
VIA_JOB_RECORDS = "job_runner.list_records"
VIA_JOB_RECORD = "job_runner.load_record"
VIA_JOB_TAIL = "job_runner.tail"
VIA_JOURNAL = "foundry_journal.parse_entry"

#: How many runs the list view shows by default (read cap, not a store).
DEFAULT_RUNS_LIMIT = 50

# File-mutation primitives forbidden in this module (the anti-theater scan).
# Each marker is split across adjacent literals so the scan never matches its
# own definition — only a REAL mutation call site in the source.
_WRITE_MARKERS = (
    "write_" "text(",
    "write_" "bytes(",
    ".mkdi" "r(",
    "makedir" "s(",
    "os.repla" "ce(",
    "os.rena" "me(",
    "json.du" "mp(",
    "shutil" ".",
    ".unli" "nk(",
    ".touc" "h(",
    ".writ" "e(",
    "open" "(",
)

#: A module-level assignment binding a MUTABLE container (dict/list/set/...)
#: is a parallel store in the making — exactly what "no parallel
#: run/progress store" forbids in the GUI data layer.
_STORE_ASSIGN_RE = re.compile(
    r"^[A-Za-z_][A-Za-z0-9_]*\s*(?::[^=\n]+)?=\s*"
    r"(?:\{|\[|dict\(|list\(|set\(|bytearray\(|collections\.|"
    r"OrderedDict\(|defaultdict\()",
    re.MULTILINE)

#: Module-global value types that are NOT a store (immutable / code / module).
_IMMUTABLE_GLOBAL_TYPES = (str, bytes, int, float, bool, tuple, frozenset,
                           type(None))


# ── Traces (every displayed value points at its engine-written artifact) ─────

def _trace(artifact, via) -> dict:
    """One provenance stamp: the artifact path a value was read from + the
    engine accessor it came through. ``exists`` is the honest liveness of the
    artifact at read time (a dir-backed trace reports dir existence)."""
    p = Path(artifact)
    return {"artifact": p.as_posix(), "via": str(via), "exists": p.exists()}


def _autoload_home(home) -> Path:
    """Resolve the autoload registry home WITHOUT creating it — this is a
    read surface; the engine (``foundry.register_autoload``) owns creation."""
    return Path(home) if home else (_paths.data_dir() / _fa.AUTOLOAD_DIRNAME)


# ── Library (browse) ─────────────────────────────────────────────────────────

def library_view(home=None) -> dict:
    """The browse-the-library projection over the autoload registry.

    Rows come from ``foundry_autoload.clickable_skills`` — the READ side of
    the Wave-8 regenerated projection of map.json v2. Honest before any
    sync (``registered=False``, no rows); a present-but-corrupted registry
    is reported as unreadable, never rendered as an empty library."""
    h = _autoload_home(home)
    reg = _fa.registry_path(h)
    t = _trace(reg, VIA_AUTOLOAD)
    try:
        skills = _fa.clickable_skills(h)
    except ValueError as exc:
        return {"ok": False, "reason": "registry-unreadable:%s" % exc,
                "registered": True, "skills": [], "trace": t}
    rows = []
    for r in skills:
        if not isinstance(r, dict):
            continue
        rows.append({
            "ref": r.get("ref"),
            "name": r.get("name"),
            "version": r.get("version"),
            "status": r.get("status"),
            "tier": r.get("tier"),
            "clickable": bool(r.get("clickable")),
            "runnable": bool(r.get("runnable")),
            "panel_title": (r.get("panel") or {}).get("title"),
            "reason": r.get("reason"),
            "trace": t,
        })
    return {"ok": True, "registered": reg.is_file(), "skills": rows,
            "count": len(rows), "trace": t}


# ── Knowledge graph (browse) ─────────────────────────────────────────────────

def graph_view(map_path=None, lock_path=None) -> dict:
    """The knowledge-graph projection: typed nodes + edges from map.json v2,
    the lockfile's resolved pins folded onto the edges when (and only when)
    the lock verifies drift-free against a fresh resolution.

    An unreadable or invalid map yields an honest refusal with NO nodes —
    an invalid graph is never projected (the Wave-6 consumption discipline);
    lock problems are reported by name, never papered over."""
    mp = Path(map_path) if map_path else _fm.MAP_FILE
    lp = Path(lock_path) if lock_path else _fm.LOCK_FILE
    map_trace = _trace(mp, VIA_MAP)
    try:
        doc = _fm.load_map(mp)
    except (OSError, ValueError) as exc:
        return {"ok": False, "reason": "map-unreadable:%s" % exc,
                "nodes": [], "edges": [], "lock": None, "trace": map_trace}
    problems = _fm.validate_map(doc)
    if problems:
        return {"ok": False,
                "reason": ("map-invalid:" + "; ".join(problems))[:300],
                "nodes": [], "edges": [], "lock": None, "trace": map_trace}
    nodes, edges = [], []
    for skill in sorted(doc["skills"], key=lambda s: str(s.get("ref"))):
        nodes.append({
            "ref": skill["ref"],
            "name": skill["name"],
            "version": skill["version"],
            "status": skill["status"],
            "tier": skill["tier"],
            "source": str(skill["source"]),
            "trace": map_trace,
        })
        for edge in (skill.get("edges") or ()):
            edges.append({
                "from": skill["ref"],
                "type": edge.get("type"),
                "to": edge.get("to"),
                "range": edge.get("range"),
                "pinned": None,  # filled from a VERIFIED lock below
                "trace": map_trace,
            })
    lock_info = {"ok": False, "problems": [], "pins": {},
                 "trace": _trace(lp, VIA_LOCK)}
    try:
        lock = _fm.load_lockfile(lp)
    except (OSError, ValueError) as exc:
        lock_info["problems"] = ["lock-unreadable:%s" % exc]
    else:
        drift = _fm.verify_lockfile(doc, lock)
        lock_info["problems"] = drift
        if not drift:
            lock_info["ok"] = True
            pin_by_edge = {}
            for entry in (lock.get("resolved") or ()):
                lock_info["pins"][entry["ref"]] = entry.get("version")
                for dep in (entry.get("dependencies") or ()):
                    pin_by_edge[(entry["ref"], dep.get("type"),
                                 dep.get("ref"))] = dep.get("pinned")
            for edge in edges:
                edge["pinned"] = pin_by_edge.get(
                    (edge["from"], edge["type"], edge["to"]))
    return {"ok": True, "nodes": nodes, "edges": edges, "lock": lock_info,
            "trace": map_trace}


# ── Runs (run/monitor) — job_runner state, never a mirror ────────────────────

def _run_row(rec: dict) -> dict:
    """SAFE projection of one job_runner record (no crypt token, no pid, no
    relaunch spec) — each row traced to the record artifact it was read from."""
    job_id = str(rec.get("job_id"))
    return {
        "job_id": job_id,
        "lane": rec.get("lane"),
        "status": rec.get("status"),
        "backend": rec.get("backend"),
        "started_at": rec.get("started_at"),
        "finished_at": rec.get("finished_at"),
        "exit_code": rec.get("exit_code"),
        "cost": rec.get("cost"),
        "trace": _trace(_jr.jobs_dir() / (job_id + ".json"), VIA_JOB_RECORDS),
    }


def runs_view(lane=None, limit=DEFAULT_RUNS_LIMIT) -> dict:
    """The run list, read from job_runner's OWN durable records each call.

    Nothing is cached and nothing is copied: a record that changes on disk
    changes here on the very next call. ``lane`` filters (e.g. the
    control-plane ``foundry-op`` lane); newest first."""
    rows = []
    for rec in _jr.list_records():
        if not isinstance(rec, dict) or not rec.get("job_id"):
            continue
        if lane is not None and rec.get("lane") != lane:
            continue
        rows.append(_run_row(rec))
    rows.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
    total = len(rows)
    if limit:
        rows = rows[:int(limit)]
    return {"ok": True, "runs": rows, "count": len(rows), "total": total,
            "lane": lane, "trace": _trace(_jr.jobs_dir(), VIA_JOB_RECORDS)}


def monitor_view(job_id, since=0) -> dict:
    """One job's LIVE state: ``job_runner.load_record`` for the record and
    ``job_runner.tail`` for the incremental output — job_runner state read
    through job_runner itself, at call time, every call. There is no
    GUI-side copy to go stale: mutate the record and the next call shows it.

    Unknown jobs are honest (``ok=False``), never fabricated."""
    jid = str(job_id)
    rec = _jr.load_record(jid)
    rec_trace = _trace(_jr.jobs_dir() / (jid + ".json"), VIA_JOB_RECORD)
    if rec is None:
        return {"ok": False, "job_id": jid, "reason": "unknown-job:%s" % jid,
                "status": None, "lines": [], "trace": rec_trace}
    t = _jr.tail(jid, since)
    log_path = rec.get("log_path") or str(_jr.log_path_for(jid))
    return {
        "ok": True,
        "job_id": jid,
        "lane": rec.get("lane"),
        "status": t.get("status"),      # job_runner's answer, this instant
        "backend": rec.get("backend"),
        "started_at": rec.get("started_at"),
        "finished_at": rec.get("finished_at"),
        "exit_code": rec.get("exit_code"),
        "cost": rec.get("cost"),
        "lines": t.get("lines") or [],
        "next": t.get("next"),
        "total": t.get("total"),
        "trace": rec_trace,
        "log_trace": _trace(log_path, VIA_JOB_TAIL),
    }


# ── Changes (see what a skill's runs/mutations did) ──────────────────────────

def changes_view(skill_dir) -> dict:
    """A skill's journaled changes: the host-enforced skeleton entries the
    Wave-2 seam wrote under ``<skill_dir>/journal/``, parsed newest-first.

    Read-only over the engine's own artifacts (each entry traced to its
    ``.md`` file); a skill with no journal yet is an honest empty list."""
    d = Path(skill_dir)
    jdir = _fj.journal_dir(d)
    entries = []
    if jdir.is_dir():
        for p in sorted(jdir.glob("*.md")):
            try:
                parsed = _fj.parse_entry(
                    p.read_text(encoding="utf-8", errors="replace"))
            except OSError:
                continue
            if not parsed:
                continue
            vt = parsed.get("verdict_timing")
            ol = parsed.get("outcome_linkage")
            entries.append({
                "id": parsed.get("id") or p.stem,
                "ts": parsed.get("ts"),
                "operation_kind": parsed.get("operation_kind"),
                "provenance": parsed.get("provenance"),
                "verdict": (vt or {}).get("verdict")
                if isinstance(vt, dict) else vt,
                "outcome": (ol or {}).get("outcome")
                if isinstance(ol, dict) else ol,
                "trace": _trace(p, VIA_JOURNAL),
            })
    entries.sort(key=lambda e: (e.get("ts") is not None, e.get("ts") or 0,
                                str(e.get("id"))), reverse=True)
    return {"ok": True, "skill_dir": d.as_posix(), "entries": entries,
            "count": len(entries), "trace": _trace(jdir, VIA_JOURNAL)}


# ── The anti-theater check (fails if a parallel store is introduced) ─────────

def anti_theater_check(source_text=None, module=None) -> list:
    """Return the anti-theater problems with the GUI data layer (empty = an
    honest stateless client).

    Two structural checks, both scoped to THIS module:

    * **no mutation path** — any file-mutation primitive in the source is a
      GUI-side write, which the DESCRIPTION forbids (every mutation is a
      confirm-gated runner op);
    * **no parallel store** — a module-level assignment binding a mutable
      container in the source, or any mutable container living in the
      module's globals at runtime, is a parallel run/progress store (a
      mirror that can go stale and start lying about the engine).

    The gate calls this against the shipped module (must be clean) AND
    against a doctored source (must fail loudly)."""
    problems = []
    if source_text is None:
        source_text = Path(__file__).resolve().read_text(
            encoding="utf-8", errors="replace")
    for n, line in enumerate(source_text.splitlines(), start=1):
        for marker in _WRITE_MARKERS:
            if marker in line:
                problems.append("gui-mutation-path:%d:%s"
                                % (n, line.strip()[:120]))
                break
    for m in _STORE_ASSIGN_RE.finditer(source_text):
        problems.append("parallel-store:%s" % m.group(0).strip()[:120])
    mod = module if module is not None else sys.modules[__name__]
    for name in sorted(vars(mod)):
        if name.startswith("__"):
            continue
        val = vars(mod)[name]
        if isinstance(val, (types.ModuleType, type)) or callable(val):
            continue
        if isinstance(val, _IMMUTABLE_GLOBAL_TYPES):
            continue
        if isinstance(val, (re.Pattern, Path)):
            continue
        problems.append("module-state:%s:%s" % (name, type(val).__name__))
    return problems


# ── The page render (what the Anchor button serves) ──────────────────────────

_PAGE_CSS = """
  :root { --bg:#0e1116; --panel:#161b24; --line:#252d3b; --text:#dbe2ee;
          --dim:#8a94a6; --accent:#6c9cfc; --ok:#22c55e; --warn:#f59e0b;
          --bad:#ef4444; }
  * { box-sizing:border-box; }
  body { background:var(--bg); color:var(--text); margin:0;
         font:14px/1.5 'Segoe UI',system-ui,sans-serif; }
  .wrap { max-width:1100px; margin:0 auto; padding:24px 20px 60px; }
  h1 { font-size:20px; margin:0 0 2px; }
  h2 { font-size:15px; margin:26px 0 8px; color:var(--accent); }
  .sub { color:var(--dim); font-size:12.5px; margin-bottom:18px; }
  a { color:var(--accent); text-decoration:none; }
  table { width:100%; border-collapse:collapse; font-size:13px;
          background:var(--panel); border:1px solid var(--line); }
  th, td { text-align:left; padding:6px 10px;
           border-bottom:1px solid var(--line); }
  th { color:var(--dim); font-weight:600; font-size:11.5px;
       text-transform:uppercase; letter-spacing:.04em; }
  .ok { color:var(--ok); } .warn { color:var(--warn); }
  .bad { color:var(--bad); } .dim { color:var(--dim); }
  .src { color:var(--dim); font-size:11px; margin:6px 0 0; }
  .edge { font-size:13px; padding:2px 0; }
  pre { background:var(--panel); border:1px solid var(--line); padding:10px;
        font-size:12px; overflow:auto; max-height:420px; white-space:pre-wrap; }
  .badge { display:inline-block; border:1px solid var(--line);
           border-radius:9px; padding:0 7px; font-size:11px;
           color:var(--dim); margin-left:6px; }
"""


def _esc(value) -> str:
    return _htmlmod.escape("" if value is None else str(value))


def _fmt_ts(ts) -> str:
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(float(ts)))
    except (TypeError, ValueError, OSError, OverflowError):
        return "—"


def _src_line(trace) -> str:
    if not isinstance(trace, dict):
        return ""
    flag = "" if trace.get("exists") else " (absent)"
    return ('<div class="src">source: %s · via %s%s</div>'
            % (_esc(trace.get("artifact")), _esc(trace.get("via")),
               _esc(flag)))


def _render_library(lib) -> list:
    out = ["<h2>Library</h2>"]
    if not lib.get("ok"):
        out.append('<p class="bad">%s</p>' % _esc(lib.get("reason")))
    elif not lib.get("skills"):
        out.append('<p class="dim">No registered skills yet — run the '
                   "autoload registration op (map.json v2 drives this list)."
                   "</p>")
    else:
        rows = []
        for r in lib["skills"]:
            run = ('<span class="ok">runnable</span>' if r.get("runnable")
                   else '<span class="warn">%s</span>'
                   % _esc(r.get("reason") or "not runnable"))
            rows.append(
                "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td>"
                "<td>%s</td><td>%s</td></tr>"
                % (_esc(r.get("name")), _esc(r.get("version")),
                   _esc(r.get("status")), _esc(r.get("tier")),
                   run, _esc(r.get("panel_title"))))
        out.append("<table><tr><th>Skill</th><th>Version</th><th>Status</th>"
                   "<th>Tier</th><th>Run</th><th>Panel</th></tr>%s</table>"
                   % "".join(rows))
    out.append(_src_line(lib.get("trace")))
    return out


def _render_graph(graph) -> list:
    out = ["<h2>Knowledge graph</h2>"]
    if not graph.get("ok"):
        out.append('<p class="bad">%s</p>' % _esc(graph.get("reason")))
        out.append(_src_line(graph.get("trace")))
        return out
    node_rows = []
    for n in graph["nodes"]:
        node_rows.append(
            "<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>"
            % (_esc(n.get("ref")), _esc(n.get("version")),
               _esc(n.get("status")), _esc(n.get("tier"))))
    out.append("<table><tr><th>Ref</th><th>Version</th><th>Status</th>"
               "<th>Tier</th></tr>%s</table>" % "".join(node_rows))
    if graph["edges"]:
        edge_bits = []
        for e in graph["edges"]:
            pin = (' <span class="badge">pinned %s</span>'
                   % _esc(e["pinned"])) if e.get("pinned") else ""
            edge_bits.append(
                '<div class="edge">%s &mdash;%s&rarr; %s '
                '<span class="dim">(%s)</span>%s</div>'
                % (_esc(e.get("from")), _esc(e.get("type")),
                   _esc(e.get("to")), _esc(e.get("range")), pin))
        out.append("".join(edge_bits))
    else:
        out.append('<p class="dim">No edges declared.</p>')
    lock = graph.get("lock") or {}
    if lock.get("ok"):
        out.append('<p class="src ok">lockfile verified drift-free '
                   "(%d pins)</p>" % len(lock.get("pins") or ()))
    else:
        out.append('<p class="src warn">lockfile: %s</p>'
                   % _esc("; ".join(lock.get("problems") or ())
                          or "not verified"))
    out.append(_src_line(graph.get("trace")))
    return out


def _render_changes(graph) -> list:
    out = ["<h2>Changes (host-enforced journals)</h2>"]
    if not graph.get("ok") or not graph.get("nodes"):
        out.append('<p class="dim">No skills to read journals from.</p>')
        return out
    rows = []
    for n in graph["nodes"]:
        ch = changes_view(n["source"])
        last = ch["entries"][0] if ch["entries"] else None
        rows.append(
            "<tr><td>%s</td><td>%d</td><td>%s</td><td>%s</td></tr>"
            % (_esc(n.get("name")), ch["count"],
               _esc((last or {}).get("outcome") or "—"),
               _esc((last or {}).get("verdict") or "—")))
    out.append("<table><tr><th>Skill</th><th>Journaled runs</th>"
               "<th>Last outcome</th><th>Last verdict</th></tr>%s</table>"
               % "".join(rows))
    out.append('<div class="src">source: each skill&#39;s own '
               "journal/*.md skeleton entries · via %s</div>"
               % _esc(VIA_JOURNAL))
    return out


def _render_runs(runs) -> list:
    out = ["<h2>Runs</h2>"]
    if not runs.get("runs"):
        out.append('<p class="dim">No engine runs recorded%s.</p>'
                   % (_esc(" on lane " + str(runs.get("lane")))
                      if runs.get("lane") else ""))
    else:
        rows = []
        for r in runs["runs"]:
            cls = {"done": "ok", "running": "warn"}.get(
                str(r.get("status")), "bad")
            rows.append(
                '<tr><td><a href="/foundry?job=%s">%s</a></td><td>%s</td>'
                '<td class="%s">%s</td><td>%s</td><td>%s</td></tr>'
                % (_esc(r.get("job_id")), _esc(str(r.get("job_id"))[:12]),
                   _esc(r.get("lane")), cls, _esc(r.get("status")),
                   _esc(r.get("backend")), _fmt_ts(r.get("started_at"))))
        out.append("<table><tr><th>Job</th><th>Lane</th><th>Status</th>"
                   "<th>Backend</th><th>Started</th></tr>%s</table>"
                   % "".join(rows))
    out.append(_src_line(runs.get("trace")))
    return out


def _render_monitor(mon) -> list:
    out = ["<h2>Monitor — %s</h2>" % _esc(mon.get("job_id"))]
    if not mon.get("ok"):
        out.append('<p class="bad">%s</p>' % _esc(mon.get("reason")))
        return out
    out.append('<p>lane <b>%s</b> · status <b>%s</b> · backend %s · '
               "exit %s · started %s</p>"
               % (_esc(mon.get("lane")), _esc(mon.get("status")),
                  _esc(mon.get("backend")), _esc(mon.get("exit_code")),
                  _fmt_ts(mon.get("started_at"))))
    out.append("<pre>%s</pre>"
               % _esc("\n".join(mon.get("lines") or ()) or "(no output yet)"))
    out.append(_src_line(mon.get("trace")))
    out.append(_src_line(mon.get("log_trace")))
    return out


def render_foundry_page(*, home=None, map_path=None, lock_path=None,
                        lane=None, job_id=None, since=0) -> str:
    """Render the Foundry GUI page — the stateless read surface the Anchor
    dashboard button opens (``GET /foundry``).

    Assembled fresh from the engine's artifacts on every request: the
    autoload registry (library), map.json v2 + lockfile (knowledge graph +
    per-skill journal summaries), and job_runner's durable records (runs;
    ``?job=<id>`` drills into one job's live monitor). Pure read — this
    render neither caches nor persists anything."""
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        "<title>Skill Foundry</title>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<style>%s</style></head><body><div class='wrap'>" % _PAGE_CSS,
        "<h1>&#9874; Skill Foundry</h1>",
        "<div class='sub' data-anti-theater='stateless'>A stateless client "
        "over Anchor&#39;s live engine &mdash; every value on this page is "
        "read from an engine-written artifact (no parallel run/progress "
        "store). <a href='/'>&larr; Anchor</a> &middot; "
        "<a href='/foundry'>refresh</a></div>",
    ]
    # Wave 10: the write-surface panel (create / edit North Star / clickable
    # sync / sleep seam) — rendered by foundry_gui_write; every button is an
    # op invocation POST, so the read layer here stays mutation-free.
    parts.append(_fgw.render_write_panel())
    # Wave 12: the North-Star acceptance scorecard — every DONE= clause
    # probed live against the same engine artifacts; the sleep-loop clause
    # stays the single declared open item (recorded, never dropped) until
    # the foundry-kernel integration registers the op body. Lazy import:
    # foundry_acceptance reads THROUGH this module's views.
    import foundry_acceptance as _facc
    parts.append(_facc.render_acceptance_panel(home=home, map_path=map_path,
                                               lock_path=lock_path))
    if job_id:
        parts.extend(_render_monitor(monitor_view(job_id, since=since)))
    lib = library_view(home=home)
    graph = graph_view(map_path=map_path, lock_path=lock_path)
    runs = runs_view(lane=lane)
    parts.extend(_render_library(lib))
    parts.extend(_render_graph(graph))
    parts.extend(_render_changes(graph))
    parts.extend(_render_runs(runs))
    parts.append("</div></body></html>")
    return "\n".join(parts)
