"""W7 Feedback transport: intake partition, edge validation, dogfood harness.

Extension point ``ext:feedback_sanitizer`` (transport half) — delivers
**sanitizer-proven** friction JSON/NDJSON to a John-owned private intake
(local repo subtree or dedicated inbox drop). W6 (``share_feedback``) only
sanitizes, keys, and queues; this module is the controlled push path.

Hard rules (NS 9; R11/R12/R14):

* **Intake-scoped credentials only** — never product-main write tokens
* **Hard per-skill partitions** — ``by_skill/<skill_id>/`` folders; no default
  cross-skill blob rollup (R14)
* **Edge validation** — rejects unknown fields and free-text overflow;
  fail closed (do not store dirty payloads)
* **No auto-merge** to skill sources — pull/review stubs only
* **Feedback ≠ code contribution** — hard-line docs + constant policy text
* **Dogfood harness** — thinnest viable intake + export-yield metrics;
  kill-channel-if-zero-yield note; no public marketing claims from code

Stdlib only. Network/git are never required for the local-drop path (CI-safe).
"""

from __future__ import annotations

import json
import re
import time
import uuid
from pathlib import Path

import share_feedback as fb

# ── Policy constants ─────────────────────────────────────────────────────────

TRANSPORT_SCHEMA = "share-feedback-transport-config/v1"
TRANSPORT_SCHEMA_VERSION = 1

INTAKE_LAYOUT_SCHEMA = "share-feedback-intake-layout/v1"
PARTITION_SUBDIR = "by_skill"
DEFAULT_INTAKE_REL = "feedback-intake"

# Credential scopes allowed on recipient machines for this channel.
INTAKE_CREDENTIAL_SCOPES = frozenset({
    "intake_write",
    "intake_drop",
    "intake_append",
})

# Product / skill-source write scopes — forbidden on recipient feedback config.
FORBIDDEN_CREDENTIAL_SCOPES = frozenset({
    "product_main_write",
    "main_write",
    "repo_admin",
    "skill_source_write",
    "code_push",
    "admin",
    "write_all",
})

# Hard-line: sanitized friction is NOT a code contribution (R12).
FEEDBACK_IS_NOT_CODE_CONTRIBUTION = (
    "Sanitized friction feedback is NOT a code contribution. "
    "It lands in a private John-controlled intake for pull/review only "
    "and never auto-merges to skill sources or product main. "
    "Use the collaborator branch/PR path for code; use this channel only "
    "for opt-in sanitizer-clean friction reports."
)

KILL_CHANNEL_IF_ZERO_YIELD_NOTE = (
    "If dogfood export yield is zero, kill the channel cost honestly "
    "rather than build heavy UI or make public marketing claims."
)

# Edge free-text overflow caps (stricter store gate; allowlist fields only).
_MAX_LEN = {
    "schema": 64,
    "schema_version": 32,
    "export_id": 64,
    "skill_id": 64,
    "skill_version": 64,
    "install_key": 36,
    "outcome": 32,
    "duration_band": 16,
    "complexity_band": 16,
    "os_class": 16,
    "source_record_id": 64,
}
_MAX_TOKEN_LEN = fb._MAX_TOKEN_LEN  # 24
_MAX_TOKEN_COUNT = fb._MAX_TOKEN_COUNT  # 4
_MAX_LIST_ITEMS = 16
_MAX_STRING_LEAF = 64  # absolute ceiling for any string leaf at the edge

_SKILL_ID_SAFE = re.compile(r"^[A-Za-z][A-Za-z0-9._\-]{0,63}$")


class IntakeError(Exception):
    """Raised when intake transport refuses (not soft drops)."""

    def __init__(self, reason, message=None):
        self.reason = reason
        self.message = message or ("intake refused: %s" % reason)
        super().__init__(self.message)


# ── Recipient transport config (credentials scope) ───────────────────────────

def default_transport_config(
    intake_root=None,
    *,
    mode: str = "local_drop",
    token_env: str = "ANCHOR_FEEDBACK_INTAKE_TOKEN",
) -> dict:
    """Build a valid intake-only recipient config (no product-main credentials)."""
    root = str(intake_root) if intake_root is not None else DEFAULT_INTAKE_REL
    return {
        "schema": TRANSPORT_SCHEMA,
        "schema_version": TRANSPORT_SCHEMA_VERSION,
        "mode": mode,  # local_drop | token_scoped_bot | mail_like_drop
        "intake": {
            "root": root,
            "partition": PARTITION_SUBDIR,
            "format": "json",  # json | ndjson
        },
        "credentials": [
            {
                "id": "intake-bot",
                "scope": "intake_write",
                "token_env": token_env,
                "path_prefix": DEFAULT_INTAKE_REL.rstrip("/") + "/",
            }
        ],
        "auto_merge_to_skill_sources": False,
        "product_main_write": False,
        "feedback_is_code_contribution": False,
        "policy": FEEDBACK_IS_NOT_CODE_CONTRIBUTION,
    }


def validate_recipient_config(doc) -> list:
    """Return problem codes; empty = config is intake-scoped and safe.

    **Credential scope assert (W7 GWT #3):** product-main write credentials
    must be absent. Any forbidden scope fails closed.
    """
    if not isinstance(doc, dict):
        return ["config-not-an-object"]
    problems = []
    if doc.get("schema") != TRANSPORT_SCHEMA:
        problems.append("schema-mismatch:%r" % (doc.get("schema"),))
    if doc.get("schema_version") != TRANSPORT_SCHEMA_VERSION:
        problems.append(
            "schema_version-mismatch:%r" % (doc.get("schema_version"),)
        )
    if doc.get("product_main_write") is True:
        problems.append("product_main_write-forbidden")
    if doc.get("auto_merge_to_skill_sources") is True:
        problems.append("auto_merge-forbidden")
    if doc.get("feedback_is_code_contribution") is True:
        problems.append("feedback-must-not-be-code-contribution")

    mode = doc.get("mode")
    if mode not in ("local_drop", "token_scoped_bot", "mail_like_drop"):
        problems.append("mode-invalid:%r" % (mode,))

    intake = doc.get("intake")
    if not isinstance(intake, dict):
        problems.append("intake-missing")
    else:
        if not intake.get("root"):
            problems.append("intake-root-missing")
        part = intake.get("partition")
        if part not in (PARTITION_SUBDIR, "by_skill"):
            problems.append("intake-partition-invalid:%r" % (part,))
        fmt = intake.get("format", "json")
        if fmt not in ("json", "ndjson"):
            problems.append("intake-format-invalid:%r" % (fmt,))

    creds = doc.get("credentials")
    if not isinstance(creds, list) or not creds:
        problems.append("credentials-missing")
    else:
        for i, c in enumerate(creds):
            if not isinstance(c, dict):
                problems.append("credential-%d-not-object" % i)
                continue
            scope = c.get("scope")
            if scope in FORBIDDEN_CREDENTIAL_SCOPES:
                problems.append("forbidden-credential-scope:%s" % scope)
            elif scope not in INTAKE_CREDENTIAL_SCOPES:
                problems.append("unknown-credential-scope:%r" % (scope,))
            # Explicit product-main style keys must never appear.
            for bad_key in (
                "github_pat_main",
                "product_main_token",
                "skill_source_token",
                "main_write_token",
                "admin_token",
            ):
                if bad_key in c and c.get(bad_key):
                    problems.append("product-credential-key-present:%s" % bad_key)

    # Inventory: every credential scope must be intake-only.
    if isinstance(creds, list):
        for c in creds:
            if not isinstance(c, dict):
                continue
            if c.get("scope") in FORBIDDEN_CREDENTIAL_SCOPES:
                # already recorded; keep idempotent
                pass

    return problems


def load_recipient_transport_config(path) -> dict:
    """Load transport config JSON from disk (fail closed on corrupt)."""
    p = Path(path)
    if not p.is_file():
        raise IntakeError("config-missing")
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntakeError("config-corrupt", str(exc)) from exc
    if not isinstance(doc, dict):
        raise IntakeError("config-not-an-object")
    problems = validate_recipient_config(doc)
    if problems:
        raise IntakeError(
            "config-invalid",
            "recipient transport config invalid: " + ",".join(problems),
        )
    return doc


def write_recipient_transport_config(path, doc=None, *, intake_root=None) -> Path:
    """Write a validated intake-only config (tests / onboard helpers)."""
    if doc is None:
        doc = default_transport_config(intake_root=intake_root)
    problems = validate_recipient_config(doc)
    if problems:
        raise IntakeError(
            "config-invalid",
            "cannot write invalid config: " + ",".join(problems),
        )
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return p


def inspect_credentials(doc) -> dict:
    """SAFE projection for tests: scopes present, product-main absent."""
    problems = validate_recipient_config(doc)
    scopes = []
    if isinstance(doc, dict):
        for c in doc.get("credentials") or []:
            if isinstance(c, dict) and c.get("scope"):
                scopes.append(c["scope"])
    forbidden_hits = [
        s for s in scopes if s in FORBIDDEN_CREDENTIAL_SCOPES
    ]
    return {
        "scopes": scopes,
        "intake_only": (
            bool(scopes)
            and not forbidden_hits
            and all(s in INTAKE_CREDENTIAL_SCOPES for s in scopes)
            and "product_main_write-forbidden" not in problems
        ),
        "product_main_credentials_absent": (
            not forbidden_hits
            and "product_main_write-forbidden" not in problems
            and not any(
                p.startswith("product-credential-key-present:")
                for p in problems
            )
        ),
        "problems": problems,
        "auto_merge": bool(
            isinstance(doc, dict) and doc.get("auto_merge_to_skill_sources")
        ),
    }


# ── Intake edge validation ───────────────────────────────────────────────────

def _string_overflows(key: str, text: str) -> str | None:
    if not isinstance(text, str):
        return "not-a-string:%s" % key
    cap = _MAX_LEN.get(key, _MAX_STRING_LEAF)
    if len(text) > cap:
        return "free-text-overflow:%s" % key
    if "\n" in text or "\r" in text:
        return "free-text-multiline:%s" % key
    return None


def validate_intake_edge(payload) -> list:
    """Edge schema validation: unknown fields + free-text overflow → reject.

    Unlike the W6 sanitizer (which *strips* unknown keys), the intake edge
    **rejects** payloads that still carry unknown fields or overflow caps.
    Empty list = acceptable to store.
    """
    if not isinstance(payload, dict):
        return ["payload-not-an-object"]

    problems = []
    unknown = sorted(set(payload.keys()) - fb.EXPORT_ALLOWLIST)
    if unknown:
        problems.append("unknown-fields:" + ",".join(unknown))

    # Structural reuse of W6 export validator.
    problems.extend(fb.validate_export_record(payload))

    # Free-text / length overflow on every string leaf.
    for path, text in fb._walk_strings(payload):
        # path like $.skill_id or $.workaround_tokens[0]
        leaf = path.rsplit(".", 1)[-1]
        leaf = re.sub(r"\[\d+\]$", "", leaf)
        if leaf.startswith("$"):
            leaf = leaf[2:] if leaf.startswith("$.") else leaf.lstrip("$.")
        # tokens use token cap
        if "workaround_tokens" in path:
            if len(text) > _MAX_TOKEN_LEN:
                problems.append("free-text-overflow:workaround_tokens")
            continue
        hit = _string_overflows(leaf or "value", text)
        if hit:
            problems.append(hit)

    # List size caps
    for list_key in (
        "structural_failure_codes",
        "model_family_seats",
        "workaround_codes",
        "workaround_tokens",
    ):
        if list_key in payload:
            val = payload[list_key]
            if isinstance(val, list) and len(val) > _MAX_LIST_ITEMS:
                problems.append("list-overflow:%s" % list_key)
    if isinstance(payload.get("workaround_tokens"), list):
        if len(payload["workaround_tokens"]) > _MAX_TOKEN_COUNT:
            problems.append("workaround_tokens-too-many")

    # Must still be sanitizer-clean (fail closed).
    if not problems:
        clean = fb.sanitize_for_export(payload)
        if clean is None:
            problems.append("sanitizer-not-clean")

    # Dedup while preserving order
    seen = set()
    out = []
    for p in problems:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def is_edge_acceptable(payload) -> bool:
    return not validate_intake_edge(payload)


# ── Per-skill partition storage ──────────────────────────────────────────────

def skill_partition_dir(intake_root, skill_id: str) -> Path:
    """Hard partition path: ``<intake_root>/by_skill/<skill_id>/``."""
    if not isinstance(skill_id, str) or not _SKILL_ID_SAFE.match(skill_id):
        raise IntakeError("skill_id-invalid-for-partition")
    root = Path(intake_root)
    return root / PARTITION_SUBDIR / skill_id


def ensure_intake_layout(intake_root) -> Path:
    """Create intake root + layout marker (no skill partitions until deliver)."""
    root = Path(intake_root)
    root.mkdir(parents=True, exist_ok=True)
    marker = root / "INTAKE-LAYOUT.json"
    if not marker.is_file():
        doc = {
            "schema": INTAKE_LAYOUT_SCHEMA,
            "schema_version": 1,
            "partition": PARTITION_SUBDIR,
            "auto_merge_to_skill_sources": False,
            "policy": FEEDBACK_IS_NOT_CODE_CONTRIBUTION,
            "created_ts": time.time(),
        }
        marker.write_text(
            json.dumps(doc, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    readme = root / "README.md"
    if not readme.is_file():
        readme.write_text(
            "# Feedback intake (private)\n\n"
            + FEEDBACK_IS_NOT_CODE_CONTRIBUTION
            + "\n\n"
            "Layout: `by_skill/<skill_id>/*.json` — one skill per folder. "
            "No cross-skill default rollup. No auto-merge to skill sources.\n",
            encoding="utf-8",
            newline="\n",
        )
    return root


def _record_filename(clean: dict) -> str:
    eid = clean.get("export_id")
    if not isinstance(eid, str) or not eid.strip():
        eid = "ex-" + uuid.uuid4().hex[:12]
    # filesystem-safe
    safe = re.sub(r"[^A-Za-z0-9._\-]+", "_", eid)[:64]
    return "%s.json" % safe


def deliver_to_intake(
    intake_root,
    clean_record: dict,
    *,
    credentials_config=None,
    format: str = "json",
) -> dict:
    """Store one sanitizer-clean record under its skill_id partition.

    Returns::

        {
          "accepted": bool,
          "path": str|None,
          "skill_id": str|None,
          "install_key": str|None,
          "partition": str|None,
          "reason": str|None,
          "edge_problems": list,
        }
    """
    result = {
        "accepted": False,
        "path": None,
        "skill_id": None,
        "install_key": None,
        "partition": None,
        "reason": None,
        "edge_problems": [],
    }

    if credentials_config is not None:
        cfg_problems = validate_recipient_config(credentials_config)
        if cfg_problems:
            result["reason"] = "credentials-invalid:" + ",".join(cfg_problems)
            return result

    edge = validate_intake_edge(clean_record)
    result["edge_problems"] = edge
    if edge:
        result["reason"] = "edge_reject"
        return result

    # Re-sanitize fail-closed before write.
    clean = fb.sanitize_for_export(clean_record)
    if clean is None:
        result["reason"] = "sanitizer_drop"
        return result

    skill_id = clean.get("skill_id")
    result["skill_id"] = skill_id
    result["install_key"] = clean.get("install_key")
    try:
        part = skill_partition_dir(intake_root, skill_id)
    except IntakeError as exc:
        result["reason"] = exc.reason
        return result

    ensure_intake_layout(intake_root)
    part.mkdir(parents=True, exist_ok=True)
    fname = _record_filename(clean)
    if format == "ndjson":
        # One record per file (partition-safe); single-line JSON object.
        path = part / (Path(fname).stem + ".ndjson")
        body = json.dumps(clean, sort_keys=True, separators=(",", ":")) + "\n"
    else:
        path = part / fname
        body = json.dumps(clean, indent=2, sort_keys=True) + "\n"

    path.write_text(body, encoding="utf-8", newline="\n")
    result["accepted"] = True
    result["path"] = str(path)
    result["partition"] = str(part)
    result["reason"] = None
    return result


def make_intake_transmitter(
    intake_root,
    *,
    credentials_config=None,
    format: str = "json",
):
    """Return a ``transmitter(record) -> bool`` for ``share_feedback.drain_queue``."""

    def _tx(record: dict) -> bool:
        out = deliver_to_intake(
            intake_root,
            record,
            credentials_config=credentials_config,
            format=format,
        )
        return bool(out.get("accepted"))

    return _tx


def transport_drain(
    home,
    intake_root,
    *,
    credentials_config=None,
    skills_root=None,
    seal_path=None,
    format: str = "json",
) -> dict:
    """Drain local queue into partitioned intake (consent + optional seal gate).

    Wires W6 ``drain_queue`` to the intake transmitter. When ``skills_root``
    is provided, a forked seal blocks the entire drain (no partial send).
    """
    out = {
        "ok": False,
        "drain": None,
        "reason": None,
        "intake_root": str(intake_root),
    }
    if credentials_config is not None:
        problems = validate_recipient_config(credentials_config)
        if problems:
            out["reason"] = "credentials-invalid:" + ",".join(problems)
            return out

    gates = fb.feedback_export_prerequisites(
        home, skills_root, seal_path=seal_path
    )
    if not gates["ok"]:
        out["reason"] = ",".join(gates["reasons"])
        return out

    ensure_intake_layout(intake_root)
    tx = make_intake_transmitter(
        intake_root,
        credentials_config=credentials_config,
        format=format,
    )
    drain = fb.drain_queue(home, transmitter=tx)
    out["drain"] = drain
    out["ok"] = drain.get("transmitted", 0) > 0 or (
        drain.get("consent_valid") and not drain.get("held")
    )
    if drain.get("reason"):
        out["reason"] = drain["reason"]
    return out


# ── Pull / review stubs (no auto-merge) ──────────────────────────────────────

def auto_merge_allowed() -> bool:
    """Always False — intake never auto-merges into skill sources."""
    return False


def attempt_auto_merge_to_skill_sources(*_args, **_kwargs) -> dict:
    """Stub: always refuse. Feedback is not a code contribution."""
    return {
        "merged": False,
        "auto_merge": False,
        "reason": "auto_merge_forbidden",
        "policy": FEEDBACK_IS_NOT_CODE_CONTRIBUTION,
    }


def pull_review_stub(intake_root) -> dict:
    """List partitioned intake for human pull/review — never merges."""
    root = Path(intake_root)
    partitions = {}
    by_skill = root / PARTITION_SUBDIR
    if by_skill.is_dir():
        for skill_dir in sorted(p for p in by_skill.iterdir() if p.is_dir()):
            files = sorted(
                p.name
                for p in skill_dir.iterdir()
                if p.is_file() and p.suffix in (".json", ".ndjson")
            )
            partitions[skill_dir.name] = {
                "count": len(files),
                "files": files,
            }
    return {
        "action": "pull_review_only",
        "auto_merge": False,
        "auto_merge_allowed": auto_merge_allowed(),
        "policy": FEEDBACK_IS_NOT_CODE_CONTRIBUTION,
        "partitions": partitions,
        "skill_ids": sorted(partitions.keys()),
        "total_records": sum(p["count"] for p in partitions.values()),
    }


# ── R14: forbid cross-skill default rollup ───────────────────────────────────

def list_partition_records(intake_root, skill_id: str) -> list:
    """Load records for **one** skill partition only."""
    if not isinstance(skill_id, str) or not _SKILL_ID_SAFE.match(skill_id):
        raise IntakeError("skill_id-invalid-for-partition")
    part = skill_partition_dir(intake_root, skill_id)
    if not part.is_dir():
        return []
    out = []
    for path in sorted(part.iterdir()):
        if not path.is_file() or path.suffix not in (".json", ".ndjson"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
            if path.suffix == ".ndjson":
                # one object per file in our layout; take first non-empty line
                line = next(
                    (ln for ln in text.splitlines() if ln.strip()),
                    "",
                )
                doc = json.loads(line) if line else None
            else:
                doc = json.loads(text)
        except (OSError, json.JSONDecodeError, StopIteration):
            continue
        if isinstance(doc, dict):
            doc = dict(doc)
            doc["_intake_path"] = str(path)
            out.append(doc)
    return out


def partition_metrics(intake_root) -> dict:
    """Per-skill counts only — never a merged cross-skill record blob."""
    root = Path(intake_root) / PARTITION_SUBDIR
    metrics = {}
    if not root.is_dir():
        return metrics
    for skill_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        n = sum(
            1
            for p in skill_dir.iterdir()
            if p.is_file() and p.suffix in (".json", ".ndjson")
        )
        metrics[skill_dir.name] = {"count": n, "skill_id": skill_dir.name}
    return metrics


def cross_skill_blob_rollup(intake_root) -> dict:
    """R14: always refuse a default cross-skill record blob.

    Callers that need multi-skill *metrics* must use ``partition_metrics``
    (counts only). Merging raw records across skills is forbidden by default.
    """
    return {
        "ok": False,
        "refused": True,
        "reason": "cross_skill_blob_rollup_forbidden",
        "r14": True,
        "use_instead": "partition_metrics|list_partition_records(skill_id)",
        "metrics_only": partition_metrics(intake_root),
    }


# ── Dogfood harness ──────────────────────────────────────────────────────────

def measure_export_yield(
    *,
    attempted: int,
    accepted: int,
    dogfood: bool = True,
) -> dict:
    """Export-yield metrics for invited-collaborator dogfood.

    Public marketing claims are **never** authorized by this helper
    (``public_marketing_allowed`` is always False). Zero yield recommends
    killing the channel cost honestly.
    """
    attempted = max(0, int(attempted))
    accepted = max(0, int(accepted))
    if accepted > attempted:
        accepted = attempted
    ratio = (float(accepted) / float(attempted)) if attempted else 0.0
    zero = accepted == 0
    return {
        "attempted": attempted,
        "accepted": accepted,
        "yield_ratio": ratio,
        "zero_yield": zero,
        "kill_channel_recommended": bool(dogfood and zero),
        "kill_channel_note": (
            KILL_CHANNEL_IF_ZERO_YIELD_NOTE if zero else None
        ),
        "public_marketing_allowed": False,
        "dogfood": bool(dogfood),
        "policy": FEEDBACK_IS_NOT_CODE_CONTRIBUTION,
    }


def run_dogfood_harness(
    home,
    intake_root,
    records: list,
    *,
    skills_root=None,
    seal_path=None,
    credentials_config=None,
) -> dict:
    """Thinnest viable dogfood path: sanitize → enqueue → transport → metrics.

    ``records`` are local journal-shaped dicts (or already-clean export dicts).
    Does not make public marketing claims. Measures export yield only.
    """
    ensure_intake_layout(intake_root)
    if credentials_config is None:
        credentials_config = default_transport_config(intake_root=intake_root)

    cfg_problems = validate_recipient_config(credentials_config)
    if cfg_problems:
        return {
            "ok": False,
            "reason": "credentials-invalid:" + ",".join(cfg_problems),
            "yield": measure_export_yield(attempted=0, accepted=0),
            "deliveries": [],
        }

    attempted = 0
    accepted = 0
    deliveries = []
    enqueued = 0

    for rec in records or []:
        attempted += 1
        # Prefer full export path when it looks like a journal record.
        if isinstance(rec, dict) and (
            "outcome" in rec and "skill_id" in rec
        ):
            exp = fb.try_export_journal_record(
                home,
                rec,
                skills_root=skills_root,
                seal_path=seal_path,
            )
            if exp.get("enqueued"):
                enqueued += 1
            elif exp.get("export_record"):
                # already clean but enqueue failed — try direct deliver
                d = deliver_to_intake(
                    intake_root,
                    exp["export_record"],
                    credentials_config=credentials_config,
                )
                deliveries.append(d)
                if d.get("accepted"):
                    accepted += 1
            else:
                deliveries.append({
                    "accepted": False,
                    "reason": exp.get("reason") or "export_failed",
                })
        else:
            d = deliver_to_intake(
                intake_root,
                rec if isinstance(rec, dict) else {},
                credentials_config=credentials_config,
            )
            deliveries.append(d)
            if d.get("accepted"):
                accepted += 1

    # Drain anything enqueued into partitioned intake.
    if enqueued:
        drain = transport_drain(
            home,
            intake_root,
            credentials_config=credentials_config,
            skills_root=skills_root,
            seal_path=seal_path,
        )
        transmitted = 0
        if drain.get("drain"):
            transmitted = int(drain["drain"].get("transmitted") or 0)
        accepted += transmitted

    y = measure_export_yield(attempted=attempted, accepted=accepted)
    return {
        "ok": True,
        "reason": None,
        "enqueued": enqueued,
        "deliveries": deliveries,
        "partitions": partition_metrics(intake_root),
        "pull_review": pull_review_stub(intake_root),
        "yield": y,
        "policy": FEEDBACK_IS_NOT_CODE_CONTRIBUTION,
        "auto_merge_allowed": auto_merge_allowed(),
    }
