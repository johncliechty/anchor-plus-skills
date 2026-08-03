"""foundry-v2 Wave 3 — the generic manifest-driven skill_runner core.

Proves the Wave-3 done-when:
  (a) the runner builds its dispatch table from per-skill manifests WITHOUT
      importing or executing any skill code (declare-then-resolve is pure
      data — a booby-trapped skill dir stays un-sprung);
  (b) lazy activation fires ONLY on the manifest's declared trigger
      (``first_run`` / ``explicit`` / ``on_event``), and activation itself
      never runs the host;
  (c) a ``mutate`` op without a valid single-use confirm token, or with a
      write target outside its declared ``write_scope``, is REFUSED;
plus the Wave-2 journaling seam moved into the runner: every dispatched op —
done, failed, or refused, mutate included — auto-appends a schema-valid
7-field skeleton entry through ``foundry_journal``.

Hermetic like tests/test_foundry_journal_w2.py: temp skill dirs, stub host
scripts written to tmp_path and run via ``sys.executable``. NEVER real
claude / real node / the real Skill Foundry / :8777. Stdlib only.
"""
import json
import sys
from pathlib import Path

import pytest

import foundry_decisions as _fd
import foundry_journal as _fj
import skill_runner as sr


# ── Fixture helpers ──────────────────────────────────────────────────────────

#: A host stub that PROVES execution (writes a canary line) then emits a
#: contract-satisfying JSON object echoing its stdin payload.
_HOST_STUB = """\
import json, sys
from pathlib import Path
canary = Path(sys.argv[1])
with canary.open("a", encoding="utf-8") as f:
    f.write("executed\\n")
raw = sys.stdin.read()
payload = json.loads(raw) if raw.strip() else None
print("host chatter before the payload")
print(json.dumps({"schema": "stub-v1", "verdict": "stub verdict fine",
                  "echo": payload}))
"""

#: A host stub that fails honestly (non-zero exit + stderr reason).
_FAILING_STUB = """\
import sys
sys.stderr.write("stub host exploded\\n")
sys.exit(3)
"""

#: A module in the skill dir that would prove ILLEGAL import of skill code.
_IMPORT_TRAP = """\
from pathlib import Path
Path(__file__).with_name("IMPORT-TRAP-SPRUNG").write_text("sprung")
raise RuntimeError("skill code was imported by the runner")
"""


def _make_skill_dir(tmp_path, name):
    d = tmp_path / name
    d.mkdir()
    (d / "SKILL.md").write_text("# %s protocol\nDeep-think per contract.\n"
                                % name, encoding="utf-8")
    (d / "evil_import.py").write_text(_IMPORT_TRAP, encoding="utf-8")
    return d


def _make_host(tmp_path, name, body=_HOST_STUB):
    """Write a stub host script + its execution canary → (host_cmd, canary)."""
    stub = tmp_path / ("%s_host.py" % name)
    stub.write_text(body, encoding="utf-8")
    canary = tmp_path / ("%s_canary.txt" % name)
    host_cmd = "%s %s %s" % (Path(sys.executable).as_posix(),
                             stub.as_posix(), canary.as_posix())
    return host_cmd, canary


def _executions(canary: Path) -> int:
    if not canary.exists():
        return 0
    return len(canary.read_text(encoding="utf-8").splitlines())


def _manifest(skill, skill_dir, host_cmd, **over):
    m = {
        "skill": skill,
        "skill_dir": str(skill_dir),
        "op_kind": "run",
        "host_cmd": host_cmd,
        "output_contract": {"format": "json",
                            "required_keys": ["schema", "verdict"]},
        "panel": {"title": skill.title(), "icon": "🧪"},
        "journal": {"enabled": True},
        "tier": "standard",
        "capabilities": [],
        "activation": {"trigger": "first_run"},
    }
    m.update(over)
    return m


@pytest.fixture
def rig(tmp_path):
    """One declared run-kind skill with a canaried stub host."""
    skill_dir = _make_skill_dir(tmp_path, "demo")
    host_cmd, canary = _make_host(tmp_path, "demo")
    manifest = _manifest("demo", skill_dir, host_cmd)
    return {"skill_dir": skill_dir, "canary": canary, "manifest": manifest}


def _journal_entries(skill_dir: Path) -> list:
    return sorted((skill_dir / "journal").glob("*.md"))


# ── Manifest schema (the Wave-3 schema gen_manifest validates against) ───────

def test_validate_manifest_good(rig):
    assert sr.validate_manifest(rig["manifest"]) == []


@pytest.mark.parametrize("mutation,fragment", [
    ({"skill": ""}, "skill name"),
    ({"skill_dir": ""}, "skill_dir"),
    ({"op_kind": "freestyle"}, "op_kind"),
    ({"host_cmd": ""}, "host_cmd"),
    ({"host_cmd": None}, "host_cmd"),
    ({"output_contract": None}, "output_contract"),
    ({"output_contract": {"format": "yaml"}}, "output_contract.format"),
    ({"output_contract": {"format": "text", "required_keys": ["x"]}},
     "required_keys"),
    ({"panel": {}}, "panel"),
    ({"journal": None}, "journal"),
    ({"journal": {"enabled": False}}, "host-enforced"),
    ({"journal": {"provenance": "self-reported:me"}}, "provenance"),
    ({"tier": "hobbyist"}, "tier"),
    ({"capabilities": None}, "capabilities"),
    ({"capabilities": ["teleport:anywhere"]}, "capability"),
    ({"activation": {"trigger": "whenever"}}, "activation.trigger"),
    ({"activation": {"trigger": "on_event"}}, "event"),
    ({"op_kind": "mutate"}, "write_scope"),
    ({"timeout_s": -5}, "timeout_s"),
])
def test_validate_manifest_rejects(rig, mutation, fragment):
    bad = dict(rig["manifest"])
    bad.update(mutation)
    problems = sr.validate_manifest(bad)
    assert problems, "expected schema problems for %r" % (mutation,)
    assert any(fragment in p for p in problems), problems


# ── (a) declare-then-resolve: dispatch built WITHOUT executing skill code ────

def test_dispatch_built_without_executing_skill_code(rig):
    dispatch = sr.build_dispatch([rig["manifest"]])
    entry = dispatch["demo"]
    # Resolved from data alone: argv split, entry populated, NOT activated.
    assert entry["op_kind"] == "run"
    assert entry["activated"] is False
    assert entry["protocol"] is None
    assert Path(sys.executable).name in Path(entry["argv"][0]).name
    # No skill code ran or was imported: both traps stayed un-sprung.
    assert _executions(rig["canary"]) == 0
    assert not (rig["skill_dir"] / "IMPORT-TRAP-SPRUNG").exists()
    assert "evil_import" not in sys.modules


def test_host_cmd_skill_dir_placeholder_resolves(rig):
    m = dict(rig["manifest"])
    m["host_cmd"] = "python {skill_dir}/runtime/host.mjs"
    dispatch = sr.build_dispatch([m])
    assert dispatch["demo"]["argv"][1] == \
        "%s/runtime/host.mjs" % rig["skill_dir"]


def test_build_dispatch_loud_on_invalid_and_duplicate(rig):
    bad = dict(rig["manifest"])
    bad["tier"] = "hobbyist"
    with pytest.raises(ValueError) as e:
        sr.build_dispatch([bad])
    assert "tier" in str(e.value)
    with pytest.raises(ValueError) as e:
        sr.build_dispatch([rig["manifest"], dict(rig["manifest"])])
    assert "duplicate" in str(e.value)


def test_discover_manifests_from_disk(tmp_path):
    root = tmp_path / "skills"
    root.mkdir()
    for name in ("alpha", "beta"):
        d = _make_skill_dir(root, name)
        host_cmd, _ = _make_host(tmp_path, name)
        m = _manifest(name, d, host_cmd)
        del m["skill_dir"]  # defaulted from the dir it is read from
        (d / sr.MANIFEST_FILENAME).write_text(json.dumps(m), encoding="utf-8")
    manifests = sr.discover_manifests(root)
    assert [m["skill"] for m in manifests] == ["alpha", "beta"]
    dispatch = sr.build_dispatch(manifests)
    assert set(dispatch) == {"alpha", "beta"}
    assert dispatch["alpha"]["skill_dir"] == str(root / "alpha")
    assert all(not e["activated"] for e in dispatch.values())
    # Discovery is declare-only: nothing ran, nothing imported.
    assert not (root / "alpha" / "IMPORT-TRAP-SPRUNG").exists()


def test_load_skill_manifest_loud_on_broken_file(tmp_path):
    d = tmp_path / "broken"
    d.mkdir()
    with pytest.raises(ValueError):
        sr.load_skill_manifest(d)  # missing manifest.json
    (d / sr.MANIFEST_FILENAME).write_text("{not json", encoding="utf-8")
    with pytest.raises(ValueError):
        sr.load_skill_manifest(d)


# ── (b) lazy activation fires only on the declared trigger ───────────────────

def test_first_run_trigger_activates_on_first_op(rig):
    dispatch = sr.build_dispatch([rig["manifest"]])
    assert dispatch["demo"]["activated"] is False
    out = sr.run_op(dispatch, "demo", payload={"q": 1})
    assert out["ok"] is True and out["outcome"] == "done"
    assert dispatch["demo"]["activated"] is True
    # Activation read the skill's OWN protocol (consume, never fork).
    assert "demo protocol" in dispatch["demo"]["protocol"]
    assert out["output"]["echo"] == {"q": 1}
    assert _executions(rig["canary"]) == 1


def test_on_event_trigger_ignores_other_events(rig):
    m = dict(rig["manifest"])
    m["activation"] = {"trigger": "on_event", "event": "project_open"}
    dispatch = sr.build_dispatch([m])
    # Not activated → a dispatched op is refused, not silently activated.
    out = sr.run_op(dispatch, "demo")
    assert out["refused"] is True
    assert "not-activated" in out["reason"]
    # The WRONG event does not activate.
    assert sr.notify_event(dispatch, "some_other_event") == []
    assert dispatch["demo"]["activated"] is False
    # The DECLARED event activates — and activation alone never runs the host.
    assert sr.notify_event(dispatch, "project_open") == ["demo"]
    assert dispatch["demo"]["activated"] is True
    assert _executions(rig["canary"]) == 0
    out = sr.run_op(dispatch, "demo")
    assert out["ok"] is True
    assert _executions(rig["canary"]) == 1


def test_explicit_trigger_requires_activate_skill(rig):
    m = dict(rig["manifest"])
    m["activation"] = {"trigger": "explicit"}
    dispatch = sr.build_dispatch([m])
    out = sr.run_op(dispatch, "demo")
    assert out["refused"] is True and "not-activated" in out["reason"]
    assert _executions(rig["canary"]) == 0
    entry = sr.activate_skill(dispatch, "demo")
    assert entry["activated"] is True
    assert _executions(rig["canary"]) == 0  # activation ≠ execution
    assert sr.run_op(dispatch, "demo")["ok"] is True


def test_preflight_probe_refuses_unsatisfied_capability(rig, monkeypatch):
    m = dict(rig["manifest"])
    m["capabilities"] = ["exec:definitely-not-a-real-binary-w3",
                         "env:W3_PROBE_VAR"]
    dispatch = sr.build_dispatch([m])
    out = sr.run_op(dispatch, "demo")
    assert out["refused"] is True
    assert out["reason"].startswith("preflight:")
    assert "definitely-not-a-real-binary-w3" in out["reason"]
    assert "W3_PROBE_VAR" in out["reason"]
    assert _executions(rig["canary"]) == 0
    # Satisfiable capabilities pass the probe (runtime = per-op re-check).
    m2 = dict(rig["manifest"])
    m2["capabilities"] = ["env:W3_PROBE_VAR", "read:SKILL.md"]
    monkeypatch.setenv("W3_PROBE_VAR", "1")
    dispatch2 = sr.build_dispatch([m2])
    assert sr.run_op(dispatch2, "demo")["ok"] is True


def test_unknown_skill_refused():
    out = sr.run_op({}, "ghost")
    assert out["ok"] is False and out["refused"] is True
    assert "unknown-skill" in out["reason"]


# ── (c) the mutate gate: confirm token + declared write-scope ────────────────

@pytest.fixture
def mutate_rig(tmp_path):
    skill_dir = _make_skill_dir(tmp_path, "mutator")
    host_cmd, canary = _make_host(tmp_path, "mutator")
    scope = tmp_path / "scope"
    scope.mkdir()
    manifest = _manifest("mutator", skill_dir, host_cmd,
                         op_kind="mutate", write_scope=[str(scope)])
    dispatch = sr.build_dispatch([manifest])
    return {"dispatch": dispatch, "scope": scope, "canary": canary,
            "skill_dir": skill_dir}


def test_mutate_without_token_refused(mutate_rig):
    d, scope = mutate_rig["dispatch"], mutate_rig["scope"]
    out = sr.run_op(d, "mutator", write_targets=[str(scope / "f.md")])
    assert out["refused"] is True and out["reason"] == "confirm-token-missing"
    out = sr.run_op(d, "mutator", confirm_token="confirm-forged",
                    write_targets=[str(scope / "f.md")])
    assert out["refused"] is True and out["reason"] == "confirm-token-invalid"
    # A token minted for a DIFFERENT skill does not authorize this one.
    other = sr.issue_confirm_token("some-other-skill")
    out = sr.run_op(d, "mutator", confirm_token=other,
                    write_targets=[str(scope / "f.md")])
    assert out["refused"] is True
    assert out["reason"] == "confirm-token-wrong-skill"
    assert _executions(mutate_rig["canary"]) == 0


def test_mutate_token_is_single_use(mutate_rig):
    d, scope = mutate_rig["dispatch"], mutate_rig["scope"]
    token = sr.issue_confirm_token("mutator")
    out = sr.run_op(d, "mutator", confirm_token=token,
                    write_targets=[str(scope / "f.md")])
    assert out["ok"] is True and out["outcome"] == "done"
    assert _executions(mutate_rig["canary"]) == 1
    # The approval is SPENT: replaying the same token is refused.
    out = sr.run_op(d, "mutator", confirm_token=token,
                    write_targets=[str(scope / "f.md")])
    assert out["refused"] is True and out["reason"] == "confirm-token-invalid"
    assert _executions(mutate_rig["canary"]) == 1


def test_mutate_expired_token_refused(mutate_rig):
    d, scope = mutate_rig["dispatch"], mutate_rig["scope"]
    token = sr.issue_confirm_token("mutator", ttl_s=-1)  # already stale
    out = sr.run_op(d, "mutator", confirm_token=token,
                    write_targets=[str(scope / "f.md")])
    assert out["refused"] is True and out["reason"] == "confirm-token-expired"


def test_mutate_write_scope_enforced(mutate_rig, tmp_path):
    d, scope = mutate_rig["dispatch"], mutate_rig["scope"]
    token = sr.issue_confirm_token("mutator")
    outside = tmp_path / "elsewhere" / "f.md"
    out = sr.run_op(d, "mutator", confirm_token=token,
                    write_targets=[str(scope / "ok.md"), str(outside)])
    assert out["refused"] is True
    assert out["reason"].startswith("write-scope-violation:")
    assert str(outside) in out["reason"]
    assert _executions(mutate_rig["canary"]) == 0
    # A scope refusal does not burn the human's approval: the SAME token with
    # in-scope targets then proceeds.
    out = sr.run_op(d, "mutator", confirm_token=token,
                    write_targets=[str(scope / "ok.md")])
    assert out["ok"] is True
    # An escape attempt via .. is resolved before the scope check.
    import os
    token2 = sr.issue_confirm_token("mutator")
    sneaky = os.path.join(str(scope), "..", "..", "evil.md")
    out = sr.run_op(d, "mutator", confirm_token=token2,
                    write_targets=[sneaky])
    assert out["refused"] is True
    assert out["reason"].startswith("write-scope-violation:")


def test_mutate_requires_declared_targets(mutate_rig):
    d = mutate_rig["dispatch"]
    token = sr.issue_confirm_token("mutator")
    out = sr.run_op(d, "mutator", confirm_token=token)
    assert out["refused"] is True
    assert out["reason"] == "write-targets-undeclared"


# ── The Wave-2 seam lives in the runner: every op auto-journals ──────────────

def test_ok_run_auto_journals_schema_valid_entry(rig):
    dispatch = sr.build_dispatch([rig["manifest"]])
    out = sr.run_op(dispatch, "demo", payload={"ask": "read the tree"})
    assert out["ok"] is True
    entries = _journal_entries(rig["skill_dir"])
    assert len(entries) == 1
    parsed = _fj.parse_entry(entries[0].read_text(encoding="utf-8"))
    assert _fj.validate_entry(parsed) == []
    for field in _fd.JOURNAL_ENTRY_FIELDS:
        assert parsed.get(field), "skeleton missing field: %s" % field
    assert parsed["operation_kind"] == "run"
    assert parsed["provenance"].startswith("host-enforced:")
    assert parsed["outcome_linkage"]["outcome"] == "done"
    assert parsed["outcome_linkage"]["run_id"] == out["run_id"]
    assert parsed["outcome_linkage"]["skill"] == "demo"
    assert parsed["verdict_timing"]["duration_s"] >= 0


def test_failed_run_still_journals(tmp_path):
    skill_dir = _make_skill_dir(tmp_path, "flaky")
    stub = tmp_path / "flaky_host.py"
    stub.write_text(_FAILING_STUB, encoding="utf-8")
    host_cmd = "%s %s" % (Path(sys.executable).as_posix(), stub.as_posix())
    dispatch = sr.build_dispatch([_manifest("flaky", skill_dir, host_cmd)])
    out = sr.run_op(dispatch, "flaky")
    assert out["ok"] is False and out["outcome"] == "failed"
    assert out["reason"].startswith("host-nonzero-exit")
    parsed = _fj.parse_entry(
        _journal_entries(skill_dir)[0].read_text(encoding="utf-8"))
    assert _fj.validate_entry(parsed) == []
    assert parsed["outcome_linkage"]["outcome"] == "failed"
    assert "host-nonzero-exit" in parsed["outcome_linkage"]["reason"]


def test_refused_mutate_journals_the_refusal(mutate_rig):
    d = mutate_rig["dispatch"]
    out = sr.run_op(d, "mutator", write_targets=["x"])
    assert out["refused"] is True
    parsed = _fj.parse_entry(
        _journal_entries(mutate_rig["skill_dir"])[0].read_text(
            encoding="utf-8"))
    assert _fj.validate_entry(parsed) == []
    assert parsed["operation_kind"] == "mutate"
    assert parsed["outcome_linkage"]["outcome"] == "refused"
    assert parsed["outcome_linkage"]["reason"] == "confirm-token-missing"


def test_each_op_journals_its_own_entry(rig):
    dispatch = sr.build_dispatch([rig["manifest"]])
    first = sr.run_op(dispatch, "demo")
    second = sr.run_op(dispatch, "demo")
    names = {p.stem for p in _journal_entries(rig["skill_dir"])}
    assert names == {first["run_id"], second["run_id"]}


# ── Output contract ──────────────────────────────────────────────────────────

def test_output_contract_missing_keys_is_honest_failure(rig):
    m = dict(rig["manifest"])
    m["output_contract"] = {"format": "json",
                            "required_keys": ["schema", "not_emitted_key"]}
    dispatch = sr.build_dispatch([m])
    out = sr.run_op(dispatch, "demo")
    assert out["ok"] is False and out["outcome"] == "failed"
    assert out["reason"] == "output-missing-keys:not_emitted_key"


def test_output_contract_text_format_returns_stdout(tmp_path):
    skill_dir = _make_skill_dir(tmp_path, "texty")
    stub = tmp_path / "texty_host.py"
    stub.write_text("print('plain prose result')", encoding="utf-8")
    host_cmd = "%s %s" % (Path(sys.executable).as_posix(), stub.as_posix())
    dispatch = sr.build_dispatch([_manifest(
        "texty", skill_dir, host_cmd,
        output_contract={"format": "text"})])
    out = sr.run_op(dispatch, "texty")
    assert out["ok"] is True
    assert "plain prose result" in out["output"]


def test_executor_seam_is_injectable(rig):
    """The execution step is a seam: an injected executor replaces the host
    subprocess entirely (how Wave 4 mounts gandalf's staged pipeline)."""
    dispatch = sr.build_dispatch([rig["manifest"]])
    calls = []

    def fake_executor(entry, payload):
        calls.append((entry["skill"], payload))
        return {"schema": "injected", "verdict": "fine", "echo": payload}

    out = sr.run_op(dispatch, "demo", payload={"k": 2},
                    executor=fake_executor)
    assert out["ok"] is True
    assert out["output"]["schema"] == "injected"
    assert calls == [("demo", {"k": 2})]
    assert _executions(rig["canary"]) == 0  # the real host never spawned
