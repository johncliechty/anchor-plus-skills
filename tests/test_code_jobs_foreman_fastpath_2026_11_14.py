"""Wave 3 (2026-11-14) — Anchor Foreman code-job fast-path & gitDiff config.

Verifies:
1. `_start_foreman` writes `"gitDiff": True, "gitCommit": False` into `foreman.config.json` (and removes it before landing).
2. When `.foreman/run-record.json` carries a verified cross-family `attested_review` (`go: True, cross_model: True`)
   whose `changed_files` SHA-256 map matches every candidate file byte-for-byte, `land()` records that attested review
   receipt directly without invoking `ANCHOR_REVIEW_CMD` (`steward_review.mjs`).
3. Same-family (`family == "claude"`) or `cross_model: False` `attested_review` refuses the fast-path and falls back to
   `ANCHOR_REVIEW_CMD`.
4. Any post-review file mutation (SHA-256 mismatch) or extra unattested output file refuses the fast-path and falls back
   to `ANCHOR_REVIEW_CMD`.
5. `foreman_plan_ok` accepts both integer waves (`## Wave 1`) and sub-wave headings (`### Wave 1.1`).
6. `distro.py` stdlib-only + no-personal-data scan passes cleanly on `steward_cockpit/code_jobs.py` and this test file.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import distro  # noqa: E402
from steward_cockpit import code_jobs  # noqa: E402

PASS_CHECK = [sys.executable, "-c", "pass"]


def _init_repo(root: Path, files: dict[str, str] | None = None) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for args in (
        ["init", "-q"],
        ["config", "user.email", "anchor@localhost"],
        ["config", "user.name", "Anchor Test"],
    ):
        subprocess.run(["git", "-C", str(root), *args], check=True)
    for rel, text in (files or {"a.txt": "one\n"}).items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-q", "-m", "initial"], check=True)
    return root


def _write_hermetic_foreman_script(script_path: Path) -> Path:
    """Write a hermetic Node stand-in for `run-live.mjs` controlled via env vars."""
    script_path.write_text(
        """import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const project = path.resolve(process.argv[2]);
const mode = process.env.FASTPATH_FOREMAN_MODE || 'attested-cross';
const cfg = JSON.parse(fs.readFileSync(path.join(project, 'foreman.config.json'), 'utf8'));

if (process.env.FASTPATH_CFG_LOG) {
  fs.writeFileSync(process.env.FASTPATH_CFG_LOG, JSON.stringify(cfg), 'utf8');
}

const nextText = 'two\\n';
const outFile = path.join(project, 'a.txt');
fs.writeFileSync(outFile, nextText, 'utf8');
const realSha = crypto.createHash('sha256').update(fs.readFileSync(outFile)).digest('hex');

const changedFiles = { 'a.txt': mode === 'tampered-sha' ? realSha.replace(/^[0-9a-f]/, (c) => (c === '0' ? '1' : '0')) : realSha };
if (mode === 'extra-unattested') {
  fs.writeFileSync(path.join(project, 'b.py'), 'VALUE = 2\\n', 'utf8');
}

let attestedReview = {
  go: true,
  cross_model: true,
  family: 'gemini',
  families: ['gemini'],
  coding_families: ['claude'],
  model_served: 'gemini-3.1-pro',
  family_attested: true,
  model_attested: true,
  review_calls: 1,
  blocking_findings: 0,
};

if (mode === 'same-family') {
  attestedReview = {
    ...attestedReview,
    cross_model: true,
    family: 'claude',
    families: ['claude'],
  };
} else if (mode === 'not-cross-model') {
  attestedReview = {
    ...attestedReview,
    cross_model: false,
  };
} else if (mode === 'missing-family-attested') {
  delete attestedReview.family_attested;
}

const rec = {
  schema: 'foreman-run-record/v1',
  status: 'DONE',
  waves: [{ wave: 1, status: 'GREEN' }],
  totals: { in: 1200, out: 350, cost: 0.0089, ms: 4200, denials: 0 },
  changed_files: changedFiles,
  attested_review: attestedReview,
};

fs.mkdirSync(path.join(project, '.foreman'), { recursive: true });
fs.writeFileSync(path.join(project, '.foreman', 'run-record.json'), JSON.stringify(rec, null, 2), 'utf8');
""",
        encoding="utf-8",
    )
    return script_path


@pytest.fixture
def fastpath_env(tmp_path, monkeypatch):
    import anchor_settings

    foreman_tool_repo = _init_repo(tmp_path / "foreman_tool_repo")
    fake_foreman = _write_hermetic_foreman_script(foreman_tool_repo / "hermetic_foreman.mjs")
    monkeypatch.setattr(code_jobs, "_report", lambda cdir, job: None)
    monkeypatch.setattr(code_jobs, "FOREMAN_RUN_LIVE", fake_foreman)
    monkeypatch.setattr(
        anchor_settings,
        "get_launch_settings",
        lambda: dict(
            anchor_settings.DEFAULTS,
            coding_family="claude",
            review_family="gemini",
            default_cli="claude",
        ),
    )
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(tmp_path / "jobs"))
    monkeypatch.setenv("ANCHOR_REVIEW_CMD", json.dumps([sys.executable, str(ROOT / "tests" / "fake_review.py")]))
    monkeypatch.setenv("FAKE_REVIEW_FAMILY", "gemini")
    monkeypatch.setenv("FAKE_REVIEW_LOG", str(tmp_path / "review.log"))
    monkeypatch.setenv("FASTPATH_CFG_LOG", str(tmp_path / "foreman_cfg.json"))
    monkeypatch.delenv("ANCHOR_FOREMAN_CODE_JOBS", raising=False)
    monkeypatch.delenv("ANCHOR_UNCONFINED_CODERS", raising=False)

    repo = _init_repo(tmp_path / "repo")
    cdir = tmp_path / "steward"
    cdir.mkdir()
    return repo, cdir, tmp_path


def _wait_done(cdir: Path, job_id: str) -> dict:
    for _ in range(400):
        j = code_jobs.read_jobs(str(cdir)).get(job_id) or {}
        if j.get("status") in ("done", "failed", "stopped"):
            return j
        time.sleep(0.05)
    raise AssertionError("Foreman code job did not finish in time")


def test_foreman_config_enables_git_diff_and_attested_cross_family_fastpaths_review(fastpath_env, monkeypatch):
    repo, cdir, tmp = fastpath_env
    monkeypatch.setenv("FASTPATH_FOREMAN_MODE", "attested-cross")

    res = code_jobs.start(str(cdir), str(repo), "Update a.txt to two.", PASS_CHECK, worker="foreman")
    assert res["ok"] is True, res
    job = _wait_done(cdir, res["job"])

    # 1. foreman.config.json had gitDiff=True and gitCommit=False, and never landed in repo
    cfg = json.loads((tmp / "foreman_cfg.json").read_text(encoding="utf-8"))
    assert cfg["gitDiff"] is True
    assert cfg["gitCommit"] is False
    assert not (repo / "foreman.config.json").exists()

    # 2. Job landed cleanly with ZERO external steward_review invocations
    assert job["landed"] is True, job["land_note"]
    assert (repo / "a.txt").read_text(encoding="utf-8") == "two\n"
    assert not (tmp / "review.log").exists(), "ANCHOR_REVIEW_CMD must NOT be called when attested cross-family review matches"
    assert job["review"]["ok"] is True
    assert job["review"]["verdict"] == "PASS"
    assert job["review"]["family"] == "gemini"
    assert job["review"]["cross_model"] is True
    assert job["review"]["source"] == "foreman_attested_review"


@pytest.mark.parametrize("bad_mode", ["same-family", "not-cross-model", "missing-family-attested", "tampered-sha", "extra-unattested"])
def test_unverified_or_modified_candidates_fall_back_to_steward_review(fastpath_env, monkeypatch, bad_mode):
    repo, cdir, tmp = fastpath_env
    monkeypatch.setenv("FASTPATH_FOREMAN_MODE", bad_mode)

    res = code_jobs.start(str(cdir), str(repo), "Update a.txt.", PASS_CHECK, worker="foreman")
    assert res["ok"] is True, res
    job = _wait_done(cdir, res["job"])

    assert job["landed"] is True, job["land_note"]
    assert (tmp / "review.log").exists(), f"mode={bad_mode} must fall back to ANCHOR_REVIEW_CMD"
    review_calls = (tmp / "review.log").read_text(encoding="utf-8").strip().splitlines()
    assert len(review_calls) == 1
    assert job["review"].get("source") != "foreman_attested_review"


def test_post_foreman_check_mutation_refuses_fastpath_and_invokes_steward_review(fastpath_env, monkeypatch):
    repo, cdir, tmp = fastpath_env
    monkeypatch.setenv("FASTPATH_FOREMAN_MODE", "attested-cross")
    # Declare rendered.txt as a job output produced by --check AFTER Foreman exited
    mutating_check = [
        sys.executable,
        "-c",
        "from pathlib import Path; Path('rendered.txt').write_text('built\\n', encoding='utf-8')",
    ]
    res = code_jobs.start(
        str(cdir),
        str(repo),
        "Update a.txt and build rendered.txt.",
        mutating_check,
        worker="foreman",
        outputs=["rendered.txt"],
    )
    assert res["ok"] is True, res
    job = _wait_done(cdir, res["job"])

    assert job["landed"] is True, job["land_note"]
    assert sorted(job["files"]) == ["a.txt", "rendered.txt"]
    assert (tmp / "review.log").exists(), "post-Foreman output produced by check must trigger full steward_review"
    assert job["review"].get("source") != "foreman_attested_review"


def test_foreman_result_extracts_totals_and_subwave_plan_ok(tmp_path):
    wt = tmp_path / "wt"
    (wt / ".foreman").mkdir(parents=True)
    digest = hashlib.sha256(b"hello\n").hexdigest()
    (wt / ".foreman" / "run-record.json").write_text(
        json.dumps(
            {
                "status": "DONE",
                "waves": [{"wave": 1, "status": "GREEN"}],
                "totals": {"in": 500, "out": 250, "cost": 0.0052, "ms": 3100},
                "changed_files": {"src/x.py": digest},
                "attested_review": {"go": True, "cross_model": True, "family": "chatgpt"},
            }
        ),
        encoding="utf-8",
    )
    parsed = code_jobs.foreman_result({"worktree": str(wt)})
    assert parsed["tokens"] == 750
    assert parsed["usage"] == {"input_tokens": 500, "output_tokens": 250}
    assert parsed["cost_usd"] == pytest.approx(0.0052)
    assert parsed["duration_ms"] == 3100
    assert parsed["changed_files"] == {"src/x.py": digest}
    assert parsed["attested_review"]["family"] == "chatgpt"

    subwave_plan = "# Plan\n\n### Wave 1.1 — Part A\nWrites: src/a.py\n\n### Wave 1.2 — Part B\nWrites: src/b.py\n"
    assert code_jobs.foreman_plan_ok(subwave_plan) == ""


def test_missing_working_tree_file_and_failed_check_never_fastpath_or_complete_roadmap(fastpath_env, monkeypatch):
    repo, cdir, tmp = fastpath_env
    monkeypatch.setenv("FASTPATH_FOREMAN_MODE", "attested-cross")

    # 1. Missing working-tree file after commit must refuse attested_foreman_review_record
    wt = _init_repo(tmp / "wt_missing")
    (wt / "a.txt").write_text("two\n", encoding="utf-8")
    digest = hashlib.sha256((wt / "a.txt").read_bytes()).hexdigest()
    subprocess.run(["git", "-C", str(wt), "add", "a.txt"], check=True)
    subprocess.run(["git", "-C", str(wt), "commit", "-q", "-m", "cand"], check=True)
    head = subprocess.run(["git", "-C", str(wt), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    (wt / "a.txt").unlink()
    rec = code_jobs.attested_foreman_review_record(
        {
            "worker": "foreman",
            "authors": ["claude"],
            "coder_family": "claude",
            "changed_files": {"a.txt": digest},
            "attested_review": {
                "go": True,
                "cross_model": True,
                "family": "gemini",
                "families": ["gemini"],
                "coding_families": ["claude"],
                "family_attested": True,
                "blocking_findings": 0,
            },
        },
        str(wt),
        head,
        ["a.txt"],
    )
    assert rec is None, "deleted working-tree file must not satisfy attested_foreman_review_record"

    # 2. Failed --check must NOT call reconcile_wave_completion even when Foreman reported GREEN waves
    reconciled_waves = []
    monkeypatch.setattr(
        code_jobs,
        "reconcile_wave_completion",
        lambda cdir_arg, job_arg, **kw: reconciled_waves.append(kw.get("wave_n")),
    )
    fail_check = [sys.executable, "-c", "import sys; sys.exit(1)"]
    res = code_jobs.start(str(cdir), str(repo), "Update a.txt.", fail_check, worker="foreman")
    assert res["ok"] is True
    failed_job = _wait_done(cdir, res["job"])
    assert failed_job["landed"] is False
    assert reconciled_waves == [], "unlanded Foreman job must never mark roadmap waves completed"


def test_code_jobs_and_fastpath_test_pass_distro_stdlib_and_pii_scan():
    pairs = [
        ("steward_cockpit/code_jobs.py", ROOT / "steward_cockpit" / "code_jobs.py"),
        (
            "tests/test_code_jobs_foreman_fastpath_2026_11_14.py",
            ROOT / "tests" / "test_code_jobs_foreman_fastpath_2026_11_14.py",
        ),
    ]
    assert distro.scan_paths(pairs, root=ROOT) == []
    assert distro.scan_third_party_imports(pairs, root=ROOT) == []
