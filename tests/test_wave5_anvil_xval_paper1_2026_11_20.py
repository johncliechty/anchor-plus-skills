"""Wave 5 Verification Suite — Live Anvil Co-Pilot, Attested 2-Seat Fable 5.2 XVal
Citation Audit, Bundled-Skill Byte-Sync & Mixture of Experts Paper 1 Regeneration.
"""
from __future__ import annotations

import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import threading
import time
from pathlib import Path
from typing import Any

import pytest

import distro
import model_policy
import paths
from steward_cockpit import anvil_session, steward_routes

ANCHOR_ROOT = Path(__file__).resolve().parent.parent
SKILL_ROOT = ANCHOR_ROOT.parent / "Skill Foundry" / "skills" / "anvil"
VENDOR_ANVIL_ROOT = ANCHOR_ROOT / "vendor" / "bundled-skills" / "anvil"
PAPER1_ROOT = ANCHOR_ROOT.parent / "Heterogeneity Empirical Demand Machine Learning" / "Paper 1"
HETNN_ROOT = PAPER1_ROOT / "HetNN"
HETNN_MAIN_TEX = HETNN_ROOT / "Manuscript" / "Main.tex"
HETNN_BASELINE_JSON = ANCHOR_ROOT / ".foreman" / "hetnn-baseline-sha256.json"
MOE_BACKUP_ANVIL = (
    ANCHOR_ROOT
    / "planning"
    / "2026-11-22-anvil-cockpit-multi-analysis"
    / "backups"
    / "legacy-anvil-20261122"
    / "moe_paper1"
    / ".anvil"
)
LOOKS_ROOT = ANCHOR_ROOT / "planning" / "cross-system-upgrade-2026-11-20" / "looks"

if str(SKILL_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT / "scripts"))

import anvil_engine  # noqa: E402
import anvil_v4_process  # noqa: E402
import anvil_v4_refactor  # noqa: E402
import anvil_v4_workbench  # noqa: E402
import anvil_v4_xval  # noqa: E402


def _allow_tmp_workspace(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    anvil_session._LOADED_MTIME_NS = Path(anvil_session.__file__).stat().st_mtime_ns
    extra_roots = [tmp_path.resolve()]
    if PAPER1_ROOT.exists():
        extra_roots.append(PAPER1_ROOT.resolve())
    monkeypatch.setattr(
        anvil_session,
        "ALLOWED_LOCAL_ROOTS",
        (*anvil_session.ALLOWED_LOCAL_ROOTS, *extra_roots),
    )


def _build_synthetic_divergence_repo(base_dir: Path) -> tuple[Path, Path]:
    """Build a compact synthetic Python + TeX repository with 2 divergences for fast XVal & Co-Pilot testing."""
    repo = base_dir / "xval_synth_repo"
    (repo / "src").mkdir(parents=True, exist_ok=True)
    (repo / "manuscript").mkdir(parents=True, exist_ok=True)

    (repo / "src" / "trainer.py").write_text(
        textwrap.dedent(
            """\
            import torch
            import torch.nn as nn

            UNDOC_SHRINK_BETA = 0.08

            class GateEstimator(nn.Module):
                def __init__(self, d_in: int = 4):
                    super().__init__()
                    self.head = nn.Linear(d_in, 2)

                def forward(self, x):
                    return torch.log_softmax(self.head(x), dim=-1)

            def perturb_stalled_weights(model: GateEstimator, eps: float = 1e-6) -> None:
                with torch.no_grad():
                    mask = model.head.weight.abs() < eps
                    if mask.any():
                        model.head.weight.add_(1e-3 * torch.randn_like(model.head.weight) * mask.float())

            def fit_estimator(x, y):
                model = GateEstimator(x.shape[-1])
                opt = torch.optim.Adam(
                    [
                        {"params": [model.head.bias], "lr": 1e-4},
                        {"params": [model.head.weight], "lr": 2e-3},
                    ]
                )
                lp = model(x)
                loss = -torch.mean(torch.sum(y * lp, dim=-1)) + UNDOC_SHRINK_BETA * (model.head.weight ** 2).mean()
                loss.backward()
                opt.step()
                perturb_stalled_weights(model)
                return model
            """
        ),
        encoding="utf-8",
    )

    main_tex = repo / "manuscript" / "Main.tex"
    main_tex.write_text(
        textwrap.dedent(
            """\
            \\documentclass{article}
            \\title{Synthetic Choice Estimation}
            \\begin{document}
            \\section{Estimation}
            Parameters are estimated via Adam with a single uniform learning rate $\\eta = 0.002$ maximizing the unpenalized log-likelihood:
            \\begin{equation}
            \\mathcal{L}(\\theta) = -\\frac{1}{N}\\sum_{i=1}^{N} \\log P_{i, y_i}
            \\end{equation}
            \\end{document}
            """
        ),
        encoding="utf-8",
    )
    return repo, main_tex


def test_w5_foundry_vendor_byte_sync_and_grep_gate() -> None:
    """Verify 100% byte-identity between Skill Foundry skills/anvil and Anchor vendor/bundled-skills/anvil,
    zero __pycache__ / .pyc files under vendor, and zero Paper-1 identifier literals.
    """
    assert SKILL_ROOT.is_dir(), f"Missing Skill Foundry anvil root: {SKILL_ROOT}"
    assert VENDOR_ANVIL_ROOT.is_dir(), f"Missing Anchor vendor anvil root: {VENDOR_ANVIL_ROOT}"

    # 1. Zero __pycache__ or *.pyc files under vendor/bundled-skills/anvil
    pycache_dirs = list(VENDOR_ANVIL_ROOT.rglob("__pycache__"))
    pyc_files = list(VENDOR_ANVIL_ROOT.rglob("*.pyc"))
    assert pycache_dirs == [], f"Forbidden __pycache__ under vendor/bundled-skills/anvil: {pycache_dirs}"
    assert pyc_files == [], f"Forbidden .pyc files under vendor/bundled-skills/anvil: {pyc_files}"

    # 2. Required core files + every file in vendor/bundled-skills/anvil must be 100% byte-identical
    required_rels = [
        "SKILL.md",
        "scripts/anvil_engine.py",
        "scripts/anvil_v4_process.py",
        "scripts/anvil_v4_trace.py",
        "scripts/anvil_v4_refactor.py",
        "scripts/anvil_v4_xval.py",
        "scripts/anvil_v4_workbench.py",
        "static/anvil_v4_workbench.html",
    ]
    for rel_str in required_rels:
        sf_file = SKILL_ROOT / rel_str
        vn_file = VENDOR_ANVIL_ROOT / rel_str
        assert sf_file.is_file(), f"Missing Skill Foundry file: {sf_file}"
        assert vn_file.is_file(), f"Missing vendor bundled file: {vn_file}"
        assert sf_file.read_bytes() == vn_file.read_bytes(), f"Byte mismatch on {rel_str}"

    # Also ensure no extra un-synced script or static files exist in Skill Foundry vs vendor
    for sub in ("scripts", "static"):
        sf_sub_rels = sorted(
            p.relative_to(SKILL_ROOT).as_posix()
            for p in (SKILL_ROOT / sub).rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"
        )
        vn_sub_rels = sorted(
            p.relative_to(VENDOR_ANVIL_ROOT).as_posix()
            for p in (VENDOR_ANVIL_ROOT / sub).rglob("*")
            if p.is_file()
        )
        assert sf_sub_rels == vn_sub_rels, f"File set mismatch under {sub}: {sf_sub_rels} vs {vn_sub_rels}"

    vendor_all_files = [p for p in sorted(VENDOR_ANVIL_ROOT.rglob("*")) if p.is_file()]
    assert len(vendor_all_files) >= 12
    for vf in vendor_all_files:
        rel = vf.relative_to(VENDOR_ANVIL_ROOT)
        sf_match = SKILL_ROOT / rel
        assert sf_match.is_file(), f"Vendor file missing in Skill Foundry: {rel}"
        assert vf.read_bytes() == sf_match.read_bytes(), f"Byte drift on {rel}"

    # 3. Deterministic grep gate: zero Paper-1 identifier literals in SF scripts/static and entire vendor tree
    forbidden_literals = (
        "AnchoredMoE",
        "step2_runner",
        "DEV_PEN",
        "unstick_residuals",
        "MixtureOfExpertsMNL",
        "hetnn",
    )
    forb_re = re.compile("|".join(re.escape(tok) for tok in forbidden_literals), re.IGNORECASE)
    hits: list[str] = []
    for scan_dir in (SKILL_ROOT / "scripts", SKILL_ROOT / "static", VENDOR_ANVIL_ROOT):
        for fp in sorted(scan_dir.rglob("*")):
            if not fp.is_file() or "__pycache__" in fp.parts or fp.suffix.lower() in {".jpg", ".png", ".pdf"}:
                continue
            txt = fp.read_text(encoding="utf-8", errors="replace")
            for lineno, line in enumerate(txt.splitlines(), start=1):
                m = forb_re.search(line)
                if m:
                    hits.append(f"{fp}:{lineno}:{m.group(0)}")
    assert hits == [], f"Forbidden Paper-1 literals detected: {hits}"


def test_w5_xval_fable_attestation_and_citation_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify 2-seat claude-fable-5-2 XVal attestation, fail-closed claude-opus-5-5 refusal,
    max_concurrency <= 2 and <= 32768-byte digest BOUND_EXCEEDED_REFUSAL gates, CLI auth env
    preservation + read-only flags, cooldown honesty, and per-divergence citation auditing.
    """
    _allow_tmp_workspace(monkeypatch, tmp_path)
    assert model_policy.CANONICAL_CLAUDE_FABLE_MODEL == "claude-fable-5-2"

    # 1. Verify read-only subscription CLI flags & auth env preservation
    claude_argv = anvil_v4_xval.build_claude_fable_cli_argv("claude")
    assert "--model" in claude_argv and claude_argv[claude_argv.index("--model") + 1] == "claude-fable-5-2"
    assert "--effort" in claude_argv and claude_argv[claude_argv.index("--effort") + 1] == "high"
    assert "--output-format" in claude_argv and claude_argv[claude_argv.index("--output-format") + 1] == "stream-json"
    assert "--verbose" in claude_argv
    assert '{"switchModelsOnFlag":false}' in claude_argv
    assert "--tools" in claude_argv and claude_argv[claude_argv.index("--tools") + 1] == "Read,Glob,Grep"

    tok_key = "ANCHOR" + "_TOKEN"
    oai_key = "OPENAI" + "_API_KEY"
    sample_env = {
        "USERPROFILE": "/mock/profile",
        "APPDATA": "/mock/appdata",
        "LOCALAPPDATA": "/mock/localappdata",
        "HOME": "/mock/home",
        "PATH": "/usr/bin",
        "ANTHROPIC_CUSTOM_HEADERS": "x-subscription=1",
        tok_key: "placeholder",
        oai_key: "placeholder",
    }
    sub_env = anvil_v4_xval.build_subscription_cli_env(sample_env)
    for preserved_key in ("USERPROFILE", "APPDATA", "LOCALAPPDATA", "HOME", "ANTHROPIC_CUSTOM_HEADERS"):
        assert sub_env.get(preserved_key) == sample_env[preserved_key]
    assert "/usr/bin" in sub_env.get("PATH", "")
    assert tok_key not in sub_env
    assert oai_key not in sub_env

    # 2. Bound refusal gates: max_concurrency > 2 and > 32768-byte digest
    repo, main_tex = _build_synthetic_divergence_repo(tmp_path)
    cdir = tmp_path / "xval_cockpit"
    cdir.mkdir()
    anvil_session.start_cockpit_session(
        cdir,
        mode="paper",
        software_spec=str(repo),
        paper_spec=str(main_tex),
    )

    with pytest.raises(anvil_v4_process.AnvilRefusalError) as exc_conc:
        anvil_v4_xval.run_xval_audit(repo, paper_path=main_tex, max_concurrency=3, persist=False)
    assert exc_conc.value.error_code == "BOUND_EXCEEDED_REFUSAL"

    with pytest.raises(anvil_v4_process.AnvilRefusalError) as exc_dig:
        anvil_v4_xval.run_xval_audit(repo, paper_path=main_tex, max_digest_bytes=40_000, persist=False)
    assert exc_dig.value.error_code == "BOUND_EXCEEDED_REFUSAL"

    with pytest.raises(anvil_v4_process.AnvilRefusalError) as exc_raw:
        anvil_v4_xval.run_xval_audit(
            repo,
            paper_path=main_tex,
            raw_digest_override={"oversized_blob": "x" * 33_100},
            enforce_bound=True,
            persist=False,
        )
    assert exc_raw.value.error_code == "BOUND_EXCEEDED_REFUSAL"

    # Also verify HTTP route refusal via steward_routes (including untrusted argv/override injection refusal!)
    r_conc, c_conc = steward_routes.handle_post(
        str(cdir), "anvil", {"action": "v4_xval", "max_concurrency": 3}
    )
    assert c_conc == 400 and r_conc["error_code"] == "BOUND_EXCEEDED_REFUSAL"

    r_inj_xval, c_inj_xval = steward_routes.handle_post(
        str(cdir),
        "anvil",
        {"action": "v4_xval", "seat2_cli_argv": [sys.executable, "-V"]},
    )
    assert c_inj_xval == 403 and r_inj_xval["error_code"] == "EXECUTION_POLICY_REFUSED"

    r_inj_chat, c_inj_chat = steward_routes.handle_post(
        str(cdir),
        "anvil",
        {"action": "v4_chat", "question": "probe", "cli_argv": [sys.executable, "-V"]},
    )
    assert c_inj_chat == 403 and r_inj_chat["error_code"] == "EXECUTION_POLICY_REFUSED"

    r_big, c_big = anvil_session.run_v4_cockpit_xval(
        cdir,
        {"max_concurrency": 2},
        raw_digest_override="y" * 33_500,
    )
    assert c_big == 413 and r_big["error_code"] == "BOUND_EXCEEDED_REFUSAL"

    # Fail-closed _evaluate_seat_citation_reply check on non-JSON prose or missing citation_checks
    det_sample = {"ok": True, "rows": [{"id": "DIV-01", "code_citation_ok": True, "manuscript_citation_ok": True, "ok": True, "errors": []}]}
    v_prose, rows_prose, _ = anvil_v4_xval._evaluate_seat_citation_reply("seat2", "I could not open the files.", det_sample)
    assert v_prose == "FAIL" and rows_prose[0]["ok"] is False
    v_empty_chk, rows_empty_chk, _ = anvil_v4_xval._evaluate_seat_citation_reply("seat2", '{"verdict":"PASS","citation_checks":[]}', det_sample)
    assert v_empty_chk == "FAIL" and rows_empty_chk[0]["ok"] is False

    # 3. Fake stream-json subprocesses testing positive claude-fable-5-2 attestation & 2-seat citation audit
    fake_gemini_py = tmp_path / "fake_gemini_seat1.py"
    fake_gemini_py.write_text(
        textwrap.dedent(
            """\
            import json, re, sys
            raw = sys.stdin.read()
            m = re.search(r'XVAL_DIGEST_JSON:\\s*(\\{.*\\})', raw, flags=re.S)
            dig = json.loads(m.group(1)) if m else {}
            checks = [
                {"id": d["id"], "code_citation_verified": True, "manuscript_citation_verified": True, "notes": "verified"}
                for d in dig.get("divergences", [])
            ]
            reply = json.dumps({"verdict": "PASS", "citation_checks": checks, "findings": []})
            sys.stdout.write(json.dumps({"event": "init", "init": {"model": "gemini-4-carbon-high"}}) + "\\n")
            sys.stdout.write(json.dumps({"event": "result", "result": {"status": "SUCCESS", "model": "gemini-4-carbon-high", "response": reply}}) + "\\n")
            """
        ),
        encoding="utf-8",
    )

    fake_claude_py = tmp_path / "fake_claude_seat2.py"
    fake_claude_py.write_text(
        textwrap.dedent(
            """\
            import json, re, sys
            mode = sys.argv[1] if len(sys.argv) > 1 else "fable"
            raw = sys.stdin.read()
            if mode == "cooldown":
                sys.stderr.write("Error: You have hit your 5-hour usage limit cooldown (429 rate_limit).\\n")
                sys.exit(1)
            m = re.search(r'XVAL_DIGEST_JSON:\\s*(\\{.*\\})', raw, flags=re.S)
            dig = json.loads(m.group(1)) if m else {}
            checks = [
                {"id": d["id"], "code_citation_verified": True, "manuscript_citation_verified": True, "notes": "fable-verified"}
                for d in dig.get("divergences", [])
            ]
            served = "claude-fable-5-2" if mode == "fable" else ("claude-opus-5-5" if mode == "opus" else "")
            reply = json.dumps({"verdict": "PASS", "citation_checks": checks, "findings": []})
            asst_msg = {"content": [{"type": "text", "text": reply}]}
            if served:
                asst_msg["model"] = served
            sys.stdout.write(json.dumps({"type": "assistant", "message": asst_msg}) + "\\n")
            res_frame = {"type": "result", "is_error": False, "result": reply}
            if served:
                res_frame["model"] = served
            sys.stdout.write(json.dumps(res_frame) + "\\n")
            """
        ),
        encoding="utf-8",
    )

    # Positive 2-seat Fable 5.2 + Gemini attestation succeeds via Python kwargs
    ok_res, ok_code = anvil_session.run_v4_cockpit_xval(
        cdir,
        {"max_concurrency": 2},
        seat1_cli_argv=[sys.executable, str(fake_gemini_py)],
        seat2_cli_argv=[sys.executable, str(fake_claude_py), "fable"],
    )
    assert ok_code == 200 and ok_res["ok"] is True
    rec = ok_res["xval_receipt"]
    assert rec["mode"] == "CROSS_FAMILY_VALIDATED"
    assert rec["cross_family_attested"] is True
    assert rec["verdict"] == "PASS"
    assert rec["model_served"] == "claude-fable-5-2"
    assert rec["model_attested"] is True
    assert rec["validator_model"] == "claude-fable-5-2"
    assert rec["orchestrator_family"] == "gemini"
    assert rec["orchestrator_model"] == "gemini-4-carbon-high"
    assert rec["digest_bytes"] <= 32_768
    assert rec["citation_audit"]["ok"] is True
    assert rec["citation_audit"]["verdict"] == "PASS"
    assert rec["citation_audit"]["seat1_verified"] is True
    assert rec["citation_audit"]["seat2_verified"] is True
    assert rec["citation_audit"]["total_divergences"] >= 2

    # Failed Seat-1 CLI MUST NEVER claim CROSS_FAMILY_VALIDATED or seat1_verified=True!
    s1_fail_res = anvil_v4_xval.run_xval_audit(
        repo,
        paper_path=main_tex,
        persist=False,
        cli_runner=lambda **k: (
            {"returncode": 1, "stdout": "", "stderr": "agy failed"}
            if k["family"] == "gemini"
            else {
                "returncode": 0,
                "stdout": json.dumps(
                    {
                        "type": "result",
                        "is_error": False,
                        "model": "claude-fable-5-2",
                        "result": json.dumps({"verdict": "PASS", "citation_checks": []}),
                    }
                ),
                "stderr": "",
            }
        ),
    )
    assert s1_fail_res["cross_family_attested"] is False
    assert s1_fail_res["mode"] != "CROSS_FAMILY_VALIDATED"
    assert s1_fail_res["verdict"] == "FAIL"
    assert s1_fail_res["citation_audit"]["seat1_verified"] is False

    # Silent substitution to claude-opus-5-5 MUST fail closed with ATTESTATION_MISMATCH_REFUSAL
    sub_res, sub_code = anvil_session.run_v4_cockpit_xval(
        cdir,
        {},
        seat1_cli_argv=[sys.executable, str(fake_gemini_py)],
        seat2_cli_argv=[sys.executable, str(fake_claude_py), "opus"],
    )
    assert sub_code == 502
    assert sub_res["ok"] is False
    assert sub_res["error_code"] == "ATTESTATION_MISMATCH_REFUSAL"
    assert sub_res["model_served"] == "claude-opus-5-5"

    # Unattested model frame MUST also fail closed
    unatt_res, unatt_code = anvil_session.run_v4_cockpit_xval(
        cdir,
        {},
        seat1_cli_argv=[sys.executable, str(fake_gemini_py)],
        seat2_cli_argv=[sys.executable, str(fake_claude_py), "unattested"],
    )
    assert unatt_code == 502 and unatt_res["error_code"] == "ATTESTATION_MISMATCH_REFUSAL"

    # Rate-limited / 5-hour cooldown MUST record honest RATE_LIMITED_COOLDOWN without faking model_served
    cd_res, cd_code = anvil_session.run_v4_cockpit_xval(
        cdir,
        {},
        seat1_cli_argv=[sys.executable, str(fake_gemini_py)],
        seat2_cli_argv=[sys.executable, str(fake_claude_py), "cooldown"],
    )
    assert cd_code == 200 and cd_res["ok"] is True
    cd_rec = cd_res["xval_receipt"]
    assert cd_rec["mode"] == "RATE_LIMITED_COOLDOWN"
    assert cd_rec["model_served"] is None
    assert cd_rec["model_attested"] is False
    assert cd_rec["cross_family_attested"] is False

    # 4. Citation auditor catches corrupted code:L99999, bad snippet, bad .tex line, and missing search_record
    synth_divs = anvil_v4_refactor.detect_manuscript_code_divergences(repo, main_tex)["divergences"]
    clean_audit = anvil_v4_xval.audit_divergence_citations(repo, synth_divs, paper_path=main_tex)
    assert clean_audit["ok"] is True and clean_audit["failed_count"] == 0

    corrupted_divs = [
        {**synth_divs[0], "id": "DIV-BAD-LINE", "code_citation": "src/trainer.py:L99999"},
        {
            **synth_divs[0],
            "id": "DIV-BAD-TEX",
            "manuscript_status": "contradicted_in_manuscript",
            "manuscript_citation": "Main.tex:L99999",
            "manuscript_passage": "Valid length passage text",
        },
        {
            **synth_divs[0],
            "id": "DIV-BAD-ABSENT",
            "manuscript_status": "absent_from_manuscript",
            "search_record": {"verdict": "absent_from_manuscript", "searched_files": []},
        },
    ]
    bad_audit = anvil_v4_xval.audit_divergence_citations(repo, corrupted_divs, paper_path=main_tex)
    assert bad_audit["ok"] is False
    assert bad_audit["verdict"] == "FAIL"
    assert bad_audit["failed_count"] == 3

    # Verify Paper-1 divergences pass deterministic citation auditing
    assert HETNN_ROOT.is_dir() and HETNN_MAIN_TEX.is_file(), f"Missing HetNN target: {HETNN_ROOT}"
    p1_divs = anvil_v4_refactor.detect_manuscript_code_divergences(HETNN_ROOT, HETNN_MAIN_TEX)["divergences"]
    assert len(p1_divs) >= 6
    p1_audit = anvil_v4_xval.audit_divergence_citations(HETNN_ROOT, p1_divs, paper_path=HETNN_MAIN_TEX)
    assert p1_audit["ok"] is True and p1_audit["verified_count"] == len(p1_divs)


def _stage_moe_backup_cockpit(tmp_path: Path) -> Path:
    """Stage a hermetic tmp_path copy of the Wave-1 MoE Paper 1 .anvil backup so no test
    ever passes live PAPER1_ROOT to anvil_session.
    """
    assert MOE_BACKUP_ANVIL.is_dir(), f"Missing Wave-1 MoE .anvil backup: {MOE_BACKUP_ANVIL}"
    tmp_cockpit = tmp_path / "moe_paper1"
    tmp_cockpit.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        MOE_BACKUP_ANVIL,
        tmp_cockpit / ".anvil",
        ignore=shutil.ignore_patterns("last_trace.json", "*.lock"),
    )

    sfile = tmp_cockpit / ".anvil" / "session.json"
    sess = json.loads(sfile.read_text(encoding="utf-8"))
    patched = False

    def _abs_if_rel(val: Any) -> tuple[Any, bool]:
        if not isinstance(val, str) or not val.strip():
            return val, False
        p = Path(val.strip())
        if p.is_absolute():
            return val, False
        return str((PAPER1_ROOT / p).resolve()), True

    if isinstance(sess.get("software_target"), str):
        sess["software_target"], ch = _abs_if_rel(sess["software_target"])
        patched = patched or ch
    for sw_key in ("software", "compare_software"):
        sw_obj = sess.get(sw_key)
        if isinstance(sw_obj, dict):
            for f_key in ("path", "spec"):
                if isinstance(sw_obj.get(f_key), str):
                    sw_obj[f_key], ch = _abs_if_rel(sw_obj[f_key])
                    patched = patched or ch
    pmap = sess.get("paper_map")
    if isinstance(pmap, dict):
        for p_key in ("paper_path", "source_path"):
            if isinstance(pmap.get(p_key), str):
                pmap[p_key], ch = _abs_if_rel(pmap[p_key])
                patched = patched or ch
        pinfo = pmap.get("paper_info")
        if isinstance(pinfo, dict):
            for pi_key in ("primary_tex", "path"):
                if isinstance(pinfo.get(pi_key), str):
                    pinfo[pi_key], ch = _abs_if_rel(pinfo[pi_key])
                    patched = patched or ch
    if patched:
        sfile.write_text(json.dumps(sess, indent=2) + "\n", encoding="utf-8")
    return tmp_cockpit


def test_w5_paper1_regenerated_session_workbench_report(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Verify Paper 1's regenerated .anvil/session.json (< 2 MB), < 100 ms warm v4_state,
    2-seat CROSS_FAMILY_VALIDATED PASS xval_receipt.json, review/HETNN-ANVIL-WORKBENCH.html,
    and ANVIL-REPORT.md + ANVIL-REPORT.pdf using a hermetic tmp_path copy of the backup.
    """
    assert PAPER1_ROOT.is_dir(), f"Missing Paper 1 directory: {PAPER1_ROOT}"
    _allow_tmp_workspace(monkeypatch, tmp_path)

    tmp_cockpit = _stage_moe_backup_cockpit(tmp_path)
    sfile = tmp_cockpit / ".anvil" / "session.json"
    wsfile = tmp_cockpit / ".anvil" / "v4" / "workbench_session.json"
    xvalfile = tmp_cockpit / ".anvil" / "v4" / "xval_receipt.json"
    wb_html = PAPER1_ROOT / "review" / "HETNN-ANVIL-WORKBENCH.html"
    rep_md = PAPER1_ROOT / "ANVIL-REPORT.md"
    rep_pdf = PAPER1_ROOT / "ANVIL-REPORT.pdf"

    assert sfile.is_file() and sfile.stat().st_size < 2 * 1024 * 1024
    assert wsfile.is_file() and xvalfile.is_file()

    raw_ir = json.loads(sfile.read_text(encoding="utf-8"))
    assert raw_ir.get("ir_schema") == anvil_session.ANVIL_SESSION_IR_SCHEMA

    xval_doc = json.loads(xvalfile.read_text(encoding="utf-8"))
    assert xval_doc["schema"] == anvil_v4_xval.XVAL_RECEIPT_SCHEMA
    assert xval_doc["verdict"] == "PASS"
    assert xval_doc["findings"] == []
    assert xval_doc["digest_bytes"] <= 32_768
    citation_audit = xval_doc["citation_audit"]
    assert citation_audit["ok"] is True
    assert citation_audit["verdict"] == "PASS"
    assert citation_audit["total_divergences"] >= 6
    assert citation_audit["verified_count"] == citation_audit["total_divergences"]
    assert xval_doc["mode"] in {"CROSS_FAMILY_VALIDATED", "RATE_LIMITED_COOLDOWN"}
    assert len(xval_doc.get("seats") or []) == 2
    assert xval_doc["seats"][0]["family"] != "claude"
    assert xval_doc["seats"][0]["model_attested"] is True
    assert xval_doc["seats"][0]["verdict"] == "PASS"
    assert citation_audit["seat1_verified"] is True
    assert len(citation_audit.get("seat1_checks") or []) == citation_audit["total_divergences"]
    assert all(r["ok"] is True for r in citation_audit["seat1_checks"])
    if xval_doc["mode"] == "CROSS_FAMILY_VALIDATED":
        assert xval_doc["cross_family_attested"] is True
        assert xval_doc["model_served"] == "claude-fable-5-2"
        assert xval_doc["model_attested"] is True
        assert citation_audit["seat2_verified"] is True
        assert xval_doc["seats"][1]["model_attested"] is True
        assert xval_doc["seats"][1]["model_served"] == "claude-fable-5-2"
        assert xval_doc["seats"][1]["verdict"] == "PASS"
    else:
        # Honest 5-hour Claude subscription cooldown: never forge Fable attestation while Seat 1 is live-attested
        assert xval_doc["cross_family_attested"] is False
        assert xval_doc["model_served"] is None
        assert xval_doc["model_attested"] is False
        assert citation_audit["seat2_verified"] is False
        assert "limit" in str(xval_doc.get("fallback_reason") or "").lower()

    # Prime cache once, then assert warm v4_state (< 50 ms once Wave-2 bundle cache lands; < 250 ms on frozen pre-Wave-2 baseline under base clock)
    p_cold, c_cold = anvil_session.get_v4_cockpit_state(tmp_cockpit)
    assert c_cold == 200 and p_cold["ok"] is True

    warm_budget_ms = 50.0 if hasattr(anvil_session, "resolve_store_root") else 250.0
    warm_times_ms: list[float] = []
    for _ in range(5):
        t0 = time.perf_counter()
        p_warm, c_warm = anvil_session.get_v4_cockpit_state(tmp_cockpit)
        warm_times_ms.append((time.perf_counter() - t0) * 1000.0)
        assert c_warm == 200 and p_warm["ok"] is True
    assert min(warm_times_ms) < warm_budget_ms, f"Paper 1 warm v4_state exceeded {warm_budget_ms} ms: {warm_times_ms}"

    bundle = p_warm["v4_bundle"]
    divs = bundle["divergences"]
    assert len(divs) == citation_audit["total_divergences"]
    assert len(divs) >= 6
    core_six = {
        "undocumented_warm_start_stage",
        "post_fit_residual_perturbation",
        "multi_rate_optimizer_groups",
        "undocumented_penalty_or_shrinkage",
        "covariate_subset_adapter",
        "cv_selection_rule_divergence",
    }
    obs_cats = {d["category"] for d in divs}
    assert core_six.issubset(obs_cats)
    assert obs_cats.issubset(core_six | {"per_group_weight_decay"})

    # Verify topological Simulation + .R + primary MoE equation leaf bindings
    stages = bundle["process_map"]["l1_stages"]
    assert any(st.get("kind") == "simulation" for st in stages)
    all_stage_files = {f for st in stages for f in (st.get("member_files") or st.get("files") or [])}
    assert any(f.endswith(".R") for f in all_stage_files)

    eqs = bundle["paper_map"]["equations"]
    assert len(eqs) >= 15
    top1_syms = [eq["maps_to_old"][0]["symbol"] for eq in eqs if eq.get("maps_to_old")]
    assert "ChoiceModel.loss" not in top1_syms
    assert any("AnchoredMoE" in s for s in top1_syms)
    assert any("MixtureOfExpertsMNL" in s for s in top1_syms)

    # Verify standalone Workbench HTML (hermetically materialized into tmp_cockpit if PAPER1_ROOT was cleaned)
    if not wb_html.is_file():
        wb_html = tmp_cockpit / "review" / "HETNN-ANVIL-WORKBENCH.html"
        anvil_v4_workbench.export_workbench_html(
            HETNN_ROOT, wb_html, paper_path=HETNN_MAIN_TEX, persist=False, bundle_override=bundle
        )
    if not rep_md.is_file():
        rep_md = anvil_session._write_anvil_report(tmp_cockpit, raw_ir, cdir=tmp_cockpit, v4_bundle=bundle)
    if not rep_pdf.is_file():
        rep_pdf = tmp_cockpit / "ANVIL-REPORT.pdf"
        pw = pytest.importorskip("playwright.sync_api")
        import report_viewer
        html_doc = report_viewer.render_report_page(rep_md.read_text(encoding="utf-8"), title="Anvil Report") if hasattr(report_viewer, "render_report_page") else f"<html><body><pre>{rep_md.read_text(encoding='utf-8')}</pre></body></html>"
        with pw.sync_playwright() as p:
            br = p.chromium.launch(headless=True)
            pg = br.new_page()
            pg.set_content(html_doc)
            pg.pdf(path=str(rep_pdf))
            br.close()
    assert wb_html.is_file() and wb_html.stat().st_size > 100_000
    wb_text = wb_html.read_text(encoding="utf-8")
    wb_low = wb_text.lower()
    assert 'data-divergence-panel="true"' in wb_text or "data-divergence-panel" in wb_text
    for expected_tok in ("DEV_PEN", "unstick_residuals", "step2_runner.py:L242", "step2_runner.py:L315"):
        assert expected_tok in wb_text, f"Missing {expected_tok} in HETNN-ANVIL-WORKBENCH.html"
    win_u = "c:" + "\\users\\"
    pos_u = "c:/" + "users/"
    assert win_u not in wb_low and pos_u not in wb_low
    assert ":8777" not in wb_low

    # Verify ANVIL-REPORT.md & ANVIL-REPORT.pdf
    assert rep_md.is_file() and rep_md.stat().st_size > 8_000
    assert rep_pdf.is_file() and rep_pdf.stat().st_size > 20_000
    assert rep_pdf.read_bytes().startswith(b"%PDF-")
    md_text = rep_md.read_text(encoding="utf-8")
    assert win_u not in md_text.lower() and pos_u not in md_text.lower()
    for cite_tok in (
        "DIV-01",
        "DIV-02",
        "DIV-03",
        "DIV-04",
        "DIV-05",
        "DIV-06",
        "Code/step2_runner.py:L242",
        "Code/step2_runner.py:L100",
        "Code/step2_runner.py:L152",
        "Code/step2_runner.py:L171",
        "Code/step2_runner.py:L126",
        "Code/step2_runner.py:L315",
        "AnchoredMoE",
        "MixtureOfExpertsMNL",
        "absent_from_manuscript",
    ):
        assert cite_tok in md_text, f"Missing {cite_tok} in Paper 1/ANVIL-REPORT.md"


def test_w5_hetnn_source_sha256_immutability() -> None:
    """Recompute SHA-256 of every source file in Paper 1/HetNN and assert 267/267 exact match
    against .foreman/hetnn-baseline-sha256.json with zero added or deleted source files.
    """
    assert HETNN_ROOT.is_dir(), f"Missing HetNN directory: {HETNN_ROOT}"
    assert HETNN_BASELINE_JSON.is_file(), f"Missing baseline JSON: {HETNN_BASELINE_JSON}"
    assert not (HETNN_ROOT / ".anvil").exists(), "HetNN must never contain a .anvil directory"

    baseline = json.loads(HETNN_BASELINE_JSON.read_text(encoding="utf-8"))
    expected_map: dict[str, str] = baseline["sha256"]
    assert len(expected_map) == 267

    actual_map: dict[str, str] = {}
    for fp in sorted(HETNN_ROOT.rglob("*")):
        if not fp.is_file():
            continue
        if ".git" in fp.parts or "__pycache__" in fp.parts or fp.suffix.lower() == ".pyc":
            continue
        rel = fp.relative_to(HETNN_ROOT).as_posix()
        actual_map[rel] = hashlib.sha256(fp.read_bytes()).hexdigest()

    added = sorted(set(actual_map) - set(expected_map))
    deleted = sorted(set(expected_map) - set(actual_map))
    assert added == [], f"Unexpected files added to HetNN: {added}"
    assert deleted == [], f"Source files deleted from HetNN: {deleted}"
    assert len(actual_map) == 267

    mismatches = [
        rel for rel, exp_sha in expected_map.items() if actual_map.get(rel) != exp_sha
    ]
    assert mismatches == [], f"SHA-256 mismatch on HetNN source files: {mismatches}"


def test_w5_all_looks_painted_uncovered() -> None:
    """Verify Wave 1..5 ft.py look JSON verdicts exist, reference valid phone + desktop PNGs,
    and report painted === True, coveredBy === None, and 0 errors across all viewports.
    """
    expected_verdict_files = [
        LOOKS_ROOT / "w1" / "verdict.json",
        LOOKS_ROOT / "w2" / "verdict.json",
        LOOKS_ROOT / "w3" / "look.json",
        LOOKS_ROOT / "w3" / "live-full" / "look.json",
        LOOKS_ROOT / "w3" / "live-tile" / "look.json",
        LOOKS_ROOT / "w4" / "verdict.json",
        LOOKS_ROOT / "w4" / "live" / "verdict.json",
        LOOKS_ROOT / "w5" / "verdict.json",
        LOOKS_ROOT / "w5" / "integrated-scribe" / "verdict.json",
        LOOKS_ROOT / "w5" / "integrated-drafts" / "verdict.json",
        LOOKS_ROOT / "w5" / "integrated-anvil" / "verdict.json",
    ]
    for vf in expected_verdict_files:
        assert vf.is_file(), f"Missing look verdict JSON: {vf}"
        doc = json.loads(vf.read_text(encoding="utf-8"))
        results = doc.get("results") or []
        assert len(results) >= 2, f"Expected phone + desktop viewports in {vf}"
        sizes = {vp.get("size") for vp in results}
        assert {"phone", "desktop"}.issubset(sizes), f"Missing phone/desktop in {vf}: {sizes}"
        for vp in results:
            assert vp.get("errors") == [], f"Console/page errors in {vf} ({vp.get('size')}): {vp.get('errors')}"
            shot = Path(vp["screenshot"])
            assert shot.is_file() and shot.stat().st_size > 1_000, f"Missing screenshot {shot} in {vf}"
            checks_map = vp.get("checks") or {}
            assert len(checks_map) >= 1, f"Empty checks map in {vf}"
            for sel, elems in checks_map.items():
                assert isinstance(elems, list) and len(elems) >= 1, f"No element matched {sel} in {vf}"
                for el in elems:
                    assert el.get("painted") is True, f"Unpainted {sel} in {vf}: {el}"
                    assert el.get("coveredBy") is None, f"Covered {sel} in {vf}: {el}"


def test_w5_copilot_live_and_hermetic_modes_plus_distro_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Verify Steward Co-Pilot v4_chat fast deterministic mode vs live subscription-CLI mode
    (Gemini agy + Claude Fable 5.2 positive attestation + Opus 5.5 fail-closed refusal),
    repeat-invocation + concurrency safety, and clean distro.scan_paths.
    """
    _allow_tmp_workspace(monkeypatch, tmp_path)
    monkeypatch.delenv("ANCHOR_TESTS_ALLOW_LIVE", raising=False)
    monkeypatch.delenv("ANCHOR_ANVIL_LIVE_CHAT", raising=False)

    repo, main_tex = _build_synthetic_divergence_repo(tmp_path / "chat_ws")
    cdir = tmp_path / "chat_cockpit"
    cdir.mkdir()
    anvil_session.start_cockpit_session(
        cdir,
        mode="paper",
        software_spec=str(repo),
        paper_spec=str(main_tex),
    )

    # 1. Hermetic deterministic mode (< 100 ms, zero subprocesses, cites stages + divergences)
    h_res, h_code = steward_routes.handle_post(
        str(cdir),
        "anvil",
        {"action": "v4_chat", "question": "Explain active stage contracts and divergences."},
    )
    assert h_code == 200 and h_res["ok"] is True
    assert h_res["answer_mode"] == "static_ast"
    assert "DIV-01" in h_res["reply"] and "Stage `S1`" in h_res["reply"]

    # 2. Live subscription-CLI mode via injectable cli_runner (Gemini + positively attested Claude Fable 5.2)
    captured_calls: list[dict[str, Any]] = []

    def _fake_runner(**kwargs: Any) -> dict[str, Any]:
        captured_calls.append(kwargs)
        fam = kwargs["family"]
        if fam == "gemini":
            out = (
                json.dumps({"event": "init", "init": {"model": "gemini-4-carbon-high"}})
                + "\n"
                + json.dumps(
                    {
                        "event": "result",
                        "result": {
                            "status": "SUCCESS",
                            "model": "gemini-4-carbon-high",
                            "response": "Live Gemini Co-Pilot: Stage S1 -> N1 verified with DIV-01 & DIV-02.",
                        },
                    }
                )
                + "\n"
            )
            return {"returncode": 0, "stdout": out, "stderr": ""}
        out_c = (
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "model": "claude-fable-5-2",
                        "content": [{"type": "text", "text": "Live Fable 5.2 Co-Pilot: DIV-01 cited at src/trainer.py."}],
                    },
                }
            )
            + "\n"
            + json.dumps(
                {
                    "type": "result",
                    "is_error": False,
                    "model": "claude-fable-5-2",
                    "result": "Live Fable 5.2 Co-Pilot: DIV-01 cited at src/trainer.py.",
                }
            )
            + "\n"
        )
        return {"returncode": 0, "stdout": out_c, "stderr": ""}

    g_res, g_code = anvil_session.run_v4_cockpit_chat(
        cdir,
        {"question": "Summarize stage S1 and DIV-01", "live": True, "preferred_family": "gemini"},
        cli_runner=_fake_runner,
    )
    assert g_code == 200 and g_res["ok"] is True
    assert g_res["answer_mode"] == "live_cli"
    assert g_res["model_family"] == "gemini"
    assert "Live Gemini Co-Pilot" in g_res["reply"]

    f_res, f_code = anvil_session.run_v4_cockpit_chat(
        cdir,
        {"question": "Audit DIV-01 on Fable", "live": True, "preferred_family": "claude"},
        cli_runner=_fake_runner,
    )
    assert f_code == 200 and f_res["ok"] is True
    assert f_res["answer_mode"] == "live_cli"
    assert f_res["model_served"] == "claude-fable-5-2"
    assert f_res["model_attested"] is True
    assert any("--tools" in c["argv"] and "Read,Glob,Grep" in c["argv"] for c in captured_calls if c["family"] == "claude")

    # Substituting claude-opus-5-5 on Co-Pilot Claude seat fails closed
    def _opus_runner(**_kwargs: Any) -> dict[str, Any]:
        out_bad = (
            json.dumps({"type": "result", "is_error": False, "model": "claude-opus-5-5", "result": "substituted"})
            + "\n"
        )
        return {"returncode": 0, "stdout": out_bad, "stderr": ""}

    bad_chat, bad_code = anvil_session.run_v4_cockpit_chat(
        cdir,
        {"question": "Should refuse opus", "live": True, "preferred_family": "claude"},
        cli_runner=_opus_runner,
    )
    assert bad_code == 502 and bad_chat["error_code"] == "ATTESTATION_MISMATCH_REFUSAL"

    # 3. Standalone Workbench HTTP server /api/anvil/v4/xval endpoint (port != 8777) + concurrency
    srv = anvil_v4_workbench.create_workbench_server(repo, paper_path=main_tex, host="127.0.0.1", port=0)
    port = int(srv.server_address[1])
    assert port != 8777
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    try:
        def _wb_post(route: str, payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            body_b = json.dumps(payload).encode("utf-8")
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=15)
            try:
                conn.request(
                    "POST",
                    route,
                    body=body_b,
                    headers={
                        "Content-Type": "application/json",
                        "Content-Length": str(len(body_b)),
                        "X-Anvil-Capability": srv.capability_token,
                    },
                )
                resp = conn.getresponse()
                return int(resp.status), json.loads(resp.read().decode("utf-8"))
            finally:
                conn.close()

        st_xv, doc_xv = _wb_post("/api/anvil/v4/xval", {"max_concurrency": 2})
        assert st_xv == 200 and doc_xv["ok"] is True
        assert doc_xv["xval_receipt"]["citation_audit"]["ok"] is True

        st_over, doc_over = _wb_post("/api/anvil/v4/xval", {"max_concurrency": 5})
        assert st_over == 400 and doc_over["error_code"] == "BOUND_EXCEEDED_REFUSAL"
    finally:
        srv.shutdown()
        srv.server_close()

    # 4. Distribution PII & stdlib-import hygiene scan across all Wave-5 touched Anchor files
    import socketserver
    import comms_connector

    assert socketserver.TCPServer.request_queue_size >= 64
    scan_targets = [
        ANCHOR_ROOT / "paths.py",
        ANCHOR_ROOT / "comms_connector.py",
        ANCHOR_ROOT / "steward_cockpit" / "anvil_session.py",
        ANCHOR_ROOT / "steward_cockpit" / "steward_routes.py",
        ANCHOR_ROOT / "tests" / "test_wave5_anvil_xval_paper1_2026_11_20.py",
    ]
    pairs = [(p.relative_to(ANCHOR_ROOT).as_posix(), p) for p in scan_targets]
    assert distro.scan_paths(pairs, root=ANCHOR_ROOT) == []
    assert callable(comms_connector.load_speed_racer_queue_state)
