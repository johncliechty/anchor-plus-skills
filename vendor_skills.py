"""vendor_skills.py — clean vendoring of the bundled Trio + Foundry skills.

Share-distro Wave 3 + Shareable Anchor+Skills W2 roster expansion. Vendors each
source skill into ``<dest>/vendor/bundled-skills/<name>/`` via
``git archive <commit>`` (which auto-drops ``.git/`` and untracked/gitignored
files), THEN applies an explicit DENYLIST filter (because ``git archive`` KEEPS
*tracked* files even if they match a ``.gitignore`` pattern — a committed
personal log would otherwise ship), THEN a residual host-path / PII / secret
scrub over the remaining text files, and finally writes ``SOURCES.md``
recording each skill's source + archived commit sha.

Roster expansion is **config-only** (``SKILL_SOURCES`` / ``CANARY_SKILL_SOURCES``).
The archive + denylist-apply + residual-scrub APIs stay frozen unless a
gap-proof redesign ticket says otherwise.

Stdlib only: ``subprocess`` (git), ``pathlib``, ``shutil``, ``re``, ``tarfile``.
Best-effort + honest: a missing / unset source env is an honest SKIP with a
clear message — never a fallback to a hardcoded real author path.
Money-safe: only local ``git -C <repo>``; no network publish, no paid CLI.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tarfile
from pathlib import Path

# --------------------------------------------------------------------------- #
# Source configuration (config-only roster expansion — W2)
# --------------------------------------------------------------------------- #
# Each entry: skill name -> (env var holding the source REPO, subdir within
# that repo holding the skill — "" means the repo root IS the skill).
#
#   ANCHOR_TRIO_DIR     — trio monorepo (researchPrime/crucible/foreman subdirs)
#   ANCHOR_GANDALF_DIR  — Gandalf skill at repo root (back-compat baseline)
#   ANCHOR_FOUNDRY_DIR  — Skill Foundry monorepo (skills/<name> subdirs)
#
# Full declared suite toward capability matrix / NS D8 (vendorable skills).
# Anchor Doctor is an Anchor feature, not a vendored skill — not listed here.
SKILL_SOURCES = [
    ("researchPrime", "ANCHOR_TRIO_DIR", "researchPrime"),
    ("crucible", "ANCHOR_TRIO_DIR", "crucible"),
    ("foreman", "ANCHOR_TRIO_DIR", "foreman"),
    ("gandalf", "ANCHOR_GANDALF_DIR", ""),
    ("jumper", "ANCHOR_FOUNDRY_DIR", "skills/jumper"),
    ("ramanujan", "ANCHOR_FOUNDRY_DIR", "skills/ramanujan"),
    ("legal-beagle", "ANCHOR_FOUNDRY_DIR", "skills/legal-beagle"),
    ("literature-review", "ANCHOR_FOUNDRY_DIR", "skills/literature-review"),
    ("financial-analyst", "ANCHOR_FOUNDRY_DIR", "skills/financial-analyst"),
    ("tidy-idy", "ANCHOR_FOUNDRY_DIR", "skills/tidy-idy"),
    ("zombie-hunter", "ANCHOR_FOUNDRY_DIR", "skills/zombie-hunter"),
    # v1.2.3: the Ecgberht steward. Repo root IS the skill (the gandalf shape).
    # Anchor already shipped its HOST CONTRACTS (the chamber_* modules) while
    # the skill itself stayed home — collaborators had steward-shaped Anchor
    # surface with no steward behind it. Its campaign record is stripped by the
    # scoped denials above; only the engine ships.
    ("ecgberht", "ANCHOR_ECGBERHT_DIR", ""),
]

# Early canary (W2): one Trio skill + one large Foundry skill through the
# frozen git-archive → denylist → residual scrub → SOURCES path.
CANARY_SKILL_SOURCES = [
    ("foreman", "ANCHOR_TRIO_DIR", "foreman"),
    ("literature-review", "ANCHOR_FOUNDRY_DIR", "skills/literature-review"),
]

VENDOR_SUBPATH = ("vendor", "bundled-skills")

_GIT_TIMEOUT = 120

# Author data dirs / secret-shaped artifacts that must NEVER appear in a
# stranger-facing shippable bundle (asserted by W2 money-safe packaging tests).
# The distro deny-by-default manifest is the real allowlist; this tuple names
# the high-risk prefixes/names the canary + stranger-tree checks refuse.
BUNDLE_AUTHOR_EXCLUDES = (
    "domains/",
    "logs/",
    "health_reports/",
    "planning/",
    ".anchor/",
    "DASHBOARD.md",
    "PROJECTS.md",
    "INBOX.md",
    "rnd_registry.json",
    "foreman-checkpoint.json",
    "planted_secret",
    "planted_leak",
    "CANCELLED.md",
    "SAVED_FOR_LATER.md",
)

# --------------------------------------------------------------------------- #
# Denylist — tracked-but-personal files git archive would otherwise keep.
# --------------------------------------------------------------------------- #
# Exact basenames (case-insensitive) anywhere in the tree.
_DENY_BASENAMES = {
    "execution-log.md",
    "decision-log.md",
    "claude_hist.md",
    "_foreman-status.log",
    "_foreman-output.log",
    "_foreman-error.log",
    "handoff.md",
}
# Path components (directory names) that, if present, drop the whole subtree.
_DENY_DIR_COMPONENTS = {
    "journal",
    ".foreman",
    "runs",
    "planning",
    "_archive",
    "scratch",
    "litreview-out",
    # v1.1.3 share-fix: skill self-test suites are DEV-ONLY and carry planted
    # secret/token fixtures BY DESIGN (e.g. tidy-idy's secret-triage tests) —
    # exactly the class Anchor deny-lists from its own shipped tests. A
    # consumer bundle never runs a skill's own test suite, so the trees are
    # dead weight that can only trip the fail-closed ship scan.
    "test",
    "tests",
}
# PER-SKILL denials (v1.2.3, added for the Ecgberht steward).
#
# The steward is a campaign-memory skill: its repo is ~970 files, and most of
# them are the AUTHOR'S OWN portfolio record — what the steward learned about
# John's projects — not product. The generic list above already drops the bulk
# (planning / test / journal / .foreman = 487 files), but the rest carry names
# too generic to deny globally: a future skill may legitimately ship a
# ``research/`` or ``drafts/`` directory as product. Scoping them to the one
# skill that must not export them keeps the global list honest.
#
# Cross-family review (2026-08-15) confirmed the engine does not read these at
# runtime: ``rank.mjs`` scores Strip projections only, ``loadDispatchTable()``
# falls back to ``BUILTIN_CELLS``, ``prior-art/`` and ``ideation/`` have no
# engine or bin load path, and ``listJournalEntries()`` is an optional
# per-PROJECT scan that returns ``present:false`` rather than failing.
_DENY_DIR_COMPONENTS_BY_SKILL = {
    "ecgberht": {
        "e4-skill-plan", "e9-e10-crucible", "ideation", "research",
        "artifacts", "drafts", "mockups", "prior-art",
        # The steward's OWN live runtime state (attention.json). Harmless-
        # looking — no project names — but it is the author's cell, so a
        # stranger's fresh install would open already showing someone else's
        # "needs_you / commission_awaiting_confirm" from 2026-08-03. A steward
        # must start with an empty attention cell, not an inherited one.
        ".ecgberht",
    },
}

#: Root documents that are the author's campaign record or in-flight process,
#: not the shipped skill. ``ecgberht.md`` is the big one: at the steward's repo
#: root it IS John's portfolio memory (per-project copies are minted from
#: ``templates/``, which ships).
_DENY_BASENAMES_BY_SKILL = {
    "ecgberht": {
        "ecgberht.md", "brief-cache.json", "roadmap.json", "strip.json",
        "implementation-plan.md", "foreman.config.json",
        "self-run-checklist.md", "handoff-grok-crucible.md",
        "next-ux-and-anchor-orchestration.md",
        "review-brief-for-external-model.md", "review-fable-2026-07-25.md",
        "vision-correction-2026-07-25.md",
    },
}

# Glob-ish suffix / pattern matches on the basename.
_DENY_BASENAME_SUFFIXES = (
    "-checkpoint.json",
)
# Basename PREFIX denials (v1.1.3): loose skill self-test files living at the
# skill ROOT (e.g. gandalf's test_sdk.py, which references the forbidden
# Gemini SDK) — dev-only, same class as the test/ dir denial above.
_DENY_BASENAME_PREFIXES = (
    "test_",
)
# Directory-name suffix matches (e.g. anything ending in "-out").
_DENY_DIR_SUFFIXES = (
    "-out",
)


def _is_denied(rel: Path, skill: str | None = None) -> bool:
    """Return True if a relative extracted path matches the denylist.

    ``skill`` (optional) additionally applies that skill's scoped denials —
    see :data:`_DENY_DIR_COMPONENTS_BY_SKILL`.
    """
    parts = [p for p in rel.parts]
    base = rel.name.lower()

    key = (skill or "").lower()
    extra_dirs = _DENY_DIR_COMPONENTS_BY_SKILL.get(key, frozenset())
    if extra_dirs and any(c.lower() in extra_dirs for c in parts):
        return True
    if base in _DENY_BASENAMES_BY_SKILL.get(key, frozenset()):
        return True

    # Directory-component denials (drop the whole subtree).
    for comp in parts[:-1] if not rel.is_dir() else parts:
        cl = comp.lower()
        if cl in _DENY_DIR_COMPONENTS:
            return True
        for suf in _DENY_DIR_SUFFIXES:
            if cl.endswith(suf):
                return True
    # Also test EVERY component as a dir (covers files under a denied dir).
    for comp in parts:
        cl = comp.lower()
        if cl in _DENY_DIR_COMPONENTS:
            return True
        for suf in _DENY_DIR_SUFFIXES:
            if cl.endswith(suf):
                return True

    # Exact basename denials.
    if base in _DENY_BASENAMES:
        return True
    for suf in _DENY_BASENAME_SUFFIXES:
        if base.endswith(suf):
            return True
    for pre in _DENY_BASENAME_PREFIXES:
        if base.startswith(pre):
            return True

    # .env* — drop everything EXCEPT .env.example.
    if base == ".env" or (base.startswith(".env") and base != ".env.example"):
        return True

    return False


# --------------------------------------------------------------------------- #
# Residual host-path / PII / secret scrub (rules expanded in W2; API frozen).
# --------------------------------------------------------------------------- #
# Windows dev paths: C:\...\dev\... or C:\dev\... (any drive letter).
_WIN_DEV_RE = re.compile(
    r"[A-Za-z]:\\(?:[^\s\"'<>|]*\\)?dev\\[^\s\"'<>|]*",
)
# Forward-slash Windows dev paths (often in ESM imports / markdown): C:/dev/...
_WIN_DEV_FWD_RE = re.compile(
    r"[A-Za-z]:/(?:[^\s\"'<>|]*/)?dev/[^\s\"'<>|]*",
    re.IGNORECASE,
)
# file:// URLs with host paths (e.g. file:///C:/dev/Skill%20Foundry/...)
_FILE_URL_HOST_RE = re.compile(
    r"file:///[A-Za-z]:/(?:Users|dev|home)[^\s\"'<>|]*",
    re.IGNORECASE,
)
# Windows user-profile paths (a drive letter, the Users dir, an account, then a
# further segment — any drive). Scrubbed so a vendored file (esp. SOURCES.md,
# which records the host source repo path) never embeds the build host's
# user-profile tree — the distro scanner's user-profile-path detector runs over
# vendor/ too, so this must be scrubbed.
_WIN_USER_RE = re.compile(
    r"[A-Za-z]:\\Users\\[^\s\"'<>|]*",
    re.IGNORECASE,
)
_WIN_USER_FWD_RE = re.compile(
    r"[A-Za-z]:/Users/[^\s\"'<>|]*",
    re.IGNORECASE,
)
# POSIX home paths: /Users/example/... and /home/example/...
_POSIX_HOME_RE = re.compile(
    r"/(?:Users|home)/[^/\s\"'<>|]+(?:/[^\s\"'<>|]*)?",
)
# Obvious example / personal emails.
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
)
# Concrete secret shapes (W2 residual secret scrub expansion).
_AWS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_OPENAI_SK_RE = re.compile(r"\bsk-[A-Za-z0-9]{16,}\b")
_GHP_RE = re.compile(r"\bghp_[A-Za-z0-9]{20,}\b")
_GHO_RE = re.compile(r"\bgho_[A-Za-z0-9]{20,}\b")
_JWT_RE = re.compile(
    r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"
)
_BEARER_RE = re.compile(r"Bearer\s+[A-Za-z0-9._\-]{24,}")

# Binary-ish suffixes we never try to scrub as text.
_BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tar",
    ".woff", ".woff2", ".ttf", ".eot", ".so", ".dll", ".pyc", ".exe", ".bin",
    ".wasm", ".node",
}


def _scrub_text(text: str) -> str:
    text = _WIN_DEV_RE.sub("<path>", text)
    text = _WIN_DEV_FWD_RE.sub("<path>", text)
    text = _FILE_URL_HOST_RE.sub("<path>", text)
    # JSDoc / import() host paths that use mixed quoting
    text = re.sub(
        r"import\(['\"][A-Za-z]:[/\\][^\s'\"]+['\"]\)",
        "import('<path>')",
        text,
    )
    text = _WIN_USER_RE.sub("<path>", text)
    text = _WIN_USER_FWD_RE.sub("<path>", text)
    text = _POSIX_HOME_RE.sub("<path>", text)
    # Broad C:/dev or C:\dev (comments, provenance, defaults)
    text = re.sub(
        r"[A-Za-z]:[/\\]+dev(?:[/\\][^\s\"'<>|]*)?",
        "<path>",
        text,
        flags=re.IGNORECASE,
    )
    text = _EMAIL_RE.sub("<email>", text)
    text = _AWS_KEY_RE.sub("<secret>", text)
    text = _OPENAI_SK_RE.sub("<secret>", text)
    text = _GHP_RE.sub("<secret>", text)
    text = _GHO_RE.sub("<secret>", text)
    text = _JWT_RE.sub("<secret>", text)
    text = _BEARER_RE.sub("Bearer <secret>", text)
    return text


def _scrub_file(path: Path) -> None:
    if path.suffix.lower() in _BINARY_SUFFIXES:
        return
    try:
        raw = path.read_bytes()
    except OSError:
        return
    # Skip files with NUL bytes (binary).
    if b"\x00" in raw:
        return
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        return
    scrubbed = _scrub_text(text)
    if scrubbed != text:
        try:
            path.write_text(scrubbed, encoding="utf-8")
        except OSError:
            pass


# --------------------------------------------------------------------------- #
# Git helpers
# --------------------------------------------------------------------------- #
def _git(repo, args, timeout=_GIT_TIMEOUT):
    """Run ``git -C <repo> <args>``; return ``(ok, rc, stdout_bytes, stderr)``.

    Never raises for a non-zero exit / missing binary — returns ``ok=False``.
    stdout is returned as BYTES (git archive emits a tar stream).
    """
    cmd = ["git", "-C", str(repo)] + [str(a) for a in args]
    try:
        proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return False, None, b"", "git invocation failed: %s" % exc
    stderr = (proc.stderr or b"").decode("utf-8", "replace")
    return (proc.returncode == 0, proc.returncode, proc.stdout or b"", stderr)


def _resolve_head(repo) -> str | None:
    ok, _rc, out, _err = _git(repo, ["rev-parse", "HEAD"])
    if not ok:
        return None
    return out.decode("utf-8", "replace").strip() or None


def _archive_subdir(repo, commit, subdir, dest_dir) -> bool:
    """``git archive <commit> [-- <subdir>]`` extracted into ``dest_dir``.

    Drops the leading ``<subdir>/`` component so the skill's own files land at
    ``dest_dir`` root. Returns True on success.
    """
    args = ["archive", "--format=tar", commit]
    if subdir:
        args += ["--", subdir]
    ok, _rc, tar_bytes, _err = _git(repo, args)
    if not ok or not tar_bytes:
        return False

    strip = subdir.strip("/").split("/") if subdir else []
    n_strip = len(strip)

    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:") as tf:
            for member in tf.getmembers():
                name = member.name
                comps = name.split("/")
                if n_strip:
                    if comps[:n_strip] != strip:
                        continue
                    comps = comps[n_strip:]
                if not comps or comps == [""]:
                    continue
                rel = Path(*comps)
                # Guard against path traversal in the tar.
                if ".." in rel.parts or rel.is_absolute():
                    continue
                target = dest_dir / rel
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                elif member.isreg():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    f = tf.extractfile(member)
                    if f is None:
                        continue
                    target.write_bytes(f.read())
                # Skip symlinks/devices — not shippable skill content.
    except (tarfile.TarError, OSError):
        return False
    return True


# --------------------------------------------------------------------------- #
# Denylist + scrub passes over the extracted tree
# --------------------------------------------------------------------------- #
def _apply_denylist(skill_dir: Path, skill: str | None = None) -> None:
    """Strip denied paths from an extracted skill tree.

    ``skill`` opts the tree into that skill's SCOPED denials on top of the
    global list (see ``_DENY_DIR_COMPONENTS_BY_SKILL``).
    """
    skill_dir = Path(skill_dir)
    if not skill_dir.exists():
        return
    # Walk bottom-up so removing dirs is safe.
    for root, dirs, files in os.walk(skill_dir, topdown=False):
        root_p = Path(root)
        for name in files:
            p = root_p / name
            rel = p.relative_to(skill_dir)
            if _is_denied(rel, skill):
                try:
                    p.unlink()
                except OSError:
                    pass
        for name in dirs:
            d = root_p / name
            rel = d.relative_to(skill_dir)
            # A directory whose name (or an ancestor) is denied.
            if _is_denied(Path(*rel.parts), skill):
                shutil.rmtree(d, ignore_errors=True)
    # Prune any now-empty directories left behind.
    for root, dirs, files in os.walk(skill_dir, topdown=False):
        rp = Path(root)
        if rp == skill_dir:
            continue
        try:
            if not any(rp.iterdir()):
                rp.rmdir()
        except OSError:
            pass


def _scrub_tree(skill_dir: Path) -> None:
    for root, _dirs, files in os.walk(skill_dir):
        for name in files:
            _scrub_file(Path(root) / name)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def declared_skill_names():
    """Ordered skill names from the full declared-suite roster config."""
    return [name for name, _env, _subdir in SKILL_SOURCES]


def canary_skill_names():
    """Ordered skill names for the W2 early canary (one Trio + one Foundry)."""
    return [name for name, _env, _subdir in CANARY_SKILL_SOURCES]


def vendor_canary(dest, sources=None):
    """Early canary vendoring path (W2).

    Runs the frozen archive → denylist → residual scrub → SOURCES pipeline for
    ``CANARY_SKILL_SOURCES`` (or an explicit ``sources`` override). Does not
    rewrite archive/scrub APIs — delegates entirely to :func:`vendor_all`.
    """
    return vendor_all(
        dest,
        sources=sources if sources is not None else CANARY_SKILL_SOURCES,
    )


def vendor_all(dest, sources=None):
    """Vendor each configured skill into ``<dest>/vendor/bundled-skills/``.

    ``sources`` (optional) overrides ``SKILL_SOURCES`` — a list of
    ``(name, env_var, subdir)`` tuples. Each source repo is resolved from its
    env var; an UNSET/missing/non-repo source is an honest SKIP (never a
    hardcoded-real-path fallback).

    Returns a dict report::

        {"vendored": [{name, source, commit, dest}], "skipped": [{name, reason}]}

    Writes ``<dest>/vendor/bundled-skills/SOURCES.md`` (only the vendored ones).
    """
    if sources is None:
        sources = SKILL_SOURCES

    dest = Path(dest)
    bundle_root = dest.joinpath(*VENDOR_SUBPATH)
    bundle_root.mkdir(parents=True, exist_ok=True)

    vendored = []
    skipped = []

    for name, env_var, subdir in sources:
        src = os.environ.get(env_var)
        if not src:
            skipped.append({
                "name": name,
                "reason": "source env %s is unset — refusing (no fallback)" % env_var,
            })
            continue
        src_path = Path(src)
        if not src_path.exists():
            skipped.append({
                "name": name,
                "reason": "source path %r (%s) does not exist" % (src, env_var),
            })
            continue
        commit = _resolve_head(src_path)
        if not commit:
            skipped.append({
                "name": name,
                "reason": "%r is not a git repo / has no HEAD" % src,
            })
            continue

        skill_dir = bundle_root / name
        # Clean any prior vendoring of this skill (idempotent re-vendor).
        if skill_dir.exists():
            shutil.rmtree(skill_dir, ignore_errors=True)

        if not _archive_subdir(src_path, commit, subdir, skill_dir):
            shutil.rmtree(skill_dir, ignore_errors=True)
            skipped.append({
                "name": name,
                "reason": "git archive of %r at %s failed or empty" % (subdir or "<root>", commit[:12]),
            })
            continue

        # THE POINT OF THE WAVE: denylist AFTER extraction (git archive keeps
        # tracked personal logs).
        _apply_denylist(skill_dir, name)
        # Residual host-path / PII scrub.
        _scrub_tree(skill_dir)

        vendored.append({
            "name": name,
            "source": str(src_path),
            "commit": commit,
            "dest": str(skill_dir),
        })

    # Runtime support for trio engines (ship-safe 2026-07-24):
    # foreman/crucible/researchPrime import ../../drivers and @foundry/triage
    # wires. Without these, collaborator packages cannot load.
    support = vendor_trio_runtime_support(bundle_root)
    if support.get("vendored"):
        vendored.extend(support["vendored"])
    if support.get("skipped"):
        skipped.extend(support["skipped"])

    _write_sources_md(bundle_root, vendored)

    return {"vendored": vendored, "skipped": skipped}


def vendor_trio_runtime_support(bundle_root: Path) -> dict:
    """Archive trio/drivers + foundry/triage next to bundled skills.

    Layout (imports resolve for skills/<name>/bin → ../../drivers):

      bundled-skills/drivers/          # from ANCHOR_TRIO_DIR
      bundled-skills/foundry/triage/   # from ANCHOR_FOUNDRY_DIR (resolver also
                                       # checks ANCHOR_FOUNDRY_DIR env at runtime)

    When source env vars are unset, this is a **silent no-op** (no skip rows) so
    roster honesty tests stay SKILL_SOURCES-shaped. Ship builders set the envs.
    """
    bundle_root = Path(bundle_root)
    vendored = []
    skipped = []

    trio = os.environ.get("ANCHOR_TRIO_DIR")
    if trio and Path(trio).exists() and (Path(trio) / "drivers").is_dir():
        src = Path(trio)
        commit = _resolve_head(src)
        if commit:
            dest = bundle_root / "drivers"
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            if _archive_subdir(src, commit, "drivers", dest):
                _apply_denylist(dest)
                _scrub_tree(dest)
                vendored.append({
                    "name": "drivers",
                    "source": str(src),
                    "commit": commit,
                    "dest": str(dest),
                })
            else:
                skipped.append({"name": "drivers", "reason": "git archive drivers failed"})
        else:
            skipped.append({"name": "drivers", "reason": "trio has no HEAD"})
    # else: env unset or no drivers/ tree → no-op (canary fixtures)

    foundry = os.environ.get("ANCHOR_FOUNDRY_DIR") or os.environ.get("SKILL_FOUNDRY_DIR")
    triage_src = Path(foundry) / "foundry" / "triage" if foundry else None
    if foundry and Path(foundry).exists() and triage_src is not None and triage_src.is_dir():
        src = Path(foundry)
        commit = _resolve_head(src)
        if commit:
            dest = bundle_root / "foundry" / "triage"
            if dest.exists():
                shutil.rmtree(dest, ignore_errors=True)
            if _archive_subdir(src, commit, "foundry/triage", dest):
                _apply_denylist(dest)
                _scrub_tree(dest)
                vendored.append({
                    "name": "foundry-triage",
                    "source": str(src),
                    "commit": commit,
                    "dest": str(dest),
                })
            else:
                skipped.append({"name": "foundry-triage", "reason": "git archive foundry/triage failed"})
        else:
            skipped.append({"name": "foundry-triage", "reason": "foundry has no HEAD"})
    # else: env unset or no foundry/triage tree → no-op
    return {"vendored": vendored, "skipped": skipped}


def _write_sources_md(bundle_root: Path, vendored) -> None:
    lines = [
        "# Bundled skills — provenance",
        "",
        "These skills were vendored via `git archive <commit>` (no `.git/`, no",
        "gitignored junk) with a denylist + host-path/PII scrub applied after",
        "extraction. The archived commit sha below is the honest provenance.",
        "",
        "| Skill | Source | Archived commit |",
        "|-------|--------|-----------------|",
    ]
    for v in vendored:
        # The SOURCES.md path is itself scrubbed of the host source path.
        src_disp = _scrub_text(v["source"])
        lines.append("| %s | %s | `%s` |" % (v["name"], src_disp, v["commit"]))
    if not vendored:
        lines.append("| _(none vendored)_ | | |")
    lines.append("")
    (bundle_root / "SOURCES.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":  # pragma: no cover
    import json
    import sys
    out = sys.argv[1] if len(sys.argv) > 1 else "."
    report = vendor_all(out)
    print(json.dumps(report, indent=2))
