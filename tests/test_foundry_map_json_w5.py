"""foundry-v2 Wave 5 — map.json v2 schema + the resolved-graph lockfile.

Proves the Wave-5 done-when:
  (a) a GOOD map.json v2 validates against the schema (typed edges keyed by
      a stable ref, closed-enum status, tier + semver, manifest ranges);
  (b) the resolved-graph lockfile (the Cargo.lock analogue) PINS the
      TRANSITIVE closure — every edge to the exact resolved target version,
      every skill to its full sorted ``ref@version`` closure — and drift
      from a fresh resolution is detected by name;
  (c) an UNTYPED edge, an OVERLOADED edge, or an OUT-OF-ENUM status fails
      validation (plus the neighboring failure classes: out-of-enum edge
      type / tier, non-semver version, dangling target, self-edge,
      duplicate ref/edge, unsatisfied range, dependency cycle).

Also pins the single-source discipline: the closed enums live ONLY in the
JSON Schema document (foundry_map.py reads them from it at import), the tier
vocabulary matches ``skill_runner.TIERS``, and the shipped map agrees with
the Wave-4 registry (jumper's compose edge IS the manifest's ``composes``).

Hermetic: pure data + the worktree-local JSON artifacts. NEVER real claude /
real node / the real Skill Foundry map.json / :8777. Stdlib only.
"""
import copy
import json

import pytest

import foundry_decisions as _fd
import foundry_map as fm
import foundry_skills as fs
import skill_runner as sr


# ── Fixture: a small, fully-typed synthetic graph (top → mid → base) ─────────

def _good_map():
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


# ── (a) a good map validates ─────────────────────────────────────────────────

def test_good_map_validates_clean():
    assert fm.validate_map(_good_map()) == []


def test_shipped_map_validates_clean():
    doc = fm.load_map()
    assert fm.validate_map(doc) == []
    # keyed by a STABLE ref: unique, pattern-bound, rename-safe (the shipped
    # map proves ref != display name on researchPrime).
    refs = [s["ref"] for s in doc["skills"]]
    assert len(refs) == len(set(refs))
    by_ref = {s["ref"]: s for s in doc["skills"]}
    assert by_ref["skill:research-prime"]["name"] == "researchPrime"


def test_enums_are_sourced_from_the_schema_document():
    schema = fm.load_schema()
    defs = schema["definitions"]
    assert fm.EDGE_TYPES == tuple(defs["edge_type"]["enum"])
    assert fm.STATUS_LADDER == tuple(defs["status"]["enum"])
    assert fm.TIERS == tuple(defs["tier"]["enum"])
    # the closed enums themselves
    assert set(fm.EDGE_TYPES) == {"compose", "import", "augment"}
    assert fm.STATUS_LADDER == (
        "1 - Planning", "2 - Pre-Alpha", "3 - Alpha", "4 - Beta",
        "5 - Production/Stable", "6 - Mature", "7 - Inactive")


def test_vocabulary_matches_runner_and_north_star():
    # tier vocabulary is skill_runner's, not a parallel invention
    assert set(fm.TIERS) == set(sr.TIERS)
    # Wave-1 anti-drift convention: the artifact traces to the North Star
    assert fm.TRACES_TO_NORTH_STAR == (_fd.NS_KNOWLEDGE_GRAPH,)


def test_shipped_map_agrees_with_the_wave4_registry():
    doc = fm.load_map()
    by_name = {s["name"]: s for s in doc["skills"]}
    by_ref = {s["ref"]: s for s in doc["skills"]}
    # every Wave-4 registry skill is in the map
    for name in ("gandalf", "jumper", fs.THIRD_SKILL):
        assert name in by_name
    # jumper's typed compose edge IS the manifest's composes: ["gandalf"]
    manifest = fs.jumper_manifest(skill_dir="stub-dir",
                                  host_cmd="python stub-host.py")
    compose_targets = [by_ref[e["to"]]["name"]
                       for e in by_name["jumper"]["edges"]
                       if e["type"] == "compose"]
    assert compose_targets == list(manifest["composes"])


# ── (c) untyped / overloaded / out-of-enum fail validation ───────────────────

def test_untyped_edge_fails():
    doc = _good_map()
    del doc["skills"][1]["edges"][0]["type"]
    problems = fm.validate_map(doc)
    assert any("edge-untyped" in p for p in problems)


def test_overloaded_edge_fails():
    # one edge claiming TWO types is overloaded, not doubly-typed
    doc = _good_map()
    doc["skills"][1]["edges"][0]["type"] = ["import", "compose"]
    assert any("edge-overloaded" in p for p in fm.validate_map(doc))
    # so is a 'types' key alongside 'type'
    doc2 = _good_map()
    doc2["skills"][1]["edges"][0]["types"] = ["import", "compose"]
    assert any("edge-overloaded" in p for p in fm.validate_map(doc2))


def test_out_of_enum_status_fails():
    doc = _good_map()
    doc["skills"][0]["status"] = "shipped"  # not on the PyPI ladder
    assert any("status-out-of-enum" in p for p in fm.validate_map(doc))


def test_out_of_enum_edge_type_fails():
    doc = _good_map()
    doc["skills"][1]["edges"][0]["type"] = "uses"
    assert any("edge-type-out-of-enum" in p for p in fm.validate_map(doc))


def test_out_of_enum_tier_and_bad_semver_fail():
    doc = _good_map()
    doc["skills"][0]["tier"] = "frontier"
    doc["skills"][1]["version"] = "1.0"
    problems = fm.validate_map(doc)
    assert any("tier-out-of-enum" in p for p in problems)
    assert any("version-not-semver" in p for p in problems)


def test_dangling_target_self_edge_and_duplicates_fail():
    doc = _good_map()
    doc["skills"][1]["edges"].append(
        {"type": "import", "to": "skill:ghost", "range": "*"})
    doc["skills"][0]["edges"].append(
        {"type": "augment", "to": "skill:base", "range": "*"})
    problems = fm.validate_map(doc)
    assert any("edge-target-unknown" in p for p in problems)
    assert any("edge-self" in p for p in problems)
    # duplicate stable ref
    dup = _good_map()
    dup["skills"].append(copy.deepcopy(dup["skills"][0]))
    assert any("duplicate-ref" in p for p in fm.validate_map(dup))
    # duplicate (type, target) edge on one skill
    dup2 = _good_map()
    dup2["skills"][1]["edges"].append(
        {"type": "import", "to": "skill:base", "range": "^1.0.0"})
    assert any("edge-duplicate" in p for p in fm.validate_map(dup2))


def test_unstable_ref_and_invalid_range_fail():
    doc = _good_map()
    doc["skills"][0]["ref"] = "base"  # no skill: prefix → not a stable ref
    assert any("ref-not-stable" in p for p in fm.validate_map(doc))
    doc2 = _good_map()
    doc2["skills"][1]["edges"][0]["range"] = "latest"
    assert any("edge-range-invalid" in p for p in fm.validate_map(doc2))


# ── semver ranges (the manifest-range side of the range/lock split) ──────────

def test_semver_range_semantics():
    assert fm.range_satisfied("1.2.0", "^1.0.0")
    assert not fm.range_satisfied("2.0.0", "^1.0.0")
    assert fm.range_satisfied("1.5.3", ">=1.0.0 <2.0.0")
    assert not fm.range_satisfied("2.0.0", ">=1.0.0 <2.0.0")
    assert fm.range_satisfied("1.2.4", "~1.2.3")
    assert not fm.range_satisfied("1.3.0", "~1.2.3")
    # npm caret semantics below 1.0.0: the first non-zero component is fixed
    assert fm.range_satisfied("0.2.9", "^0.2.3")
    assert not fm.range_satisfied("0.3.0", "^0.2.3")
    assert fm.range_satisfied("9.9.9", "*")
    assert fm.range_satisfied("1.2.3", "1.2.3")
    assert not fm.range_satisfied("1.2.3", "!=1.2.3")
    with pytest.raises(ValueError):
        fm.parse_range("latest")


# ── (b) the lockfile pins the transitive closure ─────────────────────────────

def test_lockfile_pins_the_transitive_closure():
    lock, problems = fm.build_lockfile(_good_map())
    assert problems == []
    by_ref = {e["ref"]: e for e in lock["resolved"]}
    # direct pin: the range resolves to the exact declared target version
    mid = by_ref["skill:mid"]
    assert mid["dependencies"] == [{"ref": "skill:base", "type": "import",
                                    "range": "^1.0.0", "pinned": "1.2.0"}]
    # TRANSITIVE pin: top's closure reaches base THROUGH mid
    assert by_ref["skill:top"]["closure"] == ["skill:base@1.2.0",
                                              "skill:mid@1.0.0"]
    assert by_ref["skill:base"]["closure"] == []
    # deterministic: same map → identical lockfile, and NO timestamps
    lock2, _ = fm.build_lockfile(_good_map())
    assert lock == lock2
    assert fm.verify_lockfile(_good_map(), lock) == []


def test_shipped_lockfile_matches_a_fresh_resolution():
    doc = fm.load_map()
    lock = fm.load_lockfile()
    assert fm.verify_lockfile(doc, lock) == []
    fresh, problems = fm.build_lockfile(doc)
    assert problems == []
    assert fresh == lock
    # byte-stable serialization (what Wave 6's regen + git-diff gate rides on)
    on_disk = fm.LOCK_FILE.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert fm.dumps_lock(fresh) == on_disk
    # the shipped closure is genuinely TRANSITIVE: literature-review augments
    # researchPrime, which imports crucible + foreman — all three pinned
    by_ref = {e["ref"]: e for e in lock["resolved"]}
    assert by_ref["skill:literature-review"]["closure"] == [
        "skill:crucible@1.0.0",
        "skill:foreman@2.0.0",
        "skill:research-prime@2.0.0",
    ]
    assert by_ref["skill:crucible"]["closure"] == ["skill:foreman@2.0.0"]


def test_unsatisfied_range_refuses_the_lock():
    doc = _good_map()
    doc["skills"][1]["edges"][0]["range"] = "^2.0.0"  # base is 1.2.0
    lock, problems = fm.build_lockfile(doc)
    assert lock is None
    assert any("edge-range-unsatisfied" in p for p in problems)


def test_dependency_cycle_fails_honestly():
    doc = _good_map()
    doc["skills"][0]["edges"].append(
        {"type": "import", "to": "skill:top", "range": "*"})
    lock, problems = fm.build_lockfile(doc)
    assert lock is None
    assert any("edge-cycle" in p for p in problems)


def test_tampered_or_stale_lockfile_is_detected():
    doc = _good_map()
    lock, _ = fm.build_lockfile(doc)
    # a forged pin
    forged = copy.deepcopy(lock)
    forged["resolved"][0]["version"] = "9.9.9"
    assert any("lock-pin-drift" in p
               for p in fm.verify_lockfile(doc, forged))
    # a forged closure (the transitive pin no longer matches the graph)
    forged2 = copy.deepcopy(lock)
    for entry in forged2["resolved"]:
        if entry["ref"] == "skill:top":
            entry["closure"] = ["skill:mid@1.0.0"]
    assert any("lock-closure-drift" in p
               for p in fm.verify_lockfile(doc, forged2))
    # a missing entry (stale lock after a map grew)
    forged3 = copy.deepcopy(lock)
    forged3["resolved"] = [e for e in forged3["resolved"]
                           if e["ref"] != "skill:mid"]
    assert any("lock-missing-entry" in p
               for p in fm.verify_lockfile(doc, forged3))
    # a stale extra entry (the map shrank)
    doc2 = copy.deepcopy(doc)
    doc2["skills"] = [s for s in doc2["skills"] if s["ref"] != "skill:top"]
    assert any("lock-stale-entry" in p
               for p in fm.verify_lockfile(doc2, lock))


def test_write_lockfile_regenerates_deterministically(tmp_path):
    target = tmp_path / "regen.lock.json"
    lock = fm.write_lockfile(_good_map(), path=target)
    reread = json.loads(target.read_text(encoding="utf-8"))
    assert reread == lock
    # an unresolvable map never writes a partial lock
    bad = _good_map()
    del bad["skills"][1]["edges"][0]["type"]
    target2 = tmp_path / "never-written.lock.json"
    with pytest.raises(ValueError):
        fm.write_lockfile(bad, path=target2)
    assert not target2.exists()
