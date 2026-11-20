"""Shared Setup/Cave provider service and small normally authenticated routes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import socket
import threading
import time
import uuid
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError, URLError

import anchor_settings
import model_policy
import paths
import provider_native as native
import provider_secrets
import provider_settings as metadata

TTL = 300


def stamp():
    return datetime.now(timezone.utc).isoformat()


def unknown(source, state="unknown"):
    return {"state": state, "source": source, "observed_at": None, "attempted_at": None}


def empty_observation():
    return {"auth": "unknown", "test": "not_tested", "auth_source": "Native CLI status", "observed_at": None,
            "account_identity": None,
            "allowance": {**unknown("Native subscription interface"), "windows": []},
            "provider_usage": {**unknown("Native account usage"), "tokens": None}}


def carries_figures(metric, report):
    """Whether a metric report holds figures worth retaining across a failure."""
    return bool(report.get("windows")) if metric == "allowance" else report.get("tokens") is not None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def validate_api(family, secret):
    """GET the documented public model catalog. Never submit model work."""
    if not isinstance(secret, str) or not 12 <= len(secret) <= 4096 or any(c.isspace() or ord(c) < 32 for c in secret):
        raise ValueError("Enter a valid API key in the secure host form")
    url = {"chatgpt": "https://api.openai.com/v1/models", "claude": "https://api.anthropic.com/v1/models",
           "grok": "https://api.x.ai/v1/models", "gemini": "https://generativelanguage.googleapis.com/v1beta/models"}[family]
    headers = {"Accept": "application/json"}
    if family == "claude":
        headers.update({"x-api-key": secret, "anthropic-version": "2023-06-01"})
    elif family == "gemini":
        headers["x-goog-api-key"] = secret
    else:
        headers["Authorization"] = "Bearer " + secret
    try:
        with build_opener(NoRedirect()).open(Request(url, headers=headers), timeout=10) as response:
            raw = response.read(native.MAX_OUTPUT + 1)
            if len(raw) > native.MAX_OUTPUT or response.status != 200:
                raise ValueError("API validation failed")
            data = json.loads(raw)
            if not isinstance(data, dict) or not isinstance(data.get("data", data.get("models")), list):
                raise ValueError("API validation returned an unsupported report")
    except HTTPError as exc:
        raise ValueError("API authentication failed" if exc.code in (401, 403) else "API validation is unavailable") from None
    except (URLError, OSError, ValueError):
        raise ValueError("API validation failed; no model work was submitted") from None


class ProviderService:
    def __init__(self, backend=None):
        self.native = backend or native.NativeProviders()
        self.lock = threading.RLock()
        self.refresh_locks = {}
        self.observations = {}
        self.capabilities = {}
        self.catalogs = {}
        self.logins = {}
        self.usage = AccountUsageReader()

    def _key(self, identity):
        return (str(paths.data_dir()), identity)

    def capability(self, family, refresh=False):
        key = self._key(family)
        with self.lock:
            existing = self.capabilities.get(key)
            # R1-B / R5-A: an explicit refresh never serves a cached failed or
            # missing-CLI probe for the whole TTL; it re-probes so a transient
            # failure, or an install, is seen on the next read.
            if existing and (not refresh or (time.time() - existing["at"] < TTL and existing["value"].get("state") not in ("error", "unavailable"))):
                return deepcopy(existing["value"])
        if not refresh:
            return {"installed": bool(native.executable(family)), "state": "not_checked", "version": None,
                    "isolated": False, "login": None, "observed_at": None, "source": "Installed native CLI help/schema",
                    "limit": "Refresh host status to check installed capabilities."}
        try:
            out = self.native.capabilities(family)
        except (native.NativeError, OSError, ValueError, TypeError, AttributeError, RecursionError) as exc:
            out = {"installed": bool(native.executable(family)), "state": "error", "version": None, "isolated": False, "login": None,
                   "error": exc.state if isinstance(exc, native.NativeError) else "error",
                   "limit": "Installed capability check failed. Existing sign-in is retained."}
        out.update(observed_at=stamp(), source="Installed native CLI help/schema")
        with self.lock:
            self.capabilities[key] = {"at": time.time(), "value": deepcopy(out)}
        return out

    def initialize(self, body):
        # The installer establishes the running host first. This explicit step
        # uses the existing settings writer only when neither store exists.
        # Established settings (including a valid mirror) remain authoritative.
        if set(body) != {"expected_revision"} or type(body["expected_revision"]) is not int:
            raise ValueError("Invalid first setup action")
        state = anchor_settings.read_settings_state()
        if state["missing"]:
            anchor_settings.save_settings(steward_type="aladdin", expected_revision=body["expected_revision"])
        elif not state["valid"]:
            raise anchor_settings.SettingsInvalid(state["error"])
        return self.snapshot()

    def refresh(self, connection, *, capability=None):
        key = self._key(connection["id"])
        with self.lock:
            gate = self.refresh_locks.setdefault(key, threading.Lock())
        with gate:
            cap = capability if capability is not None else self.capability(connection['family'], True)
            now = stamp()
            old = deepcopy(self.observations.get(key, empty_observation()))
            try:
                if connection["mode"] == "api":
                    secret = provider_secrets.get(connection["id"])
                    if not secret:
                        out = empty_observation()
                        out.update(auth="signed_out", auth_source="Host OS credential vault")
                    else:
                        validate_api(connection["family"], secret)
                        out = empty_observation()
                        out.update(auth="api_key", test="passed", auth_source="Public API model catalog GET")
                    out["allowance"]["state"] = "unsupported"
                elif not cap["installed"]:
                    raise native.NativeError("unavailable")
                elif not connection["native_default"] and not cap["isolated"]:
                    # R3-A: a probe that timed out or errored is reported as that
                    # failure; "unsupported" is reserved for a CLI that answered.
                    raise native.NativeError(cap.get("error", "error") if cap.get("state") == "error" else "unsupported")
                elif connection["family"] == "grok" and cap.get("status_supported") is False:
                    raise native.NativeError("unsupported")
                else:
                    if connection["family"] == "grok" and isinstance(self.native, native.NativeProviders):
                        out = self.native.observe(connection, capability=cap)
                    else:
                        out = self.native.observe(connection)
                out["observed_at"] = now
                for metric in ("allowance", "provider_usage"):
                    prior, report = old[metric], out[metric]
                    if report["state"] != "fresh" and carries_figures(metric, prior) and prior.get("observed_at"):
                        out[metric] = {**prior, "state": "stale", "attempted_at": now, "error": report["state"]}
                    else:
                        # H3: a report that was never produced (unsupported or
                        # unknown, without figures) has no observation time, so
                        # a later failed refresh cannot relabel it as stale.
                        report.update(attempted_at=now, observed_at=now if report["state"] == "fresh"
                                      or carries_figures(metric, report) else None)
                if connection["family"] == "claude" and connection["mode"] == "subscription":
                    report, prior = claude_allowance(connection["id"], now), old["allowance"]
                    # R0-A: when the account-qualified signal has gone, the last
                    # window stays, labelled stale; it is never silently dropped.
                    if not report["windows"] and carries_figures("allowance", prior) and prior.get("observed_at"):
                        report = {**prior, "state": "stale", "attempted_at": now, "error": report["state"]}
                    out["allowance"] = report
                elif (connection["family"] == "chatgpt" and connection["mode"] == "subscription"
                      and isinstance(self.native, native.NativeProviders)
                      and out.get("allowance", {}).get("state") == "fresh"
                      and out["allowance"].get("windows")):
                    try:
                        import usage_allowance_monitor as _uam
                        _uam.record_rate_limit_event(connection["id"], "chatgpt", {"allowance": out["allowance"]})
                    except Exception:
                        pass
            except (native.NativeError, ValueError, OSError) as exc:
                state = exc.state if isinstance(exc, native.NativeError) else "error"
                out = old
                out.update(auth=state, test="failed", attempted_at=now,
                           error="Host status is " + state + "; existing credentials are retained")
                for metric in ("allowance", "provider_usage"):
                    out[metric].update(state="stale" if old[metric].get("observed_at") else state,
                                       attempted_at=now, error=state)
            with self.lock:
                self.observations[key] = deepcopy(out)
            # Capability discovery reads native model catalogs and help only.
            retained_agy = (connection["family"] == "gemini" and connection["id"] == "gemini-default"
                            and connection["native_default"] and connection["mode"] == "subscription"
                            and cap.get("installed") and cap.get("execution") is True
                            and out["auth"] == "unknown" and out["test"] == "not_tested")
            if out["auth"] == "signed_in" or retained_agy:
                try:
                    rows, _ = model_policy.discover(connection["family"], env=native.account_env(connection), runner=native.catalog_command)
                    selection = model_policy.select_model(connection["family"], rows)
                    public_rows = [{"model": r["model"], "efforts": r["efforts"]} for r in rows]
                    public_selection = {"model": selection["model"], "effort": selection["effort"]}
                    with self.lock:
                        self.catalogs[key] = {"state": "fresh", "observed_at": now, "rows": public_rows, "selection": public_selection}
                except (ValueError, RuntimeError, TypeError, AttributeError, OSError):   # R4-B: discovery failure never fails the stored refresh
                    with self.lock:
                        self.catalogs[key] = {"state": "unavailable", "observed_at": now, "rows": []}

    def snapshot(self, refresh=False, identity=None):
        settings = anchor_settings.load_settings()
        connections = settings["provider_connections"]
        if refresh:
            selected = [metadata.find_connection(settings, identity)] if identity else connections
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(self.refresh, selected))
        # Ledger I/O must neither multiply by account count nor hold the lock
        # used to publish native observations and sign-in progress.
        usage = self.usage.read()
        out = []
        capabilities = {family: self.capability(family) for family in {c["family"] for c in connections}}
        with self.lock:
            for connection in connections:
                cap = capabilities[connection["family"]]
                obs = deepcopy(self.observations.get(self._key(connection["id"]), empty_observation()))
                for metric in ("allowance", "provider_usage"):
                    observation = obs[metric]
                    when = observation.get("observed_at")
                    if when and observation["state"] == "fresh" and time.time() - datetime.fromisoformat(when).timestamp() > TTL:
                        observation["state"] = "stale"
                    if metric == "allowance" and any(w.get("resets_at") is not None and w["resets_at"] <= time.time() for w in observation["windows"]):
                        observation["state"] = "stale"
                age = obs.get("observed_at")
                obs["auth_stale"] = bool(age and time.time() - datetime.fromisoformat(age).timestamp() > TTL)
                retained_agy = (connection["family"] == "gemini" and connection["id"] == "gemini-default"
                                and connection["native_default"] and connection["mode"] == "subscription"
                                and cap.get("installed") and cap.get("execution") is True
                                and obs["auth"] == "unknown" and obs["test"] == "not_tested"
                                and obs.get("auth_source") == "Existing Google Ultra connection via agy CLI")
                ready = ((obs["auth"] == "signed_in" or retained_agy) and not obs["auth_stale"] and connection["mode"] == "subscription"
                         and (connection["family"] in ("claude", "chatgpt", "gemini") or connection["family"] == "grok" and cap.get("execution") is True)
                         and (connection["native_default"] or cap["isolated"]))
                catalog = deepcopy(self.catalogs.get(self._key(connection["id"]), {"state": "unknown", "rows": []}))
                if catalog.get("observed_at") and time.time() - datetime.fromisoformat(catalog["observed_at"]).timestamp() > TTL:
                    catalog["state"] = "stale"
                ready = ready and catalog["state"] == "fresh" and bool(catalog.get("rows"))
                reported = [w["remaining_percent"] for w in obs["allowance"]["windows"]]
                remaining = reported if obs["allowance"]["state"] == "fresh" else []
                low = bool(reported and min(reported) <= settings["provider_preferences"]["warning_threshold"])
                exhausted = bool(remaining and min(remaining) <= 0)
                out.append({**connection, **obs, "connection_source": connection_source(connection), "capability": cap, "catalog": catalog,
                            "execution": {"ready": ready and not exhausted, "cockpit": ready and not exhausted,
                                          "jobs": ready and (connection["family"] == "claude" or connection["native_default"]) and not exhausted,
                                          "reason": "API keys use separate provider billing. This subscription-seat architecture has no explicit API execution adapter; saving a key does not enable paid work." if connection["mode"] == "api" else
                                          "Isolated ChatGPT accounts can start new cockpits; the one-shot adapter retains its fixed default home." if connection["family"] == "chatgpt" and not connection["native_default"] else
                                          "Retained Google Ultra via agy; passive authentication and allowance are unreported. Native model capabilities are available." if ready and retained_agy else
                                          "Native authentication checked; allowance may still be unknown." if ready else
                                          "Existing agy model capabilities are unavailable; refresh on the mother ship. Passive account reporting and additional enrollment remain incomplete." if connection["family"] == "gemini" else
                                          "Execution is unready; refresh host authentication and capabilities."},
                            "capacity": "exhausted" if exhausted else "near_limit" if low and remaining else "usable" if remaining else "unknown",
                            "warning": (("Low allowance. " if remaining else "Last report indicated low allowance; its status is now " + obs["allowance"]["state"] + ". ")
                                        + "Full model strength stays selected until you apply a change.") if low else None,
                            "anchor_observed": usage_report(usage, connection["id"]),
                            "api_spend": {**unknown("Provider API billing report", "unsupported"), "amount": None, "currency": None},
                            "subscription_price": {**unknown("Provider subscription billing", "unsupported"), "amount": None}})
        try:
            from steward_cockpit import steward_routes as _scr
            usage_summary, _ = _scr.global_usage_summary()
        except Exception:
            usage_summary = None
        routing_info = _build_services_and_routing_summary(settings, out, capabilities, usage_summary)
        return {"ok": True, "host": host_state(), "settings_revision": settings["settings_revision"],
                "settings_error": settings.get("settings_error"), "preferences": deepcopy(settings["provider_preferences"]),
                "default_family": settings["default_cli"],
                "coding_family": settings.get("coding_family") or settings["default_cli"],
                "review_family": settings.get("review_family") or ("claude" if (settings.get("coding_family") or settings["default_cli"]) != "claude" else "gemini"),
                "connections": out, "api_storage_available": provider_secrets.available(),
                "provider_matrix": [{"family": family, "transport": {"claude": "Claude Code", "chatgpt": "Codex", "gemini": "agy CLI", "grok": "Grok CLI"}[family],
                                     "enrollment": bool(capabilities[family].get("isolated") and capabilities[family].get("login")),
                                     "api_execution": False, "prerequisite": capabilities[family].get("limit")}
                                    for family in metadata.FAMILIES],
                "usage_summary": usage_summary,
                "active_routing": routing_info["active_routing"],
                "logged_in_services": routing_info["logged_in_services"],
                "catalog_defaults": routing_info["catalog_defaults"],
                "product_complete": False}

    def add(self, body):
        settings = anchor_settings.get_launch_settings()
        connection = metadata.new_connection(body.get("family"), body.get("name"), body.get("mode", "subscription"))
        if connection["mode"] == "subscription":
            cap = self.capability(connection["family"], True)
            if not cap["isolated"]:
                raise ValueError("This native provider has no verified isolated account home; existing login is preserved. " + (cap.get("limit") or "Refresh installed provider capabilities on the mother ship."))
            if not cap.get("login"):
                raise ValueError("This installed provider has no supported browser/device sign-in; existing login is preserved")
        anchor_settings.save_settings(provider_connections=settings["provider_connections"] + [connection], expected_revision=body.get("expected_revision"))
        return {"ok": True, "connection_id": connection["id"], "snapshot": self.snapshot()}

    def rename(self, body):
        settings = anchor_settings.get_launch_settings()
        connections = deepcopy(settings["provider_connections"])
        connection = metadata.find_connection(settings, body.get("connection_id"))
        for item in connections:
            if item["id"] == connection["id"]:
                item["name"] = body.get("name")
        anchor_settings.save_settings(provider_connections=connections, expected_revision=body.get("expected_revision"))
        return self.snapshot()

    def remove(self, body):
        settings = anchor_settings.get_launch_settings()
        connection = metadata.find_connection(settings, body.get("connection_id"))
        if connection["native_default"]:
            raise ValueError("Existing default native connections must be retained")
        if connection["id"] in settings["provider_preferences"]["accounts"].values():
            raise ValueError("Apply a different account before removing this connection")
        with self.lock:
            if any(v["key"] == self._key(connection["id"]) and v["state"] in ("starting", "awaiting_browser", "cancelling") for v in self.logins.values()):
                raise ValueError("Cancel this account's sign-in before removing its connection")
            anchor_settings.save_settings(provider_connections=[c for c in settings["provider_connections"] if c["id"] != connection["id"]],
                                          expected_revision=body.get("expected_revision"))
            # Native homes are retained: existing and resumable conversations
            # continue to own the same identity, even after hiding its Setup row.
            self.observations.pop(self._key(connection["id"]), None)
            self.catalogs.pop(self._key(connection["id"]), None)
        return self.snapshot()

    def apply(self, body):
        if type(body.get("expected_revision")) is not int:
            raise ValueError("Load settings before applying changes")
        settings = anchor_settings.get_launch_settings()
        prefs = metadata.validate_preferences(body.get("preferences"), settings["provider_connections"])
        saved = settings["provider_preferences"]
        proposed = {**settings, "provider_preferences": prefs}
        # Reconcile only proposed accounts on this explicit action. A cold
        # cache is unchecked evidence, not a missing adapter or failed login.
        candidates = [metadata.selected_connection(proposed, prefs["family"] or settings["default_cli"])]
        candidates += [metadata.find_connection(settings, identity) for identity in prefs["accounts"].values()]
        for candidate in {c["id"]: c for c in candidates}.values():
            if candidate["family"] in ("grok", "gemini") and candidate["mode"] == "subscription":
                with self.lock:
                    unchecked = self._key(candidate["id"]) not in self.observations
                if unchecked:
                    self.refresh(candidate)
        snapshot = self.snapshot()
        by_id = {c["id"]: c for c in snapshot["connections"]}
        # H1: readiness gates a CHANGE of the account that will execute, not a
        # threshold- or policy-only save; a stale, failed or absent observation
        # keeps the existing choice savable.
        connection = metadata.selected_connection(proposed, prefs["family"] or settings["default_cli"])
        current = metadata.selected_connection(settings, saved["family"] or settings["default_cli"])
        if connection["id"] != current["id"] and not by_id[connection["id"]]["execution"]["ready"]:
            raise ValueError("Selected account is unready for execution; refresh its host status")
        for family, identity in prefs["accounts"].items():
            if identity != saved["accounts"].get(family, family + "-default") and not by_id[identity]["execution"]["ready"]:
                raise ValueError("Selected account is unready for execution; refresh its host status")
        # H2: only a quality choice that differs from the saved one (or that now
        # rides on another account) is checked against a fresh catalog.
        for candidate_family, quality in prefs["quality"].items():
            selected = metadata.selected_connection(proposed, candidate_family)
            if (quality == saved["quality"].get(candidate_family)
                    and selected["id"] == metadata.selected_connection(settings, candidate_family)["id"]):
                continue
            if quality == {"model": "latest_supported", "effort": "highest_supported"}:
                continue
            catalog = by_id[selected["id"]]["catalog"]
            if catalog["state"] != "fresh":
                raise ValueError("Refresh native model capabilities before choosing an exact model or effort")
            model = catalog.get("selection", {}).get("model") if quality["model"] == "latest_supported" else quality["model"]
            row = next((r for r in catalog.get("rows") or [] if r["model"] == model), None)
            if not row and candidate_family == "gemini":
                m = model_policy._AGY_EFFORT_SUFFIX.match(str(model or ""))
                if m:
                    model = m.group(1)
                    row = next((r for r in catalog.get("rows") or [] if r["model"] == model), None)
                    quality["model"] = model
            if not row or quality["effort"] != "highest_supported" and quality["effort"] not in row["efforts"]:
                raise ValueError("Model or reasoning effort is not advertised by this account's native CLI")
        # Store user choices in the existing settings transaction. Do not touch
        # global family/model policy or any live engine, queue or campaign.
        anchor_settings.save_settings(provider_preferences=prefs, expected_revision=body["expected_revision"])
        return self.snapshot()

    def start_login(self, identity):
        connection = metadata.find_connection(anchor_settings.get_launch_settings(), identity)
        if connection["native_default"] or connection["mode"] != "subscription":
            raise ValueError("Add a named subscription for sign-in; the existing default is preserved")
        cap = self.capability(connection["family"], True)
        if not cap["login"] or not cap["isolated"]:
            raise ValueError("Terminal-free isolated enrollment is unsupported by this installed native CLI")
        # Never replace the source of a live/previously bound bridge. Retry a
        # failed pending login, but renewal of a signed-in home needs a new home.
        self.refresh(connection, capability=cap)
        observation = self.observations[self._key(identity)]
        if observation["auth"] == "signed_in":
            raise ValueError("This account is already signed in; add a separate subscription to change identity")
        if observation["test"] == "failed" and observation["auth"] != "expired":
            # W1-E1: a status read that failed leaves the sign-in state unknown,
            # so the guard above stays armed: no native login runs against a
            # possibly signed-in (and bound) home. An expired sign-in is a known
            # state and may still be renewed in place.
            raise ValueError("Host status for this account could not be read; refresh it on the mother ship before signing in")
        if observation["auth"] == "expired" and connection_in_use(identity):
            raise ValueError("This native account is bound to a conversation; add a separate connection to reconnect without replacing its identity")
        with self.lock:
            metadata.find_connection(anchor_settings.get_launch_settings(), identity)
            if any(v["key"] == self._key(identity) and v["state"] in ("starting", "awaiting_browser", "cancelling") for v in self.logins.values()):
                raise ValueError("Sign-in is already in progress for this account")
            if sum(v["state"] in ("starting", "awaiting_browser", "cancelling") for v in self.logins.values()) >= 2:
                raise ValueError("Two host sign-ins are already in progress")
            login_id, cancel = uuid.uuid4().hex, threading.Event()
            self.logins[login_id] = {"id": login_id, "key": self._key(identity), "connection_id": identity,
                                     "state": "starting", "message": "Starting native sign-in on the mother ship", "cancel": cancel,
                                     "started_at": time.time(), "expires_at": time.time() + native.LOGIN_TIMEOUT}
            # Remove only old completed ephemeral attempts.
            for key, value in list(self.logins.items()):
                if value["state"] not in ("starting", "awaiting_browser", "cancelling") and time.time() - value["started_at"] > 600:
                    del self.logins[key]
        def progress(value):
            with self.lock:
                if not cancel.is_set():
                    self.logins[login_id].update(value)
        def worker():
            try:
                self.native.login(connection, cancel, progress, **({'capability': cap} if connection['family'] == 'grok' and isinstance(self.native, native.NativeProviders) else {}))
                if cancel.is_set():
                    raise native.NativeError("cancelled")
                self.refresh(connection, capability=cap)
                observation = self.observations[self._key(identity)]
                if observation["auth"] == "signed_in":
                    state, message = "completed", "Native sign-in completed; account status refreshed on the mother ship"
                elif observation.get("error"):
                    # H6: the native sign-in returned normally; only the follow-up
                    # status read did not (the failure branch marks `error`). Report
                    # the sign-in honestly and leave the row's own state to the
                    # refresh button. A read that ANSWERED (expired, signed out) is a
                    # failed sign-in, below (R6-B).
                    state, message = "completed", ("Native sign-in completed; the follow-up host status read did not succeed. "
                                                   "Refresh this account on the mother ship.")
                else:
                    raise native.NativeError()
            except (native.NativeError, ValueError, OSError):
                state = "cancelled" if cancel.is_set() else "failed"
                message = "Sign-in cancelled" if cancel.is_set() else "Native sign-in failed or timed out. Retry this account; existing default login is retained."
            finally:
                with self.lock:
                    self.logins[login_id].pop("url", None)
                    self.logins[login_id].pop("user_code", None)
                    self.logins[login_id].update(state=state, message=message)
        thread = threading.Thread(target=worker, name="provider-login-" + login_id, daemon=True)
        with self.lock:
            self.logins[login_id]["thread"] = thread
        thread.start()
        return self.login_status(login_id)

    def login_status(self, identity, cancel=False):
        with self.lock:
            value = self.logins.get(identity)
            if not value or value["key"][0] != str(paths.data_dir()):
                raise ValueError("Unknown sign-in attempt")
            if cancel and value["state"] in ("starting", "awaiting_browser"):
                value["cancel"].set()
                value["state"] = "cancelling"
                value["message"] = "Cancelling owned native sign-in"
            # R6-C: the device link and code are shown only while the attempt awaits
            # the browser; a cancelling or finished attempt never carries them.
            shown = ("id", "connection_id", "state", "message", "expires_at") + (("url", "user_code") if value["state"] in ("starting", "awaiting_browser") else ())
            return {"ok": True, **{k: v for k, v in value.items() if k in shown}}


def connection_source(connection):
    transport = {"claude": "Claude Code", "chatgpt": "Codex", "gemini": "Google Ultra via agy CLI", "grok": "Grok CLI"}[connection["family"]]
    if connection["mode"] == "api":
        return "Host OS credential vault · separate API billing"
    return transport + (" · existing mother ship sign-in" if connection["native_default"] else " · isolated native account")


def connection_in_use(identity):
    from steward_cockpit import steward_engine
    with steward_engine._STATE_LOCK:
        state = steward_engine._load_state()
        if not isinstance(state, dict):
            raise ValueError("Native conversation bindings could not be read; existing credentials are retained")
        for entry in state.values():
            if not isinstance(entry, dict):
                continue
            records = [entry] + list(entry.get("provider_sessions") or [])
            if any(isinstance(r, dict) and r.get("session_id") and (r.get("provider_connection") or {}).get("id") == identity for r in records):
                return True
    return False


def claude_allowance(identity, attempted_at):
    import usage_capacity
    signal = usage_capacity.latest_limit_signal(connection_id=identity)
    out = {**unknown("Account-qualified Claude rate_limit_event", "unsupported"), "windows": [], "attempted_at": attempted_at}
    if not signal:
        return out
    out["observed_at"] = signal["seen_at"]
    out["state"] = "fresh" if time.time() - datetime.fromisoformat(signal["seen_at"]).timestamp() < TTL else "stale"
    for key in ("five_hour", "seven_day"):
        window = signal[key]
        if native.finite(window.get("utilization"), 0, 1):
            out["windows"].append({"label": key.replace("_", " "), "remaining_percent": 100 * (1 - window["utilization"]),
                                   "resets_at": window.get("resets_at"), "window_minutes": 300 if key == "five_hour" else 10080})
            if window.get("resets_at") and window["resets_at"] <= time.time():
                out["state"] = "stale"
    if not out["windows"]:
        # R4-A: a signal without one finite window is no report; it carries no
        # observation time, so a later failed refresh can never relabel it stale.
        out.update(state="unsupported", observed_at=None)
    return out


class AccountUsageReader:
    """An in-memory read cache of the existing ledger, shared by all accounts.

    Check every file on every read, but parse only new/replaced documents. Keep
    only account-qualified sums and timestamps, never raw ledger/private data.
    A separate lock serializes readers without blocking native refresh workers.
    """
    def __init__(self):
        self.lock = threading.Lock()
        self.root = None
        self.files = {}
        self._last_dir_mtime_ns = None
        self._last_scan_mono = 0.0
        self._last_stale = False
        self._recent_names = ()
        self._cached_totals = None

    @staticmethod
    def _summarize(doc):
        totals = {}
        entries = doc.get("entries") or {}
        if not isinstance(entries, dict):
            raise ValueError("Invalid usage ledger")
        for entry in entries.values():
            if not isinstance(entry, dict):
                continue
            identity, tokens = entry.get("provider_connection_id"), entry.get("tokens")
            if not isinstance(identity, str) or not identity or not native.finite(tokens):
                continue
            total, latest = totals.get(identity, (0, None))
            when = entry.get("recorded_at")
            if isinstance(when, str):
                latest = max(latest or when, when)
            totals[identity] = (total + tokens, latest)
        return totals

    @staticmethod
    def _disk_cache_path():
        return paths.data_dir() / ".anchor" / "provider_account_usage_cache.json"

    def _load_disk_cache(self, root):
        if os.environ.get("PYTEST_CURRENT_TEST") is not None:
            return
        try:
            cp = self._disk_cache_path()
            if not cp.is_file():
                return
            raw = json.loads(cp.read_text(encoding="utf-8"))
            if not isinstance(raw, dict) or raw.get("root") != str(root):
                return
            loaded = {}
            for name, rec in (raw.get("files") or {}).items():
                if not isinstance(rec, list) or len(rec) != 2:
                    continue
                sig_l, tot_d = rec
                if not isinstance(sig_l, list) or len(sig_l) != 3 or not isinstance(tot_d, dict):
                    continue
                sig = (int(sig_l[0]), int(sig_l[1]), int(sig_l[2]))
                tmap = {}
                for ident, pair in tot_d.items():
                    if isinstance(ident, str) and isinstance(pair, list) and len(pair) == 2 and native.finite(pair[0]):
                        tmap[ident] = (pair[0], pair[1] if isinstance(pair[1], str) else None)
                loaded[str(name)] = (sig, tmap)
            if loaded:
                self.files = loaded
        except Exception:
            pass

    def _save_disk_cache(self, root):
        if os.environ.get("PYTEST_CURRENT_TEST") is not None or len(self.files) <= 250:
            return
        try:
            cp = self._disk_cache_path()
            cp.parent.mkdir(parents=True, exist_ok=True)
            serial = {
                name: [list(sig), {ident: [tok, when] for ident, (tok, when) in tmap.items()}]
                for name, (sig, tmap) in self.files.items()
            }
            paths.atomic_write_json(cp, {"version": 1, "root": str(root), "files": serial})
        except Exception:
            pass

    def read(self):
        import usage_capacity
        root = usage_capacity.ledger_dir()
        root_path = Path(root)
        is_prod = os.environ.get("PYTEST_CURRENT_TEST") is None
        with self.lock:
            if root != self.root:
                self.root, self.files = root, {}
                self._last_dir_mtime_ns = None
                self._last_scan_mono = 0.0
                self._last_stale = False
                self._recent_names = ()
                self._cached_totals = None
                if is_prod:
                    self._load_disk_cache(root)
            now_mono = time.monotonic()
            # Production fast-path for 10k+ ledger dirs when directory mtime is unchanged:
            # re-stat only the 32 newest files instead of scanning all 16k+ NTFS entries every 4s.
            if (
                is_prod
                and len(self.files) > 250
                and not getattr(self, "_last_stale", False)
                and getattr(self, "_cached_totals", None) is not None
                and (now_mono - float(getattr(self, "_last_scan_mono", 0.0) or 0.0)) < 30.0
            ):
                try:
                    dir_mtime = root_path.stat().st_mtime_ns
                except OSError:
                    dir_mtime = None
                if dir_mtime is not None and dir_mtime == getattr(self, "_last_dir_mtime_ns", None):
                    hot_changed = False
                    for rname in getattr(self, "_recent_names", ()):
                        prior = self.files.get(rname)
                        try:
                            info = (root_path / rname).stat()
                            sig = (info.st_mtime_ns, info.st_ctime_ns, info.st_size)
                            if not prior or prior[0] != sig:
                                hot_changed = True
                                break
                        except OSError:
                            hot_changed = True
                            break
                    if not hot_changed:
                        cached_t = self._cached_totals
                        return dict(cached_t), set()

            seen, stale = set(), set()
            dirty_count = 0
            try:
                try:
                    dir_mtime_now = root_path.stat().st_mtime_ns
                except OSError:
                    dir_mtime_now = None
                with os.scandir(root) as files:
                    for file in files:
                        if not os.path.normcase(file.name).endswith(".json"):
                            continue
                        seen.add(file.name)
                        prior = self.files.get(file.name)
                        try:
                            info = file.stat()
                            signature = (info.st_mtime_ns, info.st_ctime_ns, info.st_size)
                            if prior and prior[0] == signature:
                                continue
                            if is_prod and len(seen) > 250:
                                raw_bytes = Path(file.path).read_bytes()
                                if b"provider_connection_id" not in raw_bytes:
                                    s_strip = raw_bytes.strip()
                                    if s_strip.startswith(b"{") and s_strip.endswith(b"}"):
                                        self.files[file.name] = (signature, {})
                                        dirty_count += 1
                                        continue
                                totals = self._summarize(json.loads(raw_bytes.decode("utf-8")))
                            else:
                                with open(file.path, encoding="utf-8") as stream:
                                    totals = self._summarize(json.load(stream))
                            self.files[file.name] = (signature, totals)
                            dirty_count += 1
                        except (OSError, ValueError, TypeError, AttributeError):
                            # Retry on the next read; a failed read cannot erase
                            # a previously observed account's usage.
                            stale.update(prior[1] if prior else ())
                prev_len = len(self.files)
                self.files = {name: value for name, value in self.files.items() if name in seen}
                if dirty_count > 0 or len(self.files) != prev_len:
                    self._save_disk_cache(root)
                if is_prod and len(self.files) > 250:
                    self._last_dir_mtime_ns = dir_mtime_now
                    self._last_scan_mono = now_mono
                    self._recent_names = tuple(
                        name for name, _ in sorted(self.files.items(), key=lambda kv: kv[1][0][0], reverse=True)[:32]
                    )
            except OSError:
                stale.update(identity for _, totals in self.files.values() for identity in totals)
            totals = {}
            for _, accounts in self.files.values():
                for identity, (tokens, when) in accounts.items():
                    total, latest = totals.get(identity, (0, None))
                    totals[identity] = (total + tokens, max(latest or when, when) if when else latest)
            self._last_stale = bool(stale)
            self._cached_totals = dict(totals)
            return totals, stale


def usage_report(usage, identity):
    totals, stale = usage
    total, latest = totals.get(identity, (None, None))
    return {"state": "stale" if identity in stale else "observed" if total is not None else "unknown",
            "tokens": total, "source": "Anchor account-qualified usage ledger",
            "observed_at": latest, "period": "Recorded Anchor work only; other native work is outside this total"}


def observed_tokens(identity):
    """Read only account-qualified entries from the existing usage ledger."""
    return usage_report(SERVICE.usage.read(), identity)


def host_state():
    # Identity facts, not a claim about Tailscale installation/reachability.
    root = paths.data_dir()
    state = anchor_settings.read_settings_state()
    return {"name": socket.gethostname(), "runtime": "mother_ship", "data_directory": str(root),
            "configured": state["valid"], "first_setup": state["missing"],
            "tailscale": "Not checked here; this connection uses Anchor's existing authentication and pairing",
            "project_roots": project_roots(), "star_chart_url": star_chart_url(), "organization": "Use the existing Star Chart and Aladdin conversation; existing projects are retained"}


def star_chart_url():
    from urllib.parse import quote
    try:
        import rnd_registry
        for entry in rnd_registry.list_projects():
            if Path(entry.get("folder_path") or "").name.lower() == "campaign":
                return "/project/" + quote(str(entry["id"]), safe="")
    except (OSError, ValueError, AttributeError, TypeError, KeyError):
        pass
    return "/high-seat#camp"


def project_roots():
    try:
        import rnd_registry
        entries = rnd_registry.list_projects()
        if isinstance(entries, dict):
            entries = entries.get("projects", [])
        return sorted({e["folder_path"] for e in entries if isinstance(e, dict) and isinstance(e.get("folder_path"), str)})
    except (OSError, ValueError, AttributeError, TypeError):
        return []


_PREV_SERVICE = globals().get("SERVICE")
if _PREV_SERVICE is not None and hasattr(_PREV_SERVICE, "observations"):
    _PREV_SERVICE.__class__ = ProviderService
    if hasattr(_PREV_SERVICE, "usage") and _PREV_SERVICE.usage is not None:
        _PREV_SERVICE.usage.__class__ = AccountUsageReader
    SERVICE = _PREV_SERVICE
else:
    SERVICE = ProviderService()

_COMMS_ACCOUNTS_SUMMARY_CACHE: dict = {"sig": None, "ts": 0.0, "accounts": []}


def require_capacity_choice(settings, connection):
    # A cached observation can require a user's explicit route choice. This
    # check performs no native/network refresh and never changes model strength.
    with SERVICE.lock:
        allowance = deepcopy(SERVICE.observations.get(SERVICE._key(connection["id"]), empty_observation())["allowance"])
    observed = allowance.get("observed_at")
    if (allowance["state"] != "fresh" or not observed
            or time.time() - datetime.fromisoformat(observed).timestamp() > TTL
            or any(w.get("resets_at") is not None and w["resets_at"] <= time.time() for w in allowance["windows"])):
        return
    remaining = [w["remaining_percent"] for w in allowance["windows"] if native.finite(w.get("remaining_percent"), 0, 100)]
    if not remaining:
        return
    if min(remaining) <= 0:
        raise ValueError("Selected subscription allowance is exhausted; refresh or apply another account in Setup. Full quality is retained.")
    prefs = settings.get("provider_preferences", metadata.DEFAULT_PREFERENCES)
    if min(remaining) <= prefs["warning_threshold"] and prefs["warning_policy"] == "manual":
        raise ValueError("Your near-limit policy requires an explicit route choice in Setup before starting work. Full quality is retained.")


def selected_for_launch(settings, family, surface="cockpit", check_capacity=False):
    connection = metadata.selected_connection(settings, family)
    if connection["family"] != family:
        raise ValueError("Selected account belongs to a different provider")
    if connection["mode"] != "subscription" or not connection["native_default"] and family not in ("claude", "chatgpt", "grok"):
        raise ValueError("Selected connection has no subscription execution adapter")
    if family == "gemini" and (connection["id"] != "gemini-default" or not connection["native_default"]
                               or not native.executable(family)):
        raise ValueError("Existing Google Ultra agy account or transport is unavailable; additional enrollment remains incomplete")
    if family == "grok" and not connection["native_default"]:
        cap = SERVICE.capability(family)
        with SERVICE.lock:
            observation = deepcopy(SERVICE.observations.get(SERVICE._key(connection["id"])))
        observed = observation.get("observed_at") if observation else None
        if (cap.get("state") == "not_checked" or not observation or not observed
                or time.time() - datetime.fromisoformat(observed).timestamp() > TTL):
            SERVICE.refresh(connection)
            cap = SERVICE.capability(family)
            with SERVICE.lock:
                observation = deepcopy(SERVICE.observations.get(SERVICE._key(connection["id"]), empty_observation()))
        if not cap.get("isolated") or not cap.get("execution"):
            if cap.get("state") == "error":
                raise ValueError("Selected Grok account capability check did not succeed; existing credentials are retained")
            raise ValueError("Selected Grok account has no subscription execution adapter with verified isolated account support")
        if observation["auth"] != "signed_in" or observation["test"] != "passed":
            raise ValueError("Selected Grok account authentication could not be verified for its isolated home; refresh host status")
    if surface == "jobs" and family == "chatgpt" and not connection["native_default"]:
        raise ValueError("The Codex one-shot adapter cannot execute an isolated account; choose its existing native default explicitly")
    if check_capacity:
        require_capacity_choice(settings, connection)
    return connection


def resolve_quality(family, settings, connection, *, surface="cockpit"):
    choice = settings.get("provider_preferences", metadata.DEFAULT_PREFERENCES)["quality"].get(family)
    if surface == "jobs" and family == "chatgpt" and choice and choice != {"model": "latest_supported", "effort": "highest_supported"}:
        raise ValueError("The Codex one-shot adapter requires latest model and highest reasoning")
    # Default accounts still need their own marker and homes when this process
    # was launched under another provider. Keep the selected native login.
    selected = model_policy.resolve(family, settings=settings, env=native.account_env(connection))
    if not choice or choice == {"model": "latest_supported", "effort": "highest_supported"}:
        return selected
    rows, _ = model_policy.discover(family, env=native.account_env(connection))
    model = selected["model"] if choice["model"] == "latest_supported" else choice["model"]
    row = next((r for r in rows if r["model"] == model), None)
    if not row and family == "gemini":
        m = model_policy._AGY_EFFORT_SUFFIX.match(str(model or ""))
        if m:
            model = m.group(1)
            row = next((r for r in rows if r["model"] == model), None)
    if not row:
        raise ValueError("The explicitly selected model is no longer available")
    effort = model_policy.highest_effort(row["efforts"]) if choice["effort"] == "highest_supported" else choice["effort"]
    if effort not in row["efforts"]:
        raise ValueError("The explicitly selected reasoning effort is unavailable")
    return {**selected, "model": model, "effort": effort, "selection_evidence": "explicit_setup_choice"}


def _human_model_display(family, model_id, effort_id):
    m = str(model_id or "").strip()
    e = str(effort_id or "").strip()
    if family == "claude" and m in ("best", "latest_supported", ""):
        m = "claude-fable-5-1"
        e = "max" if e in ("", "highest_supported") else e
    elif m in ("latest_supported", ""):
        defaults = {
            "gemini": ("gemini-4-neon", "high"),
            "chatgpt": ("gpt-6-luna", "ultra"),
            "grok": ("grok-4.7", "xhigh"),
            "claude": ("claude-fable-5-1", "max"),
        }
        dm, de = defaults.get(family, (family, "high"))
        m = dm
        if e in ("", "highest_supported"):
            e = de
    elif e == "highest_supported":
        e = {"claude": "max", "gemini": "high", "chatgpt": "ultra", "grok": "xhigh"}.get(family, "high")
    return f"{m} · {e}" if e else m


def _build_services_and_routing_summary(settings, connections, capabilities=None, usage_summary=None):
    # Support both (settings, connections, capabilities, usage_summary) and legacy/test (connections, prefs)
    if isinstance(settings, list) and isinstance(connections, dict):
        raw_conns = settings
        prefs_arg = connections
        settings = {
            "default_cli": prefs_arg.get("family") or "gemini",
            "coding_family": prefs_arg.get("coding_family") or prefs_arg.get("family") or "gemini",
            "review_family": prefs_arg.get("review_family") or ("claude" if (prefs_arg.get("family") or "gemini") != "claude" else "gemini"),
            "provider_preferences": prefs_arg,
        }
        connections = raw_conns
        if capabilities is None:
            capabilities = {
                str(c.get("family")): {"installed": bool(c.get("installed", True))}
                for c in connections
                if isinstance(c, dict) and c.get("family")
            }
    capabilities = capabilities or {}
    usage_summary = usage_summary or {}
    coding_fam = str(settings.get("coding_family") or settings.get("default_cli") or "gemini").lower()
    review_fam = str(settings.get("review_family") or ("claude" if coding_fam != "claude" else "gemini")).lower()
    prefs = settings.get("provider_preferences") or {}
    quality_map = prefs.get("quality") or {}
    accounts_map = prefs.get("accounts") or {}
    mon_families = ((usage_summary or {}).get("allowance_monitor") or {}).get("families") or {}

    # Load verified catalog defaults from disk without spawning subprocesses
    cat_defaults = {}
    try:
        cat_path = Path(__file__).parent / "gwl_hub_repository" / "verified_model_catalog.json"
        if cat_path.is_file():
            cat_doc = json.loads(cat_path.read_text(encoding="utf-8"))
            for fk, fv in (cat_doc.get("families") or {}).items():
                if isinstance(fv, dict):
                    cat_defaults[fk] = {
                        "frontier_model": fv.get("frontier_model"),
                        "effort_frontier": fv.get("effort_frontier"),
                        "models": list(fv.get("models") or []),
                    }
    except Exception:
        cat_defaults = {}

    transports = {
        "claude": "Claude Code CLI",
        "chatgpt": "OpenAI Codex CLI",
        "gemini": "Google Ultra via agy CLI",
        "grok": "xAI Grok CLI",
    }
    family_labels = {
        "claude": "Claude (Anthropic)",
        "chatgpt": "ChatGPT (OpenAI Codex)",
        "gemini": "Gemini (Google Ultra / agy)",
        "grok": "Grok (xAI)",
    }

    ai_providers = []
    by_family = {}
    for fam in metadata.FAMILIES:
        fam_conns = [c for c in connections if c.get("family") == fam]
        sel_id = accounts_map.get(fam) or f"{fam}-default"
        primary = next((c for c in fam_conns if c.get("id") == sel_id), fam_conns[0] if fam_conns else {})
        by_family[fam] = primary
        cap = (capabilities or {}).get(fam) or {}
        mon = mon_families.get(fam) or {}
        q = quality_map.get(fam) or {"model": "latest_supported", "effort": "highest_supported"}
        cat_sel = ((primary.get("catalog") or {}).get("selection") or {})
        eff_model = cat_sel.get("model") if q.get("model") in (None, "", "latest_supported") and cat_sel.get("model") else q.get("model")
        eff_effort = cat_sel.get("effort") if q.get("effort") in (None, "", "highest_supported") and cat_sel.get("effort") else q.get("effort")
        configured_display = _human_model_display(fam, eff_model, eff_effort)

        auth_raw = str(primary.get("auth") or "unknown")
        agy_ready = bool((capabilities or {}).get("gemini", {}).get("installed"))
        roles = []
        if fam == coding_fam:
            roles.append("Coding Engine")
        if fam == review_fam:
            roles.append("Adversarial Reviewer")

        fallback_active = False
        fallback_note = ""
        active_display = configured_display
        if fam == "claude" and auth_raw == "signed_out" and agy_ready:
            fallback_active = True
            active_display = "Claude Opus 5.5 · high (via agy fallback)"
            fallback_note = (
                "Standalone Claude Code CLI sign-in is expired — routing Claude reviews via Antigravity (agy) "
                "at Claude Opus 5.5 (High). Sign in to Claude CLI to restore Fable 5.1 (claude-fable-5-1 · max)."
            )
        elif fam == "gemini" and auth_raw == "unknown" and cap.get("installed"):
            auth_status = "ready_via_agy"
        auth_label = (
            "Signed in" if auth_raw == "signed_in" else
            "Signed out (via agy fallback)" if (fam == "claude" and auth_raw == "signed_out" and agy_ready) else
            "Signed out" if auth_raw == "signed_out" else
            "Google Ultra ready (agy)" if (fam == "gemini" and cap.get("installed")) else
            "CLI installed" if (cap.get("installed") and mon.get("connected")) else
            auth_raw.replace("_", " ")
        )
        acct_str = str(primary.get("account_identity") or primary.get("account") or "")
        if not acct_str and fam == "gemini" and cap.get("installed"):
            acct_str = "Google Ultra (agy)"
        eff_effort_disp = "high" if fallback_active else (
            "max" if (fam == "claude" and eff_effort in (None, "", "highest_supported")) else
            {"claude": "max", "gemini": "high", "chatgpt": "ultra", "grok": "xhigh"}.get(fam, "high")
            if eff_effort in (None, "", "highest_supported") else str(eff_effort)
        )
        is_ready_flag = bool(auth_raw == "signed_in" or (fam == "gemini" and cap.get("installed")) or fallback_active)
        ai_providers.append({
            "family": fam,
            "label": family_labels.get(fam, fam.title()),
            "connection_id": primary.get("id") or f"{fam}-default",
            "account_identity": primary.get("account_identity") or acct_str or None,
            "account": acct_str,
            "plan": str(primary.get("plan") or ""),
            "transport": transports.get(fam, fam),
            "installed": bool(cap.get("installed")),
            "auth": auth_raw,
            "auth_label": auth_label,
            "signed_in": bool(auth_raw == "signed_in" or (fam == "gemini" and cap.get("installed") and auth_raw in ("signed_in", "unknown"))),
            "signed_in_or_ready": is_ready_flag,
            "effective_ready": is_ready_flag,
            "via_agy_fallback": fallback_active,
            "roles": roles,
            "configured_model": configured_display,
            "configured_model_display": configured_display,
            "configured_effort": eff_effort_disp if not fallback_active else ("max" if fam == "claude" else eff_effort_disp),
            "active_model": active_display,
            "model_display": configured_display,
            "effective_model_display": active_display,
            "effort_display": eff_effort_disp,
            "effective_effort": eff_effort_disp,
            "fallback_active": fallback_active,
            "fallback_note": fallback_note,
            "fallback_reason": fallback_note,
            "status_note": fallback_note or auth_label,
        })

    coding_entry = next((p for p in ai_providers if p["family"] == coding_fam), ai_providers[0] if ai_providers else {})
    review_entry = next((p for p in ai_providers if p["family"] == review_fam), ai_providers[0] if ai_providers else {})

    comms_accounts = []
    try:
        import comms_connector as _cc
        if os.environ.get("PYTEST_CURRENT_TEST") is None:
            try:
                cp_st = _cc._config_path().stat()
                sp_st = _cc._sync_path().stat() if _cc._sync_path().exists() else None
                c_sig = (cp_st.st_mtime_ns, cp_st.st_size, sp_st.st_mtime_ns if sp_st else 0, sp_st.st_size if sp_st else 0)
            except OSError:
                c_sig = None
            now_m = time.monotonic()
            if (
                c_sig is not None
                and _COMMS_ACCOUNTS_SUMMARY_CACHE.get("sig") == c_sig
                and (now_m - float(_COMMS_ACCOUNTS_SUMMARY_CACHE.get("ts") or 0.0)) < 60.0
            ):
                comms_accounts = [dict(x) for x in (_COMMS_ACCOUNTS_SUMMARY_CACHE.get("accounts") or [])]
            else:
                c_state, _ = _cc.handle_comms_get({"slim": "1"})
                for acc in (c_state.get("accounts") or []):
                    if not isinstance(acc, dict):
                        continue
                    raw_em = str(acc.get("email") or "").strip()
                    masked_em = raw_em
                    if "@" in raw_em:
                        u_part, d_part = raw_em.split("@", 1)
                        masked_em = (u_part[:1] + "***@" + d_part) if u_part else ("***@" + d_part)
                    st_str = str(acc.get("status") or "configured")
                    comms_accounts.append({
                        "id": str(acc.get("id") or ""),
                        "label": str(acc.get("label") or acc.get("family") or "Account"),
                        "family": str(acc.get("family") or ""),
                        "email": masked_em,
                        "status": st_str,
                        "auth_mode": str(acc.get("auth_mode") or ""),
                        "has_credentials": bool(acc.get("has_secret") or st_str in ("synced", "connected")),
                        "has_calendar": bool(acc.get("ics_url") or acc.get("auth_mode") in ("local_outlook", "microsoft_graph", "oauth_token", "app_password")),
                    })
                _COMMS_ACCOUNTS_SUMMARY_CACHE.update(sig=c_sig, ts=now_m, accounts=[dict(x) for x in comms_accounts])
    except Exception:
        comms_accounts = []

    review_routing_obj = {
        "family": review_fam,
        "label": review_entry.get("label", review_fam),
        "configured_model": review_entry.get("configured_model", ""),
        "configured_model_display": review_entry.get("configured_model_display", ""),
        "configured_effort": review_entry.get("configured_effort", "max"),
        "active_model": review_entry.get("active_model", ""),
        "effective_model_display": review_entry.get("effective_model_display", ""),
        "effective_effort": review_entry.get("effective_effort", "high"),
        "transport": review_entry.get("transport", ""),
        "auth_label": review_entry.get("auth_label", ""),
        "status_note": review_entry.get("status_note", ""),
        "fallback_active": bool(review_entry.get("fallback_active")),
        "fallback_note": review_entry.get("fallback_note", ""),
        "fallback_reason": review_entry.get("fallback_reason", ""),
    }
    return {
        "coding_family": coding_fam,
        "review_family": review_fam,
        "active_routing": {
            "coding": {
                "family": coding_fam,
                "label": coding_entry.get("label", coding_fam),
                "configured_model": coding_entry.get("configured_model", ""),
                "configured_model_display": coding_entry.get("configured_model_display", ""),
                "configured_effort": coding_entry.get("configured_effort", "high"),
                "active_model": coding_entry.get("active_model", ""),
                "effective_model_display": coding_entry.get("effective_model_display", ""),
                "effective_effort": coding_entry.get("effective_effort", "high"),
                "transport": coding_entry.get("transport", ""),
                "auth_label": coding_entry.get("auth_label", ""),
                "status_note": coding_entry.get("status_note", ""),
            },
            "review": review_routing_obj,
            "adversarial_reviewer": review_routing_obj,
        },
        "logged_in_services": {
            "ai_providers": ai_providers,
            "comms_accounts": comms_accounts,
        },
        "catalog_defaults": cat_defaults,
    }


def handle_page(handler, path, body):
    cookie = handler._local_login_cookie() if hasattr(handler, "_local_login_cookie") else None
    if path == "/setup/install":
        from html import escape
        # The existing installer documentation is code, not user project data.
        content = (Path(__file__).parent / "USER-ONBOARD.md").read_text(encoding="utf-8")
        handler._send_html(
            '<!doctype html><html lang="en"><head><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Anchor installation</title>'
            '<style>'
            'body{margin:0;background:#0d1017;color:#eef1f5;font:14px/1.55 system-ui,Segoe UI,sans-serif}'
            '.inst-top{position:sticky;top:0;display:flex;align-items:center;justify-content:space-between;gap:12px;'
            'padding:10px 20px;background:rgba(13,16,23,0.96);border-bottom:1px solid #2e3a4d;z-index:20}'
            '.inst-top a,.inst-top button{color:#eef1f5;background:#151b26;border:1px solid #2e3a4d;border-radius:7px;'
            'padding:6px 12px;text-decoration:none;font:600 13px system-ui,sans-serif;cursor:pointer}'
            '.inst-top button.anchor-overlay-close-x{width:34px;height:32px;padding:0;display:inline-flex;align-items:center;'
            'justify-content:center;font-size:16px;font-weight:700;border-color:#475569}'
            '.inst-top button.anchor-overlay-close-x:hover{background:#dc2626;border-color:#dc2626;color:#fff}'
            '</style></head><body>'
            '<header class="inst-top">'
            '<div style="display:flex;align-items:center;gap:10px">'
            '<strong style="color:#d9b86c">⚓ Anchor · Installation Guide</strong>'
            '<a href="/setup">← Return to Setup</a>'
            '</div>'
            '<button type="button" id="install-close-x" class="anchor-overlay-close-x" '
            'aria-label="Close overlay and return" title="Close and return to Cave of Wonders or AI Cockpit (Esc)">&#10005;</button>'
            '</header>'
            '<pre style="white-space:pre-wrap;max-width:86ch;margin:24px auto;padding:0 18px">' + escape(content) + '</pre>'
            '<script>'
            '(function(){function closeOv(){if(window.parent!==window){'
            'window.parent.postMessage({type:"anchor-overlay-close",closeTile:true},location.origin);'
            'window.parent.postMessage({type:"anchor-setup-close"},location.origin);return;}'
            'var ref=document.referrer||"";'
            'if(ref && ref.indexOf(location.origin)===0 && ref.indexOf("/setup/install")===-1){location.href=ref;return;}'
            'location.href="/high-seat";}'
            'var b=document.getElementById("install-close-x");if(b)b.onclick=closeOv;'
            'document.addEventListener("keydown",function(e){if(e.key==="Escape"){e.preventDefault();closeOv();}});})();'
            '</script></body></html>',
            cookie=cookie,
        )
        return
    handler._send_html((Path(__file__).parent / "static" / "provider-setup.html").read_text(encoding="utf-8"), cookie=cookie)


def handle_get(handler, path, body):
    query = parse_qs(urlsplit(handler.path).query)
    try:
        # The dispatcher hands over the full URI (query included); route on the path alone.
        if urlsplit(path).path == "/api/provider-setup/login":
            out = SERVICE.login_status(query.get("id", [None])[0])
        else:
            out = SERVICE.snapshot(query.get("refresh", ["0"])[0] == "1", query.get("connection_id", [None])[0])
            out["client_can_enter_api"] = local_request(handler)
        if "connections" in out:
            out["client_can_enter_api"] = local_request(handler)
        if "snapshot" in out:
            out["snapshot"]["client_can_enter_api"] = local_request(handler)
        handler._send_json(out)
    except (ValueError, OSError, RuntimeError):
        handler._send_json({"ok": False, "error": "Host provider status is unavailable; existing setup is retained"}, 400)


def local_request(handler):
    try:
        if any(handler.headers.get(h) for h in ("X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host", "Forwarded", "Via")):
            return False
        host = urlsplit("http://" + handler.headers.get("Host", "")).hostname
        origin = urlsplit(handler.headers.get("Origin", "")).hostname
        return (ipaddress.ip_address(handler.client_address[0]).is_loopback
                and host in ("localhost", "127.0.0.1", "::1")
                and origin in (None, "localhost", "127.0.0.1", "::1"))
    except ValueError:
        return False


def handle_post(handler, path, body):
    path = urlsplit(path).path
    if not handler._steward_same_origin():
        handler._send_json({"ok": False, "error": "Cross-origin provider action refused"}, 403)
        return
    body = body or {}
    try:
        if not isinstance(body, dict):
            raise ValueError("Invalid provider action")
        if path.endswith("/initialize"):
            out = SERVICE.initialize(body)
        elif path.endswith("/accounts"):
            allowed = {"family", "mode", "name", "expected_revision"}
            if set(body) - allowed or type(body.get("expected_revision")) is not int:
                raise ValueError("Only non-secret named account metadata is accepted")
            out = SERVICE.add(body)
        elif path.endswith("/rename"):
            if set(body) - {"connection_id", "name", "expected_revision"} or type(body.get("expected_revision")) is not int:
                raise ValueError("Invalid nickname action")
            out = SERVICE.rename(body)
        elif path.endswith("/remove"):
            if set(body) != {"connection_id", "expected_revision"} or type(body.get("expected_revision")) is not int:
                raise ValueError("Invalid account removal")
            out = SERVICE.remove(body)
        elif path.endswith("/apply"):
            out = SERVICE.apply(body)
        elif path.endswith("/login"):
            out = SERVICE.start_login(body.get("connection_id"))
        elif path.endswith("/cancel"):
            out = SERVICE.login_status(body.get("id"), cancel=True)
        elif path.endswith("/api-key"):
            # Secret entry stays on the mother ship's local UI. A remote client
            # can view API status, but may not transmit keys over plain HTTP.
            if not local_request(handler):
                handler._send_json({"ok": False, "error": "Enter API credentials in Setup on the mother ship itself"}, 403)
                return
            if not provider_secrets.available():
                raise ValueError("Secure OS API credential storage is unavailable")
            connection = metadata.find_connection(anchor_settings.get_launch_settings(), body.get("connection_id"))
            if connection["mode"] != "api":
                raise ValueError("API keys cannot replace subscription sign-ins")
            secret = body.get("api_key")
            validate_api(connection["family"], secret)
            provider_secrets.put(connection["id"], secret)
            SERVICE.refresh(connection)
            out = SERVICE.snapshot()
        else:
            raise ValueError("Unknown provider action")
        if "connections" in out:
            out["client_can_enter_api"] = local_request(handler)
        if "snapshot" in out:
            out["snapshot"]["client_can_enter_api"] = local_request(handler)
        handler._send_json(out)
    except anchor_settings.SettingsInvalid:
        handler._send_json({"ok": False, "error": "Settings changed or are invalid; reload before saving"}, 409)
    except (ValueError, OSError, RuntimeError, TypeError, KeyError) as exc:
        # ValueError messages originate here/metadata only. Never forward any
        # provider, subprocess, vault or HTTP exception text.
        message = str(exc) if type(exc) is ValueError else "Host provider action failed; existing setup is retained"
        handler._send_json({"ok": False, "error": message}, 400)
