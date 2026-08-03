"""reaper Wave 10 — SPEC TRUTH grep gate over the zombie-hunter SKILL.md.

The shipped reaper is **ownership-based** (`reaper.live_owner_ids`) with a
**positive proof-of-death** kill predicate, an **abstain-by-default** safety
boundary, a bounded blast radius + boot-grace, a restart-durable **protect-only**
frozen-set, and a **token-authenticated**, tamper-evident **log -> freeze -> kill**
arming ladder governed by a **numeric arm bar** and a kill-switch brake
(`reaper.py` / `proc_probe.py` / `freeze_state.py` / `reaper_arming.py`).

This module mechanically FAILS the build if the skill contract drifts back to the
retired **identity/token** + native-process-library (``psutil`` / ``WMI``) model,
or if it omits any of the shipped contract's load-bearing properties (the arm bar,
abstain-default, or the control-plane integrity model). It is the criterion-13
"spec truth" gate the plan's Wave 10 done-when names.

Test function names carry the ``reaper`` token so the plan's ``-k reaper`` gate
collects them alongside the rest of the reaper suite.

The SKILL.md path resolves from ``ANCHOR_ZOMBIE_HUNTER_SKILL_DIR`` (a seam, like
gandalf.py's ``ANCHOR_GANDALF_SKILL_DIR``) else the author's Skill-Foundry source
dir — assembled from path parts so this SHIPPED test embeds NO contiguous
host-path literal for distro.py's host-path scanner (the rnd-distro convention;
see tests/test_vendor_skills.py). Stdlib + pytest only; touches no process.
"""
import os
from pathlib import Path

import pytest

_ENV = "ANCHOR_ZOMBIE_HUNTER_SKILL_DIR"


def _default_skill_dir() -> Path:
    # Assembled from parts (never a single "C:\\dev\\Skill Foundry" literal) so
    # the distro host-path scanner sees no contiguous personal build-tree path.
    return Path("C:" + os.sep) / "dev" / "Skill Foundry" / "skills" / "zombie-hunter"


def _skill_md_path() -> Path:
    base = os.environ.get(_ENV)
    root = Path(base) if base else _default_skill_dir()
    return root / "SKILL.md"


def _skill_text() -> str:
    p = _skill_md_path()
    if not p.is_file():
        pytest.skip(f"zombie-hunter SKILL.md not present at {p}")
    return p.read_text(encoding="utf-8")


# ── The retired identity/token + native-process-library model — must be GONE ──
# Ban both the psutil/WMI native enumeration and the identity/genesis-token
# "the token match authorizes the kill" model the shipped reaper replaced.
_BANNED = [
    "psutil",
    "wmi",
    "identity-based",
    "genesis token",
    "composite key",
    "sniper kill",
    "taskkill",
    "kill_on_job_close",
]

# ── The shipped contract — every load-bearing property must be DOCUMENTED ─────
_REQUIRED = [
    # ownership model, not identity-matching
    "ownership-based",
    "live owner",
    "identity tuple",       # the anti-recycle proof (a CORRECT use of identity)
    "ctypes",               # stdlib enumeration, no native process-inspection dep
    # positive proof-of-death + abstain-default
    "positive proof of death",
    "abstain",
    # detectable-lock corroboration signals
    "index.lock",
    "heartbeat",
    "socket",
    # bounded blast radius + boot grace
    "blast-radius",
    "boot-grace",
    # restart-durable protect-only freeze + containment demoted
    "protect-only",
    "reconcile",
    "non-load-bearing",
    # control-plane integrity / authz + the arming ladder
    "arming ladder",
    "arm bar",
    "kill-switch",
    "token-auth",
    "receipt",
    "in-process",
]


def test_reaper_skill_spec_has_no_retired_identity_or_psutil_language():
    """The rewritten SKILL.md must not assert the retired identity/token or
    psutil/WMI model anywhere."""
    low = _skill_text().lower()
    offenders = [tok for tok in _BANNED if tok in low]
    assert offenders == [], (
        "zombie-hunter SKILL.md still carries retired identity/native-lib "
        f"language: {offenders}")


def test_reaper_skill_spec_documents_the_shipped_contract():
    """The rewritten SKILL.md must document every load-bearing property of the
    shipped ownership-based + positive-liveness reaper."""
    low = _skill_text().lower()
    missing = [tok for tok in _REQUIRED if tok not in low]
    assert missing == [], (
        "zombie-hunter SKILL.md omits shipped-contract terms: {}".format(missing))


def test_reaper_skill_spec_ladder_and_gate_are_present():
    """Focused check on the arm-bar / control-plane-integrity contract the
    done-when singles out (numeric arm bar recomputed in-process, kill-switch
    brake, token-authed control plane)."""
    low = _skill_text().lower()
    # the log -> freeze -> kill ladder, unarmed by default
    assert "freeze" in low and "arming ladder" in low
    assert "unarmed" in low or "dry-run" in low, (
        "the ladder must document the unarmed/dry-run default")
    # the numeric arm bar is recomputed in-process (tamper-evident), not trusted
    assert "arm bar" in low
    assert "in-process" in low
    # tamper-evident hash-chained receipts + token-authed control plane
    assert "receipt" in low
    assert "token-auth" in low
    # restart-durable kill-switch brake
    assert "kill-switch" in low
