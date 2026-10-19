# W6 gate — the MEASURED first painted open on this machine, on a real
# campaign, recorded as the dated decision-log entry (the wave's early
# measured paint milestone).
#
# AUTH-ON: enforced
#
# The wave's words: "open-to-paint measured on John's actual machine on a
# real campaign with a dated decision-log entry". This test runs on the
# machine the gate runs on (named in the entry via platform.node()), opens
# the Seal in a REAL browser (Chromium via Playwright — the repo's dev-only
# UI-gate dependency), reads the browser's own performance-mark delta
# 'seal-open' -> 'seal-painted' (marked at the Seal click and at the first
# full-frame commit, per the C1 law), asserts it under the 2000ms bound, and
# APPENDS the dated first-open entry to DECISION-LOG.md (idempotent — the
# first open is recorded once).
#
# The campaign is a COPY of the LARGEST real campaign ledger captured by the
# W5 fixture record (tests/fixtures/chamber/real-ledgers — real on-disk
# ledgers, not synthetic shapes), cold-open rebuilt through the REAL W5
# command, then painted through the REAL endpoint + browser wiring.
#
# (chamber-m1 W1) This test used to route-abort the /api/ecgberht/chamber
# hydrate in the page "to isolate the measurement" — and that abort is
# exactly how the mount's post-hydrate slice-delete defect stayed green for
# twelve waves. The abort is GONE (the abort-ban rule,
# chamber_enforcement.scan_chamber_paint_aborts, now fails any chamber paint
# test that aborts a successor-hydrate route): the hydrate runs for real and
# the measurement stands anyway, because the paint marks land on the slice's
# own fetch and the W1 mount never lets the hydrate touch the DOM.
import json
import platform
import shutil
import sys
import time
from pathlib import Path

import pytest

ANCHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANCHOR))

from tests.chamber_harness import TEST_TOKEN, boot_server  # noqa: E402

import chamber_coldopen as co  # noqa: E402

REAL_LEDGERS = Path(__file__).resolve().parent / "fixtures" / "chamber" \
    / "real-ledgers"
FIXTURE_MANIFEST = REAL_LEDGERS / "fixture-manifest.json"
DECISION_LOG = ANCHOR / "DECISION-LOG.md"
ENTRY_MARKER = "W6 first painted open MEASURED"
_DEVTEST = ANCHOR / "_devtest"

PAINT_BUDGET_MS = 2000.0


def _largest_real_campaign() -> dict:
    """The manifest row of the campaign with the largest real ledger (the
    same record W6's >=2x budget rule was derived from)."""
    man = json.loads(FIXTURE_MANIFEST.read_text(encoding="utf-8"))
    return max(man["campaigns"], key=lambda c: c["bytes_full_ledger"])


def _record_first_open(campaign: dict, machine: str, paint_ms: float,
                       face: str) -> bool:
    """Append the dated first-open entry (once). True when written now."""
    existing = DECISION_LOG.read_text(encoding="utf-8") \
        if DECISION_LOG.exists() else ""
    if ENTRY_MARKER in existing:
        return False  # the first open is already on the record
    entry = (
        "\n## %s — %s (steward-chamber build)\n\n"
        "First open of the painted M1 vertical-slice Seal, measured in a "
        "real browser\n(Chromium via Playwright) on machine **%s**: "
        "performance-mark delta\n'seal-open' -> 'seal-painted' = **%.0f ms** "
        "(bound: <%d ms).\nCampaign: **%s** — a copy of the largest real "
        "campaign ledger from the W5\nfixture record (%d events / %.2f MB / "
        "%d run records), cold-open rebuilt, then\npainted from "
        "ledger/run-record/reflection/roadmap projections alone — %s.\n"
        "Zero model calls / zero child processes on the open are CI-asserted "
        "on every\nchamber change (tests/test_chamber_seal_ci_w6.py); this "
        "measured entry is\nrecorded by tests/test_chamber_first_paint_w6.py."
        "\n"
        % (time.strftime("%Y-%m-%d"), ENTRY_MARKER, machine, paint_ms,
           int(PAINT_BUDGET_MS), campaign["slug"], campaign["event_count"],
           campaign["mb_full_ledger"], campaign["run_record_count"], face))
    with DECISION_LOG.open("a", encoding="utf-8") as f:
        f.write(entry)
    return True


def test_measured_first_open_paints_under_2s_and_lands_the_decision_log(
        tmp_path):
    pytest.importorskip("playwright.sync_api")
    from playwright.sync_api import sync_playwright

    campaign = _largest_real_campaign()
    src = REAL_LEDGERS / campaign["slug"]
    assert src.is_dir(), "the W5 real-ledger fixture copy is missing"
    folder = tmp_path / campaign["slug"]
    shutil.copytree(src, folder)
    # The REAL W5 cold-open rebuild — never a hand-forged sidecar. A real
    # ledger that maps to the drawn degraded state is an honest face too;
    # the paint bound holds either way and the entry records which painted.
    co.cold_open_rebuild(folder)

    srv = boot_server(tmp_path, token=TEST_TOKEN, auth_mode="enforce")
    try:
        import rnd_registry
        pid = rnd_registry.add_project(
            "MBA Teaching AI (real-ledger copy)", str(folder),
            scaffold=False)["id"]

        with sync_playwright() as p:
            b = p.chromium.launch()
            ctx = b.new_context()
            ctx.add_init_script(
                "try{localStorage.setItem('anchor_token','%s')}catch(e){}"
                % TEST_TOKEN)
            pg = ctx.new_page()
            # (chamber-m1 W1) The chamber hydrate runs UN-ABORTED — the
            # abort-ban rule forbids silencing a successor-hydrate route in
            # a paint test. The paint marks ride the slice's own seal_open
            # fetch, so the measurement is unaffected; what the un-aborted
            # hydrate now proves is that it no longer deletes the slice.
            # (2026-08-15) ?classic=1 — ECG_SEAL_PAINT_MS is the CLASSIC
            # chamber's mount measure. /project/<id> now serves the chamber
            # page, which is rendered server-side and has no mount to time;
            # its paint budget is asserted in tests/test_chamber_page_w1.py.
            pg.goto("%s/project/%s?classic=1&token=%s#seal"
                    % (srv["base"], pid, TEST_TOKEN),
                    wait_until="domcontentloaded")
            # The #seal deep link clicks the Seal open; the slice paints and
            # the double-rAF commit stamps 'seal-painted'.
            pg.wait_for_function("window.ECG_SEAL_PAINT_MS != null",
                                 timeout=20000)
            paint_ms = pg.evaluate("window.ECG_SEAL_PAINT_MS")
            # (steward-chamber W7) The mount is STYLE-ISOLATED: the slice
            # markup lives inside #ecgSealSlice's shadow root carrying the
            # signed mockup's verbatim CSS (light-DOM fallback when the CSS
            # pin cannot serve) — the probe pierces whichever mounted.
            _in_slice = ("(function(){var s=document.getElementById("
                         "'ecgSealSlice');if(!s)return false;"
                         "var r=s.shadowRoot||s;return !!r.querySelector(%r);"
                         "})()")
            painted_dock = pg.evaluate(_in_slice % ".dock")
            degraded = pg.evaluate(_in_slice % ".degrail")
            try:
                _DEVTEST.mkdir(exist_ok=True)
                pg.screenshot(path=str(_DEVTEST / "w6_seal_first_paint.png"),
                              full_page=True)
            except Exception:
                pass  # the screenshot is a sign-off aid, never the gate
            b.close()

        assert painted_dock, "the painted M1 slice never mounted"
        assert isinstance(paint_ms, (int, float))
        assert paint_ms < PAINT_BUDGET_MS, \
            "measured 'seal-open'->'seal-painted' = %.0fms (bound %dms)" \
            % (paint_ms, int(PAINT_BUDGET_MS))

        face = ("the drawn degraded rail (rebuild affordance surfaced)"
                if degraded else "the healthy rail")
        _record_first_open(campaign, platform.node(), float(paint_ms), face)
        # The dated entry is ON the record (this run's or an earlier one's).
        assert ENTRY_MARKER in DECISION_LOG.read_text(encoding="utf-8")
    finally:
        srv["stop"]()
