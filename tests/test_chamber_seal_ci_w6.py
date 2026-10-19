# W6 gate — the painted Seal's CI bundle at the HTTP layer, wired to run on
# every chamber change from here forward (this file lives in the chamber
# new-surface namespace, so the whole-suite gate carries it on every wave).
#
# AUTH-ON: enforced
#
# What is proven here, per the wave contract:
#   * AUTH — GET /api/ecgberht/seal_open is token-gated (401 before
#     substance; painted only with the token) on an auth-ON, enforce-mode
#     server booted through the W3 chamber harness;
#   * ZERO MODEL CALLS — the runtime NETWORK/API TRACE + PROCESS-SPAWN AUDIT
#     (a sys.addaudithook over subprocess/os-spawn/socket.connect events)
#     around the painted open: zero child processes of ANY kind (a fortiori
#     zero model-CLI spawns) and zero sockets to anything but the harness's
#     own loopback address (a model endpoint hit would be a foreign
#     connect). The handler's source is ALSO statically pinned bridge-free;
#   * FIRST-OPEN-AFTER-DEPLOY — with sidecar projections absent (a simulated
#     fresh deploy) the served Seal paints the DRAWN degraded-rail state
#     within the same <2s and zero-model-call bounds, SURFACES the W5
#     cold-open rebuild affordance, and the campaign tree stays
#     byte-identical across repeated opens — an inline rebuild on the open
#     path fails here;
#   * <2s BUDGET over HTTP — a synthetic campaign generated AT the committed
#     >=2x-real fixture sizes (the W5 fixture manifest's w6_budget_rule is
#     the oracle) paints through the endpoint inside the bound, via the
#     structural fixes alone (read_stats prove the snapshot tail-read);
#   * C9 ON THE SERVED MARKUP — the HTML the endpoint actually serves (what
#     the browser injects) diffs green against the SIGNED mockup;
#   * the browser wiring carries the performance-mark law ('seal-open' at
#     the Seal click, 'seal-painted' at first full-frame commit,
#     'seal-open-to-paint' measured onto window.ECG_SEAL_PAINT_MS).
import hashlib
import inspect
import json
import sys
import time
from pathlib import Path

import pytest

ANCHOR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ANCHOR))

from tests.chamber_harness import TEST_TOKEN, boot_server  # noqa: E402

import chamber_coldopen as co  # noqa: E402
import chamber_mockup_diff as cmd  # noqa: E402
import chamber_open as copen  # noqa: E402
import chamber_reconcile as cr  # noqa: E402

FIXTURE_MANIFEST = (Path(__file__).resolve().parent / "fixtures" / "chamber"
                    / "real-ledgers" / "fixture-manifest.json")


# ── the runtime trace: spawn + connect audit (installable once, armable) ─────

_AUDIT = {"armed": False, "spawns": [], "connects": []}
_HOOK = [False]

_SPAWN_EVENTS = ("subprocess.Popen", "os.system", "os.spawn",
                 "os.posix_spawn", "os.exec", "os.startfile")


def _ensure_audit_hook():
    if _HOOK[0]:
        return
    def hook(event, args):  # noqa: ANN001 — CPython audit-hook signature
        if not _AUDIT["armed"]:
            return
        if event in _SPAWN_EVENTS:
            _AUDIT["spawns"].append((event, repr(args)[:200]))
        elif event == "socket.connect":
            try:
                _AUDIT["connects"].append(args[1])
            except Exception:
                _AUDIT["connects"].append(("<unparsed>",))
    sys.addaudithook(hook)  # cannot be removed by design — armed per window
    _HOOK[0] = True


def _armed_window():
    _ensure_audit_hook()
    _AUDIT["spawns"] = []
    _AUDIT["connects"] = []
    _AUDIT["armed"] = True


def _disarm():
    _AUDIT["armed"] = False
    return list(_AUDIT["spawns"]), list(_AUDIT["connects"])


# ── campaign builders (the recovery suite's real-campaign shape) ─────────────

def _at(i):
    return "2026-08-09T%02d:%02d:%02dZ" % (i // 3600, (i // 60) % 60, i % 60)


def _write_roadmap(folder, steps, events, as_of):
    (Path(folder) / "roadmap.json").write_text(json.dumps(
        {"project_id": "proj-w6-ci", "as_of": as_of,
         "roadmap_projection": steps, "roadmap_events": events}),
        encoding="utf-8")


def _write_run_record(folder, sid, *, step_id, outcome, at, skill="gandalf"):
    root = Path(folder) / cr.RUN_RECORDS_REL
    root.mkdir(parents=True, exist_ok=True)
    rec = {"session_id": sid, "commission_id": "c-" + sid, "step_id": step_id,
           "skill": skill, "lane": "research", "outcome": outcome, "at": at,
           "elapsed_s": 12.5, "report": {"say": "did the thing"},
           "reflection": {"say": "did the thing", "at": at}}
    (root / (sid + ".json")).write_text(json.dumps(rec), encoding="utf-8")


def _built_campaign(root, name):
    folder = root / name
    folder.mkdir()
    steps = [{"id": "s1", "name": "Draft memo", "status": "done",
              "skill": "gandalf"},
             {"id": "s2", "name": "Verify memo", "status": None,
              "skill": "researchPrime"}]
    events = [{"kind": "scaffold_proposal", "proposal_id": "prop-1",
               "goal": "A verified memo.", "at": _at(10)},
              {"kind": "step_done", "step_id": "s1", "at": _at(20)}]
    _write_roadmap(folder, steps, events, as_of=_at(20))
    _write_run_record(folder, "sess-done", step_id="s1", outcome="done",
                      at=_at(15))
    _write_run_record(folder, "sess-live", step_id="s2",
                      outcome=cr.OUTCOME_LIVE, at=_at(25))
    co.cold_open_rebuild(folder)
    return folder


def _fresh_campaign(root, name):
    """A real ledger, NO sidecar — the simulated fresh deploy."""
    folder = root / name
    folder.mkdir()
    _write_roadmap(folder,
                   [{"id": "s1", "name": "Draft memo", "status": None,
                     "skill": "gandalf"}],
                   [{"kind": "note", "at": _at(1)}], as_of=_at(1))
    return folder


def _tree_hashes(root):
    out = {}
    for p in sorted(Path(root).rglob("*")):
        if p.is_file():
            out[p.relative_to(root).as_posix()] = hashlib.sha256(
                p.read_bytes()).hexdigest()
    return out


# ── the server fixture: auth-ON + enforce (the W3 posture) ──────────────────

@pytest.fixture(scope="module")
def seal_srv(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("seal-ci")
    srv = boot_server(tmp, token=TEST_TOKEN, auth_mode="enforce")
    import rnd_registry
    built = _built_campaign(tmp, "camp-built")
    fresh = _fresh_campaign(tmp, "camp-fresh")
    pid_built = rnd_registry.add_project("SealBuilt", str(built),
                                         scaffold=False)["id"]
    pid_fresh = rnd_registry.add_project("SealFresh", str(fresh),
                                         scaffold=False)["id"]
    handle = {"srv": srv, "tmp": tmp, "built": built, "fresh": fresh,
              "pid_built": pid_built, "pid_fresh": pid_fresh}
    yield handle
    srv["stop"]()


def _get_seal(srv, pid, token=TEST_TOKEN):
    import http.client
    conn = http.client.HTTPConnection("127.0.0.1", srv["port"], timeout=30)
    try:
        # The token rides BOTH carriages the GET data plane accepts (the
        # X-Anchor-Token header and the _tokenQ()-style query param).
        headers = {"X-Anchor-Token": token} if token else {}
        url = "/api/ecgberht/seal_open?project_id=%s" % pid
        if token:
            url += "&token=%s" % token
        conn.request("GET", url, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        try:
            doc = json.loads(body.decode("utf-8"))
        except ValueError:
            doc = {}
        return resp.status, doc
    finally:
        conn.close()


# ── route + registration + bridge-free source ───────────────────────────────

def test_seal_open_route_declared_and_handler_registered(seal_srv):
    import route_table
    rows = [r for r in route_table.ROUTES
            if r.pattern == "/api/ecgberht/seal_open"]
    assert len(rows) == 1, "exactly one declared seal_open route row"
    row = rows[0]
    assert row.method == "GET"
    assert row.auth == route_table.AUTH_TOKEN
    assert row.migrated and row.handler == "handle_ecgberht_seal_open"
    gui = seal_srv["srv"]["gui"]
    # The stand_up lesson: declared migrated AND registered, or it 404s.
    assert gui._MIGRATED_HANDLERS.get("handle_ecgberht_seal_open") \
        is gui.handle_ecgberht_seal_open


def test_seal_open_handler_source_is_bridge_free(seal_srv):
    """The open path can never spawn: no bridge call, no subprocess, no
    model CLI — pinned in source, enforced at runtime by the trace test."""
    src = inspect.getsource(seal_srv["srv"]["gui"].handle_ecgberht_seal_open)
    for forbidden in ("_ecgberht_bridge", "_ecgberht_hs_bridge",
                      "_ecgberht_steward_cli", "subprocess", "Popen"):
        assert forbidden not in src.replace(
            "never touches the Node bridge", ""), forbidden


# ── auth: 401 before substance ──────────────────────────────────────────────

def test_seal_open_requires_the_token_401_before_substance(seal_srv):
    status, doc = _get_seal(seal_srv["srv"], seal_srv["pid_built"],
                            token=None)
    assert status == 401
    assert "html" not in doc and "view" not in doc
    status, doc = _get_seal(seal_srv["srv"], seal_srv["pid_built"])
    assert status == 200 and doc.get("ok") is True
    assert doc.get("html", "").startswith('<div class="dock">')
    assert doc.get("view", {}).get("schema") == copen.SCHEMA


# ── the zero-model-call trace: no spawn, no foreign connect ─────────────────

def test_painted_seal_zero_spawn_zero_foreign_connect(seal_srv):
    srv = seal_srv["srv"]
    # Warm once unarmed (route dispatch + chamber_open import settle).
    _get_seal(srv, seal_srv["pid_built"])
    _armed_window()
    try:
        s1, d1 = _get_seal(srv, seal_srv["pid_built"])
        s2, d2 = _get_seal(srv, seal_srv["pid_fresh"])
    finally:
        spawns, connects = _disarm()
    assert s1 == 200 and d1.get("ok") and s2 == 200 and d2.get("ok")
    # Process-spawn audit: NO child process of any kind during the open —
    # a model-CLI spawn is a spawn, so this is strictly stronger.
    assert spawns == [], "the painted Seal spawned a child process: %r" % spawns
    # Network/API trace: every socket this process opened during the window
    # went to the harness's own loopback address — zero model endpoints.
    allowed_hosts = {"127.0.0.1", "localhost", "::1"}
    for addr in connects:
        host = addr[0] if isinstance(addr, (tuple, list)) and addr else addr
        assert host in allowed_hosts, \
            "foreign connect during the painted open: %r" % (addr,)
        if isinstance(addr, (tuple, list)) and len(addr) > 1:
            assert addr[1] == srv["port"], \
                "connect to an unexpected port during the open: %r" % (addr,)


# ── first-open-after-deploy: drawn-degraded-until-rebuilt, over HTTP ─────────

def test_first_open_after_deploy_paints_drawn_degraded_over_http(seal_srv):
    srv, folder = seal_srv["srv"], seal_srv["fresh"]
    before = _tree_hashes(folder)
    t0 = time.perf_counter()
    status, doc = _get_seal(srv, seal_srv["pid_fresh"])
    wall_ms = (time.perf_counter() - t0) * 1000.0
    assert status == 200 and doc.get("ok") is True
    deg = doc["view"]["degraded"]
    assert deg["state"] == copen.DEGRADED_RAIL_STATE
    assert deg["amendment_ref"] == copen.DEGRADED_AMENDMENT_REF
    assert copen.REASON_PROJECTIONS_MISSING in deg["reasons"]
    # The explicit W5 cold-open rebuild affordance is SURFACED, never run.
    assert deg["rebuild"]["command"] == copen.REBUILD_COMMAND
    assert 'class="degrail"' in doc["html"]
    assert copen.REBUILD_AFFORDANCE_LABEL in doc["html"]
    assert "data-rebuild-command" in doc["html"]
    # Same bounds as the healthy open: <2s, zero run-record reads.
    assert wall_ms < 2000.0
    assert doc["view"]["read_stats"]["run_record_reads"] == 0
    # An inline rebuild on the open path is a test failure: byte-identical
    # tree, and a SECOND open still paints degraded (nothing was repaired).
    assert _tree_hashes(folder) == before
    status2, doc2 = _get_seal(srv, seal_srv["pid_fresh"])
    assert status2 == 200 and doc2["view"]["degraded"] is not None
    assert _tree_hashes(folder) == before


# ── C9 on the SERVED markup ─────────────────────────────────────────────────

def test_served_html_diffs_green_against_the_signed_mockup(seal_srv):
    spec = cmd.slice_spec()  # hash-verified load — hard-fails on a bad pin
    _, healthy = _get_seal(seal_srv["srv"], seal_srv["pid_built"])
    assert healthy["view"]["degraded"] is None
    assert cmd.verify_slice_render(healthy["html"], spec,
                                   mode="healthy") == []
    _, degraded = _get_seal(seal_srv["srv"], seal_srv["pid_fresh"])
    assert degraded["view"]["degraded"] is not None
    assert cmd.verify_slice_render(degraded["html"], spec,
                                   mode="degraded") == []


# ── the <2s budget at the committed >=2x-real sizes, over HTTP ───────────────

def test_budget_campaign_paints_under_2s_over_http(seal_srv):
    rule = json.loads(FIXTURE_MANIFEST.read_text(
        encoding="utf-8"))["w6_budget_rule"]
    tmp = seal_srv["tmp"]
    folder = tmp / "camp-budget"
    folder.mkdir()
    n_events = max(200, rule["min_event_count"])
    n_records = max(24, rule["min_run_record_count"])
    pad = "x" * 8192
    steps = [{"id": "s%d" % i, "name": "Step %d" % i,
              "status": "done" if i < 8 else None, "skill": "gandalf"}
             for i in range(10)]
    events = [{"kind": "note", "n": i, "note": pad, "at": _at(i)}
              for i in range(n_events)]
    _write_roadmap(folder, steps, events, as_of=_at(n_events - 1))
    for i in range(n_records):
        _write_run_record(folder, "sess-%03d" % i,
                          step_id="s%d" % (8 + (i % 2)), outcome="done",
                          at=_at(i))
    # The committed numbers are the oracle — the campaign genuinely meets
    # every one (events, bytes on disk, run records).
    assert n_events >= rule["min_event_count"]
    assert n_records >= rule["min_run_record_count"]
    assert (folder / "roadmap.json").stat().st_size >= rule["min_bytes"]
    co.cold_open_rebuild(folder)

    import rnd_registry
    pid = rnd_registry.add_project("SealBudget", str(folder),
                                   scaffold=False)["id"]
    t0 = time.perf_counter()
    status, doc = _get_seal(seal_srv["srv"], pid)
    wall_ms = (time.perf_counter() - t0) * 1000.0
    assert status == 200 and doc.get("ok") is True
    assert doc["view"]["degraded"] is None
    assert wall_ms < 2000.0, "months-scale painted open took %.0fms" % wall_ms
    # Structure, not a cache: months of history, ONE scanned ledger line,
    # run-record reads under the 200 backstop.
    rs = doc["view"]["read_stats"]
    assert rs["ledger_events_total"] == n_events
    assert rs["ledger_events_scanned"] == 1
    assert rs["run_record_reads"] <= copen.RUN_RECORD_READ_CAP


# ── the browser wiring carries the mark law ─────────────────────────────────

def test_project_window_wiring_carries_the_performance_marks():
    js = (ANCHOR / "static" / "project-window.js").read_text(
        encoding="utf-8", errors="replace")
    # 'seal-open' fires at the Seal click, before any fetch/layout work.
    open_fn = js[js.index("function openEcgberhtSeal()"):]
    open_fn = open_fn[:open_fn.index("ecgSealMountInline();")]
    assert "performance.mark('seal-open')" in open_fn
    # 'seal-painted' lands on the first full-frame commit after the slice
    # mounts, and the measured delta is exposed for CI/sign-off.
    assert "performance.mark('seal-painted')" in js
    assert "performance.measure('seal-open-to-paint'" in js
    assert "window.ECG_SEAL_PAINT_MS" in js
    # The deterministic-first paint rides the W6 endpoint inside the mount.
    assert "/api/ecgberht/seal_open?project_id=" in js
    mount_fn = js[js.index("function ecgSealMountInline()"):]
    mount_fn = mount_fn[:mount_fn.index("function", 10)]
    assert "_ecgSealPaintSlice(host)" in mount_fn
    css = (ANCHOR / "static" / "project-window.css").read_text(
        encoding="utf-8", errors="replace")
    assert "#ecgSealSlice .degrail" in css  # the slice styles shipped
