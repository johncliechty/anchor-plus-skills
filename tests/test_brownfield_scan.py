"""Wave 1 — brownfield_scan.py pure scanner/classifier.

Proves IMPLEMENTATION-PLAN.md "## Wave 1":

GIVEN a fixtures folder containing foreman-checkpoint.json, planning/MASTER-PLAN.md,
a root FUNDING-PLAN.md, a vendored paper.pdf under a dir named research/, and
.git/ + .anchor/ + node_modules/ subtrees, WHEN scan() runs, THEN:
  - checkpoint -> by_lane.build
  - MASTER-PLAN.md -> by_lane.planning
  - FUNDING-PLAN.md -> docs (NOT adopted)
  - paper.pdf (under research/, but not report.md/pdf) -> docs (NOT an effort)
  - .git/.anchor/node_modules trees skipped
  - counts match exactly

Robustness: a missing / mistyped path yields an empty ScanResult (no raise/hang).

House style of test_distro_scan.py: planted-fixture tree + @pytest.mark.parametrize
asserting the FULL ScanResult with numeric counts.
"""
import importlib

import pytest

import brownfield_scan as bscan


def _plant(root):
    """Build a realistic brownfield tree under ``root`` and return it."""
    root.mkdir(parents=True, exist_ok=True)
    # Build provenance.
    (root / "foreman-checkpoint.json").write_text('{"wave": 1}', encoding="utf-8")
    (root / "foreman.config.json").write_text('{"x": 1}', encoding="utf-8")
    # Planning provenance under planning/.
    planning = root / "planning"
    planning.mkdir()
    (planning / "MASTER-PLAN.md").write_text("# Master Plan\nbody", encoding="utf-8")
    (planning / "IMPLEMENTATION-PLAN.md").write_text("# Impl\n", encoding="utf-8")
    (planning / "EXECUTION-LOG.md").write_text("# Log\n", encoding="utf-8")
    # Research provenance: report.md/pdf under a research/ store.
    research = root / "research" / "store1"
    research.mkdir(parents=True)
    (research / "report.md").write_text("# Survey\n", encoding="utf-8")
    (research / "report.pdf").write_bytes(b"%PDF-1.4 fake")
    # An incidental vendored paper.pdf under research/ — NOT report.* -> docs.
    (root / "research" / "paper.pdf").write_bytes(b"%PDF-1.4 vendored")
    # A deliverable.
    deliv = root / "deliverables"
    deliv.mkdir()
    (deliv / "spec.md").write_text("# Spec\n", encoding="utf-8")
    # A root generic plan doc -> docs (NOT adopted).
    (root / "FUNDING-PLAN.md").write_text("# Funding\n", encoding="utf-8")
    # Noise that must be SKIPPED entirely.
    for skip in (".git", "node_modules", "_archive", ".anchor"):
        d = root / skip / "deep"
        d.mkdir(parents=True)
        (d / "foreman-checkpoint.json").write_text("{}", encoding="utf-8")
        (d / "MASTER-PLAN.md").write_text("# nope\n", encoding="utf-8")
        (d / "report.md").write_text("# nope\n", encoding="utf-8")
    return root


def test_full_scan_result_and_counts(tmp_path):
    root = _plant(tmp_path / "brown")
    res = bscan.scan(str(root))

    # ── Build lane: both foreman files PLUS the Foreman EXECUTION-LOG (the build
    #    trio doc), even though it lives under planning/ next to the plan docs. ──
    build_rels = {a["rel"] for a in res.by_lane["build"]}
    assert build_rels == {"foreman-checkpoint.json", "foreman.config.json",
                          "planning/EXECUTION-LOG.md"}
    kinds = {a["kind"] for a in res.by_lane["build"]}
    assert "foreman-checkpoint" in kinds and "foreman-config" in kinds
    assert "execlog" in kinds
    execlog = [a for a in res.by_lane["build"]
               if a["rel"] == "planning/EXECUTION-LOG.md"][0]
    assert execlog["kind"] == "execlog"

    # ── Planning lane: the named PLANNING trio docs (NOT the EXECUTION-LOG) ──
    plan_rels = {a["rel"] for a in res.by_lane["planning"]}
    assert plan_rels == {"planning/MASTER-PLAN.md",
                         "planning/IMPLEMENTATION-PLAN.md"}
    assert "planning/EXECUTION-LOG.md" not in plan_rels
    # Title pulled from the first markdown heading.
    mp = [a for a in res.by_lane["planning"]
          if a["rel"] == "planning/MASTER-PLAN.md"][0]
    assert mp["title"] == "Master Plan"
    assert mp["mtime"] > 0

    # ── Research lane: ONLY report.md + report.pdf under research/ ──
    research_rels = {a["rel"] for a in res.by_lane["research"]}
    assert research_rels == {"research/store1/report.md",
                             "research/store1/report.pdf"}

    # ── Deliverables ──
    deliv_rels = {a["rel"] for a in res.by_lane["deliverables"]}
    assert deliv_rels == {"deliverables/spec.md"}

    # ── docs: the incidental paper.pdf + the root FUNDING-PLAN.md, NOT adopted ──
    doc_rels = {a["rel"] for a in res.docs}
    assert "research/paper.pdf" in doc_rels
    assert "FUNDING-PLAN.md" in doc_rels
    # The paper.pdf is NOT an effort in any lane.
    for lane in bscan.LANES:
        assert "research/paper.pdf" not in {a["rel"] for a in res.by_lane[lane]}
        assert "FUNDING-PLAN.md" not in {a["rel"] for a in res.by_lane[lane]}

    # ── Skip subtrees never contributed anything ──
    for art in list(res.all_artifacts()) + list(res.docs):
        for skip in (".git", "node_modules", "_archive", ".anchor"):
            assert not art["rel"].startswith(skip + "/")

    # ── Numeric counts match exactly (EXECUTION-LOG now counts as BUILD, not
    #    planning: build 2→3, planning 3→2; total unchanged) ──
    assert res.counts["build"] == 3
    assert res.counts["planning"] == 2
    assert res.counts["research"] == 2
    assert res.counts["deliverables"] == 1
    assert res.counts["docs"] == 2
    assert res.counts["total"] == 3 + 2 + 2 + 1 + 2


@pytest.mark.parametrize("classify_case", [
    ("foreman-checkpoint.json", "build"),
    ("foreman.config.json", "build"),
    ("planning/IMPLEMENTATION-PLAN.md", "planning"),
    ("planning/DECISION-LOG.md", "planning"),
    ("research/s/report.md", "research"),
    ("research/s/report.pdf", "research"),
    ("deliverables/out.bin", "deliverables"),
    ("FUNDING-PLAN.md", "docs"),
    ("whitepaper.pdf", "docs"),
    ("README.md", None),
    ("src/main.py", None),
    # ── Wave 5: Grass Catchers idea-docs ──
    # A bare PLAN.md stub (e.g. planning/gemini-adapter/PLAN.md) -> grass.
    ("planning/gemini-adapter/PLAN.md", "grass"),
    ("PLAN.md", "grass"),
    # SAVED_FOR_LATER + scoping/ideas notes -> grass.
    ("SAVED_FOR_LATER.md", "grass"),
    ("notes/scoping.md", "grass"),
    # A REAL named trio plan-doc is NEVER grass — it stays planning.
    ("planning/MASTER-PLAN.md", "planning"),
    ("planning/x/IMPLEMENTATION-PLAN.md", "planning"),
])
def test_single_file_classification(tmp_path, classify_case):
    rel, expect = classify_case
    root = tmp_path / "one"
    f = root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    if f.suffix.lower() == ".pdf":
        f.write_bytes(b"%PDF-1.4")
    else:
        f.write_text("# x\n", encoding="utf-8")
    res = bscan.scan(str(root))
    found = None
    for lane in bscan.LANES:
        if rel in {a["rel"] for a in res.by_lane[lane]}:
            found = lane
    if found is None and rel in {a["rel"] for a in res.docs}:
        found = "docs"
    assert found == expect, (rel, found, expect)


@pytest.mark.parametrize("bad", [
    "",
    None,
    "Z:/does/not/exist/at/all",
    "\\\\unc-host-that-does-not-exist\\share\\x",
])
def test_robust_to_missing_or_mistyped_path(bad):
    res = bscan.scan(bad)
    assert isinstance(res, bscan.ScanResult)
    assert res.counts["total"] == 0
    for lane in bscan.LANES:
        assert res.by_lane[lane] == []
    assert res.docs == []


def test_own_anchor_store_is_never_imported(tmp_path):
    """A real effort pointer-record inside .anchor/ must NOT be re-imported as a
    discovered artifact (it would double-count real efforts)."""
    root = tmp_path / "p"
    store = root / ".anchor" / "projects" / "pid1" / "research"
    store.mkdir(parents=True)
    (store / "report.md").write_text("# real\n", encoding="utf-8")
    (store / "e1.pointer.json").write_text("{}", encoding="utf-8")
    res = bscan.scan(str(root))
    assert res.counts["total"] == 0


def test_scan_to_dict_is_json_serializable(tmp_path):
    import json
    root = _plant(tmp_path / "b2")
    res = bscan.scan(str(root))
    d = res.to_dict()
    s = json.dumps(d)  # must not raise
    assert "by_lane" in json.loads(s)


# ── Wave 5: Grass Catchers idea-doc classification ──────────────────────────

def test_idea_docs_classify_into_grass_lane(tmp_path):
    """SAVED_FOR_LATER + an un-run PLAN.md stub => grass; a real MASTER-PLAN.md
    stays planning (never demoted to grass)."""
    root = tmp_path / "grassy"
    root.mkdir()
    # Idea-docs that belong in Grass Catchers.
    (root / "SAVED_FOR_LATER.md").write_text("# Saved\n- idea one\n",
                                             encoding="utf-8")
    stub = root / "planning" / "gemini-adapter"
    stub.mkdir(parents=True)
    (stub / "PLAN.md").write_text("# Gemini adapter PLAN\nstub\n",
                                  encoding="utf-8")
    # A REAL named trio plan-doc must stay planning, NOT grass.
    (root / "planning" / "MASTER-PLAN.md").write_text("# Master Plan\nreal\n",
                                                      encoding="utf-8")

    res = bscan.scan(str(root))

    grass_rels = {a["rel"] for a in res.by_lane["grass"]}
    assert "SAVED_FOR_LATER.md" in grass_rels
    assert "planning/gemini-adapter/PLAN.md" in grass_rels

    plan_rels = {a["rel"] for a in res.by_lane["planning"]}
    assert "planning/MASTER-PLAN.md" in plan_rels
    # The real trio plan-doc is NOT in grass.
    assert "planning/MASTER-PLAN.md" not in grass_rels
    # Idea-docs are NOT masqueraded as planning.
    assert "SAVED_FOR_LATER.md" not in plan_rels
    assert "planning/gemini-adapter/PLAN.md" not in plan_rels

    # Counts include the grass lane in the total.
    assert res.counts["grass"] == 2
    assert res.counts["planning"] == 1


def test_grass_doc_kind_is_idea_doc(tmp_path):
    root = tmp_path / "g2"
    root.mkdir()
    (root / "PLAN.md").write_text("# stub\n", encoding="utf-8")
    res = bscan.scan(str(root))
    grass = res.by_lane["grass"]
    assert len(grass) == 1
    assert grass[0]["kind"] == "idea-doc"
    assert grass[0]["lane"] == "grass"
