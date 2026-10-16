"""usage_capacity — the capacity lines: what the provider's own windows say when a run reported them, and what
Anchor has seen spend per engine in the five-hour window and the seven-day week.

W4 of the High Seat plan (2026-09-26). Two sources, both already on disk:

* **The limit signal.** Every Claude run Anchor launches writes the CLI's ``rate_limit_event`` lines into its job
  log — the account's own windows (``unifiedWindows``: five_hour and seven_day utilization, 0–1, with the epoch
  each resets at; a status of allowed / allowed_warning with the threshold it crossed / rejected). The newest such
  event this week is the Claude row's truth: it is the account's meter, so this Claude Code session and laptop
  chats count in it too. Read from the newest logs' tails, bounded; nothing is run and nothing is written.
* **Anchor-seen spend.** The usage ledgers (one document per engine session; every entry with its cli, tokens,
  wall-clock and when it was recorded) summed over the window and the week. They count only what Anchor launched,
  and the row says so. ChatGPT's and Grok's windows are unpublished, so those rows carry no percentage.

Two Claude subscriptions cannot be told apart (neither an entry nor an event carries the account). The answer is
cached in the process for five minutes. Never raises.
"""
from __future__ import annotations

import glob
import json
import os
import time
from datetime import datetime, timedelta, timezone

WINDOW = timedelta(hours=5)
WEEK = timedelta(days=7)
TTL = 300
AMBER = 0.8
ENGINES = (("claude", "Claude"), ("chatgpt", "ChatGPT"), ("grok", "Grok"))
_CACHE = {"at": 0.0, "key": None, "out": None}


def ledger_dir():
    import paths as _paths
    return os.path.join(_paths.data_dir(), ".anchor", "usage_ledger")


def jobs_dir():
    import job_runner as _jr
    return str(_jr.jobs_dir())


def _when(s):
    try:
        t = str(s or "").strip().replace("Z", "+00:00")
        d = datetime.fromisoformat(t)
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def fmt_tokens(n):
    n = int(n or 0)
    if n >= 1_000_000:
        return "%.1fM" % (n / 1_000_000)
    if n >= 1_000:
        return "%.1fk" % (n / 1_000)
    return str(n)


def fmt_reset(epoch, now):
    """16:40 today, else Sat 18:00 inside the week, else Oct 3 — in the machine's local time."""
    try:
        d = datetime.fromtimestamp(int(epoch)).astimezone()
    except Exception:
        return "unknown"
    local_now = now.astimezone()
    if d.date() == local_now.date():
        return d.strftime("%H:%M")
    if 0 < (d.date() - local_now.date()).days < 7:
        return d.strftime("%a %H:%M")
    return d.strftime("%b %d").replace(" 0", " ")


def _age(seen_at, now):
    try:
        m = int((now - seen_at).total_seconds() // 60)
    except Exception:
        return "at an unknown time"
    if m < 1:
        return "just now"
    if m < 60:
        return "%d min ago" % m
    if m < 48 * 60:
        return ("%d h %d min ago" % (m // 60, m % 60)) if m % 60 else ("%d h ago" % (m // 60))
    return "%d days ago" % (m // (60 * 24))


# ── the limit signal ───────────────────────────────────────────────────────────────────────────

def _tail(path, size=262144):
    with open(path, "rb") as f:
        f.seek(0, os.SEEK_END)
        n = f.tell()
        f.seek(max(0, n - size))
        return f.read().decode("utf-8", errors="replace")


def _last_event(text):
    marker = '"rate_limit_event"'          # the CLI writes it compact; a spaced form is tolerated
    k = text.rfind(marker)
    while k >= 0:
        a = text.rfind("\n", 0, k) + 1
        b = text.find("\n", k)
        line = text[a:b if b >= 0 else len(text)].strip()
        try:
            d = json.loads(line)
            info = d.get("rate_limit_info") if d.get("type") == "rate_limit_event" else None
            if isinstance(info, dict):
                return info
        except Exception:
            pass
        k = text.rfind(marker, 0, a) if a > 0 else -1
    return None


def latest_limit_signal(now=None, directory=None, max_logs=300, connection_id=None):
    """The newest rate_limit_event a Claude run wrote into a job log inside the week, or None."""
    now = now or datetime.now(timezone.utc)
    if directory is None:
        try:
            import usage_allowance_monitor as _uam
            persisted = _uam.load_persisted_rate_limit(connection_id or "claude-default")
            if isinstance(persisted, dict) and isinstance(persisted.get("rate_limit_info"), dict):
                mtime = float(persisted.get("mtime") or 0)
                if mtime >= (now - WEEK).timestamp():
                    info = persisted["rate_limit_info"]
                    uw = info.get("unifiedWindows") if isinstance(info.get("unifiedWindows"), dict) else {}
                    def _pwin(key):
                        w = uw.get(key) if isinstance(uw.get(key), dict) else {}
                        u, r = w.get("utilization"), w.get("resetsAt")
                        try:
                            u = float(u) if u is not None else None
                        except Exception:
                            u = None
                        try:
                            r = int(r) if r else None
                        except Exception:
                            r = None
                        return {"utilization": u, "resets_at": r}
                    seen = datetime.fromtimestamp(mtime, tz=timezone.utc)
                    return {"five_hour": _pwin("five_hour"), "seven_day": _pwin("seven_day"),
                            "status": str(info.get("status") or ""), "type": str(info.get("rateLimitType") or ""),
                            "threshold": info.get("surpassedThreshold"), "seen_at": seen.isoformat(), "log": "steward-live"}
        except Exception:
            pass
    d = directory or jobs_dir()
    cut = (now - WEEK).timestamp()
    try:
        logs = sorted((p for p in glob.glob(os.path.join(d, "*.log")) if os.path.getmtime(p) >= cut), key=os.path.getmtime, reverse=True)[:max_logs]
    except Exception:
        logs = []
    for p in logs:
        if connection_id is not None:
            # Legacy events are unqualified: never borrow their meter for a
            # selected subscription, including the apparent native default.
            try:
                with open(os.path.splitext(p)[0] + ".json", encoding="utf-8") as stream:
                    record = json.load(stream)
                if (record.get("provider_connection") or {}).get("id") != connection_id:
                    continue
            except (OSError, ValueError, AttributeError, TypeError):
                continue
        try:
            info = _last_event(_tail(p))
        except Exception:
            info = None
        if not info:
            continue
        uw = info.get("unifiedWindows") if isinstance(info.get("unifiedWindows"), dict) else {}

        def win(key):
            w = uw.get(key) if isinstance(uw.get(key), dict) else {}
            u, r = w.get("utilization"), w.get("resetsAt")
            try:
                u = float(u) if u is not None else None
            except Exception:
                u = None
            try:
                r = int(r) if r else None
            except Exception:
                r = None
            return {"utilization": u, "resets_at": r}
        try:
            seen = datetime.fromtimestamp(os.path.getmtime(p), tz=timezone.utc)
        except Exception:
            seen = now
        return {"five_hour": win("five_hour"), "seven_day": win("seven_day"), "status": str(info.get("status") or ""),
                "type": str(info.get("rateLimitType") or ""), "threshold": info.get("surpassedThreshold"),
                "seen_at": seen.isoformat(), "log": os.path.basename(p)}
    return None


# ── Anchor-seen spend ──────────────────────────────────────────────────────────────────────────

def _sums():
    return {"window_tokens": 0, "week_tokens": 0, "window_turns": 0, "week_turns": 0, "week_minutes": 0.0}


def _seen(directory, now):
    sums = {cli: _sums() for cli, _ in ENGINES}
    docs = 0
    cut = (now - WEEK).timestamp()
    try:
        # scandir carries each file's times on Windows: no stat per file (15k ledger files, 2026-10-10)
        with os.scandir(directory) as it:
            sigs = {e.path: (e.stat().st_mtime_ns, e.stat().st_size) for e in it if e.name.endswith(".json") and e.is_file()}
        paths = sorted(p for p, s in sigs.items() if s[0] / 1e9 >= cut)
    except Exception:
        paths, sigs = [], {}
    for p in paths:
        rows = _ledger_rows(p, sigs.get(p))
        if rows is None:
            continue
        docs += 1
        for cli, when, tokens, minutes in rows:
            if cli not in sums or when is None or when < now - WEEK or when > now + timedelta(minutes=5):
                continue
            s = sums[cli]
            s["week_tokens"] += tokens
            s["week_turns"] += 1
            s["week_minutes"] += minutes
            if when >= now - WINDOW:
                s["window_tokens"] += tokens
                s["window_turns"] += 1
    for gone in set(_ROWS) - set(paths):
        _ROWS.pop(gone, None)
    return sums, docs


_ROWS = {}   # path -> ((mtime_ns, size), rows): W7 (2026-10-10) a ledger file is parsed once, not on every refresh


def _ledger_rows(p, sig=None):
    """``[(cli, when, tokens, minutes)]`` of one ledger file, reparsed only when it changed; None when unreadable."""
    if sig is None:
        try:
            st = os.stat(p)
            sig = (st.st_mtime_ns, st.st_size)
        except OSError:
            return None
    hit = _ROWS.get(p)
    if hit and hit[0] == sig:
        return hit[1]
    try:
        doc = json.loads(open(p, encoding="utf-8").read())
    except Exception:
        return None
    rows = []
    entries = doc.get("entries") if isinstance(doc, dict) else None
    for e in (entries.values() if isinstance(entries, dict) else []):
        if not isinstance(e, dict):
            continue
        try:
            tokens = int(e.get("tokens") or 0)
        except Exception:
            tokens = 0
        try:
            minutes = float(e.get("duration_ms") or 0) / 60000.0
        except Exception:
            minutes = 0.0
        rows.append((str(e.get("cli") or "").lower(), _when(e.get("recorded_at")), tokens, minutes))
    _ROWS[p] = (sig, rows)
    return rows


# ── the rows ───────────────────────────────────────────────────────────────────────────────────

def _seen_words(s):
    if not (s["week_tokens"] or s["week_turns"]):
        return "Anchor-seen · nothing this week"
    return "Anchor-seen · %s tokens in the five-hour window · %s this week" % (fmt_tokens(s["window_tokens"]), fmt_tokens(s["week_tokens"]))


def _claude_row(s, sig, now):
    turns = "%d ledger entr%s this week" % (s["week_turns"], "y" if s["week_turns"] == 1 else "ies")
    base = {"name": "Claude", "cli": "claude", "window_tokens": s["window_tokens"], "week_tokens": s["week_tokens"],
            "window_turns": s["window_turns"], "week_turns": s["week_turns"], "week_minutes": round(s["week_minutes"], 1), "bars": [], "amber": ""}
    if not sig or sig["five_hour"]["utilization"] is None:
        base["state"] = _seen_words(s)
        base["note"] = ("%s, counted from what Anchor launched only; no Claude run this week has reported the account’s windows, so no percentage "
                        "— this Claude Code session, laptop chats and bare CLI runs drain the same windows unseen; claude.ai’s own bars are the truth" % turns)
        return base
    seen_at = _when(sig["seen_at"]) or now
    parts, bars, amber = [], [], []
    for key, label, word in (("five_hour", "5h", "five-hour window"), ("seven_day", "wk", "week")):
        w = sig[key]
        if w["utilization"] is None:
            parts.append("%s unknown" % word)
            bars.append({"label": label, "pct": None, "warn": False})
            continue
        pct = int(round(w["utilization"] * 100))
        warn = w["utilization"] >= AMBER
        reset = fmt_reset(w["resets_at"], now) if w["resets_at"] else "unknown"
        if w["resets_at"] and w["resets_at"] <= now.timestamp():
            # the window has reset since that run: the old percentage is not the account's meter now
            parts.append("%s reset at %s — was %d%% before it; no newer run has reported" % (word, reset, pct))
            bars.append({"label": label, "pct": None, "warn": False})
            continue
        parts.append("%s %d%% · resets %s" % (word, pct, reset))
        bars.append({"label": label, "pct": pct, "warn": warn})
        if warn:
            amber.append("%s at %d%%, resets %s" % (word, pct, reset))
    base["state"] = " · ".join(parts)
    base["bars"] = bars
    if amber:
        base["amber"] = "amber — over 80%% of a known limit: Claude’s %s; hold a long run until then" % "; ".join(amber)
    warned = (" · the CLI warned at %d%%" % int(round(float(sig["threshold"]) * 100))) if sig.get("threshold") else ""
    base["note"] = ("the account’s own windows as of the newest Claude run Anchor launched (%s, job %s) — it is that account as of that run, so a later chat is outside it; "
                    "two accounts cannot be told apart; %s, %s%s" % (_age(seen_at, now), sig["log"], _seen_words(s).replace("Anchor-seen · ", "Anchor-seen "), turns, warned))
    return base


def _other_row(cli, label, s):
    turns = "%d ledger entr%s this week" % (s["week_turns"], "y" if s["week_turns"] == 1 else "ies")
    note = ("%s, as the CLI reported them; the window is unpublished, so no percentage" % turns) if cli == "chatgpt" else (
        "%s · %d min; tokens where the CLI reported them, wall-clock otherwise; the window is unpublished" % (turns, int(round(s["week_minutes"]))))
    return {"name": label, "cli": cli, "state": _seen_words(s), "note": note, "window_tokens": s["window_tokens"], "week_tokens": s["week_tokens"],
            "window_turns": s["window_turns"], "week_turns": s["week_turns"], "week_minutes": round(s["week_minutes"], 1), "bars": [], "amber": ""}


def anchor_seen(now=None, directory=None, jobs=None, ttl=TTL):
    """``{"as_of", "docs", "signal", "rows"}`` — one row per engine Anchor runs, plus the Gemini placeholder. Never raises."""
    now = now or datetime.now(timezone.utc)
    d = directory or ledger_dir()
    j = jobs if jobs is not None else jobs_dir()
    key = (d, j)
    if _CACHE["out"] is not None and _CACHE["key"] == key and (time.time() - _CACHE["at"]) < ttl:
        return _CACHE["out"]
    sums, docs = _seen(d, now)
    try:
        sig = latest_limit_signal(now, j) if j else None
    except Exception:
        sig = None
    rows = [_claude_row(sums["claude"], sig, now), _other_row("chatgpt", "ChatGPT", sums["chatgpt"]), _other_row("grok", "Grok", sums["grok"])]
    rows.append({"name": "Gemini", "cli": "gemini", "state": "not connected", "note": "a future subscription — nothing to read",
                 "window_tokens": 0, "week_tokens": 0, "window_turns": 0, "week_turns": 0, "week_minutes": 0.0, "bars": [], "amber": ""})
    out = {"as_of": now.isoformat(), "docs": docs, "signal": sig, "rows": rows}
    _CACHE.update({"at": time.time(), "key": key, "out": out})
    return out


def capacity_rows(now=None, directory=None, jobs=None):
    """The rows the High Seat rail and the Desk foot render — name, state, note, bars, amber — or the honest fallback."""
    try:
        return [{"name": r["name"], "state": r["state"], "note": r["note"], "bars": r.get("bars") or [], "amber": r.get("amber") or ""}
                for r in anchor_seen(now, directory, jobs)["rows"]]
    except Exception:
        return [{"name": n, "state": "not measured", "note": "the usage ledgers could not be read", "bars": [], "amber": ""} for _, n in ENGINES] + [
            {"name": "Gemini", "state": "not connected", "note": "a future subscription — nothing to read", "bars": [], "amber": ""}]
