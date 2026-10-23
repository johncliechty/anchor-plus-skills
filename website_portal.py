"""Wave 24 — Public Website, Non-Resale License Gate, Multi-Platform Download Portal & Feedback Loop.

Implements:
1. Ghost World Lab Non-Resale License v1 (Refinement 2) (`anchor.license.non_resale.v1`):
   - `LICENSE_ID = "GHOST-WORLD-LAB-NON-RESALE-v1"` ("All rights reserved — not open source").
   - Operative clauses (Sections 1–10), Plain-English Companion table, and
     Contractor Labor vs. Non-Resale Boundary table.
   - Click-wrap acceptance (`accept_non_resale_license`) minting HMAC-SHA256
     signed `anchor.license.acceptance.v1` receipts persisted in
     `.anchor/license_acceptances.json`, plus `verify_license_acceptance_token`.
   - Never creates a root `LICENSE*` or `COPYING*` file so
     `share_ci_ship_gate.check_no_oss_license_stamp()` stays green.
2. Multi-Platform Download Portal (`get_download_catalog`, `authorize_package_download`):
   - Integrates with `share_package_matrix.py` (`gwl-skills` Package A and
     `gwl-anchor-and-skills` Package B) across `("windows", "macos", "linux")`
     and architectures `("x64", "arm64", "universal")`, plus `gwl-collab-client`.
   - Enforces fail-closed `403 license_acceptance_required` without a valid
     signed license receipt, and fail-closed `400 anchor_only_forbidden` on
     forbidden Anchor-only package requests.
3. Structured User Feedback & Sanitized Skill-Friction Loop
   (`submit_portal_feedback`, `get_feedback_loop_summary`):
   - Integrates with `share_feedback.py` and `share_feedback_intake.py`.
   - Requires explicit `consent_granted: True` (`consent_required_opt_in_only`).
   - Enforces `FEEDBACK_IS_NOT_CODE_CONTRIBUTION`, drops any PII/email/path/secret
     payload fail-closed (`fail_closed_dropped`), stores clean records in
     `by_skill/<skill_id>/`, and aggregates Foundry Sleep-Cycle Triage
     Recommendations.
4. Interactive Public Website HTML (`render_public_website_html()`):
   - Self-contained HTML page served at `/website` and `/download-portal`.

100% Python standard library only. Zero personal data.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import html as html_lib
import json
import os
import uuid
from collections import Counter
from pathlib import Path

import foundry_federation as ffed
import gwl_clearinghouse as gwl
import paths
import share_feedback as fb
import share_feedback_intake as fbi
import share_package_matrix as spm

# ── License Constants ────────────────────────────────────────────────────────

LICENSE_SCHEMA = "anchor.license.non_resale.v1"
LICENSE_ACCEPTANCE_SCHEMA = "anchor.license.acceptance.v1"
LICENSE_ID = "GHOST-WORLD-LAB-NON-RESALE-v1"
LICENSE_VERSION = "1.0-r2"
RIGHTS_RESERVED_NOTICE = "All rights reserved — not open source"
DEFAULT_PSEUDONYM = "Samwise Gamgee"
COLD_START_COMMAND = "python -m share_onboard"
INCLUDED_SKILLS_COUNT = 19

SUPPORTED_PLATFORMS = ("windows", "macos", "linux")
SUPPORTED_ARCHITECTURES = ("x64", "arm64", "universal")

_PLATFORM_ALIASES = {
    "windows": "windows",
    "win": "windows",
    "win32": "windows",
    "macos": "macos",
    "mac": "macos",
    "darwin": "macos",
    "osx": "macos",
    "linux": "linux",
}

# Domain material for deterministic HMAC-SHA256 receipt signing (stdlib-only, no secret literal).
_SIGNING_DOMAIN = b"ghost-world-lab-non-resale-license-v1-r2-receipt-hmac"

ALLOWED_FREE_PERMISSIONS = [
    {
        "id": "personal_use",
        "title": "Personal Use",
        "description": "Free worldwide use, study, execution, and reproduction of Anchor and Skill Foundry for personal projects.",
    },
    {
        "id": "academic_or_research",
        "title": "Academic & Scientific Research",
        "description": "Free use in academic labs, scientific manuscripts, mathematical verification, and non-commercial research collaborations.",
    },
    {
        "id": "internal_business",
        "title": "Internal Business Operations",
        "description": "Free operation of original or modified versions for Your own employees and contractors acting on Your behalf without a license fee.",
    },
    {
        "id": "private_modifications",
        "title": "Private Modifications (No Forced Upstream)",
        "description": "Modify Covered Software privately without any obligation to publish source changes or submit patches upstream.",
    },
    {
        "id": "voluntary_sharing",
        "title": "Voluntary Non-Commercial Sharing",
        "description": "Redistribute original or modified versions free of charge with license and attribution notices preserved.",
    },
    {
        "id": "contractor_custom_labor",
        "title": "Contractor & Staff Custom Programming Labor (Section 4)",
        "description": "Pay internal staff or outside contractors for actual custom programming labor delivered for the customer's own use, with zero recurring version-use fees.",
    },
]

RESTRICTED_NON_RESALE_RULES = [
    {
        "id": "one_time_software_sale",
        "title": "One-Time Software Sale Forbidden Without Separate Permission",
        "description": "Selling Covered Software, a modified version, or a renamed fork for a one-time software price is restricted under Section 3.",
    },
    {
        "id": "recurring_version_fees",
        "title": "Recurring License, Subscription, or Royalty Fees Forbidden",
        "description": "Charging monthly, annual, or royalty fees to receive or continue using a modified version is restricted under Sections 3 and 4.",
    },
    {
        "id": "paid_hosted_access_saas",
        "title": "Paid Hosted Access / SaaS Resale Forbidden",
        "description": "Charging customers or third parties for remote access to Covered Software functionality via a hosted UI, API, or paid intermediary requires Separate Permission.",
    },
    {
        "id": "paid_product_bundling",
        "title": "Paid Product Bundling Forbidden",
        "description": "Including Covered Software in a paid software bundle is restricted even if the Anchor component is listed at a separate price of zero.",
    },
]

OPERATIVE_CLAUSES = [
    {
        "section": 1,
        "title": "Identification and definitions",
        "summary": "Defines Licensor, Covered Software, Internal Users, Sale, Hosted Access, Paid Hosted Access, and Separate Permission.",
        "text": (
            "Primary Licensor: Ghost World Labs. Covered Software means the identified Anchor and Skill Foundry files, "
            "their copies and modifications. Sale means supplying a copy, modification, or rights to use in exchange for "
            "required payment, barter, or other consideration, including licenses, rentals, subscriptions, and paid bundles. "
            "Paying Internal Users or paying for custom programming services permitted by Section 4 (including delivery of "
            "resulting changes solely for the customer's own use) is not a Sale or Paid Hosted Access."
        ),
    },
    {
        "section": 2,
        "title": "Free permissions",
        "summary": "Grants worldwide, royalty-free permission for personal, research, internal business use, private modification, and free sharing.",
        "text": (
            "Subject to sections 3 through 9, each Licensor grants You a worldwide, nonexclusive, royalty-free copyright "
            "license to use, run, reproduce, study, modify, prepare derivative works of Covered Software, and distribute it "
            "without a Sale. You may provide free Hosted Access. You need not publish private modifications or submit patches upstream."
        ),
    },
    {
        "section": 3,
        "title": "Activities requiring Separate Permission",
        "summary": "Reserves software sales, recurring version-use fees, paid bundles, and Paid Hosted Access for Separate Permission.",
        "text": (
            "This license does not authorize a Sale of Covered Software, modified Covered Software, or a product containing "
            "Covered Software, even when adding substantial independent functionality or renaming. The restriction includes a "
            "one-time price for a copy and recurring license, royalty, subscription, or other fees for receiving or continuing "
            "to use a modified version. This license does not authorize Paid Hosted Access to original or modified Covered Software."
        ),
    },
    {
        "section": 4,
        "title": "Independent work and services",
        "summary": "Permits selling independent outputs and charging for actual custom programming labor delivered for a customer's own use.",
        "text": (
            "You may charge for independently created software and outputs containing no Covered Software. You may charge for "
            "programming labor to create or modify Covered Software for a customer's own use, including delivering the "
            "customer-specific changes under this license. Payment must buy programming services actually performed for that "
            "customer; the customer's exercise or retention of permissions must not depend on continuing payments to the programmer."
        ),
    },
    {
        "section": 5,
        "title": "Redistribution and modifications",
        "summary": "Requires keeping license and attribution notices and labeling material modifications without imposing fees.",
        "text": (
            "When distributing Covered Software, include this license, retain applicable copyright and attribution notices, "
            "and identify material modifications. Do not represent a modified version as an official release or impose a fee "
            "or additional restriction on the permissions granted by this instrument."
        ),
    },
    {
        "section": 6,
        "title": "Ownership, contributions and commercial permissions",
        "summary": "Each rights holder retains ownership; voluntary patches do not assign copyright or grant commercial resale rights.",
        "text": (
            "Each rights holder retains ownership of that holder's material. Modification, distribution, or voluntary submission "
            "does not assign copyright to the Licensor. Submitting a contribution does not, by itself, grant permission to sell "
            "that contributor's material under different terms."
        ),
    },
    {
        "section": 7,
        "title": "Other rights",
        "summary": "Grants no trademark license, endorsement right, or separate patent license.",
        "text": (
            "No trademark license or endorsement right is granted. Descriptive references do not permit presenting a fork as "
            "the Licensor's official product. This instrument grants the copyright permissions expressly stated above."
        ),
    },
    {
        "section": 8,
        "title": "Disclaimer and liability",
        "summary": "Supplies Covered Software as-is without warranties or liability to the extent permitted by law.",
        "text": (
            "To the extent permitted by applicable law, Covered Software is supplied without promises about quality, fitness "
            "for a particular task, security, accuracy, availability, or freedom from infringement, and a Licensor is not "
            "liable for losses arising from use or inability to use Covered Software."
        ),
    },
    {
        "section": 9,
        "title": "Compliance and termination",
        "summary": "Unauthorized sales or paid hosting are never permitted; other breaches use a 30-day written notice-and-cure process.",
        "text": (
            "A Sale or Paid Hosted Access outside Separate Permission is unauthorized when it occurs; no notice or cure period "
            "creates a temporary commercial permission. If You materially breach this license and do not cure within 30 days "
            "after written notice, Your permissions terminate without terminating a complying recipient's direct permissions."
        ),
    },
    {
        "section": 10,
        "title": "Governing law",
        "summary": "Governed by the Licensor's designated jurisdiction, subject to mandatory applicable law.",
        "text": (
            "This license is governed by the law of the jurisdiction designated by the Primary Licensor, subject to mandatory "
            "law that cannot be excluded."
        ),
    },
]

PLAIN_ENGLISH_COMPANION = [
    {
        "clause": 1,
        "meaning": "Identify the actual owner and covered code. Renaming a paid fork or bundling Anchor for 'free' does not remove the restriction. Connecting independent software does not automatically make it covered.",
    },
    {
        "clause": 2,
        "meaning": "Use Anchor at home or inside a business, change it privately, share a free fork, or offer free hosted access. You do not owe upstream contributions or publication of your modified source.",
    },
    {
        "clause": 3,
        "meaning": "Selling Anchor-based software or charging for hosted access needs separate written permission. A one-time software price and recurring fees for a modified version are both restricted.",
    },
    {
        "clause": 4,
        "meaning": "Sell independent work produced with Anchor when it contains no covered code. Staff and contractors may charge for actual programming labor, including delivering customer-specific changes for the customer's own use without recurring version payments.",
    },
    {
        "clause": 5,
        "meaning": "Keep notices and the license with copies, label changes, and respect third-party terms. This is not a source-disclosure requirement.",
    },
    {
        "clause": 6,
        "meaning": "Contributors keep their rights. A free or paid edition needs permission to redistribute contributed material.",
    },
    {
        "clause": 7,
        "meaning": "Grants no brand or explicit patent license; forks may not be presented as official Ghost World Labs releases.",
    },
    {
        "clause": 8,
        "meaning": "Disclaims warranties and limits liability as applicable law allows.",
    },
    {
        "clause": 9,
        "meaning": "Unauthorized sales and paid hosting receive no permission, including during a cure period. Compliant recipients keep their direct permissions.",
    },
    {
        "clause": 10,
        "meaning": "Establishes governing law mechanics subject to mandatory consumer and statutory protections.",
    },
]

CONTRACTOR_VS_NON_RESALE_TABLE = [
    {
        "transaction": "Pay a contractor or employee for actual programming labor and delivery of customer-specific changes for the customer's own use",
        "treatment": "Permitted under Sections 1 & 4; delivered covered code carries this license",
        "permitted": True,
        "category": "contractor_labor_permitted",
    },
    {
        "transaction": "Pay for actual later requested programming or maintenance services while customer keeps full free rights to existing version",
        "treatment": "Permitted under Section 4; continued use never depends on recurring payments",
        "permitted": True,
        "category": "contractor_labor_permitted",
    },
    {
        "transaction": "Use Anchor internally to produce paid reports, papers, designs, or independent code containing no Covered Software",
        "treatment": "Permitted under Section 4",
        "permitted": True,
        "category": "contractor_labor_permitted",
    },
    {
        "transaction": "Charge a one-time software price for Anchor or a modified Anchor copy",
        "treatment": "Restricted under Section 3; requires Separate Permission",
        "permitted": False,
        "category": "non_resale_restricted",
    },
    {
        "transaction": "Charge a monthly subscription, royalty, or recurring version-use fee to keep using a modified Anchor version",
        "treatment": "Restricted under Sections 3 & 4; requires Separate Permission",
        "permitted": False,
        "category": "non_resale_restricted",
    },
    {
        "transaction": "Resell a ready-made or renamed Anchor product (or bundle it into a paid offering)",
        "treatment": "Restricted under Section 3; requires Separate Permission",
        "permitted": False,
        "category": "non_resale_restricted",
    },
    {
        "transaction": "Charge customers for Hosted Access / SaaS access to Anchor functionality",
        "treatment": "Restricted under Section 3; requires Separate Permission",
        "permitted": False,
        "category": "non_resale_restricted",
    },
]


# ── Storage & Signing Helpers ────────────────────────────────────────────────

def _default_anchor_store_dir(store_dir=None) -> Path:
    if store_dir is not None:
        base = Path(store_dir)
        return base if base.name == ".anchor" else (base / ".anchor")
    return Path(paths.data_dir()) / ".anchor"


def license_acceptances_path(store_dir=None) -> Path:
    return _default_anchor_store_dir(store_dir) / "license_acceptances.json"


def _default_intake_root(intake_root=None) -> Path:
    if intake_root is not None:
        return Path(intake_root)
    return _default_anchor_store_dir(None) / fbi.DEFAULT_INTAKE_REL


def _signing_key_bytes() -> bytes:
    extra = (os.environ.get("GWL_PORTAL_SIGNING_MATERIAL") or "").encode("utf-8")
    return hashlib.sha256(_SIGNING_DOMAIN + b":" + extra).digest()


def _canonical_receipt_bytes(receipt: dict) -> bytes:
    core = {
        "schema": receipt.get("schema"),
        "token_id": receipt.get("token_id"),
        "pseudonym": receipt.get("pseudonym"),
        "license_id": receipt.get("license_id"),
        "version": receipt.get("version"),
        "intended_use": receipt.get("intended_use"),
        "accepted_non_resale": receipt.get("accepted_non_resale"),
        "accepted_at": receipt.get("accepted_at"),
    }
    return json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _compute_receipt_hmac(receipt: dict) -> str:
    return hmac.new(
        _signing_key_bytes(),
        _canonical_receipt_bytes(receipt),
        hashlib.sha256,
    ).hexdigest()


# ── 1. Non-Resale License Spec & Click-Wrap Gate ─────────────────────────────

def get_non_resale_license_spec() -> dict:
    """Return the structured Ghost World Lab Non-Resale License v1 (Refinement 2) spec."""
    return {
        "schema": LICENSE_SCHEMA,
        "license_id": LICENSE_ID,
        "version": LICENSE_VERSION,
        "title": "Ghost World Lab License — Version 1, Refinement 2",
        "rights_reserved_notice": RIGHTS_RESERVED_NOTICE,
        "not_open_source": True,
        "no_root_license_file_law": "no LICENSE file; rights reserved in USER-ONBOARD.md",
        "contact": "permissions@example.org",
        "allowed_free_permissions": list(ALLOWED_FREE_PERMISSIONS),
        "restricted_non_resale_rules": list(RESTRICTED_NON_RESALE_RULES),
        "operative_clauses": list(OPERATIVE_CLAUSES),
        "plain_english_companion": list(PLAIN_ENGLISH_COMPANION),
        "contractor_vs_non_resale_table": list(CONTRACTOR_VS_NON_RESALE_TABLE),
    }


def _load_acceptance_store(store_dir=None) -> dict:
    path = license_acceptances_path(store_dir)
    if not path.is_file():
        return {"schema": "anchor.license.acceptance_store.v1", "acceptances": []}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"schema": "anchor.license.acceptance_store.v1", "acceptances": []}
    if not isinstance(doc, dict) or not isinstance(doc.get("acceptances"), list):
        return {"schema": "anchor.license.acceptance_store.v1", "acceptances": []}
    return doc


def _save_acceptance_record(receipt: dict, store_dir=None) -> Path:
    doc = _load_acceptance_store(store_dir)
    acceptances = [
        r for r in doc.get("acceptances", [])
        if isinstance(r, dict) and r.get("token_id") != receipt.get("token_id")
    ]
    acceptances.append(receipt)
    doc["acceptances"] = acceptances
    path = license_acceptances_path(store_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def accept_non_resale_license(
    pseudonym_or_handle: str,
    accepted_non_resale: bool,
    intended_use: str = "personal_or_research",
    version: str = LICENSE_VERSION,
    *,
    store_dir=None,
) -> dict:
    """Mint and persist a signed `anchor.license.acceptance.v1` receipt token.

    Fails closed unless `accepted_non_resale is True`.
    """
    if accepted_non_resale is not True:
        return {
            "ok": False,
            "code": 400,
            "error": "license_acceptance_required",
            "message": "You must explicitly accept the Ghost World Lab Non-Resale License v1 terms before downloading.",
        }

    handle = (pseudonym_or_handle if isinstance(pseudonym_or_handle, str) else "").strip()
    if not handle:
        return {
            "ok": False,
            "code": 400,
            "error": "pseudonym_required",
            "message": "A collaborator pseudonym or handle is required to record license acceptance.",
        }

    use_val = (intended_use if isinstance(intended_use, str) else "personal_or_research").strip() or "personal_or_research"
    ver_val = (version if isinstance(version, str) else LICENSE_VERSION).strip() or LICENSE_VERSION
    now_iso = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tid = "gwl-lic-" + uuid.uuid4().hex[:16]

    receipt = {
        "schema": LICENSE_ACCEPTANCE_SCHEMA,
        "token_id": tid,
        "pseudonym": handle,
        "license_id": LICENSE_ID,
        "version": ver_val,
        "intended_use": use_val,
        "accepted_non_resale": True,
        "accepted_at": now_iso,
    }
    receipt["hmac_sha256"] = _compute_receipt_hmac(receipt)
    store_path = _save_acceptance_record(receipt, store_dir=store_dir)

    return {
        "ok": True,
        "code": 200,
        "schema": LICENSE_ACCEPTANCE_SCHEMA,
        "token_id": tid,
        "pseudonym": handle,
        "license_id": LICENSE_ID,
        "version": ver_val,
        "intended_use": use_val,
        "accepted_non_resale": True,
        "accepted_at": now_iso,
        "hmac_sha256": receipt["hmac_sha256"],
        "receipt": receipt,
        "store_path": str(store_path),
    }


def verify_license_acceptance_token(token_or_dict, *, store_dir=None) -> dict:
    """Verify a signed `anchor.license.acceptance.v1` receipt dict or token_id string."""
    if not token_or_dict:
        return {
            "ok": False,
            "valid": False,
            "code": 403,
            "error": "license_acceptance_required",
            "reason": "missing_token",
        }

    candidate = None
    if isinstance(token_or_dict, str):
        raw = token_or_dict.strip()
        if not raw:
            return {
                "ok": False,
                "valid": False,
                "code": 403,
                "error": "license_acceptance_required",
                "reason": "empty_token",
            }
        if raw.startswith("{"):
            try:
                candidate = json.loads(raw)
            except json.JSONDecodeError:
                return {
                    "ok": False,
                    "valid": False,
                    "code": 403,
                    "error": "license_acceptance_required",
                    "reason": "malformed_json_token",
                }
        else:
            store = _load_acceptance_store(store_dir=store_dir)
            for rec in store.get("acceptances", []):
                if isinstance(rec, dict) and rec.get("token_id") == raw:
                    candidate = rec
                    break
            if candidate is None:
                return {
                    "ok": False,
                    "valid": False,
                    "code": 403,
                    "error": "license_acceptance_required",
                    "reason": "unknown_token_id",
                }
    elif isinstance(token_or_dict, dict):
        if isinstance(token_or_dict.get("receipt"), dict):
            candidate = dict(token_or_dict["receipt"])
        else:
            candidate = dict(token_or_dict)
    else:
        return {
            "ok": False,
            "valid": False,
            "code": 403,
            "error": "license_acceptance_required",
            "reason": "invalid_token_type",
        }

    if not isinstance(candidate, dict):
        return {
            "ok": False,
            "valid": False,
            "code": 403,
            "error": "license_acceptance_required",
            "reason": "invalid_receipt_object",
        }

    if candidate.get("accepted_non_resale") is not True:
        return {
            "ok": False,
            "valid": False,
            "code": 403,
            "error": "license_acceptance_required",
            "reason": "license_not_accepted",
        }

    if candidate.get("license_id") != LICENSE_ID:
        return {
            "ok": False,
            "valid": False,
            "code": 403,
            "error": "license_acceptance_required",
            "reason": "license_id_mismatch",
        }

    for req_key in ("token_id", "pseudonym", "version", "accepted_at", "hmac_sha256"):
        val = candidate.get(req_key)
        if not isinstance(val, str) or not val.strip():
            return {
                "ok": False,
                "valid": False,
                "code": 403,
                "error": "license_acceptance_required",
                "reason": "missing_field:%s" % req_key,
            }

    # Ensure default fields used in canonical digest exist
    check_doc = dict(candidate)
    check_doc.setdefault("schema", LICENSE_ACCEPTANCE_SCHEMA)
    check_doc.setdefault("intended_use", "personal_or_research")
    expected_mac = _compute_receipt_hmac(check_doc)
    provided_mac = str(candidate.get("hmac_sha256") or "")

    if not hmac.compare_digest(expected_mac, provided_mac):
        return {
            "ok": False,
            "valid": False,
            "code": 403,
            "error": "license_acceptance_required",
            "reason": "hmac_signature_mismatch",
        }

    return {
        "ok": True,
        "valid": True,
        "code": 200,
        "token_id": candidate["token_id"],
        "pseudonym": candidate["pseudonym"],
        "license_id": candidate["license_id"],
        "version": candidate["version"],
        "receipt": check_doc,
    }


# ── 2. Multi-Platform Download Portal ────────────────────────────────────────

_PORTAL_PACKAGES = {
    "gwl-skills": {
        "package_id": "gwl-skills",
        "matrix_id": "A",
        "matrix_artifact_name": "share-skills",
        "title": "Package A · Ghost World Labs 19-Skill Foundry Pack (gwl-skills)",
        "subtitle": "Standalone 19-Skill Suite + Anvil 3-Level Progressive Maps + Poincaré Knowledge Disks",
        "includes_anchor": False,
        "includes_skills": True,
        "included_skills_count": INCLUDED_SKILLS_COUNT,
        "cold_start_command": COLD_START_COMMAND,
        "highlights": [
            "All 19 Trio & Skill Foundry skills (researchPrime, Crucible, Foreman, Gandalf, Anvil, Aegis, Ramanujan, Legal-Beagle, etc.)",
            "Interactive Anvil 3-Level Progressive Codebase Maps & Pure-Core/Imperative-Shell workbench",
            "Poincaré Hyperbolic Knowledge Disks & deterministic verification harnesses",
            "Zero Anchor process required — works directly in Claude Code, Gemini/AGY, Grok CLI, and Codex",
        ],
    },
    "gwl-anchor-and-skills": {
        "package_id": "gwl-anchor-and-skills",
        "matrix_id": "B",
        "matrix_artifact_name": "share-anchor-skills",
        "title": "Package B · Full Anchor Mothership + 19 Skills (gwl-anchor-and-skills)",
        "subtitle": "Cave of Wonders + AI Cockpits + 3 Steward Incarnations + 19 Foundry Skills + Multi-Mothership Collaboration",
        "includes_anchor": True,
        "includes_skills": True,
        "included_skills_count": INCLUDED_SKILLS_COUNT,
        "cold_start_command": COLD_START_COMMAND,
        "highlights": [
            "Complete Anchor R&D Control Surface: Cave of Wonders, Star Chart, The Desk, and AI Cockpits",
            "3 Steward Incarnations (Aladdin, Jarvis, Ecgberht) with Single-Leader Cockpit Baton",
            "All 19 Trio & Skill Foundry skills pinned & verified (B ⊇ A guarantee)",
            "GWL Clearinghouse + Tailscale P2P Multi-Mothership Collaboration & 4-Stage Aegis Federation",
        ],
    },
    "gwl-collab-client": {
        "package_id": "gwl-collab-client",
        "matrix_id": "A",
        "matrix_artifact_name": "share-skills",
        "title": "Collaborator Connection Client (gwl-collab-client)",
        "subtitle": "Lightweight Multi-Mothership Peer Bridge + Samwise Gamgee Pseudonym Identity + 19 Skills",
        "includes_anchor": False,
        "includes_skills": True,
        "included_skills_count": INCLUDED_SKILLS_COUNT,
        "cold_start_command": COLD_START_COMMAND,
        "highlights": [
            "Pre-wired Dual-Path Transport (GWL Hub Relay + Direct Tailscale P2P)",
            "Pseudonym identity onboarding (default: Samwise Gamgee) with zero personal data",
            "3-Tier Data/Paper sync & 4-Stage Aegis Quarantine verification for shared skills",
        ],
    },
}

_PACKAGE_ID_MAP = {
    "gwl-skills": "gwl-skills",
    "a": "gwl-skills",
    "package-a": "gwl-skills",
    "skills": "gwl-skills",
    "skills-only": "gwl-skills",
    "share-skills": "gwl-skills",
    "anchor-skills-a": "gwl-skills",
    "gwl-anchor-and-skills": "gwl-anchor-and-skills",
    "b": "gwl-anchor-and-skills",
    "package-b": "gwl-anchor-and-skills",
    "anchor-skills": "gwl-anchor-and-skills",
    "anchor+skills": "gwl-anchor-and-skills",
    "anchor-plus-skills": "gwl-anchor-and-skills",
    "share-anchor-skills": "gwl-anchor-and-skills",
    "anchor-skills-b": "gwl-anchor-and-skills",
    "gwl-collab-client": "gwl-collab-client",
    "collab-client": "gwl-collab-client",
}


def _artifact_digest(package_id: str, platform_os: str, arch: str) -> str:
    seed = f"gwl-v1.2.4:{package_id}:{platform_os}:{arch}:{LICENSE_ID}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()


def get_download_catalog() -> dict:
    """Return the multi-platform download catalog backed by `share_package_matrix`."""
    matrix_doc = spm.load_matrix()
    packages_out = []
    for pkg_id, spec in _PORTAL_PACKAGES.items():
        platforms_map = {}
        for plat in SUPPORTED_PLATFORMS:
            platforms_map[plat] = {}
            for arch in SUPPORTED_ARCHITECTURES:
                fname = f"{pkg_id}-{plat}-{arch}-v1.2.4.zip"
                platforms_map[plat][arch] = {
                    "artifact_filename": fname,
                    "sha256_manifest_digest": _artifact_digest(pkg_id, plat, arch),
                    "cold_start_command": COLD_START_COMMAND,
                }
        packages_out.append({
            **spec,
            "platforms": platforms_map,
        })

    hub = gwl.GWLClearinghouse()
    nightly_bulletin = hub.generate_nightly_broadcast()
    nightly_updates = hub.check_nightly_broadcast_updates(nightly_bulletin)
    nightly_broadcast_info = {
        **nightly_bulletin,
        **nightly_updates,
        "bulletin": nightly_bulletin,
    }

    return {
        "schema": "anchor.website.download_catalog.v1",
        "license_id": LICENSE_ID,
        "license_gate_required": True,
        "supported_platforms": list(SUPPORTED_PLATFORMS),
        "supported_architectures": list(SUPPORTED_ARCHITECTURES),
        "cold_start_command": COLD_START_COMMAND,
        "included_skills_count": INCLUDED_SKILLS_COUNT,
        "forbidden_artifact_patterns": list(matrix_doc.get("forbidden_artifact_patterns") or []),
        "zero_binary_law": ffed.ZERO_BINARY_LAW,
        "nightly_broadcast": nightly_broadcast_info,
        "packages": packages_out,
    }


def authorize_package_download(
    package_id: str,
    platform_os: str,
    license_token,
    *,
    arch: str = "x64",
    store_dir=None,
) -> dict:
    """Authorize a package download after verifying license acceptance and package matrix rules."""
    # Step 1: Fail-closed license verification (403 if missing, forged, or unaccepted)
    verified = verify_license_acceptance_token(license_token, store_dir=store_dir)
    if not verified.get("ok"):
        return {
            "ok": False,
            "code": 403,
            "error": "license_acceptance_required",
            "reason": verified.get("reason") or "license_not_accepted",
            "message": "Download refused: a valid signed Ghost World Lab Non-Resale License v1 acceptance token is required.",
        }

    # Step 2: Validate package_id via share_package_matrix (forbid anchor-only packages!)
    raw_pkg = (package_id if isinstance(package_id, str) else "").strip()
    norm_pkg = raw_pkg.lower().replace("_", "-")
    if not raw_pkg:
        return {
            "ok": False,
            "code": 400,
            "error": "unknown_package_id",
            "reason_codes": ["unknown_package_id"],
        }

    # Explicit check against share_package_matrix.is_anchor_only_name
    if norm_pkg not in _PACKAGE_ID_MAP and spm.is_anchor_only_name(raw_pkg):
        matrix_codes = spm.validate_publish_request({"artifact_name": raw_pkg})
        return {
            "ok": False,
            "code": 400,
            "error": "anchor_only_forbidden",
            "reason_codes": matrix_codes or ["anchor_only_forbidden"],
            "message": "Anchor-only packages are forbidden by share_package_matrix law; only Skills (A) or Anchor+Skills (B) may be distributed.",
        }

    canonical_pkg = _PACKAGE_ID_MAP.get(norm_pkg)
    if canonical_pkg is None:
        return {
            "ok": False,
            "code": 400,
            "error": "unknown_package_id",
            "reason_codes": ["unknown_package_id"],
        }

    spec = _PORTAL_PACKAGES[canonical_pkg]
    # Validate through share_package_matrix.assert_emit_allowed
    publish_req = {
        "package_id": spec["matrix_id"],
        "artifact_name": spec["matrix_artifact_name"],
        "skills_subtree_present": True,
        "skills_pin": {"tag": "v1.2.4-gwl", "commit": "a1b2c3d4e5f6"},
    }
    try:
        emit_decision = spm.assert_emit_allowed(publish_req)
    except spm.PackageMatrixError as exc:
        return {
            "ok": False,
            "code": 400,
            "error": exc.reason_codes[0] if exc.reason_codes else "emit_refused",
            "reason_codes": exc.reason_codes,
        }

    # Step 3: Normalize platform_os and architecture
    raw_plat = (platform_os if isinstance(platform_os, str) else "").strip().lower()
    norm_plat = _PLATFORM_ALIASES.get(raw_plat)
    if norm_plat not in SUPPORTED_PLATFORMS:
        return {
            "ok": False,
            "code": 400,
            "error": "unsupported_platform",
            "supported_platforms": list(SUPPORTED_PLATFORMS),
        }

    norm_arch = (arch if isinstance(arch, str) else "x64").strip().lower() or "x64"
    if norm_arch not in SUPPORTED_ARCHITECTURES:
        return {
            "ok": False,
            "code": 400,
            "error": "unsupported_architecture",
            "supported_architectures": list(SUPPORTED_ARCHITECTURES),
        }

    artifact_filename = f"{canonical_pkg}-{norm_plat}-{norm_arch}-v1.2.4.zip"
    digest = _artifact_digest(canonical_pkg, norm_plat, norm_arch)

    return {
        "ok": True,
        "code": 200,
        "download_id": "dl-" + uuid.uuid4().hex[:12],
        "package_id": canonical_pkg,
        "matrix_package_id": emit_decision["package_id"],
        "platform_os": norm_plat,
        "arch": norm_arch,
        "artifact_filename": artifact_filename,
        "sha256_manifest_digest": digest,
        "cold_start_command": COLD_START_COMMAND,
        "included_skills_count": INCLUDED_SKILLS_COUNT,
        "license_receipt_id": verified["token_id"],
        "license_id": LICENSE_ID,
        "pseudonym": verified["pseudonym"],
    }


# ── 3. Structured Opt-In Feedback & Sanitized Skill-Friction Loop ────────────

def sanitize_friction_record(candidate: dict) -> dict | None:
    """Delegate to `share_feedback.sanitize_for_export` (allowlist + fail-closed leak scan)."""
    return fb.sanitize_for_export(candidate)


def validate_edge_record(record: dict) -> list:
    """Delegate to `share_feedback_intake.validate_intake_edge`."""
    return fbi.validate_intake_edge(record)


def store_intake_record(intake_root, clean_record: dict) -> dict:
    """Delegate to `share_feedback_intake.deliver_to_intake` into `by_skill/<skill_id>/`."""
    return fbi.deliver_to_intake(intake_root, clean_record)


def submit_portal_feedback(payload: dict, *, intake_root=None) -> dict:
    """Validate, sanitize, and store an opt-in skill-friction feedback record.

    - Requires explicit `consent_granted is True` (fails closed otherwise).
    - Scans ALL input strings for PII, emails, Windows/POSIX absolute paths,
      secrets, or session-purpose prose before projection and drops fail-closed.
    - Enforces `FEEDBACK_IS_NOT_CODE_CONTRIBUTION` and stores under `by_skill/<skill_id>/`.
    """
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "code": 400,
            "error": "invalid_payload",
            "dropped": True,
            "policy": fbi.FEEDBACK_IS_NOT_CODE_CONTRIBUTION,
        }

    if payload.get("consent_granted") is not True:
        return {
            "ok": False,
            "code": 400,
            "error": "consent_required_opt_in_only",
            "dropped": True,
            "policy": fbi.FEEDBACK_IS_NOT_CODE_CONTRIBUTION,
            "message": "Feedback export is strictly opt-in; consent_granted must be True.",
        }

    # Pre-scan EVERY string leaf in the raw payload so PII/paths/secrets in any field
    # (including extra fields) cause an immediate fail-closed drop.
    leak_hits = []
    for field_path, text in fb._walk_strings(payload):
        hits = fb.detect_string_leaks(text)
        if hits:
            for h in hits:
                leak_hits.append(f"{field_path}:{h}")

    if leak_hits:
        return {
            "ok": False,
            "code": 422,
            "error": "fail_closed_dropped",
            "dropped": True,
            "reason": "pii_or_path_or_secret_detected",
            "leak_hits": leak_hits,
            "policy": fbi.FEEDBACK_IS_NOT_CODE_CONTRIBUTION,
        }

    skill_id = payload.get("skill_id")
    skill_version = payload.get("skill_version") or "1.0.0"
    outcome = payload.get("outcome") or "friction"

    install_key = payload.get("install_key")
    if not isinstance(install_key, str) or not fb._INSTALL_KEY_RE.match(install_key):
        install_key = fb.mint_install_key()

    raw_codes = payload.get("structural_failure_codes")
    if isinstance(raw_codes, str):
        raw_codes = [raw_codes]
    elif not isinstance(raw_codes, list):
        raw_codes = ["unknown"]

    raw_wcodes = payload.get("workaround_codes")
    if isinstance(raw_wcodes, str):
        raw_wcodes = [raw_wcodes]
    elif not isinstance(raw_wcodes, list):
        raw_wcodes = ["none"]

    raw_seats = payload.get("model_family_seats")
    if isinstance(raw_seats, str):
        raw_seats = [raw_seats]
    elif not isinstance(raw_seats, list):
        raw_seats = []

    raw_tokens = payload.get("workaround_tokens")
    if isinstance(raw_tokens, str):
        raw_tokens = [raw_tokens] if raw_tokens.strip() else []
    elif not isinstance(raw_tokens, list):
        raw_tokens = []

    candidate = {
        "schema": fb.FEEDBACK_SCHEMA,
        "schema_version": fb.FEEDBACK_SCHEMA_VERSION,
        "export_id": payload.get("export_id") or ("ex-" + uuid.uuid4().hex[:12]),
        "skill_id": skill_id,
        "skill_version": skill_version,
        "install_key": install_key,
        "outcome": outcome,
        "structural_failure_codes": raw_codes,
        "duration_band": payload.get("duration_band") or "unknown",
        "complexity_band": payload.get("complexity_band") or "unknown",
        "os_class": payload.get("os_class") or "windows",
        "model_family_seats": raw_seats,
        "workaround_codes": raw_wcodes,
        "workaround_tokens": raw_tokens,
    }
    if "source_record_id" in payload:
        candidate["source_record_id"] = payload["source_record_id"]

    clean = sanitize_friction_record(candidate)
    if clean is None:
        return {
            "ok": False,
            "code": 422,
            "error": "fail_closed_dropped",
            "dropped": True,
            "reason": "sanitizer_rejected",
            "policy": fbi.FEEDBACK_IS_NOT_CODE_CONTRIBUTION,
        }

    edge_problems = validate_edge_record(clean)
    if edge_problems:
        return {
            "ok": False,
            "code": 422,
            "error": "fail_closed_dropped",
            "dropped": True,
            "reason": "edge_validation_rejected",
            "edge_problems": edge_problems,
            "policy": fbi.FEEDBACK_IS_NOT_CODE_CONTRIBUTION,
        }

    target_root = _default_intake_root(intake_root)
    delivery = store_intake_record(target_root, clean)
    if not delivery.get("accepted"):
        return {
            "ok": False,
            "code": 422,
            "error": "fail_closed_dropped",
            "dropped": True,
            "reason": delivery.get("reason") or "intake_rejected",
            "policy": fbi.FEEDBACK_IS_NOT_CODE_CONTRIBUTION,
        }

    return {
        "ok": True,
        "code": 200,
        "accepted": True,
        "dropped": False,
        "skill_id": clean["skill_id"],
        "export_id": clean["export_id"],
        "partition_path": delivery["path"],
        "partition_dir": delivery["partition"],
        "sanitized_record": clean,
        "auto_merge": False,
        "feedback_is_code_contribution": False,
        "policy": fbi.FEEDBACK_IS_NOT_CODE_CONTRIBUTION,
    }


def get_feedback_loop_summary(intake_root=None) -> dict:
    """Compute per-skill sanitized report counts, top failure codes, workaround frequencies,
    and Foundry Sleep-Cycle Triage Recommendations."""
    target_root = _default_intake_root(intake_root)
    metrics = fbi.partition_metrics(target_root)

    global_failures: Counter = Counter()
    global_workarounds: Counter = Counter()
    reports_by_skill = {}
    triage_recommendations = []
    total_reports = 0

    for skill_id in sorted(metrics.keys()):
        records = fbi.list_partition_records(target_root, skill_id)
        skill_failures: Counter = Counter()
        skill_workarounds: Counter = Counter()
        skill_outcomes: Counter = Counter()

        for rec in records:
            total_reports += 1
            outc = rec.get("outcome") or "friction"
            skill_outcomes[outc] += 1
            for fc in rec.get("structural_failure_codes") or []:
                skill_failures[fc] += 1
                global_failures[fc] += 1
            for wc in rec.get("workaround_codes") or []:
                skill_workarounds[wc] += 1
                global_workarounds[wc] += 1

        top_fc = skill_failures.most_common(1)[0][0] if skill_failures else "none"
        top_wc = skill_workarounds.most_common(1)[0][0] if skill_workarounds else "none"
        reports_by_skill[skill_id] = {
            "skill_id": skill_id,
            "count": len(records),
            "outcomes": dict(skill_outcomes),
            "top_failure_codes": [
                {"code": c, "count": n} for c, n in skill_failures.most_common()
            ],
            "workaround_frequencies": dict(skill_workarounds),
        }

        if records:
            triage_recommendations.append({
                "skill_id": skill_id,
                "report_count": len(records),
                "primary_failure_code": top_fc,
                "primary_workaround": top_wc,
                "recommended_action": (
                    f"Schedule formal Skill Foundry sleep-cycle improvement pass for '{skill_id}' "
                    f"targeting '{top_fc}' (observed {len(records)} sanitized report(s); "
                    f"common workaround: '{top_wc}')."
                ),
                "ad_hoc_patching_forbidden": True,
                "auto_merge_to_skill_sources": False,
            })

    return {
        "schema": "anchor.website.feedback_summary.v1",
        "intake_root": str(target_root),
        "total_sanitized_reports": total_reports,
        "skill_ids": sorted(reports_by_skill.keys()),
        "reports_by_skill": reports_by_skill,
        "top_structural_failure_codes": [
            {"code": c, "count": n} for c, n in global_failures.most_common()
        ],
        "workaround_frequencies": dict(global_workarounds),
        "foundry_sleep_cycle_triage_recommendations": triage_recommendations,
        "auto_merge_allowed": fbi.auto_merge_allowed(),
        "feedback_is_code_contribution": False,
        "policy": fbi.FEEDBACK_IS_NOT_CODE_CONTRIBUTION,
    }


def get_portal_state(*, store_dir=None, intake_root=None) -> dict:
    """Return combined catalog, Non-Resale License spec, and feedback loop summary for `/api/website/catalog`."""
    store = _load_acceptance_store(store_dir=store_dir)
    cat = get_download_catalog()
    return {
        "ok": True,
        "schema": "anchor.website.portal_state.v1",
        "license": get_non_resale_license_spec(),
        "catalog": cat,
        "nightly_broadcast": cat.get("nightly_broadcast"),
        "zero_binary_law": ffed.ZERO_BINARY_LAW,
        "feedback_loop": get_feedback_loop_summary(intake_root=intake_root),
        "recorded_acceptances_count": len(store.get("acceptances") or []),
    }


# ── 4. Interactive Public Website HTML ───────────────────────────────────────

def render_public_website_html(*, store_dir=None, intake_root=None) -> str:
    """Render the self-contained Ghost World Labs Public Website & Download Portal HTML."""
    lic = get_non_resale_license_spec()
    cat = get_download_catalog()
    fb_summary = get_feedback_loop_summary(intake_root=intake_root)

    clauses_html = []
    for cl in lic["operative_clauses"]:
        clauses_html.append(
            f'<div class="clause-card">'
            f'<div class="clause-hdr"><span class="sec-num">Section {cl["section"]}</span> '
            f'<strong>{html_lib.escape(cl["title"])}</strong></div>'
            f'<p class="clause-text">{html_lib.escape(cl["text"])}</p>'
            f'</div>'
        )

    companion_rows = []
    for row in lic["plain_english_companion"]:
        companion_rows.append(
            f'<tr><td class="col-sec">Clause {row["clause"]}</td>'
            f'<td>{html_lib.escape(row["meaning"])}</td></tr>'
        )

    boundary_rows = []
    for row in lic["contractor_vs_non_resale_table"]:
        badge_cls = "badge-allow" if row["permitted"] else "badge-restrict"
        badge_txt = "PERMITTED (Free / Custom Labor)" if row["permitted"] else "RESTRICTED (Separate Permission)"
        boundary_rows.append(
            f'<tr>'
            f'<td>{html_lib.escape(row["transaction"])}</td>'
            f'<td><span class="pill {badge_cls}">{badge_txt}</span></td>'
            f'<td>{html_lib.escape(row["treatment"])}</td>'
            f'</tr>'
        )

    pkg_cards_html = []
    for pkg in cat["packages"]:
        bullets = "".join(f"<li>{html_lib.escape(h)}</li>" for h in pkg["highlights"])
        pkg_id = html_lib.escape(pkg["package_id"])
        pkg_cards_html.append(
            f'<div class="pkg-card" data-package-id="{pkg_id}">'
            f'<div class="pkg-badge">Matrix Package {html_lib.escape(pkg["matrix_id"])} · {pkg["included_skills_count"]} Verified Skills</div>'
            f'<h3>{html_lib.escape(pkg["title"])}</h3>'
            f'<p class="pkg-sub">{html_lib.escape(pkg["subtitle"])}</p>'
            f'<ul class="pkg-list">{bullets}</ul>'
            f'<div class="dl-controls">'
            f'  <label>Platform OS: '
            f'    <select class="plat-select" id="plat-{pkg_id}">'
            f'      <option value="windows">Windows (x64 / arm64)</option>'
            f'      <option value="macos">macOS (Universal / Apple Silicon)</option>'
            f'      <option value="linux">Linux (x64 / arm64)</option>'
            f'    </select>'
            f'  </label>'
            f'  <button type="button" class="btn-download locked" data-pkg="{pkg_id}" onclick="authorizeDownload(\'{pkg_id}\')" disabled>'
            f'    🔒 Accept Non-Resale License to Unlock Download'
            f'  </button>'
            f'</div>'
            f'<div class="dl-manifest-box" id="manifest-{pkg_id}" style="display:none;"></div>'
            f'</div>'
        )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Ghost World Labs · Anchor &amp; 19-Skill Foundry Download Portal</title>
  <link rel="icon" href="/favicon.ico" />
  <style>
    :root {{
      --bg: #080b11;
      --panel: #101622;
      --panel-alt: #151d2e;
      --border: #25324d;
      --text: #e8ecf4;
      --muted: #9aa7c2;
      --accent: #63b3ed;
      --gold: #f6ad55;
      --green: #48bb78;
      --red: #fc8181;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: radial-gradient(circle at top right, #14213d 0%, var(--bg) 55%);
      color: var(--text);
      line-height: 1.55;
    }}
    .wrap {{
      max-width: 1220px;
      margin: 0 auto;
      padding: 28px 24px 64px;
    }}
    .masthead {{
      display: flex;
      flex-wrap: wrap;
      justify-content: space-between;
      align-items: center;
      gap: 16px;
      padding: 24px 28px;
      background: linear-gradient(135deg, #11192b 0%, #0d1320 100%);
      border: 1px solid var(--border);
      border-radius: 14px;
      margin-bottom: 26px;
    }}
    .masthead h1 {{
      margin: 0 0 6px;
      font-size: 1.75rem;
      letter-spacing: -0.02em;
    }}
    .masthead p {{
      margin: 0;
      color: var(--muted);
      font-size: 0.96rem;
    }}
    .rights-badge {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      padding: 8px 14px;
      border-radius: 999px;
      background: rgba(246, 173, 85, 0.14);
      border: 1px solid var(--gold);
      color: var(--gold);
      font-weight: 600;
      font-size: 0.85rem;
    }}
    .grid-2 {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(360px, 1fr));
      gap: 20px;
      margin-bottom: 26px;
    }}
    .section-panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 24px;
      margin-bottom: 26px;
    }}
    .section-panel h2 {{
      margin-top: 0;
      font-size: 1.3rem;
      border-bottom: 1px solid var(--border);
      padding-bottom: 10px;
    }}
    .clause-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 12px;
      max-height: 380px;
      overflow-y: auto;
      padding-right: 6px;
      margin-bottom: 18px;
    }}
    .clause-card {{
      background: var(--panel-alt);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px 14px;
    }}
    .sec-num {{
      color: var(--accent);
      font-weight: 700;
      font-size: 0.82rem;
      text-transform: uppercase;
      margin-right: 6px;
    }}
    .clause-text {{
      margin: 6px 0 0;
      color: var(--muted);
      font-size: 0.88rem;
    }}
    table.portal-table {{
      width: 100%;
      border-collapse: collapse;
      margin: 14px 0 20px;
      font-size: 0.9rem;
    }}
    table.portal-table th, table.portal-table td {{
      border: 1px solid var(--border);
      padding: 10px 12px;
      text-align: left;
      vertical-align: top;
    }}
    table.portal-table th {{
      background: var(--panel-alt);
      color: var(--accent);
    }}
    .pill {{
      display: inline-block;
      padding: 3px 9px;
      border-radius: 999px;
      font-size: 0.78rem;
      font-weight: 600;
    }}
    .badge-allow {{
      background: rgba(72, 187, 120, 0.16);
      color: var(--green);
      border: 1px solid var(--green);
    }}
    .badge-restrict {{
      background: rgba(252, 129, 129, 0.16);
      color: var(--red);
      border: 1px solid var(--red);
    }}
    .clickwrap-box {{
      background: linear-gradient(135deg, rgba(99, 179, 237, 0.1), rgba(72, 187, 120, 0.08));
      border: 1px solid var(--accent);
      border-radius: 12px;
      padding: 18px 20px;
      margin-top: 16px;
    }}
    .form-row {{
      display: flex;
      flex-wrap: wrap;
      gap: 14px;
      align-items: center;
      margin-bottom: 12px;
    }}
    input[type="text"], select {{
      background: #0b101b;
      color: var(--text);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 9px 12px;
      font-size: 0.92rem;
    }}
    button.btn-primary, button.btn-download {{
      background: var(--accent);
      color: #07101d;
      border: none;
      border-radius: 8px;
      padding: 10px 18px;
      font-weight: 700;
      font-size: 0.92rem;
      cursor: pointer;
    }}
    button.btn-download.locked {{
      background: #2b364d;
      color: var(--muted);
      cursor: not-allowed;
    }}
    .pkg-card {{
      background: var(--panel-alt);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }}
    .pkg-badge {{
      color: var(--gold);
      font-size: 0.8rem;
      font-weight: 700;
      text-transform: uppercase;
      margin-bottom: 6px;
    }}
    .pkg-sub {{
      color: var(--muted);
      font-size: 0.9rem;
      margin-top: 4px;
    }}
    .pkg-list {{
      padding-left: 18px;
      color: var(--text);
      font-size: 0.9rem;
    }}
    .dl-controls {{
      margin-top: 14px;
      display: flex;
      flex-direction: column;
      gap: 10px;
    }}
    .dl-manifest-box {{
      margin-top: 12px;
      padding: 12px;
      background: #09131c;
      border: 1px solid var(--green);
      border-radius: 8px;
      font-family: monospace;
      font-size: 0.84rem;
      color: #9ae6b4;
    }}
    .status-banner {{
      margin-top: 10px;
      padding: 10px 14px;
      border-radius: 8px;
      font-size: 0.9rem;
      display: none;
    }}
  </style>
</head>
<body>
  <div class="wrap">
    <header class="masthead">
      <div>
        <h1>Ghost World Labs · Anchor &amp; Skill Foundry Portal</h1>
        <p>Source-Available Research &amp; Engineering Distribution · Package A (<code>gwl-skills</code>) &amp; Package B (<code>gwl-anchor-and-skills</code>)</p>
      </div>
      <div class="rights-badge" data-license-id="{html_lib.escape(LICENSE_ID)}">
        <span>⚖️ {html_lib.escape(RIGHTS_RESERVED_NOTICE)} · {html_lib.escape(LICENSE_ID)} ({html_lib.escape(LICENSE_VERSION)})</span>
      </div>
    </header>

    <section class="section-panel" id="license-section">
      <h2>1. Ghost World Lab Non-Resale License v1 (Refinement 2) — Click-Wrap Gate</h2>
      <p>
        Anchor and the 19 Skill Foundry skills are shared under the <strong>Ghost World Lab License (Version 1, Refinement 2)</strong>
        (<code>{html_lib.escape(LICENSE_ID)}</code>). Free personal, academic/research, and internal business use—plus paying staff or outside
        contractors for actual custom programming labor delivered for the customer's own use—are expressly permitted.
        <strong>Selling Anchor or a modified Anchor version for a one-time price, charging recurring version-use fees, Paid Hosted Access (SaaS),
        or paid bundling requires Separate Written Permission.</strong>
      </p>

      <div class="clause-grid">
        {"".join(clauses_html)}
      </div>

      <h3>Contractor Custom Programming Labor vs. Non-Resale Boundary (Refinement 2)</h3>
      <table class="portal-table">
        <thead>
          <tr>
            <th>Transaction / Scenario</th>
            <th>Status</th>
            <th>Refinement 2 Operative Treatment</th>
          </tr>
        </thead>
        <tbody>
          {"".join(boundary_rows)}
        </tbody>
      </table>

      <details>
        <summary style="cursor:pointer;color:var(--accent);font-weight:600;">View Plain-English Companion (Clauses 1–10)</summary>
        <table class="portal-table">
          <thead>
            <tr><th>Clause</th><th>Plain-English Meaning for an Anchor User</th></tr>
          </thead>
          <tbody>
            {"".join(companion_rows)}
          </tbody>
        </table>
      </details>

      <div class="clickwrap-box">
        <div class="form-row">
          <label for="lic-pseudonym"><strong>Collaborator Pseudonym / Handle:</strong></label>
          <input type="text" id="lic-pseudonym" value="{html_lib.escape(DEFAULT_PSEUDONYM)}" />
          <label for="lic-intended-use"><strong>Intended Use:</strong></label>
          <select id="lic-intended-use">
            <option value="personal_or_research">Personal / Academic Research</option>
            <option value="internal_business">Internal Business Operations</option>
            <option value="custom_contractor_labor">Permitted Custom Programming Services (Sec. 4)</option>
          </select>
        </div>
        <div class="form-row">
          <label style="cursor:pointer;">
            <input type="checkbox" id="lic-accept-chk" />
            I have read and agree to the <strong>Ghost World Lab Non-Resale License v1 ({html_lib.escape(LICENSE_ID)})</strong>,
            including the Non-Resale Rule (Section 3) and the Contractor Programming Labor boundary (Section 4).
          </label>
          <button type="button" class="btn-primary" id="btn-accept-license" onclick="submitLicenseAcceptance()">
            Sign &amp; Mint License Acceptance Receipt
          </button>
        </div>
        <div id="license-receipt-banner" class="status-banner"></div>
      </div>
    </section>

    <section class="section-panel" id="download-matrix-section">
      <h2>2. Multi-Platform Download Portal (Windows · macOS · Linux)</h2>
      <p>
        Downloads remain locked (HTTP <code>403 license_acceptance_required</code>) until you sign the Non-Resale License above.
        Per <code>share_package_matrix.py</code> law, <code>anchor-only</code> packages are strictly forbidden (HTTP <code>400 anchor_only_forbidden</code>).
        After unzipping any package, run cold-start onboarding with: <code>{html_lib.escape(COLD_START_COMMAND)}</code>.
      </p>
      <div class="grid-2">
        {"".join(pkg_cards_html)}
      </div>
    </section>

    <section class="section-panel" id="feedback-loop-section">
      <h2>3. Opt-In Sanitized Skill-Friction &amp; Portal Feedback Loop</h2>
      <p>
        <strong>Policy:</strong> {html_lib.escape(fbi.FEEDBACK_IS_NOT_CODE_CONTRIBUTION)}
        Any payload without explicit opt-in consent (<code>consent_granted: true</code>) or containing personal emails,
        Windows/POSIX user paths, or secret tokens is dropped fail-closed (<code>fail_closed_dropped</code>).
        Clean records land in hard per-skill partitions (<code>by_skill/&lt;skill_id&gt;/</code>) to guide formal
        <strong>Skill Foundry Sleep-Cycle Triage</strong>.
      </p>
      <div class="form-row">
        <label>Skill ID:
          <select id="fb-skill-id">
            <option value="researchprime">researchprime</option>
            <option value="crucible">crucible</option>
            <option value="foreman">foreman</option>
            <option value="gandalf">gandalf</option>
            <option value="anvil">anvil</option>
            <option value="aegis">aegis</option>
            <option value="ramanujan">ramanujan</option>
            <option value="legal-beagle">legal-beagle</option>
          </select>
        </label>
        <label>Outcome:
          <select id="fb-outcome">
            <option value="friction">friction</option>
            <option value="workaround">workaround</option>
            <option value="failed">failed</option>
            <option value="refused">refused</option>
          </select>
        </label>
        <label>Failure Code:
          <select id="fb-failure-code">
            <option value="timeout">timeout</option>
            <option value="seat_failover">seat_failover</option>
            <option value="gate_red">gate_red</option>
            <option value="tool_missing">tool_missing</option>
            <option value="parse_error">parse_error</option>
          </select>
        </label>
        <label>Workaround:
          <select id="fb-workaround">
            <option value="retry">retry</option>
            <option value="seat_switch">seat_switch</option>
            <option value="manual_fix">manual_fix</option>
            <option value="reduce_scope">reduce_scope</option>
            <option value="none">none</option>
          </select>
        </label>
      </div>
      <div class="form-row">
        <label style="cursor:pointer;">
          <input type="checkbox" id="fb-consent-chk" />
          Explicit Opt-In Consent (<code>consent_granted: true</code>) — Export allowlisted enum friction only (zero PII, zero paths, zero prompts)
        </label>
        <button type="button" class="btn-primary" onclick="submitPortalFeedback()">
          Submit Sanitized Skill-Friction Report
        </button>
      </div>
      <div id="feedback-status-banner" class="status-banner"></div>
      <div style="margin-top:14px;color:var(--muted);font-size:0.88rem;">
        Active Sanitized Reports in Intake: <strong id="fb-total-count">{fb_summary["total_sanitized_reports"]}</strong> ·
        Auto-Merge to Skill Sources: <strong>False (Pull/Review &amp; Sleep-Cycle Only)</strong>
      </div>
    </section>
  </div>

  <script>
    let currentLicenseReceipt = null;

    async function submitLicenseAcceptance() {{
      const pseudonym = document.getElementById('lic-pseudonym').value.trim();
      const intendedUse = document.getElementById('lic-intended-use').value;
      const accepted = document.getElementById('lic-accept-chk').checked;
      const banner = document.getElementById('license-receipt-banner');
      banner.style.display = 'block';

      try {{
        const res = await fetch('/api/website/license/accept', {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            pseudonym_or_handle: pseudonym,
            accepted_non_resale: accepted,
            intended_use: intendedUse
          }})
        }});
        const data = await res.json();
        if (!res.ok || !data.ok) {{
          banner.style.background = 'rgba(252, 129, 129, 0.16)';
          banner.style.border = '1px solid #fc8181';
          banner.textContent = 'Refused (' + res.status + '): ' + (data.error || 'license_acceptance_required');
          return;
        }}
        currentLicenseReceipt = data.receipt;
        banner.style.background = 'rgba(72, 187, 120, 0.16)';
        banner.style.border = '1px solid #48bb78';
        banner.textContent = '✓ Signed Receipt Minted: ' + data.token_id + ' · HMAC-SHA256: ' + data.hmac_sha256.slice(0, 16) + '…';
        document.querySelectorAll('.btn-download').forEach(btn => {{
          btn.disabled = false;
          btn.classList.remove('locked');
          btn.textContent = '⬇ Authorize & Download Package (' + btn.getAttribute('data-pkg') + ')';
        }});
      }} catch (err) {{
        banner.textContent = 'Error: ' + err;
      }}
    }}

    async function authorizeDownload(packageId) {{
      const platSel = document.getElementById('plat-' + packageId);
      const platformOs = platSel ? platSel.value : 'windows';
      const box = document.getElementById('manifest-' + packageId);
      box.style.display = 'block';

      const res = await fetch('/api/website/download', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify({{
          package_id: packageId,
          platform_os: platformOs,
          license_token: currentLicenseReceipt
        }})
      }});
      const data = await res.json();
      if (!res.ok || !data.ok) {{
        box.textContent = 'Refused (' + res.status + '): ' + (data.error || 'unauthorized');
        return;
      }}
      box.innerHTML =
        '<div><strong>Authorized Artifact:</strong> ' + data.artifact_filename + '</div>' +
        '<div><strong>SHA-256 Digest:</strong> ' + data.sha256_manifest_digest.slice(0, 24) + '…</div>' +
        '<div><strong>Cold-Start Command:</strong> <code>' + data.cold_start_command + '</code></div>' +
        '<div><strong>License Receipt:</strong> ' + data.license_receipt_id + ' (' + data.included_skills_count + ' skills)</div>';
    }}

    async function submitPortalFeedback() {{
      const banner = document.getElementById('feedback-status-banner');
      banner.style.display = 'block';
      const payload = {{
        consent_granted: document.getElementById('fb-consent-chk').checked,
        skill_id: document.getElementById('fb-skill-id').value,
        skill_version: '1.0.0',
        outcome: document.getElementById('fb-outcome').value,
        structural_failure_codes: [document.getElementById('fb-failure-code').value],
        workaround_codes: [document.getElementById('fb-workaround').value],
        os_class: 'windows'
      }};
      const res = await fetch('/api/website/feedback', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(payload)
      }});
      const data = await res.json();
      if (!res.ok || !data.ok) {{
        banner.style.background = 'rgba(252, 129, 129, 0.16)';
        banner.style.border = '1px solid #fc8181';
        banner.textContent = 'Dropped (' + res.status + '): ' + (data.error || 'rejected');
        return;
      }}
      banner.style.background = 'rgba(72, 187, 120, 0.16)';
      banner.style.border = '1px solid #48bb78';
      banner.textContent = '✓ Stored Sanitized Record ' + data.export_id + ' in by_skill/' + data.skill_id + '/';
    }}
  </script>
</body>
</html>
"""
