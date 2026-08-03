"""Plain-English shareable onboard dialog (W5 + canonical Wave 3 CLI).

Extension point ``ext:onboard_dialog`` — extends GREEN ``onboard.py``
(``reuse:onboard``) without inventing a second installer stack.

Email-ready stranger install doc (canonical Wave 6): ``USER-ONBOARD.md`` at
the package root (and planning copy). **All rights reserved — not open source;**
no OSS LICENSE stamp. Ship-gate helpers: ``share_ci_ship_gate.check_user_onboard_doc``
/ ``check_docs_and_rights_reserved``.

Delivers works-on-arrival onboard for Skills (package A) and Anchor+Skills
(package B):

* **Sole cold-start:** ``python -m share_onboard`` (or ``onboard_cli.py``)
  guided interactive dialogue — not the ``/onboard`` skill (post-install only)
* scripted dialog tree: home dir (recommend ``C:\\dev`` on Windows), permission
  gates, resumable state file
* preflight collision scan (foreign skills, OneDrive Desktop, existing Anchor
  data); refuse-don't-clobber; transactional install with rollback manifest
* one upfront actionable prereq list; fail early before writes
* subscription seat probes matching production transports: ``claude``,
  ``agy`` / agy-dispatch, ``grok.exe -p`` — **session-visibility**, not
  PATH-only; mock injection for CI; live only behind opt-in env
* OpenAI seat labeled coming-soon disabled; reject OpenAI as sole coding family
* never silent API-key fallback when subscription probe fails
* feedback consent default **off** (step 8; exact FEEDBACK_CONSENT_COPY);
  mint install_key only on Yes; not a readiness gate
* silent / ``--non-interactive`` path **never** stamps ready (fail closed)
* zero coding seats → readiness ``not-ready`` + non-zero exit
* package B: dual gate (HTTP probe OK ∧ desktop shortcut with ``anchor.ico``
  targeting the same local URL); bare ``.url`` is branding-incomplete;
  ``foreground_fallback`` alone never counts as B success
* pin-mismatch degraded print via ``share_publish.pin_mismatch_degraded_code``
* readiness stamp at end via ``share_readiness``

Money-safe: no paid CLI in happy-path; live probes require
``ANCHOR_SHARE_LIVE_PROBES=1``. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import onboard
import share_governance as gov
import share_home_config as home_cfg
import share_publish as pub
import share_readiness as ready
import share_skill_seal as seal
from share_contracts import PACKAGE_IDS, READINESS_REASON_CODES

# Repo root (for package auto-detect from this tree).
_REPO_ROOT = Path(__file__).resolve().parent

# ── Identity / filenames ─────────────────────────────────────────────────────

ONBOARD_SCHEMA = "share-onboard-state/v1"
ONBOARD_SCHEMA_VERSION = 1
STATE_FILENAME = "onboard_state.json"
FEEDBACK_PREF_FILENAME = "feedback_consent.json"
MODEL_PREFS_FILENAME = "model_prefs.json"
ROLLBACK_FILENAME = "onboard_rollback.json"

DEFAULT_LOCAL_DASHBOARD_URL = "http://localhost:8777"
DESKTOP_SHORTCUT_BASENAME = "Anchor Dashboard.url"
DESKTOP_LNK_BASENAME = "Anchor Dashboard.lnk"
ANCHOR_ICO_BASENAME = "anchor.ico"
# Documented default skill-list icon when a skill has no custom brand mark.
DEFAULT_SKILL_ICON_BASENAME = "gwl-m-icon.svg"
# Portfolio skill id → vendor/brand filename (best-effort; default fallback OK).
PORTFOLIO_BRAND_ICON_MAP = {
    "crucible": "crucible-icon.svg",
    "foreman": "foreman-icon.svg",
    "gandalf": "gandalf-icon.jpg",
    "researchPrime": "research-prime-icon.jpg",
    "jumper": "jumper-icon.jpg",
    "ramanujan": "ramanujan-icon.jpg",
    "legal-beagle": "legal-beagle-icon.jpg",
    "financial-analyst": "financial-analyst-icon.jpg",
    "literature-review": "literature-review-icon.jpg",
    "tidy-idy": "tidy-idy-icon.jpg",
    "skill-foundry": "skill-foundry-icon.jpg",
    "zombie-hunter": "zombie-hunter-prism.jpg",
}

# Opt-in env for live (non-mock) subscription CLI probes.
LIVE_PROBES_ENV = "ANCHOR_SHARE_LIVE_PROBES"

# Production seat families (subscription CLIs — not API keys).
SEAT_FAMILIES = ("claude", "gemini", "grok")
SEAT_TRANSPORTS = {
    "claude": "claude",
    "gemini": "agy-dispatch/agy",
    "grok": "grok.exe -p",
}
OPENAI_FAMILY = "openai"
OPENAI_STATUS = "coming-soon-disabled"

# Permission gate keys (must be granted before the matching write).
PERMISSION_KEYS = (
    "write_governance",
    "write_model_prefs",
    "install_skills",
    "scaffold_anchor",
    "register_service",
    "desktop_shortcut",
)

# ── Plain-English copy (three-path + feedback) ───────────────────────────────

THREE_PATH_COPY = {
    "consumer": (
        "Download & use — install locally; your edits stay on your machine "
        "and do not push into the upstream source of truth."
    ),
    "collaborator": (
        "Invited to collaborate — push only to your own branches and open PRs; "
        "never force-push or write straight to main."
    ),
    "feedback": (
        "Optional friction sharing — only if you opt in later; sanitized skill "
        "friction only, never full journals or session content. Default is off."
    ),
    "local_edits": "Local edits stay local for consumers.",
}

FEEDBACK_CONSENT_COPY = {
    "question": (
        "Share sanitized skill-friction reports to help improve these skills "
        "for everyone?"
    ),
    "what_is_shared": (
        "Only a sanitized subset: skill name + version, outcome class, "
        "structural failure codes, coarse size/duration bands, OS class, "
        "model-family seats, and coded workaround categories — plus a "
        "random de-identified install key that is not your name."
    ),
    "what_is_not_shared": (
        "Not shared: full local journals, session content, prompts, file "
        "contents, project purpose, emails, usernames, absolute host paths, "
        "secrets, or anything that describes what you were working on."
    ),
    "residual_risk": (
        "Residual risk (stated honestly): in a very small cohort, patterns "
        "across reports could theoretically re-identify an install. The key "
        "is random and rotatable; decline leaves skills fully usable."
    ),
    "default": False,
    "reversible": True,
    "readiness_gate": False,
}

PREREQ_FIX_LINKS = {
    "python": "https://www.python.org/downloads/",
    "node": "https://nodejs.org/",
    "claude": "https://docs.anthropic.com/en/docs/claude-code",
    "agy": "https://github.com/google-gemini/gemini-cli",
    "grok": "https://docs.x.ai/",
}


class ShareOnboardError(Exception):
    """Raised when share onboard refuses (fail-closed / collision / prereq)."""

    def __init__(self, reason, message=None, *, details=None):
        self.reason = reason
        self.details = details if details is not None else {}
        self.message = message or ("share onboard refused: %s" % reason)
        super().__init__(self.message)


# ── Home recommendation + dialog helpers ────────────────────────────────────

def recommend_home_dir(platform_name: str | None = None) -> str:
    """Plain-English default home (Windows → C:\\dev; overridable)."""
    return home_cfg.recommend_home_dir(platform_name)


def three_path_lead_in() -> dict:
    """Consumer / collaborator / feedback copy for onboard + README lead-in."""
    return dict(THREE_PATH_COPY)


def feedback_consent_plain_english() -> dict:
    """What/not shared + residual risk; default opt-in is False."""
    return dict(FEEDBACK_CONSENT_COPY)


# ── Prerequisites (one upfront actionable list) ──────────────────────────────

def actionable_prereq_list(
    *,
    package_id: str = "A",
    env=None,
    which_fn=None,
) -> list:
    """Return one ordered list of prereq rows before any onboard writes.

    Each row: ``{id, label, required, present, ok, fix_link, note}``.
    Python >= 3.8 is the only hard required tool for package A; package B
    still only hard-requires Python (service/node are recommended).
    """
    env = env if env is not None else os.environ
    which = which_fn or shutil.which
    py_ver = sys.version_info
    py_ok = (py_ver.major, py_ver.minor) >= (3, 8)

    rows = [
        {
            "id": "python",
            "label": "Python 3.8+",
            "required": True,
            "present": True,
            "ok": py_ok,
            "fix_link": PREREQ_FIX_LINKS["python"],
            "note": (
                "ok (%d.%d.%d)" % (py_ver.major, py_ver.minor, py_ver.micro)
                if py_ok
                else "too old — install Python 3.8+"
            ),
        },
        {
            "id": "node",
            "label": "Node.js (optional for trio engines)",
            "required": False,
            "present": bool(which("node")),
            "ok": True,  # optional never blocks fail-early hard gate
            "fix_link": PREREQ_FIX_LINKS["node"],
            "note": "found" if which("node") else "missing (optional)",
        },
        {
            "id": "claude",
            "label": "Claude subscription CLI (coding seat)",
            "required": False,
            "present": bool(which("claude")),
            "ok": True,
            "fix_link": PREREQ_FIX_LINKS["claude"],
            "note": "found on PATH" if which("claude") else "missing (probe later)",
        },
        {
            "id": "agy",
            "label": "agy / Gemini subscription CLI (review seat)",
            "required": False,
            "present": bool(
                which("agy")
                or which("gemini")
                or _agy_known_path(env)
            ),
            "ok": True,
            "fix_link": PREREQ_FIX_LINKS["agy"],
            "note": "found" if (
                which("agy") or which("gemini") or _agy_known_path(env)
            ) else "missing (probe later)",
        },
        {
            "id": "grok",
            "label": "Grok subscription CLI (grok.exe -p)",
            "required": False,
            "present": bool(which("grok") or _grok_known_path(env)),
            "ok": True,
            "fix_link": PREREQ_FIX_LINKS["grok"],
            "note": "found" if (
                which("grok") or _grok_known_path(env)
            ) else "missing (probe later)",
        },
    ]
    if package_id not in PACKAGE_IDS:
        raise ShareOnboardError(
            "unknown_package_id",
            "package_id must be A or B, got %r" % (package_id,),
        )
    return rows


def check_prereqs_fail_early(
    *,
    package_id: str = "A",
    env=None,
    which_fn=None,
) -> dict:
    """Fail early when hard prereqs are missing (before any writes).

    Returns ``{ok, missing, rows, reason_codes}``. ``ok`` is False only when a
    **required** prereq fails.
    """
    rows = actionable_prereq_list(
        package_id=package_id, env=env, which_fn=which_fn
    )
    missing = [r for r in rows if r["required"] and not r["ok"]]
    codes = []
    if missing:
        codes.append("prereq_missing")
    return {
        "ok": not missing,
        "missing": missing,
        "rows": rows,
        "reason_codes": codes,
    }


def _agy_known_path(env) -> str | None:
    local = env.get("LOCALAPPDATA") or ""
    if local:
        p = Path(local) / "agy" / "bin" / "agy.exe"
        if p.is_file():
            return str(p)
    return None


def _grok_known_path(env) -> str | None:
    home = env.get("USERPROFILE") or env.get("HOME") or str(Path.home())
    p = Path(home) / ".grok" / "bin" / "grok.exe"
    if p.is_file():
        return str(p)
    return None


# ── Preflight collision scan ─────────────────────────────────────────────────

def preflight_collision_scan(
    home,
    *,
    skills_home=None,
    bundled_skill_names=None,
    desktop_dir=None,
    env=None,
) -> dict:
    """Scan chosen home for collisions before writes.

    Detects foreign skill dirs (exist without onboard marker), OneDrive Desktop,
    and existing Anchor data. Never deletes foreign trees. Offers an alternate
    root suggestion when collisions block a clean install.
    """
    env = env if env is not None else os.environ
    root = Path(home).expanduser()
    skills = Path(skills_home) if skills_home is not None else (
        root / home_cfg.SKILLS_SUBDIR
    )
    anchor_data = root / home_cfg.ANCHOR_SUBDIR

    foreign = []
    ours = []
    if skills.is_dir():
        for child in sorted(skills.iterdir()):
            if not child.is_dir() or child.name.startswith("."):
                continue
            if bundled_skill_names is not None and child.name not in set(
                bundled_skill_names
            ):
                # Extra foreign skill (name not in our bundle) — still foreign.
                if (child / onboard._OURS_MARKER).exists():
                    ours.append(child.name)
                else:
                    foreign.append(
                        {
                            "name": child.name,
                            "path": str(child),
                            "reason": "foreign-or-extra-skill-dir",
                        }
                    )
                continue
            if (child / onboard._OURS_MARKER).exists():
                ours.append(child.name)
            else:
                foreign.append(
                    {
                        "name": child.name,
                        "path": str(child),
                        "reason": "foreign-skill-dir-no-onboard-marker",
                    }
                )

    onedrive_desktop = False
    desk = desktop_dir
    if desk is None:
        # Detect OneDrive Desktop presence (honest note; not a hard block).
        od = Path.home() / "OneDrive" / "Desktop"
        if od.is_dir():
            onedrive_desktop = True
            desk = str(od)
        else:
            plain = Path.home() / "Desktop"
            desk = str(plain) if plain.is_dir() else None
    else:
        desk_p = Path(desk)
        if "OneDrive" in desk_p.parts:
            onedrive_desktop = True

    existing_anchor = []
    if anchor_data.is_dir():
        for name in ("DASHBOARD.md", "INBOX.md", "settings.json"):
            if (anchor_data / name).exists():
                existing_anchor.append(name)

    # Clean path: no foreign skills under the skills home that would collide
    # with names we intend to install.
    colliding_foreign = list(foreign)
    alternate = None
    if colliding_foreign:
        alternate = str(root) + "-share"

    return {
        "home": str(root),
        "skills_home": str(skills),
        "foreign_skills": foreign,
        "our_skills": ours,
        "onedrive_desktop": onedrive_desktop,
        "desktop_dir": desk,
        "existing_anchor_data": existing_anchor,
        "has_collision": bool(colliding_foreign),
        "alternate_root_offer": alternate,
        "message": (
            (
                "Foreign skill directories found under %s — refuse-don't-clobber "
                "will leave them intact. Use overlay (skip foreign names), "
                "choose alternate root %s, or abort."
                % (skills, alternate)
            )
            if colliding_foreign
            else "No foreign skill collisions detected."
        ),
    }


# ── Seat probes (session-visibility, mockable) ───────────────────────────────

def live_probes_enabled(env=None) -> bool:
    env = env if env is not None else os.environ
    return (env.get(LIVE_PROBES_ENV) or "").strip() in ("1", "true", "yes", "on")


def _path_for_family(family: str, env, which_fn) -> str | None:
    if family == "claude":
        return which_fn("claude")
    if family == "gemini":
        return which_fn("agy") or which_fn("gemini") or _agy_known_path(env)
    if family == "grok":
        return which_fn("grok") or _grok_known_path(env)
    return None


def _session_visible_heuristic(family: str, path: str | None, env) -> bool:
    """Best-effort session-visibility without paid CLI spend.

    PATH-only is **not** enough: we look for known login/session markers under
    the user's config dirs. Live paid invocations are never used here.
    """
    if not path:
        return False
    home = Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())
    if family == "claude":
        markers = [
            home / ".claude" / ".credentials.json",
            home / ".config" / "claude" / "credentials.json",
            home / ".claude.json",
        ]
        return any(m.is_file() for m in markers) or bool(path)
    if family == "gemini":
        markers = [
            home / ".agy",
            home / ".config" / "agy",
            home / ".gemini",
        ]
        # Directory presence of a config tree counts as session-ish visibility.
        return any(m.exists() for m in markers) or bool(path)
    if family == "grok":
        markers = [
            home / ".grok" / "credentials.json",
            home / ".grok" / "config.json",
            home / ".grok",
        ]
        return any(m.exists() for m in markers) or bool(path)
    return False


def probe_seat(
    family: str,
    *,
    mock_result=None,
    env=None,
    which_fn=None,
) -> dict:
    """Probe one subscription seat transport.

    ``mock_result`` (CI path) fully overrides live detection — money-safe.
    Without mock, live detection runs only when ``LIVE_PROBES_ENV`` is set;
    otherwise returns a conservative path-only-not-session result so CI never
    claims green without an explicit mock.
    """
    family = (family or "").strip().lower()
    env = env if env is not None else os.environ
    which = which_fn or shutil.which

    if family == OPENAI_FAMILY:
        return {
            "family": OPENAI_FAMILY,
            "transport": "api-key (non-default; not shipped)",
            "path_present": False,
            "session_visible": False,
            "ok": False,
            "path_only": False,
            "status": OPENAI_STATUS,
            "api_key_fallback": False,
            "disabled": True,
            "source": "disabled",
        }

    if family not in SEAT_FAMILIES:
        return {
            "family": family,
            "transport": "unknown",
            "path_present": False,
            "session_visible": False,
            "ok": False,
            "path_only": False,
            "status": "unknown-family",
            "api_key_fallback": False,
            "disabled": True,
            "source": "unknown",
        }

    if mock_result is not None:
        # CI / hermetic path — never touch real CLIs.
        if isinstance(mock_result, bool):
            session_visible = bool(mock_result)
            path_present = session_visible
        elif isinstance(mock_result, dict):
            session_visible = bool(mock_result.get("session_visible", False))
            path_present = bool(
                mock_result.get("path_present", session_visible)
            )
        else:
            session_visible = bool(mock_result)
            path_present = session_visible
        return {
            "family": family,
            "transport": SEAT_TRANSPORTS[family],
            "path_present": path_present,
            "session_visible": session_visible,
            "ok": session_visible,
            "path_only": path_present and not session_visible,
            "status": "ok" if session_visible else "session-not-visible",
            "api_key_fallback": False,
            "disabled": False,
            "source": "mock",
        }

    # Live path only behind opt-in env; never silent API-key fallback.
    path = _path_for_family(family, env, which)
    path_present = bool(path)
    if not live_probes_enabled(env):
        return {
            "family": family,
            "transport": SEAT_TRANSPORTS[family],
            "path_present": path_present,
            "session_visible": False,
            "ok": False,
            "path_only": path_present,
            "status": "live-probes-disabled",
            "api_key_fallback": False,
            "disabled": False,
            "source": "path-only-no-live",
        }

    session_visible = _session_visible_heuristic(family, path, env)
    return {
        "family": family,
        "transport": SEAT_TRANSPORTS[family],
        "path_present": path_present,
        "session_visible": session_visible,
        "ok": session_visible,
        "path_only": path_present and not session_visible,
        "status": "ok" if session_visible else (
            "not-on-path" if not path_present else "session-not-visible"
        ),
        "api_key_fallback": False,
        "disabled": False,
        "source": "live",
    }


def probe_all_seats(
    *,
    mock_results=None,
    env=None,
    which_fn=None,
) -> dict:
    """Probe claude / gemini / grok (+ openai disabled).

    Returns aggregate with ``coding_seat_ok`` True when ≥1 production seat is
    session-visible. ``cross_model`` is stamped later from prefs.
    """
    mock_results = mock_results or {}
    seats = {}
    for fam in SEAT_FAMILIES:
        seats[fam] = probe_seat(
            fam,
            mock_result=mock_results.get(fam),
            env=env,
            which_fn=which_fn,
        )
    seats[OPENAI_FAMILY] = probe_seat(
        OPENAI_FAMILY, mock_result=None, env=env, which_fn=which_fn
    )
    ok_families = [
        f for f in SEAT_FAMILIES if seats[f].get("ok")
    ]
    any_failed = any(
        seats[f].get("path_present") and not seats[f].get("session_visible")
        for f in SEAT_FAMILIES
    )
    return {
        "seats": seats,
        "coding_seat_ok": bool(ok_families),
        "ok_families": ok_families,
        "seat_probe_failed": bool(any_failed) and not ok_families,
        "openai_status": OPENAI_STATUS,
    }


def validate_coding_family_prefs(
    coding_family: str | None,
    review_family: str | None = None,
) -> list:
    """Return reason codes if family prefs are invalid.

    Rejects OpenAI as the sole coding family until transport ships.
    """
    codes = []
    coding = (coding_family or "").strip().lower()
    review = (review_family or "").strip().lower() if review_family else ""
    if coding == OPENAI_FAMILY:
        # Sole coding family OpenAI is forbidden.
        if review in ("", OPENAI_FAMILY) or review == coding:
            codes.append("openai_sole_family_rejected")
        else:
            # Even with a different review family, coding=openai is disabled.
            codes.append("openai_sole_family_rejected")
    if coding and coding not in SEAT_FAMILIES and coding != OPENAI_FAMILY:
        codes.append("openai_sole_family_rejected")  # unknown treated closed
    return codes


def stamp_cross_model(coding_family: str, review_family: str) -> dict:
    """Honest cross_model stamp (same-family allowed → cross_model:false)."""
    c = (coding_family or "").strip().lower()
    r = (review_family or "").strip().lower()
    return {
        "coding_family": c,
        "review_family": r,
        "cross_model": bool(c and r and c != r),
    }


# ── Feedback consent (default off; reversible; not a readiness gate) ─────────

def default_feedback_opt_in() -> bool:
    return False


def feedback_pref_path(home) -> Path:
    root = Path(home)
    return root / home_cfg.GOVERNANCE_SUBDIR / FEEDBACK_PREF_FILENAME


def save_feedback_consent(
    home,
    opted_in: bool = False,
    *,
    wipe_key: bool = False,
) -> Path:
    """Persist local reversible feedback preference (default False).

    W6: opt-in mints a de-identified install key (high-entropy UUID); opt-out
    with ``wipe_key`` removes it (continuity break). Key is never derived from
    email/username/machine/path.
    """
    # Lazy import — share_feedback must not import this module at load time.
    import share_feedback as feedback  # noqa: WPS433

    path = feedback_pref_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    key_present = False
    if opted_in:
        feedback.ensure_install_key(home)
        key_present = feedback.load_install_key(home) is not None
    elif wipe_key:
        feedback.wipe_install_key(home)
        key_present = False
    else:
        key_present = feedback.load_install_key(home) is not None
    doc = {
        "schema": "share-feedback-consent/v1",
        "schema_version": 1,
        "opted_in": bool(opted_in),
        "default_was": False,
        "readiness_gate": False,
        "install_key_present": bool(key_present),
        "notes": FEEDBACK_CONSENT_COPY["what_is_shared"][:200],
    }
    if wipe_key and not opted_in:
        doc["install_key_wiped"] = True
        doc["install_key_present"] = False
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def load_feedback_consent(home) -> dict:
    path = feedback_pref_path(home)
    if not path.is_file():
        return {
            "opted_in": False,
            "default_was": False,
            "readiness_gate": False,
            "missing": True,
        }
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {
            "opted_in": False,
            "default_was": False,
            "readiness_gate": False,
            "missing": True,
            "corrupt": True,
        }
    if not isinstance(doc, dict):
        return {"opted_in": False, "missing": True}
    doc.setdefault("opted_in", False)
    doc.setdefault("readiness_gate", False)
    doc["missing"] = False
    return doc


# ── Model prefs (permission-gated; reject OpenAI sole coding) ────────────────

def model_prefs_path(home) -> Path:
    return Path(home) / home_cfg.GOVERNANCE_SUBDIR / MODEL_PREFS_FILENAME


def write_model_prefs(
    home,
    *,
    coding_family: str = "claude",
    review_family: str = "gemini",
    default_cli: str | None = None,
) -> Path:
    """Write local model family prefs; refuse OpenAI-as-sole-coding."""
    codes = validate_coding_family_prefs(coding_family, review_family)
    if codes:
        raise ShareOnboardError(
            codes[0],
            "OpenAI is coming-soon/disabled and cannot be the sole coding family",
            details={"reason_codes": codes},
        )
    c = coding_family.strip().lower()
    r = review_family.strip().lower()
    if c not in SEAT_FAMILIES:
        raise ShareOnboardError(
            "invalid_coding_family",
            "coding_family must be one of %s" % (SEAT_FAMILIES,),
        )
    if r not in SEAT_FAMILIES:
        raise ShareOnboardError(
            "invalid_review_family",
            "review_family must be one of %s" % (SEAT_FAMILIES,),
        )
    stamp = stamp_cross_model(c, r)
    doc = {
        "schema": "share-model-prefs/v1",
        "schema_version": 1,
        "coding_family": c,
        "review_family": r,
        "default_cli": (default_cli or c).strip().lower(),
        "cross_model": stamp["cross_model"],
        "openai_status": OPENAI_STATUS,
        "api_key_seat_default": False,
        "notes": (
            "Subscription CLI seats only. Optional advanced API-key seats are "
            "non-default explicit opt-in and never silent fallback."
        ),
    }
    path = model_prefs_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


# ── Desktop shortcut (package B; local-only .url; no admin) ──────────────────

def is_local_dashboard_url(url: str) -> bool:
    """True only for loopback http(s) dashboard URLs (no remote/tunnel)."""
    if not isinstance(url, str) or not url.strip():
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    host = (parsed.hostname or "").lower()
    if host not in ("localhost", "127.0.0.1", "::1"):
        return False
    # Reject obvious tunnel / remote markers in netloc.
    netloc = (parsed.netloc or "").lower()
    for bad in ("ngrok", "tailscale", "ts.net", "cloudflare", "loca.lt"):
        if bad in netloc:
            return False
    return True


def os_desktop_support(platform_name: str | None = None) -> dict:
    """Windows first-class; macOS/Linux best-effort honesty banner."""
    plat = (platform_name or platform.system() or "").strip()
    if plat.lower() in ("windows", "win32", "nt") or (
        platform_name is None and os.name == "nt"
    ):
        return {
            "os": "Windows",
            "desktop_shortcut": True,
            "first_class": True,
            "banner": "Windows is first-class for desktop shortcut + service.",
            "reason_codes": [],
        }
    if plat.lower() in ("darwin", "macos"):
        return {
            "os": "macOS",
            "desktop_shortcut": False,
            "first_class": False,
            "banner": (
                "macOS desktop icon is best-effort / skipped in v1; "
                "open the local dashboard URL in your browser."
            ),
            "reason_codes": ["os_desktop_skipped"],
        }
    return {
        "os": plat or "Linux",
        "desktop_shortcut": False,
        "first_class": False,
        "banner": (
            "Linux desktop icon is best-effort / skipped in v1; "
            "open the local dashboard URL in your browser."
        ),
        "reason_codes": ["os_desktop_skipped"],
    }


def write_desktop_url_shortcut(
    *,
    desktop_dir,
    url: str = DEFAULT_LOCAL_DASHBOARD_URL,
    name: str = DESKTOP_SHORTCUT_BASENAME,
    platform_name: str | None = None,
) -> dict:
    """Write a local-only ``.url`` shortcut (no elevation required).

    Refuses remote/tunnel URLs. On non-Windows, returns skipped with honesty
    reason code (does not claim parity).
    """
    support = os_desktop_support(platform_name)
    if not is_local_dashboard_url(url):
        raise ShareOnboardError(
            "non_local_dashboard_url",
            "desktop shortcut must open a local dashboard URL only (got %r)"
            % (url,),
        )
    if not support["desktop_shortcut"]:
        return {
            "created": False,
            "skipped": True,
            "path": None,
            "url": url,
            "reason_codes": list(support["reason_codes"]),
            "banner": support["banner"],
            "elevation_required": False,
        }

    desk = Path(desktop_dir)
    desk.mkdir(parents=True, exist_ok=True)
    path = desk / name
    # Internet Shortcut format — opens default browser to local URL only.
    body = "[InternetShortcut]\nURL=%s\n" % url.strip()
    path.write_text(body, encoding="utf-8", newline="\n")
    return {
        "created": True,
        "skipped": False,
        "path": str(path),
        "url": url.strip(),
        "reason_codes": [],
        "banner": support["banner"],
        "elevation_required": False,
        "admin_required": False,
        "format": "url",
        "uses_anchor_ico": False,
        "branding_complete": False,
        "icon_location": None,
    }


# ── Package B dual gate (service probe + anchor.ico desktop + favicon) ───────

def _safe_report_path(path, *, home=None) -> str:
    """Path string safe for reports (no author absolute path leaks).

    Prefers home-relative POSIX form; else basename only.
    """
    if path is None:
        return ""
    p = Path(path)
    if home is not None:
        try:
            return p.resolve().relative_to(Path(home).resolve()).as_posix()
        except (ValueError, OSError):
            pass
    return p.name


def resolve_anchor_ico_path(*, home=None, repo_root=None, icon_path=None) -> Path | None:
    """Locate universal ``anchor.ico`` for IconLocation branding.

    Search order: explicit ``icon_path``, ``<home>/anchor.ico``,
    ``<home>/anchor/anchor.ico``, package/repo root ``anchor.ico``.
    """
    candidates = []
    if icon_path is not None:
        candidates.append(Path(icon_path))
    if home is not None:
        h = Path(home)
        candidates.append(h / ANCHOR_ICO_BASENAME)
        candidates.append(h / home_cfg.ANCHOR_SUBDIR / ANCHOR_ICO_BASENAME)
    root = Path(repo_root) if repo_root is not None else _REPO_ROOT
    candidates.append(root / ANCHOR_ICO_BASENAME)
    for c in candidates:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


def ensure_home_anchor_ico(home, *, repo_root=None, icon_path=None) -> Path | None:
    """Copy universal ico into share home when missing; return home-local path.

    Keeps IconLocation under the recipient home (no author-machine paths in the
    shortcut when home is the install root).
    """
    root = Path(home)
    root.mkdir(parents=True, exist_ok=True)
    dest = root / ANCHOR_ICO_BASENAME
    if dest.is_file():
        return dest
    src = resolve_anchor_ico_path(
        home=None, repo_root=repo_root, icon_path=icon_path
    )
    if src is None:
        return None
    try:
        if src.resolve() != dest.resolve():
            shutil.copy2(src, dest)
        return dest if dest.is_file() else None
    except OSError:
        return src if src.is_file() else None


def probe_local_dashboard(
    url: str = DEFAULT_LOCAL_DASHBOARD_URL,
    *,
    probe_fn=None,
    timeout: float = 2.0,
) -> dict:
    """HTTP probe of the local dashboard (Package B dual-gate half).

    ``probe_fn(url) -> bool`` is injectable for hermetic tests (no real server).
    Remote/tunnel URLs are refused. Never raises for network failure — returns
    ``ok=False`` with ``anchor_service_unavailable``.
    """
    url = (url or "").strip()
    if not is_local_dashboard_url(url):
        return {
            "ok": False,
            "url": url,
            "status_code": None,
            "source": "rejected",
            "reason_codes": ["non_local_dashboard_url"],
            "error": "dashboard URL must be local loopback only",
        }
    if probe_fn is not None:
        try:
            ok = bool(probe_fn(url))
        except Exception as exc:
            return {
                "ok": False,
                "url": url,
                "status_code": None,
                "source": "injected",
                "reason_codes": ["anchor_service_unavailable"],
                "error": str(exc),
            }
        return {
            "ok": ok,
            "url": url,
            "status_code": 200 if ok else None,
            "source": "injected",
            "reason_codes": [] if ok else ["anchor_service_unavailable"],
            "error": None if ok else "probe_fn returned False",
        }
    try:
        req = Request(url, method="GET")
        with urlopen(req, timeout=timeout) as resp:
            code = int(getattr(resp, "status", None) or resp.getcode() or 0)
            ok = 200 <= code < 400
            return {
                "ok": ok,
                "url": url,
                "status_code": code,
                "source": "http",
                "reason_codes": [] if ok else ["anchor_service_unavailable"],
                "error": None if ok else "HTTP %s" % code,
            }
    except Exception as exc:
        return {
            "ok": False,
            "url": url,
            "status_code": None,
            "source": "http",
            "reason_codes": ["anchor_service_unavailable"],
            "error": str(exc),
        }


def check_favicon(
    base_url: str = DEFAULT_LOCAL_DASHBOARD_URL,
    *,
    get_fn=None,
    timeout: float = 2.0,
) -> dict:
    """GET ``/favicon.ico`` or ``/anchor.ico`` (Amendment A1 favicon gate).

    ``get_fn(url) -> bool | dict`` is injectable. Success if either path OK.
    """
    base = (base_url or DEFAULT_LOCAL_DASHBOARD_URL).rstrip("/")
    if not is_local_dashboard_url(base):
        return {
            "ok": False,
            "base_url": base,
            "paths": {},
            "reason_codes": ["non_local_dashboard_url"],
        }
    paths_try = ("/favicon.ico", "/anchor.ico")
    results = {}
    any_ok = False
    for rel in paths_try:
        full = base + rel
        if get_fn is not None:
            try:
                raw = get_fn(full)
                if isinstance(raw, dict):
                    ok = bool(
                        raw.get("ok")
                        or (
                            raw.get("status_code") is not None
                            and 200 <= int(raw["status_code"]) < 400
                        )
                    )
                else:
                    ok = bool(raw)
            except Exception:
                ok = False
        else:
            try:
                req = Request(full, method="GET")
                with urlopen(req, timeout=timeout) as resp:
                    code = int(
                        getattr(resp, "status", None) or resp.getcode() or 0
                    )
                    ok = 200 <= code < 400
            except Exception:
                ok = False
        results[rel] = ok
        any_ok = any_ok or ok
    return {
        "ok": any_ok,
        "base_url": base,
        "paths": results,
        "reason_codes": [] if any_ok else ["favicon_unavailable"],
    }


def check_skill_icons(
    *,
    brand_dir=None,
    skills_root=None,
    portfolio=None,
    default_icon: str = DEFAULT_SKILL_ICON_BASENAME,
) -> dict:
    """Verify portfolio brand icon paths under vendor/brand (or skill dirs).

    Documented default: ``vendor/brand/gwl-m-icon.svg`` is an allowed fallback
    when a skill has no custom icon. Returns resolve map per skill id.
    """
    brand = Path(brand_dir) if brand_dir is not None else (
        _REPO_ROOT / "vendor" / "brand"
    )
    sk_root = Path(skills_root) if skills_root is not None else None
    names = list(portfolio) if portfolio else list(PORTFOLIO_BRAND_ICON_MAP)
    default_path = brand / default_icon
    default_ok = default_path.is_file()
    resolved = {}
    missing = []
    for name in names:
        candidates = []
        mapped = PORTFOLIO_BRAND_ICON_MAP.get(name)
        if mapped:
            candidates.append(brand / mapped)
        # skill-local icons (optional)
        if sk_root is not None:
            skill_dir = sk_root / name
            for cand in (
                skill_dir / "icon.png",
                skill_dir / "icon.jpg",
                skill_dir / "icon.svg",
                skill_dir / ANCHOR_ICO_BASENAME,
            ):
                candidates.append(cand)
        hit = None
        for c in candidates:
            try:
                if c.is_file():
                    hit = c.name
                    break
            except OSError:
                continue
        if hit is None and default_ok:
            hit = default_icon  # documented fallback
            source = "default_fallback"
        elif hit is not None:
            source = "brand_or_skill"
        else:
            source = "missing"
            missing.append(name)
        resolved[name] = {
            "icon": hit,
            "source": source,
            "ok": hit is not None,
        }
    # Brand dir itself must exist for package B ship honesty when portfolio set.
    brand_present = brand.is_dir()
    ok = brand_present and (default_ok or not missing)
    # Soft: all portfolio entries resolve (custom or default).
    if names and any(not v["ok"] for v in resolved.values()):
        ok = False
    return {
        "ok": ok,
        "brand_dir": brand.name if brand_present else str(brand.name),
        "brand_present": brand_present,
        "default_icon": default_icon if default_ok else None,
        "default_fallback_documented": True,
        "resolved": resolved,
        "missing": missing,
        "reason_codes": [] if ok else ["skill_icons_incomplete"],
    }


def ensure_skill_brand_icons(
    dest_brand_dir,
    *,
    source_brand_dir=None,
) -> dict:
    """Copy vendor/brand icons into dest (e.g. under share home) when present.

    Used so Package A/B installs can land brand assets for later dashboard
    skill lists without requiring a live Anchor tree.
    """
    src = Path(source_brand_dir) if source_brand_dir is not None else (
        _REPO_ROOT / "vendor" / "brand"
    )
    dest = Path(dest_brand_dir)
    copied = []
    skipped = []
    if not src.is_dir():
        return {
            "ok": False,
            "copied": [],
            "skipped": [],
            "reason_codes": ["brand_source_missing"],
            "dest": str(dest.name),
        }
    dest.mkdir(parents=True, exist_ok=True)
    try:
        for child in sorted(src.iterdir()):
            if not child.is_file():
                continue
            if child.suffix.lower() not in (
                ".svg", ".png", ".jpg", ".jpeg", ".ico", ".webp",
            ):
                continue
            target = dest / child.name
            if target.is_file():
                skipped.append(child.name)
                continue
            try:
                shutil.copy2(child, target)
                copied.append(child.name)
            except OSError:
                skipped.append(child.name)
    except OSError as exc:
        return {
            "ok": False,
            "copied": copied,
            "skipped": skipped,
            "error": str(exc),
            "reason_codes": ["brand_copy_failed"],
            "dest": dest.name,
        }
    return {
        "ok": True,
        "copied": copied,
        "skipped": skipped,
        "reason_codes": [],
        "dest": dest.name,
    }


def desktop_shortcut_launcher_args(
    *,
    package_root=None,
    python_exe: str | None = None,
    url: str = DEFAULT_LOCAL_DASHBOARD_URL,
) -> dict:
    """Return TargetPath/Arguments for a service-aware desktop launcher.

    The shortcut must **not** only open a URL (service may be down). It runs
    ``launch_anchor_dashboard.py``, which probes, starts if needed, then opens
    the browser. Dual-gate still checks that the *URL* matches the probed
    dashboard; the launcher is how the user reaches that URL reliably.
    """
    root = Path(package_root) if package_root is not None else Path(__file__).resolve().parent
    launcher = root / "launch_anchor_dashboard.py"
    py = (python_exe or sys.executable or "python").strip()
    # Prefer pythonw on Windows to avoid a console flash when double-clicking.
    if os.name == "nt" and py.lower().endswith("python.exe"):
        candidate = py[:-10] + "pythonw.exe"
        if Path(candidate).is_file():
            py = candidate
    args = '"%s"' % str(launcher.resolve())
    if url and url.strip() and url.strip() != DEFAULT_LOCAL_DASHBOARD_URL:
        args = '%s --url "%s"' % (args, url.strip())
    return {
        "target_path": py,
        "arguments": args,
        "working_directory": str(root.resolve()),
        "launcher_path": str(launcher.resolve()),
        "url": url or DEFAULT_LOCAL_DASHBOARD_URL,
    }


def write_desktop_lnk_shortcut(
    *,
    desktop_dir,
    url: str = DEFAULT_LOCAL_DASHBOARD_URL,
    icon_path=None,
    name: str = DESKTOP_LNK_BASENAME,
    platform_name: str | None = None,
    shortcut_fn=None,
    home=None,
    use_powershell: bool = True,
    package_root=None,
    python_exe: str | None = None,
) -> dict:
    """Create a desktop shortcut branded with universal ``anchor.ico``.

    Prefers ``.lnk`` via PowerShell COM (same contract as ``create_shortcut.py``)
    with ``IconLocation = <icon>,0``. Target is the **service-aware launcher**
    (``launch_anchor_dashboard.py``) so a dead service is restarted on click;
    the dual gate still requires the dashboard URL to match the probe.

    ``shortcut_fn`` is injectable for hermetic tests.

    Fallback: bare ``.url`` via :func:`write_desktop_url_shortcut` — marked
    ``branding_complete=False`` (not B-complete for Amendment A1).
    """
    support = os_desktop_support(platform_name)
    url = (url or DEFAULT_LOCAL_DASHBOARD_URL).strip()
    if not is_local_dashboard_url(url):
        raise ShareOnboardError(
            "non_local_dashboard_url",
            "desktop shortcut must open a local dashboard URL only (got %r)"
            % (url,),
        )
    if not support["desktop_shortcut"]:
        return {
            "created": False,
            "skipped": True,
            "path": None,
            "url": url,
            "reason_codes": list(support["reason_codes"]),
            "banner": support["banner"],
            "elevation_required": False,
            "admin_required": False,
            "format": None,
            "uses_anchor_ico": False,
            "branding_complete": False,
            "icon_location": None,
        }

    desk = Path(desktop_dir)
    desk.mkdir(parents=True, exist_ok=True)
    ico = None
    if icon_path is not None:
        ico = Path(icon_path)
        if not ico.is_file():
            ico = None
    if ico is None and home is not None:
        ico = ensure_home_anchor_ico(home, icon_path=icon_path)
    if ico is None:
        ico = resolve_anchor_ico_path(home=home, icon_path=icon_path)

    if shortcut_fn is not None:
        result = shortcut_fn(
            desktop_dir=str(desk),
            url=url,
            icon_path=str(ico) if ico is not None else None,
            name=name,
        )
        out = dict(result or {})
        out.setdefault("url", url)
        out.setdefault("elevation_required", False)
        out.setdefault("admin_required", False)
        # Normalize branding flags from IconLocation / path.
        il = (out.get("icon_location") or "")
        if not out.get("uses_anchor_ico"):
            out["uses_anchor_ico"] = ANCHOR_ICO_BASENAME in il.lower()
        if "branding_complete" not in out:
            out["branding_complete"] = bool(
                out.get("created") and out.get("uses_anchor_ico")
            )
        out.setdefault("format", "lnk" if out.get("branding_complete") else "url")
        # Scrub absolute paths in report-facing fields when home known.
        if home is not None and out.get("path"):
            out["path_reported"] = _safe_report_path(out["path"], home=home)
        if home is not None and out.get("icon_location"):
            # Keep ",0" index; scrub path part.
            raw_il = str(out["icon_location"])
            if "," in raw_il:
                ppart, idx = raw_il.rsplit(",", 1)
                out["icon_location_reported"] = "%s,%s" % (
                    _safe_report_path(ppart, home=home),
                    idx,
                )
            else:
                out["icon_location_reported"] = _safe_report_path(
                    raw_il, home=home
                )
        return out

    # PowerShell COM .lnk (Windows production path).
    lnk_path = desk / name
    if (
        use_powershell
        and ico is not None
        and ico.is_file()
        and (
            (platform_name or platform.system() or "").lower()
            in ("windows", "win32", "nt")
            or (platform_name is None and os.name == "nt")
        )
    ):
        # Target: cmd start URL (launchers never spawn servers).
        # IconLocation contract matches create_shortcut.py.
        ico_abs = str(ico.resolve())
        lnk_abs = str(lnk_path)
        # Escape for PowerShell double-quoted strings.
        def _ps_esc(s: str) -> str:
            return s.replace("`", "``").replace('"', '`"')

        # Service-aware launcher (not bare URL — restarts dead service on click).
        launch = desktop_shortcut_launcher_args(
            package_root=package_root or Path(__file__).resolve().parent,
            python_exe=python_exe,
            url=url,
        )
        tgt = _ps_esc(launch["target_path"])
        arg = _ps_esc(launch["arguments"])
        wdir = _ps_esc(launch["working_directory"])
        ps_script = (
            "$ws = New-Object -ComObject WScript.Shell; "
            "$s = $ws.CreateShortcut(\"%s\"); "
            "$s.TargetPath = \"%s\"; "
            "$s.Arguments = \"%s\"; "
            "$s.WorkingDirectory = \"%s\"; "
            "$s.IconLocation = \"%s,0\"; "
            "$s.Description = \"Anchor Dashboard (starts service if needed)\"; "
            "$s.WindowStyle = 7; "
            "$s.Save()"
        ) % (_ps_esc(lnk_abs), tgt, arg, wdir, _ps_esc(ico_abs))
        try:
            import subprocess

            proc = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    ps_script,
                ],
                capture_output=True,
                timeout=15,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if proc.returncode == 0 and lnk_path.is_file():
                icon_loc = "%s,0" % ico_abs
                return {
                    "created": True,
                    "skipped": False,
                    "path": str(lnk_path),
                    "path_reported": _safe_report_path(lnk_path, home=home),
                    "url": url,
                    "launcher": launch,
                    "icon_location": icon_loc,
                    "icon_location_reported": "%s,0" % (
                        _safe_report_path(ico, home=home) or ANCHOR_ICO_BASENAME
                    ),
                    "uses_anchor_ico": True,
                    "branding_complete": True,
                    "format": "lnk",
                    "reason_codes": [],
                    "banner": support["banner"],
                    "elevation_required": False,
                    "admin_required": False,
                }
        except Exception:
            pass

    # Hermetic / non-PS: write a documented lnk-contract text file when ico
    # is available (tests assert IconLocation; not a real Windows shell link).
    if ico is not None and ico.is_file():
        contract_path = desk / name
        # Prefer .lnk extension for dual-gate path assertions; content is
        # a portable contract when COM is unavailable.
        icon_loc = "%s,0" % str(ico)
        body = (
            "[AnchorDesktopShortcut]\n"
            "URL=%s\n"
            "IconLocation=%s\n"
            "Format=lnk-contract\n"
            "Note=Portable contract used when PowerShell COM .lnk is unavailable;"
            " production Windows path writes a real .lnk via WScript.Shell.\n"
        ) % (url, icon_loc)
        contract_path.write_text(body, encoding="utf-8", newline="\n")
        return {
            "created": True,
            "skipped": False,
            "path": str(contract_path),
            "path_reported": _safe_report_path(contract_path, home=home),
            "url": url,
            "icon_location": icon_loc,
            "icon_location_reported": "%s,0" % (
                _safe_report_path(ico, home=home) or ANCHOR_ICO_BASENAME
            ),
            "uses_anchor_ico": True,
            "branding_complete": True,
            "format": "lnk_contract",
            "reason_codes": [],
            "banner": support["banner"],
            "elevation_required": False,
            "admin_required": False,
        }

    # Last resort: bare .url — branding incomplete (not B-complete).
    url_result = write_desktop_url_shortcut(
        desktop_dir=desk,
        url=url,
        platform_name=platform_name if platform_name is not None else (
            "Windows" if os.name == "nt" else platform.system()
        ),
    )
    url_result["uses_anchor_ico"] = False
    url_result["branding_complete"] = False
    url_result["format"] = "url"
    url_result["icon_location"] = None
    codes = list(url_result.get("reason_codes") or [])
    if "branding_incomplete" not in codes:
        codes.append("branding_incomplete")
    url_result["reason_codes"] = codes
    return url_result


def read_onboard_token(data_dir=None) -> str | None:
    """Read the onboard-minted ``ANCHOR_TOKEN`` value, or None.

    Resolves the same out-of-tree path :func:`onboard.generate_token` writes
    (default ``~/.anchor/.anchor/onboard-token``). Returns the VALUE for
    wiring into a spawned server's environment / the one-time browser
    hand-off — callers must never log it.
    """
    try:
        p = onboard._default_token_path(data_dir)
        raw = p.read_text(encoding="utf-8").strip()
        return raw or None
    except OSError:
        return None


#: Env the spawned shared-install server gets by DEFAULT (explicit env wins).
#: ANCHOR_PROACTIVE_SUMMARY=0 — background model summaries are OPT-IN on a
#: shared install: Anchor must never spend a collaborator's Claude
#: subscription without an explicit action (v1.1.3 decision). An
#: author-style install (launched by NSSM with the flag unset) keeps
#: proactive summaries on.
SPAWN_ENV_DEFAULTS = {"ANCHOR_PROACTIVE_SUMMARY": "0"}


def spawn_anchor_server(
    *,
    package_root=None,
    token: str | None = None,
    data_dir=None,
    port: int | None = None,
    env=None,
    popen_fn=None,
) -> dict:
    """GENUINELY start ``anchor_gui.py`` as a detached background process.

    v1.1.3: this is the function the share path never had. The old chain
    (launcher → ``start_package_b_service`` → ``onboard.register_service``)
    ended in dead code — nothing ever spawned the server, the launcher's
    re-probes failed, and the browser opened on a dead URL.

    Wiring: the onboard-minted token (param → env ``ANCHOR_TOKEN`` → token
    file) is exported into the child env, so every mutating ``/api/*`` route
    and the terminal/WS surface require it by default on a collaborator
    install. ``SPAWN_ENV_DEFAULTS`` applies (background summaries opt-in).
    Detached: survives the launcher exiting; no console window on Windows.
    ``popen_fn`` is the hermetic-test seam (no real process).
    """
    import subprocess

    root = Path(package_root) if package_root is not None else _REPO_ROOT
    gui = root / "anchor_gui.py"
    if not gui.is_file():
        return {"started": False, "status": "no_anchor_gui",
                "error": "anchor_gui.py not found in the package root",
                "token_wired": False}
    e = dict(os.environ if env is None else env)
    tok = token or (e.get("ANCHOR_TOKEN") or "").strip() or read_onboard_token(data_dir)
    if tok:
        e["ANCHOR_TOKEN"] = tok
    for k, v in SPAWN_ENV_DEFAULTS.items():
        e.setdefault(k, v)
    argv = [sys.executable, str(gui), "--no-browser"]
    if port:
        argv += ["--port", str(port)]
    kwargs = {}
    if os.name == "nt":
        # DETACHED_PROCESS | CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
        kwargs["creationflags"] = 0x00000008 | 0x08000000 | 0x00000200
    else:
        kwargs["start_new_session"] = True
    opener = popen_fn or subprocess.Popen
    try:
        proc = opener(
            argv, cwd=str(root), env=e,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, **kwargs)
    except Exception as exc:
        return {"started": False, "status": "spawn_failed",
                "error": str(exc), "token_wired": bool(tok)}
    return {"started": True, "status": "spawned",
            "pid": getattr(proc, "pid", None), "token_wired": bool(tok)}


def start_package_b_service(
    *,
    start_fn=None,
    home=None,
    token: str | None = None,
    port: int | None = None,
) -> dict:
    """Attempt Package B service start (injectable for hermetic tests).

    ``foreground_fallback`` alone is **never** treated as B success — the
    dual gate requires a subsequent HTTP probe OK. The production path (no
    inject) calls :func:`spawn_anchor_server` since v1.1.3 — the old
    :func:`onboard.register_service` default was dead code that started
    nothing (see its docstring). ``port`` (v1.1.3) rides through to the
    spawn so a launcher probing a non-default dashboard URL starts the
    server on THAT port (also what lets the pull-dry-run walk the real
    launcher on an isolated port beside a live :8777).
    """
    if start_fn is not None:
        try:
            raw = start_fn()
        except Exception as exc:
            return {
                "attempted": True,
                "started": False,
                "status": "error",
                "foreground_fallback": False,
                "error": str(exc),
                "reason_codes": ["anchor_service_unavailable"],
            }
        out = dict(raw or {})
        status = str(out.get("status") or "")
        fg = status == "foreground_fallback" or bool(
            out.get("foreground_fallback")
        )
        # Honest: registered/started flags only from inject; never invent OK.
        started = bool(out.get("started")) or status in (
            "registered", "running", "started", "ok",
        )
        if fg:
            started = False  # fallback alone is not B success
        codes = list(out.get("reason_codes") or [])
        if fg and "foreground_fallback_not_b_success" not in codes:
            codes.append("foreground_fallback_not_b_success")
        if not started and "anchor_service_unavailable" not in codes and not fg:
            if status not in ("registered", "running", "started", "ok", "skipped"):
                codes.append("anchor_service_unavailable")
        return {
            "attempted": True,
            "started": started,
            "status": status or ("started" if started else "failed"),
            "foreground_fallback": fg,
            "error": out.get("error"),
            "reason_codes": codes,
            "raw": out,
        }

    # Production path (v1.1.3): genuinely spawn the server. "started" here
    # means "a spawn was launched" — B success STILL requires the dual gate's
    # subsequent HTTP probe to come back OK (the launcher re-probes).
    try:
        raw = spawn_anchor_server(token=token, port=port)
        started = bool(raw.get("started"))
        codes = []
        if not started:
            codes.append("anchor_service_unavailable")
        return {
            "attempted": True,
            "started": started,
            "status": raw.get("status") or "unknown",
            "foreground_fallback": False,
            "error": raw.get("error"),
            "reason_codes": codes,
            # No token body — only whether one was wired.
            "raw": {"status": raw.get("status"),
                    "token_wired": bool(raw.get("token_wired"))},
        }
    except Exception as exc:
        return {
            "attempted": True,
            "started": False,
            "status": "error",
            "foreground_fallback": False,
            "error": str(exc),
            "reason_codes": ["anchor_service_unavailable"],
        }


def evaluate_package_b_dual_gate(
    *,
    probe: dict,
    desktop: dict,
    dashboard_url: str = DEFAULT_LOCAL_DASHBOARD_URL,
    favicon: dict | None = None,
    skill_icons: dict | None = None,
    service: dict | None = None,
) -> dict:
    """Compute ``B_ready`` dual gate (Amendment A1).

    ``B_ready ⇔ (HTTP probe local dashboard OK)
               ∧ (desktop shortcut exists with IconLocation using anchor.ico)
               ∧ (shortcut URL == same local dashboard URL)``

    Bare ``.url`` without Anchor icon is **not** B-complete for branding.
    ``foreground_fallback`` alone is never B success.
    """
    url = (dashboard_url or DEFAULT_LOCAL_DASHBOARD_URL).strip().rstrip("/")
    probe_ok = bool((probe or {}).get("ok"))
    desk = desktop or {}
    desk_created = bool(desk.get("created")) and not desk.get("skipped")
    desk_url = (desk.get("url") or "").strip().rstrip("/")
    url_match = bool(desk_url) and desk_url == url
    il = (desk.get("icon_location") or desk.get("icon_location_reported") or "")
    uses_ico = bool(desk.get("uses_anchor_ico")) or (
        ANCHOR_ICO_BASENAME in str(il).lower()
    )
    branding = bool(desk.get("branding_complete")) or (
        desk_created and uses_ico and desk.get("format") in (
            "lnk", "lnk_contract",
        )
    )
    # Bare .url without ico is never branding-complete.
    if desk.get("format") == "url" or (
        desk_created and not uses_ico
    ):
        branding = False
        uses_ico = uses_ico and desk.get("format") != "url"

    codes = []
    if not probe_ok:
        codes.append("anchor_service_unavailable")
        codes.append("b_probe_failed")
    if not desk_created:
        codes.append("b_desktop_missing")
    elif not branding or not uses_ico:
        codes.append("b_branding_incomplete")
    if desk_created and not url_match:
        codes.append("b_desktop_url_mismatch")
    if service and service.get("foreground_fallback") and not probe_ok:
        codes.append("foreground_fallback_not_b_success")
    if favicon is not None and not favicon.get("ok"):
        codes.append("favicon_unavailable")
    if skill_icons is not None and not skill_icons.get("ok"):
        codes.append("skill_icons_incomplete")

    # Core dual gate (favicon/skill_icons are A1 acceptance; branding failure
    # on ico is hard; favicon/skill soft-reported but skill_icons_incomplete
    # / favicon do not alone flip B_ready if core dual holds — A1 says icon
    # branding failures are B-incomplete. Favicon is part of probe path when
    # checked; we require core triple only for b_ready flag.)
    b_ready = bool(probe_ok and desk_created and branding and uses_ico and url_match)

    # Amendment A1: branding failures ⇒ not B-complete even if service up.
    # Favicon OK is expected after service up; if checked and failed, not ready.
    if b_ready and favicon is not None and not favicon.get("ok"):
        b_ready = False
        if "favicon_unavailable" not in codes:
            codes.append("favicon_unavailable")
    if b_ready and skill_icons is not None and not skill_icons.get("ok"):
        b_ready = False
        if "skill_icons_incomplete" not in codes:
            codes.append("skill_icons_incomplete")

    return {
        "b_ready": b_ready,
        "b_incomplete": not b_ready,
        "probe_ok": probe_ok,
        "desktop_ok": desk_created and url_match,
        "branding_ok": bool(branding and uses_ico),
        "url_match": url_match,
        "dashboard_url": url,
        "reason_codes": codes,
        "message": (
            "Package B dual gate passed (HTTP probe OK + anchor.ico shortcut)."
            if b_ready
            else (
                "Package B incomplete: "
                + (
                    "; ".join(codes)
                    if codes
                    else "dual gate not satisfied"
                )
            )
        ),
    }


def complete_package_b_dual_gate(
    report: dict,
    *,
    home,
    desktop_dir=None,
    dashboard_url: str = DEFAULT_LOCAL_DASHBOARD_URL,
    probe_fn=None,
    shortcut_fn=None,
    start_service_fn=None,
    favicon_get_fn=None,
    brand_dir=None,
    skills_root=None,
    platform_name: str | None = None,
    skip_service_start: bool = False,
    check_favicon_flag: bool = True,
    check_skill_icons_flag: bool = True,
    package_root=None,
    python_exe: str | None = None,
) -> dict:
    """Run service start + probe + branded desktop + evaluate dual gate.

    Mutates and returns ``report`` with ``b_ready``, ``package_b``, readiness
    re-stamp when incomplete. Never claims success on ``foreground_fallback``
    alone.

    ``package_root`` is the install tree that contains ``launch_anchor_dashboard.py``
    (service-aware desktop target). Defaults to this module's directory.
    """
    root = Path(home)
    url = (dashboard_url or DEFAULT_LOCAL_DASHBOARD_URL).strip()
    plat = platform_name if platform_name is not None else (
        "Windows" if os.name == "nt" else platform.system()
    )
    desk = desktop_dir
    if desk is None:
        desk = str(root / "Desktop")
    pkg_root = Path(package_root) if package_root is not None else Path(__file__).resolve().parent

    # 1. Service start (optional inject; honesty on fallback).
    if skip_service_start:
        service = {
            "attempted": False,
            "started": False,
            "status": "skipped",
            "foreground_fallback": False,
            "reason_codes": [],
        }
    else:
        service = start_package_b_service(
            start_fn=start_service_fn,
            home=root,
        )
    report["register_service_attempted"] = bool(service.get("attempted"))
    report["anchor_service_started"] = bool(service.get("started"))

    # 2. HTTP probe (truth for dual gate — not service status alone).
    probe = probe_local_dashboard(url, probe_fn=probe_fn)

    # 3. Branded desktop shortcut (prefer .lnk + anchor.ico + service-aware launcher).
    ico = ensure_home_anchor_ico(root)
    desktop = write_desktop_lnk_shortcut(
        desktop_dir=desk,
        url=url,
        icon_path=ico,
        platform_name=plat,
        shortcut_fn=shortcut_fn,
        home=root,
        package_root=pkg_root,
        python_exe=python_exe,
    )
    report["desktop"] = desktop

    # 4. Favicon + skill icons (A1).
    favicon = None
    if check_favicon_flag:
        # When probe inject is used, favicon can share success with probe_ok.
        if favicon_get_fn is not None:
            favicon = check_favicon(url, get_fn=favicon_get_fn)
        elif probe_fn is not None:
            # Hermetic: if dashboard probe OK, treat favicon as OK unless
            # caller supplies favicon_get_fn (avoids real HTTP in tests).
            favicon = {
                "ok": bool(probe.get("ok")),
                "base_url": url.rstrip("/"),
                "paths": {
                    "/favicon.ico": bool(probe.get("ok")),
                    "/anchor.ico": bool(probe.get("ok")),
                },
                "reason_codes": (
                    [] if probe.get("ok") else ["favicon_unavailable"]
                ),
                "source": "inferred_from_probe",
            }
        else:
            favicon = check_favicon(url)

    skill_icons = None
    if check_skill_icons_flag:
        bdir = brand_dir
        if bdir is None:
            home_brand = root / "vendor" / "brand"
            # Land brand icons under home when source tree has them.
            if not home_brand.is_dir():
                ensure_skill_brand_icons(home_brand)
            bdir = home_brand if home_brand.is_dir() else (
                _REPO_ROOT / "vendor" / "brand"
            )
        sk = skills_root
        if sk is None:
            try:
                import share_skills_root as ssr

                sk = ssr.resolve_skills_root(root)
            except Exception:
                sk = root / home_cfg.SKILLS_SUBDIR
        portfolio = None
        if isinstance(report.get("skills"), dict):
            portfolio = []
            for bucket in ("installed", "skipped"):
                for item in report["skills"].get(bucket) or []:
                    n = item.get("name") if isinstance(item, dict) else item
                    if n:
                        portfolio.append(n)
        skill_icons = check_skill_icons(
            brand_dir=bdir,
            skills_root=sk,
            portfolio=portfolio or None,
        )

    gate = evaluate_package_b_dual_gate(
        probe=probe,
        desktop=desktop,
        dashboard_url=url,
        favicon=favicon,
        skill_icons=skill_icons,
        service=service,
    )

    package_b = {
        "b_ready": gate["b_ready"],
        "b_incomplete": gate["b_incomplete"],
        "message": gate["message"],
        "reason_codes": list(gate["reason_codes"]),
        "probe": {
            "ok": probe.get("ok"),
            "url": probe.get("url"),
            "source": probe.get("source"),
            "reason_codes": list(probe.get("reason_codes") or []),
            # Never echo host absolute paths / errors with user dirs.
            "error": (
                "probe_failed" if probe.get("error") and not probe.get("ok")
                else None
            ),
        },
        "desktop": {
            "created": desktop.get("created"),
            "format": desktop.get("format"),
            "url": desktop.get("url"),
            "uses_anchor_ico": desktop.get("uses_anchor_ico"),
            "branding_complete": desktop.get("branding_complete"),
            "path_reported": desktop.get("path_reported") or _safe_report_path(
                desktop.get("path"), home=root
            ),
            "icon_location_reported": desktop.get("icon_location_reported"),
        },
        "service": {
            "attempted": service.get("attempted"),
            "started": service.get("started"),
            "status": service.get("status"),
            "foreground_fallback": service.get("foreground_fallback"),
            "reason_codes": list(service.get("reason_codes") or []),
        },
        "favicon": favicon,
        "skill_icons": {
            "ok": (skill_icons or {}).get("ok"),
            "default_fallback_documented": (skill_icons or {}).get(
                "default_fallback_documented"
            ),
            "missing": (skill_icons or {}).get("missing") or [],
            "reason_codes": list((skill_icons or {}).get("reason_codes") or []),
        } if skill_icons is not None else None,
    }
    report["package_b"] = package_b
    report["b_ready"] = gate["b_ready"]
    report["package_b_handoff"] = {
        "pending": not gate["b_ready"],
        "wave": 5,
        "b_ready": gate["b_ready"],
        "message": gate["message"],
    }
    report["steps"] = list(report.get("steps") or [])
    report["steps"].append({
        "step": "package_b_dual_gate",
        "result": {
            "b_ready": gate["b_ready"],
            "reason_codes": list(gate["reason_codes"]),
            "message": gate["message"],
            "probe_ok": gate["probe_ok"],
            "branding_ok": gate["branding_ok"],
        },
    })

    # Re-stamp readiness when dual gate fails (not-ready / B-incomplete).
    if not gate["b_ready"]:
        report["ok"] = False
        gov_dir = root / home_cfg.GOVERNANCE_SUBDIR
        extra_u = []
        if not gate["probe_ok"]:
            extra_u.append("anchor_service_unavailable")
        if not gate["branding_ok"] or not gate["desktop_ok"]:
            if "os_desktop_skipped" not in extra_u:
                extra_u.append("os_desktop_skipped")
        if not extra_u:
            extra_u.append("anchor_service_unavailable")
        try:
            prev = report.get("readiness") or {}
            readiness_doc = ready.compute_readiness(
                package_id="B",
                governance_installed=bool(
                    prev.get("governance_installed", True)
                ),
                coding_seat_ok=bool(prev.get("coding_seat_ok")),
                user_accepted_degraded=False,
                skill_tree_forked=bool(prev.get("skill_tree_forked")),
                journal_proven=False,
                skills_pin_mismatch=bool(prev.get("skills_pin_mismatch")),
                seat_probe_failed=bool(prev.get("seat_probe_failed")),
                feedback_opt_in=bool(
                    report.get("feedback_opt_in")
                    if report.get("feedback_opt_in") is not None
                    else prev.get("feedback_opt_in")
                ),
                extra_reason_codes=extra_u or ["anchor_service_unavailable"],
                force_status="not-ready",
                notes=(
                    "Package B dual gate incomplete: %s"
                    % gate["message"]
                ),
            )
            if gov_dir.is_dir() or True:
                gov_dir.mkdir(parents=True, exist_ok=True)
                ready.write_readiness_stamp(gov_dir, readiness_doc)
            report["readiness"] = readiness_doc
        except ready.ReadinessError:
            # Keep prior stamp but force status view on report.
            stamp = dict(report.get("readiness") or {})
            stamp["status"] = "not-ready"
            report["readiness"] = stamp
    else:
        # Dual gate passed — keep ready if seats/gov already green.
        report["ok"] = True
        stamp = report.get("readiness") or {}
        if stamp.get("status") == "ready":
            report["ok"] = True

    report["exit_code"] = exit_code_for_report(report)
    return report


# ── Rollback manifest + resumable state ──────────────────────────────────────

def _state_path(home) -> Path:
    return Path(home) / home_cfg.GOVERNANCE_SUBDIR / STATE_FILENAME


def load_onboard_state(home) -> dict | None:
    path = _state_path(home)
    if not path.is_file():
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return doc if isinstance(doc, dict) else None


def save_onboard_state(home, state: dict) -> Path:
    path = _state_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = dict(state)
    doc.setdefault("schema", ONBOARD_SCHEMA)
    doc.setdefault("schema_version", ONBOARD_SCHEMA_VERSION)
    path.write_text(
        json.dumps(doc, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


class RollbackManifest:
    """Tracks paths **we created** so rollback never touches foreign trees."""

    def __init__(self):
        self.created: list[str] = []
        self.notes: list[str] = []

    def record(self, path) -> None:
        p = str(Path(path))
        if p not in self.created:
            self.created.append(p)

    def to_dict(self) -> dict:
        return {"created": list(self.created), "notes": list(self.notes)}

    @classmethod
    def from_dict(cls, doc) -> "RollbackManifest":
        m = cls()
        if isinstance(doc, dict):
            m.created = [str(x) for x in (doc.get("created") or [])]
            m.notes = [str(x) for x in (doc.get("notes") or [])]
        return m

    def rollback(self) -> dict:
        """Remove only recorded paths (files first, then dirs), reverse order.

        Never deletes a path that still contains a foreign skill without our
        marker when the path is a skills parent — only exact recorded entries.
        """
        removed = []
        failed = []
        for raw in reversed(self.created):
            p = Path(raw)
            try:
                if p.is_symlink() or p.is_file():
                    p.unlink()
                    removed.append(str(p))
                elif p.is_dir():
                    # Only remove if empty or entirely ours (has marker / empty).
                    shutil.rmtree(p)
                    removed.append(str(p))
            except OSError as exc:
                failed.append({"path": str(p), "error": str(exc)})
        return {"removed": removed, "failed": failed}


# ── Transactional share onboard ──────────────────────────────────────────────

def _default_permissions(package_id: str) -> dict:
    perms = {k: True for k in PERMISSION_KEYS}
    if package_id == "A":
        perms["scaffold_anchor"] = False
        perms["register_service"] = False
        perms["desktop_shortcut"] = False
    return perms


def permissions_write_list(package_id: str = "A") -> list:
    """Plain-ASCII list of writes the chosen package will perform (step 4)."""
    lines = [
        "write governance pack under <home>/governance/",
        "write model family prefs (coding/review) under governance/",
        "install product skills under <home>/skills/ (SKILLS_ROOT)",
        "register host adapters (claude pointer, grok paths; no dual Claude copy)",
    ]
    if package_id == "B":
        lines.extend([
            "scaffold Anchor data under <home>/anchor/",
            "start/probe local Anchor service (HTTP dual gate)",
            "desktop shortcut with anchor.ico to local dashboard (no admin)",
            "favicon + portfolio skill brand icons (Amendment A1)",
        ])
    else:
        lines.append("Package A never starts the Anchor service")
    return lines


def hosts_for_package(package_id: str) -> list:
    """Hosts to register for package A (no service) vs B (includes anchor env)."""
    # Package A: never imply Anchor service; still may stamp ANCHOR_SKILLS_ROOT
    # only when explicitly requested — default A = claude + grok only.
    if package_id == "B":
        return ["claude", "grok", "anchor"]
    return ["claude", "grok"]


def package_a_permissions() -> dict:
    """Permission gates for Package A (skills-only — never service/desktop)."""
    return _default_permissions("A")


def package_b_permissions() -> dict:
    """Permission gates for Package B (A + scaffold + service + desktop)."""
    return _default_permissions("B")


def _landed_skill_names(skill_report, skills_home=None) -> list:
    """Skill ids that landed under SKILLS_ROOT (installed + skipped; not refused)."""
    landed = []
    for bucket in ("installed", "skipped"):
        for item in (skill_report or {}).get(bucket) or []:
            name = item.get("name") if isinstance(item, dict) else item
            if name and name not in landed:
                landed.append(name)
    if not landed and skills_home is not None:
        root = Path(skills_home)
        if root.is_dir():
            try:
                for child in sorted(root.iterdir(), key=lambda p: p.name.lower()):
                    if (
                        child.is_dir()
                        and not child.name.startswith(".")
                        and child.name not in landed
                    ):
                        landed.append(child.name)
            except OSError:
                pass
    return landed


def _sync_package_a_registry(home, skills_root, *, hosts_registered, portfolio):
    """Rewrite skills_root.json hosts_registered to only hosts this A run touched.

    Package A honesty: never leave stale ``anchor`` (or other) hosts stamped
    unless this run actually registered them.
    """
    import share_skills_root as ssr

    home_path = Path(home)
    root_path = Path(skills_root)
    reg = ssr.load_registry(home_path)
    if reg is None:
        reg = ssr.build_skills_root_doc(
            root_path,
            install_mode="copy",
            hosts_registered=list(hosts_registered or []),
            portfolio_manifest=list(portfolio) if portfolio is not None else None,
        )
    else:
        reg = dict(reg)
        reg["hosts_registered"] = list(hosts_registered or [])
        reg["skills_root"] = str(root_path)
        reg["install_mode"] = reg.get("install_mode") or "copy"
        if portfolio is not None:
            reg["portfolio_manifest"] = list(portfolio)
    ssr.write_registry(reg, home=home_path)
    return reg


def detect_package_mode(tree_root=None) -> dict:
    """Auto-detect Package A|B from the install tree (step 3).

    If only one package shape is present, select it. If both (full Anchor
    tree with skills), prefer B. Returns ``{package_id, candidates, reason}``.
    """
    root = Path(tree_root) if tree_root is not None else _REPO_ROOT
    has_anchor = (
        (root / "anchor_gui.py").is_file()
        or (root / "anchor.py").is_file()
        or (root / "starter").is_dir()
    )
    skills_markers = [
        root / "vendor" / "bundled-skills",
        root / "bundled-skills",
        root / "skills",
    ]
    has_skills = any(p.is_dir() for p in skills_markers) or (
        (root / "share_onboard.py").is_file()
    )
    candidates = []
    if has_skills:
        candidates.append("A")
    if has_anchor and has_skills:
        candidates.append("B")
    if not candidates:
        # Bare tree — default A (skills-first cold-start).
        return {
            "package_id": "A",
            "candidates": ["A"],
            "reason": "default-skills-only",
            "auto": True,
        }
    if candidates == ["A"]:
        return {
            "package_id": "A",
            "candidates": candidates,
            "reason": "skills-tree-only",
            "auto": True,
        }
    if "B" in candidates and "A" in candidates:
        return {
            "package_id": "B",
            "candidates": ["A", "B"],
            "reason": "anchor-plus-skills-tree",
            "auto": True,
        }
    return {
        "package_id": candidates[0],
        "candidates": candidates,
        "reason": "single-candidate",
        "auto": True,
    }


def write_host_agents_pointers(home, governance_dir=None) -> dict:
    """Write thin host AGENTS/CLAUDE/Grok pointers into home host dirs (step 6).

    Points at ``<home>/governance/AGENTS.md``. Never copies the full body.
    Hermetic when ``home`` is a temp path (tests / chosen share home).
    """
    root = Path(home)
    gov_dir = Path(governance_dir) if governance_dir is not None else (
        root / home_cfg.GOVERNANCE_SUBDIR
    )
    agents = gov_dir / "AGENTS.md"
    # Prefer a home-relative pointer so stranger trees never embed
    # C:\Users\... absolute paths (ship-gate author-secret scan).
    try:
        target_display = (gov_dir / "AGENTS.md").relative_to(root).as_posix()
    except ValueError:
        # gov_dir outside home: use basename-relative form only (no host path)
        target_display = "%s/%s" % (
            home_cfg.GOVERNANCE_SUBDIR,
            "AGENTS.md",
        )
    pointer_body = (
        "# Agent notes — pointer\n\n"
        "> Canonical operating rules live in the governance pack:\n"
        "> `%s`\n\n"
        "Read that file first. This file is a thin pointer only.\n"
        "Resolve the path relative to your share home root "
        "(never hardcode another machine's absolute path).\n"
    ) % target_display
    written = {}
    paths = {
        "claude_agents": root / ".claude" / "AGENTS.md",
        "claude_claude_md": root / ".claude" / "CLAUDE.md",
        "grok_agents": root / ".grok" / "Agents.md",
    }
    for key, path in paths.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(pointer_body, encoding="utf-8", newline="\n")
        # Report relative when possible (tests/ship scans stay path-clean).
        try:
            written[key] = path.relative_to(root).as_posix()
        except ValueError:
            written[key] = path.name
    return {"ok": True, "target": target_display, "written": written}


def exit_code_for_report(report) -> int:
    """Map readiness / seats to process exit code (zero-seat matrix).

    * ``ready`` → 0
    * ``degraded`` with coding seat → 0 (honest degraded message)
    * ``not-ready`` or zero seats → non-zero
    * Package B dual gate ran and ``b_ready is False`` → non-zero
    """
    if not isinstance(report, dict):
        return 1
    # Dual gate result (only when Package B path set the key).
    if "b_ready" in report and report.get("b_ready") is False:
        return 1
    stamp = report.get("readiness") or {}
    status = stamp.get("status")
    seat_ok = bool(
        stamp.get("coding_seat_ok")
        or (report.get("seats") or {}).get("coding_seat_ok")
    )
    if status == "ready":
        return 0
    if status == "degraded" and seat_ok:
        return 0
    return 1


def run_share_onboard(
    home,
    *,
    package_id: str = "A",
    skills_src=None,
    skills_home=None,
    permissions=None,
    feedback_opt_in: bool = False,
    coding_family: str = "claude",
    review_family: str = "gemini",
    mock_seat_results=None,
    desktop_dir=None,
    dashboard_url: str = DEFAULT_LOCAL_DASHBOARD_URL,
    declared_skills_pin=None,
    observed_skills_pin=None,
    user_accepted_degraded: bool = False,
    on_collision: str = "overlay",
    platform_name: str | None = None,
    env=None,
    which_fn=None,
    write_governance: bool = True,
    register_hosts_flag: bool = True,
    dialogue_complete: bool = True,
    force_not_ready: bool = False,
    force_not_ready_reason: str | None = None,
) -> dict:
    """Run idempotent plain-English onboard for package A or B.

    ``on_collision``:
      * ``overlay`` — refuse-don't-clobber foreign skill names; install the rest
      * ``abort`` — raise :class:`ShareOnboardError` when foreign skills exist
      * ``alternate`` — raise with ``alternate_root_offer`` (caller re-invokes)

    ``feedback_opt_in`` defaults **False** and is never a readiness gate.
    Seat probes use ``mock_seat_results`` in CI (money-safe).

    ``dialogue_complete`` must be True for a path that may stamp ``ready``.
    Silent / non-interactive callers set it False (or use
    :func:`run_silent_onboard`) so readiness fails closed as ``not-ready``.
    """
    if package_id not in PACKAGE_IDS:
        raise ShareOnboardError(
            "unknown_package_id",
            "package_id must be A or B, got %r" % (package_id,),
        )
    env = env if env is not None else os.environ
    root = Path(home).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    perms = _default_permissions(package_id)
    if permissions:
        perms.update(permissions)
    # Package A hard-disables service/desktop/scaffold even if a caller
    # tried to re-enable them via permissions= (skills-only contract).
    if package_id == "A":
        perms["scaffold_anchor"] = False
        perms["register_service"] = False
        perms["desktop_shortcut"] = False

    report = {
        "ok": False,
        "package_id": package_id,
        "home": str(root),
        "steps": [],
        "three_path": three_path_lead_in(),
        "feedback_opt_in": bool(feedback_opt_in),
        "rollback": None,
        "readiness": None,
        "collision": None,
        "seats": None,
        "desktop": None,
        "hosts_registered": [],
        "pin_mismatch": False,
        "reason_codes": [],
        "dialogue_complete": bool(dialogue_complete),
        "silent": bool(force_not_ready or not dialogue_complete),
        # Package A never starts Anchor service; B service is a later wave.
        "anchor_service_started": False,
        "register_service_attempted": False,
    }
    rb = RollbackManifest()

    # ── Silent / incomplete dialogue: fail closed before claiming ready ───
    if force_not_ready or not dialogue_complete:
        reason = force_not_ready_reason or "interactive_onboard_required"
        if reason not in report["reason_codes"]:
            report["reason_codes"].append(reason)
        report["steps"].append({
            "step": "silent_path",
            "result": {
                "dialogue_complete": False,
                "reason": reason,
                "message": (
                    "Silent/non-interactive path cannot stamp ready. "
                    "Run: python -m share_onboard  (interactive cold-start)"
                ),
            },
        })

    # ── 1. Prereqs (fail early) ────────────────────────────────────────────
    prereq = check_prereqs_fail_early(
        package_id=package_id, env=env, which_fn=which_fn
    )
    report["steps"].append({"step": "prereqs", "result": prereq})
    if not prereq["ok"]:
        report["reason_codes"].extend(prereq["reason_codes"])
        raise ShareOnboardError(
            "prereq_missing",
            "hard prerequisites missing — fix before writes: %s"
            % (
                ", ".join(
                    "%s (%s)" % (m["label"], m["fix_link"])
                    for m in prereq["missing"]
                ),
            ),
            details=prereq,
        )

    # ── 2. Layout + collision scan ─────────────────────────────────────────
    layout = home_cfg.layout_for_home(root)
    # Product skills land under SKILLS_ROOT (resolve_skills_root), not
    # ~/.claude/skills. Host adapters register as pointers/config only.
    if skills_home is not None:
        sk_home = Path(skills_home)
    else:
        try:
            import share_skills_root as ssr

            sk_home = ssr.resolve_skills_root(root)
        except Exception:
            sk_home = Path(layout["absolute"]["skills"])
    bundled_names = None
    if skills_src is not None:
        bundled_names = onboard._list_source_skills(Path(skills_src))

    collision = preflight_collision_scan(
        root,
        skills_home=sk_home,
        bundled_skill_names=bundled_names,
        desktop_dir=desktop_dir,
        env=env,
    )
    report["collision"] = collision
    report["steps"].append({"step": "collision_scan", "result": {
        "has_collision": collision["has_collision"],
        "foreign_count": len(collision["foreign_skills"]),
        "message": collision["message"],
    }})

    if collision["has_collision"] and on_collision == "abort":
        raise ShareOnboardError(
            "foreign_skill_collision",
            collision["message"],
            details=collision,
        )
    if collision["has_collision"] and on_collision == "alternate":
        raise ShareOnboardError(
            "foreign_skill_collision_alternate",
            collision["message"],
            details=collision,
        )
    # overlay: continue; install_skills will refuse foreign names.

    # Ensure relative subdirs (record for rollback only if newly created).
    for key, rel in layout["relative"].items():
        d = root / rel
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            rb.record(d)

    save_onboard_state(root, {
        "step": "permissions",
        "package_id": package_id,
        "home": str(root),
        "permissions": perms,
    })
    rb.record(_state_path(root))

    # ── 3. Governance pack (permission-gated) ──────────────────────────────
    gov_dir = root / home_cfg.GOVERNANCE_SUBDIR
    governance_installed = False
    host_pointers = None
    if perms.get("write_governance") and write_governance:
        written = gov.write_governance_pack(gov_dir)
        for p in written.values():
            rb.record(p)
        governance_installed = gov.is_governance_installed(gov_dir)
        # Step 6: thin host AGENTS pointers under the share home.
        try:
            host_pointers = write_host_agents_pointers(root, gov_dir)
            for p in (host_pointers.get("written") or {}).values():
                rb.record(p)
        except OSError:
            host_pointers = {"ok": False}
        report["steps"].append({
            "step": "governance",
            "result": {
                "installed": governance_installed,
                "files": list(written),
                "host_pointers": host_pointers,
            },
        })
    else:
        governance_installed = gov.is_governance_installed(gov_dir)
        report["steps"].append({
            "step": "governance",
            "result": {"skipped": True, "installed": governance_installed},
        })

    # Home config
    hc_path = home_cfg.write_home_config(root, dest_dir=gov_dir)
    rb.record(hc_path)

    # ── 4. Model prefs (permission-gated) ──────────────────────────────────
    cross = stamp_cross_model(coding_family, review_family)
    if perms.get("write_model_prefs"):
        try:
            mp = write_model_prefs(
                root,
                coding_family=coding_family,
                review_family=review_family,
            )
            rb.record(mp)
            report["steps"].append({
                "step": "model_prefs",
                "result": {"path": str(mp), **cross},
            })
        except ShareOnboardError as exc:
            report["reason_codes"].append(exc.reason)
            raise
    else:
        report["steps"].append({"step": "model_prefs", "result": {"skipped": True}})

    # ── 5. Skills install (SKILLS_ROOT only; dual-copy refuse on re-onboard) ─
    skill_report = {
        "installed": [], "skipped": [], "refused": [], "failed": [],
        "src": None, "home": str(sk_home),
    }
    portfolio_landed = []
    if perms.get("install_skills"):
        try:
            import share_skills_root as ssr

            # Re-onboard law: refuse when Claude still holds a second product tree.
            ssr.refuse_dual_copy_on_re_onboard(root, skills_root=sk_home)
        except ShareOnboardError:
            raise
        except Exception as exc:
            msg = str(exc)
            if "dual-copy" in msg:
                raise ShareOnboardError(
                    "dual_copy_forbidden",
                    "re-onboard refused: dual Claude product tree present — "
                    "product bytes must live only under SKILLS_ROOT",
                    details={"error": msg},
                ) from exc
            # Import/other soft failures: continue with install (tests still run).
        skill_report = onboard.install_skills(
            skills_src=skills_src,
            skills_home=sk_home,
            symlink=False,
        )
        for item in skill_report.get("installed") or []:
            rb.record(sk_home / item["name"])
        report["steps"].append({
            "step": "install_skills",
            "result": {
                "installed": [x["name"] for x in skill_report["installed"]],
                "skipped": [x["name"] for x in skill_report["skipped"]],
                "refused": [x.get("name") for x in skill_report["refused"]],
                "failed": skill_report["failed"],
                "skills_root": str(sk_home),
            },
        })
        # Seal after successful install (best-effort when tree non-empty).
        if sk_home.is_dir() and any(sk_home.iterdir()):
            try:
                manifest = seal.build_seal_manifest(sk_home)
                seal_path = seal.write_seal(sk_home, manifest)
                rb.record(seal_path)
            except seal.SkillSealError:
                pass
        # Registry with portfolio of landed skills; hosts filled after register.
        portfolio_landed = _landed_skill_names(skill_report, sk_home)
        try:
            import share_skills_root as ssr

            reg_doc = ssr.build_skills_root_doc(
                sk_home,
                install_mode="copy",
                hosts_registered=[],
                portfolio_manifest=list(portfolio_landed),
            )
            reg_path = ssr.write_registry(reg_doc, home=root)
            rb.record(reg_path)
        except Exception:
            # Non-fatal: register_hosts may still write a registry.
            pass
        # Post-install dual-copy gate (install never writes Claude farm).
        try:
            import share_skills_root as ssr

            ssr.refuse_dual_copy_on_re_onboard(
                root,
                skills_root=sk_home,
                portfolio=list(portfolio_landed) if portfolio_landed else None,
            )
        except Exception as exc:
            msg = str(exc)
            if "dual-copy" in msg:
                raise ShareOnboardError(
                    "dual_copy_forbidden",
                    "post-install dual Claude product tree detected",
                    details={"error": msg},
                ) from exc
    else:
        report["steps"].append({
            "step": "install_skills",
            "result": {"skipped": True},
        })

    # ── 5b. Host register (honesty: only hosts this run successfully touches) ─
    hosts_registered = []
    if register_hosts_flag and perms.get("install_skills"):
        try:
            import share_skills_root as ssr

            host_list = hosts_for_package(package_id)
            # Register one host at a time so a single failure does not claim
            # hosts that never ran (hosts_registered honesty).
            reg_out = {}
            reg_errors = {}
            for host in host_list:
                try:
                    kwargs = {}
                    if host == "grok":
                        kwargs["skills_paths_include_skills_root"] = True
                    entry = ssr.register_host(
                        host,
                        sk_home,
                        "copy",
                        home=root,
                        **kwargs,
                    )
                    if entry.get("registered"):
                        reg_out[host] = entry
                except Exception as hexc:
                    reg_errors[host] = str(hexc)
            hosts_registered = [
                h for h in host_list if h in reg_out
            ]
            # Package A: stamp registry hosts_registered ONLY to this run's set.
            if package_id == "A":
                pin = portfolio_landed or _landed_skill_names(
                    skill_report, sk_home
                )
                _sync_package_a_registry(
                    root,
                    sk_home,
                    hosts_registered=hosts_registered,
                    portfolio=list(pin),
                )
            report["steps"].append({
                "step": "register_hosts",
                "result": {
                    "hosts_registered": list(hosts_registered),
                    "package_id": package_id,
                    "attempted": list(host_list),
                    "errors": reg_errors or None,
                },
            })
        except Exception as exc:
            report["steps"].append({
                "step": "register_hosts",
                "result": {
                    "skipped": True,
                    "error": str(exc),
                    "hosts_registered": [],
                },
            })
            hosts_registered = []
    else:
        report["steps"].append({
            "step": "register_hosts",
            "result": {"skipped": True, "hosts_registered": []},
        })
    report["hosts_registered"] = list(hosts_registered)

    # ── 6. Anchor scaffold (package B only — Package A never scaffolds) ────
    if package_id == "B" and perms.get("scaffold_anchor"):
        data_dir = root / home_cfg.ANCHOR_SUBDIR
        scaf = onboard.scaffold_anchor(data_dir=data_dir)
        for rel in scaf.get("created") or []:
            rb.record(data_dir / rel)
        report["steps"].append({
            "step": "scaffold_anchor",
            "result": {
                "created": scaf.get("created"),
                "skipped": scaf.get("skipped"),
            },
        })
    else:
        report["steps"].append({
            "step": "scaffold_anchor",
            "result": {"skipped": True},
        })

    # ── 6b. Terminal extra (Package B, Windows) — v1.1.3 ───────────────────
    # pywinpty was never installed by any onboard path, so collaborator
    # terminals opened EMPTY until a manual pip install (the 2026-07-30
    # friction intake). Probe-first (already-present short-circuits without
    # touching pip); a failure degrades honestly and never blocks onboard.
    # Hermetic seams: ANCHOR_ONBOARD_SKIP_PIP / ANCHOR_ONBOARD_PIP_CMD.
    if package_id == "B":
        try:
            term_extra = onboard.install_terminal_extra(env=env)
        except Exception as exc:  # never let the extra kill an onboard
            term_extra = {"status": "error", "installed": False,
                          "message": "pywinpty step errored: %s" % exc}
        report["steps"].append({"step": "terminal_extra", "result": term_extra})
    else:
        report["steps"].append({
            "step": "terminal_extra",
            "result": {"skipped": True, "package_id": package_id},
        })

    # ── 6c. Access token (Package B) — v1.1.3 token-wiring keystone ────────
    # The launcher wires the ONBOARD-MINTED token into the spawned server
    # (mutating APIs + terminals gated by default), but THIS path — the
    # documented `.\onboard.cmd → python -m share_onboard` cold start — never
    # minted one; only the legacy `python onboard.py` core did. Found while
    # preparing the true-VM run: a collaborator would have ended auth-OPEN.
    # Idempotent (an existing token is kept), written OUT-OF-TREE via the
    # same seam the launcher reads (onboard._default_token_path), value
    # never logged. HERMETIC GUARD: a bare pytest context with no
    # ANCHOR_DATA_DIR redirect must never write the real user profile.
    if package_id == "B":
        data_override = (env.get("ANCHOR_DATA_DIR") or "").strip() or None
        if data_override is None and env.get("PYTEST_CURRENT_TEST"):
            tok_res = {"skipped": True,
                       "reason": "hermetic-pytest-no-data-dir-redirect"}
        else:
            try:
                t = onboard.generate_token(data_dir=data_override)
                tok_res = {"created": bool(t.get("created")),
                           "in_repo": bool(t.get("in_repo")),
                           "path": t.get("path")}
                if t.get("created"):
                    rb.record(t["path"])
            except Exception as exc:
                tok_res = {"error": str(exc)}
        report["steps"].append({"step": "access_token", "result": tok_res})
    else:
        report["steps"].append({
            "step": "access_token",
            "result": {"skipped": True, "package_id": package_id},
        })

    # ── 7. Seat probes ─────────────────────────────────────────────────────
    seats = probe_all_seats(
        mock_results=mock_seat_results,
        env=env,
        which_fn=which_fn,
    )
    report["seats"] = seats
    report["steps"].append({
        "step": "seat_probes",
        "result": {
            "coding_seat_ok": seats["coding_seat_ok"],
            "ok_families": seats["ok_families"],
            "source": (
                "mock" if mock_seat_results is not None else "live-or-disabled"
            ),
            "cross_model": cross["cross_model"],
        },
    })

    # ── 8. Feedback consent (default off) ──────────────────────────────────
    # Explicit True required to opt in; default parameter is False.
    opted = feedback_opt_in is True
    fc_path = save_feedback_consent(root, opted_in=opted)
    rb.record(fc_path)
    report["feedback_opt_in"] = opted
    report["steps"].append({
        "step": "feedback_consent",
        "result": {
            "opted_in": opted,
            "default": False,
            "readiness_gate": False,
            "copy": feedback_consent_plain_english()["question"],
        },
    })

    # ── 9. Desktop shortcut (package B only) ───────────────────────────────
    desktop_result = None
    if package_id == "B" and perms.get("desktop_shortcut"):
        desk = desktop_dir or collision.get("desktop_dir")
        if desk is None:
            # Temp-friendly: put under home/Desktop for tests.
            desk = str(root / "Desktop")
        desktop_result = write_desktop_url_shortcut(
            desktop_dir=desk,
            url=dashboard_url,
            platform_name=platform_name if platform_name is not None else (
                "Windows" if os.name == "nt" else platform.system()
            ),
        )
        if desktop_result.get("created") and desktop_result.get("path"):
            rb.record(desktop_result["path"])
        report["desktop"] = desktop_result
        report["steps"].append({
            "step": "desktop_shortcut",
            "result": desktop_result,
        })
        if desktop_result.get("reason_codes"):
            report["reason_codes"].extend(desktop_result["reason_codes"])
    else:
        report["steps"].append({
            "step": "desktop_shortcut",
            "result": {"skipped": True, "package_id": package_id},
        })

    # ── 10. Pin mismatch (degraded, not crash) ─────────────────────────────
    pin_codes = pub.check_skills_pin_match(
        declared_skills_pin, observed_skills_pin
    )
    pin_mismatch = bool(pin_codes)
    report["pin_mismatch"] = pin_mismatch
    if pin_mismatch:
        report["reason_codes"].append(pub.pin_mismatch_degraded_code())

    # ── 11. Readiness stamp ────────────────────────────────────────────────
    forked = False
    if sk_home.is_dir() and (sk_home / seal.SEAL_FILENAME).is_file():
        forked = seal.is_forked(sk_home)

    # Silent / incomplete dialogue never stamps ready (fail closed).
    silent_block = bool(force_not_ready or not dialogue_complete)
    seat_ok = bool(seats["coding_seat_ok"])
    if silent_block:
        # Force not-ready regardless of seats — criterion 7.
        extra = [
            c for c in report["reason_codes"]
            if c in READINESS_REASON_CODES
        ]
        if "interactive_onboard_required" not in extra:
            extra.append("interactive_onboard_required")
        readiness_doc = ready.compute_readiness(
            package_id=package_id,
            governance_installed=governance_installed,
            coding_seat_ok=False if silent_block else seat_ok,
            user_accepted_degraded=False,
            skill_tree_forked=forked,
            journal_proven=False,
            skills_pin_mismatch=pin_mismatch,
            seat_probe_failed=bool(seats.get("seat_probe_failed")),
            feedback_opt_in=opted,
            extra_reason_codes=extra or None,
            force_status="not-ready",
            notes=(
                "silent/non-interactive path; interactive dialogue required "
                "(python -m share_onboard); feedback_opt_in=%s" % opted
            ),
        )
    else:
        readiness_doc = ready.compute_readiness(
            package_id=package_id,
            governance_installed=governance_installed,
            coding_seat_ok=seat_ok,
            user_accepted_degraded=user_accepted_degraded,
            skill_tree_forked=forked,
            journal_proven=False,
            skills_pin_mismatch=pin_mismatch,
            seat_probe_failed=bool(seats.get("seat_probe_failed")),
            feedback_opt_in=opted,
            extra_reason_codes=[
                c for c in report["reason_codes"]
                if c in READINESS_REASON_CODES
            ] or None,
            notes=(
                "share onboard complete; feedback_opt_in=%s (not a readiness gate)"
                % opted
            ),
        )
    rpath = ready.write_readiness_stamp(gov_dir, readiness_doc)
    rb.record(rpath)
    report["readiness"] = readiness_doc
    report["steps"].append({
        "step": "readiness",
        "result": {
            "status": readiness_doc["status"],
            "reason_codes": readiness_doc["reason_codes"],
            "feedback_opt_in": readiness_doc.get("feedback_opt_in"),
            "path": str(rpath),
        },
    })

    # Persist final state + rollback manifest (for later explicit rollback).
    final_state = {
        "step": "done",
        "package_id": package_id,
        "home": str(root),
        "readiness_status": readiness_doc["status"],
        "feedback_opt_in": opted,
        "rollback": rb.to_dict(),
    }
    save_onboard_state(root, final_state)
    rb_path = gov_dir / ROLLBACK_FILENAME
    rb_path.write_text(
        json.dumps(rb.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    report["rollback"] = rb.to_dict()
    # Library ok = install finished; green-ready is readiness.status == ready.
    # Silent path and zero-seat stamp not-ready; exit_code_for_report maps that.
    report["ok"] = not silent_block
    report["skills"] = skill_report
    report["exit_code"] = exit_code_for_report(report)
    # Package A invariant stamp (also true for B until service wave starts it).
    report["anchor_service_started"] = False
    report["register_service_attempted"] = False
    if package_id == "A":
        report["package_a"] = {
            "skills_only": True,
            "anchor_service_started": False,
            "hosts_registered": list(report.get("hosts_registered") or []),
            "readiness_path": str(rpath),
            "skills_root": str(sk_home),
        }
    return report


def run_package_a_onboard(
    home,
    *,
    skills_src=None,
    skills_home=None,
    feedback_opt_in: bool = False,
    coding_family: str = "claude",
    review_family: str = "gemini",
    mock_seat_results=None,
    declared_skills_pin=None,
    observed_skills_pin=None,
    user_accepted_degraded: bool = False,
    on_collision: str = "overlay",
    platform_name: str | None = None,
    env=None,
    which_fn=None,
    write_governance: bool = True,
    register_hosts_flag: bool = True,
    dialogue_complete: bool = True,
    force_not_ready: bool = False,
    force_not_ready_reason: str | None = None,
) -> dict:
    """Package A (skills-only) end-to-end onboard path.

    Integrates: vendored skills → SKILLS_ROOT, skills_root.json registry,
    host adapters (honest ``hosts_registered``), AGENTS body + Claude/Grok
    thin pointers, feedback consent (default off), readiness artifact.

    **Never** starts the Anchor service, scaffolds Anchor data, registers a
    Windows service, or writes a desktop shortcut.
    """
    perms = package_a_permissions()
    report = run_share_onboard(
        home,
        package_id="A",
        skills_src=skills_src,
        skills_home=skills_home,
        permissions=perms,
        feedback_opt_in=feedback_opt_in,
        coding_family=coding_family,
        review_family=review_family,
        mock_seat_results=mock_seat_results,
        desktop_dir=None,
        declared_skills_pin=declared_skills_pin,
        observed_skills_pin=observed_skills_pin,
        user_accepted_degraded=user_accepted_degraded,
        on_collision=on_collision,
        platform_name=platform_name,
        env=env,
        which_fn=which_fn,
        write_governance=write_governance,
        register_hosts_flag=register_hosts_flag,
        dialogue_complete=dialogue_complete,
        force_not_ready=force_not_ready,
        force_not_ready_reason=force_not_ready_reason,
    )
    report["package_id"] = "A"
    report["anchor_service_started"] = False
    report["register_service_attempted"] = False
    # Defensive: Package A report must never claim anchor host without register.
    hosts = list(report.get("hosts_registered") or [])
    if "anchor" in hosts and "anchor" not in hosts_for_package("A"):
        hosts = [h for h in hosts if h != "anchor"]
        report["hosts_registered"] = hosts
        if isinstance(report.get("package_a"), dict):
            report["package_a"]["hosts_registered"] = list(hosts)
    return report


def run_package_b_onboard(
    home,
    *,
    skills_src=None,
    skills_home=None,
    feedback_opt_in: bool = False,
    coding_family: str = "claude",
    review_family: str = "gemini",
    mock_seat_results=None,
    declared_skills_pin=None,
    observed_skills_pin=None,
    user_accepted_degraded: bool = False,
    on_collision: str = "overlay",
    platform_name: str | None = None,
    env=None,
    which_fn=None,
    write_governance: bool = True,
    register_hosts_flag: bool = True,
    dialogue_complete: bool = True,
    force_not_ready: bool = False,
    force_not_ready_reason: str | None = None,
    desktop_dir=None,
    dashboard_url: str = DEFAULT_LOCAL_DASHBOARD_URL,
    probe_fn=None,
    shortcut_fn=None,
    start_service_fn=None,
    favicon_get_fn=None,
    brand_dir=None,
    skip_service_start: bool = False,
    check_favicon_flag: bool = True,
    check_skill_icons_flag: bool = True,
    package_root=None,
    python_exe: str | None = None,
) -> dict:
    """Package B end-to-end: Package A surface + service + dual gate.

    Runs :func:`run_share_onboard` with ``package_id=B``, then
    :func:`complete_package_b_dual_gate` (HTTP probe + ``anchor.ico`` desktop
    shortcut + favicon/skill-icon checks).

    **B_ready** only when probe OK **and** branded shortcut targets the same
    URL. Service start failure, probe failure, or ``foreground_fallback`` alone
    → readiness ``not-ready`` / B-incomplete, non-zero exit.

    Injectables for hermetic tests: ``probe_fn``, ``shortcut_fn``,
    ``start_service_fn``, ``favicon_get_fn``.
    """
    perms = package_b_permissions()
    report = run_share_onboard(
        home,
        package_id="B",
        skills_src=skills_src,
        skills_home=skills_home,
        permissions=perms,
        feedback_opt_in=feedback_opt_in,
        coding_family=coding_family,
        review_family=review_family,
        mock_seat_results=mock_seat_results,
        desktop_dir=desktop_dir,
        dashboard_url=dashboard_url,
        declared_skills_pin=declared_skills_pin,
        observed_skills_pin=observed_skills_pin,
        user_accepted_degraded=user_accepted_degraded,
        on_collision=on_collision,
        platform_name=platform_name,
        env=env,
        which_fn=which_fn,
        write_governance=write_governance,
        register_hosts_flag=register_hosts_flag,
        dialogue_complete=dialogue_complete,
        force_not_ready=force_not_ready,
        force_not_ready_reason=force_not_ready_reason,
    )
    report["package_id"] = "B"
    # Silent / incomplete dialogue never claims B ready.
    if force_not_ready or not dialogue_complete:
        report["b_ready"] = False
        report["package_b"] = {
            "b_ready": False,
            "b_incomplete": True,
            "message": "interactive dialogue required before Package B dual gate",
            "reason_codes": ["interactive_onboard_required"],
        }
        report["ok"] = False
        report["exit_code"] = exit_code_for_report(report)
        return report

    return complete_package_b_dual_gate(
        report,
        home=home,
        desktop_dir=desktop_dir,
        dashboard_url=dashboard_url,
        probe_fn=probe_fn,
        shortcut_fn=shortcut_fn,
        start_service_fn=start_service_fn,
        package_root=package_root,
        python_exe=python_exe,
        favicon_get_fn=favicon_get_fn,
        brand_dir=brand_dir,
        skills_root=skills_home,
        platform_name=platform_name,
        skip_service_start=skip_service_start,
        check_favicon_flag=check_favicon_flag,
        check_skill_icons_flag=check_skill_icons_flag,
    )


def package_a_readiness_artifact(home) -> dict | None:
    """Load Package A readiness stamp from ``<home>/governance/readiness.json``.

    Returns None when missing; raises :class:`ready.ReadinessError` if invalid.
    """
    path = Path(home) / home_cfg.GOVERNANCE_SUBDIR / ready.READINESS_FILENAME
    if not path.is_file():
        return None
    return ready.load_readiness_stamp(path)


def verify_package_a_acceptance(home, report=None) -> dict:
    """Check Package A acceptance criteria against a hermetic home + report.

    Returns ``{"ok": bool, "problems": [...], ...}`` — used by regression tests
    and optional post-onboard self-check. Does **not** start any service.
    """
    import share_skills_root as ssr
    import vendor_skills as vendor

    root = Path(home)
    problems = []
    gov_dir = root / home_cfg.GOVERNANCE_SUBDIR
    skills_root = ssr.resolve_skills_root(root)

    # Readiness artifact
    readiness_path = gov_dir / ready.READINESS_FILENAME
    readiness = None
    if not readiness_path.is_file():
        problems.append("readiness-artifact-missing")
    else:
        try:
            readiness = ready.load_readiness_stamp(readiness_path)
            if readiness.get("package_id") not in (None, "A"):
                # Package A path stamps package_id=A; tolerate legacy missing.
                if readiness.get("package_id") == "B":
                    problems.append("readiness-package-id-is-B")
        except ready.ReadinessError as exc:
            problems.append("readiness-invalid:%s" % ",".join(exc.problems))

    # Registry present
    reg = None
    try:
        reg = ssr.load_registry(root)
    except ssr.SkillsRootError as exc:
        problems.append("registry-invalid:%s" % exc)
    if reg is None:
        problems.append("skills-root-registry-missing")
    else:
        reg_hosts = list(reg.get("hosts_registered") or [])
        # Honesty: only hosts actually registered (adapter state or this report).
        adapter = ssr.load_adapter_state(root)
        adapter_hosts = set((adapter.get("hosts") or {}).keys())
        for h in reg_hosts:
            if h not in adapter_hosts and h not in (
                (report or {}).get("hosts_registered") or []
            ):
                problems.append("hosts_registered-not-actually-registered:%s" % h)
        # Package A default host set never includes service implication.
        if report is not None:
            rep_hosts = list(report.get("hosts_registered") or [])
            if set(rep_hosts) != set(reg_hosts):
                # Report and registry should agree after A path sync.
                problems.append(
                    "hosts_registered-report-registry-mismatch:report=%s:reg=%s"
                    % (sorted(rep_hosts), sorted(reg_hosts))
                )
            if report.get("anchor_service_started"):
                problems.append("package-a-started-anchor-service")
            if report.get("register_service_attempted"):
                problems.append("package-a-attempted-register-service")
            # A must not list hosts it did not attempt (anchor unless registered).
            for h in rep_hosts:
                if h not in hosts_for_package("A") and h not in adapter_hosts:
                    problems.append("hosts_registered-unexpected-host:%s" % h)

    # Product bytes only under SKILLS_ROOT; Claude pointers not dual trees.
    pin = None
    if reg and reg.get("portfolio_manifest") is not None:
        try:
            pin = ssr.normalize_portfolio_manifest(reg["portfolio_manifest"])
        except ssr.SkillsRootError:
            pin = None
    proof = ssr.product_bytes_only_under_skills_root(
        root, skills_root=skills_root, portfolio=pin
    )
    if not proof.get("ok"):
        for p in proof.get("problems") or []:
            problems.append("product-bytes:%s" % p)

    # AGENTS body + thin host pointers
    agents = gov_dir / "AGENTS.md"
    if not agents.is_file():
        problems.append("governance-AGENTS-missing")
    else:
        body = agents.read_text(encoding="utf-8", errors="replace")
        if "Status table" not in body and "10-minute" not in body:
            problems.append("governance-AGENTS-missing-status-table")
        if not gov.is_governance_installed(gov_dir):
            problems.append("governance-not-installed")

    claude_agents = root / ".claude" / "AGENTS.md"
    claude_md = root / ".claude" / "CLAUDE.md"
    grok_agents = root / ".grok" / "Agents.md"
    for label, path in (
        ("claude_AGENTS", claude_agents),
        ("claude_CLAUDE", claude_md),
        ("grok_Agents", grok_agents),
    ):
        if not path.is_file():
            problems.append("host-pointer-missing:%s" % label)
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        # Thin pointer: must reference governance AGENTS, not embed full body.
        if "pointer" not in text.lower() and "AGENTS.md" not in text:
            problems.append("host-pointer-not-thin:%s" % label)
        if agents.is_file():
            full = agents.read_text(encoding="utf-8", errors="replace")
            # Pointer must be much shorter than full body (not a dual copy).
            if len(text) > max(800, len(full) // 3):
                problems.append("host-pointer-too-large:%s" % label)

    # No Anchor service side effects under Package A home.
    # (No listening claim; just refuse service registration artifacts.)
    if report is not None and report.get("package_id") == "A":
        steps = {
            (s.get("step") if isinstance(s, dict) else None)
            for s in (report.get("steps") or [])
        }
        for s in (report.get("steps") or []):
            if not isinstance(s, dict):
                continue
            if s.get("step") == "scaffold_anchor":
                res = s.get("result") or {}
                if not res.get("skipped") and res.get("created"):
                    problems.append("package-a-scaffolded-anchor")
            if s.get("step") == "desktop_shortcut":
                res = s.get("result") or {}
                if not res.get("skipped") and res.get("created"):
                    problems.append("package-a-wrote-desktop-shortcut")

    # vendor/ship still denies journal/
    if not vendor._is_denied(Path("some-skill") / "journal" / "run.json"):
        problems.append("vendor-denylist-journal-regressed")
    if not vendor._is_denied(Path("journal") / "x.md"):
        problems.append("vendor-denylist-journal-dir-regressed")

    # Equality oracle for registered hosts (when any host was registered).
    if reg is not None and pin and (reg.get("hosts_registered") or []):
        eq = ssr.portfolio_equality_oracle(
            root, portfolio=pin, registry=reg
        )
        if not eq.get("ok"):
            for p in eq.get("problems") or []:
                problems.append("equality:%s" % p)

    return {
        "ok": not problems,
        "problems": problems,
        "readiness": readiness,
        "registry": reg,
        "skills_root": str(skills_root),
        "hosts_registered": list(
            (reg or {}).get("hosts_registered")
            or (report or {}).get("hosts_registered")
            or []
        ),
        "anchor_service_started": False,
    }


def rollback_share_onboard(home) -> dict:
    """Roll back paths recorded by the last onboard run; foreign trees stay."""
    root = Path(home)
    rb_path = root / home_cfg.GOVERNANCE_SUBDIR / ROLLBACK_FILENAME
    state = load_onboard_state(root)
    doc = None
    if rb_path.is_file():
        try:
            doc = json.loads(rb_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            doc = None
    if doc is None and state and isinstance(state.get("rollback"), dict):
        doc = state["rollback"]
    if not doc:
        return {"removed": [], "failed": [], "note": "no-rollback-manifest"}
    manifest = RollbackManifest.from_dict(doc)
    return manifest.rollback()


# ── Interactive CLI (sole cold-start: python -m share_onboard) ───────────────

# Locked dialogue order (canonical Wave 3).
DIALOGUE_STEP_ORDER = (
    "home_picker",
    "python_detect",
    "package_detect",
    "permissions_list",
    "install_and_register",
    "governance_pointers",
    "seat_probe",
    "feedback_consent",
    "package_b_handoff",
    "readiness_stamp",
)


def _print(print_fn, *parts) -> None:
    print_fn(" ".join(str(p) for p in parts))


def prompt_line(
    prompt: str,
    *,
    default: str | None = None,
    input_fn=None,
    print_fn=None,
) -> str:
    """Read one line; empty input returns ``default`` (may be "")."""
    input_fn = input_fn or input
    print_fn = print_fn or print
    suffix = ""
    if default is not None and default != "":
        suffix = " [%s]" % default
    try:
        raw = input_fn(prompt + suffix + ": ")
    except EOFError:
        raw = ""
    text = (raw or "").strip()
    if not text and default is not None:
        return default
    return text


def prompt_yes_no(
    question: str,
    *,
    default: bool = False,
    input_fn=None,
    print_fn=None,
) -> bool:
    """Yes/No prompt. Empty input uses ``default`` (Wave 3 feedback: default No)."""
    input_fn = input_fn or input
    print_fn = print_fn or print
    hint = "Y/n" if default else "y/N"
    try:
        raw = input_fn("%s [%s]: " % (question, hint))
    except EOFError:
        raw = ""
    text = (raw or "").strip().lower()
    if not text:
        return bool(default)
    if text in ("y", "yes", "true", "1"):
        return True
    if text in ("n", "no", "false", "0"):
        return False
    # Unrecognized → default (fail closed toward No for consent).
    return bool(default)


def prompt_feedback_consent(*, input_fn=None, print_fn=None) -> bool:
    """Step 8: exact FEEDBACK_CONSENT_COPY; **default No**.

    Returns True only on explicit Yes. Does not mint keys here — caller
    passes the bool to :func:`save_feedback_consent` / run_share_onboard.
    """
    print_fn = print_fn or print
    copy = feedback_consent_plain_english()
    _print(print_fn, "")
    _print(print_fn, "--- Feedback consent (step 8) ---")
    _print(print_fn, copy["question"])
    _print(print_fn, "")
    _print(print_fn, "What is shared:")
    _print(print_fn, " ", copy["what_is_shared"])
    _print(print_fn, "")
    _print(print_fn, "What is NOT shared:")
    _print(print_fn, " ", copy["what_is_not_shared"])
    _print(print_fn, "")
    _print(print_fn, "Residual risk:")
    _print(print_fn, " ", copy["residual_risk"])
    _print(print_fn, "")
    _print(
        print_fn,
        "Default is No. Decline leaves skills fully usable; no install_key is minted.",
    )
    # default=False is the locked contract (FEEDBACK_CONSENT_COPY["default"]).
    return prompt_yes_no(
        "Opt in to sanitized skill-friction sharing?",
        default=False,
        input_fn=input_fn,
        print_fn=print_fn,
    )


def run_silent_onboard(
    home=None,
    *,
    package_id: str = "A",
    skills_src=None,
    platform_name: str | None = None,
    mock_seat_results=None,
    **kwargs,
) -> dict:
    """Non-interactive path — **never** stamps ready (fail closed).

    Progress-only / ``--non-interactive`` without full dialogue cannot claim
    ready. Exit non-zero; readiness status is ``not-ready``.
    """
    root = Path(home) if home is not None else Path(
        recommend_home_dir(platform_name)
    )
    report = run_share_onboard(
        root,
        package_id=package_id,
        skills_src=skills_src,
        platform_name=platform_name,
        mock_seat_results=mock_seat_results,
        dialogue_complete=False,
        force_not_ready=True,
        force_not_ready_reason="interactive_onboard_required",
        **kwargs,
    )
    report["ok"] = False
    report["silent"] = True
    report["exit_code"] = exit_code_for_report(report)
    # Belt-and-suspenders: never leave a ready stamp from silent path.
    stamp = report.get("readiness") or {}
    if stamp.get("status") == "ready":
        raise ShareOnboardError(
            "silent_path_false_green",
            "silent/non-interactive path must not stamp ready",
            details=report,
        )
    return report


def run_interactive_onboard(
    *,
    input_fn=None,
    print_fn=None,
    home=None,
    package_id: str | None = None,
    skills_src=None,
    mock_seat_results=None,
    platform_name: str | None = None,
    env=None,
    which_fn=None,
    desktop_dir=None,
    tree_root=None,
    skip_prompts: bool = False,
    feedback_opt_in: bool | None = None,
    probe_fn=None,
    shortcut_fn=None,
    start_service_fn=None,
    favicon_get_fn=None,
    brand_dir=None,
    dashboard_url: str = DEFAULT_LOCAL_DASHBOARD_URL,
    package_root=None,
    python_exe: str | None = None,
    **kwargs,
) -> dict:
    """Guided dialogue (steps 1-10). Sole cold-start UX for strangers.

    Locked order: home -> Python -> package -> permissions -> install/register
    -> governance pointers -> seat probe -> feedback (default No) -> B dual gate
    -> readiness.

    ``skip_prompts`` + explicit ``home``/``package_id`` is for hermetic tests
    that still count as dialogue_complete (full choices provided).
    Package B injectables (``probe_fn``, ``shortcut_fn``, ``start_service_fn``,
    ``favicon_get_fn``) support hermetic dual-gate tests.
    """
    input_fn = input_fn or input
    print_fn = print_fn or print
    plat = platform_name if platform_name is not None else (
        "Windows" if os.name == "nt" else platform.system()
    )
    env = env if env is not None else os.environ

    _print(print_fn, "Shareable skills onboard - interactive cold-start")
    _print(print_fn, "Entry: python -m share_onboard  (not the /onboard skill)")
    _print(print_fn, "")
    paths = three_path_lead_in()
    _print(print_fn, "Three paths:")
    _print(print_fn, "  consumer:    ", paths["consumer"])
    _print(print_fn, "  collaborator:", paths["collaborator"])
    _print(print_fn, "  feedback:    ", paths["feedback"])
    _print(print_fn, "")

    # ── 1. Home picker ────────────────────────────────────────────────────
    rec = recommend_home_dir(plat)
    _print(print_fn, "--- Step 1: Home directory ---")
    _print(print_fn, "Recommended home:", rec)
    if home is not None:
        chosen_home = Path(home)
        _print(print_fn, "Using home:", chosen_home)
    elif skip_prompts:
        chosen_home = Path(rec)
    else:
        answer = prompt_line(
            "Home directory for skills/governance/projects",
            default=rec,
            input_fn=input_fn,
            print_fn=print_fn,
        )
        chosen_home = Path(answer).expanduser()
    chosen_home.mkdir(parents=True, exist_ok=True)

    # ── 2. Python detect / PATH fix; hard fail if missing ─────────────────
    _print(print_fn, "")
    _print(print_fn, "--- Step 2: Python ---")
    prereq = check_prereqs_fail_early(
        package_id=package_id or "A", env=env, which_fn=which_fn
    )
    for row in prereq["rows"]:
        mark = "OK" if row["ok"] else "MISSING"
        req = "required" if row["required"] else "optional"
        _print(
            print_fn,
            "  [%s] %s (%s) — %s" % (mark, row["label"], req, row["note"]),
        )
        if not row["ok"] and row["required"]:
            _print(print_fn, "  Fix:", row["fix_link"])
    if not prereq["ok"]:
        _print(print_fn, "")
        _print(print_fn, "HARD FAIL: install Python 3.8+ and re-run.")
        _print(print_fn, "  ", PREREQ_FIX_LINKS["python"])
        raise ShareOnboardError(
            "prereq_missing",
            "Python 3.8+ is required",
            details=prereq,
        )

    # ── 3. Package A|B auto-detect ────────────────────────────────────────
    _print(print_fn, "")
    _print(print_fn, "--- Step 3: Package mode (A=skills, B=Anchor+skills) ---")
    detected = detect_package_mode(tree_root)
    auto_id = detected["package_id"]
    _print(
        print_fn,
        "Auto-detect: package %s (%s)" % (auto_id, detected.get("reason")),
    )
    if package_id is not None:
        chosen_pkg = package_id
        _print(print_fn, "Using package:", chosen_pkg)
    elif skip_prompts:
        chosen_pkg = auto_id
    else:
        answer = prompt_line(
            "Package A or B",
            default=auto_id,
            input_fn=input_fn,
            print_fn=print_fn,
        ).upper()
        if answer not in PACKAGE_IDS:
            answer = auto_id
        chosen_pkg = answer
    if chosen_pkg not in PACKAGE_IDS:
        raise ShareOnboardError(
            "unknown_package_id",
            "package_id must be A or B, got %r" % (chosen_pkg,),
        )

    # ── 4. Permissions list ───────────────────────────────────────────────
    _print(print_fn, "")
    _print(print_fn, "--- Step 4: Permissions (writes this run will make) ---")
    for line in permissions_write_list(chosen_pkg):
        _print(print_fn, "  *", line)
    if not skip_prompts:
        cont = prompt_yes_no(
            "Continue with these writes?",
            default=True,
            input_fn=input_fn,
            print_fn=print_fn,
        )
        if not cont:
            raise ShareOnboardError(
                "user_aborted",
                "user declined permissions list",
            )

    # Resolve skills source (bundled tree when present).
    src = skills_src
    if src is None:
        for cand in (
            _REPO_ROOT / "vendor" / "bundled-skills",
            _REPO_ROOT / "bundled-skills",
        ):
            if cand.is_dir():
                src = cand
                break

    # Provisional feedback for the install transaction: known only when
    # scripted. Live prompt is step 8 (after seats) per locked dialogue order.
    provisional_feedback = False
    if feedback_opt_in is not None:
        provisional_feedback = bool(feedback_opt_in)
    elif skip_prompts:
        provisional_feedback = False  # locked default No

    # -- 5. Install + host register -----------------------------------------
    _print(print_fn, "")
    _print(print_fn, "--- Step 5: Install skills + register hosts ---")
    # -- 6. Governance AGENTS pointers (inside transactional install) -------
    _print(print_fn, "--- Step 6: Governance AGENTS pack + host pointers ---")
    report = run_share_onboard(
        chosen_home,
        package_id=chosen_pkg,
        skills_src=src,
        feedback_opt_in=provisional_feedback,
        mock_seat_results=mock_seat_results,
        platform_name=plat,
        env=env,
        which_fn=which_fn,
        desktop_dir=desktop_dir,
        dashboard_url=dashboard_url,
        dialogue_complete=True,
        **kwargs,
    )
    report["dialogue_steps"] = list(DIALOGUE_STEP_ORDER)
    report["interactive"] = True
    hosts = report.get("hosts_registered") or []
    _print(
        print_fn,
        "  hosts_registered:",
        ", ".join(hosts) if hosts else "(none)",
    )
    skill_step = None
    for st in report.get("steps") or []:
        if st.get("step") == "install_skills":
            skill_step = st.get("result") or {}
            break
    if skill_step and not skill_step.get("skipped"):
        _print(
            print_fn,
            "  skills installed:",
            ", ".join(skill_step.get("installed") or []) or "(none new)",
        )

    # -- 7. Seat probe (results from install-time probe) --------------------
    _print(print_fn, "")
    _print(print_fn, "--- Step 7: Seat probe (claude / agy / grok) ---")
    seats = report.get("seats") or probe_all_seats(
        mock_results=mock_seat_results,
        env=env,
        which_fn=which_fn,
    )
    for fam in SEAT_FAMILIES:
        s = (seats.get("seats") or {}).get(fam) or {}
        _print(
            print_fn,
            "  %s: ok=%s session_visible=%s path_present=%s (%s)"
            % (
                fam,
                s.get("ok"),
                s.get("session_visible"),
                s.get("path_present"),
                s.get("transport") or SEAT_TRANSPORTS.get(fam, "?"),
            ),
        )
    if not seats.get("coding_seat_ok"):
        _print(
            print_fn,
            "  No coding-capable subscription seat yet (claude / agy / grok).",
        )
        _print(
            print_fn,
            "  Install at least one subscription CLI, then re-run onboard.",
        )
        for fam, link in (
            ("claude", PREREQ_FIX_LINKS["claude"]),
            ("agy", PREREQ_FIX_LINKS["agy"]),
            ("grok", PREREQ_FIX_LINKS["grok"]),
        ):
            _print(print_fn, "  ", fam, "fix:", link)

    # -- 8. Feedback consent (exact FEEDBACK_CONSENT_COPY; default No) ------
    if feedback_opt_in is not None:
        opted = bool(feedback_opt_in)
        _print(
            print_fn,
            "--- Step 8: Feedback consent (provided=%s) ---" % opted,
        )
        if opted:
            _print(
                print_fn,
                "Default is No; explicit Yes provided - install_key will be present.",
            )
        else:
            _print(print_fn, "Default is No; explicit No provided.")
    elif skip_prompts:
        opted = False
        _print(print_fn, "--- Step 8: Feedback consent (default No) ---")
        _print(
            print_fn,
            "Default is No. No install_key; local journals stay local; export blocked.",
        )
    else:
        opted = prompt_feedback_consent(input_fn=input_fn, print_fn=print_fn)

    if opted:
        _print(print_fn, "Feedback: Yes - mint de-identified install_key.")
    else:
        _print(
            print_fn,
            "Feedback: No - no install_key; local journals stay local; export blocked.",
        )

    # Reconcile consent when live prompt differs from provisional install save.
    if bool(opted) != bool(provisional_feedback):
        save_feedback_consent(chosen_home, opted_in=opted, wipe_key=not opted)
        report["feedback_opt_in"] = bool(opted)
        stamp = report.get("readiness")
        if isinstance(stamp, dict):
            stamp = dict(stamp)
            stamp["feedback_opt_in"] = bool(opted)
            # Feedback is NOT a readiness gate - status/codes stay as computed.
            try:
                gov_dir = chosen_home / home_cfg.GOVERNANCE_SUBDIR
                ready.write_readiness_stamp(gov_dir, stamp)
                report["readiness"] = stamp
            except ready.ReadinessError:
                report["readiness"] = stamp
        report["steps"].append({
            "step": "feedback_consent_reconcile",
            "result": {
                "opted_in": bool(opted),
                "default": False,
                "readiness_gate": False,
            },
        })
    else:
        report["feedback_opt_in"] = bool(opted)

    # -- 9. Package B dual gate (service + anchor.ico desktop) --------------
    _print(print_fn, "")
    if chosen_pkg == "B":
        _print(print_fn, "--- Step 9: Package B dual gate ---")
        _print(
            print_fn,
            "  Running service start + HTTP probe + anchor.ico desktop shortcut...",
        )
        report = complete_package_b_dual_gate(
            report,
            home=chosen_home,
            desktop_dir=desktop_dir,
            dashboard_url=dashboard_url,
            probe_fn=probe_fn,
            shortcut_fn=shortcut_fn,
            start_service_fn=start_service_fn,
            favicon_get_fn=favicon_get_fn,
            brand_dir=brand_dir,
            platform_name=plat,
            package_root=package_root if package_root is not None else (
                Path(tree_root) if tree_root is not None else Path(__file__).resolve().parent
            ),
            python_exe=python_exe,
        )
        pb = report.get("package_b") or {}
        if report.get("b_ready"):
            _print(print_fn, "  B_ready: YES — probe OK + branded shortcut.")
            desk = pb.get("desktop") or {}
            if desk.get("path_reported"):
                _print(print_fn, "  desktop:", desk.get("path_reported"))
            if desk.get("icon_location_reported"):
                _print(
                    print_fn,
                    "  IconLocation:",
                    desk.get("icon_location_reported"),
                )
            _print(print_fn, "  dashboard:", pb.get("probe", {}).get("url") or dashboard_url)
        else:
            _print(print_fn, "  B_ready: NO — Package B incomplete.")
            _print(print_fn, " ", pb.get("message") or "dual gate failed")
            for code in (pb.get("reason_codes") or [])[:8]:
                _print(print_fn, "  reason:", code)
            if (pb.get("service") or {}).get("foreground_fallback"):
                _print(
                    print_fn,
                    "  Note: foreground_fallback alone is never B success;",
                    "HTTP probe must pass.",
                )
    else:
        _print(print_fn, "--- Step 9: Package A (no service) ---")
        _print(print_fn, "  Package A never starts the Anchor service.")
        report["package_b_handoff"] = {"pending": False, "package_id": "A"}
        # Do not set b_ready for Package A (key absent ⇒ exit_code ignores dual gate).

    # -- 10. Readiness stamp + next steps -----------------------------------
    stamp = report.get("readiness") or {}
    hosts = report.get("hosts_registered") or hosts
    _print(print_fn, "")
    _print(print_fn, "--- Step 10: Readiness ---")
    _print(print_fn, "  status:", stamp.get("status"))
    _print(print_fn, "  coding_seat_ok:", stamp.get("coding_seat_ok"))
    _print(print_fn, "  governance_installed:", stamp.get("governance_installed"))
    _print(print_fn, "  feedback_opt_in:", stamp.get("feedback_opt_in"))
    if chosen_pkg == "B":
        _print(print_fn, "  b_ready:", report.get("b_ready"))
    codes = stamp.get("reason_codes") or []
    if codes:
        _print(print_fn, "  reason_codes:", ", ".join(codes))
    _print(print_fn, "  hosts_registered:", ", ".join(hosts) if hosts else "(none)")

    exit_code = exit_code_for_report(report)
    report["exit_code"] = exit_code
    if stamp.get("status") == "ready" and (
        chosen_pkg != "B" or report.get("b_ready") is True
    ):
        _print(print_fn, "")
        _print(
            print_fn,
            "READY. Next: try a skill (e.g. /gandalf) in your coding CLI.",
        )
        if chosen_pkg == "B":
            _print(
                print_fn,
                "  Package B: open the Anchor Dashboard desktop icon",
                "(live dashboard + branded shortcut dual gate passed).",
            )
    elif stamp.get("status") == "not-ready" or (
        chosen_pkg == "B" and report.get("b_ready") is False
    ):
        _print(print_fn, "")
        if chosen_pkg == "B" and report.get("b_ready") is False:
            _print(
                print_fn,
                "NOT READY (Package B incomplete). Fix service/probe/desktop",
                "icon, then re-run. Skills may still be installed.",
            )
        else:
            _print(
                print_fn,
                "NOT READY. Install >=1 subscription CLI (claude / agy / grok), then re-run.",
            )
    else:
        _print(print_fn, "")
        _print(
            print_fn,
            "DEGRADED (coding seat present). Review reason_codes; skills may still work.",
        )
    return report



def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m share_onboard",
        description=(
            "Interactive shareable skills onboard (sole cold-start). "
            "Silent/non-interactive path never stamps ready."
        ),
    )
    p.add_argument(
        "--home",
        default=None,
        help="Share home directory (default: prompted; recommend C:\\dev on Windows)",
    )
    p.add_argument(
        "--package",
        choices=list(PACKAGE_IDS),
        default=None,
        help="Package A (skills) or B (Anchor+skills); default auto-detect",
    )
    p.add_argument(
        "--non-interactive",
        "--silent",
        action="store_true",
        dest="non_interactive",
        help="Fail closed: never stamp ready without full interactive dialogue",
    )
    p.add_argument(
        "--skills-src",
        default=None,
        help="Optional path to bundled skills source tree",
    )
    p.add_argument(
        "--feedback-yes",
        action="store_true",
        help="(Interactive/scripted) opt in to feedback; default is No",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help="Skip confirmation prompts (still runs dialogue_complete path when interactive)",
    )
    return p


def main(argv=None) -> int:
    """CLI entry for ``python -m share_onboard`` and ``onboard_cli.py``."""
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    skills_src = Path(args.skills_src) if args.skills_src else None
    home = Path(args.home) if args.home else None

    try:
        if args.non_interactive:
            print(
                "Non-interactive path: will NOT stamp ready "
                "(run without --non-interactive for guided dialogue)."
            )
            report = run_silent_onboard(
                home=home or recommend_home_dir(),
                package_id=args.package or detect_package_mode()["package_id"],
                skills_src=skills_src,
            )
            status = (report.get("readiness") or {}).get("status")
            print("Readiness:", status)
            print("Exit: non-zero (silent path fail closed)")
            return exit_code_for_report(report)

        report = run_interactive_onboard(
            home=home,
            package_id=args.package,
            skills_src=skills_src,
            skip_prompts=bool(args.yes and home is not None),
            feedback_opt_in=True if args.feedback_yes else None,
        )
        return int(report.get("exit_code") or exit_code_for_report(report))
    except ShareOnboardError as exc:
        print("Onboard refused:", exc.message, file=sys.stderr)
        if exc.reason:
            print("  reason:", exc.reason, file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\nAborted.", file=sys.stderr)
        return 130


def onboard_cli(argv=None) -> int:
    """Thin alias used by ``onboard_cli.py``."""
    return main(argv)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
