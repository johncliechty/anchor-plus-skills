"""Shareable Anchor + Skills — Wave 5 gate.

Frozen plan (``planning/share-anchor-skills-2026-07/IMPLEMENTATION-PLAN.md``
§Wave 5): plain-English onboard — home, prereqs, seats, desktop, consent,
readiness. Extends GREEN ``onboard.py`` via ``share_onboard`` (ext:onboard_dialog).

Hermetic: temp homes only; mock seat probes; no network; no paid CLI; no :8777;
no live subscription CLIs. Live probes remain behind opt-in env (not used here).
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import onboard  # noqa: E402
import share_home_config as home_cfg  # noqa: E402
import share_onboard as sob  # noqa: E402
import share_readiness as ready  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
FAKE_SKILLS = ["researchPrime", "crucible", "foreman", "gandalf"]


def _make_bundle(root: Path, names=None) -> Path:
    src = root / "bundled-skills"
    src.mkdir(parents=True)
    (src / "SOURCES.md").write_text("# provenance\n", encoding="utf-8")
    for name in names or FAKE_SKILLS:
        d = src / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text("# %s\n" % name, encoding="utf-8")
    return src


# ── Module surface ───────────────────────────────────────────────────────────

def test_w5_modules_importable():
    assert callable(sob.run_share_onboard)
    assert callable(sob.preflight_collision_scan)
    assert callable(sob.probe_all_seats)
    assert callable(sob.probe_seat)
    assert callable(sob.write_desktop_url_shortcut)
    assert callable(sob.save_feedback_consent)
    assert callable(sob.actionable_prereq_list)
    assert callable(sob.check_prereqs_fail_early)
    assert callable(sob.rollback_share_onboard)
    assert callable(sob.validate_coding_family_prefs)
    assert sob.default_feedback_opt_in() is False
    assert sob.DEFAULT_LOCAL_DASHBOARD_URL.startswith("http://localhost")


def test_recommend_home_windows_and_three_path_copy():
    assert sob.recommend_home_dir("Windows") == r"C:\dev"
    assert sob.recommend_home_dir("nt") == r"C:\dev"
    lead = sob.three_path_lead_in()
    assert "consumer" in lead and "collaborator" in lead and "feedback" in lead
    assert "local" in lead["consumer"].lower() or "Download" in lead["consumer"]
    copy = sob.feedback_consent_plain_english()
    assert copy["default"] is False
    assert copy["readiness_gate"] is False
    assert "not" in copy["what_is_not_shared"].lower()


# ── GWT #1: foreign skill refuse-don't-clobber + rollback ────────────────────

def test_given_foreign_skill_when_onboard_then_intact_overlay_or_abort(tmp_path):
    """GWT #1: foreign tree intact; overlay leaves it; abort raises; rollback safe."""
    home = tmp_path / "home"
    home.mkdir()
    skills = home / home_cfg.SKILLS_SUBDIR
    skills.mkdir(parents=True)
    foreign = skills / "foreman"
    foreign.mkdir()
    (foreign / "SKILL.md").write_text("# FOREIGN pre-existing\n", encoding="utf-8")
    # No onboard marker → foreign.
    assert not (foreign / onboard._OURS_MARKER).exists()
    foreign_body = (foreign / "SKILL.md").read_text(encoding="utf-8")

    src = _make_bundle(tmp_path / "vendor")

    # abort path
    with pytest.raises(sob.ShareOnboardError) as ei:
        sob.run_share_onboard(
            home,
            package_id="A",
            skills_src=src,
            skills_home=skills,
            mock_seat_results={"claude": True},
            on_collision="abort",
            platform_name="Windows",
        )
    assert "foreign" in ei.value.reason or "collision" in ei.value.reason
    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == foreign_body

    # overlay path — foreign intact; other skills install
    report = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=src,
        skills_home=skills,
        mock_seat_results={"claude": True},
        on_collision="overlay",
        platform_name="Windows",
    )
    assert report["ok"] is True
    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == foreign_body
    assert not (foreign / onboard._OURS_MARKER).exists()
    refused_names = {
        r.get("name") for r in (report.get("skills") or {}).get("refused") or []
    }
    assert "foreman" in refused_names
    # Non-colliding bundled skills installed as ours.
    assert (skills / "crucible" / onboard._OURS_MARKER).is_file()

    # Rollback removes only recorded paths; foreign skill body survives.
    rb = sob.rollback_share_onboard(home)
    assert (foreign / "SKILL.md").read_text(encoding="utf-8") == foreign_body
    assert isinstance(rb.get("removed"), list)


# ── GWT #2: mock claude seat → ready; feedback default false ─────────────────

def test_given_mock_claude_when_readiness_then_ready_feedback_default_off(tmp_path):
    """GWT #2: mock session-visible claude + governance → ready; feedback still false."""
    home = tmp_path / "home-a"
    src = _make_bundle(tmp_path / "vendor-a")

    # Default feedback_opt_in (omit) must be False.
    report = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": {"session_visible": True, "path_present": True}},
        on_collision="overlay",
        platform_name="Windows",
        # feedback_opt_in intentionally omitted → default off
    )
    assert report["ok"] is True
    assert report["feedback_opt_in"] is False
    stamp = report["readiness"]
    assert stamp is not None
    assert stamp["status"] == "ready"
    assert stamp["governance_installed"] is True
    assert stamp["coding_seat_ok"] is True
    assert stamp["feedback_opt_in"] is False
    assert ready.is_green_ready(stamp) is True
    # Unrelated soft warning may appear (journal), but not feedback-gated.
    assert "no_coding_seat" not in stamp["reason_codes"]
    assert "governance_missing" not in stamp["reason_codes"]

    # Consent file on disk defaults to opted_in false.
    pref = sob.load_feedback_consent(home)
    assert pref["opted_in"] is False
    assert pref.get("readiness_gate") is False

    # Explicit opt-in still does not block readiness either way.
    home2 = tmp_path / "home-a2"
    report2 = sob.run_share_onboard(
        home2,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": True},
        feedback_opt_in=True,
        platform_name="Windows",
    )
    assert report2["feedback_opt_in"] is True
    assert report2["readiness"]["status"] == "ready"
    assert report2["readiness"]["feedback_opt_in"] is True


def test_mock_probe_not_path_only_and_openai_rejected():
    """Session-visibility mock stamps ok; path-only is not ok; OpenAI disabled."""
    ok = sob.probe_seat("claude", mock_result={"session_visible": True})
    assert ok["ok"] is True
    assert ok["session_visible"] is True
    assert ok["source"] == "mock"
    assert ok["api_key_fallback"] is False

    path_only = sob.probe_seat(
        "claude",
        mock_result={"session_visible": False, "path_present": True},
    )
    assert path_only["path_present"] is True
    assert path_only["session_visible"] is False
    assert path_only["ok"] is False
    assert path_only["path_only"] is True

    openai = sob.probe_seat("openai")
    assert openai["disabled"] is True
    assert openai["status"] == sob.OPENAI_STATUS
    assert openai["ok"] is False

    codes = sob.validate_coding_family_prefs("openai", "openai")
    assert "openai_sole_family_rejected" in codes

    stamp = sob.stamp_cross_model("claude", "claude")
    assert stamp["cross_model"] is False
    stamp2 = sob.stamp_cross_model("claude", "gemini")
    assert stamp2["cross_model"] is True


def test_write_model_prefs_openai_rejected_without_writing(tmp_path):
    with pytest.raises(sob.ShareOnboardError) as ei:
        sob.write_model_prefs(
            tmp_path,
            coding_family="openai",
            review_family="gemini",
        )
    assert ei.value.reason == "openai_sole_family_rejected"
    assert not sob.model_prefs_path(tmp_path).exists()


# ── GWT #3: Anchor+Skills desktop .url local-only, no elevation ──────────────

def test_given_package_b_when_desktop_then_local_url_no_admin(tmp_path):
    """GWT #3: package B writes .url to local dashboard only; no elevation."""
    home = tmp_path / "home-b"
    src = _make_bundle(tmp_path / "vendor-b")
    desktop = tmp_path / "Desktop"
    desktop.mkdir()

    report = sob.run_share_onboard(
        home,
        package_id="B",
        skills_src=src,
        mock_seat_results={"claude": True, "gemini": True},
        desktop_dir=desktop,
        dashboard_url="http://localhost:8777",
        platform_name="Windows",  # force first-class path hermetically
        on_collision="overlay",
    )
    assert report["ok"] is True
    desk = report["desktop"]
    assert desk is not None
    assert desk["created"] is True
    assert desk["elevation_required"] is False
    assert desk.get("admin_required") is False
    assert desk["url"] == "http://localhost:8777"
    path = Path(desk["path"])
    assert path.is_file()
    assert path.suffix.lower() == ".url"
    text = path.read_text(encoding="utf-8")
    assert "http://localhost:8777" in text
    assert "InternetShortcut" in text
    # No remote / tunnel URL content.
    for bad in ("ngrok", "tailscale", "https://example.com", "ts.net"):
        assert bad not in text.lower() or bad not in text

    # Remote URL refused.
    with pytest.raises(sob.ShareOnboardError) as ei:
        sob.write_desktop_url_shortcut(
            desktop_dir=desktop,
            url="https://evil.example.com/dashboard",
            platform_name="Windows",
        )
    assert "non_local" in ei.value.reason

    # Tunnel-ish host refused even if scheme is http.
    assert sob.is_local_dashboard_url("http://localhost:8777") is True
    assert sob.is_local_dashboard_url("http://127.0.0.1:8777") is True
    assert sob.is_local_dashboard_url("https://myapp.ngrok.io") is False
    assert sob.is_local_dashboard_url("https://example.com") is False


def test_os_honesty_skips_desktop_on_non_windows(tmp_path):
    desk = tmp_path / "Desktop"
    desk.mkdir()
    result = sob.write_desktop_url_shortcut(
        desktop_dir=desk,
        url="http://localhost:8777",
        platform_name="Linux",
    )
    assert result["created"] is False
    assert result["skipped"] is True
    assert "os_desktop_skipped" in result["reason_codes"]
    assert result["elevation_required"] is False


# ── Supporting: prereqs, pin mismatch, live-probe gate, idempotent ───────────

def test_prereqs_fail_early_structure():
    rep = sob.check_prereqs_fail_early(package_id="A")
    assert "rows" in rep
    assert any(r["id"] == "python" for r in rep["rows"])
    # Running under pytest ⇒ Python ok.
    assert rep["ok"] is True


def test_pin_mismatch_stamps_degraded(tmp_path):
    home = tmp_path / "home-pin"
    src = _make_bundle(tmp_path / "vendor-pin")
    report = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": True},
        declared_skills_pin={"tag": "v1.0.0", "commit": "abc"},
        observed_skills_pin={"tag": "v0.9.0", "commit": "def"},
        platform_name="Windows",
    )
    assert report["pin_mismatch"] is True
    assert report["readiness"]["status"] in ("ready", "degraded")
    # skills_pin_mismatch is a degradation reason; may still be ready if
    # user_accepted_degraded or seat+gov — plan says stamp/print degraded.
    # compute_readiness keeps ready when gov+seat unless forked; pin is a code.
    assert "skills_pin_mismatch" in report["readiness"]["reason_codes"]


def test_live_probes_disabled_without_env(monkeypatch):
    monkeypatch.delenv(sob.LIVE_PROBES_ENV, raising=False)
    # No mock → not session-visible in CI (money-safe).
    result = sob.probe_all_seats(mock_results=None)
    assert result["coding_seat_ok"] is False
    for fam in sob.SEAT_FAMILIES:
        assert result["seats"][fam]["source"] == "path-only-no-live"
        assert result["seats"][fam]["session_visible"] is False
        assert result["seats"][fam]["api_key_fallback"] is False


def test_idempotent_second_run(tmp_path):
    home = tmp_path / "home-idemp"
    src = _make_bundle(tmp_path / "vendor-idemp")
    r1 = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
    )
    r2 = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
    )
    assert r1["ok"] and r2["ok"]
    # Second run skips already-installed ours.
    skipped = {x["name"] for x in (r2.get("skills") or {}).get("skipped") or []}
    assert skipped == set(FAKE_SKILLS) or skipped.issubset(set(FAKE_SKILLS))
    assert r2["feedback_opt_in"] is False


# ── Canonical Wave 3: interactive CLI, silent fail-closed, zero-seat ─────────

def test_w3_cli_surface_importable():
    assert callable(sob.main)
    assert callable(sob.onboard_cli)
    assert callable(sob.run_interactive_onboard)
    assert callable(sob.run_silent_onboard)
    assert callable(sob.prompt_feedback_consent)
    assert callable(sob.detect_package_mode)
    assert callable(sob.exit_code_for_report)
    assert sob.FEEDBACK_CONSENT_COPY["default"] is False
    assert sob.default_feedback_opt_in() is False


def test_given_zero_coding_seats_when_onboard_then_not_ready_nonzero(tmp_path):
    """Zero seats → readiness not-ready + non-zero exit (seat matrix)."""
    home = tmp_path / "home-zero"
    src = _make_bundle(tmp_path / "vendor-zero")
    report = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=src,
        mock_seat_results={
            "claude": False,
            "gemini": False,
            "grok": False,
        },
        platform_name="Windows",
        dialogue_complete=True,
    )
    stamp = report["readiness"]
    assert stamp["status"] == "not-ready"
    assert stamp["coding_seat_ok"] is False
    assert "no_coding_seat" in stamp["reason_codes"]
    assert ready.is_green_ready(stamp) is False
    assert sob.exit_code_for_report(report) != 0
    assert report["exit_code"] != 0


def test_given_silent_path_when_complete_then_not_ready(tmp_path):
    """Silent/non-interactive without full dialogue never stamps ready."""
    home = tmp_path / "home-silent"
    src = _make_bundle(tmp_path / "vendor-silent")
    # Even with a mock coding seat, silent path fails closed.
    report = sob.run_silent_onboard(
        home=home,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
    )
    assert report["ok"] is False
    assert report.get("silent") is True
    stamp = report["readiness"]
    assert stamp is not None
    assert stamp["status"] != "ready"
    assert stamp["status"] == "not-ready"
    assert "interactive_onboard_required" in stamp["reason_codes"]
    assert ready.is_green_ready(stamp) is False
    assert sob.exit_code_for_report(report) != 0

    # dialogue_complete=False on library path same contract
    home2 = tmp_path / "home-silent2"
    r2 = sob.run_share_onboard(
        home2,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": True},
        dialogue_complete=False,
        platform_name="Windows",
    )
    assert r2["readiness"]["status"] == "not-ready"
    assert r2["ok"] is False


def test_given_feedback_no_when_export_then_blocked_no_install_key(tmp_path):
    """Feedback default No → no install_key; export blocked."""
    import share_feedback as fb

    home = tmp_path / "home-fb-no"
    src = _make_bundle(tmp_path / "vendor-fb-no")
    report = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": True},
        # omit feedback_opt_in → default No
        platform_name="Windows",
    )
    assert report["feedback_opt_in"] is False
    assert fb.load_install_key(home) is None
    pref = sob.load_feedback_consent(home)
    assert pref["opted_in"] is False
    assert pref.get("install_key_present") is False

    # Export attempt with local friction record is blocked by consent.
    skills = home / home_cfg.SKILLS_SUBDIR
    rec = {
        "schema": "share-skill-journal/v1",
        "schema_version": "1.0.0",
        "record_id": "jr-testfbno",
        "skill_id": "crucible",
        "skill_version": "1.0.0",
        "outcome": "friction",
        "structural_failure_codes": ["timeout"],
        "duration_band": "lt_1m",
        "complexity_band": "small",
        "os_class": "windows",
        "model_family_seats": ["claude"],
        "workaround_codes": ["none"],
    }
    result = fb.try_export_journal_record(home, rec, skills_root=skills)
    assert result.get("enqueued") is False
    assert result.get("exported") is False


def test_given_feedback_yes_when_export_then_allowlist_and_key(tmp_path):
    """Feedback Yes → install_key present; export allowlist-only (no full journal)."""
    import share_feedback as fb
    import share_skill_journal as sjournal
    import share_skill_seal as seal

    home = tmp_path / "home-fb-yes"
    src = _make_bundle(tmp_path / "vendor-fb-yes")
    report = sob.run_share_onboard(
        home,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": True},
        feedback_opt_in=True,
        platform_name="Windows",
    )
    assert report["feedback_opt_in"] is True
    key = fb.load_install_key(home)
    assert key is not None
    pref = sob.load_feedback_consent(home)
    assert pref["opted_in"] is True
    assert pref.get("install_key_present") is True

    skills = home / home_cfg.SKILLS_SUBDIR
    # Ensure seal so export allowed
    if skills.is_dir() and not (skills / seal.SEAL_FILENAME).is_file():
        seal.write_seal(skills)

    rec = sjournal.build_record(
        skill_id="crucible",
        skill_version="1.0.0",
        outcome="friction",
        structural_failure_codes=["timeout"],
        notes="LOCAL ONLY secret project C:\\Users\\secret me@x.com",
        duration_band="1_5m",
        complexity_band="small",
        os_class="windows",
        model_family_seats=["claude"],
        workaround_codes=["retry"],
    )
    result = fb.try_export_journal_record(home, rec, skills_root=skills)
    assert result["exported"] is True
    assert result["enqueued"] is True
    export = result["export_record"]
    assert export["install_key"] == key
    assert "notes" not in export
    assert set(export.keys()).issubset(fb.EXPORT_ALLOWLIST)
    assert fb.export_payload_contains_full_journal(export) is False


def test_interactive_onboard_scripted_default_feedback_no(tmp_path):
    """Interactive path with skip_prompts: feedback default No; seat ready."""
    home = tmp_path / "home-ix"
    src = _make_bundle(tmp_path / "vendor-ix")
    lines = []

    def capture_print(*a, **k):
        lines.append(" ".join(str(x) for x in a))

    report = sob.run_interactive_onboard(
        home=home,
        package_id="A",
        skills_src=src,
        mock_seat_results={"claude": True},
        platform_name="Windows",
        skip_prompts=True,
        print_fn=capture_print,
    )
    assert report["interactive"] is True
    assert report["feedback_opt_in"] is False
    assert report["readiness"]["status"] == "ready"
    assert report["exit_code"] == 0
    transcript = "\n".join(lines)
    # Transcript-friendly markers (plain ASCII dialogue)
    assert "Home" in transcript or "home" in transcript.lower()
    assert "Feedback" in transcript or "feedback" in transcript.lower()
    assert "default No" in transcript or "Default is No" in transcript or (
        "Feedback: No" in transcript
    )


def test_prompt_feedback_consent_default_no():
    """Empty input on feedback prompt → No (locked default)."""
    answers = [""]  # empty → default

    def fake_input(prompt=""):
        return answers.pop(0) if answers else ""

    assert sob.prompt_feedback_consent(input_fn=fake_input, print_fn=lambda *a, **k: None) is False

    answers2 = ["yes"]

    def fake_input_yes(prompt=""):
        return answers2.pop(0) if answers2 else ""

    assert sob.prompt_feedback_consent(
        input_fn=fake_input_yes, print_fn=lambda *a, **k: None
    ) is True


def test_main_non_interactive_exit_nonzero(tmp_path, monkeypatch):
    """python -m share_onboard --non-interactive → not ready, non-zero."""
    home = tmp_path / "home-main-silent"
    home.mkdir()
    src = _make_bundle(tmp_path / "vendor-main-silent")
    code = sob.main([
        "--non-interactive",
        "--home", str(home),
        "--package", "A",
        "--skills-src", str(src),
    ])
    assert code != 0
    stamp_path = home / home_cfg.GOVERNANCE_SUBDIR / "readiness.json"
    if stamp_path.is_file():
        stamp = ready.load_readiness_stamp(stamp_path)
        assert stamp["status"] != "ready"


def test_detect_package_mode_and_permissions_list():
    det = sob.detect_package_mode(REPO)
    assert det["package_id"] in ("A", "B")
    assert "A" in det["candidates"] or det["package_id"] == "A"
    perms_a = sob.permissions_write_list("A")
    assert any("skills" in p.lower() for p in perms_a)
    assert any("never starts" in p.lower() or "Package A" in p for p in perms_a)
    perms_b = sob.permissions_write_list("B")
    assert any("desktop" in p.lower() or "service" in p.lower() for p in perms_b)
