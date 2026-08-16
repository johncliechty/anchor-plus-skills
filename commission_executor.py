#!/usr/bin/env python3
"""Anchor reference commission executor — IMPLEMENTATION #1 of the skill-owned
durable handback-file contract (Ecgberht Wave 4 / NS criterion 15).

HOST CONTRACT ONLY (NS v5 non-goal): no propose/confirm decisions, reflection,
attention derivation, or roadmap/status law. This module:

  * refuses anything not confirmed
  * revalidates auth at the launch seam
  * writes a durable launch-intent BEFORE spawn
  * drives a real trio run through job_runner (kill_on_job_close=False for
    commissions — commissions outlive the service)
  * tracks liveness by (pid, proc_create_time) — never pid alone
  * implements the durable handback FILE protocol at the contract path
  * boot-reconciles intents + worktrees (adopt complete pairs; name dead /
    missing handbacks; never silently absorb)
  * strips ANCHOR_TOKEN / capabilities from the child env (Descope D-1)
  * surfaces substrate refusals by name (LaneBusyError, spawn-cap, folder-build-lock)
  * records G4 evidence fields (observed only — never ``commissionable``)

Contract path (skill-owned; mirrored here, not forked):
  <worktree>/.ecgberht/handback/handback.json
  <worktree>/.ecgberht/handback/TERMINAL.marker

Stdlib only.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Optional

# ── Contract constants (must match Ecgberht schema/handback-contract.schema.json) ──

CONTRACT_VERSION = "1.0.0"
HANDBACK_REL_DIR = Path(".ecgberht") / "handback"
HANDBACK_JSON_NAME = "handback.json"
TERMINAL_MARKER_NAME = "TERMINAL.marker"

# Commissions outlive the Anchor service (explicit, recorded decision).
COMMISSION_KILL_ON_JOB_CLOSE = False
COMMISSION_KILL_ON_JOB_CLOSE_REASON = (
    "commissions outlive the service — kill_on_job_close=False so nssm restart "
    "does not murder an in-flight commissioned run (Wave 4)"
)

# One-run-at-a-time as declared DEGRADED mode.
DEGRADED_ONE_RUN_AT_A_TIME = True

# Env keys that must never reach the child (Descope D-1).
_FORBIDDEN_CHILD_ENV = frozenset({
    "ANCHOR_TOKEN",
    "ANCHOR_CAPABILITY",
    "ANCHOR_CAPABILITY_TOKEN",
    "ECGBERHT_CAPABILITY",
})

# Failure-state table (Wave 4) — status codes are the machine names.
EXEC_SUBSTRATE_MISSING = "EXEC_SUBSTRATE_MISSING"
EXEC_REFUSED_UNCONFIRMED = "EXEC_REFUSED_UNCONFIRMED"
EXEC_SUBSTRATE_BUSY = "EXEC_SUBSTRATE_BUSY"
EXEC_RUN_DIED = "EXEC_RUN_DIED"
EXEC_HANDBACK_MISSING = "EXEC_HANDBACK_MISSING"
EXEC_RUN_ADOPTED = "EXEC_RUN_ADOPTED"
EXEC_AUTH_REFUSED = "EXEC_AUTH_REFUSED"
EXEC_DOSSIER_UNREADABLE = "EXEC_DOSSIER_UNREADABLE"
EXEC_NO_RUNS = "EXEC_NO_RUNS"
EXEC_LIVENESS_UNKNOWN = "EXEC_LIVENESS_UNKNOWN"
LAUNCH_INTENT_STRANDED = "LAUNCH_INTENT_STRANDED"

FAILURE_STATES = {
    EXEC_SUBSTRATE_MISSING: {
        "state": "dependency-missing (trio CLI absent)",
        "status_code": EXEC_SUBSTRATE_MISSING,
        "user_text": (
            "The build substrate is not available on this box — commission cannot launch."
        ),
    },
    EXEC_REFUSED_UNCONFIRMED: {
        "state": "launch-refused (unconfirmed)",
        "status_code": EXEC_REFUSED_UNCONFIRMED,
        "user_text": "Commission not confirmed — nothing launched, nothing spent.",
    },
    EXEC_SUBSTRATE_BUSY: {
        "state": "substrate-busy (LaneBusy / spawn cap / build lock)",
        "status_code": EXEC_SUBSTRATE_BUSY,
        "user_text": (
            "Substrate refused the launch (<reason>) — commission intact; retry when clear."
        ),
    },
    EXEC_RUN_DIED: {
        "state": "launched-then-died",
        "status_code": EXEC_RUN_DIED,
        "user_text": (
            "Run <id> died (process identity no longer live) — named dead, not absorbed."
        ),
    },
    EXEC_HANDBACK_MISSING: {
        "state": "no-handback (marker absent past TTL)",
        "status_code": EXEC_HANDBACK_MISSING,
        "user_text": (
            "Run <id> ended with no handback file — named missing, not absorbed."
        ),
    },
    EXEC_RUN_ADOPTED: {
        "state": "adopted-after-restart",
        "status_code": EXEC_RUN_ADOPTED,
        "user_text": (
            "Run <id> survived a service restart — handback adopted from its durable file."
        ),
    },
    EXEC_AUTH_REFUSED: {
        "state": "auth-refused at launch",
        "status_code": EXEC_AUTH_REFUSED,
        "user_text": (
            "Launch refused — credential invalid at the launch seam; nothing started."
        ),
    },
    EXEC_DOSSIER_UNREADABLE: {
        "state": "backing-store-unreadable",
        "status_code": EXEC_DOSSIER_UNREADABLE,
        "user_text": (
            "Commission dossier unreadable — launch refused rather than launched blind."
        ),
    },
    EXEC_NO_RUNS: {
        "state": "empty-but-valid",
        "status_code": EXEC_NO_RUNS,
        "user_text": "No commissioned runs.",
    },
    EXEC_LIVENESS_UNKNOWN: {
        "state": "unknown (liveness undeterminable)",
        "status_code": EXEC_LIVENESS_UNKNOWN,
        "user_text": "Run liveness UNKNOWN — shown as unknown, not running.",
    },
    LAUNCH_INTENT_STRANDED: {
        "state": "confirmed-but-unlaunched",
        "status_code": LAUNCH_INTENT_STRANDED,
        "user_text": (
            "Commission was confirmed but never launched — named stranded, not silent."
        ),
    },
}


def _fail(code: str, **extra: Any) -> dict:
    base = FAILURE_STATES.get(code, {
        "state": code,
        "status_code": code,
        "user_text": code,
    })
    out = {
        "ok": False,
        "status_code": base["status_code"],
        "state": base["state"],
        "user_text": base["user_text"],
        "pid": None,
        "proc_create_time": None,
    }
    out.update(extra)
    return out


# ── Atomic write (S6: temp + fsync + rename) ─────────────────────────────────

_REPLACE_RETRIES = 40
_REPLACE_BACKOFF_S = 0.005


def _atomic_write_text(target: Path, text: str) -> None:
    """Write ``text`` via temp + fsync + rename in the target directory."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(
        f".{target.name}.tmp-{os.getpid()}-{uuid.uuid4().hex[:8]}"
    )
    try:
        with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass
        for attempt in range(_REPLACE_RETRIES):
            try:
                os.replace(str(tmp), str(target))
                return
            except PermissionError:
                if attempt == _REPLACE_RETRIES - 1:
                    raise
                time.sleep(_REPLACE_BACKOFF_S)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def handback_dir(worktree: Path | str) -> Path:
    return Path(worktree) / HANDBACK_REL_DIR


def handback_json_path(worktree: Path | str) -> Path:
    return handback_dir(worktree) / HANDBACK_JSON_NAME


def terminal_marker_path(worktree: Path | str) -> Path:
    return handback_dir(worktree) / TERMINAL_MARKER_NAME


def is_ingestable(worktree: Path | str) -> bool:
    return handback_json_path(worktree).is_file() and terminal_marker_path(worktree).is_file()


def write_handback_pair(
    worktree: Path | str,
    handback_body: dict,
    *,
    client_event_id: Optional[str] = None,
    handback_id: Optional[str] = None,
) -> dict:
    """Write handback.json then TERMINAL.marker (S6). Single writer per run dir."""
    body = dict(handback_body)
    if client_event_id and not body.get("client_event_id"):
        body["client_event_id"] = client_event_id
    if handback_id and not body.get("handback_id"):
        body["handback_id"] = handback_id
    body.setdefault("contract_version", CONTRACT_VERSION)

    wt = Path(worktree)
    hb = handback_json_path(wt)
    mk = terminal_marker_path(wt)
    _atomic_write_text(hb, json.dumps(body, indent=2) + "\n")
    marker = {
        "contract_version": CONTRACT_VERSION,
        "terminal": True,
        "written_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "client_event_id": body.get("client_event_id"),
        "handback_id": body.get("handback_id"),
    }
    _atomic_write_text(mk, json.dumps(marker) + "\n")
    return {
        "ok": True,
        "handback_path": str(hb),
        "marker_path": str(mk),
        "client_event_id": body.get("client_event_id"),
        "handback_id": body.get("handback_id"),
        "contract_version": CONTRACT_VERSION,
    }


# ── Launch intent (Master-Plan P6) ───────────────────────────────────────────

def launch_intents_dir(store_root: Path | str) -> Path:
    return Path(store_root) / "launch-intents"


def launch_intent_path(store_root: Path | str, commission_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in str(commission_id))
    return launch_intents_dir(store_root) / f"{safe}.json"


def write_launch_intent(
    store_root: Path | str,
    *,
    commission_id: str,
    who: Any,
    worktree: Path | str,
    skill: str = "researchPrime",
    depth: str = "LITE",
    confirmed: bool = True,
    extra: Optional[dict] = None,
) -> dict:
    """Durable launch-intent BEFORE spawn. Boot reconciles stranded intents."""
    intent = {
        "schema": "ecgberht-launch-intent-v1",
        "contract_version": CONTRACT_VERSION,
        "commission_id": commission_id,
        "who": who,
        "worktree": str(worktree),
        "skill": skill,
        "depth": depth,
        "confirmed": bool(confirmed),
        "status": "intent_recorded",
        "recorded_at": time.time(),
        "pid": None,
        "proc_create_time": None,
        "job_id": None,
        "kill_on_job_close": COMMISSION_KILL_ON_JOB_CLOSE,
        "kill_on_job_close_reason": COMMISSION_KILL_ON_JOB_CLOSE_REASON,
        "degraded_one_run_at_a_time": DEGRADED_ONE_RUN_AT_A_TIME,
    }
    if extra:
        intent.update(extra)
    path = launch_intent_path(store_root, commission_id)
    _atomic_write_text(path, json.dumps(intent, indent=2) + "\n")
    intent["intent_path"] = str(path)
    return intent


def update_launch_intent(store_root: Path | str, commission_id: str, **fields: Any) -> dict:
    path = launch_intent_path(store_root, commission_id)
    if not path.is_file():
        return _fail(EXEC_DOSSIER_UNREADABLE, message=f"intent missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return _fail(EXEC_DOSSIER_UNREADABLE, message=str(e))
    data.update(fields)
    data["updated_at"] = time.time()
    _atomic_write_text(path, json.dumps(data, indent=2) + "\n")
    return data


def list_launch_intents(store_root: Path | str) -> list[dict]:
    d = launch_intents_dir(store_root)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError):
            continue
    return out


# ── Auth at launch seam ──────────────────────────────────────────────────────

def authorize_at_launch(
    auth_ctx: Optional[dict],
    *,
    authorizer: Optional[Callable[[str, dict], dict]] = None,
    expected_token: Optional[str] = None,
    enforce: bool = True,
) -> dict:
    """Revalidate credential at the launch seam. Named refusal + zero pid.

    When ``authorizer`` is supplied it is called as authorizer('launch', ctx).
    Otherwise a local shared-secret check against ``expected_token`` (or
    paths.expected_token when available) is used under enforce mode.
    """
    ctx = dict(auth_ctx or {})

    if authorizer is not None:
        decision = authorizer("launch", ctx)
        if not decision or not decision.get("ok"):
            return {
                "ok": False,
                "status_code": EXEC_AUTH_REFUSED,
                "auth_code": (decision or {}).get("code", "auth-refused"),
                "message": (decision or {}).get("message")
                or FAILURE_STATES[EXEC_AUTH_REFUSED]["user_text"],
                "pid": None,
            }
        return {"ok": True, "status_code": "auth-ok"}

    if not enforce:
        return {"ok": True, "status_code": "auth-disabled"}

    if ctx.get("revoked") is True:
        return {
            "ok": False,
            "status_code": EXEC_AUTH_REFUSED,
            "auth_code": "auth-revoked",
            "message": FAILURE_STATES[EXEC_AUTH_REFUSED]["user_text"],
            "pid": None,
        }

    exp = ctx.get("expires_at")
    if exp is not None:
        try:
            exp_ts = float(exp) if isinstance(exp, (int, float)) else None
            if exp_ts is None and isinstance(exp, str):
                # ISO-ish: compare as string epoch if pure digits else skip parse
                if exp.isdigit():
                    exp_ts = float(exp)
                else:
                    # simple: if looks like past date vs now — use time.time via fromisoformat
                    try:
                        from datetime import datetime, timezone
                        exp_ts = datetime.fromisoformat(exp.replace("Z", "+00:00")).timestamp()
                    except Exception:
                        exp_ts = None
            if exp_ts is not None and exp_ts < time.time():
                return {
                    "ok": False,
                    "status_code": EXEC_AUTH_REFUSED,
                    "auth_code": "auth-expired",
                    "message": FAILURE_STATES[EXEC_AUTH_REFUSED]["user_text"],
                    "pid": None,
                }
        except Exception:
            pass

    want = expected_token
    if want is None:
        try:
            import paths as _paths
            want = _paths.expected_token()
        except Exception:
            want = os.environ.get("ANCHOR_TOKEN")

    # Enforce mode: missing configured token → refuse (auth-ON lane).
    if not want:
        return {
            "ok": False,
            "status_code": EXEC_AUTH_REFUSED,
            "auth_code": "auth-absent-config",
            "message": FAILURE_STATES[EXEC_AUTH_REFUSED]["user_text"],
            "pid": None,
        }

    provided = ctx.get("token")
    if not provided:
        return {
            "ok": False,
            "status_code": EXEC_AUTH_REFUSED,
            "auth_code": "auth-absent",
            "message": FAILURE_STATES[EXEC_AUTH_REFUSED]["user_text"],
            "pid": None,
        }

    import hmac
    if not hmac.compare_digest(str(provided), str(want)):
        return {
            "ok": False,
            "status_code": EXEC_AUTH_REFUSED,
            "auth_code": "auth-wrong-token",
            "message": FAILURE_STATES[EXEC_AUTH_REFUSED]["user_text"],
            "pid": None,
        }

    return {"ok": True, "status_code": "auth-ok"}


# ── Child env (no token) ─────────────────────────────────────────────────────

def child_env(base: Optional[dict] = None) -> dict:
    """Build child environment with ANCHOR_TOKEN / capabilities stripped (D-1)."""
    env = dict(base if base is not None else os.environ)
    for k in list(env.keys()):
        if k in _FORBIDDEN_CHILD_ENV or k.upper() in _FORBIDDEN_CHILD_ENV:
            env.pop(k, None)
    return env


def assert_no_token_in_env(env: dict) -> bool:
    for k in env:
        if k in _FORBIDDEN_CHILD_ENV or "CAPABILITY" in k.upper() and "ANCHOR" in k.upper():
            return False
        if k == "ANCHOR_TOKEN":
            return False
    return True


# ── Liveness by (pid, proc_create_time) ──────────────────────────────────────

def process_identity_alive(pid: Optional[int], proc_create_time: Optional[float]) -> str:
    """Return 'alive' | 'dead' | 'unknown' using identity tuple, never pid alone."""
    if not pid:
        return "dead"
    try:
        import proc_probe
    except Exception:
        return "unknown"

    try:
        live = proc_probe.is_alive(int(pid))
    except Exception:
        return "unknown"

    if not live:
        return "dead"

    if proc_create_time is None:
        # Alive pid without create_time: cannot defeat PID reuse → unknown, not running.
        return "unknown"

    try:
        now_ct = proc_probe.creation_time(int(pid))
    except Exception:
        return "unknown"

    if now_ct is None:
        return "unknown"

    # Allow small float skew
    if abs(float(now_ct) - float(proc_create_time)) > 1.5:
        # PID recycled by a different process
        return "dead"

    return "alive"


# ── DEGRADED one-run-at-a-time ───────────────────────────────────────────────

_active_commission_lock = None
_active_commission_id: Optional[str] = None


def _get_active_lock():
    global _active_commission_lock
    if _active_commission_lock is None:
        import threading
        _active_commission_lock = threading.Lock()
    return _active_commission_lock


def claim_one_run_slot(commission_id: str) -> Optional[dict]:
    """DEGRADED mode: only one commissioned run at a time in this process."""
    if not DEGRADED_ONE_RUN_AT_A_TIME:
        return None
    lock = _get_active_lock()
    with lock:
        global _active_commission_id
        if _active_commission_id is not None and _active_commission_id != commission_id:
            return _fail(
                EXEC_SUBSTRATE_BUSY,
                reason="degraded-one-run-at-a-time",
                holder=_active_commission_id,
                user_text=FAILURE_STATES[EXEC_SUBSTRATE_BUSY]["user_text"].replace(
                    "<reason>", "degraded-one-run-at-a-time"
                ),
            )
        _active_commission_id = commission_id
        return None


def release_one_run_slot(commission_id: str) -> None:
    lock = _get_active_lock()
    with lock:
        global _active_commission_id
        if _active_commission_id == commission_id:
            _active_commission_id = None


# ── Wave 13 lease renewal (S12 outbox — interval caller) ─────────────────────

def renew_commission_lease(
    worktree: Path | str,
    *,
    run_id: str,
    step_id: Optional[str] = None,
    pid: Optional[int] = None,
    proc_create_time: Optional[float] = None,
) -> dict:
    """Renew the durable S12 lease for a live commissioned run.

    Called on an interval by the run wrapper / supervisor. Emits an outbox
    lease_renew record only — never touches roadmap.json.
    """
    import status_outbox as _sout

    return _sout.renew_lease(
        worktree,
        run_id=run_id,
        step_id=step_id,
        pid=pid,
        proc_create_time=proc_create_time,
    )


# ── Execute confirmed commission ─────────────────────────────────────────────

def execute_confirmed_commission(
    commission: dict,
    *,
    store_root: Path | str,
    worktree: Optional[Path | str] = None,
    auth_ctx: Optional[dict] = None,
    authorizer: Optional[Callable] = None,
    expected_token: Optional[str] = None,
    enforce_auth: bool = True,
    launch_fn: Optional[Callable] = None,
    command: Optional[list] = None,
    project_id: Optional[str] = None,
    folder_path: Optional[Path | str] = None,
    lane: str = "research",
    backend: str = "claude",
    prompt: Optional[str] = None,
) -> dict:
    """CONFIRMED commission → real trio run through job_runner.

    Parameters ``launch_fn`` / ``command`` enable unit tests to inject a
    substrate without a live claude. Production uses job_runner.launch_guarded
    with kill_on_job_close=False.
    """
    if not commission or not isinstance(commission, dict):
        return _fail(EXEC_DOSSIER_UNREADABLE, message="commission object required")

    if commission.get("confirmed") is not True:
        return _fail(
            EXEC_REFUSED_UNCONFIRMED,
            commission_id=commission.get("commission_id") or commission.get("proposal_id"),
        )

    commission_id = str(
        commission.get("commission_id")
        or commission.get("proposal_id")
        or commission.get("id")
        or uuid.uuid4().hex
    )
    who = commission.get("who")
    skill = commission.get("skill") or "researchPrime"
    depth = commission.get("depth") or commission.get("depth_cell") or "LITE"
    wt = Path(worktree or commission.get("worktree") or store_root)
    wt.mkdir(parents=True, exist_ok=True)
    store_root = Path(store_root)
    store_root.mkdir(parents=True, exist_ok=True)

    # AUTH REVALIDATION AT LAUNCH
    auth = authorize_at_launch(
        auth_ctx,
        authorizer=authorizer,
        expected_token=expected_token,
        enforce=enforce_auth,
    )
    if not auth.get("ok"):
        return _fail(
            EXEC_AUTH_REFUSED,
            auth_code=auth.get("auth_code"),
            message=auth.get("message"),
            commission_id=commission_id,
            pid=None,
            proc_create_time=None,
        )

    # INTENT BEFORE SPAWN
    intent = write_launch_intent(
        store_root,
        commission_id=commission_id,
        who=who,
        worktree=wt,
        skill=skill,
        depth=depth,
        confirmed=True,
        extra={"step_id": commission.get("step_id")},
    )

    # DEGRADED one-run-at-a-time: refuse if another intent is still live.
    if DEGRADED_ONE_RUN_AT_A_TIME:
        for other in list_launch_intents(store_root):
            oid = other.get("commission_id")
            if oid == commission_id:
                continue
            if other.get("status") != "launched":
                continue
            live = process_identity_alive(other.get("pid"), other.get("proc_create_time"))
            if live == "alive":
                return _fail(
                    EXEC_SUBSTRATE_BUSY,
                    reason="degraded-one-run-at-a-time",
                    holder=oid,
                    commission_id=commission_id,
                    user_text=FAILURE_STATES[EXEC_SUBSTRATE_BUSY]["user_text"].replace(
                        "<reason>", "degraded-one-run-at-a-time"
                    ),
                )

    busy = claim_one_run_slot(commission_id)
    if busy is not None:
        update_launch_intent(
            store_root, commission_id, status="refused_busy", refusal=busy
        )
        return busy

    try:
        env = child_env()
        if not assert_no_token_in_env(env):
            return _fail(
                EXEC_AUTH_REFUSED,
                message="child env still carried a forbidden token — refused before spawn",
                commission_id=commission_id,
            )

        # Build launch
        try:
            if launch_fn is not None:
                rec = launch_fn(
                    lane=lane,
                    cwd=str(wt),
                    env=env,
                    command=command,
                    kill_on_job_close=COMMISSION_KILL_ON_JOB_CLOSE,
                    project_id=project_id or commission_id,
                    folder_path=str(folder_path or wt),
                    prompt=prompt,
                    backend=backend,
                )
            else:
                import job_runner as jr
                # Prefer launch_guarded when project/folder known; else launch.
                kwargs = dict(
                    lane=lane,
                    cwd=str(wt),
                    env=env,
                    kill_on_job_close=COMMISSION_KILL_ON_JOB_CLOSE,
                    backend=backend,
                    prompt=prompt or (
                        f"Ecgberht commission {commission_id} skill={skill} depth={depth}"
                    ),
                )
                if command:
                    kwargs["command"] = command
                if project_id and folder_path:
                    rec = jr.launch_guarded(
                        project_id=project_id,
                        folder_path=str(folder_path),
                        **kwargs,
                    )
                else:
                    rec = jr.launch(**kwargs)
        except Exception as e:
            # Surface LaneBusyError / spawn-cap / folder-build-lock by name
            reason = getattr(e, "reason", None) or type(e).__name__
            name = type(e).__name__
            if name == "LaneBusyError" or reason in (
                "spawn-cap-reached",
                "folder-build-lock",
                "same-lane",
            ) or "spawn-cap" in str(e) or "folder-build" in str(e):
                update_launch_intent(
                    store_root,
                    commission_id,
                    status="refused_substrate_busy",
                    refusal_reason=str(reason),
                )
                return _fail(
                    EXEC_SUBSTRATE_BUSY,
                    reason=str(reason),
                    holder=getattr(e, "holder", None),
                    exception=name,
                    commission_id=commission_id,
                    user_text=FAILURE_STATES[EXEC_SUBSTRATE_BUSY]["user_text"].replace(
                        "<reason>", str(reason)
                    ),
                )
            if "not found" in str(e).lower() or name in ("FileNotFoundError",):
                update_launch_intent(
                    store_root, commission_id, status="refused_substrate_missing"
                )
                return _fail(
                    EXEC_SUBSTRATE_MISSING,
                    message=str(e),
                    commission_id=commission_id,
                )
            update_launch_intent(
                store_root, commission_id, status="launch_error", error=str(e)
            )
            return _fail(
                EXEC_SUBSTRATE_MISSING,
                message=str(e),
                exception=name,
                commission_id=commission_id,
            )

        pid = rec.get("pid")
        pct = rec.get("proc_create_time")
        job_id = rec.get("job_id")
        cmdline = rec.get("command") or rec.get("cmdline") or command

        update_launch_intent(
            store_root,
            commission_id,
            status="launched",
            pid=pid,
            proc_create_time=pct,
            job_id=job_id,
            cmdline=cmdline,
            kill_on_job_close=COMMISSION_KILL_ON_JOB_CLOSE,
        )

        # Wave 13 — S12 lease emission (no lease/heartbeat existed in job_runner).
        # Durable outbox record; Node mediator drains → status_flip via spine.
        # Python NEVER writes the campaign ledger.
        lease_record = None
        try:
            import status_outbox as _sout

            lease_record = _sout.renew_lease(
                wt,
                run_id=str(job_id or commission_id),
                step_id=str(dossier.get("step_id") or "") or None,
                pid=pid,
                proc_create_time=pct,
            )
        except Exception as lease_exc:  # noqa: BLE001 — best-effort; launch still ok
            lease_record = {
                "ok": False,
                "error": "lease_renew_failed",
                "detail": str(lease_exc),
            }

        # G4 evidence skeleton (observed only — never commissionable)
        evidence = {
            "commission_id": commission_id,
            "pid": pid,
            "proc_create_time": pct,
            "cmdline": cmdline,
            "job_id": job_id,
            "worktree": str(wt),
            "kill_on_job_close": COMMISSION_KILL_ON_JOB_CLOSE,
            "kill_on_job_close_reason": COMMISSION_KILL_ON_JOB_CLOSE_REASON,
            "observed_live": process_identity_alive(pid, pct) == "alive",
            "skill": skill,
            "depth": depth,
            "who": who,
            "contract_version": CONTRACT_VERSION,
            "recorded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            # S8: executor writes evidence, never commissionable
        }

        return {
            "ok": True,
            "status_code": "EXEC_LAUNCHED",
            "commission_id": commission_id,
            "job_id": job_id,
            "pid": pid,
            "proc_create_time": pct,
            "worktree": str(wt),
            "cmdline": cmdline,
            "kill_on_job_close": COMMISSION_KILL_ON_JOB_CLOSE,
            "intent_path": intent.get("intent_path"),
            "evidence": evidence,
            "who": who,
            "degraded_one_run_at_a_time": DEGRADED_ONE_RUN_AT_A_TIME,
            "lease": lease_record,
            "writes_roadmap_ledger": False,
        }
    finally:
        # Critical-section lock only — durable one-at-a-time is intent+liveness above.
        release_one_run_slot(commission_id)


# ── Boot reconcile ───────────────────────────────────────────────────────────

def boot_reconcile(
    store_root: Path | str,
    *,
    adopted_registry_path: Optional[Path | str] = None,
    handback_ttl_s: float = 0.0,
) -> dict:
    """On service start: scan launch-intents + worktrees for terminal markers.

    * complete handback pair → ADOPT exactly once (client_event_id idempotent)
    * dead run, no marker → EXEC_RUN_DIED / EXEC_HANDBACK_MISSING (named)
    * confirmed intent never launched → LAUNCH_INTENT_STRANDED
    Never silently absorb.
    """
    store_root = Path(store_root)
    results = []
    adopted_ids: set[str] = set()
    reg_path = Path(adopted_registry_path) if adopted_registry_path else (
        store_root / "adopted-handbacks.json"
    )
    if reg_path.is_file():
        try:
            data = json.loads(reg_path.read_text(encoding="utf-8"))
            adopted_ids = set(data.get("ids") or [])
        except (OSError, json.JSONDecodeError):
            adopted_ids = set()

    intents = list_launch_intents(store_root)
    if not intents:
        return {
            "ok": True,
            "status_code": EXEC_NO_RUNS,
            "results": [],
            "user_text": FAILURE_STATES[EXEC_NO_RUNS]["user_text"],
        }

    for intent in intents:
        cid = intent.get("commission_id") or "unknown"
        status = intent.get("status")
        wt = intent.get("worktree")
        pid = intent.get("pid")
        pct = intent.get("proc_create_time")

        # Confirmed but never launched
        if status in ("intent_recorded",) and not pid:
            row = {
                "commission_id": cid,
                "status_code": LAUNCH_INTENT_STRANDED,
                "user_text": FAILURE_STATES[LAUNCH_INTENT_STRANDED]["user_text"],
                "intent_status": status,
            }
            results.append(row)
            update_launch_intent(
                store_root, cid, status="stranded", reconcile=row
            )
            continue

        # Complete pair → adopt
        if wt and is_ingestable(wt):
            try:
                body = json.loads(handback_json_path(wt).read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                body = {}
            ceid = body.get("client_event_id") or body.get("handback_id") or cid
            if ceid in adopted_ids:
                results.append({
                    "commission_id": cid,
                    "status_code": EXEC_RUN_ADOPTED,
                    "duplicate": True,
                    "client_event_id": ceid,
                    "message": "already adopted — idempotent no-op",
                })
                continue
            adopted_ids.add(str(ceid))
            row = {
                "commission_id": cid,
                "status_code": EXEC_RUN_ADOPTED,
                "client_event_id": ceid,
                "handback_id": body.get("handback_id"),
                "handback_path": str(handback_json_path(wt)),
                "user_text": FAILURE_STATES[EXEC_RUN_ADOPTED]["user_text"].replace(
                    "<id>", str(cid)
                ),
                "duplicate": False,
            }
            results.append(row)
            update_launch_intent(
                store_root, cid, status="adopted", reconcile=row
            )
            continue

        # Liveness
        live = process_identity_alive(pid, pct)
        if live == "alive":
            results.append({
                "commission_id": cid,
                "status_code": "EXEC_STILL_RUNNING",
                "pid": pid,
                "proc_create_time": pct,
                "kill_on_job_close": intent.get("kill_on_job_close"),
            })
            continue

        if live == "unknown":
            results.append({
                "commission_id": cid,
                "status_code": EXEC_LIVENESS_UNKNOWN,
                "user_text": FAILURE_STATES[EXEC_LIVENESS_UNKNOWN]["user_text"],
                "pid": pid,
            })
            continue

        # Dead, no marker
        if wt and handback_json_path(wt).is_file() and not terminal_marker_path(wt).is_file():
            code = EXEC_HANDBACK_MISSING
        elif wt and not is_ingestable(wt):
            code = EXEC_HANDBACK_MISSING if status == "launched" else EXEC_RUN_DIED
        else:
            code = EXEC_RUN_DIED

        # Prefer RUN_DIED when we had a pid that is gone
        if pid and live == "dead" and not is_ingestable(wt or ""):
            # If never had handback at all → RUN_DIED; if partial → HANDBACK_MISSING
            if wt and handback_json_path(wt).is_file():
                code = EXEC_HANDBACK_MISSING
            else:
                code = EXEC_RUN_DIED

        row = {
            "commission_id": cid,
            "status_code": code,
            "user_text": FAILURE_STATES[code]["user_text"].replace("<id>", str(cid)),
            "pid": pid,
            "proc_create_time": pct,
            "worktree": wt,
        }
        results.append(row)
        update_launch_intent(store_root, cid, status="reconciled_failed", reconcile=row)

    _atomic_write_text(
        reg_path,
        json.dumps(
            {"ids": sorted(adopted_ids), "contract_version": CONTRACT_VERSION},
            indent=2,
        )
        + "\n",
    )

    return {
        "ok": True,
        "results": results,
        "adopted_count": sum(
            1 for r in results
            if r.get("status_code") == EXEC_RUN_ADOPTED and not r.get("duplicate")
        ),
        "contract_version": CONTRACT_VERSION,
    }


def attach_handback_to_dossier(
    dossier_dir: Path | str,
    worktree: Path | str,
    *,
    commission_id: str,
) -> dict:
    """Copy/link the durable handback into the commission dossier once ingestable."""
    if not is_ingestable(worktree):
        return _fail(
            EXEC_HANDBACK_MISSING,
            commission_id=commission_id,
            user_text=FAILURE_STATES[EXEC_HANDBACK_MISSING]["user_text"].replace(
                "<id>", commission_id
            ),
        )
    dest_dir = Path(dossier_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    src = handback_json_path(worktree)
    dest = dest_dir / "handback.json"
    body = src.read_text(encoding="utf-8")
    _atomic_write_text(dest, body)
    return {
        "ok": True,
        "dossier_handback_path": str(dest),
        "source": str(src),
        "commission_id": commission_id,
    }


# ── Startup hook (called from anchor_gui near job_runner.reconcile_on_startup) ─

def reconcile_commissions_on_startup(store_root: Optional[Path | str] = None) -> dict:
    """Service boot entry: reconcile commission intents under the Anchor data dir."""
    if store_root is None:
        try:
            import paths as _paths
            root = Path(_paths.data_dir()) / "ecgberht-commissions"
        except Exception:
            root = Path(os.environ.get("ANCHOR_DATA_DIR", ".")) / "ecgberht-commissions"
    else:
        root = Path(store_root)
    root.mkdir(parents=True, exist_ok=True)
    return boot_reconcile(root)


# ── Managed-session launcher (2026-08-06) ────────────────────────────────────
#
# WHY THIS EXISTS. The default launcher drives a commission as a piped one-shot
# job and tries to ANSWER the skill's human gates itself, by writing plain text
# into the child's stdin after auto-dismissing an AskUserQuestion. That path is
# documented in job_runner as "best-effort continuation, not guaranteed", and it
# is why Crucible and Foreman were both marked ``executor_not_proven``: a skill
# that asks a real question is not reliably resumable that way.
#
# John's read, and it is the right one: a skill hitting a gate is not a problem
# to route around — it is the skill saying "I need the human". So this launcher
# does not fake an answer. It runs the commission as a MANAGED TERMINAL SESSION
# (the same substrate the project window already shows), which means:
#
#   * the session is registered, attachable, and survives the service restarting
#   * when the skill asks something, it just waits — no auto-dismiss, no guessing
#   * John can open THAT session, read everything it did, type an answer, and
#     hand it back, exactly as if he had run the CLI himself
#
# Nothing about the trio changes. This is a different execution strategy behind
# the SAME ``launch_fn`` seam ``execute_confirmed_commission`` already exposes.

#: Lane a commissioned skill runs in. The lane carries the skill seed
#: (lanes.SKILL_PLAN == "crucible"), so the session opens already loaded.
COMMISSION_SKILL_LANE = {
    "Crucible": "plan",
    "crucible": "plan",
    "Foreman": "build",
    "foreman": "build",
    "researchPrime": "research",
    "researchprime": "research",
}


def lane_for_commissioned_skill(skill: str) -> Optional[str]:
    """Lane whose seed loads ``skill``, or None when the skill has no lane."""
    if not skill:
        return None
    return COMMISSION_SKILL_LANE.get(str(skill)) or COMMISSION_SKILL_LANE.get(
        str(skill).lower()
    )


def launch_commission_in_session(
    *,
    lane: str,
    project_id: str,
    prompt: Optional[str] = None,
    backend: str = "claude",
    start_session_fn: Optional[Callable] = None,
    label: str = "",
    lean_worktree: bool = True,
    **_ignored: Any,
) -> dict:
    """``launch_fn`` that starts a MANAGED SESSION instead of a piped job.

    Returns the record shape ``execute_confirmed_commission`` expects
    (``pid`` / ``proc_create_time`` / ``job_id`` / ``command``), with the managed
    session id carried as ``job_id`` so the commission binds to a session a human
    can actually open.

    ``start_session_fn`` is injectable so this is testable without a live PTY.
    """
    starter = start_session_fn
    if starter is None:
        import terminal_session as _ts

        starter = _ts.start_session

    rec = starter(
        project_id,
        lane,
        backend=backend,
        label=label or "commission",
        # The brief rides in as the session's opening turn, folded onto the lane
        # seed — so the session comes up with the skill loaded AND the work stated.
        seed_context=prompt,
        # Commissions get a LEAN checkout by default — the skill needs the project's
        # text and code, not its media (measured 0.3 MB vs 1430 MB on MBA Teaching AI).
        lean_worktree=lean_worktree,
    )
    if not isinstance(rec, dict):
        raise RuntimeError("start_session did not return a session record")

    session_id = rec.get("session_id") or rec.get("id")
    if not session_id:
        raise RuntimeError("session record carries no session_id")

    return {
        "pid": rec.get("pid"),
        "proc_create_time": rec.get("proc_create_time"),
        # The session IS the run handle. Binding to it is what lets the steward
        # raise "this needs you" and drop John into the very session that asked.
        "job_id": session_id,
        "session_id": session_id,
        "managed_session": True,
        "lane": lane,
        "backend": rec.get("backend") or backend,
        "command": rec.get("command") or rec.get("cmdline"),
        "worktree_path": rec.get("worktree_path"),
    }
