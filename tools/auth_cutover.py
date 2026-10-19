"""W9 auth-enforce ops cutover — the live tokenless-401 probe + outcome ledger.

The re-architecture's C2 criterion is "demonstrated, not narrated": the gated
data plane isn't *enforced* until a tokenless request to the LIVE ``:8777``
service returns ``401``. That flip is an OPS action (mint token → set the NSSM
``AppEnvironmentExtra`` ``ANCHOR_AUTH_MODE=enforce`` → ``nssm restart anchor``),
performed by John on ``PUTER`` per ``OPS-CUTOVER-W9.md``. This module ships the
teeth:

* :func:`probe_tokenless_401` — the mechanical assertion John runs against the
  live service after the restart: a tokenless ``GET /api/rnd/projects`` MUST
  come back ``401``. It is deliberately NOT wired into the 5AM healthcheck
  (which never touches the live ``:8777`` — see CLAUDE.md) — it is the cutover's
  own probe, run once, with John.
* :func:`record_cutover_outcome` / :func:`load_cutover_outcome` — the honest
  outcome ledger. The cutover has exactly one of a small set of outcomes, and a
  **John-declines** outcome is recorded HERE via the amendment path (a checked-in
  artifact + the ``OPS-CUTOVER-W9.md`` runbook's North-Star-amendment cell),
  **never** silently. Until the cutover runs the recorded outcome is
  ``pending``.

Stdlib only (``json``, ``urllib``). Never real-network in tests — the probe is
pointed at a throwaway loopback server.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "planning" / "rearch-2026-07"
OUTCOME_NAME = "OPS-CUTOVER-W9-OUTCOME.json"

#: The gated route the cutover asserts on (the plan's named probe target).
PROBE_PATH = "/api/rnd/projects"

# The recognized cutover outcomes (the ledger's closed set).
OUTCOME_PENDING = "pending"     # not yet run
OUTCOME_ENFORCED = "enforced"   # live tokenless-401 observed — C2 demonstrated
OUTCOME_HELD = "held"           # a would-401 was unexplained; flip held (W8 gate)
OUTCOME_DECLINED = "declined"   # John declined the flip — recorded via amendment
OUTCOMES = (OUTCOME_PENDING, OUTCOME_ENFORCED, OUTCOME_HELD, OUTCOME_DECLINED)


def probe_tokenless_401(base_url, path=PROBE_PATH, timeout=6.0):
    """Assert a TOKENLESS ``GET base_url+path`` returns ``401`` (the live flip).

    Returns ``{ok, status, detail}``. ``ok`` is True iff the status is exactly
    ``401`` — the mechanical proof that the enforce flip took on the live
    service. A ``200`` means the flip did NOT take (still open/warn); any other
    status / a transport error is reported honestly. Sends NO token, cookie, or
    Authorization header — that is the whole point.
    """
    url = base_url.rstrip("/") + path
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    except Exception as e:  # transport error — honest, not a pass
        return {"ok": False, "status": None,
                "detail": f"transport error: {type(e).__name__}: {e}"}
    if status == 401:
        return {"ok": True, "status": 401,
                "detail": f"tokenless {path} returned 401 — enforce flip took"}
    return {"ok": False, "status": status,
            "detail": f"expected 401, got {status} — flip did NOT take "
                      f"(still open/warn?)"}


def outcome_path(out_dir=None):
    out = Path(out_dir) if out_dir is not None else DEFAULT_ARTIFACT_DIR
    return out / OUTCOME_NAME


def record_cutover_outcome(outcome, *, detail="", amendment_ref=None,
                           probe=None, ts=None, out_dir=None):
    """Record the cutover outcome to the checked-in ledger (honest, never silent).

    ``outcome`` must be one of :data:`OUTCOMES`. A ``declined`` outcome REQUIRES
    an ``amendment_ref`` (the North-Star-amendment citation) — the plan mandates
    a John-declines outcome be recorded via the amendment path, never silently;
    passing ``declined`` without a citation raises. ``probe`` is the optional
    :func:`probe_tokenless_401` result to embed. Returns the written path.
    """
    if outcome not in OUTCOMES:
        raise ValueError(f"unknown cutover outcome {outcome!r}; "
                         f"expected one of {', '.join(OUTCOMES)}")
    if outcome == OUTCOME_DECLINED and not (amendment_ref or "").strip():
        raise ValueError(
            "a 'declined' cutover outcome MUST cite the North-Star amendment "
            "(amendment_ref=...) — never record a decline silently")
    payload = {
        "schema": 1,
        "wave": "W9",
        "criterion": "C2",
        "probe_path": PROBE_PATH,
        "outcome": outcome,
        "detail": detail,
        "amendment_ref": amendment_ref,
        "probe": probe,
        "ts": ts,
    }
    p = outcome_path(out_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n",
                 encoding="utf-8")
    return p


def load_cutover_outcome(out_dir=None):
    """Load the recorded cutover outcome, or the ``pending`` default."""
    p = outcome_path(out_dir)
    if not p.exists():
        return {"outcome": OUTCOME_PENDING, "detail": "cutover not yet run"}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"outcome": OUTCOME_PENDING, "detail": "unreadable outcome file"}


def main(argv=None):  # pragma: no cover - thin CLI shim
    import sys as _sys

    argv = list(_sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "probe":
        base = argv[1] if len(argv) > 1 else "http://localhost:8777"
        res = probe_tokenless_401(base)
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1
    cur = load_cutover_outcome()
    print(json.dumps(cur, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
