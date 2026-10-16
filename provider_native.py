"""Bounded, hidden native account commands. No inference and no token-file reads.

Only allowlisted fields cross this module's boundary. Provider diagnostics and
JSON-RPC errors are classified, never forwarded or logged. Login artifacts are
ephemeral and appear only in the authenticated login response.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import queue
import re
import shutil
import subprocess
import threading
import time
import tempfile
from urllib.parse import urlsplit

import model_policy
import paths

COMMAND_TIMEOUT = 15
LOGIN_TIMEOUT = 300
CANCEL_TIMEOUT = 5   # R2-A: the bound on the cancel RPC a wedged native child may ignore
MAX_OUTPUT = 1024 * 1024
NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0


class NativeError(RuntimeError):
    def __init__(self, state="error"):
        self.state = state
        super().__init__({"unsupported": "Installed native interface does not support this report",
                          "unavailable": "Native CLI is not installed",
                          "expired": "Native authentication needs renewal",
                          "timeout": "Host account command timed out",
                          "cancelled": "Sign-in cancelled",
                          "error": "Host account command failed"}.get(state, "Host account command failed"))


# The documented native redirects and the fixed dotfile homes of each family.
NATIVE_HOME_ENV = {"claude": "CLAUDE_CONFIG_DIR", "chatgpt": "CODEX_HOME", "grok": "GROK_HOME"}
NATIVE_HOME_DIRS = {"claude": ".claude", "chatgpt": ".codex", "grok": ".grok", "gemini": ".gemini"}


def account_home(connection):
    family = connection["family"]
    if connection["native_default"]:
        redirect = os.environ.get(NATIVE_HOME_ENV[family]) if family in NATIVE_HOME_ENV else None
        return Path(redirect or Path.home() / NATIVE_HOME_DIRS[family])
    root = paths.data_dir() / ".anchor" / "provider-accounts"
    nominal = root / connection["id"]
    if nominal.absolute() != nominal.resolve():
        raise ValueError("Account home must not be redirected by a link or junction")
    return nominal


def private_account_path(path):
    """Native credential homes are never project artifacts, even under a host repo.

    H4: the isolated account store AND every default native home (the fixed
    dotfile homes plus the documented CODEX_HOME / CLAUDE_CONFIG_DIR redirects)
    are private, so a registered project folder that encloses them serves none
    of their files through any artifact or project-file route.
    """
    try:
        target = Path(path).resolve()
        return any(target.is_relative_to(home) for home in private_homes())
    except (OSError, RuntimeError, ValueError):
        return True


def private_homes():
    """The private homes, resolved NOW (never cached: a junction retargeted a moment ago is seen). W7 (2026-10-10)
    also compares this tuple to decide whether a reused deliverables answer is still safe to offer."""
    homes = [paths.data_dir() / ".anchor" / "provider-accounts"]
    homes += [Path.home() / name for name in NATIVE_HOME_DIRS.values()]
    homes += [Path(os.environ[key]) for key in NATIVE_HOME_ENV.values() if os.environ.get(key)]
    return tuple(home.resolve() for home in homes)


def account_env(connection):
    env = model_policy.policy_environment()
    # A selected isolated home must never inherit another family's home.
    env.pop("CLAUDE_CONFIG_DIR", None)
    env.pop("CODEX_HOME", None)
    if connection["family"] != "grok":
        env.pop("GROK_HOME", None)  # R0-B: another family never inherits the Grok home
    if connection["family"] in NATIVE_HOME_ENV:
        env[NATIVE_HOME_ENV[connection["family"]]] = str(account_home(connection))
    env["ANCHOR_PROVIDER_CONNECTION"] = connection["id"]
    return env


def executable(family):
    name = {"chatgpt": "codex", "claude": "claude", "grok": "grok", "gemini": "agy"}[family]
    return shutil.which(name + (".exe" if os.name == "nt" else ""))


class HiddenProcess:
    """Own exactly one subprocess and its tree; bound all pipe consumption."""
    def __init__(self, argv, env, *, timeout=None):
        # The bound is read from the module at call time, so a lowered
        # COMMAND_TIMEOUT governs every hidden command that does not name its own.
        self.deadline = time.monotonic() + (COMMAND_TIMEOUT if timeout is None else timeout)
        self.events = queue.Queue(maxsize=256)
        self.stop = threading.Event()
        self.total = 0
        self.proc = subprocess.Popen(argv, env=env, cwd=str(Path(__file__).parent),
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                     shell=False, creationflags=NO_WINDOW,
                                     start_new_session=os.name != "nt")
        self.guard = None
        if os.name == "nt":
            import proc_probe
            try:
                self.guard = proc_probe.attach_to_job_object(self.proc.pid)
            except Exception:
                self.close()
                raise NativeError()
            if not self.guard:
                self.close()
                raise NativeError()
        self.threads = [threading.Thread(target=self._read, args=(stream, label), daemon=True)
                        for stream, label in ((self.proc.stdout, "stdout"), (self.proc.stderr, "stderr"))]
        for thread in self.threads:
            thread.start()

    def _read(self, stream, label):
        try:
            while not self.stop.is_set():
                line = stream.readline(MAX_OUTPUT + 1)
                if not line:
                    break
                self.total += len(line)
                if self.total > MAX_OUTPUT:
                    self.stop.set()
                    break
                try:
                    self.events.put((label, line.decode("utf-8", errors="replace")), timeout=.2)
                except queue.Full:
                    self.stop.set()
                    break
        except (OSError, ValueError):
            pass
        finally:
            try:
                self.events.put((label, None), timeout=.2)
            except queue.Full:
                self.stop.set()

    def send(self, value):
        try:
            self.proc.stdin.write((json.dumps(value) + "\n").encode("utf-8"))
            self.proc.stdin.flush()
        except (OSError, ValueError):
            raise NativeError() from None

    def next(self, cancel=None, deadline=None):
        while True:
            if cancel is not None and cancel.is_set():
                raise NativeError("cancelled")
            if time.monotonic() >= min(self.deadline, deadline or self.deadline):
                raise NativeError("timeout")
            if self.stop.is_set():
                raise NativeError()
            try:
                return self.events.get(timeout=.1)
            except queue.Empty:
                if self.proc.poll() is not None and all(not t.is_alive() for t in self.threads) and self.events.empty():
                    raise NativeError()

    def close(self):
        self.stop.set()
        if self.guard:
            try:
                import ctypes
                from ctypes import wintypes
                ctypes.windll.kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
                ctypes.windll.kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
                ctypes.windll.kernel32.TerminateJobObject(self.guard, 1)
                ctypes.windll.kernel32.CloseHandle(self.guard)
            finally:
                self.guard = None
        if self.proc.poll() is None:
            if os.name != "nt":
                import signal
                try:
                    os.killpg(self.proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            else:
                self.proc.kill()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        for stream in (self.proc.stdin, self.proc.stdout, self.proc.stderr):
            try:
                stream.close()
            except (OSError, ValueError):
                pass


def run_command(argv, env, cancel=None, timeout=None, progress=None):
    child = HiddenProcess(argv, env, timeout=timeout)
    lines, ended = [], set()
    try:
        while len(ended) < 2:
            label, line = child.next(cancel)
            if line is None:
                ended.add(label)
            else:
                if label == "stdout":
                    lines.append(line)
                if progress:
                    progress(line)
        code = child.proc.wait(timeout=2)
        return code, "".join(lines)
    finally:
        child.close()


def catalog_command(argv, env):
    code, result = run_command(argv, env)
    if code:
        raise NativeError()
    return result


class CodexAccount:
    def __init__(self, connection, *, timeout=None):
        binary = executable("chatgpt")
        if not binary:
            raise NativeError("unavailable")
        # Stdio is private to this reader, never the daemon/bridge of another effort.
        self.child = HiddenProcess([binary, "app-server", "--listen", "stdio://"], account_env(connection), timeout=timeout)
        self.sequence = 0
        self.notifications = []
        try:
            self.rpc("initialize", {"clientInfo": {"name": "anchor_provider_setup", "title": "Anchor Setup", "version": "1"},
                                    "capabilities": {"experimentalApi": True}})
            self.child.send({"method": "initialized"})
        except Exception:
            self.close()
            raise

    def rpc(self, method, params=None, cancel=None):
        self.sequence += 1
        identity = self.sequence
        self.child.send({"id": identity, "method": method, "params": params or {}})
        while True:
            label, line = self.child.next(cancel)
            if label != "stdout" or not line:
                continue
            try:
                message = json.loads(line)
            except (ValueError, RecursionError):
                raise NativeError() from None
            if message.get("id") != identity:
                if message.get("method") == "account/login/completed":
                    self.notifications.append(message)
                continue
            if "error" in message:
                error = message["error"]
                code = error.get("code") if isinstance(error, dict) else None
                state = "unsupported" if code == -32601 else "expired" if code in (401, 403) else "error"
                raise NativeError(state)
            result = message.get("result")
            if not isinstance(result, dict):
                raise NativeError()
            return result

    def close(self):
        self.child.close()


def finite(value, lower=0, upper=1e18):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and lower <= value <= upper


def allowance_windows(raw):
    result = []
    buckets = raw.get("rateLimitsByLimitId")
    if not isinstance(buckets, dict) or not buckets:
        buckets = {"codex": raw.get("rateLimits")}
    for bucket, value in list(buckets.items())[:20]:
        if not isinstance(value, dict):
            continue
        for kind in ("primary", "secondary"):
            window = value.get(kind)
            if not isinstance(window, dict) or not finite(window.get("usedPercent"), 0, 100):
                continue
            reset, duration = window.get("resetsAt"), window.get("windowDurationMins")
            result.append({"label": (bucket if isinstance(bucket, str) and re.fullmatch(r"[\w .-]{1,60}", bucket) else "Allowance") + " · " + kind,
                           "remaining_percent": 100 - window["usedPercent"],
                           "resets_at": reset if finite(reset) else None,
                           "window_minutes": duration if finite(duration, 1) else None})
    return result


def safe_auth_url(value, family):
    if not isinstance(value, str) or len(value) > 4096:
        return None
    try:
        url = urlsplit(value)
        port = url.port
    except ValueError:
        return None
    allowed = {"chatgpt": {"auth.openai.com", "chatgpt.com"},
               "claude": {"claude.ai", "claude.com", "platform.claude.com", "console.anthropic.com"},
               "grok": {"grok.com", "accounts.x.ai", "auth.x.ai"}}[family]
    if url.scheme != "https" or url.hostname not in allowed or url.username or url.password or port not in (None, 443):
        return None
    return value



def masked_identity(value):
    """Show only a masked email from an allowlisted native account field."""
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9._+%-]{1,64}@[A-Za-z0-9.-]{1,190}\.[A-Za-z]{2,20}", value):
        return None
    local, domain = value.split("@")
    return local[0] + "***@" + ".".join(part[0] + "***" for part in domain.split(".") if part)


def grok_status(connection):
    code, raw = run_command([executable("grok"), "auth", "status", "--json"], account_env(connection))
    try:
        account = json.loads(raw)
    except (ValueError, RecursionError):
        raise NativeError() from None
    if not isinstance(account, dict) or type(account.get("loggedIn")) is not bool:
        raise NativeError("unsupported")
    directory = account.get("configDirectory")
    if not isinstance(directory, str):
        raise NativeError("unsupported")
    try:
        matches = Path(directory).resolve() == account_home(connection).resolve()
    except (OSError, ValueError, RuntimeError):
        raise NativeError("unsupported") from None
    if not matches:
        raise NativeError("unsupported")
    if code not in (0, 1):
        raise NativeError()
    return account


class NativeProviders:
    def capabilities(self, family):
        binary = executable(family)
        if not binary:
            transport = {"claude": "Claude Code", "chatgpt": "Codex", "gemini": "agy", "grok": "Grok"}[family]
            return {"installed": False, "state": "unavailable", "version": None, "isolated": False, "login": None,
                    "limit": transport + " CLI is not installed on this mother ship. The existing trusted installation mechanism is required; Setup does not install a replacement."}
        code, version = run_command([binary, "--version"], model_policy.policy_environment())
        match = re.search(r"\b\d+\.\d+\.\d+\b", version)
        out = {"installed": True, "state": "available" if code == 0 else "error",
               "version": match.group() if match else None, "isolated": False, "login": None}
        if family == "chatgpt":
            code, help_text = run_command([binary, "app-server", "--help"], model_policy.policy_environment())
            if code == 0 and "--listen" in help_text:
                # The installed schema is capability proof. Do not assume a
                # documented device flow exists on an older executable.
                with tempfile.TemporaryDirectory(prefix=".provider-schema-", dir=paths.data_dir()) as directory:
                    result, _ = run_command([binary, "app-server", "generate-json-schema", "--out", directory], model_policy.policy_environment())
                    files = list(Path(directory).rglob("*.json"))
                    schema_path = next((p for p in files if p.name == "LoginAccountParams.json"), None)
                    if result == 0 and schema_path and schema_path.stat().st_size < MAX_OUTPUT:
                        schema = json.loads(schema_path.read_text(encoding="utf-8"))
                        flows = [mode for entry in schema.get("oneOf", []) for mode in entry.get("properties", {}).get("type", {}).get("enum", [])]
                        device = "chatgptDeviceCode" in flows
                        # CODEX_HOME is the native documented isolation seam;
                        # validate it with an empty temporary account read.
                        if device:
                            import provider_settings
                            probe = provider_settings.new_connection("chatgpt", "Capability probe")
                            probe_env = account_env(probe)
                            probe_env["CODEX_HOME"] = directory
                            child = HiddenProcess([binary, "app-server", "--listen", "stdio://"], probe_env)
                            # Reuse the RPC implementation with this owned child.
                            client = CodexAccount.__new__(CodexAccount)
                            client.child, client.sequence, client.notifications = child, 0, []
                            try:
                                client.rpc("initialize", {"clientInfo": {"name": "anchor_provider_setup", "version": "1"}})
                                child.send({"method": "initialized"})
                                isolated = client.rpc("account/read", {"refreshToken": False}).get("account") is None
                                out.update(isolated=isolated, login="device" if isolated else None)
                            finally:
                                client.close()
        elif family == "claude":
            code, help_text = run_command([binary, "auth", "login", "--help"], model_policy.policy_environment())
            # configDirectory attribution was added in 2.1.268. Confirm each
            # isolated status resolves the requested directory before login.
            version_tuple = tuple(map(int, match.group().split("."))) if match else ()
            out.update(isolated=version_tuple >= (2, 1, 268), login="browser" if code == 0 and "--claudeai" in help_text else None)
        elif family == "grok":
            # Only a CLI advertising these interfaces may be probed. A moving
            # model catalog or a browser password is never sign-in proof.
            out.update(status_supported=False, execution=False)
            code, help_text = run_command([binary, "--help"], model_policy.policy_environment())
            if code == 0 and re.search(r"(?m)^\s*auth\s", help_text) and "GROK_HOME" in help_text:
                code, help_text = run_command([binary, "auth", "--help"], model_policy.policy_environment())
                if code == 0 and all(re.search(r"(?m)^\s*" + command + r"\s", help_text) for command in ("status", "login")):
                    code, status_help = run_command([binary, "auth", "status", "--help"], model_policy.policy_environment())
                    login_code, login_help = run_command([binary, "auth", "login", "--help"], model_policy.policy_environment())
                    if code == 0 and login_code == 0 and "--json" in status_help and ("--browser" in login_help or "--device-auth" in login_help):
                        import provider_settings
                        with tempfile.TemporaryDirectory(prefix=".provider-grok-", dir=paths.data_dir()) as directory:
                            probe = provider_settings.new_connection("grok", "Capability probe")
                            env = account_env(probe)
                            env["GROK_HOME"] = directory
                            result, raw = run_command([binary, "auth", "status", "--json"], env)
                            try:
                                report = json.loads(raw)
                                isolated = (result in (0, 1) and isinstance(report, dict)
                                            and report.get("loggedIn") is False
                                            and isinstance(report.get("configDirectory"), str)
                                            and Path(report["configDirectory"]).resolve() == Path(directory).resolve())
                            except (ValueError, TypeError, OSError, RuntimeError):
                                isolated = False
                            login_mode = ("browser" if "--browser" in login_help else "device") if isolated else None
                            out.update(isolated=isolated, login=login_mode,
                                       execution=isolated, status_supported=isolated)
            if not out["isolated"]:
                out["limit"] = "Requires installed Grok auth status --json, auth login --browser and documented GROK_HOME isolation, with configDirectory and subscription billing attribution. Existing Grok sign-in is retained."
        else:
            # Passive reporting and native execution are separate capabilities.
            # No account enrollment or inferred authentication/allowance here.
            out.update(status_supported=False, execution=out["state"] == "available",
                       limit="Existing Google Ultra uses the agy CLI. Its passive account/status report is unsupported; the retained native account can use its supported model catalog. Isolated browser enrollment remains incomplete.")
        return out

    def observe(self, connection, *, capability=None):
        family, env = connection["family"], account_env(connection)
        if not executable(family):
            raise NativeError("unavailable")
        if family == "chatgpt":
            client = CodexAccount(connection)
            try:
                account = client.rpc("account/read", {"refreshToken": False}).get("account")
                subscription = isinstance(account, dict) and account.get("type") == "chatgpt"
                out = {"auth": "signed_in" if subscription else "different_billing_mode" if account else "signed_out",
                       "test": "passed" if subscription else "not_tested", "auth_source": "Codex account/read",
                       "account_identity": masked_identity(account.get("email")) if subscription else None,
                       "allowance": {"state": "unknown", "source": "Codex account/rateLimits/read", "windows": []},
                       "provider_usage": {"state": "unknown", "source": "Codex account/usage/read", "tokens": None}}
                if subscription:
                    for method, key in (("account/rateLimits/read", "allowance"), ("account/usage/read", "provider_usage")):
                        try:
                            report = client.rpc(method)
                            if key == "allowance":
                                windows = allowance_windows(report)
                                out[key].update(state="fresh" if windows else "unknown", windows=windows)
                            else:
                                tokens = (report.get("summary") or {}).get("lifetimeTokens")
                                out[key].update(state="fresh" if finite(tokens) else "unknown", tokens=tokens if finite(tokens) else None)
                        except NativeError as exc:
                            out[key]["state"] = exc.state
                            if exc.state == "expired":
                                out.update(auth="expired", test="failed")
                return out
            finally:
                client.close()
        if family == "claude":
            code, raw = run_command([executable(family), "auth", "status"], env)
            try:
                account = json.loads(raw)
            except (ValueError, RecursionError):
                raise NativeError() from None
            if not isinstance(account, dict):
                raise NativeError()
            if not connection["native_default"]:
                directory = account.get("configDirectory")
                if not isinstance(directory, str) or not directory:
                    raise NativeError("unsupported")
                try:
                    matches = Path(directory).resolve() == account_home(connection).resolve()
                except (OSError, ValueError, RuntimeError):
                    matches = False
                if not matches:
                    raise NativeError("unsupported")
            subscription = account.get("loggedIn") is True and account.get("authMethod") == "claude.ai"
            state = "signed_in" if subscription and code == 0 else "different_billing_mode" if account.get("loggedIn") else "signed_out" if code in (0, 1) else "error"
            return {"auth": state, "test": "passed" if state == "signed_in" else "not_tested", "auth_source": "claude auth status",
                    "account_identity": masked_identity(account.get("email")),
                    "allowance": {"state": "unsupported", "source": "Account-qualified Claude rate_limit_event", "windows": []},
                    "provider_usage": {"state": "unsupported", "source": "Native CLI", "tokens": None}}
        if family == "grok":
            # Refresh passes its verified capability; standalone reads discover
            # before touching the requested account.
            cap = capability if capability is not None else self.capabilities(family)
            if not cap.get("status_supported"):
                raise NativeError("unsupported")
            account = grok_status(connection)
            subscription = account.get("loggedIn") and account.get("billingMode") == "subscription"
            state = "signed_in" if subscription else "different_billing_mode" if account.get("loggedIn") else "signed_out"
            return {"auth": state, "test": "passed" if subscription else "not_tested",
                    "auth_source": "Grok auth status --json", "account_identity": masked_identity(account.get("email")),
                    "allowance": {"state": "unsupported", "source": "Grok exposes no verified allowance report", "windows": []},
                    "provider_usage": {"state": "unsupported", "source": "Native CLI", "tokens": None}}
        if family == "gemini":
            # A model catalog is not authentication proof. Never submit a turn
            # from a display/status refresh, including against the existing agy login.
            return {"auth": "unknown", "test": "not_tested", "auth_source": "Existing Google Ultra connection via agy CLI",
                    "allowance": {"state": "unsupported", "source": "agy has no passive allowance report", "windows": []},
                    "provider_usage": {"state": "unsupported", "source": "agy has no passive usage report", "tokens": None}}
        raise NativeError("unsupported")

    def login(self, connection, cancel, progress, *, capability=None):
        if connection["native_default"] or connection["mode"] != "subscription":
            raise ValueError("Use a separate named subscription; existing login is preserved")
        account_home(connection).mkdir(parents=True, exist_ok=True)
        family = connection["family"]
        if family == "chatgpt":
            client = CodexAccount(connection, timeout=LOGIN_TIMEOUT)
            login_id = None
            try:
                result = client.rpc("account/login/start", {"type": "chatgptDeviceCode"}, cancel)
                login_id = result.get("loginId")
                url, code = safe_auth_url(result.get("verificationUrl"), family), result.get("userCode")
                if not isinstance(login_id, str) or not url or not isinstance(code, str) or not re.fullmatch(r"[A-Z0-9-]{4,20}", code):
                    raise NativeError("unsupported")
                progress({"state": "awaiting_browser", "url": url, "user_code": code,
                          "message": "Open the native device sign-in link. Credentials are saved only on this mother ship."})
                while True:
                    if client.notifications:
                        message = client.notifications.pop(0)
                    else:
                        label, line = client.child.next(cancel)
                        if label != "stdout" or not line:
                            continue
                        try:
                            message = json.loads(line)
                        except ValueError:
                            continue
                    if message.get("method") == "account/login/completed" and message.get("params", {}).get("loginId") == login_id:
                        if message["params"].get("success") is not True:
                            raise NativeError()
                        return
            finally:
                if login_id and cancel.is_set():
                    try:
                        # R2-A: bounded through the owned child's own deadline; a
                        # native child that never answers the cancel cannot delay the
                        # reap below past CANCEL_TIMEOUT.
                        if getattr(client.child, "deadline", None) is not None:
                            client.child.deadline = min(client.child.deadline, time.monotonic() + CANCEL_TIMEOUT)
                        client.rpc("account/login/cancel", {"loginId": login_id})
                    except NativeError:
                        pass
                client.close()
        if family == "claude":
            # Prove that this CLI observes this exact separate home before a
            # command capable of replacing credentials is allowed to run.
            self.observe(connection)
            def line_progress(line):
                for candidate in re.findall(r"https://[^\s<>]+", line):
                    url = safe_auth_url(candidate.rstrip(".,)"), family)
                    if url:
                        progress({"state": "awaiting_browser", "url": url, "accepts_code": True,
                                  "message": "Complete native Claude sign-in in the browser on the mother ship. Remote callbacks must return there."})
            code, _ = run_command([executable(family), "auth", "login", "--claudeai"], account_env(connection),
                                  cancel, LOGIN_TIMEOUT, line_progress)
            if code:
                raise NativeError()
            return
        if family == "grok":
            cap = capability if capability is not None else self.capabilities(family)
            if not cap.get("isolated") or not cap.get("login"):
                raise NativeError("unsupported")
            self.observe(connection, capability=cap)
            state_box = {"url": None, "user_code": None}
            def line_progress(line):
                code_match = re.search(r"\b([A-Z0-9]{4}-[A-Z0-9]{4})\b", line)
                if code_match:
                    state_box["user_code"] = code_match.group(1)
                for candidate in re.findall(r"https://[^\s<>]+", line):
                    url = safe_auth_url(candidate.rstrip(".,)"), family)
                    if url:
                        state_box["url"] = url
                if state_box["url"]:
                    payload = {"state": "awaiting_browser", "url": state_box["url"],
                               "message": "Complete Grok subscription sign-in in the provider browser. Native credentials stay on this mother ship."}
                    if state_box["user_code"]:
                        payload["user_code"] = state_box["user_code"]
                    progress(payload)
            flag = "--device-auth" if cap.get("login") == "device" else "--browser"
            code, _ = run_command([executable(family), "auth", "login", flag], account_env(connection),
                                  cancel, LOGIN_TIMEOUT, line_progress)
            if code:
                raise NativeError()
            return
        raise NativeError("unsupported")
