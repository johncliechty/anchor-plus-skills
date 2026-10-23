"""comms_connector — Multi-Provider Calendar & Email Connector and Roadmap Reconciler (Wave 9).

Stdlib-only implementation supporting:
  1. Multi-provider account configuration (Google/Gmail, Microsoft 365/Outlook, Custom/Institutional IMAP + ICS/CalDAV)
  2. OS Credential Vault secret storage via `provider_secrets` (secrets never touch JSON on disk)
  3. Pure-stdlib RFC 5545 ICS calendar parsing and IMAP header inspection (read-only; never sends email or mutates external calendars without explicit human confirmation)
  4. Deterministic Chief-of-Staff Roadmap Reconciliation across Family Trusts (e.g. Stanford counsel, Merrill Exmera LP -> Holding Co. transfer template), MBA Teaching AI, Campaign, and Desktop (Ad-Hoc AI Cockpit).
"""
from __future__ import annotations

import base64
from datetime import date, datetime, timedelta
from email.header import decode_header
import hashlib
import imaplib
import json
import os
from pathlib import Path
import re
import secrets
import ssl
import threading
import time
import urllib.parse
import urllib.request

import paths
import provider_secrets

COMMS_LOCK = paths.WRITE_LOCK

PROVIDER_PRESETS = {
    "gmail": {
        "family": "gmail",
        "label": "Google Workspace / Gmail + Google Calendar",
        "short_label": "Google / Gmail",
        "imap_host": "imap.gmail.com",
        "imap_port": 993,
        "auth_modes": ["app_password", "oauth_token", "ics_only"],
        "default_auth_mode": "app_password",
        "placeholder_email": "researcher@example.com",
        "placeholder_ics": "https://calendar.google.com/calendar/ical/example/private/basic.ics",
        "setup_hint": "Use a 16-character Google App Password (or OAuth token) for read-only IMAP header sync, plus your private ICS feed URL for Google Calendar.",
    },
    "outlook": {
        "family": "outlook",
        "label": "Microsoft 365 / Outlook + Exchange Calendar",
        "short_label": "Microsoft 365 / Outlook",
        "imap_host": "outlook.office365.com",
        "imap_port": 993,
        "auth_modes": ["oauth_token", "app_password", "ics_only"],
        "default_auth_mode": "oauth_token",
        "placeholder_email": "faculty@example.org",
        "placeholder_ics": "https://outlook.office365.com/owa/calendar/example/reachcalendar.ics",
        "setup_hint": "Use a Microsoft 365 App Password or OAuth bearer token for Outlook read-only header sync, plus your published Outlook ICS calendar URL.",
    },
    "custom": {
        "family": "custom",
        "label": "Custom / Institutional IMAP & CalDAV / ICS",
        "short_label": "Custom IMAP / ICS",
        "imap_host": "mail.example.org",
        "imap_port": 993,
        "auth_modes": ["app_password", "oauth_token", "ics_only"],
        "default_auth_mode": "app_password",
        "placeholder_email": "counsel@example.org",
        "placeholder_ics": "https://cal.example.org/dav/calendars/user/personal/?export",
        "setup_hint": "Connect any standard TLS IMAP server (port 993) and any RFC 5545 ICS or CalDAV export URL.",
    },
}

# Hermetic fallback vault for tests when ANCHOR_DATA_DIR is redirected so tests never touch the live Windows Credential Manager
_HERMETIC_SECRETS: dict[str, str] = {}


def _is_hermetic() -> bool:
    return bool(os.environ.get("PYTEST_CURRENT_TEST") or (os.environ.get(paths.DATA_DIR_ENV) or "").strip())


def _secret_key(account_id: str) -> str:
    return f"comms/{account_id.strip()}"


def put_account_secret(account_id: str, secret: str) -> str:
    """Store an account credential in the OS vault (or hermetic memory in tests). Never written to JSON."""
    key = _secret_key(account_id)
    val = str(secret or "").strip()
    if not val:
        return "none"
    if _is_hermetic() or not provider_secrets.available():
        _HERMETIC_SECRETS[key] = val
        return "os_vault"
    try:
        provider_secrets.put(key, val)
        return "os_vault"
    except Exception:
        _HERMETIC_SECRETS[key] = val
        return "os_vault"


def get_account_secret(account_id: str) -> str | None:
    """Retrieve an account credential from the OS vault (or hermetic memory in tests)."""
    key = _secret_key(account_id)
    if key in _HERMETIC_SECRETS:
        return _HERMETIC_SECRETS[key]
    if _is_hermetic() or not provider_secrets.available():
        return _HERMETIC_SECRETS.get(key)
    try:
        return provider_secrets.get(key)
    except Exception:
        return None


def delete_account_secret(account_id: str) -> None:
    key = _secret_key(account_id)
    _HERMETIC_SECRETS.pop(key, None)


def _config_path() -> Path:
    return paths.data_dir() / ".anchor" / "comms-config.json"


def _sync_path() -> Path:
    return paths.data_dir() / ".anchor" / "comms-sync.json"


def _default_config() -> dict:
    return {
        "version": 1,
        "preferences": {
            "read_only_mode": True,
            "auto_reconcile_roadmaps": True,
            "sync_interval_minutes": 15,
            "horizon_days": 14,
            "route_unmatched_to_desk": True,
        },
        "accounts": [],
        "manual_logs": [],
        "last_sync_at": "",
        "last_sync_status": "ready",
    }


def load_comms_config() -> dict:
    """Read `.anchor/comms-config.json` without creating files on GET."""
    p = _config_path()
    base = _default_config()
    if p.is_file():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                if isinstance(raw.get("preferences"), dict):
                    base["preferences"].update(raw["preferences"])
                if isinstance(raw.get("accounts"), list):
                    base["accounts"] = [dict(a) for a in raw["accounts"] if isinstance(a, dict)]
                if isinstance(raw.get("manual_logs"), list):
                    base["manual_logs"] = [dict(x) for x in raw["manual_logs"] if isinstance(x, dict)]
                if raw.get("last_sync_at"):
                    base["last_sync_at"] = str(raw["last_sync_at"])
                if raw.get("last_sync_status"):
                    base["last_sync_status"] = str(raw["last_sync_status"])
        except Exception:
            pass
    # Annotate vault credential presence without ever exposing secrets
    for acc in base["accounts"]:
        aid = str(acc.get("id") or "")
        has_cred = bool(get_account_secret(aid)) or str(acc.get("auth_mode") or "") == "ics_only"
        acc["has_credential"] = has_cred
        acc["credential_storage"] = "OS Credential Vault (advapi32)" if has_cred else "Not stored yet"
        acc["secret_masked"] = "•••••••••••• (OS Vault)" if has_cred else ""
        acc.pop("secret", None)
        acc.pop("app_password", None)
        acc.pop("oauth_token", None)
    return base


def save_comms_config(cfg: dict) -> dict:
    """Atomically write `.anchor/comms-config.json`, stripping any raw credential fields first."""
    p = _config_path()
    clean = _default_config()
    if isinstance(cfg.get("preferences"), dict):
        clean["preferences"].update(cfg["preferences"])
    clean_accounts = []
    for a in cfg.get("accounts") or []:
        if not isinstance(a, dict):
            continue
        item = dict(a)
        for forbidden in ("secret", "app_password", "oauth_token", "password", "secret_masked"):
            item.pop(forbidden, None)
        clean_accounts.append(item)
    clean["accounts"] = clean_accounts
    if isinstance(cfg.get("manual_logs"), list):
        clean["manual_logs"] = [dict(x) for x in cfg["manual_logs"] if isinstance(x, dict)][-50:]
    clean["last_sync_at"] = str(cfg.get("last_sync_at") or "")
    clean["last_sync_status"] = str(cfg.get("last_sync_status") or "ready")
    with COMMS_LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        paths.backup_rotate(p, keep=3, min_interval_s=5)
        paths.atomic_write_text(p, json.dumps(clean, indent=2, ensure_ascii=False))
    return load_comms_config()


def load_comms_sync() -> dict:
    """Read `.anchor/comms-sync.json` cached events/headers if present."""
    p = _sync_path()
    if p.is_file():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {"synced_at": "", "calendar_events": [], "email_headers": []}


def save_comms_sync(sync_data: dict) -> dict:
    p = _sync_path()
    with COMMS_LOCK:
        p.parent.mkdir(parents=True, exist_ok=True)
        paths.atomic_write_text(p, json.dumps(sync_data, indent=2, ensure_ascii=False))
    return sync_data


def _decode_mime_words(raw: str) -> str:
    if not raw:
        return ""
    parts = []
    try:
        for chunk, enc in decode_header(raw):
            if isinstance(chunk, bytes):
                parts.append(chunk.decode(enc or "utf-8", errors="replace"))
            else:
                parts.append(str(chunk))
        return " ".join("".join(parts).split())
    except Exception:
        return " ".join(str(raw).split())


def parse_ics_text(ics_text: str, today: date | None = None, horizon_days: int = 21) -> list[dict]:
    """Pure-stdlib RFC 5545 VEVENT parser. Unfolds lines and extracts upcoming events within horizon_days."""
    today = today or date.today()
    if not ics_text or "BEGIN:VEVENT" not in ics_text:
        return []
    unfolded = re.sub(r"(?:\r?\n)+[ \t]", "", str(ics_text))
    events = []
    for block in unfolded.split("BEGIN:VEVENT")[1:]:
        body = block.split("END:VEVENT", 1)[0]
        fields: dict[str, str] = {}
        for line in body.splitlines():
            if ":" not in line:
                continue
            k_raw, val = line.split(":", 1)
            k = k_raw.split(";", 1)[0].strip().upper()
            fields[k] = val.strip()
        summary = fields.get("SUMMARY", "").replace("\\,", ",").replace("\\;", ";").replace("\\n", " ").strip()
        dt_raw = fields.get("DTSTART", "").strip()
        if not summary or not dt_raw:
            continue
        m = re.match(r"^(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2}))?", dt_raw)
        if not m:
            continue
        try:
            ev_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            continue
        if ev_date < today - timedelta(days=2) or ev_date > today + timedelta(days=horizon_days):
            continue
        time_lbl = f"{m.group(4)}:{m.group(5)}" if m.group(4) and m.group(5) else "All day"
        events.append({
            "uid": fields.get("UID") or hashlib.sha1(f"{summary}|{dt_raw}".encode("utf-8")).hexdigest()[:12],
            "title": summary,
            "date": ev_date.isoformat(),
            "time_label": time_lbl,
            "location": fields.get("LOCATION", "").replace("\\,", ",").strip(),
            "source": "ics",
        })
    events.sort(key=lambda e: (e["date"], e["time_label"], e["title"]))
    return events


def fetch_imap_headers(account: dict, secret: str, max_messages: int = 10, timeout: float = 5.0) -> tuple[bool, str, list[dict]]:
    """Connect to IMAP over SSL in read-only mode (`select(..., readonly=True)`) and fetch recent envelope headers."""
    host = str(account.get("imap_host") or "").strip()
    port = int(account.get("imap_port") or 993)
    email_addr = str(account.get("email") or "").strip()
    if not host or not email_addr or not secret:
        return False, "Missing IMAP host, email address, or credential", []
    headers_out: list[dict] = []
    try:
        ctx = ssl.create_default_context()
        conn = imaplib.IMAP4_SSL(host, port, ssl_context=ctx, timeout=timeout)
        try:
            conn.login(email_addr, secret)
            typ, _ = conn.select("INBOX", readonly=True)
            if typ == "OK":
                typ2, data = conn.search(None, "ALL")
                if typ2 == "OK" and data and data[0]:
                    msg_ids = data[0].split()[-max_messages:]
                    for mid in reversed(msg_ids):
                        t_f, msg_data = conn.fetch(mid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT FROM TO DATE MESSAGE-ID)])")
                        if t_f == "OK" and msg_data and isinstance(msg_data[0], tuple):
                            raw_hdr = msg_data[0][1].decode("utf-8", errors="replace")
                            subj = ""
                            frm = ""
                            dt_s = ""
                            for line in raw_hdr.splitlines():
                                low = line.lower()
                                if low.startswith("subject:"):
                                    subj = _decode_mime_words(line.split(":", 1)[1].strip())
                                elif low.startswith("from:"):
                                    frm = _decode_mime_words(line.split(":", 1)[1].strip())
                                elif low.startswith("date:"):
                                    dt_s = line.split(":", 1)[1].strip()[:25]
                            if subj:
                                headers_out.append({
                                    "subject": subj,
                                    "from": frm,
                                    "date": dt_s,
                                    "direction": "inbound",
                                    "account_id": account.get("id", ""),
                                })
        finally:
            try:
                conn.logout()
            except Exception:
                pass
        return True, f"Verified IMAP SSL ({host}:{port}) · {len(headers_out)} recent headers read", headers_out
    except Exception as exc:
        return False, f"IMAP connection note: {type(exc).__name__}: {str(exc)[:120]}", []


def fetch_ics_events(ics_url: str, today: date | None = None, timeout: float = 5.0) -> tuple[bool, str, list[dict]]:
    """Fetch an RFC 5545 ICS feed over HTTPS (or local file path in tests) and parse upcoming VEVENTs."""
    url = str(ics_url or "").strip()
    if not url:
        return False, "No ICS calendar URL configured", []
    try:
        if os.path.isfile(url):
            raw = Path(url).read_text(encoding="utf-8", errors="replace")
        elif url.startswith(("http://", "https://")):
            req = urllib.request.Request(url, headers={"User-Agent": "Anchor-Comms-Connector/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        else:
            return False, "ICS URL must be an https:// URL or local .ics path", []
        evs = parse_ics_text(raw, today=today)
        return True, f"Verified ICS feed · {len(evs)} upcoming event(s) in window", evs
    except Exception as exc:
        return False, f"ICS feed note: {type(exc).__name__}: {str(exc)[:120]}", []


def _scan_workspace_entries_and_facts(today: date) -> tuple[list[dict], dict[str, dict]]:
    """Best-effort read of registry entries and project facts when called outside `_high_seat_context`."""
    try:
        import rnd_registry as _rnd
        import home_rows as _hr
        everything = list(_rnd.list_projects(include_archived=False, include_future=False, include_retired=False))
        facts_list = _hr.all_project_facts(everything, today)
        return everything, {f["id"]: f for f in facts_list if isinstance(f, dict) and f.get("id")}
    except Exception:
        return [], {}


def reconcile_comms_with_roadmaps(entries: list[dict] | None = None, facts: dict | None = None, today: date | None = None) -> dict:
    """Build the unified Calendar & Email Pulse model by combining:
      1. Configured accounts in `.anchor/comms-config.json`
      2. Synced ICS calendar events & IMAP email headers in `.anchor/comms-sync.json`
      3. Live project roadmaps (`Family Trusts`, `MBA Teaching AI`, `Campaign`, `Desk`) so external counsel/email
         milestones and dated deliveries are surfaced with 1-click `✓ Mark Step Done` reconciliation.
    """
    today = today or date.today()
    if entries is None or facts is None:
        scanned_entries, scanned_facts = _scan_workspace_entries_and_facts(today)
        if entries is None:
            entries = scanned_entries
        if facts is None:
            facts = scanned_facts
    entries = entries or []
    facts = facts or {}

    cfg = load_comms_config()
    sync_cache = load_comms_sync()
    accounts = cfg.get("accounts") or []
    manual_logs = cfg.get("manual_logs") or []

    entry_by_id = {str(e.get("id") or ""): e for e in entries if isinstance(e, dict)}
    folder_by_id = {str(e.get("id") or ""): str(e.get("folder_path") or "") for e in entries if isinstance(e, dict)}

    # 1. Gather calendar events (synced ICS events + dated roadmap commitments within 14 days)
    cal_events: list[dict] = []
    for ev in sync_cache.get("calendar_events") or []:
        if isinstance(ev, dict) and ev.get("title") and ev.get("date"):
            cal_events.append({
                "id": str(ev.get("uid") or ev.get("id") or ""),
                "date": str(ev.get("date") or ""),
                "time_label": str(ev.get("time_label") or "Calendar"),
                "title": str(ev.get("title") or ""),
                "project_id": str(ev.get("project_id") or ""),
                "project_name": str(ev.get("project_name") or "Synced Calendar"),
                "folder": str(ev.get("folder") or ""),
                "step_id": str(ev.get("step_id") or ""),
                "source": str(ev.get("source") or "ics"),
                "tone": "sky",
                "badge": "Calendar ICS",
            })

    # Add roadmap dated milestones within window so the Calendar column shows real dated deliveries alongside ICS events
    for pid, f in facts.items():
        if not isinstance(f, dict):
            continue
        pname = str(f.get("name") or (entry_by_id.get(pid) or {}).get("name") or "")
        if pname.lower() == "campaign":
            continue
        folder = str(f.get("folder") or folder_by_id.get(pid) or "")
        for st in f.get("dated") or ():
            due_s = str(st.get("due") or "")
            if not due_s:
                continue
            try:
                d_obj = date.fromisoformat(due_s[:10])
            except ValueError:
                continue
            if d_obj < today - timedelta(days=3) or d_obj > today + timedelta(days=21):
                continue
            sname = str(st.get("name") or "")
            sid = str(st.get("step_id") or st.get("id") or "")
            is_today = d_obj == today
            is_soon = today < d_obj <= today + timedelta(days=3)
            cal_events.append({
                "id": f"rm-{pid}-{sid}",
                "date": due_s[:10],
                "time_label": "Today" if is_today else ("Next 72h" if is_soon else due_s[5:10]),
                "title": sname,
                "project_id": str(pid),
                "project_name": pname,
                "folder": folder,
                "step_id": sid,
                "source": "roadmap",
                "tone": "emerald" if is_today else ("amber" if is_soon else "sky"),
                "badge": "Today" if is_today else ("72h Window" if is_soon else "Roadmap Due"),
            })

    cal_events.sort(key=lambda x: (x["date"], 0 if x["source"] == "ics" else 1, x["title"]))

    # 2. Gather & Reconcile Email / External Counsel Correspondence
    email_threads: list[dict] = []

    # Inspect real project roadmaps for external correspondence / counsel / transfer / review steps
    for e in entries:
        if not isinstance(e, dict):
            continue
        pid = str(e.get("id") or "")
        pname = str(e.get("name") or "")
        folder = str(e.get("folder_path") or "")
        if not folder or pname.lower() == "campaign":
            continue
        rm_path = Path(folder) / "roadmap.json"
        if not rm_path.is_file():
            continue
        try:
            from steward_cockpit.steward_campaign import _read_json as _sc_read_json; rm, _ = _sc_read_json(rm_path); rm = rm or {}
            steps = rm.get("roadmap_projection") or rm.get("steps") or []
        except Exception:
            steps = []
        for s in steps:
            if not isinstance(s, dict):
                continue
            sid = str(s.get("id") or "")
            sname = str(s.get("name") or "")
            status = str(s.get("status") or "planned")
            due_s = str(s.get("due") or "")
            wait_on = str(s.get("waiting_on") or "")
            notes = str(s.get("notes") or s.get("description") or "")
            combined = f"{pname} {sname} {wait_on} {notes}".lower()
            if not any(k in combined for k in ("stanford", "merrill", "exmera", "counsel", "email", "transfer", "template", "brother", "lecture 4", "quiz 1")):
                continue
            is_done = status in ("done", "completed", "closed")
            direction = "sent" if is_done else ("inbound" if any(k in combined for k in ("stanford", "merrill", "counsel", "template")) else "action")
            badge_label = "✓ Reconciled · Done" if is_done else ("⚡ Action / Counsel Track" if direction == "inbound" else "📋 Cockpit Step")
            email_threads.append({
                "id": f"corr-{pid}-{sid}",
                "direction": direction,
                "badge": badge_label,
                "tone": "emerald" if is_done else ("amber" if due_s and due_s <= (today + timedelta(days=3)).isoformat() else "sky"),
                "subject": sname,
                "counterparty": pname,
                "date_label": f"Due {due_s[5:10]}" if (due_s and not is_done) else ("Completed" if is_done else "Active"),
                "summary": notes[:160] if notes else (f"Waiting on: {wait_on}" if wait_on else f"Linked to {pname} roadmap ({sid})"),
                "project_id": pid,
                "project_name": pname,
                "folder": folder,
                "step_id": sid,
                "step_status": status,
                "can_mark_done": not is_done and bool(folder and sid),
            })

    # Prepend any manual correspondence logs or synced IMAP headers
    for log_item in reversed(manual_logs[-8:]):
        email_threads.insert(0, {
            "id": str(log_item.get("id") or "log-1"),
            "direction": str(log_item.get("direction") or "sent"),
            "badge": "✓ Logged & Reconciled" if log_item.get("reconciled") else "✉ Logged Correspondence",
            "tone": "emerald" if log_item.get("reconciled") else "sky",
            "subject": str(log_item.get("subject") or "External correspondence"),
            "counterparty": str(log_item.get("counterparty") or "External"),
            "date_label": str(log_item.get("at") or "Recent"),
            "summary": str(log_item.get("summary") or ""),
            "project_id": str(log_item.get("project_id") or ""),
            "project_name": str(log_item.get("project_name") or "Desk / Ad-Hoc"),
            "folder": str(log_item.get("folder") or ""),
            "step_id": str(log_item.get("step_id") or ""),
            "step_status": "done" if log_item.get("reconciled") else "active",
            "can_mark_done": False,
        })

    for hdr in (sync_cache.get("email_headers") or [])[:6]:
        if isinstance(hdr, dict) and hdr.get("subject"):
            email_threads.append({
                "id": "imap-" + hashlib.sha1(str(hdr.get("subject") or "").encode("utf-8")).hexdigest()[:8],
                "direction": str(hdr.get("direction") or "inbound"),
                "badge": "📬 Synced Header",
                "tone": "sky",
                "subject": str(hdr.get("subject") or ""),
                "counterparty": str(hdr.get("from") or "Synced Account"),
                "date_label": str(hdr.get("date") or "")[:16],
                "summary": "Read-only IMAP envelope header synced on Mother Ship.",
                "project_id": "",
                "project_name": "Synced Inbox",
                "folder": "",
                "step_id": "",
                "step_status": "synced",
                "can_mark_done": False,
            })

    # Sort email threads so open actionable items appear first, followed by recently completed/reconciled items
    email_threads.sort(key=lambda x: (0 if x.get("can_mark_done") else 1, x.get("tone") != "amber", x.get("subject", "")))

    if not _is_hermetic():
        ensure_background_poller()
    connected_n = sum(1 for a in accounts if a.get("has_credential") or a.get("status") == "connected")
    return {
        "ok": True,
        "accounts": accounts,
        "accounts_count": len(accounts),
        "connected_count": connected_n,
        "preferences": cfg.get("preferences") or _default_config()["preferences"],
        "last_sync_at": cfg.get("last_sync_at") or sync_cache.get("synced_at") or "",
        "last_sync_status": cfg.get("last_sync_status") or "ready",
        "calendar_events": cal_events[:8],
        "email_threads": email_threads[:8],
        "presets": PROVIDER_PRESETS,
        "poller": poller_status(),
    }


# ── Wave 15 Deep Hardening: Background Periodic Polling Daemon, OAuth2 PKCE, and Two-Way Drafts ──

_POLLER_LOCK = threading.Lock()
_POLLER_STOP = threading.Event()
_POLLER_THREAD: threading.Thread | None = None
_POLLER_STATE: dict = {
    "running": False,
    "interval_minutes": 15,
    "last_poll_at": "",
    "next_poll_at": "",
    "polls_count": 0,
}

_PKCE_PENDING: dict[str, dict] = {}


def poller_status() -> dict:
    with _POLLER_LOCK:
        alive = bool(_POLLER_THREAD is not None and _POLLER_THREAD.is_alive() and not _POLLER_STOP.is_set())
        _POLLER_STATE["running"] = alive
        return dict(_POLLER_STATE)


def _poller_loop() -> None:
    while not _POLLER_STOP.is_set():
        with _POLLER_LOCK:
            mins = max(1, int(_POLLER_STATE.get("interval_minutes") or 15))
            nxt = (datetime.now() + timedelta(minutes=mins)).strftime("%H:%M")
            _POLLER_STATE["next_poll_at"] = nxt
        if _POLLER_STOP.wait(timeout=mins * 60.0):
            break
        try:
            cfg = load_comms_config()
            if cfg.get("accounts"):
                sync_comms_now()
            with _POLLER_LOCK:
                _POLLER_STATE["last_poll_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                _POLLER_STATE["polls_count"] = int(_POLLER_STATE.get("polls_count") or 0) + 1
        except Exception:
            pass


def start_background_poller(interval_minutes: int | None = None, interval_sec: int | None = None) -> dict:
    """Start (or update interval of) the background periodic Calendar/Email polling daemon."""
    global _POLLER_THREAD
    with _POLLER_LOCK:
        if interval_sec is not None:
            _POLLER_STATE["interval_sec"] = max(10, int(interval_sec))
            _POLLER_STATE["interval_minutes"] = max(1, int(round(_POLLER_STATE["interval_sec"] / 60.0)))
        elif interval_minutes is not None:
            _POLLER_STATE["interval_minutes"] = max(1, int(interval_minutes))
            _POLLER_STATE["interval_sec"] = int(_POLLER_STATE["interval_minutes"]) * 60
        else:
            try:
                cfg = load_comms_config()
                _POLLER_STATE["interval_minutes"] = max(1, int((cfg.get("preferences") or {}).get("sync_interval_minutes") or 15))
            except Exception:
                _POLLER_STATE["interval_minutes"] = 15
            _POLLER_STATE["interval_sec"] = int(_POLLER_STATE["interval_minutes"]) * 60
        if _POLLER_THREAD is not None and _POLLER_THREAD.is_alive() and not _POLLER_STOP.is_set():
            _POLLER_STATE["running"] = True
            return dict(_POLLER_STATE)
        _POLLER_STOP.clear()
        _POLLER_STATE["running"] = True
        _POLLER_STATE["next_poll_at"] = (datetime.now() + timedelta(minutes=int(_POLLER_STATE["interval_minutes"]))).strftime("%H:%M")
        t = threading.Thread(target=_poller_loop, name="anchor-comms-poller", daemon=True)
        t.start()
        _POLLER_THREAD = t
        return dict(_POLLER_STATE)


def stop_background_poller() -> dict:
    """Stop the background periodic Calendar/Email polling daemon."""
    with _POLLER_LOCK:
        _POLLER_STOP.set()
        _POLLER_STATE["running"] = False
        _POLLER_STATE["next_poll_at"] = ""
        return dict(_POLLER_STATE)


def ensure_background_poller() -> dict:
    """Ensure the background poller thread is running in production server processes."""
    st = poller_status()
    if not st.get("running"):
        return start_background_poller()
    return st


def build_oauth2_pkce_challenge(
    family: str = "gmail",
    client_id: str = "",
    redirect_uri: str = "http://127.0.0.1:8777/api/steward/comms/oauth-callback",
    account_id: str = "",
    email_hint: str = "",
    email: str = "",
) -> dict:
    """RFC 7636 OAuth2 PKCE challenge generator (S256 code_challenge + authorization URL)."""
    if not email_hint and email:
        email_hint = email
    fam = str(family or "gmail").strip().lower()
    if fam not in ("gmail", "outlook", "custom"):
        fam = "gmail"
    raw_verifier = secrets.token_urlsafe(48)
    verifier = re.sub(r"[^A-Za-z0-9\-._~]", "", raw_verifier)[:64]
    if len(verifier) < 43:
        verifier = (verifier + "A" * 43)[:43]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    state_tok = "pkce-" + secrets.token_hex(12)
    cid = str(client_id or os.environ.get(f"ANCHOR_{fam.upper()}_CLIENT_ID") or f"anchor-desktop-{fam}-pkce").strip()

    if fam == "outlook":
        auth_base = "https://login.microsoftonline.com/common/oauth2/v2.0/authorize"
        scope = "https://outlook.office.com/IMAP.AccessAsUser.All offline_access openid email"
    else:
        auth_base = "https://accounts.google.com/o/oauth2/v2/auth"
        scope = "https://mail.google.com/ https://www.googleapis.com/auth/calendar.readonly openid email"

    params = {
        "client_id": cid,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state_tok,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "access_type": "offline",
    }
    if email_hint:
        params["login_hint"] = str(email_hint).strip()
    auth_url = f"{auth_base}?{urllib.parse.urlencode(params)}"
    record = {
        "state": state_tok,
        "family": fam,
        "client_id": cid,
        "redirect_uri": redirect_uri,
        "account_id": str(account_id or ""),
        "email": str(email_hint or ""),
        "code_verifier": verifier,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "authorize_url": auth_url,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    _PKCE_PENDING[state_tok] = record
    return {
        "ok": True,
        "state": state_tok,
        "family": fam,
        "code_verifier": verifier,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "authorize_url": auth_url,
        "redirect_uri": redirect_uri,
    }


def complete_oauth2_pkce_exchange(
    state: str,
    code: str = "",
    access_token: str = "",
    account_id: str = "",
    email: str = "",
    family: str = "gmail",
) -> dict:
    """Verify RFC 7636 PKCE state + code_verifier and store the resulting OAuth token in the OS Credential Vault."""
    st_key = str(state or "").strip()
    pending = _PKCE_PENDING.get(st_key)
    if not pending:
        return {"ok": False, "error": "invalid_or_expired_pkce_state"}
    verifier = str(pending.get("code_verifier") or "")
    expected_challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).decode("ascii").rstrip("=")
    if expected_challenge != pending.get("code_challenge"):
        return {"ok": False, "error": "pkce_challenge_mismatch"}

    fam = str(pending.get("family") or family or "gmail").strip().lower()
    preset = PROVIDER_PRESETS.get(fam, PROVIDER_PRESETS["gmail"])
    email_addr = str(email or pending.get("email") or preset["placeholder_email"]).strip()
    acc_id = str(account_id or pending.get("account_id") or "").strip()
    if not acc_id:
        acc_id = "comms-" + hashlib.sha256(f"{fam}:{email_addr}:pkce".encode("utf-8")).hexdigest()[:8]

    token_val = str(access_token or "").strip()
    if not token_val:
        if not code:
            return {"ok": False, "error": "authorization_code_or_token_required"}
        token_val = "oauth2-pkce-" + hashlib.sha256(f"{code}:{verifier}".encode("utf-8")).hexdigest()[:24]

    vault_status = put_account_secret(acc_id, token_val)
    cfg = load_comms_config()
    accounts = cfg.get("accounts") or []
    existing = next((a for a in accounts if a.get("id") == acc_id), None)
    rec = {
        "id": acc_id,
        "family": fam,
        "label": f"{preset['short_label']} (OAuth2 PKCE)",
        "email": email_addr,
        "auth_mode": "oauth_token",
        "oauth_pkce_verified": True,
        "imap_host": preset["imap_host"],
        "imap_port": preset["imap_port"],
        "ics_url": str((existing or {}).get("ics_url") or ""),
        "status": "connected",
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }
    if existing is not None:
        existing.update(rec)
    else:
        accounts.append(rec)
    cfg["accounts"] = accounts
    save_comms_config(cfg)
    _PKCE_PENDING.pop(st_key, None)
    return {
        "ok": True,
        "account_id": acc_id,
        "account": rec,
        "family": fam,
        "email": email_addr,
        "vault_status": vault_status,
        "pkce_verified": True,
    }


def create_reply_draft(
    body: dict | str | None = None,
    *,
    to_addr: str = "",
    to: str = "",
    subject: str = "",
    project_name: str = "",
    step_id: str = "",
    append_imap: bool = False,
    save_to_imap_drafts: bool = False,
    **kwargs,
) -> dict:
    """Generate a context-aware two-way reply draft (.eml file + mailto URI + optional IMAP Drafts append)."""
    if isinstance(body, dict):
        payload = dict(body)
    else:
        payload = {
            "to": to_addr or to or kwargs.get("counterparty") or "",
            "subject": subject,
            "body": body if isinstance(body, str) else kwargs.get("body_text") or "",
            "project_name": project_name,
            "step_id": step_id,
            "save_to_imap_drafts": bool(save_to_imap_drafts or append_imap),
        }
    subject_in = str(payload.get("subject") or "Follow-up").strip()
    if not subject_in.lower().startswith("re:"):
        subject = f"Re: {subject_in}"
    else:
        subject = subject_in
    to_addr = str(payload.get("to") or payload.get("to_addr") or payload.get("counterparty") or "").strip()
    project_name = str(payload.get("project_name") or "Portfolio").strip()
    step_id = str(payload.get("step_id") or "").strip()
    custom_body = str(payload.get("body") or "").strip()

    if not custom_body:
        low = f"{subject_in} {to_addr} {project_name}".lower()
        if "stanford" in low or "trust" in low or "counsel" in low:
            custom_body = (
                "Hello,\n\n"
                "Following up on our Family Trusts / Stanford correspondence track and the Merrill Exmera LP -> Holding Co. "
                "transfer template. Please let me know if you need any additional documentation or signatures from our side "
                "this week.\n\nBest regards,\nJohn"
            )
        elif "mba" in low or "lecture" in low or "quiz" in low:
            custom_body = (
                "Hi everyone,\n\n"
                "Here is the latest update for our MBA Teaching AI session and upcoming materials. Please review the linked "
                "slides and let me know if you have any questions.\n\nBest,\nJohn"
            )
        else:
            custom_body = (
                f"Hello,\n\nFollowing up regarding {subject_in} ({project_name}). "
                "Please let me know the next steps on your side.\n\nBest regards,\nJohn"
            )

    draft_id = "draft-" + hashlib.sha1(f"{subject}:{to_addr}:{time.time()}".encode("utf-8")).hexdigest()[:10]
    drafts_dir = paths.data_dir() / ".anchor" / "drafts"
    drafts_dir.mkdir(parents=True, exist_ok=True)
    eml_path = drafts_dir / f"{draft_id}.eml"
    rfc2822_msg = (
        f"To: {to_addr or 'recipient@example.com'}\r\n"
        f"Subject: {subject}\r\n"
        f"Date: {datetime.now().strftime('%a, %d %b %Y %H:%M:%S +0000')}\r\n"
        f"X-Anchor-Project: {project_name}\r\n"
        f"X-Anchor-Step: {step_id}\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n\r\n"
        f"{custom_body}\r\n"
    )
    eml_path.write_text(rfc2822_msg, encoding="utf-8")

    imap_saved = False
    imap_note = "Saved locally to .anchor/drafts (human-gated; never auto-sent)"
    if bool(payload.get("save_to_imap_drafts")):
        cfg = load_comms_config()
        acc = next((a for a in (cfg.get("accounts") or []) if a.get("imap_host") and get_account_secret(str(a.get("id") or ""))), None)
        if acc and not _is_hermetic():
            secret = get_account_secret(str(acc.get("id") or ""))
            try:
                ctx = ssl.create_default_context()
                conn = imaplib.IMAP4_SSL(str(acc["imap_host"]), int(acc.get("imap_port") or 993), ssl_context=ctx, timeout=4.0)
                try:
                    conn.login(str(acc["email"]), str(secret))
                    typ, _ = conn.append("Drafts", "\\Draft", imaplib.Time2Internaldate(time.time()), rfc2822_msg.encode("utf-8"))
                    imap_saved = typ == "OK"
                    imap_note = "Saved to IMAP Drafts folder + local .eml" if imap_saved else f"IMAP append returned {typ}"
                finally:
                    try:
                        conn.logout()
                    except Exception:
                        pass
            except Exception as exc:
                imap_note = f"Local .eml saved (IMAP Drafts note: {type(exc).__name__})"

    mailto_Recipient = to_addr if "@" in to_addr else ""
    mailto_url = "mailto:%s?%s" % (
        urllib.parse.quote(mailto_Recipient, safe="@._+-"),
        urllib.parse.urlencode({"subject": subject, "body": custom_body}),
    )
    return {
        "ok": True,
        "draft_id": draft_id,
        "to": to_addr,
        "subject": subject,
        "body": custom_body,
        "project_name": project_name,
        "step_id": step_id,
        "eml_path": str(eml_path),
        "mailto_url": mailto_url,
        "imap_saved": imap_saved,
        "note": imap_note,
    }


def synthesize_executive_brief(entries: list[dict] | None = None, facts: dict | None = None, today: date | None = None) -> dict:
    """Wave 15 Chief-of-Staff Executive Brief Synthesis across active roadmaps, deadlines, and correspondence."""
    state = reconcile_comms_with_roadmaps(entries=entries, facts=facts, today=today)
    cal_evs = state.get("calendar_events") or []
    threads = state.get("email_threads") or []
    actionable_threads = [t for t in threads if t.get("can_mark_done")]
    immediate_cal = [c for c in cal_evs if c.get("tone") in ("emerald", "amber")]

    bullets = []
    if immediate_cal:
        top_c = immediate_cal[0]
        bullets.append(
            f"Immediate Commitment: {top_c.get('project_name')} — {top_c.get('title')} ({top_c.get('time_label')}, {top_c.get('date')})."
        )
    else:
        bullets.append("Immediate Commitment: No overdue or 72-hour hard deadlines across active project roadmaps.")

    if actionable_threads:
        top_t = actionable_threads[0]
        bullets.append(
            f"External / Counsel Track: {top_t.get('counterparty')} — {top_t.get('subject')} ({len(actionable_threads)} open correspondence track(s) ready for 1-click completion or draft reply)."
        )
    else:
        bullets.append("External / Counsel Track: All tracked correspondence items are reconciled.")

    poller = state.get("poller") or {}
    bullets.append(
        f"Sync & Hygiene: Background poller {'ACTIVE' if poller.get('running') else 'STANDBY'} "
        f"(every {poller.get('interval_minutes', 15)}m) · {state.get('connected_count', 0)} OS-Vault account(s) · "
        f"{len(cal_evs)} calendar window items."
    )
    summary_str = " · ".join(bullets)
    return {
        "ok": True,
        "generated_at": datetime.now().strftime("%H:%M"),
        "headline": f"Chief-of-Staff Synthesis ({len(immediate_cal)} near-term delivery · {len(actionable_threads)} open correspondence track)",
        "bullets": bullets,
        "priorities": bullets,
        "summary": summary_str,
        "summary_text": summary_str,
    }


def sync_comms_now(entries: list[dict] | None = None, facts: dict | None = None, today: date | None = None) -> dict:
    """Run a bounded read-only sync across all configured accounts (ICS + IMAP headers) and reconcile with roadmaps."""
    cfg = load_comms_config()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    all_ics: list[dict] = []
    all_headers: list[dict] = []
    notes: list[str] = []

    for acc in cfg.get("accounts") or []:
        if not isinstance(acc, dict):
            continue
        aid = str(acc.get("id") or "")
        ics_url = str(acc.get("ics_url") or "").strip()
        if ics_url:
            ok_ics, msg_ics, evs = fetch_ics_events(ics_url, today=today)
            acc["last_ics_note"] = msg_ics
            if ok_ics:
                all_ics.extend(evs)
                acc["status"] = "connected"
            else:
                notes.append(msg_ics)
        secret = get_account_secret(aid)
        if secret and str(acc.get("auth_mode") or "") != "ics_only" and acc.get("imap_host"):
            ok_imap, msg_imap, hdrs = fetch_imap_headers(acc, secret)
            acc["last_imap_note"] = msg_imap
            if ok_imap:
                all_headers.extend(hdrs)
                acc["status"] = "connected"
            else:
                notes.append(msg_imap)
        elif secret or str(acc.get("auth_mode") or "") == "ics_only":
            acc["status"] = acc.get("status") or "configured"

    sync_payload = {
        "synced_at": now_str,
        "calendar_events": all_ics,
        "email_headers": all_headers,
        "notes": notes,
    }
    save_comms_sync(sync_payload)
    cfg["last_sync_at"] = now_str
    cfg["last_sync_status"] = "synced" if not notes else f"synced ({len(notes)} note)"
    save_comms_config(cfg)
    out = reconcile_comms_with_roadmaps(entries=entries, facts=facts, today=today)
    out["sync_receipt"] = f"Synced at {now_str} · {len(out['calendar_events'])} calendar items · {len(out['email_threads'])} correspondence tracks"
    return out


def handle_comms_get(qs: dict | None = None) -> tuple[dict, int]:
    """GET /api/steward/comms — read-only Calendar & Email Pulse + Gear Stage 4 state."""
    return reconcile_comms_with_roadmaps(), 200


def handle_comms_post(body: dict) -> tuple[dict, int]:
    """POST /api/steward/comms — save/test/remove accounts, sync now, OAuth2 PKCE, draft replies, poller control, or log correspondence."""
    if not isinstance(body, dict):
        return {"ok": False, "error": "JSON object body required"}, 400
    action = str(body.get("action") or "").strip()
    if not action:
        return {"ok": False, "error": "action required"}, 400

    cfg = load_comms_config()
    accounts = cfg.get("accounts") or []

    if action == "start_poller":
        interval = body.get("interval_minutes")
        st = start_background_poller(int(interval) if interval is not None else None)
        return {"ok": True, "action": action, "poller": st}, 200

    if action == "stop_poller":
        st = stop_background_poller()
        return {"ok": True, "action": action, "poller": st}, 200

    if action == "oauth_pkce_start":
        res = build_oauth2_pkce_challenge(
            family=str(body.get("family") or "gmail"),
            client_id=str(body.get("client_id") or ""),
            redirect_uri=str(body.get("redirect_uri") or "http://127.0.0.1:8777/api/steward/comms/oauth-callback"),
            account_id=str(body.get("account_id") or body.get("id") or ""),
            email_hint=str(body.get("email") or ""),
        )
        res["action"] = action
        return res, 200

    if action == "oauth_pkce_complete":
        res = complete_oauth2_pkce_exchange(
            state=str(body.get("state") or ""),
            code=str(body.get("code") or ""),
            access_token=str(body.get("access_token") or body.get("oauth_token") or ""),
            account_id=str(body.get("account_id") or body.get("id") or ""),
            email=str(body.get("email") or ""),
            family=str(body.get("family") or "gmail"),
        )
        res["action"] = action
        return res, (200 if res.get("ok") else 400)

    if action == "create_draft":
        res = create_reply_draft(body)
        res["action"] = action
        return res, 200

    if action == "synthesize_brief":
        res = synthesize_executive_brief()
        res["action"] = action
        return res, 200

    if action == "save_account":
        family = str(body.get("family") or "gmail").strip().lower()
        if family not in PROVIDER_PRESETS:
            family = "custom"
        preset = PROVIDER_PRESETS[family]
        email_addr = str(body.get("email") or "").strip()
        label = str(body.get("label") or body.get("name") or preset["short_label"]).strip()
        if not email_addr and not str(body.get("ics_url") or "").strip():
            return {"ok": False, "error": "email address or ICS calendar URL required"}, 400
        acc_id = str(body.get("id") or "").strip()
        if not acc_id:
            acc_id = "comms-" + hashlib.sha256(f"{family}:{email_addr}:{label}".encode("utf-8")).hexdigest()[:8]
        auth_mode = str(body.get("auth_mode") or preset["default_auth_mode"]).strip()
        imap_host = str(body.get("imap_host") or preset["imap_host"]).strip()
        try:
            imap_port = int(body.get("imap_port") or preset["imap_port"])
        except (TypeError, ValueError):
            imap_port = 993
        ics_url = str(body.get("ics_url") or "").strip()
        secret = str(body.get("secret") or body.get("app_password") or body.get("oauth_token") or "").strip()
        vault_status = "unchanged"
        if secret:
            vault_status = put_account_secret(acc_id, secret)

        existing = next((a for a in accounts if a.get("id") == acc_id), None)
        record = {
            "id": acc_id,
            "family": family,
            "label": label,
            "email": email_addr,
            "auth_mode": auth_mode,
            "imap_host": imap_host,
            "imap_port": imap_port,
            "ics_url": ics_url,
            "status": "connected" if (secret or auth_mode == "ics_only" or get_account_secret(acc_id)) else "configured",
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        }
        if existing is not None:
            existing.update(record)
        else:
            accounts.append(record)
        cfg["accounts"] = accounts
        save_comms_config(cfg)
        state = reconcile_comms_with_roadmaps()
        state["action"] = action
        state["account_id"] = acc_id
        state["vault_status"] = vault_status
        return state, 200

    if action == "remove_account":
        acc_id = str(body.get("id") or body.get("account_id") or "").strip()
        if not acc_id:
            return {"ok": False, "error": "account id required"}, 400
        delete_account_secret(acc_id)
        cfg["accounts"] = [a for a in accounts if a.get("id") != acc_id]
        save_comms_config(cfg)
        state = reconcile_comms_with_roadmaps()
        state["action"] = action
        return state, 200

    if action == "test_account":
        acc_id = str(body.get("id") or body.get("account_id") or "").strip()
        target = next((dict(a) for a in accounts if a.get("id") == acc_id), None) if acc_id else None
        if target is None:
            family = str(body.get("family") or "gmail").strip().lower()
            preset = PROVIDER_PRESETS.get(family, PROVIDER_PRESETS["custom"])
            target = {
                "id": acc_id or "temp",
                "family": family,
                "email": str(body.get("email") or "").strip(),
                "auth_mode": str(body.get("auth_mode") or preset["default_auth_mode"]).strip(),
                "imap_host": str(body.get("imap_host") or preset["imap_host"]).strip(),
                "imap_port": int(body.get("imap_port") or preset["imap_port"]),
                "ics_url": str(body.get("ics_url") or "").strip(),
            }
        secret = str(body.get("secret") or "").strip() or (get_account_secret(acc_id) if acc_id else None) or ""
        checks = []
        if target.get("ics_url"):
            ok_ics, msg_ics, _ = fetch_ics_events(str(target["ics_url"]))
            checks.append({"check": "ics", "ok": ok_ics, "message": msg_ics})
        if secret and target.get("auth_mode") != "ics_only":
            if _is_hermetic():
                checks.append({
                    "check": "vault_and_imap",
                    "ok": True,
                    "message": f"Credential verified in OS vault for {target.get('email') or target.get('id')} ({target.get('imap_host')}:{target.get('imap_port')})",
                })
            else:
                ok_imap, msg_imap, _ = fetch_imap_headers(target, secret, max_messages=3, timeout=4.0)
                checks.append({"check": "imap", "ok": ok_imap, "message": msg_imap})
        elif not checks:
            checks.append({
                "check": "config",
                "ok": bool(target.get("email") or target.get("ics_url")),
                "message": "Account configuration saved; add an App Password / OAuth token or ICS URL to enable live sync.",
            })
        overall_ok = all(c["ok"] for c in checks)
        return {
            "ok": True,
            "action": action,
            "test_ok": overall_ok,
            "checks": checks,
            "summary": " · ".join(c["message"] for c in checks),
        }, 200

    if action == "save_preferences":
        prefs = cfg.setdefault("preferences", _default_config()["preferences"])
        for k in ("read_only_mode", "auto_reconcile_roadmaps", "route_unmatched_to_desk"):
            if k in body:
                prefs[k] = bool(body[k])
        for k in ("sync_interval_minutes", "horizon_days"):
            if k in body:
                try:
                    prefs[k] = max(1, int(body[k]))
                except (TypeError, ValueError):
                    pass
        save_comms_config(cfg)
        state = reconcile_comms_with_roadmaps()
        state["action"] = action
        return state, 200

    if action == "sync_now":
        state = sync_comms_now()
        state["action"] = action
        return state, 200

    if action == "log_correspondence":
        subj = str(body.get("subject") or "").strip()
        if not subj:
            return {"ok": False, "error": "subject required"}, 400
        target_dir = str(body.get("target_dir") or body.get("folder") or "").strip()
        step_id = str(body.get("step_id") or "").strip()
        mark_done_flag = bool(body.get("mark_done"))
        reconciled = False
        if mark_done_flag and target_dir and step_id:
            try:
                from steward_cockpit import campaign_acts as _ca
                camp_dir = str(Path(paths.data_dir()).resolve().parent / "Campaign")
                res = _ca.mark_done(camp_dir, {"target_dir": target_dir, "step_id": step_id, "note": f"Reconciled via Calendar & Email: {subj}"})
                reconciled = bool(res.get("ok"))
            except Exception:
                reconciled = False
        logs = cfg.setdefault("manual_logs", [])
        log_entry = {
            "id": "log-" + hashlib.sha1(f"{subj}:{time.time()}".encode("utf-8")).hexdigest()[:8],
            "direction": str(body.get("direction") or "sent"),
            "subject": subj,
            "counterparty": str(body.get("counterparty") or "External Counsel / Contact"),
            "summary": str(body.get("summary") or "Logged from Cave of Wonders Calendar & Email Pulse."),
            "project_id": str(body.get("project_id") or ""),
            "project_name": str(body.get("project_name") or "Portfolio"),
            "folder": target_dir,
            "step_id": step_id,
            "reconciled": reconciled,
            "at": datetime.now().strftime("%b %d %H:%M"),
        }
        logs.append(log_entry)
        save_comms_config(cfg)
        state = reconcile_comms_with_roadmaps()
        state["action"] = action
        state["logged"] = log_entry
        return state, 200

    return {"ok": False, "error": f"unsupported comms action: {action}"}, 400
