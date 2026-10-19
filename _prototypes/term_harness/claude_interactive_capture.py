"""Drive a REAL interactive `claude` session through a ConPTY and capture how it behaves.

This is the honest answer to 'how will the terminal actually behave?' — it IS Claude Code
running in a real Windows ConPTY (same substrate the web terminal rides). We send one prompt,
capture the bytes, and write both the raw and an ANSI-stripped readable transcript to disk.
"""
import sys, time, threading, queue, re, io
import winpty

ANSI = re.compile(r'\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[\[\]][0-9;?]*[A-Za-z@]|\x1b[=>NODEHM78]|[\x00-\x08\x0b\x0c\x0e-\x1f]')
def strip(s): return ANSI.sub('', s)

def main():
    proc = winpty.PtyProcess.spawn(["claude.exe"], dimensions=(45, 120))
    q = queue.Queue()
    def pump():
        try:
            while True:
                d = proc.read(2048)
                if not d: q.put(None); return
                q.put(d)
        except EOFError: q.put(None)
        except Exception as e: q.put(f"[err {e}]"); q.put(None)
    threading.Thread(target=pump, daemon=True).start()

    raw = []
    def drain(sec):
        end = time.time() + sec
        while time.time() < end:
            try: item = q.get(timeout=0.15)
            except queue.Empty: continue
            if item is None: return
            raw.append(item)

    drain(8)                                   # let the TUI boot
    proc.write("Reply with exactly one word: PTYHELLO\r")
    drain(20)                                  # wait for the model turn
    try: proc.write("\x03"); proc.write("\x03")   # ctrl-c to leave
    except Exception: pass
    drain(2)
    try: proc.terminate(force=True)
    except Exception: pass

    full = "".join(raw)
    clean = strip(full)
    with io.open("_prototypes/term_harness/claude_capture_raw.txt", "w", encoding="utf-8") as f:
        f.write(full)
    with io.open("_prototypes/term_harness/claude_capture_clean.txt", "w", encoding="utf-8") as f:
        f.write(clean)
    # collapse blank lines for the console print
    lines = [ln.rstrip() for ln in clean.splitlines()]
    compact = "\n".join([ln for i, ln in enumerate(lines) if ln or (i and lines[i-1])])
    out = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    out.write(f"RAW bytes: {len(full)}   CLEAN chars: {len(clean)}\n")
    out.write("===== READABLE TRANSCRIPT (ANSI stripped) =====\n")
    out.write(compact[-2500:] + "\n")
    out.write("===== contains 'PTYHELLO': " + str("PTYHELLO" in clean and clean.count("PTYHELLO") > 1) + " =====\n")
    out.flush()

if __name__ == "__main__":
    main()
