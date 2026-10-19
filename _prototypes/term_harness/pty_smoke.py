"""Headless ConPTY smoke test — proves the PTY substrate the web terminal rides on.

Run: python -u _prototypes/term_harness/pty_smoke.py
pywinpty.read() BLOCKS, so we pump it from a daemon reader thread into a queue and
drain the queue on a wall-clock budget. Tests three launch targets to see empirically
how each behaves under ConPTY.
"""
import sys, time, threading, queue

try:
    import winpty
except Exception as e:
    print("PYWINPTY MISSING:", e); sys.exit(2)

def spawn(argv):
    proc = winpty.PtyProcess.spawn(argv, dimensions=(30, 100))
    q = queue.Queue()
    def pump():
        try:
            while True:
                data = proc.read(2048)
                if data == "" or data is None:
                    q.put(None); return
                q.put(data)
        except EOFError:
            q.put(None)
        except Exception as ex:
            q.put(f"\n[reader err: {ex}]"); q.put(None)
    t = threading.Thread(target=pump, daemon=True); t.start()
    return proc, q

def drain(q, seconds, label):
    buf, end = [], time.time() + seconds
    while time.time() < end:
        try:
            item = q.get(timeout=0.1)
        except queue.Empty:
            continue
        if item is None:
            buf.append("\n[eof]"); break
        buf.append(item)
    text = "".join(buf)
    show = text if len(text) < 1800 else text[:900] + "\n…<snip>…\n" + text[-900:]
    print(f"\n===== {label}: {len(text)} chars =====\n{show}", flush=True)
    return text

def run(argv, writes, warmup, after, label):
    print("\n" + "#"*70 + f"\n# TARGET: {' '.join(argv)}   ({label})\n" + "#"*70, flush=True)
    try:
        proc, q = spawn(argv)
    except Exception as ex:
        print("SPAWN FAILED:", ex, flush=True); return
    drain(q, warmup, f"{label} startup")
    for w in writes:
        print(f"\n>>> write {w!r}", flush=True)
        try: proc.write(w)
        except Exception as ex: print("write err:", ex, flush=True)
        drain(q, after, f"{label} after-write")
    try: proc.terminate(force=True)
    except Exception: pass
    print(f"[{label}] alive after terminate: {proc.isalive()}", flush=True)

if __name__ == "__main__":
    # 1) Plain shell — cleanest control: prompt + echoed command output.
    run(["powershell.exe", "-NoLogo"], ["echo hello-from-pty\r\n", "Get-Location\r\n"], 2.5, 2.0, "powershell")
    # 2) claude --version (non-interactive) — proves the binary runs in a ConPTY at all.
    run(["claude.exe", "--version"], [], 6.0, 0.0, "claude --version")
    # 3) claude -p "..." print mode (non-interactive, exits) — proves a real model turn works.
    run(["claude.exe", "-p", "Reply with exactly: PTY_OK"], [], 30.0, 0.0, "claude -p print")
    # 4) bare interactive `claude` (what term_start launches today) — capped, watch the banner.
    run(["claude.exe"], ["hello\r"], 6.0, 6.0, "claude interactive")
    print("\nDONE.", flush=True)
