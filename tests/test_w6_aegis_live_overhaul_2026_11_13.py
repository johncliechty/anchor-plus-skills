#!/usr/bin/env python3
"""Wave 6 (2026-11-13) — Zero-Critical/High Aegis Posture, CWE-22 Containment,
CWE-918 safe_urlopen, Dynamic ?v=<sha> Asset Cache-Busting + Draft Survival,
and 5-State Failure Contract (unknown != empty).
"""

from __future__ import annotations

import ast
import http.client
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import anchor_gui
import brownfield_scan
import comms_connector
import distro
import effort_history
import high_seat_page
import office_preview
import paths
import rnd_registry
import scribe_engine
from steward_cockpit import aegis_session, steward_engine, steward_routes


def _load_module_from_path(mod_name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(mod_name, str(file_path))
    assert spec is not None and spec.loader is not None, f"Cannot load spec for {file_path}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    spec.loader.exec_module(mod)
    return mod


def _load_aegis_engine():
    candidates = [
        REPO_ROOT.parent / "Skill Foundry" / "skills" / "aegis" / "scripts" / "aegis_engine.py",
        REPO_ROOT / "vendor" / "bundled-skills" / "aegis" / "scripts" / "aegis_engine.py",
    ]
    for cand in candidates:
        if cand.is_file():
            return _load_module_from_path("_w6_aegis_engine", cand)
    raise FileNotFoundError("Could not locate aegis_engine.py relative to REPO_ROOT")


def _http_get_raw(host: str, port: int, request_target: str) -> tuple[int, bytes, dict[str, str]]:
    """Issue a raw HTTP GET via http.client so percent-encoded traversal payloads are sent verbatim."""
    conn = http.client.HTTPConnection(host, port, timeout=8.0)
    try:
        conn.request("GET", request_target, headers={"Host": f"{host}:{port}"})
        resp = conn.getresponse()
        body = resp.read()
        headers = {k.lower(): v for k, v in resp.getheaders()}
        return resp.status, body, headers
    finally:
        conn.close()


def _create_escape_dir_link(link_path: Path, target_dir: Path) -> bool:
    """Create a directory symlink or Windows junction pointing outside root without needing elevation."""
    try:
        os.symlink(str(target_dir), str(link_path), target_is_directory=True)
        return True
    except OSError:
        if os.name == "nt":
            proc = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(link_path), str(target_dir)],
                capture_output=True,
                text=True,
                shell=False,
                check=False,
            )
            return proc.returncode == 0 and link_path.exists()
        return False


def _build_minimal_docx(target: Path, paragraph_text: str = "Quarterly review summary") -> Path:
    """Create a valid minimal .docx archive on disk for office_preview testing."""
    content_types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/word/document.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    doc_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f"<w:body><w:p><w:r><w:t>{paragraph_text}</w:t></w:r></w:p></w:body>"
        "</w:document>"
    )
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("word/document.xml", doc_xml)
    return target


@pytest.fixture
def w6_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Hermetic Anchor data/settings/sidecar environment with zero live-state mutation."""
    data_dir = tmp_path / "anchor_data"
    sidecar_dir = tmp_path / "sidecars"
    settings_dir = tmp_path / "settings"
    code_jobs_dir = tmp_path / "code_jobs"
    for d in (
        data_dir,
        data_dir / ".anchor",
        data_dir / ".anchor" / "attachments",
        data_dir / "Campaign",
        sidecar_dir,
        settings_dir,
        code_jobs_dir,
    ):
        d.mkdir(parents=True, exist_ok=True)

    state_file = data_dir / "steward-cockpit-state.json"
    state_file.write_text("{}", encoding="utf-8")

    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_SIDECAR_DIR", str(sidecar_dir))
    monkeypatch.setenv("ANCHOR_SETTINGS_DIR", str(settings_dir))
    monkeypatch.setenv("ANCHOR_CODE_JOBS_DIR", str(code_jobs_dir))
    monkeypatch.delenv("ANCHOR_TOKEN", raising=False)
    monkeypatch.setattr(steward_engine, "STATE_FILE", state_file)
    paths.ensure_data_dirs()
    return data_dir


@pytest.fixture
def throwaway_anchor_server(w6_env: Path):
    """Boot a throwaway Anchor HTTP server bound to 127.0.0.1:0 (never port 8777)."""
    srv = anchor_gui.make_server("127.0.0.1", 0)
    port = int(srv.server_address[1])
    assert port != 8777
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield port, w6_env
    finally:
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5.0)


def test_aegis_aeg01_shell_false_and_zero_prod_critical_high():
    """Verify AEG-01 shell=False hardening, 0 CRITICAL/HIGH across production code, and 0 findings in this test."""
    assert scribe_engine is not None
    assert paths is not None

    anvil_mod_path = REPO_ROOT / "vendor" / "bundled-skills" / "anvil" / "scripts" / "anvil_engine.py"
    cave_jobs_path = REPO_ROOT / "vendor" / "foundry-page-maps" / "steward-cave" / "sources" / "jobs.py"
    lamp_jobs_path = REPO_ROOT / "vendor" / "foundry-page-maps" / "steward-lamp" / "sources" / "jobs.py"
    for p in (anvil_mod_path, cave_jobs_path, lamp_jobs_path):
        assert p.is_file(), f"Expected hardened module at {p}"

    anvil_mod = _load_module_from_path("_w6_anvil_engine_check", anvil_mod_path)
    cave_jobs_mod = _load_module_from_path("_w6_cave_jobs_check", cave_jobs_path)
    lamp_jobs_mod = _load_module_from_path("_w6_lamp_jobs_check", lamp_jobs_path)
    assert anvil_mod is not None and cave_jobs_mod is not None and lamp_jobs_mod is not None

    # AST check on AEG-01 targets: zero shell=True, os.system, or os.popen
    for mod_path in (REPO_ROOT / "scribe_engine.py", anvil_mod_path, cave_jobs_path, lamp_jobs_path):
        src = mod_path.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=str(mod_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords or []:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant):
                        assert kw.value.value is not True, f"shell=True remaining in {mod_path}:{node.lineno}"

    aegis_eng = _load_aegis_engine()
    repo_scan = aegis_eng.scan_target(REPO_ROOT)
    prod_findings = [
        f
        for f in repo_scan["findings"]
        if not str(f.get("file") or "").replace("\\", "/").startswith("tests/")
    ]
    crit_or_high = [f for f in prod_findings if f.get("severity") in ("CRITICAL", "HIGH")]
    assert crit_or_high == [], f"Expected 0 production CRITICAL/HIGH Aegis findings, got: {crit_or_high}"

    # Verify 0 CRITICAL/HIGH inside vendor/
    vendor_crit_high = [
        f
        for f in prod_findings
        if str(f.get("file") or "").replace("\\", "/").startswith("vendor/")
        and f.get("severity") in ("CRITICAL", "HIGH")
    ]
    assert vendor_crit_high == []


def test_aeg03_resolve_contained_path_and_escape_refusals_across_routes(
    throwaway_anchor_server: tuple[int, Path],
    tmp_path: Path,
):
    """Verify CWE-22 containment in paths.resolve_contained_path and HTTP 400/403 refusals across all 4 routes."""
    port, data_dir = throwaway_anchor_server
    outside_dir = tmp_path / "outside_vault"
    outside_dir.mkdir(parents=True, exist_ok=True)
    secret_marker = b"OUTSIDE-VAULT-SENSITIVE-PAYLOAD"
    outside_file = outside_dir / "loot.txt"
    outside_file.write_bytes(secret_marker)

    # 1. Direct unit tests on paths.resolve_contained_path
    sandbox_root = tmp_path / "sandbox_root"
    (sandbox_root / "nested").mkdir(parents=True, exist_ok=True)
    valid_doc = sandbox_root / "nested" / "note.md"
    valid_doc.write_text("# Safe Note\n", encoding="utf-8")

    resolved_ok = paths.resolve_contained_path(sandbox_root, "nested/note.md", allow_missing=False)
    assert resolved_ok == valid_doc.resolve()
    assert resolved_ok.is_relative_to(sandbox_root.resolve())
    assert paths.resolve_contained_path(sandbox_root, ".", allow_missing=False) == sandbox_root.resolve()

    with pytest.raises(FileNotFoundError):
        paths.resolve_contained_path(sandbox_root, "nested/does_not_exist.md", allow_missing=False)

    escape_vectors = [
        "",
        "   ",
        "../outside_vault/loot.txt",
        "..%2foutside_vault%2floot.txt",
        "%2e%2e/outside_vault/loot.txt",
        "nested/../../outside_vault/loot.txt",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "\\\\fileserver\\share\\loot.txt",
        "nested/bad\x00file.txt",
    ]
    for bad in escape_vectors:
        with pytest.raises(paths.UnsafePathError) as exc_info:
            paths.resolve_contained_path(sandbox_root, bad, allow_missing=True)
        assert "Blocked unsafe path traversal or disallowed URL scheme" in str(exc_info.value)

    junc_in_sandbox = sandbox_root / "junc_escape"
    has_junction = _create_escape_dir_link(junc_in_sandbox, outside_dir)
    if has_junction:
        with pytest.raises(paths.UnsafePathError) as exc_junc:
            paths.resolve_contained_path(sandbox_root, "junc_escape/loot.txt", allow_missing=True)
        assert "Blocked unsafe path traversal or disallowed URL scheme" in str(exc_junc.value)

    # Set up a registered project + effort + attachment root for live HTTP route checks
    proj_dir = tmp_path / "proj_w6"
    (proj_dir / "planning").mkdir(parents=True, exist_ok=True)
    (proj_dir / "planning" / "MASTER-PLAN.md").write_text("# W6 Master Plan\nSAFE-ARTIFACT\n", encoding="utf-8")
    eff_dir = proj_dir / "effort-alpha"
    (eff_dir / "reports").mkdir(parents=True, exist_ok=True)
    (eff_dir / "CAMPAIGN.md").write_text("# Effort Alpha\n", encoding="utf-8")
    (eff_dir / "reports" / "summary.md").write_text("# Safe Deliverable\n", encoding="utf-8")

    proj_junc = proj_dir / "junc_out"
    eff_junc = eff_dir / "junc_out"
    att_root = data_dir / ".anchor" / "attachments"
    att_safe = att_root / "invoice.txt"
    att_safe.write_text("SAFE-ATTACHMENT", encoding="utf-8")
    att_junc = att_root / "junc_out"

    has_proj_junc = _create_escape_dir_link(proj_junc, outside_dir)
    has_eff_junc = _create_escape_dir_link(eff_junc, outside_dir)
    has_att_junc = _create_escape_dir_link(att_junc, outside_dir)

    proj = rnd_registry.add_project("Wave6Proj", str(proj_dir))
    pid = proj["id"]
    effort_history.adopt_discovered(proj_dir, pid, brownfield_scan.scan(str(proj_dir)))

    # 2. Route A: GET /artifact/<pid>?path=...
    st_ok, body_ok, _ = _http_get_raw("127.0.0.1", port, f"/artifact/{pid}?path=planning/MASTER-PLAN.md")
    assert st_ok == 200 and b"W6 Master Plan" in body_ok

    st_miss, _, _ = _http_get_raw("127.0.0.1", port, f"/artifact/{pid}?path=planning/missing.md")
    assert st_miss == 404

    artifact_escapes = [
        "../outside_vault/loot.txt",
        "%2e%2e/outside_vault/loot.txt",
        "..%2foutside_vault%2floot.txt",
        "/etc/passwd",
        "C:%5CWindows%5Cwin.ini",
        ".git/config",
    ]
    if has_proj_junc:
        artifact_escapes.append("junc_out/loot.txt")
    for raw_q in artifact_escapes:
        code, body, _ = _http_get_raw("127.0.0.1", port, f"/artifact/{pid}?path={raw_q}")
        assert code in (400, 403), (raw_q, code, body)
        assert b"Blocked unsafe path traversal or disallowed URL scheme" in body
        assert secret_marker not in body

    # 3. Route B: GET /api/steward/deliverable-file & steward_routes.handle_get
    st_deliv_ok, body_deliv_ok, _ = _http_get_raw(
        "127.0.0.1",
        port,
        f"/api/steward/deliverable-file?pid={pid}&dir=effort-alpha&path=reports/summary.md",
    )
    assert st_deliv_ok == 200 and b"Safe Deliverable" in body_deliv_ok

    st_deliv_miss, _, _ = _http_get_raw(
        "127.0.0.1",
        port,
        f"/api/steward/deliverable-file?pid={pid}&dir=effort-alpha&path=reports/ghost.md",
    )
    assert st_deliv_miss == 404

    deliv_escapes = [
        "../../outside_vault/loot.txt",
        "%2e%2e/%2e%2e/outside_vault/loot.txt",
        "/etc/passwd",
        "C:%5CWindows%5Cwin.ini",
    ]
    if has_eff_junc:
        deliv_escapes.append("junc_out/loot.txt")
    for raw_q in deliv_escapes:
        code, body, _ = _http_get_raw(
            "127.0.0.1",
            port,
            f"/api/steward/deliverable-file?pid={pid}&dir=effort-alpha&path={raw_q}",
        )
        assert code in (400, 403), (raw_q, code, body)
        assert b"Blocked unsafe path traversal or disallowed URL scheme" in body
        assert secret_marker not in body

    direct_obj, direct_code = steward_routes.handle_get(
        str(eff_dir), "deliverable-file", {"path": "../outside_vault/loot.txt"}
    )
    assert direct_code == 403
    assert direct_obj["failure_state"] == "dependency-returns-garbage"
    assert direct_obj["error"] == "Blocked unsafe path traversal or disallowed URL scheme"

    # 4. Route C: GET /api/steward/comms/attachment & comms_connector.resolve_attachment_file_path
    q_safe_att = urllib.parse.quote(str(att_safe))
    st_att_ok, body_att_ok, _ = _http_get_raw("127.0.0.1", port, f"/api/steward/comms/attachment?path={q_safe_att}")
    assert st_att_ok == 200 and body_att_ok == b"SAFE-ATTACHMENT"

    q_miss_att = urllib.parse.quote(str(att_root / "missing.pdf"))
    st_att_miss, _, _ = _http_get_raw("127.0.0.1", port, f"/api/steward/comms/attachment?path={q_miss_att}")
    assert st_att_miss == 404
    assert comms_connector.resolve_attachment_file_path(raw_path="missing.pdf", allowed_roots=[att_root]) is None

    att_escapes = [
        "../outside_vault/loot.txt",
        "%2e%2e/outside_vault/loot.txt",
        urllib.parse.quote(str(outside_file)),
    ]
    if has_att_junc:
        att_escapes.append(urllib.parse.quote(str(att_junc / "loot.txt")))
    for raw_q in att_escapes:
        code, body, _ = _http_get_raw("127.0.0.1", port, f"/api/steward/comms/attachment?path={raw_q}")
        assert code in (400, 403), (raw_q, code, body)
        assert b"Blocked unsafe path traversal or disallowed URL scheme" in body
        assert secret_marker not in body

    with pytest.raises(paths.UnsafePathError):
        comms_connector.resolve_attachment_file_path(raw_path="../loot.txt", allowed_roots=[att_root])

    # 5. Surface D: office_preview.resolve_preview_path & render_preview_html
    docx_path = _build_minimal_docx(sandbox_root / "nested" / "brief.docx", "Preview Safe Content")
    resolved_prev = office_preview.resolve_preview_path(sandbox_root, "nested/brief.docx", allow_missing=False)
    assert resolved_prev == docx_path.resolve()

    for bad_prev in ("../outside_vault/loot.txt", "%2e%2e/loot.txt", "/etc/passwd"):
        with pytest.raises(paths.UnsafePathError):
            office_preview.resolve_preview_path(sandbox_root, bad_prev, allow_missing=True)
    if has_junction:
        with pytest.raises(paths.UnsafePathError):
            office_preview.resolve_preview_path(sandbox_root, "junc_escape/loot.txt", allow_missing=True)

    preview_html = office_preview.render_preview_html(
        docx_path, title="Brief", download_href="/artifact/p1?path=nested/brief.docx&download=1"
    )
    assert "Preview Safe Content" in preview_html

    for bad_href in (
        "file:///etc/passwd",
        "javascript:alert(1)",
        "ftp://example.com/brief.docx",
        "../outside_vault/loot.txt",
        "%2e%2e/loot.txt",
    ):
        with pytest.raises(paths.UnsafePathError) as exc_href:
            office_preview.render_preview_html(docx_path, title="Brief", download_href=bad_href)
        assert "Blocked unsafe path traversal or disallowed URL scheme" in str(exc_href.value)

    with pytest.raises(OSError, match=r"Target file unreadable \(unknown\)"):
        office_preview.render_preview_html(sandbox_root / "nested" / "absent.docx")


def test_aeg04_safe_urlopen_scheme_and_timeout_bounds_across_callers(monkeypatch: pytest.MonkeyPatch):
    """Verify paths.safe_urlopen scheme/netloc/timeout guards and zero raw urllib.request.urlopen in production callers."""
    disallowed_urls = [
        "file:///etc/passwd",
        "ftp://example.com/resource",
        "gopher://example.com/1",
        "javascript:alert(1)",
        "data:text/plain;base64,SGVsbG8=",
        "",
        "http:///missing-host",
        "https://example.com/path\r\nX-Injected: 1",
    ]
    for bad_url in disallowed_urls:
        with pytest.raises(paths.DisallowedUrlSchemeError) as exc_u:
            paths.safe_urlopen(bad_url, timeout=5.0)
        assert isinstance(exc_u.value, ValueError)
        assert "Blocked unsafe path traversal or disallowed URL scheme" in str(exc_u.value)

    for bad_timeout in (0, -1, -0.01, 15.5, 30, None, True, False, float("inf"), float("nan")):
        with pytest.raises(ValueError):
            paths.safe_urlopen("https://example.com/status", timeout=bad_timeout)  # type: ignore[arg-type]

    # Local loopback HTTP server proof (real http://127.0.0.1:<port> with timeout <= 15s)
    class _OkHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"ok":true}')

        def log_message(self, fmt, *args):
            return

    httpd = HTTPServer(("127.0.0.1", 0), _OkHandler)
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        local_url = f"http://127.0.0.1:{httpd.server_address[1]}/health"
        assert urllib.parse.urlparse(local_url).scheme in ("http", "https")
        assert local_url.startswith(("http://", "https://"))
        with paths.safe_urlopen(local_url, timeout=5.0) as resp:
            assert resp.status == 200
            assert json.loads(resp.read().decode("utf-8")) == {"ok": True}
    finally:
        httpd.shutdown()
        httpd.server_close()
        t.join(timeout=3.0)

    # Hermetic HTTPS check via monkeypatched urllib.request.urlopen (no external network)
    seen_calls: list[tuple[str, float]] = []

    class _DummyHttpsResp(io.BytesIO):
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.close()

    def _fake_urlopen(url_or_req, *args, timeout=None, **kwargs):
        u = url_or_req.full_url if hasattr(url_or_req, "full_url") else str(url_or_req)
        seen_calls.append((u, float(timeout)))
        return _DummyHttpsResp(b'{"https_ok":true}')

    monkeypatch.setattr(urllib.request, "urlopen", _fake_urlopen)
    https_url = "https://example.com/api/v1/ping"
    assert https_url.startswith(("http://", "https://"))
    with paths.safe_urlopen(https_url, timeout=15.0) as resp_s:
        assert json.loads(resp_s.read().decode("utf-8")) == {"https_ok": True}
    assert seen_calls == [(https_url, 15.0)]

    # AST verification across all Wave 6 network caller modules: zero raw urllib.request.urlopen
    caller_rel_paths = [
        "comms_connector.py",
        "anchor_gui.py",
        "anchor_healthcheck.py",
        "doctor.py",
        "preview_server.py",
        "supervisor.py",
        "usage_allowance_monitor.py",
        "scribe_engine.py",
        "tools/steward_comms.py",
    ]
    for rel in caller_rel_paths:
        mod_file = REPO_ROOT / rel
        src = mod_file.read_text(encoding="utf-8")
        tree = ast.parse(src, filename=rel)
        raw_urlopen_lines: list[int] = []
        safe_urlopen_count = 0

        class _UrlopenVisitor(ast.NodeVisitor):
            def __init__(self) -> None:
                self._in_safe_urlopen_wrapper = False

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                prev = self._in_safe_urlopen_wrapper
                if node.name == "safe_urlopen":
                    self._in_safe_urlopen_wrapper = True
                self.generic_visit(node)
                self._in_safe_urlopen_wrapper = prev

            def visit_Call(self, node: ast.Call) -> None:
                nonlocal safe_urlopen_count
                fn = node.func
                if isinstance(fn, ast.Attribute) and fn.attr == "safe_urlopen":
                    safe_urlopen_count += 1
                elif isinstance(fn, ast.Name) and fn.id == "safe_urlopen":
                    safe_urlopen_count += 1
                elif not self._in_safe_urlopen_wrapper:
                    if isinstance(fn, ast.Attribute) and fn.attr == "urlopen":
                        raw_urlopen_lines.append(getattr(node, "lineno", -1))
                    elif isinstance(fn, ast.Name) and fn.id == "urlopen":
                        raw_urlopen_lines.append(getattr(node, "lineno", -1))
                self.generic_visit(node)

        _UrlopenVisitor().visit(tree)
        assert raw_urlopen_lines == [], f"{rel} still contains raw urlopen calls at lines {raw_urlopen_lines}"
        assert safe_urlopen_count >= 1, f"{rel} did not wire safe_urlopen"


def test_aeg06_distro_clean_no_provider_schema_dirs_and_cache_busting_draft_survival(
    throwaway_anchor_server: tuple[int, Path],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Verify no .provider-schema-* dirs, clean distro scans, live ?v=<sha> updates, and composer draft survival."""
    port, _ = throwaway_anchor_server

    # 1. Zero stray .provider-schema-* temp directories in REPO_ROOT
    assert list(REPO_ROOT.glob(".provider-schema-*")) == []

    # 2. Distro PII/path scan and stdlib-only import scan clean on Wave 6 modules
    scanned_rels = [
        "comms_connector.py",
        "scribe_engine.py",
        "paths.py",
        "high_seat_page.py",
        "office_preview.py",
        "steward_cockpit/steward_routes.py",
        "anchor_gui.py",
    ]
    file_pairs = [(rel, REPO_ROOT / rel) for rel in scanned_rels]
    assert distro.scan_paths(file_pairs, root=REPO_ROOT) == []
    assert distro.scan_third_party_imports(file_pairs, root=REPO_ROOT) == []

    # 3. Render Cave HTML and Cockpit HTML (both mounted and standalone with empty BUILD_ID)
    cave_html_1 = high_seat_page.render_high_seat_page(logged_in=True)
    m_cave_js_1 = re.search(r'/static/high-seat-page\.js\?v=([0-9a-f]{12})', cave_html_1)
    m_cave_css_1 = re.search(r'/static/high-seat-page\.css\?v=([0-9a-f]{12})', cave_html_1)
    assert m_cave_js_1 is not None, "Missing 12-hex ?v= on /static/high-seat-page.js"
    assert m_cave_css_1 is not None, "Missing 12-hex ?v= on /static/high-seat-page.css"

    monkeypatch.setitem(steward_routes.CONFIG, "build", "")
    cockpit_html_1 = steward_routes.serve_page_doc(
        "v1", pid="p-w6", effort_dir="effort-alpha", mount_prefix="/steward", api_prefix="/api/steward"
    )
    assert cockpit_html_1 is not None
    m_cp_js_1 = re.search(r'/steward-static/shared\.js\?v=([0-9a-f]{12})', cockpit_html_1)
    m_cp_css_1 = re.search(r'/steward-static/shared\.css\?v=([0-9a-f]{12})', cockpit_html_1)
    assert m_cp_js_1 is not None, "Missing 12-hex ?v= on /steward-static/shared.js"
    assert m_cp_css_1 is not None, "Missing 12-hex ?v= on /steward-static/shared.css"

    standalone_html = steward_routes.serve_page_doc("v1", pid="p-w6", mount_prefix="", api_prefix="/api")
    assert standalone_html is not None
    assert re.search(r'/static/shared\.js\?v=([0-9a-f]{12})', standalone_html) is not None
    assert re.search(r'/static/shared\.css\?v=([0-9a-f]{12})', standalone_html) is not None

    # 4. Mutate copied static assets on disk WITHOUT server restart -> ?v=<hash> updates immediately
    temp_anchor_root = tmp_path / "asset_mirror"
    (temp_anchor_root / "static").mkdir(parents=True, exist_ok=True)
    (temp_anchor_root / "steward_cockpit" / "static").mkdir(parents=True, exist_ok=True)
    for asset_name in (
        "high-seat-page.js",
        "high-seat-page.css",
        "steward-dialogue.js",
        "steward-dialogue.css",
        "cave-terminal.js",
        "app-frame.js",
        "provider-setup.css",
        "provider-controls.js",
    ):
        src_p = REPO_ROOT / "static" / asset_name
        if src_p.is_file():
            shutil.copy2(src_p, temp_anchor_root / "static" / asset_name)
    for st_asset in ("v1.html", "shared.js", "shared.css", "md.js", "plate.js", "skill-icons.js", "notebook-actions.js"):
        src_p = REPO_ROOT / "steward_cockpit" / "static" / st_asset
        if src_p.is_file():
            shutil.copy2(src_p, temp_anchor_root / "steward_cockpit" / "static" / st_asset)

    monkeypatch.setattr(high_seat_page, "ANCHOR_DIR", temp_anchor_root)
    monkeypatch.setattr(steward_routes, "STATIC", temp_anchor_root / "steward_cockpit" / "static")
    high_seat_page._STATIC_ASSET_HASH_CACHE.clear()
    steward_routes._STATIC_ASSET_HASH_CACHE.clear()

    proj = rnd_registry.add_project("CacheBustProj", str(tmp_path / "cb_proj"))
    (tmp_path / "cb_proj" / "effort-cb").mkdir(parents=True, exist_ok=True)
    (tmp_path / "cb_proj" / "effort-cb" / "CAMPAIGN.md").write_text("# CB\n", encoding="utf-8")
    cb_pid = proj["id"]

    st_c1, raw_c1, _ = _http_get_raw("127.0.0.1", port, "/high-seat")
    st_s1, raw_s1, _ = _http_get_raw("127.0.0.1", port, f"/steward/v1?pid={cb_pid}&dir=effort-cb")
    assert st_c1 == 200 and st_s1 == 200
    c_js_before = re.search(r'/static/high-seat-page\.js\?v=([0-9a-f]{12})', raw_c1.decode("utf-8")).group(1)  # type: ignore[union-attr]
    c_css_before = re.search(r'/static/high-seat-page\.css\?v=([0-9a-f]{12})', raw_c1.decode("utf-8")).group(1)  # type: ignore[union-attr]
    s_js_before = re.search(r'/steward-static/shared\.js\?v=([0-9a-f]{12})', raw_s1.decode("utf-8")).group(1)  # type: ignore[union-attr]
    s_css_before = re.search(r'/steward-static/shared\.css\?v=([0-9a-f]{12})', raw_s1.decode("utf-8")).group(1)  # type: ignore[union-attr]

    # Append benign comment bytes to assets while the SAME server stays live
    for p_mut in (
        temp_anchor_root / "static" / "high-seat-page.js",
        temp_anchor_root / "static" / "high-seat-page.css",
        temp_anchor_root / "steward_cockpit" / "static" / "shared.js",
        temp_anchor_root / "steward_cockpit" / "static" / "shared.css",
    ):
        p_mut.write_text(p_mut.read_text(encoding="utf-8") + "\n/* wave6-cache-bust-probe */\n", encoding="utf-8")

    st_c2, raw_c2, _ = _http_get_raw("127.0.0.1", port, "/high-seat")
    st_s2, raw_s2, _ = _http_get_raw("127.0.0.1", port, f"/steward/v1?pid={cb_pid}&dir=effort-cb")
    assert st_c2 == 200 and st_s2 == 200
    html_c2 = raw_c2.decode("utf-8")
    html_s2 = raw_s2.decode("utf-8")
    c_js_after = re.search(r'/static/high-seat-page\.js\?v=([0-9a-f]{12})', html_c2).group(1)  # type: ignore[union-attr]
    c_css_after = re.search(r'/static/high-seat-page\.css\?v=([0-9a-f]{12})', html_c2).group(1)  # type: ignore[union-attr]
    s_js_after = re.search(r'/steward-static/shared\.js\?v=([0-9a-f]{12})', html_s2).group(1)  # type: ignore[union-attr]
    s_css_after = re.search(r'/steward-static/shared\.css\?v=([0-9a-f]{12})', html_s2).group(1)  # type: ignore[union-attr]

    assert c_js_after != c_js_before
    assert c_css_after != c_css_before
    assert s_js_after != s_js_before
    assert s_css_after != s_css_before

    # 5. Draft survival oracle: verify stable localStorage keys in JS + execute Node VM reload simulation
    cave_js_src = (REPO_ROOT / "static" / "high-seat-page.js").read_text(encoding="utf-8")
    shared_js_src = (REPO_ROOT / "steward_cockpit" / "static" / "shared.js").read_text(encoding="utf-8")
    assert "DRAFT_KEY = 'anchor:draft:highseat'" in cave_js_src
    assert "anchor_cave_steward_dir_" in cave_js_src
    assert 'DRAFT_KEY = "anchor:draft:say:" + (PARAMS.get("pid") || "") + ":" + DIR' in shared_js_src

    cave_draft_line = next(l for l in cave_js_src.splitlines() if "DRAFT_KEY = 'anchor:draft:highseat'" in l)
    shared_draft_line = next(l for l in shared_js_src.splitlines() if 'DRAFT_KEY = "anchor:draft:say:"' in l)
    node_bin = shutil.which("node")
    assert node_bin is not None, "Node runtime expected for deterministic JS localStorage reload check"
    node_script = (
        "const store = new Map();\n"
        "const localStorage = {\n"
        "  getItem: (k) => (store.has(k) ? store.get(k) : null),\n"
        "  setItem: (k, v) => store.set(String(k), String(v)),\n"
        "};\n"
        "function bootCave(scriptUrl) {\n"
        f"  {cave_draft_line.strip()}\n"
        "  const scribeKey = 'anchor_cave_steward_dir_' + 'msg-42';\n"
        "  return { DRAFT_KEY, scribeKey, scriptUrl };\n"
        "}\n"
        "function bootCockpit(pageSearch, scriptUrl) {\n"
        "  const PARAMS = new URLSearchParams(pageSearch);\n"
        "  const DIR = PARAMS.get('dir') || '';\n"
        "  const TILE = PARAMS.get('view') === 'tile';\n"
        f"  {shared_draft_line.strip()}\n"
        "  return { DRAFT_KEY, scriptUrl };\n"
        "}\n"
        f"const c1 = bootCave('/static/high-seat-page.js?v={c_js_before}');\n"
        "localStorage.setItem(c1.DRAFT_KEY, 'Unsent Cave thought before deploy');\n"
        "localStorage.setItem(c1.scribeKey, 'Unsent Scribe direction before deploy');\n"
        f"const s1 = bootCockpit('?pid={cb_pid}&dir=effort-cb', '/steward-static/shared.js?v={s_js_before}');\n"
        "localStorage.setItem(s1.DRAFT_KEY, 'Unsent Cockpit composer draft before deploy');\n"
        f"const c2 = bootCave('/static/high-seat-page.js?v={c_js_after}');\n"
        f"const s2 = bootCockpit('?pid={cb_pid}&dir=effort-cb', '/steward-static/shared.js?v={s_js_after}');\n"
        "console.log(JSON.stringify({\n"
        "  caveDraft: localStorage.getItem(c2.DRAFT_KEY),\n"
        "  scribeDraft: localStorage.getItem(c2.scribeKey),\n"
        "  cockpitDraft: localStorage.getItem(s2.DRAFT_KEY),\n"
        "  hashChanged: c1.scriptUrl !== c2.scriptUrl && s1.scriptUrl !== s2.scriptUrl,\n"
        "}));\n"
    )
    proc = subprocess.run(
        [node_bin, "-e", node_script],
        capture_output=True,
        text=True,
        shell=False,
        check=True,
        timeout=10.0,
    )
    reload_result = json.loads(proc.stdout.strip())
    assert reload_result == {
        "caveDraft": "Unsent Cave thought before deploy",
        "scribeDraft": "Unsent Scribe direction before deploy",
        "cockpitDraft": "Unsent Cockpit composer draft before deploy",
        "hashChanged": True,
    }


def test_wave6_five_state_failure_contract_unknown_not_equal_empty(
    w6_env: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Verify all 5 Wave 6 failure states (503, 504, 400/403, 500, and 200 empty-but-valid) never conflate unknown with empty."""
    eff_dir = tmp_path / "effort_5state"
    eff_dir.mkdir(parents=True, exist_ok=True)
    clean_py = eff_dir / "clean_module.py"
    clean_py.write_text("def add_numbers(a: int, b: int) -> int:\n    return a + b\n", encoding="utf-8")

    # 1. dependency-missing -> HTTP 503 "Security scanner module unavailable"
    monkeypatch.setattr(
        aegis_session,
        "_load_aegis_engine",
        lambda: (_ for _ in ()).throw(ImportError("scanner missing")),
    )
    obj_503, code_503 = steward_routes.handle_post(
        str(eff_dir), "aegis", {"action": "scan", "target": "."}
    )
    assert code_503 == 503
    assert obj_503["ok"] is False
    assert obj_503["failure_state"] == "dependency-missing"
    assert obj_503["error"] == "Security scanner module unavailable"
    assert "findings" not in obj_503

    obj_503_get, code_503_get = steward_routes.handle_get(
        str(eff_dir), "aegis", {"target": "clean_module.py"}
    )
    assert code_503_get == 503
    assert obj_503_get["failure_state"] == "dependency-missing"
    assert obj_503_get["error"] == "Security scanner module unavailable"
    monkeypatch.undo()

    # Restore clean engine loader for states 2..5
    aeg_engine = _load_aegis_engine()
    monkeypatch.setattr(aegis_session, "_load_aegis_engine", lambda: aeg_engine)

    # 2. dependency-slow-or-killed -> HTTP 504 "Upstream URL fetch exceeded 15s timeout"
    monkeypatch.setattr(
        paths,
        "safe_urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError(socket.timeout("15s exceeded"))),
    )
    obj_504, code_504 = steward_routes.handle_post(
        str(eff_dir),
        "aegis",
        {"action": "scan", "target": ".", "url": "https://example.com/slow-feed", "timeout": 15.0},
    )
    assert code_504 == 504
    assert obj_504["ok"] is False
    assert obj_504["failure_state"] == "dependency-slow-or-killed"
    assert obj_504["error"] == "Upstream URL fetch exceeded 15s timeout"
    assert "findings" not in obj_504

    # 3. dependency-returns-garbage -> HTTP 400 or 403 "Blocked unsafe path traversal or disallowed URL scheme"
    obj_403_path, code_403_path = steward_routes.handle_post(
        str(eff_dir), "aegis", {"action": "scan", "target": "../escape.py"}
    )
    assert code_403_path in (400, 403)
    assert obj_403_path["ok"] is False
    assert obj_403_path["failure_state"] == "dependency-returns-garbage"
    assert obj_403_path["error"] == "Blocked unsafe path traversal or disallowed URL scheme"

    obj_403_url, code_403_url = steward_routes.handle_get(
        str(eff_dir), "aegis", {"url": "file:///etc/passwd"}
    )
    assert code_403_url in (400, 403)
    assert obj_403_url["ok"] is False
    assert obj_403_url["failure_state"] == "dependency-returns-garbage"
    assert obj_403_url["error"] == "Blocked unsafe path traversal or disallowed URL scheme"

    obj_403_deliv, code_403_deliv = steward_routes.handle_get(
        str(eff_dir), "deliverable-file", {"path": "%2e%2e/escape.py"}
    )
    assert code_403_deliv in (400, 403)
    assert obj_403_deliv["failure_state"] == "dependency-returns-garbage"
    assert obj_403_deliv["error"] == "Blocked unsafe path traversal or disallowed URL scheme"

    # 4. backing-store-unreadable -> HTTP 500 "Target file unreadable (unknown)"
    obj_500_missing_target, code_500_missing_target = steward_routes.handle_post(
        str(eff_dir), "aegis", {"action": "scan", "target": "unreadable_missing.py"}
    )
    assert code_500_missing_target == 500
    assert obj_500_missing_target["ok"] is False
    assert obj_500_missing_target["failure_state"] == "backing-store-unreadable"
    assert obj_500_missing_target["error"] == "Target file unreadable (unknown)"
    assert "findings" not in obj_500_missing_target

    corrupt_dir = tmp_path / "effort_corrupt_store"
    (corrupt_dir / ".aegis").mkdir(parents=True, exist_ok=True)
    (corrupt_dir / ".aegis" / "session.json").write_bytes(b"\xff\xfe\x00not-utf8-json")
    obj_500_corrupt, code_500_corrupt = steward_routes.handle_get(str(corrupt_dir), "aegis", {})
    assert code_500_corrupt == 500
    assert obj_500_corrupt["ok"] is False
    assert obj_500_corrupt["failure_state"] == "backing-store-unreadable"
    assert obj_500_corrupt["error"] == "Target file unreadable (unknown)"

    # 5. empty-but-valid -> HTTP 200 "Aegis scan clean (0 CRITICAL/HIGH findings)"
    obj_200, code_200 = steward_routes.handle_post(
        str(eff_dir), "aegis", {"action": "scan", "target": "."}
    )
    assert code_200 == 200
    assert obj_200["ok"] is True
    assert obj_200["critical_count"] == 0
    assert obj_200["high_count"] == 0
    assert obj_200["failure_state"] == "empty-but-valid"
    assert obj_200["status_message"] == "Aegis scan clean (0 CRITICAL/HIGH findings)"

    obj_200_get, code_200_get = steward_routes.handle_get(str(eff_dir), "aegis", {"target": "clean_module.py"})
    assert code_200_get == 200
    assert obj_200_get["failure_state"] == "empty-but-valid"
    assert obj_200_get["status_message"] == "Aegis scan clean (0 CRITICAL/HIGH findings)"
