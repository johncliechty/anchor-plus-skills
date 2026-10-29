"""Foundry tools - small, fast, standard commands for chores agents keep doing by hand (John, 2026-10-12).

  python C:/dev/foundry-tools/ft.py list                      the tools, one line each
  python C:/dev/foundry-tools/ft.py <tool> [args...]          run one (timed and logged)
  python C:/dev/foundry-tools/ft.py usage [--days N]          runs, failures and time per tool
  python C:/dev/foundry-tools/ft.py propose <name> --why "<evidence>"   suggest a new tool (PROPOSALS.md)

Every run appends one line to .usage/<YYYY-MM>.jsonl: tool, seconds, exit code, caller (the Anchor job, session or
skill from the environment), folder. Logging never fails a tool."""
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
INDEX = HERE / "INDEX.json"
USAGE = Path(os.environ.get("FOUNDRY_TOOLS_USAGE_DIR") or HERE / ".usage")   # tests point it elsewhere
PROPOSALS = HERE / "PROPOSALS.md"
CALLER_ENV = ("ANCHOR_JOB_ID", "ANCHOR_SESSION_ID", "ANCHOR_EFFORT_DIR", "FOUNDRY_SKILL")


def index():
    return json.loads(INDEX.read_text(encoding="utf-8"))["tools"]


def caller():
    return {k: os.environ[k] for k in CALLER_ENV if os.environ.get(k)}


def log(entry):
    """Append one line under a short lock (several agents run tools at once); never raises."""
    try:
        USAGE.mkdir(exist_ok=True)
        line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
        with open(USAGE / ".lock", "a+b") as lock:
            if not _lock(lock):
                return                       # no lock, no line: the log is optional, a garbled one is not
            try:
                with open(USAGE / (time.strftime("%Y-%m") + ".jsonl"), "ab") as f:
                    f.write(line)
            finally:
                _unlock(lock)
    except Exception:
        pass


def _lock(f, wait_s=3.0):
    deadline = time.time() + wait_s
    while True:
        try:
            if os.name == "nt":
                import msvcrt
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if time.time() >= deadline:
                return False
            time.sleep(0.02)


def _unlock(f):
    try:
        if os.name == "nt":
            import msvcrt
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    except OSError:
        pass


def cmd_list():
    for t in index():
        print("%-14s %s  (~%s s)" % (t["name"], t["purpose"], t["seconds"]))
        print("%-14s %s" % ("", t["command"]))


def cmd_usage(argv):
    days = int(argv[argv.index("--days") + 1]) if "--days" in argv else 30
    since = time.time() - days * 86400
    rows = {}
    for f in sorted(USAGE.glob("*.jsonl")) if USAGE.is_dir() else []:
        for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("at_epoch", 0) < since:
                continue
            r = rows.setdefault(e.get("tool", "?"), [0, 0, 0.0])
            r[0] += 1
            r[1] += e.get("exit") not in (0, None)
            r[2] += e.get("seconds") or 0
    print("last %d days" % days)
    for name, (n, bad, s) in sorted(rows.items(), key=lambda x: -x[1][0]):
        print("%-14s %4d runs  %3d failed  %7.1f s total  %5.1f s each" % (name, n, bad, s, s / n))
    if not rows:
        print("(no runs logged)")


def cmd_propose(argv):
    if not argv or "--why" not in argv:
        print('usage: ft.py propose <name> --why "<evidence: what was done by hand, how long, where>"')
        return 2
    name, why = argv[0], argv[argv.index("--why") + 1]
    who = ", ".join("%s=%s" % kv for kv in caller().items()) or "unknown caller"
    with open(PROPOSALS, "a", encoding="utf-8") as f:
        f.write("\n## %s - proposed %s\n- Why: %s\n- From: %s\n- Status: waiting for John\n"
                % (name, datetime.now().strftime("%Y-%m-%d %H:%M"), why, who))
    log({"tool": "propose", "name": name, "at": datetime.now().isoformat(timespec="seconds"),
         "at_epoch": time.time(), "seconds": 0, "exit": 0, **caller()})
    print("proposed: %s (in %s)" % (name, PROPOSALS))
    return 0


def main(argv):
    if not argv or argv[0] in ("-h", "--help", "help"):
        print(__doc__)
        return 0
    if argv[0] == "list":
        cmd_list()
        return 0
    if argv[0] == "usage":
        cmd_usage(argv[1:])
        return 0
    if argv[0] == "propose":
        return cmd_propose(argv[1:])
    tools = {t["name"]: t for t in index()}
    if argv[0] not in tools:
        print("no Foundry tool named %r; the tools are: %s" % (argv[0], ", ".join(sorted(tools))))
        return 2
    script = HERE / argv[0] / "tool.py"
    t0 = time.time()
    try:
        code = subprocess.call([sys.executable, str(script)] + argv[1:], creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
    except KeyboardInterrupt:
        code = 130
    log({"tool": argv[0], "at": datetime.fromtimestamp(t0).isoformat(timespec="seconds"), "at_epoch": t0,
         "seconds": round(time.time() - t0, 2), "exit": code, "cwd": os.getcwd(), **caller()})
    return code


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
