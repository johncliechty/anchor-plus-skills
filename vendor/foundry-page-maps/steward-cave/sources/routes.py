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
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
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
UPLOAD_LOCK = threading.Lock()

_UPLOAD_MODES = frozenset(("new", "replace", "keepboth"))
_UPLOAD_TEMP_PREFIX = ".anchor-upload-"

# persona + fake flag injected by anchor_gui at mount time
CONFIG = {"steward": "Ecgberht", "fake": False, "permission_mode": "bypassPermissions"}
BONEYARD = campaign.BONEYARD_DIRNAME
SKILLS = ["researchPrime", "Crucible", "Foreman", "Gandalf", "Jumper",
          "Superjump",
          "ramanujan", "legal-beagle", "financial-analyst",
          "literature-review", "tidy-idy", "chekhov"]
# (2026-09-05, John) every skill has a brand mark under /vendor/brand/; the cockpit
# reaches it as /brand/<file>. The client twin is static/skill-icons.js.
SKILL_ICONS = {
    "researchPrime": "research-prime-icon.jpg", "Crucible": "crucible-icon.svg",
    "Foreman": "foreman-icon.svg", "Gandalf": "gandalf-icon.jpg", "Jumper": "jumper-icon.jpg",
    "Superjump": "superjump-icon.jpg",
    "ramanujan": "ramanujan-icon.jpg", "legal-beagle": "legal-beagle-icon.jpg",
    "financial-analyst": "financial-analyst-icon.jpg",
    "literature-review": "literature-review-icon.jpg", "tidy-idy": "tidy-idy-icon.jpg",
    "zombie-hunter": "zombie-hunter-radar.jpg", "Ecgberht": "ecgberht-project-seal.jpg",
    "chekhov": "chekhov-icon.svg",
}
SKILL_ICON_FALLBACK = "gwl-m-icon.svg"


def skill_icon(name):
    """The brand file for a skill name (case-insensitive); the GWL mark when unknown."""
    key = str(name or "").strip().lower()
    for k, v in SKILL_ICONS.items():
        if k.lower() == key:
            return v
    return SKILL_ICON_FALLBACK
# (2026-09-05, John) every skill has a brand mark under /vendor/brand/; the cockpit
# reaches it as /brand/<file>. The client twin is static/skill-icons.js.
SKILL_ICONS = {
    "researchPrime": "research-prime-icon.jpg", "Crucible": "crucible-icon.svg",
    "Foreman": "foreman-icon.svg", "Gandalf": "gandalf-icon.jpg", "Jumper": "jumper-icon.jpg",
    "Superjump": "superjump-icon.jpg",
    "ramanujan": "ramanujan-icon.jpg", "legal-beagle": "legal-beagle-icon.jpg",
    "financial-analyst": "financial-analyst-icon.jpg",
    "literature-review": "literature-review-icon.jpg", "tidy-idy": "tidy-idy-icon.jpg",
    "zombie-hunter": "zombie-hunter-radar.jpg", "Ecgberht": "ecgberht-project-seal.jpg",
    "chekhov": "chekhov-icon.svg",
}
SKILL_ICON_FALLBACK = "gwl-m-icon.svg"


def skill_icon(name):
    """The brand file for a skill name (case-insensitive); the GWL mark when unknown."""
    key = str(name or "").strip().lower()
    for k, v in SKILL_ICONS.items():
        if k.lower() == key:
            return v
    return SKILL_ICON_FALLBACK


# ---------- terminal registry (per campaign dir) ----------
def _terms_file(cdir):
    return Path(cdir) / ".anchor" / "steward-terms.json"


def _load_terms(cdir):
    try:
        return json.loads(_terms_file(cdir).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_terms(cdir, terms):
    f = _terms_file(cdir)
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(terms, indent=2), encoding="utf-8")
    os.replace(tmp, f)


def _bad_component(name):
    s = str(name)
    return (not s or s.startswith(".") or s.startswith("_")
            or ":" in s or s.rstrip() != s or s.rstrip(".") != s
            or "/" in s or "\\" in s)


def proceed_on_silence_sweep(now=None):
    """On the server's reconcile tick: every steward whose saved decision is reversible, carries an
    undo and a recommendation, and has waited SILENCE_SECONDS proceeds - a sleeping steward wakes
    for it. Returns the campaign dirs that proceeded."""
    from steward_cockpit.steward_engine import _read_all_state, SILENCE_SECONDS
    now = time.time() if now is None else now
    done = []
    for key, entry in _read_all_state().items():
        if "||general||" in key or not isinstance(entry, dict):
            continue
        q = entry.get("question_context")
        if not isinstance(q, dict) or q.get("reversible") is not True or not q.get("undo") or not q.get("recommendation"):
            continue
        asked = q.get("asked_at")
        if not isinstance(asked, (int, float)) or isinstance(asked, bool) or now - asked < SILENCE_SECONDS:
            continue
        eng = get_engine(key)
        if eng is None:
            continue
        try:
            if eng.proceed_on_silence(q.get("id"), now=now).get("ok"):
                done.append(key)
        except Exception:
            continue
    return done


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


def rename_stewards(label):
    """The persona changed (2026-10-05, his word: the persona is not what the steward knows - switching it must never
    look like forgetting): every live steward takes the new name for its next wake and its page labels. Storage never
    depended on it (state, logs and engines are keyed by folder); only this cached name lagged."""
    label = str(label or "").strip()
    if not label:
        return 0
    CONFIG["steward"] = label
    n = 0
    with ENGINES_LOCK:
        for eng in ENGINES.values():
            if getattr(eng, "steward", None) != label:
                eng.steward = label
                n += 1
    return n


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


_CLIENT_SHIM = """<script src="/static/app-frame.js"></script><script>
window.STEWARD_PID = %s;
window.STEWARD_BUILD = %s;
window.STEWARD_MODE = %s;
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
      if(u.indexOf('/api/rnd/')===0 || u.indexOf('/api/version')===0){o=auth(o);}
      else if(u.indexOf('/api/')===0){u='/api/steward/'+u.slice(5);
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
  // Never mid-dictation (the Anchor app, 2026-10-02): a reload waits while a box holds unsent words or
  // took input in the last ten seconds; the next check (30 s) tries again.
  // The say box lives in the chamber (v1/v3), a frame inside the cockpit: a focused frame asks its own guard.
  var _lastIn=0;document.addEventListener('input',function(){_lastIn=Date.now();},true);
  function _busy(){var ae=document.activeElement;
    if(Date.now()-_lastIn<10000)return true;
    if(!ae)return false;
    if(ae.tagName==='IFRAME'){try{var b=ae.contentWindow.__stewardBusy;return !!(b&&b());}catch(_){return false;}}
    return !!((ae.tagName==='TEXTAREA'||(ae.tagName==='INPUT'&&/^(text|search|)$/i.test(ae.type||'')))&&ae.value);}
  window.__stewardBusy=_busy;
  if (window.STEWARD_BUILD) setInterval(function(){
    _f('/api/version', {cache:'no-store'}).then(function(r){return r.json();})
      .then(function(j){
        var v = j && j.version;
        if (!v || v === window.STEWARD_BUILD || _busy()) return;
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


def _mode_name():
    """The Campaign's mode name for the persona (Star Chart / Chart Room / Beacon, 2026-10-03); "" when unreadable."""
    try:
        import anchor_settings as _aset
        return str(_aset.steward_profile().get("campaign_name") or "")
    except Exception:
        return ""


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
                           json.dumps(CONFIG.get("build") or ""), json.dumps(_mode_name()))
    return html.replace("<script", shim + '<script src="/steward-static/notebook-actions.js"></script><script', 1)


def _effort_dir(proot, rel):
    """Resolve an effort rel-name to its dir, refusing anything not discovered."""
    rel = (rel or "").strip()
    for e in campaign.discover_efforts(proot):
        if e["rel"] == rel:
            return str(Path(proot) / rel) if rel else proot
    return None


# project-level verbs read the whole project; effort-level verbs read one effort
# (2026-08-25 fix: "deliverables" was BOTH here and an effort-level handler —
# the project routing won, so the register tile read the project ROOT and the
# legacy session-files tab got shadowed by the register handler. Two surfaces,
# one collision, both blank on John's screen while every unit test passed,
# because the tests pinned handle_get and never this dispatch. The register
# verb "deliverables" is effort-level; the legacy files-produced view is now
# its own project verb "session-files".)
_PROJECT_VERBS = {"efforts", "grass", "boneyard", "skills", "gandalf",
                  "session-files", "register-all", "new_effort",
                  "boneyard_restore"}
# Files/upload/open are the PROJECT folder, not an effort. The cockpit
# always sends dir="" — if we resolve that through discover_efforts and the
# root has no Face, the files tile was an honest empty while the folder
# was full (2026-08-28).
_PROJECT_FILE_VERBS = {"files", "filetext", "upload", "open", "notebook-open",
                       "notebook-register", "notebook-status", "deliverable-file"}


_PROJECT_TERMINAL_VERBS = {"term_new", "term_archive", "term_restore"}
_GENERAL_READ_VERBS = {"map", "history", "state", "events", "deliverables"}
_GENERAL_POST_VERBS = {"say", "engine"}


def _registered_project_terminal(proot, raw_tid):
    tid = str(raw_tid or "")
    if not re.fullmatch(r"\d{1,6}", tid):
        return False
    record = _load_terms(proot).get(tid)
    return isinstance(record, dict) and not record.get("archived")


def api_get(proot, verb, qs):
    if qs.get("general") == "1" and not (qs.get("dir") or "").strip():
        if verb in _GENERAL_READ_VERBS:
            if not _registered_project_terminal(proot, qs.get("term")):
                return {"error": "no such project terminal"}, 404
            return events(proot, qs) if verb == "events" else handle_get(proot, verb, qs)
    if verb == "events":
        cdir = _effort_dir(proot, qs.get("dir", ""))
        if cdir is None:
            return {"error": "unknown effort"}, 404
        return events(cdir, qs)
    if verb in _PROJECT_VERBS or verb in ("terms",) or verb in _PROJECT_FILE_VERBS:
        rel = (qs.get("dir") or "").strip()
        if verb in _PROJECT_FILE_VERBS and rel:
            cdir = _effort_dir(proot, rel)
            if cdir is None:
                return {"error": "unknown effort"}, 404
            return handle_get(cdir, verb, qs)
        return handle_get(proot, verb, qs)
    cdir = _effort_dir(proot, qs.get("dir", ""))
    if cdir is None:
        return {"error": "unknown effort"}, 404
    return handle_get(cdir, verb, qs)


def _busy_engine_keys():
    with ENGINES_LOCK:
        return [key for key, e in ENGINES.items() if e.alive() and e.busy]


def _running_job_ids():
    import job_runner as _jr
    return [str(r.get("job_id") or "?") for r in _jr.list_records()
            if r.get("status") == _jr.STATUS_RUNNING]


def api_post(proot, verb, body):
    if verb in ("new_effort", "boneyard_restore", "boneyard_move",
                "rename_effort"):
        return _project_post(proot, verb, body)
    rel = (body.get("dir") or "").strip()
    if not rel and verb in _PROJECT_TERMINAL_VERBS:
        return handle_post(proot, verb, body)
    if not rel and body.get("general") is True and verb in _GENERAL_POST_VERBS:
        if not _registered_project_terminal(proot, body.get("term")):
            return {"ok": False, "error": "no such project terminal"}, 404
        if body.get("refinement_context"):
            return {"ok": False, "error": "refinement belongs to its campaign"}, 400
        return handle_post(proot, verb, body)
    if verb in _PROJECT_FILE_VERBS and not rel:
        return handle_post(proot, verb, body)
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
        # resting in place (marker) → resurrect by removing the marker
        if (dst / "ECGBERHT.md").is_file() and campaign.is_retired_in_place(str(dst)):
            campaign.resurrect_in_place(str(dst))
            return {"ok": True, "rel": name, "in_place": True}, 200
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
        # (2026-09-03, John: "there was an error archiving") Windows refuses
        # the rename while anything inside is open — a deck in PowerPoint, an
        # Explorer window, a terminal's cwd, the engine we just stopped still
        # letting go. Retry briefly; if it still refuses, retire IN PLACE
        # (marker) — the effort leaves the live list and joins the boneyard
        # exactly as if moved, and nothing is lost.
        last = None
        for _i in range(5):
            try:
                Path(cdir).rename(dst)
                return {"ok": True, "in_place": False}, 200
            except OSError as e:
                last = e
                time.sleep(0.4)
        try:
            campaign.retire_in_place(cdir, "folder in use at retire time: %s" % last)
        except OSError as e:
            return {"ok": False, "error": f"could not archive: {e}"}, 500
        return {"ok": True, "in_place": True,
                "note": "retired in place — a file in it was open, so the folder "
                        "stayed where it is; it rests in the boneyard all the same"}, 200
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
            "usage": _usage_rollup(cdir), "efforts": out,
            "other_recorded_usage": _other_recorded_usage(cdir),
            "plates": campaign.list_plates(cdir)}


def _other_recorded_usage(cdir):
    """Expose saved run records separately; their overlap with cockpit usage is unknown."""
    import json
    import math

    result = {
        "scope": "separate run records; may overlap cockpit history",
        "status": "available", "records": [], "duplicate_count": 0,
        "conflict_count": 0, "unavailable_sources": [], "project_aliases": [],
    }

    def unavailable(source, project_id=None, lane=None):
        item = {"source": source, "status": "unavailable"}
        if project_id is not None:
            item["project_id"] = project_id
        if lane is not None:
            item["lane"] = lane
        result["unavailable_sources"].append(item)

    def nonnegative(value, integer=False):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        try:
            if not math.isfinite(value) or value < 0 or (integer and int(value) != value):
                return None
        except (OverflowError, ValueError):
            return None
        return int(value) if integer else float(value)

    try:
        import effort_history as eh
    except Exception:
        unavailable("effort-history-import")
        result["status"] = "unavailable"
        return result
    try:
        import rnd_registry
        projects = rnd_registry.list_projects()
        if not isinstance(projects, (list, tuple)):
            raise ValueError("invalid registry result")
    except Exception:
        unavailable("project-registry")
        result["status"] = "unavailable"
        return result

    try:
        target = os.path.normcase(os.path.realpath(cdir))
    except (OSError, ValueError, TypeError):
        unavailable("project-scope")
        result["status"] = "unavailable"
        return result
    aliases = {}
    for project in projects:
        if not isinstance(project, dict):
            continue
        folder = project.get("folder_path")
        project_id = project.get("id")
        if not isinstance(folder, str) or not folder.strip() or not isinstance(project_id, str) or not project_id:
            continue
        try:
            matches = os.path.normcase(os.path.realpath(folder)) == target
        except (OSError, ValueError):
            matches = False
        if matches:
            name = project.get("name")
            aliases[project_id] = {"id": project_id, "name": name[:160] if isinstance(name, str) else project_id}
    result["project_aliases"] = [aliases[key] for key in sorted(aliases)]
    groups = {}
    for project_id in sorted(aliases):
        for lane in eh.ROLLUP_LANES:
            try:
                records = eh.list_efforts(cdir, project_id, lane)
                if not isinstance(records, (list, tuple)):
                    raise ValueError("invalid effort history")
            except Exception:
                unavailable("effort-history", project_id, lane)
                continue
            for record in records:
                if not isinstance(record, dict):
                    unavailable("effort-history-record", project_id, lane)
                    continue
                try:
                    discovered = eh.is_discovered(record)
                except Exception:
                    unavailable("effort-history-record", project_id, lane)
                    continue
                if discovered:
                    continue
                cost = record.get("cost")
                cost = cost if isinstance(cost, dict) else {}
                if not cost and record.get("kind") != "run-cost":
                    continue
                cost_context = {field: cost.get(field, record.get(field))
                                for field in ("cost_state", "billing_mode", "cost_complete")}
                try:
                    # Different billing context must not disappear when equal saved
                    # dollar amounts are deduplicated, especially legacy zeros.
                    payload = json.dumps({"cost": cost, "context": cost_context}, sort_keys=True,
                                         separators=(",", ":"), ensure_ascii=False)
                except (TypeError, ValueError, OverflowError):
                    unavailable("effort-history-cost", project_id, lane)
                    continue
                identity_type, identity = None, None
                for field in ("engine_session_uuid", "session_id", "job_id"):
                    value = record.get(field)
                    if isinstance(value, str) and value.strip():
                        identity_type, identity = field, value
                        break
                identity_key = (identity_type, identity) if identity is not None else None
                group = groups.setdefault(identity_key, []) if identity_key is not None else []
                duplicate = next((row for saved_payload, row in group if saved_payload == payload), None)
                if duplicate is not None:
                    if project_id not in duplicate["project_ids"]:
                        duplicate["project_ids"].append(project_id)
                    if lane not in duplicate["lanes"]:
                        duplicate["lanes"].append(lane)
                    result["duplicate_count"] += 1
                    continue
                saved_usd = nonnegative(cost.get("total_cost_usd"))
                cost_state = cost.get("cost_state", record.get("cost_state"))
                billing_mode = cost.get("billing_mode", record.get("billing_mode"))
                cost_complete = cost.get("cost_complete", record.get("cost_complete"))
                has_cost_context = (
                    isinstance(cost_state, str) and bool(cost_state.strip()) or
                    isinstance(billing_mode, str) and bool(billing_mode.strip()) or
                    isinstance(cost_complete, bool)
                )
                zero_unverified = saved_usd == 0 and not has_cost_context
                cost_status = "unavailable" if saved_usd is None else (
                    "zero_requires_verification" if zero_unverified else
                    "partial" if cost_complete is False else "recorded")
                label = record.get("label")
                title = " ".join(label.split())[:160] if isinstance(label, str) and label.strip() else str(lane) + " run"
                row = {
                    "title": title, "lane": lane, "lanes": [lane], "project_ids": [project_id],
                    "identity_type": identity_type, "identity": identity,
                    "tokens": nonnegative(cost.get("total_tokens"), integer=True),
                    "saved_usd": saved_usd, "cost_status": cost_status,
                    "cost_zero_requires_verification": zero_unverified,
                    "source": "effort-history", "conflict": bool(group),
                }
                created_at = nonnegative(record.get("created_at"))
                if created_at is not None:
                    row["created_at"] = created_at
                if group:
                    if not any(previous["conflict"] for _, previous in group):
                        result["conflict_count"] += 1
                    for _, previous in group:
                        previous["conflict"] = True
                if identity_key is not None:
                    group.append((payload, row))
                result["records"].append(row)
    if result["unavailable_sources"]:
        result["status"] = "partial" if result["records"] else "unavailable"
    return result


def _usage_rollup(cdir, estate=None):
    numeric_fields = ("reported_spend", "unpriced_turns", "estimated_spend", "estimated_turns", "tokens", "secs")
    coverage_fields = ("tracked_invocations", "reported_invocations", "partial_invocations",
                       "unavailable_invocations", "finalized_invocations")
    def zero():
        return {"reported_spend": 0.0, "unpriced_turns": 0, "estimated_spend": 0.0, "estimated_turns": 0, "tokens": 0, "secs": 0,
                "checkpoint_coverage": {field: 0 for field in coverage_fields},
                "usage_updated_at": None, "_cost_known": 0, "_cost_unknown": 0,
                "_tokens_known": 0, "_tokens_unknown": 0, "_tokens_partial": 0,
                "_sub_unpriced": 0, "_other_unpriced": 0, "_sub_clis": []}
    def number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < float("inf")
    from steward_cockpit.steward_engine import (
        _read_all_state, _usage_snapshot, fmt_usage_cost_text, infer_subscription_cli)
    if estate is None:
        estate = _read_all_state()
    stew, term = zero(), zero()
    cdir_n = os.path.realpath(cdir)
    for key, entry in estate.items():
        base = os.path.realpath(key.split("||")[0])
        # exact boundary, not a string prefix: '.../foo' must not match '.../foobar'
        if base != cdir_n and not base.startswith(cdir_n + os.sep):
            continue
        raw = entry.get("usage")
        u = _usage_snapshot(raw)
        b = term if "||general||" in key else stew
        for field in numeric_fields:
            b[field] += u[field]
        coverage = u.get("checkpoint_coverage") or {}
        for field in coverage_fields:
            value = coverage.get(field)
            if number(value):
                b["checkpoint_coverage"][field] += value
        updated = u.get("usage_updated_at")
        if isinstance(updated, str) and updated:
            b["usage_updated_at"] = max(b["usage_updated_at"] or updated, updated)
        raw = raw if isinstance(raw, dict) else {}
        activity = any(number(u.get(field)) and u[field] > 0 for field in numeric_fields)
        activity = activity or (number(coverage.get("tracked_invocations")) and coverage["tracked_invocations"] > 0)
        active_checkpoints = (number(coverage.get("tracked_invocations")) and
                              number(coverage.get("finalized_invocations")) and
                              coverage["tracked_invocations"] > coverage["finalized_invocations"])
        incomplete = (u.get("cost_status") == "partial" or u.get("cost_complete") is False or
                      u["unpriced_turns"] > 0 or active_checkpoints)
        explicit_cost = any(number(raw.get(field)) for field in ("spend", "reported_spend"))
        cost_known = u["reported_spend"] > 0 or (explicit_cost and not incomplete)
        if u.get("cost_status") == "unavailable":
            cost_known = False
        b["_cost_known"] += int(cost_known)
        b["_cost_unknown"] += int(incomplete or (activity and not cost_known))
        token_status = u.get("token_status")
        tokens_known = token_status == "reported" or u["tokens"] > 0 or (
            token_status == "partial" and number(coverage.get("reported_invocations")) and coverage["reported_invocations"] > 0)
        if token_status == "unavailable":
            tokens_known = False
        b["_tokens_known"] += int(tokens_known)
        b["_tokens_unknown"] += int(activity and not tokens_known)
        b["_tokens_partial"] += int(token_status == "partial")
        family = infer_subscription_cli(entry.get("cli"), raw.get("usage_source") or u.get("usage_source"))
        if u["unpriced_turns"] > 0:
            if family:
                b["_sub_unpriced"] += u["unpriced_turns"]
                if family not in b["_sub_clis"]:
                    b["_sub_clis"].append(family)
            else:
                b["_other_unpriced"] += u["unpriced_turns"]
    # (Wave 2 S1) delegated jobs are a source of their own, beside the total the
    # dashboard already reads as the steward's figure: the rows the seam indexed
    # for this effort's project, joined by the folder the job ran in (this effort
    # dir or under it). One small doc per project — never a scan of rnd_jobs or
    # the ledger on a poll. Shown only when rows exist; "unknown" counts jobs
    # whose usage never reached us, never a zero.
    jobs = zero()
    jobs["count"], jobs["unknown"] = 0, 0
    # (S2) sub-agents the stewards of this effort spawned: count, tokens, unknown
    children = zero()
    children["count"], children["unknown"] = 0, 0
    # (S3) trio seats the skills of this effort ran: priced, unpriced or unknown, like
    # jobs; a seat that is a job's own engine session or a recorded child is not
    # counted twice (the job or the child wins)
    seats = zero()
    seats["count"], seats["unknown"] = 0, 0
    try:
        import usage_capture as _uc
        import usage_index as _ui
        project_id = _uc.resolve_project(cdir)[0]
        rows = _ui.load_rows(project_id) if project_id else []
    except Exception:
        rows = []
    owned = {row.get("engine_session_uuid") for row in rows
             if isinstance(row, dict) and row.get("source") == "job" and row.get("engine_session_uuid")}
    owned |= {row.get("native_id") for row in rows
              if isinstance(row, dict) and row.get("source") == "subagent" and row.get("native_id")}
    cdir_c = os.path.normcase(cdir_n)
    cdir_prefix = cdir_c.rstrip(os.sep) + os.sep

    def in_scope(scope):
        return isinstance(scope, str) and (scope == cdir_c or scope.startswith(cdir_prefix))
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("source") == "subagent":
            if not in_scope(row.get("scope")):
                continue
            tokens = row.get("tokens")
            children["count"] += 1
            if number(tokens):
                children["tokens"] += tokens
            if row.get("usage_state") == "unknown":
                children["unknown"] += 1
                children["_tokens_unknown"] += 1
            else:
                children["unpriced_turns"] += 1
                children["_tokens_known"] += 1
            children["_cost_unknown"] += 1
            stamp = row.get("recorded_at")
            if isinstance(stamp, str) and stamp:
                children["usage_updated_at"] = max(children["usage_updated_at"] or stamp, stamp)
            continue
        if row.get("source") not in ("job", "seat"):
            continue
        # a job that ran in a worktree outside the project folder joins at the
        # project folder (Grok R1 F2); scopes were stamped at write time (F5)
        if not (in_scope(row.get("scope")) or in_scope(row.get("folder_scope"))):
            continue
        if row.get("source") == "seat" and (row.get("engine_session_uuid") in owned or row.get("native_id") in owned):
            continue
        b = jobs if row.get("source") == "job" else seats
        state, tokens, cost = row.get("usage_state"), row.get("tokens"), row.get("cost_usd")
        b["count"] += 1
        if number(tokens):
            b["tokens"] += tokens
        if number(row.get("duration_ms")):
            b["secs"] += row["duration_ms"] / 1000
        if state == "measured" and number(cost):
            b["reported_spend"] += cost
            b["_cost_known"] += 1
            b["_tokens_known"] += 1
        elif state == "unpriced":
            b["unpriced_turns"] += 1
            b["_cost_unknown"] += 1
            b["_tokens_known"] += 1
            family = infer_subscription_cli(row.get("cli"))
            if family:
                b["_sub_unpriced"] += 1
                if family not in b["_sub_clis"]:
                    b["_sub_clis"].append(family)
            else:
                b["_other_unpriced"] += 1
        else:
            b["unknown"] += 1
            b["_cost_unknown"] += 1
            b["_tokens_unknown"] += 1
        stamp = row.get("recorded_at")
        if isinstance(stamp, str) and stamp:
            b["usage_updated_at"] = max(b["usage_updated_at"] or stamp, stamp)
    total = zero()
    for field in numeric_fields + ("_cost_known", "_cost_unknown", "_tokens_known",
                                   "_tokens_unknown", "_tokens_partial",
                                   "_sub_unpriced", "_other_unpriced"):
        total[field] = round(stew[field] + term[field], 4)
    for field in coverage_fields:
        total["checkpoint_coverage"][field] = stew["checkpoint_coverage"][field] + term["checkpoint_coverage"][field]
    total["usage_updated_at"] = max(filter(None, (stew["usage_updated_at"], term["usage_updated_at"])), default=None)
    clis = []
    for family in stew["_sub_clis"] + term["_sub_clis"]:
        if family not in clis:
            clis.append(family)
    total["_sub_clis"] = clis
    private = ("_cost_known", "_cost_unknown", "_tokens_known", "_tokens_unknown",
               "_tokens_partial", "_sub_unpriced", "_other_unpriced", "_sub_clis")
    for bucket in (stew, term, jobs, children, seats, total):
        bucket["reported_spend"] = round(bucket["reported_spend"], 4)
        bucket["estimated_spend"] = round(bucket["estimated_spend"], 4)
        bucket["cost_status"] = "unavailable" if not bucket["_cost_known"] else (
            "partial" if bucket["_cost_unknown"] else "reported")
        bucket["cost_complete"] = bucket["cost_status"] == "reported"
        bucket["spend"] = bucket["reported_spend"] if bucket["cost_complete"] else None
        bucket["token_status"] = "unavailable" if not bucket["_tokens_known"] else (
            "partial" if bucket["_tokens_unknown"] or bucket["_tokens_partial"] else "reported")
        bucket["usage_source"] = "persisted session records"
        bucket["usage_basis"] = "recorded"
        if bucket["_sub_unpriced"] > 0 and bucket["_other_unpriced"] <= 0:
            bucket["billing_mode"] = "subscription"
            families = bucket["_sub_clis"]
            bucket["billing_family"] = families[0] if len(families) == 1 else "mixed"
        else:
            bucket["billing_mode"] = None
            bucket["billing_family"] = None
        bucket["cost_text"] = fmt_usage_cost_text(bucket, cli=bucket.get("billing_family"))
        for field in private:
            del bucket[field]
    return {"steward": stew, "terms": term, "jobs": jobs, "children": children, "seats": seats, "total": total}


def _state_with_usage(eng, cdir):
    state = eng.state()
    state["usage_rollup"] = _usage_rollup(cdir)
    return state

def render_brief(proot, rel):
    """(Wave D1, 2026-09-26) The collaborator's printable brief: goal, path, lead line, waiting on,
    open decisions, last change. Token-less by design and read-only: no conversation, no file
    links, no token. None when the effort is not one of the project's discovered efforts."""
    import html as _html
    cdir = _effort_dir(proot, rel)
    if cdir is None:
        return None
    m = campaign.read_map(cdir)
    last = campaign.read_last_status(cdir)
    focused, _ = campaign._focused_step(m)
    e = lambda v: _html.escape(str(v or ""), quote=True)
    marks = {"done": "\u2713", "waiting": "\u2691"}
    shown = [s for s in m.get("steps") or [] if s.get("status") not in ("parked", "cancelled", "dropped")]
    rows = []
    for s in shown:
        now = focused is not None and s.get("id") == focused.get("id")
        mark = marks.get(s.get("status"), "\u25cf" if now else "\u00b7")
        wait = (" \u2014 waiting on " + e(s.get("waiting_on"))) if s.get("waiting_on") else ""
        rows.append("<li>%s %s%s</li>" % (mark, e(s.get("name")), wait))
    lead = (last or {}).get("lead_line") or "No status recorded yet"
    at = (last or {}).get("at") or ""
    plan = (last or {}).get("plan") or {}
    waiting = plan.get("waiting_on_you") or (m.get("heartbeat") or {}).get("human_wait") or ""
    pending = (m.get("heartbeat") or {}).get("pending_request") or {}
    decisions = []
    if pending.get("purpose"):
        decisions.append(pending["purpose"])
    reviews = (m.get("attention") or {}).get("pending_requests") or []
    if reviews:
        decisions.append("%d deliverable%s awaiting review" % (len(reviews), "" if len(reviews) == 1 else "s"))
    return ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"robots\" content=\"noindex\">"
        "<title>%s \u00b7 brief</title>"
        "<style>body{font:15px/1.5 Georgia,serif;max-width:760px;margin:40px auto;padding:0 20px;color:#222}"
        "h1{font-size:24px;margin:0 0 4px}h2{font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#666;margin:26px 0 6px}"
        "ul{padding-left:18px;margin:0}li{list-style:none;margin:3px 0}.meta{color:#666;font-size:13px}</style></head><body>"
        "<h1>%s</h1>"
        "<h2>Goal</h2><p>%s</p>"
        "<h2>Path</h2><p>%d of %d steps done%s</p><ul>%s</ul>"
        "<h2>Status</h2><p>%s</p>"
        "<h2>Waiting on</h2><p>%s</p>"
        "<h2>Open decisions</h2><p>%s</p>"
        "<h2>Last change</h2><p>%s</p>"
        "<p class=\"meta\">This page is read-only and carries no conversation or files.</p></body></html>") % (
        e(m.get("name")), e(m.get("name")),
        e(m.get("goal") or "(no goal recorded)"),
        sum(1 for s in shown if s.get("status") == "done"), len(shown),
        (" \u00b7 now: " + e(focused.get("name"))) if focused else "", "".join(rows),
        e(lead),
        e(waiting) if waiting else "nothing waiting",
        e(" \u00b7 ".join(decisions)) if decisions else "none open",
        ("last status " + e(at)) if at else "no status recorded")


def note_goal_receipt(cdir, goal, text, receipt):
    """A verb said inside a goal's place and applied by the Campaign's writer: his words and the receipt go into the
    goal's thread — the one log, tagged — so the answer appears where he spoke (Grok W2, missing). Marked as the
    writer's receipt, never as the steward's speech. Best-effort: a history error never undoes the act."""
    try:
        from steward_cockpit.conversation_history import append_turns
        append_turns(cdir, [{"role": "john", "text": text, "goal": goal, "via": "campaign_act"},
                            {"role": "steward", "text": receipt, "goal": goal, "via": "campaign_act"}])
        return True
    except Exception:
        return False


def handle_get(cdir, verb, qs):
    if verb == "notebook-status":
        import anchor_notebooks
        return anchor_notebooks.service_status(), 200
    if verb == "notebook-open":
        import anchor_notebooks
        try:
            return {"__notebook_redirect__": anchor_notebooks.open_url(cdir, qs.get("path", ""))}, 200
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 409
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
        from provider_native import private_account_path
        if private_account_path(real):
            return {"error": "private host credentials are not deliverables"}, 403
        if not (real == creal or real.startswith(creal + os.sep)) \
                or not os.path.isfile(real):
            return {"error": "not an openable deliverable (outside this effort or missing)"}, 404
        if os.path.getsize(real) > 50 * 1024 * 1024:
            return {"error": "file too large to serve inline (50MB cap)"}, 413
        expected_hash = qs.get("hash")
        if expected_hash and hashlib.sha256(Path(real).read_bytes()).hexdigest() != expected_hash:
            return {"error": "artifact-hash-mismatch"}, 409
        ext = Path(real).suffix.lower()
        # (2026-09-04, John) "PDFs, MD, Word, PPT, Excel docs should all show
        # up well." Every type gets its honest content-type; a browser renders
        # PDF and images inline; an Office document (which no browser renders)
        # gets a stdlib TEXT PREVIEW page (?view=1 — the cockpit's default) with
        # a download link that hands it to Word / PowerPoint / Excel; anything
        # else downloads under its own name instead of painting bytes as text.
        # md/txt/csv/log still go through the Reader route from the cockpit.
        want_view = str(qs.get("view", "")).strip() in ("1", "true")
        want_download = str(qs.get("download", "")).strip() in ("1", "true")
        ctype, disposition = deliverable_content_type(ext)
        if want_view and not want_download and ext == ".pptx":
            # Only a ledger-bound PDF of these exact deck bytes is a slide preview.
            digest = hashlib.sha256(Path(real).read_bytes()).hexdigest()
            refinement = campaign.read_refinement(cdir)
            previews = [rev["visual_companion"]
                for sl in (refinement or {}).get("state", {}).get("slices", {}).values()
                for rev in sl.get("revisions", {}).values()
                if rev.get("hash") == digest and rev.get("visual_companion")]
            if previews:
                preview = previews[-1]
                target = (Path(cdir) / preview["path"]).resolve()
                if (preview.get("source_hash") != digest or not target.is_relative_to(Path(cdir).resolve())
                        or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != preview["hash"]):
                    return {"error": "visual-companion-mismatch"}, 409
                return {"__file__": str(target), "__ctype__": "application/pdf", "__disposition__": "inline",
                        "__csp__": sandbox_csp_for("application/pdf")}, 200
            import html
            dl = "/api/steward/deliverable-file?pid=%s&dir=%s&path=%s&hash=%s&download=1" % (
                _q(str(qs.get("pid", ""))), _q(str(qs.get("dir", ""))), _q(rel), digest)
            if qs.get("token"):
                dl += "&token=" + _q(str(qs["token"]))
            return {"__html__": "<!doctype html><meta charset='utf-8'><title>Slide preview unavailable</title>"
                    "<h1>Slide preview not yet registered</h1><p>This PowerPoint version needs a verified PDF companion.</p>"
                    '<p><a href="' + html.escape(dl, quote=True) + '">Download the PowerPoint</a></p>'}, 200
        if want_view and not want_download and ext in OFFICE_PREVIEW_EXTENSIONS:
            import office_preview as _op
            with open(real, "rb") as fh:
                data = fh.read()
            dl = "/api/steward/deliverable-file?pid=%s&dir=%s&path=%s&download=1%s" % (
                _q(str(qs.get("pid", ""))), _q(str(qs.get("dir", ""))), _q(rel),
                ("&token=" + _q(str(qs.get("token")))) if qs.get("token") else "")
            html_page = _op.render_preview(data, os.path.basename(real), dl)
            return {"__html__": html_page}, 200
        if want_download:
            disposition = "attachment"
        return {"__file__": real, "__ctype__": ctype, "__disposition__": disposition,
                "__csp__": sandbox_csp_for(ctype)}, 200
    if verb == "efforts":
        return _efforts(cdir), 200
    if verb == "map":
        m = campaign.read_map(cdir)
        # W0b (High Seat, 2026-09-26): a part that points at another record is resolved at read,
        # once per distinct target per request; a broken reference is named on the page, never blank.
        try:
            from steward_cockpit.campaign_parts import resolve_parts
            m["resolved"] = resolve_parts(m.get("steps") or [], cache={}, with_lead=True)
        except Exception:
            m["resolved"] = {}
        m["stamp"] = campaign.map_stamp(cdir)
        m["steward"] = CONFIG["steward"]
        return m, 200
    if verb == "history":
        if qs.get("goal"):
            # W2 v2 (the active set): a goal's thread — the Campaign's one log, the turns tagged with that goal
            from steward_cockpit.conversation_history import read_history_document
            try:
                turns = [t for t in read_history_document(cdir)["turns"] if t.get("goal") == str(qs.get("goal"))]
                return {"turns": turns[-campaign.TAIL_TURNS:], "goal": str(qs.get("goal"))}, 200
            except (OSError, ValueError) as exc:
                return {"turns": [], "note": "conversation history unreadable: " + str(exc)}, 409
        if qs.get("turn_id"):
            from steward_cockpit.conversation_history import read_history_document
            try:
                turns = read_history_document(cdir, thread_id=str(qs.get("term") or "1") if qs.get("general") == "1" else None)["turns"]
                index = next((i for i,t in enumerate(turns) if t.get("turn_id") == qs["turn_id"]), None)
                if index is None:
                    return {"turns":[],"error":"original-exchange-not-found"},404
                return {"turns":turns[max(0,index-1):index+1]},200
            except (OSError,ValueError):
                return {"turns":[],"error":"conversation-history-unreadable"},409
        if qs.get("general") == "1":
            from steward_cockpit.conversation_history import read_history_document
            try:
                turns = read_history_document(cdir, thread_id=str(qs.get("term") or "1"))["turns"]
                return {"turns": turns[-campaign.TAIL_TURNS:],
                        "note": "" if len(turns) <= campaign.TAIL_TURNS else f"showing last {campaign.TAIL_TURNS} of {len(turns)} turns"}, 200
            except (OSError, ValueError) as exc:
                return {"turns": [], "note": "conversation history unreadable: " + str(exc)}, 409
        return campaign.read_history(cdir), 200
    if verb == "state":
        eng = get_engine(cdir, qs.get("general") == "1", qs.get("term"))
        if eng is None:
            return {"error": "no such session"}, 404
        st = _state_with_usage(eng, cdir); st["stamp"] = campaign.map_stamp(cdir)
        return st, 200
    if verb == "status":
        # the deterministic two-part 10-minute status, composed FRESH
        # (zero-model) — the same shape the engine's cadence persists to
        # .ecgberht/status-summary.json; the pane paints it on open.
        # (2026-09-03, John): an effort with NO live engine shows its LAST
        # recorded update, stamped, rather than a fresh "nothing running" —
        # ``stale: true`` tells the pane it is looking at the record.
        # W3c (2026-10-01, his word on the tile's Status reading old): with no live engine the pane shows the record
        # as it is NOW with the last run's receipts and stamp carried - one rule with the High Seat's tile and the Desk
        eng = ENGINES.get(cdir)
        return campaign.status_for_pane(cdir, eng.state() if eng else None, live=eng is not None), 200
    if verb == "grass":
        return {"grass": campaign.read_grass(cdir)}, 200
    if verb == "boneyard":
        return {"boneyard": campaign.list_boneyard(cdir)}, 200
    if verb == "skills":
        return {"skills": SKILLS, "icons": {s: skill_icon(s) for s in SKILLS}}, 200
    if verb == "terms":
        return {"terms": _terms_view(cdir)}, 200
    if verb == "gandalf":
        return {"runs": _gandalf_runs(cdir)}, 200
    if verb == "session-files":
        # legacy project-level view: files WORK SESSIONS wrote (engine state),
        # distinct from the curated effort register above
        return {"deliverables": _deliverables(cdir)}, 200
    if verb == "register-all":
        # project-wide deliverables (John, 2026-08-26): the UNION of every
        # effort's curated DELIVERABLES.md register — reports a human would
        # open, never raw session files. Each item carries its effort's rel
        # so the client can build the contained open link.
        out = []
        for e in campaign.discover_efforts(cdir):
            edir = str(Path(cdir) / e["rel"]) if e["rel"] else cdir
            d = campaign.read_deliverables(edir)
            for it in d.get("items", []):
                row = dict(it)
                row["effort"] = e["name"]
                row["dir"] = e["rel"]
                out.append(row)
        return {"items": out}, 200
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
    # SOFT START (John, 2026-08-26: opened the JCR tile after a restart and
    # the dialog was EMPTY — no pickup, no pending question). The pickup
    # machinery all lived inside wake(), but nothing called wake() on OPEN;
    # before the cutover engines simply stayed alive in RAM, so the gap only
    # shows after a service restart. Opening the page IS the wake for a
    # PARKED steward session: resume it so the deterministic pickup lines +
    # the model's brief orientation land on first poll. Guards: never for
    # workbench terminals, never for a brand-new effort (no stored session —
    # a mere page view must not spawn a fresh model session), only on the
    # open poll (since=0), single-flight via wake()'s own lock, and a 60s
    # cooldown so a wake that keeps failing can't respawn every poll.
    if since == 0 and not eng.general and not eng.alive():
        from steward_cockpit.steward_engine import _read_state_entry
        now = time.time()
        entry = _read_state_entry(eng.skey())
        has_durable_work = (entry.get("session_id")
                            or entry.get("pending_queue"))
        from steward_cockpit import maintenance
        if (getattr(eng, "_auto_wake_at", 0) + 60 < now
                and has_durable_work and not maintenance.is_active()):
            eng._auto_wake_at = now
            try:
                eng.wake()
            except Exception as exc:
                eng._emit({"t": "sys", "text":
                           "automatic wake failed: " + type(exc).__name__})
    evs, oldest, gap = eng.events_since(since, timeout=8)
    return {"events": evs, "state": _state_with_usage(eng, cdir), "oldest_seq": oldest,
            "gap": gap, "stamp": campaign.map_stamp(cdir)}, 200


def _terms_view(cdir):
    from steward_cockpit.steward_engine import _read_all_state, _usage_snapshot
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
                    "usage": _usage_snapshot(entry.get("usage"))})
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


# The content types a deliverable is served under (ext → (ctype, disposition)).
# "inline" lets the browser render what it can (PDF, images, plain text);
# "attachment" hands the rest to the native app under the file's own name.
# html/svg are served INERT as text (active content from a project folder
# must never execute in the dashboard's origin).
OFFICE_PREVIEW_EXTENSIONS = {".docx", ".pptx", ".xlsx"}
_DELIVERABLE_TYPES = {
    ".pdf": ("application/pdf", "inline"),
    ".png": ("image/png", "inline"), ".jpg": ("image/jpeg", "inline"),
    ".jpeg": ("image/jpeg", "inline"), ".gif": ("image/gif", "inline"),
    ".webp": ("image/webp", "inline"),
    ".json": ("application/json; charset=utf-8", "inline"),
    ".md": ("text/plain; charset=utf-8", "inline"), ".txt": ("text/plain; charset=utf-8", "inline"),
    ".csv": ("text/plain; charset=utf-8", "inline"), ".log": ("text/plain; charset=utf-8", "inline"),
    # (2026-09-06, John: "I just see the raw code") HTML and SVG RENDER — served as
    # their real types under a Content-Security-Policy sandbox (see sandbox_csp_for):
    # an opaque origin that cannot read the dashboard's token, cookies or storage.
    ".html": ("text/html; charset=utf-8", "inline"), ".htm": ("text/html; charset=utf-8", "inline"),
    ".svg": ("image/svg+xml", "inline"),
    ".docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", "attachment"),
    ".pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", "attachment"),
    ".xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "attachment"),
    ".doc": ("application/msword", "attachment"),
    ".ppt": ("application/vnd.ms-powerpoint", "attachment"),
    ".xls": ("application/vnd.ms-excel", "attachment"),
    ".zip": ("application/zip", "attachment"),
}


#: The sandbox a project's own HTML/SVG renders under: scripts may run, popups and forms
#: work, but the document has an OPAQUE origin — no allow-same-origin, so it can never
#: read the dashboard's localStorage token, cookies, or call the API as the user.
SANDBOX_CSP = "sandbox allow-scripts allow-popups allow-forms allow-modals allow-downloads"


def sandbox_csp_for(ctype):
    """The CSP header value for a content type that can carry active content, else None."""
    c = str(ctype or "").lower()
    if c.startswith("text/html") or c.startswith("image/svg"):
        return SANDBOX_CSP
    return None


def deliverable_content_type(ext):
    """(content_type, disposition) for a deliverable's extension — total."""
    return _DELIVERABLE_TYPES.get(str(ext or "").lower(), ("application/octet-stream", "attachment"))


def _q(s):
    from urllib.parse import quote
    return quote(str(s or ""), safe="")


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
                if name.startswith(".") or name in ("node_modules", "__pycache__",
                                                    "vendor"):
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
    import anchor_notebooks
    for entry in entries:
        if not entry["dir"]:
            rel = entry["name"] if q or not sub else sub.replace("\\", "/") + "/" + entry["name"]
            info = anchor_notebooks.describe(cdir, rel)
            if info:
                entry["notebook_product"] = info
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
    if verb == "refinement-accept":
        from steward_cockpit.refinement_client import update
        import uuid
        current = campaign.read_refinement(cdir)
        if not current or not current.get("ok"):
            return {"ok": False, "error": "refinement-state-unavailable"}, 409
        sl = current["state"]["slices"].get(str(body.get("step_id")), {})
        presentation = next((p for p in sl.get("presentations", []) if p["id"] == body.get("presentation_id")), {})
        member = next((m for m in presentation.get("members", []) if m["product_id"] == body.get("product_id")), None)
        if not member or member["revision_id"] != body.get("revision_id") or member["hash"] != body.get("hash"):
            return {"ok": False, "error": "approval-version-mismatch"}, 409
        target = (Path(cdir) / member["path"]).resolve()
        if not target.is_relative_to(Path(cdir).resolve()) or not target.is_file() or hashlib.sha256(target.read_bytes()).hexdigest() != member["hash"]:
            return {"ok": False, "error": "approval-artifact-changed"}, 409
        result = update(cdir, {"action": "accept", "operation_id": str(uuid.uuid4()), "expected_seq": current["sequence"],
            "step_id": body["step_id"], "presentation_id": presentation["id"], "member_product_id": member["product_id"],
            "complete_current": True, "human": {"explicit": True, "source_message":
                "Authenticated cockpit: Done with " + member["product_id"] + "; exact revision " + member["revision_id"]}})
        if result.get('committed') is True and not result.get('ok'):
            result={**result,'ok':True,'warning':'Approval saved; the derived collection needs repair.'}
        if result.get("ok"):
            # W4 (2026-09-28): the correction set is PROPOSED in the foreground, never applied (his Q2); a failed
            # composition rides on the acceptance's answer as repair_error so the card can say no set was proposed;
            # the horizon follows, so its stamp covers the proposal event too (Grok W4)
            from steward_cockpit import repair as _repair
            rp = _repair.propose(cdir, body["step_id"], presentation["id"], background=False)
            if not (isinstance(rp, dict) and rp.get("ok")):
                result = {**result, "repair_error": str((rp or {}).get("error") or "repair_failed"), "repair_message": str((rp or {}).get("message") or "")[:200]}
            elif rp.get("appended"):
                result = {**result, "repair_proposed": {"proposal_id": rp.get("proposal_id"), "count": rp.get("count")}}
            from steward_cockpit import horizon as _horizon
            _horizon.refresh(cdir, "accepted")      # W3 (2026-09-28): the line follows the acceptance, at once
        return result, 200 if result.get("ok") else 409
    if verb == "refinement-close":
        from steward_cockpit.refinement_client import update
        import uuid
        current = campaign.read_refinement(cdir)
        if not current or not current.get("ok"):
            return {"ok": False, "error": "refinement-state-unavailable"}, 409
        result = update(cdir, {"operation_id": str(uuid.uuid4()), "expected_seq": current["sequence"],
            "action": "close", "step_id": body.get("step_id"), "presentation_id": body.get("presentation_id"),
            "human": {"explicit": True, "source_message": "Authenticated cockpit: Done with this slice; named presentation " + str(body.get("presentation_id"))}})
        if result.get('committed') is True and not result.get('ok'):
            result={**result,'ok':True,'warning':'Completion saved; the derived collection needs repair.'}
        return result, 200 if result.get("ok") else 409
    if verb == "refinement-update":
        from steward_cockpit.refinement_client import update
        result = update(cdir, body)
        return result, 200 if result.get("ok") else 409
    if verb == "refinement-open":
        # An explicit authenticated cockpit click, not a GET/prefetch receipt.
        # Anchor authenticates this route before dispatch. Verify exact bytes
        # before recording which frozen member the user chose to open.
        from steward_cockpit.refinement_client import update
        current = campaign.read_refinement(cdir)
        if not current or not current.get("ok"):
            return {"ok": False, "error": "refinement-state-unavailable"}, 409
        state = current["state"]
        step = state["slices"].get(str(body.get("step_id")))
        presentation = next((p for p in (step or {}).get("presentations", []) if p["id"] == body.get("presentation_id")), None)
        member = next((m for m in (presentation or {}).get("members", []) if m["product_id"] == body.get("product_id")), None)
        if not member:
            return {"ok": False, "error": "unknown-presentation-member"}, 409
        root = Path(cdir).resolve()
        target = (root / member["path"]).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            return {"ok": False, "error": "containment-refused"}, 409
        if hashlib.sha256(target.read_bytes()).hexdigest() != member["hash"]:
            return {"ok": False, "error": "artifact-hash-mismatch"}, 409
        pending = next((request for request in step.get("review_requests", []) if request.get("presentation_id") == presentation["id"]), {})
        import uuid
        result = update(cdir, {"action": "view", "operation_id": str(uuid.uuid4()),
            "expected_seq": current["sequence"], "step_id": body["step_id"],
            "presentation_id": presentation["id"], "member_product_id": member["product_id"],
            "hash": member["hash"], "request_id": pending.get("id") if pending.get("presentation_id") == presentation["id"] else None,
            "session_id": str(body.get("session_id") or "cockpit"), "source": "cockpit-user-open"})
        if result.get("ok"):
            result["path"] = member["path"]
            result["hash"] = member["hash"]
        return result, 200 if result.get("ok") else 409
    if verb == "notebook-register":
        import anchor_notebooks
        try:
            return anchor_notebooks.register(cdir, source=body.get("source"),
                what=body.get("what"), step=body.get("step", ""),
                regenerate=body.get("regenerate") is True), 200
        except (ValueError, OSError) as exc:
            return {"ok": False, "error": str(exc)}, 409
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
        # W5 (High Seat, 2026-09-26): a Campaign verb spoken on the Campaign record (move ... to tier n, add a part
        # to ..., make ... an initiative, park ... until ..., unpark ..., what needs me) is compiled by the engine's
        # act table and applied by the Campaign's own writer; the answer is its receipt with undo. Only the engine's
        # word that it is NOT a Campaign verb hands the text to the steward: a failed compile or a writer error
        # answers a refusal here, never a model turn.
        if not body.get("question_id") and not isinstance(body.get("refinement_context"), dict):
            from steward_cockpit.campaign_say import is_campaign_folder, say_campaign
            if is_campaign_folder(cdir):
                _goal = str(body.get("goal") or "").strip() or None
                spoken = say_campaign(cdir, str(body.get("text") or ""), goal=_goal)
                if spoken is not None:
                    if _goal and spoken.get("ok"):
                        note_goal_receipt(cdir, _goal, str(body.get("text") or ""), str(spoken.get("receipt") or spoken.get("say") or ""))
                    return spoken, (200 if spoken.get("ok") else 400)
        context = body.get("refinement_context")
        _refined_turn = False
        if isinstance(context, dict):
            from steward_cockpit.refinement_client import update
            import uuid
            current = campaign.read_refinement(cdir)
            if not current or not current.get("ok"):
                return {"ok": False, "error": "refinement-state-unavailable"}, 409
            feedback_id = str(uuid.uuid4())
            result = update(cdir, {"operation_id": feedback_id, "expected_seq": current["sequence"],
                "action": "feedback", "step_id": context.get("step_id"), "feedback_id": feedback_id,
                "source_message": str(body.get("text", "")), "base_presentation_id": context.get("presentation_id"),
                "changes": [{"id": "change-" + feedback_id, "scope": context.get("product_id") or "slice", "directive": "require", "text": str(body.get("text", ""))}],
                "elegance": {"mode": "RC6", "source": "User selected Refine this slice", "reason": "Apply the user's requested changes within this slice; assess new elements before adding scope."}})
            if not result.get("ok"):
                return result, 409
            from steward_cockpit import horizon as _horizon
            _horizon.refresh(cdir, "refined")       # W3 (2026-09-28): the line moves when the feedback is recorded
            _refined_turn = True
        eng = get_engine(cdir, bool(body.get("general")),
                         str(body.get("term") or "") or None)
        if eng is None:
            return {"ok": False, "error": "no such session / cap hit"}, 404
        result = (eng.say(body.get("text", ""), question_id=body["question_id"]) if body.get("question_id")
                  else eng.say(body.get("text", ""), goal=(str(body.get("goal") or "").strip() or None)))
        if _refined_turn:
            # W3 (Grok's hold): the turn's reply may have written the line — derive it again so the turn's own
            # sentence never stands over the stamped derivation
            from steward_cockpit import horizon as _horizon2
            _horizon2.refresh(cdir, "refined")
        return result, 200 if result.get("ok") else 409
    if verb == "code_job":
        # R3 (steward responsiveness, 2026-10-04): the steward hands real work to a code job and stays free to talk
        from steward_cockpit import code_jobs as _cj
        action = body.get("action") or "list"
        if action == "start":
            eng = get_engine(cdir)
            out = _cj.start(cdir, body.get("repo") or "", body.get("brief") or "", body.get("check") or "",
                            engine_factory=lambda wt: get_engine(wt, general=True, tid="1"),
                            steward=(eng.steward if eng else ""))
            if out.get("ok") and eng is not None:
                eng._emit({"t": "sys", "text": "code job %s started on %s (best model, full effort); the steward stays free to talk" % (out["job"], body.get("repo"))})
            return out, (200 if out.get("ok") else 400)
        if action == "stop":
            return _cj.stop(cdir, body.get("job"), engine_lookup=lambda wt: get_engine(wt, general=True, tid="1", create=False)), 200
        return {"ok": True, "jobs": list(_cj.read_jobs(cdir).values())[-20:]}, 200
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
        if action == "take_now":
            # R1 (2026-10-04): his queued message goes now - interrupt the running turn, then wake on the queue
            return eng.take_now(), 200
        if action == "interrupt":
            # codex-discipline-2026-09-15 Wave 1.3: Stop turn (not park).
            return eng.interrupt_turn(str(body.get("reason") or "stopped by John")[:120]), 200
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


def _upload_version(st_):
    """Return an opaque optimistic-concurrency token for one file identity."""
    fields = (
        "v1", getattr(st_, "st_dev", 0), getattr(st_, "st_ino", 0),
        st_.st_mode, st_.st_size, getattr(st_, "st_mtime_ns", 0),
        getattr(st_, "st_ctime_ns", 0),
    )
    raw = "\0".join(str(value) for value in fields).encode("ascii")
    return "v1-" + hashlib.sha256(raw).hexdigest()


def _upload_snapshot(dst, incoming):
    """Describe a stable existing target, reading bytes only when sizes match."""
    for _attempt in range(2):
        before = dst.stat()
        version = _upload_version(before)
        same = False
        if stat.S_ISREG(before.st_mode) and before.st_size == len(incoming):
            existing = dst.read_bytes()
            after = dst.stat()
            if _upload_version(after) != version:
                continue
            same = existing == incoming
        return ({"ok": False, "exists": True, "name": dst.name,
                 "same": same, "size": before.st_size,
                 "mtime": int(before.st_mtime),
                 "incoming_size": len(incoming), "version": version}, before)
    raise OSError("target changed while it was being inspected")


def _stage_upload(folder, data):
    """Durably stage bytes beside their destination for atomic publication."""
    fd, raw_path = tempfile.mkstemp(prefix=_UPLOAD_TEMP_PREFIX, suffix=".tmp",
                                    dir=folder)
    stream = None
    try:
        stream = os.fdopen(fd, "wb")
        fd = None
        with stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        return Path(raw_path)
    except Exception:
        if fd is not None:
            os.close(fd)
        try:
            os.unlink(raw_path)
        except OSError:
            pass
        raise


def _discard_upload_stage(staged):
    if staged is None:
        return
    try:
        staged.unlink()
    except FileNotFoundError:
        pass


def _upload(cdir, body):
    name = Path(str(body.get("name", ""))).name
    mode = body.get("mode", "new")
    sub = str(body.get("sub", "") or "")
    if not isinstance(mode, str) or mode not in _UPLOAD_MODES:
        return {"ok": False, "error": "unknown upload mode"}, 400
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
    final = os.path.realpath(dst)
    if final != base and not final.startswith(base + os.sep):
        return {"ok": False, "error": "refused (link escapes effort)"}, 400
    if os.path.islink(dst):
        return {"ok": False, "error": "refused (target is a link)"}, 400

    if mode == "replace":
        expected = body.get("if_match")
        if not isinstance(expected, str) or not expected:
            return {"ok": False, "error":
                    "replace requires the version from the conflict review"}, 428

    staged = None
    try:
        staged = _stage_upload(folder, data)
    except OSError:
        return {"ok": False, "error": "couldn't stage that file"}, 500

    published = None
    try:
        with UPLOAD_LOCK:
            # Re-assert link safety after staging, immediately before publish.
            if os.path.islink(dst):
                return {"ok": False,
                        "error": "refused (target is a link)"}, 400

            if mode == "replace":
                try:
                    conflict, current = _upload_snapshot(dst, data)
                except FileNotFoundError:
                    return {"ok": False, "exists": False,
                            "error": "the reviewed file is no longer there"}, 412
                except OSError:
                    return {"ok": False, "error":
                            "the file changed while it was being reviewed"}, 409
                if not stat.S_ISREG(current.st_mode):
                    return {"ok": False, "exists": True,
                            "error": "the existing target is not a file"}, 409
                if expected != conflict["version"]:
                    conflict["error"] = (
                        "the file changed after conflict review; review it again")
                    return conflict, 412
                os.chmod(staged, stat.S_IMODE(current.st_mode))
                os.replace(staged, dst)
                staged = None
                published = dst

            elif mode == "new":
                # A hard-link publish is atomic and fails if another caller (or
                # process) claimed the name; it can never overwrite that file.
                for _attempt in range(3):
                    try:
                        os.link(staged, dst)
                        published = dst
                        break
                    except FileExistsError:
                        if os.path.islink(dst):
                            return {"ok": False, "error":
                                    "refused (target is a link)"}, 400
                        try:
                            conflict, _current = _upload_snapshot(dst, data)
                            return conflict, 200
                        except FileNotFoundError:
                            continue
                        except OSError:
                            return {"ok": False, "error":
                                    "the file changed while it was being reviewed"}, 409
                if published is None:
                    return {"ok": False, "error":
                            "the destination kept changing; try again"}, 409

            else:  # keepboth
                stem, suffix = Path(name).stem, Path(name).suffix
                candidate = dst
                number = 1
                while True:
                    try:
                        os.link(staged, candidate)
                        published = candidate
                        break
                    except FileExistsError:
                        candidate = Path(folder) / f"{stem} ({number}){suffix}"
                        number += 1
    except OSError:
        return {"ok": False, "error": "couldn't save that file"}, 500
    finally:
        _discard_upload_stage(staged)

    try:
        version = _upload_version(published.stat())
    except OSError:
        version = ""
    return {"ok": True, "name": published.name, "version": version}, 200


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
