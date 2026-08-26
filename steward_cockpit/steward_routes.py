"""Anchor mount for the steward cockpit (the validated chamber replacement).

anchor_gui.py delegates here, additively and behind Anchor's own token check,
without disturbing the chamber:

  GET  /project/<pid>             -> serve_cockpit_doc()   (the DEFAULT page
                                     since the 2026-08-25 cutover; the chamber
                                     is the ?classic=1 escape hatch)
  GET  /steward-static/<file>     -> serve_static(name)
  GET  /api/steward/<verb>?...    -> handle_get(cdir, verb, qs)  / events()
  POST /api/steward/<verb>        -> handle_post(cdir, verb, body)

Everything is scoped to ONE campaign dir. Terms (workbench terminals) live in
<cdir>/.anchor/steward-terms.json, flat {tid: {...}}. Path/file safety is
preserved verbatim from the hardened prototype (allow-list open, dot-component
refusal, upload deny-list, link re-assertion). Anchor's token gate is the
primary auth; these handlers assume an authorized caller.
"""
import base64
import json
import os
import re
import threading
import time
from pathlib import Path

from steward_cockpit import steward_campaign as campaign
from steward_cockpit.steward_engine import Engine

HERE = Path(__file__).parent
STATIC = HERE / "static"

OPENABLE_EXT = {".md", ".txt", ".pdf", ".docx", ".doc", ".xlsx", ".xls",
                ".csv", ".pptx", ".ppt", ".png", ".jpg", ".jpeg", ".gif", ".json"}
DENY_UPLOAD_EXT = {".exe", ".bat", ".cmd", ".com", ".scr", ".hta", ".js",
                   ".jse", ".vbs", ".vbe", ".wsf", ".wsh", ".ps1", ".psm1",
                   ".ps1xml", ".lnk", ".url", ".msi", ".reg", ".dll", ".jar",
                   ".pif", ".application", ".gadget", ".cpl", ".py", ".pyw",
                   ".pyc", ".pyo", ".ipynb", ".r", ".svg", ".html", ".htm",
                   ".scf", ".sct", ".inf", ".msc", ".jnlp", ".vb", ".ws"}
MAX_LIVE_ENGINES = 24

ENGINES = {}
ENGINES_LOCK = threading.Lock()
TERMS_LOCK = threading.Lock()

# persona + fake flag injected by anchor_gui at mount time
CONFIG = {"steward": "Ecgberht", "fake": False, "permission_mode": "bypassPermissions"}
BONEYARD = campaign.BONEYARD_DIRNAME
SKILLS = ["researchPrime", "Crucible", "Foreman", "Gandalf", "Jumper",
          "ramanujan", "legal-beagle", "financial-analyst",
          "literature-review", "tidy-idy"]


# ---------- terminal registry (per campaign dir) ----------
def _terms_file(cdir):
    return Path(cdir) / ".anchor" / "steward-terms.json"


def _load_terms(cdir):
    try:
        return json.loads(_terms_file(cdir).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_terms(cdir, terms):
    try:
        f = _terms_file(cdir)
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".tmp")
        tmp.write_text(json.dumps(terms, indent=2), encoding="utf-8")
        os.replace(tmp, f)
    except Exception:
        pass


def _bad_component(name):
    s = str(name)
    return (not s or s.startswith(".") or s.startswith("_")
            or ":" in s or s.rstrip() != s or s.rstrip(".") != s
            or "/" in s or "\\" in s)


def get_engine(cdir, general=False, tid=None, create=True):
    if general:
        tid = str(tid or "1")
        if not re.fullmatch(r"\d{1,6}", tid):
            return None
        if create and tid not in _load_terms(cdir):
            return None
    key = cdir + (f"||general||{tid}" if general else "")
    with ENGINES_LOCK:
        if key not in ENGINES:
            if not create:
                return None
            if sum(1 for e in ENGINES.values() if e.alive()) >= MAX_LIVE_ENGINES:
                return None
            ENGINES[key] = Engine(cdir, permission_mode=CONFIG["permission_mode"],
                                  fake=CONFIG["fake"], steward=CONFIG["steward"],
                                  general=general, tid=tid if general else None)
        return ENGINES[key]


# ---------- static + document ----------
def serve_static(name):
    name = Path(name).name
    if not name.endswith((".html", ".js", ".css")):
        return None, None
    f = STATIC / name
    if not f.is_file():
        return None, None
    ctype = ("text/html; charset=utf-8" if name.endswith(".html")
             else "text/css; charset=utf-8" if name.endswith(".css")
             else "application/javascript; charset=utf-8")
    return f.read_bytes(), ctype


_CLIENT_SHIM = """<script>
window.STEWARD_PID = %s;
window.STEWARD_BUILD = %s;
(function(){
  // token: prefer one arriving in the URL (the beta-link / bounce), else the
  // stored one; persist a URL token so later fetches stay authed
  var TOK="";
  try{TOK=(new URLSearchParams(location.search)).get('token')||'';}catch(_){}
  try{if(TOK){localStorage.setItem('anchor_token',TOK);}else{TOK=localStorage.getItem('anchor_token')||'';}}catch(_){}
  window.STEWARD_TOKEN=TOK;
  function auth(o){o=o||{};if(TOK){o.headers=Object.assign({},o.headers||{},{'Authorization':'Bearer '+TOK});}return o;}
  var _f=window.fetch;window.fetch=function(u,o){
    if(typeof u==='string'){
      if(u.indexOf('/api/')===0){u='/api/steward/'+u.slice(5);
        u+=(u.indexOf('?')<0?'?':'&')+'pid='+encodeURIComponent(window.STEWARD_PID);
        o=auth(o);}
      else if(u.indexOf('/static/')===0){u='/steward-static/'+u.slice(8);}
      else if(u.indexOf('/report')===0){u='/steward'+u;
        u+=(u.indexOf('?')<0?'?':'&')+'pid='+encodeURIComponent(window.STEWARD_PID);}
    }
    return _f(u,o);
  };
  var _op=window.open;window.open=function(u,t){
    if(typeof u==='string'&&u.indexOf('/report')===0){u='/steward'+u+
      (u.indexOf('?')<0?'?':'&')+'pid='+encodeURIComponent(window.STEWARD_PID)+
      (TOK?'&token='+encodeURIComponent(TOK):'');}
    return _op(u,t);};
  // self-heal on redeploy (the BUILD_ID lesson, 2026-08-15): an open cockpit
  // page polls the server's build and reloads ITSELF when it moves — via the
  // ORIGINAL fetch (_f), so the /api/ -> /api/steward/ rewrite never eats the
  // probe. Loop guard: at most one reload per server version.
  if (window.STEWARD_BUILD) setInterval(function(){
    _f('/api/version', {cache:'no-store'}).then(function(r){return r.json();})
      .then(function(j){
        var v = j && j.version;
        if (!v || v === window.STEWARD_BUILD) return;
        var key = 'steward_reloaded_for';
        try{ if (sessionStorage.getItem(key) === v) return;
             sessionStorage.setItem(key, v); }catch(_){}
        location.reload();
      }).catch(function(){});
  }, 30000);
})();
</script>"""


def serve_cockpit_doc(pid=""):
    return serve_page_doc("cockpit", pid)


def serve_report_doc(pid, path):
    return serve_page_doc("report", pid)


# the cockpit opens the effort conversation (v1) and workbench terminal (v3)
# as iframes; Anchor serves them under /steward/<page> with the shim injected
_PAGES = {"v1": "v1.html", "v3": "v3.html", "report": "report.html",
          "cockpit": "cockpit.html"}


def serve_page_doc(page, pid=""):
    fname = _PAGES.get(page)
    if not fname:
        return None
    html = (STATIC / fname).read_text(encoding="utf-8")
    html = (html.replace('href="/static/', 'href="/steward-static/')
                .replace('src="/static/', 'src="/steward-static/')
                # Anchor serves brand marks at /vendor/brand/, not /brand/;
                # rewrite both the static hrefs and the JS "/brand/" base
                .replace('/brand/', '/vendor/brand/'))
    shim = _CLIENT_SHIM % (json.dumps(pid),
                           json.dumps(CONFIG.get("build") or ""))
    return html.replace("<script", shim + "<script", 1)


def _effort_dir(proot, rel):
    """Resolve an effort rel-name to its dir, refusing anything not discovered."""
    rel = (rel or "").strip()
    for e in campaign.discover_efforts(proot):
        if e["rel"] == rel:
            return str(Path(proot) / rel) if rel else proot
    return None


# project-level verbs read the whole project; effort-level verbs read one effort
_PROJECT_VERBS = {"efforts", "grass", "boneyard", "skills", "gandalf",
                  "deliverables", "new_effort", "boneyard_restore"}


def api_get(proot, verb, qs):
    if verb == "events":
        cdir = _effort_dir(proot, qs.get("dir", ""))
        if cdir is None:
            return {"error": "unknown effort"}, 404
        return events(cdir, qs)
    if verb in _PROJECT_VERBS or verb in ("terms",):
        return handle_get(proot, verb, qs)
    cdir = _effort_dir(proot, qs.get("dir", ""))
    if cdir is None:
        return {"error": "unknown effort"}, 404
    return handle_get(cdir, verb, qs)


def api_post(proot, verb, body):
    if verb in ("new_effort", "boneyard_restore", "boneyard_move",
                "rename_effort"):
        return _project_post(proot, verb, body)
    cdir = _effort_dir(proot, body.get("dir", ""))
    if cdir is None:
        return {"ok": False, "error": "unknown effort"}, 404
    return handle_post(cdir, verb, body)


def _project_post(proot, verb, body):
    if verb == "new_effort":
        return _new_effort(proot, body)
    if verb == "boneyard_restore":
        name = Path(str(body.get("name", ""))).name
        if not re.fullmatch(r"[\w\- ]{1,60}", name):
            return {"ok": False, "error": "bad name"}, 400
        src = Path(proot) / BONEYARD / name
        dst = Path(proot) / name
        if not (src / "ECGBERHT.md").is_file():
            return {"ok": False, "error": "not in the boneyard"}, 404
        if dst.exists():
            return {"ok": False, "error": "a live effort already has that name"}, 409
        src.rename(dst)
        return {"ok": True, "rel": name}, 200
    if verb == "rename_effort":
        # Effort names are the USER'S to set (John, 2026-08-25) — this is the
        # sanctioned rename path: stops the effort's engines cleanly (refusing
        # mid-turn), renames the dir, migrates the engine-state keys so usage
        # and saved sessions follow. The model-side CLI session cannot resume
        # across a cwd change, so the steward stands back up from the record.
        rel = body.get("dir", "")
        if not rel:
            return {"ok": False, "error":
                    "the project root is renamed in Anchor, not here"}, 400
        cdir = _effort_dir(proot, rel)
        if cdir is None:
            return {"ok": False, "error": "unknown effort"}, 404
        name, err = _validate_effort_name(body.get("name", ""))
        if err:
            return {"ok": False, "error": err}, 400
        dst = Path(proot) / name
        if dst.exists():
            return {"ok": False, "error": "an effort already has that name"}, 409
        with ENGINES_LOCK:
            keys = [k for k in ENGINES if k == cdir or k.startswith(cdir + "||")]
            if any(ENGINES[k].alive() and (ENGINES[k].busy or ENGINES[k].queue)
                   for k in keys):
                return {"ok": False, "error":
                        "finish or pause the current turn before renaming"}, 409
            engs = [ENGINES.pop(k) for k in keys]
        for e in engs:
            try:
                e.stop()
            except Exception:
                pass
        try:
            Path(cdir).rename(dst)
        except OSError as e:
            return {"ok": False, "error": f"could not rename: {e}"}, 500
        try:
            from steward_cockpit.steward_engine import rename_state_keys
            rename_state_keys(cdir, str(dst))
        except Exception:
            pass
        return {"ok": True, "rel": name}, 200
    if verb == "boneyard_move":
        rel = body.get("dir", "")
        if not rel:
            return {"ok": False, "error": "the project root cannot be boneyarded"}, 400
        cdir = _effort_dir(proot, rel)
        if cdir is None:
            return {"ok": False, "error": "unknown effort"}, 404
        with ENGINES_LOCK:
            keys = [k for k in ENGINES if k == cdir or k.startswith(cdir + "||")]
            engs = [ENGINES.pop(k) for k in keys]
        for e in engs:
            try:
                e.stop()
            except Exception:
                pass
        yard = Path(proot) / BONEYARD
        yard.mkdir(exist_ok=True)
        dst = yard / Path(cdir).name
        if dst.exists():
            return {"ok": False, "error": "name collision in the boneyard"}, 409
        try:
            Path(cdir).rename(dst)
        except OSError as e:
            return {"ok": False, "error": f"could not archive: {e}"}, 500
        return {"ok": True}, 200
    return {"ok": False, "error": "unknown"}, 404


# ---------- GET data ----------
def _efforts(cdir):
    out = []
    for e in campaign.discover_efforts(cdir):
        edir = str(Path(cdir) / e["rel"]) if e["rel"] else cdir
        m = campaign.read_map(edir)
        eng = ENGINES.get(m["dir"])
        active = next((s for s in m["steps"] if s["status"] == "active"), None)
        out.append({"rel": e["rel"], "name": e["name"],
                    # goal-derived rename suggestion (zero-model; the ✎
                    # prompt prefills it — user edits or replaces)
                    "suggested_name": campaign.suggest_effort_name(
                        m["goal_brief"]),
                    "light": eng.light() if eng else "orange",
                    "goal_brief": m["goal_brief"], "steps_done": m["steps_done"],
                    "steps_total": m["steps_total"],
                    "active_step": active["name"] if active else "",
                    "attention": m["attention"]["state"],
                    "human_wait": m["heartbeat"]["human_wait"],
                    "talked": m["freshness"]["talked"],
                    "touched": campaign.last_touched(edir),
                    "alive": bool(eng and eng.alive()),
                    "busy": bool(eng and eng.busy)})
    out.sort(key=lambda x: x["touched"], reverse=True)
    livery = campaign.STEWARD_LIVERY.get(CONFIG["steward"], {})
    est = campaign.STEWARD_LIVERY  # noqa
    return {"project": Path(cdir).name, "steward": CONFIG["steward"],
            "seal_icon": livery.get("seal_icon", ""),
            "seal_name": livery.get("seal_name", "Seal"),
            "seats": campaign.read_seats(),
            "usage": _usage_rollup(cdir), "efforts": out}


def _usage_rollup(cdir):
    zero = lambda: {"spend": 0.0, "tokens": 0, "secs": 0}
    from steward_cockpit.steward_engine import _read_all_state
    estate = _read_all_state()
    stew, term = zero(), zero()
    cdir_n = os.path.realpath(cdir)
    for key, entry in estate.items():
        base = os.path.realpath(key.split("||")[0])
        # exact boundary, not a string prefix: '.../foo' must not match '.../foobar'
        if base != cdir_n and not base.startswith(cdir_n + os.sep):
            continue
        u = entry.get("usage") or {}
        b = term if "||general||" in key else stew
        b["spend"] += u.get("spend", 0); b["tokens"] += u.get("tokens", 0)
        b["secs"] += u.get("secs", 0)
    total = {k: round(stew[k] + term[k], 4) for k in stew}
    return {"steward": stew, "terms": term, "total": total}


def handle_get(cdir, verb, qs):
    if verb == "deliverables":
        # 2026-08-25 (John's ask; campaign journal 0010 "where is the thing I paid
        # for?"): the effort's DELIVERABLES.md register, parsed disk-true — the ONE
        # source the tile, the map links, and the steward's own answer all read.
        return campaign.read_deliverables(cdir), 200
    if verb == "deliverable-file":
        # Serve ONE deliverable's bytes, HARD-CONTAINED to the effort dir (realpath
        # prefix check — ../ or symlink escapes 404; active content served inert).
        rel = str(qs.get("path", ""))
        creal = os.path.realpath(str(cdir))
        real = os.path.realpath(str(Path(cdir) / rel))
        if not (real == creal or real.startswith(creal + os.sep)) \
                or not os.path.isfile(real):
            return {"error": "not an openable deliverable (outside this effort or missing)"}, 404
        if os.path.getsize(real) > 50 * 1024 * 1024:
            return {"error": "file too large to serve inline (50MB cap)"}, 413
        ext = Path(real).suffix.lower()
        ctype = {
            ".pdf": "application/pdf",
            ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
            ".json": "application/json; charset=utf-8",
        }.get(ext, "text/plain; charset=utf-8")  # md/csv/html/svg served INERT as text
        return {"__file__": real, "__ctype__": ctype}, 200
    if verb == "efforts":
        return _efforts(cdir), 200
    if verb == "map":
        m = campaign.read_map(cdir)
        m["stamp"] = campaign.map_stamp(cdir)
        m["steward"] = CONFIG["steward"]
        return m, 200
    if verb == "history":
        return campaign.read_history(cdir), 200
    if verb == "state":
        eng = get_engine(cdir, qs.get("general") == "1", qs.get("term"))
        if eng is None:
            return {"error": "no such session"}, 404
        st = eng.state(); st["stamp"] = campaign.map_stamp(cdir)
        return st, 200
    if verb == "status":
        # the deterministic two-part 10-minute status, composed FRESH
        # (zero-model) — the same shape the engine's cadence persists to
        # .ecgberht/status-summary.json; the pane paints it on open
        eng = ENGINES.get(cdir)
        return campaign.compose_status(
            cdir, eng.state() if eng else None), 200
    if verb == "grass":
        return {"grass": campaign.read_grass(cdir)}, 200
    if verb == "boneyard":
        return {"boneyard": campaign.list_boneyard(cdir)}, 200
    if verb == "skills":
        return {"skills": SKILLS}, 200
    if verb == "terms":
        return {"terms": _terms_view(cdir)}, 200
    if verb == "gandalf":
        return {"runs": _gandalf_runs(cdir)}, 200
    if verb == "deliverables":
        return {"deliverables": _deliverables(cdir)}, 200
    if verb == "files":
        return _files(cdir, qs.get("sub", ""), qs.get("q", "").strip().lower())
    if verb == "filetext":
        return _filetext(cdir, qs.get("path", ""))
    return {"error": "unknown"}, 404


def events(cdir, qs):
    eng = get_engine(cdir, qs.get("general") == "1", qs.get("term"))
    if eng is None:
        return {"error": "no such session"}, 404
    try:
        since = int(qs.get("since", "0"))
    except (ValueError, TypeError):
        since = 0
    evs, oldest, gap = eng.events_since(since, timeout=8)
    return {"events": evs, "state": eng.state(), "oldest_seq": oldest,
            "gap": gap, "stamp": campaign.map_stamp(cdir)}, 200


def _terms_view(cdir):
    from steward_cockpit.steward_engine import _read_all_state
    estate = _read_all_state()
    out = []
    for tid, meta in _load_terms(cdir).items():
        key = cdir + f"||general||{tid}"
        eng = ENGINES.get(key)
        entry = estate.get(key, {})
        out.append({"tid": tid, "label": meta.get("label", "term " + tid),
                    "created": meta.get("created", ""),
                    "archived": bool(meta.get("archived")),
                    "alive": bool(eng and eng.alive()),
                    "busy": bool(eng and eng.busy),
                    "saved": bool(entry.get("session_id")),
                    "cli": (eng.cli if eng else entry.get("cli", "claude")),
                    "last_used": entry.get("last_used", ""),
                    "last_text": entry.get("last_text", ""),
                    "usage": entry.get("usage", {})})
    out.sort(key=lambda t: (t["alive"], t["last_used"] or t["created"]),
             reverse=True)
    return out


def _gandalf_runs(cdir):
    runs, gdir = [], Path(cdir) / "gandalf"
    if not gdir.is_dir():
        return runs
    for rd in sorted(gdir.iterdir(), reverse=True):
        if not rd.name.startswith("run-") or not rd.is_dir():
            continue
        summary = ""
        for cand in ("exec-summary.md", "report.md"):
            try:
                summary = (rd / cand).read_text(encoding="utf-8",
                                                errors="replace")[:2600]
                break
            except OSError:
                continue
        finding, points = "", []
        m = re.search(r"^\**Bottom line:?\**[:\s]*(.+)$", summary,
                      re.MULTILINE | re.IGNORECASE)
        if m:
            finding = m.group(1).strip()
        try:
            adv = json.loads((rd / "advisor-output.json").read_text(
                encoding="utf-8", errors="replace"))
            for f in (adv.get("findings") or [])[:3]:
                if isinstance(f, dict) and f.get("verdict"):
                    points.append(" ".join(str(f["verdict"]).replace("**", "").split())[:260])
            if not finding and points:
                finding = points[0]
        except Exception:
            pass
        try:
            ts = int(rd.name.split("-")[1]) / 1000
            when = time.strftime("%Y-%m-%d", time.localtime(ts))
        except Exception:
            when = ""
        runs.append({"id": rd.name, "when": when, "summary": summary,
                     "finding": finding[:230], "points": points,
                     "report_rel": f"gandalf/{rd.name}/report.md"
                        if (rd / "report.md").is_file() else "",
                     "exec_rel": f"gandalf/{rd.name}/exec-summary.md"
                        if (rd / "exec-summary.md").is_file() else ""})
        if len(runs) >= 8:
            break
    return runs


def _deliverables(cdir):
    from steward_cockpit.steward_engine import _read_all_state
    estate = _read_all_state()
    live = {os.path.realpath(str(Path(cdir) / e["rel"]) if e["rel"] else cdir)
            for e in campaign.discover_efforts(cdir)}
    seen, out = set(), []
    for key, entry in estate.items():
        base = key.split("||")[0]
        if os.path.realpath(base) not in live:
            continue
        src = (CONFIG["steward"] if "||general||" not in key
               else _load_terms(base).get(key.rsplit("||", 1)[-1], {})
                    .get("label", "term"))
        effort = Path(base).name
        for f in entry.get("files", []):
            if f in seen:
                continue
            seen.add(f)
            try:
                mt = int(os.stat(f).st_mtime); exists = True
            except OSError:
                mt, exists = 0, False
            try:
                rel_path = os.path.relpath(f, base).replace(os.sep, "/")
            except ValueError:
                continue
            if rel_path.startswith(".."):
                continue
            out.append({"dir": "" if base == cdir else effort, "path": rel_path,
                        "name": Path(f).name, "effort": effort, "src": src,
                        "mtime": mt, "exists": exists})
    out.sort(key=lambda x: x["mtime"], reverse=True)
    return out[:80]


def _files(cdir, sub, q):
    base = os.path.realpath(cdir)
    target = os.path.realpath(os.path.join(cdir, sub)) if sub else base
    if target != base and not target.startswith(base + os.sep):
        return {"error": "outside the effort"}, 400
    entries = []
    if q:
        hits = 0
        for root_, dirs, files_ in os.walk(base):
            dirs[:] = [x for x in dirs if not x.startswith((".", "_"))
                       and x not in ("node_modules", "vendor")]
            if root_[len(base):].count(os.sep) > 5:
                dirs[:] = []; continue
            for name in files_:
                if name.startswith((".", "_")):
                    continue
                if q in name.lower():
                    full = os.path.join(root_, name)
                    try:
                        st_ = os.stat(full); size, mt = st_.st_size, st_.st_mtime
                    except OSError:
                        size, mt = 0, 0
                    entries.append({"name": os.path.relpath(full, base).replace(os.sep, "/"),
                                    "dir": False, "size": size, "mtime": int(mt)})
                    hits += 1
                    if hits >= 300:
                        break
            if hits >= 300:
                break
    else:
        try:
            for name in sorted(os.listdir(target))[:250]:
                if name.startswith((".", "_")) or name == "node_modules":
                    continue
                full = os.path.join(target, name)
                isdir = os.path.isdir(full)
                try:
                    st_ = os.stat(full); size, mt = st_.st_size, st_.st_mtime
                except OSError:
                    size, mt = 0, 0
                entries.append({"name": name, "dir": isdir, "size": size,
                                "mtime": int(mt)})
        except OSError as e:
            return {"error": str(e)}, 500
    return {"sub": sub, "q": q, "entries": entries}, 200


def _filetext(cdir, fpath):
    parts = [x for x in re.split(r"[\\/]+", fpath) if x]
    if not parts or any(_bad_component(x) for x in parts):
        return {"error": "bad path"}, 400
    base = os.path.realpath(cdir)
    target = os.path.realpath(os.path.join(cdir, fpath))
    if target != base and not target.startswith(base + os.sep):
        return {"error": "outside the effort"}, 400
    if not target.lower().endswith((".md", ".txt", ".json", ".csv", ".log")):
        return {"error": "not a text report"}, 415
    try:
        return {"text": Path(target).read_text(encoding="utf-8",
                                               errors="replace")[:400_000]}, 200
    except OSError as e:
        return {"error": str(e)}, 404


# ---------- POST acts ----------
def handle_post(cdir, verb, body):
    if verb == "drain-all":
        # 2026-08-25 hardening (review finding #1): the restart drain runs in a SEPARATE
        # process, so it can never see this service's live ENGINES — the in-process leg
        # was a structural no-op. The drain now POSTs here and THE SERVICE parks its own
        # engines: stop() commits a dirty steward tree and closes the proc; resume stays
        # seamless. Report distinguishes parked / already-idle — never a vacuous empty.
        report = {"parked": [], "idle": [], "errors": []}
        for key, eng in list(ENGINES.items()):
            try:
                if eng.alive():
                    eng.stop()
                    report["parked"].append(str(key))
                else:
                    report["idle"].append(str(key))
            except Exception as e:
                report["errors"].append(f"{key}: {type(e).__name__}: {e}")
        report["ok"] = not report["errors"]
        return report, 200
    if verb == "status-ack":
        # 2026-08-25 (elegance S-batch): render receipt from the pane — never
        # spawns an engine (create=False); a dead engine just means no receipt.
        eng = get_engine(cdir, bool(body.get("general")),
                         str(body.get("term") or "") or None, create=False)
        if eng is None:
            return {"ok": False, "error": "no live engine"}, 404
        return eng.record_status_ack(str(body.get("at") or "")), 200
    if verb == "say":
        eng = get_engine(cdir, bool(body.get("general")),
                         str(body.get("term") or "") or None)
        if eng is None:
            return {"ok": False, "error": "no such session / cap hit"}, 404
        return eng.say(body.get("text", "")), 200
    if verb == "engine":
        eng = get_engine(cdir, bool(body.get("general")),
                         str(body.get("term") or "") or None)
        if eng is None:
            return {"ok": False, "error": "no such session"}, 404
        action = body.get("action")
        if action == "wake":
            ok, why = eng.wake(fresh=bool(body.get("fresh")))
            return {"ok": ok, "why": why}, 200
        if action == "stop":
            eng.stop(); return {"ok": True}, 200
        if action in ("drive_on", "drive_off"):
            eng.set_drive(action == "drive_on"); return {"ok": True, "drive": eng.drive}, 200
        if action == "switch":
            return eng.switch_cli(body.get("cli", "")), 200
        return {"ok": False, "error": "unknown action"}, 400
    if verb == "open":
        target = os.path.realpath(os.path.join(cdir, body.get("path", "")))
        if not target.startswith(os.path.realpath(cdir) + os.sep):
            return {"ok": False, "error": "outside the effort"}, 400
        if os.path.splitext(target)[1].lower() not in OPENABLE_EXT:
            return {"ok": False, "error": "that file type is not openable here"}, 400
        if not os.path.isfile(target):
            return {"ok": False, "error": "file not found"}, 404
        try:
            os.startfile(target); return {"ok": True}, 200
        except Exception as e:
            return {"ok": False, "error": str(e)}, 500
    if verb == "term_new":
        with TERMS_LOCK:
            terms = _load_terms(cdir)
            tid = str(max([int(k) for k in terms] or [0]) + 1)
            terms[tid] = {"label": "terminal " + tid,
                          "created": time.strftime("%Y-%m-%d %H:%M"),
                          "archived": False}
            _save_terms(cdir, terms)
        return {"ok": True, "tid": tid}, 200
    if verb in ("term_archive", "term_restore"):
        tid = str(body.get("tid", ""))
        to_stop = None
        with TERMS_LOCK:
            terms = _load_terms(cdir)
            meta = terms.get(tid)
            if not meta:
                return {"ok": False, "error": "unknown terminal"}, 404
            if verb == "term_archive":
                live = ENGINES.get(cdir + f"||general||{tid}")
                if live and live.alive():
                    to_stop = live
                meta["archived"] = True
            else:
                meta["archived"] = False
            _save_terms(cdir, terms)
        if to_stop is not None:
            to_stop.stop()
        return {"ok": True}, 200
    if verb == "upload":
        return _upload(cdir, body)
    if verb == "new_effort":
        return _new_effort(cdir, body)
    return {"ok": False, "error": "unknown"}, 404


def _upload(cdir, body):
    name = Path(str(body.get("name", ""))).name
    mode = body.get("mode", "new")
    sub = str(body.get("sub", "") or "")
    if _bad_component(name):
        return {"ok": False, "error": "bad file name"}, 400
    if Path(name).suffix.lower() in DENY_UPLOAD_EXT:
        return {"ok": False, "error": "that file type can't be loaded in"}, 400
    if sub and any(_bad_component(p) for p in re.split(r"[\\/]+", sub) if p):
        return {"ok": False, "error": "bad folder"}, 400
    base = os.path.realpath(cdir)
    folder = os.path.realpath(os.path.join(cdir, sub)) if sub else base
    if folder != base and not folder.startswith(base + os.sep):
        return {"ok": False, "error": "outside the effort"}, 400
    try:
        data = base64.b64decode(body.get("data_b64", ""), validate=True)
    except Exception:
        return {"ok": False, "error": "bad file data"}, 400
    if len(data) > 30_000_000:
        return {"ok": False, "error": "over 30 MB"}, 413
    dst = Path(folder) / name
    if dst.exists() and mode == "new":
        return {"ok": False, "exists": True, "name": name}, 200
    if dst.exists() and mode == "keepboth":
        n = 1
        while dst.exists():
            dst = Path(folder) / f"{Path(name).stem} ({n}){Path(name).suffix}"; n += 1
    final = os.path.realpath(dst)
    if final != base and not final.startswith(base + os.sep):
        return {"ok": False, "error": "refused (link escapes effort)"}, 400
    if os.path.islink(dst):
        return {"ok": False, "error": "refused (target is a link)"}, 400
    dst.write_bytes(data)
    return {"ok": True, "name": dst.name}, 200


def _validate_effort_name(raw):
    """Effort names are HUMAN names → ``(clean_name, None)`` or
    ``(None, error)``. Guarded because on 2026-08-25 a token-shaped paste rode
    into the new-effort prompt and became a live effort's directory name (the
    name IS the display name everywhere): refuse the configured Anchor token
    outright, and refuse anything shaped like a pasted secret/id — one long
    unbroken word mixing upper, lower and digits."""
    raw = str(raw or "")
    name = re.sub(r"[^\w\- ]+", "", raw).strip()[:60]
    if not name:
        return None, "give it a short name"
    tok = str(CONFIG.get("anchor_token") or "")
    if tok and tok in raw:
        return None, ("that is your Anchor access token, not a name - pick a "
                      "plain name (and consider rotating the token)")
    if (len(name) >= 24 and " " not in name
            and re.search(r"[A-Z]", name) and re.search(r"[a-z]", name)
            and re.search(r"\d", name)):
        return None, ("that looks like a pasted token or id - give the effort "
                      "a short human name (a few words)")
    return name, None


def _new_effort(cdir, body):
    name, err = _validate_effort_name(body.get("name", ""))
    if err:
        return {"ok": False, "error": err}, 400
    d = Path(cdir) / name
    if (d / "ECGBERHT.md").exists():
        return {"ok": False, "error": "that effort already exists"}, 409
    d.mkdir(exist_ok=True)
    (d / "ECGBERHT.md").write_text(
        "# Ecgberht — Face (campaign memory)\n\n## North star\n\n\n"
        "## Active effort\n\n- None yet.\n\n## Why next\n\n- Stand-up: John "
        "describes the effort; the steward drafts the goal and the map.\n\n"
        "## Human wait\n\n- John: describe this effort.\n", encoding="utf-8")
    return {"ok": True, "rel": name}, 200
