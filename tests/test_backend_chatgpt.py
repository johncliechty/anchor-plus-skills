"""ChatGPT (Codex CLI) as a fourth terminal/family peer."""
import importlib
import json
import os
import re
from pathlib import Path

import pytest


@pytest.fixture
def stack(tmp_path, monkeypatch):
    host_localappdata = os.environ.get("LOCALAPPDATA")
    data = tmp_path / "data"
    data.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "local"))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    monkeypatch.setenv("ANCHOR_CLAUDE_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GEMINI_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_GROK_AVAILABLE", "1")
    monkeypatch.setenv("ANCHOR_CHATGPT_AVAILABLE", "1")

    import paths
    importlib.reload(paths)
    import session_registry
    importlib.reload(session_registry)
    import job_runner
    importlib.reload(job_runner)
    import lanes
    importlib.reload(lanes)
    import terminal_session
    importlib.reload(terminal_session)
    import anchor_settings
    importlib.reload(anchor_settings)
    return {
        "reg": session_registry,
        "jr": job_runner,
        "lanes": lanes,
        "ts": terminal_session,
        "settings": anchor_settings,
        "home": home,
        "tmp": tmp_path,
        "host_localappdata": host_localappdata,
    }


def test_valid_backends_include_chatgpt(stack):
    assert "chatgpt" in stack["reg"].VALID_BACKENDS
    assert "chatgpt" in stack["ts"].VALID_BACKENDS
    assert stack["jr"].BACKEND_CHATGPT == "chatgpt"
    assert "chatgpt" in stack["settings"].VALID_CLIS
    # ChatGPT is a valid CODING family but NOT a valid default terminal CLI while
    # the terminal bridge is pending: every terminal open resolves the default
    # engine, so a persisted "chatgpt" would brick them all with a bare 400.
    assert "chatgpt" not in stack["settings"].VALID_DEFAULT_CLIS
    with pytest.raises(ValueError):
        stack["settings"].save_settings(default_cli="chatgpt")
    stack["settings"].save_settings(coding_family="chatgpt", review_family="gemini")
    assert stack["settings"].get_coding_family() == "chatgpt"
    assert stack["settings"].get_default_cli() in stack["settings"].VALID_DEFAULT_CLIS


def test_model_role_capability_matrix_is_honest_by_role(stack):
    import anchor_gui

    caps = anchor_gui.model_role_capabilities({
        "claude": True, "gemini": True, "grok": True, "chatgpt": True,
    })
    roles = caps["roles"]
    assert set(roles) == {"terminal", "coder", "reviewer", "judge"}
    assert roles["terminal"]["families"]["chatgpt"]["status"] == "bridge_pending"
    assert roles["terminal"]["families"]["chatgpt"]["selectable"] is False
    assert roles["coder"]["families"]["chatgpt"]["status"] == "available_unattested"
    assert roles["coder"]["families"]["chatgpt"]["selectable"] is True
    for role in ("reviewer", "judge"):
        chatgpt = roles[role]["families"]["chatgpt"]
        assert chatgpt["status"] == "verification_unattested"
        assert chatgpt["selectable"] is False
        assert "fails closed" in chatgpt["reason"]
    assert roles["judge"]["setting"] == "review_family"
    assert caps["judge_follows"] == "reviewer"


def test_main_dashboard_offers_four_honest_chatgpt_role_controls(stack):
    """The visible home controls match the transport/attestation boundary."""
    import anchor_gui

    controls = anchor_gui.render_model_prefs_controls()
    assert "id='mpDefaultCli'" in controls
    assert "id='mpCoding'" in controls
    assert "id='mpReview'" in controls
    assert "id='mpJudge'" in controls
    assert controls.count("<option value='chatgpt'") == 4
    assert controls.count("ChatGPT &mdash; terminal bridge pending") == 1
    assert controls.count("ChatGPT &mdash; coder ready") == 1
    assert controls.count("ChatGPT &mdash; verification unavailable") == 2
    assert len(re.findall(
        r"<option value='chatgpt'[^>]* disabled>ChatGPT", controls,
    )) == 3
    assert "review_family: ['mpReview', 'mpJudge']" in controls
    assert "data-linked-role='reviewer'" in controls


def test_chatgpt_unavailable_state_is_visible_and_disabled(stack):
    import anchor_gui

    caps = anchor_gui.model_role_capabilities({
        "claude": True, "gemini": True, "grok": True, "chatgpt": False,
    })
    for role in ("terminal", "coder", "reviewer", "judge"):
        chatgpt = caps["roles"][role]["families"]["chatgpt"]
        assert chatgpt["available"] is False
        assert chatgpt["selectable"] is False
        assert chatgpt["status"] == "unavailable"


def test_browser_role_controls_disable_honestly_and_link_judge(stack, monkeypatch):
    """One hermetic browser smoke covers availability and linked persistence."""
    from playwright.sync_api import sync_playwright
    import anchor_gui

    profile = {
        "claude": True, "gemini": True, "grok": True, "chatgpt": True,
    }
    capabilities = anchor_gui.model_role_capabilities(profile)
    state = {
        "ok": True,
        "default_cli": "grok",
        "coding_family": "claude",
        "review_family": "gemini",
        "model_capabilities": capabilities,
    }
    posts = []
    controls = anchor_gui.render_model_prefs_controls()
    page_html = "<!doctype html><html><body>%s</body></html>" % controls

    # The transport fixture redirects LOCALAPPDATA to a synthetic Codex install.
    # Playwright also uses LOCALAPPDATA to find its already-installed browser.
    if stack["host_localappdata"]:
        monkeypatch.setenv("LOCALAPPDATA", stack["host_localappdata"])

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()

        def fulfill(route):
            request = route.request
            if "/api/settings" in request.url:
                if request.method == "POST":
                    body = json.loads(request.post_data or "{}")
                    posts.append(body)
                    state.update(body)
                route.fulfill(
                    status=200, content_type="application/json",
                    body=json.dumps(state),
                )
                return
            route.fulfill(status=200, content_type="text/html", body=page_html)

        page.route("**/*", fulfill)
        page.goto("http://anchor.test/", wait_until="domcontentloaded")
        page.wait_for_function("window.ANCHOR_MODEL_CAPABILITIES !== undefined")

        def option_disabled(selector):
            return page.locator(selector).evaluate("option => option.disabled")

        assert option_disabled("#mpDefaultCli option[value=chatgpt]") is True
        assert option_disabled("#mpCoding option[value=chatgpt]") is False
        assert option_disabled("#mpReview option[value=chatgpt]") is True
        assert option_disabled("#mpJudge option[value=chatgpt]") is True

        page.select_option("#mpJudge", "grok")
        page.wait_for_function(
            "document.querySelector('#mpReview').value === 'grok' && "
            "document.querySelector('#mpJudge').value === 'grok'"
        )
        assert posts[-1] == {"review_family": "grok"}
        browser.close()


def test_resolve_engine_cmd_openai_programs(stack, monkeypatch):
    ts = stack["ts"]
    bin_dir = stack["tmp"] / "local" / "Programs" / "OpenAI" / "Codex" / "bin"
    bin_dir.mkdir(parents=True)
    exe = bin_dir / "codex.exe"
    exe.write_text("", encoding="utf-8")
    monkeypatch.delenv("ANCHOR_ENGINE_CMD", raising=False)
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert Path(ts._resolve_engine_cmd("chatgpt")) == exe


def test_chatgpt_allowed_on_lanes(stack):
    for lane in ("research", "plan", "build", "general"):
        stack["lanes"].check_engine_allowed(lane, "chatgpt")


def test_interactive_chatgpt_terminal_fails_closed_until_bridge_exists(stack):
    with pytest.raises(
        stack["ts"].TerminalSessionError,
        match="chatgpt-gated-bridge-pending",
    ):
        stack["ts"]._check_engine_allowed("general", "chatgpt")


def test_interactive_chatgpt_start_refuses_before_worktree_or_pty(stack, monkeypatch):
    ts = stack["ts"]
    monkeypatch.setattr(ts._rnd, "get_project", lambda _pid: {"id": "p1"})
    monkeypatch.setattr(
        ts._wt, "create_worktree",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("bridge-pending must precede worktree creation")
        ),
    )
    with pytest.raises(ts.TerminalSessionError, match="chatgpt-gated-bridge-pending"):
        ts.start_session("p1", "general", backend="chatgpt")


def test_interactive_chatgpt_switch_refuses_before_source_session_changes(
        stack, monkeypatch):
    ts = stack["ts"]
    source = {
        "session_id": "source",
        "lane": "general",
        "worktree_path": str(stack["tmp"]),
        "project_id": "p1",
        "backend": "claude",
        "seeded": True,
        "seed_text": "seed",
    }
    monkeypatch.setattr(ts._reg, "get_session", lambda _sid: dict(source))
    monkeypatch.setattr(
        ts, "_switch_handoff_summary",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("bridge-pending must precede transcript access")
        ),
    )
    with pytest.raises(ts.TerminalSessionError, match="chatgpt-gated-bridge-pending"):
        ts.switch_engine("source", "chatgpt")


def test_chatgpt_switch_without_worktree_still_reports_bridge_pending(
        stack, monkeypatch):
    ts = stack["ts"]
    monkeypatch.setattr(ts._reg, "get_session", lambda _sid: {
        "session_id": "source", "lane": "general", "worktree_path": "",
        "backend": "claude",
    })
    with pytest.raises(ts.TerminalSessionError, match="chatgpt-gated-bridge-pending"):
        ts.switch_engine("source", "chatgpt")


@pytest.mark.parametrize("backend", ([], {}, ["chatgpt"], {"x": 1}))
def test_backend_boundaries_return_typed_errors_for_unhashable_values(
        stack, backend):
    with pytest.raises(ValueError, match="unknown backend"):
        stack["jr"].build_backend_argv(backend, "hi", stack["tmp"], False)
    with pytest.raises(ValueError, match="unknown backend"):
        stack["jr"].resolve_runner_cmd(backend=backend)
    with pytest.raises(stack["ts"].TerminalSessionError, match="unknown backend"):
        stack["ts"]._check_engine_allowed("general", backend)


def test_detect_host_profile_includes_chatgpt(stack):
    prof = stack["lanes"].detect_host_profile()
    assert prof["chatgpt"] is True


def test_job_runner_uses_safe_headless_adapter_and_refuses_unbuilt_gate_bridge(stack):
    argv = stack["jr"].build_backend_argv(
        "chatgpt", "hi", stack["tmp"], False, permission_mode="plan",
    )
    assert Path(argv[1]).name == "codex_adapter.py"
    assert argv[argv.index("--sandbox") + 1] == "read-only"
    assert Path(argv[argv.index("--target") + 1]) == stack["tmp"].resolve()
    assert "hi" not in argv
    assert "codex" not in Path(argv[0]).name.lower(), "job_runner must launch the adapter"
    with pytest.raises(ValueError, match="chatgpt-gated-bridge-pending"):
        stack["jr"].build_backend_argv("chatgpt", "hi", stack["tmp"], "plan")


def test_codex_adapter_is_required_by_the_deny_by_default_distribution(stack):
    import distro
    selected = set(distro.select_shippable())
    assert "codex_adapter.py" in selected
    manifest_lines = {
        line.strip() for line in (Path(distro.REPO_ROOT) / "dist_manifest.txt")
        .read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    assert "codex_adapter.py" in manifest_lines
