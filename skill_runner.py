"""Skill Foundry v2 — the generic manifest-driven skill_runner core (Wave 3).

This module GENERALIZES Anchor's ``gandalf.py`` consumer ADAPTER (never the
skill itself) into ONE reusable runner parameterized by a per-skill MANIFEST.
The single-source invariant holds: skills are CONSUMED from their canonical
on-disk dir (``skill_dir``), embedding the skill's own ``SKILL.md`` and running
the skill's OWN host (``host_cmd``) — never forked, copied, or re-versioned,
and NEVER imported as Python code.

The manifest (the Wave-3 schema Wave 9's ``foundry.gen_manifest`` validates
against) carries, per skill:

* ``skill``            — the registry key (unique per dispatch table)
* ``skill_dir``        — the canonical on-disk skill folder (single source)
* ``host_cmd``         — the skill's own host process, as a command string or
                         argv list; ``{skill_dir}`` placeholders resolve at
                         declare time. Resolved, NEVER executed, at build.
* ``output_contract``  — what a correct host output looks like
                         (``format`` = ``json``|``text``, optional
                         ``required_keys`` for json)
* ``panel``            — GUI panel meta (``title`` + free-form extras)
* ``journal``          — the journal spec. Journaling is HOST-ENFORCED
                         (DESCRIPTION invariant): ``enabled: false`` is a
                         schema error, and a custom ``provenance`` must keep
                         the ``host-enforced:`` prefix — no opt-out, no
                         relabeling.
* ``tier``             — ``heavy`` | ``standard`` (the model-tier split)
* ``capabilities``     — DECLARED capabilities (``exec:``/``read:``/
                         ``write:``/``env:`` entries) checked by the runtime
                         pre-flight probe before every run (DR-02
                         compensating control #1)
* ``activation``       — the LAZY activation trigger: ``first_run`` (default),
                         ``explicit``, or ``on_event`` + ``event``
* ``op_kind``          — ``run`` | ``mutate`` (the DR-01 enum). A ``mutate``
                         op additionally declares ``write_scope`` and refuses
                         to run without a valid single-use confirm token and
                         in-scope write targets (DR-02 controls #2/#3).

DECLARE-THEN-RESOLVE: :func:`build_dispatch` validates + resolves every
manifest into a dispatch table WITHOUT executing or importing any skill code
— discovery is pure data. Skill ACTIVATION (reading the skill's ``SKILL.md``
protocol + running the capability pre-flight probe) is LAZY and fires only on
the manifest's declared trigger; activation still never runs the host.

THE WAVE-2 SEAM LIVES HERE NOW: every dispatched op — done, failed, or
refused, ``mutate`` included — auto-appends the 7-field skeleton entry via
``foundry_journal.journal_run_writeback`` (the ONE sanctioned writer; this
module never writes a journal file itself). Capture is a by-product of the
run, zero author action.

WAVE 11 (Phase 8 — safety before scale): the PER-HOST concurrent-skill-run
budget is enforced HERE, in the one seam every dispatched op passes through,
BEFORE default-on fan-out. At most :func:`concurrency_budget` ops execute at
once host-wide; an over-budget dispatch is REFUSED honestly (and journaled),
never silently queued. The process-lifecycle reaper family
(``foundry_decisions.NATIVE_BUILTINS`` — zombie-hunter et al.) stays a NATIVE
built-in: :func:`validate_manifest` refuses to register those names as
manifest skill actions.

Stdlib only (Anchor's no-dep rule) + the product seams ``paths`` /
``foundry_decisions`` / ``foundry_journal``.
"""

import json
import os
import shlex
import shutil
import subprocess
import threading
import time
from pathlib import Path

import paths as _paths
import foundry_decisions as _fd
import foundry_journal as _fj


# ── Constants / seams ────────────────────────────────────────────────────────

#: The per-skill manifest filename under a skill dir (Wave 9's gen_manifest
#: writes this file; :func:`discover_manifests` scans for it).
MANIFEST_FILENAME = "manifest.json"

#: Bump when a fix changes what a correct manifest looks like.
MANIFEST_SCHEMA_VERSION = 1

#: The op kinds come from the Wave-1 decision module (DR-01) — the runner is a
#: CONSUMER of the decision, so a drifted enum breaks loudly here.
OP_KINDS = tuple(_fd.OP_KINDS)
OP_RUN, OP_MUTATE = "run", "mutate"

#: The two model tiers (HEAVY = frontier Claude seats, STANDARD = one notch
#: below). The runner only records the tier — model routing lives with the
#: engine drivers — but an out-of-enum tier is a schema error.
TIERS = ("heavy", "standard")

#: Lazy-activation triggers. ``first_run``: the first dispatched op activates.
#: ``explicit``: only :func:`activate_skill` activates. ``on_event``: only a
#: matching :func:`notify_event` activates.
ACTIVATION_TRIGGERS = ("first_run", "explicit", "on_event")

#: Declared-capability kinds the pre-flight probe understands.
CAPABILITY_KINDS = ("exec", "read", "write", "env")

#: Output-contract formats.
OUTPUT_FORMATS = ("json", "text")

#: Host-enforced journaling: a manifest journal spec may extend, never dodge.
PROVENANCE_PREFIX = "host-enforced:"

#: Env var overriding the per-run host timeout (seconds) for EVERY skill;
#: else the manifest's ``timeout_s``; else this default (generous, like
#: gandalf's — agentic hosts are slow and the runner never blocks a render).
TIMEOUT_ENV = "ANCHOR_SKILL_RUNNER_TIMEOUT"
DEFAULT_TIMEOUT = 900.0

#: How many bytes of a skill's SKILL.md the activation step reads (bounded,
#: same cap as the gandalf adapter it generalizes).
_MAX_SKILL_BYTES = 64 * 1024

#: Confirm tokens are single-use and expire (a stale approval is no approval).
CONFIRM_TOKEN_TTL_S = 3600.0

#: Wave 11 — the per-host concurrent-skill-run budget. Env override (floor 1);
#: a missing/invalid value falls back to the default. Kept deliberately small:
#: fan-out earns scale AFTER the safety envelope, never before.
MAX_CONCURRENT_ENV = "ANCHOR_SKILL_RUNNER_MAX_CONCURRENT"
DEFAULT_MAX_CONCURRENT = 3

#: Wave 11 — the process-lifecycle reaper family stays NATIVE (in-process);
#: these names may never be manifest-registered as skill actions. Consumed
#: from the Wave-1 decision module so the decision sits on the dispatch path.
NATIVE_BUILTINS = tuple(_fd.NATIVE_BUILTINS)


# ── Confirm tokens (the DR-02 mutate gate) ───────────────────────────────────

#: token → {"skill", "issued_ts", "ttl_s"}; mutated only under the lock.
_CONFIRM_TOKENS: dict = {}
_CONFIRM_LOCK = threading.Lock()

#: run-id uniqueness counter (two ops in the same millisecond must not share
#: a journal entry id).
_RUN_SEQ = [0]
_RUN_SEQ_LOCK = threading.Lock()


def issue_confirm_token(skill, *, ttl_s=CONFIRM_TOKEN_TTL_S) -> str:
    """Mint a single-use confirm token authorizing ONE ``mutate`` op of
    ``skill``. The human approval path (GUI / control plane) calls this;
    :func:`run_op` consumes the token exactly once."""
    token = "confirm-" + os.urandom(16).hex()
    with _CONFIRM_LOCK:
        _CONFIRM_TOKENS[token] = {
            "skill": str(skill),
            "issued_ts": time.time(),
            "ttl_s": float(ttl_s),
        }
    return token


def _peek_confirm_token(token, skill):
    """Validate (without consuming) → ``None`` if valid, else the refusal reason."""
    if not token:
        return "confirm-token-missing"
    with _CONFIRM_LOCK:
        rec = _CONFIRM_TOKENS.get(token)
        if rec is None:
            return "confirm-token-invalid"
        if rec["skill"] != str(skill):
            return "confirm-token-wrong-skill"
        if time.time() - rec["issued_ts"] > rec["ttl_s"]:
            _CONFIRM_TOKENS.pop(token, None)
            return "confirm-token-expired"
    return None


def _consume_confirm_token(token) -> None:
    with _CONFIRM_LOCK:
        _CONFIRM_TOKENS.pop(token, None)


# ── The per-host concurrency budget (Wave 11 — safety before scale) ──────────

#: In-flight dispatched-op count, host-wide; mutated only under the lock.
_INFLIGHT = {"count": 0}
_INFLIGHT_LOCK = threading.Lock()


def concurrency_budget() -> int:
    """The per-host budget: how many runner ops may execute CONCURRENTLY.

    ``ANCHOR_SKILL_RUNNER_MAX_CONCURRENT`` overrides (floor 1 — a budget can
    throttle fan-out, never wedge the runner shut); a missing / invalid /
    non-positive value falls back to :data:`DEFAULT_MAX_CONCURRENT`.
    """
    raw = (os.environ.get(MAX_CONCURRENT_ENV) or "").strip()
    if raw:
        try:
            n = int(raw)
        except ValueError:
            n = 0
        if n >= 1:
            return n
    return DEFAULT_MAX_CONCURRENT


def inflight_runs() -> int:
    """How many dispatched ops are executing RIGHT NOW (host-wide)."""
    with _INFLIGHT_LOCK:
        return _INFLIGHT["count"]


def _acquire_run_slot():
    """Try to take one budget slot → ``(ok, refusal_reason)``.

    Refusal is honest and immediate — the runner never queues an over-budget
    op (a silent queue would hide the pressure the budget exists to surface).
    """
    budget = concurrency_budget()
    with _INFLIGHT_LOCK:
        if _INFLIGHT["count"] >= budget:
            return False, ("concurrency-budget-exceeded:%d/%d"
                           % (_INFLIGHT["count"], budget))
        _INFLIGHT["count"] += 1
    return True, None


def _release_run_slot() -> None:
    with _INFLIGHT_LOCK:
        if _INFLIGHT["count"] > 0:
            _INFLIGHT["count"] -= 1


# ── Manifest: load / validate / normalize ────────────────────────────────────

def _split_cmd(raw: str) -> list:
    """Split a command string into argv, surviving Windows backslash paths
    (same semantics as ``job_runner._shlex_split`` — posix=False on nt)."""
    return shlex.split(raw, posix=(os.name != "nt"))


def load_skill_manifest(skill_dir):
    """Read ``<skill_dir>/manifest.json`` → the manifest dict (with
    ``skill_dir`` defaulted to the dir it was read from). Raises ``ValueError``
    on a missing/unparseable file — a declared skill with a broken manifest
    must break loudly, not vanish silently."""
    d = Path(skill_dir)
    p = d / MANIFEST_FILENAME
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError as e:
        raise ValueError("manifest unreadable at %s: %s" % (p, e))
    try:
        manifest = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        raise ValueError("manifest unparseable at %s: %s" % (p, e))
    if not isinstance(manifest, dict):
        raise ValueError("manifest at %s is not a JSON object" % p)
    manifest.setdefault("skill_dir", str(d))
    return manifest


def discover_manifests(skills_root) -> list:
    """Scan ``<skills_root>/*/manifest.json`` → the declared manifests
    (sorted by dir name). Pure data discovery — no skill code runs."""
    root = Path(skills_root)
    out = []
    if not root.is_dir():
        return out
    for child in sorted(root.iterdir()):
        if child.is_dir() and (child / MANIFEST_FILENAME).is_file():
            out.append(load_skill_manifest(child))
    return out


def validate_manifest(manifest) -> list:
    """Return a list of schema problems (empty = a valid Wave-3 manifest).

    This is THE schema Wave 9's ``foundry.gen_manifest`` validates against
    before writing a manifest to disk.
    """
    problems = []
    if not isinstance(manifest, dict):
        return ["manifest is not a dict"]

    skill = manifest.get("skill")
    if not (isinstance(skill, str) and skill.strip()):
        problems.append("missing/empty skill name")
    elif skill.strip().lower().replace("-", "_") in NATIVE_BUILTINS:
        # Wave 11: zombie-hunter/reaper stay in-process — kill authority never
        # moves behind the skill-action surface it polices.
        problems.append("skill %r is a native built-in — the process-"
                        "lifecycle reaper is never manifest-registered"
                        % skill)

    if not str(manifest.get("skill_dir") or "").strip():
        problems.append("missing skill_dir")

    kind = manifest.get("op_kind")
    if kind not in OP_KINDS:
        problems.append("op_kind %r not in OP_KINDS %r" % (kind, OP_KINDS))

    host_cmd = manifest.get("host_cmd")
    if isinstance(host_cmd, str):
        if not host_cmd.strip():
            problems.append("empty host_cmd")
    elif isinstance(host_cmd, (list, tuple)):
        if not host_cmd or not all(
                isinstance(a, str) and a.strip() for a in host_cmd):
            problems.append("host_cmd argv must be non-empty strings")
    else:
        problems.append("missing host_cmd (command string or argv list)")

    contract = manifest.get("output_contract")
    if not isinstance(contract, dict):
        problems.append("missing output_contract")
    else:
        fmt = contract.get("format")
        if fmt not in OUTPUT_FORMATS:
            problems.append("output_contract.format %r not in %r"
                            % (fmt, OUTPUT_FORMATS))
        keys = contract.get("required_keys")
        if keys is not None:
            if fmt != "json":
                problems.append("output_contract.required_keys needs "
                                "format=json")
            elif not (isinstance(keys, (list, tuple)) and all(
                    isinstance(k, str) and k for k in keys)):
                problems.append("output_contract.required_keys must be "
                                "a list of key names")

    panel = manifest.get("panel")
    if not (isinstance(panel, dict)
            and isinstance(panel.get("title"), str) and panel["title"].strip()):
        problems.append("missing panel meta (dict with a title)")

    jspec = manifest.get("journal")
    if not isinstance(jspec, dict):
        problems.append("missing journal spec")
    else:
        if jspec.get("enabled") is False:
            problems.append("journal.enabled=false forbidden: journaling is "
                            "host-enforced, a manifest cannot opt out")
        prov = jspec.get("provenance")
        if prov is not None and not (isinstance(prov, str)
                                     and prov.startswith(PROVENANCE_PREFIX)):
            problems.append("journal.provenance must keep the %r prefix"
                            % PROVENANCE_PREFIX)

    if manifest.get("tier") not in TIERS:
        problems.append("tier %r not in %r" % (manifest.get("tier"), TIERS))

    caps = manifest.get("capabilities")
    if not isinstance(caps, (list, tuple)):
        problems.append("missing capabilities (declare a list; may be empty)")
    else:
        for cap in caps:
            kind_ok = (isinstance(cap, str) and ":" in cap
                       and cap.split(":", 1)[0] in CAPABILITY_KINDS
                       and cap.split(":", 1)[1].strip())
            if not kind_ok:
                problems.append("undeclared capability form: %r (use "
                                "kind:target, kind in %r)"
                                % (cap, CAPABILITY_KINDS))

    activation = manifest.get("activation")
    if not isinstance(activation, dict):
        problems.append("missing activation spec")
    else:
        trig = activation.get("trigger")
        if trig not in ACTIVATION_TRIGGERS:
            problems.append("activation.trigger %r not in %r"
                            % (trig, ACTIVATION_TRIGGERS))
        elif trig == "on_event" and not str(
                activation.get("event") or "").strip():
            problems.append("activation.trigger=on_event needs an event name")

    if kind == OP_MUTATE:
        scope = manifest.get("write_scope")
        if isinstance(scope, str):
            scope = [scope] if scope.strip() else []
        if not (isinstance(scope, (list, tuple)) and scope and all(
                isinstance(s, str) and s.strip() for s in scope)):
            problems.append("mutate op needs a non-empty declared write_scope")

    timeout_s = manifest.get("timeout_s")
    if timeout_s is not None:
        try:
            if float(timeout_s) <= 0:
                problems.append("timeout_s must be positive")
        except (TypeError, ValueError):
            problems.append("timeout_s must be a number")

    return problems


def _resolve_host_argv(manifest) -> list:
    """Resolve ``host_cmd`` to an argv list with ``{skill_dir}`` placeholders
    substituted. Resolution is string work only — nothing is executed."""
    skill_dir = str(manifest["skill_dir"])
    host_cmd = manifest["host_cmd"]
    if isinstance(host_cmd, str):
        argv = _split_cmd(host_cmd)
    else:
        argv = [str(a) for a in host_cmd]
    return [a.replace("{skill_dir}", skill_dir) for a in argv]


# ── Declare-then-resolve dispatch ────────────────────────────────────────────

def build_dispatch(manifests) -> dict:
    """Build the dispatch table from declared manifests → ``{skill: entry}``.

    DECLARE-THEN-RESOLVE: every manifest is validated (loudly — an invalid or
    duplicate declaration raises ``ValueError``) and resolved into a dispatch
    entry from its DATA alone. No skill code is imported, no host process is
    spawned, no SKILL.md is read — that is activation, and activation is lazy.
    """
    table: dict = {}
    problems = []
    for i, manifest in enumerate(manifests):
        errs = validate_manifest(manifest)
        if errs:
            name = (manifest or {}).get("skill") if isinstance(manifest, dict) \
                else None
            label = name or ("manifest[%d]" % i)
            problems.extend("%s: %s" % (label, e) for e in errs)
            continue
        name = manifest["skill"].strip()
        if name in table:
            problems.append("%s: duplicate skill declaration" % name)
            continue
        activation = dict(manifest["activation"])
        scope = manifest.get("write_scope")
        if isinstance(scope, str):
            scope = [scope]
        table[name] = {
            "skill": name,
            "manifest": manifest,
            "op_kind": manifest["op_kind"],
            "tier": manifest["tier"],
            "argv": _resolve_host_argv(manifest),
            "skill_dir": str(manifest["skill_dir"]),
            "output_contract": dict(manifest["output_contract"]),
            "panel": dict(manifest["panel"]),
            "journal_spec": dict(manifest["journal"]),
            "capabilities": tuple(manifest["capabilities"]),
            "activation": activation,
            "write_scope": tuple(str(s) for s in (scope or ())),
            "activated": False,
            "protocol": None,      # SKILL.md text — read at ACTIVATION only
            "preflight": None,     # last probe result — filled at activation/run
        }
    if problems:
        raise ValueError("invalid skill declaration(s): " + "; ".join(problems))
    return table


# ── Lazy activation + the runtime pre-flight probe ──────────────────────────

def preflight_probe(entry) -> list:
    """Probe the DECLARED capabilities against the live host → problems list.

    DR-02 compensating control #1: permissions are advisory in v2, so the one
    honest check is that every declared capability is actually satisfiable
    RIGHT NOW — before the host runs, never after. Read-only probing: nothing
    is executed, created, or written.
    """
    problems = []
    skill_dir = Path(entry["skill_dir"])
    if not skill_dir.is_dir():
        problems.append("skill_dir missing: %s" % skill_dir)
    for cap in entry["capabilities"]:
        kind, _, target = cap.partition(":")
        target = target.strip()
        if kind == "exec":
            p = Path(target)
            found = shutil.which(target) or (
                str(p) if (p.is_absolute() and p.is_file()) else None)
            if not found:
                problems.append("exec capability unsatisfied: %s" % target)
        elif kind == "read":
            p = Path(target)
            if not p.is_absolute():
                p = skill_dir / target
            if not p.exists():
                problems.append("read capability unsatisfied: %s" % target)
        elif kind == "write":
            p = Path(target)
            if not p.is_absolute():
                p = skill_dir / target
            probe_dir = p if p.is_dir() else p.parent
            if not (probe_dir.is_dir() and os.access(str(probe_dir), os.W_OK)):
                problems.append("write capability unsatisfied: %s" % target)
        elif kind == "env":
            if not (os.environ.get(target) or "").strip():
                problems.append("env capability unsatisfied: %s" % target)
        else:  # unreachable for a validated manifest; honest anyway
            problems.append("unknown capability kind: %s" % cap)
    return problems


def _activate(entry) -> None:
    """Activate one dispatch entry: read the skill's own ``SKILL.md`` protocol
    (bounded; honest empty on absence, like the gandalf adapter) and run the
    pre-flight probe. Activation NEVER executes the host."""
    protocol = ""
    try:
        p = Path(entry["skill_dir"]) / "SKILL.md"
        if p.is_file():
            protocol = p.read_text(
                encoding="utf-8", errors="replace")[:_MAX_SKILL_BYTES]
    except OSError:
        protocol = ""
    entry["protocol"] = protocol
    entry["preflight"] = preflight_probe(entry)
    entry["activated"] = True


def activate_skill(dispatch, skill):
    """The EXPLICIT activation path (a direct operator/host command).

    Returns the activated entry, or ``None`` for an unknown skill."""
    entry = dispatch.get(str(skill))
    if entry is None:
        return None
    if not entry["activated"]:
        _activate(entry)
    return entry


def notify_event(dispatch, event) -> list:
    """Fire one activation event → the skill names it activated.

    Only entries that DECLARED ``on_event`` with this exact event name
    activate; every other entry (other events, other triggers) is untouched —
    lazy activation fires only on the declared trigger."""
    activated = []
    ev = str(event)
    for name, entry in dispatch.items():
        if entry["activated"]:
            continue
        act = entry["activation"]
        if act.get("trigger") == "on_event" and str(act.get("event")) == ev:
            _activate(entry)
            activated.append(name)
    return activated


# ── Write-scope enforcement (mutate) ─────────────────────────────────────────

def _in_write_scope(target, scopes) -> bool:
    """True iff ``target`` resolves inside one of the declared scope roots
    (case-normalized for Windows; a scope root itself is in scope)."""
    try:
        t = os.path.normcase(str(Path(target).resolve()))
    except (OSError, ValueError):
        return False
    for scope in scopes:
        try:
            s = os.path.normcase(str(Path(scope).resolve()))
        except (OSError, ValueError):
            continue
        if t == s or t.startswith(s.rstrip("\\/") + os.sep):
            return True
    return False


# ── Host execution (the skill's OWN host; injectable for tests) ──────────────

def _timeout_for(entry) -> float:
    raw = (os.environ.get(TIMEOUT_ENV) or "").strip()
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    try:
        t = entry["manifest"].get("timeout_s")
        if t:
            return float(t)
    except (TypeError, ValueError):
        pass
    return DEFAULT_TIMEOUT


def _execute_host(entry, payload):
    """Run the manifest's host command, payload as JSON on stdin → the tuple
    ``(stdout_text, reason)``; ``reason`` is the honest failure tag (host
    absent / spawn failed / timeout / non-zero exit) and ``None`` on success.
    Mirrors the gandalf adapter's Stage-B posture. Never raises."""
    argv = list(entry["argv"])
    stdin_text = json.dumps(payload, ensure_ascii=False, default=str) \
        if payload is not None else ""
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_paths.NO_WINDOW,
        )
    except FileNotFoundError:
        return None, "host-unavailable"
    except (OSError, subprocess.SubprocessError):
        return None, "host-spawn-failed"
    try:
        stdout, stderr = proc.communicate(input=stdin_text,
                                          timeout=_timeout_for(entry))
    except subprocess.TimeoutExpired:
        try:
            import proc_probe
            proc_probe.tree_kill(proc.pid)
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        return None, "host-timeout"
    except Exception:
        return None, "host-spawn-failed"
    if proc.returncode != 0:
        err = (stderr or "").strip().splitlines()
        reason = "host-nonzero-exit"
        if err:
            reason += ":" + err[-1][:200]
        return None, reason
    return stdout or "", None


def _last_json_object(text: str):
    """Parse the LAST balanced top-level JSON object in ``text`` (string/escape
    aware, like the gandalf adapter it generalizes). ``None`` if none parse."""
    if not text:
        return None
    spans = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    spans.append((start, i + 1))
                    start = -1
    for s, e in reversed(spans):
        try:
            obj = json.loads(text[s:e])
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


def _check_output_contract(entry, stdout_text):
    """Apply the manifest's declared output contract → ``(output, reason)``.

    Defensive on the executor seam: an injected executor may hand back a
    parsed dict directly instead of stdout text — accept it as the json
    payload; anything else is coerced to text. Never raises."""
    contract = entry["output_contract"]
    if contract.get("format") == "text":
        return "" if stdout_text is None else str(stdout_text), None
    if isinstance(stdout_text, dict):
        obj = stdout_text
    else:
        obj = _last_json_object(str(stdout_text or ""))
    if not isinstance(obj, dict):
        return None, "output-unparseable"
    missing = [k for k in (contract.get("required_keys") or ()) if k not in obj]
    if missing:
        return None, "output-missing-keys:" + ",".join(missing)
    return obj, None


# ── The Wave-2 journaling seam, moved into the runner ────────────────────────

def _journal_op(entry, run_id, *, started_ts, outcome, verdict, payload,
                write_targets, reason=None, output=None):
    """Auto-journal one dispatched op through the ONE write-back seam.

    Host-enforced and unconditional: done, failed, AND refused ops journal —
    ``mutate`` included (a refused mutation is exactly the audit trail the
    DR-02 downgrade depends on). Best-effort like every journal call:
    never crashes or blocks the op it records."""
    try:
        provenance = (entry["journal_spec"].get("provenance")
                      or (PROVENANCE_PREFIX + "anchor.skill_runner:"
                          + entry["skill"]))
        finished = time.time()
        linkage = {
            "skill": entry["skill"],
            "run_id": run_id,
            "tier": entry["tier"],
            "panel_title": entry["panel"].get("title"),
        }
        if reason:
            linkage["reason"] = str(reason)[:160]
        _fj.journal_run_writeback(
            entry["skill_dir"],
            run_id=run_id,
            operation_kind=entry["op_kind"],
            provenance=provenance,
            model_cost=None,
            inputs={"payload": payload,
                    "write_targets": list(write_targets or ()),
                    "argv": list(entry["argv"])},
            outputs={"output": output, "reason": reason, "outcome": outcome},
            verdict=verdict,
            timing={"started_ts": round(float(started_ts), 3),
                    "finished_ts": round(finished, 3),
                    "duration_s": round(finished - float(started_ts), 3)},
            outcome=outcome,
            linkage=linkage,
        )
    except Exception:
        pass


# ── run_op — the ONE generic execution path ──────────────────────────────────

def _next_run_id(skill) -> str:
    with _RUN_SEQ_LOCK:
        _RUN_SEQ[0] += 1
        seq = _RUN_SEQ[0]
    return "%s-run-%d-%d" % (skill, int(time.time() * 1000), seq)


def _result(entry, run_id, *, ok, outcome, reason=None, output=None,
            started_ts):
    return {
        "ok": bool(ok),
        "skill": entry["skill"],
        "op_kind": entry["op_kind"],
        "run_id": run_id,
        "outcome": outcome,                  # done | failed | refused
        "refused": outcome == "refused",
        "reason": reason,
        "output": output,
        "duration_s": round(time.time() - started_ts, 3),
    }


def run_op(dispatch, skill, *, payload=None, confirm_token=None,
           write_targets=None, executor=None):
    """Dispatch ONE op through the generic runner. Never raises.

    The full gate order, per the Wave-3 contract:

    1. resolve the skill from the dispatch table (unknown → honest refusal);
    2. lazy activation — ``first_run`` activates now; ``explicit``/``on_event``
       entries that never saw their declared trigger are REFUSED, not
       silently activated;
    3. runtime pre-flight probe over the declared capabilities;
    4. the Wave-11 per-host concurrency budget: at most
       :func:`concurrency_budget` ops execute at once — an over-budget
       dispatch is REFUSED honestly, never queued. Checked BEFORE the mutate
       gate so a budget refusal never burns a single-use confirm token;
    5. ``mutate`` only: a valid single-use confirm token AND every declared
       write target inside the manifest's ``write_scope`` — else refused;
    6. execute the skill's own host (``executor`` is the injectable seam;
       default = the manifest's ``host_cmd`` subprocess);
    7. apply the declared output contract;
    8. journal the op — done, failed, or refused — through the Wave-2 seam.

    Returns the result record (``ok`` / ``outcome`` / ``reason`` / ``output``).
    """
    entry = dispatch.get(str(skill))
    if entry is None:
        return {
            "ok": False, "skill": str(skill), "op_kind": None,
            "run_id": None, "outcome": "refused", "refused": True,
            "reason": "unknown-skill:%s" % skill, "output": None,
            "duration_s": 0.0,
        }
    started = time.time()
    run_id = _next_run_id(entry["skill"])

    def _refuse(reason):
        _journal_op(entry, run_id, started_ts=started, outcome="refused",
                    verdict=reason, payload=payload,
                    write_targets=write_targets, reason=reason)
        return _result(entry, run_id, ok=False, outcome="refused",
                       reason=reason, started_ts=started)

    # 2 — lazy activation on the declared trigger only.
    if not entry["activated"]:
        if entry["activation"].get("trigger") == "first_run":
            _activate(entry)
        else:
            return _refuse("not-activated:trigger=%s"
                           % entry["activation"].get("trigger"))

    # 3 — runtime pre-flight probe (re-run per op: the host changes under us).
    problems = preflight_probe(entry)
    entry["preflight"] = problems
    if problems:
        return _refuse("preflight:" + "; ".join(problems))

    # 4 — the Wave-11 per-host concurrency budget (Phase 8: safety before
    # scale). Checked BEFORE the mutate gate so an over-budget dispatch never
    # burns a single-use confirm token; over budget → an honest, journaled
    # refusal — default-on fan-out must degrade loudly, never queue silently.
    slot_ok, slot_reason = _acquire_run_slot()
    if not slot_ok:
        return _refuse(slot_reason)
    try:
        # 5 — the mutate gate: confirm token + declared write-scope.
        if entry["op_kind"] == OP_MUTATE:
            token_problem = _peek_confirm_token(confirm_token, entry["skill"])
            if token_problem:
                return _refuse(token_problem)
            targets = list(write_targets or ())
            if not targets:
                return _refuse("write-targets-undeclared")
            for target in targets:
                if not _in_write_scope(target, entry["write_scope"]):
                    return _refuse("write-scope-violation:%s" % target)
            # Everything checked — the approval is spent by the execution.
            _consume_confirm_token(confirm_token)

        # 6 — execute the skill's OWN host (never imported, only spawned).
        if executor is not None:
            try:
                stdout_text, reason = executor(entry, payload), None
            except Exception as e:
                stdout_text, reason = None, "executor-failed:%s" % e
        else:
            stdout_text, reason = _execute_host(entry, payload)

        # 7 — the declared output contract.
        output = None
        if reason is None:
            output, reason = _check_output_contract(entry, stdout_text)

        outcome = "done" if reason is None else "failed"
        verdict = reason if reason else "ok"
        if isinstance(output, dict) and output.get("verdict"):
            verdict = str(output["verdict"])

        # 8 — the Wave-2 seam, now living in the runner: capture is a
        # by-product.
        _journal_op(entry, run_id, started_ts=started, outcome=outcome,
                    verdict=verdict, payload=payload,
                    write_targets=write_targets, reason=reason, output=output)

        return _result(entry, run_id, ok=(reason is None), outcome=outcome,
                       reason=reason, output=output, started_ts=started)
    finally:
        # The slot is released whatever happened — a refused mutate, a failed
        # host, a done run: the budget can never leak shut.
        _release_run_slot()
