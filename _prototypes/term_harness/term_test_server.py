"""Anchor terminal harness — a REAL ConPTY <-> WebSocket <-> xterm.js bridge.

Standalone, stdlib + pywinpty only. Does NOT touch the live :8777 service.
Spawns real interactive processes (PowerShell / Claude Code / Gemini) in a Windows
ConPTY and streams them to xterm.js terminals in the browser. Multiple terminals can
be open at once as draggable windows — so this is both the terminal proof-of-test AND
a working preview of the "multiple sessions open in the dashboard" UX.

Run:   python -u _prototypes/term_harness/term_test_server.py
Then:  open http://localhost:8799   (port is HARD-pinned away from 8777)

Each browser terminal:  GET /ws?target=<shell|claude|gemini>&cwd=<path>  (WebSocket upgrade)
  - server spawns one ConPTY child, pumps its output to the socket as text frames
  - client keystrokes arrive as text frames -> proc.write
  - a JSON control frame {"t":"resize","cols":N,"rows":M} resizes the PTY
"""
import sys, os, base64, hashlib, struct, threading, json, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
from pathlib import Path

HARNESS_DIR = Path(__file__).resolve().parent
VENDOR = HARNESS_DIR.parent.parent / "vendor"          # C:\dev\Anchor\vendor
PORT = 8799                                            # never 8777
WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

try:
    import winpty
except Exception as e:
    print("FATAL: pywinpty not importable:", e)
    print("Install with: pip install pywinpty")
    sys.exit(2)

TARGETS = {
    # label -> argv (the actual process launched in the ConPTY)
    "shell":  ["powershell.exe", "-NoLogo"],
    "claude": ["claude.exe"],
    "gemini": ["gemini.ps1"],   # gemini is a .ps1 shim; launched via powershell below
}

def build_argv(target):
    if target == "gemini":
        # gemini is a PowerShell shim on PATH; run it through powershell -Command.
        return ["powershell.exe", "-NoLogo", "-NoExit", "-Command", "gemini"]
    return TARGETS.get(target, TARGETS["shell"])

# ───────────────────────── WebSocket framing (RFC 6455, minimal) ─────────────
def ws_accept(key):
    return base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()

def ws_send(sock, payload, opcode=0x1):
    """Send one unmasked server frame. payload: str (text) or bytes."""
    data = payload.encode("utf-8", "replace") if isinstance(payload, str) else payload
    n = len(data)
    hdr = bytearray([0x80 | opcode])
    if n < 126:
        hdr.append(n)
    elif n < 65536:
        hdr.append(126); hdr += struct.pack(">H", n)
    else:
        hdr.append(127); hdr += struct.pack(">Q", n)
    sock.sendall(bytes(hdr) + data)

def ws_recv(sock):
    """Read one client frame -> (opcode, bytes) or (None, None) on close/error."""
    def recvn(n):
        b = b""
        while len(b) < n:
            chunk = sock.recv(n - len(b))
            if not chunk:
                return None
            b += chunk
        return b
    h = recvn(2)
    if not h:
        return None, None
    b0, b1 = h[0], h[1]
    opcode = b0 & 0x0F
    masked = b1 & 0x80
    ln = b1 & 0x7F
    if ln == 126:
        ext = recvn(2);  ln = struct.unpack(">H", ext)[0] if ext else 0
    elif ln == 127:
        ext = recvn(8);  ln = struct.unpack(">Q", ext)[0] if ext else 0
    mask = recvn(4) if masked else b"\x00\x00\x00\x00"
    data = recvn(ln) if ln else b""
    if data is None:
        return None, None
    if masked:
        data = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
    return opcode, data

# ───────────────────────── one PTY-backed session ───────────────────────────
def serve_session(sock, target, cwd):
    argv = build_argv(target)
    try:
        proc = winpty.PtyProcess.spawn(argv, cwd=cwd or None, dimensions=(30, 100))
    except Exception as ex:
        try: ws_send(sock, f"\r\n[harness] spawn failed: {ex}\r\n")
        except Exception: pass
        return
    alive = {"v": True}

    def pump_out():
        try:
            while alive["v"]:
                try:
                    data = proc.read(2048)
                except EOFError:
                    break
                if data:
                    ws_send(sock, data)
                else:
                    time.sleep(0.02)
        except Exception:
            pass
        finally:
            try: ws_send(sock, "\r\n[harness] process exited.\r\n")
            except Exception: pass
            try: ws_send(sock, b"", opcode=0x8)   # close
            except Exception: pass

    t = threading.Thread(target=pump_out, daemon=True); t.start()
    ws_send(sock, f"\x1b[90m[harness] launched: {' '.join(argv)}  (cwd={cwd or os.getcwd()})\x1b[0m\r\n")

    try:
        while True:
            opcode, data = ws_recv(sock)
            if opcode is None or opcode == 0x8:    # closed
                break
            if opcode == 0x9:                       # ping -> pong
                ws_send(sock, data, opcode=0xA); continue
            if not data:
                continue
            text = data.decode("utf-8", "replace")
            if text.startswith("{") and '"t"' in text:
                try:
                    msg = json.loads(text)
                    if msg.get("t") == "resize":
                        proc.setwinsize(int(msg["rows"]), int(msg["cols"])); continue
                    if msg.get("t") == "input":
                        proc.write(msg.get("data", "")); continue
                except Exception:
                    pass
            proc.write(text)
    finally:
        alive["v"] = False
        try: proc.terminate(force=True)
        except Exception: pass

# ───────────────────────── HTTP + upgrade handler ───────────────────────────
class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    def log_message(self, *a): pass

    def _file(self, path, ctype):
        try:
            data = Path(path).read_bytes()
        except Exception:
            self.send_response(404); self.end_headers(); return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            data = INDEX_HTML.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers(); self.wfile.write(data); return
        if u.path == "/vendor/xterm/xterm.js":   return self._file(VENDOR/"xterm"/"xterm.js", "application/javascript")
        if u.path == "/vendor/xterm/xterm.css":  return self._file(VENDOR/"xterm"/"xterm.css", "text/css")
        if u.path == "/vendor/brand/gwl.svg":    return self._file(VENDOR/"brand"/"gwl-m-icon.svg", "image/svg+xml")
        if u.path == "/ws":
            return self._upgrade(parse_qs(u.query))
        self.send_response(404); self.end_headers()

    def _upgrade(self, qs):
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self.send_response(400); self.end_headers(); return
        self.send_response(101)
        self.send_header("Upgrade", "websocket")
        self.send_header("Connection", "Upgrade")
        self.send_header("Sec-WebSocket-Accept", ws_accept(key))
        self.end_headers()
        target = (qs.get("target", ["shell"])[0]).strip()
        cwd = (qs.get("cwd", [""])[0]).strip()
        try:
            serve_session(self.connection, target, cwd)
        except Exception:
            pass
        try: self.connection.close()
        except Exception: pass

INDEX_HTML = r"""<!DOCTYPE html><html><head><meta charset="utf-8">
<title>Anchor Terminal Harness — ConPTY x xterm.js</title>
<link rel="stylesheet" href="/vendor/xterm/xterm.css">
<style>
:root{--bg:#0f1117;--surface:#1a1d27;--surface2:#232733;--border:#2e3340;--text:#e2e4e9;--dim:#8b8f9a;--accent:#6c9cfc;--green:#22c55e;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--text);font-family:-apple-system,'Segoe UI',system-ui,sans-serif;height:100vh;overflow:hidden;}
.bar{display:flex;align-items:center;gap:10px;padding:10px 16px;border-bottom:1px solid var(--border);background:rgba(15,23,42,.7);}
.bar img{width:22px;height:22px;border-radius:5px;box-shadow:0 0 8px rgba(34,197,94,.4);}
.bar h1{font-size:14px;font-weight:700;}
.bar h1 .g{color:var(--green);}
.bar .sp{flex:1;}
.bar button{font-size:12px;padding:6px 12px;border-radius:7px;border:1px solid var(--border);background:var(--surface2);color:var(--text);cursor:pointer;}
.bar button:hover{border-color:var(--accent);}
.bar button.claude{border-color:rgba(34,197,94,.5);}
.bar .hint{font-size:11px;color:var(--dim);}
#desk{position:relative;width:100vw;height:calc(100vh - 49px);}
.win{position:absolute;width:680px;height:420px;background:#000;border:1px solid var(--border);border-radius:9px;overflow:hidden;display:flex;flex-direction:column;box-shadow:0 12px 40px rgba(0,0,0,.55);}
.win .t{display:flex;align-items:center;gap:8px;padding:6px 10px;background:var(--surface2);border-bottom:1px solid var(--border);cursor:move;user-select:none;}
.win .t .dot{width:8px;height:8px;border-radius:50%;background:var(--green);box-shadow:0 0 0 0 rgba(34,197,94,.6);animation:pulse 1.6s infinite;}
.win .t.dead .dot{background:#f87171;animation:none;}
.win .t .lab{font-size:12px;font-weight:600;}
.win .t .meta{font-size:11px;color:var(--dim);}
.win .t .sp{flex:1;}
.win .t button{font-size:13px;width:24px;height:22px;border:1px solid var(--border);background:var(--surface);color:var(--dim);border-radius:5px;cursor:pointer;}
.win .t button:hover{color:var(--text);}
.win .term{flex:1;padding:4px 6px;overflow:hidden;}
.win .grip{position:absolute;right:0;bottom:0;width:16px;height:16px;cursor:nwse-resize;}
/* embedded-mode summary header (Anchor tile chrome) */
.win .embhead{display:none;padding:8px 11px;background:#11141c;border-bottom:1px solid var(--border);font-size:11.5px;color:var(--dim);}
.win.embedded .embhead{display:block;}
.win .embhead b{color:var(--text);}
.win .embhead .docs{margin-top:5px;display:flex;gap:6px;}
.win .embhead .docs a{font-size:10.5px;padding:2px 7px;border:1px solid var(--border);border-radius:6px;color:var(--text);text-decoration:none;}
/* console mode (ANSI-stripped clean transcript) */
.win .console{display:none;flex:1;flex-direction:column;background:#0a0d14;min-height:0;}
.win.console-mode .term{display:none;}
.win.console-mode .console{display:flex;}
.win .console .log{flex:1;overflow:auto;padding:11px 13px;font-family:ui-monospace,Consolas,monospace;font-size:12.5px;line-height:1.55;color:#cdd2dc;white-space:pre-wrap;}
.win .console .row{display:flex;gap:7px;padding:8px;border-top:1px solid var(--border);background:#060810;}
.win .console .row input{flex:1;background:#05070c;border:1px solid var(--border);border-radius:6px;padding:7px 9px;color:var(--text);font-size:12.5px;font-family:ui-monospace,Consolas,monospace;}
.win .console .row button{font-size:12px;padding:0 13px;border-radius:6px;border:1px solid var(--green);background:var(--green);color:#05140a;font-weight:600;cursor:pointer;}
@keyframes pulse{0%{box-shadow:0 0 0 0 rgba(34,197,94,.5);}70%{box-shadow:0 0 0 6px rgba(34,197,94,0);}100%{box-shadow:0 0 0 0 rgba(34,197,94,0);}}
</style></head>
<body>
<div class="bar">
  <img src="/vendor/brand/gwl.svg" alt="">
  <h1>Anchor Terminal Harness <span class="g">· ConPTY × xterm.js</span></h1>
  <span class="hint">launch a real interactive session — drag windows, open several at once</span>
  <span class="sp"></span>
  <span class="hint" style="margin-right:4px;">Claude Code, 3 looks:</span>
  <button class="claude" onclick="newWin('claude','raw')">Raw</button>
  <button class="claude" onclick="newWin('claude','embedded')">Embedded</button>
  <button class="claude" onclick="newWin('claude','console')">Console</button>
  <span style="width:1px;height:20px;background:var(--border);margin:0 4px;"></span>
  <button onclick="newWin('shell','raw')">+ PowerShell</button>
  <button onclick="newWin('gemini','embedded')">+ Gemini</button>
</div>
<div id="desk"></div>
<script src="/vendor/xterm/xterm.js"></script>
<script>
var Z = 10, N = 0;
// strip ANSI/VT escape sequences for the clean "console" rendering
function stripAnsi(s){
  return s.replace(/\x1b\][^\x07\x1b]*(\x07|\x1b\\)/g,'')   // OSC
          .replace(/\x1b[\[\]][0-9;?]*[A-Za-z@]/g,'')       // CSI
          .replace(/\x1b[=>NODEHM78]/g,'')                  // misc
          .replace(/[\x00-\x08\x0b\x0c\x0e-\x1f]/g,'');     // ctrl (keep \t \n \r)
}
function newWin(target, mode){
  mode = mode || 'raw';
  N++; var id = 'w'+N;
  var labels = {shell:'PowerShell', claude:'Claude Code', gemini:'Gemini CLI'};
  var modeLabel = {raw:'raw terminal', embedded:'embedded', console:'console'};
  var win = document.createElement('div');
  win.className = 'win ' + (mode==='console' ? 'console-mode' : mode==='embedded' ? 'embedded' : '');
  win.id = id;
  win.style.left = (24 + (N%4)*40) + 'px';
  win.style.top  = (24 + (N%5)*34) + 'px';
  win.style.zIndex = ++Z;
  win.innerHTML =
    "<div class='t'><span class='dot'></span><span class='lab'>"+labels[target]+" "+N+"</span>"+
    "<span class='meta'>· "+modeLabel[mode]+"</span><span class='sp'></span>"+
    "<button title='Minimize'>–</button><button title='Close (kills session)'>×</button></div>"+
    "<div class='embhead'><b>Planning · "+labels[target]+"</b> · isolated worktree · status "+
      "<span style='color:#22c55e'>● running</span>"+
      "<div class='docs'><a href='#'>🗺️ MASTER-PLAN.md</a><a href='#'>📋 IMPLEMENTATION-PLAN.md</a></div></div>"+
    "<div class='term'></div>"+
    "<div class='console'><div class='log'></div><div class='row'><input placeholder='type a message + Enter…'><button>Send</button></div></div>"+
    "<div class='grip'></div>";
  document.getElementById('desk').appendChild(win);
  win.onmousedown = function(){ win.style.zIndex = ++Z; };

  var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  var ws = new WebSocket(proto+'//'+location.host+'/ws?target='+target);
  var meta = win.querySelector('.meta');

  var term = null, logEl = null;
  if (mode === 'console') {
    logEl = win.querySelector('.console .log');
    var inp = win.querySelector('.console .row input');
    var btn = win.querySelector('.console .row button');
    function send(){ var v=inp.value; if(ws.readyState===1){ ws.send(v+'\r'); } inp.value=''; }
    btn.onclick = send;
    inp.addEventListener('keydown', function(e){ if(e.key==='Enter'){ e.preventDefault(); send(); }});
  } else {
    term = new Terminal({fontSize:13, fontFamily:'Consolas, ui-monospace, monospace',
                         cursorBlink:true, theme:{background:'#000000'}, scrollback:4000});
    term.open(win.querySelector('.term'));
    fit(term, win);
    term.onData(function(d){ if(ws.readyState===1) ws.send(d); });
  }

  ws.onopen = function(){ sendResize(); };
  ws.onmessage = function(ev){
    if (term) { term.write(ev.data); }
    else { logEl.textContent += stripAnsi(ev.data); logEl.scrollTop = logEl.scrollHeight; }
  };
  ws.onclose = function(){ win.querySelector('.t').classList.add('dead'); meta.textContent='· exited'; };

  function sendResize(){ if(term && ws.readyState===1){ try{ ws.send(JSON.stringify({t:'resize',cols:term.cols,rows:term.rows})); }catch(e){} } }
  function fit(t, w){
    if(!t) return;
    var host = w.querySelector('.term');
    var cw = 8.0, ch = 17;  // approx Consolas 13px cell
    var cols = Math.max(20, Math.floor((host.clientWidth-10)/cw));
    var rows = Math.max(6, Math.floor((host.clientHeight-6)/ch));
    try{ t.resize(cols, rows); }catch(e){}
  }
  // titlebar buttons
  var btns = win.querySelectorAll('.t button');
  btns[0].onclick = function(){ var tm=win.querySelector('.term'); tm.style.display = tm.style.display==='none'?'':'none'; };
  btns[1].onclick = function(){ if(confirm('Kill this session?')){ try{ws.close();}catch(e){} win.remove(); } };
  // drag
  var tt = win.querySelector('.t'), dragging=false, ox=0, oy=0;
  tt.onmousedown = function(e){ if(e.target.tagName==='BUTTON')return; dragging=true; ox=e.clientX-win.offsetLeft; oy=e.clientY-win.offsetTop; e.preventDefault(); };
  document.addEventListener('mousemove', function(e){ if(dragging){ win.style.left=(e.clientX-ox)+'px'; win.style.top=(e.clientY-oy)+'px'; }});
  document.addEventListener('mouseup', function(){ dragging=false; });
  // resize
  var grip = win.querySelector('.grip'), rz=false;
  grip.onmousedown = function(e){ rz=true; e.preventDefault(); e.stopPropagation(); };
  document.addEventListener('mousemove', function(e){ if(rz){ win.style.width=Math.max(320,e.clientX-win.offsetLeft)+'px'; win.style.height=Math.max(180,e.clientY-win.offsetTop)+'px'; fit(term,win); sendResize(); }});
  document.addEventListener('mouseup', function(){ rz=false; });
}
// open one Claude Code window on load so the test is one click from a model turn
window.addEventListener('load', function(){ newWin('claude','embedded'); });
</script>
</body></html>"""

if __name__ == "__main__":
    print(f"Anchor terminal harness on http://localhost:{PORT}  (PID {os.getpid()})", flush=True)
    print(f"  vendor xterm: {VENDOR/'xterm'/'xterm.js'}  exists={(VENDOR/'xterm'/'xterm.js').exists()}", flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
