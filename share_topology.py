"""Dual-audience git topology, CONTRIBUTING, and release captain gate (W8).

Extension point ``ext:topology`` — makes consumer vs collaborator vs
sanitized-feedback paths **git-honest** and enforceable with one-way mirrors
and a signed release-captain checklist (NS 2, 3, 9; R4/R12).

Hard rules (Master Plan P5 / Implementation Plan Wave 8):

* Private ``*-dev`` is the source of truth; public mirrors are **one-way**
  publish only (bot identity; human hand-edit forbidden where automatable)
* Collaborators: invite + branch protection (no force-push, no direct main),
  CODEOWNERS, PR-only integrate; uninvited PRs get misroute guidance
* Consumers: read/download release artifacts only; local edits stay local
* Sanitized feedback is a **separate** channel from product write access
  (links ``docs/share-feedback-intake.md``; never "push to main")
* Pin consumers to **release artifacts**, not floating ``main``
* Mirror lag: private tag without matching public publish → alert / fail item
* Release captain checklist is **machine-checkable** and **fail-closed**:
  any red of freeze tags / clean-scan / SOURCES / package matrix /
  stranger smoke / sanitizer red-team → not ship-allowed

Stdlib only. Does not invent a second distro/publish stack — reuses W3
``share_publish`` / W1 matrices as inputs when evaluating captain status.
"""

from __future__ import annotations

from pathlib import Path

# Optional light imports of frozen contracts (no cycles with onboard).
from share_contracts import PACKAGE_IDS, is_placeholder

_MODULE_DIR = Path(__file__).resolve().parent
_PACK_DIR = _MODULE_DIR / "share_topology_pack"
_DOCS_DIR = _MODULE_DIR / "docs"

# ── Identity / topology constants ────────────────────────────────────────────

TOPOLOGY_SCHEMA = "share-topology/v1"
TOPOLOGY_SCHEMA_VERSION = 1

# Private source of truth naming convention (NS D11 / Master Plan P5).
PRIVATE_SOT_PATTERN = "*-dev"
PUBLIC_MIRROR_ROLE = "one-way-release-mirror"
BOT_WRITE_IDENTITIES = frozenset({
    "release-bot",
    "mirror-bot",
    "github-actions[bot]",
    "share-publish-bot",
})
HUMAN_PUBLIC_WRITE_FORBIDDEN = True

# Branch protection policy (docs-as-code; CI/process checks).
BRANCH_PROTECTION_POLICY = {
    "protected_branches": ("main", "master", "release"),
    "allow_force_push": False,
    "allow_direct_push_to_main": False,
    "require_pull_request": True,
    "require_codeowners_review": True,
}

# Honest backlog SLA (no false "we review every PR in 24h" claim).
BACKLOG_SLA = (
    "Invited collaborator PRs are reviewed when the maintainer is free — "
    "there is no guaranteed turnaround SLA. Uninvited public PRs into "
    "private upstream are not accepted."
)

# Three-path diagram labels (use / sanitized-feedback / collaborate).
THREE_PATH_DIAGRAM = {
    "use": (
        "Download & use — pin to release artifacts (not floating main); "
        "local edits stay local; no write access to upstream."
    ),
    "sanitized_feedback": (
        "Optional sanitized friction feedback — opt-in only; separate "
        "John-controlled intake channel; NOT a code push to main or a PR "
        "into product sources. See docs/share-feedback-intake.md."
    ),
    "collaborate": (
        "Invited collaborate — private *-dev invite, feature branches + PR "
        "only; no force-push; no direct push to main; CODEOWNERS review."
    ),
}

# Required section markers for CONTRIBUTING / package README tests (GWT #2).
REQUIRED_CONTRIBUTING_MARKERS = (
    "Download & use",
    "sanitized",
    "collaborat",  # collaborate / collaborator
    "not",  # feedback is NOT code push
    "code push",
    "branch",
    "pull request",
    "main",
    "release artifact",
    "backlog",
    "feedback intake",
)

REQUIRED_README_MARKERS = (
    "Download & use",
    "Invited to collaborate",
    "friction",
    "CONTRIBUTING",
    "release artifact",
    "not floating main",
    "sanitized",
    "privacy",
)

# Captain checklist item ids (machine-checkable; GWT #3).
CAPTAIN_CHECKLIST_ITEMS = (
    "freeze_tags",
    "clean_scan_green",
    "sources_complete",
    "package_matrix_green",
    "stranger_install_smoke",
    "sanitizer_red_team_green",
)

CAPTAIN_ITEM_LABELS = {
    "freeze_tags": "Freeze tags present (no PLACEHOLDER remaining)",
    "clean_scan_green": "Clean-scan green (no-leak)",
    "sources_complete": "SOURCES.md / multi-repo pin complete",
    "package_matrix_green": "Package matrix green (A|B only; B contains A)",
    "stranger_install_smoke": "Stranger install smoke green",
    "sanitizer_red_team_green": "Feedback sanitizer red-team green",
}

# Mirror lag / cadence reason codes.
MIRROR_REASON_CODES = (
    "private_tag_missing_public_publish",
    "consumers_pinned_to_last_public",
    "human_public_write_forbidden",
    "unknown_public_writer",
    "captain_item_red",
    "captain_incomplete",
    "ship_not_allowed",
)


class TopologyError(Exception):
    """Raised when topology / captain checks refuse (fail closed)."""

    def __init__(self, reason, message=None, *, details=None):
        self.reason = reason
        self.details = details if details is not None else {}
        self.message = message or ("topology refused: %s" % reason)
        super().__init__(self.message)


# ── Topology policy ──────────────────────────────────────────────────────────

def topology_policy() -> dict:
    """Machine-readable dual-audience topology policy."""
    return {
        "schema": TOPOLOGY_SCHEMA,
        "schema_version": TOPOLOGY_SCHEMA_VERSION,
        "private_source_of_truth": PRIVATE_SOT_PATTERN,
        "public_mirror": {
            "role": PUBLIC_MIRROR_ROLE,
            "direction": "private-to-public-one-way",
            "bot_only_write": True,
            "human_hand_edit_forbidden": HUMAN_PUBLIC_WRITE_FORBIDDEN,
            "allowed_writer_identities": sorted(BOT_WRITE_IDENTITIES),
        },
        "consumers": {
            "write_access": False,
            "pin_to": "release_artifacts",
            "not_pin_to": "floating_main",
        },
        "collaborators": {
            "invite_required": True,
            "branch_protection": dict(BRANCH_PROTECTION_POLICY),
            "pr_only": True,
        },
        "feedback": {
            "channel": "separate_intake",
            "docs": "docs/share-feedback-intake.md",
            "is_code_contribution": False,
            "is_product_main_write": False,
        },
        "backlog_sla": BACKLOG_SLA,
        "three_path": dict(THREE_PATH_DIAGRAM),
    }


def is_private_sot_name(repo_name: str) -> bool:
    """True when *repo_name* matches the private ``*-dev`` SoT convention."""
    name = (repo_name or "").strip().lower()
    return name.endswith("-dev") or name.endswith("_dev")


def check_public_write_identity(identity: str) -> list:
    """Return reason codes if *identity* must not write the public mirror.

    Bot identities in :data:`BOT_WRITE_IDENTITIES` are allowed; empty/unknown
    humans fail closed (human hand-edit forbidden).
    """
    ident = (identity or "").strip().lower()
    if not ident:
        return ["unknown_public_writer"]
    # Normalize common bot suffix forms.
    if ident in {b.lower() for b in BOT_WRITE_IDENTITIES}:
        return []
    if ident.endswith("[bot]") or ident.endswith("-bot") or ident.endswith("_bot"):
        # Still require membership in the allowlist for automatable check.
        if ident in {b.lower() for b in BOT_WRITE_IDENTITIES}:
            return []
        return ["unknown_public_writer"]
    if HUMAN_PUBLIC_WRITE_FORBIDDEN:
        return ["human_public_write_forbidden"]
    return ["unknown_public_writer"]


def assert_public_write_allowed(identity: str) -> None:
    """Raise :class:`TopologyError` when a human/unknown would edit public."""
    codes = check_public_write_identity(identity)
    if codes:
        raise TopologyError(
            codes[0],
            "public mirror write refused for identity %r: %s"
            % (identity, ",".join(codes)),
            details={"identity": identity, "reason_codes": codes},
        )


# ── Mirror lag / release cadence ─────────────────────────────────────────────

def last_public_release(public_publishes) -> str | None:
    """Return the latest public tag/artifact id, or None if none published."""
    tags = _normalize_tag_list(public_publishes)
    return tags[-1] if tags else None


def _normalize_tag_list(tags) -> list:
    if tags is None:
        return []
    out = []
    for t in tags:
        if t is None:
            continue
        s = str(t).strip()
        if s:
            out.append(s)
    return out


def check_mirror_lag(
    private_tags=None,
    public_publishes=None,
    *,
    private_release_tags=None,
    public_release_tags=None,
) -> dict:
    """Compare private release tags to public publishes.

    **GWT #1:** a private release tag without a matching public publish raises
    an alert / failed checklist item; consumers remain pinned to the last
    public release artifact (not floating main).

    Accepts either ``private_tags``/``public_publishes`` or the longer
    ``private_release_tags``/``public_release_tags`` aliases.
    """
    private = _normalize_tag_list(
        private_tags if private_tags is not None else private_release_tags
    )
    public = _normalize_tag_list(
        public_publishes if public_publishes is not None else public_release_tags
    )
    public_set = set(public)
    missing = [t for t in private if t not in public_set]
    last_pub = last_public_release(public)
    alert = bool(missing)
    return {
        "ok": not alert,
        "alert": alert,
        "missing_public": missing,
        "reason_codes": (
            ["private_tag_missing_public_publish"] if missing else []
        ),
        "last_public_release": last_pub,
        "consumers_pin_to": (
            last_pub if last_pub is not None else "none-yet-do-not-use-floating-main"
        ),
        "consumers_must_not_pin_to": "floating_main",
        "failed_checklist_item": (
            "mirror_lag:private_tag_missing_public_publish" if missing else None
        ),
    }


def mirror_lag_badge(lag_report: dict) -> str:
    """Short badge string for public README (lag vs in-sync)."""
    if not isinstance(lag_report, dict):
        return "mirror: unknown"
    if lag_report.get("ok"):
        last = lag_report.get("last_public_release") or "none"
        return "mirror: in-sync · pin consumers to `%s`" % last
    missing = lag_report.get("missing_public") or []
    last = lag_report.get("last_public_release") or "none"
    return (
        "mirror: LAG — private tags without public publish: %s · "
        "consumers stay on last public `%s` (not floating main)"
        % (", ".join(missing) if missing else "?", last)
    )


def release_cadence_checklist() -> list:
    """Ordered release-cadence checklist rows (docs + automation)."""
    return [
        {
            "id": "freeze_then_tag",
            "label": "Freeze skill sources at agreed tags before public publish",
            "required": True,
        },
        {
            "id": "captain_signoff",
            "label": "Release captain checklist green (see CAPTAIN_CHECKLIST_ITEMS)",
            "required": True,
        },
        {
            "id": "one_way_mirror",
            "label": "Publish private → public via bot only (no human public hand-edit)",
            "required": True,
        },
        {
            "id": "mirror_lag_check",
            "label": "Run check_mirror_lag; alert if private tag lacks public publish",
            "required": True,
        },
        {
            "id": "pin_release_artifacts",
            "label": "Document consumer pin to release artifacts, not floating main",
            "required": True,
        },
        {
            "id": "sources_stamp",
            "label": "SOURCES.md / skills_pin stamp matches published artifacts",
            "required": True,
        },
    ]


# ── Collaborator invite (docs-as-code) ───────────────────────────────────────

def collaborator_invite_checklist() -> list:
    """Invite checklist: protection, CODEOWNERS, PR-only, misroute guidance."""
    return [
        {
            "id": "private_invite",
            "label": "Invite collaborator to private *-dev source of truth only",
            "required": True,
        },
        {
            "id": "branch_protection_no_force_push",
            "label": "Branch protection: force-push disabled on main/release",
            "required": True,
            "policy": {"allow_force_push": False},
        },
        {
            "id": "branch_protection_no_direct_main",
            "label": "Branch protection: no direct push to main (PR-only integrate)",
            "required": True,
            "policy": {"allow_direct_push_to_main": False, "require_pull_request": True},
        },
        {
            "id": "codeowners",
            "label": "CODEOWNERS present and required for review on protected paths",
            "required": True,
        },
        {
            "id": "pr_only",
            "label": "PR-only integrate into main; no bypass for collaborators",
            "required": True,
        },
        {
            "id": "uninvited_pr_misroute",
            "label": "Uninvited PR misroute guidance published (public consumers)",
            "required": True,
        },
    ]


def uninvited_pr_misroute_guidance() -> str:
    """Guidance shown when an uninvited public PR targets private upstream."""
    return (
        "This repository's private *-dev source of truth does not accept "
        "unsolicited pull requests from the public. Public consumers may "
        "(1) download & use release artifacts, (2) file issues, or "
        "(3) optionally opt into sanitized friction feedback — which is "
        "NOT a code contribution and is not a PR into product main. "
        "To contribute code, request a collaborator invite first; then "
        "push only feature branches and open a PR for review."
    )


def default_codeowners_body(owners=None) -> str:
    """CODEOWNERS file body (docs-as-code asset)."""
    owners = list(owners) if owners else ["@maintainer"]
    owner_line = " ".join(owners)
    return "\n".join([
        "# Shareable Anchor + Skills — CODEOWNERS (W8)",
        "# Required on protected paths; PR-only integrate into main.",
        "",
        "* %s" % owner_line,
        "/share_*.py %s" % owner_line,
        "/docs/ %s" % owner_line,
        "/share_topology_pack/ %s" % owner_line,
        "",
    ])


def validate_branch_protection(config: dict) -> list:
    """Return problem codes when *config* weakens required protection."""
    problems = []
    if not isinstance(config, dict):
        return ["branch_protection_missing"]
    if config.get("allow_force_push") is True:
        problems.append("force_push_allowed")
    if config.get("allow_direct_push_to_main") is True:
        problems.append("direct_main_push_allowed")
    if config.get("require_pull_request") is False:
        problems.append("pr_not_required")
    return problems


# ── CONTRIBUTING + package README generation ─────────────────────────────────

def _three_path_markdown() -> str:
    return "\n".join([
        "## Three paths (use / sanitized-feedback / collaborate)",
        "",
        "```",
        "  [use]  Download & use ──► local install; edits stay local",
        "  [sanitized-feedback] ──► opt-in friction intake (NOT code push to main)",
        "  [collaborate] ──► invited branch/PR on private *-dev only",
        "```",
        "",
        "1. **Download & use** — %s" % THREE_PATH_DIAGRAM["use"],
        "2. **Sanitized feedback** — %s" % THREE_PATH_DIAGRAM["sanitized_feedback"],
        "3. **Collaborate** — %s" % THREE_PATH_DIAGRAM["collaborate"],
        "",
    ])


def render_contributing() -> str:
    """Public CONTRIBUTING with three-path write policy (GWT #2)."""
    lines = [
        "# Contributing — Shareable Anchor + Skills",
        "",
        "This project is **dual-audience**: public consumers download and use; "
        "invited collaborators work on private `*-dev` via branch/PR. "
        "Sanitized friction feedback is a **separate** channel — it is "
        "**not** a code push to main.",
        "",
        _three_path_markdown().rstrip(),
        "",
        "## Public consumers (read-only)",
        "",
        "- Pin to **release artifacts**, not floating `main`.",
        "- Local edits stay local; they do not flow back to upstream.",
        "- You may open issues. You may **not** open unsolicited PRs into "
        "private upstream without an invitation.",
        "",
        "## Sanitized feedback (optional, not code contribution)",
        "",
        "- Opt-in only (default off). Fail-closed sanitizer.",
        "- Lands in a John-controlled **feedback intake** for pull/review only.",
        "- **Not** a code push to main; **not** a product write path.",
        "- Ops detail: [`docs/share-feedback-intake.md`](docs/share-feedback-intake.md).",
        "",
        "## Invited collaborators",
        "",
        "- Invite is required to the private `*-dev` source of truth.",
        "- Push **feature branches** only; open a **pull request** for review.",
        "- **No force-push** and **no direct push to main** (branch protection).",
        "- CODEOWNERS review is required on protected paths.",
        "",
        "## Uninvited pull requests",
        "",
        uninvited_pr_misroute_guidance(),
        "",
        "## Backlog SLA (honest)",
        "",
        BACKLOG_SLA,
        "",
        "## Release topology",
        "",
        "- Private `*-dev` is the source of truth.",
        "- Public mirrors are **one-way** publish from private (bot-only write; "
        "human hand-edit of public mirrors is forbidden).",
        "- Mirror lag is checked: a private release tag without a matching "
        "public publish raises an alert; consumers stay on the last public "
        "release artifact.",
        "",
        "## Privacy / friction",
        "",
        "See package README privacy section and "
        "[`docs/share-feedback-intake.md`](docs/share-feedback-intake.md).",
        "",
    ]
    return "\n".join(lines)


def render_package_readme(package_id: str = "A") -> str:
    """Package-level README dual-audience lead (A or B)."""
    pid = (package_id or "A").strip().upper()
    if pid not in PACKAGE_IDS:
        pid = "A"
    title = (
        "Skills-only (Package A)"
        if pid == "A"
        else "Anchor + Skills (Package B)"
    )
    lines = [
        "# %s — Shareable release" % title,
        "",
        "> **Dual audience.** Download & use · Invited to collaborate · "
        "Optional sanitized friction sharing. See [CONTRIBUTING.md](CONTRIBUTING.md).",
        "",
        "## Which path are you on?",
        "",
        "| Path | Who | What you do |",
        "|------|-----|-------------|",
        "| **Download & use** | Public consumer | Install release artifacts; "
        "local edits stay local |",
        "| **Invited to collaborate** | Collaborator | Branch + PR on private "
        "`*-dev` only |",
        "| **Optional friction sharing** | Opt-in user | Sanitized feedback "
        "intake — **not** code push to main |",
        "",
        _three_path_markdown().rstrip(),
        "",
        "## Pin to release artifacts (not floating main)",
        "",
        "Consumers must pin to **published release artifacts** (tagged, "
        "scrubbed packages). Do **not** track floating `main` as your install "
        "source — private development history is not the consumer product.",
        "",
        "## Privacy / friction",
        "",
        "- Feedback is **opt-in**, fail-closed, and de-identified.",
        "- Full local journals never leave your machine via this channel.",
        "- Details: [`docs/share-feedback-intake.md`](docs/share-feedback-intake.md) "
        "and [CONTRIBUTING.md](CONTRIBUTING.md).",
        "",
        "## Package identity",
        "",
        "- **Package id:** `%s`" % pid,
        "- **Never ships:** Anchor-only (hard-blocked by package matrix).",
        "",
        "## Mirror lag badge",
        "",
        "Public README may embed the output of `mirror_lag_badge(...)` so "
        "consumers know when private tags have not yet been published.",
        "",
        "## Links",
        "",
        "- [CONTRIBUTING.md](CONTRIBUTING.md) — write policy + three paths",
        "- [`docs/share-feedback-intake.md`](docs/share-feedback-intake.md) — "
        "feedback intake (not product write access)",
        "- [`docs/share-topology.md`](docs/share-topology.md) — topology ops",
        "- [`docs/share-release-captain-checklist.md`]"
        "(docs/share-release-captain-checklist.md) — captain gate",
        "",
    ]
    return "\n".join(lines)


def required_section_problems(text: str, markers) -> list:
    """Return missing required-section markers (case-insensitive)."""
    if not isinstance(text, str) or not text.strip():
        return ["document_empty"]
    low = text.lower()
    missing = []
    for m in markers:
        if m.lower() not in low:
            missing.append("missing_section:%s" % m)
    # Extra hard rule: feedback must NOT be described as code push to main.
    if "code push" in low or "push to main" in low:
        # Require a negation near the feedback story.
        if "not" not in low and "never" not in low:
            missing.append("feedback_not_negated_as_code_push")
    return missing


def validate_contributing_text(text: str) -> list:
    """Problems for CONTRIBUTING required sections (GWT #2)."""
    problems = required_section_problems(text, REQUIRED_CONTRIBUTING_MARKERS)
    low = (text or "").lower()
    # Feedback must not be described as the code-push path.
    if "feedback" in low and "code push" in low:
        # OK when "not" appears (our template does).
        if "not" not in low and "never" not in low:
            problems.append("feedback_described_as_code_push")
    if "pull request" not in low and "pull requests" not in low and " pr " not in low:
        if "missing_section:pull request" not in problems:
            # already covered by markers; keep explicit
            pass
    return problems


def validate_readme_text(text: str) -> list:
    """Problems for package README required sections (GWT #2)."""
    return required_section_problems(text, REQUIRED_README_MARKERS)


def write_topology_docs(dest_root=None) -> dict:
    """Write CONTRIBUTING, package READMEs, CODEOWNERS, and docs under *dest*.

    Defaults to the repo root (module parent). Returns written relative paths.
    """
    root = Path(dest_root) if dest_root is not None else _MODULE_DIR
    written = []

    contrib = root / "CONTRIBUTING.md"
    contrib.write_text(render_contributing(), encoding="utf-8")
    written.append("CONTRIBUTING.md")

    pack = root / "share_topology_pack"
    pack.mkdir(parents=True, exist_ok=True)
    for pid in PACKAGE_IDS:
        name = "README-package-%s.md" % pid
        (pack / name).write_text(render_package_readme(pid), encoding="utf-8")
        written.append("share_topology_pack/%s" % name)

    (pack / "CONTRIBUTING.md").write_text(render_contributing(), encoding="utf-8")
    written.append("share_topology_pack/CONTRIBUTING.md")

    (pack / "CODEOWNERS").write_text(default_codeowners_body(), encoding="utf-8")
    written.append("share_topology_pack/CODEOWNERS")

    (pack / "collaborator-invite-checklist.md").write_text(
        render_collaborator_invite_doc(), encoding="utf-8"
    )
    written.append("share_topology_pack/collaborator-invite-checklist.md")

    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "share-topology.md").write_text(render_topology_ops_doc(), encoding="utf-8")
    written.append("docs/share-topology.md")
    (docs / "share-release-captain-checklist.md").write_text(
        render_captain_checklist_doc(), encoding="utf-8"
    )
    written.append("docs/share-release-captain-checklist.md")

    return {"ok": True, "written": written, "root": str(root)}


def render_collaborator_invite_doc() -> str:
    rows = collaborator_invite_checklist()
    lines = [
        "# Collaborator invite checklist",
        "",
        "Docs-as-code checklist for inviting a collaborator to private `*-dev`.",
        "",
    ]
    for row in rows:
        lines.append("- [ ] **%s** — %s" % (row["id"], row["label"]))
    lines.extend([
        "",
        "## Misroute guidance (uninvited PR)",
        "",
        uninvited_pr_misroute_guidance(),
        "",
        "## Branch protection policy",
        "",
        "```",
        str(BRANCH_PROTECTION_POLICY),
        "```",
        "",
    ])
    return "\n".join(lines)


def render_topology_ops_doc() -> str:
    policy = topology_policy()
    lines = [
        "# Dual-audience topology ops",
        "",
        "Machine + human ops note for Shareable Anchor + Skills (W8).",
        "",
        "## Source of truth",
        "",
        "- Private pattern: `%s`" % PRIVATE_SOT_PATTERN,
        "- Public role: **%s** (one-way private → public)." % PUBLIC_MIRROR_ROLE,
        "- Public write: **bot-only**; human hand-edit forbidden.",
        "- Allowed bot identities: %s"
        % ", ".join(sorted(BOT_WRITE_IDENTITIES)),
        "",
        "## Feedback intake is separate from product write access",
        "",
        "See [`share-feedback-intake.md`](share-feedback-intake.md). "
        "Sanitized friction is **not** a code contribution and never uses "
        "product-main write credentials.",
        "",
        "## Mirror lag",
        "",
        "Run `share_topology.check_mirror_lag(private_tags, public_publishes)`. "
        "Any private release tag without a matching public publish raises an "
        "alert; consumers remain pinned to the last public release artifact "
        "(never floating main).",
        "",
        "## Policy snapshot",
        "",
        "```",
        "private_sot=%s" % policy["private_source_of_truth"],
        "public_direction=%s" % policy["public_mirror"]["direction"],
        "bot_only_write=%s" % policy["public_mirror"]["bot_only_write"],
        "consumer_pin=%s" % policy["consumers"]["pin_to"],
        "feedback_is_code=%s" % policy["feedback"]["is_code_contribution"],
        "```",
        "",
        "## Cadence checklist",
        "",
    ]
    for row in release_cadence_checklist():
        lines.append("- [ ] %s" % row["label"])
    lines.append("")
    return "\n".join(lines)


def render_captain_checklist_doc() -> str:
    lines = [
        "# Release captain checklist",
        "",
        "John (or the release captain) signs this gate before a public release. "
        "Items are **machine-checkable** via "
        "`share_topology.evaluate_captain_checklist`. **Fail closed:** any red "
        "item means the release is **not** ship-allowed.",
        "",
        "## Required items",
        "",
    ]
    for item_id in CAPTAIN_CHECKLIST_ITEMS:
        lines.append(
            "- [ ] **`%s`** — %s"
            % (item_id, CAPTAIN_ITEM_LABELS.get(item_id, item_id))
        )
    lines.extend([
        "",
        "## Evaluation",
        "",
        "```python",
        "from share_topology import evaluate_captain_checklist",
        "report = evaluate_captain_checklist({",
        "    'freeze_tags': True,",
        "    'clean_scan_green': True,",
        "    'sources_complete': True,",
        "    'package_matrix_green': True,",
        "    'stranger_install_smoke': True,",
        "    'sanitizer_red_team_green': True,",
        "})",
        "# report['ship_allowed'] is True only when every item is green",
        "```",
        "",
        "## Linkage",
        "",
        "- Freeze / SOURCES: W3 `share_sources` + `verify_freeze_manifest`",
        "- Clean-scan / matrix: W3 `share_publish` + W1 package matrix",
        "- Sanitizer red-team: W6 `share_feedback` unit/red-team suite",
        "- Stranger smoke: W9 E2E harness (status may be injected here)",
        "",
    ])
    return "\n".join(lines)


# ── Release captain checklist (fail-closed) ──────────────────────────────────

def _coerce_item_ok(value) -> bool:
    """Interpret checklist item values: True/'green'/'pass'/'ok' → green."""
    if value is True:
        return True
    if value is False or value is None:
        return False
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        s = value.strip().lower()
        return s in ("green", "pass", "passed", "ok", "true", "yes", "1")
    if isinstance(value, dict):
        if "ok" in value:
            return bool(value.get("ok"))
        if "green" in value:
            return bool(value.get("green"))
        if "status" in value:
            return _coerce_item_ok(value.get("status"))
    return False


def evaluate_captain_checklist(status=None, **kwargs) -> dict:
    """Evaluate release captain checklist; fail closed (GWT #3).

    *status* is a mapping of checklist item id → green/red indicator.
    Missing items are treated as **red**. Returns::

        {
          ok, ship_allowed, failed_items, green_items, items, reason_codes
        }

    ``ship_allowed`` is True **only** when every required item is green.
    """
    status = dict(status or {})
    status.update(kwargs)
    failed = []
    green = []
    items = {}
    for item_id in CAPTAIN_CHECKLIST_ITEMS:
        ok = _coerce_item_ok(status.get(item_id))
        items[item_id] = {
            "ok": ok,
            "label": CAPTAIN_ITEM_LABELS.get(item_id, item_id),
            "raw": status.get(item_id, None),
        }
        if ok:
            green.append(item_id)
        else:
            failed.append(item_id)

    all_green = len(failed) == 0
    reason_codes = []
    if failed:
        reason_codes.append("captain_item_red")
        if any(status.get(i) is None for i in failed):
            reason_codes.append("captain_incomplete")
        reason_codes.append("ship_not_allowed")

    return {
        "ok": all_green,
        "ship_allowed": all_green,
        "failed_items": failed,
        "green_items": green,
        "items": items,
        "reason_codes": reason_codes,
        "required_items": list(CAPTAIN_CHECKLIST_ITEMS),
    }


def captain_checklist_item_ids() -> tuple:
    """Stable ordered tuple of captain checklist ids (for presence tests)."""
    return tuple(CAPTAIN_CHECKLIST_ITEMS)


def build_captain_status_from_gates(
    *,
    freeze_tags_ok: bool = False,
    clean_scan_ok: bool = False,
    sources_ok: bool = False,
    package_matrix_ok: bool = False,
    stranger_smoke_ok: bool = False,
    sanitizer_red_team_ok: bool = False,
    sources_doc=None,
    freeze_doc=None,
    matrix_doc=None,
) -> dict:
    """Helper: assemble a captain status map from booleans / optional docs.

    When docs are supplied, freeze/sources/matrix greens can be derived:
    placeholders → freeze_tags red; ship_allowed false does not alone
    decide captain (captain is the pre-ship gate).
    """
    freeze_ok = freeze_tags_ok
    sources_complete = sources_ok
    matrix_ok = package_matrix_ok

    if sources_doc is not None and isinstance(sources_doc, dict):
        # Placeholders mean freeze tags are not present yet.
        sp = sources_doc.get("skills_pin") or {}
        pins = sources_doc.get("pins") or []
        still_ph = is_placeholder(sp.get("tag")) or is_placeholder(sp.get("commit"))
        for pin in pins:
            if isinstance(pin, dict) and (
                is_placeholder(pin.get("tag")) or is_placeholder(pin.get("commit"))
            ):
                still_ph = True
                break
        freeze_ok = freeze_ok or (not still_ph)
        # SOURCES complete when structure has pins + skills_pin keys.
        sources_complete = sources_complete or (
            bool(pins) and isinstance(sp, dict) and "tag" in sp and "commit" in sp
            and not still_ph
        )

    if freeze_doc is not None and isinstance(freeze_doc, dict):
        fsp = freeze_doc.get("skills_pin") or {}
        if not (
            is_placeholder(fsp.get("tag")) or is_placeholder(fsp.get("commit"))
        ):
            freeze_ok = True

    if matrix_doc is not None and isinstance(matrix_doc, dict):
        try:
            import share_package_matrix as pm
            matrix_ok = matrix_ok or (pm.matrix_problems(matrix_doc) == [])
        except Exception:
            pass

    return {
        "freeze_tags": freeze_ok,
        "clean_scan_green": clean_scan_ok,
        "sources_complete": sources_complete,
        "package_matrix_green": matrix_ok,
        "stranger_install_smoke": stranger_smoke_ok,
        "sanitizer_red_team_green": sanitizer_red_team_ok,
    }


def may_mark_ship_allowed(captain_report: dict) -> bool:
    """True only when captain checklist is fully green (fail closed)."""
    if not isinstance(captain_report, dict):
        return False
    return bool(captain_report.get("ship_allowed")) and bool(
        captain_report.get("ok")
    )


# ── Shipped pack presence helpers ────────────────────────────────────────────

def shipped_pack_paths(root=None) -> dict:
    """Paths to shipped W8 topology assets under the repo (or *root*)."""
    base = Path(root) if root is not None else _MODULE_DIR
    return {
        "contributing": base / "CONTRIBUTING.md",
        "pack_contributing": base / "share_topology_pack" / "CONTRIBUTING.md",
        "readme_a": base / "share_topology_pack" / "README-package-A.md",
        "readme_b": base / "share_topology_pack" / "README-package-B.md",
        "codeowners": base / "share_topology_pack" / "CODEOWNERS",
        "invite_checklist": (
            base / "share_topology_pack" / "collaborator-invite-checklist.md"
        ),
        "topology_ops": base / "docs" / "share-topology.md",
        "captain_doc": base / "docs" / "share-release-captain-checklist.md",
        "feedback_intake_docs": base / "docs" / "share-feedback-intake.md",
    }


def ensure_shipped_assets(root=None) -> dict:
    """Idempotently write topology pack + docs if missing or stale render."""
    return write_topology_docs(root)


# ── CLI (optional) ───────────────────────────────────────────────────────────

def main(argv=None) -> int:
    """``python share_topology.py write|check-captain|mirror-lag``."""
    import json
    import sys

    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ("-h", "--help"):
        print(
            "usage: share_topology.py write|check-captain|mirror-lag|policy",
            file=sys.stderr,
        )
        return 2
    cmd = args[0]
    if cmd == "write":
        report = write_topology_docs()
        print(json.dumps(report, indent=2))
        return 0
    if cmd == "policy":
        print(json.dumps(topology_policy(), indent=2))
        return 0
    if cmd == "check-captain":
        # Example: all red unless env/json provided — fail closed demo.
        status = {k: False for k in CAPTAIN_CHECKLIST_ITEMS}
        report = evaluate_captain_checklist(status)
        print(json.dumps(report, indent=2))
        return 0 if report["ship_allowed"] else 1
    if cmd == "mirror-lag":
        # Demo with empty lists (ok, no lag).
        report = check_mirror_lag([], [])
        print(json.dumps(report, indent=2))
        print(mirror_lag_badge(report))
        return 0 if report["ok"] else 1
    print("unknown command: %s" % cmd, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
