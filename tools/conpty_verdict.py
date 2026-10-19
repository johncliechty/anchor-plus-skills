"""ConPTY verdict APPLICATION for W17 (rearch, Wave 19).

W3 recorded the ConPTY-across-processes spike verdict
(:mod:`tools.conpty_spike` → ``planning/rearch-2026-07/SPIKE-CONPTY-VERDICT.json``).
W17 must APPLY that verdict — the plan's fork:

* **YES** — the across-process PTY-ownership architecture is economically
  feasible, so the PTY-adoption follow-on wave is SCHEDULED inside this phase's
  plan (a checked-in, Foreman-ready follow-on scope), and the pre-designed
  graceful drain (:mod:`tools.pre_restart_drain`) remains the SAFETY NET for any
  dashboard restart that lands before adoption ships. No North-Star narrowing is
  required — a YES verdict narrows nothing.
* **NO** — PTYs stay dashboard-owned; the pre-designed drain (close_session park
  + capture_session_docs + warm-resume seed) ships in W17 as the active path and
  the narrowing is recorded via the North-Star amendment path — never silently.
* **UNRUN** — no leg has been recorded yet; the branch is honestly pending (the
  application doc fabricates nothing).

This module reads the recorded verdict, computes the applied branch, and renders
+ diff-stably writes the checked-in application artifact
``planning/rearch-2026-07/CONPTY-VERDICT-APPLICATION.md``. Stdlib only; never
runs the spike, never touches the model, never mutates the verdict artifact.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "planning" / "rearch-2026-07"

VERDICT_JSON_NAME = "SPIKE-CONPTY-VERDICT.json"
APPLICATION_DOC_NAME = "CONPTY-VERDICT-APPLICATION.md"

#: The applied branches, keyed by the overall verdict.
BRANCH_ADOPTION = "adoption"    # YES → schedule the PTY-adoption follow-on wave
BRANCH_DRAIN = "drain"          # NO  → ship the drain + record the narrowing
BRANCH_PENDING = "pending"      # UNRUN → honestly pending

VERDICT_YES = "YES"
VERDICT_NO = "NO"
VERDICT_UNRUN = "UNRUN"


def _verdict_path(path=None) -> Path:
    if path is not None:
        return Path(path)
    return DEFAULT_ARTIFACT_DIR / VERDICT_JSON_NAME


def read_verdict(path=None) -> dict:
    """Read the recorded ConPTY spike verdict and compute the OVERALL verdict.

    Returns ``{legs, ran_legs, overall}`` where ``overall`` is:

    * ``"YES"``   — at least one leg ran and EVERY ran leg is YES;
    * ``"NO"``    — at least one ran leg is NO (a single NO routes to the drain);
    * ``"UNRUN"`` — no leg has been recorded (nothing is fabricated).

    Never raises on a missing/torn artifact — it degrades to ``UNRUN``.
    """
    p = _verdict_path(path)
    legs = {}
    try:
        payload = json.loads(p.read_text(encoding="utf-8"))
        legs = payload.get("legs") or {}
    except (OSError, ValueError):
        legs = {}

    ran = {name: leg for name, leg in legs.items() if leg.get("ran")}
    if not ran:
        overall = VERDICT_UNRUN
    elif any((leg.get("verdict") or "").upper() == VERDICT_NO
             for leg in ran.values()):
        overall = VERDICT_NO
    elif all((leg.get("verdict") or "").upper() == VERDICT_YES
             for leg in ran.values()):
        overall = VERDICT_YES
    else:  # a ran leg with a non-YES/NO verdict is honestly indeterminate
        overall = VERDICT_UNRUN
    return {"legs": legs, "ran_legs": sorted(ran), "overall": overall}


def applied_branch(overall: str) -> str:
    """Map an overall verdict to the applied W17 branch."""
    o = (overall or "").upper()
    if o == VERDICT_YES:
        return BRANCH_ADOPTION
    if o == VERDICT_NO:
        return BRANCH_DRAIN
    return BRANCH_PENDING


# ── the checked-in application doc ───────────────────────────────────────────

def _adoption_body(ran_legs) -> str:
    legs = ", ".join(ran_legs) if ran_legs else "(none)"
    return f"""## Applied branch: PTY ADOPTION (verdict YES)

Both recorded legs ({legs}) answered **YES** against the pre-written W3
acceptance questions (latency bound, re-attach after client death, complexity
budget). The across-process PTY-ownership architecture — owner-side PTY + byte
proxying over loopback IPC, the same shape the W15/W16 supervisor already uses
for jobs — is economically feasible.

Per the plan's fork, W17 applies the **YES** branch: **the PTY-adoption
follow-on wave is SCHEDULED inside this phase's plan** (below). No North-Star
narrowing amendment is required or recorded — a YES verdict narrows nothing; the
jobs half of C4 (non-negotiable) is unaffected and already lands in W15/W16.

Until the adoption follow-on ships, the pre-designed graceful drain
(`tools/pre_restart_drain.py`) remains the **safety net**: any dashboard restart
that lands before PTY adoption parks every live PTY WARM (close_session park +
capture_session_docs + warm-resume seed), so a restart costs a warm reconnect,
never dead context. The drain is retained, not deleted — it is the belt to
adoption's braces.

### Scheduled follow-on wave — PTY Adoption (Foreman-ready scope)

> Scheduled, NOT yet a plan ordinal. The frozen plan is 20 wave ordinals
> (W1–W18 with W6a/b/c); this follow-on is a checked-in scoped wave the way
> Crucible/Foreman schedule downstream work — it is taken up as its own effort
> after this phase closes (W18), so the C4 jobs half is not blocked on it.

**Intent:** Move PTY-session ownership behind the ANCHOR_SUPERVISOR seam using
the spike-proven owner-side-PTY + loopback-byte-proxy architecture, so
`nssm restart anchor` leaves live terminals attached to the supervisor-owned
PTY — the same restart survival jobs already have.

**Deliverables (scoped):**
- Owner-side PTY in the supervisor process: `pty_manager` sessions owned by the
  supervisor, bytes proxied over the existing loopback token-authed IPC (the
  W16 transport), re-using the spike's ≤400-significant-line harness shape.
- The dashboard-side client: `term_ws` / `term_stream2` bridge the browser
  socket to the supervisor byte-proxy instead of a dashboard-local PTY; auth
  unchanged (401-before-101 preserved).
- Re-attach on restart: a new dashboard connection re-attaches with full replay
  of prior output + live I/O, the owner-held PTY having survived (the spike's
  Q-REATTACH, now on the real service).
- Degraded mode: supervisor down → PTYs fall back to dashboard-owned + the
  pre-restart drain (unchanged safety net); named in the hybrid-state matrix.
- Live probe: a terminal open, `nssm restart anchor`, and a warm re-attach with
  the PTY still live — the PTY analogue of the C4 jobs runbook.

**Depends on:** W16 (external supervisor service + loopback IPC) — landed.
**Not blocking:** W18 closure; the jobs half of C4 stands alone.
"""


def _drain_body(ran_legs) -> str:
    legs = ", ".join(ran_legs) if ran_legs else "(none)"
    return f"""## Applied branch: PTY DRAIN (verdict NO)

A recorded leg ({legs}) answered **NO** against the pre-written W3 acceptance
questions. Per the plan's fork and D2's non-negotiable narrowing rule, PTYs
stay **dashboard-owned** and W17 ships the pre-designed graceful drain as the
active path:

- `tools/pre_restart_drain.py` — for every live PTY: `close_session` park +
  `capture_session_docs` (docs persisted to main) + a bounded warm-resume seed,
  wired into the deploy/restart script so a dashboard restart costs a WARM
  reconnect, not dead context.

**Narrowing recorded via the North-Star amendment path:** PTY sessions remain
dashboard-owned (they do NOT move behind the supervisor); the jobs half of C4
(non-negotiable) is unaffected. This narrowing is recorded here as the required
citation — never silently.
"""


def _pending_body() -> str:
    return """## Applied branch: PENDING (verdict not yet recorded)

No ConPTY spike leg has been recorded in `SPIKE-CONPTY-VERDICT.json` yet, so no
branch is applied — nothing is fabricated. Run the spike
(`python tools/conpty_spike.py --run --backend stub` and, on a console host,
`--backend real`) and re-render this artifact
(`python tools/conpty_verdict.py`). Until then the pre-designed drain
(`tools/pre_restart_drain.py`) is the standing safety net for any restart.
"""


def render_application_md(verdict=None) -> str:
    """Render the ``CONPTY-VERDICT-APPLICATION.md`` body deterministically.

    ``verdict`` (an object from :func:`read_verdict`) is injectable for tests;
    when ``None`` the checked-in verdict is read.
    """
    if verdict is None:
        verdict = read_verdict()
    overall = verdict.get("overall", VERDICT_UNRUN)
    branch = applied_branch(overall)
    ran_legs = verdict.get("ran_legs") or []

    header = (
        "# ConPTY verdict — W17 application\n\n"
        "The W3 ConPTY-across-processes spike verdict "
        f"(`{VERDICT_JSON_NAME}`), APPLIED by W17 (Wave 19).\n"
        "Rendered mechanically by `tools/conpty_verdict.py` — never "
        "hand-edited.\n\n"
        f"- **Overall verdict:** {overall}\n"
        f"- **Applied branch:** {branch}\n"
        f"- **Ran legs:** {', '.join(ran_legs) if ran_legs else '(none)'}\n\n"
    )
    if branch == BRANCH_ADOPTION:
        body = _adoption_body(ran_legs)
    elif branch == BRANCH_DRAIN:
        body = _drain_body(ran_legs)
    else:
        body = _pending_body()
    return header + body


def _write_doc(path: Path, text: str) -> Path:
    """Diff-stable write: skip an unchanged rewrite so `git status` stays clean."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return path
    except OSError:
        pass
    path.write_text(text, encoding="utf-8")
    return path


def write_application_doc(out_dir=None) -> Path:
    """Write ``CONPTY-VERDICT-APPLICATION.md`` (skipping an unchanged rewrite)."""
    out = Path(out_dir) if out_dir is not None else DEFAULT_ARTIFACT_DIR
    return _write_doc(out / APPLICATION_DOC_NAME, render_application_md())


def main(argv=None):  # pragma: no cover - thin CLI shim
    import argparse

    ap = argparse.ArgumentParser(
        description="Apply the recorded ConPTY spike verdict (W17): render the "
                    "checked-in CONPTY-VERDICT-APPLICATION.md.")
    ap.add_argument("--out-dir", default=None,
                    help="artifact dir (default: planning/rearch-2026-07)")
    ap.add_argument("--show", action="store_true",
                    help="print the read verdict + applied branch, write nothing")
    args = ap.parse_args(argv)
    v = read_verdict()
    if args.show:
        print(json.dumps({"overall": v["overall"],
                          "branch": applied_branch(v["overall"]),
                          "ran_legs": v["ran_legs"]}, indent=2))
        return 0
    p = write_application_doc(out_dir=args.out_dir)
    print(f"overall={v['overall']} branch={applied_branch(v['overall'])} "
          f"wrote={p}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys
    sys.exit(main())
