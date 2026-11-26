#!/usr/bin/env python3
"""Anchor Mother Ship Registration & Push/Pull Update Engine (v1.5.4, stdlib only).

Provides:
1. Repo-tracked & runtime Mother Ship registration (`mothership_registry.json` + `.anchor/mothership_registry.json`)
   so every collaborator Mother Ship (Windows, macOS / MacBook Air, Linux) is registered in the Anchor repo.
2. Pull Update (`check_for_updates` + `pull_latest_update`): allows any Anchor installation (including v1.5.0/v1.5.1
   via zero-dependency compatibility shims, CRLF stash hygiene, and module reload / two-phase re-exec) to check for
   the latest release version and pull/apply the update in-place while refreshing bundled Foundry skills.
3. Push & Zero-Inbound Outbound Heartbeat Updates (`push_update_to_motherships` + `sync_telemetry_to_homebase`):
   delivers updates both via inbound Tailscale HTTP (`/api/system/pull_update`) and outbound 15-minute collaborator
   heartbeats (`pending_update` piggybacked on `receive_homebase_telemetry`), working across 1-way Tailscale Node
   Sharing without exposing inbound port 8777.
"""
from __future__ import annotations

import contextlib
from datetime import datetime, timezone
import hashlib
import hmac
import importlib
import json
import os
from pathlib import Path
import platform
import re
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request

import anchor_agent_protocol as aap
import onboard
import paths


REGISTRY_SCHEMA = "anchor.mothership.registry.v1"
REGISTRY_FILENAME = "mothership_registry.json"
HOMEBASE_LINK_SCHEMA = "anchor.homebase.link.v1"
HOMEBASE_LINK_FILENAME = "homebase_link.json"
HOMEBASE_PEERS_CAP_FILENAME = "homebase_peer_capabilities.json"
DEFAULT_HOMEBASE_URL = "https://gwl-server.tailb49f65.ts.net"
DEFAULT_GITHUB_REPO = "https://github.com/johncliechty/ghostworldlabs-anchor.git"
ALLOWED_RELEASE_REPOS = (
    "https://github.com/johncliechty/ghostworldlabs-anchor.git",
    "https://github.com/johncliechty/anchor-plus-skills.git",
)
RAW_VERSION_URL = "https://raw.githubusercontent.com/johncliechty/ghostworldlabs-anchor/main/VERSION"
RELEASE_SIGNAL_SCHEMA = "anchor.release.signal.v1"
RELEASE_SIGNAL_FILENAME = "release-signal.json"
DEFAULT_RELEASE_SIGNAL_URL = "https://raw.githubusercontent.com/johncliechty/ghostworldlabs-anchor/main/release-signal.json"
UPDATE_STATUS_FILENAME = "update_status.json"
RELEASE_SIGNAL_KEY_ID = "gwl-homebase-2026-v1"
CORE_ATTESTED_FILES = (
    "VERSION",
    "anchor_gui.py",
    "mothership_updater.py",
    "onboard_wizard.py",
    "website_portal.py",
    "paths.py",
)
# Pinned Ed25519 public key bytes for gwl-homebase-2026-v1 (stored as integer tuple; stdlib RFC 8032 verifier)
PINNED_RELEASE_PUBKEY_BYTES = (
    0x52, 0xED, 0x45, 0x45, 0xF7, 0x0D, 0xBF, 0x4B,
    0x00, 0x50, 0xB4, 0x2A, 0x48, 0xC0, 0x93, 0x89,
    0x24, 0xDA, 0xDC, 0x2A, 0x39, 0x6D, 0xFD, 0xA1,
    0xBE, 0x96, 0x35, 0x94, 0x99, 0xAE, 0xA2, 0x00,
)

_FALLBACK_WRITE_LOCK = threading.RLock()
_AUTO_UPDATE_LOCK = threading.Lock()
_CLI_MAIN_MODE = False


# ── Pure-stdlib RFC 8032 Ed25519 Release-Signal Signing & Verification ───────

_ED_Q = (1 << 255) - 19
_ED_L = (1 << 252) + 27742317777372353535851937790883648493
_ED_D = (-121665 * pow(121666, _ED_Q - 2, _ED_Q)) % _ED_Q
_ED_I = pow(2, (_ED_Q - 1) // 4, _ED_Q)


def _ed_xrecover(y: int) -> int:
    xx = (y * y - 1) * pow(_ED_D * y * y + 1, _ED_Q - 2, _ED_Q) % _ED_Q
    x = pow(xx, (_ED_Q + 3) // 8, _ED_Q)
    if (x * x - xx) % _ED_Q != 0:
        x = (x * _ED_I) % _ED_Q
    if x & 1:
        x = _ED_Q - x
    return x


_ED_BY = (4 * pow(5, _ED_Q - 2, _ED_Q)) % _ED_Q
_ED_BX = _ed_xrecover(_ED_BY)
_ED_BASE = (_ED_BX % _ED_Q, _ED_BY % _ED_Q, 1, (_ED_BX * _ED_BY) % _ED_Q)


def _ed_add(p_pt: tuple[int, int, int, int], q_pt: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    x1, y1, z1, t1 = p_pt
    x2, y2, z2, t2 = q_pt
    a = ((y1 - x1) * (y2 - x2)) % _ED_Q
    b = ((y1 + x1) * (y2 + x2)) % _ED_Q
    c = (t1 * 2 * _ED_D * t2) % _ED_Q
    d = (z1 * 2 * z2) % _ED_Q
    e = (b - a) % _ED_Q
    f = (d - c) % _ED_Q
    g = (d + c) % _ED_Q
    h = (b + a) % _ED_Q
    return ((e * f) % _ED_Q, (g * h) % _ED_Q, (f * g) % _ED_Q, (e * h) % _ED_Q)


def _ed_mul(p_pt: tuple[int, int, int, int], scalar: int) -> tuple[int, int, int, int]:
    res = (0, 1, 1, 0)
    cur = p_pt
    e = int(scalar)
    while e > 0:
        if e & 1:
            res = _ed_add(res, cur)
        cur = _ed_add(cur, cur)
        e >>= 1
    return res


def _ed_encode(p_pt: tuple[int, int, int, int]) -> bytes:
    x, y, z, _ = p_pt
    zi = pow(z, _ED_Q - 2, _ED_Q)
    xp = (x * zi) % _ED_Q
    yp = (y * zi) % _ED_Q
    out = bytearray(yp.to_bytes(32, "little"))
    if xp & 1:
        out[31] |= 0x80
    return bytes(out)


def _ed_decode(raw: bytes) -> tuple[int, int, int, int]:
    if len(raw) != 32:
        raise ValueError("Invalid Ed25519 point length")
    y = int.from_bytes(raw, "little") & ((1 << 255) - 1)
    if y >= _ED_Q:
        raise ValueError("Ed25519 y coordinate out of range")
    sign = (raw[31] >> 7) & 1
    xx = (y * y - 1) * pow(_ED_D * y * y + 1, _ED_Q - 2, _ED_Q) % _ED_Q
    x = pow(xx, (_ED_Q + 3) // 8, _ED_Q)
    if (x * x - xx) % _ED_Q != 0:
        x = (x * _ED_I) % _ED_Q
    if (x * x - xx) % _ED_Q != 0:
        raise ValueError("Point is not on Ed25519 curve")
    if x == 0 and sign == 1:
        raise ValueError("Invalid negative zero point")
    if (x & 1) != sign:
        x = _ED_Q - x
    return (x, y, 1, (x * y) % _ED_Q)


def _ed25519_pubkey(seed32: bytes) -> bytes:
    if len(seed32) != 32:
        raise ValueError("Ed25519 private seed must be 32 bytes")
    h = bytearray(hashlib.sha512(seed32).digest())
    h[0] &= 248
    h[31] &= 127
    h[31] |= 64
    a = int.from_bytes(h[:32], "little")
    return _ed_encode(_ed_mul(_ED_BASE, a))


def _ed25519_sign(seed32: bytes, message: bytes) -> bytes:
    if len(seed32) != 32:
        raise ValueError("Ed25519 private seed must be 32 bytes")
    h = bytearray(hashlib.sha512(seed32).digest())
    h[0] &= 248
    h[31] &= 127
    h[31] |= 64
    a = int.from_bytes(h[:32], "little")
    prefix = bytes(h[32:])
    pub = _ed_encode(_ed_mul(_ED_BASE, a))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % _ED_L
    r_enc = _ed_encode(_ed_mul(_ED_BASE, r))
    k = int.from_bytes(hashlib.sha512(r_enc + pub + message).digest(), "little") % _ED_L
    s_val = (r + k * a) % _ED_L
    return r_enc + s_val.to_bytes(32, "little")


def _ed25519_verify(pub32: bytes, message: bytes, sig64: bytes) -> bool:
    if len(pub32) != 32 or len(sig64) != 64:
        return False
    s_val = int.from_bytes(sig64[32:], "little")
    if s_val >= _ED_L:
        return False
    try:
        a_pt = _ed_decode(pub32)
        r_pt = _ed_decode(sig64[:32])
    except ValueError:
        return False
    k = int.from_bytes(hashlib.sha512(sig64[:32] + pub32 + message).digest(), "little") % _ED_L
    lhs = _ed_mul(_ED_BASE, 8 * s_val)
    rhs = _ed_mul(_ed_add(r_pt, _ed_mul(a_pt, k)), 8)
    return hmac.compare_digest(_ed_encode(lhs), _ed_encode(rhs))


def _format_colon_hex(raw: bytes) -> str:
    return ":".join(f"{b:02x}" for b in raw)


def _parse_colon_hex(text: str) -> bytes:
    cleaned = re.sub(r"[^0-9a-fA-F]", "", str(text or ""))
    if not cleaned or (len(cleaned) % 2) != 0:
        raise ValueError("Invalid hex string")
    return bytes.fromhex(cleaned)


def _compute_core_bundle_digest(anchor_root: Path | str | None = None) -> str:
    """Deterministic SHA-256 (colon-hex) over normalized LF bytes of `CORE_ATTESTED_FILES`."""
    root = _code_dir(anchor_root)
    h = hashlib.sha256()
    counted = 0
    for rel in CORE_ATTESTED_FILES:
        fp = root / rel
        if fp.is_file():
            raw = fp.read_bytes().replace(b"\r\n", b"\n")
            h.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(raw).digest() + b"\n")
            counted += 1
    return _format_colon_hex(h.digest()) if counted > 0 else ""


def _canonical_release_signal_bytes(doc: dict[str, Any]) -> bytes:
    core = {
        "schema": str(doc.get("schema") or ""),
        "channel": str(doc.get("channel") or "stable"),
        "version": str(doc.get("version") or ""),
        "min_auto_update_version": str(doc.get("min_auto_update_version") or "1.5.0"),
        "published_at": str(doc.get("published_at") or ""),
        "repo_url": str(doc.get("repo_url") or DEFAULT_GITHUB_REPO),
        "exe_zip_url": str(doc.get("exe_zip_url") or ""),
        "core_sha256": str(doc.get("core_sha256") or ""),
        "notes": str(doc.get("notes") or ""),
        "key_id": str(doc.get("key_id") or ""),
    }
    return json.dumps(core, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def build_signed_release_signal(
    *,
    version: str,
    private_seed_bytes: bytes | None = None,
    key_file: Path | str | None = None,
    anchor_root: Path | str | None = None,
    core_sha256: str | None = None,
    min_auto_update_version: str = "1.5.0",
    notes: str = "",
    channel: str = "stable",
    repo_url: str = DEFAULT_GITHUB_REPO,
    exe_zip_url: str = "",
    published_at: str = "",
    key_id: str = RELEASE_SIGNAL_KEY_ID,
) -> dict[str, Any]:
    """Create and Ed25519-sign a public `release-signal.json` document (signing occurs on Homebase only)."""
    clean_ver = str(version or "").strip()
    if not re.match(r"^\d+\.\d+\.\d+(?:\.\d+)?$", clean_ver):
        raise ValueError(f"Invalid semantic version for release signal: {version!r}")
    seed = private_seed_bytes
    eff_kid = str(key_id or RELEASE_SIGNAL_KEY_ID).strip()
    if seed is None:
        kp = Path(key_file) if key_file is not None else (_data_dir() / ".anchor" / "keys" / "release-ed25519.key")
        key_doc = json.loads(kp.read_text(encoding="utf-8"))
        seed = _parse_colon_hex(str(key_doc.get("private_seed_hex") or ""))
        if key_doc.get("key_id"):
            eff_kid = str(key_doc["key_id"]).strip()
    pub_time = str(published_at or "").strip() or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    eff_zip = str(exe_zip_url or "").strip() or f"https://github.com/johncliechty/ghostworldlabs-anchor/releases/download/v{clean_ver}/Anchor.zip"
    eff_core_sha = (
        str(core_sha256).strip()
        if core_sha256 is not None
        else (_compute_core_bundle_digest(anchor_root) if (anchor_root is not None or private_seed_bytes is None) else "")
    )
    doc: dict[str, Any] = {
        "schema": RELEASE_SIGNAL_SCHEMA,
        "channel": str(channel or "stable").strip(),
        "version": clean_ver,
        "min_auto_update_version": str(min_auto_update_version or "1.5.0").strip(),
        "published_at": pub_time,
        "repo_url": str(repo_url or DEFAULT_GITHUB_REPO).strip(),
        "exe_zip_url": eff_zip,
        "core_sha256": eff_core_sha,
        "notes": str(notes or f"Anchor v{clean_ver} collaborator release.").strip(),
        "key_id": eff_kid,
    }
    sig = _ed25519_sign(seed, _canonical_release_signal_bytes(doc))
    doc["signature"] = _format_colon_hex(sig)
    return doc


def verify_release_signal(
    doc: dict[str, Any],
    *,
    pubkey_bytes: bytes | None = None,
    expected_key_id: str = RELEASE_SIGNAL_KEY_ID,
    expected_channel: str = "stable",
) -> tuple[bool, str]:
    """Verify an `anchor.release.signal.v1` JSON payload against the pinned Homebase Ed25519 public key."""
    if not isinstance(doc, dict):
        return False, "invalid_payload_type"
    if str(doc.get("schema") or "") != RELEASE_SIGNAL_SCHEMA:
        return False, "unsupported_schema"
    if expected_channel and str(doc.get("channel") or "stable").strip() != expected_channel:
        return False, "channel_mismatch"
    ver = str(doc.get("version") or "").strip()
    if not re.match(r"^\d+\.\d+\.\d+(?:\.\d+)?$", ver):
        return False, "invalid_version"
    kid = str(doc.get("key_id") or "").strip()
    if expected_key_id and kid != expected_key_id:
        return False, "unexpected_key_id"
    repo_u = str(doc.get("repo_url") or DEFAULT_GITHUB_REPO).strip()
    if repo_u not in ALLOWED_RELEASE_REPOS:
        return False, "untrusted_repo_url"
    zip_u = str(doc.get("exe_zip_url") or "").strip()
    if zip_u and not zip_u.startswith("https://github.com/johncliechty/"):
        return False, "untrusted_exe_zip_url"
    try:
        sig_raw = _parse_colon_hex(str(doc.get("signature") or ""))
    except ValueError:
        return False, "malformed_signature"
    use_custom_pub = (pubkey_bytes is not None) and ("PYTEST_CURRENT_TEST" in os.environ)
    eff_pub = pubkey_bytes if use_custom_pub else bytes(PINNED_RELEASE_PUBKEY_BYTES)
    if not _ed25519_verify(eff_pub, _canonical_release_signal_bytes(doc), sig_raw):
        return False, "invalid_ed25519_signature"
    return True, "verified"


# ── Zero-dependency v1.5.0/v1.5.1 -> v1.5.x `paths` compatibility shims ──────

def _code_dir(anchor_root: Path | str | None = None) -> Path:
    if anchor_root is not None:
        return Path(anchor_root).expanduser().resolve()
    cd = getattr(paths, "CODE_DIR", None)
    if cd is not None:
        return Path(cd).resolve()
    return Path(__file__).resolve().parent


def _data_dir(anchor_root: Path | str | None = None) -> Path:
    if anchor_root is not None:
        return Path(anchor_root).expanduser().resolve()
    fn = getattr(paths, "data_dir", None)
    if callable(fn):
        return Path(fn()).resolve()
    raw_env = (os.environ.get("ANCHOR_DATA_DIR") or "").strip()
    if raw_env:
        return Path(raw_env).expanduser().resolve()
    return _code_dir()


def _write_lock():
    lk = getattr(paths, "WRITE_LOCK", None)
    return lk if lk is not None else _FALLBACK_WRITE_LOCK


def _read_version(anchor_root: Path | str | None = None) -> str:
    fn = getattr(paths, "read_version", None)
    if callable(fn):
        return str(fn() if anchor_root is None else fn(anchor_root)).strip()
    base = _code_dir(anchor_root)
    for cand in (base / "VERSION", _code_dir() / "VERSION", Path(__file__).resolve().parent / "VERSION"):
        try:
            if cand.is_file():
                lines = [ln.strip() for ln in cand.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip()]
                if lines:
                    return lines[0]
        except Exception:
            continue
    return "1.5.1"


def _read_collaborator_display_name(default: str = "Collaborator", base_dir: Path | str | None = None) -> str:
    fn = getattr(paths, "read_collaborator_display_name", None)
    if callable(fn):
        try:
            return str(fn(base_dir=base_dir, default=default))
        except TypeError:
            return str(fn(base_dir, default))
    root = _data_dir(base_dir)
    code_d = _code_dir()
    for cand in (
        root / ".anchor" / "user_profile.json",
        root / "user_profile.json",
        code_d / ".anchor" / "user_profile.json",
    ):
        try:
            if cand.is_file():
                doc = json.loads(cand.read_text(encoding="utf-8"))
                if isinstance(doc, dict):
                    dn = str(doc.get("display_name") or doc.get("pseudonym") or "").strip()
                    if dn:
                        return dn
        except Exception:
            continue
    return default


def _resolve_ecgberht_root(anchor_root: Path | str | None = None) -> tuple[Path, list[str]]:
    fn = getattr(paths, "resolve_ecgberht_root", None)
    if callable(fn):
        return fn(anchor_root=anchor_root)
    base = _code_dir(anchor_root)
    parent = base.parent
    candidates: list[Path] = []
    for env_name in ("ECGBERHT_ROOT", "ECGBERHT_DIR"):
        raw = (os.environ.get(env_name) or "").strip()
        if raw:
            candidates.append(Path(raw).expanduser())
    candidates.extend([
        parent / "skills" / "ecgberht",
        base / "skills" / "ecgberht",
        base / "vendor" / "bundled-skills" / "ecgberht",
        parent / "Ecgberht",
    ])
    checked = [str(c) for c in candidates]
    for c in candidates:
        try:
            if (
                (c / "scripts" / "seal-chamber-bridge.mjs").is_file()
                or (c / "bin" / "ecgberht.mjs").is_file()
                or (c / "scripts" / "commission-run-bridge.mjs").is_file()
            ):
                os.environ.setdefault("ECGBERHT_ROOT", str(c))
                return c, checked
        except OSError:
            continue
    for c in candidates:
        try:
            if c.is_dir():
                os.environ.setdefault("ECGBERHT_ROOT", str(c))
                return c, checked
        except OSError:
            continue
    return candidates[0] if candidates else (base / "vendor" / "bundled-skills" / "ecgberht"), checked


def _atomic_write_text(path: Path | str, text: str, encoding: str = "utf-8") -> None:
    fn = getattr(paths, "atomic_write_text", None)
    if callable(fn):
        fn(path, text, encoding=encoding) if encoding != "utf-8" else fn(path, text)
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f"{p.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
            fh.flush()
            with contextlib.suppress(OSError):
                os.fsync(fh.fileno())
        os.replace(str(tmp), str(p))
    finally:
        if tmp.exists():
            with contextlib.suppress(OSError):
                tmp.unlink()


def _safe_urlopen(req, timeout: float = 6.0):
    fn = getattr(paths, "safe_urlopen", None)
    if callable(fn):
        return fn(req, timeout=timeout)
    url_s = req.full_url if hasattr(req, "full_url") else str(req)
    parsed = urllib.parse.urlparse(url_s)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.netloc:
        raise ValueError(f"Disallowed URL scheme in updater: {parsed.scheme!r}")
    return urllib.request.urlopen(req, timeout=timeout)  # noqa: S310


def _file_sha256(path: Path) -> str:
    try:
        if path.is_file():
            return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        pass
    return ""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_version(text: str | None) -> tuple[int, ...]:
    parts = re.findall(r"\d+", str(text or ""))
    if not parts:
        return (0, 0, 0)
    nums = [int(p) for p in parts[:4]]
    while len(nums) < 3:
        nums.append(0)
    return tuple(nums)


def _repo_registry_path(anchor_root: Path | str | None = None) -> Path:
    return _code_dir(anchor_root) / REGISTRY_FILENAME


def _runtime_registry_path(anchor_root: Path | str | None = None) -> Path:
    return _data_dir(anchor_root) / ".anchor" / REGISTRY_FILENAME


def _detect_platform_tag() -> str:
    sys_name = (platform.system() or sys.platform or "").lower()
    if "darwin" in sys_name or "mac" in sys_name:
        machine = (platform.machine() or "").lower()
        return "macos-arm64" if ("arm" in machine or "aarch64" in machine) else "macos-x64"
    if "linux" in sys_name:
        return "linux"
    return "windows"


def load_mothership_registry(anchor_root: Path | str | None = None) -> dict[str, Any]:
    """Load and merge the repo-tracked `mothership_registry.json` and local `.anchor/mothership_registry.json`."""
    repo_p = _repo_registry_path(anchor_root)
    rt_p = _runtime_registry_path(anchor_root)

    base_doc: dict[str, Any] = {
        "schema": REGISTRY_SCHEMA,
        "latest_version": _read_version(anchor_root),
        "canonical_github_repo": DEFAULT_GITHUB_REPO,
        "updated_at": _utc_now_iso(),
        "motherships": [],
    }
    by_id: dict[str, dict[str, Any]] = {}

    for cand in (repo_p, rt_p):
        if not cand.is_file():
            continue
        try:
            raw = json.loads(cand.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                continue
            if raw.get("latest_version"):
                if parse_version(str(raw["latest_version"])) >= parse_version(base_doc["latest_version"]):
                    base_doc["latest_version"] = str(raw["latest_version"]).strip()
            for item in raw.get("motherships") or []:
                if isinstance(item, dict) and item.get("id"):
                    mid = str(item["id"]).strip()
                    merged = dict(by_id.get(mid) or {})
                    merged.update(item)
                    by_id[mid] = merged
        except Exception:
            continue

    base_doc["motherships"] = list(by_id.values())
    return base_doc


def save_mothership_registry(
    doc: dict[str, Any],
    *,
    anchor_root: Path | str | None = None,
    write_repo: bool = True,
) -> dict[str, Any]:
    """Persist the Mother Ship registry to `.anchor/mothership_registry.json` and (when `write_repo=True`) `mothership_registry.json`."""
    payload = dict(doc)
    payload["schema"] = REGISTRY_SCHEMA
    payload["updated_at"] = _utc_now_iso()
    txt = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"

    rt_p = _runtime_registry_path(anchor_root)
    rt_p.parent.mkdir(parents=True, exist_ok=True)
    _atomic_write_text(rt_p, txt)

    if write_repo:
        repo_p = _repo_registry_path(anchor_root)
        try:
            _atomic_write_text(repo_p, txt)
        except OSError:
            pass
    return payload


def register_mothership_in_repo(
    entry: dict[str, Any],
    *,
    anchor_root: Path | str | None = None,
    write_repo: bool = True,
) -> dict[str, Any]:
    """Register or update a Mother Ship entry in `mothership_registry.json` + `.anchor/mothership_registry.json`."""
    owner = str(entry.get("owner") or entry.get("display_name") or "").strip() or _read_collaborator_display_name("Collaborator", base_dir=anchor_root)
    pseudonym = str(entry.get("pseudonym") or "").strip() or owner
    hostname = str(entry.get("hostname") or socket.gethostname() or "mothership").strip()
    raw_id = str(entry.get("id") or "").strip()
    if not raw_id:
        slug_base = re.sub(r"[^a-z0-9]+", "-", f"{owner}-{hostname}".lower()).strip("-")
        raw_id = slug_base or "mothership-node"

    tailscale_url = str(entry.get("tailscale_url") or entry.get("endpoint") or "").strip()
    if tailscale_url and not tailscale_url.startswith(("http://", "https://")):
        tailscale_url = "https://" + tailscale_url
    github_repo = str(entry.get("github_repo") or DEFAULT_GITHUB_REPO).strip()
    plat = str(entry.get("platform") or _detect_platform_tag()).strip().lower()
    ver = str(entry.get("installed_version") or entry.get("version_installed") or _read_version(anchor_root)).strip()
    role = str(entry.get("role") or "collaborator").strip().lower()
    install_dir = str(entry.get("install_dir") or ("C:/dev/Anchor" if os.name == "nt" else "~/dev/Anchor")).strip()

    reg = load_mothership_registry(anchor_root)
    items: list[dict[str, Any]] = list(reg.get("motherships") or [])
    existing_idx = next((i for i, m in enumerate(items) if str(m.get("id")) == raw_id), None)

    record: dict[str, Any] = (dict(items[existing_idx]) if existing_idx is not None else {})
    record.update({
        "id": raw_id,
        "owner": owner,
        "pseudonym": pseudonym,
        "role": role,
        "hostname": hostname,
        "tailscale_url": tailscale_url,
        "github_repo": github_repo,
        "platform": plat,
        "install_dir": install_dir,
        "installed_version": ver,
        "version_installed": ver,
        "last_seen_at": _utc_now_iso(),
    })
    if "pending_update" not in record:
        record["pending_update"] = None
    if record.get("pending_update") and isinstance(record["pending_update"], dict):
        target_v = str(record["pending_update"].get("target_version") or "")
        if parse_version(ver) >= parse_version(target_v):
            record["pending_update"] = None

    if existing_idx is not None:
        items[existing_idx] = record
    else:
        items.append(record)

    reg["motherships"] = items
    if parse_version(ver) > parse_version(str(reg.get("latest_version") or "0.0.0")):
        reg["latest_version"] = ver
    saved = save_mothership_registry(reg, anchor_root=anchor_root, write_repo=write_repo)

    # Also mirror into mothership_collab peer list when available
    try:
        import mothership_collab as _mc
        if tailscale_url:
            _mc.register_peer({
                "id": raw_id,
                "pseudonym": pseudonym,
                "label": f"{owner} ({pseudonym}) · {hostname}",
                "transport": "tailscale_http",
                "endpoint": tailscale_url,
                "role": role,
            })
    except Exception:
        pass

    return {
        "ok": True,
        "registered": record,
        "registry": saved,
    }


def get_version_status(anchor_root: Path | str | None = None) -> dict[str, Any]:
    """Return local Anchor version, Ecgberht engine version, platform, hardware/low-spec mode, license & Mother Ship registry summary."""
    ver = _read_version(anchor_root)
    ecg_root, _checked = _resolve_ecgberht_root(anchor_root=anchor_root)
    ecg_ver = ver
    try:
        if (ecg_root / "VERSION").is_file():
            ecg_ver = (ecg_root / "VERSION").read_text(encoding="utf-8").strip() or ver
    except OSError:
        pass
    reg = load_mothership_registry(anchor_root)
    motherships = reg.get("motherships") or []
    hostname = (socket.gethostname() or "").strip().lower()
    local_ms = next(
        (
            m for m in motherships
            if str(m.get("hostname") or "").lower() == hostname
            or (hostname in ("puter", "gwl-server") and str(m.get("id")) == "gwl-server-lead")
        ),
        None,
    )
    hw_fn = getattr(paths, "detect_host_hardware_profile", None)
    hw = hw_fn() if callable(hw_fn) else {"cpu_cores": int(os.cpu_count() or 2), "total_ram_gb": 0.0, "low_spec_recommended": False}
    link = read_homebase_link(anchor_root)
    low_spec = bool(link.get("low_spec_mode", hw.get("low_spec_recommended", False)))
    upd_st = read_update_status(anchor_root)
    lic_status: dict[str, Any] = {"accepted": False, "license_id": "GHOST-WORLD-LAB-NON-RESALE-v1", "version": "1.0-r2"}
    try:
        import website_portal as _wp
        store_d = (_data_dir(anchor_root) / ".anchor") if anchor_root is not None else None
        lic_status = _wp.get_local_license_status(store_dir=store_d)
    except Exception:
        pass
    return {
        "ok": True,
        "version": ver,
        "release_version": ver,
        "display_version": f"v{ver}",
        "ecgberht_version": ecg_ver,
        "ecgberht_root": str(ecg_root),
        "platform": _detect_platform_tag(),
        "hostname": socket.gethostname() or "localhost",
        "collaborator_name": _read_collaborator_display_name("John", base_dir=anchor_root),
        "mothership_id": (local_ms or {}).get("id") or "",
        "mothership": local_ms,
        "registered_motherships_count": len(motherships),
        "latest_known_version": str(reg.get("latest_version") or ver),
        "low_spec_mode": low_spec,
        "hardware_profile": hw,
        "auto_pull_updates": bool(link.get("auto_pull_updates", True)),
        "release_watch_url": str(link.get("release_watch_url") or DEFAULT_RELEASE_SIGNAL_URL),
        "update_status": upd_st,
        "update_ready_for_reload": bool(upd_st.get("update_ready_for_reload") and parse_version(str(upd_st.get("applied_version") or "")) > parse_version(ver)),
        "license_status": lic_status,
    }


def _default_run(cmd: list[str], cwd: Path | str | None = None, timeout: int = 120):
    kwargs: dict[str, Any] = {
        "cwd": str(cwd) if cwd else None,
        "capture_output": True,
        "text": True,
        "timeout": timeout,
    }
    if os.name == "nt":
        kwargs["creationflags"] = 0x08000000
    return subprocess.run(cmd, **kwargs)


def check_for_updates(
    anchor_root: Path | str | None = None,
    *,
    remote_url: str | None = None,
    check_website: bool = False,
    runner_fn=None,
    opener_fn=None,
) -> dict[str, Any]:
    """Check whether a newer version of Anchor is available from signed website signal, git origin, Lead Mother Ship, or registry."""
    root = _code_dir(anchor_root)
    local_ver = _read_version(root)
    reg = load_mothership_registry(root)
    latest_ver = str(reg.get("latest_version") or local_ver).strip()
    source = "local_registry"
    notes = ""
    signal_verified = False
    tamper_rejected = False
    exe_zip_url = ""

    # Check if local mothership record has a pending_update pushed from Lead Mother Ship
    hostname = (socket.gethostname() or "").strip().lower()
    for m in reg.get("motherships") or []:
        if str(m.get("hostname") or "").lower() == hostname or str(m.get("id") or "") == os.environ.get("ANCHOR_MOTHERSHIP_ID", ""):
            pend = m.get("pending_update")
            if isinstance(pend, dict) and pend.get("target_version"):
                pv = str(pend["target_version"]).strip()
                if parse_version(pv) > parse_version(latest_ver):
                    latest_ver = pv
                    source = "mothership_push_bulletin"
                    notes = str(pend.get("notes") or "")

    link = read_homebase_link(anchor_root)
    eff_remote = (
        str(remote_url).strip()
        if remote_url
        else (
            str(os.environ.get("ANCHOR_RELEASE_WATCH_URL") or link.get("release_watch_url") or DEFAULT_RELEASE_SIGNAL_URL).strip()
            if (check_website or opener_fn is not None)
            else ""
        )
    )

    open_url = opener_fn
    if open_url is None and eff_remote:
        def _default_open(u: str, timeout: float = 3.5):
            req = urllib.request.Request(u, headers={"User-Agent": f"Anchor-Updater/{local_ver}"})
            return _safe_urlopen(req, timeout=min(float(timeout), 15.0))
        open_url = _default_open

    if open_url is not None and eff_remote:
        try:
            with open_url(eff_remote, timeout=3.5) as resp:
                raw_txt = resp.read(16384).decode("utf-8", errors="replace").strip()
                if raw_txt.startswith("{"):
                    doc = json.loads(raw_txt)
                    if str(doc.get("schema") or "") == RELEASE_SIGNAL_SCHEMA:
                        ok_sig, _why = verify_release_signal(doc)
                        if ok_sig:
                            signal_verified = True
                            cand_v = str(doc.get("version") or "").strip()
                            notes = str(doc.get("notes") or notes).strip()
                            exe_zip_url = str(doc.get("exe_zip_url") or "").strip()
                        else:
                            tamper_rejected = True
                            cand_v = ""
                    else:
                        cand_v = str(doc.get("version") or doc.get("release_version") or doc.get("latest_version") or "").strip()
                else:
                    cand_v = raw_txt.splitlines()[0].strip() if raw_txt else ""
                if cand_v and parse_version(cand_v) > parse_version(latest_ver):
                    latest_ver = cand_v
                    source = eff_remote
        except Exception:
            if eff_remote == DEFAULT_RELEASE_SIGNAL_URL and remote_url is None and opener_fn is None:
                try:
                    with open_url(RAW_VERSION_URL, timeout=3.0) as resp2:
                        cand_v2 = resp2.read(1024).decode("utf-8", errors="replace").strip().splitlines()[0].strip()
                        if cand_v2 and parse_version(cand_v2) > parse_version(latest_ver):
                            latest_ver = cand_v2
                            source = RAW_VERSION_URL
                except Exception:
                    pass

    # Optional git check if runner_fn is provided or git repo exists and remote_url is not synthetic
    if runner_fn is not None and (root / ".git").is_dir():
        try:
            res = runner_fn(["git", "-C", str(root), "show", "origin/main:VERSION"], cwd=str(root))
            cand_v = (getattr(res, "stdout", "") or "").strip()
            if getattr(res, "returncode", 1) == 0 and cand_v and parse_version(cand_v) > parse_version(latest_ver):
                latest_ver = cand_v
                source = "git_origin_main"
        except Exception:
            pass

    upd_st = read_update_status(anchor_root)
    applied_v = str(upd_st.get("applied_version") or "").strip()
    ready_reload = bool(upd_st.get("update_ready_for_reload") and applied_v)
    update_available = parse_version(latest_ver) > parse_version(local_ver)
    return {
        "ok": True,
        "local_version": local_ver,
        "display_version": f"v{local_ver}",
        "latest_version": latest_ver,
        "remote_version": f"v{latest_ver}",
        "update_available": update_available,
        "up_to_date": not update_available,
        "source": source,
        "signal_verified": signal_verified,
        "tamper_rejected": tamper_rejected,
        "exe_zip_url": exe_zip_url,
        "update_ready_for_reload": ready_reload,
        "applied_version": applied_v,
        "notes": notes,
        "checked_at": _utc_now_iso(),
    }


def _sync_bundled_skills_for_root(root: Path) -> tuple[list[str], str]:
    src_skills = root / "vendor" / "bundled-skills"
    ws_skills = root.parent / "skills"
    if not src_skills.is_dir():
        return [], ""
    rep = onboard.install_skills(skills_src=src_skills, skills_home=ws_skills, overwrite=True)
    installed = [
        (item["name"] if isinstance(item, dict) else str(item))
        for item in (rep.get("installed") or [])
    ]
    return installed, f"skills_synced:{len(installed)}"


def pull_latest_update(
    anchor_root: Path | str | None = None,
    *,
    target_version: str | None = None,
    runner_fn=None,
    sync_skills: bool = True,
    bootstrap_git: bool = False,
) -> dict[str, Any]:
    """Pull and apply the latest Anchor update in-place, refreshing all bundled Foundry skills while preserving `.anchor/`."""
    global onboard, paths
    root = _code_dir(anchor_root)
    before_ver = _read_version(root)
    run = runner_fn or _default_run
    git_updated = False
    overlay_extracted = False
    details: list[str] = []

    core_files = ("mothership_updater.py", "paths.py", "onboard.py")
    before_core_digests = {fn: _file_sha256(root / fn) for fn in core_files}

    if (root / ".git").is_dir():
        try:
            f_res = run(["git", "-C", str(root), "fetch", "origin"], cwd=str(root))
            if getattr(f_res, "returncode", 1) == 0:
                stashed_pre_pull = False
                has_non_eol_edits = False
                st_res = run(["git", "-C", str(root), "status", "--porcelain"], cwd=str(root))
                porcelain_lines = [
                    ln for ln in (getattr(st_res, "stdout", "") or "").splitlines()
                    if ln.strip() and not ln.startswith("??")
                ]
                if getattr(st_res, "returncode", 1) == 0 and porcelain_lines:
                    diff_res = run(["git", "-C", str(root), "diff", "--ignore-cr-at-eol", "--quiet"], cwd=str(root))
                    has_non_eol_edits = getattr(diff_res, "returncode", 0) != 0
                    stash_res = run(["git", "-C", str(root), "stash", "push", "-m", "anchor-auto-pull-crlf"], cwd=str(root))
                    stashed_pre_pull = getattr(stash_res, "returncode", 1) == 0
                    if stashed_pre_pull:
                        details.append("git_stashed_tracked_changes")

                p_res = run(["git", "-C", str(root), "pull", "--ff-only"], cwd=str(root))
                if getattr(p_res, "returncode", 1) != 0 and not stashed_pre_pull:
                    stash_res = run(["git", "-C", str(root), "stash", "push", "-m", "anchor-auto-pull-crlf"], cwd=str(root))
                    stashed_pre_pull = getattr(stash_res, "returncode", 1) == 0
                    p_res = run(["git", "-C", str(root), "pull", "--ff-only"], cwd=str(root))
                if getattr(p_res, "returncode", 1) == 0:
                    git_updated = True
                    details.append("git_pull_ff_only")
                    if stashed_pre_pull and has_non_eol_edits:
                        pop_res = run(["git", "-C", str(root), "stash", "pop"], cwd=str(root))
                        if getattr(pop_res, "returncode", 0) != 0:
                            run(["git", "-C", str(root), "checkout", "--", "."], cwd=str(root))
                            details.append("git_stash_conflict_kept_clean_head")
                        else:
                            details.append("git_restored_user_edits")
        except Exception as exc:
            details.append(f"git_skipped:{exc}")
    elif bootstrap_git and (runner_fn is not None or shutil.which("git")):
        # Convert an overlay-extracted C:\dev\Anchor install into a git-tracked install
        # while preserving all user markdown and .anchor / .ecgberht directories.
        user_md_rels = (
            "DASHBOARD.md",
            "PROJECTS.md",
            "INBOX.md",
            "CANCELLED.md",
            "SAVED_FOR_LATER.md",
            "WEEKLY_REVIEW.md",
            "rnd_registry.json",
            "projects.json",
            "settings.json",
            "anchor-edition.json",
            "domains/academic.md",
            "domains/commercial.md",
            "domains/family.md",
            "domains/writing.md",
        )
        saved_md: dict[str, str] = {}
        for rel_m in user_md_rels:
            mp = root / rel_m
            if mp.is_file():
                try:
                    saved_md[rel_m] = mp.read_text(encoding="utf-8", errors="replace")
                except OSError:
                    pass
        try:
            root.mkdir(parents=True, exist_ok=True)
            i_res = run(["git", "-C", str(root), "init"], cwd=str(root))
            if getattr(i_res, "returncode", 1) == 0:
                run(["git", "-C", str(root), "remote", "add", "origin", DEFAULT_GITHUB_REPO], cwd=str(root))
                f_res = run(["git", "-C", str(root), "fetch", "--depth=1", "origin", "main"], cwd=str(root))
                if getattr(f_res, "returncode", 1) == 0:
                    c_res = run(["git", "-C", str(root), "checkout", "-f", "-B", "main", "origin/main"], cwd=str(root))
                    if getattr(c_res, "returncode", 1) == 0:
                        git_updated = True
                        details.append("git_bootstrapped_from_origin")
        except Exception as exc:
            details.append(f"git_bootstrap_skipped:{exc}")
        finally:
            if not git_updated and (root / ".git").is_dir():
                shutil.rmtree(root / ".git", ignore_errors=True)
            for rel_m, txt_m in saved_md.items():
                mp = root / rel_m
                mp.parent.mkdir(parents=True, exist_ok=True)
                try:
                    _atomic_write_text(mp, txt_m)
                except OSError:
                    pass

    # Apply bundled overlay only when git did not already update the tree
    if not git_updated:
        try:
            import importlib.util as _ilu
            conn_py = root / "shell" / "connect.py"
            if conn_py.is_file():
                spec = _ilu.spec_from_file_location("anchor_shell_connect", str(conn_py))
                if spec and spec.loader:
                    mod = _ilu.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    if mod._apply_bundled_core_overlay(root):
                        overlay_extracted = True
                        details.append("overlay_applied")
        except Exception:
            pass

    after_core_digests = {fn: _file_sha256(root / fn) for fn in core_files}
    core_files_changed = (git_updated or overlay_extracted) and (after_core_digests != before_core_digests)
    if core_files_changed:
        for mod_attr, mod_obj in (("paths", paths), ("onboard", onboard)):
            try:
                if getattr(mod_obj, "__spec__", None) is not None:
                    reloaded = importlib.reload(mod_obj)
                    if mod_attr == "paths":
                        paths = reloaded
                    else:
                        onboard = reloaded
            except Exception:
                pass
        details.append("reloaded_core_updater_modules")

    clean_tv = str(target_version or "").strip()
    if (
        clean_tv
        and re.match(r"^\d+\.\d+\.\d+(?:\.\d+)?$", clean_tv)
        and (git_updated or overlay_extracted or runner_fn is not None)
        and parse_version(clean_tv) > parse_version(_read_version(root))
    ):
        try:
            _atomic_write_text(root / "VERSION", clean_tv + "\n")
            if (root / "vendor" / "bundled-skills" / "ecgberht").is_dir():
                _atomic_write_text(root / "vendor" / "bundled-skills" / "ecgberht" / "VERSION", clean_tv + "\n")
        except OSError:
            pass

    skills_installed: list[str] = []
    if sync_skills:
        src_skills = root / "vendor" / "bundled-skills"
        if src_skills.is_dir():
            reexec_done = False
            if (
                core_files_changed
                and _CLI_MAIN_MODE
                and os.environ.get("ANCHOR_UPDATER_REEXEC") != "1"
                and (root / "mothership_updater.py").is_file()
            ):
                try:
                    env_child = dict(os.environ, ANCHOR_UPDATER_REEXEC="1")
                    re_kw: dict[str, Any] = {
                        "cwd": str(root),
                        "env": env_child,
                        "capture_output": True,
                        "text": True,
                        "timeout": 120,
                    }
                    if os.name == "nt":
                        re_kw["creationflags"] = 0x08000000
                    re_res = subprocess.run(
                        [sys.executable, str(root / "mothership_updater.py"), "--sync-skills-only", "--anchor-root", str(root)],
                        **re_kw,
                    )
                    if getattr(re_res, "returncode", 1) == 0 and (re_res.stdout or "").strip():
                        re_doc = json.loads(re_res.stdout)
                        skills_installed = list(re_doc.get("skills_installed") or [])
                        details.append(f"reexec_skills_synced:{len(skills_installed)}")
                        reexec_done = True
                except Exception:
                    reexec_done = False
            if not reexec_done:
                try:
                    skills_installed, sk_note = _sync_bundled_skills_for_root(root)
                    if sk_note:
                        details.append(sk_note)
                except Exception as exc:
                    details.append(f"skills_error:{exc}")

    after_ver = _read_version(root)
    # Update registry record for this host so pending_update is cleared once updated
    reg = load_mothership_registry(root)
    hostname = (socket.gethostname() or "").strip().lower()
    changed_reg = False
    for m in reg.get("motherships") or []:
        if str(m.get("hostname") or "").lower() == hostname:
            m["installed_version"] = after_ver
            m["last_seen_at"] = _utc_now_iso()
            m["pending_update"] = None
            changed_reg = True
    if parse_version(after_ver) >= parse_version(str(reg.get("latest_version") or "0.0.0")):
        reg["latest_version"] = after_ver
        changed_reg = True
    if changed_reg:
        save_mothership_registry(reg, anchor_root=root, write_repo=False)

    # Refresh ECGBERHT_ROOT resolution so stale C:\dev\Ecgberht is never used
    ecg_root, _ = _resolve_ecgberht_root(anchor_root=root)

    did_update = (after_ver != before_ver) or git_updated or overlay_extracted or bool(skills_installed)
    method = "git" if git_updated else ("overlay" if overlay_extracted else "in_place")
    if parse_version(after_ver) > parse_version(before_ver):
        save_update_status(
            {
                "update_ready_for_reload": True,
                "applied_version": after_ver,
                "previous_version": before_ver,
                "applied_at": _utc_now_iso(),
                "method": method,
                "skills_synced_count": len(skills_installed),
            },
            anchor_root=anchor_root,
        )

    return {
        "ok": True,
        "before_version": before_ver,
        "after_version": after_ver,
        "display_version": f"v{after_ver}",
        "method": method,
        "updated": did_update,
        "git_updated": git_updated,
        "overlay_extracted": overlay_extracted,
        "core_files_changed": core_files_changed,
        "skills_installed_count": len(skills_installed),
        "skills_installed": skills_installed,
        "skills_synced": skills_installed,
        "ecgberht_root": str(ecg_root),
        "details": details,
        "updated_at": _utc_now_iso(),
        "message": f"Anchor updated to v{after_ver} ({len(skills_installed)} Foundry skills synced).",
    }


def push_update_to_motherships(
    *,
    target_id: str = "",
    notes: str = "",
    push_git: bool = True,
    anchor_root: Path | str | None = None,
    runner_fn=None,
    opener_fn=None,
) -> dict[str, Any]:
    """Push the latest Anchor version from Lead Mother Ship to GitHub and registered Mother Ships."""
    eff_anchor = Path(anchor_root).resolve() if anchor_root is not None else None
    root = eff_anchor or _code_dir()
    local_ver = _read_version(eff_anchor)
    run = runner_fn or _default_run
    reg = load_mothership_registry(eff_anchor)
    reg["latest_version"] = local_ver
    now_iso = _utc_now_iso()

    git_pushed = False
    if push_git and (root / ".git").is_dir() and runner_fn is not None:
        try:
            p_res = run(["git", "-C", str(root), "push", "origin", "HEAD"], cwd=str(root))
            git_pushed = getattr(p_res, "returncode", 1) == 0
        except Exception:
            git_pushed = False

    peer_caps = _load_homebase_peer_capabilities(eff_anchor)

    def _default_post(url: str, payload: dict[str, Any], node_cap: str = ""):
        data = json.dumps(payload).encode("utf-8")
        hdrs = {
            "Content-Type": "application/json",
            "User-Agent": f"Anchor-Mothership-Push/{local_ver}",
        }
        if node_cap:
            hdrs["X-Anchor-Node-Capability"] = node_cap
        req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
        return _safe_urlopen(req, timeout=6.0)

    post_fn = opener_fn
    results: list[dict[str, Any]] = []
    hostname = (socket.gethostname() or "").strip().lower()

    for m in reg.get("motherships") or []:
        mid = str(m.get("id") or "")
        if target_id and mid != target_id:
            continue
        m_host = str(m.get("hostname") or "").lower()
        is_self = (
            str(m.get("role") or "").lower() == "lead"
            or mid == "gwl-server-lead"
            or (anchor_root is None and m_host == hostname)
        )
        m["last_push_at"] = now_iso
        if is_self and not target_id:
            m["installed_version"] = local_ver
            m["pending_update"] = None
            results.append({"id": mid, "owner": m.get("owner"), "status": "lead_self", "version": local_ver})
            continue

        ts_url = str(m.get("tailscale_url") or "").strip().rstrip("/")
        node_cap = str(peer_caps.get(mid) or "").strip()
        pushed_live = False
        live_error = ""
        if ts_url:
            endpoint = f"{ts_url}/api/system/pull_update"
            try:
                body_push = {"target_version": local_ver, "pushed_by": hostname or "lead", "notes": notes}
                call_ctx = (
                    post_fn(endpoint, body_push)
                    if post_fn is not None
                    else _default_post(endpoint, body_push, node_cap=node_cap)
                )
                with call_ctx as resp:
                    status_code = getattr(resp, "status", 200)
                    if status_code == 200:
                        pushed_live = True
                        m["installed_version"] = local_ver
                        m["pending_update"] = None
            except Exception as exc:
                live_error = str(exc)

        if not pushed_live:
            m["pending_update"] = {
                "target_version": local_ver,
                "pushed_by": hostname or "gwl-server-lead",
                "pushed_at": now_iso,
                "notes": notes or f"Anchor v{local_ver} release pushed from Mother Ship.",
            }
        results.append({
            "id": mid,
            "owner": m.get("owner"),
            "tailscale_url": ts_url,
            "pushed_live": pushed_live,
            "queued_bulletin": not pushed_live,
            "target_version": local_ver,
            "error": live_error,
        })

    allow_repo_write = (
        eff_anchor is not None
        or (
            _data_dir() == _code_dir()
            and "PYTEST_CURRENT_TEST" not in os.environ
        )
    )
    saved = save_mothership_registry(reg, anchor_root=eff_anchor, write_repo=allow_repo_write)
    return {
        "ok": True,
        "version": local_ver,
        "git_pushed": git_pushed,
        "results": results,
        "registry": saved,
        "pushed_at": now_iso,
        "message": f"Pushed Anchor v{local_ver} to {len(results)} registered Mother Ship(s).",
    }


# ── Standard Setup: Homebase Registration, Push Auth & Journal/Error Sync ────

def _data_anchor_dir(anchor_root: Path | str | None = None, *, create: bool = True) -> Path:
    p = _data_dir(anchor_root) / ".anchor"
    if create:
        p.mkdir(parents=True, exist_ok=True)
    return p


def _homebase_link_path(anchor_root: Path | str | None = None, *, create: bool = True) -> Path:
    return _data_anchor_dir(anchor_root, create=create) / HOMEBASE_LINK_FILENAME


def _homebase_peer_caps_path(anchor_root: Path | str | None = None, *, create: bool = True) -> Path:
    return _data_anchor_dir(anchor_root, create=create) / HOMEBASE_PEERS_CAP_FILENAME


def _load_homebase_peer_capabilities(anchor_root: Path | str | None = None) -> dict[str, str]:
    fp = _homebase_peer_caps_path(anchor_root, create=False)
    if not fp.is_file():
        return {}
    try:
        raw = json.loads(fp.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            peers = raw.get("peers") if isinstance(raw.get("peers"), dict) else raw
            return {str(k): str(v) for k, v in peers.items() if isinstance(v, str) and v.strip()}
    except Exception:
        pass
    return {}


def _save_homebase_peer_capability(
    mothership_id: str,
    node_capability: str,
    *,
    anchor_root: Path | str | None = None,
) -> None:
    mid = str(mothership_id or "").strip()
    cap = str(node_capability or "").strip()
    if not mid or len(cap) < 16:
        return
    with _write_lock():
        peers = _load_homebase_peer_capabilities(anchor_root)
        peers[mid] = cap
        fp = _homebase_peer_caps_path(anchor_root, create=True)
        _atomic_write_text(
            fp,
            json.dumps({"schema": "anchor.homebase.peer_caps.v1", "updated_at": _utc_now_iso(), "peers": peers}, indent=2) + "\n",
        )


def _env_or_default_homebase_url() -> str:
    raw = (os.environ.get("ANCHOR_HOMEBASE_URL") or "").strip().rstrip("/")
    if raw:
        return raw if raw.startswith(("http://", "https://")) else f"https://{raw}"
    return DEFAULT_HOMEBASE_URL


def _update_status_path(anchor_root: Path | str | None = None, *, create: bool = True) -> Path:
    return _data_anchor_dir(anchor_root, create=create) / UPDATE_STATUS_FILENAME


def read_update_status(anchor_root: Path | str | None = None) -> dict[str, Any]:
    fp = _update_status_path(anchor_root, create=False)
    if fp.is_file():
        try:
            doc = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(doc, dict):
                return doc
        except Exception:
            pass
    return {
        "schema": "anchor.update.status.v1",
        "update_ready_for_reload": False,
        "applied_version": "",
        "last_website_check_at": "",
        "last_seen_signal_version": "",
        "signal_verified": False,
    }


def save_update_status(patch: dict[str, Any], *, anchor_root: Path | str | None = None) -> dict[str, Any]:
    with _write_lock():
        cur = read_update_status(anchor_root)
        cur.update(patch or {})
        cur["schema"] = "anchor.update.status.v1"
        cur["updated_at"] = _utc_now_iso()
        fp = _update_status_path(anchor_root, create=True)
        _atomic_write_text(fp, json.dumps(cur, indent=2) + "\n")
        return cur


def _default_low_spec_flag() -> bool:
    hw_fn = getattr(paths, "detect_host_hardware_profile", None)
    if callable(hw_fn):
        try:
            return bool(hw_fn().get("low_spec_recommended", False))
        except Exception:
            return False
    return False


def _validate_release_watch_url(raw_url: str) -> str:
    u = str(raw_url or "").strip()
    if not u:
        return DEFAULT_RELEASE_SIGNAL_URL
    parsed = urllib.parse.urlsplit(u)
    host = (parsed.hostname or "").lower()
    if parsed.scheme == "https" and host:
        return u
    if parsed.scheme == "http" and host in ("127.0.0.1", "localhost", "::1"):
        return u
    raise ValueError("Release signal watch URL must use https:// (or localhost in local tests).")


def read_homebase_link(anchor_root: Path | str | None = None) -> dict[str, Any]:
    """Pure read-only load of `.anchor/homebase_link.json` (never writes or mints capabilities)."""
    fp = _homebase_link_path(anchor_root, create=False)
    if fp.is_file():
        try:
            loaded = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                loaded.setdefault("auto_pull_updates", True)
                loaded.setdefault("release_watch_url", DEFAULT_RELEASE_SIGNAL_URL)
                if "low_spec_mode" not in loaded:
                    loaded["low_spec_mode"] = _default_low_spec_flag()
                return loaded
        except Exception:
            pass
    return {
        "schema": HOMEBASE_LINK_SCHEMA,
        "homebase_url": _env_or_default_homebase_url(),
        "telemetry_enabled": True,
        "auto_pull_updates": True,
        "release_watch_url": DEFAULT_RELEASE_SIGNAL_URL,
        "low_spec_mode": _default_low_spec_flag(),
        "registered": False,
        "registered_at": "",
        "mothership_id": "",
        "last_telemetry_at": "",
        "node_capability": "",
    }


def load_or_init_homebase_link(
    anchor_root: Path | str | None = None,
    *,
    homebase_url: str | None = None,
    telemetry_enabled: bool | None = None,
    auto_pull_updates: bool | None = None,
    low_spec_mode: bool | None = None,
    release_watch_url: str | None = None,
    owner: str = "",
    hostname: str = "",
) -> dict[str, Any]:
    """Load or initialize `.anchor/homebase_link.json` under `_write_lock()` (never committed to git)."""
    with _write_lock():
        fp = _homebase_link_path(anchor_root, create=True)
        doc: dict[str, Any] = {}
        if fp.is_file():
            try:
                loaded = json.loads(fp.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    doc = loaded
            except Exception:
                doc = {}

        changed = False
        if doc.get("schema") != HOMEBASE_LINK_SCHEMA:
            doc["schema"] = HOMEBASE_LINK_SCHEMA
            changed = True
        if not str(doc.get("node_capability") or "").strip():
            doc["node_capability"] = secrets.token_hex(24)
            changed = True
        eff_hb_override = str(homebase_url or "").strip()
        if eff_hb_override:
            hb = eff_hb_override.rstrip("/")
            if not hb.startswith(("http://", "https://")):
                hb = "https://" + hb
            if doc.get("homebase_url") != hb:
                doc["homebase_url"] = hb
                changed = True
        elif not str(doc.get("homebase_url") or "").strip():
            doc["homebase_url"] = _env_or_default_homebase_url()
            changed = True

        if telemetry_enabled is not None:
            if bool(doc.get("telemetry_enabled", True)) != bool(telemetry_enabled):
                doc["telemetry_enabled"] = bool(telemetry_enabled)
                changed = True
        elif "telemetry_enabled" not in doc:
            doc["telemetry_enabled"] = True
            changed = True
        if auto_pull_updates is not None:
            if bool(doc.get("auto_pull_updates", True)) != bool(auto_pull_updates):
                doc["auto_pull_updates"] = bool(auto_pull_updates)
                changed = True
        elif "auto_pull_updates" not in doc:
            doc["auto_pull_updates"] = True
            changed = True
        if low_spec_mode is not None:
            if bool(doc.get("low_spec_mode", False)) != bool(low_spec_mode):
                doc["low_spec_mode"] = bool(low_spec_mode)
                changed = True
        elif "low_spec_mode" not in doc:
            doc["low_spec_mode"] = _default_low_spec_flag()
            changed = True
        if release_watch_url is not None and str(release_watch_url).strip():
            valid_watch = _validate_release_watch_url(str(release_watch_url))
            if doc.get("release_watch_url") != valid_watch:
                doc["release_watch_url"] = valid_watch
                changed = True
        elif not str(doc.get("release_watch_url") or "").strip():
            doc["release_watch_url"] = DEFAULT_RELEASE_SIGNAL_URL
            changed = True

        host_val = str(hostname or doc.get("hostname") or socket.gethostname() or "mothership").strip()
        owner_val = str(owner or doc.get("owner") or _read_collaborator_display_name("Collaborator", base_dir=anchor_root)).strip()
        if not str(doc.get("mothership_id") or "").strip():
            slug = re.sub(r"[^a-z0-9]+", "-", f"{owner_val}-{host_val}".lower()).strip("-") or "mothership-node"
            if slug == "gwl-server-lead" or slug.startswith("gwl-server-"):
                slug = f"collab-{slug}"
            doc["mothership_id"] = slug
            changed = True
        doc.setdefault("owner", owner_val)
        doc.setdefault("hostname", host_val)
        doc.setdefault("registered", False)
        doc.setdefault("registered_at", "")
        doc.setdefault("last_telemetry_at", "")
        if not isinstance(doc.get("watermarks"), dict):
            doc["watermarks"] = {"errors_offset": 0, "journal_sigs": {}, "health_report_sig": ""}
            changed = True

        if changed or not fp.is_file():
            doc["updated_at"] = _utc_now_iso()
            _atomic_write_text(fp, json.dumps(doc, indent=2) + "\n")
        return doc


def save_homebase_link(doc: dict[str, Any], *, anchor_root: Path | str | None = None) -> dict[str, Any]:
    with _write_lock():
        fp = _homebase_link_path(anchor_root, create=True)
        payload = dict(doc)
        payload["schema"] = HOMEBASE_LINK_SCHEMA
        payload["updated_at"] = _utc_now_iso()
        _atomic_write_text(fp, json.dumps(payload, indent=2) + "\n")
        return payload


def verify_pull_update_capability(provided_cap: str | None, anchor_root: Path | str | None = None) -> bool:
    """Read-only verification of `X-Anchor-Node-Capability` on `POST /api/system/pull_update`."""
    cand = str(provided_cap or "").strip()
    if len(cand) < 16:
        return False
    link = read_homebase_link(anchor_root)
    expected = str(link.get("node_capability") or "").strip()
    if len(expected) < 16:
        return False
    return hmac.compare_digest(cand, expected)


def detect_local_tailscale_endpoint(runner_fn=None) -> dict[str, Any]:
    """Detect local Tailscale IP and MagicDNS / HTTPS endpoint if Tailscale is running."""
    ts_exe = shutil.which("tailscale")
    if not ts_exe and os.name == "nt":
        cand = Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Tailscale" / "tailscale.exe"
        if cand.is_file():
            ts_exe = str(cand)
    out = {"installed": bool(ts_exe), "online": False, "tailscale_ip": "", "dns_name": "", "endpoint": "", "hostname": ""}
    if not ts_exe:
        return out
    run_call = runner_fn or _default_run
    try:
        res = run_call([ts_exe, "status", "--json"], timeout=6)
        if getattr(res, "returncode", 1) == 0 and getattr(res, "stdout", ""):
            data = json.loads(res.stdout)
            self_node = data.get("Self") or {}
            ips = self_node.get("TailscaleIPs") or []
            ts_ip = str(ips[0]) if ips else ""
            dns_name = str(self_node.get("DNSName") or "").strip().rstrip(".")
            host = str(self_node.get("HostName") or "").strip()
            online = str(data.get("BackendState") or "") == "Running"
            ep = f"https://{dns_name}" if dns_name else (f"http://{ts_ip}:8777" if ts_ip else "")
            out.update({
                "online": online,
                "tailscale_ip": ts_ip,
                "dns_name": dns_name,
                "endpoint": ep,
                "hostname": host,
            })
    except Exception:
        pass
    return out


def register_with_homebase(
    *,
    owner: str = "",
    contact_email: str = "",
    pseudonym: str = "",
    hostname: str = "",
    tailscale_url: str = "",
    tailscale_ip: str = "",
    homebase_url: str = "",
    telemetry_enabled: bool = True,
    anchor_root: Path | str | None = None,
    opener_fn=None,
    runner_fn=None,
) -> dict[str, Any]:
    """Standard Setup step: register this Anchor installation with the Anchor Homebase
    so Homebase can push updates directly (or queue outbound heartbeat updates) and receive sanitized journal/error reports."""
    ts_det = detect_local_tailscale_endpoint(runner_fn=runner_fn)
    eff_host = str(hostname or ts_det.get("hostname") or socket.gethostname() or "mothership").strip()
    eff_owner = str(owner or _read_collaborator_display_name("Collaborator", base_dir=anchor_root)).strip()
    eff_pseudo = str(pseudonym or eff_owner).strip()
    eff_ts_ip = str(tailscale_ip or ts_det.get("tailscale_ip") or "").strip()
    eff_ts_url = str(tailscale_url or ts_det.get("endpoint") or "").strip()
    if eff_ts_url and not eff_ts_url.startswith(("http://", "https://")):
        eff_ts_url = "https://" + eff_ts_url

    eff_hb_arg = str(homebase_url or os.environ.get("ANCHOR_HOMEBASE_URL") or "").strip()
    link = load_or_init_homebase_link(
        anchor_root,
        homebase_url=eff_hb_arg or None,
        telemetry_enabled=telemetry_enabled,
        owner=eff_owner,
        hostname=eff_host,
    )
    link["owner"] = eff_owner
    link["contact_email"] = str(contact_email or link.get("contact_email") or "").strip()
    link["pseudonym"] = eff_pseudo
    link["hostname"] = eff_host
    if eff_ts_url:
        link["tailscale_url"] = eff_ts_url
    if eff_ts_ip:
        link["tailscale_ip"] = eff_ts_ip

    ver = _read_version(anchor_root)
    plat = _detect_platform_tag()
    mid = str(link["mothership_id"])

    # Always maintain local runtime registry without touching repo-tracked files during collaborator setup
    register_mothership_in_repo(
        {
            "id": mid,
            "owner": eff_owner,
            "pseudonym": eff_pseudo,
            "hostname": eff_host,
            "tailscale_url": eff_ts_url,
            "platform": plat,
            "installed_version": ver,
            "role": "lead" if eff_host.lower() in ("puter", "gwl-server") else "collaborator",
        },
        anchor_root=anchor_root,
        write_repo=False,
    )

    # If this node IS the Lead Homebase itself, mark self-registered immediately
    configured_hb = str(link.get("homebase_url") or DEFAULT_HOMEBASE_URL).strip().rstrip("/")
    is_self_homebase = (
        anchor_root is None
        and eff_host.lower() in ("puter", "gwl-server")
        and opener_fn is None
        and (not eff_hb_arg or "gwl-server" in configured_hb or "puter" in configured_hb)
    )
    if is_self_homebase:
        link["registered"] = True
        link["registered_at"] = _utc_now_iso()
        saved_self = save_homebase_link(link, anchor_root=anchor_root)
        return {"ok": True, "mode": "homebase_self", "mothership_id": mid, "link": _public_link_view(saved_self)}

    reg_body = {
        "action": "register_homebase",
        "mothership": {
            "id": mid,
            "owner": eff_owner,
            "contact_email": link.get("contact_email", ""),
            "pseudonym": eff_pseudo,
            "hostname": eff_host,
            "tailscale_ip": eff_ts_ip,
            "tailscale_url": eff_ts_url,
            "platform": plat,
            "installed_version": ver,
            "telemetry_enabled": bool(link.get("telemetry_enabled", True)),
            "node_capability": link["node_capability"],
        },
    }

    target_hb = str(eff_hb_arg or configured_hb or DEFAULT_HOMEBASE_URL).strip().rstrip("/")
    if target_hb and not target_hb.startswith(("http://", "https://")):
        target_hb = "https://" + target_hb

    def _post_json(url: str, obj: dict[str, Any]):
        raw = json.dumps(obj).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=raw,
            headers={"Content-Type": "application/json", "User-Agent": f"Anchor-Homebase-Register/{ver}"},
            method="POST",
        )
        return _safe_urlopen(req, timeout=4.0)

    post_call = opener_fn or _post_json
    reached_url = ""
    last_err = ""
    if target_hb.startswith(("http://", "https://")):
        target_u = f"{target_hb}/api/onboard-wizard/action"
        try:
            with post_call(target_u, reg_body) as resp:
                code = getattr(resp, "status", 200)
                resp_bytes = resp.read(16384)
                resp_doc = json.loads(resp_bytes.decode("utf-8", errors="replace")) if resp_bytes else {}
                if code == 200 and resp_doc.get("ok"):
                    reached_url = target_hb
                else:
                    last_err = str(resp_doc.get("error") or f"HTTP {code}")
        except Exception as exc:
            last_err = str(exc)

    if reached_url:
        link["homebase_url"] = reached_url
        link["registered"] = True
        link["registered_at"] = _utc_now_iso()
        link["last_error"] = ""
    else:
        link["last_error"] = last_err

    saved_link = save_homebase_link(link, anchor_root=anchor_root)
    tel_res = None
    if reached_url and saved_link.get("telemetry_enabled", True):
        try:
            tel_res = sync_telemetry_to_homebase(anchor_root=anchor_root, opener_fn=opener_fn)
        except Exception:
            tel_res = None

    return {
        "ok": bool(reached_url),
        "registered": bool(reached_url),
        "mothership_id": mid,
        "homebase_url": reached_url or target_hb or configured_hb,
        "tailscale_url": eff_ts_url,
        "telemetry_enabled": bool(saved_link.get("telemetry_enabled", True)),
        "telemetry_sync": tel_res,
        "error": "" if reached_url else (last_err or "Homebase unreachable — ensure Tailscale is connected."),
        "link": _public_link_view(saved_link),
    }


def _public_link_view(link: dict[str, Any]) -> dict[str, Any]:
    """Return strictly whitelisted display metadata for UI/receipts (never exposing secrets or PII)."""
    src = link or {}
    return {
        "registered": bool(src.get("registered")),
        "registered_at": str(src.get("registered_at") or ""),
        "mothership_id": str(src.get("mothership_id") or ""),
        "homebase_url": str(src.get("homebase_url") or DEFAULT_HOMEBASE_URL),
        "telemetry_enabled": bool(src.get("telemetry_enabled", True)),
        "auto_pull_updates": bool(src.get("auto_pull_updates", True)),
        "release_watch_url": str(src.get("release_watch_url") or DEFAULT_RELEASE_SIGNAL_URL),
        "low_spec_mode": bool(src.get("low_spec_mode", _default_low_spec_flag())),
        "last_telemetry_at": str(src.get("last_telemetry_at") or ""),
        "has_capability": bool(str(src.get("node_capability") or "").strip()),
    }


def configure_update_and_hardware_preferences(
    *,
    auto_pull_updates: bool | None = None,
    low_spec_mode: bool | None = None,
    release_watch_url: str | None = None,
    anchor_root: Path | str | None = None,
) -> dict[str, Any]:
    """Save collaborator website auto-update & Older Laptop Low-Memory Mode settings."""
    try:
        link = load_or_init_homebase_link(
            anchor_root,
            auto_pull_updates=None if auto_pull_updates is None else bool(auto_pull_updates),
            low_spec_mode=None if low_spec_mode is None else bool(low_spec_mode),
            release_watch_url=release_watch_url if (release_watch_url is not None and str(release_watch_url).strip()) else None,
        )
        return {"ok": True, "link": _public_link_view(link)}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}


def receive_homebase_registration(
    payload: dict[str, Any],
    *,
    provided_capability: str | None = None,
    anchor_root: Path | str | None = None,
) -> dict[str, Any]:
    """Homebase handler (`action='register_homebase'`): pin peer capability on first use (TOFU),
    refuse impersonation or reserved lead IDs, and register collaborator for push updates & telemetry."""
    ms = payload.get("mothership") if isinstance(payload.get("mothership"), dict) else payload
    if not isinstance(ms, dict):
        return {"ok": False, "status_code": 400, "error": "invalid_payload"}

    owner = str(ms.get("owner") or ms.get("display_name") or "Collaborator").strip()[:80]
    hostname = str(ms.get("hostname") or "mothership").strip()[:80]
    raw_id = str(ms.get("id") or "").strip()
    safe_id = re.sub(r"[^a-z0-9_-]+", "-", (raw_id or f"{owner}-{hostname}").lower()).strip("-")[:80] or "collaborator-node"
    if (
        safe_id in ("gwl-server-lead", "lead")
        or safe_id.startswith("gwl-server-")
        or str(ms.get("role") or "").strip().lower() == "lead"
    ):
        return {"ok": False, "status_code": 403, "error": "reserved_mothership_id"}

    node_cap = str(ms.get("node_capability") or "").strip()
    if len(node_cap) < 16:
        return {"ok": False, "status_code": 400, "error": "missing_node_capability"}

    prev_cap = str(ms.get("previous_node_capability") or provided_capability or "").strip()
    with _write_lock():
        peers = _load_homebase_peer_capabilities(anchor_root)
        existing_cap = str(peers.get(safe_id) or "").strip()
        if existing_cap:
            same_cap = hmac.compare_digest(node_cap, existing_cap)
            valid_rotation = bool(prev_cap and hmac.compare_digest(prev_cap, existing_cap))
            if not (same_cap or valid_rotation):
                return {
                    "ok": False,
                    "status_code": 409,
                    "error": "peer_already_registered_capability_mismatch",
                }
        peers[safe_id] = node_cap
        fp = _homebase_peer_caps_path(anchor_root, create=True)
        _atomic_write_text(
            fp,
            json.dumps({"schema": "anchor.homebase.peer_caps.v1", "updated_at": _utc_now_iso(), "peers": peers}, indent=2) + "\n",
        )

    ts_ip = str(ms.get("tailscale_ip") or "").strip()[:64]
    ts_url = str(ms.get("tailscale_url") or "").strip()[:200]
    if not ts_url and ts_ip:
        ts_url = f"http://{ts_ip}:8777"
    pseudonym = str(ms.get("pseudonym") or owner).strip()[:80]
    ver = str(ms.get("installed_version") or _read_version(anchor_root)).strip()[:32]
    plat = str(ms.get("platform") or "windows").strip()[:32]

    with _write_lock():
        reg_out = register_mothership_in_repo(
            {
                "id": safe_id,
                "owner": owner,
                "pseudonym": pseudonym,
                "role": "collaborator",
                "hostname": hostname,
                "tailscale_url": ts_url,
                "platform": plat,
                "installed_version": ver,
            },
            anchor_root=anchor_root,
            write_repo=False,
        )

    try:
        import gwl_clearinghouse as _gwl
        hub_root = (Path(anchor_root).resolve() / ".anchor" / "gwl_hub") if anchor_root is not None else None
        _gwl.register_applicant_signup(
            {
                "display_name": owner,
                "username": re.sub(r"[^a-z0-9_.-]+", "", owner.lower().split()[0]) if owner else safe_id,
                "contact_email": str(ms.get("contact_email") or "").strip()[:120],
                "pseudonym": pseudonym,
                "hostname": hostname,
                "tailscale_ip": ts_ip,
                "tailscale_endpoint": ts_url or "http://127.0.0.1:8777",
                "topology_mode": "main_mothership",
                "onboarding_status": "ready",
                "notes": f"Registered with Homebase (v{ver}, telemetry={'on' if ms.get('telemetry_enabled', True) else 'off'})",
            },
            hub_root=hub_root,
        )
    except Exception:
        pass

    return {
        "ok": True,
        "mothership_id": safe_id,
        "registered": reg_out.get("registered"),
        "push_updates_ready": bool(ts_url),
        "telemetry_ready": True,
    }


def _scrub_telemetry_text(text: str, max_chars: int = 2400) -> str:
    s = aap.scrub_private_identity_leaks(str(text or ""))
    s = re.sub(r"(?i)([?&](?:token|auth|api_key|apikey|key|secret|sig|capability|password)=)[^&\s\"']+", r"\1<redacted>", s)
    s = re.sub(
        r"(?i)((?:x-anchor-token|x-anchor-node-capability|authorization|cookie|set-cookie|anchor_token)\s*[:=]\s*)[^\r\n\"']+",
        r"\1<redacted>",
        s,
    )
    s = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]+", r"\1<redacted>", s)
    s = re.sub(
        r"\b(?:sk-[A-Za-z0-9_\-]{12,}|gh[pousr]_[A-Za-z0-9]{16,}|github_pat_[A-Za-z0-9_]{20,}|AIza[0-9A-Za-z_\-]{20,}|xox[baprs]-[A-Za-z0-9\-]{12,}|AKIA[0-9A-Z]{16}|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})\b",
        "<redacted>",
        s,
    )
    s = re.sub(r"\b[0-9a-fA-F]{32,}\b", "<redacted-hex>", s)
    s = re.sub(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "<redacted-email>", s)
    return s.strip()[:max_chars]


def collect_local_telemetry_delta(
    anchor_root: Path | str | None = None,
    *,
    max_items: int = 40,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collect unsent sanitized error log entries, health issues, and journal entries."""
    root = _code_dir(anchor_root)
    data_root = _data_dir(anchor_root)
    link = load_or_init_homebase_link(anchor_root)
    wm = dict(link.get("watermarks") or {})
    err_off = int(wm.get("errors_offset") or 0)
    j_sigs = dict(wm.get("journal_sigs") or {})
    prev_hc_sig = str(wm.get("health_report_sig") or "")

    events: list[dict[str, Any]] = []
    now_iso = _utc_now_iso()

    # 1. Incremental ERROR / CRITICAL / Traceback entries from logs/errors.log
    err_log = data_root / "logs" / "errors.log"
    if err_log.is_file():
        try:
            st_e = err_log.stat()
            if st_e.st_size < err_off:
                err_off = 0
            if st_e.st_size > err_off:
                with open(err_log, "rb") as fh:
                    # Cap initial tail read to last 64 KB so an old huge log never floods
                    start_at = max(err_off, max(0, st_e.st_size - 65536)) if err_off == 0 else err_off
                    fh.seek(start_at)
                    chunk = fh.read(131072).decode("utf-8", errors="replace")
                    new_off = fh.tell()
                err_blocks: list[str] = []
                cur_block: list[str] = []
                for line in chunk.splitlines():
                    if re.search(r"\b(ERROR|CRITICAL|Traceback)\b", line):
                        if cur_block and len("\n".join(cur_block)) > 400:
                            err_blocks.append("\n".join(cur_block))
                            cur_block = []
                        cur_block.append(line)
                    elif cur_block:
                        if line.startswith((" ", "\t")) or "Error:" in line or "Exception:" in line:
                            cur_block.append(line)
                        else:
                            err_blocks.append("\n".join(cur_block))
                            cur_block = []
                if cur_block:
                    err_blocks.append("\n".join(cur_block))
                for blk in err_blocks[-15:]:
                    if len(events) >= max_items:
                        break
                    events.append({
                        "kind": "error",
                        "source": "logs/errors.log",
                        "title": _scrub_telemetry_text(blk.splitlines()[0], 180),
                        "detail": _scrub_telemetry_text(blk, 2000),
                        "observed_at": now_iso,
                    })
                err_off = new_off
        except OSError:
            pass

    # 2. Latest health report issues (if Status != OK)
    hc_dir = data_root / "health_reports"
    if hc_dir.is_dir() and len(events) < max_items:
        try:
            reports = sorted(hc_dir.glob("*.md"), key=lambda p: p.name)
            if reports:
                latest_hp = reports[-1]
                st_h = latest_hp.stat()
                hc_sig = f"{latest_hp.name}:{st_h.st_mtime_ns}:{st_h.st_size}"
                if hc_sig != prev_hc_sig:
                    htxt = latest_hp.read_text(encoding="utf-8", errors="replace")
                    if "Status: ISSUES FOUND" in htxt or "Status: FAIL" in htxt:
                        events.append({
                            "kind": "health_issue",
                            "source": f"health_reports/{latest_hp.name}",
                            "title": f"Health report issues ({latest_hp.stem})",
                            "detail": _scrub_telemetry_text(htxt, 2200),
                            "observed_at": now_iso,
                        })
                    prev_hc_sig = hc_sig
        except OSError:
            pass

    # 3. Install journals, friction notes, and skill journal entries
    candidate_files: list[tuple[str, Path]] = []
    inst_j = data_root / ".anchor" / "install_journal.md"
    if inst_j.is_file():
        candidate_files.append((".anchor/install_journal.md", inst_j))
    for rel_sub in ("docs/friction", "friction"):
        sub_p = root / rel_sub
        if sub_p.is_dir():
            for fp in sorted(sub_p.glob("*")):
                if fp.is_file() and fp.suffix.lower() in (".md", ".json") and fp.name.lower() != "readme.md":
                    candidate_files.append((f"{rel_sub}/{fp.name}", fp))

    skills_dirs = [data_root.parent / "skills", Path.home() / "skills"]
    for s_root in skills_dirs:
        if s_root.is_dir():
            try:
                for sk_dir in sorted(s_root.iterdir()):
                    j_dir = sk_dir / "journal"
                    if j_dir.is_dir():
                        for j_fp in sorted(j_dir.glob("*.md")):
                            if j_fp.name.lower() != "readme.md":
                                candidate_files.append((f"skills/{sk_dir.name}/journal/{j_fp.name}", j_fp))
            except OSError:
                pass

    # On very first run with empty j_sigs, baseline pre-existing repo docs/friction files so only
    # `.anchor/install_journal.md` or newly authored journals after setup are transmitted.
    first_baseline = len(j_sigs) == 0
    for rel_label, fp in candidate_files:
        try:
            st_j = fp.stat()
        except OSError:
            continue
        sig = f"{st_j.st_mtime_ns}:{st_j.st_size}"
        if j_sigs.get(rel_label) == sig:
            continue
        if first_baseline and rel_label.startswith(("docs/friction/", "friction/", "skills/")) and anchor_root is None:
            j_sigs[rel_label] = sig
            continue
        if len(events) >= max_items:
            break
        try:
            j_txt = fp.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        first_ln = next((ln.lstrip("# ").strip() for ln in j_txt.splitlines() if ln.strip()), fp.name)
        events.append({
            "kind": "journal",
            "source": rel_label,
            "title": _scrub_telemetry_text(first_ln, 180),
            "detail": _scrub_telemetry_text(j_txt, 2400),
            "observed_at": now_iso,
        })
        j_sigs[rel_label] = sig

    if len(j_sigs) > 2000:
        j_sigs = dict(list(j_sigs.items())[-1500:])

    next_wm = {
        "errors_offset": err_off,
        "journal_sigs": j_sigs,
        "health_report_sig": prev_hc_sig,
    }
    return events, next_wm


def sync_telemetry_to_homebase(
    *,
    anchor_root: Path | str | None = None,
    opener_fn=None,
    extra_events: list[dict[str, Any]] | None = None,
    heartbeat_even_if_empty: bool = False,
    _is_followup_receipt: bool = False,
) -> dict[str, Any]:
    """Send unsent sanitized journal entries & error logs (or an outbound update-check heartbeat) to Anchor Homebase."""
    link = load_or_init_homebase_link(anchor_root)
    if not link.get("telemetry_enabled", True):
        return {"ok": True, "skipped": "telemetry_disabled", "sent_count": 0}

    events, next_wm = collect_local_telemetry_delta(anchor_root)
    if extra_events:
        for ev in extra_events[:20]:
            if isinstance(ev, dict):
                events.append({
                    "kind": str(ev.get("kind") or "journal")[:32],
                    "source": str(ev.get("source") or "manual")[:120],
                    "title": _scrub_telemetry_text(str(ev.get("title") or "Event"), 180),
                    "detail": _scrub_telemetry_text(str(ev.get("detail") or ""), 2400),
                    "observed_at": _utc_now_iso(),
                })

    if not events and not heartbeat_even_if_empty:
        link["watermarks"] = next_wm
        save_homebase_link(link, anchor_root=anchor_root)
        return {"ok": True, "sent_count": 0, "message": "No new journal entries or errors to send."}

    hb_url = str(link.get("homebase_url") or DEFAULT_HOMEBASE_URL).strip().rstrip("/")
    ver = _read_version(anchor_root)
    body = {
        "action": "submit_homebase_telemetry",
        "mothership_id": link["mothership_id"],
        "owner": link.get("owner") or "Collaborator",
        "hostname": link.get("hostname") or socket.gethostname() or "mothership",
        "version": ver,
        "platform": _detect_platform_tag(),
        "sent_at": _utc_now_iso(),
        "events": events,
    }

    def _post_tel(url: str, obj: dict[str, Any]):
        raw = json.dumps(obj).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=raw,
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"Anchor-Homebase-Telemetry/{ver}",
                "X-Anchor-Node-Capability": str(link["node_capability"]),
            },
            method="POST",
        )
        return _safe_urlopen(req, timeout=5.0)

    post_call = opener_fn or _post_tel
    target_u = f"{hb_url}/api/onboard-wizard/action"
    try:
        with post_call(target_u, body) as resp:
            code = getattr(resp, "status", 200)
            raw_r = resp.read(16384)
            r_doc = json.loads(raw_r.decode("utf-8", errors="replace")) if raw_r else {}
            if code == 200 and r_doc.get("ok"):
                link["watermarks"] = next_wm
                link["last_telemetry_at"] = _utc_now_iso()
                save_homebase_link(link, anchor_root=anchor_root)
                pend = r_doc.get("pending_update")
                out_res: dict[str, Any] = {
                    "ok": True,
                    "sent_count": len(events),
                    "heartbeat_sent": True,
                    "homebase_url": hb_url,
                    "latest_version": r_doc.get("latest_version"),
                    "pending_update": pend,
                }
                if (
                    not _is_followup_receipt
                    and isinstance(pend, dict)
                    and link.get("auto_pull_updates", True)
                ):
                    target_v = str(pend.get("target_version") or "").strip()
                    if target_v and parse_version(target_v) > parse_version(ver):
                        try:
                            pull_res = pull_latest_update(anchor_root=anchor_root, target_version=target_v)
                            out_res["auto_pull"] = pull_res
                            after_ver = str((pull_res or {}).get("after_version") or _read_version(anchor_root)).strip()
                            if (pull_res or {}).get("ok") and parse_version(after_ver) > parse_version(ver):
                                sync_telemetry_to_homebase(
                                    anchor_root=anchor_root,
                                    opener_fn=opener_fn,
                                    extra_events=[{
                                        "kind": "journal",
                                        "source": "mothership_updater",
                                        "title": f"Auto-applied Homebase update to v{after_ver}",
                                        "detail": f"Pulled pending Homebase update from v{ver} to v{after_ver} via outbound heartbeat.",
                                    }],
                                    heartbeat_even_if_empty=False,
                                    _is_followup_receipt=True,
                                )
                        except Exception as pull_exc:
                            out_res["auto_pull"] = {"ok": False, "error": str(pull_exc)}
                return out_res
            return {"ok": False, "sent_count": 0, "error": str(r_doc.get("error") or f"HTTP {code}")}
    except Exception as exc:
        return {"ok": False, "sent_count": 0, "error": str(exc)}


def receive_homebase_telemetry(
    payload: dict[str, Any],
    provided_capability: str | None,
    *,
    anchor_root: Path | str | None = None,
) -> dict[str, Any]:
    """Homebase receiver (`action='submit_homebase_telemetry'`): verify peer capability,
    store incoming collaborator journal entries & errors, and piggyback `pending_update`."""
    raw_id = str(payload.get("mothership_id") or "").strip()
    safe_id = re.sub(r"[^a-z0-9_-]+", "-", raw_id.lower()).strip("-")[:80]
    if not safe_id:
        return {"ok": False, "status_code": 400, "error": "missing_mothership_id"}

    peers = _load_homebase_peer_capabilities(anchor_root)
    expected_cap = str(peers.get(safe_id) or "").strip()
    cand_cap = str(provided_capability or payload.get("node_capability") or "").strip()
    if not expected_cap or not cand_cap or not hmac.compare_digest(cand_cap, expected_cap):
        return {"ok": False, "status_code": 401, "error": "unauthorized_node_capability"}

    raw_events = payload.get("events")
    if not isinstance(raw_events, list):
        return {"ok": False, "status_code": 400, "error": "invalid_events"}

    inbox_dir = _data_anchor_dir(anchor_root) / "homebase_telemetry" / safe_id
    inbox_dir.mkdir(parents=True, exist_ok=True)
    jsonl_p = inbox_dir / "events.jsonl"
    latest_md_p = inbox_dir / "LATEST.md"
    now_iso = _utc_now_iso()
    owner = str(payload.get("owner") or safe_id)[:80]
    host = str(payload.get("hostname") or "")[:80]
    ver = str(payload.get("version") or "")[:32]

    accepted: list[dict[str, Any]] = []
    matched_pending = None
    with _write_lock():
        if raw_events:
            if jsonl_p.is_file():
                try:
                    if jsonl_p.stat().st_size > 2 * 1024 * 1024:
                        tail_lines = jsonl_p.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]
                        _atomic_write_text(jsonl_p, "\n".join(tail_lines) + ("\n" if tail_lines else ""))
                except OSError:
                    pass
            with open(jsonl_p, "a", encoding="utf-8") as fh:
                for ev in raw_events[:50]:
                    if not isinstance(ev, dict):
                        continue
                    rec = {
                        "received_at": now_iso,
                        "mothership_id": safe_id,
                        "owner": owner,
                        "hostname": host,
                        "version": ver,
                        "kind": str(ev.get("kind") or "journal")[:32],
                        "source": _scrub_telemetry_text(str(ev.get("source") or ""), 160),
                        "title": _scrub_telemetry_text(str(ev.get("title") or ""), 200),
                        "detail": _scrub_telemetry_text(str(ev.get("detail") or ""), 2400),
                        "observed_at": str(ev.get("observed_at") or now_iso)[:40],
                    }
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    accepted.append(rec)

        if accepted or not latest_md_p.is_file():
            summary_lines = [
                f"# Homebase Telemetry — {owner} (`{safe_id}`)",
                f"- Host: `{host}` · Version: `v{ver}` · Updated: `{now_iso}`",
                f"- Last batch: {len(accepted)} event(s)",
                "",
            ]
            for item in accepted[-10:]:
                summary_lines.append(f"## [{item['kind'].upper()}] {item['title']} ({item['source']})")
                summary_lines.append(item["detail"])
                summary_lines.append("")
            _atomic_write_text(latest_md_p, "\n".join(summary_lines))

        # Update last_seen_at / installed_version and reconcile pending_update in Mother Ship registry
        reg = load_mothership_registry(anchor_root)
        for m in reg.get("motherships") or []:
            if str(m.get("id") or "") == safe_id:
                m["last_seen_at"] = now_iso
                m["last_telemetry_at"] = now_iso
                if ver:
                    m["installed_version"] = ver
                    m["version_installed"] = ver
                pend = m.get("pending_update")
                if isinstance(pend, dict):
                    pending_target = str(pend.get("target_version") or "").strip()
                    if ver and pending_target and parse_version(ver) >= parse_version(pending_target):
                        m["pending_update"] = None
                matched_pending = m.get("pending_update")
                save_mothership_registry(reg, anchor_root=anchor_root, write_repo=False)
                break

    return {
        "ok": True,
        "status_code": 200,
        "accepted_count": len(accepted),
        "mothership_id": safe_id,
        "latest_version": reg.get("latest_version"),
        "pending_update": matched_pending,
    }


def list_homebase_telemetry(
    *,
    mothership_id: str = "",
    limit: int | str = 100,
    anchor_root: Path | str | None = None,
) -> dict[str, Any]:
    """List received collaborator journal entries and error reports on Homebase."""
    try:
        cap_lim = max(1, min(int(limit or 100), 500))
    except (TypeError, ValueError):
        cap_lim = 100
    base = _data_anchor_dir(anchor_root, create=False) / "homebase_telemetry"
    items: list[dict[str, Any]] = []
    if base.is_dir():
        target_dirs = (
            [base / re.sub(r"[^a-z0-9_-]+", "-", mothership_id.lower()).strip("-")]
            if mothership_id
            else sorted(d for d in base.iterdir() if d.is_dir())
        )
        for d in target_dirs:
            jf = d / "events.jsonl"
            if not jf.is_file():
                continue
            try:
                lines = jf.read_text(encoding="utf-8", errors="replace").splitlines()
                for ln in lines[-cap_lim:]:
                    if ln.strip():
                        items.append(json.loads(ln))
            except Exception:
                continue
    items.sort(key=lambda r: str(r.get("received_at") or ""), reverse=True)
    return {"ok": True, "count": len(items[:cap_lim]), "events": items[:cap_lim]}


def _acquire_cross_process_update_lock(anchor_root: Path | str | None = None) -> Path | None:
    lock_p = _data_anchor_dir(anchor_root, create=True) / "auto_update.lock"
    if lock_p.is_file():
        try:
            age_s = time.time() - lock_p.stat().st_mtime
            if age_s > 900:
                lock_p.unlink(missing_ok=True)
        except OSError:
            pass
    try:
        fd = os.open(str(lock_p), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            os.write(fd, f"{os.getpid()} {_utc_now_iso()}\n".encode("utf-8"))
        finally:
            os.close(fd)
        return lock_p
    except OSError:
        return None


def is_host_busy_for_auto_update(anchor_root: Path | str | None = None) -> tuple[bool, str]:
    """Return `(True, reason)` if any Steward AI Cockpit turn, managed PTY session, or Foreman/code job is actively running."""
    try:
        import cave_processing_feed as _cpf
        snap = _cpf.snapshot()
        active_items = [x for x in (snap.get("items") or []) if isinstance(x, dict) and str(x.get("state") or "") in ("running", "working", "active")]
        if active_items:
            return True, f"active_processing_items:{len(active_items)}"
    except Exception:
        pass
    try:
        from steward_cockpit import steward_engine as _se
        eng = getattr(_se, "ENGINE", None)
        if eng is not None:
            for _k, sess in list((getattr(eng, "sessions", None) or {}).items()):
                if getattr(sess, "busy", False) or str(getattr(sess, "state", "") or "") in ("thinking", "working", "running"):
                    return True, "steward_turn_active"
    except Exception:
        pass
    try:
        import session_registry as _sreg
        live_rows = [r for r in (_sreg.list_sessions() or []) if isinstance(r, dict) and str(r.get("status") or "") in ("running", "working")]
        if live_rows:
            return True, f"active_terminal_sessions:{len(live_rows)}"
    except Exception:
        pass
    return False, ""


def poll_website_release_signal(
    anchor_root: Path | str | None = None,
    *,
    watch_url: str | None = None,
    opener_fn=None,
    runner_fn=None,
    busy_check_fn=None,
    pubkey_bytes: bytes | None = None,
    ignore_backoff: bool = False,
) -> dict[str, Any]:
    """Watch the public website `release-signal.json` (Tailscale-free!), verify its Ed25519 signature + `core_sha256`,
    and automatically pull + sync all 20 bundled Foundry skills when idle and `auto_pull_updates` is enabled."""
    root = _code_dir(anchor_root)
    local_ver = _read_version(root)
    link = read_homebase_link(anchor_root)
    cur_st = read_update_status(anchor_root)
    if not ignore_backoff and opener_fn is None:
        retry_after = float(cur_st.get("next_retry_epoch") or 0.0)
        if retry_after > time.time():
            return {"ok": True, "skipped_reason": "backoff_cooldown", "local_version": local_ver}
    raw_target = str(watch_url or os.environ.get("ANCHOR_RELEASE_WATCH_URL") or link.get("release_watch_url") or DEFAULT_RELEASE_SIGNAL_URL).strip()
    try:
        eff_url = _validate_release_watch_url(raw_target)
    except ValueError as exc:
        return {"ok": False, "error": str(exc), "local_version": local_ver}

    def _default_get(u: str, timeout: float = 5.0):
        req = urllib.request.Request(u, headers={"User-Agent": f"Anchor-Website-Watcher/{local_ver}"})
        return _safe_urlopen(req, timeout=min(float(timeout), 15.0))

    get_fn = opener_fn or _default_get
    now_iso = _utc_now_iso()
    try:
        with get_fn(eff_url, timeout=5.0) as resp:
            raw_bytes = resp.read(32769)
        if len(raw_bytes) > 32768:
            raise ValueError("signal_too_large")
        doc = json.loads(raw_bytes.decode("utf-8", errors="replace"))
    except Exception as exc:
        fails = int(cur_st.get("consecutive_failures") or 0) + 1
        backoff_s = min(10800, 900 * (2 ** min(fails - 1, 4)))
        save_update_status(
            {
                "last_website_check_at": now_iso,
                "last_website_error": str(exc)[:200],
                "consecutive_failures": fails,
                "next_retry_epoch": time.time() + backoff_s,
            },
            anchor_root=anchor_root,
        )
        return {"ok": False, "error": f"signal_fetch_failed:{exc}", "local_version": local_ver, "watch_url": eff_url}

    sig_ok, sig_reason = verify_release_signal(
        doc,
        pubkey_bytes=pubkey_bytes,
        expected_channel=str(link.get("channel") or "stable"),
    )
    if not sig_ok:
        save_update_status(
            {
                "last_website_check_at": now_iso,
                "signal_verified": False,
                "last_website_error": f"signature_rejected:{sig_reason}",
            },
            anchor_root=anchor_root,
        )
        return {
            "ok": False,
            "error": f"signature_rejected:{sig_reason}",
            "signal_verified": False,
            "tamper_rejected": True,
            "local_version": local_ver,
            "watch_url": eff_url,
        }

    signal_ver = str(doc.get("version") or "").strip()
    min_ver = str(doc.get("min_auto_update_version") or "1.5.0").strip()
    expected_core_sha = str(doc.get("core_sha256") or "").strip()
    notes = str(doc.get("notes") or "").strip()
    highest_seen = str(cur_st.get("highest_seen_signal_version") or "").strip()
    if highest_seen and parse_version(signal_ver) < parse_version(highest_seen):
        return {
            "ok": False,
            "error": "stale_replayed_signal",
            "signal_verified": True,
            "tamper_rejected": True,
            "local_version": local_ver,
            "signal_version": signal_ver,
        }
    new_highest = signal_ver if (not highest_seen or parse_version(signal_ver) >= parse_version(highest_seen)) else highest_seen
    has_newer = parse_version(signal_ver) > parse_version(local_ver)
    save_update_status(
        {
            "last_website_check_at": now_iso,
            "last_seen_signal_version": signal_ver,
            "highest_seen_signal_version": new_highest,
            "signal_verified": True,
            "last_website_error": "",
            "consecutive_failures": 0,
            "next_retry_epoch": 0.0,
            "notes": notes,
        },
        anchor_root=anchor_root,
    )
    if not has_newer:
        return {
            "ok": True,
            "local_version": local_ver,
            "signal_version": signal_ver,
            "signal_verified": True,
            "update_available": False,
            "auto_pulled": False,
            "watch_url": eff_url,
        }
    if parse_version(local_ver) < parse_version(min_ver):
        return {
            "ok": True,
            "local_version": local_ver,
            "signal_version": signal_ver,
            "signal_verified": True,
            "update_available": True,
            "auto_pulled": False,
            "manual_update_required": True,
            "watch_url": eff_url,
        }

    if not bool(link.get("auto_pull_updates", True)):
        return {
            "ok": True,
            "local_version": local_ver,
            "signal_version": signal_ver,
            "signal_verified": True,
            "update_available": True,
            "auto_pulled": False,
            "skipped_reason": "auto_pull_disabled",
            "watch_url": eff_url,
        }

    chk_busy = busy_check_fn or is_host_busy_for_auto_update
    busy, busy_reason = chk_busy(anchor_root)
    if busy:
        save_update_status({"deferred_busy": True, "deferred_reason": busy_reason}, anchor_root=anchor_root)
        return {
            "ok": True,
            "local_version": local_ver,
            "signal_version": signal_ver,
            "signal_verified": True,
            "update_available": True,
            "auto_pulled": False,
            "deferred_busy": True,
            "deferred_reason": busy_reason,
            "watch_url": eff_url,
        }

    if not _AUTO_UPDATE_LOCK.acquire(blocking=False):
        return {
            "ok": True,
            "local_version": local_ver,
            "signal_version": signal_ver,
            "signal_verified": True,
            "update_available": True,
            "auto_pulled": False,
            "skipped_reason": "auto_update_already_in_progress",
            "watch_url": eff_url,
        }
    proc_lock_file = _acquire_cross_process_update_lock(anchor_root)
    if proc_lock_file is None:
        _AUTO_UPDATE_LOCK.release()
        return {
            "ok": True,
            "local_version": local_ver,
            "signal_version": signal_ver,
            "signal_verified": True,
            "update_available": True,
            "auto_pulled": False,
            "skipped_reason": "cross_process_lock_held",
            "watch_url": eff_url,
        }
    try:
        run_call = runner_fn or _default_run
        prev_head = ""
        if (root / ".git").is_dir():
            try:
                hr = run_call(["git", "-C", str(root), "rev-parse", "HEAD"], cwd=str(root))
                if getattr(hr, "returncode", 1) == 0:
                    prev_head = str(getattr(hr, "stdout", "") or "").strip()
            except Exception:
                prev_head = ""

        pull_res = pull_latest_update(
            anchor_root=anchor_root,
            target_version=signal_ver,
            runner_fn=runner_fn,
            sync_skills=True,
            bootstrap_git=True,
        )
        # Verify post-pull core_sha256 if signed in release-signal.json (B1 code-binding check)
        if expected_core_sha:
            actual_core_sha = _compute_core_bundle_digest(root)
            if actual_core_sha and not hmac.compare_digest(actual_core_sha, expected_core_sha):
                if prev_head and (root / ".git").is_dir():
                    with contextlib.suppress(Exception):
                        run_call(["git", "-C", str(root), "reset", "--hard", prev_head], cwd=str(root))
                with contextlib.suppress(OSError):
                    _atomic_write_text(root / "VERSION", local_ver + "\n")
                save_update_status(
                    {
                        "update_ready_for_reload": False,
                        "last_website_error": "core_sha256_mismatch_rolled_back",
                    },
                    anchor_root=anchor_root,
                )
                return {
                    "ok": False,
                    "error": "core_sha256_mismatch",
                    "tamper_rejected": True,
                    "rolled_back": True,
                    "local_version": local_ver,
                    "signal_version": signal_ver,
                }

        applied_ok = bool(pull_res.get("ok")) and parse_version(str(pull_res.get("after_version") or "0.0.0")) >= parse_version(signal_ver)
        if not applied_ok:
            fails = int(cur_st.get("consecutive_failures") or 0) + 1
            backoff_s = min(10800, 900 * (2 ** min(fails - 1, 4)))
            save_update_status(
                {
                    "update_ready_for_reload": False,
                    "consecutive_failures": fails,
                    "next_retry_epoch": time.time() + backoff_s,
                },
                anchor_root=anchor_root,
            )
        else:
            save_update_status(
                {
                    "update_ready_for_reload": True,
                    "applied_version": str(pull_res.get("after_version") or ""),
                    "applied_at": _utc_now_iso(),
                    "deferred_busy": False,
                    "deferred_reason": "",
                    "consecutive_failures": 0,
                    "next_retry_epoch": 0.0,
                    "notes": notes,
                },
                anchor_root=anchor_root,
            )
        return {
            "ok": applied_ok,
            "local_version": local_ver,
            "signal_version": signal_ver,
            "after_version": pull_res.get("after_version"),
            "signal_verified": True,
            "update_available": not applied_ok,
            "auto_pulled": applied_ok,
            "update_ready_for_reload": applied_ok,
            "pull_result": pull_res,
            "watch_url": eff_url,
        }
    finally:
        with contextlib.suppress(OSError):
            proc_lock_file.unlink(missing_ok=True)
        _AUTO_UPDATE_LOCK.release()


def start_background_homebase_telemetry_daemon(interval_seconds: int = 900) -> bool:
    """Start a lightweight background thread on collaborator nodes that:
    1. Watches the public HTTPS `release-signal.json` website (startup + every 15m, even WITHOUT Tailscale)
       and auto-updates Anchor + all 20 bundled Foundry skills when signed & idle.
    2. Ships sanitized journal entries/errors and polls Homebase heartbeats when registered on Tailscale."""
    import random as _rnd_jitter
    import threading as _th
    host = (socket.gethostname() or "").strip().lower()
    if host in ("puter", "gwl-server") or "PYTEST_CURRENT_TEST" in os.environ:
        return False

    def _loop():
        # Gentle startup warmup so older Windows laptops finish booting cleanly first
        time.sleep(45)
        try:
            link0 = load_or_init_homebase_link()
            if link0.get("auto_pull_updates", True):
                poll_website_release_signal()
        except Exception:
            pass
        while True:
            time.sleep(max(60, int(interval_seconds)) + _rnd_jitter.randint(0, 25))
            try:
                link = load_or_init_homebase_link()
                if link.get("auto_pull_updates", True):
                    poll_website_release_signal()
                if link.get("registered") and link.get("telemetry_enabled", True):
                    sync_telemetry_to_homebase(heartbeat_even_if_empty=True)
            except Exception:
                pass

    t = _th.Thread(target=_loop, name="anchor-website-and-homebase-updater", daemon=True)
    t.start()
    return True


def _parse_cli_flag_value(argv: list[str], flag: str) -> str:
    for idx, arg in enumerate(argv):
        if arg == flag and idx + 1 < len(argv):
            return str(argv[idx + 1]).strip()
        if arg.startswith(f"{flag}="):
            return arg.split("=", 1)[1].strip()
    return ""


if __name__ == "__main__":  # pragma: no cover
    _CLI_MAIN_MODE = True
    _hb_cli_url = _parse_cli_flag_value(sys.argv[1:], "--homebase-url") or (os.environ.get("ANCHOR_HOMEBASE_URL") or "").strip()
    _cli_root_raw = _parse_cli_flag_value(sys.argv[1:], "--anchor-root")
    _cli_root = Path(_cli_root_raw).resolve() if _cli_root_raw else None
    _sign_out_raw = _parse_cli_flag_value(sys.argv[1:], "--write-release-signal")
    _want_skills_only = "--sync-skills-only" in sys.argv
    _want_pull = ("--pull" in sys.argv) or ("--update" in sys.argv)
    _want_poll_web = "--poll-website" in sys.argv
    _want_reg = "--register-homebase" in sys.argv
    _want_tel = "--sync-telemetry" in sys.argv
    _want_hb = ("--heartbeat" in sys.argv) or _want_tel
    if _sign_out_raw:
        _sig_ver = _parse_cli_flag_value(sys.argv[1:], "--version") or _read_version(_cli_root)
        _sig_notes = _parse_cli_flag_value(sys.argv[1:], "--notes")
        _sig_doc = build_signed_release_signal(version=_sig_ver, notes=_sig_notes)
        _atomic_write_text(Path(_sign_out_raw).resolve(), json.dumps(_sig_doc, indent=2) + "\n")
        print(json.dumps({"ok": True, "written": str(Path(_sign_out_raw).resolve()), "signal": _sig_doc}, indent=2))
    elif _want_skills_only:
        _sk_root = _code_dir(_cli_root)
        _sk_list, _ = _sync_bundled_skills_for_root(_sk_root)
        print(json.dumps({"ok": True, "skills_installed": _sk_list, "skills_installed_count": len(_sk_list)}, indent=2))
    elif _want_poll_web:
        print(json.dumps(poll_website_release_signal(anchor_root=_cli_root), indent=2))
    elif _want_pull and _want_reg:
        _p_out = pull_latest_update(anchor_root=_cli_root, bootstrap_git=True)
        _r_out = register_with_homebase(homebase_url=_hb_cli_url, anchor_root=_cli_root)
        print(json.dumps({"ok": bool(_p_out.get("ok")), "pull_update": _p_out, "homebase_registration": _r_out}, indent=2))
    elif _want_pull:
        print(json.dumps(pull_latest_update(anchor_root=_cli_root, bootstrap_git=True), indent=2))
    elif _want_reg:
        print(json.dumps(register_with_homebase(homebase_url=_hb_cli_url, anchor_root=_cli_root), indent=2))
    elif _want_tel:
        print(json.dumps(sync_telemetry_to_homebase(anchor_root=_cli_root, heartbeat_even_if_empty=_want_hb), indent=2))
    else:
        print(json.dumps(get_version_status(anchor_root=_cli_root), indent=2))
