"""Wave 22.1 — Canonical Agentic Envelope, Pseudonym Identity, ACL Grants & 3 Steward Incarnations (stdlib only).

Provides:
- First-Class User Pseudonyms with J.R.R. Tolkien canonical default ``"Samwise Gamgee"``
  (``did:anchor:samwise-gamgee``) and seamless alias resolution for ``"Samwise Gamgi"`` and ``"Samwise"``.
- Privacy-preserving identity scrubbing so outbound packets, Ghost World Lab Hub records,
  Cockpit Batons, Step Leases, and Federated Lesson Cards never leak raw OS usernames or private hostnames.
- ``anchor.identity.record.v1`` (``get_or_create_identity``, ``resolve_pseudonym``).
- ``anchor.acl.grant.v1`` (``create_acl_grant``, ``verify_acl_grant``, ``revoke_acl_grant``, ``list_acl_grants``).
- ``anchor.agent.envelope.v1`` (``create_agent_envelope``, ``verify_agent_envelope``, ``StewardDialogueSession``)
  across the 3 Steward incarnations (``steward:cave``, ``steward:cockpit``, ``steward:foundry``).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import socket
from typing import Any

import paths
import provider_secrets


IDENTITY_SCHEMA = "anchor.identity.record.v1"
ACL_GRANT_SCHEMA = "anchor.acl.grant.v1"
ENVELOPE_SCHEMA = "anchor.agent.envelope.v1"

PSEUDONYM_DEFAULT = "Samwise Gamgee"
PSEUDONYM_ALIASES_DEFAULT = ["Samwise Gamgi", "Samwise"]

STEWARD_INCARNATIONS = ("steward:cave", "steward:cockpit", "steward:foundry")
VALID_TRUST_MODES = ("prompt_first", "auto_accept_scoped")
VALID_INTENTS = (
    "HELLO_IDENTIFY",
    "ASK_DIALOGUE",
    "INVITE_PROJECT",
    "CONSENT_DECISION",
    "COCKPIT_MOUNT_HANDOFF",
    "LEASE_DELEGATE",
    "BATON_TRANSFER",
    "FOUNDRY_SHARE",
    "HUMAN_SIGNAL",
)
DEFAULT_MAX_TURNS = 6


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_now_iso() -> str:
    return _utc_now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _collab_dir() -> Path:
    override = os.environ.get("ANCHOR_COLLAB_DIR", "").strip()
    if override:
        p = Path(override)
    else:
        base = paths.data_dir() if hasattr(paths, "data_dir") else Path(__file__).resolve().parent
        p = Path(base) / ".anchor"
    p.mkdir(parents=True, exist_ok=True)
    return p


def slugify_pseudonym(name: str) -> str:
    """Convert a display pseudonym into a URL/DID/branch-safe lowercase slug."""
    raw = str(name or "").strip().lower()
    if raw.startswith("did:anchor:"):
        raw = raw[len("did:anchor:"):]
    slug = re.sub(r"[^a-z0-9]+", "-", raw).strip("-")
    return slug or "samwise-gamgee"


def did_from_pseudonym(name: str) -> str:
    """Return the canonical ``did:anchor:<slug>`` identifier for a pseudonym."""
    raw = str(name or "").strip()
    if raw.startswith("did:anchor:"):
        slug = slugify_pseudonym(raw[len("did:anchor:"):])
        if slug in ("samwise-gamgi", "samwise"):
            slug = "samwise-gamgee"
        return f"did:anchor:{slug}"
    slug = slugify_pseudonym(raw)
    if slug in ("samwise-gamgi", "samwise"):
        slug = "samwise-gamgee"
    return f"did:anchor:{slug}"


def canonicalize_pseudonym(pseudonym: str | None, aliases: list[str] | None = None) -> tuple[str, list[str]]:
    """Normalize Samwise spelling variants to canonical 'Samwise Gamgee' while preserving aliases."""
    raw = str(pseudonym or "").strip()
    if not raw:
        raw = PSEUDONYM_DEFAULT
    slug = slugify_pseudonym(raw)
    alias_list: list[str] = []
    if aliases:
        for a in aliases:
            a_str = str(a or "").strip()
            if a_str and a_str not in alias_list:
                alias_list.append(a_str)

    if slug in ("samwise-gamgee", "samwise-gamgi", "samwise"):
        canon = PSEUDONYM_DEFAULT
        for def_a in PSEUDONYM_ALIASES_DEFAULT:
            if def_a not in alias_list:
                alias_list.append(def_a)
        if raw != canon and raw not in alias_list:
            alias_list.insert(0, raw)
        return canon, alias_list

    return raw, alias_list


_WIN_USER_SCRUB_RE = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+([^\\/\s\"']+)", re.IGNORECASE)
_POSIX_USER_SCRUB_RE = re.compile(r"/(?:Users|home)/([^/\s\"']+)")


def scrub_private_identity_leaks(val: Any, pseudonym: str = PSEUDONYM_DEFAULT) -> Any:
    """Recursively scrub raw OS usernames, home paths, and private hostnames from outbound structures."""
    slug = slugify_pseudonym(pseudonym)
    if isinstance(val, str):
        out = val
        try:
            home_str = str(Path.home())
            home_posix = Path.home().as_posix()
            if home_str and len(home_str) > 3:
                out = out.replace(home_str, f"<home:{slug}>")
                out = out.replace(home_str.lower(), f"<home:{slug}>")
            if home_posix and len(home_posix) > 3:
                out = out.replace(home_posix, f"<home:{slug}>")
                out = out.replace(home_posix.lower(), f"<home:{slug}>")
        except Exception:
            pass
        out = _WIN_USER_SCRUB_RE.sub(f"<home:{slug}>", out)
        out = _POSIX_USER_SCRUB_RE.sub(f"<home:{slug}>", out)
        try:
            host = (socket.gethostname() or "").strip()
            if host and len(host) > 2 and host.lower() not in ("localhost", "anchor"):
                out = re.sub(re.escape(host), slug, out, flags=re.IGNORECASE)
        except Exception:
            pass
        return out
    if isinstance(val, list):
        return [scrub_private_identity_leaks(x, pseudonym=pseudonym) for x in val]
    if isinstance(val, tuple):
        return tuple(scrub_private_identity_leaks(x, pseudonym=pseudonym) for x in val)
    if isinstance(val, dict):
        return {k: scrub_private_identity_leaks(v, pseudonym=pseudonym) for k, v in val.items()}
    return val


def _signing_key_file(did: str) -> Path:
    safe = slugify_pseudonym(did)
    kdir = _collab_dir() / "keystore"
    kdir.mkdir(parents=True, exist_ok=True)
    return kdir / f"{safe}.key"


def _get_or_create_signing_key(did: str) -> str:
    """Load or generate a deterministic/persistent 256-bit signing key for ``did``."""
    use_hermetic = bool(os.environ.get("ANCHOR_COLLAB_DIR", "").strip() or os.environ.get("PYTEST_CURRENT_TEST"))
    vault_id = f"mothership-signing-key/{did}"
    if not use_hermetic and provider_secrets.available():
        try:
            existing = provider_secrets.get(vault_id)
            if existing and len(existing) >= 32:
                return existing
        except Exception:
            pass

    kf = _signing_key_file(did)
    if kf.is_file():
        try:
            raw = kf.read_text(encoding="utf-8").strip()
            if len(raw) >= 32:
                return raw
        except Exception:
            pass

    generated = secrets.token_hex(32)
    try:
        kf.write_text(generated + "\n", encoding="utf-8")
    except Exception:
        pass
    if not use_hermetic and provider_secrets.available():
        try:
            provider_secrets.put(vault_id, generated)
        except Exception:
            pass
    return generated


def derive_pubkey_fingerprint(signing_key: str, did: str = "") -> str:
    """Derive a public verification commitment from the local signing key."""
    material = f"anchor-pubkey-v1:{did}:{signing_key}".encode("utf-8")
    return "hmac-sha256-pub:" + hashlib.sha256(material).hexdigest()


def _canonical_bytes(payload: dict[str, Any] | str | bytes) -> bytes:
    if isinstance(payload, bytes):
        return payload
    if isinstance(payload, str):
        return payload.encode("utf-8")
    clean = {k: v for k, v in payload.items() if k != "signature"}
    return json.dumps(clean, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_payload(payload: dict[str, Any] | str | bytes, did: str = "", signing_key: str = "") -> str:
    """Sign a canonical JSON payload with HMAC-SHA256."""
    eff_did = did or f"did:anchor:{slugify_pseudonym(PSEUDONYM_DEFAULT)}"
    key = signing_key or _get_or_create_signing_key(eff_did)
    digest = hmac.new(key.encode("utf-8"), _canonical_bytes(payload), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{digest}"


def verify_signature(
    payload: dict[str, Any] | str | bytes,
    signature: str,
    did: str = "",
    signing_key: str = "",
) -> bool:
    """Verify an HMAC-SHA256 signature over ``payload``."""
    sig_str = str(signature or "").strip()
    if not sig_str.startswith("hmac-sha256:"):
        return False
    expected = sign_payload(payload, did=did, signing_key=signing_key)
    return hmac.compare_digest(sig_str, expected)


def _identity_file() -> Path:
    return _collab_dir() / "mothership_identity.json"


def get_or_create_identity(
    pseudonym: str | None = None,
    aliases: list[str] | None = None,
    role: str = "lead",
    persist: bool = True,
) -> dict[str, Any]:
    """Return or initialize the local Mothership identity record (``anchor.identity.record.v1``).

    Defaults to ``"Samwise Gamgee"`` (``did:anchor:samwise-gamgee``) with aliases
    ``["Samwise Gamgi", "Samwise"]``, while preserving any existing ``id``/``label`` on disk
    when ``pseudonym`` is not explicitly overridden.
    """
    fp = _identity_file()
    existing: dict[str, Any] = {}
    if fp.is_file():
        try:
            loaded = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except Exception:
            existing = {}

    explicit_update = pseudonym is not None or aliases is not None
    raw_pseudo = pseudonym if pseudonym is not None else existing.get("pseudonym")
    raw_aliases = aliases if aliases is not None else existing.get("pseudonym_aliases")
    canon_pseudo, canon_aliases = canonicalize_pseudonym(raw_pseudo, raw_aliases)
    slug = slugify_pseudonym(canon_pseudo)
    did = did_from_pseudonym(canon_pseudo)

    if existing.get("id") and not explicit_update:
        ms_id = str(existing["id"])
    else:
        ms_id = f"{slug}-mothership"

    if existing.get("label") and not explicit_update:
        ms_label = str(existing["label"])
    else:
        ms_label = f"{canon_pseudo} · Mother Ship"

    eff_role = str(existing.get("role") or role or "lead")
    skey = _get_or_create_signing_key(did)
    pub_fp = derive_pubkey_fingerprint(skey, did=did)

    record = {
        "schema": IDENTITY_SCHEMA,
        "id": ms_id,
        "did": did,
        "pseudonym": canon_pseudo,
        "pseudonym_slug": slug,
        "pseudonym_aliases": canon_aliases,
        "label": ms_label,
        "role": eff_role,
        "pubkey_hmac_sha256": pub_fp,
        "incarnations": list(STEWARD_INCARNATIONS),
        "updated_at": str(existing.get("updated_at") or _utc_now_iso()),
    }
    if persist and (explicit_update or not fp.is_file() or existing.get("schema") != IDENTITY_SCHEMA):
        record["updated_at"] = _utc_now_iso()
        fp.parent.mkdir(parents=True, exist_ok=True)
        fp.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    return record


def resolve_pseudonym(
    name_or_did: str,
    directory: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Resolve a pseudonym, spelling variant ('Samwise Gamgi'), slug, or DID to its canonical record."""
    query = str(name_or_did or "").strip()
    if not query:
        return {"ok": False, "error": "empty_query"}

    q_lower = query.lower()
    q_slug = slugify_pseudonym(query)

    candidates: list[dict[str, Any]] = []
    local_ident = get_or_create_identity(persist=False)
    candidates.append(local_ident)

    if directory:
        for entry in directory:
            if isinstance(entry, dict):
                candidates.append(entry)

    # Also inspectcollab_peers.json if present
    peers_fp = _collab_dir() / "collab_peers.json"
    if peers_fp.is_file():
        try:
            raw_peers = json.loads(peers_fp.read_text(encoding="utf-8"))
            plist = raw_peers.get("peers") if isinstance(raw_peers, dict) else raw_peers
            if isinstance(plist, list):
                for p in plist:
                    if isinstance(p, dict):
                        candidates.append(p)
        except Exception:
            pass

    for cand in candidates:
        c_pseudo = str(cand.get("pseudonym") or cand.get("label") or "").strip()
        c_did = str(cand.get("did") or "").strip() or (did_from_pseudonym(c_pseudo) if c_pseudo else "")
        c_slug = str(cand.get("pseudonym_slug") or "").strip() or (slugify_pseudonym(c_pseudo) if c_pseudo else "")
        c_id = str(cand.get("id") or "").strip()
        c_aliases = [str(a).strip() for a in (cand.get("pseudonym_aliases") or []) if str(a).strip()]

        match_Pool = {
            c_pseudo.lower(),
            c_did.lower(),
            c_slug.lower(),
            c_id.lower(),
        }
        for al in c_aliases:
            match_Pool.add(al.lower())
            match_Pool.add(slugify_pseudonym(al))
            match_Pool.add(f"did:anchor:{slugify_pseudonym(al)}")

        if q_lower in match_Pool or q_slug in match_Pool:
            return {
                "ok": True,
                "did": c_did or did_from_pseudonym(c_pseudo or q_slug),
                "pseudonym": c_pseudo or PSEUDONYM_DEFAULT,
                "pseudonym_slug": c_slug or slugify_pseudonym(c_pseudo or q_slug),
                "pseudonym_aliases": c_aliases,
                "mothership_id": c_id or f"{c_slug}-mothership",
                "matched_query": query,
            }

    # Built-in canonical Samwise Gamgee / Samwise Gamgi fallback
    if q_slug in ("samwise-gamgee", "samwise-gamgi", "samwise") or q_lower in (
        "did:anchor:samwise-gamgee",
        "did:anchor:samwise-gamgi",
    ):
        return {
            "ok": True,
            "did": "did:anchor:samwise-gamgee",
            "pseudonym": PSEUDONYM_DEFAULT,
            "pseudonym_slug": "samwise-gamgee",
            "pseudonym_aliases": list(PSEUDONYM_ALIASES_DEFAULT),
            "mothership_id": "samwise-gamgee-mothership",
            "matched_query": query,
        }

    return {
        "ok": False,
        "error": "pseudonym_not_found",
        "matched_query": query,
        "suggested_did": did_from_pseudonym(query),
    }


# ── ACL Grants (anchor.acl.grant.v1) ──────────────────────────────────────────────────────────

def _acl_file() -> Path:
    return _collab_dir() / "acl_grants.json"


def _load_raw_grants() -> list[dict[str, Any]]:
    fp = _acl_file()
    if not fp.is_file():
        return []
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
        if isinstance(data, dict) and isinstance(data.get("grants"), list):
            return [g for g in data["grants"] if isinstance(g, dict)]
        if isinstance(data, list):
            return [g for g in data if isinstance(g, dict)]
    except Exception:
        pass
    return []


def _save_raw_grants(grants: list[dict[str, Any]]) -> None:
    fp = _acl_file()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(
        json.dumps({"grants": grants, "updated_at": _utc_now_iso()}, indent=2) + "\n",
        encoding="utf-8",
    )


def create_acl_grant(
    grantee_pseudonym: str,
    grantee_did: str = "",
    scope_projects: list[str] | None = None,
    allowed_incarnations: list[str] | None = None,
    standing_trust_mode: str = "prompt_first",
    can_hold_lead_baton: bool = True,
    issuer_pseudonym: str = "",
    issuer_did: str = "",
    expires_in_days: int = 90,
    expires_at: str = "",
) -> dict[str, Any]:
    """Create and sign an ``anchor.acl.grant.v1`` record specifying who shares with who and standing consent."""
    ident = get_or_create_identity(persist=False)
    iss_pseudo = str(issuer_pseudonym or ident["pseudonym"]).strip()
    iss_did = str(issuer_did or ident["did"]).strip()

    gran_pseudo, _ = canonicalize_pseudonym(grantee_pseudonym) if slugify_pseudonym(grantee_pseudonym) in ("samwise-gamgee", "samwise-gamgi") else (str(grantee_pseudonym or "Collaborator").strip(), [])
    gran_did = str(grantee_did or did_from_pseudonym(gran_pseudo)).strip()

    trust_mode = str(standing_trust_mode or "prompt_first").strip()
    if trust_mode not in VALID_TRUST_MODES:
        trust_mode = "prompt_first"

    inc_list = list(allowed_incarnations) if allowed_incarnations else list(STEWARD_INCARNATIONS)
    proj_list = [str(p).strip() for p in (scope_projects or ["*"]) if str(p).strip()] or ["*"]

    now = _utc_now()
    issued_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    exp_iso = str(expires_at or (now + timedelta(days=max(1, int(expires_in_days)))).strftime("%Y-%m-%dT%H:%M:%SZ"))

    grant_seed = f"{iss_did}:{gran_did}:{','.join(sorted(proj_list))}:{issued_iso}:{secrets.token_hex(4)}"
    grant_id = "acl-" + hashlib.sha256(grant_seed.encode("utf-8")).hexdigest()[:16]

    grant: dict[str, Any] = {
        "schema": ACL_GRANT_SCHEMA,
        "grant_id": grant_id,
        "issuer_did": iss_did,
        "issuer_pseudonym": iss_pseudo,
        "grantee_did": gran_did,
        "grantee_pseudonym": gran_pseudo,
        "scope_projects": proj_list,
        "allowed_incarnations": inc_list,
        "standing_trust_mode": trust_mode,
        "can_hold_lead_baton": bool(can_hold_lead_baton),
        "issued_at": issued_iso,
        "expires_at": exp_iso,
        "revoked": False,
    }
    grant["signature"] = sign_payload(grant, did=iss_did)

    grants = _load_raw_grants()
    # Replace existing unrevoked grant for same issuer+grantee+scope if exact match, else append
    grants.append(grant)
    _save_raw_grants(grants)
    return grant


def verify_acl_grant(
    grant: dict[str, Any],
    project_uid: str = "",
    incarnation: str = "",
) -> dict[str, Any]:
    """Verify signature, expiration, revocation status, and scope of an ``anchor.acl.grant.v1``."""
    if not isinstance(grant, dict) or grant.get("schema") != ACL_GRANT_SCHEMA:
        return {"ok": False, "valid": False, "error": "invalid_acl_schema"}
    if grant.get("revoked"):
        return {"ok": False, "valid": False, "error": "acl_grant_revoked"}
    if grant.get("standing_trust_mode") not in VALID_TRUST_MODES:
        return {"ok": False, "valid": False, "error": "invalid_standing_trust_mode"}

    exp_str = str(grant.get("expires_at") or "").strip()
    if exp_str:
        try:
            exp_dt = datetime.fromisoformat(exp_str.replace("Z", "+00:00"))
            if exp_dt < _utc_now():
                return {"ok": False, "valid": False, "error": "acl_grant_expired"}
        except Exception:
            return {"ok": False, "valid": False, "error": "malformed_expires_at"}

    iss_did = str(grant.get("issuer_did") or "")
    sig = str(grant.get("signature") or "")
    if not verify_signature(grant, sig, did=iss_did):
        return {"ok": False, "valid": False, "error": "invalid_acl_signature"}

    if project_uid:
        scopes = grant.get("scope_projects") or []
        if "*" not in scopes and project_uid not in scopes:
            return {"ok": False, "valid": False, "error": "project_out_of_scope"}

    if incarnation:
        base_inc = ":".join(incarnation.split(":")[:2])
        allowed = grant.get("allowed_incarnations") or []
        if incarnation not in allowed and base_inc not in allowed:
            return {"ok": False, "valid": False, "error": "incarnation_not_allowed"}

    return {
        "ok": True,
        "valid": True,
        "grant_id": grant.get("grant_id"),
        "standing_trust_mode": grant.get("standing_trust_mode"),
        "can_hold_lead_baton": bool(grant.get("can_hold_lead_baton")),
    }


def revoke_acl_grant(grant_id: str) -> dict[str, Any]:
    """Revoke an ACL grant by ``grant_id``."""
    gid = str(grant_id or "").strip()
    grants = _load_raw_grants()
    target = None
    for g in grants:
        if str(g.get("grant_id") or "") == gid:
            g["revoked"] = True
            g["revoked_at"] = _utc_now_iso()
            target = g
            break
    if target is None:
        return {"ok": False, "error": "grant_not_found", "grant_id": gid}
    _save_raw_grants(grants)
    return {"ok": True, "grant": target}


def list_acl_grants(include_revoked: bool = False) -> list[dict[str, Any]]:
    """List ACL grants on this Mothership."""
    grants = _load_raw_grants()
    if include_revoked:
        return grants
    return [g for g in grants if not g.get("revoked")]


# ── Canonical Agentic Envelope (anchor.agent.envelope.v1) ─────────────────────────────────────

def _nonces_file() -> Path:
    return _collab_dir() / "envelope_nonces.json"


def _load_seen_nonces() -> set[str]:
    fp = _nonces_file()
    if not fp.is_file():
        return set()
    try:
        data = json.loads(fp.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {str(x) for x in data}
    except Exception:
        pass
    return set()


def _record_nonce(nonce: str) -> None:
    seen = list(_load_seen_nonces())
    if nonce not in seen:
        seen.append(nonce)
    # Keep bounded window of last 1024 nonces
    if len(seen) > 1024:
        seen = seen[-1024:]
    fp = _nonces_file()
    fp.parent.mkdir(parents=True, exist_ok=True)
    fp.write_text(json.dumps(seen) + "\n", encoding="utf-8")


def _valid_incarnation(inc: str) -> bool:
    s = str(inc or "").strip()
    return any(s == base or s.startswith(base + ":") for base in STEWARD_INCARNATIONS)


def create_agent_envelope(
    intent: str,
    recipient_pseudonym: str,
    payload: dict[str, Any] | None = None,
    recipient_did: str = "",
    sender_pseudonym: str = "",
    sender_did: str = "",
    from_incarnation: str = "steward:cave",
    to_incarnation: str = "steward:cave",
    project_uid: str = "",
    session_id: str = "",
    turn_index: int = 1,
    max_turns: int = DEFAULT_MAX_TURNS,
    acl_grant_id: str = "",
    nonce: str = "",
) -> dict[str, Any]:
    """Create and sign a canonical ``anchor.agent.envelope.v1`` packet.

    Enforces privacy scrubbing and hard bounded turn budget (``turn_index <= max_turns``,
    auto-escalating to ``HUMAN_SIGNAL`` when exceeded).
    """
    ident = get_or_create_identity(persist=False)
    s_pseudo, _ = canonicalize_pseudonym(sender_pseudonym or ident["pseudonym"])
    s_did = str(sender_did or did_from_pseudonym(s_pseudo)).strip()

    r_pseudo_raw = str(recipient_pseudonym or "Collaborator").strip()
    if slugify_pseudonym(r_pseudo_raw) in ("samwise-gamgee", "samwise-gamgi", "samwise"):
        r_pseudo = PSEUDONYM_DEFAULT
    else:
        r_pseudo = r_pseudo_raw
    r_did = str(recipient_did or did_from_pseudonym(r_pseudo)).strip()

    if not _valid_incarnation(from_incarnation):
        raise ValueError(f"Invalid from_incarnation: {from_incarnation}")
    if not _valid_incarnation(to_incarnation):
        raise ValueError(f"Invalid to_incarnation: {to_incarnation}")

    eff_intent = str(intent or "HELLO_IDENTIFY").strip().upper()
    if eff_intent not in VALID_INTENTS:
        raise ValueError(f"Invalid envelope intent: {eff_intent}")

    t_idx = int(turn_index)
    m_turns = int(max_turns) if int(max_turns) > 0 else DEFAULT_MAX_TURNS
    escalated = False
    escalation_reason = ""
    if t_idx > m_turns and eff_intent != "HUMAN_SIGNAL":
        escalated = True
        escalation_reason = f"turn_budget_exceeded ({t_idx} > {m_turns})"
        eff_intent = "HUMAN_SIGNAL"

    scrubbed_payload = scrub_private_identity_leaks(dict(payload or {}), pseudonym=s_pseudo)
    if escalated:
        scrubbed_payload["auto_escalated"] = True
        scrubbed_payload["escalation_reason"] = escalation_reason
        scrubbed_payload["original_intent"] = str(intent)

    eff_nonce = str(nonce or f"n-{secrets.token_hex(12)}")
    eff_session = str(session_id or f"sess-{hashlib.sha256((s_did + r_did + project_uid).encode('utf-8')).hexdigest()[:12]}")
    env_id = "env-" + hashlib.sha256(f"{eff_session}:{t_idx}:{eff_nonce}".encode("utf-8")).hexdigest()[:16]

    envelope: dict[str, Any] = {
        "schema": ENVELOPE_SCHEMA,
        "envelope_id": env_id,
        "session_id": eff_session,
        "sender_did": s_did,
        "sender_pseudonym": s_pseudo,
        "recipient_did": r_did,
        "recipient_pseudonym": r_pseudo,
        "from_incarnation": from_incarnation,
        "to_incarnation": to_incarnation,
        "intent": eff_intent,
        "project_uid": str(project_uid or ""),
        "turn_index": t_idx,
        "max_turns": m_turns,
        "escalated_to_human": escalated,
        "nonce": eff_nonce,
        "acl_grant_id": str(acl_grant_id or ""),
        "created_at": _utc_now_iso(),
        "payload": scrubbed_payload,
    }
    envelope["signature"] = sign_payload(envelope, did=s_did)
    return envelope


def verify_agent_envelope(
    envelope: dict[str, Any],
    check_replay: bool = True,
    seen_nonces: set[str] | None = None,
) -> dict[str, Any]:
    """Verify schema, incarnations, replay nonce window, turn cap, and signature of an envelope."""
    if not isinstance(envelope, dict) or envelope.get("schema") != ENVELOPE_SCHEMA:
        return {"ok": False, "valid": False, "error": "invalid_envelope_schema"}

    intent = str(envelope.get("intent") or "")
    if intent not in VALID_INTENTS:
        return {"ok": False, "valid": False, "error": f"invalid_intent:{intent}"}

    if not _valid_incarnation(str(envelope.get("from_incarnation") or "")) or not _valid_incarnation(
        str(envelope.get("to_incarnation") or "")
    ):
        return {"ok": False, "valid": False, "error": "invalid_incarnation"}

    t_idx = int(envelope.get("turn_index") or 0)
    m_turns = int(envelope.get("max_turns") or DEFAULT_MAX_TURNS)
    if t_idx < 1:
        return {"ok": False, "valid": False, "error": "invalid_turn_index"}
    if t_idx > m_turns and intent != "HUMAN_SIGNAL":
        return {"ok": False, "valid": False, "error": "turn_budget_exceeded_without_human_signal"}

    s_did = str(envelope.get("sender_did") or "")
    sig = str(envelope.get("signature") or "")
    if not verify_signature(envelope, sig, did=s_did):
        return {"ok": False, "valid": False, "error": "invalid_envelope_signature"}

    nonce = str(envelope.get("nonce") or "").strip()
    if not nonce:
        return {"ok": False, "valid": False, "error": "missing_nonce"}

    if check_replay:
        if seen_nonces is not None:
            if nonce in seen_nonces:
                return {"ok": False, "valid": False, "error": "replay_nonce_detected"}
            seen_nonces.add(nonce)
        else:
            disk_nonces = _load_seen_nonces()
            if nonce in disk_nonces:
                return {"ok": False, "valid": False, "error": "replay_nonce_detected"}
            _record_nonce(nonce)

    return {
        "ok": True,
        "valid": True,
        "envelope_id": envelope.get("envelope_id"),
        "intent": intent,
        "sender_did": s_did,
        "sender_pseudonym": envelope.get("sender_pseudonym"),
        "recipient_did": envelope.get("recipient_did"),
        "recipient_pseudonym": envelope.get("recipient_pseudonym"),
        "escalated_to_human": bool(envelope.get("escalated_to_human") or intent == "HUMAN_SIGNAL"),
    }


class StewardDialogueSession:
    """Bounded multi-turn dialogue coordinator between two Steward incarnations."""

    def __init__(
        self,
        sender_pseudonym: str = PSEUDONYM_DEFAULT,
        recipient_pseudonym: str = "Merrill",
        from_incarnation: str = "steward:cave",
        to_incarnation: str = "steward:cave",
        project_uid: str = "",
        max_turns: int = DEFAULT_MAX_TURNS,
        session_id: str = "",
    ) -> None:
        self.sender_pseudonym, _ = canonicalize_pseudonym(sender_pseudonym)
        self.sender_did = did_from_pseudonym(self.sender_pseudonym)
        self.recipient_pseudonym = recipient_pseudonym
        self.recipient_did = did_from_pseudonym(recipient_pseudonym)
        self.from_incarnation = from_incarnation
        self.to_incarnation = to_incarnation
        self.project_uid = project_uid
        self.max_turns = max_turns
        self.session_id = session_id or f"sess-{secrets.token_hex(6)}"
        self.turn_index = 0
        self.history: list[dict[str, Any]] = []
        self.seen_nonces: set[str] = set()

    def next_envelope(
        self,
        intent: str,
        payload: dict[str, Any] | None = None,
        swap_direction: bool = False,
        acl_grant_id: str = "",
    ) -> dict[str, Any]:
        """Advance the dialogue by one turn and emit a verified envelope."""
        self.turn_index += 1
        s_pseudo = self.recipient_pseudonym if swap_direction else self.sender_pseudonym
        s_did = self.recipient_did if swap_direction else self.sender_did
        r_pseudo = self.sender_pseudonym if swap_direction else self.recipient_pseudonym
        r_did = self.sender_did if swap_direction else self.recipient_did
        f_inc = self.to_incarnation if swap_direction else self.from_incarnation
        t_inc = self.from_incarnation if swap_direction else self.to_incarnation

        env = create_agent_envelope(
            intent=intent,
            recipient_pseudonym=r_pseudo,
            recipient_did=r_did,
            sender_pseudonym=s_pseudo,
            sender_did=s_did,
            from_incarnation=f_inc,
            to_incarnation=t_inc,
            project_uid=self.project_uid,
            session_id=self.session_id,
            turn_index=self.turn_index,
            max_turns=self.max_turns,
            payload=payload,
            acl_grant_id=acl_grant_id,
        )
        ver = verify_agent_envelope(env, check_replay=True, seen_nonces=self.seen_nonces)
        if not ver.get("ok"):
            raise ValueError(f"Dialogue turn verification failed: {ver.get('error')}")
        self.history.append(env)
        return env
