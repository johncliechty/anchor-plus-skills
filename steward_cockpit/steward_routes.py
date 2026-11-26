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

_HOT_MOD_MTIMES = globals().get("_HOT_MOD_MTIMES") if isinstance(globals().get("_HOT_MOD_MTIMES"), dict) else {}
for _hot_mod in ("paths", "office_preview", "anchor_settings", "model_policy", "provider_setup", "gwl_admin_gui", "onboard_wizard", "usage_allowance_monitor", "usage_nightly_sync", "deliverables_register", "steward_cockpit.steward_core", "tools.steward_plan", "steward_cockpit.wave_map_model", "steward_cockpit.deliverable_shelves", "steward_cockpit.spellcheck_engine", "steward_cockpit.dictation_engine", "steward_cockpit.steward_campaign", "steward_cockpit.campaign_acts", "steward_cockpit.campaign_say", "steward_cockpit.anvil_session", "steward_cockpit.anvil_scoping_v6", "steward_cockpit.anvil_py_deps", "steward_cockpit.anvil_replication_job", "steward_cockpit.anvil_verification_guard", "steward_cockpit.anvil_comprehension_engine", "steward_cockpit.anvil_literature_job", "high_seat_page", "report_viewer", "scribe_engine", "comms_connector"):
    if _hot_mod in sys.modules:
        try:
            _m_obj = sys.modules[_hot_mod]
            _m_file = getattr(_m_obj, "__file__", None)
            _m_mt = os.stat(_m_file).st_mtime_ns if _m_file else None
            if _m_mt is not None and _HOT_MOD_MTIMES.get(_hot_mod) != _m_mt and not (os.environ.get("PYTEST_CURRENT_TEST") and _hot_mod in ("model_policy", "provider_setup", "steward_cockpit.dictation_engine", "comms_connector")):
                importlib.reload(_m_obj)
                _HOT_MOD_MTIMES[_hot_mod] = _m_mt
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

_ROUTE_TLS = globals().get("_ROUTE_TLS") or threading.local()

for _main_mod_name in ("__main__", "anchor_gui"):
    _m = sys.modules.get(_main_mod_name)
    if _m is not None and "provider_setup" in sys.modules and isinstance(getattr(_m, "_MIGRATED_HANDLERS", None), dict):
        _ps_live = sys.modules["provider_setup"]
        _m._MIGRATED_HANDLERS["handle_provider_setup_page"] = _ps_live.handle_page
        _m._MIGRATED_HANDLERS["handle_provider_setup_get"] = _ps_live.handle_get
        _m._MIGRATED_HANDLERS["handle_provider_setup_post"] = _ps_live.handle_post
    _ah = getattr(_m, "AnchorHandler", None) if _m else None
    if _ah is not None and hasattr(_ah, "_steward_pid_dir"):
        _orig_spd = getattr(_ah, "_orig_steward_pid_dir", _ah._steward_pid_dir)
        _ah._orig_steward_pid_dir = _orig_spd
        def _patched_steward_pid_dir(self, pid, _orig=_orig_spd):
            import urllib.parse as _up
            _ROUTE_TLS.pending_cd = None
            _ROUTE_TLS.req_query = _up.urlparse(str(getattr(self, "path", "") or "")).query
            res = _orig(self, pid)
            if res is None:
                res = _resolve_named_cockpit_dir(pid)
            return res
        _ah._steward_pid_dir = _patched_steward_pid_dir
    if _ah is not None and hasattr(_ah, "send_header"):
        _orig_sh = getattr(_ah, "_orig_steward_send_header", _ah.send_header)
        _ah._orig_steward_send_header = _orig_sh
        def _patched_send_header(self, keyword, value, _orig=_orig_sh):
            if str(keyword or "").lower() == "content-disposition":
                cd_override = getattr(_ROUTE_TLS, "pending_cd", None)
                if cd_override:
                    _ROUTE_TLS.pending_cd = None
                    value = cd_override
            return _orig(self, keyword, value)
        _ah.send_header = _patched_send_header
    if _ah is not None and hasattr(_ah, "_send_json"):
        _orig_sj = getattr(_ah, "_orig_steward_send_json", _ah._send_json)
        _ah._orig_steward_send_json = _orig_sj
        def _patched_send_json(self, data, code=200, _orig=_orig_sj):
            _ROUTE_TLS.req_query = ""
            _ROUTE_TLS.pending_cd = None
            if code == 404 and isinstance(data, dict) and "failure_state" not in data:
                _req_path = str(getattr(self, "path", "") or "").split("?", 1)[0]
                if _req_path in ("/api/steward/plan", "/api/plan"):
                    data = {
                        "ok": False,
                        "failure_state": "dependency-missing",
                        "error": "Campaign directory not found",
                        "message": "Campaign directory not found",
                    }
            return _orig(self, data, code)
        _ah._send_json = _patched_send_json
    if _m is not None:
        try:
            _m._BOOT_RELEASE_VERSION = "1.4.3"
        except Exception:
            pass

import paths
from steward_cockpit import steward_campaign as campaign
from steward_cockpit.steward_engine import Engine

HERE = Path(__file__).parent
STATIC = HERE / "static"

OPENABLE_EXT = {".md", ".txt", ".pdf", ".docx", ".doc", ".xlsx", ".xls",
                ".csv", ".pptx", ".ppt", ".png", ".jpg", ".jpeg", ".gif", ".json",
                ".r", ".rmd", ".qmd", ".rds", ".rdata", ".py", ".ipynb", ".jl",
                ".m", ".sql", ".stan", ".tex", ".bib", ".toml", ".yaml", ".yml",
                ".html", ".htm", ".svg", ".xml", ".log", ".zip"}
# Only block actual OS binary executables / shell linkers; source code & data-science scripts
# (.r, .rmd, .py, .ipynb, .jl, .sql, .sh, .ps1, .js, .ts, .html, .svg) are allowed in AI Cockpits.
DENY_UPLOAD_EXT = {".exe", ".com", ".scr", ".hta", ".jse", ".vbs", ".vbe",
                   ".wsf", ".wsh", ".lnk", ".url", ".msi", ".reg", ".dll", ".jar",
                   ".pif", ".application", ".gadget", ".cpl",
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
        in_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
        now_m = time.monotonic()
        hit_fast = _DELIV_CACHE.get(key)
        if not in_pytest and hit_fast and (now_m - hit_fast[1]) < 4.0 and hit_fast[0][0] == _deliv_stamp(cdir):
            return dict(hit_fast[2])
        stamp = (_deliv_stamp(cdir), _private_stamp())
        hit = _DELIV_CACHE.get(key)
        if (hit and stamp[1] is not None and hit[0] == stamp and now_m - hit[1] < _DELIV_TTL
                and _identity(cdir, [e[0] for e in hit[3]]) == hit[3]):
            return copy.deepcopy(hit[2]) if in_pytest else dict(hit[2])
        began = time.monotonic()
        data = read()
        before = _identity(cdir, _offered_paths(data))
        annotate(data)                                # the links are checked here, between the two snapshots
        after = _identity(cdir, _offered_paths(data))
        if isinstance(data, dict) and data.get("failure_state") == "backing-store-unreadable":
            return data
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
    "Superjump": "superjump-icon.jpg", "superjump": "superjump-icon.jpg",
    "Anvil": "anvil-icon.jpg", "anvil": "anvil-icon.jpg",
    "Aegis": "aegis-icon.jpg", "aegis": "aegis-icon.jpg",
    "Einstein": "einstein-icon.png", "einstein": "einstein-icon.png",
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
    if name == "anvil.html":
        html_txt = f.read_text(encoding="utf-8")
        def _stamp_static_html(m):
            attr_and_url = m.group(1)
            asset_rel = m.group(2)
            ver = _static_asset_version(asset_rel)
            return f'{attr_and_url}?v={ver}"'
        html_txt = re.sub(
            r'((?:href|src)="(?:/steward-static/|/static/)([^"?]+\.(?:js|css)))(?:\?v=[^"]*)?"',
            _stamp_static_html,
            html_txt,
        )
        return html_txt.encode("utf-8"), ctype
    return f.read_bytes(), ctype


_CLIENT_SHIM = """<script src="/static/app-frame.js"></script><script>
window.STEWARD_PID = %s;
window.STEWARD_BUILD = %s;
window.STEWARD_MODE = %s;
(function(){
  // token: prefer one arriving in the URL (the beta-link / bounce), else the
  // stored one; persist a URL token so later fetches stay authed
  var TOK="";
  var _PAGE_PID=window.STEWARD_PID||'';
  var _PAGE_DIR=window.STEWARD_EFFORT_DIR||'';
  try{
    var _sp0=new URLSearchParams(location.search);
    TOK=_sp0.get('token')||'';
    if(!_PAGE_PID)_PAGE_PID=_sp0.get('pid')||_sp0.get('project')||'';
    if(!_PAGE_DIR)_PAGE_DIR=_sp0.get('dir')||_sp0.get('effort')||'';
  }catch(_){}
  try{if(TOK){localStorage.setItem('anchor_token',TOK);}else{TOK=localStorage.getItem('anchor_token')||'';}}catch(_){}
  window.STEWARD_TOKEN=TOK;
  window.STEWARD_EFFORT_DIR=_PAGE_DIR;
  window.STEWARD_FULL_COCKPIT_URL='/steward/v1?pid='+encodeURIComponent(_PAGE_PID)+'&dir='+encodeURIComponent(_PAGE_DIR)+(TOK?'&token='+encodeURIComponent(TOK):'');
  function auth(o){o=o||{};if(TOK){o.headers=Object.assign({},o.headers||{},{'Authorization':'Bearer '+TOK});}return o;}
  var _f=window.fetch;window.fetch=function(u,o){
    if(typeof u==='string'){
      if(u.indexOf('/api/rnd/')===0 || u.indexOf('/api/version')===0){o=auth(o);}
      else if(u.indexOf('/api/steward/')===0){
        if(u.indexOf('pid=')<0 && window.STEWARD_PID){
          u+=(u.indexOf('?')<0?'?':'&')+'pid='+encodeURIComponent(window.STEWARD_PID);
        }
        if(u.indexOf('dir=')<0 && _PAGE_DIR && u.indexOf('/api/steward/plan')===0){
          u+=(u.indexOf('?')<0?'?':'&')+'dir='+encodeURIComponent(_PAGE_DIR);
        }
        o=auth(o);
      }
      else if(u.indexOf('/api/')===0){u='/api/steward/'+u.slice(5);
        u+=(u.indexOf('?')<0?'?':'&')+'pid='+encodeURIComponent(window.STEWARD_PID);
        if(u.indexOf('dir=')<0 && _PAGE_DIR && u.indexOf('/api/steward/plan')===0){
          u+='&dir='+encodeURIComponent(_PAGE_DIR);
        }
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
  var _bootId='';
  function _checkVersion(){
    try{var hw=window;for(var hk=0;hk<6;hk++){if(hw.__anchorHidden)return;if(hw===hw.parent)break;hw=hw.parent;}}catch(_){}
    _f('/api/version', {cache:'no-store'}).then(function(r){return r.json();})
      .then(function(j){
        if (j && j.boot) {
          if (!_bootId) _bootId = String(j.boot);
          else if (String(j.boot) === _bootId) { if (j.version) window.STEWARD_BUILD = String(j.version); return; }
        }
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
    _f('/api/version', {cache:'no-store'}).then(function(r){return r.json();}).then(function(j){if(j&&j.boot)_bootId=String(j.boot);}).catch(function(){});
    setInterval(_checkVersion, 30000);
    window.addEventListener('anchor-app-visibility', function(ev){
      if (ev && ev.detail && !ev.detail.hidden) setTimeout(_checkVersion, 150);
    });
  }
})();
</script>"""


def full_cockpit_url(pid="", effort_dir="", token=""):
    """Build the direct full-cockpit URL (/steward/v1) preserving exact pid + dir per AGENTS.md."""
    import urllib.parse as _up
    q_pid = _up.quote(str(pid or ""), safe="")
    q_dir = _up.quote(str(effort_dir or ""), safe="")
    url = f"/steward/v1?pid={q_pid}&dir={q_dir}"
    if token:
        url += "&token=" + _up.quote(str(token), safe="")
    return url


def serve_cockpit_doc(pid="", effort_dir="", embed=False, view=""):
    return serve_page_doc("cockpit", pid, effort_dir=effort_dir, embed=embed, view=view)


def serve_report_doc(pid, path):
    return serve_page_doc("report", pid)


# the cockpit opens the effort conversation (v1) and workbench terminal (v3)
# as iframes; Anchor serves them under /steward/<page> with the shim injected
_PAGES = {"v1": "v1.html", "v3": "v3.html", "report": "report.html",
          "cockpit": "cockpit.html"}


def _load_aegis_session_module():
    """Load (and hot-reload if changed on disk) ``steward_cockpit.aegis_session``."""
    import importlib as _il
    from steward_cockpit import aegis_session as _aeg
    if _aeg is None:
        raise ImportError("Security scanner module unavailable")
    try:
        _aeg_file = getattr(_aeg, "__file__", None)
        if _aeg_file:
            _aeg_mtime = Path(_aeg_file).stat().st_mtime_ns
            _prev_mtime = getattr(_aeg, "_LOADED_MTIME_NS", None)
            if _prev_mtime is None:
                _aeg._LOADED_MTIME_NS = _aeg_mtime
            elif _prev_mtime != _aeg_mtime:
                _aeg = _il.reload(_aeg)
                _aeg._LOADED_MTIME_NS = _aeg_mtime
    except Exception:
        pass
    return _aeg


def _verify_aegis_scanner_available(_aeg, *, verify_exec: bool = True):
    """Ensure the Aegis scanner engine module is available; raise ImportError otherwise."""
    if _aeg is None:
        raise ImportError("Security scanner module unavailable")
    if "load_aegis_engine_module" in vars(_aeg):
        loader = getattr(_aeg, "load_aegis_engine_module", None)
        if loader is None or not callable(loader):
            raise ImportError("Security scanner module unavailable")
        eng = loader()
        if eng is None:
            raise ImportError("Security scanner module unavailable")
        return eng
    loader = getattr(_aeg, "_load_aegis_engine", None)
    if loader is None or not callable(loader):
        raise ImportError("Security scanner module unavailable")
    if verify_exec:
        try:
            eng = loader()
        except (TimeoutError,):
            raise
        except (ImportError, ModuleNotFoundError, FileNotFoundError, OSError, RuntimeError) as exc:
            raise ImportError("Security scanner module unavailable") from exc
        if eng is None:
            raise ImportError("Security scanner module unavailable")
        return eng
    return None


def _run_aegis_route_contract(cdir, params, run_fn, *, verify_scanner_exec: bool = True):
    """Execute an Aegis cockpit route action under Wave 6's 5-state failure contract (unknown != empty)."""
    import socket as _socket
    import urllib.error as _urlerr
    import urllib.parse as _urlparse
    from provider_native import private_account_path

    if not isinstance(params, dict):
        return {
            "ok": False,
            "failure_state": "dependency-returns-garbage",
            "error": "Blocked unsafe path traversal or disallowed URL scheme",
            "message": "Blocked unsafe path traversal or disallowed URL scheme",
        }, 400

    try:
        raw_url = str(params.get("url") or "").strip()
        if raw_url:
            parsed_u = _urlparse.urlparse(raw_url)
            if parsed_u.scheme.lower() not in ("http", "https") or not parsed_u.netloc:
                raise paths.DisallowedUrlSchemeError("Blocked unsafe path traversal or disallowed URL scheme")
            req_timeout = float(params.get("timeout", 15.0))
            with paths.safe_urlopen(raw_url, timeout=req_timeout) as _u_resp:
                _u_resp.read(4096)

        target_spec = str(params.get("target") or ".").strip()
        cdir_str = str(cdir or "").strip()
        if not cdir_str:
            raise FileNotFoundError("Target file unreadable (unknown)")
        cdir_path = Path(cdir_str)
        if target_spec not in ("", "."):
            # Check unsafe path syntax/containment BEFORE verifying backing store existence when possible,
            # while still letting missing contained files raise FileNotFoundError -> 500.
            resolved_target = paths.resolve_contained_path(
                cdir_path if cdir_path.exists() else Path(os.path.abspath(cdir_str)),
                target_spec,
                allow_missing=True,
            )
            if private_account_path(str(resolved_target)):
                raise paths.UnsafePathError("Blocked unsafe path traversal or disallowed URL scheme")

        _aeg = _load_aegis_session_module()
        _verify_aegis_scanner_available(_aeg, verify_exec=verify_scanner_exec)

        if not cdir_path.exists() or not cdir_path.is_dir():
            raise FileNotFoundError("Target file unreadable (unknown)")
        os.listdir(cdir_path)

        if target_spec not in ("", "."):
            resolved_target = paths.resolve_contained_path(cdir_path, target_spec, allow_missing=False)
            if private_account_path(str(resolved_target)):
                raise paths.UnsafePathError("Blocked unsafe path traversal or disallowed URL scheme")
            if resolved_target.is_file():
                resolved_target.read_text(encoding="utf-8")
            elif resolved_target.is_dir():
                os.listdir(resolved_target)

        sess_file = cdir_path / ".aegis" / "session.json"
        if sess_file.exists():
            sess_raw = sess_file.read_text(encoding="utf-8")
            sess_parsed = json.loads(sess_raw)
            if not isinstance(sess_parsed, dict):
                raise OSError("Target file unreadable (unknown)")

        res = run_fn(_aeg)
    except (ImportError, ModuleNotFoundError):
        return {
            "ok": False,
            "failure_state": "dependency-missing",
            "error": "Security scanner module unavailable",
            "message": "Security scanner module unavailable",
        }, 503
    except (TimeoutError, _socket.timeout):
        return {
            "ok": False,
            "failure_state": "dependency-slow-or-killed",
            "error": "Upstream URL fetch exceeded 15s timeout",
            "message": "Upstream URL fetch exceeded 15s timeout",
        }, 504
    except _urlerr.URLError as exc:
        if isinstance(getattr(exc, "reason", None), (TimeoutError, _socket.timeout)):
            return {
                "ok": False,
                "failure_state": "dependency-slow-or-killed",
                "error": "Upstream URL fetch exceeded 15s timeout",
                "message": "Upstream URL fetch exceeded 15s timeout",
            }, 504
        return {
            "ok": False,
            "failure_state": "backing-store-unreadable",
            "error": "Target file unreadable (unknown)",
            "message": "Target file unreadable (unknown)",
        }, 500
    except (paths.UnsafePathError, paths.DisallowedUrlSchemeError):
        return {
            "ok": False,
            "failure_state": "dependency-returns-garbage",
            "error": "Blocked unsafe path traversal or disallowed URL scheme",
            "message": "Blocked unsafe path traversal or disallowed URL scheme",
        }, 403
    except (FileNotFoundError, PermissionError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {
            "ok": False,
            "failure_state": "backing-store-unreadable",
            "error": "Target file unreadable (unknown)",
            "message": "Target file unreadable (unknown)",
        }, 500
    except ValueError:
        return {
            "ok": False,
            "failure_state": "dependency-returns-garbage",
            "error": "Blocked unsafe path traversal or disallowed URL scheme",
            "message": "Blocked unsafe path traversal or disallowed URL scheme",
        }, 400

    if isinstance(res, dict):
        sc = (res.get("session") or {}).get("scan") or res.get("scan") or {}
        if isinstance(sc, dict):
            sev = sc.get("severity_counts") or {}
            crit_cnt = int(sev.get("CRITICAL", sc.get("critical_count", 0)) or 0)
            high_cnt = int(sev.get("HIGH", sc.get("high_count", 0)) or 0)
            res.setdefault("critical_count", crit_cnt)
            res.setdefault("high_count", high_cnt)
            if crit_cnt + high_cnt == 0:
                res["failure_state"] = "empty-but-valid"
                res["status_message"] = "Aegis scan clean (0 CRITICAL/HIGH findings)"
                res.setdefault("message", "Aegis scan clean (0 CRITICAL/HIGH findings)")
    return res, 200


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


_STATIC_ASSET_HASH_CACHE: dict[str, tuple[int, int, str]] = {}


def _static_asset_version(rel_name: str, fallback: str = "") -> str:
    """Compute 12-char SHA-256 content hash for a steward static asset, cached by ``(mtime_ns, size)``."""
    clean = str(rel_name or "").split("?", 1)[0].split("#", 1)[0].strip()
    for pfx in ("/steward-static/", "/static/"):
        if clean.startswith(pfx):
            clean = clean[len(pfx):]
            break
    clean = clean.lstrip("/")
    if not clean:
        return fallback or ("0" * 12)
    fpath = STATIC / clean
    try:
        st = fpath.stat()
        key = str(fpath)
        cached = _STATIC_ASSET_HASH_CACHE.get(key)
        if cached and cached[0] == st.st_mtime_ns and cached[1] == st.st_size:
            return cached[2]
        digest = hashlib.sha256(fpath.read_bytes()).hexdigest()[:12]
        _STATIC_ASSET_HASH_CACHE[key] = (st.st_mtime_ns, st.st_size, digest)
        return digest
    except OSError:
        return fallback or ("0" * 12)


def serve_page_doc(page="v1", pid="", effort_dir="", embed=False, view="", *, mount_prefix="/steward", api_prefix="/api/steward"):
    fname = _PAGES.get(page)
    if not fname:
        return None
    build = str(CONFIG.get("build") or getattr(sys.modules.get("anchor_gui") or sys.modules.get("__main__"), "BUILD_ID", "") or "")
    html = (STATIC / fname).read_text(encoding="utf-8")
    use_mounted_static = str(mount_prefix or "").strip() != ""
    static_url_prefix = "/steward-static/" if use_mounted_static else "/static/"
    if use_mounted_static:
        html = (html.replace('href="/static/', 'href="/steward-static/')
                    .replace('src="/static/', 'src="/steward-static/')
                    # Anchor serves brand marks at /vendor/brand/, not /brand/;
                    # rewrite both the static hrefs and the JS "/brand/" base
                    # without double-rewriting existing "/vendor/brand/" paths
                    .replace('"/brand/', '"/vendor/brand/')
                    .replace("'/brand/", "'/vendor/brand/"))

    def _stamp_asset_attr(m):
        attr_and_url = m.group(1)
        asset_rel = m.group(2)
        ver = _static_asset_version(asset_rel, fallback=build)
        return f'{attr_and_url}?v={ver}"'

    html = re.sub(
        r'((?:href|src)="(?:/steward-static/|/static/)([^"?]+\.(?:js|css)))(?:\?v=[^"]*)?"',
        _stamp_asset_attr,
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
    is_embed = bool(embed) or str(view or "").strip().lower() == "tile"
    eff_str = str(effort_dir or "")
    proj_dir_str = ""
    if pid:
        try:
            import rnd_registry as _rnd_sr
            _p_ent = _rnd_sr.get_project(str(pid))
            if isinstance(_p_ent, dict) and _p_ent.get("folder_path"):
                proj_dir_str = str(_p_ent["folder_path"]).replace("\\", "/").rstrip("/")
        except Exception:
            proj_dir_str = ""
    extra_boot = "<script>window.STEWARD_EFFORT_DIR=%s;window.STEWARD_PROJECT_DIR=%s;window.STEWARD_EMBED=%s;</script>" % (
        json.dumps(eff_str),
        json.dumps(proj_dir_str),
        "true" if is_embed else "false",
    )
    shim = extra_boot + (_CLIENT_SHIM % (json.dumps(pid),
                            json.dumps(build), json.dumps(_mode_name()))) + (
        "<script>window.STEWARD_NAME=%s;window.USER_DISPLAY_NAME=%s;</script>" % (
            json.dumps(_persona_name()), json.dumps(user_display_name)
        )
    )
    if api_prefix and api_prefix != "/api/steward":
        shim = shim.replace("/api/steward", str(api_prefix).rstrip("/"))
    nb_ver = _static_asset_version("notebook-actions.js", fallback=build)
    nb_src = f"{static_url_prefix}notebook-actions.js?v={nb_ver}"
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
                       "anvil/walkthrough", "anvil/source", "anvil/v4_state", "anvil/analyses", "anvil/discover",
                       "anvil/scoping", "anvil/replication",
                       "spellcheck", "dictate", "drafts", "fleet-brief", "fleet-relay"}


# ── Wave 3: Crash-Durable Unified Composer Drafts (/api/steward/drafts) ──────
COMPOSER_DRAFT_MAX_BYTES = 256 * 1024
COMPOSER_DRAFTS_MAX_KEYS = 500
COMPOSER_DRAFT_LOCK_TIMEOUT_SEC = 2.0
_DRAFT_STORAGE_AVAILABLE = None
_DRAFT_STORAGE_RESOLVER = None

COMPOSER_DRAFTS_FAILURE_STATE_TABLE = {
    "dependency-missing": {
        "ok": False,
        "status_code": 503,
        "status_kind": "dependency-missing",
        "failure_state": "dependency-missing",
        "badge": "DEPENDENCY_MISSING",
        "unknown_state": False,
        "draft": None,
        "error_code": "DEPENDENCY_MISSING",
        "message": "Composer draft storage engine is unavailable — unsent text stays in your browser.",
    },
    "dependency-slow-or-killed": {
        "ok": False,
        "status_code": 504,
        "status_kind": "dependency-slow-or-killed",
        "failure_state": "dependency-slow-or-killed",
        "badge": "TIMEOUT",
        "unknown_state": False,
        "draft": None,
        "error_code": "LOCK_TIMEOUT",
        "message": "Composer draft store lock timed out — existing draft preserved; retry safely.",
    },
    "dependency-returns-garbage": {
        "ok": False,
        "status_code": 400,
        "status_kind": "dependency-returns-garbage",
        "failure_state": "dependency-returns-garbage",
        "badge": "REJECTED_GARBAGE",
        "unknown_state": False,
        "draft": None,
        "error_code": "INVALID_DRAFT_PAYLOAD",
        "message": "Invalid composer draft request payload or schema.",
    },
    "backing-store-unreadable": {
        "ok": False,
        "status_code": 500,
        "status_kind": "backing-store-unreadable",
        "failure_state": "backing-store-unreadable",
        "badge": "UNKNOWN",
        "unknown_state": True,
        "draft": None,
        "error_code": "BACKING_STORE_UNREADABLE",
        "message": "Composer draft backing store is unreadable (unknown state) — existing file preserved.",
    },
    "empty-but-valid": {
        "ok": True,
        "status_code": 200,
        "status_kind": "empty-but-valid",
        "failure_state": "empty-but-valid",
        "badge": "EMPTY",
        "unknown_state": False,
        "draft": "",
        "error_code": "",
        "message": "No unsent composer draft stored for this scope.",
    },
}


class DraftDependencyMissingError(RuntimeError):
    """Raised when the composer draft storage root or target cockpit directory is unavailable."""


class DraftContainmentError(ValueError):
    """Raised on path traversal, NUL byte, out-of-workspace path, or symlink escape."""


class DraftBoundExceededError(ValueError):
    """Raised when a draft payload exceeds COMPOSER_DRAFT_MAX_BYTES (256 KB)."""


class DraftStoreUnreadableError(OSError):
    """Raised when an on-disk composer-drafts.json file is corrupt or unreadable (`UNKNOWN` != `EMPTY`)."""


def set_draft_storage_available(available=None):
    """Configure or reset (`None`) composer draft storage availability for testing."""
    global _DRAFT_STORAGE_AVAILABLE
    _DRAFT_STORAGE_AVAILABLE = available


def set_draft_storage_resolver(resolver=None):
    """Configure or reset (`None`) custom data_dir resolver for composer drafts."""
    global _DRAFT_STORAGE_RESOLVER
    _DRAFT_STORAGE_RESOLVER = resolver


def set_draft_lock_timeout(timeout_sec: float = 2.0):
    """Configure lock acquisition timeout (`COMPOSER_DRAFT_LOCK_TIMEOUT_SEC`)."""
    global COMPOSER_DRAFT_LOCK_TIMEOUT_SEC
    COMPOSER_DRAFT_LOCK_TIMEOUT_SEC = max(0.01, float(timeout_sec))


def _draft_failure_response(row_key: str, *, status_code: int | None = None, detail: str = "", **extra):
    base = dict(COMPOSER_DRAFTS_FAILURE_STATE_TABLE[row_key])
    code = int(status_code if status_code is not None else base["status_code"])
    base["status_code"] = code
    if detail:
        base["detail"] = str(detail)
        base["error"] = str(detail)
    else:
        base["error"] = base["message"]
    base.update(extra)
    return base, code


def _draft_containment_refusal(detail: str = "Blocked unsafe path traversal, absolute path, or symlink escape"):
    return {
        "ok": False,
        "refused": True,
        "status_code": 403,
        "status_kind": "dependency-returns-garbage",
        "failure_state": "dependency-returns-garbage",
        "badge": "REJECTED_GARBAGE",
        "unknown_state": False,
        "draft": None,
        "error_code": "PATH_CONTAINMENT_REFUSAL",
        "error": detail,
        "message": detail,
    }, 403


def _draft_bound_exceeded_refusal(actual_bytes: int = 0):
    msg = f"Composer draft payload ({actual_bytes} bytes) exceeds 256 KB limit ({COMPOSER_DRAFT_MAX_BYTES} bytes)."
    return {
        "ok": False,
        "refused": True,
        "status_code": 413,
        "status_kind": "bound-exceeded",
        "failure_state": "bound-exceeded",
        "badge": "BOUND_EXCEEDED",
        "unknown_state": False,
        "draft": None,
        "max_bytes": COMPOSER_DRAFT_MAX_BYTES,
        "actual_bytes": int(actual_bytes),
        "error_code": "BOUND_EXCEEDED_REFUSAL",
        "error": msg,
        "message": msg,
    }, 413


def _check_no_traversal_or_nul(raw_val: str, *, allow_slashes: bool = False) -> str:
    import urllib.parse as _up
    from pathlib import PurePosixPath, PureWindowsPath
    if raw_val is None:
        return ""
    if not isinstance(raw_val, str):
        raise ValueError("String parameter required")
    s = raw_val.strip()
    if not s:
        return ""
    forms = [raw_val, s, _up.unquote(raw_val), _up.unquote(_up.unquote(raw_val))]
    for f in forms:
        if "\x00" in f:
            raise DraftContainmentError("NUL byte rejected")
        norm = f.replace("\\", "/")
        parts = [p for p in PurePosixPath(norm).parts if p]
        if ".." in parts:
            raise DraftContainmentError("Relative '..' traversal rejected")
        if not allow_slashes:
            if "/" in f or "\\" in f or ":" in f or bool(PureWindowsPath(f).drive):
                raise DraftContainmentError("Path separator or drive prefix rejected in identifier")
    return s


def _verify_contained_effort_dir(proot_path: Path, rel_effort: str) -> Path:
    from provider_native import private_account_path
    proot_real = proot_path.resolve()
    if private_account_path(str(proot_real)):
        raise DraftContainmentError("Private account path refused")
    if not rel_effort:
        if proot_path.is_symlink():
            raise DraftContainmentError("Symlink root escape refused")
        return proot_real
    try:
        resolved = paths.resolve_contained_path(proot_real, rel_effort, allow_missing=True)
    except paths.UnsafePathError as exc:
        raise DraftContainmentError(str(exc)) from exc
    if private_account_path(str(resolved)):
        raise DraftContainmentError("Private account path refused")
    # Walk every segment under proot_real to reject symlinks/junctions pointing outside proot_real
    import urllib.parse as _up
    clean_rel = _up.unquote(rel_effort).replace("\\", "/").strip("/")
    cur = proot_real
    for seg in [p for p in clean_rel.split("/") if p and p != "."]:
        if seg == ".." or ":" in seg:
            raise DraftContainmentError("Unsafe effort segment")
        cur = cur / seg
        try:
            if cur.is_symlink():
                link_target = cur.resolve()
                if not link_target.is_relative_to(proot_real):
                    raise DraftContainmentError("Symlink escapes project root")
        except DraftContainmentError:
            raise
        except OSError as exc:
            raise DraftContainmentError("Unresolvable symlink in effort path") from exc
        if cur.exists():
            real_cur = cur.resolve()
            if not real_cur.is_relative_to(proot_real):
                raise DraftContainmentError("Junction/reparse point escapes project root")
    return resolved


def _allowed_workspace_roots(data_root: Path) -> list[Path]:
    roots: list[Path] = [data_root.resolve()]
    try:
        import rnd_registry as _rnd
        for proj in _rnd.list_projects(include_archived=True, include_future=True, include_retired=True):
            fp = str(proj.get("folder_path") or "").strip()
            if fp:
                p = Path(fp)
                if p.exists():
                    roots.append(p.resolve())
    except Exception:
        pass
    if os.path.isdir(_DEFAULT_CAMPAIGN_DIR):
        roots.append(Path(_DEFAULT_CAMPAIGN_DIR).resolve())
    return roots


def _resolve_draft_data_root() -> Path:
    if _DRAFT_STORAGE_AVAILABLE is False:
        raise DraftDependencyMissingError("Composer draft storage engine disabled/unavailable")
    if callable(_DRAFT_STORAGE_RESOLVER):
        dd = _DRAFT_STORAGE_RESOLVER()
        if dd is None:
            raise DraftDependencyMissingError("Composer draft storage root unavailable")
        root = Path(dd)
    else:
        raw_env = (os.environ.get(paths.DATA_DIR_ENV) or "").strip()
        root = Path(raw_env).expanduser() if raw_env else paths.data_dir()
    if root.exists() and not root.is_dir():
        raise DraftDependencyMissingError(f"ANCHOR_DATA_DIR is not a directory: {root}")
    return root.resolve()


def _resolve_draft_scope(params: dict, *, proot: str | Path | None = None) -> tuple[str, Path | None, Path]:
    """Validate containment and return `(canonical_scope_key, optional_cockpit_dir, anchor_drafts_file)`."""
    from provider_native import private_account_path
    data_root = _resolve_draft_data_root()
    anchor_store = data_root / ".anchor" / "composer-drafts.json"

    raw_surface = params.get("surface", "")
    raw_uid = params.get("uid", params.get("email_id", ""))
    raw_pid = params.get("pid", params.get("project", params.get("project_id", "")))
    raw_eff = params.get("dir", params.get("effort", params.get("effort_dir", "")))
    raw_target_dir = params.get("target_dir", "")
    raw_goal = params.get("goal", "")
    raw_term = params.get("term", "")
    raw_gen = params.get("general", False)

    for k_name, v_val in (
        ("surface", raw_surface),
        ("uid", raw_uid),
        ("pid", raw_pid),
        ("effort", raw_eff),
        ("target_dir", raw_target_dir),
        ("goal", raw_goal),
        ("term", raw_term),
    ):
        if v_val is not None and not isinstance(v_val, (str, int, bool)):
            raise ValueError(f"Invalid type for {k_name}")

    surface = _check_no_traversal_or_nul(str(raw_surface or ""), allow_slashes=False).lower()
    uid = _check_no_traversal_or_nul(str(raw_uid or ""), allow_slashes=False)
    pid_clean = _check_no_traversal_or_nul(str(raw_pid or ""), allow_slashes=False)
    eff_clean = _check_no_traversal_or_nul(str(raw_eff or ""), allow_slashes=True)
    goal_clean = _check_no_traversal_or_nul(str(raw_goal or ""), allow_slashes=False)
    term_clean = _check_no_traversal_or_nul(str(raw_term or ""), allow_slashes=False)
    is_general = str(raw_gen).strip().lower() in ("1", "true", "yes") if not isinstance(raw_gen, bool) else raw_gen

    if eff_clean:
        from pathlib import PureWindowsPath
        if eff_clean.startswith(("/", "\\")) or os.path.isabs(eff_clean) or bool(PureWindowsPath(eff_clean).drive):
            raise DraftContainmentError("Effort path must be relative to project root")

    target_dir_str = str(raw_target_dir or "").strip()
    if target_dir_str:
        _check_no_traversal_or_nul(target_dir_str, allow_slashes=True)
        td_path = Path(target_dir_str)
        if not td_path.is_absolute():
            raise DraftContainmentError("target_dir must be a contained workspace root, not relative escape")
        if td_path.is_symlink():
            raise DraftContainmentError("Symlink target_dir refused")
        td_real = td_path.resolve()
        if private_account_path(str(td_real)):
            raise DraftContainmentError("Private account path refused")
        allowed_roots = _allowed_workspace_roots(data_root)
        if not any(td_real == r or td_real.is_relative_to(r) for r in allowed_roots):
            raise DraftContainmentError("Out-of-workspace absolute target_dir refused")
        if not td_real.is_dir():
            raise DraftDependencyMissingError("Target cockpit directory unavailable")
        resolved_eff = _verify_contained_effort_dir(td_real, eff_clean)
        if not resolved_eff.is_dir():
            raise DraftDependencyMissingError("Target effort directory unavailable")
        scope_key = f"cockpit::{os.path.normcase(str(resolved_eff))}"
        if is_general:
            scope_key += f"::general::{term_clean or '1'}"
        if goal_clean:
            scope_key += f"::goal::{goal_clean}"
        return scope_key, resolved_eff, anchor_store

    # Email Scribe / Steward directions surface (#caveDlgStewardDirectionsInput)
    if surface in ("email", "cave_email", "scribe_directions") or (uid and not pid_clean and not proot):
        if not uid:
            uid = "none"
        return f"email::{uid}", None, anchor_store

    # Global Cave (#say) and Star Chart (#exSay) steward composers
    if surface in ("cave_say", "star_chart", "exsay", "ex_say"):
        canonical_surf = "exSay" if surface in ("star_chart", "exsay", "ex_say") else "cave_say"
        scope_key = f"surface::{canonical_surf}"
        if goal_clean:
            scope_key += f"::goal::{goal_clean}"
        opt_cdir: Path | None = None
        if proot and os.path.isdir(str(proot)):
            try:
                cand = _verify_contained_effort_dir(Path(proot), eff_clean)
                if cand.is_dir():
                    opt_cdir = cand
            except Exception:
                opt_cdir = None
        return scope_key, opt_cdir, anchor_store

    # Project / Effort AI Cockpit (/steward/v1 and /steward/v1?view=tile share the EXACT SAME canonical scope!)
    resolved_proot: Path | None = None
    if proot is not None and str(proot).strip():
        p_cand = Path(str(proot))
        if p_cand.is_symlink():
            raise DraftContainmentError("Symlink project root refused")
        if p_cand.is_dir():
            resolved_proot = p_cand.resolve()
    if resolved_proot is None and pid_clean:
        try:
            import rnd_registry as _rnd
            proj = _rnd.get_project(pid_clean) or {}
            fp = str(proj.get("folder_path") or "").strip()
            if fp and os.path.isdir(fp):
                resolved_proot = Path(fp).resolve()
        except Exception:
            pass
        if resolved_proot is None:
            named = _resolve_named_cockpit_dir(pid_clean)
            if named and os.path.isdir(named):
                resolved_proot = Path(named).resolve()
        if resolved_proot is None:
            # Also check data_root / pid_clean for hermetic test fixtures under ANCHOR_DATA_DIR
            cand_dd = (data_root / pid_clean)
            if cand_dd.is_dir() and not cand_dd.is_symlink():
                resolved_proot = cand_dd.resolve()

    if resolved_proot is None:
        if pid_clean or eff_clean:
            raise DraftDependencyMissingError(f"Cockpit project directory unavailable for '{pid_clean or eff_clean}'")
        raise ValueError("Draft scope requires project/pid, surface, or email uid")

    resolved_target = _verify_contained_effort_dir(resolved_proot, eff_clean)
    if not resolved_target.exists() or not resolved_target.is_dir():
        raise DraftDependencyMissingError(f"Effort directory unavailable: {resolved_target}")

    # Canonical scope key ignores `view=tile` / `embed=1` so tile and full cockpit are 100% unified!
    scope_key = f"cockpit::{os.path.normcase(str(resolved_target))}"
    if is_general:
        scope_key += f"::general::{term_clean or '1'}"
    if goal_clean:
        scope_key += f"::goal::{goal_clean}"
    return scope_key, resolved_target, anchor_store


def _read_draft_store_file_strict(store_path: Path) -> dict:
    """Read `composer-drafts.json` strictly:
    - Missing file -> empty dict `{}` (`EMPTY` state).
    - Corrupt JSON / non-dict / OSError -> raises `DraftStoreUnreadableError` (`500 UNKNOWN`, never collapsed to `{}`)!"""
    if not store_path.exists():
        return {"version": 1, "drafts": {}}
    try:
        if store_path.is_dir():
            raise DraftStoreUnreadableError(f"Expected JSON file, found directory: {store_path}")
        raw_text = store_path.read_text(encoding="utf-8")
        doc = json.loads(raw_text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DraftStoreUnreadableError(f"Unreadable composer draft store {store_path}: {exc}") from exc
    if not isinstance(doc, dict) or not isinstance(doc.get("drafts", {}), dict):
        raise DraftStoreUnreadableError(f"Invalid composer draft store schema in {store_path}")
    return doc


def _write_single_draft_store_atomic(store_path: Path, scope_key: str, entry: dict | None) -> None:
    """Mutate `scope_key` inside `store_path` under exclusive `cross_process_lock` via `temp + os.fsync + os.replace`."""
    lock_path = store_path.with_name(f"{store_path.name}.lock")
    store_path.parent.mkdir(parents=True, exist_ok=True)
    with paths.cross_process_lock(lock_path, timeout_sec=COMPOSER_DRAFT_LOCK_TIMEOUT_SEC):
        doc = _read_draft_store_file_strict(store_path)
        drafts = dict(doc.get("drafts") or {})
        if entry is None:
            drafts.pop(scope_key, None)
        else:
            drafts[scope_key] = entry
            if len(drafts) > COMPOSER_DRAFTS_MAX_KEYS:
                ordered = sorted(
                    drafts.items(),
                    key=lambda kv: int((kv[1].get("updated_at_ms") if isinstance(kv[1], dict) else 0) or 0),
                )
                for evict_k, _ in ordered[: len(drafts) - COMPOSER_DRAFTS_MAX_KEYS]:
                    if evict_k != scope_key:
                        drafts.pop(evict_k, None)
        out_doc = {
            "version": 1,
            "updated_at_ms": int(time.time() * 1000),
            "drafts": drafts,
        }
        paths.atomic_write_text(store_path, json.dumps(out_doc, indent=2, ensure_ascii=False))


def handle_drafts_request(
    method: str,
    *,
    qs: dict | None = None,
    body: object = None,
    proot: str | Path | None = None,
    raw_parse_error: bool = False,
    raw_body_too_large: bool = False,
    raw_body_len: int = 0,
) -> tuple[dict, int]:
    """Unified `GET` / `POST` / `DELETE` handler for `/api/steward/drafts`."""
    verb_method = str(method or "GET").upper()
    if raw_body_too_large:
        return _draft_bound_exceeded_refusal(raw_body_len or (COMPOSER_DRAFT_MAX_BYTES + 1))
    if raw_parse_error:
        return _draft_failure_response("dependency-returns-garbage", detail="Malformed JSON body in /api/steward/drafts request")

    flat_qs: dict = {}
    for k, v in (qs or {}).items():
        flat_qs[k] = v[0] if isinstance(v, list) and v else ("" if isinstance(v, list) else v)

    merged_params = dict(flat_qs)
    if verb_method in ("POST", "DELETE") and body is not None:
        if not isinstance(body, dict):
            return _draft_failure_response("dependency-returns-garbage", detail="JSON object body required")
        for bk, bv in body.items():
            if bv is not None and (bk not in merged_params or merged_params[bk] == "" or verb_method == "POST"):
                merged_params[bk] = bv

    # Pre-check payload bound on POST BEFORE touching disk
    draft_text = ""
    is_clear_op = (verb_method == "DELETE")
    if verb_method == "POST":
        if not isinstance(body, dict):
            return _draft_failure_response("dependency-returns-garbage", detail="JSON object body required")
        act = str(body.get("action") or "").strip().lower()
        if act in ("clear", "delete"):
            is_clear_op = True
            raw_draft = body.get("draft", body.get("text", ""))
            if raw_draft is not None and not isinstance(raw_draft, str):
                return _draft_failure_response("dependency-returns-garbage", detail="draft field must be a string")
        else:
            if "draft" in body:
                raw_draft = body["draft"]
            elif "text" in body:
                raw_draft = body["text"]
            else:
                return _draft_failure_response("dependency-returns-garbage", detail="Missing required 'draft' string field")
            if not isinstance(raw_draft, str):
                return _draft_failure_response("dependency-returns-garbage", detail="'draft' field must be a string")
            draft_text = raw_draft
            encoded_len = len(draft_text.encode("utf-8"))
            if encoded_len > COMPOSER_DRAFT_MAX_BYTES:
                return _draft_bound_exceeded_refusal(encoded_len)
            if draft_text == "":
                is_clear_op = True

    try:
        scope_key, cockpit_dir, anchor_store = _resolve_draft_scope(merged_params, proot=proot)
    except DraftContainmentError as exc:
        return _draft_containment_refusal(str(exc))
    except DraftDependencyMissingError as exc:
        return _draft_failure_response("dependency-missing", detail=str(exc))
    except ValueError as exc:
        return _draft_failure_response("dependency-returns-garbage", detail=str(exc))

    ecg_store = (cockpit_dir / ".ecgberht" / "composer-drafts.json") if cockpit_dir is not None else None
    stores_in_order = [s for s in (ecg_store, anchor_store) if s is not None]
    # Deduplicate if paths happen to coincide
    uniq_stores: list[Path] = []
    seen_st: set[str] = set()
    for sp in stores_in_order:
        nk = os.path.normcase(os.path.abspath(str(sp)))
        if nk not in seen_st:
            seen_st.add(nk)
            uniq_stores.append(sp)

    try:
        if verb_method == "GET":
            candidates: list[dict] = []
            for sp in uniq_stores:
                lock_p = sp.with_name(f"{sp.name}.lock")
                if sp.exists():
                    with paths.cross_process_lock(lock_p, timeout_sec=COMPOSER_DRAFT_LOCK_TIMEOUT_SEC):
                        doc = _read_draft_store_file_strict(sp)
                    rec = (doc.get("drafts") or {}).get(scope_key)
                    if isinstance(rec, dict) and isinstance(rec.get("draft"), str) and rec.get("draft") != "":
                        candidates.append(rec)
                    elif isinstance(rec, str) and rec != "":
                        candidates.append({"draft": rec, "updated_at_ms": int(doc.get("updated_at_ms") or 0)})
            if not candidates:
                return _draft_failure_response("empty-but-valid", scope_key=scope_key)
            best = max(candidates, key=lambda r: int(r.get("updated_at_ms") or 0))
            return {
                "ok": True,
                "status_code": 200,
                "status_kind": "ok",
                "failure_state": "ok",
                "badge": "SAVED",
                "unknown_state": False,
                "scope_key": scope_key,
                "draft": str(best.get("draft") or ""),
                "updated_at_ms": int(best.get("updated_at_ms") or 0),
                "message": "Restored unsent composer draft.",
            }, 200

        if is_clear_op:
            first_clear_err: Exception | None = None
            for sp in uniq_stores:
                if sp.exists():
                    try:
                        _write_single_draft_store_atomic(sp, scope_key, None)
                    except Exception as clr_exc:
                        if first_clear_err is None:
                            first_clear_err = clr_exc
            if first_clear_err is not None:
                raise first_clear_err
            res_clear, code_clear = _draft_failure_response("empty-but-valid", scope_key=scope_key, cleared=True)
            return res_clear, code_clear

        now_ms = int(time.time() * 1000)
        entry_obj = {
            "draft": draft_text,
            "byte_length": len(draft_text.encode("utf-8")),
            "updated_at_ms": now_ms,
            "scope_key": scope_key,
        }
        for sp in uniq_stores:
            _write_single_draft_store_atomic(sp, scope_key, entry_obj)
        return {
            "ok": True,
            "status_code": 200,
            "status_kind": "ok",
            "failure_state": "ok",
            "badge": "SAVED",
            "unknown_state": False,
            "scope_key": scope_key,
            "draft": draft_text,
            "byte_length": entry_obj["byte_length"],
            "updated_at_ms": now_ms,
            "stores_written": len(uniq_stores),
            "message": "Saved unsent composer draft atomically.",
        }, 200
    except TimeoutError as exc:
        return _draft_failure_response("dependency-slow-or-killed", detail=str(exc))
    except DraftStoreUnreadableError as exc:
        return _draft_failure_response("backing-store-unreadable", detail=str(exc))
    except OSError as exc:
        return _draft_failure_response("backing-store-unreadable", detail=str(exc))


def handle_drafts_http(
    handler,
    full_path: str,
    method: str,
    body: object = None,
    *,
    raw_parse_error: bool = False,
    raw_body_too_large: bool = False,
    raw_body_len: int = 0,
) -> None:
    """HTTP adapter invoked by `anchor_gui` strangler dispatch for `GET` / `POST` / `DELETE` `/api/steward/drafts`."""
    import urllib.parse as _up
    if hasattr(handler, "_steward_same_origin") and not handler._steward_same_origin():
        handler._send_json({"ok": False, "error": "cross-origin refused"}, code=403)
        return
    parsed = _up.urlparse(str(full_path or getattr(handler, "path", "") or ""))
    qs = _up.parse_qs(parsed.query, keep_blank_values=True)
    # Only auto-resolve proot via handler._steward_pid_dir when pid/project looks safe (let containment gate catch escapes!)
    raw_pid = ((qs.get("pid") or qs.get("project") or [""])[0] or "").strip()
    if not raw_pid and isinstance(body, dict):
        raw_pid = str(body.get("pid") or body.get("project") or "").strip()
    proot = None
    if raw_pid and not any(ch in raw_pid for ch in ("/", "\\", ":", "\x00")) and ".." not in raw_pid:
        if hasattr(handler, "_steward_pid_dir"):
            proot = handler._steward_pid_dir(raw_pid)
    res, code = handle_drafts_request(
        method,
        qs=qs,
        body=body,
        proot=proot,
        raw_parse_error=raw_parse_error,
        raw_body_too_large=raw_body_too_large,
        raw_body_len=raw_body_len,
    )
    handler._send_json(res, code=code)


_PROJECT_TERMINAL_VERBS = {"term_new", "term_archive", "term_restore"}
_GENERAL_READ_VERBS = {"map", "history", "state", "events", "deliverables", "plan", "spend"}
_GENERAL_POST_VERBS = {"say", "engine", "dismiss-deliverable", "deliverables/dismiss",
                       "approve-deliverable", "deliverables/approve", "plan"}


def _plan_missing_response():
    return {
        "ok": False,
        "failure_state": "dependency-missing",
        "error": "Campaign directory not found",
        "message": "Campaign directory not found",
    }, 404


def _plan_garbage_response():
    return {
        "ok": False,
        "failure_state": "dependency-returns-garbage",
        "error": "Invalid plan mutation or step cap (>200) exceeded",
        "message": "Invalid plan mutation or step cap (>200) exceeded",
    }, 400


def _plan_http_error(exc):
    from tools import steward_plan as _splan
    if isinstance(exc, _splan.PlanMissingDirError):
        return exc.to_dict(), 404
    if isinstance(exc, (_splan.PlanLockTimeoutError, TimeoutError)):
        return {
            "ok": False,
            "failure_state": "dependency-slow-or-killed",
            "error": "Plan state lock busy (>2.0s) — retry",
            "message": "Plan state lock busy (>2.0s) — retry",
        }, 504
    if isinstance(exc, (_splan.PlanValidationError, ValueError)):
        return _plan_garbage_response()
    if isinstance(exc, _splan.PlanStoreUnreadableError):
        return exc.to_dict(), 500
    return {
        "ok": False,
        "failure_state": "backing-store-unreadable",
        "error": "Plan/Deliverables unreadable (unknown) — inspect roadmap.json",
        "message": "Plan/Deliverables unreadable (unknown) — inspect roadmap.json",
    }, 500


def _resolve_plan_cdir(proot, rel):
    """Resolve the effort directory for /api/plan safely (allowing valid project/effort dirs
    even before ECGBERHT.md exists so empty-but-valid and init/add_step work immediately)."""
    if not proot or not os.path.isdir(str(proot)):
        return None
    rel = str(rel or "").strip()
    if not rel:
        if campaign.is_retired_in_place(str(proot)):
            return None
        return str(proot)
    if ":" in rel or rel.startswith(("/", "\\")):
        return None
    norm_rel = rel.replace("\\", "/").strip("/")
    parts = [p for p in norm_rel.split("/") if p]
    if not parts or any(p in (".", "..") or p.startswith((".", "_")) for p in parts):
        return None
    ed = _effort_dir(proot, rel)
    if ed and os.path.isdir(ed):
        return ed
    proot_real = os.path.realpath(str(proot))
    cand_real = os.path.realpath(str(Path(proot) / norm_rel))
    if cand_real.startswith(proot_real + os.sep) and os.path.isdir(cand_real):
        if not campaign.is_retired_in_place(cand_real):
            return cand_real
    return None


def _resolve_anvil_route_cdir(proot, rel):
    """Resolve and containment-check `dir` for Anvil routes, or discover child effort when `dir` is omitted."""
    from steward_cockpit import anvil_session as _as_dir

    base = Path(str(proot or "")).resolve()
    raw_rel = str(rel or "").strip()
    if not raw_rel:
        if hasattr(_as_dir, "resolve_cockpit_or_child_effort"):
            return str(_as_dir.resolve_cockpit_or_child_effort(base)), None
        return str(base), None

    if (
        "\x00" in raw_rel
        or ".." in raw_rel.replace("\\", "/").split("/")
        or ".." in Path(raw_rel).parts
        or raw_rel.startswith(("/", "\\"))
        or ":" in raw_rel
        or Path(raw_rel).is_absolute()
    ):
        msg = "Malformed Anvil request or invalid engine output"
        return None, (
            {
                "ok": False,
                "error_code": "PATH_ESCAPE_REFUSED",
                "status_kind": "dependency-returns-garbage",
                "failure_state": "dependency-returns-garbage",
                "http_status": 403,
                "state": "REJECTED_GARBAGE",
                "badge": "REJECTED_GARBAGE",
                "unknown_state": False,
                "error": msg,
                "message": msg,
            },
            403,
        )

    walk = base
    for part in [p for p in re.split(r"[\\/]+", raw_rel) if p and p != "."]:
        low = part.lower()
        if low in _as_dir.FORBIDDEN_DOT_PARTS or low in _as_dir.FORBIDDEN_SECRET_NAMES or part.startswith("."):
            msg = "Malformed Anvil request or invalid engine output"
            return None, (
                {
                    "ok": False,
                    "error_code": "PATH_ESCAPE_REFUSED",
                    "status_kind": "dependency-returns-garbage",
                    "failure_state": "dependency-returns-garbage",
                    "http_status": 403,
                    "state": "REJECTED_GARBAGE",
                    "badge": "REJECTED_GARBAGE",
                    "unknown_state": False,
                    "error": msg,
                    "message": msg,
                },
                403,
            )
        walk = walk / part
        if _as_dir._is_symlink_or_junction(walk):
            msg = "Malformed Anvil request or invalid engine output"
            return None, (
                {
                    "ok": False,
                    "error_code": "PATH_ESCAPE_REFUSED",
                    "status_kind": "dependency-returns-garbage",
                    "failure_state": "dependency-returns-garbage",
                    "http_status": 403,
                    "state": "REJECTED_GARBAGE",
                    "badge": "REJECTED_GARBAGE",
                    "unknown_state": False,
                    "error": msg,
                    "message": msg,
                },
                403,
            )

    cand_resolved = walk.resolve()
    if cand_resolved != base and base not in cand_resolved.parents:
        msg = "Malformed Anvil request or invalid engine output"
        return None, (
            {
                "ok": False,
                "error_code": "PATH_ESCAPE_REFUSED",
                "status_kind": "dependency-returns-garbage",
                "failure_state": "dependency-returns-garbage",
                "http_status": 403,
                "state": "REJECTED_GARBAGE",
                "badge": "REJECTED_GARBAGE",
                "unknown_state": False,
                "error": msg,
                "message": msg,
            },
            403,
        )

    eff = _effort_dir(proot, raw_rel)
    if eff and os.path.isdir(eff):
        return str(Path(eff).resolve()), None
    if cand_resolved.is_dir():
        return str(cand_resolved), None
    if base.name.lower() == raw_rel.lower():
        return str(base), None
    return None, ({"ok": False, "error_code": "UNKNOWN_EFFORT", "error": "unknown effort", "message": "Unknown effort"}, 404)


def _registered_project_terminal(proot, raw_tid):
    tid = str(raw_tid or "")
    if not re.fullmatch(r"\d{1,6}", tid):
        return False
    record = _load_terms(proot).get(tid)
    return isinstance(record, dict) and not record.get("archived")


def api_get(proot, verb, qs):
    _ROUTE_TLS.req_query = ""
    qs = qs or {}
    if verb == "usage-summary":
        return global_usage_summary(qs)
    if verb == "usage-allowance":
        return usage_allowance_get(qs)
    if verb == "drafts":
        return handle_drafts_request("GET", qs=qs, proot=proot)
    if verb == "plan":
        if qs.get("general") == "1" and not (qs.get("dir") or "").strip():
            if not proot or not os.path.isdir(str(proot)):
                return _plan_missing_response()
            if not _registered_project_terminal(proot, qs.get("term")):
                return {"error": "no such project terminal"}, 404
            return handle_get(proot, "plan", qs)
        cdir = _resolve_plan_cdir(proot, qs.get("dir", ""))
        if cdir is None:
            return _plan_missing_response()
        return handle_get(cdir, "plan", qs)
    if verb == "spend":
        if qs.get("general") == "1" and not (qs.get("dir") or "").strip():
            if not proot or not os.path.isdir(str(proot)):
                return {"error": "unknown effort"}, 404
            if not _registered_project_terminal(proot, qs.get("term")):
                return {"error": "no such project terminal"}, 404
            return handle_get(proot, "spend", qs)
        rel_s = (qs.get("dir") or "").strip()
        cdir = _effort_dir(proot, rel_s) or _resolve_plan_cdir(proot, rel_s)
        if cdir is None and (qs.get("project_id") or qs.get("pid")):
            return spend_http_response("", qs=qs)
        if cdir is None:
            return {"error": "unknown effort"}, 404
        return handle_get(cdir, "spend", qs)
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
    if verb == "anvil" or verb.startswith("anvil/"):
        rel_av = (qs.get("dir") or "").strip()
        cdir_av, err_av = _resolve_anvil_route_cdir(proot, rel_av)
        if err_av is not None:
            return err_av
        return handle_get(cdir_av, verb, qs)
    if verb in ("spellcheck", "dictate", "fleet-brief", "fleet-relay", "mothership-files"):
        rel = (qs.get("dir") or "").strip()
        cdir = _effort_dir(proot, rel) or (_resolve_named_cockpit_dir(rel) if rel else None) or proot
        return handle_get(cdir, verb, qs)
    if verb == "aegis":
        rel = (qs.get("dir") or "").strip()
        if rel:
            try:
                cand_eff = paths.resolve_contained_path(proot, rel, allow_missing=True)
            except paths.UnsafePathError:
                return {
                    "ok": False,
                    "failure_state": "dependency-returns-garbage",
                    "error": "Blocked unsafe path traversal or disallowed URL scheme",
                    "message": "Blocked unsafe path traversal or disallowed URL scheme",
                }, 403
            cdir = _effort_dir(proot, rel) or _resolve_plan_cdir(proot, rel) or str(cand_eff)
        else:
            cdir = str(proot or "")
        return handle_get(cdir, verb, qs)
    if verb in _PROJECT_VERBS or verb in ("terms",) or verb in _PROJECT_FILE_VERBS:
        rel = (qs.get("dir") or "").strip()
        if verb in _PROJECT_FILE_VERBS and rel:
            if verb == "deliverable-file":
                try:
                    paths.resolve_contained_path(proot, rel, allow_missing=True)
                except paths.UnsafePathError:
                    return {
                        "ok": False,
                        "failure_state": "dependency-returns-garbage",
                        "error": "Blocked unsafe path traversal or disallowed URL scheme",
                    }, 403
                cdir = _effort_dir(proot, rel) or _resolve_plan_cdir(proot, rel)
            else:
                cdir = _effort_dir(proot, rel)
            if cdir is None:
                return {"error": "unknown effort"}, 404
            return handle_get(cdir, verb, qs)
        return handle_get(proot, verb, qs)
    if verb in ("wave-state", "wave-map", "deliverable-batches"):
        rel_w = (qs.get("dir") or "").strip()
        if rel_w:
            try:
                paths.resolve_contained_path(proot, rel_w, allow_missing=True)
            except paths.UnsafePathError:
                return {"ok": False, "error": "path traversal refused"}, 403
        cdir_w = _effort_dir(proot, rel_w)
        if cdir_w is None:
            return {"ok": False, "error": "unknown effort"}, 404
        return handle_get(cdir_w, verb, qs)
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
    _req_q = str(getattr(_ROUTE_TLS, "req_query", "") or "")
    _ROUTE_TLS.req_query = ""
    if verb == "drafts":
        import urllib.parse as _up
        _qs_d = _up.parse_qs(_req_q, keep_blank_values=True) if _req_q else {}
        return handle_drafts_request("POST", qs=_qs_d, body=body, proot=proot)
    if verb == "plan":
        if not isinstance(body, dict):
            return _plan_garbage_response()
        if "dir" in body:
            rel_p = str(body.get("dir") or "").strip()
        elif _req_q:
            import urllib.parse as _up
            rel_p = str((_up.parse_qs(_req_q, keep_blank_values=True).get("dir") or [""])[0] or "").strip()
        else:
            rel_p = ""
        if not rel_p and body.get("general") is True:
            if not proot or not os.path.isdir(str(proot)):
                return _plan_missing_response()
            if not _registered_project_terminal(proot, body.get("term")):
                return {"ok": False, "error": "no such project terminal"}, 404
            return handle_post(proot, "plan", body)
        cdir_p = _resolve_plan_cdir(proot, rel_p)
        if cdir_p is None:
            return _plan_missing_response()
        return handle_post(cdir_p, "plan", body)
    if verb in ("new_effort", "boneyard_restore", "boneyard_move",
                "rename_effort"):
        return _project_post(proot, verb, body)
    if verb == "aegis":
        if not isinstance(body, dict):
            return {
                "ok": False,
                "failure_state": "dependency-returns-garbage",
                "error": "Blocked unsafe path traversal or disallowed URL scheme",
                "message": "Blocked unsafe path traversal or disallowed URL scheme",
            }, 400
        rel_a = str(body.get("dir") or "").strip()
        if rel_a:
            try:
                cand_eff = paths.resolve_contained_path(proot, rel_a, allow_missing=True)
            except paths.UnsafePathError:
                return {
                    "ok": False,
                    "failure_state": "dependency-returns-garbage",
                    "error": "Blocked unsafe path traversal or disallowed URL scheme",
                    "message": "Blocked unsafe path traversal or disallowed URL scheme",
                }, 403
            cdir_a = _effort_dir(proot, rel_a) or _resolve_plan_cdir(proot, rel_a) or str(cand_eff)
        else:
            cdir_a = str(proot or "")
        return handle_post(cdir_a, verb, body)
    if verb == "anvil" or verb.startswith("anvil/"):
        if not isinstance(body, dict):
            msg_g = "Malformed Anvil request or invalid engine output"
            return {"ok": False, "error_code": "MALFORMED_DATA_REFUSED", "status_kind": "dependency-returns-garbage", "failure_state": "dependency-returns-garbage", "error": msg_g, "message": msg_g}, 400
        rel_av = (body.get("dir") or "").strip()
        cdir_av, err_av = _resolve_anvil_route_cdir(proot, rel_av)
        if err_av is not None:
            return err_av
        return handle_post(cdir_av, verb, body)
    rel = (body.get("dir") or "").strip()
    if not rel and verb in _PROJECT_TERMINAL_VERBS:
        return handle_post(proot, verb, body)
    if not rel and body.get("general") is True and verb in _GENERAL_POST_VERBS:
        if not _registered_project_terminal(proot, body.get("term")):
            return {"ok": False, "error": "no such project terminal"}, 404
        if body.get("refinement_context"):
            return {"ok": False, "error": "refinement belongs to its campaign"}, 400
        return handle_post(proot, verb, body)
    if verb in ("spellcheck", "dictate", "fleet-brief", "fleet-relay", "mothership-files"):
        cdir = _effort_dir(proot, rel) or (_resolve_named_cockpit_dir(rel) if rel else None) or proot
        return handle_post(cdir, verb, body)
    if verb in _PROJECT_FILE_VERBS and not rel:
        return handle_post(proot, verb, body)
    if verb in ("wave-state", "wave-map", "deliverable-batches"):
        if not isinstance(body, dict):
            return {"ok": False, "error": "JSON object required"}, 400
        rel_w = str(body.get("dir") or "").strip()
        if rel_w:
            try:
                paths.resolve_contained_path(proot, rel_w, allow_missing=True)
            except paths.UnsafePathError:
                return {"ok": False, "error": "path traversal refused"}, 403
        cdir_w = _effort_dir(proot, rel_w)
        if cdir_w is None:
            return {"ok": False, "error": "unknown effort"}, 404
        return handle_post(cdir_w, verb, body)
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
                    "has_anvil": (Path(edir) / ".anvil" / "session.json").is_file()
                                 or (Path(edir) / ".anvil" / "analyses" / "index.json").is_file(),
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
    if value.get("ok") is not False:
        with _ROLLUP_LOCK:
            if len(_ROLLUP_CACHE) > 256:
                _ROLLUP_CACHE.clear()
            _ROLLUP_CACHE[key] = (now, value)
    return copy.deepcopy(value)


def _fmt_compact_tok(n) -> str:
    try:
        v = max(0, int(round(float(n or 0))))
    except (TypeError, ValueError):
        v = 0
    if v >= 1_000_000:
        m_str = f"{v / 1e6:.2f}".removesuffix(".00")
        return f"{v:,} ({m_str}M)"
    if v >= 1_000:
        return f"{v:,} ({round(v / 1e3)}k)"
    return f"{v:,}"


def _row_usage_dict(row_d):
    if not isinstance(row_d, dict):
        return None
    u_d = row_d.get("usage")
    if isinstance(u_d, dict) and any(
        k in u_d for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "cached_input_tokens")
    ):
        return u_d
    if any(
        row_d.get(k) is not None
        for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens", "cached_input_tokens")
    ):
        out_u = {
            "input_tokens": int(row_d.get("input_tokens") or 0),
            "output_tokens": int(row_d.get("output_tokens") or 0),
        }
        if row_d.get("cached_input_tokens") is not None:
            out_u["cached_input_tokens"] = int(row_d.get("cached_input_tokens") or 0)
        if row_d.get("cache_read_input_tokens") is not None:
            out_u["cache_read_input_tokens"] = int(row_d.get("cache_read_input_tokens") or 0)
        if row_d.get("cache_creation_input_tokens") is not None:
            out_u["cache_creation_input_tokens"] = int(row_d.get("cache_creation_input_tokens") or 0)
        return out_u
    return None


_REALPATH_CACHE = globals().get("_REALPATH_CACHE") if isinstance(globals().get("_REALPATH_CACHE"), dict) else {}
_STATE_FILE_MEM_CACHE = globals().get("_STATE_FILE_MEM_CACHE") if isinstance(globals().get("_STATE_FILE_MEM_CACHE"), dict) else {}
_STATE_FILE_MEM_LOCK = globals().get("_STATE_FILE_MEM_LOCK") or threading.Lock()


def _read_state_file_cached(st_candidate: Path, se_mod):
    """Read & parse steward-cockpit-state.json once per (mtime_ns, size) instead of parsing 7MB+ twice per poll."""
    if st_candidate.is_dir():
        raise OSError("state file is a directory")
    in_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    st_stat = st_candidate.stat()
    sig = (st_stat.st_mtime_ns, st_stat.st_size)
    ckey = str(st_candidate)
    if not in_pytest:
        with _STATE_FILE_MEM_LOCK:
            hit = _STATE_FILE_MEM_CACHE.get(ckey)
            if hit is not None and hit[0] == sig:
                return hit[1]
    lock_ctx = se_mod._STATE_LOCK if st_candidate == Path(se_mod.STATE_FILE) else None
    if lock_ctx is not None:
        with lock_ctx:
            raw_st_txt = st_candidate.read_text(encoding="utf-8")
    else:
        raw_st_txt = st_candidate.read_text(encoding="utf-8")
    if "\x00" in raw_st_txt:
        raise ValueError("null byte in state file")
    parsed_st = json.loads(raw_st_txt)
    if not isinstance(parsed_st, dict):
        raise ValueError("state file root is not a JSON object")
    if not in_pytest:
        with _STATE_FILE_MEM_LOCK:
            if len(_STATE_FILE_MEM_CACHE) > 8:
                _STATE_FILE_MEM_CACHE.clear()
            _STATE_FILE_MEM_CACHE[ckey] = (sig, parsed_st)
    return parsed_st


def _realpath_fast(p):
    s = str(p or "")
    if "PYTEST_CURRENT_TEST" in os.environ:
        return os.path.realpath(s)
    hit = _REALPATH_CACHE.get(s)
    if hit is not None:
        return hit
    res = os.path.realpath(s)
    if len(_REALPATH_CACHE) > 4096:
        _REALPATH_CACHE.clear()
    _REALPATH_CACHE[s] = res
    return res


def _usage_rollup_fresh(cdir, estate=None, *, lock_timeout: float = 5.0, project_id=None):
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
        _backfill_usage_estimate, _read_all_state, _usage_snapshot, estimate_list_price_usd,
        fmt_usage_cost_text, infer_subscription_cli, load_usage_baseline)
    lock_busy = False
    backing_unreadable = False
    quarantined_count = 0
    if estate is None:
        from steward_cockpit import steward_engine as _se_mod
        import paths as _p_reloc
        if _se_mod.STATE_FILE == _se_mod.HERE / "proto-state.json" and "PYTEST_CURRENT_TEST" not in os.environ:
            try:
                _se_mod.relocate_state(_p_reloc.data_dir() / "steward-cockpit-state.json")
            except Exception:
                pass
        st_candidate = Path(_se_mod.STATE_FILE)
        if (
            st_candidate == _se_mod.HERE / "proto-state.json"
            and "ANCHOR_DATA_DIR" in os.environ
            and (_p_reloc.data_dir() / "steward-cockpit-state.json").exists()
        ):
            st_candidate = _p_reloc.data_dir() / "steward-cockpit-state.json"
        if st_candidate.exists():
            try:
                estate = _read_state_file_cached(st_candidate, _se_mod)
            except (OSError, ValueError, TypeError):
                backing_unreadable = True
                estate = {}
        else:
            estate = _read_all_state()
    try:
        baseline_doc = load_usage_baseline(strict=True)
    except (OSError, ValueError, TypeError):
        backing_unreadable = True
        baseline_doc = {}
    stew, term = zero(), zero()
    cdir_str = str(cdir or "").strip()
    cdir_is_dir = bool(cdir_str and os.path.isdir(cdir_str))
    cdir_n = _realpath_fast(cdir_str) if cdir_str else ""
    discovered = campaign.discover_efforts(cdir_n) if cdir_is_dir else []
    allowed_roots = ({cdir_n} | {_realpath_fast(str(Path(cdir_n) / e["rel"])) for e in discovered if e.get("rel")}) if discovered else None
    for key, entry in (estate or {}).items():
        if not cdir_n or not isinstance(entry, dict):
            continue
        base = _realpath_fast(key.split("||")[0])
        # exact boundary, not a string prefix: '.../foo' must not match '.../foobar'
        if base != cdir_n and not base.startswith(cdir_n + os.sep):
            continue
        if allowed_roots is not None and base != cdir_n and not any(base == r or base.startswith(r + os.sep) for r in allowed_roots if r != cdir_n):
            continue
        raw = entry.get("usage")
        u = _backfill_usage_estimate(_usage_snapshot(raw), raw, entry.get("model_policy"))
        eng_live = ENGINES.get(key)
        if eng_live is not None and getattr(eng_live, "busy", False) and isinstance(getattr(eng_live, "_inflight_claude_usage", None), dict):
            try:
                inf_usd, inf_turns, inf_tok = eng_live._inflight_usage_estimate()
                if inf_tok > 0:
                    u["tokens"] = int(u.get("tokens") or 0) + inf_tok
                    u["estimated_spend"] = round(float(u.get("estimated_spend") or 0.0) + inf_usd, 4)
                    u["estimated_turns"] = int(u.get("estimated_turns") or 0) + inf_turns
                    u["unpriced_turns"] = int(u.get("unpriced_turns") or 0) + max(1, inf_turns)
            except Exception:
                pass
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
    jobs = zero()
    jobs["count"], jobs["unknown"] = 0, 0
    children = zero()
    children["count"], children["unknown"] = 0, 0
    seats = zero()
    seats["count"], seats["unknown"] = 0, 0
    resolved_pid, folder_path = None, None
    rows = []
    try:
        import usage_capture as _uc
        import usage_index as _ui
        if cdir_str:
            resolved_pid, folder_path = _uc.resolve_project(cdir_str)
        eff_pid = project_id or resolved_pid
        if not eff_pid and cdir_str:
            if not cdir_is_dir:
                eff_pid = cdir_str
            else:
                cand_name = Path(cdir_str).name
                if _ui.index_path(cand_name).exists() or (_ui.index_dir() / f"{_ui._safe_id(cand_name)}.meta.json").exists():
                    eff_pid = cand_name
        if eff_pid:
            if hasattr(_ui, "inspect_project_index"):
                insp = _ui.inspect_project_index(eff_pid, lock_timeout=lock_timeout)
                rows = list(insp.get("rows") or [])
                quarantined_count = int(insp.get("quarantined_count") or 0)
            else:
                rows = _ui.load_rows(eff_pid)
    except Exception as exc:
        try:
            import usage_index as _ui_err
            lock_cls = getattr(_ui_err, "LockBusyError", TimeoutError)
            unread_cls = getattr(_ui_err, "IndexUnreadableError", OSError)
        except Exception:
            lock_cls = TimeoutError
            unread_cls = OSError
        if isinstance(exc, (lock_cls, TimeoutError)):
            lock_busy = True
        elif isinstance(exc, (unread_cls, OSError, ValueError)):
            backing_unreadable = True
        rows = []
    else:
        eff_pid = locals().get("eff_pid")
    eff_pid = locals().get("eff_pid") or project_id or resolved_pid
    owned = {row.get("engine_session_uuid") for row in rows
             if isinstance(row, dict) and row.get("source") == "job" and row.get("engine_session_uuid")}
    owned |= {row.get("native_id") for row in rows
              if isinstance(row, dict) and row.get("source") == "subagent" and row.get("native_id")}
    cdir_c = os.path.normcase(cdir_n) if cdir_n else ""
    cdir_prefix = (cdir_c.rstrip(os.sep) + os.sep) if cdir_c else ""

    def in_scope(scope):
        if not cdir_is_dir:
            return True
        return isinstance(scope, str) and (scope == cdir_c or scope.startswith(cdir_prefix))

    def _norm_scope_val(val):
        if not isinstance(val, str) or not val.strip():
            return None
        return os.path.normcase(_realpath_fast(val))

    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("source") == "subagent":
            row_sc = row.get("scope") or _norm_scope_val(row.get("effort_dir"))
            if row_sc:
                if not in_scope(row_sc):
                    continue
            elif not in_scope(row.get("folder_scope")):
                continue
            tokens, cost = row.get("tokens"), row.get("cost_usd")
            children["count"] += 1
            if number(tokens):
                children["tokens"] += tokens
            if number(row.get("duration_ms")):
                children["secs"] += row["duration_ms"] / 1000
            if row.get("usage_state") == "unknown":
                children["unknown"] += 1
                children["_tokens_unknown"] += 1
                children["_cost_unknown"] += 1
            elif (row.get("usage_state") == "measured" and number(cost)) or (number(cost) and cost > 0):
                children["reported_spend"] += cost
                children["_cost_known"] += 1
                children["_tokens_known"] += 1
            else:
                children["unpriced_turns"] += 1
                children["_tokens_known"] += 1
                children["_cost_unknown"] += 1
                c_fam = str(row.get("cli") or "").strip().lower()
                c_mod = row.get("model") or (_FAMILY_DEFAULT_MODELS.get(c_fam) if c_fam else "claude-opus-4-6")
                est_c = estimate_list_price_usd(c_mod, _row_usage_dict(row))
                if est_c is None and number(tokens) and tokens > 0:
                    est_c = estimate_list_price_usd(
                        c_mod,
                        {
                            "input_tokens": int(tokens * 0.95),
                            "cached_input_tokens": int(tokens * 0.85),
                            "output_tokens": max(1, int(tokens * 0.05)),
                        },
                    )
                if est_c is not None:
                    children["estimated_spend"] += est_c
                    children["estimated_turns"] += 1
            stamp = row.get("recorded_at")
            if isinstance(stamp, str) and stamp:
                children["usage_updated_at"] = max(children["usage_updated_at"] or stamp, stamp)
            continue
        if row.get("source") not in ("job", "seat"):
            continue
        eff_sc = _norm_scope_val(row.get("effort_dir"))
        if not (in_scope(row.get("scope")) or (eff_sc and in_scope(eff_sc)) or in_scope(row.get("folder_scope"))):
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
        if (state == "measured" and number(cost)) or (state not in ("unknown", "unpriced", "unmeasured") and number(cost) and cost > 0):
            b["reported_spend"] += cost
            b["_cost_known"] += 1
            b["_tokens_known"] += 1
        elif state == "unpriced" or (state != "unknown" and number(tokens) and tokens > 0):
            b["unpriced_turns"] += 1
            b["_cost_unknown"] += 1
            b["_tokens_known"] += 1
            row_fam = str(row.get("cli") or "").strip().lower()
            row_mod = row.get("model") or (_FAMILY_DEFAULT_MODELS.get(row_fam) if row_fam else "claude-opus-5-5")
            est = estimate_list_price_usd(row_mod, _row_usage_dict(row))
            if est is None and number(tokens) and tokens > 0:
                est = estimate_list_price_usd(
                    row_mod,
                    {
                        "input_tokens": int(tokens * 0.95),
                        "cached_input_tokens": int(tokens * 0.85),
                        "output_tokens": max(1, int(tokens * 0.05)),
                    },
                )
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
        elif state == "unmeasured":
            b["_tokens_known"] += 1
        else:
            b["unknown"] += 1
            b["_cost_unknown"] += 1
            b["_tokens_unknown"] += 1
        stamp = row.get("recorded_at")
        if isinstance(stamp, str) and stamp:
            b["usage_updated_at"] = max(b["usage_updated_at"] or stamp, stamp)
    try:
        roots_for_jobs = allowed_roots if allowed_roots is not None else ({cdir_n} if cdir_n else set())
        effort_job_ids: set[str] = set()
        for rdir in roots_for_jobs:
            cj_file = Path(rdir) / ".ecgberht" / "code-jobs.json"
            if cj_file.is_file():
                cj_data = json.loads(cj_file.read_text(encoding="utf-8"))
                if isinstance(cj_data, dict):
                    effort_job_ids.update(str(k) for k in cj_data.keys() if k)
        if effort_job_ids:
            already_indexed_jobs = {
                str(r.get("job_id") or "")
                for r in rows
                if isinstance(r, dict) and r.get("source") == "job" and (in_scope(r.get("scope")) or in_scope(r.get("folder_scope")))
            }
            for ekey, eentry in (estate or {}).items():
                if "anchor-code-jobs" not in ekey.lower() or not isinstance(eentry, dict):
                    continue
                ebase_name = Path(ekey.split("||")[0]).name
                if ebase_name not in effort_job_ids or ebase_name in already_indexed_jobs:
                    continue
                j_raw = eentry.get("usage")
                j_live = ENGINES.get(ekey)
                ju = _backfill_usage_estimate(
                    _usage_snapshot(j_raw), j_raw, eentry.get("model_policy"),
                    include_inflight=bool(j_live is not None and getattr(j_live, "busy", False)),
                )
                jobs["count"] += 1
                for field in numeric_fields:
                    jobs[field] += ju[field]
                if ju["reported_spend"] > 0:
                    jobs["_cost_known"] += 1
                    jobs["_tokens_known"] += 1
                elif ju["unpriced_turns"] > 0 or ju["tokens"] > 0:
                    jobs["_cost_unknown"] += 1
                    jobs["_tokens_known"] += 1
                    j_fam = infer_subscription_cli(eentry.get("cli"), (j_raw or {}).get("usage_source") if isinstance(j_raw, dict) else None)
                    if j_fam:
                        jobs["_sub_unpriced"] += max(1, ju["unpriced_turns"])
                        if j_fam not in jobs["_sub_clis"]:
                            jobs["_sub_clis"].append(j_fam)
                    else:
                        jobs["_other_unpriced"] += max(1, ju["unpriced_turns"])
                else:
                    jobs["unknown"] += 1
                    jobs["_cost_unknown"] += 1
                    jobs["_tokens_unknown"] += 1
                j_upd = ju.get("usage_updated_at")
                if isinstance(j_upd, str) and j_upd:
                    jobs["usage_updated_at"] = max(jobs["usage_updated_at"] or j_upd, j_upd)
    except Exception:
        pass
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
    matched_floor = None
    if isinstance(baseline_doc, dict) and baseline_doc:
        raw_floors = baseline_doc.get("floors") if isinstance(baseline_doc.get("floors"), dict) else baseline_doc
        norm_floors = {}
        for fk, fv in raw_floors.items():
            if not isinstance(fv, dict):
                continue
            fk_s = str(fk)
            if "::" in fk_s:
                p_part, d_part = fk_s.split("::", 1)
                nk = p_part.strip().lower() + "::" + d_part.replace("\\", "/").rstrip("/").lower()
            else:
                nk = fk_s.replace("\\", "/").rstrip("/").lower()
            norm_floors[nk] = fv
        if norm_floors:
            raw_norm = cdir_str.replace("\\", "/").rstrip("/").lower()
            real_norm = str(cdir_n or "").replace("\\", "/").rstrip("/").lower()
            pid_low = str(eff_pid or "").strip().lower()
            cand_keys = []
            if pid_low and real_norm:
                cand_keys.append(f"{pid_low}::{real_norm}")
            if pid_low and raw_norm and raw_norm != real_norm:
                cand_keys.append(f"{pid_low}::{raw_norm}")
            if pid_low and folder_path:
                fp_norm = str(_realpath_fast(folder_path)).replace("\\", "/").rstrip("/").lower()
                if real_norm == fp_norm:
                    cand_keys.append(f"{pid_low}::")
                elif real_norm.startswith(fp_norm + "/"):
                    cand_keys.append(f"{pid_low}::{real_norm[len(fp_norm) + 1:]}")
            elif pid_low and not cdir_str:
                cand_keys.append(f"{pid_low}::")
            if real_norm:
                cand_keys.append(real_norm)
            if raw_norm and raw_norm != real_norm:
                cand_keys.append(raw_norm)
            for ck in cand_keys:
                if ck in norm_floors:
                    matched_floor = dict(norm_floors[ck])
                    break
            if matched_floor:
                for fk_num, fv_num in matched_floor.items():
                    if fk_num in numeric_fields and number(fv_num):
                        if total[fk_num] < fv_num:
                            total[fk_num] = fv_num
                if total["reported_spend"] > 0:
                    total["_cost_known"] = max(1, total["_cost_known"])
                if total["unpriced_turns"] > 0:
                    total["_cost_unknown"] = max(1, total["_cost_unknown"])
                if total["tokens"] > 0:
                    total["_tokens_known"] = max(1, total["_tokens_known"])
    private = ("_cost_known", "_cost_unknown", "_tokens_known", "_tokens_unknown",
               "_tokens_partial", "_sub_unpriced", "_other_unpriced", "_sub_clis")
    for bucket in (stew, term, jobs, children, seats, total):
        bucket["reported_spend"] = round(bucket["reported_spend"], 4)
        bucket["estimated_spend"] = round(bucket["estimated_spend"], 4)
        bucket["combined_spend"] = round(bucket["reported_spend"] + bucket["estimated_spend"], 4)
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
    twc_rep = round(sum(b["reported_spend"] for b in (total, jobs, children, seats)), 4)
    twc_est = round(sum(b["estimated_spend"] for b in (total, jobs, children, seats)), 4)
    total_with_children = {
        "tokens": int(sum(b["tokens"] for b in (total, jobs, children, seats))),
        "reported_spend": twc_rep,
        "estimated_spend": twc_est,
        "combined_spend": round(twc_rep + twc_est, 4),
        "secs": round(sum(b["secs"] for b in (total, jobs, children, seats)), 4),
        "turns": int(
            total["turns"]
            + max(jobs["turns"], jobs["count"])
            + max(children["turns"], children["count"])
            + max(seats["turns"], seats["count"])
        ),
        "unpriced_turns": int(sum(b["unpriced_turns"] for b in (total, jobs, children, seats))),
        "estimated_turns": int(sum(b["estimated_turns"] for b in (total, jobs, children, seats))),
        "unknown": int(jobs.get("unknown", 0) + children.get("unknown", 0) + seats.get("unknown", 0)),
    }
    roll = {
        "steward": stew,
        "terms": term,
        "jobs": jobs,
        "children": children,
        "seats": seats,
        "total": total,
        "total_with_children": total_with_children,
        "quarantined_count": quarantined_count,
    }
    if matched_floor is not None:
        roll["baseline_floor"] = matched_floor
    if lock_busy:
        msg = "Usage index lock busy \u2014 retry"
        roll.update({
            "ok": False,
            "failure_state": "dependency-slow-or-killed",
            "spend_state": "dependency-slow-or-killed",
            "state": "unknown",
            "pill_label": msg,
            "message": msg,
        })
        return roll
    if backing_unreadable:
        msg = "Spend unreadable (unknown) \u2014 inspect usage_index"
        roll.update({
            "ok": False,
            "failure_state": "backing-store-unreadable",
            "spend_state": "backing-store-unreadable",
            "state": "unknown",
            "pill_label": msg,
            "message": msg,
        })
        return roll
    roll["ok"] = True
    compact_tok = _fmt_compact_tok(total_with_children["tokens"])
    dur_part = f" \u00b7 {round(total_with_children['secs'] / 60)}m" if total_with_children["secs"] >= 60 else ""
    if total_with_children["combined_spend"] > 0:
        tok_part = f" \u00b7 {compact_tok} tok" if total_with_children["tokens"] > 0 else ""
        pill_lbl = f"Total ${total_with_children['combined_spend']:,.2f}{tok_part}{dur_part} \u25be"
    elif total_with_children["tokens"] > 0 or total_with_children["unpriced_turns"] > 0:
        pill_lbl = f"Unpriced \u00b7 {compact_tok if total_with_children['tokens'] > 0 else '0'} tok{dur_part} \u25be"
    else:
        pill_lbl = "No spend recorded yet"
    roll["pill_label"] = pill_lbl
    if quarantined_count > 0:
        warn_msg = f"Corrupt usage record quarantined ({quarantined_count} skipped)"
        roll["failure_state"] = "dependency-returns-garbage"
        roll["spend_state"] = "dependency-returns-garbage"
        roll["warning"] = warn_msg
        roll["message"] = warn_msg
    elif total_with_children["tokens"] == 0 and total_with_children["combined_spend"] == 0 and total_with_children["unpriced_turns"] == 0:
        roll["failure_state"] = "empty-but-valid"
        roll["spend_state"] = "empty-but-valid"
        roll["message"] = "No spend recorded yet"
    elif total_with_children["combined_spend"] == 0 and (total_with_children["tokens"] > 0 or total_with_children["unpriced_turns"] > 0):
        roll["failure_state"] = "dependency-missing"
        roll["spend_state"] = "dependency-missing"
        roll["message"] = pill_lbl
    else:
        roll["failure_state"] = None
        roll["spend_state"] = "ok"
        roll["message"] = pill_lbl
    return roll


def spend_http_response(cdir, estate=None, *, lock_timeout: float = 5.0, qs=None, project_id=None) -> tuple[dict, int]:
    """Wave 5 5-state failure contract endpoint for cockpit spend."""
    qs = qs if isinstance(qs, dict) else {}
    eff_timeout = lock_timeout
    if qs.get("lock_timeout") not in (None, ""):
        try:
            eff_timeout = max(0.01, float(qs["lock_timeout"]))
        except (TypeError, ValueError):
            eff_timeout = lock_timeout
    eff_pid = project_id or qs.get("project_id") or qs.get("pid") or None
    roll = _usage_rollup_fresh(cdir, estate=estate, lock_timeout=eff_timeout, project_id=eff_pid)
    if roll.get("ok") is False:
        if roll.get("failure_state") == "dependency-slow-or-killed":
            return {
                "ok": False,
                "failure_state": "dependency-slow-or-killed",
                "state": "unknown",
                "message": "Usage index lock busy \u2014 retry",
            }, 504
        return {
            "ok": False,
            "failure_state": "backing-store-unreadable",
            "state": "unknown",
            "message": "Spend unreadable (unknown) \u2014 inspect usage_index",
        }, 500
    return roll, 200


_GLOBAL_USAGE_CACHE = globals().get("_GLOBAL_USAGE_CACHE") if isinstance(globals().get("_GLOBAL_USAGE_CACHE"), dict) else {}; _GLOBAL_USAGE_LOCK = globals().get("_GLOBAL_USAGE_LOCK") or threading.Lock()
_GLOBAL_USAGE_COMPUTE_LOCK = globals().get("_GLOBAL_USAGE_COMPUTE_LOCK") or threading.Lock()
_LEDGER_DOC_CACHE = globals().get("_LEDGER_DOC_CACHE") if isinstance(globals().get("_LEDGER_DOC_CACHE"), dict) else {}
_USAGE_INDEX_CACHE = globals().get("_USAGE_INDEX_CACHE") if isinstance(globals().get("_USAGE_INDEX_CACHE"), dict) else {}
_CLAUDE_AGENT_USAGE_CACHE = globals().get("_CLAUDE_AGENT_USAGE_CACHE") if isinstance(globals().get("_CLAUDE_AGENT_USAGE_CACHE"), dict) else {}

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
    canon_by_folder = {}
    pid_alias = {}
    folder_to_proj = []
    # Sort active projects ahead of archived/retired so canonical folder ownership prefers active projects
    sorted_projs = sorted(
        [p for p in projects_list if isinstance(p, dict) and p.get("id")],
        key=lambda p: (1 if p.get("status") in ("archived", "retired", "future") else 0, -len(str(p.get("name") or ""))),
    )
    for p in sorted_projs:
        pid = str(p["id"])
        pname = str(p.get("name") or pid)
        fp = str(p.get("folder_path") or "").strip()
        if pname.startswith("__healthcheck__"):
            continue
        proj_by_id[pid] = {"project_id": pid, "name": pname, "folder_path": fp}
        if fp and fp != ".":
            try:
                norm_fp = os.path.normcase(_realpath_fast(fp))
                if norm_fp in canon_by_folder:
                    c_pid, c_name = canon_by_folder[norm_fp]
                    pid_alias[pid] = (c_pid, c_name)
                else:
                    canon_by_folder[norm_fp] = (pid, pname)
                    folder_to_proj.append((len(norm_fp), norm_fp, pid, pname))
            except Exception:
                pass
    folder_to_proj.sort(reverse=True)

    def canon_proj(pid_val, pname_val):
        if pid_val and pid_val in pid_alias:
            return pid_alias[pid_val]
        return pid_val, pname_val

    code_job_to_sdir = {}
    cj_index_paths = []
    try:
        cj_index_paths.append(_paths.code_jobs_dir() / "jobs-index.jsonl")
    except Exception:
        pass
    try:
        leg_cj_p = _paths.legacy_code_jobs_dir() / "jobs-index.jsonl"
        if leg_cj_p not in cj_index_paths:
            cj_index_paths.append(leg_cj_p)
    except Exception:
        pass
    for cj_idx in cj_index_paths:
        if not cj_idx.is_file():
            continue
        try:
            for raw_ln in cj_idx.read_text(encoding="utf-8").splitlines():
                raw_ln = raw_ln.strip()
                if not raw_ln:
                    continue
                try:
                    obj = json.loads(raw_ln)
                except ValueError:
                    continue
                if not isinstance(obj, dict):
                    continue
                sdir_val = str(obj.get("steward_dir") or "").strip()
                if not sdir_val:
                    continue
                jid_val = str(obj.get("job") or obj.get("job_id") or obj.get("id") or "").strip()
                if jid_val:
                    code_job_to_sdir[jid_val] = sdir_val
                wt_val = str(obj.get("worktree") or "").strip()
                if wt_val:
                    try:
                        code_job_to_sdir[os.path.normcase(_realpath_fast(wt_val))] = sdir_val
                    except Exception:
                        pass
                    code_job_to_sdir[wt_val.replace("\\", "/").rstrip("/").lower()] = sdir_val
        except Exception:
            pass

    def _looks_like_path(s: str) -> bool:
        return ("/" in s or "\\" in s or ":" in s)

    def resolve_code_job_sdir(val):
        if not val or not code_job_to_sdir:
            return None
        s = str(val).strip()
        if not s:
            return None
        for prefix in ("job:", "foreman:", "code:"):
            if s.startswith(prefix) and s[len(prefix):] in code_job_to_sdir:
                return code_job_to_sdir[s[len(prefix):]]
        if s in code_job_to_sdir:
            return code_job_to_sdir[s]
        if _looks_like_path(s):
            try:
                nr = os.path.normcase(_realpath_fast(s))
                if nr in code_job_to_sdir:
                    return code_job_to_sdir[nr]
            except Exception:
                pass
        s_norm = s.replace("\\", "/").rstrip("/")
        s_low = s_norm.lower()
        if s_low in code_job_to_sdir:
            return code_job_to_sdir[s_low]
        marker = "anchor-code-jobs/"
        pos = s_low.find(marker)
        if pos >= 0:
            tail = s_norm[pos + len(marker):]
            seg = tail.split("/", 1)[0].strip()
            if seg and seg in code_job_to_sdir:
                return code_job_to_sdir[seg]
        return None

    _match_proj_memo = {}

    def _match_folder_direct(folder):
        if not folder:
            return None, None
        s = str(folder).strip()
        if not s or not _looks_like_path(s):
            return None, None
        try:
            nf = os.path.normcase(_realpath_fast(s))
        except Exception:
            return None, None
        for _, norm_fp, pid, pname in folder_to_proj:
            if nf == norm_fp or nf.startswith(norm_fp.rstrip(os.sep) + os.sep):
                return pid, pname
        return None, None

    def match_proj(folder):
        if not folder:
            return None, None
        key_f = str(folder)
        hit_m = _match_proj_memo.get(key_f)
        if hit_m is not None:
            return hit_m
        pid_m, pname_m = _match_folder_direct(key_f)
        if not pid_m:
            mapped_sdir = resolve_code_job_sdir(key_f)
            if mapped_sdir:
                pid_m, pname_m = _match_folder_direct(mapped_sdir)
        res_m = (pid_m, pname_m)
        _match_proj_memo[key_f] = res_m
        return res_m

    sid_map = {}
    lsu_by_sid = {}
    inflight_by_sid = {}
    estate_cj_fallbacks = []
    from steward_cockpit import steward_engine as _se_mod
    if _se_mod.STATE_FILE == _se_mod.HERE / "proto-state.json" and "PYTEST_CURRENT_TEST" not in os.environ:
        try:
            _se_mod.relocate_state(_paths.data_dir() / "steward-cockpit-state.json")
            estate = _read_all_state()
        except Exception:
            pass
    for skey, entry in estate.items():
        if not isinstance(entry, dict):
            continue
        base_dir = skey.split("||")[0]
        if "anchor-hc-" in base_dir or "__healthcheck__" in base_dir:
            continue
        pid, pname = match_proj(base_dir)
        if not pid and ("Temp" in base_dir or "scratchpad" in base_dir):
            continue
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
            sid_str = str(entry["session_id"])
            sid_map[sid_str] = (fam, mod, pid, pname, base_dir)
            raw_u = entry.get("usage") if isinstance(entry.get("usage"), dict) else {}
            lsu = raw_u.get("last_session_usage")
            if isinstance(lsu, dict) and (int(lsu.get("input_tokens") or 0) > 0 or int(lsu.get("output_tokens") or 0) > 0):
                lsu_by_sid[sid_str] = (lsu, str(raw_u.get("usage_updated_at") or ""), fam, mod, pid, pname, base_dir)
            cks = raw_u.get("usage_checkpoints")
            if isinstance(cks, dict):
                for ck_id, ck in cks.items():
                    if isinstance(ck, dict) and not ck.get("invalid") and ck.get("finalized") is not True and isinstance(ck.get("counts"), dict):
                        inflight_by_sid.setdefault(sid_str, []).append((ck, fam, mod, pid, pname))
        if "anchor-code-jobs" in base_dir.lower() and isinstance(entry.get("usage"), dict):
            raw_cj_u = entry["usage"]
            cj_tok = int(raw_cj_u.get("tokens") or 0)
            cj_rep = float(raw_cj_u.get("reported_spend") or raw_cj_u.get("spend") or 0.0)
            if cj_tok > 0 or cj_rep > 0:
                mp = entry.get("model_policy") if isinstance(entry.get("model_policy"), dict) else {}
                fam = entry.get("cli") or mp.get("family") or "claude"
                mod = mp.get("model_served") or mp.get("model")
                cj_name = Path(base_dir).name
                estate_cj_fallbacks.append((
                    str(entry.get("session_id") or ""),
                    cj_name,
                    str(fam).lower(),
                    mod,
                    pid,
                    pname,
                    {
                        "key": f"estate-code-job:{cj_name}",
                        "source": "job",
                        "native_id": cj_name,
                        "cli": str(fam).lower(),
                        "model": mod,
                        "tokens": cj_tok,
                        "cost_usd": cj_rep if cj_rep > 0 else None,
                        "recorded_at": str(raw_cj_u.get("usage_updated_at") or ""),
                    },
                ))

    seen_keys = set()
    records = []
    try:
        import usage_ledger as _ul
    except Exception:
        _ul = None

    if _ul is not None:
        ledger_dir = _ul.ledger_dir() if hasattr(_ul, "ledger_dir") else (_paths.data_dir() / ".anchor" / "usage_ledger")
        extra_sids = []
        ledger_stat_by_stem = {}
        ledger_dir_exists = ledger_dir.is_dir()
        if ledger_dir_exists:
            try:
                with os.scandir(ledger_dir) as it:
                    for ent in it:
                        if ent.name.lower().endswith(".json") and not ent.name.startswith("."):
                            stem = ent.name[:-5]
                            try:
                                st = ent.stat()
                                ledger_stat_by_stem[stem] = (st.st_mtime_ns, st.st_size, ent.path)
                            except OSError:
                                pass
                            if stem not in sid_map:
                                extra_sids.append(stem)
            except Exception:
                ledger_dir_exists = False
        custom_load_ledger = getattr(_ul.load_ledger, "__module__", "") != "usage_ledger"
        if len(_LEDGER_DOC_CACHE) > 50000:
            _LEDGER_DOC_CACHE.clear()
        all_sid_items = list(sid_map.items()) + [(s, (None, None, None, None, None)) for s in extra_sids]
        for sid, (fam, mod, pid, pname, base_dir) in all_sid_items:
            if custom_load_ledger:
                doc = _ul.load_ledger(sid)
            else:
                safe_stem = _ul._safe_uuid(sid) if hasattr(_ul, "_safe_uuid") else str(sid or "")
                st_info = ledger_stat_by_stem.get(safe_stem)
                if st_info is None:
                    doc = _ul.load_ledger(sid) if not ledger_dir_exists else {"engine_session_uuid": str(sid or ""), "entries": {}}
                else:
                    mt_ns, fsize, fpath = st_info
                    cached_l = _LEDGER_DOC_CACHE.get(fpath)
                    if cached_l is not None and cached_l[0] == mt_ns and cached_l[1] == fsize:
                        doc = cached_l[2]
                    else:
                        try:
                            raw_l = json.loads(Path(fpath).read_text(encoding="utf-8"))
                            entries_l = raw_l.get("entries") if isinstance(raw_l, dict) else None
                            doc = {
                                "engine_session_uuid": (raw_l.get("engine_session_uuid") if isinstance(raw_l, dict) else None) or str(sid or ""),
                                "entries": entries_l if isinstance(entries_l, dict) else {},
                            }
                        except Exception:
                            doc = {"engine_session_uuid": str(sid or ""), "entries": {}}
                        _LEDGER_DOC_CACHE[fpath] = (mt_ns, fsize, doc)
            raw_entries = doc.get("entries") or {}
            max_line_cum_at = max(
                (
                    str(ev_item.get("recorded_at") or "")
                    for ek_item, ev_item in raw_entries.items()
                    if isinstance(ev_item, dict)
                    and not str(ek_item).startswith("agy-sync:")
                    and "cache_read_input_tokens" in (ev_item.get("usage") or {})
                ),
                default="",
            )
            es = sorted(raw_entries.items(), key=lambda kv: str((kv[1] or {}).get("recorded_at") or ""))
            prev_by_sess = {}
            for k, e in es:
                if not isinstance(e, dict):
                    continue
                if str(k).startswith("agy-sync:") and max_line_cum_at and str(e.get("recorded_at") or "") <= max_line_cum_at:
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
                is_per_turn_gemini = (
                    efam == "gemini"
                    and not str(k).startswith("agy-sync:")
                    and isinstance(u, dict)
                    and "cached_input_tokens" in u
                    and "cache_read_input_tokens" not in u
                )
                if is_per_turn_gemini and (src in ("steward-turn", "terminal-turn", None)):
                    prev_u, prev_tok = prev_by_sess.get(sess_key, (None, 0))
                    if isinstance(prev_u, dict):
                        in_t = int(u.get("input_tokens") or 0)
                        ca_t = int(u.get("cached_input_tokens") or 0)
                        out_t = int(u.get("output_tokens") or 0)
                        prev_by_sess[sess_key] = ({
                            "input_tokens": int(prev_u.get("input_tokens") or 0) + max(0, in_t - ca_t),
                            "cache_read_input_tokens": int(prev_u.get("cache_read_input_tokens") or prev_u.get("cached_input_tokens") or 0) + ca_t,
                            "output_tokens": int(prev_u.get("output_tokens") or 0) + out_t,
                        }, prev_tok + int(e.get("tokens") or 0))
                elif efam in ("chatgpt", "gemini") and (src in ("steward-turn", "terminal-turn", None)):
                    tok = int(e.get("tokens") or 0)
                    prev_u, prev_tok = prev_by_sess.get(sess_key, (None, 0))
                    if isinstance(u, dict) and isinstance(prev_u, dict):
                        in_c = int(u.get("input_tokens") or 0)
                        out_c = int(u.get("output_tokens") or 0)
                        ca_c = int(u.get("cached_input_tokens") or u.get("cache_read_input_tokens") or 0)
                        in_p = int(prev_u.get("input_tokens") or 0)
                        out_p = int(prev_u.get("output_tokens") or 0)
                        ca_p = int(prev_u.get("cached_input_tokens") or prev_u.get("cache_read_input_tokens") or 0)
                        if in_c >= in_p or out_c >= out_p or ca_c >= ca_p or (in_c + ca_c) > max(1, tok * 2):
                            delta_in = max(0, in_c - in_p)
                            delta_out = max(0, out_c - out_p)
                            delta_ca = max(0, ca_c - ca_p)
                            has_additive_ca = "cache_read_input_tokens" in u and "cached_input_tokens" not in u
                            delta_sum = delta_in + delta_out + (delta_ca if has_additive_ca else 0)
                            # tok in .anchor/usage_ledger is already the per-turn delta for steward-turn/terminal-turn;
                            # only subtract prev_tok when tok is a cumulative counter larger than the current cumulative input.
                            if tok >= prev_tok and prev_tok > 0 and tok >= in_c and delta_sum > 0 and tok > delta_sum:
                                e_copy["tokens"] = tok - prev_tok
                            elif delta_sum > 0 and (tok <= 0 or delta_sum < tok):
                                e_copy["tokens"] = delta_sum
                            if has_additive_ca:
                                e_copy["usage"] = {
                                    "input_tokens": delta_in,
                                    "output_tokens": delta_out,
                                    "cache_read_input_tokens": delta_ca,
                                }
                            else:
                                e_copy["usage"] = {
                                    "input_tokens": delta_in,
                                    "output_tokens": delta_out,
                                    "cached_input_tokens": delta_ca,
                                }
                    has_u = isinstance(u, dict) and (int(u.get("input_tokens") or 0) > 0 or int(u.get("output_tokens") or 0) > 0)
                    if has_u:
                        in_cur = int(u.get("input_tokens") or 0)
                        out_cur = int(u.get("output_tokens") or 0)
                        ca_cur = int(u.get("cached_input_tokens") or u.get("cache_read_input_tokens") or 0)
                        in_prv = int((prev_u or {}).get("input_tokens") or 0)
                        out_prv = int((prev_u or {}).get("output_tokens") or 0)
                        ca_prv = int((prev_u or {}).get("cached_input_tokens") or (prev_u or {}).get("cache_read_input_tokens") or 0)
                        has_add = "cache_read_input_tokens" in u and "cached_input_tokens" not in u
                        ck_key = "cache_read_input_tokens" if has_add else "cached_input_tokens"
                        if prev_u is None:
                            prev_by_sess[sess_key] = (u, tok if tok >= prev_tok else prev_tok)
                        elif in_cur >= in_prv or out_cur >= out_prv or ca_cur >= ca_prv or (in_cur + ca_cur) > max(1, tok * 2):
                            prev_by_sess[sess_key] = ({
                                "input_tokens": max(in_cur, in_prv),
                                "output_tokens": max(out_cur, out_prv),
                                ck_key: max(ca_cur, ca_prv),
                            }, tok if tok >= prev_tok else prev_tok)
                    elif tok > prev_tok:
                        prev_by_sess[sess_key] = (prev_u, tok)
                epid = e.get("project_id") or pid
                if epid == "unknown":
                    epid = None
                epname = (proj_by_id.get(epid) or {}).get("name") or pname
                if not epid:
                    for cand_loc in (e.get("effort_dir"), e.get("folder_path"), e.get("job_id"), e.get("native_id"), base_dir):
                        m_pid, m_name = match_proj(cand_loc)
                        if m_pid:
                            epid, epname = m_pid, m_name
                            break
                epid, epname = canon_proj(epid, epname)
                records.append((efam, emod, epid, epname, e_copy))
            # If last_session_usage in estate has strictly higher cumulative tokens than the last
            # ledger entry for this session (e.g., turns run after a turn-counter reset), include
            # the verified un-ledgered delta at usage_updated_at.
            if sid in lsu_by_sid:
                lsu, lsu_at, lfam, lmod, lpid, lpname, _ = lsu_by_sid[sid]
                efam = str(lfam or fam or "claude").lower()
                if efam in ("chatgpt", "gemini"):
                    prev_u, _ = prev_by_sess.get(sid, (None, 0))
                    in_c = int(lsu.get("input_tokens") or 0)
                    out_c = int(lsu.get("output_tokens") or 0)
                    ca_c = int(lsu.get("cached_input_tokens") or lsu.get("cache_read_input_tokens") or 0)
                    in_p = int((prev_u or {}).get("input_tokens") or 0)
                    out_p = int((prev_u or {}).get("output_tokens") or 0)
                    ca_p = int((prev_u or {}).get("cached_input_tokens") or (prev_u or {}).get("cache_read_input_tokens") or 0)
                    if in_c >= in_p and out_c >= out_p and ca_c >= ca_p and (in_c > in_p or out_c > out_p or ca_c > ca_p):
                        delta_in = in_c - in_p
                        delta_out = out_c - out_p
                        delta_ca = ca_c - ca_p
                        has_additive_ca = "cache_read_input_tokens" in lsu and "cached_input_tokens" not in lsu
                        delta_tok = delta_in + delta_out + (delta_ca if has_additive_ca else 0)
                        delta_u = {
                            "input_tokens": delta_in,
                            "output_tokens": delta_out,
                            ("cache_read_input_tokens" if has_additive_ca else "cached_input_tokens"): delta_ca,
                        }
                        records.append((efam, lmod or mod, lpid or pid, lpname or pname, {
                            "session_id": sid,
                            "cli": efam,
                            "model": lmod or mod,
                            "tokens": delta_tok,
                            "usage": delta_u,
                            "recorded_at": lsu_at,
                            "source": "steward-turn",
                        }))
            if sid in inflight_by_sid:
                for ck, ifam, imod, ipid, ipname in inflight_by_sid[sid]:
                    efam = str(ifam or fam or "claude").lower()
                    counts = ck.get("counts") or {}
                    tok_inf = int(counts.get("input_tokens") or 0) + int(counts.get("output_tokens") or 0)
                    if tok_inf > 0:
                        records.append((efam, imod or mod, ipid or pid, ipname or pname, {
                            "session_id": sid,
                            "cli": efam,
                            "model": imod or mod,
                            "tokens": tok_inf,
                            "usage": dict(counts),
                            "recorded_at": str(ck.get("updated_at") or ""),
                            "source": "steward-checkpoint",
                        }))

    try:
        import usage_index as _ui
    except Exception:
        _ui = None

    seen_child_ids = set()
    if _ui is not None:
        index_pids = list(proj_by_id.keys())
        idx_d = _ui.index_dir()
        idx_stat_by_stem = {}
        idx_dir_exists = idx_d.is_dir()
        if idx_dir_exists:
            try:
                with os.scandir(idx_d) as it:
                    for ent in it:
                        if ent.name.lower().endswith(".jsonl") and not ent.name.startswith(".") and not ent.name.lower().endswith(".quarantine.jsonl"):
                            stem = ent.name[:-6]
                            try:
                                st = ent.stat()
                                idx_stat_by_stem[stem] = (st.st_mtime_ns, st.st_size, ent.path)
                            except OSError:
                                pass
                            if stem not in proj_by_id and not stem.startswith("__healthcheck__"):
                                index_pids.append(stem)
            except Exception:
                idx_dir_exists = False
        custom_load_rows = getattr(_ui.load_rows, "__module__", "") != "usage_index"
        if len(_USAGE_INDEX_CACHE) > 4096:
            _USAGE_INDEX_CACHE.clear()
        for pid_k in index_pids:
            pinfo = proj_by_id.get(pid_k)
            if custom_load_rows:
                idx_rows = _ui.load_rows(pid_k)
            else:
                safe_pid = _ui._safe_id(pid_k) if hasattr(_ui, "_safe_id") else str(pid_k or "")
                idx_st = idx_stat_by_stem.get(safe_pid)
                if idx_st is None:
                    idx_rows = _ui.load_rows(pid_k) if not idx_dir_exists else []
                else:
                    mt_ns, fsize, fpath = idx_st
                    cached_i = _USAGE_INDEX_CACHE.get(fpath)
                    if cached_i is not None and cached_i[0] == mt_ns and cached_i[1] == fsize:
                        idx_rows = cached_i[2]
                    else:
                        idx_rows = _ui.load_rows(pid_k)
                        _USAGE_INDEX_CACHE[fpath] = (mt_ns, fsize, idx_rows)
            for r in idx_rows:
                if not isinstance(r, dict):
                    continue
                esid = r.get("engine_session_uuid")
                if esid == "stub":
                    continue
                ukey = (esid, r.get("key"))
                if ukey in seen_keys:
                    continue
                seen_keys.add(ukey)
                if r.get("source") == "subagent" and r.get("native_id"):
                    seen_child_ids.add(str(r["native_id"]))
                sfam, smod, spid, spname, sbase = sid_map.get(str(esid or ""), (None, None, None, None, None))
                rfam = str(r.get("cli") or sfam or "claude").lower()
                rmod = r.get("model") or smod
                if pinfo is not None:
                    r_pid, r_pname = pid_k, pinfo["name"]
                else:
                    r_pid, r_pname = spid, spname
                    if not r_pid:
                        for cand_loc in (r.get("effort_dir"), r.get("folder_path"), r.get("job_id"), r.get("native_id"), r.get("key"), sbase):
                            m_pid, m_name = match_proj(cand_loc)
                            if m_pid:
                                r_pid, r_pname = m_pid, m_name
                                break
                cpid, cpname = canon_proj(r_pid, r_pname)
                records.append((rfam, rmod, cpid, cpname, r))

    if estate_cj_fallbacks:
        recorded_sids = {str(rec[4].get("session_id") or rec[4].get("engine_session_uuid") or "") for rec in records if isinstance(rec[4], dict)}
        recorded_jids = {str(rec[4].get("native_id") or rec[4].get("job_id") or "") for rec in records if isinstance(rec[4], dict)}
        for cj_sid, cj_name, cj_fam, cj_mod, cj_pid, cj_pname, cj_rec in estate_cj_fallbacks:
            if (cj_sid and cj_sid in recorded_sids) or (cj_name and cj_name in recorded_jids):
                continue
            cpid, cpname = canon_proj(cj_pid, cj_pname)
            records.append((cj_fam, cj_mod, cpid, cpname, cj_rec))

    if "ANCHOR_SIDECAR_DIR" in os.environ or "PYTEST_CURRENT_TEST" not in os.environ:
        try:
            import usage_capture as _uc_sc
            custom_claude_children = getattr(_uc_sc.claude_children, "__module__", "") != "usage_capture"
            sidecar_subagents_by_sid = {}
            if not custom_claude_children:
                sc_base = _paths.sidecar_root()
                if sc_base.is_dir():
                    direct_dirs = set()
                    slug_dirs = []
                    with os.scandir(sc_base) as it_b:
                        for ent_b in it_b:
                            if ent_b.is_dir():
                                direct_dirs.add(ent_b.name)
                                slug_dirs.append(ent_b.path)
                            elif ent_b.name.lower().endswith(".jsonl"):
                                sid_stem = ent_b.name[:-6]
                                sidecar_subagents_by_sid[sid_stem] = (str(sc_base), direct_dirs)
                    for sdir in sorted(slug_dirs):
                        try:
                            s_dirs = set()
                            s_jsonls = []
                            with os.scandir(sdir) as it_s:
                                for ent_s in it_s:
                                    if ent_s.is_dir():
                                        s_dirs.add(ent_s.name)
                                    elif ent_s.name.lower().endswith(".jsonl"):
                                        s_jsonls.append(ent_s.name[:-6])
                            if s_dirs and s_jsonls:
                                for sid_stem in s_jsonls:
                                    sidecar_subagents_by_sid.setdefault(sid_stem, (sdir, s_dirs))
                        except OSError:
                            continue
            if len(_CLAUDE_AGENT_USAGE_CACHE) > 4096:
                _CLAUDE_AGENT_USAGE_CACHE.clear()
            for sid_k, (sfam, smod, spid, spname, _) in sid_map.items():
                if not sid_k or str(sfam or "claude").lower() != "claude":
                    continue
                if custom_claude_children:
                    ch_list = _uc_sc.claude_children(sid_k) or []
                else:
                    sc_hit = sidecar_subagents_by_sid.get(str(sid_k))
                    if not sc_hit or str(sid_k) not in sc_hit[1]:
                        continue
                    sub_folder = Path(sc_hit[0]) / str(sid_k) / "subagents"
                    if not sub_folder.is_dir():
                        continue
                    ch_list = [
                        {"id": p.stem[len("agent-"):], "path": str(p), "parent": str(sid_k), "started": None}
                        for p in sorted(sub_folder.glob("agent-*.jsonl"))
                    ]
                for ch in ch_list:
                    if not isinstance(ch, dict):
                        continue
                    cid = str(ch.get("id") or ch.get("native_id") or "")
                    if not cid or cid in seen_child_ids:
                        continue
                    seen_child_ids.add(cid)
                    ch_u = ch
                    if ch.get("tokens") is None and ch.get("path"):
                        ch_path = str(ch["path"])
                        try:
                            ch_st = os.stat(ch_path)
                            ch_cached = _CLAUDE_AGENT_USAGE_CACHE.get(ch_path)
                            if ch_cached is not None and ch_cached[0] == ch_st.st_mtime_ns and ch_cached[1] == ch_st.st_size:
                                ch_u = ch_cached[2]
                            else:
                                ch_u = _uc_sc.claude_agent_usage(ch_path) or {}
                                _CLAUDE_AGENT_USAGE_CACHE[ch_path] = (ch_st.st_mtime_ns, ch_st.st_size, ch_u)
                        except OSError:
                            ch_u = _uc_sc.claude_agent_usage(ch_path) or {}
                    ch_tok = int(ch_u.get("tokens") or 0)
                    if ch_tok <= 0:
                        continue
                    ch_mod = ch_u.get("model") or ch.get("model") or smod
                    cpid, cpname = canon_proj(spid, spname)
                    records.append(("claude", ch_mod, cpid, cpname, {
                        "key": f"child:{sid_k}:{cid}",
                        "source": "subagent",
                        "native_id": cid,
                        "cli": "claude",
                        "model": ch_mod,
                        "tokens": ch_tok,
                        "usage": ch.get("usage") if isinstance(ch.get("usage"), dict) else None,
                        "recorded_at": str(ch.get("recorded_at") or ""),
                    }))
        except Exception:
            pass

    def normalize_model(fam, mod):
        m = str(mod or "").strip()
        if not m or m in ("best", "latest_supported", "<synthetic>", "False", "None"):
            return _FAMILY_DEFAULT_MODELS.get(fam, "claude-opus-5-5")
        return m

    def extract_io(r, tok):
        if any(r.get(k) is not None for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")):
            in_t = int(r.get("input_tokens") or 0)
            cr_t = int(r.get("cache_read_input_tokens") or 0)
            cc_t = int(r.get("cache_creation_input_tokens") or 0)
            ca_sub = int(r.get("cached_input_tokens") or 0)
            out_t = int(r.get("output_tokens") or 0)
            if cr_t > 0 or cc_t > 0:
                return in_t + cr_t + cc_t, cr_t, out_t
            if in_t > 0 or out_t > 0 or ca_sub > 0:
                return in_t, ca_sub, out_t
        u = r.get("usage")
        if isinstance(u, dict) and any(k in u for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")):
            in_t = int(u.get("input_tokens") or 0)
            cr_t = int(u.get("cache_read_input_tokens") or 0)
            cc_t = int(u.get("cache_creation_input_tokens") or 0)
            ca_sub = int(u.get("cached_input_tokens") or 0)
            out_t = int(u.get("output_tokens") or 0)
            if cr_t > 0 or cc_t > 0:
                return in_t + cr_t + cc_t, cr_t, out_t
            return in_t, ca_sub, out_t
        if tok > 0:
            return int(tok * 0.95), int(tok * 0.85), max(1, int(tok * 0.05))
        return 0, 0, 0

    price_table_usd = (prices.get("usd_per_million") if isinstance(prices, dict) else None) or {}

    def price_record(fam, eff_mod, r):
        c = r.get("cost_usd")
        reported = float(c) if isinstance(c, (int, float)) and not isinstance(c, bool) and c > 0 else 0.0
        if reported > 0:
            return reported, 0.0, reported
        rec_mod = normalize_model(fam, r.get("model")) if r.get("model") else eff_mod
        est = None
        if any(r.get(k) is not None for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")):
            top_u = {
                "input_tokens": int(r.get("input_tokens") or 0),
                "output_tokens": int(r.get("output_tokens") or 0),
            }
            if r.get("cached_input_tokens") is not None:
                top_u["cached_input_tokens"] = int(r.get("cached_input_tokens") or 0)
            if r.get("cache_read_input_tokens") is not None:
                top_u["cache_read_input_tokens"] = int(r.get("cache_read_input_tokens") or 0)
            if r.get("cache_creation_input_tokens") is not None:
                top_u["cache_creation_input_tokens"] = int(r.get("cache_creation_input_tokens") or 0)
            if any(v > 0 for v in top_u.values()):
                est = _se.estimate_list_price_usd(rec_mod, top_u, price_table=price_table_usd)
        if est is None:
            u = r.get("usage")
            if isinstance(u, dict) and any(k in u for k in ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")):
                in_t = int(u.get("input_tokens") or 0)
                cr_t = int(u.get("cache_read_input_tokens") or 0)
                cc_t = int(u.get("cache_creation_input_tokens") or 0)
                ca_sub = int(u.get("cached_input_tokens") or 0)
                out_t = int(u.get("output_tokens") or 0)
                if cr_t > 0 or cc_t > 0:
                    norm_u = {
                        "input_tokens": in_t,
                        "cache_read_input_tokens": cr_t,
                        "cache_creation_input_tokens": cc_t,
                        "output_tokens": out_t,
                    }
                else:
                    norm_u = {
                        "input_tokens": in_t,
                        "cached_input_tokens": ca_sub,
                        "output_tokens": out_t,
                    }
                est = _se.estimate_list_price_usd(rec_mod, norm_u, price_table=price_table_usd)
        if est is None:
            tok = int(r.get("tokens") or 0)
            if tok > 0:
                est = _se.estimate_list_price_usd(rec_mod, {
                    "input_tokens": int(tok * 0.95),
                    "cached_input_tokens": int(tok * 0.85),
                    "output_tokens": max(1, int(tok * 0.05)),
                }, price_table=price_table_usd)
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
            if isinstance(hit, tuple) and len(hit) == 2:
                if now - hit[0] < ttl:
                    return copy.deepcopy(hit[1]), 200
                if _GLOBAL_USAGE_COMPUTE_LOCK.locked():
                    return copy.deepcopy(hit[1]), 200
    with _GLOBAL_USAGE_COMPUTE_LOCK:
        if not force and ttl:
            now2 = time.monotonic()
            with _GLOBAL_USAGE_LOCK:
                hit2 = _GLOBAL_USAGE_CACHE.get(key)
                if isinstance(hit2, tuple) and len(hit2) == 2 and now2 - hit2[0] < ttl:
                    return copy.deepcopy(hit2[1]), 200
        value = _compute_global_usage_summary()
        with _GLOBAL_USAGE_LOCK:
            _GLOBAL_USAGE_CACHE[key] = (time.monotonic(), value)
    return copy.deepcopy(value), 200


_STATE_CACHE = globals().get("_STATE_CACHE") if isinstance(globals().get("_STATE_CACHE"), dict) else {}; _STATE_LOCK = globals().get("_STATE_LOCK") or threading.Lock()


_MAP_STAMP_FAST_CACHE = globals().get("_MAP_STAMP_FAST_CACHE") if isinstance(globals().get("_MAP_STAMP_FAST_CACHE"), dict) else {}


def _map_stamp_fast(cdir):
    if "PYTEST_CURRENT_TEST" in os.environ:
        return campaign.map_stamp(cdir)
    ck = os.path.normcase(os.path.abspath(str(cdir)))
    now_m = time.monotonic()
    hit = _MAP_STAMP_FAST_CACHE.get(ck)
    if hit is not None and (now_m - hit[0]) < 1.5:
        return hit[1]
    val = campaign.map_stamp(cdir)
    if len(_MAP_STAMP_FAST_CACHE) > 256:
        _MAP_STAMP_FAST_CACHE.clear()
    _MAP_STAMP_FAST_CACHE[ck] = (now_m, val)
    return val


def _shallow_state_copy(st_dict):
    out = dict(st_dict)
    if isinstance(out.get("usage_rollup"), dict):
        out["usage_rollup"] = dict(out["usage_rollup"])
    return out


def _state_cached(eng, cdir):
    """The state poll (2026-10-11 speed): the app's tiles and the Cave page both ask every open cockpit every few
    seconds; one answer serves every asker for up to four seconds, and anything the engine says (a new event) makes the
    next ask fresh."""
    try:
        ttl = max(0.0, float(os.environ.get("ANCHOR_STATE_TTL_S", "4")))
    except ValueError:
        ttl = 4.0
    stamp = _map_stamp_fast(cdir)                      # a question or review written to disk is never answered stale
    try:
        inf_est = round(float(eng._inflight_usage_estimate()[0] or 0.0), 4) if hasattr(eng, "_inflight_usage_estimate") else 0.0
    except Exception:
        inf_est = 0.0
    key = (
        id(eng),
        getattr(eng, "seq", None),
        getattr(eng, "busy", None),
        getattr(eng, "tokens", None),
        getattr(eng, "turns", None),
        round(float(getattr(eng, "spend", 0.0) or 0.0), 4),
        round(float(getattr(eng, "estimated_spend", 0.0) or 0.0), 4),
        inf_est,
        getattr(eng, "_usage_updated_at", None),
        stamp,
    )
    now = time.monotonic()
    if ttl:
        with _STATE_LOCK:
            hit = _STATE_CACHE.get(key)
            if hit and now - hit[0] < ttl:
                return _shallow_state_copy(hit[1])
    st = _state_with_usage(eng, cdir)
    st["stamp"] = stamp
    if ttl:
        with _STATE_LOCK:
            for k in [k for k, v in _STATE_CACHE.items() if now - v[0] >= ttl]:
                _STATE_CACHE.pop(k, None)
            _STATE_CACHE[key] = (now, st)
        return _shallow_state_copy(st)
    return st


def _state_with_usage(eng, cdir):
    state = eng.state()
    cur_sig = (
        getattr(eng, "tokens", 0),
        getattr(eng, "turns", 0),
        round(float(getattr(eng, "spend", 0.0) or 0.0), 4),
        round(float(getattr(eng, "estimated_spend", 0.0) or 0.0), 4),
        round(float(state.get("estimated_spend_usd") or 0.0), 4),
        getattr(eng, "_usage_updated_at", None),
    )
    if getattr(eng, "_last_rollup_sig", None) != cur_sig:
        eng._last_rollup_sig = cur_sig
        with _ROLLUP_LOCK:
            _ROLLUP_CACHE.pop(os.path.normcase(os.path.abspath(cdir)), None)
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


def _resolve_clean_download_filename(cdir, rel, real, ext, qs):
    """Resolve a clean, sanitized human download filename preserving extension and stripping hashes/IDs."""
    qs = qs or {}
    raw_fn = str(qs.get("filename") or "").strip()
    if raw_fn:
        return _core.sanitize_download_filename(raw_fn, fallback_ext=ext)
    norm_rel = str(rel or "").replace("\\", "/").strip("/")
    norm_rel_low = norm_rel.lower()
    exp_hash = str(qs.get("hash") or "").strip().lower()
    try:
        deliv_data = {}
        if cdir and os.path.isdir(str(cdir)):
            norm_c = os.path.normcase(os.path.abspath(str(cdir)))
            cached_d = None
            with _DELIV_LOCK:
                for dk, dv in _DELIV_CACHE.items():
                    if dk[0] == norm_c and isinstance(dv[2], dict):
                        cached_d = dv[2]
                        break
            deliv_data = cached_d if cached_d is not None else campaign.read_deliverables(cdir)
        pool = list(deliv_data.get("items") or []) + list(deliv_data.get("approved") or [])
        best_item = None
        for it in pool:
            if not isinstance(it, dict):
                continue
            it_open = str(it.get("open_path") or "").replace("\\", "/").strip("/").lower()
            it_path = str(it.get("path") or "").replace("\\", "/").strip("/").lower()
            it_read = str(it.get("readable_path") or "").replace("\\", "/").strip("/").lower()
            it_hash = str(it.get("hash") or "").strip().lower()
            if norm_rel_low and norm_rel_low in (it_open, it_path, it_read):
                best_item = it
                break
            if exp_hash and exp_hash != "0" * 64 and it_hash == exp_hash:
                best_item = it
        if best_item is not None:
            cand = str(best_item.get("suggested_filename") or best_item.get("human_title") or best_item.get("what") or "").strip()
            if cand:
                return _core.sanitize_download_filename(cand, fallback_ext=ext)
    except Exception:
        pass
    base_candidate = os.path.basename(norm_rel) if norm_rel else os.path.basename(str(real or ""))
    human_fn = campaign._human_filename_for_item(norm_rel or base_candidate, "", "")
    return _core.sanitize_download_filename(human_fn or base_candidate, fallback_ext=ext)


def handle_get(cdir, verb, qs):
    qs = qs or {}
    if verb in ("wave-state", "wave-map"):
        from steward_cockpit import wave_map_model as _wmm
        w_res = _wmm.build_wave_map_payload(cdir)
        return w_res, (500 if w_res.get("failure_state") == "backing-store-unreadable" else 200)
    if verb == "plan":
        if not cdir or not os.path.isdir(str(cdir)):
            return _plan_missing_response()
        from tools import steward_plan as _splan
        try:
            return _splan.read_plan_state(cdir), 200
        except Exception as exc:
            return _plan_http_error(exc)
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
                def _attach_rt(obj):
                    if not isinstance(obj, dict):
                        return
                    rt = _dr.reading_target(obj, pid=pid_q, effort_rel=dir_q, effort_dir=cdir, registered=reg, _root_real=_root_real, _priv_homes=_priv_homes)
                    obj["reading"] = rt
                    if isinstance(rt, dict) and rt.get("download"):
                        obj["download_url"] = rt["download"]
                    for old in obj.get("history") or []:
                        if isinstance(old, dict):
                            old_rt = _dr.reading_target(old, pid=pid_q, effort_rel=dir_q, effort_dir=cdir, registered=reg, _root_real=_root_real, _priv_homes=_priv_homes)
                            old["reading"] = old_rt
                            if isinstance(old_rt, dict) and old_rt.get("download"):
                                old["download_url"] = old_rt["download"]
                buckets_obj = data.get("buckets") if isinstance(data.get("buckets"), dict) else {}
                for coll in (
                    data.get("items") or [],
                    data.get("approved") or [],
                    data.get("key_deliverables") or [],
                    buckets_obj.get("for_review") or [],
                    buckets_obj.get("final") or [],
                    buckets_obj.get("in_progress") or [],
                    buckets_obj.get("archive") or [],
                ):
                    for it in coll:
                        _attach_rt(it)
                for a in data.get("acts") or []:
                    if isinstance(a.get("item"), dict):
                        _attach_rt(a["item"])
                    for c in a.get("companions") or []:
                        if isinstance(c.get("item"), dict):
                            _attach_rt(c["item"])
                shelves_obj = data.get("shelves") if isinstance(data.get("shelves"), dict) else {}
                for sb in shelves_obj.get("most_recent_batches") or []:
                    for sit in (sb.get("items") if isinstance(sb, dict) else None) or []:
                        _attach_rt(sit)
                        for fp in (sit.get("format_pills") if isinstance(sit, dict) else None) or []:
                            _attach_rt(fp)
                for scol in (shelves_obj.get("final") or [], shelves_obj.get("earlier") or []):
                    for sit in scol:
                        _attach_rt(sit)
                        for fp in (sit.get("format_pills") if isinstance(sit, dict) else None) or []:
                            _attach_rt(fp)
            except Exception:
                pass   # the tile still builds its own link from the path
        res_deliv = _deliverables_cached(cdir, qs, lambda: campaign.read_deliverables(cdir), _build)
        if isinstance(res_deliv, dict) and res_deliv.get("failure_state") == "backing-store-unreadable":
            return res_deliv, 500
        return res_deliv, 200
    if verb == "deliverable-file":
        # Serve ONE deliverable's bytes, HARD-CONTAINED to the effort dir via
        # paths.resolve_contained_path (../, %2e%2e, absolute, NUL, or symlink escape -> 403).
        rel = str(qs.get("path", ""))
        from provider_native import private_account_path
        try:
            contained_target = paths.resolve_contained_path(cdir, rel, allow_missing=True)
        except paths.UnsafePathError:
            return {
                "ok": False,
                "failure_state": "dependency-returns-garbage",
                "error": "Blocked unsafe path traversal or disallowed URL scheme",
            }, 403
        creal_path = Path(cdir).resolve()
        creal = str(creal_path)
        real = str(contained_target)
        if private_account_path(real):
            return {
                "ok": False,
                "failure_state": "dependency-returns-garbage",
                "error": "Blocked unsafe path traversal or disallowed URL scheme",
            }, 403
        in_effort = contained_target.is_relative_to(creal_path)
        if in_effort and not os.path.isfile(real) and rel:
            # 0. Strip duplicate leading effort folder prefix (e.g. `Book 1/chapters/...` inside `Book 1`)
            cdir_name = Path(cdir).name
            rel_norm = rel.replace("\\", "/").lstrip("/")
            if cdir_name and rel_norm.lower().startswith(cdir_name.lower() + "/"):
                stripped_rel = rel_norm[len(cdir_name) + 1:]
                try:
                    cand_strip_p = paths.resolve_contained_path(creal_path, stripped_rel, allow_missing=True)
                    if cand_strip_p.is_file() and not private_account_path(str(cand_strip_p)):
                        real = str(cand_strip_p)
                        rel = stripped_rel
                except paths.UnsafePathError:
                    pass
            # 1. Resolve bare or relative filenames (e.g. `CHAPTER-04-05-DRAFT-v2.docx` written in backticks in Steward dialogue)
            # against DELIVERABLES.md rows or effort subdirectories before checking code-job worktrees.
            target_name = Path(rel).name.lower()
            _skip_deliv_dirs = frozenset({".git", ".anchor", "node_modules", "__pycache__", "venv", ".venv", "dist", "build"})
            if not os.path.isfile(real) and target_name:
                try:
                    deliv_data = campaign.read_deliverables(cdir)
                    all_deliv_rows = (deliv_data.get("items") or []) + (deliv_data.get("approved") or [])
                    for it in all_deliv_rows:
                        if not isinstance(it, dict):
                            continue
                        row_cands = [str(it.get("open_path") or it.get("path") or "").strip()] + [
                            str(cp or "").strip() for cp in (it.get("companion_paths") or [])
                        ]
                        found_row_match = False
                        for ip in row_cands:
                            if ip and Path(ip).name.lower() == target_name:
                                try:
                                    cand_cdir_p = paths.resolve_contained_path(creal_path, ip, allow_missing=True)
                                    if cand_cdir_p.is_file() and not private_account_path(str(cand_cdir_p)):
                                        real = str(cand_cdir_p)
                                        rel = ip
                                        found_row_match = True
                                        break
                                except paths.UnsafePathError:
                                    continue
                        if found_row_match:
                            break
                    # Version-agnostic stem fallback (e.g. clicking an older `(v4).pdf` receipt superseded by `(v5).pdf`)
                    if not os.path.isfile(real):
                        req_suffix = Path(target_name).suffix.lower()
                        def _ver_agnostic_stem(fn: str) -> str:
                            st = Path(fn).stem.lower()
                            st = re.sub(r"\s*\(v\d+[^)]*\)", "", st, flags=re.I)
                            st = re.sub(r"[-_ ]v\d+\b", "", st, flags=re.I)
                            return re.sub(r"\s+", " ", st).strip(" -_")
                        target_vstem = _ver_agnostic_stem(target_name)
                        if target_vstem and len(target_vstem) >= 4:
                            for it in all_deliv_rows:
                                if not isinstance(it, dict):
                                    continue
                                row_cands = [str(it.get("open_path") or it.get("path") or "").strip()] + [
                                    str(cp or "").strip() for cp in (it.get("companion_paths") or [])
                                ]
                                found_vstem = False
                                for ip in row_cands:
                                    if ip and Path(ip).suffix.lower() == req_suffix and _ver_agnostic_stem(Path(ip).name) == target_vstem:
                                        try:
                                            cand_cdir_p = paths.resolve_contained_path(creal_path, ip, allow_missing=True)
                                            if cand_cdir_p.is_file() and not private_account_path(str(cand_cdir_p)):
                                                real = str(cand_cdir_p)
                                                rel = ip
                                                found_vstem = True
                                                break
                                        except paths.UnsafePathError:
                                            continue
                                if found_vstem:
                                    break
                except Exception:
                    pass
            if not os.path.isfile(real) and target_name:
                try:
                    cdir_root_p = Path(cdir)
                    for sub in ("Key Deliverables", "chapters", "visual-canon", "book-drafts", "deliverables", "story-arc", "editorial", "Finished Deliverables", "Final Deliverables", ".ecgberht/journal"):
                        sub_root = cdir_root_p / sub
                        if not sub_root.is_dir():
                            continue
                        for match_p in sub_root.rglob("*"):
                            if match_p.is_file() and match_p.name.lower() == target_name:
                                try:
                                    rel_sub = match_p.relative_to(cdir_root_p)
                                    cand_sub_p = paths.resolve_contained_path(creal_path, str(rel_sub), allow_missing=False)
                                    if cand_sub_p.is_file() and not private_account_path(str(cand_sub_p)):
                                        real = str(cand_sub_p)
                                        break
                                except (ValueError, OSError, paths.UnsafePathError):
                                    continue
                        if os.path.isfile(real):
                            break
                    # Bounded effort-wide filename search across all non-hidden subdirectories of cdir
                    if not os.path.isfile(real):
                        visited_files = 0
                        for walk_root, walk_dirs, walk_files in os.walk(cdir_root_p):
                            walk_dirs[:] = [
                                d for d in walk_dirs
                                if not d.startswith(".") and d.lower() not in _skip_deliv_dirs
                            ]
                            for fn in walk_files:
                                visited_files += 1
                                if visited_files > 6000:
                                    break
                                if fn.lower() == target_name:
                                    match_p = Path(walk_root) / fn
                                    try:
                                        rel_sub = match_p.relative_to(cdir_root_p)
                                        cand_sub_p = paths.resolve_contained_path(creal_path, str(rel_sub), allow_missing=False)
                                        if cand_sub_p.is_file() and not private_account_path(str(cand_sub_p)):
                                            real = str(cand_sub_p)
                                            break
                                    except (ValueError, OSError, paths.UnsafePathError):
                                        continue
                            if os.path.isfile(real) or visited_files > 6000:
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
                        for rec in reversed(cj_rows):
                            if not isinstance(rec, dict):
                                continue
                            wt = (rec.get("kept_delivery") or {}).get("worktree") or rec.get("worktree")
                            if not wt:
                                continue
                            wdir = str(rec.get("work_dir") or "").strip().strip("/\\")
                            rel_cands = [rel]
                            if wdir:
                                rel_cands.append(f"{wdir}/{rel}")
                            for out_p in (rec.get("outputs") or []):
                                if isinstance(out_p, str) and Path(out_p).name.lower() == target_name:
                                    rel_cands.append(out_p)
                            found_wt = False
                            for rc in rel_cands:
                                try:
                                    cand_wt_p = paths.resolve_contained_path(wt, rc, allow_missing=True)
                                    if cand_wt_p.is_file() and not private_account_path(str(cand_wt_p)):
                                        real = str(cand_wt_p)
                                        in_effort = True
                                        found_wt = True
                                        break
                                except paths.UnsafePathError:
                                    continue
                            if found_wt:
                                break
                except Exception:
                    pass
            # 2026-10-31 (Journal 0202 / Chekhov 0066): On-the-fly reading copy synthesis when `.docx`/`.pdf`/`.html`
            # is requested for a manuscript/deliverable whose `.md` source exists in the effort directory.
            req_ext = Path(rel).suffix.lower()
            if not os.path.isfile(real) and req_ext in (".docx", ".pdf", ".html"):
                try:
                    stem_lower = Path(rel).stem.lower()
                    md_source = None
                    try:
                        cand_md_direct = paths.resolve_contained_path(creal_path, str(Path(rel).with_suffix(".md")), allow_missing=True)
                        if cand_md_direct.is_file() and not private_account_path(str(cand_md_direct)):
                            md_source = cand_md_direct
                    except paths.UnsafePathError:
                        md_source = None
                    if md_source is None:
                        cdir_root_p = Path(cdir)
                        for sub in ("Key Deliverables", "chapters", "visual-canon", "book-drafts", "deliverables", "story-arc", "editorial", "Finished Deliverables", "Final Deliverables", ""):
                            sub_root = cdir_root_p / sub if sub else cdir_root_p
                            if not sub_root.is_dir():
                                continue
                            it_files = sub_root.rglob("*.md") if sub else sub_root.glob("*.md")
                            for match_p in it_files:
                                if match_p.is_file() and match_p.stem.lower() == stem_lower:
                                    try:
                                        rel_md = match_p.relative_to(cdir_root_p)
                                        cand_md_p = paths.resolve_contained_path(creal_path, str(rel_md), allow_missing=False)
                                        if cand_md_p.is_file() and not private_account_path(str(cand_md_p)):
                                            md_source = cand_md_p
                                            break
                                    except (ValueError, OSError, paths.UnsafePathError):
                                        continue
                            if md_source is not None:
                                break
                        if md_source is None:
                            visited_md = 0
                            for walk_root, walk_dirs, walk_files in os.walk(cdir_root_p):
                                walk_dirs[:] = [
                                    d for d in walk_dirs
                                    if not d.startswith(".") and d.lower() not in _skip_deliv_dirs
                                ]
                                for fn in walk_files:
                                    visited_md += 1
                                    if visited_md > 6000:
                                        break
                                    if fn.lower().endswith(".md") and Path(fn).stem.lower() == stem_lower:
                                        match_p = Path(walk_root) / fn
                                        try:
                                            rel_md = match_p.relative_to(cdir_root_p)
                                            cand_md_p = paths.resolve_contained_path(creal_path, str(rel_md), allow_missing=False)
                                            if cand_md_p.is_file() and not private_account_path(str(cand_md_p)):
                                                md_source = cand_md_p
                                                break
                                        except (ValueError, OSError, paths.UnsafePathError):
                                            continue
                                if md_source is not None or visited_md > 6000:
                                    break
                    if md_source is not None and md_source.is_file():
                        from tools import reading_copy as _rc
                        target_out = paths.resolve_contained_path(
                            creal_path,
                            str(md_source.relative_to(creal_path).with_suffix(req_ext)),
                            allow_missing=True,
                        )
                        if req_ext == ".docx":
                            _rc.write_docx(md_source, target_out)
                        elif req_ext == ".pdf":
                            _rc.write_pdf(md_source, target_out)
                        elif req_ext == ".html":
                            _rc.write_html(md_source, target_out)
                        if target_out.is_file():
                            real = str(target_out.resolve())
                except Exception:
                    pass
        if not in_effort or not os.path.isfile(real):
            return {"error": "not an openable deliverable (outside this effort or missing)"}, 404
        if qs.get("pdf_page") is None and not qs.get("_range_cont"):
            def _rec_viewed():
                try:
                    campaign.record_deliverable_viewed(cdir, rel)
                    rel_from_cdir = os.path.relpath(real, creal).replace("\\", "/")
                    if rel_from_cdir and not rel_from_cdir.startswith("..") and rel_from_cdir != rel:
                        campaign.record_deliverable_viewed(cdir, rel_from_cdir)
                except Exception:
                    pass
            if str(qs.get("download", "")).strip() in ("1", "true") and "PYTEST_CURRENT_TEST" not in os.environ:
                threading.Thread(target=_rec_viewed, name="anchor-deliv-viewed", daemon=True).start()
            else:
                _rec_viewed()
        if os.path.getsize(real) > 50 * 1024 * 1024:
            return {"error": "file too large to serve inline (50MB cap)"}, 413

        def _cached_file_sha256(fpath: str) -> str:
            _hcache = globals().setdefault("_DELIV_SHA256_CACHE", {})
            _hlock = globals().setdefault("_DELIV_SHA256_LOCK", threading.Lock())
            st_f = os.stat(fpath)
            hkey = (
                os.path.normcase(os.path.abspath(fpath)),
                getattr(st_f, "st_mtime_ns", st_f.st_mtime),
                getattr(st_f, "st_ctime_ns", 0),
                getattr(st_f, "st_ino", 0),
                st_f.st_size,
            )
            with _hlock:
                hit = _hcache.get(hkey)
            if hit is not None:
                return hit
            h = hashlib.sha256()
            with open(fpath, "rb") as fh_hash:
                while True:
                    blk = fh_hash.read(262144)
                    if not blk:
                        break
                    h.update(blk)
            digest_hex = h.hexdigest()
            with _hlock:
                if len(_hcache) >= 1024:
                    _hcache.clear()
                _hcache[hkey] = digest_hex
            return digest_hex

        expected_hash = qs.get("hash")
        if expected_hash and _cached_file_sha256(real) != expected_hash:
            matched_rev_path = None
            if expected_hash != "0" * 64:
                try:
                    ref_state = (campaign.read_refinement(cdir) or {}).get("state") or {}
                    for sl in (ref_state.get("slices") or {}).values():
                        for rev in (sl.get("revisions") or {}).values():
                            if isinstance(rev, dict) and rev.get("hash") == expected_hash and rev.get("path"):
                                cand_rev = (Path(cdir) / str(rev["path"])).resolve()
                                if cand_rev.is_relative_to(Path(cdir).resolve()) and cand_rev.is_file():
                                    if _cached_file_sha256(str(cand_rev)) == expected_hash:
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
        want_raw = str(qs.get("raw", "")).strip() in ("1", "true")
        raw_pdf_page = qs.get("pdf_page")
        want_pdf_page = None
        if raw_pdf_page is not None and str(raw_pdf_page).strip() != "":
            try:
                want_pdf_page = int(str(raw_pdf_page).strip())
            except (TypeError, ValueError):
                want_pdf_page = None
        ctype, disposition = deliverable_content_type(ext)
        clean_dl_filename = _resolve_clean_download_filename(cdir, rel, real, ext, qs)
        if ext == ".pdf" and not want_download and not want_raw:
            if want_pdf_page is not None:
                return _serve_pdf_page_png(real, want_pdf_page)
            if want_scrollview:
                return _serve_pdf_scrollview(real, qs, rel, cdir)
        if ext in (".html", ".htm") and not want_download and not want_raw and want_scrollview:
            return _serve_html_scrollview(real, qs, rel, cdir)
        if want_view and not want_download and ext == ".pptx":
            # Only a ledger-bound PDF of these exact deck bytes is a slide preview.
            digest = _cached_file_sha256(real)
            refinement = campaign.read_refinement(cdir)
            previews = [rev["visual_companion"]
                for sl in (refinement or {}).get("state", {}).get("slices", {}).values()
                for rev in sl.get("revisions", {}).values()
                if rev.get("hash") == digest and rev.get("visual_companion")]
            if previews:
                preview = previews[-1]
                target = (Path(cdir) / preview["path"]).resolve()
                if (preview.get("source_hash") != digest or not target.is_relative_to(Path(cdir).resolve())
                        or not target.is_file() or _cached_file_sha256(str(target)) != preview["hash"]):
                    return {"error": "visual-companion-mismatch"}, 409
                if want_pdf_page is not None:
                    return _serve_pdf_page_png(str(target), want_pdf_page)
                if want_scrollview:
                    return _serve_pdf_scrollview(str(target), qs, rel, cdir)
                pdf_fn = _core.sanitize_download_filename(Path(clean_dl_filename).stem, fallback_ext=".pdf")
                pdf_cd = _format_content_disposition("inline", pdf_fn)
                _ROUTE_TLS.pending_cd = pdf_cd
                return {"__file__": str(target), "__ctype__": "application/pdf", "__disposition__": "inline",
                        "__filename__": pdf_fn, "__content_disposition__": pdf_cd,
                        "__csp__": sandbox_csp_for("application/pdf")}, 200
            import html
            dl = "/api/steward/deliverable-file?pid=%s&dir=%s&path=%s&hash=%s&download=1&filename=%s" % (
                _q(str(qs.get("pid", ""))), _q(str(qs.get("dir", ""))), _q(rel), digest, _q(clean_dl_filename))
            if qs.get("token"):
                dl += "&token=" + _q(str(qs["token"]))
            import office_preview as _op_pptx
            return {"__html__": _op_pptx.render_preview(Path(real).read_bytes(), clean_dl_filename, dl)}, 200


        if str(qs.get("render", "")).strip() in ("1", "true") and not want_download and (
                ext in (".md", ".markdown", ".txt") or ext in _SOURCE_TEXT):
            # 2026-10-07 (execution minimum item 2): the canonical reading URL of a markdown product - formatted
            # (tables, links, math), never raw bytes; plain text keeps its lines in a code block
            import report_viewer
            try:
                _rv_mt = os.stat(report_viewer.__file__).st_mtime_ns
                if getattr(report_viewer, "_ANCHOR_MT", None) != _rv_mt:
                    report_viewer = importlib.reload(report_viewer)
                    report_viewer._ANCHOR_MT = _rv_mt
            except Exception:
                pass
            text = Path(real).read_text(encoding="utf-8", errors="replace")
            if ext not in (".md", ".markdown"):          # plain text and program source keep their lines
                text = "```\n" + text.replace("```", "'''") + "\n```"
            return {"__html__": report_viewer.reader_html(text, title=clean_dl_filename)}, 200
        if want_view and not want_download and ext in OFFICE_PREVIEW_EXTENSIONS:
            import office_preview as _op
            with open(real, "rb") as fh:
                data = fh.read()
            hash_param = ("&hash=" + _q(str(expected_hash))) if expected_hash else ""
            dl = "/api/steward/deliverable-file?pid=%s&dir=%s&path=%s%s&download=1&filename=%s%s" % (
                _q(str(qs.get("pid", ""))), _q(str(qs.get("dir", ""))), _q(rel), hash_param, _q(clean_dl_filename),
                ("&token=" + _q(str(qs.get("token")))) if qs.get("token") else "")
            html_page = _op.render_preview(data, clean_dl_filename, dl)
            return {"__html__": html_page}, 200
        if want_download:
            disposition = "attachment"
        cd_header = _format_content_disposition(disposition, clean_dl_filename)
        _ROUTE_TLS.pending_cd = cd_header
        return {"__file__": real, "__ctype__": ctype, "__disposition__": disposition,
                "__filename__": clean_dl_filename, "__content_disposition__": cd_header,
                "__csp__": sandbox_csp_for(ctype)}, 200
    if verb == "efforts":
        return _efforts(cdir), 200
    if verb == "map":
        _in_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
        _map_cache = globals().setdefault("_MAP_ROUTE_CACHE", {})
        _map_lock = globals().setdefault("_MAP_ROUTE_LOCK", threading.Lock())
        _map_key_locks = globals().setdefault("_MAP_ROUTE_KEY_LOCKS", {})
        _norm_cdir = os.path.normcase(os.path.abspath(str(cdir)))
        _raw_ph = str(qs.get("plan_history", qs.get("include_plan_history", "1"))).strip().lower()
        _want_plan_hist = _raw_ph not in ("0", "false", "no")
        _mkey = (_norm_cdir, str(qs.get("pid", "")), str(qs.get("dir", "")), _want_plan_hist)
        if not _in_pytest:
            _cur_stamp = campaign.map_stamp(cdir)
            _now_mono = time.monotonic()
            with _map_lock:
                _mhit = _map_cache.get(_mkey)
                if _mhit is not None and _mhit[0] == _cur_stamp and (_now_mono - _mhit[1]) < 30.0:
                    return dict(_mhit[2]), 200
                _klock = _map_key_locks.setdefault(_norm_cdir, threading.Lock())
        else:
            _klock = None

        def _derive_recent_done_sentence(cdir_in, m_in) -> str:
            def _clean_one_sentence(raw_txt: str, suffix: str = "") -> str:
                s = str(raw_txt or "").replace("**", "").replace("`", "").strip()
                s = re.sub(r"^[\-\*\u2022\d\.\)\s]+", "", s)
                s = re.sub(r"\s+", " ", s).strip()
                if not s:
                    return ""
                parts = re.split(r"(?<=[.!?])\s+", s)
                head = parts[0].strip() if parts else s
                if len(head) < 16 and len(parts) > 1:
                    head = f"{head} {parts[1].strip()}".strip()
                if len(head) > 185:
                    head = head[:182].rstrip(" ,;:-") + "…"
                if suffix:
                    head = head.rstrip(".") + f" ({suffix})."
                elif head and head[-1] not in ".!?…":
                    head += "."
                return head

            wm = m_in.get("wave_map")
            if isinstance(wm, dict):
                rh = wm.get("recent_history")
                if isinstance(rh, list) and rh:
                    h0 = rh[0] if isinstance(rh[0], dict) else {}
                    htxt = str(h0.get("text") or "").strip()
                    hago = str(h0.get("ago") or "").strip()
                    sfx = hago if (hago and hago.lower() not in ("done", "completed")) else ""
                    sent = _clean_one_sentence(htxt, sfx)
                    if sent:
                        return sent

            steps_list = m_in.get("steps")
            if isinstance(steps_list, list):
                for st_done in reversed(steps_list):
                    if isinstance(st_done, dict) and (st_done.get("status") == "done" or st_done.get("done") is True):
                        nm = str(st_done.get("name") or st_done.get("title") or "").strip()
                        gl = str(st_done.get("goal") or "").strip()
                        if nm:
                            combo = f"Completed {nm}" + (f" — {gl}" if gl else "")
                            sent = _clean_one_sentence(combo)
                            if sent:
                                return sent

            try:
                clog = Path(cdir_in) / ".ecgberht" / "conversation-log.json"
                if clog.is_file():
                    turns = (json.loads(clog.read_text(encoding="utf-8")) or {}).get("turns") or []
                    for trn in reversed(turns):
                        if not isinstance(trn, dict) or trn.get("role") != "steward":
                            continue
                        tid = str(trn.get("turn_id") or "")
                        ttxt = str(trn.get("text") or "").strip()
                        if not ttxt:
                            continue
                        if tid.startswith("receipt:"):
                            m_lnk = re.search(r"\[([^\]]+)\]\(", ttxt)
                            if m_lnk:
                                return _clean_one_sentence(f"Delivered {m_lnk.group(1)}")
                        else:
                            sent = _clean_one_sentence(ttxt)
                            if sent:
                                return sent
            except Exception:
                pass

            hb = m_in.get("heartbeat") if isinstance(m_in.get("heartbeat"), dict) else {}
            ae = str(hb.get("active_effort") or "").strip()
            if ae:
                return _clean_one_sentence(ae)
            return "No completed waves recorded yet — use the dialogue or left plan to kick off the first wave."

        def _build_map_resp():
            if not _in_pytest:
                try:
                    _sync_cache = globals().setdefault("_LAST_MAP_SYNC_TS", {})
                    _now_s = time.monotonic()
                    if _now_s - _sync_cache.get(_norm_cdir, 0.0) > 30.0:
                        _sync_cache[_norm_cdir] = _now_s
                        campaign.sync_steward_projections(cdir)
                except Exception:
                    pass
            m = dict(campaign.read_map(cdir, include_plan_history=_want_plan_hist))
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

            def _slim_steps_list(steps_in):
                if not isinstance(steps_in, list):
                    return steps_in
                slim_out = []
                for st_item in steps_in:
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
                        slim_out.append(st_copy)
                    else:
                        slim_out.append(st_item)
                return slim_out

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
                m["steps"] = _slim_steps_list(m["steps"])
            try:
                from tools import steward_plan as _splan
                p_state = _splan.read_plan_state(cdir)
                if isinstance(p_state, dict) and isinstance(p_state.get("steps"), list):
                    p_state = dict(p_state)
                    p_state["steps"] = _slim_steps_list(p_state["steps"])
                m["plan_state"] = p_state
            except Exception as _pexc:
                _err_body, _ = _plan_http_error(_pexc)
                m["plan_state"] = _err_body
            m["full_cockpit_url"] = full_cockpit_url(str(qs.get("pid", "")), str(qs.get("dir", "")))
            m["folder_path"] = str(Path(cdir).resolve())
            try:
                from steward_cockpit import wave_map_model as _wmm
                m["wave_map"] = _wmm.build_wave_map_payload(cdir)
            except Exception:
                m["wave_map"] = None
            m["recent_done_sentence"] = _derive_recent_done_sentence(cdir, m)
            m["stamp"] = campaign.map_stamp(cdir)
            m["steward"] = _persona_name()
            return m

        if _klock is None:
            return _build_map_resp(), 200
        with _klock:
            _cur_stamp2 = campaign.map_stamp(cdir)
            _now_mono2 = time.monotonic()
            with _map_lock:
                _mhit2 = _map_cache.get(_mkey)
                if _mhit2 is not None and _mhit2[0] == _cur_stamp2 and (_now_mono2 - _mhit2[1]) < 30.0:
                    return dict(_mhit2[2]), 200
            _built_m = _build_map_resp()
            with _map_lock:
                if len(_map_cache) > 256:
                    _map_cache.clear()
                _map_cache[_mkey] = (_built_m.get("stamp") or campaign.map_stamp(cdir), time.monotonic(), _built_m)
            return dict(_built_m), 200
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
        return campaign.status_http_response(cdir, eng.state() if eng else None, live=eng is not None, qs=qs)
    if verb == "spend":
        return spend_http_response(cdir, qs=qs)
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
    if verb in (
        "anvil",
        "anvil/walkthrough",
        "anvil/source",
        "anvil/v4_state",
        "anvil/analyses",
        "anvil/discover",
        "/api/steward/anvil",
        "/api/steward/anvil/walkthrough",
        "/api/steward/anvil/source",
        "/api/steward/anvil/v4_state",
        "/api/steward/anvil/analyses",
        "/api/steward/anvil/discover",
        "anvil/scoping",
        "/api/steward/anvil/scoping",
        "anvil/replication",
        "/api/steward/anvil/replication",
        "anvil/comprehension",
        "/api/steward/anvil/comprehension",
        "anvil/literature",
        "/api/steward/anvil/literature",
    ):
        from steward_cockpit import anvil_session as _as
        from steward_cockpit import anvil_scoping_v6 as _as6
        from steward_cockpit import anvil_py_deps as _apd
        from steward_cockpit import anvil_replication_job as _arj
        from steward_cockpit import anvil_verification_guard as _avg
        from steward_cockpit import anvil_comprehension_engine as _ace
        from steward_cockpit import anvil_literature_job as _alj
        for _m_ref in (_as, _as6, _apd, _arj, _avg, _ace, _alj):
            try:
                _mt = Path(_m_ref.__file__).stat().st_mtime_ns
                if getattr(_m_ref, "_LOADED_MTIME_NS", None) != _mt:
                    importlib.reload(_m_ref)
                    _m_ref._LOADED_MTIME_NS = _mt
            except Exception:
                pass
        norm_verb = verb[len("/api/steward/"):] if verb.startswith("/api/steward/") else verb
        raw_act_q = qs.get("action")
        if isinstance(raw_act_q, list):
            raw_act_q = raw_act_q[0] if raw_act_q else ""
        act_get = str(raw_act_q or "").strip().lower()
        raw_aid_q = qs.get("analysis_id")
        if isinstance(raw_aid_q, list):
            raw_aid_q = raw_aid_q[0] if raw_aid_q else None
        aid_get = raw_aid_q if raw_aid_q is not None else None
        raw_disc_q = qs.get("discover")
        if isinstance(raw_disc_q, list):
            raw_disc_q = raw_disc_q[0] if raw_disc_q else ""
        raw_an_q = qs.get("analyses")
        if isinstance(raw_an_q, list):
            raw_an_q = raw_an_q[0] if raw_an_q else ""

        try:
            if norm_verb == "anvil/discover" or act_get in ("discover", "discover_candidates") or str(raw_disc_q or "").strip().lower() in ("1", "true", "yes"):
                return _as.discover_cockpit_candidates_http(cdir)
            if norm_verb == "anvil/scoping" or act_get in ("scoping", "scoping_state", "scoping_v2"):
                raw_sw_q = qs.get("software_spec") if qs.get("software_spec") is not None else qs.get("software_target")
                if isinstance(raw_sw_q, list):
                    raw_sw_q = raw_sw_q[0] if raw_sw_q else None
                raw_pp_q = qs.get("paper_spec") if qs.get("paper_spec") is not None else qs.get("paper_target")
                if isinstance(raw_pp_q, list):
                    raw_pp_q = raw_pp_q[0] if raw_pp_q else None
                raw_mids_q = qs.get("module_ids")
                if isinstance(raw_mids_q, list):
                    raw_mids_q = raw_mids_q[0] if raw_mids_q else None
                parsed_mids = None
                if raw_mids_q is not None and str(raw_mids_q).strip():
                    s_mids = str(raw_mids_q).strip()
                    if s_mids.startswith("["):
                        try:
                            parsed_mids = json.loads(s_mids)
                        except Exception:
                            return {
                                "ok": False,
                                "error_code": "MALFORMED_DATA_REFUSED",
                                "status_kind": "dependency-returns-garbage",
                                "failure_state": "dependency-returns-garbage",
                                "message": "Malformed Anvil request or invalid engine output",
                                "error": "Malformed Anvil request or invalid engine output",
                            }, 400
                    else:
                        parsed_mids = [x.strip() for x in s_mids.split(",") if x.strip()]
                return _as.get_scoping_v2_state(
                    cdir,
                    selected_module_ids=parsed_mids,
                    software_spec=str(raw_sw_q) if raw_sw_q is not None else None,
                    paper_spec=str(raw_pp_q) if raw_pp_q is not None else None,
                    analysis_id=aid_get,
                )
            if norm_verb == "anvil/replication" or act_get in ("replication", "replication_state"):
                from steward_cockpit import anvil_replication_job as _arj
                raw_jid = qs.get("job_id")
                if isinstance(raw_jid, list):
                    raw_jid = raw_jid[0] if raw_jid else None
                return _arj.get_replication_state(cdir, analysis_id=aid_get, job_id=str(raw_jid) if raw_jid else None)
            if norm_verb == "anvil/comprehension" or act_get in ("comprehension", "semantic_state"):
                from steward_cockpit import anvil_comprehension_engine as _ace
                raw_ss = qs.get("scope_sha256")
                if isinstance(raw_ss, list):
                    raw_ss = raw_ss[0] if raw_ss else None
                return _ace.get_comprehension_state(cdir, scope_sha256=str(raw_ss) if raw_ss else None, analysis_id=aid_get)
            if norm_verb == "anvil/literature" or act_get in ("literature", "literature_state"):
                from steward_cockpit import anvil_literature_job as _alj
                return _alj.get_literature_state(cdir, analysis_id=aid_get)
            if norm_verb == "anvil/analyses" or act_get in ("analyses", "list_analyses") or str(raw_an_q or "").strip().lower() in ("1", "true", "yes"):
                inc_arch = qs.get("include_archived")
                if isinstance(inc_arch, list):
                    inc_arch = inc_arch[0] if inc_arch else ""
                return _as.list_cockpit_analyses(
                    cdir,
                    include_archived=str(inc_arch or "").strip().lower() in ("1", "true", "yes"),
                )
            if norm_verb == "anvil/v4_state" or act_get == "v4_state":
                return _as.get_v4_cockpit_state(cdir, analysis_id=aid_get)
            if norm_verb == "anvil/source" or act_get == "source":
                raw_file_q = qs.get("file") if qs.get("file") is not None else qs.get("path")
                if isinstance(raw_file_q, list):
                    raw_file_q = raw_file_q[0] if raw_file_q else ""
                rel_file = str(raw_file_q or "").strip()
                src_out = _as.get_cockpit_file_source(cdir, rel_file, analysis_id=aid_get)
                if isinstance(src_out, tuple) and len(src_out) == 2:
                    return src_out
                return src_out, 200
            if norm_verb == "anvil/walkthrough" or act_get == "walkthrough":
                raw_blk = qs.get("block_id") if qs.get("block_id") is not None else qs.get("block")
                if isinstance(raw_blk, list):
                    raw_blk = raw_blk[0] if raw_blk else ""
                return _run_with_cockpit_usage_attribution(
                    "anvil", "walkthrough", cdir, qs,
                    lambda: _as.walkthrough_in_session(cdir, str(raw_blk or ""), analysis_id=aid_get),
                ), 200
            raw_sum_q = qs.get("summary")
            if isinstance(raw_sum_q, list):
                raw_sum_q = raw_sum_q[0] if raw_sum_q else ""
            summary_only = str(raw_sum_q or "").strip().lower() in ("1", "true", "yes")
            return _as.get_session_status(cdir, summary_only=summary_only, analysis_id=aid_get), 200
        except ValueError as exc:
            if hasattr(exc, "payload") and hasattr(exc, "http_status"):
                return exc.payload, int(exc.http_status)
            msg = str(exc)
            msg_low = msg.lower()
            if "bound_exceeded_refusal" in msg_low or "exceeds 2 mb" in msg_low:
                return {"ok": False, "error_code": "BOUND_EXCEEDED_REFUSAL", "error": msg, "message": msg}, 413
            is_escape = any(
                tok in msg_low
                for tok in ("traversal", "permitted", "outside", "restricted", "symlink", "escape")
            )
            err_code = 403 if is_escape else 400
            return {
                "ok": False,
                "error_code": "PATH_ESCAPE_REFUSED" if is_escape else "MALFORMED_DATA_REFUSED",
                "error": msg,
                "message": msg,
            }, err_code
    if verb == "aegis":
        def _do_aegis_get(_aeg):
            target_q = str(qs.get("target") or "").strip()
            if target_q and target_q != ".":
                return _aeg.run_cockpit_aegis_scan(cdir, target_spec=target_q)
            cdir_p = Path(cdir).resolve()
            if (cdir_p / ".aegis" / "session.json").is_file() or (cdir_p / ".anvil" / "session.json").is_file():
                return _aeg.get_cockpit_aegis_state(cdir, auto_init=True)
            return _aeg.run_cockpit_aegis_scan(cdir, target_spec=".")

        return _run_aegis_route_contract(cdir, qs or {}, _do_aegis_get, verify_scanner_exec=True)
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
    if verb == "drafts":
        return handle_drafts_request("GET", qs=qs, proot=cdir)
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


def _run_with_cockpit_usage_attribution(tool_name: str, act: str, cdir: str, body, fn):
    """Best-effort attribute Anvil / Aegis cockpit invocations into usage_capture / usage_index."""
    import uuid as _uuid_mod

    att_env = {}
    prev_env = {}
    pid = None
    folder_path = None
    _uc = None
    try:
        import usage_capture as _uc
        pid, folder_path = _uc.resolve_project(cdir)
        if not pid and isinstance(body, dict):
            pid = body.get("project_id") or body.get("pid") or None
        att_env = _uc.attribution_env(
            project_id=pid,
            effort_dir=cdir,
            folder_path=folder_path,
            source=f"{tool_name}:{act}",
        )
        for ek, ev in att_env.items():
            prev_env[ek] = os.environ.get(ek)
            os.environ[ek] = str(ev)
    except Exception:
        _uc = None
    t0 = time.monotonic()
    try:
        res = fn()
    finally:
        for ek, old_v in prev_env.items():
            if old_v is None:
                os.environ.pop(ek, None)
            else:
                os.environ[ek] = old_v
    dur_ms = int(max(0.0, (time.monotonic() - t0) * 1000.0))
    if _uc is not None:
        try:
            res_d = (
                res[0]
                if (isinstance(res, tuple) and len(res) == 2 and isinstance(res[0], dict))
                else (res if isinstance(res, dict) else {})
            )
            sess_d = res_d.get("session") if isinstance(res_d.get("session"), dict) else {}
            seat_d = sess_d.get("model_seating") if isinstance(sess_d.get("model_seating"), dict) else {}
            u_dict = (
                res_d.get("usage")
                if isinstance(res_d.get("usage"), dict)
                else (sess_d.get("usage") if isinstance(sess_d.get("usage"), dict) else None)
            )
            raw_tok = res_d.get("tokens")
            if raw_tok is None and isinstance(u_dict, dict):
                raw_tok = u_dict.get("total_tokens")
                if raw_tok is None:
                    raw_tok = (
                        int(u_dict.get("input_tokens") or 0)
                        + int(u_dict.get("output_tokens") or 0)
                        + int(u_dict.get("cache_read_input_tokens") or 0)
                        + int(u_dict.get("cache_creation_input_tokens") or 0)
                    )
            tok = int(raw_tok or 0)
            cost_usd = res_d.get("cost_usd")
            mod = (
                res_d.get("model")
                or (u_dict.get("model") if isinstance(u_dict, dict) else None)
                or seat_d.get("coding_model_id")
                or seat_d.get("review_model_id")
                or None
            )
            mod_low = str(mod or "").lower()
            cli = (
                res_d.get("cli")
                or seat_d.get("coding_family")
                or ("gemini" if "gemini" in mod_low else "chatgpt" if "gpt" in mod_low else "grok" if "grok" in mod_low else "claude")
            )
            run_uid = str(_uuid_mod.uuid4())
            native_id = f"{tool_name}:{act}:{run_uid[:12]}"
            idx_key = f"seat:{native_id}"
            u_state = "unmeasured" if (tok == 0 and cost_usd is None) else None
            _uc.ingest_usage(
                run_uid if (tok > 0 or cost_usd is not None) else None,
                key=idx_key,
                index_key=idx_key,
                source=_uc.SOURCE_SEAT,
                native_id=native_id,
                tokens=tok,
                cost_usd=cost_usd,
                project_id=pid,
                folder_path=folder_path,
                effort_dir=cdir,
                cli=cli,
                model=mod,
                duration_ms=dur_ms,
                usage=u_dict,
                usage_state=u_state,
            )
            try:
                _uc.ingest_receipts(parent_effort=cdir)
            except Exception:
                pass
        except Exception:
            pass
    return res


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


def _format_content_disposition(disposition: str, filename: str) -> str:
    """Build an RFC-9110 / RFC-5987 Content-Disposition header guaranteed to encode
    cleanly in HTTP latin-1 while preserving full UTF-8 human titles via filename*."""
    import unicodedata as _ud
    disp = (str(disposition or "inline").strip() or "inline").replace("\r", "").replace("\n", "")
    raw_fn = str(filename or "download").replace("\r", "").replace("\n", "").replace('"', "'").strip() or "download"
    ascii_map = str.maketrans({
        "\u2014": "-", "\u2013": "-", "\u2212": "-", "\u2010": "-", "\u2011": "-",
        "\u2018": "'", "\u2019": "'", "\u201c": "'", "\u201d": "'",
        "\u2026": "...", "\u00a0": " ", "\u00b7": "-", "\u2022": "-",
    })
    norm = _ud.normalize("NFKD", raw_fn.translate(ascii_map))
    ascii_fn = "".join(ch for ch in norm if 32 <= ord(ch) <= 126 and ch not in ('"', "\\")).strip()
    if not ascii_fn or ascii_fn.startswith("."):
        ext = Path(raw_fn).suffix
        ascii_ext = "".join(ch for ch in ext if 32 <= ord(ch) <= 126 and ch not in ('"', "\\", "/", " "))
        ascii_fn = "document" + (ascii_ext or "")
    hdr = f'{disp}; filename="{ascii_fn}"'
    if any(ord(ch) > 126 or ord(ch) < 32 for ch in raw_fn) or ascii_fn != raw_fn:
        hdr += "; filename*=UTF-8''" + _q(raw_fn)
    return hdr


def _serve_pdf_page_png(real_path: str, page_idx: int):
    """Render a single PDF page to PNG via PyMuPDF (fitz) for scrollable split-view."""
    try:
        fitz = importlib.import_module("fitz")
        st = os.stat(real_path)
        cache_dir = Path(tempfile.gettempdir()) / "anchor-pdf-pages"
        cache_dir.mkdir(parents=True, exist_ok=True)
        hkey = hashlib.sha256(f"{real_path}:{st.st_mtime_ns}:{st.st_size}:{page_idx}:s24".encode("utf-8")).hexdigest()[:24]
        cache_png = cache_dir / f"{hkey}-p{page_idx}.png"
        if not cache_png.is_file():
            doc = fitz.open(real_path)
            if page_idx < 0 or page_idx >= len(doc):
                doc.close()
                return {"error": "pdf page out of range"}, 404
            page = doc[page_idx]
            pix = page.get_pixmap(matrix=fitz.Matrix(2.4, 2.4), alpha=False)
            png_bytes = pix.tobytes("png")
            doc.close()
            tmp_png = cache_png.with_suffix(".tmp")
            tmp_png.write_bytes(png_bytes)
            os.replace(tmp_png, cache_png)
        return {"__file__": str(cache_png), "__ctype__": "image/png", "__disposition__": "inline"}, 200
    except Exception as exc:
        return {"error": f"pdf page render failed: {exc}"}, 500


def _serve_pdf_scrollview(real_path: str, qs: dict, rel: str, cdir: str):
    """Serve a PDF deliverable as a scrollable, independently zoomable same-origin HTML page
    of high-DPI page images so Ctrl+ / Ctrl- / Ctrl+0 / Ctrl+wheel, drag-panning, PageUp/PageDown,
    and non-focus-stealing scroll buttons work cleanly inside split panes without rescaling Anchor."""
    try:
        fitz = importlib.import_module("fitz")
        import html as _html
        doc = fitz.open(real_path)
        page_count = len(doc)
        doc.close()
        if page_count <= 0:
            raise ValueError("empty pdf")
    except Exception:
        cd_fb = _format_content_disposition("inline", os.path.basename(real_path))
        return {"__file__": real_path, "__ctype__": "application/pdf", "__disposition__": "inline",
                "__content_disposition__": cd_fb, "__csp__": sandbox_csp_for("application/pdf")}, 200

    import html as _html
    pid_q = _q(str(qs.get("pid", "")))
    dir_q = _q(str(qs.get("dir", "")))
    rel_q = _q(str(rel or ""))
    tok_q = ("&token=" + _q(str(qs.get("token")))) if qs.get("token") else ""
    hash_q = ("&hash=" + _q(str(qs.get("hash")))) if qs.get("hash") else ""
    view_q = ("&view=1") if str(qs.get("view", "")).strip() in ("1", "true") else ""
    dl_ext = Path(str(rel or real_path)).suffix.lower() or ".pdf"
    clean_scroll_fn = _resolve_clean_download_filename(cdir, rel, real_path, dl_ext, qs)
    fn_q = "&filename=" + _q(clean_scroll_fn)
    base_url = f"/api/steward/deliverable-file?pid={pid_q}&dir={dir_q}&path={rel_q}{hash_q}{view_q}{tok_q}"
    dl_url = f"/api/steward/deliverable-file?pid={pid_q}&dir={dir_q}&path={rel_q}{hash_q}&download=1{fn_q}{tok_q}"
    native_url = f"{base_url}&raw=1"
    fname = _html.escape(clean_scroll_fn or os.path.basename(real_path))
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
        "html,body{height:100%;margin:0;padding:0;overflow:hidden;display:flex;flex-direction:column;"
        "background:#0d1117;color:#e6edf3;font:13.5px/1.45 -apple-system,'Segoe UI',system-ui,sans-serif}"
        ".pdf-bar{flex:0 0 auto;width:100%;box-sizing:border-box;z-index:20;background:rgba(22,27,34,0.96);"
        "backdrop-filter:blur(8px);border-bottom:1px solid #30363d;padding:5px 10px;display:flex;align-items:center;gap:5px;flex-wrap:wrap}"
        ".pdf-badge{font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;background:rgba(248,81,73,0.18);color:#ff7b72;border:1px solid rgba(248,81,73,0.4);letter-spacing:.04em;flex:none}"
        ".pdf-title{font-weight:600;font-size:12.5px;color:#f0f6fc;flex:1 1 80px;min-width:60px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        ".pdf-meta{font-size:11px;color:#8b949e;white-space:nowrap;flex:none}"
        "@media(max-width:740px){.pdf-meta{display:none}}"
        ".pdf-btn{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:3px 7px;font-size:11.5px;font-weight:600;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:3px;user-select:none;white-space:nowrap;flex:none}"
        ".pdf-btn:hover,.pdf-btn.active{background:#30363d;color:#fff;border-color:#58a6ff}"
        ".pdf-zoom-readout{min-width:46px;justify-content:center;font-variant-numeric:tabular-nums;color:#f0f6fc}"
        ".pdf-stage{flex:1 1 auto;min-height:0;width:100%;overflow:auto;box-sizing:border-box;background:#0d1117;outline:none}"
        ".pdf-stage.is-zoomed{cursor:grab}"
        ".pdf-stage.is-dragging{cursor:grabbing;user-select:none}"
        ".pdf-main{width:100%;max-width:1040px;margin:0 auto;padding:8px 8px 40px;box-sizing:border-box;display:flex;flex-direction:column;gap:14px}"
        ".pdf-page-card{background:#161b22;border:1px solid #30363d;border-radius:8px;overflow:hidden;box-shadow:0 4px 16px rgba(0,0,0,0.35)}"
        ".pdf-page-hdr{padding:4px 10px;background:#0d1117;border-bottom:1px solid #21262d;font-size:10.5px;font-weight:600;color:#8b949e;display:flex;justify-content:space-between}"
        ".pdf-page-img{display:block;width:100%;height:auto;background:#fff;user-select:none;-webkit-user-drag:none}"
        "</style></head><body>"
        "<div class='pdf-bar' onmousedown='event.preventDefault()'>"
        f"<span class='pdf-badge'>{ext_badge}</span>"
        f"<span class='pdf-title' title='{fname}'>{fname}</span>"
        f"<span class='pdf-meta'>{page_count}p</span>"
        "<button type='button' class='pdf-btn' onmousedown='event.preventDefault()' onclick='scrollStep(-1);restoreParentSayFocus(true);' title='Scroll Up'>⬆</button>"
        "<button type='button' class='pdf-btn' onmousedown='event.preventDefault()' onclick='scrollStep(1);restoreParentSayFocus(true);' title='Scroll Down'>⬇</button>"
        "<button type='button' class='pdf-btn' id='pdfZoomOut' onmousedown='event.preventDefault()' onclick='adjustZoom(-20);restoreParentSayFocus(true);' title='Zoom Out PDF (Ctrl −)'>−</button>"
        "<button type='button' class='pdf-btn pdf-zoom-readout' id='pdfZoomReadout' onmousedown='event.preventDefault()' onclick='setZoom(100);restoreParentSayFocus(true);' title='Fit Width / 100% (Ctrl 0)'>100%</button>"
        "<button type='button' class='pdf-btn' id='pdfZoomIn' onmousedown='event.preventDefault()' onclick='adjustZoom(20);restoreParentSayFocus(true);' title='Zoom In PDF (Ctrl +)'>+</button>"
        "<button type='button' class='pdf-btn' id='pdfFitToggle' onmousedown='event.preventDefault()' onclick='toggleFitPage();restoreParentSayFocus(true);' title='Toggle Fit Full Page vs Fit Width'>Fit Page</button>"
        f"<a class='pdf-btn' href='{_html.escape(native_url, quote=True)}' target='_blank' rel='noopener' title='Open raw PDF'>Native</a>"
        f"<a class='pdf-btn' href='{_html.escape(dl_url, quote=True)}' title='Download file'>⬇ Save</a>"
        "</div>"
        f"<div class='pdf-stage' id='pdfStage' tabindex='-1'><main class='pdf-main' id='pdfMain'>{''.join(pages_html)}</main></div>"
        "<script>"
        "var curZoom = 100, fitPageOn = false;"
        "var MIN_ZOOM = 35, MAX_ZOOM = 300;"
        "window.__anchorPdfViewer = true;"
        "function getStage(){ return document.getElementById('pdfStage'); }"
        "function scrollStep(dir){"
        "  var st = getStage();"
        "  var h = st ? st.clientHeight : window.innerHeight;"
        "  var dy = dir * Math.max(300, h * 0.78);"
        "  if(st) st.scrollBy({top: dy, behavior: 'smooth'});"
        "  else window.scrollBy({top: dy, behavior: 'smooth'});"
        "}"
        "function computeFitPageZoom(){"
        "  var st = getStage(), img = document.querySelector('.pdf-page-img');"
        "  if(!st) return 100;"
        "  var availW = Math.max(200, Math.min(1040, st.clientWidth) - 16);"
        "  var availH = Math.max(180, st.clientHeight - 48);"
        "  var ratio = (img && img.naturalWidth > 0 && img.naturalHeight > 0) ? (img.naturalHeight / img.naturalWidth) : (792 / 612);"
        "  var fitPageW = availH / ratio;"
        "  return Math.max(MIN_ZOOM, Math.min(100, Math.round((fitPageW / availW) * 100)));"
        "}"
        "function toggleFitPage(){"
        "  var btn = document.getElementById('pdfFitToggle');"
        "  if(!fitPageOn){"
        "    fitPageOn = true;"
        "    if(btn){ btn.classList.add('active'); btn.textContent = 'Fit Width'; }"
        "    applyZoom(computeFitPageZoom(), null, null, true);"
        "  } else {"
        "    fitPageOn = false;"
        "    if(btn){ btn.classList.remove('active'); btn.textContent = 'Fit Page'; }"
        "    applyZoom(100, null, null, true);"
        "  }"
        "}"
        "function applyZoom(nextZoom, clientX, clientY, keepFitFlag){"
        "  var st = getStage(), m = document.getElementById('pdfMain');"
        "  if(!st || !m) return curZoom;"
        "  if(!keepFitFlag){"
        "    fitPageOn = false;"
        "    var fb = document.getElementById('pdfFitToggle');"
        "    if(fb){ fb.classList.remove('active'); fb.textContent = 'Fit Page'; }"
        "  }"
        "  var clamped = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, Math.round(nextZoom)));"
        "  var prevRect = m.getBoundingClientRect();"
        "  var stageRect = st.getBoundingClientRect();"
        "  var fx = (typeof clientX === 'number') ? (clientX - stageRect.left) : (st.clientWidth / 2);"
        "  var fy = (typeof clientY === 'number') ? (clientY - stageRect.top) : (st.clientHeight / 2);"
        "  var prevW = Math.max(1, m.offsetWidth);"
        "  var prevH = Math.max(1, m.offsetHeight);"
        "  var docX = (st.scrollLeft + fx - Math.max(0, prevRect.left - stageRect.left + st.scrollLeft)) / prevW;"
        "  var docY = (st.scrollTop + fy) / prevH;"
        "  curZoom = clamped;"
        "  var availW = Math.max(200, st.clientWidth);"
        "  var baseW = Math.min(1040, availW);"
        "  if(curZoom === 100){"
        "    m.style.width = '100%';"
        "    m.style.maxWidth = '1040px';"
        "    m.style.margin = '0 auto';"
        "  } else {"
        "    var px = Math.max(180, Math.round(baseW * (curZoom / 100)));"
        "    m.style.width = px + 'px';"
        "    m.style.maxWidth = 'none';"
        "    m.style.margin = (px < availW) ? '0 auto' : '0';"
        "  }"
        "  var rd = document.getElementById('pdfZoomReadout');"
        "  if(rd) rd.textContent = curZoom + '%';"
        "  st.classList.toggle('is-zoomed', m.offsetWidth > st.clientWidth + 2);"
        "  var newW = Math.max(1, m.offsetWidth);"
        "  var newH = Math.max(1, m.offsetHeight);"
        "  if(curZoom <= 100){"
        "    st.scrollLeft = 0;"
        "  } else {"
        "    st.scrollLeft = Math.max(0, Math.round(docX * newW - fx));"
        "  }"
        "  st.scrollTop = Math.max(0, Math.round(docY * newH - fy));"
        "  return curZoom;"
        "}"
        "function setZoom(z, cx, cy){ return applyZoom(z, cx, cy); }"
        "function adjustZoom(delta, cx, cy){ return applyZoom(curZoom + delta, cx, cy); }"
        "window.__anchorPdfZoom = function(step, cx, cy){"
        "  var s = Number(step);"
        "  if(s === 0) return setZoom(100, cx, cy);"
        "  return adjustZoom(s > 0 ? 20 : -20, cx, cy);"
        "};"
        "window.__anchorGetPdfZoom = function(){ return curZoom; };"
        "function restoreParentSayFocus(force){"
        "  try {"
        "    if(window.parent && window.parent !== window && typeof window.parent.__restoreSayFocusIfActive === 'function'){"
        "      if(force || window.parent.__dictationActive){"
        "        window.parent.__restoreSayFocusIfActive();"
        "      }"
        "    }"
        "  } catch(_e){}"
        "}"
        "document.addEventListener('keydown', function(ev){"
        "  if((ev.ctrlKey || ev.metaKey) && !ev.altKey){"
        "    var k = ev.key || '';"
        "    var step = (k === '+' || k === '=' || ev.code === 'NumpadAdd') ? 1"
        "      : (k === '-' || k === '_' || ev.code === 'NumpadSubtract') ? -1"
        "      : (k === '0' || ev.code === 'Numpad0') ? 0 : null;"
        "    if(step !== null){"
        "      ev.preventDefault();"
        "      ev.stopImmediatePropagation();"
        "      window.__anchorPdfZoom(step);"
        "      return;"
        "    }"
        "  }"
        "  if(!ev.ctrlKey && !ev.metaKey && !ev.altKey){"
        "    var st = getStage();"
        "    if(!st) return;"
        "    if(ev.key === 'PageDown'){ ev.preventDefault(); scrollStep(1); }"
        "    else if(ev.key === 'PageUp'){ ev.preventDefault(); scrollStep(-1); }"
        "    else if(ev.key === 'ArrowDown'){ ev.preventDefault(); st.scrollBy({top: 64}); }"
        "    else if(ev.key === 'ArrowUp'){ ev.preventDefault(); st.scrollBy({top: -64}); }"
        "    else if(ev.key === 'ArrowRight'){ ev.preventDefault(); st.scrollBy({left: 64}); }"
        "    else if(ev.key === 'ArrowLeft'){ ev.preventDefault(); st.scrollBy({left: -64}); }"
        "  }"
        "}, true);"
        "window.addEventListener('wheel', function(ev){"
        "  if(ev.ctrlKey || ev.metaKey){"
        "    if(ev.deltaY){"
        "      ev.preventDefault();"
        "      ev.stopImmediatePropagation();"
        "      adjustZoom(ev.deltaY < 0 ? 15 : -15, ev.clientX, ev.clientY);"
        "    }"
        "    return;"
        "  }"
        "  restoreParentSayFocus(false);"
        "}, {capture: true, passive: false});"
        "(function(){"
        "  var st = getStage(), dragging = false, sx = 0, sy = 0, sl = 0, stp = 0;"
        "  if(!st) return;"
        "  st.addEventListener('mousedown', function(ev){"
        "    if(ev.button !== 0) return;"
        "    try { st.focus({preventScroll: true}); } catch(_e){}"
        "    if(st.scrollWidth <= st.clientWidth + 2) return;"
        "    dragging = true; sx = ev.clientX; sy = ev.clientY; sl = st.scrollLeft; stp = st.scrollTop;"
        "    st.classList.add('is-dragging');"
        "    ev.preventDefault();"
        "  });"
        "  window.addEventListener('mousemove', function(ev){"
        "    if(!dragging) return;"
        "    st.scrollLeft = Math.max(0, sl - (ev.clientX - sx));"
        "    st.scrollTop = Math.max(0, stp - (ev.clientY - sy));"
        "  });"
        "  window.addEventListener('mouseup', function(){"
        "    if(dragging){ dragging = false; st.classList.remove('is-dragging'); }"
        "  });"
        "  window.addEventListener('resize', function(){"
        "    if(fitPageOn) applyZoom(computeFitPageZoom(), null, null, true);"
        "    else if(curZoom !== 100) applyZoom(curZoom);"
        "  });"
        "})();"
        "window.addEventListener('message', function(ev){"
        "  if(!ev || !ev.data) return;"
        "  if(ev.data.type === 'anchor-scroll-deliverable'){"
        "    var st = getStage();"
        "    var dy = Number(ev.data.deltaY) || 420;"
        "    if(st) st.scrollBy({top: dy, behavior: 'smooth'});"
        "    else window.scrollBy({top: dy, behavior: 'smooth'});"
        "  } else if(ev.data.type === 'anchor-pdf-zoom'){"
        "    window.__anchorPdfZoom(ev.data.step);"
        "  }"
        "});"
        "document.addEventListener('mouseup', function(){"
        "  try {"
        "    var sel = window.getSelection ? String(window.getSelection()) : '';"
        "    if(!sel) restoreParentSayFocus(false);"
        "  } catch(_e){}"
        "});"
        "</script></body></html>"
    )
    return {"__html__": html_doc}, 200


def _serve_html_scrollview(real_path: str, qs: dict, rel: str, cdir: str):
    """Wrap an HTML deliverable in Anchor's dark split-pane document frame while keeping
    the inner document strictly sandboxed (opaque origin, no allow-same-origin) and auto-fitting
    wide print/briefing sheets (e.g. 820px Letter HTML reports) cleanly to the pane width."""
    import html as _html
    try:
        raw_html = Path(real_path).read_text(encoding="utf-8", errors="replace")
    except Exception:
        cd_fb = _format_content_disposition("inline", os.path.basename(real_path))
        return {"__file__": real_path, "__ctype__": "text/html; charset=utf-8", "__disposition__": "inline",
                "__content_disposition__": cd_fb, "__csp__": sandbox_csp_for("text/html; charset=utf-8")}, 200

    pid_q = _q(str(qs.get("pid", "")))
    dir_q = _q(str(qs.get("dir", "")))
    rel_q = _q(str(rel or ""))
    tok_q = ("&token=" + _q(str(qs.get("token")))) if qs.get("token") else ""
    hash_q = ("&hash=" + _q(str(qs.get("hash")))) if qs.get("hash") else ""
    dl_ext = Path(str(rel or real_path)).suffix.lower() or ".html"
    clean_fn = _resolve_clean_download_filename(cdir, rel, real_path, dl_ext, qs)
    fn_q = "&filename=" + _q(clean_fn)
    raw_url = f"/api/steward/deliverable-file?pid={pid_q}&dir={dir_q}&path={rel_q}{hash_q}&raw=1{tok_q}"
    dl_url = f"/api/steward/deliverable-file?pid={pid_q}&dir={dir_q}&path={rel_q}{hash_q}&download=1{fn_q}{tok_q}"
    fname = _html.escape(clean_fn or os.path.basename(real_path))

    fit_snippet = (
        "<style id='anchor-html-fit-style'>"
        "img,svg,video,canvas{max-width:100%;height:auto}"
        "</style>"
        "<script id='anchor-html-fit-script'>"
        "(function(){"
        "  var userPct = 100, baseW = 0;"
        "  function measureNaturalW(){"
        "    var de = document.documentElement, b = document.body;"
        "    if(!de) return window.innerWidth || 800;"
        "    var prevZ = de.style.zoom || '';"
        "    de.style.zoom = '1';"
        "    var w = Math.max(de.scrollWidth || 0, b ? b.scrollWidth : 0);"
        "    de.style.zoom = prevZ;"
        "    return w;"
        "  }"
        "  function applyFit(){"
        "    var de = document.documentElement;"
        "    if(!de || !window.innerWidth) return;"
        "    if(!baseW || baseW < 200) baseW = measureNaturalW();"
        "    var fitRatio = (baseW > window.innerWidth + 4) ? ((window.innerWidth - 8) / baseW) : 1;"
        "    var z = Math.max(0.35, Math.min(3.0, fitRatio * (userPct / 100)));"
        "    de.style.zoom = String(Math.round(z * 1000) / 1000);"
        "    try { parent.postMessage({type:'anchor-html-zoom-state', pct: userPct, eff: Math.round(z * 100)}, '*'); } catch(_e){}"
        "  }"
        "  window.addEventListener('load', function(){ baseW = 0; applyFit(); });"
        "  window.addEventListener('resize', applyFit);"
        "  setTimeout(applyFit, 60); setTimeout(applyFit, 300);"
        "  window.addEventListener('message', function(ev){"
        "    if(!ev || !ev.data) return;"
        "    if(ev.data.type === 'anchor-doc-zoom'){"
        "      if(ev.data.step === 0) userPct = 100;"
        "      else userPct = Math.max(50, Math.min(260, userPct + (ev.data.step > 0 ? 15 : -15)));"
        "      applyFit();"
        "    } else if(ev.data.type === 'anchor-scroll-deliverable'){"
        "      window.scrollBy({top: Number(ev.data.deltaY) || 400, behavior: 'smooth'});"
        "    }"
        "  });"
        "  document.addEventListener('keydown', function(ev){"
        "    if(!(ev.ctrlKey || ev.metaKey) || ev.altKey) return;"
        "    var k = ev.key || '';"
        "    var s = (k==='+'||k==='='||ev.code==='NumpadAdd')?1:(k==='-'||k==='_'||ev.code==='NumpadSubtract')?-1:(k==='0'||ev.code==='Numpad0')?0:null;"
        "    if(s !== null){ ev.preventDefault(); ev.stopImmediatePropagation(); if(s===0) userPct=100; else userPct=Math.max(50,Math.min(260,userPct+(s>0?15:-15))); applyFit(); }"
        "  }, true);"
        "  window.addEventListener('wheel', function(ev){"
        "    if((ev.ctrlKey || ev.metaKey) && ev.deltaY){ ev.preventDefault(); ev.stopImmediatePropagation(); userPct=Math.max(50,Math.min(260,userPct+(ev.deltaY<0?15:-15))); applyFit(); }"
        "  }, {capture:true, passive:false});"
        "})();"
        "</script>"
    )
    lower_raw = raw_html.lower()
    body_close = lower_raw.rfind("</body>")
    if body_close >= 0:
        augmented_html = raw_html[:body_close] + fit_snippet + raw_html[body_close:]
    else:
        augmented_html = raw_html + fit_snippet
    escaped_srcdoc = _html.escape(augmented_html, quote=True)

    wrapper = (
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width,initial-scale=1'>"
        f"<title>{fname}</title>"
        "<style>"
        "html,body{height:100%;margin:0;padding:0;overflow:hidden;display:flex;flex-direction:column;"
        "background:#0d1117;color:#e6edf3;font:13.5px/1.45 -apple-system,'Segoe UI',system-ui,sans-serif}"
        ".pdf-bar{flex:0 0 auto;width:100%;box-sizing:border-box;background:rgba(22,27,34,0.96);"
        "border-bottom:1px solid #30363d;padding:5px 10px;display:flex;align-items:center;gap:5px;flex-wrap:wrap}"
        ".pdf-badge{font-size:10px;font-weight:700;padding:2px 6px;border-radius:4px;background:rgba(56,189,248,0.16);color:#7dd3fc;border:1px solid rgba(56,189,248,0.4);letter-spacing:.04em;flex:none}"
        ".pdf-title{font-weight:600;font-size:12.5px;color:#f0f6fc;flex:1 1 80px;min-width:60px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}"
        ".pdf-btn{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:5px;padding:3px 7px;font-size:11.5px;font-weight:600;cursor:pointer;text-decoration:none;display:inline-flex;align-items:center;gap:3px;user-select:none;white-space:nowrap;flex:none}"
        ".pdf-btn:hover{background:#30363d;color:#fff;border-color:#58a6ff}"
        ".pdf-zoom-readout{min-width:46px;justify-content:center;font-variant-numeric:tabular-nums;color:#f0f6fc}"
        "#htmlDocFrame{flex:1 1 auto;width:100%;height:100%;min-height:0;border:0;background:#fff}"
        "</style></head><body>"
        "<div class='pdf-bar' onmousedown='event.preventDefault()'>"
        "<span class='pdf-badge'>HTML</span>"
        f"<span class='pdf-title' title='{fname}'>{fname}</span>"
        "<button type='button' class='pdf-btn' onmousedown='event.preventDefault()' onclick='sendScroll(-1)' title='Scroll Up'>⬆</button>"
        "<button type='button' class='pdf-btn' onmousedown='event.preventDefault()' onclick='sendScroll(1)' title='Scroll Down'>⬇</button>"
        "<button type='button' class='pdf-btn' onmousedown='event.preventDefault()' onclick='window.__anchorPdfZoom(-1)' title='Zoom Out (Ctrl −)'>−</button>"
        "<button type='button' class='pdf-btn pdf-zoom-readout' id='htmlZoomReadout' onmousedown='event.preventDefault()' onclick='window.__anchorPdfZoom(0)' title='Auto-Fit to Pane (Ctrl 0)'>Fit</button>"
        "<button type='button' class='pdf-btn' onmousedown='event.preventDefault()' onclick='window.__anchorPdfZoom(1)' title='Zoom In (Ctrl +)'>+</button>"
        f"<a class='pdf-btn' href='{_html.escape(raw_url, quote=True)}' target='_blank' rel='noopener' title='Open unscaled raw HTML'>Raw</a>"
        f"<a class='pdf-btn' href='{_html.escape(dl_url, quote=True)}' title='Download file'>⬇ Save</a>"
        "</div>"
        f"<iframe id='htmlDocFrame' sandbox='allow-scripts allow-popups allow-forms allow-modals allow-downloads' srcdoc=\"{escaped_srcdoc}\"></iframe>"
        "<script>"
        "window.__anchorPdfViewer = true;"
        "var f = document.getElementById('htmlDocFrame');"
        "window.__anchorPdfZoom = function(step){"
        "  try { if(f && f.contentWindow) f.contentWindow.postMessage({type:'anchor-doc-zoom', step: Number(step)}, '*'); } catch(_e){}"
        "};"
        "function sendScroll(dir){"
        "  try { if(f && f.contentWindow) f.contentWindow.postMessage({type:'anchor-scroll-deliverable', deltaY: dir * Math.max(300, window.innerHeight * 0.75)}, '*'); } catch(_e){}"
        "}"
        "window.addEventListener('message', function(ev){"
        "  if(!ev || !ev.data) return;"
        "  if(ev.data.type === 'anchor-html-zoom-state'){"
        "    var rd = document.getElementById('htmlZoomReadout');"
        "    if(rd) rd.textContent = (ev.data.pct === 100) ? ('Fit' + (ev.data.eff < 99 ? ' ' + ev.data.eff + '%' : '')) : (ev.data.pct + '%');"
        "  } else if(ev.data.type === 'anchor-scroll-deliverable'){"
        "    try { if(f && f.contentWindow) f.contentWindow.postMessage(ev.data, '*'); } catch(_e){}"
        "  }"
        "});"
        "</script></body></html>"
    )
    return {"__html__": wrapper}, 200


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
    ext = Path(target).suffix.lower()
    if ext not in (".md", ".txt", ".json", ".csv", ".log") and ext not in _SOURCE_TEXT:
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
    if verb in ("wave-state", "wave-map"):
        from steward_cockpit import wave_map_model as _wmm
        try:
            res_w = _wmm.mutate_wave_state(cdir, body)
        except _wmm.WaveStateValidationError as exc:
            return {"ok": False, "error": str(exc)}, 400
        _DELIV_CACHE.clear()
        return res_w, 200
    if verb == "deliverable-batches":
        from steward_cockpit import deliverable_shelves as _ds
        res_b = _ds.update_curation(cdir, body if isinstance(body, dict) else {})
        _DELIV_CACHE.clear()
        return res_b, 200
    if verb == "plan":
        if not cdir or not os.path.isdir(str(cdir)):
            return _plan_missing_response()
        if not isinstance(body, dict):
            return _plan_garbage_response()
        op = body.get("op") if body.get("op") is not None else body.get("action")
        from tools import steward_plan as _splan
        try:
            res = _splan.mutate_plan_state(cdir, op, body)
        except Exception as exc:
            return _plan_http_error(exc)
        _DELIV_CACHE.clear()
        return res, 200
    if verb in ("dismiss-deliverable", "deliverables/dismiss", "approve-deliverable", "deliverables/approve"):
        default_disp = "approved" if verb in ("approve-deliverable", "deliverables/approve") else ""
        items = body.get("items")
        if isinstance(items, list) and items:
            last_res = {"ok": True, "dismissed_count": 0}
            for it in items:
                if isinstance(it, dict):
                    disp = str(it.get("disposition") or body.get("disposition") or default_disp or "")
                    sid = str(it.get("step_id") or it.get("owner_step_id") or body.get("step_id") or "")
                    last_res = campaign.dismiss_deliverable(
                        cdir,
                        path=str(it.get("path") or ""),
                        product_id=str(it.get("product_id") or ""),
                        what=str(it.get("what") or ""),
                        revision_id=str(it.get("revision_id") or ""),
                        hash_val=str(it.get("hash") or ""),
                        disposition=disp,
                        step_id=sid,
                    )
            if not os.environ.get("PYTEST_CURRENT_TEST"):
                try:
                    campaign.sync_steward_projections(cdir)
                except Exception:
                    pass
            _DELIV_CACHE.clear()
            return last_res, 200
        disp = str(body.get("disposition") or default_disp or "")
        sid = str(body.get("step_id") or body.get("owner_step_id") or "")
        result = campaign.dismiss_deliverable(
            cdir,
            path=str(body.get("path") or ""),
            product_id=str(body.get("product_id") or ""),
            what=str(body.get("what") or ""),
            revision_id=str(body.get("revision_id") or ""),
            hash_val=str(body.get("hash") or ""),
            disposition=disp,
            step_id=sid,
        )
        if not os.environ.get("PYTEST_CURRENT_TEST"):
            try:
                campaign.sync_steward_projections(cdir)
            except Exception:
                pass
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
        import paths as _paths
        req_id = str(body.get("step_id") or body.get("step") or "").strip()
        rm_path = Path(cdir) / "roadmap.json"
        st_path = Path(cdir) / "strip.json"
        lock_path = Path(cdir) / ".ecgberht" / "plan.lock"
        done_id, done_name, next_id, next_name = "", "", "", ""
        try:
            with _paths.cross_process_lock(lock_path, timeout_sec=2.0):
                try:
                    st_data = json.loads(st_path.read_text(encoding="utf-8")) if st_path.is_file() else {}
                except Exception:
                    st_data = {}
                cur_strip_id = str((st_data.get("strip") or st_data).get("current_step_id") or "").strip()
                if rm_path.is_file():
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
                        target["done"] = True
                        target.pop("waiting_on", None)
                        done_id = str(target.get("id") or "")
                        done_name = str(target.get("name") or target.get("title") or done_id)
                        nxt = next((s for s in steps if isinstance(s, dict) and str(s.get("id") or "") != done_id and s.get("status") not in ("done", "completed", "withdrawn", "parked")), None)
                        if nxt is not None:
                            if not any(isinstance(s, dict) and s.get("status") == "active" for s in steps):
                                nxt["status"] = "active"
                            next_id = str(nxt.get("id") or "")
                            next_name = str(nxt.get("name") or nxt.get("title") or next_id)
                        rm["roadmap_projection"] = steps
                        rm["steps"] = steps
                        _paths.atomic_write_json(rm_path, rm)
                        campaign._JSON_FILE_CACHE.clear()
                if st_path.is_file() and isinstance(st_data, dict):
                    inner = st_data.get("strip") if isinstance(st_data.get("strip"), dict) else st_data
                    if next_id:
                        inner["current_step_id"] = next_id
                    if inner.get("waiting_on"):
                        inner["waiting_on"] = None
                    _paths.atomic_write_json(st_path, st_data)
                    campaign._JSON_FILE_CACHE.clear()
        except TimeoutError as exc:
            return _plan_http_error(exc)
        except Exception as exc:
            return {"ok": False, "error": str(exc)}, 400
        if done_id:
            try:
                campaign._record_plan_history_snapshot(
                    cdir,
                    steps,
                    label=f"{time.strftime('%Y-%m-%d')} · Completed '{done_name[:40]}'",
                    summary=f"Marked step '{done_name}' done" + (f" → active '{next_name}'" if next_name else ""),
                    trigger="step_done",
                )
            except Exception:
                pass
        _DELIV_CACHE.clear()
        return {"ok": True, "step_id": done_id or req_id, "step_name": done_name or req_id, "next_step_id": next_id, "next_step_name": next_name}, 200
    if verb in ("anvil", "anvil/walkthrough", "anvil/analyses", "anvil/discover", "anvil/scoping", "anvil/replication", "anvil/comprehension", "anvil/literature"):
        from steward_cockpit import anvil_session as _as
        from steward_cockpit import anvil_scoping_v6 as _as6
        from steward_cockpit import anvil_py_deps as _apd
        from steward_cockpit import anvil_replication_job as _arj
        from steward_cockpit import anvil_verification_guard as _avg
        from steward_cockpit import anvil_comprehension_engine as _ace
        from steward_cockpit import anvil_literature_job as _alj
        for _m_ref in (_as, _as6, _apd, _arj, _avg, _ace, _alj):
            try:
                _mt = Path(_m_ref.__file__).stat().st_mtime_ns
                if getattr(_m_ref, "_LOADED_MTIME_NS", None) != _mt:
                    importlib.reload(_m_ref)
                    _m_ref._LOADED_MTIME_NS = _mt
            except Exception:
                pass
        if not isinstance(body, dict):
            msg_g = "Malformed Anvil request or invalid engine output"
            return {"ok": False, "error_code": "MALFORMED_DATA_REFUSED", "status_kind": "dependency-returns-garbage", "failure_state": "dependency-returns-garbage", "error": msg_g, "message": msg_g}, 400
        act = (
            "walkthrough"
            if verb == "anvil/walkthrough"
            else (
                "discover_candidates"
                if verb == "anvil/discover"
                else str(body.get("action") or ("list_analyses" if verb == "anvil/analyses" else "start_code")).strip()
            )
        )
        aid_post = body.get("analysis_id") if "analysis_id" in body else None
        try:
            if act in ("discover", "discover_candidates"):
                return _as.discover_cockpit_candidates_http(cdir)
            if act == "scoping_preview":
                return _as.get_scoping_v2_state(
                    cdir,
                    selected_module_ids=body["module_ids"] if "module_ids" in body else body.get("selected_module_ids"),
                    software_spec=body.get("software_spec") if "software_spec" in body else body.get("software_target"),
                    paper_spec=body.get("paper_spec") if "paper_spec" in body else body.get("paper_target"),
                    analysis_id=aid_post,
                    require_v6=True,
                )
            if act in ("scoping", "scoping_state"):
                return _as.get_scoping_v2_state(
                    cdir,
                    selected_module_ids=body["module_ids"] if "module_ids" in body else body.get("selected_module_ids"),
                    software_spec=body.get("software_spec") if "software_spec" in body else body.get("software_target"),
                    paper_spec=body.get("paper_spec") if "paper_spec" in body else body.get("paper_target"),
                    analysis_id=aid_post,
                    require_v6=False,
                )
            if act in ("replication_state", "replication_status"):
                from steward_cockpit import anvil_replication_job as _arj
                return _arj.get_replication_state(cdir, analysis_id=aid_post, job_id=body.get("job_id"))
            if act in ("replication_consent", "issue_replication_consent"):
                from steward_cockpit import anvil_replication_job as _arj
                return _arj.issue_replication_consent(cdir, body)
            if act in ("replication_start", "replication_phase_b", "run_replication"):
                from steward_cockpit import anvil_replication_job as _arj
                eff_body = dict(body)
                if act == "replication_phase_b" and "phase" not in eff_body:
                    eff_body["phase"] = "B"
                out = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, eff_body, lambda: _arj.start_replication_job(cdir, eff_body)
                )
                return out if (isinstance(out, tuple) and len(out) == 2) else (out, 200)
            if act in ("replication_install_deps", "approve_replication_deps"):
                from steward_cockpit import anvil_replication_job as _arj
                out = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body, lambda: _arj.approve_install_and_run_replication(cdir, body)
                )
                return out if (isinstance(out, tuple) and len(out) == 2) else (out, 200)
            if act in ("replication_cancel", "cancel_replication"):
                from steward_cockpit import anvil_replication_job as _arj
                return _arj.cancel_replication_job(cdir, body)
            if act in ("replication_queue_refactor", "queue_refactoring"):
                from steward_cockpit import anvil_replication_job as _arj
                return _arj.queue_vetted_refactoring(cdir, body)
            if act in ("replication_export_deliverables", "export_replication_deliverables"):
                from steward_cockpit import anvil_replication_job as _arj
                return _arj.export_replication_deliverables(cdir, body)
            if act in ("scoping_turn", "scoping_chat"):
                out = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body, lambda: _as.run_scoping_v2_turn(cdir, body)
                )
                return out if (isinstance(out, tuple) and len(out) == 2) else (out, 200)
            if act in ("lock_scope", "scoping_lock"):
                out = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body, lambda: _as.lock_scope_v2(cdir, body)
                )
                return out if (isinstance(out, tuple) and len(out) == 2) else (out, 200)
            if act == "quick_literature_sketch":
                out = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body, lambda: _as.run_quick_literature_sketch(cdir, body)
                )
                return out if (isinstance(out, tuple) and len(out) == 2) else (out, 200)
            if act in ("semantic_state", "comprehension_state"):
                return _ace.get_comprehension_state(cdir, scope_sha256=body.get("scope_sha256"), analysis_id=aid_post)
            if act in ("semantic_consent", "issue_comprehension_consent"):
                return _ace.issue_comprehension_consent(cdir, body)
            if act in ("semantic_run", "run_comprehension", "run_pass2"):
                out = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body, lambda: _ace.run_semantic_comprehension(cdir, body)
                )
                return out if (isinstance(out, tuple) and len(out) == 2) else (out, 200)
            if act in ("literature_state", "get_literature"):
                return _alj.get_literature_state(cdir, analysis_id=aid_post)
            if act in ("literature_consent", "issue_literature_consent"):
                return _alj.issue_literature_consent(cdir, body)
            if act in ("literature_start", "run_literature"):
                out = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body, lambda: _alj.start_literature_job(cdir, body)
                )
                return out if (isinstance(out, tuple) and len(out) == 2) else (out, 200)
            if act in ("literature_cancel", "cancel_literature"):
                return _alj.cancel_literature_job(cdir, body)
            if act in ("analyses", "list_analyses"):
                return _as.list_cockpit_analyses(cdir, include_archived=bool(body.get("include_archived")))
            if act in ("register_legacy", "register_legacy_analysis"):
                return _as.register_legacy_analysis(
                    cdir,
                    analysis_id=aid_post,
                    title=str(body.get("title") or ""),
                )
            if act in ("create_analysis", "new_analysis"):
                out = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body,
                    lambda: _as.create_cockpit_analysis(
                        cdir,
                        analysis_id=aid_post,
                        title=str(body.get("title") or ""),
                        mode=str(body.get("mode") or "code"),
                        software_spec=str(body.get("software_target") or body.get("software_spec") or "."),
                        compare_spec=str(body.get("compare_target") or ""),
                        paper_spec=str(body.get("paper_target") or body.get("paper_spec") or ""),
                        direction=body.get("direction", ""),
                        active_pipeline=str(body.get("active_pipeline") or ""),
                        selected_pipelines=body.get("selected_pipelines"),
                        materialize_replication_package=body.get("materialize_replication_package", True),
                        max_concurrency=body.get("max_concurrency", 2),
                        set_active=bool(body.get("set_active", True)),
                    ),
                )
                return out if (isinstance(out, tuple) and len(out) == 2) else (out, 200)
            if act in ("switch_analysis", "switch"):
                return _as.switch_cockpit_analysis(cdir, aid_post)
            if act in ("export_replication_package", "materialize_replication_package"):
                raw_cf = body.get("closure_files")
                cf_list = [str(x) for x in raw_cf] if isinstance(raw_cf, list) else None
                raw_ap = str(body.get("active_pipeline") or "").strip() or None
                return _as.export_replication_package(
                    cdir,
                    analysis_id=aid_post,
                    closure_files=cf_list,
                    active_pipeline=raw_ap,
                )
            if act == "v4_session":
                return _as.save_v4_cockpit_ui_session(cdir, body, analysis_id=aid_post)
            if act == "v4_chat":
                out = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body, lambda: _as.run_v4_cockpit_chat(cdir, body, analysis_id=aid_post)
                )
                return out if (isinstance(out, tuple) and len(out) == 2) else (out, 200)
            if act in ("v4_xval", "xval_audit"):
                out = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body, lambda: _as.run_v4_cockpit_xval(cdir, body, analysis_id=aid_post)
                )
                return out if (isinstance(out, tuple) and len(out) == 2) else (out, 200)
            if act in ("trace_install_deps", "approve_trace_deps"):
                out = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body, lambda: _as.approve_install_and_run_trace(cdir, body, analysis_id=aid_post)
                )
                return out if (isinstance(out, tuple) and len(out) == 2) else (out, 200)
            if act == "v4_trace":
                out = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body, lambda: _as.run_v4_cockpit_trace(cdir, body, analysis_id=aid_post)
                )
                return out if (isinstance(out, tuple) and len(out) == 2) else (out, 200)
            if act == "v4_profile_lit":
                out = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body, lambda: _as.run_v4_cockpit_profile_lit(cdir, body, analysis_id=aid_post)
                )
                return out if (isinstance(out, tuple) and len(out) == 2) else (out, 200)
            if act == "walkthrough":
                return _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body,
                    lambda: _as.walkthrough_in_session(
                        cdir,
                        str(body.get("block_id") or body.get("block") or ""),
                        analysis_id=aid_post,
                    ),
                ), 200
            if act in ("start_code", "start_paper"):
                res = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body,
                    lambda: _as.start_cockpit_session(
                        cdir,
                        mode="paper" if act == "start_paper" else str(body.get("mode") or "code"),
                        software_spec=str(body.get("software_target") or "."),
                        compare_spec=str(body.get("compare_target") or ""),
                        paper_spec=str(body.get("paper_target") or ""),
                        signed_off_drops=body.get("signed_off_drops") if isinstance(body.get("signed_off_drops"), list) else None,
                        analysis_id=aid_post,
                        title=str(body.get("title") or ""),
                        direction=body.get("direction", ""),
                        active_pipeline=str(body.get("active_pipeline") or ""),
                        selected_pipelines=body.get("selected_pipelines"),
                        materialize_replication_package=body.get("materialize_replication_package", True),
                        max_concurrency=body.get("max_concurrency", 2),
                        create_new=bool(body.get("create_new", False)),
                    ),
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
                raw_tcmd = body.get("test_cmd")
                if raw_tcmd is not None and raw_tcmd != "" and raw_tcmd != []:
                    if isinstance(raw_tcmd, (str, bytes)) or not isinstance(raw_tcmd, list) or body.get("operator_consent_confirmed") is not True:
                        return {
                            "ok": False,
                            "error_code": "EXECUTION_POLICY_REFUSED",
                            "cwe": "CWE-78",
                            "http_status": 403,
                            "error": "Raw probe_block.test_cmd strings are retired; pass an explicit argv list with operator_consent_confirmed: true.",
                            "message": "Raw probe_block.test_cmd strings are retired; pass an explicit argv list with operator_consent_confirmed: true.",
                        }, 403
                out_pb = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body,
                    lambda: _as.probe_block_in_session(
                        cdir,
                        str(body.get("block_id") or ""),
                        str(body.get("lock_description") or ""),
                        raw_tcmd if isinstance(raw_tcmd, list) else "",
                        analysis_id=aid_post,
                        operator_consent_confirmed=bool(body.get("operator_consent_confirmed")),
                    ),
                )
                return out_pb if (isinstance(out_pb, tuple) and len(out_pb) == 2) else (out_pb, 200)
            if act == "sign_off_drop":
                return _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body,
                    lambda: _as.sign_off_null_space_in_session(
                        cdir,
                        str(body.get("function_name") or ""),
                        analysis_id=aid_post,
                    ),
                ), 200
            if act == "attach_paper":
                return _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body,
                    lambda: _as.attach_paper_to_session(
                        cdir,
                        str(body.get("paper_target") or ""),
                        analysis_id=aid_post,
                    ),
                ), 200
            if act == "chat":
                q_str = str(body.get("question") or "").strip()
                res = _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body,
                    lambda: _as.chat_in_session(
                        cdir,
                        q_str,
                        str(body.get("mode") or "map"),
                        str(body.get("target") or ""),
                        analysis_id=aid_post,
                    ),
                )
                try:
                    eng = get_engine(cdir, create=False)
                    if eng is not None and q_str:
                        sess_obj = res.get("session") or {}
                        dlg = sess_obj.get("chat_history") or sess_obj.get("dialogue") or []
                        last_asst = next(
                            (
                                m.get("text")
                                for m in reversed(dlg)
                                if m.get("role") in ("anvil", "assistant") and m.get("text")
                            ),
                            "",
                        ) or str(res.get("reply") or "").strip()
                        eng._emit({"t": "john", "text": q_str})
                        if last_asst:
                            eng._emit({"t": "delta", "text": str(last_asst)})
                            eng._emit({"t": "turn_end", "tokens": 0})
                except Exception:
                    pass
                return res, 200
            if act == "reset":
                return _run_with_cockpit_usage_attribution(
                    "anvil", act, cdir, body,
                    lambda: _as.reset_cockpit_session(cdir, analysis_id=aid_post),
                ), 200
            msg_u = f"Malformed Anvil request or invalid engine output (unknown action: {act})"
            return {
                "ok": False,
                "error_code": "MALFORMED_DATA_REFUSED",
                "status_kind": "dependency-returns-garbage",
                "failure_state": "dependency-returns-garbage",
                "error": f"unknown anvil action: {act}",
                "message": msg_u,
            }, 400
        except ValueError as exc:
            if hasattr(exc, "payload") and hasattr(exc, "http_status"):
                return exc.payload, int(exc.http_status)
            msg = str(exc)
            msg_low = msg.lower()
            is_escape = any(
                tok in msg_low
                for tok in ("traversal", "permitted", "outside", "restricted", "symlink", "escape")
            )
            if is_escape:
                return {"ok": False, "error_code": "PATH_ESCAPE_REFUSED", "error": msg, "message": msg}, 403
            return {"ok": False, "error_code": "MALFORMED_DATA_REFUSED", "error": msg, "message": msg}, 400
    if verb == "aegis":
        if not isinstance(body, dict):
            return {
                "ok": False,
                "failure_state": "dependency-returns-garbage",
                "error": "Blocked unsafe path traversal or disallowed URL scheme",
                "message": "Blocked unsafe path traversal or disallowed URL scheme",
            }, 400
        act = str(body.get("action") or "scan").strip()
        if act not in ("scan", "bind_target", "remediate", "sign_off", "chat"):
            return {
                "ok": False,
                "failure_state": "dependency-returns-garbage",
                "error": "Blocked unsafe path traversal or disallowed URL scheme",
                "message": f"unknown aegis action: {act}",
            }, 400

        def _do_aegis_post(_aeg):
            if act in ("scan", "bind_target"):
                res = _run_with_cockpit_usage_attribution(
                    "aegis", act, cdir, body,
                    lambda: _aeg.run_cockpit_aegis_scan(
                        cdir,
                        target_spec=str(body.get("target") or "."),
                        signed_off_ids=body.get("signed_off_ids") if isinstance(body.get("signed_off_ids"), list) else None,
                        sync_anvil=bool(body.get("sync_anvil", act == "bind_target")),
                    ),
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
                return res
            if act == "remediate":
                return _run_with_cockpit_usage_attribution(
                    "aegis", act, cdir, body,
                    lambda: _aeg.run_cockpit_aegis_remediate(
                        cdir,
                        apply=bool(body.get("apply")),
                        rule_filter=str(body.get("rule") or ""),
                    ),
                )
            if act == "sign_off":
                return _run_with_cockpit_usage_attribution(
                    "aegis", act, cdir, body,
                    lambda: _aeg.sign_off_aegis_finding(
                        cdir,
                        str(body.get("finding_id") or ""),
                    ),
                )
            q_str = str(body.get("question") or "").strip()
            res = _run_with_cockpit_usage_attribution(
                "aegis", act, cdir, body,
                lambda: _aeg.chat_in_aegis_session(
                    cdir,
                    q_str,
                    str(body.get("target") or ""),
                ),
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
            return res

        return _run_aegis_route_contract(
            cdir,
            body,
            _do_aegis_post,
            verify_scanner_exec=(act in ("scan", "bind_target")),
        )
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
        if result.get("ok"):
            try:
                from steward_cockpit import deliverable_shelves as _ds
                _ds.sync_refinement_batches(cdir, refinement_state=result.get("state"), operation=body if isinstance(body, dict) else None)
            except Exception:
                pass
            _DELIV_CACHE.clear()
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
            _ep_raw = body.get("dictation_epoch")
            _ep_val = int(_ep_raw) if isinstance(_ep_raw, int) and not isinstance(_ep_raw, bool) else None
            _tr_res = _de.transcribe_audio(
                str(body.get("audio_b64") or ""),
                client_msg_id=str(body.get("client_msg_id") or ""),
                dictation_epoch=_ep_val,
                scope=str(body.get("scope") or cdir or ""),
            )
            return _tr_res, int(_tr_res.get("status_code") or 200)
        if act == "tts":
            return _de.synthesize_speech_wav(str(body.get("text") or ""), int(body.get("rate") or 1)), 200
        if act == "start":
            if getattr(_de, "_DICTATION_BACKEND_AVAILABLE", None) is False:
                return _draft_failure_response("dependency-missing", detail="Local dictation engine backend unavailable.")
            return _de.start_session(), 200
        if act == "stop":
            return _de.stop_session(), 200
        try:
            since = int(body.get("since") or 0)
        except (TypeError, ValueError):
            since = 0
        return _de.poll_session(since), 200
    if verb == "drafts":
        return handle_drafts_request("POST", body=body, proot=cdir)
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
        from steward_cockpit.steward_engine import execute_idempotent_say
        _client_msg_id = str(body.get("client_msg_id") or body.get("client_req_id") or "").strip()
        _say_scope = (
            f"{os.path.normcase(os.path.abspath(str(cdir or '')))}||general||{body.get('term') or '1'}"
            if body.get("general")
            else os.path.normcase(os.path.abspath(str(cdir or "")))
        )
        if body.get("goal"):
            _say_scope += f"||goal||{str(body.get('goal') or '').strip()}"

        def _execute_say_once():
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
                        spoken = say_campaign(_camp_dir, _txt, goal=_goal, run_fast_fallback=False)
                        if spoken and not spoken.get("ok") and "a goal has no seat" in str(spoken.get("say") or ""):
                            spoken_goal = fast_steward_command(_camp_dir, _txt, goal=_goal, from_cave=_is_cave, force_goal_seat=True)
                            if spoken_goal is not None:
                                spoken = spoken_goal
                    if spoken is not None:
                        if spoken.get("ok"):
                            _reply_txt = str(spoken.get("say") or spoken.get("receipt") or "")
                            note_goal_receipt(cdir, _goal, _txt, _reply_txt)
                            if _camp_dir != cdir and _goal:
                                note_goal_receipt(_camp_dir, _goal, _txt, _reply_txt)
                            try:
                                _live_eng = get_engine(cdir, create=False)
                                if _live_eng is not None:
                                    _live_eng._emit({"t": "john", "text": _txt})
                                    _live_eng._emit({"t": "delta", "text": _reply_txt})
                                    _live_eng._emit({"t": "turn_end", "tokens": 0})
                            except Exception:
                                pass
                        out_sp = dict(spoken)
                        out_sp["_http_code"] = 200 if spoken.get("ok") else 400
                        return out_sp
            context = body.get("refinement_context")
            _refined_turn = False
            if isinstance(context, dict):
                from steward_cockpit.refinement_client import update
                import uuid
                current = campaign.read_refinement(cdir)
                if not current or not current.get("ok"):
                    return {"ok": False, "error": "refinement-state-unavailable", "_http_code": 409}
                feedback_id = str(uuid.uuid4())
                result = update(cdir, {"operation_id": feedback_id, "expected_seq": current["sequence"],
                    "action": "feedback", "step_id": context.get("step_id"), "feedback_id": feedback_id,
                    "source_message": str(body.get("text", "")), "base_presentation_id": context.get("presentation_id"),
                    "changes": [{"id": "change-" + feedback_id, "scope": context.get("product_id") or "slice", "directive": "require", "text": str(body.get("text", ""))}],
                    "elegance": {"mode": "RC6", "source": "User selected Refine this slice", "reason": "Apply the user's requested changes within this slice; assess new elements before adding scope."}})
                if not result.get("ok"):
                    out_ref = dict(result)
                    out_ref["_http_code"] = 409
                    return out_ref
                from steward_cockpit import horizon as _horizon
                _horizon.refresh(cdir, "refined")       # W3 (2026-09-28): the line moves when the feedback is recorded
                _refined_turn = True
            if (Path(cdir) / ".anvil" / "session.json").is_file():
                try:
                    from steward_cockpit import anvil_session as _as_say
                    _as_say.apply_conversational_anvil_side_effects(cdir, str(body.get("text", "")))
                except Exception:
                    pass
            _reconciled_review = False
            if not body.get("general") and str(body.get("text") or "").strip():
                try:
                    _rec_res = campaign.reconcile_review_on_feedback(cdir, str(body.get("text") or ""))
                    _reconciled_review = bool((_rec_res or {}).get("reconciled", 0) > 0)
                    _DELIV_CACHE.clear()
                except Exception:
                    pass
            eng = get_engine(cdir, bool(body.get("general")),
                             str(body.get("term") or "") or None)
            if eng is None:
                return {"ok": False, "error": "no such session / cap hit", "_http_code": 404}
            if _reconciled_review and not body.get("question_id"):
                try:
                    eng.open_question = None
                    eng.question_context = None
                    eng.pending_questions = []
                except Exception:
                    pass
            import inspect as _inspect
            _say_kwargs = (
                {"question_id": body["question_id"]}
                if body.get("question_id")
                else {"goal": (str(body.get("goal") or "").strip() or None)}
            )
            try:
                if "client_msg_id" in _inspect.signature(eng.say).parameters:
                    _say_kwargs["client_msg_id"] = _client_msg_id or None
            except (TypeError, ValueError):
                pass
            result = eng.say(body.get("text", ""), **_say_kwargs)
            if _refined_turn:
                # W3 (Grok's hold): the turn's reply may have written the line — derive it again so the turn's own
                # sentence never stands over the stamped derivation
                from steward_cockpit import horizon as _horizon2
                _horizon2.refresh(cdir, "refined")
            out_res = dict(result) if isinstance(result, dict) else {"ok": False}
            out_res["_http_code"] = 200 if out_res.get("ok") else 409
            return out_res

        say_out = execute_idempotent_say(_say_scope, _client_msg_id, _execute_say_once, cdir=cdir)
        http_code = int(say_out.pop("_http_code", 200 if say_out.get("ok") else 409))
        if say_out.get("ok") and body.get("clear_draft") is not False and cdir and os.path.isdir(str(cdir)):
            try:
                handle_drafts_request(
                    "DELETE",
                    qs={
                        "general": "1" if body.get("general") else "",
                        "term": str(body.get("term") or ""),
                        "goal": str(body.get("goal") or ""),
                    },
                    proot=cdir,
                )
            except Exception:
                pass
        return say_out, http_code
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
        import paths as _paths_open
        if _paths_open.is_windows_service_or_session0():
            return {
                "ok": False,
                "error": "Anchor service is running in background Session 0; open this deliverable via its browser preview link instead.",
            }, 409
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
    user_name = "John"
    try:
        import onboard_wizard as _ow
        prof = _ow.get_active_user_profile()
        if isinstance(prof, dict) and prof.get("configured") and str(prof.get("display_name") or "").strip():
            user_name = str(prof.get("display_name")).strip()
    except Exception:
        pass
    (d / "ECGBERHT.md").write_text(
        "# Ecgberht — Face (campaign memory)\n\n## North star\n\n\n"
        f"## Active effort\n\n- None yet.\n\n## Why next\n\n- Stand-up: {user_name} "
        "describes the effort; the steward drafts the goal and the map.\n\n"
        f"## Human wait\n\n- {user_name}: describe this effort.\n", encoding="utf-8")
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "effort"
    today_str = time.strftime("%Y-%m-%d")
    if not (d / "roadmap.json").exists():
        c_rm = {
            "schema": "ecgberht-roadmap-v0",
            "project_id": slug,
            "updated": today_str,
            "roadmap_events": [],
            "roadmap_projection": [
                {"id": "stage-0-intake", "name": f"Stage 0 Intake & Scope: {name}", "status": "active", "done_when": f"Scope and objectives locked for {name}"},
            ],
        }
        (d / "roadmap.json").write_text(json.dumps(c_rm, indent=2) + "\n", encoding="utf-8")
    if not (d / "strip.json").exists():
        c_strip = {
            "schema": "ecgberht-strip-v0",
            "project_id": slug,
            "face_path": "ECGBERHT.md",
            "as_of": today_str,
            "phase": "intake",
            "active_effort": name,
            "effort_status": "IN_PROGRESS",
            "current_step_id": "stage-0-intake",
            "next_recommended": f"Stage 0 Intake & Scope: {name}",
            "why_next": f"Stand-up: {user_name} describes the effort; the steward drafts the goal and the map.",
        }
        (d / "strip.json").write_text(json.dumps(c_strip, indent=2) + "\n", encoding="utf-8")
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
                "src": r"D:\WorkspaceArchive\Documents\Neuro-Circuit-Notes",
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
                    "src": r"D:\WorkspaceArchive\Downloads\Options-Flow-Scanner",
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
                    "src": r"D:\WorkspaceArchive\Desktop\BioCompute-SpikeSim",
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
                    "src": r"D:\WorkspaceArchive\Documents\repos\mcp-bridge-prototype",
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
                    "src": r"D:\WorkspaceArchive\Documents\Deals\Series-B-TermSheets-2026",
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

