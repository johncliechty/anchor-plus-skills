"""Capture COPIES of every real live-campaign ledger into committed fixtures.

Steward-chamber W5 (the plan's words): the brownfield derivation is
"fixture-tested against copies of every real live-campaign ledger" — real
on-disk ledgers, not synthetic shapes. This script makes those copies and
commits the FIXTURE-SIZE RECORD (event count, MB on disk, run-record count
of the largest real ledger) that W6's budget fixtures MUST be generated at
>= 2x of, per metric.

WHAT IS COPIED (the chamber's W5 read set, and nothing more):
    roadmap.json                        — roadmap_events + roadmap_projection
    ECGBERHT.md                         — the Face (goal-guard / north star)
    .ecgberht/attention.json            — the attention cell (brief seed)
    .anchor/commission-runs/*.json      — the Anchor-side run records
Conversation logs, dossiers, envelope ledgers and other campaign material are
NOT copied (they are measured into the full-ledger byte count, but their
content stays out of the repo).

SCRUBBING: any absolute user-home path (the Windows ``<drive>:\Users\<name>``
form, ``/Users/<name>`` on macOS, ``/home/<name>`` on Linux) inside a copied
file is replaced with the literal placeholder
``<home>`` — fixture copies never embed a host home path. Scrubbed files are
named in the fixture manifest. Nothing else is altered: the copies otherwise
stay byte-faithful so the derivation tests run against REAL shapes.

RE-RUNNING: deterministic given the same on-disk campaigns — delete the
campaign dirs here and run ``python refresh_real_ledgers.py`` from this
folder (the dev root resolves relative to this file; override with
ANCHOR_DEV_ROOT). Captured-at is a recorded fact, not part of any
determinism claim.

Stdlib only. READ-ONLY over the live campaigns — this script never writes
into a campaign folder.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES_ROOT = HERE / "real-ledgers"
MANIFEST_PATH = FIXTURES_ROOT / "fixture-manifest.json"

SCHEMA_VERSION = 1


def dev_root() -> Path:
    env = os.environ.get("ANCHOR_DEV_ROOT", "").strip()
    if env:
        return Path(env)
    # tests/fixtures/chamber -> tests/fixtures -> tests -> <anchor root> -> <dev root>
    return HERE.parents[2].parent


#: Every real live campaign on disk (a folder carrying roadmap.json and/or a
#: .ecgberht store), slug -> path parts under the dev root. The frozen
#: _ecgberht-backup-* snapshot and .anchor/worktrees/* session copies are
#: EXCLUDED by name below — they are copies of campaigns, not live campaigns.
CAMPAIGNS = {
    "ecgberht": ("Ecgberht",),
    "family-trusts": ("Family Trusts",),
    "family-finances": ("Family-Finances",),
    "axmra-holding-company": ("Axmra", "Holding Company"),
    "mba-teaching-ai": ("MBA Teaching AI",),
    "mba-teaching-with-ai": ("MBA Teaching AI", "MBA Teaching with AI"),
}

EXCLUSIONS = [
    {"path": "MBA Teaching AI/_ecgberht-backup-20260806-082232",
     "reason": "frozen backup snapshot of mba-teaching-ai — a copy, not a "
               "live campaign"},
    {"path": "Anchor/.anchor/worktrees/*",
     "reason": "per-session worktree checkouts — session copies of a "
               "campaign's ledger, not campaigns"},
]

#: The read-set files copied per campaign (relative to the campaign folder).
READ_SET_FILES = ("roadmap.json", "ECGBERHT.md",
                  os.path.join(".ecgberht", "attention.json"))
RUN_RECORDS_REL = os.path.join(".anchor", "commission-runs")

#: Absolute user-home paths never ride into the repo.
_HOME_PATH = re.compile(
    r"(?:[A-Za-z]:)?[\\/](?:\\\\|/)?(?:Users|home)(?:\\\\|[\\/])+[^\\/\"'\s]+")


def _scrub(text: str) -> tuple:
    scrubbed = _HOME_PATH.sub("<home>", text)
    return scrubbed, scrubbed != text


def _dir_bytes(p: Path) -> int:
    if not p.is_dir():
        return 0
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file())


def _copy_file(src: Path, dst: Path, scrubbed_files: list, rel: str) -> int:
    text = src.read_text(encoding="utf-8")
    text, was_scrubbed = _scrub(text)
    if was_scrubbed:
        scrubbed_files.append(rel)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(text, encoding="utf-8", newline="\n")
    return dst.stat().st_size


def capture_campaign(slug: str, folder: Path) -> dict:
    """Copy one campaign's read-set files; measure the FULL ledger on disk."""
    out_dir = FIXTURES_ROOT / slug
    scrubbed: list = []
    copied: list = []
    copied_bytes = 0

    for rel in READ_SET_FILES:
        src = folder / rel
        if src.is_file():
            copied_bytes += _copy_file(src, out_dir / rel, scrubbed,
                                       rel.replace("\\", "/"))
            copied.append(rel.replace("\\", "/"))

    run_record_count = 0
    runs_dir = folder / RUN_RECORDS_REL
    if runs_dir.is_dir():
        for src in sorted(runs_dir.glob("*.json")):
            rel = (RUN_RECORDS_REL + os.sep + src.name).replace("\\", "/")
            copied_bytes += _copy_file(src, out_dir / RUN_RECORDS_REL / src.name,
                                       scrubbed, rel)
            copied.append(rel)
            run_record_count += 1

    event_count = 0
    step_count = 0
    roadmap = folder / "roadmap.json"
    if roadmap.is_file():
        try:
            doc = json.loads(roadmap.read_text(encoding="utf-8"))
            event_count = len(doc.get("roadmap_events") or [])
            step_count = len(doc.get("roadmap_projection") or [])
        except ValueError:
            pass

    # The FULL ledger on disk (roadmap + the whole .ecgberht store + run
    # records) — the honest open-read-set size the W6 budget keys off, which
    # includes stores (conversation log, dossiers) whose CONTENT is not
    # copied here.
    full_bytes = 0
    if roadmap.is_file():
        full_bytes += roadmap.stat().st_size
    full_bytes += _dir_bytes(folder / ".ecgberht")
    full_bytes += _dir_bytes(runs_dir)

    return {
        "slug": slug,
        "event_count": event_count,
        "step_count": step_count,
        "run_record_count": run_record_count,
        "bytes_full_ledger": full_bytes,
        "mb_full_ledger": round(full_bytes / (1024 * 1024), 6),
        "bytes_copied": copied_bytes,
        "copied_files": copied,
        "scrubbed_files": scrubbed,
    }


def main() -> int:
    root = dev_root()
    rows = []
    for slug, parts in sorted(CAMPAIGNS.items()):
        folder = root.joinpath(*parts)
        if not folder.is_dir():
            print(f"SKIP {slug}: campaign folder not found under {root}")
            continue
        rows.append(capture_campaign(slug, folder))
        print(f"captured {slug}: {rows[-1]['event_count']} events, "
              f"{rows[-1]['run_record_count']} run records, "
              f"{rows[-1]['bytes_full_ledger']} full-ledger bytes")

    largest = {
        "event_count": max(r["event_count"] for r in rows),
        "run_record_count": max(r["run_record_count"] for r in rows),
        "bytes_full_ledger": max(r["bytes_full_ledger"] for r in rows),
        "mb_full_ledger": max(r["mb_full_ledger"] for r in rows),
    }
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "artifact": "chamber-real-ledger-fixtures",
        "owner_file": "tests/fixtures/chamber/refresh_real_ledgers.py",
        "plan_ref": "planning/steward-chamber-2026-08-09/IMPLEMENTATION-PLAN.md"
                    " :: Wave 5 (fixture-size record; W6 >=2x budget fixtures)",
        "captured_at": time.strftime("%Y-%m-%d"),
        "campaigns": rows,
        "excluded": EXCLUSIONS,
        "largest_real_ledger": largest,
        "w6_budget_rule": {
            "rule": "W6's synthetic budget fixtures MUST be generated at >= "
                    "2x EACH measured number of the largest real ledger "
                    "(events, MB on disk, run records).",
            "min_event_count": largest["event_count"] * 2,
            "min_run_record_count": largest["run_record_count"] * 2,
            "min_bytes": largest["bytes_full_ledger"] * 2,
        },
    }
    FIXTURES_ROOT.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2) + "\n",
                             encoding="utf-8", newline="\n")
    print(f"wrote {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
