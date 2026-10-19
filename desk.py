"""desk — the Desk (John 2026-10-06, his mockup notes): admin work with no project. ONE Anchor project (DESK_DIR,
default C:/dev/Desk) whose efforts are AI Cockpits:

* **Small items** — one small-item cockpit for every admin item too small for its own cockpit. Its list lives INSIDE
  its own folder (``Small items/ITEMS.json``), so its steward keeps the list itself even behind the step-3 fence.
* every other effort — a SUBSTANTIAL admin effort with its own cockpit; like any cockpit it can be seated On deck or
  Active in the Cave (the Campaign's ``seat_new`` act with ``effort:<pid>/<dir>``).

An item that grows becomes its own cockpit in one act (``promote``): a new effort seeded with the item, the item
marked as moved. Pure file logic here; the server wires the routes and the pages render from ``summary``."""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

DESK_NAME = "Desk"
SMALL = "Small items"
ITEMS_FILE = "ITEMS.json"
_LOCK = threading.RLock()

SMALL_FACE = """# Ecgberht — Face (campaign memory)

## North star

Keep John's small admin items moving: each one done, or clearly waiting on someone, with nothing forgotten.

## Active effort

- The Small items list (ITEMS.json in this folder): one line per item; work them one at a time.

## Why next

- Read ITEMS.json; for each open item set its "state" (waits | working | quiet) and a one-line "note" on where it
  stands; mark it "done" when it is done. John adds items from the Desk page.
- An item that turns out to be substantial (many steps, days of work, its own deliverables): say so, and John moves it
  to its own cockpit with one click.

## Human wait

- None yet.
"""

EFFORT_FACE = """# Ecgberht — Face (campaign memory)

## North star

{name}

## Active effort

- Stand-up: this admin effort started from a Desk item{note}.

## Why next

- Draft the goal and the steps for John; ask him only what is genuinely his to decide.

## Human wait

- John: confirm what done looks like for "{name}".
"""


def desk_dir():
    return Path(os.environ.get("ANCHOR_DESK_DIR") or (Path(__file__).resolve().parent.parent / "Desk"))


def small_dir(root=None):
    return Path(root or desk_dir()) / SMALL


def ensure_small_items(root=None):
    """The Small items cockpit exists (its Face and an empty list) - idempotent, never overwrites."""
    d = small_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    if not (d / "ECGBERHT.md").exists():
        (d / "ECGBERHT.md").write_text(SMALL_FACE, encoding="utf-8")
    if not (d / ITEMS_FILE).exists():
        _write_items(d, [])
    return d


def read_items(root=None):
    try:
        data = json.loads((small_dir(root) / ITEMS_FILE).read_text(encoding="utf-8"))
        items = data.get("items") if isinstance(data, dict) else data
        return [i for i in items if isinstance(i, dict) and i.get("id") and i.get("text")] if isinstance(items, list) else []
    except Exception:
        return []


def _write_items(d, items):
    p = Path(d) / ITEMS_FILE
    tmp = p.with_suffix(".tmp-%s" % uuid.uuid4().hex[:6])
    tmp.write_text(json.dumps({"items": items}, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, p)


def add_item(text, root=None):
    text = " ".join(str(text or "").split())[:300]
    if not text:
        return {"ok": False, "error": "an item needs words"}
    with _LOCK:
        d = ensure_small_items(root)
        items = read_items(root)
        item = {"id": uuid.uuid4().hex[:8], "text": text, "status": "open", "state": "quiet", "note": "",
                "added": time.strftime("%Y-%m-%d %H:%M")}
        items.append(item)
        _write_items(d, items)
    return {"ok": True, "item": item}


def set_done(item_id, done=True, root=None):
    with _LOCK:
        items = read_items(root)
        it = next((i for i in items if i["id"] == item_id), None)
        if it is None:
            return {"ok": False, "error": "no such item"}
        it["status"] = "done" if done else "open"
        it["done_at" if done else "reopened_at"] = time.strftime("%Y-%m-%d %H:%M")
        _write_items(small_dir(root), items)
    return {"ok": True, "item": it}


def _effort_name(text):
    """A folder name from an item's words: letters, digits, spaces and - only; short; never empty."""
    keep = "".join(c if (c.isalnum() or c in " -") else " " for c in text)
    name = " ".join(keep.split())[:60].strip(" -")
    return name or "Desk effort"


def promote(item_id, root=None):
    """The item becomes its own cockpit: a new effort folder seeded with the item; the item is marked moved."""
    with _LOCK:
        items = read_items(root)
        it = next((i for i in items if i["id"] == item_id), None)
        if it is None:
            return {"ok": False, "error": "no such item"}
        if it.get("status") == "moved":
            return {"ok": True, "dir": it.get("moved_to"), "already": True}
        base = _effort_name(it["text"])
        name, n = base, 2
        while (Path(root or desk_dir()) / name).exists():
            name, n = "%s %d" % (base, n), n + 1
        out = new_cockpit(name, root=root, note=it.get("note") or "")
        if not out.get("ok"):
            return out
        it.update(status="moved", moved_to=name, moved_at=time.strftime("%Y-%m-%d %H:%M"))
        _write_items(small_dir(root), items)
    return {"ok": True, "dir": name}


def new_cockpit(name, root=None, note=""):
    name = " ".join(str(name or "").split())
    if not name or name.lower() == SMALL.lower() or any(c in name for c in '\\/:*?"<>|') or ".." in name:
        return {"ok": False, "error": "a cockpit needs a plain name"}
    d = Path(root or desk_dir()) / name
    if (d / "ECGBERHT.md").exists():
        return {"ok": False, "error": "that cockpit already exists"}
    d.mkdir(parents=True, exist_ok=True)
    (d / "ECGBERHT.md").write_text(EFFORT_FACE.format(name=name, note=(" - its note: " + note) if note else ""),
                                   encoding="utf-8")
    return {"ok": True, "dir": name}


def cockpit_dirs(root=None):
    """The substantial cockpits: every effort folder under the Desk except Small items, newest first."""
    r = Path(root or desk_dir())
    if not r.is_dir():
        return []
    out = [p for p in r.iterdir() if p.is_dir() and p.name != SMALL and (p / "ECGBERHT.md").is_file()]
    return [p.name for p in sorted(out, key=lambda p: (p / "ECGBERHT.md").stat().st_mtime, reverse=True)]


def summary(light_of, seat_of=None, root=None):
    """What both pages show. ``light_of(folder) -> {light, word, why}`` (the Cave's own light rule);
    ``seat_of(dir) -> "active"|"deck"|""`` (the Campaign record). Never raises on a missing Desk."""
    r = Path(root or desk_dir())
    items = read_items(root)
    open_items = [i for i in items if i.get("status") == "open"]
    small = {"dir": SMALL, "items": open_items, "done": sum(1 for i in items if i.get("status") == "done"),
             **(light_of(str(small_dir(root))) if (small_dir(root) / "ECGBERHT.md").is_file() else {"light": "gray", "word": "idle", "why": ""})}
    if any(i.get("state") == "waits" for i in open_items) and small["light"] in ("gray", "green"):
        waiting = next(i for i in open_items if i.get("state") == "waits")
        small.update(light="orange", word="needs you", why=small.get("why") or ("%s%s" % (waiting["text"], (" - " + waiting["note"]) if waiting.get("note") else "")))
    cockpits = []
    for d in cockpit_dirs(root):
        c = {"dir": d, "name": d, **light_of(str(r / d))}
        c["seat"] = (seat_of(d) if seat_of else "") or ""
        cockpits.append(c)
    waits = int(small["light"] == "orange") + sum(1 for c in cockpits if c["light"] == "orange")
    return {"small": small, "cockpits": cockpits, "waits": waits}


def steward_command(text, root=None):
    """Wave 21: Sub-20ms deterministic Desk Steward command execution."""
    import re
    raw = " ".join(str(text or "").split())
    if not raw:
        return {"ok": False, "error": "Say what you want the Desk Steward to do."}
    low = raw.lower()

    # 1. Mark all small items done
    if re.search(r"\b(mark|check|complete|finish)\s+(all|every(?:thing)?)\b", low):
        open_its = [i for i in read_items(root) if i.get("status") == "open"]
        for it in open_its:
            set_done(it["id"], done=True, root=root)
        msg = "Marked %d open small item(s) done." % len(open_its)
        return {"ok": True, "say": msg, "receipt": msg, "mutated": True}

    # 2. Create / start a new substantial cockpit
    m_new = re.match(
        r"^(?:please\s+)?(?:create|start|open|new|launch)\s+(?:a\s+)?(?:new\s+)?(?:substantial\s+)?(?:ai\s+)?cockpit(?:\s+(?:called|named|for))?\s*[:\-]?\s*(.+)$",
        raw,
        re.I,
    )
    if m_new:
        cname = m_new.group(1).strip(" .\"'")
        res = new_cockpit(cname, root=root)
        if not res.get("ok"):
            return {"ok": False, "error": res.get("error") or "Could not create cockpit."}
        msg = 'Created substantial Desk cockpit "%s".' % res["dir"]
        return {"ok": True, "say": msg, "receipt": msg, "dir": res["dir"], "mutated": True}

    # 3. Promote an existing small item to its own cockpit
    m_prom = re.match(
        r"^(?:please\s+)?(?:promote|upgrade|move)\s+(.+?)(?:\s+to\s+(?:its\s+own\s+|a\s+)?cockpit)?$",
        raw,
        re.I,
    )
    if m_prom:
        q = m_prom.group(1).strip(" .\"'").lower()
        open_its = [i for i in read_items(root) if i.get("status") == "open"]
        hit = next((i for i in open_its if q in i.get("text", "").lower() or i.get("id") == q), None)
        if hit:
            res = promote(hit["id"], root=root)
            if res.get("ok"):
                msg = 'Promoted "%s" to its own Desk cockpit (%s).' % (hit["text"], res.get("dir"))
                return {"ok": True, "say": msg, "receipt": msg, "dir": res.get("dir"), "mutated": True}

    # 4. Mark a specific small item done
    m_done = re.match(
        r"^(?:please\s+)?(?:mark|check|complete|finish)\s+(.+?)(?:\s+as\s+done|\s+done)?$",
        raw,
        re.I,
    )
    if m_done:
        q = m_done.group(1).strip(" .\"'").lower()
        open_its = [i for i in read_items(root) if i.get("status") == "open"]
        hit = next((i for i in open_its if q in i.get("text", "").lower() or i.get("id") == q), (open_its[0] if (q in ("next", "first", "top") and open_its) else None))
        if hit:
            set_done(hit["id"], done=True, root=root)
            msg = 'Marked "%s" done.' % hit["text"]
            return {"ok": True, "say": msg, "receipt": msg, "item": hit, "mutated": True}

    # 5. Add a small item
    m_add = re.match(
        r"^(?:please\s+)?(?:add|create|note|put|log)(?:\s+(?:a\s+)?(?:small\s+)?(?:admin\s+)?item)?\s*[:\-]?\s*(.+)$",
        raw,
        re.I,
    )
    if m_add:
        txt = m_add.group(1).strip(" .\"'")
        res = add_item(txt, root=root)
        if res.get("ok"):
            msg = 'Added small item: "%s".' % res["item"]["text"]
            return {"ok": True, "say": msg, "receipt": msg, "item": res["item"], "mutated": True}

    # 6. Triage / status summary
    items = read_items(root)
    open_its = [i for i in items if i.get("status") == "open"]
    done_cnt = sum(1 for i in items if i.get("status") == "done")
    c_dirs = cockpit_dirs(root)
    msg = (
        "Desk Triage Summary: %d open small item(s), %d completed, and %d substantial cockpit(s) (%s)."
        % (len(open_its), done_cnt, len(c_dirs), ", ".join(c_dirs[:4]) if c_dirs else "none yet")
    )
    return {"ok": True, "say": msg, "receipt": msg, "mutated": False}

