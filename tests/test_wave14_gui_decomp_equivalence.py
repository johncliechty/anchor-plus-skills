"""test_wave14_gui_decomp_equivalence.py — Wave 14 Anvil GUI Decomposition & Hypothesis Equivalence Suite."""
from __future__ import annotations

import json
from pathlib import Path
from hypothesis import given, settings, strategies as st

import anchor_gui as gui
from steward_cockpit import gui_ingress_routes as ingress
from steward_cockpit import gui_domain_core as domain
from steward_cockpit import gui_surface_emit as emit


@settings(max_examples=50)
@given(
    kind=st.sampled_from(["", "trio", "general", "grass-dev", "other"]),
    current_stage=st.sampled_from(["", "research", "plan", "build", "deliverables", "unknown"]),
    lane=st.sampled_from(["research", "plan", "build", "general"]),
)
def test_hypothesis_effort_zone_equivalence(kind: str, current_stage: str, lane: str):
    rec = {"kind": kind, "current_stage": current_stage, "lane": lane}
    # Legacy reference calculation
    if kind in ("general", "grass-dev"):
        expected = None
    elif current_stage == "research":
        expected = gui._EFFORT_ZONE_RESEARCH
    elif current_stage in ("plan", "build"):
        expected = gui._EFFORT_ZONE_PLAN_BUILD
    else:
        expected = None

    assert gui._effort_zone(rec) == expected
    assert domain.effort_zone(rec, gui._EFFORT_ZONE_RESEARCH, gui._EFFORT_ZONE_PLAN_BUILD) == expected


@settings(max_examples=50)
@given(
    discovered=st.booleans(),
    title=st.text(max_size=40),
    artifact_path=st.text(max_size=40),
    sub=st.text(max_size=40),
    skill=st.text(max_size=20),
)
def test_hypothesis_session_tile_title_equivalence(
    discovered: bool,
    title: str,
    artifact_path: str,
    sub: str,
    skill: str,
):
    rep = {
        "discovered": discovered,
        "title": title,
        "artifact_path": artifact_path,
        "sub": sub,
        "skill": skill,
    }
    if discovered:
        expected = (title or artifact_path or "imported").strip()
    elif sub.strip():
        expected = sub.strip()
    else:
        expected = (skill or "session").strip() or "session"

    assert gui._session_tile_title(rep) == expected
    assert domain.session_tile_title(rep) == expected


@settings(max_examples=50)
@given(
    total=st.integers(min_value=-5, max_value=200),
    measured=st.integers(min_value=0, max_value=200),
    unmeasured=st.integers(min_value=0, max_value=50),
    failed=st.integers(min_value=0, max_value=50),
)
def test_hypothesis_fmt_capture_rate_short_equivalence(
    total: int,
    measured: int,
    unmeasured: int,
    failed: int,
):
    rate = {
        "total": total,
        "measured": measured,
        "unmeasured": unmeasured,
        "capture-failed": failed,
    }
    if total <= 0:
        expected = ""
    else:
        parts = [f"measured {measured}/{total}"]
        if unmeasured:
            parts.append(f"{unmeasured} unmeasured")
        if failed:
            parts.append(f"{failed} capture-failed")
        expected = " \u00b7 ".join(parts)

    assert gui._fmt_capture_rate_short(rate) == expected
    assert domain.fmt_capture_rate_short(rate) == expected


def test_wave14_stage_modules_and_null_space_pruning():
    gui_src = Path(gui.__file__).read_text(encoding="utf-8")
    # 3 unreferenced Null-Space scaffolding functions pruned from anchor_gui.py
    assert "def _render_effort_card(" not in gui_src
    assert "def _idea_source_label(" not in gui_src
    assert "def _safe_dom_id(" not in gui_src

    # Stage 1 Ingress validation
    assert ingress.unsafe_path_seg("../secret") is True
    assert ingress.unsafe_path_seg("Anchor Refactoring") is False
    assert ingress.is_loopback_address("127.0.0.1:8777") is True
    assert ingress.is_tailscale_host("gwl-server.tailb49f65.ts.net") is True
    assert ingress.extract_bearer_token({"Authorization": "Bearer tok-123"}) == "tok-123"
    ok, msg = ingress.validate_upload_meta("notes.md", 1024, deny_ext={".exe"})
    assert ok is True and msg == "ok"

    # Stage 2 Domain Core
    fp = domain.compute_build_fingerprint("8233ddd", ["a.py:10:20"])
    assert fp.startswith("8233ddd+") and len(fp.split("+")[1]) == 7
    boot = domain.assemble_anchor_boot(fp, True, extra={"mode": "cave"})
    assert boot == {"schema_ver": 1, "build": fp, "auth": True, "mode": "cave"}

    # Stage 3 Surface Emit
    boot_tag = emit.render_anchor_boot_script({"build": "</script>"})
    assert "<\\/script>" in boot_tag
    sse = emit.format_sse_frame({"ok": True}, event_name="tick")
    assert sse == b'event: tick\ndata: {"ok": true}\n\n'
