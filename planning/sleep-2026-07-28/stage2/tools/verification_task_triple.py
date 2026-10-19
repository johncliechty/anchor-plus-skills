"""Verification task triple — W1, Phase 0.

Three reproducible Anchor v1.2 tasks (**open**, **run**, **stop-restart**),
each carrying its exact invocation, its expected observable, and John's dated
confirmation line. S1 (W22) replays this triple live; every wave in between
leans on it.

The hard part is what this module refuses to do. The triple's confirmation is a
**live-John item** and *no exit substitutes for it*:

    live-John item — no E5 available on the task triple

An unconfirmed triple is a HALT and the wave is **not GO** — regardless of how
many tests pass. That sentence is the whole point of Phase 0: a green suite is
not a confirmation, and this module never lets structure stand in for John.

Nothing here fabricates a confirmation, back-dates one, or accepts a vague date
("recently", "yesterday"): a confirmation needs ``confirmed: true``, an
ISO ``YYYY-MM-DD`` date, a non-empty confirmer, and a non-empty line.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

GO = "GO"
HALT = "HALT"

#: Verbatim HALT reason for an unconfirmed triple (asserted by the wave gate).
HALT_REASON_NO_E5 = "live-John item — no E5 available on the task triple"
HALT_REASON_MALFORMED = "verification task triple is malformed"

#: The three tasks, by kind. Exactly these three, no more and no fewer.
REQUIRED_KINDS = ("open", "run", "stop-restart")

ARTIFACT_RELPATH = os.path.join("artifacts", "verification-task-triple.json")

_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class ExitNotAvailable(Exception):
    """Raised when an exit id is offered as a substitute for John's line."""


@dataclass
class Result:
    status: str
    reason: str
    problems: List[str] = field(default_factory=list)
    unconfirmed: List[str] = field(default_factory=list)
    confirmed: List[str] = field(default_factory=list)

    @property
    def is_go(self) -> bool:
        return self.status == GO

    def as_dict(self) -> Dict[str, object]:
        return {
            "status": self.status,
            "reason": self.reason,
            "problems": list(self.problems),
            "unconfirmed": list(self.unconfirmed),
            "confirmed": list(self.confirmed),
        }


# --------------------------------------------------------------------------
# Loading
# --------------------------------------------------------------------------


def _root(root: Optional[Path] = None) -> Path:
    if root is not None:
        return Path(root)
    try:
        from tools import containment_smoke  # type: ignore
    except ImportError:  # running as a script: tools/ is sys.path[0]
        import containment_smoke  # type: ignore
    return containment_smoke.containment_root()


def triple_path(root: Optional[Path] = None) -> Path:
    return _root(root) / ARTIFACT_RELPATH


def load_triple(path: Optional[Path] = None, root: Optional[Path] = None) -> Dict[str, object]:
    path = triple_path(root) if path is None else Path(path)
    return json.loads(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def _tasks(doc: Dict[str, object]) -> List[Dict[str, object]]:
    tasks = doc.get("tasks")
    return list(tasks) if isinstance(tasks, list) else []


def confirmation_is_valid(confirmation: Optional[Dict[str, object]]) -> bool:
    """A confirmation is John's or it is nothing. No partial credit."""
    if not isinstance(confirmation, dict):
        return False
    if confirmation.get("confirmed") is not True:
        return False
    date = confirmation.get("date")
    if not isinstance(date, str) or not _ISO_DATE.match(date.strip()):
        return False
    if not str(confirmation.get("confirmed_by") or "").strip():
        return False
    if not str(confirmation.get("line") or "").strip():
        return False
    return True


def _structural_problems(doc: Dict[str, object]) -> List[str]:
    problems: List[str] = []
    tasks = _tasks(doc)
    if not tasks:
        problems.append("no tasks: the triple must carry exactly three tasks")
        return problems

    kinds = [str(t.get("kind") or "") for t in tasks]
    for required in REQUIRED_KINDS:
        if kinds.count(required) != 1:
            problems.append(
                "task kind %r appears %d time(s); exactly one is required"
                % (required, kinds.count(required))
            )
    extra = [k for k in kinds if k not in REQUIRED_KINDS]
    for kind in extra:
        problems.append("unexpected task kind %r" % kind)

    for task in tasks:
        tid = str(task.get("id") or task.get("kind") or "<unnamed>")
        if not str(task.get("id") or "").strip():
            problems.append("task %s: missing id" % tid)
        invocation = task.get("invocation")
        steps = invocation.get("steps") if isinstance(invocation, dict) else None
        if not isinstance(steps, list) or not [s for s in steps if str(s).strip()]:
            problems.append("task %s: invocation.steps is empty — not reproducible" % tid)
        if not str(task.get("expected_observable") or "").strip():
            problems.append("task %s: expected_observable is empty" % tid)
    return problems


def validate_triple(doc: Dict[str, object]) -> Result:
    """Structure first, then John's confirmation. Confirmation is never inferred."""
    problems = _structural_problems(doc)
    if problems:
        return Result(HALT, "%s: %s" % (HALT_REASON_MALFORMED, "; ".join(problems)),
                      problems=problems)

    confirmed: List[str] = []
    unconfirmed: List[str] = []
    for task in _tasks(doc):
        tid = str(task.get("id") or task.get("kind"))
        if confirmation_is_valid(task.get("john_confirmation")):
            confirmed.append(tid)
        else:
            unconfirmed.append(tid)

    if unconfirmed:
        return Result(
            HALT,
            HALT_REASON_NO_E5,
            problems=["task %s carries no dated confirmation from John" % t for t in unconfirmed],
            unconfirmed=unconfirmed,
            confirmed=confirmed,
        )
    return Result(GO, "all three tasks carry John's dated confirmation",
                  confirmed=confirmed)


def gate(path: Optional[Path] = None, root: Optional[Path] = None) -> Result:
    """Validate the shipped triple. A missing file is a HALT, never a pass."""
    target = triple_path(root) if path is None else Path(path)
    if not target.is_file():
        return Result(HALT, "%s: %s not found" % (HALT_REASON_MALFORMED, ARTIFACT_RELPATH),
                      problems=["artifact missing"])
    try:
        doc = json.loads(target.read_text(encoding="utf-8"))
    except ValueError as exc:
        return Result(HALT, "%s: not valid JSON (%s)" % (HALT_REASON_MALFORMED, exc),
                      problems=["unparseable"])
    return validate_triple(doc)


# --------------------------------------------------------------------------
# No exit substitutes for John
# --------------------------------------------------------------------------


def available_exits() -> tuple:
    """No exit — E1..E6 — closes the task triple. It is a live-John item."""
    return ()


def assert_no_exit_substitute(exit_id: str) -> None:
    """Refuse any exit offered in place of John's confirmation, naming E5."""
    normalized = str(exit_id or "").strip().upper()
    if normalized == "E5":
        raise ExitNotAvailable(HALT_REASON_NO_E5)
    raise ExitNotAvailable(
        "%s is not available on the task triple — %s" % (normalized or "<none>", HALT_REASON_NO_E5)
    )


def confirmation_template() -> Dict[str, object]:
    """Exactly the block John fills in — one per task, filled in by hand."""
    return {
        "confirmed": False,
        "confirmed_by": "",
        "date": "",
        "line": "",
    }


# --------------------------------------------------------------------------
# The Phase-0 GO decision
# --------------------------------------------------------------------------


def phase0_go_decision(root: Optional[Path] = None) -> Result:
    """Combine the triple, the ledger sign-off, and the containment smoke.

    This is deliberately independent of the test suite: no count of passing
    tests appears anywhere in the decision. Structure cannot sign for John.
    """
    base = _root(root)
    problems: List[str] = []
    reasons: List[str] = []

    triple = gate(root=base)
    if not triple.is_go:
        problems.extend(triple.problems)
        reasons.append(triple.reason)

    try:
        from tools import artifact_ledger  # type: ignore
    except ImportError:  # running as a script
        import artifact_ledger  # type: ignore
    ledger = artifact_ledger.gate(root=base)
    if ledger.status != GO:
        problems.extend(ledger.problems)
        reasons.append(ledger.reason)

    try:
        from tools import containment_smoke  # type: ignore
    except ImportError:  # running as a script
        import containment_smoke  # type: ignore
    smoke = containment_smoke.run_smoke(root=base)
    if not smoke.ok:
        problems.extend(smoke.problems)
        reasons.append("containment smoke failed")

    if problems:
        return Result(HALT, " | ".join(reasons), problems=problems,
                      unconfirmed=triple.unconfirmed, confirmed=triple.confirmed)
    return Result(GO, "task triple confirmed, ledger signed, containment proven",
                  confirmed=triple.confirmed)


def main(argv: Optional[List[str]] = None) -> int:  # pragma: no cover - CLI
    import sys

    result = phase0_go_decision()
    sys.stdout.write("%s — %s\n" % (result.status, result.reason))
    for problem in result.problems:
        sys.stdout.write("  - %s\n" % problem)
    return 0 if result.is_go else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
