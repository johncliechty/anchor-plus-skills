"""foundry-v2 Wave 4 — re-express gandalf on the runner + prove on jumper.

Proves the Wave-4 done-when:
  (a) gandalf-on-runner OUTPUT PARITY vs. the legacy adapter — for the same
      fixture project (same Stage-A stub, same Stage-B host, same env seams)
      the graded output produced through the generic runner is BYTE-IDENTICAL
      to the ``advisor-output.json`` the legacy ``run_gandalf`` stored (the
      Stage-B host stub grades as a function of its stdin, so a single drifted
      byte in the draft or its serialization fails the test);
  (b) jumper — which COMPOSES gandalf, the hard case — runs END-TO-END via its
      manifest registry entry: the composed gandalf leg runs FIRST through the
      same generic runner (journaling into gandalf's own skill dir), its
      graded output folded into jumper's host payload;
  (c) the 3rd skill (financial-analyst) is wired in PURE DATA under the
      DECLARED line budget (``THIRD_SKILL_LINE_BUDGET``) — no executor, no
      composition, just a manifest;
  (d) all three AUTO-JOURNAL via the runner's Wave-2 seam, and NONE imports or
      executes skill code to be DISCOVERED (declare-then-resolve stays pure
      data; the import traps stay un-sprung).

Hermetic like tests/test_foundry_skill_runner_w3.py + test_gandalf_mapreduce_w9.py:
temp ``ANCHOR_DATA_DIR``, temp skill dirs, ``ANCHOR_RUNNER_CMD`` →
``stub_gandalf_draft.py`` (canned Stage-A raw draft), stub Stage-B/jumper/3rd
hosts written to tmp_path and run via ``sys.executable``. NEVER real claude /
real node / the real Skill Foundry / :8777. Stdlib only.
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

_TESTS = Path(__file__).resolve().parent
DRAFT_STUB = (_TESTS / "stub_gandalf_draft.py").as_posix()


# ── Stub hosts (written to tmp_path; run via sys.executable) ─────────────────

#: Stage-B host whose graded output is a FUNCTION OF ITS STDIN (sha256 of the
#: raw-draft bytes + the draft's own content) — the byte-parity instrument: if
#: the runner path feeds a draft that differs by ONE byte from the legacy
#: adapter's, the graded outputs diverge and the parity test fails.
_PARITY_HOST = """\
import hashlib, json, sys
raw = sys.stdin.read()
draft = json.loads(raw)
graded = {
    "schema_version": "1",
    "cross_model": False,
    "degraded": False,
    "reasoning": "graded from draft sha256:"
                 + hashlib.sha256(raw.encode("utf-8")).hexdigest(),
    "verdict": str(draft.get("verdict") or "")[:200],
    "findings": draft.get("findings") or [],
    "nitpicks": draft.get("nitpicks") or [],
    "elevations": draft.get("elevations") or [],
    "risk_labels": [{"leg": "diagnose", "tier": "SPECULATIVE",
                     "rung": "OBSERVED"}],
}
print(json.dumps(graded, indent=2, ensure_ascii=False))
"""

#: Jumper's own host: REFUSES (exit 1) unless the composed gandalf graded
#: output was actually delivered on stdin — proving the composition really ran
#: through the runner, not that jumper improvised without it.
_JUMPER_HOST = """\
import json, sys
payload = json.loads(sys.stdin.read() or "{}")
composed = payload.get("composed") or {}
gandalf = composed.get("gandalf")
if not isinstance(gandalf, dict) or "verdict" not in gandalf \\
        or "findings" not in gandalf:
    sys.stderr.write("jumper host: composed gandalf output missing\\n")
    sys.exit(1)
print(json.dumps({
    "schema": "jumper-v1",
    "verdict": "ideation grounded on the composed gandalf read",
    "gandalf_verdict": gandalf.get("verdict"),
    "ideas": [{"id": "i-1", "title": "one grounded idea"}],
}, ensure_ascii=False))
"""

#: The 3rd skill's host — a trivial JSON emitter (its wiring, not its host,
#: is what Wave 4 proves).
_THIRD_HOST = """\
import json, sys
payload = json.loads(sys.stdin.read() or "null")
print(json.dumps({"schema": "fa-v1", "verdict": "penny-exact tie-out",
                  "echo": payload}, ensure_ascii=False))
"""

#: A minimal contract-satisfying host for the cycle fixtures.
_ECHO_HOST = """\
import json, sys
_ = sys.stdin.read()
print(json.dumps({"schema": "echo-v1", "verdict": "fine"}))
"""

#: A module in a skill dir that would prove ILLEGAL import of skill code.
_IMPORT_TRAP = """\
from pathlib import Path
Path(__file__).with_name("IMPORT-TRAP-SPRUNG").write_text("sprung")
raise RuntimeError("skill code was imported by the wave-4 registry")
"""


def _make_skill_dir(tmp_path, name):
    d = tmp_path / ("skills-" + name)
    d.mkdir()
    (d / "SKILL.md").write_text("# %s protocol\nDeep-think per contract.\n"
                                % name, encoding="utf-8")
    (d / "evil_import.py").write_text(_IMPORT_TRAP, encoding="utf-8")
    return d


def _make_host(tmp_path, name, body):
    stub = tmp_path / ("%s_host_w4.py" % name)
    stub.write_text(body, encoding="utf-8")
    return "%s %s" % (Path(sys.executable).as_posix(), stub.as_posix())


def _journal_entries(skill_dir: Path) -> list:
    return sorted((Path(skill_dir) / "journal").glob("*.md"))


def _entry_for(skill_dir: Path, run_id: str):
    p = Path(skill_dir) / "journal" / (str(run_id) + ".md")
    assert p.is_file(), "no journal entry for run %s in %s" % (run_id,
                                                               skill_dir)
    return p.read_text(encoding="utf-8")


@pytest.fixture
def w4(tmp_path, monkeypatch):
    """The hermetic Wave-4 rig: temp data dir + temp skill dirs + stub hosts,
    all product modules reloaded against the temp env (the W9 pattern)."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    gandalf_skill = _make_skill_dir(tmp_path, "gandalf")
    jumper_skill = _make_skill_dir(tmp_path, "jumper")
    third_skill = _make_skill_dir(tmp_path, "financial-analyst")

    parity_cmd = _make_host(tmp_path, "gandalf", _PARITY_HOST)
    jumper_cmd = _make_host(tmp_path, "jumper", _JUMPER_HOST)
    third_cmd = _make_host(tmp_path, "third", _THIRD_HOST)

    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    # Even DEFAULT manifest paths must resolve inside tmp — never the real
    # Skill Foundry (pure string work either way, but hermetic by construction).
    monkeypatch.setenv("ANCHOR_SKILLS_ROOT", str(tmp_path / "skills-root"))
    monkeypatch.setenv("ANCHOR_RUNNER_CMD",
                       f"{Path(sys.executable).as_posix()} {DRAFT_STUB}")
    monkeypatch.setenv("ANCHOR_GANDALF_HOST_CMD", parity_cmd)
    monkeypatch.setenv("ANCHOR_GANDALF_SKILL_DIR", str(gandalf_skill))
    monkeypatch.setenv("ANCHOR_PROACTIVE_SUMMARY", "")
    # Parity is about the STAGED PIPELINE, not the fusion feature — the fusion
    # pass has its own gates; single-shard fixtures skip it anyway.
    monkeypatch.setenv("ANCHOR_GANDALF_FUSION", "0")
    # Byte-parity is against the LEGACY two-stage adapter. master flipped
    # run_gandalf's DEFAULT to the AGENTIC single-job path (DEFAULT_MODE=
    # agentic); pin the legacy map-reduce path this fixture's draft+host
    # stubs implement so `legacy` is the intended two-stage run.
    monkeypatch.setenv("ANCHOR_GANDALF_MODE", "mapreduce")
    monkeypatch.delenv("STUB_GANDALF_DRAFT", raising=False)

    import paths
    importlib.reload(paths)
    import job_runner
    importlib.reload(job_runner)
    import summarizer
    importlib.reload(summarizer)
    import gandalf
    gandalf = importlib.reload(gandalf)
    import foundry_decisions
    importlib.reload(foundry_decisions)
    import foundry_journal
    foundry_journal = importlib.reload(foundry_journal)
    import skill_runner
    skill_runner = importlib.reload(skill_runner)
    import foundry_skills
    foundry_skills = importlib.reload(foundry_skills)

    proj = tmp_path / "proj"
    proj.mkdir()
    (proj / "README.md").write_text("# fixture project\n", encoding="utf-8")

    return {
        "gd": gandalf, "fs": foundry_skills, "sr": skill_runner,
        "fj": foundry_journal,
        "gandalf_skill": gandalf_skill, "jumper_skill": jumper_skill,
        "third_skill": third_skill,
        "jumper_cmd": jumper_cmd, "third_cmd": third_cmd,
        "proj": proj, "tmp": tmp_path,
    }


def _registry_dispatch(w4):
    """The full 3-skill registry dispatch, every entry on temp dirs + stubs."""
    fs = w4["fs"]
    manifests = fs.registry_manifests(overrides={
        # gandalf: defaults already resolve to the temp env seams.
        "jumper": {"skill_dir": w4["jumper_skill"],
                   "host_cmd": w4["jumper_cmd"],
                   "output_contract": {"format": "json",
                                       "required_keys": ["schema", "verdict"]}},
        fs.THIRD_SKILL: {"skill_dir": w4["third_skill"],
                         "host_cmd": w4["third_cmd"]},
    })
    return fs.build_registry_dispatch(manifests)


# ── (a) gandalf re-expressed: byte-parity vs. the legacy adapter ─────────────

def test_gandalf_on_runner_byte_parity_with_legacy(w4):
    gd, fs = w4["gd"], w4["fs"]
    # Legacy adapter: the full two-stage run, artifacts stored on disk.
    legacy = gd.run_gandalf(str(w4["proj"]), "pid-parity-w4")
    assert legacy["ok"] is True
    advisor = (w4["proj"] / gd.GANDALF_DIRNAME / legacy["run_id"]
               / gd.ADVISOR_OUTPUT_JSON)
    legacy_text = advisor.read_text(encoding="utf-8")

    # The runner expression: the SAME env seams resolve the manifest defaults.
    dispatch = fs.build_registry_dispatch([fs.gandalf_manifest()])
    out = fs.run_skill(dispatch, "gandalf",
                       payload={"folder": str(w4["proj"])})
    assert out["ok"] is True and out["outcome"] == "done"

    # BYTE parity on the graded output (the host grades from its stdin bytes,
    # so this also proves the draft + its serialization were identical).
    runner_text = json.dumps(out["output"], indent=2, ensure_ascii=False)
    assert runner_text == legacy_text
    assert out["output"] == json.loads(legacy_text)


def test_gandalf_stage_b_parity_on_explicit_draft(w4):
    """The tight parity leg: the SAME explicit raw draft through the legacy
    ``_run_stage_b`` and through the runner path grades identically."""
    gd, fs = w4["gd"], w4["fs"]
    draft = {"reasoning": "fixed", "verdict": "fixture verdict",
             "findings": [{"id": "d-1", "verdict": "x", "group": "(root)"}],
             "nitpicks": [], "elevations": []}
    legacy_graded, reason = gd._run_stage_b(dict(draft))
    assert reason is None

    dispatch = fs.build_registry_dispatch([fs.gandalf_manifest()])
    out = fs.run_skill(dispatch, "gandalf", payload={"raw_draft": dict(draft)})
    assert out["ok"] is True
    assert out["output"] == legacy_graded
    assert (json.dumps(out["output"], indent=2, ensure_ascii=False)
            == json.dumps(legacy_graded, indent=2, ensure_ascii=False))


def test_gandalf_on_runner_journals_the_run(w4):
    fs, fj = w4["fs"], w4["fj"]
    dispatch = fs.build_registry_dispatch([fs.gandalf_manifest()])
    out = fs.run_skill(dispatch, "gandalf",
                       payload={"folder": str(w4["proj"])})
    assert out["ok"] is True
    parsed = fj.parse_entry(_entry_for(w4["gandalf_skill"], out["run_id"]))
    assert fj.validate_entry(parsed) == []
    assert parsed["provenance"].startswith("host-enforced:")
    assert parsed["outcome_linkage"]["outcome"] == "done"
    assert parsed["outcome_linkage"]["skill"] == "gandalf"


def test_gandalf_stage_a_failure_is_honest_and_journaled(w4, monkeypatch):
    fs, fj = w4["fs"], w4["fj"]
    monkeypatch.setenv("STUB_GANDALF_DRAFT", "UNPARSEABLE")
    dispatch = fs.build_registry_dispatch([fs.gandalf_manifest()])
    out = fs.run_skill(dispatch, "gandalf",
                       payload={"folder": str(w4["proj"])})
    assert out["ok"] is False and out["outcome"] == "failed"
    assert "stage-a-unparseable-draft" in out["reason"]
    parsed = fj.parse_entry(_entry_for(w4["gandalf_skill"], out["run_id"]))
    assert parsed["outcome_linkage"]["outcome"] == "failed"
    assert "stage-a-unparseable-draft" in parsed["outcome_linkage"]["reason"]


# ── (b) jumper — composes gandalf, end-to-end via its manifest ───────────────

def test_jumper_runs_end_to_end_composing_gandalf(w4):
    fs = w4["fs"]
    dispatch = _registry_dispatch(w4)
    before = len(_journal_entries(w4["gandalf_skill"]))
    out = fs.run_skill(dispatch, "jumper",
                       payload={"folder": str(w4["proj"])})
    assert out["ok"] is True and out["outcome"] == "done"
    # Jumper's host really received the composed gandalf graded output (it
    # exits 1 otherwise) and grounded its result on it.
    assert out["output"]["schema"] == "jumper-v1"
    assert out["output"]["gandalf_verdict"], "composed verdict not delivered"
    # The composed leg ran through the RUNNER: gandalf journaled its own run.
    assert len(_journal_entries(w4["gandalf_skill"])) == before + 1


def test_jumper_and_composed_gandalf_both_journal(w4):
    fs, fj = w4["fs"], w4["fj"]
    dispatch = _registry_dispatch(w4)
    out = fs.run_skill(dispatch, "jumper",
                       payload={"folder": str(w4["proj"])})
    assert out["ok"] is True
    parsed = fj.parse_entry(_entry_for(w4["jumper_skill"], out["run_id"]))
    assert fj.validate_entry(parsed) == []
    assert parsed["outcome_linkage"]["skill"] == "jumper"
    assert parsed["provenance"].startswith("host-enforced:")
    # gandalf's leg journaled under ITS OWN skill dir (composition never
    # relabels provenance).
    gj = [fj.parse_entry(p.read_text(encoding="utf-8"))
          for p in _journal_entries(w4["gandalf_skill"])]
    assert any(e["outcome_linkage"].get("skill") == "gandalf"
               and e["outcome_linkage"].get("outcome") == "done" for e in gj)


def test_jumper_fails_honestly_when_composed_gandalf_fails(w4, monkeypatch):
    fs, fj = w4["fs"], w4["fj"]
    monkeypatch.setenv("STUB_GANDALF_DRAFT", "UNPARSEABLE")  # break the leg
    dispatch = _registry_dispatch(w4)
    out = fs.run_skill(dispatch, "jumper",
                       payload={"folder": str(w4["proj"])})
    assert out["ok"] is False and out["outcome"] == "failed"
    assert "composed-skill-failed:gandalf" in out["reason"]
    # BOTH legs journaled their honest failures.
    parsed = fj.parse_entry(_entry_for(w4["jumper_skill"], out["run_id"]))
    assert parsed["outcome_linkage"]["outcome"] == "failed"
    gj = [fj.parse_entry(p.read_text(encoding="utf-8"))
          for p in _journal_entries(w4["gandalf_skill"])]
    assert any(e["outcome_linkage"].get("outcome") == "failed" for e in gj)


def test_composition_cycle_is_refused_not_infinite(w4):
    fs = w4["fs"]
    a_dir = _make_skill_dir(w4["tmp"], "alpha")
    b_dir = _make_skill_dir(w4["tmp"], "beta")
    host = _make_host(w4["tmp"], "echo", _ECHO_HOST)

    def _m(name, skill_dir, composes):
        return {
            "skill": name, "skill_dir": str(skill_dir), "op_kind": "run",
            "host_cmd": host, "composes": composes,
            "output_contract": {"format": "json"},
            "panel": {"title": name}, "journal": {"enabled": True},
            "tier": "standard", "capabilities": [],
            "activation": {"trigger": "first_run"},
        }

    dispatch = fs.build_registry_dispatch(
        [_m("alpha", a_dir, ["beta"]), _m("beta", b_dir, ["alpha"])])
    out = fs.run_skill(dispatch, "alpha")
    assert out["ok"] is False and out["outcome"] == "failed"
    assert "composition-cycle" in out["reason"]


def test_unknown_executor_kind_breaks_loudly(w4):
    fs = w4["fs"]
    m = fs.third_skill_manifest(skill_dir=w4["third_skill"],
                                host_cmd=w4["third_cmd"],
                                executor="warp-drive")
    dispatch = fs.build_registry_dispatch([m])
    with pytest.raises(ValueError) as e:
        fs.run_skill(dispatch, fs.THIRD_SKILL)
    assert "warp-drive" in str(e.value)


# ── (c) the 3rd skill: pure-data wiring under the declared line budget ───────

def test_third_skill_wiring_under_declared_line_budget(w4):
    fs = w4["fs"]
    lines = fs.third_skill_wiring_lines()
    assert 0 < lines <= fs.THIRD_SKILL_LINE_BUDGET, (
        "3rd-skill wiring is %d lines, over the declared budget of %d"
        % (lines, fs.THIRD_SKILL_LINE_BUDGET))


def test_third_skill_is_pure_data_and_runs_on_default_path(w4):
    fs, fj = w4["fs"], w4["fj"]
    dispatch = _registry_dispatch(w4)
    # Pure data: no executor kind, no composition — the runner's default path.
    assert fs.resolve_executor(dispatch, fs.THIRD_SKILL) is None
    out = fs.run_skill(dispatch, fs.THIRD_SKILL, payload={"deal": "series-a"})
    assert out["ok"] is True and out["outcome"] == "done"
    assert out["output"]["schema"] == "fa-v1"
    assert out["output"]["echo"] == {"deal": "series-a"}
    parsed = fj.parse_entry(_entry_for(w4["third_skill"], out["run_id"]))
    assert fj.validate_entry(parsed) == []
    assert parsed["outcome_linkage"]["skill"] == fs.THIRD_SKILL


# ── (d) all three journal; discovery imports no skill code ───────────────────

def test_all_three_auto_journal_via_the_runner_seam(w4):
    fs, fj = w4["fs"], w4["fj"]
    dispatch = _registry_dispatch(w4)
    runs = {
        "gandalf": fs.run_skill(dispatch, "gandalf",
                                payload={"folder": str(w4["proj"])}),
        "jumper": fs.run_skill(dispatch, "jumper",
                               payload={"folder": str(w4["proj"])}),
        fs.THIRD_SKILL: fs.run_skill(dispatch, fs.THIRD_SKILL),
    }
    dirs = {"gandalf": w4["gandalf_skill"], "jumper": w4["jumper_skill"],
            fs.THIRD_SKILL: w4["third_skill"]}
    for name, out in runs.items():
        assert out["ok"] is True, "%s: %s" % (name, out["reason"])
        parsed = fj.parse_entry(_entry_for(dirs[name], out["run_id"]))
        assert fj.validate_entry(parsed) == []
        assert parsed["provenance"].startswith("host-enforced:")
        assert parsed["outcome_linkage"]["skill"] == name
        assert parsed["outcome_linkage"]["run_id"] == out["run_id"]


def test_registry_discovery_imports_no_skill_code(w4):
    fs = w4["fs"]
    dispatch = _registry_dispatch(w4)
    assert set(dispatch) == {"gandalf", "jumper", fs.THIRD_SKILL}
    # Declare-then-resolve stayed pure data: nothing activated, nothing ran,
    # nothing imported — every trap un-sprung.
    for entry in dispatch.values():
        assert entry["activated"] is False
        assert entry["protocol"] is None
    for d in (w4["gandalf_skill"], w4["jumper_skill"], w4["third_skill"]):
        assert not (d / "IMPORT-TRAP-SPRUNG").exists()
        assert not _journal_entries(d)  # no run ⇒ no journal side-effects
    assert "evil_import" not in sys.modules


def test_registry_manifests_are_schema_valid(w4):
    fs, sr = w4["fs"], w4["sr"]
    for m in fs.registry_manifests():
        assert sr.validate_manifest(m) == [], m.get("skill")
