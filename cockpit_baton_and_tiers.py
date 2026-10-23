"""Wave 22.4 — AI Cockpit Steward, Single-Leader Baton, 3-Tier Hybrid Data/Papers & Multi-Agent GitHub (stdlib only).

Implements:
- Single-Leader Cockpit Baton (``anchor.cockpit.baton.v1``):
  - ``init_or_get_baton``, ``transfer_lead_baton``, ``validate_roadmap_mutation``.
  - Monotonic ``baton_epoch`` + cryptographic signature verification; prevents structural ``roadmap.json``
    split-brain while allowing non-lead collaborators to update their leased ``step_id``s.
- 6 Mandatory Human Escalation Triggers (``check_human_escalation_triggers``):
  - ``HT-1`` North Star change, ``HT-2`` Baton transfer, ``HT-3`` Turn cap exceeded,
    ``HT-4`` Cloud compute budget, ``HT-5`` Cross-family review blocker, ``HT-6`` Foundry quarantine promotion.
- 3-Tier Hybrid Data, Paper & Cloud Execution Classifier (``classify_and_manifest_resources``):
  - Tier 1 (``< 5 MB``, ``local_replicated``): Cockpit JSONs, code, and active papers with ``doc_sha256``.
  - Tier 2 (``5 MB - 500 MB``, ``cas_pointer_link``): ``anchor.resource.link.v1`` hydrated into ``.anchor/cas/sha256/<sha256>``.
  - Tier 3 (``> 500 MB``, ``shared_cloud_workspace``): ``anchor.cloud.workspace.v1`` + ``< 50 KB`` signed ``anchor.cloud.receipt.v1``.
- Multi-Agent GitHub Branch Coordinator (``plan_multi_agent_branches``):
  - Conflict-free topology: ``main <- cockpit/<project_uid>/integration <- step/<pseudonym_slug>/<step_id>``.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

import anchor_agent_protocol as aap


BATON_SCHEMA = "anchor.cockpit.baton.v1"
TIER1_PAPER_SCHEMA = "anchor.paper.sync.v1"
TIER2_RESOURCE_SCHEMA = "anchor.resource.link.v1"
TIER3_WORKSPACE_SCHEMA = "anchor.cloud.workspace.v1"
TIER3_RECEIPT_SCHEMA = "anchor.cloud.receipt.v1"

TIER1_MAX_BYTES = 5 * 1024 * 1024        # 5 MB
TIER2_MAX_BYTES = 500 * 1024 * 1024      # 500 MB
MAX_CLOUD_RECEIPT_BYTES = 50 * 1024      # 50 KB

HUMAN_TRIGGERS: dict[str, dict[str, str]] = {
    "HT-1": {
        "code": "HT-1",
        "name": "north_star_change",
        "title": "North Star / Locked Objective Change",
        "description": "Any modification to the project North Star or locked success criteria requires human approval.",
    },
    "HT-2": {
        "code": "HT-2",
        "name": "baton_transfer",
        "title": "Single-Leader Cockpit Baton Transfer",
        "description": "Transferring the Single-Leader Cockpit Baton between collaborators requires explicit human confirmation.",
    },
    "HT-3": {
        "code": "HT-3",
        "name": "turn_cap_exceeded",
        "title": "Agent-to-Agent Dialogue Turn Budget Exceeded",
        "description": "Steward-to-Steward dialogue reached max_turns without convergence and escalated to HUMAN_SIGNAL.",
    },
    "HT-4": {
        "code": "HT-4",
        "name": "cloud_compute_budget",
        "title": "Shared Cloud Compute Budget Threshold",
        "description": "Tier-3 cloud execution job exceeds the pre-authorized spend or GPU duration threshold.",
    },
    "HT-5": {
        "code": "HT-5",
        "name": "cross_family_review_blocker",
        "title": "Cross-Family Adversarial Review Blocker",
        "description": ">=2 adversarial reviewers agreed on an unresolved architectural BLOCKER.",
    },
    "HT-6": {
        "code": "HT-6",
        "name": "foundry_quarantine_promotion",
        "title": "Skill Foundry Quarantine Promotion",
        "description": "Promoting a peer-shared skill from .anchor/foundry_quarantine/ into live execution requires human sign-off.",
    },
}

_TRIGGER_ALIAS_MAP: dict[str, str] = {
    "ht-1": "HT-1",
    "north_star_change": "HT-1",
    "north_star": "HT-1",
    "ht-2": "HT-2",
    "baton_transfer": "HT-2",
    "lead_baton_transfer": "HT-2",
    "ht-3": "HT-3",
    "turn_cap_exceeded": "HT-3",
    "max_turns_exceeded": "HT-3",
    "ht-4": "HT-4",
    "cloud_compute_budget": "HT-4",
    "budget_exceeded": "HT-4",
    "ht-5": "HT-5",
    "cross_family_review_blocker": "HT-5",
    "review_blocker": "HT-5",
    "ht-6": "HT-6",
    "foundry_quarantine_promotion": "HT-6",
    "quarantine_promotion": "HT-6",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _baton_file(cdir: str | Path) -> Path:
    return Path(cdir) / "cockpit_baton.json"


def check_human_escalation_triggers(
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate the 6 mandatory Human-in-the-Loop Escalation Triggers (``HT-1`` through ``HT-6``)."""
    raw = str(event_type or "").strip().lower()
    code = _TRIGGER_ALIAS_MAP.get(raw, str(event_type or "").strip().upper())
    data = dict(payload or {})

    if code not in HUMAN_TRIGGERS:
        return {
            "ok": True,
            "escalate": False,
            "trigger_id": "",
            "intent": "ASK_DIALOGUE",
            "reason": "no_human_trigger_matched",
        }

    meta = HUMAN_TRIGGERS[code]
    escalate = True
    if code == "HT-3":
        turn_idx = int(data.get("turn_index") or 7)
        max_t = int(data.get("max_turns") or aap.DEFAULT_MAX_TURNS)
        escalate = turn_idx > max_t
    elif code == "HT-4":
        cost = float(data.get("estimated_cost_usd") or 100.0)
        limit = float(data.get("budget_limit_usd") or 25.0)
        escalate = cost > limit
    elif code == "HT-5":
        blockers = int(data.get("blocker_agreement_count") or 2)
        escalate = blockers >= 2

    return {
        "ok": True,
        "escalate": escalate,
        "trigger_id": code,
        "trigger_name": meta["name"],
        "title": meta["title"],
        "description": meta["description"],
        "intent": "HUMAN_SIGNAL" if escalate else "ASK_DIALOGUE",
        "payload": aap.scrub_private_identity_leaks(data),
        "evaluated_at": _utc_now_iso(),
    }


def init_or_get_baton(
    cdir: str | Path,
    lead_did: str = "did:anchor:samwise-gamgee",
    lead_pseudonym: str = aap.PSEUDONYM_DEFAULT,
    project_uid: str = "",
    force_reset: bool = False,
) -> dict[str, Any]:
    """Load or initialize the Single-Leader Cockpit Baton (``anchor.cockpit.baton.v1``) in ``cdir``."""
    cpath = Path(cdir)
    cpath.mkdir(parents=True, exist_ok=True)
    bf = _baton_file(cpath)

    if bf.is_file() and not force_reset:
        try:
            existing = json.loads(bf.read_text(encoding="utf-8"))
            if isinstance(existing, dict) and existing.get("schema") == BATON_SCHEMA:
                return existing
        except Exception:
            pass

    canon_pseudo, _ = (
        aap.canonicalize_pseudonym(lead_pseudonym)
        if aap.slugify_pseudonym(lead_pseudonym) in ("samwise-gamgee", "samwise-gamgi", "samwise")
        else (str(lead_pseudonym or aap.PSEUDONYM_DEFAULT).strip(), [])
    )
    eff_did = str(lead_did or aap.did_from_pseudonym(canon_pseudo)).strip()
    if aap.slugify_pseudonym(eff_did) in ("samwise-gamgee", "samwise-gamgi", "samwise"):
        eff_did = "did:anchor:samwise-gamgee"

    p_uid = str(project_uid or aap.slugify_pseudonym(cpath.name))
    now_iso = _utc_now_iso()

    baton: dict[str, Any] = {
        "schema": BATON_SCHEMA,
        "project_uid": p_uid,
        "lead_did": eff_did,
        "lead_pseudonym": canon_pseudo,
        "baton_epoch": 1,
        "updated_at": now_iso,
        "history": [
            {
                "epoch": 1,
                "from_did": None,
                "to_did": eff_did,
                "to_pseudonym": canon_pseudo,
                "at": now_iso,
            }
        ],
    }
    baton["signature"] = aap.sign_payload(baton, did=eff_did)
    bf.write_text(json.dumps(baton, indent=2) + "\n", encoding="utf-8")
    return baton


def transfer_lead_baton(
    cdir: str | Path,
    from_did: str,
    to_did: str,
    to_pseudonym: str = "",
) -> dict[str, Any]:
    """Transfer the Single-Leader Cockpit Baton with monotonic epoch increment & signature verification."""
    cpath = Path(cdir)
    baton = init_or_get_baton(cpath)

    cur_lead = str(baton.get("lead_did") or "")
    from_resolved = aap.did_from_pseudonym(from_did)
    if cur_lead != from_did and cur_lead != from_resolved:
        return {
            "ok": False,
            "error": "not_current_baton_holder",
            "current_lead_did": cur_lead,
            "attempted_from_did": from_did,
        }

    if not aap.verify_signature(baton, str(baton.get("signature") or ""), did=cur_lead):
        return {"ok": False, "error": "current_baton_signature_invalid"}

    target_pseudo_raw = str(to_pseudonym or to_did).strip()
    if aap.slugify_pseudonym(target_pseudo_raw) in ("samwise-gamgee", "samwise-gamgi", "samwise"):
        target_pseudo = aap.PSEUDONYM_DEFAULT
        target_did = "did:anchor:samwise-gamgee"
    else:
        target_pseudo = target_pseudo_raw if not target_pseudo_raw.startswith("did:anchor:") else target_pseudo_raw[len("did:anchor:"):].capitalize()
        target_did = aap.did_from_pseudonym(to_did or target_pseudo)

    new_epoch = int(baton.get("baton_epoch") or 1) + 1
    now_iso = _utc_now_iso()
    history = list(baton.get("history") or [])
    history.append({
        "epoch": new_epoch,
        "from_did": cur_lead,
        "to_did": target_did,
        "to_pseudonym": target_pseudo,
        "at": now_iso,
    })

    updated: dict[str, Any] = {
        "schema": BATON_SCHEMA,
        "project_uid": baton.get("project_uid") or aap.slugify_pseudonym(cpath.name),
        "lead_did": target_did,
        "lead_pseudonym": target_pseudo,
        "previous_lead_did": cur_lead,
        "baton_epoch": new_epoch,
        "updated_at": now_iso,
        "history": history,
    }
    updated["signature"] = aap.sign_payload(updated, did=target_did)
    _baton_file(cpath).write_text(json.dumps(updated, indent=2) + "\n", encoding="utf-8")

    ht2 = check_human_escalation_triggers(
        "HT-2",
        {
            "project_uid": updated["project_uid"],
            "from_did": cur_lead,
            "to_did": target_did,
            "to_pseudonym": target_pseudo,
            "baton_epoch": new_epoch,
        },
    )
    return {
        "ok": True,
        "baton": updated,
        "baton_epoch": new_epoch,
        "human_escalation": ht2,
    }


def validate_roadmap_mutation(
    cdir: str | Path,
    actor_did_or_pseudonym: str,
    mutation_type: str = "step_update",
    step_id: str = "",
) -> dict[str, Any]:
    """Enforce Single-Leader Cockpit Baton rules on ``roadmap.json`` mutations.

    - Structural mutations (``structural``, ``add_step``, ``delete_step``, ``reorder_steps``, ``edit_north_star``)
      are restricted strictly to the current Baton holder (``lead_did``).
    - Step-level updates (``step_update``) are permitted for non-lead collaborators ONLY on steps they hold a lease for.
    """
    cpath = Path(cdir)
    baton = init_or_get_baton(cpath)
    lead_did = str(baton.get("lead_did") or "")
    actor_did = aap.did_from_pseudonym(actor_did_or_pseudonym)
    actor_slug = aap.slugify_pseudonym(actor_did_or_pseudonym)

    is_lead = (actor_did == lead_did) or (aap.slugify_pseudonym(lead_did) == actor_slug)
    structural_types = {"structural", "add_step", "delete_step", "reorder_steps", "edit_north_star"}

    if mutation_type in structural_types:
        if not is_lead:
            return {
                "ok": False,
                "allowed": False,
                "error": "structural_edit_requires_lead_baton",
                "lead_did": lead_did,
                "lead_pseudonym": baton.get("lead_pseudonym"),
                "actor_did": actor_did,
            }
        return {"ok": True, "allowed": True, "role": "lead_baton_holder", "baton_epoch": baton.get("baton_epoch")}

    if is_lead:
        return {"ok": True, "allowed": True, "role": "lead_baton_holder", "baton_epoch": baton.get("baton_epoch")}

    # Non-lead peer updating a specific step: verify step lease ownership
    rm_path = cpath / "roadmap.json"
    if not rm_path.is_file():
        return {"ok": False, "allowed": False, "error": "roadmap_not_found"}

    rm = json.loads(rm_path.read_text(encoding="utf-8"))
    steps = rm.get("steps") or rm.get("roadmap_projection") or []
    target = next((s for s in steps if isinstance(s, dict) and str(s.get("id") or s.get("step_id") or "") == str(step_id)), None)
    if target is None:
        return {"ok": False, "allowed": False, "error": "step_not_found", "step_id": step_id}

    lease = target.get("lease") if isinstance(target.get("lease"), dict) else {}
    holder_ms = str(lease.get("mothership_id") or "")
    holder_did = str(lease.get("holder_did") or "")
    holder_label = str(lease.get("owner_label") or "")

    match_tokens = {
        holder_ms.lower(),
        holder_did.lower(),
        aap.slugify_pseudonym(holder_ms),
        aap.slugify_pseudonym(holder_label),
    }
    if actor_did.lower() in match_tokens or actor_slug in match_tokens or f"{actor_slug}-mothership" in match_tokens:
        return {"ok": True, "allowed": True, "role": "leased_step_contributor", "step_id": step_id}

    return {
        "ok": False,
        "allowed": False,
        "error": "step_not_leased_by_actor",
        "step_id": step_id,
        "actor_did": actor_did,
        "lease_holder": holder_ms or holder_label,
    }


# ── 3-Tier Hybrid Data, Paper & Cloud Execution Classifier ────────────────────────────────────

def classify_resource(
    path_or_descriptor: str | Path | dict[str, Any],
    cdir: str | Path | None = None,
) -> dict[str, Any]:
    """Classify a project file or resource descriptor into Tier 1 (<5MB), Tier 2 (5-500MB), or Tier 3 (>500MB)."""
    base_dir = Path(cdir).resolve() if cdir else None

    if isinstance(path_or_descriptor, (str, Path)):
        p = Path(path_or_descriptor)
        if not p.is_absolute() and base_dir is not None:
            p = base_dir / p
        size_bytes = p.stat().st_size if p.is_file() else 0
        sha = hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() and size_bytes <= TIER1_MAX_BYTES else hashlib.sha256(str(p.name).encode("utf-8")).hexdigest()
        rel_path = p.relative_to(base_dir).as_posix() if (base_dir and p.is_Absolute() if hasattr(p, "is_Absolute") else (base_dir and p.is_absolute() and str(p.resolve()).startswith(str(base_dir)))) else p.name
        desc: dict[str, Any] = {
            "path": rel_path,
            "size_bytes": size_bytes,
            "sha256": sha,
        }
    else:
        desc = dict(path_or_descriptor)
        rel_path = str(desc.get("path") or desc.get("name") or "resource.bin")
        size_bytes = int(desc.get("size_bytes") or 0)
        sha = str(desc.get("sha256") or hashlib.sha256(f"{rel_path}:{size_bytes}".encode("utf-8")).hexdigest())

    is_paper = rel_path.startswith("papers/") or rel_path.endswith((".pdf", ".tex", ".bib", ".md"))

    if size_bytes < TIER1_MAX_BYTES:
        return {
            "schema": TIER1_PAPER_SCHEMA if is_paper else "anchor.resource.tier1.v1",
            "tier": 1,
            "tier_mode": "local_replicated",
            "path": rel_path,
            "size_bytes": size_bytes,
            "doc_sha256": sha,
            "is_active_paper": is_paper,
            "synced_at": _utc_now_iso(),
        }

    if size_bytes <= TIER2_MAX_BYTES:
        return {
            "schema": TIER2_RESOURCE_SCHEMA,
            "tier": 2,
            "tier_mode": "cas_pointer_link",
            "path": rel_path,
            "size_bytes": size_bytes,
            "sha256": sha,
            "cas_relpath": f".anchor/cas/sha256/{sha}",
            "hydrate_on_demand": True,
            "created_at": _utc_now_iso(),
        }

    return {
        "schema": TIER3_WORKSPACE_SCHEMA,
        "tier": 3,
        "tier_mode": "shared_cloud_workspace",
        "path": rel_path,
        "size_bytes": size_bytes,
        "dataset_sha256": sha,
        "workspace_uri": str(desc.get("workspace_uri") or f"s3://gwl-shared-workspaces/{sha[:16]}/{ Path(rel_path).name }"),
        "compute_target": str(desc.get("compute_target") or "gwl-cloud-gpu-runner"),
        "zero_local_copy": True,
        "created_at": _utc_now_iso(),
    }


def hydrate_cas_resource(
    cdir: str | Path,
    descriptor: dict[str, Any],
    content_bytes: bytes,
) -> dict[str, Any]:
    """Hydrate a Tier 2 ``anchor.resource.link.v1`` resource on demand into ``.anchor/cas/sha256/<sha256>``."""
    if not isinstance(descriptor, dict) or descriptor.get("schema") != TIER2_RESOURCE_SCHEMA:
        return {"ok": False, "error": "invalid_tier2_descriptor"}

    expected_sha = str(descriptor.get("sha256") or "")
    actual_sha = hashlib.sha256(content_bytes).hexdigest()
    if expected_sha and actual_sha != expected_sha:
        return {
            "ok": False,
            "error": "cas_sha256_mismatch",
            "expected_sha256": expected_sha,
            "actual_sha256": actual_sha,
        }

    cpath = Path(cdir)
    cas_file = cpath / ".anchor" / "cas" / "sha256" / actual_sha
    cas_file.parent.mkdir(parents=True, exist_ok=True)
    cas_file.write_bytes(content_bytes)
    return {
        "ok": True,
        "sha256": actual_sha,
        "cas_path": str(cas_file),
        "bytes_written": len(content_bytes),
    }


def create_cloud_execution_receipt(
    workspace_descriptor: dict[str, Any],
    executor_pseudonym: str = aap.PSEUDONYM_DEFAULT,
    metrics: dict[str, Any] | None = None,
    command_summary: str = "python train_eval.py",
    exit_code: int = 0,
) -> dict[str, Any]:
    """Create a compact (<50 KB), cryptographically signed ``anchor.cloud.receipt.v1`` for a Tier 3 run."""
    canon_pseudo, _ = aap.canonicalize_pseudonym(executor_pseudonym)
    exec_did = aap.did_from_pseudonym(canon_pseudo)
    receipt: dict[str, Any] = {
        "schema": TIER3_RECEIPT_SCHEMA,
        "workspace_uri": str(workspace_descriptor.get("workspace_uri") or ""),
        "dataset_sha256": str(workspace_descriptor.get("dataset_sha256") or ""),
        "executor_did": exec_did,
        "executor_pseudonym": canon_pseudo,
        "command_summary": str(command_summary),
        "exit_code": int(exit_code),
        "metrics": dict(metrics or {}),
        "completed_at": _utc_now_iso(),
    }
    receipt["signature"] = aap.sign_payload(receipt, did=exec_did)
    encoded = json.dumps(receipt).encode("utf-8")
    if len(encoded) > MAX_CLOUD_RECEIPT_BYTES:
        raise ValueError(f"Cloud execution receipt exceeds 50KB limit ({len(encoded)} bytes)")
    return receipt


def verify_cloud_execution_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
    """Verify size (<50 KB), schema, and HMAC-SHA256 signature of an ``anchor.cloud.receipt.v1``."""
    if not isinstance(receipt, dict) or receipt.get("schema") != TIER3_RECEIPT_SCHEMA:
        return {"ok": False, "valid": False, "error": "invalid_receipt_schema"}
    raw_bytes = json.dumps(receipt).encode("utf-8")
    if len(raw_bytes) > MAX_CLOUD_RECEIPT_BYTES:
        return {"ok": False, "valid": False, "error": "receipt_exceeds_50kb_cap"}
    exec_did = str(receipt.get("executor_did") or "")
    sig = str(receipt.get("signature") or "")
    if not aap.verify_signature(receipt, sig, did=exec_did):
        return {"ok": False, "valid": False, "error": "invalid_receipt_signature"}
    return {
        "ok": True,
        "valid": True,
        "executor_did": exec_did,
        "executor_pseudonym": receipt.get("executor_pseudonym"),
        "size_bytes": len(raw_bytes),
    }


def classify_and_manifest_resources(
    cdir: str | Path,
    extra_descriptors: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Scan ``cdir`` plus optional descriptors and emit ``resource_tiers_manifest.json``."""
    cpath = Path(cdir).resolve()
    cpath.mkdir(parents=True, exist_ok=True)

    tier1: list[dict[str, Any]] = []
    tier2: list[dict[str, Any]] = []
    tier3: list[dict[str, Any]] = []

    skip_parts = {".git", ".anchor", "__pycache__", ".pytest_cache"}
    for fp in sorted(cpath.rglob("*")):
        if not fp.is_file():
            continue
        rel = fp.relative_to(cpath)
        if any(part in skip_parts for part in rel.parts):
            continue
        if fp.name == "resource_tiers_manifest.json":
            continue
        item = classify_resource(fp, cdir=cpath)
        if item["tier"] == 1:
            tier1.append(item)
        elif item["tier"] == 2:
            tier2.append(item)
        else:
            tier3.append(item)

    for desc in extra_descriptors or []:
        if not isinstance(desc, dict):
            continue
        item = classify_resource(desc, cdir=cpath)
        if item["tier"] == 1:
            tier1.append(item)
        elif item["tier"] == 2:
            tier2.append(item)
        else:
            tier3.append(item)

    manifest = {
        "schema": "anchor.resource.tiers_manifest.v1",
        "project_uid": aap.slugify_pseudonym(cpath.name),
        "generated_at": _utc_now_iso(),
        "counts": {
            "tier1_local_replicated": len(tier1),
            "tier2_cas_pointer_links": len(tier2),
            "tier3_shared_cloud_workspaces": len(tier3),
        },
        "tier1_local_replicated": tier1,
        "tier2_cas_links": tier2,
        "tier3_cloud_workspaces": tier3,
    }
    (cpath / "resource_tiers_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


# ── Multi-Agent GitHub Branch Coordinator ─────────────────────────────────────────────────────

def plan_multi_agent_branches(
    project_uid: str,
    collaborator_steps: list[dict[str, Any]],
    trunk_branch: str = "main",
) -> dict[str, Any]:
    """Generate a conflict-free GitHub branch topology for concurrent multi-Anchor collaborators.

    Topology: ``main <- cockpit/<project_uid>/integration <- step/<pseudonym_slug>/<step_id>``.
    """
    p_slug = aap.slugify_pseudonym(project_uid or "shared-cockpit")
    integration_branch = f"cockpit/{p_slug}/integration"
    step_branches: list[dict[str, Any]] = []
    seen_step_ids: dict[str, str] = {}
    conflicts: list[dict[str, Any]] = []

    for item in collaborator_steps:
        if not isinstance(item, dict):
            continue
        raw_pseudo = str(item.get("pseudonym") or item.get("owner") or aap.PSEUDONYM_DEFAULT)
        canon_pseudo, _ = (
            aap.canonicalize_pseudonym(raw_pseudo)
            if aap.slugify_pseudonym(raw_pseudo) in ("samwise-gamgee", "samwise-gamgi", "samwise")
            else (raw_pseudo.strip(), [])
        )
        u_slug = aap.slugify_pseudonym(canon_pseudo)
        step_id = aap.slugify_pseudonym(str(item.get("step_id") or "step-1"))
        branch_name = f"step/{u_slug}/{step_id}"

        if step_id in seen_step_ids and seen_step_ids[step_id] != u_slug:
            conflicts.append({
                "step_id": step_id,
                "existing_owner_slug": seen_step_ids[step_id],
                "conflicting_owner_slug": u_slug,
            })
            continue

        seen_step_ids[step_id] = u_slug
        step_branches.append({
            "step_id": step_id,
            "pseudonym": canon_pseudo,
            "pseudonym_slug": u_slug,
            "did": aap.did_from_pseudonym(canon_pseudo),
            "branch": branch_name,
            "base_branch": integration_branch,
            "merge_target": integration_branch,
        })

    return {
        "ok": len(conflicts) == 0,
        "project_uid": p_slug,
        "trunk_branch": trunk_branch,
        "integration_branch": integration_branch,
        "step_branches": step_branches,
        "conflicts": conflicts,
    }
