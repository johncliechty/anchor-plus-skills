"""vendor_skills.py — clean vendoring of the bundled trio + Gandalf skills.

Share-distro Wave 3. Vendors each source skill into
``<dest>/vendor/bundled-skills/<name>/`` via ``git archive <commit>`` (which
auto-drops ``.git/`` and untracked/gitignored files), THEN applies an explicit
DENYLIST filter (because ``git archive`` KEEPS *tracked* files even if they
match a ``.gitignore`` pattern — a committed personal log would otherwise
ship), THEN a residual host-path / PII scrub over the remaining text files, and
finally writes ``SOURCES.md`` recording each skill's source + archived commit
sha.

Stdlib only: ``subprocess`` (git), ``pathlib``, ``shutil``, ``re``, ``tarfile``.
Best-effort + honest: a missing / unset source env is an honest SKIP with a
clear message — never a fallback to a hardcoded real author path.
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
# Source configuration
# --------------------------------------------------------------------------- #
# Each entry: skill name -> (env var holding the source REPO, subdir within
# that repo holding the skill — "" means the repo root IS the skill).
# The trio repo (ANCHOR_TRIO_DIR) holds researchPrime/crucible/foreman subdirs;
# Gandalf lives at the root of its own repo (ANCHOR_GANDALF_DIR).
SKILL_SOURCES = [
    ("researchPrime", "ANCHOR_TRIO_DIR", "researchPrime"),
    ("crucible", "ANCHOR_TRIO_DIR", "crucible"),
    ("foreman", "ANCHOR_TRIO_DIR", "foreman"),
    ("gandalf", "ANCHOR_GANDALF_DIR", ""),
]

VENDOR_SUBPATH = ("vendor", "bundled-skills")

_GIT_TIMEOUT = 120

# --------------------------------------------------------------------------- #
# Denylist — tracked-but-personal files git archive would otherwise keep.
# --------------------------------------------------------------------------- #
# Exact basenames (case-insensitive) anywhere in the tree.
_DENY_BASENAMES = {
    "execution-log.md",
    "decision-log.md",
    "claude_hist.md",
}
# Path components (directory names) that, if present, drop the whole subtree.
_DENY_DIR_COMPONENTS = {
    "journal",
    ".foreman",
    "runs",
}
# Glob-ish suffix / pattern matches on the basename.
_DENY_BASENAME_SUFFIXES = (
    "-checkpoint.json",
)
# Directory-name suffix matches (e.g. anything ending in "-out").
_DENY_DIR_SUFFIXES = (
    "-out",
)


def _is_denied(rel: Path) -> bool:
    """Return True if a relative extracted path matches the denylist."""
    parts = [p for p in rel.parts]
    base = rel.name.lower()

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

    # .env* — drop everything EXCEPT .env.example.
    if base == ".env" or (base.startswith(".env") and base != ".env.example"):
        return True

    return False


# --------------------------------------------------------------------------- #
# Residual host-path / PII scrub.
# --------------------------------------------------------------------------- #
# Windows dev paths: C:\...\dev\... or C:\dev\... (any drive letter).
_WIN_DEV_RE = re.compile(
    r"[A-Za-z]:\\(?:[^\s\"'<>|]*\\)?dev\\[^\s\"'<>|]*",
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
# POSIX home paths: /Users/example/... and /home/example/...
_POSIX_HOME_RE = re.compile(
    r"/(?:Users|home)/[^/\s\"'<>|]+(?:/[^\s\"'<>|]*)?",
)
# Obvious example / personal emails.
_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}",
)

# Binary-ish suffixes we never try to scrub as text.
_BINARY_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".gz", ".tar",
    ".woff", ".woff2", ".ttf", ".eot", ".so", ".dll", ".pyc", ".exe", ".bin",
    ".wasm", ".node",
}


def _scrub_text(text: str) -> str:
    text = _WIN_DEV_RE.sub("<path>", text)
    text = _WIN_USER_RE.sub("<path>", text)
    text = _POSIX_HOME_RE.sub("<path>", text)
    text = _EMAIL_RE.sub("<email>", text)
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
def _apply_denylist(skill_dir: Path) -> None:
    skill_dir = Path(skill_dir)
    if not skill_dir.exists():
        return
    # Walk bottom-up so removing dirs is safe.
    for root, dirs, files in os.walk(skill_dir, topdown=False):
        root_p = Path(root)
        for name in files:
            p = root_p / name
            rel = p.relative_to(skill_dir)
            if _is_denied(rel):
                try:
                    p.unlink()
                except OSError:
                    pass
        for name in dirs:
            d = root_p / name
            rel = d.relative_to(skill_dir)
            # A directory whose name (or an ancestor) is denied.
            if _is_denied(Path(*rel.parts)):
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
        _apply_denylist(skill_dir)
        # Residual host-path / PII scrub.
        _scrub_tree(skill_dir)

        vendored.append({
            "name": name,
            "source": str(src_path),
            "commit": commit,
            "dest": str(skill_dir),
        })

    _write_sources_md(bundle_root, vendored)

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
