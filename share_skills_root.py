"""Skills-root registry, host adapter contracts, and portfolio equality.

Canonical SKILLS_ROOT is agent-independent. Claude / Grok / Gemini / Anchor are
adapters that point at one product tree. This module freezes:

* ``skills-root/v1`` registry schema + write under ``<HOME>/governance/``
* portfolio ≡ vendor-pin skill ID set (host-natives are out of portfolio)
* ``list_portfolio_ids_*`` + equality oracle that **fails** Claude-compat-only
  false GREEN (Grok must register SKILLS_ROOT on its own paths)
* adapter contracts: ``resolve_skills_root``, ``write_registry``,
  ``register_host``, ``resolve_skill_journal_dir``, install-to-SKILLS_ROOT

W0 froze the registry + equality surface. W1/Wave-2 adds live register
side-effects under a **caller-supplied home root** (hermetic: never touches
the real user profile unless ``home`` is that path).

Gemini promote-or-demote is recorded here (no half-registered): **promoted**
as first-class when registered; participates in criterion-2 equality.

Extends the share stack via ``share_home_config`` governance layout +
``share_schemas``. Stdlib only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import share_home_config as _home
import vendor_skills as _vendor

# ── Schema / identity ────────────────────────────────────────────────────────

SKILLS_ROOT_SCHEMA = "skills-root/v1"
SKILLS_ROOT_SCHEMA_VERSION = 1
SKILLS_ROOT_FILENAME = "skills_root.json"
ADAPTER_STATE_FILENAME = "host_adapters.json"
ADAPTER_STATE_SCHEMA = "skills-root-adapters/v1"

INSTALL_MODES = ("junction", "copy")
HOST_IDS = ("claude", "grok", "gemini", "anchor")

# Claude adapter: pointer-only (never a second product tree under ~/.claude).
CLAUDE_POINTER_MARKER = ".anchor-skills-root-pointer"
CLAUDE_SKILLS_REL = Path(".claude") / "skills"

# Grok host-local config (relative to controlled home, not real ~/.grok unless
# home is the real profile).
GROK_CONFIG_REL = Path(".grok") / "config.toml"

# Gemini promoted single-entry skills.json → SKILLS_ROOT.
GEMINI_SKILLS_JSON_REL = Path(".gemini") / "config" / "skills.json"

# Anchor hermetic env stamp (under governance; not a second product tree).
ANCHOR_ENV_FILENAME = "anchor_skills_env.json"

# Gemini promote-or-demote (W0 LOCK — no half-registered "maybe").
# Promoted: first-class adapter; single skills.json → SKILLS_ROOT in W1;
# list_portfolio_ids_gemini participates in equality when gemini is registered.
# Dual skills-master farm is not grown on new register.
GEMINI_HOST_POLICY = "promoted"  # "promoted" | "demoted"
GEMINI_EQUALITY_PARTICIPANT = GEMINI_HOST_POLICY == "promoted"

# Hosts that participate in criterion-2 portfolio equality when registered.
_EQUALITY_BASE = ("claude", "grok", "anchor")
EQUALITY_HOSTS = (
    _EQUALITY_BASE + ("gemini",)
    if GEMINI_EQUALITY_PARTICIPANT
    else _EQUALITY_BASE
)

# Documented adapter mechanisms (contract surface for tests / later waves).
HOST_ADAPTER_CONTRACTS = {
    "claude": {
        "mechanism": "pointer_junction",
        "target_description": (
            "~/.claude/skills/<id> is symlink/junction → SKILLS_ROOT/<id>, "
            "else a MARKED full copy (v1.1.3 last resort — always loadable, "
            "tracked by its marker, refreshed on re-onboard). Never an "
            "untracked second product copy, never a marker-only dir."
        ),
        "config_path": "~/.claude/skills/<id>",
    },
    "grok": {
        "mechanism": "config_skills_paths",
        "target_description": (
            "~/.grok/config.toml [skills].paths must include SKILLS_ROOT. "
            "Claude-compat alone is NOT portfolio equality."
        ),
        "config_path": "~/.grok/config.toml",
    },
    "gemini": {
        "mechanism": "skills_json_single_entry",
        "target_description": (
            "Promoted first-class: single skills.json entry → SKILLS_ROOT. "
            "Do not grow dual skills-master farm on new register."
        ),
        "config_path": "~/.gemini/config/skills.json",
        "policy": GEMINI_HOST_POLICY,
    },
    "anchor": {
        "mechanism": "env_skills_root",
        "target_description": (
            "ANCHOR_SKILLS_ROOT / runner root = SKILLS_ROOT only. "
            "One env, one root; do not stamp hosts_registered without register."
        ),
        "config_path": "ANCHOR_SKILLS_ROOT",
    },
}

JOURNAL_SUBDIR = "journal"


class SkillsRootError(Exception):
    """Raised when skills-root registry or adapter contract refuses a write."""


# ── Portfolio (vendor pin) ───────────────────────────────────────────────────

def vendor_portfolio_ids():
    """Ordered portfolio skill IDs ≡ vendor-pin declared suite.

    Host-native skills (Grok bundled docx/design, Claude thin locals, etc.)
    are **out of portfolio** and must not appear here.
    """
    return list(_vendor.declared_skill_names())


def normalize_portfolio_manifest(manifest) -> list:
    """Return ordered skill-id list from inline list or known ref string."""
    if isinstance(manifest, list):
        out = []
        for item in manifest:
            if not isinstance(item, str) or not item.strip():
                raise SkillsRootError("portfolio_manifest-item-empty")
            out.append(item.strip())
        return out
    if isinstance(manifest, str) and manifest.strip():
        ref = manifest.strip()
        if ref in (
            "vendor_pin",
            "vendor_skills.declared_skill_names",
            "share:vendor_portfolio",
        ):
            return vendor_portfolio_ids()
        raise SkillsRootError("portfolio_manifest-unknown-ref:%s" % ref)
    raise SkillsRootError("portfolio_manifest-invalid")


# ── Validation ───────────────────────────────────────────────────────────────

def validate_skills_root_doc(doc) -> list:
    """Return problem list (empty = valid). Stdlib; no jsonschema dep."""
    if not isinstance(doc, dict):
        return ["skills-root-not-an-object"]
    problems = []
    required = (
        "schema",
        "skills_root",
        "install_mode",
        "hosts_registered",
        "portfolio_manifest",
    )
    for key in required:
        if key not in doc:
            problems.append("missing-key:%s" % key)

    allowed = set(required) | {"schema_version", "notes"}
    for key in doc:
        if key not in allowed:
            problems.append("unknown-key:%s" % key)

    if "schema" in doc and doc["schema"] != SKILLS_ROOT_SCHEMA:
        problems.append("schema-wrong:%r" % (doc.get("schema"),))

    if "schema_version" in doc and doc["schema_version"] != SKILLS_ROOT_SCHEMA_VERSION:
        problems.append(
            "schema_version-wrong:%r" % (doc.get("schema_version"),)
        )

    root = doc.get("skills_root")
    if "skills_root" in doc:
        if not isinstance(root, str) or not root.strip():
            problems.append("skills_root-empty")

    mode = doc.get("install_mode")
    if "install_mode" in doc:
        if mode not in INSTALL_MODES:
            problems.append("install_mode-out-of-enum:%r" % (mode,))

    hosts = doc.get("hosts_registered")
    if "hosts_registered" in doc:
        if not isinstance(hosts, list):
            problems.append("hosts_registered-not-a-list")
        else:
            seen = set()
            for h in hosts:
                if h not in HOST_IDS:
                    problems.append("hosts_registered-out-of-enum:%r" % (h,))
                elif h in seen:
                    problems.append("hosts_registered-duplicate:%s" % h)
                else:
                    seen.add(h)
            # Demoted Gemini must never be stamped as registered-required.
            if (
                GEMINI_HOST_POLICY == "demoted"
                and "gemini" in seen
            ):
                problems.append(
                    "hosts_registered-gemini-demoted-forbidden"
                )

    pm = doc.get("portfolio_manifest")
    if "portfolio_manifest" in doc:
        if isinstance(pm, list):
            if not pm:
                problems.append("portfolio_manifest-empty")
            else:
                for i, item in enumerate(pm):
                    if not isinstance(item, str) or not item.strip():
                        problems.append(
                            "portfolio_manifest-item-empty:%d" % i
                        )
        elif isinstance(pm, str):
            if not pm.strip():
                problems.append("portfolio_manifest-empty")
        else:
            problems.append("portfolio_manifest-invalid-type")

    return problems


def build_skills_root_doc(
    skills_root,
    *,
    install_mode: str = "copy",
    hosts_registered=None,
    portfolio_manifest=None,
    notes: str | None = None,
) -> dict:
    """Build a skills-root/v1 document (does not write)."""
    if portfolio_manifest is None:
        portfolio_manifest = vendor_portfolio_ids()
    elif isinstance(portfolio_manifest, str):
        # Keep ref form when caller passed a ref string.
        pass
    else:
        portfolio_manifest = list(portfolio_manifest)

    doc = {
        "schema": SKILLS_ROOT_SCHEMA,
        "schema_version": SKILLS_ROOT_SCHEMA_VERSION,
        "skills_root": str(skills_root).strip() if skills_root is not None else "",
        "install_mode": install_mode,
        "hosts_registered": list(hosts_registered or []),
        "portfolio_manifest": portfolio_manifest,
    }
    if notes is not None:
        doc["notes"] = notes
    return doc


# ── Paths / IO ───────────────────────────────────────────────────────────────

def governance_dir(home=None) -> Path:
    """``<HOME>/governance`` — registry write target (share_home_config seam)."""
    layout = _home.layout_for_home(home)
    return Path(layout["absolute"]["governance"])


def skills_root_registry_path(home=None) -> Path:
    return governance_dir(home) / SKILLS_ROOT_FILENAME


def adapter_state_path(home=None) -> Path:
    return governance_dir(home) / ADAPTER_STATE_FILENAME


def resolve_skills_root(home=None, *, env=None, registry=None) -> Path:
    """Resolve SKILLS_ROOT from registry, then env, then home layout default.

    Order: explicit ``registry`` doc → load registry → env
    ``ANCHOR_SKILLS_ROOT`` → ``<HOME>/skills``.
    """
    if registry is not None and isinstance(registry, dict):
        raw = (registry.get("skills_root") or "").strip()
        if raw:
            return Path(raw).expanduser()

    if home is not None:
        try:
            loaded = load_registry(home)
        except SkillsRootError:
            loaded = None
        if loaded:
            raw = (loaded.get("skills_root") or "").strip()
            if raw:
                return Path(raw).expanduser()

    env = env if env is not None else os.environ
    raw_env = (env.get("ANCHOR_SKILLS_ROOT") or "").strip()
    if raw_env:
        return Path(raw_env).expanduser()

    layout = _home.layout_for_home(home)
    return Path(layout["absolute"]["skills"])


def load_registry(home=None) -> dict | None:
    """Load skills_root.json if present; None if missing. Raises if invalid."""
    path = skills_root_registry_path(home)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SkillsRootError("registry-unreadable:%s" % exc) from exc
    problems = validate_skills_root_doc(doc)
    if problems:
        raise SkillsRootError(
            "registry-invalid:" + ";".join(problems)
        )
    return doc


def write_registry(doc, *, home=None, dest=None) -> Path:
    """Validate and write skills_root.json under governance (or ``dest``).

    Returns the written path. Creates parent dirs.
    """
    problems = validate_skills_root_doc(doc)
    if problems:
        raise SkillsRootError(
            "invalid skills-root registry: " + ";".join(problems)
        )
    if dest is None:
        dest = skills_root_registry_path(home)
    else:
        dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return dest


# ── Adapter state + live host side-effects (hermetic under ``home``) ─────────

def _default_adapter_entry(host: str, *, root, mode: str) -> dict:
    contract = HOST_ADAPTER_CONTRACTS[host]
    entry = {
        "registered": True,
        "mechanism": contract["mechanism"],
        "target_description": contract["target_description"],
        "config_path": contract["config_path"],
        "skills_root": str(root),
        "install_mode": mode,
    }
    if host == "grok":
        # Default registration claims paths include SKILLS_ROOT.
        # Tests can flip this to falsify Claude-compat-only GREEN.
        entry["skills_paths_include_skills_root"] = True
        entry["skills_paths"] = [str(root)]
        entry["host_native_ids"] = []
        entry["claude_compat_only"] = False
    elif host == "claude":
        entry["pointer_only"] = True
        entry["dual_copy_forbidden"] = True
        entry["pointers"] = {}
    elif host == "gemini":
        entry["policy"] = GEMINI_HOST_POLICY
        entry["skills_json_points_at_skills_root"] = (
            GEMINI_HOST_POLICY == "promoted"
        )
    elif host == "anchor":
        entry["env_var"] = "ANCHOR_SKILLS_ROOT"
        entry["env_points_at_skills_root"] = True
    return entry


def load_adapter_state(home=None) -> dict:
    """Load host adapter state. Empty registered map if missing."""
    path = adapter_state_path(home)
    if not path.is_file():
        return {
            "schema": ADAPTER_STATE_SCHEMA,
            "hosts": {},
        }
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "schema": ADAPTER_STATE_SCHEMA,
            "hosts": {},
        }
    if not isinstance(doc, dict):
        return {"schema": ADAPTER_STATE_SCHEMA, "hosts": {}}
    hosts = doc.get("hosts")
    if not isinstance(hosts, dict):
        hosts = {}
    return {
        "schema": doc.get("schema") or ADAPTER_STATE_SCHEMA,
        "hosts": hosts,
    }


def write_adapter_state(state: dict, *, home=None) -> Path:
    path = adapter_state_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    out = {
        "schema": ADAPTER_STATE_SCHEMA,
        "hosts": dict(state.get("hosts") or {}),
    }
    path.write_text(
        json.dumps(out, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def claude_skills_home(home=None) -> Path:
    """``<home>/.claude/skills`` — Claude adapter farm (pointers only)."""
    root = Path(home) if home is not None else Path.home()
    return root / CLAUDE_SKILLS_REL


def grok_config_path(home=None) -> Path:
    root = Path(home) if home is not None else Path.home()
    return root / GROK_CONFIG_REL


def gemini_skills_json_path(home=None) -> Path:
    root = Path(home) if home is not None else Path.home()
    return root / GEMINI_SKILLS_JSON_REL


def anchor_env_path(home=None) -> Path:
    return governance_dir(home) / ANCHOR_ENV_FILENAME


def _win_create_dir_symlink(link: Path, target: Path) -> bool:
    """Best-effort Windows directory symlink via ctypes (no shell).

    NOTE (v1.1.3): this creates a SYMLINK — the ``0x2`` flag is
    ``ALLOW_UNPRIVILEGED_CREATE``, which only works with Developer Mode ON. It
    was historically mislabeled "junction". Real junctions (which need NO
    privilege on stock Windows) are :func:`_win_create_junction`.
    """
    if os.name != "nt":
        return False
    try:
        import ctypes
    except ImportError:
        return False
    # SYMBOLIC_LINK_FLAG_DIRECTORY | ALLOW_UNPRIVILEGED_CREATE
    flags = 0x1 | 0x2
    # CreateSymbolicLinkW returns nonzero on success.
    fn = getattr(ctypes.windll.kernel32, "CreateSymbolicLinkW", None)
    if fn is None:
        return False
    link_s = str(link)
    target_s = str(target)
    try:
        rc = fn(link_s, target_s, flags)
    except OSError:
        return False
    return bool(rc)


def _win_create_junction(link: Path, target: Path) -> bool:
    """Create a REAL directory junction (``mklink /J``) — stock-Windows-safe.

    Junctions require NO admin rights and NO Developer Mode, unlike symlinks —
    this is the mechanism that makes skill registration actually work on a
    default collaborator box (v1.1.3 share-fix; the old chain fell through to
    a pointer-marker dir Claude Code cannot read, reported as "registered").
    ``mklink`` is a cmd builtin, so it is invoked through ``cmd /c``.
    Junction targets must be absolute.
    """
    if os.name != "nt":
        return False
    import subprocess
    try:
        proc = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(Path(target).resolve())],
            capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0 and Path(link).exists()


def _is_dir_junction(p: Path) -> bool:
    """True iff ``p`` is a Windows directory junction (reparse, not symlink)."""
    if os.name != "nt":
        return False
    try:
        st = os.stat(str(p), follow_symlinks=False)
    except OSError:
        return False
    # FILE_ATTRIBUTE_REPARSE_POINT and not a symlink → junction (3.8-safe;
    # Path.is_junction() only exists on 3.12+).
    if not (getattr(st, "st_file_attributes", 0) & 0x400):
        return False
    try:
        return not Path(p).is_symlink()
    except OSError:
        return False


#: Forced link mode for the stranger-sandbox / tests: ``auto`` (default) walks
#: the full symlink → junction → copy chain; ``junction`` skips the symlink
#: attempts; ``copy`` goes straight to the full-copy fallback. Lets acceptance
#: runs exercise the exact mechanism a no-DevMode / no-admin collaborator box
#: would land on, from a box where symlinks happen to work.
LINK_MODE_ENV = "ANCHOR_SKILLS_LINK_MODE"


def _copy_skill_with_marker(link: Path, target: Path) -> str:
    """FULL-COPY fallback: real bytes Claude can load + our ownership marker.

    The marker file keeps the dual-copy law satisfied and re-onboard
    idempotent: line 1 is the (relative when possible) target it mirrors —
    :func:`read_claude_pointer_target` resolves it — and line 2 records the
    mechanism. A copy goes stale when SKILLS_ROOT updates; re-onboard
    refreshes it (the marker marks it OURS, so it is never refused).
    """
    import shutil as _sh
    _sh.copytree(str(target), str(link))
    marker = link / CLAUDE_POINTER_MARKER
    try:
        dest = os.path.relpath(str(target.resolve()), str(link.resolve()))
    except (OSError, ValueError):
        dest = os.path.join("..", "..", "..", "skills", target.name)
    dest = str(dest).replace("\\", "/")
    marker.write_text(dest + "\nmechanism: copy\n", encoding="utf-8",
                      newline="\n")
    return "copy"


def _try_link_skill(link: Path, target: Path) -> str:
    """Register one skill for Claude: symlink → junction → FULL COPY.

    Returns the mechanism label: ``symlink`` | ``junction`` | ``copy``.
    v1.1.3 share-fix: the old last resort — a directory holding ONLY a pointer
    marker file — is retired. Claude Code cannot read a marker dir (no
    SKILL.md), yet onboard reported the skill "registered": the classic
    stranger-install failure on a no-DevMode / no-admin Windows box. Every
    mechanism this chain can now return leaves a tree Claude actually loads.
    A pre-existing legacy marker-only dir is UPGRADED in place (removed, then
    re-linked via the chain) so a broken install heals on re-onboard.
    """
    target = Path(target)
    link = Path(link)
    mode = (os.environ.get(LINK_MODE_ENV) or "auto").strip().lower()

    if link.exists() or link.is_symlink():
        if link.is_symlink():
            return "symlink"
        if _is_dir_junction(link):
            return "junction"
        marker = link / CLAUDE_POINTER_MARKER
        if marker.is_file():
            if (link / "SKILL.md").is_file():
                return "copy"  # our v1.1.3 copy fallback — already installed
            # Legacy pointer-only dir (Claude can't read it): heal in place.
            import shutil as _sh
            _sh.rmtree(str(link), ignore_errors=True)
        else:
            # Pre-existing foreign dir: do not clobber.
            raise SkillsRootError(
                "claude-pointer-target-exists-not-pointer:%s" % link
            )

    link.parent.mkdir(parents=True, exist_ok=True)

    if mode == "copy":
        return _copy_skill_with_marker(link, target)

    if mode != "junction":
        # 1) pathlib symlink (works when OS/permissions allow).
        try:
            link.symlink_to(target, target_is_directory=True)
            return "symlink"
        except OSError:
            pass

        # 2) Windows CreateSymbolicLinkW (no shell / mklink) — ALSO a symlink
        # (needs Developer Mode); honestly labeled since v1.1.3.
        if _win_create_dir_symlink(link, target):
            if link.exists() or link.is_symlink():
                return "symlink"

    # 3) REAL directory junction — works on stock Windows, no privileges.
    if _win_create_junction(link, target):
        return "junction"

    # 4) FULL COPY — always loadable, marked as ours.
    return _copy_skill_with_marker(link, target)


def read_claude_pointer_target(link: Path) -> Path | None:
    """Resolve where a Claude adapter path points (symlink/junction/marker).

    Marker parsing reads the FIRST line only (v1.1.3 copy-fallback markers
    carry a second ``mechanism: copy`` line; legacy single-line markers are
    unchanged). A junction resolves via ``os.path.realpath`` like a symlink.
    """
    link = Path(link)
    try:
        if link.is_symlink() or _is_dir_junction(link):
            return Path(os.path.realpath(link))
    except OSError:
        pass
    marker = link / CLAUDE_POINTER_MARKER
    if marker.is_file():
        try:
            raw = marker.read_text(encoding="utf-8")
        except OSError:
            return None
        first = (raw.splitlines() or [""])[0].strip()
        if first:
            p = Path(first)
            if not p.is_absolute():
                # Marker is relative to the skill link dir (or its parent).
                p = (link / p).resolve()
            return p
    return None


def inspect_claude_adapter(home, skill_id: str, *, skills_root=None) -> dict:
    """Inspect Claude path for skill_id — pointer-only proof for tests.

    v1.1.3: junction- and copy-aware. A directory JUNCTION (the stock-Windows
    mechanism) counts like a symlink; a marker-carrying FULL COPY (the last
    resort) is OUR tracked install — ``is_copy`` True, never ``dual_copy``.
    ``dual_copy`` remains exactly: a full SKILL.md tree with NO link/junction
    and NO marker (an untracked second product tree).
    """
    link = claude_skills_home(home) / skill_id
    root = (
        Path(skills_root)
        if skills_root is not None
        else resolve_skills_root(home)
    )
    expected = Path(root) / skill_id
    out = {
        "path": str(link),
        "exists": link.exists() or link.is_symlink(),
        "is_symlink": False,
        "is_junction": False,
        "is_pointer_marker": False,
        "is_copy": False,
        "pointer_only": False,
        "dual_copy": False,
        "target": None,
        "expected": str(expected),
        "matches_skills_root": False,
    }
    if not out["exists"]:
        return out
    try:
        out["is_symlink"] = link.is_symlink()
    except OSError:
        out["is_symlink"] = False
    out["is_junction"] = _is_dir_junction(link)
    marker = link / CLAUDE_POINTER_MARKER
    out["is_pointer_marker"] = (marker.is_file() and not out["is_symlink"]
                                and not out["is_junction"])
    out["is_copy"] = out["is_pointer_marker"] and (link / "SKILL.md").is_file()
    tgt = read_claude_pointer_target(link)
    if tgt is not None:
        out["target"] = str(tgt)
        out["pointer_only"] = True
        try:
            out["matches_skills_root"] = (
                os.path.realpath(str(tgt)) == os.path.realpath(str(expected))
            )
        except OSError:
            out["matches_skills_root"] = Path(tgt) == expected
    else:
        # Full directory without marker/symlink/junction = dual-copy smell.
        skill_md = link / "SKILL.md"
        out["dual_copy"] = (skill_md.is_file() and not out["is_symlink"]
                            and not out["is_junction"])
        out["pointer_only"] = False
    return out


def _skill_ids_for_claude_pointers(root: Path, home=None) -> list:
    """IDs under SKILLS_ROOT that get Claude pointers (dirs only)."""
    present = _skill_ids_under_root(root)
    pin = _portfolio_set(home)
    if pin:
        return sorted(set(present) & pin, key=str.lower)
    return list(present)


def _apply_claude_register(home, root_path: Path, entry: dict) -> dict:
    """Create pointer/symlink farm under home/.claude/skills → SKILLS_ROOT."""
    if home is None:
        entry["side_effect"] = "skipped-no-home"
        return entry
    ids = _skill_ids_for_claude_pointers(root_path, home=home)
    # Refuse dual product trees before creating any pointer (re-onboard law).
    refuse_dual_copy_on_re_onboard(
        home, skills_root=root_path, portfolio=ids or None
    )
    pointers = {}
    for sid in ids:
        link = claude_skills_home(home) / sid
        target = root_path / sid
        if not target.is_dir() and not target.is_symlink():
            continue
        try:
            kind = _try_link_skill(link, target)
        except SkillsRootError as exc:
            msg = str(exc)
            if "exists-not-pointer" in msg:
                raise SkillsRootError(
                    "dual-copy-forbidden:refuse-re-onboard:%s" % sid
                ) from exc
            raise
        pointers[sid] = {
            "path": str(link),
            "target": str(target),
            "kind": kind,
        }
    entry["pointers"] = pointers
    entry["pointer_only"] = True
    entry["dual_copy_forbidden"] = True
    entry["side_effect"] = "claude-pointers"
    entry["config_path_resolved"] = str(claude_skills_home(home))
    return entry


def _toml_escape_path(p: str) -> str:
    # Minimal TOML basic-string escape for Windows paths.
    return p.replace("\\", "\\\\").replace('"', '\\"')


def _write_grok_skills_paths(home, root_path: Path, *, include: bool) -> Path:
    """Write/update ``home/.grok/config.toml`` [skills].paths (stdlib only)."""
    path = grok_config_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    root_s = str(root_path)
    if include:
        paths_line = 'paths = ["%s"]' % _toml_escape_path(root_s)
    else:
        # Explicit omit SKILLS_ROOT — Claude-compat-only false GREEN case.
        paths_line = "paths = []"

    existing = ""
    if path.is_file():
        try:
            existing = path.read_text(encoding="utf-8")
        except OSError:
            existing = ""

    if not existing.strip():
        body = "# Managed by Anchor share_skills_root.register_host\n\n[skills]\n%s\n" % (
            paths_line,
        )
        path.write_text(body, encoding="utf-8", newline="\n")
        return path

    # Replace or insert [skills] paths without a full TOML library.
    lines = existing.splitlines(keepends=False)
    out_lines = []
    in_skills = False
    skills_seen = False
    paths_written = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_skills and not paths_written:
                out_lines.append(paths_line)
                paths_written = True
            in_skills = stripped == "[skills]"
            if in_skills:
                skills_seen = True
            out_lines.append(line)
            continue
        if in_skills and stripped.startswith("paths"):
            out_lines.append(paths_line)
            paths_written = True
            continue
        out_lines.append(line)
    if in_skills and not paths_written:
        out_lines.append(paths_line)
        paths_written = True
    if not skills_seen:
        if out_lines and out_lines[-1].strip():
            out_lines.append("")
        out_lines.append("[skills]")
        out_lines.append(paths_line)
    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8", newline="\n")
    return path


def _read_grok_skills_paths(home) -> list:
    """Best-effort parse of [skills].paths from home/.grok/config.toml."""
    path = grok_config_path(home)
    if not path.is_file():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []
    in_skills = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_skills = stripped == "[skills]"
            continue
        if not in_skills or not stripped.startswith("paths"):
            continue
        # paths = ["a", "b"] or paths = []
        eq = stripped.find("=")
        if eq < 0:
            continue
        rhs = stripped[eq + 1 :].strip()
        if not (rhs.startswith("[") and rhs.endswith("]")):
            continue
        inner = rhs[1:-1].strip()
        if not inner:
            return []
        parts = []
        for chunk in inner.split(","):
            c = chunk.strip().strip('"').strip("'")
            # Unescape simple backslash form.
            c = c.replace("\\\\", "\\")
            if c:
                parts.append(c)
        return parts
    return []


def _apply_grok_register(
    home, root_path: Path, entry: dict, *, include_skills_root: bool
) -> dict:
    if home is None:
        entry["side_effect"] = "skipped-no-home"
        return entry
    cfg = _write_grok_skills_paths(
        home, root_path, include=include_skills_root
    )
    paths = _read_grok_skills_paths(home)
    entry["skills_paths"] = list(paths)
    entry["skills_paths_include_skills_root"] = include_skills_root
    entry["claude_compat_only"] = not include_skills_root
    entry["config_path_resolved"] = str(cfg)
    entry["side_effect"] = "grok-config-toml"
    return entry


def _apply_gemini_register(home, root_path: Path, entry: dict) -> dict:
    """Single skills.json entry → SKILLS_ROOT (promoted; no dual farm)."""
    if home is None:
        entry["side_effect"] = "skipped-no-home"
        return entry
    path = gemini_skills_json_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "skills_root": str(root_path),
        "note": (
            "Anchor share_skills_root: single entry → SKILLS_ROOT; "
            "do not grow dual skills-master farm."
        ),
    }
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    entry["skills_json_points_at_skills_root"] = True
    entry["config_path_resolved"] = str(path)
    entry["side_effect"] = "gemini-skills-json"
    entry["policy"] = GEMINI_HOST_POLICY
    return entry


def _apply_anchor_register(home, root_path: Path, entry: dict) -> dict:
    """Stamp ANCHOR_SKILLS_ROOT under controlled home governance."""
    if home is None:
        entry["side_effect"] = "skipped-no-home"
        return entry
    path = anchor_env_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "ANCHOR_SKILLS_ROOT": str(root_path),
        "note": "Hermetic/host stamp from register_host; one env, one root.",
    }
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    entry["env_var"] = "ANCHOR_SKILLS_ROOT"
    entry["env_points_at_skills_root"] = True
    entry["env_value"] = str(root_path)
    entry["config_path_resolved"] = str(path)
    entry["side_effect"] = "anchor-env-stamp"
    return entry


def register_host(
    host: str,
    root,
    mode: str,
    *,
    home=None,
    skills_paths_include_skills_root: bool | None = None,
    update_registry: bool = True,
    apply_side_effects: bool = True,
) -> dict:
    """Register a host adapter against SKILLS_ROOT under controlled ``home``.

    Side effects (deterministic, testable; all under ``home`` when provided):
    * writes/updates ``governance/host_adapters.json`` entry for ``host``
    * optionally appends ``host`` to registry ``hosts_registered``
    * **claude**: junction/symlink/pointer under ``home/.claude/skills/<id>``
      → ``SKILLS_ROOT/<id>`` (never a second product copy)
    * **grok**: ``home/.grok/config.toml`` ``[skills].paths`` includes
      SKILLS_ROOT (or empty when ``skills_paths_include_skills_root=False``)
    * **gemini**: single ``home/.gemini/config/skills.json`` → SKILLS_ROOT
    * **anchor**: ``governance/anchor_skills_env.json`` stamps
      ``ANCHOR_SKILLS_ROOT``

    Pass ``apply_side_effects=False`` to keep W0-style adapter-state-only
    registration (tests that only need the equality oracle stub).
    """
    if host not in HOST_IDS:
        raise SkillsRootError("register_host-unknown-host:%r" % (host,))
    if mode not in INSTALL_MODES:
        raise SkillsRootError("register_host-install_mode-out-of-enum:%r" % (mode,))
    if host == "gemini" and GEMINI_HOST_POLICY == "demoted":
        raise SkillsRootError(
            "register_host-gemini-demoted:gemini is demoted; not first-class"
        )

    root_path = Path(root).expanduser() if root is not None else resolve_skills_root(home)
    entry = _default_adapter_entry(host, root=root_path, mode=mode)

    include_grok = True
    if host == "grok" and skills_paths_include_skills_root is not None:
        include_grok = bool(skills_paths_include_skills_root)
        entry["skills_paths_include_skills_root"] = include_grok
        if include_grok:
            entry["skills_paths"] = [str(root_path)]
            entry["claude_compat_only"] = False
        else:
            entry["skills_paths"] = []
            entry["claude_compat_only"] = True

    if apply_side_effects:
        if host == "claude":
            entry = _apply_claude_register(home, root_path, entry)
        elif host == "grok":
            entry = _apply_grok_register(
                home, root_path, entry, include_skills_root=include_grok
            )
        elif host == "gemini":
            entry = _apply_gemini_register(home, root_path, entry)
        elif host == "anchor":
            entry = _apply_anchor_register(home, root_path, entry)

    state = load_adapter_state(home)
    state.setdefault("hosts", {})[host] = entry
    write_adapter_state(state, home=home)

    if update_registry:
        reg = load_registry(home)
        if reg is None:
            reg = build_skills_root_doc(
                root_path,
                install_mode=mode,
                hosts_registered=[host],
            )
        else:
            hosts = list(reg.get("hosts_registered") or [])
            if host not in hosts:
                hosts.append(host)
            reg["hosts_registered"] = hosts
            reg["skills_root"] = str(root_path)
            reg["install_mode"] = mode
        write_registry(reg, home=home)

    return entry


def resolve_skill_journal_dir(skill_id: str, *, home=None, registry=None) -> Path:
    """Named journal resolve: SKILLS_ROOT/<skill_id>/journal.

    Live write path for skill runs (criterion 3). Optional home
    ``skill-journals`` is mirror/export staging only — never returned here.
    """
    if not isinstance(skill_id, str) or not skill_id.strip():
        raise SkillsRootError("skill_id-empty")
    root = resolve_skills_root(home, registry=registry)
    return Path(root) / skill_id.strip() / JOURNAL_SUBDIR


# ── Product install into SKILLS_ROOT (recipient: one tree only) ──────────────

def refuse_dual_copy_on_re_onboard(
    home, *, skills_root=None, portfolio=None
) -> None:
    """Hard refuse when Claude still holds a second full product tree.

    Seal/upgrade/re-onboard must not leave dual trees. Raises
    :class:`SkillsRootError` with ``dual-copy-forbidden:...`` when detected.
    """
    proof = product_bytes_only_under_skills_root(
        home, skills_root=skills_root, portfolio=portfolio
    )
    dual = proof.get("claude_dual_copy_ids") or []
    if dual:
        raise SkillsRootError(
            "dual-copy-forbidden:refuse-re-onboard:%s" % ",".join(dual)
        )


def install_skills_to_skills_root(
    home,
    skills_src,
    *,
    mode: str = "copy",
    portfolio=None,
    write_reg: bool = True,
    hosts_registered=None,
    seal: bool = True,
    refuse_dual: bool = True,
) -> dict:
    """Install product skill bytes **only** under SKILLS_ROOT/<id>/.

    Recipient default is ``mode="copy"`` (bytes once under ``<home>/skills``)
    then seal. ``mode="junction"`` uses onboard's symlink path into the source
    tree (author/advanced). Never installs a second product tree under
    ``~/.claude/skills`` — use :func:`register_host` for adapters.

    Reuses ``onboard.install_skills`` (no second distro stack). Re-onboard
    refuses when a dual Claude product tree is present.
    """
    if mode not in INSTALL_MODES:
        raise SkillsRootError("install_mode-out-of-enum:%r" % (mode,))
    # Local import: onboard is stdlib-only product installer; avoid cycle.
    import onboard as _onboard
    import share_skill_seal as _seal

    home_path = Path(home) if home is not None else None
    root = resolve_skills_root(home_path)
    root.mkdir(parents=True, exist_ok=True)

    pin_for_check = list(portfolio) if portfolio is not None else None
    if refuse_dual and home_path is not None:
        refuse_dual_copy_on_re_onboard(
            home_path, skills_root=root, portfolio=pin_for_check
        )

    symlink = mode == "junction"
    report = _onboard.install_skills(
        skills_src=skills_src,
        skills_home=root,
        symlink=symlink,
    )
    report["skills_root"] = str(root)
    report["install_mode"] = mode
    report["home"] = str(home_path) if home_path is not None else None

    if portfolio is not None:
        pin = list(portfolio)
    else:
        # Prefer names that actually landed (installed + skipped).
        landed = []
        for bucket in ("installed", "skipped"):
            for item in report.get(bucket) or []:
                name = item.get("name") if isinstance(item, dict) else item
                if name and name not in landed:
                    landed.append(name)
        pin = landed if landed else vendor_portfolio_ids()
    report["portfolio_manifest"] = list(pin)

    # Seal after copy (immutability; re-vendor required if forked).
    report["seal_path"] = None
    if seal and root.is_dir() and any(root.iterdir()):
        try:
            manifest = _seal.build_seal_manifest(root)
            seal_path = _seal.write_seal(root, manifest)
            report["seal_path"] = str(seal_path)
        except _seal.SkillSealError as exc:
            raise SkillsRootError("seal-failed:%s" % exc) from exc

    if write_reg and home_path is not None:
        hosts = list(hosts_registered or [])
        doc = build_skills_root_doc(
            root,
            install_mode=mode,
            hosts_registered=hosts,
            portfolio_manifest=pin,
        )
        write_registry(doc, home=home_path)
        report["registry"] = str(skills_root_registry_path(home_path))

    # Post-install dual-copy gate (install itself never writes Claude farm).
    if refuse_dual and home_path is not None:
        refuse_dual_copy_on_re_onboard(
            home_path, skills_root=root, portfolio=pin
        )

    return report


def register_hosts(
    home,
    root=None,
    *,
    mode: str = "copy",
    hosts=None,
    portfolio=None,
) -> dict:
    """Register multiple host adapters against SKILLS_ROOT (recipient path).

    Default host set is equality participants (Claude/Grok/Anchor + Gemini
    when promoted). Returns ``{host: entry, ...}``.
    """
    home_path = Path(home)
    root_path = (
        Path(root) if root is not None else resolve_skills_root(home_path)
    )
    if portfolio is not None:
        refuse_dual_copy_on_re_onboard(
            home_path, skills_root=root_path, portfolio=portfolio
        )
    else:
        refuse_dual_copy_on_re_onboard(home_path, skills_root=root_path)

    host_list = list(hosts) if hosts is not None else list(EQUALITY_HOSTS)
    out = {}
    for h in host_list:
        if h not in HOST_IDS:
            raise SkillsRootError("register_host-unknown-host:%r" % (h,))
        if h == "gemini" and GEMINI_HOST_POLICY == "demoted":
            continue
        kwargs = {}
        if h == "grok":
            kwargs["skills_paths_include_skills_root"] = True
        out[h] = register_host(
            h, root_path, mode, home=home_path, **kwargs
        )
    return out


def product_bytes_only_under_skills_root(home, *, skills_root=None, portfolio=None) -> dict:
    """Acceptance helper: product SKILL.md trees live only under SKILLS_ROOT.

    Returns ``{"ok": bool, "problems": [...], "skills_root": str, ...}``.
    Claude adapter paths may be symlink/pointer but must not hold a full
    second product copy (SKILL.md without pointer/symlink).
    """
    root = (
        Path(skills_root)
        if skills_root is not None
        else resolve_skills_root(home)
    )
    pin = sorted(
        _portfolio_set(home, portfolio=portfolio),
        key=str.lower,
    )
    problems = []
    under_root = {}
    for sid in pin:
        skill_dir = root / sid
        under_root[sid] = skill_dir.is_dir() or skill_dir.is_symlink()
        if not under_root[sid]:
            problems.append("missing-under-skills-root:%s" % sid)

    dual = []
    for sid in pin:
        insp = inspect_claude_adapter(home, sid, skills_root=root)
        if insp.get("dual_copy"):
            dual.append(sid)
            problems.append("claude-dual-copy:%s" % sid)
    return {
        "ok": not problems,
        "problems": problems,
        "skills_root": str(root),
        "under_skills_root": under_root,
        "claude_dual_copy_ids": dual,
        "portfolio": pin,
    }


# ── Per-host portfolio list (adapter registration → SKILLS_ROOT only) ────────

def _skill_ids_under_root(skills_root: Path) -> list:
    """Skill directory names under SKILLS_ROOT (dirs only; no host-natives)."""
    root = Path(skills_root)
    if not root.is_dir():
        return []
    out = []
    try:
        for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
            if child.is_dir() and not child.name.startswith("."):
                out.append(child.name)
    except OSError:
        return []
    return out


def _portfolio_set(home=None, portfolio=None, registry=None) -> set:
    if portfolio is not None:
        return set(portfolio)
    reg = registry
    if reg is None and home is not None:
        try:
            reg = load_registry(home)
        except SkillsRootError:
            reg = None
    if reg and "portfolio_manifest" in reg:
        try:
            return set(normalize_portfolio_manifest(reg["portfolio_manifest"]))
        except SkillsRootError:
            pass
    return set(vendor_portfolio_ids())


def _host_registered(host: str, home=None, adapter_state=None, registry=None) -> bool:
    if adapter_state is None:
        adapter_state = load_adapter_state(home)
    hosts = adapter_state.get("hosts") or {}
    entry = hosts.get(host) or {}
    if entry.get("registered"):
        return True
    reg = registry
    if reg is None and home is not None:
        try:
            reg = load_registry(home)
        except SkillsRootError:
            reg = None
    if reg and host in (reg.get("hosts_registered") or []):
        return True
    return False


def list_portfolio_ids_claude(
    home=None,
    *,
    portfolio=None,
    adapter_state=None,
    registry=None,
    skills_root=None,
) -> list:
    """Skill IDs Claude loads via its **pointer** adapter to SKILLS_ROOT.

    Does not dump host-native thin locals. Unregistered → empty list.
    """
    if not _host_registered(
        "claude", home=home, adapter_state=adapter_state, registry=registry
    ):
        return []
    root = (
        Path(skills_root)
        if skills_root is not None
        else resolve_skills_root(home, registry=registry)
    )
    present = set(_skill_ids_under_root(root))
    pin = _portfolio_set(home, portfolio=portfolio, registry=registry)
    # Intersection: only portfolio IDs present under SKILLS_ROOT.
    return sorted(present & pin, key=str.lower)


def list_portfolio_ids_grok(
    home=None,
    *,
    portfolio=None,
    adapter_state=None,
    registry=None,
    skills_root=None,
) -> list:
    """Skill IDs Grok loads from **its** ``[skills].paths`` → SKILLS_ROOT.

    **Must not** count Claude-compat superset alone. Host-natives (bundled
    docx/design, etc.) are ignored. If ``skills_paths_include_skills_root``
    is false/missing while registered, returns **empty** (false GREEN fail).
    """
    if adapter_state is None:
        adapter_state = load_adapter_state(home)
    if not _host_registered(
        "grok", home=home, adapter_state=adapter_state, registry=registry
    ):
        return []

    entry = (adapter_state.get("hosts") or {}).get("grok") or {}
    # Explicit false → Claude-compat-only path: NOT portfolio GREEN.
    if entry.get("skills_paths_include_skills_root") is not True:
        return []

    root = (
        Path(skills_root)
        if skills_root is not None
        else resolve_skills_root(home, registry=registry)
    )
    present = set(_skill_ids_under_root(root))
    pin = _portfolio_set(home, portfolio=portfolio, registry=registry)
    # Host natives never enter this set (we only scan SKILLS_ROOT ∩ pin).
    return sorted(present & pin, key=str.lower)


def list_portfolio_ids_anchor(
    home=None,
    *,
    portfolio=None,
    adapter_state=None,
    registry=None,
    skills_root=None,
    env=None,
) -> list:
    """Skill IDs Anchor loads from ANCHOR_SKILLS_ROOT / registry SKILLS_ROOT."""
    if not _host_registered(
        "anchor", home=home, adapter_state=adapter_state, registry=registry
    ):
        return []
    root = (
        Path(skills_root)
        if skills_root is not None
        else resolve_skills_root(home, env=env, registry=registry)
    )
    present = set(_skill_ids_under_root(root))
    pin = _portfolio_set(home, portfolio=portfolio, registry=registry)
    return sorted(present & pin, key=str.lower)


def list_portfolio_ids_gemini(
    home=None,
    *,
    portfolio=None,
    adapter_state=None,
    registry=None,
    skills_root=None,
) -> list:
    """Skill IDs Gemini loads when promoted + registered (else empty)."""
    if not GEMINI_EQUALITY_PARTICIPANT:
        return []
    if not _host_registered(
        "gemini", home=home, adapter_state=adapter_state, registry=registry
    ):
        return []
    if adapter_state is None:
        adapter_state = load_adapter_state(home)
    entry = (adapter_state.get("hosts") or {}).get("gemini") or {}
    if entry.get("skills_json_points_at_skills_root") is False:
        return []
    root = (
        Path(skills_root)
        if skills_root is not None
        else resolve_skills_root(home, registry=registry)
    )
    present = set(_skill_ids_under_root(root))
    pin = _portfolio_set(home, portfolio=portfolio, registry=registry)
    return sorted(present & pin, key=str.lower)


_LIST_FNS = {
    "claude": list_portfolio_ids_claude,
    "grok": list_portfolio_ids_grok,
    "anchor": list_portfolio_ids_anchor,
    "gemini": list_portfolio_ids_gemini,
}


def portfolio_equality_oracle(
    home=None,
    *,
    portfolio=None,
    adapter_state=None,
    registry=None,
    skills_root=None,
    hosts=None,
) -> dict:
    """Criterion-2 equality: registered equality-hosts match vendor pin.

    Scoped to **registered** hosts that participate in equality (Claude,
    Grok, Anchor, and Gemini when promoted). Host-natives never break a
    match. Claude-compat-only Grok (paths omit SKILLS_ROOT) **fails**.

    Returns::

        {
          "ok": bool,
          "problems": [str, ...],
          "host_ids": {host: [ids...]},
          "portfolio": [ids...],
          "hosts_checked": [host, ...],
        }
    """
    pin = sorted(
        _portfolio_set(home, portfolio=portfolio, registry=registry),
        key=str.lower,
    )
    pin_set = set(pin)

    if registry is None and home is not None:
        try:
            registry = load_registry(home)
        except SkillsRootError:
            registry = None
    if adapter_state is None:
        adapter_state = load_adapter_state(home)

    if hosts is not None:
        check = [h for h in hosts if h in EQUALITY_HOSTS]
    else:
        registered = []
        if registry:
            registered = list(registry.get("hosts_registered") or [])
        # Also include adapter-state registered hosts.
        for h, entry in (adapter_state.get("hosts") or {}).items():
            if entry.get("registered") and h not in registered:
                registered.append(h)
        check = [h for h in EQUALITY_HOSTS if h in registered]

    host_ids = {}
    problems = []
    if not check:
        problems.append("equality-no-registered-hosts")
    for host in check:
        fn = _LIST_FNS[host]
        ids = fn(
            home,
            portfolio=pin,
            adapter_state=adapter_state,
            registry=registry,
            skills_root=skills_root,
        )
        host_ids[host] = list(ids)
        got = set(ids)
        if got != pin_set:
            missing = sorted(pin_set - got, key=str.lower)
            extra = sorted(got - pin_set, key=str.lower)
            problems.append(
                "host-portfolio-mismatch:%s:missing=%s:extra=%s"
                % (host, missing, extra)
            )
            if host == "grok":
                entry = (adapter_state.get("hosts") or {}).get("grok") or {}
                if entry.get("skills_paths_include_skills_root") is not True:
                    problems.append(
                        "grok-claude-compat-only:"
                        "skills_paths_omit_skills_root"
                    )

    return {
        "ok": not problems,
        "problems": problems,
        "host_ids": host_ids,
        "portfolio": pin,
        "hosts_checked": list(check),
    }
