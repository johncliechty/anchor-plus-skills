"""Skill Foundry v2 — Wave 4: the manifest REGISTRY + per-skill glue on the
generic runner.

Wave 3 generalized Anchor's ``gandalf.py`` consumer ADAPTER into the ONE
manifest-driven ``skill_runner``. This module is Wave 4 — the proof the
platform actually carries real skills:

* **gandalf re-expressed** as a manifest (:func:`gandalf_manifest`) plus the
  ``gandalf-staged`` executor mounted on the runner's injectable executor
  seam: Stage A stays gandalf's OWN map-reduce model read (through
  ``job_runner``); Stage B is the MANIFEST's ``host_cmd`` run by the runner's
  host-execution seam with the raw draft on stdin — exactly the legacy
  adapter's contract, so the graded output is BYTE-IDENTICAL for the same
  fixture project (proven by ``tests/test_foundry_runner_skills_w4.py``).
  NO behavior change: the defaults resolve through gandalf.py's OWN env seams
  (``ANCHOR_GANDALF_SKILL_DIR`` / ``ANCHOR_GANDALF_HOST_CMD``), so the legacy
  adapter and the runner expression always target the SAME skill + host.

* **jumper wired via a registry entry** (:func:`jumper_manifest`) — the HARD
  case: jumper COMPOSES gandalf. The composition is declared as manifest DATA
  (``composes: ["gandalf"]``) and resolved by :func:`run_skill`: every
  composed dependency runs FIRST through the SAME generic runner (so it
  auto-journals into its OWN skill dir), and its output is folded into the
  composer's host payload under ``payload["composed"][<dep>]``. A failed or
  cyclic composition fails the composer HONESTLY (and is journaled) — never
  fabricated, never an infinite recursion.

* **a 3rd skill wired in PURE DATA** (:func:`third_skill_manifest` —
  financial-analyst) under the declared line budget
  (``THIRD_SKILL_LINE_BUDGET``, measured by
  :func:`third_skill_wiring_lines`) — the marginal cost of putting one more
  skill on the platform is a few lines of manifest data, zero adapter code:
  no executor, no composition, just the runner's default host path.

All three auto-journal through the runner's Wave-2 seam (host-enforced —
done, failed, and refused ops alike). Discovery stays declare-then-resolve:
building the registry imports/executes NO skill code (the single-source
invariant: skills are CONSUMED from their canonical on-disk dirs, never
forked, never imported).

Wave 6 put **map.json v2 on the consumption path**: the canonical registry
build reads the Wave-5 graph (``foundry_map``) and REFUSES to build when the
registry and the graph disagree — a skill missing from the map, a declared
composition without its typed ``compose`` edge (the wrong/empty-edge case),
an edge the runner doesn't honor, or a tier mismatch
(:func:`verify_registry_against_map`). The drift gates themselves live in
``foundry_map_gates``.

Stdlib only (Anchor's no-dep rule) + the product seams ``foundry_map`` /
``gandalf`` / ``skill_runner``.
"""

import inspect
import os
from pathlib import Path

import foundry_map as _fm
import gandalf as _gandalf
import skill_runner as _sr


# ── Constants / seams ────────────────────────────────────────────────────────

#: Env var pointing at the canonical Skill Foundry skills root (the
#: single-source dirs the registry consumes; NEVER copied or forked).
SKILLS_ROOT_ENV = "ANCHOR_SKILLS_ROOT"
DEFAULT_SKILLS_ROOT = r"C:\dev\Skill Foundry\skills"

#: Env seams overriding the non-gandalf host commands (gandalf keeps its own
#: ``ANCHOR_GANDALF_HOST_CMD`` seam — the parity invariant).
JUMPER_HOST_CMD_ENV = "ANCHOR_JUMPER_HOST_CMD"
THIRD_HOST_CMD_ENV = "ANCHOR_FINANCIAL_ANALYST_HOST_CMD"

#: The Wave-4 3rd skill + its DECLARED wiring line budget: the whole wiring
#: diff for skill #3 is :func:`third_skill_manifest` (pure data), and the gate
#: test asserts its source stays under this budget.
THIRD_SKILL = "financial-analyst"
THIRD_SKILL_LINE_BUDGET = 25


def _skills_root() -> Path:
    raw = (os.environ.get(SKILLS_ROOT_ENV) or "").strip() or DEFAULT_SKILLS_ROOT
    return Path(raw)


def _base_caps(host_cmd) -> list:
    """The honest baseline capabilities for a host-run skill: the host binary
    itself (``exec:<argv0>``) + the skill's own protocol (``read:SKILL.md``).
    The runtime pre-flight probe refuses the run when either is unsatisfied."""
    if isinstance(host_cmd, str):
        parts = _sr._split_cmd(host_cmd)
    else:
        parts = [str(a) for a in (host_cmd or ())]
    caps = ["read:SKILL.md"]
    if parts:
        caps.insert(0, "exec:" + parts[0])
    return caps


# ── The registry manifests (pure data — declare-then-resolve) ────────────────

def gandalf_manifest(skill_dir=None, host_cmd=None, **over):
    """Gandalf RE-EXPRESSED as manifest data on the generic runner.

    Defaults resolve through gandalf.py's OWN seams (``_skill_dir()`` /
    ``_host_cmd_argv()``), so the legacy adapter and the runner expression
    always point at the SAME canonical skill dir and the SAME Stage-B host —
    the precondition for the byte-parity proof. The staged Stage-A model read
    is declared as the ``gandalf-staged`` executor kind (an ANCHOR adapter in
    this module, never skill code)."""
    d = str(skill_dir) if skill_dir else str(_gandalf._skill_dir())
    cmd = host_cmd if host_cmd else _gandalf._host_cmd_argv()
    m = {
        "skill": "gandalf",
        "skill_dir": d,
        "op_kind": "run",
        "host_cmd": cmd,
        "executor": "gandalf-staged",
        "output_contract": {"format": "json",
                            "required_keys": list(_gandalf._REQUIRED_TOP_KEYS)},
        "panel": {"title": "Gandalf", "icon": "🧙"},
        "journal": {"enabled": True},
        "tier": "standard",
        "capabilities": _base_caps(cmd),
        "activation": {"trigger": "first_run"},
        "timeout_s": _gandalf._timeout(),
    }
    m.update(over)
    return m


def jumper_manifest(skill_dir=None, host_cmd=None, **over):
    """Jumper wired via a registry entry — the HARD case: it COMPOSES gandalf.

    The composition is pure manifest DATA (``composes: ["gandalf"]``); the
    resolution lives in :func:`run_skill`, which runs each composed dependency
    through the SAME generic runner first (own journal, own contract) and
    folds the outputs into this skill's host payload. The default host command
    is the package's declared entry (``index.js``); an absent/failing host is
    an honest refusal/failure at run time, never fabricated."""
    d = str(skill_dir) if skill_dir else str(_skills_root() / "jumper")
    cmd = host_cmd or (os.environ.get(JUMPER_HOST_CMD_ENV) or "").strip() \
        or "node {skill_dir}/index.js"
    m = {
        "skill": "jumper",
        "skill_dir": d,
        "op_kind": "run",
        "host_cmd": cmd,
        "composes": ["gandalf"],
        "output_contract": {"format": "json"},
        "panel": {"title": "Jumper", "icon": "🪂"},
        "journal": {"enabled": True},
        "tier": "standard",
        "capabilities": _base_caps(cmd),
        "activation": {"trigger": "first_run"},
    }
    m.update(over)
    return m


def third_skill_manifest(skill_dir=None, host_cmd=None, **over):
    """The Wave-4 3rd skill (financial-analyst) — wired in PURE DATA.

    This function IS the whole wiring diff for skill #3 (no executor, no
    composition — the runner's default host path); the line-budget gate
    counts exactly this source."""
    d = str(skill_dir) if skill_dir else str(_skills_root() / THIRD_SKILL)
    cmd = host_cmd or (os.environ.get(THIRD_HOST_CMD_ENV) or "").strip() \
        or "python {skill_dir}/agent_interface.py"
    m = {
        "skill": THIRD_SKILL,
        "skill_dir": d,
        "op_kind": "run",
        "host_cmd": cmd,
        "output_contract": {"format": "json"},
        "panel": {"title": "Financial Analyst", "icon": "📊"},
        "journal": {"enabled": True},
        "tier": "standard",
        "capabilities": _base_caps(cmd),
        "activation": {"trigger": "first_run"},
    }
    m.update(over)
    return m


def third_skill_wiring_lines() -> int:
    """The 3rd skill's wiring size in source lines — the declared-budget gate
    measures the marginal cost of adding one more skill to the platform."""
    return len(inspect.getsource(third_skill_manifest).splitlines())


def registry_manifests(overrides=None) -> list:
    """The Wave-4 registry: gandalf + jumper + the 3rd skill, as pure data.

    ``overrides`` maps a skill name to kwargs for its manifest builder (how
    the hermetic tests point every entry at temp skill dirs + stub hosts).
    Building the registry imports/executes NO skill code."""
    ov = overrides or {}
    return [
        gandalf_manifest(**ov.get("gandalf", {})),
        jumper_manifest(**ov.get("jumper", {})),
        third_skill_manifest(**ov.get(THIRD_SKILL, {})),
    ]


def verify_registry_against_map(manifests, map_doc) -> list:
    """Cross-check the registry against map.json v2 → problem list.

    The Wave-6 consumption contract (the real consumer READS the graph, so a
    wrong or empty edge breaks a build, loudly):

    * the map itself must validate clean (``map-invalid:*`` — an invalid
      graph is never consumed);
    * every registry skill must exist in the map by name
      (``skill-not-in-map``);
    * a manifest's declared ``composes`` must be backed, dependency for
      dependency, by a typed ``compose`` edge in the map
      (``compose-edge-missing`` — the EMPTY/wrongly-typed/wrong-target edge
      case), and every ``compose`` edge the map declares for that skill must
      appear in the manifest (``compose-edge-undeclared`` — the graph and
      the runner may not silently disagree in either direction);
    * the manifest's runner ``tier`` must match the map's
      (``tier-mismatch``)."""
    problems = _fm.validate_map(map_doc)
    if problems:
        return ["map-invalid:%s" % p for p in problems]
    by_name = {s["name"]: s for s in map_doc["skills"]}
    by_ref = {s["ref"]: s for s in map_doc["skills"]}
    out = []
    for m in manifests:
        name = str((m or {}).get("skill") or "") if isinstance(m, dict) else ""
        entry = by_name.get(name)
        if entry is None:
            out.append("skill-not-in-map:%s" % (name or "?"))
            continue
        tier = m.get("tier")
        if tier is not None and entry["tier"] != tier:
            out.append("tier-mismatch:%s:map=%r,manifest=%r"
                       % (name, entry["tier"], tier))
        declared = [str(c) for c in (m.get("composes") or ())]
        edge_names = [by_ref[e["to"]]["name"] for e in entry["edges"]
                      if e["type"] == "compose"]
        for dep in declared:
            if dep not in edge_names:
                out.append("compose-edge-missing:%s->%s" % (name, dep))
        for dep in edge_names:
            if dep not in declared:
                out.append("compose-edge-undeclared:%s->%s" % (name, dep))
    return out


def build_registry_dispatch(manifests=None, map_doc=None) -> dict:
    """Declare-then-resolve the registry into a runner dispatch table.

    Wave 6 put map.json v2 ON THE CONSUMPTION PATH: the canonical build
    (``manifests=None``) — and any build handed a ``map_doc`` explicitly —
    verifies the registry against the graph FIRST and refuses to build on
    any disagreement (``ValueError`` naming every problem; a wrong or empty
    edge breaks the build here, before a dispatch table exists). A consumed
    build's entries then carry the map's pin under ``entry["map"]``
    (ref/version/status/tier — graph data genuinely read into the build
    product). An explicit-manifests build WITHOUT a map stays the pure
    Wave-3/4 seam (hermetic subset/fixture dispatches)."""
    consume = manifests is None or map_doc is not None
    if manifests is None:
        manifests = registry_manifests()
    if consume:
        if map_doc is None:
            map_doc = _fm.load_map()
        problems = verify_registry_against_map(manifests, map_doc)
        if problems:
            raise ValueError("map-consumption-refused: "
                             + "; ".join(problems))
    dispatch = _sr.build_dispatch(manifests)
    if consume:
        by_name = {s["name"]: s for s in map_doc["skills"]}
        for name, entry in dispatch.items():
            skill = by_name[name]
            entry["map"] = {"ref": skill["ref"], "version": skill["version"],
                            "status": skill["status"], "tier": skill["tier"]}
    return dispatch


# ── Executors (ANCHOR adapters mounted on the runner's executor seam) ────────

def _gandalf_staged_executor(entry, payload):
    """The staged gandalf pipeline on the runner's executor seam.

    Stage A — gandalf's OWN map-reduce model read (through ``job_runner``,
    honoring every existing seam: ``ANCHOR_RUNNER_CMD``, sharding, fusion) —
    unless the caller supplied ``payload["raw_draft"]`` directly. Stage B —
    the MANIFEST's ``host_cmd`` via the runner's host-execution seam, the raw
    draft as the stdin payload. That is byte-for-byte the legacy adapter's
    Stage-B contract (same draft, same host argv, same serialization), so the
    graded output is identical; ``run_op``'s output contract then applies the
    same 9-required-keys check the legacy ``_run_stage_b`` enforced.

    Raises ``ValueError`` with the honest stage reason on failure — ``run_op``
    records it as a failed (and journaled) op. Never fabricates."""
    p = payload if isinstance(payload, dict) else {}
    draft = p.get("raw_draft")
    if not isinstance(draft, dict):
        folder = str(p.get("folder") or "")
        if not folder:
            raise ValueError("gandalf-payload-missing-folder")
        draft, reason = _gandalf._run_stage_a_mapreduce(folder,
                                                        env=p.get("env"))
        if not isinstance(draft, dict):
            raise ValueError(reason or "stage-a-failed")
    stdout_text, reason = _sr._execute_host(entry, draft)
    if reason:
        raise ValueError(reason)
    return stdout_text


def _composing_executor(dispatch, composes, base=None, chain=()):
    """Build the executor for a manifest that DECLARES composition.

    Each composed dependency runs FIRST through the generic runner
    (:func:`run_skill`, so it activates, pre-flights, journals, and honors its
    own output contract); the outputs are folded into the composer's host
    payload under ``composed``. A dependency already on the in-flight chain is
    a composition CYCLE → honest failure. When ``base`` is set (a declared
    executor kind), it runs the composer's own leg; else the manifest's host
    runs via the runner's host-execution seam."""
    def _executor(entry, payload):
        composed = {}
        for dep in composes:
            if dep in chain:
                raise ValueError("composition-cycle:"
                                 + "->".join(chain + (dep,)))
            res = run_skill(dispatch, dep, payload=payload, _chain=chain)
            if not res.get("ok"):
                raise ValueError("composed-skill-failed:%s:%s"
                                 % (dep, res.get("reason")))
            composed[dep] = res.get("output")
        if isinstance(payload, dict):
            p = dict(payload)
        elif payload is None:
            p = {}
        else:
            p = {"payload": payload}
        p["composed"] = composed
        if base is not None:
            return base(entry, p)
        stdout_text, reason = _sr._execute_host(entry, p)
        if reason:
            raise ValueError(reason)
        return stdout_text
    return _executor


#: Executor KINDS a manifest may declare via its ``executor`` field. These are
#: Anchor-side adapters (this module) — resolving a kind never imports or
#: executes skill code.
EXECUTOR_KINDS = {
    "gandalf-staged": _gandalf_staged_executor,
}


def resolve_executor(dispatch, skill, _chain=()):
    """Resolve the executor for one dispatch entry from its MANIFEST data.

    ``None`` for an unknown skill or a plain host-run manifest (the runner's
    default path). A declared-but-unknown executor kind raises ``ValueError``
    loudly — a manifest naming an adapter that does not exist must break the
    caller, not silently fall back to the wrong execution path."""
    entry = dispatch.get(str(skill))
    if entry is None:
        return None
    kind = entry["manifest"].get("executor")
    base = None
    if kind is not None:
        base = EXECUTOR_KINDS.get(str(kind))
        if base is None:
            raise ValueError("unknown executor kind %r for skill %s"
                             % (kind, skill))
    composes = tuple(str(c) for c in (entry["manifest"].get("composes") or ()))
    if composes:
        return _composing_executor(dispatch, composes, base=base,
                                   chain=_chain)
    return base


def run_skill(dispatch, skill, *, payload=None, confirm_token=None,
              write_targets=None, _chain=()):
    """Run ONE registry skill through the generic runner.

    The Wave-4 entry point: resolves the manifest's declared executor kind +
    composition, then delegates to ``skill_runner.run_op`` — so every gate
    (lazy activation, pre-flight probe, mutate confirm/scope) and the Wave-2
    auto-journal seam apply unchanged. ``_chain`` is internal (the in-flight
    composition chain for cycle detection)."""
    name = str(skill)
    executor = resolve_executor(dispatch, name, _chain=_chain + (name,))
    return _sr.run_op(dispatch, name, payload=payload,
                      confirm_token=confirm_token,
                      write_targets=write_targets, executor=executor)
