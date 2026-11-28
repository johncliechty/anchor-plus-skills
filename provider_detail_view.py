"""Single-Provider Detail, Mothership Subscription Auto-Discovery & Usage View.
Stdlib-only backend: 0 subprocesses on GET, bounded 2.0s NativeProviders.observe on POST.
"""
from __future__ import annotations
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json, os, re, subprocess, threading
from pathlib import Path
import anchor_settings, paths, provider_native as native, provider_secrets, provider_settings as metadata
import usage_allowance_monitor as allowance_mon, usage_index

FAMILIES = metadata.FAMILIES
MAX_POST_BODY_BYTES, PROBE_TIMEOUT_S = 32 * 1024, 2.0
STATE_FILENAME, LOCK_FILENAME = "provider_detail_state.json", "provider_detail_state.lock"
FAMILY_META = {
    "claude": ("Claude (Anthropic)", "claude-code", "claude-fable-5-2 · max", "Primary Coding & Steward Seat"),
    "gemini": ("Gemini (Google Antigravity / agy)", "agy CLI", "gemini-4-hydrogen · high", "Cross-Family Adversarial Reviewer & Heavy Reader"),
    "chatgpt": ("ChatGPT / Codex (OpenAI)", "codex CLI", "gpt-6-luna · ultra", "Synthesis & Secondary Shark Seat"),
    "grok": ("Grok (xAI)", "grok CLI", "grok-4.7 · xhigh", "Independent 3rd-Family Shark & Refuter"),
}
FAILURE_STATES = {
    "dependency-missing": (503, "DEPENDENCY_MISSING", False, "Native subscription CLI is not installed on this mother ship."),
    "dependency-slow-or-killed": (504, "TIMEOUT", False, "Mothership CLI status probe timed out (>2.0s) and was terminated; existing setup retained."),
    "dependency-returns-garbage": (502, "REJECTED_GARBAGE", False, "Mothership CLI returned malformed status output — rejected fail-closed."),
    "backing-store-unreadable": (500, "UNKNOWN", True, "Provider detail backing store is unreadable (unknown state, not empty)."),
    "empty-but-valid": (200, "EMPTY", False, "Provider store parsed cleanly with 0 configured provider connections."),
}
_WIN_USER_RE = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"']+", re.IGNORECASE)
_POSIX_USER_RE = re.compile(r"/(?:Users|home)/[^/\s\"']+")
_CACHE_LOCK = threading.Lock()
_DETAIL_CACHE, _USAGE_CACHE = {}, {}


def failure_payload(kind: str, *, family: str | None = None) -> tuple[dict, int]:
    code, badge, unknown_st, msg = FAILURE_STATES[kind]
    out = {"ok": code == 200, "status_kind": kind, "badge": badge, "unknown_state": unknown_st, "message": msg, "error": None if code == 200 else msg}
    if family: out["family"] = family
    return out, code


def redact_home_path(raw_path: str | None) -> str | None:
    if not raw_path or not isinstance(raw_path, str) or not raw_path.strip(): return None
    val = raw_path.strip()
    try:
        home_s = str(Path.home())
        if home_s and len(home_s) > 3 and val.lower().startswith(home_s.lower()):
            tail = val[len(home_s):].lstrip("\\/").replace("\\", "/")
            return f"~/{tail}" if tail else "~"
    except Exception:
        pass
    return _POSIX_USER_RE.sub("~", _WIN_USER_RE.sub("~", val)).replace("\\", "/")


def mask_vault_secret(secret: str | None) -> str | None:
    if not isinstance(secret, str) or not secret.strip(): return None
    s = secret.strip()
    return ("••••••" + s[-4:]) if len(s) >= 8 else "••••••"


def validate_family(raw_family) -> str:
    if not isinstance(raw_family, str): raise ValueError("Invalid provider family")
    fam = raw_family.strip().lower()
    if not fam or "\x00" in fam or ".." in fam or "/" in fam or "\\" in fam or fam not in FAMILIES:
        raise ValueError("Invalid provider family; expected claude, gemini, chatgpt, or grok")
    return fam


def resolve_contained_anchor_file(filename: str, *, base_dir: Path | None = None) -> Path:
    if not isinstance(filename, str) or not filename or "\x00" in filename or Path(filename).is_absolute() or ".." in filename or "/" in filename or "\\" in filename:
        raise ValueError("Blocked unsafe state path")
    anchor_dir = (Path(base_dir).resolve() if base_dir else paths.data_dir().resolve()) / ".anchor"
    candidate = anchor_dir / filename
    if (anchor_dir.exists() and anchor_dir.is_symlink()) or (candidate.exists() and candidate.is_symlink()):
        raise ValueError("Blocked symlink state path")
    if not candidate.resolve().is_relative_to(anchor_dir.resolve()):
        raise ValueError("Blocked path escape outside .anchor")
    return candidate


def _stat_sig(p: Path) -> tuple[int, int]:
    try:
        st = p.stat(); return (st.st_mtime_ns, st.st_size)
    except OSError:
        return (0, 0)


def _read_detail_store() -> dict:
    p = resolve_contained_anchor_file(STATE_FILENAME)
    if not p.exists(): return {"families": {}}
    if p.is_dir(): raise OSError("provider_detail_state.json is a directory")
    raw = p.read_bytes()
    if b"\x00" in raw: raise ValueError("NUL bytes in provider_detail_state.json")
    doc = json.loads(raw.decode("utf-8"))
    if not isinstance(doc, dict) or not isinstance(doc.get("families", {}), dict):
        raise ValueError("Invalid provider_detail_state root")
    return doc


def _update_detail_store(family: str, patch: dict) -> dict:
    p, lp = resolve_contained_anchor_file(STATE_FILENAME), resolve_contained_anchor_file(LOCK_FILENAME)
    p.parent.mkdir(parents=True, exist_ok=True)
    with paths.WRITE_LOCK, paths.cross_process_lock(lp, timeout_sec=5.0):
        doc = _read_detail_store() if p.exists() else {"version": 1, "families": {}}
        fams = dict(doc.get("families") or {})
        cur = {**(fams.get(family) or {}), **patch, "updated_at": datetime.now(timezone.utc).isoformat()}
        fams[family] = cur
        paths.atomic_write_text(p, json.dumps({"version": 1, "families": fams}, indent=2, ensure_ascii=False) + "\n")
        return cur


def _family_usage_attribution(family: str) -> dict:
    root, idx_dir, idx_files = paths.data_dir(), usage_index.index_dir(), []
    if idx_dir.is_dir():
        try:
            with os.scandir(idx_dir) as it:
                for e in it:
                    if e.name.endswith(".jsonl") and not e.name.endswith(".quarantine.jsonl"):
                        st = e.stat(); idx_files.append((e.name[:-6], st.st_mtime_ns, st.st_size))
        except OSError:
            pass
    cache_key = (str(root), family, tuple(sorted(idx_files)), _stat_sig(root / ".anchor" / "usage_ledger"))
    with _CACHE_LOCK:
        if cache_key in _USAGE_CACHE: return deepcopy(_USAGE_CACHE[cache_key])
    now = datetime.now(timezone.utc)
    cut7, cut30 = (now - timedelta(days=7)).isoformat(), (now - timedelta(days=30)).isoformat()
    per_mtok = {"claude": 12.0, "chatgpt": 10.0, "gemini": 3.5, "grok": 8.0}.get(family, 8.0)
    tok7 = tok30 = 0; usd7 = usd30 = 0.0; by_proj, proj_names = {}, {}
    try:
        import rnd_registry
        proj_names = {str(p["id"]): str(p.get("name") or p["id"]) for p in (rnd_registry.list_projects() or []) if isinstance(p, dict) and p.get("id")}
    except Exception:
        pass
    for pid, _, _ in idx_files:
        for r in usage_index.load_rows(pid):
            if not isinstance(r, dict) or str(r.get("cli") or r.get("family") or "").strip().lower() != family: continue
            t = max(0, int(r.get("tokens") or 0))
            if t <= 0: continue
            c = float(r["cost_usd"]) if isinstance(r.get("cost_usd"), (int, float)) and not isinstance(r.get("cost_usd"), bool) and r["cost_usd"] > 0 else (t / 1_000_000.0) * per_mtok
            at = str(r.get("recorded_at") or "")
            if not at or at >= cut30: tok30 += t; usd30 += c
            if not at or at >= cut7: tok7 += t; usd7 += c; by_proj[pid] = by_proj.get(pid, 0) + t
    top = [{"project_id": pid, "name": proj_names.get(pid, pid), "tokens_7d": ptok, "share_pct": int(round((ptok / tok7) * 100)) if tok7 else 0}
           for pid, ptok in sorted(by_proj.items(), key=lambda kv: kv[1], reverse=True)[:3]]
    fmt_tok = allowance_mon._fmt_tokens_short
    out = {
        "window_7d": {"tokens": tok7, "hypothetical_usd": round(usd7, 2), "display": f"{fmt_tok(tok7)} tokens (~${usd7:,.2f} API-equiv)"},
        "window_30d": {"tokens": tok30, "hypothetical_usd": round(usd30, 2), "display": f"{fmt_tok(tok30)} tokens (~${usd30:,.2f} API-equiv)"},
        "top_cockpits": top, "top_cockpits_text": " · ".join(f"{x['name']} ({x['share_pct']}%)" for x in top) if top else "No recorded cockpit turns in last 7d",
    }
    with _CACHE_LOCK:
        if len(_USAGE_CACHE) > 64: _USAGE_CACHE.clear()
        _USAGE_CACHE[cache_key] = deepcopy(out)
    return out


def _vault_status(family: str, connections: list[dict], is_local: bool) -> dict:
    avail = bool(provider_secrets.available())
    api_conn = next((c for c in connections if c.get("family") == family and c.get("mode") == "api"), None)
    secret, matched_id = None, (api_conn["id"] if api_conn else f"{family}-api")
    if avail:
        for cid in dict.fromkeys([f"{family}-api", f"{family}-default"] + ([api_conn["id"]] if api_conn else [])):
            val = provider_secrets.get(cid)
            if val: secret, matched_id = val, cid; break
    masked = mask_vault_secret(secret)
    return {"available": avail, "client_can_enter_api": bool(is_local), "has_api_key": masked is not None, "masked_key": masked,
            "target_id": matched_id, "api_connection_id": api_conn["id"] if api_conn else None,
            "status_text": f"Stored in OS Credential Vault ({masked})" if masked else f"No {FAMILY_META[family][0].split()[0]} API key in OS Credential Vault"}


def _allowance_summary(family: str, obs: dict) -> dict:
    pct_5h = pct_7d = rst_5h = rst_7d = None
    wins = list((obs.get("allowance") or {}).get("windows") or [])
    for w in wins:
        if isinstance(w, dict) and native.finite(w.get("remaining_percent"), 0, 100):
            rem = int(round(float(w["remaining_percent"])))
            if int(w.get("window_minutes") or 10080) <= 360 and pct_5h is None: pct_5h, rst_5h = rem, w.get("resets_at")
            elif pct_7d is None: pct_7d, rst_7d = rem, w.get("resets_at")
    if pct_5h is None and pct_7d is None:
        mon = (allowance_mon.compute_allowance_monitor() or {}).get("families", {}).get(family) or {}
        pct_5h, pct_7d, rst_5h, rst_7d = mon.get("pct_5h"), mon.get("pct_7d"), mon.get("reset_5h"), mon.get("reset_7d")
    fmt_r = allowance_mon._fmt_reset_local
    return {"state": str((obs.get("allowance") or {}).get("state") or "unknown"), "source": str((obs.get("allowance") or {}).get("source") or "Native subscription interface"),
            "window_5h": {"remaining_percent": pct_5h, "resets_at": rst_5h, "reset_text": fmt_r(rst_5h) or "Not published by CLI"},
            "window_7d": {"remaining_percent": pct_7d, "resets_at": rst_7d, "reset_text": fmt_r(rst_7d) or "Not published by CLI"}, "windows": wins}


def get_provider_detail(service, raw_family, *, is_local: bool = True) -> tuple[dict, int]:
    try: family = validate_family(raw_family)
    except ValueError as exc: return {"ok": False, "status_kind": "invalid-family", "error": str(exc)}, 400
    spath = anchor_settings.settings_path()
    if spath.exists():
        try:
            if spath.is_dir(): raise OSError("settings dir")
            raw_s = json.loads(spath.read_text(encoding="utf-8"))
            if not isinstance(raw_s, dict): raise ValueError("settings root")
            if isinstance(raw_s.get("provider_connections"), list) and len(raw_s["provider_connections"]) == 0:
                return failure_payload("empty-but-valid", family=family)
        except (OSError, ValueError):
            return failure_payload("backing-store-unreadable", family=family)
    st_state = anchor_settings.read_settings_state()
    if not st_state["valid"] and not st_state["missing"]: return failure_payload("backing-store-unreadable", family=family)
    try: detail_doc = _read_detail_store()
    except (OSError, ValueError): return failure_payload("backing-store-unreadable", family=family)

    dpath, rl_dir = resolve_contained_anchor_file(STATE_FILENAME), allowance_mon.rate_limits_dir()
    with service.lock:
        svc_obs = deepcopy(service.observations.get(service._key(f"{family}-default")))
        svc_cap = deepcopy((service.capabilities.get(service._key(family)) or {}).get("value") or {})
        svc_cat = deepcopy(service.catalogs.get(service._key(f"{family}-default")) or {})
    sig = (str(paths.data_dir()), family, _stat_sig(spath), _stat_sig(dpath), _stat_sig(rl_dir / f"{family}-default.json"), _stat_sig(rl_dir / "browser_usage.json"), (svc_obs or {}).get("observed_at"))
    with _CACHE_LOCK: cached = deepcopy(_DETAIL_CACHE.get(sig)) if sig in _DETAIL_CACHE else None

    settings = st_state["settings"]
    connections = settings.get("provider_connections") or []
    if cached is None:
        fname, cli_lbl, def_mod, role_hint = FAMILY_META[family]
        saved_fam = (detail_doc.get("families") or {}).get(family) or {}
        obs = svc_obs or (saved_fam.get("mothership") if isinstance(saved_fam.get("mothership"), dict) else None) or {
            "auth": "unknown", "test": "not_tested", "auth_source": "Native CLI status", "observed_at": None, "account_identity": None,
            "allowance": {"state": "unknown", "source": "Native subscription interface", "windows": []}}
        exe_raw = native.executable(family)
        installed, exe_red, ver = bool(exe_raw), redact_home_path(exe_raw), svc_cap.get("version")
        cli_disp = f"{cli_lbl}" + (f" v{ver}" if ver else "") + (f" ({exe_red})" if exe_red else " (not installed)")
        sel_acct = (settings.get("provider_preferences") or {}).get("accounts", {}).get(family) or f"{family}-default"
        auth = str(obs.get("auth") or "unknown")
        adopted = bool(saved_fam.get("adopted") or (sel_acct == f"{family}-default" and auth == "signed_in"))
        raw_id = obs.get("account_identity")
        ident = native.masked_identity(raw_id) or (raw_id if isinstance(raw_id, str) and "***@" in raw_id else None)
        scan_msg = ("Google Ultra via agy CLI installed — passive auth status is unknown without running a billable turn." if (family == "gemini" and installed) else
                    f"Signed-in {fname} subscription verified via native CLI" + (f" ({ident})" if ident else "") if auth == "signed_in" else
                    f"{cli_lbl} is not installed on this mother ship" if not installed else f"Native status: {auth.replace('_', ' ')} — click Use Signed-In Subscription or Test Live Connection to probe")
        coding_fam, review_fam = settings.get("coding_family") or settings.get("default_cli"), settings.get("review_family")
        role_lbl = "Coding & Steward Seat" if family == coding_fam else ("Adversarial Reviewer Seat" if family == review_fam else role_hint)
        cat_sel = svc_cat.get("selection") or {}
        model_lbl = f"{cat_sel['model']} · {cat_sel.get('effort', 'high')}" if cat_sel.get("model") else def_mod
        usage_attr = _family_usage_attribution(family)
        usage_attr["anchor_observed_tokens"] = usage_attr["window_30d"]["tokens"]
        warn = not (auth == "signed_in" or (family == "gemini" and installed))
        cached = {
            "ok": True, "status_kind": "ok", "badge": "READY" if not warn else "ATTENTION", "unknown_state": False,
            "family": family, "name": fname, "warn": warn, "passive_auth_unknown": family == "gemini" and auth == "unknown",
            "billing_mode": "api_key" if saved_fam.get("billing_mode") == "api_key" else "subscription",
            "status": "Connected · Google Ultra via agy (passive auth unknown)" if (family == "gemini" and installed) else "Connected · Native Subscription" if auth == "signed_in" else "CLI Not Installed on Mothership" if not installed else f"Needs Sign-In or Adoption ({auth.replace('_', ' ')})",
            "subscription": {
                "connection_id": f"{family}-default", "native_default": True, "auth": auth, "account_identity": ident,
                "sub_account_text": f"Signed in on Mothership ({ident})" if (auth == "signed_in" and ident) else "Signed in on Mothership" if auth == "signed_in" else "Google Ultra via agy CLI (passive auth status unknown; zero turns billed)" if (family == "gemini" and installed) else f"Status: {auth.replace('_', ' ')}",
                "cli": {"installed": installed, "path": exe_red, "version": ver, "display": cli_disp},
                "mothership_scan": {"state": auth, "found": bool(auth == "signed_in" or (family == "gemini" and installed)), "adoptable": bool(installed and auth in ("signed_in", "unknown")), "adopted": adopted, "observed_at": obs.get("observed_at"), "summary": scan_msg},
                "role": {"label": role_lbl, "model": model_lbl, "is_coding": family == coding_fam, "is_review": family == review_fam},
            },
            "allowance": _allowance_summary(family, obs), "usage": usage_attr,
        }
        with _CACHE_LOCK:
            if len(_DETAIL_CACHE) > 64: _DETAIL_CACHE.clear()
            _DETAIL_CACHE[sig] = deepcopy(cached)

    vault = _vault_status(family, connections, is_local)
    if cached["billing_mode"] == "api_key" and vault["has_api_key"]: cached["status"] = "API Key Billing Selected · OS Credential Vault"
    elif cached["subscription"]["auth"] == "signed_in" and vault["has_api_key"]: cached["status"] = "Connected · Native Subscription + Vault API Backup"
    cached["vault"], cached["settings_revision"] = vault, settings.get("settings_revision", 0)
    return cached, 200


def _observe_mothership(backend, connection: dict, *, timeout: float = PROBE_TIMEOUT_S) -> dict:
    try: return backend.observe(connection, timeout=timeout)
    except TypeError: return backend.observe(connection)


def handle_detail_post(service, path: str, body: dict, *, is_local: bool = True, raw_len: int = 0) -> tuple[dict, int]:
    if raw_len > MAX_POST_BODY_BYTES or len(json.dumps(body or {})) > MAX_POST_BODY_BYTES:
        return {"ok": False, "status_kind": "payload-too-large", "error": "Provider detail payload exceeds 32 KB limit"}, 413
    if not isinstance(body, dict): return {"ok": False, "error": "Invalid JSON object payload"}, 400
    action = str(body.get("detail_action") or "").strip().lower()
    act = ("probe" if (path.endswith("/probe-mothership") or action == "probe_mothership") else "adopt" if (path.endswith("/adopt-mothership") or action == "adopt_mothership") else "billing" if (path.endswith("/billing-mode") or action in ("billing_mode", "save_api_key")) else None)
    if not act: return {"ok": False, "error": "Unknown provider detail action"}, 400
    try: family = validate_family(body.get("family"))
    except ValueError as exc: return {"ok": False, "status_kind": "invalid-family", "error": str(exc)}, 400

    if act in ("probe", "adopt"):
        conn = metadata.find_connection(anchor_settings.load_settings(), f"{family}-default")
        try: obs = _observe_mothership(service.native, conn, timeout=PROBE_TIMEOUT_S)
        except subprocess.TimeoutExpired: return failure_payload("dependency-slow-or-killed", family=family)
        except FileNotFoundError: return failure_payload("dependency-missing", family=family)
        except native.NativeError as exc:
            return failure_payload("dependency-missing" if exc.state == "unavailable" else "dependency-slow-or-killed" if exc.state == "timeout" else "dependency-returns-garbage", family=family)
        except (ValueError, OSError, RuntimeError): return failure_payload("dependency-returns-garbage", family=family)

        now = datetime.now(timezone.utc).isoformat()
        raw_id = obs.get("account_identity")
        safe_id = native.masked_identity(raw_id) or (raw_id if isinstance(raw_id, str) and "***@" in raw_id else None)
        clean_obs = {
            "auth": str(obs.get("auth") or "unknown"), "test": str(obs.get("test") or "not_tested"),
            "auth_source": str(obs.get("auth_source") or "Native CLI status"), "observed_at": now, "account_identity": safe_id,
            "allowance": deepcopy(obs.get("allowance") or {"state": "unknown", "source": "Native CLI", "windows": []}),
            "provider_usage": deepcopy(obs.get("provider_usage") or {"state": "unknown", "source": "Native CLI", "tokens": None}),
        }
        with service.lock: service.observations[service._key(conn["id"])] = deepcopy(clean_obs)
        if act == "adopt":
            if clean_obs["auth"] != "signed_in" and not (family == "gemini" and clean_obs["auth"] == "unknown" and native.executable("gemini")):
                return {"ok": False, "family": family, "error": f"Mothership CLI is not signed in ({clean_obs['auth']}); sign in first before adopting"}, 400
            launch_st = anchor_settings.get_launch_settings() if anchor_settings.read_settings_state()["valid"] else anchor_settings.save_settings(steward_type="aladdin")
            prefs = deepcopy(launch_st["provider_preferences"]); prefs["accounts"][family] = f"{family}-default"
            anchor_settings.save_settings(provider_preferences=prefs, expected_revision=launch_st["settings_revision"])
            _update_detail_store(family, {"mothership": clean_obs, "adopted": True, "adopted_at": now, "billing_mode": "subscription"})
        else:
            _update_detail_store(family, {"mothership": clean_obs})
        detail, code = get_provider_detail(service, family, is_local=is_local)
        detail["probe"] = {"auth": clean_obs["auth"], "account_identity": safe_id, "observed_at": now, "adopted": act == "adopt"}
        return detail, code

    raw_mode = "api_key" if str(body.get("billing_mode") or "subscription").strip().lower() == "api" else str(body.get("billing_mode") or "subscription").strip().lower()
    if raw_mode not in ("subscription", "api_key"): return {"ok": False, "error": "billing_mode must be 'subscription' or 'api_key'"}, 400
    secret = body.get("api_key")
    if secret is not None and str(secret).strip():
        if not is_local: return {"ok": False, "error": "Enter API credentials in Setup on the mother ship itself"}, 403
        if not provider_secrets.available(): return {"ok": False, "error": "Secure OS API credential storage is unavailable"}, 400
        import provider_setup as _ps
        try: _ps.validate_api(family, str(secret).strip()); provider_secrets.put(f"{family}-api", str(secret).strip())
        except ValueError as exc: return {"ok": False, "error": str(exc)}, 400
    if raw_mode == "api_key" and not _vault_status(family, anchor_settings.load_settings().get("provider_connections") or [], is_local)["has_api_key"]:
        return {"ok": False, "error": "Save a valid API key to the OS Credential Vault before selecting API Key Billing"}, 400
    _update_detail_store(family, {"billing_mode": raw_mode})
    return get_provider_detail(service, family, is_local=is_local)
