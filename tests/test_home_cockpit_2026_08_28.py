"""Home + cockpit pins for the 2026-08-28 screen pass.

Files listing was empty because dir="" went through effort discovery.
Drop-in must report same-bytes. Home tab icon is the Anchor. Grass lives
on the home, not in the cockpit seal. Workbench toggles closed. Gandalf
renders expandable run rows. No 5:1 chip on the home.
"""
import base64
import os
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from steward_cockpit import steward_routes as routes  # noqa: E402

REPO = Path(__file__).resolve().parent.parent


class FilesProjectLevelTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="steward-files-")
        Path(self.tmp, "readme.md").write_text("hello", encoding="utf-8")
        Path(self.tmp, "notes.txt").write_text("n", encoding="utf-8")

    def test_files_lists_project_root_without_a_face(self):
        d, code = routes.api_get(self.tmp, "files", {"dir": "", "sub": "", "q": ""})
        self.assertEqual(code, 200, d)
        names = {e["name"] for e in d["entries"]}
        self.assertIn("readme.md", names)
        self.assertIn("notes.txt", names)

    def test_upload_reports_same_bytes(self):
        payload = base64.b64encode(b"hello").decode("ascii")
        d, code = routes.api_post(self.tmp, "upload", {
            "dir": "", "sub": "", "name": "readme.md",
            "data_b64": payload, "mode": "new",
        })
        self.assertEqual(code, 200)
        self.assertFalse(d["ok"])
        self.assertTrue(d["exists"])
        self.assertTrue(d["same"])
        self.assertTrue(d["version"].startswith("v1-"))

    def test_upload_replace_with_matching_version_overwrites(self):
        payload = base64.b64encode(b"replaced").decode("ascii")
        conflict, code = routes.api_post(self.tmp, "upload", {
            "dir": "", "sub": "", "name": "readme.md",
            "data_b64": payload, "mode": "new",
        })
        self.assertEqual(code, 200)
        d, code = routes.api_post(self.tmp, "upload", {
            "dir": "", "sub": "", "name": "readme.md",
            "data_b64": payload, "mode": "replace",
            "if_match": conflict["version"],
        })
        self.assertEqual(code, 200)
        self.assertTrue(d["ok"])
        self.assertEqual(Path(self.tmp, "readme.md").read_text(encoding="utf-8"),
                         "replaced")

    def test_upload_rejects_unknown_mode_without_overwriting(self):
        for mode in ("surprise", ["replace"]):
            with self.subTest(mode=mode):
                d, code = routes.api_post(self.tmp, "upload", {
                    "dir": "", "sub": "", "name": "readme.md",
                    "data_b64": base64.b64encode(b"bad").decode("ascii"),
                    "mode": mode,
                })
                self.assertEqual(code, 400)
                self.assertFalse(d["ok"])
        self.assertEqual(Path(self.tmp, "readme.md").read_bytes(), b"hello")

    def test_upload_replace_requires_conflict_version(self):
        d, code = routes.api_post(self.tmp, "upload", {
            "dir": "", "sub": "", "name": "readme.md",
            "data_b64": base64.b64encode(b"bad").decode("ascii"),
            "mode": "replace",
        })
        self.assertEqual(code, 428)
        self.assertFalse(d["ok"])
        self.assertEqual(Path(self.tmp, "readme.md").read_bytes(), b"hello")

    def test_upload_replace_rejects_stale_conflict_version(self):
        payload = base64.b64encode(b"incoming").decode("ascii")
        conflict, code = routes.api_post(self.tmp, "upload", {
            "dir": "", "sub": "", "name": "readme.md",
            "data_b64": payload, "mode": "new",
        })
        self.assertEqual(code, 200)
        Path(self.tmp, "readme.md").write_bytes(b"changed after review")

        d, code = routes.api_post(self.tmp, "upload", {
            "dir": "", "sub": "", "name": "readme.md",
            "data_b64": payload, "mode": "replace",
            "if_match": conflict["version"],
        })
        self.assertEqual(code, 412)
        self.assertFalse(d["ok"])
        self.assertTrue(d["exists"])
        self.assertNotEqual(d["version"], conflict["version"])
        self.assertEqual(Path(self.tmp, "readme.md").read_bytes(),
                         b"changed after review")

    def test_upload_size_mismatch_does_not_read_existing_content(self):
        payload = base64.b64encode(b"a different length").decode("ascii")
        with mock.patch.object(Path, "read_bytes",
                               side_effect=AssertionError("content read")):
            d, code = routes.api_post(self.tmp, "upload", {
                "dir": "", "sub": "", "name": "readme.md",
                "data_b64": payload, "mode": "new",
            })
        self.assertEqual(code, 200)
        self.assertFalse(d["same"])
        self.assertEqual(d["size"], 5)

    def test_concurrent_new_uploads_never_overwrite(self):
        barrier = threading.Barrier(3)

        def send(raw):
            barrier.wait()
            return routes.api_post(self.tmp, "upload", {
                "dir": "", "sub": "", "name": "race.txt",
                "data_b64": base64.b64encode(raw).decode("ascii"),
                "mode": "new",
            })

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(send, raw) for raw in (b"first", b"second")]
            barrier.wait()
            results = [future.result(timeout=5) for future in futures]

        self.assertEqual(sum(bool(body["ok"]) for body, _code in results), 1)
        self.assertEqual(sum(bool(body.get("exists"))
                             for body, _code in results), 1)
        self.assertIn(Path(self.tmp, "race.txt").read_bytes(),
                      (b"first", b"second"))

    def test_concurrent_keepboth_uploads_claim_distinct_names(self):
        barrier = threading.Barrier(3)

        def send(raw):
            barrier.wait()
            return routes.api_post(self.tmp, "upload", {
                "dir": "", "sub": "", "name": "notes.txt",
                "data_b64": base64.b64encode(raw).decode("ascii"),
                "mode": "keepboth",
            })

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(send, raw) for raw in (b"first", b"second")]
            barrier.wait()
            results = [future.result(timeout=5) for future in futures]

        self.assertTrue(all(body["ok"] and code == 200
                            for body, code in results))
        names = {body["name"] for body, _code in results}
        self.assertEqual(names, {"notes (1).txt", "notes (2).txt"})
        self.assertEqual(Path(self.tmp, "notes.txt").read_bytes(), b"n")
        self.assertEqual({Path(self.tmp, name).read_bytes() for name in names},
                         {b"first", b"second"})

    def test_concurrent_replace_allows_only_one_matching_version(self):
        probe = base64.b64encode(b"probe").decode("ascii")
        conflict, code = routes.api_post(self.tmp, "upload", {
            "dir": "", "sub": "", "name": "readme.md",
            "data_b64": probe, "mode": "new",
        })
        self.assertEqual(code, 200)
        barrier = threading.Barrier(3)

        def send(raw):
            barrier.wait()
            return routes.api_post(self.tmp, "upload", {
                "dir": "", "sub": "", "name": "readme.md",
                "data_b64": base64.b64encode(raw).decode("ascii"),
                "mode": "replace", "if_match": conflict["version"],
            })

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(send, raw) for raw in (b"first", b"second")]
            barrier.wait()
            results = [future.result(timeout=5) for future in futures]

        self.assertEqual(sum(bool(body["ok"]) for body, _code in results), 1)
        self.assertEqual(sorted(code for _body, code in results), [200, 412])
        self.assertIn(Path(self.tmp, "readme.md").read_bytes(),
                      (b"first", b"second"))

    def test_failed_atomic_replace_keeps_original_and_cleans_stage(self):
        payload = base64.b64encode(b"replacement").decode("ascii")
        conflict, code = routes.api_post(self.tmp, "upload", {
            "dir": "", "sub": "", "name": "readme.md",
            "data_b64": payload, "mode": "new",
        })
        self.assertEqual(code, 200)
        with mock.patch.object(routes.os, "replace", side_effect=OSError("boom")):
            d, code = routes.api_post(self.tmp, "upload", {
                "dir": "", "sub": "", "name": "readme.md",
                "data_b64": payload, "mode": "replace",
                "if_match": conflict["version"],
            })
        self.assertEqual(code, 500)
        self.assertFalse(d["ok"])
        self.assertEqual(Path(self.tmp, "readme.md").read_bytes(), b"hello")
        self.assertEqual(list(Path(self.tmp).glob(".anchor-upload-*")), [])

    def test_failed_exclusive_publish_leaves_no_file_or_stage(self):
        with mock.patch.object(routes.os, "link", side_effect=OSError("boom")):
            d, code = routes.api_post(self.tmp, "upload", {
                "dir": "", "sub": "", "name": "new.txt",
                "data_b64": base64.b64encode(b"new").decode("ascii"),
                "mode": "new",
            })
        self.assertEqual(code, 500)
        self.assertFalse(d["ok"])
        self.assertFalse(Path(self.tmp, "new.txt").exists())
        self.assertEqual(list(Path(self.tmp).glob(".anchor-upload-*")), [])


class CockpitStaticTest(unittest.TestCase):
    def setUp(self):
        self.html = (REPO / "steward_cockpit" / "static" / "cockpit.html").read_text(
            encoding="utf-8")
        self.shim = routes._CLIENT_SHIM

    def test_workbench_toggles_closed(self):
        self.assertIn("function toggleDrawer()", self.html)
        self.assertIn("toggleDrawer(); return;", self.html)
        self.assertNotIn("openDrawer(); return;", self.html)

    def test_conflict_dialog_has_replace_skip_keep(self):
        for needle in ("data-conflict-replace", "data-conflict-skip",
                       "data-conflict-keep", "Same bytes"):
            self.assertIn(needle, self.html)

    def test_upload_client_carries_review_version_and_serializes_dialogs(self):
        for needle in (
                "if_match: ifMatch || undefined",
                'choice === "replace" ? result.version : undefined',
                "file.size > 30000000",
                "let uploadQueue = Promise.resolve()",
                "uploadQueue = uploadQueue.then(() => uploadOne(file))",
                "failed (connection or read error)"):
            self.assertIn(needle, self.html)

    def test_server_rejects_oversized_upload_before_reading_body(self):
        source = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
        guard = source.index('urlparse(self.path).path == "/api/steward/upload"')
        body_read = source.index("self.rfile.read(content_len)", guard)
        self.assertLess(guard, body_read)
        self.assertIn("content_len > 41_000_000", source[guard:body_read])

    def test_github_in_header(self):
        self.assertIn("data-github", self.html)
        self.assertIn("loadGithub", self.html)
        self.assertIn("/api/rnd/remote_status", self.html)

    def test_shim_does_not_eat_rnd_routes(self):
        self.assertIn("/api/rnd/", self.shim)

    def test_grass_left_the_seal(self):
        self.assertNotIn("data-shelf-grass", self.html)
        self.assertNotIn("data-grasshead", self.html)

    def test_gandalf_uses_expandable_runs(self):
        self.assertIn("data-gruns", self.html)
        self.assertIn("renderGandalfRun", self.html)

    def test_favicon_is_anchor(self):
        self.assertIn('href="/anchor.ico"', self.html)

    def test_tidy_idy_in_workbench_corner(self):
        self.assertIn("data-tidy", self.html)
        self.assertIn("tidy-corner", self.html)
        self.assertIn("tidy-idy-icon.jpg", self.html)
        self.assertIn("tidy-idy-run.js", self.html)
        self.assertIn("tidyIdyRun", self.html)
        js = (REPO / "steward_cockpit" / "static" / "tidy-idy-run.js").read_text(
            encoding="utf-8")
        self.assertIn("/api/rnd/tidy_idy_run", js)
        self.assertIn("/api/rnd/tidy_idy_status", js)

    def test_new_cockpit_assets_ship_in_the_deny_by_default_bundle(self):
        manifest = (REPO / "dist_manifest.txt").read_text(encoding="utf-8")
        for rel in (
                "steward_cockpit/static/plate.js",
                "steward_cockpit/static/tidy-idy-run.js",
                "vendor/brand/tidy-idy-icon.jpg"):
            self.assertIn(rel, manifest)
            self.assertTrue((REPO / rel).is_file(), rel)

    def test_high_seat_project_links_use_cookie_auth(self):
        js = (REPO / "static" / "high-seat.js").read_text(encoding="utf-8")
        self.assertIn("function _ecgHsProjectUrl", js)
        self.assertIn("var url = _ecgHsProjectUrl(pid, hash);", js)
        self.assertIn("tile.href = _ecgHsProjectUrl(t.anchor_project_id, '');", js)
        helper = js[js.index("function _ecgHsProjectUrl"):
                    js.index("function _ecgHsOpenProject")]
        self.assertNotIn("_ecgHsTok", helper)


class HomeAndPrototypeTest(unittest.TestCase):
    def test_prototype_jumps_not_peek(self):
        html = (REPO / "_mockups" / "dashboard-v2" / "index.html").read_text(
            encoding="utf-8")
        self.assertIn("function jumpTo(", html)
        self.assertNotIn("function openPeek(", html)
        self.assertIn('id="tile-grass"', html)
        self.assertIn("Save for later", html)
        self.assertIn('href="../../anchor.ico"', html)

    def test_home_html_contract(self):
        import importlib
        import os as _os
        prev = _os.environ.get("ANCHOR_DATA_DIR")
        td = tempfile.mkdtemp(prefix="anchor-home-")
        _os.environ["ANCHOR_DATA_DIR"] = td
        try:
            import paths
            importlib.reload(paths)
            paths.ensure_data_dirs()
            import rnd_registry
            importlib.reload(rnd_registry)
            import effort_history
            importlib.reload(effort_history)
            import sessions
            importlib.reload(sessions)
            import anchor_gui
            importlib.reload(anchor_gui)
            html = anchor_gui.generate_html(*anchor_gui.gather_all())
        finally:
            if prev is None:
                _os.environ.pop("ANCHOR_DATA_DIR", None)
            else:
                _os.environ["ANCHOR_DATA_DIR"] = prev
        self.assertIn('href="/anchor.ico', html)
        self.assertNotIn('href="/vendor/brand/gwl-m-icon.svg', html.split("<body")[0])
        self.assertIn('id="tile-grass"', html)
        self.assertNotIn("Claude driver", html)
        self.assertNotIn("Gemini swarm", html)
        self.assertIn("rndRescan(", html)
        row = anchor_gui.render_project_tile_html({
            "id": "p1", "name": "X", "priority": 1, "state": "active",
            "folder_path": td, "notes": "", "blurb": "", "group": "",
        })
        self.assertIn("rndRescan(", row)
        self.assertNotIn("rndSetPriority(", row)
        self.assertNotIn("rndArchive(", row)
        self.assertNotIn("rndRetire(", row)

    def test_home_grass_reads_the_synthetic_dashboard_project(self):
        import anchor_gui

        dashboard = {
            "id": "__dashboard__",
            "name": "Workspace Root (dev)",
            "folder_path": "C:/workspace",
        }
        idea = {
            "title": "Decompose the problem, then synthesize the whole",
            "when": "2026-08-29",
            "source": "Dashboard",
        }
        with mock.patch.object(anchor_gui._rnd, "get_project",
                               return_value=dashboard) as get_project:
            with mock.patch.object(anchor_gui._eh, "grass_workbench_data",
                                   return_value=[idea]) as grass_data:
                html = anchor_gui._home_grass_tile_html()

        get_project.assert_called_once_with("__dashboard__")
        grass_data.assert_called_once_with("C:/workspace", "__dashboard__")
        self.assertIn("Decompose the problem, then synthesize the whole", html)
        self.assertIn("1 idea", html)

    def test_home_grass_empty_state_never_scans_steward_effort_folders(self):
        import anchor_gui

        dashboard = {
            "id": "__dashboard__",
            "name": "Workspace Root (dev)",
            "folder_path": "C:/workspace",
        }
        with mock.patch.object(anchor_gui._rnd, "get_project",
                               return_value=dashboard):
            with mock.patch.object(anchor_gui._eh, "grass_workbench_data",
                                   return_value=[]):
                with mock.patch(
                        "steward_cockpit.steward_campaign.read_grass",
                        side_effect=AssertionError("home must not scan campaigns")) as scan:
                    html = anchor_gui._home_grass_tile_html()

        scan.assert_not_called()
        self.assertIn("Nothing caught yet", html)
        self.assertIn("0 ideas", html)


class ProjectOpenDiscoveryTest(unittest.TestCase):
    def setUp(self):
        import anchor_gui
        self.gui = anchor_gui
        with self.gui._PROJECT_OPEN_DISCOVERY_LOCK:
            self.gui._PROJECT_OPEN_DISCOVERY_INFLIGHT.clear()

    def tearDown(self):
        with self.gui._PROJECT_OPEN_DISCOVERY_LOCK:
            self.gui._PROJECT_OPEN_DISCOVERY_INFLIGHT.clear()

    def test_unauthenticated_open_never_starts_discovery(self):
        with mock.patch.object(self.gui, "discover_and_adopt") as discover:
            started = self.gui._start_project_open_discovery(
                "private-project", authorized=False)
        self.assertFalse(started)
        discover.assert_not_called()

    def test_rapid_repeat_is_singleflight_per_project(self):
        entered = threading.Event()
        release = threading.Event()

        def discover(_pid):
            entered.set()
            release.wait(2)

        with mock.patch.object(self.gui, "discover_and_adopt", discover):
            self.assertTrue(self.gui._start_project_open_discovery(
                "p1", authorized=True))
            self.assertTrue(entered.wait(2), "discovery worker did not start")
            self.assertFalse(self.gui._start_project_open_discovery(
                "p1", authorized=True))
            release.set()
            deadline = time.time() + 2
            while time.time() < deadline:
                with self.gui._PROJECT_OPEN_DISCOVERY_LOCK:
                    if "p1" not in self.gui._PROJECT_OPEN_DISCOVERY_INFLIGHT:
                        break
                time.sleep(0.01)
            with self.gui._PROJECT_OPEN_DISCOVERY_LOCK:
                self.assertNotIn(
                    "p1", self.gui._PROJECT_OPEN_DISCOVERY_INFLIGHT)


class BrowserPopupTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise unittest.SkipTest("Playwright is not installed")
        cls._pw = sync_playwright().start()
        try:
            cls._browser = cls._pw.chromium.launch(headless=True)
        except Exception as exc:
            cls._pw.stop()
            raise unittest.SkipTest("Playwright Chromium unavailable: %s" % exc)

    @classmethod
    def tearDownClass(cls):
        cls._browser.close()
        cls._pw.stop()

    def test_dashboard_click_opens_exactly_one_cockpit_page(self):
        source = (REPO / "anchor_gui.py").read_text(encoding="utf-8")
        start = source.index("function openProjectWindow")
        end = source.index("function rndSetPriority", start)
        # The function lives inside a Python f-string. Materialize that exact
        # browser source without importing Anchor (module startup legitimately
        # migrates the live registry, which a browser test must never touch).
        opener = source[start:end].replace("{BUILD_ID}", "test")
        opener = opener.replace("{{", "{").replace("}}", "}")
        home = ("<!doctype html><button id='open' "
                "onclick=\"openProjectWindow('p1')\">Open</button>"
                "<script>function showToast(t){window.lastToast=t;}\n" +
                opener + "</script>")
        ctx = self._browser.new_context()
        page = ctx.new_page()

        def route(req):
            if "/project/p1" in req.request.url:
                req.fulfill(status=200, content_type="text/html",
                            body="<!doctype html><title>Cockpit</title>")
            else:
                req.fulfill(status=200, content_type="text/html", body=home)

        ctx.route("**/*", route)
        page.goto("http://anchor.test/")
        with ctx.expect_page() as opened:
            page.click("#open")
        popup = opened.value
        popup.wait_for_url("**/project/p1*", timeout=5000)
        self.assertEqual(len(ctx.pages), 2)
        self.assertEqual(page.url, "http://anchor.test/")
        self.assertTrue(popup.evaluate("window.opener === null"))
        ctx.close()

    def test_async_project_create_reserves_then_navigates_one_page(self):
        js = (REPO / "static" / "high-seat.js").read_text(encoding="utf-8")
        home = ("<!doctype html><div id='host'></div><script>"
                "function _anchorToken(){return 'must-not-leak';}\n" + js +
                "\n_ecgHsProjectCreateCard(document.getElementById('host'),"
                "{name:'New Project',folder:'C:/workspace/New Project'});"
                "</script>")
        ctx = self._browser.new_context()
        page = ctx.new_page()

        def route(req):
            url = req.request.url
            if "/api/rnd/new_project" in url:
                req.fulfill(status=200, content_type="application/json",
                            body='{"ok":true,"entry":{"id":"p-new"},'
                                 '"path_existed":false}')
            elif "/project/p-new" in url:
                req.fulfill(status=200, content_type="text/html",
                            body="<!doctype html><title>New cockpit</title>")
            else:
                req.fulfill(status=200, content_type="text/html", body=home)

        ctx.route("**/*", route)
        page.goto("http://anchor.test/")
        with ctx.expect_page() as opened:
            page.click(".ecg-hs-createcard button.pri")
        popup = opened.value
        popup.wait_for_url("**/project/p-new*", timeout=5000)
        self.assertEqual(len(ctx.pages), 2)
        self.assertTrue(popup.evaluate("window.opener === null"))
        self.assertNotIn("token=", popup.url)
        self.assertNotIn("must-not-leak", popup.url)
        ctx.close()
