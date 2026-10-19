"""The stewards' responsiveness, read from each effort's .ecgberht/turn-timing.jsonl (W1 of the two-lane plan,
2026-10-05): per steward, his turns - how long his message waited, how long to the first word, the whole turn, the
tools. Read only. Usage: python tools/steward_timing.py [--since 2026-10-05]"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _pct(xs, q):
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(round(q * (len(xs) - 1))))]


def rows_for(folder, since=""):
    out = []
    for p in [Path(folder) / ".ecgberht" / "turn-timing.jsonl"] + list(Path(folder).glob("*/.ecgberht/turn-timing.jsonl")):
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("at", "") >= since:
                    r["effort"] = p.parent.parent.name if p.parent.parent != Path(folder) else ""
                    out.append(r)
        except OSError:
            continue
    return out


def main():
    since = sys.argv[sys.argv.index("--since") + 1] if "--since" in sys.argv else ""
    import rnd_registry as r
    print("%-44s %5s %9s %9s %9s %6s" % ("steward", "turns", "wait p50", "word p50", "word p95", "tools"))
    for e in r.list_projects(include_archived=False):
        folder = e.get("folder_path")
        if not folder:
            continue
        by = {}
        for row in rows_for(folder, since):
            if row.get("origin") != "human":
                continue
            by.setdefault(row["effort"], []).append(row)
        for eff, rows in sorted(by.items()):
            first = [x.get("first_word_s") for x in rows]
            print("%-44s %5d %9s %9s %9s %6s" % ((e.get("name", "") + (" / " + eff if eff else ""))[:44], len(rows),
                  _pct([x.get("queued_s") for x in rows], .5), _pct(first, .5), _pct(first, .95),
                  _pct([x.get("tools") for x in rows], .5)))


if __name__ == "__main__":
    main()
