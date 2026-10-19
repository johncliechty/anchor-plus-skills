"""One-shot clean ship package builder — THIN WRAPPER (v1.1.3 share-fix).

HISTORY / WHY THIS IS NOW THIN. Until v1.1.3 this script was a SECOND builder:
it started from ``distro.select_shippable()`` but then hand-globbed ~30 extra
files past the manifest, never ran the startup-import gate, and PRINTED its
PII/import scan results instead of failing on them. The package collaborators
received in the 1.1.x share came from THIS script — which is how eleven
runtime modules could be missing while every gate stayed green
(``friction-intake-2026-07-30.md``). Two builders with different file sets was
the root cause; one must win.

NOW: ``distro.py`` is the ONE blessed builder. The manifest owns the file set
(the cold-start/share surface this script used to glob is listed there), and
``distro.build_distro`` FAIL-CLOSES on the no-personal-data scan, the
import-closure gate, and the startup-import gate. This wrapper only:

  1. points the skill-vendoring env at the author machine's source repos
     (packaging-time only; never baked into shipped files),
  2. builds Package B by CALLING ``distro.build_distro`` (any gate hit raises
     — nothing here filters, downgrades, or prints-and-continues), and
  3. composes Package A (skills-only) from B's already-gated tree + the
     cold-start subset, re-running the SAME fail-closed scans over A.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Runnable from anywhere: the repo root carries the modules, not planning/.
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import distro                      # noqa: E402
import share_governance as gov     # noqa: E402
import vendor_skills as vs         # noqa: E402
# v1.1.3: built trees live OUTSIDE the repo (default <repo-parent>/Anchor-ship,
# override via ANCHOR_SHIP_OUT). The old in-repo planning/…/package-v1 output
# accumulated 61MB of stale product duplicates that agents crawled, hygiene
# tests tripped over, and nobody could tell apart from the real shipped zip.
OUT = Path(os.environ.get("ANCHOR_SHIP_OUT")
           or (ROOT.parent / "Anchor-ship")) / "clean-ship"

# Author machine layout for packaging only (never baked into shipped files).
os.environ.setdefault("ANCHOR_TRIO_DIR", r"C:\dev\trio")
os.environ.setdefault("ANCHOR_FOUNDRY_DIR", r"C:\dev\Skill Foundry")
# Gandalf lives under Foundry on this host (not a separate git root).
os.environ.setdefault("ANCHOR_GANDALF_DIR", r"C:\dev\Skill Foundry")
# The Ecgberht steward is its own git root; the repo root IS the skill.
os.environ.setdefault("ANCHOR_ECGBERHT_DIR", r"C:\dev\Ecgberht")

# Package A cold-start subset (same onboard shell; no Anchor service/desktop
# gate). Everything here is ALSO on dist_manifest.txt — this list only picks
# the skills-only slice out of the gated B surface.
_PACKAGE_A_FILES = (
    "onboard.cmd",
    "onboard.ps1",
    "onboard_cli.py",
    "onboard.py",
    "onboard_bootstrap.py",
    "share_onboard.py",
    "share_agent_rules.py",
    # v1.2.3: the collaborator run contract. Every vendored SKILL.md points at
    # `AGENTS.md`; Package A ships the same skills, so omitting these here
    # would re-create the dangling-pointer defect for skills-only installs
    # (B gets them via distro.emit_share_docs; A composes from B's tree).
    "AGENTS.md",
    "AUTONOMOUS-MODE.md",
    "ELEGANCE.md",
    "share_contracts.py",
    "share_governance.py",
    "share_home_config.py",
    "share_publish.py",
    "share_readiness.py",
    "share_skill_journal.py",
    "share_skill_seal.py",
    "share_skills_root.py",
    "share_capability_matrix.py",
    "share_package_matrix.py",
    "share_feedback.py",
    "share_feedback_intake.py",
    "USER-ONBOARD.md",
    "vendor_skills.py",
    "distro.py",
    "paths.py",
    "VERSION",
    "CHANGELOG.md",
    "share_sources_pin.json",
    "share_freeze_manifest.json",
)

# Package A deliberately omits the Anchor app (anchor.py / anchor_gui.py /
# lanes.py …). onboard.py's uses of those are lazy probes inside try/except
# that degrade honestly, so they are declared optional FOR A ONLY. Package B
# passes nothing extra — its closure must be total.
_PACKAGE_A_OPTIONAL = ("anchor", "lanes", "anchor_gui", "pillar_flags",
                      "verify_freeze_manifest", "share_ci_ship_gate",
                      "share_sources", "share_topology", "gandalf",
                      # distro.py's skill-integrity manifest step imports this
                      # lazily inside try/except (A ships distro for its scan
                      # helpers only; a skills-only tree never builds bundles).
                      "foundry_integrity")


def _scan_package_a(a: Path) -> list:
    """Fail-closed scans over the composed A tree. Returns [] when clean.

    A's skills live at ``skills/`` (not ``vendor/bundled-skills/``), so their
    rels are mapped to the vendored form for the scan — vendored payloads are
    already host-path-scrubbed by vendor_skills and must get the same
    vendored-file semantics (concrete-PII detectors still run; the first-party
    entropy heuristic does not false-fail on skill payloads). Exactly mirrors
    how the same bytes were scanned inside B.
    """
    files = []
    for p in sorted(a.rglob("*")):
        if not p.is_file():
            continue
        rel = str(p.relative_to(a)).replace("\\", "/")
        if rel.startswith("skills/"):
            rel = "vendor/bundled-skills/" + rel[len("skills/"):]
        files.append((rel, p))
    hits = list(distro.scan_paths(files, root=ROOT))
    hits.extend(distro.scan_import_closure(
        files, root=ROOT, extra_optional=_PACKAGE_A_OPTIONAL))
    return hits


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    b = OUT / "B-anchor-plus-skills"
    a = OUT / "A-skills-only"
    a.mkdir(parents=True)

    # Gandalf source override (author layout): skills/gandalf under Foundry.
    sources = []
    for name, env_var, subdir in vs.SKILL_SOURCES:
        if name == "gandalf":
            sources.append((name, "ANCHOR_FOUNDRY_DIR", "skills/gandalf"))
        else:
            sources.append((name, env_var, subdir))

    # ── Package B: the blessed fail-closed build. Any PII / import-closure /
    # startup-import hit RAISES out of here — no filtering, no downgrade.
    report = distro.build_distro(output_dir=b, vendor_sources=sources)
    print("B: %d files staged; all gates clean." % len(report["files"]))

    # ── Package A: skills + governance + the cold-start subset, from B's tree.
    shutil.copytree(b / "vendor" / "bundled-skills", a / "skills")
    gp = a / "governance"
    gp.mkdir()
    for k, v in gov.build_pack_files().items():
        (gp / k).write_text(v, encoding="utf-8")
    for name in _PACKAGE_A_FILES:
        src = b / name          # prefer the GATED staged copy…
        if not src.is_file():
            src = ROOT / name   # …else the source file (e.g. not staged in B)
        if src.is_file():
            shutil.copy2(src, a / name)
    for base in ("share_schemas", "share_governance_pack"):
        d = ROOT / base
        if d.is_dir():
            shutil.copytree(d, a / base, dirs_exist_ok=True)
    (a / "README.md").write_text(
        "# Skills package (A)\n\n"
        "Cold-start: .\\onboard.cmd  (or powershell -File .\\onboard.ps1)\n"
        "Local edits stay local. Installs skills + governance pack.\n",
        encoding="utf-8",
    )

    # ── Fail-closed A scans (same gates, same severity — a hit RAISES).
    hits = _scan_package_a(a)
    if hits:
        shutil.rmtree(a, ignore_errors=True)
        raise distro.PersonalDataError(hits)
    n_a = sum(1 for p in a.rglob("*") if p.is_file())
    print("A: %d files; all gates clean." % n_a)
    print("clean-ship OUT:", OUT)


if __name__ == "__main__":
    main()
