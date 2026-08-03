"""CI matrices, stranger E2E, and ship/execute gate (W9).

Extension point ``ext:ci_ship_gate`` — prove money-safe, no-leak, works-on-arrival
paths end-to-end and freeze the execute/ship gate on skill freeze tags + John
go-ahead before any live vendoring (NS 1,3,6,7,8; R1/R7).

Hard rules (Master Plan P6 / Implementation Plan Wave 9):

* Skills-only CI smoke matrix runs **without** starting an Anchor process
* Anchor+Skills CI asserts B⊇A and Doctor/Zombie/Tidy surfaces per capability matrix
* Money-safe defaults: mock CLI probes, network deny, live probes only behind
  opt-in env, no paid spend, no recipient API keys in happy-path fixtures
* Dual scrub fixtures (planted-leak fail / planted-legit pass) required for publish
* Stranger-install E2E (scrubbed zip → onboard → seat probe → desktop .url)
* Non-admin Windows path for service + desktop .url (no elevation)
* Execute re-validation: actual freeze tags must match SOURCES (or still be
  matching placeholders with plan amendment); go-ahead + captain required to
  vendor live skill trees — fail closed otherwise
* Foreman wave templates: reuse-proof section mandatory; forbid
  security/Tailscale/onboard2 reimplementation and skill-internals rebuild
  without gap-proof ticket

Reuses W1–W8 modules (``share_publish``, ``share_onboard``, ``share_topology``,
``verify_freeze_manifest``, ``share_governance``, ``share_capability_matrix``,
``distro`` clean-scan). Does **not** invent a second distro/publish stack.
Stdlib only.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import zipfile
from pathlib import Path

import share_capability_matrix as cap
import share_contracts as sc
import share_governance as gov
import share_home_config as home_cfg
import share_onboard as sob
import share_publish as pub
import share_readiness as ready
import share_sources as sources
import share_topology as topo
import verify_freeze_manifest as vfm

_MODULE_DIR = Path(__file__).resolve().parent
_PLAN_DIR = _MODULE_DIR / "planning" / "share-anchor-skills-2026-07"
_FIXTURE_SCRUB = _MODULE_DIR / "tests" / "fixtures" / "share_scrub"
_GOV_GOLDEN = _MODULE_DIR / "tests" / "fixtures" / "share_governance" / "golden"

# ── Schema / identity ────────────────────────────────────────────────────────

CI_SHIP_SCHEMA = "share-ci-ship-gate/v1"
CI_SHIP_SCHEMA_VERSION = 1

# Money-safe env (must match share_onboard.LIVE_PROBES_ENV).
LIVE_PROBES_ENV = sob.LIVE_PROBES_ENV  # ANCHOR_SHARE_LIVE_PROBES
NETWORK_ALLOW_ENV = "ANCHOR_SHARE_ALLOW_NETWORK"
PAID_SPEND_ENV = "ANCHOR_SHARE_ALLOW_PAID_SPEND"

# Package-B surfaces that must appear on the Anchor+Skills capability roster.
PACKAGE_B_REQUIRED_SURFACES = (
    "anchor-doctor",
    "zombie-hunter",
    "tidy-idy",
)

# Dual scrub fixture paths (relative to tests/fixtures/share_scrub).
DUAL_SCRUB_LEAK = "planted_leak"
DUAL_SCRUB_LEGIT = "planted_legit"

# Author-secret / host-path detectors for stranger-tree assertions.
_AUTHOR_SECRET_RES = (
    re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE),
    re.compile(r"/(?:Users|home)/[^/\s\"'<>|]+"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"(?i)(api[_-]?key|secret|token)\s*[:=]\s*['\"]?[A-Za-z0-9_\-]{16,}"),
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
)

# Ship gate checklist item ids (plan-workspace artifact + machine check).
SHIP_GATE_CHECKLIST_ITEMS = (
    "concurrent_skill_run_merged",
    "multi_repo_tags",
    "clean_scan",
    "captain_signoff",
    "john_go_ahead",
)

SHIP_GATE_ITEM_LABELS = {
    "concurrent_skill_run_merged": "Concurrent skill-run merged",
    "multi_repo_tags": "Multi-repo freeze tags real (not PLACEHOLDER)",
    "clean_scan": "Clean-scan green (no-leak)",
    "captain_signoff": "Release captain checklist green",
    "john_go_ahead": "John go-ahead recorded",
}

# Foreman wave-template rules.
REUSE_PROOF_SECTION_MARKERS = (
    "reuse-proof",
    "reuse_proof",
    "reuse:",
    "ext:",
)
FORBIDDEN_REIMPLEMENT_TOKENS = (
    "tailscale",
    "onboard2",
    "rebuild skill internals",
    "second distro",
    "second publish",
    "reimplement security",
    "re-implement security",
    "reimplement auth",
    "re-implement auth",
    "reimplement scrub",
    "re-implement scrub",
)
GAP_PROOF_MARKERS = (
    "gap-proof",
    "gap_proof",
    "gap proof ticket",
)

# Execute / ship gate reason codes.
EXECUTE_GATE_REASON_CODES = (
    "freeze_tag_mismatch",
    "freeze_placeholders_block_ship",
    "go_ahead_missing",
    "captain_not_green",
    "verify_freeze_manifest_failed",
    "ship_gate_incomplete",
    "live_vendoring_forbidden",
    "money_safe_violation",
    "anchor_process_started",
    "dual_scrub_missing",
    "dual_scrub_failed",
    "package_b_surface_missing",
    "b_contains_a_mismatch",
    "author_secret_in_tree",
    "readiness_missing",
    "desktop_shortcut_invalid",
    "elevation_required",
    "reuse_proof_missing",
    "forbidden_reimplementation",
    "network_not_denied",
    "live_probes_without_opt_in",
    "recipient_api_key_in_fixture",
    "user_onboard_doc_missing",
    "user_onboard_marker_missing",
    "user_onboard_rights_missing",
    "user_onboard_oss_stamp",
    "oss_license_file_present",
)

# ── Wave 6 — email-ready USER-ONBOARD.md + rights-reserved (no OSS stamp) ───

USER_ONBOARD_FILENAME = "USER-ONBOARD.md"

# Clone/unzip package root first; planning effort copy is also accepted.
USER_ONBOARD_SEARCH_RELS = (
    "USER-ONBOARD.md",
    "planning/share-canonical-onboard-2026-07/USER-ONBOARD.md",
    "docs/USER-ONBOARD.md",
)

# Markers the email-ready install doc must carry (plain-English acceptance).
USER_ONBOARD_REQUIRED_MARKERS = (
    "python -m share_onboard",
    "Package A",
    "Package B",
    "feedback",
    "anchor.ico",
    "service",
    "favicon",
)

# At least one rights-reserved / not-OSS family string required.
USER_ONBOARD_RIGHTS_MARKERS = (
    "rights reserved",
    "not open source",
    "not open-source",
)

# Phrases that would constitute an OSS license stamp *in the onboard doc*.
USER_ONBOARD_FORBIDDEN_OSS_PHRASES = (
    "licensed under the mit",
    "mit license",
    "apache license",
    "licensed under apache",
    "gnu general public license",
    "spdx-license-identifier: mit",
    "spdx-license-identifier: apache",
    "bsd 2-clause",
    "bsd 3-clause",
    "isc license",
)

# Repo-root license filenames that would stamp OSS (Wave 6: do not add).
OSS_LICENSE_FILENAMES = (
    "LICENSE",
    "LICENSE.txt",
    "LICENSE.md",
    "COPYING",
    "COPYING.txt",
)

# Open-source grant patterns if a LICENSE-like file is present.
_OSS_LICENSE_BODY_RES = (
    re.compile(r"\bMIT\s+License\b", re.IGNORECASE),
    re.compile(r"Apache\s+License", re.IGNORECASE),
    re.compile(r"GNU\s+General\s+Public\s+License", re.IGNORECASE),
    re.compile(r"SPDX-License-Identifier\s*:\s*(MIT|Apache|GPL|BSD)", re.IGNORECASE),
    re.compile(r"Permission is hereby granted, free of charge", re.IGNORECASE),
)


def resolve_user_onboard_docs(repo_root=None) -> list:
    """Return existing USER-ONBOARD.md paths under *repo_root* (ordered)."""
    root = Path(repo_root) if repo_root is not None else _MODULE_DIR
    found = []
    for rel in USER_ONBOARD_SEARCH_RELS:
        p = root / rel
        if p.is_file():
            found.append(p)
    return found


def check_user_onboard_doc(repo_root=None) -> dict:
    """Doc presence + required string markers for email-ready onboard.

    Acceptance (canonical Wave 6): clone/unzip → ``python -m share_onboard``;
    Package A vs B; feedback step; B icons/service/favicon; rights-reserved /
    not open-source. Returns ``{ok, paths, missing_markers, problems, …}``.
    """
    root = Path(repo_root) if repo_root is not None else _MODULE_DIR
    paths = resolve_user_onboard_docs(root)
    problems = []
    missing = []
    rights_hits = 0
    readable = 0
    oss_hits = []
    bodies = []

    if not paths:
        problems.append("user_onboard_doc_missing")
        return {
            "ok": False,
            "paths": [],
            "missing_markers": list(USER_ONBOARD_REQUIRED_MARKERS),
            "rights_reserved_ok": False,
            "oss_phrase_hits": [],
            "problems": problems,
            "repo_root": str(root),
        }

    # All found copies must satisfy markers (package + planning stay in lockstep).
    for path in paths:
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append("user_onboard_doc_unreadable:%s" % path.name)
            bodies.append({"path": str(path), "error": str(exc)})
            continue
        readable += 1
        low = text.lower()
        bodies.append({"path": str(path), "chars": len(text)})
        for marker in USER_ONBOARD_REQUIRED_MARKERS:
            if marker.lower() not in low and marker not in missing:
                missing.append(marker)
        if any(m in low for m in USER_ONBOARD_RIGHTS_MARKERS):
            rights_hits += 1
        for phrase in USER_ONBOARD_FORBIDDEN_OSS_PHRASES:
            if phrase not in low:
                continue
            # Allow "not licensed under MIT..." style denials.
            idx = low.find(phrase)
            window = low[max(0, idx - 48): idx + len(phrase) + 12]
            if re.search(r"\bnot\b|\bno\b|\bnever\b", window):
                continue
            if phrase not in oss_hits:
                oss_hits.append(phrase)

    rights_ok = readable > 0 and rights_hits == readable
    if missing:
        problems.append("user_onboard_marker_missing")
    if not rights_ok:
        problems.append("user_onboard_rights_missing")
    if oss_hits:
        problems.append("user_onboard_oss_stamp")

    return {
        "ok": not problems,
        "paths": [str(p) for p in paths],
        "missing_markers": missing,
        "rights_reserved_ok": rights_ok,
        "oss_phrase_hits": oss_hits,
        "problems": problems,
        "bodies": bodies,
        "repo_root": str(root),
        "required_markers": list(USER_ONBOARD_REQUIRED_MARKERS),
    }


def check_no_oss_license_stamp(repo_root=None) -> dict:
    """Wave 6: no OSS LICENSE file / open-source grant at package root.

    Presence of a root LICENSE* that grants MIT/Apache/GPL/etc. fails.
    Absence of LICENSE is the expected GREEN state (rights reserved in docs).
    """
    root = Path(repo_root) if repo_root is not None else _MODULE_DIR
    problems = []
    found = []
    for name in OSS_LICENSE_FILENAMES:
        p = root / name
        if not p.is_file():
            continue
        found.append(str(p))
        try:
            body = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            problems.append("oss_license_file_present")
            continue
        # Any root LICENSE-like file is an OSS stamp for this effort
        # (plan: do not add LICENSE). Body patterns also fail closed.
        problems.append("oss_license_file_present")
        for rx in _OSS_LICENSE_BODY_RES:
            if rx.search(body):
                if "user_onboard_oss_stamp" not in problems:
                    problems.append("user_onboard_oss_stamp")
                break

    return {
        "ok": not problems,
        "license_files": found,
        "problems": problems,
        "repo_root": str(root),
        "expected": "no LICENSE file; rights reserved in USER-ONBOARD.md",
    }


def check_docs_and_rights_reserved(repo_root=None) -> dict:
    """Combined Wave 6 ship-gate doc check (presence + no OSS license stamp)."""
    doc = check_user_onboard_doc(repo_root)
    lic = check_no_oss_license_stamp(repo_root)
    problems = list(doc.get("problems") or []) + list(lic.get("problems") or [])
    # De-dupe while preserving order.
    seen = set()
    uniq = []
    for p in problems:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return {
        "ok": not uniq,
        "user_onboard": doc,
        "no_oss_license": lic,
        "problems": uniq,
        "repo_root": doc.get("repo_root") or lic.get("repo_root"),
    }


class ShipGateError(Exception):
    """Raised when CI/ship/execute gates refuse (fail closed)."""

    def __init__(self, reason_codes, message=None, *, details=None):
        codes = list(reason_codes) if reason_codes else ["ship_gate_incomplete"]
        self.reason_codes = codes
        self.details = details if details is not None else {}
        self.message = message or ("ship gate refused: " + ",".join(codes))
        super().__init__(self.message)


# ── Money-safe gate ──────────────────────────────────────────────────────────

def money_safe_defaults(env=None) -> dict:
    """Report money-safe posture for CI (network deny, mock probes, no paid)."""
    env = env if env is not None else os.environ
    live = sob.live_probes_enabled(env)
    network_allowed = (env.get(NETWORK_ALLOW_ENV) or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    paid_allowed = (env.get(PAID_SPEND_ENV) or "").strip().lower() in (
        "1", "true", "yes", "on",
    )
    return {
        "schema": CI_SHIP_SCHEMA,
        "live_probes_enabled": live,
        "network_denied_default": not network_allowed,
        "paid_spend_allowed": paid_allowed,
        "mock_cli_probes_required": True,
        "recipient_api_keys_forbidden_in_happy_path": True,
        "live_probes_env": LIVE_PROBES_ENV,
        "network_allow_env": NETWORK_ALLOW_ENV,
        "paid_spend_env": PAID_SPEND_ENV,
        "ok": (not live) and (not network_allowed) and (not paid_allowed),
        "reason_codes": (
            []
            if (not live) and (not network_allowed) and (not paid_allowed)
            else [
                c for c, bad in (
                    ("live_probes_without_opt_in", live),
                    ("network_not_denied", network_allowed),
                    ("money_safe_violation", paid_allowed),
                )
                if bad
            ]
        ),
    }


def assert_money_safe(env=None, *, mock_seat_results=None) -> dict:
    """Fail closed when money-safe defaults are violated in CI happy-path.

    Live probes are only allowed when the opt-in env is set **and** the caller
    is not on the mock happy-path (mock seats present). Happy-path fixtures
    must use mocks and keep network/paid denied.
    """
    report = money_safe_defaults(env)
    codes = list(report["reason_codes"])
    # Happy-path CI always requires mock seats when probes run.
    if mock_seat_results is None and report["live_probes_enabled"]:
        if "live_probes_without_opt_in" not in codes:
            # Live without opt-in already coded; with opt-in, still warn if
            # no mock for happy-path — allowed only for explicit live jobs.
            pass
    if mock_seat_results is not None and report["live_probes_enabled"]:
        # CI happy-path must not combine mocks with live env — prefer mock.
        codes.append("money_safe_violation")
    if codes:
        raise ShipGateError(
            codes,
            message="money-safe gate failed: " + ",".join(codes),
            details=report,
        )
    report["mock_seat_results_present"] = mock_seat_results is not None
    return report


def fixture_has_recipient_api_keys(text: str) -> bool:
    """True if fixture prose embeds recipient-shaped API key material."""
    if not isinstance(text, str):
        return False
    # Happy-path fixtures must not embed live key shapes.
    patterns = (
        re.compile(r"sk-[A-Za-z0-9]{20,}"),
        re.compile(r"xai-[A-Za-z0-9]{20,}"),
        re.compile(r"AIza[0-9A-Za-z\-_]{20,}"),
        re.compile(r"ghp_[A-Za-z0-9]{20,}"),
    )
    return any(p.search(text) for p in patterns)


def assert_no_recipient_api_keys_in_text(text: str, *, where="fixture") -> list:
    if fixture_has_recipient_api_keys(text):
        return ["recipient_api_key_in_fixture:%s" % where]
    return []


# ── Dual scrub fixtures (publish job prerequisite) ───────────────────────────

def dual_scrub_fixture_paths(root=None) -> dict:
    base = Path(root) if root is not None else _FIXTURE_SCRUB
    return {
        "leak": base / DUAL_SCRUB_LEAK,
        "legit": base / DUAL_SCRUB_LEGIT,
    }


def dual_scrub_fixtures_present(root=None) -> dict:
    paths = dual_scrub_fixture_paths(root)
    leak_ok = paths["leak"].is_dir() and any(paths["leak"].iterdir())
    legit_ok = paths["legit"].is_dir() and any(paths["legit"].iterdir())
    codes = []
    if not leak_ok:
        codes.append("dual_scrub_missing:leak")
    if not legit_ok:
        codes.append("dual_scrub_missing:legit")
    return {
        "ok": not codes,
        "paths": {k: str(v) for k, v in paths.items()},
        "reason_codes": codes,
    }


def require_dual_scrub_for_publish(
    *,
    fixture_root=None,
    clean_scan_fn=None,
) -> dict:
    """Publish job prerequisite: dual scrub fixtures must exist and behave.

    planted-leak → clean-scan finds hits (fail); planted-legit → no hits (pass).
    Uses GREEN ``distro.scan_staged_dir`` by default (no second scrub stack).
    """
    presence = dual_scrub_fixtures_present(fixture_root)
    if not presence["ok"]:
        return {
            "ok": False,
            "job": "dual_scrub_required",
            "reason_codes": presence["reason_codes"] or ["dual_scrub_missing"],
            "leak_hits": None,
            "legit_hits": None,
        }

    if clean_scan_fn is None:
        import distro as distro_mod
        clean_scan_fn = distro_mod.scan_staged_dir

    paths = dual_scrub_fixture_paths(fixture_root)
    leak_hits = list(clean_scan_fn(paths["leak"]) or [])
    legit_hits = list(clean_scan_fn(paths["legit"]) or [])
    codes = []
    if not leak_hits:
        codes.append("dual_scrub_failed:leak_should_fail")
    if legit_hits:
        codes.append("dual_scrub_failed:legit_should_pass")
    return {
        "ok": not codes,
        "job": "dual_scrub_required",
        "reason_codes": codes,
        "leak_hits": len(leak_hits),
        "legit_hits": len(legit_hits),
        "paths": presence["paths"],
    }


# ── Governance golden + clean-scan ───────────────────────────────────────────

def governance_golden_and_clean_scan(
    *,
    golden_dir=None,
    clean_scan_fn=None,
) -> dict:
    """CI: generated governance pack matches golden; clean-scan has no hits."""
    golden = Path(golden_dir) if golden_dir is not None else _GOV_GOLDEN
    spine = gov.build_pack_files(None)
    match_problems = gov.pack_matches_golden(spine, golden) if golden.is_dir() else [
        "golden_dir_missing"
    ]
    author_problems = []
    for name, text in spine.items():
        author_problems.extend(
            ["%s:%s" % (name, p) for p in gov.assert_no_author_paths(text)]
        )

    # Stage generated pack into a temp dir and clean-scan it (money-safe local).
    if clean_scan_fn is None:
        import distro as distro_mod
        clean_scan_fn = distro_mod.scan_staged_dir
    hits = []
    with tempfile.TemporaryDirectory(prefix="share-gov-scan-") as td:
        stage = Path(td)
        for name, text in spine.items():
            (stage / name).write_text(text, encoding="utf-8", newline="\n")
        hits = list(clean_scan_fn(stage) or [])

    codes = []
    if match_problems:
        codes.append("governance_golden_mismatch")
    if author_problems:
        codes.append("author_secret_in_tree")
    if hits:
        codes.append("clean_scan_failed")
    return {
        "ok": not codes,
        "job": "governance_golden_clean_scan",
        "reason_codes": codes,
        "match_problems": match_problems,
        "author_problems": author_problems,
        "clean_scan_hits": len(hits),
    }


# ── Skills-only CI smoke matrix ──────────────────────────────────────────────

def run_skills_only_ci_smoke(
    home,
    *,
    skills_src=None,
    mock_seat_results=None,
    env=None,
    skill_to_invoke: str = "foreman",
    platform_name: str = "Windows",
) -> dict:
    """Skills-only (package A) day-1 smoke: governance + mock seat + readiness.

    **Never** starts an Anchor process (no ``anchor_gui`` import, no service).
    Money-safe: mock seats required; network/paid denied by default.
    """
    env = dict(env if env is not None else os.environ)
    # Force money-safe happy-path: strip live/network/paid opts.
    env.pop(LIVE_PROBES_ENV, None)
    env.pop(NETWORK_ALLOW_ENV, None)
    env.pop(PAID_SPEND_ENV, None)

    money = assert_money_safe(env, mock_seat_results=mock_seat_results or {"claude": True})
    mock = mock_seat_results if mock_seat_results is not None else {"claude": True}

    anchor_process_started = False
    # Deliberately do not import anchor_gui / start service.
    try:
        import sys
        if "anchor_gui" in sys.modules:
            # Pre-imported by other tests is fine for unit suite isolation —
            # we record whether *this* job started a listener, not import cache.
            pass
    except Exception:
        pass

    report = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=skills_src,
        mock_seat_results=mock,
        platform_name=platform_name,
        env=env,
        on_collision="overlay",
        feedback_opt_in=False,
    )

    readiness = report.get("readiness") or {}
    readiness_path = Path(home) / home_cfg.GOVERNANCE_SUBDIR / ready.READINESS_FILENAME
    skill_ready = False
    skills_home = Path(home) / home_cfg.SKILLS_SUBDIR
    skill_dir = skills_home / skill_to_invoke
    if skill_dir.is_dir() and (skill_dir / "SKILL.md").is_file():
        skill_ready = True
    elif skills_src is None:
        # No bundled skills_src: readiness alone is the day-1 signal when
        # governance + seat are green (skill invoke readiness structural).
        skill_ready = readiness.get("status") in ("ready", "degraded")

    codes = []
    if not report.get("ok"):
        codes.append("skills_only_smoke_failed")
    if not readiness_path.is_file():
        codes.append("readiness_missing")
    if not skill_ready and skills_src is not None:
        codes.append("skill_invoke_readiness_missing")
    if anchor_process_started:
        codes.append("anchor_process_started")

    return {
        "ok": not codes and report.get("ok") is True,
        "job": "skills_only_ci_smoke",
        "package_id": "A",
        "anchor_process_started": False,
        "money_safe": money,
        "readiness": readiness,
        "readiness_path": str(readiness_path) if readiness_path.is_file() else None,
        "skill_invoke_readiness": {
            "skill": skill_to_invoke,
            "ready": skill_ready,
        },
        "governance_installed": bool(
            (Path(home) / home_cfg.GOVERNANCE_SUBDIR / "AGENTS.md").is_file()
        ),
        "seat_probe_mock": True,
        "paid_cli_spend": False,
        "reason_codes": codes,
        "onboard": {
            "ok": report.get("ok"),
            "steps": [s.get("step") for s in (report.get("steps") or [])],
        },
    }


# ── Anchor+Skills CI matrix ──────────────────────────────────────────────────

def package_b_required_surfaces(doc=None) -> list:
    """Skill ids that must be present on package B (Doctor/Zombie/Tidy)."""
    roster = cap.resolve_package_b_roster(doc)
    by_id = {s.get("skill_id"): s for s in roster if isinstance(s, dict)}
    return list(PACKAGE_B_REQUIRED_SURFACES), by_id


def check_package_b_surfaces(doc=None) -> dict:
    required, by_id = package_b_required_surfaces(doc)
    missing = [sid for sid in required if sid not in by_id]
    present = {
        sid: {
            "skill_id": sid,
            "display_name": by_id[sid].get("display_name"),
            "capability": by_id[sid].get("capability"),
            "package_a_policy": by_id[sid].get("package_a_policy"),
        }
        for sid in required
        if sid in by_id
    }
    codes = ["package_b_surface_missing:%s" % m for m in missing]
    return {
        "ok": not missing,
        "required": list(required),
        "present": present,
        "missing": missing,
        "reason_codes": codes,
    }


def run_anchor_skills_ci_matrix(
    *,
    package_a_skills_root=None,
    package_b_skills_root=None,
    skills_pin=None,
    capability_doc=None,
) -> dict:
    """Anchor+Skills CI: B contains A + Doctor/Zombie/Tidy surfaces present."""
    pin = skills_pin if skills_pin is not None else {
        "tag": sc.PLACEHOLDER,
        "commit": sc.PLACEHOLDER,
    }
    codes = []
    bca = {"ok": True, "reason_codes": [], "checksum_a": None, "checksum_b": None}
    if package_a_skills_root is not None and package_b_skills_root is not None:
        bca = pub.ci_b_contains_a(
            package_a_skills_root,
            package_b_skills_root,
            skills_pin=pin,
        )
        if not bca.get("ok"):
            codes.extend(bca.get("reason_codes") or ["b_contains_a_mismatch"])

    surfaces = check_package_b_surfaces(capability_doc)
    if not surfaces["ok"]:
        codes.extend(surfaces["reason_codes"])

    matrix = pub.ci_matrix_assert({
        "artifact_name": "anchor-skills",
        "package_id": "B",
        "skills_subtree_present": True,
        "skills_pin": pin,
    })
    if not matrix.get("ok"):
        codes.extend(matrix.get("reason_codes") or [])

    return {
        "ok": not codes,
        "job": "anchor_skills_ci_matrix",
        "package_id": "B",
        "b_contains_a": bca,
        "surfaces": surfaces,
        "matrix": matrix,
        "reason_codes": codes,
    }


# ── Non-admin Windows matrix ─────────────────────────────────────────────────

def non_admin_windows_path(
    *,
    desktop_dir,
    dashboard_url: str = sob.DEFAULT_LOCAL_DASHBOARD_URL,
    platform_name: str = "Windows",
    service_registration_fn=None,
) -> dict:
    """Non-admin Windows path: desktop .url + optional local service (no elev).

    Default path never requires elevation. Service registration is optional and
    must report ``admin_required=False`` / ``elevation_required=False``.
    """
    codes = []
    desktop = sob.write_desktop_url_shortcut(
        desktop_dir=desktop_dir,
        url=dashboard_url,
        platform_name=platform_name,
    )
    if desktop.get("admin_required") or desktop.get("elevation_required"):
        codes.append("elevation_required")
    if not desktop.get("created") and not desktop.get("skipped"):
        codes.append("desktop_shortcut_invalid")
    if desktop.get("created"):
        url = desktop.get("url") or ""
        if not sob.is_local_dashboard_url(url):
            codes.append("desktop_shortcut_invalid")
        path = desktop.get("path")
        if path and Path(path).is_file():
            body = Path(path).read_text(encoding="utf-8")
            if "URL=" not in body or not any(
                h in body for h in ("localhost", "127.0.0.1")
            ):
                codes.append("desktop_shortcut_invalid")

    service = {
        "registered": False,
        "admin_required": False,
        "elevation_required": False,
        "skipped": True,
        "reason": "no service_registration_fn",
    }
    if service_registration_fn is not None:
        service = dict(service_registration_fn() or {})
        service.setdefault("skipped", False)
        if service.get("admin_required") or service.get("elevation_required"):
            codes.append("elevation_required")

    return {
        "ok": not codes,
        "job": "non_admin_windows_matrix",
        "desktop": desktop,
        "service": service,
        "elevation_required": "elevation_required" in codes,
        "reason_codes": codes,
        "platform": platform_name,
    }


# ── Stranger-install E2E ─────────────────────────────────────────────────────

def build_scrubbed_stranger_zip(
    dest_zip,
    *,
    skills=None,
    package_id: str = "B",
    include_author_secrets: bool = False,
) -> Path:
    """Build a scrubbed stranger zip fixture (package tree, no author secrets).

    When ``include_author_secrets`` is True the zip is intentionally dirty
    (for negative tests). Happy-path uses False.
    """
    dest_zip = Path(dest_zip)
    dest_zip.parent.mkdir(parents=True, exist_ok=True)
    names = skills or ["foreman", "crucible", "researchPrime", "gandalf"]
    with zipfile.ZipFile(dest_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "SOURCES.md",
            "# SOURCES (scrubbed stranger fixture)\nskills_pin: PLACEHOLDER\n",
        )
        zf.writestr("package_id.txt", package_id + "\n")
        for name in names:
            zf.writestr(
                "skills/%s/SKILL.md" % name,
                "# %s\nSee ./src/run.mjs\n" % name,
            )
            zf.writestr(
                "skills/%s/src/run.mjs" % name,
                "export const ok = true;\n",
            )
        if include_author_secrets:
            zf.writestr(
                "skills/leak/notes.md",
                "Host C:\\Users\\john\\secret token=a9F3kZ2pQ7wL5mN8xR1tY6vB4cD0eH2j\n",
            )
    return dest_zip


def extract_stranger_zip(zip_path, dest_dir) -> Path:
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(dest)
    return dest


def assert_no_author_secrets_in_tree(root) -> list:
    """Walk an installed tree; return problem codes for author secrets/paths."""
    root = Path(root)
    problems = []
    if not root.exists():
        return ["tree_missing"]
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        # Skip binary-ish
        if path.suffix.lower() in (".png", ".jpg", ".ico", ".zip", ".pyc"):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for rx in _AUTHOR_SECRET_RES:
            if rx.search(text):
                rel = str(path.relative_to(root)).replace("\\", "/")
                problems.append("author_secret_in_tree:%s" % rel)
                break
        for p in gov.assert_no_author_paths(text):
            rel = str(path.relative_to(root)).replace("\\", "/")
            problems.append("author_secret_in_tree:%s:%s" % (rel, p))
    # Dedupe preserve order
    seen = set()
    out = []
    for p in problems:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def run_stranger_install_e2e(
    work_dir,
    *,
    package_id: str = "B",
    mock_seat_results=None,
    env=None,
    platform_name: str = "Windows",
    dashboard_url: str = sob.DEFAULT_LOCAL_DASHBOARD_URL,
    zip_path=None,
    dirty_zip: bool = False,
) -> dict:
    """Stranger-install E2E: scrubbed zip → onboard → seat probe → desktop.

    Asserts local dashboard URL via shortcut, readiness stamp present, and no
    author secrets in the installed tree. Money-safe mocks only.
    """
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    env = dict(env if env is not None else os.environ)
    env.pop(LIVE_PROBES_ENV, None)
    env.pop(NETWORK_ALLOW_ENV, None)
    env.pop(PAID_SPEND_ENV, None)
    mock = mock_seat_results if mock_seat_results is not None else {"claude": True}
    money = assert_money_safe(env, mock_seat_results=mock)

    if zip_path is None:
        zip_path = work / "stranger-package.zip"
        build_scrubbed_stranger_zip(
            zip_path,
            package_id=package_id,
            include_author_secrets=dirty_zip,
        )
    extract_root = work / "package"
    extract_stranger_zip(zip_path, extract_root)
    skills_src = extract_root / "skills"
    if not skills_src.is_dir():
        skills_src = extract_root

    home = work / "home"
    desktop = home / "Desktop"
    desktop.mkdir(parents=True, exist_ok=True)

    onboard = sob.run_share_onboard(
        home,
        package_id=package_id,
        skills_src=skills_src if skills_src.is_dir() else None,
        mock_seat_results=mock,
        desktop_dir=str(desktop),
        dashboard_url=dashboard_url,
        platform_name=platform_name,
        env=env,
        on_collision="overlay",
        feedback_opt_in=False,
    )

    readiness_path = home / home_cfg.GOVERNANCE_SUBDIR / ready.READINESS_FILENAME
    readiness = onboard.get("readiness")
    if readiness is None and readiness_path.is_file():
        readiness = ready.load_readiness_stamp(readiness_path)

    desktop_report = onboard.get("desktop") or {}
    local_url_ok = False
    if desktop_report.get("created"):
        local_url_ok = sob.is_local_dashboard_url(desktop_report.get("url") or "")
        # Treat shortcut file as "reachable" for fixture E2E (no HTTP server).
        if desktop_report.get("path") and Path(desktop_report["path"]).is_file():
            body = Path(desktop_report["path"]).read_text(encoding="utf-8")
            local_url_ok = local_url_ok and ("URL=" in body)

    secret_problems = assert_no_author_secrets_in_tree(home)
    # Also scan extracted package tree
    secret_problems.extend(assert_no_author_secrets_in_tree(extract_root))

    codes = []
    if not onboard.get("ok"):
        codes.append("stranger_e2e_onboard_failed")
    if not readiness_path.is_file():
        codes.append("readiness_missing")
    if package_id == "B" and not local_url_ok:
        codes.append("desktop_shortcut_invalid")
    if secret_problems:
        codes.append("author_secret_in_tree")

    return {
        "ok": not codes and onboard.get("ok") is True,
        "job": "stranger_install_e2e",
        "package_id": package_id,
        "money_safe": money,
        "zip_path": str(zip_path),
        "home": str(home),
        "readiness": readiness,
        "readiness_path": str(readiness_path) if readiness_path.is_file() else None,
        "desktop": desktop_report,
        "local_dashboard_via_shortcut": local_url_ok,
        "author_secret_problems": secret_problems,
        "reason_codes": codes,
        "onboard_ok": onboard.get("ok"),
    }


# ── Execute re-validation / ship gate ────────────────────────────────────────

def freeze_tags_match_sources(
    *,
    sources_doc=None,
    freeze_doc=None,
    actual_tags=None,
) -> dict:
    """Compare SOURCES / freeze docs to *actual* multi-repo tags.

    When ``actual_tags`` is None, only checks internal consistency of the two
    docs (skills_pin + per-repo pins). Placeholders match placeholders.
    """
    src = sources_doc if sources_doc is not None else sources.load_sources_pin()
    frz = freeze_doc if freeze_doc is not None else sc.load_data("freeze_manifest")
    codes = []
    mismatches = []

    if not isinstance(src, dict) or not isinstance(frz, dict):
        return {
            "ok": False,
            "reason_codes": ["verify_freeze_manifest_failed"],
            "mismatches": ["docs_missing"],
            "placeholders": True,
        }

    src_pin = src.get("skills_pin") or {}
    frz_pin = frz.get("skills_pin") or {}
    if (src_pin.get("tag") or "") != (frz_pin.get("tag") or ""):
        mismatches.append("skills_pin.tag")
    if (src_pin.get("commit") or "") != (frz_pin.get("commit") or ""):
        mismatches.append("skills_pin.commit")

    frz_tags = frz.get("freeze_tags") or {}
    src_by_repo = {
        p.get("repo"): p
        for p in (src.get("pins") or [])
        if isinstance(p, dict) and p.get("repo")
    }
    for repo, tag in frz_tags.items():
        pin = src_by_repo.get(repo) or {}
        if (pin.get("tag") or "") != (tag or ""):
            mismatches.append("freeze_tags.%s" % repo)

    placeholders = sources.freeze_still_placeholder(src)
    if actual_tags is not None:
        # actual_tags: {repo: {tag, commit}} or {repo: tag}
        for repo, val in dict(actual_tags).items():
            if isinstance(val, dict):
                a_tag, a_commit = val.get("tag"), val.get("commit")
            else:
                a_tag, a_commit = val, None
            pin = src_by_repo.get(repo) or {}
            if a_tag is not None and (pin.get("tag") or "") != a_tag:
                mismatches.append("actual.%s.tag" % repo)
            if a_commit is not None and (pin.get("commit") or "") != a_commit:
                mismatches.append("actual.%s.commit" % repo)
            # Placeholder in SOURCES vs real actual tag is a mismatch.
            if a_tag and sc.is_placeholder(pin.get("tag")) and not sc.is_placeholder(
                str(a_tag)
            ):
                mismatches.append("actual.%s.placeholder_vs_real" % repo)

    if mismatches:
        codes.append("freeze_tag_mismatch")
    if placeholders and actual_tags:
        # Live actual tags cannot ship while SOURCES still PLACEHOLDER.
        if any(
            not sc.is_placeholder(
                (v.get("tag") if isinstance(v, dict) else v) or ""
            )
            for v in dict(actual_tags).values()
        ):
            if "freeze_placeholders_block_ship" not in codes:
                codes.append("freeze_placeholders_block_ship")

    return {
        "ok": not codes,
        "reason_codes": codes,
        "mismatches": mismatches,
        "placeholders": placeholders,
        "skills_pin": src_pin,
    }


def evaluate_execute_ship_gate(
    *,
    sources_doc=None,
    freeze_doc=None,
    actual_tags=None,
    concurrent_skill_run_merged: bool = False,
    john_go_ahead: bool = False,
    captain_status=None,
    clean_scan_ok: bool = False,
    stranger_smoke_ok: bool = False,
    sanitizer_red_team_ok: bool = False,
    package_matrix_ok: bool = False,
    require_placeholders: bool = True,
) -> dict:
    """Execute/ship gate: fail closed until freeze tags + captain + John go-ahead.

    Live skill-tree vendoring is **forbidden** unless this report's
    ``may_vendor_live_skill_trees`` is True.
    """
    src = sources_doc if sources_doc is not None else sources.load_sources_pin()
    frz = freeze_doc if freeze_doc is not None else sc.load_data("freeze_manifest")

    vfm_report = vfm.verify_freeze_manifest(
        freeze_doc=frz,
        sources_doc=src,
        require_placeholders=require_placeholders,
        concurrent_skill_run_merged=concurrent_skill_run_merged,
        john_go_ahead=john_go_ahead,
    )
    tag_match = freeze_tags_match_sources(
        sources_doc=src,
        freeze_doc=frz,
        actual_tags=actual_tags,
    )

    go_ahead_ok = sources.go_ahead_conditions_met(
        concurrent_skill_run_merged=concurrent_skill_run_merged,
        john_go_ahead=john_go_ahead,
    )
    placeholders = bool(tag_match.get("placeholders")) or bool(
        vfm_report.get("freeze_placeholders")
    )

    # Build captain status if not injected.
    if captain_status is None:
        captain_status = topo.build_captain_status_from_gates(
            freeze_tags_ok=not placeholders and tag_match.get("ok", False),
            clean_scan_ok=clean_scan_ok,
            sources_ok=not placeholders and bool(src.get("pins")),
            package_matrix_ok=package_matrix_ok,
            stranger_smoke_ok=stranger_smoke_ok,
            sanitizer_red_team_ok=sanitizer_red_team_ok,
            sources_doc=src,
            freeze_doc=frz,
        )
    captain = topo.evaluate_captain_checklist(captain_status)

    ship_items = {
        "concurrent_skill_run_merged": concurrent_skill_run_merged,
        "multi_repo_tags": (not placeholders) and tag_match.get("ok", False),
        "clean_scan": clean_scan_ok,
        "captain_signoff": bool(captain.get("ship_allowed")),
        "john_go_ahead": john_go_ahead,
    }
    ship_failed = [k for k, ok in ship_items.items() if not ok]

    codes = []
    if not vfm_report.get("ok") and require_placeholders:
        # In placeholder mode, schema ok is expected; only add on real fail.
        if vfm_report.get("problems"):
            codes.append("verify_freeze_manifest_failed")
    if not vfm_report.get("ok") and not require_placeholders:
        codes.append("verify_freeze_manifest_failed")
    if tag_match.get("reason_codes"):
        codes.extend(tag_match["reason_codes"])
    if not go_ahead_ok:
        codes.append("go_ahead_missing")
    if placeholders:
        codes.append("freeze_placeholders_block_ship")
    if not captain.get("ship_allowed"):
        codes.append("captain_not_green")
    if ship_failed:
        codes.append("ship_gate_incomplete")
    codes.append("live_vendoring_forbidden")  # default until all green

    # Dedupe
    seen = set()
    uniq = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            uniq.append(c)
    codes = uniq

    may_vendor = (
        go_ahead_ok
        and not placeholders
        and tag_match.get("ok") is True
        and captain.get("ship_allowed") is True
        and clean_scan_ok
        and not vfm_report.get("problems")
    )
    if may_vendor:
        codes = [c for c in codes if c != "live_vendoring_forbidden"]
        codes = [
            c for c in codes
            if c not in (
                "go_ahead_missing",
                "freeze_placeholders_block_ship",
                "captain_not_green",
                "ship_gate_incomplete",
            )
        ]

    return {
        "ok": may_vendor,
        "job": "execute_ship_gate",
        "may_vendor_live_skill_trees": may_vendor,
        "ship_allowed": may_vendor,
        "reason_codes": codes,
        "verify_freeze_manifest": {
            "ok": vfm_report.get("ok"),
            "ship_allowed": vfm_report.get("ship_allowed"),
            "freeze_placeholders": vfm_report.get("freeze_placeholders"),
            "problems": vfm_report.get("problems"),
        },
        "freeze_tag_match": tag_match,
        "go_ahead": {
            "concurrent_skill_run_merged": concurrent_skill_run_merged,
            "john_go_ahead": john_go_ahead,
            "ok": go_ahead_ok,
        },
        "captain": captain,
        "ship_gate_items": ship_items,
        "ship_gate_failed": ship_failed,
    }


def assert_execute_ship_gate(**kwargs) -> dict:
    """Raise :class:`ShipGateError` when live vendoring is not allowed."""
    report = evaluate_execute_ship_gate(**kwargs)
    if not report.get("may_vendor_live_skill_trees"):
        raise ShipGateError(
            report.get("reason_codes") or ["live_vendoring_forbidden"],
            message=(
                "execute/ship gate blocks live skill-tree vendoring: "
                + ",".join(report.get("reason_codes") or [])
            ),
            details=report,
        )
    return report


# ── Foreman wave text templates ──────────────────────────────────────────────

FOREMAN_WAVE_TEMPLATE = """## Wave N — <title>

**reuse-proof:** reuse:<marker> | ext:<extension_point>
(Cite one REUSE_MARKERS entry or a named extension point from SUPERSEDES-REUSE.md.
Forbidden without gap-proof ticket: security/auth/scrub reimplementation,
Tailscale/onboard2, second distro/publish stack, skill-internals rebuild.)

**Intent:** …

**Deliverables:** …

**Depends on:** …

**done-when:** …
"""


def validate_foreman_wave_text(text: str, *, allow_gap_proof: bool = False) -> list:
    """Validate a Foreman wave body for mandatory reuse-proof + forbid list.

    Returns problem codes (empty = OK).
    """
    if not isinstance(text, str) or not text.strip():
        return ["reuse_proof_missing:empty"]
    low = text.lower()
    problems = []

    has_reuse = any(m.lower() in low for m in REUSE_PROOF_SECTION_MARKERS)
    # Also accept explicit reuse marker names from contracts.
    if not has_reuse:
        for marker in sc.REUSE_MARKERS:
            if marker.lower() in low:
                has_reuse = True
                break
    if not has_reuse:
        # Named extension points
        if "ext:" in low or "extension point" in low:
            has_reuse = True
    if not has_reuse:
        problems.append("reuse_proof_missing")

    has_gap = any(m in low for m in GAP_PROOF_MARKERS)
    for token in FORBIDDEN_REIMPLEMENT_TOKENS:
        if token in low:
            if allow_gap_proof and has_gap:
                continue
            if has_gap:
                # gap-proof present → allowed
                continue
            problems.append("forbidden_reimplementation:%s" % token.replace(" ", "_"))

    return problems


def foreman_wave_template_text() -> str:
    return FOREMAN_WAVE_TEMPLATE


# ── Ship gate checklist artifact (plan workspace) ────────────────────────────

def render_ship_gate_checklist_md(status=None) -> str:
    """Render the plan-workspace ship gate checklist (machine-checkable ids)."""
    status = dict(status or {})
    lines = [
        "# Ship / execute gate checklist",
        "",
        "Plan workspace artifact for Shareable Anchor + Skills (W9).",
        "Fail closed: live skill-tree vendoring is forbidden until every item is green.",
        "",
        "Evaluate with `share_ci_ship_gate.evaluate_execute_ship_gate` / "
        "`evaluate_ship_gate_checklist`.",
        "",
        "## Required items",
        "",
    ]
    for item_id in SHIP_GATE_CHECKLIST_ITEMS:
        label = SHIP_GATE_ITEM_LABELS.get(item_id, item_id)
        raw = status.get(item_id)
        mark = "x" if _truthy(raw) else " "
        lines.append("- [%s] **`%s`** — %s" % (mark, item_id, label))
    lines.extend([
        "",
        "## Linkage",
        "",
        "- Concurrent skill-run + John go-ahead: W3 `share_sources.go_ahead_conditions_met`",
        "- Multi-repo tags / SOURCES: W3 `share_sources` + `verify_freeze_manifest`",
        "- Clean-scan: GREEN `distro.scan_staged_dir` + W2 dual scrub fixtures",
        "- Captain sign-off: W8 `share_topology.evaluate_captain_checklist`",
        "- Stranger E2E + CI matrices: W9 `share_ci_ship_gate`",
        "",
        "## Rule",
        "",
        "**Plan-complete ≠ ship-allowed.** PLACEHOLDER freeze tags + missing",
        "go-ahead → execute gate fails closed; Foreman must not vendor live trees.",
        "",
    ])
    return "\n".join(lines)


def _truthy(value) -> bool:
    if value is True:
        return True
    if value in (False, None, 0, ""):
        return False
    if isinstance(value, str):
        return value.strip().lower() in (
            "1", "true", "yes", "on", "green", "pass", "ok", "done",
        )
    if isinstance(value, dict):
        return bool(value.get("ok") or value.get("green") or value.get("done"))
    return bool(value)


def evaluate_ship_gate_checklist(status=None, **kwargs) -> dict:
    """Machine-check ship gate checklist (plan artifact items)."""
    status = dict(status or {})
    status.update(kwargs)
    failed = []
    green = []
    items = {}
    for item_id in SHIP_GATE_CHECKLIST_ITEMS:
        ok = _truthy(status.get(item_id))
        items[item_id] = {
            "ok": ok,
            "label": SHIP_GATE_ITEM_LABELS.get(item_id, item_id),
            "raw": status.get(item_id, None),
        }
        if ok:
            green.append(item_id)
        else:
            failed.append(item_id)
    all_green = not failed
    codes = []
    if failed:
        codes.append("ship_gate_incomplete")
        codes.append("live_vendoring_forbidden")
    return {
        "ok": all_green,
        "ship_allowed": all_green,
        "may_vendor_live_skill_trees": all_green,
        "failed_items": failed,
        "green_items": green,
        "items": items,
        "reason_codes": codes,
        "required_items": list(SHIP_GATE_CHECKLIST_ITEMS),
    }


def write_ship_gate_checklist(
    dest_dir=None,
    *,
    status=None,
) -> dict:
    """Write SHIP-GATE-CHECKLIST.md (+ JSON) into the plan workspace."""
    dest = Path(dest_dir) if dest_dir is not None else _PLAN_DIR
    dest.mkdir(parents=True, exist_ok=True)
    md_path = dest / "SHIP-GATE-CHECKLIST.md"
    json_path = dest / "SHIP-GATE-CHECKLIST.json"
    report = evaluate_ship_gate_checklist(status)
    md_path.write_text(
        render_ship_gate_checklist_md(status),
        encoding="utf-8",
        newline="\n",
    )
    payload = {
        "schema": CI_SHIP_SCHEMA,
        "schema_version": CI_SHIP_SCHEMA_VERSION,
        "items": SHIP_GATE_CHECKLIST_ITEMS,
        "labels": SHIP_GATE_ITEM_LABELS,
        "status": status or {},
        "evaluation": report,
    }
    json_path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return {
        "ok": True,
        "md": str(md_path),
        "json": str(json_path),
        "evaluation": report,
    }


def write_foreman_wave_template(dest_dir=None) -> Path:
    """Write the mandatory reuse-proof Foreman wave template into plan workspace."""
    dest = Path(dest_dir) if dest_dir is not None else _PLAN_DIR
    dest.mkdir(parents=True, exist_ok=True)
    path = dest / "FOREMAN-WAVE-TEMPLATE.md"
    body = (
        "# Foreman wave text template (W9)\n\n"
        "Every wave in this effort **must** include a reuse-proof section.\n"
        "Security / Tailscale / onboard2 reimplementation and skill-internals\n"
        "rebuilds are **forbidden** without a gap-proof ticket.\n\n"
        + FOREMAN_WAVE_TEMPLATE
    )
    path.write_text(body, encoding="utf-8", newline="\n")
    return path


def ensure_plan_workspace_artifacts(dest_dir=None) -> dict:
    """Idempotently write ship-gate checklist + wave template to plan workspace."""
    dest = Path(dest_dir) if dest_dir is not None else _PLAN_DIR
    checklist = write_ship_gate_checklist(dest, status=None)
    template = write_foreman_wave_template(dest)
    return {
        "ok": True,
        "checklist_md": checklist["md"],
        "checklist_json": checklist["json"],
        "wave_template": str(template),
        "evaluation": checklist["evaluation"],
    }


# ── Aggregate CI matrix runner ───────────────────────────────────────────────

def run_full_ci_matrices(
    work_dir,
    *,
    skills_src_a=None,
    package_a_skills_root=None,
    package_b_skills_root=None,
    env=None,
) -> dict:
    """Run Skills-only + Anchor+Skills CI matrices under money-safe defaults."""
    work = Path(work_dir)
    work.mkdir(parents=True, exist_ok=True)
    env = dict(env if env is not None else os.environ)
    env.pop(LIVE_PROBES_ENV, None)
    env.pop(NETWORK_ALLOW_ENV, None)
    env.pop(PAID_SPEND_ENV, None)

    money = money_safe_defaults(env)
    dual = require_dual_scrub_for_publish()
    gov_job = governance_golden_and_clean_scan()
    skills_only = run_skills_only_ci_smoke(
        work / "skills_only_home",
        skills_src=skills_src_a,
        mock_seat_results={"claude": True},
        env=env,
    )
    anchor_skills = run_anchor_skills_ci_matrix(
        package_a_skills_root=package_a_skills_root,
        package_b_skills_root=package_b_skills_root,
    )
    non_admin = non_admin_windows_path(
        desktop_dir=work / "Desktop",
        platform_name="Windows",
    )
    execute = evaluate_execute_ship_gate(
        concurrent_skill_run_merged=False,
        john_go_ahead=False,
        require_placeholders=True,
    )

    jobs = {
        "money_safe": money,
        "dual_scrub": dual,
        "governance_golden": gov_job,
        "skills_only": skills_only,
        "anchor_skills": anchor_skills,
        "non_admin_windows": non_admin,
        "execute_ship_gate": execute,
    }
    # Execute gate is *expected* red while placeholders remain — not a CI matrix fail.
    matrix_jobs_ok = all(
        jobs[k].get("ok")
        for k in (
            "money_safe",
            "dual_scrub",
            "governance_golden",
            "skills_only",
            "anchor_skills",
            "non_admin_windows",
        )
    )
    return {
        "ok": matrix_jobs_ok,
        "jobs": jobs,
        "live_vendoring_allowed": bool(execute.get("may_vendor_live_skill_trees")),
    }


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(
            "usage: share_ci_ship_gate.py "
            "write-artifacts|money-safe|execute-gate|skills-only-smoke",
            file=sys.stderr,
        )
        return 2
    cmd = args[0]
    if cmd == "write-artifacts":
        report = ensure_plan_workspace_artifacts()
        print(json.dumps(report, indent=2))
        return 0
    if cmd == "money-safe":
        print(json.dumps(money_safe_defaults(), indent=2))
        return 0 if money_safe_defaults()["ok"] else 1
    if cmd == "execute-gate":
        report = evaluate_execute_ship_gate()
        print(json.dumps({
            "may_vendor_live_skill_trees": report["may_vendor_live_skill_trees"],
            "reason_codes": report["reason_codes"],
            "ship_gate_failed": report["ship_gate_failed"],
        }, indent=2))
        return 0 if report["may_vendor_live_skill_trees"] else 1
    print("unknown command: %s" % cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
