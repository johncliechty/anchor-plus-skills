#!/usr/bin/env python3
"""
Anchor GUI — Local web-based dashboard with full read/write access.

Starts a local HTTP server that serves the interactive dashboard and provides
API endpoints so that every click (done, add, capture) writes directly to
the markdown files, logs changes, and refreshes the state.

Usage:
    python3 anchor_gui.py          # Opens dashboard in your default browser
    python3 anchor_gui.py --port 8777   # Use a custom port

Launch from Cowork by typing "Dashboard" — Claude will run this for you.
"""

import json, logging, os, re, socket, sys, threading, time, traceback, webbrowser
from datetime import datetime, date
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import parse_qs, quote as url_quote, urlparse
import html as html_lib

# ── Paths ──────────────────────────────────────────────────────────────
# Single-folder layout (was previously dual-folder PSU + Axmra; consolidated 2026-05-02).
# Wave 2: data paths resolve via the shared `paths` helper, honoring the
# ANCHOR_DATA_DIR env var (unset -> the code dir, so behavior is unchanged).
import paths as _paths
# Declarative HTTP route table + strangler dispatch substrate (rearch W7 / C2).
# Pure data + pure functions (stdlib only); the migrated handler *functions* live
# in this module and are looked up by name via _MIGRATED_HANDLERS below.
import route_table as _routes
# Per-pillar off-switch flags (rearch W3) + the ANCHOR_AUTH_WARN log-only soak
# recorder (rearch W8). The auth-mode flag governs the data-plane gate below:
# open (today) → serve; warn → log a would-401 but still serve; enforce (W9) → 401.
import pillar_flags as _pillar_flags
import auth_warn as _auth_warn

# Process-wide write lock: held around every markdown/JSON mutation so two
# concurrent mutating requests (ThreadingHTTPServer) cannot lose an update.
WRITE_LOCK = _paths.WRITE_LOCK

# ANCHOR_DIR is the *code* dir (used for static assets like anchor.ico).
ANCHOR_DIR = _paths.CODE_DIR

DASHBOARD_MD = _paths.dashboard_md()
PROJECTS_MD = _paths.projects_md()
INBOX_MD = _paths.inbox_md()
DOMAINS_DIR = _paths.domains_dir()
LOGS_DIR = _paths.logs_dir()
CANCELLED_MD = _paths.cancelled_md()
SAVED_FOR_LATER_MD = _paths.saved_for_later_md()

# Ensure data dirs exist (logs/, domains/, health_reports/). This is the GUI's
# explicit call — directory creation is no longer an import-time side effect of
# the shared helper.
_paths.ensure_data_dirs()

# ── Error Logging ─────────────────────────────────────────────────────
ERROR_LOG = LOGS_DIR / "errors.log"
ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
# Boot-time size rotation (2026-07 review: errors.log had grown to 7MB with no
# cap anywhere). One rotated generation is kept (errors.log.1); rotation happens
# only at process start so nothing races the live FileHandlers.
try:
    _ERRLOG_CAP = int(os.environ.get("ANCHOR_ERROR_LOG_MAX_BYTES", "") or 5 * 1024 * 1024)
    if ERROR_LOG.exists() and ERROR_LOG.stat().st_size > _ERRLOG_CAP:
        _rot = ERROR_LOG.with_suffix(".log.1")
        if _rot.exists():
            _rot.unlink()
        ERROR_LOG.rename(_rot)
except OSError:
    pass
logging.basicConfig(
    filename=str(ERROR_LOG),
    level=logging.ERROR,
    format="%(asctime)s — %(levelname)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# Also log INFO to the error log for server lifecycle events
_logger = logging.getLogger("anchor")
_logger.setLevel(logging.INFO)
# Guard against double-handler attach: if anchor_gui is imported more than once
# in the same interpreter (e.g. by anchor_healthcheck), only one FileHandler
# should remain on the logger. Also disable propagation so records don't also
# get written by the root logger's FileHandler (installed by basicConfig above)
# — that was producing duplicated lines in errors.log.
if not any(isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == str(ERROR_LOG)
           for h in _logger.handlers):
    _fh = logging.FileHandler(str(ERROR_LOG))
    _fh.setFormatter(logging.Formatter("%(asctime)s — %(levelname)s — %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    _logger.addHandler(_fh)
_logger.propagate = False


# ── Build identity (cache-bust) ────────────────────────────────────────
# Computed ONCE at process startup. Used by the self-healing client JS to
# detect a redeploy and force a cache-busting reload (and to kill any leftover
# service worker / Cache Storage left behind by an old Anchor build).
def _compute_build_id():
    import subprocess
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(ANCHOR_DIR),
            capture_output=True, text=True, timeout=5,
            creationflags=_paths.NO_WINDOW,
        )
        rev = (out.stdout or "").strip()
        if out.returncode == 0 and rev:
            return rev
    except Exception:
        pass
    # Fallback: mtime of this source file (changes on every redeploy).
    try:
        return str(int(os.path.getmtime(__file__)))
    except Exception:
        return "0"


BUILD_ID = _compute_build_id()


# Self-healing cache-bust client JS. Kept as a plain (non-f) string so it can
# be embedded verbatim in BOTH the f-string dashboard page (generate_html) and
# the concatenated project-window page without brace-doubling concerns. The
# build id is substituted via a simple placeholder, not f-string formatting.
_CACHE_BUST_JS_TEMPLATE = """
(function () {
  try {
    window.__ANCHOR_BUILD__ = "__ANCHOR_BUILD_ID__";
    // Kill any leftover service worker registered by an OLD Anchor build.
    if (navigator.serviceWorker && navigator.serviceWorker.getRegistrations) {
      navigator.serviceWorker.getRegistrations().then(function (rs) {
        rs.forEach(function (r) { try { r.unregister(); } catch (e) {} });
      }).catch(function () {});
    }
    // Best-effort: clear any stale Cache Storage entries.
    if (window.caches && caches.keys) {
      caches.keys().then(function (ks) {
        ks.forEach(function (k) { try { caches.delete(k); } catch (e) {} });
      }).catch(function () {});
    }
    function checkVersion() {
      fetch('/api/version', { cache: 'no-store' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          var v = d && d.version;
          if (!v || v === window.__ANCHOR_BUILD__) return;
          // Loop guard: never reload more than once per server version.
          var key = 'anchor_reloaded_for';
          try {
            if (sessionStorage.getItem(key) === String(v)) return;
            sessionStorage.setItem(key, String(v));
          } catch (e) {}
          location.replace(location.pathname + '?v=' + encodeURIComponent(v));
        })
        .catch(function () {});
    }
    checkVersion();
    setInterval(checkVersion, 30000);
  } catch (e) {}
})();
"""


def cache_bust_script():
    """Return the inline cache-bust JS for the current BUILD_ID.

    No f-string formatting is used (the JS contains literal braces), so this is
    safe to drop into an f-string page as ``{cache_bust_script()}`` only after
    the result is a plain string — callers embed the returned string verbatim.
    """
    return _CACHE_BUST_JS_TEMPLATE.replace("__ANCHOR_BUILD_ID__", BUILD_ID)


# ── Contract-versioning shim (re-architecture 2026-07 · W2) ─────────────────
# ``window.ANCHOR_BOOT`` is the VERSIONED server→client bootstrap channel.
# W2 ships it minimally — the build id + the auth flag — as the deploy-safety
# contract shim (the LAST pre-migration release): every ``_postJson`` declares
# the page's build id via the ``X-Anchor-Build`` header, and a mismatch is
# answered with a STRUCTURED 409 the stale client renders as a 'reload
# required' banner (stale-tab / PWA-cached iPad client protection). W4 grows
# ANCHOR_BOOT into the ONLY server→client state channel for the extracted
# static frontend (token presence, project id, feature flags, initial counts).
ANCHOR_BOOT_SCHEMA_VER = 1

#: The structured 409 discriminator the client JS matches on. Keep stable —
#: old clients in the field match this exact string forever.
BUILD_MISMATCH_ERROR = "build-mismatch"


def anchor_boot(extra=None):
    """Assemble the ``window.ANCHOR_BOOT`` bootstrap dict.

    Documented contract (versioned via ``schema_ver``; additive-only):
      - ``schema_ver``     — int, the ANCHOR_BOOT shape version;
      - ``build_id``       — the server build this page was rendered from;
      - ``auth_required``  — whether the server has ANCHOR_TOKEN configured
                             (token PRESENCE only — never the value).
    ``extra`` lets a render surface add page-scoped keys. Never embeds the
    token VALUE itself — only its presence.

    W4 (static frontend, rearch C1 increment 1) — the PROJECT WINDOW adds,
    via ``extra`` = :func:`project_window_boot_extra`:
      - ``page``                   — ``"project-window"``;
      - ``project_id``             — the window's project id;
      - ``grass_dev_label_prefix`` — ``effort_history.GRASS_DEV_LABEL_PREFIX``
                                     (the [grass-dev] top-strip filter marker);
      - ``flags``                  — feature flags (``{"frontend": "static"}``);
      - ``counts``                 — initial counts (``sessions`` /
                                     ``live_sessions`` from the managed-session
                                     registry; best-effort zeros on error).
    On the static-frontend path this dict is the ONLY server→client state
    channel for the project window: the page derives its legacy globals from
    it client-side (``_PW_BOOT_GLOBALS_JS``) and the app JS arrives as a
    static file — no other per-page server value injection exists.
    """
    boot = {
        "schema_ver": ANCHOR_BOOT_SCHEMA_VER,
        "build_id": BUILD_ID,
        "auth_required": bool(_paths.expected_token()),
    }
    if extra:
        boot.update(extra)
    return boot


def anchor_boot_script(extra=None):
    """The inline ``window.ANCHOR_BOOT = {…};`` bootstrap line.

    Returned as a PLAIN string so the project-window page embeds it by
    concatenation — never as a new f-string interpolation in the two
    census-counted render surfaces (the W1 census contract).
    """
    return "window.ANCHOR_BOOT = " + json.dumps(anchor_boot(extra)) + ";"


# ── Parsing ────────────────────────────────────────────────────────────

#: Warnings from the most recent gather_all() — markdown files that could not
#: be read/parsed and were skipped so one bad file can't 500 the whole
#: dashboard. Best-effort, for diagnostics/tests and future UI surfacing. (The
#: daily healthcheck independently flags malformed files via its own strict
#: parse check.)
LAST_GATHER_WARNINGS = []


def _read_md_text(filepath):
    """Read a markdown file as text, resilient to non-UTF-8 bytes.

    Anchor always writes markdown as UTF-8, but a file edited by an external
    tool can arrive in another encoding (e.g. a Windows-1252 em-dash, byte
    0x97). A single such byte must never take down the dashboard: try strict
    UTF-8 first, and on a UnicodeDecodeError fall back to a lenient decode so
    the stray byte degrades to a replacement char instead of raising. The next
    write re-saves the file as clean UTF-8. The daily healthcheck still reads
    strictly, so a malformed file is still surfaced there for cleanup.
    """
    try:
        return filepath.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return filepath.read_text(encoding="utf-8", errors="replace")


# ── Markdown parsers — the single shared layer (C5 de-fork, 2026-07) ───
# The task/project/inbox/archived parsers + serialize_task_line live in the
# shared ``anchor_md`` module (imported here and by anchor.py). They used to be
# a byte-identical twin duplicated across anchor_gui.py / anchor.py (plus a
# drifted third copy in the now-deleted dead Flask ``anchor_server.py``). These
# names are re-exported as module globals so existing ``anchor_gui.parse_*``
# call sites — and the test monkeypatches of them — keep working unchanged.
from anchor_md import (  # noqa: E402  (kept next to the local _read_md_text)
    parse_tasks_from_md,
    serialize_task_line,
    parse_projects_from_md,
    parse_inbox_from_md,
    parse_archived_tasks,
)


# ── Gather all data ────────────────────────────────────────────────────

def gather_all():
    """Read everything from both directories, return (projects, tasks, inbox)."""
    all_tasks = []
    seen = set()

    def _add(task_list, default_domain=None):
        for t in task_list:
            key = t["text"].lower().strip()[:60]
            if key not in seen:
                seen.add(key)
                if default_domain and t["domain"] == "personal":
                    t["domain"] = default_domain
                all_tasks.append(t)

    # Collect per-render warnings locally; a single unreadable/unparseable file
    # must be skipped (recorded here) rather than 500-ing the whole dashboard.
    # We accumulate into a local list and publish it atomically at the end, so
    # concurrent gather_all() calls (ThreadingHTTPServer) never observe a torn
    # mid-clear state of the module global.
    _warn = []

    def _safe(parse_fn, src, *, into, **kw):
        try:
            into(parse_fn(src), **kw)
        except Exception as e:  # one bad file can't take down every view
            _warn.append(f"{getattr(src, 'name', src)}: {e}")

    if DASHBOARD_MD.exists():
        _safe(parse_tasks_from_md, DASHBOARD_MD, into=_add)
    if DOMAINS_DIR.exists():
        for f in sorted(DOMAINS_DIR.glob("*.md")):
            _safe(parse_tasks_from_md, f, into=_add, default_domain=f.stem)

    projects = []
    seen_p = set()
    if PROJECTS_MD.exists():
        try:
            parsed_projects = parse_projects_from_md(PROJECTS_MD)
        except Exception as e:
            parsed_projects = []
            _warn.append(f"{PROJECTS_MD.name}: {e}")
        for p in parsed_projects:
            key = p["name"].lower().strip()[:60]
            if key not in seen_p:
                seen_p.add(key)
                projects.append(p)

    inbox = []
    if INBOX_MD.exists():
        try:
            inbox.extend(parse_inbox_from_md(INBOX_MD))
        except Exception as e:
            _warn.append(f"{INBOX_MD.name}: {e}")

    # Publish warnings atomically (slice-assign in place, no clear/append window).
    LAST_GATHER_WARNINGS[:] = _warn

    # Filter out synthetic health-check probes so they never appear in any view
    all_tasks = [t for t in all_tasks if "__healthcheck__" not in t["text"].lower()]
    inbox = [i for i in inbox if "__healthcheck__" not in i["text"].lower()]

    return projects, all_tasks, inbox


# ── Health report banner ──────────────────────────────────────────────

HEALTH_REPORTS_DIR = ANCHOR_DIR / "health_reports"


def latest_health_report():
    """Return (date_str, status, path) for the most recent health report, or None.

    status is "OK" or "ISSUES FOUND" (taken from the second non-blank line of the report).
    """
    if not HEALTH_REPORTS_DIR or not HEALTH_REPORTS_DIR.exists():
        return None
    reports = sorted(HEALTH_REPORTS_DIR.glob("*.md"), reverse=True)
    for r in reports:
        if r.name.lower() == "readme.md":
            continue
        try:
            text = r.read_text(encoding="utf-8")
        except Exception:
            continue
        m = re.search(r'^Status:\s*(.+)$', text, re.MULTILINE)
        if m:
            status = m.group(1).strip()
            return (r.stem, status, r)
    return None


def _all_md_files():
    files = []
    if DASHBOARD_MD.exists():
        files.append(DASHBOARD_MD)
    if DOMAINS_DIR.exists():
        files.extend(sorted(DOMAINS_DIR.glob("*.md")))
    return files


# ── R&D control surface (Wave 3) ───────────────────────────────────────
# Thin id-keyed project registry + New Project flow + per-project store +
# folder-grouped projects view + single-instance project windows.

import rnd_registry as _rnd
import dir_browser as _dirb
import effort_history as _eh
import sessions as _sessions
import report_viewer as _rv
import summarizer as _summarizer
import deliverables as _deliv
import lanes as _lanes
import job_runner as _jr
import gate_adapter as _gate
import supervisor as _sup  # rearch W15 — ANCHOR_SUPERVISOR job-ownership seam
import brownfield_scan as _bscan
import anchor_marker as _marker
import rnd_terminal as _term
import terminal_session as _termsess
import session_registry as _sessreg
import anchor_settings as _aset  # durable model/engine prefs (default_cli, families)
import handoff as _handoff
import preview_server as _preview
import project_bootstrap as _bootstrap
import project_remote as _remote  # v8 Wave 3 — GitHub link + auto-push (seam)
import boneyard as _boneyard  # v10 Wave 6/7 — per-project searchable discard index
import effort_view as _effview  # v12 Wave 9 — derived effort view-layer (chains→efforts)
import narration as _narr  # telemetry-resume W3 — deterministic narration floor + Layer-1 warm view
import usage_capture as _usage  # telemetry-resume W4 — usage-capture pipeline (ledger inspection)
import rollup_honesty as _rollhon  # telemetry-resume W5 — three-state rollup honesty + capture-rate stamp
import gandalf as _gandalf  # Gandalf integration v1 — two-stage honest project read
import foundry_gui as _fgui  # foundry-v2 Wave 9 — stateless Foundry GUI read surface
import foundry_gui_write as _fgw  # foundry-v2 Wave 10 — GUI write surface (op invocations only, never a GUI-side file write)
import foundry_api as _fapi  # foundry GUI fold-in — the React app's real-data API layer (port of server.mjs)
import pillar_flags as _pillar  # rearch W3/W4 — per-pillar off-switch flags (stdlib-only)
import paths as _paths  # re-import alias (already imported above; harmless)


# ── Hand-rolled stdlib WebSocket frame codec (RFC 6455) — PURE functions ─────
# v3 "Mission Control" (MASTER-PLAN §D / Wave 3). The ConPTY terminal transport
# is a minimal hand-rolled WebSocket carrying PTY bytes both ways over the raw
# socket. The frame codec is factored into PURE, socket-free functions so it is
# unit-testable without a connection.
import base64 as _b64
import hashlib as _hashlib
import struct as _struct

#: The RFC 6455 GUID concatenated with the client key to derive the accept hash.
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

# WebSocket opcodes.
WS_OP_CONT = 0x0
WS_OP_TEXT = 0x1
WS_OP_BINARY = 0x2
WS_OP_CLOSE = 0x8
WS_OP_PING = 0x9
WS_OP_PONG = 0xA


def ws_accept_key(client_key: str) -> str:
    """Compute the ``Sec-WebSocket-Accept`` value for a client key (RFC 6455).

    ``base64(sha1(client_key + WS_GUID))``. Pure + deterministic so it is
    unit-tested against the spec example
    (``dGhlIHNhbXBsZSBub25jZQ==`` -> ``s3pPLMBiTxaQ9kYGzzhZRbK+xOo=``).
    """
    digest = _hashlib.sha1(
        (client_key.strip() + WS_GUID).encode("ascii")).digest()
    return _b64.b64encode(digest).decode("ascii")


def encode_text_frame(text) -> bytes:
    """Encode a server->client TEXT frame (FIN=1, unmasked — server frames are
    never masked per RFC 6455)."""
    if isinstance(text, str):
        payload = text.encode("utf-8")
    else:
        payload = bytes(text)
    return _encode_frame(WS_OP_TEXT, payload)


def encode_close_frame(code=1000, reason=b"") -> bytes:
    """Encode a server->client CLOSE frame with an optional status code."""
    if isinstance(reason, str):
        reason = reason.encode("utf-8")
    payload = _struct.pack(">H", code) + reason if code is not None else b""
    return _encode_frame(WS_OP_CLOSE, payload)


#: telemetry-resume W6 — the WS ATTACH-ACK control-frame protocol prefix. The
#: term_ws stream is otherwise opaque PTY bytes written straight into xterm; a
#: structured control message (attach_ack / replay_complete / error) rides the
#: SAME token-authed socket as a TEXT frame whose payload begins with this
#: prefix. Real PTY output effectively never starts with a NUL byte, so the
#: client disambiguates a control frame from terminal bytes by this prefix and
#: only swaps in the live pane after ``attach_ack ok:true`` + ``replay_complete``
#: — a blank pane becomes a protocol impossibility (NORTH-STAR-AMENDMENT Layer 2).
WS_CTL_PREFIX = "\x00ANCHOR-CTL:"


def ws_ctl_frame(obj) -> bytes:
    """Encode a W6 attach-ack control message as a prefixed server TEXT frame."""
    return encode_text_frame(WS_CTL_PREFIX + json.dumps(obj, separators=(",", ":")))


def encode_pong_frame(payload=b"") -> bytes:
    """Encode a server->client PONG frame echoing the ping payload."""
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return _encode_frame(WS_OP_PONG, payload)


def _encode_frame(opcode, payload: bytes) -> bytes:
    """Build a single unmasked WebSocket frame (FIN=1) for ``opcode``+payload."""
    b0 = 0x80 | (opcode & 0x0F)            # FIN=1, opcode
    n = len(payload)
    if n < 126:
        header = _struct.pack(">BB", b0, n)
    elif n < (1 << 16):
        header = _struct.pack(">BBH", b0, 126, n)
    else:
        header = _struct.pack(">BBQ", b0, 127, n)
    return header + payload


#: Max bytes a single client frame's declared payload may be before the codec
#: signals a clean close instead of accumulating an unbounded inbuf. Also caps
#: the fragmentation-reassembly buffer (FIN=0 TEXT + CONTINUATION run).
MAX_WS_FRAME = 1 << 20  # 1 MiB

#: A pseudo-opcode the codec emits to tell the pump to close the connection on a
#: protocol error (oversized frame, unmasked client data frame, bad fragment).
#: It is NOT a real RFC 6455 opcode (0x10 is out of the 4-bit opcode range), so
#: it can never collide with a genuine decoded frame.
WS_SIGNAL_CLOSE = 0x10


def decode_frames(buf: bytes, state=None, require_mask=False):
    """Decode as many complete WebSocket frames as ``buf`` holds.

    Returns ``(messages, rest)`` where ``messages`` is a list of
    ``(opcode, payload_bytes)`` and ``rest`` is the trailing bytes of an
    incomplete frame to carry forward.

    ``decode_frames`` is dual-use: the pump decodes CLIENT frames (always masked)
    and tests decode SERVER frames (never masked). Pass ``require_mask=True``
    (the pump does) to enforce RFC 6455 §5.1 — an unmasked CLIENT frame is then a
    protocol error and yields a single ``(WS_SIGNAL_CLOSE, ...)`` message so the
    pump closes the connection. With ``require_mask=False`` (default) an unmasked
    frame's payload is taken verbatim (so server→client frames decode cleanly).

    Bounded (FIX 3): a frame whose DECLARED payload length exceeds
    :data:`MAX_WS_FRAME` yields ``(WS_SIGNAL_CLOSE, ...)`` instead of buffering
    toward an allocation — even before the payload bytes arrive.

    Fragmentation reassembly (FIX 6, RFC 6455 §5.4): a TEXT/BINARY frame with
    FIN=0 starts a message that is continued by CONTINUATION (opcode 0x0) frames
    and delivered as ONE message when a CONTINUATION arrives with FIN=1. Control
    frames (close/ping/pong) are delivered immediately and may interleave a
    fragmented data message. Reassembly state is carried in the optional
    ``state`` dict (the pump passes a persistent one); when ``state`` is None a
    transient one is used (single-buffer/backward-compatible call form). The
    reassembly buffer is itself bounded by :data:`MAX_WS_FRAME`.
    """
    if state is None:
        state = {}
    messages = []
    i = 0
    n = len(buf)
    while True:
        if n - i < 2:
            break
        b0 = buf[i]
        b1 = buf[i + 1]
        fin = bool(b0 & 0x80)
        opcode = b0 & 0x0F
        masked = bool(b1 & 0x80)
        length = b1 & 0x7F
        j = i + 2
        if length == 126:
            if n - j < 2:
                break
            length = _struct.unpack(">H", buf[j:j + 2])[0]
            j += 2
        elif length == 127:
            if n - j < 8:
                break
            length = _struct.unpack(">Q", buf[j:j + 8])[0]
            j += 8
        # Reject an oversized DECLARED payload BEFORE waiting for/allocating it.
        if length > MAX_WS_FRAME:
            messages.append((WS_SIGNAL_CLOSE, b"frame too large"))
            return messages, b""
        is_control = bool(opcode & 0x8)
        # RFC 6455 §5.1: a client frame MUST be masked. When decoding client
        # frames (require_mask), an unmasked frame is a protocol error.
        if require_mask and not masked:
            messages.append((WS_SIGNAL_CLOSE, b"unmasked client frame"))
            return messages, b""
        mask = b""
        if masked:
            if n - j < 4:
                break
            mask = buf[j:j + 4]
            j += 4
        if n - j < length:
            break  # incomplete payload — wait for more bytes
        payload = bytearray(buf[j:j + length])
        if masked and mask:
            for k in range(length):
                payload[k] ^= mask[k & 3]
        payload = bytes(payload)
        i = j + length

        if is_control:
            # Control frames are never fragmented; deliver immediately, even mid
            # data-message reassembly.
            messages.append((opcode, payload))
            continue

        if opcode == WS_OP_CONT:
            if "frag_op" not in state:
                # CONTINUATION with no message in progress — protocol error.
                messages.append((WS_SIGNAL_CLOSE, b"unexpected continuation"))
                return messages, b""
            state["frag_buf"] = state.get("frag_buf", b"") + payload
            if len(state["frag_buf"]) > MAX_WS_FRAME:
                messages.append((WS_SIGNAL_CLOSE, b"fragmented message too large"))
                return messages, b""
            if fin:
                messages.append((state.pop("frag_op"), state.pop("frag_buf")))
            continue

        # A new TEXT/BINARY data frame.
        if not fin:
            # Start of a fragmented message.
            state["frag_op"] = opcode
            state["frag_buf"] = payload
            if len(state["frag_buf"]) > MAX_WS_FRAME:
                messages.append((WS_SIGNAL_CLOSE, b"fragmented message too large"))
                return messages, b""
            continue
        messages.append((opcode, payload))
    return messages, buf[i:]


def _unsafe_path_seg(seg: str) -> bool:
    """True if a URL segment is unsafe to use as a filesystem path component.

    Rejects path separators (``/`` ``\\``) and parent-dir traversal (``..``)
    before the value is used to build a filesystem path. Mirrors the
    path-traversal hardening on the vendored-KaTeX static route.
    """
    if seg is None:
        return False
    return "/" in seg or "\\" in seg or ".." in seg


# ── Vendored terminal-console static asset (Wave 7) ──────────────────────────
# The lightweight, dependency-free terminal console (anchor-term) is vendored
# exactly like KaTeX: a read-only static dir served traversal-safe under a URL
# prefix. It backs the interactive terminal that replaces the raw-log console.
ANCHOR_TERM_DIR = ANCHOR_DIR / "vendor" / "anchor-term"
ANCHOR_TERM_URL_PREFIX = "/vendor/anchor-term"
_ANCHOR_TERM_CONTENT_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
}


def anchor_term_asset(rel_path: str):
    """Resolve a ``/vendor/anchor-term/<rel>`` request to (bytes, content_type).

    Path-traversal safe (mirrors ``report_viewer.katex_asset``): the resolved
    file MUST stay within :data:`ANCHOR_TERM_DIR`. Returns ``None`` for a missing
    file or an escape attempt.
    """
    rel = rel_path.lstrip("/")
    target = (ANCHOR_TERM_DIR / rel).resolve()
    try:
        target.relative_to(ANCHOR_TERM_DIR.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    ctype = _ANCHOR_TERM_CONTENT_TYPES.get(target.suffix.lower(),
                                           "application/octet-stream")
    return target.read_bytes(), ctype


# ── Vendored xterm.js static asset (real terminal emulator) ──────────────────
# The interactive terminal canvas is a genuine xterm.js Terminal. xterm.js is
# pure browser JS (no native/compiled component), vendored offline as a plain
# static asset exactly like KaTeX. The anchor-term chrome (input line, gates,
# adopt panel) is layered on top via the anchor-term asset above.
XTERM_DIR = ANCHOR_DIR / "vendor" / "xterm"
XTERM_URL_PREFIX = "/vendor/xterm"


def xterm_asset(rel_path: str):
    """Resolve a ``/vendor/xterm/<rel>`` request to (bytes, content_type).

    Path-traversal safe (same containment pattern as :func:`anchor_term_asset`
    and ``report_viewer.katex_asset``): the resolved file MUST stay within
    :data:`XTERM_DIR`. Returns ``None`` for a missing file or an escape attempt.
    """
    rel = rel_path.lstrip("/")
    target = (XTERM_DIR / rel).resolve()
    try:
        target.relative_to(XTERM_DIR.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    ctype = _ANCHOR_TERM_CONTENT_TYPES.get(target.suffix.lower(),
                                           "application/octet-stream")
    return target.read_bytes(), ctype


# ── Vendored Ghost World Labs brand mark static asset (Wave 9) ───────────────
# The GWL brand mark (gwl-m-icon.svg) is vendored on-disk under vendor/brand/
# and served traversal-safe exactly like the KaTeX/xterm/anchor-term assets. It
# backs the home-page lockup and the dashboard favicon. Pure-data static SVG —
# no native dependency, no secret.
BRAND_DIR = ANCHOR_DIR / "vendor" / "brand"
BRAND_URL_PREFIX = "/vendor/brand"
_BRAND_CONTENT_TYPES = {
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}


def brand_asset(rel_path: str):
    """Resolve a ``/vendor/brand/<rel>`` request to (bytes, content_type).

    Path-traversal safe (same containment pattern as :func:`anchor_term_asset`
    / :func:`xterm_asset` / ``report_viewer.katex_asset``): the resolved file
    MUST stay within :data:`BRAND_DIR`. Returns ``None`` for a missing file or
    an escape attempt (so a ``../`` traversal can never read outside the brand
    dir).
    """
    rel = rel_path.lstrip("/")
    target = (BRAND_DIR / rel).resolve()
    try:
        target.relative_to(BRAND_DIR.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    ctype = _BRAND_CONTENT_TYPES.get(target.suffix.lower(),
                                     "application/octet-stream")
    return target.read_bytes(), ctype


# ── Static app-frontend root (re-architecture 2026-07 · W4) ──────────────────
# C1 Extraction Increment 1: the project-window app JS (the census-confirmed
# ZERO-interpolation ``_PROJECT_WINDOW_JS`` raw string) also exists as a
# checked-in static file — ``static/project-window.js`` — minted VERBATIM from
# the string by ``tools/extract_project_window_js.py`` (the W4 byte-parity
# gate refreshes it and fails on drift; until W6 removes the embedded blob,
# the raw string stays the single source of truth and the file is its derived
# byte-identical mirror). Which copy a project window actually gets is chosen
# by the ``frontend`` pillar off-switch flag (``pillar_flags``:
# ANCHOR_FRONTEND = embedded | static; default embedded = the pre-wave
# behavior, byte-identical), so this pillar reverts by FLAG ONLY — flipping
# back to embedded never requires reverting later waves. The static root is
# served through the SAME traversal-safe resolve()+relative_to idiom as the
# vendored assets above (zero new security surface), with content-hash
# cache-busting: ?v=<hash8> is minted per process from the file bytes, so a
# new deploy changes the asset URL and a long-lived tab can never pin a stale
# copy (the W6 stale-browser criterion).
STATIC_DIR = ANCHOR_DIR / "static"
STATIC_URL_PREFIX = "/static"

#: The extracted project-window app JS asset (Extraction Increment 1).
PROJECT_WINDOW_JS_ASSET = "project-window.js"

#: The extracted project-window SHELL assets (Extraction Increment 2 · W5):
#: the interpolation-free stylesheet + the ``@@slot@@`` HTML shell template,
#: both minted verbatim from their in-source twins (``_PW_SHELL_CSS`` /
#: ``_PW_SHELL_TMPL``) by ``tools/extract_project_window_shell.py``.
PROJECT_WINDOW_CSS_ASSET = "project-window.css"
PROJECT_WINDOW_SHELL_ASSET = "project-window.html"

#: The extracted HOME-dashboard assets (rearch W6b · C1 increment 3): the
#: interpolation-free stylesheet, the ANCHOR_BOOT-driven application JS, and the
#: ANCHOR:SLOT-marked HTML shell — minted VERBATIM from ``generate_html``'s
#: return f-string by ``tools/extract_home_dashboard.py`` behind the W6b
#: byte-parity gate (mirrors the W4 app-JS + W5 shell idiom, one level up: the
#: home f-string's markup-emitting interpolations stay SERVER-RENDERED as slot
#: values — they cannot ride the ANCHOR_BOOT JSON). The raw slot markers live in
#: the minted static shell FILE, never inline in this source.
HOME_CSS_ASSET = "home.css"
HOME_JS_ASSET = "home.js"
HOME_SHELL_ASSET = "home.html"

#: The ANCHOR:SLOT HTML-comment include-slot marker (the W6a substrate
#: delimiter, mirrored inline here so product code stays stdlib-only and
#: self-contained — ``tools/slot_renderer.py`` is the gate/test twin). This
#: comment form (and the W5 project-window ``@@`` form) never appear in real
#: frontend content, so neither can collide with page bytes.
_HOME_SLOT_RE = re.compile(r"<!--ANCHOR:SLOT:([A-Za-z0-9_.\-]+)-->")


def _render_home_slots(shell: str, helpers: dict) -> str:
    """Substitute every ANCHOR:SLOT include marker in ``shell`` with
    ``helpers[name]`` (byte-compatible twin of
    ``tools.slot_renderer.render_slots``).

    A slot with no helper output, a helper output with no slot, or a non-string
    output each raises ``ValueError`` LOUDLY — the completeness invariant that
    makes the extraction provably faithful (never a silent drop / silent extra).
    """
    shell_slots = {m.group(1) for m in _HOME_SLOT_RE.finditer(shell)}
    provided = set(helpers)
    missing = shell_slots - provided
    if missing:
        raise ValueError("home shell slot(s) with no helper output: "
                         + ", ".join(sorted(missing)))
    extra = provided - shell_slots
    if extra:
        raise ValueError("home helper output(s) with no matching slot: "
                         + ", ".join(sorted(extra)))
    for name in shell_slots:
        if not isinstance(helpers[name], str):
            raise ValueError(f"home slot {name!r} output must be str, got "
                             f"{type(helpers[name]).__name__}")
    return _HOME_SLOT_RE.sub(lambda m: helpers[m.group(1)], shell)


def home_boot_extra() -> dict:
    """Page-scoped ``window.ANCHOR_BOOT`` keys for the home dashboard (W6b).

    ``auth_required`` already rides the base :func:`anchor_boot` dict (token
    PRESENCE only); this adds the page marker + the frontend feature flag so the
    static ``home.js`` shares the same ANCHOR_BOOT contract as
    ``project-window.js``.
    """
    return {"page": "home", "flags": {"frontend": "static"}}


def _home_shell_template():
    """The ``static/home.html`` slot template, or ``None`` when unavailable.

    Read from the checked-in static FILE (the W6b byte-parity-gated mirror of
    ``generate_html``'s return f-string). ``None`` signals the render to fall
    back to the EMBEDDED f-string path — so a missing/undecodable mirror serves
    the pre-wave dashboard correctly, never a 500 (drift is the gate's job to
    catch, not the render path's).
    """
    asset = static_asset(HOME_SHELL_ASSET)
    if asset is not None:
        try:
            return asset[0].decode("utf-8")
        except UnicodeDecodeError:
            pass
    return None


def static_asset(rel_path: str):
    """Resolve a ``/static/<rel>`` request to (bytes, content_type).

    Path-traversal safe (same containment pattern as :func:`anchor_term_asset`
    / :func:`xterm_asset` / :func:`brand_asset` / ``report_viewer.katex_asset``):
    the resolved file MUST stay within :data:`STATIC_DIR`. Returns ``None``
    for a missing file or an escape attempt.
    """
    rel = rel_path.lstrip("/")
    target = (STATIC_DIR / rel).resolve()
    try:
        target.relative_to(STATIC_DIR.resolve())
    except ValueError:
        return None
    if not target.is_file():
        return None
    ctype = _ANCHOR_TERM_CONTENT_TYPES.get(target.suffix.lower(),
                                           "application/octet-stream")
    return target.read_bytes(), ctype


#: Per-process cache of minted content-hash versions {rel_path: hash8}.
_static_asset_versions = {}


def static_asset_version(rel_path: str) -> str:
    """The content-hash cache-buster for a static asset (the ``?v=<hash8>``).

    sha256 of the file bytes, first 8 hex chars, minted ONCE per process (a
    restart re-mints it, so a deploy that changes the file changes every
    page's asset URL). A missing asset honestly returns ``"missing"`` and is
    NOT cached, so the version heals as soon as the file exists.
    """
    cached = _static_asset_versions.get(rel_path)
    if cached is not None:
        return cached
    asset = static_asset(rel_path)
    if asset is None:
        return "missing"
    ver = _hashlib.sha256(asset[0]).hexdigest()[:8]
    _static_asset_versions[rel_path] = ver
    return ver


def _static_frontend_enabled() -> bool:
    """True iff the ``frontend`` pillar flag resolves to ``static`` (W4).

    Resolved FRESH per call through :func:`pillar_flags.current_flags` so a
    restartless env flip (tests, ops) is honored. An INVALID flag value falls
    back to the embedded (pre-wave) path here — conservative render behavior,
    never a 500 dashboard — while the healthcheck's ``check_pillar_state``
    assertion fails loudly on the same invalid value, so a misconfiguration
    is surfaced, never silently served.
    """
    try:
        return _pillar.current_flags()[_pillar.FLAG_FRONTEND] == "static"
    except Exception:
        return False


#: Static-frontend bootstrap tail: the legacy page globals the app JS reads
#: (PROJECT_ID · GRASS_DEV_LABEL_PREFIX · ANCHOR_AUTH_REQUIRED) DERIVED from
#: ``window.ANCHOR_BOOT`` client-side — on the static path the bootstrap JSON
#: is the ONLY server→client state channel; no per-page ``var X = <server
#: value>`` injection remains. Plain constant string (zero interpolations).
_PW_BOOT_GLOBALS_JS = (
    "var PROJECT_ID = window.ANCHOR_BOOT.project_id;\n"
    "var GRASS_DEV_LABEL_PREFIX = window.ANCHOR_BOOT.grass_dev_label_prefix;\n"
    "window.ANCHOR_AUTH_REQUIRED = !!window.ANCHOR_BOOT.auth_required;\n"
    "window.ANCHOR_DEFAULT_CLI = window.ANCHOR_BOOT.default_cli || 'grok';\n"
    "window.ANCHOR_CODING_FAMILY = window.ANCHOR_BOOT.coding_family || 'claude';\n"
    "window.ANCHOR_REVIEW_FAMILY = window.ANCHOR_BOOT.review_family || 'gemini';\n"
)


def project_window_boot_extra(project_id: str) -> dict:
    """The project window's page-scoped ``window.ANCHOR_BOOT`` keys (W4).

    See :func:`anchor_boot` for the documented, versioned contract. The
    initial counts are best-effort reads of the managed-session registry —
    a registry hiccup renders honest zeros, never a failed page.
    """
    sessions = live = 0
    try:
        recs = _sessreg.list_sessions(project_id=project_id)
        sessions = len(recs)
        live = sum(1 for r in recs
                   if r.get("status") == _sessreg.STATUS_RUNNING)
    except Exception:
        pass
    try:
        prefs = _aset.load_settings()
    except Exception:
        prefs = dict(_aset.DEFAULTS)
    return {
        "page": "project-window",
        "project_id": project_id,
        "grass_dev_label_prefix": _eh.GRASS_DEV_LABEL_PREFIX,
        "flags": {"frontend": "static"},
        "counts": {"sessions": sessions, "live_sessions": live},
        "default_cli": prefs.get("default_cli") or "grok",
        "coding_family": prefs.get("coding_family") or "claude",
        "review_family": prefs.get("review_family") or "gemini",
    }


# ── Project-window SHELL include layer (re-architecture 2026-07 · W5) ────────
# C1 Extraction Increment 2: the project-window HTML/CSS shell lives in two
# module-level plain strings — ``_PW_SHELL_CSS`` (the whole <style> body,
# zero interpolations) and ``_PW_SHELL_TMPL`` (the document shell whose ONLY
# dynamic points are named ``@@slot@@`` placeholders — the include-layer
# design the W1 census's C1 amendment mandated: markup-emitting values are
# computed server-side and injected whole; they cannot ride the ANCHOR_BOOT
# JSON). Both are minted VERBATIM to static files (``static/
# project-window.css`` / ``static/project-window.html``) by
# ``tools/extract_project_window_shell.py`` behind the W5 byte-parity gate;
# until W6 removes the embedded copies the in-source strings stay the single
# source of truth and the files are their derived byte-identical mirrors.
# EMBEDDED (the default) inlines the CSS and fills the in-source template —
# the pre-wave emission, byte-identical. STATIC swaps the inline <style> for
# the hashed static stylesheet link and fills the template read from the
# static FILE (falling back to the in-source twin on a missing/undecodable/
# drifted file so the window still renders correctly, never a 500 — drift is
# the byte-parity GATE's job to catch, not the render path's).

#: ``@@slot@@`` placeholder syntax for the shell template. ``@@`` appears
#: nowhere in the shell/CSS/JS bodies (gate-checked), so the delimiter can
#: never collide with real frontend content.
_PW_SLOT_RE = re.compile(r"@@([a-z][a-z0-9_]*)@@")


def _pw_fill(template: str, slots: dict) -> str:
    """Fill ``@@slot@@`` placeholders in ONE regex pass.

    Slot values are inserted verbatim and NEVER re-scanned — user content
    containing ``@@…@@`` text can never pull in a second substitution (no
    injection through notes/names). An unknown placeholder raises
    ``KeyError`` (a drifted template must fail loudly, not render holes).
    """
    return _PW_SLOT_RE.sub(lambda m: slots[m.group(1)], template)


def _pw_shell_template() -> str:
    """The shell template the project-window render fills.

    The static path reads it from the static FILE (the W5 "static shell
    serving"); embedded — and any static-path miss — uses the in-source
    twin, which the gate keeps byte-identical to the file.
    """
    if _static_frontend_enabled():
        asset = static_asset(PROJECT_WINDOW_SHELL_ASSET)
        if asset is not None:
            try:
                return asset[0].decode("utf-8")
            except UnicodeDecodeError:
                pass
    return _PW_SHELL_TMPL


# Single-instance project windows (Master Plan C2): opening a project that is
# already open returns the EXISTING instance id rather than spawning a duplicate.
# Server-side, process-local map {project_id: instance_id}. Guarded by the same
# process-wide write lock so concurrent opens resolve to one instance.
_project_instances = {}


def open_project_instance(project_id: str) -> dict:
    """Return the (single) window instance for a project, creating if needed.

    Re-opening an already-open project returns the same ``instance_id`` — no
    duplicate window (C2). Returns ``{project_id, instance_id, reused}``.
    """
    with WRITE_LOCK:
        existing = _project_instances.get(project_id)
        if existing is not None:
            return {"project_id": project_id, "instance_id": existing,
                    "reused": True}
        import uuid as _uuid
        inst = _uuid.uuid4().hex
        _project_instances[project_id] = inst
        return {"project_id": project_id, "instance_id": inst, "reused": False}


def close_project_instance(project_id: str) -> bool:
    """Forget a project's open instance (so a later open is fresh)."""
    with WRITE_LOCK:
        return _project_instances.pop(project_id, None) is not None


def _maybe_git_init(folder: Path) -> bool:
    """Optionally run ``git init`` in ``folder``. Best-effort, never raises.

    Returns True if git init was attempted and succeeded. Skipped silently if
    git is unavailable or the folder is already a repo.
    """
    try:
        import subprocess
        if (folder / ".git").exists():
            return False
        subprocess.run(["git", "init"], cwd=str(folder), check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       timeout=30, creationflags=_paths.NO_WINDOW)
        return True
    except Exception:
        return False


def _bootstrap_project_best_effort(folder, project_name) -> None:
    """Best-effort v8 bootstrap: starter CLAUDE.md + git-init the folder.

    Wired into the register / open / rescan paths so a non-git project doesn't
    dead-end a session start with ``not-a-git-repo`` and the keystone (Wave 2
    doc persistence) has a repo to commit to. NEVER breaks registration/rescan
    if bootstrap fails (try/except → log + skip). Idempotent (an existing repo /
    CLAUDE.md is a no-op).
    """
    try:
        if not folder:
            return
        f = Path(folder)
        if not f.is_dir():
            return
        res = _bootstrap.bootstrap_project(folder, project_name)
        git = res.get("git", {})
        cm = res.get("claude_md", {})
        if git.get("initialized"):
            log_change(f"R&D: bootstrap git-init {folder}")
        elif not git.get("ok") and git.get("reason") == "git-unavailable":
            log_change(f"R&D: bootstrap skipped git-init (git unavailable) {folder}")
        if cm.get("created"):
            log_change(f"R&D: bootstrap wrote starter CLAUDE.md {folder}")
    except Exception:
        pass  # bootstrap is best-effort; never block registration/open/rescan


def resolve_project_dir(parent_path, name: str) -> Path:
    """Computes the on-disk project directory and prevents double-nesting.

    If parent_path already ends with name (case/sep-insensitive),
    do NOT append name again.
    """
    p_str = str(parent_path).replace('\\', '/').rstrip('/')
    n_str = str(name).replace('\\', '/').strip('/')
    parent = Path(p_str).expanduser()
    if parent.name.lower() == n_str.lower():
        return parent
    return parent / n_str


def create_new_folder_project(name: str, parent_path, priority: int = 2,
                              git_init: bool = False) -> dict:
    """+ New Project / create-new-folder mode.

    Creates ``<parent>/<name>`` (optional ``git init``), registers a project
    with a FRESH id, and scaffolds ``.anchor/projects/<id>/{lanes}/``. Returns
    the registry entry plus ``folder_created`` / ``git_initialized`` flags.
    """
    with WRITE_LOCK:
        parent = Path(parent_path).expanduser()
        folder = resolve_project_dir(parent, name)
        folder.mkdir(parents=True, exist_ok=True)
        git_done = _maybe_git_init(folder) if git_init else False
        # v8 Wave 1: always bootstrap (starter CLAUDE.md + git-init if absent) so
        # a session start never dead-ends on not-a-git-repo. Idempotent + best-
        # effort; honors the explicit git_init above (a no-op if already a repo).
        _bootstrap_project_best_effort(folder, name)
        entry = _rnd.add_project(name, str(folder), priority=priority,
                                 scaffold=True)
        log_change(f"R&D: created project '{name}' at {folder} (id {entry['id']})")
        try:
            discover_and_adopt(entry["id"])
        except Exception:
            pass
        return {"entry": entry, "folder_created": True,
                "git_initialized": git_done}


def select_existing_project(name: str, folder_path, priority: int = 2) -> dict:
    """+ New Project / select-existing mode.

    Registers the chosen folder as a project (fresh id, isolated store). Adding
    another project for a folder that already hosts projects is allowed
    (1 folder : N projects). A missing path still registers but surfaces a
    ``path-missing`` state on read (no crash).
    """
    with WRITE_LOCK:
        folder = Path(folder_path).expanduser()
        exists = folder.exists()
        # v8 Wave 1: bootstrap an existing folder on register — starter CLAUDE.md
        # + git-init if it isn't a repo — so a research/build session start on it
        # no longer returns not-a-git-repo. Best-effort + idempotent; skipped for
        # a missing path (nothing to bootstrap).
        if exists:
            _bootstrap_project_best_effort(folder, name)
        entry = _rnd.add_project(name, str(folder), priority=priority,
                                 scaffold=exists)
        if not exists:
            # Don't fabricate a store under a missing path; mark it so the view
            # shows path-missing rather than crashing.
            entry = dict(entry)
            entry["state"] = _rnd.STATE_PATH_MISSING
        existing = _rnd.group_by_folder().get(str(folder), [])
        log_change(f"R&D: registered project '{name}' at {folder} (id {entry['id']})")
        # Brownfield: instantly discover + adopt any pre-existing trio artifacts
        # so the tile/Kanban/home panel populate from disk on register.
        if exists:
            try:
                discover_and_adopt(entry["id"])
            except Exception:
                pass
        return {"entry": entry, "path_exists": exists,
                "siblings_in_folder": [e for e in existing
                                       if e["id"] != entry["id"]]}


def discover_and_adopt(project_id: str) -> dict:
    """One brownfield pipeline: scan -> adopt -> reconcile -> write marker.

    Called from register (``add_project`` wiring), open (``GET /project/<id>``),
    and the manual Rescan (``POST /api/rnd/rescan``). Idempotent, bounded, and
    robust to a missing/huge/UNC/mistyped folder (returns a no-op report, never
    hangs/raises). Discovered records are reconciled (pruned when their artifact
    is gone); real efforts are never touched. The marker (``Anchor.md`` +
    sidecar) is rewritten ONLY when its structure changed (no-churn).

    Returns ``{"ok": bool, "scanned": <counts>, "adopt": <report>,
    "marker": <report>}``.
    """
    proj = _rnd.get_project(project_id)
    if proj is None:
        return {"ok": False, "reason": "unknown-project"}
    folder = (proj or {}).get("folder_path", "")
    try:
        if not folder or not Path(folder).is_dir():
            return {"ok": False, "reason": "path-missing"}
    except OSError:
        return {"ok": False, "reason": "path-missing"}

    # v8 Wave 1: bootstrap on open/rescan (this is the rescan path AND the open
    # path via GET /project/<id>) — starter CLAUDE.md + git-init if the folder
    # isn't a repo. Best-effort + idempotent; heals a non-git project so a later
    # session start succeeds.
    _bootstrap_project_best_effort(folder, (proj or {}).get("name", ""))

    scan = _bscan.scan(folder)
    adopt = _eh.adopt_discovered(folder, project_id, scan)
    # Reconcile is implicit in adopt (prunes stale discovered), but run an
    # explicit pass too so a deleted artifact whose lane vanished is pruned.
    _eh.reconcile_discovered(folder, project_id)
    # Folder-history unification (Wave 2, scope #1): also adopt trio sessions
    # found in OTHER project-ids' stores for the SAME folder, so a run recorded
    # under a sibling id is not invisible to this project. Non-destructive — the
    # sibling stores/ids are left intact (the explicit, reviewable
    # ``reconcile_folder`` is what folds + hard-deletes them).
    sibling = _eh.adopt_sibling_sessions(folder, project_id)
    marker = _marker.write_anchor_md(folder)
    # Wave 5 (v3): proactively (re)generate the accurate cached PROJECT summary
    # off the render path. We force a regenerate here so a rescan picks up new
    # plan docs / deliverables; the dashboard render only READS the cache.
    _trigger_project_summary(folder, project_id, force=True)
    # Wave 6 (v3): proactively generate per-session summaries that lack a cache,
    # so an expanded session accordion serves a ready cache rather than a
    # "generating…" fallback. Background + gated like the project summary.
    _trigger_project_session_summaries(folder, project_id)
    # Gandalf v1 (decision #4): on first scan ONLY, kick off the honest project
    # read. first-run-ONLY (check-and-set BEFORE scheduling — no TOCTOU) + gated
    # by _PROACTIVE_SUMMARY_ENABLED (off in tests) + background daemon. Never
    # blocks the rescan/render path.
    _trigger_gandalf_first_scan(folder, project_id)
    return {"ok": True, "scanned": dict(scan.counts), "adopt": adopt,
            "sibling_adopt": sibling, "marker": marker}


#: Proactive project-summary generation is OFF by default so importing the module
#: and calling endpoints in unit tests never spawns a background model job. The
#: live server turns it ON in ``main()``; a test can opt in via the env flag
#: ``ANCHOR_PROACTIVE_SUMMARY=1``. When OFF, summaries are still generated
#: lazily/on demand (and the render path always just reads the cache).
_PROACTIVE_SUMMARY_ENABLED = (
    os.environ.get("ANCHOR_PROACTIVE_SUMMARY", "").strip().lower()
    in ("1", "true", "yes", "on"))


def _proactive_summary_pref(raw) -> bool:
    """v1.1.3: the server main()'s background-summary decision, testable.

    False ONLY for an EXPLICIT off (``0/false/no/off``) — the shared-install
    opt-out ``share_onboard.spawn_anchor_server`` sets, so Anchor never spends
    a collaborator's subscription without an explicit action. Unset/anything
    else keeps the author default: force-on in ``main()``.
    """
    return (raw or "").strip().lower() not in ("0", "false", "no", "off")

_zombie_hunter_started = False
_ZH_NODE_PORT = 48484
# System-Wide Sentinel Node server.js (multi-engine Burn Ledger GUI).
# Prefer ANCHOR_ZH_NODE_SERVER when set; otherwise resolve the canonical Skill
# Foundry path (or ~/.claude/skills junction). Unset/missing → Python fallback
# report only (tests + hosts without the Node skill).
def _resolve_zh_node_server_path():
    env = (os.environ.get("ANCHOR_ZH_NODE_SERVER") or "").strip()
    if env and os.path.isfile(env):
        return env
    candidates = [
        os.path.join("C:\\dev", "Skill Foundry", "skills", "zombie-hunter", "src", "server.js"),
        os.path.join(os.path.expanduser("~"), ".claude", "skills", "zombie-hunter", "src", "server.js"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "Skill Foundry",
                     "skills", "zombie-hunter", "src", "server.js"),
    ]
    for c in candidates:
        try:
            if c and os.path.isfile(c):
                return os.path.abspath(c)
        except OSError:
            continue
    return env  # may be empty — warm-start then no-ops honestly


_ZH_NODE_SERVER_PATH = _resolve_zh_node_server_path()
_zh_node_start_lock = threading.Lock()


def _zh_node_base():
    return f"http://127.0.0.1:{_ZH_NODE_PORT}"


def _zh_node_is_up(timeout=1.0):
    """True when the System-Wide Sentinel on :48484 answers /api/state."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"{_zh_node_base()}/api/state", timeout=timeout) as r:
            return 200 <= getattr(r, "status", 200) < 500
    except Exception:
        return False


def _zh_node_port_listening():
    """True if something accepts TCP on the ZH port (may still be wedged)."""
    try:
        with socket.create_connection(("127.0.0.1", _ZH_NODE_PORT), timeout=0.4):
            return True
    except OSError:
        return False


def _zh_node_kill_listener():
    """Best-effort kill of whatever holds :48484 (wedged Node after blocking probe)."""
    import subprocess
    if not sys.platform.startswith("win"):
        return False
    try:
        # netstat -ano: find LISTENING pid on our port
        out = subprocess.check_output(
            ["netstat", "-ano"],
            text=True,
            timeout=5,
            creationflags=0x08000000 if sys.platform.startswith("win") else 0,
        )
    except Exception as e:
        _logger.warning("ensure_zh_node: netstat failed: %s", e)
        return False
    killed = False
    needle = f":{_ZH_NODE_PORT}"
    for line in out.splitlines():
        if "LISTENING" not in line.upper() and "LISTEN" not in line.upper():
            continue
        if needle not in line:
            continue
        parts = line.split()
        if not parts:
            continue
        try:
            pid = int(parts[-1])
        except ValueError:
            continue
        if pid <= 0:
            continue
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                timeout=8,
                creationflags=0x08000000 if sys.platform.startswith("win") else 0,
            )
            _logger.warning("ensure_zh_node: killed wedged listener pid=%s", pid)
            killed = True
        except Exception as e:
            _logger.warning("ensure_zh_node: taskkill pid=%s failed: %s", pid, e)
    return killed


#: Consecutive failed (re)starts before the ZH-node breaker OPENS.
_ZH_NODE_MAX_RETRIES = 3
#: Backoff between attempts: 5s, 20s, 80s (capped), then the breaker opens.
_ZH_NODE_BACKOFF_BASE_S = 5.0
_ZH_NODE_BACKOFF_CAP_S = 120.0
#: How long the breaker stays open before allowing one probe again.
_ZH_NODE_COOLDOWN_S = 600.0

#: Breaker state. Guarded by ``_zh_node_start_lock`` at every mutation site.
_zh_node_breaker = {"fails": 0, "next_attempt_at": 0.0, "open_until": 0.0}


def _zh_node_breaker_reset():
    """The radar answered — forget the failure history."""
    if _zh_node_breaker["fails"]:
        _logger.info("ensure_zh_node: healthy again — breaker reset after %s failure(s)",
                     _zh_node_breaker["fails"])
    _zh_node_breaker["fails"] = 0
    _zh_node_breaker["next_attempt_at"] = 0.0
    _zh_node_breaker["open_until"] = 0.0


def _zh_node_breaker_fail():
    """One more failed (re)start: back off, and open the breaker at the cap."""
    _zh_node_breaker["fails"] += 1
    n = _zh_node_breaker["fails"]
    delay = min(_ZH_NODE_BACKOFF_CAP_S, _ZH_NODE_BACKOFF_BASE_S * (4 ** (n - 1)))
    _zh_node_breaker["next_attempt_at"] = time.time() + delay
    if n >= _ZH_NODE_MAX_RETRIES:
        _zh_node_breaker["open_until"] = time.time() + _ZH_NODE_COOLDOWN_S
        _logger.error(
            "ensure_zh_node: %s consecutive failed starts — breaker OPEN for %.0fs. "
            "The Zombie Hunter radar is DOWN and will not be respawned until then; "
            "check `node %s` by hand.",
            n, _ZH_NODE_COOLDOWN_S, _ZH_NODE_SERVER_PATH,
        )
    else:
        _logger.warning(
            "ensure_zh_node: start failed (%s/%s) — next attempt in %.0fs",
            n, _ZH_NODE_MAX_RETRIES, delay,
        )


def zh_node_breaker_state():
    """Honest read of the breaker for status surfaces/tests."""
    now = time.time()
    return {
        "fails": _zh_node_breaker["fails"],
        "open": _zh_node_breaker["open_until"] > now,
        "open_for_s": max(0.0, _zh_node_breaker["open_until"] - now),
        "next_attempt_in_s": max(0.0, _zh_node_breaker["next_attempt_at"] - now),
    }


def _ensure_zh_node_server(wait_s=10.0):
    """Start the ZH Node radar if it is down; wait until it accepts connections.

    After a host restart the Anchor boot path fire-and-forgets ``node server.js``.
    Opening the Zombie Hunter button before listen completes (or if the spawn
    failed) used to surface ``Error connecting … timed out``. This helper is
    the proxy's safety net: start once, poll briefly, return readiness.

    Also recycles a **wedged** listener: port open but HTTP timed out (classic
    blocking freeze-capability probe on the old Node build).
    """
    import subprocess
    if _zh_node_is_up(timeout=0.8):
        return True
    with _zh_node_start_lock:
        if _zh_node_is_up(timeout=0.8):
            _zh_node_breaker_reset()
            return True
        # CIRCUIT BREAKER (2026-07-26 hardening, P0.6). This recycle loop had no
        # backoff and no give-up: logs/errors.log shows 74 cycles of
        # "listening but /api/state dead -> killed wedged listener -> launched
        # server.js" at 6-8 second intervals, forking a Node process each time.
        # It was the loudest error in the log — in the very subsystem meant to
        # look trustworthy. Now: exponential backoff between attempts, and after
        # _ZH_NODE_MAX_RETRIES consecutive failures the breaker OPENS and stays
        # open for a cooldown, reporting honestly instead of thrashing.
        now = time.time()
        if _zh_node_breaker["open_until"] > now:
            _logger.debug(
                "ensure_zh_node: breaker OPEN for another %.0fs after %s "
                "consecutive failures — not respawning",
                _zh_node_breaker["open_until"] - now, _zh_node_breaker["fails"],
            )
            return False
        if now < _zh_node_breaker["next_attempt_at"]:
            return False  # inside the backoff window; stay quiet
        # Port held but unresponsive → kill and re-spawn with current server.js
        if _zh_node_port_listening():
            _logger.warning(
                "ensure_zh_node: port %s listening but /api/state dead — recycling "
                "(attempt %s/%s)",
                _ZH_NODE_PORT, _zh_node_breaker["fails"] + 1, _ZH_NODE_MAX_RETRIES,
            )
            _zh_node_kill_listener()
            time.sleep(0.4)
        try:
            if os.path.exists(_ZH_NODE_SERVER_PATH):
                creationflags = 0x08000000 if sys.platform.startswith("win") else 0
                subprocess.Popen(
                    ["node", _ZH_NODE_SERVER_PATH],
                    creationflags=creationflags,
                    cwd=os.path.dirname(_ZH_NODE_SERVER_PATH),
                )
                _logger.info("ensure_zh_node: launched server.js on port %s", _ZH_NODE_PORT)
            else:
                _logger.error("ensure_zh_node: missing %s", _ZH_NODE_SERVER_PATH)
                return False
        except Exception as e:
            _logger.error("ensure_zh_node: spawn failed: %s", e)
            return False
        deadline = time.time() + max(0.5, float(wait_s))
        while time.time() < deadline:
            if _zh_node_is_up(timeout=0.8):
                _zh_node_breaker_reset()
                return True
            time.sleep(0.35)
        if _zh_node_is_up(timeout=1.0):
            _zh_node_breaker_reset()
            return True
        _zh_node_breaker_fail()
        return False


def _trigger_project_summary(folder_path, project_id, force: bool = False):
    """Kick off proactive project-summary generation WITHOUT blocking the caller.

    Wave 5 (v3): the accurate cached project summary is generated proactively on
    rescan through the runner seam (``ANCHOR_RUNNER_CMD`` → never live claude),
    in a background daemon thread so the rescan/render path is never blocked by a
    model run. All errors are swallowed — a failed generation just leaves the row
    on its blurb fallback (and never poisons the cache, per summarizer FIX 2).

    No-op unless proactive generation is enabled (the live server enables it; see
    ``_PROACTIVE_SUMMARY_ENABLED``) so unit tests that merely register/open a
    project never spawn a background model job.
    """
    if not _PROACTIVE_SUMMARY_ENABLED:
        return
    # Snapshot the runner-seam env at TRIGGER time so a late daemon thread uses
    # the runner/counter configured now — not whatever the process env is when it
    # finally runs. (Forwarded to the spawned job via job_runner.launch(env=...).
    # In production this is just ANCHOR_RUNNER_CMD; in tests it also carries the
    # STUB_* vars so a leaked thread can't bump a later test's call counter.)
    runner_env = {k: v for k, v in os.environ.items()
                  if k == "ANCHOR_RUNNER_CMD" or k.startswith("STUB_")
                  or k.startswith("FAKE_")}

    def _run():
        try:
            _summarizer.summarize_project(folder_path, project_id, force=force,
                                          runner_env=(runner_env or None))
        except Exception:
            pass
    try:
        threading.Thread(target=_run, daemon=True).start()
    except Exception:
        pass


# ── Gandalf integration (v1) — proactive first-scan + manual re-run ───────────
# Per-project locks/guards live in-process (a server owns its subprocess jobs).
# ``_GANDALF_FIRSTSCAN_LOCKS`` serializes the first-scan check-and-set so two
# concurrent rescans can't both schedule the first run (TOCTOU double-fire).
# Track in-flight Gandalf runs per-project to prevent duplicates and expose status.
_GANDALF_LOCKS_GUARD = threading.Lock()
_GANDALF_FIRSTSCAN_LOCKS = {}
_GANDALF_INFLIGHT_GUARD = threading.Lock()
_GANDALF_INFLIGHT = {}


def _gandalf_firstscan_lock(project_id):
    """Return the per-project first-scan lock (created once)."""
    with _GANDALF_LOCKS_GUARD:
        lk = _GANDALF_FIRSTSCAN_LOCKS.get(project_id)
        if lk is None:
            lk = threading.Lock()
            _GANDALF_FIRSTSCAN_LOCKS[project_id] = lk
        return lk


def _gandalf_runner_env():
    """Snapshot the runner-seam env at trigger time (mirror of the summary
    triggers) so a late daemon thread uses the runner configured NOW. Also
    forwards the Gandalf-specific seams so a forwarded job grades through the
    same host/skill/timeout, PLUS the trio model/driver/tier seams so the Claude
    reasoner + Gemini checker resolve at the chosen tier on the real host (the
    explicit-driver-init rule): TRIO_TIER (heavy→fable-5 / standard→opus-4-8),
    CLAUDE_MODEL[_ROLE], ANTHROPIC_MODEL, GEMINI_MODEL, TRIO_MODEL[_ROLE],
    TRIO_DRIVER[_ROLE], CRUCIBLE_AGENT_LIVE."""
    _prefixes = ("STUB_", "FAKE_", "ANCHOR_GANDALF_",
                 "CLAUDE_MODEL", "TRIO_MODEL", "TRIO_DRIVER")
    _keys = {"ANCHOR_RUNNER_CMD", "TRIO_TIER", "ANTHROPIC_MODEL",
             "GEMINI_MODEL", "CRUCIBLE_AGENT_LIVE"}
    return {k: v for k, v in os.environ.items()
            if k in _keys or any(k.startswith(p) for p in _prefixes)}


def _trigger_gandalf(folder_path, project_id, *, manual=False, first_scan=False,
                     tier="standard"):
    """Schedule a Gandalf run in a daemon thread WITHOUT blocking the caller.

    Mirrors ``_trigger_project_summary``: snapshots the runner-seam env at
    trigger time and forwards it to the spawned job, runs in a background daemon
    thread, swallows all errors. Per-project in-flight guard prevents a duplicate
    pile-up.

    - ``manual=True`` (the explicit ``POST /api/rnd/gandalf_run``) is NOT gated by
      ``_PROACTIVE_SUMMARY_ENABLED`` — a manual re-run is always honored.
    - ``first_scan=True`` is the proactive register/open/rescan hook: gated by the
      module flag (off in tests) AND first-run-ONLY via ``run_gandalf_if_absent``.

    Returns ``True`` if a run was scheduled, ``False`` if suppressed (gate off, or
    already in-flight).
    """
    # The run is always RECORDED against the registry folder (store_folder) — the
    # read path (`GET /api/rnd/gandalf`, the panel render, archive/delete) resolves
    # the index off the registry folder, so storing anywhere else makes a finished
    # run permanently invisible (the 2026-06-29→07-02 __dashboard__ regression: five
    # ok-runs stranded under ANCHOR_DIR/dev while the UI polled an empty index).
    # The ANALYSIS scope for __dashboard__ is the registry folder too (the whole
    # workspace): the Wave-9 map-reduce shards a big heterogeneous tree by
    # top-level component (12-shard cap), which is exactly the honest "what's
    # really going on across my workspace" read — the old ANCHOR_DIR/dev inbox
    # re-scope produced reports about IDE junk and stranded them besides.
    store_folder = str(folder_path)
    if first_scan and not _PROACTIVE_SUMMARY_ENABLED:
        return False
    # In-flight guard: at most one scheduled-but-unfinished run per project.
    with _GANDALF_INFLIGHT_GUARD:
        if project_id in _GANDALF_INFLIGHT:
            rec = _GANDALF_INFLIGHT[project_id]
            if isinstance(rec, dict) and time.time() - rec.get("ts", 0) > 1800:
                _GANDALF_INFLIGHT.pop(project_id, None)
            else:
                return False
        _GANDALF_INFLIGHT[project_id] = {"status": "Starting...", "ts": time.time()}

    runner_env = _gandalf_runner_env()

    def _run():
        def _cb(msg):
            with _GANDALF_INFLIGHT_GUARD:
                if project_id in _GANDALF_INFLIGHT:
                    _GANDALF_INFLIGHT[project_id] = {"status": msg, "ts": time.time()}
        try:
            if first_scan:
                _gandalf.run_gandalf_if_absent(folder_path, project_id,
                                               env=(runner_env or None), status_cb=_cb,
                                               store_folder=store_folder, tier=tier)
            else:
                _gandalf.run_gandalf(folder_path, project_id,
                                     env=(runner_env or None), status_cb=_cb,
                                     store_folder=store_folder, tier=tier)
        except Exception:
            pass
        finally:
            with _GANDALF_INFLIGHT_GUARD:
                _GANDALF_INFLIGHT.pop(project_id, None)

    try:
        threading.Thread(target=_run, daemon=True).start()
        return True
    except Exception:
        with _GANDALF_INFLIGHT_GUARD:
            _GANDALF_INFLIGHT.pop(project_id, None)
        return False


def _trigger_gandalf_first_scan(folder_path, project_id):
    """First-scan hook (register/open/rescan). First-run-ONLY, no TOCTOU.

    Check-and-set under a per-project lock BEFORE scheduling: if a prior Gandalf
    run already exists OR a first-scan run is already in-flight, do nothing.
    Otherwise schedule exactly one. Gated by ``_PROACTIVE_SUMMARY_ENABLED`` (off
    in tests) so a bare register/open never spawns a model job. Never raises.
    """
    if not _PROACTIVE_SUMMARY_ENABLED:
        return False
    lk = _gandalf_firstscan_lock(project_id)
    with lk:
        try:
            if _gandalf.list_runs(folder_path, project_id):
                return False  # a prior run exists — not a first scan
        except Exception:
            return False
        # check-and-set the in-flight set under the SAME first-scan lock so two
        # concurrent rescans can't both pass the prior-run check and schedule.
        with _GANDALF_INFLIGHT_GUARD:
            if project_id in _GANDALF_INFLIGHT:
                rec = _GANDALF_INFLIGHT[project_id]
                if isinstance(rec, dict) and time.time() - rec.get("ts", 0) > 1800:
                    _GANDALF_INFLIGHT.pop(project_id, None)
                else:
                    return False
        return _trigger_gandalf(folder_path, project_id, first_scan=True)


def _reconcile_gandalf_boot_runs() -> int:
    """Boot hook (2026-07 durability Wave 3): reconcile dangling Gandalf runs.

    Right after ``job_runner.reconcile_on_startup()``, iterate the registered
    projects and reconcile each project's Gandalf index
    (``gandalf.reconcile_dangling_runs``) so an ``in_progress`` row orphaned by
    a restart goes honestly terminal (``failed / interrupted-by-restart``)
    instead of showing a perpetual "running" state. Best-effort per project,
    logged via the boot logger. Returns the total reconciled count; never
    raises."""
    total = 0
    try:
        projects = list(_rnd.list_projects())
    except Exception as e:
        _logger.error(f"gandalf boot reconcile: list_projects failed: {e}")
        projects = []
    # The synthetic __dashboard__ project (the dashboard's own "project window")
    # is fabricated on demand and is NOT in the registry, so list_projects never
    # returns it. Its Gandalf runs (e.g. a Heavy self-read) would therefore never
    # get boot-reconciled — a restart mid-run left a perpetual "running" ghost.
    # Fold it in explicitly so its dangling in_progress rows heal too.
    try:
        _dash = _rnd.get_project("__dashboard__")
        if _dash and not any(p.get("id") == "__dashboard__" for p in projects):
            projects.append(_dash)
    except Exception:
        pass
    for proj in projects:
        pid = proj.get("id") or ""
        folder = proj.get("folder_path") or ""
        if not pid or not folder:
            continue
        try:
            n = _gandalf.reconcile_dangling_runs(folder, pid)
        except Exception as e:
            _logger.error(f"gandalf boot reconcile failed for {pid}: {e}")
            continue
        if n:
            _logger.info(
                f"gandalf boot reconcile: {n} dangling run(s) → "
                f"failed/interrupted-by-restart for {pid}")
            total += n
    return total


def _trigger_session_summary(folder_path, project_id, lane, session,
                             force: bool = False):
    """Kick off proactive SESSION-summary generation WITHOUT blocking (Wave 6).

    Mirror of ``_trigger_project_summary``: generates one session's cached,
    validated summary through the runner seam in a background daemon thread, so
    neither the render path nor the read-only ``/api/rnd/session_summary``
    endpoint ever blocks on a model run. No-op unless proactive generation is
    enabled (``_PROACTIVE_SUMMARY_ENABLED``) so unit tests that merely
    register/open a project never spawn a background model job. Errors are
    swallowed (a failed run never poisons the cache, per summarizer FIX 2).

    The runner-seam env is snapshotted at trigger time (same isolation rationale
    as the project-summary trigger) and forwarded to ``job_runner.launch``.
    """
    if not _PROACTIVE_SUMMARY_ENABLED:
        return
    runner_env = {k: v for k, v in os.environ.items()
                  if k == "ANCHOR_RUNNER_CMD" or k.startswith("STUB_")
                  or k.startswith("FAKE_")}
    if runner_env:
        os.environ.setdefault("_ANCHOR_SESS_SUMMARY_ENV", "1")

    def _run():
        try:
            # Forward the snapshotted runner env onto the spawned job for test
            # isolation. summarize_session resolves the runner from the process
            # env; in production this is just ANCHOR_RUNNER_CMD (already set).
            prev = {}
            for k, v in runner_env.items():
                prev[k] = os.environ.get(k)
                os.environ[k] = v
            try:
                _summarizer.summarize_session(folder_path, project_id, lane,
                                              session, force=force)
            finally:
                for k, old in prev.items():
                    if old is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = old
        except Exception:
            pass
    try:
        threading.Thread(target=_run, daemon=True).start()
    except Exception:
        pass


def _resolve_finished_session(folder, project_id, lane, session_id):
    """Resolve the durable SESSION dict for a finished managed session (v8 Wave 5).

    A managed terminal session (the killed one) keys off a bare registry id, but
    the documents it PRODUCED were persisted (Wave 2 ``persist_session_docs``) as
    DISCOVERED efforts that group — in ``sessions.list_sessions`` — under their
    common parent directory, NOT under the bare managed id. So a kill's durable
    summary/detail must TIE the managed session to its produced docs explicitly:

      1. Prefer an exact ``sessions.list_sessions`` match on the managed id (a RUN
         session adopted under the same id, e.g. a discover→adopt flow).
      2. Else SYNTHESIZE a session dict from the lane efforts tagged with this
         managed ``session_id`` (``effort_history.efforts_for_session_id``) — the
         persisted produced docs. This is the no-loss tie: the killed session now
         resolves to a lane SESSION carrying {its id, its produced docs}, so the
         summarizer seeds skill/prompts/actions off the REAL docs (not empty).

    Returns a session dict (with ``member_files``) when the managed session has
    resolvable produced docs, else ``None`` (honest — nothing was produced).
    Never raises.
    """
    try:
        for s in _sessions.list_sessions(folder, project_id, lane):
            if s.get("session_id") == session_id:
                return s
    except Exception:
        pass
    try:
        members = _eh.efforts_for_session_id(folder, project_id, lane,
                                             session_id)
    except Exception:
        members = []
    if not members:
        return None
    # Synthesize a session dict keyed to the MANAGED id so its cached summary
    # (and the detail view, which fetches by that id) carries these exact docs.
    discovered = all(_eh.is_discovered(m) for m in members)
    try:
        ts = max(float(m.get("created_at", 0.0) or 0.0) for m in members)
    except (TypeError, ValueError):
        ts = 0.0
    skill = ""
    title = ""
    for m in members:
        if not skill and m.get("skill"):
            skill = m["skill"]
        if not title and (m.get("title") or "").strip():
            title = (m.get("title") or "").strip()
    return {
        "session_id": session_id,
        "lane": _eh._resolve_subdir(lane),
        "skill": skill,
        "timestamp": ts,
        "title": title,
        "member_files": members,
        "provenance": "imported" if discovered else "run",
        "summary_ref": None,
    }


def _trigger_session_summary_on_finish(project_id, lane, session_id):
    """Best-effort: schedule a BACKGROUND session-summary for a session that just
    reached a terminal state (v7 Wave 2 — kill / finish→build / reconcile-dead).

    Resolves the project folder + the effort-history ``session`` dict (the shape
    ``_trigger_session_summary`` needs) from ``session_id`` and kicks off the
    existing background generator. NON-BLOCKING and IDEMPOTENT:

      - returns immediately (the generation runs on a daemon thread);
      - skips when the session already has a CACHED summary (so a second finish /
        a repeated reconcile poll never re-runs the model);
      - a failed generation never poisons the cache (the summarizer surfaces
        ``error`` WITHOUT writing, per FIX 2).

    No-op unless ``_PROACTIVE_SUMMARY_ENABLED`` (the live server enables it; tests
    opt in). Never raises — any resolution failure is swallowed so it can never
    delay or break the finish (kill / finish→build / reconcile) response.
    """
    if not _PROACTIVE_SUMMARY_ENABLED:
        return
    try:
        if not project_id or not lane or not session_id:
            return
        proj = _rnd.get_project(project_id)
        if proj is None:
            return
        folder = proj.get("folder_path", "")
        if not folder:
            return
        store_lane = _eh._resolve_subdir(lane)
        # Idempotent: a session that already has a cache is left alone (the
        # summarizer would no-op it too, but skip the thread spin-up entirely).
        try:
            if _summarizer.load_cached(folder, project_id, store_lane,
                                       session_id) is not None:
                return
        except Exception:
            pass
        # v8 Wave 5 — TIE the finished managed session to the docs it PRODUCED.
        # The Wave-2 keystone persists those docs tagged with this session_id, so
        # the durable summary keyed to the managed id seeds skill/prompts/actions
        # off the REAL produced docs (no-loss), not an empty record.
        session = _resolve_finished_session(folder, project_id, lane, session_id)
        if session is None:
            # The session produced no resolvable docs (e.g. nothing was written)
            # — seed a minimal record off the registry so the summarizer still has
            # a session_id/title to key the (honest, empty) cache to.
            session = {"session_id": session_id}
        _trigger_session_summary(folder, project_id, lane, session)
    except Exception:
        pass


def _auto_push_on_finish(project_id):
    """Best-effort: auto-push the project's repo when a session reaches a terminal
    state (v8 Wave 3 — wired into the kill/finish path AFTER the produced docs are
    persisted/committed by Wave 2's capture-before-reap).

    Delegates to :func:`project_remote.auto_push_if_opted`, which pushes ONLY when
    the project is BOTH linked to a remote AND opted-in to auto-push. A non-linked
    or non-opted project never pushes. NON-BLOCKING + never raises — any failure is
    swallowed so it can never delay or break the finish response. In tests the
    configured ``origin`` is a LOCAL BARE repo (``file://``) so there is NO network.
    """
    try:
        if not project_id:
            return
        _remote.auto_push_if_opted(project_id)
    except Exception:
        pass


#: Max chars of prior-session context folded into a continue-live seed (bounded).
_MAX_CONTINUE_SEED_CHARS = 4000


#: Trio/store lane → the trio skill a resumed effort should load (W3 #6 backend).
_RESUME_LANE_SKILL = {
    "research": "researchPrime",
    "plan": "Crucible",
    "planning": "Crucible",
    "build": "Foreman",
}


def _resume_skill_for_lane(lane: str) -> str:
    """The trio skill a resumed effort in ``lane`` should load (W3 #6 backend).

    Maps a trio/store lane to its skill — research→researchPrime, plan→Crucible,
    build→Foreman. Returns ``""`` for an unknown lane (honest — no skill claimed).
    """
    return _RESUME_LANE_SKILL.get((lane or "").strip(), "")


def _detect_resume_phase(store_lane: str, doc_rels) -> str:
    """Detect the phase a discovered effort is at from its on-disk docs (W3 #6).

    Reads only the document filenames (NO model call) and returns a human phase
    label so a synthesized resume seed orients the turn:

      - planning: an IMPLEMENTATION-PLAN → ``"implementation plan (Stage 2)"``; a
        MASTER-PLAN → ``"master plan (Stage 1)"``; a NORTH-STAR → ``"intake /
        North Star (Stage 0)"``; else ``"planning"``.
      - build: an EXECUTION-LOG present → ``"build in progress"``; else ``"build"``.
      - research: ``"research investigation"``.

    Falls back to the store-lane name for an unknown lane. Never raises.
    """
    blob = " ".join(str(r or "").upper().replace("\\", "/")
                    for r in (doc_rels or []))
    sl = (store_lane or "").strip()
    if sl == "planning":
        if "IMPLEMENTATION-PLAN" in blob:
            return "implementation plan (Stage 2)"
        if "MASTER-PLAN" in blob:
            return "master plan (Stage 1)"
        if "NORTH-STAR" in blob:
            return "intake / North Star (Stage 0)"
        return "planning"
    if sl == "build":
        if "EXECUTION-LOG" in blob:
            return "build in progress"
        return "build"
    if sl == "research":
        return "research investigation"
    return sl or "work"


def _synthesize_discovered_seed(lane, store_lane, members):
    """Synthesize a resume seed for a DISCOVERED/brownfield effort (W3 #6 backend).

    When a discovered effort has NO registry record and NO cached summary, the
    seed is built from the documents on disk so the resumed turn opens WARM, not
    cold: the detected phase, the trio skill to load, and the enumerated document
    list. Returns a list of seed-text blocks (the caller appends them to the seed
    ``parts``); ``[]`` when there are no documents to synthesize from.
    """
    docs = []
    for m in members or []:
        rel = (m.get("artifact_path") or "").strip().replace("\\", "/")
        if not rel:
            continue
        docs.append((rel, (m.get("title") or "").strip()))
    if not docs:
        return []
    skill = _resume_skill_for_lane(lane) or _resume_skill_for_lane(store_lane)
    phase = _detect_resume_phase(store_lane, [r for r, _ in docs])
    blocks = ["Lane: " + str(lane) + " · Phase: " + phase]
    if skill:
        blocks.append("Skill to load: " + skill)
    doc_lines = ["Documents on disk (read these first to recover context):"]
    for rel, title in docs:
        doc_lines.append("- " + rel + ((" — " + title) if title else ""))
    blocks.append("\n".join(doc_lines))
    blocks.append(
        "Read the documents listed above to recover the full context, then load "
        "the " + (skill or "appropriate trio") + " skill and continue the "
        + phase + " work where it left off.")
    return blocks


def _build_continue_seed(folder_path, project_id, lane, source_session_id):
    """Build the seed_context text for "Continue in a live session" (v5 Wave 2).

    READ-ONLY: resolves the prior (done/historical) session and assembles a
    compact context string from its CACHED summary, preferring (in order):

      1. the cached summary's rendered markdown (``markdown``), else
      2. a deterministic digest of the cached summary's structured fields
         (skill · what-was-asked · north-star · prompts · files produced), else
      3. the live session record's intent (``what_was_asked`` / ``title``).

    NEVER mutates the original session/summary (Risk R2) — every access is a read.
    Returns a bounded string (or ``""`` when nothing resolves, in which case the
    new session is started bare-seeded with just the lane skill). Stdlib only;
    never raises.
    """
    store_lane = _eh._resolve_subdir(lane)
    cached = None
    try:
        cached = _summarizer.load_cached(folder_path, project_id, store_lane,
                                         source_session_id)
    except Exception:
        cached = None

    parts = ["This is a continuation of an earlier session in the "
             + str(lane) + " lane. Here is its summary so you can pick up the "
             "work:"]
    if isinstance(cached, dict):
        md = (cached.get("markdown") or "").strip()
        if md:
            parts.append(md)
        else:
            skill = (cached.get("skill") or "").strip()
            if skill:
                parts.append("Skill: " + skill)
            asked = (cached.get("what_was_asked") or "").strip()
            if asked:
                parts.append("Originally asked: " + asked)
            ns = (cached.get("north_star") or "").strip()
            if ns:
                parts.append("North Star: " + ns)
            prompts = cached.get("prompts") or []
            if prompts:
                parts.append("Prompts asked: "
                             + " | ".join(str(p) for p in prompts))
            actions = cached.get("actions") or []
            labels = []
            for a in actions:
                if isinstance(a, dict):
                    lbl = (a.get("label") or a.get("rel")
                           or a.get("job_id") or "").strip()
                else:
                    lbl = str(a).strip()
                if lbl:
                    labels.append(lbl)
            if labels:
                parts.append("Files produced: " + ", ".join(labels))
    else:
        # No cached summary. Resolve the source session from disk. For a
        # DISCOVERED/brownfield effort (no registry record AND no cached summary),
        # SYNTHESIZE an orienting seed from the documents on disk — the detected
        # phase, the trio skill to load, and the enumerated document list (W3 #6
        # backend) — so the resumed turn opens WARM, not cold. Otherwise fall back
        # to the session record's bare intent (its title).
        session = None
        try:
            for s in _sessions.list_sessions(folder_path, project_id, lane):
                if s.get("session_id") == source_session_id:
                    session = s
                    break
        except Exception:
            session = None
        if session:
            members = session.get("member_files", []) or []
            discovered = bool(members) and all(
                _eh.is_discovered(m) for m in members)
            synth = []
            if discovered:
                try:
                    synth = _synthesize_discovered_seed(
                        lane, store_lane, members)
                except Exception:
                    synth = []
            if synth:
                # Replace the generic "here is its summary" lead-in with a
                # discovered-specific one — there is genuinely no prior session
                # summary; the context below is synthesized from on-disk docs.
                parts[0] = ("This is a brownfield/discovered effort in the "
                            + str(lane) + " lane being resumed as a live "
                            "session. There is no prior Anchor session summary, "
                            "so this orienting context is synthesized from the "
                            "documents already on disk:")
                parts.extend(synth)
            else:
                asked = (session.get("title") or "").strip()
                if asked:
                    parts.append("Originally: " + asked)

    text = "\n\n".join(p for p in parts if p and p.strip()).strip()
    # If we never resolved any real prior context (only the lead-in line), return
    # empty so the new session is started bare-seeded (just the lane skill).
    if len(parts) <= 1:
        return ""
    return text[:_MAX_CONTINUE_SEED_CHARS]


def _trigger_project_session_summaries(folder_path, project_id):
    """Proactively generate summaries for all of a project's sessions lacking a
    cache (Wave 6) — bounded, background, gated like the project-summary trigger.

    Walks each trio lane's sessions (skipping the defensive ``loose::`` wrappers),
    and for any session WITHOUT a cached summary kicks off a background
    generation. No-op unless ``_PROACTIVE_SUMMARY_ENABLED``. Best-effort: any
    error per lane/session is swallowed so a rescan is never blocked or broken.
    """
    if not _PROACTIVE_SUMMARY_ENABLED:
        return
    try:
        # Exclude grass (workbench-only) AND general (bare terminals — proactively
        # summarizing the many ad-hoc general sessions would add needless
        # background load; the general tile shows its label without a cached blurb).
        lanes = [c[0] for c in _KANBAN_COLUMNS if c[0] not in ("grass", "general")]
    except Exception:
        lanes = ["research", "plan", "build", "deliverables"]
    for trio_lane in lanes:
        try:
            sess_list = _sessions.list_sessions(folder_path, project_id, trio_lane)
        except Exception:
            continue
        for s in sess_list:
            sid = (s.get("session_id") or "")
            if not sid or sid.startswith("loose::"):
                continue
            store_lane = _eh._resolve_subdir(trio_lane)
            try:
                if _summarizer.load_cached(folder_path, project_id, store_lane,
                                           sid) is not None:
                    continue
            except Exception:
                pass
            _trigger_session_summary(folder_path, project_id, trio_lane, s)


def render_status_line_html(project_id: str) -> str:
    """Render the per-lane SESSION summary line (Research/Planning/Build/Deliv).

    Wave 3 contract: ``rnd_registry.status_line`` returns per-lane counts +
    provenance, so the line reads e.g.
    ``Research: 1 · Planning: 2 (1 imported) · Build: 1 · Deliverables: 1`` —
    a lane with sessions NEVER renders as ``import`` or ``none-yet``. A lane with
    zero sessions shows a dimmed ``0``; an imported count adds a small
    ``(N imported)`` provenance chip; a live job adds ``• N running``.
    """
    line = _rnd.status_line(project_id)
    chips = []
    for lane in _rnd.STATUS_LANES:
        counts = line.get(lane) or {}
        n = int(counts.get("count", 0) or 0)
        n_imp = int(counts.get("imported", 0) or 0)
        n_run = int(counts.get("running", 0) or 0)
        label = lane.capitalize()
        prov = (f' <span class="rnd-imported">({n_imp} imported)</span>'
                if n_imp else '')
        run = (f' <span class="rnd-running">&bull; {n_run} running</span>'
               if n_run else '')
        dim = ' rnd-lane-empty' if n == 0 else ''
        chips.append(
            f'<span class="rnd-lane{dim}">'
            f'{html_lib.escape(label)}: {n}{prov}{run}</span>'
        )
    return '<div class="rnd-status-line">' + "".join(chips) + "</div>"


def _project_summary_text(entry: dict) -> tuple:
    """Return ``(summary_text, source)`` for a project's thin-row summary.

    Wave 5 (v3): the row's summary is the accurate CACHED project summary when
    present (``summarizer.load_cached_project`` — read-only, NEVER runs the model
    on the render path), else the existing blurb (seeded once from CLAUDE.md/
    README/Anchor.md), else "". ``source`` is ``"summary"`` | ``"blurb"`` | ``""``.
    """
    pid_raw = entry.get("id", "")
    folder = entry.get("folder_path", "")
    # 1. Cached project summary (read-only — no model run on the render path).
    if folder:
        try:
            cached = _summarizer.load_cached_project(folder, pid_raw)
            if cached:
                txt = (cached.get("summary_text") or "").strip()
                if txt:
                    # v7 Wave 1: normalize the cached summary to a clean, capped
                    # plain-text short line for the row (strip markdown/glyphs).
                    return _summarizer.short_summary_text(txt), "summary"
        except Exception:
            pass
    # 2. Fall back to the blurb (seed once if empty).
    blurb = entry.get("blurb", "") or ""
    if not blurb.strip():
        try:
            seeded = _rnd.seed_blurb(pid_raw)
            if seeded:
                blurb = seeded.get("blurb", "") or ""
        except Exception:
            pass
    if blurb.strip():
        return blurb.strip(), "blurb"
    return "", ""


def _project_status_dot(entry: dict, status_line: dict, registry_running: int = 0) -> str:
    """Pick the row's status-dot class (kept simple + documented, Wave 5).

    Mapping: green if ANY lane has a running session; for inactive projects
    (archived/future/retired) a dimmed grey; otherwise a neutral idle grey. The
    dot is purely advisory (the per-lane mini-counts carry the detail).

    v10.1 FIX 3 — ``status_line.running`` counts ONLY effort-history/job_runner
    sessions; a live MANAGED terminal/ConPTY session registers in
    ``session_registry`` as RUNNING with NO job_runner record, so it left the dot
    grey. ``registry_running`` (the count from the SAME registry read the
    activity line already does, ZERO new rnd_jobs/ scans) greens the dot when any
    managed session is running. (A running general/grass managed session greens
    the dot too — a defensible "is anything running" signal.)"""
    state = entry.get("state", "active")
    if state in ("archived", "future", "retired"):
        return "rnd-dot-idle"
    try:
        if int(registry_running or 0) > 0:
            return "rnd-dot-running"
        if any(int((status_line.get(l) or {}).get("running", 0) or 0) > 0
               for l in status_line):
            return "rnd-dot-running"
    except Exception:
        pass
    return "rnd-dot-idle"


# Map a registry session status → the locked status-light color word, mirroring
# `_session_light_class` / the JS `_statusColor` (single source of truth for the
# four colors). Used by the home-row "what's happening" line (Wave 7).
_SESSION_STATUS_COLOR = {
    _sessreg.STATUS_RUNNING: "green",
    _sessreg.STATUS_NEEDS_ATTENTION: "amber",
    _sessreg.STATUS_DONE: "amber",
    _sessreg.STATUS_FAILED: "red",
    _sessreg.STATUS_IDLE: "grey",
    # Wave 5: the split of the overloaded idle — a parked-warm session is a grey
    # reopenable tile (like idle); a reaped orphan is a spent grey tile.
    _sessreg.STATUS_PARKED_WARM: "grey",
    _sessreg.STATUS_REAPED_ORPHAN: "grey",
}


def _project_activity_reflection(pid_raw: str) -> dict:
    """Return a CACHE/REGISTRY-only activity reflection for a home-dashboard row
    (v6 Wave 7). Reads ONLY ``session_registry`` (no model call, no PTY) so it is
    safe on the render path.

    Returns ``{running: int, latest: {lane, label, status, color, age} | None}``:
    - ``running`` — how many of the project's managed sessions are RUNNING;
    - ``latest`` — the newest session (by ``created_at``) with a human label, its
      lane, status, status-color word, and a compact age — for the "latest:
      planning · Crucible pipeline plan (running)" line. ``None`` when the
      project has no managed sessions at all (honest — never fabricated).
    Never raises (a registry hiccup degrades to ``{running:0, latest:None}``).
    """
    out = {"running": 0, "latest": None}
    try:
        sessions = _sessreg.list_sessions(project_id=pid_raw)
    except Exception:
        return out
    if not sessions:
        return out
    out["running"] = sum(1 for s in sessions
                         if s.get("status") == _sessreg.STATUS_RUNNING)
    # list_sessions is already newest-first by created_at, so [0] is the newest.
    newest = sessions[0]
    lane = (newest.get("lane") or "").strip()
    status = (newest.get("status") or _sessreg.STATUS_IDLE).strip()
    # A friendly title: the session's own label if it set one, else the lane name.
    label = (newest.get("label") or "").strip() or (lane.capitalize() or "session")
    # v12 W10 — the EFFORT's current_stage (research/plan/build) is the truthful
    # "where this effort is" signal (the lane flips as an effort advances, but it
    # always reflects the most-advanced stage). Prefer it for the home-row line;
    # fall back to the lane when this is not a v12 effort. Cache/registry-only.
    stage = (newest.get("current_stage") or "").strip()
    out["latest"] = {
        "lane": lane,
        "stage": stage,
        "label": label,
        "status": status,
        "color": _SESSION_STATUS_COLOR.get(status, "grey"),
        "age": _fmt_age(newest.get("created_at")),
    }
    return out


def _render_activity_reflection_html(refl: dict) -> str:
    """Render the per-row activity-reflection block (v6 Wave 7): a running
    indicator/count + a "what's happening" latest-session line. Honest empty
    state ("idle — no sessions") when the project has none. Pure formatting of
    the cache/registry-sourced ``refl`` dict; never runs the model."""
    running = int(refl.get("running", 0) or 0)
    latest = refl.get("latest")
    parts = []
    if running > 0:
        # A live indicator (the pulsing dot CSS) + the count.
        parts.append(
            f'<span class="rnd-act-running" title="live sessions">'
            f'<span class="rnd-act-pulse" aria-hidden="true"></span>'
            f'running: {running}</span>'
        )
    if latest:
        lane = latest.get("lane") or ""
        # v12 W10 — show the effort's current_stage when present (research/plan/
        # build), else the lane (honest fallback for non-effort sessions).
        stage = (latest.get("stage") or "").strip()
        lane_lbl = html_lib.escape(
            (stage or lane).capitalize() or "session")
        title = html_lib.escape(latest.get("label") or "")
        status = html_lib.escape(latest.get("status") or "")
        color = html_lib.escape(latest.get("color") or "grey")
        age = html_lib.escape(latest.get("age") or "")
        age_txt = f' · {age}' if age else ""
        parts.append(
            f'<span class="rnd-act-latest">latest: '
            f'<span class="rnd-act-lane">{lane_lbl}</span> · '
            f'<span class="rnd-act-title">{title}</span> '
            f'<span class="rnd-act-status rnd-act-{color}">'
            f'({status})</span>{age_txt}</span>'
        )
    if not parts:
        # Honest placeholder — never fabricate activity.
        parts.append('<span class="rnd-act-latest rnd-dim">'
                     'idle — no sessions yet</span>')
    return '<div class="rnd-row-activity">' + "".join(parts) + "</div>"


def render_project_tile_html(entry: dict) -> str:
    """Render a THIN, full-width project ROW (v3 Wave 5, IMPLEMENTATION-PLAN
    lines 124-141): ``name · accurate cached project summary · per-lane
    mini-counts · status dot``. Clicking the row opens the project window;
    lifecycle controls (P1/P2, rescan, blurb, notes, archive/retire/reactivate)
    moved OFF the row into a kebab/hover menu so the row stays one line. This
    REPLACES the old square ``.rnd-tile``."""
    pid_raw = entry.get("id", "")
    pid = html_lib.escape(pid_raw)
    name = html_lib.escape(entry.get("name", ""))
    pr = entry.get("priority", 2)
    state = html_lib.escape(entry.get("state", "active"))
    notes = entry.get("notes", "") or ""
    notes_attr = html_lib.escape(notes, quote=True)
    folder = entry.get("folder_path", "")

    # Row summary text: cached project summary, else blurb (read-only path).
    summary_text, _src = _project_summary_text(entry)
    summary_attr = html_lib.escape(summary_text, quote=True)
    summary_block = (f'<span class="rnd-row-summary" title="{summary_attr}">'
                     f'{html_lib.escape(summary_text)}</span>'
                     if summary_text else
                     '<span class="rnd-row-summary rnd-dim">No summary yet</span>')
    # data-blurb keeps the kebab "Blurb" prompt seeded with the editable blurb.
    blurb = entry.get("blurb", "") or ""
    blurb_attr = html_lib.escape(blurb, quote=True)

    # v6 Wave 7 — timely activity reflection (running count + newest-session
    # "what's happening" line), sourced from the session registry ONLY (no model
    # call on the render path). Honest "idle — no sessions yet" placeholder when
    # the project has none.
    # v10.1 FIX 3 — capture the reflection ONCE (it carries the registry running
    # count) so the status dot can reuse it (the SAME single registry read; ZERO
    # new rnd_jobs/ scans, GET / perf invariant holds).
    refl = _project_activity_reflection(pid_raw)
    activity_block = _render_activity_reflection_html(refl)

    # Per-lane mini-counts (compact form of the status line) + status dot.
    status = render_status_line_html(pid_raw)
    try:
        sline = _rnd.status_line(pid_raw)
    except Exception:
        sline = {}
    # v10.1 FIX 3 — pass the registry running count so a live MANAGED terminal
    # session (no job_runner record → status_line.running == 0) still greens the
    # home-row dot.
    dot_cls = _project_status_dot(
        entry, sline, registry_running=int(refl.get("running", 0) or 0))

    # Per-row cost/tokens/time rollup (v4 Wave 8, MASTER-PLAN cockpit dashboard
    # rows). Reuses the Wave-3 `effort_history.project_effort_rollup` (RUN-session
    # totals only — imported/discovered contribute 0, never fabricated) and the
    # shared `_fmt_rollup_line` formatter. Rendered at LIFETIME by default; the
    # R&D view's single global lifetime/30-day toggle (rndRowsRollupWindow) swaps
    # every row's text in place via the read-only `/api/rnd/project_rollup`
    # endpoint, so a no-JS view still shows lifetime totals. Never raises.
    rate = {}
    try:
        rate = _rollhon.project_capture_rate(pid_raw, window="lifetime") or {}
    except Exception:
        rate = {}
    try:
        roll = _eh.project_effort_rollup(pid_raw, window=_eh.WINDOW_LIFETIME)
    except Exception:
        roll = {"tokens": 0, "cost_usd": 0.0, "wall_clock_ms": 0, "sessions": 0}
    live_n = _live_session_count(pid_raw)
    try:
        roll_txt = html_lib.escape(
            _fmt_project_usage_line(roll, rate=rate, live_count=live_n))
    except Exception:
        roll_txt = html_lib.escape("Σ no run sessions yet")
    # Honesty stamp: measured vs unmeasured (incl. Grok wall-clock-only).
    cap_note = ""
    try:
        if int(rate.get("total", 0) or 0) > 0:
            cap_note = " · " + html_lib.escape(
                _rollhon.capture_rate_text(rate)
                if hasattr(_rollhon, "capture_rate_text")
                else _fmt_capture_rate_short(rate))
    except Exception:
        cap_note = ""
    rollup_block = (
        f'<span class="rnd-row-roll" data-pid="{pid}" data-window="lifetime" '
        f'title="Cost / tokens / time across run sessions (RUN provenance only;'
        f' Grok may show time without $)">{roll_txt}{cap_note}</span>'
    )

    is_active = state in ("active", "path-missing")
    p1on = " rnd-pr-on" if pr == 1 else ""
    p2on = " rnd-pr-on" if pr == 2 else ""
    rescan_btn = (f'<button class="rnd-mini" onclick="rndRescan(\'{pid}\')" '
                  f'title="Re-scan the folder for trio artifacts">Rescan</button>')
    if is_active:
        lifecycle = (
            f'<button class="rnd-mini{p1on}" onclick="rndSetPriority(\'{pid}\',1)" title="Priority 1">P1</button>'
            f'<button class="rnd-mini{p2on}" onclick="rndSetPriority(\'{pid}\',2)" title="Priority 2">P2</button>'
            f'{rescan_btn}'
            f'<button class="rnd-mini" onclick="rndBlurb(\'{pid}\')" title="Edit blurb (what this project is)">Blurb</button>'
            f'<button class="rnd-mini" onclick="rndNotes(\'{pid}\')" title="Edit notes">Notes</button>'
            f'<button class="rnd-mini" onclick="rndArchive(\'{pid}\')" title="Archive (shelve, reviewable)">Archive</button>'
            f'<button class="rnd-mini rnd-danger" onclick="rndRetire(\'{pid}\')" title="Retire / cancel">Retire</button>'
        )
    else:
        lifecycle = (
            f'<button class="rnd-mini rnd-accent" onclick="rndReactivate(\'{pid}\')" title="Make active again">Reactivate</button>'
            f'{rescan_btn}'
            f'<button class="rnd-mini" onclick="rndBlurb(\'{pid}\')" title="Edit blurb (what this project is)">Blurb</button>'
            f'<button class="rnd-mini" onclick="rndNotes(\'{pid}\')" title="Edit notes">Notes</button>'
        )
    # Kebab menu holds all lifecycle controls so the row stays thin. The row
    # itself (click anywhere not on the kebab) opens the project window.
    kebab = (
        f'<div class="rnd-kebab" onclick="event.stopPropagation()">'
        f'<button class="rnd-kebab-btn" onclick="rndToggleKebab(event,\'{pid}\')" '
        f'title="Project actions" aria-label="Project actions">&#8942;</button>'
        f'<div class="rnd-kebab-menu" id="rnd-kebab-{pid}">'
        f'{lifecycle}'
        f'</div>'
        f'</div>'
    )
    # v9 Wave 3 — drag-to-group: the row is draggable and carries its current
    # group so the drag handlers can call /api/rnd/set_group (dashboard-only; NO
    # disk move). The ⋮⋮ grip is the drag affordance. The on-disk folder path is
    # deliberately NOT stamped on the row (it lives on the project-window header;
    # the v8 no-path-on-dashboard invariant holds — the Wave-4 move dialog reads
    # the path server-side, not from the row).
    group = entry.get("group", "") or ""
    group_attr = html_lib.escape(group, quote=True)
    return (
        f'<div class="rnd-row" data-project-id="{pid}" data-notes="{notes_attr}" '
        f'data-blurb="{blurb_attr}" data-group="{group_attr}" '
        f'draggable="true" tabindex="0" role="button" '
        f'onclick="openProjectWindow(\'{pid}\')" '
        f'title="Open {name}">'
        f'<span class="rnd-grip" aria-hidden="true" '
        f'title="Drag into a folder">&#8942;&#8942;</span>'
        f'<span class="rnd-dot {dot_cls}" aria-hidden="true"></span>'
        f'<img class="rnd-seal-ico" src="{_steward_seal_icon_src()}" alt="" '
        f'onerror="this.style.display=\'none\'" />'
        f'<span class="rnd-name">{name}</span>'
        f'<span class="rnd-badge rnd-p{pr}">P{pr}</span>'
        f'<span class="rnd-badge rnd-state-{state}">{state}</span>'
        f'{summary_block}'
        f'{activity_block}'
        f'<span class="rnd-row-counts">{status}</span>'
        f'{rollup_block}'
        f'{kebab}'
        f'</div>'
    )


def _render_folder_groups(groups: dict) -> str:
    """Render a FLAT one-line ROW list for the dashboard (v4 Wave 8 — archive view).

    The per-folder directory header is GONE on the FLAT path; projects render as
    a single flat list of thin rows. Still used by the Archive view, which has no
    group concept. The ACTIVE home dashboard now uses
    :func:`_render_group_folders` (v9 Wave 3 collapsible folders) instead.
    """
    rows = []
    for folder in sorted(groups):
        rows.extend(render_project_tile_html(e) for e in groups[folder])
    return ('<div class="rnd-projects">'
            '<div class="rnd-folder-rows">' + "".join(rows) + '</div>'
            '</div>')


def _group_folder_path(entries: list) -> str:
    """If every project in a group shares one on-disk parent/path, return it.

    The mockup shows a folder's real on-disk path in the header only when it is
    uniform across the group's projects. Returns "" when the group is empty or
    its projects live in different folders (heterogeneous → no path shown).
    """
    paths = {(e.get("folder_path") or "") for e in entries if e.get("folder_path")}
    if len(paths) == 1:
        return next(iter(paths))
    return ""


def _render_group_folders(groups: dict) -> str:
    """Render the home dashboard's COLLAPSIBLE FOLDERS (v9 Wave 3).

    ``groups`` is keyed by GROUP NAME (from ``rnd_registry.group_by_group``) →
    list of project entries; the empty-group bucket is keyed ``Ungrouped`` and
    always renders last (it is the drop target for "remove from a folder").

    Each folder is a header (▸/▾ twisty · name · count · uniform on-disk path)
    over a body of the group's thin project rows. Folders are a drop target for
    drag-to-group; collapse state is persisted client-side (localStorage) by the
    home dashboard JS (``rndFolderInit``). Organization ONLY — no disk move.
    """
    ungrouped_label = getattr(_rnd, "UNGROUPED_LABEL", "Ungrouped")
    # Order: named groups as given (group_by_group already sorts them), with
    # Ungrouped last regardless of dict order.
    names = [g for g in groups if g != ungrouped_label]
    if ungrouped_label in groups:
        names.append(ungrouped_label)

    folders = []
    for gname in names:
        entries = groups.get(gname, [])
        rows = "".join(render_project_tile_html(e) for e in entries)
        name_esc = html_lib.escape(gname)
        name_attr = html_lib.escape(gname, quote=True)
        is_ungrouped = (gname == ungrouped_label)
        # The Ungrouped bucket is a catch-all, not a real on-disk folder → never
        # stamp a path on it (even if its members happen to share a dir).
        fpath = "" if is_ungrouped else _group_folder_path(entries)
        path_block = (f'<span class="rnd-fpath">{html_lib.escape(fpath)}</span>'
                      if fpath else '')
        drop_hint = ('<span class="rnd-fdrop-hint">drop here to remove '
                     'from a folder</span>' if is_ungrouped else '')
        folders.append(
            f'<div class="rnd-folder" data-group="{name_attr}" '
            f'data-ungrouped="{"1" if is_ungrouped else "0"}">'
            f'<div class="rnd-folder-head" '
            f'onclick="rndToggleFolder(this)" role="button" tabindex="0" '
            f'title="Collapse / expand folder">'
            f'<span class="rnd-tw" aria-hidden="true">▾</span>'
            f'<span class="rnd-fname">{name_esc}</span>'
            f'<span class="rnd-fcount">({len(entries)})</span>'
            f'{path_block}'
            f'<span class="rnd-fsp"></span>'
            f'{drop_hint}'
            f'</div>'
            f'<div class="rnd-folder-body">{rows}</div>'
            f'</div>'
        )
    return ('<div class="rnd-projects">'
            '<div class="rnd-folder-list" id="rndFolderList">'
            + "".join(folders) +
            '</div></div>')


def render_projects_view_html(include_archived: bool = False,
                              include_future: bool = False,
                              include_retired: bool = False) -> str:
    """Render the ACTIVE folder-grouped projects view (collapsible folder → tiles).

    Defaults to active-only; inactive projects (archived/future/retired) live on
    the separate Archive view (:func:`render_archive_view_html`).
    """
    groups = _rnd.group_by_group(include_archived=include_archived,
                                 include_future=include_future,
                                 include_retired=include_retired)
    # group_by_group always returns the Ungrouped bucket; "empty" = only an
    # empty Ungrouped bucket and no named (extra) groups.
    ungrouped_label = getattr(_rnd, "UNGROUPED_LABEL", "Ungrouped")
    has_any = any(groups.get(g) for g in groups)
    extra_groups = sorted(g for g in groups if g != ungrouped_label)
    if not has_any and not extra_groups:
        return ('<div class="rnd-projects"><p class="rnd-empty">'
                'No active R&D projects. Use "+ New Project" to add one.</p></div>')
    return (_render_folder_toolbar()
            + _render_rows_rollup_toggle()
            + _render_group_folders(groups))


def _render_folder_toolbar() -> str:
    """The "+ New folder" control row above the collapsible folders (v9 W3).

    "+ New folder" prompts for a name and creates an empty group; you then drag
    a project row into it (NO disk move). Purely additive — a no-JS view still
    renders the existing folders below."""
    return (
        '<div class="rnd-folder-toolbar">'
        '<button class="rnd-newfolder-btn" type="button" '
        'onclick="rndNewFolder()" title="Create a new project folder (group)">'
        '+ New folder</button>'
        '<span class="rnd-folder-hint">drag any project row (⋮⋮) '
        'into a folder header to group it</span>'
        '</div>'
    )


def _render_rows_rollup_toggle() -> str:
    """A single GLOBAL lifetime/30-day toggle for the R&D rows' cost rollups
    (v4 Wave 8). Clicking re-fetches every row's read-only
    ``/api/rnd/project_rollup?window=...`` and swaps the text in place
    (``rndRowsRollupWindow`` in the JS). Lifetime is the default; the toggle is
    purely additive (a no-JS view still shows lifetime totals on each row)."""
    return (
        '<div class="rnd-rows-rolltog" role="group" '
        'aria-label="project rollup window">'
        '<span class="rnd-rows-rolltog-label">Σ&nbsp;effort:</span>'
        '<b class="on" data-window="lifetime" '
        'onclick="rndRowsRollupWindow(\'lifetime\',this)">lifetime</b>'
        '<b data-window="30d" '
        'onclick="rndRowsRollupWindow(\'30d\',this)">30d</b>'
        '</div>'
    )


def render_archive_view_html() -> str:
    """Render the Archive/Inactive view: archived + future + retired projects,
    each reactivatable (the tile shows a Reactivate button for inactive states)."""
    inactive = _rnd.list_inactive_projects()
    if not inactive:
        return ('<div class="rnd-projects"><p class="rnd-empty">'
                'No archived, future, or retired projects.</p></div>')
    groups = {}
    for e in inactive:
        groups.setdefault(e.get("folder_path", ""), []).append(e)
    return _render_folder_groups(groups)


# Kanban column wiring: which trio/store lanes map to each board column, the
# column's display label + glyph, and the "+ New run" affordance.
_KANBAN_COLUMNS = (
    ("research", "research", "Research", "\U0001F52C", "+ New research run"),
    ("plan", "planning", "Planning", "\U0001F4D0", "+ New plan run"),
    ("build", "build", "Build", "\U0001F528", "+ New build run"),
    ("deliverables", "deliverables", "Deliverables", "\U0001F4E6", "+ Add deliverable"),
    ("grass", "grass", "Grass Catchers", "\U0001F33F", "+ Add idea"),
    # General sessions (bare terminals — NOT a trio lane, stage-less/skill-less).
    # They were previously only visible on the ephemeral top strip; this column
    # gives them a durable board zone (most-recent headline + older-runs shelf),
    # rendered explicitly in _render_layoutd_html. The gather loops fold in the
    # lane's on-disk efforts + live registry general sessions.
    ("general", "general", "General", "\U0001F4BB", "+ New general session"),
)


def _fmt_age(created_at) -> str:
    """Compact relative age ("now", "5m", "2h", "3d", "1w") from an epoch ts."""
    try:
        ts = float(created_at or 0)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    delta = max(0.0, time.time() - ts)
    if delta < 60:
        return "now"
    if delta < 3600:
        return f"{int(delta // 60)}m"
    if delta < 86400:
        return f"{int(delta // 3600)}h"
    if delta < 604800:
        return f"{int(delta // 86400)}d"
    return f"{int(delta // 604800)}w"


# v4 Wave 4 — Paradigm-2 lane-tile status light.
#
# Map a session's representative effort view → the LOCKED status-light bucket
# (session_registry status constants → colors, MASTER-PLAN §E):
#   running                       → green  (live PTY / job producing output)
#   needs-attention / done        → amber  (come look — waiting on you or finished)
#   failed / cancelled / interrupted → red
#   idle / unknown / discovered   → grey
# This mirrors the JS ``_statusColor`` (which maps the registry status strings):
# a single source of truth for the four colors, applied here at the lane-tile
# render and there at the live session-bar / panel render.
def _session_light_class(ev):
    """Return the lane-tile status-light color class ('green'|'amber'|'red'|
    'grey') for a session's representative effort view ``ev``."""
    if not ev:
        return "grey"
    if ev.get("needs_input"):
        return "amber"          # needs-attention (awaiting input)
    if ev.get("is_live"):
        return "green"          # running
    status = (ev.get("status") or "").strip()
    if ev.get("is_done") or status == _jr.STATUS_DONE:
        return "amber"          # done → amber (finished; awaiting your review)
    if status in (_jr.STATUS_FAILED, _jr.STATUS_INTERRUPTED, _jr.STATUS_CANCELLED):
        return "red"
    return "grey"               # idle / discovered / unknown


# Map a job record's status/state to the board state-pill class + label.
def _effort_pill(status, gate_state):
    """Return ``(pill_class, pill_label, is_live, needs_input)`` for an effort."""
    if gate_state == "awaiting-input":
        return ("input", "needs input", True, True)
    if status == _jr.STATUS_RUNNING:
        return ("run", "running", True, False)
    if status == _jr.STATUS_DONE:
        return ("done", "done", False, False)
    if status in (_jr.STATUS_FAILED, _jr.STATUS_INTERRUPTED, _jr.STATUS_CANCELLED):
        label = "failed" if status == _jr.STATUS_FAILED else status
        return ("fail", label, False, False)
    return ("", status or "queued", False, False)


def _gather_project_efforts(folder_path, project_id):
    """Join each lane's effort pointer-records with their live job records.

    Returns ``{column_lane: [effort_view, ...]}`` newest-first, where an
    ``effort_view`` carries everything the board needs (already HTML-escaped
    where it lands in attributes/text) plus the live status/gate.
    """
    # Gather each lane's efforts ONCE, then load ONLY the job records those
    # efforts actually reference (targeted load_record per job_id) — instead of
    # scanning the entire global rnd_jobs/ dir via list_records() for every
    # project-lane. That full scan made the dashboard O(projects x lanes x
    # all-jobs); once rnd_jobs/ grew to ~1k records it pushed GET / past the
    # health check's 5s timeout (the red banner). The lookup only ever needs the
    # records for THIS project's efforts, so load exactly those.
    efforts_by_lane = {}
    needed_jids = set()
    for trio_lane, _subdir, _label, _glyph, _addlabel in _KANBAN_COLUMNS:
        try:
            lane_efforts = _eh.list_efforts(folder_path, project_id, trio_lane)
        except Exception:
            lane_efforts = []
        efforts_by_lane[trio_lane] = lane_efforts
        for _e in lane_efforts:
            _jid = _e.get("job_id")
            if _jid:
                needed_jids.add(_jid)
    jobs_by_id = {}
    for _jid in needed_jids:
        try:
            _rec = _jr.load_record(_jid)
        except Exception:
            _rec = None
        if _rec:
            jobs_by_id[_jid] = _rec
    out = {}
    for trio_lane, _subdir, _label, _glyph, _addlabel in _KANBAN_COLUMNS:
        efforts = efforts_by_lane.get(trio_lane, [])
        views = []
        # Version numbering (vN) is computed over NON-DISCOVERED (real) efforts
        # ONLY (honesty contract): a discovered card gets NO vN. So the newest
        # REAL effort is v<real_count>, descending; discovered cards are skipped
        # in the version counter and instead carry an "imported" marker.
        real_total = sum(1 for e in efforts if not _eh.is_discovered(e))
        real_seen = 0
        for idx, eff in enumerate(efforts):
            jid = eff.get("job_id", "")
            job = jobs_by_id.get(jid, {})
            discovered = _eh.is_discovered(eff)
            status = job.get("status") or eff.get("status") or ""
            gate_state = job.get("state")
            pill_cls, pill_lbl, is_live, needs_input = _effort_pill(
                status, gate_state)
            if discovered:
                # No vN; an "imported" marker instead. Discovered records are
                # never live and never link to a report viewer route.
                ver = ""
                is_live = needs_input = False
                pill_cls, pill_lbl = "", ""
            else:
                # Newest real effort = v<real_total>, descending by recency.
                real_seen += 1
                ver = f"v{real_total - real_seen + 1}" if real_total else "v1"
            skill = eff.get("skill") or job.get("skill") or ""
            seed = eff.get("prompt_seed") or ""
            hint = seed.strip().splitlines()[0] if seed.strip() else ""
            sub = " · ".join(p for p in (skill, hint) if p)
            # A manual/promoted Grass Catchers idea (Wave 5) carries its text as
            # the title; surface it so the card body shows the idea, not a blank.
            if not discovered and eff.get("kind") == "idea":
                idea_text = (eff.get("title") or "").strip()
                if idea_text:
                    sub = idea_text
            cost = (eff.get("cost") or {})
            cost_usd = float(cost.get("total_cost_usd", 0.0) or 0.0)
            views.append({
                "job_id": jid,
                "trio_lane": trio_lane,
                "ver": ver,
                "status": status,
                "pill_cls": pill_cls,
                "pill_lbl": pill_lbl,
                "is_live": is_live,
                "needs_input": needs_input,
                "is_done": (not discovered) and status == _jr.STATUS_DONE,
                "age": _fmt_age(eff.get("created_at")),
                "skill": skill,
                "sub": sub,
                "cost_usd": 0.0 if discovered else cost_usd,
                "discovered": discovered,
                "artifact_path": eff.get("artifact_path", "") if discovered else "",
                "title": eff.get("title", "") if discovered else "",
                "kind": eff.get("kind", "") if discovered else "",
                # real epoch for the Layout-D newest-first cross-lane merge (v12 W2,
                # Reviewer F1): without this the plan/build merge had no recency key
                # and demoted the newest build under an older plan.
                "_eff_created_at": float(eff.get("created_at") or 0.0),
            })
        out[trio_lane] = views
    return out


def _render_effort_card(ev, store_lane, project_id):
    """Render ONE effort card. Done efforts link to the report viewer; live ones
    carry the data hooks the console uses to attach. Every dynamic field is
    HTML-escaped (XSS-safe)."""
    jid = ev["job_id"]
    jid_esc = html_lib.escape(jid, quote=True)
    ver = html_lib.escape(ev["ver"])
    age = html_lib.escape(ev["age"])
    sub = html_lib.escape(ev["sub"]) if ev["sub"] else ""

    # ── Discovered (brownfield-imported) card: subtle, honest, no vN ──────────
    # It carries data-discovered="1" + a small dot + an "imported" marker, and
    # links to the REAL on-disk file via /artifact/<pid>?path=<rel>. It is NEVER
    # masqueraded as an Anchor-run session (no vN, no cost, no live hooks).
    if ev.get("discovered"):
        rel = ev.get("artifact_path", "")
        title = ev.get("title", "") or rel
        kind = ev.get("kind", "")
        title_esc = html_lib.escape(title)
        kind_esc = html_lib.escape(kind)
        data = (
            f" data-job-id=\"{jid_esc}\""
            f" data-lane=\"{html_lib.escape(store_lane, quote=True)}\""
            f" data-trio-lane=\"{html_lib.escape(ev['trio_lane'], quote=True)}\""
            f" data-discovered=\"1\" data-live=\"0\""
            f" data-artifact-path=\"{html_lib.escape(rel, quote=True)}\""
        )
        marker = ("<span class='imported'><span class='dotdisc'></span>"
                  "imported</span>")
        inner = (
            f"<div class='er'>{marker}"
            f"<span class='age'>{age}</span></div>"
            f"<div class='sub'>{title_esc}"
            + (f" <span class='dkind'>{kind_esc}</span>" if kind_esc else "")
            + "</div>"
        )
        if rel:
            href = (f"/artifact/{html_lib.escape(project_id, quote=True)}"
                    f"?path={url_quote(rel, safe='')}")
            return (f"<div class='effort discovered'{data} "
                    f"onclick=\"openReport('{html_lib.escape(href, quote=True)}')\">"
                    f"{inner}</div>")
        return f"<div class='effort discovered'{data}>{inner}</div>"

    pill = ""
    if ev["pill_cls"]:
        dot = ""
        if ev["pill_cls"] == "run":
            dot = "<span class='dotpulse'></span>"
        elif ev["pill_cls"] == "input":
            dot = "<span class='dotwarn'></span>"
        pill = (f"<span class='statepill {ev['pill_cls']}'>{dot}"
                f"{html_lib.escape(ev['pill_lbl'])}</span>")
    cost_bit = ""
    if ev["cost_usd"] > 0:
        cost_bit = (f"<span class='ecost'>${ev['cost_usd']:.4f}</span>")
    # Classes + data hooks. A live/needs-input card is clickable to attach the
    # console; a done card links to its report.
    cls = "effort"
    data = (f" data-job-id=\"{jid_esc}\" data-lane=\"{html_lib.escape(store_lane, quote=True)}\""
            f" data-trio-lane=\"{html_lib.escape(ev['trio_lane'], quote=True)}\""
            f" data-ver=\"{ver}\" data-live=\"{'1' if ev['is_live'] else '0'}\"")
    inner = (
        f"<div class='er'><span class='ver'>{ver}</span>{pill}"
        f"<span class='age'>{age}</span></div>"
        + (f"<div class='sub'>{sub}{cost_bit}</div>" if (sub or cost_bit) else "")
    )
    if ev["is_done"] and jid:
        # Link a done effort to the report viewer route.
        href = (f"/report/{html_lib.escape(project_id, quote=True)}/"
                f"{html_lib.escape(ev['trio_lane'], quote=True)}/{jid_esc}")
        return (f"<div class='{cls}'{data} onclick=\"openReport('{href}')\">"
                f"{inner}</div>")
    if ev["is_live"] and jid:
        return (f"<div class='{cls}' id='effort_{jid_esc}'{data} "
                f"onclick=\"attachSession('{jid_esc}')\">{inner}</div>")
    return f"<div class='{cls}'{data}>{inner}</div>"


# v7 Wave 3 — bridge LIVE managed sessions (session_registry) into the board.
#
# The board's trio columns are keyed by the trio-lane values in _KANBAN_COLUMNS
# (research / plan / build / deliverables / grass). A registry record's ``lane``
# may use the store form (``planning``) or the trio form (``plan``); both map to
# the ``plan`` board column. ``general`` now maps to its OWN board column (a
# bare-terminal zone); ``grass``/``grass-dev`` remain EXCLUDED (workbench-only).
_REGISTRY_LANE_TO_COLUMN = {
    "research": "research",
    "plan": "plan",
    "planning": "plan",
    "build": "build",
    "deliverables": "deliverables",
    # General sessions now get a board zone (a bare-terminal lane, rendered as its
    # own Layout-D column). grass/grass-dev are still excluded (workbench-only).
    "general": "general",
}

# ── v12 Wave 1: effort board-routing accessor ───────────────────────────────
#
# Layout-D routes an effort to a zone by ``current_stage``/``kind`` ONLY (the
# record's ``lane`` flips with the stage, so it must NOT be the routing key —
# Skeptic SK-8). A trio effort in research → the Research zone; in plan/build →
# the Plan/Build zone; a general/grass-dev effort → no trio zone.
#
# RENDER UNCHANGED this wave (the 5-col board still renders); this accessor is
# added + unit-tested only. Its live render consumer arrives in W10.
_EFFORT_ZONE_RESEARCH = "Research"
_EFFORT_ZONE_PLAN_BUILD = "Plan/Build"


def _effort_zone(record):
    """Return the Layout-D board zone for an effort record (v12 Wave 1).

    Routes by ``current_stage``/``kind`` only (never ``lane``, which flips):

    - ``current_stage == "research"`` → :data:`_EFFORT_ZONE_RESEARCH`.
    - ``current_stage in {"plan", "build"}`` → :data:`_EFFORT_ZONE_PLAN_BUILD`.
    - ``kind in {"general", "grass-dev"}`` → ``None`` (never a trio zone).
    - anything else → ``None``.

    ``record`` is a normalized session record (dict). Pure / read-only.
    """
    if not isinstance(record, dict):
        return None
    kind = (record.get("kind") or "").strip()
    if kind in ("general", "grass-dev"):
        return None
    stage = (record.get("current_stage") or "").strip()
    if stage == "research":
        return _EFFORT_ZONE_RESEARCH
    if stage in ("plan", "build"):
        return _EFFORT_ZONE_PLAN_BUILD
    return None


#: session_registry status → the locked light-color bucket (mirrors
#: :func:`_session_light_class`; running=green, needs-attention=amber,
#: done=amber, failed=red, idle/unknown=grey).
_REG_STATUS_LIGHT = {
    _sessreg.STATUS_RUNNING: "green",
    _sessreg.STATUS_NEEDS_ATTENTION: "amber",
    _sessreg.STATUS_DONE: "amber",
    _sessreg.STATUS_FAILED: "red",
    _sessreg.STATUS_IDLE: "grey",
    # Wave 5: the split of the overloaded idle — both render grey (parked-warm is
    # a reopenable tile like idle; a reaped orphan is a spent grey tile).
    _sessreg.STATUS_PARKED_WARM: "grey",
    _sessreg.STATUS_REAPED_ORPHAN: "grey",
}


def _registry_session_view(rec):
    """Build a single board ``effort_view``-shaped dict from a LIVE managed
    session record (``session_registry``), so a started session can render as a
    lane tile BEFORE it has any effort-history rows (v7 Wave 3).

    SAFE: reads only the projection-safe fields (session_id, lane, status,
    label, created_at) — NEVER ``worktree_path`` / ``branch`` (those must not
    leak into the page). The shape carries the same keys ``_render_lane_tile`` /
    ``_session_state_text`` / ``_session_light_class`` read off a representative
    effort view, plus the registry ``status`` and a ``from_registry`` marker so
    the merge can keep the live status when deduping against an effort view.
    """
    status = (rec.get("status") or "").strip()
    is_live = status == _sessreg.STATUS_RUNNING
    needs_input = status == _sessreg.STATUS_NEEDS_ATTENTION
    is_done = status in _sessreg.TERMINAL_STATUSES
    if status == _sessreg.STATUS_RUNNING:
        pill_cls, pill_lbl = "run", "running"
    elif status == _sessreg.STATUS_NEEDS_ATTENTION:
        pill_cls, pill_lbl = "input", "needs input"
    elif status == _sessreg.STATUS_DONE:
        pill_cls, pill_lbl = "done", "done"
    elif status == _sessreg.STATUS_FAILED:
        pill_cls, pill_lbl = "fail", "failed"
    elif status == _sessreg.STATUS_PARKED_WARM:
        # Wave 5: a parked-warm session is the reopenable grey tile the pre-split
        # STATUS_IDLE produced — keep the same "idle" pill so a migrated record
        # renders identically.
        pill_cls, pill_lbl = "", "idle"
    else:
        pill_cls, pill_lbl = "", (status or "idle")
    label = (rec.get("label") or "").strip()
    return {
        "job_id": "",
        "trio_lane": _REGISTRY_LANE_TO_COLUMN.get(
            (rec.get("lane") or "").strip(), ""),
        "ver": "",
        "status": status,
        "pill_cls": pill_cls,
        "pill_lbl": pill_lbl,
        "is_live": is_live,
        "needs_input": needs_input,
        "is_done": is_done,
        "age": _fmt_age(rec.get("created_at")),
        "skill": "",
        "sub": label,
        "cost_usd": 0.0,
        "discovered": False,
        "artifact_path": "",
        "title": label,
        "kind": "",
        # v10 Wave 4: grass→project lineage stamp. Just an idea id — SAFE (never
        # worktree_path/branch). Lets a board tile show the "from grass: <idea>"
        # back-link chip when this session's chain traces back to a grass idea.
        "grass_origin": (rec.get("grass_origin") or ""),
        # v12 W7: the effort_managed discriminator on the rep, so a board tile can
        # emit data-effort-managed and the JS advance-bar guard goes live for the
        # historical/synth path too (W7-R2-01). SAFE (a bool).
        "effort_managed": bool(rec.get("effort_managed", False)),
        # v7 Wave 3 merge markers (consumed only by _gather_project_sessions):
        "from_registry": True,
        "_reg_session_id": rec.get("session_id") or "",
        "_reg_created_at": rec.get("created_at") or 0.0,
        "_reg_status": status,
        "_reg_light": _REG_STATUS_LIGHT.get(status, "grey"),
    }


def _strip_session_prefix(sid: str) -> str:
    """Strip the effort session_id namespacing prefix (``run::`` / ``loose::`` /
    ``discovered::`` …) to recover the bare id, for cross-form dedupe with a
    managed registry session id (v7 Wave 3)."""
    s = str(sid or "")
    idx = s.find("::")
    return s[idx + 2:] if idx >= 0 else s


def _merge_registry_sessions(session_views, trio_lane, reg_by_column):
    """Merge the LIVE managed sessions for ``trio_lane`` into the effort-derived
    ``session_views`` (v7 Wave 3), deduped by session_id and ordered newest-first.

    - A registry session whose id ALREADY appears as an effort session keeps the
      richer effort view but adopts the LIVE registry status (so a just-started
      run shows running even before its effort rows land).
    - A registry session with no effort counterpart becomes a synthetic
      single-member session_view.
    - Ordered newest-first by created_at (registry ``created_at`` for synthetic
      rows; the effort rep's already-newest order is preserved by sort-stability).

    Returns the merged, newest-first list. ``general`` / ``grass`` never reach
    here (not in ``_REGISTRY_LANE_TO_COLUMN`` values for the trio columns).
    """
    reg_rows = reg_by_column.get(trio_lane, [])
    if not reg_rows:
        return session_views
    # Index existing effort session_views by id for dedupe + live-status adoption.
    # An effort session derived from a run job is keyed ``run::<job_id>`` (and a
    # defensive loose view ``loose::<job_id>``), while a managed registry session
    # is keyed by the BARE session id — which equals that job_id when the session
    # was adopted (terminal_session reuses the pty/session id as the job id). So
    # we index BOTH the full key AND the prefix-stripped tail to dedupe across
    # those two forms.
    by_sid = {}
    for sv in session_views:
        sid = sv.get("session_id") or ""
        by_sid.setdefault(sid, sv)
        tail = _strip_session_prefix(sid)
        if tail and tail != sid:
            by_sid.setdefault(tail, sv)
    merged = list(session_views)
    # Stamp created_at onto each existing view for the newest-first sort (the
    # rep member carries the effort age, not an epoch; fall back to 0 → sorts
    # after timestamped registry rows of equal recency, which is fine).
    order = {id(sv): i for i, sv in enumerate(merged)}
    sort_ts = {id(sv): _sv_created_at(sv) for sv in merged}
    for rv in reg_rows:
        sid = rv.get("_reg_session_id") or ""
        existing = by_sid.get(sid)
        if existing is not None:
            # DEDUPE: keep the richer effort view, adopt the live registry status
            # onto its representative member so the tile light/state is current.
            rep = (existing.get("members") or [None])[0]
            if isinstance(rep, dict):
                rep["is_live"] = rv["is_live"]
                rep["needs_input"] = rv["needs_input"]
                rep["is_done"] = rep.get("is_done") or rv["is_done"]
                if rv["status"]:
                    rep["status"] = rv["status"]
                rep["pill_cls"] = rv["pill_cls"]
                rep["pill_lbl"] = rv["pill_lbl"]
            sort_ts[id(existing)] = max(
                sort_ts.get(id(existing), 0.0), rv.get("_reg_created_at") or 0.0)
            continue
        sv = {"session_id": sid, "members": [rv]}
        merged.append(sv)
        by_sid[sid] = sv
        order[id(sv)] = len(order)
        sort_ts[id(sv)] = rv.get("_reg_created_at") or 0.0
    # Newest-first by created_at; stable on ties (preserves original ordering).
    merged.sort(key=lambda sv: (-(sort_ts.get(id(sv), 0.0)), order.get(id(sv), 0)))
    return merged


def _sv_created_at(sv):
    """Best-effort epoch created_at for a session_view (for the merge sort).

    A registry-sourced view carries ``_reg_created_at``; an effort view carries
    ``_eff_created_at`` (the effort record's real epoch, v12 W2). Either gives a
    true recency key for the newest-first / cross-lane merge; 0.0 only if neither."""
    rep = (sv.get("members") or [None])[0]
    if isinstance(rep, dict):
        ts = rep.get("_reg_created_at") or rep.get("_eff_created_at")
        if ts:
            return float(ts or 0.0)
    return 0.0


def _gather_project_sessions(folder_path, project_id, efforts_by_lane=None):
    """Group each lane's effort views into SESSIONS (v2 Wave 4, MASTER-PLAN §A).

    Wraps :func:`sessions.list_sessions` (Wave 1) — one trio run = one session —
    and joins each session to the per-effort views produced by
    :func:`_gather_project_efforts`. Returns ``{trio_lane: [session_view, ...]}``
    newest-first, where a ``session_view`` is::

        {"session_id", "members": [effort_view, ...]}

    ``members`` are the session's effort views, newest-first (the representative
    card = ``members[0]``). Member views not found (defensive) are skipped.
    """
    if efforts_by_lane is None:
        efforts_by_lane = _gather_project_efforts(folder_path, project_id)
    # v7 Wave 3 — pull the project's LIVE managed sessions ONCE and bucket them
    # by board column (research/plan/build/deliverables). ``general``/``grass``
    # are excluded (not in _REGISTRY_LANE_TO_COLUMN). Registry-only (no model
    # call); never leaks worktree_path/branch (see _registry_session_view).
    reg_by_column = {}
    try:
        for rec in _sessreg.list_sessions(project_id=project_id):
            # v8 Wave 6: a CONTAINED grass-workbench develop session keeps its
            # research/plan lane (so its trio skill seeds) but must NOT render as
            # a board tile — it lives only in the workbench pane. Its label marker
            # excludes it here (and the JS never adds it to MANAGED/the top strip).
            if _eh.is_grass_dev_label(rec.get("label")):
                continue
            col = _REGISTRY_LANE_TO_COLUMN.get((rec.get("lane") or "").strip())
            if not col:
                continue
            reg_by_column.setdefault(col, []).append(_registry_session_view(rec))
    except Exception:
        reg_by_column = {}
    out = {}
    for trio_lane, _subdir, _label, _glyph, _addlabel in _KANBAN_COLUMNS:
        views = efforts_by_lane.get(trio_lane, [])
        # Index this lane's effort views by job_id for the session→view join.
        by_jid = {}
        for v in views:
            jid = v.get("job_id") or ""
            by_jid.setdefault(jid, v)
        try:
            sess_list = _sessions.list_sessions(folder_path, project_id, trio_lane)
        except Exception:
            sess_list = []
        session_views = []
        claimed = set()
        for s in sess_list:
            members = []
            for m in s.get("member_files", []):
                jid = (m.get("job_id") or "").strip()
                v = by_jid.get(jid)
                if v is not None:
                    members.append(v)
                    claimed.add(jid)
            if not members:
                continue
            # Keep members newest-first (the effort views already arrive
            # newest-first from list_efforts; preserve that ordering).
            session_views.append({
                "session_id": s.get("session_id", ""),
                "members": members,
            })
        # Defensive: surface any effort view not claimed by a session as its own
        # single-member session so nothing silently disappears from the board.
        for v in views:
            jid = v.get("job_id") or ""
            if jid not in claimed:
                claimed.add(jid)
                session_views.append({
                    "session_id": f"loose::{jid}",
                    "members": [v],
                })
        # v7 Wave 3 — bridge in the LIVE managed sessions for this column,
        # deduped by session_id + ordered newest-first (the most-recent becomes
        # the prominent tile, older ones the expander).
        session_views = _merge_registry_sessions(
            session_views, trio_lane, reg_by_column)
        out[trio_lane] = session_views
    # Build→Planning tie: a BUILD session whose source directory equals a PLANNING
    # session's source directory (the Foreman EXECUTION-LOG lives under
    # planning/<version>/ next to the plan docs) is the SAME trio run's build
    # stage — tie them so the build tile can link back to the plan it executed.
    # Honest: only an unambiguous (single-planning-session-per-dir) match links;
    # no match → no link (nothing fabricated). Discovered/effort sessions only —
    # live managed sessions carry their own v6 parent/chain lineage.
    _attach_build_planning_tie(out)
    return out


def _gather_efforts(project_id):
    """Return the project's EFFORT view (v12 Wave 9) for the render layer.

    Thin accessor over :func:`effort_view.build_effort_view` — groups the
    project's registry chains AND new single-session efforts into one uniform
    list of efforts (one per chain, deduped against the migration overlap, no
    ghost stage for a deleted member), REBUILT from the registry on every call.
    Consumed by the W10/W11 render layer. The legacy
    :func:`_gather_project_sessions` is RETAINED as the fallback (not removed).

    Resolves the project's folder from the registry; honest ``[]`` for an unknown
    project or any failure (never raises — best-effort, like the legacy gather).
    """
    try:
        entry = _rnd.get_project(project_id)
    except Exception:
        entry = None
    folder_path = (entry or {}).get("folder_path", "") if entry else ""
    try:
        return _effview.build_effort_view(folder_path, project_id)
    except Exception:
        return []


def _sv_source_dir(sv) -> str:
    """The folder-relative POSIX source directory of a discovered session view,
    from its representative member's ``artifact_path`` (``""`` if none/loose)."""
    for m in sv.get("members", []) or []:
        ap = (m.get("artifact_path") or "").strip().replace("\\", "/")
        if ap and "/" in ap:
            return ap.rsplit("/", 1)[0]
    return ""


def _attach_build_planning_tie(out) -> None:
    """Attach ``linked_planning`` = ``{"session_id", "label"}`` to each BUILD
    session that shares a source directory with exactly one PLANNING session.

    Mutates ``out`` in place. The planning ``session_id`` is the real
    (un-qualified) ``dir::…`` id whose tile lives in the Planning column, so a
    chip/breadcrumb click resolves to that tile via ``openPanel``. ``label`` is
    the version dir basename (e.g. ``rnd-v4``).
    """
    planning_by_dir = {}        # source_dir -> session_id (None marks ambiguous)
    # NB: the planning column's key in ``out`` is the trio-lane "plan" (its
    # store-lane is "planning"); see _KANBAN_COLUMNS.
    for sv in out.get("plan", []) or []:
        d = _sv_source_dir(sv)
        if not d:
            continue
        sid = sv.get("session_id") or ""
        if not sid:
            continue
        planning_by_dir[d] = None if d in planning_by_dir else sid
    for sv in out.get("build", []) or []:
        d = _sv_source_dir(sv)
        if not d:
            continue
        sid = planning_by_dir.get(d)
        if not sid:
            continue   # no match, or ambiguous (>1 planning session in that dir)
        label = d.rsplit("/", 1)[-1] or d
        sv["linked_planning"] = {"session_id": sid, "label": label}


def _idea_source_label(eff) -> str:
    """Human source chip for a grass idea: 'from inbox' | 'discovered' | 'manual'.

    Reads the effort record (NOT the trimmed view) so it can see the honest
    provenance markers ``promoted_from`` / discovered / manual-add.
    """
    if _eh.is_discovered(eff):
        return "discovered"
    if (eff.get("promoted_from") or "") == "inbox":
        return "from inbox"
    return "manual"


#: Human label for a grass idea's lifecycle status (used by the workbench chips).
_GRASS_STATUS_LABEL = {
    _eh.GRASS_RAW: "raw",
    _eh.GRASS_REFINED: "refined",
    _eh.GRASS_PROMOTED: "promoted",
}


# v10 Wave 7 — Boneyard: human label for each locked source (D3).
_BONEYARD_SOURCE_LABEL = {
    _boneyard.SOURCE_KILLED: "killed",
    _boneyard.SOURCE_DELETED: "deleted",
    _boneyard.SOURCE_GRASS_DELETED: "grass-deleted",
}


def _boneyard_entry_view(project_id, entry) -> dict:
    """SAFE projection of a Boneyard entry + server-built traversal-safe doc links.

    The entry comes from ``boneyard.list_entries`` / ``boneyard.search``, already a
    SAFE projection (only the public ``_SAFE_KEYS`` — never an absolute path /
    worktree / branch). We add ``doc_links`` (``[{name, href}]``) by routing EVERY
    ``doc_rel`` through the existing traversal-safe ``/artifact?path=<rel>`` route
    (W7 routing decision: the produced docs survive on disk by their main-folder
    rel path under Option A regardless of source — killed/deleted/grass-deleted —
    so /artifact is ALWAYS resolvable and consistent; no fragile /report job_id
    resolution from a content-addressed effort id). The href is path+query escaped;
    the route itself rejects ``..``/absolute/symlink-escape. No absolute path /
    worktree / branch is ever emitted.
    """
    e = entry or {}
    pid_q = url_quote(str(project_id), safe="")
    links = []
    for rel in (e.get("doc_rels", []) or []):
        rel = str(rel or "").strip()
        if not rel:
            continue
        name = rel.replace("\\", "/").rsplit("/", 1)[-1] or rel
        href = f"/artifact/{pid_q}?path={url_quote(rel, safe='')}"
        links.append({"name": name, "href": href})
    # ``when_display`` is the formatted, LOCAL-tz timestamp string computed ONCE on
    # the server (v10 Wave 7 fix). BOTH the server initial render
    # (_render_boneyard_entry_html) AND the client live-search render
    # (_boneyardEntryHtml) use it verbatim, so the displayed time is byte-identical
    # across the initial paint and a post-search re-render (the client used to
    # re-format ``when`` in UTC, causing a ~tz-offset jump on the first search).
    # ``when`` (raw epoch) is kept too for any ordering/raw use. SAFE: a formatted
    # string only — no path / worktree / branch.
    when_raw = e.get("when", 0)
    when_display = ""
    try:
        if when_raw:
            when_display = datetime.fromtimestamp(
                float(when_raw)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        when_display = ""
    return {
        "entry_id": e.get("entry_id", ""),
        "source": e.get("source", ""),
        "source_label": _BONEYARD_SOURCE_LABEL.get(e.get("source", ""),
                                                   e.get("source", "")),
        "session_id": e.get("session_id", ""),
        "lane": e.get("lane", ""),
        "title": e.get("title", ""),
        "summary_excerpt": e.get("summary_excerpt", ""),
        "idea_text": e.get("idea_text", ""),
        "when": when_raw,
        "when_display": when_display,
        "doc_links": links,
    }


def _render_boneyard_entry_html(view) -> str:
    """Render ONE Boneyard entry as a ``.byentry`` (collapsed; expands to summary +
    doc links). All engine/user content HTML-escaped. ``view`` is the
    ``_boneyard_entry_view`` shape (SAFE projection + ``doc_links``)."""
    src = view.get("source", "")
    src_lbl = html_lib.escape(view.get("source_label", src) or src)
    src_cls = html_lib.escape(src, quote=True)
    # RAW title escaped EXACTLY ONCE (quote-safe). ``title`` here is the escaped
    # string reused below; we must NOT re-escape it (the v10-W7 double-escape bug
    # turned ``A & B`` into ``A &amp;amp; B`` because the already-escaped value was
    # passed back through html.escape on the data-title attribute).
    title_raw = view.get("title", "") or "(untitled)"
    title = html_lib.escape(title_raw, quote=True)
    lane = (view.get("lane", "") or "").strip()
    lane_chip = (f"<span class='bylanechip'>{html_lib.escape(lane)}</span>"
                 if lane else "")
    # The displayed timestamp is the server-computed, LOCAL-tz ``when_display`` from
    # the SAFE projection — the SAME string the client live-search render uses, so
    # the initial paint and a post-search re-render are byte-identical (no tz jump).
    when_txt = view.get("when_display", "") or ""
    when_chip = (f"<span class='bywhen'>{html_lib.escape(when_txt)}</span>"
                 if when_txt else "")
    # The expand body: full summary/idea text + doc links.
    summary = (view.get("summary_excerpt", "") or "").strip()
    idea = (view.get("idea_text", "") or "").strip()
    body_text = summary or idea
    if body_text:
        sum_html = (f"<div class='bysum'>{html_lib.escape(body_text)}</div>")
    else:
        sum_html = ("<div class='bysum dim'>No summary captured.</div>")
    # A short collapsed excerpt (the first line of whatever body we have).
    excerpt = body_text.splitlines()[0] if body_text else ""
    exc_html = (f"<div class='byexc'>{html_lib.escape(excerpt)}</div>"
                if excerpt else "")
    links = view.get("doc_links", []) or []
    if links:
        rows = "".join(
            f"<a class='bydoc' href='{html_lib.escape(l['href'], quote=True)}' "
            f"target='anchor_report_window' rel='noopener'>"
            f"{html_lib.escape(l['name'])}</a>"
            for l in links)
        docs_html = (f"<div class='bydocs'><div class='h'>Documents</div>"
                     f"{rows}</div>")
    else:
        docs_html = ("<div class='bydocs'><div class='h'>Documents</div>"
                     "<span class='none'>No documents.</span></div>")
    eid = html_lib.escape(view.get("entry_id", ""), quote=True)
    return (
        f"<div class='byentry' data-byentry=\"{eid}\" data-source='{src_cls}' "
        f"data-title=\"{title}\" "
        f"onclick='toggleBoneyardEntry(this)'>"
        f"<div class='byhd'>"
        f"<span class='bybadge {src_cls}'>{src_lbl}</span>"
        f"<div class='bymeta'><div class='bytitle'>{title}</div>{exc_html}</div>"
        f"{lane_chip}{when_chip}<span class='bycar'>&#9656;</span>"
        f"</div>"
        f"<div class='bybody' onclick='event.stopPropagation()'>"
        f"{sum_html}{docs_html}"
        f"</div>"
        f"</div>"
    )


def _render_boneyard_panel(project_id) -> str:
    """Render the Boneyard panel template (hidden; cloned into ``#panelStack`` by
    ``openBoneyard()``): a search box over a newest-first entry list. The initial
    entries are server-rendered (so the DOM positive/negative assertions are real);
    live search re-fetches ``/api/rnd/boneyard?q=`` and re-renders the list. An
    honest empty state when the project has no discarded material."""
    entry = _rnd.get_project(project_id)
    folder = (entry or {}).get("folder_path", "")
    try:
        raw = _boneyard.list_entries(folder, project_id)
    except Exception:
        raw = []
    views = [_boneyard_entry_view(project_id, e) for e in raw]
    if views:
        rows = "".join(_render_boneyard_entry_html(v) for v in views)
        list_html = rows
    else:
        # Honest empty state — NO fabricated entries (Wave-7 negative).
        list_html = ("<div class='byempty' data-byempty='1'>"
                     "Nothing discarded yet. Killed sessions with material, "
                     "deleted sessions, and deleted grass ideas land here.</div>")
    return (
        "<div class='boneyard' id='boneyardView'>"
        "<div class='bytop'>"
        "<span class='ic'>&#9760;</span>"
        "<span class='lbl'>Discarded material</span>"
        "<span class='sp'></span>"
        "<input class='bysearch' id='boneyardSearch' type='search' "
        "placeholder='search discarded&hellip;' oninput='searchBoneyard()'>"
        "</div>"
        f"<div class='bylist' id='boneyardList'>{list_html}</div>"
        "</div>"
    )


def _render_grass_column_tile(folder_path, project_id) -> str:
    """Render the Grass LANE column content: a single tile that OPENS the
    full-width two-pane idea workbench panel (v5 Wave 5).

    The 5-column cockpit board's Grass column is too narrow for the B+C hybrid
    two-pane workbench, so the column shows one clickable tile (idea count +
    status mix) whose click (``openGrassWorkbench()``) expands the workbench panel
    in ``#panelStack`` — exactly like a lane tile opens a session panel. The old
    single-column ``idea-board`` / ``idea-card`` markup is GONE.
    """
    try:
        ideas = _eh.grass_workbench_data(folder_path, project_id)
    except Exception:
        ideas = []
    n = len(ideas)
    n_raw = sum(1 for i in ideas if i["status"] == _eh.GRASS_RAW)
    n_ref = sum(1 for i in ideas if i["status"] == _eh.GRASS_REFINED)
    n_pro = sum(1 for i in ideas if i["status"] == _eh.GRASS_PROMOTED)
    light = "green" if n_ref else ("amber" if n_raw else "grey")
    sub = (f"{n_raw} raw · {n_ref} refined · {n_pro} promoted"
           if n else "no ideas yet")
    return (
        f"<div class='tile lane-tile grass-tile' data-grass-tile='1' "
        f"data-light='{light}' onclick='openGrassWorkbench()'>"
        f"<div class='tr1'><span class='lane'>ideas</span>"
        f"<span class='ver'></span>"
        f"<span class='lt {light}' aria-hidden='true'></span></div>"
        f"<div class='ttl'>Idea workbench</div>"
        f"<div class='st'><span class='state done'>{html_lib.escape(sub)}</span>"
        f"<span class='age'>· {n} idea{'s' if n != 1 else ''}</span></div>"
        f"</div>"
    )


def _render_grass_idea_li(idea) -> str:
    """Render one idea as a ``.gli`` row for the workbench LEFT list (mockup C)."""
    status = idea["status"]
    cls_extra = (" r" if status == _eh.GRASS_REFINED
                 else (" p" if status == _eh.GRASS_PROMOTED else ""))
    title = html_lib.escape(idea["title"] or "(untitled idea)")
    short = html_lib.escape(idea["short_id"])
    idea_attr = html_lib.escape(idea["idea_id"], quote=True)
    st_lbl = html_lib.escape(_GRASS_STATUS_LABEL.get(status, status))
    src = html_lib.escape(idea["source"])
    return (
        f"<div class='gli{cls_extra}' data-idea=\"{idea_attr}\" "
        f"data-status='{html_lib.escape(status)}' "
        f"data-title=\"{html_lib.escape(idea['title'], quote=True)}\">"
        f"<div class='t'>{title}</div>"
        f"<div class='m'><span class='dot'></span>"
        f"<span class='idchip'>{short}</span>"
        f"<span class='stchip {html_lib.escape(status)}'>{st_lbl}</span>"
        f"<span class='srcchip'>{src}</span>"
        # v9 Wave 2 — a red ✕ DELETE control on the idea row. event.stopPropagation
        # so clicking ✕ does NOT also select the idea; deleteGrassIdea is
        # confirm()-gated then POSTs grass_delete {confirm:true}.
        f"<span class='gli-del' title='Delete this idea' "
        f"onclick=\"event.stopPropagation();deleteGrassIdea('{idea_attr}')\">"
        f"&#10005;</span>"
        f"</div></div>"
    )


def _render_grass_workbench(folder_path, project_id) -> str:
    """Render the FULL B+C hybrid Grass workbench (the approved mockup), as a
    hidden template the panel manager clones into ``#panelStack`` (v5 Wave 5).

    Structure (matching ``_mockups/grass_catcher_refined.html``):
      - ``.gtabs`` filter-tab row: 🌿 · All/raw/refined/promoted (with counts) ·
        a ``.gsearch`` search box · ``+ Add idea`` / ``+ From inbox`` buttons.
      - ``.gwrap`` two-pane grid: ``.glist`` (filtered idea list, ``.gli`` rows
        with ``.idchip``/``.stchip``/``.srcchip``) · ``.gwork`` (the selected
        idea's workbench: title + id + status, ``.desc``, ``.devbar`` with
        Develop 🔬 Research / 📐 Plan + engine toggle + → Promote to a lane, a
        ``.gterms`` block of TWO independent, collapsible ``.gterm`` workbench
        terminals (v10 Wave 3 — one per lane: research, plan), and ``.ghist``
        refinement history with per-version pull buttons).

    The JS (``openGrassWorkbench`` / ``selectGrassIdea`` / ``filterGrass`` /
    ``toggleGrassTerminal`` / ``developGrass`` / ``pullGrass``) wires interactivity;
    this server render
    provides the data-bearing DOM (so the rendered-DOM assertions are real).
    """
    try:
        ideas = _eh.grass_workbench_data(folder_path, project_id)
    except Exception:
        ideas = []
    n = len(ideas)
    n_raw = sum(1 for i in ideas if i["status"] == _eh.GRASS_RAW)
    n_ref = sum(1 for i in ideas if i["status"] == _eh.GRASS_REFINED)
    n_pro = sum(1 for i in ideas if i["status"] == _eh.GRASS_PROMOTED)
    tabs = (
        "<div class='gtabs'>"
        "<span class='ic'>&#127807;</span>"
        f"<span class='gtab on' data-filter='all'>All <span class='n'>{n}</span></span>"
        f"<span class='gtab' data-filter='raw'>raw <span class='n'>{n_raw}</span></span>"
        f"<span class='gtab' data-filter='refined'>refined "
        f"<span class='n'>{n_ref}</span></span>"
        f"<span class='gtab' data-filter='promoted'>promoted "
        f"<span class='n'>{n_pro}</span></span>"
        "<span class='sp'></span>"
        "<input class='gsearch' type='search' placeholder='search ideas&hellip;' "
        "oninput='filterGrass()'>"
        "<button class='mini' onclick='addIdea()'>+ Add idea</button>"
        "<button class='mini' onclick='promoteInbox()'>+ From inbox</button>"
        "</div>"
    )
    if ideas:
        lis = "".join(_render_grass_idea_li(i) for i in ideas)
        list_html = (
            f"<div class='glist'>{lis}"
            "<div class='gadd'><button class='mini' style='width:100%' "
            "onclick='addIdea()'>+ Add idea</button></div></div>"
        )
    else:
        list_html = (
            "<div class='glist'><div class='gli-empty'>No ideas yet — "
            "capture one with &ldquo;+ Add idea&rdquo;.</div>"
            "<div class='gadd'><button class='mini' style='width:100%' "
            "onclick='addIdea()'>+ Add idea</button></div></div>"
        )
    # The right workbench pane starts EMPTY (a "select an idea" hint); selecting
    # a .gli populates it client-side from the row's data + a fetch of /api/rnd/grass.
    work_html = (
        "<div class='gwork' data-empty='1'>"
        "<div class='gwork-empty'>Select an idea on the left to develop it.</div>"
        "</div>"
    )
    return (
        "<div class='grass-workbench' data-grass-workbench='1'>"
        f"{tabs}"
        f"<div class='gwrap'>{list_html}{work_html}</div>"
        "</div>"
    )


def _render_kanban_html(folder_path, project_id):
    """Render the Paradigm-2 lane board: 5 ``.p2col`` columns (Research|Planning|
    Build|Deliverables|Grass) inside a ``.p2lanes`` grid (v4.1 cockpit-render).

    Each content lane (research/plan/build) renders GENUINE Paradigm-2 ``.tile``
    cards — the MOST-RECENT session is the visible tile (status light + click-to-
    -openPanel hook); the remaining sessions sit behind a "previous sessions (N)"
    ``<details>`` expander, ALSO rendered as tiles (NOT effort cards, NO report
    links / summary accordions / file expanders — that detail lives in the opened
    panel). The Deliverables lane renders launch-by-type tiles; the Grass lane is
    the idea board. Each column has an ``<h4>`` header (glyph + label + a live/attn
    lane badge) and a "+ new <lane>" launcher.
    """
    efforts_by_lane = _gather_project_efforts(folder_path, project_id)
    sessions_by_lane = _gather_project_sessions(
        folder_path, project_id, efforts_by_lane)
    cols = []
    for trio_lane, store_lane, label, glyph, add_label in _KANBAN_COLUMNS:
        views = efforts_by_lane.get(trio_lane, [])
        session_views = sessions_by_lane.get(trio_lane, [])
        any_live = any(v["is_live"] and not v["needs_input"] for v in views)
        any_input = any(v["needs_input"] for v in views)
        # The lane header badge is a small status light (mockup: <span class="lt">
        # in the <h4>): amber when a session needs you, a pulsing green when one is
        # live, otherwise nothing.
        badge = ""
        if any_input:
            badge = "<span class='lt amber' title='needs you'></span>"
        elif any_live:
            badge = "<span class='lt green' title='running'></span>"
        if trio_lane == "grass":
            # v5 Wave 5: the grass lane column shows ONE tile that opens the
            # full-width two-pane B+C hybrid workbench panel (the column is too
            # narrow for the two-pane workbench). The old single-column idea-board
            # markup is gone; the workbench template is appended after the board.
            cards = _render_grass_column_tile(folder_path, project_id)
        elif trio_lane == "deliverables":
            # The deliverables lane is launch-by-type TILES (mockup Paradigm-2),
            # NOT session/effort cards: a tile per pinned deliverable whose click
            # launches it per its type contract.
            cards = _render_deliverable_lane_tiles(folder_path, project_id)
        else:
            cards = _render_lane_sessions(
                session_views, store_lane, project_id, trio_lane, folder_path)
        # The "+ new <lane>" launcher. All lanes launch on Claude by default
        # (the locked model policy: Claude is the default engine; the 5:1
        # Claude-orchestrates-Gemini split lives at the skill/session layer; and
        # Foreman/build code-writing is pinned to Claude). Gemini is reachable
        # only via the per-session engine toggle — never as a launch default.
        # deliverables are config-driven (no launch); grass gets manual add +
        # promote-from-INBOX.
        if trio_lane == "deliverables":
            add = ""
        elif trio_lane == "grass":
            add = (
                f"<span class='addnew' onclick=\"addIdea()\">"
                f"{html_lib.escape(add_label)}</span> "
                f"<span class='addnew' onclick=\"promoteInbox()\">"
                f"+ From inbox</span>"
            )
        elif trio_lane == "research":
            add = (
                "<span class='addnew' onclick=\"newTermSession('research','claude')\">"
                f"{html_lib.escape(add_label)}</span>"
            )
        else:
            add = (f"<span class='addnew' onclick=\"newTermSession('{trio_lane}')\">"
                   f"{html_lib.escape(add_label)}</span>")
        lane_attr = html_lib.escape(trio_lane, quote=True)
        cols.append(
            f"<div class='p2col' data-col-lane='{lane_attr}'>"
            f"<h4><span>{glyph}</span> {html_lib.escape(label)} "
            f"<span class='sp'></span>"
            f"<span class='badge' id='badge_{lane_attr}'>{badge}</span></h4>"
            f"<div class='col-tiles' id='cards_{lane_attr}'>{cards}</div>"
            f"{add}</div>"
        )
    board = "<div class='p2lanes'>" + "".join(cols) + "</div>"
    # v5 Wave 5: the full two-pane Grass workbench, rendered ONCE as a hidden
    # template the panel manager (openGrassWorkbench) clones into #panelStack.
    workbench = (
        "<div id='grassWorkbenchTpl' style='display:none'>"
        + _render_grass_workbench(folder_path, project_id)
        + "</div>"
    )
    return board + workbench


# ════════════════════════════════════════════════════════════════════════════
# v12 Wave 2 — Layout-D static skeleton ("ship the look early").
#
# Render the approved Layout-D shell per _mockups/dashboard_D_headline_shelf.html
# — a Latest-Research headline card + a collapsible older-research shelf, a
# Latest-Plan/Build headline card + its own shelf, a persistent right column
# (Grass mini-panel + Deliverables panel), a "+ New effort" control, and an
# INERT bottom dock chrome (summary-on-top + draggable splitter + terminal host,
# buttons disabled/labeled "wired in W10"). This wave is DRIVEN BY EXISTING DATA
# (`_gather_project_sessions`, already on master) via a thin adapter — the live
# effort-view (W9), the bottom-dock terminal/transport (W10), and the
# advance/handoff interactions are deliberately DEFERRED. The headline cards +
# little-tiles carry the legacy ``tile lane-tile`` + ``data-session`` hooks so
# the W10 panel-open wiring (and the existing panel-open tests) still bind.
# ════════════════════════════════════════════════════════════════════════════

def _layoutd_zones(folder_path, project_id, sessions_by_lane=None):
    """Map the EXISTING per-lane session views into the Layout-D headline/shelf
    shape (v12 Wave 2). Pure adapter over :func:`_gather_project_sessions` — no
    new data source, no model call.

    Returns ``{"research": [session_view, ...], "plan_build": [session_view, ...]}``
    newest-first, where the RESEARCH zone is the research column's sessions and
    the PLAN/BUILD zone is the plan + build columns' sessions merged newest-first.
    In each zone ``[0]`` is the headline (most-recent) and ``[1:]`` are the
    collapsible-shelf "little tiles". Each ``session_view`` is carried verbatim
    (``{"session_id", "members": [...], ...}``) so the existing tile helpers
    (:func:`_session_tile_title` / :func:`_session_light_class` /
    :func:`_session_state_text`) read it unchanged.
    """
    if sessions_by_lane is None:
        sessions_by_lane = _gather_project_sessions(folder_path, project_id)
    research = list(sessions_by_lane.get("research", []) or [])
    plan = list(sessions_by_lane.get("plan", []) or [])
    build = list(sessions_by_lane.get("build", []) or [])
    # Merge plan + build newest-first. Effort views don't carry an epoch on the
    # rep, so use the same best-effort created_at the merge sort uses, stable on
    # ties (build listed first → slightly newer-leaning, harmless for a skeleton).
    plan_build = sorted(
        plan + build, key=lambda sv: -_sv_created_at(sv))
    # General sessions (bare terminals) get their own zone: most-recent headline +
    # older-runs shelf, newest-first (registry created_at drives recency).
    general = sorted(
        list(sessions_by_lane.get("general", []) or []),
        key=lambda sv: -_sv_created_at(sv))
    return {"research": research, "plan_build": plan_build, "general": general}


def _layoutd_tie_chip(sv):
    """The build→planning tie (v3, preserved into Layout-D): ``(data_attr, chip)``
    for a build session view whose ``linked_planning`` was set by
    :func:`_attach_build_planning_tie`. Returns ``("", "")`` when none. The chip
    links back to the planning session this build executed on (same markup the v4
    lane tile emitted, so the tie tests + ``openLinkedPlanning`` still bind)."""
    tie = sv.get("linked_planning") or {}
    if not tie.get("session_id"):
        return "", ""
    lp_sid = html_lib.escape(tie["session_id"], quote=True)
    lp_lbl = html_lib.escape(tie.get("label") or "planning")
    lp_lbl_attr = html_lib.escape(tie.get("label") or "planning", quote=True)
    data = (f" data-linked-planning=\"{lp_sid}\""
            f" data-linked-planning-label=\"{lp_lbl_attr}\"")
    chip = (
        f"<span class='tiechip' title='Open the planning session this build "
        f"executed on' onclick=\"openLinkedPlanning(event,'{lp_sid}')\">"
        f"&#9741; Planning: {lp_lbl} &#9656;</span>")
    return data, chip


def _layoutd_grass_origin_chip(rep, trio_lane):
    """The board-tile "from grass: <idea>" lineage chip (v10 W4, preserved into
    Layout-D). Rendered for a plan/build tile whose representative session carries
    a ``grass_origin`` (the SAFE idea-id field). The label + dead-state are
    resolved client-side by ``_resolveGrassOriginChips``; here we emit the pending
    chip with ``data-grass-origin`` + ``data-grass-pending`` exactly as the v10
    lane tile did. ``""`` when none / not a plan-build lane."""
    if not isinstance(rep, dict):
        return ""
    origin = (rep.get("grass_origin") or "").strip()
    if not origin or trio_lane not in ("plan", "planning", "build"):
        return ""
    origin_attr = html_lib.escape(origin, quote=True)
    return (
        f"<span class='grassorigin' data-grass-origin=\"{origin_attr}\" "
        f"data-grass-pending=\"1\" "
        f"title='This work traces back to a grass idea — click to open it'>"
        f"&#127793; from grass</span>")


def _layoutd_resume_control(sv, rep, trio_lane):
    """The "Resume as session" control for a DISCOVERED/brownfield effort tile
    (crucible-improve #6 UI, W4). A discovered effort has no managed Anchor
    session — its tile otherwise only opens the on-disk artifact (read-only), so
    there is no way to *carry it on*. This control drives ``resumeDiscovered`` →
    ``continueSession`` → ``POST /api/rnd/continue_session``, whose
    :func:`_build_continue_seed` SYNTHESIZES a warm seed from the documents on disk
    for a discovered effort (W3 #6 backend — the detected phase, the trio skill,
    the enumerated doc list) before calling ``terminal_session.start_session``. So
    clicking it opens a WARM live session (skill loaded, docs read, oriented), not
    a cold terminal. Returns ``""`` for a non-discovered tile — those resume via
    the opened panel's "Continue in a live session" button instead.

    SAFE: emits only the ``session_id`` + the trio lane (never ``worktree_path`` /
    ``branch``). ``stopPropagation`` keeps the click off the tile's
    ``laneTileClick`` so it resumes rather than merely opening the read-only panel.
    """
    if not isinstance(rep, dict) or not rep.get("discovered"):
        return ""
    sid = (sv.get("session_id") or "") if isinstance(sv, dict) else ""
    if not sid:
        return ""
    sid_attr = html_lib.escape(sid, quote=True)
    lane_attr = html_lib.escape(trio_lane or "", quote=True)
    return (
        f"<button class='resume-disc' type='button' data-session=\"{sid_attr}\" "
        f"data-lane=\"{lane_attr}\" title='Resume this discovered effort as a warm "
        f"live session — the trio skill loads and the on-disk docs orient the turn' "
        f"onclick=\"resumeDiscovered(event,'{sid_attr}','{lane_attr}')\">"
        f"&#9654; Resume as session</button>")


#: trio-lane → the trio STAGE it represents (for the EV-2 stage-track fallback
#: when a tile has no live effort-view entry, e.g. a discovered/imported tile).
_LANE_TO_STAGE = {"research": "research", "plan": "plan", "planning": "plan",
                  "build": "build"}


def _effort_data_attrs(sid, effort_index, fallback_lane=""):
    """The v12 W10 effort-binding data-* attrs for a Layout-D tile.

    Resolves the session id to its EFFORT (via ``effort_index`` = session_id →
    effort dict, built from :func:`_gather_efforts`) and emits
    ``data-effort-id`` + ``data-current-stage`` so the bottom dock can open BOUND
    to the effort and light the 3-node stage track from ``current_stage`` (EV-2 —
    presence-based, NOT by iterating stage_history). When the index has no entry
    (a discovered/imported tile that never minted a managed session), it falls
    back to the session id as a singleton effort id and derives the stage from the
    tile's trio lane (``fallback_lane``) — honest, never blank for a real lane
    tile. Returns a leading-space attribute string ("" only if ``sid`` is empty).
    """
    if not sid:
        return ""
    eff = (effort_index or {}).get(sid)
    if eff:
        eid = (eff.get("effort_id") or sid)
        stage = (eff.get("current_stage") or "")
    else:
        eid = sid
        stage = ""
    if not stage:
        stage = _LANE_TO_STAGE.get((fallback_lane or "").strip(), "")
    eid_attr = html_lib.escape(str(eid), quote=True)
    stage_attr = html_lib.escape(str(stage), quote=True)
    return (f" data-effort-id=\"{eid_attr}\""
            f" data-current-stage=\"{stage_attr}\"")


def _build_effort_index(project_id):
    """Build a ``session_id -> effort dict`` index from :func:`_gather_efforts`
    (the v12 Wave 9 effort view). Used by the Layout-D render to bind each tile to
    its effort (W10). Each effort's chain root AND every member session id map to
    the SAME effort dict. Best-effort: honest ``{}`` on any failure (the tiles
    then fall back to a singleton effort = the session id)."""
    idx = {}
    try:
        for eff in _gather_efforts(project_id):
            if not isinstance(eff, dict):
                continue
            eid = eff.get("effort_id") or eff.get("chain_id") or ""
            if eid:
                idx[eid] = eff
            for m in eff.get("members", []) or []:
                msid = m.get("session_id") if isinstance(m, dict) else None
                if msid:
                    idx[msid] = eff
    except Exception:
        return {}
    return idx


def _render_layoutd_minitile(sv, trio_lane, project_id, folder_path, store_lane,
                             effort_index=None):
    """Render ONE Layout-D shelf ``.minitile`` from a session view (v12 Wave 2).

    Mockup schema: a ``.minitile`` with a ``.mtop`` (status dot + a stage badge),
    a ``.mtitle`` (the session's short title), and a ``.mfoot`` (state + age). It
    ALSO carries the legacy ``tile lane-tile`` + ``data-session`` click hooks so
    the W10 dock-open wiring (and the panel-open tests) bind to it. v12 W10:
    clicking it opens the SINGLE bottom dock bound to the tile's effort.
    """
    members = sv.get("members", []) or []
    rep = members[0] if members else None
    if rep is None:
        return ""
    light = _session_light_class(rep)
    sid = sv.get("session_id", "") or ""
    sid_attr = html_lib.escape(sid, quote=True)
    lane_attr = html_lib.escape(trio_lane, quote=True)
    title = html_lib.escape(_session_tile_title(rep))
    state_cls, state_lbl = _session_state_text(rep)
    state_lbl = html_lib.escape(state_lbl)
    age = html_lib.escape(rep.get("age") or "")
    if trio_lane == "general":
        badge_lane, badge_lbl = "general", "General"
    else:
        badge_lane = "build" if trio_lane == "build" else (
            "plan" if trio_lane in ("plan", "planning") else "research")
        badge_lbl = badge_lane.capitalize()
    extra = ""
    if light == "green":
        extra = " running"
    elif light == "red":
        extra = " failed"
    foot = (f"<span class='state {html_lib.escape(state_cls)}'>{state_lbl}</span>"
            + (f"<span class='age'>{age}</span>" if age else "<span></span>"))
    grass_chip = _layoutd_grass_origin_chip(rep, trio_lane)
    tie_data, tie_chip = _layoutd_tie_chip(sv)
    em_data = " data-effort-managed=\"1\"" if rep.get("effort_managed") else ""
    eff_data = _effort_data_attrs(sid, effort_index, fallback_lane=trio_lane)
    # W4 #6 UI — a discovered/brownfield shelf tile also carries the "Resume as
    # session" control (same warm-resume path as the headline); "" otherwise.
    resume_ctl = _layoutd_resume_control(sv, rep, trio_lane)
    return (
        f"<div class='minitile tile lane-tile{extra}' data-session=\"{sid_attr}\" "
        f"data-lane=\"{lane_attr}\" data-light=\"{light}\"{tie_data}{em_data}"
        f"{eff_data} "
        f"onclick=\"laneTileClick(event,'{sid_attr}')\">"
        f"<div class='mtop'><span class='dot {light}'></span>"
        f"<span class='badge {badge_lane}'>{badge_lbl}</span></div>"
        f"<div class='mtitle'>{title}</div>"
        f"<div class='mfoot'>{foot}</div>"
        f"{tie_chip}"
        f"{grass_chip}"
        f"{resume_ctl}"
        f"</div>"
    )


def _render_layoutd_headline(sv, trio_lane, project_id, folder_path, store_lane,
                             zone_label, effort_index=None):
    """Render the Layout-D ``.headline`` card for a zone's most-recent session
    (v12 Wave 2 / wired W10). Mirrors the mockup headline (status dot + stage
    badge + title + blurb + a 3-node stage track + report/summary links). Carries
    the legacy ``tile lane-tile`` + ``data-session`` hooks so the W10 dock-open
    wiring (and the panel-open tests) bind.

    v12 W10 / EV-2: the 3-node stage track lights by the tile's EFFORT
    ``current_stage`` (presence-based — research→node1, plan→1-2, build→1-3), NOT
    by the bare lane and NOT by iterating ``stage_history`` 1:1. Falls back to the
    lane when no effort resolves.
    """
    members = sv.get("members", []) or []
    rep = members[0] if members else None
    if rep is None:
        return ""
    light = _session_light_class(rep)
    sid = sv.get("session_id", "") or ""
    sid_attr = html_lib.escape(sid, quote=True)
    lane_attr = html_lib.escape(trio_lane, quote=True)
    title = html_lib.escape(_session_tile_title(rep))
    state_cls, state_lbl = _session_state_text(rep)
    blurb = ""
    if folder_path is not None:
        blurb = _session_tile_blurb(sv, folder_path, project_id, store_lane)
    blurb_html = (f"<p class='hblurb'>{html_lib.escape(blurb)}</p>"
                  if blurb else "")
    if trio_lane == "general":
        badge_lane, badge_lbl = "general", "General"
    else:
        badge_lane = "build" if trio_lane == "build" else (
            "plan" if trio_lane in ("plan", "planning") else "research")
        # Plan and Build share ONE combined zone → label it as both.
        badge_lbl = ("Plan / Build" if badge_lane in ("plan", "build")
                     else badge_lane.capitalize())
    running_cls = " running" if light == "green" else ""
    running_chip = ("<span style='font-size:11px;color:var(--success)'>"
                    "&#9679; running</span>" if light == "green" else "")
    # v12 W10 / EV-2: light the 3-node stage track by the EFFORT's current_stage
    # (presence-based), falling back to the bare lane when no effort resolves.
    # General sessions are stage-less (not a trio lane) — no Research→Plan→Build
    # track (it would be misleading); the dock likewise suppresses it for general.
    if trio_lane == "general":
        track = ""
    else:
        eff = (effort_index or {}).get(sid)
        track_stage = (eff.get("current_stage") if eff else "") or trio_lane
        # research → first node; plan → first two; build → all three.
        reached = {"research": 1, "plan": 2, "planning": 2, "build": 3}.get(
            track_stage, 1)
        track = _render_layoutd_track(track_stage, reached)
    grass_chip = _layoutd_grass_origin_chip(rep, trio_lane)
    tie_data, tie_chip = _layoutd_tie_chip(sv)
    em_data = " data-effort-managed=\"1\"" if rep.get("effort_managed") else ""
    eff_data = _effort_data_attrs(sid, effort_index, fallback_lane=trio_lane)
    # W4 #6 UI — a discovered/brownfield headline carries a "Resume as session"
    # control (warm resume via the W3 synthesized seed); "" for a managed tile.
    resume_ctl = _layoutd_resume_control(sv, rep, trio_lane)
    # Trio skill icon(s) on the big headline tile: Research→researchPrime; the
    # combined Plan/Build zone shows BOTH Crucible + Foreman. Served from /vendor/brand.
    def _skill_icon_img(fn, skill):
        return (
            f"<img class='lane-skill-icon' src='/vendor/brand/{fn}?v={BUILD_ID}' "
            f"alt='{skill}' title='{skill}' "
            f"style='width:22px;height:22px;border-radius:5px;object-fit:cover;"
            f"vertical-align:middle;margin-right:5px'>")
    if badge_lane == "research":
        lane_icon = _skill_icon_img("research-prime-icon.jpg", "researchPrime")
    elif badge_lane in ("plan", "build"):
        lane_icon = (_skill_icon_img("crucible-icon.svg", "Crucible")
                     + _skill_icon_img("foreman-icon.svg", "Foreman"))
    else:
        lane_icon = ""
    return (
        f"<div class='headline tile lane-tile{running_cls}' "
        f"data-session=\"{sid_attr}\" data-lane=\"{lane_attr}\" "
        f"data-light=\"{light}\"{tie_data}{em_data}{eff_data} "
        f"onclick=\"laneTileClick(event,'{sid_attr}')\">"
        f"<div class='htop'>"
        f"<span class='dot {light}'></span>"
        f"{lane_icon}"
        f"<span class='badge {badge_lane}'>{badge_lbl}</span>"
        f"{running_chip}{grass_chip}</div>"
        f"<div class='htitle'>{title}</div>"
        f"{blurb_html}"
        f"<div class='hrow'>{track}{tie_chip}{resume_ctl}</div>"
        f"</div>"
    )


def _render_layoutd_track(trio_lane, reached):
    """Render the 3-node Research→Plan→Build stage track for a headline card."""
    lanes = ("research", "plan", "build")
    cur_idx = {"research": 0, "plan": 1, "planning": 1, "build": 2}.get(
        trio_lane, 0)
    parts = ["<span class='track'>"]
    for i, ln in enumerate(lanes):
        node_cls = ["node", ln]
        if i < reached:
            node_cls.append("reached")
        if i == cur_idx:
            node_cls.append("current")
        parts.append(f"<span class='{' '.join(node_cls)}'></span>")
        if i < len(lanes) - 1:
            line_cls = "line done" if i + 1 < reached else "line"
            parts.append(f"<span class='{line_cls}'></span>")
    cur_lbl = {"plan": "Plan", "planning": "Plan", "build": "Build"}.get(
        trio_lane, "Research")
    parts.append(f"<span class='track-lbl'>{cur_lbl}</span></span>")
    return "".join(parts)


def _render_layoutd_zone(zone_key, zone_label, section_lbl, sessions,
                         folder_path, project_id, effort_index=None):
    """Render one Layout-D zone: a section label + the headline card + a
    collapsible shelf of older "little tiles" (v12 Wave 2 / wired W10). Honest
    empty state (and NO shelf) when the zone has no sessions. ``effort_index``
    (session_id → effort dict) binds each tile to its effort for the dock.
    """
    if not sessions:
        empty = (
            f"<div class='sectionlbl'>{section_lbl}</div>"
            f"<div class='headline' data-empty='1' data-zone='{zone_key}'>"
            f"<p class='hblurb'>No {html_lib.escape(zone_label.lower())} "
            f"sessions yet.</p></div>"
        )
        return empty
    head_sv = sessions[0]
    head_lane = _sv_zone_lane(head_sv, zone_key)
    store_lane = "planning" if head_lane == "plan" else head_lane
    headline = _render_layoutd_headline(
        head_sv, head_lane, project_id, folder_path, store_lane, zone_label,
        effort_index=effort_index)
    older = sessions[1:]
    shelf = ""
    if older:
        tiles = []
        for sv in older:
            ln = _sv_zone_lane(sv, zone_key)
            sl = "planning" if ln == "plan" else ln
            tiles.append(_render_layoutd_minitile(
                sv, ln, project_id, folder_path, sl,
                effort_index=effort_index))
        n = len(older)
        shelf_id = f"shelf_{html_lib.escape(zone_key, quote=True)}"
        tgl_id = f"tgl_{html_lib.escape(zone_key, quote=True)}"
        label_attr = html_lib.escape(zone_label.lower(), quote=True)
        # John tweak: the OLDER-runs shelf starts COLLAPSED on first load (the
        # headline card stays visible). Server-render the collapsed class + the
        # "Show all" caption so there is no flash of expanded content before JS.
        # W4 #3 render — the shelf IS the "previous efforts" expander: it renders
        # ONLY when a zone holds >1 effort (the latest is the headline, the rest
        # sit behind this expander). The ``prev-efforts`` class is the stable hook
        # for that contract (present iff >1).
        shelf = (
            f"<button class='showall prev-efforts' id='{tgl_id}' "
            f"onclick=\"toggleShelf('{shelf_id}','{tgl_id}',{n},"
            f"'{label_attr}')\">&#9656; Show all {n} older "
            f"{html_lib.escape(zone_label.lower())} sessions</button>"
            f"<div class='shelf-wrap prev-efforts collapsed' id='{shelf_id}'>"
            f"<div class='shelf'>{''.join(tiles)}</div></div>"
        )
    return (
        f"<div class='sectionlbl'>{section_lbl}</div>"
        f"{headline}"
        f"{shelf}"
    )


def _sv_zone_lane(sv, zone_key):
    """Best-effort trio-lane for a session view inside a Layout-D zone, from the
    representative member's ``trio_lane`` (the merged plan/build zone holds both)."""
    if zone_key == "research":
        return "research"
    if zone_key == "general":
        return "general"
    rep = (sv.get("members") or [None])[0]
    if isinstance(rep, dict):
        ln = (rep.get("trio_lane") or "").strip()
        if ln in ("plan", "planning", "build"):
            return ln
    return "plan"


def _gandalf_ts_label(ts) -> str:
    """Format a Gandalf run's unix ts as ``YYYY-MM-DD HH:MM`` (honest empty)."""
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M")
    except (TypeError, ValueError, OSError):
        return ""


def _render_layoutd_gandalf_panel(folder_path, project_id) -> str:
    """Render the Layout-D right-column Gandalf mini-panel (Gandalf v1 Wave 3).

    The white-wizard "what's really going on here" read. Reads ``gandalf.list_runs``
    ONLY (the internal index — NEVER a model call on render). Header = the
    white-wizard icon + "Gandalf" + a Re-run button (``gandalfRun(PROJECT_ID)``).
    Run history newest-first; each row = the one-line verdict + ts + grade chips
    (a SPECULATIVE/PROMISING floor chip + a single-family/Error chip as applicable).
    Clicking a row inline-expands its exec-summary (fetched from ``exec_rel`` via
    the traversal-safe ``/artifact`` route) with [Full report] + [raw JSON] links.
    A degraded/error run renders an HONEST row (reason text, NO dead links).
    Honest empty state ("No Gandalf read yet" + a Run button) before the first run.
    Sits ABOVE Grass in the right column (decision #5). HTML f-string (double
    braces); the panel JS lives in the RAW ``_PROJECT_WINDOW_JS``.
    """
    try:
        runs = _gandalf.list_runs(folder_path, project_id)
    except Exception:
        runs = []
    n = len(runs)
    
    in_flight = False
    with _GANDALF_INFLIGHT_GUARD:
        in_flight = project_id in _GANDALF_INFLIGHT
        
    pid_q = html_lib.escape(str(project_id), quote=True)
    icon = (
        f"<img class='gicon' src='/vendor/brand/gandalf-icon-v5.jpg?v={BUILD_ID}' "
        "alt='Gandalf the White'>")

    dis = " disabled" if in_flight else ""

    if not runs:
        # Honest empty state — no fabricated rows; a single Run control.
        body = (
            "<div class='gandalf-empty' data-gandalf-empty='1'>"
            "No Gandalf read yet."
            f"<button class='btn sm primary gandalf-run'{dis} "
            f"onclick=\"gandalfRun('{pid_q}')\">&#8635; { 'Running...' if in_flight else 'Run' }</button>"
            f"<button class='btn sm gandalf-run gandalf-heavy'{dis} "
            "title='Gandalf-Heavy — top-tier Claude (Fable-5) reasoner' "
            f"onclick=\"gandalfRun('{pid_q}', 'heavy')\">&#9733; { 'Running Heavy...' if in_flight else 'Run Heavy' }</button>"
            "</div>")
        inflight_attr = " data-gandalf-inflight='1'" if in_flight else ""
        return (
            f"<div class='panel gandalf-panel' id='gandalfPanel'{inflight_attr}>"
            "<div class='ptitle gandalf-head'>"
            ""
            f"{icon}<span class='gt'>Gandalf</span>"
            f"<button class='btn sm gandalf-run gandalf-rerun'{dis} "
            f"onclick=\"gandalfRun('{pid_q}')\">&#8635; { 'Running...' if in_flight else 'Re-run' }</button>"
            f"<button class='btn sm gandalf-run gandalf-heavy'{dis} "
            "title='Gandalf-Heavy — top-tier Claude (Fable-5) reasoner' "
            f"onclick=\"gandalfRun('{pid_q}', 'heavy')\">&#9733; { 'Running Heavy...' if in_flight else 'Heavy' }</button></div>"
            f"<div class='gandalf-panel-body' id='gandalfPanelBody'>{body}</div>"
            "</div>")

    rows = []
    for r in runs:
        run_id = html_lib.escape(str(r.get("run_id") or ""), quote=True)
        ok = bool(r.get("ok"))
        verdict = r.get("verdict") or ""
        ts_lbl = html_lib.escape(_gandalf_ts_label(r.get("ts")))
        report_rel = r.get("report_rel") or ""
        exec_rel = r.get("exec_rel") or ""
        adv_rel = r.get("advisor_rel") or ""

        # A still-running record (the up-front in-progress row a background run
        # writes before it finishes) is neither a success nor an error — render it
        # as a RUNNING row, never a red "Run did not complete" error.
        running = bool(r.get("in_progress")) or (r.get("status") == "running")

        # Verdict / honest-error one-liner.
        if running:
            vtxt = "Running&hellip;"
            vcls = "verdict"
        elif ok:
            vtxt = html_lib.escape(verdict or "(no verdict)")
            vcls = "verdict"
        else:
            reason = html_lib.escape(str(r.get("reason") or "unknown"))
            vtxt = ("Run did not complete &mdash; " + reason)
            vcls = "verdict err"

        # Grade chips. The v1 honesty floor: Tier-1 elevations land SPECULATIVE,
        # single-family is cross_model:false. An error run gets a single Error chip.
        chips = []
        if running:
            chips.append("<span class='chip run'>Running</span>")
        elif not ok:
            chips.append("<span class='chip deg'>Error</span>")
        else:
            if r.get("cross_model"):
                chips.append("<span class='chip prom'>Promising</span>")
            else:
                chips.append("<span class='chip spec'>Speculative</span>")
                chips.append("<span class='chip sf'>single-family</span>")
            if r.get("degraded"):
                chips.append("<span class='chip deg'>degraded</span>")
        # Tier badge — mark a Gandalf-Heavy (Fable-5) read so it's distinguishable
        # from a regular (Opus) read at a glance.
        if r.get("tier") == "heavy":
            chips.append("<span class='chip heavy'>Heavy</span>")
        chips_html = "".join(chips)

        # SAFE links — only when the artifact rel paths exist (an error run has
        # none → NO dead links, per the mockup).
        exec_attr = html_lib.escape(exec_rel, quote=True)
        links = ""
        link_parts = []
        if ok and exec_rel:
            link_parts.append(
                f"<span class='genlarge' onclick=\"enlargeGandalfRun(event, this)\" style='cursor:pointer;color:var(--accent);margin-right:12px;font-size:11px'>&#10530; Enlarge</span>"
            )
        if ok and (report_rel or adv_rel):
            if report_rel:
                # v13 W1: &render=1 → the route serves the rendered Reader page;
                # the named window keeps every report open in ONE tab.
                href = (f"/artifact/{pid_q}?path="
                        + url_quote(report_rel, safe='') + "&render=1")
                link_parts.append(
                    f"<a href='{href}' target='anchor_report_window' "
                    "rel='noopener'>&#128196; Full report</a>")
            if adv_rel:
                ahref = (f"/artifact/{pid_q}?path="
                         + url_quote(adv_rel, safe=''))
                link_parts.append(
                    f"<a href='{ahref}' target='anchor_report_window' "
                    "rel='noopener'>{ } raw JSON</a>")
        if link_parts:
            links = "<div class='glinks'>" + "".join(link_parts) + "</div>"

        # The expandable body: only OK runs with an exec-summary carry one (fetched
        # lazily on first expand via gandalfToggleRun → /artifact). John tweak: an
        # ERROR run is NOT expandable — drop its caret + onclick (the failure reason
        # already shows in the row line; clicking opened an empty body box). OK runs
        # keep the expand caret + onclick.
        body_attr = (f" data-exec-rel='{exec_attr}'" if (ok and exec_rel) else "")
        # The (x) retire/archive control on EACH tile — drops the run via
        # /api/rnd/gandalf_archive and removes the tile on success. stopPropagation
        # so it never toggles the row open.
        retire = (
            "<span class='gretire' title='Retire / archive this run' "
            f"onclick=\"gandalfArchiveRun(event, '{run_id}')\">&times;</span>")
        if running:
            # Non-expandable RUNNING row: no caret, no error class, no retire
            # control (a live run can't be archived) — just a live status line.
            rows.append(
                f"<div class='grun run-row' data-run='{run_id}'>"
                f"<div class='grtop'><span class='{vcls}'>{vtxt}</span></div>"
                "<div class='gmeta'>"
                f"<span class='gts'>{ts_lbl}</span>{chips_html}</div>"
                "</div>")
        elif ok:
            rows.append(
                f"<div class='grun' data-run='{run_id}'{body_attr} "
                "onclick='gandalfToggleRun(this)'>"
                "<div class='grtop'><span class='gcaret'>&#9656;</span>"
                f"<span class='{vcls}'>{vtxt}</span>{retire}</div>"
                "<div class='gmeta'>"
                f"<span class='gts'>{ts_lbl}</span>{chips_html}</div>"
                "<div class='gbody' onclick='event.stopPropagation()'>"
                f"<div class='gexec'></div>{links}</div>"
                "</div>")
        else:
            # Non-expandable error row: no caret, no onclick, no body box.
            rows.append(
                f"<div class='grun err-row' data-run='{run_id}'>"
                f"<div class='grtop'><span class='{vcls}'>{vtxt}</span>{retire}</div>"
                "<div class='gmeta'>"
                f"<span class='gts'>{ts_lbl}</span>{chips_html}</div>"
                "</div>")

    # "Clear failed" — bulk-retire every failed/error run. Rendered ONLY when at
    # least one failed run exists (POST /api/rnd/gandalf_clear_failed).
    n_failed = sum(1 for r in runs if not bool(r.get("ok"))
                   and not (r.get("in_progress") or r.get("status") == "running"))
    clear_failed_btn = ""
    if n_failed:
        clear_failed_btn = (
            "<button class='btn sm gandalf-clear-failed' "
            "title='Retire all failed runs' "
            f"onclick=\"gandalfClearFailed('{pid_q}')\">&#10005; "
            f"Clear failed ({n_failed})</button>")
    # John tweak: the run list is collapsible IN THE HEADER (caret toggle, mirrors
    # the grass-mini pattern) and starts COLLAPSED on first load (server-rendered
    # .collapsed + the ▸ caret) so there is no flash of expanded content before JS.
    inflight_attr = " data-gandalf-inflight='1'" if in_flight else ""
    return (
        f"<div class='panel gandalf-panel' id='gandalfPanel'{inflight_attr}>"
        "<div class='ptitle gandalf-head'>"
        "<span class='gmini-tog' id='gandalfRunsTog' title='Collapse / expand the "
        "run list' onclick='toggleGandalfRuns(this)'>&#9656;</span>"
        f"{icon}<span class='gt'>Gandalf</span>"
        f"<span class='cnt'>{n} read{'s' if n != 1 else ''}</span>"
        f"{clear_failed_btn}"
        f"<button class='btn sm gandalf-run gandalf-rerun'{dis} "
        f"onclick=\"gandalfRun('{pid_q}')\">&#8635; { 'Running...' if in_flight else 'Re-run' }</button>"
        f"<button class='btn sm gandalf-run gandalf-heavy'{dis} "
        "title='Gandalf-Heavy — top-tier Claude (Fable-5) reasoner' "
        f"onclick=\"gandalfRun('{pid_q}', 'heavy')\">&#9733; { 'Running Heavy...' if in_flight else 'Heavy' }</button></div>"
        f"<div class='gandalf-panel-body' id='gandalfPanelBody'>"
        f"<div class='gruns collapsed' id='gandalfRuns'>{''.join(rows)}</div>"
        "</div>"
        "</div>")


def _render_layoutd_grass_panel(folder_path, project_id) -> str:
    """Render the Layout-D right-column Grass mini-panel (v12 Wave 2). Reuses the
    existing grass data; clicking a row / "Open workbench" opens the existing
    two-pane workbench (``openGrassWorkbench`` template, retained)."""
    try:
        ideas = _eh.grass_workbench_data(folder_path, project_id)
    except Exception:
        ideas = []
    n = len(ideas)
    rows = []
    _light = {_eh.GRASS_RAW: "grey", _eh.GRASS_REFINED: "amber",
              _eh.GRASS_PROMOTED: "green"}
    for i in ideas[:6]:
        status = i.get("status", _eh.GRASS_RAW)
        dot = _light.get(status, "grey")
        txt = html_lib.escape(i.get("title") or "(untitled idea)")
        tag = html_lib.escape(_GRASS_STATUS_LABEL.get(status, status))
        rows.append(
            f"<div class='idearow' onclick='openGrassWorkbench()'>"
            f"<span class='dot {dot}'></span><span class='it'>{txt}</span>"
            f"<span class='tag'>{tag}</span></div>"
        )
    if not rows:
        rows.append("<div class='idea-empty'>No ideas captured yet.</div>")
    # The idea list is collapsible IN THE TILE (caret toggle) — fold the open items
    # away while keeping +capture / Open-workbench reachable. John tweak: default
    # COLLAPSED (server-rendered .collapsed + the ▸ caret) so the first-load
    # dashboard is minimal with no flash of expanded content before JS.
    return (
        "<div class='panel'>"
        "<div class='ptitle'>"
        "<span class='gmini-tog' id='grassMiniTog' title='Collapse / expand the "
        "idea list' onclick='toggleGrassMini(this)'>&#9656;</span> "
        "&#127793; Grass Catcher "
        f"<span class='cnt'>{n} idea{'s' if n != 1 else ''}</span></div>"
        f"<div class='grass-mini-list collapsed' id='grassMiniList'>{''.join(rows)}</div>"
        "<div class='pactions'>"
        "<button class='btn sm' onclick='addIdea()'>+ capture</button>"
        # The open-workbench control carries the legacy grass-tile hooks
        # (``grass-tile`` class + ``data-grass-tile='1'``) so the existing grass
        # Playwright click targets resolve to the Layout-D mini-panel.
        "<button class='btn sm primary grass-open grass-tile' "
        "data-grass-tile='1' data-light='grey' "
        "onclick='openGrassWorkbench()'>Open workbench &#8594;</button>"
        "</div></div>"
    )


def _render_layoutd_deliverables_panel(folder_path, project_id) -> str:
    """Render the Layout-D right-column Deliverables panel (v12 Wave 2). Reuses
    the existing pinned-deliverable data; each row launches via the existing
    ``launchDeliverable`` JS (carried verbatim, the row keeps the deliv hooks)."""
    try:
        pinned = _deliv.list_pinned_deliverables(folder_path, project_id)
    except Exception:
        pinned = []
    rows = []
    for r in pinned:
        rel = r.get("artifact_path", "") or ""
        name = html_lib.escape(r.get("title") or rel or "")
        raw_type = (r.get("deliverable_type", "") or "").strip().lower()
        if raw_type not in _deliv.VALID_TYPES:
            raw_type = _deliv.infer_type(rel)
        dtype = html_lib.escape(raw_type)
        rel_attr = html_lib.escape(rel, quote=True)
        did_attr = html_lib.escape(r.get("job_id", "") or "", quote=True)
        rows.append(
            f"<div class='delivrow tile deliv-tile deliv-pinned' "
            f"data-deliv=\"{rel_attr}\" data-deliv-id=\"{did_attr}\" "
            f"data-deliv-type=\"{dtype}\" onclick='launchDeliverable(this)'>"
            f"<span class='dn'>&#8595; <span class='mono'>{name}</span></span>"
            f"<span class='tag'>{dtype}</span></div>"
        )
    if not rows:
        rows.append(
            "<div class='idea-empty'>No deliverables pinned yet — a Foreman "
            "build pins one on GREEN.</div>")
    return (
        "<div class='panel deliverables-panel'>"
        # crucible-improve #4 (W5): deliverables start COLLAPSED — drop the
        # `open` attribute so the panel renders folded by default (the
        # disc-caret CSS keys off [open]/:not([open]) and flips automatically).
        "<details class='deliv-details'>"
        f"<summary class='ptitle' style='cursor:pointer; outline:none'>"
        f"<span class='disc-caret' style='font-size:11px; transition:transform 0.12s; display:inline-block; margin-right:4px'>&#9662;</span>"
        f"&#128230; Deliverables <span class='cnt'>{len(pinned)}</span>"
        f"</summary>"
        f"<div class='deliv-body' style='margin-top:8px'>{''.join(rows)}</div>"
        "</details>"
        "</div>"
    )


def _load_gitignore(folder_path) -> list:
    """Read .gitignore patterns from the project root if present, plus .anchorignore."""
    ignore_path = Path(folder_path) / ".gitignore"
    patterns = []
    if ignore_path.is_file():
        try:
            with open(ignore_path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)
        except OSError:
            pass
    anchorignore_path = Path(folder_path) / ".anchorignore"
    if anchorignore_path.is_file():
        try:
            with open(anchorignore_path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)
        except OSError:
            pass
    return patterns


def _should_ignore_file(rel_path: Path, patterns: list) -> bool:
    """Determine if a relative path matches any ignore pattern or standard skip dirs.

    Reuses the existing logic shape from gandalf.py.
    """
    import fnmatch
    parts_lower = [p.lower() for p in rel_path.parts]
    for skip in {".git", ".anchor", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache"}:
        if skip in parts_lower:
            return True

    rel_str = rel_path.as_posix()
    rel_str_lower = rel_str.lower()

    for pattern in patterns:
        clean_pat = pattern.rstrip('/')
        if not clean_pat:
            continue
        clean_pat_lower = clean_pat.lower()

        # Check components of the path
        for part in rel_path.parts:
            part_lower = part.lower()
            if fnmatch.fnmatch(part, clean_pat) or fnmatch.fnmatch(part_lower, clean_pat_lower):
                return True

        # Check full relative path and patterns
        if fnmatch.fnmatch(rel_str, clean_pat) or fnmatch.fnmatch(rel_str_lower, clean_pat_lower):
            return True
        if fnmatch.fnmatch(rel_str, pattern) or fnmatch.fnmatch(rel_str_lower, pattern.lower()):
            return True

        # Support directory-specific patterns like "dir/*" or "dir/"
        if pattern.endswith('/'):
            if rel_str_lower.startswith(clean_pat_lower + '/'):
                return True
        if clean_pat.startswith('*') and fnmatch.fnmatch(rel_str_lower, '*' + clean_pat_lower):
            return True

    return False


def _render_layoutd_files_panel(folder_path, project_id) -> str:
    """Render the Layout-D right-column Project Files panel (v13 Wave 3)."""
    pid_attr = html_lib.escape(project_id, quote=True)
    try:
        project_root = Path(folder_path).resolve()
        patterns = _load_gitignore(project_root)
        count = 0
        for entry in project_root.iterdir():
            try:
                resolved_entry = entry.resolve()
                resolved_entry.relative_to(project_root)
                rel_entry = entry.relative_to(project_root)
                if not _should_ignore_file(rel_entry, patterns):
                    count += 1
            except (ValueError, OSError):
                continue
    except Exception:
        count = 0

    return (
        "<div class='panel files-panel'>"
        "<details class='files-details' id='projectFilesDetails' ontoggle='onProjectFilesToggle(this)'>"
        "<summary class='ptitle' style='cursor:pointer; outline:none'>"
        "<span class='disc-caret' style='font-size:11px; transition:transform 0.12s; display:inline-block; margin-right:4px'>&#9656;</span>"
        f"&#128194; Imported files ({count}) "
        f"<span class='path' id='projectFilesPath' style='font-size:11px;color:var(--text-dim);font-family:ui-monospace,Consolas,monospace;margin-left:6px'>/</span>"
        "</summary>"
        f"<div class='files-list' id='projectFilesList' style='max-height:250px;overflow-y:auto;background:rgba(0,0,0,0.15);border-radius:6px;margin-top:8px'>"
        "<div class='idea-empty'>Loading files...</div>"
        "</div>"
        f"<div class='files-preview' id='projectFilesPreviewContainer' style='display:none;margin-top:8px'>"
        "<div class='files-preview-header' style='display:flex;align-items:center'>"
        "<span class='files-preview-title' id='projectFilesPreviewTitle' style='font-size:12.5px;font-weight:700;color:var(--accent)'>Preview</span>"
        "<button class='files-preview-close' onclick='closeProjectFilesPreview()' style='margin-left:auto;background:none;border:none;color:var(--text-dim);cursor:pointer;font-size:16px'>&times;</button>"
        "</div>"
        "<pre class='files-preview-body' id='projectFilesPreviewCode' style='margin-top:6px;padding:8px;background:var(--surface2);border-radius:4px;overflow-x:auto;max-height:200px;font-size:11px;font-family:ui-monospace,Consolas,monospace;white-space:pre-wrap'></pre>"
        "</div>"
        "</details>"
        "</div>"
    )


def _render_layoutd_html(folder_path, project_id):
    """Render the v12 Layout-D board (Wave 2 skeleton, wired LIVE in W10).

    The headline cards + collapsible shelves render from
    :func:`_gather_project_sessions` (the visible tile shape) and are BOUND to the
    effort view (:func:`_gather_efforts`) via an effort index so each tile carries
    ``data-effort-id`` + ``data-current-stage`` — the dock opens bound to the
    effort and the 3-node stage track lights by ``current_stage`` (W10 / EV-2).
    The single bottom dock (chrome rendered separately) is the live surface.
    Returns the board fragment (+ the retained hidden grass-workbench template)."""
    sessions_by_lane = _gather_project_sessions(folder_path, project_id)
    zones = _layoutd_zones(folder_path, project_id, sessions_by_lane)
    # v12 W10: bind the tiles to the effort view (session_id → effort dict).
    effort_index = _build_effort_index(project_id)
    research_zone = _render_layoutd_zone(
        "research", "Research", "&#128300; Latest Research",
        zones["research"], folder_path, project_id, effort_index=effort_index)
    plan_build_zone = _render_layoutd_zone(
        "plan_build", "Plan/Build", "&#128208;&#8594;&#128296; Latest Plan / Build",
        zones["plan_build"], folder_path, project_id, effort_index=effort_index)
    # General sessions zone (bare terminals): most-recent headline + older-runs
    # shelf, mirroring the research / plan-build zones. Rendered ONLY when the
    # project actually has general sessions (unlike the always-present trio zones)
    # — so a project with no general activity is unchanged, and general sessions
    # are still started from the existing top "Open terminal" control (newGeneral,
    # which refreshes the board so this zone appears).
    general_sessions = zones.get("general", []) or []
    general_zone = ""
    if general_sessions:
        general_zone = _render_layoutd_zone(
            "general", "General", "&#128187; Latest General session",
            general_sessions, folder_path, project_id, effort_index=effort_index)
    gandalf_panel = _render_layoutd_gandalf_panel(folder_path, project_id)
    grass_panel = _render_layoutd_grass_panel(folder_path, project_id)
    deliv_panel = _render_layoutd_deliverables_panel(folder_path, project_id)
    files_panel = _render_layoutd_files_panel(folder_path, project_id)
    # v12 W10 (John change #2): TWO explicit start controls — "+ New research"
    # starts an effort at the Research stage, "+ New plan/build" starts one at the
    # Plan stage (W6 supports starting at research OR plan). Both go through
    # newEffort(stage) → term_start (effort_managed=True), token-authed.
    new_effort = (
        "<div class='neweffort-wrap' style='margin:0 0 18px;display:flex;gap:8px'>"
        "<button class='btn primary neweffort' id='newResearchBtn' "
        "onclick=\"newEffort('research')\" "
        "title='Start a new effort at the Research stage'>"
        "+ New research</button>"
        "<button class='btn primary neweffort' id='newPlanBuildBtn' "
        "onclick=\"newEffort('plan')\" "
        "title='Start a new effort at the Plan stage (then advance to Build)'>"
        "+ New plan/build</button>"
        "<button class='btn primary neweffort' id='newGeneralBtn' "
        "onclick=\"newEffort('general')\" "
        "title='Start a new general session'>"
        "+ New general</button></div>"
    )
    board = (
        "<div class='pgrid layoutd'>"
        "<div class='leftcol'>"
        f"{new_effort}"
        f"{research_zone}"
        f"{plan_build_zone}"
        f"{general_zone}"
        "</div>"
        "<div class='rightcol'>"
        f"{gandalf_panel}"
        f"{grass_panel}"
        f"{deliv_panel}"
        f"{files_panel}"
        "</div>"
        "</div>"
    )
    # The full two-pane Grass workbench, kept as a hidden template the panel
    # manager (openGrassWorkbench) clones into #panelStack (reused unchanged).
    workbench = (
        "<div id='grassWorkbenchTpl' style='display:none'>"
        + _render_grass_workbench(folder_path, project_id)
        + "</div>"
    )
    return board + workbench


def _render_layoutd_dock_html() -> str:
    """Render the Layout-D single bottom DOCK chrome (v12 Wave 2; wired LIVE W10).

    Mirrors the mockup dock: a title bar (status dot + title + a 3-node stage
    track + min/max/close + a distinct Kill -> Boneyard + the context-full WARN
    banner + Advance ->), then the body — summary ON TOP (full width), a draggable
    vertical splitter, and a full-width terminal whose height the user drags.
    Hidden + UNBOUND by default (``display:none``, no ``data-effort-id``); the W10
    JS (``openEffortDock``) shows + binds it to the clicked effort. The structural
    ids/classes here are the JS attach points; the live content is filled by JS
    (summary via ``_loadPanelSummary``/``_renderSplitSummary``; terminal via
    ``_mountTerminal``/``_mountReadOnlyBody`` over the WS->SSE transport).
    """
    return (
        "<div class='dock' id='effortDock' style='display:none'>"
        "<div class='dbar'>"
        "<span class='dot grey' id='dockDot'></span>"
        "<span class='dtitle' id='dockTitle'>Effort</span>"
        "<span id='dockEngTog' style='margin-left:8px;'></span>"
        # The 3-node stage track (filled by JS from current_stage — EV-2).
        "<span class='track' id='dockTrack'></span>"
        "<span class='dockrun' id='dockRun' style='display:none;font-size:11px;"
        "color:var(--success)'>&#9679; running</span>"
        # The context-full WARN banner (hidden until context_status.over_threshold;
        # one click -> handoff_to_fresh). An intentional addition beyond the mockup.
        "<span class='dock-warn' id='dockWarn' style='display:none' "
        "title='This session is getting full — hand off to a fresh session "
        "(continues the same effort)' onclick='dockHandoffToFresh()'>"
        "&#9888; context getting full &mdash; hand off &#8594;</span>"
        "<div class='dctrls'>"
        # Advance -> : in-session stage advance (POST /api/rnd/advance_stage).
        "<button class='btn primary sm' id='dockAdvance' "
        "title='Advance this effort to the next stage (same session)' "
        "onclick='dockAdvance()'>Advance &#8594;</button>"
        "<span class='ctl' id='dockMin' title='Minimize' "
        "onclick='dockMinimize()'>&#9601;</span>"
        "<span class='ctl' id='dockMax' title='Maximize / restore' "
        "onclick='dockMaximize()'>&#9634;</span>"
        "<span class='ctl' id='dockClose' title='Close (keeps the effort)' "
        "onclick='dockClose()'>&#10005;</span>"
        # W2 (followup): unified with the inline panel — the dock now carries
        # exactly TWO lifecycle controls, matching the panel's × + 🪦: the ×
        # graceful CLOSE above, and this ONE destructive Kill → Boneyard as the
        # headstone glyph (🪦, .killbone). The old "Kill → Boneyard" text button
        # AND the redundant second-× v9 true-delete (dockDelete) were removed.
        "<span class='ctl panelbtn killbone' id='dockKill' "
        "title='Kill &#8594; Boneyard (archive + reap this effort)' "
        "onclick='dockKill()'>&#129702;</span>"
        "</div></div>"
        "<div class='dbody'>"
        # TOP: summary region (full width).
        "<div class='dtop' id='dockTop'>"
        "<div class='dtop-head'>"
        "<p class='slabel'>Summary</p>"
        # v12 W10 (John change #3): the SELECTED effort's metrics — Σ tokens ·
        # time · $ — summed from its members' job_runner cost records
        # (GET /api/rnd/effort_rollup). Imported/discovered contribute 0 (honest).
        "<span class='dock-metrics' id='dockMetrics' "
        "title='This effort: tokens spent &middot; wall-clock time &middot; cost'>"
        "&#931; &mdash; tok &middot; &mdash; &middot; $&mdash;</span>"
        "</div>"
        "<div class='dock-summary summary split' id='dockSummary'>"
        "<span class='summ-loading'>Select an effort &mdash; "
        "its summary loads here.</span>"
        "</div></div>"
        # The DRAGGABLE vertical splitter (drag to resize the terminal height).
        "<div class='dsplit' id='dockSplit' "
        "title='Drag to resize the terminal height'></div>"
        # BOTTOM: full-width terminal host (xterm mounts here for a live session,
        # a read-only body for a historical one).
        "<div class='dbottom' id='dockBottom'>"
        "<p class='slabel'>Live terminal &middot; full width "
        "&middot; drag the bar above to resize</p>"
        "<div class='term dock-term-host' id='dockTermHost'></div>"
        "</div>"
        "</div></div>"
    )


def _safe_dom_id(seg: str) -> str:
    """A DOM-id-safe slug of a session id (which contains ``::`` etc.)."""
    return re.sub(r"[^A-Za-z0-9_-]+", "_", str(seg or "")) or "x"


def _session_tile_title(rep) -> str:
    """The visible title for a Paradigm-2 lane tile, derived from a session's
    representative effort view. Discovered → its ``title``; a run → its prompt
    hint / skill ``sub``; falls back to a lane-agnostic placeholder."""
    if not rep:
        return "session"
    if rep.get("discovered"):
        return (rep.get("title") or rep.get("artifact_path") or "imported").strip()
    sub = (rep.get("sub") or "").strip()
    if sub:
        return sub
    return (rep.get("skill") or "session").strip() or "session"


def _session_state_text(rep):
    """Return ``(state_class, state_label)`` for a tile's ``.st`` state span,
    mapped from the representative effort view (mirrors the mockup states:
    running / needs you / fail / done / imported / idle)."""
    if not rep:
        return ("done", "idle")
    if rep.get("discovered"):
        return ("done", "imported")
    if rep.get("needs_input"):
        return ("attn", "needs you")
    if rep.get("is_live"):
        return ("running", "running")
    if rep.get("is_done"):
        return ("done", "done")
    pill = (rep.get("pill_cls") or "").strip()
    if pill == "fail":
        return ("fail", rep.get("pill_lbl") or "failed")
    return ("done", rep.get("pill_lbl") or rep.get("status") or "idle")


def _session_tile_blurb(sv, folder_path, project_id, store_lane):
    """The short, clean blurb line for a lane tile (v7 Wave 3).

    Cache/registry-only — NEVER a synchronous model call on the render path:

    - A FINISHED session prefers its CACHED session summary blurb
      (:func:`summarizer.session_blurb`, a cache read; ``""`` when uncached).
    - A RUNNING session (or a finished one with no cache yet) falls back to its
      own short intent — the rep's ``sub`` (skill · prompt hint) or its
      ``title``/``label`` — run through :func:`summarizer.tile_blurb` so it is
      clean + capped (the Wave-1 normalizer).
    - Honest empty (``""``) when there is neither; the caller renders nothing.

    Stdlib only; never raises (degrades to ``""``).
    """
    rep = (sv.get("members") or [None])[0]
    if not isinstance(rep, dict):
        return ""
    sid = (sv.get("session_id") or "").strip()
    blurb = ""
    # Prefer a cached SESSION summary blurb (cache read; no model call). Skip the
    # synthetic "loose::<jid>" ids (no real cached summary keyed on them).
    if sid and not sid.startswith("loose::"):
        try:
            blurb = _summarizer.session_blurb(
                folder_path, project_id, store_lane, sid) or ""
        except Exception:
            blurb = ""
    if blurb:
        return blurb
    # Fall back to the session's own short intent (running or uncached).
    intent = (rep.get("sub") or rep.get("title") or "").strip()
    if not intent:
        return ""
    try:
        return _summarizer.tile_blurb(intent) or ""
    except Exception:
        return ""


def _render_lane_tile(sv, trio_lane, project_id, folder_path=None,
                      store_lane=""):
    """Render ONE session as a GENUINE Paradigm-2 ``.tile`` (v4.1 cockpit-render).

    Schema (per the mockup): ``.tr1`` (lane + version + status light ``.lt``),
    ``.ttl`` (title), ``.st`` (state + age). The tile carries a status light
    (locked color bucket via :func:`_session_light_class`) and a click hook
    (``laneTileClick`` → ``openPanel``) that opens the full-width inline panel —
    where the summary + transcript/terminal live. The tile itself contains NO
    report-viewer links, NO summary accordion, NO files expander; that detail
    moved INTO the opened panel. The legacy ``lane-tile`` class + ``data-light``
    are preserved alongside ``.tile`` so the panel-open hooks/tests still bind.
    """
    members = sv.get("members", [])
    rep = members[0] if members else None
    if rep is None:
        return ""
    light = _session_light_class(rep)
    sid = sv.get("session_id", "") or ""
    sid_attr = html_lib.escape(sid, quote=True)
    lane_attr = html_lib.escape(trio_lane, quote=True)
    ver = html_lib.escape(rep.get("ver") or "")
    age = html_lib.escape(rep.get("age") or "")
    title = html_lib.escape(_session_tile_title(rep))
    state_cls, state_lbl = _session_state_text(rep)
    state_lbl = html_lib.escape(state_lbl)
    # Extra tile class for the attn/fail accent borders (mockup .tile.attn/.fail).
    extra = ""
    if light == "amber" and rep.get("needs_input"):
        extra = " attn"
    elif light == "red":
        extra = " fail"
    st_bits = [f"<span class='state {html_lib.escape(state_cls)}'>{state_lbl}</span>"]
    if age:
        st_bits.append(f"<span class='age'>· {age}</span>")
    n_members = len(members)
    counts = ""
    if n_members > 1:
        counts = (f"<div class='counts'>{n_members} files</div>")
    # v7 Wave 3 — a short, clean blurb line (cache/registry-only; no model call).
    # Cached session-summary blurb for a finished session, else the session's own
    # short intent for a running/uncached one; honest-empty renders nothing.
    blurb_html = ""
    if folder_path is not None:
        blurb = _session_tile_blurb(sv, folder_path, project_id, store_lane)
        if blurb:
            blurb_html = f"<div class='blurb'>{html_lib.escape(blurb)}</div>"
    # Live-job data hooks: a live/needs-input representative carries its job_id +
    # live flag as data-* attributes (used by tests + any future re-adoption of a
    # background job). The cockpit opens such a tile through laneTileClick →
    # openPanel like any other. (Discovered/done tiles carry no live hooks.)
    live_data = ""
    if rep.get("is_live"):
        jid = rep.get("job_id", "") or ""
        live_data = (
            f" data-job-id=\"{html_lib.escape(jid, quote=True)}\""
            f" data-trio-lane=\"{lane_attr}\""
            f" data-ver=\"{ver}\" data-live=\"1\"")
    # Build→Planning tie (Option A): a clickable chip on the build tile linking to
    # the planning session this build executed on (set by _attach_build_planning_tie
    # only when there is a clear single-planning match). The matched planning
    # session_id rides as data-* so the opened panel's chain breadcrumb can render
    # the same tie (see _loadChainBreadcrumb's static fallback). Clicking the chip
    # opens that planning session's panel without also opening this tile's panel.
    tie = sv.get("linked_planning") or {}
    tie_data = ""
    tie_chip = ""
    if tie.get("session_id"):
        lp_sid = html_lib.escape(tie["session_id"], quote=True)
        lp_lbl = html_lib.escape(tie.get("label") or "planning")
        lp_lbl_attr = html_lib.escape(tie.get("label") or "planning", quote=True)
        tie_data = (f" data-linked-planning=\"{lp_sid}\""
                    f" data-linked-planning-label=\"{lp_lbl_attr}\"")
        tie_chip = (
            f"<span class='tiechip' title='Open the planning session this build "
            f"executed on' onclick=\"openLinkedPlanning(event,'{lp_sid}')\">"
            f"&#9741; Planning: {lp_lbl} &#9656;</span>")
    # v10 Wave 4 FIX 2 (D8): the board-tile "from grass" lineage chip. When this
    # session's record carries a ``grass_origin`` (set on the dev session at
    # export, or INHERITED down the chain by start_session FIX 1), render a chip
    # on the plan/build board tile that links back to the originating grass idea
    # — satisfying D8 VISIBLY on the board (not only in the opened panel). The
    # chip reads ONLY the SAFE projection field ``grass_origin`` (an idea id —
    # never worktree_path/branch). Its label + dead-state ("idea removed") are
    # resolved client-side by ``_resolveGrassOriginChips`` against the loaded
    # grass data, so the server render stays cheap and the panel + tile chips
    # share one dead-chip code path. Only plan/build columns carry it (the lanes
    # the mockup depicts); research is the chain root, never "from" itself.
    grass_chip = ""
    origin = (rep.get("grass_origin") or "").strip()
    if origin and trio_lane in ("plan", "planning", "build"):
        origin_attr = html_lib.escape(origin, quote=True)
        grass_chip = (
            f"<span class='grassorigin' data-grass-origin=\"{origin_attr}\" "
            f"data-grass-pending=\"1\" "
            f"title='This work traces back to a grass idea — click to open it'>"
            f"&#127793; from grass</span>")
    return (
        f"<div class='tile lane-tile{extra}' data-session=\"{sid_attr}\" "
        f"data-lane=\"{lane_attr}\" data-light=\"{light}\"{live_data}{tie_data} "
        f"onclick=\"laneTileClick(event,'{sid_attr}')\">"
        f"<div class='tr1'><span class='lane'>{ver or lane_attr}</span>"
        f"<span class='ver'></span>"
        f"<span class='lt {light}' aria-hidden='true'></span></div>"
        f"<div class='ttl'>{title}</div>"
        f"{blurb_html}"
        f"<div class='st'>{''.join(st_bits)}</div>"
        f"{counts}"
        f"{tie_chip}"
        f"{grass_chip}"
        f"</div>"
    )


def _render_lane_sessions(session_views, store_lane, project_id, trio_lane="",
                          folder_path=None):
    """Render a lane's sessions as Paradigm-2 tiles: most-recent visible +
    a "previous sessions (N)" expander holding the rest, ALSO as tiles
    (v4.1 cockpit-render — replaces the old effort-card lane content).

    The MOST-RECENT session is the visible lane TILE — a status light
    (``.lt green/amber/red/grey`` from :func:`_session_light_class`) + a
    click-to-expand hook (``laneTileClick`` → ``openPanel``) opening the
    full-width inline panel (NOT a floating window, NOT page nav). The remaining
    sessions are tiles inside a ``<details class='prev-sessions'>`` expander. No
    tile carries report links / a summary accordion / a files expander — that
    detail lives in the opened panel.
    """
    if not session_views:
        return ""
    recent = _render_lane_tile(
        session_views[0], trio_lane, project_id, folder_path, store_lane)
    older = session_views[1:]
    if not older:
        return recent
    older_tiles = "".join(
        _render_lane_tile(sv, trio_lane, project_id, folder_path, store_lane)
        for sv in older)
    return (
        f"{recent}"
        f"<details class='prev-sessions'>"
        f"<summary>previous sessions ({len(older)})</summary>"
        f"<div class='prev-sessions-body'>{older_tiles}</div>"
        f"</details>"
    )


# v4.1 cockpit-render — Deliverables lane = launch-by-type TILES.
def _render_deliverable_lane_tiles(folder_path, project_id) -> str:
    """Render the Deliverables lane as launch-by-type ``.tile`` cards (mockup
    Paradigm-2): one tile per pinned deliverable, showing its name + type, whose
    click launches it via the existing ``launchDeliverable`` JS (which POSTs the
    type-appropriate run endpoint). Falls back to a placeholder when none are
    pinned. Best-effort; never raises."""
    try:
        pinned = _deliv.list_pinned_deliverables(folder_path, project_id)
    except Exception:
        pinned = []
    if not pinned:
        return ("<div class='idea-empty'>No deliverables pinned yet — a Foreman "
                "build pins one on GREEN.</div>")
    tiles = []
    for r in pinned:
        name = html_lib.escape(r.get("title") or r.get("artifact_path") or "")
        rel = r.get("artifact_path", "") or ""
        raw_type = (r.get("deliverable_type", "") or "").strip().lower()
        if raw_type not in _deliv.VALID_TYPES:
            raw_type = _deliv.infer_type(rel)
        dtype = html_lib.escape(raw_type)
        did = r.get("job_id", "") or ""
        rel_attr = html_lib.escape(rel, quote=True)
        did_attr = html_lib.escape(did, quote=True)
        tiles.append(
            f"<div class='tile deliv-tile deliv-pinned' data-deliv=\"{rel_attr}\" "
            f"data-deliv-id=\"{did_attr}\" data-deliv-type=\"{dtype}\" "
            f"onclick=\"launchDeliverable(this)\">"
            f"<div class='tr1'><span class='lane'>{dtype}</span>"
            f"<span class='lt grey' aria-hidden='true'></span></div>"
            f"<div class='ttl'>{name}</div>"
            f"<div class='st'><span class='state done'>▸ launch</span>"
            f"<span class='deliv-msg' style='color:var(--text-dim);"
            f"margin-left:6px'></span></div>"
            f"<button class='deliv-stop' onclick=\"event.stopPropagation();"
            f"stopDeliverable(this)\" style='display:none'>Stop</button>"
            f"</div>"
        )
    return "".join(tiles)


def _fmt_rollup_line(roll: dict) -> str:
    """Render a ``project_effort_rollup`` dict as ``Σ <tok> tok · $<c> · <t> · N sessions``.

    Used by the project-window header (v4 Wave 5). Run-session-only totals (the
    rollup already excludes imported/discovered). Stdlib only; never raises.

    Honesty rules (optimize-not-lying):
    - Zero activity (no sessions, no tokens, no wall clock) → named empty state,
      never ``0 tok · (subscription)``.
    - ``$`` is shown ONLY when the engine reported a nonzero ``cost_usd``.
    - ``(subscription)`` only when tokens were actually measured and cost is 0
      (Max-subscription path) — never inferred from a bare zero cost alone.
    - Sessions with no token measurement use ``0 tok measured`` / ``cost unknown``.
    """
    toks = int(roll.get("tokens", 0) or 0)
    cost = float(roll.get("cost_usd", 0.0) or 0.0)
    ms = int(roll.get("wall_clock_ms", 0) or 0)
    n = int(roll.get("sessions", 0) or 0)
    if n <= 0 and toks <= 0 and ms <= 0:
        return "Σ no run sessions yet"
    secs = ms / 1000.0
    if secs >= 3600:
        tstr = f"{secs / 3600.0:.1f}h"
    elif secs >= 60:
        tstr = f"{secs / 60.0:.0f}m"
    else:
        tstr = f"{secs:.0f}s"
    if toks >= 1000:
        tokstr = f"{toks / 1000.0:.0f}k tok"
    else:
        tokstr = f"{toks} tok"
    # No-own-pricing-table (LOCKED, telemetry-resume W5): ``$`` is shown ONLY when
    # the engine itself reported a nonzero ``costUSD``. On the Max-subscription
    # host the per-message sidecar carries no dollar figure, so a *measured*
    # session renders ``… (subscription)`` — Anchor never computes a dollar
    # figure of its own. (See NORTH-STAR-AMENDMENT.md "No-own-pricing-table".)
    if cost > 0:
        money = f"${cost:.2f}"
    elif toks > 0:
        money = "(subscription)"
    else:
        money = "cost unknown"
    # When only wall-clock exists (Grok unmeasured / wall-only rows), be explicit.
    if toks == 0 and ms > 0:
        return (f"Σ time {tstr} · {money} · 0 tok measured"
                f" · {n} session{'' if n == 1 else 's'}")
    if toks == 0:
        return (f"Σ 0 tok measured · {money} · {tstr}"
                f" · {n} session{'' if n == 1 else 's'}")
    return (f"Σ {tokstr} · {money} · {tstr} "
            f"· {n} session{'' if n == 1 else 's'}")



def _live_session_count(project_id: str) -> int:
    """Count not-yet-finalized live managed sessions for a project (never raises)."""
    if not project_id:
        return 0
    try:
        import session_registry as _sreg
        live_statuses = {
            getattr(_sreg, "STATUS_RUNNING", "running"),
            getattr(_sreg, "STATUS_NEEDS_ATTENTION", "needs-attention"),
            getattr(_sreg, "STATUS_IDLE", "idle"),
        }
        n = 0
        for rec in _sreg.list_sessions(project_id) or []:
            if (rec or {}).get("status") in live_statuses:
                n += 1
        return n
    except Exception:
        return 0


def _fmt_project_usage_line(roll, rate=None, live_count=0) -> str:
    """Honest project usage line combining effort rollup + capture-rate + live.

    ``project_effort_rollup`` only counts RUN cost records (tokens/wall). Managed
    terminal sessions can exist with zero rollup contribution (still live, or
    finalized unmeasured with no wall row). Never show ``Σ no run sessions yet``
    when capture-rate or live registry sessions prove activity.
    """
    roll = roll or {}
    toks = int(roll.get("tokens", 0) or 0)
    ms = int(roll.get("wall_clock_ms", 0) or 0)
    n = int(roll.get("sessions", 0) or 0)
    if toks > 0 or ms > 0 or n > 0:
        return _fmt_rollup_line(roll)

    rate = rate or {}
    total = int(rate.get("total", 0) or 0)
    measured = int(rate.get("measured", 0) or 0)
    unm = int(rate.get("unmeasured", 0) or 0)
    failed = int(rate.get("capture_failed", 0)
                 or rate.get("capture-failed", 0) or 0)
    live = int(live_count or 0)

    if total <= 0 and live <= 0:
        return "Σ no run sessions yet"

    parts = []
    if live > 0:
        parts.append("%d live" % live)
    if measured > 0:
        parts.append("%d measured" % measured)
    if unm > 0:
        parts.append("%d unmeasured" % unm)
    if failed > 0:
        parts.append("%d capture-failed" % failed)
    if not parts and total > 0:
        parts.append("%d session%s" % (total, "" if total == 1 else "s"))

    reason_bit = ""
    reasons = rate.get("reasons") or {}
    if isinstance(reasons, dict) and reasons:
        try:
            top = max(reasons.items(), key=lambda kv: int(kv[1] or 0))
            if top and top[0]:
                reason_bit = " (%s)" % top[0]
        except Exception:
            reason_bit = ""

    pending = " · usage pending finalize" if live > 0 and measured == 0 else ""
    return ("Σ 0 tok measured · cost unknown · %s%s%s"
            % (", ".join(parts), reason_bit, pending))


def _fmt_capture_rate_short(rate: dict) -> str:
    """Compact capture-rate note for project-row rollup (never raises)."""
    try:
        total = int(rate.get("total", 0) or 0)
        measured = int(rate.get("measured", 0) or 0)
        unm = int(rate.get("unmeasured", 0) or 0)
        failed = int(rate.get("capture-failed", 0) or rate.get("capture_failed", 0) or 0)
        if total <= 0:
            return ""
        parts = [f"measured {measured}/{total}"]
        if unm:
            parts.append(f"{unm} unmeasured")
        if failed:
            parts.append(f"{failed} capture-failed")
        return " · ".join(parts)
    except Exception:
        return ""


def render_header_rollup_html(project_id: str) -> str:
    """The per-project cost/tokens/time rollup for the project-window header.

    Server-side render of ``effort_history.project_effort_rollup(pid,'lifetime')``
    beside the project path (v4 Wave 5, MASTER-PLAN cockpit header). A small
    lifetime/30-day toggle re-fetches the read-only ``/api/rnd/project_rollup``
    endpoint and swaps the text in place (the actual swap is the JS
    ``rndRollupWindow``). Both windows' text are rendered so a no-JS view still
    shows lifetime totals. Stdlib only; never raises (omits on failure).
    """
    try:
        life = _eh.project_effort_rollup(project_id, window=_eh.WINDOW_LIFETIME)
    except Exception:
        return ""
    rate_life = {}
    try:
        rate_life = _rollhon.project_capture_rate(
            project_id, window="lifetime") or {}
    except Exception:
        rate_life = {}
    live_n = _live_session_count(project_id)
    pid_attr = html_lib.escape(project_id, quote=True)
    life_txt = html_lib.escape(
        _fmt_project_usage_line(life, rate=rate_life, live_count=live_n))
    # Honest Telemetry W5: the capture-rate stamp beside the numeric rollup —
    # 'measured N/T sessions (lifetime) · K capture-failed'. capture-failed is
    # ALWAYS counted separately (never folded into unmeasured) and tinted red when
    # present. Sibling projection (rollup_honesty) — the numeric rollup dict above
    # is unchanged (the W1 audit's preferred path). Best-effort; omit on failure.
    caprate_html = ""
    try:
        rate = _rollhon.project_capture_rate(project_id, window="lifetime")
        if int(rate.get("total", 0) or 0) > 0:
            caprate_html = " &nbsp;·&nbsp; " + _rollhon.capture_rate_html(rate)
    except Exception:
        caprate_html = ""
    # telemetry-resume W6: the bounded parked-worktree budget count (a system
    # indicator — parked warm worktrees held vs the eviction budget). Best-effort;
    # omitted when there are no parked worktrees.
    parked_html = _parked_worktree_stamp()
    return (
        f"<span class='roll' id='hdrRollup' data-window='lifetime' "
        f"data-pid=\"{pid_attr}\">{life_txt}</span>"
        f"{caprate_html}"
        f"{parked_html}"
        f"<span class='rolltog' role='group' aria-label='rollup window'>"
        f"<b class='on' data-window='lifetime' "
        f"onclick=\"rndRollupWindow('lifetime',this)\">lifetime</b>"
        f"<b data-window='30d' "
        f"onclick=\"rndRollupWindow('30d',this)\">30d</b>"
        f"</span>"
    )


def _parked_worktree_stamp() -> str:
    """The bounded parked-worktree count stamp (telemetry-resume W6, dashboard).

    'N parked worktrees / budget M' — the count of RETAINED-parked worktrees vs
    the eviction budget, so the user can see how close the system is to graceful
    oldest-first eviction. Returns '' when nothing is parked (or on any failure).
    """
    try:
        import worktrees as _wt
        import pty_manager as _pty_c
        n = _wt.parked_worktree_count(set(_pty_c._LIVE.keys()))
        if n <= 0:
            return ""
        budget = _wt.parked_worktree_budget()
        over = n > budget
        tint = " style='color:#dc2626'" if over else ""
        return (" &nbsp;·&nbsp; <span class='pwbudget'%s title='parked warm "
                "worktrees held vs the eviction budget'>%d parked / budget %d"
                "</span>" % (tint, n, budget))
    except Exception:
        return ""


def render_model_flex_badge(env=None) -> str:
    """Header badge surfacing the host's model-flex posture (Wave 8, #10).

    Reads the host-capability profile (``lanes.detect_host_profile``) and shows,
    honestly, how execution resolves on THIS host:

    - both subscriptions → Claude driver + Gemini 5:1 skill-layer swarm;
    - Claude only → Claude everywhere, no Gemini swarm spawned;
    - Gemini only → research on Gemini, Plan/Build require Claude;
    - neither → no engine.

    Pure render (no side effects, no subprocess). Returns a ``<span class='mflex …'>``.
    """
    prof = _lanes.detect_host_profile(env)
    has_c, has_g = bool(prof.get("claude")), bool(prof.get("gemini"))
    if has_c and has_g:
        label = "&#9670; Claude driver &middot; &#10022; Gemini swarm %s" % (
            html_lib.escape(_lanes.SWARM_RATIO))
        title = ("Both subscriptions: Claude drives every lane; Gemini runs the "
                 "skill-layer %s swarm (agy-dispatch). Never cross-called." %
                 _lanes.SWARM_RATIO)
        cls = "mflex-both"
    elif has_c:
        label = "&#9670; Claude only"
        title = ("Claude-only host: Claude drives every lane; no agy/Gemini "
                 "process is ever spawned.")
        cls = "mflex-claude"
    elif has_g:
        label = "&#10022; Gemini only &middot; Plan/Build require Claude"
        title = ("Gemini-only host: research runs on Gemini; Plan/Build require "
                 "Claude (Crucible/Foreman are Claude Code engines) and are shown "
                 "as an honest 'requires Claude' state, not a crash.")
        cls = "mflex-gemini"
    else:
        label = "no engine"
        title = "No Claude or Gemini subscription detected on this host."
        cls = "mflex-none"
    # Dismissible chip (2026-07-02, John): an inline × persists the dismissal in
    # localStorage ('mflexDismissed'); the trailing self-contained script hides an
    # already-dismissed chip on load (document.currentScript anchors it to THIS
    # badge, so the pattern is safe wherever the badge is rendered — project
    # window and home dashboard). Clearing site data brings it back.
    _x = ("<button class='mflex-x' title='Dismiss' "
          "style=\"background:transparent;border:none;color:inherit;cursor:pointer;"
          "font-size:13px;line-height:1;padding:0 0 0 6px;vertical-align:baseline\" "
          "onclick=\"try{localStorage.setItem('mflexDismissed','1')}catch(e){}"
          "this.parentNode.style.display='none';return false\">&times;</button>")
    # NOTE: no consecutive `{{`/`}}` anywhere in this JS — the W8 test suite
    # treats doubled braces in rendered HTML as f-string leakage (a real bug
    # class in this file), so the closing braces are spaced.
    _hide = ("<script>try{if(localStorage.getItem('mflexDismissed')==='1')"
             "{var _m=document.currentScript.previousElementSibling;"
             "if(_m&&_m.classList&&_m.classList.contains('mflex'))"
             "_m.style.display='none';} }catch(e){}</script>")
    return (f"<span class='mflex {cls}' "
            f"title='{html_lib.escape(title, quote=True)}'>{label}{_x}</span>{_hide}")


_STEWARD_UI_FALLBACK = {
    "key": "ecgberht", "label": "Ecgberht",
    "desc": "The royal steward — stone high seat and wax seal (the original).",
    "high_seat": "ecgberht-portfolio-high-seat.jpg",
    "seal": "ecgberht-project-seal.jpg",
    "high_seat_name": "High Seat",
    "seal_name": "Seal",
    "projects_hint": "each under Ecgberht&rsquo;s seal",
}


def _steward_ui() -> dict:
    """TOTAL steward profile for UI renders — every catalog field present.

    The single resolver every steward-branded surface goes through (tiles,
    rows, selector), so livery can never mix: one persona, one icon pair,
    one naming set. Settings hiccup → complete Ecgberht fallback.
    """
    try:
        prof = dict(_aset.steward_profile())
    except Exception:
        return dict(_STEWARD_UI_FALLBACK)
    for k, v in _STEWARD_UI_FALLBACK.items():
        prof.setdefault(k, v)
    return prof


def _steward_seal_icon_src() -> str:
    """The active persona's SEAL icon src (project-level mark), cache-busted."""
    return "/vendor/brand/%s?v=%s" % (_steward_ui()["seal"], BUILD_ID)


def render_steward_control() -> str:
    """Compact 'Steward' persona select for the home header (2026-07-29).

    One steward engine, selectable livery: Ecgberht (throne + wax seal),
    Aladdin (opened cave + genie lamp), Jarvis (tipped bowler + silver
    server). Each option's title carries the one-line description. POSTs
    ``steward_type`` to /api/settings on change, then reloads — the HIGH
    SEAT and SEAL icons are rendered server-side from the setting.
    """
    prof = _steward_ui()
    active = prof.get("key", "ecgberht")
    opts = []
    for key in ("ecgberht", "aladdin", "jarvis"):
        meta = _aset.STEWARDS[key]
        sel = " selected" if key == active else ""
        opts.append(
            "<option value='%s' title=\"%s\"%s>%s</option>"
            % (key, html_lib.escape(meta["desc"], quote=True), sel,
               html_lib.escape(meta["label"])))
    seal_icon = html_lib.escape(str(prof.get("seal", "")), quote=True)
    desc = html_lib.escape(str(prof.get("desc", "")), quote=True)
    html = (
        "<div id='stewardPick' style=\"display:inline-flex;align-items:center;"
        "gap:6px;font-size:11px;color:var(--text-dim)\" title=\"%s\">"
        "<img src='/vendor/brand/%s?v=%s' alt='' "
        "style=\"width:16px;height:16px;border-radius:3px\" "
        "onerror=\"this.style.display='none'\" />"
        "<label style=\"display:inline-flex;align-items:center;gap:4px;"
        "white-space:nowrap\">Steward "
        "<select id='stewardSelect' style=\"background:var(--surface);"
        "color:var(--text);border:1px solid var(--border);border-radius:6px;"
        "padding:2px 6px;font-size:11px;cursor:pointer\">%s</select>"
        "</label>"
        "<span id='stewardStatus' style=\"font-size:10px;opacity:.7\"></span>"
        "</div>"
    ) % (desc, seal_icon, BUILD_ID, "".join(opts))
    # Self-contained script (dashboard conventions: X-Anchor-Token on POST;
    # spaced braces — never consecutive `{{`/`}}` in raw JS).
    script = r"""
<script>
(function () {
  function tok() {
    try { return localStorage.getItem('anchor_token') || ''; }
    catch (e) { return ''; }
  }
  function setStatus(m) {
    var el = document.getElementById('stewardStatus');
    if (el) el.textContent = m || '';
  }
  document.addEventListener('DOMContentLoaded', function () {
    var sel = document.getElementById('stewardSelect');
    if (!sel) return;
    sel.addEventListener('change', function () {
      setStatus('saving…');
      var headers = { 'Content-Type': 'application/json' };
      var t = tok();
      if (t) headers['X-Anchor-Token'] = t;
      fetch('/api/settings', {
        method: 'POST', headers: headers,
        body: JSON.stringify({ steward_type: sel.value })
      }).then(function (r) { return r.json(); })
        .then(function (d) {
          if (d && d.ok) { setStatus('✓'); location.reload(); }
          else { setStatus((d && d.error) || 'failed'); }
        })
        .catch(function () { setStatus('failed'); });
    });
  });
})();
</script>
"""
    return html + script


def render_model_prefs_controls() -> str:
    """Compact Default-terminal / Coding / Review family selects for the home header.

    Loads current prefs via GET ``/api/settings`` (token from localStorage, same
    pattern as other dashboard token-gated reads) and POSTs on change. Dark-theme
    compact styling; pure HTML + a small self-contained script (no consecutive
    ``{{``/``}}`` so f-string-leakage tests stay clean).
    """
    # Server-side initial values so the selects are correct before the fetch
    # returns (and when auth is off / settings unreachable).
    try:
        s = _aset.load_settings()
    except Exception:
        s = dict(_aset.DEFAULTS)
    dcli = html_lib.escape(str(s.get("default_cli") or "grok"), quote=True)
    ccode = html_lib.escape(str(s.get("coding_family") or "claude"), quote=True)
    rcode = html_lib.escape(str(s.get("review_family") or "gemini"), quote=True)

    def _opts(selected: str) -> str:
        parts = []
        for val, lab in (("claude", "Claude"), ("gemini", "Gemini"),
                         ("grok", "Grok")):
            sel = " selected" if val == selected else ""
            parts.append("<option value='%s'%s>%s</option>" % (val, sel, lab))
        return "".join(parts)

    style = (
        "display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap;"
        "font-size:11px;color:var(--text-dim)"
    )
    sel_style = (
        "background:var(--surface);color:var(--text);border:1px solid var(--border);"
        "border-radius:6px;padding:2px 6px;font-size:11px;cursor:pointer"
    )
    lab_style = "display:inline-flex;align-items:center;gap:4px;white-space:nowrap"
    html = (
        "<div id='modelPrefs' class='model-prefs' style=\"%s\" "
        "title='Interactive default terminal + coding/review model families'>"
        "<label style=\"%s\">Default terminal "
        "<select id='mpDefaultCli' data-key='default_cli' style=\"%s\">%s</select>"
        "</label>"
        "<label style=\"%s\">Coding "
        "<select id='mpCoding' data-key='coding_family' style=\"%s\">%s</select>"
        "</label>"
        "<label style=\"%s\">Review "
        "<select id='mpReview' data-key='review_family' style=\"%s\">%s</select>"
        "</label>"
        "<span id='mpStatus' style=\"font-size:10px;opacity:.7\"></span>"
        "</div>"
    ) % (style, lab_style, sel_style, _opts(dcli),
         lab_style, sel_style, _opts(ccode),
         lab_style, sel_style, _opts(rcode))

    # Self-contained script: load prefs on DOMContentLoaded; POST on change.
    # Uses X-Anchor-Token for POST and ?token= for GET (dashboard convention).
    # NEVER emit consecutive `{{` or `}}` — dashboard f-string-leakage tests
    # treat those as accidental Python f-string escapes. Always space braces.
    script = r"""
<script>
(function () {
  function tok() {
    try { return localStorage.getItem('anchor_token') || ''; }
    catch (e) { return ''; }
  }
  function tq() {
    var t = tok();
    return t ? ('?token=' + encodeURIComponent(t)) : '';
  }
  function setStatus(m) {
    var el = document.getElementById('mpStatus');
    if (el) el.textContent = m || '';
  }
  function apply(d) {
    if (!d) return;
    var map = {
      default_cli: 'mpDefaultCli',
      coding_family: 'mpCoding',
      review_family: 'mpReview'
    };
    Object.keys(map).forEach(function (k) {
      var el = document.getElementById(map[k]);
      if (el && d[k]) el.value = d[k];
    });
    if (d.default_cli) window.ANCHOR_DEFAULT_CLI = d.default_cli;
    if (d.coding_family) window.ANCHOR_CODING_FAMILY = d.coding_family;
    if (d.review_family) window.ANCHOR_REVIEW_FAMILY = d.review_family;
  }
  function load() {
    var opts = { cache: 'no-store', headers: { Accept: 'application/json' } };
    fetch('/api/settings' + tq(), opts)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) { if (d && d.ok) apply(d); })
      .catch(function () { });
  }
  function save(el) {
    var key = el.getAttribute('data-key');
    if (!key) return;
    var body = Object.create(null);
    body[key] = el.value;
    setStatus('saving…');
    var h = {
      'Content-Type': 'application/json',
      Accept: 'application/json'
    };
    var t = tok();
    if (t) h['X-Anchor-Token'] = t;
    var opts = { method: 'POST', headers: h, body: JSON.stringify(body) };
    fetch('/api/settings', opts)
      .then(function (r) { return r.json(); })
      .then(function (d) {
        if (d && d.ok) {
          apply(d);
          setStatus('saved');
          setTimeout(function () { setStatus(''); }, 1200);
        } else {
          setStatus((d && d.error) || 'error');
        }
      })
      .catch(function () { setStatus('error'); });
  }
  function wire() {
    ['mpDefaultCli', 'mpCoding', 'mpReview'].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('change', function () { save(el); });
    });
    load();
  }
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', wire);
  } else {
    wire();
  }
})();
</script>
""".strip()
    # Defense-in-depth: if any consecutive brace pair snuck in, space it.
    while "{{" in script:
        script = script.replace("{{", "{ {")
    while "}}" in script:
        script = script.replace("}}", "} }")
    return html + script


# ANCHOR[rearch]: RENDER_PROJECT_WINDOW — structural anchor (W1); keep UNIQUE,
# keep directly above the def. The anchor-freshness gate (tools/anchors.py)
# re-locates this before every extraction wave — no line numbers anywhere.
def render_project_window_html(project_id: str) -> str:
    """Render the per-project "Project Cockpit" (Paradigm 2) for ``/project/<id>``.

    A 5-column Paradigm-2 lane grid (``.p2lanes`` → Research|Planning|Build|
    Deliverables|Grass) of clean status-light TILES (most-recent session per lane
    + a "previous sessions" expander; Deliverables = launch-by-type tiles; Grass =
    idea board). Clicking ANY tile (live OR historical) opens an inline expanding
    panel in ``#panelStack`` with a split summary on top (materials + doc-role
    links) and, below, a live xterm terminal for running sessions or a read-only
    note for done/historical ones. Plus the lifecycle header with the cost/tokens/
    time rollup. Returns a standalone HTML page; all engine/user content is
    HTML-escaped (XSS-safe).
    """
    entry = _rnd.get_project(project_id)
    if entry is None:
        return ("<!doctype html><html><head><meta charset='utf-8'>"
                "<title>Project not found</title></head><body>"
                "<h1>Project not found</h1>"
                f"<p>No R&amp;D project with id "
                f"{html_lib.escape(project_id)}.</p>"
                "<p><a href=\"/\" target=\"_top\">&larr; Back to dashboard</a></p>"
                "</body></html>")
        # Surface path-missing on read.
        eff = _rnd.list_projects()
        for e in eff:
            if e["id"] == project_id:
                entry = e
                break
    inst = open_project_instance(project_id)
    folder_raw = entry.get("folder_path", "")
    name = html_lib.escape(entry.get("name", ""))
    folder = html_lib.escape(folder_raw)
    state_raw = entry.get("state", "active")
    state = html_lib.escape(state_raw)
    pr = entry.get("priority", 2)
    pid_attr = html_lib.escape(project_id, quote=True)
    notes_raw = entry.get("notes", "") or ""
    notes_attr = html_lib.escape(notes_raw, quote=True)
    notes_esc = html_lib.escape(notes_raw)
    blurb_raw = entry.get("blurb", "") or ""
    if not blurb_raw.strip():
        try:
            seeded = _rnd.seed_blurb(project_id)
            if seeded:
                blurb_raw = seeded.get("blurb", "") or ""
        except Exception:
            pass
    blurb_attr = html_lib.escape(blurb_raw, quote=True)
    blurb_esc = html_lib.escape(_summarizer.short_summary_text(blurb_raw))
    # v5 Wave 3: the project's cached OBJECTIVE summary (read-only — NEVER runs
    # the model on the render path). Shown in the header as the "objective" line;
    # falls back to the blurb when no summary is cached yet.
    objective_raw = ""
    try:
        cached = _summarizer.load_cached_project(folder_raw, project_id)
        if cached:
            # v7 Wave 1: clean, capped plain-text objective line (strip
            # markdown/decorative glyphs) for the project-window header.
            objective_raw = _summarizer.short_summary_text(
                (cached.get("summary_text") or "").strip())
    except Exception:
        objective_raw = ""
    objective_esc = html_lib.escape(objective_raw)
    is_active = state_raw in ("active", "path-missing")
    p1on = " rnd-pr-on" if pr == 1 else ""
    p2on = " rnd-pr-on" if pr == 2 else ""
    
    files_id = f"upload_files_{project_id}"
    folder_id = f"upload_folder_{project_id}"
    # Destination name for the upload success alert; injected as a JS global so we
    # avoid escaping pitfalls in inline event-handler attributes. The `</`->`<\/`
    # replacement keeps a project name containing "</script>" from breaking out.
    _upload_name_js = json.dumps(entry.get("name", "")).replace("</", "<\\/")
    upload_btn = (
        "<div class='upload-container'>"
        f"<div class='upload-dropzone' ondragover='handleUploadDragOver(event)' ondragleave='handleUploadDragLeave(event)' ondrop=\"handleUploadDrop(event, '{pid_attr}')\" title='Drag files or a folder here to upload'>"
        f"<span>&#8681; Drop files &amp; folders here to upload (any mix)</span>"
        "</div>"
        "<div class='upload-browse-wrap'>"
        f"<button type='button' class='btn-browse' onclick=\"document.getElementById('{files_id}').click()\" title='Open your file explorer — shift/ctrl-click to select multiple files (drag a folder onto the drop zone above for whole folders)'>&#8681; Browse</button>"
        f"<input type='file' id='{files_id}' style='display:none' multiple onchange=\"handleGlobalUpload('{files_id}', '{pid_attr}')\" />"
        f"<input type='file' id='{folder_id}' style='display:none' webkitdirectory onchange=\"handleGlobalUpload('{folder_id}', '{pid_attr}')\" />"
        "</div>"
        f"<script>window._anchorUploadName = {_upload_name_js};</script>"
        "</div>"
    )

    # Lifecycle header actions (all send the auth token via _postJson in the JS).
    rescan_btn = (f"<button class='rnd-mini' onclick=\"rndRescan('{pid_attr}')\" "
                  f"title='Re-scan the folder for trio artifacts'>Rescan</button>")
    # Tidy-Idy repo-hygiene launcher — icon-only, pinned to the tile's top-right
    # corner (its own @@tidy_btn@@ slot; no longer inline in the lifecycle row).
    tidy_btn = (
        f"<button class='tidy-corner' onclick=\"tidyIdyRun()\" "
        f"title='Run Tidy-Idy repo hygiene on this project'>"
        f"<img src='/vendor/brand/tidy-idy-icon.jpg?v={BUILD_ID}' alt='Tidy-Idy'></button>")
    # The file-drop window (upload_btn) and the tidy icon are now their own header
    # slots (right side / top-right corner), so the lifecycle row holds only the
    # remaining actions.
    if is_active:
        lifecycle = (
            f"<button class='rnd-mini{p1on}' onclick=\"rndSetPriority('{pid_attr}',1)\" title='Priority 1'>P1</button>"
            f"<button class='rnd-mini{p2on}' onclick=\"rndSetPriority('{pid_attr}',2)\" title='Priority 2'>P2</button>"
            f"{rescan_btn}"
            f"<button class='rnd-mini' onclick=\"rndArchive('{pid_attr}')\">Archive</button>"
            f"<button class='rnd-mini rnd-danger' onclick=\"rndRetire('{pid_attr}')\">Retire</button>"
        )
    else:
        lifecycle = (
            f"<button class='rnd-mini rnd-accent' onclick=\"rndReactivate('{pid_attr}')\">Reactivate</button>"
            f"{rescan_btn}"
        )
    # Wave 8: if this project's folder IS an Anchor checkout (has anchor_gui.py),
    # pin it as the runnable deliverable so the Deliverables LANE shows it as a
    # launch-by-type tile. Idempotent (content-addressed); best-effort. (The loose
    # bottom "Deliverables / Pinned" section is gone — deliverables are the lane.)
    # MUST run BEFORE _render_kanban_html so the freshly-pinned deliverable shows
    # in the Deliverables lane on THIS render (not only the next one).
    try:
        if (Path(folder_raw) / _preview.DEFAULT_TARGET).is_file():
            ensure_anchor_deliverable(folder_raw, project_id)
    except Exception:
        pass
    # v5 Wave 4: backfill — scan this project's BUILD sessions and auto-pin any
    # unambiguously-resolved deliverable so it appears in the Deliverables lane.
    # Idempotent (content-addressed pins); ambiguous/none left unpinned (never
    # fabricated). Best-effort: a failure never breaks the window render. Runs
    # BEFORE the kanban render so the auto-pinned deliverable surfaces this render.
    try:
        _deliv.backfill_build_deliverables(folder_raw, project_id)
    except Exception:
        pass
    # v12 Wave 2: the Layout-D static skeleton replaces the 5-col .p2lanes board
    # (driven by the EXISTING data; the bottom dock + live wiring arrive in W10).
    kanban = _render_layoutd_html(folder_raw, project_id)
    dock_chrome = _render_layoutd_dock_html()
    status = render_status_line_html(project_id)
    header_rollup = render_header_rollup_html(project_id)
    tasks_html = render_project_tasks_html(project_id)
    # v10 Wave 7: the Boneyard panel, rendered ONCE as a hidden template the panel
    # manager (openBoneyard) clones into #panelStack — same idiom as the grass
    # workbench template.
    boneyard_tpl = (
        "<div id='boneyardTpl' style='display:none'>"
        + _render_boneyard_panel(project_id)
        + "</div>"
    )
    pid_js = json.dumps(project_id)
    _stew_ui = _steward_ui()  # persona livery for the seal button + boot global
    back_link_normal = '<p><a href="/" target="_top">&larr; Back to dashboard</a></p>'
    # ── rearch W4 (C1 increment 1): the project-window APP-JS block ─────────
    # Chosen by the `frontend` pillar off-switch flag. EMBEDDED (the default)
    # is the pre-wave path, byte-identical: the raw `_PROJECT_WINDOW_JS`
    # string inline plus the legacy `var` globals. STATIC serves the SAME
    # bytes from the checked-in `static/project-window.js` (byte-parity-gated
    # mirror of the string) via the traversal-safe static route with a
    # content-hash `?v=`, and the ONLY server→client state channel is the
    # versioned ANCHOR_BOOT bootstrap JSON — the legacy globals are derived
    # from it client-side (`_PW_BOOT_GLOBALS_JS`). The static branch is built
    # by PLAIN CONCATENATION (zero new f-string interpolations) and the
    # embedded branch's three legacy `var` interpolations simply moved here
    # from the return expression — same function, so the W1 census counts for
    # this render surface are undisturbed.
    if _static_frontend_enabled():
        pw_app_js_block = (
            "<script>\n"
            + anchor_boot_script(project_window_boot_extra(project_id)) + "\n"
            + _PW_BOOT_GLOBALS_JS +
            "</script>"
            "<script src='" + STATIC_URL_PREFIX + "/"
            + PROJECT_WINDOW_JS_ASSET + "?v="
            + static_asset_version(PROJECT_WINDOW_JS_ASSET)
            + "'></script>"
        )
    else:
        try:
            _pw_prefs = _aset.load_settings()
        except Exception:
            _pw_prefs = dict(_aset.DEFAULTS)
        _pw_dcli = json.dumps(_pw_prefs.get("default_cli") or "grok")
        _pw_cfam = json.dumps(_pw_prefs.get("coding_family") or "claude")
        _pw_rfam = json.dumps(_pw_prefs.get("review_family") or "gemini")
        pw_app_js_block = (
            "<script>\n"
            f"var PROJECT_ID = {pid_js};\n"
            # v10 Wave 5 (DEFECT-2 fix): the [grass-dev] label marker, injected
            # from the single Python constant so the JS top-strip filter can't
            # drift from ``effort_history.is_grass_dev_label``.
            f"var GRASS_DEV_LABEL_PREFIX = {json.dumps(_eh.GRASS_DEV_LABEL_PREFIX)};\n"
            f"window.ANCHOR_AUTH_REQUIRED = {'true' if _paths.expected_token() else 'false'};\n"
            f"window.ANCHOR_DEFAULT_CLI = {_pw_dcli};\n"
            f"window.ANCHOR_CODING_FAMILY = {_pw_cfam};\n"
            f"window.ANCHOR_REVIEW_FAMILY = {_pw_rfam};\n"
            # W2 contract shim: the versioned bootstrap (build id). Embedded by
            # PLAIN CONCATENATION — not an f-string interpolation — so the W1
            # census counts for this render surface are undisturbed.
            + anchor_boot_script(project_window_boot_extra(project_id)) + "\n"
            + _PROJECT_WINDOW_JS +
            "</script>"
        )
    # ── rearch W5 (C1 increment 2): the shell-CSS block ─────────────────────
    # Chosen by the SAME `frontend` pillar flag as the W4 app-JS block above
    # (one flag, one revert — no new flag). EMBEDDED (the default) inlines the
    # full stylesheet — the pre-wave emission, byte-identical. STATIC swaps it
    # for the checked-in `static/project-window.css` (the byte-parity-gated
    # mirror of `_PW_SHELL_CSS`) via the traversal-safe static route with a
    # content-hash `?v=` — ONLY when the minted file exists; a missing mirror
    # falls back to the in-source inline twin (the same fallback contract as
    # `_pw_shell_template`: the page must never reference a 404 stylesheet).
    # Built by PLAIN CONCATENATION (zero new f-string interpolations — census
    # hygiene, exactly like the W4 block).
    shell_css_ver = (static_asset_version(PROJECT_WINDOW_CSS_ASSET)
                     if _static_frontend_enabled() else "missing")
    if shell_css_ver != "missing":
        shell_css_block = (
            "<link rel='stylesheet' href='" + STATIC_URL_PREFIX + "/"
            + PROJECT_WINDOW_CSS_ASSET + "?v=" + shell_css_ver + "'>"
        )
    else:
        shell_css_block = "<style>" + _PW_SHELL_CSS + "</style>"
    # ── rearch W5: the include-layer slot values ─────────────────────────────
    # The C1-amendment blocks: conditional MARKUP computed server-side and
    # injected whole into the ``@@slot@@`` template (empty string when the
    # feature is absent — they cannot ride ANCHOR_BOOT). Each block keeps its
    # exact pre-wave bytes.
    # ── Project OBJECTIVE (v5 Wave 3 — cached, validated; read-only) ──
    objective_block = (
        f"<div class='proj-objective' data-objective='1' "
        f"style='padding:8px 18px;border-bottom:1px solid var(--border);"
        f"font-size:13px;color:var(--text)'>"
        f"<b style='color:var(--accent)'>Objective:</b> {objective_esc}</div>"
        if objective_raw else "")
    # ── Project blurb ("what this project is"; click 'Blurb' above to edit) ──
    blurb_block = (
        f"<div class='rnd-blurb' data-blurb='{blurb_attr}' "
        f"style='padding:8px 18px;border-bottom:1px solid var(--border);"
        f"font-size:13px'>{blurb_esc}</div>" if blurb_raw.strip() else "")
    # ── Project notes (like a task's Notes; click 'Notes' above to edit) ──
    notes_block = (
        f"<div style='padding:8px 18px;border-bottom:1px solid var(--border);"
        f"font-size:12.5px;color:var(--text-dim);white-space:pre-wrap'>"
        f"&#128221; {notes_esc}</div>" if notes_raw.strip() else "")
    slots = {
        "name": name,
        "xterm_prefix": XTERM_URL_PREFIX,
        "shell_css": shell_css_block,
        "back_link": "" if project_id == "__dashboard__" else back_link_normal,
        "notes_attr": notes_attr,
        "blurb_attr": blurb_attr,
        "folder": folder,
        "header_rollup": header_rollup,
        "pr": str(pr),
        "active_cls": " active" if is_active else "",
        "state": state,
        "model_flex_badge": render_model_flex_badge(),
        "token_display": "inline-block" if _paths.expected_token() else "none",
        "lifecycle": lifecycle,
        "upload_btn": upload_btn,
        "tidy_btn": tidy_btn,
        "objective_block": objective_block,
        "blurb_block": blurb_block,
        "notes_block": notes_block,
        "status_line": status,
        "kanban": kanban,
        "dock_chrome": dock_chrome,
        "boneyard_tpl": boneyard_tpl,
        "tasks_html": tasks_html,
        "build_id": html_lib.escape(BUILD_ID),
        "instance_id": html_lib.escape(inst["instance_id"]),
        "app_js": pw_app_js_block,
        "cache_bust": cache_bust_script(),
        # Steward persona livery (2026-07-30): the seal button follows the
        # active persona (icon + name + label), and window.ANCHOR_STEWARD is
        # injected BEFORE the app JS so every chamber/overlay display string
        # resolves through the same persona. (% formatting on purpose — the
        # W1 interpolation census for this render surface stays undisturbed.)
        "steward_label": html_lib.escape(_stew_ui["label"], quote=True),
        "steward_seal_src": html_lib.escape(
            "/vendor/brand/%s?v=%s" % (_stew_ui["seal"], BUILD_ID), quote=True),
        "steward_seal_name": html_lib.escape(_stew_ui["seal_name"]),
        "steward_boot": (
            "<script>window.ANCHOR_STEWARD = %s;</script>" % json.dumps({
                "key": _stew_ui["key"],
                "label": _stew_ui["label"],
                "seal_src": "/vendor/brand/%s?v=%s" % (_stew_ui["seal"],
                                                       BUILD_ID),
                "high_seat_src": "/vendor/brand/%s?v=%s" % (
                    _stew_ui["high_seat"], BUILD_ID),
                "seal_name": _stew_ui["seal_name"],
                "high_seat_name": _stew_ui["high_seat_name"],
            })),
    }
    # W5: the whole document shell is ONE ``@@slot@@`` template fill — the
    # static path fills the template read from the static FILE; a drifted
    # file (unknown placeholder) falls back to the byte-identical in-source
    # twin so the window renders, never a 500 (the gate catches the drift).
    tmpl = _pw_shell_template()
    try:
        return _pw_fill(tmpl, slots)
    except Exception:
        if tmpl is not _PW_SHELL_TMPL:
            return _pw_fill(_PW_SHELL_TMPL, slots)
        raise


# The project-window shell STYLESHEET (rearch W5 · C1 increment 2): the whole
# <style> body as ONE plain module-level string (zero interpolations — plain
# single-brace CSS, implicit literal concatenation), minted verbatim to
# `static/project-window.css` by `tools/extract_project_window_shell.py`.
# The embedded (default) render path inlines THIS string; the static path
# serves the minted file instead — the W5 byte-parity gate holds the two
# byte-identical, so this string stays the single source of truth until W6.
# ANCHOR[rearch]: PW_SHELL_CSS — structural anchor (W5); keep UNIQUE, keep
# directly above the assignment (the shell extractor re-locates it fresh and
# refuses a stale/ambiguous anchor, exactly like the census).
_PW_SHELL_CSS = (STATIC_DIR / PROJECT_WINDOW_CSS_ASSET).read_text(encoding="utf-8")  # C1: extracted verbatim to static/project-window.css (byte-identical)


# The project-window HTML shell TEMPLATE (rearch W5 · C1 increment 2): the
# whole document as ONE plain module-level string whose ONLY dynamic points
# are named ``@@slot@@`` placeholders (the C1-amendment include layer —
# markup-emitting values are computed server-side in the render and injected
# whole; scalar data/flags could not carry markup through ANCHOR_BOOT).
# Filled in ONE pass by `_pw_fill` (slot values are never re-scanned).
# Minted verbatim to `static/project-window.html` by
# `tools/extract_project_window_shell.py`; the embedded (default) path fills
# THIS string — the byte-identical pre-wave emission — while the static path
# fills the minted file. Single source of truth until W6.
# ANCHOR[rearch]: PW_SHELL_TMPL — structural anchor (W5); keep UNIQUE, keep
# directly above the assignment (the shell extractor re-locates it fresh).
_PW_SHELL_TMPL = (STATIC_DIR / PROJECT_WINDOW_SHELL_ASSET).read_text(encoding="utf-8")  # C1: extracted verbatim to static/project-window.html (byte-identical)


# JS for the v4.1 "Project Cockpit" (Paradigm-2). Drives ONLY: the inline
# expanding panel stack (openPanel/minimize/kill + the xterm transport for live
# sessions, a read-only note for historical ones), the per-panel engine toggle
# (term_set_engine), the lane-tile click (laneTileClick → openPanel), the lane
# launchers (newTermSession → term_start), the grass idea board (add/promote),
# type-aware deliverable launch, the lifecycle header, and the header rollup
# toggle. NO console drawer / live-terminals bar / loose rollup or deliverables
# section remain. Plain RAW string (NOT an f-string), so braces are single. No
# template interpolation here beyond the PROJECT_ID var injected above.
# ANCHOR[rearch]: PROJECT_WINDOW_JS — structural anchor (W1); keep UNIQUE, keep
# directly above the assignment. Census contract: this stays a PLAIN raw
# string with ZERO interpolations (tools/interpolation_census.py fails loudly
# if it ever becomes an f-string).
_PROJECT_WINDOW_JS = (STATIC_DIR / PROJECT_WINDOW_JS_ASSET).read_text(encoding="utf-8")  # C1: extracted verbatim to static/project-window.js (byte-identical)


def _fmt_cost(rollup: dict) -> str:
    """Render a one-line cost/time/tokens summary from a rollup dict."""
    cost = rollup.get("total_cost_usd", 0.0) or 0.0
    dur_ms = rollup.get("duration_ms", 0) or 0
    toks = rollup.get("total_tokens", 0) or 0
    secs = dur_ms / 1000.0
    return (f"${cost:.4f} · {secs:.1f}s · {toks:,} tok "
            f"({rollup.get('effort_count', 0)} effort"
            f"{'s' if rollup.get('effort_count', 0) != 1 else ''})")


def render_cost_rollup_html(project_id: str, folder_path: str) -> str:
    """Render the per-project cost/time/tokens rollup (tile + dashboard, Wave 7).

    Shows the project total plus a per-lane breakdown. Best-effort: a project
    with no efforts shows zeros and never crashes.
    """
    try:
        roll = _eh.project_rollup(project_id, folder_path)
    except Exception:
        return ""
    total = roll.get("total", {})
    lanes = roll.get("lanes", {})
    rows = []
    for lane in _eh.ROLLUP_LANES:
        lr = lanes.get(lane, {})
        if not lr.get("effort_count"):
            continue
        rows.append(
            f"<div class='rnd-lane'>{html_lib.escape(lane)}: "
            f"{html_lib.escape(_fmt_cost(lr))}</div>"
        )
    breakdown = ("<div class='rnd-status-line'>" + "".join(rows) + "</div>"
                 if rows else "")
    n_imp = int(total.get("discovered_count", 0) or 0)
    imported_bit = (f" · <span class='rnd-imported'>{n_imp} imported</span>"
                    if n_imp else "")
    return (
        "<h2>Cost rollup</h2>"
        f"<p style='font-size:15px'><strong>Total:</strong> "
        f"{html_lib.escape(_fmt_cost(total))}{imported_bit}</p>"
        f"{breakdown}"
    )


# ── Task ↔ project link (Wave 9 — activates the parsed Project: field) ──────

def project_tasks(project_id: str) -> list:
    """Return every active task whose ``Project: <id>`` field matches.

    ``gather_all()`` already parses each task's ``project`` field (Wave 3) and
    deduplicates; Wave 9 simply FILTERS on it. This is the data behind the
    project-tasks view (AC2). Returns the matching task dicts (order preserved).
    """
    pid = (project_id or "").strip()
    if not pid:
        return []
    _projects, tasks, _inbox = gather_all()
    return [t for t in tasks if (t.get("project") or "").strip() == pid]


def render_project_tasks_html(project_id: str) -> str:
    """Render the linked-tasks strip inside the project window (v2 Wave 4 / §G).

    Surfaces the existing ``link_task`` capability: lists every active task whose
    ``Project: <id>`` matches, each with an Unlink affordance, plus a "Link task"
    button that calls the existing ``/api/rnd/link_task`` endpoint. Replaces the
    old dead-end "no tasks linked yet" message with a working strip.
    """
    pid_attr = html_lib.escape(project_id, quote=True)
    link_btn = (f"<button class='rnd-mini' data-project=\"{pid_attr}\" "
                f"onclick=\"rndLinkTask(this)\" "
                f"title='Link an existing task to this project'>+ Link task"
                f"</button>")
    header = (f"<h2 style='display:flex;align-items:center;gap:10px'>Tasks "
              f"{link_btn}</h2>")
    tasks = project_tasks(project_id)
    if not tasks:
        return (header + "<p class='rnd-empty-tasks' style='color:#8a90a2'>"
                "No tasks linked to this project yet. Use "
                "<strong>+ Link task</strong> above (or "
                "<code>anchor.py link \"task\" --project &lt;id&gt;</code>).</p>")
    rows = []
    for t in tasks:
        mark = "✓" if t.get("done") else "○"
        txt_raw = t.get("text", "")
        txt = html_lib.escape(txt_raw)
        txt_attr = html_lib.escape(txt_raw, quote=True)
        dom = html_lib.escape(t.get("domain", ""))
        pr = t.get("priority", 2)
        # Task identity rides via data- attributes (entity-decoded by the
        # browser), NOT as an inline JS string arg — so text with apostrophes,
        # quotes, &, <, > round-trips verbatim to /api/rnd/link_task.
        unlink = (f"<button class='rnd-mini rnd-unlink' "
                  f"data-task=\"{txt_attr}\" data-project=\"{pid_attr}\" "
                  f"onclick=\"rndUnlinkTask(this)\" "
                  f"title='Unlink this task'>Unlink</button>")
        rows.append(
            f"<li class='linked-task' style='display:flex;align-items:center;"
            f"gap:8px;margin-bottom:5px'>"
            f"<span style='color:#6c9cfc'>{mark}</span> {txt} "
            f"<span style='color:#8a90a2;font-size:12px'>"
            f"(P{pr} · {dom})</span>"
            f"<span style='margin-left:auto'>{unlink}</span></li>"
        )
    return (header + "<ul style='list-style:none;padding:0'>"
            + "".join(rows) + "</ul>")


def ensure_anchor_deliverable(folder_path: str, project_id: str):
    """Pin ``anchor_gui.py`` as the project's runnable Anchor deliverable (Wave 8).

    Idempotent: ``deliverables.pin_deliverable`` is content-addressed by path, so
    pinning the same file twice produces no duplicate. ``anchor_gui.py`` is a
    long-running SERVER (not a run-to-completion program), so its run is the
    ephemeral preview (``preview_server``), not the program contract — it is
    pinned with type ``program`` only so it surfaces in the Deliverables lane.
    Best-effort: a pin failure never breaks the window render.

    Pin-if-absent: this runs on EVERY ``GET /project/<id>`` render, and
    ``pin_deliverable`` → ``record_effort`` unconditionally rewrites the pointer
    JSON under ``WRITE_LOCK``. To avoid needless disk-write/lock churn on this
    hot path, skip the pin entirely when ``anchor_gui.py`` is already pinned for
    this project; the first render still pins. The pinned content/id is
    unchanged (content-addressed by path).
    """
    try:
        target = _preview.DEFAULT_TARGET
        for rec in _deliv.list_pinned_deliverables(folder_path, project_id):
            if (rec.get("artifact_path") or "") == target:
                return rec  # already pinned — no write, no lock contention
        return _deliv.pin_deliverable(
            folder_path, project_id, target,
            name=target, dtype=_deliv.TYPE_PROGRAM,
            description="Anchor dashboard web app (run as an ephemeral preview)")
    except Exception:
        return None


def render_deliverables_html(project_id: str, folder_path: str) -> str:
    """Render the project's deliverables: pinned deliverables (with Run/Stop) +
    deliverable run-status records (Wave 9 AC1 + v3 Wave 8 ephemeral preview).

    The pinned ``anchor_gui.py`` deliverable gets a **Run** action that starts an
    ephemeral preview on a free port (≠8777) and opens it in a new tab, plus a
    **Stop** that reaps it — token-aware via the project-window JS.
    """
    pinned = []
    try:
        pinned = _deliv.list_pinned_deliverables(folder_path, project_id)
    except Exception:
        pinned = []
    try:
        records = _deliv.list_status(folder_path, project_id)
    except Exception:
        records = []

    out = []

    # Pinned deliverables with Run/Stop (the runnable Anchor deliverable).
    if pinned:
        # v4 Wave 7: the launch action ADAPTS to the deliverable type — the
        # per-type affordance label mirrors the "📦 Deliverable" mockup card.
        _launch_label = {
            _deliv.TYPE_SERVICE: "▶ launch in window / pull up",
            _deliv.TYPE_PROGRAM: "▶ run in a window",
            _deliv.TYPE_SCRIPT: "▶ run in a window",
            _deliv.TYPE_SKILL: "✓ verify status",
            _deliv.TYPE_TOOL: "✓ verify status",
            _deliv.TYPE_DOC: "📖 open rendered",
        }
        items = []
        for r in pinned:
            name = html_lib.escape(
                r.get("title") or r.get("artifact_path") or "")
            rel = r.get("artifact_path", "") or ""
            raw_type = (r.get("deliverable_type", "") or "").strip().lower()
            if raw_type not in _deliv.VALID_TYPES:
                raw_type = _deliv.infer_type(rel)
            dtype = html_lib.escape(raw_type)
            did = r.get("job_id", "") or ""
            rel_attr = html_lib.escape(rel, quote=True)
            did_attr = html_lib.escape(did, quote=True)
            label = html_lib.escape(_launch_label.get(raw_type, "▶ launch"))
            items.append(
                f"<li class='deliv-pinned' data-deliv=\"{rel_attr}\" "
                f"data-deliv-id=\"{did_attr}\" data-deliv-type=\"{dtype}\">"
                f"<span class='deliv-name'>{name}</span> "
                f"<span style='color:#8a90a2;font-size:12px'>[{dtype}]</span> "
                f"<button class='deliv-run' "
                f"onclick=\"launchDeliverable(this)\">{label}</button> "
                f"<button class='deliv-stop' "
                f"onclick=\"stopDeliverable(this)\" style='display:none'>"
                f"Stop</button> "
                f"<span class='deliv-msg' style='color:#8a90a2;"
                f"font-size:12px'></span></li>"
            )
        out.append("<h3 style='margin:8px 0 4px;font-size:14px;color:#aeb4c2'>"
                   "Pinned</h3>")
        out.append("<ul style='list-style:none;padding:0'>"
                   + "".join(items) + "</ul>")

    # Run-status records (read-only history).
    if records:
        colors = {_deliv.STATUS_SUCCESS: "#4caf78",
                  _deliv.STATUS_FAILED: "#e06c75",
                  _deliv.STATUS_TIMED_OUT: "#d6a35c"}
        rows = []
        for r in records:
            status = r.get("status", "")
            color = colors.get(status, "#8a90a2")
            name = html_lib.escape(
                r.get("name", "") or r.get("deliverable_id", ""))
            dtype = html_lib.escape(r.get("type", ""))
            rows.append(
                f"<li>{name} <span style='color:#8a90a2;font-size:12px'>"
                f"[{dtype}]</span> — <span style='color:{color}'>"
                f"{html_lib.escape(status)}</span></li>"
            )
        out.append("<h3 style='margin:8px 0 4px;font-size:14px;color:#aeb4c2'>"
                   "Run history</h3>")
        out.append("<ul style='list-style:none;padding:0'>"
                   + "".join(rows) + "</ul>")

    if not pinned and not records:
        out.append("<p style='color:#8a90a2'>No deliverables yet.</p>")
    # crucible-improve #4 (W5): wrap the deliverables in a <details> so they
    # render COLLAPSED by default (no `open` attribute); the "Deliverables"
    # heading becomes the always-visible <summary> disclosure.
    return ("<details class='deliv-collapse'>"
            "<summary class='deliv-summary'><h2 style='display:inline'>"
            "Deliverables</h2></summary>"
            + "".join(out) + "</details>")


# ── Change operations ──────────────────────────────────────────────────
#
# Every function that MUTATES a markdown or JSON file is wrapped with
# @_with_write_lock. The lock is a process-wide RLock (re-entrant), so nested
# mutators (e.g. mark_done -> log_change) acquire it safely. Under
# ThreadingHTTPServer this serializes concurrent writers so no update is lost.

import functools as _functools


def _with_write_lock(fn):
    @_functools.wraps(fn)
    def _wrapped(*args, **kwargs):
        with WRITE_LOCK:
            return fn(*args, **kwargs)
    return _wrapped


@_with_write_lock
def log_change(message):
    today = date.today().isoformat()
    now = datetime.now().strftime("%H:%M")
    LOGS_DIR.mkdir(exist_ok=True)
    log_file = LOGS_DIR / f"{today}.md"
    if not log_file.exists():
        day_name = datetime.now().strftime("%A")
        _paths.atomic_write_text(log_file, f"# {today} — {day_name}\n\n## Changes\n")
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(f"- {now} — {message}\n")
    print(f"  Logged: {now} — {message}")


@_with_write_lock
def mark_done(task_text):
    search = task_text.lower().strip()
    found = False
    for md_file in _all_md_files():
        if not md_file.exists():
            continue
        text = _read_md_text(md_file)
        new_lines = []
        changed = False
        for line in text.splitlines():
            if re.match(r'\s*-\s*\[ \]', line) and search in line.lower():
                new_lines.append(line.replace("[ ]", "[x]", 1))
                found = True
                changed = True
            else:
                new_lines.append(line)
        if changed:
            _paths.atomic_write_text(md_file, "\n".join(new_lines) + "\n")
    if found:
        log_change(f"Completed: {task_text}")
    return found


@_with_write_lock
def mark_undone(task_text):
    search = task_text.lower().strip()
    found = False
    for md_file in _all_md_files():
        if not md_file.exists():
            continue
        text = _read_md_text(md_file)
        new_lines = []
        changed = False
        for line in text.splitlines():
            if re.match(r'\s*-\s*\[[xX]\]', line) and search in line.lower():
                new_lines.append(re.sub(r'\[[xX]\]', '[ ]', line, count=1))
                found = True
                changed = True
            else:
                new_lines.append(line)
        if changed:
            _paths.atomic_write_text(md_file, "\n".join(new_lines) + "\n")
    if found:
        log_change(f"Reopened: {task_text}")
    return found


@_with_write_lock
def add_task(text, domain="academic", priority=2, energy="med", due="", notes=""):
    due_str = f" — Due: {due}" if due else ""
    notes_str = f" — Notes: {notes}" if notes else ""
    line = f"- [ ] {text} — Priority: {priority} — energy: {energy} — [{domain}]{due_str}{notes_str}"

    def _insert(filepath, section_names):
        if not filepath or not filepath.exists():
            return False
        content = _read_md_text(filepath)
        for section in section_names:
            idx = content.find(section)
            if idx >= 0:
                ns = content.find("\n##", idx + len(section))
                if ns < 0:
                    ns = len(content)
                content = content[:ns].rstrip() + "\n" + line + "\n\n" + content[ns:]
                _paths.atomic_write_text(filepath, content)
                return True
        return False

    _insert(DASHBOARD_MD, ["## Today's Priorities", "## Active Priorities"])
    if DOMAINS_DIR.exists():
        _insert(DOMAINS_DIR / f"{domain}.md", ["## Active Tasks"])

    log_change(f"Added task: {text} [{domain}] P{priority}")


@_with_write_lock
def capture_inbox(text, domain=""):
    today = date.today().isoformat()
    domain_tag = f" [{domain}]" if domain else ""
    line = f"- {today}: {text}{domain_tag}"
    if not INBOX_MD.exists():
        # Fresh/empty data dir: create a minimal inbox so the capture is never
        # silently dropped.
        _paths.atomic_write_text(INBOX_MD, "# Inbox\n\n")
    content = _read_md_text(INBOX_MD)
    content = content.rstrip() + "\n" + line + "\n"
    _paths.atomic_write_text(INBOX_MD, content)
    log_change(f"Captured: {text}")


@_with_write_lock
def link_task(task_text, project_id):
    """Link a task to an R&D project — set/maintain its ``Project: <id>`` field.

    Wave 9 activation: edits ONLY the ``Project:`` field on the first matching
    active task line, preserving every other character verbatim (byte-stable for
    untouched tasks; clean round-trip for linked ones). An empty ``project_id``
    unlinks. Mirrors ``anchor.link_task``. Returns True if a task was updated.
    """
    search = task_text.lower().strip()
    new_id = (project_id or "").strip()
    found = False
    for md_file in _all_md_files():
        if not md_file or not md_file.exists():
            continue
        text = _read_md_text(md_file)
        new_lines = []
        changed = False
        for line in text.splitlines():
            if (not found and re.match(r'\s*-\s*\[([ xX])\]', line)
                    and search in line.lower()):
                existing = re.search(r'(\s*—\s*Project:\s*)([^\s—]+)', line, re.I)
                if existing:
                    if new_id:
                        new_line = (line[:existing.start(2)] + new_id
                                    + line[existing.end(2):])
                    else:
                        new_line = line[:existing.start(1)] + line[existing.end(2):]
                else:
                    new_line = line.rstrip() + f" — Project: {new_id}" if new_id else line
                if new_line != line:
                    changed = True
                new_lines.append(new_line)
                found = True
            else:
                new_lines.append(line)
        if changed:
            _paths.atomic_write_text(md_file, "\n".join(new_lines) + "\n")
    if found:
        log_change(f"Linked task '{task_text}' to project {new_id}" if new_id
                   else f"Unlinked task '{task_text}'")
    return found


@_with_write_lock
def edit_task(old_text, new_text=None, new_priority=None, new_domain=None, new_energy=None, new_due=None, new_notes=None):
    """Edit a task's properties across all markdown files. Only changes specified fields."""
    search = old_text.lower().strip()
    found = False
    for md_file in _all_md_files():
        if not md_file or not md_file.exists():
            continue

        # Infer domain from filename: domains/family.md → "family"
        file_domain = None
        if md_file.parent == DOMAINS_DIR:
            file_domain = md_file.stem  # e.g. "family", "academic", "writing", "commercial"

        text = _read_md_text(md_file)
        new_lines = []
        changed = False
        for line in text.splitlines():
            if re.match(r'\s*-\s*\[([ xX])\]', line) and search in line.lower():
                check_m = re.match(r'(\s*-\s*\[)([ xX])(\]\s*)', line)
                if check_m:
                    prefix = check_m.group(1)
                    check_state = check_m.group(2)
                    rest = line[check_m.end():]

                    # Parse existing text (everything before the first " — ")
                    raw_rest = line[check_m.end():]
                    text_end = raw_rest.find(" — ")
                    existing_text = raw_rest[:text_end].strip(' *') if text_end >= 0 else raw_rest.strip(' *')
                    existing_priority = 2
                    existing_energy = "med"
                    existing_due = ""

                    # Domain: prefer file-inferred domain, then tag in line, then "personal"
                    existing_domain = file_domain or "personal"
                    dm = re.search(r'\[(\w+)\]', rest)
                    if dm and not file_domain:
                        existing_domain = dm.group(1).lower()

                    pm = re.search(r'Priority:\s*(\d)', rest)
                    if pm: existing_priority = int(pm.group(1))
                    em = re.search(r'energy:\s*(\w+)', rest, re.I)
                    if em: existing_energy = em.group(1).lower()
                    due_m = re.search(r'Due:\s*([\d/\-\w]+)', rest, re.I)
                    if due_m: existing_due = due_m.group(1)
                    existing_notes = ""
                    notes_m = re.search(r'Notes:\s*(.+?)(?:\s*—\s*(?:Priority|energy|Due|Project|\[)|$)', rest, re.I)
                    if not notes_m:
                        notes_m = re.search(r'Notes:\s*(.+?)$', rest, re.I)
                    if notes_m: existing_notes = notes_m.group(1).strip().rstrip(' —')
                    # Preserve the optional Project: <id> link unchanged (Wave 3).
                    existing_project = ""
                    proj_m = re.search(r'Project:\s*([^\s—]+)', rest, re.I)
                    if proj_m: existing_project = proj_m.group(1).strip()

                    # Apply only specified changes
                    t_text = new_text if new_text is not None else existing_text
                    t_priority = new_priority if new_priority is not None else existing_priority
                    t_energy = new_energy if new_energy is not None else existing_energy
                    t_domain = new_domain if new_domain is not None else existing_domain
                    t_due = new_due if new_due is not None else existing_due
                    t_notes = new_notes if new_notes is not None else existing_notes
                    due_str = f" — Due: {t_due}" if t_due else ""
                    notes_str = f" — Notes: {t_notes}" if t_notes else ""
                    project_str = f" — Project: {existing_project}" if existing_project else ""

                    new_line = f"{prefix}{check_state}] {t_text} — Priority: {t_priority} — energy: {t_energy} — [{t_domain}]{due_str}{project_str}{notes_str}"
                    new_lines.append(new_line)
                    found = True
                    changed = True
                else:
                    new_lines.append(line)
            else:
                new_lines.append(line)
        if changed:
            _paths.atomic_write_text(md_file, "\n".join(new_lines) + "\n")
    if found:
        changes = []
        if new_text and new_text != old_text:
            changes.append(f"renamed to '{new_text}'")
        if new_priority is not None:
            changes.append(f"P{new_priority}")
        if new_domain:
            changes.append(f"[{new_domain}]")
        if new_due is not None:
            changes.append(f"due {new_due}" if new_due else "due removed")
        log_change(f"Edited task '{old_text}': {', '.join(changes)}")
    return found


@_with_write_lock
def edit_project(old_name, new_name=None, new_priority=None, new_domain=None,
                 new_status=None, new_effort=None, new_due=None, new_next=None):
    """Edit a project's properties in PROJECTS.md files."""
    search = old_name.lower().strip()
    found = False

    for proj_file in [PROJECTS_MD]:
        if not proj_file or not proj_file.exists():
            continue
        text = _read_md_text(proj_file)
        lines = text.splitlines()
        new_lines = []
        in_project = False
        i = 0
        while i < len(lines):
            line = lines[i]
            h2 = re.match(r'^##\s+(.+)', line)
            if h2 and search in h2.group(1).lower():
                in_project = True
                found = True
                # Replace name if needed
                if new_name:
                    new_lines.append(f"## {new_name}")
                else:
                    new_lines.append(line)
                i += 1
                # Process key-value lines within this project section
                while i < len(lines):
                    line = lines[i]
                    # Stop at next project heading
                    if re.match(r'^##\s+', line):
                        in_project = False
                        break
                    kv = re.match(r'(\s*-\s*\*\*)(\w[\w\s]*?)(:\*\*\s*)(.*)', line)
                    if kv:
                        key = kv.group(2).strip().lower()
                        indent = kv.group(1)
                        colon = kv.group(3)
                        if key == "priority" and new_priority is not None:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_priority}")
                        elif key == "domain" and new_domain:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_domain}")
                        elif key == "status" and new_status:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_status}")
                        elif key in ("effort", "effort level") and new_effort:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_effort}")
                        elif key in ("deadline", "due") and new_due is not None:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_due}")
                        elif key.startswith("next") and new_next is not None:
                            new_lines.append(f"{indent}{kv.group(2)}{colon}{new_next}")
                        else:
                            new_lines.append(line)
                    else:
                        new_lines.append(line)
                    i += 1
                continue
            else:
                if h2:
                    in_project = False
                new_lines.append(line)
            i += 1
        _paths.atomic_write_text(proj_file, "\n".join(new_lines) + "\n")

    if found:
        changes = []
        if new_name and new_name != old_name:
            changes.append(f"renamed to '{new_name}'")
        if new_priority is not None:
            changes.append(f"P{new_priority}")
        if new_domain:
            changes.append(f"[{new_domain}]")
        if new_status:
            changes.append(f"status: {new_status}")
        if new_next is not None:
            changes.append(f"next: {new_next}")
        log_change(f"Edited project '{old_name}': {', '.join(changes)}")
    return found


def _remove_task_from_files(task_text):
    """Remove a task line from all markdown files. Returns the task dict if found."""
    search = task_text.lower().strip()
    found_task = None
    for md_file in _all_md_files():
        if not md_file or not md_file.exists():
            continue
        text = _read_md_text(md_file)
        new_lines = []
        changed = False
        for line in text.splitlines():
            if re.match(r'\s*-\s*\[([ xX])\]', line) and search in line.lower():
                # Parse the task before removing
                if not found_task:
                    tm = re.match(r'\s*-\s*\[([ xX])\]\s*\*?\*?(.*?)(?:\*?\*?\s*—\s*(.*))?$', line)
                    if tm:
                        meta = tm.group(3) or ""
                        dm = re.search(r'\[(\w+)\]', meta)
                        pm = re.search(r'Priority:\s*(\d)', meta)
                        notes_m = re.search(r'Notes:\s*(.+?)(?:\s*—\s*(?:Priority|energy|Due|\[)|$)', meta, re.I)
                        if not notes_m:
                            notes_m = re.search(r'Notes:\s*(.+?)$', meta, re.I)
                        found_task = {
                            "text": task_text,
                            "domain": dm.group(1).lower() if dm else "",
                            "priority": int(pm.group(1)) if pm else 2,
                            "notes": notes_m.group(1).strip().rstrip(' —') if notes_m else "",
                        }
                changed = True
                continue  # skip this line (remove it)
            new_lines.append(line)
        if changed:
            _paths.atomic_write_text(md_file, "\n".join(new_lines) + "\n")
    return found_task


def _append_to_archive(filepath, task_dict):
    """Append a task entry to an archive file (CANCELLED.md or SAVED_FOR_LATER.md)."""
    if not filepath:
        return
    today = date.today().isoformat()
    domain_str = f" — [{task_dict.get('domain', '')}]" if task_dict.get('domain') else ""
    priority_str = f" — P{task_dict.get('priority', 2)}"
    notes_str = f" — Notes: {task_dict['notes']}" if task_dict.get('notes') else ""
    line = f"- {today}: {task_dict['text']}{domain_str}{priority_str}{notes_str}"

    if not filepath.exists():
        _paths.atomic_write_text(filepath, f"# {filepath.stem.replace('_', ' ').title()}\n\n")
    content = _read_md_text(filepath)
    content = content.rstrip() + "\n" + line + "\n"
    _paths.atomic_write_text(filepath, content)


@_with_write_lock
def cancel_task(task_text):
    """Cancel a task: remove from active lists, add to CANCELLED.md, log it."""
    task = _remove_task_from_files(task_text)
    if task:
        _append_to_archive(CANCELLED_MD, task)
        log_change(f"Cancelled: {task_text}")
        return True
    return False


@_with_write_lock
def save_for_later(task_text):
    """Save a task for later: remove from active lists, add to SAVED_FOR_LATER.md, log it."""
    task = _remove_task_from_files(task_text)
    if task:
        _append_to_archive(SAVED_FOR_LATER_MD, task)
        log_change(f"Saved for later: {task_text}")
        return True
    return False


@_with_write_lock
def restore_task(task_text, from_archive="saved"):
    """Restore a task from an archive back to the active dashboard."""
    archive_file = SAVED_FOR_LATER_MD if from_archive == "saved" else CANCELLED_MD
    if not archive_file or not archive_file.exists():
        return False
    text = _read_md_text(archive_file)
    search = task_text.lower().strip()
    found = None
    new_lines = []
    for line in text.splitlines():
        if search in line.lower() and not found:
            # Parse the archived task
            m = re.match(r'\s*-\s*\d{4}-\d{2}-\d{2}:\s*(.*?)(?:\s*—\s*\[(\w+)\])?(?:\s*—\s*P(\d))?(?:\s*—\s*Notes:\s*(.*))?$', line)
            if m:
                found = {
                    "text": m.group(1).strip(),
                    "domain": m.group(2) or "personal",
                    "priority": int(m.group(3)) if m.group(3) else 2,
                    "notes": m.group(4).strip() if m.group(4) else "",
                }
            continue  # remove from archive
        new_lines.append(line)
    if found:
        _paths.atomic_write_text(archive_file, "\n".join(new_lines) + "\n")
        add_task(found["text"], found["domain"], found["priority"], "med", "", found["notes"])
        log_change(f"Restored from {from_archive}: {task_text}")
        return True
    return False


# ── HTML Dashboard Generation ─────────────────────────────────────────

# ANCHOR[rearch]: GENERATE_HTML — structural anchor (W1); keep UNIQUE, keep
# directly above the def. The anchor-freshness gate (tools/anchors.py)
# re-locates this before every extraction wave — no line numbers anywhere.
def generate_html(projects, tasks, inbox):
    """Generate a full standalone HTML dashboard matching the original Anchor style."""
    today_str = datetime.now().strftime("%A, %B %d, %Y")
    active = [t for t in tasks if not t["done"]]
    done_tasks = [t for t in tasks if t["done"]]
    # Whether the server requires a token (remote/exposed). Embedded as a bool so
    # the page can prompt for the token ONCE on first load — never the token value
    # itself (GET is unauthenticated; embedding the secret would leak it).
    auth_required_js = "true" if _paths.expected_token() else "false"
    # Initial visibility of the masthead 🔑 token control — shown only when the
    # server has an ANCHOR_TOKEN configured (auth on), invisible otherwise.
    auth_token_btn_display = "inline-block" if _paths.expected_token() else "none"
    # W2 contract shim: the versioned window.ANCHOR_BOOT bootstrap (build id +
    # auth flag) — a JSON literal, never the token value itself.
    anchor_boot_js = json.dumps(anchor_boot())

    # ── Health banner (W9 / SC7) ──
    # Clickable → Doctor with 1:1 issue seed (issueId, message, component,
    # lastError, suggestedChecks) + async diagnose attempt. NOT a static
    # markdown path to health_reports/*.md.
    health_banner_html = ""
    hr = latest_health_report()
    if hr is not None:
        report_date, status, _ = hr
        if "ISSUE" in status.upper() or "FAIL" in status.upper() or "ERROR" in status.upper():
            try:
                _hb_issue = _w9_build_dashboard_health_banner_issue(
                    report_date=report_date, status=status)
                health_banner_html = _w9_render_clickable_banner_html(
                    _hb_issue,
                    title="Health check found issues",
                    body=(
                        f'on {html_lib.escape(str(report_date))}. '
                        f'Click to open Doctor and diagnose this issue '
                        f'(seeded context — not a static markdown path).'
                    ),
                    style_kind="health",
                )
            except Exception:
                # Fail-soft: still show a clickable Doctor open, never only a .md path.
                health_banner_html = (
                    f'<div role="button" tabindex="0" onclick="window.open('
                    f"'/doctor?issueId=ZH_HEALTH_CHECK_ISSUES&diagnose=1'"
                    f' + (_anchorToken() ? (\'&token=\' + encodeURIComponent(_anchorToken())) : \'\'), \'_blank\')" '
                    f'style="background:#3b1f1f;border:1px solid #9b3a3a;color:#ffb3b3;'
                    f'padding:10px 14px;border-radius:6px;margin:0 0 10px 0;font-size:13px;'
                    f'cursor:pointer;" title="Open Doctor with health-check issue seed">'
                    f'<strong style="color:#ff7a7a">&#9888; Health check found issues</strong>'
                    f' on {html_lib.escape(report_date)}. Click to diagnose in Doctor.'
                    f'</div>'
                )

    # Reaper consecutive-abstain / chain-tampered health banner (W9/SC7 clickable).
    # Best-effort: never break the dashboard render over a reaper diagnostic.
    try:
        import reaper_arming as _reaper_arm
        _rb = _reaper_arm.health_banner()
        if _rb and _rb.get("tripped"):
            try:
                _rh_issue = _w9_build_reaper_health_banner_issue(_rb)
                health_banner_html += _w9_render_clickable_banner_html(
                    _rh_issue,
                    title="Reaper health",
                    body=html_lib.escape(str(_rb.get("message", ""))),
                    style_kind="reaper",
                )
            except Exception:
                health_banner_html += (
                    f'<div role="button" tabindex="0" onclick="window.open('
                    f"'/doctor?issueId=ZH_REAPER_ABSTAIN_STREAK&diagnose=1'"
                    f' + (_anchorToken() ? (\'&token=\' + encodeURIComponent(_anchorToken())) : \'\'), \'_blank\')" '
                    f'style="background:#3b2a1f;border:1px solid #9b6a3a;color:#ffd9b3;'
                    f'padding:10px 14px;border-radius:6px;margin:0 0 10px 0;font-size:13px;'
                    f'cursor:pointer;" title="Open Doctor with reaper-health issue seed">'
                    f'<strong style="color:#ffb37a">&#9888; Reaper health</strong> '
                    f'{html_lib.escape(str(_rb.get("message", "")))}'
                    f'</div>'
                )
    except Exception:
        pass

    # Domain sort order: commercial first, then academic, family, writing, personal
    domain_sort_order = {"commercial": 0, "academic": 1, "family": 2, "writing": 3, "personal": 4}
    # Energy sort order: high-energy tasks first, then med, then low
    energy_sort_order = {"high": 0, "med": 1, "medium": 1, "low": 2}
    today_iso = date.today().isoformat()

    # Top Tasks = P1 tasks + anything due today (any priority)
    # Other Tasks = everything P2+ (that isn't due today)
    # Within Top Tasks: due today first, then by domain order (commercial → academic → family → writing → personal)
    p1 = [t for t in active if t["priority"] == 1]
    due_today_non_p1 = [t for t in active if t["priority"] != 1 and t.get("due") and t["due"] <= today_iso]
    p1_sorted = sorted(p1, key=lambda t: (
        0 if t.get("due") and t["due"] <= today_iso else 1,  # due today first
        domain_sort_order.get(t["domain"], 9),
        t["text"]
    ))

    seen_top = set()
    top_tasks = []
    for t in due_today_non_p1 + p1_sorted:
        key = t["text"].lower()[:60]
        if key not in seen_top:
            seen_top.add(key)
            top_tasks.append(t)
    top_done = len([t for t in top_tasks if t["done"]])
    top_task_texts = set(t["text"].lower()[:60] for t in top_tasks)

    # P1 and P2+ projects
    p1_projects = sorted([p for p in projects if p["priority"] == 1 and p["status"] == "active"],
                         key=lambda p: (0 if p.get("due") else 1, p.get("due", ""), p["name"]))
    p2_projects = sorted([p for p in projects if p["priority"] >= 2 and p["status"] == "active"],
                         key=lambda p: (p["priority"], p["name"]))

    # P2+ tasks not already in Top Tasks (other tasks).
    # Sort: by domain (commercial → academic → family → writing → personal),
    # then by energy (high → med → low), then by priority number, then text.
    other_tasks = sorted(
        [t for t in active if t["priority"] >= 2 and t["text"].lower()[:60] not in top_task_texts],
        key=lambda t: (
            domain_sort_order.get(t["domain"], 9),
            energy_sort_order.get(t.get("energy", "med").lower(), 1),
            t["priority"],
            t["text"],
        ),
    )

    # Group by domain for sidebar
    domain_counts = {}
    for t in active:
        domain_counts[t["domain"]] = domain_counts.get(t["domain"], 0) + 1

    def esc(s):
        return html_lib.escape(str(s)).replace("'", "&#39;").replace('"', "&quot;")

    def linkify_notes(s):
        """Escape HTML, then convert URLs into clickable <a> tags."""
        escaped = html_lib.escape(str(s))
        return re.sub(
            r'(https?://[^\s<>&\'"]+)',
            r'<a href="\1" target="_blank" rel="noopener" onclick="event.stopPropagation()">\1</a>',
            escaped
        )

    def notes_popover(notes_text):
        """Build a hoverable popover element for task notes."""
        if not notes_text:
            return ""
        linked = linkify_notes(notes_text)
        return f'''<span class="notes-wrapper">
            <span class="notes-indicator">&#128203;</span>
            <div class="notes-popover">{linked}</div>
        </span>'''

    def js_safe(s):
        """Escape a string for safe use inside JS onclick='func(\"...\")' attributes."""
        import base64
        return base64.b64encode(s.encode('utf-8')).decode('ascii')

    def task_data_b64(t):
        """Base64-encode a task's full data dict for safe embedding in HTML attributes."""
        import base64
        d = {"text": t["text"], "priority": t["priority"], "domain": t["domain"],
             "energy": t.get("energy","med"), "due": t.get("due",""), "notes": t.get("notes","")}
        return base64.b64encode(json.dumps(d).encode('utf-8')).decode('ascii')

    def project_data_b64(p):
        """Base64-encode a project's full data dict for safe embedding in HTML attributes."""
        import base64
        d = {"name": p["name"], "priority": p["priority"], "domain": p["domain"],
             "status": p.get("status","active"), "effort": p.get("effort","high"),
             "due": p.get("due",""), "next": p.get("next","")}
        return base64.b64encode(json.dumps(d).encode('utf-8')).decode('ascii')

    # Domain labels and colors
    domain_labels = {
        "academic": "Academic Research", "writing": "Writing Projects",
        "family": "Family & Personal", "commercial": "Commercial",
        "personal": "Systems & Meta"
    }
    domain_css_colors = {
        "academic": "var(--academic)", "writing": "var(--writing)",
        "family": "var(--family)", "commercial": "var(--commercial)",
        "personal": "var(--personal)"
    }

    # Build top task rows
    def top_task_row(t):
        done_class = "done" if t["done"] else ""
        btn_class = "checked" if t["done"] else ""
        action = "markUndone" if t["done"] else "markDone"
        btn_label = "&#10003; Done" if t["done"] else "Done"
        effort = t.get("energy", "med")
        b64 = js_safe(t["text"])
        tb64 = task_data_b64(t)
        if t["priority"] == 1:
            tier_btn = f'<button class="demote-btn" onclick="demoteTask(\'{b64}\')">&#8595; P2</button>'
        else:
            tier_btn = f'<button class="promote-btn" onclick="promoteTask(\'{b64}\')">&#8593; P1</button>'
        notes_html = notes_popover(t.get("notes", ""))
        return f'''<div class="top-task-row {done_class}">
            <button class="top-task-done-btn {btn_class}" onclick="{action}('{b64}')">{btn_label}</button>
            <span class="top-task-text">{esc(t["text"])}{notes_html}</span>
            {f'<span class="top-task-due">{esc(t["due"])}</span>' if t.get("due") else ""}
            <span class="top-task-effort {effort}">{effort}</span>
            <span class="domain-tag {t["domain"]}">{esc(t["domain"])}</span>
            {tier_btn}
            <button class="edit-btn" onclick="openEditTask(decTask('{tb64}'))">&#9998;</button>
            <button class="cancel-btn" onclick="cancelTask('{b64}')" title="Cancel task">&#10007;</button>
            <button class="save-later-btn" onclick="saveForLater('{b64}')" title="Save for later">&#128337;</button>
        </div>'''

    # Map a dashboard project NAME → its R&D registry id, so a card can carry a
    # data-project-id that the Gandalf-status poller matches against the bulk
    # /api/rnd/gandalf_status_all map (keyed by R&D project_id). Best-effort: a
    # registry read failure leaves the map empty (cards simply carry no id and
    # never show a Gandalf badge). Last writer wins on a duplicate name.
    _gandalf_name_to_pid = {}
    try:
        for _e in _rnd.list_projects(include_archived=False, include_future=False,
                                     include_retired=False):
            _nm = (_e.get("name") or "").strip().lower()
            if _nm and _e.get("id"):
                _gandalf_name_to_pid[_nm] = _e["id"]
    except Exception:
        _gandalf_name_to_pid = {}

    # Build project cards
    def project_card(p):
        effort = p.get("effort", "high")
        pb64 = project_data_b64(p)
        b64p = js_safe(p["name"])
        if p["priority"] == 1:
            tier_btn = f'<button class="demote-btn" onclick="demoteProject(\'{b64p}\')">&#8595; P2</button>'
        else:
            tier_btn = f'<button class="promote-btn" onclick="promoteProject(\'{b64p}\')">&#8593; P1</button>'
        # Bridge to the R&D project id (if this dashboard project is registered),
        # so the dashboard Gandalf-status poller can target this exact card.
        _gpid = _gandalf_name_to_pid.get((p["name"] or "").strip().lower(), "")
        gpid_attr = f' data-project-id="{esc(_gpid)}"' if _gpid else ""
        return f'''<div class="card priority-{p["priority"]}{' has-deadline' if p.get('due') else ''}"{gpid_attr}>
            <div class="card-main">
                <div class="card-top">
                    <h3>{esc(p["name"])}</h3>
                    <span class="gandalf-card-status" hidden aria-live="polite"><span class="gcs-spin"></span><span class="gcs-text"></span></span>
                    {f'<span class="due-badge">{esc(p["due"])}</span>' if p.get("due") else ""}
                    <span class="effort-badge {effort}">{effort}</span>
                    <span class="domain-tag {p["domain"]}">{esc(p["domain"])}</span>
                    {tier_btn}
                    <button class="edit-btn" onclick="openEditProject(decProj('{pb64}'))">&#9998;</button>
                </div>
                {f'<div class="next-text">Next: {esc(p["next"])}</div>' if p.get("next") else ""}
            </div>
        </div>'''

    # Build task items (for Other Tasks and domain views).
    # Presentation mirrors top_task_row() so P2 tasks look the same as P1 tasks —
    # flat row with a Done button instead of a boxy checkbox card.
    def task_item(t):
        done_class = "done" if t["done"] else ""
        btn_class = "checked" if t["done"] else ""
        action = "markUndone" if t["done"] else "markDone"
        btn_label = "&#10003; Done" if t["done"] else "Done"
        effort = t.get("energy", "med")
        b64 = js_safe(t["text"])
        tb64 = task_data_b64(t)
        if t["priority"] == 1:
            tier_btn = f'<button class="demote-btn" onclick="demoteTask(\'{b64}\')">&#8595; P2</button>'
        else:
            tier_btn = f'<button class="promote-btn" onclick="promoteTask(\'{b64}\')">&#8593; P1</button>'
        notes_html = notes_popover(t.get("notes", ""))
        return f'''<div class="top-task-row p2-task-row {done_class}">
            <button class="top-task-done-btn {btn_class}" onclick="{action}('{b64}')">{btn_label}</button>
            <span class="top-task-text">{esc(t["text"])}{notes_html}</span>
            {f'<span class="top-task-due">{esc(t["due"])}</span>' if t.get("due") else ""}
            <span class="top-task-effort {effort}">{effort}</span>
            <span class="domain-tag {t["domain"]}">{esc(t["domain"])}</span>
            {tier_btn}
            <button class="edit-btn" onclick="openEditTask(decTask('{tb64}'))">&#9998;</button>
            <button class="cancel-btn" onclick="cancelTask('{b64}')" title="Cancel task">&#10007;</button>
            <button class="save-later-btn" onclick="saveForLater('{b64}')" title="Save for later">&#128337;</button>
        </div>'''

    # Build sidebar nav items
    domain_order = ["academic", "writing", "family", "commercial", "personal"]
    nav_items = ""
    for d in domain_order:
        if d in domain_counts or any(p["domain"] == d for p in projects):
            count = domain_counts.get(d, 0)
            nav_items += f'''<div class="nav-item" data-view="{d}" onclick="showView('{d}')">
                <span class="dot" style="background:{domain_css_colors.get(d,'var(--text-dim)')}"></span>
                {domain_labels.get(d, d.title())}
                <span class="count">{count}</span>
            </div>'''

    # Build domain views — same structure as the main dashboard
    domain_views = ""
    for d in domain_order:
        d_projects = [p for p in projects if p["domain"] == d]
        d_tasks = [t for t in tasks if t["domain"] == d]
        d_active = [t for t in d_tasks if not t["done"]]
        d_done = [t for t in d_tasks if t["done"]]
        if not d_projects and not d_tasks:
            continue

        # Same logic as main dashboard: Top Tasks = P1 + due soon
        d_p1 = [t for t in d_active if t["priority"] == 1]
        d_due_soon_non_p1 = [t for t in d_active if t["priority"] != 1 and t.get("due") and t["due"] <= today_iso]
        d_p1_sorted = sorted(d_p1, key=lambda t: (
            0 if t.get("due") and t["due"] <= today_iso else 1,
            t["text"]
        ))
        d_seen_top = set()
        d_top_tasks = []
        for t in d_due_soon_non_p1 + d_p1_sorted:
            key = t["text"].lower()[:60]
            if key not in d_seen_top:
                d_seen_top.add(key)
                d_top_tasks.append(t)
        d_top_done = len([t for t in d_top_tasks if t["done"]])
        d_top_texts = set(t["text"].lower()[:60] for t in d_top_tasks)

        # P1 and P2+ projects for this domain
        d_p1_projects = sorted([p for p in d_projects if p["priority"] == 1 and p["status"] == "active"],
                               key=lambda p: (0 if p.get("due") else 1, p.get("due", ""), p["name"]))
        d_p2_projects = sorted([p for p in d_projects if p["priority"] >= 2 and p["status"] == "active"],
                               key=lambda p: (p["priority"], p["name"]))

        # P2+ tasks not already in top tasks.
        # Sort: by energy (high → med → low), then by priority number, then text.
        # (Domain is constant here since we're inside a single-domain view.)
        d_other_tasks = sorted(
            [t for t in d_active if t["priority"] >= 2 and t["text"].lower()[:60] not in d_top_texts],
            key=lambda t: (
                energy_sort_order.get(t.get("energy", "med").lower(), 1),
                t["priority"],
                t["text"],
            ),
        )

        # Stats for this domain
        d_active_projects = len([p for p in d_projects if p.get("status") == "active"])

        # Build the top tasks rows
        d_top_rows = "".join(top_task_row(t) for t in d_top_tasks)
        if not d_top_tasks:
            d_top_rows = '<div class="empty-msg">No priority or time-sensitive tasks in this domain.</div>'

        # Build completed items for this domain
        d_completed_items = ""
        for t in reversed(d_done):
            b64c = js_safe(t["text"])
            notes_html_c = notes_popover(t.get("notes", ""))
            d_completed_items += f'''<div class="task-item completed">
                <div class="task-check checked" onclick="markUndone('{b64c}')"></div>
                <div class="task-text">{esc(t["text"])}{notes_html_c}</div>
                <div class="task-meta">
                    {f'<span class="task-energy">{t["energy"]}</span>' if t.get("energy") else ""}
                    <span class="task-priority p{t["priority"]}">P{t["priority"]}</span>
                </div>
            </div>'''

        domain_views += f'''
        <div class="view" id="view-{d}" style="display:none">
            <div class="page-header">
                <div style="display:flex;align-items:center;gap:8px">
                    <h2>{domain_labels.get(d, d.title())}</h2>
                    <button class="btn btn-sm btn-outline" onclick="showView('dashboard')" style="font-size:11px;padding:4px 10px">&#8592; Dashboard</button>
                </div>
                <div class="date">{today_str}</div>
            </div>

            <div style="display:flex;justify-content:flex-end;margin-bottom:8px">
                <button class="btn btn-sm" onclick="toggleAddTask_{d}()">+ Add Task</button>
            </div>
            <div class="add-task-bar" id="addTaskBar_{d}" style="display:none;flex-wrap:wrap">
                <input type="text" id="newTask_{d}" placeholder="What needs to be done?" onkeypress="if(event.key==='Enter')addTaskDomain('{d}')" style="min-width:200px" />
                <select id="newPriority_{d}">
                    <option value="1">P1</option>
                    <option value="2" selected>P2</option>
                    <option value="3">P3</option>
                </select>
                <div class="date-picker-wrap">
                  <input type="date" id="newDue_{d}" title="Due date (optional)" />
                  <button type="button" class="cal-toggle" onclick="toggleCalendar('newDue_{d}', this)" title="Open calendar">&#128197;</button>
                  <div class="cal-popup" id="cal_newDue_{d}"></div>
                </div>
                <button class="btn btn-sm" onclick="addTaskDomain('{d}')">Add</button>
                <input type="text" id="newNotes_{d}" placeholder="Notes — email, link, reference (optional)" style="min-width:200px;flex:1;margin-top:4px" />
            </div>

            <div class="top-tasks-box">
                <div class="top-header">
                    <h3>Top Tasks</h3>
                    <span class="top-progress">{d_top_done} / {len(d_top_tasks)} done</span>
                </div>
                {d_top_rows}
            </div>

            {f'<div class="section-header"><h3>Priority 1 Projects</h3></div><div class="card-grid">{"".join(project_card(p) for p in d_p1_projects)}</div>' if d_p1_projects else ""}

            <div class="stats-row">
                <div class="stat-card"><div class="num">{d_active_projects}</div><div class="label">Active Projects</div></div>
                <div class="stat-card"><div class="num">{len(d_active)}</div><div class="label">Open Tasks</div></div>
                <div class="stat-card"><div class="num">{len(d_done)}</div><div class="label">Completed</div></div>
            </div>

            {f'<div class="section-header"><h3>Other Tasks</h3></div><div class="task-list">{"".join(task_item(t) for t in d_other_tasks)}</div>' if d_other_tasks else ""}

            {f'<div class="section-header"><h3>Priority 2+ Projects</h3></div><div class="card-grid">{"".join(project_card(p) for p in d_p2_projects)}</div>' if d_p2_projects else ""}

            {f'<div class="section-header" style="margin-top:24px"><h3>Completed ({len(d_done)})</h3></div><div class="task-list">{d_completed_items}</div>' if d_done else ""}
        </div>'''

    # Build completed view
    completed_items = ""
    for t in reversed(done_tasks):  # most recent first
        b64c = js_safe(t["text"])
        notes_html = notes_popover(t.get("notes", ""))
        completed_items += f'''<div class="task-item completed">
            <div class="task-check checked" onclick="markUndone('{b64c}')"></div>
            <div class="task-text">{esc(t["text"])}{notes_html}</div>
            <div class="task-meta">
                {f'<span class="task-energy">{t["energy"]}</span>' if t.get("energy") else ""}
                <span class="task-priority p{t["priority"]}">P{t["priority"]}</span>
                <span class="domain-tag {t["domain"]}">{esc(t["domain"])}</span>
            </div>
        </div>'''
    if not done_tasks:
        completed_items = '<div class="empty-msg">No completed tasks yet. Check off items from the dashboard to see them here.</div>'

    # Build cancelled view
    cancelled_tasks = parse_archived_tasks(CANCELLED_MD)
    cancelled_items = ""
    for ct in reversed(cancelled_tasks):
        b64r = js_safe(ct["text"])
        notes_line = f'<div class="archived-notes">Notes: {esc(ct["notes"])}</div>' if ct.get("notes") else ""
        cancelled_items += f'''<div class="task-item archived-task">
            <div style="flex:1">
                <div class="task-text">{esc(ct["text"])}</div>
                <div style="font-size:11px;color:var(--text-dim);margin-top:2px">Cancelled {esc(ct["date"])}{(' &bull; ' + esc(ct["domain"])) if ct.get("domain") else ""} &bull; P{ct.get("priority",2)}</div>
                {notes_line}
            </div>
            <button class="btn btn-sm btn-outline" onclick="restoreTask('{b64r}','cancelled')" style="font-size:11px">&#8634; Restore</button>
        </div>'''
    if not cancelled_tasks:
        cancelled_items = '<div class="empty-msg">No cancelled tasks.</div>'

    # Build saved-for-later view
    saved_tasks = parse_archived_tasks(SAVED_FOR_LATER_MD)
    saved_items = ""
    for st in reversed(saved_tasks):
        b64r = js_safe(st["text"])
        notes_line = f'<div class="archived-notes">Notes: {esc(st["notes"])}</div>' if st.get("notes") else ""
        saved_items += f'''<div class="task-item archived-task">
            <div style="flex:1">
                <div class="task-text">{esc(st["text"])}</div>
                <div style="font-size:11px;color:var(--text-dim);margin-top:2px">Saved {esc(st["date"])}{(' &bull; ' + esc(st["domain"])) if st.get("domain") else ""} &bull; P{st.get("priority",2)}</div>
                {notes_line}
            </div>
            <button class="btn btn-sm btn-outline" onclick="restoreTask('{b64r}','saved')" style="font-size:11px">&#8634; Restore</button>
        </div>'''
    if not saved_tasks:
        saved_items = '<div class="empty-msg">No saved-for-later tasks.</div>'

    # Inbox items
    inbox_items = ""
    for item in inbox:
        inbox_items += f'''<div class="task-item">
            <div style="flex:1">
                <div class="task-text">{esc(item["text"])}</div>
                <div style="font-size:11px;color:var(--text-dim);margin-top:2px">{esc(item["date"])}{(' &bull; ' + esc(item["domain"])) if item.get("domain") else ""}</div>
            </div>
        </div>'''
    if not inbox:
        inbox_items = '<div class="empty-msg">Inbox empty. Nice work.</div>'

    # R&D control surface: surface the (previously orphaned) folder-grouped
    # projects view inside the dashboard. Best-effort so a registry hiccup never
    # blanks the whole dashboard.
    try:
        rnd_projects_html = render_projects_view_html()
    except Exception:
        rnd_projects_html = ('<div class="rnd-projects"><p class="rnd-empty">'
                             'R&amp;D projects unavailable.</p></div>')
    try:
        rnd_archive_html = render_archive_view_html()
    except Exception:
        rnd_archive_html = ('<div class="rnd-projects"><p class="rnd-empty">'
                            'Archive unavailable.</p></div>')

    # Projects-tile summary line. The markdown PROJECTS.md count alone reads "0
    # active" on a dashboard full of R&D work, so the tile counts what it
    # actually contains: R&D folders + projects, then the markdown-tracked
    # cards. Best-effort — a registry hiccup degrades the label, never the page.
    try:
        _rnd_groups = _rnd.group_by_group()
        _rnd_folder_n = len(_rnd_groups)
        _rnd_project_n = sum(len(v) for v in _rnd_groups.values())
        projects_tile_count = "%d folder%s &middot; %d R&amp;D project%s" % (
            _rnd_folder_n, "" if _rnd_folder_n == 1 else "s",
            _rnd_project_n, "" if _rnd_project_n == 1 else "s")
    except Exception:
        projects_tile_count = "R&amp;D projects"
    _md_active = len([p for p in projects if p["status"] == "active"])
    if _md_active:
        projects_tile_count += " &middot; %d tracked" % _md_active

    # Steward persona (selectable livery, 2026-07-29): ONE steward engine,
    # the user picks the face. The HIGH SEAT icon fronts the portfolio
    # steward tile; the SEAL icon fronts the Projects tile (the projects are
    # run under the steward's seal). Best-effort — settings hiccup falls back
    # to the Ecgberht originals, never breaks the page.
    _stew = _steward_ui()
    steward_hs_icon = _stew["high_seat"]
    steward_seal_icon = _stew["seal"]
    steward_label = _stew["label"]
    steward_hs_name = _stew["high_seat_name"]
    steward_projects_hint = _stew["projects_hint"]
    # The HIGH SEAT src, resolved ONCE for the tile <img> and the boot global.
    # _steward_ui() setdefaults MISSING fields only, so a saved profile
    # carrying a BLANK high_seat would render a bare /vendor/brand/ src; a
    # blank degrades to the locked Ecgberht original at its shipped path.
    if str(steward_hs_icon or "").strip():
        steward_hs_src = "/vendor/brand/%s?v=%s" % (steward_hs_icon, BUILD_ID)
    else:
        steward_hs_src = (
            "/vendor/brand/ecgberht-portfolio-high-seat.jpg?v=%s" % BUILD_ID)
    # Boot global for the High Seat overlay JS (loads before high-seat.js):
    # display names + icons in the overlay resolve through this, so the
    # overlay speaks the same livery as the tiles.
    steward_boot_json = json.dumps({
        "key": _stew["key"],
        "label": steward_label,
        "seal_src": "/vendor/brand/%s?v=%s" % (steward_seal_icon, BUILD_ID),
        "high_seat_src": steward_hs_src,
        "seal_name": _stew["seal_name"],
        "high_seat_name": steward_hs_name,
    })

    # Pre-build balance widget rows (avoid nested f-string issues)
    max_count = max(domain_counts.values()) if domain_counts else 1
    balance_rows = ""
    for d in domain_order:
        if d in domain_counts:
            pct = min(100, domain_counts[d] * 100 // max(max_count, 1))
            color = domain_css_colors.get(d, 'var(--text-dim)')
            balance_rows += f'''<div class="balance-row">
                <span class="label">{d.title()[:8]}</span>
                <div class="balance-bar"><div class="fill" style="width:{pct}%;background:{color}"></div></div>
                <span>{domain_counts[d]}</span>
            </div>'''

    # ── rearch W6b (C1 increment 3): the static home-dashboard path ─────────
    # Chosen by the SAME ``frontend`` pillar off-switch flag as W4/W5 (one flag,
    # one revert). EMBEDDED (the default, the f-string below) is the pre-wave
    # emission — byte-identical and the byte-parity reference. STATIC assembles
    # the same page from the checked-in ``static/home.{html,css,js}`` mirror
    # (minted by ``tools/extract_home_dashboard.py``): the head <style> and the
    # application <script> arrive as hashed static assets, server state rides
    # ONLY the ANCHOR_BOOT bootstrap, and the markup-emitting values stay
    # server-rendered as include-slot fills. A missing/undecodable shell mirror
    # (or a missing hashed asset) falls back to the embedded path — never a 500.
    if _static_frontend_enabled():
        _home_shell = _home_shell_template()
        _home_css_ver = static_asset_version(HOME_CSS_ASSET)
        _home_js_ver = static_asset_version(HOME_JS_ASSET)
        if (_home_shell is not None and _home_css_ver != "missing"
                and _home_js_ver != "missing"):
            _home_css_block = (
                "<link rel='stylesheet' href='" + STATIC_URL_PREFIX + "/"
                + HOME_CSS_ASSET + "?v=" + _home_css_ver + "'>")
            _home_js_block = (
                "<script>\n" + anchor_boot_script(home_boot_extra()) + "\n</script>"
                "<script src='" + STATIC_URL_PREFIX + "/" + HOME_JS_ASSET
                + "?v=" + _home_js_ver + "'></script>")
            _home_slots = {
                "build_id": BUILD_ID,
                "inbox_count": str(len(inbox)),
                "nav_items": nav_items,
                "balance_rows": balance_rows,
                "auth_token_btn_display": auth_token_btn_display,
                "health_banner_html": health_banner_html,
                "done_count": str(len(done_tasks)),
                "cancelled_count": str(len(cancelled_tasks)),
                "saved_count": str(len(saved_tasks)),
                "model_flex_badge": render_model_flex_badge(),
                "today_str": today_str,
                "top_done": str(top_done),
                "top_total": str(len(top_tasks)),
                "top_task_rows": "".join(top_task_row(t) for t in top_tasks),
                "rnd_projects_html": rnd_projects_html,
                "p1_cards": "".join(project_card(p) for p in p1_projects),
                "active_projects": str(
                    len([p for p in projects if p["status"] == "active"])),
                "open_tasks": str(len(active)),
                "other_task_items": "".join(
                    task_item(t) for t in other_tasks),
                "p2_cards": "".join(project_card(p) for p in p2_projects),
                "completed_items": completed_items,
                "cancelled_items": cancelled_items,
                "saved_items": saved_items,
                "inbox_items": inbox_items,
                "rnd_archive_html": rnd_archive_html,
                "domain_views": domain_views,
                "cache_bust": cache_bust_script(),
                "orphan_alert": _ORPHAN_ALERT_JS,
                "home_css": _home_css_block,
                "home_js": _home_js_block,
            }
            return _render_home_slots(_home_shell, _home_slots)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Anchor Dashboard — J.C. Liechty</title>
<link rel="icon" href="/vendor/brand/gwl-m-icon.svg?v={BUILD_ID}" type="image/svg+xml">
<link rel="icon" href="/anchor.ico?v=2026-05-11" type="image/x-icon">
<link rel="icon" href="/anchor.png?v=2026-05-11" type="image/png" sizes="256x256">
<link rel="apple-touch-icon" href="/anchor-touch.png?v=2026-05-11">
<style>
:root {{
    --bg: #0f1117; --surface: #1a1d27; --surface2: #232733; --border: #2e3340;
    --text: #e2e4e9; --text-dim: #8b8f9a; --accent: #6c9cfc;
    --academic: #6c9cfc; --writing: #c084fc; --family: #4ade80;
    --commercial: #fb923c; --personal: #67e8f9;
    --danger: #f87171; --warning: #fbbf24; --success: #4ade80;
    color-scheme: dark;
}}
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; min-height: 100vh; }}
.app {{ display: flex; min-height: 100vh; }}

/* Sidebar */
.sidebar {{
    width: 260px; background: var(--surface); border-right: 1px solid var(--border);
    padding: 20px 0; flex-shrink: 0; display: flex; flex-direction: column;
    position: fixed; top: 0; left: 0; bottom: 0; overflow-y: auto;
}}
.sidebar h1 {{ font-size: 20px; padding: 0 20px 4px; font-weight: 700; }}
.sidebar h1 span {{ color: var(--accent); }}
.sidebar .subtitle {{ font-size: 11px; color: var(--text-dim); padding: 0 20px 20px; }}

/* Ghost World Labs brand lockup (Wave 9) — elegant, unobtrusive, theme-fit */
.gwl-lockup {{
    display: flex; align-items: center; gap: 9px;
    padding: 14px 20px 4px;
}}
.gwl-lockup img {{
    width: 26px; height: 26px; border-radius: 6px; flex-shrink: 0;
    box-shadow: 0 0 8px rgba(34, 197, 94, 0.35);
}}
.gwl-lockup .gwl-wordmark {{
    font-size: 12px; font-weight: 700; letter-spacing: 0.3px;
    color: #f8fafc; line-height: 1.1;
}}
.gwl-lockup .gwl-wordmark .gwl-accent {{ color: #22c55e; }}
.gwl-badge {{
    display: inline-flex; align-items: center; gap: 5px;
    margin: 4px 20px 14px; padding: 3px 9px;
    font-size: 10px; font-weight: 600; letter-spacing: 0.2px;
    color: #f8fafc; background: rgba(15, 23, 42, 0.6);
    border: 1px solid rgba(34, 197, 94, 0.35); border-radius: 999px;
}}
.gwl-badge .gwl-rad {{ color: #22c55e; }}
.gwl-footer {{
    margin-top: 28px; padding-top: 14px; border-top: 1px solid var(--border);
    display: flex; align-items: center; gap: 8px;
    font-size: 11px; color: var(--text-dim);
}}
.gwl-footer img {{ width: 16px; height: 16px; border-radius: 4px; }}
.gwl-footer .gwl-accent {{ color: #22c55e; }}

/* v4 Wave 8 — Option B masthead lockup (branding_proposals.html Proposal B):
   Anchor title · vertical divider · GWL mark + wordmark off to the side ·
   "Powered by NextGen Nuclear ☢" pill pushed to the far right. Reuses the SINGLE
   vendored brand mark (/vendor/brand/gwl-m-icon.svg); no second asset. */
.masthead {{
    display: flex; align-items: center; gap: 18px;
    padding: 14px 0 18px; margin-bottom: 8px;
    border-bottom: 1px solid var(--border);
}}
.masthead .mh-title {{
    font-size: 28px; font-weight: 700; letter-spacing: -0.5px;
    display: flex; align-items: center; gap: 9px;
}}
.masthead .mh-title .mh-anchor {{ color: var(--accent); }}
.masthead .mh-vdiv {{ width: 1px; height: 38px; background: var(--border); flex-shrink: 0; }}
.masthead .mh-lock {{ display: flex; align-items: center; gap: 10px; }}
.masthead .mh-lock img {{
    width: 30px; height: 30px; border-radius: 7px; flex-shrink: 0;
    box-shadow: 0 0 9px rgba(34, 197, 94, 0.4);
}}
.masthead .mh-words {{ line-height: 1.2; }}
.masthead .mh-words .mh-w1 {{ font-size: 13px; font-weight: 700; color: #f8fafc; }}
.masthead .mh-words .mh-w1 .gwl-accent {{ color: #22c55e; }}
.masthead .mh-words .mh-w2 {{ font-size: 10.5px; color: var(--text-dim); margin-top: 2px; }}
.masthead .mh-spacer {{ flex: 1; }}
.masthead .mh-pill {{
    display: inline-flex; align-items: center; gap: 6px;
    padding: 4px 11px; border-radius: 999px;
    font-size: 10.5px; font-weight: 600; color: #f8fafc;
    background: rgba(15, 23, 42, 0.6); border: 1px solid rgba(34, 197, 94, 0.4);
}}
.masthead .mh-pill .gwl-rad {{ color: #22c55e; }}
.nav-section {{ margin-top: 16px; }}
.nav-section h3 {{ font-size: 10px; text-transform: uppercase; letter-spacing: 1.2px; color: var(--text-dim); padding: 0 20px 6px; }}
.nav-item {{
    padding: 8px 20px; cursor: pointer; font-size: 13px; display: flex; align-items: center;
    gap: 10px; transition: background 0.15s; border-left: 3px solid transparent;
}}
.nav-item:hover {{ background: var(--surface2); }}
.nav-item.active {{ background: var(--surface2); border-left-color: var(--accent); }}
.nav-item .dot {{ width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }}
.nav-item .count {{ margin-left: auto; background: var(--surface2); padding: 1px 7px; border-radius: 10px; font-size: 11px; color: var(--text-dim); }}

/* Balance widget */
.balance-widget {{
    margin: auto 16px 16px; padding: 14px; background: var(--surface2);
    border-radius: 10px; border: 1px solid var(--border);
}}
.balance-widget h4 {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-dim); margin-bottom: 10px; }}
.balance-bars {{ display: flex; flex-direction: column; gap: 6px; }}
.balance-row {{ display: flex; align-items: center; gap: 8px; font-size: 11px; }}
.balance-row .label {{ width: 60px; color: var(--text-dim); }}
.balance-bar {{ flex: 1; height: 6px; background: var(--border); border-radius: 3px; overflow: hidden; }}
.balance-bar .fill {{ height: 100%; border-radius: 3px; transition: width 0.5s ease; }}

/* Main content */
.main {{ margin-left: 260px; flex: 1; padding: 28px 32px; max-width: 1100px; }}
.page-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }}
.page-header h2 {{ font-size: 22px; font-weight: 600; }}
.page-header .date {{ color: var(--text-dim); font-size: 13px; }}

/* Cards */
.card-grid {{ display: flex; flex-direction: column; gap: 6px; margin-bottom: 24px; }}
.card {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; transition: border-color 0.2s; display: flex; align-items: center; gap: 12px;
}}
.card:hover {{ border-color: #3e4455; }}
.card.priority-1 {{ border-left: 3px solid var(--danger); }}
.card.priority-2 {{ border-left: 3px solid var(--warning); }}
.card.priority-3 {{ border-left: 3px solid var(--accent); }}
.card.has-deadline {{ background: linear-gradient(90deg, rgba(248,113,113,0.06), transparent 40%); }}
.card-main {{ flex: 1; min-width: 0; }}
.card-top {{ display: flex; align-items: center; gap: 8px; }}
.card h3 {{ font-size: 13px; font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.due-badge {{ font-size: 10px; background: rgba(248,113,113,0.2); color: var(--danger); padding: 1px 7px; border-radius: 3px; font-weight: 600; white-space: nowrap; }}
.effort-badge {{ font-size: 9px; padding: 1px 6px; border-radius: 3px; white-space: nowrap; }}
.effort-badge.low {{ background: rgba(74,222,128,0.15); color: var(--success); }}
.effort-badge.med {{ background: rgba(251,191,36,0.12); color: var(--warning); }}
.effort-badge.high {{ background: rgba(192,132,252,0.12); color: var(--writing); }}
.next-text {{ font-size: 11.5px; color: var(--text-dim); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; margin-top: 2px; }}
.domain-tag {{ font-size: 9px; text-transform: uppercase; letter-spacing: 0.8px; padding: 2px 7px; border-radius: 4px; white-space: nowrap; }}
.domain-tag.academic {{ background: rgba(108,156,252,0.15); color: var(--academic); }}
.domain-tag.writing {{ background: rgba(192,132,252,0.15); color: var(--writing); }}
.domain-tag.family {{ background: rgba(74,222,128,0.15); color: var(--family); }}
.domain-tag.commercial {{ background: rgba(251,146,60,0.15); color: var(--commercial); }}
.domain-tag.personal {{ background: rgba(103,232,249,0.15); color: var(--personal); }}

.card-grid.expanded .card {{ flex-direction: column; align-items: stretch; padding: 14px; }}
.card-grid.expanded .card-main {{ width: 100%; }}
.card-grid.expanded .card h3 {{ white-space: normal; }}
.card-grid.expanded .next-text {{ white-space: normal; }}

/* Gandalf in-flight status badge on a dashboard project card. Hidden until the
   bulk poller finds an active run for this card's project, then shows a small
   spinner + short status text (e.g. "Gandalf: running…"). */
.gandalf-card-status {{
    display: inline-flex; align-items: center; gap: 5px;
    font-size: 9px; font-weight: 600; letter-spacing: 0.2px;
    padding: 1px 7px 1px 6px; border-radius: 999px; white-space: nowrap;
    background: rgba(192,132,252,0.14); color: var(--writing);
    border: 1px solid rgba(192,132,252,0.30);
}}
.gandalf-card-status[hidden] {{ display: none; }}
.gandalf-card-status .gcs-spin {{
    width: 8px; height: 8px; border-radius: 50%;
    border: 1.5px solid rgba(192,132,252,0.35); border-top-color: var(--writing);
    animation: gcs-spin 0.8s linear infinite; flex-shrink: 0;
}}
@keyframes gcs-spin {{ to {{ transform: rotate(360deg); }} }}

/* Tasks */
.task-list {{ margin-bottom: 24px; }}
.section-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }}
.section-header h3 {{ font-size: 15px; font-weight: 600; }}
.task-item {{
    display: flex; align-items: flex-start; gap: 10px; padding: 10px 12px;
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px; margin-bottom: 6px; transition: all 0.15s;
}}
.task-item:hover {{ border-color: #3e4455; }}
.task-item.completed {{ opacity: 0.5; }}
.task-item.completed .task-text {{ text-decoration: line-through; }}
.task-check {{
    width: 18px; height: 18px; border: 2px solid var(--border); border-radius: 5px;
    cursor: pointer; flex-shrink: 0; margin-top: 1px; display: flex; align-items: center;
    justify-content: center; transition: all 0.15s;
}}
.task-check:hover {{ border-color: var(--accent); }}
.task-check.checked {{ background: var(--accent); border-color: var(--accent); }}
.task-check.checked::after {{ content: '\\2713'; color: white; font-size: 11px; font-weight: 700; }}
.task-text {{ font-size: 13px; flex: 1; }}
.task-meta {{ display: flex; gap: 8px; align-items: center; flex-shrink: 0; }}
.task-priority {{ font-size: 10px; padding: 1px 6px; border-radius: 3px; font-weight: 600; }}
.task-priority.p1 {{ background: rgba(248,113,113,0.15); color: var(--danger); }}
.task-priority.p2 {{ background: rgba(251,191,36,0.15); color: var(--warning); }}
.task-priority.p3 {{ background: rgba(108,156,252,0.15); color: var(--accent); }}
.task-energy {{ font-size: 10px; color: var(--text-dim); }}

/* Top Tasks */
.top-tasks-box {{
    background: var(--surface); border: 1px solid rgba(108,156,252,0.3);
    border-radius: 12px; padding: 16px 18px; margin-bottom: 20px;
}}
.top-tasks-box .top-header {{ display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px; }}
.top-tasks-box h3 {{ font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--accent); }}
.top-tasks-box .top-progress {{ font-size: 11px; color: var(--text-dim); }}
.top-task-row {{ display: flex; align-items: center; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--border); transition: opacity 0.3s; }}
.top-task-row:last-child {{ border-bottom: none; }}
.top-task-row.done {{ opacity: 0.4; }}
.top-task-row.done .top-task-text {{ text-decoration: line-through; }}
.top-task-done-btn {{
    padding: 4px 12px; font-size: 11px; font-weight: 600; border-radius: 5px;
    cursor: pointer; flex-shrink: 0; transition: all 0.15s;
    border: 1px solid var(--border); background: var(--surface2); color: var(--text-dim);
}}
.top-task-done-btn:hover {{ background: var(--success); color: #000; border-color: var(--success); }}
.top-task-done-btn.checked {{ background: var(--success); color: #000; border-color: var(--success); }}
.top-task-text {{ font-size: 13px; flex: 1; font-weight: 500; position: relative; }}
.top-task-due {{ font-size: 10px; background: rgba(248,113,113,0.2); color: var(--danger); padding: 2px 8px; border-radius: 4px; font-weight: 600; white-space: nowrap; }}
.top-task-effort {{ font-size: 9px; padding: 2px 6px; border-radius: 3px; white-space: nowrap; }}
.top-task-effort.low {{ background: rgba(74,222,128,0.15); color: var(--success); }}
.top-task-effort.med {{ background: rgba(251,191,36,0.12); color: var(--warning); }}
.top-task-effort.high {{ background: rgba(192,132,252,0.12); color: var(--writing); }}

/* ── Dashboard section tiles (2026-07-27) ──────────────────────────────────
   The dashboard body is four collapsible tiles, in this order:
   High Seat · Workbench · Tasks · Projects. Each is a plain <details>, so the
   open/closed state needs no JS; the hint text flips off the [open] attribute
   ("Click to expand" → "Click to collapse") rather than lying when open. */
.dash-tile {{
    border: 1px solid var(--border); border-radius: 10px;
    background: var(--surface); margin-bottom: 14px; overflow: hidden;
}}
.dash-tile > summary {{
    display: flex; align-items: center; gap: 10px; padding: 12px 16px;
    cursor: pointer; list-style: none; font-size: 15px; font-weight: 600;
    user-select: none;
}}
.dash-tile > summary::-webkit-details-marker {{ display: none; }}
.dash-tile > summary::marker {{ content: ""; }}
.dash-tile > summary:hover {{ background: var(--surface2); }}
.dash-tile .tile-ico {{ width: 24px; height: 24px; border-radius: 4px; flex: none; }}
.dash-tile .tile-glyph {{ font-size: 18px; line-height: 1; flex: none; }}
.dash-tile .tile-count {{ font-size: 11px; font-weight: 500; color: var(--text-dim); }}
.dash-tile .tile-hint {{ margin-left: auto; font-size: 12px; font-weight: 400; color: var(--text-dim); white-space: nowrap; }}
.dash-tile .tile-hint::after {{ content: "\\25BE Click to expand"; }}
.dash-tile[open] .tile-hint::after {{ content: "\\25B4 Click to collapse"; }}
.dash-tile .tile-body {{ border-top: 1px solid var(--border); padding: 16px 18px; background: var(--bg); }}
.dash-tile .tile-body > *:first-child {{ margin-top: 0; }}
.dash-tile .tile-body .section-header {{ margin-top: 22px; }}
.dash-tile .tile-body .card-grid {{ margin-bottom: 0; }}
.dash-tile .tile-body .top-tasks-box {{ margin-bottom: 0; }}
/* The High Seat leads the stack: larger seal, larger title, gold accent. */
.dash-tile.tile-seat {{ border-color: rgba(224,164,55,0.45); }}
.dash-tile.tile-seat > summary {{ font-size: 18px; padding: 16px 18px; color: #e0a437; }}
.dash-tile.tile-seat .tile-ico {{ width: 44px; height: 44px; border-radius: 6px; }}
/* The High Seat rendered INSIDE its tile rather than as a floating dock. */
.ecg-hs-inline {{ color: var(--text); font-size: 13px; }}

/* Stats row */
.stats-row {{ display: flex; gap: 10px; margin-bottom: 20px; }}
.stat-card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 10px 14px; flex: 1; text-align: center; }}
.stat-card .num {{ font-size: 20px; font-weight: 700; }}
.stat-card .label {{ font-size: 10px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; }}

/* Inbox */
.inbox-input-row {{ display: flex; gap: 8px; margin-bottom: 16px; }}
.inbox-input-row input {{
    flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; color: var(--text); font-size: 13px; outline: none;
}}
.inbox-input-row input:focus {{ border-color: var(--accent); }}
.inbox-input-row input::placeholder {{ color: var(--text-dim); }}
.inbox-input-row select {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 12px; color: var(--text); font-size: 13px; cursor: pointer;
}}

/* Buttons */
.btn {{
    background: var(--accent); color: #fff; border: none; padding: 10px 18px;
    border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; white-space: nowrap;
}}
.btn:hover {{ opacity: 0.85; }}
.btn-sm {{ padding: 6px 12px; font-size: 12px; }}
.btn-outline {{ background: transparent; border: 1px solid var(--border); color: var(--text); }}
.btn-outline:hover {{ background: var(--surface2); opacity: 1; }}

/* Add task bar */
.add-task-bar {{
    display: flex; gap: 8px; margin-bottom: 12px;
}}
.add-task-bar input {{
    flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; color: var(--text); font-size: 13px; outline: none;
}}
.add-task-bar input:focus {{ border-color: var(--accent); }}
.add-task-bar input::placeholder {{ color: var(--text-dim); }}
.add-task-bar select {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
    padding: 8px 10px; color: var(--text); font-size: 12px; cursor: pointer;
}}

.empty-msg {{ color: var(--text-dim); font-size: 13px; padding: 12px; text-align: center; }}

/* Date picker wrapper */
.date-picker-wrap {{
    position: relative; display: inline-flex; align-items: center; gap: 0;
}}
.date-picker-wrap input[type="date"] {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 8px 0 0 8px;
    padding: 8px 10px; color: var(--text); font-size: 12px; width: 140px; outline: none;
}}
.date-picker-wrap input[type="date"]:focus {{ border-color: var(--accent); }}
.date-picker-wrap input[type="date"]::-webkit-calendar-picker-indicator {{ filter: invert(0.7); cursor: pointer; }}
.cal-toggle {{
    background: var(--surface2); border: 1px solid var(--border); border-left: none;
    border-radius: 0 8px 8px 0; padding: 8px 10px; cursor: pointer; color: var(--text-dim);
    font-size: 14px; display: flex; align-items: center; transition: all 0.15s;
}}
.cal-toggle:hover {{ background: var(--accent); color: #fff; border-color: var(--accent); }}

/* Calendar popup */
.cal-popup {{
    display: none; position: absolute; top: 100%; left: 0; z-index: 1000;
    background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
    padding: 12px; box-shadow: 0 8px 24px rgba(0,0,0,0.4); min-width: 280px; margin-top: 4px;
}}
.cal-popup.open {{ display: block; }}
.cal-header {{
    display: flex; align-items: center; justify-content: space-between; margin-bottom: 10px;
}}
.cal-header button {{
    background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
    color: var(--text); cursor: pointer; padding: 4px 10px; font-size: 13px; transition: all 0.15s;
}}
.cal-header button:hover {{ background: var(--accent); color: #fff; border-color: var(--accent); }}
.cal-header .cal-title {{ font-size: 13px; font-weight: 600; color: var(--text); }}
.cal-grid {{
    display: grid; grid-template-columns: repeat(7, 1fr); gap: 2px; text-align: center;
}}
.cal-grid .cal-dow {{
    font-size: 10px; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px;
    padding: 4px 0; font-weight: 600;
}}
.cal-grid .cal-day {{
    font-size: 12px; padding: 6px 2px; border-radius: 6px; cursor: pointer;
    color: var(--text); transition: all 0.12s; border: 1px solid transparent;
}}
.cal-grid .cal-day:hover {{ background: var(--surface2); border-color: var(--accent); }}
.cal-grid .cal-day.today {{ border-color: var(--accent); font-weight: 700; }}
.cal-grid .cal-day.selected {{ background: var(--accent); color: #fff; font-weight: 700; }}
.cal-grid .cal-day.other-month {{ color: var(--text-dim); opacity: 0.4; }}
.cal-grid .cal-day.empty {{ cursor: default; }}
.cal-grid .cal-day.empty:hover {{ background: transparent; border-color: transparent; }}
.cal-actions {{
    display: flex; gap: 6px; margin-top: 10px; justify-content: flex-end;
}}
.cal-actions button {{
    background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
    color: var(--text-dim); cursor: pointer; padding: 4px 12px; font-size: 11px; transition: all 0.15s;
}}
.cal-actions button:hover {{ color: var(--text); background: var(--border); }}
.cal-actions .cal-today-btn:hover {{ background: var(--accent); color: #fff; border-color: var(--accent); }}

/* Modal date picker adjustments */
.modal .date-picker-wrap {{ width: 100%; }}
.modal .date-picker-wrap input[type="date"] {{ width: 100%; border-radius: 8px 0 0 8px; }}

/* Edit buttons */
.edit-btn {{
    background: none; border: none; color: var(--text-dim); cursor: pointer;
    font-size: 12px; padding: 2px 6px; border-radius: 4px; opacity: 0; transition: all 0.15s;
}}
.task-item:hover .edit-btn, .top-task-row:hover .edit-btn, .card:hover .edit-btn {{ opacity: 1; }}
.edit-btn:hover {{ background: var(--surface2); color: var(--accent); }}

/* Promote/Demote buttons */
.promote-btn, .demote-btn {{
    background: none; border: 1px solid var(--border); color: var(--text-dim); cursor: pointer;
    font-size: 10px; padding: 2px 8px; border-radius: 4px; opacity: 0; transition: all 0.15s; white-space: nowrap;
}}
.card:hover .promote-btn, .card:hover .demote-btn,
.task-item:hover .promote-btn, .task-item:hover .demote-btn,
.top-task-row:hover .promote-btn, .top-task-row:hover .demote-btn {{ opacity: 1; }}
.promote-btn:hover {{ background: rgba(248,113,113,0.15); color: var(--danger); border-color: var(--danger); }}
.demote-btn:hover {{ background: rgba(251,191,36,0.15); color: var(--warning); border-color: var(--warning); }}

/* Modal */
.modal-overlay {{
    display: none; position: fixed; inset: 0; background: rgba(0,0,0,0.6);
    z-index: 200; align-items: center; justify-content: center;
}}
.modal-overlay.open {{ display: flex; }}
.modal {{
    background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
    padding: 24px; width: 500px; max-width: 90vw; max-height: 85vh; overflow-y: auto;
}}
.modal h3 {{ font-size: 16px; margin-bottom: 16px; }}
.modal label {{ font-size: 12px; color: var(--text-dim); display: block; margin-bottom: 4px; margin-top: 12px; }}
.modal input, .modal select, .modal textarea {{
    width: 100%; background: var(--surface2); border: 1px solid var(--border); border-radius: 6px;
    padding: 8px 12px; color: var(--text); font-size: 13px; outline: none; font-family: inherit;
}}
.modal textarea {{ resize: vertical; min-height: 60px; }}
.modal input:focus, .modal select:focus {{ border-color: var(--accent); }}
.modal-actions {{ display: flex; gap: 8px; justify-content: flex-end; margin-top: 20px; }}

/* R&D existing-folder picker */
.rnd-picker-loc {{
    font-size: 12px; color: var(--text-dim); margin-bottom: 6px;
    word-break: break-all; line-height: 1.4;
}}
.rnd-picker-loc b {{ color: var(--text); }}
.rnd-picker-selected {{
    font-size: 12px; margin: 6px 0 0; padding: 6px 10px; border-radius: 6px;
    background: rgba(108,156,252,0.12); border: 1px solid var(--accent);
    color: var(--text); word-break: break-all; line-height: 1.4;
}}
.rnd-picker-selected.empty {{
    background: var(--surface2); border-color: var(--border); color: var(--text-dim);
}}
.rnd-picker-err {{
    font-size: 12px; margin: 6px 0; padding: 6px 10px; border-radius: 6px;
    background: rgba(248,113,113,0.12); border: 1px solid var(--danger); color: var(--text);
    word-break: break-all; line-height: 1.4;
}}
/* Explorer-style expandable TREE folder picker */
.rnd-tree {{
    background: var(--surface2); max-height: 300px; overflow: auto;
    border: 1px solid var(--border); border-radius: 6px; padding: 6px;
    margin-top: 6px; font-size: 13px;
}}
.rnd-tree-children {{ margin-left: 16px; border-left: 1px solid var(--border); padding-left: 2px; }}
.rnd-tree-row {{
    display: flex; align-items: center; gap: 8px; padding: 5px 6px;
    border-radius: 5px; cursor: pointer; user-select: none; transition: background 0.12s;
}}
.rnd-tree-row:hover {{ background: rgba(108,156,252,0.14); }}
.rnd-tree-row.selected {{ background: rgba(108,156,252,0.28); }}
.rnd-tree-row .rt-caret {{
    flex: 0 0 auto; width: 14px; text-align: center; color: var(--text-dim);
    font-size: 11px;
}}
.rnd-tree-row .rt-icon {{ flex: 0 0 auto; font-size: 15px; }}
.rnd-tree-row .rt-name {{
    flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}}
.rnd-tree-err {{ color: var(--danger); font-size: 11px; padding: 2px 6px 2px 22px; }}
.rnd-use-btn {{ background: var(--accent); }}

/* Toast */
.toast {{
    position: fixed; bottom: 24px; right: 24px; background: var(--success);
    color: #000; padding: 12px 20px; border-radius: 8px; font-weight: 600;
    display: none; z-index: 200; animation: fadeIn 0.2s;
}}
@keyframes fadeIn {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: translateY(0); }} }}

/* Cancel / Save for Later buttons */
.cancel-btn, .save-later-btn {{
    background: none; border: 1px solid var(--border); cursor: pointer;
    font-size: 10px; padding: 2px 8px; border-radius: 4px; opacity: 0; transition: all 0.15s; white-space: nowrap;
}}
.cancel-btn {{ color: var(--danger); }}
.save-later-btn {{ color: var(--warning); }}
.task-item:hover .cancel-btn, .task-item:hover .save-later-btn,
.top-task-row:hover .cancel-btn, .top-task-row:hover .save-later-btn {{ opacity: 1; }}
.cancel-btn:hover {{ background: rgba(248,113,113,0.15); border-color: var(--danger); }}
.save-later-btn:hover {{ background: rgba(251,191,36,0.15); border-color: var(--warning); }}

/* Notes popover */
.notes-wrapper {{
    position: relative; display: inline-block; margin-left: 6px;
}}
.notes-indicator {{
    font-size: 11px; cursor: help; opacity: 0.6;
}}
.notes-wrapper:hover .notes-indicator {{ opacity: 1; }}
.notes-popover {{
    display: none; position: absolute; bottom: calc(100% + 8px); left: 50%;
    transform: translateX(-50%); z-index: 150;
    background: var(--surface2); border: 1px solid var(--border); border-radius: 8px;
    padding: 10px 14px; min-width: 220px; max-width: 400px;
    font-size: 12px; line-height: 1.6; color: var(--text);
    box-shadow: 0 8px 24px rgba(0,0,0,0.4);
    word-break: break-word; white-space: normal;
}}
.notes-popover::after {{
    content: ''; position: absolute; top: 100%; left: 50%; transform: translateX(-50%);
    border: 6px solid transparent; border-top-color: var(--border);
}}
.notes-popover a {{
    color: var(--accent); text-decoration: underline; word-break: break-all;
}}
.notes-popover a:hover {{ color: #93b8fd; }}
.notes-wrapper:hover .notes-popover {{ display: block; }}

/* Archived task notes */
.archived-notes {{
    font-size: 12px; color: var(--text-dim); margin-top: 4px;
    padding: 4px 8px; background: var(--surface2); border-radius: 4px;
    word-break: break-word;
}}
.archived-notes a {{ color: var(--accent); }}

/* Archived task items */
.archived-task {{
    align-items: center;
}}

@media (max-width: 768px) {{
    .sidebar {{ display: none; }}
    .main {{ margin-left: 0; padding: 16px; }}
    .stats-row {{ flex-wrap: wrap; }}
    .stat-card {{ min-width: calc(50% - 6px); }}
}}

/* ── R&D project tiles (rich) ── */
.rnd-projects {{ display: flex; flex-direction: column; gap: 14px; }}
/* v4 Wave 8: the per-folder directory header (.rnd-folder/.rnd-folder-head/
   .rnd-folder-tiles) was removed — projects render as a FLAT row list. */
.rnd-name {{ font-weight: 600; font-size: 14px; }}
.rnd-badge {{ font-size: 10px; font-weight: 700; padding: 1px 7px; border-radius: 4px; border: 1px solid var(--border); color: var(--text-dim); }}
.rnd-badge.rnd-p1 {{ background: rgba(248,113,113,.18); color: var(--danger); border-color: rgba(248,113,113,.3); }}
.rnd-badge.rnd-p2 {{ background: rgba(251,191,36,.15); color: var(--warning); border-color: rgba(251,191,36,.3); }}
.rnd-badge[class*="rnd-state-archived"], .rnd-badge[class*="rnd-state-future"], .rnd-badge[class*="rnd-state-retired"] {{ background: rgba(255,255,255,.04); }}
.rnd-imported {{ color: var(--text-dim); font-style: italic; font-size: 11px; }}
.rnd-running {{ color: var(--success); font-size: 11px; }}
.rnd-status-line {{ margin: 0; display: flex; flex-wrap: wrap; gap: 8px; }}
.rnd-lane {{ padding: 4px 10px; border-radius: 6px; background: #1b2030; font-size: 13px; }}
.rnd-lane.rnd-lane-empty {{ color: var(--text-dim); }}
.rnd-blurb {{ font-size: 12px; color: var(--text); opacity: .85; }}
.rnd-notes {{ font-size: 11.5px; color: var(--text-dim); background: rgba(255,255,255,.03); border-radius: 6px; padding: 5px 8px; white-space: pre-wrap; }}
.rnd-actions {{ display: flex; flex-wrap: wrap; gap: 5px; margin-top: 2px; }}
.rnd-mini {{ font-size: 11px; padding: 3px 9px; border-radius: 6px; border: 1px solid var(--border); background: var(--surface); color: var(--text); cursor: pointer; }}
.rnd-mini:hover {{ border-color: var(--accent); }}
.rnd-mini.rnd-pr-on {{ border-color: var(--accent); color: var(--accent); font-weight: 600; }}
.rnd-mini.rnd-open-btn {{ background: var(--accent); color: #0b1020; border-color: var(--accent); font-weight: 600; }}
.rnd-mini.rnd-accent {{ border-color: var(--accent); color: var(--accent); }}
/* v9 Wave 3 — collapsible project FOLDERS (group field; drag-to-group). */
.rnd-folder-toolbar {{ display: flex; align-items: center; gap: 10px; margin-bottom: 8px; }}
.rnd-newfolder-btn {{ font-size: 12px; padding: 6px 12px; border-radius: 7px; border: 1px solid rgba(108,156,252,.5); background: var(--surface2, #232733); color: var(--accent); cursor: pointer; }}
.rnd-newfolder-btn:hover {{ border-color: var(--accent); }}
.rnd-folder-hint {{ font-size: 11.5px; color: var(--text-dim); }}
.rnd-folder-list {{ display: flex; flex-direction: column; border: 1px solid var(--border); border-radius: 12px; overflow: hidden; }}
.rnd-folder {{ border-bottom: 1px solid var(--border); }}
.rnd-folder:last-child {{ border-bottom: none; }}
.rnd-folder-head {{ display: flex; align-items: center; gap: 8px; padding: 11px 14px; cursor: pointer; background: var(--surface2, #232733); }}
.rnd-folder-head:hover {{ background: var(--surface3, #2a2f3d); }}
.rnd-tw {{ font-size: 11px; color: var(--text-dim); width: 12px; flex: 0 0 auto; }}
.rnd-fname {{ font-size: 13.5px; font-weight: 600; }}
.rnd-fcount {{ font-size: 11px; color: var(--text-dim); }}
.rnd-fpath {{ font-size: 10.5px; color: var(--text-dim); font-family: ui-monospace, Consolas, monospace; margin-left: 6px; }}
.rnd-fsp {{ flex: 1; }}
.rnd-fdrop-hint {{ font-size: 11px; color: var(--accent); }}
.rnd-folder-body {{ display: flex; flex-direction: column; gap: 6px; padding: 6px 8px 8px; }}
.rnd-folder.rnd-collapsed .rnd-folder-body {{ display: none; }}
.rnd-folder.rnd-droptarget .rnd-folder-head {{ outline: 2px dashed var(--accent); outline-offset: -2px; }}
.rnd-grip {{ flex: 0 0 auto; color: var(--text-dim); font-size: 13px; cursor: grab; letter-spacing: -2px; }}
.rnd-row[draggable="true"] {{ cursor: grab; }}
.rnd-row.rnd-dragging {{ opacity: .5; }}
/* v9 Wave 4 — the Option-C "move on disk + group" confirm dialog. */
.rnd-move-overlay {{ position: fixed; inset: 0; z-index: 9000; background: rgba(0,0,0,.55); display: flex; align-items: center; justify-content: center; }}
.rnd-move-dlg {{ max-width: 560px; width: calc(100% - 40px); border: 1px solid rgba(239,68,68,.4); border-radius: 12px; background: #160f12; overflow: hidden; box-shadow: 0 12px 40px rgba(0,0,0,.6); }}
.rnd-move-h {{ padding: 10px 14px; background: rgba(239,68,68,.1); font-size: 14px; font-weight: 600; border-bottom: 1px solid rgba(239,68,68,.3); color: var(--text); }}
.rnd-move-b {{ padding: 13px 14px; font-size: 13px; color: var(--text); }}
.rnd-move-mono {{ font-family: ui-monospace, Consolas, monospace; font-size: 11.5px; color: #cdd2dc; background: #05070c; border: 1px solid var(--border); border-radius: 7px; padding: 8px 10px; margin: 9px 0; word-break: break-all; }}
.rnd-move-mono .rnd-move-arr {{ color: var(--accent); }}
.rnd-move-guard {{ font-size: 12px; color: var(--text-dim); margin-top: 8px; }}
.rnd-move-guard b {{ color: #e9dca8; }}
.rnd-move-acts {{ display: flex; flex-wrap: wrap; gap: 9px; padding: 11px 14px; border-top: 1px solid var(--border); }}
.rnd-move-btn {{ font-size: 12.5px; padding: 7px 12px; border-radius: 7px; border: 1px solid var(--border); background: var(--surface2, #232733); color: var(--text); cursor: pointer; }}
.rnd-move-btn:hover {{ border-color: var(--accent); }}
.rnd-move-btn.rnd-move-go {{ border-color: rgba(239,68,68,.55); background: rgba(239,68,68,.14); color: #ffd2d2; }}
/* v3 Wave 5 — thin full-width project ROWS (replace the square .rnd-tile). */
.rnd-folder-rows {{ display: flex; flex-direction: column; gap: 6px; }}
.rnd-row {{ display: flex; align-items: center; gap: 10px; width: 100%; padding: 8px 12px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface2, #232733); cursor: pointer; position: relative; }}
.rnd-seal-ico {{ width: 18px; height: 18px; border-radius: 4px; flex: 0 0 auto; object-fit: cover; }}
.rnd-row:hover {{ border-color: var(--accent); }}
.rnd-row:focus {{ outline: 2px solid var(--accent); outline-offset: 1px; }}
.rnd-dot {{ flex: 0 0 auto; width: 9px; height: 9px; border-radius: 50%; background: var(--text-dim); }}
.rnd-dot.rnd-dot-running {{ background: var(--success); box-shadow: 0 0 5px var(--success); }}
.rnd-dot.rnd-dot-idle {{ background: var(--text-dim); }}
.rnd-row .rnd-name {{ flex: 0 0 auto; white-space: nowrap; }}
.rnd-row-summary {{ flex: 2 1 0; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; font-size: 12px; color: var(--text); opacity: .85; }}
.rnd-row-summary.rnd-dim {{ color: var(--text-dim); opacity: .6; font-style: italic; }}
/* v6 Wave 7 — timely activity reflection: running indicator + "what's happening". */
.rnd-row-activity {{ flex: 3 1 0; min-width: 0; display: flex; align-items: center; gap: 8px; font-size: 11px; color: var(--text-dim); overflow: hidden; }}
.rnd-act-running {{ flex: 0 0 auto; display: inline-flex; align-items: center; gap: 4px; color: var(--success); font-weight: 600; }}
.rnd-act-pulse {{ width: 7px; height: 7px; border-radius: 50%; background: var(--success); box-shadow: 0 0 5px var(--success); animation: rndActPulse 1.4s ease-in-out infinite; }}
@keyframes rndActPulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: .35; }} }}
.rnd-act-latest {{ flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
.rnd-act-lane {{ text-transform: capitalize; color: var(--text); opacity: .85; }}
.rnd-act-title {{ color: var(--text); opacity: .9; }}
.rnd-act-status.rnd-act-green {{ color: var(--success); }}
.rnd-act-status.rnd-act-amber {{ color: #e0a02a; }}
.rnd-act-status.rnd-act-red {{ color: var(--danger, #e06c6c); }}
.rnd-act-status.rnd-act-grey {{ color: var(--text-dim); }}
.rnd-row-counts {{ flex: 0 0 auto; }}
.rnd-row-counts .rnd-status-line {{ gap: 5px; }}
.rnd-row-counts .rnd-lane {{ padding: 2px 7px; font-size: 11px; }}
/* v4 Wave 8 — per-row cost/tokens/time rollup + the R&D view's global window toggle. */
.rnd-row-roll {{ flex: 0 0 auto; font-size: 11px; color: var(--text-dim); white-space: nowrap; font-variant-numeric: tabular-nums; }}
.rnd-rows-rolltog {{ display: inline-flex; align-items: center; gap: 4px; margin-bottom: 8px; font-size: 11px; color: var(--text-dim); }}
.rnd-rows-rolltog-label {{ margin-right: 2px; }}
.rnd-rows-rolltog b {{ font-size: 10px; padding: 2px 8px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); color: var(--text-dim); font-weight: 600; cursor: pointer; }}
.rnd-rows-rolltog b.on {{ background: rgba(108,156,252,.15); color: var(--accent); border-color: var(--accent); }}
.rnd-kebab {{ flex: 0 0 auto; position: relative; }}
.rnd-kebab-btn {{ background: transparent; border: 1px solid transparent; color: var(--text-dim); font-size: 16px; line-height: 1; padding: 2px 7px; border-radius: 6px; cursor: pointer; }}
.rnd-kebab-btn:hover {{ border-color: var(--border); color: var(--text); }}
.rnd-kebab-menu {{ display: none; position: absolute; right: 0; top: 100%; margin-top: 4px; z-index: 30; background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 6px; flex-direction: column; gap: 4px; min-width: 120px; box-shadow: 0 6px 18px rgba(0,0,0,.4); }}
.rnd-kebab-menu.rnd-kebab-open {{ display: flex; }}
.rnd-kebab-menu .rnd-mini {{ width: 100%; text-align: left; }}
.rnd-mini.rnd-danger:hover {{ border-color: var(--danger); color: var(--danger); }}
.rnd-empty {{ color: var(--text-dim); font-size: 13px; }}
</style>
</head>
<body>
<div class="app">
  <nav class="sidebar">
    <div class="gwl-lockup">
      <img src="/vendor/brand/gwl-m-icon.svg?v={BUILD_ID}" alt="Ghost World Labs">
      <div class="gwl-wordmark">Ghost World <span class="gwl-accent">Labs</span></div>
    </div>
    <div class="gwl-badge">Powered by NextGen Nuclear <svg class="gwl-rad" width="12" height="12" viewBox="0 0 24 24" style="vertical-align:middle" role="img" aria-label="radiation"><circle cx="12" cy="12" r="2.6" fill="#22c55e"/><path fill="#22c55e" d="M13.6 14.77L17.5 21.53A11 11 0 0 1 6.5 21.53L10.4 14.77A3.2 3.2 0 0 0 13.6 14.77ZM8.8 12L1 12A11 11 0 0 1 6.5 2.47L10.4 9.23A3.2 3.2 0 0 0 8.8 12ZM13.6 9.23L17.5 2.47A11 11 0 0 1 23 12L15.2 12A3.2 3.2 0 0 0 13.6 9.23Z"/></svg></div>
    <h1><span>&#9875;</span> Anchor</h1>
    <div class="subtitle">J.C. Liechty — Life Dashboard</div>
    <div class="nav-section">
      <h3>Views</h3>
      <div class="nav-item active" data-view="dashboard" onclick="showView('dashboard')">
        <span class="dot" style="background:var(--accent)"></span> Dashboard
      </div>
      <div class="nav-item" data-view="inbox" onclick="showView('inbox')">
        <span class="dot" style="background:var(--warning)"></span> Inbox <span class="count">{len(inbox)}</span>
      </div>
      <div class="nav-item" data-view="rnd" onclick="showView('rnd')">
        <span class="dot" style="background:#6c9cfc"></span> R&amp;D
      </div>
      <div class="nav-item" data-view="rnd-archive" onclick="showView('rnd-archive')">
        <span class="dot" style="background:var(--text-dim)"></span> R&amp;D Archive
      </div>
    </div>
    <div class="nav-section">
      <h3>Domains</h3>
      {nav_items}
    </div>
    <div class="balance-widget">
      <h4>Domain Balance</h4>
      <div class="balance-bars">
        {balance_rows}
      </div>
    </div>
  </nav>

  <div class="main">
    <!-- v4 Wave 8 — Option B masthead lockup (Anchor · divider · GWL mark +
         wordmark · NextGen Nuclear pill). Single vendored brand mark. -->
    <div class="masthead">
      <div class="mh-title"><span class="mh-anchor">&#9875;</span>Anchor</div>
      <div class="mh-vdiv"></div>
      <div class="mh-lock">
        <img src="/vendor/brand/gwl-m-icon.svg?v={BUILD_ID}" alt="Ghost World Labs">
        <div class="mh-words">
          <div class="mh-w1">Ghost World <span class="gwl-accent">Labs</span></div>
          <div class="mh-w2">R&amp;D Mission Control</div>
        </div>
      </div>
      <div class="mh-spacer"></div>
      <button id="tokenBtn" onclick="if(setAnchorToken())location.reload();" title="Set or clear the Anchor access token" style="display:{auth_token_btn_display};margin-right:10px;background:transparent;border:1px solid var(--border);color:var(--text);border-radius:6px;padding:4px 8px;cursor:pointer;font-size:14px">&#128273;</button>
      <div class="mh-pill">Powered by NextGen Nuclear <svg class="gwl-rad" width="12" height="12" viewBox="0 0 24 24" style="vertical-align:middle" role="img" aria-label="radiation"><circle cx="12" cy="12" r="2.6" fill="#22c55e"/><path fill="#22c55e" d="M13.6 14.77L17.5 21.53A11 11 0 0 1 6.5 21.53L10.4 14.77A3.2 3.2 0 0 0 13.6 14.77ZM8.8 12L1 12A11 11 0 0 1 6.5 2.47L10.4 9.23A3.2 3.2 0 0 0 8.8 12ZM13.6 9.23L17.5 2.47A11 11 0 0 1 23 12L15.2 12A3.2 3.2 0 0 0 13.6 9.23Z"/></svg></div>
    </div>
    <!-- Dashboard view -->
    <div class="view" id="view-dashboard">
      {health_banner_html}
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>Dashboard</h2>
          <button class="btn btn-sm" onclick="refresh()" style="font-size:11px;padding:4px 10px;background:var(--accent)">&#8635; Update</button>
          <button class="btn btn-sm" onclick="window.open('/api/rnd/zombie_hunter_report' + (_anchorToken() ? ('?token=' + encodeURIComponent(_anchorToken())) : ''), '_blank')" style="font-size:11px;padding:4px 10px;background:var(--surface2);border:1px solid var(--accent);color:var(--text);display:inline-flex;align-items:center;gap:4px;" title="Zombie Hunter Radar"><img src="/vendor/brand/zombie-hunter-radar.jpg" style="width:14px;height:14px;border-radius:2px;" alt="" /> Zombie Hunter</button>
          <button class="btn btn-sm" onclick="window.open('/foundry','_blank')" style="font-size:11px;padding:4px 10px;background:var(--surface2);border:1px solid var(--accent);color:var(--text);display:inline-flex;align-items:center;gap:4px;" title="Skill Foundry — library, knowledge graph, sleep runs"><img src="/vendor/brand/skill-foundry-icon.jpg?v={BUILD_ID}" style="width:14px;height:14px;border-radius:2px;" alt="" /> Skill Foundry</button>
          <!-- Ecgberht High Seat moved out of this button row (2026-07-27): it is
               now the FIRST dashboard tile below, and carries the ⚑ badge with
               it. The badge (raise-queue length) is still the only ambient
               Ecgberht signal anywhere in Anchor. -->
          <button class="btn btn-sm btn-outline" id="completedBtn" onclick="showView('completed')" style="font-size:11px;padding:4px 10px">&#10003; Completed ({len(done_tasks)})</button>
          <button class="btn btn-sm btn-outline" onclick="showView('cancelled')" style="font-size:11px;padding:4px 10px;border-color:var(--danger);color:var(--danger)">&#10007; Cancelled ({len(cancelled_tasks)})</button>
          <button class="btn btn-sm btn-outline" onclick="showView('saved')" style="font-size:11px;padding:4px 10px;border-color:var(--warning);color:var(--warning)">&#128337; Saved ({len(saved_tasks)})</button>
          <!-- 2026-05-12: Stop button removed. Server lifecycle is owned by
               the NSSM "anchor" service on gwl-server. To restart, run
               `nssm restart anchor` on gwl-server. -->
          <!-- 2026-07-02: model-flex posture chip on the HOME header too (John);
               dismissible via its inline × (localStorage 'mflexDismissed'). The
               home stylesheet lacks the project window's .mflex rules, so a
               scoped copy rides along right here. -->
          <style>.mflex{{display:inline-flex;align-items:center;gap:4px;font-size:10.5px;font-weight:600;padding:3px 9px;border-radius:7px;border:1px solid var(--border);background:var(--surface);color:var(--text-dim);white-space:nowrap;cursor:default}}.mflex.mflex-both{{border-color:rgba(34,197,94,.45);color:var(--success);background:rgba(34,197,94,.12)}}.mflex.mflex-claude{{border-color:rgba(56,139,253,.45);color:var(--accent)}}.mflex.mflex-gemini{{border-color:rgba(234,179,8,.5);color:#eab308;background:rgba(234,179,8,.1)}}.mflex.mflex-none{{border-color:rgba(248,81,73,.5);color:var(--danger)}}</style>
          </div>
        <div class="date">{today_str}</div>
      </div>

      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;">
          {render_model_flex_badge()}
          {render_model_prefs_controls()}
          {render_steward_control()}
          <button class="btn btn-sm" onclick="window.open('/doctor' + (_anchorToken() ? ('?token=' + encodeURIComponent(_anchorToken())) : ''), '_blank')" style="font-size:12px;padding:4px 10px;background:#131828;border:1px solid #10b981;color:#10b981;font-weight:600;border-radius:6px;cursor:pointer;" title="Anchor Doctor Diagnostic">&#10010; Anchor Doctor</button>
        </div>
      </div>

      <div class="stats-row">
        <div class="stat-card"><div class="num">{len([p for p in projects if p["status"]=="active"])}</div><div class="label">Active Projects</div></div>
        <div class="stat-card"><div class="num">{len(active)}</div><div class="label">Open Tasks</div></div>
        <div class="stat-card"><div class="num">{len(done_tasks)}</div><div class="label">Completed</div></div>
        <div class="stat-card"><div class="num">{len(inbox)}</div><div class="label">In Inbox</div></div>
      </div>

      <!-- ── Tile 1 · High Seat ───────────────────────────────────────────
           The Ecgberht portfolio steward, rendered INSIDE the tile (it used to
           be a floating dock opened from the toolbar). The ⚑ badge rides on the
           summary and stays the only ambient Ecgberht signal in Anchor. -->
      <details class="dash-tile tile-seat" id="tile-highseat"
               ontoggle="if(this.open)ecgHighSeatMountInline()">
        <summary title="{steward_label} — the {steward_hs_name} (all your projects, one place to steer them)">
          <img class="tile-ico" src="{steward_hs_src}" alt="" onerror="this.style.display='none'" />
          {steward_hs_name}
          <span class="tile-count">{steward_label} &mdash; all your projects, one place to steer them</span>
          <span class="ecg-hs-badge" id="ecgHighSeatBadge"></span>
          <!-- The docked-overlay entry point. Ecgberht's frozen HIGH_SEAT_MOUNT
               contract is presentation="docked_overlay" on surface="main_dashboard",
               so the main dashboard must still be able to raise the dock; the
               inline tile above is the everyday surface, this is the pop-out.
               It sits INSIDE the tile (not back in the toolbar button row) so the
               ⚑ badge remains the only ambient Ecgberht signal in Anchor. -->
          <button class="btn btn-sm btn-outline" id="ecgHighSeatBtn"
                  onclick="event.preventDefault();event.stopPropagation();openEcgberhtHighSeat()"
                  title="Open the {steward_hs_name} as a floating dock"
                  style="font-size:11px;padding:3px 9px;font-weight:500">&#8599; Dock</button>
          <span class="tile-hint"></span>
        </summary>
        <div class="tile-body"><div class="ecg-hs-inline" id="ecgHighSeatInline"></div></div>
      </details>

      <!-- ── Tile 2 · Workbench ──────────────────────────────────────────── -->
      <details class="dash-tile" id="dashboard-workbench-details">
        <summary>
          <img class="tile-ico" src="/vendor/brand/workbench-icon.jpg?v={BUILD_ID}" alt="" onerror="this.style.display='none'" />
          Workbench
          <span class="tile-count">the dashboard's own project cockpit</span>
          <span class="tile-hint"></span>
        </summary>
        <div class="tile-body" style="padding:0">
          <iframe src="/project/__dashboard__" style="width:100%; height:1100px; border:none; display:block;"></iframe>
        </div>
      </details>

      <!-- ── Tile 3 · Tasks ───────────────────────────────────────────────
           One expanded window holding BOTH groups: P1 (+ anything due now) at
           the top, then P2/P3 below it. -->
      <details class="dash-tile" id="tile-tasks">
        <summary>
          <span class="tile-glyph" aria-hidden="true">&#10003;</span>
          Tasks
          <span class="tile-count">{len(top_tasks)} priority &middot; {len(other_tasks)} other</span>
          <span class="tile-hint"></span>
        </summary>
        <div class="tile-body">
          <div style="display:flex;justify-content:flex-end;margin-bottom:10px">
            <button class="btn btn-sm" onclick="toggleAddTask()">+ Add Task</button>
          </div>
          <div class="add-task-bar" id="addTaskBar" style="display:none;flex-wrap:wrap">
            <input type="text" id="newTask" placeholder="What needs to be done?" onkeypress="if(event.key==='Enter')addTask()" style="min-width:200px" />
            <select id="newDomain">
              <option value="academic">Academic</option>
              <option value="commercial">Commercial</option>
              <option value="writing">Writing</option>
              <option value="family">Family</option>
              <option value="personal">Personal</option>
            </select>
            <select id="newPriority">
              <option value="1">P1</option>
              <option value="2" selected>P2</option>
              <option value="3">P3</option>
            </select>
            <div class="date-picker-wrap">
              <input type="date" id="newDue" title="Due date (optional)" />
              <button type="button" class="cal-toggle" onclick="toggleCalendar('newDue', this)" title="Open calendar">&#128197;</button>
              <div class="cal-popup" id="cal_newDue"></div>
            </div>
            <button class="btn btn-sm" onclick="addTask()">Add</button>
            <input type="text" id="newNotes" placeholder="Notes — email, link, reference (optional)" style="min-width:200px;flex:1;margin-top:4px" />
          </div>

          <div class="top-tasks-box">
            <div class="top-header">
              <h3>Priority 1 &amp; due now</h3>
              <span class="top-progress">{top_done} / {len(top_tasks)} done</span>
            </div>
            {"".join(top_task_row(t) for t in top_tasks)}
          </div>

          <div class="section-header"><h3>Priority 2 &amp; 3</h3></div>
          <div class="task-list">
            {"".join(task_item(t) for t in other_tasks) or '<div class="empty-msg">No P2/P3 tasks.</div>'}
          </div>
        </div>
      </details>

      <!-- ── Tile 4 · Projects ────────────────────────────────────────────
           The R&D project folders (+ New folder, + New Project) first, then the
           markdown-tracked P1 and P2+ project cards — all in one window. -->
      <details class="dash-tile" id="tile-projects">
        <summary>
          <img class="tile-ico" src="/vendor/brand/{steward_seal_icon}?v={BUILD_ID}" alt="" onerror="this.style.display='none'" />
          Projects
          <span class="tile-count">{projects_tile_count}</span>
          <span class="tile-hint">{steward_projects_hint}</span>
        </summary>
        <div class="tile-body">
          <div class="section-header" style="display:flex;align-items:center;gap:8px">
            <h3>R&amp;D Projects</h3>
            <button class="btn btn-sm" onclick="openNewProject()" style="font-size:11px;padding:4px 10px;background:var(--accent)">+ New Project</button>
          </div>
          {rnd_projects_html}
          {f'<div class="section-header"><h3>Priority 1 Projects</h3></div><div class="card-grid">{"".join(project_card(p) for p in p1_projects)}</div>' if p1_projects else ""}
          {f'<div class="section-header"><h3>Priority 2+ Projects</h3></div><div class="card-grid">{"".join(project_card(p) for p in p2_projects)}</div>' if p2_projects else ""}
        </div>
      </details>
    </div>

    <!-- Completed view -->
    <div class="view" id="view-completed" style="display:none">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>Completed</h2>
          <button class="btn btn-sm btn-outline" onclick="showView('dashboard')" style="font-size:11px;padding:4px 10px">&#8592; Back</button>
        </div>
        <div class="date">{today_str}</div>
      </div>
      <div class="task-list">{completed_items}</div>
    </div>

    <!-- Cancelled view -->
    <div class="view" id="view-cancelled" style="display:none">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>Cancelled Tasks</h2>
          <button class="btn btn-sm btn-outline" onclick="showView('dashboard')" style="font-size:11px;padding:4px 10px">&#8592; Back</button>
        </div>
        <div class="date">{today_str}</div>
      </div>
      <p style="color:var(--text-dim);font-size:13px;margin-bottom:16px">Tasks you decided not to do. Click Restore to move one back to active.</p>
      <div class="task-list">{cancelled_items}</div>
    </div>

    <!-- Saved for Later view -->
    <div class="view" id="view-saved" style="display:none">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>Saved for Later</h2>
          <button class="btn btn-sm btn-outline" onclick="showView('dashboard')" style="font-size:11px;padding:4px 10px">&#8592; Back</button>
        </div>
        <div class="date">{today_str}</div>
      </div>
      <p style="color:var(--text-dim);font-size:13px;margin-bottom:16px">Tasks on hold. Click Restore to move one back to active.</p>
      <div class="task-list">{saved_items}</div>
    </div>

    <!-- Inbox view -->
    <div class="view" id="view-inbox" style="display:none">
      <div class="page-header"><h2>Inbox</h2></div>
      <div class="inbox-input-row">
        <input type="text" id="captureText" placeholder="Quick capture — type anything and hit Enter..." onkeydown="if(event.key==='Enter')captureItem()">
        <select id="captureDomain">
          <option value="">No tag</option>
          <option value="academic">Academic</option>
          <option value="writing">Writing</option>
          <option value="family">Family</option>
          <option value="commercial">Commercial</option>
          <option value="personal">Personal</option>
        </select>
        <button class="btn" onclick="captureItem()">Add</button>
      </div>
      <div class="task-list">{inbox_items}</div>
    </div>

    <!-- R&D control surface view -->
    <div class="view" id="view-rnd" style="display:none">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>R&amp;D Projects</h2>
          <button class="btn btn-sm" onclick="openNewProject()" style="font-size:11px;padding:4px 10px;background:var(--accent)">+ New Project</button>
          <!-- foundry-v2 Wave 9: the Anchor button that launches the Foundry GUI (stateless read surface over the live engine) -->
          <button class="btn btn-sm" onclick="window.open('/foundry','_blank')" style="font-size:11px;padding:4px 10px;display:inline-flex;align-items:center;gap:5px" title="Skill Foundry — library, knowledge graph, runs (stateless read surface)"><img src="/vendor/brand/skill-foundry-icon.jpg?v={BUILD_ID}" style="height:15px;width:15px;border-radius:3px;object-fit:cover" alt=""> Foundry</button>
        </div>
        <div class="date">{today_str}</div>
      </div>
      <p style="color:var(--text-dim);font-size:13px;margin-bottom:16px">Per-project R&amp;D control surface. <b>Open</b> a project to launch research / plan / build jobs in its own window (run several at once). Use the tile buttons to change priority, add notes, or archive / retire a project. <a href="#" onclick="showView('rnd-archive');return false" style="color:var(--accent)">View Archive &#8594;</a></p>
      <div id="rndProjectsRows">{rnd_projects_html}</div>
    </div>

    <div class="view" id="view-rnd-archive" style="display:none">
      <div class="page-header">
        <div style="display:flex;align-items:center;gap:8px">
          <h2>R&amp;D Archive</h2>
          <button class="btn btn-sm" onclick="showView('rnd')" style="font-size:11px;padding:4px 10px">&#8592; Active projects</button>
        </div>
        <div class="date">{today_str}</div>
      </div>
      <p style="color:var(--text-dim);font-size:13px;margin-bottom:16px">Archived, future, and retired projects (kept, reviewable). Use <b>Reactivate</b> to bring one back to the active list.</p>
      {rnd_archive_html}
    </div>

    <!-- Domain views -->
    {domain_views}

    <!-- Ghost World Labs footer credit (Wave 9) -->
    <div class="gwl-footer">
      <img src="/vendor/brand/gwl-m-icon.svg?v={BUILD_ID}" alt="Ghost World Labs">
      <span>A <b class="gwl-accent">Ghost World Labs</b> tool &bull; Powered by NextGen Nuclear <svg class="gwl-rad" width="11" height="11" viewBox="0 0 24 24" style="vertical-align:middle" role="img" aria-label="radiation"><circle cx="12" cy="12" r="2.6" fill="#22c55e"/><path fill="#22c55e" d="M13.6 14.77L17.5 21.53A11 11 0 0 1 6.5 21.53L10.4 14.77A3.2 3.2 0 0 0 13.6 14.77ZM8.8 12L1 12A11 11 0 0 1 6.5 2.47L10.4 9.23A3.2 3.2 0 0 0 8.8 12ZM13.6 9.23L17.5 2.47A11 11 0 0 1 23 12L15.2 12A3.2 3.2 0 0 0 13.6 9.23Z"/></svg></span>
    </div>
  </div>
</div>

<!-- Edit Task Modal -->
<div class="modal-overlay" id="editTaskModal">
  <div class="modal">
    <h3>Edit Task</h3>
    <input type="hidden" id="editTaskOld" />
    <label>Task</label>
    <input type="text" id="editTaskText" />
    <label>Domain</label>
    <select id="editTaskDomain">
      <option value="academic">Academic</option>
      <option value="commercial">Commercial</option>
      <option value="writing">Writing</option>
      <option value="family">Family</option>
      <option value="personal">Personal</option>
    </select>
    <label>Priority</label>
    <select id="editTaskPriority">
      <option value="1">P1 — Urgent</option>
      <option value="2">P2 — Important</option>
      <option value="3">P3 — Normal</option>
    </select>
    <label>Energy</label>
    <select id="editTaskEnergy">
      <option value="low">Low</option>
      <option value="med">Med</option>
      <option value="high">High</option>
    </select>
    <label>Due Date</label>
    <div class="date-picker-wrap">
      <input type="date" id="editTaskDue" />
      <button type="button" class="cal-toggle" onclick="toggleCalendar('editTaskDue', this)" title="Open calendar">&#128197;</button>
      <div class="cal-popup" id="cal_editTaskDue"></div>
    </div>
    <label>Notes</label>
    <textarea id="editTaskNotes" placeholder="Email, link, reference, context..."></textarea>
    <div class="modal-actions">
      <button class="btn btn-outline" onclick="closeModal('editTaskModal')">Cancel</button>
      <button class="btn" onclick="saveEditTask()">Save</button>
    </div>
  </div>
</div>

<!-- Edit Project Modal -->
<div class="modal-overlay" id="editProjectModal">
  <div class="modal">
    <h3>Edit Project</h3>
    <input type="hidden" id="editProjOld" />
    <label>Name</label>
    <input type="text" id="editProjName" />
    <label>Domain</label>
    <select id="editProjDomain">
      <option value="academic">Academic</option>
      <option value="commercial">Commercial</option>
      <option value="writing">Writing</option>
      <option value="family">Family</option>
      <option value="personal">Personal</option>
    </select>
    <label>Priority</label>
    <select id="editProjPriority">
      <option value="1">P1 — Top Tier</option>
      <option value="2">P2 — Important</option>
      <option value="3">P3 — Normal</option>
    </select>
    <label>Status</label>
    <select id="editProjStatus">
      <option value="active">Active</option>
      <option value="paused">Paused</option>
      <option value="completed">Completed</option>
      <option value="blocked">Blocked</option>
    </select>
    <label>Effort</label>
    <select id="editProjEffort">
      <option value="low">Low</option>
      <option value="med">Med</option>
      <option value="high">High</option>
    </select>
    <label>Due Date</label>
    <div class="date-picker-wrap">
      <input type="date" id="editProjDue" />
      <button type="button" class="cal-toggle" onclick="toggleCalendar('editProjDue', this)" title="Open calendar">&#128197;</button>
      <div class="cal-popup" id="cal_editProjDue"></div>
    </div>
    <label>Next Step</label>
    <input type="text" id="editProjNext" />
    <div class="modal-actions">
      <button class="btn btn-outline" onclick="closeModal('editProjectModal')">Cancel</button>
      <button class="btn" onclick="saveEditProject()">Save</button>
    </div>
  </div>
</div>

<!-- New R&D Project Modal -->
<div class="modal-overlay" id="newProjectModal">
  <div class="modal">
    <h3>New R&amp;D Project</h3>
    <div style="display:flex;gap:8px;margin-bottom:8px">
      <button type="button" class="btn btn-sm" id="npModeNewBtn" onclick="npSetMode('new_folder')">Create new folder</button>
      <button type="button" class="btn btn-sm btn-outline" id="npModeExistingBtn" onclick="npSetMode('existing')">Select existing</button>
    </div>
    <label>Project name</label>
    <input type="text" id="npName" placeholder="Project name" oninput="npNameEdited(); npUpdatePreview()" />
    <label>Priority</label>
    <select id="npPriority">
      <option value="1">P1 — Top Tier</option>
      <option value="2" selected>P2 — Important</option>
      <option value="3">P3 — Normal</option>
    </select>
    <!-- Create-new-folder mode -->
    <div id="npNewFolderFields">
      <label>Parent path</label>
      <input type="text" id="npParentPath" placeholder="e.g. C:\\dev" oninput="npUpdatePreview()" />
      <div id="npPreviewPath" style="font-size:11px;color:var(--text-dim);margin-top:4px;font-style:italic"></div>
      <label style="display:flex;align-items:center;gap:6px;margin-top:6px">
        <input type="checkbox" id="npGitInit" /> Initialize git repo
      </label>
    </div>
    <!-- Select-existing mode (Explorer-style expandable TREE) -->
    <div id="npExistingFields" style="display:none">
      <input type="hidden" id="npFolderPath" />
      <label>Browse to a folder on gwl-server</label>
      <div class="rnd-picker-err" id="npBrowseErr" style="display:none"></div>
      <div class="rnd-tree" id="npTree" role="tree"></div>
      <button type="button" class="btn btn-sm rnd-use-btn" id="npSelectHereBtn" style="margin-top:8px" onclick="npSelectCurrent()">&#10003; Use this folder</button>
      <div class="rnd-picker-selected empty" id="npSelected">No folder selected yet</div>
    </div>
    <div class="modal-actions">
      <button class="btn btn-outline" onclick="closeModal('newProjectModal')">Cancel</button>
      <button class="btn" onclick="createNewProject()">Create</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<!-- v9 Wave 4 — the Option-C "move on disk + group" confirm dialog. Hidden by
     default; shown when a project row is dropped into a folder header. -->
<div class="rnd-move-overlay" id="rndMoveOverlay" style="display:none"
     onclick="if(event.target===this)rndMoveCancel()">
  <div class="rnd-move-dlg" role="dialog" aria-modal="true"
       aria-labelledby="rndMoveTitle">
    <div class="rnd-move-h" id="rndMoveTitle">Move project into folder?</div>
    <div class="rnd-move-b">
      <span id="rndMoveLede">You dragged a project into a folder. Also move its
      directory on disk to match?</span>
      <div class="rnd-move-mono" id="rndMovePaths"></div>
      <div class="rnd-move-guard">Safety: the move is <b>refused for the Anchor
      app itself</b> and for any project with a <b>live session</b> (stop them
      first). The move is atomic — folder moved, registry + git worktrees +
      discovery re-pointed — and rolls back if anything fails.</div>
    </div>
    <div class="rnd-move-acts">
      <button class="rnd-move-btn rnd-move-go" type="button"
              id="rndMoveGo">Move on disk + group</button>
      <button class="rnd-move-btn" type="button" id="rndMoveJust">Just group
      (leave files where they are)</button>
      <button class="rnd-move-btn" type="button"
              onclick="rndMoveCancel()">Cancel</button>
    </div>
  </div>
</div>

<script>
// Heartbeat disabled — the server runs until explicitly stopped so the
// dashboard is instantly available when you return to the tab later.

// ── Access token (D4) ──
// Kept ONLY in this browser's localStorage; sent as X-Anchor-Token on mutating
// POSTs; NEVER embedded in the served HTML (GET is unauthenticated). When the
// server has no ANCHOR_TOKEN set, auth is off and the header is ignored.
window.ANCHOR_AUTH_REQUIRED = {auth_required_js};
// W2 contract shim: the versioned bootstrap — apiCall declares this build id on
// every mutating POST (X-Anchor-Build); a mismatch renders the reload banner.
window.ANCHOR_BOOT = {anchor_boot_js};
function _anchorToken() {{ try {{ return localStorage.getItem('anchor_token') || ''; }} catch (e) {{ return ''; }} }}
// ── One-time launcher token hand-off (v1.1.3 share-fix) ──
// launch_anchor_dashboard.py opens this page ONCE as /?token=<minted>. Store
// it (localStorage — same slot the manual paste uses), mint the HttpOnly auth
// cookie so page NAVIGATION (/project/, /report/, term_ws…) authenticates,
// then STRIP the token from the URL/history. Loopback-only by construction;
// after this runs no page URL carries the token again.
(function () {{
    try {{
        var _q = new URLSearchParams(window.location.search);
        var _t = (_q.get('token') || '').trim();
        if (!_t) return;
        try {{ localStorage.setItem('anchor_token', _t); }} catch (e) {{}}
        try {{
            fetch('/api/auth/login', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json',
                            'X-Anchor-Token': _t }},
                body: JSON.stringify({{ token: _t }})
            }});
        }} catch (e) {{}}
        _q.delete('token');
        var _rest = _q.toString();
        history.replaceState(null, '',
            window.location.pathname + (_rest ? '?' + _rest : '') +
            window.location.hash);
    }} catch (e) {{}}
}})();
function setAnchorToken(opts) {{
    const cur = _anchorToken();
    // Do NOT re-offer a token the server just REJECTED (2026-07-28). The prompt
    // used to pre-fill the saved value even when that value had just produced a
    // 401, so pressing OK re-sent the known-bad token and the user looped. After
    // a token rotation this is exactly what happens on every device that still
    // holds the old one — "it was still saved" was the symptom.
    const rejected = !!(opts && opts.rejected) && !!cur;
    const msg = rejected
        ? 'Your saved Anchor token was REJECTED (it is probably out of date).\\nPaste the current token:'
        : 'Paste your Anchor access token:';
    const t = window.prompt(msg, rejected ? '' : cur);
    if (t === null) return false;
    try {{ if (t) {{ localStorage.setItem('anchor_token', t.trim()); }} else {{ localStorage.removeItem('anchor_token'); }} }} catch (e) {{}}
    return true;
}}
// On first load, if the server requires auth and we have no token yet, ask once.
// Once stored, this never fires again (token persists in localStorage).
window.addEventListener('DOMContentLoaded', function () {{
    if (window.ANCHOR_AUTH_REQUIRED && !_anchorToken()) {{ setAnchorToken(); }}
}});

// ── Global 401 auto-reprompt (self-service token) ──
// A fresh origin (e.g. a laptop on the tailnet IP) has no token in this origin's
// localStorage → token-gated reads return 401 and dynamic content comes up empty.
// Wrap window.fetch so a 401 (auth on, not already prompting) re-prompts for the
// token and reloads — every read then retries with the new token. Non-401
// responses pass through UNCHANGED (the body/stream is never touched).
// /api/version is public (returns 200) so the cache-bust poll never trips this.
(function () {{
    if (window.__anchorFetchWrapped) return;
    window.__anchorFetchWrapped = true;
    const _origFetch = window.fetch.bind(window);
    let prompting = false;
    // Rewrite a stale ?token= in a URL so a retry carries the NEW token.
    function _retok(u) {{
        try {{
            const t = _anchorToken();
            if (!t) return u;
            return String(u).replace(/([?&]token=)[^&]*/, '$1' + encodeURIComponent(t));
        }} catch (e) {{ return u; }}
    }}
    window.fetch = function () {{
        const _args = arguments;
        return _origFetch.apply(null, _args).then(function (resp) {{
            if (resp && resp.status === 401 && window.ANCHOR_AUTH_REQUIRED && !prompting) {{
                prompting = true;
                try {{
                    // RETRY, DO NOT RELOAD (2026-07-28). This used to be
                    // `location.reload()`, which threw away everything the user
                    // had typed — the High Seat saybox draft and the in-flight
                    // act itself. After a token rotation that is guaranteed data
                    // loss on the first click, and it made the steward unusable.
                    // We already hold the original arguments, so re-issue the
                    // SAME request with the new token instead.
                    if (setAnchorToken({{ rejected: true }})) {{
                        prompting = false;
                        const a0 = _args[0];
                        if (typeof a0 === 'string') {{
                            const a1 = _args[1] ? Object.assign({{}}, _args[1]) : undefined;
                            if (a1 && a1.headers) {{
                                try {{
                                    const h = new Headers(a1.headers);
                                    if (h.has('X-Anchor-Token')) h.set('X-Anchor-Token', _anchorToken());
                                    a1.headers = h;
                                }} catch (e) {{}}
                            }}
                            return _origFetch(_retok(a0), a1).then(function (r2) {{
                                // Still refused with a fresh token — the token is
                                // wrong, not stale. Reload is the honest last resort.
                                if (r2 && r2.status === 401) location.reload();
                                return r2;
                            }});
                        }}
                        // Non-string input (a Request): its body may already be
                        // consumed, so a retry is not safe. Fall back to reload.
                        location.reload();
                    }}
                }} finally {{
                    prompting = false;
                }}
            }}
            // W2 contract shim: a structured 409 build-mismatch means this tab
            // predates the current deploy — show the 'reload required' banner.
            // The body is read off a CLONE so the caller's .json() still works.
            if (resp && resp.status === 409) {{
                try {{
                    resp.clone().json().then(function (d) {{
                        if (d && d.error === 'build-mismatch') _showReloadBanner();
                    }}).catch(function () {{}});
                }} catch (e) {{}}
            }}
            return resp;
        }});
    }};
}})();

// ── W2 contract shim: the 'reload required' banner ──
// Idempotent; fixed to the top of the viewport; one click reloads onto the
// new build. Matched by the structured 409 body ({{error:'build-mismatch'}}).
function _showReloadBanner() {{
    if (document.getElementById('anchorReloadBanner')) return;
    const d = document.createElement('div');
    d.id = 'anchorReloadBanner';
    d.setAttribute('role', 'alert');
    d.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:2147483647;' +
        'background:#b45309;color:#fff;padding:10px 16px;text-align:center;' +
        'font:600 14px/1.4 system-ui,sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.4)';
    d.innerHTML = 'Anchor was updated — this page is out of date. ' +
        '<button onclick="location.reload()" style="margin-left:10px;padding:4px 12px;' +
        'border:1px solid #fff;border-radius:6px;background:transparent;color:#fff;' +
        'cursor:pointer;font:inherit">Reload</button>';
    (document.body || document.documentElement).appendChild(d);
}}

async function apiCall(endpoint, body) {{
    // Retry once on network failure — the server may have briefly paused
    // (e.g. GC, slow I/O) and the browser throttled our heartbeat.
    async function _doFetch() {{
        const headers = {{'Content-Type': 'application/json'}};
        const tok = _anchorToken();
        if (tok) headers['X-Anchor-Token'] = tok;
        // W2 contract shim: declare this page's build id on every mutating
        // POST (a stale tab gets the structured 409 → the reload banner).
        const bid = (window.ANCHOR_BOOT && window.ANCHOR_BOOT.build_id) || '';
        if (bid) headers['X-Anchor-Build'] = bid;
        const r = await fetch(endpoint, {{
            method: 'POST',
            headers: headers,
            body: JSON.stringify(body)
        }});
        return await r.json();
    }}
    try {{
        let data;
        try {{ data = await _doFetch(); }}
        catch(e1) {{
            await new Promise(res => setTimeout(res, 400));
            data = await _doFetch();
        }}
        // Auth required but missing/stale → let the user supply it, then retry once.
        if (data && data.error === 'unauthorized' && setAnchorToken()) {{
            data = await _doFetch();
        }}
        if (data.ok) {{
            showToast(data.message || 'Done!');
            setTimeout(() => window.location.reload(), 600);
        }} else {{
            showToast('Error: ' + (data.error || 'unknown'));
        }}
    }} catch(e) {{
        showToast('Connection error: ' + e.message + ' — the server may have stopped. Relaunch the dashboard.');
    }}
}}

function showToast(msg) {{
    const t = document.getElementById('toast');
    t.textContent = msg;
    t.style.display = 'block';
    setTimeout(() => t.style.display = 'none', 2500);
}}

// ── Calendar Picker ──
let _calOpen = null;   // currently open calendar popup element
let _calInput = null;   // the date input it controls
let _calMonth = null;   // displayed month (0-11)
let _calYear = null;    // displayed year

function toggleCalendar(inputId, btn) {{
    const popup = document.getElementById('cal_' + inputId);
    const input = document.getElementById(inputId);
    if (_calOpen && _calOpen === popup) {{ closeAllCalendars(); return; }}
    closeAllCalendars();
    _calOpen = popup;
    _calInput = input;
    // Start on the input's current value or today
    const cur = input.value ? new Date(input.value + 'T00:00:00') : new Date();
    _calMonth = cur.getMonth();
    _calYear = cur.getFullYear();
    renderCalendar();
    popup.classList.add('open');
}}

function closeAllCalendars() {{
    document.querySelectorAll('.cal-popup.open').forEach(el => el.classList.remove('open'));
    _calOpen = null;
    _calInput = null;
}}

function renderCalendar() {{
    if (!_calOpen) return;
    const today = new Date();
    const todayStr = today.getFullYear() + '-' + String(today.getMonth()+1).padStart(2,'0') + '-' + String(today.getDate()).padStart(2,'0');
    const selectedStr = _calInput.value || '';
    const monthNames = ['January','February','March','April','May','June','July','August','September','October','November','December'];
    const dows = ['Su','Mo','Tu','We','Th','Fr','Sa'];

    const firstDay = new Date(_calYear, _calMonth, 1).getDay();
    const daysInMonth = new Date(_calYear, _calMonth + 1, 0).getDate();
    const daysInPrev = new Date(_calYear, _calMonth, 0).getDate();

    let html = `<div class="cal-header">
        <button onclick="calNav(-1)">&#9664;</button>
        <span class="cal-title">${{monthNames[_calMonth]}} ${{_calYear}}</span>
        <button onclick="calNav(1)">&#9654;</button>
    </div><div class="cal-grid">`;
    dows.forEach(d => html += `<span class="cal-dow">${{d}}</span>`);

    // Previous month trailing days
    for (let i = firstDay - 1; i >= 0; i--) {{
        const day = daysInPrev - i;
        const m = _calMonth === 0 ? 12 : _calMonth;
        const y = _calMonth === 0 ? _calYear - 1 : _calYear;
        const ds = y + '-' + String(m).padStart(2,'0') + '-' + String(day).padStart(2,'0');
        html += `<span class="cal-day other-month" onclick="calPick('${{ds}}')">${{day}}</span>`;
    }}
    // Current month days
    for (let d = 1; d <= daysInMonth; d++) {{
        const ds = _calYear + '-' + String(_calMonth+1).padStart(2,'0') + '-' + String(d).padStart(2,'0');
        let cls = 'cal-day';
        if (ds === todayStr) cls += ' today';
        if (ds === selectedStr) cls += ' selected';
        html += `<span class="${{cls}}" onclick="calPick('${{ds}}')">${{d}}</span>`;
    }}
    // Next month leading days
    const totalCells = firstDay + daysInMonth;
    const remaining = (7 - (totalCells % 7)) % 7;
    for (let d = 1; d <= remaining; d++) {{
        const m = _calMonth === 11 ? 1 : _calMonth + 2;
        const y = _calMonth === 11 ? _calYear + 1 : _calYear;
        const ds = y + '-' + String(m).padStart(2,'0') + '-' + String(d).padStart(2,'0');
        html += `<span class="cal-day other-month" onclick="calPick('${{ds}}')">${{d}}</span>`;
    }}
    html += `</div>`;
    html += `<div class="cal-actions">
        <button onclick="calClear()">Clear</button>
        <button class="cal-today-btn" onclick="calPickToday()">Today</button>
    </div>`;
    _calOpen.innerHTML = html;
}}

function calNav(delta) {{
    _calMonth += delta;
    if (_calMonth > 11) {{ _calMonth = 0; _calYear++; }}
    if (_calMonth < 0) {{ _calMonth = 11; _calYear--; }}
    renderCalendar();
}}

function calPick(dateStr) {{
    if (_calInput) {{
        _calInput.value = dateStr;
        _calInput.dispatchEvent(new Event('change'));
    }}
    closeAllCalendars();
}}

function calPickToday() {{
    const t = new Date();
    calPick(t.getFullYear() + '-' + String(t.getMonth()+1).padStart(2,'0') + '-' + String(t.getDate()).padStart(2,'0'));
}}

function calClear() {{
    if (_calInput) {{ _calInput.value = ''; _calInput.dispatchEvent(new Event('change')); }}
    closeAllCalendars();
}}

// Close calendar when clicking outside
document.addEventListener('click', function(e) {{
    if (_calOpen && !e.target.closest('.date-picker-wrap')) closeAllCalendars();
}});

function dec(b64) {{ return decodeURIComponent(Array.from(atob(b64), c => '%' + c.charCodeAt(0).toString(16).padStart(2,'0')).join('')); }}
function decTask(b64) {{ return JSON.parse(dec(b64)); }}
function decProj(b64) {{ return JSON.parse(dec(b64)); }}
function markDone(b64) {{ apiCall('/api/done', {{text: dec(b64)}}); }}
function markUndone(b64) {{ apiCall('/api/undone', {{text: dec(b64)}}); }}

function addTask() {{
    const text = document.getElementById('newTask').value.trim();
    if (!text) return;
    const domain = document.getElementById('newDomain').value;
    const priority = parseInt(document.getElementById('newPriority').value);
    const due = document.getElementById('newDue').value || '';
    const notes = document.getElementById('newNotes').value.trim();
    apiCall('/api/add', {{text, domain, priority, energy: 'med', due, notes}});
}}

function cancelTask(b64) {{
    if (confirm('Cancel this task? It will be moved to the Cancelled list.')) {{
        apiCall('/api/cancel', {{text: dec(b64)}});
    }}
}}

function saveForLater(b64) {{
    if (confirm('Save this task for later? It will be moved off the dashboard.')) {{
        apiCall('/api/save_for_later', {{text: dec(b64)}});
    }}
}}

function restoreTask(b64, from_archive) {{
    apiCall('/api/restore', {{text: dec(b64), from: from_archive}});
}}

function captureItem() {{
    const text = document.getElementById('captureText').value.trim();
    if (!text) return;
    const domain = document.getElementById('captureDomain').value;
    apiCall('/api/capture', {{text, domain}});
}}

function refresh() {{ window.location.reload(); }}

function toggleAddTask() {{
    const bar = document.getElementById('addTaskBar');
    bar.style.display = bar.style.display === 'none' ? 'flex' : 'none';
    if (bar.style.display === 'flex') document.getElementById('newTask').focus();
}}

function showView(view) {{
    document.querySelectorAll('.view').forEach(el => el.style.display = 'none');
    const el = document.getElementById('view-' + view);
    if (el) el.style.display = 'block';
    document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
    const navEl = document.querySelector('.nav-item[data-view="' + view + '"]');
    if (navEl) navEl.classList.add('active');
    // v5 Wave 3: when the R&D view opens, pull the latest rows so a change made
    // in a project window (or another tab) shows up without a manual reload.
    if (view === 'rnd') rndRowsRefresh();
}}

// ── v5 Wave 3: live-ish R&D rows refresh (no full page reload) ──
// Poll the read-only rows fragment ONLY while the R&D view is active AND the
// tab is visible; swap the container's innerHTML only when the fragment CHANGED
// (diff-before-swap → no DOM churn / scroll jumps). Failure-tolerant: a failed
// fetch is a silent no-op, never throws.
function _rndViewActive() {{
    const v = document.getElementById('view-rnd');
    return !!(v && v.style.display !== 'none'
              && document.visibilityState === 'visible');
}}
function rndRowsRefresh() {{
    try {{
        if (!_rndViewActive()) return;
        // Don't clobber an OPEN kebab menu (the swap would re-render it closed) —
        // skip this tick; the user is mid-interaction. The next tick refreshes.
        if (document.querySelector('.rnd-kebab-menu.rnd-kebab-open')) return;
        const box = document.getElementById('rndProjectsRows');
        if (!box) return;
        fetch('/api/rnd/projects_html', {{cache: 'no-store'}})
          .then(function (r) {{ return r.ok ? r.json() : null; }})
          .then(function (d) {{
              if (!d || !d.ok || typeof d.html !== 'string') return;
              if (!_rndViewActive()) return;              // re-check after await
              if (document.querySelector('.rnd-kebab-menu.rnd-kebab-open')) return;
              if (d.html === box.innerHTML) return;       // diff-before-swap
              // Preserve the user's lifetime/30d rollup-window toggle across the
              // swap: the server fragment always renders 'lifetime' as active, so
              // capture the active window BEFORE the swap and re-apply it after
              // (otherwise the 15s poll would silently revert a 30d selection).
              var onBtn = box.querySelector('.rnd-rows-rolltog b.on[data-window]');
              var savedWin = onBtn ? onBtn.getAttribute('data-window') : 'lifetime';
              box.innerHTML = d.html;
              if (savedWin && savedWin !== 'lifetime') {{
                  var reBtn = box.querySelector(
                      '.rnd-rows-rolltog b[data-window="' + savedWin + '"]');
                  if (reBtn) rndRowsRollupWindow(savedWin, reBtn);
              }}
              // v9 Wave 3 — re-wire folder drag/drop + restore collapse state on
              // the freshly-swapped rows.
              if (typeof rndFolderInit === 'function') rndFolderInit();
          }})
          .catch(function () {{}});                       // silent no-op
    }} catch (e) {{}}
}}
setInterval(rndRowsRefresh, 15000);
document.addEventListener('visibilitychange', function () {{
    if (document.visibilityState === 'visible') rndRowsRefresh();
}});

// ── Gandalf in-flight status on dashboard project cards ──
// One bulk poll (/api/rnd/gandalf_status_all) drives the per-card badge instead
// of N single-project requests. Each card carrying a data-project-id is matched
// against the returned project_id-to-status map: a match shows a spinner + the
// short status text; a card no longer in the map is cleared. The interval runs
// only while the tab is visible AND at least one run is in-flight — it idles
// (interval cleared) otherwise and is woken by a slow keep-alive probe / a
// visibility change, so it never leaks intervals and never polls in the dark.
var _gandalfCardTimer = null;
var _gandalfCardProbe = null;
function _gandalfCardTokenQ() {{
    try {{ var t = _anchorToken(); return t ? ('?token=' + encodeURIComponent(t)) : ''; }}
    catch (e) {{ return ''; }}
}}
function _gandalfCardApply(statuses) {{
    var any = false;
    var cards = document.querySelectorAll('.card[data-project-id]');
    for (var i = 0; i < cards.length; i++) {{
        var card = cards[i];
        var pid = card.getAttribute('data-project-id');
        var badge = card.querySelector('.gandalf-card-status');
        if (!badge) continue;
        var st = statuses && Object.prototype.hasOwnProperty.call(statuses, pid)
                 ? statuses[pid] : null;
        if (st) {{
            any = true;
            var txt = badge.querySelector('.gcs-text');
            if (txt) txt.textContent = 'Gandalf: ' + st;
            badge.title = 'Gandalf: ' + st;
            badge.hidden = false;
        }} else {{
            badge.hidden = true;
            var txt2 = badge.querySelector('.gcs-text');
            if (txt2) txt2.textContent = '';
        }}
    }}
    return any;
}}
function _gandalfCardTick() {{
    if (document.visibilityState !== 'visible'
        || !document.querySelector('.card[data-project-id]')) {{
        _gandalfCardStop();
        return;
    }}
    fetch('/api/rnd/gandalf_status_all' + _gandalfCardTokenQ(), {{cache: 'no-store'}})
      .then(function (r) {{ return r.ok ? r.json() : null; }})
      .then(function (d) {{
          if (!d || !d.ok) return;
          var any = _gandalfCardApply(d.statuses || {{}});
          if (!any) _gandalfCardStop();   // nothing in-flight → idle the poller
      }})
      .catch(function () {{}});            // silent no-op
}}
function _gandalfCardStart() {{
    if (_gandalfCardTimer) return;        // already polling — don't stack intervals
    if (document.visibilityState !== 'visible'
        || !document.querySelector('.card[data-project-id]')) return;
    _gandalfCardTick();                   // immediate first paint
    _gandalfCardTimer = setInterval(_gandalfCardTick, 1000);
}}
function _gandalfCardStop() {{
    if (_gandalfCardTimer) {{ clearInterval(_gandalfCardTimer); _gandalfCardTimer = null; }}
}}
// Slow keep-alive: while idle, probe occasionally so a run STARTED after the
// poller went quiet re-arms the 1s loop (single probe; re-uses the same fetch).
function _gandalfCardProbeTick() {{
    if (_gandalfCardTimer) return;        // already active
    if (document.visibilityState !== 'visible'
        || !document.querySelector('.card[data-project-id]')) return;
    fetch('/api/rnd/gandalf_status_all' + _gandalfCardTokenQ(), {{cache: 'no-store'}})
      .then(function (r) {{ return r.ok ? r.json() : null; }})
      .then(function (d) {{
          if (d && d.ok && d.statuses && Object.keys(d.statuses).length) {{
              _gandalfCardApply(d.statuses);
              _gandalfCardStart();
          }}
      }})
      .catch(function () {{}});
}}
window.addEventListener('DOMContentLoaded', function () {{
    _gandalfCardStart();
    _gandalfCardProbe = setInterval(_gandalfCardProbeTick, 8000);
}});
document.addEventListener('visibilitychange', function () {{
    if (document.visibilityState === 'visible') _gandalfCardStart();
    else _gandalfCardStop();
}});

// ── Modal helpers ──
function closeModal(id) {{
    document.getElementById(id).classList.remove('open');
}}

function toggleBrowseMenu(ev, suffix) {{
  if (ev) ev.stopPropagation();
  var menu = document.getElementById('browseMenu_' + suffix);
  if (!menu) return;
  var show = menu.style.display === 'none';
  var all = document.querySelectorAll('.browse-menu');
  for (var i = 0; i < all.length; i++) all[i].style.display = 'none';
  if (show) {{
    menu.style.display = 'block';
  }}
}}
document.addEventListener('click', function() {{
  var all = document.querySelectorAll('.browse-menu');
  for (var i = 0; i < all.length; i++) all[i].style.display = 'none';
}});

function openEditTask(t) {{
    document.getElementById('editTaskOld').value = t.text;
    document.getElementById('editTaskText').value = t.text;
    document.getElementById('editTaskDomain').value = t.domain || 'academic';
    document.getElementById('editTaskPriority').value = t.priority || 2;
    document.getElementById('editTaskEnergy').value = t.energy || 'med';
    document.getElementById('editTaskDue').value = t.due || '';
    document.getElementById('editTaskNotes').value = t.notes || '';
    document.getElementById('editTaskModal').classList.add('open');
}}

function saveEditTask() {{
    const old_text = document.getElementById('editTaskOld').value;
    const body = {{
        old_text: old_text,
        new_text: document.getElementById('editTaskText').value.trim(),
        new_priority: parseInt(document.getElementById('editTaskPriority').value),
        new_domain: document.getElementById('editTaskDomain').value,
        new_energy: document.getElementById('editTaskEnergy').value,
        new_due: document.getElementById('editTaskDue').value || '',
        new_notes: document.getElementById('editTaskNotes').value.trim(),
    }};
    closeModal('editTaskModal');
    apiCall('/api/edit_task', body);
}}

function openEditProject(p) {{
    document.getElementById('editProjOld').value = p.name;
    document.getElementById('editProjName').value = p.name;
    document.getElementById('editProjDomain').value = p.domain || 'academic';
    document.getElementById('editProjPriority').value = p.priority || 2;
    document.getElementById('editProjStatus').value = p.status || 'active';
    document.getElementById('editProjEffort').value = p.effort || 'high';
    document.getElementById('editProjDue').value = p.due || '';
    document.getElementById('editProjNext').value = p.next || '';
    document.getElementById('editProjectModal').classList.add('open');
}}

function saveEditProject() {{
    const old_name = document.getElementById('editProjOld').value;
    const body = {{
        old_name: old_name,
        new_name: document.getElementById('editProjName').value.trim(),
        new_priority: parseInt(document.getElementById('editProjPriority').value),
        new_domain: document.getElementById('editProjDomain').value,
        new_status: document.getElementById('editProjStatus').value,
        new_effort: document.getElementById('editProjEffort').value,
        new_due: document.getElementById('editProjDue').value || '',
        new_next: document.getElementById('editProjNext').value,
    }};
    closeModal('editProjectModal');
    apiCall('/api/edit_project', body);
}}

// ── R&D: New Project modal ──
let _npMode = 'new_folder';
// Tracks whether npName currently holds an auto-suggested basename (vs a value
// the user typed). When true, selecting a folder may overwrite it; the moment
// the user edits the field (npNameEdited), we stop auto-overwriting.
let _npAutoName = false;

function openNewProject() {{
    _npMode = 'new_folder';
    npSetMode('new_folder');
    document.getElementById('npName').value = '';
    document.getElementById('npParentPath').value = 'C:\\\\dev';
    if (document.getElementById('npPreviewPath')) {{
        document.getElementById('npPreviewPath').textContent = '';
    }}
    document.getElementById('npFolderPath').value = '';
    document.getElementById('npGitInit').checked = false;
    _npCurrentPath = null;
    _npAutoName = false;
    npUpdateSelectedUI();
    document.getElementById('newProjectModal').classList.add('open');
}}

// Called on every keystroke in the name field: a manual edit clears the
// auto-suggest flag so later folder selections never clobber the user's text.
function npNameEdited() {{ _npAutoName = false; }}

function npUpdatePreview() {{
    const parentInput = document.getElementById('npParentPath');
    const nameInput = document.getElementById('npName');
    const previewEl = document.getElementById('npPreviewPath');
    if (!previewEl) return;
    
    const parentVal = (parentInput.value || '').trim();
    const nameVal = (nameInput.value || '').trim();
    if (!parentVal || !nameVal) {{
        previewEl.textContent = '';
        return;
    }}
    
    let normalizedParent = parentVal.replace(/[\\\\/]+$/, '');
    let lastSegment = normalizedParent.split(/[\\\\/]/).pop() || '';
    
    let resolved;
    if (lastSegment.toLowerCase() === nameVal.toLowerCase()) {{
        resolved = normalizedParent;
    }} else {{
        const sep = parentVal.includes('/') ? '/' : '\\\\';
        resolved = normalizedParent + sep + nameVal;
    }}
    previewEl.innerHTML = 'Preview: <b>' + escHtml(resolved) + '</b>';
}}

// Auto-suggest the project name from a selected folder's basename, but ONLY if
// the field is empty or still holds a prior auto-suggestion (never overwrite a
// value the user typed). Keeps the field fully editable.
function npSuggestName(path) {{
    if (!path) return;
    const nameEl = document.getElementById('npName');
    const cur = (nameEl.value || '').trim();
    if (cur !== '' && !_npAutoName) return;   // user typed their own — leave it
    const base = npBasename(path);
    if (!base) return;
    nameEl.value = base;
    _npAutoName = true;
    npUpdatePreview();
}}

// Last path segment (drive-letter and trailing-separator aware), e.g.
// 'C:\\dev\\Anchor' -> 'Anchor', 'C:\\' -> 'C:'.
function npBasename(path) {{
    // NOTE: this is inside a Python f-string, so a literal backslash in the
    // emitted JS regex needs FOUR here ('\\\\' -> '\\' in JS -> one '\\' match).
    // Two backslashes would collapse to one in the f-string and the JS regex
    // would only match forward slashes, breaking Windows path basenames.
    let p = String(path).replace(/[\\\\/]+$/, '');     // strip trailing slashes
    const parts = p.split(/[\\\\/]+/);
    let base = parts[parts.length - 1] || '';
    if (/^[A-Za-z]:$/.test(base)) base = base.charAt(0);  // 'C:' -> 'C'
    return base;
}}

function npSetMode(mode) {{
    _npMode = mode;
    const isNew = mode === 'new_folder';
    document.getElementById('npNewFolderFields').style.display = isNew ? 'block' : 'none';
    document.getElementById('npExistingFields').style.display = isNew ? 'none' : 'block';
    document.getElementById('npModeNewBtn').className = 'btn btn-sm' + (isNew ? '' : ' btn-outline');
    document.getElementById('npModeExistingBtn').className = 'btn btn-sm' + (isNew ? ' btn-outline' : '');
    if (!isNew) npTreeInit();
}}

// ── Explorer-style expandable TREE picker ────────────────────────────────────
// Each tree node is a <div class="rnd-tree-node"> containing one clickable row
// (caret + folder icon + label) and a hidden children container. Clicking a row
// BOTH selects the node (highlight + Selected line + name auto-suggest) AND
// toggles lazy expansion (fetch child dirs from /api/rnd/dir_browse). Clicking
// an open node again collapses it. Drill arbitrarily deep.

let _npCurrentPath = null;   // the currently highlighted/selected folder path

// Populate the top level with the drive roots.
async function npTreeInit() {{
    const tree = document.getElementById('npTree');
    if (!tree) return;
    tree.innerHTML = '';
    _npCurrentPath = null;
    let data;
    try {{ data = await npDirBrowse(null); }}
    catch(e) {{ npTreeErr(tree, 'Browse failed: ' + e.message); return; }}
    const res = (data && data.result) || {{}};
    (res.roots || []).forEach(r => tree.appendChild(npMakeNode(r, r)));
}}

// Fetch helper — returns the parsed JSON for a dir_browse call.
async function npDirBrowse(path) {{
    const url = '/api/rnd/dir_browse' + (path ? ('?path=' + encodeURIComponent(path)) : '');
    const r = await fetch(url);
    return await r.json();
}}

// Build one tree node (row + empty children container). `path` is the absolute
// folder path; `label` is what to display (drive root or folder basename).
function npMakeNode(path, label) {{
    const node = document.createElement('div');
    node.className = 'rnd-tree-node';
    node.dataset.path = path;

    const row = document.createElement('div');
    row.className = 'rnd-tree-row';
    row.dataset.path = path;

    const caret = document.createElement('span');
    caret.className = 'rt-caret';
    caret.textContent = '\\u25B8';                // ▸ collapsed

    const icon = document.createElement('span');
    icon.className = 'rt-icon';
    icon.textContent = '\\uD83D\\uDCC1';          // 📁

    const name = document.createElement('span');
    name.className = 'rt-name';
    name.textContent = label;

    row.appendChild(caret);
    row.appendChild(icon);
    row.appendChild(name);

    const kids = document.createElement('div');
    kids.className = 'rnd-tree-children';
    kids.style.display = 'none';

    node.appendChild(row);
    node.appendChild(kids);

    node._loaded = false;
    node._open = false;

    // One click = select + toggle expand/collapse.
    row.addEventListener('click', function(ev) {{
        ev.stopPropagation();
        npTreeSelect(row, path);
        npTreeToggle(node);
    }});

    return node;
}}

// Highlight a row as the current selection, update the Selected line, and
// auto-suggest the project name.
function npTreeSelect(row, path) {{
    document.querySelectorAll('#npTree .rnd-tree-row.selected')
        .forEach(r => r.classList.remove('selected'));
    row.classList.add('selected');
    _npCurrentPath = path;
    document.getElementById('npFolderPath').value = path;
    npSuggestName(path);
    npUpdateSelectedUI();
}}

// Expand (lazy-load children on first open) or collapse a node.
async function npTreeToggle(node) {{
    const caret = node.querySelector(':scope > .rnd-tree-row > .rt-caret');
    const kids = node.querySelector(':scope > .rnd-tree-children');
    if (node._open) {{
        node._open = false;
        caret.textContent = '\\u25B8';            // ▸
        kids.style.display = 'none';
        return;
    }}
    node._open = true;
    caret.textContent = '\\u25BE';                // ▾
    kids.style.display = 'block';
    if (node._loaded) return;
    node._loaded = true;
    let data;
    try {{ data = await npDirBrowse(node.dataset.path); }}
    catch(e) {{ npTreeErr(kids, 'Browse failed: ' + e.message); return; }}
    const res = (data && data.result) || {{}};
    if (res.error) {{
        // Inline message; parent stays usable. Allow a later retry.
        node._loaded = false;
        npTreeErr(kids, "Can't open this folder — " + res.error);
        return;
    }}
    kids.innerHTML = '';
    const dirs = res.dirs || [];
    if (!dirs.length) {{
        const empty = document.createElement('div');
        empty.className = 'rnd-tree-err';
        empty.style.color = 'var(--text-dim)';
        empty.textContent = '(no subfolders)';
        kids.appendChild(empty);
        return;
    }}
    dirs.forEach(d => kids.appendChild(npMakeNode(d.path, d.name)));
}}

// Render a small inline error/notice inside a container.
function npTreeErr(container, msg) {{
    const e = document.createElement('div');
    e.className = 'rnd-tree-err';
    e.textContent = msg;
    container.innerHTML = '';
    container.appendChild(e);
    container.style.display = 'block';
}}

// "Use this folder" — confirm the currently highlighted folder (selection
// already set it; this is the explicit confirm affordance).
function npSelectCurrent() {{
    if (!_npCurrentPath) {{ showToast('Click a folder in the tree first'); return; }}
    document.getElementById('npFolderPath').value = _npCurrentPath;
    npSuggestName(_npCurrentPath);
    npUpdateSelectedUI();
    showToast('Using: ' + _npCurrentPath);
}}

function npUpdateSelectedUI() {{
    const sel = (document.getElementById('npFolderPath').value || '').trim();
    const el = document.getElementById('npSelected');
    if (!el) return;
    if (sel) {{
        el.classList.remove('empty');
        el.innerHTML = 'Selected: <b>' + escHtml(sel) + '</b>';
    }} else {{
        el.classList.add('empty');
        el.textContent = 'No folder selected yet';
    }}
}}

function escHtml(s) {{ const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }}
function jsStr(s) {{ return JSON.stringify(s == null ? '' : s); }}

async function createNewProject() {{
    const name = document.getElementById('npName').value.trim();
    if (!name) {{ showToast('Project name required'); return; }}
    const priority = parseInt(document.getElementById('npPriority').value);
    let body;
    if (_npMode === 'new_folder') {{
        const parent = document.getElementById('npParentPath').value.trim();
        if (!parent) {{ showToast('Parent path required'); return; }}
        body = {{mode: 'new_folder', name, priority, parent_path: parent,
                 git_init: document.getElementById('npGitInit').checked}};
    }} else {{
        const folder = document.getElementById('npFolderPath').value.trim();
        if (!folder) {{ showToast('No folder selected — browse to a folder and click “Select this folder”'); return; }}
        body = {{mode: 'existing', name, priority, folder_path: folder}};
    }}
    closeModal('newProjectModal');
    apiCall('/api/rnd/new_project', body);
}}

// 2026-05-12: stopServer() removed. The dashboard no longer kills its own
// server; that responsibility now belongs to the NSSM "anchor" service
// supervisor on gwl-server. To restart, run `nssm restart anchor`.
// /api/shutdown is also gone from the Python side, so external POSTs can
// no longer kill the server either.

function promoteProject(b64) {{ apiCall('/api/promote_project', {{name: dec(b64)}}); }}
function demoteProject(b64) {{ apiCall('/api/demote_project', {{name: dec(b64)}}); }}

// ── R&D project lifecycle (rich tiles) ──
// Open a project in ITS OWN window, named per-project: if that window is already
// open, this focuses it instead of opening a duplicate (multiple projects at a
// time, but one window each). The URL is version-stamped with the build id so a
// project window left open across a DEPLOY no longer matches the new URL and the
// browser re-navigates (reloads) it — otherwise a same-name/same-URL window is
// merely focused (no re-fetch) and would show stale pre-deploy HTML.
function openProjectWindow(pid) {{
    var w = window.open('/project/' + encodeURIComponent(pid) + '?v={BUILD_ID}', 'anchorproj_' + pid);
    if (w) {{ try {{ w.focus(); }} catch (e) {{}} }}
}}
function rndSetPriority(pid, pr) {{ apiCall('/api/rnd/set_priority', {{id: pid, priority: pr}}); }}
function rndArchive(pid) {{ if (confirm('Archive this project? It moves to the Archive view (kept, reviewable).')) apiCall('/api/rnd/archive_project', {{id: pid}}); }}
function rndRetire(pid) {{ if (confirm('Retire/cancel this project? It moves to the Archive view as retired.')) apiCall('/api/rnd/retire_project', {{id: pid}}); }}
function rndReactivate(pid) {{ apiCall('/api/rnd/reactivate_project', {{id: pid}}); }}
function rndRescan(pid) {{ apiCall('/api/rnd/rescan', {{id: pid}}); }}
// v4 Wave 8 — one GLOBAL lifetime/30-day toggle for the dashboard rows' cost
// rollups. Re-fetches each row's read-only /api/rnd/project_rollup?window=... and
// swaps the .rnd-row-roll text in place (no page reload). The header renders
// lifetime server-side, so a no-JS view still shows lifetime totals.
function rndRowsRollupWindow(window_, btn) {{
    if (btn && btn.parentNode) {{
        var bs = btn.parentNode.querySelectorAll('b');
        for (var i = 0; i < bs.length; i++) bs[i].classList.remove('on');
        btn.classList.add('on');
    }}
    var tok = _anchorToken();
    var tq = tok ? ('&token=' + encodeURIComponent(tok)) : '';
    var rolls = document.querySelectorAll('.rnd-row-roll[data-pid]');
    for (var j = 0; j < rolls.length; j++) {{
        (function (el) {{
            var pid = el.getAttribute('data-pid') || '';
            if (!pid) return;
            var url = '/api/rnd/project_rollup?pid=' + encodeURIComponent(pid)
                + '&window=' + encodeURIComponent(window_) + tq;
            var hdrs = {{'Content-Type': 'application/json'}};
            fetch(url, {{headers: hdrs}})
                .then(function (r) {{ return r.json(); }})
                .then(function (d) {{
                    if (d && d.ok && typeof d.text === 'string') {{
                        el.textContent = d.text;
                        el.setAttribute('data-window', window_);
                    }}
                }})
                .catch(function () {{}});
        }})(rolls[j]);
    }}
}}
// v3 Wave 5 — toggle a project ROW's kebab menu (lifecycle controls live here so
// the thin row stays one line). Closes any other open menu first.
function rndToggleKebab(ev, pid) {{
    ev.stopPropagation();
    var menu = document.getElementById('rnd-kebab-' + pid);
    var wasOpen = menu && menu.classList.contains('rnd-kebab-open');
    document.querySelectorAll('.rnd-kebab-menu.rnd-kebab-open').forEach(function(m) {{
        m.classList.remove('rnd-kebab-open');
    }});
    if (menu && !wasOpen) menu.classList.add('rnd-kebab-open');
}}
document.addEventListener('click', function() {{
    document.querySelectorAll('.rnd-kebab-menu.rnd-kebab-open').forEach(function(m) {{
        m.classList.remove('rnd-kebab-open');
    }});
}});
function rndNotes(pid) {{
    var el = document.querySelector('.rnd-row[data-project-id="' + pid + '"]');
    var cur = el ? (el.getAttribute('data-notes') || '') : '';
    var n = window.prompt('Project notes:', cur);
    if (n === null) return;
    apiCall('/api/rnd/set_notes', {{id: pid, notes: n}});
}}
function rndBlurb(pid) {{
    var el = document.querySelector('.rnd-row[data-project-id="' + pid + '"]');
    var cur = el ? (el.getAttribute('data-blurb') || '') : '';
    var n = window.prompt('What this project is (blurb):', cur);
    if (n === null) return;
    apiCall('/api/rnd/set_blurb', {{id: pid, blurb: n}});
}}

// ── v9 Wave 3 — project FOLDERS (group field; collapsible; drag-to-group) ──
// Organization only — NOTHING moves on disk this wave (that's Wave 4). Dragging
// a row into a folder header just sets the project's `group` via set_group.
var RND_FOLDER_LS = 'anchor_rnd_folder_collapsed';
function _rndCollapsedSet() {{
    try {{ return JSON.parse(localStorage.getItem(RND_FOLDER_LS) || '[]') || []; }}
    catch (e) {{ return []; }}
}}
function _rndSaveCollapsed(arr) {{
    try {{ localStorage.setItem(RND_FOLDER_LS, JSON.stringify(arr || [])); }} catch (e) {{}}
}}
// Collapse / expand one folder, persisting the state by group name.
function rndToggleFolder(headEl) {{
    var folder = headEl && headEl.closest ? headEl.closest('.rnd-folder') : null;
    if (!folder) return;
    var collapsed = folder.classList.toggle('rnd-collapsed');
    var tw = folder.querySelector('.rnd-tw');
    if (tw) tw.textContent = collapsed ? '\\u25B8' : '\\u25BE';  // ▸ / ▾
    var g = folder.getAttribute('data-group') || '';
    var set = _rndCollapsedSet();
    var i = set.indexOf(g);
    if (collapsed && i < 0) set.push(g);
    else if (!collapsed && i >= 0) set.splice(i, 1);
    _rndSaveCollapsed(set);
}}
// "+ New folder" — name a group and assign the FIRST ungrouped project to it,
// OR (if there is none) create an empty folder by re-rendering a placeholder.
// Simplest persistence model: a folder "exists" once >=1 project carries that
// group. We create it by re-grouping the first ungrouped project; if none are
// ungrouped, we still surface an empty folder via localStorage so the user can
// drag into it (it persists once a project lands there).
var RND_PENDING_FOLDERS = 'anchor_rnd_pending_folders';
function _rndPendingFolders() {{
    try {{ return JSON.parse(localStorage.getItem(RND_PENDING_FOLDERS) || '[]') || []; }}
    catch (e) {{ return []; }}
}}
function _rndSavePending(arr) {{
    try {{ localStorage.setItem(RND_PENDING_FOLDERS, JSON.stringify(arr || [])); }} catch (e) {{}}
}}
function rndNewFolder() {{
    var name = window.prompt('New folder name:', '');
    if (name === null) return;
    name = (name || '').trim();
    if (!name) return;
    // Render an empty folder immediately so the user can drag into it. It only
    // truly persists once a project is dropped in (set_group), but we keep the
    // pending name in localStorage so a reload still shows the empty folder.
    var pend = _rndPendingFolders();
    if (pend.indexOf(name) < 0) {{ pend.push(name); _rndSavePending(pend); }}
    // The home page renders the folder list in two places — create in each.
    var lists = document.querySelectorAll('.rnd-folder-list');
    for (var i = 0; i < lists.length; i++) _rndEnsureFolderIn(lists[i], name);
}}
// Ensure a folder header with the given group name exists in ONE list (create
// an empty one before that list's Ungrouped folder if absent). Returns the el.
function _rndEnsureFolderIn(list, name) {{
    if (!list) return null;
    var sel = (window.CSS && CSS.escape) ? CSS.escape(name) : name;
    var existing = list.querySelector('.rnd-folder[data-group="' + sel + '"]');
    if (existing) return existing;
    var folder = document.createElement('div');
    folder.className = 'rnd-folder';
    folder.setAttribute('data-group', name);
    folder.setAttribute('data-ungrouped', '0');
    folder.innerHTML =
        '<div class="rnd-folder-head" role="button" tabindex="0" '
        + 'title="Collapse / expand folder">'
        + '<span class="rnd-tw" aria-hidden="true">\u25BE</span>'
        + '<span class="rnd-fname"></span>'
        + '<span class="rnd-fcount">(0)</span>'
        + '<span class="rnd-fsp"></span>'
        + '</div><div class="rnd-folder-body"></div>';
    folder.querySelector('.rnd-fname').textContent = name;
    var head = folder.querySelector('.rnd-folder-head');
    head.addEventListener('click', function () {{ rndToggleFolder(head); }});
    // Insert before this list's Ungrouped folder so Ungrouped stays last.
    var ung = list.querySelector('.rnd-folder[data-ungrouped="1"]');
    if (ung) list.insertBefore(folder, ung); else list.appendChild(folder);
    _rndWireFolderDrop(folder);
    return folder;
}}
// Wire one folder header as a drop target. Dropping a dragged project row here
// calls set_group with this folder's group ("" for the Ungrouped folder).
function _rndWireFolderDrop(folder) {{
    var head = folder.querySelector('.rnd-folder-head');
    if (!head) return;
    head.addEventListener('dragover', function (ev) {{
        ev.preventDefault();
        if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'move';
        folder.classList.add('rnd-droptarget');
    }});
    head.addEventListener('dragleave', function () {{
        folder.classList.remove('rnd-droptarget');
    }});
    head.addEventListener('drop', function (ev) {{
        ev.preventDefault();
        folder.classList.remove('rnd-droptarget');
        var pid = ev.dataTransfer ? ev.dataTransfer.getData('text/plain') : '';
        if (!pid) return;
        var isUng = folder.getAttribute('data-ungrouped') === '1';
        var grp = isUng ? '' : (folder.getAttribute('data-group') || '');
        // v9 Wave 4 — the Option-C choice. Dropping into the Ungrouped folder
        // (remove from a folder) is dashboard-only — just set_group, no dialog.
        // Dropping into a NAMED folder asks: "Move on disk + group" (the guarded
        // move_project) vs "Just group" (set_group only) vs Cancel.
        if (isUng) {{
            apiCall('/api/rnd/set_group', {{project_id: pid, group: grp}});
        }} else {{
            rndMoveDialog(pid, grp, folder);
        }}
    }});
}}
// ── v9 Wave 4 — the Option-C "move on disk + group" dialog ─────────────────
// On a drop into a NAMED folder, offer: (1) "Move on disk + group" → the guarded
// POST /api/rnd/move_project {{confirm:true}} (refuses the Anchor app + any
// live-session project; atomic + rolls back); (2) "Just group" → the Wave-3
// set_group (dashboard-only, NO disk move); (3) Cancel.
function rndMoveDialog(pid, group, folder) {{
    var ov = document.getElementById('rndMoveOverlay');
    if (!ov) {{  // dialog markup absent → fall back to the plain group path.
        apiCall('/api/rnd/set_group', {{project_id: pid, group: group}});
        return;
    }}
    var pname = '';
    var row = document.querySelector('.rnd-row[data-project-id="'
        + (window.CSS && CSS.escape ? CSS.escape(pid) : pid) + '"]');
    if (row) {{
        var n = row.querySelector('.rnd-name');
        if (n) pname = n.textContent || '';
    }}
    var title = document.getElementById('rndMoveTitle');
    if (title) title.textContent =
        'Move "' + (pname || 'project') + '" into folder "' + group + '"?';
    // The exact source→dest paths are resolved server-side (the row deliberately
    // carries no on-disk path); show the destination group so the user knows
    // what "move on disk" does.
    var mono = document.getElementById('rndMovePaths');
    if (mono) mono.textContent = 'Destination group: ' + group
        + '  →  <projects-root>/' + group + '/<project-dir>';
    var go = document.getElementById('rndMoveGo');
    var just = document.getElementById('rndMoveJust');
    if (go) go.onclick = function () {{ rndMoveConfirm(pid, group, true); }};
    if (just) just.onclick = function () {{ rndMoveConfirm(pid, group, false); }};
    ov.style.display = 'flex';
}}
function rndMoveCancel() {{
    var ov = document.getElementById('rndMoveOverlay');
    if (ov) ov.style.display = 'none';
}}
// onDisk=true → the guarded move_project; false → set_group (Wave-3 path). On a
// refusal (Anchor repo / live session) we surface a clear toast (no reload).
function rndMoveConfirm(pid, group, onDisk) {{
    rndMoveCancel();
    if (!onDisk) {{
        apiCall('/api/rnd/set_group', {{project_id: pid, group: group}});
        return;
    }}
    var headers = {{'Content-Type': 'application/json'}};
    var tok = (typeof _anchorToken === 'function') ? _anchorToken() : '';
    if (tok) headers['X-Anchor-Token'] = tok;
    fetch('/api/rnd/move_project', {{
        method: 'POST', headers: headers,
        body: JSON.stringify({{project_id: pid, group: group, confirm: true}})
    }}).then(function (r) {{ return r.json(); }}).then(function (data) {{
        if (data && data.ok) {{
            showToast('Moved on disk + grouped under "' + group + '"');
            setTimeout(function () {{ window.location.reload(); }}, 700);
        }} else {{
            var reason = (data && data.reason) || (data && data.error) || 'unknown';
            var msg;
            if (reason === 'refused-anchor-repo')
                msg = "Can't move the running Anchor app (it'd kill the server). Grouped only.";
            else if (reason === 'refused-live-sessions')
                msg = 'Refused: this project has a live session — stop it first. Grouped only.';
            else
                msg = 'Move refused (' + reason + '). Grouped only.';
            showToast(msg);
            // The dashboard grouping still applies even when the disk move is
            // refused, so the row at least lands under the folder.
            apiCall('/api/rnd/set_group', {{project_id: pid, group: group}});
        }}
    }}).catch(function (e) {{
        showToast('Move error: ' + e.message);
    }});
}}
// Make project rows draggable and wire every folder as a drop target. Also
// restore the persisted collapse state. The home page renders the folder list
// in TWO places (the dashboard section + the #rndProjectsRows view), so we wire
// EVERY .rnd-folder-list. Runs on DOMContentLoaded + after an in-place refresh.
function rndFolderInit() {{
    var lists = document.querySelectorAll('.rnd-folder-list');
    for (var L = 0; L < lists.length; L++) {{
        var list = lists[L];
        if (list.getAttribute('data-rnd-wired') === '1') continue;
        list.setAttribute('data-rnd-wired', '1');
        // Draggable rows.
        var rows = list.querySelectorAll('.rnd-row[draggable="true"]');
        for (var i = 0; i < rows.length; i++) {{
            (function (row) {{
                row.addEventListener('dragstart', function (ev) {{
                    var pid = row.getAttribute('data-project-id') || '';
                    if (ev.dataTransfer) {{
                        ev.dataTransfer.setData('text/plain', pid);
                        ev.dataTransfer.effectAllowed = 'move';
                    }}
                    row.classList.add('rnd-dragging');
                }});
                row.addEventListener('dragend', function () {{
                    row.classList.remove('rnd-dragging');
                }});
            }})(rows[i]);
        }}
        // Drop targets + restore collapse state.
        var folders = list.querySelectorAll('.rnd-folder');
        var collapsed = _rndCollapsedSet();
        for (var j = 0; j < folders.length; j++) {{
            _rndWireFolderDrop(folders[j]);
            var g = folders[j].getAttribute('data-group') || '';
            if (collapsed.indexOf(g) >= 0) {{
                folders[j].classList.add('rnd-collapsed');
                var tw = folders[j].querySelector('.rnd-tw');
                if (tw) tw.textContent = '\\u25B8';  // ▸
            }}
        }}
        // Re-surface any pending (empty, not-yet-populated) folders from a prior
        // "+ New folder" that has no project yet.
        var pend = _rndPendingFolders();
        for (var k = 0; k < pend.length; k++) {{
            if (!list.querySelector('.rnd-folder[data-group="'
                + (window.CSS && CSS.escape ? CSS.escape(pend[k]) : pend[k]) + '"]')) {{
                _rndEnsureFolderIn(list, pend[k]);
            }}
        }}
    }}
}}
window.addEventListener('DOMContentLoaded', rndFolderInit);

// --- Wave 2: File Upload (Dashboard) — multi-file + folder + drag-drop ---
function _anchorReadB64(file) {{
  return new Promise(function(resolve, reject) {{
    var r = new FileReader();
    r.onload = function() {{ resolve(r.result.split(',')[1]); }};
    r.onerror = reject;
    r.readAsDataURL(file);
  }});
}}

function _anchorUploadDest(projectId) {{
  if (projectId === '__dashboard__') return "the dev inbox (C:\\\\dev\\\\Anchor\\\\dev)";
  if (typeof window._anchorUploadName === 'string' && window._anchorUploadName) return window._anchorUploadName;
  return "project " + projectId;
}}

// Unified upload core. `items` is an array of {{ file, path }} where path is the
// destination-relative path (leading slashes stripped). All three controls
// (multi-file picker, folder picker, drag-drop) funnel through here.
async function _anchorDoUpload(items, projectId) {{
  if (!items || !items.length) return;

  var folders = new Set();
  var fileCount = 0;
  for (var i = 0; i < items.length; i++) {{
    var p = items[i].path || "";
    if (p.indexOf('/') !== -1) {{
      var parts = p.split('/');
      parts.pop();
      folders.add(parts.join('/'));
    }}
    fileCount++;
  }}
  var folderCount = folders.size;
  var stagingMsg = fileCount + " file(s)" + (folderCount ? " across " + folderCount + " folder(s)" : "") + " ready";

  var dz = document.querySelector('.upload-dropzone');
  if (dz) {{
    dz.innerHTML = "&#9203; Staging: " + stagingMsg + "...";
  }}

  var filesPayload = [];
  for (var i = 0; i < items.length; i++) {{
    var rel = String(items[i].path || items[i].file.name).replace(/^\\/+/, '');
    try {{
      var base64 = await _anchorReadB64(items[i].file);
      filesPayload.push({{ path: rel, content_b64: base64 }});
    }} catch (e) {{
      alert("Failed to read file: " + rel);
      if (dz) dz.innerHTML = "&#8681; Drop files &amp; folders here to upload (any mix)";
      return;
    }}
  }}
  var res = await fetch("/api/rnd/upload_batch", {{
    method: "POST",
    headers: {{
      "Content-Type": "application/json",
      "X-Anchor-Token": _anchorToken()
    }},
    body: JSON.stringify({{ project_id: projectId, files: filesPayload }})
  }});
  if (res.ok) {{
    alert("Uploaded " + filesPayload.length + " file(s) to " + _anchorUploadDest(projectId) + ".");
    if (typeof loadProjectFiles === 'function') {{
      loadProjectFiles(projectId, (typeof currentFilesPath !== 'undefined' ? currentFilesPath : ''));
    }}
  }} else {{
    var data = await res.json();
    alert("Upload failed: " + (data.error || "Unknown error"));
  }}
  if (dz) {{
    dz.innerHTML = "&#8681; Drop files &amp; folders here to upload (any mix)";
  }}
}}

async function handleGlobalUpload(inputId, projectId) {{
  var input = document.getElementById(inputId);
  if (!input || !input.files || input.files.length === 0) return;
  var items = [];
  for (var i = 0; i < input.files.length; i++) {{
    var file = input.files[i];
    items.push({{ file: file, path: file.webkitRelativePath || file.name }});
  }}
  await _anchorDoUpload(items, projectId);
  input.value = "";
}}

// Recurse a dropped FileSystemEntry, collecting every File with its full
// relative path. readEntries() returns results in batches, so it must be
// called repeatedly until it yields an empty array.
function _anchorWalkEntry(entry, prefix, out) {{
  return new Promise(function(resolve) {{
    if (entry.isFile) {{
      entry.file(function(file) {{
        out.push({{ file: file, path: prefix ? (prefix + "/" + entry.name) : entry.name }});
        resolve();
      }}, function() {{ resolve(); }});
    }} else if (entry.isDirectory) {{
      var reader = entry.createReader();
      var dirPrefix = prefix ? (prefix + "/" + entry.name) : entry.name;
      var all = [];
      var readBatch = function() {{
        reader.readEntries(function(results) {{
          if (!results || !results.length) {{
            var chain = Promise.resolve();
            all.forEach(function(child) {{
              chain = chain.then(function() {{ return _anchorWalkEntry(child, dirPrefix, out); }});
            }});
            chain.then(resolve);
          }} else {{
            for (var m = 0; m < results.length; m++) all.push(results[m]);
            readBatch();
          }}
        }}, function() {{ resolve(); }});
      }};
      readBatch();
    }} else {{
      resolve();
    }}
  }});
}}

function handleUploadDragOver(ev) {{
  ev.preventDefault();
  if (ev.dataTransfer) ev.dataTransfer.dropEffect = 'copy';
  var dz = ev.currentTarget;
  if (dz) dz.classList.add('dragover');
}}

function handleUploadDragLeave(ev) {{
  var dz = ev.currentTarget;
  if (dz) dz.classList.remove('dragover');
}}

async function handleUploadDrop(ev, projectId) {{
  ev.preventDefault();
  var dz = ev.currentTarget;
  if (dz) dz.classList.remove('dragover');
  var dt = ev.dataTransfer;
  if (!dt) return;
  // Collect entries synchronously BEFORE any await (the DataTransfer is cleared
  // once the event handler yields).
  var entries = [];
  if (dt.items && dt.items.length && dt.items[0].webkitGetAsEntry) {{
    for (var i = 0; i < dt.items.length; i++) {{
      var en = dt.items[i].webkitGetAsEntry();
      if (en) entries.push(en);
    }}
  }}
  var items = [];
  if (entries.length) {{
    for (var j = 0; j < entries.length; j++) {{
      await _anchorWalkEntry(entries[j], "", items);
    }}
  }} else if (dt.files && dt.files.length) {{
    for (var k = 0; k < dt.files.length; k++) {{
      items.push({{ file: dt.files[k], path: dt.files[k].name }});
    }}
  }}
  await _anchorDoUpload(items, projectId);
}}

function promoteTask(b64) {{ apiCall('/api/promote_task', {{text: dec(b64)}}); }}
function demoteTask(b64) {{ apiCall('/api/demote_task', {{text: dec(b64)}}); }}

// Domain-specific add task
function toggleAddTask_(domain) {{
    const bar = document.getElementById('addTaskBar_' + domain);
    bar.style.display = bar.style.display === 'none' ? 'flex' : 'none';
    if (bar.style.display === 'flex') document.getElementById('newTask_' + domain).focus();
}}
// Alias so onclick="toggleAddTask_family()" works via dynamic name
{" ".join(f"function toggleAddTask_{d}() {{ toggleAddTask_('{d}'); }}" for d in domain_order)}

function addTaskDomain(domain) {{
    const text = document.getElementById('newTask_' + domain).value.trim();
    if (!text) return;
    const priority = parseInt(document.getElementById('newPriority_' + domain).value);
    const due = document.getElementById('newDue_' + domain).value || '';
    const notes = document.getElementById('newNotes_' + domain).value.trim();
    apiCall('/api/add', {{text, domain, priority, energy: 'med', due, notes}});
}}
</script>
<script>{cache_bust_script()}</script>
<script>{_ORPHAN_ALERT_JS}</script>
<script>{_ZOMBIE_SPEND_ALERT_JS}</script>
<!-- Ecgberht High Seat overlay (TW6): host + static assets. The overlay
     renders the engine view model only; closing it writes nothing. -->
<link rel="stylesheet" href="/static/high-seat.css?v={BUILD_ID}">
<div id="ecgHighSeatHost"></div>
<script>window.ANCHOR_STEWARD = {steward_boot_json};</script>
<script src="/static/high-seat.js?v={BUILD_ID}"></script>
</body>
</html>'''


# Timestamp captured at module load = THIS server process's start. orphan_check
# only banners on orphans whose session record was created at/after this, so a
# restart's leftover prior-instance sessions never trigger a false alert. Safe
# default semantics: any record predating this (or with no timestamp) is excluded.
_SERVER_BOOT_TS = time.time()


# ── Orphan-swarm alert banner (dashboard) ───────────────────────────────
# Polls /api/rnd/orphan_check; when a NEW orphan session appears (one we have
# not alerted on before) it shows a dismissible, click-through banner that opens
# the Zombie Hunter report. NOT a pest: an orphan we've already alerted on is
# never re-alerted (tracked in localStorage); the set is pruned to currently
# present orphans so a freshly-spawned orphan re-alerts but a still-unkilled one
# does not. Plain (non-f) string — its braces are literal JS.
_ORPHAN_ALERT_JS = r'''
(function () {
  function _zhTok() { try { return (typeof _anchorToken === 'function') ? (_anchorToken() || '') : ''; } catch (e) { return ''; } }
  function _zhGet() { try { return JSON.parse(localStorage.getItem('zombieAlertedOrphans') || '[]'); } catch (e) { return []; } }
  function _zhSet(a) { try { localStorage.setItem('zombieAlertedOrphans', JSON.stringify(a)); } catch (e) {} }
  function _zhBanner(n) {
    if (document.getElementById('zhOrphanBanner')) return;
    var tok = _zhTok();
    var url = '/api/rnd/zombie_hunter_report' + (tok ? ('?token=' + encodeURIComponent(tok)) : '');
    var b = document.createElement('div');
    b.id = 'zhOrphanBanner';
    b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#7f1d1d;color:#fee2e2;padding:10px 16px;display:flex;align-items:center;gap:12px;font-size:13px;box-shadow:0 2px 8px rgba(0,0,0,.4)';
    var msg = document.createElement('span');
    msg.style.cssText = 'flex:1';
    msg.innerHTML = '<span style="font-size:16px;margin-right:6px">&#9888;</span>' + n + ' orphaned swarm' + (n > 1 ? 's' : '') + ' detected and paused — review in Zombie Hunter.';
    var go = document.createElement('button');
    go.textContent = 'Review';
    go.style.cssText = 'background:#fee2e2;color:#7f1d1d;border:none;border-radius:4px;padding:5px 12px;font-weight:600;cursor:pointer';
    go.onclick = function () { window.open(url, '_blank'); if (b.parentNode) b.parentNode.removeChild(b); };
    var x = document.createElement('button');
    x.innerHTML = '&times;';
    x.title = 'Dismiss';
    x.style.cssText = 'background:transparent;color:#fee2e2;border:none;font-size:18px;cursor:pointer;line-height:1';
    x.onclick = function () { if (b.parentNode) b.parentNode.removeChild(b); };
    b.appendChild(msg); b.appendChild(go); b.appendChild(x);
    document.body.appendChild(b);
  }
  function _zhPoll() {
    var tok = _zhTok();
    fetch('/api/rnd/orphan_check' + (tok ? ('?token=' + encodeURIComponent(tok)) : ''), { headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.ok || !Array.isArray(d.orphans)) return;
        var cur = d.orphans;
        var alerted = _zhGet();
        var fresh = cur.filter(function (s) { return alerted.indexOf(s) < 0; });
        var pruned = alerted.filter(function (s) { return cur.indexOf(s) >= 0; });
        if (fresh.length > 0) { _zhBanner(cur.length); pruned = pruned.concat(fresh); }
        _zhSet(pruned);
      })
      .catch(function () {});
  }
  if (document.readyState !== 'loading') { _zhPoll(); }
  else { window.addEventListener('DOMContentLoaded', _zhPoll); }
  setInterval(_zhPoll, 45000);
})();
'''


# ── Token-spend zombie banner (dashboard) ───────────────────────────────
# STATE-DRIVEN: polls /api/rnd/zombie_spenders (which reads the node Sentinel's
# whole-computer token-spend scan). While >=1 VALID zombie exists (a process
# spending paid tokens with no live session) it shows a red top banner; clicking
# opens the Zombie Hunter GUI. When the zombie is dealt with (reaped OR
# re-designated supervised), the next poll returns 0 and the banner is removed
# automatically. Plain (non-f) string — its braces are literal JS.
_ZOMBIE_SPEND_ALERT_JS = r'''
(function () {
  function _zsTok() { try { return (typeof _anchorToken === 'function') ? (_anchorToken() || '') : ''; } catch (e) { return ''; } }
  function _zsUrl() { var t = _zsTok(); return '/api/rnd/zombie_hunter_report' + (t ? ('?token=' + encodeURIComponent(t)) : ''); }
  function _zsShow(count, usd) {
    var b = document.getElementById('zhSpendBanner');
    if (!b) {
      b = document.createElement('div');
      b.id = 'zhSpendBanner';
      b.style.cssText = 'position:fixed;top:0;left:0;right:0;z-index:99999;background:#7f1d1d;color:#fee2e2;padding:10px 16px;display:flex;align-items:center;gap:12px;font-size:13px;box-shadow:0 2px 8px rgba(0,0,0,.4);cursor:pointer';
      b.onclick = function () { window.open(_zsUrl(), '_blank'); };
      var msg = document.createElement('span'); msg.id = 'zhSpendMsg'; msg.style.cssText = 'flex:1';
      var go = document.createElement('button');
      go.textContent = 'Deal with it →';
      go.style.cssText = 'background:#fee2e2;color:#7f1d1d;border:none;border-radius:4px;padding:5px 12px;font-weight:600;cursor:pointer';
      go.onclick = function (e) { e.stopPropagation(); window.open(_zsUrl(), '_blank'); };
      b.appendChild(msg); b.appendChild(go);
      document.body.appendChild(b);
    }
    var m = document.getElementById('zhSpendMsg');
    if (m) m.innerHTML = '<span style="font-size:16px;margin-right:6px">&#9888;</span><b>' + count + ' token-spending zombie' + (count > 1 ? 's' : '') + '</b> running unsupervised' + (usd > 0 ? ' — ~$' + usd + '/min burning' : '') + '. Click to investigate &amp; reap.';
  }
  function _zsHide() { var b = document.getElementById('zhSpendBanner'); if (b && b.parentNode) b.parentNode.removeChild(b); }
  function _zsPoll() {
    var t = _zsTok();
    fetch('/api/rnd/zombie_spenders' + (t ? ('?token=' + encodeURIComponent(t)) : ''), { headers: { 'Accept': 'application/json' } })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        if (!d || !d.ok) return;
        if (d.count > 0) _zsShow(d.count, d.usdPerMin); else _zsHide();
      })
      .catch(function () {});
  }
  if (document.readyState !== 'loading') { _zsPoll(); }
  else { window.addEventListener('DOMContentLoaded', _zsPoll); }
  setInterval(_zsPoll, 30000);
})();
'''


# ── HTTP Server ────────────────────────────────────────────────────────

# WinError codes for the benign "the client went away" socket conditions.
# 10053 = WSAECONNABORTED (an established connection aborted by the host/software),
# 10054 = WSAECONNRESET (connection reset by peer). These ride in on a generic
# OSError on Windows (BufferedWriter.write → sock.sendall) rather than as the
# typed ConnectionAbortedError / ConnectionResetError, so we sniff .winerror too.
_BENIGN_DISCONNECT_WINERRORS = (10053, 10054)


def _is_benign_disconnect(exc):
    """True for a socket-teardown error that means the CLIENT closed the
    connection mid-response — not a server bug. A browser closing a terminal
    tab (or Playwright tearing down a page) makes the in-flight SSE/WS/HTTP
    write raise one of these; treating them as a normal client-gone condition
    is correct production behavior, never an error to surface or log loudly.

    Catches the typed connection-teardown exceptions AND a Windows OSError whose
    ``winerror`` is 10053/10054 (which is how the abort actually arrives on the
    BufferedWriter.write → sock.sendall path). Deliberately TIGHT — it never
    swallows a generic OSError/Exception that could hide a real defect.
    """
    if isinstance(exc, (BrokenPipeError, ConnectionResetError,
                        ConnectionAbortedError)):
        return True
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) \
            in _BENIGN_DISCONNECT_WINERRORS:
        return True
    return False


# ── Migrated route handlers (rearch W7 / C2 strangler, first batch) ──────────
# Module-level handler functions the declarative route table dispatches to. Each
# takes ``(handler, path, body)`` — ``handler`` is the live AnchorHandler
# instance (for _send_json/wfile/etc.), ``path`` is the request path, ``body`` is
# the parsed POST body (None for GET). Auth is applied by the strangler BEFORE
# these run, per the route row's declared policy. Moving these out of the
# do_GET/do_POST if/elif chains to module-level functions is the mechanism that
# structurally kills the in-method import-shadowing class (W8 completes it).

def handle_version(handler, path, body):
    """GET /api/version — the build-id probe for the self-healing redeploy client.

    Always fetched fresh (no-store) so the client can detect a redeploy.
    """
    payload = json.dumps({"version": BUILD_ID}).encode()
    handler.send_response(200)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(payload)


def handle_status(handler, path, body):
    """GET /api/status — coarse task/project/inbox counts for the page header."""
    projects, tasks, inbox = gather_all()
    active = [t for t in tasks if not t["done"]]
    handler._send_json({
        "projects": len(projects),
        "active": len(active),
        "done": len([t for t in tasks if t["done"]]),
        "inbox": len(inbox),
    })


def handle_dir_browse(handler, path, body):
    """GET /api/rnd/dir_browse — read-only directory browser for the "select
    existing" project UI (rearch W8 migration batch → module-level handler).

    Reads the ``?path=`` query off ``handler.path`` (the strangler passes the
    query-stripped path as ``path``). Open by policy (declared in the reviewed
    OPEN_ROUTES allowlist), so no token gate applies.
    """
    q = parse_qs(urlparse(handler.path).query)
    path_arg = q.get("path", [None])[0]
    handler._send_json({"ok": True, "result": _dirb.browse(path_arg)})


def handle_routes(handler, path, body):
    """GET /api/routes — dump the live declarative route table (token-authed).

    The audit surface: path, method, auth policy, handler kind, and legacy-or-
    migrated status for every declared route, plus the C2 progress counters.
    """
    handler._send_json({
        "ok": True,
        "routes": _routes.table_dump(),
        "legacy_arm_count": _routes.legacy_arm_count(),
        "migrated_count": _routes.migrated_count(),
        "total": len(_routes.ROUTES),
    })


# ── Browser auth-cookie login/logout (rearch W9 / C2) ───────────────────────
def _request_presented_token(handler, body):
    """The shared-secret token this request carried, or ``None``.

    Mirrors the do_POST middleware's extraction order (X-Anchor-Token header →
    standard Authorization header → JSON body ``token``) and additionally
    accepts the W9 auth cookie, so the login handler can echo the caller's
    already-validated token into the Set-Cookie value.
    """
    provided = handler.headers.get("X-Anchor-Token")
    if provided is None:
        provided = _paths.token_from_authorization(
            handler.headers.get("Authorization"))
    if provided is None and isinstance(body, dict):
        provided = body.get("token")
    if provided is None:
        provided = _paths.token_from_cookie(handler.headers.get("Cookie"))
    return provided


def _request_is_secure(handler):
    """True iff the request reached us over HTTPS (so the cookie gets ``Secure``).

    Tailscale Serve terminates TLS and proxies to the loopback HTTP server,
    declaring the original scheme via ``X-Forwarded-Proto``. On the plain-HTTP
    ``http://localhost:8777`` loopback the header is absent → ``Secure`` is
    omitted so the cookie is still accepted locally.
    """
    xf = (handler.headers.get("X-Forwarded-Proto") or "").strip().lower()
    if xf:
        return xf == "https"
    return bool(getattr(handler, "_is_tls", False))


def _send_json_with_cookie(handler, data, cookie, code=200):
    """Send a JSON response carrying ONE ``Set-Cookie`` header (W9 login/logout)."""
    payload = json.dumps(data).encode()
    try:
        handler.send_response(code)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("X-Content-Type-Options", "nosniff")
        if cookie is not None:
            handler.send_header("Set-Cookie", cookie)
        handler.send_header("Cache-Control", "no-store")
        handler.send_header("Content-Length", str(len(payload)))
        handler.end_headers()
        handler.wfile.write(payload)
    except Exception as exc:
        if _is_benign_disconnect(exc):
            return
        raise


def handle_auth_login(handler, path, body):
    """POST /api/auth/login — mint the HttpOnly browser auth cookie (rearch W9).

    The do_POST token middleware has ALREADY validated the caller (the row is
    ``token``, default-deny), so this only ever runs for an authenticated
    request. It Set-Cookies the presented token so subsequent same-origin page
    navigation (``/project/``, ``/report/``, ``/summary/``, ``/artifact/``,
    ``/api/rnd/projects`` …) and the ``term_ws`` upgrade authenticate off the
    cookie — no shared-secret token ever rides in a page URL under
    ``ANCHOR_AUTH_MODE=enforce``.
    """
    want = _paths.expected_token()
    if want is None:
        # Auth disabled (no ANCHOR_TOKEN) — nothing to gate, no cookie to set.
        _send_json_with_cookie(handler, {"ok": True, "auth": "disabled"}, None)
        return
    token = _request_presented_token(handler, body)
    if not _paths.auth_ok(token):
        # Belt-and-suspenders: the middleware already enforced this.
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    cookie = _paths.build_auth_cookie(token, secure=_request_is_secure(handler))
    _send_json_with_cookie(handler, {"ok": True, "auth": "cookie-set"}, cookie)


def handle_auth_logout(handler, path, body):
    """POST /api/auth/logout — clear the browser auth cookie (rearch W9)."""
    cookie = _paths.build_auth_cookie(
        None, secure=_request_is_secure(handler), clear=True)
    _send_json_with_cookie(
        handler, {"ok": True, "auth": "cookie-cleared"}, cookie)


# ── R&D mutation + data handlers (strangler calibration batch) ──────────────
def handle_set_priority(handler, path, body):
    """POST /api/rnd/set_priority — set a project's dashboard priority.

    Token-gated by the do_POST middleware (which runs before the strangler)."""
    pid = body.get("id", "")
    try:
        entry = _rnd.set_priority(pid, int(body.get("priority", 2)))
        handler._send_json({"ok": True, "entry": entry})
    except KeyError:
        handler._send_json({"ok": False, "error": "Not found"}, 404)


def handle_set_group(handler, path, body):
    """POST /api/rnd/set_group — reassign a project's dashboard FOLDER (group).

    Organization-only: this NEVER moves anything on disk (that is the guarded
    on-disk move). Token-gated by the do_POST middleware.
    """
    pid = body.get("project_id", "") or body.get("id", "")
    group = body.get("group", "")
    try:
        entry = _rnd.set_group(pid, group)
        handler._send_json({
            "ok": True,
            "entry": entry,
            "message": (f"Grouped under '{entry.get('group')}'"
                        if entry.get("group")
                        else "Moved to Ungrouped"),
        })
    except KeyError:
        handler._send_json({"ok": False, "error": "Not found"}, 404)


def handle_add_idea(handler, path, body):
    """POST /api/rnd/add_idea — manually add an idea to a project's Grass
    Catchers lane (a real Anchor-created idea card, NOT a discovered artifact).
    Auth is enforced by the middleware. Clean 404 for an unknown project; 400
    for empty text.
    """
    pid = body.get("project_id", "") or body.get("id", "")
    proj = _rnd.get_project(pid)
    if proj is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    else:
        folder = proj.get("folder_path", "")
        try:
            rec = _eh.add_idea(folder, pid,
                               body.get("text", ""),
                               notes=body.get("notes", ""))
            handler._send_json({"ok": True, "effort": rec})
        except ValueError as ve:
            handler._send_json({"ok": False, "error": str(ve)}, 400)


def handle_pin_deliverable(handler, path, body):
    """POST /api/rnd/pin_deliverable — pin a path (e.g. anchor_gui.py) as a
    deliverable so it surfaces as a deliverables-lane effort even though it is
    not under a deliverables/ directory. With ``declare:true``, instead pin
    every deliverable declared in the folder's Anchor.md marker block. Auth is
    enforced by the middleware.
    """
    pid = body.get("project_id", "")
    proj = _rnd.get_project(pid)
    if proj is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    else:
        folder = proj.get("folder_path", "")
        if body.get("declare"):
            res = _deliv.declare_deliverables_from_marker(folder, pid)
            handler._send_json({"ok": True, **res})
        else:
            target = body.get("path", "") or body.get("target", "")
            if not target:
                handler._send_json({"ok": False,
                                    "error": "path required"}, 400)
            else:
                try:
                    rec = _deliv.pin_deliverable(
                        folder, pid, target,
                        name=body.get("name"),
                        dtype=body.get("type"),
                        description=body.get("description", ""),
                    )
                except ValueError as e:
                    # A path that escapes the project folder is rejected
                    # cleanly (400), never a 500-crash.
                    handler._send_json({"ok": False, "error": str(e)}, 400)
                else:
                    handler._send_json({"ok": True, "effort": rec})


def handle_remote_status(handler, path, body):
    """GET /api/rnd/remote_status — the project's GitHub link state for the
    header control: {linked, remote_url, auto_push}. NO mutation, NO network.

    Token-authed by the route row (the strangler applies the row's auth via
    ``_term_token_ok`` BEFORE this handler runs), so no inline auth check is
    needed. Reads ``?project_id=`` off ``handler.path``.
    """
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("project_id", [""])[0]
           or q.get("pid", [""])[0]
           or q.get("id", [""])[0] or "").strip()
    if not pid:
        handler._send_json({"ok": False, "error": "project_id required"}, 400)
    elif _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad pid"}, 400)
    elif _rnd.get_project(pid) is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    else:
        st = _remote.remote_status(pid)
        handler._send_json({"ok": True, "linked": st["linked"],
                            "remote_url": st["remote_url"],
                            "auto_push": st["auto_push"]})


def handle_chain(handler, path, body):
    """GET /api/rnd/chain — the ordered lineage chain a session belongs to, for
    the panel-header breadcrumb (R-1 → P-2 → …). Emits a SAFE projection of each
    member (never worktree_path / branch).

    Token-authed by the route row (the strangler applies the row's auth BEFORE
    this handler runs). Reads ``?session=`` off ``handler.path``.
    """
    q = parse_qs(urlparse(handler.path).query)
    sid = (q.get("session", [""])[0]
           or q.get("session_id", [""])[0] or "").strip()
    if not sid:
        handler._send_json({"ok": False, "error": "session required"}, 400)
    else:
        try:
            chain_id = _sessreg.chain_for(sid)
            members = (_sessreg.chain_members(chain_id)
                       if chain_id else [])
        except Exception:
            chain_id = None
            members = []
        safe = []
        for r in members:
            if not isinstance(r, dict):
                continue
            safe.append({
                "session_id": r.get("session_id"),
                "lane": r.get("lane", ""),
                "label": r.get("label", ""),
                "status": r.get("status", ""),
                "parent_session_id": r.get("parent_session_id", ""),
                "chain_id": r.get("chain_id", ""),
                # v10 Wave 4: grass→project lineage (SAFE — idea id only).
                "grass_origin": r.get("grass_origin", ""),
            })
        handler._send_json({"ok": True, "chain_id": chain_id or "",
                            "members": safe})


def handle_done(handler, path, body):
    """POST /api/done — mark a task done. Token-gated by the do_POST middleware."""
    text = body.get("text", "")
    ok = mark_done(text)
    handler._send_json({"ok": ok, "message": f"Marked done: {text}" if ok else f"Not found: {text}"})


def handle_undone(handler, path, body):
    """POST /api/undone — reopen a completed task. Token-gated by the middleware."""
    text = body.get("text", "")
    ok = mark_undone(text)
    handler._send_json({"ok": ok, "message": f"Reopened: {text}" if ok else f"Not found: {text}"})


def handle_add(handler, path, body):
    """POST /api/add — add a new task. Token-gated by the do_POST middleware."""
    text = body.get("text", "")
    domain = body.get("domain", "academic")
    priority = body.get("priority", 2)
    energy = body.get("energy", "med")
    due = body.get("due", "")
    notes = body.get("notes", "")
    add_task(text, domain, priority, energy, due, notes)
    handler._send_json({"ok": True, "message": f"Added: {text} [{domain}] P{priority}"})


def handle_capture(handler, path, body):
    """POST /api/capture — capture an inbox item. Token-gated by the middleware."""
    text = body.get("text", "")
    domain = body.get("domain", "")
    capture_inbox(text, domain)
    handler._send_json({"ok": True, "message": f"Captured: {text}"})


def handle_edit_task(handler, path, body):
    """POST /api/edit_task — edit a task's properties. Token-gated by the middleware."""
    old_text = body.get("old_text", "")
    ok = edit_task(
        old_text,
        new_text=body.get("new_text"),
        new_priority=body.get("new_priority"),
        new_domain=body.get("new_domain"),
        new_energy=body.get("new_energy"),
        new_due=body.get("new_due"),
        new_notes=body.get("new_notes"),
    )
    handler._send_json({"ok": ok, "message": f"Updated task" if ok else f"Task not found: {old_text}"})


def handle_edit_project(handler, path, body):
    """POST /api/edit_project — edit a project's properties. Token-gated by the middleware."""
    old_name = body.get("old_name", "")
    ok = edit_project(
        old_name,
        new_name=body.get("new_name"),
        new_priority=body.get("new_priority"),
        new_domain=body.get("new_domain"),
        new_status=body.get("new_status"),
        new_effort=body.get("new_effort"),
        new_due=body.get("new_due"),
        new_next=body.get("new_next"),
    )
    handler._send_json({"ok": ok, "message": f"Updated project" if ok else f"Project not found: {old_name}"})


def handle_promote_task(handler, path, body):
    """POST /api/promote_task — promote a task to P1. Token-gated by the middleware."""
    text = body.get("text", "")
    ok = edit_task(text, new_priority=1)
    handler._send_json({"ok": ok, "message": f"Promoted to P1: {text}" if ok else f"Not found: {text}"})


def handle_demote_task(handler, path, body):
    """POST /api/demote_task — demote a task to P2. Token-gated by the middleware."""
    text = body.get("text", "")
    ok = edit_task(text, new_priority=2)
    handler._send_json({"ok": ok, "message": f"Demoted to P2: {text}" if ok else f"Not found: {text}"})


def handle_cancel(handler, path, body):
    """POST /api/cancel — cancel a task (→ CANCELLED.md). Token-gated by the middleware."""
    text = body.get("text", "")
    ok = cancel_task(text)
    handler._send_json({"ok": ok, "message": f"Cancelled: {text}" if ok else f"Not found: {text}"})


def handle_save_for_later(handler, path, body):
    """POST /api/save_for_later — save a task for later (→ SAVED_FOR_LATER.md). Token-gated by the middleware."""
    text = body.get("text", "")
    ok = save_for_later(text)
    handler._send_json({"ok": ok, "message": f"Saved for later: {text}" if ok else f"Not found: {text}"})


def handle_restore(handler, path, body):
    """POST /api/restore — restore a task from an archive (saved/cancelled). Token-gated by the middleware."""
    text = body.get("text", "")
    from_archive = body.get("from", "saved")
    ok = restore_task(text, from_archive)
    handler._send_json({"ok": ok, "message": f"Restored: {text}" if ok else f"Not found: {text}"})


def handle_promote_project(handler, path, body):
    """POST /api/promote_project — promote a project to P1. Token-gated by the middleware."""
    name = body.get("name", "")
    ok = edit_project(name, new_priority=1)
    handler._send_json({"ok": ok, "message": f"Promoted to P1: {name}" if ok else f"Not found: {name}"})


def handle_demote_project(handler, path, body):
    """POST /api/demote_project — demote a project to P2. Token-gated by the middleware."""
    name = body.get("name", "")
    ok = edit_project(name, new_priority=2)
    handler._send_json({"ok": ok, "message": f"Demoted to P2: {name}" if ok else f"Not found: {name}"})


def handle_new_project(handler, path, body):
    """POST /api/rnd/new_project — register a new/existing R&D project. Token-gated by the middleware."""
    mode = body.get("mode", "existing")
    name = body.get("name", "")
    priority = body.get("priority", 2)
    if mode == "new_folder":
        res = create_new_folder_project(
            name, body.get("parent_path", ""),
            priority=priority,
            git_init=bool(body.get("git_init", False)),
        )
    else:
        res = select_existing_project(
            name, body.get("folder_path", ""), priority=priority,
        )
    handler._send_json({"ok": True, **res})


def handle_open_project(handler, path, body):
    """POST /api/rnd/open_project — open a project instance. Token-gated by the middleware."""
    pid = body.get("id", "")
    handler._send_json({"ok": True, **open_project_instance(pid)})


def handle_rescan(handler, path, body):
    """POST /api/rnd/rescan — re-discover + re-adopt a brownfield project's on-disk artifacts.

    scan -> adopt -> reconcile (prune deletions) -> rewrite marker. Idempotent
    (no dupes). Clean JSON; never a 500 for a bad folder. Token-gated by the
    middleware.
    """
    pid = body.get("id", "") or body.get("project_id", "")
    res = discover_and_adopt(pid)
    code = 200 if res.get("ok") else 404
    handler._send_json(res, code)


def handle_archive_project(handler, path, body):
    """POST /api/rnd/archive_project — archive a project. Token-gated by the middleware."""
    pid = body.get("id", "")
    try:
        handler._send_json({"ok": True,
                            "entry": _rnd.archive_project(pid)})
    except KeyError:
        handler._send_json({"ok": False, "error": "Not found"}, 404)


def handle_future_project(handler, path, body):
    """POST /api/rnd/future_project — mark a project as future. Token-gated by the middleware."""
    pid = body.get("id", "")
    try:
        handler._send_json({"ok": True,
                            "entry": _rnd.mark_future(pid)})
    except KeyError:
        handler._send_json({"ok": False, "error": "Not found"}, 404)


def handle_retire_project(handler, path, body):
    """POST /api/rnd/retire_project — retire a project. Token-gated by the middleware."""
    pid = body.get("id", "")
    try:
        handler._send_json({"ok": True,
                            "entry": _rnd.retire_project(pid)})
    except KeyError:
        handler._send_json({"ok": False, "error": "Not found"}, 404)


def handle_reactivate_project(handler, path, body):
    """POST /api/rnd/reactivate_project — reactivate a project. Token-gated by the middleware."""
    pid = body.get("id", "")
    try:
        handler._send_json({"ok": True,
                            "entry": _rnd.reactivate_project(pid)})
    except KeyError:
        handler._send_json({"ok": False, "error": "Not found"}, 404)


def handle_set_notes(handler, path, body):
    """POST /api/rnd/set_notes — set a project's free-text notes. Token-gated by the middleware."""
    pid = body.get("id", "")
    try:
        handler._send_json({"ok": True,
                            "entry": _rnd.set_notes(pid, body.get("notes", ""))})
    except KeyError:
        handler._send_json({"ok": False, "error": "Not found"}, 404)


def handle_settings_get(handler, path, body):
    """GET /api/settings — durable model/engine prefs + env override map.

    Token-authed by the route row. Returns load_settings() fields plus
    ``env`` (export_env_overrides), ``cross_model`` (coding ≠ review family),
    and a cheap host-capability profile when available.
    """
    settings = _aset.load_settings()
    payload = {
        "ok": True,
        **settings,
        "env": _aset.export_env_overrides(),
        "cross_model": _aset.families_are_cross_model(),
        # Steward persona catalog + the resolved active profile, so the UI can
        # render the selector (label + one-line desc + icon pair) without
        # hardcoding the persona set client-side.
        "stewards": _aset.STEWARDS,
        "steward": _aset.steward_profile(settings),
    }
    try:
        payload["host_profile"] = _lanes.detect_host_profile()
    except Exception:
        pass
    handler._send_json(payload)


def handle_settings_post(handler, path, body):
    """POST /api/settings — merge partial model prefs; return full settings.

    Accepts any of ``default_cli``, ``coding_family``, ``review_family``.
    Invalid values → 400. Token-authed by the route row (mutating).
    """
    body = body or {}
    kwargs = {}
    for key in ("default_cli", "coding_family", "review_family",
                "steward_type"):
        if key in body and body[key] is not None:
            kwargs[key] = body[key]
    if not kwargs:
        # No-op write: still return the current full settings snapshot.
        settings = _aset.load_settings()
        handler._send_json({
            "ok": True,
            **settings,
            "env": _aset.export_env_overrides(),
            "cross_model": _aset.families_are_cross_model(),
        })
        return
    try:
        settings = _aset.save_settings(**kwargs)
    except ValueError as exc:
        handler._send_json({"ok": False, "error": str(exc)}, 400)
        return
    handler._send_json({
        "ok": True,
        **settings,
        "env": _aset.export_env_overrides(),
        "cross_model": _aset.families_are_cross_model(),
    })


def handle_set_blurb(handler, path, body):
    """POST /api/rnd/set_blurb — set a project's blurb. Token-gated by the middleware."""
    pid = body.get("id", "")
    try:
        handler._send_json({"ok": True,
                            "entry": _rnd.set_blurb(pid, body.get("blurb", ""))})
    except KeyError:
        handler._send_json({"ok": False, "error": "Not found"}, 404)


def handle_link_task(handler, path, body):
    """POST /api/rnd/link_task — link/unlink a task ↔ R&D project (activates the
    Project: field). Token-gated by the do_POST middleware."""
    text = body.get("text", "")
    pid = body.get("project_id", "")
    ok = link_task(text, pid)
    handler._send_json({
        "ok": ok,
        "message": (f"Linked '{text}' → {pid}" if pid else
                    f"Unlinked '{text}'") if ok
                   else f"Task not found: {text}",
    })


def handle_project_rollup(handler, path, body):
    """GET /api/rnd/project_rollup — the per-project cost/tokens/time rollup
    (effort_history.project_effort_rollup) for the header's lifetime/30-day toggle.
    RUN-session totals only (imported/discovered contribute 0 — never fabricated).
    Returns both the raw fields and a pre-formatted ``text`` for the header swap.

    Token-authed by the route row (the strangler applies the row's auth BEFORE
    this handler runs). Reads the query off ``handler.path``.
    """
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("pid", [""])[0]
           or q.get("project_id", [""])[0] or "").strip()
    window = (q.get("window", ["lifetime"])[0] or "lifetime").strip()
    if window not in (_eh.WINDOW_LIFETIME, _eh.WINDOW_30D):
        window = _eh.WINDOW_LIFETIME
    if not pid:
        handler._send_json({"ok": False, "error": "pid required"}, 400)
    elif _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad pid"}, 400)
    else:
        try:
            roll = _eh.project_effort_rollup(pid, window=window)
        except Exception:
            roll = {"tokens": 0, "cost_usd": 0.0,
                    "wall_clock_ms": 0, "sessions": 0}
        rate = {}
        try:
            rate = _rollhon.project_capture_rate(pid, window=window) or {}
        except Exception:
            rate = {}
        live_n = _live_session_count(pid)
        handler._send_json({"ok": True, "window": window,
                            "rollup": roll,
                            "capture_rate": rate,
                            "live_sessions": live_n,
                            "text": _fmt_project_usage_line(
                                roll, rate=rate, live_count=live_n)})


def handle_effort_rollup(handler, path, body):
    """GET /api/rnd/effort_rollup — the SELECTED effort's cost/tokens/wall-clock
    rollup, summed over the effort's per-stage job_runner cost records
    (effort_view.effort_rollup). SAFE — numbers only (no worktree/branch).

    Token-authed by the route row (the strangler applies the row's auth BEFORE
    this handler runs). Reads the query off ``handler.path``.
    """
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("pid", [""])[0]
           or q.get("project_id", [""])[0] or "").strip()
    effort = (q.get("effort", [""])[0]
              or q.get("session", [""])[0] or "").strip()
    if not pid or not effort:
        handler._send_json({"ok": False,
                            "error": "pid, effort required"}, 400)
    elif _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad pid"}, 400)
    else:
        proj = _rnd.get_project(pid)
        folder = (proj or {}).get("folder_path", "")
        roll = {"tokens": 0, "cost_usd": 0.0, "wall_clock_ms": 0}
        try:
            roll = _effview.effort_rollup(folder, pid, effort)
        except Exception:
            pass
        handler._send_json({
            "ok": True,
            "tokens": int(roll.get("tokens", 0) or 0),
            "cost_usd": float(roll.get("cost_usd", 0.0) or 0.0),
            "wall_clock_ms": int(roll.get("wall_clock_ms", 0) or 0),
        })


def handle_boneyard(handler, path, body):
    """GET /api/rnd/boneyard — the project's per-project Boneyard: a searchable
    list of DISCARDED material (hard-killed sessions w/ material, v9-deleted
    sessions, deleted grass ideas). Project-scoped. Empty ``q`` → ALL entries
    (newest-first); else boneyard.search. Each entry is the SAFE projection PLUS
    server-built, traversal-safe ``doc_links`` (href via the existing /artifact
    route).

    Token-authed by the route row (the strangler applies the row's auth BEFORE
    this handler runs). Reads the query off ``handler.path``.
    """
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("project_id", [""])[0]
           or q.get("pid", [""])[0]
           or q.get("id", [""])[0] or "").strip()
    query = (q.get("q", [""])[0] or "").strip()
    if not pid:
        handler._send_json({"ok": False,
                            "error": "project_id required"}, 400)
    elif _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad pid"}, 400)
    else:
        proj = _rnd.get_project(pid)
        if proj is None:
            handler._send_json({"ok": False,
                                "error": "Unknown project"}, 404)
        else:
            folder = proj.get("folder_path", "")
            try:
                if query:
                    entries = _boneyard.search(folder, pid, query)
                else:
                    entries = _boneyard.list_entries(folder, pid)
            except Exception:
                entries = []
            out = [_boneyard_entry_view(pid, e) for e in entries]
            handler._send_json({"ok": True, "entries": out, "q": query})



def _ecgberht_root():
    """Resolve the Ecgberht engine root: ECGBERHT_ROOT env override, else the
    sibling checkout next to this Anchor tree (Ecgberht beside Anchor).
    Never a host-absolute literal in call sites."""
    env = os.environ.get("ECGBERHT_ROOT", "").strip()
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "Ecgberht"


def _ecgberht_bridge(args, timeout=20):
    """Spawn the Ecgberht seal-chamber bridge (Node, read-only) and parse its
    one-line JSON. Same closed verb bodies as the ecgberht CLI (parity)."""
    import subprocess
    root = _ecgberht_root()
    bridge = root / "scripts" / "seal-chamber-bridge.mjs"
    if not bridge.exists():
        return {"ok": False, "error": "ecgberht_engine_missing",
                "message": "seal-chamber bridge not found (set ECGBERHT_ROOT "
                           "or keep Ecgberht checkout beside Anchor)"}
    try:
        res = subprocess.run(
            ["node", str(bridge)] + list(args),
            capture_output=True, text=True, timeout=timeout,
            # Node emits UTF-8; without this Windows decodes cp1252 and
            # the steward's dialogue (em-dashes, curly quotes, flags)
            # turns to mojibake in the chamber/overlay.
            encoding="utf-8", errors="replace",
            cwd=str(root), creationflags=_paths.NO_WINDOW)
    except Exception as exc:
        return {"ok": False, "error": "bridge_spawn_failed",
                "message": str(exc)}
    out = (res.stdout or "").strip()
    if not out:
        return {"ok": False, "error": "bridge_no_output",
                "message": (res.stderr or "").strip()[:500]}
    try:
        return json.loads(out.splitlines()[-1])
    except Exception:
        return {"ok": False, "error": "bridge_bad_json",
                "message": out[:500]}


def _ecgberht_project_folder(pid):
    """project_id -> (folder, error_json, status). Same validation as boneyard."""
    if not pid:
        return None, {"ok": False, "error": "project_id required"}, 400
    if _unsafe_path_seg(pid):
        return None, {"ok": False, "error": "bad pid"}, 400
    proj = _rnd.get_project(pid)
    if proj is None:
        return None, {"ok": False, "error": "Unknown project"}, 404
    folder = (proj.get("folder_path") or "").strip()
    if not folder:
        # A registry row with a blank folder_path would otherwise reach the
        # bridge as `--project ""`, which spawns Node to work on nothing.
        return None, {"ok": False, "error": "project_has_no_folder",
                      "message": "the project record carries no folder_path"}, 409
    return folder, None, 200


def handle_ecgberht_chamber(handler, path, body):
    """GET /api/ecgberht/chamber — Seal chamber view model (wireframes v2.1 Screen 1)."""
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("project_id", [""])[0] or q.get("pid", [""])[0] or "").strip()
    folder, err, status = _ecgberht_project_folder(pid)
    if err is not None:
        handler._send_json(err, status)
        return
    out = _ecgberht_bridge(["--project", folder])
    handler._send_json(out, 200 if out.get("ok") else 502)


def handle_ecgberht_speak(handler, path, body):
    """POST /api/ecgberht/speak — compile saybox talk (closed acts only)."""
    pid = str(body.get("project_id", "") or "").strip()
    text = str(body.get("text", "") or "").strip()
    kind = str(body.get("kind", "speak") or "speak").strip()
    folder, err, status = _ecgberht_project_folder(pid)
    if err is not None:
        handler._send_json(err, status)
        return
    if not text:
        handler._send_json({"ok": False, "error": "text required"}, 400)
        return
    if _ecgberht_reject_oversized(handler, text):
        return
    flag = "--recall" if kind == "recall" else "--speak"
    out = _ecgberht_bridge(["--project", folder, flag, text])
    handler._send_json(out, 200 if out.get("ok") else 502)


def handle_ecgberht_stand_up(handler, path, body):
    """POST /api/ecgberht/stand_up — TW7 Screen 4 stand-up confirm ONLY:
    create Face+Strip from the pack templates once John has spoken the goal
    in his own words. The steward never invents a goal; an empty goal is a
    structured refusal, and the engine refuses freeze-tree targets
    (realpath-before-prefix, junction-aware)."""
    pid = str(body.get("project_id", "") or "").strip()
    folder, err, status = _ecgberht_project_folder(pid)
    if err is not None:
        handler._send_json(err, status)
        return
    goal = str(body.get("north_star", "") or "").strip()
    if not goal:
        handler._send_json({"ok": False, "error": "empty_goal_refused",
                            "message": "no goal text — the steward never "
                                       "invents one"}, 400)
        return
    fields = {"project_path": folder, "north_star": goal,
              "project_id": pid,
              "who": str(body.get("who") or "john"),
              "active_effort": body.get("active_effort")}
    out = _ecgberht_bridge(["--stand-up-confirm", json.dumps(fields)])
    handler._send_json(out, 200 if out.get("ok") else 502)


# ── Ecgberht High Seat (TW6 — wireframes v2.1 Screens 0+2+3) ──────────────
# Portfolio altitude on the live-Anchor MAIN dashboard. Same engine-bridge
# pattern as the TW5 Seal chamber, spawning scripts/high-seat-bridge.mjs.
# Read-compose only; the only writes the bridge can produce are structured
# receipts (override / seen) and single-writer Roadmap appends (decide).

def _ecgberht_hs_bridge(args, timeout=30):
    """Spawn the Ecgberht high-seat bridge (Node) and parse its one-line JSON.
    Same closed surfaces as `ecgberht status --roots …` (CLI parity)."""
    import subprocess
    root = _ecgberht_root()
    bridge = root / "scripts" / "high-seat-bridge.mjs"
    if not bridge.exists():
        return {"ok": False, "error": "ecgberht_engine_missing",
                "message": "high-seat bridge not found (set ECGBERHT_ROOT "
                           "or keep Ecgberht checkout beside Anchor)"}
    try:
        res = subprocess.run(
            ["node", str(bridge)] + list(args),
            capture_output=True, text=True, timeout=timeout,
            # Node emits UTF-8; without this Windows decodes cp1252 and
            # the steward's dialogue (em-dashes, curly quotes, flags)
            # turns to mojibake in the chamber/overlay.
            encoding="utf-8", errors="replace",
            cwd=str(root), creationflags=_paths.NO_WINDOW)
    except Exception as exc:
        return {"ok": False, "error": "bridge_spawn_failed",
                "message": str(exc)}
    out = (res.stdout or "").strip()
    if not out:
        return {"ok": False, "error": "bridge_no_output",
                "message": (res.stderr or "").strip()[:500]}
    try:
        return json.loads(out.splitlines()[-1])
    except Exception:
        return {"ok": False, "error": "bridge_bad_json",
                "message": out[:500]}


#: Cap on user text handed to a bridge AS A COMMAND-LINE ARGUMENT. This is not
#: the PTY path: ``rnd_terminal.MAX_TURN_CHARS`` (100_000) writes to a child's
#: STDIN, which has no such limit. Here the text becomes argv, and Windows caps
#: the entire command line near 32_767 characters — so an oversized paste does
#: not fail as "too long", it fails as an opaque spawn error that surfaces as
#: `bridge_spawn_failed`. Refuse it honestly, before spawning anything.
_ECGBERHT_MAX_SPOKEN_CHARS = 8_000


def _ecgberht_reject_oversized(handler, text):
    """True (and a 413 already sent) iff ``text`` is too long to pass as argv."""
    if len(text) <= _ECGBERHT_MAX_SPOKEN_CHARS:
        return False
    handler._send_json({"ok": False, "error": "text_too_long",
                        "message": "%d characters exceeds the %d-character "
                                   "limit for a spoken act"
                                   % (len(text), _ECGBERHT_MAX_SPOKEN_CHARS),
                        "length": len(text),
                        "limit": _ECGBERHT_MAX_SPOKEN_CHARS}, 413)
    return True


#: The high-seat bridge takes its roots as ONE ``--roots a;b;c`` argument, so a
#: folder path containing a semicolon would be split into two bogus roots. A
#: semicolon is legal in a Windows directory name, so this is filtered, not
#: assumed away.
_ECGBERHT_ROOT_DELIM = ";"


def _ecgberht_portfolio_roots():
    """Active R&D project folders = the High Seat's discovery roots.

    Returns ``(roots, skipped, failed)``. Registry-derived, never a hardcoded
    host path.

    ``failed`` exists because this used to swallow every exception and return
    ``[]`` — so a registry read that BLEW UP was reported to the user as the
    cheerful "no active R&D project folders to steward". An empty portfolio and
    a broken registry are not the same state and must not render the same.

    ``skipped`` carries any root containing the delimiter (see
    ``_ECGBERHT_ROOT_DELIM``); including one would silently corrupt the root
    list the engine sees, so it is dropped and reported rather than mis-split.
    """
    roots = []
    skipped = []
    try:
        for entry in _rnd.list_projects(include_archived=False,
                                        include_future=False,
                                        include_retired=False):
            folder = (entry.get("folder_path") or "").strip()
            if not folder or folder in roots:
                continue
            if _ECGBERHT_ROOT_DELIM in folder:
                skipped.append(folder)
                continue
            roots.append(folder)
    except Exception:
        return [], skipped, True
    return roots, skipped, False


def handle_ecgberht_high_seat(handler, path, body):
    """GET /api/ecgberht/high_seat — Screen 2 view model (raise queue +
    tiles + spoken capacity balancing) over all active project roots."""
    roots, skipped, failed = _ecgberht_portfolio_roots()
    if failed:
        # A registry read that BLEW UP is not an empty portfolio. Say so.
        handler._send_json({"ok": False, "error": "registry_unreadable",
                            "message": "could not read the project registry; "
                                       "the portfolio is unknown, not empty"}, 502)
        return
    if not roots:
        handler._send_json({"ok": False, "error": "no_projects",
                            "message": "no active R&D project folders to steward",
                            "skipped_roots": skipped}, 200)
        return
    out = _ecgberht_hs_bridge(["--roots", _ECGBERHT_ROOT_DELIM.join(roots)])
    if skipped and isinstance(out, dict):
        out["skipped_roots"] = skipped
    handler._send_json(out, 200 if out.get("ok") else 502)


def handle_ecgberht_high_seat_badge(handler, path, body):
    """GET /api/ecgberht/high_seat_badge — ⚑ raise-queue length ONLY.
    The single ambient Ecgberht signal anywhere in Anchor (S0-E2)."""
    roots, _skipped, failed = _ecgberht_portfolio_roots()
    if failed:
        # The badge is ambient chrome, so it stays quiet rather than throwing a
        # banner — but it must not claim a queue of 0, which reads as "nothing
        # needs you". Report the unknown honestly and let the UI hide it.
        handler._send_json({"ok": False, "error": "registry_unreadable",
                            "mode": "badge", "queue_length": None}, 502)
        return
    if not roots:
        handler._send_json({"ok": True, "mode": "badge",
                            "badge": {"glyph": "⚑", "count": 0},
                            "queue_length": 0}, 200)
        return
    out = _ecgberht_hs_bridge(
        ["--roots", _ECGBERHT_ROOT_DELIM.join(roots), "--badge"])
    handler._send_json(out, 200 if out.get("ok") else 502)


def handle_ecgberht_bring_up(handler, path, body):
    """GET /api/ecgberht/bring_up?project_id= — in-overlay altitude hop to the
    project's Decision Packet (Option P path passport; zero further gathering)."""
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("project_id", [""])[0] or "").strip()
    folder, err, status = _ecgberht_project_folder(pid)
    if err is not None:
        handler._send_json(err, status)
        return
    out = _ecgberht_hs_bridge(["--bring-up", folder])
    handler._send_json(out, 200 if out.get("ok") else 502)


def handle_ecgberht_high_seat_act(handler, path, body):
    """POST /api/ecgberht/high_seat_act — closed High Seat acts only:
    speak (compile), override (balancing → receipt), decide (packet answer →
    receipt moving the Roadmap through the single writer)."""
    kind = str(body.get("kind", "") or "").strip()
    if kind == "speak":
        text = str(body.get("text", "") or "").strip()
        if not text:
            handler._send_json({"ok": False, "error": "text required"}, 400)
            return
        if _ecgberht_reject_oversized(handler, text):
            return
        out = _ecgberht_hs_bridge(["--speak", text])
    elif kind == "override":
        fields = {k: body.get(k) for k in ("who", "why", "from", "to")}
        out = _ecgberht_hs_bridge(["--override", json.dumps(fields)])
    elif kind == "decide":
        pid = str(body.get("project_id", "") or "").strip()
        folder, err, status = _ecgberht_project_folder(pid)
        if err is not None:
            handler._send_json(err, status)
            return
        fields = {
            "project_path": folder,
            "step_id": body.get("step_id"),
            "decision": body.get("decision"),
            "who": body.get("who") or "john",
            "why": body.get("why"),
        }
        out = _ecgberht_hs_bridge(["--decide", json.dumps(fields)])
    elif kind == "capacity_choice":
        # TW7 S4-E2 — one of the three honest options under unknown capacity:
        # lite_now / queue_full / override (which lands as a receipt). There
        # is no silent-FULL path; anything else refuses with the options.
        fields = {"capacity": "unknown",
                  "choice": body.get("choice"),
                  "who": body.get("who") or "john",
                  "why": body.get("why"),
                  "from": body.get("from") or "blocked — capacity unknown",
                  "to": body.get("to") or "FULL admit (human override)"}
        out = _ecgberht_hs_bridge(["--request-full", json.dumps(fields)])
    else:
        handler._send_json({"ok": False, "error": "unknown_act",
                            "allowed": ["speak", "override", "decide",
                                        "capacity_choice"]}, 400)
        return
    handler._send_json(out, 200 if out.get("ok") else 502)


# Artifact display MVP (S3-E4): serve a packet artifact from inside the
# project folder — traversal-safe — so HTML mockups render best-effort inline
# (iframe) and everything else opens in the browser viewer. Never a bare
# path with no open action.
#: Cap on a single steward artifact served inline. The handler reads the whole
#: file into memory on a shared server thread, so this is a memory bound, not a
#: policy preference. 25 MB comfortably covers decision packets and images.
_ECGBERHT_ARTIFACT_MAX_BYTES = 25 * 1024 * 1024

_ECGBERHT_ARTIFACT_TYPES = {
    ".html": "text/html", ".htm": "text/html",
    ".md": "text/plain", ".markdown": "text/plain", ".txt": "text/plain",
    ".json": "application/json",
    ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".gif": "image/gif", ".svg": "image/svg+xml", ".webp": "image/webp",
    ".pdf": "application/pdf",
}


def handle_ecgberht_artifact(handler, path, body):
    """GET /api/ecgberht/artifact?project_id=&rel= — open path for packet
    artifacts (resolve()+relative_to containment, same idiom as static_asset)."""
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("project_id", [""])[0] or "").strip()
    rel = (q.get("rel", [""])[0] or "").strip()
    folder, err, status = _ecgberht_project_folder(pid)
    if err is not None:
        handler._send_json(err, status)
        return
    if not rel:
        handler._send_json({"ok": False, "error": "rel required"}, 400)
        return
    root = Path(folder).resolve()
    target = (root / rel).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        handler._send_json({"ok": False, "error": "artifact_outside_project"}, 400)
        return
    if not target.is_file():
        handler._send_json({"ok": False, "error": "artifact_missing"}, 404)
        return
    # Bounded read: this runs on a shared server thread and reads the whole file
    # into memory before sending, so an oversized artifact in a project folder
    # is an unbounded allocation. Refuse honestly instead of trying.
    try:
        size = target.stat().st_size
    except OSError:
        handler._send_json({"ok": False, "error": "artifact_unreadable"}, 404)
        return
    if size > _ECGBERHT_ARTIFACT_MAX_BYTES:
        handler._send_json({"ok": False, "error": "artifact_too_large",
                            "message": "%d bytes exceeds the %d-byte cap"
                                       % (size, _ECGBERHT_ARTIFACT_MAX_BYTES),
                            "size": size,
                            "limit": _ECGBERHT_ARTIFACT_MAX_BYTES}, 413)
        return
    ctype = _ECGBERHT_ARTIFACT_TYPES.get(target.suffix.lower(),
                                         "application/octet-stream")
    handler._send_bytes(target.read_bytes(), ctype, cache="no-cache")


def handle_build_deliverable(handler, path, body):
    """GET /api/rnd/build_deliverable — resolve the DELIVERABLE one BUILD session
    produced — explicit signals only, never fabricated. Honest
    ``{resolved:false, deliverable:null}`` when unresolved. NO mutation, NO model
    call.

    Token-authed by the route row (the strangler applies the row's auth BEFORE
    this handler runs). Reads the query off ``handler.path``.
    """
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("pid", [""])[0]
           or q.get("project_id", [""])[0] or "").strip()
    lane = (q.get("lane", ["build"])[0] or "build").strip()
    session_id = (q.get("session", [""])[0] or "").strip()
    if not pid or not session_id:
        handler._send_json({"ok": False,
                            "error": "pid, session required"}, 400)
    elif _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad pid"}, 400)
    elif _unsafe_path_seg(lane):
        handler._send_json({"ok": False, "error": "bad lane"}, 400)
    else:
        proj = _rnd.get_project(pid)
        folder = (proj or {}).get("folder_path", "")
        result = {"resolved": False, "deliverable": None,
                  "reason": "no deliverable pinned yet"}
        try:
            session = None
            for s in _sessions.list_sessions(folder, pid, lane):
                if s.get("session_id") == session_id:
                    session = s
                    break
            if session is not None:
                result = _deliv.resolve_build_deliverable(
                    folder, pid, session)
        except Exception:
            result = {"resolved": False, "deliverable": None,
                      "reason": "no deliverable pinned yet"}
        handler._send_json({"ok": True,
                            "resolved": bool(result.get("resolved")),
                            "deliverable": result.get("deliverable"),
                            "reason": result.get("reason", "")})


def handle_orphan_check(handler, path, body):
    """GET /api/rnd/orphan_check — lightweight read-only poll for the dashboard's
    orphan-swarm alert banner: the session_ids of RUNNING sessions currently
    classified ORPHANED (verdict "kill"). Token-gated (the strangler applies the
    row's auth FIRST); a no-op when ANCHOR_TOKEN is unset. Global (not
    project-scoped).
    """
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    import reaper
    import pty_manager
    try:
        attached = set(pty_manager.live_sessions())
    except Exception:
        attached = set()
    orphans = []
    try:
        running_recs = _sessreg.list_sessions(status="running")
        # (#3, single source) An orphan is a RUNNING session with NO LIVE OWNER —
        # not merely one absent from the PTY-attached set. Build the ONE immutable
        # liveness snapshot for this sweep and classify every record against it so
        # a legit, work-doing session with no open browser stream is never falsely
        # flagged as a runaway.
        try:
            _snap = reaper.build_snapshot(attached_pty_ids=attached, records=running_recs,
                                          enumerate_pids=reaper.enumerate_live_pids)
            live_ids = reaper.live_owner_ids(_snap)
        except Exception:
            _snap = None
            live_ids = attached
        for rec in running_recs:
            sid = rec.get("session_id", "")
            try:
                verdict = reaper.classify_record(rec, _snap)
            except Exception:
                # Defensive: a fault NEVER produces a "kill" — abstain-safe so the
                # startup banner can't false-alarm on a hiccup.
                verdict = reaper.VERDICT_ABSTAIN
            # Only alert on orphans born DURING THIS server's life (a restart's
            # prior-instance 'running' records must not fire the startup banner).
            if (verdict == "kill" and sid
                    and float(rec.get("created_at") or 0) >= _SERVER_BOOT_TS):
                orphans.append(sid)
    except Exception:
        pass
    handler._send_json({"ok": True, "orphans": orphans})


def handle_zombie_spenders(handler, path, body):
    """GET /api/rnd/zombie_spenders — lightweight read-only poll for the home
    dashboard's token-spend zombie banner. Server-side reads the node Sentinel's
    /api/state and reports how many VALID zombies exist right now (processes
    spending paid AI tokens with no live session) plus the current burn rate.
    Best-effort: if the node server is down/absent, returns count 0 (no banner)
    rather than erroring. Token-gated like the other read-API GET routes.

    Dual-write dark (G0): under classifierMode=shadow (or missing armed receipt),
    actionable scare count is forced to 0 even if observe dual-run would-be
    candidates exist — no token-spending zombie banner chrome until armed.
    """
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    import urllib.request
    count = 0
    usd_per_min = 0.0
    classifier_mode = "shadow"
    actionable_red_allowed = False
    observe_would_be = 0
    try:
        with urllib.request.urlopen('http://127.0.0.1:48484/api/state', timeout=3) as r:
            st = json.loads(r.read().decode('utf-8'))
        classifier_mode = str(st.get("classifierMode") or "shadow").lower()
        actionable_red_allowed = bool(st.get("actionableRedAllowed"))
        # Prefer explicit dual-write dashboard surface when present
        dash = st.get("dashboardZombieBanner") or {}
        if isinstance(dash, dict) and "actionableRed" in dash:
            if dash.get("actionableRed"):
                count = int(dash.get("count", 0) or 0)
            else:
                count = 0
        elif actionable_red_allowed and classifier_mode in (
                "armed", "armed_partial", "armed_global"):
            zg = st.get("zombies", []) or []
            count = sum(int(g.get("count", 0) or 0) for g in zg)
        else:
            # Shadow / dual-write dark: never paint scare banner
            count = 0
        obs = st.get("observe") or {}
        if isinstance(obs, dict):
            observe_would_be = int(obs.get("wouldBeCount", 0) or 0)
        usd_per_min = float((st.get("ledger", {}) or {}).get("totals", {}).get("usdPerMin", 0) or 0)
    except Exception:
        pass
    handler._send_json({
        "ok": True,
        "count": count,
        "usdPerMin": round(usd_per_min, 2),
        "classifierMode": classifier_mode,
        "actionableRedAllowed": actionable_red_allowed,
        "observeWouldBeCount": observe_would_be,
    })


def handle_reaper_status(handler, path, body):
    """GET /api/rnd/reaper_status — read-only reaper-explain inspection surface:
    the current arm tier + distance-to-bar, the disarm/brake state, the
    abstain-streak health banner, and every running session's classification +
    latest owner-evidence receipt. NO mutation, NO kill/freeze — pure inspection.
    Token-gated (the strangler applies the row's auth FIRST); back-compat when no
    token set. Global (not project-scoped).
    """
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    import reaper_arming as _arm
    try:
        dump = _arm.explain()
    except Exception as exc:
        handler._send_json({"ok": False, "error": str(exc)}, 500)
    else:
        handler._send_json({"ok": True, "reaper": dump})


def handle_promote_grass(handler, path, body):
    # v4 Wave 6: promote a Grass Catcher idea into a NEW seeded session in
    # the target lane (research|plan). Reuses the Wave-1 seed path via
    # effort_history.promote_grass_to_lane → terminal_session.start_session
    # so the opening turn loads the lane skill AND carries the idea text.
    # The idea REMAINS in grass (copy, never destroy). Auth enforced above.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    idea_id = (body.get("idea_id", "") or "").strip()
    lane = (body.get("lane", "") or "").strip()
    # Settings-backed default: a promote opens a NEW session with no prior
    # engine choice, so it uses default_cli — never the project's sticky
    # last_engine (which could be another engine from an unrelated per-session
    # toggle). Other engines stay reachable via the session engine toggle.
    backend = ((body.get("backend", "") or "").strip()
               or _aset.get_default_cli())
    if not pid or not idea_id or not lane:
        handler._send_json(
            {"ok": False,
             "error": "project_id, idea_id and lane required"}, 400)
    elif lane not in _eh.PROMOTE_LANES:
        handler._send_json(
            {"ok": False,
             "error": "lane must be one of %s"
             % (", ".join(_eh.PROMOTE_LANES),)}, 400)
    elif _rnd.get_project(pid) is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    else:
        try:
            rec = _eh.promote_grass_to_lane(pid, idea_id, lane,
                                            backend=backend)
            handler._send_json({"ok": True, "session": rec})
        except ValueError as ve:
            handler._send_json({"ok": False, "error": str(ve)}, 400)
        except _termsess.TerminalSessionError as exc:
            handler._send_json({"ok": False, "error": str(exc)}, 400)


def handle_grass_develop(handler, path, body):
    # v5 Wave 5: DEVELOP a grass idea in a seeded WORKBENCH session in the
    # target lane (research|plan). Reuses the Wave-1 seed path via
    # effort_history.develop_grass_idea → terminal_session.start_session,
    # seeding the idea text + its latest refinements. The idea STAYS in
    # grass (copy, never destroy). Auth enforced by the middleware above.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    idea_id = (body.get("idea_id", "") or "").strip()
    lane = (body.get("lane", "") or "").strip()
    backend = (body.get("backend", "") or "").strip() or None
    if not pid or not idea_id or not lane:
        handler._send_json(
            {"ok": False,
             "error": "project_id, idea_id and lane required"}, 400)
    elif lane not in _eh.PROMOTE_LANES:
        handler._send_json(
            {"ok": False, "error": "lane must be one of %s"
             % (", ".join(_eh.PROMOTE_LANES),)}, 400)
    elif _rnd.get_project(pid) is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    else:
        try:
            rec = _eh.develop_grass_idea(pid, idea_id, lane,
                                         backend=backend)
            handler._send_json({"ok": True, "session": rec})
        except ValueError as ve:
            handler._send_json({"ok": False, "error": str(ve)}, 400)
        except _termsess.TerminalSessionError as exc:
            handler._send_json({"ok": False, "error": str(exc)}, 400)


def handle_grass_workbench(handler, path, body):
    # v12 Wave 11 (SC5): open the idea's SINGLE one-session workbench — ONE
    # stage-carrying effort_managed grass-dev session per idea (no Research/
    # Plan split). Starts at research (researchPrime seeds) and advances
    # research→plan IN-SESSION via /api/rnd/advance_stage; the grass
    # second-advance is gated off for effort_managed ideas (W7). Dedupes/
    # focuses an existing live workbench session (incl. a pre-v12 idea's
    # most-advanced lane session — back-compat A10). Auth enforced above.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    idea_id = (body.get("idea_id", "") or "").strip()
    backend = (body.get("backend", "") or "").strip() or None
    if not pid or not idea_id:
        handler._send_json(
            {"ok": False,
             "error": "project_id and idea_id required"}, 400)
    elif _rnd.get_project(pid) is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    else:
        try:
            rec = _eh.develop_grass_workbench(pid, idea_id,
                                              backend=backend)
            handler._send_json({"ok": True, "session": rec})
        except ValueError as ve:
            handler._send_json({"ok": False, "error": str(ve)}, 400)
        except _termsess.TerminalSessionError as exc:
            handler._send_json({"ok": False, "error": str(exc)}, 400)


def handle_grass_save_refinement(handler, path, body):
    # v5 Wave 5: save a NEW versioned refinement (grass-<id>/dev-N) for an
    # idea (append-only; auto-incrementing N). Marks the idea REFINED.
    # Auth enforced above. 404 unknown project, 400 unknown idea/empty.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    idea_id = (body.get("idea_id", "") or "").strip()
    if not pid or not idea_id:
        handler._send_json(
            {"ok": False,
             "error": "project_id and idea_id required"}, 400)
    else:
        proj = _rnd.get_project(pid)
        if proj is None:
            handler._send_json({"ok": False,
                                "error": "Unknown project"}, 404)
        else:
            folder = proj.get("folder_path", "")
            try:
                rec = _eh.save_grass_refinement(
                    folder, pid, idea_id,
                    text=body.get("text", ""),
                    label=body.get("label", ""),
                    artifacts=body.get("artifacts") or [],
                    session_id=body.get("session_id") or None)
                handler._send_json({"ok": True, "refinement": rec})
            except ValueError as ve:
                handler._send_json({"ok": False, "error": str(ve)}, 400)


def handle_grass_set_status(handler, path, body):
    # v5 Wave 5: set a grass idea's lifecycle status (raw/refined/
    # promoted), validating the transition. Auth enforced above.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    idea_id = (body.get("idea_id", "") or "").strip()
    status = (body.get("status", "") or "").strip()
    if not pid or not idea_id or not status:
        handler._send_json(
            {"ok": False,
             "error": "project_id, idea_id and status required"}, 400)
    else:
        proj = _rnd.get_project(pid)
        if proj is None:
            handler._send_json({"ok": False,
                                "error": "Unknown project"}, 404)
        else:
            folder = proj.get("folder_path", "")
            try:
                rec = _eh.set_grass_status(
                    folder, pid, idea_id, status,
                    promoted_to_session=body.get("promoted_to_session"),
                    promoted_to_lane=body.get("promoted_to_lane"))
                handler._send_json({"ok": True, "idea": rec})
            except ValueError as ve:
                handler._send_json({"ok": False, "error": str(ve)}, 400)


def handle_grass_pull(handler, path, body):
    # v5 Wave 5: PULL a chosen refinement version into a NEW seeded session
    # (research|plan). Reuses the Wave-1 seed path. Idea + refinement are
    # left untouched. Auth enforced above.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    idea_id = (body.get("idea_id", "") or "").strip()
    refinement_id = (body.get("refinement_id", "") or "").strip()
    lane = (body.get("lane", "") or "").strip()
    backend = (body.get("backend", "") or "").strip() or None
    if not pid or not idea_id or not refinement_id or not lane:
        handler._send_json(
            {"ok": False,
             "error": "project_id, idea_id, refinement_id and lane "
                      "required"}, 400)
    elif lane not in _eh.PROMOTE_LANES:
        handler._send_json(
            {"ok": False, "error": "lane must be one of %s"
             % (", ".join(_eh.PROMOTE_LANES),)}, 400)
    elif _rnd.get_project(pid) is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    else:
        try:
            rec = _eh.pull_grass_refinement(
                pid, idea_id, refinement_id, lane, backend=backend)
            handler._send_json({"ok": True, "session": rec})
        except ValueError as ve:
            handler._send_json({"ok": False, "error": str(ve)}, 400)
        except _termsess.TerminalSessionError as exc:
            handler._send_json({"ok": False, "error": str(exc)}, 400)


def handle_grass_export(handler, path, body):
    # v8 Wave 6: EXPORT an idea's research/plan develop WORK up into REAL
    # lane tiles (Option B): copy the develop docs up as board-visible
    # lane sessions AND mark the idea "promoted" with a link. The idea
    # STAYS in grass (copy, never destroy). Auth enforced above.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    idea_id = (body.get("idea_id", "") or "").strip()
    if not pid or not idea_id:
        handler._send_json(
            {"ok": False, "error": "project_id and idea_id required"}, 400)
    elif _rnd.get_project(pid) is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    else:
        try:
            res = _eh.export_grass_to_project(pid, idea_id)
            code = 200 if res.get("ok") else 400
            handler._send_json(res, code)
        except ValueError as ve:
            handler._send_json({"ok": False, "error": str(ve)}, 400)


def handle_grass_archive(handler, path, body):
    # v10 Wave 4 (D7): ARCHIVE a grass dev session's produced docs +
    # summary into a per-idea bundle (survives kill; available at
    # promotion). Distinct from grass_save_refinement (a text snapshot).
    # Token-gated by the do_POST middleware above. The idea STAYS in grass.
    # HONEST: ok:false + reason when there is no dev session / no docs.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    idea_id = (body.get("idea_id", "") or "").strip()
    lane = (body.get("lane", "") or "").strip()
    if not pid or not idea_id or not lane:
        handler._send_json(
            {"ok": False,
             "error": "project_id, idea_id and lane required"}, 400)
    elif lane not in _eh.PROMOTE_LANES:
        handler._send_json(
            {"ok": False, "error": "lane must be one of %s"
             % (", ".join(_eh.PROMOTE_LANES),)}, 400)
    elif _rnd.get_project(pid) is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    else:
        try:
            res = _eh.archive_grass_session(pid, idea_id, lane)
            # ok:false is an honest "nothing to archive" (200, not an
            # error) — the bundle is None + a reason; never fabricated.
            handler._send_json(res, 200)
        except ValueError as ve:
            handler._send_json({"ok": False, "error": str(ve)}, 400)


def handle_grass_advance(handler, path, body):
    # v10 Wave 5 (Pillar 2 #2): ADVANCE a grass idea's RESEARCH dev session
    # → a linked grass PLAN dev session, staying INSIDE the workbench, using
    # the SAME paste-NOT-submit seeded handoff as the project-level advance
    # (Wave 1/2). effort_history.advance_grass_research_to_plan builds the
    # research→plan prompt from the research dev session's persisted docs,
    # starts (or focuses) the CONTAINED (idea, 'plan') dev session with
    # paste_prompt (held UNSENT) + parent_session_id (links the chain) +
    # grass_origin, and records the stage edge. Token-gated by the do_POST
    # middleware above. v11.1 Wave 2: the keystone snapshots a research
    # CONVERSATION's transcript when no file was written, so the plan session
    # ALWAYS opens (transcript-backed or honest-minimal prompt); the only
    # ok:false left is no-research-session (no research dev session at all to
    # advance FROM). The idea STAYS in grass.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    idea_id = (body.get("idea_id", "") or "").strip()
    backend = (body.get("backend", "") or "").strip() or None
    if not pid or not idea_id:
        handler._send_json(
            {"ok": False, "error": "project_id and idea_id required"}, 400)
    elif _rnd.get_project(pid) is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    else:
        try:
            res = _eh.advance_grass_research_to_plan(
                pid, idea_id, backend=backend)
            # ok:false is an honest "nothing to advance" (200, not an
            # error) — session is None + a reason; never fabricated.
            handler._send_json(res, 200)
        except ValueError as ve:
            handler._send_json({"ok": False, "error": str(ve)}, 400)
        except _termsess.TerminalSessionError as exc:
            handler._send_json({"ok": False, "error": str(exc)}, 400)


def handle_grass_delete(handler, path, body):
    # v9 Wave 2 — permanently DELETE a grass idea + all its grass-side
    # stores (pointer-record + index entry + refinements dir + the
    # contained dev_sessions). Token-gated by the do_POST middleware above
    # AND requires an explicit confirm:true (a deliberate, irreversible
    # removal). Project-scoped — never touches another project's grass.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    idea_id = (body.get("idea_id", "") or "").strip()
    confirm = bool(body.get("confirm"))
    if not pid or not idea_id:
        handler._send_json(
            {"ok": False, "error": "project_id and idea_id required"}, 400)
    elif not confirm:
        handler._send_json({"ok": False,
                            "error": "delete requires confirm:true",
                            "reason": "confirm-required"}, 400)
    else:
        proj = _rnd.get_project(pid)
        if proj is None:
            handler._send_json({"ok": False,
                                "error": "Unknown project"}, 404)
        else:
            folder = proj.get("folder_path", "")
            try:
                out = _eh.delete_grass_idea(folder, pid, idea_id)
            except Exception as exc:
                handler._send_json({"ok": False, "error": str(exc)}, 500)
            else:
                handler._send_json({"ok": True,
                                    "deleted": bool(out.get("deleted")),
                                    "result": out})


def handle_gandalf_run(handler, path, body):
    # Gandalf v1 (Wave 2): MANUAL re-run. Schedule a fresh two-stage
    # Gandalf run in a daemon thread and return immediately
    # ({ok, scheduled}). NOT module-flag-gated (manual is explicit); a
    # per-project in-flight guard prevents duplicate pile-up. Auth is
    # enforced by the do_POST token middleware above.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    if not pid:
        handler._send_json({"ok": False,
                            "error": "project_id required"}, 400)
    elif _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad pid"}, 400)
    else:
        proj = _rnd.get_project(pid)
        if proj is None:
            handler._send_json({"ok": False,
                                "error": "Unknown project"}, 404)
        else:
            folder = proj.get("folder_path", "")
            # tier: "standard" (Opus) | "heavy" (Fable-5). Validated in
            # gandalf.run_gandalf (_normalize_tier); default standard.
            tier = (body.get("tier", "") or "standard").strip().lower()
            scheduled = _trigger_gandalf(folder, pid, manual=True,
                                         tier=tier)
            handler._send_json({"ok": True, "scheduled": bool(scheduled),
                                "tier": tier})


def handle_tidy_idy_run(handler, path, body):
    """POST /api/rnd/tidy_idy_run — thin caller for the tidy-idy CLI.

    Dispatches ``bin/tidy-idy.mjs`` via job_runner (build lane) and returns
    quickly with a ``status_url`` / ``job_id`` so the browser tab can show live
    progress. The panel bootstrap URL is fetched via ``tidy_idy_status`` poll
    (or is already present on a second click when a run is live).
    """
    import tidy_idy_runner as _tidy
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    if not pid:
        handler._send_json({"ok": False, "error": "project_id required"}, 400)
        return
    if _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad pid"}, 400)
        return
    proj = _rnd.get_project(pid)
    if proj is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
        return
    folder = proj.get("folder_path", "")
    if not folder:
        handler._send_json({"ok": False, "error": "project has no folder_path"}, 400)
        return
    # Default async: return as soon as status page is known (not after full scan).
    async_mode = body.get("async", True)
    if isinstance(async_mode, str):
        async_mode = async_mode.strip().lower() not in ("0", "false", "no")
    out = _tidy.launch_tidy_idy(pid, folder, async_mode=bool(async_mode))
    status = 200 if out.get("ok") else 400
    if not out.get("ok") and out.get("code") in (
            "spawn-cap-reached",
            getattr(_jr, "REFUSED_SAME_LANE", "same-lane"),
            getattr(_jr, "REFUSED_FOLDER_BUILD", "folder-build-lock"),
            "same-lane", "folder-build-lock", "busy"):
        status = 409
    handler._send_json(out, status)


def handle_tidy_idy_status(handler, path, body):
    """GET /api/rnd/tidy_idy_status?project_id=&job_id= — live run status for the status tab.

    Query must be read from ``handler.path`` (full request URI). The strangler
    passes a query-stripped ``path`` for route matching — using that alone made
    every remote Tailscale poll return ``project_id required`` and freeze the
    status shell at the last launch snapshot (often 42% / save).
    """
    import tidy_idy_runner as _tidy
    # Prefer the live request URI (includes ?project_id=…&token=…); fall back to
    # the strangler path only if somehow empty. Also accept X-Project-Id header
    # (remote status shell sends it so a query-strip bug cannot black-hole polls).
    raw = getattr(handler, "path", None) or path or ""
    qs = parse_qs(urlparse(raw).query)
    if not qs.get("project_id"):
        # body is usually None on GET; keep for tests that pass a dict.
        qs = parse_qs(urlparse(path or "").query) or qs
    hdr_pid = ""
    try:
        hdr_pid = (
            handler.headers.get("X-Project-Id")
            or handler.headers.get("x-project-id")
            or ""
        ).strip()
    except Exception:
        hdr_pid = ""
    pid = (
        (qs.get("project_id") or [""])[0].strip()
        or hdr_pid
        or (body or {}).get("project_id", "")
        or ""
    )
    if isinstance(pid, str):
        pid = pid.strip()
    job_id = (qs.get("job_id") or [""])[0].strip() or (body or {}).get("job_id") or None
    if not pid:
        handler._send_json({"ok": False, "error": "project_id required"}, 400)
        return
    if _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad pid"}, 400)
        return
    proj = _rnd.get_project(pid)
    if proj is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
        return
    folder = proj.get("folder_path", "")
    if not folder:
        handler._send_json({"ok": False, "error": "project has no folder_path"}, 400)
        return
    handler._send_json(
        _tidy.status_for_folder(folder, job_id=job_id or None, project_id=pid)
    )


def handle_tidy_idy_proxy(handler, path, body):
    """GET|POST /api/rnd/tidy_idy_proxy/<project_id>/<...> — reverse-proxy to tool loopback.

    The tidy-idy status page and Triage Panel bind 127.0.0.1 only (by design).
    That works when the browser is on the same machine as Anchor; it fails for
    Tailscale / remote dashboard clients. This route is same-origin with Anchor,
    so remote browsers can reach the panel while the upstream stays loopback.
    """
    import json as _json
    import tidy_idy_runner as _tidy

    parsed = urlparse(path)
    prefix = "/api/rnd/tidy_idy_proxy/"
    if not parsed.path.startswith(prefix):
        handler._send_json({"ok": False, "error": "bad proxy path"}, 400)
        return
    rest = parsed.path[len(prefix):]
    if not rest:
        handler._send_json({"ok": False, "error": "project_id required in path"}, 400)
        return
    parts = rest.split("/", 1)
    pid = parts[0].strip()
    sub = "/" + parts[1] if len(parts) > 1 else "/"
    if not pid or _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad project_id"}, 400)
        return
    proj = _rnd.get_project(pid)
    if proj is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
        return
    folder = proj.get("folder_path", "")
    if not folder:
        handler._send_json({"ok": False, "error": "project has no folder_path"}, 400)
        return

    method = (getattr(handler, "command", None) or "GET").upper()
    # Panel POSTs JSON; the strangler already parsed the body into a dict.
    raw_body = None
    if method in ("POST", "PUT", "PATCH") and body is not None:
        if isinstance(body, (bytes, bytearray)):
            raw_body = bytes(body)
        else:
            raw_body = _json.dumps(body).encode("utf-8")

    fwd_headers = {}
    # Capability token for the panel control plane (never logged).
    tok = handler.headers.get("x-tidy-idy-token") or handler.headers.get("X-Tidy-Idy-Token")
    if tok:
        fwd_headers["x-tidy-idy-token"] = tok
    ctype = handler.headers.get("Content-Type")
    if ctype:
        fwd_headers["Content-Type"] = ctype
    elif raw_body is not None:
        fwd_headers["Content-Type"] = "application/json"

    result = _tidy.proxy_to_loopback(
        folder,
        method=method,
        rel_path=sub,
        query=parsed.query or "",
        headers=fwd_headers,
        body=raw_body,
    )

    def _tidy_html_page(title, heading, body_html, code=410):
        from html import escape as _html_esc
        html = (
            "<!doctype html><html><head><meta charset=utf-8>"
            f"<title>{_html_esc(title)}</title>"
            '<link rel="icon" href="/vendor/brand/tidy-idy-icon.jpg" type="image/jpeg"/>'
            "<style>body{font-family:system-ui,sans-serif;background:#0f1115;color:#e8eaed;"
            "padding:2rem;line-height:1.5} .card{max-width:36rem;border:1px solid #2a2f3a;"
            "border-radius:12px;padding:1.25rem 1.4rem;background:#161a22}"
            "h1{font-size:1.25rem;margin:0 0 .5rem} p{color:#9aa0a6;margin:0 0 .75rem}"
            "code{color:#8ab4f8}</style></head><body><div class=card>"
            f"<h1>{_html_esc(heading)}</h1>{body_html}</div></body></html>"
        )
        payload = html.encode("utf-8")
        try:
            handler.send_response(code)
            handler.send_header("Content-Type", "text/html; charset=utf-8")
            handler.send_header("Content-Length", str(len(payload)))
            handler.send_header("Cache-Control", "no-store")
            handler.end_headers()
            handler.wfile.write(payload)
        except Exception:
            pass

    # Spent single-use bootstrap: reissue when panel is still live, else clear HTML.
    # Never forward raw JSON "{" to a browser tab (Tailscale operators hit this often).
    status_hop = int(result.get("status") or 0)
    if (
        method == "GET"
        and "/bootstrap/" in str(sub)
        and status_hop == 410
    ):
        fresh = _tidy.reissue_panel_bootstrap(folder)
        if fresh:
            loc = _tidy.browser_open_url(pid, fresh)
            if loc:
                # Preserve Anchor auth token on the redirect.
                tok = None
                try:
                    tok = (parse_qs(parsed.query or "").get("token") or [""])[0]
                except Exception:
                    tok = ""
                if not tok:
                    tok = (handler.headers.get("X-Anchor-Token")
                           or handler.headers.get("x-anchor-token") or "")
                if tok:
                    loc = loc + ("&" if "?" in loc else "?") + "token=" + url_quote(str(tok))
                try:
                    handler.send_response(302)
                    handler.send_header("Location", loc)
                    handler.send_header("Cache-Control", "no-store")
                    handler.end_headers()
                except Exception:
                    pass
                return
        # Panel gone or too old to reissue — clear corpse status and explain.
        try:
            _tidy.mark_status_stale(
                folder, reason="bootstrap nonce spent; panel cannot reissue")
        except Exception:
            pass
        _tidy_html_page(
            "Tidy-Idy — link already used",
            "This panel link was already used",
            "<p>The open link is single-use (so a refresh cannot re-enable Apply).</p>"
            "<p>Close this tab and click <b>Tidy-Idy</b> on the project again to "
            "start a <b>fresh</b> hygiene pass and mint a new open link.</p>"
            "<p><code>bootstrap nonce already redeemed</code></p>",
            code=410,
        )
        return

    if not result.get("ok") and result.get("code"):
        code = 502 if result.get("code") in ("proxy-failed", "upstream-gone", "no-upstream") else 404
        if result.get("code") == "proxy-timeout":
            code = 504
        if result.get("code") == "ssrf-guard":
            code = 403
        # Browser navigations (GET bootstrap / status) should not show raw JSON.
        wants_html = method == "GET" and not str(sub).startswith("/api/")
        if wants_html:
            from html import escape as _html_esc
            err = result.get("error") or "Tidy-Idy panel is not available."
            _tidy_html_page(
                "Tidy-Idy — session ended",
                "Tidy-Idy session ended",
                f"<p>{_html_esc(err)}</p>"
                "<p>Close this tab and click <b>Tidy-Idy</b> on the project again "
                "to start a fresh pass (the previous panel process is no longer running).</p>"
                f"<p><code>{_html_esc(str(result.get('code') or ''))}</code></p>",
                code=code,
            )
            return
        if result.get("code") == "proxy-timeout":
            code = 504
        handler._send_json(
            {"ok": False, "error": result.get("error"), "code": result.get("code")},
            code,
        )
        return

    upstream = result.get("upstream") or ""
    public_base = _tidy.proxy_mount_for(pid)
    payload = result.get("body") or b""
    ctype_out = result.get("content_type") or "application/octet-stream"
    if upstream and isinstance(payload, (bytes, bytearray)):
        payload = _tidy.rewrite_proxied_body(
            bytes(payload),
            content_type=ctype_out,
            upstream_base=upstream,
            public_base=public_base,
        )

    status = int(result.get("status") or 200)

    # If upstream still returned JSON 410 for bootstrap (old panel), convert to HTML.
    if (
        method == "GET"
        and "/bootstrap/" in str(sub)
        and status == 410
        and "json" in (ctype_out or "").lower()
    ):
        _tidy_html_page(
            "Tidy-Idy — link already used",
            "This panel link was already used",
            "<p>Close this tab and click <b>Tidy-Idy</b> on the project again "
            "for a fresh open link.</p>"
            "<p><code>bootstrap nonce already redeemed</code></p>",
            code=410,
        )
        return

    try:
        handler.send_response(status)
        handler.send_header("Content-Type", ctype_out)
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Cache-Control", "no-store")
        # Do not forward upstream Set-Cookie / hop-by-hop headers.
        handler.end_headers()
        handler.wfile.write(payload)
    except Exception:
        pass


def handle_gandalf_delete(handler, path, body):
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    run_id = (body.get("run_id", "") or body.get("session_id", "")).strip()
    if not pid or not run_id:
        handler._send_json({"ok": False, "error": "project_id and run_id required"}, 400)
    elif _unsafe_path_seg(pid) or _unsafe_path_seg(run_id):
        handler._send_json({"ok": False, "error": "bad project_id or run_id"}, 400)
    else:
        proj = _rnd.get_project(pid)
        if proj is None:
            handler._send_json({"ok": False, "error": "Unknown project"}, 404)
        else:
            folder = proj.get("folder_path", "")
            try:
                res = _gandalf.delete_run(folder, pid, run_id)
            except Exception:
                res = {"ok": False, "removed": False}
            handler._send_json({"ok": bool(res.get("ok")), "deleted": bool(res.get("removed"))})


def handle_gandalf_archive(handler, path, body):
    # Archive/retire ONE Gandalf run: drop it from the index + remove its
    # artifact dir (gandalf.delete_run). Mutating; auth enforced by the
    # do_POST token middleware above. Project-scoped + path-seg guarded.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    run_id = (body.get("run_id", "") or "").strip()
    if not pid or not run_id:
        handler._send_json({"ok": False,
                            "error": "project_id and run_id required"}, 400)
    elif _unsafe_path_seg(pid) or _unsafe_path_seg(run_id):
        handler._send_json({"ok": False, "error": "bad pid/run_id"}, 400)
    else:
        proj = _rnd.get_project(pid)
        if proj is None:
            handler._send_json({"ok": False,
                                "error": "Unknown project"}, 404)
        else:
            folder = proj.get("folder_path", "")
            try:
                res = _gandalf.delete_run(folder, pid, run_id)
            except Exception:
                res = {"ok": False, "removed": False}
            handler._send_json({"ok": bool(res.get("ok")),
                                "removed": bool(res.get("removed"))},
                               200 if res.get("ok") else 500)


def handle_gandalf_clear_failed(handler, path, body):
    # Bulk-retire every FAILED Gandalf run (gandalf.clear_failed_runs);
    # completed runs are retained. Mutating; auth enforced by the do_POST
    # token middleware above. Project-scoped.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    if not pid:
        handler._send_json({"ok": False,
                            "error": "project_id required"}, 400)
    elif _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad pid"}, 400)
    else:
        proj = _rnd.get_project(pid)
        if proj is None:
            handler._send_json({"ok": False,
                                "error": "Unknown project"}, 404)
        else:
            folder = proj.get("folder_path", "")
            try:
                res = _gandalf.clear_failed_runs(folder, pid)
            except Exception:
                res = {"ok": False, "removed": 0}
            handler._send_json({"ok": bool(res.get("ok")),
                                "removed": int(res.get("removed") or 0)},
                               200 if res.get("ok") else 500)


def handle_gandalf_cancel(handler, path, body):
    project_id = (body.get("project_id", "") or "").strip()
    if not project_id:
        handler._send_json({"ok": False, "error": "missing project_id"}, 400)
    else:
        cancelled = _gandalf.cancel_gandalf_run(project_id)
        handler._send_json({
            "ok": True,
            "project_id": project_id,
            "cancelled": cancelled,
        })


def handle_term_kill(handler, path, body):
    session = (body.get("session", "") or "").strip()
    if not session:
        handler._send_json({"ok": False, "error": "session required"}, 400)
    elif _termsess.get_session(session) is None:
        handler._send_json({"ok": False,
                         "error": f"unknown session: {session}",
                         "reason": "unknown-session"}, 404)
    else:
        rec = _termsess.get_session(session)
        if rec and rec.get("lane") == "gandalf":
            cancelled = _gandalf.cancel_run(session)
            handler._send_json({"ok": True, "result": {"ok": True, "cancelled": cancelled}})
            return
        # v6 Wave 6: a DELIBERATE hard-kill of a PLANNING session is a
        # DONE transition that may auto-advance to build.
        #
        # v8 Wave 4 (ordering fix): kill() PERSISTS the session's
        # freshly-produced docs into the MAIN folder (Wave 2,
        # capture-before-reap) BEFORE the worktree is reaped. The plan-set
        # capture (discover_recent_plan_set) reads the MAIN folder, so it
        # must run AFTER kill() — otherwise it sees the project as it was
        # before this session and the auto-opened build gets a stale (or no)
        # plan. So: kill (persists docs + sets STATUS_DONE + reaps), THEN
        # capture the now-persisted plan set, THEN auto-advance (idempotent
        # on parent_session_id; no plan ⇒ no advance). Best-effort.
        pid_for_advance = rec.get("project_id") if rec else None
        # v12 Wave 7 — RETIREMENT MAP (Shark C1/C3): a v12 EFFORT
        # advances IN-SESSION (advance_stage / detect_stage_progress) and
        # must NEVER trigger the legacy plan→build auto-advance mint. Gate
        # on ``effort_managed`` ONLY (never lane/kind/current_stage —
        # legacy records carry those too). A legacy record (False) keeps
        # the v6 planning-kill auto-advance fully live.
        planning_kill = (
            rec is not None
            and not rec.get("effort_managed")
            and rec.get("lane") in _termsess._PLANNING_LANES
            and pid_for_advance)
        out = _termsess.kill(session)
        # v7 Wave 2: a killed session is DONE — schedule a background
        # session-summary so the finished tile opens to a real summary
        # (and so it's restartable). Best-effort + non-blocking +
        # idempotent (skips a cached one); never delays the kill response.
        try:
            _trigger_session_summary_on_finish(
                pid_for_advance or (rec.get("project_id") if rec else None),
                rec.get("lane") if rec else None, session)
        except Exception:
            pass
        # v8 Wave 3: auto-push the project AFTER kill() persisted the
        # produced docs (Wave 2, capture-before-reap) — but ONLY when the
        # project is linked to a remote AND has opted in. A non-linked or
        # non-opted project never pushes. Best-effort + never blocks the
        # kill response; in tests origin is a LOCAL BARE repo (no network).
        try:
            _auto_push_on_finish(
                pid_for_advance or (rec.get("project_id") if rec else None))
        except Exception:
            pass
        auto_build = None
        if planning_kill:
            # Capture the plan set AFTER kill() persisted this session's
            # produced docs into the main folder (the ordering fix above).
            try:
                post_plan_set = _termsess.capture_plan_set(
                    pid_for_advance, session)
            except Exception:
                post_plan_set = None
            try:
                auto_build = _termsess.auto_advance_planning_to_build(
                    pid_for_advance, session,
                    plan_set=post_plan_set)
            except Exception:
                auto_build = None
        handler._send_json({"ok": True, "result": out,
                         "auto_build": auto_build})


def handle_term_close(handler, path, body):
    # crucible-improve W6 — the panel "×" GRACEFUL CLOSE. Stop the PTY but
    # PRESERVE the worktree + KEEP the registry record (parked STATUS_IDLE,
    # resumable WARM via W3/W4). close_session persists the produced docs to
    # MAIN (so the boot reaper can't lose them and the W3 resume seed reads
    # them); here we ALSO schedule the SAME best-effort, non-blocking,
    # idempotent background session-summary hook kill/finish use, so a later
    # resume opens WARM, not cold. Token-gated by the do_POST middleware. A
    # park is NOT a finish — never auto-advances. Best-effort throughout.
    session = (body.get("session", "") or "").strip()
    if not session:
        handler._send_json({"ok": False, "error": "session required"}, 400)
    elif _termsess.get_session(session) is None:
        handler._send_json({"ok": False,
                         "error": f"unknown session: {session}",
                         "reason": "unknown-session"}, 404)
    else:
        rec = _termsess.get_session(session)
        out = _termsess.close_session(session)
        try:
            _trigger_session_summary_on_finish(
                rec.get("project_id") if rec else None,
                rec.get("lane") if rec else None, session)
        except Exception:
            pass
        handler._send_json({"ok": True, "result": out})


def handle_term_delete(handler, path, body):
    # v9 Wave 1 — TRUE session delete (DISTINCT from term_kill). Removes
    # the session from Anchor entirely: hard-deletes the registry record
    # (so the tile stays gone across a reload), drops its lane effort
    # pointer-records / index entries / cached summary, and (if still
    # live) kills it first. The produced DOCUMENTS are KEPT (Option A).
    # Token-gated by the do_POST middleware above AND requires an explicit
    # confirm:true in the body (a deliberate, irreversible removal).
    session = (body.get("session", "") or "").strip()
    confirm = bool(body.get("confirm"))
    if not session:
        handler._send_json({"ok": False, "error": "session required"}, 400)
    elif not confirm:
        handler._send_json({"ok": False,
                         "error": "delete requires confirm:true",
                         "reason": "confirm-required"}, 400)
    else:
        try:
            out = _termsess.delete_session(session)
        except Exception as exc:
            handler._send_json({"ok": False, "error": str(exc)}, 500)
        else:
            handler._send_json({"ok": True,
                             "deleted": bool(out.get("deleted")),
                             "result": out})


def handle_cleanup_ghost_sessions(handler, path, body):
    # v9 Wave 1 — sweep a project's empty GHOST sessions (terminal/idle
    # registry records with NO tied efforts). Token-gated + confirm-gated
    # (it deletes records). Project-scoped.
    pid = (body.get("project_id", "") or "").strip()
    confirm = bool(body.get("confirm"))
    if not pid:
        handler._send_json({"ok": False, "error": "project_id required"}, 400)
    elif not confirm:
        handler._send_json({"ok": False,
                         "error": "cleanup requires confirm:true",
                         "reason": "confirm-required"}, 400)
    else:
        try:
            out = _termsess.cleanup_ghost_sessions(pid)
        except Exception as exc:
            handler._send_json({"ok": False, "error": str(exc)}, 500)
        else:
            handler._send_json({"ok": True,
                             "removed": out.get("removed", [])})


def handle_term_set_engine(handler, path, body):
    # v4 Wave 2: switch a live session to another engine (claude|gemini|grok).
    # Token-gated by the do_POST middleware above. Reaps + relaunches in
    # the SAME worktree, re-seeds once, updates the registry backend.
    session = (body.get("session", "") or "").strip()
    engine = (body.get("engine", "") or "").strip()
    if not session or not engine:
        handler._send_json({"ok": False,
                         "error": "session and engine required"}, 400)
    elif engine not in _termsess.VALID_BACKENDS:
        handler._send_json({"ok": False,
                         "error": "invalid engine (expected claude|gemini|grok)",
                         "reason": "invalid-engine"}, 400)
    elif _termsess.get_session(session) is None:
        handler._send_json({"ok": False,
                         "error": f"unknown session: {session}",
                         "reason": "unknown-session"}, 404)
    else:
        try:
            rec = _termsess.switch_engine(session, engine)
        except _termsess.TerminalSessionError as exc:
            handler._send_json({"ok": False, "error": str(exc)}, 400)
        else:
            handler._send_json({"ok": True, "session": rec})


def handle_switch_terminal_engine(handler, path, body):
    # Wave 4: switch engine (claude|gemini|grok) with graceful suspension and summary context handoff.
    # Token-gated by the do_POST middleware above.
    session = (body.get("session", "") or body.get("session_id", "") or "").strip()
    engine = (body.get("engine", "") or "").strip()
    if not session or not engine:
        handler._send_json({"ok": False,
                         "error": "session and engine required"}, 400)
    elif engine not in _termsess.VALID_BACKENDS:
        handler._send_json({"ok": False,
                         "error": "invalid engine (expected claude|gemini|grok)",
                         "reason": "invalid-engine"}, 400)
    elif _termsess.get_session(session) is None:
        handler._send_json({"ok": False,
                         "error": f"unknown session: {session}",
                         "reason": "unknown-session"}, 404)
    else:
        try:
            # Switch engine (which natively does a bounded context summary and injects it) 
            rec = _termsess.switch_engine(session, engine)
            summary_text = ''
            handler._send_json({
                "ok": True,
                "session": rec,
                "context_loaded": bool(summary_text)
            })
        except _termsess.TerminalSessionError as exc:
            handler._send_json({"ok": False, "error": str(exc)}, 400)


def handle_term_resize(handler, path, body):
    session = (body.get("session", "") or "").strip()
    cols = body.get("cols")
    rows = body.get("rows")
    if not session or cols is None or rows is None:
        handler._send_json({"ok": False,
                         "error": "session, cols, rows required"}, 400)
    else:
        out = _termsess.resize(session, cols, rows)
        if out.get("ok"):
            handler._send_json({"ok": True})
        elif out.get("reason") == "unknown-session":
            # A resize is ADVISORY: a session with no live PTY
            # (parked / closed-to-tile / reconnecting, or a stale panel
            # caught mid-teardown or window-reuse) simply has nothing to
            # resize — a benign no-op, NOT a client error. Returning 404
            # here surfaced a spurious "Failed to load resource: 404"
            # browser console error on every reopen/continue, because
            # the terminal fit path fires term_resize as the panel lays
            # out. Report the no-op at HTTP 200 so it never reads as a
            # failed request. (Genuinely bad cols/rows still 400 below.)
            handler._send_json({"ok": False, "noop": True,
                             "reason": "unknown-session"})
        else:
            handler._send_json({"ok": False,
                             "error": out.get("detail", "bad request"),
                             "reason": out.get("reason")}, 400)


def handle_start_terminal(handler, path, body):
    # Start a persistent interactive terminal session for a lane. The
    # returned job_id is the terminal session id the SSE stream + input
    # endpoints key off of. Clean JSON errors (not 500s) for unknown
    # project / invalid lane / engine or concurrency refusals.
    pid = body.get("project_id", "")
    lane = body.get("lane", "")
    backend = body.get("backend") or _aset.get_default_cli()
    if lane not in _lanes.LANES:
        handler._send_json({"ok": False, "error": f"invalid lane: {lane}",
                         "reason": "invalid-lane"}, 400)
    elif backend not in _termsess.VALID_BACKENDS:
        handler._send_json({"ok": False,
                         "error": f"invalid engine: {backend}",
                         "reason": "invalid-engine"}, 400)
    else:
        try:
            rec = _term.start_terminal(pid, lane, backend=backend)
            handler._send_json({
                "ok": True,
                "session": rec.get("job_id"),
                "job_id": rec.get("job_id"),
                "lane": lane,
                "backend": rec.get("backend"),
                "status": rec.get("status"),
                "skill": rec.get("skill"),
                "gates": rec.get("gates"),
            })
        except _lanes.EngineNotAllowedError as eng:
            handler._send_json({"ok": False, "error": str(eng),
                             "reason": "engine-not-allowed",
                             "lane": eng.lane, "backend": eng.backend},
                            400)
        except KeyError:
            handler._send_json({"ok": False,
                             "error": f"unknown project: {pid}",
                             "reason": "unknown-project"}, 404)
        except _jr.LaneBusyError as busy:
            handler._send_json({"ok": False, "error": str(busy),
                             "reason": busy.reason,
                             "holder": busy.holder}, 409)


def handle_term_input(handler, path, body):
    # Write ONE user turn onto a live terminal session's stdin (reuses the
    # gate-adapter stdin sink — never forks it). Auth is enforced by the
    # middleware above. Clean JSON for an unknown/terminal session.
    session = (body.get("session", "") or body.get("job_id", "")).strip()
    text = body.get("text", "")
    if not session:
        handler._send_json({"ok": False, "error": "missing session"}, 400)
    elif text is None or not str(text).strip():
        # Reject an empty/whitespace-only turn cleanly (nothing written).
        handler._send_json({"ok": False, "written": False,
                         "session": session, "error": "empty turn",
                         "reason": "empty"}, 400)
    elif len(str(text)) > _term.MAX_TURN_CHARS:
        # Reject an oversized turn cleanly (nothing written).
        handler._send_json({"ok": False, "written": False,
                         "session": session, "error": "turn too large",
                         "reason": "too-large"}, 413)
    else:
        ok = _term.send_turn(session, text)
        handler._send_json({"ok": bool(ok), "written": bool(ok),
                         "session": session,
                         "reason": None if ok else "not-writable"})


def handle_term_discover(handler, path, body):
    # On session exit, return the adoption PROPOSAL (files this session
    # produced under its output dir) for the UI to confirm. Read-style but
    # POSTed so the token-aware client path is uniform.
    session = (body.get("session", "") or body.get("job_id", "")).strip()
    proposal = _term.discover_produced(session) if session else None
    if proposal is None:
        handler._send_json({"ok": False,
                         "error": f"unknown session: {session}",
                         "reason": "unknown-session"}, 404)
    else:
        handler._send_json({"ok": True, "proposal": proposal})


def handle_term_adopt(handler, path, body):
    # Confirm-adopt a terminal session's produced files as ONE session in
    # the lane (Wave 1 grouping + Wave 2 adopt paths). Auth enforced above.
    session = (body.get("session", "") or body.get("job_id", "")).strip()
    if not session:
        handler._send_json({"ok": False, "error": "missing session"}, 400)
    else:
        sess = _term.adopt_produced(session)
        if sess is None:
            handler._send_json({"ok": False,
                             "error": "nothing to adopt",
                             "reason": "nothing-adoptable"}, 404)
        else:
            handler._send_json({"ok": True, "session": sess})


def handle_term_start(handler, path, body):
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    lane = (body.get("lane", "") or "").strip()
    # Interactive default from durable settings (default_cli), not a hard-coded engine.
    backend = ((body.get("backend", "") or "").strip()
               or _aset.get_default_cli())
    label = body.get("label", "") or ""
    # Wave 6 seam → Wave 7: a launch-from-panel carries the source
    # session id as a seed hint. On a BUILD launch we now consume it:
    # after start_session creates the session+worktree, we discover the
    # most-recent plan set (preferring this seed_session's plan docs),
    # prime the worktree with a HANDOFF reference file, and record the
    # handoff in the per-project Anchor reference. The bare-PTY launch
    # still works when there is no plan set (no crash; priming skipped).
    _seed_session = (body.get("seed_session", "") or "").strip() or None
    # v12 Wave 10: the "+ New effort" control starts an effort_managed trio
    # session (the v12 discriminator — set ONLY by the v12 entrypoints). A
    # legacy launch omits it (default False), so the legacy paths are
    # unaffected. Coerced to a real bool.
    _effort_managed = bool(body.get("effort_managed", False))
    if not pid or not lane:
        handler._send_json({"ok": False,
                         "error": "project_id and lane required"}, 400)
    else:
        proj = _rnd.get_project(pid)
        if proj is None:
            handler._send_json({"ok": False,
                             "error": "Unknown project"}, 404)
        else:
            try:
                rec = _termsess.start_session(pid, lane, backend=backend,
                                              label=label,
                                              effort_managed=_effort_managed)
            except _termsess.TerminalSessionError as exc:
                handler._send_json({"ok": False, "error": str(exc)}, 400)
            else:
                handoff_info = None
                if lane in _handoff.BUILD_LANES:
                    folder = proj.get("folder_path", "")
                    try:
                        plan_set = _handoff.discover_recent_plan_set(
                            folder, pid, source_session_id=_seed_session)
                    except Exception:
                        plan_set = None
                    if plan_set:
                        primed = _handoff.prime_worktree(
                            rec.get("worktree_path", ""), plan_set,
                            project_id=pid)
                        recorded = _handoff.record_handoff(
                            folder, pid, rec.get("session_id", ""),
                            plan_set)
                        handoff_info = {
                            "plan_set": plan_set,
                            "primed": primed,
                            "recorded": bool(recorded.get("ok")),
                        }
                resp = {"ok": True, "session": rec}
                if handoff_info is not None:
                    resp["handoff"] = handoff_info
                handler._send_json(resp)


def _zombie_scan_and_skill_briefing():
    """Whole-computer scan (the System-Wide Sentinel classifier on :48484) plus a
    distilled zombie-hunter awareness block, so the investigator agent reasons
    over the SAME data the GUI shows and knows the safety rules."""
    import urllib.request
    out = "\n\n## Whole-Computer Token-Spend Scan (System-Wide Sentinel)\n"
    try:
        with urllib.request.urlopen('http://127.0.0.1:48484/api/state', timeout=3) as r:
            st = json.loads(r.read().decode('utf-8'))
        tot = (st.get("ledger", {}) or {}).get("totals", {}) or {}
        zombies = st.get("zombies", []) or []
        active = st.get("active", []) or []
        out += (f"- Burn rate NOW: ${tot.get('usdPerMin', 0):.2f}/min "
                f"(${tot.get('usdRecent', 0):.2f} in last {(st.get('ledger', {}) or {}).get('windowMin', 10)}m, "
                f"{tot.get('activeSessions', 0)} active Claude sessions)\n"
                f"- Token-spending ZOMBIES (spending + no live session): {sum(g.get('count', 0) for g in zombies)}\n"
                f"- Active + supervised (your live sessions): {sum(g.get('count', 0) for g in active)}\n"
                f"- Idle engines + non-engine matches (hidden): {st.get('idleCount', 0)} + {st.get('hiddenNonEngine', 0)}\n\n")
        if zombies:
            out += "### ZOMBIES — reap candidates (spending paid tokens, unsupervised)\n"
            for g in zombies[:12]:
                out += (f"- {g.get('count')}x {g.get('name')} | providers={','.join(g.get('providers') or [])} "
                        f"| supervised={g.get('supervised')} root={g.get('root')} "
                        f"| pids={','.join((g.get('pids') or [])[:8])}\n")
            out += "\n"
        sessions = (st.get("ledger", {}) or {}).get("sessions", []) or []
        if sessions:
            out += "### Burn ledger (Claude sessions accruing tokens)\n"
            for s in sessions[:8]:
                out += (f"- ${s.get('usdPerMin', 0):.2f}/min | {s.get('model')} | {s.get('cwd')} "
                        f"| last {s.get('lastActivityAgoMin')}m ago\n")
            out += "\n"
    except Exception as exc:
        out += f"(live scan unavailable: {exc})\n\n"
    out += (
        "## Zombie-Hunter awareness (how to reason)\n"
        "The threat that MATTERS is a process SPENDING PAID AI TOKENS with nobody steering it. "
        "A ZOMBIE = an AI engine (claude->Anthropic, agy/gemini->Google) that is (a) actively "
        "calling a paid provider (live :443 connection to the provider's IP, and/or a Claude "
        "session log accruing tokens) AND (b) NOT rooted in a live interactive session "
        "(parent dead, or service-rooted with no session). An AI run that IS supervised (rooted "
        "in a live powershell/terminal you're using) is NOT a zombie — it's your work. Processes "
        "that merely matched a keyword but spend nothing (tail -f on an AI log, shells) are NOT a "
        "threat and are hidden. Safety: observe-only; prefer FREEZE (reversible) before KILL "
        "(tree-kill); never mass-kill; confirm before killing your own live session.\n\n"
        "Tools: spend detector (zombie-hunter spend.js — network by provider IP-prefix + Claude "
        "token-log $/min ledger from ~/.claude/projects/*/*.jsonl); "
        "classifier classify.js; live scan JSON http://127.0.0.1:48484/api/state; a PID's live API "
        "connections via `Get-NetTCPConnection -OwningProcess <pid> -State Established` (RemotePort 443); "
        "a PID's tree via `Get-CimInstance Win32_Process` (ParentProcessId).\n"
    )
    return out


# ── W8 / SC5+SC6 — shared Investigate + Doctor session-start plumbing (P5) ──
# Shell + engine picker + seed BEFORE session. Session is async/cancelable;
# failure is non-blocking. Engine toggle: Claude, Gemini(agy), Grok (grok-cli /
# grok.exe -p). Dead toggle forbidden; unhealthy engine disabled with health.
# Doctor: shell first, no blocking auto-session. Slim Investigate seed by default.

_W8_ENGINE_IDS = ("claude", "gemini", "grok")
_W8_SHELL_PAINT_BUDGET_MS = 1000
_W8_FIRST_PROMPT_BUDGET_MS = 15_000
_W8_P5_PLUMBING = {
    "id": "p5-shared-session-start",
    "version": "w8-p5-v1",
    "required": [
        "shared_session_start_helper",
        "shell_before_session",
        "engine_picker_three",
        "slim_seed",
        "async_cancelable_session",
        "failure_non_blocking",
        "first_prompt_budget",
        "doctor_shell_first",
    ],
    "surfaces": ["investigate", "doctor"],
    "engines": list(_W8_ENGINE_IDS),
    "shellPaintBudgetMs": _W8_SHELL_PAINT_BUDGET_MS,
    "firstPromptBudgetMs": _W8_FIRST_PROMPT_BUDGET_MS,
}


def _w8_normalize_engine(raw):
    e = (raw or "").strip().lower()
    if e == "agy":
        return "gemini"
    if e in ("grok-cli", "grok.exe"):
        return "grok"
    if e in _W8_ENGINE_IDS:
        return e
    return None


def _w8_engine_toggle(profile=None, prefs=None, last_used=None):
    """Three-engine toggle with health; never offers a silent dead toggle."""
    if profile is None:
        try:
            profile = _lanes.detect_host_profile()
        except Exception:
            profile = {"claude": False, "gemini": False, "grok": False}
    prefs = prefs or {}
    engines = []
    for eid in _W8_ENGINE_IDS:
        available = bool(profile.get(eid))
        transport = {
            "claude": ("claude", "claude"),
            "gemini": ("agy", "agy"),
            "grok": ("grok-cli", "grok.exe -p"),
        }[eid]
        health = "healthy" if available else "unavailable (subscription CLI not detected)"
        engines.append({
            "id": eid,
            "label": eid.capitalize() if eid != "gemini" else "Gemini",
            "transport": transport[0],
            "spawn": transport[1],
            "subscriptionCli": True,
            "available": available,
            "enabled": available,
            "disabled": not available,
            "health": health,
            "firstPromptBudgetMs": _W8_FIRST_PROMPT_BUDGET_MS,
        })
    healthy = [e["id"] for e in engines if e["enabled"]]
    default = None
    last = _w8_normalize_engine(last_used)
    if last and last in healthy:
        default = last
    else:
        family = _w8_normalize_engine(
            prefs.get("coding_family") or prefs.get("default_cli"))
        if family and family in healthy:
            default = family
        elif healthy:
            default = healthy[0]
    return {
        "engines": engines,
        "available": healthy,
        "defaultEngine": default,
        "anyHealthy": bool(healthy),
        "shellPaintBudgetMs": _W8_SHELL_PAINT_BUDGET_MS,
        "firstPromptBudgetMs": _W8_FIRST_PROMPT_BUDGET_MS,
        "profile": {
            "claude": bool(profile.get("claude")),
            "gemini": bool(profile.get("gemini")),
            "grok": bool(profile.get("grok")),
        },
    }


def _w8_resolve_interactive_engine(requested, toggle=None):
    """Pick a healthy engine; refuse dead toggles with health (never silent)."""
    toggle = toggle or _w8_engine_toggle()
    req = _w8_normalize_engine(requested)
    if req:
        row = next((e for e in toggle["engines"] if e["id"] == req), None)
        if row and row["enabled"]:
            return req, None
        reason = (row or {}).get("health") or "unknown engine (dead toggle forbidden)"
        return None, {"engine": req, "reason": reason, "disabled": True}
    if toggle.get("defaultEngine"):
        return toggle["defaultEngine"], None
    return None, {"engine": None, "reason": "no healthy engine", "disabled": True}


def _w8_clip(s, n=240):
    t = "" if s is None else str(s)
    if len(t) <= n:
        return t
    return t[: n - 1] + "…"


def _w8_build_investigate_slim_seed(candidate=None, opts=None):
    """Investigate slim seed: pid + class + top reason codes + freeze/kill status."""
    candidate = candidate or {}
    opts = opts or {}
    reasons = candidate.get("reasonCodes") or candidate.get("topReasonCodes") or []
    if not isinstance(reasons, list):
        reasons = []
    reasons = [str(r) for r in reasons[:8]]
    pid = candidate.get("pid")
    if pid is None and candidate.get("pids"):
        try:
            pid = int(candidate["pids"][0])
        except Exception:
            pid = None
    else:
        try:
            pid = int(pid) if pid is not None else None
        except Exception:
            pid = None
    freeze_status = opts.get("freezeStatus") or candidate.get("freezeStatus") or (
        "disabled" if opts.get("freezeKillEnabled") is False else (
            "available" if opts.get("freezeCapability") else "unavailable"))
    kill_status = opts.get("killStatus") or candidate.get("killStatus") or (
        "disabled" if opts.get("freezeKillEnabled") is False else "confirm_required")
    return {
        "kind": "investigate_slim",
        "version": "w8-investigate-slim-v1",
        "pid": pid,
        "class": _w8_clip(
            candidate.get("engineClass")
            or candidate.get("class")
            or candidate.get("name")
            or "unknown",
            80,
        ),
        "topReasonCodes": reasons,
        "freezeStatus": str(freeze_status),
        "killStatus": str(kill_status),
        "classifierMode": opts.get("classifierMode") or "shadow",
        "freezeCapability": bool(opts.get("freezeCapability")),
        "image": _w8_clip(candidate.get("imagePath") or candidate.get("image") or "", 160),
        "name": _w8_clip(candidate.get("name") or "", 80),
        "slim": True,
        "deepBrief": False,
    }


def _w8_format_investigate_slim_seed_text(slim):
    s = slim or {}
    lines = [
        "ZOMBIE-HUNTER INVESTIGATE — SLIM SEED (W8/SC5)",
        "You help the operator treat ONE candidate. Prefer FREEZE before KILL. Uncertain ≠ red.",
        "pid: %s" % (s.get("pid") if s.get("pid") is not None else "unknown"),
        "class: %s" % (s.get("class") or "unknown"),
        "top reason codes: %s" % (", ".join(s.get("topReasonCodes") or []) or "(none)"),
        "freeze status: %s" % (s.get("freezeStatus") or "unknown"),
        "kill status: %s" % (s.get("killStatus") or "unknown"),
        "classifierMode: %s" % (s.get("classifierMode") or "shadow"),
        "freezeCapability: %s" % bool(s.get("freezeCapability")),
    ]
    if s.get("image"):
        lines.append("image: %s" % s["image"])
    lines.append(
        "Safety: observe-only unless DESTRUCTIVE_ELIGIBLE; never mass-kill; confirm before kill.")
    return "\n".join(lines)


def _w8_build_doctor_short_seed(issue=None):
    """Optional one-click diagnose short seed (shell paints first)."""
    base = {
        "kind": "doctor_short",
        "version": "w8-doctor-short-v1",
        "short": True,
        "note": "Short diagnose seed — shell painted first; session start is on demand.",
        "markdownPath": None,
        "isMarkdownPath": False,
    }
    if not issue or not isinstance(issue, dict):
        return base
    message = _w8_clip(issue.get("message") or issue.get("exactMessage") or "", 400)
    base.update({
        "issueId": str(issue.get("issueId") or issue.get("id") or "") or None,
        "message": message,
        "exactMessage": message,
        "component": _w8_clip(issue.get("component") or "", 120),
        "lastError": _w8_clip(issue.get("lastError") or "", 400),
        "suggestedChecks": [
            _w8_clip(c, 160)
            for c in (issue.get("suggestedChecks") or [])[:8]
        ],
        "bannerSurface": issue.get("bannerSurface"),
    })
    return base


def _w8_format_doctor_short_seed_text(short):
    s = short or {}
    lines = [
        "ANCHOR DOCTOR — SHORT DIAGNOSE SEED (W8/SC6)",
        "Read-only diagnose. Never invent numbers. Shell-first: session started on demand.",
    ]
    if s.get("issueId"):
        lines.append("issueId: %s" % s["issueId"])
    if s.get("message"):
        lines.append("message: %s" % s["message"])
    if s.get("component"):
        lines.append("component: %s" % s["component"])
    if s.get("lastError"):
        lines.append("lastError: %s" % s["lastError"])
    if s.get("suggestedChecks"):
        lines.append("suggestedChecks: %s" % "; ".join(s["suggestedChecks"]))
    lines.append("Say plainly when healthy; prefer inspect-then-suggest over mutation.")
    return "\n".join(lines)


def _w8_shared_session_start_plan(surface="investigate", engine=None, candidate=None,
                                  issue=None, deep_brief=False, slim=True,
                                  prefs=None, last_used=None):
    """Shared session-start helper: shell + picker + seed before session (P5)."""
    try:
        prefs = prefs or {
            "default_cli": _aset.get_default_cli(),
            "coding_family": getattr(_aset, "get_coding_family", lambda: None)()
            if hasattr(_aset, "get_coding_family") else None,
        }
    except Exception:
        prefs = prefs or {}
    toggle = _w8_engine_toggle(prefs=prefs, last_used=last_used)
    eng, denied = _w8_resolve_interactive_engine(engine, toggle)
    if surface == "doctor":
        seed = _w8_build_doctor_short_seed(issue)
        seed_text = _w8_format_doctor_short_seed_text(seed)
    else:
        seed = _w8_build_investigate_slim_seed(candidate or {})
        seed_text = _w8_format_investigate_slim_seed_text(seed)
        if deep_brief:
            seed = {
                "kind": "investigate_deep_brief",
                "version": "w8-investigate-deep-brief-v1",
                "slim": seed,
                "recommendedNext": "INVESTIGATE",
                "deepBrief": True,
            }
            seed_text += "\nrecommendedNext: INVESTIGATE\n(deep-brief path; shell already painted)"
    can_start = bool(eng) and toggle["anyHealthy"] and not denied
    return {
        "surface": surface,
        "shell": {
            "paintFirst": True,
            "paintBudgetMs": _W8_SHELL_PAINT_BUDGET_MS,
            "enginePicker": True,
            "engines": toggle["engines"],
            "autoStartSession": False,
        },
        "seed": seed,
        "seedText": seed_text,
        "seedBeforeSession": True,
        "engine": eng,
        "engineDenied": denied,
        "engineToggle": toggle,
        "session": {
            "async": True,
            "cancelable": True,
            "failureNonBlocking": True,
            "autoStart": False,
            "firstPromptBudgetMs": _W8_FIRST_PROMPT_BUDGET_MS,
            "startWhen": ("operator_or_diagnose_click" if can_start
                          else "blocked_no_healthy_engine"),
        },
        "canStart": can_start,
        "ok": can_start,
        "error": (None if can_start else (
            (denied or {}).get("reason") if denied else "no healthy engine")),
        "p5Plumbing": _W8_P5_PLUMBING,
        "slim": bool(slim),
        "deepBrief": bool(deep_brief),
    }


def handle_zh_engines(handler, path, body):
    """W8: engine toggle health for Investigate/Doctor shells (shell-first)."""
    try:
        prefs = {"default_cli": _aset.get_default_cli()}
    except Exception:
        prefs = {}
    toggle = _w8_engine_toggle(prefs=prefs)
    handler._send_json({
        "ok": True,
        **toggle,
        "p5Plumbing": _W8_P5_PLUMBING,
        "doctorShell": {
            "shellFirst": True,
            "autoStartSession": False,
            "oneClickDiagnose": True,
            "sessionStartOnDemand": True,
        },
    })


# ── W9 / SC7 — clickable health + reaper-health banners → Doctor seed ──────
# Banner click opens Doctor with 1:1 fields (issueId, exact message, component,
# lastError, suggestedChecks). Async diagnose start attempted when engine
# enabled; failure surfaces health and leaves UI usable. Never a markdown path.

_W9_BANNER_SEED_FIELDS = (
    "issueId", "message", "component", "lastError", "suggestedChecks",
)
_W9_BANNER_DOCTOR_SEED_VERSION = "w9-banner-doctor-seed-v1"

# Closed Doctor issue defaults aligned with zombie-hunter reason-catalog.js (W9).
_W9_DOCTOR_ISSUE_DEFAULTS = {
    "ZH_HEALTH_CHECK_ISSUES": {
        "component": "health-check",
        "message": (
            "Dashboard health check found issues — diagnose in Doctor "
            "(not a markdown path)"
        ),
        "suggestedChecks": [
            "Open Doctor from the health banner (seeded issue context)",
            "Inspect latest health_reports entry via Doctor, not a static file link alone",
            "Re-run diagnostics if status is stale",
        ],
    },
    "ZH_REAPER_ABSTAIN_STREAK": {
        "component": "reaper-health",
        "message": (
            "Reaper consecutive-abstain streak — liveness inputs may be "
            "broken; reaper flying blind"
        ),
        "suggestedChecks": [
            "Run reaper explain (read-only) and inspect live_owner_ids",
            "Check liveness snapshot degraded flag and owner enumeration inputs",
            "Confirm reaper is unarmed/disarmed until inputs recover",
        ],
    },
    "ZH_REAPER_CHAIN_TAMPERED": {
        "component": "reaper-health",
        "message": (
            "Reaper owner-evidence receipt chain failed verification — "
            "audit log may be tampered"
        ),
        "suggestedChecks": [
            "Verify receipt chain hashes under .anchor/",
            "Do not arm or advance reaper tier until chain verifies",
            "Inspect last owner-evidence receipt entries",
        ],
    },
    "ZH_SWEEP_ERROR": {
        "component": "sweep",
        "message": "Sweep parse or worker error — abstain, never invent RED",
        "suggestedChecks": [
            "Read sweepError field",
            "Re-run scan; check control-char safety of process JSON",
        ],
    },
}


def _w9_normalize_banner_issue(raw, banner_surface=None):
    """Normalize banner/issue payload to 1:1 Doctor seed fields (SC7)."""
    if not raw or not isinstance(raw, dict):
        return None
    issue_id = raw.get("issueId") or raw.get("id")
    issue_id = str(issue_id) if issue_id else None
    catalog = _W9_DOCTOR_ISSUE_DEFAULTS.get(issue_id or "", {})
    message = _w8_clip(
        raw.get("message") or raw.get("exactMessage") or catalog.get("message") or "",
        400,
    )
    component = _w8_clip(
        raw.get("component") or catalog.get("component") or "",
        120,
    )
    last_error = _w8_clip(raw.get("lastError") or raw.get("error") or "", 400)
    checks = raw.get("suggestedChecks")
    if not isinstance(checks, list):
        checks = list(catalog.get("suggestedChecks") or [])
    checks = [_w8_clip(c, 160) for c in checks[:8] if c]
    surface = raw.get("bannerSurface") or banner_surface
    return {
        "issueId": issue_id,
        "message": message,
        "exactMessage": message,
        "component": component,
        "lastError": last_error,
        "suggestedChecks": checks,
        "bannerSurface": surface,
        "markdownPath": None,
        "isMarkdownPath": False,
        "version": _W9_BANNER_DOCTOR_SEED_VERSION,
        "catalogAligned": bool(issue_id and issue_id in _W9_DOCTOR_ISSUE_DEFAULTS),
    }


def _w9_build_dashboard_health_banner_issue(report_date="", status="ISSUES FOUND",
                                           last_error=None, message=None):
    """Dashboard health-check banner issue (replaces static health_reports path)."""
    report_date = str(report_date or "")
    status = str(status or "ISSUES FOUND")
    msg = message or (
        f"Health check found issues"
        f"{(' on ' + report_date) if report_date else ''} ({status})"
    )
    return _w9_normalize_banner_issue({
        "issueId": "ZH_HEALTH_CHECK_ISSUES",
        "message": msg,
        "component": "health-check",
        "lastError": last_error if last_error is not None else status,
        "bannerSurface": "dashboard_health",
    }, banner_surface="dashboard_health")


def _w9_build_reaper_health_banner_issue(banner=None):
    """Reaper-health banner issue from reaper_arming.health_banner() dict."""
    banner = banner or {}
    kind = str(banner.get("kind") or "abstain-streak")
    issue_id = (
        "ZH_REAPER_CHAIN_TAMPERED" if kind == "chain-tampered"
        else "ZH_REAPER_ABSTAIN_STREAK"
    )
    msg = banner.get("message") or (
        "Reaper receipt chain failed verification."
        if kind == "chain-tampered"
        else (
            f"Reaper has ABSTAINED for {banner.get('streak', '?')} consecutive "
            f"sweeps — flying blind."
        )
    )
    last_error = banner.get("lastError") or (
        "chain_verification_failed" if kind == "chain-tampered"
        else (
            f"abstain_streak={banner.get('streak', '?')};"
            f"threshold={banner.get('threshold', '?')}"
        )
    )
    return _w9_normalize_banner_issue({
        "issueId": issue_id,
        "message": msg,
        "component": "reaper-health",
        "lastError": last_error,
        "bannerSurface": "reaper_health",
    }, banner_surface="reaper_health")


def _w9_extract_banner_seed_fields(issue):
    n = _w9_normalize_banner_issue(issue) or {}
    return {
        "issueId": n.get("issueId"),
        "message": n.get("message") or "",
        "component": n.get("component") or "",
        "lastError": n.get("lastError") or "",
        "suggestedChecks": list(n.get("suggestedChecks") or []),
    }


def _w9_assert_banner_seed_one_to_one(banner_issue, doctor_seed):
    """True iff Doctor short seed matches banner 1:1 on SC7 fields."""
    b = _w9_extract_banner_seed_fields(banner_issue)
    seed = doctor_seed or {}
    mismatches = []
    if str(seed.get("issueId") or "") != str(b.get("issueId") or ""):
        mismatches.append("issueId")
    if str(seed.get("message") or "") != str(b.get("message") or ""):
        mismatches.append("message")
    if str(seed.get("component") or "") != str(b.get("component") or ""):
        mismatches.append("component")
    if str(seed.get("lastError") or "") != str(b.get("lastError") or ""):
        mismatches.append("lastError")
    seed_checks = [str(c) for c in (seed.get("suggestedChecks") or [])]
    b_checks = [str(c) for c in (b.get("suggestedChecks") or [])]
    if seed_checks != b_checks:
        mismatches.append("suggestedChecks")
    if seed.get("markdownPath") or seed.get("isMarkdownPath") is True:
        mismatches.append("markdownPath_present")
    return {"ok": len(mismatches) == 0, "mismatches": mismatches,
            "fields": list(_W9_BANNER_SEED_FIELDS)}


def _w9_build_doctor_navigation_from_banner(issue, token=None, auto_diagnose=True):
    """Doctor href with 1:1 query seed — never health_reports/*.md."""
    n = _w9_normalize_banner_issue(issue)
    if not n:
        return {
            "ok": False, "href": "/doctor", "path": "/doctor",
            "isMarkdownPath": False, "markdownPath": None,
            "autoDiagnose": False, "issue": None, "error": "no_issue",
        }
    from urllib.parse import urlencode
    q = {
        "issueId": n.get("issueId") or "",
        "message": n.get("message") or "",
        "component": n.get("component") or "",
        "lastError": n.get("lastError") or "",
        "suggestedChecks": "|".join(n.get("suggestedChecks") or []),
    }
    if auto_diagnose:
        q["diagnose"] = "1"
    if token:
        q["token"] = str(token)
    # Drop empties for cleaner URLs
    q = {k: v for k, v in q.items() if v not in (None, "")}
    href = "/doctor?" + urlencode(q)
    return {
        "ok": True,
        "href": href,
        "path": "/doctor",
        "isMarkdownPath": False,
        "markdownPath": None,
        "autoDiagnose": bool(auto_diagnose),
        "query": q,
        "issue": _w9_extract_banner_seed_fields(n),
        "bannerSurface": n.get("bannerSurface"),
        "version": _W9_BANNER_DOCTOR_SEED_VERSION,
    }


def _w9_build_banner_diagnose_plan(issue, engine=None, profile=None):
    """Session-start plan for banner→Doctor with 1:1 seed + async diagnose markers."""
    n = _w9_normalize_banner_issue(issue)
    plan = _w8_shared_session_start_plan(
        surface="doctor", engine=engine, issue=n)
    seed = plan.get("seed") or _w8_build_doctor_short_seed(n)
    if n:
        seed = dict(seed)
        seed["exactMessage"] = n.get("exactMessage") or seed.get("message")
        seed["markdownPath"] = None
        seed["isMarkdownPath"] = False
        seed["bannerSurface"] = n.get("bannerSurface")
        seed["bannerDoctorVersion"] = _W9_BANNER_DOCTOR_SEED_VERSION
        plan["seed"] = seed
        plan["seedText"] = _w8_format_doctor_short_seed_text(seed)
    plan["bannerIssue"] = _w9_extract_banner_seed_fields(n)
    plan["bannerOneToOne"] = _w9_assert_banner_seed_one_to_one(n, plan.get("seed"))
    plan["navigation"] = _w9_build_doctor_navigation_from_banner(n, auto_diagnose=True)
    plan["p6BannerDoctor"] = {
        "id": "p6-health-banner-doctor-seed",
        "version": _W9_BANNER_DOCTOR_SEED_VERSION,
        "notMarkdownPath": True,
        "fields": list(_W9_BANNER_SEED_FIELDS),
    }
    if plan.get("canStart"):
        plan["session"] = dict(plan.get("session") or {})
        plan["session"]["attemptAsyncDiagnose"] = True
        plan["session"]["startWhen"] = "banner_click_diagnose"
        plan["session"]["failureNonBlocking"] = True
        plan["session"]["async"] = True
    return plan


def _w9_attempt_async_banner_diagnose_start(issue, engine=None, force_fail=False,
                                           fail_reason=None, profile=None):
    """Contract for async diagnose attempt; failure leaves UI usable."""
    plan = _w9_build_banner_diagnose_plan(issue, engine=engine, profile=profile)
    if force_fail or not plan.get("canStart"):
        reason = (
            fail_reason if force_fail
            else (plan.get("error") or "no healthy engine")
        )
        return {
            "ok": False,
            "attempted": bool(force_fail),
            "async": True,
            "failureNonBlocking": True,
            "uiUsable": True,
            "health": {
                "status": "start_failed" if force_fail else "engine_disabled",
                "message": str(reason),
                "engine": plan.get("engine") or engine,
            },
            "plan": plan,
            "session": None,
            "seed": plan.get("seed"),
            "seedOneToOne": plan.get("bannerOneToOne"),
            "error": reason,
        }
    return {
        "ok": True,
        "attempted": True,
        "async": True,
        "failureNonBlocking": True,
        "uiUsable": True,
        "health": {
            "status": "healthy",
            "message": "async diagnose start attempted with banner seed",
            "engine": plan.get("engine"),
        },
        "plan": plan,
        "session": {
            "status": "starting",
            "async": True,
            "cancelable": True,
            "engine": plan.get("engine"),
            "issueId": (plan.get("bannerIssue") or {}).get("issueId"),
        },
        "seed": plan.get("seed"),
        "seedOneToOne": plan.get("bannerOneToOne"),
        "error": None,
    }


def _w9_render_clickable_banner_html(issue, title, body, style_kind="health"):
    """Render a clickable health/reaper banner that opens Doctor with 1:1 seed."""
    n = _w9_normalize_banner_issue(issue) or {}
    nav = _w9_build_doctor_navigation_from_banner(n, auto_diagnose=True)
    href = nav.get("href") or "/doctor?diagnose=1"
    # JS open with token: base href + optional token from _anchorToken()
    if style_kind == "reaper":
        bg, border, color, strong = "#3b2a1f", "#9b6a3a", "#ffd9b3", "#ffb37a"
    else:
        bg, border, color, strong = "#3b1f1f", "#9b3a3a", "#ffb3b3", "#ff7a7a"
    # Escape attribute values
    def _attr(s):
        return html_lib.escape(str(s or ""), quote=True)

    issue_id = _attr(n.get("issueId") or "")
    message = _attr(n.get("message") or "")
    component = _attr(n.get("component") or "")
    last_error = _attr(n.get("lastError") or "")
    checks = _attr("|".join(n.get("suggestedChecks") or []))
    surface = _attr(n.get("bannerSurface") or "")
    href_js = href.replace("\\", "\\\\").replace("'", "\\'")
    return (
        f'<div role="button" tabindex="0" class="zh-health-banner-doctor" '
        f'data-issue-id="{issue_id}" data-message="{message}" '
        f'data-component="{component}" data-last-error="{last_error}" '
        f'data-suggested-checks="{checks}" data-banner-surface="{surface}" '
        f'data-diagnose="1" data-not-markdown-path="1" '
        f'onclick="(function(){{var h=\'{href_js}\';'
        f'try{{var t=(typeof _anchorToken===\'function\')?(_anchorToken()||\'\'):\'\';'
        f'if(t)h+=(h.indexOf(\'?\')>=0?\'&amp;\':\'?\')+\'token=\'+encodeURIComponent(t);'
        f'}}catch(e){{}}window.open(h,\'_blank\');}})()" '
        f'style="background:{bg};border:1px solid {border};color:{color};'
        f'padding:10px 14px;border-radius:6px;margin:0 0 10px 0;font-size:13px;'
        f'cursor:pointer;" title="Open Doctor with seeded diagnose context (W9/SC7)">'
        f'<strong style="color:{strong}">&#9888; {_attr(title)}</strong> {body}'
        f'</div>'
    )


def handle_doctor_banner_seed(handler, path, body):
    """GET/POST helper surface for W9 banner→Doctor seed (tests + clients)."""
    # Parse query from handler path when GET
    qs = {}
    try:
        qs = {k: (v[0] if v else "") for k, v in parse_qs(
            urlparse(path).query).items()}
    except Exception:
        qs = {}
    body = body or {}
    surface = (body.get("surface") or qs.get("surface") or "dashboard_health").lower()
    if surface in ("reaper_health", "reaper"):
        issue = _w9_build_reaper_health_banner_issue({
            "kind": body.get("kind") or qs.get("kind") or "abstain-streak",
            "message": body.get("message") or qs.get("message"),
            "streak": body.get("streak") or qs.get("streak"),
            "threshold": body.get("threshold") or qs.get("threshold"),
            "lastError": body.get("lastError") or qs.get("lastError"),
        })
    else:
        issue = _w9_build_dashboard_health_banner_issue(
            report_date=body.get("reportDate") or qs.get("reportDate") or "",
            status=body.get("status") or qs.get("status") or "ISSUES FOUND",
            last_error=body.get("lastError") or qs.get("lastError"),
            message=body.get("message") or qs.get("message"),
        )
    plan = _w9_build_banner_diagnose_plan(
        issue, engine=body.get("engine") or qs.get("engine"))
    attempt = _w9_attempt_async_banner_diagnose_start(
        issue,
        engine=body.get("engine") or qs.get("engine"),
        force_fail=bool(body.get("forceFail") or qs.get("forceFail") == "1"),
        fail_reason=body.get("failReason"),
    )
    handler._send_json({
        "ok": True,
        "surface": surface,
        "issue": _w9_extract_banner_seed_fields(issue),
        "seed": plan.get("seed"),
        "seedText": plan.get("seedText"),
        "oneToOne": plan.get("bannerOneToOne"),
        "navigation": plan.get("navigation"),
        "diagnosePlan": plan,
        "asyncDiagnoseAttempt": attempt,
        "bannerDoctorVersion": _W9_BANNER_DOCTOR_SEED_VERSION,
        "notMarkdownPath": True,
        "markdownPath": None,
        "p5Plumbing": _W8_P5_PLUMBING,
    })



def handle_zombie_terminal_start(handler, path, body):
    import zombie_hunter
    import reaper
    import pty_manager

    body = body or {}
    # W8: prefer slim seed + three-engine health gate (shared start helper).
    want_slim = body.get("slim") is not False  # default slim (SC5)
    want_deep = bool(body.get("deepBrief") or body.get("deep_brief"))
    candidate = body.get("candidate") if isinstance(body.get("candidate"), dict) else {}
    if body.get("pid") is not None and "pid" not in candidate:
        candidate = dict(candidate)
        candidate["pid"] = body.get("pid")
    if body.get("reasonCodes") and "reasonCodes" not in candidate:
        candidate = dict(candidate)
        candidate["reasonCodes"] = body.get("reasonCodes")

    plan = _w8_shared_session_start_plan(
        surface="investigate",
        engine=body.get("backend") or body.get("engine"),
        candidate=candidate,
        deep_brief=want_deep,
        slim=want_slim,
    )
    backend = plan.get("engine")
    if not backend:
        # Failure is non-blocking for the shell — honest JSON, no crash.
        handler._send_json({
            "ok": False,
            "error": plan.get("error") or "no healthy engine",
            "engineDenied": plan.get("engineDenied"),
            "engineToggle": plan.get("engineToggle"),
            "shell": plan.get("shell"),
            "failureNonBlocking": True,
            "p5Plumbing": _W8_P5_PLUMBING,
        }, 200)
        return

    # Deep-brief or slim: use the shared seed. Optional legacy full briefing when
    # caller explicitly sets slim=false (pre-W8 path).
    if want_slim or want_deep:
        briefing = plan["seedText"]
        # Optional: append a short live scan tip without multi-minute assembly.
        try:
            import urllib.request
            with urllib.request.urlopen('http://127.0.0.1:48484/api/state', timeout=1.5) as r:
                st = json.loads(r.read().decode('utf-8'))
            tot = (st.get("ledger", {}) or {}).get("totals", {}) or {}
            briefing += (
                "\n\n## Live scan tip (non-blocking)\n"
                "- Burn $/min: %.2f · observe zombies: %s · mode: %s\n"
                % (
                    float(tot.get("usdPerMin") or 0),
                    sum(g.get("count", 0) for g in (st.get("zombies") or [])),
                    st.get("classifierMode") or "shadow",
                )
            )
        except Exception:
            pass
    else:
        # Legacy full briefing path (explicit slim=false only).
        try:
            attached = set(pty_manager.live_sessions())
        except Exception:
            attached = set()

        report_path = zombie_hunter._last_report_path()
        report_data = None
        if report_path.exists():
            try:
                report_data = json.loads(report_path.read_text("utf-8"))
            except Exception:
                pass

        if not report_data:
            try:
                report_data = zombie_hunter.sweep(
                    live_session_ids=list(attached), apply=False)
            except Exception:
                report_data = {}

        running_records = []
        try:
            running_records = _sessreg.list_sessions(status="running")
        except Exception:
            pass

        try:
            _snap = reaper.build_snapshot(
                attached_pty_ids=attached, records=running_records,
                enumerate_pids=reaper.enumerate_live_pids)
        except Exception:
            _snap = None

        session_briefs = []
        orphaned_ids = []
        for rec in running_records:
            sid = rec.get("session_id", "")
            lane_name = rec.get("lane", "")
            pid = rec.get("pid")
            rec_backend = rec.get("backend", "")
            proj_id = rec.get("project_id", "")
            owner = "(unowned)"
            if proj_id:
                proj = _rnd.get_project(proj_id)
                if proj and proj.get("name"):
                    owner = proj["name"]
                else:
                    owner = proj_id
            try:
                classification = reaper.classify_record(rec, _snap)
            except Exception:
                classification = reaper.VERDICT_ABSTAIN
            if classification == "kill":
                orphaned_ids.append(sid)
                cls_str = "ORPHANED (Pending Kill)"
            elif classification == "alive":
                cls_str = "ALIVE (Attached)"
            else:
                cls_str = classification.upper()
            session_briefs.append(
                "- Session ID: %s\n  Lane: %s\n  PID: %s\n  Backend: %s\n  "
                "Owner Project: %s\n  Classification: %s"
                % (sid, lane_name, pid, rec_backend, owner, cls_str)
            )

        briefing = "# ZOMBIE-HUNTER LIVE BRIEFING\n\n"
        briefing += "You are the user's zombie-hunting assistant inside Anchor.\n"
        briefing += (
            "Your role is to help the user investigate the current "
            "swarm/owner/orphan state of the terminal sessions, "
            "and when the user confirms, cancel (kill) orphaned sessions.\n\n"
        )
        if orphaned_ids:
            briefing += "## Orphaned Sessions (Pending Kill)\n"
            for oid in orphaned_ids:
                briefing += "- `%s`\n" % oid
            briefing += "\n"
        else:
            briefing += "No orphaned sessions detected.\n\n"
        briefing += "## Sweep Report Summary\n"
        if report_data:
            briefing += "- Killed count (orphaned): %s\n" % len(report_data.get("killed", []))
            briefing += "- Alive count (attached): %s\n" % len(report_data.get("alive", []))
        else:
            briefing += "No sweep report data available.\n"
        briefing += "\n## Running Sessions Details\n"
        briefing += "\n".join(session_briefs) if session_briefs else "No running sessions."
        try:
            briefing += _zombie_scan_and_skill_briefing()
        except Exception:
            pass

    try:
        rec = _termsess.start_session(
            project_id="__dashboard__",
            lane="zombie",
            backend=backend,
            label="zombie-hunter",
            seed_context=briefing,
        )
    except _termsess.TerminalSessionError as exc:
        # Failure non-blocking for the shell UI.
        handler._send_json({
            "ok": False,
            "error": str(exc),
            "failureNonBlocking": True,
            "engine": backend,
            "shell": plan.get("shell"),
        }, 400)
    else:
        handler._send_json({
            "ok": True,
            "session_id": rec.get("session_id"),
            "backend": rec.get("backend"),
            "slim": want_slim,
            "deepBrief": want_deep,
            "seedKind": (plan.get("seed") or {}).get("kind"),
            "engineToggle": plan.get("engineToggle"),
            "session": {
                "async": True,
                "cancelable": True,
                "failureNonBlocking": True,
                "firstPromptBudgetMs": _W8_FIRST_PROMPT_BUDGET_MS,
            },
            "p5Plumbing": _W8_P5_PLUMBING,
        })


#: Cap on how much of the latest health report rides in the doctor seed —
#: enough for the whole summary + failures section of a normal report without
#: flooding the opening turn.
_DOCTOR_SEED_REPORT_CAP = 6000


def _build_doctor_seed():
    """Compose the ONE-TIME doctor-session briefing (doctor V3 Wave 2).

    Content (plan §W2): the latest ``health_reports/*.md`` (graceful "no
    reports yet" when absent), fresh ``doctor.run_doctor()`` output, the
    CORRECTNESS-vs-PERFORMANCE severity rule, and a capability list. ASCII-safe
    (encoded with replacement so no non-ASCII byte ever reaches the PTY seed).
    Every section is individually guarded — a failure degrades to an honest
    note, never a fabricated value and never a crash.
    """
    import contextlib
    import io as _io
    lines = [
        "ANCHOR DOCTOR - LIVE DIAGNOSTIC BRIEFING",
        "You are the Anchor Doctor: an HONEST, READ-ONLY diagnostic assistant "
        "for this Anchor installation. This terminal runs in plan permission "
        "mode - you may inspect anything, you can mutate nothing. Never invent "
        "a number: every figure you state must come from a file you actually "
        "read or a command you actually ran; say 'unknown' otherwise.",
    ]

    # 1) The latest health report (graceful when absent/corrupt).
    try:
        reports = sorted(_paths.health_reports_dir().glob("*.md"),
                         reverse=True)
    except Exception:
        reports = []
    if reports:
        latest = reports[0]
        try:
            body = latest.read_text(encoding="utf-8", errors="replace")
        except Exception as exc:
            body = "(report unreadable: %s)" % exc
        lines.append("## Latest health report (%s of %d on disk)"
                     % (latest.name, len(reports)))
        lines.append(body[:_DOCTOR_SEED_REPORT_CAP])
    else:
        lines.append("## Latest health report")
        lines.append("No health reports yet - the daily 5 AM health check has "
                     "not produced one on this install.")

    # 2) Fresh doctor.py system-check output (stdout captured; honest on fail).
    try:
        import doctor as _doctor
        buf = _io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = _doctor.run_doctor()
        lines.append("## Fresh doctor.py system check (exit %s)" % rc)
        lines.append(buf.getvalue().strip() or "(no output)")
    except Exception as exc:
        lines.append("## Fresh doctor.py system check")
        lines.append("doctor.run_doctor() failed: %s" % exc)

    # 3) The severity rule (locked 2026-07-07) — so the agent explains a red
    #    banner vs a yellow warning correctly.
    lines.append("## Severity rule (locked 2026-07-07)")
    lines.append(
        "Every health check is either CORRECTNESS or PERFORMANCE - never "
        "conflate them. A CORRECTNESS failure (broken endpoint, journal "
        "corruption/loss, auth violation, bad page content) sets ISSUES FOUND "
        "and turns the dashboard banner RED. A PERFORMANCE/timing measurement "
        "(render latency, journal overhead %) is load-sensitive and flaps, so "
        "it is a NON-BLOCKING YELLOW warning that never reddens the banner. "
        "Never present a timing warning as a correctness failure.")

    # 4) Capability list.
    lines.append("## What you can do in this session")
    lines.append(
        "- Read health_reports/*.md and explain any failure or warning "
        "honestly (red = correctness, yellow = performance).\n"
        "- Inspect the Anchor folder (code, logs/, .anchor/ state) to "
        "diagnose issues; cross-reference the doctor.py output above.\n"
        "- Suggest fixes as commands FOR THE USER to run - this session is "
        "read-only and must not (and cannot) apply them itself.\n"
        "- Say plainly when something is healthy; never invent a problem.")

    text = "\n\n".join(lines)
    return text.encode("ascii", "replace").decode("ascii")


def handle_doctor_session_start(handler, path, body):
    # Doctor V3 Wave 2 + W8/SC6 multi-engine — start (or attach to) THE doctor
    # agentic session. Token-authed by middleware BEFORE this handler runs.
    # When the UI picker sends backend=claude|gemini|grok, resolve via the
    # shared three-engine start helper (dead toggle forbidden). When no
    # backend is provided (legacy API callers / V3 tests), keep honest
    # select_engine_plan (claude/agy job-layer) so unavailable stays honest.
    # Page itself must NOT auto-call this on load (shell-first / one-click
    # diagnose).
    body = body or {}
    short_only = bool(body.get("short") or body.get("shortSeed"))
    issue = body.get("issue") if isinstance(body.get("issue"), dict) else None
    requested = _w8_normalize_engine(body.get("backend") or body.get("engine"))
    start_plan = _w8_shared_session_start_plan(
        surface="doctor",
        engine=requested,
        issue=issue,
    )
    engine_meta = {
        "driver": None,
        "swarm": None,
        "swarm_ratio": None,
        "reason": "",
    }
    if requested:
        backend = start_plan.get("engine")
        engine_meta["driver"] = backend
        engine_meta["reason"] = "interactive doctor picker (W8/SC6)"
        if not backend:
            handler._send_json({
                "ok": False,
                "status": _lanes.ENGINE_STATUS_UNAVAILABLE,
                "reason": start_plan.get("error") or "no healthy engine",
                "session": None,
                "engineDenied": start_plan.get("engineDenied"),
                "engineToggle": start_plan.get("engineToggle"),
                "shell": start_plan.get("shell"),
                "failureNonBlocking": True,
                "p5Plumbing": _W8_P5_PLUMBING,
            })
            return
    else:
        # Legacy / no-picker path: claude|gemini job-layer honesty (V3 tests).
        profile = _lanes.detect_host_profile()
        plan = _lanes.select_engine_plan("general", profile=profile)
        if plan.get("status") != _lanes.ENGINE_STATUS_OK or not plan.get("driver"):
            handler._send_json({
                "ok": False,
                "status": plan.get("status") or _lanes.ENGINE_STATUS_UNAVAILABLE,
                "reason": plan.get("reason", ""),
                "session": None,
                "engineToggle": start_plan.get("engineToggle"),
                "shell": start_plan.get("shell"),
                "failureNonBlocking": True,
                "p5Plumbing": _W8_P5_PLUMBING,
            })
            return
        backend = plan["driver"]
        engine_meta = {
            "driver": plan.get("driver"),
            "swarm": plan.get("swarm"),
            "swarm_ratio": plan.get("swarm_ratio"),
            "reason": plan.get("reason", ""),
        }
    try:
        if short_only or issue:
            seed = start_plan.get("seedText") or _w8_format_doctor_short_seed_text(
                start_plan.get("seed"))
        else:
            seed = _build_doctor_seed()
    except Exception as exc:
        # The briefing must never block the session — degrade honestly.
        seed = ("ANCHOR DOCTOR - LIVE DIAGNOSTIC BRIEFING\n\n"
                "(briefing assembly failed: %s)" % exc)
    try:
        rec, attached = _termsess.start_doctor_session(
            seed_context=seed, backend=backend)
    except _termsess.TerminalSessionError as exc:
        handler._send_json({
            "ok": False,
            "error": str(exc),
            "failureNonBlocking": True,
            "engine": backend,
            "shell": start_plan.get("shell"),
        }, 400)
        return
    # SAFE projection (consistent with term_sessions): NEVER worktree_path /
    # branch / seed text — the UI needs only the id + engine + status.
    handler._send_json({
        "ok": True,
        "status": _lanes.ENGINE_STATUS_OK,
        "attached": bool(attached),
        "session": {
            "session_id": rec.get("session_id"),
            "project_id": rec.get("project_id", ""),
            "lane": rec.get("lane", ""),
            "backend": rec.get("backend", ""),
            "status": rec.get("status", ""),
            "label": rec.get("label", ""),
            "created_at": rec.get("created_at"),
        },
        "engine": engine_meta,
        "engineToggle": start_plan.get("engineToggle"),
        "sessionStart": {
            "async": True,
            "cancelable": True,
            "failureNonBlocking": True,
            "autoStart": False,
            "firstPromptBudgetMs": _W8_FIRST_PROMPT_BUDGET_MS,
        },
        "p5Plumbing": _W8_P5_PLUMBING,
    })


# ── Doctor V3 Wave 3 — the /doctor page + background diagnostics ────────────
# Every number the page shows is REAL or ABSENT (plan North Star): status /
# last-run / count come from health_reports/*.md on disk; the reports list rows
# are the actual files; the terminal attaches to the Wave-2 agentic session.
# Nothing fabricated — no disk-usage card, no fake chart, no placeholder nav.

_DOCTOR_STATUS_TEXT = {
    "red": "Issues found",
    "yellow": "Warnings",
    "green": "Healthy",
    "unknown": "Unreadable report",
    "none": "No reports yet",
}

_DOCTOR_STATUS_DETAIL = {
    "red": "The latest report flags correctness issues (red banner).",
    "yellow": ("All correctness checks passed; non-blocking performance "
               "warnings present."),
    "green": "All checks passed in the latest report.",
    "unknown": "The latest report file could not be parsed.",
    "none": "Run diagnostics now, or wait for the daily 5 AM health check.",
}


def _doctor_report_status(body):
    """Classify ONE health-report body per the locked severity rule.

    red    = a CORRECTNESS failure ("Status: ISSUES FOUND");
    yellow = correctness clean but the non-blocking Warnings section has
             content (PERFORMANCE/timing notes never redden the banner);
    green  = "Status: OK" with an empty Warnings section;
    unknown= no recognizable status line (corrupt/foreign file) — honest,
             never guessed.
    """
    if "Status: ISSUES FOUND" in body:
        return "red"
    warn_match = re.search(r"^## Warnings[^\n]*\n+(.*?)(?=^## |\Z)",
                           body, re.S | re.M)
    if warn_match:
        content = warn_match.group(1).strip()
        if content and content != "(none)":
            return "yellow"
    if re.search(r"^Status: OK\s*$", body, re.M):
        return "green"
    return "unknown"


def _doctor_stats():
    """REAL /doctor stats — every value from ``health_reports/`` or absent.

    Total over an empty/corrupt reports dir: an unreadable file classifies
    ``unknown``, an empty dir yields the honest ``none`` state; never raises.
    """
    try:
        rd = _paths.health_reports_dir()
        files = sorted((p for p in rd.glob("*.md") if p.is_file()),
                       key=lambda p: p.name, reverse=True)
    except OSError:
        files = []
    reports = []
    for p in files[:10]:
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
            st = _doctor_report_status(body)
        except OSError:
            st = "unknown"
        reports.append({"name": p.name, "date": p.stem, "status": st})
    status = reports[0]["status"] if reports else "none"
    last_run = reports[0]["date"] if reports else None
    days_ago = None
    if last_run:
        try:
            days_ago = (date.today()
                        - datetime.strptime(last_run, "%Y-%m-%d").date()).days
        except ValueError:
            days_ago = None  # non-date filename — honest absence, no guess
    return {
        "status": status,
        "status_text": _DOCTOR_STATUS_TEXT.get(status, status),
        "status_detail": _DOCTOR_STATUS_DETAIL.get(status, ""),
        "last_run": last_run,
        "days_ago": days_ago,
        "report_count": len(files),
        "reports": reports,
    }


def handle_doctor_status(handler, path, body):
    # Read-only JSON stats for the /doctor card + reports-list refresh after a
    # diagnostics run. Token-authed by the route row (?token= / header /
    # cookie). Never spawns / never blocks. W8: includes engine toggle so the
    # shell can paint pickers without starting a session.
    try:
        prefs = {"default_cli": _aset.get_default_cli()}
    except Exception:
        prefs = {}
    toggle = _w8_engine_toggle(prefs=prefs)
    handler._send_json({
        "ok": True,
        **_doctor_stats(),
        "engines": toggle["engines"],
        "defaultEngine": toggle["defaultEngine"],
        "shellFirst": True,
        "autoStartSession": False,
        "oneClickDiagnose": True,
        "p5Plumbing": _W8_P5_PLUMBING,
    })


_DOCTOR_REPORT_NAME_RE = re.compile(r"^[A-Za-z0-9._-]+\.md$")


def handle_doctor_report(handler, path, body):
    # Read-only render of ONE health report. Traversal-safe: the name must be
    # a bare *.md filename (no separators — ".." can't survive the regex) AND
    # the resolved path must stay inside health_reports/.
    q = parse_qs(urlparse(handler.path).query)
    name = (q.get("name", [""])[0] or "").strip()
    if not name or not _DOCTOR_REPORT_NAME_RE.match(name) or ".." in name:
        handler._send_json({"ok": False, "error": "bad report name"}, 400)
        return
    rd = _paths.health_reports_dir()
    try:
        target = (rd / name).resolve()
        if target.parent != rd.resolve():
            handler._send_json({"ok": False, "error": "bad report name"}, 400)
            return
        text = target.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        handler._send_json({"ok": False, "error": "unknown report"}, 404)
        return
    except OSError as exc:
        handler._send_json({"ok": False, "error": str(exc)}, 500)
        return
    handler._send_html(_rv.reader_html(text, title=name))


# One background anchor_healthcheck.py run at a time (idempotent: a second
# POST while one is live attaches to it). The output tails from a log file by
# BYTE offset — the cursor-stable /api/rnd/tail pattern — so the page streams
# it live and a re-fetch from an old offset is stable, never interleaved.
_DOCTOR_HC_LOCK = threading.Lock()
_DOCTOR_HC = {"proc": None, "log": None, "started_at": None}


def _doctor_hc_log_path():
    return _paths.logs_dir() / "doctor-healthcheck-run.log"


def _doctor_hc_cmd():
    """The background diagnostics argv. ``ANCHOR_HEALTHCHECK_CMD`` is the
    test/deploy seam (same idiom as ANCHOR_RUNNER_CMD — the gate never runs
    the real 75s healthcheck); default = this install's anchor_healthcheck.py
    under the current interpreter."""
    raw = (os.environ.get("ANCHOR_HEALTHCHECK_CMD", "") or "").strip()
    if raw:
        import shlex
        return shlex.split(raw, posix=(os.name != "nt"))
    return [sys.executable, str(ANCHOR_DIR / "anchor_healthcheck.py")]


def handle_doctor_healthcheck_run(handler, path, body):
    # Doctor V3 W3 — launch anchor_healthcheck.py as a BACKGROUND process
    # (never the V2 75s synchronous request-thread block). Token-authed by the
    # do_POST default-deny middleware BEFORE this runs. Idempotent while live.
    import subprocess
    with _DOCTOR_HC_LOCK:
        proc = _DOCTOR_HC.get("proc")
        if proc is not None and proc.poll() is None:
            handler._send_json({"ok": True, "already_running": True})
            return
        log_path = _doctor_hc_log_path()
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            fh = open(log_path, "wb")
        except OSError as exc:
            handler._send_json(
                {"ok": False, "error": f"cannot open run log: {exc}"}, 500)
            return
        try:
            proc = subprocess.Popen(
                _doctor_hc_cmd(),
                stdout=fh,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                cwd=str(_paths.data_dir()),
                creationflags=_paths.NO_WINDOW,
            )
        except OSError as exc:
            fh.close()
            handler._send_json(
                {"ok": False, "error": f"failed to launch: {exc}"}, 500)
            return
        # The child holds its own inherited handle; the parent's is done.
        fh.close()
        _DOCTOR_HC["proc"] = proc
        _DOCTOR_HC["log"] = str(log_path)
        _DOCTOR_HC["started_at"] = time.time()
    handler._send_json({"ok": True, "already_running": False})


def handle_doctor_healthcheck_tail(handler, path, body):
    # Cursor-stable incremental read of the background run's log (?since=
    # BYTE offset → {text, next, running, exit_code}). Plain non-blocking
    # fetch the page polls ~1s; never holds the request thread. A missing log
    # (no run yet) is an honest empty, never a 500.
    q = parse_qs(urlparse(handler.path).query)
    try:
        since = int(q.get("since", ["0"])[0] or 0)
    except (TypeError, ValueError):
        since = 0
    with _DOCTOR_HC_LOCK:
        proc = _DOCTOR_HC.get("proc")
        log = _DOCTOR_HC.get("log") or str(_doctor_hc_log_path())
        started = _DOCTOR_HC.get("started_at")
    running = proc is not None and proc.poll() is None
    exit_code = None if (proc is None or running) else proc.returncode
    text = ""
    next_off = since
    try:
        with open(log, "rb") as f:
            f.seek(0, 2)
            total = f.tell()
            if since < 0 or since > total:
                since = 0  # truncated/new log — clamp, stay stable
            f.seek(since)
            data = f.read()
        text = data.decode("utf-8", errors="replace")
        next_off = since + len(data)
    except OSError:
        pass  # no run yet — honest empty tail
    handler._send_json({
        "ok": True,
        "text": text,
        "next": next_off,
        "running": running,
        "exit_code": exit_code,
        "started": started is not None,
    })


# The /doctor page template. A RAW string filled via .replace() — NEVER an
# f-string — so the V2 literal-{placeholder}-in-page bug class is structurally
# impossible (regression-tested in tests/test_doctor_v3.py). Styled in the
# Anchor dashboard's own idiom: same palette variables, same system font
# stack, same card/button patterns — not a standalone-product mock.
_DOCTOR_PAGE_TEMPLATE = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Anchor Doctor</title>
<link rel="icon" href="/vendor/brand/gwl-m-icon.svg" type="image/svg+xml">
<link rel="stylesheet" href="/vendor/xterm/xterm.css" />
<script src="/vendor/xterm/xterm.js"></script>
<style>
:root {
    --bg: #0f1117; --surface: #1a1d27; --surface2: #232733; --border: #2e3340;
    --text: #e2e4e9; --text-dim: #8b8f9a; --accent: #6c9cfc;
    --danger: #f87171; --warning: #fbbf24; --success: #4ade80;
    color-scheme: dark;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif; background: var(--bg); color: var(--text); line-height: 1.5; min-height: 100vh; }
.wrap { max-width: 1280px; margin: 0 auto; padding: 20px 24px 40px; }
.masthead { display: flex; align-items: center; gap: 14px; padding: 6px 0 16px; border-bottom: 1px solid var(--border); margin-bottom: 20px; }
.mh-title { font-size: 24px; font-weight: 700; letter-spacing: -0.4px; }
.mh-title .mh-anchor { color: var(--accent); }
.mh-title .mh-doctor { color: var(--success); }
.mh-sub { font-size: 12px; color: var(--text-dim); }
.mh-spacer { flex: 1; }
.backlink { color: var(--accent); text-decoration: none; font-size: 13px; }
.backlink:hover { text-decoration: underline; }
.cards { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; margin-bottom: 20px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; }
.stat-label { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-dim); margin-bottom: 8px; }
.stat-value { font-size: 22px; font-weight: 700; display: flex; align-items: center; gap: 10px; }
.stat-sub { font-size: 12px; color: var(--text-dim); margin-top: 4px; }
.dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; flex-shrink: 0; background: var(--text-dim); }
.dot.green { background: var(--success); }
.dot.yellow { background: var(--warning); }
.dot.red { background: var(--danger); }
.dot.none, .dot.unknown { background: var(--text-dim); }
.cols { display: grid; grid-template-columns: 1fr 1.4fr; gap: 16px; align-items: start; }
.panel h3 { font-size: 11px; text-transform: uppercase; letter-spacing: 1px; color: var(--text-dim); margin-bottom: 12px; }
.panel + .panel { margin-top: 16px; }
.btn { background: var(--accent); color: #fff; border: none; padding: 10px 18px; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; }
.btn:hover { filter: brightness(1.1); }
.btn:disabled { opacity: 0.6; cursor: default; }
.hint { font-size: 11.5px; color: var(--text-dim); margin-top: 8px; }
.hcout { display: none; margin-top: 12px; background: #0c0e14; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; font-family: ui-monospace, Consolas, monospace; font-size: 12px; max-height: 320px; overflow-y: auto; white-space: pre-wrap; word-break: break-word; color: var(--text); }
.report-row { display: flex; align-items: center; gap: 10px; padding: 9px 4px; border-bottom: 1px solid var(--border); text-decoration: none; color: var(--text); font-size: 13.5px; }
.report-row:last-child { border-bottom: none; }
.report-row:hover { background: var(--surface2); }
.rr-date { font-weight: 600; }
.rr-chip { margin-left: auto; font-size: 11px; padding: 2px 9px; border-radius: 999px; background: var(--surface2); color: var(--text-dim); border: 1px solid var(--border); }
.rr-chip.green { color: var(--success); border-color: rgba(74,222,128,0.4); }
.rr-chip.yellow { color: var(--warning); border-color: rgba(251,191,36,0.4); }
.rr-chip.red { color: var(--danger); border-color: rgba(248,113,113,0.4); }
.empty { color: var(--text-dim); font-size: 13px; padding: 6px 0; }
.term-panel #terminal { height: 480px; background: #0c0e14; border-radius: 8px; padding: 6px; }
.term-eng { color: var(--success); text-transform: none; letter-spacing: 0; margin-left: 8px; font-weight: 600; }
@media (max-width: 980px) { .cols { grid-template-columns: 1fr; } .cards { grid-template-columns: 1fr; } }
</style>
</head>
<body>
<div class="wrap">
  <div class="masthead">
    <div class="mh-title"><span class="mh-anchor">&#9875;</span> Anchor <span class="mh-doctor">Doctor</span></div>
    <div class="mh-sub">honest diagnostics &mdash; every number real or absent</div>
    <div class="mh-spacer"></div>
    <a class="backlink" href="/">&larr; Dashboard</a>
  </div>

  <div class="cards">
    <div class="card">
      <div class="stat-label">Overall status</div>
      <div class="stat-value"><span class="dot __STATUS_CLASS__" id="cardStatusDot"></span><span id="cardStatusText">__STATUS_TEXT__</span></div>
      <div class="stat-sub" id="cardStatusDetail">__STATUS_DETAIL__</div>
    </div>
    <div class="card">
      <div class="stat-label">Last health run</div>
      <div class="stat-value" id="cardLastRun">__LAST_RUN__</div>
      <div class="stat-sub" id="cardLastAgo">__LAST_AGO__</div>
    </div>
    <div class="card">
      <div class="stat-label">Reports on disk</div>
      <div class="stat-value" id="cardCount">__REPORT_COUNT__</div>
      <div class="stat-sub">in health_reports/</div>
    </div>
  </div>

  <div class="cols">
    <div class="col-left">
      <div class="card panel">
        <h3>Diagnostics</h3>
        <button class="btn" id="runBtn" onclick="runDiagnostics()">Run diagnostics</button>
        <div class="hint">Runs anchor_healthcheck.py in the background; output tails below live.</div>
        <pre id="hcout" class="hcout"></pre>
      </div>
      <div class="card panel">
        <h3>Recent health reports</h3>
        <div id="reportsList">__REPORTS_LIST__</div>
      </div>
    </div>
    <div class="col-right">
      <div class="card panel term-panel">
        <h3>Doctor session <span class="term-eng" id="termEngine">shell ready</span></h3>
        <div id="enginePicker" style="display:flex;gap:8px;flex-wrap:wrap;margin:0 0 10px;align-items:center">
          <span style="color:#71717a;font-size:12px">Engine:</span>
          <button type="button" class="btn eng-btn" data-eng="claude" id="engC" onclick="pickDoctorEng('claude')">Claude</button>
          <button type="button" class="btn eng-btn" data-eng="gemini" id="engG" onclick="pickDoctorEng('gemini')">Gemini</button>
          <button type="button" class="btn eng-btn" data-eng="grok" id="engK" onclick="pickDoctorEng('grok')">Grok</button>
          <button type="button" class="btn" id="diagnoseBtn" onclick="runDiagnose()">Diagnose</button>
          <span id="engHealth" style="color:#a1a1aa;font-size:11px"></span>
        </div>
        <div id="terminal"></div>
        <div class="hint">Shell-first (W8/SC6): page is usable immediately. Session starts only when you click Diagnose — no multi-minute blank wait. Engines: Claude · Gemini(agy) · Grok (grok.exe -p). Unhealthy engines disable with health.</div>
      </div>
    </div>
  </div>
</div>

<script>
(function () {
  var token = new URLSearchParams(location.search).get('token') || '';
  function tq(url) {
    if (!token) return url;
    return url + (url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(token);
  }
  function hdrs() {
    var h = { 'Content-Type': 'application/json' };
    if (token) h['X-Anchor-Token'] = token;
    return h;
  }
  function getHdrs() {
    var h = {};
    if (token) h['X-Anchor-Token'] = token;
    return h;
  }
  // Carry the token onto the server-rendered report links when configured.
  document.querySelectorAll('a.report-row').forEach(function (a) {
    if (token) a.href = tq(a.getAttribute('href'));
  });

  // ── W8/SC6 shell-first doctor terminal (NO auto session_start on load) ──
  var term = new Terminal({ convertEol: true, fontSize: 13, theme: { background: '#0c0e14' }, scrollback: 5000 });
  term.open(document.getElementById('terminal'));
  term.write('[doctor] Shell ready (≤1s). Pick Claude / Gemini / Grok, then Diagnose.\\r\\n');
  term.write('[doctor] No auto-session — page stays usable without multi-minute blank wait.\\r\\n');
  var activeWs = null;
  var sendChain = Promise.resolve();
  var sessionId = null;
  var ZH_ENG = 'claude';
  var ZH_ENG_HEALTH = { claude: true, gemini: true, grok: true };
  function paintEng() {
    ['claude','gemini','grok'].forEach(function (e) {
      var id = e === 'claude' ? 'engC' : (e === 'gemini' ? 'engG' : 'engK');
      var el = document.getElementById(id);
      if (!el) return;
      var ok = ZH_ENG_HEALTH[e] !== false;
      el.disabled = !ok;
      el.style.opacity = ok ? '1' : '0.45';
      el.style.outline = (ZH_ENG === e) ? '1px solid #6c9cfc' : 'none';
    });
    var h = document.getElementById('engHealth');
    if (h) h.textContent = ZH_ENG_HEALTH[ZH_ENG] === false ? (ZH_ENG + ' unavailable') : (ZH_ENG + ' ready');
  }
  window.pickDoctorEng = function (e) {
    if (ZH_ENG_HEALTH[e] === false) {
      term.write('[doctor] ' + e + ' disabled (unhealthy).\\r\\n');
      return;
    }
    ZH_ENG = e;
    paintEng();
  };
  function sendInput(d) {
    if (!sessionId || d === '' || d == null) return;
    if (activeWs && activeWs.readyState === 1) {
      try { activeWs.send(d); return; } catch (e) { /* fall through */ }
    }
    var body = { session: sessionId, data: d };
    if (token) body.token = token;
    sendChain = sendChain.then(function () {
      return fetch('/api/rnd/term_input2', { method: 'POST', headers: hdrs(), body: JSON.stringify(body) });
    }).catch(function () {});
  }
  term.onData(sendInput);
  var sseStarted = false;
  function startSSE() {
    if (sseStarted || !sessionId) return;
    sseStarted = true;
    var es = new EventSource(tq('/api/rnd/term_stream2?session=' + encodeURIComponent(sessionId)));
    es.addEventListener('output', function (ev) {
      try {
        var p = JSON.parse(ev.data);
        if (p.text) term.write(p.text);
      } catch (e) {}
    });
    es.addEventListener('done', function () { try { es.close(); } catch (e) {} });
  }
  function fitTerm() {
    if (!sessionId) return;
    var el = document.getElementById('terminal');
    var cols = Math.max(40, Math.floor(el.clientWidth / 8)) || 80;
    var rows = Math.max(10, Math.floor(el.clientHeight / 18)) || 24;
    try { term.resize(cols, rows); } catch (e) {}
    var body = { session: sessionId, cols: cols, rows: rows };
    if (token) body.token = token;
    fetch('/api/rnd/term_resize', { method: 'POST', headers: hdrs(), body: JSON.stringify(body) }).catch(function () {});
  }
  window.addEventListener('resize', fitTerm);
  function attach() {
    var wsProto = (location.protocol === 'https:') ? 'wss:' : 'ws:';
    var wsUrl = tq(wsProto + '//' + location.host + '/api/rnd/term_ws?session=' + encodeURIComponent(sessionId));
    try {
      var ws = new WebSocket(wsUrl);
      activeWs = ws;
      ws.onmessage = function (ev) { term.write(ev.data); };
      ws.onclose = function () { activeWs = null; if (!sseStarted) startSSE(); };
      ws.onerror = function () { activeWs = null; try { ws.close(); } catch (e) {} startSSE(); };
    } catch (e) {
      activeWs = null;
      startSSE();
    }
    setTimeout(fitTerm, 100);
  }
  // W9 / SC7 — banner→Doctor seed from URL query (1:1 fields; not a markdown path).
  var BANNER_ISSUE = null;
  var AUTO_DIAGNOSE = false;
  (function parseBannerIssueFromQuery() {
    try {
      var sp = new URLSearchParams(location.search);
      var issueId = sp.get('issueId') || sp.get('id') || '';
      var message = sp.get('message') || sp.get('exactMessage') || '';
      var component = sp.get('component') || '';
      var lastError = sp.get('lastError') || '';
      var checksRaw = sp.get('suggestedChecks') || '';
      var suggestedChecks = checksRaw ? checksRaw.split('|').filter(Boolean) : [];
      AUTO_DIAGNOSE = sp.get('diagnose') === '1' || sp.get('autoDiagnose') === '1';
      if (issueId || message || component || lastError || suggestedChecks.length) {
        BANNER_ISSUE = {
          issueId: issueId || null,
          message: message,
          exactMessage: message,
          component: component,
          lastError: lastError,
          suggestedChecks: suggestedChecks,
          markdownPath: null,
          isMarkdownPath: false
        };
        term.write('[doctor] Banner seed loaded (W9/SC7) — not a markdown path.\\r\\n');
        term.write('[doctor] issueId: ' + (BANNER_ISSUE.issueId || '(none)') + '\\r\\n');
        if (BANNER_ISSUE.message) term.write('[doctor] message: ' + BANNER_ISSUE.message + '\\r\\n');
        if (BANNER_ISSUE.component) term.write('[doctor] component: ' + BANNER_ISSUE.component + '\\r\\n');
        if (BANNER_ISSUE.lastError) term.write('[doctor] lastError: ' + BANNER_ISSUE.lastError + '\\r\\n');
        if (BANNER_ISSUE.suggestedChecks.length) {
          term.write('[doctor] suggestedChecks: ' + BANNER_ISSUE.suggestedChecks.join('; ') + '\\r\\n');
        }
      }
    } catch (e) {
      BANNER_ISSUE = null;
      AUTO_DIAGNOSE = false;
    }
  })();

  // Shell-first: load engine health ONLY (never auto session_start on plain open).
  // Banner navigation with diagnose=1 may attempt async diagnose after engines paint.
  fetch(tq('/api/doctor/status'), { headers: getHdrs() })
    .then(function (r) { return r.json(); })
    .then(function (s) {
      if (s && s.engines) {
        s.engines.forEach(function (row) { ZH_ENG_HEALTH[row.id] = !!row.enabled; });
        if (s.defaultEngine) ZH_ENG = s.defaultEngine;
      }
      paintEng();
      // W9: banner click with diagnose=1 → attempt async session start with seed.
      if (AUTO_DIAGNOSE && BANNER_ISSUE && ZH_ENG_HEALTH[ZH_ENG] !== false) {
        term.write('[doctor] Banner diagnose path: attempting async session start…\\r\\n');
        window.runDiagnose({ fromBanner: true });
      } else if (AUTO_DIAGNOSE && BANNER_ISSUE && ZH_ENG_HEALTH[ZH_ENG] === false) {
        term.write('[doctor] Banner diagnose deferred — engine ' + ZH_ENG + ' disabled with health; shell usable.\\r\\n');
      }
    })
    .catch(function () {
      paintEng();
      if (AUTO_DIAGNOSE && BANNER_ISSUE) {
        term.write('[doctor] Engine health probe failed (non-blocking); shell usable. Click Diagnose when ready.\\r\\n');
      }
    });

  window.runDiagnose = function (opts) {
    opts = opts || {};
    if (sessionId) {
      term.write('[doctor] Session already live.\\r\\n');
      return;
    }
    if (ZH_ENG_HEALTH[ZH_ENG] === false) {
      term.write('[doctor] Engine ' + ZH_ENG + ' disabled with health — pick another.\\r\\n');
      return;
    }
    var btn = document.getElementById('diagnoseBtn');
    if (btn) { btn.disabled = true; btn.textContent = 'Starting…'; }
    var startBody = { backend: ZH_ENG };
    if (token) startBody.token = token;
    // W9: seed Doctor 1:1 from banner issue payload (short diagnose seed).
    if (BANNER_ISSUE) {
      startBody.issue = BANNER_ISSUE;
      startBody.short = true;
      startBody.shortSeed = true;
    }
    fetch('/api/doctor/session_start', { method: 'POST', headers: hdrs(), body: JSON.stringify(startBody) })
      .then(function (r) { return r.json(); })
      .then(function (p) {
        if (btn) { btn.disabled = false; btn.textContent = 'Diagnose'; }
        if (p && p.ok && p.session && p.session.session_id) {
          sessionId = p.session.session_id;
          var eng = document.getElementById('termEngine');
          if (eng && p.session.backend) eng.textContent = p.session.backend + (p.attached ? ' (reattached)' : '');
          term.write('[doctor] Session started async on ' + (p.session.backend || ZH_ENG)
            + (opts.fromBanner ? ' (banner seed)' : '') + '.\\r\\n');
          attach();
        } else {
          var status = (p && p.status) || 'error';
          var reason = (p && (p.reason || p.error)) || 'unknown';
          // Failure surfaces health; UI stays usable (SC7).
          term.write('[doctor] Diagnose failed (non-blocking): ' + status + ' — ' + reason + '\\r\\n');
          term.write('[doctor] Shell remains usable; try another engine or fix CLI health.\\r\\n');
          var h = document.getElementById('engHealth');
          if (h) h.textContent = 'start failed: ' + reason;
        }
      })
      .catch(function (e) {
        if (btn) { btn.disabled = false; btn.textContent = 'Diagnose'; }
        term.write('[doctor] session start failed (non-blocking): ' + e + '\\r\\n');
        var h = document.getElementById('engHealth');
        if (h) h.textContent = 'start failed (non-blocking)';
      });
  };

  // ── Background diagnostics run + live tail ──
  var chipNames = { red: 'issues', yellow: 'warnings', green: 'healthy' };
  function setCards(s) {
    var el = document.getElementById('cardStatusDot');
    if (el) el.className = 'dot ' + (s.status || 'none');
    el = document.getElementById('cardStatusText');
    if (el) el.textContent = s.status_text || '';
    el = document.getElementById('cardStatusDetail');
    if (el) el.textContent = s.status_detail || '';
    el = document.getElementById('cardLastRun');
    if (el) el.textContent = s.last_run || '—';
    el = document.getElementById('cardLastAgo');
    if (el) {
      if (s.days_ago === 0) el.textContent = 'today';
      else if (s.days_ago === 1) el.textContent = '1 day ago';
      else if (s.days_ago == null) el.textContent = (s.last_run ? '' : 'never run');
      else el.textContent = s.days_ago + ' days ago';
    }
    el = document.getElementById('cardCount');
    if (el) el.textContent = String(s.report_count == null ? 0 : s.report_count);
    var list = document.getElementById('reportsList');
    if (list && s.reports) {
      if (!s.reports.length) {
        list.innerHTML = '<div class="empty">No health reports on disk yet.</div>';
      } else {
        list.innerHTML = s.reports.map(function (r) {
          var chip = chipNames[r.status] || 'unreadable';
          var href = tq('/doctor/report?name=' + encodeURIComponent(r.name));
          return '<a class="report-row" target="_blank" href="' + href + '">'
            + '<span class="dot ' + r.status + '"></span>'
            + '<span class="rr-date">' + r.date + '</span>'
            + '<span class="rr-chip ' + r.status + '">' + chip + '</span></a>';
        }).join('');
      }
    }
  }
  function refreshStats() {
    fetch(tq('/api/doctor/status'), { headers: getHdrs() })
      .then(function (r) { return r.json(); })
      .then(function (s) { if (s && s.ok) setCards(s); })
      .catch(function () {});
  }
  var polling = false;
  function pollDone() {
    polling = false;
    var btn = document.getElementById('runBtn');
    btn.disabled = false;
    btn.textContent = 'Run diagnostics';
    refreshStats();
  }
  function pollTail(since) {
    if (polling) return;
    polling = true;
    (function step(cursor) {
      fetch(tq('/api/doctor/healthcheck_tail?since=' + cursor), { headers: getHdrs() })
        .then(function (r) { return r.json(); })
        .then(function (p) {
          var out = document.getElementById('hcout');
          if (p && p.ok) {
            if (p.text) { out.textContent += p.text; out.scrollTop = out.scrollHeight; }
            if (p.running) { setTimeout(function () { step(p.next); }, 1000); return; }
            out.textContent += '\n[diagnostics finished' + (p.exit_code == null ? '' : ', exit ' + p.exit_code) + ']\n';
          }
          pollDone();
        })
        .catch(function () { pollDone(); });
    })(since);
  }
  window.runDiagnostics = function () {
    var out = document.getElementById('hcout');
    out.style.display = 'block';
    var body = {};
    if (token) body.token = token;
    fetch('/api/doctor/healthcheck_run', { method: 'POST', headers: hdrs(), body: JSON.stringify(body) })
      .then(function (r) { return r.json(); })
      .then(function (p) {
        if (!p || !p.ok) {
          out.textContent += '\n[doctor] run failed: ' + ((p && p.error) || 'unknown') + '\n';
          return;
        }
        if (!p.already_running) out.textContent = '';
        var btn = document.getElementById('runBtn');
        btn.disabled = true;
        btn.textContent = 'Running…';
        pollTail(0);
      })
      .catch(function (e) { out.textContent += '\n[doctor] run failed: ' + e + '\n'; });
  };
})();
</script>
</body>
</html>"""


def render_doctor_page_html():
    """The /doctor page — Anchor's own visual idiom, REAL values only.

    Server-renders the stat cards + reports list from :func:`_doctor_stats`;
    the terminal panel and diagnostics tail are wired by the page JS against
    the Wave-2 session endpoint and the background-run endpoints. Built by
    ``str.replace`` over a raw template — never an f-string (the V2 bug class).
    """
    s = _doctor_stats()
    esc = html_lib.escape
    if s["reports"]:
        chip_names = {"red": "issues", "yellow": "warnings", "green": "healthy"}
        rows = []
        for r in s["reports"]:
            chip = chip_names.get(r["status"], "unreadable")
            rows.append(
                '<a class="report-row" target="_blank"'
                ' href="/doctor/report?name=%s">'
                '<span class="dot %s"></span>'
                '<span class="rr-date">%s</span>'
                '<span class="rr-chip %s">%s</span></a>'
                % (url_quote(r["name"]), esc(r["status"]), esc(r["date"]),
                   esc(r["status"]), esc(chip)))
        reports_html = "".join(rows)
    else:
        reports_html = (
            '<div class="empty">No health reports on disk yet &mdash; run '
            'diagnostics now, or wait for the daily 5 AM check.</div>')
    if s["days_ago"] is None:
        ago = "" if s["last_run"] else "never run"
    elif s["days_ago"] == 0:
        ago = "today"
    elif s["days_ago"] == 1:
        ago = "1 day ago"
    else:
        ago = "%d days ago" % s["days_ago"]
    page = _DOCTOR_PAGE_TEMPLATE
    for key, value in (
        ("__STATUS_CLASS__", esc(s["status"])),
        ("__STATUS_TEXT__", esc(s["status_text"])),
        ("__STATUS_DETAIL__", esc(s["status_detail"])),
        ("__LAST_RUN__", esc(s["last_run"] or "—")),
        ("__LAST_AGO__", esc(ago)),
        ("__REPORT_COUNT__", str(s["report_count"])),
        ("__REPORTS_LIST__", reports_html),
    ):
        page = page.replace(key, value)
    return page


def handle_term_input2(handler, path, body):
    # POST-in half of the SSE-out + POST-in fallback transport. Authed by
    # the middleware above.
    session = (body.get("session", "") or "").strip()
    data = body.get("data", "")
    if not session:
        handler._send_json({"ok": False, "error": "session required"}, 400)
    elif len(str(data)) > _term.MAX_TURN_CHARS:
        # INPUT CAP (2026-07-26 hardening, P0.3). The legacy REPL endpoint has
        # capped turns since v2; this ConPTY path had NO length guard, so the
        # iPad dictation blow-up (each utterance re-sending everything said so
        # far) could pin the PTY with an unbounded write. The client-side
        # composition guard is the fix; this is the backstop that keeps a
        # runaway input from reaching the terminal at all.
        handler._send_json(
            {"ok": False,
             "error": f"turn too large ({len(str(data))} chars > "
                      f"{_term.MAX_TURN_CHARS}); refusing to write it to the PTY",
             "reason": "turn-too-large"}, 413)
    else:
        out = _termsess.input(session, data)
        if out.get("ok"):
            handler._send_json({"ok": True})
        else:
            handler._send_json({"ok": False,
                             "error": f"unknown session: {session}",
                             "reason": "unknown-session"}, 404)


def handle_journal_friction(handler, path, body):
    """Capture ONE friction/problem/concern the user just hit (2026-07-26).

    The user's words are stored verbatim; context (project/session/lane/route/
    engine/version + recent error lines) is attached automatically so nobody has
    to type it. ZERO model calls — the moment of friction is exactly when the
    engines are down, wedged, or burning money.
    """
    import friction_journal as _fj
    title = (body.get("title", "") or "").strip()
    if not title:
        handler._send_json(
            {"ok": False, "error": "title required (one line: what hurt?)"}, 400)
        return
    try:
        rec = _fj.capture(
            title,
            body=body.get("body", "") or "",
            severity=body.get("severity", _fj.DEFAULT_SEVERITY),
            project_id=body.get("project_id"),
            session_id=body.get("session_id"),
            lane=body.get("lane"),
            route=body.get("route"),
            engine=body.get("engine"),
        )
    except _fj.FrictionJournalError as e:
        handler._send_json({"ok": False, "error": str(e)}, 400)
        return
    except Exception as e:  # capture must never 500 on the user
        _logger.error("journal_friction failed: %s", e)
        handler._send_json({"ok": False, "error": "could not write the record"}, 500)
        return
    handler._send_json({"ok": True, "record": _fj.safe_projection(rec)})


def handle_friction_list(handler, path, body=None):
    """Read the friction records (SAFE projection — never raw log lines)."""
    import friction_journal as _fj
    q = parse_qs(urlparse(handler.path).query)
    status = (q.get("status", ["open"])[0] or "").strip() or None
    try:
        recs = _fj.list_records(status=status)
    except Exception as e:
        _logger.error("friction_list failed: %s", e)
        recs = []
    handler._send_json({"ok": True, "status": status,
                        "records": [_fj.safe_projection(r) for r in recs]})


def handle_answer_gate(handler, path, body):
    # Answer a pending in-session gate through the supervisor seam
    # (rearch W15): the answer is durably QUEUED + ACKed to the job dir
    # BEFORE this POST returns, then delivered to the session's stdin
    # supervisor-side — exactly once, retryable across a killed hop.
    # ``written`` is kept for the legacy endpoint contract (== delivered).
    job_id = body.get("job_id", "")
    choice = body.get("choice", "")
    res = _sup.get_supervisor().answer_gate(job_id, choice)
    handler._send_json({
        "ok": bool(res.get("ok")) and bool(res.get("delivered")),
        "written": bool(res.get("delivered")),
        "delivered": bool(res.get("delivered")),
        "deferred": bool(res.get("deferred")),
        "queued": bool(res.get("queued")),
        "reason": res.get("reason"),
        "job_id": res.get("job_id"),
    })


def handle_cancel_job(handler, path, body):
    # Stop a running job (tree-kill via job_runner.cancel). Acts on the
    # job_id supplied by the ATTACHED console session only — the caller
    # passes the exact job_id, so two concurrent sessions never cross-
    # wire. A clean 404 for an unknown id; auth is already enforced by the
    # middleware above (this is a mutating POST).
    job_id = (body.get("job_id", "") or "").strip()
    rec = _jr.load_record(job_id) if job_id else None
    if rec is None:
        handler._send_json({"ok": False, "error": f"unknown job: {job_id}",
                         "reason": "unknown-job"}, 404)
    else:
        # rearch W15: cancel through the supervisor seam (it owns the
        # process tree). Tree-kill is idempotent; a re-cancel no-ops.
        out = _sup.get_supervisor().cancel(job_id)
        handler._send_json({
            "ok": True,
            "job_id": job_id,
            "status": (out or {}).get("status"),
        })


def handle_regenerate_summary(handler, path, body):
    # Force re-run + re-cache a session's validated summary. Auth is
    # already enforced by the middleware above (mutating POST). The
    # session's members are summarized again through the runner seam and
    # summary.json + summary.md are overwritten. Clean 404 for an unknown
    # project or session.
    pid = body.get("project_id", "") or body.get("id", "")
    lane = body.get("lane", "")
    session_id = body.get("session_id", "")
    proj = _rnd.get_project(pid)
    if proj is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    elif not lane or not session_id:
        handler._send_json({"ok": False,
                         "error": "lane and session_id required"}, 400)
    else:
        folder = proj.get("folder_path", "")
        session = None
        try:
            for s in _sessions.list_sessions(folder, pid, lane):
                if s.get("session_id") == session_id:
                    session = s
                    break
        except Exception:
            session = None
        if session is None:
            handler._send_json({"ok": False,
                             "error": f"Unknown session: {session_id}"},
                            404)
        else:
            summary = _summarizer.summarize_session(
                folder, pid, lane, session, force=True)
            handler._send_json({"ok": True, "summary": summary})


def handle_continue_session(handler, path, body):
    # v5 Wave 2: open a NEW live session in the SAME lane as a DONE/
    # historical session, SEEDED with that prior session's context (its
    # cached summary, else a deterministic digest of its members). The
    # ORIGINAL session/registry record is NEVER mutated (Risk R2) — we
    # only READ it. Reuses terminal_session.start_session(seed_context=…)
    # (the Wave-1 seed path), so the new session's single opening turn
    # loads the lane skill AND carries the prior context. Auth enforced by
    # the do_POST middleware above (mutating/terminal).
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    lane = (body.get("lane", "") or "").strip()
    source = (body.get("source_session", "")
              or body.get("session", "") or "").strip()
    # Settings-backed default: continuing a past session opens a NEW session;
    # default it to default_cli rather than the project's sticky last_engine
    # (which could be another engine from an unrelated toggle). Explicit
    # backend in the body still wins; other engines stay reachable via the toggle.
    backend = ((body.get("backend", "") or "").strip()
               or _aset.get_default_cli())
    if not pid or not lane or not source:
        handler._send_json(
            {"ok": False,
             "error": "project_id, lane and source_session required"},
            400)
    else:
        proj = _rnd.get_project(pid)
        if proj is None:
            handler._send_json({"ok": False,
                             "error": "Unknown project"}, 404)
        else:
            folder = proj.get("folder_path", "")
            seed_context = _build_continue_seed(
                folder, pid, lane, source)
            # telemetry-resume W6 — the eviction sub-contract (NORTH-STAR-
            # AMENDMENT): an EVICTED-parked source (worktree reaped, docs persisted
            # to main) resumes as a NEW seeded session whose orientation opens with
            # an explicit 'resumed from persisted docs (worktree evicted)' line —
            # the UI NEVER claims a reattach it cannot perform. The replacement
            # joins the SAME chain via parent_session_id below.
            evicted = False
            try:
                src_rec = _termsess.get_session(source) or {}
                evicted = bool(src_rec.get("evicted")) or (
                    _sessreg.is_parked_warm(src_rec)
                    and not (src_rec.get("worktree_path") or "").strip())
            except Exception:
                evicted = False
            if evicted:
                note = ("(resumed from persisted docs (worktree evicted))\n")
                seed_context = note + (seed_context or "")
            try:
                # Join the SAME chain as the source (lineage continuity across
                # resume/eviction) via parent_session_id; an unknown source id
                # harmlessly resets to its own chain (start_session guard).
                if backend:
                    rec = _termsess.start_session(
                        pid, lane, backend=backend,
                        seed_context=seed_context, parent_session_id=source)
                else:
                    rec = _termsess.start_session(
                        pid, lane, seed_context=seed_context,
                        parent_session_id=source)
            except _termsess.TerminalSessionError as exc:
                handler._send_json({"ok": False, "error": str(exc)}, 400)
            else:
                handler._send_json({"ok": True, "session": rec,
                                 "seeded_from": source, "evicted": evicted})


def handle_resume_live(handler, path, body):
    # telemetry-resume W6 — the Layer-2 '▶ Resume live' escalation, routed by tile
    # class on the SERVER (so the per-class contract is one testable decision, not
    # scattered client logic). Cites the NORTH-STAR-AMENDMENT click contract +
    # eviction sub-contract:
    #   * RUNNING            → focus the already-live session (mode 'already-live').
    #   * parked-idle        → WARM REATTACH: relaunch a PTY in the RETAINED
    #                          worktree under the same id (mode 'reattach').
    #   * evicted-parked     → NEW seeded session on the SAME chain, seed opens with
    #                          'resumed from persisted docs (worktree evicted)'
    #                          (mode 'continue', evicted:true) — NEVER a reattach.
    #   * done/failed/discovered/one-shot job → the W3/W4 continue-seed path
    #                          (mode 'continue') on the SAME chain.
    # Auth: the do_POST token middleware gates this (mutating).
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    lane = (body.get("lane", "") or "").strip()
    source = (body.get("source_session", "")
              or body.get("session", "") or "").strip()
    backend = ((body.get("backend", "") or "").strip()
               or _aset.get_default_cli())
    if not pid or not source:
        handler._send_json({"ok": False,
                         "error": "project_id and source_session required"}, 400)
        return
    proj = _rnd.get_project(pid)
    if proj is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
        return
    folder = proj.get("folder_path", "")
    try:
        src_rec = _termsess.get_session(source) or {}
    except Exception:
        src_rec = {}
    if not lane:
        lane = (src_rec.get("lane") or "").strip()
    # RUNNING → focus the existing live session (no new spawn).
    import pty_manager as _pty
    is_truly_live = False
    if src_rec.get("status") == _sessreg.STATUS_RUNNING:
        with _pty._TABLE_LOCK:
            is_truly_live = source in _pty._LIVE

    if src_rec.get("status") == _sessreg.STATUS_RUNNING and is_truly_live:
        handler._send_json({"ok": True, "mode": "already-live",
                         "session": _safe_session_projection(src_rec)})
        return
    # parked-idle (retained worktree) → warm reattach in place.
    is_parked = _sessreg.is_parked_warm(src_rec)
    has_worktree = bool((src_rec.get("worktree_path") or "").strip())
    if is_parked and has_worktree and not src_rec.get("evicted"):
        res = _termsess.resume_parked_session(source)
        if res.get("ok"):
            handler._send_json({"ok": True, "mode": res.get("mode", "reattach"),
                             "session": _safe_session_projection(
                                 res.get("session") or {})})
            return
        # A reattach that couldn't happen (evicted mid-flight) falls through to
        # the continue path below — honest, never a false reattach claim.
    # Everything else (evicted / done / failed / discovered) → continue-seed a NEW
    # session on the SAME chain (reuse the continue handler's exact policy).
    handle_continue_session(handler, path, {
        "project_id": pid, "lane": lane or (src_rec.get("lane") or ""),
        "source_session": source, "backend": backend})


def _safe_session_projection(rec):
    """SAFE session projection for a Layer-2 escalation response — NEVER leaks
    ``worktree_path``/``branch`` (the board-projection discipline)."""
    rec = rec if isinstance(rec, dict) else {}
    return {
        "session_id": rec.get("session_id", ""),
        "lane": rec.get("lane", ""),
        "backend": rec.get("backend", ""),
        "status": rec.get("status", ""),
        "label": rec.get("label", ""),
        "chain_id": rec.get("chain_id", ""),
        "parent_session_id": rec.get("parent_session_id", ""),
        "evicted": bool(rec.get("evicted", False)),
    }


def handle_orient_session(handler, path, body):
    # telemetry-resume W6 — the read-only plan-mode ORIENTATION trigger (the
    # Phase-0 orientation fork, NORTH-STAR-AMENDMENT). On a Layer-2 escalation the
    # orientation narration AUTO-EXECUTES as a read-only ``permission_mode='plan'``
    # one-shot job through job_runner (the Gandalf-shard substrate) — it prints
    # what was done / produced / next, and can NEVER edit the tree. It is NEVER a
    # seeded turn on the live PTY, and any ACTION prompt stays v10 paste-NOT-submit
    # (nothing is auto-submitted). Returns the launched job id so the client can
    # tail its output into the terminal chrome.
    #   POST /api/rnd/orient_session  {project_id, lane, session}
    # Auth: the do_POST token middleware gates this (mutating — it launches a job).
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    lane = (body.get("lane", "") or "").strip()
    session_id = (body.get("session", "")
                  or body.get("source_session", "") or "").strip()
    if not pid or not session_id:
        handler._send_json({"ok": False,
                         "error": "project_id and session required"}, 400)
        return
    proj = _rnd.get_project(pid)
    if proj is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
        return
    folder = proj.get("folder_path", "")
    if not lane:
        try:
            lane = (_termsess.get_session(session_id) or {}).get("lane", "")
        except Exception:
            lane = ""
    try:
        import orientation as _orient
        out = _orient.orient_session(pid, lane, session_id, folder_path=folder)
    except Exception as exc:
        handler._send_json({"ok": False, "error": str(exc)}, 500)
        return
    if out.get("ok"):
        handler._send_json({"ok": True, "job_id": out.get("job_id"),
                         "permission_mode": out.get("permission_mode"),
                         "owned_until": out.get("owned_until")})
    else:
        handler._send_json({"ok": False,
                         "reason": out.get("reason", "orient-failed")}, 400)


def handle_advance_session(handler, path, body):
    # v6 Wave 5: MANUAL advance research → planning. Starts a NEW live
    # session in ``to_lane`` (defaults 'planning' for a research source),
    # LINKED to the source via ``parent_session_id`` (so it inherits the
    # source's ``chain_id`` — see session_registry.start_session / Wave 2),
    # and SEEDED with the source session's grounded summary/report context.
    # The seed is built by the SAME read-only _build_continue_seed helper
    # (its cached summary, else a member digest), so the SOURCE session /
    # registry record is NEVER mutated — we only READ it. Returns the new
    # session record in the same JSON shape as continue_session. Auth is
    # enforced by the do_POST token middleware above (mutating/terminal).
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    source = (body.get("source_session", "")
              or body.get("session", "") or "").strip()
    to_lane = (body.get("to_lane", "") or "").strip() or "planning"
    backend = (body.get("backend", "") or "").strip() or None
    if not pid or not source:
        handler._send_json(
            {"ok": False,
             "error": "project_id and source_session required"},
            400)
    else:
        proj = _rnd.get_project(pid)
        if proj is None:
            handler._send_json({"ok": False,
                             "error": "Unknown project"}, 404)
        elif (_termsess.get_session(source) or {}).get("effort_managed"):
            # v12 Wave 7 — RETIREMENT MAP (Shark C2/C3): a v12 EFFORT
            # advances IN-SESSION via /api/rnd/advance_stage; the legacy
            # research→plan advance must mint NOTHING for it. Early-return
            # so the effort's session-id set is unchanged. Gate on the
            # SOURCE session's ``effort_managed`` ONLY (never lane/kind).
            # Legacy records (False) fall through to the full v6/v11
            # advance path below, unchanged.
            handler._send_json(
                {"ok": False, "session": None,
                 "reason": "effort-managed-use-advance-stage"}, 409)
        else:
            folder = proj.get("folder_path", "")
            # Resolve the SOURCE session's lane for the seed lookup. The
            # seed reads the source's CACHED summary in ITS lane; default
            # to 'research' (the only source this wave advances).
            src_lane = "research"
            try:
                for r in _termsess.list_sessions(project_id=pid):
                    if r.get("session_id") == source:
                        src_lane = r.get("lane") or src_lane
                        break
            except Exception:
                pass
            # v11 Wave 2 — THE user-facing fix: route research→plan through
            # the SHARED handoff KEYSTONE (terminal_session.prepare_stage_
            # handoff), mirroring finish_to_build's capture-before-advance.
            # The keystone (a) PERSISTS the live source session's produced
            # docs into the MAIN project (copy + commit to main HEAD,
            # session-tagged efforts — best-effort, idempotent, never raises)
            # so they ride into the planning worktree (checked out off main
            # HEAD); (b) BUILDS the REAL doc-referencing prompt (names the
            # actual persisted paths + "read these first, then plan" + load
            # Crucible — honest minimal only when there are genuinely no
            # docs, never fabricated); (c) resolves doc_rels + skill + the
            # source's cached summary for HANDOFF.md. This is the fix for the
            # reported failure: the pre-v11 path NEVER persisted the live
            # research docs, so the prompt was a bare "load Crucible" with no
            # paths and no HANDOFF.md.
            hk = _termsess.prepare_stage_handoff(pid, source, to_lane)
            # v11 honesty guard: if the keystone could NOT resolve the
            # source session (ok=False → no record / unknown id → empty
            # prompt + empty doc_rels), do NOT mint an orphan planning
            # session with an empty paste. Return an honest error instead
            # (matching the honest-degradation discipline). The
            # no-DOCS-but-valid-source path keeps ok=True and proceeds with
            # the honest minimal prompt — only the source-unresolvable case
            # is guarded here.
            if not hk.get("ok"):
                handler._send_json(
                    {"ok": False,
                     "error": "could not resolve source session"}, 400)
                return
            # The reviewable TASK PROMPT is delivered as a PENDING PASTE
            # (held in the new PTY input UNSENT until the user presses
            # Enter — paste-NOT-submit, unchanged). The grounded summary
            # context still seeds phase-1 (load+greet) so the model greets
            # with prior context. Best-effort: an empty prompt → falls back
            # to today's seed-context-only path (honest, no fabrication).
            seed_context = _build_continue_seed(
                folder, pid, src_lane, source)
            paste = (hk.get("prompt", "") or "").strip() or None
            try:
                if backend:
                    rec = _termsess.start_session(
                        pid, to_lane, backend=backend,
                        seed_context=seed_context,
                        paste_prompt=paste,
                        parent_session_id=source)
                else:
                    rec = _termsess.start_session(
                        pid, to_lane, seed_context=seed_context,
                        paste_prompt=paste,
                        parent_session_id=source)
            except _termsess.TerminalSessionError as exc:
                handler._send_json({"ok": False, "error": str(exc)}, 400)
            else:
                # The planning worktree now EXISTS (off main HEAD, which the
                # keystone just committed the research docs to). Write BOTH
                # durable artifacts into it: the real HANDOFF.md (lists the
                # persisted upstream doc paths + the Crucible skill + the
                # source's cached summary) AND NEXT-PROMPT.md (the reviewable
                # pasted prompt). Then record the research->plan stage edge.
                # All best-effort — a write hiccup never strands the advance.
                new_wt = rec.get("worktree_path", "")
                new_sid = rec.get("session_id", "")
                if new_wt:
                    try:
                        _handoff.write_handoff_md(
                            new_wt, hk.get("doc_rels", []),
                            hk.get("skill", "") or "Crucible",
                            hk.get("summary_text", ""))
                    except Exception:
                        pass
                    if paste:
                        try:
                            _handoff.write_next_prompt(new_wt, paste)
                        except Exception:
                            pass
                try:
                    _handoff.record_stage_link(
                        folder, pid, source, new_sid,
                        kind="research->plan")
                except Exception:
                    pass
                handler._send_json({"ok": True, "session": rec,
                                 "advanced_from": source,
                                 "to_lane": to_lane,
                                 "persisted": hk.get("persisted", [])})


def handle_advance_stage(handler, path, body):
    # v12 Wave 6: in-session "Advance" = relabel + save. Keeps the SAME
    # session (no new session minted, NOTHING injected into the PTY by
    # default): terminal_session.advance_stage persists+summarizes the
    # current stage (Wave 5, no reap) and flips current_stage to the next
    # trio stage. Auth is enforced by the do_POST token middleware above.
    session = (body.get("session", "")
               or body.get("session_id", "") or "").strip()
    to_stage = (body.get("to_stage", "") or "").strip() or None
    pid = (body.get("project_id", "") or body.get("id", "")).strip() or None
    if not session:
        handler._send_json({"ok": False, "error": "session required"}, 400)
    elif _termsess.get_session(session) is None:
        handler._send_json({"ok": False,
                         "error": f"unknown session: {session}",
                         "reason": "unknown-session"}, 404)
    else:
        out = _termsess.advance_stage(
            session, to_stage=to_stage, mode="manual", project_id=pid)
        rec = out.get("record")
        # SAFE projection of the updated record — NEVER worktree_path /
        # branch (those must not leak into the page).
        safe = None
        if isinstance(rec, dict):
            safe = {
                "session_id": rec.get("session_id", ""),
                "project_id": rec.get("project_id", ""),
                "lane": rec.get("lane", ""),
                "status": rec.get("status", ""),
                "label": rec.get("label", ""),
                "kind": rec.get("kind", ""),
                "current_stage": rec.get("current_stage", ""),
                "effort_id": rec.get("effort_id", ""),
                "effort_managed": rec.get("effort_managed", False),
                # project stage_history to SAFE fields — drop baseline_ref
                # (a git SHA) + store_lane (Reviewer W6-R2-05).
                "stage_history": [
                    {"stage": e.get("stage", ""),
                     "state": e.get("state", ""),
                     "started_at": e.get("started_at"),
                     "ended_at": e.get("ended_at"),
                     "doc_count": e.get("doc_count", 0),
                     "summary_ref": e.get("summary_ref")}
                    for e in (rec.get("stage_history") or [])
                    if isinstance(e, dict)
                ],
            }
        handler._send_json({"ok": bool(out.get("ok")),
                         "advanced": bool(out.get("advanced")),
                         "reason": out.get("reason"),
                         "from_stage": out.get("from_stage"),
                         "to_stage": out.get("to_stage"),
                         "session": safe},
                        200 if out.get("ok") else 400)


def handle_handoff_to_fresh(handler, path, body):
    # v12 Wave 8: the context-relief valve. Continue the effort in a FRESH
    # session that JOINS the same effort (same effort_id / tile / lineage),
    # carrying the prior stage's docs + the real next prompt forward via the
    # v11.1 machinery — held as a PENDING PASTE (UNSENT; NOTHING
    # auto-submitted). The old session's stage is closed (done); its
    # worktree is NOT reaped. Auth is enforced by the do_POST token
    # middleware above (mutating).
    session = (body.get("session", "")
               or body.get("session_id", "")
               or body.get("effort_id", "")).strip()
    pid = (body.get("project_id", "") or body.get("id", "")).strip() or None
    if not session:
        handler._send_json(
            {"ok": False,
             "error": "session or effort_id required"}, 400)
    else:
        out = _termsess.handoff_to_fresh(session, project_id=pid)
        if not out.get("ok"):
            code = 404 if out.get("reason") == "unknown-session" else 400
            handler._send_json({"ok": False,
                             "reason": out.get("reason"),
                             "error": out.get("reason", "handoff failed")},
                            code)
        else:
            new_rec = out.get("new_session") or {}
            old_rec = out.get("old_session") or {}

            def _safe(rec):
                # SAFE projection — NEVER worktree_path / branch.
                if not isinstance(rec, dict):
                    return None
                return {
                    "session_id": rec.get("session_id", ""),
                    "project_id": rec.get("project_id", ""),
                    "lane": rec.get("lane", ""),
                    "status": rec.get("status", ""),
                    "kind": rec.get("kind", ""),
                    "current_stage": rec.get("current_stage", ""),
                    "effort_id": rec.get("effort_id", ""),
                    "effort_managed": rec.get("effort_managed", False),
                    "parent_session_id": rec.get("parent_session_id", ""),
                    "chain_id": rec.get("chain_id", ""),
                    "pending_paste": rec.get("pending_paste", ""),
                    "paste_flushed": rec.get("paste_flushed", False),
                }

            handler._send_json({
                "ok": True,
                "effort_id": out.get("effort_id", ""),
                "new_session": _safe(new_rec),
                "old_session": _safe(old_rec),
                "persisted": out.get("persisted", []),
            })


def handle_finish_to_build(handler, path, body):
    # v6 Wave 9 (polish 1): EXPLICIT, NON-DESTRUCTIVE plan→build advance.
    # Mirrors the term_kill auto-advance trigger, but WITHOUT reaping the
    # planning session's worktree: it stays a reopenable, finished tile
    # (close-to-tile philosophy). Steps:
    #   1. capture the plan set NOW (before any reap) via capture_plan_set;
    #   2. mark THIS planning session DONE via session_registry
    #      .update_session(status=STATUS_DONE) — NOT kill() (worktree kept);
    #   3. auto_advance_planning_to_build(..., plan_set=…) — idempotent on
    #      parent_session_id, so a second call never duplicates the build.
    # No plan set ⇒ {ok:true, auto_build:null, reason:"no plan set yet"} so
    # the UI can be honest (never a fabricated build). Auth is enforced by
    # the do_POST token middleware above (mutating).
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    session = (body.get("session", "")
               or body.get("source_session", "") or "").strip()
    if not pid or not session:
        handler._send_json(
            {"ok": False,
             "error": "project_id and session required"}, 400)
    else:
        rec = _termsess.get_session(session)
        if rec is None:
            handler._send_json({"ok": False,
                             "error": f"unknown session: {session}",
                             "reason": "unknown-session"}, 404)
        elif rec.get("lane") not in _termsess._PLANNING_LANES:
            handler._send_json(
                {"ok": False,
                 "error": "finish→build applies only to a planning "
                          "session",
                 "reason": "not-planning"}, 400)
        elif rec.get("effort_managed"):
            # v12 Wave 7 — RETIREMENT MAP (Shark C2/C3): a v12 EFFORT
            # advances IN-SESSION via /api/rnd/advance_stage; the legacy
            # finish→build path must mint NOTHING for it. Early-return
            # (no persist-DONE-mark, no auto-advance) so the effort's
            # session-id set is unchanged. Gate on ``effort_managed``
            # ONLY (never lane/kind). Legacy records (False) fall through
            # to the full v6 finish→build path below, unchanged.
            handler._send_json(
                {"ok": False, "auto_build": None,
                 "reason": "effort-managed-use-advance-stage"}, 409)
        else:
            # 0) v11 Wave 3 — route the persist through the SHARED keystone
            #    (:func:`prepare_stage_handoff`), unifying this path with
            #    research→plan + auto-advance. The keystone PERSISTS the
            #    planning session's produced docs into the MAIN project (copy
            #    + commit to main HEAD, session-tagged efforts — best-effort,
            #    idempotent, never raises) WITHOUT reaping the worktree, so the
            #    planning session stays a reopenable finished tile (v6
            #    non-destructive finish semantics preserved). This is the
            #    North-Star hole fix (the finish→build path marks the session
            #    DONE via update_session WITHOUT kill(), so persist is NOT
            #    otherwise run — the plan docs authored in the planning
            #    worktree would never reach main, and the build worktree
            #    created off main HEAD by auto_advance would lack the
            #    HANDOFF.md/NEXT-PROMPT.md referenced paths). It is ALSO what
            #    makes the just-authored plan set DISCOVERABLE to the
            #    capture_plan_set() below: discovery reads the session-tagged
            #    effort pointer-records the persist creates, so the persist
            #    MUST run here, before capture, on the worktree-only finish
            #    flow (the docs are not yet on main / not yet recorded as
            #    efforts otherwise). The build prompt itself is (re)built by
            #    auto_advance_planning_to_build through the SAME keystone
            #    (idempotent re-persist), so there is ONE persist+prompt
            #    mechanism across every advance path.
            try:
                _termsess.prepare_stage_handoff(pid, session, "build")
            except Exception:
                pass
            # 1) Capture the plan set AFTER persisting (so the just-authored
            #    plan docs are now on main HEAD and discoverable). No reap
            #    here, so the worktree survives either way.
            plan_set = _termsess.capture_plan_set(pid, session)
            if not plan_set:
                # Honest: no plan set yet ⇒ no build (worktree untouched;
                # the session stays exactly as it was — we do NOT mark it
                # done if there is nothing to advance to).
                handler._send_json({"ok": True, "auto_build": None,
                                 "reason": "no plan set yet"})
            else:
                # 2) Mark the planning session DONE WITHOUT reaping its
                #    worktree (non-destructive — reopenable finished tile).
                try:
                    _sessreg.update_session(
                        session, status=_sessreg.STATUS_DONE)
                except KeyError:
                    pass
                # Honest Telemetry W4: eager finalize on the FINISH end path
                # (the DONE mark WITHOUT a reap). Idempotent CAS; best-effort.
                try:
                    _termsess.finalize_usage(session, project_id=pid, record=rec)
                except Exception:
                    pass
                # v7 Wave 2: the finished planning session is DONE —
                # schedule a background session-summary (best-effort,
                # non-blocking, idempotent). Never delays this response.
                try:
                    _trigger_session_summary_on_finish(
                        pid, rec.get("lane"), session)
                except Exception:
                    pass
                # 3) Auto-advance to ONE linked build (idempotent).
                try:
                    auto_build = _termsess.auto_advance_planning_to_build(
                        pid, session, plan_set=plan_set)
                except Exception:
                    auto_build = None
                if auto_build is None:
                    handler._send_json(
                        {"ok": True, "auto_build": None,
                         "reason": "no build (already advanced or "
                                   "discovery failed)"})
                else:
                    handler._send_json({"ok": True,
                                     "auto_build": auto_build})


def handle_heartbeat(handler, path, body):
    global _last_heartbeat
    _last_heartbeat = datetime.now()
    handler._send_json({"ok": True})


def handle_move_project(handler, path, body):
    # v9 Wave 4 — GUARDED on-disk move: relocate a project's directory
    # into a group subfolder and re-point registry+worktrees+discovery.
    # Token-gated by the do_POST middleware above AND requires an
    # explicit confirm:true (a real, irreversible filesystem move).
    # REFUSES (no fs change) the running Anchor repo + any live-session
    # project, surfacing the refusal reason. NEVER raises into here.
    import project_move as _pmove
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    group = body.get("group", "")
    confirm = bool(body.get("confirm"))
    if not pid:
        handler._send_json(
            {"ok": False, "error": "project_id required"}, 400)
    elif not confirm:
        handler._send_json({"ok": False,
                         "error": "move requires confirm:true",
                         "reason": "confirm-required"}, 400)
    else:
        try:
            out = _pmove.move_to_group(pid, group)
        except Exception as exc:  # defensive — move_to_group never raises
            handler._send_json({"ok": False, "error": str(exc)}, 500)
        else:
            status = 200 if out.get("ok") else (
                404 if out.get("reason") == "unknown-project" else 400)
            handler._send_json(out, status)


def handle_run_deliverable(handler, path, body):
    # Run a deliverable per its type contract; persist + report status.
    pid = body.get("project_id", "")
    proj = _rnd.get_project(pid)
    if proj is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    else:
        folder = proj.get("folder_path", "")
        try:
            rec = _deliv.run_deliverable(
                body.get("type", ""),
                target=body.get("target"),
                argv=body.get("argv"),
                cwd=body.get("cwd") or folder or None,
                timeout=float(body.get("timeout",
                                       _deliv.DEFAULT_TIMEOUT)),
                folder_path=folder,
                project_id=pid,
                name=body.get("name"),
            )
            handler._send_json({"ok": True, "status": rec})
        except ValueError as ve:
            handler._send_json({"ok": False, "error": str(ve)}, 400)


def handle_launch_deliverable(handler, path, body):
    # v4 Wave 7: TYPE-AWARE launch of a pinned deliverable. Dispatches on
    # the deliverable's type — skill/tool VERIFY status (no spawn);
    # service launches/pulls-up a persistent preview (free port != 8777,
    # isolated temp data dir); program runs to result; doc returns the
    # rendered view href. Auth is enforced by the middleware above.
    pid = (body.get("project_id", "") or body.get("pid", "")).strip()
    deliverable_id = (body.get("deliverable_id", "") or "").strip()
    proj = _rnd.get_project(pid)
    if proj is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    elif not deliverable_id:
        handler._send_json({"ok": False,
                         "error": "deliverable_id required"}, 400)
    else:
        folder = proj.get("folder_path", "")
        try:
            res = _deliv.launch_deliverable(folder, pid, deliverable_id)
        except Exception as exc:  # never a 500 to the UI
            handler._send_json({"ok": False, "error": str(exc)}, 400)
        else:
            if not res.get("ok") and \
                    res.get("reason") == "unknown deliverable":
                # Unknown deliverable id → clean 404 (not a crash).
                handler._send_json({"ok": False,
                                 "error": "unknown deliverable",
                                 "reason": "unknown-deliverable"}, 404)
            elif not res.get("ok"):
                # Type-specific clean failure (e.g. service never came
                # up / program failed its contract) → 400, not a 500.
                handler._send_json({"ok": False,
                                 "error": res.get("reason")
                                 or "launch failed",
                                 "type": res.get("type"),
                                 "port": res.get("port")}, 400)
            else:
                handler._send_json({"ok": True, **res})


def handle_launch_lane(handler, path, body):
    # Launch a trio lane (research|plan|build) for a project. Returns a
    # clean JSON error (not a 500) for an unknown project / invalid lane
    # / a concurrency refusal (same-lane-busy or folder-build-lock).
    # Headless jobs keep lanes.DEFAULT_BACKEND (claude) when omitted —
    # only interactive terminals use settings default_cli.
    pid = body.get("project_id", "")
    lane = body.get("lane", "")
    backend = body.get("backend") or _lanes.DEFAULT_BACKEND
    if lane not in _lanes.LANES:
        handler._send_json({"ok": False, "error": f"invalid lane: {lane}",
                         "reason": "invalid-lane"}, 400)
    elif backend not in _termsess.VALID_BACKENDS:
        handler._send_json({"ok": False,
                         "error": f"invalid engine: {backend}",
                         "reason": "invalid-engine"}, 400)
    else:
        try:
            rec = _lanes.launch_lane(pid, lane, backend=backend)
            handler._send_json({
                "ok": True,
                "job_id": rec.get("job_id"),
                "lane": lane,
                "backend": rec.get("backend"),
                "status": rec.get("status"),
                "skill": rec.get("skill"),
                "gates": rec.get("gates"),
            })
        except _lanes.EngineNotAllowedError as eng:
            # Engine policy refused (e.g. gemini on plan/build) — clean
            # JSON error, NOT a 500.
            handler._send_json({
                "ok": False,
                "error": str(eng),
                "reason": "engine-not-allowed",
                "lane": eng.lane,
                "backend": eng.backend,
            }, 400)
        except KeyError:
            handler._send_json({"ok": False,
                             "error": f"unknown project: {pid}",
                             "reason": "unknown-project"}, 404)
        except _jr.LaneBusyError as busy:
            # Concurrency policy refused the launch — surface a clean
            # indicator (same-lane-busy / folder-build-lock), not a 500.
            handler._send_json({
                "ok": False,
                "error": str(busy),
                "reason": busy.reason,
                "holder": busy.holder,
            }, 409)


def handle_preview_start(handler, path, body):
    # Spin up an EPHEMERAL preview of the project's deliverable web app
    # (e.g. anchor_gui.py) on an OS-assigned free port (NEVER 8777) in an
    # isolated TEMP ANCHOR_DATA_DIR — so it can never bind or disturb the
    # live :8777 service. Auth is enforced by the middleware above.
    pid = (body.get("project_id", "") or "").strip()
    proj = _rnd.get_project(pid)
    if proj is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    else:
        folder = proj.get("folder_path", "")
        target = (body.get("deliverable") or body.get("target")
                  or _preview.DEFAULT_TARGET)
        res = _preview.start_preview(folder, pid, target=target)
        if res.get("ok"):
            handler._send_json({"ok": True, "url": res.get("url"),
                             "preview_id": res.get("preview_id"),
                             "port": res.get("port"),
                             "pid": res.get("pid")})
        else:
            # Clean 400 (e.g. target missing / never came up), not a 500.
            handler._send_json({"ok": False,
                             "error": res.get("reason", "preview failed"),
                             "port": res.get("port")}, 400)


def handle_preview_stop(handler, path, body):
    # Tree-kill + reap a running preview. Idempotent; 404 for unknown id.
    preview_id = (body.get("preview_id", "") or "").strip()
    res = _preview.stop_preview(preview_id)
    if res.get("ok"):
        handler._send_json({"ok": True,
                         "preview_id": res.get("preview_id"),
                         "status": res.get("status")})
    else:
        handler._send_json({"ok": False,
                         "error": res.get("reason", "unknown preview"),
                         "reason": "unknown-preview"}, 404)


def handle_promote_inbox(handler, path, body):
    # Promote an EXISTING INBOX.md item into a project's Grass Catchers
    # (copy-by-default: the inbox item is NOT removed). Reuses the
    # existing inbox parser — no new format. Auth enforced above.
    pid = body.get("project_id", "") or body.get("id", "")
    proj = _rnd.get_project(pid)
    if proj is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    else:
        folder = proj.get("folder_path", "")
        inbox_items = parse_inbox_from_md(INBOX_MD)
        try:
            rec = _eh.promote_inbox(folder, pid,
                                    body.get("text", ""),
                                    inbox_items=inbox_items)
            handler._send_json({"ok": True, "effort": rec})
        except ValueError as ve:
            handler._send_json({"ok": False, "error": str(ve)}, 400)


def handle_link_github(handler, path, body):
    # v8 Wave 3: link the project's repo to a GitHub remote. mode=create
    # → gh repo create <name> --private (through the ANCHOR_GH_CMD seam —
    # NEVER real github.com in tests); mode=existing → git remote add
    # origin <url> (local). Persists the remote on the project record.
    # Default repos are PRIVATE. Auth enforced by the middleware above.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    mode = (body.get("mode", "") or "").strip().lower()
    value = (body.get("value", "") or "").strip()
    if not pid or not mode:
        handler._send_json(
            {"ok": False, "error": "project_id and mode required"}, 400)
    elif mode not in ("create", "existing"):
        handler._send_json(
            {"ok": False,
             "error": "mode must be 'create' or 'existing'"}, 400)
    else:
        proj = _rnd.get_project(pid)
        if proj is None:
            handler._send_json({"ok": False,
                             "error": "Unknown project"}, 404)
        else:
            folder = proj.get("folder_path", "")
            res = _remote.link_github(folder, mode, value,
                                      project_id=pid)
            code = 200 if res.get("ok") else 400
            handler._send_json(res, code)


def handle_set_auto_push(handler, path, body):
    # v8 Wave 3: persist the per-project auto-push-on-finish opt-in flag.
    # Auth enforced above. A non-opted project never pushes.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    if not pid:
        handler._send_json({"ok": False,
                         "error": "project_id required"}, 400)
    elif _rnd.get_project(pid) is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    else:
        enabled = bool(body.get("enabled"))
        _remote.set_auto_push(pid, enabled)
        handler._send_json({"ok": True, "auto_push": enabled})


def handle_push_now(handler, path, body):
    # v8 Wave 3: manual "Push now" — git push -u origin <branch>. In tests
    # origin is a LOCAL BARE repo (file://) so there is NO network. Auth
    # enforced above. 400 when not linked (no origin). Never raises.
    pid = (body.get("project_id", "") or body.get("id", "")).strip()
    if not pid:
        handler._send_json({"ok": False,
                         "error": "project_id required"}, 400)
    elif _rnd.get_project(pid) is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
    else:
        proj = _rnd.get_project(pid)
        folder = proj.get("folder_path", "")
        res = _remote.push_project(folder, pid)
        code = 200 if res.get("ok") else 400
        handler._send_json(res, code)


def handle_project_files(handler, path, body):
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    q = parse_qs(urlparse(handler.path).query)
    project_id = (q.get("project_id", [""])[0] or "").strip()
    path_param = (q.get("path", [""])[0] or "").strip()
    recursive_param = (q.get("recursive", [""])[0] or "").strip().lower() == "true"

    if not project_id:
        handler._send_json({"ok": False, "error": "project_id required"}, 400)
        return
    if _unsafe_path_seg(project_id):
        handler._send_json({"ok": False, "error": "invalid project_id"}, 400)
        return

    proj = _rnd.get_project(project_id)
    if proj is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
        return

    project_root = Path(proj["folder_path"]).resolve()

    # Traversal check
    p = Path(path_param) if path_param else Path(".")
    if p.is_absolute() or ".." in p.parts:
        handler._send_json({"ok": False, "error": "Path traversal detected"}, 400)
        return

    target_path = (project_root / p).resolve()
    try:
        target_path.relative_to(project_root)
    except ValueError:
        handler._send_json({"ok": False, "error": "Path containment check failed"}, 400)
        return

    if not target_path.exists():
        handler._send_json({"ok": False, "error": "Path not found"}, 404)
        return
    if not target_path.is_dir():
        handler._send_json({"ok": False, "error": "Not a directory"}, 400)
        return

    patterns = _load_gitignore(project_root)
    dirs_list = []
    files_list = []

    if recursive_param:
        for root, dirs, files in os.walk(target_path):
            # Filter ignored directories in-place to prevent scanning them
            dirs_to_keep = []
            for d in dirs:
                full_d = Path(root) / d
                try:
                    resolved_d = full_d.resolve()
                    resolved_d.relative_to(project_root)
                    rel_d = full_d.relative_to(project_root)
                    if not _should_ignore_file(rel_d, patterns):
                        dirs_to_keep.append(d)
                except (ValueError, OSError):
                    continue
            dirs[:] = dirs_to_keep

            for file in files:
                full_f = Path(root) / file
                try:
                    resolved_f = full_f.resolve()
                    resolved_f.relative_to(project_root)
                    rel_f = full_f.relative_to(project_root)
                    if not _should_ignore_file(rel_f, patterns):
                        stat = full_f.stat()
                        files_list.append({
                            "name": rel_f.as_posix(),
                            "path": rel_f.as_posix(),
                            "size": stat.st_size,
                            "mtime": stat.st_mtime
                        })
                except (ValueError, OSError):
                    continue

            for d in dirs:
                full_d = Path(root) / d
                try:
                    rel_d = full_d.relative_to(project_root)
                    dirs_list.append(rel_d.as_posix())
                except (ValueError, OSError):
                    continue
    else:
        try:
            for entry in sorted(target_path.iterdir(), key=lambda x: x.name.lower()):
                try:
                    # Strict symlink containment check
                    resolved_entry = entry.resolve()
                    resolved_entry.relative_to(project_root)
                except (ValueError, OSError):
                    continue

                rel_entry = entry.relative_to(project_root)
                if _should_ignore_file(rel_entry, patterns):
                    continue

                if entry.is_dir():
                    dirs_list.append(rel_entry.as_posix())
                elif entry.is_file():
                    try:
                        stat = entry.stat()
                        files_list.append({
                            "name": rel_entry.name,
                            "path": rel_entry.as_posix(),
                            "size": stat.st_size,
                            "mtime": stat.st_mtime
                        })
                    except OSError:
                        continue
        except PermissionError:
            handler._send_json({"ok": False, "error": "permission-denied"}, 403)
            return
        except OSError as exc:
            handler._send_json({"ok": False, "error": f"os-error: {exc}"}, 500)
            return

    handler._send_json({
        "ok": True,
        "path": p.as_posix() if path_param else "",
        "dirs": sorted(dirs_list, key=lambda x: x.lower()),
        "files": sorted(files_list, key=lambda x: x["name"].lower())
    })


def handle_project_file_content(handler, path, body):
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    q = parse_qs(urlparse(handler.path).query)
    project_id = (q.get("project_id", [""])[0] or "").strip()
    path_param = (q.get("path", [""])[0] or "").strip()

    if not project_id or not path_param:
        handler._send_json({"ok": False, "error": "project_id and path required"}, 400)
        return
    if _unsafe_path_seg(project_id):
        handler._send_json({"ok": False, "error": "invalid project_id"}, 400)
        return

    proj = _rnd.get_project(project_id)
    if proj is None:
        handler._send_json({"ok": False, "error": "Unknown project"}, 404)
        return

    project_root = Path(proj["folder_path"]).resolve()

    # Traversal check
    p = Path(path_param)
    if p.is_absolute() or ".." in p.parts:
        handler._send_json({"ok": False, "error": "Path traversal detected"}, 400)
        return

    target_path = (project_root / p).resolve()
    try:
        target_path.relative_to(project_root)
    except ValueError:
        handler._send_json({"ok": False, "error": "Path containment check failed"}, 400)
        return

    if not target_path.exists():
        handler._send_json({"ok": False, "error": "File not found"}, 404)
        return
    if not target_path.is_file():
        handler._send_json({"ok": False, "error": "Not a file"}, 400)
        return

    patterns = _load_gitignore(project_root)
    if _should_ignore_file(p, patterns):
        handler._send_json({"ok": False, "error": "Access denied (file is ignored)"}, 403)
        return

    # Size cap check: 1 MB limit
    SIZE_CAP = 1 * 1024 * 1024
    try:
        stat = target_path.stat()
        if stat.st_size > SIZE_CAP:
            handler._send_json({"ok": False, "error": f"File exceeds size limit of {SIZE_CAP} bytes"}, 400)
            return

        with open(target_path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        handler._send_json({
            "ok": True,
            "path": path_param,
            "content": content,
            "size": stat.st_size
        })
    except Exception as exc:
        handler._send_json({"ok": False, "error": f"Failed to read file: {exc}"}, 500)
        return


def handle_session_doc_roles(handler, path, body):
    # Read-only (v4 Wave 5): the per-lane ROLE→doc map for one
    # session (summarizer.session_doc_roles, Wave 3). The cockpit's
    # split-summary RIGHT column (.slinks) renders these role-tagged
    # links. Each href reuses the EXISTING /report and /artifact
    # routes; absent roles are simply omitted (never fabricated).
    # AUTH: ``?token=`` (read-only GET; back-compat when no token set).
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("pid", [""])[0] or "").strip()
    lane = (q.get("lane", [""])[0] or "").strip()
    session_id = (q.get("session", [""])[0] or "").strip()
    if not pid or not lane or not session_id:
        handler._send_json({"ok": False,
                         "error": "pid, lane, session required"}, 400)
    elif _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad pid"}, 400)
    elif _unsafe_path_seg(lane):
        handler._send_json({"ok": False, "error": "bad lane"}, 400)
    else:
        try:
            roles = _summarizer.session_doc_roles(
                pid, lane, session_id)
        except Exception:
            roles = {}
        handler._send_json({"ok": True, "roles": roles})


def handle_context_status(handler, path, body):
    # Read-only (v12 Wave 8): the live session's context-fullness
    # heuristic — the data behind the cockpit's "context getting full"
    # warn banner + one-click handoff. NO mutation, NO model call.
    # AUTH: ``?token=`` (read-only GET; back-compat when no token set).
    #   /api/rnd/context_status?session=<sid>
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    q = parse_qs(urlparse(handler.path).query)
    sid = (q.get("session", [""])[0]
           or q.get("session_id", [""])[0] or "").strip()
    if not sid:
        handler._send_json({"ok": False,
                         "error": "session required"}, 400)
    else:
        try:
            cf = _termsess.context_fullness(sid)
        except Exception:
            cf = {"ratio": 0.0, "over_threshold": False,
                  "observed_bytes": 0, "budget": 0}
        handler._send_json({
            "ok": True,
            "ratio": cf.get("ratio", 0.0),
            "over_threshold": bool(cf.get("over_threshold", False)),
            "observed_bytes": cf.get("observed_bytes", 0),
            "budget": cf.get("budget", 0),
        })


def handle_grass(handler, path, body):
    # Read-only (v5 Wave 5): the project's Grass ideas + their status
    # + versioned refinements, for the two-pane idea workbench. NO
    # mutation, NO model call. AUTH: ``?token=`` (read-only GET;
    # back-compat when no token set). Project-scoped (no cross-project
    # grass view). /api/rnd/grass?project_id=<id>
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("project_id", [""])[0]
           or q.get("pid", [""])[0]
           or q.get("id", [""])[0] or "").strip()
    if not pid:
        handler._send_json({"ok": False,
                         "error": "project_id required"}, 400)
    elif _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad pid"}, 400)
    else:
        proj = _rnd.get_project(pid)
        if proj is None:
            handler._send_json({"ok": False,
                             "error": "Unknown project"}, 404)
        else:
            folder = proj.get("folder_path", "")
            try:
                ideas = _eh.grass_workbench_data(folder, pid)
            except Exception:
                ideas = []
            handler._send_json({"ok": True, "ideas": ideas})


def handle_gandalf(handler, path, body):
    # Read-only (Gandalf v1): the project's Gandalf run history —
    # newest-first SAFE projections (verdict · chips · report/exec
    # rel paths; NEVER absolute paths). NO mutation, NO model call.
    # AUTH: ``?token=`` (read-only GET; back-compat when no token
    # set), mirroring /api/rnd/grass. Project-scoped.
    #   /api/rnd/gandalf?project_id=<id>
    # NOTE: this GET prefix must NOT match the POST /api/rnd/gandalf_run.
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("project_id", [""])[0]
           or q.get("pid", [""])[0]
           or q.get("id", [""])[0] or "").strip()
    if not pid:
        handler._send_json({"ok": False,
                         "error": "project_id required"}, 400)
    elif _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad pid"}, 400)
    else:
        proj = _rnd.get_project(pid)
        if proj is None:
            handler._send_json({"ok": False,
                             "error": "Unknown project"}, 404)
        else:
            folder = proj.get("folder_path", "")
            try:
                runs = _gandalf.list_runs(folder, pid)
            except Exception:
                runs = []
            handler._send_json({"ok": True, "runs": runs})


def handle_gandalf_status(handler, path, body):
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("project_id", [""])[0]
           or q.get("pid", [""])[0]
           or q.get("id", [""])[0] or "").strip()
    if not pid:
        handler._send_json({"ok": False, "error": "project_id required"}, 400)
    else:
        with _GANDALF_INFLIGHT_GUARD:
            rec = _GANDALF_INFLIGHT.get(pid, None)
            if isinstance(rec, dict):
                if time.time() - rec.get("ts", 0) > 1800:
                    _GANDALF_INFLIGHT.pop(pid, None)
                    status = None
                else:
                    status = rec.get("status")
            else:
                status = rec
        handler._send_json({"ok": True, "status": status})


def handle_gandalf_status_all(handler, path, body):
    # BULK in-flight status for ALL projects with a live Gandalf run —
    # one request the dashboard polls instead of N single-project
    # calls. Returns {ok, statuses:{project_id: status_string}} for
    # every project currently in-flight; finished/absent projects are
    # simply omitted. Mirrors the single endpoint's token gate, ok/err
    # envelope, and the >30-min staleness sweep.
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    statuses = {}
    now = time.time()
    with _GANDALF_INFLIGHT_GUARD:
        for _pid, rec in list(_GANDALF_INFLIGHT.items()):
            if isinstance(rec, dict):
                if now - rec.get("ts", 0) > 1800:
                    _GANDALF_INFLIGHT.pop(_pid, None)
                    continue
                st = rec.get("status")
            else:
                st = rec
            if st:
                statuses[_pid] = st
    handler._send_json({"ok": True, "statuses": statuses})


# Public same-origin mount for the ZH Node radar (Tailscale / remote safe).
_ZH_PROXY_PREFIX = "/api/rnd/zombie_hunter_proxy"


def _zh_extract_token(handler, qs=None):
    """Token from query or X-Anchor-Token (dashboard convention)."""
    try:
        if qs is None:
            qs = parse_qs(urlparse(getattr(handler, "path", "") or "").query or "")
        t = (qs.get("token") or [""])[0]
        if t:
            return str(t).strip()
    except Exception:
        pass
    try:
        return (handler.headers.get("X-Anchor-Token")
                or handler.headers.get("x-anchor-token") or "").strip()
    except Exception:
        return ""


def _zh_proxy_to_node(method, upstream_path, query="", headers=None, body=None, timeout=30):
    """Server-side fetch to 127.0.0.1:48484. Returns dict ok/status/headers/body."""
    import urllib.request
    import urllib.error
    q = f"?{query}" if query else ""
    url = f"{_zh_node_base()}{upstream_path}{q}"
    req_headers = dict(headers or {})
    # Never forward Host of the remote client
    req_headers.pop("Host", None)
    req_headers.pop("host", None)
    data = body if body is not None and method.upper() not in ("GET", "HEAD") else None
    req = urllib.request.Request(url, data=data, headers=req_headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return {
                "ok": True,
                "status": getattr(resp, "status", 200) or 200,
                "headers": {k: v for k, v in resp.headers.items()},
                "body": raw,
                "content_type": resp.headers.get("Content-Type") or "application/octet-stream",
            }
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
        except Exception:
            raw = b""
        return {
            "ok": False,
            "status": int(getattr(e, "code", 502) or 502),
            "headers": {},
            "body": raw,
            "content_type": e.headers.get("Content-Type") if e.headers else "text/plain",
            "error": str(e),
        }
    except Exception as e:
        return {
            "ok": False,
            "status": 502,
            "headers": {},
            "body": b"",
            "content_type": "text/plain",
            "error": str(e),
        }


def _zh_rewrite_html_for_proxy(html_text, token=""):
    """Rewrite Node radar HTML so browser stays on Anchor origin (Tailscale-safe)."""
    import re as _re
    text = html_text
    # Absolute loopback API → same-origin proxy mount
    text = _re.sub(
        r"https?://127\.0\.0\.1:\d+",
        _ZH_PROXY_PREFIX,
        text,
    )
    text = _re.sub(
        r"const API = ['\"][^'\"]+['\"]",
        f"const API = '{_ZH_PROXY_PREFIX}'",
        text,
        count=1,
    )
    if token:
        # Escape for JS single-quoted string
        safe = (
            str(token)
            .replace("\\", "\\\\")
            .replace("'", "\\'")
            .replace("\n", "")
            .replace("\r", "")
        )
        text = text.replace(
            "var ANCHOR_TOKEN='__ANCHOR_TOKEN__'",
            f"var ANCHOR_TOKEN='{safe}'",
        )
    return text


def handle_zombie_hunter_proxy(handler, path, body):
    """GET|POST /api/rnd/zombie_hunter_proxy/* — reverse-proxy to ZH Node on loopback.

    Same pattern as tidy_idy_proxy: browser stays same-origin with Anchor (works
    over Tailscale); Anchor fetches 127.0.0.1:48484 server-side.
    """
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return

    parsed = urlparse(path)
    if not parsed.path.startswith(_ZH_PROXY_PREFIX):
        handler._send_json({"ok": False, "error": "bad proxy path"}, 400)
        return
    rest = parsed.path[len(_ZH_PROXY_PREFIX):] or "/"
    if not rest.startswith("/"):
        rest = "/" + rest
    # Only allow path chars that the Node radar actually serves
    if ".." in rest or "\\" in rest:
        handler._send_json({"ok": False, "error": "bad path"}, 400)
        return

    _in_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    if not _in_pytest:
        try:
            _ensure_zh_node_server(wait_s=8.0)
        except Exception:
            pass
    if not _zh_node_is_up(timeout=1.5):
        handler._send_json(
            {"ok": False, "error": "Zombie Hunter Node radar is not running on the Anchor host",
             "code": "zh-upstream-down"},
            502,
        )
        return

    method = (getattr(handler, "command", None) or "GET").upper()
    raw_body = None
    if method in ("POST", "PUT", "PATCH") and body is not None:
        if isinstance(body, (bytes, bytearray)):
            raw_body = bytes(body)
        else:
            raw_body = json.dumps(body).encode("utf-8")

    fwd = {"Accept": handler.headers.get("Accept") or "*/*"}
    ctype = handler.headers.get("Content-Type")
    if ctype:
        fwd["Content-Type"] = ctype
    elif raw_body is not None:
        fwd["Content-Type"] = "application/json"

    result = _zh_proxy_to_node(
        method, rest, query=parsed.query or "", headers=fwd, body=raw_body,
        timeout=60 if rest.startswith("/api/sweep") else 30,
    )
    status = int(result.get("status") or 502)
    payload = result.get("body") or b""
    ctype_out = result.get("content_type") or "application/octet-stream"

    # Rewrite HTML so assets/API stay on the proxy
    if isinstance(payload, (bytes, bytearray)) and "text/html" in (ctype_out or ""):
        try:
            token = _zh_extract_token(handler)
            text = payload.decode("utf-8", errors="replace")
            text = _zh_rewrite_html_for_proxy(text, token=token)
            payload = text.encode("utf-8")
            ctype_out = "text/html; charset=utf-8"
        except Exception as e:
            _logger.warning("zh_proxy: HTML rewrite failed: %s", e)

    try:
        handler.send_response(status)
        handler.send_header("Content-Type", ctype_out)
        handler.send_header("Content-Length", str(len(payload)))
        handler.send_header("Cache-Control", "no-store")
        # CORS not needed same-origin; allow for belt-and-suspenders
        handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        if payload:
            handler.wfile.write(payload)
    except Exception as e:
        _logger.warning("zh_proxy: write failed: %s", e)


def handle_zombie_hunter_report(handler, path, body):
    # Auth gate (defense-in-depth): the radar report exposes process
    # metadata (PIDs / session ids). Token-gated like the other
    # read-API GET routes; a no-op when ANCHOR_TOKEN is unset (local
    # single-user), enforced in remote mode. The dashboard button
    # passes ?token= via _anchorToken().
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    import zombie_hunter
    import reaper
    import pty_manager
    import subprocess
    # NOTE: do NOT import json/sys/os/datetime function-locally here —
    # they are module-global (top of file). A function-local import
    # makes the name local to the ENTIRE do_GET method, so an earlier
    # branch referencing it before this line raises UnboundLocalError
    # -> a 500 on every page load. (rearch W8: the shadowing class is
    # structurally eliminated — route_import_scan proves it stays 0.)
    #
    # Operator path: prefer Node multi-engine radar, served via SAME-ORIGIN
    # reverse proxy (works over Tailscale). Never redirect the browser to
    # 127.0.0.1 — that is the host machine, not the remote client.
    # Pure-Python Cached Sweep Report is FALLBACK when Node is down.
    # Query ?legacy=1 forces the Python report.
    try:
        _qs = parse_qs(urlparse(getattr(handler, "path", "") or "").query or "")
        _force_legacy = str((_qs.get("legacy") or ["0"])[0]).strip() in ("1", "true", "yes")
        _tok = _zh_extract_token(handler, _qs)
    except Exception:
        _force_legacy = False
        _tok = ""
    # Never auto-spawn Node under pytest (frozen UX tests assert the Python HTML).
    _in_pytest = bool(os.environ.get("PYTEST_CURRENT_TEST"))
    if not _force_legacy and not _in_pytest:
        try:
            if _ensure_zh_node_server(wait_s=10.0) and _zh_node_is_up(timeout=1.5):
                # Same-origin proxy to Node HTML (Tailscale-safe).
                q = f"?token={url_quote(_tok)}" if _tok else ""
                handler.send_response(302)
                handler.send_header("Location", f"{_ZH_PROXY_PREFIX}/{q}")
                handler.send_header("Cache-Control", "no-store")
                handler.end_headers()
                return
        except Exception as _zh_exc:
            _logger.warning("zombie_hunter_report: Node radar unavailable (%s) — Python fallback",
                            _zh_exc)

    # Check if zombie_hunter_last.json exists and is not stale (within 60 seconds)
    report_path = zombie_hunter._last_report_path()
    is_stale = True
    report_data = None

    if report_path.exists():
        try:
            report_data = json.loads(report_path.read_text("utf-8"))
            swept_at = report_data.get("swept_at", 0)
            mtime = report_path.stat().st_mtime
            now = time.time()
            if abs(now - mtime) < 60 and abs(now - swept_at) < 60:
                is_stale = False
        except Exception:
            is_stale = True

    # Observe phase: classify processes using the dry-run sweep (apply=False).
    # This is read-only (NO kills, NO registry updates) and writes/refreshes
    # zombie_hunter_last.json. Only refresh a STALE-but-PRESENT report; when the
    # report file is ABSENT we deliberately fall through to the live-process
    # fallback below (do NOT synthesize a cached report), so a fresh install with
    # no daemon sweep yet still shows real OS processes.
    if is_stale and report_path.exists():
        try:
            live_ids = pty_manager.live_sessions()
            report = zombie_hunter.sweep(live_session_ids=live_ids, apply=False)
            zombie_hunter._persist_report(report)
            report_data = report
            is_stale = False
        except Exception:
            pass

    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.end_headers()

    html = "<html><head><title>Zombie Hunter Report</title>"
    html += "<style>"
    html += "body { font-family: system-ui, -apple-system, sans-serif; background: #0a0a0c; color: #e4e4e7; padding: 30px; margin: 0; }"
    html += ".container { max-width: 900px; margin: 0 auto; background: #18181b; border: 1px solid #27272a; border-radius: 8px; padding: 24px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1), 0 2px 4px -1px rgba(0,0,0,0.06); }"
    html += "h1 { margin-top: 0; color: #fafafa; font-size: 24px; display: flex; align-items: center; gap: 10px; border-bottom: 1px solid #27272a; padding-bottom: 12px; }"
    html += "h2 { color: #f4f4f5; font-size: 18px; margin-top: 24px; margin-bottom: 12px; }"
    html += "table { width: 100%; border-collapse: collapse; margin-top: 8px; margin-bottom: 16px; }"
    html += "th { background: #27272a; color: #a1a1aa; font-weight: 500; text-align: left; padding: 10px 12px; font-size: 14px; border-bottom: 2px solid #3f3f46; }"
    html += "td { padding: 10px 12px; border-bottom: 1px solid #27272a; font-size: 14px; color: #d4d4d8; }"
    html += ".badge { display: inline-block; padding: 2px 6px; border-radius: 4px; font-size: 12px; font-weight: 600; }"
    html += ".badge-info { background: #1e3a8a; color: #93c5fd; }"
    html += ".badge-warning { background: #78350f; color: #fde047; }"
    html += ".badge-danger { background: #7f1d1d; color: #fca5a5; }"
    html += ".badge-success { background: #064e3b; color: #6ee7b7; }"
    html += ".badge-secondary { background: #27272a; color: #d4d4d8; }"
    html += "pre { font-family: monospace; font-size: 13px; background: #09090b; padding: 16px; border: 1px solid #27272a; border-radius: 6px; overflow-x: auto; max-height: 500px; color: #4ade80; }"
    html += ".meta { font-size: 13px; color: #71717a; margin-bottom: 20px; display: flex; justify-content: space-between; align-items: center; background: #202024; padding: 10px 16px; border-radius: 6px; }"
    html += ".meta-label { font-weight: bold; color: #a1a1aa; }"
    html += "</style></head><body>"
    html += "<div class='container'>"
    html += "<h1><img src=\"/vendor/brand/zombie-hunter-radar.jpg\" style=\"width:32px;height:32px;border-radius:6px;vertical-align:middle;\" /> Zombie Hunter Radar</h1>"

    if not is_stale and report_data:
        swept_time_str = datetime.fromtimestamp(report_data.get("swept_at", 0)).strftime("%Y-%m-%d %H:%M:%S")
        html += f"<div class='meta'>"
        html += f"<div><span class='meta-label'>Source:</span> <span class='badge badge-success'>Cached Sweep Report</span></div>"
        html += f"<div><span class='meta-label'>Swept At:</span> {swept_time_str}</div>"
        html += f"</div>"

        html += "<h2>Sweep Status Summary</h2>"
        html += "<table>"
        html += "<tr><th>Category</th><th>Count</th><th>Description</th></tr>"

        killed_cnt = len(report_data.get("killed", []))
        alive_cnt = len(report_data.get("alive", []))
        abst_cnt = len(report_data.get("abstained", []))
        reap_d_cnt = len(report_data.get("reaped_dead", []))
        reap_r_cnt = len(report_data.get("reaped_recycled", []))

        html += f"<tr><td><span class='badge badge-danger'>Orphaned (Pending Kill)</span></td><td>{killed_cnt}</td><td>Process is ours, running, but no longer attached.</td></tr>"
        html += f"<tr><td><span class='badge badge-success'>Alive (Attached)</span></td><td>{alive_cnt}</td><td>Process is ours, running, and actively attached.</td></tr>"
        html += f"<tr><td><span class='badge badge-warning'>Abstained (Manual Review)</span></td><td>{abst_cnt}</td><td>Identity missing or incomplete. Never auto-killed.</td></tr>"
        html += f"<tr><td><span class='badge badge-secondary'>Reaped (Dead)</span></td><td>{reap_d_cnt}</td><td>Process exited naturally. Registry updated.</td></tr>"
        html += f"<tr><td><span class='badge badge-secondary'>Reaped (Recycled PID)</span></td><td>{reap_r_cnt}</td><td>PID recycled by another process. Registry updated, new process spared.</td></tr>"
        html += "</table>"

        # Detail lists if any
        for cat_name, cat_list, badge_class in [
            ("Orphaned (Pending Kill) Session IDs", report_data.get("killed", []), "badge-danger"),
            ("Active/Attached Session IDs", report_data.get("alive", []), "badge-success"),
            ("Abstained Session IDs", report_data.get("abstained", []), "badge-warning")
        ]:
            if cat_list:
                html += f"<h2>{cat_name}</h2>"
                html += "<ul>"
                for sid in cat_list:
                    html += f"<li><code>{sid}</code></li>"
                html += "</ul>"
    else:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        html += f"<div class='meta'>"
        html += f"<div><span class='meta-label'>Source:</span> <span class='badge badge-warning'>Live Process Query Fallback</span></div>"
        html += f"<div><span class='meta-label'>Query Time:</span> {now_str} (Sweep report stale or absent)</div>"
        html += f"</div>"

        html += "<h2>System Process List</h2>"
        cmd_output = ""
        try:
            if sys.platform.startswith("win"):
                creationflags = 0x08000000  # CREATE_NO_WINDOW
                res = subprocess.run(["tasklist"], capture_output=True, text=True, creationflags=creationflags, timeout=10)
                cmd_output = res.stdout
            else:
                res = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=10)
                cmd_output = res.stdout
        except Exception as e:
            cmd_output = f"Error running fallback process query: {e}"

        html += f"<pre>{html_lib.escape(cmd_output)}</pre>"

    # ── Swarm & Owner View ────────────────────────────────────────
    # NOTE: _sessreg / _rnd are the MODULE-LEVEL aliases (imported at top).
    # Do NOT re-import them locally here — a local `import ... as _rnd`
    # makes _rnd function-local for ALL of do_GET, breaking earlier routes
    # in this method with UnboundLocalError.
    try:
        attached = set(pty_manager.live_sessions())
    except Exception:
        attached = set()

    running_records = []
    try:
        running_records = _sessreg.list_sessions(status="running")
    except Exception:
        pass

    # (#3, single source) This view marks orphans AND FREEZES them
    # (pause_orphan). Build the ONE immutable snapshot for this sweep
    # and classify against it (the shared provider) so a legit
    # work-doing session with no open stream is never frozen/killed:
    # an orphan has NO live owner (not job-owned, not parent-owned),
    # not merely "no attached PTY stream".
    try:
        _snap = reaper.build_snapshot(attached_pty_ids=attached, records=running_records,
                                      enumerate_pids=reaper.enumerate_live_pids)
        live_ids = reaper.live_owner_ids(_snap)
    except Exception:
        _snap = None
        live_ids = attached

    # Group by OWNER (project title, or project_id, or "(unowned)")
    groups = {}
    for rec in running_records:
        proj_id = rec.get("project_id", "")
        if proj_id:
            proj = _rnd.get_project(proj_id)
            owner = proj.get("name") if (proj and proj.get("name")) else proj_id
        else:
            owner = "(unowned)"

        if owner not in groups:
            groups[owner] = []
        groups[owner].append(rec)

    # Add new section Swarm & Owner View
    html += "<h2>Swarm & Owner View</h2>"
    html += "<style>"
    html += ".btn-kill { background: #7f1d1d; color: #fca5a5; border: 1px solid #b91c1c; border-radius: 4px; padding: 4px 8px; font-size: 11px; cursor: pointer; font-weight: 600; transition: background 0.2s; margin-left: 8px; }"
    html += ".btn-kill:hover { background: #991b1b; }"
    html += ".btn-kill:disabled { background: #27272a; color: #71717a; border-color: #3f3f46; cursor: not-allowed; }"
    html += ".btn-resume { background: #064e3b; color: #6ee7b7; border: 1px solid #059669; border-radius: 4px; padding: 4px 8px; font-size: 11px; cursor: pointer; font-weight: 600; transition: background 0.2s; margin-left: 6px; }"
    html += ".btn-resume:hover { background: #065f46; }"
    html += ".btn-resume:disabled { background: #27272a; color: #71717a; border-color: #3f3f46; cursor: not-allowed; }"
    html += ".btn-start { background: #1e3a8a; color: #93c5fd; border: 1px solid #2563eb; border-radius: 4px; padding: 6px 12px; font-size: 12px; cursor: pointer; font-weight: 600; transition: background 0.2s; }"
    html += ".btn-start:hover { background: #1e40af; }"
    html += ".btn-start:disabled { background: #27272a; color: #71717a; border-color: #3f3f46; cursor: not-allowed; }"
    html += ".owner-heading { color: #f4f4f5; font-size: 16px; margin-top: 20px; margin-bottom: 8px; padding-bottom: 4px; border-bottom: 1px solid #27272a; font-weight: bold; }"
    html += "</style>"

    if not running_records:
        html += "<p style='color: #a1a1aa; font-style: italic;'>No active swarms or sessions.</p>"
    else:
        sorted_owners = sorted(groups.keys(), key=lambda o: (o == "(unowned)", o.lower()))
        for owner in sorted_owners:
            html += f"<div class='owner-heading'>Owner: {html_lib.escape(owner)}</div>"
            html += "<table>"
            html += "<thead><tr><th>Swarm/Lane</th><th>Session</th><th>PID</th><th>Backend</th><th>Status</th><th>State</th></tr></thead>"
            html += "<tbody>"
            for rec in groups[owner]:
                sid = rec.get("session_id", "")
                short_sid = sid[:8]
                lane = rec.get("lane", "")
                pid = rec.get("pid")
                pid_str = str(pid) if pid is not None else ""
                backend = rec.get("backend", "")
                status = rec.get("status", "")

                try:
                    is_orphaned = (reaper.classify_record(rec, _snap) == "kill")
                except Exception:
                    # Defensive boundary (Wave 2, criterion 1): a
                    # fault NEVER freezes — treat as OWNED/alive so
                    # pause_orphan can't freeze a legit session.
                    is_orphaned = False

                if is_orphaned:
                    # FREEZE the orphan while it waits to be killed so
                    # it stops burning CPU (pytest-guarded inside).
                    paused = False
                    try:
                        paused = zombie_hunter.pause_orphan(pid)
                    except Exception:
                        paused = False
                    pause_badge = ("<span class='badge badge-warning' title='Process frozen while it waits to be killed'>Paused</span> "
                                   if paused else "")
                    resume_btn = (f" <button class='btn-resume' onclick=\"resumeSession('{sid}', this)\">Resume</button>"
                                  if paused else "")
                    state_html = (
                        f"<span class='badge badge-danger'>Orphaned</span> {pause_badge}"
                        f"<button class='btn-kill' onclick=\"killSession('{sid}', this)\">Kill</button>{resume_btn}")
                else:
                    state_html = (
                        "<span class='badge badge-success'>Attached</span> "
                        f"<button class='btn-kill' onclick=\"killSession('{sid}', this)\">Kill</button>")

                html += f"<tr id='row-{sid}'>"
                html += f"<td>{html_lib.escape(lane)}</td>"
                html += f"<td title='{html_lib.escape(sid)}'><code>{html_lib.escape(short_sid)}</code></td>"
                html += f"<td>{html_lib.escape(pid_str)}</td>"
                html += f"<td><code>{html_lib.escape(backend)}</code></td>"
                html += f"<td><span class='badge badge-success'>{html_lib.escape(status)}</span></td>"
                html += f"<td>{state_html}</td>"
                html += "</tr>"
            html += "</tbody>"
            html += "</table>"

    html += "<script>"
    html += """
function getAnchorToken() {
  try {
    const params = new URLSearchParams(window.location.search);
    const tok = params.get('token');
    if (tok) return tok;
  } catch(e) {}
  try {
    return localStorage.getItem('anchor_token') || '';
  } catch(e) {
    return '';
  }
}
function killSession(sessionId, btn) {
  if (!confirm("Are you sure you want to kill session " + sessionId + "?")) {
    return;
  }
  btn.disabled = true;
  btn.innerText = "Killing...";

  const token = getAnchorToken();
  const headers = {
    'Content-Type': 'application/json'
  };
  if (token) {
    headers['X-Anchor-Token'] = token;
  }

  const payload = {
    session_id: sessionId
  };
  if (token) {
    payload.token = token;
  }

  fetch('/api/rnd/zombie_kill', {
    method: 'POST',
    headers: headers,
    body: JSON.stringify(payload)
  })
  .then(response => {
    if (response.ok) {
      return response.json();
    }
    throw new Error("HTTP error " + response.status);
  })
  .then(data => {
    if (data.ok) {
      btn.innerText = "Killed";
      btn.className = "badge badge-secondary";
      btn.style.border = "none";
      btn.disabled = true;
      const row = document.getElementById("row-" + sessionId);
      if (row) {
        row.style.transition = "opacity 0.5s ease";
        row.style.opacity = "0";
        setTimeout(function () { if (row && row.parentNode) row.parentNode.removeChild(row); }, 550);
      }
    } else {
      alert("Failed to kill session: " + (data.error || "unknown error"));
      btn.disabled = false;
      btn.innerText = "Kill";
    }
  })
  .catch(err => {
    alert("Error communicating with server: " + err.message);
    btn.disabled = false;
    btn.innerText = "Kill";
  });
}
function resumeSession(sessionId, btn) {
  btn.disabled = true;
  btn.innerText = "Resuming...";
  const token = getAnchorToken();
  const headers = { 'Content-Type': 'application/json' };
  if (token) { headers['X-Anchor-Token'] = token; }
  const payload = { session_id: sessionId };
  if (token) { payload.token = token; }
  fetch('/api/rnd/zombie_resume', {
    method: 'POST', headers: headers, body: JSON.stringify(payload)
  })
  .then(response => { if (response.ok) return response.json(); throw new Error("HTTP error " + response.status); })
  .then(data => {
    if (data.ok) {
      btn.innerText = "Resumed";
      btn.disabled = true;
      btn.className = "badge badge-secondary";
      btn.style.border = "none";
    } else {
      alert("Failed to resume session: " + (data.error || "unknown error"));
      btn.disabled = false;
      btn.innerText = "Resume";
    }
  })
  .catch(err => {
    alert("Error communicating with server: " + err.message);
    btn.disabled = false;
    btn.innerText = "Resume";
  });
}
var ZH_ENG = 'claude';
var ZH_ENG_HEALTH = { claude: true, gemini: true, grok: true };
function paintZhEng() {
  ['claude','gemini','grok'].forEach(function(e) {
    var el = document.getElementById('zh-eng-' + e);
    if (!el) return;
    var ok = ZH_ENG_HEALTH[e] !== false;
    el.disabled = !ok;
    el.style.opacity = ok ? '1' : '0.45';
    el.style.outline = (ZH_ENG === e) ? '1px solid #6c9cfc' : 'none';
  });
  var h = document.getElementById('zh-eng-health');
  if (h) h.textContent = ZH_ENG_HEALTH[ZH_ENG] === false
    ? (ZH_ENG + ' unavailable') : (ZH_ENG + ' · slim seed · async start');
}
function setZhEng(e) {
  if (ZH_ENG_HEALTH[e] === false) return;
  ZH_ENG = e;
  paintZhEng();
}
function loadZhEngines() {
  const token = getAnchorToken();
  const headers = {};
  if (token) headers['X-Anchor-Token'] = token;
  const q = token ? ('?token=' + encodeURIComponent(token)) : '';
  fetch('/api/zh/engines' + q, { headers: headers })
    .then(function(r) { return r.json(); })
    .then(function(j) {
      if (j && j.engines) {
        j.engines.forEach(function(row) { ZH_ENG_HEALTH[row.id] = !!row.enabled; });
        if (j.defaultEngine) ZH_ENG = j.defaultEngine;
      }
      paintZhEng();
    })
    .catch(function() { paintZhEng(); });
}
function startZombieTerminal(btn) {
  if (ZH_ENG_HEALTH[ZH_ENG] === false) {
    alert(ZH_ENG + ' is disabled (unhealthy). Pick another engine.');
    return;
  }
  btn.disabled = true;
  btn.innerText = "Starting…";

  const token = getAnchorToken();
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers['X-Anchor-Token'] = token;

  const payload = { backend: ZH_ENG, slim: true };
  if (token) payload.token = token;

  fetch('/api/rnd/zombie_terminal_start', {
    method: 'POST',
    headers: headers,
    body: JSON.stringify(payload)
  })
  .then(response => {
    if (response.ok) return response.json();
    throw new Error("HTTP error " + response.status);
  })
  .then(data => {
    if (data.ok && data.session_id) {
      const iframe = document.getElementById('terminal-iframe');
      const placeholder = document.getElementById('terminal-placeholder');
      const tokenQuery = token ? ('&token=' + encodeURIComponent(token)) : '';
      iframe.src = '/zombie_terminal?session=' + encodeURIComponent(data.session_id) + tokenQuery;
      placeholder.style.display = 'none';
      iframe.style.display = 'block';
    } else {
      alert("Failed (non-blocking): " + (data.error || "unknown error"));
      btn.disabled = false;
      btn.innerText = "Start Terminal";
    }
  })
  .catch(err => {
    alert("Error (non-blocking): " + err.message);
    btn.disabled = false;
    btn.innerText = "Start Terminal";
  });
}
document.addEventListener('DOMContentLoaded', loadZhEngines);
"""
    html += "</script>"

    html += "<h2>Zombie-Hunter Terminal</h2>"
    html += "<div id='terminal-container' style='background:#0c0e14; border:1px solid #27272a; border-radius:8px; padding:16px; margin-top:12px; margin-bottom:24px; min-height:100px; display:flex; flex-direction:column; align-items:center; justify-content:center;'>"
    html += "  <div id='terminal-placeholder' style='text-align:center;'>"
    html += "    <p style='color:#a1a1aa; font-size:14px; margin-bottom:12px;'>Shell-first Investigate (W8/SC5): pick Claude / Gemini / Grok, then start with a slim seed (async — no multi-minute blank wait).</p>"
    html += "    <div style='display:flex;gap:8px;justify-content:center;flex-wrap:wrap;margin-bottom:12px;'>"
    html += "      <button class='btn-start' id='zh-eng-claude' onclick='setZhEng(\"claude\")'>Claude</button>"
    html += "      <button class='btn-start' id='zh-eng-gemini' onclick='setZhEng(\"gemini\")'>Gemini</button>"
    html += "      <button class='btn-start' id='zh-eng-grok' onclick='setZhEng(\"grok\")'>Grok</button>"
    html += "    </div>"
    html += "    <div id='zh-eng-health' style='color:#71717a;font-size:12px;margin-bottom:10px;'>loading engines…</div>"
    html += "    <button class='btn-start' onclick='startZombieTerminal(this)'>Start Terminal (slim seed)</button>"
    html += "  </div>"
    html += "  <iframe id='terminal-iframe' style='width:100%; height:450px; border:none; display:none; border-radius:6px;'></iframe>"
    html += "</div>"

    # Wave 1 (#12a): bounded LIVE auto-refresh of the radar so it
    # updates during a sweep WITHOUT a manual reload. Bounded by
    # ZOMBIE_MAX_TICKS so it never churns forever; it SKIPS the
    # reload while the investigation terminal is open (so an active
    # session is never nuked) and while the tab is hidden.
    html += "<script id='zombie-auto-refresh'>"
    html += """
(function () {
  var ZOMBIE_REFRESH_MS = 6000;   // poll cadence
  var ZOMBIE_MAX_TICKS = 100;     // bounded: ~10 min then stop
  var ticks = 0;
  var timer = setInterval(function () {
    ticks += 1;
    if (ticks > ZOMBIE_MAX_TICKS) { clearInterval(timer); return; }
    var iframe = document.getElementById('terminal-iframe');
    if (iframe && iframe.style.display !== 'none') { return; }  // terminal open -> skip
    if (document.hidden) { return; }                            // tab hidden  -> skip
    window.location.reload();
  }, ZOMBIE_REFRESH_MS);
})();
"""
    html += "</script>"

    html += "</div></body></html>"
    handler.wfile.write(html.encode("utf-8"))
    return


def handle_zombie_terminal(handler, path, body):
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    q = parse_qs(urlparse(handler.path).query)
    sid = (q.get("session", [""])[0] or "").strip()
    token = (q.get("token", [""])[0] or "").strip()

    handler.send_response(200)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.end_headers()

    html = """<!DOCTYPE html>
<html>
<head>
  <title>Zombie Hunter Terminal</title>
  <link rel="stylesheet" href="/vendor/xterm/xterm.css" />
  <script src="/vendor/xterm/xterm.js"></script>
  <style>
    body {
      background: #0c0e14;
      margin: 0;
      padding: 0;
      width: 100vw;
      height: 100vh;
      overflow: hidden;
    }
    #terminal {
      width: 100%;
      height: 100%;
    }
  </style>
</head>
<body>
  <div id="terminal"></div>
  <script>
    (function() {
      const params = new URLSearchParams(window.location.search);
      const sessionId = params.get('session');
      const token = params.get('token') || '';

      if (!sessionId) {
        document.getElementById('terminal').textContent = 'Error: session parameter required';
        return;
      }

      const term = new Terminal({
        convertEol: true,
        fontSize: 12,
        theme: { background: '#0c0e14' },
        scrollback: 5000
      });
      term.open(document.getElementById('terminal'));

      function fitTerminal() {
        const cols = Math.floor(window.innerWidth / 7.2) || 80;
        const rows = Math.floor(window.innerHeight / 17) || 24;
        term.resize(cols, rows);

        const headers = { 'Content-Type': 'application/json' };
        if (token) headers['X-Anchor-Token'] = token;

        const body = { session: sessionId, cols: cols, rows: rows };
        if (token) body.token = token;

        fetch('/api/rnd/term_resize', {
          method: 'POST',
          headers: headers,
          body: JSON.stringify(body)
        }).catch(err => console.error('resize error:', err));
      }

      window.addEventListener('resize', fitTerminal);
      setTimeout(fitTerminal, 100);

      // Ordering fix (2026-07-08): keystrokes used to fire independent, racing
      // POSTs (browser parallel connections + threaded server) → muddled typing.
      // Prefer the ordered WebSocket (single FIFO stream applied to the PTY in
      // frame order by the one server pump); fall back to a PROMISE-CHAINED POST
      // queue (one term_input2 POST in flight at a time) when the WS isn't OPEN.
      let activeWs = null;
      let _sendChain = Promise.resolve();
      function _sendInput(d) {
        if (d === '' || d == null) return;
        if (activeWs && activeWs.readyState === 1 /* OPEN */) {
          try { activeWs.send(d); return; } catch (e) { /* fall through */ }
        }
        const headers = { 'Content-Type': 'application/json' };
        if (token) headers['X-Anchor-Token'] = token;
        const body = { session: sessionId, data: d };
        if (token) body.token = token;
        _sendChain = _sendChain.then(function () {
          return fetch('/api/rnd/term_input2', {
            method: 'POST', headers: headers, body: JSON.stringify(body)
          });
        }).catch(err => console.error('input error:', err));
      }
      term.onData(function (d) { _sendInput(d); });

      const tq = token ? ('&token=' + encodeURIComponent(token)) : '';
      const wsProto = (location.protocol === 'https:') ? 'wss:' : 'ws:';
      const wsUrl = wsProto + '//' + location.host + '/api/rnd/term_ws?session=' + encodeURIComponent(sessionId) + tq;

      let sseStarted = false;
      function startSSE() {
        if (sseStarted) return;
        sseStarted = true;
        const sseUrl = '/api/rnd/term_stream2?session=' + encodeURIComponent(sessionId) + tq;
        const es = new EventSource(sseUrl);
        es.addEventListener('output', function (ev) {
          try {
            const p = JSON.parse(ev.data);
            if (p.text) term.write(p.text);
          } catch (e) {}
        });
        es.addEventListener('done', function () {
          try { es.close(); } catch (e) {}
        });
      }

      try {
        const ws = new WebSocket(wsUrl);
        activeWs = ws;  // ordered input channel (see _sendInput above)
        ws.onmessage = function (ev) { term.write(ev.data); };
        ws.onclose = function () {
          activeWs = null;
          if (!sseStarted) startSSE();
        };
        ws.onerror = function () {
          activeWs = null;
          try { ws.close(); } catch (e) {}
          startSSE();
        };
      } catch (e) {
        activeWs = null;
        startSSE();
      }
    })();
  </script>
</body>
</html>"""
    handler.wfile.write(html.encode("utf-8"))


def handle_board_html(handler, path, body):
    # Read-only (v7 Wave 6): the project's rendered 5-lane board
    # FRAGMENT, so an already-open project window can refresh the
    # board IN PLACE after a session-lifecycle mutation (start /
    # finish / advance / promote / develop) and the lane-column
    # tile appears WITHOUT a full page reload. REUSES
    # _render_kanban_html (the SAME server render the page used) —
    # the board is the single source of truth, so the JS just
    # re-fetches it (no duplicate JS-injected tile; dedupe stays
    # correct = exactly one tile per session in its lane). SAFE: the
    # kanban render already emits SAFE tiles (no absolute
    # worktree_path / branch). AUTH: ``?token=`` (read-only GET;
    # back-compat when no token configured), consistent with the
    # other ?token= GET seams. /api/rnd/board_html?project_id=<id>
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("project_id", [""])[0] or "").strip()
    entry = _rnd.get_project(pid) if pid else None
    if not pid or entry is None:
        handler._send_json({"ok": False,
                         "error": "unknown project"}, 404)
        return
    folder_raw = entry.get("folder_path", "")
    try:
        # v12 Wave 2: the in-place refresh fragment is now the
        # Layout-D board (the SAME render the page emits), so a
        # refreshBoard() swap keeps the headline/shelf structure.
        frag = _render_layoutd_html(folder_raw, pid)
    except Exception:
        frag = ("<div class='pgrid layoutd'><p class='rnd-empty'>"
                "Board unavailable.</p></div>")
    handler._send_json({"ok": True, "html": frag})


def handle_handoff_proposal(handler, path, body):
    # Read-only stage-handoff PROPOSAL (v3 Wave 7): the UI shows
    # "execute on this plan set?" BEFORE launching a build session.
    # Pure metadata (structure-only, no contents) — read endpoint,
    # consistent with the other read GETs (no token required).
    # /api/rnd/handoff_proposal?project_id=<id>&lane=build[&seed_session=<sid>]
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("project_id", [""])[0]
           or q.get("id", [""])[0] or "").strip()
    lane = (q.get("lane", ["build"])[0] or "build").strip()
    seed = (q.get("seed_session", [""])[0] or "").strip() or None
    if not pid:
        handler._send_json({"ok": False,
                         "error": "project_id required"}, 400)
    elif _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad pid"}, 400)
    elif _unsafe_path_seg(lane):
        handler._send_json({"ok": False, "error": "bad lane"}, 400)
    elif seed and _unsafe_path_seg(seed):
        handler._send_json({"ok": False, "error": "bad seed"}, 400)
    else:
        proj = _rnd.get_project(pid)
        if proj is None:
            handler._send_json({"ok": False,
                             "error": "Unknown project"}, 404)
        else:
            folder = proj.get("folder_path", "")
            try:
                prop = _handoff.propose_handoff(
                    folder, pid, lane, source_session_id=seed)
            except Exception:
                prop = {"has_plan_set": False}
            handler._send_json({"ok": True, **prop})


def handle_session_summary(handler, path, body):
    # Read-only structured SESSION summary as JSON (v3 Wave 6): the
    # in-place accordion fetches this instead of navigating to the
    # /summary page. If cached → return it. If NOT cached → kick off
    # background generation (run-once, runner seam) and return a
    # {status:"generating"} fallback so the panel can re-fetch. This
    # NEVER runs the model synchronously on the request thread.
    # /api/rnd/session_summary?pid=<id>&lane=<lane>&session=<sid>
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("pid", [""])[0] or "").strip()
    lane = (q.get("lane", [""])[0] or "").strip()
    session_id = (q.get("session", [""])[0] or "").strip()
    if not pid or not lane or not session_id:
        handler._send_json({"ok": False,
                         "error": "pid, lane, session required"}, 400)
    elif _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad pid"}, 400)
    elif _unsafe_path_seg(lane):
        handler._send_json({"ok": False, "error": "bad lane"}, 400)
    else:
        proj = _rnd.get_project(pid)
        folder = (proj or {}).get("folder_path", "")
        store_lane = _eh._resolve_subdir(lane)
        cached = None
        try:
            cached = _summarizer.load_cached(
                folder, pid, store_lane, session_id)
        except Exception:
            cached = None
        if isinstance(cached, dict) and not cached.get("error"):
            handler._send_json({"ok": True, "status": "ready",
                             "summary": cached})
        elif proj is None:
            # Unknown / unregistered project → TERMINAL status so a
            # polling panel STOPS (never an endless "generating").
            handler._send_json({"ok": True, "status": "unknown"})
        else:
            # Not cached (or a prior failed/uncached run): resolve the
            # session so generation can seed from its members. v8 Wave
            # 5 — a killed managed session's produced docs are persisted
            # tagged with its id (they GROUP elsewhere in list_sessions),
            # so resolve via _resolve_finished_session which TIES the
            # managed id to those exact docs. Unresolvable → TERMINAL
            # "unknown" (the panel stops polling); else kick off
            # background generation run-once and tell the panel to poll.
            session = None
            try:
                session = _resolve_finished_session(
                    folder, pid, lane, session_id)
            except Exception:
                session = None
            if session is None:
                handler._send_json({"ok": True, "status": "unknown"})
            else:
                _trigger_session_summary(
                    folder, pid, lane, session)
                handler._send_json({"ok": True, "status": "generating"})


def handle_session_narration(handler, path, body):
    # Read-only Layer-1 WARM NARRATION data (telemetry-resume W3): the
    # deterministic narration spine (done / produced / next) for ONE session
    # tile, rendered in the session-window terminal chrome as the first-click
    # 'warm terminal that narrates'. PURE render off durable local data —
    # NO PTY spawn, NO synchronous model call, NO network. Cites the North
    # Star amendment (click contract · first-click sentence · narration floor ·
    # endpoint auth rule).
    #
    # Lazy enrichment (the CHOSEN narration-floor path): the floor is ALWAYS
    # returned immediately; when the session has no cached summary yet, the
    # first open triggers the EXISTING v3 background generation (unmodified) and
    # the view carries an ``enrichment='generating'`` badge — a badge OVER
    # content, never a spinner instead of content. A failed/absent generation
    # leaves the floor standing (no loop; a later open may retry once).
    #
    # AUTH: ``?token=`` (401-before-substance, like session_summary /
    # session_doc_roles). The strangler applies the row's token gate FIRST; this
    # in-handler check is the belt-and-braces second line.
    #   /api/rnd/session_narration?pid=<id>&lane=<lane>&session=<sid>
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("pid", [""])[0] or "").strip()
    lane = (q.get("lane", [""])[0] or "").strip()
    session_id = (q.get("session", [""])[0] or "").strip()
    if not pid or not lane or not session_id:
        handler._send_json({"ok": False,
                         "error": "pid, lane, session required"}, 400)
        return
    if _unsafe_path_seg(pid):
        handler._send_json({"ok": False, "error": "bad pid"}, 400)
        return
    if _unsafe_path_seg(lane):
        handler._send_json({"ok": False, "error": "bad lane"}, 400)
        return
    proj = _rnd.get_project(pid)
    folder = (proj or {}).get("folder_path", "")
    # Resolve the registry record (SAFE — never echoed to the client; only the
    # narration projection is returned).
    try:
        record = _termsess.get_session(session_id) or {}
    except Exception:
        record = {}
    # Finished ONE-SHOT JOB tile (no managed session record): the ``session`` is
    # a durable job_id. Render the effort record + its /report link directly —
    # the locked one-shot-job tile-class definition. Guarded; falls through to the
    # session floor if nothing resolves.
    if not record:
        try:
            eff = _eh.load_effort(folder, pid, _eh._resolve_subdir(lane),
                                  session_id)
        except Exception:
            eff = None
        if isinstance(eff, dict) and (eff.get("provenance") == "run"
                                      or isinstance(eff.get("cost"), dict)) \
                and not (eff.get("session_id") or ""):
            try:
                view = _narr.narrate_effort(pid, lane, eff, folder_path=folder)
                handler._send_json({"ok": True, "narration": view})
                return
            except Exception:
                pass
    # Lazy enrichment: decide 'generating' vs floor WITHOUT ever blocking on the
    # model. Cache HIT → 'cached' (build_narration resolves it). Cache MISS on a
    # registered project → trigger the existing background generation ONCE and
    # badge 'generating'. Unknown project / unresolvable session → plain floor.
    enrichment = None
    store_lane = lane
    try:
        store_lane = _eh._resolve_subdir(lane)
    except Exception:
        store_lane = lane
    cached = None
    try:
        cached = _summarizer.load_cached(folder, pid, store_lane, session_id)
    except Exception:
        cached = None
    if not (isinstance(cached, dict) and not cached.get("error")) and proj is not None:
        session_obj = None
        try:
            session_obj = _resolve_finished_session(
                folder, pid, lane, session_id)
        except Exception:
            session_obj = None
        if session_obj is not None:
            try:
                _trigger_session_summary(folder, pid, lane, session_obj)
                enrichment = _narr.ENRICH_GENERATING
            except Exception:
                enrichment = None
    try:
        view = _narr.narrate_session(
            pid, lane, session_id, folder_path=folder, record=record,
            enrichment=enrichment)
    except Exception:
        # TOTAL fallback — the narration builder is pure/never-raises, but keep
        # the endpoint structurally-never-blank even under an unexpected error.
        view = {
            "session_id": session_id, "tile_class": "done", "lane": lane,
            "title": lane, "done": f"ran {lane}", "produced": [],
            "produced_note": "no recoverable documents",
            "next": {"text": "Resume this session to continue where it left "
                             "off.", "source": "stage_derived", "submit": False},
            "badges": [], "enrichment": "floor", "links_valid": True,
        }
    handler._send_json({"ok": True, "narration": view})


def handle_usage_ledger(handler, path, body):
    # Read-only ledger/capture inspection (telemetry-resume W4): the finalized
    # usage verdict + cost block + deduped ledger totals for ONE managed session
    # — the honest cost trail the rollup renders. PURE read off the durable
    # ``.anchor/`` store; NO PTY, NO model call, NO network, NO sidecar read (the
    # ledger is Anchor's own snapshot). SAFE projection: never a worktree_path /
    # branch / absolute path. Cites the North Star amendment 'Endpoint auth rule'
    # (LOCKED) — this NEW route is token-authed (``?token=``) and enumerated in the
    # auth-enumeration test (401-before-substance).
    #   /api/rnd/usage_ledger?session=<sid>
    if not handler._term_token_ok():
        handler._send_json({"ok": False, "error": "unauthorized"}, 401)
        return
    q = parse_qs(urlparse(handler.path).query)
    sid = (q.get("session", [""])[0]
           or q.get("session_id", [""])[0] or "").strip()
    if not sid:
        handler._send_json({"ok": False, "error": "session required"}, 400)
        return
    try:
        rec = _sessreg.get_session(sid) or {}
    except Exception:
        rec = {}
    uuids = []
    try:
        uuids = _usage._engine_uuids_of(rec)
    except Exception:
        uuids = []
    try:
        totals = _usage.combined_totals(uuids)
    except Exception:
        totals = _usage._zero_totals()
    usage = {
        "session_id": sid,
        # SAFE projection — only the usage verdict + the engine-session UUIDs
        # (opaque ids, never worktree/branch/absolute paths).
        "state": rec.get("usage_state", "") or "",
        "reason": rec.get("usage_reason", "") or "",
        "cost_final": bool(rec.get("cost_final", False)),
        "engine_session_uuids": list(uuids),
        "ledger_totals": totals,
    }
    handler._send_json({"ok": True, "usage": usage})


def handle_term_sessions(handler, path, body):
    # Read-only: managed terminal sessions for a project — the
    # repopulate-from-registry hook the cockpit tiles row paints from
    # on load. Returns a SAFE projection of each registry record (NO
    # absolute worktree_path / branch — the UI has no need for them,
    # and they MUST NOT leak). Consistent with /api/rnd/projects
    # (GET, no mutation, no auth gate).
    #
    # v6 Wave 4: this projection now INCLUDES terminal-status
    # (done/failed) sessions too — finished tiles stay in the row as
    # greyed, reopenable tiles (newest-prominent + "previously done").
    # It also carries the Wave-2 lineage fields
    # (parent_session_id / chain_id) so the front end can group a
    # chain. Still SAFE: worktree_path / branch are NEVER included.
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("project_id", [""])[0] or "").strip()
    # v6 Wave 9 (polish 3): wire the reconcile→auto-advance into the
    # project-window refresh/poll path. Before listing, reconcile the
    # registry against the LIVE PTY set: a managed planning session
    # whose process is gone is re-statused DONE and (idempotently)
    # auto-advanced to ONE linked build — so a planning session that
    # DIED (not just an explicit hard-kill) advances on the next
    # refresh. Idempotent on parent_session_id → repeated polls are
    # no-ops. Best-effort + fully guarded: an error here NEVER breaks
    # the (read-only) session list response. live_session_ids MUST be
    # passed (the function default treats NO session as live, which
    # would wrongly mark live ones stale).
    try:
        live = list(_termsess._pty.live_sessions())
        # v12 Wave 8 — restart recovery MUST run BEFORE reconcile
        # (Reviewer W8-R2-01): reconcile_and_advance blanket-marks every
        # RUNNING-but-PTY-gone session DONE (no effort exemption), and
        # recover only acts on RUNNING records — so recover has to claim
        # an ``effort_managed`` effort whose PTY is gone FIRST (persist
        # its active stage's worktree docs [no reap], mark the stage entry
        # 'interrupted' [≠ done/failed], re-status IDLE so it is honestly
        # not-running + reopenable; NEVER auto-spawns/advances) — otherwise
        # reconcile would mark it DONE and its uncommitted docs would be
        # LOST. Once recover sets it IDLE, the reconcile pass below leaves
        # it alone (it only re-statuses RUNNING-but-gone). Best-effort +
        # fully guarded: an error here NEVER breaks the read-only list.
        try:
            _termsess.recover_interrupted_efforts(
                live_session_ids=live)
        except Exception:
            pass
        _rec_out = _termsess.reconcile_and_advance(
            live_session_ids=live)
        # v12 Wave 7 — REWIRE: an ``effort_managed`` effort does NOT
        # use the legacy reconcile→auto_advance_planning_to_build mint
        # (which is gated off for it anyway). Instead, on the SAME
        # refresh poll, run the on-disk-only ``detect_stage_progress``
        # over the project's LIVE efforts — it auto-advances IN-SESSION
        # on a committed plan-set / build signal (ZERO PTY bytes,
        # idempotent, mints nothing). Legacy sessions stay on the
        # reconcile_and_advance path above. Best-effort + fully guarded
        # (never breaks the read-only session-list response).
        try:
            for _er in _termsess.list_sessions(
                    project_id=pid or None):
                if not isinstance(_er, dict):
                    continue
                if not _er.get("effort_managed"):
                    continue
                if _er.get("status") != _termsess._reg.STATUS_RUNNING:
                    continue
                try:
                    _termsess.detect_stage_progress(
                        _er.get("session_id"),
                        project_id=_er.get("project_id") or None)
                except Exception:
                    pass
        except Exception:
            pass
        # v7 Wave 2: any session newly re-statused DONE by the
        # reconcile-dead path gets a background session-summary
        # scheduled (best-effort, non-blocking, idempotent — a cached
        # one is skipped, so repeated polls don't re-run the model).
        # Never breaks the read-only session-list response.
        try:
            marked = ((_rec_out or {}).get("reconcile", {})
                      or {}).get("marked", []) or []
            for _sid in marked:
                _r = _termsess.get_session(_sid)
                if _r is None:
                    continue
                _trigger_session_summary_on_finish(
                    _r.get("project_id"), _r.get("lane"), _sid)
        except Exception:
            pass
    except Exception:
        pass
    try:
        recs = _termsess.list_sessions(project_id=pid or None)
    except Exception:
        recs = []
    safe = []
    for r in recs:
        if not isinstance(r, dict):
            continue
        # v10 Wave 5 (DEFECT-2 fix): a CONTAINED grass-workbench
        # develop session (research/plan, [grass-dev] label) must NOT
        # surface on the top strip. It is mounted by session id
        # directly in the workbench pane (developGrass), not via this
        # projection, so dropping it here keeps the contained promise
        # at the source (the JS top-strip guard is the belt-and-braces
        # second line). Nothing else consumes this projection for
        # grass-dev sessions (the chain breadcrumb uses chain_members).
        if _eh.is_grass_dev_label(r.get("label")):
            continue
        # Phantom-tile fix: a Gandalf run registers a lane='gandalf'
        # status/cancel record, and the Zombie-Hunter terminal runs
        # under lane='zombie' (legacy records: lane='general',
        # label='zombie-hunter'). NONE of these are cockpit terminals
        # — exclude them so they never paint a workstation tile. The
        # label clause clears ALREADY-PERSISTED zombie records that
        # still carry lane='general'. Real general-tab terminals
        # (lane='general', no zombie-hunter label) are unaffected.
        if (r.get("lane") in ("gandalf", "zombie")
                or r.get("label") == "zombie-hunter"):
            continue
        # Doctor V3 W2: the reserved __doctor__ pseudo-project is FILTERED
        # from every dashboard/board surface (same pattern as __healthcheck__
        # task filtering) — its session must never paint a cockpit tile, even
        # when this projection is queried with project_id=__doctor__ directly.
        if r.get("project_id") == _termsess.DOCTOR_PROJECT_ID:
            continue
        safe.append({
            "session_id": r.get("session_id"),
            "project_id": r.get("project_id", ""),
            "lane": r.get("lane", ""),
            "backend": r.get("backend", ""),
            "status": r.get("status", ""),
            "label": r.get("label", ""),
            "created_at": r.get("created_at"),
            "parent_session_id": r.get("parent_session_id", ""),
            "chain_id": r.get("chain_id", ""),
            # v10 Wave 4: grass→project lineage (SAFE — idea id only,
            # never worktree_path/branch).
            "grass_origin": r.get("grass_origin", ""),
            # v12 Wave 7: the effort discriminator (SAFE — a bool).
            # The JS uses it to HIDE the retired legacy advance bars
            # (research "Advance to Planning →" / planning
            # "Finish → Build →") for a v12 effort, so the old
            # session-minting affordances are not reachable for it.
            "effort_managed": bool(r.get("effort_managed", False)),
        })
    handler._send_json({"ok": True, "sessions": safe})


def handle_projects_html(handler, path, body):
    # Read-only (v5 Wave 3): the rendered R&D rows FRAGMENT, so an
    # already-open main dashboard can poll for changes (new session,
    # added idea, priority/notes/blurb edit, archive, new project,
    # refreshed summary, rollups) and swap them in WITHOUT a full
    # page reload. REUSES render_projects_view_html (which reads
    # ONLY the cached summaries — no synchronous model run here). No
    # mutation, no auth gate (consistent with /api/rnd/projects).
    try:
        frag = render_projects_view_html()
    except Exception:
        frag = ('<div class="rnd-projects"><p class="rnd-empty">'
                'No active R&amp;D projects.</p></div>')
    handler._send_json({"ok": True, "html": frag})


def handle_previews(handler, path, body):
    # Read-only: list ephemeral deliverable previews for a project
    # (reconciles dead previews → stopped so the UI repopulates
    # truthfully on reconnect). Wave 8. Returns a SAFE projection of
    # each registry record — NO absolute filesystem paths
    # (data_dir / folder_path); the UI only needs the id/url/port/
    # status. Consistent with the term_sessions projection (which
    # strips worktree_path). The persisted record (.anchor/
    # previews.json) keeps the full fields for reaping.
    q = parse_qs(urlparse(handler.path).query)
    pid = (q.get("project_id", [""])[0] or "").strip() or None
    safe = []
    for r in _preview.list_previews(pid):
        if not isinstance(r, dict):
            continue
        safe.append({
            "preview_id": r.get("preview_id"),
            "project_id": r.get("project_id"),
            "target": r.get("target", ""),
            "port": r.get("port"),
            "url": r.get("url", ""),
            "status": r.get("status", ""),
            "started_at": r.get("started_at"),
            "stopped_at": r.get("stopped_at"),
        })
    handler._send_json({"ok": True, "previews": safe})


def handle_zombie_kill(handler, path, body):
    # Kill an orphaned swarm/terminal session by its SESSION id. The swarm
    # & owner view lists session_registry records, so it passes a
    # session_id (NOT a job_runner job_id) — cancel_job's _jr.load_record
    # would 404 on it. Here we tree-kill the recorded PID directly and mark
    # the registry record CANCELLED so it drops out of the running list and
    # never reappears on refresh. Idempotent; clean 404 for an unknown id.
    # Auth is enforced by the mutating-POST middleware above.
    import proc_probe
    sid = (body.get("session_id", "") or body.get("session", "")
           or body.get("job_id", "") or "").strip()
    rec = _sessreg.get_session(sid) if sid else None
    if rec is None:
        handler._send_json({"ok": False, "error": f"unknown session: {sid}",
                         "reason": "unknown-session"}, 404)
    else:
        pid = rec.get("pid")
        killed = False
        try:
            if pid not in (None, ""):
                killed = bool(proc_probe.tree_kill(int(pid)))
        except Exception:
            killed = False
        try:
            _sessreg.update_session(sid, status=_sessreg.STATUS_CANCELLED)
        except Exception:
            pass
        try:
            import zombie_hunter
            zombie_hunter.forget_pid(pid)
        except Exception:
            pass
        handler._send_json({"ok": True, "session_id": sid, "killed": killed})


def handle_zombie_resume(handler, path, body):
    # Un-freeze an orphan that was auto-paused in the report while it
    # waited to be killed (the swarm & owner view's Resume button). Acts
    # by session_id. Clean 404 for an unknown id; auth enforced above.
    sid = (body.get("session_id", "") or body.get("session", "")).strip()
    rec = _sessreg.get_session(sid) if sid else None
    if rec is None:
        handler._send_json({"ok": False, "error": f"unknown session: {sid}",
                         "reason": "unknown-session"}, 404)
    else:
        pid = rec.get("pid")
        resumed = False
        try:
            if pid not in (None, ""):
                import zombie_hunter
                resumed = bool(zombie_hunter.resume_pid(pid))
        except Exception:
            resumed = False
        handler._send_json({"ok": True, "session_id": sid, "resumed": resumed})


def handle_upload_batch(handler, path, body):
    """POST /api/rnd/upload_batch — write a batch of base64-encoded files into a
    project's folder (or the dashboard 'dev' dir), traversal-safe. Auth enforced by
    the do_POST middleware (the strangler runs after it).
    """
    project_id = body.get("project_id", "__dashboard__")
    files = body.get("files", [])

    if not isinstance(files, list):
        handler._send_json({"ok": False, "error": "files must be a list"})
        return

    if project_id == "__dashboard__" or project_id == "dev" or not project_id:
        upload_dir = ANCHOR_DIR / "dev"
    else:
        entry = _rnd.get_project(project_id)
        if entry and entry.get("folder_path"):
            upload_dir = Path(entry["folder_path"])
        else:
            upload_dir = ANCHOR_DIR / ".anchor" / "projects" / project_id / "uploads"

    upload_dir = upload_dir.resolve()

    import base64
    import tempfile

    try:
        for file_info in files:
            rel_path_str = file_info.get("path", "")
            content_b64 = file_info.get("content_b64", "")

            if not rel_path_str or content_b64 is None:
                handler._send_json({"ok": False, "error": "missing path or content_b64 for a file"})
                return

            p = Path(rel_path_str)
            if p.is_absolute() or os.path.isabs(rel_path_str):
                handler._send_json({"ok": False, "error": f"Absolute paths not allowed: {rel_path_str}"})
                return

            for part in p.parts:
                if part == ".." or part == ".":
                    handler._send_json({"ok": False, "error": f"Path traversal/invalid directory name: {rel_path_str}"})
                    return

            dest_path = (upload_dir / p).resolve()
            try:
                dest_path.relative_to(upload_dir)
                if dest_path == upload_dir:
                    handler._send_json({"ok": False, "error": "Cannot overwrite project root directory"})
                    return
            except ValueError:
                handler._send_json({"ok": False, "error": f"Path containment check failed for {rel_path_str}"})
                return

            file_data = base64.b64decode(content_b64)

            parent_dir = dest_path.parent
            parent_dir.mkdir(parents=True, exist_ok=True)

            tmp_fd, tmp_name = tempfile.mkstemp(dir=str(parent_dir))
            try:
                with os.fdopen(tmp_fd, 'wb') as tmp_file:
                    tmp_file.write(file_data)
                os.replace(tmp_name, dest_path)
            except Exception:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
                raise

        handler._send_json({"ok": True, "message": f"Uploaded {len(files)} files successfully."})
    except Exception as e:
        handler._send_json({"ok": False, "error": str(e)})


def handle_upload(handler, path, body):
    """POST /api/upload — write a single base64-encoded file into a project's
    folder (or the dashboard 'dev' dir). Auth enforced by the do_POST middleware.
    """
    project_id = body.get("project_id", "__dashboard__")
    filename = body.get("filename", "")
    content_b64 = body.get("content_b64", "")

    if not filename or not content_b64:
        handler._send_json({"ok": False, "error": "missing filename or content"})
        return

    import base64
    try:
        file_data = base64.b64decode(content_b64)
        if project_id == "__dashboard__" or project_id == "dev" or not project_id:
            upload_dir = ANCHOR_DIR / "dev"
        else:
            entry = _rnd.get_project(project_id)
            if entry and entry.get("folder_path"):
                upload_dir = Path(entry["folder_path"])
            else:
                upload_dir = ANCHOR_DIR / ".anchor" / "projects" / project_id / "uploads"

        upload_dir.mkdir(parents=True, exist_ok=True)
        dest_path = upload_dir / filename
        dest_path.write_bytes(file_data)

        handler._send_json({"ok": True, "message": f"Uploaded {filename} successfully."})
    except Exception as e:
        handler._send_json({"ok": False, "error": str(e)})


def _reaper_control(handler, body, action):
    """Shared body for the reaper arm/advance/disarm control-plane handlers.

    Already token-gated by the do_POST middleware; the reaper module fns ALSO
    re-check paths.auth_ok(provided) (defense in depth), so the presented token is
    reconstructed here (mirroring the middleware's order) and passed through.
    """
    provided = _request_presented_token(handler, body)
    import reaper_arming as _arm
    try:
        out = getattr(_arm, action)(provided)
    except Exception as exc:
        handler._send_json({"ok": False, "error": str(exc)}, 500)
    else:
        code = 200 if out.get("ok") else (
            401 if out.get("error") == "unauthorized" else 409)
        handler._send_json(out, code)


def handle_reaper_arm(handler, path, body):
    """POST /api/rnd/reaper_arm — the reaper ARMING control plane (arm).

    Wave 11 (foundry-v2, safety before scale): the ARM rung (log->freeze) goes
    through the sanctioned Wave-11 path, which RE-CHECKS the 2026-07-05
    fail-deadly finding before delegating to the token-authed, receipt-gated
    ladder — an open finding refuses the arm with no state change. Targets
    FREEZE only; this endpoint can never arm KILL. Mirrors ``_reaper_control``'s
    token reconstruction + error/response handling (the middleware token-gates
    this row FIRST; the reaper module re-checks paths.auth_ok in depth)."""
    provided = _request_presented_token(handler, body)
    import foundry_safety as _fsafety
    try:
        out = _fsafety.arm_reaper_to_freeze(provided)
    except Exception as exc:
        handler._send_json({"ok": False, "error": str(exc)}, 500)
    else:
        code = 200 if out.get("ok") else (
            401 if out.get("error") == "unauthorized" else 409)
        handler._send_json(out, code)


def handle_reaper_advance(handler, path, body):
    """POST /api/rnd/reaper_advance — reaper arming control plane (advance)."""
    _reaper_control(handler, body, "advance")


def handle_reaper_disarm(handler, path, body):
    """POST /api/rnd/reaper_disarm — reaper arming control plane (disarm)."""
    _reaper_control(handler, body, "disarm")


# ── Skill Foundry v2 GUI write surface (foundry-v2 Wave 10) ──────────────────
# EVERY Foundry GUI mutation is a confirm-gated control-plane op dispatched
# through job_runner (auto-journaled) — never a GUI-side file write. Token-gated
# by the do_POST middleware (the strangler applies the row auth BEFORE these run).

def handle_foundry_create_skill(handler, path, body):
    """POST /api/foundry/create_skill — create a skill → foundry.scaffold_skill
    (refuses to overwrite; branch commit)."""
    handler._send_json(_fgw.create_skill(
        body.get("name"),
        confirm=bool(body.get("confirm")),
        title=body.get("title") or None,
        description=body.get("description") or None))


def handle_foundry_north_star(handler, path, body):
    """POST /api/foundry/north_star — edit a per-skill North Star via the ONLY
    sanctioned mutation path (foundry.edit_north_star): propose parks a
    reviewable diff; apply spends the explicit confirm (prior version retained,
    branch commit)."""
    if str(body.get("mode") or "propose") == "apply":
        handler._send_json(_fgw.north_star_apply(
            body.get("skill"), body.get("proposal_id"),
            confirm=bool(body.get("confirm"))))
    else:
        handler._send_json(_fgw.north_star_propose(
            body.get("skill"), body.get("new_text"),
            confirm=bool(body.get("confirm"))))


def handle_foundry_sleep_session(handler, path, body):
    """POST /api/foundry/sleep_session — SPLIT seam: targets the DECLARED op
    interface foundry.sleep_session; until the separate foundry build delivers
    the op body this answers the honest pending status — nothing is faked,
    nothing dispatched."""
    handler._send_json(_fgw.run_sleep_session(
        confirm=bool(body.get("confirm"))))


def handle_foundry_sync_autoload(handler, path, body):
    """POST /api/foundry/sync_autoload — regenerate Anchor's clickable skill set
    from map.json v2 alone (foundry.register_autoload — every foundry skill
    auto-loaded, never hand-wired)."""
    handler._send_json(_fgw.sync_autoload(
        confirm=bool(body.get("confirm"))))


# ── Foundry GUI fold-in: the REAL sleep-session kernel loop (server.mjs port) ─
# The folded-in React app POSTs these three verbs; each spawns the genuine
# foundry-v2 kernel CLI (sleep-kernel-cli.mjs) via foundry_api and returns its
# honest JSON record (0 ok / 3 refused / 1 blocked). Apply is confirm-gated by
# the kernel AND by foundry_api. Token-gated by the do_POST middleware.

def handle_foundry_sleep_propose(handler, path, body):
    """POST /api/foundry/sleep_session/propose — kernel `propose`."""
    payload, code = _fapi.sleep_propose(body)
    handler._send_json(payload, code)


def handle_foundry_sleep_apply(handler, path, body):
    """POST /api/foundry/sleep_session/apply — confirm-gated kernel `apply`."""
    payload, code = _fapi.sleep_apply(body)
    handler._send_json(payload, code)


def handle_foundry_sleep_rollback(handler, path, body):
    """POST /api/foundry/sleep_session/rollback — kernel `rollback`."""
    payload, code = _fapi.sleep_rollback(body)
    handler._send_json(payload, code)


# Route-table handler name -> module-level function. route_table rows reference
# the STRING name (keeping route_table.py import-free); the strangler resolves it
# here. A migrated row whose name is absent falls through to legacy (defensive).
_MIGRATED_HANDLERS = {
    "handle_version": handle_version,
    "handle_status": handle_status,
    "handle_routes": handle_routes,
    "handle_dir_browse": handle_dir_browse,
    "handle_auth_login": handle_auth_login,
    "handle_auth_logout": handle_auth_logout,
    "handle_set_priority": handle_set_priority,
    "handle_set_group": handle_set_group,
    "handle_add_idea": handle_add_idea,
    "handle_pin_deliverable": handle_pin_deliverable,
    "handle_remote_status": handle_remote_status,
    "handle_chain": handle_chain,
    "handle_done": handle_done,
    "handle_undone": handle_undone,
    "handle_add": handle_add,
    "handle_capture": handle_capture,
    "handle_edit_task": handle_edit_task,
    "handle_edit_project": handle_edit_project,
    "handle_promote_task": handle_promote_task,
    "handle_demote_task": handle_demote_task,
    "handle_cancel": handle_cancel,
    "handle_save_for_later": handle_save_for_later,
    "handle_restore": handle_restore,
    "handle_promote_project": handle_promote_project,
    "handle_demote_project": handle_demote_project,
    "handle_new_project": handle_new_project,
    "handle_open_project": handle_open_project,
    "handle_rescan": handle_rescan,
    "handle_archive_project": handle_archive_project,
    "handle_future_project": handle_future_project,
    "handle_retire_project": handle_retire_project,
    "handle_reactivate_project": handle_reactivate_project,
    "handle_set_notes": handle_set_notes,
    "handle_settings_get": handle_settings_get,
    "handle_settings_post": handle_settings_post,
    "handle_set_blurb": handle_set_blurb,
    "handle_link_task": handle_link_task,
    "handle_project_rollup": handle_project_rollup,
    "handle_effort_rollup": handle_effort_rollup,
    "handle_boneyard": handle_boneyard,
    # (2026-07-30 FIX) Same omission as stand_up below, found by the new
    # test_every_migrated_route_has_a_registered_handler gate: both are defined,
    # both are declared migrated=True in the route table, neither was registered
    # — and neither has a legacy-chain fallback, so GET /api/rnd/friction and
    # POST /api/rnd/journal_friction were dead 404s.
    "handle_friction_list": handle_friction_list,
    "handle_journal_friction": handle_journal_friction,
    "handle_ecgberht_chamber": handle_ecgberht_chamber,
    "handle_ecgberht_speak": handle_ecgberht_speak,
    # (2026-07-30 FIX) stand_up was DEFINED and declared migrated=True in the
    # route table, but never registered here — so _strangler_dispatch took its
    # defensive "migrated row with an unregistered handler" branch, fell through
    # to the legacy chain, and answered 404 "Unknown endpoint". That is what
    # John hit setting a project goal: "Couldn't do that: Unknown endpoint —
    # nothing was created." test_every_migrated_route_has_a_handler now makes
    # this class of omission impossible to reintroduce.
    "handle_ecgberht_stand_up": handle_ecgberht_stand_up,
    "handle_ecgberht_high_seat": handle_ecgberht_high_seat,
    "handle_ecgberht_high_seat_badge": handle_ecgberht_high_seat_badge,
    "handle_ecgberht_bring_up": handle_ecgberht_bring_up,
    "handle_ecgberht_high_seat_act": handle_ecgberht_high_seat_act,
    "handle_ecgberht_artifact": handle_ecgberht_artifact,
    "handle_build_deliverable": handle_build_deliverable,
    "handle_orphan_check": handle_orphan_check,
    "handle_zombie_spenders": handle_zombie_spenders,
    "handle_reaper_status": handle_reaper_status,
    "handle_promote_grass": handle_promote_grass,
    "handle_grass_develop": handle_grass_develop,
    "handle_grass_workbench": handle_grass_workbench,
    "handle_grass_save_refinement": handle_grass_save_refinement,
    "handle_grass_set_status": handle_grass_set_status,
    "handle_grass_pull": handle_grass_pull,
    "handle_grass_export": handle_grass_export,
    "handle_grass_archive": handle_grass_archive,
    "handle_grass_advance": handle_grass_advance,
    "handle_grass_delete": handle_grass_delete,
    "handle_gandalf_run": handle_gandalf_run,
    "handle_tidy_idy_run": handle_tidy_idy_run,
    "handle_tidy_idy_status": handle_tidy_idy_status,
    "handle_tidy_idy_proxy": handle_tidy_idy_proxy,
    "handle_gandalf_delete": handle_gandalf_delete,
    "handle_gandalf_archive": handle_gandalf_archive,
    "handle_gandalf_clear_failed": handle_gandalf_clear_failed,
    "handle_gandalf_cancel": handle_gandalf_cancel,
    "handle_term_kill": handle_term_kill,
    "handle_term_close": handle_term_close,
    "handle_term_delete": handle_term_delete,
    "handle_cleanup_ghost_sessions": handle_cleanup_ghost_sessions,
    "handle_term_set_engine": handle_term_set_engine,
    "handle_switch_terminal_engine": handle_switch_terminal_engine,
    "handle_term_resize": handle_term_resize,
    "handle_start_terminal": handle_start_terminal,
    "handle_term_input": handle_term_input,
    "handle_term_discover": handle_term_discover,
    "handle_term_adopt": handle_term_adopt,
    "handle_term_start": handle_term_start,
    "handle_zombie_terminal_start": handle_zombie_terminal_start,
    "handle_zh_engines": handle_zh_engines,
    "handle_doctor_session_start": handle_doctor_session_start,
    "handle_doctor_banner_seed": handle_doctor_banner_seed,
    "handle_doctor_status": handle_doctor_status,
    "handle_doctor_report": handle_doctor_report,
    "handle_doctor_healthcheck_run": handle_doctor_healthcheck_run,
    "handle_doctor_healthcheck_tail": handle_doctor_healthcheck_tail,
    "handle_term_input2": handle_term_input2,
    "handle_answer_gate": handle_answer_gate,
    "handle_cancel_job": handle_cancel_job,
    "handle_regenerate_summary": handle_regenerate_summary,
    "handle_continue_session": handle_continue_session,
    "handle_resume_live": handle_resume_live,
    "handle_orient_session": handle_orient_session,
    "handle_advance_session": handle_advance_session,
    "handle_advance_stage": handle_advance_stage,
    "handle_handoff_to_fresh": handle_handoff_to_fresh,
    "handle_finish_to_build": handle_finish_to_build,
    "handle_heartbeat": handle_heartbeat,
    "handle_move_project": handle_move_project,
    "handle_run_deliverable": handle_run_deliverable,
    "handle_launch_deliverable": handle_launch_deliverable,
    "handle_launch_lane": handle_launch_lane,
    "handle_preview_start": handle_preview_start,
    "handle_preview_stop": handle_preview_stop,
    "handle_promote_inbox": handle_promote_inbox,
    "handle_link_github": handle_link_github,
    "handle_set_auto_push": handle_set_auto_push,
    "handle_push_now": handle_push_now,
    "handle_project_files": handle_project_files,
    "handle_project_file_content": handle_project_file_content,
    "handle_session_doc_roles": handle_session_doc_roles,
    "handle_context_status": handle_context_status,
    "handle_grass": handle_grass,
    "handle_gandalf": handle_gandalf,
    "handle_gandalf_status": handle_gandalf_status,
    "handle_gandalf_status_all": handle_gandalf_status_all,
    "handle_zombie_hunter_report": handle_zombie_hunter_report,
    "handle_zombie_hunter_proxy": handle_zombie_hunter_proxy,
    "handle_zombie_terminal": handle_zombie_terminal,
    "handle_board_html": handle_board_html,
    "handle_handoff_proposal": handle_handoff_proposal,
    "handle_session_summary": handle_session_summary,
    "handle_session_narration": handle_session_narration,
    "handle_usage_ledger": handle_usage_ledger,
    "handle_term_sessions": handle_term_sessions,
    "handle_projects_html": handle_projects_html,
    "handle_previews": handle_previews,
    "handle_zombie_kill": handle_zombie_kill,
    "handle_zombie_resume": handle_zombie_resume,
    "handle_upload_batch": handle_upload_batch,
    "handle_upload": handle_upload,
    "handle_reaper_arm": handle_reaper_arm,
    "handle_reaper_advance": handle_reaper_advance,
    "handle_reaper_disarm": handle_reaper_disarm,
    "handle_foundry_create_skill": handle_foundry_create_skill,
    "handle_foundry_north_star": handle_foundry_north_star,
    "handle_foundry_sleep_session": handle_foundry_sleep_session,
    "handle_foundry_sync_autoload": handle_foundry_sync_autoload,
    "handle_foundry_sleep_propose": handle_foundry_sleep_propose,
    "handle_foundry_sleep_apply": handle_foundry_sleep_apply,
    "handle_foundry_sleep_rollback": handle_foundry_sleep_rollback,
}


class AnchorHandler(BaseHTTPRequestHandler):
    #: Query params whose VALUES must never reach a log file.
    _LOG_REDACT_PARAMS = ("token", "capability", "nonce", "key", "secret")

    @classmethod
    def _redact_request_line(cls, line):
        """Strip secret query-param values from an access-log request line.

        2026-07-26 hardening. Every authed GET carried the LIVE capability token
        verbatim into ``logs/nssm-stdout.log`` (the GET-transport ``?token=``
        design), forever — in the very directory a collaborator is told to
        inspect when something breaks. The token is redacted here, at the one
        place request lines are written, so no call site can forget.
        """
        import re as _re  # module-local: anchor_gui imports re per-function
        try:
            s = str(line)
        except Exception:
            return line
        for p in cls._LOG_REDACT_PARAMS:
            s = _re.sub(r"(?i)([?&]" + _re.escape(p) + r"=)[^&\s\"']+",
                        r"\1<redacted>", s)
        return s

    def log_message(self, format, *args):
        first = self._redact_request_line(args[0]) if args else ""
        print(f"  [{datetime.now().strftime('%H:%M:%S')}] {first}")

    def log_error(self, format, *args):
        # Quiet the benign client-disconnect noise the base class would log to
        # stderr (it routes BrokenPipe/ConnectionReset/timeout messages here).
        # Real protocol errors still surface via the normal response paths.
        return

    def _send_json(self, data, code=200):
        body = json.dumps(data).encode()
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            # Client closed mid-response (browser tab close / Playwright
            # teardown). Nothing left to send — swallow ONLY the benign
            # disconnect; re-raise anything else.
            if _is_benign_disconnect(exc):
                return
            raise

    def _send_html(self, html_text):
        body = html_text.encode("utf-8")
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
            self.send_header("Pragma", "no-cache")
            self.send_header("Expires", "0")
            self.end_headers()
            self.wfile.write(body)
        except Exception as exc:
            if _is_benign_disconnect(exc):
                return
            raise

    def _send_bytes(self, data, content_type, cache="no-cache"):
        try:
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", cache)
            self.end_headers()
            self.wfile.write(data)
        except Exception as exc:
            if _is_benign_disconnect(exc):
                return
            raise

    # ── SSE for the interactive terminal (Wave 7) ────────────────────────────
    def _sse_event(self, event, data_obj):
        """Write ONE well-formed SSE event frame and flush it.

        Frame shape (per the SSE spec): an ``event:`` line, one ``data:`` line
        carrying a JSON payload, then a BLANK line terminating the event. Flushed
        immediately so a streaming client observes events as they arrive.

        Teardown hardening: writing/flushing onto a ``wfile`` whose underlying
        socket was already closed (client gone, or the request thread torn down
        out from under a leaked pump) raises ``ValueError("I/O operation on
        closed file")`` — which is a benign client-gone condition, not a server
        bug, but it is NOT in the OSError family the stream loops guard on. We
        normalize it to a ``BrokenPipeError`` so the existing
        ``except (BrokenPipeError, ConnectionResetError, OSError)`` guards end
        the stream CLEANLY (the daemon thread never raises a stray ValueError on
        teardown). The benign socket-teardown OSErrors propagate unchanged for
        those same guards; any non-benign error is re-raised untouched.
        """
        payload = json.dumps(data_obj, ensure_ascii=False)
        frame = f"event: {event}\ndata: {payload}\n\n"
        try:
            self.wfile.write(frame.encode("utf-8"))
            self.wfile.flush()
        except ValueError as exc:
            # I/O on a closed file (wfile closed under us) == client/connection
            # gone. Re-raise as BrokenPipeError so the OSError-family guards
            # catch it; never swallow a different ValueError.
            if "closed file" in str(exc):
                raise BrokenPipeError(str(exc)) from exc
            raise

    def _serve_term_sse(self):
        """Stream a terminal session's output as Server-Sent Events.

        Stdlib-only streaming: a chunked ``text/event-stream`` response that
        loops, polling :func:`rnd_terminal.read_since` for new output, flushing an
        ``output`` event for new lines, a ``status`` event on change, and a
        ``gate`` event when an in-session prompt surfaces. It emits a
        ``heartbeat`` every few idle ticks and ENDS with a ``done`` event when the
        session is terminal OR a bounded tick budget elapses — so a test can read
        N events and the stream closes (no indefinite hang). The bound + poll
        interval are query-overridable for fast hermetic tests.
        """
        q = parse_qs(urlparse(self.path).query)
        session = (q.get("session", [""])[0] or "").strip()
        try:
            since = int(q.get("since", ["0"])[0] or 0)
        except (TypeError, ValueError):
            since = 0
        if not session:
            self._send_json({"ok": False, "error": "missing session"}, 400)
            return
        # Bounded loop knobs (defaults are production-sane; tests shrink them so
        # the stream ends quickly). poll_interval in seconds; max_ticks bounds the
        # total loop iterations; heartbeat_every emits a keep-alive on idle ticks.
        try:
            poll_interval = float(q.get("poll", ["0.25"])[0] or 0.25)
        except (TypeError, ValueError):
            poll_interval = 0.25
        try:
            max_ticks = int(q.get("max_ticks", ["240"])[0] or 240)
        except (TypeError, ValueError):
            max_ticks = 240
        try:
            heartbeat_every = int(q.get("hb", ["8"])[0] or 8)
        except (TypeError, ValueError):
            heartbeat_every = 8

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection", "close")
        # No Content-Length → chunked/streamed body via the connection close.
        self.end_headers()

        cursor = since
        last_status = None
        idle = 0
        try:
            for _tick in range(max(1, max_ticks)):
                # Guard the per-tick read + event emission so ANY exception from
                # read_since (not just pipe/OS errors) ends the stream CLEANLY
                # with a terminal done/error event instead of letting the handler
                # thread crash mid-stream and leaving the client hung (never
                # getting a 'done'). Pipe/connection errors mean the client is
                # already gone, so for those we just stop without trying to write.
                try:
                    out = _term.read_since(session, cursor)
                    lines = out.get("lines") or []
                    if lines:
                        self._sse_event("output", {"lines": lines,
                                                   "next": out.get("next", cursor)})
                        cursor = out.get("next", cursor)
                        idle = 0
                    else:
                        idle += 1
                    status = out.get("status")
                    if status and status != last_status:
                        self._sse_event("status", {"status": status})
                        last_status = status
                    pending = out.get("pending_prompt")
                    if pending:
                        self._sse_event("gate", {"prompt": pending})
                    if status in _term.TERMINAL_STATUSES:
                        # Drain any final lines, then end the stream cleanly.
                        final = _term.read_since(session, cursor)
                        fl = final.get("lines") or []
                        if fl:
                            self._sse_event("output", {"lines": fl,
                                                       "next": final.get("next", cursor)})
                            cursor = final.get("next", cursor)
                        self._sse_event("done", {"status": status, "next": cursor})
                        return
                    if heartbeat_every and idle and idle % heartbeat_every == 0:
                        self._sse_event("heartbeat", {"next": cursor})
                except (BrokenPipeError, ConnectionResetError, OSError):
                    # Client closed the connection — stop cleanly (re-raise to the
                    # outer guard, which simply returns).
                    raise
                except Exception:
                    # ANY other failure (a generic read_since error, a bad record,
                    # etc.): emit a final error-flavored done so the client always
                    # gets a terminal frame, then end the stream. Best-effort — if
                    # even this write fails the outer guard swallows it.
                    try:
                        self._sse_event("done", {"status": "error",
                                                 "next": cursor, "error": True})
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    return
                time.sleep(max(0.0, poll_interval))
            # Tick budget exhausted while still live — end with a heartbeat-flavored
            # done so the client can re-open (bounded, never an infinite hold).
            self._sse_event("done", {"status": last_status or "running",
                                     "next": cursor, "bounded": True})
        except (BrokenPipeError, ConnectionResetError, OSError):
            # Client closed the connection — stop cleanly.
            return

    # ── ConPTY terminal transport (Wave 3) ──────────────────────────────────
    def _term_token_ok(self):
        """Auth a token-gated GET endpoint (``?token=`` / Authorization header).

        Browsers can't set request headers on an EventSource / WebSocket
        handshake, so the terminal GET surface (an RCE surface) authenticates via
        a query-param token with the SAME semantics as ``paths.auth_ok``: if no
        token is configured (``ANCHOR_TOKEN`` unset) it is allowed (local
        back-compat); otherwise the provided token must match.

        rearch-2026-07 W2: the standard ``Authorization`` header (Bearer or a
        bare token) is accepted EVERYWHERE this gate applies, so every
        non-browser consumer (healthcheck endpoint walk, scripts) has a header
        token path — ``?token=`` remains only because the WS/SSE transports
        demand it. Also accepts a token carried in the
        ``Sec-WebSocket-Protocol`` header (for WS clients).
        """
        q = parse_qs(urlparse(self.path).query)
        provided = (q.get("token", [None])[0])
        if provided is None:
            provided = _paths.token_from_authorization(
                self.headers.get("Authorization"))
        if provided is None:
            # WS clients may smuggle the token via the subprotocol header.
            provided = self.headers.get("Sec-WebSocket-Protocol")
        if provided is None:
            # rearch W9: browser page navigation (and the desktop term_ws
            # upgrade — cookie-through-WS spike proven) authenticates off the
            # HttpOnly auth cookie, so no token rides in a page URL.
            provided = _paths.token_from_cookie(self.headers.get("Cookie"))
        return _paths.auth_ok(provided)

    # ── Strangler dispatch (rearch W7 / C2) ─────────────────────────────────
    def _route_auth_ok(self, route):
        """Apply a route row's declared auth policy. True == permitted.

        ``open`` routes are always permitted. For ``token``/``ws_token`` routes:
        a POST is already gated by the do_POST token middleware (which runs
        BEFORE the strangler), so re-checking would be redundant AND wrong (that
        middleware also accepts the X-Anchor-Token header and a body token, which
        :meth:`_term_token_ok` does not) — so a POST returns True here. A GET is
        gated via :meth:`_term_token_ok` (query token / Authorization header),
        matching the pre-existing token-gated GET surface exactly.
        """
        if route.auth == _routes.AUTH_OPEN:
            return True
        if route.method == "POST":
            return True
        return self._term_token_ok()

    def _strangler_dispatch(self, method, path, body=None):
        """Table-first dispatch. Returns True iff this request was HANDLED here.

        Looks the request up in the declarative route table. A matched, MIGRATED
        row is handled by its module-level function — but the row's auth check is
        invoked FIRST (honestly special-cased for ``kind != standard``: the auth
        gate runs before any stream/upgrade handler takes over the socket). A
        miss, or a matched-but-not-yet-migrated row, returns False so the caller
        FALLS THROUGH to the legacy if/elif chain unchanged (the strangler
        pattern). Defensive: a row flagged migrated whose handler name is not
        registered also falls through rather than 500-ing.
        """
        route = _routes.match(method, path)
        if route is None or not route.migrated:
            return False
        fn = _MIGRATED_HANDLERS.get(route.handler)
        if fn is None:
            return False
        if not self._route_auth_ok(route):
            self._send_json({"ok": False, "error": "unauthorized"}, 401)
            return True
        # Always hand handlers the FULL request URI (query included). Route
        # matching uses a path-only string, but handlers that parse ?project_id=
        # must see the query. Passing path-only caused tidy_idy_status to return
        # "project_id required" on every remote poll (Tailscale freeze at 42%).
        full = getattr(self, "path", None) or path
        fn(self, full, body)
        return True

    # ── Data-plane auth-mode gate (rearch W8 warn / W9 enforce) ──────────────
    def _auth_mode(self):
        """The current ``auth`` pillar flag: ``open`` | ``warn`` | ``enforce``.

        Resolved from the environment each call (``ANCHOR_AUTH_MODE`` / the
        ``ANCHOR_AUTH_WARN`` alias). Defensive: an unreadable/invalid config
        falls back to ``open`` (today's live behavior) rather than crashing a
        request — the loud invalid-value failure is the healthcheck's job
        (``check_pillar_state``), not the hot request path's.
        """
        try:
            return _pillar_flags.current_flags()[_pillar_flags.FLAG_AUTH]
        except Exception:
            return _pillar_flags.FLAG_DEFAULTS[_pillar_flags.FLAG_AUTH]

    def _presented_token(self):
        """Any token the request carried (``?token=`` / Authorization / WS proto),
        or ``None`` — used only to record WHETHER a token was presented, never its
        value."""
        try:
            q = parse_qs(urlparse(self.path).query)
            provided = q.get("token", [None])[0]
            if provided is None:
                provided = _paths.token_from_authorization(
                    self.headers.get("Authorization"))
            if provided is None:
                provided = self.headers.get("Sec-WebSocket-Protocol")
            if provided is None:
                # W9: the browser auth cookie is also a presented token.
                provided = _paths.token_from_cookie(
                    self.headers.get("Cookie"))
            return provided
        except Exception:
            return None

    def _data_plane_gate(self, method, path):
        """Apply the W8/W9 auth-mode overlay to the reviewed data-plane batch.

        Returns True iff the request was HANDLED here (a 401 was sent) and the
        caller must ``return``. Behavior by mode for a route in
        ``route_table.DATA_PLANE_GATED``:

          * ``open`` (today)  → False (serve; no overlay).
          * ``warn`` (W8)     → for a TOKENLESS request, append a would-401 entry
            to the soak log, then return False (log-only — STILL served).
          * ``enforce`` (W9)  → for a TOKENLESS request, send 401 + return True.

        An authorized request (valid token) is always served (False) in every
        mode. A non-gated / unmatched route is a no-op (False).
        """
        route = _routes.match(method, path)
        if not _routes.is_data_plane_gated(route):
            return False
        mode = self._auth_mode()
        if mode == _auth_warn.MODE_OPEN:
            return False
        if self._term_token_ok():
            return False
        # Tokenless request against a gated route while warned/enforced.
        try:
            remote = None
            addr = getattr(self, "client_address", None)
            if addr:
                remote = addr[0]
            _auth_warn.record_would_401(
                method, path,
                remote=remote,
                has_token=self._presented_token() is not None,
                user_agent=self.headers.get("User-Agent"),
                referer=self.headers.get("Referer"),
                mode=mode,
            )
        except Exception:
            # Logging must never break the request during the soak.
            pass
        if mode == _auth_warn.MODE_ENFORCE:
            self._send_json({"ok": False, "error": "unauthorized"}, 401)
            return True
        return False  # warn: observe-only, fall through to the legacy handler

    def _serve_term_stream2(self):
        """SSE-out fallback for a ConPTY session (Wave 3).

        The plan's named fallback half: an ``text/event-stream`` of a ConPTY
        session's output via ``pty_manager.read_since`` (through
        ``terminal_session.read_since``). Modeled on :meth:`_serve_term_sse` —
        bounded by ``max_ticks``, heartbeated, ends with a ``done`` event on a
        terminal (``dead``) status or when the tick budget elapses. Query knobs
        ``poll``/``max_ticks``/``hb``/``since`` mirror the v2 SSE handler.

        AUTH: ``?token=`` (401 when a token is configured and missing/wrong).
        """
        if not self._term_token_ok():
            self._send_json({"ok": False, "error": "unauthorized"}, 401)
            return
        q = parse_qs(urlparse(self.path).query)
        session = (q.get("session", [""])[0] or "").strip()
        try:
            since = int(q.get("since", ["0"])[0] or 0)
        except (TypeError, ValueError):
            since = 0
        if not session:
            self._send_json({"ok": False, "error": "missing session"}, 400)
            return
        try:
            poll_interval = float(q.get("poll", ["0.25"])[0] or 0.25)
        except (TypeError, ValueError):
            poll_interval = 0.25
        try:
            # High backstop (the loop ends on a terminal session or client
            # disconnect); the old 240/5000 ceiling froze the SSE fallback after
            # ~60s. Tests pass an explicit small max_ticks.
            max_ticks = int(q.get("max_ticks", ["4000000"])[0] or 4000000)
        except (TypeError, ValueError):
            max_ticks = 4000000
        # Clamp client-supplied knobs (self-DoS guard): poll in [0.01, 1.0]s,
        # max_ticks in [1, 4_000_000] (high backstop — loop ends on close/done).
        poll_interval = min(1.0, max(0.01, poll_interval))
        max_ticks = min(4000000, max(1, max_ticks))
        try:
            heartbeat_every = int(q.get("hb", ["8"])[0] or 8)
        except (TypeError, ValueError):
            heartbeat_every = 8

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        cursor = since
        last_status = None
        idle = 0
        try:
            # ── attach-ack / replay-complete handshake (telemetry-resume W6) ──
            # The SSE fallback mirrors the WS attach-ack: a dead/unknown session
            # emits an explicit ``attach_ack ok:false`` event (the client paints
            # its error state) instead of a bare terminating stream; a live one
            # emits ``attach_ack ok:true`` + a ``replay_complete`` after the first
            # read, so the pane swaps in only once the buffer is replayed.
            try:
                first = _termsess.read_since(session, cursor)
            except Exception:
                first = {"ok": False, "reason": "error"}
            if not first.get("ok", True):
                self._sse_event("attach_ack", {"ok": False,
                                               "reason": first.get(
                                                   "reason", "unknown-session")})
                self._sse_event("done", {"status": "error",
                                         "next": cursor, "error": True})
                return
            self._sse_event("attach_ack", {"ok": True})
            ftext = first.get("text", "")
            if ftext:
                self._sse_event("output", {"text": ftext,
                                           "next": first.get("next", cursor)})
                cursor = first.get("next", cursor)
            self._sse_event("replay_complete", {"next": cursor})
            for _tick in range(max(1, max_ticks)):
                try:
                    out = _termsess.read_since(session, cursor)
                    if not out.get("ok", True):  # unknown session
                        self._sse_event("done", {"status": "error",
                                                 "next": cursor, "error": True})
                        return
                    text = out.get("text", "")
                    if text:
                        self._sse_event("output", {"text": text,
                                                   "next": out.get("next", cursor)})
                        cursor = out.get("next", cursor)
                        idle = 0
                    else:
                        idle += 1
                    status = out.get("status")
                    if status and status != last_status:
                        self._sse_event("status", {"status": status})
                        last_status = status
                    if status == "dead":
                        final = _termsess.read_since(session, cursor)
                        ft = final.get("text", "") if isinstance(final, dict) else ""
                        if ft:
                            self._sse_event("output", {"text": ft,
                                                       "next": final.get("next", cursor)})
                            cursor = final.get("next", cursor)
                        self._sse_event("done", {"status": status, "next": cursor})
                        return
                    if heartbeat_every and idle and idle % heartbeat_every == 0:
                        self._sse_event("heartbeat", {"next": cursor})
                except (BrokenPipeError, ConnectionResetError, OSError):
                    raise
                except Exception:
                    try:
                        self._sse_event("done", {"status": "error",
                                                 "next": cursor, "error": True})
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        pass
                    return
                time.sleep(max(0.0, poll_interval))
            self._sse_event("done", {"status": last_status or "running",
                                     "next": cursor, "bounded": True})
        except (BrokenPipeError, ConnectionResetError, OSError):
            return

    def _serve_term_ws(self):
        """Hand-rolled stdlib WebSocket terminal endpoint (Wave 3, RFC 6455).

        Detects the ``Upgrade: websocket`` handshake, authenticates via
        ``?token=`` (or the ``Sec-WebSocket-Protocol`` header), computes the
        ``Sec-WebSocket-Accept`` value, replies ``101 Switching Protocols``, then
        takes over the raw socket and pumps PTY bytes BOTH ways:

        - decode client frames (text/binary -> ``terminal_session.input``;
          close -> end; ping -> pong);
        - poll ``terminal_session.read_since`` for new output -> encode + send
          server text frames.

        The pump loop is BOUNDED/interruptible (``poll``/``max_ticks`` query
        knobs, same as the SSE handler) so it ends cleanly on client close or a
        terminal (``dead``) session and is testable without hanging.
        """
        # AUTH FIRST: never upgrade an unauthorized handshake.
        if not self._term_token_ok():
            self._send_json({"ok": False, "error": "unauthorized"}, 401)
            return

        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self._send_json({"ok": False, "error": "missing Sec-WebSocket-Key"},
                            400)
            return

        q = parse_qs(urlparse(self.path).query)
        session = (q.get("session", [""])[0] or "").strip()
        if not session:
            self._send_json({"ok": False, "error": "missing session"}, 400)
            return
        try:
            poll_interval = float(q.get("poll", ["0.05"])[0] or 0.05)
        except (TypeError, ValueError):
            poll_interval = 0.05
        try:
            # Default is effectively "for the life of the connection": the loop
            # already breaks on client close (recv b"") or a dead session, so this
            # is only a runaway backstop. The old 1200/5000 ceiling (~60-250s) was
            # the FREEZE bug — a multi-minute session lost its stream and went
            # silent. Tests pass an explicit small max_ticks via the query knob.
            max_ticks = int(q.get("max_ticks", ["4000000"])[0] or 4000000)
        except (TypeError, ValueError):
            max_ticks = 4000000
        # Clamp client-supplied knobs (self-DoS guard): poll in [0.01, 1.0]s,
        # max_ticks in [1, 4_000_000] (a high backstop — the loop ends on close).
        poll_interval = min(1.0, max(0.01, poll_interval))
        max_ticks = min(4000000, max(1, max_ticks))

        # ── 101 handshake ────────────────────────────────────────────────
        accept = ws_accept_key(key)
        handshake = (
            "HTTP/1.1 101 Switching Protocols\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            "Sec-WebSocket-Accept: " + accept + "\r\n"
            "\r\n"
        )
        try:
            self.connection.sendall(handshake.encode("ascii"))
        except OSError:
            return

        # ── raw-socket pump (both ways), bounded + interruptible ─────────
        sock = self.connection
        sock.settimeout(max(0.01, poll_interval))
        inbuf = b""
        # CURSOR RESUME (2026-07-26 hardening, P0.1). This used to hard-code
        # ``cursor = 0``, so every WS (re)attach replayed the ENTIRE retained
        # 200KB PTY buffer on top of whatever the client already had on screen —
        # the terminal double-printing. The SSE path already honored ``since``;
        # the WS path had no knob at all. Same parse, same clamp, same default.
        try:
            _q = parse_qs(urlparse(self.path).query)
            cursor = int(_q.get("since", ["0"])[0] or 0)
            if cursor < 0:
                cursor = 0
        except Exception:
            cursor = 0
        ws_state = {}  # persistent fragmentation-reassembly state for decode_frames
        try:
            # ── attach-ack / replay-complete handshake (telemetry-resume W6) ──
            # Resolve the session BEFORE the pump and send an explicit ack: a
            # dead/unknown session yields ``attach_ack ok:false`` (the client
            # paints its styled error state, narration still visible) rather than
            # the old SILENT break that wrote zero bytes → a blank pane (diag-B2
            # S1). A live session gets ``attach_ack ok:true``, its buffered output
            # is replayed, then ``replay_complete`` — the client swaps in the live
            # pane ONLY after that signal, so a blank pane is a protocol
            # impossibility.
            try:
                first = _termsess.read_since(session, cursor)
            except Exception:
                first = {"ok": False, "reason": "error"}
            if not first.get("ok", True):
                try:
                    sock.sendall(ws_ctl_frame({
                        "type": "attach_ack", "ok": False,
                        "reason": first.get("reason", "unknown-session")}))
                except OSError:
                    pass
                return  # finally sends the close frame; client shows error state
            try:
                sock.sendall(ws_ctl_frame({"type": "attach_ack", "ok": True,
                                           "session": session}))
                replay = first.get("text", "")
                if replay:
                    sock.sendall(encode_text_frame(replay))
                cursor = first.get("next", cursor)
                sock.sendall(ws_ctl_frame({"type": "replay_complete",
                                           "next": cursor}))
            except (BrokenPipeError, ConnectionResetError, OSError):
                return
            for _tick in range(max(1, max_ticks)):
                # 1) Drain client -> PTY (non-blocking-ish via the socket timeout).
                try:
                    chunk = sock.recv(65536)
                    if chunk == b"":
                        break  # client closed the TCP connection
                    inbuf += chunk
                    # Guard the carried inbuf so an endless stream of incomplete
                    # frame headers can't grow it without bound either.
                    if len(inbuf) > MAX_WS_FRAME:
                        break
                    msgs, inbuf = decode_frames(inbuf, ws_state,
                                                require_mask=True)
                    closed = False
                    for opcode, payload in msgs:
                        if opcode in (WS_SIGNAL_CLOSE, WS_OP_CLOSE):
                            # Protocol error or a client close -> clean close.
                            closed = True
                            break
                        if opcode == WS_OP_PING:
                            try:
                                sock.sendall(encode_pong_frame(payload))
                            except OSError:
                                closed = True
                                break
                            continue
                        if opcode == WS_OP_PONG:
                            continue  # unsolicited pong — ignore
                        if opcode in (WS_OP_TEXT, WS_OP_BINARY):
                            # Reassembled, complete data message (CONT frames are
                            # folded in by the codec — never delivered alone).
                            data = payload.decode("utf-8", "replace")
                            res = _termsess.input(session, data)
                            if not res.get("ok"):
                                closed = True
                                break
                    if closed:
                        break
                except socket.timeout:
                    pass
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break

                # 2) Pump PTY -> client.
                try:
                    out = _termsess.read_since(session, cursor)
                except Exception:
                    break
                if not out.get("ok", True):
                    break  # unknown session
                text = out.get("text", "")
                if text:
                    try:
                        sock.sendall(encode_text_frame(text))
                    except (BrokenPipeError, ConnectionResetError, OSError):
                        break
                    cursor = out.get("next", cursor)
                if out.get("status") == "dead":
                    # Drain any final output, then close cleanly.
                    final = _termsess.read_since(session, cursor)
                    ft = final.get("text", "") if isinstance(final, dict) else ""
                    if ft:
                        try:
                            sock.sendall(encode_text_frame(ft))
                        except OSError:
                            pass
                    break
        finally:
            try:
                sock.sendall(encode_close_frame())
            except OSError:
                pass

    def do_GET(self):
        try:
            _path_only = urlparse(self.path).path
            if (self.headers.get("Upgrade", "").lower() == "websocket"
                    and _path_only == "/api/rnd/term_ws"):
                # Hand-rolled stdlib WebSocket terminal transport (Wave 3). Must
                # be checked BEFORE the normal GET dispatch because it takes over
                # the raw socket. Auth-gated inside (?token=).
                self._serve_term_ws()
                return
            if _path_only == "/api/rnd/term_stream2":
                # SSE-out fallback for a ConPTY session (Wave 3). Auth-gated
                # inside (?token=). Distinct from the v2 /api/rnd/term_stream.
                self._serve_term_stream2()
                return
            # Strangler dispatch (rearch W7 / C2): the declarative route table
            # is consulted FIRST; a matched, migrated GET row is handled here
            # (with the row's auth applied first). Anything unmatched or not-yet-
            # migrated falls through to the legacy if/elif chain below unchanged.
            if self._strangler_dispatch("GET", _path_only, None):
                return
            # Data-plane auth-mode overlay (rearch W8 warn / W9 enforce). In
            # 'open' mode this is a no-op; in 'warn' it logs would-401 consumers
            # for the soak but still serves; in 'enforce' a tokenless request to
            # the gated batch is 401'd here before the legacy handler runs.
            if self._data_plane_gate("GET", _path_only):
                return
            if _path_only == "/" or _path_only == "/dashboard":
                # Serve the dashboard for "/" REGARDLESS of query string so the
                # cache-busting reload ("/?v=<build_id>") lands on the dashboard
                # instead of 404ing.
                projects, tasks, inbox = gather_all()
                html = generate_html(projects, tasks, inbox)
                self._send_html(html)
            elif _path_only == "/doctor":
                # Doctor V3 Wave 3 — the honest diagnostics page in Anchor's
                # own style (render_doctor_page_html: real stats from
                # health_reports/, the Wave-2 agentic terminal, the background
                # diagnostics tail). The V2 standalone-product mock (fake disk
                # usage, fake chart, dead nav, f-string {placeholder} bug) is
                # gone; the doctor gate regression-tests its absence.
                self._send_html(render_doctor_page_html())
            elif _path_only == "/foundry" or _path_only == "/foundry/":
                # Foundry GUI (folded-in React app): serve the built SPA
                # (foundry-gui/dist/index.html). Its absolute /assets, /brand
                # and /api/* calls are answered by the routes below + the
                # foundry_api layer — no standalone node sidecar, no port 8780.
                idx, ctype = _fapi.resolve_dist_file("index.html")
                if idx is None:
                    # dist/ missing (React app not built) — fall back to the
                    # stateless Python read page so /foundry never 404s.
                    q = parse_qs(urlparse(self.path).query)
                    self._send_html(_fgui.render_foundry_page(
                        lane=(q.get("lane") or [None])[0],
                        job_id=(q.get("job") or [None])[0]))
                else:
                    self._send_bytes(idx.read_bytes(), ctype, cache="no-cache")
            elif _path_only.startswith("/assets/") or _path_only.startswith("/brand/"):
                # Static assets for the folded-in Foundry React app — traversal-
                # safe, resolved strictly inside foundry-gui/dist. The bundle's
                # filenames are content-hashed, so they cache immutably.
                target, ctype = _fapi.resolve_dist_file(_path_only)
                if target is None:
                    self._send_json({"error": "not found"}, 404)
                else:
                    self._send_bytes(target.read_bytes(), ctype,
                                     cache="public, max-age=86400")
            elif _path_only in ("/api/skills", "/api/north-star", "/api/summary",
                                "/api/timeline", "/api/metrics",
                                "/api/agent-payload"):
                # The folded-in Foundry GUI's READ data-plane (ports of
                # server.mjs): every value traces to a real file on disk; a
                # missing file is an honest empty. Read-only, open (same as the
                # /foundry page); the app calls these same-origin, tokenless.
                if _path_only == "/api/skills":
                    self._send_json(_fapi.build_skills())
                elif _path_only == "/api/north-star":
                    self._send_json({"northStar": _fapi.load_north_star()})
                elif _path_only == "/api/summary":
                    self._send_json({"summary": _fapi.build_summary()})
                elif _path_only == "/api/timeline":
                    self._send_json(_fapi.build_timeline())
                elif _path_only == "/api/metrics":
                    self._send_json(_fapi.build_metrics())
                else:
                    self._send_json(_fapi.build_agent_payload())
            # /api/version migrated to route_table (handle_version, W7 batch 1) —
            # served by the strangler above.
            elif self.path == "/favicon.ico" or self.path.startswith("/anchor.ico"):
                ico_path = ANCHOR_DIR / "anchor.ico"
                if ico_path.exists():
                    self.send_response(200)
                    self.send_header("Content-Type", "image/x-icon")
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(ico_path.read_bytes())
                else:
                    self.send_response(404)
                    self.end_headers()
            elif self.path.startswith("/anchor.png"):
                png_path = ANCHOR_DIR / "anchor.png"
                if png_path.exists():
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(png_path.read_bytes())
                else:
                    self.send_response(404)
                    self.end_headers()
            elif self.path.startswith("/zombie_radar.jpg"):
                jpg_path = ANCHOR_DIR / "zombie_radar.jpg"
                if jpg_path.exists():
                    self.send_response(200)
                    self.send_header("Content-Type", "image/jpeg")
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(jpg_path.read_bytes())
                else:
                    self.send_response(404)
                    self.end_headers()
            elif self.path.startswith("/anchor-touch.png"):
                png_path = ANCHOR_DIR / "anchor-touch.png"
                if png_path.exists():
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Cache-Control", "public, max-age=86400")
                    self.end_headers()
                    self.wfile.write(png_path.read_bytes())
                else:
                    self.send_response(404)
                    self.end_headers()
            # /api/status migrated to route_table (handle_status, W7 batch 1) —
            # served by the strangler above.
            elif self.path.startswith(_rv.KATEX_URL_PREFIX):
                # Read-only vendored KaTeX static assets for the Reader (Wave 7).
                rel = urlparse(self.path).path[len(_rv.KATEX_URL_PREFIX):]
                asset = _rv.katex_asset(rel)
                if asset is None:
                    self.send_response(404)
                    self.end_headers()
                else:
                    data, ctype = asset
                    self._send_bytes(data, ctype, cache="public, max-age=86400")
            elif self.path.startswith(XTERM_URL_PREFIX):
                # Read-only vendored REAL xterm.js static asset (terminal canvas),
                # served like KaTeX (traversal-safe). Loaded before anchor-term.js.
                rel = urlparse(self.path).path[len(XTERM_URL_PREFIX):]
                asset = xterm_asset(rel)
                if asset is None:
                    self.send_response(404)
                    self.end_headers()
                else:
                    data, ctype = asset
                    self._send_bytes(data, ctype, cache="public, max-age=86400")
            elif self.path.startswith(BRAND_URL_PREFIX):
                # Read-only vendored Ghost World Labs brand mark static asset
                # (Wave 9), served like KaTeX/xterm (traversal-safe). Backs the
                # home-page lockup and the dashboard favicon.
                rel = urlparse(self.path).path[len(BRAND_URL_PREFIX):]
                asset = brand_asset(rel)
                if asset is None:
                    self.send_response(404)
                    self.end_headers()
                else:
                    data, ctype = asset
                    self._send_bytes(data, ctype, cache="public, max-age=86400")
            elif self.path.startswith(STATIC_URL_PREFIX + "/"):
                # Read-only extracted app-frontend static asset (rearch W4:
                # C1 increment 1 — the project-window app JS), served through
                # the SAME traversal-safe resolve()+relative_to idiom as the
                # vendored assets (zero new security surface). The long
                # max-age is safe because every reference carries a
                # content-hash ?v= minted at startup from the file bytes.
                rel = urlparse(self.path).path[len(STATIC_URL_PREFIX):]
                asset = static_asset(rel)
                if asset is None:
                    self.send_response(404)
                    self.end_headers()
                else:
                    data, ctype = asset
                    self._send_bytes(data, ctype, cache="public, max-age=86400")
            elif self.path.startswith(ANCHOR_TERM_URL_PREFIX):
                # Read-only vendored terminal-console static asset (Wave 7),
                # served like KaTeX (traversal-safe). Backs the interactive
                # terminal that replaced the raw-log launch console.
                rel = urlparse(self.path).path[len(ANCHOR_TERM_URL_PREFIX):]
                asset = anchor_term_asset(rel)
                if asset is None:
                    self.send_response(404)
                    self.end_headers()
                else:
                    data, ctype = asset
                    self._send_bytes(data, ctype, cache="public, max-age=3600")
            elif self.path.startswith("/api/rnd/term_stream"):
                # SSE (Server-Sent Events) stream of a terminal session's output
                # (Wave 7). Implemented on stdlib http.server as a chunked
                # text/event-stream response loop: it flushes "output"/"status"/
                # "gate" events as new lines arrive, emits periodic "heartbeat"
                # events, and TERMINATES cleanly with a "done" event when the
                # session reaches a terminal status OR a bounded number of ticks
                # elapses. The bound (max_ticks) makes it TESTABLE without
                # hanging: a client reads a finite set of events and the stream
                # ends. The ThreadingHTTPServer handles concurrent streams.
                self._serve_term_sse()
            elif self.path.startswith("/report/"):
                # Read-only report viewer (Wave 7): PDF-by-default else Reader.
                # /report/<project_id>/<lane>[/<job_id>]
                parts = [p for p in urlparse(self.path).path[len("/report/"):]
                         .split("/") if p]
                if len(parts) < 2:
                    self.send_response(404)
                    self.end_headers()
                else:
                    pid, lane = parts[0], parts[1]
                    job_id = parts[2] if len(parts) > 2 else None
                    # Reject path-separator / traversal in the path-bound
                    # segments before they hit the filesystem (consistent with
                    # the hardened KaTeX static route).
                    if any(_unsafe_path_seg(seg)
                           for seg in (lane, job_id) if seg is not None):
                        self.send_response(400)
                        self.end_headers()
                        return
                    proj = _rnd.get_project(pid)
                    folder = (proj or {}).get("folder_path", "")
                    out = _rv.render_effort(folder, pid, lane, job_id)
                    body = out["body"]
                    if isinstance(body, str):
                        body = body.encode("utf-8")
                    self._send_bytes(body, out["content_type"])
            elif self.path.startswith("/summary/"):
                # Read-only cached session SUMMARY page (Wave 6): the validated,
                # cached markdown summary (goal · key decisions · files-with-
                # links) rendered via report_viewer (vendored KaTeX). Generated
                # once on first view (run-once), then served from cache.
                # /summary/<project_id>/<lane>/<session_id>
                parts = [p for p in urlparse(self.path).path[len("/summary/"):]
                         .split("/") if p]
                if len(parts) < 3:
                    self.send_response(404)
                    self.end_headers()
                else:
                    pid, lane = parts[0], parts[1]
                    # The session_id may itself contain '/'-free '::' segments;
                    # rejoin any remaining components defensively.
                    session_id = "/".join(parts[2:])
                    if _unsafe_path_seg(lane):
                        self.send_response(400)
                        self.end_headers()
                        return
                    proj = _rnd.get_project(pid)
                    folder = (proj or {}).get("folder_path", "")
                    # Look up the live session record so an uncached summary can
                    # be generated on first view (run-once).
                    session = None
                    try:
                        for s in _sessions.list_sessions(folder, pid, lane):
                            if s.get("session_id") == session_id:
                                session = s
                                break
                    except Exception:
                        session = None
                    out = _summarizer.render_summary_page(
                        folder, pid, lane, session_id, session=session)
                    body = out["body"]
                    if isinstance(body, str):
                        body = body.encode("utf-8")
                    self._send_bytes(body, out["content_type"])
            # /api/rnd/handoff_proposal migrated to route_table (handle_handoff_proposal) — served by the strangler above.
            # /api/rnd/project_files migrated to route_table (handle_project_files) — served by the strangler above.

            # /api/rnd/project_file_content migrated to route_table (handle_project_file_content) — served by the strangler above.

            # /api/rnd/session_summary migrated to route_table (handle_session_summary) — served by the strangler above.
            # /api/rnd/session_doc_roles migrated to route_table (handle_session_doc_roles) — served by the strangler above.
            # /api/rnd/context_status migrated to route_table (handle_context_status) — served by the strangler above.
            # /api/rnd/effort_rollup migrated to route_table
            # (handle_effort_rollup) — served by the strangler above.
            # /api/rnd/build_deliverable migrated to route_table
            # (handle_build_deliverable) — served by the strangler above.
            # /api/rnd/grass migrated to route_table (handle_grass) — served by the strangler above.
            # /api/rnd/gandalf migrated to route_table (handle_gandalf) — served by the strangler above.
            # /api/rnd/gandalf_status migrated to route_table (handle_gandalf_status) — served by the strangler above.
            # /api/rnd/gandalf_status_all migrated to route_table (handle_gandalf_status_all) — served by the strangler above.
            # /api/rnd/orphan_check migrated to route_table (handle_orphan_check)
            # — served by the strangler above.
            # /api/rnd/zombie_hunter_report migrated to route_table (handle_zombie_hunter_report) — served by the strangler above.
            # /api/rnd/reaper_status migrated to route_table (handle_reaper_status)
            # — served by the strangler above.
            # /api/rnd/boneyard migrated to route_table (handle_boneyard) —
            # served by the strangler above.
            # /api/rnd/remote_status migrated to route_table (handle_remote_status)
            # — served by the strangler above.
            # /api/rnd/project_rollup migrated to route_table
            # (handle_project_rollup) — served by the strangler above.
            elif self.path.startswith("/artifact/"):
                # Read-only serving of a DISCOVERED (brownfield) artifact from a
                # project's folder (Wave 4). Traversal-safe via the proven
                # report_viewer.katex_asset containment pattern:
                #   target=(folder/rel).resolve(); target.relative_to(folder)
                # Rejects absolute rel, ../.. escape, .git/.anchor, symlink
                # escape -> 400/404, ZERO bytes read.
                pid = urlparse(self.path).path[len("/artifact/"):].strip("/")
                q = parse_qs(urlparse(self.path).query)
                rel = q.get("path", [None])[0]
                if not pid or not rel:
                    self.send_response(400)
                    self.end_headers()
                    return
                proj = _rnd.get_project(pid)
                folder = (proj or {}).get("folder_path", "")
                if not folder:
                    self.send_response(404)
                    self.end_headers()
                    return
                asset = _rv.resolve_project_artifact(folder, rel)
                if asset is None:
                    self.send_response(404)
                    self.end_headers()
                else:
                    data, ctype = asset
                    # v13 Wave 1 — rich markdown rendering for report links. With
                    # ?render=1 a MARKDOWN artifact is served as a fully rendered
                    # Reader page (the EXISTING report_viewer markdown logic +
                    # vendored KaTeX), so the Gandalf "Full report" link opens rich
                    # HTML in the unified anchor_report_window instead of raw text.
                    # Without the flag the raw bytes are served (UNCHANGED) — so the
                    # inline exec-summary fetch still gets raw md to render
                    # client-side via marked.parse, and every other /artifact
                    # consumer keeps its current raw behavior. Non-markdown is
                    # always raw, even with render=1.
                    want_render = (q.get("render", [""])[0] or "").strip()
                    if want_render and "markdown" in (ctype or ""):
                        try:
                            md_text = data.decode("utf-8", "replace")
                            title = Path(rel).name or "Report"
                            self._send_html(_rv.reader_html(md_text, title))
                        except Exception:
                            self._send_bytes(data, ctype)
                    else:
                        self._send_bytes(data, ctype)
            # /zombie_terminal migrated to route_table (handle_zombie_terminal) — served by the strangler above.
            elif self.path.startswith("/project/"):
                # Per-project window (Wave 3 basic view + 4-state status line).
                # Opening a brownfield project DISCOVERS + ADOPTS its on-disk
                # trio artifacts so the Kanban/tile/home panel populate (Wave 6).
                pid = urlparse(self.path).path[len("/project/"):].strip("/")
                try:
                    discover_and_adopt(pid)
                except Exception:
                    pass  # discovery is best-effort; never block the view
                self._send_html(render_project_window_html(pid))
            # /api/rnd/term_sessions migrated to route_table (handle_term_sessions) — served by the strangler above.
            # /api/rnd/chain migrated to route_table (handle_chain) — served by
            # the strangler above.
            # /api/rnd/board_html migrated to route_table (handle_board_html) — served by the strangler above.
            # /api/rnd/projects_html migrated to route_table (handle_projects_html) — served by the strangler above.
            elif self.path.startswith("/api/rnd/projects"):
                # Read-only: folder-grouped registry listing.
                self._send_json({"ok": True,
                                 "groups": _rnd.group_by_folder()})
            # /api/rnd/dir_browse migrated to route_table (handle_dir_browse,
            # W8 migration batch) — served by the strangler above.
            elif self.path.startswith("/api/rnd/tail"):
                # Read-only incremental log tail for the project-window console
                # drawer. Returns {lines,next,status,pending_prompt}. This is a
                # plain non-blocking ?since= fetch (the JS polls ~1.5s); it never
                # holds the request, so it can't stall the dashboard.
                q = parse_qs(urlparse(self.path).query)
                job_id = (q.get("job_id", [""])[0] or "").strip()
                try:
                    since = int(q.get("since", ["0"])[0] or 0)
                except (TypeError, ValueError):
                    since = 0
                if not job_id:
                    self._send_json({"ok": False, "error": "missing job_id"}, 400)
                else:
                    # rearch W15: read through the supervisor seam so job
                    # ownership is a single swap point (inline today, external
                    # in W16). Persist the served offset as the durable read
                    # cursor so a client resumes across a restart.
                    out = _sup.get_supervisor().tail(job_id, since, persist=True)
                    try:
                        pending = _gate.load_pending_prompt(job_id)
                    except Exception:
                        pending = None
                    self._send_json({
                        "ok": True,
                        "lines": out.get("lines", []),
                        "next": out.get("next", since),
                        "total": out.get("total", 0),
                        "status": out.get("status"),
                        "pending_prompt": pending,
                    })
            elif self.path.startswith("/api/rnd/jobs"):
                # Read-only: recent job records for a project (lane status).
                q = parse_qs(urlparse(self.path).query)
                pid = (q.get("project_id", [""])[0] or "").strip()
                jobs = [r for r in _jr.list_records()
                        if not pid or r.get("project_id") == pid]
                jobs.sort(key=lambda r: r.get("started_at") or 0, reverse=True)
                self._send_json({"ok": True, "jobs": jobs})
            # /api/rnd/previews migrated to route_table (handle_previews) — served by the strangler above.
            else:
                self.send_response(404)
                self.end_headers()
        except Exception as e:
            if _is_benign_disconnect(e):
                # Client closed the connection mid-GET (browser tab close /
                # Playwright teardown). Not a server error — stop silently;
                # the socket is gone so there's nothing to write back.
                return
            _logger.error(f"GET {self.path} failed: {e}\n{traceback.format_exc()}")
            self._send_json({"ok": False, "error": str(e)}, 500)

    def do_POST(self):
      try:
        content_len = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(content_len)) if content_len > 0 else {}

        # Contract-versioning shim (re-architecture 2026-07 · W2). A browser
        # page declares the build id it was rendered from (window.ANCHOR_BOOT
        # → the X-Anchor-Build header on every _postJson/apiCall). A mismatch
        # means the tab predates the current deploy (stale JS about to call a
        # migrated server): answer a STRUCTURED 409 the old client renders as
        # the 'reload required' banner — never an opaque failure. Consumers
        # that declare no build (healthcheck, CLI, curl) are never blocked.
        # Checked BEFORE auth so a stale tab learns 'reload' instead of
        # re-prompting for a token (the build id is already public via
        # GET /api/version — nothing new is leaked).
        client_build = (self.headers.get("X-Anchor-Build") or "").strip()
        if client_build and client_build != BUILD_ID:
            self._send_json({
                "ok": False,
                "error": BUILD_MISMATCH_ERROR,
                "reason": "reload-required",
                "server_build": BUILD_ID,
                "client_build": client_build,
                "action": "reload",
            }, 409)
            return

        # Token-auth middleware (Wave 2 / D4). Every mutating /api/* POST
        # requires a valid shared-secret token when ANCHOR_TOKEN is configured.
        # If ANCHOR_TOKEN is unset, auth is disabled (local-only back-compat).
        # The token may be supplied via the X-Anchor-Token header (preferred
        # by the browser clients), the standard Authorization header
        # (Bearer <token> or a bare token — the rearch-W2 path every
        # non-browser consumer uses), or a "token" field in the JSON body.
        # Read endpoints are not gated.
        provided = self.headers.get("X-Anchor-Token")
        if provided is None:
            provided = _paths.token_from_authorization(
                self.headers.get("Authorization"))
        if provided is None and isinstance(body, dict):
            provided = body.get("token")
        # Default-deny by construction, driven by the declared route table (W7):
        # a POST is gated UNLESS its row explicitly declares ``auth == open``. No
        # POST is open today, so behavior is unchanged — but the middleware now
        # DEFERS to the reviewed table (+ OPEN_ROUTES) instead of blanket-gating,
        # so an undeclared POST is still default-denied while a future reviewed
        # open POST would be honored (rearch W8: post-middleware consults the
        # route-table auth policy).
        _post_route = _routes.match("POST", urlparse(self.path).path)
        _post_open = (_post_route is not None
                      and _post_route.auth == _routes.AUTH_OPEN)
        if not _post_open and not _paths.auth_ok(provided):
            self._send_json({"ok": False, "error": "unauthorized"}, 401)
            return

        # Strangler dispatch (rearch W7 / C2): consult the declarative route
        # table FIRST. Runs AFTER the token middleware, so a migrated POST row is
        # already authenticated. Unmatched / not-yet-migrated POSTs fall through
        # to the legacy if/elif chain below unchanged.
        #
        # (2026-07-30 FIX) Dispatch on the PATH-ONLY string, exactly like the
        # auth lookup two lines up (and like do_GET, which already passes
        # ``_path_only``). ``_routes.match`` compares an EXACT row with ``path ==
        # pattern``, so passing the raw request line meant ANY POST carrying a
        # query string missed its exact row, fell through the strangler, and
        # answered 404 "Unknown endpoint". That is what broke every steward act
        # (/api/ecgberht/stand_up?token=… → "Couldn't do that: Unknown
        # endpoint"): the URLs carry ?token=, so with auth ON they could never
        # dispatch — and with auth OFF the query is empty, which is why the
        # suites never saw it. Handlers still receive the FULL URI (query
        # included) — _strangler_dispatch passes ``self.path`` to the handler.
        if self._strangler_dispatch("POST", urlparse(self.path).path, body):
            return
            
        # /api/doctor/run removed (doctor V3 wave 1). The V2 handler spawned a
        # third-party Gemini API-key wrapper script (deleted; stdlib-only
        # violation, unusable on a subscription-CLI host) and ran
        # anchor_healthcheck.py synchronously in the request thread for up to
        # 75s. V3 replaces them with a real agentic session on the existing PTY
        # substrate (wave 2) and a background healthcheck run with a live tail
        # (wave 3). An unmatched POST here falls through to the 404 below.

        # /api/rnd/upload_batch migrated to route_table (handle_upload_batch) — served by the strangler above.
        # /api/upload migrated to route_table (handle_upload) — served by the strangler above.
        # /api/rnd/reaper_arm, /api/rnd/reaper_advance, /api/rnd/reaper_disarm
        # migrated to route_table — served by the strangler above.
        # 2026-05-12: /api/shutdown removed. The NSSM "anchor" service owns
        # process lifecycle; the dashboard cannot kill the server.
        # Any POST not handled by the strangler above is an unknown endpoint.
        self._send_json({"ok": False, "error": "Unknown endpoint"}, 404)
      except Exception as e:
            if _is_benign_disconnect(e):
                # Client closed the connection mid-POST. Not a server error.
                return
            _logger.error(f"POST {self.path} failed: {e}\n{traceback.format_exc()}")
            self._send_json({"ok": False, "error": str(e)}, 500)


_server_instance = None
_last_heartbeat = None
_heartbeat_active = False  # Only start monitoring after the first heartbeat arrives


def _heartbeat_watchdog():
    """Background thread: heartbeat monitoring disabled.

    The server now runs until explicitly stopped — via the Stop button in the
    dashboard, Ctrl+C in the terminal, or by killing the Python process. This
    keeps the dashboard instantly available when the user comes back to the
    tab after any amount of time.
    """
    return


class _QuietDisconnectMixin:
    """Server mixin that quiets BENIGN client-disconnect errors.

    socketserver calls ``handle_error(request, client_address)`` when a request
    handler raises an unhandled exception, and by default it prints a full
    traceback to stderr. A browser closing a terminal tab (or Playwright tearing
    a page down) makes an in-flight SSE/WS/HTTP write raise
    ``ConnectionAbortedError``/``ConnectionResetError``/``BrokenPipeError`` (on
    Windows often a bare ``OSError`` with ``winerror`` 10053/10054). That is the
    client going away, not a server bug — so we swallow it silently here as a
    last line of defense (the handlers already break out of their stream loops
    on these). Any OTHER exception still gets the normal noisy traceback so real
    defects are never hidden.
    """

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if _is_benign_disconnect(exc):
            return
        super().handle_error(request, client_address)


class _ExclusiveThreadingHTTPServer(_QuietDisconnectMixin, ThreadingHTTPServer):
    """ThreadingHTTPServer that claims EXCLUSIVE ownership of its port.

    On Windows, ``socket.SO_EXCLUSIVEADDRUSE`` guarantees only ONE process can
    own the listening port — so a duplicate/orphan Anchor process can never
    silently squat 8777 and serve stale code. We deliberately turn OFF
    ``allow_reuse_address`` (HTTPServer enables SO_REUSEADDR by default, which
    is what permits port sharing) and set SO_EXCLUSIVEADDRUSE before binding.

    Used ONLY for the real fixed-port path (see ``make_server``). The ephemeral
    ``port=0`` path used by the tests/health check keeps the default behavior.
    """

    # HTTPServer sets this to 1 (SO_REUSEADDR). Force it off for exclusivity.
    allow_reuse_address = False

    def server_bind(self):
        try:
            self.socket.setsockopt(
                socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1
            )
        except (AttributeError, OSError):
            # SO_EXCLUSIVEADDRUSE is Windows-only; on any platform/socket that
            # rejects it, fall back to the default bind (use_exclusive_bind
            # already gates us to Windows, so this is just belt-and-suspenders).
            pass
        super().server_bind()


class _PosixExclusiveThreadingHTTPServer(_QuietDisconnectMixin, ThreadingHTTPServer):
    """ThreadingHTTPServer that claims single-ownership of its port on POSIX.

    share-distro v1 Wave 2 (MASTER-PLAN decision #6 — POSIX single-instance
    guard). macOS/Linux have no ``SO_EXCLUSIVEADDRUSE``; instead the guard simply
    leaves ``SO_REUSEADDR`` **OFF** (``allow_reuse_address = False``) for the real
    fixed port. A second Anchor binding the same port then fails with
    ``EADDRINUSE`` — which ``paths.classify_bind_error`` maps to a clean
    ``exit(0)`` in ``main`` (exactly the Windows ``SO_EXCLUSIVEADDRUSE`` parity:
    one mechanism, no pidfile). Used ONLY for the real fixed-port path on
    non-Windows (see ``make_server``); the ephemeral ``port=0`` path is unaffected.
    """

    # HTTPServer sets this to 1 (SO_REUSEADDR). Force it off so a duplicate bind
    # on the same fixed port raises EADDRINUSE instead of silently sharing it.
    allow_reuse_address = False


class _QuietThreadingHTTPServer(_QuietDisconnectMixin, ThreadingHTTPServer):
    """Plain ThreadingHTTPServer for the ephemeral ``port=0`` path (tests /
    health check) that also quiets benign client-disconnect errors — so a
    Playwright teardown racing an in-flight stream can't print a traceback or
    flake the gate."""
    daemon_threads = True


def make_server(host="127.0.0.1", port=8777):
    """Construct + bind the threading HTTP server.

    Two distinct bind-failure modes are reconciled here (D4/Wave 2 + Wave 3
    single-instance guard):

    - **Transient** failures (e.g. EADDRNOTAVAIL — a slow-to-come-up Tailscale
      interface not yet assignable) are retried by ``paths.bind_with_retry``.
    - **Address already owned by another Anchor** (EADDRINUSE) is NOT retried —
      ``bind_with_retry`` re-raises it immediately so the caller can exit
      cleanly instead of spinning into a bad state.

    For the real fixed port (non-zero, on Windows) we bind with
    SO_EXCLUSIVEADDRUSE so the OS guarantees a single owner. The ``port=0``
    ephemeral path (tests / health check) keeps the default ThreadingHTTPServer
    behavior so OS-assigned ports are unaffected.
    """
    if _paths.use_exclusive_bind(host, port):
        # Windows real fixed port → SO_EXCLUSIVEADDRUSE single-owner guard.
        server_cls = _ExclusiveThreadingHTTPServer
    elif _paths.use_posix_exclusive_bind(host, port):
        # POSIX real fixed port → SO_REUSEADDR OFF so a duplicate bind raises
        # EADDRINUSE → classify_bind_error → clean exit(0) (Wave-2 parity).
        server_cls = _PosixExclusiveThreadingHTTPServer
    else:
        # Ephemeral port=0 (tests / health check) → unchanged default behavior.
        server_cls = _QuietThreadingHTTPServer
    return _paths.bind_with_retry(
        lambda: server_cls((host, port), AnchorHandler)
    )


_LOOPBACK_HOSTS = ("127.0.0.1", "::1", "localhost")


def resolve_bind_host():
    """Resolve the server bind host from ``ANCHOR_BIND`` (default loopback).

    Set ``ANCHOR_BIND`` to the Tailscale IP (e.g. ``100.69.215.4``) to expose the
    dashboard over the tailnet. SAFETY (D4): refuse a non-loopback bind unless
    ``ANCHOR_TOKEN`` is configured — otherwise every mutating ``/api/*`` endpoint
    (including the ``bypassPermissions`` build lane) would be reachable
    unauthenticated. Returns the host string; raises ``RuntimeError`` for the
    unsafe combination so ``main`` can refuse to start.
    """
    host = (os.environ.get("ANCHOR_BIND") or "127.0.0.1").strip() or "127.0.0.1"
    if host not in _LOOPBACK_HOSTS and _paths.expected_token() is None:
        raise RuntimeError(
            f"Refusing to bind {host} without ANCHOR_TOKEN set — that would "
            f"expose mutating endpoints (incl. the build lane) unauthenticated. "
            f"Set ANCHOR_TOKEN, or use ANCHOR_BIND=127.0.0.1 for local-only."
        )
    return host


def main():
    global _server_instance, _PROACTIVE_SUMMARY_ENABLED, _zombie_hunter_started
    # The live server proactively (re)generates the cached project summary on
    # rescan/discovery (Wave 5). Unit tests leave this off (default) so importing
    # the module never spawns a background model job.
    #
    # v1.1.3 share-fix: an EXPLICIT off (ANCHOR_PROACTIVE_SUMMARY=0/off/false/no)
    # is now honored — background summaries spawn `claude` against the HOST'S
    # subscription with zero user action, so shared installs default them OFF
    # (share_onboard.spawn_anchor_server sets the flag; summaries stay available
    # on demand — the render path always reads the cache, and regenerate is an
    # explicit click). An UNSET flag keeps today's author behavior: force-on.
    if not _proactive_summary_pref(os.environ.get("ANCHOR_PROACTIVE_SUMMARY")):
        _PROACTIVE_SUMMARY_ENABLED = False
    else:
        _PROACTIVE_SUMMARY_ENABLED = True
        # v11.1 Wave 1 FIX-3: the keystone's background transcript-refine summary
        # (terminal_session._trigger_background_source_summary) gates on the
        # ANCHOR_PROACTIVE_SUMMARY env flag — it reads the env directly to avoid
        # an import cycle (terminal_session must not import anchor_gui). Set it
        # here in the SERVER main() path (never imported, never run in
        # tests/healthcheck) so the refine actually fires in production.
        # Tests/the 5 AM healthcheck never call main(), so they keep the flag
        # unset/OFF and never spawn live claude.
        os.environ["ANCHOR_PROACTIVE_SUMMARY"] = "1"
    port = 8777
    no_browser = "--no-browser" in sys.argv
    if "--port" in sys.argv:
        idx = sys.argv.index("--port")
        if idx + 1 < len(sys.argv):
            port = int(sys.argv[idx + 1])

    try:
        bind_host = resolve_bind_host()
    except RuntimeError as exc:
        print(str(exc))
        try:
            _logger.error(str(exc))
        except Exception:
            pass
        sys.exit(1)

    try:
        server = make_server(bind_host, port)
    except OSError as exc:
        # Single-instance guard: another healthy Anchor already owns this port.
        # Do NOT retry-forever or fight for the port — exit cleanly so the
        # existing server keeps serving and we never become a stale duplicate.
        if _paths.classify_bind_error(exc) == "exit":
            msg = (
                f"Anchor already running on {port} — this instance is exiting "
                f"to avoid a duplicate."
            )
            print(msg)
            try:
                _logger.warning(msg)
            except Exception:
                pass
            sys.exit(0)
        raise
    _server_instance = server
    # Browser/log URL: localhost for a loopback bind, else the bound interface.
    url = (f"http://localhost:{port}" if bind_host in _LOOPBACK_HOSTS
           else f"http://{bind_host}:{port}")

    # Start heartbeat watchdog thread
    watchdog = threading.Thread(target=_heartbeat_watchdog, daemon=True)
    watchdog.start()

    print(f"\n{'='*50}")
    print(f"  Anchor Dashboard running at {url}")
    print(f"  Server runs until you stop it (Stop button / Ctrl+C).")
    print(f"  Press Ctrl+C to stop manually.")
    print(f"  Error log: {ERROR_LOG}")
    print(f"{'='*50}\n")

    _logger.info(f"Server started on {url}")

    if not no_browser:
        # Open browser after a short delay
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        import job_runner
        job_runner.reconcile_on_startup()
    except Exception as e:
        _logger.error(f"job_runner.reconcile_on_startup failed: {e}")

    try:
        # rearch W15: re-adopt in-flight jobs through the supervisor seam — a
        # dashboard restart must leave a still-running job listed live with its
        # concurrency slots (lane serialization + folder-build lock) rebuilt
        # from the durable records. Inline today; the external supervisor
        # (W16) sits behind the same seam. Best-effort — never blocks boot.
        _summary = _sup.get_supervisor().rebuild()
        if _summary.get("running_jobs"):
            _logger.info("supervisor.rebuild re-adopted %d running job(s); "
                         "rebuilt %d lane slot(s), %d folder lock(s)"
                         % (len(_summary["running_jobs"]),
                            _summary.get("rebuilt_lane_slots", 0),
                            _summary.get("rebuilt_folder_locks", 0)))
    except Exception as e:
        _logger.error(f"supervisor.rebuild failed: {e}")

    try:
        # (2026-07 durability Wave 3) No perpetual "running" Gandalf row after a
        # restart: reconcile each registered project's dangling in-progress runs.
        _reconcile_gandalf_boot_runs()
    except Exception as e:
        _logger.error(f"gandalf boot reconcile failed: {e}")

    try:
        # (#3, single source) Reconcile managed-terminal-session registry
        # "running" records by PROCESS liveness on boot: a record whose recorded
        # PID no longer resolves to a live process is reconciled to a terminal
        # (idle) status, so a stale prior-instance "running" record can never feed
        # the startup orphan banner. Derive the alive-by-PID set from the SAME
        # immutable snapshot/provider the banner + daemon use (reaper.live_pid_ids
        # — process liveness, NOT ownership): a record with a live PID (genuine
        # work OR a true orphan the banner/daemon handles) is LEFT running; only
        # dead PIDs are reconciled.
        import session_registry as _sr_boot
        import reaper
        # Boot reconcile only needs PROCESS liveness (reaper.live_pid_ids reads
        # the snapshot's PID probe), so build it probe-only: no attached/owning-job
        # enumeration — this preserves the pre-Wave-1 boot behavior exactly (a
        # plain per-PID probe, no owner/job side effects at startup).
        _snap_boot = reaper.build_snapshot(
            attached_pty_ids=set(),
            records=_sr_boot.list_sessions(status="running"),
            job_active=lambda _sid: False,
            enumerate_pids=reaper.enumerate_live_pids)
        _alive_pids = reaper.live_pid_ids(_snap_boot)
        # Durability (2026-07-07): a RUNNING record whose process is gone is about
        # to be reconciled to IDLE. PERSIST its produced worktree docs into MAIN
        # FIRST so a hung/crashed session — notably a bare `general` session, which
        # boot-recovery skips (effort_managed=False) — never strands its work as
        # orphaned worktree files (the "found and manually saved later" case). The
        # worktree is IDLE-retained across the reap, so its files are still on disk
        # here. Best-effort; a persist failure never blocks the reconcile/boot.
        try:
            _dry = _sr_boot.reconcile(live_session_ids=_alive_pids, apply=False)
            _stale = _dry.get("stale") or []
            if _stale:
                import terminal_session as _ts_boot
                for _sid in _stale:
                    try:
                        _ts_boot.capture_session_docs(_sid)
                    except Exception:
                        pass
                _logger.info("boot: persisted docs for %d stale running "
                             "session(s) before reconcile→idle", len(_stale))
        except Exception as _e:
            _logger.error(f"boot persist-before-reconcile failed: {_e}")
        _sr_boot.reconcile(live_session_ids=_alive_pids)
        # zombie-hunter safe-to-arm Wave 5: conservatively migrate every legacy
        # STATUS_IDLE record forward to STATUS_PARKED_WARM (over-protect only) so
        # worktree-retention keys on the explicit split state. On the first boot
        # that actually migrates a record this arms the reaper dry-run, so the
        # first post-migration worktree sweep below is report-only.
        try:
            _mig = _sr_boot.migrate_idle_to_parked_warm()
            if _mig.get("migrated"):
                _logger.info(
                    "session_registry: migrated %d legacy idle record(s) to "
                    "parked-warm (reaper sweep armed report-only for this boot)",
                    len(_mig["migrated"]))
        except Exception as e:
            _logger.error(f"session_registry idle→parked-warm migration failed: {e}")
    except Exception as e:
        _logger.error(f"session_registry boot reconcile failed: {e}")

    try:
        # zombie-hunter safe-to-arm Wave 7: re-honor the persisted, PROTECT-ONLY
        # frozen-set across the NSSM restart. Re-probe each frozen entry's owning
        # PID (identity-tuple reuse guard) and re-establish the per-PID freeze
        # from scratch — a dead/recycled PID is dropped (never touched), and a
        # persisted 'would-kill' marker is INERT (kept pending; a kill is only
        # ever re-derived in-process from a fresh live probe). Relies on NO
        # cross-restart OS containment; never kills.
        import freeze_state
        _fz = freeze_state.reconcile_after_restart()
        if _fz.re_frozen or _fz.thawed or _fz.would_kill_pending:
            _logger.info(
                "freeze_state boot reconcile: re-froze %d, dropped %d "
                "(dead/recycled), %d would-kill marker(s) pending",
                len(_fz.re_frozen), len(_fz.thawed),
                len(_fz.would_kill_pending))
    except Exception as e:
        _logger.error(f"freeze_state boot reconcile failed: {e}")

    try:
        import preview_server
        preview_server.reap_orphans()
    except Exception as e:
        _logger.error(f"preview_server.reap_orphans failed: {e}")

    try:
        import worktrees
        import pty_manager
        _reap = worktrees.reap_orphans(set(pty_manager._LIVE.keys()))
        # W11 (C6): the first post-move boot sweeps report-only so a path-rewrite
        # miss can never delete a legit worktree. Live reaping re-arms only after
        # a clean dry report (worktrees.reap_orphans clears the marker itself).
        if _reap.get("dryrun"):
            _logger.info(
                "worktrees.reap_orphans DRY-RUN (post-move): would_reap=%s "
                "kept=%s — live reaping %s",
                _reap.get("would_reap"), _reap.get("kept"),
                "re-armed (clean report)" if not _reap.get("would_reap")
                and not _reap.get("errors") else "held (report not clean)")
    except Exception as e:
        _logger.error(f"worktrees.reap_orphans failed: {e}")

    try:
        # telemetry-resume W6 — bounded oldest-first parked-worktree eviction.
        # After orphan-reaping, if the RETAINED-parked worktree count exceeds the
        # budget, gracefully evict the OLDEST: only the git worktree is reclaimed —
        # the registry record, chain lineage, cached summary, and finalized cost
        # all SURVIVE (the tile renders evicted-parked and stays MEASURED; its
        # escalation opens a NEW seeded session on the SAME chain). Never in the
        # post-move dry-run window (reaping was report-only there).
        import worktrees as _wt_evict
        import pty_manager as _pty_evict
        if not _wt_evict.reaper_dryrun_active():
            _ev = _wt_evict.evict_oldest_parked(set(_pty_evict._LIVE.keys()))
            if _ev.get("evicted"):
                _logger.info(
                    "worktrees.evict_oldest_parked: evicted %d parked worktree(s) "
                    "(budget %d, parked %d) — records/chains/summaries/cost kept",
                    len(_ev["evicted"]), _ev.get("budget"),
                    _ev.get("parked_count"))
    except Exception as e:
        _logger.error(f"worktrees.evict_oldest_parked failed: {e}")

    try:
        # Purge leaked synthetic health-check probe projects. The daily
        # healthcheck task creates "__healthcheck__ rnd probe vN" projects and
        # tears them down in a finally, but a hard-kill (e.g. its 10-min Task
        # Scheduler limit) skips teardown, leaving them as bogus R&D dashboard
        # project tiles. Remove any such record at boot so they never accumulate.
        _purged = 0
        for _p in _rnd.list_projects():
            if str(_p.get("name", "")).startswith("__healthcheck__"):
                if _rnd.remove_project(_p.get("id", "")):
                    _purged += 1
        if _purged:
            _logger.info(f"purged {_purged} leaked __healthcheck__ probe project(s)")
    except Exception as e:
        _logger.error(f"healthcheck-probe purge failed: {e}")

    try:
        if "PYTEST_CURRENT_TEST" not in os.environ and not _zombie_hunter_started:
            _zombie_hunter_started = True
            import zombie_hunter
            import reaper
            import pty_manager
            import session_registry as _sr_daemon
            # Wave 8 — the daemon is governed by the ARMING LADDER, UNARMED by
            # default. Each cycle does ONE running-record read and builds the ONE
            # immutable snapshot (the single shared provider — same source the
            # banner/view/brief/boot-reconcile sites use), derives the live-owner
            # set from THAT snapshot (abstain-safe), caches it for _live_provider,
            # then routes the SAME snapshot + records through
            # reaper_arming.armed_sweep, whose effective tier (log → freeze → kill)
            # honors the persisted arm state AND the restart-durable
            # .anchor/reaper.disarmed kill-switch brake. Every destructive action
            # is re-derived in-process from the fresh snapshot (protect-only) — a
            # persisted 'kill' tier never kills a session whose owner is alive. A
            # second build_snapshot here would violate the single-source contract.
            import reaper_arming
            _daemon_owners = {"set": set()}
            def _live_provider():
                # The daemon's live-owner set, derived from the most-recent sweep
                # snapshot (abstain-safe PTY-attached fallback before the first
                # sweep). Never builds a second snapshot.
                return _daemon_owners["set"] or set(pty_manager._LIVE.keys())
            def _armed_sweep_cycle():
                try:
                    running = _sr_daemon.list_sessions(status="running")
                except Exception:
                    running = []
                attached = set(pty_manager._LIVE.keys())
                try:
                    snap = reaper.build_snapshot(attached_pty_ids=attached,
                                                 records=running,
                                                 enumerate_pids=reaper.enumerate_live_pids)
                except Exception:
                    snap = None
                # Derive the live-owner set DIRECTLY from the one snapshot via the
                # shared provider. Defensive boundary (Wave 2, criterion 1): a
                # degraded/None snapshot → owner_ids_or_abstain returns EVERY
                # running id as "owned", so a single fetch hiccup can never feed
                # the armed daemon a narrowed live set → mass-kill.
                try:
                    if snap is not None and not getattr(snap, "degraded", False):
                        _daemon_owners["set"] = reaper.live_owner_ids(snap) or attached
                    else:
                        _daemon_owners["set"] = (
                            reaper.owner_ids_or_abstain(snap, running) or attached)
                except Exception:
                    _daemon_owners["set"] = attached
                reaper_arming.armed_sweep(running, snap)
            zombie_hunter.start_hunter(_live_provider, sweep_fn=_armed_sweep_cycle)
            
            try:
                # Fire-and-forget warm start; handle_zombie_hunter_report will
                # _ensure_zh_node_server if the user opens the radar before listen.
                import subprocess as _sp_zh
                if not _zh_node_is_up(timeout=0.5):
                    creationflags = 0x08000000 if sys.platform.startswith("win") else 0
                    if os.path.exists(_ZH_NODE_SERVER_PATH):
                        _sp_zh.Popen(
                            ["node", _ZH_NODE_SERVER_PATH],
                            creationflags=creationflags,
                            cwd=os.path.dirname(_ZH_NODE_SERVER_PATH),
                        )
                        _logger.info("Launched ZH Node Server on port %s", _ZH_NODE_PORT)
            except Exception as e:
                _logger.error(f"Failed to launch ZH Node Server: {e}")
                
    except Exception as e:
        _logger.error(f"zombie_hunter.start_hunter failed: {e}")

    try:
        # Durability (2026-07-07): the incremental-autosave heartbeat — every
        # ~120s it snapshots each RUNNING session's transcript + copies its
        # produced docs into MAIN + refreshes RESTART.md, so a hung/long session
        # never loses more than one interval of work and is warm-restartable. One
        # main-process-owned daemon; spawns no subprocess (no console popups).
        import terminal_session as _ts_auto
        if _ts_auto.start_autosave_daemon():
            _logger.info("session autosave heartbeat started (interval %ss)",
                         int(_ts_auto._autosave_interval()))
    except Exception as e:
        _logger.error(f"session autosave daemon start failed: {e}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        _logger.info("Server stopped")
        print("\nAnchor stopped.")
        server.server_close()


if __name__ == "__main__":
    main()
