"""Containment smoke — W1, Phase 0 of the Anchor sleep cycle 2026-07-28 (v1.2).

Two claims this build makes constantly, and which this module is the machine
proof of:

1. **Every write target resolves under ``planning/sleep-2026-07-28/stage2/``.**
   Nothing this effort produces may land anywhere else — the repository root
   carries a *foreign* Foreman doc-trio (``DESCRIPTION.md``,
   ``IMPLEMENTATION-PLAN.md``, ``EXECUTION-LOG.md``, the FOUNDRY-V2 set, …)
   belonging to other efforts. Clobbering one of those is the landmine this
   wave exists to disarm.
2. **Those root foreign artifacts are byte-identical before and after.**
   Not "we did not mean to touch them" — the SHA-256 of each, taken before and
   after the run, is recorded and compared.
3. **The protected set does not silently fall behind the repository.**
   :func:`unprotected_foreign_candidates` reports root files shaped like
   another effort's Foreman document that :data:`ROOT_FOREIGN_ARTIFACTS` does
   not cover. It is advisory — a neighbour's unprotected file is a gap to
   close, not a reason to fail *this* build's own containment verdict.

The hardening law (crucible journal 0080) says containment is asserted far more
often than it is exercised, so :func:`escape_attempt_suite` actually attempts
the three escapes — ``..`` traversal, an absolute path, and a symlink/junction
whose lexical path is inside the root but whose real path is not — and each
must be refused **by name** (see the ``RULE_*`` constants).

Boundedness: at most :data:`MAX_WRITE_TARGETS` write targets are accepted in
one run; exceeding the bound is a named refusal, not a silent truncation.

No absolute host path is hard-coded here. The containment root is derived from
this file's own location (``<root>/tools/containment_smoke.py``) and may be
overridden for tests via the ``ANCHOR_SLEEP_CONTAINMENT_ROOT`` /
``ANCHOR_SLEEP_REPO_ROOT`` environment seams.

CLI::

    python tools/containment_smoke.py [extra write target ...]

exits 0 when contained, 1 when any target is refused, any root foreign
artifact changed, or any attempted escape was not refused.
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------

#: The containment root, expressed as the trailing path components it must
#: have. Written as components (never as a host absolute path) so this module
#: is portable and so the assertion is checkable rather than decorative.
CONTAINMENT_ROOT_TAIL: Tuple[str, ...] = ("planning", "sleep-2026-07-28", "stage2")

ENV_CONTAINMENT_ROOT = "ANCHOR_SLEEP_CONTAINMENT_ROOT"
ENV_REPO_ROOT = "ANCHOR_SLEEP_REPO_ROOT"

#: Named numeric bound (boundedness gate). A run offering more write targets
#: than this is REFUSED — never silently truncated.
MAX_WRITE_TARGETS = 1000

#: Repo-root documents owned by OTHER efforts. This build reads none of them
#: and writes none of them; the smoke proves byte-identity across the run.
#:
#: ``DESCRIPTION.md`` is first by contract: the escape-attempt suite uses
#: ``ROOT_FOREIGN_ARTIFACTS[0]`` as the concrete landmine it tries to clobber.
ROOT_FOREIGN_ARTIFACTS: Tuple[str, ...] = (
    "DESCRIPTION.md",
    "IMPLEMENTATION-PLAN.md",
    "EXECUTION-LOG.md",
    "DECISION-LOG.md",
    "HANDOFF.md",
    "SESSION-HANDOFF.md",
    "FOREMAN-EXECUTION-LOG-2026-07.md",
    "FOREMAN-EXECUTION-LOG-REARCH.md",
    "FOUNDRY-V2-DESCRIPTION.md",
    "FOUNDRY-V2-IMPLEMENTATION-PLAN.md",
    "FOUNDRY-V2-EXECUTION-LOG.md",
    "ANCHOR-STATE.md",
    # Other Foreman efforts' reports and per-wave execute summaries, which sit
    # at the repository root exactly where this build must never write.
    "PHASE3-FOREMAN-TUNING.md",
    "ANCHOR-OVERHAUL-REPORT-2026-07.md",
    "WAVE4-EXECUTE-SUMMARY.md",
    "WAVE7-EXECUTE-SUMMARY.md",
    "WAVE8-EXECUTE-SUMMARY.md",
)

#: Filename shapes that only ever appear at the repository root because some
#: *other* Foreman effort put them there. A root file matching one of these and
#: absent from :data:`ROOT_FOREIGN_ARTIFACTS` is unprotected drift — the smoke
#: reports it so the protected set cannot silently fall behind the repository.
FOREIGN_ARTIFACT_PATTERNS: Tuple[str, ...] = (
    "DESCRIPTION.md",
    "IMPLEMENTATION-PLAN.md",
    "EXECUTION-LOG.md",
    "DECISION-LOG.md",
    "*HANDOFF.md",
    "FOREMAN-*.md",
    "FOUNDRY-*.md",
    "WAVE*-EXECUTE-SUMMARY.md",
    "PHASE*-FOREMAN-*.md",
)

# Refusal / allowance rules. Every verdict names exactly one of these, so a
# refusal can be asserted BY NAME instead of by substring-matching prose.
RULE_INSIDE = "inside-containment-root"
RULE_TRAVERSAL = "parent-traversal"
RULE_ABSOLUTE_OUTSIDE = "absolute-path-outside-root"
RULE_SYMLINK_ESCAPE = "symlink-escape"
RULE_OUTSIDE = "outside-containment-root"
RULE_BOUND_EXCEEDED = "write-target-bound-exceeded"
RULE_UNAVAILABLE = "unavailable"

#: The three escapes the hardening gate requires be *attempted*, not asserted.
ESCAPE_DOTDOT = "dotdot-traversal"
ESCAPE_ABSOLUTE = "absolute-path"
ESCAPE_SYMLINK = "symlink-junction"
ESCAPE_ATTEMPT_NAMES: Tuple[str, ...] = (ESCAPE_DOTDOT, ESCAPE_ABSOLUTE, ESCAPE_SYMLINK)


class ContainmentViolation(Exception):
    """Raised by :func:`assert_write_target` for a target outside the root."""


class WriteTargetBoundExceeded(Exception):
    """Raised when more than :data:`MAX_WRITE_TARGETS` targets are offered."""


# --------------------------------------------------------------------------
# Roots
# --------------------------------------------------------------------------


def containment_root(env: Optional[Dict[str, str]] = None) -> Path:
    """The one directory this build may write into.

    Derived from this module's own location — ``<root>/tools/`` — so no host
    absolute path is baked in. ``ANCHOR_SLEEP_CONTAINMENT_ROOT`` overrides it
    for tests that need a throwaway root.
    """
    env = os.environ if env is None else env
    override = env.get(ENV_CONTAINMENT_ROOT)
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parents[1]


def repo_root(root: Optional[Path] = None, env: Optional[Dict[str, str]] = None) -> Path:
    """The repository root that carries the foreign Foreman doc-trio."""
    env = os.environ if env is None else env
    override = env.get(ENV_REPO_ROOT)
    if override:
        return Path(override).resolve()
    base = containment_root(env) if root is None else Path(root)
    return base.resolve().parents[len(CONTAINMENT_ROOT_TAIL) - 1]


def root_is_canonical(root: Optional[Path] = None) -> bool:
    """True when ``root`` really is ``…/planning/sleep-2026-07-28/stage2``."""
    root = containment_root() if root is None else Path(root)
    parts = tuple(p.lower() for p in root.resolve().parts)
    tail = tuple(p.lower() for p in CONTAINMENT_ROOT_TAIL)
    return parts[-len(tail):] == tail


# --------------------------------------------------------------------------
# Path containment
# --------------------------------------------------------------------------


def _norm(p) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def is_within(path, root) -> bool:
    """Case- and separator-insensitive ``path`` is ``root`` or under it."""
    a, b = _norm(path), _norm(root)
    return a == b or a.startswith(b + os.sep)


def _realpath(p) -> str:
    try:
        return os.path.realpath(str(p))
    except OSError:  # pragma: no cover - realpath is total on supported hosts
        return os.path.abspath(str(p))


@dataclass
class Verdict:
    """One write target's containment decision."""

    allowed: bool
    rule: str
    target: str
    resolved: str
    reason: str
    #: set when the target resolves onto a root foreign artifact
    foreign_artifact: Optional[str] = None
    pre_hash: Optional[str] = None
    post_hash: Optional[str] = None

    def as_dict(self) -> Dict[str, object]:
        return dict(self.__dict__)


def check_write_target(target, root: Optional[Path] = None) -> Verdict:
    """Decide whether ``target`` may be written, naming the deciding rule.

    A relative target is interpreted against the containment root (that is how
    every path in the plan and in the shared-artifact ledger is written).
    """
    root_real = _realpath(containment_root() if root is None else root)
    raw = str(target)
    p = Path(raw)

    if any(part == os.pardir for part in p.parts):
        resolved = _realpath(p if p.is_absolute() else Path(root_real) / p)
        return Verdict(
            False, RULE_TRAVERSAL, raw, resolved,
            "target carries a '..' parent-traversal component",
        )

    if p.is_absolute():
        resolved = _realpath(p)
        if not is_within(resolved, root_real):
            return Verdict(
                False, RULE_ABSOLUTE_OUTSIDE, raw, resolved,
                "absolute target resolves outside the containment root",
            )
        return Verdict(True, RULE_INSIDE, raw, resolved,
                       "absolute target resolves under the containment root")

    candidate = Path(root_real) / p
    resolved = _realpath(candidate)
    if not is_within(resolved, root_real):
        lexical_inside = is_within(os.path.normpath(str(candidate)), root_real)
        rule = RULE_SYMLINK_ESCAPE if lexical_inside else RULE_OUTSIDE
        reason = (
            "a path component is a symlink/junction that resolves outside the "
            "containment root" if lexical_inside else
            "target resolves outside the containment root"
        )
        return Verdict(False, rule, raw, resolved, reason)

    return Verdict(True, RULE_INSIDE, raw, resolved,
                   "target resolves under the containment root")


def assert_write_target(target, root: Optional[Path] = None) -> Verdict:
    """:func:`check_write_target`, raising :class:`ContainmentViolation`."""
    verdict = check_write_target(target, root=root)
    if not verdict.allowed:
        raise ContainmentViolation(
            "refused write target '%s' (%s): %s" % (verdict.target, verdict.rule, verdict.reason)
        )
    return verdict


# --------------------------------------------------------------------------
# Root foreign artifact snapshots
# --------------------------------------------------------------------------


def sha256_of(path) -> Optional[str]:
    """SHA-256 of a file, or ``None`` when it does not exist.

    ``None`` means *absent*, which is a different fact from a hash — an absent
    file that stays absent is still byte-identical across the run.
    """
    p = Path(path)
    if not p.is_file():
        return None
    digest = hashlib.sha256()
    with p.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_foreign_artifacts(
    repo: Optional[Path] = None,
    names: Sequence[str] = ROOT_FOREIGN_ARTIFACTS,
) -> Dict[str, Optional[str]]:
    base = repo_root() if repo is None else Path(repo)
    return {name: sha256_of(base / name) for name in names}


def compare_snapshots(
    before: Dict[str, Optional[str]],
    after: Dict[str, Optional[str]],
) -> List[Dict[str, Optional[str]]]:
    """Rows for every foreign artifact whose bytes changed."""
    changed = []
    for name in sorted(set(before) | set(after)):
        pre, post = before.get(name), after.get(name)
        if pre != post:
            changed.append({"artifact": name, "pre_hash": pre, "post_hash": post})
    return changed


def _foreign_artifact_for(resolved: str, repo: Path) -> Optional[str]:
    for name in ROOT_FOREIGN_ARTIFACTS:
        if _norm(repo / name) == _norm(resolved):
            return name
    return None


def unprotected_foreign_candidates(
    repo: Optional[Path] = None,
    patterns: Sequence[str] = FOREIGN_ARTIFACT_PATTERNS,
    known: Sequence[str] = ROOT_FOREIGN_ARTIFACTS,
) -> List[str]:
    """Root files that *look* like another effort's Foreman artifact but are
    not in the protected set.

    This is the drift guard on :data:`ROOT_FOREIGN_ARTIFACTS`: a hand-written
    list of names is only as good as its last edit, and another Foreman effort
    dropping a new report at the repository root would otherwise leave that
    file unhashed and therefore unproven. Sorted for determinism; an
    unreadable repository root yields ``[]`` rather than raising, because this
    is a *reporting* signal and never the thing that decides containment.
    """
    base = repo_root() if repo is None else Path(repo)
    protected = {name.lower() for name in known}
    found = set()
    try:
        entries = [p for p in base.iterdir() if p.is_file()]
    except OSError:
        return []

    for entry in entries:
        if entry.name.lower() in protected:
            continue
        for pattern in patterns:
            if fnmatch.fnmatch(entry.name.lower(), pattern.lower()):
                found.add(entry.name)
                break
    return sorted(found)


# --------------------------------------------------------------------------
# Escape-attempt suite (containment is exercised, not asserted)
# --------------------------------------------------------------------------


def _make_link(link: Path, target: Path) -> str:
    """Create a directory symlink or NTFS junction; return which, or ``""``."""
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return "symlink"
    except (OSError, NotImplementedError, AttributeError, ValueError):
        pass
    try:  # Windows without the symlink privilege still allows junctions
        import _winapi  # type: ignore

        _winapi.CreateJunction(str(target), str(link))  # type: ignore[attr-defined]
        return "junction"
    except Exception:
        return ""


def _remove_link(link: Path) -> None:
    """Remove a directory symlink or junction without following it.

    ``shutil.rmtree`` refuses (or, worse, treats inconsistently) a Windows
    junction, so the link is unhooked first and the scratch tree removed after.
    ``os.rmdir`` unhooks both junctions and directory symlinks on Windows;
    ``os.unlink`` covers POSIX symlinks.
    """
    if not os.path.lexists(str(link)):
        return
    try:
        os.rmdir(str(link))
        return
    except OSError:
        pass
    try:
        os.unlink(str(link))
    except OSError:
        pass


def escape_attempt_suite(
    root: Optional[Path] = None,
    repo: Optional[Path] = None,
) -> List[Dict[str, object]]:
    """Actually attempt the three escapes; each must be refused BY NAME.

    Returns one row per attempt with ``name``, ``target``, ``attempted``,
    ``refused``, ``rule`` and ``reason``. When the host offers no symlink and
    no junction facility the row is honestly recorded as ``attempted: False``
    with rule ``unavailable`` — never as a pass.
    """
    root = containment_root() if root is None else Path(root)
    base = repo_root(root) if repo is None else Path(repo)
    rows: List[Dict[str, object]] = []

    # 1. `..` traversal — lexically climbs out to the repo root doc-trio.
    climb = [os.pardir] * len(CONTAINMENT_ROOT_TAIL)
    dotdot = os.path.join(*(climb + [ROOT_FOREIGN_ARTIFACTS[0]]))
    v = check_write_target(dotdot, root=root)
    rows.append({
        "name": ESCAPE_DOTDOT, "target": dotdot, "attempted": True,
        "refused": not v.allowed, "rule": v.rule, "reason": v.reason,
        "expected_rule": RULE_TRAVERSAL,
    })

    # 2. absolute path — the exact landmine: the repo root DESCRIPTION.md.
    absolute = str(base / ROOT_FOREIGN_ARTIFACTS[0])
    v = check_write_target(absolute, root=root)
    rows.append({
        "name": ESCAPE_ABSOLUTE, "target": absolute, "attempted": True,
        "refused": not v.allowed, "rule": v.rule, "reason": v.reason,
        "expected_rule": RULE_ABSOLUTE_OUTSIDE,
    })

    # 3. symlink / junction — lexically inside the root, really outside it.
    workdir = Path(tempfile.mkdtemp(prefix=".containment-smoke-", dir=str(root)))
    outside = Path(tempfile.mkdtemp(prefix="containment-smoke-outside-"))
    try:
        # A real file on the far side, so the escape target genuinely exists
        # through the link and its resolution is unambiguous.
        (outside / "clobbered.md").write_text("would have been clobbered\n", encoding="utf-8")
        link = workdir / "escape"
        kind = _make_link(link, outside)
        rel = os.path.join(workdir.name, "escape", "clobbered.md")
        if kind:
            v = check_write_target(rel, root=root)
            rows.append({
                "name": ESCAPE_SYMLINK, "target": rel, "attempted": True,
                "refused": not v.allowed, "rule": v.rule, "reason": v.reason,
                "expected_rule": RULE_SYMLINK_ESCAPE, "link_kind": kind,
            })
        else:
            rows.append({
                "name": ESCAPE_SYMLINK, "target": rel, "attempted": False,
                "refused": False, "rule": RULE_UNAVAILABLE,
                "reason": "this host offers neither os.symlink nor CreateJunction",
                "expected_rule": RULE_SYMLINK_ESCAPE, "link_kind": "",
            })
    finally:
        _remove_link(workdir / "escape")
        shutil.rmtree(str(workdir), ignore_errors=True)
        shutil.rmtree(str(outside), ignore_errors=True)

    return rows


# --------------------------------------------------------------------------
# The smoke run
# --------------------------------------------------------------------------


@dataclass
class SmokeResult:
    ok: bool
    root: str
    repo: str
    verdicts: List[Verdict] = field(default_factory=list)
    refusals: List[Verdict] = field(default_factory=list)
    foreign_before: Dict[str, Optional[str]] = field(default_factory=dict)
    foreign_after: Dict[str, Optional[str]] = field(default_factory=dict)
    changed_foreign: List[Dict[str, Optional[str]]] = field(default_factory=list)
    escape_suite: List[Dict[str, object]] = field(default_factory=list)
    bound_exceeded: bool = False
    problems: List[str] = field(default_factory=list)
    #: Advisory: root files shaped like another effort's Foreman artifact that
    #: the protected set does not cover. Reported, never fatal — this run's
    #: own containment is decided by the verdicts, not by the neighbours.
    unprotected_candidates: List[str] = field(default_factory=list)

    def report(self) -> str:
        lines = ["containment smoke: %s" % ("PASS" if self.ok else "FAIL")]
        lines.append("  containment root: %s" % self.root)
        lines.append("  write targets checked: %d (bound %d)"
                     % (len(self.verdicts), MAX_WRITE_TARGETS))
        for v in self.refusals:
            lines.append("  REFUSED %s" % v.target)
            lines.append("    rule: %s - %s" % (v.rule, v.reason))
            lines.append("    resolved: %s" % v.resolved)
            if v.foreign_artifact:
                lines.append("    root foreign artifact it would have clobbered: %s"
                             % v.foreign_artifact)
                lines.append("    pre_hash:  %s" % v.pre_hash)
                lines.append("    post_hash: %s" % v.post_hash)
        for row in self.changed_foreign:
            lines.append("  CHANGED root foreign artifact %s" % row["artifact"])
            lines.append("    pre_hash:  %s" % row["pre_hash"])
            lines.append("    post_hash: %s" % row["post_hash"])
        for row in self.escape_suite:
            state = "refused" if row["refused"] else (
                "NOT ATTEMPTED" if not row["attempted"] else "NOT REFUSED")
            lines.append("  escape %s: %s (rule %s)" % (row["name"], state, row["rule"]))
        for problem in self.problems:
            lines.append("  PROBLEM %s" % problem)
        if not self.changed_foreign and self.foreign_before:
            lines.append("  root foreign artifacts byte-identical before/after: %d checked"
                         % len(self.foreign_before))
        for name in self.unprotected_candidates:
            lines.append("  ADVISORY unprotected root artifact %s - looks like another "
                         "effort's Foreman doc but is not in ROOT_FOREIGN_ARTIFACTS" % name)
        return "\n".join(lines)

    def as_dict(self) -> Dict[str, object]:
        return {
            "ok": self.ok,
            "root": self.root,
            "repo": self.repo,
            "verdicts": [v.as_dict() for v in self.verdicts],
            "refusals": [v.as_dict() for v in self.refusals],
            "foreign_before": self.foreign_before,
            "foreign_after": self.foreign_after,
            "changed_foreign": self.changed_foreign,
            "escape_suite": self.escape_suite,
            "bound_exceeded": self.bound_exceeded,
            "problems": self.problems,
            "unprotected_candidates": self.unprotected_candidates,
        }


def run_smoke(
    write_targets: Optional[Sequence[str]] = None,
    root: Optional[Path] = None,
    repo: Optional[Path] = None,
    run_escape_suite: bool = True,
) -> SmokeResult:
    """Check every write target, prove the root foreign artifacts unchanged.

    ``write_targets`` defaults to the write rows of the shared-artifact ledger,
    so the smoke checks what the build actually declares it will write.
    """
    root = containment_root() if root is None else Path(root)
    base = repo_root(root) if repo is None else Path(repo)
    targets = list(ledger_write_targets(root) if write_targets is None else write_targets)

    result = SmokeResult(ok=True, root=str(root), repo=str(base))

    if len(targets) > MAX_WRITE_TARGETS:
        result.ok = False
        result.bound_exceeded = True
        result.problems.append(
            "%s: %d write targets offered, bound is %d"
            % (RULE_BOUND_EXCEEDED, len(targets), MAX_WRITE_TARGETS)
        )
        result.refusals.append(Verdict(
            False, RULE_BOUND_EXCEEDED, "<%d targets>" % len(targets), "",
            "more write targets than the named bound %d" % MAX_WRITE_TARGETS,
        ))
        return result

    result.foreign_before = snapshot_foreign_artifacts(base)

    for target in targets:
        verdict = check_write_target(target, root=root)
        if not verdict.allowed:
            name = _foreign_artifact_for(verdict.resolved, base)
            if name:
                verdict.foreign_artifact = name
                verdict.pre_hash = result.foreign_before.get(name)
        result.verdicts.append(verdict)
        if not verdict.allowed:
            result.refusals.append(verdict)

    if run_escape_suite:
        result.escape_suite = escape_attempt_suite(root=root, repo=base)

    result.foreign_after = snapshot_foreign_artifacts(base)
    result.changed_foreign = compare_snapshots(result.foreign_before, result.foreign_after)
    result.unprotected_candidates = unprotected_foreign_candidates(repo=base)

    for verdict in result.refusals:
        if verdict.foreign_artifact:
            verdict.post_hash = result.foreign_after.get(verdict.foreign_artifact)

    if result.refusals:
        result.ok = False
        for verdict in result.refusals:
            detail = ""
            if verdict.foreign_artifact:
                detail = (" - would have clobbered root foreign artifact %s "
                          "(pre_hash %s / post_hash %s)"
                          % (verdict.foreign_artifact, verdict.pre_hash, verdict.post_hash))
            result.problems.append(
                "refused write target %s (%s)%s" % (verdict.target, verdict.rule, detail)
            )
    if result.changed_foreign:
        result.ok = False
        for row in result.changed_foreign:
            result.problems.append(
                "root foreign artifact %s changed (pre_hash %s / post_hash %s)"
                % (row["artifact"], row["pre_hash"], row["post_hash"])
            )
    for row in result.escape_suite:
        if row["attempted"] and not row["refused"]:
            result.ok = False
            result.problems.append(
                "escape attempt %s was NOT refused (rule %s)" % (row["name"], row["rule"])
            )

    return result


def ledger_write_targets(root: Optional[Path] = None) -> List[str]:
    """Write/append paths declared by the shared-artifact ledger."""
    try:
        from tools import artifact_ledger  # type: ignore
    except ImportError:  # running as a script: tools/ is sys.path[0]
        import artifact_ledger  # type: ignore
    return artifact_ledger.write_targets(root=root)


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = containment_root()
    extra = [a for a in argv if not a.startswith("--")]
    targets = ledger_write_targets(root) + extra
    result = run_smoke(write_targets=targets, root=root)
    sys.stdout.write(result.report() + "\n")
    if "--json" in argv:
        sys.stdout.write(json.dumps(result.as_dict(), indent=2, sort_keys=True) + "\n")
    return 0 if result.ok else 1


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main())
