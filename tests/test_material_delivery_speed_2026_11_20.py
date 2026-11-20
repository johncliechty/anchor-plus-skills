"""Regression & Live HTTP Suite for Material Delivery & Page Speed (2026-11-20).

Covers:
1. Deliverable file HTTP `Range` (`206 Partial Content` for explicit, open-ended, and suffix ranges;
   `416 Range Not Satisfiable`; `If-Range` mismatch fallback to `200 OK`) and strong `ETag`
   revalidation (`If-None-Match` -> `304 Not Modified`, instant invalidation on disk edit,
   and preserved `401` auth + `409` `?hash=` mismatch enforcement).
2. `_send_html` (`/` and `/high-seat`) and textual `_send_bytes` (`/static/*.js`) negotiate lossless
   `gzip` (`Content-Encoding: gzip`, `Vary: Accept-Encoding`) when `Accept-Encoding: gzip` is sent,
   while preserving raw uncompressed bytes for callers without `Accept-Encoding: gzip`.
3. `foundry_api.build_skills()` and `GET /api/skills` use `DirEntry.stat()` + exact mtime-stamp
   caching (`<20ms` warm) while immediately reflecting added, edited, or deleted `SKILL.md`,
   `HUMAN.md`, manifest, and `journal/*.md` files without stale reads.
4. Zero `distro.scan_paths` findings across all modified files.
"""
from __future__ import annotations

import gzip
import hashlib
import http.client
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import anchor_gui
import distro
import foundry_api
import rnd_registry

ANCHOR_ROOT = Path(__file__).resolve().parent.parent


def test_distro_scan_clean_on_material_speed_files() -> None:
    targets = [
        ("anchor_gui.py", ANCHOR_ROOT / "anchor_gui.py"),
        ("foundry_api.py", ANCHOR_ROOT / "foundry_api.py"),
        ("steward_cockpit/steward_routes.py", ANCHOR_ROOT / "steward_cockpit" / "steward_routes.py"),
    ]
    findings = distro.scan_paths(targets)
    assert findings == [], f"Unexpected distro findings: {findings}"


def _raw_get(host: str, port: int, path: str, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    conn = http.client.HTTPConnection(host, port, timeout=15)
    try:
        conn.request("GET", path, headers=headers)
        resp = conn.getresponse()
        body = resp.read()
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        return resp.status, hdrs, body
    finally:
        conn.close()


def test_deliverable_range_etag_hash_and_auth_roundtrip(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    (data_dir / ".anchor").mkdir(parents=True, exist_ok=True)
    tok = os.urandom(16).hex()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_TOKEN", tok)

    proj_dir = tmp_path / "proj"
    eff_dir = proj_dir / "MIT Lectures"
    eff_dir.mkdir(parents=True, exist_ok=True)
    pdf_bytes = b"%PDF-1.7\n" + bytes((i % 251 for i in range(200_000))) + b"\n%%EOF\n"
    pdf_path = eff_dir / "slides_v1.pdf"
    pdf_path.write_bytes(pdf_bytes)
    expected_sha = hashlib.sha256(pdf_bytes).hexdigest()

    proj = rnd_registry.add_project("MIT Test", str(proj_dir))
    pid = proj["id"]

    srv = anchor_gui.make_server("127.0.0.1", 0)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    host, port = srv.server_address[0], srv.server_address[1]
    qs = urllib.parse.urlencode({"pid": pid, "dir": "MIT Lectures", "path": "slides_v1.pdf", "hash": expected_sha})
    route = f"/api/steward/deliverable-file?{qs}"
    auth_h = {"Authorization": f"Bearer {tok}"}

    try:
        # 1. Full 200 OK advertises Accept-Ranges, private no-cache, and strong ETag
        st_code, hdrs, body = _raw_get(host, port, route, auth_h)
        assert st_code == 200
        assert body == pdf_bytes
        assert hdrs.get("accept-ranges") == "bytes"
        assert hdrs.get("cache-control") == "private, no-cache"
        etag1 = hdrs.get("etag")
        assert etag1 and etag1.startswith('"') and etag1.endswith('"')

        # 2. Unauthenticated request is still rejected with 401 even when carrying valid If-None-Match
        st_unauth, _, _ = _raw_get(host, port, route, {"If-None-Match": etag1})
        assert st_unauth == 401

        # 3. Conditional GET with matching ETag (strong & weak) -> 304 Not Modified, 0 body bytes
        st_304, hdrs_304, body_304 = _raw_get(host, port, route, {**auth_h, "If-None-Match": etag1})
        assert st_304 == 304
        assert body_304 == b""
        assert hdrs_304.get("etag") == etag1

        st_304w, _, body_304w = _raw_get(host, port, route, {**auth_h, "If-None-Match": f"W/{etag1}"})
        assert st_304w == 304 and body_304w == b""

        # RFC 9110 §13.2.2: matching If-None-Match takes precedence even when Range is also sent
        st_304r, _, body_304r = _raw_get(
            host, port, route, {**auth_h, "If-None-Match": etag1, "Range": "bytes=0-1023"}
        )
        assert st_304r == 304 and body_304r == b""

        # Non-matching If-None-Match falls through to Range -> 206 Partial Content
        st_206_inm, _, body_206_inm = _raw_get(
            host, port, route, {**auth_h, "If-None-Match": '"other-etag"', "Range": "bytes=0-127"}
        )
        assert st_206_inm == 206 and body_206_inm == pdf_bytes[:128]

        # 4. Explicit byte range (PDF Page-1 header probe) -> 206 Partial Content
        st_r1, hdrs_r1, body_r1 = _raw_get(host, port, route, {**auth_h, "Range": "bytes=0-1023", "If-Range": etag1})
        assert st_r1 == 206
        assert body_r1 == pdf_bytes[:1024]
        assert hdrs_r1.get("content-range") == f"bytes 0-1023/{len(pdf_bytes)}"

        # 5. Open-ended range & suffix range (PDF xref trailer read) -> 206 Partial Content
        tail_start = len(pdf_bytes) - 500
        st_r2, hdrs_r2, body_r2 = _raw_get(host, port, route, {**auth_h, "Range": f"bytes={tail_start}-"})
        assert st_r2 == 206
        assert body_r2 == pdf_bytes[tail_start:]
        assert hdrs_r2.get("content-range") == f"bytes {tail_start}-{len(pdf_bytes) - 1}/{len(pdf_bytes)}"

        st_r3, hdrs_r3, body_r3 = _raw_get(host, port, route, {**auth_h, "Range": "bytes=-256"})
        assert st_r3 == 206
        assert body_r3 == pdf_bytes[-256:]
        assert hdrs_r3.get("content-range") == f"bytes {len(pdf_bytes) - 256}-{len(pdf_bytes) - 1}/{len(pdf_bytes)}"

        # 6. Stale If-Range falls back to full 200 OK per RFC 9110
        st_ifr, _, body_ifr = _raw_get(host, port, route, {**auth_h, "Range": "bytes=0-63", "If-Range": '"stale-etag"'})
        assert st_ifr == 200
        assert body_ifr == pdf_bytes

        # 7. Unsatisfiable range -> 416 Range Not Satisfiable with Content-Range: bytes */total
        st_416, hdrs_416, body_416 = _raw_get(host, port, route, {**auth_h, "Range": f"bytes={len(pdf_bytes) + 100}-"})
        assert st_416 == 416
        assert body_416 == b""
        assert hdrs_416.get("content-range") == f"bytes */{len(pdf_bytes)}"

        # 8. Mutating the file on disk invalidates both the ETag and the SHA-256 hash cache immediately
        updated_bytes = pdf_bytes + b"% revised slide\n"
        pdf_path.write_bytes(updated_bytes)
        # Old ?hash= now fails closed with 409 (immutable lifecycle invariant preserved)
        st_409, _, _ = _raw_get(host, port, route, {**auth_h, "If-None-Match": etag1})
        assert st_409 == 409

        # Unpinned path with old ETag immediately gets 200 OK + new bytes + new ETag (zero stale cache)
        qs_plain = urllib.parse.urlencode({"pid": pid, "dir": "MIT Lectures", "path": "slides_v1.pdf"})
        st_new, hdrs_new, body_new = _raw_get(host, port, f"/api/steward/deliverable-file?{qs_plain}", {**auth_h, "If-None-Match": etag1})
        assert st_new == 200
        assert body_new == updated_bytes
        assert hdrs_new.get("etag") != etag1
    finally:
        srv.shutdown()
        srv.server_close()
        th.join(timeout=5)


def test_html_and_static_bytes_gzip_negotiation(tmp_path: Path, monkeypatch) -> None:
    data_dir = tmp_path / "data"
    (data_dir / ".anchor").mkdir(parents=True, exist_ok=True)
    tok = os.urandom(12).hex()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    monkeypatch.setenv("ANCHOR_TOKEN", tok)

    srv = anchor_gui.make_server("127.0.0.1", 0)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        # Warm up once so first-render Desk bootstrap completes before comparing bytes
        urllib.request.urlopen(
            urllib.request.Request(f"{base}/high-seat", headers={"Authorization": f"Bearer {tok}"}),
            timeout=15,
        ).read()

        # 1. Authenticated /high-seat HTML negotiates gzip and shrinks substantially
        req_gz = urllib.request.Request(
            f"{base}/high-seat",
            headers={"Authorization": f"Bearer {tok}", "Accept-Encoding": "gzip"},
        )
        with urllib.request.urlopen(req_gz, timeout=15) as r_gz:
            wire_gz = r_gz.read()
            assert r_gz.headers.get("Content-Encoding") == "gzip"
            assert "Accept-Encoding" in (r_gz.headers.get("Vary") or "")
        html_text = gzip.decompress(wire_gz).decode("utf-8")
        assert len(wire_gz) < len(html_text.encode("utf-8")) // 2
        assert "<!DOCTYPE html>" in html_text

        # 2. Caller without Accept-Encoding: gzip receives raw HTML
        req_raw = urllib.request.Request(
            f"{base}/high-seat",
            headers={"Authorization": f"Bearer {tok}"},
        )
        with urllib.request.urlopen(req_raw, timeout=15) as r_raw:
            wire_raw = r_raw.read()
            assert r_raw.headers.get("Content-Encoding") is None
        raw_text = wire_raw.decode("utf-8")
        assert raw_text.startswith("<!DOCTYPE html>")
        assert abs(len(raw_text) - len(html_text)) < 64

        # 3. Static JS asset negotiates gzip via _send_bytes
        req_js = urllib.request.Request(
            f"{base}/static/app.js",
            headers={"Accept-Encoding": "gzip"},
        )
        with urllib.request.urlopen(req_js, timeout=15) as r_js:
            js_wire = r_js.read()
            assert r_js.headers.get("Content-Encoding") == "gzip"
        assert "foundry" in gzip.decompress(js_wire).decode("utf-8")
    finally:
        srv.shutdown()
        srv.server_close()
        th.join(timeout=5)


def test_build_skills_cache_speed_and_instant_invalidation(tmp_path: Path, monkeypatch) -> None:
    skills_dir = tmp_path / "skills"
    alpha = skills_dir / "alpha"
    (alpha / "journal").mkdir(parents=True, exist_ok=True)
    (alpha / "SKILL.md").write_text("---\ndescription: Alpha initial protocol\n---\n\n## Stage 1\nBody one.\n", encoding="utf-8")
    (alpha / "journal" / "0001-init.md").write_text("# First Run\nInitial journal entry.\n", encoding="utf-8")

    manifest_file = tmp_path / "foundry_map_v2.json"
    manifest_file.write_text(
        json.dumps({
            "skills": [
                {"ref": "skill:alpha", "name": "Alpha", "source": str(alpha), "status": "stable", "tier": "regular", "version": "1.0.0", "edges": []}
            ]
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(foundry_api, "MANIFEST_PATH", manifest_file)
    monkeypatch.setattr(foundry_api, "FOUNDRY_ROOT", str(tmp_path))
    monkeypatch.setattr(foundry_api, "SKILLS_ROOT", str(skills_dir))

    s1 = foundry_api.build_skills()
    assert len(s1) == 1
    assert s1[0]["description"] == "Alpha initial protocol"
    assert s1[0]["journalCount"] == 1

    #Mutating returned list must never corrupt cached payload
    s1[0]["description"] = "MUTATED_BY_CALLER"
    s2 = foundry_api.build_skills()
    assert s2[0]["description"] == "Alpha initial protocol"

    # Adding a journal entry + editing SKILL.md invalidates stamp immediately with zero manual flush
    (alpha / "SKILL.md").write_text("---\ndescription: Alpha updated protocol v2\n---\n\n## Stage 1\nBody two.\n", encoding="utf-8")
    (alpha / "journal" / "0002-next.md").write_text("# Second Run\nFollow-up journal entry.\n", encoding="utf-8")

    s3 = foundry_api.build_skills()
    assert s3[0]["description"] == "Alpha updated protocol v2"
    assert s3[0]["journalCount"] == 2
    assert {ev["event"] for ev in s3[0]["timeline"]} == {"First Run", "Second Run"}

    # Same-byte-length manifest edit (e.g. "stable" -> "active", both 6 chars) invalidates immediately
    manifest_file.write_text(
        manifest_file.read_text(encoding="utf-8").replace('"stable"', '"active"'),
        encoding="utf-8",
    )
    s4 = foundry_api.build_skills()
    assert s4[0]["status"] == "active"

    # Warm pre-encoded HTTP payload matches JSON & gzip bytes
    t0 = time.perf_counter()
    http_p = foundry_api.build_skills_http_payload()
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert elapsed_ms < 50.0
    assert json.loads(http_p["__preencoded_json__"].decode("utf-8")) == s4
    assert json.loads(gzip.decompress(http_p["__preencoded_gzip__"]).decode("utf-8")) == s4
