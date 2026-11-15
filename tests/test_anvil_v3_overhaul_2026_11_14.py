"""Regression Suite for Anvil v3 Overhaul (2026-11-14).

Verifies:
1. Bundled vendor engine fallback (`vendor/bundled-skills/anvil`) & byte-for-byte parity with Skill Foundry.
2. Safe arXiv `/e-print/` multi-file `.tar.gz` & `.gz` extraction + strict tar traversal/symlink/hardlink/secret rejection.
3. Single-scan `start_cockpit_session`, lazy-migration write-back in `get_session_status`, and `<15 KB` `?summary=1` status payload.
4. On-demand Level-3 file source endpoint (`GET anvil/source`) and path-containment / secret guards.
5. Cockpit chat mirroring (`role == 'anvil'`), pre-session `discover_cockpit_candidates` safety, honest `STATIC_ONLY`/`DIVERGENCE`/`EXECUTED_PASS` verdicts, real model seating (zero fake placeholder strings), and `distro.scan_paths` cleanliness.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import sys
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

import distro
from steward_cockpit import anvil_session, steward_routes

ANCHOR_ROOT = Path(__file__).resolve().parent.parent
BUNDLED_ANVIL_DIR = ANCHOR_ROOT / "vendor" / "bundled-skills" / "anvil"


def _build_tar_gz_bytes(entries: list[tuple[str, bytes, bytes]]) -> bytes:
    """Create an in-memory `.tar.gz` archive from `(name, typeflag, payload)` tuples."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for name, typeflag, data in entries:
            info = tarfile.TarInfo(name=name)
            info.type = typeflag
            if typeflag in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                info.linkname = data.decode("utf-8")
                info.size = 0
                tf.addfile(info)
            else:
                info.size = len(data)
                tf.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def test_bundled_anvil_engine_fallback_and_byte_parity(tmp_path: Path):
    bundled_scripts = BUNDLED_ANVIL_DIR / "scripts"
    assert (bundled_scripts / "anvil_engine.py").is_file()

    missing_foundry = tmp_path / "nonexistent_foundry_dir"
    loaded = anvil_session._load_anvil_engine((missing_foundry, bundled_scripts))
    try:
        assert loaded is not None
        assert Path(loaded.__file__).resolve() == (bundled_scripts / "anvil_engine.py").resolve()
        for attr in ("build_map", "paper_to_code_map", "get_file_level3_source", "extract_orange_split"):
            assert hasattr(loaded, attr), f"Missing {attr} on bundled anvil_engine"
    finally:
        # Restore default engine binding
        anvil_session.anvil_engine = anvil_session._load_anvil_engine()

    foundry_anvil = ANCHOR_ROOT.parent / ("Skill" + " Foundry") / "skills" / "anvil"
    if foundry_anvil.is_dir():
        bundled_files = [p for p in sorted(BUNDLED_ANVIL_DIR.rglob("*")) if p.is_file()]
        assert len(bundled_files) >= 6
        for bf in bundled_files:
            rel = bf.relative_to(BUNDLED_ANVIL_DIR)
            assert "__pycache__" not in rel.parts
            src = foundry_anvil / rel
            assert src.is_file(), f"Bundled file missing from canonical skill: {rel}"
            assert hashlib.sha256(bf.read_bytes()).hexdigest() == hashlib.sha256(src.read_bytes()).hexdigest()


def test_safe_arxiv_eprint_bundle_extraction_and_malicious_tar_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cdir = tmp_path / "paper_cockpit"
    cdir.mkdir()
    (cdir / "flow_model.py").write_text(
        "import math\n\n"
        "def affine_forward(z: float, mu: float, sigma: float) -> tuple[float, float]:\n"
        '    """Forward affine transformation x = mu + sigma * z and log-det."""\n'
        "    x = mu + sigma * z\n"
        "    log_det = math.log(abs(sigma))\n"
        "    return x, log_det\n",
        encoding="utf-8",
    )

    main_tex = (
        b"\\documentclass{article}\n"
        b"\\title{Tractable Affine Flows}\n"
        b"\\begin{document}\n"
        b"\\section{Overview}\n"
        b"We introduce affine flows.\n"
        b"\\input{sec_methods}\n"
        b"\\end{document}\n"
    )
    methods_tex = (
        b"\\section{Affine Coupling Mechanics}\n"
        b"\\begin{equation}\\label{eq:affine}\n"
        b"x = \\mu + \\sigma z, \\quad \\log |\\det J| = \\log |\\sigma|\n"
        b"\\end{equation}\n"
        b"\\begin{algorithm}\n"
        b"\\caption{Affine Forward Pass}\n"
        b"\\begin{algorithmic}\n"
        b"\\Require Latent $z$, location $\\mu$, scale $\\sigma$\n"
        b"\\Ensure Sample $x$ and $\\log |\\det J|$\n"
        b"\\State Compute $x \\gets \\mu + \\sigma z$ via $\\text{affine\\_forward}$\n"
        b"\\Return $(x, \\log |\\sigma|)$\n"
        b"\\end{algorithmic}\n"
        b"\\end{algorithm}\n"
    )
    good_tar = _build_tar_gz_bytes([
        ("main.tex", tarfile.REGTYPE, main_tex),
        ("sec_methods.tex", tarfile.REGTYPE, methods_tex),
    ])

    def fake_urlopen(url: str, max_bytes: int = 2_000_000, timeout: float = 12.0):
        if "/e-print/" in url:
            return good_tar, "application/x-eprint-tar"
        if "/api/query" in url:
            atom = (
                b'<?xml version="1.0" encoding="UTF-8"?>'
                b'<feed xmlns="http://www.w3.org/2005/Atom">'
                b"<entry><title>Tractable Affine Flows</title><summary>Affine flow summary.</summary></entry>"
                b"</feed>"
            )
            return atom, "application/atom+xml"
        raise AssertionError(f"Unexpected URL: {url}")

    monkeypatch.setattr(anvil_session, "_safe_urlopen", fake_urlopen)
    res = anvil_session.start_cockpit_session(
        cdir,
        software_spec=".",
        paper_spec="https://arxiv.org/abs/2501.12345",
        mode="both",
    )
    pmap = res["session"]["paper_map"]
    assert pmap["paper_title"] == "Tractable Affine Flows"
    assert len(pmap["sections"]) == 2
    assert len(pmap["algorithms"]) == 1
    assert len(pmap["algorithms"][0]["steps"]) == 2
    assert len(pmap["equations"]) == 1
    assert "$" not in pmap["equations"][0]["mathml"]
    ET.fromstring(pmap["equations"][0]["mathml"])
    assert pmap["equations"][0]["matched_functions"][0]["qualname"].endswith("affine_forward")

    # Verify single-file .gz extraction as well
    gz_single = gzip.compress(main_tex.replace(b"\\input{sec_methods}", methods_tex))
    gz_root = anvil_session._safe_extract_arxiv_bundle(gz_single, tmp_path / "gz_dest")
    assert gz_root is not None and gz_root.is_file()
    assert "\\begin{equation}" in gz_root.read_text(encoding="utf-8")

    # Malicious archives MUST raise ValueError
    malicious_cases = [
        [("../escape.tex", tarfile.REGTYPE, b"bad")],
        [("/abs/escape.tex", tarfile.REGTYPE, b"bad")],
        [("link.tex", tarfile.SYMTYPE, b"../secret.txt")],
        [("hard.tex", tarfile.LNKTYPE, b"../secret.txt")],
        [(".ssh/id_rsa", tarfile.REGTYPE, b"PRIVATE")],
    ]
    for idx, entries in enumerate(malicious_cases):
        bad_bytes = _build_tar_gz_bytes(entries)
        with pytest.raises(ValueError):
            anvil_session._safe_extract_arxiv_bundle(bad_bytes, tmp_path / f"bad_{idx}")


def test_single_scan_start_lazy_migration_persistence_and_compact_summary_get(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    cdir = tmp_path / "polyglot_cockpit"
    (cdir / "pkg").mkdir(parents=True)
    (cdir / "web").mkdir(parents=True)
    (cdir / "pkg" / "core.py").write_text(
        "from pkg.io_mod import load_items\n\n"
        "def compute_total(raw: list[int]) -> int:\n"
        '    """Pure sum over items."""\n'
        "    return sum(load_items(raw))\n",
        encoding="utf-8",
    )
    (cdir / "pkg" / "io_mod.py").write_text(
        "def load_items(vals: list[int]) -> list[int]:\n"
        "    return [int(v) for v in vals]\n",
        encoding="utf-8",
    )
    (cdir / "web" / "ui.mjs").write_text(
        "/** Render numeric badge */\n"
        "export function renderBadge(total) {\n"
        "  return `Total: ${total}`;\n"
        "}\n",
        encoding="utf-8",
    )

    real_build_map = anvil_session.anvil_engine.build_map
    call_counter = {"count": 0}

    def counted_build_map(*args, **kwargs):
        call_counter["count"] += 1
        return real_build_map(*args, **kwargs)

    monkeypatch.setattr(anvil_session.anvil_engine, "build_map", counted_build_map)
    anvil_session.start_cockpit_session(cdir, software_spec=".")
    assert call_counter["count"] == 1, f"Expected exactly 1 build_map scan on start, got {call_counter['count']}"

    # Summary GET must be <15 KB
    sum_res, sum_code = steward_routes.handle_get(str(cdir), "anvil", {"summary": "1"})
    assert sum_code == 200
    assert sum_res["active"] is True
    assert sum_res["summary_only"] is True
    encoded_summary = json.dumps(sum_res).encode("utf-8")
    assert len(encoded_summary) < 15_000

    # Full GET preserves complete session payload
    full_res, full_code = steward_routes.handle_get(str(cdir), "anvil", {})
    assert full_code == 200
    assert full_res["active"] is True
    assert not full_res.get("summary_only")
    assert "conceptual_buckets" in full_res["session"]["code_map"]

    # Lazy migration write-back: strip v2 fields once, verify get_session_status persists them to disk
    sfile = cdir / ".anvil" / "session.json"
    raw_sess = json.loads(sfile.read_text(encoding="utf-8"))
    raw_sess.pop("beta_reader_panel", None)
    raw_sess.pop("walkthrough_trace", None)
    sfile.write_text(json.dumps(raw_sess), encoding="utf-8")

    migrated = anvil_session.get_session_status(cdir)
    assert migrated["session"].get("beta_reader_panel")
    persisted = json.loads(sfile.read_text(encoding="utf-8"))
    assert "beta_reader_panel" in persisted
    assert "walkthrough_trace" in persisted


def test_level3_on_demand_source_endpoint_and_traversal_containment(tmp_path: Path):
    cdir = tmp_path / "source_cockpit"
    (cdir / "pkg").mkdir(parents=True)
    (cdir / "pkg" / "mod.py").write_text(
        "def alpha(x: int) -> int:\n"
        "    return beta(x) + 1\n\n"
        "def beta(y: int) -> int:\n"
        "    return y * 2\n",
        encoding="utf-8",
    )
    (cdir / ".env").write_text("SECRET_KEY=123\n", encoding="utf-8")
    (cdir / "credentials.json").write_text("{}\n", encoding="utf-8")
    outside_file = tmp_path / "outside_secret.py"
    outside_file.write_text("SECRET = 1\n", encoding="utf-8")

    anvil_session.start_cockpit_session(cdir, software_spec=".")

    ok_res, ok_code = steward_routes.handle_get(str(cdir), "anvil/source", {"file": "pkg/mod.py"})
    assert ok_code == 200
    assert ok_res["ok"] is True
    assert "def alpha" in ok_res["numbered_source"]
    assert len(ok_res["symbols"]) == 2

    for bad_target in ("../outside_secret.py", str(outside_file), ".env", "credentials.json"):
        err_res, err_code = steward_routes.handle_get(str(cdir), "anvil/source", {"file": bad_target})
        assert err_code in (400, 403)
        assert err_res["ok"] is False


def test_chat_mirroring_pre_session_discovery_honest_verdicts_and_distro_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    # 1. Pre-session chat MUST NOT raise NameError on discover_cockpit_candidates
    empty_cdir = tmp_path / "empty_cockpit"
    empty_cdir.mkdir()
    (empty_cdir / "app.py").write_text("def greet():\n    return 'hi'\n", encoding="utf-8")
    pre_chat = anvil_session.chat_in_session(empty_cdir, "What local files are available here?")
    assert pre_chat["active"] is False
    assert "app.py" in pre_chat["reply"]

    # 2. Active session starts with honest STATIC_ONLY (validated == False)
    cdir = tmp_path / "honest_cockpit"
    cdir.mkdir()
    (cdir / "calc.py").write_text(
        "def double_val(n: int) -> int:\n"
        '    """Double an integer."""\n'
        "    return n * 2\n",
        encoding="utf-8",
    )
    started = anvil_session.start_cockpit_session(cdir, software_spec=".")
    buckets = started["session"]["code_map"]["conceptual_buckets"]
    assert all(b["validated"] is False for b in buckets)

    # 3. Chat via steward_routes mirrors both John + Anvil reply to Cockpit engine and emits zero fake strings
    emitted: list[dict] = []

    class _StubEngine:
        def _emit(self, evt: dict) -> None:
            emitted.append(evt)

    monkeypatch.setattr(steward_routes, "get_engine", lambda _cdir, create=False: _StubEngine())
    chat_res, chat_code = steward_routes.handle_post(
        str(cdir),
        "anvil",
        {"action": "chat", "question": "What model are you running right now?", "mode": "map"},
    )
    assert chat_code == 200
    reply_txt = chat_res["reply"]
    for banned in ("-ar" + "gon", "-fab" + "le-", "-s" + "ol", "47/" + "47 Hypothesis", "Agreed-" + "Upon"):
        assert banned not in reply_txt
    # Chat must NOT fabricate bucket validation
    after_chat_buckets = chat_res["session"]["code_map"]["conceptual_buckets"]
    assert all(b["validated"] is False for b in after_chat_buckets)
    # Transcript mirror emitted both john and delta
    assert any(e.get("t") == "john" for e in emitted)
    assert any(e.get("t") == "delta" and e.get("text") == reply_txt for e in emitted)

    # 4. Honest probe verdicts: non-zero exit -> DIVERGENCE (validated=False); exit 0 -> EXECUTED_PASS (validated=True)
    bid = after_chat_buckets[0]["id"]
    fail_probe = anvil_session.probe_block_in_session(
        cdir,
        block_id=bid,
        test_cmd=f'"{sys.executable}" -c "import sys; sys.exit(2)"',
    )
    assert fail_probe["inspection"]["validated"] is False
    assert fail_probe["inspection"]["empirical_validation"]["status"] == "DIVERGENCE"

    pass_probe = anvil_session.probe_block_in_session(
        cdir,
        block_id=bid,
        test_cmd=f'"{sys.executable}" -c "import calc; assert calc.double_val(4) == 8"',
    )
    assert pass_probe["inspection"]["validated"] is True
    assert pass_probe["inspection"]["empirical_validation"]["status"] == "EXECUTED_PASS"

    # 5. Distro cleanliness across all modified/bundled Anvil files
    targets = [
        ANCHOR_ROOT / "steward_cockpit" / "anvil_session.py",
        ANCHOR_ROOT / "steward_cockpit" / "steward_routes.py",
        Path(__file__).resolve(),
        *[p for p in sorted(BUNDLED_ANVIL_DIR.rglob("*")) if p.is_file()],
    ]
    pairs = [(p.relative_to(ANCHOR_ROOT).as_posix(), p) for p in targets]
    violations = distro.scan_paths(pairs, root=ANCHOR_ROOT)
    assert violations == [], f"Distro violations detected: {violations}"
