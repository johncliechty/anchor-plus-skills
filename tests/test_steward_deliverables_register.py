"""Clickable review links in Deliverables and Next steps (wave 1, 2026-10-07).

John's standard (turns cab78cce / 174395b4, journaled as the default): every
review target in conversation, Next steps and Deliverables is DIRECTLY
clickable — a PDF, HTML or Markdown document, or the live page itself. The
observed break: ``steward_campaign._read_deliverables`` recognized only
``/report/`` and ``/artifact/`` as contained routes, so the supervising
register's ``/foundry?skill=researchprime|gandalf|steward-project|
steward-portfolio`` rows rendered as plain FOR REVIEW text.

Continuation (job 20261007-082041-7e4dbe): the five-file change landed, but
the final reviewers of job 20261007-073444-de5804 retained two defects in
``wave-1-review-1.json`` (rules ``acceptance-unproven``/``click-through-
unproven`` and ``plan-pdf-not-opened``/``pdf-not-clicked``): the browser
proof's Foundry screenshots showed the React shell still on "Loading skill…"
(a nonempty body and a route substring passed as a review page), and the plan
PDF was a planted dummy — the bytes ``%PDF-1.4 fake plan review copy`` —
fetched by request, never clicked. This file carries the CORRECTED acceptance.

Pins:
  (1) ``classify_route`` validates the live Foundry review page grammar
      ``/foundry?skill=<id>`` — and ONLY that grammar: hostile or unsupported
      route cells (second query keys, traversal, schemes, ``/foundry/source``,
      prefix-shaped lookalikes) never classify;
  (2) the REAL supervising-register rows (bare ``/foundry?skill=…`` tokens,
      FOR REVIEW labels, the backticked plan PDF, an ``/artifact`` row) parse
      openable through the one register reader — and the uncorrected
      Refinement-2 ``researchprime/`` folder row stays HONESTLY non-openable
      (that row's fix is the correction artifact, tested below);
  (3) Next steps (the server-side acts the tile paints) carries the classified
      route item;
  (4) the shared renderer stays route-generic and names a Foundry route by its
      skill (source-level, both delivRow and loadDeliv);
  (5) the loaded steward delivery instructions carry the rule: no FOR REVIEW
      claim without an openable same-version target registered and linked;
  (6) the correction artifact for the supervising effort's first Refinement-2
      row is parser-compatible and classifies openable;
  (7) REAL-BROWSER CLICK-THROUGH (the corrected proof): a hermetic server
      (throwaway port, never :8777) serves the actual cockpit; at desktop
      1440x1000 AND touch-phone 390x844 the test CLICKS rendered links in BOTH
      Deliverables and Next steps and must reach the FULLY LOADED intended
      Foundry skill heading with its real Library/map content — never a
      nonempty body, a route substring or a Loading shell — and CLICKS the
      approved existing plan PDF's anchor, verifying the REAL bytes the
      browser received against the identity recorded at acquisition
      (``.foreman-job/wave1-evidence/EVIDENCE.json``, acquired through the
      live service's registered artifact reader). Screenshots and the exact
      tested links land under ``.foreman-job/wave1-proof/``;
  (8) the two review-1 defects are PROVEN REJECTED: a page that remains
      loading (the ``/api/foundry/skill`` answer stalled — the reviewers'
      exact screenshot state) FAILS the loaded-page check, and the dummy PDF
      stand-in (the verbatim prior bytes) FAILS the plan-PDF check.

Live (:8777) verification is deliberately NOT here: the running service needs
activation first (John's no-restart instruction is active); source changes are
reported separately from live results.
"""
import hashlib
import json
import re
import sys
import tempfile
import time
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

# REQUIRED, never importorskip'd (the chamber-page precedent): a missing
# Playwright must fail loudly, or the pixels stop being checked.
from playwright.sync_api import (                             # noqa: E402
    TimeoutError as PlaywrightTimeout,
    sync_playwright,
)

from steward_cockpit import steward_campaign as campaign   # noqa: E402
from steward_cockpit import steward_engine as engine       # noqa: E402
from steward_cockpit import steward_routes as routes       # noqa: E402

PROOF = REPO / ".foreman-job" / "wave1-proof"
EVIDENCE_DIR = REPO / ".foreman-job" / "wave1-evidence"

#: The review-1 stand-in, verbatim (reviewer-1 ``pdf-not-clicked``, reviewer-0
#: ``plan-pdf-not-opened``). It must never again pass as the plan PDF.
DUMMY_PDF = b"%PDF-1.4 fake plan review copy"

FOUNDRY_ROUTES = [
    "/foundry?skill=researchprime",
    "/foundry?skill=gandalf",
    "/foundry?skill=steward-project",
    "/foundry?skill=steward-portfolio",
]

#: route → the FULLY LOADED page's exact skill heading (foundry_page catalog
#: names: DISPLAY_NAMES / the steward persona rows).
INTENDED_HEADINGS = {"researchprime": "researchPrime", "gandalf": "Gandalf"}

HOSTILE_OR_UNSUPPORTED = [
    "/foundry?skill=../../etc",                 # traversal-shaped id
    "/foundry?skill=a/b",                       # path separator in id
    "/foundry?skill=a\\b",                      # backslash in id
    "/foundry?skill=a&redirect=//evil",         # second query key
    "/foundry?evil=researchprime",              # wrong key
    "/foundry?skill=",                          # empty id
    "/foundry",                                 # bare — not a review target
    "/foundry/",
    "/foundry/source?skill=x&path=../../x",     # per-anchor link, never a register target
    "/foundrybogus?skill=x",                    # prefix-shaped lookalike
    "/foundry?skill=a%2F..%2Fb",                # percent escape
    "/foundry?skill=a#frag",                    # fragment
    "/foundry?skill=javascript:alert(1)",       # scheme-shaped id
    "http://evil/foundry?skill=x",              # absolute URL
    "//evil/foundry?skill=x",                   # protocol-relative
    "../foundry?skill=x",                       # relative traversal
]

# The supervising register's rows, shape-faithful (bare route tokens, the
# FOR REVIEW designations, the folder-pointing Refinement-2 row, the plan
# PDF, an /artifact route) — dates as in the real register so the acts
# ordering below mirrors what John's page would compute.
REGISTER = """# Deliverables

| What | Where | Date | Step |
| --- | --- | --- | --- |
| researchPrime Refinement 2 — source bundle verified; activation reported by the other session, live browser verification pending | `researchprime/` (activated by the other session; live browser verification pending) | 2026-10-07 | gwl-walk-researchprime |
| ecgberht Current Foundry working plan - PDF review copy 1, for reading and feedback | `planning/working-plan/PLAN-review-copy-1.pdf` | 2026-10-05 | gwl-page |
| FOR REVIEW — researchPrime Library and maps, Refinement 1 of mockup v7; open resources and compare the process with its sources | /foundry?skill=researchprime | 2026-10-04 | gwl-walk-researchprime |
| FOR REVIEW — Gandalf Library, navigable knowledge map and program/process map — Initial draft | /foundry?skill=gandalf | 2026-10-05 | gwl-walk-gandalf |
| FOR REVIEW — Aladdin-Lamp Library, navigable knowledge map and actual process map — Initial draft | /foundry?skill=steward-project | 2026-10-05 | gwl-walk-steward-lamp |
| FOR REVIEW — Aladdin-Cave of Wonders Library, navigable knowledge map and actual portfolio process map — Initial draft | /foundry?skill=steward-portfolio | 2026-10-05 | gwl-walk-steward-cave |
| Preserved Foundry page mockup v7 — original, unaccepted review foundation | /artifact/30ffba93f3614ce48aeda6252b74cf42?path=planning%2Ffoundry-page-2026-10-02%2Fmockup%2Ffoundry-mockup.html | 2026-10-04 | gwl-page |
"""

ROADMAP = {
    "roadmap_projection": [
        {"id": "gwl-page", "name": "Foundry page", "status": "done"},
        {"id": "gwl-walk-researchprime", "name": "researchPrime walkthrough",
         "status": "active"},
        {"id": "gwl-walk-gandalf", "name": "Gandalf walkthrough",
         "status": "proposed"},
        {"id": "gwl-walk-steward-lamp", "name": "Lamp walkthrough",
         "status": "proposed"},
        {"id": "gwl-walk-steward-cave", "name": "Cave walkthrough",
         "status": "proposed"},
    ]
}

_EVIDENCE_CACHE = {}


def _plan_pdf_manifest():
    """The identity recorded at ACQUISITION time (before any serving)."""
    if "man" not in _EVIDENCE_CACHE:
        _EVIDENCE_CACHE["man"] = json.loads(
            (EVIDENCE_DIR / "EVIDENCE.json").read_text(encoding="utf-8")
        )["plan_pdf"]
    return _EVIDENCE_CACHE["man"]


def _assert_real_plan_pdf(body):
    """THE plan-PDF acceptance: real bytes only — dummy stand-ins rejected.

    Used on the evidence file itself AND on the bytes the browser receives
    from the actual click; identical criteria in both places."""
    man = _plan_pdf_manifest()
    assert isinstance(body, (bytes, bytearray)) and body, "no PDF bytes received"
    body = bytes(body)
    assert body != DUMMY_PDF, "the review-1 dummy PDF stand-in is rejected"
    assert b"fake plan review copy" not in body, "a dummy stand-in is rejected"
    assert body.startswith(b"%PDF-"), "not a PDF document"
    assert b"%%EOF" in body[-2048:], "truncated PDF (no trailer)"
    assert len(body) == man["size"], "size differs from the recorded identity"
    assert hashlib.sha256(body).hexdigest() == man["sha256"], \
        "sha256 differs from the identity recorded at acquisition"


def _real_plan_pdf():
    """The supervising effort's REAL plan PDF (immutable shipped evidence,
    acquired through the live service — never a fabricated fixture)."""
    if "pdf" not in _EVIDENCE_CACHE:
        man = _plan_pdf_manifest()
        body = (EVIDENCE_DIR / man["file"]).read_bytes()
        _assert_real_plan_pdf(body)
        _EVIDENCE_CACHE["pdf"] = body
    return _EVIDENCE_CACHE["pdf"]


def _effort(root):
    """A supervising-shaped effort dir: register + roadmap + the REAL PDF."""
    eff = Path(root) / "effort"
    (eff / "planning" / "working-plan").mkdir(parents=True)
    (eff / "ECGBERHT.md").write_text("# effort face", encoding="utf-8")
    (eff / "DELIVERABLES.md").write_text(REGISTER, encoding="utf-8")
    (eff / "roadmap.json").write_text(json.dumps(ROADMAP), encoding="utf-8")
    (eff / "planning" / "working-plan" / "PLAN-review-copy-1.pdf").write_bytes(
        _real_plan_pdf())
    return eff


# ─── (1) the route grammar ───────────────────────────────────────────────────

def test_foundry_review_routes_classify():
    for r in FOUNDRY_ROUTES:
        assert campaign.classify_route(r) == r, r
    # whitespace-padded cells classify to the stripped route
    assert campaign.classify_route("  /foundry?skill=gandalf  ") == \
        "/foundry?skill=gandalf"


def test_existing_report_and_artifact_grammars_unchanged():
    assert campaign.classify_route("/report/pid-1/research/job-1") == \
        "/report/pid-1/research/job-1"
    art = "/artifact/pid-1?path=gandalf/run-1/report.md"
    assert campaign.classify_route(art) == art


def test_hostile_and_unsupported_routes_never_classify():
    for w in HOSTILE_OR_UNSUPPORTED:
        assert campaign.classify_route(w) is None, w


# ─── (2) the real register rows ──────────────────────────────────────────────

def test_supervising_register_rows_parse_openable():
    td = tempfile.mkdtemp(prefix="steward-register-w1-")
    eff = _effort(td)
    got = campaign.read_deliverables(str(eff))
    assert got["exists"] is True
    by = {it["what"].split(" — ")[0].split(" - ")[0].strip(): it
          for it in got["items"]}
    # every /foundry review row is now an openable ROUTE (the FOR REVIEW fix)
    foundry_rows = [it for it in got["items"]
                    if (it.get("route") or "").startswith("/foundry?skill=")]
    assert sorted(it["route"] for it in foundry_rows) == sorted(FOUNDRY_ROUTES)
    for it in foundry_rows:
        assert it["openable"] is True, it["what"]
        assert it["path"] is None, it["what"]
    # the /artifact row keeps working exactly as before
    art = by["Preserved Foundry page mockup v7"]
    assert art["openable"] is True and art["route"].startswith("/artifact/")
    # the plan PDF opens as a contained file — and it is the REAL document
    pdf = by["ecgberht Current Foundry working plan"]
    assert pdf["openable"] is True
    assert pdf["path"] == "planning/working-plan/PLAN-review-copy-1.pdf"
    _assert_real_plan_pdf(
        (eff / "planning" / "working-plan" / "PLAN-review-copy-1.pdf")
        .read_bytes())
    # the uncorrected Refinement-2 row points at a FOLDER — honestly
    # non-openable (its fix is the correction artifact, tested below)
    r2 = by["researchPrime Refinement 2"]
    assert r2["openable"] is False and r2["route"] is None
    # step ids survive untouched (independent feedback stays attached)
    for it in foundry_rows:
        assert it["step"].startswith("gwl-")


def test_api_dispatch_layer_carries_the_routes():
    """The 2026-08-25 lesson: test the layer the page actually hits."""
    td = tempfile.mkdtemp(prefix="steward-register-w1-api-")
    _effort(td)
    d, code = routes.api_get(td, "deliverables", {"dir": "effort"})
    assert code == 200
    routed = {it["route"] for it in d["items"] if it.get("route")}
    for r in FOUNDRY_ROUTES:
        assert r in routed


# ─── (3) Next steps carries the route item ───────────────────────────────────

def test_next_steps_acts_carry_the_foundry_route():
    td = tempfile.mkdtemp(prefix="steward-register-w1-acts-")
    eff = _effort(td)
    got = campaign.read_deliverables(str(eff))
    opens = [a for a in got["acts"] if a.get("act") == "Open" and a.get("item")]
    assert opens, "the FOR REVIEW rows must surface an Open act"
    act = opens[0]
    # newest FOR REVIEW row (2026-10-05, file order) → the Gandalf page
    assert act["item"]["route"] == "/foundry?skill=gandalf"
    assert act["item"]["openable"] is True
    # and the register rows flagged current include the foundry review rows
    current = [it for it in got["items"] if it.get("is_current")]
    assert any((it.get("route") or "").startswith("/foundry?skill=")
               for it in current)


# ─── (4) the shared renderer stays route-generic ─────────────────────────────

def test_renderers_stay_route_generic_and_name_foundry_routes():
    js = (REPO / "steward_cockpit" / "static" / "shared.js").read_text(
        encoding="utf-8")
    deliv = js.split("function delivRow(it)")[1].split("function actLabel")[0]
    # ONE generic route branch — anchors from whatever the server classified,
    # never a client-side prefix allowlist that would re-break new grammars
    assert "it.route" in deliv
    assert '"/report/' not in deliv and '"/artifact/' not in deliv \
        and '"/foundry' not in deliv
    assert "innerHTML" not in deliv
    # a Foundry route is named by its skill — the live page it opens
    name = js.split("function routeName(r)")[1].split("function delivRow")[0]
    assert "foundry\\?skill=" in name
    # loadDeliv (cockpit.html) keeps its matching generic anchor branch
    ld = (REPO / "steward_cockpit" / "static" / "cockpit.html").read_text(
        encoding="utf-8").split("async function loadDeliv()")[1].split(
        "async function loadFiles()")[0]
    assert "fn.href = it.route" in ld
    assert "innerHTML" not in ld


# ─── (5) the rule rides in the loaded delivery instructions ──────────────────

def test_delivery_instructions_carry_the_review_link_rule():
    rules = engine.CONTRACT          # 2026-10-07 (execution minimum item 4): the register rule is in the base contract
    assert "/foundry?skill=<id>" in rules
    assert "never claim FOR REVIEW" in rules
    assert "openable same-version target registered in" in rules


# ─── (6) the correction artifact for the supervising register ────────────────

def test_correction_artifact_row_parses_openable():
    art = REPO / ".foreman-job" / "DELIVERABLES-rows-correction.md"
    assert art.is_file(), "the steward-applicable correction artifact ships with this wave"
    text = art.read_text(encoding="utf-8")
    # no host-absolute paths ride in the artifact
    assert "C:\\" not in text and "/Users/" not in text
    corrected = [ln for ln in text.splitlines()
                 if ln.startswith("| researchPrime Refinement 2")
                 and "/foundry?skill=researchprime" in ln]
    assert len(corrected) == 1, "exactly one corrected row, paste-ready"
    row = corrected[0]
    cells = [c.strip() for c in row.strip("|").split("|")]
    assert cells[3] == "gwl-walk-researchprime"   # step id intact
    assert "`" not in cells[1], "the corrected Where cell must stay backtick-free"
    td = tempfile.mkdtemp(prefix="steward-register-w1-fix-")
    eff = Path(td) / "effort"
    eff.mkdir()
    (eff / "DELIVERABLES.md").write_text(
        "| What | Where | Date | Step |\n|---|---|---|---|\n" + row + "\n",
        encoding="utf-8")
    it = campaign.read_deliverables(str(eff))["items"][0]
    assert it["route"] == "/foundry?skill=researchprime"
    assert it["openable"] is True


# ─── (7) the real browser: click-through proof, desktop & phone ──────────────

@pytest.fixture(scope="module")
def srv(tmp_path_factory):
    from tests.chamber_harness import TEST_TOKEN, boot_server
    tmp = tmp_path_factory.mktemp("register-w1-browser")
    handle = boot_server(tmp, token=TEST_TOKEN)
    try:
        import rnd_registry
        folder = tmp / "proj"
        folder.mkdir()
        _effort(folder)
        pid = rnd_registry.add_project("Review Links W1", str(folder),
                                       scaffold=False)["id"]
        yield {"base": handle["base"], "pid": pid, "token": TEST_TOKEN}
    finally:
        handle["stop"]()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture(scope="module")
def evidence():
    return {"pdf": _real_plan_pdf(), "manifest": _plan_pdf_manifest()}


def test_evidence_identities_recorded_before_serving():
    """Record the REAL evidence inputs' identities BEFORE any browser serving.

    The plan PDF ships as immutable evidence (acquired through the live
    service's registered artifact reader — provenance in
    ``.foreman-job/wave1-evidence/EVIDENCE.json``) and is verified
    byte-for-byte against that recorded identity. The Foundry Library/map
    content the candidate server reads (the configured content root — a
    read-only, separately owned surface; only Anchor is writable or
    plan-owned in this commission) is identity-recorded HERE, before the
    click-through legs serve it. No fake fixture stands in for either."""
    import foundry_page
    PROOF.mkdir(parents=True, exist_ok=True)
    for stale in PROOF.glob("*"):      # stale proof never vouches for this run
        if stale.is_file():
            stale.unlink()
    man = _plan_pdf_manifest()
    _assert_real_plan_pdf(_real_plan_pdf())
    rows = ["plan PDF `%s` · sha256 `%s` · %d bytes · acquired via the live "
            "service (see wave1-evidence/EVIDENCE.json)"
            % (man["register_row_where"], man["sha256"], man["size"])]
    for skill in ("researchprime", "gandalf"):
        p = foundry_page.content_root() / skill / "maps.json"
        assert p.is_file(), \
            "the real Foundry content must exist for this proof wave: " + skill
        raw = p.read_bytes()
        data = json.loads(raw.decode("utf-8-sig"))
        steps = (data.get("process") or {}).get("steps") or []
        nodes = (data.get("knowledge") or {}).get("nodes") or []
        assert steps and nodes, "real map content, never an empty shell"
        rows.append("%s maps.json · sha256 `%s` · %d bytes · %d process steps "
                    "· %d knowledge nodes"
                    % (skill, hashlib.sha256(raw).hexdigest(), len(raw),
                       len(steps), len(nodes)))
    (PROOF / "EVIDENCE-USED.md").write_text(
        "# Wave 1 — real evidence inputs, identities recorded BEFORE serving\n\n"
        "Candidate server: hermetic (throwaway OS-assigned port, never :8777).\n"
        "The Foundry content root is read ONLY; the plan PDF is the shipped\n"
        "immutable acquisition, never a fabricated fixture.\n\n"
        + "".join("- %s\n" % r for r in rows),
        encoding="utf-8")


def _open_cockpit(ctx, srv):
    pg = ctx.new_page()
    pg.goto("%s/steward/v1?pid=%s&dir=effort&token=%s"
            % (srv["base"], srv["pid"], srv["token"]), wait_until="load")
    pg.wait_for_selector(".blk.deliv", timeout=20000)
    pg.wait_for_selector(".blk.next", timeout=20000)
    # both tiles start folded by design — open them the way John does
    for sel in (".blk.deliv > .who", ".blk.next > .who"):
        who = pg.locator(sel)
        who.scroll_into_view_if_needed()
        who.click()
    pg.wait_for_selector(".blk.deliv a[href^='/foundry?skill=']",
                         timeout=30000)
    pg.wait_for_selector(".blk.next a[href^='/foundry?skill=']",
                         timeout=30000)
    return pg


def _assert_anchors(pg):
    """Both surfaces expose REAL anchors for the classified routes."""
    deliv_foundry = pg.locator(".blk.deliv a[href^='/foundry?skill=']")
    assert deliv_foundry.count() >= 4, \
        "all four /foundry review rows must render as anchors in Deliverables"
    next_foundry = pg.locator(".blk.next a[href^='/foundry?skill=']")
    assert next_foundry.count() >= 1, \
        "Next steps must link the current FOR REVIEW page"
    # the plan PDF's anchor is PRESENT in the delivery surface (its step is
    # done, so it lives under the step group, not the current-work pin)
    pdf = pg.locator(".blk.deliv a[href*='deliverable-file']").first
    pdf.wait_for(state="attached", timeout=20000)
    href = pdf.get_attribute("href")
    assert href and "PLAN-review-copy-1.pdf" in href and "token=" in href
    return href


def _reveal(pg, locator):
    """Unfold the anchor's ancestor disclosure groups (summary clicks — the
    toggles John uses) so the link is really visible, then scroll to it."""
    handle = locator.element_handle(timeout=15000)
    pg.evaluate(
        """(el) => { let d = el.closest('details');
             while (d) {
               if (!d.open) {
                 const s = d.querySelector(':scope > summary');
                 if (s) s.click(); else d.open = true;
               }
               d = d.parentElement ? d.parentElement.closest('details') : null;
             } }""",
        handle)
    locator.scroll_into_view_if_needed()
    locator.wait_for(state="visible", timeout=10000)


def _assert_foundry_loaded(pg, skill_id, timeout_ms=90000):
    """The intended Foundry skill page, FULLY LOADED — a Loading shell FAILS.

    ``researchprime`` serves the ported Refinement-2 display page (the shell
    is server-rendered; the canonical scripts mount the knowledge/Library
    content into ``#panel``). Every other skill serves the folded-in React
    walkthrough, which shows ``role=status`` "Loading skill…" (NO heading)
    until ``/api/foundry/skill`` answers. Both kinds must present the exact
    intended skill heading AND real Library/map content; a page that remains
    loading, refuses, or errors can never pass (review-1
    ``acceptance-unproven`` / ``click-through-unproven``)."""
    pg.wait_for_load_state()
    assert "/foundry?skill=" + skill_id in pg.url, pg.url
    if skill_id == "researchprime":
        # mounted knowledge content: the real node → Library-resource links
        pg.wait_for_selector("#panel [data-resource]", state="attached",
                             timeout=timeout_ms)
        panel = pg.locator("#panel").inner_text()
        assert "Loading the walkthrough" not in panel, "still the Loading shell"
        assert "Walkthrough refused" not in panel
        assert pg.locator("#panel [data-resource]").count() >= 10, \
            "the knowledge map must render its real node links"
        assert "Knowledge map" in panel
        body = pg.locator("body").inner_text()
        # the preserved lifecycle facts ride on the real data, untouched
        assert "accepted: false" in body and "closed: false" in body
    else:
        # the React page has NO heading while "Loading skill…" shows — the
        # heading appearing IS the loaded state; a stuck loader times out here
        pg.wait_for_selector("#skill-main h1", state="attached",
                             timeout=timeout_ms)
        main_text = pg.locator("#skill-main").inner_text()
        assert pg.locator('#skill-main [role="status"]').count() == 0, \
            "no Loading/error status may remain on the loaded page"
        assert "Library and maps awaiting independent human review" in main_text, \
            "real knowledge+process maps must be loaded (not the unfinished notice)"
        m = re.search(r"(\d+) source resources", main_text)
        assert m and int(m.group(1)) >= 1, "the Library must carry real resources"
    h1 = pg.locator("main h1").first.inner_text().strip()
    assert h1 == INTENDED_HEADINGS[skill_id], \
        "intended skill heading %r, got %r" % (INTENDED_HEADINGS[skill_id], h1)
    full = pg.locator("body").inner_text()
    assert not re.search(r"Loading (skill|the walkthrough|source catalog)", full), \
        "a page that remains loading is rejected"


def _click_through(ctx, pg, selector, skill_id, shot):
    """CLICK a rendered register/acts anchor; the popup must fully load."""
    link = pg.locator(selector).first
    _reveal(pg, link)
    clicked = link.get_attribute("href")
    with ctx.expect_page() as pop:
        link.click()
    page2 = pop.value
    _assert_foundry_loaded(page2, skill_id)
    page2.screenshot(path=str(PROOF / shot), full_page=True)
    page2.close()
    return clicked


def _click_pdf_and_capture(ctx, pg, link, timeout_s=45):
    """Really CLICK the plan-PDF anchor; return the bytes the BROWSER got.

    A target=_blank PDF click lands one of two ways depending on the browser
    build: an inline viewer page (application/pdf renders) or a download
    handoff. Both are the browser OPENING the document from the click; both
    yield the exact served bytes (the download file / the click navigation's
    own document response) — never a separate fetch of the href."""
    got = {}

    def _hook_downloads(p):
        # download events are PAGE events; the click opens a popup, so hook
        # the opener and every page the context creates from here on
        p.on("download", lambda d: got.setdefault("download", d))

    def _on_response(r):
        try:
            if "deliverable-file" in r.url and \
                    r.request.resource_type == "document":
                got.setdefault("response", r)
        except Exception:
            pass
    _hook_downloads(pg)
    ctx.on("page", _hook_downloads)
    ctx.on("response", _on_response)
    before = list(ctx.pages)
    link.click()
    body = mode = viewer = None
    deadline = time.time() + timeout_s
    while time.time() < deadline and body is None:
        if "download" in got:
            path = got["download"].path()        # blocks until complete
            body, mode = Path(path).read_bytes(), "download"
            break
        if "response" in got:
            try:
                body, mode = got["response"].body(), "inline-viewer"
                break
            except Exception:                    # intercepted as a download
                got.pop("response", None)
        for p in ctx.pages:
            if p not in before and viewer is None:
                viewer = p
        pg.wait_for_timeout(250)
    assert body is not None, \
        "clicking the plan PDF produced neither a viewer nor a download"
    return body, mode, viewer


def _mask(link, srv):
    return (link or "").replace(srv["token"], "<token>")


_TESTED = []


def _click_leg(srv, browser, *, width, height, mobile, tag):
    """One full viewport leg: cockpit render, BOTH-surface click-throughs,
    the real plan-PDF click, screenshots."""
    kwargs = {"viewport": {"width": width, "height": height},
              "accept_downloads": True}
    if mobile:
        kwargs.update(is_mobile=True, has_touch=True, device_scale_factor=2)
    ctx = browser.new_context(**kwargs)
    ctx.add_init_script(
        "try{localStorage.setItem('anchor_token','%s')}catch(e){}" % srv["token"])
    try:
        pg = _open_cockpit(ctx, srv)
        pdf_href = _assert_anchors(pg)
        pg.screenshot(path=str(PROOF / (tag + "-cockpit.png")), full_page=True)
        # (a) DELIVERABLES click → the researchPrime Refinement-2 display page
        deliv_clicked = _click_through(
            ctx, pg, ".blk.deliv a[href^='/foundry?skill=researchprime']",
            "researchprime", tag + "-foundry-deliverables.png")
        # (b) NEXT STEPS click → the Gandalf React walkthrough
        next_clicked = _click_through(
            ctx, pg, ".blk.next a[href^='/foundry?skill=']",
            "gandalf", tag + "-foundry-next.png")
        assert next_clicked.startswith("/foundry?skill=gandalf"), next_clicked
        # (c) the approved existing plan PDF: CLICK its rendered anchor and
        # verify the REAL bytes the browser received (identity recorded at
        # acquisition) — the dummy stand-in can never pass _assert_real_plan_pdf
        pdf_link = pg.locator(".blk.deliv a[href*='deliverable-file']").first
        _reveal(pg, pdf_link)
        body, mode, viewer = _click_pdf_and_capture(ctx, pg, pdf_link)
        _assert_real_plan_pdf(body)
        if viewer is not None:
            try:
                viewer.screenshot(path=str(PROOF / (tag + "-pdf-open.png")))
            except Exception:
                pass
            try:
                viewer.close()
            except Exception:
                pass
        pg.screenshot(path=str(PROOF / (tag + "-pdf-click.png")))
        # supplementary header check on the SAME anchor URL (never the proof
        # of opening — that is the click above)
        rp = pg.request.get(srv["base"] + pdf_href)
        assert rp.status == 200
        assert "pdf" in (rp.headers.get("content-type") or "").lower()
        _TESTED.extend([
            "%s · Deliverables click-through (fully loaded researchPrime): %s"
            % (tag, _mask(deliv_clicked, srv)),
            "%s · Next steps click-through (fully loaded Gandalf): %s"
            % (tag, _mask(next_clicked, srv)),
            "%s · plan PDF clicked (%s, %d real bytes, sha256-verified): %s"
            % (tag, mode, len(body), _mask(pdf_href, srv)),
        ])
        return pg
    finally:
        ctx.close()


def test_browser_desktop_clicks_through_both_surfaces(srv, browser, evidence):
    PROOF.mkdir(parents=True, exist_ok=True)
    _click_leg(srv, browser, width=1440, height=1000, mobile=False,
               tag="desktop")


def test_browser_desktop_other_review_routes_carry_real_maps(srv, browser):
    """The two non-clicked review routes answer with REAL map data — a 200 of
    an HTML shell is no longer treated as the review page (review-1)."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    try:
        pg = ctx.new_page()
        for route in ("/foundry?skill=steward-project",
                      "/foundry?skill=steward-portfolio"):
            rr = pg.request.get(srv["base"] + route + "&token=" + srv["token"])
            assert rr.status == 200, route
            skill_q = route.split("=", 1)[1]
            rd = pg.request.get(
                srv["base"] + "/api/foundry/skill?skill=" + skill_q)
            assert rd.status == 200, skill_q
            detail = rd.json()
            assert len(detail["knowledgeMap"]["nodes"]) >= 1, skill_q
            assert len(detail["processMap"]["steps"]) >= 1, skill_q
            _TESTED.append("desktop · 200 OK + real map data: " + route)
    finally:
        ctx.close()


def test_browser_phone_clicks_through_both_surfaces(srv, browser, evidence):
    PROOF.mkdir(parents=True, exist_ok=True)
    _click_leg(srv, browser, width=390, height=844, mobile=True, tag="phone")


# ─── (8) the review-1 defects are PROVEN REJECTED ────────────────────────────

def test_check_rejects_a_page_that_remains_loading(srv, browser):
    """The reviewers' exact screenshot state — the React shell stuck on
    'Loading skill…' because /api/foundry/skill never answers — must FAIL
    the loaded-page check, never pass it."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 1000})
    try:
        ctx.route("**/api/foundry/skill*", lambda route: None)   # stall forever
        pg = ctx.new_page()
        pg.goto(srv["base"] + "/foundry?skill=gandalf")
        pg.wait_for_selector('#skill-main [role="status"]', timeout=20000)
        assert "Loading skill" in pg.locator("#skill-main").inner_text()
        with pytest.raises((AssertionError, PlaywrightTimeout)):
            _assert_foundry_loaded(pg, "gandalf", timeout_ms=5000)
    finally:
        ctx.close()


def test_check_rejects_the_dummy_pdf_stand_in():
    """The verbatim review-1 stand-in — and any other wrong PDF — fails."""
    with pytest.raises(AssertionError):
        _assert_real_plan_pdf(DUMMY_PDF)
    with pytest.raises(AssertionError):
        _assert_real_plan_pdf(DUMMY_PDF + b"\n%%EOF")
    with pytest.raises(AssertionError):            # well-formed but not the plan
        _assert_real_plan_pdf(b"%PDF-1.7\nsome other document\n%%EOF")


# ─── the durable proof record ────────────────────────────────────────────────

def _candidate_build():
    """The exact candidate build (HEAD sha), read from git's own files — no
    git commands, no absolute paths shipped."""
    try:
        git = REPO / ".git"
        gitdir = git if git.is_dir() else Path(
            git.read_text(encoding="utf-8").split("gitdir:", 1)[1].strip())
        if not gitdir.is_absolute():
            gitdir = (REPO / gitdir).resolve()
        head = (gitdir / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref:"):
            return head
        ref = head.split(None, 1)[1]
        common = gitdir
        cd = gitdir / "commondir"
        if cd.is_file():
            common = (gitdir / cd.read_text(encoding="utf-8").strip()).resolve()
        reffile = common / ref
        if reffile.is_file():
            return reffile.read_text(encoding="utf-8").strip()
        packed = common / "packed-refs"
        if packed.is_file():
            for line in packed.read_text(encoding="utf-8").splitlines():
                if line.endswith(" " + ref):
                    return line.split(" ", 1)[0]
    except (OSError, IndexError, ValueError):
        pass
    return "unknown"


def test_record_exact_tested_links():
    """The durable proof the wave demands: screenshots, the exact links, the
    evidence identities and the exact candidate build — no worktree-only
    references, no absolute host paths."""
    assert _TESTED, "the browser legs must run before the record is written"
    PROOF.mkdir(parents=True, exist_ok=True)
    shots = sorted(p.name for p in PROOF.glob("*.png"))
    assert {"desktop-cockpit.png", "desktop-foundry-deliverables.png",
            "desktop-foundry-next.png", "desktop-pdf-click.png",
            "phone-cockpit.png", "phone-foundry-deliverables.png",
            "phone-foundry-next.png", "phone-pdf-click.png"} <= set(shots)
    assert (PROOF / "EVIDENCE-USED.md").is_file()
    man = _plan_pdf_manifest()
    (PROOF / "LINKS-TESTED.md").write_text(
        "# Wave 1 — exact links tested (hermetic server, OS-assigned port, "
        "never :8777)\n\n"
        "Candidate build: `%s` (branch worktree of the Anchor repository).\n\n"
        "Origin: a throwaway Anchor server booted by the gate "
        "(`tests/chamber_harness.boot_server`); `<token>` is the page token "
        "the cockpit itself appends (ordinary browser authentication). "
        "Every Foundry click-through below REACHED the fully loaded intended "
        "skill page (exact heading + real Library/map content; a Loading "
        "shell fails the check — proven by the stalled-answer rejection "
        "test). The plan PDF was CLICKED and the browser-received bytes "
        "verified against the identity recorded at acquisition "
        "(sha256 `%s`, %d bytes — see `../wave1-evidence/EVIDENCE.json`); "
        "the review-1 dummy stand-in is proven rejected. "
        "Live-:8777 verification requires activation and is reported "
        "separately per the no-restart instruction.\n\n" % (
            _candidate_build(), man["sha256"], man["size"])
        + "".join("- %s\n" % t for t in _TESTED)
        + "\nScreenshots: " + ", ".join(shots) + "\n",
        encoding="utf-8")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
