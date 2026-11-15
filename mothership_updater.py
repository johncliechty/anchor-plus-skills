#!/usr/bin/env python3
"""Anchor Mother Ship Registration & Push/Pull Update Engine (v1.5.2, stdlib only).

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
import json
import os
from pathlib import Path
import platform
import re
import shutil
import socket
import ssl
import subprocess
import sys
from typing import Any
import urllib.error
import urllib.request

import onboard
import paths


REGISTRY_SCHEMA = "anchor.mothership.registry.v1"
REGISTRY_FILENAME = "mothership_registry.json"
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
            ctx = ssl.create_default_context()
            req = urllib.request.Request(u, headers={"User-Agent": f"Anchor-Updater/{local_ver}"})
            return urllib.request.urlopen(req, timeout=timeout, context=ctx)
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

    if target_version and parse_version(target_version) > parse_version(paths.read_version(root)):
        try:
            paths.atomic_write_text(root / "VERSION", str(target_version).strip() + "\n")
            if (root / "vendor" / "bundled-skills" / "ecgberht").is_dir():
                paths.atomic_write_text(root / "vendor" / "bundled-skills" / "ecgberht" / "VERSION", str(target_version).strip() + "\n")
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
    root = Path(anchor_root).resolve() if anchor_root else paths.CODE_DIR
    local_ver = paths.read_version(root)
    run = runner_fn or _default_run
    reg = load_mothership_registry(root)
    reg["latest_version"] = local_ver
    now_iso = _utc_now_iso()

    git_pushed = False
    if push_git and (root / ".git").is_dir() and runner_fn is not None:
        try:
            p_res = run(["git", "-C", str(root), "push", "origin", "HEAD"], cwd=str(root))
            git_pushed = getattr(p_res, "returncode", 1) == 0
        except Exception:
            git_pushed = False

    def _default_post(url: str, payload: dict[str, Any]):
        data = json.dumps(payload).encode("utf-8")
        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": f"Anchor-Mothership-Push/{local_ver}"},
            method="POST",
        )
        return urllib.request.urlopen(req, timeout=4.0, context=ctx)

    post_fn = opener_fn or _default_post
    results: list[dict[str, Any]] = []
    hostname = (socket.gethostname() or "").strip().lower()

    for m in reg.get("motherships") or []:
        mid = str(m.get("id") or "")
        if target_id and mid != target_id:
            continue
        m_host = str(m.get("hostname") or "").lower()
        is_self = (m_host == hostname) or (hostname in ("puter", "gwl-server") and mid == "gwl-server-lead")
        m["last_push_at"] = now_iso
        if is_self and not target_id:
            m["installed_version"] = local_ver
            m["pending_update"] = None
            results.append({"id": mid, "owner": m.get("owner"), "status": "lead_self", "version": local_ver})
            continue

        ts_url = str(m.get("tailscale_url") or "").strip().rstrip("/")
        pushed_live = False
        live_error = ""
        if ts_url:
            endpoint = f"{ts_url}/api/system/pull_update"
            try:
                with post_fn(endpoint, {"target_version": local_ver, "pushed_by": hostname or "lead", "notes": notes}) as resp:
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

    saved = save_mothership_registry(reg, anchor_root=root, write_repo=True)
    return {
        "ok": True,
        "version": local_ver,
        "git_pushed": git_pushed,
        "results": results,
        "registry": saved,
        "pushed_at": now_iso,
        "message": f"Pushed Anchor v{local_ver} to {len(results)} registered Mother Ship(s).",
    }
