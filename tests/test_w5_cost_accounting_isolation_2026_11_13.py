#!/usr/bin/env python3
"""Wave 5 (2026-11-13) — Honest Cost Accounting, Attribution, Locking & 5-State Failure Contract."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import anchor_healthcheck
import paths
import rnd_registry
import session_registry
from steward_cockpit import aegis_session, anvil_session, code_jobs, skill_jobs, steward_engine, steward_routes
import usage_capture
import usage_index


def _clear_spend_caches() -> None:
    with steward_routes._ROLLUP_LOCK:
        steward_routes._ROLLUP_CACHE.clear()
    with steward_routes._STATE_LOCK:
        steward_routes._STATE_CACHE.clear()
    with steward_routes._GLOBAL_USAGE_LOCK:
        steward_routes._GLOBAL_USAGE_CACHE.clear()
    if hasattr(session_registry, "_drop_read_cache"):
        session_registry._drop_read_cache()


@pytest.fixture
def w5_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Hermetic data, sidecar, settings, state, and code-jobs directories."""
    data_dir = tmp_path / "anchor_data"
    sidecar_dir = tmp_path / "sidecars"
    settings_dir = tmp_path / "settings"
    cj_dir = tmp_path / "Anchor-code-jobs"
    for d in (data_dir, data_dir / ".anchor", sidecar_dir, settings_dir, cj_dir):
        d.mkdir(parents=True, exist_ok=True)

    state_file = data_dir / "steward-cockpit-state.json"
    state_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(sidecar_dir))
    monkeypatch.setenv("ANCHOR_SETTINGS_DIR", str(settings_dir))
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(cj_dir))
    monkeypatch.setattr(steward_engine, "STATE_FILE", state_file)
    monkeypatch.setattr(paths, "code_jobs_dir", lambda: cj_dir)
    monkeypatch.setattr(paths, "legacy_code_jobs_dir", lambda: cj_dir)

    _clear_spend_caches()
    try:
        yield SimpleNamespace(
            data_dir=data_dir,
            sidecar_dir=sidecar_dir,
            settings_dir=settings_dir,
            cj_dir=cj_dir,
            state_file=state_file,
        )
    finally:
        _clear_spend_caches()


def test_cockpit_spend_includes_children_best_pricing_unpriced_label_baseline_migration_and_live_model_policy(
    w5_env, tmp_path: Path
):
    """Verify 'best' pricing, scalar fallback vs unlisted model, baseline floor, child rollup, and UI slice."""
    prices = steward_engine.api_list_prices().get("usd_per_million") or {}
    assert prices.get("best") == {"input": 15.0, "cached_input": 1.5, "output": 75.0}

    ck_raw = {
        "tokens": 150_000,
        "turns": 1,
        "unpriced_turns": 1,
        "cost_complete": False,
        "usage_checkpoints": {
            "ck1": {
                "session_id": "sess-best-1",
                "finalized": True,
                "updated_at": "2026-11-13T12:00:00Z",
                "counts": {
                    "input_tokens": 100_000,
                    "cache_read_input_tokens": 50_000,
                    "output_tokens": 0,
                },
            }
        },
    }
    # Known family ('gemini') preserves family default ('gemini-4-argon-high': 2.5 / 0.25 / 15.0)
    u_gem = steward_engine._backfill_usage_estimate(
        steward_engine._usage_snapshot(ck_raw),
        ck_raw,
        {"family": "gemini", "model": "best"},
    )
    assert u_gem["estimated_spend"] == pytest.approx(0.2625, abs=1e-4)
    assert u_gem["estimated_turns"] == 1

    # Unknown family + 'best' falls back directly to 'best' (15.0 / 1.5 / 75.0) in api_list_prices.json
    u_unknown_fam = steward_engine._backfill_usage_estimate(
        steward_engine._usage_snapshot(ck_raw),
        ck_raw,
        {"family": "", "model": "best"},
    )
    assert u_unknown_fam["estimated_spend"] == pytest.approx(1.575, abs=1e-4)
    assert u_unknown_fam["estimated_turns"] == 1

    # Scalar-token fallback (0.95 input / 0.85 cached subset / 0.05 output) when checkpoints are absent
    raw_scalar = {
        "tokens": 200_000,
        "turns": 1,
        "unpriced_turns": 1,
        "cost_complete": False,
        "model": "best",
    }
    u_scalar = steward_engine._backfill_usage_estimate(
        steward_engine._usage_snapshot(raw_scalar),
        raw_scalar,
        {"family": "claude", "model": "best"},
    )
    # 20k uncached * $15/M ($0.30) + 170k cached * $1.5/M ($0.255) + 10k output * $75/M ($0.75) = $1.305
    assert u_scalar["estimated_spend"] == pytest.approx(1.305, abs=1e-4)
    assert u_scalar["estimated_turns"] == 1

    # Unlisted custom model keeps estimated_spend == 0 and unpriced_turns > 0 (honest unpriced state)
    raw_unlisted = {
        "tokens": 180_000,
        "turns": 2,
        "unpriced_turns": 2,
        "cost_complete": False,
        "model": "unlisted-mystery-v9",
    }
    u_unlisted = steward_engine._backfill_usage_estimate(
        steward_engine._usage_snapshot(raw_unlisted),
        raw_unlisted,
        {"family": "custom", "model": "unlisted-mystery-v9", "model_served": "unlisted-mystery-v9"},
    )
    assert u_unlisted["estimated_spend"] == 0.0
    assert u_unlisted["estimated_turns"] == 0
    assert u_unlisted["unpriced_turns"] == 2

    # Absent usage_baseline.json -> {}
    assert steward_engine.load_usage_baseline(w5_env.data_dir) == {}

    proj_dir = tmp_path / "proj_cockpit_spend"
    effort_dir = proj_dir / "effort_alpha"
    effort_dir.mkdir(parents=True, exist_ok=True)
    (effort_dir / "ECGBERHT.md").write_text("# Effort Alpha\n", encoding="utf-8")
    proj = rnd_registry.add_project("Cockpit Spend Alpha", str(proj_dir))
    pid = proj["id"]

    baseline_path = w5_env.data_dir / ".anchor" / "usage_baseline.json"
    baseline_path.write_text(
        json.dumps(
            {
                "floors": {
                    f"{pid}::{effort_dir}": {
                        "reported_spend": 12.50,
                        "tokens": 50_000,
                        "turns": 4,
                        "secs": 120,
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert "floors" in steward_engine.load_usage_baseline(w5_env.data_dir)

    w5_env.state_file.write_text(
        json.dumps(
            {
                str(effort_dir): {
                    "cli": "claude",
                    "usage": {
                        "spend": 2.00,
                        "reported_spend": 2.00,
                        "cost_complete": True,
                        "tokens": 10_000,
                        "turns": 1,
                        "secs": 30,
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    usage_index.append_rows(
        pid,
        [
            {
                "key": "child:s1:a1",
                "source": "subagent",
                "effort_dir": str(effort_dir),
                "tokens": 20_000,
                "cost_usd": 0.50,
                "usage_state": "measured",
                "duration_ms": 15_000,
                "model": "claude-sonnet-5-5",
            },
            {
                "key": "child:s1:a2",
                "source": "subagent",
                "effort_dir": str(effort_dir),
                "tokens": 100_000,
                "cost_usd": None,
                "usage_state": "unpriced",
                "duration_ms": 25_000,
                "cli": "chatgpt",
                "model": "gpt-6-astra",
                "input_tokens": 80_000,
                "cache_read_input_tokens": 10_000,
                "output_tokens": 10_000,
            },
            {
                "key": "code-job:j1",
                "source": "job",
                "effort_dir": str(effort_dir),
                "tokens": 30_000,
                "cost_usd": 1.25,
                "usage_state": "measured",
                "duration_ms": 20_000,
                "model": "claude-opus-5-5",
            },
            {
                "key": "seat:r1",
                "source": "seat",
                "effort_dir": str(effort_dir),
                "tokens": 10_000,
                "cost_usd": 0.25,
                "usage_state": "measured",
                "duration_ms": 10_000,
                "model": "gemini-4-argon",
            },
        ],
    )

    roll = steward_routes._usage_rollup_fresh(str(effort_dir))
    assert roll["ok"] is True
    assert roll["baseline_floor"]["reported_spend"] == pytest.approx(12.50, abs=1e-4)
    assert roll["total"]["reported_spend"] == pytest.approx(12.50, abs=1e-4)
    assert roll["children"]["count"] == 2
    assert roll["children"]["reported_spend"] == pytest.approx(0.50, abs=1e-4)
    # gpt-6-astra: 80k * $10/M ($0.80) + 10k * $1/M ($0.01) + 10k * $50/M ($0.50) = $1.31
    assert roll["children"]["estimated_spend"] == pytest.approx(1.31, abs=1e-4)
    assert roll["children"]["combined_spend"] == pytest.approx(1.81, abs=1e-4)

    twc = roll["total_with_children"]
    assert twc["reported_spend"] == pytest.approx(14.50, abs=1e-4)
    assert twc["estimated_spend"] == pytest.approx(1.31, abs=1e-4)
    assert twc["combined_spend"] == pytest.approx(15.81, abs=1e-4)
    assert twc["tokens"] == 210_000

    # Verify shared.js floor migration and execute the real spend block in Node if available
    shared_js_path = REPO_ROOT / "steward_cockpit" / "static" / "shared.js"
    js_src = shared_js_path.read_text(encoding="utf-8")
    for removed_ident in ("_MBA_FLOOR", "_MAGI_FLOOR", "_LEDGER_FLOORS", "Total $0.00"):
        assert removed_ident not in js_src

    start_marker = '    const spend = $("[data-spend]");'
    end_marker = '    const wake = $("[data-wake]");'
    s_idx = js_src.index(start_marker)
    e_idx = js_src.index(end_marker, s_idx)
    spend_slice = js_src[s_idx:e_idx]

    node_bin = shutil.which("node")
    if node_bin:
        js_harness = r"""
const fs = require("fs");
const slice = fs.readFileSync(process.argv[1], "utf8");

function makeNode(tag, cls, txt) {
  return {
    tagName: String(tag || "div").toUpperCase(),
    className: cls || "",
    _text: txt === undefined || txt === null ? "" : String(txt),
    dataset: {},
    style: {},
    children: [],
    listeners: {},
    hidden: false,
    colSpan: 1,
    get textContent() {
      return this._text + this.children.map((c) => c.textContent).join("");
    },
    set textContent(v) {
      this._text = v === undefined || v === null ? "" : String(v);
      this.children = [];
    },
    appendChild(child) {
      this.children.push(child);
      return child;
    },
    contains(other) {
      return other === this || this.children.some((c) => c.contains && c.contains(other));
    },
    addEventListener(ev, fn) {
      (this.listeners[ev] = this.listeners[ev] || []).push(fn);
    },
    click() {
      (this.listeners.click || []).forEach((fn) => fn({ stopPropagation() {}, target: this }));
    },
  };
}

function runRender(st, spendNode, docBody) {
  const window = { STEWARD_PID: "p1" };
  const DIR = "effort_alpha";
  const GENERAL = false;
  const personaName = () => "Ecgberht";
  const el = (t, c, tx) => makeNode(t, c, tx);
  const $ = (sel) => (sel === "[data-spend]" ? spendNode : null);
  const document = {
    body: docBody,
    addEventListener() {},
    querySelector(sel) {
      if (sel === "[data-spend-popover]") {
        return docBody.children.find((n) => n.dataset && n.dataset.spendPopover) || null;
      }
      return null;
    },
  };
  const fn = new Function("st", "$", "window", "DIR", "GENERAL", "personaName", "el", "document", slice);
  fn(st, $, window, DIR, GENERAL, personaName, el, document);
}

const body = makeNode("body", "");
const spend = makeNode("button", "");

// 1. Empty-but-valid
runRender({
  alive: false,
  turns: 0,
  tokens: 0,
  unpriced_turns: 0,
  usage_rollup: {
    ok: true,
    spend_state: "empty-but-valid",
    total: { reported_spend: 0, estimated_spend: 0, tokens: 0, turns: 0, unpriced_turns: 0, estimated_turns: 0, secs: 0 },
    jobs: { count: 0, reported_spend: 0, estimated_spend: 0, tokens: 0, secs: 0, unpriced_turns: 0, estimated_turns: 0 },
    children: { count: 0, reported_spend: 0, estimated_spend: 0, tokens: 0, secs: 0, unpriced_turns: 0, estimated_turns: 0 },
    seats: { count: 0, reported_spend: 0, estimated_spend: 0, tokens: 0, secs: 0, unpriced_turns: 0, estimated_turns: 0 },
  },
}, spend, body);
const emptySummary = spend.dataset.spendSummary;

// 2. Unpriced + live model_policy
runRender({
  alive: true,
  cli: "custom",
  turns: 2,
  tokens: 45000,
  unpriced_turns: 2,
  model_policy: { model_served: "gemini-4-argon-high", effort: "high" },
  usage_rollup: {
    ok: true,
    spend_state: "dependency-missing",
    total: { reported_spend: 0, estimated_spend: 0, tokens: 45000, turns: 2, unpriced_turns: 2, estimated_turns: 0, secs: 90, token_status: "reported" },
    jobs: { count: 0, reported_spend: 0, estimated_spend: 0, tokens: 0, secs: 0, unpriced_turns: 0, estimated_turns: 0 },
    children: { count: 0, reported_spend: 0, estimated_spend: 0, tokens: 0, secs: 0, unpriced_turns: 0, estimated_turns: 0 },
    seats: { count: 0, reported_spend: 0, estimated_spend: 0, tokens: 0, secs: 0, unpriced_turns: 0, estimated_turns: 0 },
  },
}, spend, body);
const unpricedSummary = spend.dataset.spendSummary;
const unpricedModel = spend._breakdownData.rows[0].model;
const unpricedRowSpend = spend._breakdownData.rows[0].spend;

// 3. Children + quarantine warning in popover
runRender({
  alive: true,
  cli: "claude",
  turns: 4,
  tokens: 50000,
  model_policy: { model_served: "claude-fable-5-1", reasoning_effort: "max" },
  usage_rollup: {
    ok: true,
    spend_state: "dependency-returns-garbage",
    warning: "Corrupt usage record quarantined (1 skipped)",
    total: { reported_spend: 12.5, estimated_spend: 0, tokens: 50000, turns: 4, unpriced_turns: 0, estimated_turns: 0, secs: 120, token_status: "reported" },
    jobs: { count: 1, reported_spend: 1.25, estimated_spend: 0, tokens: 30000, secs: 20, unpriced_turns: 0, estimated_turns: 0, token_status: "reported" },
    children: { count: 2, reported_spend: 0.5, estimated_spend: 1.31, tokens: 120000, secs: 40, unpriced_turns: 1, estimated_turns: 1, token_status: "reported" },
    seats: { count: 1, reported_spend: 0.25, estimated_spend: 0, tokens: 10000, secs: 10, unpriced_turns: 0, estimated_turns: 0, token_status: "reported" },
  },
}, spend, body);
spend.click();
const pop = body.children.find((n) => n.dataset && n.dataset.spendPopover);
const warnNode = pop ? pop.children.find((c) => c.className === "sp-warn") : null;

console.log(JSON.stringify({
  emptySummary,
  unpricedSummary,
  unpricedModel,
  unpricedRowSpend,
  kidsSummary: spend.dataset.spendSummary,
  rowModels: spend._breakdownData.rows.map((r) => r.model),
  warnText: warnNode ? warnNode.textContent : "",
}));
"""
        slice_file = tmp_path / "spend_slice.js"
        slice_file.write_text(spend_slice, encoding="utf-8")
        proc = subprocess.run(
            [node_bin, "-e", js_harness, str(slice_file)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=True,
        )
        ui_out = json.loads(proc.stdout.strip())
        assert ui_out["emptySummary"] == "No spend recorded yet"
        assert "$0.00" not in ui_out["emptySummary"]
        assert ui_out["unpricedSummary"].startswith("Unpriced \u00b7 ")
        assert "tok" in ui_out["unpricedSummary"] and ui_out["unpricedSummary"].endswith("\u25be")
        assert "$0.00" not in ui_out["unpricedSummary"]
        assert ui_out["unpricedModel"] == "gemini-4-argon-high \u00b7 high"
        assert ui_out["unpricedRowSpend"] == "Unpriced"
        assert "Total $15.81" in ui_out["kidsSummary"]
        assert "Sub-agent Swarm" in ui_out["rowModels"]
        assert ui_out["warnText"] == "Corrupt usage record quarantined (1 skipped)"


def test_usage_index_token_breakdown_cross_process_concurrent_ingest_rebuild_and_lock_timeout(
    w5_env, tmp_path: Path
):
    """Verify schema v2 token breakdown persistence, 2-process append+rebuild concurrency, and LockBusyError."""
    assert usage_index.INDEX_SCHEMA_VERSION == 2
    assert usage_index.DEFAULT_LOCK_TIMEOUT_S == 5.0

    proj_dir = tmp_path / "proj_index_v2"
    effort_dir = proj_dir / "effort_v2"
    effort_dir.mkdir(parents=True, exist_ok=True)
    proj = rnd_registry.add_project("Index V2 Proj", str(proj_dir))
    pid = proj["id"]

    usage_capture.ingest_usage(
        "11111111-2222-3333-4444-555555555555",
        "job:v2-breakdown",
        index_key="job:v2-breakdown",
        source="job",
        native_id="v2-breakdown",
        tokens=14_500,
        cost_usd=0.42,
        project_id=pid,
        folder_path=str(proj_dir),
        effort_dir=str(effort_dir),
        cli="claude",
        model="claude-opus-5-5",
        usage={
            "input_tokens": 10_000,
            "cache_read_input_tokens": 3_000,
            "cache_creation_input_tokens": 500,
            "output_tokens": 1_000,
        },
    )

    insp = usage_index.inspect_project_index(pid)
    assert insp["ok"] is True
    assert insp["schema_version"] == 2
    assert insp["quarantined_count"] == 0
    assert len(insp["rows"]) == 1
    row0 = insp["rows"][0]
    assert row0["input_tokens"] == 10_000
    assert row0["cache_read_input_tokens"] == 3_000
    assert row0["cache_creation_input_tokens"] == 500
    assert row0["output_tokens"] == 1_000
    assert row0["model"] == "claude-opus-5-5"

    # Cross-process concurrent append_rows + rebuild_index across two real Python subprocesses
    pid_conc = "proj-conc-two-proc"
    worker_code = """
import os, sys
sys.path.insert(0, sys.argv[1])
import usage_index

pid = sys.argv[2]
prefix = sys.argv[3]
do_rebuild = sys.argv[4] == "1"

for i in range(25):
    usage_index.append_rows(pid, [{
        "key": f"{prefix}:{i}",
        "source": "job",
        "native_id": f"{prefix}-{i}",
        "tokens": 1000 + i,
        "input_tokens": 800 + i,
        "cache_read_input_tokens": 100,
        "cache_creation_input_tokens": 20,
        "output_tokens": 80,
        "model": "claude-sonnet-5-5",
        "usage_state": "unpriced",
    }], lock_timeout=5.0)
    if do_rebuild and i % 5 == 4:
        res = usage_index.rebuild_index(pid, lock_timeout=5.0)
        assert res["ok"] is True
        assert res["schema_version"] == usage_index.INDEX_SCHEMA_VERSION
"""
    child_env = dict(os.environ)
    child_env["ANCHOR_DATA_DIR"] = str(w5_env.data_dir)
    p_a = subprocess.Popen(
        [sys.executable, "-c", worker_code, str(REPO_ROOT), pid_conc, "procA", "0"],
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    p_b = subprocess.Popen(
        [sys.executable, "-c", worker_code, str(REPO_ROOT), pid_conc, "procB", "1"],
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    out_a, err_a = p_a.communicate(timeout=30)
    out_b, err_b = p_b.communicate(timeout=30)
    assert p_a.returncode == 0, f"Child A failed: {out_a} {err_a}"
    assert p_b.returncode == 0, f"Child B failed: {out_b} {err_b}"

    conc_insp = usage_index.inspect_project_index(pid_conc)
    assert conc_insp["ok"] is True
    assert conc_insp["quarantined_count"] == 0
    assert conc_insp["schema_version"] == 2
    keys = {r["key"] for r in conc_insp["rows"]}
    expected_keys = {f"procA:{i}" for i in range(25)} | {f"procB:{i}" for i in range(25)}
    assert keys == expected_keys
    assert all(r["model"] == "claude-sonnet-5-5" and r["output_tokens"] == 80 for r in conc_insp["rows"])

    # Cross-process lock contention -> LockBusyError("Usage index lock busy — retry")
    holder_code = """
import sys
sys.path.insert(0, sys.argv[1])
import paths, usage_index
lp = usage_index.lock_path(sys.argv[2])
lp.parent.mkdir(parents=True, exist_ok=True)
with paths.cross_process_lock(lp, timeout_sec=5.0):
    print("LOCKED", flush=True)
    sys.stdin.readline()
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_code, str(REPO_ROOT), pid_conc],
        env=child_env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        ready_line = holder.stdout.readline().strip()
        assert ready_line == "LOCKED"
        with pytest.raises(usage_index.LockBusyError, match="Usage index lock busy"):
            usage_index.append_rows(
                pid_conc,
                [{"key": "blocked:row", "source": "job", "tokens": 50}],
                lock_timeout=0.2,
            )
        with pytest.raises(usage_index.LockBusyError, match="Usage index lock busy"):
            usage_index.inspect_project_index(pid_conc, lock_timeout=0.2)
    finally:
        if holder.poll() is None:
            try:
                holder.stdin.write("release\n")
                holder.stdin.flush()
            except Exception:
                holder.kill()
            holder.wait(timeout=5)


def test_attribution_env_ingest_usage_across_skill_jobs_code_jobs_global_summary_and_anvil_aegis(
    w5_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Verify attribution_env + ingest_usage across skill_jobs, code_jobs, global summary, anvil, and aegis."""
    proj_dir = tmp_path / "proj_attribution"
    effort_dir = proj_dir / "effort_1"
    effort_dir.mkdir(parents=True, exist_ok=True)
    (effort_dir / "ECGBERHT.md").write_text("# Effort 1\n", encoding="utf-8")
    proj = rnd_registry.add_project("Attribution Project", str(proj_dir))
    pid = proj["id"]

    # 1. skill_jobs.start -> attribution_env inherited + usage JSON ingested into usage_index
    skill_root = tmp_path / "skills_root" / "demo_skill"
    skill_root.mkdir(parents=True, exist_ok=True)
    env_dump_file = tmp_path / "skill_env_dump.json"
    skill_script = skill_root / "run_demo.py"
    skill_script.write_text(
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "Path(sys.argv[1]).write_text(json.dumps({\n"
        "  'ANCHOR_PROJECT_ID': os.environ.get('ANCHOR_PROJECT_ID'),\n"
        "  'ANCHOR_EFFORT_DIR': os.environ.get('ANCHOR_EFFORT_DIR'),\n"
        "  'ANCHOR_JOB_ID': os.environ.get('ANCHOR_JOB_ID'),\n"
        "  'ANCHOR_USAGE_SOURCE': os.environ.get('ANCHOR_USAGE_SOURCE'),\n"
        "  'ANCHOR_DATA_DIR': os.environ.get('ANCHOR_DATA_DIR'),\n"
        "}), encoding='utf-8')\n"
        "print(json.dumps({\n"
        "  'cli': 'gemini',\n"
        "  'model_served': 'gemini-4-argon',\n"
        "  'total_tokens': 12000,\n"
        "  'cost_usd': 0.08,\n"
        "  'usage': {'input_tokens': 9000, 'cache_read_input_tokens': 2000, 'output_tokens': 1000}\n"
        "}), flush=True)\n",
        encoding="utf-8",
    )

    monkeypatch.setenv("ANCHOR_SKILL_ROOTS", str(tmp_path / "skills_root"))
    monkeypatch.setattr(skill_jobs, "OBSERVE_S", 0.05)

    def _simple_popen_contained(argv, cwd, env, out):
        clean_env = {k: v for k, v in env.items() if k != "ANCHOR_TOKEN"}
        proc = subprocess.Popen(
            argv, cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT, env=clean_env
        )
        return code_jobs._Run(proc, None)

    monkeypatch.setattr(code_jobs, "_popen_contained", _simple_popen_contained)

    started = skill_jobs.start(str(effort_dir), [sys.executable, str(skill_script), str(env_dump_file)], label="demo")
    assert started.get("ok") is True, started
    sjob_id = started["job"]

    deadline = time.time() + 10.0
    while time.time() < deadline:
        rec_s = skill_jobs.read_jobs(str(effort_dir)).get(sjob_id) or {}
        if rec_s.get("status") == "done":
            break
        time.sleep(0.05)
    assert (skill_jobs.read_jobs(str(effort_dir)).get(sjob_id) or {}).get("status") == "done"

    captured_env = json.loads(env_dump_file.read_text(encoding="utf-8"))
    assert captured_env["ANCHOR_PROJECT_ID"] == pid
    assert os.path.normcase(os.path.realpath(captured_env["ANCHOR_EFFORT_DIR"])) == os.path.normcase(
        os.path.realpath(str(effort_dir))
    )
    assert captured_env["ANCHOR_JOB_ID"] == sjob_id
    assert captured_env["ANCHOR_USAGE_SOURCE"] == "skill-job"
    assert os.path.normcase(os.path.realpath(captured_env["ANCHOR_DATA_DIR"])) == os.path.normcase(
        os.path.realpath(str(w5_env.data_dir))
    )

    rows_after_skill = {r["key"]: r for r in usage_index.load_rows(pid)}
    s_row = rows_after_skill.get(f"skill-job:{sjob_id}")
    assert s_row is not None
    assert s_row["tokens"] == 12_000
    assert s_row["input_tokens"] == 9_000
    assert s_row["cache_read_input_tokens"] == 2_000
    assert s_row["output_tokens"] == 1_000
    assert s_row["model"] == "gemini-4-argon"

    # 2. code_jobs: foreman_settings isolates ANCHOR_SETTINGS_DIR while _job_attribution_env keeps real ANCHOR_DATA_DIR
    (w5_env.settings_dir / "settings.json").write_text(
        json.dumps(
            {
                "coding_family": "claude",
                "review_family": "gemini",
                "default_cli": "claude",
                "settings_revision": 1,
            }
        ),
        encoding="utf-8",
    )
    f_settings_dir, f_err = code_jobs.foreman_settings({"id": "foreman-job-1"})
    assert f_err is None and f_settings_dir is not None
    assert Path(f_settings_dir) != w5_env.data_dir
    assert (Path(f_settings_dir) / "settings.json").is_file()

    att_cj_env = code_jobs._job_attribution_env(str(effort_dir), "cj-101", repo=str(proj_dir), source="code-job")
    assert att_cj_env["ANCHOR_DATA_DIR"] == str(w5_env.data_dir)
    assert att_cj_env["ANCHOR_PROJECT_ID"] == pid
    assert att_cj_env["ANCHOR_JOB_ID"] == "cj-101"

    code_jobs._ingest_review_usage(
        {"id": "cj-101", "steward_dir": str(effort_dir), "repo": str(proj_dir), "attempt": 1, "reviewer_family": "gemini"},
        {
            "family": "gemini",
            "model_served": "gemini-4-argon-high",
            "tokens": 8_000,
            "cost_usd": 0.05,
            "usage": {"input_tokens": 7_000, "output_tokens": 1_000},
        },
    )
    code_jobs._ingest_code_job_usage(
        str(effort_dir),
        {"id": "cj-101", "steward_dir": str(effort_dir), "repo": str(proj_dir), "coder_family": "claude"},
        {
            "model_served": "claude-opus-5-5",
            "tokens": 25_000,
            "cost_usd": 0.65,
            "usage": {"input_tokens": 20_000, "cache_read_input_tokens": 3_000, "output_tokens": 2_000},
        },
    )
    rows_after_cj = {r["key"]: r for r in usage_index.load_rows(pid)}
    assert "review:cj-101:main:1" in rows_after_cj
    assert rows_after_cj["review:cj-101:main:1"]["source"] == "seat"
    assert "code-job:cj-101" in rows_after_cj
    assert rows_after_cj["code-job:cj-101"]["source"] == "job"

    # 3. _compute_global_usage_summary maps Anchor-code-jobs/<id> via jobs-index.jsonl & prices v2 subagent splits
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    wt_orphan = w5_env.cj_dir / "cj-worktree-77"
    wt_orphan.mkdir(parents=True, exist_ok=True)
    (w5_env.cj_dir / "jobs-index.jsonl").write_text(
        json.dumps({"job": "cj-worktree-77", "worktree": str(wt_orphan), "steward_dir": str(effort_dir)}) + "\n",
        encoding="utf-8",
    )
    w5_env.state_file.write_text(
        json.dumps(
            {
                str(wt_orphan): {
                    "cli": "claude",
                    "model_policy": {"family": "claude", "model_served": "claude-opus-5-5"},
                    "usage": {
                        "tokens": 40_000,
                        "reported_spend": 1.20,
                        "spend": 1.20,
                        "usage_updated_at": now_iso,
                    },
                }
            }
        ),
        encoding="utf-8",
    )
    # Write a schema-v2 subagent row with ONLY top-level token breakdown fields (no nested 'usage' dict)
    raw_v2_subagent = {
        "key": "child:global:top-only",
        "source": "subagent",
        "native_id": "sub-top-1",
        "effort_dir": str(effort_dir),
        "cli": "chatgpt",
        "model": "gpt-6-astra",
        "tokens": 50_000,
        "input_tokens": 40_000,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "output_tokens": 10_000,
        "cost_usd": None,
        "usage_state": "unpriced",
        "recorded_at": now_iso,
    }
    idx_file = usage_index.index_path(pid)
    with open(idx_file, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(raw_v2_subagent) + "\n")

    _clear_spend_caches()
    gsum = steward_routes._compute_global_usage_summary()
    proj_map = {p["project_id"]: p for p in gsum["projects"]}
    assert pid in proj_map
    # Total tokens on pid must include: skill-job (12k) + review (8k) + code-job (25k) + wt_orphan (40k) + subagent (50k) = 135k
    assert proj_map[pid]["tokens_all"] >= 135_000
    # gpt-6-astra top-level split: 40k * $10/M ($0.40) + 10k * $50/M ($0.50) = $0.90 + reported ($0.08+$0.05+$0.65+$1.20 = $1.98) = $2.88
    assert proj_map[pid]["usd_all"] >= 2.85

    # 4. anvil and aegis POST routes populate attribution_env and ingest seat usage rows
    seen_route_envs = {}
    anvil_session._LOADED_MTIME_NS = Path(anvil_session.__file__).stat().st_mtime_ns
    aegis_session._LOADED_MTIME_NS = Path(aegis_session.__file__).stat().st_mtime_ns

    def _stub_anvil_walkthrough(cdir_arg, block_id):
        seen_route_envs["anvil"] = {
            "project_id": os.environ.get("ANCHOR_PROJECT_ID"),
            "effort_dir": os.environ.get("ANCHOR_EFFORT_DIR"),
            "source": os.environ.get("ANCHOR_USAGE_SOURCE"),
        }
        return {
            "ok": True,
            "block_id": block_id,
            "model": "gemini-4-argon",
            "usage": {"input_tokens": 4_000, "output_tokens": 500},
        }

    def _stub_aegis_remediate(cdir_arg, *, apply=False, rule_filter=""):
        seen_route_envs["aegis"] = {
            "project_id": os.environ.get("ANCHOR_PROJECT_ID"),
            "effort_dir": os.environ.get("ANCHOR_EFFORT_DIR"),
            "source": os.environ.get("ANCHOR_USAGE_SOURCE"),
        }
        return {
            "ok": True,
            "applied": apply,
            "model": "claude-fable-5-1",
            "usage": {"input_tokens": 6_000, "output_tokens": 1_000},
        }

    monkeypatch.setattr(anvil_session, "walkthrough_in_session", _stub_anvil_walkthrough)
    monkeypatch.setattr(aegis_session, "run_cockpit_aegis_remediate", _stub_aegis_remediate)

    anvil_res, anvil_code = steward_routes.api_post(
        str(proj_dir), "anvil", {"dir": "effort_1", "action": "walkthrough", "block_id": "blk-1"}
    )
    assert anvil_code == 200 and anvil_res.get("ok") is True
    assert seen_route_envs["anvil"]["project_id"] == pid
    assert seen_route_envs["anvil"]["source"] == "anvil:walkthrough"

    aegis_res, aegis_code = steward_routes.api_post(
        str(proj_dir), "aegis", {"dir": "effort_1", "action": "remediate", "apply": False}
    )
    assert aegis_code == 200 and aegis_res.get("ok") is True
    assert seen_route_envs["aegis"]["project_id"] == pid
    assert seen_route_envs["aegis"]["source"] == "aegis:remediate"

    final_rows = usage_index.load_rows(pid)
    anvil_rows = [r for r in final_rows if str(r.get("key") or "").startswith("seat:anvil:walkthrough:")]
    aegis_rows = [r for r in final_rows if str(r.get("key") or "").startswith("seat:aegis:remediate:")]
    assert len(anvil_rows) == 1 and anvil_rows[0]["tokens"] == 4_500
    assert len(aegis_rows) == 1 and aegis_rows[0]["tokens"] == 7_000


def test_session_registry_two_process_concurrency_healthcheck_isolation_and_purge(
    w5_env, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Verify 2-process session_registry locking, healthcheck ANCHOR_DATA_DIR isolation, and synthetic purge."""
    reg_worker = """
import sys
sys.path.insert(0, sys.argv[1])
import session_registry

tag = sys.argv[2]
for i in range(15):
    sid = f"sess-{tag}-{i:02d}"
    session_registry.register_session(
        project_id=f"proj-{tag}",
        lane="build",
        backend="claude",
        status=session_registry.STATUS_RUNNING,
        label=f"{tag}-{i}",
        session_id=sid,
    )
    session_registry.update_session(sid, status=session_registry.STATUS_DONE)
"""
    child_env = dict(os.environ)
    child_env["ANCHOR_DATA_DIR"] = str(w5_env.data_dir)
    p1 = subprocess.Popen(
        [sys.executable, "-c", reg_worker, str(REPO_ROOT), "wA"],
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    p2 = subprocess.Popen(
        [sys.executable, "-c", reg_worker, str(REPO_ROOT), "wB"],
        env=child_env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    o1, e1 = p1.communicate(timeout=30)
    o2, e2 = p2.communicate(timeout=30)
    assert p1.returncode == 0, f"Registry worker A failed: {o1} {e1}"
    assert p2.returncode == 0, f"Registry worker B failed: {o2} {e2}"

    _clear_spend_caches()
    loaded = session_registry.load_sessions()
    expected_sids = {f"sess-wA-{i:02d}" for i in range(15)} | {f"sess-wB-{i:02d}" for i in range(15)}
    assert expected_sids.issubset(set(loaded.keys()))
    assert all(loaded[sid]["status"] == session_registry.STATUS_DONE for sid in expected_sids)

    # Seed live markdown + live project in w5_env.data_dir, then run healthcheck R&D surfaces
    live_inbox = w5_env.data_dir / "INBOX.md"
    live_inbox.write_text("# Inbox\n\n- Keep this real note untouched\n", encoding="utf-8")
    live_proj_dir = tmp_path / "live_user_proj"
    live_proj_dir.mkdir(parents=True, exist_ok=True)
    live_proj = rnd_registry.add_project("Real User Project", str(live_proj_dir))
    live_pid = live_proj["id"]

    sessions_before = (w5_env.data_dir / ".anchor" / "sessions.json").read_text(encoding="utf-8")
    rnd_before = (w5_env.data_dir / "rnd_registry.json").read_text(encoding="utf-8")
    inbox_before = live_inbox.read_text(encoding="utf-8")

    runner_cmd = anchor_healthcheck._fake_runner_cmd()
    assert runner_cmd is not None
    monkeypatch.setenv("ANCHOR_HEALTHCHECK", "1")
    monkeypatch.setenv("ANCHOR_RUNNER_CMD", runner_cmd)

    srv_seed_dir = anchor_healthcheck._seed_server_data_dir()
    hc_rnd_folder = tmp_path / "hc_rnd_probe_folder"
    hc_rnd_folder.mkdir(parents=True, exist_ok=True)
    rnd_env = {
        "runner_cmd": runner_cmd,
        "folder": hc_rnd_folder,
        "created_ids": [],
        "v3_temp_dirs": [],
    }
    rep = anchor_healthcheck.Report()
    try:
        assert srv_seed_dir != w5_env.data_dir
        assert (srv_seed_dir / "INBOX.md").is_file()

        # Exercise check_rnd_v2_surface ANCHOR_DATA_DIR isolation against srv_seed_dir
        rep_v2 = anchor_healthcheck.Report()
        with pytest.MonkeyPatch.context() as mp_v2:
            mp_v2.setattr(anchor_healthcheck, "_post", lambda *a, **kw: {"ok": True, "id": "idea-1"})
            mp_v2.setattr(anchor_healthcheck.urllib.request, "urlopen", lambda *a, **kw: (_ for _ in ()).throw(OSError("offline")))
            anchor_healthcheck.check_rnd_v2_surface(
                rep_v2, SimpleNamespace(_hc_data_dir=srv_seed_dir), dict(rnd_env)
            )

        # Exercise check_rnd_v3_surface, check_rnd_v4_surface, and check_rnd_v5_surface end-to-end
        anchor_healthcheck.check_rnd_v3_surface(rep, None, rnd_env)
        anchor_healthcheck.check_rnd_v4_surface(rep, None, rnd_env)
        anchor_healthcheck.check_rnd_v5_surface(rep, None, rnd_env)
        assert not rep.has_issues, f"Healthcheck R&D surfaces reported issues: {rep.issues}"
    finally:
        for td in rnd_env.get("v3_temp_dirs", []):
            anchor_healthcheck._rmtree_force(Path(td))
        anchor_healthcheck._rmtree_force(srv_seed_dir)

    # Live ANCHOR_DATA_DIR env and files must be 100% untouched
    assert os.environ.get("ANCHOR_DATA_DIR") == str(w5_env.data_dir)
    assert (w5_env.data_dir / ".anchor" / "sessions.json").read_text(encoding="utf-8") == sessions_before
    assert (w5_env.data_dir / "rnd_registry.json").read_text(encoding="utf-8") == rnd_before
    assert live_inbox.read_text(encoding="utf-8") == inbox_before

    # Seed synthetic healthcheck / fake pollution alongside real ledger & index records, then purge
    ledger_dir = w5_env.data_dir / ".anchor" / "usage_ledger"
    ledger_dir.mkdir(parents=True, exist_ok=True)
    (ledger_dir / "fake-9991.json").write_text(
        json.dumps({"engine_session_uuid": "fake-9991", "entries": {"e1": {"tokens": 500}}}),
        encoding="utf-8",
    )
    real_uuid = "22222222-3333-4444-5555-666666666666"
    (ledger_dir / f"{real_uuid}.json").write_text(
        json.dumps(
            {
                "engine_session_uuid": real_uuid,
                "entries": {
                    "real-turn-1": {"key": "real-turn-1", "tokens": 2500, "project_id": live_pid},
                    "hc-leak-1": {"key": "hc-leak-1", "tokens": 100, "effort_dir": "anchor-hc-v4-proj-xyz"},
                },
            }
        ),
        encoding="utf-8",
    )
    usage_index.append_rows(
        live_pid,
        [
            {"key": "job:real-keep-1", "source": "job", "tokens": 4_000, "model": "claude-opus-5-5"},
            {"key": "job:fake-drop-1", "source": "job", "engine_session_uuid": "fake-1234", "tokens": 900},
        ],
    )
    usage_index.append_rows(
        "__healthcheck__-probe",
        [{"key": "job:hc-only", "source": "job", "tokens": 300}],
    )

    purge_res = usage_capture.purge_synthetic_healthcheck_records(w5_env.data_dir)
    assert purge_res["ok"] is True
    assert purge_res["removed_ledgers"] >= 1
    assert purge_res["removed_ledger_entries"] >= 2
    assert purge_res["removed_index_rows"] >= 2

    assert not (ledger_dir / "fake-9991.json").exists()
    kept_ledger = json.loads((ledger_dir / f"{real_uuid}.json").read_text(encoding="utf-8"))
    assert list(kept_ledger["entries"].keys()) == ["real-turn-1"]

    assert not usage_index.index_path("__healthcheck__-probe").exists()
    kept_idx_rows = usage_index.load_rows(live_pid)
    assert [r["key"] for r in kept_idx_rows] == ["job:real-keep-1"]


def test_wave5_five_state_failure_contract_unknown_not_equal_empty(w5_env, tmp_path: Path):
    """Exercise GET /api/steward/spend across all 5 Wave 5 states, keeping unknown distinct from empty."""
    proj_dir = tmp_path / "proj_five_states"
    effort_dir = proj_dir / "effort_5s"
    effort_dir.mkdir(parents=True, exist_ok=True)
    (effort_dir / "ECGBERHT.md").write_text("# Effort 5 States\n", encoding="utf-8")
    proj = rnd_registry.add_project("Five States Project", str(proj_dir))
    pid = proj["id"]

    # 1. empty-but-valid -> HTTP 200, "No spend recorded yet"
    _clear_spend_caches()
    body_empty, status_empty = steward_routes.api_get(str(proj_dir), "spend", {"dir": "effort_5s"})
    assert status_empty == 200
    assert body_empty["ok"] is True
    assert body_empty["failure_state"] == "empty-but-valid"
    assert body_empty["pill_label"] == "No spend recorded yet"
    assert body_empty["message"] == "No spend recorded yet"
    assert "$0.00" not in body_empty["pill_label"]

    # 2. dependency-missing (tokens > 0 on unlisted model -> combined_spend == 0) -> HTTP 200, "Unpriced · ... tok ▾"
    usage_index.append_rows(
        pid,
        [
            {
                "key": "job:unlisted-model-turn",
                "source": "job",
                "effort_dir": str(effort_dir),
                "cli": "custom-engine",
                "model": "unlisted-mystery-v9",
                "tokens": 25_000,
                "cost_usd": None,
                "usage_state": "unpriced",
            }
        ],
    )
    _clear_spend_caches()
    body_missing, status_missing = steward_routes.api_get(str(proj_dir), "spend", {"dir": "effort_5s"})
    assert status_missing == 200
    assert body_missing["ok"] is True
    assert body_missing["failure_state"] == "dependency-missing"
    assert body_missing["pill_label"].startswith("Unpriced \u00b7 ")
    assert "tok" in body_missing["pill_label"] and body_missing["pill_label"].endswith("\u25be")
    assert "$0.00" not in body_missing["pill_label"]

    # 3. dependency-returns-garbage (valid priced row + malformed JSONL line -> quarantined_count == 1) -> HTTP 200
    usage_index.append_rows(
        pid,
        [
            {
                "key": "job:valid-priced",
                "source": "job",
                "effort_dir": str(effort_dir),
                "cli": "claude",
                "model": "claude-opus-5-5",
                "tokens": 10_000,
                "cost_usd": 0.75,
                "usage_state": "measured",
            }
        ],
    )
    idx_path = usage_index.index_path(pid)
    with open(idx_path, "a", encoding="utf-8") as fh:
        fh.write("{corrupt-json-line-wave5\n")

    _clear_spend_caches()
    body_garb, status_garb = steward_routes.api_get(str(proj_dir), "spend", {"dir": "effort_5s"})
    assert status_garb == 200
    assert body_garb["ok"] is True
    assert body_garb["failure_state"] == "dependency-returns-garbage"
    assert body_garb["quarantined_count"] == 1
    assert body_garb["warning"] == "Corrupt usage record quarantined (1 skipped)"
    assert body_garb["message"] == "Corrupt usage record quarantined (1 skipped)"
    assert body_garb["total_with_children"]["reported_spend"] == pytest.approx(0.75, abs=1e-4)

    # 4. dependency-slow-or-killed (cross-process lock held beyond lock_timeout) -> HTTP 504, state="unknown"
    holder_script = """
import sys
sys.path.insert(0, sys.argv[1])
import paths, usage_index
lp = usage_index.lock_path(sys.argv[2])
with paths.cross_process_lock(lp, timeout_sec=5.0):
    print("LOCKED", flush=True)
    sys.stdin.readline()
"""
    child_env = dict(os.environ)
    child_env["ANCHOR_DATA_DIR"] = str(w5_env.data_dir)
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_script, str(REPO_ROOT), pid],
        env=child_env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "LOCKED"
        _clear_spend_caches()
        body_slow, status_slow = steward_routes.api_get(
            str(proj_dir), "spend", {"dir": "effort_5s", "lock_timeout": "0.2"}
        )
        assert status_slow == 504
        assert body_slow == {
            "ok": False,
            "failure_state": "dependency-slow-or-killed",
            "state": "unknown",
            "message": "Usage index lock busy \u2014 retry",
        }
    finally:
        if holder.poll() is None:
            try:
                holder.stdin.write("release\n")
                holder.stdin.flush()
            except Exception:
                holder.kill()
            holder.wait(timeout=5)

    # 5. backing-store-unreadable (binary NUL corruption in usage_index & corrupt usage_baseline.json) -> HTTP 500
    idx_path.write_bytes(b'{"key":"k1"}\x00corrupt\n')
    _clear_spend_caches()
    body_unread, status_unread = steward_routes.api_get(str(proj_dir), "spend", {"dir": "effort_5s"})
    assert status_unread == 500
    assert body_unread == {
        "ok": False,
        "failure_state": "backing-store-unreadable",
        "state": "unknown",
        "message": "Spend unreadable (unknown) \u2014 inspect usage_index",
    }

    # Restore clean index and verify corrupt usage_baseline.json also triggers backing-store-unreadable (500)
    idx_path.unlink()
    usage_index.meta_path(pid).unlink(missing_ok=True)
    usage_index.quarantine_path(pid).unlink(missing_ok=True)
    bad_baseline = w5_env.data_dir / ".anchor" / "usage_baseline.json"
    bad_baseline.write_text("{not-valid-json", encoding="utf-8")
    try:
        _clear_spend_caches()
        body_bad_base, status_bad_base = steward_routes.api_get(str(proj_dir), "spend", {"dir": "effort_5s"})
        assert status_bad_base == 500
        assert body_bad_base["ok"] is False
        assert body_bad_base["failure_state"] == "backing-store-unreadable"
        assert body_bad_base["state"] == "unknown"
        assert body_bad_base["message"] == "Spend unreadable (unknown) \u2014 inspect usage_index"
    finally:
        bad_baseline.unlink(missing_ok=True)
