#!/usr/bin/env python3
"""Anchor ⇄ Gandalf integration — the two-stage runtime engine (v1, Wave 1).

Give each Anchor project an honest "what's really going on here" read by invoking
the **existing** Gandalf skill through Anchor's runner seam, then grading the
result with Gandalf's **own** Tier-1 host. Anchor is integration glue only —
Gandalf's reasoning + grading are never reimplemented here.

The flow is two stages, both injectable + STUBBED in tests (never real claude /
real node):

  Stage A (model) — build a prompt = the Gandalf ``SKILL.md`` protocol (read from
    ``ANCHOR_GANDALF_SKILL_DIR``) + "analyze the project at <folder> and emit ONLY
    the RAW draft JSON per ``runtime/RAW-DRAFT-CONTRACT.md`` as your final message;
    do NOT self-assign tiers/stamps". Launched through ``job_runner`` /
    ``ANCHOR_RUNNER_CMD`` with ``cwd=folder``, ``--add-dir folder``, an
    ``ANCHOR_GANDALF_TIMEOUT`` (default 600s), and the forwarded env. The raw
    draft is recovered via ``job_runner.extract_assistant_text`` + parsing the
    last balanced top-level JSON object.

  Stage B (host) — run ``ANCHOR_GANDALF_HOST_CMD`` (default
    ``node "<skilldir>/runtime/gandalf-run.mjs"``) feeding the raw draft on stdin,
    capturing the GRADED ``advisor-output.json`` on stdout. ``node`` is an
    EXTERNAL CLI through a seam (like git/gh) — never a Python dep. A parse
    failure / non-zero exit / absent host is an honest **error run**
    (``ok:false``, ``reason``) — never fabricated, never raised to the caller,
    never crashes a render.

Store layout (decision #3 — served artifacts MUST live at PROJECT ROOT because
``report_viewer.resolve_project_artifact`` hard-rejects any path under
``.anchor``):

  <folder>/gandalf/run-<ts>/report.md          (full rendered schema)
  <folder>/gandalf/run-<ts>/exec-summary.md     (verdict + top findings/elevations)
  <folder>/gandalf/run-<ts>/advisor-output.json (the graded schema, audit truth)

The internal INDEX lives at ``.anchor/projects/<id>/gandalf/index.json`` (read
directly by the GET endpoint, never via ``/artifact``), newest-first, stamped
with ``GANDALF_INDEX_SCHEMA_VERSION``, written under ``paths.WRITE_LOCK``.

Stdlib only. No third-party imports.
"""

import fnmatch
import json
import os
import re
import shutil
import subprocess
import threading
import time
from pathlib import Path

import paths as _paths
import job_runner as _jr
import lanes as _lanes
import summarizer as _summarizer
import foundry_journal as _fj


# ── Active-run registry (Wave 1: active cancel) ──────────────────────────────
#: In-flight Gandalf runs, keyed by run_id → {"job_id", "proc", "cancelled"}.
#: Mutated only under ``_ACTIVE_RUNS_LOCK``. ``run_gandalf`` registers a run on
#: start and pops it in its ``finally``; ``cancel_run`` flips ``cancelled`` and
#: tree-kills the live Stage-A job / Stage-B subprocess.
_ACTIVE_RUNS: dict = {}
_ACTIVE_RUNS_LOCK = threading.Lock()


# ── Constants / seams ────────────────────────────────────────────────────────

#: Env var pointing at the on-disk Gandalf skill folder (its ``SKILL.md`` +
#: ``runtime/gandalf-run.mjs`` live here). Resolves BLOCKER B — ``/gandalf`` is
#: not auto-discoverable, so the protocol is read from this dir.
SKILL_DIR_ENV = "ANCHOR_GANDALF_SKILL_DIR"
# No host default — resolve package-local or env (ship-safe for collaborators).
DEFAULT_SKILL_DIR = ""

#: Env var overriding the Stage-B host command. When unset, the default is
#: ``node "<skilldir>/runtime/gandalf-run.mjs"``. ``node`` is an external CLI
#: through a seam (like git/gh) — never a Python dep. Tests point this at a
#: Python stub emitting a canned graded advisor-output.json.
HOST_CMD_ENV = "ANCHOR_GANDALF_HOST_CMD"

#: Env var overriding the Stage-A model timeout (seconds). Pointing Gandalf at a
#: whole project folder is an unbounded agentic run, so this is GENEROUS and
#: Gandalf-specific — NOT summarizer's 60s. An honest degraded run on timeout,
#: never a hang.
TIMEOUT_ENV = "ANCHOR_GANDALF_TIMEOUT"
# 900s (was 600): a real run on a LARGE repo (aurora) landed at ~515s with
# run-to-run variance that tripped the old 600s ceiling. The run is a background
# daemon (never blocks a render), so a generous default just lets big repos finish;
# override per-run via ANCHOR_GANDALF_TIMEOUT.
DEFAULT_TIMEOUT = 900.0

# Gandalf-Heavy (Fable-5 + its OWN whole-tree 5:1 Gemini adversarial reviews) is
# far slower than a standard Opus read, so it routinely blew past the single
# shared ceiling — hitting the incomplete/tree-kill path BEFORE the summary was
# written (report present, exec-summary missing). Heavy therefore gets a
# multiplied ceiling: an explicit ANCHOR_GANDALF_TIMEOUT_HEAVY wins, else
# base × ANCHOR_GANDALF_TIMEOUT_HEAVY_MULT (default 2.5×). Env-tunable.
TIMEOUT_HEAVY_ENV = "ANCHOR_GANDALF_TIMEOUT_HEAVY"
TIMEOUT_HEAVY_MULT_ENV = "ANCHOR_GANDALF_TIMEOUT_HEAVY_MULT"
HEAVY_TIMEOUT_MULT = 2.5

# ── Tier (regular vs Gandalf-Heavy) ──────────────────────────────────────────
#: The canonical Gandalf reasoner seat is Claude (the skill run by a Claude agent
#: → RAW draft). The trio ALREADY wires the tier→model choice
#: (``drivers/claude.mjs``: ``TRIO_TIER=heavy`` → ``claude-fable-5``,
#: ``standard`` → ``claude-opus-4-8``). Anchor's Stage-A launcher honors
#: ``ANTHROPIC_MODEL`` (the seam the fusion pass already uses), so pinning it from
#: the chosen tier runs the tile's read on the SAME top-tier Claude seat the
#: canonical regular/heavy runs use — nothing is reimplemented, just made
#: available. ``TRIO_TIER`` is also forwarded so any tier-honoring seat downstream
#: (e.g. a Gemini checker) resolves at the matching tier.
TIER_ANTHROPIC_MODEL = {"heavy": "claude-fable-5", "standard": "claude-opus-4-8"}
VALID_TIERS = ("standard", "heavy")
DEFAULT_TIER = "standard"


def _normalize_tier(tier) -> str:
    t = (tier or DEFAULT_TIER)
    t = t.strip().lower() if isinstance(t, str) else DEFAULT_TIER
    return t if t in VALID_TIERS else DEFAULT_TIER


# ── Run mode: agentic (canonical skill) vs legacy map-reduce ─────────────────
#: How Stage A produces the read. ``agentic`` (the DEFAULT, 2026-07-07) runs the
#: REAL ``gandalf`` / ``gandalf-heavy`` skill as a background Claude agent over
#: the folder — the skill decides map-reduce (its own context-sizer), writes the
#: report, and runs its own 5:1 Gemini reviews — exactly what a terminal
#: ``run gandalf-heavy`` does, just captured into the tile. ``mapreduce`` is the
#: legacy homegrown Python shard→grade, retained as a fallback so nothing
#: regresses if the live agentic run misbehaves on a given host.
MODE_AGENTIC = "agentic"
MODE_MAPREDUCE = "mapreduce"
GANDALF_MODE_ENV = "ANCHOR_GANDALF_MODE"
DEFAULT_MODE = MODE_AGENTIC


def _gandalf_mode() -> str:
    m = (os.environ.get(GANDALF_MODE_ENV) or "").strip().lower()
    return m if m in (MODE_AGENTIC, MODE_MAPREDUCE) else DEFAULT_MODE


#: Permission posture for the agentic run. The canonical Gandalf skill MUST spawn
#: a shell → agy (the Gemini 5:1) AND reach its grading host in the skill folder
#: (outside the analyzed repo); ``acceptEdits`` sandboxes headless Bash and blocks
#: BOTH — proven by the 2026-07-07 live smoke test (agy unreachable → single-family
#: ``degraded:true``). ``bypassPermissions`` unblocks them (re-run under the fix:
#: agy dispatched a Gemini 3.1 Pro shard, grader ran → ``degraded:false``). This is
#: broad (arbitrary shell + full-FS for the read-only advisor) but REQUIRED for the
#: canonical skill and consistent with an interactive ``gandalf-heavy`` run. Still
#: env-overridable (``ANCHOR_GANDALF_PERMISSION_MODE``) for a locked-down host.
GANDALF_PERMISSION_ENV = "ANCHOR_GANDALF_PERMISSION_MODE"
DEFAULT_PERMISSION_MODE = "bypassPermissions"


def _gandalf_permission_mode() -> str:
    return (os.environ.get(GANDALF_PERMISSION_ENV) or "").strip() or DEFAULT_PERMISSION_MODE


#: The canonical Gandalf reasoner is a CLAUDE-Code skill (it spawns its own Gemini
#: 5:1 via agy); force the claude backend for the agentic run so it never routes
#: the reasoner itself to Gemini. ``ANCHOR_RUNNER_CMD`` still overrides in tests.
_AGENTIC_BACKEND = "claude"

#: Matches the ``VERDICT: <one sentence>`` the agentic prompt requests. ``search``
#: (not ``match``) + optional ``**`` so it is caught even when the model emits it
#: INLINE with the last sentence or markdown-bolded (``**VERDICT:**``).
_VERDICT_RE = re.compile(r"(?i)\*{0,2}\s*VERDICT\s*\*{0,2}\s*:\s*(.+?)\s*$")


def _build_agentic_prompt(folder_path, tier, report_abs) -> str:
    """The natural-language seed that invokes the canonical skill — the same
    thing a user types in a terminal (``run gandalf`` / ``run gandalf-heavy`` +
    a description), plus an instruction to WRITE the report to a known path and
    print a capturable summary + ``VERDICT:`` line."""
    skill = "gandalf-heavy" if tier == "heavy" else "gandalf"
    return (
        f"Run the {skill} skill to analyze the project folder at:\n{folder_path}\n\n"
        "Objective: provide a concise summary of what this project/folder is, its "
        "key points of weakness, and the potential next steps.\n\n"
        "Write the full report as Markdown to this exact path:\n"
        f"{report_abs}\n\n"
        "If the skill produces a graded advisor-output JSON, also write it next to "
        "the report as 'advisor-output.json' in the same directory.\n\n"
        "Then, as your FINAL message, print your executive summary and verdict wrapped in exactly this format:\n"
        "<EXEC_SUMMARY>\n"
        "[Provide a short, easy-to-read bulleted list covering the core findings]\n\n"
        "VERDICT: <one sentence overall assessment>\n"
        "</EXEC_SUMMARY>")


def _parse_agentic_summary(text):
    """Split the agent's final text into ``(verdict, summary)``: the verdict is
    the ``VERDICT:`` line (if present); the summary is the remaining prose."""
    if not text:
        return "", ""
    
    import re
    match = re.search(r"<EXEC_SUMMARY>(.*?)</EXEC_SUMMARY>", text, re.DOTALL | re.IGNORECASE)
    if match:
        text = match.group(1).strip()
        
    verdict = ""
    keep = []
    for ln in text.splitlines():
        m = _VERDICT_RE.search(ln)
        if m:
            verdict = m.group(1).strip().strip("*").strip()
            # Keep any prose that preceded an INLINE verdict marker on the line.
            before = ln[:m.start()].rstrip()
            if before:
                keep.append(before)
            continue
        keep.append(ln)
    return verdict, "\n".join(keep).strip()


def _run_stage_agentic(folder_path, store, run_id, run_rel, ts, tier, env=None,
                       status_cb=None) -> dict:
    """Canonical path: run the real ``gandalf``/``gandalf-heavy`` skill agentically
    over the folder as ONE background job. The skill writes its own report (to the
    path in the prompt) and runs its own 5:1; Anchor captures the report + the
    printed summary/verdict. Returns the finalize dict — never raises."""
    res = {"ok": False, "reason": "unknown", "verdict": "",
           "report_rel": None, "exec_rel": None, "advisor_rel": None,
           "degraded": True, "cross_model": False}
    run_dir = _runs_dir(store) / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        res["reason"] = "artifact-write-failed:" + str(exc)[:160]
        return res
    report_abs = str(run_dir / REPORT_MD)
    prompt = _build_agentic_prompt(folder_path, tier, report_abs)
    if status_cb:
        status_cb("Running gandalf-heavy..." if tier == "heavy"
                  else "Running gandalf...")
    try:
        rec = _jr.launch("research", cwd=str(folder_path), prompt=prompt,
                         output_dir=str(run_dir), env=(env or None),
                         permission_mode=_gandalf_permission_mode(),
                         backend=_AGENTIC_BACKEND)
    except Exception:
        res["reason"] = "launch-failed"
        return res
    jid = rec.get("job_id")
    with _ACTIVE_RUNS_LOCK:
        r = _ACTIVE_RUNS.get(run_id)
        if r is not None:
            r["job_id"] = jid
            r.setdefault("job_ids", []).append(jid)
            if r.get("cancelled"):
                try:
                    _jr.cancel(jid)
                except Exception:
                    pass
                res["reason"] = "cancelled"
                return res

    import time
    start_t = time.time()
    t_limit = _timeout(tier)
    last_status = 0
    while True:
        if time.time() - start_t > t_limit:
            break
        rec = _jr.load_record(jid) or {}
        st = rec.get("status")
        if st in (_jr.STATUS_DONE, _jr.STATUS_FAILED, _jr.STATUS_CANCELLED):
            break
        if status_cb and time.time() - last_status > 2.0:
            elapsed = int(time.time() - start_t)
            # Try to get the last log line to give a hint of activity
            lines = _jr.all_lines(jid)
            hint = ""
            if lines:
                extracted = _jr.extract_assistant_text(lines)
                if extracted:
                    last_txt = extracted[-1].strip()
                    if last_txt:
                        hint = last_txt[:60].replace('\n', ' ') + "..."
            
            msg = f"Running ({elapsed}s elapsed)"
            if hint:
                msg += f" - {hint}"
            status_cb(msg)
            last_status = time.time()
        time.sleep(1.0)

    final = _jr.load_record(jid) or {}
    st = final.get("status")

    # SWARM SAFETY (2026-07-07): _jr.wait only BOUNDS the wait — it never kills the
    # job. If the run is not terminal (timed out / still running), TREE-KILL it now
    # so the write-capable agentic job AND the nested 5:1 (agy/Gemini) it spawned
    # can never orphan past this run's lifecycle (a live-owner-less swarm the
    # zombie-hunter would otherwise have to reap). cancel is idempotent — a no-op
    # on an already-exited job.
    if st != _jr.STATUS_DONE:
        try:
            _jr.cancel(jid)
        except Exception:
            pass

    with _ACTIVE_RUNS_LOCK:
        r = _ACTIVE_RUNS.get(run_id)
        if r is not None and r.get("cancelled"):
            res["reason"] = "cancelled"
            return res
    if st == "cancelled":
        res["reason"] = "cancelled"
        return res

    # HONESTY: a successful (GREEN) Gandalf read REQUIRES a COMPLETED job
    # (STATUS_DONE) that actually produced a NON-EMPTY report. A timed-out/failed
    # run — or a finished run that only printed prose (or emitted JSON) but wrote
    # no report — is an honest FAILURE, never a green tile. A stray/empty report
    # file can NEVER bypass the completion check.
    #
    # BUT: if the skill DID write a non-empty report before we bounded the wait
    # (heavy runs are slow), we still SALVAGE it — capturing the report + whatever
    # summary text was printed onto the FAILED record — so a time-bounded run
    # yields a viewable report + exec-summary instead of silently discarding the
    # work and looking "stuck". ok stays False; the tile is honestly not-green.
    try:
        report_written = ((run_dir / REPORT_MD).is_file()
                          and (run_dir / REPORT_MD).stat().st_size > 0)
    except OSError:
        report_written = False
    incomplete = st != _jr.STATUS_DONE
    if incomplete and not report_written:
        res["reason"] = "agentic-run-incomplete:" + str(st or "unknown")
        return res
    if (not incomplete) and not report_written:
        res["reason"] = "no-report-produced"
        return res

    text = "\n".join(_jr.extract_assistant_text(_jr.all_lines(jid)))
    verdict, summary = _parse_agentic_summary(text)

    # exec-summary.md from the printed summary (fallback: the verdict).
    exec_body = summary or verdict or "(report produced; no summary text printed)"
    
    # If the summary is a massive dump of assistant_parts (because result_text was missing),
    # truncate it so it doesn't pollute the UI.
    if len(exec_body) > 2000:
        exec_body = exec_body[-2000:] + "\n\n...(truncated agent scratchpad)..."

    if incomplete:
        exec_body = ("_This run was time-bounded before it fully completed; the "
                     "report may be partial and was not adversarially graded._\n\n"
                     + exec_body)
    try:
        (run_dir / EXEC_SUMMARY_MD).write_text(
            "# Gandalf executive summary\n\n" + exec_body + "\n", encoding="utf-8")
        res["exec_rel"] = f"{run_rel}/{EXEC_SUMMARY_MD}"
    except OSError:
        pass
    res["report_rel"] = f"{run_rel}/{REPORT_MD}"

    # If the skill also emitted its graded advisor-output.json, honor its honesty
    # stamps (cross_model/degraded) + verdict; otherwise leave the honest defaults
    # (a report without the graded envelope is NOT claimed cross-model).
    adv = run_dir / ADVISOR_OUTPUT_JSON
    if adv.is_file():
        try:
            graded = json.loads(adv.read_text(encoding="utf-8"))
            if isinstance(graded, dict):
                res["advisor_rel"] = f"{run_rel}/{ADVISOR_OUTPUT_JSON}"
                res["degraded"] = bool(graded.get("degraded", res["degraded"]))
                res["cross_model"] = bool(graded.get("cross_model", res["cross_model"]))
                if not verdict:
                    verdict = _one_line_verdict(graded)
        except (OSError, ValueError):
            pass

    if not verdict:
        verdict = (summary.split(". ")[0][:200] if summary
                   else ("Gandalf read time-bounded (partial report)."
                         if incomplete else "Gandalf read complete."))
    res["verdict"] = verdict
    _add_gitignore_best_effort(store)
    if incomplete:
        # Report salvaged, but the run did not fully complete → honest FAILURE.
        res["ok"] = False
        res["reason"] = ("agentic-run-incomplete:" + str(st or "unknown")
                         + "; report-salvaged")
        return res
    res["ok"] = True
    res["reason"] = None
    return res

#: Project-root subdir holding the served run artifacts (NOT under .anchor, which
#: /artifact rejects). One ``run-<ts>/`` per run.
GANDALF_DIRNAME = "gandalf"

#: Internal index (under the per-project store) + its filenames. NEVER served via
#: /artifact — read directly by the GET endpoint.
INDEX_DIRNAME = "gandalf"
INDEX_FILENAME = "index.json"

#: Per-run artifact filenames.
REPORT_MD = "report.md"
EXEC_SUMMARY_MD = "exec-summary.md"
ADVISOR_OUTPUT_JSON = "advisor-output.json"

#: Index schema version. BUMP when a fix changes what a correct index record
#: looks like; ``list_runs`` normalizes older/missing versions with honest
#: defaults so stale indexes don't crash the read path.
GANDALF_INDEX_SCHEMA_VERSION = 1

#: The 9 required top-level keys of a graded advisor-output (per
#: ``schema/advisor-output.schema.json``). A graded output missing any of these
#: is a malformed host result → an honest error run.
_REQUIRED_TOP_KEYS = (
    "schema_version", "cross_model", "degraded", "reasoning", "verdict",
    "findings", "nitpicks", "elevations", "risk_labels",
)

#: How many bytes of SKILL.md to embed in the Stage-A prompt (bounded).
_MAX_SKILL_BYTES = 64 * 1024

# ── Wave 9 — map-reduce sharding (Pillar B, #2) ──────────────────────────────
#: The single whole-tree Stage-A pass is replaced by a MAP-REDUCE: shard the
#: target tree, fan out one read per shard through the W8 engine substrate
#: (``lanes.select_engine_plan`` picks the honest driver — Claude, or Gemini on a
#: Gemini-only host), then REDUCE the per-shard drafts into ONE merged raw draft
#: whose findings are GROUPED by shard (≥1 per shard that produced a draft). The
#: merged draft is graded once by the Stage-B host (unchanged). A single-file /
#: trivial tree still yields ONE shard (so the whole-tree behavior is preserved).

#: Cap on the number of shards a run fans out to (env-overridable). Keeps a huge
#: tree from spawning an unbounded number of concurrent reads.
MAX_SHARDS_ENV = "ANCHOR_GANDALF_MAX_SHARDS"
DEFAULT_MAX_SHARDS = 12

#: A top-level bucket bigger than this many files is split into sub-shards so a
#: large flat tree still fans out (env-overridable).
FILES_PER_SHARD_ENV = "ANCHOR_GANDALF_FILES_PER_SHARD"
DEFAULT_FILES_PER_SHARD = 40

#: How many shard file paths to enumerate inside a shard's Stage-A prompt (bounded
#: so a big shard doesn't blow the prompt; the read agent still has --add-dir).
_MAX_SHARD_PROMPT_FILES = 120

#: Label for the bucket holding root-level (no-subdir) files.
_ROOT_SHARD_LABEL = "(root)"


# ── ContextSizer / Ignore Helpers (Wave 1) ──────────────────────────────────

def _load_anchorignore(folder_path) -> list:
    """Read .anchorignore patterns if present."""
    ignore_path = Path(folder_path) / ".anchorignore"
    patterns = []
    if ignore_path.is_file():
        try:
            with open(ignore_path, "r", encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        patterns.append(line)
        except OSError:
            pass
    return patterns


def _should_ignore(rel_path: Path, patterns: list) -> bool:
    """Determine if a relative path matches any ignore pattern or standard skip dirs."""
    parts_lower = [p.lower() for p in rel_path.parts]
    for skip in {".git", ".anchor", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", ".pytest_cache", ".anchorignore", "gandalf"}:
        if skip in parts_lower:
            return True

    rel_str = rel_path.as_posix()
    rel_str_lower = rel_str.lower()

    for pattern in patterns:
        clean_pat = pattern.rstrip('/')
        clean_pat_lower = clean_pat.lower()

        # Check components of the path
        for part in rel_path.parts:
            part_lower = part.lower()
            if fnmatch.fnmatch(part, clean_pat) or fnmatch.fnmatch(part_lower, clean_pat_lower):
                return True

        # Check full relative path
        if fnmatch.fnmatch(rel_str, clean_pat) or fnmatch.fnmatch(rel_str_lower, clean_pat_lower):
            return True
        if fnmatch.fnmatch(rel_str, pattern) or fnmatch.fnmatch(rel_str_lower, pattern.lower()):
            return True

    return False


def scan_project_context(folder_path) -> float:
    """Recursively scan the directory (respecting .anchorignore) and compute total_bytes / 4."""
    root = Path(folder_path).resolve()
    if not root.is_dir():
        return 0.0

    patterns = _load_anchorignore(folder_path)
    total_bytes = 0

    for dirpath, dirnames, filenames in os.walk(str(root)):
        try:
            rel_dirpath = Path(dirpath).resolve().relative_to(root)
        except (ValueError, OSError):
            continue

        # Prune directories in-place
        keep_dirs = []
        for d in dirnames:
            rel_d = rel_dirpath / d
            if not _should_ignore(rel_d, patterns):
                keep_dirs.append(d)
        dirnames[:] = keep_dirs

        for fname in filenames:
            rel_file = rel_dirpath / fname
            if _should_ignore(rel_file, patterns):
                continue

            fpath = Path(dirpath) / fname
            try:
                total_bytes += fpath.stat().st_size
            except OSError:
                pass

    return total_bytes / 4.0


# ── Path helpers ─────────────────────────────────────────────────────────────

def _skill_dir() -> Path:
    raw = (os.environ.get(SKILL_DIR_ENV) or "").strip()
    if raw:
        return Path(raw)
    here = Path(__file__).resolve().parent
    for c in (
        here / "vendor" / "bundled-skills" / "gandalf",
        here / "skills" / "gandalf",
        Path(os.environ.get("ANCHOR_FOUNDRY_DIR", "") or "") / "skills" / "gandalf",
        Path(os.environ.get("SKILL_FOUNDRY_DIR", "") or "") / "skills" / "gandalf",
    ):
        try:
            if c.is_dir() and (c / "SKILL.md").is_file():
                return c
        except OSError:
            continue
    if DEFAULT_SKILL_DIR:
        return Path(DEFAULT_SKILL_DIR)
    # Last resort: relative name so callers get a Path (host grades fail honestly).
    return Path("skills") / "gandalf"


def _timeout(tier: str = DEFAULT_TIER) -> float:
    raw = (os.environ.get(TIMEOUT_ENV) or "").strip()
    base = DEFAULT_TIMEOUT
    if raw:
        try:
            base = float(raw)
        except ValueError:
            base = DEFAULT_TIMEOUT
    if _normalize_tier(tier) != "heavy":
        return base
    # Heavy: an explicit override wins; else a multiplier over the base ceiling.
    raw_h = (os.environ.get(TIMEOUT_HEAVY_ENV) or "").strip()
    if raw_h:
        try:
            return float(raw_h)
        except ValueError:
            pass
    try:
        mult = float((os.environ.get(TIMEOUT_HEAVY_MULT_ENV) or "").strip()
                     or HEAVY_TIMEOUT_MULT)
    except ValueError:
        mult = HEAVY_TIMEOUT_MULT
    return base * mult


def _runs_dir(folder_path) -> Path:
    """``<folder>/gandalf/`` — the project-root dir holding run-<ts>/ subdirs."""
    return Path(folder_path) / GANDALF_DIRNAME


def _index_path(folder_path, project_id) -> Path:
    """``<folder>/.anchor/projects/<id>/gandalf/index.json`` — the internal index."""
    return (_summarizer._project_store_dir(folder_path, project_id)
            / INDEX_DIRNAME / INDEX_FILENAME)


def _host_cmd_argv():
    """Resolve the Stage-B host command as an argv list.

    ``ANCHOR_GANDALF_HOST_CMD`` wins (tests point it at a Python stub); else the
    default ``node "<skilldir>/runtime/gandalf-run.mjs"``. Split survives Windows
    backslash paths (reuses job_runner's splitter).
    """
    override = (os.environ.get(HOST_CMD_ENV) or "").strip()
    if override:
        return _jr._shlex_split(override)
    host_mjs = _skill_dir() / "runtime" / "gandalf-run.mjs"
    return ["node", str(host_mjs)]


# ── Stage A — build the embedded-protocol prompt ─────────────────────────────

def _read_skill_protocol() -> str:
    """Read ``SKILL.md`` from the skill dir (bounded). Honest empty on absence."""
    try:
        p = _skill_dir() / "SKILL.md"
        if not p.is_file():
            return ""
        return p.read_text(encoding="utf-8", errors="replace")[:_MAX_SKILL_BYTES]
    except OSError:
        return ""


def _build_prompt(folder_path) -> str:
    """Stage-A prompt = the Gandalf protocol + the raw-draft instruction."""
    protocol = _read_skill_protocol()
    parts = []
    if protocol:
        parts.append("You are running the Gandalf deep-think advisor skill. Its "
                     "protocol follows verbatim:\n\n" + protocol)
    else:
        parts.append("You are running the Gandalf deep-think advisor skill.")
    parts.append(
        "Analyze the project at the following folder and emit ONLY the RAW draft "
        "JSON per the skill's runtime/RAW-DRAFT-CONTRACT.md as your FINAL message. "
        "Do NOT self-assign tiers or refutation stamps — the host applies them.\n\n"
        f"Project folder: {folder_path}")
    return "\n\n".join(parts)


# ── JSON extraction (last balanced top-level object) ─────────────────────────

def _last_balanced_json(text: str):
    """Locate + parse the LAST balanced top-level JSON object in ``text``.

    Scans for ``{`` ... matching ``}`` spans at brace-depth 0 (string/escape
    aware so braces inside strings don't confuse the depth count) and returns the
    parsed value of the LAST one that ``json.loads`` accepts. Returns ``None`` if
    none parse. Stdlib only; never raises.
    """
    if not text:
        return None
    spans = []
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start >= 0:
                    spans.append((start, i + 1))
                    start = -1
    for s, e in reversed(spans):
        try:
            obj = json.loads(text[s:e])
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(obj, dict):
            return obj
    return None


# ── Stage A — run the model, recover the raw draft ───────────────────────────

def _run_stage_a(folder_path, env=None, run_id=None):
    """Run Stage A → ``(raw_draft_dict, reason)``.

    On any failure (job failed/timed-out, no parseable JSON) returns
    ``(None, "<reason>")``. Never raises.
    """
    folder = str(folder_path)
    prompt = _build_prompt(folder)
    try:
        rec = _jr.launch("research", cwd=folder, prompt=prompt,
                         output_dir=folder, env=(env or None),
                         permission_mode="plan")
    except Exception:
        return None, "launch-failed"
    jid = rec["job_id"]
    if run_id:
        with _ACTIVE_RUNS_LOCK:
            if run_id in _ACTIVE_RUNS:
                if _ACTIVE_RUNS[run_id]["cancelled"]:
                    try:
                        _jr.cancel(jid)
                    except Exception:
                        pass
                    return None, "cancelled"
                _ACTIVE_RUNS[run_id]["job_id"] = jid
    _jr.wait(jid, timeout=_timeout())
    if run_id:
        with _ACTIVE_RUNS_LOCK:
            if run_id in _ACTIVE_RUNS and _ACTIVE_RUNS[run_id]["cancelled"]:
                return None, "cancelled"
    final = _jr.load_record(jid) or {}
    if final.get("status") == "cancelled":
        return None, "cancelled"
    if final.get("status") != _jr.STATUS_DONE:
        return None, "stage-a-run-failed:" + str(final.get("status") or "unknown")
    lines = _jr.all_lines(jid)
    text_lines = _jr.extract_assistant_text(lines)
    draft = _last_balanced_json("\n".join(text_lines))
    if not isinstance(draft, dict):
        return None, "stage-a-unparseable-draft"
    return draft, None


# ── Stage A (map-reduce) — shard the tree, fan out reads, reduce ─────────────

def _int_env(name, default):
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = int(raw)
        return v if v > 0 else default
    except ValueError:
        return default


def _collect_files(folder_path) -> list:
    """Relative POSIX paths of the non-ignored files under ``folder`` (sorted).

    Reuses the same ignore rules as :func:`scan_project_context` (``.anchorignore``
    + the standard skip dirs), so the map covers exactly what the ContextSizer
    counts. Never raises."""
    root = Path(folder_path).resolve()
    if not root.is_dir():
        return []
    patterns = _load_anchorignore(folder_path)
    out = []
    for dirpath, dirnames, filenames in os.walk(str(root)):
        try:
            rel_dirpath = Path(dirpath).resolve().relative_to(root)
        except (ValueError, OSError):
            continue
        keep = []
        for d in dirnames:
            if not _should_ignore(rel_dirpath / d, patterns):
                keep.append(d)
        dirnames[:] = keep
        for fname in filenames:
            rel_file = rel_dirpath / fname
            if _should_ignore(rel_file, patterns):
                continue
            out.append(rel_file.as_posix())
    out.sort()
    return out


def _shard_tree(folder_path, files=None) -> list:
    """Shard the target tree into read-units for the map step.

    Returns a list of shards ``[{"label": <str>, "files": [<rel posix>, ...]}]``:

    - Files are bucketed by their TOP-LEVEL path component; root-level files land
      in a single ``(root)`` bucket.
    - A bucket larger than ``FILES_PER_SHARD`` is split into ``…#N`` sub-shards so
      a large flat tree still fans out.
    - The shard count is capped at ``MAX_SHARDS`` (extra buckets are round-robin
      merged), keeping a huge tree bounded.
    - A trivial tree (0–1 files, or a single small bucket) yields ONE shard, so
      the historical whole-tree single-pass behavior is preserved.

    Deterministic (sorted inputs). Never raises."""
    if files is None:
        files = _collect_files(folder_path)
    if not files:
        return [{"label": _ROOT_SHARD_LABEL, "files": []}]

    buckets = {}
    for rel in files:
        parts = rel.split("/")
        top = _ROOT_SHARD_LABEL if len(parts) == 1 else parts[0]
        buckets.setdefault(top, []).append(rel)

    files_per_shard = _int_env(FILES_PER_SHARD_ENV, DEFAULT_FILES_PER_SHARD)
    max_shards = _int_env(MAX_SHARDS_ENV, DEFAULT_MAX_SHARDS)

    # Split oversized buckets into deterministic sub-shards.
    shards = []
    for label in sorted(buckets):
        group = buckets[label]
        if len(group) <= files_per_shard:
            shards.append({"label": label, "files": group})
        else:
            for i in range(0, len(group), files_per_shard):
                chunk = group[i:i + files_per_shard]
                shards.append({"label": f"{label}#{i // files_per_shard + 1}",
                               "files": chunk})

    # Cap the fan-out: round-robin merge extras into the first max_shards shards.
    if len(shards) > max_shards:
        merged = [dict(s) for s in shards[:max_shards]]
        for i, extra in enumerate(shards[max_shards:]):
            tgt = merged[i % max_shards]
            tgt["files"] = tgt["files"] + extra["files"]
            tgt["label"] = tgt["label"] + "+" + extra["label"]
        shards = merged
    return shards


def _build_shard_prompt(folder_path, shard) -> str:
    """Stage-A prompt for ONE shard = the protocol + the shard's file list."""
    protocol = _read_skill_protocol()
    parts = []
    if protocol:
        parts.append("You are running the Gandalf deep-think advisor skill. Its "
                     "protocol follows verbatim:\n\n" + protocol)
    else:
        parts.append("You are running the Gandalf deep-think advisor skill.")
    label = shard.get("label") or _ROOT_SHARD_LABEL
    flist = shard.get("files") or []
    shown = flist[:_MAX_SHARD_PROMPT_FILES]
    more = len(flist) - len(shown)
    file_block = "\n".join(shown) if shown else "(the whole folder)"
    if more > 0:
        file_block += f"\n… and {more} more file(s) in this shard."
    parts.append(
        "This is a MAP shard of a larger project. Analyze ONLY the following slice "
        f"of the project (shard '{label}') and emit ONLY the RAW draft JSON per the "
        "skill's runtime/RAW-DRAFT-CONTRACT.md as your FINAL message. Do NOT "
        "self-assign tiers or refutation stamps — the host applies them.\n\n"
        f"Project folder: {folder_path}\n\nFiles in this shard:\n{file_block}")
    return "\n\n".join(parts)


def _resolve_shard_backend() -> str:
    """Pick the shard read engine via the W8 substrate (locked #10).

    ``lanes.select_engine_plan`` returns the HONEST driver for the research lane on
    this host — Claude when present (Gemini stays the 5:1 skill-layer swarm), or
    Gemini on a Gemini-only host (research is Gemini-runnable). Never cross-calls;
    falls back to the default backend when the plan yields no driver. The
    ``ANCHOR_RUNNER_CMD`` override still wins inside ``job_runner`` (tests)."""
    try:
        profile = _lanes.detect_host_profile()
        plan = _lanes.select_engine_plan(_lanes.LANE_RESEARCH, profile=profile)
        return plan.get("driver") or _jr.DEFAULT_BACKEND
    except Exception:
        return _jr.DEFAULT_BACKEND


def _map_shards(folder_path, shards, env=None, run_id=None) -> list:
    """MAP: launch one read per shard (concurrently), recover each raw draft.

    Returns ``[(label, draft_dict_or_None, reason_or_None), ...]``. All shard jobs
    are launched first (so they run in PARALLEL as server-owned subprocesses),
    their ids registered for cancel, then each is awaited + parsed. Read-only
    (``permission_mode='plan'``). Never raises."""
    folder = str(folder_path)
    backend = _resolve_shard_backend()
    launched = []  # (label, job_id_or_None, launch_reason_or_None)
    for shard in shards:
        label = shard.get("label") or _ROOT_SHARD_LABEL
        prompt = _build_shard_prompt(folder, shard)
        try:
            rec = _jr.launch("research", cwd=folder, prompt=prompt,
                             output_dir=folder, env=(env or None),
                             permission_mode="plan", backend=backend)
            launched.append((label, rec["job_id"], None))
        except Exception:
            launched.append((label, None, "launch-failed"))

    # Register every shard job so cancel_run can tree-kill the whole fan-out.
    if run_id:
        cancelled = False
        with _ACTIVE_RUNS_LOCK:
            r = _ACTIVE_RUNS.get(run_id)
            if r is not None:
                jids = [j for (_lbl, j, _rs) in launched if j]
                r["job_ids"] = jids
                if jids and not r.get("job_id"):
                    r["job_id"] = jids[0]
                cancelled = bool(r.get("cancelled"))
        if cancelled:
            for (_lbl, j, _rs) in launched:
                if j:
                    try:
                        _jr.cancel(j)
                    except Exception:
                        pass
            return [(lbl, None, "cancelled") for (lbl, _j, _rs) in launched]

    results = []
    for (label, jid, lreason) in launched:
        if jid is None:
            results.append((label, None, lreason or "launch-failed"))
            continue
        if run_id:
            with _ACTIVE_RUNS_LOCK:
                r = _ACTIVE_RUNS.get(run_id)
                if r is not None and r.get("cancelled"):
                    results.append((label, None, "cancelled"))
                    continue
        _jr.wait(jid, timeout=_timeout())
        final = _jr.load_record(jid) or {}
        st = final.get("status")
        if st == "cancelled":
            results.append((label, None, "cancelled"))
            continue
        if st != _jr.STATUS_DONE:
            results.append((label, None,
                            "stage-a-run-failed:" + str(st or "unknown")))
            continue
        text_lines = _jr.extract_assistant_text(_jr.all_lines(jid))
        draft = _last_balanced_json("\n".join(text_lines))
        if not isinstance(draft, dict):
            results.append((label, None, "stage-a-unparseable-draft"))
            continue
        results.append((label, draft, None))
    return results


def _group_item(item, label):
    """A shallow copy of one finding/nitpick/elevation tagged with its shard."""
    it = dict(item) if isinstance(item, dict) else {"verdict": str(item)}
    it["group"] = label
    return it


def _reduce_drafts(shard_results) -> tuple:
    """REDUCE the per-shard drafts into ONE merged raw draft with GROUPED findings.

    ``shard_results`` is the list from :func:`_map_shards`. Returns
    ``(merged_draft_or_None, reason_or_None)``:

    - Every finding/nitpick/elevation is tagged with its shard ``group``.
    - Each shard that produced a draft contributes ≥1 finding — a shard whose
      draft carried none gets an honest "no notable findings in this shard"
      coverage marker (proves the slice was read, never fabricates a problem).
    - ``groups`` lists the covered shard labels; ``shard_count`` the count.

    When NO shard produced a parseable draft, returns ``(None, <reason>)`` —
    preferring an ``unparseable`` reason so the honest Stage-A degrade path (and
    its tests) is preserved. Never raises."""
    valid = [(lbl, d) for (lbl, d, _rs) in shard_results if isinstance(d, dict)]
    if not valid:
        reason = None
        for (_lbl, _d, rs) in shard_results:
            if rs and "unparseable" in rs:
                reason = rs
                break
        if reason is None:
            for (_lbl, _d, rs) in shard_results:
                if rs and rs != "cancelled":
                    reason = rs
                    break
        if reason is None:
            for (_lbl, _d, rs) in shard_results:
                if rs:
                    reason = rs
                    break
        return None, (reason or "stage-a-no-drafts")

    findings, nitpicks, elevations = [], [], []
    reasonings, verdicts, groups = [], [], []
    for (label, d) in valid:
        groups.append(label)
        shard_findings = [_group_item(f, label) for f in (d.get("findings") or [])]
        if not shard_findings:
            shard_findings = [{
                "id": f"cover-{label}",
                "kind": "diagnose",
                "rung": "OBSERVED",
                "reasoning": f"Shard '{label}' was read; no notable findings surfaced.",
                "verdict": f"No notable findings in '{label}'.",
                "severity": "info",
                "group": label,
            }]
        findings.extend(shard_findings)
        nitpicks.extend(_group_item(n, label) for n in (d.get("nitpicks") or []))
        elevations.extend(_group_item(e, label) for e in (d.get("elevations") or []))
        if d.get("reasoning"):
            reasonings.append(f"[{label}] " + str(d.get("reasoning")))
        if d.get("verdict"):
            verdicts.append(str(d.get("verdict")))

    # Contract caps (2026-07-02 live finding): the Stage-B host enforces the
    # PRE-REGISTERED output caps (prereg-constants.json: max_nitpicks=7,
    # max_elevations=5) and hard-fails an over-cap draft — a 12-shard merge
    # aggregated 35 nitpicks and the whole run failed at grading. Trim HERE,
    # round-robin across shards (fair coverage — every shard keeps its top
    # items before any shard gets a second), and record the trim honestly.
    nitpicks, n_dropped = _cap_round_robin(nitpicks, 7)
    elevations, e_dropped = _cap_round_robin(elevations, 5)
    trim_note = ""
    if n_dropped or e_dropped:
        trim_note = ("\n\n[reduce] Trimmed to the pre-registered output caps: "
                     f"dropped {n_dropped} nitpick(s) and {e_dropped} "
                     "elevation(s) beyond the top-per-shard round-robin "
                     "(caps: 7 nitpicks, 5 elevations).")

    merged = {
        "reasoning": "\n\n".join(reasonings) + trim_note,
        "verdict": (" ".join(verdicts)[:1000]
                    or f"Map-reduce read across {len(valid)} shard(s)."),
        "findings": findings,
        "nitpicks": nitpicks,
        "elevations": elevations,
        "groups": groups,
        "shard_count": len(valid),
    }
    return merged, None


def _cap_round_robin(items, cap: int):
    """Trim a merged, shard-tagged item list to ``cap`` FAIRLY: round-robin by
    shard ``group`` (every shard keeps its first item before any shard keeps a
    second), preserving within-shard order. Returns ``(kept, dropped_count)``."""
    if len(items) <= cap:
        return items, 0
    by_group: dict = {}
    order = []
    for it in items:
        g = (it.get("group") if isinstance(it, dict) else None) or ""
        if g not in by_group:
            by_group[g] = []
            order.append(g)
        by_group[g].append(it)
    kept = []
    rank = 0
    while len(kept) < cap:
        took = False
        for g in order:
            bucket = by_group[g]
            if rank < len(bucket):
                kept.append(bucket[rank])
                took = True
                if len(kept) >= cap:
                    break
        if not took:
            break
        rank += 1
    return kept, len(items) - len(kept)


def _run_stage_a_mapreduce(folder_path, env=None, run_id=None) -> tuple:
    """The map-reduce Stage A: shard → parallel map → reduce → FUSE → raw draft.

    Returns ``(merged_draft_dict, reason)`` with the same contract as the legacy
    :func:`_run_stage_a` (``(None, "<reason>")`` on failure). Never raises."""
    shards = _shard_tree(folder_path)
    shard_results = _map_shards(folder_path, shards, env=env, run_id=run_id)
    merged, reason = _reduce_drafts(shard_results)
    if merged is not None:
        merged = _fuse_merged_draft(folder_path, merged, env=env, run_id=run_id)
    return merged, reason


#: Fusion toggle (default ON): one frontier-model synthesis pass over the
#: mechanically merged draft. ``0`` disables (pure mechanical merge, the pre-fusion
#: behavior — also what launch-counting tests set).
FUSION_ENV = "ANCHOR_GANDALF_FUSION"
#: Cap on the merged-draft JSON embedded in the fusion prompt.
_MAX_FUSION_PROMPT_BYTES = 120 * 1024


def _fuse_merged_draft(folder_path, merged, env=None, run_id=None) -> dict:
    """FUSION (2026-07): one frontier-model pass over the merged draft.

    The mechanical reduce staples per-shard drafts together — no model ever
    reads ACROSS the shards, so cross-cutting findings and a real top-level
    verdict never existed (the review's single biggest gandalf quality gap).
    This pass AUGMENTS, never replaces: the grouped per-shard findings (and the
    ≥1-finding-per-shard coverage contract) are kept verbatim; fusion may only
    (a) rewrite ``reasoning``/``verdict`` as a true cross-shard synthesis and
    (b) APPEND cross-cutting findings tagged ``group='(cross-shard)'``.
    Single-shard runs skip it (nothing to fuse). Any failure degrades honestly
    to the mechanical merge, stamped in ``merged['fusion']``. Never raises."""
    if merged.get("shard_count", 0) <= 1:
        merged["fusion"] = "single-shard"
        return merged
    if (os.environ.get(FUSION_ENV) or "").strip() == "0":
        merged["fusion"] = "disabled"
        return merged
    payload = json.dumps(merged, ensure_ascii=False)[:_MAX_FUSION_PROMPT_BYTES]
    prompt = (
        "You are the Gandalf map-reduce FUSION step — the first reader who sees the "
        "WHOLE picture. Below is the merged raw draft of a sharded analysis: each "
        "shard was read independently and its findings are tagged with a 'group'. "
        "Synthesize ACROSS the shards. Emit ONLY one JSON object (no prose, no "
        "fences) with exactly these keys:\n"
        '  "reasoning": the cross-shard synthesis — the story of the whole tree, '
        "not a concatenation of per-shard notes;\n"
        '  "verdict": ONE sentence — the honest top-level read;\n'
        '  "cross_cutting_findings": findings visible ONLY across shards '
        "(duplicated effort, contradictory approaches, shared root causes, "
        "systemic risks) — each shaped like the input findings (id, kind, rung, "
        "reasoning, verdict, severity), possibly empty. Do NOT restate per-shard "
        "findings; they are already recorded.\n\n"
        "=== MERGED RAW DRAFT ===\n" + payload + "\n=== END DRAFT ==="
    )
    fusion_env = dict(env) if env else {}
    # Pin the fusion brain to the frontier tier (the synthesis seat) unless the
    # caller already routed it. The claude CLI honors ANTHROPIC_MODEL.
    fusion_env.setdefault("ANTHROPIC_MODEL", "claude-fable-5")
    try:
        rec = _jr.launch("research", cwd=str(folder_path), prompt=prompt,
                         output_dir=str(folder_path), env=fusion_env,
                         permission_mode="plan",
                         backend=_resolve_shard_backend())
        jid = rec["job_id"]
        if run_id:
            with _ACTIVE_RUNS_LOCK:
                r = _ACTIVE_RUNS.get(run_id)
                if r is not None:
                    r.setdefault("job_ids", []).append(jid)
                    if r.get("cancelled"):
                        merged["fusion"] = "skipped:cancelled"
                        return merged
        _jr.wait(jid, timeout=_timeout())
        final = _jr.load_record(jid) or {}
        if final.get("status") != _jr.STATUS_DONE:
            merged["fusion"] = "skipped:fusion-run-" + str(final.get("status") or "unknown")
            return merged
        text = "\n".join(_jr.extract_assistant_text(_jr.all_lines(jid)))
        fused = _last_balanced_json(text)
        if not isinstance(fused, dict):
            merged["fusion"] = "skipped:unparseable"
            return merged
        if isinstance(fused.get("reasoning"), str) and fused["reasoning"].strip():
            merged["reasoning"] = fused["reasoning"].strip()
        if isinstance(fused.get("verdict"), str) and fused["verdict"].strip():
            merged["verdict"] = fused["verdict"].strip()[:1000]
        extra = fused.get("cross_cutting_findings")
        if isinstance(extra, list):
            merged["findings"].extend(
                _group_item(f, "(cross-shard)") for f in extra if isinstance(f, dict))
        merged["fusion"] = "fused"
        return merged
    except Exception:
        merged["fusion"] = "skipped:error"
        return merged


# ── Stage B — run the host, recover the graded output ────────────────────────

def _run_stage_b(raw_draft, run_id=None):
    """Run Stage B (the host) on the raw draft → ``(graded_dict, reason)``.

    Feeds the raw draft on stdin, captures the graded advisor-output.json on
    stdout. A non-zero exit / absent host / unparseable output is an honest
    error (returns ``(None, "<reason>")``). Never raises.
    """
    argv = _host_cmd_argv()
    payload = json.dumps(raw_draft, ensure_ascii=False)
    if run_id:
        with _ACTIVE_RUNS_LOCK:
            if run_id in _ACTIVE_RUNS and _ACTIVE_RUNS[run_id]["cancelled"]:
                return None, "cancelled"
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=_paths.NO_WINDOW
        )
    except FileNotFoundError:
        return None, "host-unavailable"
    except (OSError, subprocess.SubprocessError):
        return None, "host-spawn-failed"

    if run_id:
        with _ACTIVE_RUNS_LOCK:
            if run_id in _ACTIVE_RUNS:
                if _ACTIVE_RUNS[run_id]["cancelled"]:
                    try:
                        import proc_probe
                        proc_probe.tree_kill(proc.pid)
                    except Exception:
                        pass
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    return None, "cancelled"
                _ACTIVE_RUNS[run_id]["proc"] = proc

    try:
        stdout, stderr = proc.communicate(input=payload, timeout=_timeout())
    except subprocess.TimeoutExpired:
        try:
            import proc_probe
            proc_probe.tree_kill(proc.pid)
        except Exception:
            pass
        try:
            proc.kill()
        except Exception:
            pass
        return None, "host-timeout"
    except Exception:
        return None, "host-spawn-failed"

    if run_id:
        with _ACTIVE_RUNS_LOCK:
            if run_id in _ACTIVE_RUNS and _ACTIVE_RUNS[run_id]["cancelled"]:
                return None, "cancelled"

    if proc.returncode != 0:
        err = (stderr or "").strip().splitlines()
        reason = "host-nonzero-exit"
        if err:
            reason += ":" + err[-1][:200]
        return None, reason
    graded = _last_balanced_json(stdout or "")
    if not isinstance(graded, dict):
        return None, "host-unparseable-output"
    missing = [k for k in _REQUIRED_TOP_KEYS if k not in graded]
    if missing:
        return None, "host-output-missing-keys:" + ",".join(missing)
    return graded, None


# ── Render helpers ───────────────────────────────────────────────────────────

def _one_line_verdict(graded) -> str:
    """The cleaned one-line verdict (pinned to the top-level ``verdict`` field)."""
    val = graded.get("verdict") or ""
    # Strip any markdown / formatting.
    val = val.replace("*", "").replace("`", "").strip()
    return val[:200]


def _severity_rank(item) -> int:
    """Helper: order findings/nitpicks/elevations by severity."""
    r = item.get("severity") or ""
    if r == "critical":
        return 4
    if r == "high":
        return 3
    if r == "medium":
        return 2
    return 1


def _render_finding(f, lines) -> None:
    """Append one finding's markdown to ``lines``."""
    sev = (f.get("severity") or "info").upper()
    lines.append(f"### [{sev}] {f.get('title') or 'Finding'}")
    lines.append(str(f.get("description") or f.get("verdict") or ""))
    remedy = f.get("remedy")
    if remedy:
        lines.append(f"\n*Remedy:* {remedy}")
    lines.append("")


def _render_full_report(graded, *, run_id="", when=None) -> str:
    """Render the full markdown report.

    Wave 9: when the map-reduce grouping survives grading (findings carry a
    ``group`` shard tag), findings are rendered GROUPED by area; otherwise a flat
    severity-ordered list (unchanged)."""
    date_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when or time.time()))
    lines = [
        f"# Gandalf Read Report — {run_id or 'run'}\n",
        f"*Generated:* {date_str}\n",
        f"## Verdict\n**{_one_line_verdict(graded)}**\n",
        "## Reasoning\n",
        str(graded.get("reasoning") or ""),
        "\n## Findings & Risks\n",
    ]
    findings = sorted(graded.get("findings") or [], key=_severity_rank, reverse=True)
    if not findings:
        lines.append("*No major findings.*")
        return "\n".join(lines)

    grouped = any(isinstance(f, dict) and f.get("group") for f in findings)
    if grouped:
        # Preserve the shard order the reduce emitted (via ``groups``), then any
        # remaining/ungrouped findings under a catch-all.
        order = [g for g in (graded.get("groups") or []) if isinstance(g, str)]
        seen = set()
        ordered_groups = []
        for g in order:
            if g not in seen:
                ordered_groups.append(g)
                seen.add(g)
        for f in findings:
            g = f.get("group") if isinstance(f, dict) else None
            key = g or "(other)"
            if key not in seen:
                ordered_groups.append(key)
                seen.add(key)
        lines.append(f"*Grouped across {len(ordered_groups)} area(s).*\n")
        for g in ordered_groups:
            members = [f for f in findings
                       if (f.get("group") if isinstance(f, dict) else None) == g
                       or (g == "(other)" and not (isinstance(f, dict) and f.get("group")))]
            if not members:
                continue
            lines.append(f"## Area: {g}\n")
            for f in members:
                _render_finding(f, lines)
    else:
        for f in findings:
            _render_finding(f, lines)
    return "\n".join(lines)


def _render_exec_summary(graded, *, run_id="", when=None) -> str:
    """Render the executive summary markdown (inline dashboard)."""
    lines = [
        f"**Verdict:** {_one_line_verdict(graded)}\n",
        "### Key Findings\n",
    ]
    findings = sorted(graded.get("findings") or [], key=_severity_rank, reverse=True)[:3]
    if not findings:
        lines.append("*No major findings.*")
    for f in findings:
        sev = (f.get("severity") or "info").upper()
        lines.append(f"- **[{sev}]** {f.get('title') or 'Finding'}")
    return "\n".join(lines)


# ── Index store ──────────────────────────────────────────────────────────────

def _load_index(folder_path, project_id) -> list:
    """Load the raw index list (newest-first). Honest empty on absence/corruption."""
    p = _index_path(folder_path, project_id)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    if isinstance(data, dict):
        data = data.get("runs") or []
    if not isinstance(data, list):
        return []
    return [r for r in data if isinstance(r, dict)]


def _append_index(folder_path, project_id, record: dict) -> None:
    """Upsert a record into the index (newest-first) under the write lock.

    Wave 9: an UPSERT keyed on ``run_id`` — a run first writes an in-progress
    record (``status='running'``) and later replaces it IN PLACE with its terminal
    record, so a single run never leaves two rows. A NEW run_id is prepended
    (newest-first). Distinct run_ids keep the historical append behavior."""
    with _paths.WRITE_LOCK:
        p = _index_path(folder_path, project_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        runs = _load_index(folder_path, project_id)
        rid = str(record.get("run_id") or "")
        replaced = False
        if rid:
            for i, r in enumerate(runs):
                if str(r.get("run_id") or "") == rid:
                    runs[i] = record
                    replaced = True
                    break
        if not replaced:
            runs.insert(0, record)

        # Cap / auto-prune to newest N (default 20, or env-override)
        max_runs_str = os.environ.get("ANCHOR_GANDALF_MAX_RUNS", "20").strip()
        try:
            max_runs = int(max_runs_str)
        except ValueError:
            max_runs = 20
        if max_runs > 0:
            runs = runs[:max_runs]
            
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(runs, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)


def _add_gitignore_best_effort(folder_path) -> None:
    """Best-effort: add ``gandalf/`` to the project ``.gitignore`` so regenerable
    analysis doesn't clutter git status. Never raises."""
    try:
        gi = Path(folder_path) / ".gitignore"
        existing = ""
        if gi.exists():
            existing = gi.read_text(encoding="utf-8", errors="replace")
        lines = [ln.strip() for ln in existing.splitlines()]
        if "gandalf/" in lines or "/gandalf/" in lines or "gandalf" in lines:
            return
        sep = "" if (existing == "" or existing.endswith("\n")) else "\n"
        with gi.open("a", encoding="utf-8") as fh:
            fh.write(sep + "gandalf/\n")
    except OSError:
        pass


# ── Public engine ────────────────────────────────────────────────────────────

# ── Wave 2 (foundry-v2) — the HOST-ENFORCED journaling write-back ────────────

def _aggregate_model_cost(job_ids) -> dict:
    """Best-effort model + billed-cost + cache-token rollup over a run's jobs.

    Reads only what ``job_runner`` already persisted: each record's ``backend``
    + ``cost`` block, plus the stream result envelope's cache-token counters
    (``usage.cache_read_input_tokens`` / ``cache_creation_input_tokens``).
    Honest zeros / ``unrecorded`` when the runner reported nothing (a stubbed
    run has no cost). Never raises."""
    models = set()
    billed = 0.0
    inp = out = cache = jobs = 0
    for jid in (job_ids or []):
        try:
            rec = _jr.load_record(jid) or {}
        except Exception:
            continue
        jobs += 1
        if rec.get("backend"):
            models.add(str(rec["backend"]))
        c = rec.get("cost") or {}
        try:
            billed += float(c.get("total_cost_usd") or 0.0)
            inp += int(c.get("input_tokens") or 0)
            out += int(c.get("output_tokens") or 0)
        except (TypeError, ValueError):
            pass
        try:
            for line in reversed(_jr.all_lines(jid)):
                s = line.strip()
                if not (s.startswith("{") and '"usage"' in s):
                    continue
                try:
                    obj = json.loads(s)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(obj, dict):
                    continue
                usage = obj.get("usage") or {}
                try:
                    cache += int(usage.get("cache_read_input_tokens") or 0)
                    cache += int(usage.get("cache_creation_input_tokens") or 0)
                except (TypeError, ValueError):
                    pass
                break
        except Exception:
            pass
    return {
        "model": ",".join(sorted(models)) if models else "unrecorded",
        "billed_cost_usd": round(billed, 6),
        "cache_tokens": cache,
        "input_tokens": inp,
        "output_tokens": out,
        "jobs": jobs,
    }


def _journal_writeback(run_id, ts, pid, folder, record, *, graded=None,
                       draft=None):
    """Wave 2 (foundry-v2): auto-journal one finished run through the seam.

    Every gandalf run through Anchor — done, failed, or cancelled — appends
    the 7-field skeleton entry to ``<skill_dir>/journal/`` via the ONE
    write-back seam (``foundry_journal.journal_run_writeback``), with the
    heavy payloads (raw draft, graded output, index record) shunted to the
    droppable side channel. Capture is a by-product of the run — zero author
    action, no env toggle. Best-effort: journaling never crashes or blocks
    the run it records."""
    try:
        skill = _skill_dir()
        with _ACTIVE_RUNS_LOCK:
            r = _ACTIVE_RUNS.get(run_id) or {}
            job_ids = list(r.get("job_ids") or [])
            jid0 = r.get("job_id")
        if jid0 and jid0 not in job_ids:
            job_ids.insert(0, jid0)
        finished = time.time()
        outcome = record.get("status") or ("done" if record.get("ok")
                                           else "failed")
        linkage = {
            "project_id": str(pid),
            "run_id": run_id,
            "session_id": record.get("session_id") or run_id,
            "report_rel": record.get("report_rel"),
            "advisor_rel": record.get("advisor_rel"),
        }
        if record.get("reason"):
            linkage["reason"] = str(record["reason"])[:160]
        _fj.journal_run_writeback(
            skill,
            run_id=run_id,
            operation_kind="run",
            provenance="host-enforced:anchor.gandalf",
            model_cost=_aggregate_model_cost(job_ids),
            inputs={"analysis_folder": str(folder), "project_id": str(pid),
                    "job_ids": job_ids, "skill_dir": str(skill)},
            outputs={"index_record": record, "graded": graded,
                     "raw_draft": draft},
            verdict=(record.get("verdict") or record.get("reason")
                     or outcome),
            timing={"started_ts": round(float(ts), 3),
                    "finished_ts": round(finished, 3),
                    "duration_s": round(finished - float(ts), 3)},
            outcome=outcome,
            linkage=linkage,
        )
    except Exception:
        pass


def run_gandalf(folder_path, project_id, *, force=False, env=None, status_cb=None,
                store_folder=None, tier=DEFAULT_TIER) -> dict:
    """Run one full two-stage Gandalf analysis and store the result.

    ``folder_path`` is the ANALYSIS scope (what Gandalf reads); ``store_folder``
    (default: the analysis folder) is where the run is RECORDED — the index +
    ``gandalf/run-*/`` artifacts. They must be split whenever a caller re-scopes
    the analysis away from the project's registry folder (the dashboard read
    path resolves the index off the REGISTRY folder, so a run stored anywhere
    else is invisible — the 2026-07 ``__dashboard__`` regression)."""
    folder = str(folder_path)
    store = str(store_folder) if store_folder else folder
    pid = str(project_id)
    tier = _normalize_tier(tier)
    ts = time.time()
    run_id = "run-" + str(int(ts * 1000))
    run_rel = f"{GANDALF_DIRNAME}/{run_id}"

    try:
        import session_registry
        session_registry.register_session(
            project_id=pid,
            lane="gandalf",
            status=session_registry.STATUS_RUNNING,
            session_id=run_id
        )
    except Exception:
        pass

    with _ACTIVE_RUNS_LOCK:
        # folder/project_id are carried so cancel_run can record the cancelled
        # outcome into the index without waiting for this worker to unwind.
        # job_ids holds the whole map-reduce fan-out so cancel tree-kills all shards.
        _ACTIVE_RUNS[run_id] = {
            "job_id": None, "job_ids": [], "proc": None, "cancelled": False,
            # "folder" feeds cancel_run's index write — the STORE folder, so a
            # cancelled record lands where the read path looks.
            "folder": store, "project_id": pid, "index_recorded": False,
        }

    # Wave 9: write an IN-PROGRESS index record up front so the tab exposes a
    # live "running" state while the map-reduce fans out (index ok:false). It is
    # UPSERTED into the terminal record on completion (never a duplicate row).
    with _ACTIVE_RUNS_LOCK:
        _pre_cancelled = _ACTIVE_RUNS[run_id]["cancelled"]
    if not _pre_cancelled:
        try:
            _append_index(store, pid, {
                "schema_version": GANDALF_INDEX_SCHEMA_VERSION,
                "run_id": run_id, "ts": ts, "ok": False, "verdict": "",
                "degraded": True, "cross_model": False,
                "report_rel": None, "exec_rel": None, "advisor_rel": None,
                "session_id": run_id, "status": "running", "in_progress": True,
                "tier": tier,
            })
        except Exception:
            pass

    ok = False
    reason = "unknown"
    graded = None
    draft = None
    finalized = False
    # Shared finalize locals (set by whichever mode branch runs; read by the
    # single record build below).
    verdict = ""
    report_rel = None
    exec_rel = None
    advisor_rel = None
    degraded = True
    cross_model = False

    try:
        # Check if cancelled early
        with _ACTIVE_RUNS_LOCK:
            is_cancelled = _ACTIVE_RUNS[run_id]["cancelled"]
        if is_cancelled:
            reason = "cancelled"
        else:
            if status_cb: status_cb("Reading files (Stage A)...")

            # Wave 1: ContextSizer & Dynamic Router
            context_size = scan_project_context(folder)
            frontier_max_str = os.environ.get("ANCHOR_FRONTIER_MAX", "100000").strip()
            try:
                frontier_max = float(frontier_max_str)
            except ValueError:
                frontier_max = 100000.0

            actual_env = dict(env) if env is not None else {}
            # Tier → the canonical Claude reasoner model. The tile's read now runs
            # on the SAME top-tier Claude seat the canonical regular/heavy Gandalf
            # uses (heavy=claude-fable-5, standard=claude-opus-4-8) — the fix for
            # the shallow reads (Stage A previously ran on the CLI's default
            # model). The chosen tier is AUTHORITATIVE (overrides any inherited
            # ANTHROPIC_MODEL). TRIO_TIER rides along for tier-honoring seats.
            actual_env["ANTHROPIC_MODEL"] = TIER_ANTHROPIC_MODEL[tier]
            actual_env["TRIO_TIER"] = tier
            # Let the agentic skill's canonical live 5:1 (Claude reasoner + Gemini
            # adversarial reviews) actually fire; harmless for the legacy path.
            actual_env.setdefault("CRUCIBLE_AGENT_LIVE", "1")
            if context_size > frontier_max:
                # Over-cap trees route Gemini-backend shards to the strong
                # long-context tier. (Was the RETIRED gemini-1.5-pro — a dead
                # model id that made every over-cap Gemini shard fail.)
                actual_env["GEMINI_MODEL"] = "gemini-3.1-pro"
                actual_env["TRIO_MODEL"] = "gemini-3.1-pro"

            _use_mapreduce = _gandalf_mode() != MODE_AGENTIC
            if not _use_mapreduce:
                # CANONICAL path (default): run the real gandalf/gandalf-heavy
                # skill agentically over the folder — the skill decides map-reduce,
                # writes its report, and runs its own 5:1. Capture report + summary.
                _res = _run_stage_agentic(folder, store, run_id, run_rel, ts, tier,
                                          env=actual_env, status_cb=status_cb)
                if (not _res.get("ok")) and _res.get("reason") == "launch-failed":
                    # Claude unavailable / spawn failed (e.g. a Claude-absent
                    # collaborator host) → fall back to the legacy map-reduce path
                    # so a read is still produced (honest degrade, not a hard fail).
                    if status_cb:
                        status_cb("Claude unavailable; falling back to map-reduce...")
                    _use_mapreduce = True
                else:
                    ok = bool(_res.get("ok"))
                    reason = _res.get("reason") or reason
                    verdict = _res.get("verdict") or ""
                    report_rel = _res.get("report_rel")
                    exec_rel = _res.get("exec_rel")
                    advisor_rel = _res.get("advisor_rel")
                    degraded = bool(_res.get("degraded", True))
                    cross_model = bool(_res.get("cross_model", False))
            if _use_mapreduce:
                # LEGACY / FALLBACK (ANCHOR_GANDALF_MODE=mapreduce, or the agentic
                # launch failed on a Claude-absent host): homegrown shard→grade.
                draft, reason = _run_stage_a_mapreduce(folder, env=actual_env,
                                                       run_id=run_id)
                with _ACTIVE_RUNS_LOCK:
                    is_cancelled = _ACTIVE_RUNS.get(run_id, {}).get("cancelled", False)
                if is_cancelled:
                    reason = "cancelled"
                elif draft is not None:
                    if status_cb: status_cb("Synthesizing (Stage B)...")
                    graded, reason = _run_stage_b(draft, run_id=run_id)
                with _ACTIVE_RUNS_LOCK:
                    is_cancelled = _ACTIVE_RUNS.get(run_id, {}).get("cancelled", False)
                if is_cancelled:
                    reason = "cancelled"
                ok = (graded is not None) and (reason != "cancelled")
                if ok:
                    verdict = _one_line_verdict(graded)
                    degraded = bool(graded.get("degraded"))
                    cross_model = bool(graded.get("cross_model"))
                    try:
                        run_dir = _runs_dir(store) / run_id
                        run_dir.mkdir(parents=True, exist_ok=True)
                        report_md = _render_full_report(graded, run_id=run_id, when=ts)
                        exec_md = _render_exec_summary(graded, run_id=run_id, when=ts)
                        (run_dir / REPORT_MD).write_text(report_md, encoding="utf-8")
                        (run_dir / EXEC_SUMMARY_MD).write_text(exec_md, encoding="utf-8")
                        (run_dir / ADVISOR_OUTPUT_JSON).write_text(
                            json.dumps(graded, indent=2, ensure_ascii=False),
                            encoding="utf-8")
                        report_rel = f"{run_rel}/{REPORT_MD}"
                        exec_rel = f"{run_rel}/{EXEC_SUMMARY_MD}"
                        advisor_rel = f"{run_rel}/{ADVISOR_OUTPUT_JSON}"
                        _add_gitignore_best_effort(store)
                    except OSError as exc:
                        ok = False
                        reason = "artifact-write-failed:" + str(exc)[:160]
                        report_rel = None
                        exec_rel = None
                        advisor_rel = None

        record = {
            "schema_version": GANDALF_INDEX_SCHEMA_VERSION,
            "run_id": run_id,
            "ts": ts,
            "ok": bool(ok),
            "verdict": verdict,
            "degraded": bool(degraded),
            "cross_model": bool(cross_model),
            "report_rel": report_rel,
            "exec_rel": exec_rel,
            "advisor_rel": advisor_rel,
            "session_id": run_id,
            "status": "cancelled" if reason == "cancelled" else ("done" if ok else "failed"),
            "in_progress": False,
            "tier": tier,
        }
        if not ok:
            record["reason"] = reason or "unknown"

        # If cancel_run already recorded the cancelled outcome in the index
        # (the worker may still be unwinding a killed Stage-A/B), don't write a
        # duplicate record for the same run_id.
        already_recorded = False
        with _ACTIVE_RUNS_LOCK:
            r = _ACTIVE_RUNS.get(run_id)
            if r and r.get("index_recorded"):
                already_recorded = True
        wrote_terminal = already_recorded
        if not already_recorded:
            try:
                _append_index(store, pid, record)
                wrote_terminal = True
            except Exception:
                # Terminal index write failed (lock/IO contention). Do NOT mark the
                # run finalized — leave the finally-block crash-reconcile free to
                # write an honest terminal row, so a failed write can never leave a
                # perpetual in_progress "still running" ghost.
                wrote_terminal = False

        # Wave 2 (foundry-v2): host-enforced journaling — EVERY run through
        # Anchor (done/failed/cancelled) auto-appends its 7-field skeleton
        # entry to the skill journal via the write-back seam. Zero author
        # action; never raises.
        _journal_writeback(run_id, ts, pid, folder, record, graded=graded,
                           draft=(draft if isinstance(draft, dict) else None))
        finalized = wrote_terminal

        out = dict(record)
        out["ok"] = bool(ok)
        if not ok:
            out["reason"] = reason or "unknown"
        return out

    finally:
        # Wave 9: if the run raised before writing a terminal record (e.g. an
        # unexpected crash in the ContextSizer), reconcile the dangling in-progress
        # index row to an honest failed record so no "running" ghost persists.
        if not finalized:
            with _ACTIVE_RUNS_LOCK:
                r = _ACTIVE_RUNS.get(run_id)
                _already = bool(r and r.get("index_recorded"))
            if not _already:
                try:
                    _append_index(store, pid, {
                        "schema_version": GANDALF_INDEX_SCHEMA_VERSION,
                        "run_id": run_id, "ts": ts, "ok": False, "verdict": "",
                        "degraded": True, "cross_model": False,
                        "report_rel": None, "exec_rel": None, "advisor_rel": None,
                        "session_id": run_id, "status": "failed",
                        "in_progress": False, "reason": "run-crashed",
                        "tier": tier,
                    })
                except Exception:
                    pass
            # Wave 2 (foundry-v2): a crashed run still journals — the
            # host-enforced skeleton entry records the honest failure.
            _journal_writeback(run_id, ts, pid, folder, {
                "run_id": run_id, "ok": False, "status": "failed",
                "reason": "run-crashed", "session_id": run_id,
                "verdict": "", "report_rel": None, "advisor_rel": None,
            })
        try:
            import session_registry
            with _ACTIVE_RUNS_LOCK:
                is_cancelled = _ACTIVE_RUNS[run_id]["cancelled"]
            if is_cancelled or reason == "cancelled":
                st = "cancelled"
            else:
                st = session_registry.STATUS_DONE if ok else session_registry.STATUS_FAILED
            session_registry.update_session(run_id, status=st)
        except Exception:
            pass

        with _ACTIVE_RUNS_LOCK:
            _ACTIVE_RUNS.pop(run_id, None)


def run_gandalf_if_absent(folder_path, project_id, env=None, status_cb=None,
                          store_folder=None, tier=DEFAULT_TIER) -> dict:
    """First-scan idempotent: run Gandalf ONLY if no prior run exists.

    The absence check reads the STORE index (where the dashboard reads), so a
    re-scoped analysis folder never causes duplicate first-scan runs."""
    try:
        if _load_index(store_folder or folder_path, project_id):
            return {"ok": True, "skipped": True, "reason": "prior-run-exists"}
    except Exception:
        pass
    return run_gandalf(folder_path, project_id, env=env, status_cb=status_cb,
                       store_folder=store_folder, tier=tier)


def _session_running_alive(run_id) -> bool:
    """True iff the run's session-registry record is RUNNING **and** its
    recorded process is verifiably alive (identity-probed PID).

    Gandalf runs register their session without a PID, so a prior instance's
    stale "running" record never counts as alive — only a record that carries a
    PID resolving to a live process does. Never raises."""
    try:
        import session_registry
        rec = session_registry.get_session(str(run_id))
        if not rec or rec.get("status") != session_registry.STATUS_RUNNING:
            return False
        pid = rec.get("pid")
        if not pid:
            return False
        import proc_probe
        return proc_probe.creation_time(pid) is not None
    except Exception:
        return False


def reconcile_dangling_runs(folder_path, project_id) -> int:
    """Boot reconcile: no perpetual "running" Gandalf row after a restart.

    For every index row with ``in_progress: true`` whose ``run_id`` is NOT in
    ``_ACTIVE_RUNS`` (an in-flight run of THIS process) and whose
    session-registry record is not RUNNING-alive, upsert the row to an honest
    terminal record (``status: 'failed'``, ``reason: 'interrupted-by-restart'``,
    ``in_progress: false``). Returns the reconciled count. Never raises."""
    count = 0
    try:
        runs = _load_index(folder_path, project_id)
        if not runs:
            return 0
        with _ACTIVE_RUNS_LOCK:
            active_ids = set(_ACTIVE_RUNS.keys())
        for r in runs:
            if not r.get("in_progress"):
                continue
            rid = str(r.get("run_id") or "")
            if not rid or rid in active_ids:
                continue
            if _session_running_alive(rid):
                continue
            record = dict(r)
            record["ok"] = False
            record["status"] = "failed"
            record["in_progress"] = False
            record["reason"] = "interrupted-by-restart"
            try:
                _append_index(folder_path, project_id, record)
            except Exception:
                continue
            count += 1
            # Best-effort: the dangling session-registry "running" row (no live
            # process) goes terminal too, so it can't feed the orphan banner.
            try:
                import session_registry
                rec = session_registry.get_session(rid)
                if rec and rec.get("status") == session_registry.STATUS_RUNNING:
                    session_registry.update_session(
                        rid, status=session_registry.STATUS_FAILED)
            except Exception:
                pass
    except Exception:
        pass
    return count


# ── Read seams (SAFE projections — never absolute paths) ─────────────────────

def _safe_run_view(record: dict) -> dict:
    """SAFE projection of one index record (no absolute paths)."""
    r = record if isinstance(record, dict) else {}
    view = {
        "run_id": str(r.get("run_id") or ""),
        "ts": r.get("ts"),
        "ok": bool(r.get("ok")),
        "verdict": str(r.get("verdict") or ""),
        "degraded": bool(r.get("degraded", True)),
        "cross_model": bool(r.get("cross_model", False)),
        "report_rel": r.get("report_rel"),
        "exec_rel": r.get("exec_rel"),
        "advisor_rel": r.get("advisor_rel"),
        # Wave 9: surface the lifecycle so the UI can show an in-progress/queued
        # indicator while a map-reduce run is still fanning out (index ok:false).
        "status": str(r.get("status") or ""),
        "in_progress": bool(r.get("in_progress")),
        # Which tier produced this read (regular Opus vs Gandalf-Heavy Fable-5),
        # so the tile can badge it. Older records w/o the field read "standard".
        "tier": _normalize_tier(r.get("tier")),
    }
    reason = r.get("reason")
    if reason:
        view["reason"] = str(reason)
    return view


def list_runs(folder_path, project_id) -> list:
    """Newest-first SAFE projections of the project's Gandalf runs."""
    runs = _load_index(folder_path, project_id)
    return [_safe_run_view(r) for r in runs]


def get_run(folder_path, project_id, run_id) -> dict:
    """The SAFE projection of one run by id, or ``None``. Read-only."""
    for r in _load_index(folder_path, project_id):
        if str(r.get("run_id") or "") == str(run_id):
            return _safe_run_view(r)
    return None


# ── Write seams — archive/retire ─────────────────────────────────────────────

def _rewrite_index(folder_path, project_id, runs) -> bool:
    """Atomically overwrite the index with ``runs`` (already filtered). Caller
    holds ``paths.WRITE_LOCK``. Honest False on a write error."""
    p = _index_path(folder_path, project_id)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(runs, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(p)
        return True
    except OSError:
        return False


def _remove_run_artifacts(folder_path, run_id) -> None:
    """Best-effort: remove the ``<folder>/gandalf/run-<id>/`` artifact dir for a
    retired run. Never raises (regenerable analysis)."""
    rid = str(run_id or "")
    if not rid or _unsafe_seg(rid):
        return
    try:
        run_dir = _runs_dir(folder_path) / rid
        if run_dir.is_dir():
            shutil.rmtree(run_dir, ignore_errors=True)
    except OSError:
        pass


def _unsafe_seg(seg: str) -> bool:
    """Reject a path-segment that could traverse (defense-in-depth on run_id)."""
    s = str(seg or "")
    return (not s) or ("/" in s) or ("\\" in s) or (".." in s)


def delete_run(folder_path, project_id, run_id) -> dict:
    """Archive/retire ONE Gandalf run: drop its record from the internal index
    and best-effort remove its on-disk ``gandalf/run-<id>/`` artifact dir.

    Returns ``{ok, removed}`` — ``removed`` is False when no record matched the
    id (idempotent). Written atomically under ``paths.WRITE_LOCK``. Never raises.
    """
    rid = str(run_id or "")
    if not rid:
        return {"ok": False, "removed": False, "reason": "run_id required"}
    with _paths.WRITE_LOCK:
        runs = _load_index(folder_path, project_id)
        kept = [r for r in runs if str(r.get("run_id") or "") != rid]
        removed = len(kept) != len(runs)
        if removed and not _rewrite_index(folder_path, project_id, kept):
            return {"ok": False, "removed": False, "reason": "index-write-failed"}
        if removed:
            _remove_run_artifacts(folder_path, rid)
    return {"ok": True, "removed": bool(removed)}


def clear_failed_runs(folder_path, project_id) -> dict:
    """Bulk-retire every FAILED run (``ok:false`` — status failed/error) from the
    index, leaving completed runs untouched, and best-effort remove their artifact
    dirs. Returns ``{ok, removed}`` (count cleared). Atomic; never raises."""
    with _paths.WRITE_LOCK:
        runs = _load_index(folder_path, project_id)
        failed = [r for r in runs if not bool(r.get("ok"))]
        kept = [r for r in runs if bool(r.get("ok"))]
        if not failed:
            return {"ok": True, "removed": 0}
        if not _rewrite_index(folder_path, project_id, kept):
            return {"ok": False, "removed": 0, "reason": "index-write-failed"}
        for r in failed:
            _remove_run_artifacts(folder_path, str(r.get("run_id") or ""))
    return {"ok": True, "removed": len(failed)}


def cancel_run(run_id: str) -> bool:
    """Active cancel (tree-kill) an in-flight Gandalf run."""
    with _ACTIVE_RUNS_LOCK:
        run = _ACTIVE_RUNS.get(run_id)
        if not run:
            try:
                import session_registry
                rec = session_registry.get_session(run_id)
                if rec and rec.get("status") == session_registry.STATUS_RUNNING:
                    session_registry.update_session(run_id, status="cancelled")
            except Exception:
                pass
            return False

        run["cancelled"] = True

        # 1) If in Stage A (job_runner jobs are active) — cancel the WHOLE
        # map-reduce fan-out (every shard job), not just the first.
        job_ids = list(run.get("job_ids") or [])
        primary = run.get("job_id")
        if primary and primary not in job_ids:
            job_ids.append(primary)
        for jid in job_ids:
            try:
                import job_runner
                job_runner.cancel(jid)
            except Exception:
                pass

        # 2) If in Stage B (subprocess is active)
        proc = run.get("proc")
        if proc:
            try:
                pid = proc.pid
                if pid:
                    import proc_probe
                    proc_probe.tree_kill(pid)
            except Exception:
                pass
            try:
                proc.kill()
            except Exception:
                pass

        # Update the session registry record to cancelled
        try:
            import session_registry
            session_registry.update_session(run_id, status="cancelled")
        except Exception:
            pass

        # Record the cancelled outcome in the gandalf index now (Wave 1: active
        # cancel "records the cancelled outcome"). The worker thread may still be
        # unwinding a tree-killed child, so record here and mark it so the worker
        # does not write a duplicate record for the same run_id.
        folder = run.get("folder")
        pid = run.get("project_id")
        if folder and pid:
            try:
                _append_index(folder, pid, {
                    "schema_version": GANDALF_INDEX_SCHEMA_VERSION,
                    "run_id": run_id,
                    "ts": time.time(),
                    "ok": False,
                    "verdict": "",
                    "degraded": True,
                    "cross_model": False,
                    "report_rel": None,
                    "exec_rel": None,
                    "advisor_rel": None,
                    "session_id": run_id,
                    "status": "cancelled",
                    "in_progress": False,
                    "reason": "cancelled",
                })
                run["index_recorded"] = True
            except Exception:
                pass

        return True


def cancel_gandalf_run(project_id) -> bool:
    """Look up the running run by project_id and cancel it."""
    target_run_id = None
    with _ACTIVE_RUNS_LOCK:
        for run_id, run in _ACTIVE_RUNS.items():
            if str(run.get("project_id")) == str(project_id):
                target_run_id = run_id
                break
    if target_run_id:
        # Flip the cancelled flag + tree-kill (Stage-A job / Stage-B proc). Do NOT
        # pop _ACTIVE_RUNS here: the run_gandalf worker still reads the cancelled
        # flag to bail out, and its finally is what pops the entry and finalizes the
        # session registry. Popping early KeyErrors that finally (stuck "running")
        # and races the worker's cancel check (job runs to completion).
        return cancel_run(target_run_id)
    return False
