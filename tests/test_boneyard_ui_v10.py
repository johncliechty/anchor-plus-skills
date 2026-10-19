"""v10 Wave 7 — Boneyard UI (per-project view).

A per-project Boneyard view (frozen design in ``planning/rnd-v10/MASTER-PLAN.md``,
Pillar 3, locked D4 = per-project) — a searchable list of DISCARDED material (the
three locked sources from Wave 6: ``killed`` sessions w/ material, ``deleted``
v9-deleted sessions, ``grass-deleted`` ideas), each expandable to its summary +
openable doc links.

This wave (UI) builds ON the Wave-6 backend ``boneyard.py`` (record/list/search/
get) — it does NOT change W6 semantics. It adds:

  1. ``GET /api/rnd/boneyard?project_id=<id>&q=<query>`` — read-only, ``?token=``
     gated (mirroring ``/api/rnd/grass``); returns the SAFE projection of entries
     (NO absolute path / worktree / branch) PLUS server-built, traversal-safe
     ``doc_links`` (href via the existing ``/artifact?path=<rel>`` route — robust
     across sources: the produced docs survive on disk by their rel path under
     Option A regardless of source, so ``/artifact`` is always resolvable).
  2. A Boneyard panel in the project window (search box + newest-first entry list;
     each entry expands to summary + doc links). Honest empty state when nothing
     was discarded.

Tests:
  * DOM positive + negative against ``render_project_window_html`` /
    ``_render_boneyard_panel``.
  * Endpoint: all entries (SAFE — no abs path / worktree / branch), ``q`` filters,
    ``?token=`` gate behavior consistent with the other read endpoints.
  * Playwright (DEV-ONLY, free port != 8777, hardened fixture): open the Boneyard,
    assert entries render, type a DISCRIMINATING search term (a token unique to the
    matching entry), assert the matching entry stays AND the non-matching one
    disappears, expand an entry, assert a doc link with the correct ``/artifact``
    href is present, no console error. Screenshot → ``_devtest/wave7_boneyard.png``.

Hermetic: ``ANCHOR_PTY_BACKEND=stub`` + a temp git repo + tmp data dir + tmp
worktree base. NEVER binds ``:8777``; NEVER a worktree off the real
``C:\\dev\\Anchor`` repo; no network.
"""
import importlib
import json
import re
import subprocess
import threading
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser
from pathlib import Path

import pytest

_DEVTEST = Path(__file__).resolve().parent.parent / "_devtest"


def _git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True)


def _have_git():
    try:
        return subprocess.run(["git", "--version"],
                              capture_output=True).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


pytestmark = pytest.mark.skipif(not _have_git(), reason="git not on PATH")


# ── env / fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def env(tmp_path, monkeypatch):
    """Tmp data dir + worktree base + stub PTY + a temp git repo + a registered
    project. The full stack is reloaded against the isolated env."""
    data = tmp_path / "data"
    data.mkdir()
    wbase = tmp_path / "wt-base"
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data))
    monkeypatch.setenv("ANCHOR_WORKTREE_BASE", str(wbase))
    monkeypatch.setenv("ANCHOR_PTY_BACKEND", "stub")
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)

    for mod in ("paths", "job_runner", "pty_manager", "rnd_registry",
                "effort_history", "sessions", "anchor_marker",
                "session_registry", "worktrees", "lanes", "summarizer",
                "report_viewer", "handoff", "boneyard", "terminal_session"):
        importlib.reload(importlib.import_module(mod))
    import paths
    paths.ensure_data_dirs()
    import anchor_gui
    gui = importlib.reload(anchor_gui)

    import boneyard
    import rnd_registry

    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("hello\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial")

    proj = rnd_registry.add_project("Temp", str(repo), scaffold=False)
    pid = proj["id"]

    bundle = {
        "gui": gui, "bone": boneyard, "rnd": rnd_registry,
        "repo": repo, "pid": pid, "data": data,
    }
    yield bundle
    try:
        import pty_manager
        pty_manager._reset_live_table_for_tests()
    except Exception:
        pass


def _seed_three_entries(bundle):
    """Seed one entry per locked source. Each ``killed``/``deleted`` references a
    REAL doc on disk (so the /artifact route resolves). Returns the doc rels."""
    bone, repo, pid = bundle["bone"], bundle["repo"], bundle["pid"]
    # killed — w/ a produced research report doc (unique term 'thermocline').
    rel_killed = "research/run-1/REPORT.md"
    p = repo / rel_killed
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# thermocline cooling report\n", encoding="utf-8")
    bone.record_entry(str(repo), pid, {
        "source": bone.SOURCE_KILLED,
        "session_id": "sid-killed-1",
        "lane": "research",
        "title": "research — thermocline sizing",
        "summary_excerpt": "Explored thermocline stratification for decay heat.",
        "doc_rels": [rel_killed],
        "when": 3000.0,
    })
    # deleted — a v9-deleted plan session; unique term 'controlrod'.
    rel_deleted = "planning/v1/MASTER-PLAN.md"
    p2 = repo / rel_deleted
    p2.parent.mkdir(parents=True, exist_ok=True)
    p2.write_text("# controlrod drive plan\n", encoding="utf-8")
    bone.record_entry(str(repo), pid, {
        "source": bone.SOURCE_DELETED,
        "session_id": "sid-deleted-1",
        "lane": "plan",
        "title": "plan — controlrod drive concept",
        "summary_excerpt": "A deleted planning session; docs kept on disk.",
        "doc_rels": [rel_deleted],
        "when": 2000.0,
    })
    # grass-deleted — a deleted idea; unique term 'moltensalt'.
    bone.record_entry(str(repo), pid, {
        "source": bone.SOURCE_GRASS_DELETED,
        "idea_id": "grass-abc",
        "lane": "grass",
        "title": "moltensalt buffer tank",
        "idea_text": "A natural-circulation moltensalt buffer to flatten peaks.",
        "doc_rels": [],
        "when": 1000.0,
    })
    return {"killed": rel_killed, "deleted": rel_deleted}


# ════════════════════════════════════════════════════════════════════════════
# DOM positive + negative
# ════════════════════════════════════════════════════════════════════════════

class _Collector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.els = []

    def handle_starttag(self, tag, attrs):
        self.els.append((tag, dict(attrs)))


def _parse(html):
    c = _Collector()
    c.feed(html)
    return c.els


def test_boneyard_button_and_panel_render_positive(env):
    """POSITIVE: with entries seeded, the project window renders the Boneyard
    open button + the panel template (search box + entry-list container) + a row
    per seeded source (the three source badges + a doc link)."""
    gui, pid = env["gui"], env["pid"]
    _seed_three_entries(env)
    html = gui.render_project_window_html(pid)

    # The header "Boneyard" button is wired to openBoneyard().
    assert 'id="openBoneyardBtn"' in html or "id='openBoneyardBtn'" in html
    assert "openBoneyard()" in html

    # The panel template + search box + list container render.
    assert "id='boneyardTpl'" in html or 'id="boneyardTpl"' in html
    assert "id='boneyardSearch'" in html or 'id="boneyardSearch"' in html
    assert "id='boneyardList'" in html or 'id="boneyardList"' in html

    els = _parse(html)
    # One .byentry per seeded entry, carrying its source on data-source.
    sources = sorted(d.get("data-source") for t, d in els
                     if "byentry" in (d.get("class") or "").split())
    assert sources == ["deleted", "grass-deleted", "killed"], sources

    # The killed/deleted docs route through the SAFE /artifact path.
    doc_hrefs = [d.get("href") for t, d in els
                 if "bydoc" in (d.get("class") or "").split()]
    assert any("/artifact/" in (h or "") and "research%2Frun-1%2FREPORT.md" in (h or "")
               for h in doc_hrefs), doc_hrefs
    # NO /report doc links (we route everything through /artifact — D9/Option A).
    assert not any("/report/" in (h or "") for h in doc_hrefs)

    # The empty-state ROW marker is ABSENT in the rendered list when there ARE
    # entries (the JS source carries the string for the live-search empty case,
    # so we assert on the rendered .byempty element, not raw substring).
    assert not [d for t, d in els
                if "byempty" in (d.get("class") or "").split()], \
        "a populated boneyard must not render the empty-state row"


def test_boneyard_empty_state_negative(env):
    """NEGATIVE: a project with NO discarded material shows the honest empty state
    and renders NO fabricated entries."""
    gui, pid = env["gui"], env["pid"]
    html = gui.render_project_window_html(pid)
    # Button + template still render...
    assert "openBoneyard()" in html
    assert "id='boneyardTpl'" in html or 'id="boneyardTpl"' in html
    # ...but a rendered empty-state row is present and there are NO entry rows.
    els = _parse(html)
    assert [d for t, d in els
            if "byempty" in (d.get("class") or "").split()], \
        "empty boneyard must render the honest empty-state row"
    assert not [d for t, d in els
                if "byentry" in (d.get("class") or "").split()], \
        "empty boneyard must render no fabricated entries"


def test_boneyard_js_helpers_wired(env):
    """The JS defines openBoneyard / searchBoneyard / toggleBoneyardEntry, POSTs
    nothing (read-only GET only), and the live search calls the GET endpoint with
    ``q`` (so it exercises ``boneyard.search``)."""
    import anchor_gui
    js = anchor_gui._PROJECT_WINDOW_JS
    assert "function openBoneyard(" in js
    assert "function searchBoneyard(" in js
    assert "function toggleBoneyardEntry(" in js
    m = re.search(r"async function _doBoneyardSearch\(([\s\S]*?)\n\}", js)
    assert m, "_doBoneyardSearch not found"
    body = m.group(1)
    assert "/api/rnd/boneyard" in body
    assert "&q=" in body, "live search must pass the q param (exercise search)"
    # READ-ONLY: the boneyard JS never POSTs / mutates.
    assert "_postJson" not in body


# ════════════════════════════════════════════════════════════════════════════
# Endpoint: SAFE projection, q filter, token gate
# ════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def server(env):
    gui = env["gui"]
    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield env, f"http://127.0.0.1:{port}", port
    finally:
        # Hardened teardown (the v11 flake fix). The server runs daemon request
        # threads, so server_close() does NOT block on an in-flight streaming
        # response (a boneyard fetch / SSE pump) still writing onto its wfile. If
        # we close the socket mid-flight that pump raises late on a closed file —
        # benign noise the conftest excepthook swallows, but under full-suite load
        # it can still flap. So: stop accepting (shutdown), give any in-flight
        # request thread a beat to drain, THEN close the socket — and only treat a
        # still-alive serve_forever thread (never a request thread) as the join
        # target.
        try:
            srv.shutdown()       # stop the serve_forever accept loop
        except Exception:
            pass
        time.sleep(0.15)         # let in-flight request threads finish their write
        try:
            srv.server_close()
        except Exception:
            pass
        t.join(timeout=5)


def _get_json(url):
    with urllib.request.urlopen(url, timeout=5) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8"))


def test_endpoint_lists_all_entries_safe(server):
    """GET /api/rnd/boneyard?project_id=&q= → ALL entries, newest-first, SAFE
    (no absolute path / worktree / branch anywhere in the JSON)."""
    env, base, _ = server
    _seed_three_entries(env)
    pid = env["pid"]
    status, data = _get_json(
        base + "/api/rnd/boneyard?project_id=" + pid + "&q=")
    assert status == 200 and data["ok"] is True
    entries = data["entries"]
    assert len(entries) == 3
    # Recording-order, NEWEST-FIRST (the index inserts each new entry at index 0).
    # Seeded order: killed, deleted, grass-deleted → so grass-deleted is first.
    assert [e["source"] for e in entries] == [
        "grass-deleted", "deleted", "killed"]
    # SAFE: no absolute path / worktree / branch anywhere.
    blob = json.dumps(data)
    assert "worktree" not in blob
    assert "branch" not in blob
    assert str(env["repo"]) not in blob, "absolute project path leaked"
    assert "C:\\\\" not in blob and ":/" not in blob.replace("http://", "")
    for e in entries:
        assert "worktree_path" not in e and "branch" not in e
        for link in e.get("doc_links", []):
            assert link["href"].startswith("/artifact/"), link
            assert ".." not in link["href"]


def test_endpoint_q_filters_to_matching(server):
    """?q=<term> returns ONLY matching entries (exercises boneyard.search)."""
    env, base, _ = server
    _seed_three_entries(env)
    pid = env["pid"]
    # 'moltensalt' is unique to the grass-deleted idea text.
    status, data = _get_json(
        base + "/api/rnd/boneyard?project_id=" + pid + "&q=moltensalt")
    assert status == 200 and data["ok"] is True
    matched = data["entries"]
    assert len(matched) == 1
    assert matched[0]["source"] == "grass-deleted"
    assert "moltensalt" in matched[0]["idea_text"].lower()

    # A term unique to the killed entry's doc filename path.
    status, data = _get_json(
        base + "/api/rnd/boneyard?project_id=" + pid + "&q=thermocline")
    assert len(data["entries"]) == 1
    assert data["entries"][0]["source"] == "killed"

    # A term matching nothing → empty (honest, never fabricated).
    status, data = _get_json(
        base + "/api/rnd/boneyard?project_id=" + pid + "&q=zzzznotathing")
    assert data["entries"] == []


def test_endpoint_unknown_project_404(server):
    env, base, _ = server
    try:
        status, data = _get_json(base + "/api/rnd/boneyard?project_id=nope")
    except urllib.error.HTTPError as e:
        status = e.code
    assert status == 404


def test_endpoint_token_gate(env, monkeypatch):
    """When a token IS set, the boneyard GET requires a matching ?token= — exactly
    like /api/rnd/grass (the read-endpoint pattern this mirrors)."""
    monkeypatch.setenv("ANCHOR_TOKEN", "s3cret")
    import importlib
    import paths
    importlib.reload(paths)
    gui = importlib.reload(env["gui"])
    _seed_three_entries(env)
    pid = env["pid"]

    srv = gui.make_server("127.0.0.1", 0)
    port = srv.server_address[1]
    assert port != 8777
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        base = f"http://127.0.0.1:{port}"
        # No token → 401.
        try:
            status, _ = _get_json(base + "/api/rnd/boneyard?project_id=" + pid)
        except urllib.error.HTTPError as e:
            status = e.code
        assert status == 401
        # Correct token → 200 and the entries.
        status, data = _get_json(
            base + "/api/rnd/boneyard?project_id=" + pid + "&token=s3cret")
        assert status == 200 and data["ok"] is True
        assert len(data["entries"]) == 3
    finally:
        try:
            srv.shutdown()
        except Exception:
            pass
        try:
            srv.server_close()
        except Exception:
            pass
        t.join(timeout=5)
        monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
        importlib.reload(paths)


# ════════════════════════════════════════════════════════════════════════════
# Playwright (DEV-ONLY): open, search-filter (discriminating), expand → doc link
# ════════════════════════════════════════════════════════════════════════════

def test_boneyard_in_browser(server):
    """Open the Boneyard, assert all three entries render, type a DISCRIMINATING
    search term ('moltensalt' — unique to the grass-deleted entry) and assert the
    matching entry STAYS while a non-matching one (the 'thermocline' killed entry)
    DISAPPEARS, expand an entry and assert its /artifact doc link is present, no
    console error. Screenshot → _devtest/wave7_boneyard.png."""
    pytest.importorskip("playwright.sync_api")
    env, base, _ = server
    rels = _seed_three_entries(env)
    pid = env["pid"]

    from playwright.sync_api import sync_playwright
    _DEVTEST.mkdir(exist_ok=True)
    shot = _DEVTEST / "wave7_boneyard.png"

    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed

        # Open the Boneyard panel.
        pg.click("#openBoneyardBtn")
        pg.wait_for_selector("#boneyardPanel #boneyardList", timeout=8000)

        # All three entries render (a token that appears ONLY when an entry
        # rendered: the unique idea/title tokens).
        pg.wait_for_function(
            "document.querySelectorAll('#boneyardPanel .byentry').length === 3",
            timeout=8000)
        body_txt = pg.eval_on_selector("#boneyardPanel", "e => e.innerText")
        assert "moltensalt" in body_txt.lower()
        assert "thermocline" in body_txt.lower()
        assert "controlrod" in body_txt.lower()

        # DISCRIMINATING live search: 'moltensalt' is unique to the grass-deleted
        # entry. After search → exactly ONE entry, the matching one stays AND the
        # non-matching 'thermocline' (killed) entry is GONE from the rendered list.
        pg.fill("#boneyardPanel #boneyardSearch", "moltensalt")
        pg.wait_for_function(
            "document.querySelectorAll('#boneyardPanel .byentry').length === 1",
            timeout=8000)
        filtered = pg.eval_on_selector("#boneyardPanel #boneyardList",
                                       "e => e.innerText").lower()
        assert "moltensalt" in filtered, "the matching entry must remain"
        assert "thermocline" not in filtered, \
            "a non-matching entry must DISAPPEAR after the search filter"
        kept_source = pg.eval_on_selector(
            "#boneyardPanel .byentry", "e => e.getAttribute('data-source')")
        assert kept_source == "grass-deleted"

        # Clear the search → all three return; expand the killed entry and assert
        # its /artifact doc link (the real research report rel) is present.
        pg.fill("#boneyardPanel #boneyardSearch", "")
        pg.wait_for_function(
            "document.querySelectorAll('#boneyardPanel .byentry').length === 3",
            timeout=8000)
        pg.click('#boneyardPanel .byentry[data-source="killed"] .byhd')
        pg.wait_for_selector(
            '#boneyardPanel .byentry[data-source="killed"].open', timeout=4000)
        href = pg.eval_on_selector(
            '#boneyardPanel .byentry[data-source="killed"] a.bydoc',
            "e => e.getAttribute('href')")
        assert href and href.startswith("/artifact/"), href
        # The href names the REAL research report rel path (url-encoded).
        assert "REPORT.md" in href
        assert rels["killed"].split("/")[-1] in href

        pg.screenshot(path=str(shot), full_page=True)
        assert not errors, f"JS console errors: {errors}"
        b.close()

    assert shot.exists(), "screenshot not written"


# ════════════════════════════════════════════════════════════════════════════
# v10 Wave 7 FIX — security + render parity (the coverage the suite was blind to)
# ════════════════════════════════════════════════════════════════════════════

# An entry whose TITLE breaks out of a double-quoted data-title="..." attribute
# (the stored DOM XSS) and one whose IDEA TEXT carries an <img onerror> payload.
_XSS_ATTR_PAYLOAD = 'x" onmouseover="alert(document.cookie)" z="'
_XSS_TAG_PAYLOAD = '<img src=x onerror=alert(1)>'


def _seed_xss_entries(bundle):
    """Seed two malicious entries: a title that tries to break the data-title
    attribute, and an idea body carrying an <img onerror> tag."""
    bone, repo, pid = bundle["bone"], bundle["repo"], bundle["pid"]
    bone.record_entry(str(repo), pid, {
        "source": bone.SOURCE_GRASS_DELETED,
        "idea_id": "grass-xss-attr",
        "lane": "grass",
        "title": _XSS_ATTR_PAYLOAD,
        "idea_text": "attr-breakout idea uniquetokenAAA",
        "doc_rels": [],
        "when": 5000.0,
    })
    bone.record_entry(str(repo), pid, {
        "source": bone.SOURCE_GRASS_DELETED,
        "idea_id": "grass-xss-tag",
        "lane": "grass",
        "title": "tag injection uniquetokenBBB",
        "idea_text": _XSS_TAG_PAYLOAD,
        "doc_rels": [],
        "when": 4000.0,
    })


class _XSSAudit(HTMLParser):
    """Collect every (tag, attrs) so we can assert NO live event-handler attribute
    (onmouseover/onerror/onclick-from-payload) ever materializes, and capture the
    .byentry data-title for the breakout payload."""
    def __init__(self):
        super().__init__()
        self.els = []

    def handle_starttag(self, tag, attrs):
        self.els.append((tag, dict(attrs)))


def test_boneyard_server_render_escapes_xss(env):
    """SERVER path: the malicious title/idea_text are fully escaped — no live
    onmouseover/onerror attribute exists in the parsed DOM, and the breakout
    double-quote is &quot; inside data-title. (Fails against the pre-fix _esc/
    double-escape only on the client; this guards the server path single-escape +
    quote-safety so both paths are pinned.)"""
    gui, pid = env["gui"], env["pid"]
    _seed_xss_entries(env)
    html = gui.render_project_window_html(pid)

    p = _XSSAudit()
    p.feed(html)
    # No element may carry a live event handler sourced from the PAYLOAD.
    #
    # (2026-07-30) This used to reject `onerror` anywhere in the document, which
    # made it fail on Anchor's OWN first-party icon fallback — every tile icon
    # carries onerror="this.style.display='none'" so a missing brand asset
    # collapses quietly. A blanket ban therefore went permanently red the day
    # the steward/workbench tile icons shipped, and a permanently red XSS test
    # guards nothing. The assertion now allows exactly that one static
    # first-party handler and still fails on ANY other handler value — an
    # injected onerror=alert(1) trips it as before.
    _FIRST_PARTY_HANDLERS = {"this.style.display='none'"}
    for tag, attrs in p.els:
        for k in attrs:
            if k.lower() not in ("onmouseover", "onerror"):
                continue
            val = (attrs.get(k) or "").strip()
            assert val in _FIRST_PARTY_HANDLERS, \
                f"live handler attribute injected: {tag} {k}={val!r}"
    # No injected <img> tag with an onerror — the payload tag is text, not markup.
    assert "<img src=x onerror=" not in html, \
        "the <img onerror> payload must be escaped, not rendered as a tag"
    # The breakout double-quote is escaped inside the data-title attribute.
    assert 'onmouseover="alert' not in html, "attribute breakout in server HTML"
    assert "&quot;" in html, "the double-quote in the title must be &quot;-escaped"


def test_boneyard_client_render_escapes_xss(server):
    """CLIENT path (Playwright): record the breakout-title + <img onerror> entries,
    open the Boneyard, type a char to trigger the live re-render through
    _boneyardEntryHtml(_esc(...)), and assert NO .byentry carries an onmouseover/
    onerror attribute, no extra attribute breakout, no alert dialog, no console
    error. This FAILS against the pre-fix client _esc (which left " unescaped, so
    the title broke out of data-title="...")."""
    pytest.importorskip("playwright.sync_api")
    env, base, _ = server
    _seed_xss_entries(env)
    pid = env["pid"]

    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        pg = b.new_page()
        errors = []
        dialogs = []
        pg.on("console",
              lambda m: errors.append(m.text) if m.type == "error" else None)
        # If the payload executed it would open a dialog — accept+record it (a
        # failure signal), never let it hang the test.
        pg.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
        pg.goto(f"{base}/project/{pid}", wait_until="networkidle")
        from tests.ui_helpers import expand_workbench
        expand_workbench(pg)  # the Workbench tile now opens collapsed

        # v12 Wave 2: wait for the Layout-D board to settle (its async board_html
        # swap reflows the page) before clicking the masthead control, so the
        # actionability "stable" check doesn't race the in-place board render.
        pg.wait_for_selector("#kanbanBoard .sectionlbl", timeout=8000)
        pg.click("#openBoneyardBtn")
        pg.wait_for_selector("#boneyardPanel #boneyardList", timeout=8000)
        # WAIT FOR THE SOURCE OF TRUTH before driving the live search: the initial
        # boneyard load completes asynchronously (GET /api/rnd/boneyard), and the
        # two seeded XSS entries must be present BEFORE we type a search term —
        # otherwise the search fires against a not-yet-populated list and the
        # subsequent "== 2" wait races the initial fetch under full-suite load
        # (the v11 flake). Settle on the populated initial render first.
        pg.wait_for_function(
            "document.querySelectorAll('#boneyardPanel .byentry').length === 2",
            timeout=8000)
        # Trigger the CLIENT re-render (the vulnerable path) via live search.
        pg.fill("#boneyardPanel #boneyardSearch", "uniquetoken")
        pg.wait_for_function(
            "document.querySelectorAll('#boneyardPanel .byentry').length === 2",
            timeout=8000)

        # ── CORE non-vacuous assertion ──────────────────────────────────────
        # Drive the EXACT client builder (`_boneyardEntryHtml`) on the breakout
        # entry and parse its output into a FRESH container the same way the live
        # search does (assignment to .innerHTML). With the pre-fix `_esc` (which
        # left `"` unescaped) the title breaks out of data-title="..." and the
        # browser materialises a real `onmouseover` attribute. The hardened `_esc`
        # (`"`→&quot;) keeps the payload INSIDE the attribute → NO on* attribute.
        # This is the deterministic XSS regression guard.
        attr_names = pg.evaluate(
            """(payload) => {
                 var h = _boneyardEntryHtml({
                   source: 'grass-deleted', entry_id: 'xss-attr',
                   title: payload, idea_text: 'x', when: 5000, doc_links: []
                 });
                 var d = document.createElement('div');
                 d.innerHTML = h;                       // parse like the live search
                 return d.firstChild.getAttributeNames();
               }""",
            _XSS_ATTR_PAYLOAD)
        injected = [n for n in attr_names
                    if n.lower().startswith("on") and n.lower() != "onclick"]
        assert injected == [], \
            f"the breakout title injected handler attribute(s): {injected} " \
            f"(all attrs: {attr_names})"
        # The only on* handler is the legitimate wired onclick.
        assert "onclick" in [n.lower() for n in attr_names]
        # The payload survives as an INERT data-title value (escaped, not broken).
        dt = pg.evaluate(
            """(payload) => {
                 var h = _boneyardEntryHtml({
                   source: 'grass-deleted', entry_id: 'xss-attr',
                   title: payload, idea_text: 'x', when: 5000, doc_links: []
                 });
                 var d = document.createElement('div');
                 d.innerHTML = h;
                 return d.firstChild.getAttribute('data-title');
               }""",
            _XSS_ATTR_PAYLOAD)
        assert dt == _XSS_ATTR_PAYLOAD, \
            f"data-title must hold the literal payload (decoded), got {dt!r}"

        # The <img onerror> idea_text must NEVER materialise as an <img> element
        # in the client-rendered body (it is escaped to text).
        img_count = pg.evaluate(
            """(payload) => {
                 var h = _boneyardEntryHtml({
                   source: 'grass-deleted', entry_id: 'xss-tag',
                   title: 't', idea_text: payload, when: 4000, doc_links: []
                 });
                 var d = document.createElement('div');
                 d.innerHTML = h;
                 return d.querySelectorAll('img').length;
               }""",
            _XSS_TAG_PAYLOAD)
        assert img_count == 0, "the <img onerror> payload must not become an element"

        # ── Belt-and-suspenders: the LIVE rendered .byentry rows carry no on* ──
        # injected handler either (and no payload executed → no dialog).
        live_bad = pg.eval_on_selector_all(
            "#boneyardPanel .byentry",
            "els => els.map(el => el.getAttributeNames()).flat()"
            ".filter(n => /^on/i.test(n) && n.toLowerCase() !== 'onclick')")
        assert live_bad == [], f"live .byentry injected handler(s): {live_bad}"
        live_imgs = pg.eval_on_selector_all(
            "#boneyardPanel #boneyardList img", "els => els.length")
        assert live_imgs == 0, "no <img> payload element in the live list"
        # Give any latent onmouseover a chance to fire. Re-query by index right
        # before each hover and tolerate a stale handle: a debounced live-search
        # re-render can detach the prior .byentry handles (harmless — the payload
        # would still have fired a dialog), so a detachment is not a test failure;
        # the dialogs/console assertions below are the real signal.
        n_entries = pg.eval_on_selector_all(
            "#boneyardPanel .byentry", "els => els.length")
        for i in range(n_entries):
            try:
                rows = pg.query_selector_all("#boneyardPanel .byentry")
                if i < len(rows):
                    rows[i].hover()
            except Exception:
                pass   # element detached by a live re-render — not an XSS signal
        assert dialogs == [], f"a payload executed (dialog): {dialogs}"
        assert not errors, f"JS console errors: {errors}"
        b.close()


def test_boneyard_when_display_parity_server_vs_client(env):
    """DEFECT 2 parity: the server-rendered .bywhen text and the value the client
    render would produce (e.when_display) are IDENTICAL for the same entry — both
    use the server-computed LOCAL-tz string, so the displayed time no longer jumps
    when the user searches. Also asserts it reflects LOCAL tz (matches
    datetime.fromtimestamp)."""
    from datetime import datetime
    gui, pid = env["gui"], env["pid"]
    _seed_three_entries(env)

    # The SAFE projection (what the endpoint serves to the client) carries
    # when_display; the client render uses it verbatim as the .bywhen text.
    raw = gui._boneyard.list_entries(str(env["repo"]), pid)
    views = [gui._boneyard_entry_view(pid, e) for e in raw]
    by_when = {v["when"]: v for v in views}

    # Each entry's server-computed display string == local-tz format of its epoch.
    for v in views:
        expected = datetime.fromtimestamp(
            float(v["when"])).strftime("%Y-%m-%d %H:%M")
        assert v["when_display"] == expected, (v["when"], v["when_display"])

    # The SERVER render emits exactly that string in .bywhen — so server-initial
    # and client-search renders are byte-identical (both read when_display).
    one = by_when[3000.0]
    server_html = gui._render_boneyard_entry_html(one)
    m = re.search(r"<span class='bywhen'>([^<]*)</span>", server_html)
    assert m, "server render must emit a .bywhen span"
    assert m.group(1) == one["when_display"], \
        "server .bywhen must equal the when_display the client also renders"


def test_boneyard_title_single_escape_parity(env):
    """DEFECT 3: a title 'A & B <plan>' is single-escaped (NOT 'A &amp;amp; B ...')
    in the server render, and the SAFE projection carries the RAW title so the
    client _esc() also single-escapes it — parity + correctness."""
    bone, repo, pid = env["bone"], env["repo"], env["pid"]
    bone.record_entry(str(repo), pid, {
        "source": bone.SOURCE_GRASS_DELETED,
        "idea_id": "grass-amp",
        "lane": "grass",
        "title": "A & B <plan>",
        "idea_text": "ampersand idea",
        "doc_rels": [],
        "when": 1500.0,
    })
    view = next(v for v in (env["gui"]._boneyard_entry_view(pid, e)
                            for e in bone.list_entries(str(repo), pid))
                if v["entry_id"] and v["title"] == "A & B <plan>")
    # SAFE projection carries the RAW (unescaped) title — the client _esc escapes
    # it exactly once, so it must not be pre-escaped here.
    assert view["title"] == "A & B <plan>", "projection must carry the RAW title"

    html = env["gui"]._render_boneyard_entry_html(view)
    # Single-escaped: '&amp;' present, the double-escape '&amp;amp;' ABSENT.
    assert "A &amp; B" in html
    assert "&amp;amp;" not in html, "title double-escaped (the DEFECT-3 bug)"
    assert "&lt;plan&gt;" in html
