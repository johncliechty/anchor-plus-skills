"""Subscription-CLI model capabilities; no dated model IDs or API-key calls.

The durable choice is latest-supported / highest-supported. Exact model IDs
belong only to short-lived capability records and per-launch receipts.
"""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import threading
import time
from codex_catalog import reconcile_codex_catalog

POLICY_VERSION = 1
DEFAULT_POLICY = {"mode": "latest_supported", "effort": "highest_supported"}
VARIABLE_STRENGTH_POLICY = {"mode": "variable_strength", "default_strength": "standard"}
STRENGTH_TIERS = ("standard", "heavy", "light")
TOP_EFFORT_CHOICES = ("highest", "ultra", "max", "xhigh", "high")
DEFAULT_HEAVY_SPEC = {"model_steps_below": 0, "effort_steps_below": 0}
DEFAULT_LIGHT_SPEC = {"model_steps_below": 1, "effort_steps_below": 2}
HEAVY_DEFAULT_SKILLS = frozenset({"anvil", "chekhov", "aegis", "superjump"})
PORTFOLIO_SKILLS = (
    {"id": "anvil", "label": "Anvil", "group": "Heavy Default", "default_heavy": True},
    {"id": "chekhov", "label": "Chekhov", "group": "Heavy Default", "default_heavy": True},
    {"id": "aegis", "label": "Aegis", "group": "Heavy Default", "default_heavy": True},
    {"id": "superjump", "label": "Superjump", "group": "Heavy Default", "default_heavy": True},
    {"id": "gandalf", "label": "Gandalf", "group": "Deep Think & Ideation", "default_heavy": False},
    {"id": "jumper", "label": "Jumper", "group": "Deep Think & Ideation", "default_heavy": False},
    {"id": "researchprime", "label": "researchPrime", "group": "Trio (Research · Plan · Build)", "default_heavy": False},
    {"id": "crucible", "label": "Crucible", "group": "Trio (Research · Plan · Build)", "default_heavy": False},
    {"id": "foreman", "label": "Foreman", "group": "Trio (Research · Plan · Build)", "default_heavy": False},
    {"id": "einstein", "label": "Einstein", "group": "Domain & Specialist", "default_heavy": False},
    {"id": "ramanujan", "label": "Ramanujan", "group": "Domain & Specialist", "default_heavy": False},
    {"id": "literature-review", "label": "Literature Review", "group": "Domain & Specialist", "default_heavy": False},
    {"id": "financial-analyst", "label": "Financial Analyst", "group": "Domain & Specialist", "default_heavy": False},
    {"id": "legal-beagle", "label": "Legal Beagle", "group": "Domain & Specialist", "default_heavy": False},
    {"id": "doctor-seuss", "label": "Doctor Seuss", "group": "Domain & Specialist", "default_heavy": False},
    {"id": "figure-designer", "label": "Figure Designer", "group": "Domain & Specialist", "default_heavy": False},
    {"id": "scribe", "label": "Scribe", "group": "Operations & Hygiene", "default_heavy": False},
    {"id": "tidy-idy", "label": "Tidy-Idy", "group": "Operations & Hygiene", "default_heavy": False},
    {"id": "zombie-hunter", "label": "Zombie Hunter", "group": "Operations & Hygiene", "default_heavy": False},
    {"id": "agy-dispatch", "label": "AGY Dispatch", "group": "Operations & Hygiene", "default_heavy": False},
)
FAMILIES = frozenset({"chatgpt", "claude", "grok", "gemini"})
EFFORT_ORDER = ("none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra")
CLAUDE_CATALOG_MODELS = (
    "claude-fable-5-2",
    "claude-opus-5-5",
    "best",
    "opus",
    "sonnet",
    "haiku",
)
CLAUDE_PRO_CATALOG_MODELS = (
    "claude-opus-5-5",
    "opus",
    "sonnet",
    "haiku",
)
CANONICAL_CLAUDE_FABLE_MODEL = "claude-fable-5-2"
CANONICAL_CLAUDE_STANDARD_MODEL = "claude-opus-5-5"
_CLAUDE_MOVING_ALIASES = frozenset({"best", "opus", "sonnet", "haiku"})
_CLAUDE_DUPLICATE_ALIASES = frozenset({"best", "opus"})
_SMALL_OR_WRAPPER_TOKENS = ("flash", "lite", "nano", "mini", "haiku", "spark", "orchestrator")
CLAUDE_VERIFICATION_ROLES = frozenset({
    "review", "shark", "reviewer", "debate", "refuter", "gate3",
    "verify", "judge", "attacker", "analysis", "verifier", "adversarial",
})
_DATED_CLAUDE_FABLE_RE = re.compile(r"^claude-fable-5-2(?:-\d{8}|-\d{4}-\d{2}-\d{2})?$")
_DATED_CLAUDE_OPUS_55_RE = re.compile(r"^claude-opus-5-5(?:-\d{8}|-\d{4}-\d{2}-\d{2})?$")
_DATED_CLAUDE_SONNET_RE = re.compile(r"^claude-sonnet-\d+(?:-\d+)*(?:-\d{8}|-\d{4}-\d{2}-\d{2})?$")
_SKILL_ALIASES = {
    "anvil": "anvil",
    "chekhov": "chekhov",
    "checkov": "chekhov",
    "aegis": "aegis",
    "agies": "aegis",
    "sentinel": "aegis",
    "superjump": "superjump",
    "super-jump": "superjump",
    "gandalf": "gandalf",
    "researchprime": "researchprime",
    "research-prime": "researchprime",
    "crucible": "crucible",
    "foreman": "foreman",
    "jumper": "jumper",
    "ramanujan": "ramanujan",
    "scribe": "scribe",
    "einstein": "einstein",
    "legal-beagle": "legal-beagle",
    "legalbeagle": "legal-beagle",
    "financial-analyst": "financial-analyst",
    "financialanalyst": "financial-analyst",
    "doctor-seuss": "doctor-seuss",
    "literature-review": "literature-review",
    "figure-designer": "figure-designer",
    "figuredesigner": "figure-designer",
    "tidy-idy": "tidy-idy",
    "tidyidy": "tidy-idy",
    "zombie-hunter": "zombie-hunter",
    "zombiehunter": "zombie-hunter",
    "agy-dispatch": "agy-dispatch",
    "agydispatch": "agy-dispatch",
}
_LEADING_SKILL_QUALIFIER_RE = re.compile(
    r"^\s*(?:(?:please\s+)?(?:run|use|launch|start|invoke)\s+|/)?"
    r"(?P<skill>super\s+jump|super-jump|superjump|research\s*prime|research-prime|"
    r"legal[-\s]+beagle|financial[-\s]+analyst|doctor[-\s]+seuss|literature[-\s]+review|"
    r"figure[-\s]+designer|tidy[-\s]+idy|zombie[-\s]+hunter|agy[-\s]+dispatch|"
    r"anvil|chekhov|checkov|aegis|agies|sentinel|gandalf|crucible|foreman|jumper|ramanujan|scribe|einstein)"
    r"(?:\s+(?P<strength>heavy|light|standard|regular))?(?=$|[\s:.,;\-—/!?])",
    re.IGNORECASE,
)
CAPABILITY_TTL_SECONDS = 300
_LOCK = threading.RLock()
_MEMORY = {}


def normalize_strength(value, default="standard"):
    if not isinstance(value, str):
        return default
    tok = value.strip().lower()
    if tok == "regular":
        return "standard"
    if tok in STRENGTH_TIERS:
        return tok
    return default


def canonical_skill_name(skill) -> str | None:
    if not isinstance(skill, str) or not skill.strip():
        return None
    cleaned = re.sub(r"[\s_]+", "-", skill.strip().lower()).strip("/")
    return _SKILL_ALIASES.get(cleaned, _SKILL_ALIASES.get(cleaned.replace("-", "")))


def parse_leading_skill_qualifier(text) -> dict:
    """Extract leading `<Skill> [Heavy|Light|Standard]` intent without matching mid-sentence prose."""
    if not isinstance(text, str) or not text.strip():
        return {"skill": None, "strength": None}
    m = _LEADING_SKILL_QUALIFIER_RE.match(text)
    if not m:
        return {"skill": None, "strength": None}
    skill = canonical_skill_name(m.group("skill"))
    strength = normalize_strength(m.group("strength"), default=None)
    return {"skill": skill, "strength": strength}


def _normalize_step_spec(raw, fallback: dict) -> dict:
    if not isinstance(raw, dict):
        raise ValueError("strength tier spec must be an object")
    extra = set(raw) - {"model_steps_below", "effort_steps_below"}
    if extra:
        raise ValueError("strength tier spec contains unsupported keys")
    m_steps = raw.get("model_steps_below", fallback["model_steps_below"])
    e_steps = raw.get("effort_steps_below", fallback["effort_steps_below"])
    if type(m_steps) is not int or not 0 <= m_steps <= 3:
        raise ValueError("model_steps_below must be an integer between 0 and 3")
    if type(e_steps) is not int or not 0 <= e_steps <= 3:
        raise ValueError("effort_steps_below must be an integer between 0 and 3")
    return {"model_steps_below": m_steps, "effort_steps_below": e_steps}


def _normalize_heavy_skills(raw) -> list[str]:
    if not isinstance(raw, (list, tuple, set)):
        raise ValueError("heavy_skills must be a list of skill names")
    out: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise ValueError("heavy_skills entries must be strings")
        canon = canonical_skill_name(item)
        if not canon:
            raise ValueError(f"unknown skill in heavy_skills: {item!r}")
        if canon not in out:
            out.append(canon)
    return out


def effective_variable_strength_config(policy_or_settings=None) -> dict:
    pol = None
    if isinstance(policy_or_settings, dict):
        pol = policy_or_settings.get("model_policy") if "model_policy" in policy_or_settings else policy_or_settings
    if not isinstance(pol, dict) or pol.get("mode") != "variable_strength":
        pol = {}
    def_str = normalize_strength(pol.get("default_strength"), default="standard")
    top_eff = str(pol.get("top_effort") or "highest").strip().lower()
    if top_eff not in TOP_EFFORT_CHOICES:
        top_eff = "highest"
    try:
        heavy_spec = _normalize_step_spec(pol["heavy"], DEFAULT_HEAVY_SPEC) if isinstance(pol.get("heavy"), dict) else dict(DEFAULT_HEAVY_SPEC)
    except ValueError:
        heavy_spec = dict(DEFAULT_HEAVY_SPEC)
    try:
        light_spec = _normalize_step_spec(pol["light"], DEFAULT_LIGHT_SPEC) if isinstance(pol.get("light"), dict) else dict(DEFAULT_LIGHT_SPEC)
    except ValueError:
        light_spec = dict(DEFAULT_LIGHT_SPEC)
    if isinstance(pol.get("heavy_skills"), (list, tuple, set)):
        try:
            heavy_skills = _normalize_heavy_skills(pol["heavy_skills"])
        except ValueError:
            heavy_skills = [s["id"] for s in PORTFOLIO_SKILLS if s["default_heavy"]]
    else:
        heavy_skills = [s["id"] for s in PORTFOLIO_SKILLS if s["default_heavy"]]
    return {
        "mode": "variable_strength",
        "default_strength": def_str,
        "top_effort": top_eff,
        "heavy": heavy_spec,
        "light": light_spec,
        "heavy_skills": heavy_skills,
    }


def _configured_heavy_skills_set(*, settings=None, heavy_skills=None) -> set[str]:
    if heavy_skills is not None:
        try:
            return set(_normalize_heavy_skills(heavy_skills))
        except ValueError:
            return set(HEAVY_DEFAULT_SKILLS)
    if isinstance(settings, dict):
        pol = settings.get("model_policy")
        if isinstance(pol, dict) and isinstance(pol.get("heavy_skills"), (list, tuple, set)):
            try:
                return set(_normalize_heavy_skills(pol["heavy_skills"]))
            except ValueError:
                pass
    if not os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("ANCHOR_SETTINGS_DIR"):
        try:
            import anchor_settings
            loaded = anchor_settings.load_settings()
            pol = (loaded or {}).get("model_policy")
            if isinstance(pol, dict) and isinstance(pol.get("heavy_skills"), (list, tuple, set)):
                return set(_normalize_heavy_skills(pol["heavy_skills"]))
        except Exception:
            pass
    return set(HEAVY_DEFAULT_SKILLS)


def resolve_skill_strength(
    *,
    skill=None,
    explicit_strength=None,
    inherited_strength=None,
    cockpit_strength=None,
    default_strength="standard",
    settings=None,
    heavy_skills=None,
) -> str:
    """5-Level Variable Strength Precedence Law:
    1. Explicit per-call / CLI / UI pill designation (`Heavy` | `Light` | `Standard`)
    2. Inherited parent-run strength (`ANCHOR_INHERITED_STRENGTH`)
    3. Active Cockpit / Workbench override (`heavy` or `light`)
    4. Skill intrinsic or Setup-configured default (`Anvil`, `Chekhov`, `Aegis`, `Superjump` -> `heavy`)
    5. System default (`standard`)
    """
    exp = normalize_strength(explicit_strength, default=None)
    if exp is not None:
        return exp
    inh = normalize_strength(inherited_strength, default=None)
    if inh is not None:
        return inh
    ckp = normalize_strength(cockpit_strength, default=None)
    if ckp in ("heavy", "light"):
        return ckp
    canon_skill = canonical_skill_name(skill)
    if canon_skill and canon_skill in _configured_heavy_skills_set(settings=settings, heavy_skills=heavy_skills):
        return "heavy"
    return normalize_strength(default_strength, default="standard")


def _normalize_role_token(role=None, label=None) -> str:
    raw = role if isinstance(role, str) and role.strip() else None
    if not raw and isinstance(label, str) and label.strip():
        raw = re.split(r"[:#.\s/]", label.strip(), maxsplit=1)[0]
    return str(raw or "").strip().lower()


def is_claude_verification_role(*, role=None, label=None) -> bool:
    token = _normalize_role_token(role=role, label=label)
    return bool(token and token in CLAUDE_VERIFICATION_ROLES)


def normalize_claude_fable_model(model_id):
    if not isinstance(model_id, str):
        return model_id
    trimmed = model_id.strip()
    if _DATED_CLAUDE_FABLE_RE.fullmatch(trimmed):
        return CANONICAL_CLAUDE_FABLE_MODEL
    if _DATED_CLAUDE_OPUS_55_RE.fullmatch(trimmed):
        return CANONICAL_CLAUDE_STANDARD_MODEL
    return trimmed


class PolicyUnavailable(RuntimeError):
    def __init__(self, family, reason, *, code="capability_unavailable"):
        self.family, self.code = family, code
        super().__init__(f"{family}: {reason}")


def validate_policy(value):
    if not isinstance(value, dict):
        raise ValueError("model_policy must select latest_supported / highest_supported or variable_strength")
    if value == DEFAULT_POLICY:
        return dict(DEFAULT_POLICY)
    if value.get("mode") == "variable_strength":
        allowed = {"mode", "default_strength", "top_effort", "heavy", "light", "heavy_skills"}
        extra = set(value) - allowed
        if extra:
            raise ValueError("variable_strength model_policy contains unsupported keys")
        raw_def = value.get("default_strength", "standard")
        if not isinstance(raw_def, str) or normalize_strength(raw_def, default=None) is None:
            raise ValueError("variable_strength default_strength must be standard, heavy, or light")
        out = {
            "mode": "variable_strength",
            "default_strength": normalize_strength(raw_def, default="standard"),
        }
        if "top_effort" in value:
            te = value["top_effort"]
            if not isinstance(te, str) or te.strip().lower() not in TOP_EFFORT_CHOICES:
                raise ValueError("variable_strength top_effort must be highest, ultra, max, xhigh, or high")
            out["top_effort"] = te.strip().lower()
        if "heavy" in value:
            out["heavy"] = _normalize_step_spec(value["heavy"], DEFAULT_HEAVY_SPEC)
        if "light" in value:
            out["light"] = _normalize_step_spec(value["light"], DEFAULT_LIGHT_SPEC)
        if "heavy_skills" in value:
            out["heavy_skills"] = _normalize_heavy_skills(value["heavy_skills"])
        return out
    raise ValueError("model_policy must select latest_supported / highest_supported or variable_strength")


def highest_effort(levels):
    """Reject unknown semantics instead of silently choosing a lower effort."""
    values = []
    if not isinstance(levels, list):
        raise ValueError("No supported, understood reasoning-effort ordering")
    for level in levels:
        if not isinstance(level, (str, dict)):
            raise ValueError("Invalid reasoning-effort metadata")
        value = level if isinstance(level, str) else (
            level.get("effort") or level.get("reasoningEffort")
            or level.get("value") or level.get("id"))
        if value:
            values.append(str(value).lower())
    if not values or any(value not in EFFORT_ORDER for value in values):
        raise ValueError("No supported, understood reasoning-effort ordering")
    return max(values, key=EFFORT_ORDER.index)


def normalize_catalog(family, raw):
    """Keep capability fields only; never persist prompts, headers or secrets."""
    rows = []
    if not isinstance(raw, dict):
        raise PolicyUnavailable(family, "invalid capability catalog")
    def hidden(entry):
        return (entry.get("hidden") is True or entry.get("isHidden") is True
                or entry.get("selectable") is False
                or entry.get("visibility") in ("hide", "hidden", "none"))
    def row(model, levels, rank, upgrade, evidence):
        if not isinstance(model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model):
            raise PolicyUnavailable(family, "catalog model identity has unsupported characters")
        if type(rank) not in (int, float) or not math.isfinite(rank):
            raise PolicyUnavailable(family, "invalid catalog priority")
        try:
            highest_effort(levels)
        except ValueError as exc:
            raise PolicyUnavailable(family, str(exc), code="unsupported_effort") from exc
        rows.append({"model": model, "efforts": levels, "rank": rank,
                     "upgrade": upgrade, "evidence": evidence})
    if family == "chatgpt":
        entries = raw.get("models", raw.get("data", []))
        if not isinstance(entries, list):
            raise PolicyUnavailable(family, "invalid capability catalog")
        explicit_priority = bool(entries) and all(isinstance(e, dict) and type(e.get("priority")) in (int, float) for e in entries)
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise PolicyUnavailable(family, "invalid model metadata")
            model = entry.get("slug") or entry.get("model") or entry.get("id")
            if hidden(entry):
                continue
            levels = entry.get("supported_reasoning_levels", entry.get("supportedReasoningEfforts", []))
            row(model, levels, entry["priority"] if explicit_priority else index,
                entry.get("upgrade"), "installed_cli_priority+native_capabilities" if entry.get("_codex_catalog_evidence")
                else "provider_priority" if explicit_priority else "provider_catalog_order")
    elif family == "grok":
        entries = raw.get("models", {})
        if isinstance(entries, dict):
            entries = list(entries.values())
        if not isinstance(entries, list):
            raise PolicyUnavailable(family, "invalid capability catalog")
        for index, entry in enumerate(entries):
            if not isinstance(entry, dict):
                raise PolicyUnavailable(family, "invalid model metadata")
            info = entry.get("info", entry)
            if not isinstance(info, dict):
                raise PolicyUnavailable(family, "invalid model metadata")
            model = info.get("model") or info.get("id")
            if hidden(info):
                continue
            row(model, info.get("reasoning_efforts", []), index, None, "provider_catalog_order")
    elif family == "gemini":
        models = list(raw.get("models", []))
        def _gemini_key(item):
            idx, entry = item
            name = str(entry.get("model", "")).lower()
            is_small = 1 if any(t in name for t in ("flash", "lite", "nano")) else 0
            is_internal = 1 if "orchestrator" in name else 0
            m = re.match(r"^gemini-(\d+(?:\.\d+)*)", name)
            ver = tuple(-int(x) for x in m.group(1).split(".")) if m else (1,)
            return (is_small, is_internal, ver, idx)
        ranks = {orig_idx: new_rank for new_rank, (orig_idx, _) in enumerate(sorted(enumerate(models), key=_gemini_key))}
        for index, entry in enumerate(models):
            row(entry["model"], entry["efforts"], ranks[index], None, "provider_catalog_order")
    elif family == "claude":
        efforts = raw.get("efforts", [])
        explicit_models = raw.get("models")
        if isinstance(explicit_models, (list, tuple)) and explicit_models:
            for rank_idx, entry in enumerate(explicit_models):
                if isinstance(entry, dict):
                    row(
                        entry.get("model") or entry.get("slug") or entry.get("id"),
                        entry.get("efforts", efforts),
                        entry.get("rank", rank_idx),
                        entry.get("upgrade"),
                        entry.get("evidence", "provider_moving_alias"),
                    )
                else:
                    row(entry, efforts, rank_idx, None, "provider_moving_alias")
        else:
            aliases = (
                CLAUDE_CATALOG_MODELS
                if (raw.get("include_frontier") is True or raw.get("canonical") is True)
                else ("best", "opus", "sonnet", "haiku")
            )
            for rank_idx, alias in enumerate(aliases):
                row(alias, efforts, rank_idx, None, "provider_moving_alias")
    else:
        raise PolicyUnavailable(family, "the installed transport does not expose verified model capabilities")
    if not rows:
        raise PolicyUnavailable(family, "no visible subscription models were advertised")
    return rows


_AGY_EFFORT_SUFFIX = re.compile(r"^(gemini-[A-Za-z0-9.\-]+?)-(minimal|low|medium|high|xhigh|max)$")


def parse_agy_models(text):
    """``agy models`` -> [{"model": base, "efforts": [...]}] in the CLI's order. agy encodes the effort in the id
    (gemini-3.8-flash-high); the base is the model, the suffixes its efforts. Use :func:`agy_model_id` to rebuild."""
    order, efforts = [], {}
    for line in str(text or "").splitlines():
        ident = line.split("	", 1)[0].strip()
        if not ident.startswith("gemini-"):
            continue
        m = _AGY_EFFORT_SUFFIX.match(ident)
        base, effort = (m.group(1), m.group(2)) if m else (ident, None)
        if base not in efforts:
            order.append(base)
            efforts[base] = []
        if effort and effort not in efforts[base]:
            efforts[base].append(effort)
    # a model agy lists without an effort suffix runs at its one default effort, which agy calls medium
    return [{"model": base, "efforts": efforts[base] or ["medium"]} for base in order]


def agy_model_id(model, effort):
    """The id agy accepts for a Gemini base model at an effort (the suffixed form when the base has efforts)."""
    if effort and not _AGY_EFFORT_SUFFIX.match(str(model)):
        return f"{model}-{effort}"
    return str(model)


def select_model(family, catalog):
    if family not in FAMILIES:
        raise PolicyUnavailable(str(family), "unknown model family")
    rows = sorted(catalog, key=lambda item: item["rank"])
    if not rows:
        raise PolicyUnavailable(family, "no available model")
    if family == "chatgpt" and len(rows) > 1 and rows[0]["rank"] == rows[1]["rank"]:
        raise PolicyUnavailable(family, "latest model ranking is ambiguous; refresh subscription capabilities")
    chosen = rows[0]
    initial_model = chosen["model"]
    initial_evidence = str(chosen.get("evidence") or "normalized_catalog")
    by_name = {row["model"]: row for row in rows}
    visited = set()
    while chosen.get("upgrade"):
        target = chosen["upgrade"]
        if isinstance(target, dict):
            target = target.get("model") or target.get("id")
        if target in visited:
            raise PolicyUnavailable(family, "cyclic catalog upgrade metadata")
        visited.add(chosen["model"])
        if target not in by_name:
            raise PolicyUnavailable(family, "recommended model upgrade is unavailable")
        chosen = by_name[target]
    try:
        effort = highest_effort(chosen["efforts"])
    except ValueError as error:
        raise PolicyUnavailable(family, str(error), code="unsupported_effort") from error
    result = {"policy_version": POLICY_VERSION, "requested_policy": dict(DEFAULT_POLICY),
              "family": family, "model": chosen["model"], "effort": effort,
              "selection_evidence": initial_evidence + ("+provider_upgrade" if initial_model != chosen["model"] else ""), "model_attested": False}
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", result["model"]):
        raise PolicyUnavailable(family, "catalog model identity has unsupported characters")
    if initial_evidence == "provider_catalog_order":
        result["warning"] = "Provider-recommended catalog order; frontier ranking is not explicitly attested."
    return result


def _resolve_effort_for_steps(levels, effort_steps_below: int, top_effort: str = "highest") -> str:
    highest_effort(levels)
    supported_set = set()
    for level in levels:
        val = level if isinstance(level, str) else (
            level.get("effort") or level.get("reasoningEffort")
            or level.get("value") or level.get("id")
        )
        if val:
            supported_set.add(str(val).lower())
    ordered = [e for e in EFFORT_ORDER if e in supported_set]
    cap_name = top_effort if top_effort in ("ultra", "max", "xhigh", "high") else "ultra"
    cap_idx = EFFORT_ORDER.index(cap_name)
    capped = [e for e in ordered if EFFORT_ORDER.index(e) <= cap_idx] or [ordered[0]]
    top_rung = 2 if top_effort == "high" else 3
    target_rung = max(0, top_rung - max(0, int(effort_steps_below)))
    if target_rung >= 3:
        return capped[-1]
    if target_rung == 2:
        if "high" in capped:
            return "high"
        le = [e for e in capped if EFFORT_ORDER.index(e) <= EFFORT_ORDER.index("high")]
        return le[-1] if le else capped[0]
    if target_rung == 1:
        if "medium" in capped:
            return "medium"
        le = [e for e in capped if EFFORT_ORDER.index(e) <= EFFORT_ORDER.index("medium")]
        return le[-1] if le else capped[0]
    if "low" in capped:
        return "low"
    le = [e for e in capped if EFFORT_ORDER.index(e) <= EFFORT_ORDER.index("low")]
    return le[-1] if le else capped[0]


def _standard_effort_for_levels(levels, family: str) -> str:
    return _resolve_effort_for_steps(levels, 2, "highest")


def _is_small_or_wrapper_model(model_id: str) -> bool:
    segs = set(re.split(r"[-_./:\s]+", str(model_id or "").lower()))
    return bool(segs & set(_SMALL_OR_WRAPPER_TOKENS))


def _generalist_ladder(family: str, rows: list[dict]) -> list[dict]:
    if family == "claude":
        has_versioned = any(r["model"] not in _CLAUDE_MOVING_ALIASES for r in rows)
        if has_versioned:
            generalist = [
                r for r in rows
                if r["model"] not in _CLAUDE_DUPLICATE_ALIASES
                and not _is_small_or_wrapper_model(r["model"])
            ]
        else:
            generalist = [r for r in rows if "haiku" not in r["model"].lower()]
    else:
        generalist = [
            r for r in rows
            if not _is_small_or_wrapper_model(r["model"])
        ]
    return generalist if generalist else rows


def select_strength(family, catalog, strength="standard", *, policy=None):
    """Select (model, effort) for ``strength`` ('standard' | 'heavy' | 'light')
    using user-configurable relative step-downs below the discovered top-tier
    frontier model and highest effort."""
    eff_strength = normalize_strength(strength, default="standard")
    cfg = effective_variable_strength_config(policy)
    spec = cfg["heavy"] if eff_strength == "heavy" else cfg["light"]
    m_steps = int(spec["model_steps_below"])
    e_steps = int(spec["effort_steps_below"])
    top_eff = str(cfg["top_effort"])
    if eff_strength == "heavy" and m_steps == 0 and e_steps == 0 and top_eff == "highest":
        base = select_model(family, catalog)
        base["requested_strength"] = "heavy"
        return base
    if family not in FAMILIES:
        raise PolicyUnavailable(str(family), "unknown model family")
    rows = sorted(catalog, key=lambda item: item["rank"])
    if not rows:
        raise PolicyUnavailable(family, "no available model")
    if family == "chatgpt" and len(rows) > 1 and rows[0]["rank"] == rows[1]["rank"]:
        raise PolicyUnavailable(family, "latest model ranking is ambiguous; refresh subscription capabilities")
    generalist = _generalist_ladder(family, rows)
    idx = min(max(0, m_steps), len(generalist) - 1)
    chosen = generalist[idx]
    if m_steps == 0:
        step_suffix = "+frontier_step0" if (e_steps > 0 or top_eff != "highest") else ""
    elif len(generalist) == 1:
        step_suffix = "+single_model_catalog_effort_stepdown"
    elif idx == 1:
        step_suffix = "+one_below_frontier"
    else:
        step_suffix = f"+{idx}_below_frontier"
    try:
        effort = _resolve_effort_for_steps(chosen["efforts"], e_steps, top_eff)
    except ValueError as error:
        raise PolicyUnavailable(family, str(error), code="unsupported_effort") from error
    initial_evidence = str(chosen.get("evidence") or "normalized_catalog")
    req_pol = dict(policy) if isinstance(policy, dict) and policy.get("mode") == "variable_strength" else {"mode": "variable_strength", "default_strength": "standard"}
    result = {
        "policy_version": POLICY_VERSION,
        "requested_policy": req_pol,
        "requested_strength": eff_strength,
        "family": family,
        "model": chosen["model"],
        "effort": effort,
        "selection_evidence": initial_evidence + step_suffix,
        "model_attested": False,
    }
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", result["model"]):
        raise PolicyUnavailable(family, "catalog model identity has unsupported characters")
    if initial_evidence == "provider_catalog_order":
        result["warning"] = "Provider-recommended catalog order; frontier ranking is not explicitly attested."
    return result


def is_variable_strength_active(*, settings=None, env=None, tier=None, skill=None) -> bool:
    pol = (settings or {}).get("model_policy") if isinstance(settings, dict) else None
    mode = pol.get("mode") if isinstance(pol, dict) else None
    if mode == "variable_strength":
        return True
    active_env = os.environ if env is None else env
    if normalize_strength(tier, default=None) == "light":
        return True
    if normalize_strength(active_env.get("ANCHOR_STRENGTH"), default=None) is not None:
        return True
    if normalize_strength(active_env.get("TRIO_TIER"), default=None) == "light":
        return True
    if active_env.get("ANCHOR_VARIABLE_STRENGTH") == "1":
        return True
    if canonical_skill_name(skill or active_env.get("ANCHOR_SKILL")) and mode != "latest_supported":
        return True
    return False


_IMPORT_TIME_HOME_LOWER = str(Path.home().resolve()).lower()
_IMPORT_TIME_LOCAL_LOWER = str((Path.home() / "AppData" / "Local").resolve()).lower() if os.name == "nt" else ""
_IMPORT_TIME_ROAMING_LOWER = str((Path.home() / "AppData" / "Roaming").resolve()).lower() if os.name == "nt" else ""
_CMD_METACHARS_RE = re.compile(r'[&|^%!<>\"\r\n]')
_NPM_SHIM_SCRIPT_RE = re.compile(
    r'["\']?(?:%~?dp0[\\/]?|%dp0%[\\/]?)(node_modules[\\/][^"\'\r\n]+?\.(?:c?m?js))["\']?',
    re.IGNORECASE,
)
_PY_SHIM_SCRIPT_RE = re.compile(
    r'@echo\s+off\s+"([^"]*python[^"]*\.exe)"\s+"([^"]+\.py)"\s+%\*',
    re.IGNORECASE,
)


def _agy_bin_dir(env):
    """agy (Gemini) installs per user under %LOCALAPPDATA%/agy/bin. The Anchor service's PATH is the machine PATH plus
    a few user folders, so agy is not on it (2026-10-07); Codex has the same shape and codex_adapter finds it by its
    known folder. LOCALAPPDATA may be unset in the service, so USERPROFILE/AppData/Local is the fallback."""
    if os.name != "nt":
        return None
    bases = [env.get("LOCALAPPDATA")]
    if env.get("USERPROFILE"):
        bases.append(os.path.join(env["USERPROFILE"], "AppData", "Local"))
    for base in filter(None, bases):
        folder = os.path.join(base, "agy", "bin")
        if os.path.isfile(os.path.join(folder, "agy.exe")):
            return folder
    return None


def _allow_user_cli_fallback(active_env: dict, explicit_env_passed: bool) -> bool:
    if active_env.get("ANCHOR_HERMETIC_PATH_ONLY") == "1":
        return False
    if active_env.get("ANCHOR_ALLOW_USER_CLI_FALLBACK") == "1":
        return True
    if not os.environ.get("PYTEST_CURRENT_TEST"):
        if explicit_env_passed:
            return any(k in active_env for k in ("USERPROFILE", "HOME", "LOCALAPPDATA", "APPDATA"))
        return True
    # Under pytest, only probe user-profile CLI dirs when the test explicitly pointed
    # HOME / USERPROFILE / LOCALAPPDATA / APPDATA at an isolated test directory (not the host home itself).
    defaults = {
        "USERPROFILE": _IMPORT_TIME_HOME_LOWER,
        "HOME": _IMPORT_TIME_HOME_LOWER,
        "LOCALAPPDATA": _IMPORT_TIME_LOCAL_LOWER,
        "APPDATA": _IMPORT_TIME_ROAMING_LOWER,
    }
    for key, host_default in defaults.items():
        val = active_env.get(key)
        if val:
            try:
                p_low = str(Path(val).resolve()).lower()
                if p_low and p_low != host_default:
                    return True
            except OSError:
                continue
    return False


def _candidate_cli_paths(family: str, active_env: dict) -> list[Path]:
    """Return ordered native-first CLI binary candidates for ``family``."""
    home_raw = active_env.get("USERPROFILE") or active_env.get("HOME") or ""
    home = Path(home_raw) if home_raw else None
    local_raw = active_env.get("LOCALAPPDATA") or (str(home / "AppData" / "Local") if (os.name == "nt" and home) else "")
    app_raw = active_env.get("APPDATA") or (str(home / "AppData" / "Roaming") if (os.name == "nt" and home) else "")
    local_app = Path(local_raw) if local_raw else None
    app_data = Path(app_raw) if app_raw else None
    out: list[Path] = []
    if os.name == "nt":
        if family == "claude":
            if home:
                out.extend([home / ".local" / "bin" / "claude.exe", home / ".claude" / "local" / "claude.exe"])
            if local_app:
                out.extend([local_app / "Programs" / "claude" / "claude.exe", local_app / "AnthropicClaude" / "claude.exe"])
            if app_data:
                out.append(app_data / "npm" / "claude.cmd")
        elif family == "gemini":
            if local_app:
                out.extend([
                    local_app / "agy" / "bin" / "agy.exe",
                    local_app / "Programs" / "Antigravity" / "bin" / "agy.exe",
                    local_app / "agy" / "bin" / "agy.cmd",
                ])
            if home:
                out.append(home / ".local" / "bin" / "agy.exe")
        elif family == "chatgpt":
            if local_app:
                out.extend([
                    local_app / "Programs" / "OpenAI" / "Codex" / "bin" / "codex.exe",
                    local_app / "Programs" / "codex" / "codex.exe",
                ])
            if home:
                out.extend([home / ".codex" / "bin" / "codex.exe", home / ".local" / "bin" / "codex.exe"])
            if app_data:
                out.append(app_data / "npm" / "codex.cmd")
        elif family == "grok":
            if home:
                out.extend([home / ".grok" / "bin" / "grok.exe", home / ".local" / "bin" / "grok.exe"])
            if local_app:
                out.extend([local_app / "grok" / "bin" / "grok.exe", local_app / "grok" / "bin" / "grok.cmd"])
            if app_data:
                out.append(app_data / "npm" / "grok.cmd")
    else:
        bin_name = {"chatgpt": "codex", "claude": "claude", "grok": "grok", "gemini": "agy"}.get(family, "")
        if bin_name:
            if home:
                out.extend([
                    home / ".local" / "bin" / bin_name,
                    home / f".{bin_name}" / "bin" / bin_name,
                    home / ".npm-global" / "bin" / bin_name,
                ])
            out.extend([Path("/opt/homebrew/bin") / bin_name, Path("/usr/local/bin") / bin_name])
    return out


def resolve_cli_executable(family: str, env=None) -> str | None:
    """Resolve ``family`` CLI binary, preferring native ``.exe`` binaries over ``.cmd`` shims."""
    binary = {"chatgpt": "codex", "claude": "claude", "grok": "grok", "gemini": "agy"}.get(family)
    if not binary:
        return None
    explicit = env is not None
    active_env = dict(os.environ if env is None else env)
    path_val = active_env.get("PATH")
    if os.name == "nt":
        direct_exe = shutil.which(binary + ".exe", path=path_val)
        if direct_exe:
            return direct_exe
    else:
        direct_bin = shutil.which(binary, path=path_val)
        if direct_bin:
            return direct_bin
    if _allow_user_cli_fallback(active_env, explicit):
        for cand in _candidate_cli_paths(family, active_env):
            if cand.is_file() and cand.suffix.lower() != ".cmd":
                return str(cand)
        if os.name == "nt":
            direct_cmd = shutil.which(binary + ".cmd", path=path_val) or shutil.which(binary, path=path_val)
            if direct_cmd:
                return direct_cmd
            for cand in _candidate_cli_paths(family, active_env):
                if cand.is_file():
                    return str(cand)
    elif os.name == "nt":
        direct_cmd = shutil.which(binary + ".cmd", path=path_val)
        if direct_cmd:
            return direct_cmd
    return None


def safe_cli_argv(command: str, args=(), *, env=None) -> list[str]:
    """Build ``BatBadBut``-safe subprocess argv.

    On Windows, ``.cmd`` / ``.bat`` shims are routed by ``CreateProcessW`` through
    ``cmd.exe /c``, even when ``shell=False``. Whenever ``command`` is a ``.cmd``/``.bat``
    shim, unwrap standard npm / Anchor Python shims directly to ``[node.exe, script.js, ...]``
    or ``[python.exe, script.py, ...]`` so ``cmd.exe`` never runs; if a custom batch file
    cannot be unwrapped, reject ``cmd.exe`` metacharacters fail-closed.
    """
    cmd_str = str(command or "")
    arg_list = [str(a) for a in (args or ())]
    if os.name != "nt" or not cmd_str.lower().endswith((".cmd", ".bat")):
        return [cmd_str] + arg_list
    cmd_path = Path(cmd_str)
    active_env = dict(os.environ if env is None else env)
    if cmd_path.is_file():
        try:
            shim_txt = cmd_path.read_text(encoding="utf-8", errors="ignore")
            shim_dir = cmd_path.parent.resolve()
            m_npm = _NPM_SHIM_SCRIPT_RE.search(shim_txt)
            if m_npm:
                rel_script = m_npm.group(1).replace("\\", "/")
                script_path = (shim_dir / rel_script).resolve()
                if script_path.is_file() and script_path.is_relative_to(shim_dir):
                    node_exe = (
                        ( str(shim_dir / "node.exe") if (shim_dir / "node.exe").is_file() else None )
                        or shutil.which("node.exe", path=active_env.get("PATH"))
                        or (r"C:\Program Files\nodejs\node.exe" if os.path.isfile(r"C:\Program Files\nodejs\node.exe") else None)
                    )
                    if node_exe:
                        return [node_exe, str(script_path)] + arg_list
            m_py = _PY_SHIM_SCRIPT_RE.search(shim_txt)
            if m_py:
                py_exe, py_script = m_py.group(1), m_py.group(2)
                if os.path.isfile(py_exe) and os.path.isfile(py_script):
                    return [py_exe, py_script] + arg_list
        except OSError:
            pass
    for a in arg_list:
        if _CMD_METACHARS_RE.search(a):
            raise ValueError("Refusing unsafe cmd.exe metacharacters in .cmd/.bat argument")
    return [cmd_str] + arg_list


def ensure_agy_on_path(env):
    """Append agy's folder to ``env``'s PATH when agy is installed but not reachable; returns ``env``."""
    folder = _agy_bin_dir(env)
    key = next((k for k in env if k.upper() == "PATH"), "PATH")
    entries = [p for p in str(env.get(key) or "").split(os.pathsep) if p]
    if folder and not any(os.path.normcase(os.path.normpath(p)) == os.path.normcase(folder) for p in entries):
        env[key] = os.pathsep.join(entries + [folder])
    return env


# Every provider lookup and child launch in the Anchor process (stewards, job runner, Setup checks, Foreman's trio
# seats) inherits this process's PATH, so agy is made reachable once, here.
ensure_agy_on_path(os.environ)


def policy_environment(env=None):
    """Ignore stale model-only pins; preserve credentials and permission policy."""
    out = ensure_agy_on_path(dict(os.environ if env is None else env))
    for key in list(out):
        if (key.startswith("ANTHROPIC_DEFAULT_") and key.endswith("_MODEL")) or key in {
            "ANTHROPIC_MODEL", "CLAUDE_MODEL", "CLAUDE_CODE_EFFORT_LEVEL", "GROK_DEFAULT_MODEL",
            "GROK_MODEL", "CODEX_MODEL", "CHATGPT_MODEL", "CODEX_REASONING_EFFORT",
            "OPENAI_API_KEY", "CODEX_API_KEY", "XAI_API_KEY", "GROK_API_KEY",
            "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN",
            "OPENAI_BASE_URL", "OPENAI_API_BASE", "ANTHROPIC_BASE_URL",
            "XAI_BASE_URL", "GROK_BASE_URL", "GEMINI_API_KEY", "GOOGLE_API_KEY",
            "CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
        }:
            out.pop(key, None)
    return out


def _run(argv, env):
    try:
        safe_argv = safe_cli_argv(argv[0], argv[1:], env=env) if argv else list(argv)
        completed = subprocess.run(safe_argv, env=env, capture_output=True, text=True,
                                   encoding="utf-8", errors="replace", timeout=25,
                                   shell=False, creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0))
    except ValueError as error:
        raise RuntimeError(f"CLI discovery {type(error).__name__}: {error}") from error
    except (OSError, subprocess.TimeoutExpired) as error:
        raise RuntimeError(f"CLI discovery {type(error).__name__}") from error
    if completed.returncode:
        # Provider stderr can contain credentials/login URLs. Never return it.
        # Classify it instead (Grok R2 N1): only an auth-shaped failure is a
        # dead login; any other nonzero exit is transient or unknown.
        # URLs are stripped first: a transient body can name auth.openai.com
        # without meaning the login is dead (Grok R3 P1); the phrases below
        # are the adapter's own auth pattern.
        diagnostics = re.sub(r"https?://\S+", " ", f"{completed.stderr or ''} {completed.stdout or ''}")
        if re.search(r"(?i)(not logged in|logged out|authentication|unauthori[sz]ed|forbidden|\b401\b|\b403\b)", diagnostics):
            raise RuntimeError(f"CLI discovery exited {completed.returncode}; subscription login required")
        raise RuntimeError(f"CLI discovery exited {completed.returncode}; transient or unknown failure")
    return completed.stdout


def _probe_claude_subscription_profile(command: str, env: dict) -> dict:
    """Best-effort live Claude subscription tier probe (`claude auth status --json`).
    Never called when a unit test supplies a custom `runner` stub."""
    try:
        safe_argv = safe_cli_argv(command, ["auth", "status", "--json"], env=env)
        completed = subprocess.run(
            safe_argv, env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=6, shell=False,
            creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
        )
        parsed = json.loads((completed.stdout or "").strip())
        if isinstance(parsed, dict):
            sub_type = str(parsed.get("subscriptionType") or "").strip().lower()
            plan_tier = str(parsed.get("planTier") or "").strip().lower()
            return {
                "logged_in": bool(parsed.get("loggedIn")),
                "subscription_type": sub_type,
                "plan_tier": plan_tier,
                "restrict_frontier": bool(parsed.get("loggedIn") is True and sub_type in ("pro", "free")),
            }
    except Exception:
        pass
    return {"logged_in": None, "subscription_type": "", "plan_tier": "", "restrict_frontier": False}


def discover(family, *, env=None, runner=_run):
    explicit_env = env is not None
    env = policy_environment(env)
    if not explicit_env:
        env = dict(env)
    binary = {"chatgpt": "codex", "claude": "claude", "grok": "grok", "gemini": "agy"}.get(family)
    if binary is None:
        raise PolicyUnavailable(str(family), "unknown model family")
    command = resolve_cli_executable(family, env=env if explicit_env else None)
    if not command:
        raise PolicyUnavailable(family, "subscription CLI is not installed", code="cli_missing")
    try:
        if family == "chatgpt":
            raw = json.loads(runner([command, "debug", "models"], env))
            # The refreshed catalog may retain bundled predecessor ranks.
            # Reconcile only an ambiguous native top group; availability and
            # effort remain from the refreshed subscription capabilities.
            try:
                bundled = json.loads(runner([command, "debug", "models", "--bundled"], env))
            except Exception:
                bundled = None  # A unique current ranking needs no tie-break.
            raw = reconcile_codex_catalog(raw, bundled)
        elif family == "grok":
            version_text = runner([command, "--version"], env)
            version_match = re.search(r"\b\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.]+)?\b", version_text)
            runner([command, "models"], env)
            grok_root = Path(env.get("GROK_HOME") or Path(env.get("USERPROFILE") or env.get("HOME") or Path.home()) / ".grok")
            cache = json.loads((grok_root / "models_cache.json").read_text(encoding="utf-8"))
            from datetime import datetime, timezone
            fetched = datetime.fromisoformat(cache["fetched_at"].replace("Z", "+00:00"))
            # The subscription CLI renews unchanged catalogs after an etag
            # check without changing their original content-fetch timestamp.
            renewed = cache.get("renewed_at")
            fresh = (datetime.fromisoformat(renewed.replace("Z", "+00:00"))
                     if renewed is not None else fetched)
            if fresh < fetched:
                raise RuntimeError("Grok catalog renewal predates its content")
            age = (datetime.now(timezone.utc) - fresh).total_seconds()
            if not 0 <= age < CAPABILITY_TTL_SECONDS:
                raise RuntimeError("Grok catalog is stale; refresh subscription capability discovery")
            if cache.get("auth_method") != "session":
                raise RuntimeError("Grok capability catalog is not from subscription authentication")
            if not version_match or cache.get("grok_version") != version_match.group(0):
                raise RuntimeError("Grok capability catalog belongs to another CLI version")
            if cache.get("origin") != "https://cli-chat-proxy.grok.com/v1/models":
                raise RuntimeError("Grok capability catalog has an unverified subscription origin")
            raw = cache
        elif family == "claude":
            help_text = runner([command, "--help"], env)
            match = re.search(r"--effort\s+<[^>]+>[\s\S]{0,180}?\(([^)]+)\)", help_text)
            if not match:
                raise RuntimeError("Installed Claude CLI does not advertise effort capabilities")
            sub_prof = _probe_claude_subscription_profile(command, env) if runner is _run else {"restrict_frontier": False}
            models_list = list(CLAUDE_PRO_CATALOG_MODELS if sub_prof.get("restrict_frontier") else CLAUDE_CATALOG_MODELS)
            raw = {
                "models": models_list,
                "efforts": [part.strip() for part in match.group(1).split(",")],
            }
        elif family == "gemini":
            # agy (the Antigravity CLI, 2026-10-07: 1.3.x) lists "<id>	<display name>" rows, newest first. It
            # also serves other vendors' models; only gemini-* rows belong to the Gemini family.
            raw = {"models": parse_agy_models(runner([command, "models"], env))}
        else:
            raise RuntimeError("capability discovery is not supported; configure a verified transport")
        return normalize_catalog(family, raw), command
    except (RuntimeError, ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        # codex-discipline-2026-09-15: a dead subscription login is a capacity
        # loss (the ladder may walk), unlike a timeout or an ambiguous ranking.
        code = "auth_required" if "subscription login required" in str(error) else "capability_unavailable"
        raise PolicyUnavailable(family, str(error), code=code) from error


def _cache_identity(family, env):
    """Invalidate on CLI/auth/config changes without reading credential values."""
    profile = Path(env.get("USERPROFILE") or env.get("HOME") or Path.home())
    binary = {"chatgpt": "codex", "claude": "claude", "grok": "grok", "gemini": "agy"}.get(family, "")
    command = shutil.which(binary, path=env.get("PATH")) if binary else None
    provider_root = Path(env.get("CODEX_HOME") or profile / ".codex") if family == "chatgpt" else (
        Path(env.get("GROK_HOME") or profile / ".grok") if family == "grok" else (
            profile / ".gemini" / "antigravity-cli" if family == "gemini" else Path(env.get("CLAUDE_CONFIG_DIR") or profile / ".claude")))
    paths = ([Path(command)] if command else []) + [provider_root / name for name in
             ("auth.json", "config.toml", "settings.json", ".credentials.json", "session.json", "models_cache.json")]
    stamps = []
    for path in paths:
        try:
            stat = path.stat()
            stamps.append((str(path), stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns))
        except OSError:
            stamps.append((str(path), None))
    return (family, str(profile), env.get("PATH"), str(provider_root), env.get('ANCHOR_PROVIDER_CONNECTION'), tuple(stamps))


def resolve(family, *, settings=None, force=False, env=None, discoverer=None, role=None, label=None, tier=None, skill=None):
    """Resolve for a new session/seat. This never changes an existing session."""
    discoverer = discoverer or discover
    validated_pol = dict(DEFAULT_POLICY)
    if settings is not None:
        if settings.get("settings_error"):
            raise PolicyUnavailable(family, "Anchor settings are invalid", code="invalid_settings")
        validated_pol = validate_policy(settings.get("model_policy", DEFAULT_POLICY))
    active_env = os.environ if env is None else env
    identity = _cache_identity(family, active_env)
    with _LOCK:
        cached = _MEMORY.get(identity)
        if force or not cached or time.time() - cached["discovered_at"] >= CAPABILITY_TTL_SECONDS:
            catalog, command = discoverer(family, env=active_env)
            selected = select_model(family, catalog)
            cached = {**selected, "command": command, "discovered_at": time.time(), "_catalog_rows": list(catalog)}
            _MEMORY[_cache_identity(family, active_env)] = cached
        result = dict(cached)
        catalog_rows = list(result.pop("_catalog_rows", None) or [])
        result["requested_policy"] = dict(validated_pol)
    if is_variable_strength_active(settings=settings, env=active_env, tier=tier, skill=skill):
        vs_cfg = effective_variable_strength_config(validated_pol if validated_pol.get("mode") == "variable_strength" else settings)
        eff_strength = resolve_skill_strength(
            skill=skill or active_env.get("ANCHOR_SKILL"),
            explicit_strength=tier or active_env.get("ANCHOR_STRENGTH") or active_env.get("TRIO_TIER"),
            inherited_strength=active_env.get("ANCHOR_INHERITED_STRENGTH"),
            cockpit_strength=active_env.get("ANCHOR_COCKPIT_STRENGTH"),
            default_strength=vs_cfg["default_strength"],
            settings=settings,
        )
        vs_selected = select_strength(family, catalog_rows, eff_strength, policy=vs_cfg)
        result.update(vs_selected)
        result["requested_policy"] = (
            dict(validated_pol) if validated_pol.get("mode") == "variable_strength" else dict(VARIABLE_STRENGTH_POLICY)
        )
        if (
            family == "claude"
            and eff_strength == "heavy"
            and vs_cfg["heavy"]["model_steps_below"] == 0
            and (
                any(r.get("model") == CANONICAL_CLAUDE_FABLE_MODEL for r in catalog_rows)
                or all(r.get("model") in _CLAUDE_MOVING_ALIASES for r in catalog_rows)
            )
        ):
            fable_row = next((r for r in catalog_rows if r.get("model") == CANONICAL_CLAUDE_FABLE_MODEL), None)
            result["model"] = CANONICAL_CLAUDE_FABLE_MODEL
            if vs_cfg["heavy"]["effort_steps_below"] == 0 and vs_cfg["top_effort"] == "highest":
                if fable_row and fable_row.get("efforts"):
                    result["effort"] = highest_effort(fable_row["efforts"])
                elif result.get("effort") not in EFFORT_ORDER:
                    result["effort"] = "max"
            elif fable_row and fable_row.get("efforts"):
                result["effort"] = _resolve_effort_for_steps(
                    fable_row["efforts"],
                    vs_cfg["heavy"]["effort_steps_below"],
                    vs_cfg["top_effort"],
                )
            result["selection_evidence"] = "heavy_review_fable_pin"
        result["settings_revision"] = (settings or {}).get("settings_revision", 0)
        return result
    if family == "claude":
        heavy_or_verify = is_claude_verification_role(role=role, label=label) or (
            str(tier or active_env.get("TRIO_TIER") or "").strip().lower() == "heavy"
        )
        if heavy_or_verify:
            fable_row = next((r for r in catalog_rows if r.get("model") == CANONICAL_CLAUDE_FABLE_MODEL), None)
            result["model"] = CANONICAL_CLAUDE_FABLE_MODEL
            if fable_row and fable_row.get("efforts"):
                result["effort"] = highest_effort(fable_row["efforts"])
            elif result.get("effort") not in EFFORT_ORDER:
                result["effort"] = "max"
            result["selection_evidence"] = "heavy_review_fable_pin"
    result["settings_revision"] = (settings or {}).get("settings_revision", 0)
    return result


def cached_selection(family, *, settings=None, env=None, tier=None, skill=None):
    """codex-discipline-2026-09-15 Wave 1.2: the last successful discovery for
    ``family`` regardless of age (``stale`` says whether it is past the TTL),
    or None when there has never been one. A pinned steward answers John from
    this and refreshes discovery off the request thread; it never blocks a
    send on a 25 s catalog probe."""
    active_env = os.environ if env is None else env
    with _LOCK:
        cached = _MEMORY.get(_cache_identity(family, active_env))
        if not cached:
            return None
        result = dict(cached)
        catalog_rows = list(result.pop("_catalog_rows", None) or [])
    pol = (settings or {}).get("model_policy", DEFAULT_POLICY) if isinstance(settings, dict) else DEFAULT_POLICY
    if catalog_rows and is_variable_strength_active(settings=settings, env=active_env, tier=tier, skill=skill):
        vs_cfg = effective_variable_strength_config(pol if isinstance(pol, dict) and pol.get("mode") == "variable_strength" else settings)
        eff_strength = resolve_skill_strength(
            skill=skill or active_env.get("ANCHOR_SKILL"),
            explicit_strength=tier or active_env.get("ANCHOR_STRENGTH") or active_env.get("TRIO_TIER"),
            inherited_strength=active_env.get("ANCHOR_INHERITED_STRENGTH"),
            cockpit_strength=active_env.get("ANCHOR_COCKPIT_STRENGTH"),
            default_strength=vs_cfg["default_strength"],
            settings=settings,
        )
        vs_selected = select_strength(family, catalog_rows, eff_strength, policy=vs_cfg)
        result.update(vs_selected)
        if (
            family == "claude"
            and eff_strength == "heavy"
            and vs_cfg["heavy"]["model_steps_below"] == 0
            and (
                any(r.get("model") == CANONICAL_CLAUDE_FABLE_MODEL for r in catalog_rows)
                or all(r.get("model") in _CLAUDE_MOVING_ALIASES for r in catalog_rows)
            )
        ):
            fable_row = next((r for r in catalog_rows if r.get("model") == CANONICAL_CLAUDE_FABLE_MODEL), None)
            result["model"] = CANONICAL_CLAUDE_FABLE_MODEL
            if fable_row and fable_row.get("efforts") and vs_cfg["heavy"]["effort_steps_below"] == 0 and vs_cfg["top_effort"] == "highest":
                result["effort"] = highest_effort(fable_row["efforts"])
        result["requested_policy"] = dict(pol) if isinstance(pol, dict) and pol.get("mode") == "variable_strength" else dict(VARIABLE_STRENGTH_POLICY)
    else:
        result["requested_policy"] = dict(DEFAULT_POLICY)
    result["settings_revision"] = (settings or {}).get("settings_revision", 0)
    result["stale"] = time.time() - result.get("discovered_at", 0) >= CAPABILITY_TTL_SECONDS
    return result


def launch_args(selection, *, subagents=True):
    family, model, effort = selection["family"], selection["model"], selection["effort"]
    if (family not in FAMILIES or not isinstance(model, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model)
            or effort not in EFFORT_ORDER):
        raise PolicyUnavailable(family, "invalid frozen launch selection")
    if family == "chatgpt":
        args = ["--model", model, "-c", f'model_reasoning_effort="{effort}"',
                "-c", 'forced_login_method="chatgpt"']
        if subagents:
            args += ["-c", f'agents.default_subagent_model="{model}"',
                     "-c", f'agents.default_subagent_reasoning_effort="{effort}"']
        return args
    if family == "claude":
        return ["--model", model, "--effort", effort]
    if family == "grok":
        return ["--model", model, "--reasoning-effort", effort]
    if family == "gemini":
        # agy names the effort inside the model id (gemini-3.8-flash-high); it has no separate effort flag for it.
        return ["--model", agy_model_id(model, effort)]
    raise PolicyUnavailable(family, "no supported highest-effort launch contract")


def attest_claude_fable_receipt(receipt, *, requested_model=None, role=None, label=None, tier=None):
    """Positive served-model attestation gate for heavy and variable-strength Claude seats."""
    if not isinstance(receipt, dict):
        raise PolicyUnavailable("claude", "turn receipt is missing or malformed", code="attestation_mismatch")
    out = dict(receipt)
    eff_role = role if role is not None else out.get("role")
    eff_label = label if label is not None else out.get("label")
    verification = is_claude_verification_role(role=eff_role, label=eff_label)
    norm_tier = normalize_strength(
        tier or out.get("requested_strength") or out.get("tier"),
        default=None,
    )
    raw_req = requested_model if (isinstance(requested_model, str) and requested_model.strip()) else out.get("requested_model")
    if verification and norm_tier in ("standard", "light"):
        req = (
            normalize_claude_fable_model(raw_req)
            if (isinstance(raw_req, str) and raw_req.strip())
            else CANONICAL_CLAUDE_STANDARD_MODEL
        )
    elif verification:
        req = CANONICAL_CLAUDE_FABLE_MODEL
    elif isinstance(raw_req, str) and raw_req.strip():
        req = normalize_claude_fable_model(raw_req)
    else:
        req = CANONICAL_CLAUDE_FABLE_MODEL
    raw_served = out.get("model_served")
    norm_served = normalize_claude_fable_model(raw_served) if isinstance(raw_served, str) and raw_served.strip() else None
    attested = out.get("model_attested") is True
    allow_fallback = (
        not verification
        and normalize_claude_fable_model(out.get("fallback_from_model")) == CANONICAL_CLAUDE_FABLE_MODEL
    )
    allow_quota_stepdown = (
        out.get("allow_quota_stepdown") is True
        and normalize_claude_fable_model(out.get("quota_stepdown_from")) == CANONICAL_CLAUDE_FABLE_MODEL
        and attested
        and norm_served == CANONICAL_CLAUDE_STANDARD_MODEL
    )
    if req == CANONICAL_CLAUDE_FABLE_MODEL and not allow_fallback and not allow_quota_stepdown:
        if attested and norm_served == CANONICAL_CLAUDE_FABLE_MODEL:
            out["model_served"] = CANONICAL_CLAUDE_FABLE_MODEL
        else:
            out["ok"] = False
            out["status"] = "attestation_mismatch"
            out["model_attested"] = bool(attested and isinstance(raw_served, str) and raw_served)
            out["error"] = (
                f"Claude positive attestation failed: requested {CANONICAL_CLAUDE_FABLE_MODEL}, "
                f"served {raw_served if attested and raw_served else 'unattested'}"
            )
            return out
    elif req == "sonnet" and verification:
        is_sonnet = norm_served == "sonnet" or bool(_DATED_CLAUDE_SONNET_RE.fullmatch(str(norm_served or "")))
        if not (attested and is_sonnet):
            out["ok"] = False
            out["status"] = "attestation_mismatch"
            out["model_attested"] = bool(attested and isinstance(raw_served, str) and raw_served)
            out["error"] = (
                f"Claude positive attestation failed: requested sonnet, "
                f"served {raw_served if attested and raw_served else 'unattested'}"
            )
            return out
    elif req == CANONICAL_CLAUDE_STANDARD_MODEL and verification:
        if attested and norm_served == CANONICAL_CLAUDE_STANDARD_MODEL:
            out["model_served"] = CANONICAL_CLAUDE_STANDARD_MODEL
        else:
            out["ok"] = False
            out["status"] = "attestation_mismatch"
            out["model_attested"] = bool(attested and isinstance(raw_served, str) and raw_served)
            out["error"] = (
                f"Claude positive attestation failed: requested {CANONICAL_CLAUDE_STANDARD_MODEL}, "
                f"served {raw_served if attested and raw_served else 'unattested'}"
            )
            return out
    elif attested and norm_served in (CANONICAL_CLAUDE_FABLE_MODEL, CANONICAL_CLAUDE_STANDARD_MODEL):
        out["model_served"] = norm_served
    out.setdefault("ok", True)
    out.setdefault("status", "success")
    return out
