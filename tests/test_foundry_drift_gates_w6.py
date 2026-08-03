"""foundry-v2 Wave 6 — three drift gates + consumption path + supply-chain
signing.

Proves the Wave-6 done-when:
  (a) a WRONG/EMPTY edge breaks a build LOUDLY — the real consumer
      (``foundry_skills.build_registry_dispatch``) reads map.json v2 and
      refuses the dispatch build when the graph and the registry disagree
      (missing skill, missing/wrongly-typed/wrong-target compose edge, an
      edge the runner doesn't honor, a tier mismatch, an invalid map);
  (b) all THREE drift gates are green on a consistent graph and red on a
      stale/forged one — schema-in-CI (artifact parses + reader-enum
      anti-drift + instance validates), regenerate + exact-diff (byte-level
      ``git diff --exit-code`` semantics; the coupled CI argv is exposed),
      and target-existence at ingest (every declared edge resolves to a
      real skill on disk);
  (c) a TAMPERED lockfile fails the checksum gate — on the KEYLESS sha256
      leg alone — and a forged signature document fails the keyed HMAC leg
      (an attacker who re-hashes a tampered lock still cannot sign it).

Hermetic: synthetic graphs + tmp dirs + the worktree-local JSON artifacts.
NEVER real claude / real node / real git / the real Skill Foundry map.json /
:8777. Stdlib only.
"""
import copy
import json

import pytest

import foundry_decisions as fd
import foundry_map as fm
import foundry_map_gates as fg
import foundry_skills as fs


# ── Fixture: the Wave-5 synthetic graph, materialized on disk ────────────────

def _graph_doc():
    return {
        "schema": fm.MAP_SCHEMA_ID,
        "map_version": fm.MAP_VERSION,
        "skills": [
            {"ref": "skill:base", "name": "base", "source": "skills/base",
             "status": "5 - Production/Stable", "tier": "standard",
             "version": "1.2.0", "edges": []},
            {"ref": "skill:mid", "name": "mid", "source": "skills/mid",
             "status": "4 - Beta", "tier": "standard", "version": "1.0.0",
             "edges": [{"type": "import", "to": "skill:base",
                        "range": "^1.0.0"}]},
            {"ref": "skill:top", "name": "top", "source": "skills/top",
             "status": "3 - Alpha", "tier": "heavy", "version": "0.2.0",
             "edges": [{"type": "compose", "to": "skill:mid",
                        "range": ">=1.0.0 <2.0.0"}]},
        ],
    }


@pytest.fixture
def graph(tmp_path):
    """A consistent graph: map doc + real source dirs + a fresh lockfile."""
    doc = _graph_doc()
    root = tmp_path / "foundry"
    for skill in doc["skills"]:
        (root / skill["source"]).mkdir(parents=True)
    map_path = tmp_path / "map.json"
    map_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    lock_path = tmp_path / "graph.lock.json"
    fm.write_lockfile(doc, path=lock_path)
    return {"doc": doc, "root": root, "map": map_path, "lock": lock_path,
            "tmp": tmp_path}


def _problems(gate):
    assert gate["ok"] is False
    return gate["problems"]


# ── Vocabulary / North-Star trace ────────────────────────────────────────────

def test_gate_vocabulary_and_north_star_trace():
    assert fg.DRIFT_GATES == ("schema", "lock-regenerate", "target-existence")
    assert fg.GATE_SUPPLY_CHAIN == "supply-chain"
    # Wave-1 anti-drift convention: the artifact traces to the North Star.
    assert fg.TRACES_TO_NORTH_STAR == (fd.NS_KNOWLEDGE_GRAPH,)


# ── Drift gate 1: schema-in-CI ───────────────────────────────────────────────

def test_gate_schema_green_on_consistent_and_shipped(graph):
    assert fg.gate_schema(graph["doc"]) == {
        "gate": "schema", "ok": True, "problems": []}
    # the SHIPPED worktree artifacts pass the same gate
    assert fg.gate_schema()["ok"] is True


def test_gate_schema_red_on_forged_map(graph):
    doc = copy.deepcopy(graph["doc"])
    del doc["skills"][1]["edges"][0]["type"]           # untyped edge
    doc["skills"][0]["status"] = "shipped"             # off the ladder
    problems = _problems(fg.gate_schema(doc))
    assert any("edge-untyped" in p for p in problems)
    assert any("status-out-of-enum" in p for p in problems)


def test_gate_schema_red_on_broken_schema_artifact(graph, tmp_path):
    broken = tmp_path / "broken.schema.json"
    broken.write_text("{ not json", encoding="utf-8")
    problems = _problems(fg.gate_schema(graph["doc"], schema_path=broken))
    assert any(p.startswith("schema-artifact-broken:") for p in problems)
    # structurally-empty document (parses, but is not the schema)
    empty = tmp_path / "empty.schema.json"
    empty.write_text("{}", encoding="utf-8")
    problems = _problems(fg.gate_schema(graph["doc"], schema_path=empty))
    assert any(p.startswith("schema-artifact-broken:") for p in problems)


def test_gate_schema_red_on_reader_enum_drift(graph, tmp_path):
    # someone widens the enum in the schema DOCUMENT after the validator
    # imported it — the single source and its reader may not disagree
    schema = json.loads(fm.SCHEMA_FILE.read_text(encoding="utf-8"))
    schema["definitions"]["edge_type"]["enum"].append("uses")
    drifted = tmp_path / "drifted.schema.json"
    drifted.write_text(json.dumps(schema), encoding="utf-8")
    problems = _problems(fg.gate_schema(graph["doc"], schema_path=drifted))
    assert "schema-enum-drift:edge_type" in problems


# ── Drift gate 2: regenerate + exact diff (git diff --exit-code) ─────────────

def test_gate_lock_green_on_fresh_lockfile(graph):
    gate = fg.gate_lock_regenerate(graph["doc"], lock_path=graph["lock"])
    assert gate == {"gate": "lock-regenerate", "ok": True, "problems": []}


def test_gate_lock_green_on_shipped_artifacts():
    assert fg.gate_lock_regenerate()["ok"] is True


def test_gate_lock_red_on_stale_lock_after_map_change(graph):
    doc = copy.deepcopy(graph["doc"])
    doc["skills"][0]["version"] = "1.3.0"  # map moved, lock did not
    problems = _problems(fg.gate_lock_regenerate(doc,
                                                 lock_path=graph["lock"]))
    assert any("lock-regen-diff" in p for p in problems)
    assert any("lock-pin-drift" in p for p in problems)  # names WHAT drifted


def test_gate_lock_red_on_tampered_bytes(graph):
    # semantic forgery: a pin edited in place
    text = graph["lock"].read_text(encoding="utf-8")
    graph["lock"].write_text(text.replace('"1.2.0"', '"9.9.9"'),
                             encoding="utf-8")
    problems = _problems(fg.gate_lock_regenerate(graph["doc"],
                                                 lock_path=graph["lock"]))
    assert any("lock-regen-diff" in p for p in problems)
    assert any("lock-pin-drift" in p or "lock-closure-drift" in p
               for p in problems)
    # whitespace-only tamper: semantically identical, still red — the gate
    # is BYTE-exact, precisely git diff --exit-code semantics
    graph["lock"].write_text(text + "\n", encoding="utf-8")
    problems = _problems(fg.gate_lock_regenerate(graph["doc"],
                                                 lock_path=graph["lock"]))
    assert any("lock-regen-diff" in p for p in problems)


def test_gate_lock_red_on_missing_or_unparseable(graph, tmp_path):
    gone = tmp_path / "no-such.lock.json"
    problems = _problems(fg.gate_lock_regenerate(graph["doc"],
                                                 lock_path=gone))
    assert any("lockfile-missing" in p for p in problems)
    junk = tmp_path / "junk.lock.json"
    junk.write_text("not json at all", encoding="utf-8")
    problems = _problems(fg.gate_lock_regenerate(graph["doc"],
                                                 lock_path=junk))
    assert any("lockfile-unparseable" in p for p in problems)


def test_gate_lock_red_on_unresolvable_map(graph):
    doc = copy.deepcopy(graph["doc"])
    doc["skills"][1]["edges"][0]["range"] = "^2.0.0"  # base is 1.2.0
    problems = _problems(fg.gate_lock_regenerate(doc,
                                                 lock_path=graph["lock"]))
    assert any("map-unresolvable" in p for p in problems)


def test_lock_diff_ci_command_is_the_git_exit_code_form():
    assert fg.lock_diff_ci_command() == [
        "git", "diff", "--exit-code", "--", "foundry_map_v2.lock.json"]
    assert fg.lock_diff_ci_command("some/dir/other.lock.json")[-1] == \
        "other.lock.json"


# ── Drift gate 3: target-existence at ingest ─────────────────────────────────

def test_gate_targets_green_and_edge_scoped(graph):
    gate = fg.gate_target_existence(graph["doc"], root=graph["root"])
    assert gate == {"gate": "target-existence", "ok": True, "problems": []}
    # edge-SCOPED per the plan: a skill NOTHING depends on may be absent
    (graph["root"] / "skills" / "top").rmdir()
    assert fg.gate_target_existence(graph["doc"],
                                    root=graph["root"])["ok"] is True


def test_gate_targets_red_when_an_edge_target_is_not_on_disk(graph):
    (graph["root"] / "skills" / "base").rmdir()
    problems = _problems(fg.gate_target_existence(graph["doc"],
                                                  root=graph["root"]))
    assert any(p.startswith("edge-target-not-on-disk:skill:mid->skill:base")
               for p in problems)


def test_gate_targets_red_on_unknown_edge_ref(graph):
    doc = copy.deepcopy(graph["doc"])
    doc["skills"][1]["edges"].append(
        {"type": "import", "to": "skill:ghost", "range": "*"})
    problems = _problems(fg.gate_target_existence(doc, root=graph["root"]))
    assert "edge-target-unknown:skill:mid->skill:ghost" in problems


def test_gate_targets_absolute_sources_stand_alone(graph, tmp_path):
    doc = copy.deepcopy(graph["doc"])
    abs_dir = tmp_path / "elsewhere" / "base"
    abs_dir.mkdir(parents=True)
    doc["skills"][0]["source"] = str(abs_dir)
    assert fg.gate_target_existence(doc, root=graph["root"])["ok"] is True
    abs_dir.rmdir()
    problems = _problems(fg.gate_target_existence(doc, root=graph["root"]))
    assert any("edge-target-not-on-disk:skill:mid->skill:base" in p
               for p in problems)


def test_gate_targets_honors_the_root_env_seam(graph, monkeypatch):
    monkeypatch.setenv(fg.FOUNDRY_ROOT_ENV, str(graph["root"]))
    assert fg.gate_target_existence(graph["doc"])["ok"] is True
    monkeypatch.setenv(fg.FOUNDRY_ROOT_ENV, str(graph["tmp"] / "empty"))
    assert fg.gate_target_existence(graph["doc"])["ok"] is False


# ── The trio + ingest ────────────────────────────────────────────────────────

def test_run_drift_gates_green_on_a_consistent_graph(graph):
    result = fg.run_drift_gates(graph["doc"], lock_path=graph["lock"],
                                root=graph["root"])
    assert result["ok"] is True
    assert [g["gate"] for g in result["gates"]] == list(fg.DRIFT_GATES)
    assert all(g["ok"] and g["problems"] == [] for g in result["gates"])


def test_run_drift_gates_red_names_the_failing_gate(graph):
    text = graph["lock"].read_text(encoding="utf-8")
    graph["lock"].write_text(text + "\n", encoding="utf-8")
    result = fg.run_drift_gates(graph["doc"], lock_path=graph["lock"],
                                root=graph["root"])
    assert result["ok"] is False
    bad = [g["gate"] for g in result["gates"] if not g["ok"]]
    assert bad == ["lock-regenerate"]  # the OTHER two stay green


def test_ingest_map_green_returns_the_doc_and_red_refuses(graph):
    doc = fg.ingest_map(map_path=graph["map"], lock_path=graph["lock"],
                        root=graph["root"])
    assert doc == graph["doc"]
    # a stale lock refuses the ingest loudly, naming the gate
    text = graph["lock"].read_text(encoding="utf-8")
    graph["lock"].write_text(text.replace('"1.2.0"', '"9.9.9"'),
                             encoding="utf-8")
    with pytest.raises(ValueError) as e:
        fg.ingest_map(map_path=graph["map"], lock_path=graph["lock"],
                      root=graph["root"])
    assert "map-ingest-refused" in str(e.value)
    assert "lock-regenerate:" in str(e.value)


def test_ingest_map_with_signature_gate(graph):
    lock_text = graph["lock"].read_text(encoding="utf-8")
    sig = fg.sign_lock_text(lock_text, key="ingest-key")
    doc = fg.ingest_map(map_path=graph["map"], lock_path=graph["lock"],
                        root=graph["root"], sig=sig, key="ingest-key")
    assert doc == graph["doc"]
    # requiring a signature with none supplied is red, never a silent skip
    with pytest.raises(ValueError) as e:
        fg.ingest_map(map_path=graph["map"], lock_path=graph["lock"],
                      root=graph["root"], key="ingest-key",
                      require_signature=True)
    assert "supply-chain:" in str(e.value)


# ── (a) consumption path: a wrong/empty edge breaks a build ──────────────────

def _mani(name, composes=None, tier="standard"):
    """A minimal valid Wave-3 manifest (pure data, stub host)."""
    m = {
        "skill": name, "skill_dir": "stub-dir", "op_kind": "run",
        "host_cmd": "python stub-host.py",
        "output_contract": {"format": "json"},
        "panel": {"title": name}, "journal": {"enabled": True},
        "tier": tier, "capabilities": [],
        "activation": {"trigger": "first_run"},
    }
    if composes is not None:
        m["composes"] = composes
    return m


def _graph_manifests():
    return [_mani("top", composes=["mid"], tier="heavy"), _mani("mid"),
            _mani("base")]


def test_consumed_build_reads_the_map_pins(graph):
    manifests = _graph_manifests()
    assert fs.verify_registry_against_map(manifests, graph["doc"]) == []
    dispatch = fs.build_registry_dispatch(manifests, map_doc=graph["doc"])
    assert dispatch["top"]["map"] == {
        "ref": "skill:top", "version": "0.2.0", "status": "3 - Alpha",
        "tier": "heavy"}
    assert dispatch["base"]["map"]["ref"] == "skill:base"


def test_empty_edge_breaks_the_build_loudly(graph):
    doc = copy.deepcopy(graph["doc"])
    doc["skills"][2]["edges"] = []  # the graph lost top's compose edge
    with pytest.raises(ValueError) as e:
        fs.build_registry_dispatch(_graph_manifests(), map_doc=doc)
    assert "map-consumption-refused" in str(e.value)
    assert "compose-edge-missing:top->mid" in str(e.value)


def test_wrong_edge_breaks_the_build_loudly(graph):
    # wrongly TYPED: the composition is declared as an import
    doc = copy.deepcopy(graph["doc"])
    doc["skills"][2]["edges"][0]["type"] = "import"
    with pytest.raises(ValueError) as e:
        fs.build_registry_dispatch(_graph_manifests(), map_doc=doc)
    assert "compose-edge-missing:top->mid" in str(e.value)
    # wrong TARGET: the map composes something the runner does not honor
    doc2 = copy.deepcopy(graph["doc"])
    doc2["skills"][2]["edges"][0]["to"] = "skill:base"
    with pytest.raises(ValueError) as e2:
        fs.build_registry_dispatch(_graph_manifests(), map_doc=doc2)
    assert "compose-edge-missing:top->mid" in str(e2.value)
    assert "compose-edge-undeclared:top->base" in str(e2.value)


def test_missing_skill_invalid_map_and_tier_mismatch_break(graph):
    with pytest.raises(ValueError) as e:
        fs.build_registry_dispatch(
            _graph_manifests() + [_mani("phantom")], map_doc=graph["doc"])
    assert "skill-not-in-map:phantom" in str(e.value)
    # an INVALID map is never consumed at all
    doc = copy.deepcopy(graph["doc"])
    doc["skills"][1]["edges"][0]["to"] = "skill:ghost"
    with pytest.raises(ValueError) as e2:
        fs.build_registry_dispatch(_graph_manifests(), map_doc=doc)
    assert "map-invalid:" in str(e2.value)
    # the runner tier must be the graph's tier
    manifests = [_mani("top", composes=["mid"], tier="standard"),
                 _mani("mid"), _mani("base")]
    with pytest.raises(ValueError) as e3:
        fs.build_registry_dispatch(manifests, map_doc=graph["doc"])
    assert "tier-mismatch:top" in str(e3.value)


def test_explicit_build_without_a_map_stays_the_pure_wave4_seam():
    # the hermetic subset/fixture path (W4's cycle test, gandalf-only
    # dispatches) is unchanged: no map read, no annotation, no refusal
    dispatch = fs.build_registry_dispatch(
        [_mani("alpha", composes=["beta"]), _mani("beta")])
    assert set(dispatch) == {"alpha", "beta"}
    assert all("map" not in entry for entry in dispatch.values())


def test_shipped_map_agrees_with_the_real_registry():
    overrides = {
        "gandalf": {"skill_dir": "stub-dir", "host_cmd": "python stub.py"},
        "jumper": {"skill_dir": "stub-dir", "host_cmd": "python stub.py"},
        fs.THIRD_SKILL: {"skill_dir": "stub-dir",
                         "host_cmd": "python stub.py"},
    }
    manifests = fs.registry_manifests(overrides=overrides)
    shipped = fm.load_map()
    assert fs.verify_registry_against_map(manifests, shipped) == []
    dispatch = fs.build_registry_dispatch(manifests, map_doc=shipped)
    by_name = {s["name"]: s for s in shipped["skills"]}
    for name in ("gandalf", "jumper", fs.THIRD_SKILL):
        assert dispatch[name]["map"]["ref"] == by_name[name]["ref"]
        assert dispatch[name]["map"]["version"] == by_name[name]["version"]


def test_default_build_consumes_the_map_artifact(graph, monkeypatch, tmp_path):
    # hermetic env: every manifest default resolves to stub values
    monkeypatch.setenv("ANCHOR_GANDALF_SKILL_DIR", str(tmp_path / "gd"))
    monkeypatch.setenv("ANCHOR_GANDALF_HOST_CMD", "python stub-host.py")
    monkeypatch.setenv(fs.SKILLS_ROOT_ENV, str(tmp_path / "skills"))
    monkeypatch.setenv(fs.JUMPER_HOST_CMD_ENV, "python stub-host.py")
    monkeypatch.setenv(fs.THIRD_HOST_CMD_ENV, "python stub-host.py")
    # the CANONICAL no-arg build reads the shipped map and carries its pins
    dispatch = fs.build_registry_dispatch()
    assert dispatch["gandalf"]["map"]["ref"] == "skill:gandalf"
    assert dispatch["jumper"]["map"]["ref"] == "skill:jumper"
    # break the ARTIFACT (jumper's compose edge emptied) → the same default
    # build now refuses: the consumer genuinely reads map.json v2
    broken = fm.load_map()
    for skill in broken["skills"]:
        if skill["name"] == "jumper":
            skill["edges"] = []
    broken_path = tmp_path / "broken-map.json"
    broken_path.write_text(json.dumps(broken), encoding="utf-8")
    monkeypatch.setattr(fm, "MAP_FILE", broken_path)
    with pytest.raises(ValueError) as e:
        fs.build_registry_dispatch()
    assert "compose-edge-missing:jumper->gandalf" in str(e.value)


# ── (c) supply-chain: signing/checksums coupled to the lockfile ──────────────

def test_sign_verify_roundtrip_is_deterministic(graph):
    text = graph["lock"].read_text(encoding="utf-8")
    sig = fg.sign_lock_text(text, key="secret")
    assert sig["schema"] == fg.SIG_SCHEMA_ID
    assert set(sig["entry_sha256"]) == {"skill:base", "skill:mid",
                                        "skill:top"}
    assert fg.verify_lock_signature(text, sig, key="secret") == []
    assert fg.gate_supply_chain(text, sig=sig, key="secret")["ok"] is True
    # deterministic: same bytes + key → the identical document, no timestamps
    assert fg.sign_lock_text(text, key="secret") == sig


def test_tampered_lockfile_fails_the_checksum_gate_keylessly(graph,
                                                             monkeypatch):
    monkeypatch.delenv(fg.SIGNING_KEY_ENV, raising=False)
    text = graph["lock"].read_text(encoding="utf-8")
    sig = fg.sign_lock_text(text, key="secret")
    tampered = text.replace('"1.2.0"', '"9.9.9"')
    # the KEYLESS checksum leg alone catches the tamper
    problems = fg.verify_lock_signature(tampered, sig, key=None)
    assert "checksum-mismatch:lockfile" in problems
    assert any(p.startswith("checksum-mismatch:skill:") for p in problems)
    assert "signature-unverifiable:no-key" in problems  # fail-closed, named
    assert fg.gate_supply_chain(tampered, sig=sig)["ok"] is False


def test_forged_signature_cannot_pass_without_the_key(graph):
    text = graph["lock"].read_text(encoding="utf-8")
    tampered = text.replace('"1.2.0"', '"9.9.9"')
    # the attacker re-hashes the tampered lock with their OWN key: every
    # checksum matches, but the HMAC cannot verify under the real key
    forged = fg.sign_lock_text(tampered, key="attacker")
    problems = fg.verify_lock_signature(tampered, forged, key="secret")
    assert "checksum-mismatch:lockfile" not in problems
    assert "signature-invalid" in problems
    # and a wrong key on a genuine signature is equally invalid
    genuine = fg.sign_lock_text(text, key="secret")
    assert "signature-invalid" in fg.verify_lock_signature(
        text, genuine, key="wrong")


def test_malformed_and_stale_signature_documents_fail(graph):
    text = graph["lock"].read_text(encoding="utf-8")
    assert fg.verify_lock_signature(text, "junk") == ["sig-not-an-object"]
    problems = fg.verify_lock_signature(text, {"schema": "nope"}, key="k")
    assert any("sig-schema-wrong" in p for p in problems)
    sig = fg.sign_lock_text(text, key="k")
    missing = copy.deepcopy(sig)
    del missing["entry_sha256"]["skill:mid"]
    assert "checksum-missing-entry:skill:mid" in fg.verify_lock_signature(
        text, missing, key="k")
    stale = copy.deepcopy(sig)
    stale["entry_sha256"]["skill:ghost"] = "0" * 64
    assert "checksum-stale-entry:skill:ghost" in fg.verify_lock_signature(
        text, stale, key="k")


def test_signing_key_seam_no_default_key_theater(graph, monkeypatch):
    text = graph["lock"].read_text(encoding="utf-8")
    monkeypatch.delenv(fg.SIGNING_KEY_ENV, raising=False)
    with pytest.raises(ValueError) as e:
        fg.sign_lock_text(text)  # no key anywhere → honest refusal
    assert "no-signing-key" in str(e.value)
    monkeypatch.setenv(fg.SIGNING_KEY_ENV, "env-key")
    sig = fg.sign_lock_text(text)
    assert fg.verify_lock_signature(text, sig) == []  # env key verifies too


def test_write_and_load_signature_roundtrip(graph, tmp_path):
    text = graph["lock"].read_text(encoding="utf-8")
    path = tmp_path / "graph.lock.sig.json"
    written = fg.write_signature(text, key="secret", path=path)
    assert fg.load_signature(path) == written
    assert fg.verify_lock_signature(text, fg.load_signature(path),
                                    key="secret") == []
    # regenerable: signing again writes the identical bytes (diffable in CI)
    first = path.read_text(encoding="utf-8")
    fg.write_signature(text, key="secret", path=path)
    assert path.read_text(encoding="utf-8") == first
