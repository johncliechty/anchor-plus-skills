"""Brownfield sidecar-manifest derivation (steward-chamber W5, C1/C2).

Campaigns that PREDATE the W4 manifest convention (no sidecar manifest, no
convention marker — the ``brownfield-w5`` route out of
``chamber_manifest.commission_time_lint``) get their manifest DERIVED from
the existing scaffold/ledger records, so every REAL campaign becomes
openable deterministically:

* **Deterministic + re-runnable** — the derivation is a pure function of the
  campaign's ``roadmap.json`` (roadmap_projection steps, scaffold_proposal
  events): same ledger bytes → byte-identical manifest, run it as many times
  as you like. No wall-clock, no randomness, no model.
* **Chamber-side READS only** — the ledger is read, never written. The only
  writes land in the chamber sidecar (``.anchor/chamber/``) through
  ``chamber_manifest.write_manifest``. Zero spine writes (E8/W4 law).
* **Degraded-rail, never a guess** — a campaign whose ledger cannot yield a
  valid manifest maps to the DRAWN degraded-rail state (the ``degraded rail``
  row of the W1 batched mockup-amendment gate) with a NAMED reason. Nothing
  is fabricated, nothing partial is written.

WHAT IS DERIVED (no invention — provenance table DV-DESC/FS-SKILL rules):

* steps       — from ``roadmap_projection`` (id, name, roadmap status);
* skills      — from each step's ``commissioned_as`` (``skill:job-id`` →
                the skill half; absent → honest ``""``, AG-STEP-NO-SKILL);
* typed edges — sequential, artifact kind from the upstream step's skill
                (``chamber_manifest.ARTIFACT_KIND_BY_SKILL``);
* yields      — the default per-step yield contract pointing at the step's
                run record (``run-record:<id>``), exactly as scaffold-time
                derivation does;
* deliverable — HONEST ``{declared: false}`` always (a brownfield ledger
                never declared a typed deliverable; fabricating one would be
                a guess). The final step's ``done_when`` — else the latest
                ``scaffold_proposal.goal`` — rides along as a DESCRIPTION
                SEED (``derived_seed``), clearly labeled derivation seed,
                never a declared deliverable.

Stdlib only. Validation, schema, atomic writes and the convention marker all
ride ``chamber_manifest`` (one manifest discipline, not a second one).
"""
from __future__ import annotations

import json
from pathlib import Path

import chamber_manifest as cm

SCHEMA_VERSION = cm.SCHEMA_VERSION

#: The drawn degraded-rail state (the failure-state table's W5/W6
#: ``backing-store-unreadable`` / ``dependency-returns-garbage`` answer, and
#: the ``degraded rail`` row of the W1 batched mockup-amendment gate —
#: rendered as drawn, pending John's signature on that batch; NEVER a guess).
DEGRADED_RAIL_STATE = "degraded-rail"
DEGRADED_AMENDMENT_REF = "AG-DEGRADED-RAIL"

ROUTE_DERIVED = "derived"
ROUTE_DEGRADED = DEGRADED_RAIL_STATE
ROUTE_REFUSED = "refused"

#: Named degraded-rail reasons (the mapping is BY NAME — a reader can tell
#: exactly why the rail is degraded; "underivable" is never a shrug).
REASON_ROADMAP_MISSING = "roadmap-missing"
REASON_ROADMAP_UNREADABLE = "roadmap-unreadable"
REASON_NO_STEPS = "no-projection-steps"
REASON_DERIVED_INVALID = "derived-manifest-invalid"

#: Named refusal reasons for the APPLY path (a refusal is not a degraded
#: rail: the campaign may be perfectly derivable, but writing would clobber
#: something this module does not own).
REFUSAL_FOREIGN_MANIFEST = "manifest-not-brownfield-owned"
REFUSAL_MANIFEST_UNREADABLE = "existing-manifest-unreadable"

#: Cap on the derived deliverable description seed (deterministic).
_SEED_CAP = 400


def degraded_rail_state(reason: str, detail: str | None = None) -> dict:
    """The drawn degraded-rail mapping for an underivable campaign."""
    out = {
        "ok": False,
        "route": ROUTE_DEGRADED,
        "state": DEGRADED_RAIL_STATE,
        "amendment_ref": DEGRADED_AMENDMENT_REF,
        "reason": reason,
        "message": "This campaign's ledger cannot yield a sidecar pipeline "
                   "manifest (%s) — the chamber paints the drawn "
                   "degraded-rail state, never a guessed rail. The W5 "
                   "cold-open rebuild affordance re-derives once the ledger "
                   "is readable." % reason,
    }
    if detail:
        out["detail"] = str(detail)[:300]
    return out


# ── Ledger reads (chamber-side, read-only) ───────────────────────────────────

def read_campaign_ledger(folder) -> dict:
    """READ-ONLY load of the campaign's roadmap ledger.

    Returns ``{ok: True, roadmap: <doc>}`` or ``{ok: False, reason}`` with a
    named reason (missing vs unreadable are DISTINCT states — the failure
    table never collapses them).
    """
    p = Path(folder) / "roadmap.json"
    if not p.exists():
        return {"ok": False, "reason": REASON_ROADMAP_MISSING}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("roadmap.json is not a JSON object")
        return {"ok": True, "roadmap": doc}
    except (ValueError, OSError) as exc:
        return {"ok": False, "reason": REASON_ROADMAP_UNREADABLE,
                "detail": str(exc)[:300]}


def _skill_from_commissioned_as(value) -> str:
    """``"researchPrime:ecgberht-job-…"`` → ``"researchPrime"``; an absent or
    malformed value is the honest empty string (AG-STEP-NO-SKILL), never a
    guessed skill."""
    if not isinstance(value, str) or not value.strip():
        return ""
    return value.split(":", 1)[0].strip()


def _projection_steps(roadmap: dict) -> list:
    """The derivable steps: every roadmap_projection entry carrying a
    non-empty id and name, in ledger order (the order IS the pipeline)."""
    steps = []
    raw = roadmap.get("roadmap_projection")
    if not isinstance(raw, list):
        return steps
    for s in raw:
        if not isinstance(s, dict):
            continue
        sid, name = s.get("id"), s.get("name")
        if isinstance(sid, str) and sid.strip() and \
                isinstance(name, str) and name.strip():
            steps.append({
                "id": sid.strip(),
                "name": name.strip(),
                "status": (s.get("status") if isinstance(s.get("status"), str)
                           else None),
                "done_when": (s.get("done_when")
                              if isinstance(s.get("done_when"), str) else None),
                "skill": _skill_from_commissioned_as(s.get("commissioned_as")),
            })
    return steps


def _latest_scaffold_proposal(roadmap: dict) -> dict | None:
    """The LATEST scaffold_proposal event (by ledger order — append-only, so
    last wins deterministically), or None."""
    latest = None
    events = roadmap.get("roadmap_events")
    if isinstance(events, list):
        for e in events:
            if isinstance(e, dict) and e.get("kind") == "scaffold_proposal":
                latest = e
    return latest


def _deliverable_for(steps: list, proposal: dict | None) -> dict:
    """HONEST deliverable: always ``{declared: false}`` (a brownfield ledger
    never declared one). The derivation SEED — final-step done_when, else the
    scaffold goal — rides along labeled as a seed (provenance DV-DESC)."""
    seed_text, seed_source = None, None
    if steps and steps[-1].get("done_when"):
        seed_text, seed_source = steps[-1]["done_when"], "final-step done_when"
    elif proposal and isinstance(proposal.get("goal"), str) \
            and proposal["goal"].strip():
        seed_text, seed_source = proposal["goal"], "scaffold_proposal.goal"
    deliv: dict = {"declared": False}
    if seed_text:
        deliv["derived_seed"] = {"text": seed_text.strip()[:_SEED_CAP],
                                 "source": seed_source}
    return deliv


# ── The derivation (pure; deterministic; never writes) ───────────────────────

def derive_brownfield_manifest(folder) -> dict:
    """Derive the sidecar pipeline manifest from the campaign's existing
    ledger, or map to the drawn degraded-rail state. Pure read — call it a
    thousand times, same answer."""
    ledger = read_campaign_ledger(folder)
    if not ledger.get("ok"):
        return degraded_rail_state(ledger["reason"], ledger.get("detail"))
    roadmap = ledger["roadmap"]

    steps = _projection_steps(roadmap)
    if not steps:
        return degraded_rail_state(REASON_NO_STEPS)

    proposal = _latest_scaffold_proposal(roadmap)
    proposal_id = None
    if proposal and isinstance(proposal.get("proposal_id"), str) \
            and proposal["proposal_id"].strip():
        proposal_id = proposal["proposal_id"].strip()
    if not proposal_id:
        pid = roadmap.get("project_id")
        proposal_id = "brownfield:%s" % pid if isinstance(pid, str) and pid \
            else "brownfield"

    msteps, edges = [], []
    for i, s in enumerate(steps):
        mstep = {
            "id": s["id"],
            "name": s["name"],
            "skill": s["skill"],
            "stages": list(cm.DEFAULT_STEP_STAGES),
            "yield": {
                "shape": "one-line yield for '%s'" % s["name"],
                "report_link": cm.RUN_RECORD_LINK_PREFIX + s["id"],
            },
        }
        if s["status"]:
            mstep["roadmap_status"] = s["status"]
        msteps.append(mstep)
        if i > 0:
            prev = steps[i - 1]
            kind = cm.ARTIFACT_KIND_BY_SKILL.get(
                prev["skill"].lower(), cm.DEFAULT_ARTIFACT_KIND)
            edges.append({"from": prev["id"], "to": s["id"],
                          "artifact_kind": kind})

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "scaffold": {"proposal_id": proposal_id},
        "steps": msteps,
        "edges": edges,
        "deliverable": _deliverable_for(steps, proposal),
        # Provenance: this manifest was DERIVED, not declared — the apply
        # path only ever overwrites manifests carrying this key.
        "brownfield": {
            "derived_by": "chamber_brownfield.py",
            "source": "roadmap_projection",
            "campaign_project_id": (roadmap.get("project_id")
                                    if isinstance(roadmap.get("project_id"),
                                                  str) else None),
        },
    }

    problems = cm.validate_manifest(manifest)
    if problems:
        # A derivation that fails its own schema is UNDERIVABLE — degraded
        # rail with the problems named, never a trimmed-to-fit guess.
        return degraded_rail_state(REASON_DERIVED_INVALID,
                                   "; ".join(problems)[:300])

    return {"ok": True, "route": ROUTE_DERIVED, "manifest": manifest,
            "manifest_hash": cm.compute_manifest_hash(manifest)}


# ── The apply path (writes ONLY the chamber sidecar) ─────────────────────────

def apply_brownfield_derivation(folder) -> dict:
    """Derive and LAND the sidecar manifest for a brownfield campaign.

    Re-runnable: an identical existing manifest is a no-op; a stale
    brownfield-derived manifest (this module's own ``brownfield`` provenance
    key) is refreshed; a manifest this module does NOT own — scaffold-derived
    or hand-authored — is never clobbered (named refusal). Underivable stays
    the drawn degraded-rail state with nothing written."""
    derived = derive_brownfield_manifest(folder)
    if not derived.get("ok"):
        return derived

    manifest = derived["manifest"]
    existing = cm.load_manifest(folder)
    if existing is not None and "_unparseable" in existing:
        return {"ok": False, "route": ROUTE_REFUSED,
                "reason": REFUSAL_MANIFEST_UNREADABLE,
                "message": "an existing sidecar manifest is unreadable — "
                           "refusing to overwrite what cannot be inspected; "
                           "remove or repair it first"}
    if existing is not None and "brownfield" not in existing:
        return {"ok": False, "route": ROUTE_REFUSED,
                "reason": REFUSAL_FOREIGN_MANIFEST,
                "message": "a sidecar manifest this derivation does not own "
                           "already exists (scaffold-derived or "
                           "hand-authored) — brownfield derivation never "
                           "overwrites it"}

    if existing == manifest:
        cm.mark_manifest_convention(folder, who="chamber_brownfield")
        return {"ok": True, "route": ROUTE_DERIVED, "changed": False,
                "manifest_rel": cm.MANIFEST_REL,
                "manifest_hash": derived["manifest_hash"]}

    wrote = cm.write_manifest(folder, manifest)
    if not wrote.get("ok"):
        return degraded_rail_state(REASON_DERIVED_INVALID,
                                   "; ".join(wrote.get("problems") or [])[:300])
    return {"ok": True, "route": ROUTE_DERIVED, "changed": True,
            "manifest_rel": cm.MANIFEST_REL,
            "manifest_hash": wrote["manifest_hash"]}
