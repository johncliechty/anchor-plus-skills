"""Skill Foundry v2 — Phase 8 "safety before scale" (Wave 11).

Fan-out does not become default-on until the safety envelope is armed. This
module delivers the Anchor-side keystones the frozen plan names:

1. **Arm the reaper to >= FREEZE** — :func:`arm_reaper_to_freeze` is the one
   sanctioned Wave-11 arming path. It RE-CHECKS the 2026-07-05 fail-deadly
   finding first (:func:`recheck_fail_deadly`) and only then delegates to
   :func:`reaper_arming.arm` — token-authed (``paths.auth_ok``),
   kill-switch-brake-checked, and gated by the tamper-evident arm gate
   (chain-verified receipts + the consecutive-clean-sweep bar + a fresh live
   probe). It targets the FREEZE rung ONLY: this path can NEVER arm the KILL
   rung (kill is earned later on lived zero-false-freeze evidence), and at
   FREEZE the armed sweep never kills-on-uncertainty — a degraded/``None``
   snapshot abstains everything and a corroborated positive signal abstains
   that session.

2. **The fail-deadly finding, retired-in-code** — :func:`recheck_fail_deadly`
   re-verifies the 2026-07-05 finding (fail-deadly fallback #1 of the
   safe-to-arm reaper build: a classify FAULT at a call site resolving to
   "kill"/freeze instead of OWNED/alive) is RETIRED and stays retired: the
   retired call-site patterns must be absent, the abstain-safe replacements
   present, and a live behavioral probe proves an uncertain sweep ABSTAINS
   and acts on nothing. Arming REFUSES while the finding is open — the
   fail-deadly path is retired or the arm is explicitly bounded to LOG.

3. **Zombie-hunter stays a native built-in** —
   :func:`reaper_is_native_builtin` proves the process-lifecycle reaper is
   wired as an IN-PROCESS subsystem (boot daemon + importable modules) and
   that the generic runner REFUSES to register any
   :data:`foundry_decisions.NATIVE_BUILTINS` name as a manifest skill action.

(The remaining Phase-8 deliverable — the per-host concurrent-skill-run
budget — lives IN the generic runner itself, per the plan's "enforced IN the
generic runner": ``skill_runner.concurrency_budget`` and ``run_op``'s budget
gate.)

Stdlib only + the product seams ``foundry_decisions`` / ``reaper`` /
``reaper_arming``.
"""

from __future__ import annotations

from pathlib import Path

import foundry_decisions as _fd
import reaper as _reaper
import reaper_arming as _arm


#: Where the audited call sites live (the reaper build's five call sites —
#: banner, Swarm & Owner View, brief, armed-daemon provider, boot reconcile —
#: are all in the GUI server module).
CODE_DIR = Path(__file__).resolve().parent
CALL_SITE_SOURCE = "anchor_gui.py"

#: The finding this wave re-checks before arming (frozen-plan reference).
FAIL_DEADLY_FINDING = (
    "2026-07-05 fail-deadly fallback #1: a classify FAULT at a call site "
    "resolved to 'kill'/freeze instead of OWNED/alive"
)

#: The exact retired fallback patterns (the same set the reaper build's
#: stub gate locks) — a reappearance RE-OPENS the finding.
RETIRED_PATTERNS = (
    '"kill" if (sid and sid not in live_ids)',
    '"kill" if sid not in live_ids',
    "is_orphaned = (sid not in live_ids)",
)

#: The abstain-safe replacements that must REMAIN on the call-site path.
REQUIRED_MARKERS = (
    "reaper.owner_ids_or_abstain(",
    "reaper.live_pid_ids(",
)

#: A synthetic session id for the behavioral probe (never a real session).
_PROBE_SID = "__fail_deadly_probe__"


def _behavioral_uncertainty_probe(problems) -> None:
    """The explicit BOUND on the fail-deadly path, proven live: an uncertain
    (``None``-snapshot) sweep must ABSTAIN everything and act on NOTHING.

    Pure classification: ``apply=False`` + ``write_receipts=False`` — no
    process is touched, no receipt appended, no registry mutated.
    """
    probe_rec = {"session_id": _PROBE_SID, "status": "running", "pid": None}
    try:
        report = _arm.armed_sweep([probe_rec], None, apply=False,
                                  write_receipts=False)
    except Exception as e:
        problems.append("uncertainty probe failed: %r" % (e,))
        return
    if not report.get("degraded"):
        problems.append("a None snapshot was not honestly reported degraded")
    if report.get("frozen") or report.get("killed"):
        problems.append("an uncertain sweep acted destructively "
                        "(the fail-deadly path is OPEN)")
    if _PROBE_SID not in (report.get("abstained") or ()):
        problems.append("an uncertain sweep did not ABSTAIN the session")
    # The shared armed-daemon provider must fail-safe the same way: an
    # unobservable snapshot treats every running session as OWNED.
    try:
        owned = _reaper.owner_ids_or_abstain(None, [probe_rec])
    except Exception:
        owned = set()
    if _PROBE_SID not in owned:
        problems.append("owner_ids_or_abstain no longer fail-safes to OWNED "
                        "on an unobservable snapshot")


def recheck_fail_deadly(*, source=None) -> dict:
    """Re-check the 2026-07-05 fail-deadly finding → an honest report dict.

    Returns ``{"finding", "retired", "problems", "checked_patterns"}`` —
    ``retired`` is True only when EVERY check passes;
    :func:`arm_reaper_to_freeze` refuses to arm while it is False. ``source``
    injects the call-site source text (tests); the default reads the live
    ``anchor_gui.py``.
    """
    problems: list = []
    src = source
    if src is None:
        try:
            src = (CODE_DIR / CALL_SITE_SOURCE).read_text(encoding="utf-8")
        except OSError as e:
            src = None
            problems.append("call-site source unreadable: %r" % (e,))
    if src is not None:
        for pat in RETIRED_PATTERNS:
            if pat in src:
                problems.append(
                    "retired fail-deadly fallback re-appeared: %s" % pat)
        for marker in REQUIRED_MARKERS:
            if marker not in src:
                problems.append(
                    "abstain-safe replacement missing: %s" % marker)
    _behavioral_uncertainty_probe(problems)
    return {
        "finding": FAIL_DEADLY_FINDING,
        "retired": not problems,
        "problems": problems,
        "checked_patterns": list(RETIRED_PATTERNS),
    }


def arm_reaper_to_freeze(provided_token, *, snapshot=None, records=None,
                         min_sweeps=None, now=None, probe=None,
                         recheck=None) -> dict:
    """Arm the reaper to the FREEZE rung — the Wave-11 sanctioned arm path.

    The safety envelope, none of it weakened here:

    * the 2026-07-05 fail-deadly finding is RE-CHECKED first; an open finding
      REFUSES the arm with NO state change;
    * the arm itself is :func:`reaper_arming.arm` — token-authed
      (``paths.auth_ok``), refused while the ``.anchor/reaper.disarmed``
      kill-switch brake is engaged, and gated by
      :func:`reaper_arming.evaluate_arm_gate` (chain-verified receipts + the
      consecutive-clean-sweep bar + a fresh live probe);
    * the target is :data:`reaper_arming.TIER_FREEZE` ONLY — this path can
      never arm the KILL rung, and at FREEZE the armed sweep never kills:
      uncertainty abstains (re-verified above), a corroborated positive
      signal abstains that session, and every freeze is reversible + bounded
      by the auto-thaw watchdog.

    ``recheck`` injects a pre-computed :func:`recheck_fail_deadly` report
    (tests); the default recomputes it live. Returns the arm-result dict with
    ``target_tier`` + the ``fail_deadly`` report attached.
    """
    check = recheck if recheck is not None else recheck_fail_deadly()
    if not check.get("retired"):
        return {
            "ok": False,
            "changed": False,
            "tier": _arm.persisted_tier(),
            "target_tier": _arm.TIER_FREEZE,
            "error": "fail-deadly finding not retired: "
                     + "; ".join(str(p) for p in (check.get("problems") or ())),
            "fail_deadly": check,
        }
    out = dict(_arm.arm(provided_token, snapshot=snapshot, records=records,
                        min_sweeps=min_sweeps, now=now, probe=probe))
    out["target_tier"] = _arm.TIER_FREEZE
    out["fail_deadly"] = check
    return out


def reaper_is_native_builtin() -> dict:
    """Prove the process-lifecycle reaper stays a NATIVE BUILT-IN.

    Three checks, all honest: (a) the in-process modules import (the native
    wiring is intact); (b) the boot daemon starts the hunter natively
    (``zombie_hunter.start_hunter`` in the server boot path — never a skill
    op); (c) the generic runner REFUSES a manifest that tries to register any
    :data:`foundry_decisions.NATIVE_BUILTINS` name as a skill action. Returns
    ``{"native": bool, "problems": [...]}``. Read-only — never starts,
    freezes, or kills anything.
    """
    problems: list = []
    try:
        import zombie_hunter  # noqa: F401 — the native wiring must import
        import freeze_state   # noqa: F401
    except Exception as e:
        problems.append("native reaper module failed to import: %r" % (e,))
    try:
        src = (CODE_DIR / CALL_SITE_SOURCE).read_text(encoding="utf-8")
        if "zombie_hunter.start_hunter(" not in src:
            problems.append("the boot daemon no longer starts the native "
                            "hunter (zombie_hunter.start_hunter)")
    except OSError as e:
        problems.append("call-site source unreadable: %r" % (e,))
    try:
        import skill_runner as _sr
        for name in _fd.NATIVE_BUILTINS:
            errs = _sr.validate_manifest({"skill": name})
            if not any("native built-in" in str(p) for p in errs):
                problems.append("skill_runner would accept a manifest for "
                                "native built-in %r" % (name,))
    except Exception as e:
        problems.append("runner native-builtin guard probe failed: %r" % (e,))
    return {"native": not problems, "problems": problems}
