"""Opt-in fail-closed skill-friction feedback (W6).

Extension point ``ext:feedback_sanitizer`` — builds a **sanitized subset** of
per-skill journal friction for an optional global improvement feed.

Hard rules (NS 9; R11/R13/R14):

* **Opt-in only** — no export unless local consent is true
* **Allowlist fields only** — unknown keys stripped; free-text notes never export
* **Fail closed** — PII / absolute path / secret / session-purpose hit → drop
* **Untagged records dropped** — missing skill_id or skill_version → drop
* **De-identified install key** — high-entropy random UUID on opt-in only;
  never derived from email/username/machine/path
* **Local full journals stay local** — never retro-uploaded on later opt-in
* **Local offline queue** — drain only while consent still valid; mid-queue
  opt-out stops all further sends
* **Immutability seal gate** — forked skill trees cannot export
* Schema-versioned semver contracts with major-forward-compat checks

Transport to John's intake is **W7** (``share_feedback_intake``) — this
module only sanitizes, keys, and queues. Stdlib only.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import time
import uuid
from pathlib import Path

import share_home_config as home_cfg
import share_skill_journal as sjournal
import share_skill_seal as seal

# ── Contract identity (semver) ───────────────────────────────────────────────

FEEDBACK_SCHEMA = "share-skill-friction/v1"
FEEDBACK_SCHEMA_VERSION = "1.0.0"
FEEDBACK_SCHEMA_MAJOR = 1

INSTALL_KEY_SCHEMA = "share-install-key/v1"
INSTALL_KEY_FILENAME = "install_key.json"
QUEUE_DIRNAME = "feedback_queue"
QUEUE_META_FILENAME = "queue_meta.json"
# Mirrors share_onboard.FEEDBACK_PREF_FILENAME — kept local to avoid import cycle.
FEEDBACK_CONSENT_FILENAME = "feedback_consent.json"

CONTINUITY_BREAK_WARNING = (
    "Rotating or wiping the install key breaks continuity: prior friction "
    "reports cannot be linked to this install anymore. That is intentional "
    "and fine."
)

# ── Closed enums (export allowlist values) ───────────────────────────────────

# Outcomes eligible for the friction feed (not "worked").
EXPORT_OUTCOMES = frozenset({"friction", "failed", "refused", "workaround"})

DURATION_BANDS = frozenset({
    "lt_1m", "1_5m", "5_30m", "30m_2h", "gt_2h", "unknown",
})
COMPLEXITY_BANDS = frozenset({
    "trivial", "small", "medium", "large", "unknown",
})
OS_CLASSES = frozenset({
    "windows", "macos", "linux", "other", "unknown",
})
MODEL_FAMILY_SEATS = frozenset({
    "claude", "gemini", "grok", "openai", "unknown",
})
WORKAROUND_CODES = frozenset({
    "retry",
    "seat_switch",
    "manual_fix",
    "skip_step",
    "reduce_scope",
    "reread_docs",
    "other",
    "none",
})

# Short bounded free-ish tokens (still scanned; max length enforced).
_MAX_TOKEN_LEN = 24
_MAX_TOKEN_COUNT = 4
_TOKEN_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,23}$")

# Allowlisted keys on a sanitizer-clean export record (nothing else ships).
EXPORT_ALLOWLIST = frozenset({
    "schema",
    "schema_version",
    "export_id",
    "skill_id",
    "skill_version",
    "install_key",
    "outcome",
    "structural_failure_codes",
    "duration_band",
    "complexity_band",
    "os_class",
    "model_family_seats",
    "workaround_codes",
    "workaround_tokens",
    "source_record_id",  # opaque journal record_id only if clean enum-like
})

# Fields copied from a local journal into a candidate export (pre-sanitize).
_JOURNAL_FRICTION_KEYS = (
    "skill_id",
    "skill_version",
    "outcome",
    "structural_failure_codes",
    "duration_band",
    "complexity_band",
    "os_class",
    "model_family_seats",
    "workaround_codes",
    "workaround_tokens",
    "record_id",
)

# ── Detectors (fail-closed on any hit) ───────────────────────────────────────

_EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"
)
_WIN_ABS_PATH_RE = re.compile(
    r"[A-Za-z]:\\(?:Users|home|dev|Program Files|Windows)(?:\\[^\s\"'<>|]*)?",
    re.IGNORECASE,
)
_WIN_USERS_RE = re.compile(r"[A-Za-z]:\\Users\\", re.IGNORECASE)
_POSIX_ABS_HOME_RE = re.compile(
    r"/(?:Users|home)/[^/\s\"'<>|]+(?:/[^\s\"'<>|]*)?"
)
_POSIX_ABS_DEV_RE = re.compile(r"/(?:Users|home|opt|var|tmp)/[^\s\"'<>|]+")
# Generic absolute path shapes (drive-rooted or root-rooted with depth).
_ABS_PATH_GENERIC_RE = re.compile(
    r"(?:"
    r"[A-Za-z]:\\[^\s\"'<>|]+"
    r"|/(?:Users|home|usr|var|opt|tmp|etc)/[^\s\"'<>|]+"
    r")"
)
_SECRET_SHAPE_RE = re.compile(
    r"""(?x)
    (?:
        \bAKIA[0-9A-Z]{16}\b
      | \beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+
      | \bsk-[A-Za-z0-9]{16,}\b
      | \bghp_[A-Za-z0-9]{20,}\b
      | \bgho_[A-Za-z0-9]{20,}\b
      | Bearer\s+[A-Za-z0-9._\-]{24,}
    )
    """
)
_GENERIC_ENTROPY_RE = re.compile(
    r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{40,}(?![A-Za-z0-9+/])"
)

# Session-purpose / prompt / work-product prose detectors.
_SESSION_PURPOSE_RES = (
    re.compile(
        r"\b(?:working on|building|implementing|debugging|fixing)\b.{0,40}"
        r"\b(?:project|feature|bug|app|paper|thesis|client|customer)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:user(?:'s)?\s+)?(?:prompt|system prompt|session (?:goal|purpose|"
        r"content)|proprietary|confidential|trade secret)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:my (?:codebase|repo|company|employer|client)|what I was "
        r"(?:doing|building|working on))\b",
        re.IGNORECASE,
    ),
)

# skill_id / skill_version must stay opaque identifiers (no paths/PII).
_SKILL_ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9._\-]{0,63}$")
_SKILL_VER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+\-]{0,63}$")
_OPAQUE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,63}$")
_INSTALL_KEY_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_SEMVER_RE = re.compile(r"^([0-9]+)\.([0-9]+)\.([0-9]+)([+-][0-9A-Za-z.-]+)?$")


class FeedbackError(Exception):
    """Raised when feedback key/queue ops refuse (not used for soft drops)."""

    def __init__(self, reason, message=None):
        self.reason = reason
        self.message = message or ("feedback refused: %s" % reason)
        super().__init__(self.message)


# ── Paths under recipient home ───────────────────────────────────────────────

def _gov_dir(home) -> Path:
    return Path(home) / home_cfg.GOVERNANCE_SUBDIR


def install_key_path(home) -> Path:
    return _gov_dir(home) / INSTALL_KEY_FILENAME


def queue_dir(home) -> Path:
    return _gov_dir(home) / QUEUE_DIRNAME


# ── De-identified install key ────────────────────────────────────────────────

def mint_install_key() -> str:
    """High-entropy random UUID string — never derived from identity material."""
    return str(uuid.uuid4())


def load_install_key(home) -> str | None:
    path = install_key_path(home)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(doc, dict):
        return None
    key = doc.get("install_key")
    if isinstance(key, str) and _INSTALL_KEY_RE.match(key):
        return key
    return None


def write_install_key(home, key: str, *, rotated: bool = False) -> Path:
    """Persist install key doc (key must already be a random UUID)."""
    if not isinstance(key, str) or not _INSTALL_KEY_RE.match(key):
        raise FeedbackError("install-key-not-uuid")
    path = install_key_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": INSTALL_KEY_SCHEMA,
        "schema_version": 1,
        "install_key": key,
        "minted_ts": time.time(),
        "rotated": bool(rotated),
        "derivation": "uuid4-random",
        "never_from": ["email", "username", "machine", "path"],
    }
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def ensure_install_key(home) -> str:
    """Return existing key or mint a new one (opt-in path only)."""
    existing = load_install_key(home)
    if existing:
        return existing
    key = mint_install_key()
    write_install_key(home, key, rotated=False)
    return key


def wipe_install_key(home) -> bool:
    """Remove the install key file. Returns True if a file was removed."""
    path = install_key_path(home)
    if not path.is_file():
        return False
    try:
        path.unlink()
    except OSError:
        return False
    return True


def rotate_install_key(home) -> dict:
    """Mint a new key (continuity break). Returns key + warning text."""
    key = mint_install_key()
    write_install_key(home, key, rotated=True)
    return {
        "install_key": key,
        "continuity_break": True,
        "warning": CONTINUITY_BREAK_WARNING,
    }


# ── Consent helpers ──────────────────────────────────────────────────────────

def feedback_consent_path(home) -> Path:
    return _gov_dir(home) / FEEDBACK_CONSENT_FILENAME


def load_consent_doc(home) -> dict:
    """Read local feedback consent (fail-closed default False)."""
    path = feedback_consent_path(home)
    if not path.is_file():
        return {"opted_in": False, "missing": True}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"opted_in": False, "missing": True, "corrupt": True}
    if not isinstance(doc, dict):
        return {"opted_in": False, "missing": True}
    doc.setdefault("opted_in", False)
    doc["missing"] = False
    return doc


def write_consent_doc(home, opted_in: bool, *, install_key_present: bool = False) -> Path:
    """Persist consent preference (used by set_feedback_opt_in; onboard may also write)."""
    path = feedback_consent_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema": "share-feedback-consent/v1",
        "schema_version": 1,
        "opted_in": bool(opted_in),
        "default_was": False,
        "readiness_gate": False,
        "install_key_present": bool(install_key_present),
    }
    if not opted_in and not install_key_present:
        doc["install_key_wiped"] = True
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def consent_valid(home) -> bool:
    """True only when local preference is explicitly opted in."""
    doc = load_consent_doc(home)
    return bool(doc.get("opted_in") is True)


def feedback_export_prerequisites(
    home,
    skills_root=None,
    *,
    seal_path=None,
) -> dict:
    """Gate check before any enqueue/drain send.

    Returns ``{ok, reasons, install_key, consent, seal_ok}``.
    """
    reasons = []
    consented = consent_valid(home)
    if not consented:
        reasons.append("consent_off")
    key = load_install_key(home)
    if not key:
        reasons.append("install_key_missing")
    seal_ok = True
    if skills_root is not None:
        seal_ok = seal.feedback_export_allowed(
            skills_root, seal_path=seal_path
        )
        if not seal_ok:
            reasons.append("skill_tree_forked")
    return {
        "ok": not reasons,
        "reasons": reasons,
        "install_key": key,
        "consent": consented,
        "seal_ok": seal_ok,
    }


# ── Schema version forward-compat ────────────────────────────────────────────

def parse_schema_version(sv) -> tuple | None:
    if not isinstance(sv, str):
        return None
    m = _SEMVER_RE.match(sv)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def schema_version_acceptable(sv) -> bool:
    """Accept same major, any minor/patch ≥ known (forward-compat within major).

    Unknown major → refuse (fail closed). Lower major → refuse.
    """
    parsed = parse_schema_version(sv)
    if parsed is None:
        return False
    major, _minor, _patch = parsed
    return major == FEEDBACK_SCHEMA_MAJOR


# ── Friction candidate build (journal → export shape) ────────────────────────

def _norm_os_class(value) -> str:
    if value in OS_CLASSES:
        return value
    return "unknown"


def _norm_band(value, allowed) -> str:
    if value in allowed:
        return value
    return "unknown"


def build_friction_candidate(
    journal_record: dict,
    *,
    install_key: str | None = None,
    os_class: str | None = None,
) -> dict | None:
    """Map a local journal record to a pre-sanitize export candidate.

    Returns None for untagged / non-exportable outcomes. Never includes
    ``notes`` or other free-text journal fields.
    """
    if not isinstance(journal_record, dict):
        return None
    skill_id = journal_record.get("skill_id")
    skill_version = journal_record.get("skill_version")
    if not isinstance(skill_id, str) or not skill_id.strip():
        return None
    if not isinstance(skill_version, str) or not skill_version.strip():
        return None
    outcome = journal_record.get("outcome")
    if outcome not in EXPORT_OUTCOMES:
        return None

    codes = journal_record.get("structural_failure_codes")
    if not isinstance(codes, list):
        codes = []
    codes = [c for c in codes if c in sjournal.STRUCTURAL_FAILURE_CODES]

    seats = journal_record.get("model_family_seats")
    if not isinstance(seats, list):
        seats = []
    seats = [s for s in seats if s in MODEL_FAMILY_SEATS]

    wcodes = journal_record.get("workaround_codes")
    if not isinstance(wcodes, list):
        wcodes = []
    wcodes = [c for c in wcodes if c in WORKAROUND_CODES]

    wtokens = journal_record.get("workaround_tokens")
    if not isinstance(wtokens, list):
        wtokens = []
    wtokens = [
        t for t in wtokens
        if isinstance(t, str) and _TOKEN_RE.match(t)
    ][:_MAX_TOKEN_COUNT]

    os_val = os_class if os_class is not None else journal_record.get("os_class")
    if os_val not in OS_CLASSES:
        # Best-effort host OS class — never a hostname/path.
        plat = (os.name or "").lower()
        if plat == "nt":
            os_val = "windows"
        elif plat == "posix":
            # mac vs linux not distinguished without platform; keep unknown-safe.
            os_val = "unknown"
        else:
            os_val = "unknown"

    cand = {
        "schema": FEEDBACK_SCHEMA,
        "schema_version": FEEDBACK_SCHEMA_VERSION,
        "export_id": "ex-" + uuid.uuid4().hex[:12],
        "skill_id": skill_id.strip(),
        "skill_version": skill_version.strip(),
        "outcome": outcome,
        "structural_failure_codes": codes,
        "duration_band": _norm_band(
            journal_record.get("duration_band"), DURATION_BANDS
        ),
        "complexity_band": _norm_band(
            journal_record.get("complexity_band"), COMPLEXITY_BANDS
        ),
        "os_class": _norm_os_class(os_val),
        "model_family_seats": seats,
        "workaround_codes": wcodes or ["none"],
        "workaround_tokens": wtokens,
    }
    if install_key:
        cand["install_key"] = install_key
    rid = journal_record.get("record_id")
    if isinstance(rid, str) and _OPAQUE_ID_RE.match(rid):
        cand["source_record_id"] = rid
    return cand


# ── String detectors ─────────────────────────────────────────────────────────

def _looks_high_entropy(s: str) -> bool:
    has_lower = any(c.islower() for c in s)
    has_upper = any(c.isupper() for c in s)
    has_digit = any(c.isdigit() for c in s)
    if sum((has_lower, has_upper, has_digit)) < 2:
        return False
    return len(set(s)) >= 12


def detect_string_leaks(text: str) -> list:
    """Return detector hit codes for one string (empty = clean)."""
    if not isinstance(text, str) or not text:
        return []
    hits = []
    if _EMAIL_RE.search(text):
        hits.append("pii_email")
    if (
        _WIN_ABS_PATH_RE.search(text)
        or _WIN_USERS_RE.search(text)
        or _POSIX_ABS_HOME_RE.search(text)
        or _ABS_PATH_GENERIC_RE.search(text)
    ):
        hits.append("absolute_path")
    if _SECRET_SHAPE_RE.search(text):
        hits.append("secret_shape")
    for m in _GENERIC_ENTROPY_RE.finditer(text):
        if _looks_high_entropy(m.group(0)):
            hits.append("high_entropy_secret")
            break
    for rx in _SESSION_PURPOSE_RES:
        if rx.search(text):
            hits.append("session_purpose")
            break
    return hits


def _walk_strings(obj, path="$"):
    """Yield (path, string) for every string leaf."""
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _walk_strings(v, "%s.%s" % (path, k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _walk_strings(v, "%s[%d]" % (path, i))


# ── Sanitizer (allowlist + fail-closed) ──────────────────────────────────────

def validate_export_record(doc) -> list:
    """Structural problems for a candidate/clean export (empty = structurally ok)."""
    if not isinstance(doc, dict):
        return ["export-not-an-object"]
    problems = []
    for key in (
        "schema",
        "schema_version",
        "skill_id",
        "skill_version",
        "outcome",
        "structural_failure_codes",
    ):
        if key not in doc:
            problems.append("missing-key:%s" % key)
    if doc.get("schema") != FEEDBACK_SCHEMA:
        problems.append("schema-mismatch:%r" % (doc.get("schema"),))
    if not schema_version_acceptable(doc.get("schema_version")):
        problems.append(
            "schema_version-not-acceptable:%r" % (doc.get("schema_version"),)
        )
    sid = doc.get("skill_id")
    if not isinstance(sid, str) or not _SKILL_ID_RE.match(sid or ""):
        problems.append("skill_id-invalid")
    sver = doc.get("skill_version")
    if not isinstance(sver, str) or not _SKILL_VER_RE.match(sver or ""):
        problems.append("skill_version-invalid")
    if doc.get("outcome") not in EXPORT_OUTCOMES:
        problems.append("outcome-not-exportable:%r" % (doc.get("outcome"),))
    codes = doc.get("structural_failure_codes")
    if not isinstance(codes, list):
        problems.append("structural_failure_codes-not-a-list")
    else:
        for c in codes:
            if c not in sjournal.STRUCTURAL_FAILURE_CODES:
                problems.append("structural_failure_code-out-of-enum:%r" % (c,))
    if "duration_band" in doc and doc["duration_band"] not in DURATION_BANDS:
        problems.append("duration_band-out-of-enum")
    if "complexity_band" in doc and doc["complexity_band"] not in COMPLEXITY_BANDS:
        problems.append("complexity_band-out-of-enum")
    if "os_class" in doc and doc["os_class"] not in OS_CLASSES:
        problems.append("os_class-out-of-enum")
    if "model_family_seats" in doc:
        seats = doc["model_family_seats"]
        if not isinstance(seats, list):
            problems.append("model_family_seats-not-a-list")
        else:
            for s in seats:
                if s not in MODEL_FAMILY_SEATS:
                    problems.append("model_family_seat-out-of-enum:%r" % (s,))
    if "workaround_codes" in doc:
        wcodes = doc["workaround_codes"]
        if not isinstance(wcodes, list):
            problems.append("workaround_codes-not-a-list")
        else:
            for c in wcodes:
                if c not in WORKAROUND_CODES:
                    problems.append("workaround_code-out-of-enum:%r" % (c,))
    if "workaround_tokens" in doc:
        wtokens = doc["workaround_tokens"]
        if not isinstance(wtokens, list):
            problems.append("workaround_tokens-not-a-list")
        elif len(wtokens) > _MAX_TOKEN_COUNT:
            problems.append("workaround_tokens-too-many")
        else:
            for t in wtokens:
                if not isinstance(t, str) or not _TOKEN_RE.match(t):
                    problems.append("workaround_token-invalid:%r" % (t,))
    if "install_key" in doc:
        ik = doc["install_key"]
        if not isinstance(ik, str) or not _INSTALL_KEY_RE.match(ik):
            problems.append("install_key-not-uuid")
    if "export_id" in doc and not isinstance(doc["export_id"], str):
        problems.append("export_id-not-a-string")
    if "source_record_id" in doc:
        rid = doc["source_record_id"]
        if not isinstance(rid, str) or not _OPAQUE_ID_RE.match(rid):
            problems.append("source_record_id-invalid")
    # Unknown keys are NOT structural errors here — sanitizer strips them.
    return problems


def sanitize_for_export(candidate: dict) -> dict | None:
    """Allowlist + detector gate. Returns clean record or None (hard drop).

    Fail closed: any detector hit, structural problem, or untagged identity
    yields None. Never returns a partial dirty payload.
    """
    if not isinstance(candidate, dict):
        return None

    # Untagged / non-exportable outcomes
    if not candidate.get("skill_id") or not candidate.get("skill_version"):
        return None
    if candidate.get("outcome") not in EXPORT_OUTCOMES:
        return None

    # Allowlist projection only
    clean = {}
    for key in EXPORT_ALLOWLIST:
        if key in candidate:
            clean[key] = candidate[key]

    # Force schema identity (never trust caller free-text schema)
    clean["schema"] = FEEDBACK_SCHEMA
    if "schema_version" not in clean:
        clean["schema_version"] = FEEDBACK_SCHEMA_VERSION
    if not schema_version_acceptable(clean.get("schema_version")):
        return None
    # Normalize to the known contract version string for export stability.
    clean["schema_version"] = FEEDBACK_SCHEMA_VERSION

    if "export_id" not in clean or not isinstance(clean.get("export_id"), str):
        clean["export_id"] = "ex-" + uuid.uuid4().hex[:12]

    # Defaults for optional enum fields
    clean.setdefault("duration_band", "unknown")
    clean.setdefault("complexity_band", "unknown")
    clean.setdefault("os_class", "unknown")
    clean.setdefault("model_family_seats", [])
    clean.setdefault("workaround_codes", ["none"])
    clean.setdefault("workaround_tokens", [])
    clean.setdefault("structural_failure_codes", [])

    # Structural validation
    problems = validate_export_record(clean)
    if problems:
        return None

    # Detector pass on every string leaf
    for _path, text in _walk_strings(clean):
        if detect_string_leaks(text):
            return None

    # Final allowlist re-projection (no extras)
    out = {k: clean[k] for k in EXPORT_ALLOWLIST if k in clean}
    # Prove clean: re-validate
    if validate_export_record(out):
        return None
    for _path, text in _walk_strings(out):
        if detect_string_leaks(text):
            return None
    return out


# ── Local offline queue ──────────────────────────────────────────────────────

def _queue_encrypt_key_bytes(install_key: str, nonce: bytes) -> bytes:
    """Derive a stream key from install key + nonce (optional at-rest wrap)."""
    return hashlib.pbkdf2_hmac(
        "sha256",
        install_key.encode("utf-8"),
        nonce,
        100_000,
        dklen=32,
    )


def _xor_bytes(data: bytes, key: bytes) -> bytes:
    if not key:
        return data
    out = bytearray(len(data))
    for i, b in enumerate(data):
        out[i] = b ^ key[i % len(key)]
    return bytes(out)


def _encode_queue_payload(record: dict, *, encrypt: bool, install_key: str) -> dict:
    raw = json.dumps(record, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if not encrypt:
        return {
            "encrypted": False,
            "payload": record,
        }
    nonce = secrets.token_bytes(16)
    key = _queue_encrypt_key_bytes(install_key, nonce)
    cipher = _xor_bytes(raw, key)
    return {
        "encrypted": True,
        "nonce_b64": base64.b64encode(nonce).decode("ascii"),
        "ciphertext_b64": base64.b64encode(cipher).decode("ascii"),
    }


def _decode_queue_payload(envelope: dict, *, install_key: str | None) -> dict | None:
    if not isinstance(envelope, dict):
        return None
    if not envelope.get("encrypted"):
        payload = envelope.get("payload")
        return payload if isinstance(payload, dict) else None
    if not install_key:
        return None
    try:
        nonce = base64.b64decode(envelope["nonce_b64"])
        cipher = base64.b64decode(envelope["ciphertext_b64"])
    except (KeyError, ValueError, TypeError):
        return None
    key = _queue_encrypt_key_bytes(install_key, nonce)
    raw = _xor_bytes(cipher, key)
    try:
        doc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def enqueue_export(
    home,
    clean_record: dict,
    *,
    encrypt_at_rest: bool = False,
) -> Path | None:
    """Append a sanitizer-clean record to the local offline queue.

    Returns the queue file path, or None if consent/key missing (fail closed).
    Does **not** re-check seal (caller should); does re-check consent + key.
    """
    if not consent_valid(home):
        return None
    key = load_install_key(home)
    if not key:
        return None
    # Record must already be clean — re-sanitize fail-closed.
    clean = sanitize_for_export(clean_record)
    if clean is None:
        return None
    # Stamp install key from local store (never trust caller identity key).
    clean["install_key"] = key
    # Re-prove after stamp
    clean = sanitize_for_export(clean)
    if clean is None:
        return None

    qdir = queue_dir(home)
    qdir.mkdir(parents=True, exist_ok=True)
    export_id = clean.get("export_id") or ("ex-" + uuid.uuid4().hex[:12])
    path = qdir / ("%s.json" % export_id)
    envelope = {
        "schema": "share-feedback-queue-entry/v1",
        "schema_version": 1,
        "enqueued_ts": time.time(),
        "export_id": export_id,
        "skill_id": clean.get("skill_id"),
    }
    envelope.update(
        _encode_queue_payload(
            clean, encrypt=encrypt_at_rest, install_key=key
        )
    )
    path.write_text(
        json.dumps(envelope, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def list_queue_entries(home) -> list:
    """Load queue envelopes (payload may still be encrypted)."""
    qdir = queue_dir(home)
    if not qdir.is_dir():
        return []
    out = []
    for path in sorted(qdir.glob("*.json")):
        if path.name == QUEUE_META_FILENAME:
            continue
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(doc, dict):
            doc["_path"] = str(path)
            out.append(doc)
    return out


def clear_queue(home) -> int:
    """Delete all queue entry files. Returns count removed."""
    qdir = queue_dir(home)
    if not qdir.is_dir():
        return 0
    n = 0
    for path in qdir.glob("*.json"):
        if path.name == QUEUE_META_FILENAME:
            continue
        try:
            path.unlink()
            n += 1
        except OSError:
            continue
    return n


def drain_queue(
    home,
    *,
    transmitter=None,
    encrypt_at_rest: bool = False,
) -> dict:
    """Drain local queue to ``transmitter(record) -> bool``.

    **Consent gate (R11):** if consent is off at start or flips mid-drain,
    **no** further records are transmitted. Opt-out never flushes remaining
    payloads to the network.

    ``transmitter`` is optional — when None, this is a dry check that reports
    what *would* send while consent is valid (does not delete).

    Returns::

        {
          "sent": [export_id, ...],
          "held": [export_id, ...],   # not sent (consent off / dirty / fail)
          "transmitted": int,
          "consent_valid": bool,
          "reason": str|None,
        }
    """
    result = {
        "sent": [],
        "held": [],
        "transmitted": 0,
        "consent_valid": consent_valid(home),
        "reason": None,
    }
    if not result["consent_valid"]:
        result["reason"] = "consent_off"
        # Do not transmit anything; leave queue on disk (caller may wipe).
        for env in list_queue_entries(home):
            result["held"].append(env.get("export_id") or env.get("_path"))
        return result

    key = load_install_key(home)
    if not key:
        result["reason"] = "install_key_missing"
        result["consent_valid"] = consent_valid(home)
        for env in list_queue_entries(home):
            result["held"].append(env.get("export_id") or env.get("_path"))
        return result

    entries = list_queue_entries(home)
    for idx, envelope in enumerate(entries):
        eid = envelope.get("export_id") or envelope.get("_path")
        # Re-check consent every entry (mid-queue opt-out → never send rest).
        if not consent_valid(home):
            result["consent_valid"] = False
            result["reason"] = "consent_revoked_mid_drain"
            for env2 in entries[idx:]:
                eid2 = env2.get("export_id") or env2.get("_path")
                if eid2 not in result["held"] and eid2 not in result["sent"]:
                    result["held"].append(eid2)
            break

        payload = _decode_queue_payload(envelope, install_key=key)
        if payload is None:
            result["held"].append(eid or "undecodable")
            continue
        clean = sanitize_for_export(payload)
        if clean is None:
            result["held"].append(eid or "dirty")
            # Drop dirty from queue (fail closed — do not send).
            _unlink_queue_path(envelope.get("_path"))
            continue

        if transmitter is None:
            # Dry-run: count as held (not transmitted), leave on disk.
            result["held"].append(clean.get("export_id"))
            continue

        try:
            ok = bool(transmitter(clean))
        except Exception:
            ok = False
        if ok:
            result["sent"].append(clean.get("export_id"))
            result["transmitted"] += 1
            _unlink_queue_path(envelope.get("_path"))
        else:
            result["held"].append(clean.get("export_id"))

    return result


def _unlink_queue_path(path_str) -> None:
    if not path_str:
        return
    try:
        Path(path_str).unlink()
    except OSError:
        pass


# ── High-level export API ────────────────────────────────────────────────────

def try_export_journal_record(
    home,
    journal_record: dict,
    *,
    skills_root=None,
    seal_path=None,
    encrypt_at_rest: bool = False,
    os_class: str | None = None,
) -> dict:
    """Build → sanitize → enqueue one journal record if gates pass.

    Local full journal content (e.g. ``notes``) is **never** included.
    Returns a result dict describing drop/enqueue — never raises on soft drop.
    """
    result = {
        "exported": False,
        "enqueued": False,
        "dropped": True,
        "reason": None,
        "export_record": None,
        "queue_path": None,
    }
    gates = feedback_export_prerequisites(
        home, skills_root, seal_path=seal_path
    )
    if not gates["ok"]:
        result["reason"] = ",".join(gates["reasons"])
        return result

    cand = build_friction_candidate(
        journal_record,
        install_key=gates["install_key"],
        os_class=os_class,
    )
    if cand is None:
        result["reason"] = "untagged_or_non_exportable"
        return result

    # Never put notes / free text into candidate (defense in depth)
    if "notes" in cand:
        del cand["notes"]

    clean = sanitize_for_export(cand)
    if clean is None:
        result["reason"] = "sanitizer_drop"
        return result

    path = enqueue_export(
        home, clean, encrypt_at_rest=encrypt_at_rest
    )
    if path is None:
        result["reason"] = "enqueue_refused"
        return result

    result["exported"] = True
    result["enqueued"] = True
    result["dropped"] = False
    result["reason"] = None
    result["export_record"] = clean
    result["queue_path"] = str(path)
    return result


def export_payload_contains_full_journal(export_record: dict) -> bool:
    """True if an export payload illegitimately carries full-journal fields."""
    if not isinstance(export_record, dict):
        return True
    forbidden = {
        "notes", "prompt", "session", "transcript", "messages",
        "full_journal", "journal", "purpose", "user_content",
    }
    return bool(forbidden.intersection(export_record.keys()))


def set_feedback_opt_in(
    home,
    opted_in: bool,
    *,
    wipe_key_on_opt_out: bool = False,
    clear_queue_on_opt_out: bool = False,
) -> dict:
    """Opt in (mint key) or opt out (stop sends; optional key wipe / queue clear).

    Does **not** retro-export prior local journals on opt-in.
    """
    if opted_in:
        key = ensure_install_key(home)
        path = write_consent_doc(home, True, install_key_present=True)
        return {
            "opted_in": True,
            "install_key_present": True,
            "install_key": key,
            "consent_path": str(path),
            "retro_upload": False,
            "warning": None,
        }
    wiped = False
    if wipe_key_on_opt_out:
        wiped = wipe_install_key(home)
    cleared = 0
    if clear_queue_on_opt_out:
        cleared = clear_queue(home)
    key_present = load_install_key(home) is not None
    path = write_consent_doc(
        home, False, install_key_present=key_present
    )
    return {
        "opted_in": False,
        "install_key_present": key_present,
        "install_key_wiped": wiped,
        "queue_cleared": cleared,
        "consent_path": str(path),
        "warning": CONTINUITY_BREAK_WARNING if wiped else None,
    }
