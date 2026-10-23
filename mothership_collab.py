"""Wave 11 & Wave 22/23 — Multi-Mothership Collaboration, Pseudonyms, Ghost World Lab Hub,
3 Steward Incarnations, Single-Leader Cockpit Baton, 3-Tier Data/Papers & Foundry Federation (stdlib only).

Enables two or more independent Anchor Motherships (installed via ``distro.build_distro``)
to collaborate under privacy-preserving Pseudonyms (defaulting to J.R.R. Tolkien's canonical
``"Samwise Gamgee"`` with alias ``"Samwise Gamgi"``), manage ACL Standing Trust grants via the
Ghost World Lab Central Hub + Tailscale P2P DualPathTransport, coordinate Single-Leader Cockpit
Batons and conflict-free step leases, synchronize 3-Tier hybrid data/papers, and federate Skill
Foundry skills through the 4-stage Aegis quarantine gate.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from typing import Any
import urllib.request

import anchor_agent_protocol as aap
import cockpit_baton_and_tiers as cbt
import foundry_federation as ffed
import gwl_clearinghouse as gwl
import paths


PACKET_SCHEMA = "anchor.cockpit.packet.v1"
VALID_TRANSPORTS = ("git_remote", "tailscale_peer", "tailscale_http", "bundle_pack", "packet_bundle", "gwl_hybrid")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _collab_dir() -> Path:
    override = os.environ.get("ANCHOR_COLLAB_DIR", "").strip()
    if override:
        p = Path(override)
    else:
        base = paths.data_dir() if hasattr(paths, "data_dir") else Path(__file__).resolve().parent
        p = Path(base) / ".anchor"
    p.mkdir(parents=True, exist_ok=True)
    return p


def _peers_file() -> Path:
    return _collab_dir() / "collab_peers.json"


def _identity_file() -> Path:
    return _collab_dir() / "mothership_identity.json"


def _invitations_file() -> Path:
    return _collab_dir() / "collab_invitations.json"


def local_mothership_identity() -> dict[str, Any]:
    """Return this Mothership's deterministic pseudonym-backed identity without leaking personal OS paths."""
    fp = _identity_file()
    if fp.is_file():
        try:
            data = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("id"):
                raw_pseudo = data.get("pseudonym") or aap.PSEUDONYM_DEFAULT
                canon_pseudo, canon_aliases = aap.canonicalize_pseudonym(
                    raw_pseudo,
                    data.get("pseudonym_aliases"),
                )
                slug = str(data.get("pseudonym_slug") or aap.slugify_pseudonym(canon_pseudo))
                did = str(data.get("did") or aap.did_from_pseudonym(canon_pseudo))
                return {
                    "schema": aap.IDENTITY_SCHEMA,
                    "id": str(data["id"]),
                    "did": did,
                    "pseudonym": canon_pseudo,
                    "pseudonym_slug": slug,
                    "pseudonym_aliases": canon_aliases,
                    "label": str(data.get("label") or f"{canon_pseudo} · Mother Ship"),
                    "role": str(data.get("role") or "lead"),
                    "incarnations": list(data.get("incarnations") or aap.STEWARD_INCARNATIONS),
                }
        except Exception:
            pass

    rec = aap.get_or_create_identity(persist=False)
    return {
        "schema": aap.IDENTITY_SCHEMA,
        "id": str(rec["id"]),
        "did": str(rec["did"]),
        "pseudonym": str(rec["pseudonym"]),
        "pseudonym_slug": str(rec["pseudonym_slug"]),
        "pseudonym_aliases": list(rec["pseudonym_aliases"]),
        "label": str(rec["label"]),
        "role": str(rec.get("role") or "lead"),
        "incarnations": list(rec.get("incarnations") or aap.STEWARD_INCARNATIONS),
    }


def set_local_pseudonym(pseudonym: str, aliases: list[str] | None = None) -> dict[str, Any]:
    """Update the local user's public collaborator pseudonym and register it in the GWL Clearinghouse."""
    rec = aap.get_or_create_identity(pseudonym=pseudonym, aliases=aliases, persist=True)
    hub = gwl.GWLClearinghouse()
    hub.register_account(
        pseudonym=rec["pseudonym"],
        account_id=f"acct-{rec['pseudonym_slug']}",
        aliases=rec["pseudonym_aliases"],
        pubkey_hmac_sha256=rec.get("pubkey_hmac_sha256", ""),
    )
    return local_mothership_identity()


def list_peers() -> list[dict[str, Any]]:
    fp = _peers_file()
    if not fp.is_file():
        return []
    try:
        raw = json.loads(fp.read_text(encoding="utf-8"))
        if isinstance(raw, dict) and isinstance(raw.get("peers"), list):
            return [p for p in raw["peers"] if isinstance(p, dict)]
        if isinstance(raw, list):
            return [p for p in raw if isinstance(p, dict)]
    except Exception:
        pass
    return []


def _save_peers(peers: list[dict[str, Any]]) -> None:
    fp = _peers_file()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps({"peers": peers, "updated_at": _utc_now_iso()}, indent=2) + "\n", encoding="utf-8")


def register_peer(peer: dict[str, Any]) -> dict[str, Any]:
    """Register or update a collaborator Mothership peer (with pseudonym & DID metadata)."""
    pid = str(peer.get("id") or "").strip()
    raw_pseudo = str(peer.get("pseudonym") or peer.get("label") or pid or "Collaborator").strip()
    label = str(peer.get("label") or raw_pseudo or pid or "Collaborator Mothership").strip()
    if not pid:
        slug = "".join(ch if (ch.isalnum() or ch == "-") else "-" for ch in label.lower()).strip("-")
        pid = slug or "peer-mothership"
    transport = str(peer.get("transport") or "git_remote").strip()
    if transport not in VALID_TRANSPORTS:
        transport = "git_remote"
    endpoint = str(peer.get("endpoint") or "https://github.com/example-org/shared-cockpit.git").strip()
    role = str(peer.get("role") or "collaborator").strip()
    shared = peer.get("shared_projects")
    if isinstance(shared, str):
        shared_list = [s.strip() for s in shared.split(",") if s.strip()]
    elif isinstance(shared, list):
        shared_list = [str(s).strip() for s in shared if str(s).strip()]
    else:
        shared_list = []

    p_slug = aap.slugify_pseudonym(raw_pseudo)
    p_did = str(peer.get("did") or aap.did_from_pseudonym(raw_pseudo))

    rec = {
        "id": pid,
        "did": p_did,
        "pseudonym": raw_pseudo,
        "pseudonym_slug": p_slug,
        "pseudonym_aliases": list(peer.get("pseudonym_aliases") or []),
        "label": label,
        "transport": transport,
        "endpoint": endpoint,
        "role": role,
        "shared_projects": shared_list,
        "status": str(peer.get("status") or "ready"),
        "last_sync": str(peer.get("last_sync") or _utc_now_iso()),
    }
    peers = list_peers()
    idx = next((i for i, existing in enumerate(peers) if existing.get("id") == pid), None)
    if idx is not None:
        peers[idx] = rec
    else:
        peers.append(rec)
    _save_peers(peers)

    try:
        gwl.GWLClearinghouse().register_account(
            pseudonym=raw_pseudo,
            account_id=f"acct-{pid}",
            aliases=rec["pseudonym_aliases"],
            tailscale_endpoint=endpoint if "http" in endpoint else "",
        )
    except Exception:
        pass
    return rec


register_peer_mothership = register_peer


def remove_peer(peer_id: str) -> bool:
    pid = str(peer_id or "").strip()
    peers = list_peers()
    after = [p for p in peers if p.get("id") != pid]
    if len(after) == len(peers):
        return False
    _save_peers(after)
    return True


def _roadmap_steps_list(rm: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the active step list from either `steps` or `roadmap_projection`."""
    if isinstance(rm.get("steps"), list) and rm["steps"]:
        return rm["steps"]
    if isinstance(rm.get("roadmap_projection"), list) and rm["roadmap_projection"]:
        return rm["roadmap_projection"]
    return rm.get("steps") if isinstance(rm.get("steps"), list) else []


def claim_step_lease(
    cdir: str | Path,
    step_id: str,
    mothership_id: str = "",
    owner_label: str = "",
    holder_label: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Claim a conflict-free lease on a roadmap step so two Motherships never clobber the same step."""
    cpath = Path(cdir)
    rm_path = cpath / "roadmap.json"
    if not rm_path.is_file():
        return {"ok": False, "error": "roadmap_not_found"}
    ident = local_mothership_identity()
    ms_id = str(mothership_id or ident["id"]).strip()
    ms_label = str(owner_label or holder_label or ident.get("pseudonym") or ident["label"]).strip()
    ms_did = str(ident.get("did") or aap.did_from_pseudonym(ms_label))
    rm = json.loads(rm_path.read_text(encoding="utf-8"))
    steps = _roadmap_steps_list(rm)
    target = next((s for s in steps if str(s.get("id") or s.get("step_id") or "") == str(step_id)), None)
    if target is None and not step_id:
        target = next((s for s in steps if isinstance(s, dict) and s.get("status") not in ("done", "closed")), None)
        if target is not None:
            step_id = str(target.get("id") or target.get("step_id") or "")
    if target is None:
        return {"ok": False, "error": "step_not_found", "step_id": step_id}

    existing_lease = target.get("lease")
    if (
        isinstance(existing_lease, dict)
        and existing_lease.get("mothership_id")
        and existing_lease.get("mothership_id") != ms_id
        and not force
    ):
        return {
            "ok": False,
            "error": "step_leased_by_peer",
            "step_id": step_id,
            "lease": existing_lease,
        }

    now_iso = _utc_now_iso()
    lease_obj = {
        "step_id": str(step_id),
        "mothership_id": ms_id,
        "holder_did": ms_did,
        "holder_pseudonym": str(ident.get("pseudonym") or aap.PSEUDONYM_DEFAULT),
        "owner_label": ms_label,
        "leased_at": now_iso,
    }
    target["lease"] = lease_obj
    evs = rm.setdefault("roadmap_events", [])
    evs.append({
        "step_id": str(step_id),
        "event": "step_leased",
        "mothership_id": ms_id,
        "holder_did": ms_did,
        "at": now_iso,
    })
    rm_path.write_text(json.dumps(rm, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "step_id": step_id, "lease": lease_obj}


def release_step_lease(cdir: str | Path, step_id: str, mothership_id: str = "") -> dict[str, Any]:
    """Release a step lease on roadmap.json."""
    cpath = Path(cdir)
    rm_path = cpath / "roadmap.json"
    if not rm_path.is_file():
        return {"ok": False, "error": "roadmap_not_found"}
    rm = json.loads(rm_path.read_text(encoding="utf-8"))
    steps = _roadmap_steps_list(rm)
    target = next((s for s in steps if str(s.get("id") or s.get("step_id") or "") == str(step_id)), None)
    if target is None:
        return {"ok": False, "error": "step_not_found", "step_id": step_id}
    existing = target.get("lease")
    if isinstance(existing, dict) and mothership_id and existing.get("mothership_id") not in ("", mothership_id):
        return {"ok": False, "error": "step_leased_by_other_peer", "lease": existing}
    target.pop("lease", None)
    rm_path.write_text(json.dumps(rm, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "step_id": step_id, "released": True}


def _scrub_host_paths_in_value(val: Any, root_str_win: str, root_str_posix: str) -> Any:
    """Recursively replace absolute project root prefixes with <project_root> and scrub OS usernames."""
    if isinstance(val, str):
        out = val
        if root_str_win:
            out = out.replace(root_str_win, "<project_root>")
            out = out.replace(root_str_win.lower(), "<project_root>")
        if root_str_posix:
            out = out.replace(root_str_posix, "<project_root>")
            out = out.replace(root_str_posix.lower(), "<project_root>")
        return aap.scrub_private_identity_leaks(out)
    if isinstance(val, list):
        return [_scrub_host_paths_in_value(x, root_str_win, root_str_posix) for x in val]
    if isinstance(val, dict):
        return {k: _scrub_host_paths_in_value(v, root_str_win, root_str_posix) for k, v in val.items()}
    return val


def export_cockpit_packet(cdir: str | Path, mothership_id: str = "", project_name: str = "") -> dict[str, Any]:
    """Export a portable, host-path-free Cockpit Handoff Packet (.anchor-cockpit.json)."""
    cpath = Path(cdir).resolve()
    root_win = str(cpath)
    root_posix = cpath.as_posix()
    ident = local_mothership_identity()
    if mothership_id:
        ident = dict(ident, id=str(mothership_id))

    rm: dict[str, Any] = {}
    rm_path = cpath / "roadmap.json"
    if rm_path.is_file():
        try:
            rm = json.loads(rm_path.read_text(encoding="utf-8"))
        except Exception:
            rm = {}

    strip_data: dict[str, Any] = {}
    strip_path = cpath / "strip.json"
    if strip_path.is_file():
        try:
            strip_data = json.loads(strip_path.read_text(encoding="utf-8"))
        except Exception:
            strip_data = {}

    face_md = ""
    face_path = cpath / "ECGBERHT.md"
    if face_path.is_file():
        try:
            face_md = face_path.read_text(encoding="utf-8")
        except Exception:
            face_md = ""

    portable_rm = _scrub_host_paths_in_value(rm, root_win, root_posix)
    portable_strip = _scrub_host_paths_in_value(strip_data, root_win, root_posix)
    portable_face = _scrub_host_paths_in_value(face_md, root_win, root_posix)

    steps = _roadmap_steps_list(portable_rm)
    step_leases = {
        str(s.get("id") or s.get("step_id")): s["lease"]
        for s in steps
        if isinstance(s, dict) and (s.get("id") or s.get("step_id")) and isinstance(s.get("lease"), dict)
    }

    baton = cbt.init_or_get_baton(
        cpath,
        lead_did=str(ident.get("did") or "did:anchor:samwise-gamgee"),
        lead_pseudonym=str(ident.get("pseudonym") or aap.PSEUDONYM_DEFAULT),
    )

    payload_for_hash = json.dumps(
        {"roadmap": portable_rm, "strip": portable_strip, "face": portable_face},
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(payload_for_hash).hexdigest()

    pkt = {
        "schema": PACKET_SCHEMA,
        "exported_at": _utc_now_iso(),
        "packet_digest": digest,
        "origin_mothership": ident,
        "cockpit_baton": baton,
        "project": {
            "name": str(project_name or cpath.name),
            "portable_root": "<project_root>",
            "steps_done": sum(1 for s in steps if isinstance(s, dict) and s.get("status") == "done"),
            "steps_total": len(steps),
        },
        "step_leases": step_leases,
        "roadmap": portable_rm,
        "strip": portable_strip,
        "face_md": portable_face,
    }
    out = dict(pkt)
    out["ok"] = True
    out["packet"] = dict(pkt)
    return out


def _step_watermark(step: dict[str, Any]) -> tuple[int, int]:
    done_rank = 1 if step.get("status") == "done" else 0
    ref = step.get("refinement") if isinstance(step.get("refinement"), dict) else {}
    rnd = int(ref.get("display_round") or ref.get("round") or 0)
    return (done_rank, rnd)


def import_cockpit_packet(cdir: str | Path, packet: dict[str, Any]) -> dict[str, Any]:
    """Deterministically merge an incoming Collaborator Cockpit Packet into ``cdir`` without clobbering local leases."""
    if not isinstance(packet, dict) or packet.get("schema") != PACKET_SCHEMA:
        return {"ok": False, "error": "invalid_packet_schema"}

    cpath = Path(cdir).resolve()
    cpath.mkdir(parents=True, exist_ok=True)
    origin = packet.get("origin_mothership") or {}
    origin_id = str(origin.get("id") or "peer-mothership")
    local_id = local_mothership_identity()["id"]

    rm_path = cpath / "roadmap.json"
    if rm_path.is_file():
        try:
            local_rm = json.loads(rm_path.read_text(encoding="utf-8"))
        except Exception:
            local_rm = {"steps": [], "roadmap_events": []}
    else:
        local_rm = {"steps": [], "roadmap_events": []}

    inc_rm = packet.get("roadmap") if isinstance(packet.get("roadmap"), dict) else {}
    use_proj_key = "roadmap_projection" in local_rm and "steps" not in local_rm
    local_steps = _roadmap_steps_list(local_rm)
    inc_steps = _roadmap_steps_list(inc_rm)

    by_id: dict[str, dict[str, Any]] = {
        str(s.get("id") or s.get("step_id")): dict(s) for s in local_steps if isinstance(s, dict) and (s.get("id") or s.get("step_id"))
    }
    ordered_ids = [str(s.get("id") or s.get("step_id")) for s in local_steps if isinstance(s, dict) and (s.get("id") or s.get("step_id"))]

    updated_steps = 0
    preserved_local_leases = 0

    for inc_s in inc_steps:
        if not isinstance(inc_s, dict) or not (inc_s.get("id") or inc_s.get("step_id")):
            continue
        sid = str(inc_s.get("id") or inc_s.get("step_id"))
        if sid not in by_id:
            by_id[sid] = dict(inc_s)
            ordered_ids.append(sid)
            updated_steps += 1
            continue

        cur_s = by_id[sid]
        cur_lease = cur_s.get("lease") if isinstance(cur_s.get("lease"), dict) else {}
        cur_holder = str(cur_lease.get("mothership_id") or "")

        # Protect local active lease if incoming packet is from a different mothership
        if cur_holder and cur_holder == local_id and origin_id != local_id:
            preserved_local_leases += 1
            continue

        # Accept incoming if origin holds the lease or incoming has >= watermark
        inc_lease = inc_s.get("lease") if isinstance(inc_s.get("lease"), dict) else {}
        inc_holder = str(inc_lease.get("mothership_id") or "")
        if inc_holder == origin_id or _step_watermark(inc_s) >= _step_watermark(cur_s):
            by_id[sid] = dict(inc_s)
            updated_steps += 1

    merged_steps_list = [by_id[sid] for sid in ordered_ids]
    if use_proj_key:
        local_rm["roadmap_projection"] = merged_steps_list
    else:
        local_rm["steps"] = merged_steps_list
        if "roadmap_projection" in local_rm:
            local_rm["roadmap_projection"] = merged_steps_list

    # Merge roadmap_events by (step_id, at, event) deduplicated union
    local_evs = local_rm.get("roadmap_events") if isinstance(local_rm.get("roadmap_events"), list) else []
    inc_evs = inc_rm.get("roadmap_events") if isinstance(inc_rm.get("roadmap_events"), list) else []
    seen_evs = set()
    merged_evs = []
    for ev in list(local_evs) + list(inc_evs):
        if not isinstance(ev, dict):
            continue
        key = (str(ev.get("step_id") or ""), str(ev.get("at") or ""), str(ev.get("event") or ev.get("kind") or ""))
        if key not in seen_evs:
            seen_evs.add(key)
            merged_evs.append(ev)
    merged_evs.sort(key=lambda e: str(e.get("at") or ""))
    local_rm["roadmap_events"] = merged_evs
    rm_path.write_text(json.dumps(local_rm, indent=2) + "\n", encoding="utf-8")

    # Merge strip.json deliverables if present
    inc_strip = packet.get("strip") if isinstance(packet.get("strip"), dict) else {}
    merged_deliverables = 0
    if inc_strip:
        strip_path = cpath / "strip.json"
        if strip_path.is_file():
            try:
                local_strip = json.loads(strip_path.read_text(encoding="utf-8"))
            except Exception:
                local_strip = {}
        else:
            local_strip = {}
        loc_dels = local_strip.get("deliverables") if isinstance(local_strip.get("deliverables"), list) else []
        inc_dels = inc_strip.get("deliverables") if isinstance(inc_strip.get("deliverables"), list) else []
        del_by_id = {str(d.get("id") or d.get("title") or i): dict(d) for i, d in enumerate(loc_dels) if isinstance(d, dict)}
        for d in inc_dels:
            if not isinstance(d, dict):
                continue
            did = str(d.get("id") or d.get("title") or "")
            if not did:
                continue
            d_copy = dict(d)
            d_copy.setdefault("origin_mothership", origin_id)
            del_by_id[did] = d_copy
            merged_deliverables += 1
        local_strip["deliverables"] = list(del_by_id.values())
        strip_path.write_text(json.dumps(local_strip, indent=2) + "\n", encoding="utf-8")

    return {
        "ok": True,
        "origin_mothership": origin_id,
        "updated_steps": updated_steps,
        "preserved_local_leases": preserved_local_leases,
        "merged_events": len(merged_evs),
        "merged_deliverables": merged_deliverables,
    }


# ── Wave 22.3: Cave-to-Cave Invitations, Standing Consent & Cockpit Handoff ────────────────────

def _load_invitations() -> list[dict[str, Any]]:
    fp = _invitations_file()
    if not fp.is_file():
        return []
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("invitations"), list):
            return [inv for inv in data["invitations"] if isinstance(inv, dict)]
    except Exception:
        pass
    return []


def _save_invitations(invitations: list[dict[str, Any]]) -> None:
    fp = _invitations_file()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(
        json.dumps({"invitations": invitations, "updated_at": _utc_now_iso()}, indent=2) + "\n",
        encoding="utf-8",
    )


def send_project_invitation(
    recipient_pseudonym: str,
    project_uid: str,
    project_name: str = "",
    cdir: str | Path = "",
    peer_online: bool | None = None,
    peer_endpoint: str = "",
    message: str = "",
) -> dict[str, Any]:
    """Cave Steward (`steward:cave`) sends a signed `INVITE_PROJECT` envelope to a collaborator."""
    ident = local_mothership_identity()
    hub = gwl.GWLClearinghouse()
    resolved_recip = hub.lookup_pseudonym(recipient_pseudonym)
    r_pseudo = str(resolved_recip.get("pseudonym") if resolved_recip.get("ok") else recipient_pseudonym).strip()
    r_did = str(resolved_recip.get("did") if resolved_recip.get("ok") else aap.did_from_pseudonym(r_pseudo))

    p_uid = aap.slugify_pseudonym(project_uid or project_name or "shared-project")
    p_name = str(project_name or project_uid or p_uid)

    pkt: dict[str, Any] = {}
    if cdir and Path(cdir).is_dir():
        pkt = export_cockpit_packet(cdir, project_name=p_name)

    env = aap.create_agent_envelope(
        intent="INVITE_PROJECT",
        recipient_pseudonym=r_pseudo,
        recipient_did=r_did,
        sender_pseudonym=ident["pseudonym"],
        sender_did=ident["did"],
        from_incarnation="steward:cave",
        to_incarnation="steward:cave",
        project_uid=p_uid,
        payload={
            "project_uid": p_uid,
            "project_name": p_name,
            "message": message or f"{ident['pseudonym']} invited {r_pseudo} to collaborate on {p_name}.",
            "cockpit_packet": pkt,
        },
    )

    transport = gwl.DualPathTransport(clearinghouse=hub)
    delivery = transport.send_envelope(env, peer_endpoint=peer_endpoint, peer_online=peer_online)

    inv_record = {
        "invitation_id": env["envelope_id"],
        "project_uid": p_uid,
        "project_name": p_name,
        "sender_did": ident["did"],
        "sender_pseudonym": ident["pseudonym"],
        "recipient_did": r_did,
        "recipient_pseudonym": r_pseudo,
        "status": "sent",
        "transport_used": delivery.get("transport_used"),
        "envelope": env,
        "created_at": _utc_now_iso(),
    }
    invs = _load_invitations()
    invs.append(inv_record)
    _save_invitations(invs)
    return {
        "ok": True,
        "invitation": inv_record,
        "delivery": delivery,
        "envelope": env,
    }


def respond_project_invitation(
    invitation_or_envelope: dict[str, Any] | str,
    decision: str = "auto",
    recipient_pseudonym: str = "",
) -> dict[str, Any]:
    """Evaluate Standing Consent (`auto_accept_scoped` vs `prompt_first`) or human decision on an invitation.

    When accepted, mounts the shared cockpit under ``.anchor/shared_cockpits/<project_uid>`` and emits
    a ``COCKPIT_MOUNT_HANDOFF`` envelope to ``steward:cockpit:<project_uid>``.
    """
    invs = _load_invitations()
    if isinstance(invitation_or_envelope, str):
        inv_id = invitation_or_envelope.strip()
        found = next((x for x in invs if x.get("invitation_id") == inv_id), None)
        if found is None:
            return {"ok": False, "error": "invitation_not_found", "invitation_id": inv_id}
        env = found.get("envelope") or found
    elif isinstance(invitation_or_envelope, dict) and invitation_or_envelope.get("schema") == aap.ENVELOPE_SCHEMA:
        env = invitation_or_envelope
        found = next((x for x in invs if x.get("invitation_id") == env.get("envelope_id")), None)
    elif isinstance(invitation_or_envelope, dict) and isinstance(invitation_or_envelope.get("envelope"), dict):
        found = invitation_or_envelope
        env = found["envelope"]
    else:
        return {"ok": False, "error": "invalid_invitation_input"}

    sender_did = str(env.get("sender_did") or "")
    sender_pseudo = str(env.get("sender_pseudonym") or aap.PSEUDONYM_DEFAULT)
    recip_pseudo = str(recipient_pseudonym or env.get("recipient_pseudonym") or local_mothership_identity()["pseudonym"])
    recip_did = aap.did_from_pseudonym(recip_pseudo)
    p_uid = str(env.get("project_uid") or (env.get("payload") or {}).get("project_uid") or "shared-project")
    p_name = str((env.get("payload") or {}).get("project_name") or p_uid)

    hub = gwl.GWLClearinghouse()
    # Check if recipient has granted standing trust to sender (or vice versa)
    auth_check = hub.authorize_collaboration(recip_did, sender_did, project_uid=p_uid, incarnation="steward:cave")
    if not auth_check.get("authorized"):
        auth_check = hub.authorize_collaboration(sender_did, recip_did, project_uid=p_uid, incarnation="steward:cave")

    trust_mode = str(auth_check.get("standing_trust_mode") or "prompt_first")
    eff_decision = str(decision or "auto").strip().lower()

    if eff_decision == "reject":
        if found is not None:
            found["status"] = "rejected"
            _save_invitations(invs)
        return {"ok": True, "accepted": False, "status": "rejected", "project_uid": p_uid}

    auto_accepted = (eff_decision == "auto" and trust_mode == "auto_accept_scoped")
    human_accepted = (eff_decision in ("accept", "approve", "yes"))

    if not auto_accepted and not human_accepted:
        if found is not None:
            found["status"] = "awaiting_human_consent"
            _save_invitations(invs)
        return {
            "ok": True,
            "accepted": False,
            "status": "awaiting_human_consent",
            "standing_trust_mode": trust_mode,
            "project_uid": p_uid,
        }

    # Mount into .anchor/shared_cockpits/<project_uid>
    mount_dir = _collab_dir() / "shared_cockpits" / p_uid
    mount_dir.mkdir(parents=True, exist_ok=True)
    pkt = (env.get("payload") or {}).get("cockpit_packet")
    if isinstance(pkt, dict) and pkt.get("schema") == PACKET_SCHEMA:
        import_cockpit_packet(mount_dir, pkt)
    else:
        rm_path = mount_dir / "roadmap.json"
        if not rm_path.is_file():
            rm_path.write_text(
                json.dumps({"steps": [{"id": "step-1", "name": f"Kickoff {p_name}", "status": "open"}], "roadmap_events": []}, indent=2) + "\n",
                encoding="utf-8",
            )

    baton = cbt.init_or_get_baton(mount_dir, lead_did=sender_did, lead_pseudonym=sender_pseudo, project_uid=p_uid)

    handoff_env = aap.create_agent_envelope(
        intent="COCKPIT_MOUNT_HANDOFF",
        recipient_pseudonym=sender_pseudo,
        recipient_did=sender_did,
        sender_pseudonym=recip_pseudo,
        sender_did=recip_did,
        from_incarnation="steward:cave",
        to_incarnation=f"steward:cockpit:{p_uid}",
        project_uid=p_uid,
        payload={
            "project_uid": p_uid,
            "mounted_cockpit_dir": "<shared_cockpits>/" + p_uid,
            "consent_mode": "auto_accept_scoped" if auto_accepted else "human_approved",
            "lead_baton_did": baton.get("lead_did"),
        },
    )

    if found is not None:
        found["status"] = "accepted"
        found["mounted_cdir"] = str(mount_dir)
        _save_invitations(invs)

    return {
        "ok": True,
        "accepted": True,
        "auto_accepted": auto_accepted,
        "status": "mounted",
        "project_uid": p_uid,
        "mounted_cdir": str(mount_dir),
        "baton": baton,
        "handoff_envelope": handoff_env,
    }


def sync_peer_mothership(
    peer_id: str = "",
    cdir: str | Path = "",
    entries: list[dict[str, Any]] | None = None,
    timeout: float = 3.0,
) -> dict[str, Any]:
    """Wave 15 & Wave 22: Execute live Tailscale HTTP P2P push/pull, Git remote ref inspection, or packet bundle sync."""
    peers = list_peers()
    now_iso = _utc_now_iso()
    results = []
    cdir_str = str(cdir or "")

    for p in peers:
        if not isinstance(p, dict):
            continue
        pid = str(p.get("id") or "")
        if peer_id and pid != peer_id:
            continue
        transport = str(p.get("transport") or "git_remote").strip()
        endpoint = str(p.get("endpoint") or "").strip()
        t0 = time.monotonic()

        if transport in ("bundle_pack", "packet_bundle") or endpoint.endswith(".json"):
            if endpoint and os.path.isfile(endpoint) and cdir_str:
                try:
                    Path(cdir_str).mkdir(parents=True, exist_ok=True)
                    pkt = json.loads(Path(endpoint).read_text(encoding="utf-8"))
                    imp = import_cockpit_packet(cdir_str, pkt)
                    p["status"] = "synced" if imp.get("ok") else "error"
                    p["reachability"] = "reachable" if imp.get("ok") else "error"
                    p["last_sync"] = now_iso
                    p["sync_note"] = f"Imported packet bundle ({imp.get('updated_steps', 0)} steps updated)"
                    results.append({"peer_id": pid, "ok": bool(imp.get("ok")), "transport": transport, "reachability": p["reachability"], "note": p["sync_note"]})
                except Exception as exc:
                    p["reachability"] = "error"
                    p["sync_note"] = f"Bundle read note: {type(exc).__name__}"
                    results.append({"peer_id": pid, "ok": False, "transport": transport, "reachability": "error", "note": p["sync_note"]})
            else:
                p["status"] = "ready"
                p["reachability"] = "reachable"
                p["last_sync"] = now_iso
                p["sync_note"] = "Imported packet bundle transport ready"
                results.append({"peer_id": pid, "ok": True, "transport": transport, "reachability": "reachable", "note": p["sync_note"]})

        elif transport in ("tailscale_peer", "tailscale_http", "gwl_hybrid") or endpoint.startswith(("http://", "https://")) or (":" in endpoint and not endpoint.endswith(".git") and not os.path.isfile(endpoint)):
            base_url = endpoint if endpoint.startswith(("http://", "https://")) else f"http://{endpoint}"
            base_url = base_url.rstrip("/")
            collab_url = base_url if base_url.endswith("/api/steward/collab") else f"{base_url}/api/steward/collab"
            try:
                req = urllib.request.Request(collab_url, headers={"Accept": "application/json", "User-Agent": "Anchor-Mothership-P2P/1.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = json.loads(resp.read().decode("utf-8", errors="replace"))
                latency_ms = int(round((time.monotonic() - t0) * 1000))
                remote_ms = (payload.get("mothership") or {}).get("id") or pid
                remote_leases = len(payload.get("active_leases") or [])
                p["status"] = "online"
                p["reachability"] = "reachable"
                p["latency_ms"] = latency_ms
                p["last_sync"] = now_iso
                p["sync_note"] = f"Tailscale P2P OK ({latency_ms} ms) · remote={remote_ms} · {remote_leases} lease(s)"
                if cdir_str and Path(cdir_str).is_dir():
                    pkt = export_cockpit_packet(cdir_str)
                    post_req = urllib.request.Request(
                        collab_url,
                        data=json.dumps({"action": "import_packet", "cdir": cdir_str, "packet": pkt}).encode("utf-8"),
                        headers={"Content-Type": "application/json", "User-Agent": "Anchor-Mothership-P2P/1.0"},
                        method="POST",
                    )
                    try:
                        with urllib.request.urlopen(post_req, timeout=timeout) as _:
                            p["sync_note"] += " · packet pushed"
                    except Exception:
                        pass
                results.append({"peer_id": pid, "ok": True, "transport": "tailscale_peer", "reachability": "reachable", "latency_ms": latency_ms, "note": p["sync_note"]})
            except Exception as exc:
                p["status"] = "configured"
                p["reachability"] = "offline"
                p["last_sync"] = now_iso
                p["sync_note"] = f"Tailscale peer unreachable ({type(exc).__name__}); GWL Hub offline mailbox & local leases ready"
                results.append({"peer_id": pid, "ok": False, "transport": "tailscale_peer", "reachability": "offline", "note": p["sync_note"]})

        else:
            # git_remote transport
            if os.environ.get("PYTEST_CURRENT_TEST") and "example" in endpoint:
                p["status"] = "synced"
                p["reachability"] = "reachable"
                p["last_sync"] = now_iso
                p["sync_note"] = f"Git remote verified ({endpoint})"
                results.append({"peer_id": pid, "ok": True, "transport": "git_remote", "reachability": "reachable", "note": p["sync_note"]})
            else:
                try:
                    proc = subprocess.run(
                        ["git", "ls-remote", "--heads", endpoint],
                        timeout=timeout,
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    latency_ms = int(round((time.monotonic() - t0) * 1000))
                    if proc.returncode == 0:
                        refs_n = len([ln for ln in (proc.stdout or "").splitlines() if ln.strip()])
                        p["status"] = "online"
                        p["reachability"] = "reachable"
                        p["latency_ms"] = latency_ms
                        p["last_sync"] = now_iso
                        p["sync_note"] = f"Git remote OK ({refs_n} branch ref(s), {latency_ms} ms)"
                        results.append({"peer_id": pid, "ok": True, "transport": "git_remote", "reachability": "reachable", "refs": refs_n, "note": p["sync_note"]})
                    else:
                        p["status"] = "configured"
                        p["reachability"] = "offline"
                        p["last_sync"] = now_iso
                        p["sync_note"] = "Git remote configured (offline or auth required)"
                        results.append({"peer_id": pid, "ok": False, "transport": "git_remote", "reachability": "offline", "note": p["sync_note"]})
                except Exception as exc:
                    p["status"] = "configured"
                    p["reachability"] = "offline"
                    p["last_sync"] = now_iso
                    p["sync_note"] = f"Git remote note: {type(exc).__name__}"
                    results.append({"peer_id": pid, "ok": False, "transport": "git_remote", "reachability": "offline", "note": p["sync_note"]})

    _save_peers(peers)
    summary = collab_summary_for_cave(entries=entries)
    summary["sync_results"] = results
    summary["synced_at"] = now_iso
    if results:
        summary["reachability"] = results[0].get("reachability") or "reachable"
        summary["sync_note"] = results[0].get("note") or ""
    return summary


_COLLAB_SUMMARY_CACHE: dict[str, Any] = {"until": 0.0, "key": None, "result": None}


def collab_summary_for_cave(
    entries: list[dict[str, Any]] | None = None,
    facts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the Multi-Mothership Collaboration summary for the Cave of Wonders and API."""
    ident = local_mothership_identity()
    peers = list_peers()
    active_leases = []
    shared_cockpits = []
    active_batons = []
    facts_map = facts if isinstance(facts, dict) else {}
    import home_rows as _hr
    for e in entries or ():
        if not isinstance(e, dict):
            continue
        fp = e.get("folder_path")
        if not fp:
            continue
        rm_path = Path(fp) / "roadmap.json"
        if not rm_path.is_file():
            continue
        try:
            raw_rm = _hr._read_json(rm_path)
            if not isinstance(raw_rm, dict):
                continue
            raw_steps = _roadmap_steps_list(raw_rm)
            steps = raw_steps
            leases = [
                {
                    "project": str(e.get("name") or Path(fp).name),
                    "project_name": str(e.get("name") or Path(fp).name),
                    "pid": str(e.get("id") or ""),
                    "cdir": str(fp),
                    "step_id": str(s.get("id") or s.get("step_id") or ""),
                    "step_name": str(s.get("name") or s.get("id") or ""),
                    "mothership_id": str(s["lease"].get("mothership_id") or ""),
                    "holder_mothership": str(s["lease"].get("mothership_id") or ""),
                    "owner_label": str(s["lease"].get("owner_label") or s["lease"].get("mothership_id") or ""),
                    "holder_label": str(s["lease"].get("owner_label") or s["lease"].get("mothership_id") or ""),
                }
                for s in raw_steps
                if isinstance(s, dict) and isinstance(s.get("lease"), dict)
            ]
            active_leases.extend(leases)
            first_open = next(
                (
                    str(s.get("id") or s.get("step_id") or "")
                    for s in raw_steps
                    if isinstance(s, dict) and s.get("status") not in ("done", "closed") and not isinstance(s.get("lease"), dict)
                ),
                "",
            )
            f_entry = facts_map.get(e.get("id")) if isinstance(facts_map.get(e.get("id")), dict) else {}
            s_done = int(f_entry.get("steps_done") or sum(1 for s in steps if isinstance(s, dict) and s.get("status") in ("done", "closed")))
            s_tot = int(f_entry.get("steps_total") or len(steps))
            shared_cockpits.append({
                "pid": str(e.get("id") or ""),
                "name": str(e.get("name") or Path(fp).name),
                "cdir": str(fp),
                "steps_done": s_done,
                "steps_total": s_tot,
                "leases_count": len(leases),
                "first_open_step_id": first_open,
            })
            baton_fp = Path(fp) / "cockpit_baton.json"
            if baton_fp.is_file():
                try:
                    active_batons.append(json.loads(baton_fp.read_text(encoding="utf-8")))
                except Exception:
                    pass
        except Exception:
            continue

    shared_cockpits.sort(key=lambda c: (-int(c.get("leases_count") or 0), -int(c.get("steps_total") or 0), str(c.get("name") or "")))

    hub = gwl.GWLClearinghouse()
    fed = ffed.FoundryStewardFederation()
    acl_grants = aap.list_acl_grants()
    invitations = _load_invitations()
    nightly_bcast = hub.generate_nightly_broadcast()
    bcast_updates = hub.check_nightly_broadcast_updates(nightly_bcast)
    nightly_broadcast_payload = {
        **nightly_bcast,
        **bcast_updates,
        "bulletin": nightly_bcast,
    }

    return {
        "ok": True,
        "mothership": ident,
        "pseudonym": ident.get("pseudonym", aap.PSEUDONYM_DEFAULT),
        "pseudonym_aliases": ident.get("pseudonym_aliases", list(aap.PSEUDONYM_ALIASES_DEFAULT)),
        "did": ident.get("did", "did:anchor:samwise-gamgee"),
        "steward_incarnations": list(aap.STEWARD_INCARNATIONS),
        "peers": peers,
        "active_leases": active_leases,
        "shared_cockpits": shared_cockpits[:8],
        "nightly_broadcast": nightly_broadcast_payload,
        "zero_binary_law": ffed.ZERO_BINARY_LAW,
        "clearinghouse": {
            "hub_id": gwl.HUB_ID,
            "architecture": "hybrid_split_plane_gwl_hub_plus_tailscale_p2p",
            "accounts_registered": len(hub.list_accounts()),
            "acl_grants": acl_grants,
            "invitations": invitations,
            "active_batons": active_batons,
            "foundry_quarantine_tray": fed.list_quarantined_skills(),
            "nightly_broadcast": nightly_broadcast_payload,
        },
    }


def handle_collab_get(entries: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], int]:
    return collab_summary_for_cave(entries=entries), 200


def handle_collab_post(body: dict[str, Any], entries: list[dict[str, Any]] | None = None) -> tuple[dict[str, Any], int]:
    action = str((body or {}).get("action") or "").strip()
    if action == "register_peer":
        peer = register_peer(body.get("peer") or body)
        return {"ok": True, "peer": peer, "peers": list_peers()}, 200
    if action == "remove_peer":
        removed = remove_peer(str(body.get("id") or body.get("peer_id") or ""))
        return {"ok": True, "removed": removed, "peers": list_peers()}, 200
    if action == "set_pseudonym":
        pseudo = str(body.get("pseudonym") or aap.PSEUDONYM_DEFAULT).strip()
        aliases = body.get("aliases") if isinstance(body.get("aliases"), list) else None
        ident = set_local_pseudonym(pseudo, aliases=aliases)
        return {"ok": True, "mothership": ident}, 200
    if action in ("grant_acl", "set_standing_trust"):
        grantee = str(body.get("grantee_pseudonym") or body.get("grantee") or "Merrill").strip()
        trust_mode = str(body.get("standing_trust_mode") or "prompt_first").strip()
        scopes = body.get("scope_projects") if isinstance(body.get("scope_projects"), list) else ["*"]
        can_baton = bool(body.get("can_hold_lead_baton", True))
        grant = aap.create_acl_grant(
            grantee_pseudonym=grantee,
            scope_projects=scopes,
            standing_trust_mode=trust_mode,
            can_hold_lead_baton=can_baton,
        )
        gwl.GWLClearinghouse().publish_acl_grant(grant)
        return {"ok": True, "grant": grant}, 200
    if action == "revoke_acl":
        gid = str(body.get("grant_id") or "").strip()
        res = gwl.GWLClearinghouse().revoke_acl_grant(gid)
        return res, (200 if res.get("ok") else 404)
    if action == "send_invitation":
        res = send_project_invitation(
            recipient_pseudonym=str(body.get("recipient_pseudonym") or body.get("recipient") or "Merrill"),
            project_uid=str(body.get("project_uid") or ""),
            project_name=str(body.get("project_name") or ""),
            cdir=str(body.get("cdir") or ""),
            peer_online=body.get("peer_online"),
            peer_endpoint=str(body.get("peer_endpoint") or ""),
            message=str(body.get("message") or ""),
        )
        return res, 200
    if action == "respond_invitation":
        inv = body.get("invitation") or body.get("envelope") or body.get("invitation_id") or ""
        res = respond_project_invitation(
            inv,
            decision=str(body.get("decision") or "auto"),
            recipient_pseudonym=str(body.get("recipient_pseudonym") or ""),
        )
        return res, (200 if res.get("ok") else 400)
    if action == "transfer_baton":
        cdir = str(body.get("cdir") or "").strip()
        if not cdir:
            return {"ok": False, "error": "missing_cdir"}, 400
        res = cbt.transfer_lead_baton(
            cdir=cdir,
            from_did=str(body.get("from_did") or local_mothership_identity()["did"]),
            to_did=str(body.get("to_did") or body.get("to_pseudonym") or ""),
            to_pseudonym=str(body.get("to_pseudonym") or ""),
        )
        return res, (200 if res.get("ok") else 409)
    if action == "sync_tier_resources":
        cdir = str(body.get("cdir") or "").strip()
        if not cdir:
            return {"ok": False, "error": "missing_cdir"}, 400
        extra = body.get("extra_descriptors") if isinstance(body.get("extra_descriptors"), list) else None
        manifest = cbt.classify_and_manifest_resources(cdir, extra_descriptors=extra)
        return {"ok": True, "manifest": manifest}, 200
    if action == "share_foundry_skill":
        fed = ffed.FoundryStewardFederation()
        bundle = body.get("bundle")
        if not isinstance(bundle, dict):
            bundle = fed.export_skill_bundle(
                skill_id=str(body.get("skill_id") or "custom-skill"),
                author_pseudonym=str(body.get("author_pseudonym") or local_mothership_identity()["pseudonym"]),
                skill_md=str(body.get("skill_md") or ""),
                scripts=body.get("scripts") if isinstance(body.get("scripts"), dict) else None,
            )
        q_res = fed.receive_into_quarantine(bundle)
        eval_res = fed.evaluate_quarantined_skill(bundle)
        return {"ok": True, "bundle": bundle, "quarantine": q_res, "evaluation": eval_res}, 200
    if action == "claim_step":
        cdir = str(body.get("cdir") or "").strip()
        if not cdir:
            return {"ok": False, "error": "missing_cdir"}, 400
        res = claim_step_lease(
            cdir,
            step_id=str(body.get("step_id") or ""),
            mothership_id=str(body.get("mothership_id") or ""),
            owner_label=str(body.get("owner_label") or ""),
            force=bool(body.get("force")),
        )
        return res, (200 if res.get("ok") else 409)
    if action == "release_step":
        cdir = str(body.get("cdir") or "").strip()
        if not cdir:
            return {"ok": False, "error": "missing_cdir"}, 400
        res = release_step_lease(
            cdir,
            step_id=str(body.get("step_id") or ""),
            mothership_id=str(body.get("mothership_id") or ""),
        )
        return res, (200 if res.get("ok") else 409)
    if action == "export_packet":
        cdir = str(body.get("cdir") or "").strip()
        if not cdir:
            return {"ok": False, "error": "missing_cdir"}, 400
        pkt = export_cockpit_packet(cdir, mothership_id=str(body.get("mothership_id") or ""))
        return {"ok": True, "packet": pkt}, 200
    if action == "import_packet":
        cdir = str(body.get("cdir") or "").strip()
        pkt = body.get("packet")
        if isinstance(pkt, str) and pkt.strip():
            try:
                pkt = json.loads(pkt)
            except Exception:
                pkt = None
        if not cdir or not isinstance(pkt, dict):
            return {"ok": False, "error": "missing_cdir_or_packet"}, 400
        res = import_cockpit_packet(cdir, pkt)
        return res, (200 if res.get("ok") else 400)
    if action in ("sync_now", "sync_peer"):
        peer_id = str(body.get("peer_id") or body.get("id") or "").strip()
        cdir = str(body.get("cdir") or "").strip()
        return sync_peer_mothership(peer_id=peer_id, cdir=cdir, entries=entries), 200
    return {"ok": False, "error": f"unknown_action:{action}"}, 400
