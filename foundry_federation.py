"""Wave 22.5 — Foundry Steward & Librarian Federation, 4-Stage Aegis Quarantine & 3D Lorentz-Procrustes Alignment (stdlib only).

Implements:
- ``FoundryStewardFederation``:
  1. ``export_skill_bundle`` (``anchor.foundry.federation.v1`` with ``SKILL.md``, ``ANVIL-MAP.json``,
     ``knowledge-map.json``, 3D Poincaré/Lorentz coordinates, tools list, and SHA-256 Merkle root).
  2. ``receive_into_quarantine`` staging into ``.anchor/foundry_quarantine/<skill_id>@<sha256>/``.
  3. ``evaluate_quarantined_skill`` running the 4-Stage Quarantine Gate:
     - Stage 1: Aegis AST & Prompt-Directive Security Scan (CWE-78/94/502 sinks + prompt injection).
     - Stage 2: Anvil Structural & Null-Space Verification.
     - Stage 3: Hermetic Test & Merkle Integrity Gate.
     - Stage 4: Gandalf Differential Scorecard + HT-6 Human Promotion Escalation.
  4. ``export_distilled_lessons`` & ``import_distilled_lessons`` (``anchor.librarian.lesson.v1`` with
     idempotent per-DID ``provenance_ledger`` so circular A -> B -> A sharing never double-counts credit).
  5. ``lorentz_procrustes_align`` aligning peer 3D Lorentz coordinates L^3_kappa onto the local
     manifold frame while preserving -<Lambda x, Lambda x>_L = 1/kappa.
"""
from __future__ import annotations

import ast
import base64
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
from typing import Any

import anchor_agent_protocol as aap
import cockpit_baton_and_tiers as cbt
import paths


FEDERATION_BUNDLE_SCHEMA = "anchor.foundry.federation.v1"
LIBRARIAN_LESSON_SCHEMA = "anchor.librarian.lesson.v1"
GWL_BINARY_SEAL_SCHEMA = "anchor.gwl.binary.seal.v1"
GWL_HUB_ISSUER_DID = "did:anchor:ghost-world-labs-hub"
_GWL_SEAL_SIGNING_DOMAIN = b"ghost-world-labs-reproducible-binary-seal-v1-hmac"

ZERO_BINARY_LAW = (
    "ZERO_BINARY_LAW: Peer and collaborator skill/tool submissions are strictly plain-text "
    "source-only. Any compiled binary extension, binary magic-byte header (PE/ELF/Mach-O/Wasm/JVM), "
    "or spyware/obfuscated dropper pattern is rejected fail-closed at Stage 0 unless vetted, "
    "reproducibly compiled in an airgapped builder, and cryptographically sealed by Ghost World Labs "
    "(anchor.gwl.binary.seal.v1)."
)

FORBIDDEN_BINARY_EXTENSIONS: frozenset[str] = frozenset({
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".pyd",
    ".pyc",
    ".pyo",
    ".wasm",
    ".bin",
    ".dat",
    ".jar",
    ".class",
    ".whl",
    ".egg",
    ".scr",
    ".msi",
    ".com",
    ".sys",
    ".drv",
    ".ocx",
    ".ko",
    ".o",
    ".a",
    ".lib",
})

BINARY_MAGIC_SIGNATURES: dict[bytes, str] = {
    b"MZ": "windows_pe_executable",
    b"\x7fELF": "linux_elf_binary",
    b"\xfe\xed\xfa\xce": "mach_o_32_be",
    b"\xfe\xed\xfa\xcf": "mach_o_64_be",
    b"\xce\xfa\xed\xfe": "mach_o_32_le",
    b"\xcf\xfa\xed\xfe": "mach_o_64_le",
    b"\xca\xfe\xba\xbe": "mach_o_universal_or_java_class",
    b"\x00asm": "webassembly_binary",
}

SPYWARE_BACKDOOR_PATTERNS: tuple[dict[str, Any], ...] = (
    {
        "id": "SPYWARE-KEYLOGGER-WIN32",
        "category": "keylogger",
        "pattern": re.compile(r"\b(?:GetAsyncKeyState|SetWindowsHookEx|GetKeyState|CallNextHookEx)\b"),
        "reason": "Win32 keystroke hook / keylogger API detected",
    },
    {
        "id": "SPYWARE-KEYLOGGER-PY",
        "category": "keylogger",
        "pattern": re.compile(r"\b(?:pynput\.keyboard|keyboard\.on_press|keyboard\.hook)\b"),
        "reason": "Python keyboard interceptor / keylogger library detected",
    },
    {
        "id": "SPYWARE-CLIPBOARD-SCREEN",
        "category": "clipboard_or_screen_capture",
        "pattern": re.compile(
            r"\b(?:OpenClipboard|GetClipboardData|pyperclip\.paste|ImageGrab\.grab|pyautogui\.screenshot|mss\.mss)\b"
        ),
        "reason": "Covert clipboard or screen capture spyware primitive detected",
    },
    {
        "id": "SPYWARE-CREDENTIAL-THEFT",
        "category": "credential_theft",
        "pattern": re.compile(
            r"(?:CryptUnprotectData|win32crypt|Login\s+Data|lsass\.exe|\.ssh/id_rsa|mimikatz)",
            re.IGNORECASE,
        ),
        "reason": "Credential store or browser/OS secret harvesting primitive detected",
    },
    {
        "id": "SPYWARE-OBFUSCATED-DROPPER",
        "category": "obfuscated_dropper",
        "pattern": re.compile(
            r"\b(?:exec|eval|compile)\s*\(\s*(?:base64\.b64decode|zlib\.decompress| marshal\.loads|codecs\.decode)\s*\(",
            re.IGNORECASE,
        ),
        "reason": "Hidden base64/zlib obfuscated code dropper detected",
    },
    {
        "id": "SPYWARE-RAW-SOCKET-C2",
        "category": "c2_beacon_or_raw_socket",
        "pattern": re.compile(r"(?:\bSOCK_RAW\b|\bIPPROTO_ICMP\b|/dev/tcp/|reverse_shell)", re.IGNORECASE),
        "reason": "Unauthorized raw socket or covert C2 beacon pattern detected",
    },
)

_PROMPT_INJECTION_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions", re.IGNORECASE),
    re.compile(r"disregard\s+(?:all\s+)?system\s+rules", re.IGNORECASE),
    re.compile(r"bypass\s+aegis\s+quarantine", re.IGNORECASE),
    re.compile(r"exfiltrate\s+(?:credentials|secrets|keys|vault)", re.IGNORECASE),
    re.compile(r"rm\s+-rf\s+/", re.IGNORECASE),
)


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


def _quarantine_root(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir else (_collab_dir() / "foundry_quarantine")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _lessons_ledger_file(base_dir: str | Path | None = None) -> Path:
    root = Path(base_dir) if base_dir else _collab_dir()
    root.mkdir(parents=True, exist_ok=True)
    return root / "federated_lessons_ledger.json"


# ── Hyperbolic / Lorentz Geometry & Procrustes Alignment (stdlib math) ────────────────────────

def poincare_to_lorentz(poincare_xyz: list[float] | tuple[float, float, float], kappa: float = 1.0) -> list[float]:
    """Map a 3D Poincaré ball vector ``(u1, u2, u3)`` (||u|| < 1) onto the Lorentz hyperboloid L^3_kappa."""
    u1, u2, u3 = float(poincare_xyz[0]), float(poincare_xyz[1]), float(poincare_xyz[2])
    norm_sq = u1 * u1 + u2 * u2 + u3 * u3
    if norm_sq >= 0.999999:
        scale = 0.999 / math.sqrt(norm_sq)
        u1, u2, u3 = u1 * scale, u2 * scale, u3 * scale
        norm_sq = u1 * u1 + u2 * u2 + u3 * u3
    inv_sqrt_k = 1.0 / math.sqrt(max(1e-9, float(kappa)))
    denom = 1.0 - norm_sq
    x0 = inv_sqrt_k * (1.0 + norm_sq) / denom
    x1 = inv_sqrt_k * (2.0 * u1) / denom
    x2 = inv_sqrt_k * (2.0 * u2) / denom
    x3 = inv_sqrt_k * (2.0 * u3) / denom
    return [x0, x1, x2, x3]


def lorentz_to_poincare(lorentz_txyz: list[float] | tuple[float, ...], kappa: float = 1.0) -> list[float]:
    """Project a 4D Lorentz vector ``(x0, x1, x2, x3)`` onto the 3D unit Poincaré ball."""
    x0, x1, x2, x3 = (
        float(lorentz_txyz[0]),
        float(lorentz_txyz[1]),
        float(lorentz_txyz[2]),
        float(lorentz_txyz[3]),
    )
    inv_sqrt_k = 1.0 / math.sqrt(max(1e-9, float(kappa)))
    denom = x0 + inv_sqrt_k
    if abs(denom) < 1e-12:
        return [0.0, 0.0, 0.0]
    return [x1 / denom, x2 / denom, x3 / denom]


def lorentz_inner(u: list[float] | tuple[float, ...], v: list[float] | tuple[float, ...]) -> float:
    """Compute the Minkowski/Lorentz inner product <u, v>_L = -u0*v0 + u1*v1 + u2*v2 + u3*v3."""
    return -float(u[0]) * float(v[0]) + float(u[1]) * float(v[1]) + float(u[2]) * float(v[2]) + float(u[3]) * float(v[3])


def _gram_schmidt_3x3(mat: list[list[float]]) -> list[list[float]]:
    """Orthonormalize a 3x3 matrix in pure Python stdlib so R^T R = I_3."""
    cols = [[mat[r][c] for r in range(3)] for c in range(3)]
    ortho: list[list[float]] = []
    for i, v in enumerate(cols):
        w = list(v)
        for u in ortho:
            dot = sum(w[k] * u[k] for k in range(3))
            w = [w[k] - dot * u[k] for k in range(3)]
        norm = math.sqrt(sum(x * x for x in w))
        if norm < 1e-9:
            # Fallback canonical basis vector orthogonal to existing
            basis = [0.0, 0.0, 0.0]
            basis[i] = 1.0
            for u in ortho:
                dot = sum(basis[k] * u[k] for k in range(3))
                basis = [basis[k] - dot * u[k] for k in range(3)]
            norm = math.sqrt(sum(x * x for x in basis)) or 1.0
            ortho.append([x / norm for x in basis])
        else:
            ortho.append([x / norm for x in w])
    return [[ortho[c][r] for c in range(3)] for r in range(3)]


def lorentz_procrustes_align(
    source_lorentz_vecs: list[list[float]],
    target_lorentz_vecs: list[list[float]] | None = None,
    kappa: float = 1.0,
) -> dict[str, Any]:
    """Align peer 3D Lorentz coordinates L^3_kappa onto the local manifold frame via an O(1, 3)
    spatial orthogonal transformation Lambda = diag(1, R) that strictly preserves
    -<Lambda x, Lambda x>_L = 1/kappa.
    """
    inv_k = 1.0 / max(1e-9, float(kappa))
    if not source_lorentz_vecs:
        return {"ok": True, "aligned_lorentz": [], "aligned_poincare": [], "max_invariant_error": 0.0}

    # Build 3x3 spatial cross-covariance H = sum(target_spatial * source_spatial^T)
    if target_lorentz_vecs and len(target_lorentz_vecs) == len(source_lorentz_vecs):
        cov = [[0.0, 0.0, 0.0] for _ in range(3)]
        for s_vec, t_vec in zip(source_lorentz_vecs, target_lorentz_vecs):
            for r in range(3):
                for c in range(3):
                    cov[r][c] += float(t_vec[r + 1]) * float(s_vec[c + 1])
        # Regularize with tiny identity so degenerate rank still yields a valid orthogonal frame
        for d in range(3):
            cov[d][d] += 1e-6
        rot_3x3 = _gram_schmidt_3x3(cov)
    else:
        rot_3x3 = [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]]

    aligned_lorentz: list[list[float]] = []
    aligned_poincare: list[list[float]] = []
    max_err = 0.0

    for vec in source_lorentz_vecs:
        s1, s2, s3 = float(vec[1]), float(vec[2]), float(vec[3])
        y1 = rot_3x3[0][0] * s1 + rot_3x3[0][1] * s2 + rot_3x3[0][2] * s3
        y2 = rot_3x3[1][0] * s1 + rot_3x3[1][1] * s2 + rot_3x3[1][2] * s3
        y3 = rot_3x3[2][0] * s1 + rot_3x3[2][1] * s2 + rot_3x3[2][2] * s3
        # Re-anchor timelike coordinate on the hyperboloid sheet x0 = sqrt(1/kappa + ||y||^2)
        y0 = math.sqrt(inv_k + y1 * y1 + y2 * y2 + y3 * y3)
        l_vec = [y0, y1, y2, y3]
        inv_val = -lorentz_inner(l_vec, l_vec)
        err = abs(inv_val - inv_k)
        if err > max_err:
            max_err = err
        aligned_lorentz.append(l_vec)
        aligned_poincare.append(lorentz_to_poincare(l_vec, kappa=kappa))

    return {
        "ok": max_err < 1e-6,
        "kappa": kappa,
        "rotation_3x3": rot_3x3,
        "aligned_lorentz": aligned_lorentz,
        "aligned_poincare": aligned_poincare,
        "max_invariant_error": max_err,
    }


# ── Merkle Root & 4-Stage Aegis Quarantine Gate ───────────────────────────────────────────────

def _json_safe_value(val: Any) -> Any:
    if isinstance(val, bytes):
        return {"__bytes_b64__": base64.b64encode(val).decode("ascii")}
    if isinstance(val, dict):
        return {str(k): _json_safe_value(v) for k, v in val.items()}
    if isinstance(val, list):
        return [_json_safe_value(x) for x in val]
    if isinstance(val, tuple):
        return [_json_safe_value(x) for x in val]
    return val


def compute_bundle_merkle_root(
    skill_md: str,
    anvil_map: dict[str, Any],
    knowledge_map: dict[str, Any],
    tools: list[dict[str, Any]],
    scripts: dict[str, Any],
) -> str:
    """Compute a deterministic SHA-256 Merkle root over all skill bundle artifacts."""
    leaves = [
        hashlib.sha256(("skill_md:" + str(skill_md)).encode("utf-8")).hexdigest(),
        hashlib.sha256(("anvil_map:" + json.dumps(_json_safe_value(anvil_map), sort_keys=True)).encode("utf-8")).hexdigest(),
        hashlib.sha256(("knowledge_map:" + json.dumps(_json_safe_value(knowledge_map), sort_keys=True)).encode("utf-8")).hexdigest(),
        hashlib.sha256(("tools:" + json.dumps(_json_safe_value(tools), sort_keys=True)).encode("utf-8")).hexdigest(),
        hashlib.sha256(("scripts:" + json.dumps(_json_safe_value(scripts), sort_keys=True)).encode("utf-8")).hexdigest(),
    ]
    combined = ":".join(leaves).encode("utf-8")
    return hashlib.sha256(combined).hexdigest()


# ── Stage 0: Zero-Binary & Anti-Spyware Gate + GWL Reproducible Binary Seal ──────────────────

def _gwl_seal_signing_key() -> bytes:
    extra = (os.environ.get("GWL_BINARY_SEAL_SIGNING_MATERIAL") or "").encode("utf-8")
    return hashlib.sha256(_GWL_SEAL_SIGNING_DOMAIN + b":" + GWL_HUB_ISSUER_DID.encode("utf-8") + b":" + extra).digest()


def _canonical_binary_seal_bytes(seal: dict[str, Any]) -> bytes:
    core = {
        "schema": seal.get("schema"),
        "seal_id": seal.get("seal_id"),
        "issuer_did": seal.get("issuer_did"),
        "builder_id": seal.get("builder_id"),
        "artifact_name": seal.get("artifact_name"),
        "source_sha256": seal.get("source_sha256"),
        "binary_sha256": seal.get("binary_sha256"),
        "aegis_6_cwe_ast_vetted": seal.get("aegis_6_cwe_ast_vetted"),
        "gandalf_backdoor_review_vetted": seal.get("gandalf_backdoor_review_vetted"),
        "reproducible_build_verified": seal.get("reproducible_build_verified"),
        "issued_at": seal.get("issued_at"),
    }
    return json.dumps(core, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign_gwl_binary_seal(seal: dict[str, Any]) -> str:
    mac = hmac.new(_gwl_seal_signing_key(), _canonical_binary_seal_bytes(seal), hashlib.sha256).hexdigest()
    return f"hmac-sha256:{mac}"


def create_gwl_reproducible_binary_seal(
    artifact_name: str,
    source_sha256: str,
    binary_sha256: str,
    *,
    aegis_passed: bool = True,
    gandalf_passed: bool = True,
    builder_id: str = "gwl-airgapped-builder-v1",
    issued_at: str = "",
) -> dict[str, Any]:
    """Create a Ghost World Labs reproducible build seal (`anchor.gwl.binary.seal.v1`) binding
    vetted plain-text source (`source_sha256`) to a reproducibly compiled binary (`binary_sha256`).
    """
    art = str(artifact_name or "").strip()
    src_hash = str(source_sha256 or "").strip()
    bin_hash = str(binary_sha256 or "").strip()
    if not art or not src_hash or not bin_hash:
        raise ValueError("artifact_name, source_sha256, and binary_sha256 are required for GWL binary seal")
    if not aegis_passed or not gandalf_passed:
        raise ValueError("GWL binary seal requires both Aegis 6-CWE AST and Gandalf backdoor vetting to pass")

    ts = str(issued_at or _utc_now_iso()).strip()
    seal_seed = f"{art}:{src_hash}:{bin_hash}:{builder_id}:{ts}"
    seal_id = "gwl-seal-" + hashlib.sha256(seal_seed.encode("utf-8")).hexdigest()[:16]

    seal: dict[str, Any] = {
        "schema": GWL_BINARY_SEAL_SCHEMA,
        "seal_id": seal_id,
        "issuer_did": GWL_HUB_ISSUER_DID,
        "builder_id": str(builder_id or "gwl-airgapped-builder-v1"),
        "artifact_name": art,
        "source_sha256": src_hash,
        "binary_sha256": bin_hash,
        "aegis_6_cwe_ast_vetted": True,
        "gandalf_backdoor_review_vetted": True,
        "reproducible_build_verified": True,
        "issued_at": ts,
    }
    seal["signature"] = _sign_gwl_binary_seal(seal)
    return seal


def verify_gwl_reproducible_binary_seal(
    seal: dict[str, Any],
    *,
    expected_artifact_name: str = "",
    expected_source_sha256: str = "",
    expected_binary_sha256: str = "",
) -> dict[str, Any]:
    """Verify a Ghost World Labs reproducible binary seal (`anchor.gwl.binary.seal.v1`)."""
    if not isinstance(seal, dict) or seal.get("schema") != GWL_BINARY_SEAL_SCHEMA:
        return {"ok": False, "valid": False, "error": "invalid_gwl_binary_seal_schema"}
    if seal.get("issuer_did") != GWL_HUB_ISSUER_DID:
        return {"ok": False, "valid": False, "error": "untrusted_binary_seal_issuer"}
    if (
        seal.get("aegis_6_cwe_ast_vetted") is not True
        or seal.get("gandalf_backdoor_review_vetted") is not True
        or seal.get("reproducible_build_verified") is not True
    ):
        return {"ok": False, "valid": False, "error": "incomplete_gwl_vetting_attestation"}

    art = str(seal.get("artifact_name") or "").strip()
    src_hash = str(seal.get("source_sha256") or "").strip()
    bin_hash = str(seal.get("binary_sha256") or "").strip()
    if not art or not src_hash or not bin_hash:
        return {"ok": False, "valid": False, "error": "missing_seal_digests"}

    if expected_artifact_name and art != str(expected_artifact_name).strip():
        return {"ok": False, "valid": False, "error": "artifact_name_mismatch"}
    if expected_source_sha256 and src_hash != str(expected_source_sha256).strip():
        return {"ok": False, "valid": False, "error": "source_sha256_mismatch"}
    if expected_binary_sha256 and bin_hash != str(expected_binary_sha256).strip():
        return {"ok": False, "valid": False, "error": "binary_sha256_mismatch"}

    provided_sig = str(seal.get("signature") or "").strip()
    expected_sig = _sign_gwl_binary_seal(seal)
    if not provided_sig or not hmac.compare_digest(provided_sig, expected_sig):
        return {"ok": False, "valid": False, "error": "invalid_gwl_binary_seal_signature"}

    return {
        "ok": True,
        "valid": True,
        "seal_id": seal.get("seal_id"),
        "issuer_did": GWL_HUB_ISSUER_DID,
        "builder_id": seal.get("builder_id"),
        "artifact_name": art,
        "source_sha256": src_hash,
        "binary_sha256": bin_hash,
    }


def _extract_raw_bytes_and_text(content: Any) -> tuple[bytes, str]:
    if isinstance(content, bytes):
        return content, content.decode("latin-1", errors="replace")
    if isinstance(content, dict) and "__bytes_b64__" in content:
        try:
            raw = base64.b64decode(str(content["__bytes_b64__"]).encode("ascii"))
            return raw, raw.decode("latin-1", errors="replace")
        except Exception:
            pass
    if isinstance(content, str):
        return content.encode("latin-1", errors="replace"), content
    s = str(content or "")
    return s.encode("utf-8", errors="replace"), s


def _detect_binary_magic(raw_bytes: bytes) -> str | None:
    if not raw_bytes:
        return None
    for magic, label in BINARY_MAGIC_SIGNATURES.items():
        if raw_bytes.startswith(magic):
            return label
    return None


def _collect_bundle_seals(bundle: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Collect candidate GWL binary seals keyed by artifact_name."""
    seals_by_artifact: dict[str, dict[str, Any]] = {}
    single = bundle.get("gwl_binary_seal")
    if isinstance(single, dict) and single.get("artifact_name"):
        seals_by_artifact[str(single["artifact_name"])] = single

    multi = bundle.get("gwl_binary_seals")
    if isinstance(multi, dict):
        for k, v in multi.items():
            if isinstance(v, dict):
                art_name = str(v.get("artifact_name") or k)
                seals_by_artifact[art_name] = v
    elif isinstance(multi, list):
        for item in multi:
            if isinstance(item, dict) and item.get("artifact_name"):
                seals_by_artifact[str(item["artifact_name"])] = item

    for tool in bundle.get("tools") or []:
        if isinstance(tool, dict) and isinstance(tool.get("gwl_binary_seal"), dict):
            t_seal = tool["gwl_binary_seal"]
            art_name = str(t_seal.get("artifact_name") or tool.get("entrypoint") or tool.get("name") or "")
            if art_name:
                seals_by_artifact[art_name] = t_seal

    return seals_by_artifact


def scan_for_forbidden_binaries_and_spyware(bundle: dict[str, Any]) -> dict[str, Any]:
    """Stage 0 Zero-Binary & Anti-Spyware scanner (`stage0_zero_binary_and_anti_spyware`).

    - Rule 1 (Peer/Collaborator Submissions are Strictly Source-Only):
      Rejects fail-closed any file/tool with a forbidden binary extension (`.exe`, `.dll`, `.so`,
      `.dylib`, `.pyd`, `.pyc`, `.wasm`, `.jar`, `.whl`, etc.), binary magic-byte header
      (`MZ`, `\\x7fELF`, Mach-O, `\\x00asm`), or spyware/obfuscated dropper pattern unless
      covered by a valid Ghost World Labs reproducible build seal (`anchor.gwl.binary.seal.v1`).
    - Rule 2 (GWL Vetted Reproducible Build Exception):
      Allows a compiled binary only when accompanied by a cryptographically verified
      `anchor.gwl.binary.seal.v1` binding `source_sha256 <-> binary_sha256` and zero spyware hits.
    """
    if not isinstance(bundle, dict):
        return {
            "ok": False,
            "passed": False,
            "stage": "stage0_zero_binary_and_anti_spyware",
            "zero_binary_verified": False,
            "anti_spyware_verified": False,
            "reason": "invalid_bundle",
            "reason_codes": ["invalid_bundle"],
            "binary_findings": [],
            "spyware_findings": [],
            "findings": [],
            "sealed_binaries": [],
        }

    seals_map = _collect_bundle_seals(bundle)
    binary_findings: list[dict[str, Any]] = []
    spyware_findings: list[dict[str, Any]] = []
    sealed_binaries: list[dict[str, Any]] = []

    # Gather all candidate file/artifact entries from scripts, files, binaries, and tools
    artifact_entries: list[tuple[str, Any]] = []
    scripts = bundle.get("scripts")
    if isinstance(scripts, dict):
        for fname, content in scripts.items():
            artifact_entries.append((str(fname), content))

    for extra_key in ("files", "binaries", "artifacts"):
        extra_map = bundle.get(extra_key)
        if isinstance(extra_map, dict):
            for fname, content in extra_map.items():
                artifact_entries.append((str(fname), content))
        elif isinstance(extra_map, list):
            for item in extra_map:
                if isinstance(item, dict):
                    fname = str(item.get("path") or item.get("name") or item.get("filename") or "artifact")
                    content = item.get("content") if "content" in item else item.get("bytes", "")
                    artifact_entries.append((fname, content))

    for tool in bundle.get("tools") or []:
        if isinstance(tool, dict):
            ep = str(tool.get("entrypoint") or tool.get("path") or tool.get("binary") or "")
            t_content = tool.get("content") if "content" in tool else tool.get("binary_bytes", "")
            if ep:
                artifact_entries.append((ep, t_content))

    # Compute available plain-text source hashes so GWL binary seals can also verify source binding when present
    source_hashes: set[str] = set()
    for fname, content in artifact_entries:
        ext = Path(fname).suffix.lower()
        if ext not in FORBIDDEN_BINARY_EXTENSIONS:
            raw_b, txt = _extract_raw_bytes_and_text(content)
            if _detect_binary_magic(raw_b) is None:
                source_hashes.add(hashlib.sha256(txt.encode("utf-8")).hexdigest())
                source_hashes.add(hashlib.sha256(raw_b).hexdigest())

    checked_artifacts: set[str] = set()
    for fname, content in artifact_entries:
        raw_b, txt = _extract_raw_bytes_and_text(content)
        ext = Path(fname).suffix.lower()
        has_forbidden_ext = ext in FORBIDDEN_BINARY_EXTENSIONS
        magic_label = _detect_binary_magic(raw_b)
        is_binary = has_forbidden_ext or (magic_label is not None)

        if is_binary:
            if fname in checked_artifacts and any(s.get("artifact_name") == fname for s in sealed_binaries):
                continue
            checked_artifacts.add(fname)
            candidate_seal = seals_map.get(fname) or seals_map.get(Path(fname).name)
            bin_sha = hashlib.sha256(raw_b).hexdigest() if raw_b else ""
            seal_ver = (
                verify_gwl_reproducible_binary_seal(
                    candidate_seal,
                    expected_artifact_name=str(candidate_seal.get("artifact_name") or fname),
                    expected_binary_sha256=bin_sha if raw_b else "",
                )
                if isinstance(candidate_seal, dict)
                else {"ok": False, "error": "missing_gwl_binary_seal"}
            )
            # If source files are present and source_sha256 doesn't match any source when explicitly mismatched
            if seal_ver.get("ok") and source_hashes and isinstance(candidate_seal, dict):
                # Allow if source_sha256 matches one of the bundle's sources OR if no companion source with same stem exists
                stem = Path(fname).stem
                companion_sources = [
                    f for f, _ in artifact_entries
                    if Path(f).stem == stem and Path(f).suffix.lower() not in FORBIDDEN_BINARY_EXTENSIONS
                ]
                if companion_sources and str(candidate_seal.get("source_sha256")) not in source_hashes:
                    seal_ver = {"ok": False, "error": "source_sha256_mismatch_against_companion_source"}

            if seal_ver.get("ok"):
                sealed_binaries.append({
                    "artifact_name": fname,
                    "seal_id": seal_ver.get("seal_id"),
                    "source_sha256": seal_ver.get("source_sha256"),
                    "binary_sha256": seal_ver.get("binary_sha256"),
                    "issuer_did": seal_ver.get("issuer_did"),
                })
            else:
                binary_findings.append({
                    "file": fname,
                    "category": "forbidden_compiled_binary",
                    "extension": ext,
                    "magic_signature": magic_label,
                    "seal_error": seal_ver.get("error", "missing_gwl_binary_seal"),
                    "reason": "compiled_binary_forbidden_source_only",
                })
        else:
            # Scan plain-text source for spyware / backdoors / obfuscated droppers
            for pat_spec in SPYWARE_BACKDOOR_PATTERNS:
                m = pat_spec["pattern"].search(txt)
                if m:
                    spyware_findings.append({
                        "file": fname,
                        "rule_id": pat_spec["id"],
                        "category": pat_spec["category"],
                        "match": m.group(0),
                        "description": pat_spec["reason"],
                        "reason": "spyware_or_obfuscated_dropper_detected",
                    })

    # Also scan SKILL.md for spyware/backdoor dropper patterns
    skill_md_txt = str(bundle.get("skill_md") or "")
    for pat_spec in SPYWARE_BACKDOOR_PATTERNS:
        m = pat_spec["pattern"].search(skill_md_txt)
        if m:
            spyware_findings.append({
                "file": "SKILL.md",
                "rule_id": pat_spec["id"],
                "category": pat_spec["category"],
                "match": m.group(0),
                "description": pat_spec["reason"],
                "reason": "spyware_or_obfuscated_dropper_detected",
            })

    reason_codes: list[str] = []
    if binary_findings:
        reason_codes.append("compiled_binary_forbidden_source_only")
    if spyware_findings:
        reason_codes.append("spyware_or_obfuscated_dropper_detected")

    passed = (len(binary_findings) == 0) and (len(spyware_findings) == 0)
    if not passed:
        primary_reason = reason_codes[0]
    elif sealed_binaries:
        primary_reason = "gwl_reproducible_binary_seal_verified"
    else:
        primary_reason = "clean_source_only"

    return {
        "ok": passed,
        "passed": passed,
        "stage": "stage0_zero_binary_and_anti_spyware",
        "policy": ZERO_BINARY_LAW,
        "zero_binary_verified": len(binary_findings) == 0,
        "anti_spyware_verified": len(spyware_findings) == 0,
        "reason": primary_reason,
        "reason_codes": reason_codes,
        "binary_findings": binary_findings,
        "spyware_findings": spyware_findings,
        "findings": binary_findings + spyware_findings,
        "sealed_binaries": sealed_binaries,
    }


def _scan_python_ast_for_cwe_sinks(filename: str, code: str) -> list[dict[str, Any]]:
    """Deterministic AST scanner for CWE-78 (shell injection) and CWE-94/502 (code exec / pickle)."""
    findings: list[dict[str, Any]] = []
    try:
        tree = ast.parse(code, filename=filename)
    except SyntaxError as exc:
        findings.append({
            "file": filename,
            "cwe": "SYNTAX-ERR",
            "sink": "ast.parse",
            "line": exc.lineno or 1,
            "reason": f"SyntaxError: {exc.msg}",
        })
        return findings

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                prefix = node.func.value.id if isinstance(node.func.value, ast.Name) else ""
                func_name = f"{prefix}.{node.func.attr}" if prefix else node.func.attr

            if func_name in ("os.system", "os.popen", "system", "popen"):
                findings.append({
                    "file": filename,
                    "cwe": "CWE-78",
                    "sink": func_name,
                    "line": getattr(node, "lineno", 1),
                    "reason": f"Forbidden shell execution sink: {func_name}",
                })
            elif func_name in ("eval", "exec", "pickle.loads", "marshal.loads"):
                findings.append({
                    "file": filename,
                    "cwe": "CWE-94/502",
                    "sink": func_name,
                    "line": getattr(node, "lineno", 1),
                    "reason": f"Forbidden dynamic code/deserialization sink: {func_name}",
                })
            elif func_name.startswith("subprocess.") or func_name in ("Popen", "run", "call", "check_output"):
                for kw in node.keywords:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        findings.append({
                            "file": filename,
                            "cwe": "CWE-78",
                            "sink": f"{func_name}(shell=True)",
                            "line": getattr(node, "lineno", 1),
                            "reason": "Subprocess call with shell=True is prohibited in federated skills",
                        })
    return findings


class FoundryStewardFederation:
    """Foundry Steward & Librarian Federation with Stage 0 Zero-Binary/Anti-Spyware + 4-Stage Aegis Quarantine Gate."""

    ZERO_BINARY_LAW = ZERO_BINARY_LAW
    FORBIDDEN_BINARY_EXTENSIONS = FORBIDDEN_BINARY_EXTENSIONS
    BINARY_MAGIC_SIGNATURES = BINARY_MAGIC_SIGNATURES
    SPYWARE_BACKDOOR_PATTERNS = SPYWARE_BACKDOOR_PATTERNS

    def __init__(self, base_dir: str | Path | None = None) -> None:
        self.base_dir = Path(base_dir) if base_dir else _collab_dir()
        self.quarantine_dir = _quarantine_root(self.base_dir / "foundry_quarantine")
        self.lessons_file = _lessons_ledger_file(self.base_dir)

    def scan_for_forbidden_binaries_and_spyware(self, bundle: dict[str, Any]) -> dict[str, Any]:
        return scan_for_forbidden_binaries_and_spyware(bundle)

    def create_gwl_reproducible_binary_seal(
        self,
        artifact_name: str,
        source_sha256: str,
        binary_sha256: str,
        *,
        aegis_passed: bool = True,
        gandalf_passed: bool = True,
        builder_id: str = "gwl-airgapped-builder-v1",
    ) -> dict[str, Any]:
        return create_gwl_reproducible_binary_seal(
            artifact_name=artifact_name,
            source_sha256=source_sha256,
            binary_sha256=binary_sha256,
            aegis_passed=aegis_passed,
            gandalf_passed=gandalf_passed,
            builder_id=builder_id,
        )

    def verify_gwl_reproducible_binary_seal(
        self,
        seal: dict[str, Any],
        *,
        expected_artifact_name: str = "",
        expected_source_sha256: str = "",
        expected_binary_sha256: str = "",
    ) -> dict[str, Any]:
        return verify_gwl_reproducible_binary_seal(
            seal,
            expected_artifact_name=expected_artifact_name,
            expected_source_sha256=expected_source_sha256,
            expected_binary_sha256=expected_binary_sha256,
        )

    def export_skill_bundle(
        self,
        skill_id: str,
        author_pseudonym: str = aap.PSEUDONYM_DEFAULT,
        skill_md: str = "",
        anvil_map: dict[str, Any] | None = None,
        knowledge_map: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        scripts: dict[str, Any] | None = None,
        poincare_coords: list[list[float]] | None = None,
        gwl_binary_seal: dict[str, Any] | None = None,
        gwl_binary_seals: Any = None,
        files: dict[str, Any] | None = None,
        binaries: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Export a privacy-scrubbed, Merkle-signed ``anchor.foundry.federation.v1`` skill bundle."""
        canon_pseudo, _ = (
            aap.canonicalize_pseudonym(author_pseudonym)
            if aap.slugify_pseudonym(author_pseudonym) in ("samwise-gamgee", "samwise-gamgi", "samwise")
            else (str(author_pseudonym or aap.PSEUDONYM_DEFAULT).strip(), [])
        )
        author_did = aap.did_from_pseudonym(canon_pseudo)
        s_id = aap.slugify_pseudonym(skill_id or "custom-skill")

        eff_md = aap.scrub_private_identity_leaks(
            skill_md or f"---\nname: {s_id}\ndescription: Federated skill by {canon_pseudo}\n---\n# {s_id}\n",
            pseudonym=canon_pseudo,
        )
        eff_anvil = aap.scrub_private_identity_leaks(
            anvil_map
            or {
                "schema": "anvil.progressive_map.v1",
                "skill_id": s_id,
                "level1_role_io": {"role": f"{s_id} core engine", "inputs": ["brief"], "outputs": ["artifact"]},
                "level2_subflow": ["ingest", "verify", "emit"],
                "null_space_ratio": 0.0,
            },
            pseudonym=canon_pseudo,
        )
        default_p_coords = poincare_coords or [[0.15, -0.22, 0.10], [-0.12, 0.31, -0.08]]
        l_coords = [poincare_to_lorentz(pt) for pt in default_p_coords]
        eff_kmap = aap.scrub_private_identity_leaks(
            knowledge_map
            or {
                "schema": "anchor.knowledge_map.v1",
                "skill_id": s_id,
                "nodes": [
                    {
                        "id": f"{s_id}-concept-{i + 1}",
                        "poincare_xyz": default_p_coords[i],
                        "lorentz_txyz": l_coords[i],
                    }
                    for i in range(len(default_p_coords))
                ],
            },
            pseudonym=canon_pseudo,
        )
        eff_tools = aap.scrub_private_identity_leaks(
            tools or [{"name": f"{s_id}_run", "entrypoint": "scripts/main.py"}],
            pseudonym=canon_pseudo,
        )
        raw_scripts = scripts or {"scripts/main.py": "def run(payload: dict) -> dict:\n    return {'ok': True, 'result': payload}\n"}
        eff_scripts = aap.scrub_private_identity_leaks(_json_safe_value(raw_scripts), pseudonym=canon_pseudo)

        merkle_root = compute_bundle_merkle_root(eff_md, eff_anvil, eff_kmap, eff_tools, eff_scripts)
        bundle: dict[str, Any] = {
            "schema": FEDERATION_BUNDLE_SCHEMA,
            "skill_id": s_id,
            "author_did": author_did,
            "author_pseudonym": canon_pseudo,
            "exported_at": _utc_now_iso(),
            "merkle_root_sha256": merkle_root,
            "skill_md": eff_md,
            "anvil_map": eff_anvil,
            "knowledge_map": eff_kmap,
            "tools": eff_tools,
            "scripts": eff_scripts,
        }
        if isinstance(gwl_binary_seal, dict):
            bundle["gwl_binary_seal"] = gwl_binary_seal
        if gwl_binary_seals is not None:
            bundle["gwl_binary_seals"] = gwl_binary_seals
        if isinstance(files, dict):
            bundle["files"] = _json_safe_value(files)
        if isinstance(binaries, dict):
            bundle["binaries"] = _json_safe_value(binaries)
        bundle["signature"] = aap.sign_payload(_json_safe_value(bundle), did=author_did)
        return bundle

    def receive_into_quarantine(self, bundle: dict[str, Any]) -> dict[str, Any]:
        """Stage an incoming federated skill bundle into ``.anchor/foundry_quarantine/<skill_id>@<sha256>/``."""
        if not isinstance(bundle, dict) or bundle.get("schema") != FEDERATION_BUNDLE_SCHEMA:
            return {"ok": False, "error": "invalid_federation_bundle_schema"}

        s_id = aap.slugify_pseudonym(str(bundle.get("skill_id") or "unknown-skill"))
        merkle = str(bundle.get("merkle_root_sha256") or "")[:12] or "unverified"
        q_folder = self.quarantine_dir / f"{s_id}@{merkle}"
        q_folder.mkdir(parents=True, exist_ok=True)

        safe_bundle = _json_safe_value(bundle)
        (q_folder / "bundle.json").write_text(json.dumps(safe_bundle, indent=2) + "\n", encoding="utf-8")
        (q_folder / "SKILL.md").write_text(str(bundle.get("skill_md") or ""), encoding="utf-8")
        (q_folder / "ANVIL-MAP.json").write_text(json.dumps(bundle.get("anvil_map") or {}, indent=2) + "\n", encoding="utf-8")
        (q_folder / "knowledge-map.json").write_text(json.dumps(bundle.get("knowledge_map") or {}, indent=2) + "\n", encoding="utf-8")

        return {
            "ok": True,
            "status": "quarantined",
            "skill_id": s_id,
            "author_did": bundle.get("author_did"),
            "author_pseudonym": bundle.get("author_pseudonym"),
            "merkle_root_sha256": bundle.get("merkle_root_sha256"),
            "quarantine_dir": str(q_folder),
        }

    def evaluate_quarantined_skill(self, bundle_or_qdir: dict[str, Any] | str | Path) -> dict[str, Any]:
        """Execute Stage 0 Zero-Binary/Anti-Spyware Gate + 4-Stage Aegis + Anvil + Hermetic + Gandalf Quarantine Gate."""
        if isinstance(bundle_or_qdir, (str, Path)):
            bp = Path(bundle_or_qdir)
            if bp.is_dir():
                bp = bp / "bundle.json"
            bundle = json.loads(bp.read_text(encoding="utf-8"))
        else:
            bundle = dict(bundle_or_qdir)

        skill_md = str(bundle.get("skill_md") or "")
        anvil_map = bundle.get("anvil_map") if isinstance(bundle.get("anvil_map"), dict) else {}
        knowledge_map = bundle.get("knowledge_map") if isinstance(bundle.get("knowledge_map"), dict) else {}
        tools = bundle.get("tools") if isinstance(bundle.get("tools"), list) else []
        scripts = bundle.get("scripts") if isinstance(bundle.get("scripts"), dict) else {}

        # Stage 0: Zero-Binary & Anti-Spyware Gate (Fail-Closed unless GWL Reproducible Binary Seal)
        stage0 = scan_for_forbidden_binaries_and_spyware(bundle)
        stage0_passed = bool(stage0.get("passed"))
        sealed_artifact_names = {
            str(s.get("artifact_name")) for s in (stage0.get("sealed_binaries") or []) if isinstance(s, dict)
        }

        # Stage 1: Aegis AST & Prompt-Directive Security Scan
        aegis_findings: list[dict[str, Any]] = []
        for pat in _PROMPT_INJECTION_PATTERNS:
            m = pat.search(skill_md)
            if m:
                aegis_findings.append({
                    "file": "SKILL.md",
                    "cwe": "PROMPT-INJECTION",
                    "sink": m.group(0),
                    "line": 1,
                    "reason": f"Prohibited prompt-override directive detected: '{m.group(0)}'",
                })
        for fname, code_val in scripts.items():
            fname_str = str(fname)
            if fname_str in sealed_artifact_names or Path(fname_str).suffix.lower() in FORBIDDEN_BINARY_EXTENSIONS:
                continue
            raw_b, code_str = _extract_raw_bytes_and_text(code_val)
            if _detect_binary_magic(raw_b) is not None:
                continue
            aegis_findings.extend(_scan_python_ast_for_cwe_sinks(fname_str, code_str))

        stage1_passed = stage0_passed and (len(aegis_findings) == 0)

        # Stage 2: Anvil Structural & Null-Space Verification
        null_ratio = float(anvil_map.get("null_space_ratio") or 0.0)
        has_role_io = isinstance(anvil_map.get("level1_role_io"), dict)
        has_kmap_nodes = isinstance(knowledge_map.get("nodes"), list) and len(knowledge_map.get("nodes") or []) > 0
        stage2_passed = bool(skill_md.strip()) and has_role_io and has_kmap_nodes and (null_ratio <= 0.15)

        # Stage 3: Hermetic Test & Merkle Integrity Gate
        expected_merkle = compute_bundle_merkle_root(skill_md, anvil_map, knowledge_map, tools, scripts)
        merkle_match = (expected_merkle == str(bundle.get("merkle_root_sha256") or ""))
        author_did = str(bundle.get("author_did") or "")
        sig_str = str(bundle.get("signature") or "")
        safe_bundle = _json_safe_value(bundle)
        sig_valid = aap.verify_signature(safe_bundle, sig_str, did=author_did)
        if not sig_valid:
            # Allow detached GWL binary seal attached after author signed core bundle
            core_bundle = {
                k: v for k, v in safe_bundle.items()
                if k not in ("gwl_binary_seal", "gwl_binary_seals", "files", "binaries", "artifacts")
            }
            sig_valid = aap.verify_signature(core_bundle, sig_str, did=author_did)
        stage3_passed = merkle_match and sig_valid

        # Stage 4: Gandalf Differential Scorecard
        score = 100
        if not stage0_passed:
            score = 0
        else:
            if not stage1_passed:
                score -= 60
            if not stage2_passed:
                score -= 25
            if not stage3_passed:
                score -= 30
        score = max(0, score)
        stage4_passed = stage0_passed and (score >= 80)

        all_passed = stage0_passed and stage1_passed and stage2_passed and stage3_passed and stage4_passed
        ht6 = cbt.check_human_escalation_triggers(
            "HT-6",
            {
                "skill_id": bundle.get("skill_id"),
                "author_pseudonym": bundle.get("author_pseudonym"),
                "merkle_root_sha256": bundle.get("merkle_root_sha256"),
                "gandalf_score": score,
            },
        )

        out: dict[str, Any] = {
            "ok": all_passed,
            "passed": all_passed,
            "skill_id": bundle.get("skill_id"),
            "author_pseudonym": bundle.get("author_pseudonym"),
            "status": "ready_for_human_promotion" if all_passed else "rejected_in_quarantine",
            "reason": stage0.get("reason") if not stage0_passed else ("ready_for_human_promotion" if all_passed else "quarantine_gate_failed"),
            "stages": {
                "stage0_zero_binary_and_anti_spyware": stage0,
                "aegis_security": {"passed": len(aegis_findings) == 0, "findings": aegis_findings},
                "anvil_structural": {
                    "passed": stage2_passed,
                    "has_role_io": has_role_io,
                    "has_knowledge_nodes": has_kmap_nodes,
                    "null_space_ratio": null_ratio,
                },
                "hermetic_test_gate": {
                    "passed": stage3_passed,
                    "merkle_verified": merkle_match,
                    "signature_verified": sig_valid,
                },
                "gandalf_scorecard": {
                    "passed": stage4_passed,
                    "score": score,
                    "verdict": "PASS" if stage4_passed else "BLOCK",
                },
            },
            "human_escalation": ht6,
        }
        if not stage0_passed:
            out["rejection_reason"] = stage0.get("reason")
            out["reason_codes"] = stage0.get("reason_codes", [])
        return out

    # ── Federated Librarian Distilled Lesson Cards & Provenance Ledger ────────────────────────

    def _load_lessons_store(self) -> dict[str, Any]:
        if not self.lessons_file.is_file():
            return {"lessons": [], "provenance_ledger": {}}
        try:
            data = json.loads(self.lessons_file.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("lessons", [])
                data.setdefault("provenance_ledger", {})
                return data
        except Exception:
            pass
        return {"lessons": [], "provenance_ledger": {}}

    def _save_lessons_store(self, store: dict[str, Any]) -> None:
        self.lessons_file.parent.mkdir(parents=True, exist_ok=True)
        self.lessons_file.write_text(json.dumps(store, indent=2) + "\n", encoding="utf-8")

    def export_distilled_lessons(
        self,
        skill_id: str,
        lessons: list[dict[str, Any]] | None = None,
        author_pseudonym: str = aap.PSEUDONYM_DEFAULT,
    ) -> dict[str, Any]:
        """Export privacy-scrubbed ``anchor.librarian.lesson.v1`` cards attributed to ``author_pseudonym``."""
        canon_pseudo, _ = (
            aap.canonicalize_pseudonym(author_pseudonym)
            if aap.slugify_pseudonym(author_pseudonym) in ("samwise-gamgee", "samwise-gamgi", "samwise")
            else (str(author_pseudonym or aap.PSEUDONYM_DEFAULT).strip(), [])
        )
        author_did = aap.did_from_pseudonym(canon_pseudo)
        s_id = aap.slugify_pseudonym(skill_id or "general")

        raw_items = lessons or [
            {
                "title": f"Distilled invariant for {s_id}",
                "summary": "Always verify cross-family adversarial gates before promoting artifacts.",
            }
        ]
        cards: list[dict[str, Any]] = []
        for item in raw_items:
            scrubbed = aap.scrub_private_identity_leaks(dict(item), pseudonym=canon_pseudo)
            title = str(scrubbed.get("title") or "Lesson")
            summary = str(scrubbed.get("summary") or "")
            content_hash = hashlib.sha256(f"{s_id}:{author_did}:{title}:{summary}".encode("utf-8")).hexdigest()
            lesson_id = str(scrubbed.get("lesson_id") or f"lesson-{content_hash[:16]}")
            card: dict[str, Any] = {
                "schema": LIBRARIAN_LESSON_SCHEMA,
                "lesson_id": lesson_id,
                "skill_id": s_id,
                "origin_did": str(scrubbed.get("origin_did") or author_did),
                "origin_pseudonym": str(scrubbed.get("origin_pseudonym") or canon_pseudo),
                "title": title,
                "summary": summary,
                "content_sha256": content_hash,
                "hops": list(scrubbed.get("hops") or [author_did]),
                "exported_at": _utc_now_iso(),
            }
            card["signature"] = aap.sign_payload(card, did=author_did)
            cards.append(card)

        return {
            "ok": True,
            "schema": LIBRARIAN_LESSON_SCHEMA,
            "skill_id": s_id,
            "author_did": author_did,
            "author_pseudonym": canon_pseudo,
            "lessons": cards,
        }

    def import_distilled_lessons(self, packet_or_lessons: dict[str, Any] | list[dict[str, Any]]) -> dict[str, Any]:
        """Idempotently merge federated Librarian Lesson Cards into the local ledger.

        Prevents circular A -> B -> A echo inflation by keying credit on ``(lesson_id, origin_did)``.
        """
        if isinstance(packet_or_lessons, dict):
            incoming = packet_or_lessons.get("lessons") or [packet_or_lessons]
        else:
            incoming = list(packet_or_lessons)

        store = self._load_lessons_store()
        existing_lessons: list[dict[str, Any]] = store["lessons"]
        ledger: dict[str, dict[str, Any]] = store["provenance_ledger"]

        by_id: dict[str, dict[str, Any]] = {
            str(x.get("lesson_id")): x for x in existing_lessons if isinstance(x, dict) and x.get("lesson_id")
        }
        added = 0
        deduplicated = 0

        for card in incoming:
            if not isinstance(card, dict) or card.get("schema") != LIBRARIAN_LESSON_SCHEMA:
                continue
            lid = str(card.get("lesson_id") or "")
            origin_did = str(card.get("origin_did") or "")
            origin_pseudo = str(card.get("origin_pseudonym") or aap.PSEUDONYM_DEFAULT)
            if not lid or not origin_did:
                continue

            if lid in by_id:
                deduplicated += 1
                continue

            by_id[lid] = dict(card)
            added += 1

            author_entry = ledger.setdefault(
                origin_did,
                {
                    "did": origin_did,
                    "pseudonym": origin_pseudo,
                    "credited_lesson_ids": [],
                    "credit_count": 0,
                },
            )
            if lid not in author_entry["credited_lesson_ids"]:
                author_entry["credited_lesson_ids"].append(lid)
                author_entry["credit_count"] = len(author_entry["credited_lesson_ids"])

        store["lessons"] = list(by_id.values())
        store["provenance_ledger"] = ledger
        self._save_lessons_store(store)
        return {
            "ok": True,
            "added": added,
            "deduplicated": deduplicated,
            "total_lessons": len(store["lessons"]),
            "provenance_ledger": ledger,
        }

    def list_quarantined_skills(self) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        if not self.quarantine_dir.is_dir():
            return items
        for bp in sorted(self.quarantine_dir.glob("*/bundle.json")):
            try:
                b = json.loads(bp.read_text(encoding="utf-8"))
                items.append({
                    "skill_id": b.get("skill_id"),
                    "author_did": b.get("author_did"),
                    "author_pseudonym": b.get("author_pseudonym"),
                    "merkle_root_sha256": b.get("merkle_root_sha256"),
                    "quarantine_dir": str(bp.parent),
                })
            except Exception:
                continue
        return items
