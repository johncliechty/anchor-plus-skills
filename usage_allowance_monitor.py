"""Provider Usage & Allowance Monitor for Anchor Cave of Wonders & Setup.

Combines:
1. Live CLI `rate_limit_event` streams persisted by `steward_engine.py` into
   `<data_dir>/.anchor/rate_limits/<connection_id>.json` and `rnd_jobs/*.log`
   (`usage_capacity.latest_limit_signal`).
2. Local subscription CLI installation & auth verification (`claude`, `agy`/`gemini`,
   `grok`, `codex`) + Anchor ledger 5h / 7d token & turn activity.
3. Optional Chrome DevTools Protocol (CDP `127.0.0.1:9222`) / browser usage-page
   inspection (`claude.ai/settings/usage`, `chatgpt.com/codex/settings/usage`,
   `console.x.ai`, `one.google.com`) when triggered on demand, persisted into
   `<data_dir>/.anchor/rate_limits/browser_usage.json`.

Never runs extra subprocesses inside `ProviderService.snapshot()` so hermetic
provider-setup command-count tests remain untouched.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

import paths as _paths
import usage_capacity as _ucap

USAGE_PAGE_URLS: Dict[str, str] = {
    "claude": "https://claude.ai/settings/usage",
    "chatgpt": "https://chatgpt.com/codex/settings/usage",
    "gemini": "https://aistudio.google.com/app/plan_information",
    "grok": "https://console.x.ai",
}

DEFAULT_FRONTIER_MODELS: Dict[str, str] = {
    "claude": "claude-fable-5-1 · max",
    "chatgpt": "gpt-6.1-sol · ultra",
    "gemini": "gemini-4-argon · high",
    "grok": "grok-4.7 · xhigh",
}


def _fmt_reset_local(epoch_sec: Any) -> Optional[str]:
    if epoch_sec is None:
        return None
    try:
        ts = float(epoch_sec)
        if ts <= 0:
            return None
        dt = datetime.fromtimestamp(ts).astimezone()
        return dt.strftime("%a %b %d %H:%M")
    except Exception:
        return None


def _fmt_tokens_short(n: int) -> str:
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.2f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n:,} ({n / 1_000:.1f}k)"
    return f"{n:,}"


def rate_limits_dir() -> Path:
    d = _paths.data_dir() / ".anchor" / "rate_limits"
    d.mkdir(parents=True, exist_ok=True)
    return d


def record_rate_limit_event(connection_id: str, family: str, rate_limit_info: Dict[str, Any]) -> None:
    """Persist a live `rate_limit_event` from `steward_engine.py` or `provider_setup.py`."""
    if not isinstance(rate_limit_info, dict):
        return
    cid = str(connection_id or f"{family}-default").strip() or "claude-default"
    payload = {
        "connection_id": cid,
        "family": str(family or "claude").lower(),
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "mtime": time.time(),
        "rate_limit_info": rate_limit_info,
    }
    try:
        target = rate_limits_dir() / f"{re.sub(r'[^a-zA-Z0-9_.-]', '_', cid)}.json"
        _paths.atomic_write_text(target, json.dumps(payload, indent=2, ensure_ascii=False))
    except Exception:
        pass


def load_persisted_rate_limit(connection_id: str) -> Optional[Dict[str, Any]]:
    cid = str(connection_id or "").strip()
    if not cid:
        return None
    target = rate_limits_dir() / f"{re.sub(r'[^a-zA-Z0-9_.-]', '_', cid)}.json"
    if not target.is_file():
        return None
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            return None
        return doc
    except Exception:
        return None


def load_browser_usage_cache() -> Dict[str, Any]:
    target = rate_limits_dir() / "browser_usage.json"
    if not target.is_file():
        return {}
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except Exception:
        return {}


def save_browser_usage_cache(data: Dict[str, Any]) -> None:
    try:
        target = rate_limits_dir() / "browser_usage.json"
        _paths.atomic_write_text(target, json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:
        pass


def probe_chrome_cdp_usage(port: int = 9222, timeout: float = 2.0, open_family: Optional[str] = None) -> Dict[str, Any]:
    """Check if Chrome has remote debugging open on `port` or launch/inspect usage tabs."""
    result: Dict[str, Any] = {
        "ok": True,
        "cdp_reachable": False,
        "port": port,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "tabs": [],
        "extracted": {},
    }
    url = f"http://127.0.0.1:{int(port)}/json/list"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            tabs = json.loads(resp.read().decode("utf-8", errors="replace"))
        if isinstance(tabs, list):
            result["cdp_reachable"] = True
            for t in tabs:
                if not isinstance(t, dict):
                    continue
                t_url = str(t.get("url") or "")
                t_title = str(t.get("title") or "")
                t_host = (urllib.parse.urlparse(t_url).hostname or "").lower()
                for fam, u_url in USAGE_PAGE_URLS.items():
                    u_host = (urllib.parse.urlparse(u_url).hostname or "").lower()
                    if t_host == u_host or t_host.endswith("." + u_host):
                        result["tabs"].append({"family": fam, "url": t_url, "title": t_title})
                        m = re.search(r"(\d{1,3})\s*%\s*(?:left|remaining|used)", t_title, re.I)
                        if m:
                            pct = int(m.group(1))
                            if "used" in m.group(0).lower():
                                pct = max(0, 100 - pct)
                            result["extracted"][fam] = {
                                "remaining_percent": max(0, min(100, pct)),
                                "source": "chrome_cdp_tab",
                                "observed_at": result["checked_at"],
                            }
    except Exception as exc:
        result["cdp_error"] = str(exc)

    if open_family and open_family in USAGE_PAGE_URLS:
        target_url = USAGE_PAGE_URLS[open_family]
        result["opened_url"] = target_url
        result["browser_opened"] = False

    if result["extracted"]:
        cached = load_browser_usage_cache()
        cached.update(result["extracted"])
        save_browser_usage_cache(cached)

    return result


def _cli_installed(family: str) -> bool:
    candidates = {
        "claude": ("claude.exe", "claude.cmd", "claude"),
        "gemini": ("agy.cmd", "agy.exe", "agy", "gemini.cmd", "gemini.exe", "gemini"),
        "grok": ("grok.exe", "grok.cmd", "grok"),
        "chatgpt": ("codex.cmd", "codex.exe", "codex"),
    }.get(family, ())
    for c in candidates:
        if shutil.which(c):
            return True
    if family == "gemini":
        local_agy = Path.home() / "AppData" / "Local" / "Programs" / "Antigravity" / "bin" / "agy.cmd"
        if local_agy.exists():
            return True
    return False


def _is_fresh_iso(iso_str: Any, now: datetime, max_age_sec: float = 21600.0) -> bool:
    if not iso_str or not isinstance(iso_str, str):
        return False
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return 0 <= (now - dt).total_seconds() <= max_age_sec
    except Exception:
        return False


def compute_allowance_monitor(usage_summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build per-family connection + allowance status for the Cave left rail and Setup."""
    now = datetime.now(timezone.utc)
    browser_cache = load_browser_usage_cache()
    providers_us = (usage_summary or {}).get("providers") if isinstance(usage_summary, dict) else {}
    windows_us = (usage_summary or {}).get("windows") if isinstance(usage_summary, dict) else {}
    w7_by_fam = ((windows_us or {}).get("7d") or {}).get("by_family") or {}
    w5h_by_fam = ((windows_us or {}).get("5h") or {}).get("by_family") or {}

    try:
        claude_sig = _ucap.latest_limit_signal(now, max_logs=300, connection_id="claude-default")
        if not claude_sig:
            claude_sig = _ucap.latest_limit_signal(now, max_logs=300)
    except Exception:
        claude_sig = None

    chatgpt_persisted = load_persisted_rate_limit("chatgpt-default")

    families_out: Dict[str, Any] = {}
    for fam in ("claude", "gemini", "grok", "chatgpt"):
        installed = _cli_installed(fam)
        fam_7d = w7_by_fam.get(fam) or {}
        fam_5h = w5h_by_fam.get(fam) or {}
        tokens_7d = int(fam_7d.get("total_tokens") or 0)
        tokens_5h = int(fam_5h.get("total_tokens") or 0)
        usd_7d = float(fam_7d.get("hypothetical_usd") or 0.0)
        connected = bool(installed or tokens_7d > 0)

        pct_5h: Optional[int] = None
        pct_7d: Optional[int] = None
        reset_5h: Optional[int] = None
        reset_7d: Optional[int] = None
        basis = "cli_unreported"
        basis_label = "CLI does not publish quota %"

        if fam == "claude" and claude_sig:
            w5 = claude_sig.get("five_hour") or {}
            w7 = claude_sig.get("seven_day") or {}
            if w5.get("utilization") is not None:
                u5 = float(w5["utilization"])
                if not (w5.get("resets_at") and w5["resets_at"] <= now.timestamp()):
                    pct_5h = max(0, min(100, int(round((1.0 - u5) * 100))))
                    reset_5h = w5.get("resets_at")
                else:
                    pct_5h = 100
            if w7.get("utilization") is not None:
                u7 = float(w7["utilization"])
                if not (w7.get("resets_at") and w7["resets_at"] <= now.timestamp()):
                    pct_7d = max(0, min(100, int(round((1.0 - u7) * 100))))
                    reset_7d = w7.get("resets_at")
                else:
                    pct_7d = 100
            if pct_5h is not None or pct_7d is not None:
                basis = "live_rate_limit_event"
                basis_label = "Live Claude CLI window signal"

        if fam == "chatgpt" and isinstance(chatgpt_persisted, dict):
            rli = chatgpt_persisted.get("rate_limit_info") or {}
            allow = rli.get("allowance") if isinstance(rli.get("allowance"), dict) else rli
            wins = allow.get("windows") if isinstance(allow, dict) else []
            if isinstance(wins, list) and wins:
                for w in wins:
                    if not isinstance(w, dict):
                        continue
                    rem = w.get("remaining_percent")
                    res_at = w.get("resets_at")
                    w_min = int(w.get("window_minutes") or 10080)
                    if rem is None:
                        continue
                    if res_at and float(res_at) <= now.timestamp():
                        pct_val = 100
                        res_val = None
                    else:
                        pct_val = max(0, min(100, int(round(float(rem)))))
                        res_val = int(res_at) if res_at else None
                    if w_min <= 360:
                        pct_5h = pct_val
                        reset_5h = res_val
                    else:
                        pct_7d = pct_val
                        reset_7d = res_val
                if pct_5h is not None or pct_7d is not None:
                    basis = "live_codex_rate_limits"
                    basis_label = "Live Codex CLI rateLimits/read"

        b_entry = browser_cache.get(fam)
        if (
            isinstance(b_entry, dict)
            and b_entry.get("remaining_percent") is not None
            and _is_fresh_iso(b_entry.get("observed_at"), now)
            and basis not in ("live_rate_limit_event", "live_codex_rate_limits")
        ):
            pct_7d = int(b_entry["remaining_percent"])
            basis = "browser_usage_page"
            basis_label = "Browser usage page"

        primary_pct = pct_5h if pct_5h is not None else pct_7d
        reset_5h_text = _fmt_reset_local(reset_5h)
        reset_7d_text = _fmt_reset_local(reset_7d)
        primary_reset_text = reset_5h_text or reset_7d_text

        if pct_5h is not None and pct_7d is not None:
            summary_line = (
                f"5h: {pct_5h}% left" + (f" (resets {reset_5h_text})" if reset_5h_text else "")
                + f" · 7d: {pct_7d}% left" + (f" (resets {reset_7d_text})" if reset_7d_text else "")
            )
            short_allowance = f"5h {pct_5h}% · 7d {pct_7d}% left"
        elif pct_7d is not None:
            summary_line = f"7d: {pct_7d}% left" + (f" · resets {reset_7d_text}" if reset_7d_text else "")
            short_allowance = f"7d: {pct_7d}% left"
        elif pct_5h is not None:
            summary_line = f"5h: {pct_5h}% left" + (f" · resets {reset_5h_text}" if reset_5h_text else "")
            short_allowance = f"5h: {pct_5h}% left"
        elif tokens_7d > 0:
            summary_line = f"7d: {_fmt_tokens_short(tokens_7d)} tok (~${usd_7d:,.2f}) · CLI quota % not published"
            short_allowance = f"7d: {_fmt_tokens_short(tokens_7d)} tok"
        else:
            summary_line = "CLI Ready · 0 tok (7d) · quota % not published"
            short_allowance = "CLI Ready"

        p_info = (providers_us or {}).get(fam) or {}
        models_list = p_info.get("models") or []
        top_recorded = models_list[0].get("model") if models_list and isinstance(models_list[0], dict) else None
        frontier_display = DEFAULT_FRONTIER_MODELS.get(fam, "latest_supported")

        families_out[fam] = {
            "family": fam,
            "connected": connected,
            "cli_installed": installed,
            "mode": "Sub",
            "frontier_model": frontier_display,
            "top_recorded_model": top_recorded,
            "remaining_percent": primary_pct,
            "pct_5h": pct_5h,
            "pct_7d": pct_7d,
            "reset_5h": reset_5h,
            "reset_7d": reset_7d,
            "reset_5h_text": reset_5h_text,
            "reset_7d_text": reset_7d_text,
            "primary_reset_text": primary_reset_text,
            "summary_line": summary_line,
            "short_allowance": short_allowance,
            "basis": basis,
            "basis_label": basis_label,
            "tokens_5h": tokens_5h,
            "tokens_7d": tokens_7d,
            "hypothetical_usd_7d": round(usd_7d, 2),
            "usage_url": USAGE_PAGE_URLS.get(fam, ""),
        }

    auto_meta = _read_auto_refresh_meta()
    return {
        "ok": True,
        "as_of": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "families": families_out,
        "usage_urls": USAGE_PAGE_URLS,
        "auto_refresh": auto_meta,
    }


_NIGHTLY_SCHEDULER_LOCK = None
_NIGHTLY_SCHEDULER_STARTED = False


def _auto_refresh_meta_file() -> Path:
    return _paths.data_dir() / ".anchor" / "rate_limits" / "nightly_refresh_state.json"


def _allowance_interval_sec() -> int:
    try:
        val = int(os.environ.get("ANCHOR_ALLOWANCE_REFRESH_SEC", "900"))
        return max(60, min(86400, val))
    except (ValueError, TypeError):
        return 900


def _read_auto_refresh_meta() -> Dict[str, Any]:
    p = _auto_refresh_meta_file()
    data: Dict[str, Any] = {}
    if p.is_file():
        try:
            raw = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            if isinstance(raw, dict):
                data = raw
        except Exception:
            pass
    interval_min = max(1, _allowance_interval_sec() // 60)
    last_at = data.get("last_refresh_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "enabled": True,
        "allowance_interval_minutes": interval_min,
        "models_schedule": "Nightly 02:00 local",
        "schedule": f"Allowance: every {interval_min}m · Models: Nightly (02:00 local)",
        "last_refresh_at": last_at,
        "last_refresh_local": data.get("last_refresh_local") or datetime.now().astimezone().strftime("%a %b %d %H:%M"),
        "last_model_check_day": data.get("last_model_check_day") or datetime.now().astimezone().strftime("%Y-%m-%d"),
        "next_refresh_text": f"Every {interval_min}m (workday) · Models Nightly 02:00",
    }


def run_nightly_allowance_refresh(force: bool = False) -> Dict[str, Any]:
    """Run a workday 15-minute subscription allowance refresh + Nightly 02:00 model frontier check."""
    meta_file = _auto_refresh_meta_file()
    now_utc = datetime.now(timezone.utc)
    now_local = datetime.now().astimezone()
    today_str = now_local.strftime("%Y-%m-%d")
    interval_sec = _allowance_interval_sec()
    interval_min = max(1, interval_sec // 60)
    prev: Dict[str, Any] = {}

    if meta_file.is_file():
        try:
            loaded = json.loads(meta_file.read_text(encoding="utf-8", errors="replace"))
            if isinstance(loaded, dict):
                prev = loaded
        except Exception:
            prev = {}

    last_epoch = float(prev.get("last_refresh_epoch") or 0)
    last_model_day = str(prev.get("last_model_check_day") or prev.get("last_refresh_day") or "")
    is_stale_allowance = (now_utc.timestamp() - last_epoch) >= interval_sec
    is_new_night = (last_model_day != today_str and now_local.hour >= 2)

    if not force and meta_file.is_file() and not is_stale_allowance and not is_new_night:
        return compute_allowance_monitor()

    try:
        import provider_setup as _ps
        _ps.SERVICE.snapshot(refresh=True)
    except Exception:
        pass

    try:
        refresh_browser_usage_via_cdp(open_tabs=False)
    except Exception:
        pass

    state_payload = {
        "last_refresh_at": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "last_refresh_epoch": int(now_utc.timestamp()),
        "last_refresh_day": today_str,
        "last_model_check_day": today_str if (is_new_night or not last_model_day or force) else last_model_day,
        "last_refresh_local": now_local.strftime("%a %b %d %H:%M"),
        "allowance_interval_minutes": interval_min,
        "models_schedule": "Nightly 02:00 local",
        "schedule": f"Allowance: every {interval_min}m · Models: Nightly (02:00 local)",
    }
    try:
        meta_file.parent.mkdir(parents=True, exist_ok=True)
        meta_file.write_text(json.dumps(state_payload, indent=2), encoding="utf-8")
    except Exception:
        pass

    try:
        from steward_cockpit import steward_routes as _sr
        with _sr._GLOBAL_USAGE_LOCK:
            _sr._GLOBAL_USAGE_CACHE.clear()
    except Exception:
        pass

    return compute_allowance_monitor()


run_allowance_refresh = run_nightly_allowance_refresh


def ensure_nightly_allowance_scheduler() -> bool:
    """Start the background daemon thread that refreshes subscription allowances every 15m and models nightly at 02:00."""
    global _NIGHTLY_SCHEDULER_STARTED, _NIGHTLY_SCHEDULER_LOCK
    import threading
    if _NIGHTLY_SCHEDULER_LOCK is None:
        _NIGHTLY_SCHEDULER_LOCK = threading.Lock()
    with _NIGHTLY_SCHEDULER_LOCK:
        if _NIGHTLY_SCHEDULER_STARTED:
            return False
        _NIGHTLY_SCHEDULER_STARTED = True

    def _loop() -> None:
        time.sleep(3.0)
        while True:
            try:
                run_nightly_allowance_refresh(force=False)
            except Exception:
                pass
            time.sleep(float(_allowance_interval_sec()))

    t = threading.Thread(target=_loop, name="anchor-allowance-15m-refresh", daemon=True)
    t.start()
    return True


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Anchor Provider Usage & Allowance Monitor")
    parser.add_argument("--refresh-now", action="store_true", help="Force an immediate CLI + allowance refresh")
    args = parser.parse_args()
    out = run_nightly_allowance_refresh(force=True) if args.refresh_now else compute_allowance_monitor()
    print(json.dumps(out, indent=2))

