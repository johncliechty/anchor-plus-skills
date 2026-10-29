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
import copy
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import threading
import time
import importlib
from pathlib import Path

for _hot_mod in ("anchor_settings", "usage_allowance_monitor", "deliverables_register", "steward_cockpit.spellcheck_engine", "steward_cockpit.dictation_engine", "steward_cockpit.steward_campaign", "steward_cockpit.campaign_acts", "steward_cockpit.campaign_say", "high_seat_page", "report_viewer"):
    if _hot_mod in sys.modules:
        try:
            importlib.reload(sys.modules[_hot_mod])
        except Exception:
            pass

# Ensure live AnchorHandler._steward_pid_dir falls back to workspace Campaign when pid is omitted (e.g., global spellcheck / fleet-brief)
_WS_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CAMPAIGN_DIR = str(_WS_ROOT / "Campaign")
def _resolve_named_cockpit_dir(raw_pid):
    import urllib.parse
    clean = urllib.parse.unquote(str(raw_pid or "")).strip()
    if not clean:
        return _DEFAULT_CAMPAIGN_DIR if os.path.isdir(_DEFAULT_CAMPAIGN_DIR) else None
    if ":" in clean or clean.startswith(("/", "\\")) or ".." in Path(clean).parts or Path(clean).is_absolute():
        return None
    low = clean.lower()
    known = {
        "book 1": str(_WS_ROOT / "Writing" / "Artificial Magi" / "Book 1"),
        "paper 1": str(_WS_ROOT / "Hierarchical Normalizing Flows" / "Paper 1"),
        "basic infastructure": str(_WS_ROOT / "Open Source Token Source" / "Basic Infastructure"),
        "basic infrastructure": str(_WS_ROOT / "Open Source Token Source" / "Basic Infastructure"),
        "campaign": _DEFAULT_CAMPAIGN_DIR,
        "anchor": str(_WS_ROOT / "Anchor"),
    }
    if low in known and os.path.isdir(known[low]):
        return known[low]
    try:
        import rnd_registry as _rnd
        for proj in _rnd.list_projects(include_archived=True, include_future=True, include_retired=True):
            fp = str(proj.get("folder_path") or "").strip()
            pname = str(proj.get("name") or "").strip()
            if not fp or not os.path.isdir(fp):
                continue
            if pname.lower() == low or Path(fp).name.lower() == low:
                return fp
            sub = Path(fp) / clean
            if sub.is_dir():
                return str(sub)
    except Exception:
        pass
    cand = Path(r"C:\dev") / clean
    if cand.is_dir():
        return str(cand)
    return None

for _main_mod_name in ("__main__", "anchor_gui"):
    _m = sys.modules.get(_main_mod_name)
    _ah = getattr(_m, "AnchorHandler", None) if _m else None
    if _ah is not None and hasattr(_ah, "_steward_pid_dir"):
        _orig_spd = getattr(_ah, "_orig_steward_pid_dir", _ah._steward_pid_dir)
        _ah._orig_steward_pid_dir = _orig_spd
        def _patched_steward_pid_dir(self, pid, _orig=_orig_spd):
            res = _orig(self, pid)
            if res is None:
                res = _resolve_named_cockpit_dir(pid)
            return res
        _ah._steward_pid_dir = _patched_steward_pid_dir
    if _m is not None:
        try:
            _m._BOOT_RELEASE_VERSION = "1.4.3"
        except Exception:
            pass

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

ENGINES = globals().get("ENGINES") if isinstance(globals().get("ENGINES"), dict) else {}
ENGINES_LOCK = globals().get("ENGINES_LOCK") or threading.Lock()
TERMS_LOCK = threading.Lock()
UPLOAD_LOCK = threading.Lock()

# W7 (2026-10-10): the deliverables answer per (effort, pid, dir), reused while what it was built from is unchanged,
# for at most _DELIV_TTL seconds from the moment its build began. "Unchanged" covers the map's files, the ledger
# folder, the private homes AS THEY RESOLVE NOW (a retargeted junction is a change) and the identity of every file
# the answer offers (an lstat each: mode, inode, size, mtime - a deliverable swapped for a link is a change). Any
# change rebuilds, so every offered link was checked by the same containment and privacy rule serving uses. An
# answer whose files changed WHILE its links were being checked is returned but never kept (review r2). Misses on one
# key build once (the others wait); the cache is bounded and drops expired entries. The per-key locks are never
# dropped: the keys are the real efforts (the route resolved them), so they are few.
_DELIV_CACHE = globals().get("_DELIV_CACHE") if isinstance(globals().get("_DELIV_CACHE"), dict) else {}           # key -> (stamp, built_at, data, offered)
_DELIV_LOCK = globals().get("_DELIV_LOCK") or threading.Lock()
_DELIV_KEY_LOCKS = globals().get("_DELIV_KEY_LOCKS") if isinstance(globals().get("_DELIV_KEY_LOCKS"), dict) else {}
_DELIV_TTL = 180.0
_DELIV_MAX = 128


from steward_cockpit import steward_core as _core


def _offered_paths(data):
    """Every in-effort path the answer offers (items, approved, their history, acts and companions)."""
    return _core.extract_offered_paths(data)



def _identity(cdir, rels):
    sig = []
    for rel in rels:
        try:
            st = os.lstat(os.path.join(cdir, rel))
            sig.append((rel, st.st_mode, st.st_ino, st.st_size, st.st_mtime_ns))
        except OSError:
            sig.append((rel, None))
    return tuple(sig)


def _private_stamp():
    try:
        from provider_native import private_homes
        return tuple(str(h) for h in private_homes())
    except Exception:
        return None                                   # unknown: never equal, so never reused


def _deliverables_cached(cdir, qs, read, annotate):
    """``read()`` parses the register; ``annotate(data)`` checks and attaches every reading link."""
    key = (os.path.normcase(os.path.abspath(cdir)), str(qs.get("pid", "")).strip(), str(qs.get("dir", "")).strip())
    with _DELIV_LOCK:
        klock = _DELIV_KEY_LOCKS.setdefault(key, threading.Lock())
    acquired = klock.acquire(timeout=12.0)
    if not acquired:
        with _DELIV_LOCK:
            klock = threading.Lock()
            _DELIV_KEY_LOCKS[key] = klock
        acquired = klock.acquire(timeout=5.0)
    try:
        stamp = (_deliv_stamp(cdir), _private_stamp())
        hit = _DELIV_CACHE.get(key)
        if (hit and stamp[1] is not None and hit[0] == stamp and time.monotonic() - hit[1] < _DELIV_TTL
                and _identity(cdir, [e[0] for e in hit[3]]) == hit[3]):
            return copy.deepcopy(hit[2])
        began = time.monotonic()
        data = read()
        before = _identity(cdir, _offered_paths(data))
        annotate(data)                                # the links are checked here, between the two snapshots
        after = _identity(cdir, _offered_paths(data))
        if before != after or stamp[1] is None:
            return data                               # changed under the check: answered, never kept
        with _DELIV_LOCK:
            now = time.monotonic()
            for k in [k for k, v in _DELIV_CACHE.items() if now - v[1] >= _DELIV_TTL]:
                _DELIV_CACHE.pop(k, None)
            while len(_DELIV_CACHE) >= _DELIV_MAX:
                _DELIV_CACHE.pop(min(_DELIV_CACHE, key=lambda k: _DELIV_CACHE[k][1]), None)
            _DELIV_CACHE[key] = (stamp, now, copy.deepcopy(data), after)
        return data
    finally:
        if acquired:
            try:
                klock.release()
            except RuntimeError:
                pass


def _deliv_stamp(cdir):
    """What the deliverables answer is built from: the map's files (DELIVERABLES.md, roadmap.json among them) and
    the steward's ledger folder."""
    try:
        led = (Path(cdir) / ".ecgberht").stat().st_mtime_ns
    except OSError:
        led = 0
    return "%s-%s" % (campaign.map_stamp(cdir), led)

_UPLOAD_MODES = frozenset(("new", "replace", "keepboth"))
_UPLOAD_TEMP_PREFIX = ".anchor-upload-"

# persona + fake flag injected by anchor_gui at mount time
CONFIG = {**{"steward": "Ecgberht", "fake": False, "permission_mode": "bypassPermissions"}, **(globals().get("CONFIG") if isinstance(globals().get("CONFIG"), dict) else {})}
BONEYARD = campaign.BONEYARD_DIRNAME
SKILLS = ["researchPrime", "Crucible", "Foreman", "Gandalf", "Jumper",
          "Superjump", "Anvil", "Aegis",
          "ramanujan", "legal-beagle", "financial-analyst",
          "literature-review", "tidy-idy", "chekhov"]
# (2026-09-05, John) every skill has a brand mark under /vendor/brand/; the cockpit
# reaches it as /brand/<file>. The client twin is static/skill-icons.js.
SKILL_ICONS = {
    "researchPrime": "research-prime-icon.jpg", "Crucible": "crucible-icon.svg",
    "Foreman": "foreman-icon.svg", "Gandalf": "gandalf-icon.jpg", "Jumper": "jumper-icon.jpg",
    "Superjump": "superjump-icon.jpg", "Anvil": "anvil-icon.jpg", "anvil": "anvil-icon.jpg",
    "Aegis": "aegis-icon.jpg", "aegis": "aegis-icon.jpg",
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
      else if(u.indexOf('/api/steward/')===0){
        if(u.indexOf('pid=')<0 && window.STEWARD_PID){
          u+=(u.indexOf('?')<0?'?':'&')+'pid='+encodeURIComponent(window.STEWARD_PID);
        }
        o=auth(o);
      }
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
    try{var w=window;for(var k=0;k<6;k++){if(w.__anchorHidden)return true;if(w===w.parent)break;w=w.parent;}}catch(_){}   // a tile the app keeps hidden (this frame or one around it) reloads when he can see it, never under him
    if(Date.now()-_lastIn<10000)return true;
    if(document.querySelector('[data-send][disabled]'))return false;
    var tas=document.querySelectorAll('textarea');for(var i=0;i<tas.length;i++){if(tas[i].value&&tas[i].value.trim())return true;}
    var frs=document.querySelectorAll('iframe');for(var j=0;j<frs.length;j++){try{var fb=frs[j].contentWindow.__stewardBusy;if(fb&&fb())return true;}catch(_){}}
    if(!ae)return false;
    if(ae.tagName==='IFRAME'){try{var b=ae.contentWindow.__stewardBusy;return !!(b&&b());}catch(_){return false;}}
    return !!((ae.tagName==='TEXTAREA'||(ae.tagName==='INPUT'&&/^(text|search|)$/i.test(ae.type||'')))&&ae.value);}
  window.__stewardBusy=_busy;
  // W4 (2026-10-08, ChatGPT r4): a cockpit view embedded as a Cave card (view=tile) never reloads itself while open
  // in the Cave, except inside the Anchor App shell (window.parent.ANCHOR_APP) or when parked/idle across a new build.
  var _tile=false;try{_tile=new URLSearchParams(location.search).get('view')==='tile'&&window.parent!==window&&!window.parent.ANCHOR_APP;}catch(_){}
  function _checkVersion(){
    try{var hw=window;for(var hk=0;hk<6;hk++){if(hw.__anchorHidden)return;if(hw===hw.parent)break;hw=hw.parent;}}catch(_){}
    _f('/api/version', {cache:'no-store'}).then(function(r){return r.json();})
      .then(function(j){
        var v = j && j.version;
        if (!v || v === window.STEWARD_BUILD || _busy()) return;
        if (_tile) { try { if (window.parent && window.parent.document && window.parent.document.querySelector('.tile.open')) return; } catch (_) {} }
        var key = 'steward_reloaded_for:' + location.pathname + location.search;
        try{ if (sessionStorage.getItem(key) === v) return;
             sessionStorage.setItem(key, v); }catch(_){}
        location.reload();
      }).catch(function(){});
  }
  if (window.STEWARD_BUILD) {
    setInterval(_checkVersion, 30000);
    window.addEventListener('anchor-app-visibility', function(ev){
      if (ev && ev.detail && !ev.detail.hidden) setTimeout(_checkVersion, 150);
    });
  }
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


def _persona_name():
    """The active companion persona name (Aladdin / Jarvis / Ecgberht — never 'Steward')."""
    try:
        import anchor_settings as _aset
        prof = _aset.steward_profile()
        name = str(prof.get("name") or prof.get("label") or CONFIG.get("steward") or "Aladdin").strip()
        resolved = "Aladdin" if not name or name.lower() == "steward" else name
        if _aset.settings_path().is_file() and CONFIG.get("steward") != resolved:
            rename_stewards(resolved)
        return resolved
    except Exception:
        return str(CONFIG.get("steward") or "Aladdin")


def serve_page_doc(page, pid=""):
    fname = _PAGES.get(page)
    if not fname:
        return None
    build = str(CONFIG.get("build") or getattr(sys.modules.get("anchor_gui") or sys.modules.get("__main__"), "BUILD_ID", "") or "")
    html = (STATIC / fname).read_text(encoding="utf-8")
    html = (html.replace('href="/static/', 'href="/steward-static/')
                .replace('src="/static/', 'src="/steward-static/')
                # Anchor serves brand marks at /vendor/brand/, not /brand/;
                # rewrite both the static hrefs and the JS "/brand/" base
                # without double-rewriting existing "/vendor/brand/" paths
                .replace('"/brand/', '"/vendor/brand/')
                .replace("'/brand/", "'/vendor/brand/"))
    if build:
        html = re.sub(
            r'((?:href|src)="/steward-static/[^"?]+\.(?:js|css))"',
            lambda m: m.group(1) + "?v=" + build + '"',
            html,
        )
    user_display_name = "John"
    try:
        import onboard_wizard as _ow
        _uprof = _ow.get_active_user_profile()
        if _uprof.get("configured") and _uprof.get("display_name"):
            user_display_name = str(_uprof["display_name"]).strip()
    except Exception:
        pass
    shim = (_CLIENT_SHIM % (json.dumps(pid),
                            json.dumps(build), json.dumps(_mode_name()))) + (
        "<script>window.STEWARD_NAME=%s;window.USER_DISPLAY_NAME=%s;</script>" % (
            json.dumps(_persona_name()), json.dumps(user_display_name)
        )
    )
    nb_src = '/steward-static/notebook-actions.js' + (("?v=" + build) if build else "")
    return html.replace("<script", shim + '<script src="' + nb_src + '"></script><script', 1)


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
                       "notebook-register", "notebook-status", "deliverable-file", "anvil",
                       "anvil/walkthrough", "spellcheck", "dictate", "fleet-brief", "fleet-relay"}


_PROJECT_TERMINAL_VERBS = {"term_new", "term_archive", "term_restore"}
_GENERAL_READ_VERBS = {"map", "history", "state", "events", "deliverables"}
_GENERAL_POST_VERBS = {"say", "engine", "dismiss-deliverable", "deliverables/dismiss"}


def _registered_project_terminal(proot, raw_tid):
    tid = str(raw_tid or "")
    if not re.fullmatch(r"\d{1,6}", tid):
        return False
    record = _load_terms(proot).get(tid)
    return isinstance(record, dict) and not record.get("archived")


def api_get(proot, verb, qs):
    if verb == "usage-summary":
        return global_usage_summary(qs)
    if verb == "usage-allowance":
        return usage_allowance_get(qs)
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
    if verb in ("spellcheck", "dictate", "fleet-brief", "fleet-relay", "anvil", "anvil/walkthrough", "mothership-files"):
        rel = (qs.get("dir") or "").strip()
        cdir = _effort_dir(proot, rel) or _resolve_named_cockpit_dir(rel) or proot
        return handle_get(cdir, verb, qs)
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
    ids = _running_record_ids(_jr)
    try:                         # final review 10-10: a skill job (Gandalf, researchPrime ...) is a child of this server too
        from steward_cockpit import skill_jobs as _skj
        ids += ["skill:" + str(k) for k, p in list(_skj._PROCS.items()) if p.poll() is None]
    except Exception:
        ids.append("skill:unreadable")
    try:                         # a Foreman code job's process counts until it is seen to end, even after its Stop
        from steward_cockpit import code_jobs as _cjf
        ids += ["foreman:" + str(k) for k, p in list(_cjf._FOREMAN_PROCS.items()) if p.poll() is None]
    except Exception:
        ids.append("foreman:unreadable")
    # 2026-10-07: a steward code job (Foreman in its own worktree) is a child of this server too; the drained
    # restart once fired mid-job because only job_runner records counted. The busy ledger names every live one.
    try:
        from steward_cockpit import code_jobs as _cj
        _cj.busy_repos()                # a Foreman lost to a restart and gone since is marked interrupted first
        ids += ["code:" + str(entry.get("job") or "?") for entry in _cj._busy_read().values() if isinstance(entry, dict)]
    except Exception:
        ids.append("code:unreadable")   # cannot prove none are running: never restart over one
    return ids


_JOB_STATUS = globals().get("_JOB_STATUS") if isinstance(globals().get("_JOB_STATUS"), dict) else {}   # record path -> ((mtime_ns, size), status, job_id)
_JOB_STATUS_LOCK = globals().get("_JOB_STATUS_LOCK") or threading.Lock()   # the boot warm-up and a request never fill it at once


def _running_record_ids(jr):
    """The running job records' ids, as ``job_runner.list_records`` would find them, but each record is re-read only
    when its file changed (W7, 2026-10-10: 20,000 records were re-read on every maintenance status - 300 s live)."""
    with _JOB_STATUS_LOCK:
        return _running_record_ids_locked(jr)


def _running_record_ids_locked(jr):
    d = jr.jobs_dir()
    seen, out = set(), []
    try:
        with os.scandir(d) as it:
            files = sorted((e for e in it if e.name.endswith(".json") and e.is_file()), key=lambda e: e.name)
            for e in files:
                if e.name.endswith((".gate.json", ".cursor.json")):
                    continue
                seen.add(e.path)
                try:
                    st = e.stat()
                    sig = (st.st_mtime_ns, st.st_size)
                except OSError:
                    continue
                hit = _JOB_STATUS.get(e.path)
                if not hit or hit[0] != sig:
                    try:
                        rec = json.loads(Path(e.path).read_text(encoding="utf-8"))
                    except (json.JSONDecodeError, OSError):
                        continue
                    hit = (sig, rec.get("status") if isinstance(rec, dict) else None,
                           str((rec.get("job_id") if isinstance(rec, dict) else None) or "?"))
                    _JOB_STATUS[e.path] = hit
                if hit[1] == jr.STATUS_RUNNING:
                    out.append(hit[2])
    except FileNotFoundError:
        return []
    for gone in set(_JOB_STATUS) - seen:
        _JOB_STATUS.pop(gone, None)
    return out


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
    if verb in ("spellcheck", "dictate", "fleet-brief", "fleet-relay", "anvil", "anvil/walkthrough", "mothership-files"):
        cdir = _effort_dir(proot, rel) or _resolve_named_cockpit_dir(rel) or proot
        return handle_post(cdir, verb, body)
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
    from steward_cockpit.steward_engine import _read_state_entry
    out = []
    for e in campaign.discover_efforts(cdir):
        edir = str(Path(cdir) / e["rel"]) if e["rel"] else cdir
        m = campaign.read_map(edir, include_plan_history=False)
        eng = get_engine(m["dir"], create=False)
        if eng is not None:
            eff_light = eng.light(m["attention"])
        else:
            st_entry = _read_state_entry(m["dir"])
            att_state = (m.get("attention") or {}).get("state")
            is_working = (att_state == "working"
                          or bool(campaign.running_code_jobs(m["dir"]))
                          or bool(campaign.running_skill_jobs(m["dir"])))
            has_q = bool(st_entry.get("open_question")) or bool(st_entry.get("pending_questions")) or att_state in ("needs_you", "blocked")
            eff_light = "green" if is_working else ("orange" if has_q else "quiet")
        active = next((s for s in m["steps"] if s["status"] == "active"), None)
        out.append({"rel": e["rel"], "name": e["name"],
                    # goal-derived rename suggestion (zero-model; the ✎
                    # prompt prefills it — user edits or replaces)
                    "suggested_name": campaign.suggest_effort_name(
                        m["goal_brief"]),
                    "light": eff_light,
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
    active_steward = _persona_name()
    livery = campaign.STEWARD_LIVERY.get(active_steward, {})
    est = campaign.STEWARD_LIVERY  # noqa
    return {"project": Path(cdir).name, "steward": active_steward,
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
    search_dirs = [cdir]
    try:
        for e in campaign.discover_efforts(cdir):
            if e.get("rel"):
                edir = str(Path(cdir) / e["rel"])
                if edir not in search_dirs:
                    search_dirs.append(edir)
    except Exception:
        pass
    groups = {}
    for project_id in sorted(aliases):
        for lane in eh.ROLLUP_LANES:
            records = []
            for sdir in search_dirs:
                try:
                    part = eh.list_efforts(sdir, project_id, lane)
                    if not isinstance(part, (list, tuple)):
                        raise ValueError("invalid effort history")
                    records.extend(part)
                except Exception:
                    if sdir == cdir:
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


_ROLLUP_CACHE = globals().get("_ROLLUP_CACHE") if isinstance(globals().get("_ROLLUP_CACHE"), dict) else {}; _ROLLUP_LOCK = globals().get("_ROLLUP_LOCK") or threading.Lock()


def _rollup_ttl():
    try:
        return max(0.0, float(os.environ.get("ANCHOR_USAGE_ROLLUP_TTL_S", "15")))
    except ValueError:
        return 15.0


def _usage_rollup(cdir, estate=None):
    """A cockpit's usage figures, reused for a few seconds (2026-10-11 speed): every open tile asks for its state every
    few seconds and recomputing these from every engine record was ~40% of the service's busy time. Spend and token
    figures a quarter-minute old are fine; a caller handing its own engine state always gets a fresh figure."""
    ttl = _rollup_ttl()
    if estate is not None or not ttl:
        return _usage_rollup_fresh(cdir, estate)
    key = os.path.normcase(os.path.abspath(cdir))
    now = time.monotonic()
    with _ROLLUP_LOCK:
        hit = _ROLLUP_CACHE.get(key)
        if hit and now - hit[0] < ttl:
            return copy.deepcopy(hit[1])
    value = _usage_rollup_fresh(cdir)
    with _ROLLUP_LOCK:
        if len(_ROLLUP_CACHE) > 256:
            _ROLLUP_CACHE.clear()
        _ROLLUP_CACHE[key] = (now, value)
    return copy.deepcopy(value)


def _usage_rollup_fresh(cdir, estate=None):
    numeric_fields = ("reported_spend", "unpriced_turns", "estimated_spend", "estimated_turns",
                      "tokens", "secs", "turns", "cumulative_tokens", "cumulative_estimated_spend")
    coverage_fields = ("tracked_invocations", "reported_invocations", "partial_invocations",
                       "unavailable_invocations", "finalized_invocations")
    def zero():
        return {"reported_spend": 0.0, "unpriced_turns": 0, "estimated_spend": 0.0, "estimated_turns": 0,
                "tokens": 0, "secs": 0, "turns": 0, "cumulative_tokens": 0, "cumulative_estimated_spend": 0.0,
                "checkpoint_coverage": {field: 0 for field in coverage_fields},
                "usage_updated_at": None, "_cost_known": 0, "_cost_unknown": 0,
                "_tokens_known": 0, "_tokens_unknown": 0, "_tokens_partial": 0,
                "_sub_unpriced": 0, "_other_unpriced": 0, "_sub_clis": []}
    def number(value):
        return isinstance(value, (int, float)) and not isinstance(value, bool) and 0 <= value < float("inf")
    from steward_cockpit.steward_engine import (
        _backfill_usage_estimate, _read_all_state, _usage_snapshot, estimate_list_price_usd, fmt_usage_cost_text, infer_subscription_cli)
    if estate is None:
        estate = _read_all_state()
    stew, term = zero(), zero()
    cdir_n = os.path.realpath(cdir)
    discovered = campaign.discover_efforts(cdir_n)
    allowed_roots = ({cdir_n} | {os.path.realpath(str(Path(cdir_n) / e["rel"])) for e in discovered if e.get("rel")}) if discovered else None
    for key, entry in estate.items():
        base = os.path.realpath(key.split("||")[0])
        # exact boundary, not a string prefix: '.../foo' must not match '.../foobar'
        if base != cdir_n and not base.startswith(cdir_n + os.sep):
            continue
        if allowed_roots is not None and base != cdir_n and not any(base == r or base.startswith(r + os.sep) for r in allowed_roots if r != cdir_n):
            continue
        raw = entry.get("usage")
        u = _backfill_usage_estimate(_usage_snapshot(raw), raw, entry.get("model_policy"))
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
            est = estimate_list_price_usd(row.get("model"), row.get("usage"))
            if est is not None:
                b["estimated_spend"] += est
                b["estimated_turns"] += 1
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
        bucket["cumulative_estimated_spend"] = round(bucket.get("cumulative_estimated_spend", 0.0), 4)
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


_GLOBAL_USAGE_CACHE = globals().get("_GLOBAL_USAGE_CACHE") if isinstance(globals().get("_GLOBAL_USAGE_CACHE"), dict) else {}; _GLOBAL_USAGE_LOCK = globals().get("_GLOBAL_USAGE_LOCK") or threading.Lock()

_FAMILY_DEFAULT_MODELS = {
    "claude": "claude-opus-5-5",
    "chatgpt": "gpt-6-astra",
    "gemini": "gemini-4-argon-high",
    "grok": "grok-4.20",
}

_FAMILY_LABELS = {
    "claude": "Claude",
    "chatgpt": "ChatGPT",
    "gemini": "Gemini",
    "grok": "Grok",
}


def _compute_global_usage_summary():
    from datetime import datetime, timedelta, timezone
    import paths as _paths
    from steward_cockpit import steward_engine as _se
    try:
        target_state = _paths.data_dir() / "steward-cockpit-state.json"
        if target_state.exists():
            _se.relocate_state(target_state)
    except Exception:
        pass
    now = datetime.now(timezone.utc)
    cut5h = (now - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cut7d = (now - timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    cut30d = (now - timedelta(days=30)).strftime("%Y-%m-%dT%H:%M:%SZ")

    prices = _se.api_list_prices()
    estate = _se._read_all_state()

    try:
        import rnd_registry as _rr
        raw_projs = _rr.list_projects()
        projects_list = raw_projs if isinstance(raw_projs, list) else []
    except Exception:
        projects_list = []

    proj_by_id = {}
    folder_to_proj = []
    for p in projects_list:
        if not isinstance(p, dict) or not p.get("id"):
            continue
        pid = str(p["id"])
        pname = str(p.get("name") or pid)
        fp = str(p.get("folder_path") or "").strip()
        if pname.startswith("__healthcheck__"):
            continue
        proj_by_id[pid] = {"project_id": pid, "name": pname, "folder_path": fp}
        if fp and fp != ".":
            try:
                norm_fp = os.path.normcase(os.path.realpath(fp))
                folder_to_proj.append((len(norm_fp), norm_fp, pid, pname))
            except Exception:
                pass
    folder_to_proj.sort(reverse=True)

    def match_proj(folder):
        if not folder:
            return None, None
        try:
            nf = os.path.normcase(os.path.realpath(str(folder)))
        except Exception:
            return None, None
        for _, norm_fp, pid, pname in folder_to_proj:
            if nf == norm_fp or nf.startswith(norm_fp.rstrip(os.sep) + os.sep):
                return pid, pname
        return None, None

    sid_map = {}
    for skey, entry in estate.items():
        if not isinstance(entry, dict):
            continue
        base_dir = skey.split("||")[0]
        if "Temp" in base_dir or "scratchpad" in base_dir or "anchor-hc-" in base_dir:
            continue
        pid, pname = match_proj(base_dir)
        for ps in (entry.get("provider_sessions") or []):
            if isinstance(ps, dict) and ps.get("session_id"):
                mp = ps.get("model_policy") if isinstance(ps.get("model_policy"), dict) else {}
                fam = ps.get("family") or mp.get("family") or entry.get("cli")
                mod = mp.get("model_served") or mp.get("model")
                sid_map[str(ps["session_id"])] = (fam, mod, pid, pname, base_dir)
        if entry.get("session_id"):
            mp = entry.get("model_policy") if isinstance(entry.get("model_policy"), dict) else {}
            fam = entry.get("cli") or mp.get("family")
            mod = mp.get("model_served") or mp.get("model")
            sid_map[str(entry["session_id"])] = (fam, mod, pid, pname, base_dir)

    seen_keys = set()
    records = []
    try:
        import usage_ledger as _ul
    except Exception:
        _ul = None

    if _ul is not None:
        ledger_dir = _paths.data_dir() / ".anchor" / "usage_ledger"
        extra_sids = []
        if ledger_dir.is_dir():
            try:
                for p in ledger_dir.iterdir():
                    if p.suffix.lower() == ".json" and p.stem not in sid_map:
                        extra_sids.append(p.stem)
            except Exception:
                pass
        all_sid_items = list(sid_map.items()) + [(s, (None, None, None, None, None)) for s in extra_sids]
        for sid, (fam, mod, pid, pname, base_dir) in all_sid_items:
            doc = _ul.load_ledger(sid)
            es = sorted((doc.get("entries") or {}).items(), key=lambda kv: str((kv[1] or {}).get("recorded_at") or ""))
            prev_by_sess = {}
            for k, e in es:
                if not isinstance(e, dict):
                    continue
                ukey = (sid, k)
                if ukey in seen_keys:
                    continue
                seen_keys.add(ukey)
                efam = str(e.get("cli") or fam or "claude").lower()
                emod = e.get("model") or mod
                e_copy = dict(e)
                u = e.get("usage")
                if not isinstance(u, dict) and ("input_tokens" in e or "output_tokens" in e):
                    u = {
                        "input_tokens": int(e.get("input_tokens") or 0),
                        "cached_input_tokens": int(e.get("cached_input_tokens") or 0),
                        "output_tokens": int(e.get("output_tokens") or 0),
                    }
                    e_copy["usage"] = u
                sess_key = str(e.get("session_id") or sid)
                src = e.get("source")
                if efam in ("chatgpt", "gemini") and (src in ("steward-turn", "terminal-turn", None)):
                    tok = int(e.get("tokens") or 0)
                    prev_u, prev_tok = prev_by_sess.get(sess_key, (None, 0))
                    if isinstance(u, dict) and isinstance(prev_u, dict):
                        in_c = int(u.get("input_tokens") or 0)
                        out_c = int(u.get("output_tokens") or 0)
                        ca_c = int(u.get("cached_input_tokens") or u.get("cache_read_input_tokens") or 0)
                        in_p = int(prev_u.get("input_tokens") or 0)
                        out_p = int(prev_u.get("output_tokens") or 0)
                        ca_p = int(prev_u.get("cached_input_tokens") or prev_u.get("cache_read_input_tokens") or 0)
                        if in_c >= in_p and out_c >= out_p and ca_c >= ca_p:
                            e_copy["tokens"] = tok - prev_tok
                            e_copy["usage"] = {
                                "input_tokens": in_c - in_p,
                                "output_tokens": out_c - out_p,
                                "cached_input_tokens": ca_c - ca_p,
                            }
                    has_u = isinstance(u, dict) and (int(u.get("input_tokens") or 0) > 0 or int(u.get("output_tokens") or 0) > 0)
                    prev_by_sess[sess_key] = (u if has_u else prev_u, tok if tok > 0 else prev_tok)
                epid = e.get("project_id") or pid
                epname = (proj_by_id.get(epid) or {}).get("name") or pname
                records.append((efam, emod, epid, epname, e_copy))

    try:
        import usage_index as _ui
    except Exception:
        _ui = None

    if _ui is not None:
        for pid, pinfo in proj_by_id.items():
            for r in _ui.load_rows(pid):
                if not isinstance(r, dict):
                    continue
                esid = r.get("engine_session_uuid")
                if esid == "stub":
                    continue
                ukey = (esid, r.get("key"))
                if ukey in seen_keys:
                    continue
                seen_keys.add(ukey)
                sfam, smod, _, _, _ = sid_map.get(str(esid or ""), (None, None, None, None, None))
                rfam = str(r.get("cli") or sfam or "claude").lower()
                rmod = r.get("model") or smod
                records.append((rfam, rmod, pid, pinfo["name"], r))

    def normalize_model(fam, mod):
        m = str(mod or "").strip()
        if not m or m in ("best", "latest_supported", "<synthetic>", "False", "None"):
            return _FAMILY_DEFAULT_MODELS.get(fam, "claude-opus-5-5")
        return m

    def extract_io(r, tok):
        u = r.get("usage")
        if isinstance(u, dict) and ("input_tokens" in u or "output_tokens" in u):
            in_t = int(u.get("input_tokens") or 0)
            ca_t = int(u.get("cached_input_tokens") or u.get("cache_read_input_tokens") or 0)
            out_t = int(u.get("output_tokens") or 0)
            total_in = in_t + ca_t if "cache_read_input_tokens" in u and in_t < ca_t else in_t
            return total_in, ca_t, out_t
        if tok > 0:
            return int(tok * 0.95), int(tok * 0.85), max(1, int(tok * 0.05))
        return 0, 0, 0

    def price_record(fam, eff_mod, r):
        c = r.get("cost_usd")
        reported = float(c) if isinstance(c, (int, float)) and not isinstance(c, bool) and c > 0 else 0.0
        if reported > 0:
            return reported, 0.0, reported
        u = r.get("usage")
        est = None
        if isinstance(u, dict) and ("input_tokens" in u or "output_tokens" in u):
            in_t = int(u.get("input_tokens") or 0)
            ca_t = int(u.get("cached_input_tokens") or u.get("cache_read_input_tokens") or 0)
            out_t = int(u.get("output_tokens") or 0)
            norm_u = {
                "input_tokens": in_t + ca_t if "cache_read_input_tokens" in u and in_t < ca_t else in_t,
                "cached_input_tokens": ca_t,
                "output_tokens": out_t,
            }
            est = _se.estimate_list_price_usd(eff_mod, norm_u)
        if est is None:
            tok = int(r.get("tokens") or 0)
            if tok > 0:
                est = _se.estimate_list_price_usd(eff_mod, {
                    "input_tokens": int(tok * 0.95),
                    "cached_input_tokens": int(tok * 0.85),
                    "output_tokens": max(1, int(tok * 0.05)),
                })
        estimated = float(est) if est is not None else 0.0
        return 0.0, estimated, estimated

    def empty_win():
        return {"tokens": 0, "turns": 0, "reported_spend_usd": 0.0, "estimated_spend_usd": 0.0, "hypothetical_api_usd": 0.0}

    windows = {w: empty_win() for w in ("5h", "7d", "30d", "all_time")}
    providers = {}
    for fam in ("claude", "chatgpt", "gemini", "grok"):
        providers[fam] = {
            "family": fam,
            "label": _FAMILY_LABELS[fam],
            "default_model": _FAMILY_DEFAULT_MODELS[fam],
            "rate_limit": None,
            "5h": empty_win(),
            "7d": empty_win(),
            "30d": empty_win(),
            "all_time": empty_win(),
            "_models": {},
        }
    proj_agg = {}
    price_models = (prices.get("models") if isinstance(prices, dict) else None) or {}

    for fam, mod, pid, pname, r in records:
        if fam not in providers:
            continue
        tok = int(r.get("tokens") or 0)
        if tok < 0:
            tok = 0
        eff_mod = normalize_model(fam, mod)
        rep, est, hyp = price_record(fam, eff_mod, r)
        in_tok, ca_tok, out_tok = extract_io(r, tok)
        at = str(r.get("recorded_at") or "")

        active_wins = ["all_time"]
        if at >= cut30d:
            active_wins.append("30d")
        if at >= cut7d:
            active_wins.append("7d")
        if at >= cut5h:
            active_wins.append("5h")

        p_entry = providers[fam]
        m_entry = p_entry["_models"].setdefault(eff_mod, {
            "model": eff_mod,
            "family": fam,
            "tokens_5h": 0, "in_5h": 0, "out_5h": 0, "usd_5h": 0.0, "turns_5h": 0,
            "tokens_7d": 0, "in_7d": 0, "out_7d": 0, "usd_7d": 0.0, "turns_7d": 0,
            "tokens_30d": 0, "in_30d": 0, "out_30d": 0, "usd_30d": 0.0, "turns_30d": 0,
            "tokens_all": 0, "in_all": 0, "out_all": 0, "usd_all": 0.0, "turns_all": 0,
        })

        for w in active_wins:
            for target in (windows[w], p_entry[w]):
                target["tokens"] += tok
                target["turns"] += 1
                target["reported_spend_usd"] += rep
                target["estimated_spend_usd"] += est
                target["hypothetical_api_usd"] += hyp

        m_entry["tokens_all"] += tok
        m_entry["in_all"] += in_tok
        m_entry["out_all"] += out_tok
        m_entry["usd_all"] += hyp
        m_entry["turns_all"] += 1
        if "30d" in active_wins:
            m_entry["tokens_30d"] += tok
            m_entry["in_30d"] += in_tok
            m_entry["out_30d"] += out_tok
            m_entry["usd_30d"] += hyp
            m_entry["turns_30d"] += 1
        if "7d" in active_wins:
            m_entry["tokens_7d"] += tok
            m_entry["in_7d"] += in_tok
            m_entry["out_7d"] += out_tok
            m_entry["usd_7d"] += hyp
            m_entry["turns_7d"] += 1
        if "5h" in active_wins:
            m_entry["tokens_5h"] += tok
            m_entry["in_5h"] += in_tok
            m_entry["out_5h"] += out_tok
            m_entry["usd_5h"] += hyp
            m_entry["turns_5h"] += 1

        if pid:
            pa = proj_agg.setdefault(pid, {
                "project_id": pid,
                "name": pname or pid,
                "tokens_7d": 0, "usd_7d": 0.0, "turns_7d": 0,
                "tokens_30d": 0, "usd_30d": 0.0, "turns_30d": 0,
                "tokens_all": 0, "usd_all": 0.0, "turns_all": 0,
            })
            pa["tokens_all"] += tok
            pa["usd_all"] += hyp
            pa["turns_all"] += 1
            if "30d" in active_wins:
                pa["tokens_30d"] += tok
                pa["usd_30d"] += hyp
                pa["turns_30d"] += 1
            if "7d" in active_wins:
                pa["tokens_7d"] += tok
                pa["usd_7d"] += hyp
                pa["turns_7d"] += 1

    try:
        import usage_capacity as _ucap
        sig = _ucap.latest_limit_signal(now)
        providers["claude"]["rate_limit"] = sig
    except Exception:
        pass

    for w_obj in windows.values():
        w_obj["reported_spend_usd"] = round(w_obj["reported_spend_usd"], 2)
        w_obj["estimated_spend_usd"] = round(w_obj["estimated_spend_usd"], 2)
        w_obj["hypothetical_api_usd"] = round(w_obj["hypothetical_api_usd"], 2)
        w_obj["total_tokens"] = w_obj["tokens"]
        w_obj["hypothetical_usd"] = w_obj["hypothetical_api_usd"]
        w_obj["by_family"] = {}
        w_obj["by_model"] = {}

    all_models = []
    win_suffix = {"5h": "5h", "7d": "7d", "30d": "30d", "all_time": "all"}
    for fam, p_entry in providers.items():
        for w in ("5h", "7d", "30d", "all_time"):
            w_obj = p_entry[w]
            w_obj["reported_spend_usd"] = round(w_obj["reported_spend_usd"], 2)
            w_obj["estimated_spend_usd"] = round(w_obj["estimated_spend_usd"], 2)
            w_obj["hypothetical_api_usd"] = round(w_obj["hypothetical_api_usd"], 2)
            windows[w]["by_family"][fam] = {
                "total_tokens": w_obj["tokens"],
                "hypothetical_usd": w_obj["hypothetical_api_usd"],
                "turns": w_obj["turns"],
            }
        models_list = []
        for m_obj in p_entry.pop("_models").values():
            m_obj["usd_5h"] = round(m_obj["usd_5h"], 2)
            m_obj["usd_7d"] = round(m_obj["usd_7d"], 2)
            m_obj["usd_30d"] = round(m_obj["usd_30d"], 2)
            m_obj["usd_all"] = round(m_obj["usd_all"], 2)
            pm = price_models.get(m_obj["model"]) or {}
            rates = {"in": pm.get("input_per_mtok"), "out": pm.get("output_per_mtok")} if pm else {}
            m_obj["rates"] = rates
            models_list.append(m_obj)
            all_models.append(dict(m_obj))
            for w, sfx in win_suffix.items():
                if m_obj[f"tokens_{sfx}"] > 0 or m_obj[f"usd_{sfx}"] > 0:
                    windows[w]["by_model"][m_obj["model"]] = {
                        "family": fam,
                        "total_tokens": m_obj[f"tokens_{sfx}"],
                        "input_tokens": m_obj[f"in_{sfx}"],
                        "output_tokens": m_obj[f"out_{sfx}"],
                        "hypothetical_usd": m_obj[f"usd_{sfx}"],
                        "turns": m_obj[f"turns_{sfx}"],
                        "rates": rates,
                    }
        models_list.sort(key=lambda x: (x["usd_30d"], x["tokens_30d"], x["usd_all"]), reverse=True)
        p_entry["models"] = models_list

    all_models.sort(key=lambda x: (x["usd_30d"], x["tokens_30d"], x["usd_all"]), reverse=True)
    projects_sorted = []
    for pa in proj_agg.values():
        pa["usd_7d"] = round(pa["usd_7d"], 2)
        pa["usd_30d"] = round(pa["usd_30d"], 2)
        pa["usd_all"] = round(pa["usd_all"], 2)
        projects_sorted.append(pa)
    projects_sorted.sort(key=lambda x: (x["usd_30d"], x["tokens_30d"], x["usd_all"]), reverse=True)

    summary_out = {
        "ok": True,
        "as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "price_table_as_of": prices.get("as_of"),
        "price_table_source": prices.get("source"),
        "windows": windows,
        "providers": providers,
        "models": all_models,
        "projects": projects_sorted,
    }
    try:
        import usage_allowance_monitor as _uam
        summary_out["allowance_monitor"] = _uam.compute_allowance_monitor(summary_out)
    except Exception:
        summary_out["allowance_monitor"] = {"ok": False, "families": {}}
    return summary_out


def usage_allowance_get(qs=None):
    """GET /api/steward/usage-allowance — live allowance & connection monitor for all 4 providers."""
    us, _ = global_usage_summary(qs)
    mon = (us or {}).get("allowance_monitor")
    if isinstance(mon, dict) and mon.get("families"):
        return mon, 200
    try:
        import usage_allowance_monitor as _uam
        return _uam.compute_allowance_monitor(us), 200
    except Exception as exc:
        return {"ok": False, "error": str(exc)}, 500


def usage_allowance_post(body: dict):
    """POST /api/steward/usage-allowance — probe Chrome CDP / open provider usage page or record manual/browser pct."""
    if not isinstance(body, dict):
        return {"ok": False, "error": "JSON object body required"}, 400
    import usage_allowance_monitor as _uam
    action = str(body.get("action") or "probe_browser").strip()
    if action == "record_browser_pct":
        fam = str(body.get("family") or "").strip().lower()
        pct = body.get("remaining_percent")
        if fam not in ("claude", "chatgpt", "gemini", "grok") or pct is None:
            return {"ok": False, "error": "family and remaining_percent required"}, 400
        try:
            pct_int = max(0, min(100, int(pct)))
        except (ValueError, TypeError):
            return {"ok": False, "error": "remaining_percent must be an integer 0..100"}, 400
        cache = _uam.load_browser_usage_cache()
        cache[fam] = {
            "remaining_percent": pct_int,
            "source": "browser_usage_page",
            "observed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        _uam.save_browser_usage_cache(cache)
        with _GLOBAL_USAGE_LOCK:
            _GLOBAL_USAGE_CACHE.clear()
        mon, _ = usage_allowance_get({"refresh": "1"})
        return {"ok": True, "action": action, "allowance_monitor": mon}, 200
    open_fam = str(body.get("family") or "").strip().lower() or None
    probe = _uam.probe_chrome_cdp_usage(
        port=9222,
        open_family=open_fam if action == "open_usage_page" else None,
    )
    with _GLOBAL_USAGE_LOCK:
        _GLOBAL_USAGE_CACHE.clear()
    mon, _ = usage_allowance_get({"refresh": "1"})
    return {"ok": True, "action": action, "probe": probe, "allowance_monitor": mon}, 200


def global_usage_summary(qs=None):
    """Dynamic multi-project token & hypothetical API spend summary across 5h, 7d, 30d, and all-time."""
    import paths as _paths
    from steward_cockpit import steward_engine as _se
    ttl = _rollup_ttl()
    raw_ref = qs.get("refresh") if isinstance(qs, dict) else None
    ref_val = raw_ref[0] if isinstance(raw_ref, list) and raw_ref else raw_ref
    force = str(ref_val or "").lower() in ("1", "true")
    key = (str(_se.STATE_FILE), str(_paths.data_dir()))
    now = time.monotonic()
    if not force and ttl:
        with _GLOBAL_USAGE_LOCK:
            hit = _GLOBAL_USAGE_CACHE.get(key)
            if hit and now - hit[0] < ttl:
                return copy.deepcopy(hit[1]), 200
    value = _compute_global_usage_summary()
    with _GLOBAL_USAGE_LOCK:
        _GLOBAL_USAGE_CACHE[key] = (now, value)
    return copy.deepcopy(value), 200


_STATE_CACHE = globals().get("_STATE_CACHE") if isinstance(globals().get("_STATE_CACHE"), dict) else {}; _STATE_LOCK = globals().get("_STATE_LOCK") or threading.Lock()


def _state_cached(eng, cdir):
    """The state poll (2026-10-11 speed): the app's tiles and the Cave page both ask every open cockpit every few
    seconds; one answer serves every asker for up to two seconds, and anything the engine says (a new event) makes the
    next ask fresh."""
    try:
        ttl = max(0.0, float(os.environ.get("ANCHOR_STATE_TTL_S", "2")))
    except ValueError:
        ttl = 2.0
    stamp = campaign.map_stamp(cdir)                  # a question or review written to disk is never answered stale
    key = (id(eng), getattr(eng, "seq", None), getattr(eng, "busy", None), getattr(eng, "tokens", None), getattr(eng, "turns", None), stamp)
    now = time.monotonic()
    if ttl:
        with _STATE_LOCK:
            hit = _STATE_CACHE.get(key)
            if hit and now - hit[0] < ttl:
                return copy.deepcopy(hit[1])
    st = _state_with_usage(eng, cdir)
    st["stamp"] = stamp
    if ttl:
        with _STATE_LOCK:
            for k in [k for k, v in _STATE_CACHE.items() if now - v[0] >= ttl]:
                _STATE_CACHE.pop(k, None)
            _STATE_CACHE[key] = (now, st)
        return copy.deepcopy(st)
    return st


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
        # W7 (2026-10-10): every open cockpit polls this; the answer is reused while the effort's files are unchanged
        # (and for at most _DELIV_TTL s, so a file that appears is seen) - rebuilt per poll it queued the whole server
        def _build(data):
            # 2026-10-07 (item 2): every item carries its ONE reading target - the URL the dialogue's receipt also uses
            try:
                import deliverables_register as _dr
                pid_q, dir_q = str(qs.get("pid", "")), str(qs.get("dir", ""))
                reg = {str(i.get("path") or "").replace(chr(92), "/").lower() for i in (data.get("items") or [])
                       if isinstance(i, dict)}
                reg |= {(_dr._canonical_route(i["route"]) or "").lower() for i in (data.get("items") or [])
                        if isinstance(i, dict) and i.get("route")}
                _root_real = Path(cdir).resolve() if cdir else None
                try:
                    from provider_native import private_homes as _ph
                    _priv_homes = _ph()
                except Exception:
                    _priv_homes = None
                for coll in (data.get("items") or [], data.get("approved") or []):
                    for it in coll:
                        if isinstance(it, dict):
                            it["reading"] = _dr.reading_target(it, pid=pid_q, effort_rel=dir_q, effort_dir=cdir, registered=reg, _root_real=_root_real, _priv_homes=_priv_homes)
                            for old in it.get("history") or []:          # earlier versions read the same way
                                if isinstance(old, dict):
                                    old["reading"] = _dr.reading_target(old, pid=pid_q, effort_rel=dir_q, effort_dir=cdir, registered=reg, _root_real=_root_real, _priv_homes=_priv_homes)
                for a in data.get("acts") or []:
                    if isinstance(a.get("item"), dict):
                        a["item"]["reading"] = _dr.reading_target(a["item"], pid=pid_q, effort_rel=dir_q, effort_dir=cdir, registered=reg, _root_real=_root_real, _priv_homes=_priv_homes)
                    for c in a.get("companions") or []:
                        if isinstance(c.get("item"), dict):
                            c["item"]["reading"] = _dr.reading_target(c["item"], pid=pid_q, effort_rel=dir_q, effort_dir=cdir, registered=reg, _root_real=_root_real, _priv_homes=_priv_homes)
            except Exception:
                pass   # the tile still builds its own link from the path
        return _deliverables_cached(cdir, qs, lambda: campaign.read_deliverables(cdir), _build), 200
    if verb == "deliverable-file":
        # Serve ONE deliverable's bytes, HARD-CONTAINED to the effort dir (realpath
        # prefix check — ../ or symlink escapes 404; active content served inert).
        rel = str(qs.get("path", ""))
        creal = os.path.realpath(str(cdir))
        real = os.path.realpath(str(Path(cdir) / rel))
        from provider_native import private_account_path
        if private_account_path(real):
            return {"error": "private host credentials are not deliverables"}, 403
        in_effort = (real == creal or real.startswith(creal + os.sep))
        if in_effort and not os.path.isfile(real) and rel and not rel.startswith(("/", "\\")) and ".." not in Path(rel).parts:
            # Resolve bare filenames (e.g. `CHAPTER-04-05-DRAFT-v2.docx` written in backticks in Steward dialogue)
            # against DELIVERABLES.md rows or effort subdirectories before checking code-job worktrees.
            if "/" not in rel and "\\" not in rel:
                target_name = Path(rel).name.lower()
                try:
                    deliv_data = campaign.read_deliverables(cdir)
                    for it in (deliv_data.get("items") or []) + (deliv_data.get("approved") or []):
                        if not isinstance(it, dict):
                            continue
                        ip = str(it.get("open_path") or it.get("path") or "").strip()
                        if ip and Path(ip).name.lower() == target_name:
                            cand_cdir = os.path.realpath(str(Path(cdir) / ip))
                            if (cand_cdir == creal or cand_cdir.startswith(creal + os.sep)) and os.path.isfile(cand_cdir) and not private_account_path(cand_cdir):
                                real = cand_cdir
                                rel = ip
                                break
                except Exception:
                    pass
                if not os.path.isfile(real):
                    try:
                        for sub in ("chapters", "deliverables", "story-arc", "editorial", "Finished Deliverables", ".ecgberht/journal"):
                            sub_root = Path(cdir) / sub
                            if not sub_root.is_dir():
                                continue
                            for match_p in sub_root.rglob("*"):
                                if match_p.is_file() and match_p.name.lower() == target_name:
                                    cand_sub = os.path.realpath(str(match_p))
                                    if (cand_sub == creal or cand_sub.startswith(creal + os.sep)) and not private_account_path(cand_sub):
                                        real = cand_sub
                                        break
                            if os.path.isfile(real):
                                break
                    except Exception:
                        pass
            # 2026-10-14 (John: "why are we still having problems with deliverables not landing"):
            # When a code job builds deliverables in its worktree and keeps them in kept_delivery
            # (or while a worktree has produced the file under work_dir), serve the kept file
            # cleanly so registered links never 404 while the follow-up landing finishes.
            if not os.path.isfile(real):
                try:
                    cj_path = Path(cdir) / ".ecgberht" / "code-jobs.json"
                    if cj_path.is_file():
                        cj_raw = json.loads(cj_path.read_text(encoding="utf-8"))
                        cj_rows = list(cj_raw.values()) if isinstance(cj_raw, dict) else (cj_raw if isinstance(cj_raw, list) else [])
                        target_name = Path(rel).name.lower()
                        for rec in reversed(cj_rows):
                            if not isinstance(rec, dict):
                                continue
                            wt = (rec.get("kept_delivery") or {}).get("worktree") or rec.get("worktree")
                            if not wt:
                                continue
                            wreal = os.path.realpath(str(wt))
                            wdir = str(rec.get("work_dir") or "").strip().strip("/\\")
                            rel_cands = [rel]
                            if wdir:
                                rel_cands.append(f"{wdir}/{rel}")
                            if "/" not in rel and "\\" not in rel:
                                for out_p in (rec.get("outputs") or []):
                                    if isinstance(out_p, str) and Path(out_p).name.lower() == target_name:
                                        rel_cands.append(out_p)
                            found_wt = False
                            for rc in rel_cands:
                                cand = os.path.realpath(str(Path(wt) / rc))
                                if (cand == wreal or cand.startswith(wreal + os.sep)) and os.path.isfile(cand) and not private_account_path(cand):
                                    real = cand
                                    found_wt = True
                                    break
                            if found_wt:
                                break
                except Exception:
                    pass
        if not in_effort or not os.path.isfile(real):
            return {"error": "not an openable deliverable (outside this effort or missing)"}, 404
        if os.path.getsize(real) > 50 * 1024 * 1024:
            return {"error": "file too large to serve inline (50MB cap)"}, 413
        expected_hash = qs.get("hash")
        if expected_hash and hashlib.sha256(Path(real).read_bytes()).hexdigest() != expected_hash:
            matched_rev_path = None
            if expected_hash != "0" * 64:
                try:
                    ref_state = (campaign.read_refinement(cdir) or {}).get("state") or {}
                    for sl in (ref_state.get("slices") or {}).values():
                        for rev in (sl.get("revisions") or {}).values():
                            if isinstance(rev, dict) and rev.get("hash") == expected_hash and rev.get("path"):
                                cand_rev = (Path(cdir) / str(rev["path"])).resolve()
                                if cand_rev.is_relative_to(Path(cdir).resolve()) and cand_rev.is_file():
                                    if hashlib.sha256(cand_rev.read_bytes()).hexdigest() == expected_hash:
                                        matched_rev_path = str(cand_rev)
                                        break
                        if matched_rev_path:
                            break
                except Exception:
                    matched_rev_path = None
            if matched_rev_path:
                real = matched_rev_path
            else:
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
        want_scrollview = str(qs.get("scrollview", "")).strip() in ("1", "true")
        raw_pdf_page = qs.get("pdf_page")
        want_pdf_page = None
        if raw_pdf_page is not None and str(raw_pdf_page).strip() != "":
            try:
                want_pdf_page = int(str(raw_pdf_page).strip())
            except (TypeError, ValueError):
                want_pdf_page = None
        ctype, disposition = deliverable_content_type(ext)
        if ext == ".pdf" and not want_download:
            if want_pdf_page is not None:
                return _serve_pdf_page_png(real, want_pdf_page)
            if want_scrollview:
                return _serve_pdf_scrollview(real, qs, rel, cdir)
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
                if want_pdf_page is not None:
                    return _serve_pdf_page_png(str(target), want_pdf_page)
                if want_scrollview:
                    return _serve_pdf_scrollview(str(target), qs, rel, cdir)
                return {"__file__": str(target), "__ctype__": "application/pdf", "__disposition__": "inline",
                        "__csp__": sandbox_csp_for("application/pdf")}, 200
            import html
            dl = "/api/steward/deliverable-file?pid=%s&dir=%s&path=%s&hash=%s&download=1" % (
                _q(str(qs.get("pid", ""))), _q(str(qs.get("dir", ""))), _q(rel), digest)
            if qs.get("token"):
                dl += "&token=" + _q(str(qs["token"]))
            import office_preview as _op_pptx
            return {"__html__": _op_pptx.render_preview(Path(real).read_bytes(), os.path.basename(real), dl)}, 200


        if str(qs.get("render", "")).strip() in ("1", "true") and not want_download and (
                ext in (".md", ".markdown", ".txt") or ext in _SOURCE_TEXT):
            # 2026-10-07 (execution minimum item 2): the canonical reading URL of a markdown product - formatted
            # (tables, links, math), never raw bytes; plain text keeps its lines in a code block
            import report_viewer
            text = Path(real).read_text(encoding="utf-8", errors="replace")
            if ext not in (".md", ".markdown"):          # plain text and program source keep their lines
                text = "```\n" + text.replace("```", "'''") + "\n```"
            return {"__html__": report_viewer.reader_html(text, title=os.path.basename(real))}, 200
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
        m = dict(campaign.read_map(cdir, include_plan_history=True))
        # W0b (High Seat, 2026-09-26): a part that points at another record is resolved at read,
        # once per distinct target per request; a broken reference is named on the page, never blank.
        try:
            from steward_cockpit.campaign_parts import resolve_parts
            m["resolved"] = resolve_parts(m.get("steps") or [], cache={}, with_lead=True)
        except Exception:
            m["resolved"] = {}
        # Slim multi-megabyte refinement history blobs for HTTP wire transfer while preserving all UI fields
        def _slim_handoff(h):
            if not isinstance(h, dict):
                return h
            return {hk: h[hk] for hk in ("id", "step_id", "status", "terminal", "at", "summary", "title") if hk in h}

        ref = m.get("refinement")
        if isinstance(ref, dict):
            ref_slim = {k: v for k, v in ref.items() if k != "approved_products"}
            st_state = ref_slim.get("state")
            if isinstance(st_state, dict):
                handoffs = st_state.get("producer_handoffs")
                slim_handoffs = (
                    {k: _slim_handoff(v) for k, v in handoffs.items() if isinstance(v, dict) and v.get("status") == "pending_steward_review"}
                    if isinstance(handoffs, dict)
                    else {}
                )
                ref_slim["state"] = {
                    k: v for k, v in st_state.items() if k not in ("slices", "producer_handoffs", "events", "history")
                }
                ref_slim["state"]["producer_handoffs"] = slim_handoffs
            m["refinement"] = ref_slim
        if isinstance(m.get("steps"), list):
            slim_steps = []
            for st_item in m["steps"]:
                if isinstance(st_item, dict) and isinstance(st_item.get("refinement"), dict):
                    st_copy = dict(st_item)
                    r_orig = st_item["refinement"]
                    r_slim = {
                        k: r_orig[k]
                        for k in ("phase", "round", "display_round", "candidate", "title", "step_id", "status")
                        if k in r_orig
                    }
                    if isinstance(r_orig.get("producer_handoffs"), list):
                        r_slim["producer_handoffs"] = [_slim_handoff(ph) for ph in r_orig["producer_handoffs"]]
                    st_copy["refinement"] = r_slim
                    slim_steps.append(st_copy)
                else:
                    slim_steps.append(st_item)
            m["steps"] = slim_steps
        m["stamp"] = campaign.map_stamp(cdir)
        m["steward"] = _persona_name()
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
        return _state_cached(eng, cdir), 200
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
    if verb in ("anvil", "anvil/walkthrough"):
        import importlib
        from steward_cockpit import anvil_session as _as
        try:
            _as_mtime = Path(_as.__file__).stat().st_mtime_ns
            if getattr(_as, "_LOADED_MTIME_NS", None) != _as_mtime:
                _as = importlib.reload(_as)
                _as._LOADED_MTIME_NS = _as_mtime
        except Exception:
            pass
        if verb == "anvil/walkthrough" or str(qs.get("action") or "").strip().lower() == "walkthrough":
            return _as.walkthrough_in_session(cdir, str(qs.get("block_id") or qs.get("block") or "")), 200
        return _as.get_session_status(cdir), 200
    if verb == "aegis":
        import importlib
        from steward_cockpit import aegis_session as _aeg
        try:
            _aeg_mtime = Path(_aeg.__file__).stat().st_mtime_ns
            if getattr(_aeg, "_LOADED_MTIME_NS", None) != _aeg_mtime:
                _aeg = importlib.reload(_aeg)
                _aeg._LOADED_MTIME_NS = _aeg_mtime
        except Exception:
            pass
        return _aeg.get_cockpit_aegis_state(cdir, auto_init=True), 200
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
    if verb == "mothership-files":
        return _mothership_files_get(cdir, qs)
    if verb == "filetext":
        return _filetext(cdir, qs.get("path", ""))
    if verb == "spellcheck":
        from steward_cockpit import spellcheck_engine as _se
        w = str(qs.get("word") or "").strip()
        if w:
            return _se.check_word(w), 200
        return _se.check_text(str(qs.get("text") or "")), 200
    if verb == "dictate":
        from steward_cockpit import dictation_engine as _de
        try:
            since = int(qs.get("since") or "0")
        except (TypeError, ValueError):
            since = 0
        return _de.poll_session(since), 200
    if verb in ("plan-history", "plan/history", "plan-proposal", "plan/proposal"):
        return {
            "ok": True,
            "history": campaign.read_plan_history(cdir),
            "proposal": campaign.read_plan_proposal(cdir),
        }, 200
    if verb == "fleet-brief":
        from steward_cockpit.campaign_say import build_fleet_brief, is_cave_folder
        camp_dir = str(Path(cdir).parent) if is_cave_folder(cdir) and (Path(cdir).parent / "roadmap.json").is_file() else cdir
        if not (Path(camp_dir) / "roadmap.json").is_file():
            camp_dir = _DEFAULT_CAMPAIGN_DIR
        return build_fleet_brief(camp_dir), 200
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
    if not eng.general and not eng.alive():
        from steward_cockpit.steward_engine import _read_state_entry, prune_persisted_job_queue
        prune_persisted_job_queue(eng.skey())
        now = time.time()
        entry = _read_state_entry(eng.skey())
        has_in_flight = bool(entry.get("in_flight") or entry.get("submitted") or entry.get("pending_queue"))
        has_durable_work = (entry.get("session_id")
                            or has_in_flight)
        from steward_cockpit import maintenance
        if ((since == 0 or has_in_flight)
                and getattr(eng, "_auto_wake_at", 0) + 60 < now
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
_SOURCE_TEXT = __import__("report_viewer").SOURCE_TEXT_EXTENSIONS    # program source reads as text, never a download
_DELIVERABLE_TYPES.update({e: ("text/plain; charset=utf-8", "inline") for e in _SOURCE_TEXT if e not in _DELIVERABLE_TYPES})


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


def _serve_pdf_page_png(real_path: str, page_idx: int):
    """Render a single PDF page to PNG via PyMuPDF (fitz) for scrollable split-view."""
    try:
        fitz = importlib.import_module("fitz")
        st = os.stat(real_path)
        cache_dir = Path(tempfile.gettempdir()) / "anchor-pdf-pages"
        cache_dir.mkdir(parents=True, exist_ok=True)
        hkey = hashlib.sha256(f"{real_path}:{st.st_mtime_ns}:{st.st_size}:{page_idx}".encode("utf-8")).hexdigest()[:24]
        cache_png = cache_dir / f"{hkey}-p{page_idx}.png"
        if not cache_png.is_file():
            doc = fitz.open(real_path)
            if page_idx < 0 or page_idx >= len(doc):
                doc.close()
                return {"error": "pdf page out of range"}, 404
            page = doc[page_idx]
            pix = page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
            png_bytes = pix.tobytes("png")
            doc.close()
            tmp_png = cache_png.with_suffix(".tmp")
            tmp_png.write_bytes(png_bytes)
            os.replace(tmp_png, cache_png)
        return {"__file__": str(cache_png), "__ctype__": "image/png", "__disposition__": "inline"}, 200
    except Exception as exc:
        return {"error": f"pdf page render failed: {exc}"}, 500


def _serve_pdf_scrollview(real_path: str, qs: dict, rel: str, cdir: str):
    """Serve a PDF deliverable as a scrollable same-origin HTML page of high-DPI page images
    so wheel scrolling, PageUp/PageDown, and non-focus-stealing scroll buttons work seamlessly
    while dictating with Win+H or 🎤 Dictate."""
    try:
        fitz = importlib.import_module("fitz")
        import html as _html
        doc = fitz.open(real_path)
        page_count = len(doc)
        doc.close()
        if page_count <= 0:
            raise ValueError("empty pdf")
    except Exception:
        return {"__file__": real_path, "__ctype__": "application/pdf", "__disposition__": "inline",
                "__csp__": sandbox_csp_for("application/pdf")}, 200

    import html as _html
    pid_q = _q(str(qs.get("pid", "")))
    dir_q = _q(str(qs.get("dir", "")))
    rel_q = _q(str(rel or ""))
    tok_q = ("&token=" + _q(str(qs.get("token")))) if qs.get("token") else ""
    hash_q = ("&hash=" + _q(str(qs.get("hash")))) if qs.get("hash") else ""
    view_q = ("&view=1") if str(qs.get("view", "")).strip() in ("1", "true") else ""
    base_url = f"/api/steward/deliverable-file?pid={pid_q}&dir={dir_q}&path={rel_q}{hash_q}{view_q}{tok_q}"
    dl_url = f"/api/steward/deliverable-file?pid={pid_q}&dir={dir_q}&path={rel_q}{hash_q}&download=1{tok_q}"
    native_url = base_url
    fname = _html.escape(os.path.basename(real_path))
    ext_badge = "PPTX → PDF SLIDES" if str(rel or "").lower().endswith(".pptx") else "PDF DOCUMENT"

    pages_html = []
    for i in range(page_count):
        load_attr = "eager" if i < 3 else "lazy"
        img_src = _html.escape(f"{base_url}&pdf_page={i}", quote=True)
        pages_html.append(
            f'<section class="pdf-page-card" id="pdf-page-{i+1}" data-page="{i+1}">'
            f'<div class="pdf-page-hdr"><span>Page {i+1} of {page_count}</span></div>'
            f'<img class="pdf-page-img" loading="{load_attr}" src="{img_src}" alt="Page {i+1} of {fname}" />'
            f'</section>'
        )

    html_doc = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{fname}</title>"
        "<style>"
        "html,body{margin:0;padding:0;background:#0d1117;color:#e6edf3;font:14px/1.5 -apple-system,'Segoe UI',system-ui,sans-serif;scroll-behavior:smooth}"
        ".pdf-bar{position:sticky;top:0;z-index:20;background:rgba(22,27,34,0.96);backdrop-filter:blur(8px);"
        "border-bottom:1px solid #30363d;padding:8px 14px;display:flex;align-items:center;gap:8px;flex-wrap:wrap}"
        ".pdf-badge{font-size:11px;font-weight:700;padding:2px 7px;border-radius:5px;background:rgba(248,81,73,0.18);color:#ff7b72;border:1px solid rgba(248,81,73,0.4);letter-spacing:.04em}"
        ".pdf-title{font-weight:600;font-size:13px;color:#f0f6fc;max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        ".pdf-meta{font-size:12px;color:#8b949e}"
        ".pdf-spacer{flex:1 1 auto}"
        ".pdf-btn{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:6px;padding:4px 10px;font-size:12px;font-weight:600;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:4px;user-select:none}"
        ".pdf-btn:hover{background:#30363d;color:#fff;border-color:#58a6ff}"
        ".pdf-main{max-width:980px;margin:0 auto;padding:16px 14px 64px;display:flex;flex-direction:column;gap:18px}"
        ".pdf-page-card{background:#161b22;border:1px solid #30363d;border-radius:10px;overflow:hidden;box-shadow:0 6px 20px rgba(0,0,0,0.35)}"
        ".pdf-page-hdr{padding:6px 12px;background:#0d1117;border-bottom:1px solid #21262d;font-size:11px;font-weight:600;color:#8b949e;display:flex;justify-content:space-between}"
        ".pdf-page-img{display:block;width:100%;height:auto;background:#fff;user-select:none;-webkit-user-drag:none}"
        "</style></head><body>"
        "<div class='pdf-bar' onmousedown='event.preventDefault()'>"
        f"<span class='pdf-badge'>{ext_badge}</span>"
        f"<span class='pdf-title' title='{fname}'>{fname}</span>"
        f"<span class='pdf-meta'>{page_count} page{'s' if page_count != 1 else ''} · Win+H scroll-ready</span>"
        "<span class='pdf-spacer'></span>"
        "<button type='button' class='pdf-btn' onmousedown='event.preventDefault()' onclick='scrollStep(-1);restoreParentSayFocus();' title='Scroll Up (keeps Win+H dictation active)'>⬆ Page Up</button>"
        "<button type='button' class='pdf-btn' onmousedown='event.preventDefault()' onclick='scrollStep(1);restoreParentSayFocus();' title='Scroll Down (keeps Win+H dictation active)'>⬇ Page Down</button>"
        "<button type='button' class='pdf-btn' onmousedown='event.preventDefault()' onclick='adjustZoom(-15);restoreParentSayFocus();' title='Zoom Out'>🔍−</button>"
        "<button type='button' class='pdf-btn' onmousedown='event.preventDefault()' onclick='adjustZoom(15);restoreParentSayFocus();' title='Zoom In'>🔍+</button>"
        f"<a class='pdf-btn' href='{_html.escape(native_url, quote=True)}' target='_blank' rel='noopener' title='Open raw PDF in new tab'>📄 Native PDF</a>"
        f"<a class='pdf-btn' href='{_html.escape(dl_url, quote=True)}' title='Download file'>⬇ Download</a>"
        "</div>"
        f"<main class='pdf-main' id='pdfMain'>{''.join(pages_html)}</main>"
        "<script>"
        "var curZoom = 100; function scrollStep(dir){window.scrollBy({top:dir*Math.max(360,window.innerHeight*0.78),behavior:'smooth'});}"
        "function adjustZoom(delta){"
        "  curZoom = Math.max(60, Math.min(180, curZoom + delta));"
        "  var m = document.getElementById('pdfMain');"
        "  if(m) m.style.maxWidth = Math.round(980 * (curZoom / 100)) + 'px';"
        "}"
        "function restoreParentSayFocus(){"
        "  try {"
        "    if(window.parent && window.parent !== window && typeof window.parent.__restoreSayFocusIfActive === 'function'){"
        "      window.parent.__restoreSayFocusIfActive();"
        "    }"
        "  } catch(_e){}"
        "}"
        "window.addEventListener('message', function(ev){"
        "  if(!ev || !ev.data) return;"
        "  if(ev.data.type === 'anchor-scroll-deliverable'){"
        "    window.scrollBy({top: Number(ev.data.deltaY) || 420, behavior: 'smooth'});"
        "  }"
        "});"
        "document.addEventListener('mouseup', function(){"
        "  try {"
        "    var sel = window.getSelection ? String(window.getSelection()) : '';"
        "    if(!sel) restoreParentSayFocus();"
        "  } catch(_e){}"
        "});"
        "window.addEventListener('wheel', function(){"
        "  restoreParentSayFocus();"
        "}, {passive: true});"
        "</script></body></html>"
    )
    return {"__html__": html_doc}, 200


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


def _mothership_allowed_roots(cdir: str) -> list[dict]:
    """Return allowed Mothership browse roots starting with the active AI Cockpit folder."""
    cockpit_real = os.path.realpath(str(cdir))
    cockpit_name = Path(cockpit_real).name or "Cockpit"
    roots = [
        {"id": "cockpit", "label": f"📍 Cockpit ({cockpit_name})", "path": cockpit_real},
    ]
    dev_root = os.path.realpath(r"C:\dev")
    if os.path.isdir(dev_root):
        roots.append({"id": "workspace", "label": r"💻 C:\dev (Mothership)", "path": dev_root})
    home = Path.home()
    for rid, icon, sub in (
        ("downloads", "📥 Downloads", "Downloads"),
        ("documents", "📄 Documents", "Documents"),
        ("desktop", "🖥 Desktop", "Desktop"),
    ):
        cand = home / sub
        if cand.is_dir():
            roots.append({"id": rid, "label": icon, "path": os.path.realpath(str(cand))})
    return roots


def _is_allowed_mothership_path(real_path: str, roots: list[dict]) -> bool:
    try:
        from provider_native import private_account_path
        if private_account_path(real_path):
            return False
    except Exception:
        pass
    norm = os.path.normcase(os.path.realpath(real_path))
    for part in Path(norm).parts:
        low = part.lower()
        if low in (".ssh", ".aws", ".gnupg", ".claude", ".anchor", ".gemini", ".git", "node_modules", "__pycache__", ".venv"):
            return False
    for r in roots:
        rp = os.path.normcase(os.path.realpath(r["path"]))
        if norm == rp or norm.startswith(rp + os.sep):
            return True
    return False


def _mothership_files_get(cdir: str, qs: dict):
    """Browse directories and files on the Mothership where the AI Cockpit lives."""
    import socket
    cockpit_real = os.path.realpath(str(cdir))
    roots = _mothership_allowed_roots(cdir)
    raw_dir = str(qs.get("browse_dir") or qs.get("path") or "").strip()
    q = str(qs.get("q") or "").strip().lower()
    if raw_dir:
        cand = os.path.realpath(raw_dir if os.path.isabs(raw_dir) else os.path.join(cockpit_real, raw_dir))
    else:
        cand = cockpit_real
    if not os.path.isdir(cand) or not _is_allowed_mothership_path(cand, roots):
        cand = cockpit_real

    parent_dir = ""
    par_cand = os.path.realpath(os.path.dirname(cand))
    if par_cand != cand and _is_allowed_mothership_path(par_cand, roots):
        parent_dir = par_cand

    entries = []
    skip_dirs = {"node_modules", "__pycache__", "vendor", ".git", ".venv", ".ecgberht", ".anvil", ".aegis"}
    try:
        if q:
            hits = 0
            for root_, dirs, files_ in os.walk(cand):
                dirs[:] = [
                    d for d in dirs
                    if not d.startswith(".") and d not in skip_dirs
                    and _is_allowed_mothership_path(os.path.join(root_, d), roots)
                ]
                if root_[len(cand):].count(os.sep) > 3:
                    dirs[:] = []
                    continue
                for dname in dirs:
                    if q in dname.lower():
                        dfull = os.path.realpath(os.path.join(root_, dname))
                        try:
                            st_ = os.stat(dfull)
                            mt = int(st_.st_mtime)
                        except OSError:
                            mt = 0
                        in_cockpit = dfull == cockpit_real or dfull.startswith(cockpit_real + os.sep)
                        rel_c = os.path.relpath(dfull, cockpit_real).replace(os.sep, "/") if in_cockpit else ""
                        entries.append({
                            "name": os.path.relpath(dfull, cand).replace(os.sep, "/"),
                            "path": dfull,
                            "dir": True,
                            "size": 0,
                            "mtime": mt,
                            "ext": "",
                            "in_cockpit": in_cockpit,
                            "rel_to_cockpit": rel_c,
                        })
                        hits += 1
                for fname in files_:
                    if fname.startswith("."):
                        continue
                    if q in fname.lower():
                        ffull = os.path.realpath(os.path.join(root_, fname))
                        if not _is_allowed_mothership_path(ffull, roots):
                            continue
                        try:
                            st_ = os.stat(ffull)
                            size, mt = int(st_.st_size), int(st_.st_mtime)
                        except OSError:
                            size, mt = 0, 0
                        in_cockpit = ffull == cockpit_real or ffull.startswith(cockpit_real + os.sep)
                        rel_c = os.path.relpath(ffull, cockpit_real).replace(os.sep, "/") if in_cockpit else ""
                        entries.append({
                            "name": os.path.relpath(ffull, cand).replace(os.sep, "/"),
                            "path": ffull,
                            "dir": False,
                            "size": size,
                            "mtime": mt,
                            "ext": Path(fname).suffix.lower(),
                            "in_cockpit": in_cockpit,
                            "rel_to_cockpit": rel_c,
                        })
                        hits += 1
                        if hits >= 200:
                            break
                if hits >= 200:
                    break
        else:
            for name in sorted(os.listdir(cand), key=lambda s: s.lower())[:250]:
                if name.startswith(".") or name in skip_dirs:
                    continue
                full = os.path.realpath(os.path.join(cand, name))
                if not _is_allowed_mothership_path(full, roots):
                    continue
                isdir = os.path.isdir(full)
                try:
                    st_ = os.stat(full)
                    size, mt = (0 if isdir else int(st_.st_size)), int(st_.st_mtime)
                except OSError:
                    size, mt = 0, 0
                in_cockpit = full == cockpit_real or full.startswith(cockpit_real + os.sep)
                rel_c = os.path.relpath(full, cockpit_real).replace(os.sep, "/") if in_cockpit else ""
                entries.append({
                    "name": name,
                    "path": full,
                    "dir": isdir,
                    "size": size,
                    "mtime": mt,
                    "ext": "" if isdir else Path(name).suffix.lower(),
                    "in_cockpit": in_cockpit,
                    "rel_to_cockpit": rel_c,
                })
            entries.sort(key=lambda x: (0 if x["dir"] else 1, -x["mtime"], x["name"].lower()))
    except OSError as exc:
        return {"ok": False, "error": str(exc)}, 500

    return {
        "ok": True,
        "mothership_host": socket.gethostname(),
        "cockpit_dir": cockpit_real,
        "current_dir": cand,
        "parent_dir": parent_dir,
        "roots": roots,
        "q": q,
        "entries": entries,
    }, 200


def _mothership_files_post(cdir: str, body: dict):
    """Attach/stage a file from anywhere on the Mothership into this AI Cockpit folder."""
    cockpit_real = os.path.realpath(str(cdir))
    roots = _mothership_allowed_roots(cdir)
    raw_src = str(body.get("source_path") or body.get("path") or "").strip()
    if not raw_src:
        return {"ok": False, "error": "source_path is required"}, 400
    src_real = os.path.realpath(raw_src if os.path.isabs(raw_src) else os.path.join(cockpit_real, raw_src))
    if not _is_allowed_mothership_path(src_real, roots):
        return {"ok": False, "error": "path is outside allowed Mothership roots"}, 403
    if not os.path.isfile(src_real):
        return {"ok": False, "error": "file not found on Mothership"}, 404

    if src_real == cockpit_real or src_real.startswith(cockpit_real + os.sep):
        rel_path = os.path.relpath(src_real, cockpit_real).replace(os.sep, "/")
        return {
            "ok": True,
            "already_in_cockpit": True,
            "attached": False,
            "name": Path(src_real).name,
            "path": rel_path,
            "source_path": src_real,
            "cockpit_dir": cockpit_real,
        }, 200

    name = Path(src_real).name
    if _bad_component(name) or Path(name).suffix.lower() in DENY_UPLOAD_EXT:
        return {"ok": False, "error": "that file type cannot be attached"}, 400
    try:
        sz = os.path.getsize(src_real)
    except OSError as exc:
        return {"ok": False, "error": str(exc)}, 400
    if sz > MAX_UPLOAD_BYTES:
        return {"ok": False, "error": "file over 250 MB"}, 413

    try:
        data = Path(src_real).read_bytes()
    except OSError as exc:
        return {"ok": False, "error": f"could not read Mothership file: {exc}"}, 500

    b64 = base64.b64encode(data).decode("ascii")
    up_res, status = _upload(cdir, {"name": name, "data_b64": b64, "mode": "keepboth", "sub": ""})
    if status == 200 and up_res.get("ok"):
        saved_name = up_res.get("name") or name
        return {
            "ok": True,
            "already_in_cockpit": False,
            "attached": True,
            "name": saved_name,
            "path": saved_name,
            "source_path": src_real,
            "cockpit_dir": cockpit_real,
        }, 200
    return up_res, status


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
def drain_all():
    """Park every live cockpit engine of THIS service (the restart drain). Global: no project and no effort (W5,
    2026-10-09: the drain posted {} and was answered "unknown project", so for weeks nothing was parked)."""
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


def handle_post(cdir, verb, body):
    if verb == "clear-wait":
        cleared = []
        try:
            strip_path = Path(cdir) / "strip.json"
            if strip_path.is_file():
                sdata = json.loads(strip_path.read_text(encoding="utf-8"))
                if isinstance(sdata, dict) and sdata.get("human_wait"):
                    sdata["human_wait"] = ""
                    strip_path.write_text(json.dumps(sdata, indent=2), encoding="utf-8")
                    cleared.append("strip.human_wait")
        except Exception:
            pass
        try:
            rm_path = Path(cdir) / "roadmap.json"
            if rm_path.is_file():
                rm = json.loads(rm_path.read_text(encoding="utf-8"))
                changed_rm = False
                for s in (rm.get("roadmap_projection") or rm.get("steps") or []):
                    if isinstance(s, dict) and s.get("status") in ("waiting", "blocked"):
                        s["status"] = "active"
                        s.pop("waiting_on", None)
                        changed_rm = True
                if changed_rm:
                    rm_path.write_text(json.dumps(rm, indent=2), encoding="utf-8")
                    cleared.append("roadmap.waiting")
        except Exception:
            pass
        try:
            from steward_cockpit import steward_engine as _se
            _se._update_state(str(cdir), {"open_question": None, "question_context": None, "pending_questions": []})
            eng = get_engine(str(cdir), False, None, create=False)
            if eng is not None:
                eng.open_question = None
                eng.question_context = None
                if hasattr(eng, "pending_questions"):
                    eng.pending_questions = []
            cleared.append("engine.questions")
        except Exception:
            pass
        _DELIV_CACHE.clear()
        return {"ok": True, "cleared": cleared}, 200
    if verb in ("dismiss-deliverable", "deliverables/dismiss"):
        items = body.get("items")
        if isinstance(items, list) and items:
            last_res = {"ok": True, "dismissed_count": 0}
            for it in items:
                if isinstance(it, dict):
                    last_res = campaign.dismiss_deliverable(
                        cdir,
                        path=str(it.get("path") or ""),
                        product_id=str(it.get("product_id") or ""),
                        what=str(it.get("what") or ""),
                        revision_id=str(it.get("revision_id") or ""),
                        hash_val=str(it.get("hash") or ""),
                    )
            _DELIV_CACHE.clear()
            return last_res, 200
        result = campaign.dismiss_deliverable(
            cdir,
            path=str(body.get("path") or ""),
            product_id=str(body.get("product_id") or ""),
            what=str(body.get("what") or ""),
            revision_id=str(body.get("revision_id") or ""),
            hash_val=str(body.get("hash") or ""),
        )
        _DELIV_CACHE.clear()
        return result, 200 if result.get("ok") else 400
    if verb in ("plan-proposal", "plan/proposal", "plan-history", "plan/history"):
        res = campaign.resolve_plan_proposal(
            cdir,
            action=str(body.get("action") or "accept"),
            proposal_id=str(body.get("proposal_id") or body.get("version_id") or ""),
        )
        _DELIV_CACHE.clear()
        return res, 200 if res.get("ok") else 400
    if verb in ("step-done", "mark-step-done"):
        req_id = str(body.get("step_id") or body.get("step") or "").strip()
        rm_path = Path(cdir) / "roadmap.json"
        st_path = Path(cdir) / "strip.json"
        done_id, done_name, next_id, next_name = "", "", "", ""
        try:
            st_data = json.loads(st_path.read_text(encoding="utf-8")) if st_path.is_file() else {}
        except Exception:
            st_data = {}
        cur_strip_id = str((st_data.get("strip") or st_data).get("current_step_id") or "").strip()
        if rm_path.is_file():
            try:
                rm = json.loads(rm_path.read_text(encoding="utf-8"))
                steps = rm.get("roadmap_projection") if isinstance(rm.get("roadmap_projection"), list) else (rm.get("steps") if isinstance(rm.get("steps"), list) else [])
                target = None
                if req_id:
                    target = next((s for s in steps if isinstance(s, dict) and (str(s.get("id") or "") == req_id or str(s.get("name") or "") == req_id)), None)
                if target is None and cur_strip_id:
                    target = next((s for s in steps if isinstance(s, dict) and str(s.get("id") or "") == cur_strip_id and s.get("status") != "done"), None)
                if target is None:
                    target = next((s for s in steps if isinstance(s, dict) and s.get("status") in ("active", "in_progress", "waiting", "review")), None)
                if target is None:
                    target = next((s for s in steps if isinstance(s, dict) and s.get("status") not in ("done", "completed", "withdrawn")), None)
                if target is not None:
                    target["status"] = "done"
                    target.pop("waiting_on", None)
                    done_id = str(target.get("id") or "")
                    done_name = str(target.get("name") or target.get("title") or done_id)
                    nxt = next((s for s in steps if isinstance(s, dict) and str(s.get("id") or "") != done_id and s.get("status") not in ("done", "completed", "withdrawn")), None)
                    if nxt is not None:
                        if not any(isinstance(s, dict) and s.get("status") == "active" for s in steps):
                            nxt["status"] = "active"
                        next_id = str(nxt.get("id") or "")
                        next_name = str(nxt.get("name") or nxt.get("title") or next_id)
                    rm_path.write_text(json.dumps(rm, indent=2), encoding="utf-8")
                    campaign._record_plan_history_snapshot(
                        cdir,
                        steps,
                        label=f"{time.strftime('%Y-%m-%d')} · Completed '{done_name[:40]}'",
                        summary=f"Marked step '{done_name}' done" + (f" → active '{next_name}'" if next_name else ""),
                        trigger="step_done",
                    )
            except Exception as exc:
                return {"ok": False, "error": str(exc)}, 400
        if st_path.is_file() and isinstance(st_data, dict):
            try:
                inner = st_data.get("strip") if isinstance(st_data.get("strip"), dict) else st_data
                if next_id:
                    inner["current_step_id"] = next_id
                if inner.get("waiting_on"):
                    inner["waiting_on"] = None
                st_path.write_text(json.dumps(st_data, indent=2), encoding="utf-8")
            except Exception:
                pass
        _DELIV_CACHE.clear()
        return {"ok": True, "step_id": done_id or req_id, "step_name": done_name or req_id, "next_step_id": next_id, "next_step_name": next_name}, 200
    if verb in ("anvil", "anvil/walkthrough"):
        import importlib
        from steward_cockpit import anvil_session as _as
        try:
            _as_mtime = Path(_as.__file__).stat().st_mtime_ns
            if getattr(_as, "_LOADED_MTIME_NS", None) != _as_mtime:
                _as = importlib.reload(_as)
                _as._LOADED_MTIME_NS = _as_mtime
        except Exception:
            pass
        act = "walkthrough" if verb == "anvil/walkthrough" else str(body.get("action") or "start_code").strip()
        try:
            if act == "walkthrough":
                return _as.walkthrough_in_session(
                    cdir,
                    str(body.get("block_id") or body.get("block") or ""),
                ), 200
            if act in ("start_code", "start_paper"):
                res = _as.start_cockpit_session(
                    cdir,
                    mode="paper" if act == "start_paper" else str(body.get("mode") or "code"),
                    software_spec=str(body.get("software_target") or "."),
                    compare_spec=str(body.get("compare_target") or ""),
                    paper_spec=str(body.get("paper_target") or ""),
                    signed_off_drops=body.get("signed_off_drops") if isinstance(body.get("signed_off_drops"), list) else None,
                )
                try:
                    import deliverables_register as _dr
                    _dr.register(
                        cdir,
                        f"Anvil Session Report ({res.get('cockpit_name') or 'Cockpit'})",
                        "`ANVIL-REPORT.md`",
                    )
                except Exception:
                    pass
                return res, 200
            if act == "probe_block":
                return _as.probe_block_in_session(
                    cdir,
                    str(body.get("block_id") or ""),
                    str(body.get("lock_description") or ""),
                ), 200
            if act == "sign_off_drop":
                return _as.sign_off_null_space_in_session(
                    cdir,
                    str(body.get("function_name") or ""),
                ), 200
            if act == "attach_paper":
                return _as.attach_paper_to_session(
                    cdir,
                    str(body.get("paper_target") or ""),
                ), 200
            if act == "chat":
                q_str = str(body.get("question") or "").strip()
                res = _as.chat_in_session(
                    cdir,
                    q_str,
                    str(body.get("mode") or "map"),
                    str(body.get("target") or ""),
                )
                try:
                    eng = get_engine(cdir, create=False)
                    if eng is not None and q_str:
                        dlg = ((res.get("session") or {}).get("dialogue") or [])
                        last_asst = next((m.get("text") for m in reversed(dlg) if m.get("role") == "assistant" and m.get("text")), "")
                        eng._emit({"t": "john", "text": q_str})
                        if last_asst:
                            eng._emit({"t": "delta", "text": str(last_asst)})
                            eng._emit({"t": "turn_end", "tokens": 0})
                except Exception:
                    pass
                return res, 200
            if act == "reset":
                return _as.reset_cockpit_session(cdir), 200
            return {"ok": False, "error": f"unknown anvil action: {act}"}, 400
        except ValueError as exc:
            return {"ok": False, "error": str(exc)}, 400
    if verb == "aegis":
        import importlib
        from steward_cockpit import aegis_session as _aeg
        try:
            _aeg_mtime = Path(_aeg.__file__).stat().st_mtime_ns
            if getattr(_aeg, "_LOADED_MTIME_NS", None) != _aeg_mtime:
                _aeg = importlib.reload(_aeg)
                _aeg._LOADED_MTIME_NS = _aeg_mtime
        except Exception:
            pass
        act = str(body.get("action") or "scan").strip()
        if act in ("scan", "bind_target"):
            res = _aeg.run_cockpit_aegis_scan(
                cdir,
                target_spec=str(body.get("target") or "."),
                signed_off_ids=body.get("signed_off_ids") if isinstance(body.get("signed_off_ids"), list) else None,
                sync_anvil=bool(body.get("sync_anvil", act == "bind_target")),
            )
            try:
                import deliverables_register as _dr
                _dr.register(cdir, f"Aegis Security Audit Report ({res.get('cockpit_name') or 'Cockpit'})", "`AEGIS-SECURITY-REPORT.md`")
            except Exception:
                pass
            try:
                eng = get_engine(cdir, create=False)
                if eng is not None:
                    sc = (res.get("session") or {}).get("scan") or {}
                    seat = (res.get("session") or {}).get("model_seating") or {}
                    msg = (
                        f"🛡 **Aegis Security Audit (`{sc.get('verdict', 'PASS')}`):** Scanned `{sc.get('files_scanned', 0)}` Python files "
                        f"across all 6 OWASP/CWE families (`AEG-01`–`AEG-06`) — `{sc.get('total_findings', 0)}` open finding(s) "
                        f"(`{sc.get('auto_fixable_count', 0)}` auto-fixable). Seated on **`{seat.get('coding_model_id', 'gemini-4-argon')} · {seat.get('coding_effort', 'high')}`** "
                        f"+ **`{seat.get('review_model_id', 'claude-fable-5-1')} · {seat.get('review_effort', 'max')}`**; report saved to `AEGIS-SECURITY-REPORT.md`."
                    )
                    eng._emit({"t": "delta", "text": msg})
                    eng._emit({"t": "turn_end", "tokens": 0})
            except Exception:
                pass
            return res, 200
        if act == "remediate":
            res = _aeg.run_cockpit_aegis_remediate(
                cdir,
                apply=bool(body.get("apply")),
                rule_filter=str(body.get("rule") or ""),
            )
            return res, 200
        if act == "sign_off":
            res = _aeg.sign_off_aegis_finding(
                cdir,
                str(body.get("finding_id") or ""),
            )
            return res, 200
        if act == "chat":
            q_str = str(body.get("question") or "").strip()
            res = _aeg.chat_in_aegis_session(
                cdir,
                q_str,
                str(body.get("target") or ""),
            )
            try:
                eng = get_engine(cdir, create=False)
                if eng is not None and q_str:
                    dlg = ((res.get("session") or {}).get("dialogue") or [])
                    last_asst = next((m.get("text") for m in reversed(dlg) if m.get("role") == "assistant" and m.get("text")), "")
                    eng._emit({"t": "john", "text": q_str})
                    if last_asst:
                        eng._emit({"t": "delta", "text": str(last_asst)})
                        eng._emit({"t": "turn_end", "tokens": 0})
            except Exception:
                pass
            return res, 200
        return {"ok": False, "error": f"unknown aegis action: {act}"}, 400
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
        return drain_all()
    if verb == "spellcheck":
        from steward_cockpit import spellcheck_engine as _se
        act = str(body.get("action") or "").strip().lower()
        if act == "add":
            return _se.add_word(str(body.get("word") or "")), 200
        w = str(body.get("word") or "").strip()
        if w:
            return _se.check_word(w), 200
        return _se.check_text(str(body.get("text") or "")), 200
    if verb == "dictate":
        from steward_cockpit import dictation_engine as _de
        act = str(body.get("action") or "poll").strip().lower()
        if act == "transcribe":
            return _de.transcribe_audio(str(body.get("audio_b64") or "")), 200
        if act == "tts":
            return _de.synthesize_speech_wav(str(body.get("text") or ""), int(body.get("rate") or 1)), 200
        if act == "start":
            return _de.start_session(), 200
        if act == "stop":
            return _de.stop_session(), 200
        try:
            since = int(body.get("since") or 0)
        except (TypeError, ValueError):
            since = 0
        return _de.poll_session(since), 200
    if verb == "fleet-relay":
        from steward_cockpit.campaign_say import relay_to_cockpit_steward, is_cave_folder
        camp_dir = str(Path(cdir).parent) if is_cave_folder(cdir) and (Path(cdir).parent / "roadmap.json").is_file() else cdir
        if not (Path(camp_dir) / "roadmap.json").is_file():
            camp_dir = _DEFAULT_CAMPAIGN_DIR
        res = relay_to_cockpit_steward(
            camp_dir,
            str(body.get("target") or ""),
            str(body.get("action") or "open_deliverable"),
            str(body.get("text") or ""),
        )
        return res, (200 if res.get("ok") else 400)
    if verb == "status-ack":
        # 2026-08-25 (elegance S-batch): render receipt from the pane — never
        # spawns an engine (create=False); a dead engine just means no receipt.
        if not body.get("general") and str(body.get("text") or "").strip():
            try:
                campaign.reconcile_review_on_feedback(cdir, str(body.get("text") or ""))
                _DELIV_CACHE.clear()
            except Exception:
                pass
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
            from steward_cockpit.campaign_say import is_campaign_folder, is_cave_folder, say_campaign, fast_steward_command
            _is_cave = is_cave_folder(cdir)
            if is_campaign_folder(cdir) or _is_cave:
                _camp_dir = str(Path(cdir).parent) if _is_cave and (Path(cdir).parent / "roadmap.json").is_file() else cdir
                _goal = str(body.get("goal") or "").strip() or None
                _txt = str(body.get("text") or "")
                spoken = fast_steward_command(_camp_dir, _txt, goal=_goal, from_cave=_is_cave)
                if spoken is None:
                    spoken = say_campaign(_camp_dir, _txt, goal=_goal)
                    if spoken and not spoken.get("ok") and "a goal has no seat" in str(spoken.get("say") or ""):
                        spoken_goal = fast_steward_command(_camp_dir, _txt, goal=_goal, from_cave=_is_cave, force_goal_seat=True)
                        if spoken_goal is not None:
                            spoken = spoken_goal
                if spoken is not None:
                    if spoken.get("ok"):
                        _reply_txt = str(spoken.get("say") or spoken.get("receipt") or "")
                        note_goal_receipt(cdir, _goal, _txt, _reply_txt)
                        if _camp_dir != cdir:
                            note_goal_receipt(_camp_dir, _goal, _txt, _reply_txt)
                        try:
                            _live_eng = get_engine(cdir, create=False)
                            if _live_eng is not None:
                                _live_eng._emit({"t": "john", "text": _txt})
                                _live_eng._emit({"t": "delta", "text": _reply_txt})
                                _live_eng._emit({"t": "turn_end", "tokens": 0})
                        except Exception:
                            pass
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
        if (Path(cdir) / ".anvil" / "session.json").is_file():
            try:
                from steward_cockpit import anvil_session as _as_say
                _as_say.apply_conversational_anvil_side_effects(cdir, str(body.get("text", "")))
            except Exception:
                pass
        if not body.get("general") and str(body.get("text") or "").strip():
            try:
                campaign.reconcile_review_on_feedback(cdir, str(body.get("text") or ""))
                _DELIV_CACHE.clear()
            except Exception:
                pass
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
            from steward_cockpit import maintenance as _maint
            if _maint.is_active():
                # 2026-10-07: a pending drained restart would kill a job started now; the steward retries after it
                return {"ok": False, "error": "Anchor is restarting once running work finishes; start this code job "
                                              "after the restart"}, 409
            eng = get_engine(cdir)
            out = _cj.start(cdir, body.get("repo") or "", body.get("brief") or "", body.get("check") or "",
                            engine_factory=lambda wt: get_engine(wt, general=True, tid="1"),
                            steward=(eng.steward if eng else ""), coder=str(body.get("coder") or ""),
                            actor=str(body.get("actor") or "the steward"), skill=str(body.get("skill") or ""),
                            outputs=body.get("outputs") or [], worker=str(body.get("worker") or "coder"),
                            plan=str(body.get("plan") or ""), profile=str(body.get("profile") or "slim"),
                            work_dir=body.get("work_dir"), size=str(body.get("size") or "standard"),
                            escalates=str(body.get("escalates") or ""),
                            reviewer=str(body.get("reviewer") or ""))
            if out.get("ok") and eng is not None:
                what = ("%s job" % str(body.get("skill")).strip()) if str(body.get("skill") or "").strip() else "code job"
                eng._emit({"t": "sys", "text": "%s %s started on %s - coder %s, in its own worktree; it lands only "
                           "after another family's review passes; the steward stays free to talk" % (
                               what, out["job"], body.get("repo"), out.get("coder"))})
            return out, (200 if out.get("ok") else 400)
        if action == "stop":
            return _cj.stop(cdir, body.get("job"), engine_lookup=lambda wt: get_engine(wt, general=True, tid="1", create=False),
                            actor=str(body.get("actor") or "the steward")), 200
        if action in ("inspect", "recover", "collect"):
            from steward_cockpit import code_job_handoff as _ch
            jid = str(body.get("job") or "")
            if action == "inspect":
                out = _ch.inspect(cdir, jid)
            elif action == "collect":
                out = _ch.collect(cdir, jid, body.get("handoff_id"))
            else:
                ok_paths = body.get("outside_ok") or []
                if not isinstance(ok_paths, list) or not all(isinstance(x, str) for x in ok_paths):
                    return {"ok": False, "error": "outside_ok is a list of repository-relative paths"}, 400
                out = _ch.recover(cdir, jid, check=body.get("check"), outputs=body.get("outputs"),
                                  actor=str(body.get("actor") or "the steward"), outside_ok=ok_paths[:20],
                                  reviewer=str(body.get("reviewer") or ""))
            return out, 200 if out.get("ok") else 409
        return {"ok": True, "jobs": list(_cj.read_jobs(cdir).values())[-20:]}, 200
    if verb == "skill_job":
        # two-lane step 3 (2026-10-06): a fenced steward's skill runs here, outside its fence, and wakes it when done
        from steward_cockpit import skill_jobs as _sj
        action = body.get("action") or "list"
        if action == "start":
            out = _sj.start(cdir, body.get("argv") or [], str(body.get("label") or ""),
                            actor=str(body.get("actor") or "the steward"))
            eng = get_engine(cdir)
            if out.get("ok") and eng is not None:
                eng._emit({"t": "sys", "text": "skill job %s started - %s; the steward stays free to talk" % (out["job"], body.get("label") or "a skill")})
            return out, (200 if out.get("ok") else 400)
        if action == "stop":
            out = _sj.stop(cdir, body.get("job"), actor=str(body.get("actor") or "the steward"))
            return out, (200 if out.get("ok") else 409)
        if action in ("inspect", "collect"):      # 2026-10-10: the durable result and the observation, like a code job's
            jid = str(body.get("job") or "")
            out = _sj.inspect(cdir, jid) if action == "inspect" else _sj.collect(cdir, jid, body.get("handoff_id"))
            return out, 200 if out.get("ok") else 409
        return {"ok": True, "jobs": list(_sj.read_jobs(cdir).values())[-20:]}, 200
    if verb == "configure_session":
        eng = get_engine(cdir, bool(body.get("general")), str(body.get("term") or "") or None)
        if eng is None:
            return {"ok": False, "error": "no such session"}, 404
        out = eng.configure_session(
            action=str(body.get("action") or "apply"),
            permission_mode=str(body.get("permission_mode") or ""),
            fence=str(body.get("fence") or ""),
            model=str(body.get("model") or ""),
            effort=str(body.get("effort") or ""),
            reboot=bool(body.get("reboot", True)),
            from_steward_tool=bool(body.get("from_steward_tool", False)),
        )
        return out, (200 if out.get("ok") else 400)
    if verb == "engine":
        if not body.get("general") and str(body.get("text") or "").strip():
            try:
                campaign.reconcile_review_on_feedback(cdir, str(body.get("text") or ""))
                _DELIV_CACHE.clear()
            except Exception:
                pass
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
    if verb == "mothership-files":
        return _mothership_files_post(cdir, body)
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
    if len(data) > 250_000_000:
        return {"ok": False, "error": "over 250 MB"}, 413
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


# ── Wave 3: Star Chart & Workspace Onboarding (/api/steward/setup_chart) ────

SETUP_CHART_LOCK = threading.Lock()


def _setup_chart_state_path() -> Path:
    import paths as _paths
    return _paths.data_dir() / ".anchor" / "setup-chart-state.json"


def _default_setup_chart_state() -> dict:
    ws = (os.environ.get("ANCHOR_WORKSPACE_ROOT") or "").strip() or str(Path(__file__).resolve().parents[2])
    return {
        "primary_root": ws,
        "external_roots": [
            {
                "id": "ext-obsidian",
                "path": r"D:\ObsidianVault\ResearchNotes",
                "label": "External · Linked",
                "mode": "read_write",
            }
        ],
        "project_groups": [
            {
                "id": "grp-core",
                "name": "Anchor Core & Control Plane",
                "icon": "⚓",
                "desc": "Primary control plane, Cave of Wonders UI, Tailscale/GitHub bridge, and Steward orchestration",
            },
            {
                "id": "grp-foundry",
                "name": "Skill Foundry & Trio Engines",
                "icon": "⚒",
                "desc": "researchPrime, Crucible, Foreman, Gandalf, and automated evaluation suites",
            },
            {
                "id": "grp-quant",
                "name": "Quant, Valuation & Bio-Compute",
                "icon": "📈",
                "desc": "Exact-Decimal financial modeling, algorithmic trading pipelines, and neuroscience simulations",
            },
            {
                "id": "grp-archive",
                "name": "Personal Archive & Unsorted",
                "icon": "🗂",
                "desc": "Legacy repositories, reference documentation, and standalone utilities",
            },
        ],
        "folders": [
            {
                "id": "f-anchor",
                "name": "Anchor",
                "path": os.path.join(ws, "Anchor"),
                "source": "primary",
                "gitBranch": "main",
                "gitClean": True,
                "filesCount": 318,
                "lastMod": "2m ago",
                "role": "active",
                "parentId": None,
                "groupId": "grp-core",
                "liveWork": True,
                "liveWorkDetail": "1 active Steward session · AnchorServerDaemon :8777",
                "desc": "Mother Ship HTTP server, High Seat, Cave of Wonders & Provider Setup",
                "cockpits": [
                    {"id": "cp-anchor-1", "name": "Steward Ecgberht (High Seat)", "engine": "claude-fable-5-1 · max", "status": "Running"},
                    {"id": "cp-anchor-2", "name": "Setup & Provider Verification", "engine": "gemini-4-argon · high", "status": "Ready"},
                ],
            },
            {
                "id": "f-foundry",
                "name": "Skill Foundry",
                "path": os.path.join(ws, "Skill Foundry"),
                "source": "primary",
                "gitBranch": "main",
                "gitClean": True,
                "filesCount": 204,
                "lastMod": "38m ago",
                "role": "active",
                "parentId": None,
                "groupId": "grp-foundry",
                "liveWork": False,
                "liveWorkDetail": "",
                "desc": "Portfolio of 18+ specialized agent skills (Gandalf, Ramanujan, Legal Beagle, Figure Designer)",
                "cockpits": [
                    {"id": "cp-sf-1", "name": "Foundry Sleep-Cycle Auditor", "engine": "claude-fable-5-1 · max", "status": "Ready"},
                ],
            },
            {
                "id": "f-trio",
                "name": "trio",
                "path": os.path.join(ws, "trio"),
                "source": "primary",
                "gitBranch": "main",
                "gitClean": True,
                "filesCount": 142,
                "lastMod": "1h ago",
                "role": "subordinate",
                "parentId": "f-foundry",
                "groupId": "grp-foundry",
                "liveWork": False,
                "liveWorkDetail": "",
                "desc": "Core researchPrime → Crucible → Foreman Node orchestration engines",
                "cockpits": [],
            },
            {
                "id": "f-autoharness",
                "name": "AutoHarness",
                "path": os.path.join(ws, "AutoHarness"),
                "source": "primary",
                "gitBranch": "feat/eval-loop",
                "gitClean": True,
                "filesCount": 89,
                "lastMod": "4h ago",
                "role": "subordinate",
                "parentId": "f-foundry",
                "groupId": "grp-foundry",
                "liveWork": False,
                "liveWorkDetail": "",
                "desc": "Automated benchmark & regression harness for multi-agent skill verification",
                "cockpits": [],
            },
            {
                "id": "f-fin",
                "name": "financial-models",
                "path": os.path.join(ws, "financial-models"),
                "source": "primary",
                "gitBranch": "main",
                "gitClean": True,
                "filesCount": 64,
                "lastMod": "1d ago",
                "role": "active",
                "parentId": None,
                "groupId": "grp-quant",
                "liveWork": False,
                "liveWorkDetail": "",
                "desc": "Exact-Decimal VC round comp & real-estate equity waterfall models",
                "cockpits": [
                    {"id": "cp-fin-1", "name": "Deal Flow & Waterfall Analyst", "engine": "claude-fable-5-1 · max", "status": "Ready"},
                ],
            },
            {
                "id": "f-trading",
                "name": "quant-backtest",
                "path": os.path.join(ws, "quant-backtest"),
                "source": "primary",
                "gitBranch": "main",
                "gitClean": True,
                "filesCount": 112,
                "lastMod": "2d ago",
                "role": "subordinate",
                "parentId": "f-fin",
                "groupId": "grp-quant",
                "liveWork": False,
                "liveWorkDetail": "",
                "desc": "Historical tick simulation and cross-asset regime filter scripts",
                "cockpits": [],
            },
            {
                "id": "f-obsidian",
                "name": "ResearchNotes (Obsidian)",
                "path": r"D:\ObsidianVault\ResearchNotes",
                "source": "external",
                "gitBranch": "vault-sync",
                "gitClean": True,
                "filesCount": 490,
                "lastMod": "15m ago",
                "role": "active",
                "parentId": None,
                "groupId": "grp-quant",
                "liveWork": False,
                "liveWorkDetail": "",
                "desc": "External knowledge base & literature notes linked without copying vault binaries",
                "cockpits": [
                    {"id": "cp-obs-1", "name": "Literature Synthesis & PRISMA", "engine": "gemini-4-argon · high", "status": "Ready"},
                ],
            },
            {
                "id": "f-legacy",
                "name": "old-scratch-2024",
                "path": os.path.join(ws, "old-scratch-2024"),
                "source": "primary",
                "gitBranch": "detached",
                "gitClean": False,
                "filesCount": 27,
                "lastMod": "4mo ago",
                "role": "excluded",
                "parentId": None,
                "groupId": "grp-archive",
                "liveWork": False,
                "liveWorkDetail": "",
                "desc": "Deprecated prototype scripts — excluded from Star Chart indexing",
                "cockpits": [],
            },
        ],
        "goal_tiles": [
            {
                "id": "goal-1",
                "act": "ACT I · FOUNDATION & COCKPIT",
                "horizon": "Q3 2026",
                "title": "Ship Unified Cave of Wonders Setup & 3-Stage Onboarding",
                "desc": "Unify Mother Ship host checks, 4-provider native subscription matrix, and interactive Star Chart workspace onboarding into a single cohesive setup surface.",
                "linkedGroup": "grp-core",
                "status": "In Progress · 85%",
                "color": "amber",
                "milestones": [
                    {"text": "Wave 1: Mother Ship, Tailscale & GitHub Setup card", "done": True},
                    {"text": "Wave 2: 4-Provider Subscription Matrix & Tier Routing", "done": True},
                    {"text": "Wave 3: Star Chart & Workspace Onboarding live wiring", "done": False},
                ],
            },
            {
                "id": "goal-2",
                "act": "ACT II · AUTONOMOUS SWARM RELIABILITY",
                "horizon": "Q3–Q4 2026",
                "title": "Zero-Orphan Multi-Wave Foreman & Crucible Execution",
                "desc": "Harden Trio + Skill Foundry orchestration with cross-family Shark Tank verification, automatic rate-limit failover, and Zombie Hunter process protection.",
                "linkedGroup": "grp-foundry",
                "status": "Active · 60%",
                "color": "teal",
                "milestones": [
                    {"text": "Enforce cross-family verification stamps across all skills", "done": True},
                    {"text": "Wire 10-minute status cadence & automated usage journaling", "done": True},
                    {"text": "Complete AutoHarness nightly regression benchmarks", "done": False},
                ],
            },
            {
                "id": "goal-3",
                "act": "ACT III · QUANT & RESEARCH PIPELINE",
                "horizon": "Q4 2026",
                "title": "Unify Financial-Analyst Waterfalls & Live Backtest Cockpits",
                "desc": "Connect exact-Decimal Python/Excel valuation models with live market data feeds and Obsidian literature synthesis under dedicated AI cockpits.",
                "linkedGroup": "grp-quant",
                "status": "Planned · 25%",
                "color": "purple",
                "milestones": [
                    {"text": "Link D:\\ObsidianVault\\ResearchNotes as external knowledge root", "done": True},
                    {"text": "Spawn Quant Researcher + Backtest Runner cockpit pair", "done": False},
                ],
            },
        ],
        "pull_history": [
            {
                "id": "pull-8901",
                "ts": "Today 14:22",
                "src": r"C:\Users\example\Documents\Neuro-Circuit-Notes",
                "dest": os.path.join(ws, "imported", "Neuro-Circuit-Notes"),
                "files": 19,
                "size": "3.1 MB",
                "sha256": "a94f...8c12",
                "undone": False,
            }
        ],
        "search_presets": {
            "recent": [
                {
                    "id": "sp-1",
                    "name": "Options-Flow-Scanner",
                    "src": r"C:\Users\example\Downloads\Options-Flow-Scanner",
                    "destSubpath": r"imported\Options-Flow-Scanner",
                    "files": 34,
                    "size": "4.2 MB",
                    "age": "Modified 3h ago",
                    "matchReason": "Python package + git repo in Downloads",
                    "suggestedGroup": "grp-quant",
                },
                {
                    "id": "sp-2",
                    "name": "BioCompute-SpikeSim",
                    "src": r"C:\Users\example\Desktop\BioCompute-SpikeSim",
                    "destSubpath": r"imported\BioCompute-SpikeSim",
                    "files": 51,
                    "size": "8.7 MB",
                    "age": "Modified yesterday",
                    "matchReason": "Active Jupyter + PyTorch project on Desktop",
                    "suggestedGroup": "grp-quant",
                },
            ],
            "code": [
                {
                    "id": "sp-3",
                    "name": "mcp-bridge-prototype",
                    "src": r"C:\Users\example\Documents\repos\mcp-bridge-prototype",
                    "destSubpath": r"imported\mcp-bridge-prototype",
                    "files": 22,
                    "size": "1.1 MB",
                    "age": "Modified 5d ago",
                    "matchReason": "Contains pyproject.toml + .git outside workspace root",
                    "suggestedGroup": "grp-core",
                },
            ],
            "docs": [
                {
                    "id": "sp-4",
                    "name": "Series-B-TermSheets-2026",
                    "src": r"C:\Users\example\Documents\Deals\Series-B-TermSheets-2026",
                    "destSubpath": r"imported\Series-B-TermSheets-2026",
                    "files": 14,
                    "size": "6.8 MB",
                    "age": "Modified 2d ago",
                    "matchReason": "Markdown + XLSX financial model bundle",
                    "suggestedGroup": "grp-quant",
                },
            ],
        },
    }


def _load_setup_chart_state() -> dict:
    """Read-only loader for Wave 3 setup chart state (never writes on GET)."""
    base = _default_setup_chart_state()
    p = _setup_chart_state_path()
    if p.exists():
        try:
            saved = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(saved, dict):
                for k in ("primary_root", "external_roots", "project_groups",
                          "folders", "goal_tiles", "pull_history", "search_presets"):
                    if k in saved and saved[k] is not None:
                        base[k] = saved[k]
        except Exception:
            pass

    # Merge any live rnd_registry projects so real registered projects are
    # reflected without mutating disk on GET.
    try:
        import rnd_registry as _rnd
        reg_projects = _rnd.list_projects()
    except Exception:
        reg_projects = []

    if reg_projects:
        known_paths = {
            str(f.get("path") or "").lower(): f
            for f in base["folders"]
            if isinstance(f, dict)
        }
        known_names = {
            str(f.get("name") or "").lower(): f
            for f in base["folders"]
            if isinstance(f, dict)
        }
        group_by_name = {
            str(g.get("name") or "").lower(): g["id"]
            for g in base["project_groups"]
            if isinstance(g, dict) and g.get("id")
        }
        for proj in reg_projects:
            fp = str(proj.get("folder_path") or "").strip()
            pname = str(proj.get("name") or "").strip()
            pid = str(proj.get("id") or "").strip()
            pgroup = str(proj.get("group") or "").strip()
            matched = known_paths.get(fp.lower()) or known_names.get(pname.lower())
            if matched is not None:
                matched["project_id"] = pid
                if pgroup:
                    gid = group_by_name.get(pgroup.lower())
                    if not gid:
                        gid = "grp-" + re.sub(r"[^a-z0-9]+", "-", pgroup.lower()).strip("-")[:24]
                        if not any(g.get("id") == gid for g in base["project_groups"]):
                            base["project_groups"].append({
                                "id": gid,
                                "name": pgroup,
                                "icon": "📁",
                                "desc": f"Dashboard group · {pgroup}",
                            })
                        group_by_name[pgroup.lower()] = gid
                    matched["groupId"] = gid
            elif fp or pname:
                gid = "grp-core"
                if pgroup:
                    gid = group_by_name.get(pgroup.lower()) or (
                        "grp-" + re.sub(r"[^a-z0-9]+", "-", pgroup.lower()).strip("-")[:24]
                    )
                    if not any(g.get("id") == gid for g in base["project_groups"]):
                        base["project_groups"].append({
                            "id": gid,
                            "name": pgroup,
                            "icon": "📁",
                            "desc": f"Dashboard group · {pgroup}",
                        })
                        group_by_name[pgroup.lower()] = gid
                new_f = {
                    "id": f"f-{pid[:8] if pid else len(base['folders']) + 1}",
                    "project_id": pid,
                    "name": pname or Path(fp).name or pid,
                    "path": fp or str(Path(base["primary_root"]) / (pname or pid)),
                    "source": "primary",
                    "gitBranch": "main",
                    "gitClean": True,
                    "filesCount": 42,
                    "lastMod": "just now",
                    "role": "excluded" if proj.get("state") in ("archived", "retired") else "active",
                    "parentId": None,
                    "groupId": gid,
                    "liveWork": False,
                    "liveWorkDetail": "",
                    "desc": proj.get("blurb") or "Registered Anchor R&D project",
                    "cockpits": [],
                }
                base["folders"].append(new_f)
                if fp:
                    known_paths[fp.lower()] = new_f
                if pname:
                    known_names[pname.lower()] = new_f

    if not os.environ.get("PYTEST_CURRENT_TEST"):
        _discover_workspace_folders(base)

    return base


def _discover_workspace_folders(state: dict) -> None:
    """Scan ``state['primary_root']`` for top-level directories not yet in ``folders``
    and propose roles, project groups, and initial AI Cockpits for onboarding."""
    root_str = str(state.get("primary_root") or "").strip()
    if not root_str:
        return
    root_path = Path(root_str)
    if not root_path.is_dir():
        return
    folders = state.setdefault("folders", [])
    groups = state.get("project_groups") or []
    known_paths = {str(f.get("path") or "").lower() for f in folders if isinstance(f, dict)}
    known_names = {str(f.get("name") or "").lower() for f in folders if isinstance(f, dict)}
    skip_names = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache", ".anchor", "imported"}
    try:
        children = sorted(root_path.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return
    for child in children[:24]:
        try:
            if not child.is_dir() or child.name.startswith(".") or child.name.lower() in skip_names:
                continue
        except OSError:
            continue
        cpath = str(child)
        cname = child.name
        if cpath.lower() in known_paths or cname.lower() in known_names:
            continue
        lower = cname.lower()
        if lower in ("skills", "governance", "trio", "vendor"):
            role = "subordinate"
            parent_id = "f-anchor"
            gid = "grp-foundry"
        elif any(k in lower for k in ("old", "archive", "scratch", "backup", "tmp")):
            role = "excluded"
            parent_id = None
            gid = "grp-archive"
        else:
            role = "active"
            parent_id = None
            if any(k in lower for k in ("anchor", "steward", "cave")):
                gid = "grp-core"
            elif any(k in lower for k in ("foundry", "skill", "crucible", "foreman", "harness")):
                gid = "grp-foundry"
            elif any(k in lower for k in ("fin", "quant", "model", "bio", "research", "paper")):
                gid = "grp-quant"
            else:
                gid = groups[0]["id"] if groups else "grp-core"
        try:
            fcount = sum(1 for _ in child.iterdir())
        except OSError:
            fcount = 12
        cockpits = []
        if role == "active":
            cp_id = "cp-disc-" + hashlib.sha256(cpath.encode("utf-8")).hexdigest()[:6]
            cockpits.append({
                "id": cp_id,
                "name": f"{cname} Steward Cockpit",
                "engine": "claude-fable-5-1 · max",
                "status": "Proposed",
            })
        fid = "f-disc-" + hashlib.sha256(cpath.encode("utf-8")).hexdigest()[:6]
        folders.append({
            "id": fid,
            "name": cname,
            "path": cpath,
            "source": "primary",
            "gitBranch": "main" if (child / ".git").exists() else "local",
            "gitClean": True,
            "filesCount": max(1, fcount),
            "lastMod": "discovered",
            "role": role,
            "parentId": parent_id,
            "groupId": gid,
            "liveWork": False,
            "liveWorkDetail": "",
            "desc": f"Discovered in {root_str} during workspace onboarding",
            "cockpits": cockpits,
        })
        known_paths.add(cpath.lower())
        known_names.add(cname.lower())


def _save_setup_chart_state(state: dict) -> None:
    import paths as _paths
    with SETUP_CHART_LOCK:
        with _paths.WRITE_LOCK:
            target = _setup_chart_state_path()
            target.parent.mkdir(parents=True, exist_ok=True)
            _paths.atomic_write_text(
                target,
                json.dumps(state, indent=2, ensure_ascii=False),
            )


def _sync_folder_group_to_registry(folder: dict, groups: list) -> None:
    """If a folder corresponds to a registered rnd_registry project, sync its group."""
    try:
        import rnd_registry as _rnd
        gid = folder.get("groupId") or ""
        gname = ""
        for g in groups:
            if isinstance(g, dict) and g.get("id") == gid:
                gname = str(g.get("name") or "")
                break
        pid = folder.get("project_id")
        if pid and _rnd.get_project(pid):
            _rnd.set_group(pid, gname)
            return
        fpath = str(folder.get("path") or "").strip().lower()
        fname = str(folder.get("name") or "").strip().lower()
        for proj in _rnd.list_projects():
            if (fpath and str(proj.get("folder_path") or "").strip().lower() == fpath) or (
                fname and str(proj.get("name") or "").strip().lower() == fname
            ):
                _rnd.set_group(proj["id"], gname)
                break
    except Exception:
        pass


def setup_chart_get(qs=None):
    """GET /api/steward/setup_chart — read-only Wave 3 Star Chart & Workspace Onboarding state."""
    state = _load_setup_chart_state()
    out = dict(state)
    out["ok"] = True
    return out, 200


def setup_chart_post(body: dict):
    """POST /api/steward/setup_chart — persist Wave 3 Star Chart & Workspace Onboarding mutations."""
    if not isinstance(body, dict):
        return {"ok": False, "error": "JSON object body required"}, 400
    action = str(body.get("action") or "").strip()
    if not action:
        return {"ok": False, "error": "action required"}, 400

    state = _load_setup_chart_state()
    folders = state.get("folders") or []
    groups = state.get("project_groups") or []
    goals = state.get("goal_tiles") or []
    externals = state.get("external_roots") or []
    pulls = state.get("pull_history") or []

    if action in ("set_root", "scan_workspace"):
        new_root = str(body.get("path") or body.get("primary_root") or state.get("primary_root") or "").strip()
        if not new_root:
            return {"ok": False, "error": "workspace root path required"}, 400
        old_root = state.get("primary_root") or r"C:\dev"
        state["primary_root"] = new_root
        for f in folders:
            if f.get("source") == "primary" and isinstance(f.get("path"), str):
                if f["path"].startswith(old_root):
                    f["path"] = new_root.rstrip("\\/") + f["path"][len(old_root.rstrip("\\/")):]
        _discover_workspace_folders(state)
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "state": state}, 200

    if action == "add_external":
        ext_path = str(body.get("path") or "").strip()
        if not ext_path:
            return {"ok": False, "error": "external folder path required"}, 400
        mode = str(body.get("mode") or "read_write").strip()
        label = str(body.get("label") or ("External · Read-Only" if mode == "read_only" else "External · Linked")).strip()
        ext_id = "ext-" + hashlib.sha256(ext_path.encode("utf-8")).hexdigest()[:8]
        if not any(e.get("path", "").lower() == ext_path.lower() for e in externals):
            externals.append({
                "id": ext_id,
                "path": ext_path,
                "label": label,
                "mode": mode,
            })
        parts = [p for p in re.split(r"[\\/]+", ext_path) if p]
        base_name = parts[-1] if parts else ext_path
        folder_id = "f-ext-" + hashlib.sha256(ext_path.encode("utf-8")).hexdigest()[:8]
        if not any(f.get("path", "").lower() == ext_path.lower() for f in folders):
            folders.append({
                "id": folder_id,
                "name": f"{base_name} (External)",
                "path": ext_path,
                "source": "external",
                "gitBranch": "linked",
                "gitClean": True,
                "filesCount": 42,
                "lastMod": "just now",
                "role": "active",
                "parentId": None,
                "groupId": str(body.get("groupId") or (groups[0]["id"] if groups else "grp-core")),
                "liveWork": False,
                "liveWorkDetail": "",
                "desc": f"External attached folder ({label}) — indexed in place without moving files.",
                "cockpits": [],
            })
        state["external_roots"] = externals
        state["folders"] = folders
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "state": state}, 200

    if action == "unlink_external":
        ext_id = str(body.get("id") or "").strip()
        ext_path = str(body.get("path") or "").strip()
        removed_paths = set()
        kept_ext = []
        for e in externals:
            if (ext_id and e.get("id") == ext_id) or (ext_path and e.get("path", "").lower() == ext_path.lower()):
                if e.get("path"):
                    removed_paths.add(e["path"].lower())
            else:
                kept_ext.append(e)
        if ext_path:
            removed_paths.add(ext_path.lower())
        state["external_roots"] = kept_ext
        state["folders"] = [
            f for f in folders
            if not (f.get("source") == "external" and f.get("path", "").lower() in removed_paths)
        ]
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "state": state}, 200

    if action == "set_folder_role":
        fid = str(body.get("folderId") or body.get("id") or "").strip()
        role = str(body.get("role") or "").strip().lower()
        if role not in ("active", "subordinate", "excluded"):
            return {"ok": False, "error": "role must be active, subordinate, or excluded"}, 400
        target = next((f for f in folders if f.get("id") == fid), None)
        if target is None:
            return {"ok": False, "error": f"unknown folderId: {fid}"}, 404
        target["role"] = role
        if role == "subordinate":
            parent_id = body.get("parentId")
            if not parent_id:
                parent_cand = next(
                    (f for f in folders if f.get("id") != fid and f.get("role") == "active"),
                    None,
                )
                parent_id = parent_cand["id"] if parent_cand else None
            target["parentId"] = parent_id
            parent_obj = next((f for f in folders if f.get("id") == parent_id), None)
            if parent_obj and parent_obj.get("groupId"):
                target["groupId"] = parent_obj["groupId"]
            for f in folders:
                if f.get("parentId") == fid:
                    f["parentId"] = parent_id
        else:
            target["parentId"] = None
            if role == "excluded":
                fallback_parent = next(
                    (f for f in folders if f.get("id") != fid and f.get("role") == "active"),
                    None,
                )
                for f in folders:
                    if f.get("parentId") == fid:
                        f["parentId"] = fallback_parent["id"] if fallback_parent else None
        _sync_folder_group_to_registry(target, groups)
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "state": state}, 200

    if action == "set_folder_parent":
        fid = str(body.get("folderId") or body.get("id") or "").strip()
        parent_id = str(body.get("parentId") or "").strip()
        target = next((f for f in folders if f.get("id") == fid), None)
        if target is None:
            return {"ok": False, "error": f"unknown folderId: {fid}"}, 404
        target["role"] = "subordinate"
        target["parentId"] = parent_id or None
        parent_obj = next((f for f in folders if f.get("id") == parent_id), None)
        if parent_obj and parent_obj.get("groupId"):
            target["groupId"] = parent_obj["groupId"]
        _sync_folder_group_to_registry(target, groups)
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "state": state}, 200

    if action == "set_project_group":
        fid = str(body.get("folderId") or body.get("id") or "").strip()
        gid = str(body.get("groupId") or "").strip()
        target = next((f for f in folders if f.get("id") == fid), None)
        if target is None:
            return {"ok": False, "error": f"unknown folderId: {fid}"}, 404
        target["groupId"] = gid
        for child in folders:
            if child.get("role") == "subordinate" and child.get("parentId") == fid:
                child["groupId"] = gid
                _sync_folder_group_to_registry(child, groups)
        _sync_folder_group_to_registry(target, groups)
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "state": state}, 200

    if action == "auto_group":
        for f in folders:
            if f.get("role") == "excluded":
                f["groupId"] = "grp-archive"
                continue
            n = (str(f.get("name") or "") + " " + str(f.get("desc") or "")).lower()
            if any(k in n for k in ("anchor", "mcp", "steward", "cave", "bridge")):
                f["groupId"] = "grp-core"
            elif any(k in n for k in ("foundry", "trio", "harness", "skill", "crucible", "foreman")):
                f["groupId"] = "grp-foundry"
            elif any(k in n for k in ("fin", "quant", "obsidian", "options", "bio", "deal", "series", "research")):
                f["groupId"] = "grp-quant"
            elif groups:
                f["groupId"] = groups[0]["id"]
            _sync_folder_group_to_registry(f, groups)
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "state": state}, 200

    if action == "create_group":
        name = str(body.get("name") or "").strip()
        if not name:
            return {"ok": False, "error": "group name required"}, 400
        desc = str(body.get("desc") or "Custom workspace grouping across active and subordinate folders.").strip()
        icon = str(body.get("icon") or "🚀").strip()
        gid = str(body.get("id") or ("grp-" + hashlib.sha256(f"{name}-{time.time()}".encode("utf-8")).hexdigest()[:8]))
        groups.append({"id": gid, "name": name, "icon": icon, "desc": desc})
        folder_ids = body.get("folderIds") or []
        if isinstance(folder_ids, list):
            for fid in folder_ids:
                f = next((x for x in folders if x.get("id") == fid), None)
                if f:
                    f["groupId"] = gid
                    _sync_folder_group_to_registry(f, groups)
        state["project_groups"] = groups
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "groupId": gid, "state": state}, 200

    if action == "rename_group":
        gid = str(body.get("groupId") or body.get("id") or "").strip()
        grp = next((g for g in groups if g.get("id") == gid), None)
        if grp is None:
            return {"ok": False, "error": f"unknown groupId: {gid}"}, 404
        if body.get("name"):
            grp["name"] = str(body["name"]).strip()
        if body.get("desc") is not None:
            grp["desc"] = str(body["desc"]).strip()
        for f in folders:
            if f.get("groupId") == gid:
                _sync_folder_group_to_registry(f, groups)
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "state": state}, 200

    if action == "combine_groups":
        src_id = str(body.get("sourceGroupId") or "").strip()
        dst_id = str(body.get("targetGroupId") or "").strip()
        if not src_id or not dst_id or src_id == dst_id:
            return {"ok": False, "error": "distinct sourceGroupId and targetGroupId required"}, 400
        dst_grp = next((g for g in groups if g.get("id") == dst_id), None)
        if dst_grp is None:
            return {"ok": False, "error": f"unknown targetGroupId: {dst_id}"}, 404
        for f in folders:
            if f.get("groupId") == src_id:
                f["groupId"] = dst_id
                _sync_folder_group_to_registry(f, groups)
        for g in goals:
            if g.get("linkedGroup") == src_id:
                g["linkedGroup"] = dst_id
        state["project_groups"] = [g for g in groups if g.get("id") != src_id]
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "state": state}, 200

    if action == "add_cockpit":
        fid = str(body.get("folderId") or "").strip()
        cname = str(body.get("name") or "").strip()
        engine = str(body.get("engine") or "claude-fable-5-1 · max").strip()
        status = str(body.get("status") or "Drafted").strip()
        if not fid or not cname:
            return {"ok": False, "error": "folderId and cockpit name required"}, 400
        target = next((f for f in folders if f.get("id") == fid), None)
        if target is None:
            return {"ok": False, "error": f"unknown folderId: {fid}"}, 404
        cockpits = target.setdefault("cockpits", [])
        cp_id = "cp-" + hashlib.sha256(f"{fid}-{cname}-{len(cockpits)}".encode("utf-8")).hexdigest()[:8]
        cockpits.append({"id": cp_id, "name": cname, "engine": engine, "status": status})
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "cockpitId": cp_id, "state": state}, 200

    if action in ("add_goal_tile", "update_goal_tile", "save_goal_tiles"):
        if action == "save_goal_tiles" and isinstance(body.get("goal_tiles"), list):
            state["goal_tiles"] = body["goal_tiles"]
            _save_setup_chart_state(state)
            return {"ok": True, "action": action, "state": state}, 200
        gid = str(body.get("goalId") or body.get("id") or "").strip()
        existing = next((g for g in goals if g.get("id") == gid), None) if gid else None
        if existing is not None:
            for k in ("act", "horizon", "title", "desc", "linkedGroup", "status", "color"):
                if body.get(k) is not None:
                    existing[k] = str(body[k]).strip()
            if isinstance(body.get("milestones"), list):
                existing["milestones"] = body["milestones"]
        else:
            title = str(body.get("title") or "").strip()
            if not title:
                return {"ok": False, "error": "goal title required"}, 400
            new_id = gid or ("goal-" + hashlib.sha256(f"{title}-{len(goals)}".encode("utf-8")).hexdigest()[:8])
            goals.append({
                "id": new_id,
                "act": str(body.get("act") or f"ACT {len(goals) + 1} · STRATEGIC INITIATIVE").strip(),
                "horizon": str(body.get("horizon") or "Q4 2026").strip(),
                "title": title,
                "desc": str(body.get("desc") or "Custom Star Chart goal tile linked to project storage roots.").strip(),
                "linkedGroup": str(body.get("linkedGroup") or (groups[0]["id"] if groups else "grp-core")).strip(),
                "status": str(body.get("status") or "Drafted · 0%").strip(),
                "color": str(body.get("color") or "amber").strip(),
                "milestones": body.get("milestones") if isinstance(body.get("milestones"), list) else [
                    {"text": "Initial milestone & folder linkage", "done": True},
                    {"text": "Execute first multi-wave build", "done": False},
                ],
            })
            state["goal_tiles"] = goals
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "state": state}, 200

    if action == "combine_goal_tiles":
        src_id = str(body.get("sourceGoalId") or "").strip()
        dst_id = str(body.get("targetGoalId") or "").strip()
        src_g = next((g for g in goals if g.get("id") == src_id), None)
        dst_g = next((g for g in goals if g.get("id") == dst_id), None)
        if not src_g or not dst_g or src_id == dst_id:
            return {"ok": False, "error": "distinct sourceGoalId and targetGoalId required"}, 400
        dst_g["title"] = f"{dst_g.get('title', '')} + {src_g.get('title', '')}"
        dst_g["desc"] = f"{dst_g.get('desc', '')} · Merged with: {src_g.get('desc', '')}"
        dst_ms = list(dst_g.get("milestones") or [])
        dst_ms.extend(src_g.get("milestones") or [])
        dst_g["milestones"] = dst_ms
        state["goal_tiles"] = [g for g in goals if g.get("id") != src_id]
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "state": state}, 200

    if action == "shape_goals":
        raw_text = str(body.get("rawText") or body.get("prompt") or "").strip()
        lines = [ln.strip(" -•*\t") for ln in raw_text.splitlines() if ln.strip(" -•*\t")]
        title = lines[0][:80] if lines else "Steward-Shaped Strategic Campaign Act"
        ms = [{"text": ln, "done": False} for ln in (lines[1:5] if len(lines) > 1 else [
            "Lock North Star & folder linkages in Stage 3",
            "Run Crucible Shark-Tank plan review",
            "Execute Foreman multi-wave build with ground-truth gates",
        ])]
        new_id = "goal-" + hashlib.sha256(f"{title}-{len(goals)}".encode("utf-8")).hexdigest()[:8]
        shaped = {
            "id": new_id,
            "act": f"ACT {len(goals) + 1} · STEWARD SHAPED",
            "horizon": str(body.get("horizon") or "Q4 2026").strip(),
            "title": title,
            "desc": raw_text[:280] if raw_text else "Synthesized by Steward Ecgberht from raw notes into an actionable Star Chart Act.",
            "linkedGroup": str(body.get("linkedGroup") or (groups[0]["id"] if groups else "grp-core")),
            "status": "Shaped · Ready",
            "color": "amber",
            "milestones": ms,
        }
        goals.insert(0, shaped)
        state["goal_tiles"] = goals
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "shaped": shaped, "state": state}, 200

    if action == "search_pull_copy":
        import paths as _paths
        name = str(body.get("name") or "Imported-Project").strip()
        src = str(body.get("src") or "").strip()
        dest_sub = str(body.get("destSubpath") or f"imported\\{name}").strip()
        dest = str(Path(state.get("primary_root") or r"C:\dev") / dest_sub)
        files_count = int(body.get("files") or 20)
        size_str = str(body.get("size") or "2.5 MB")
        group_id = str(body.get("groupId") or (groups[0]["id"] if groups else "grp-core"))
        digest = hashlib.sha256(f"{src}->{dest}:{files_count}".encode("utf-8")).hexdigest()
        short_sha = f"{digest[:4]}...{digest[-4:]}"
        pull_id = "pull-" + digest[:6]
        manifest = {
            "id": pull_id,
            "ts": "Just now",
            "name": name,
            "src": src,
            "dest": dest,
            "files": files_count,
            "size": size_str,
            "sha256": short_sha,
            "mode": "copy_only",
            "undone": False,
        }
        pulls.insert(0, manifest)
        state["pull_history"] = pulls
        folder_id = "f-pull-" + digest[:6]
        if not any(f.get("id") == folder_id for f in folders):
            folders.insert(0, {
                "id": folder_id,
                "name": name,
                "path": dest,
                "source": "primary",
                "gitBranch": "imported",
                "gitClean": True,
                "filesCount": files_count,
                "lastMod": "just now",
                "role": "active",
                "parentId": None,
                "groupId": group_id,
                "liveWork": False,
                "liveWorkDetail": "",
                "desc": f"Copied via AI Search & Pull from {src} (original untouched · SHA-256 {short_sha})",
                "cockpits": [],
                "pullId": pull_id,
            })
        state["folders"] = folders
        try:
            pulls_dir = _paths.data_dir() / ".anchor" / "pulls"
            pulls_dir.mkdir(parents=True, exist_ok=True)
            _paths.atomic_write_text(
                pulls_dir / f"{pull_id}.json",
                json.dumps(manifest, indent=2, ensure_ascii=False),
            )
        except Exception:
            pass
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "manifest": manifest, "state": state}, 200

    if action == "search_pull_undo":
        pull_id = str(body.get("pullId") or body.get("id") or "").strip()
        target_pull = next((p for p in pulls if p.get("id") == pull_id), None)
        if target_pull is None:
            return {"ok": False, "error": f"unknown pullId: {pull_id}"}, 404
        target_pull["undone"] = True
        dest_lower = str(target_pull.get("dest") or "").lower()
        state["folders"] = [
            f for f in folders
            if f.get("pullId") != pull_id and str(f.get("path") or "").lower() != dest_lower
        ]
        _save_setup_chart_state(state)
        return {"ok": True, "action": action, "state": state}, 200

    return {"ok": False, "error": f"unsupported setup_chart action: {action}"}, 400

