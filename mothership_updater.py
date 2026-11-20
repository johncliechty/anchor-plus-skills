#!/usr/bin/env python3
"""Anchor Mother Ship Registration & Push/Pull Update Engine (v1.5.3, stdlib only).

Provides:
1. Repo-tracked & runtime Mother Ship registration (`mothership_registry.json` + `.anchor/mothership_registry.json`)
   so every collaborator Mother Ship (Windows, macOS / MacBook Air, Linux) is registered in the Anchor repo.
2. Pull Update (`check_for_updates` + `pull_latest_update`): allows any Anchor installation to check for
   the latest release version and pull/apply the update in-place (preserving `.anchor/` user state while
   refreshing all 20 bundled Foundry skills with `overwrite=True`).
3. Push Update (`push_update_to_motherships`): allows the Lead Mother Ship (or any registered Mother Ship)
   to push the latest Anchor release to GitHub and notify/trigger updates across registered Mother Ships
   over Tailscale HTTP (`/api/system/pull_update`) plus a durable repo-tracked `pending_update` bulletin.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import hmac
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
import time
from typing import Any
import urllib.error
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
RAW_VERSION_URL = "https://raw.githubusercontent.com/johncliechty/ghostworldlabs-anchor/main/VERSION"


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
    base = Path(anchor_root).resolve() if anchor_root else paths.CODE_DIR
    return base / REGISTRY_FILENAME


def _runtime_registry_path(anchor_root: Path | str | None = None) -> Path:
    if anchor_root:
        base = Path(anchor_root).resolve()
    else:
        base = paths.data_dir() if hasattr(paths, "data_dir") else paths.CODE_DIR
    return base / ".anchor" / REGISTRY_FILENAME


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
        "latest_version": paths.read_version(anchor_root),
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
    paths.atomic_write_text(rt_p, txt)

    if write_repo:
        repo_p = _repo_registry_path(anchor_root)
        try:
            paths.atomic_write_text(repo_p, txt)
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
    owner = str(entry.get("owner") or entry.get("display_name") or "").strip() or paths.read_collaborator_display_name("Collaborator")
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
    ver = str(entry.get("installed_version") or entry.get("version_installed") or paths.read_version(anchor_root)).strip()
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
    """Return local Anchor version, Ecgberht engine version, platform, and Mother Ship registry summary."""
    ver = paths.read_version(anchor_root)
    ecg_root, _checked = paths.resolve_ecgberht_root(anchor_root=anchor_root)
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
    return {
        "ok": True,
        "version": ver,
        "release_version": ver,
        "display_version": f"v{ver}",
        "ecgberht_version": ecg_ver,
        "ecgberht_root": str(ecg_root),
        "platform": _detect_platform_tag(),
        "hostname": socket.gethostname() or "localhost",
        "collaborator_name": paths.read_collaborator_display_name("John"),
        "mothership_id": (local_ms or {}).get("id") or "",
        "mothership": local_ms,
        "registered_motherships_count": len(motherships),
        "latest_known_version": str(reg.get("latest_version") or ver),
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
    runner_fn=None,
    opener_fn=None,
) -> dict[str, Any]:
    """Check whether a newer version of Anchor is available from git origin, registered Lead Mother Ship, or registry."""
    root = Path(anchor_root).resolve() if anchor_root else paths.CODE_DIR
    local_ver = paths.read_version(root)
    reg = load_mothership_registry(root)
    latest_ver = str(reg.get("latest_version") or local_ver).strip()
    source = "local_registry"
    notes = ""

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

    # Optional HTTP check against remote_url or Lead Mother Ship
    open_url = opener_fn
    if open_url is None and remote_url:
        def _default_open(u: str, timeout: float = 3.0):
            req = urllib.request.Request(u, headers={"User-Agent": f"Anchor-Updater/{local_ver}"})
            return paths.safe_urlopen(req, timeout=min(float(timeout), 15.0))
        open_url = _default_open

    if open_url is not None:
        check_target = (remote_url or RAW_VERSION_URL).strip()
        try:
            with open_url(check_target, timeout=3.0) as resp:
                raw_txt = resp.read(4096).decode("utf-8", errors="replace").strip()
                if raw_txt.startswith("{"):
                    doc = json.loads(raw_txt)
                    cand_v = str(doc.get("version") or doc.get("release_version") or doc.get("latest_version") or "").strip()
                else:
                    cand_v = raw_txt.splitlines()[0].strip() if raw_txt else ""
                if cand_v and parse_version(cand_v) > parse_version(latest_ver):
                    latest_ver = cand_v
                    source = check_target
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

    update_available = parse_version(latest_ver) > parse_version(local_ver)
    return {
        "ok": True,
        "local_version": local_ver,
        "latest_version": latest_ver,
        "update_available": update_available,
        "up_to_date": not update_available,
        "source": source,
        "notes": notes,
        "checked_at": _utc_now_iso(),
    }


def pull_latest_update(
    anchor_root: Path | str | None = None,
    *,
    target_version: str | None = None,
    runner_fn=None,
    sync_skills: bool = True,
) -> dict[str, Any]:
    """Pull and apply the latest Anchor update in-place, refreshing all 20 bundled Foundry skills while preserving `.anchor/`."""
    root = Path(anchor_root).resolve() if anchor_root else paths.CODE_DIR
    before_ver = paths.read_version(root)
    run = runner_fn or _default_run
    git_updated = False
    overlay_extracted = False
    details: list[str] = []

    if (root / ".git").is_dir():
        try:
            f_res = run(["git", "-C", str(root), "fetch", "origin"], cwd=str(root))
            if getattr(f_res, "returncode", 1) == 0:
                p_res = run(["git", "-C", str(root), "pull", "--ff-only"], cwd=str(root))
                if getattr(p_res, "returncode", 1) != 0:
                    run(["git", "-C", str(root), "stash", "push", "-m", "anchor-pull-update"], cwd=str(root))
                    p_res = run(["git", "-C", str(root), "pull", "--ff-only"], cwd=str(root))
                if getattr(p_res, "returncode", 1) == 0:
                    git_updated = True
                    details.append("git_pull_ff_only")
        except Exception as exc:
            details.append(f"git_skipped:{exc}")

    # Also apply bundled overlay if present and newer or if not a git repo
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

    clean_tv = str(target_version or "").strip()
    if (
        clean_tv
        and re.match(r"^\d+\.\d+\.\d+(?:\.\d+)?$", clean_tv)
        and (git_updated or overlay_extracted or runner_fn is not None)
        and parse_version(clean_tv) > parse_version(paths.read_version(root))
    ):
        try:
            paths.atomic_write_text(root / "VERSION", clean_tv + "\n")
            if (root / "vendor" / "bundled-skills" / "ecgberht").is_dir():
                paths.atomic_write_text(root / "vendor" / "bundled-skills" / "ecgberht" / "VERSION", clean_tv + "\n")
        except OSError:
            pass

    skills_installed: list[str] = []
    if sync_skills:
        src_skills = root / "vendor" / "bundled-skills"
        ws_skills = root.parent / "skills"
        if src_skills.is_dir():
            try:
                rep = onboard.install_skills(skills_src=src_skills, skills_home=ws_skills, overwrite=True)
                skills_installed = [item["name"] for item in (rep.get("installed") or [])]
                details.append(f"skills_synced:{len(skills_installed)}")
            except Exception as exc:
                details.append(f"skills_error:{exc}")

    after_ver = paths.read_version(root)
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
        save_mothership_registry(reg, anchor_root=root, write_repo=True)

    # Refresh ECGBERHT_ROOT resolution so stale C:\dev\Ecgberht is never used
    ecg_root, _ = paths.resolve_ecgberht_root(anchor_root=root)

    return {
        "ok": True,
        "before_version": before_ver,
        "after_version": after_ver,
        "updated": (after_ver != before_ver) or git_updated or overlay_extracted or bool(skills_installed),
        "git_updated": git_updated,
        "overlay_extracted": overlay_extracted,
        "skills_installed_count": len(skills_installed),
        "skills_installed": skills_installed,
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
    root = eff_anchor or paths.CODE_DIR
    local_ver = paths.read_version(eff_anchor)
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
        return paths.safe_urlopen(req, timeout=6.0)

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
            hasattr(paths, "data_dir")
            and paths.data_dir().resolve() == paths.CODE_DIR.resolve()
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
    if anchor_root is not None:
        p = Path(anchor_root).resolve() / ".anchor"
    else:
        base = paths.data_dir() if hasattr(paths, "data_dir") else paths.CODE_DIR
        p = Path(base).resolve() / ".anchor"
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
    with paths.WRITE_LOCK:
        peers = _load_homebase_peer_capabilities(anchor_root)
        peers[mid] = cap
        fp = _homebase_peer_caps_path(anchor_root, create=True)
        paths.atomic_write_text(
            fp,
            json.dumps({"schema": "anchor.homebase.peer_caps.v1", "updated_at": _utc_now_iso(), "peers": peers}, indent=2) + "\n",
        )


def read_homebase_link(anchor_root: Path | str | None = None) -> dict[str, Any]:
    """Pure read-only load of `.anchor/homebase_link.json` (never writes or mints capabilities)."""
    fp = _homebase_link_path(anchor_root, create=False)
    if fp.is_file():
        try:
            loaded = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
        except Exception:
            pass
    return {
        "schema": HOMEBASE_LINK_SCHEMA,
        "homebase_url": DEFAULT_HOMEBASE_URL,
        "telemetry_enabled": True,
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
    owner: str = "",
    hostname: str = "",
) -> dict[str, Any]:
    """Load or initialize `.anchor/homebase_link.json` under `paths.WRITE_LOCK` (never committed to git)."""
    with paths.WRITE_LOCK:
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
        if homebase_url and str(homebase_url).strip():
            hb = str(homebase_url).strip().rstrip("/")
            if not hb.startswith(("http://", "https://")):
                hb = "https://" + hb
            if doc.get("homebase_url") != hb:
                doc["homebase_url"] = hb
                changed = True
        elif not str(doc.get("homebase_url") or "").strip():
            doc["homebase_url"] = DEFAULT_HOMEBASE_URL
            changed = True

        if telemetry_enabled is not None:
            if bool(doc.get("telemetry_enabled", True)) != bool(telemetry_enabled):
                doc["telemetry_enabled"] = bool(telemetry_enabled)
                changed = True
        elif "telemetry_enabled" not in doc:
            doc["telemetry_enabled"] = True
            changed = True

        host_val = str(hostname or doc.get("hostname") or socket.gethostname() or "mothership").strip()
        owner_val = str(owner or doc.get("owner") or paths.read_collaborator_display_name("Collaborator")).strip()
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
            paths.atomic_write_text(fp, json.dumps(doc, indent=2) + "\n")
        return doc


def save_homebase_link(doc: dict[str, Any], *, anchor_root: Path | str | None = None) -> dict[str, Any]:
    with paths.WRITE_LOCK:
        fp = _homebase_link_path(anchor_root, create=True)
        payload = dict(doc)
        payload["schema"] = HOMEBASE_LINK_SCHEMA
        payload["updated_at"] = _utc_now_iso()
        paths.atomic_write_text(fp, json.dumps(payload, indent=2) + "\n")
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
    so Homebase can push updates directly and receive sanitized journal/error reports."""
    ts_det = detect_local_tailscale_endpoint(runner_fn=runner_fn)
    eff_host = str(hostname or ts_det.get("hostname") or socket.gethostname() or "mothership").strip()
    eff_owner = str(owner or paths.read_collaborator_display_name("Collaborator")).strip()
    eff_pseudo = str(pseudonym or eff_owner).strip()
    eff_ts_ip = str(tailscale_ip or ts_det.get("tailscale_ip") or "").strip()
    eff_ts_url = str(tailscale_url or ts_det.get("endpoint") or "").strip()
    if eff_ts_url and not eff_ts_url.startswith(("http://", "https://")):
        eff_ts_url = "https://" + eff_ts_url

    link = load_or_init_homebase_link(
        anchor_root,
        homebase_url=homebase_url or None,
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

    ver = paths.read_version(anchor_root)
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
        and (not homebase_url or "gwl-server" in configured_hb or "puter" in configured_hb)
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

    target_hb = str(homebase_url or configured_hb or DEFAULT_HOMEBASE_URL).strip().rstrip("/")
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
        return paths.safe_urlopen(req, timeout=4.0)

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
        "homebase_url": reached_url or configured_hb,
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
        "last_telemetry_at": str(src.get("last_telemetry_at") or ""),
        "has_capability": bool(str(src.get("node_capability") or "").strip()),
    }


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
    with paths.WRITE_LOCK:
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
        paths.atomic_write_text(
            fp,
            json.dumps({"schema": "anchor.homebase.peer_caps.v1", "updated_at": _utc_now_iso(), "peers": peers}, indent=2) + "\n",
        )

    ts_ip = str(ms.get("tailscale_ip") or "").strip()[:64]
    ts_url = str(ms.get("tailscale_url") or "").strip()[:200]
    if not ts_url and ts_ip:
        ts_url = f"http://{ts_ip}:8777"
    pseudonym = str(ms.get("pseudonym") or owner).strip()[:80]
    ver = str(ms.get("installed_version") or paths.read_version(anchor_root)).strip()[:32]
    plat = str(ms.get("platform") or "windows").strip()[:32]

    with paths.WRITE_LOCK:
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
    root = Path(anchor_root).resolve() if anchor_root else paths.CODE_DIR
    data_root = Path(anchor_root).resolve() if anchor_root else (paths.data_dir() if hasattr(paths, "data_dir") else root)
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
) -> dict[str, Any]:
    """Send unsent sanitized journal entries & error logs back to the Anchor Homebase."""
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

    if not events:
        link["watermarks"] = next_wm
        save_homebase_link(link, anchor_root=anchor_root)
        return {"ok": True, "sent_count": 0, "message": "No new journal entries or errors to send."}

    hb_url = str(link.get("homebase_url") or DEFAULT_HOMEBASE_URL).strip().rstrip("/")
    ver = paths.read_version(anchor_root)
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
        return paths.safe_urlopen(req, timeout=5.0)

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
                return {"ok": True, "sent_count": len(events), "homebase_url": hb_url}
            return {"ok": False, "sent_count": 0, "error": str(r_doc.get("error") or f"HTTP {code}")}
    except Exception as exc:
        return {"ok": False, "sent_count": 0, "error": str(exc)}


def receive_homebase_telemetry(
    payload: dict[str, Any],
    provided_capability: str | None,
    *,
    anchor_root: Path | str | None = None,
) -> dict[str, Any]:
    """Homebase receiver (`action='submit_homebase_telemetry'`): verify peer capability
    and store incoming collaborator journal entries & errors."""
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
    now_iso = _utc_now_iso()
    owner = str(payload.get("owner") or safe_id)[:80]
    host = str(payload.get("hostname") or "")[:80]
    ver = str(payload.get("version") or "")[:32]

    accepted: list[dict[str, Any]] = []
    with paths.WRITE_LOCK:
        if jsonl_p.is_file():
            try:
                if jsonl_p.stat().st_size > 2 * 1024 * 1024:
                    tail_lines = jsonl_p.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]
                    paths.atomic_write_text(jsonl_p, "\n".join(tail_lines) + ("\n" if tail_lines else ""))
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
        paths.atomic_write_text(inbox_dir / "LATEST.md", "\n".join(summary_lines))

        # Update last_seen_at in runtime Mother Ship registry
        reg = load_mothership_registry(anchor_root)
        for m in reg.get("motherships") or []:
            if str(m.get("id") or "") == safe_id:
                m["last_seen_at"] = now_iso
                m["last_telemetry_at"] = now_iso
                if ver:
                    m["installed_version"] = ver
                save_mothership_registry(reg, anchor_root=anchor_root, write_repo=False)
                break

    return {"ok": True, "status_code": 200, "accepted_count": len(accepted), "mothership_id": safe_id}


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


def start_background_homebase_telemetry_daemon(interval_seconds: int = 900) -> bool:
    """Start a lightweight background thread on registered collaborator nodes to ship
    new journal entries and errors back to the Anchor Homebase every 15 minutes."""
    import threading as _th
    host = (socket.gethostname() or "").strip().lower()
    if host in ("puter", "gwl-server") or "PYTEST_CURRENT_TEST" in os.environ:
        return False

    def _loop():
        while True:
            time.sleep(max(60, int(interval_seconds)))
            try:
                link = load_or_init_homebase_link()
                if link.get("registered") and link.get("telemetry_enabled", True):
                    sync_telemetry_to_homebase()
            except Exception:
                pass

    t = _th.Thread(target=_loop, name="anchor-homebase-telemetry", daemon=True)
    t.start()
    return True


if __name__ == "__main__":  # pragma: no cover
    if "--register-homebase" in sys.argv:
        print(json.dumps(register_with_homebase(), indent=2))
    elif "--sync-telemetry" in sys.argv:
        print(json.dumps(sync_telemetry_to_homebase(), indent=2))
    else:
        print(json.dumps(get_version_status(), indent=2))
