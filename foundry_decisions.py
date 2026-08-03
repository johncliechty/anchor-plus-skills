"""Skill Foundry v2 — the four Phase-0 decisions, encoded as CODE (Wave 1).

This module is the machine-readable form of the four de-risking DECISION
RECORDS the Crucible Master Plan requires Phase 0 to produce
(``planning/foundry-v2/DR-01..04-*.md`` hold the human-readable rationale).
Later waves IMPORT these constants — that puts the decisions on the
consumption path, so a wrong or missing decision breaks a build instead of
rotting as prose:

* Wave 2 (journaling seam)   → ``JOURNAL_ENTRY_FIELDS``, ``PROCESS_TELEMETRY_DEPTH``,
                               ``SIDE_CHANNEL_DESIGN``
* Wave 3 (generic runner)    → ``OP_KINDS``, ``ISOLATION_RUNTIME``,
                               ``ISOLATION_COMPENSATING_CONTROLS``
* Wave 6 (sleep gate)        → ``TEST_PROVENANCE_CLASSES``, ``PROMOTION_ACCEPTED_CLASSES``
* Waves 9-12 (control plane + GUI) → ``ANCHOR_API_CONTRACT`` / ``MUTATIVE_VERBS``

Anchor's no-dependency rule applies: stdlib only, and nothing here imports
anything at all — pure data + one small validator.
"""

# ---------------------------------------------------------------------------
# North-Star clause tags (the anti-drift anchor every decision traces to).
# Source: C:/dev/plans/2026-07-foundry-v2/NORTH-STAR.md (LOCKED 2026-07-06).
# ---------------------------------------------------------------------------

NORTH_STAR_DOC = "C:/dev/plans/2026-07-foundry-v2/NORTH-STAR.md"

NS_MANIFEST_RUNNER = "NS#1-manifest-driven-skill-runner"
NS_HOST_ENFORCED_JOURNAL = "NS#2-host-enforced-journaling"
NS_SLEEP_LOOP_TURNS_OVER = "NS#3-test-gated-sleep-loop"
NS_KNOWLEDGE_GRAPH = "NS#4-knowledge-graph-library"
NS_GUI_DRIVES_REAL_MACHINERY = "NS#5-gui-drives-real-machinery"
NS_SAFETY_ENVELOPE = "NS#5-reaper-safety-envelope"


# ---------------------------------------------------------------------------
# Decision 1 — ANCHOR_API_CONTRACT (DR-01)
# The two-column contract: what the Foundry GUI drives NATIVELY on Anchor's
# existing read/execute surface, vs. the MUTATIVE verbs Anchor lacks that the
# Phase-6 control plane (Waves 9-10) must supply as manifest-registered
# ``mutate`` ops. "Mutations are runs, not endpoints."
# ---------------------------------------------------------------------------

# Column A — native READ/EXECUTE capabilities (already served by Anchor's
# job_runner / session / artifact surface; the GUI is a stateless client).
NATIVE_READ_EXECUTE = {
    "run_skill_job": (
        "POST /api/rnd/launch_lane",       # one-shot lane job via job_runner
        "POST /api/rnd/run_deliverable",   # per-type deliverable run contract
        "POST /api/rnd/cancel_job",        # tree-kill one job
    ),
    "monitor_job": (
        "GET /api/rnd/tail",               # cursor-stable incremental job log
    ),
    "live_session": (
        "POST /api/rnd/term_start",
        "POST /api/rnd/term_input2",
        "POST /api/rnd/term_resize",
        "POST /api/rnd/term_kill",
        "POST /api/rnd/term_close",
        "GET /api/rnd/term_ws",            # RFC-6455 PTY transport
        "GET /api/rnd/term_stream2",       # SSE fallback transport
        "GET /api/rnd/term_sessions",      # SAFE session projection
    ),
    "read_artifacts": (
        "GET /artifact/<pid>?path=<rel>",  # traversal-safe artifact serve
        "GET /report/<pid>/<lane>/<job_id>",
        "GET /summary/<pid>/<lane>/<session_id>",
        "GET /api/rnd/session_summary",
    ),
    "interactive_gate": (
        "POST /api/rnd/answer_gate",       # AskUserQuestion gate answers
    ),
    "auth": (
        "ANCHOR_TOKEN",                    # token-authed POSTs; GETs via ?token=
    ),
}

# Column B — the MUTATIVE verbs Anchor's execution API lacks.  This is the
# Phase-6 op inventory: every entry ships as a manifest-registered ``mutate``
# op on the Wave-3 generic runner, dispatched through job_runner (therefore
# confirm-token-gated, write-scoped, and auto-journaled).  ``wave`` is the
# frozen implementation-plan wave that delivers the op.
MUTATIVE_VERBS = {
    "foundry.scaffold_skill": {
        "wave": 9,
        "summary": "create a new skill on disk from a template (SKILL.md, "
                   "manifest, journal dir, per-skill North-Star stub), "
                   "register it in map.json v2, commit on a branch; "
                   "idempotent, refuses to overwrite",
        "confirm_gated": True,
        "write_scope": "Skill Foundry/skills/<new-skill>/ + map.json",
    },
    "foundry.gen_manifest": {
        "wave": 9,
        "summary": "derive/update a skill's runner manifest, validated "
                   "against the Wave-3 schema before write",
        "confirm_gated": True,
        "write_scope": "Skill Foundry/skills/<skill>/manifest",
    },
    "foundry.edit_north_star": {
        "wave": 10,
        "summary": "the ONLY sanctioned per-skill North-Star mutation path: "
                   "proposal-diff -> explicit human confirm token -> apply "
                   "as a branch commit with the prior version retained",
        "confirm_gated": True,
        "write_scope": "Skill Foundry/skills/<skill>/NORTH-STAR.md",
    },
    "foundry.register_autoload": {
        "wave": 10,
        "summary": "the auto-load registration op set that makes every "
                   "foundry skill clickable inside Anchor, driven from "
                   "map.json v2 (never hand-wired)",
        "confirm_gated": True,
        "write_scope": "Anchor skill-registration state",
    },
    "foundry.apply_sleep_improvement": {
        "wave": 6,
        "summary": "the Phase-4 sleep-session apply: plan-mode PROPOSAL "
                   "artifact -> separate confirm-gated apply-on-branch "
                   "behind the test gate, frozen rollback-able baseline",
        "confirm_gated": True,
        "write_scope": "target skill dir, on a branch behind the test gate",
    },
}

ANCHOR_API_CONTRACT = {
    "native_read_execute": NATIVE_READ_EXECUTE,
    "mutative_verbs": MUTATIVE_VERBS,
    "principle": "mutations are runs, not endpoints: no new server, DB, or "
                 "store; every mutation is a confirm-gated runner op through "
                 "job_runner, never a GUI-side write",
}

# The op kinds the Wave-3 manifest schema must support (Phase-2 hook that the
# Phase-6 control-plane ops plug into).
OP_KINDS = ("run", "mutate")


# ---------------------------------------------------------------------------
# Decision 2 — ISOLATION_RUNTIME (DR-02)
# The Master Plan asks for a named OS-level primitive with a measured
# cost/latency envelope, OR "an explicit 'permissions stay advisory for v2'
# honest downgrade".  v2 takes the sanctioned downgrade: foundry skills are
# agentic CLI runs (claude.exe / agy.exe subprocesses) that must read/write
# the real project tree and run git — no evaluated OS-level primitive can
# enclose that workload on this host without breaking Anchor's stdlib-only /
# portability rules or the single-source skill-consumption invariant.
# ---------------------------------------------------------------------------

PERMISSIONS_ADVISORY_V2 = "PERMISSIONS_ADVISORY_V2"

ISOLATION_RUNTIME = PERMISSIONS_ADVISORY_V2

# Cost/latency envelope: the chosen posture plus every evaluated candidate.
# Candidate latency figures are literature-tier estimates (evidence tier
# CLAIMED); the ineligibility facts are OBSERVED host facts.
ISOLATION_COST_ENVELOPE = {
    "chosen": {
        "runtime": PERMISSIONS_ADVISORY_V2,
        "startup_latency_ms": 0,        # advisory permissions add no spawn cost
        "per_run_overhead_ms": 0,
        "lazy_activation_conflict": False,  # zero cost => no tension with
                                            # lazy/budgeted activation (C2)
        "evidence_tier": "OBSERVED",
    },
    "candidates": {
        "wasm_wasmtime": {
            "startup_latency_ms": 10,   # CLAIMED (literature; unmeasured here)
            "eligible": False,
            "why_not": "cannot host claude.exe/agy.exe agentic subprocesses; "
                       "skills are not WASM modules",
        },
        "container_docker_wsl2": {
            "startup_latency_ms": 3000,  # CLAIMED (cold-start, literature)
            "eligible": False,
            "why_not": "requires Docker Desktop/WSL2 — a heavy non-stdlib "
                       "host dependency; violates Anchor's 'any machine with "
                       "Python 3.8+' rule and the single-source skill dir",
        },
        "microvm_firecracker": {
            "startup_latency_ms": 125,  # CLAIMED (literature)
            "eligible": False,
            "why_not": "Linux/KVM only; host is Windows 11",
        },
        "deno_permissions": {
            "startup_latency_ms": 50,   # CLAIMED (literature)
            "eligible": False,
            "why_not": "governs only Deno-runtime code; foundry skills are "
                       "not Deno programs",
        },
    },
}

# The downgrade is honest, not naked: permission enforcement moves to the ONE
# seam every run already passes through (the Wave-3 generic runner), plus the
# platform's existing containment rails.  Later waves import this list and
# must keep every control true.
ISOLATION_COMPENSATING_CONTROLS = (
    "declared capabilities per manifest + runtime pre-flight probe (Wave 3)",
    "mutate ops require an explicit confirm token (Wave 3)",
    "mutate ops declare a write-scope; out-of-scope writes are refused (Wave 3)",
    "mutations apply on a git branch/worktree, never straight to main",
    "host-enforced journaling of every op, mutative ops included (Wave 2)",
    "grep/drift gates catch out-of-band write paths (Waves 2, 8, 10)",
    "reaper armed to >=FREEZE + per-host concurrency budget before "
    "default-on fan-out (Wave 13)",
)


# ---------------------------------------------------------------------------
# Decision 3 — TEST_PROVENANCE_CLASSES (DR-03)
# The taxonomy that lets a sleep improvement be gated without circular
# validation (an agent grading its own unverified test is the failure mode).
# Trust ceilings are a closed ladder; the sleep gate (Wave 6) may never trust
# a test ABOVE its class ceiling, and the human remains the promotion
# authority for every class.
# ---------------------------------------------------------------------------

# The trust ladder, weakest to strongest.
TRUST_REJECTED = "REJECTED"            # may not gate anything
TRUST_ADVISORY = "ADVISORY"            # may inform, never gate
TRUST_PROMOTION_GATE = "PROMOTION_GATE"  # may gate a promotion (human approves)

TRUST_LADDER = (TRUST_REJECTED, TRUST_ADVISORY, TRUST_PROMOTION_GATE)

TEST_PROVENANCE_CLASSES = {
    "human_authored": {
        "trust_ceiling": TRUST_PROMOTION_GATE,
        "applies_to": ("code", "prose"),
        "requirements": ("authored or materially reviewed line-by-line by a "
                         "human",),
    },
    "agent_cross_model_verified": {
        "trust_ceiling": TRUST_PROMOTION_GATE,
        "applies_to": ("code",),
        "requirements": ("generated by one model family, independently "
                         "verified by a DIFFERENT model family",
                         "held-out: the test never ran inside the loop that "
                         "produced the improvement"),
    },
    "agent_human_ratified": {
        "trust_ceiling": TRUST_PROMOTION_GATE,
        "applies_to": ("code", "prose"),
        "requirements": ("agent-generated, then explicitly ratified by a "
                         "human before first gating use",),
    },
    "frozen_benchmark_delta": {
        "trust_ceiling": TRUST_PROMOTION_GATE,
        "applies_to": ("prose",),
        "requirements": ("before/after delta on a benchmark FROZEN before "
                         "the improvement was proposed",
                         "the ONLY accepted gate for prose lessons"),
    },
    # Encoded explicitly so the anti-circular rule is machine-checkable, not
    # implied by omission: an agent-generated test with no independent check
    # is the circular-validation failure mode and gates NOTHING.
    "agent_unverified": {
        "trust_ceiling": TRUST_REJECTED,
        "applies_to": (),
        "requirements": (),
    },
}

# The classes v2 ACCEPTS for promotion (Wave 6 imports this set).
PROMOTION_ACCEPTED_CLASSES = (
    "human_authored",
    "agent_cross_model_verified",
    "agent_human_ratified",
    "frozen_benchmark_delta",
)


# ---------------------------------------------------------------------------
# Decision 4 — PROCESS_TELEMETRY_DEPTH + the droppable side-channel (DR-04)
# How far capture goes beyond the outcome seam, and where the heavy bytes
# live so the always-on skeleton entry stays small.
# ---------------------------------------------------------------------------

# Depth = OUTCOME_PLUS_RECOVERY: the 7-field OUTCOME skeleton is captured on
# every host-mediated run (host-enforced, never honor-system), PLUS depth-1
# process telemetry (sub-agent call counts, failed recoveries, retries) —
# but the depth-1 detail and all heavy payloads route to the DROPPABLE side
# channel, never into the skeleton.  Full step-by-step process tracing is
# explicitly OUT of scope for v2.
PROCESS_TELEMETRY_DEPTH = "OUTCOME_PLUS_RECOVERY"

# The 7 fields of the always-on skeleton journal entry (Wave 2 seam).
JOURNAL_ENTRY_FIELDS = (
    "provenance",        # who/what produced the run (per DR-03 taxonomy)
    "operation_kind",    # run | mutate (per DR-01 op kinds)
    "model_cost",        # model + billed cost + cache tokens
    "inputs_ref",        # reference into the side channel, never inline bulk
    "outputs_ref",       # reference into the side channel, never inline bulk
    "verdict_timing",    # verdict + timing
    "outcome_linkage",   # outcome + linkage to related runs/artifacts
)

SIDE_CHANNEL_DESIGN = {
    "location": "<skill_dir>/journal/side/<run_id>/",
    "droppable": True,   # deleting the side channel NEVER breaks the skeleton
    "referenced_by": ("inputs_ref", "outputs_ref"),
    "holds": ("full transcripts", "per-shard drafts", "sub-agent call detail",
              "failed-recovery traces", "raw model I/O"),
    "skeleton_max_bytes": 2048,  # the always-on entry stays this small
    "skeleton_survives_drop": True,  # kernel parses skeleton entries only
}


# ---------------------------------------------------------------------------
# Wave 11 (Phase 8 — safety before scale): NATIVE BUILT-INS.
# The process-lifecycle reaper (zombie-hunter + its liveness/arming/freeze
# modules) is a NATIVE, in-process subsystem — deliberately NOT forced into
# the skill-action manifest registry.  It must run before/without any skill
# dispatch (the boot daemon), its authority comes from the arming ladder +
# the token-authed control plane (never a runner confirm token), and
# manifest-registering it would put kill authority behind the very surface
# it polices.  ``skill_runner`` CONSUMES this tuple and refuses a manifest
# that tries to register one of these names as a skill (name-normalized:
# lowercase, "-" == "_"), so the decision is enforced on the dispatch path.
# ---------------------------------------------------------------------------

NATIVE_BUILTINS = (
    "zombie_hunter",
    "reaper",
    "reaper_arming",
    "freeze_state",
    "proc_probe",
)

#: The North-Star clause the native-built-in decision traces to.
NATIVE_BUILTINS_TRACE = (NS_SAFETY_ENVELOPE,)


# ---------------------------------------------------------------------------
# The decision registry — one record per Phase-0 gap, each North-Star-tagged.
# Later phases cite decisions by ``id``; the Wave-1 gate asserts every record
# carries a non-empty ``traces_to_north_star``.
# ---------------------------------------------------------------------------

DECISIONS = (
    {
        "id": "DR-01",
        "title": "Anchor API contract: native read/execute vs. control-plane "
                 "mutative verbs",
        "decision": ANCHOR_API_CONTRACT,
        "rationale_doc": "planning/foundry-v2/DR-01-anchor-api-contract.md",
        "traces_to_north_star": (NS_GUI_DRIVES_REAL_MACHINERY,
                                 NS_MANIFEST_RUNNER),
        "consumed_by_waves": (3, 9, 10, 11, 12),
    },
    {
        "id": "DR-02",
        "title": "Isolation runtime: explicit PERMISSIONS_ADVISORY_V2 "
                 "downgrade + compensating controls",
        "decision": {
            "runtime": ISOLATION_RUNTIME,
            "cost_envelope": ISOLATION_COST_ENVELOPE,
            "compensating_controls": ISOLATION_COMPENSATING_CONTROLS,
        },
        "rationale_doc": "planning/foundry-v2/DR-02-isolation-runtime.md",
        "traces_to_north_star": (NS_MANIFEST_RUNNER, NS_SAFETY_ENVELOPE),
        "consumed_by_waves": (3, 13),
    },
    {
        "id": "DR-03",
        "title": "Test/lesson provenance classes with per-class trust "
                 "ceilings (anti-circular-validation)",
        "decision": {
            "classes": TEST_PROVENANCE_CLASSES,
            "promotion_accepted": PROMOTION_ACCEPTED_CLASSES,
            "trust_ladder": TRUST_LADDER,
        },
        "rationale_doc": "planning/foundry-v2/DR-03-test-provenance.md",
        "traces_to_north_star": (NS_SLEEP_LOOP_TURNS_OVER,),
        "consumed_by_waves": (6, 14),
    },
    {
        "id": "DR-04",
        "title": "Process-telemetry depth + droppable side-channel design",
        "decision": {
            "depth": PROCESS_TELEMETRY_DEPTH,
            "journal_entry_fields": JOURNAL_ENTRY_FIELDS,
            "side_channel": SIDE_CHANNEL_DESIGN,
        },
        "rationale_doc": "planning/foundry-v2/DR-04-process-telemetry.md",
        "traces_to_north_star": (NS_HOST_ENFORCED_JOURNAL,),
        "consumed_by_waves": (2, 5),
    },
)


def validate_decisions():
    """Return a list of problems with the decision registry (empty = valid).

    Later waves may call this as a cheap import-time drift gate: a decision
    that loses its North-Star trace, its rationale doc pointer, or its
    machine-readable payload fails loudly here.
    """
    problems = []
    seen_ids = set()
    for record in DECISIONS:
        rid = record.get("id", "<missing id>")
        if rid in seen_ids:
            problems.append("duplicate decision id: %s" % rid)
        seen_ids.add(rid)
        if not record.get("traces_to_north_star"):
            problems.append("%s: missing traces_to_north_star tag" % rid)
        if not record.get("rationale_doc"):
            problems.append("%s: missing rationale_doc pointer" % rid)
        if not record.get("decision"):
            problems.append("%s: empty decision payload" % rid)
        if not record.get("consumed_by_waves"):
            problems.append("%s: no consuming wave declared" % rid)
    for expected in ("DR-01", "DR-02", "DR-03", "DR-04"):
        if expected not in seen_ids:
            problems.append("missing decision record: %s" % expected)
    if ISOLATION_RUNTIME != PERMISSIONS_ADVISORY_V2 and not str(
            ISOLATION_RUNTIME).strip():
        problems.append("ISOLATION_RUNTIME is unset")
    for cls, spec in TEST_PROVENANCE_CLASSES.items():
        if spec.get("trust_ceiling") not in TRUST_LADDER:
            problems.append("provenance class %s: trust ceiling not on the "
                            "ladder" % cls)
    for accepted in PROMOTION_ACCEPTED_CLASSES:
        if accepted not in TEST_PROVENANCE_CLASSES:
            problems.append("accepted class %s not in the taxonomy" % accepted)
        elif (TEST_PROVENANCE_CLASSES[accepted]["trust_ceiling"]
              == TRUST_REJECTED):
            problems.append("accepted class %s has a REJECTED ceiling"
                            % accepted)
    return problems
