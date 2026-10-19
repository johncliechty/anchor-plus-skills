"""Release guard — W22, Phase 5.

Asserts that **nothing from this effort** is publishable to v1.1.x
collaborators. The sleep cycle ships on branch **v1.2**; collaborator
channels and release branches under the 1.1 line must refuse publish.

Hard rules:

* Effort branch is ``v1.2`` (and related v1.2 tokens).
* Target branch/channel matching ``v1.1``, ``v1.1.x``, ``release/1.1``, etc.
  is **not publishable**.
* Default posture is refuse when the target is ambiguous toward 1.1.
* No absolute host paths are hard-coded.

CLI::

    python tools/release_guard.py --branch v1.2 --channel internal-v1.2
    python tools/release_guard.py --branch v1.1.2   # exits non-zero
"""
from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# Public constants
# --------------------------------------------------------------------------

GO = "GO"
REFUSE = "REFUSE"

#: This effort's home line — the only line that may receive its artifacts.
EFFORT_BRANCH = "v1.2"
EFFORT_LINE = "1.2"

#: Collaborator line that must not receive this effort's work.
FORBIDDEN_LINE = "1.1"
FORBIDDEN_LINE_LABEL = "v1.1.x"

REFUSE_V11_MESSAGE = (
    "release guard: nothing from this effort is publishable to v1.1.x "
    "collaborators (branch/channel check)"
)

REFUSE_WRONG_EFFORT_BRANCH_MESSAGE = (
    "release guard: publish source must be this effort's v1.2 line — "
    "refusing foreign/unknown source branch"
)

ALLOW_V12_MESSAGE = (
    "release guard: publish target is on the v1.2 effort line — not v1.1.x"
)

#: Explicit channel names that are always treated as v1.1.x collaborator sinks.
_FORBIDDEN_CHANNEL_EXACT = frozenset(
    {
        "v1.1",
        "v1.1.x",
        "1.1",
        "1.1.x",
        "release-1.1",
        "release/1.1",
        "stable-1.1",
        "collaborators-v1.1",
        "collaborators-1.1",
        "prod-1.1",
        "production-1.1",
    }
)

#: Branch name patterns that mark the forbidden 1.1 line.
_V11_BRANCH = re.compile(
    r"""
    (^|[/._-])
    (
        v?1\.1(\.\d+)?([xX])?     # v1.1 / v1.1.0 / v1.1.x
        | release[/._-]?v?1\.1
        | rel[/._-]?v?1\.1
    )
    ($|[/._-])
    """,
    re.IGNORECASE | re.VERBOSE,
)

#: Branch name patterns that mark this effort's 1.2 line.
_V12_BRANCH = re.compile(
    r"""
    (^|[/._-])
    (
        v?1\.2(\.\d+)?([xX])?
        | release[/._-]?v?1\.2
        | rel[/._-]?v?1\.2
    )
    ($|[/._-])
    """,
    re.IGNORECASE | re.VERBOSE,
)


# --------------------------------------------------------------------------
# Errors + result
# --------------------------------------------------------------------------


class ReleaseGuardError(Exception):
    """Raised when a publish path to v1.1.x (or illegal source) is attempted."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


@dataclass
class GuardResult:
    """Outcome of a branch/channel publish check."""

    status: str  # GO | REFUSE
    publishable: bool
    message: str
    branch: Optional[str] = None
    channel: Optional[str] = None
    reasons: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "publishable": self.publishable,
            "message": self.message,
            "branch": self.branch,
            "channel": self.channel,
            "reasons": list(self.reasons),
        }

    def assert_ok(self) -> "GuardResult":
        if not self.publishable or self.status != GO:
            raise ReleaseGuardError(self.message)
        return self


# --------------------------------------------------------------------------
# Classification helpers
# --------------------------------------------------------------------------


def _norm(token: Optional[str]) -> str:
    return (token or "").strip().lower()


def is_v11_line(token: Optional[str]) -> bool:
    """True when branch or channel names the forbidden v1.1.x collaborator line."""
    t = _norm(token)
    if not t:
        return False
    if t in _FORBIDDEN_CHANNEL_EXACT:
        return True
    # Strip common prefixes for exact compare.
    compact = t.replace(" ", "")
    if compact in _FORBIDDEN_CHANNEL_EXACT:
        return True
    if re.search(r"\bv?1\.1(\.\d+)?x?\b", t):
        # Exclude accidental 1.10 / 1.12 if ever present — require 1.1 not 1.1N
        # where N continues the minor without a dot. v1.10 would match v1.1 + 0
        # under naive patterns; require end or separator after 1.1 patch.
        if re.search(r"\bv?1\.1(\.\d+)?x?\b", t) and not re.search(
            r"\bv?1\.1\d", t
        ):
            return True
    if _V11_BRANCH.search(t):
        # Same 1.10 guard.
        if re.search(r"v?1\.1\d", t):
            return False
        return True
    if "collaborator" in t and "1.1" in t:
        return True
    return False


def is_v12_line(token: Optional[str]) -> bool:
    """True when branch or channel names this effort's v1.2 line."""
    t = _norm(token)
    if not t:
        return False
    if t in {"v1.2", "1.2", "v1.2.x", "1.2.x", "release/1.2", "release-v1.2"}:
        return True
    if re.search(r"\bv?1\.2(\.\d+)?x?\b", t) and not re.search(r"\bv?1\.2\d", t):
        return True
    return bool(_V12_BRANCH.search(t))


def is_forbidden_publish_target(
    *,
    branch: Optional[str] = None,
    channel: Optional[str] = None,
) -> bool:
    """True when either branch or channel is a v1.1.x collaborator sink."""
    return is_v11_line(branch) or is_v11_line(channel)


# --------------------------------------------------------------------------
# Guard API
# --------------------------------------------------------------------------


def check_publish(
    *,
    branch: Optional[str] = None,
    channel: Optional[str] = None,
    source_branch: Optional[str] = None,
    require_source_v12: bool = True,
) -> GuardResult:
    """Check whether a publish from this effort to the given target is allowed.

    Parameters
    ----------
    branch:
        Destination branch (e.g. ``v1.1.2``, ``v1.2``).
    channel:
        Destination channel label (e.g. ``collaborators-v1.1``, ``internal-v1.2``).
    source_branch:
        Branch this effort would publish *from*. Defaults to ``v1.2``.
    require_source_v12:
        When True (default), source must be on the v1.2 line.
    """
    reasons: List[str] = []
    src = source_branch if source_branch is not None else EFFORT_BRANCH

    if require_source_v12 and not is_v12_line(src):
        return GuardResult(
            status=REFUSE,
            publishable=False,
            message=REFUSE_WRONG_EFFORT_BRANCH_MESSAGE,
            branch=branch,
            channel=channel,
            reasons=["source_branch %r is not on the v1.2 effort line" % src],
        )

    if is_v11_line(branch):
        reasons.append("destination branch %r is on the v1.1.x line" % branch)
    if is_v11_line(channel):
        reasons.append("destination channel %r is a v1.1.x collaborator sink" % channel)

    if reasons:
        return GuardResult(
            status=REFUSE,
            publishable=False,
            message=REFUSE_V11_MESSAGE,
            branch=branch,
            channel=channel,
            reasons=reasons,
        )

    # No explicit target → still not "publishable to v1.1.x"; for a positive
    # GO the caller must name a non-v1.1 target (v1.2 line or neutral).
    if branch is None and channel is None:
        return GuardResult(
            status=GO,
            publishable=True,
            message=ALLOW_V12_MESSAGE + " (no destination named — not a v1.1.x publish)",
            branch=branch,
            channel=channel,
            reasons=["no destination branch/channel; v1.1.x publish not asserted"],
        )

    # Named target that is not v1.1 — allow when on v1.2 or neutral.
    if is_v12_line(branch) or is_v12_line(channel):
        return GuardResult(
            status=GO,
            publishable=True,
            message=ALLOW_V12_MESSAGE,
            branch=branch,
            channel=channel,
            reasons=["destination is on the v1.2 effort line"],
        )

    # Neutral destination (e.g. internal staging name without 1.1/1.2 markers).
    return GuardResult(
        status=GO,
        publishable=True,
        message=ALLOW_V12_MESSAGE + " (destination not on v1.1.x)",
        branch=branch,
        channel=channel,
        reasons=["destination does not match v1.1.x collaborator patterns"],
    )


def assert_not_publishable_to_v11(
    *,
    branch: Optional[str] = None,
    channel: Optional[str] = None,
    source_branch: Optional[str] = None,
) -> GuardResult:
    """Refuse if the destination is v1.1.x; return GO result otherwise.

    This is the W22 gate helper: collaborators on the 1.1 line must not
    receive this effort's artifacts.
    """
    result = check_publish(
        branch=branch,
        channel=channel,
        source_branch=source_branch,
    )
    if is_forbidden_publish_target(branch=branch, channel=channel):
        # Always refuse v1.1 destinations even if check_publish were softened.
        raise ReleaseGuardError(REFUSE_V11_MESSAGE)
    return result.assert_ok()


def assert_publish_allowed(
    *,
    branch: Optional[str] = None,
    channel: Optional[str] = None,
    source_branch: Optional[str] = None,
) -> GuardResult:
    """Full assert: source on v1.2 and destination not v1.1.x."""
    result = check_publish(
        branch=branch,
        channel=channel,
        source_branch=source_branch,
        require_source_v12=True,
    )
    return result.assert_ok()


def guard_effort_release(
    *,
    branch: Optional[str] = None,
    channel: Optional[str] = None,
    source_branch: str = EFFORT_BRANCH,
) -> GuardResult:
    """Primary W22 API — branch + channel check for this effort's release."""
    return check_publish(
        branch=branch,
        channel=channel,
        source_branch=source_branch,
        require_source_v12=True,
    )


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    branch: Optional[str] = None
    channel: Optional[str] = None
    source: Optional[str] = None
    i = 0
    while i < len(args):
        a = args[i]
        if a == "--branch" and i + 1 < len(args):
            branch = args[i + 1]
            i += 2
            continue
        if a == "--channel" and i + 1 < len(args):
            channel = args[i + 1]
            i += 2
            continue
        if a == "--source-branch" and i + 1 < len(args):
            source = args[i + 1]
            i += 2
            continue
        i += 1

    result = check_publish(
        branch=branch,
        channel=channel,
        source_branch=source if source is not None else EFFORT_BRANCH,
    )
    print("status:", result.status)
    print("publishable:", result.publishable)
    print("message:", result.message)
    for r in result.reasons:
        print("reason:", r)
    return 0 if result.publishable and result.status == GO else 1


if __name__ == "__main__":
    raise SystemExit(main())
