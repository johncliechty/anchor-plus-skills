"""Steward responsiveness R0 (Ecgberht/planning/steward-responsiveness-2026-10-04): how long John waits and where a
steward's turns go, on his own record. Read-only.

For each steward folder given (default: the Cave of Wonders, the Campaign, and every folder with a Codex thread in
the window):
  - the WAIT he saw: each of his messages in .ecgberht/conversation-log.json to the next steward line;
  - from the Codex threads whose cwd is that folder: working turns, median and longest turn, tool calls per turn,
    seconds per step, and the share of steps that wrote the steward's own bookkeeping (.ecgberht/, plan pages,
    verify/record/report scripts, DELIVERABLES) rather than product files.

  python tools/turn_profile.py [--days 3] [folder ...]
"""
import argparse, glob, json, os, re, statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path

BOOK = re.compile(r"(\.ecgberht[\\/]|attention\.json|DELIVERABLES\.md|PLAN[-\w]*\.(html|md)|REPORT[-\w]*\.(html|md)|"
                  r"verify[-\w]*\.(py|mjs)|record[-\w]*\.(py|mjs)|make-[-\w]*report|STATUS\.html|JOURNAL\.md|journal[\\/])", re.I)


def T(x):
    return datetime.fromisoformat(str(x).replace("Z", "+00:00"))


def waits(folder, since):
    try:
        turns = json.loads((Path(folder) / ".ecgberht" / "conversation-log.json").read_text(encoding="utf-8"))["turns"]
    except Exception:
        return []
    out = []
    for k, t in enumerate(turns):
        if t.get("role") != "john" or T(t["at"]) < since:
            continue
        nxt = next((u for u in turns[k + 1:] if u.get("role") == "steward"), None)
        out.append((T(nxt["at"]) - T(t["at"])).total_seconds() / 60 if nxt else None)
    return out


def threads(since):
    by = {}
    for f in glob.glob(os.path.expanduser("~/.codex/sessions/*/*/*/*.jsonl")):
        if datetime.fromtimestamp(os.path.getmtime(f), timezone.utc) < since:
            continue
        cwd, turns, cur = None, [], None
        try:
            for ln in open(f, encoding="utf-8"):
                try:
                    e = json.loads(ln)
                except Exception:
                    continue
                t, p = e.get("type"), e.get("payload") or {}
                pt = p.get("type") if isinstance(p, dict) else None
                if t == "session_meta":
                    cwd = p.get("cwd")
                elif t == "turn_context":
                    cur = {"start": e["timestamp"], "last": e["timestamp"], "calls": 0, "book": 0}
                    turns.append(cur)
                elif cur is not None:
                    if pt not in ("token_count",):
                        cur["last"] = e["timestamp"]
                    if pt in ("function_call", "custom_tool_call", "local_shell_call"):
                        cur["calls"] += 1
                        if BOOK.search(str(p.get("input") or p.get("arguments") or "")[:4000]):
                            cur["book"] += 1
        except Exception:
            continue
        if cwd:
            by.setdefault(str(Path(cwd).resolve()).lower(), []).extend(
                c for c in turns if c["calls"] and T(c["start"]) >= since)
    return by


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=float, default=3)
    ap.add_argument("folders", nargs="*")
    a = ap.parse_args()
    since = datetime.now(timezone.utc) - timedelta(days=a.days)
    th = threads(since)
    folders = a.folders or [r"C:\dev\Campaign\Cave of Wonders", r"C:\dev\Campaign"] + sorted(th)
    seen = set()
    for f in folders:
        key = str(Path(f).resolve()).lower()
        if key in seen:
            continue
        seen.add(key)
        w = [x for x in waits(f, since) if x is not None]
        unanswered = sum(1 for x in waits(f, since) if x is None)
        ts = [c for c in th.get(key, []) if (T(c["last"]) - T(c["start"])).total_seconds() < 4 * 3600]
        mins = [(T(c["last"]) - T(c["start"])).total_seconds() / 60 for c in ts]
        steps = sum(c["calls"] for c in ts)
        book = sum(c["book"] for c in ts)
        if not (w or ts):
            continue
        print("%s\n  his wait: %s%s\n  turns: %d  median %.1f min  longest %.1f min  steps/turn %.0f  s/step %.0f  bookkeeping %d%%" % (
            f, ("median %.1f min, longest %.1f min over %d replies" % (statistics.median(w), max(w), len(w))) if w else "no replies in window",
            (", %d unanswered" % unanswered) if unanswered else "",
            len(ts), statistics.median(mins) if mins else 0, max(mins) if mins else 0, (steps / len(ts)) if ts else 0,
            (sum(mins) * 60 / steps) if steps else 0, round(100 * book / steps) if steps else 0))


if __name__ == "__main__":
    main()
