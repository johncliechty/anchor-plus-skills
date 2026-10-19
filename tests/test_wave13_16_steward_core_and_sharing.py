"""Tests for Wave 13 (steward_core.py Anvil extraction + 4-Mode Anvil UI) and Wave 16 (Anchor.exe sharing + 18-skill bundling).

Covers:
1. AST zero-I/O purity audit of steward_cockpit/steward_core.py.
2. Hypothesis property-based differential equivalence between steward_campaign / steward_routes and steward_core.
3. Locked 4-Mode Anvil UI & session payload verification (Conceptual & Process Map, Inner Process Map, Old-to-New Map & Null Space).
4. Wave 16 full 18-skill roster in vendor_skills.SKILL_SOURCES.
5. Wave 16 shell/connect.py & shell/anchor_shell.py GitHub Mothership pull + Tailscale peer discovery.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

from hypothesis import given, settings, strategies as st
import pytest

from shell import connect
from steward_cockpit import anvil_session, steward_campaign, steward_core, steward_routes
import vendor_skills

REPO_ROOT = Path(__file__).resolve().parent.parent
STEWARD_CORE_PATH = REPO_ROOT / "steward_cockpit" / "steward_core.py"
ANVIL_HTML_PATH = REPO_ROOT / "steward_cockpit" / "static" / "anvil.html"


# ---------------------------------------------------------------------------
# 1. AST Purity Audit of steward_cockpit/steward_core.py
# ---------------------------------------------------------------------------

def test_steward_core_is_pure_zero_io():
    """steward_core.py must contain zero I/O, network, subprocess, or filesystem mutations."""
    source = STEWARD_CORE_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(STEWARD_CORE_PATH))

    forbidden_imports = {
        "subprocess", "socket", "urllib", "http", "threading",
        "multiprocessing", "shutil", "sqlite3", "ctypes", "os",
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                assert top not in forbidden_imports, f"Forbidden import in steward_core.py: {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                top = node.module.split(".")[0]
                assert top not in forbidden_imports, f"Forbidden from-import in steward_core.py: {node.module}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                assert node.func.id not in {"open", "exec", "eval", "compile"}, (
                    f"Forbidden builtin call in steward_core.py: {node.func.id}"
                )


def test_steward_core_in_dist_manifest():
    manifest = (REPO_ROOT / "dist_manifest.txt").read_text(encoding="utf-8").splitlines()
    clean = {line.strip() for line in manifest if line.strip() and not line.strip().startswith("#")}
    assert "steward_cockpit/steward_core.py" in clean


# ---------------------------------------------------------------------------
# 2. Hypothesis Property-Based Differential Equivalence (steward_core vs wrappers)
# ---------------------------------------------------------------------------

@given(
    raw=st.one_of(
        st.none(),
        st.dictionaries(
            keys=st.sampled_from(["state", "reason", "state_since", "updated_at", "at", "failure_code", "schema", "provenance"]),
            values=st.one_of(
                st.none(),
                st.sampled_from(["working", "needs_you", "deliverable_ready", "blocked", "idle", "quiet", "invalid"]),
                st.text(max_size=60),
                st.lists(st.text(max_size=20), max_size=3),
            ),
        ),
    ),
    error=st.sampled_from(["", "absent", "parse error"]),
)
@settings(max_examples=50, deadline=None)
def test_hypothesis_normalize_attention_equivalence(raw, error):
    assert steward_campaign._normalize_attention(raw, error=error) == steward_core.normalize_attention(raw, error=error)


@given(
    secs=st.one_of(
        st.none(),
        st.integers(min_value=0, max_value=500000),
    )
)
@settings(max_examples=50, deadline=None)
def test_hypothesis_humanize_age_equivalence(secs):
    assert steward_campaign._humanize(secs) == steward_core.humanize_age(secs)
    if secs is None:
        assert steward_core.humanize_age(secs) == "never"
    elif secs < 90:
        assert steward_core.humanize_age(secs) == "just now"


@given(md_text=st.text(max_size=300))
@settings(max_examples=50, deadline=None)
def test_hypothesis_markdown_and_face_parsers_equivalence(md_text):
    assert steward_campaign._face_sections(md_text) == steward_core.parse_face_sections(md_text)
    assert steward_campaign._strip_md(md_text) == steward_core.strip_markdown(md_text)
    assert steward_campaign._first_sentence(md_text) == steward_core.first_sentence(md_text)
    assert steward_campaign.one_line(md_text) == steward_core.one_line(md_text)
    assert steward_campaign._compact_line(md_text) == steward_core.compact_line(md_text)
    assert steward_campaign._goal_md(md_text) == steward_core.format_goal_md(md_text)


@given(
    effort=st.text(max_size=60),
    summary=st.text(max_size=120),
    doing=st.text(max_size=120),
    status=st.text(max_size=120),
    tests=st.text(max_size=80),
    blocker=st.text(max_size=80),
)
@settings(max_examples=40, deadline=None)
def test_hypothesis_status_facts_equivalence(effort, summary, doing, status, tests, blocker):
    assert steward_campaign.status_facts(
        effort=effort, summary=summary, doing=doing, status=status, tests=tests, blocker=blocker
    ) == steward_core.status_facts(
        effort=effort, summary=summary, doing=doing, status=status, tests=tests, blocker=blocker
    )


@given(
    steps=st.lists(
        st.fixed_dictionaries({
            "id": st.text(min_size=1, max_size=20),
            "name": st.text(min_size=1, max_size=40),
            "part": st.sampled_from(["research", "slice", "rigor", "integrate", "harden", ""]),
            "status": st.sampled_from(["done", "in_progress", "pending", "blocked"]),
            "gate": st.booleans(),
        }),
        max_size=8,
    )
)
@settings(max_examples=40, deadline=None)
def test_hypothesis_work_product_map_equivalence(steps):
    assert steward_campaign.work_product_map(steps) == steward_core.work_product_map(steps)
    assert steward_campaign.derive_product_map(steps) == steward_core.derive_product_map(steps)


@given(
    goal_brief=st.text(max_size=120),
    items=st.lists(
        st.fixed_dictionaries({
            "path": st.text(min_size=1, max_size=40),
            "history": st.lists(st.fixed_dictionaries({"path": st.text(min_size=1, max_size=40)}), max_size=3),
        }),
        max_size=5,
    ),
)
@settings(max_examples=40, deadline=None)
def test_hypothesis_effort_name_and_offered_paths_equivalence(goal_brief, items):
    assert steward_campaign.suggest_effort_name(goal_brief) == steward_core.suggest_effort_name(goal_brief)
    payload = {"items": items, "approved": items[:2]}
    assert steward_routes._offered_paths(payload) == steward_core.extract_offered_paths(payload)


# ---------------------------------------------------------------------------
# 3. Locked 4-Mode Anvil UI & Session Payload Verification
# ---------------------------------------------------------------------------

def test_anvil_session_includes_best_in_class_remap_and_inner_process_map(tmp_path):
    cockpit = tmp_path / "Cockpit"
    cockpit.mkdir()
    result = anvil_session.start_cockpit_session(
        cockpit,
        mode="code",
        software_spec=str(REPO_ROOT / "steward_cockpit"),
        compare_spec="",
    )
    assert result["ok"] is True
    session = result["session"]
    code_map = session["code_map"]
    assert "remap" in session and "best_in_class_map" in session["remap"]
    bic = session["remap"]["best_in_class_map"]
    assert len(bic["old_monoliths"]) >= 10
    assert len(bic["new_blocks"]) == 3
    assert bic["new_blocks"][1]["file"] == "steward_core.py"
    for bucket in code_map["conceptual_buckets"]:
        assert "inner_process_map" in bucket
        assert len(bucket["inner_process_map"].get("steps") or []) >= 1

    html_text = ANVIL_HTML_PATH.read_text(encoding="utf-8")
    assert "1. Conceptual &amp; Process Map" in html_text
    assert "2. Block Drill-Down &amp; Live Probe" in html_text
    assert "3. Old-to-New Map &amp; ∅ Null Space" in html_text
    assert "4. Paper-to-Software Process &amp; Math Map" in html_text


# ---------------------------------------------------------------------------
# 4. Wave 16 — 18-Skill Bundling + GitHub Mothership Pull + Tailscale Discovery
# ---------------------------------------------------------------------------

def test_vendor_skills_declares_full_18_skill_suite():
    names = vendor_skills.declared_skill_names()
    expected = {
        "researchPrime", "crucible", "foreman", "gandalf",
        "jumper", "ramanujan", "legal-beagle", "literature-review",
        "financial-analyst", "tidy-idy", "zombie-hunter",
        "anvil", "superjump", "chekhov", "einstein",
        "figure-designer", "agy-dispatch", "ecgberht",
    }
    assert expected <= set(names)
    assert len(names) >= 18


def test_connect_pull_and_install_mothership_hermetic(tmp_path):
    assert connect.DEFAULT_GITHUB_REPO == "https://github.com/johncliechty/ghostworldlabs-anchor.git"
    assert connect.FALLBACK_GITHUB_REPO == "https://github.com/johncliechty/anchor-plus-skills.git"

    # Reject non-GitHub URLs
    bad = connect.pull_and_install_mothership(tmp_path / "dest", repo_url="http://evil.example/repo.git")
    assert bad["ok"] is False
    assert "https://github.com/" in bad["message"]

    # Simulate git clone populating cold-start files + fallback on primary failure
    calls = []
    dest = tmp_path / "mothership"

    def fake_runner(cmd, cwd=None):
        calls.append(cmd)
        if cmd[:2] == ["git", "clone"] and connect.DEFAULT_GITHUB_REPO in cmd:
            return SimpleNamespace(returncode=1, stdout="", stderr="repository not found")
        if cmd[:2] == ["git", "clone"] and connect.FALLBACK_GITHUB_REPO in cmd:
            dest.mkdir(parents=True, exist_ok=True)
            for req in ("onboard.cmd", "onboard.ps1", "share_onboard.py", "USER-ONBOARD.md"):
                (dest / req).write_text("rem mock\n", encoding="utf-8")
            return SimpleNamespace(returncode=0, stdout="cloned", stderr="")
        if cmd[0] == "cmd.exe":
            return SimpleNamespace(returncode=0, stdout="onboarded", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    res = connect.pull_and_install_mothership(dest, repo_url=connect.DEFAULT_GITHUB_REPO, run_onboard=True, runner_fn=fake_runner)
    assert res["ok"] is True
    assert res["onboard_ready"] is True
    assert res["repo_url"] == connect.FALLBACK_GITHUB_REPO
    assert any(c[0] == "cmd.exe" for c in calls)


def test_connect_discover_tailscale_motherships_hermetic():
    sample_status = {
        "BackendState": "Running",
        "Self": {"DNSName": "laptop.tailnet.ts.net."},
        "Peer": {
            "nodekey:1": {
                "HostName": "ghostworld-mothership",
                "DNSName": "ghostworld-mothership.tailnet.ts.net.",
                "Online": True,
            },
            "nodekey:2": {
                "HostName": "offline-box",
                "DNSName": "offline-box.tailnet.ts.net.",
                "Online": False,
            },
        },
    }
    res = connect.discover_tailscale_motherships(
        runner_fn=lambda cmd: SimpleNamespace(returncode=0, stdout=json.dumps(sample_status), stderr="")
    )
    assert res["ok"] is True
    assert res["backend_state"] == "Running"
    assert res["self_dns"] == "laptop.tailnet.ts.net"
    assert len(res["peers"]) == 2
    assert res["peers"][0]["hostname"] == "ghostworld-mothership"
    assert res["peers"][0]["https_url"] == "https://ghostworld-mothership.tailnet.ts.net"
    assert res["peers"][0]["online"] is True

    # Verify UI pages contain the new buttons and recommended C:\dev folder while preserving existing selectors
    inst_html = connect.installation_page(REPO_ROOT)
    assert "Install your mother ship" in inst_html
    assert 'id="retry-host-setup"' in inst_html
    assert 'id="install-from-github"' in inst_html
    assert 'id="github-repo"' in inst_html
    assert 'id="install-target-dir"' in inst_html
    assert r'value="C:\dev"' in inst_html

    dest_repo, ws_home = connect._resolve_mothership_paths(workspace_dir=r"C:\dev")
    assert dest_repo == Path(r"C:\dev\Anchor")
    assert ws_home == Path(r"C:\dev")

    custom_repo, custom_home = connect._resolve_mothership_paths(workspace_dir=r"D:\MerrillWorkspace")
    assert custom_repo == Path(r"D:\MerrillWorkspace\Anchor")
    assert custom_home == Path(r"D:\MerrillWorkspace")

    setup_html = connect.setup_page()
    assert 'id="addr"' in setup_html
    assert 'id="discover-tailscale"' in setup_html
