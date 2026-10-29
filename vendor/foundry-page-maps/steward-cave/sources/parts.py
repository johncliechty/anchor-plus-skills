"""campaign_parts — resolve a roadmap step's ``ref`` against the record it points at.

W0b of the High Seat plan (2026-09-26). A Campaign part is a step whose ``ref`` names
another record: ``project:<pid>`` · ``step:<pid>/<sid>`` · ``deliverable:<pid>/<row>`` ·
``calendar:<id>``. The Campaign never copies or writes the target's date or state; this
module READS them, once per distinct target per request (the ``cache`` dict the caller
passes), and names a broken reference instead of inventing anything.

Pure apart from file reads; never raises on odd input; no model, no bridge spawn.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import unquote

REF_KINDS = ("project", "step", "deliverable", "calendar", "effort")   # effort:<pid>/<dir> — one cockpit within a project (2026-09-30)
_OPEN = ("proposed", "planned", "active", "waiting")


def parse_ref(ref):
    """``'step:abc/lec3'`` → ``{"kind","pid","sub"}``; None when malformed."""
    s = str(ref or "").strip()
    if ":" not in s:
        return None
    kind, rest = s.split(":", 1)
    rest = rest.strip()
    if kind not in REF_KINDS or not rest or any(ch.isspace() for ch in rest):
        return None
    if kind in ("step", "deliverable", "effort"):
        if "/" not in rest:
            return None
        pid, sub = rest.split("/", 1)
        if not pid or not sub:
            return None
        if kind == "effort":
            # Stored refs have no literal whitespace; effort folders commonly do.
            # Decode once, then let resolve_ref enforce the one-directory boundary.
            try:
                sub = unquote(sub, errors="strict")
            except UnicodeError:
                return None
        return {"kind": kind, "pid": pid, "sub": sub}
    if kind == "calendar":
        return {"kind": kind, "pid": "", "sub": rest}
    return {"kind": kind, "pid": rest, "sub": ""}


def _default_lookup(pid):
    """The registry entry for the full id, nothing looser (a prefix would bind whichever project has it)."""
    try:
        import rnd_registry as _rnd
        return _rnd.get_project(pid) or None
    except Exception:
        return None


def _cached(cache, key, fn):
    if key in cache:
        return cache[key]
    try:
        v = fn()
    except Exception:
        v = None
    cache[key] = v
    return v


def _projection(folder, cache):
    def read():
        d = json.loads((Path(folder) / "roadmap.json").read_text(encoding="utf-8"))
        return d.get("roadmap_projection") or []
    return _cached(cache, ("projection", str(folder)), read)


def _summary(folder, cache):
    def read():
        d = json.loads((Path(folder) / ".ecgberht" / "status-summary.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    return _cached(cache, ("summary", str(folder)), read) or {}


def _strip_wait(folder, cache):
    def read():
        d = json.loads((Path(folder) / "strip.json").read_text(encoding="utf-8"))
        return str(d.get("human_wait") or "").strip()
    return _cached(cache, ("wait", str(folder)), read) or ""


def _register(folder, cache):
    def read():
        from .steward_campaign import _read_deliverables
        return (_read_deliverables(str(folder)) or {}).get("items") or []
    return _cached(cache, ("register", str(folder)), read) or []


def _nearest_due(steps):
    dues = sorted(str(s.get("due")) for s in steps or ()
                  if isinstance(s, dict) and s.get("due") and s.get("status") in _OPEN)
    return dues[0] if dues else ""


def resolve_ref(ref, cache=None, lookup=None, with_lead=False):
    """One part → ``{"ref","kind","pid","name","what","state","date","href","lead","broken","gap"}``."""
    cache = cache if isinstance(cache, dict) else {}
    lookup = lookup or _default_lookup
    out = {"ref": str(ref or ""), "kind": "", "pid": "", "name": "", "what": "", "state": "",
           "date": "", "href": "", "lead": "", "broken": True, "gap": ""}
    p = parse_ref(ref)
    if not p:
        out["gap"] = "not a reference the Campaign knows (project: · step: · deliverable: · calendar: · effort:)"
        return out
    out["kind"] = p["kind"]
    if p["kind"] == "calendar":
        out["gap"] = "calendar not connected"
        return out
    entry = _cached(cache, ("entry", p["pid"]), lambda: lookup(p["pid"]))
    if not entry or not entry.get("folder_path"):
        out["pid"] = p["pid"]
        out["gap"] = "no project with id %s" % p["pid"]
        return out
    folder = entry["folder_path"]
    out["pid"] = str(entry.get("id") or p["pid"])
    out["name"] = str(entry.get("name") or out["pid"][:8])
    steps = _projection(folder, cache)
    if p["kind"] == "project":
        out["href"] = "/project/%s" % out["pid"]
        # the same fact the home's rows use: the strip's human wait, else the last status's "waiting on you"
        wait = _strip_wait(folder, cache)
        if not wait:
            plan = _summary(folder, cache).get("plan")
            wait = " ".join(str((plan or {}).get("waiting_on_you") or "").split()) if isinstance(plan, dict) else ""
            wait = (wait[:88].rstrip() + "…") if len(wait) > 90 else wait
        out["state"] = ("waiting on you: " + wait) if wait else ""
        out["date"] = _nearest_due(steps)
        out["broken"] = False
    elif p["kind"] == "effort":
        # one cockpit within the project (2026-09-30): the effort directory with its own Face; its light is the
        # ONE attention flag the steward writes; its date the nearest due of its own roadmap
        from pathlib import Path as _P
        from urllib.parse import quote as _q
        eff = _P(folder) / p["sub"]
        sub_ = str(p["sub"])
        try:
            inside = eff.resolve().parent == _P(folder).resolve()
        except OSError:
            inside = False
        if sub_ in (".", "..") or "\\" in sub_ or "/" in sub_ or not inside:
            out["gap"] = "an effort is one directory inside %s, not '%s'" % (out["name"], sub_)      # Grok's read of W2b: never a path out of the project
            return out
        if not (eff / "ECGBERHT.md").is_file():
            out["gap"] = "no effort '%s' in %s" % (p["sub"], out["name"])
            return out
        title = p["sub"]
        try:
            for ln in (eff / "ECGBERHT.md").read_text(encoding="utf-8", errors="replace").splitlines()[:40]:
                if ln.startswith("# "):
                    heading = ln[2:].strip()
                    if heading and not heading.lower().startswith("ecgberht"):
                        title = heading
                    break
        except OSError:
            pass
        out["what"] = title
        out["dir"] = sub_
        out["name"] = "%s · %s" % (out["name"], title)
        out["href"] = "/project/%s?dir=%s" % (out["pid"], _q(p["sub"]))
        try:
            import json as _json
            att = _json.loads((eff / ".ecgberht" / "attention.json").read_text(encoding="utf-8"))
        except Exception:
            att = {}
        state = str((att or {}).get("state") or "").lower() if isinstance(att, dict) else ""
        reason = " ".join(str((att or {}).get("reason") or "").split()) if isinstance(att, dict) else ""
        reason = (reason[:88].rstrip() + "…") if len(reason) > 90 else reason
        out["state"] = ("waiting on you: " + reason) if state == "needs_you" else ((state.replace("_", " ") + ((": " + reason) if reason else "")) if state else "")
        out["date"] = _nearest_due(_projection(str(eff), cache))
        out["broken"] = False
    elif p["kind"] == "step":
        st = next((s for s in steps or () if isinstance(s, dict) and s.get("id") == p["sub"]), None)
        if st is None:
            out["gap"] = ("no step '%s' in %s" % (p["sub"], out["name"])) if steps is not None \
                else ("%s has no readable plan" % out["name"])
            return out
        out["href"] = "/project/%s" % out["pid"]
        out["what"] = str(st.get("name") or p["sub"])
        out["state"] = str(st.get("status") or "")
        # W1 (2026-09-28): the TARGET's own status, typed, so the Campaign's open/next reads the referenced step's
        # truth and never the wrapper's status alone (Grok's live replay: a done target stayed "next")
        out["target_status"] = str(st.get("status") or "")
        if st.get("waiting_on") and st.get("status") in ("waiting", "parked"):
            out["state"] += " · " + str(st.get("waiting_on"))
        out["date"] = str(st.get("due") or "")
        out["broken"] = False
    elif p["kind"] == "deliverable":
        items = _register(folder, cache)
        if not p["sub"].isdigit():
            out["gap"] = "a deliverable part names a row number (deliverable:<pid>/<n>); '%s' is not one" % p["sub"]
            return out
        n = int(p["sub"])
        it = items[n - 1] if 1 <= n <= len(items) else None
        if it is None:
            out["gap"] = "no row %d in %s's register (%d rows)" % (n, out["name"], len(items))
            return out
        out["what"] = str(it.get("what") or "")
        out["href"] = str(it.get("route") or "") or "/project/%s" % out["pid"]
        out["state"] = "current" if it.get("is_current") else ""
        out["broken"] = False
    if with_lead and not out["broken"]:
        out["lead"] = str(_summary(folder, cache).get("lead_line") or "")
    return out


def resolve_parts(steps, cache=None, lookup=None, with_lead=False):
    """Every step carrying ``ref`` → ``{step_id: resolved}``. Steps without ``ref`` are skipped."""
    cache = cache if isinstance(cache, dict) else {}
    out = {}
    for s in steps or ():
        try:
            if isinstance(s, dict) and s.get("ref") and s.get("id"):
                out[str(s["id"])] = resolve_ref(s["ref"], cache=cache, lookup=lookup, with_lead=with_lead)
        except Exception:
            continue
    return out
