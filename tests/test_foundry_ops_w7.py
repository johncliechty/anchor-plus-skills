"""foundry-v2 Wave 7 — control-plane ops (scaffold + gen_manifest).

Proves the Wave-7 done-when:
  (a) each op runs HEADLESSLY via job_runner (no GUI): the op subprocess is a
      server-owned job with a durable log + record, launched through the
      Wave-7 ``command=`` dispatch seam — never a model run, never a terminal;
  (b) ``foundry.scaffold_skill`` scaffolds a demo skill END TO END into a
      RUNNABLE (its manifest dispatches + its template host answers the
      declared contract) + JOURNALED (the runner's Wave-2 seam journals its
      runs into the NEW skill's journal) + MAP-REGISTERED (map.json v2 valid,
      lockfile regenerated, all three Wave-6 drift gates green) skill;
  (c) the scaffold op REFUSES to overwrite an existing skill (idempotent —
      a re-run never clobbers or half-writes);
  (d) both ops are manifest-registered ``mutate`` ops: the runner's gates
      (single-use confirm token + declared write scope) refuse an unapproved
      or out-of-scope invocation BEFORE any job spawns, and every dispatched
      op auto-journals through the Wave-2 seam;
  (e) ``foundry.gen_manifest`` derives/updates a skill's manifest validated
      against the Wave-3 schema — an invalid result refuses WITHOUT writing.

Hermetic like tests/test_foundry_skill_runner_w3.py: temp ANCHOR_DATA_DIR +
temp skills root + temp map/lock artifacts; the op host is this repo's own
``foundry_ops.py`` run via ``sys.executable`` (deterministic local code —
NEVER real claude / real node / the real Skill Foundry / the worktree map /
:8777). Stdlib only.
"""
import json
import shutil
import sys
from pathlib import Path

import pytest

import foundry_decisions as fd
import foundry_journal as fj
import foundry_map as fm
import foundry_map_gates as fg
import foundry_ops as fo
import skill_runner as sr


# ── Fixture: a hermetic control-plane rig ────────────────────────────────────

@pytest.fixture
def rig(tmp_path, monkeypatch):
    """Temp data dir + skills root + a valid seed map/lock + the op dispatch."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.setenv("ANCHOR_DATA_DIR", str(data_dir))
    skills_root = tmp_path / "skills"
    skills_root.mkdir()
    (skills_root / "gandalf").mkdir()
    doc = {
        "schema": fm.MAP_SCHEMA_ID,
        "map_version": fm.MAP_VERSION,
        "skills": [
            {"ref": "skill:gandalf", "name": "gandalf",
             "source": (skills_root / "gandalf").as_posix(),
             "status": "5 - Production/Stable", "tier": "standard",
             "version": "1.2.0", "edges": []},
        ],
    }
    map_path = tmp_path / "map.json"
    map_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    lock_path = tmp_path / "map.lock.json"
    fm.write_lockfile(doc, path=lock_path)
    dispatch = fo.build_control_dispatch(
        skills_root=skills_root, map_path=map_path, lock_path=lock_path)
    return {"tmp": tmp_path, "data": data_dir, "skills_root": skills_root,
            "map": map_path, "lock": lock_path, "dispatch": dispatch}


def _scaffold_payload(rig, name="demo-skill", **over):
    p = {"name": name,
         "skills_root": str(rig["skills_root"]),
         "map_path": str(rig["map"]),
         "lock_path": str(rig["lock"]),
         "git": False}
    p.update(over)
    return p


def _ops_journal_entries(rig) -> list:
    return sorted((rig["data"] / "foundry_ops" / "journal").glob("*.md"))


def _scaffold(rig, name="demo-skill", **over):
    token = sr.issue_confirm_token(fo.OP_SCAFFOLD)
    return fo.run_control_op(rig["dispatch"], fo.OP_SCAFFOLD,
                             payload=_scaffold_payload(rig, name, **over),
                             confirm_token=token)


# ── (d) the ops are the DR-01 inventory, as valid mutate manifests ───────────

def test_ops_trace_dr01_and_manifests_validate(rig):
    # The registry keys ARE the DR-01 mutative-verb inventory entries.
    assert fo.OP_SCAFFOLD in fd.MUTATIVE_VERBS
    assert fo.OP_GEN_MANIFEST in fd.MUTATIVE_VERBS
    for m in fo.control_plane_manifests(skills_root=rig["skills_root"],
                                        map_path=rig["map"],
                                        lock_path=rig["lock"]):
        assert m["op_kind"] == "mutate"
        assert m["write_scope"]  # an explicit, non-empty declared scope
        assert sr.validate_manifest(m) == []
    # Both resolve into the dispatch table (declare-then-resolve, no exec).
    assert set(rig["dispatch"]) == {fo.OP_SCAFFOLD, fo.OP_GEN_MANIFEST}


# ── (a)+(b) scaffold end-to-end, headlessly via job_runner ───────────────────

def test_scaffold_runs_headlessly_via_job_runner(rig):
    res = _scaffold(rig)
    assert res["ok"] is True and res["outcome"] == "done"
    out = res["output"]
    assert out["ok"] is True and out["op"] == "scaffold_skill"
    assert out["map_registered"] is True and out["lock_regenerated"] is True

    # HEADLESS via job_runner: a real server-owned job ran the op — durable
    # record + log under the (temp) data dir, on the control-plane lane.
    import job_runner as jr
    job = res["job"]
    assert job and job["status"] == jr.STATUS_DONE
    rec = jr.load_record(job["job_id"])
    assert rec["lane"] == fo.OPS_LANE
    assert rec["status"] == jr.STATUS_DONE
    log = Path(rec["log_path"])
    assert log.is_file()
    assert '"op": "scaffold_skill"' in log.read_text(encoding="utf-8")
    # The Wave-7 dispatch seam: the job's durable relaunch spec preserves the
    # explicit op argv (an interrupted op job can never relaunch as a model).
    assert rec["relaunch_spec"]["command"][0] == sys.executable

    # The full template landed on disk.
    sd = rig["skills_root"] / "demo-skill"
    for rel in ("SKILL.md", "NORTH-STAR.md", "host.py", "manifest.json"):
        assert (sd / rel).is_file(), rel
    assert (sd / "journal").is_dir()

    # MAP-REGISTERED: map.json v2 valid, the lockfile pins the new skill, and
    # all three Wave-6 drift gates are green on the post-scaffold artifacts.
    doc = fm.load_map(rig["map"])
    assert fm.validate_map(doc) == []
    assert "skill:demo-skill" in {s["ref"] for s in doc["skills"]}
    lock = fm.load_lockfile(rig["lock"])
    assert "skill:demo-skill" in {e["ref"] for e in lock["resolved"]}
    gates = fg.run_drift_gates(doc, lock_path=rig["lock"], root=rig["tmp"])
    assert gates["ok"] is True, gates

    # The op itself AUTO-JOURNALED through the Wave-2 seam (host-enforced).
    entries = _ops_journal_entries(rig)
    assert len(entries) == 1
    parsed = fj.parse_entry(entries[0].read_text(encoding="utf-8"))
    assert fj.validate_entry(parsed) == []
    assert parsed["operation_kind"] == "mutate"
    assert parsed["outcome_linkage"]["outcome"] == "done"
    assert "scaffolded:demo-skill" in parsed["verdict_timing"]["verdict"]


def test_scaffolded_skill_is_runnable_and_journaled(rig):
    assert _scaffold(rig, name="runnable-demo")["ok"] is True
    sd = rig["skills_root"] / "runnable-demo"

    # RUNNABLE: the scaffolded manifest dispatches on the generic runner and
    # the template host answers the declared output contract.
    manifest = sr.load_skill_manifest(sd)
    assert sr.validate_manifest(manifest) == []
    dispatch = sr.build_dispatch([manifest])
    run = sr.run_op(dispatch, "runnable-demo", payload={"ping": "pong"})
    assert run["ok"] is True, run["reason"]
    assert run["output"]["schema"] == "runnable-demo/v1"
    assert run["output"]["echo"] == {"ping": "pong"}

    # JOURNALED: the run auto-journaled into the NEW skill's own journal.
    entries = sorted((sd / "journal").glob("*.md"))
    assert len(entries) == 1
    parsed = fj.parse_entry(entries[0].read_text(encoding="utf-8"))
    assert fj.validate_entry(parsed) == []
    assert parsed["outcome_linkage"]["outcome"] == "done"


# ── (c) the scaffold op refuses to overwrite ─────────────────────────────────

def test_scaffold_refuses_to_overwrite(rig):
    first = _scaffold(rig, name="once-only")
    assert first["ok"] is True
    sd = rig["skills_root"] / "once-only"
    before = (sd / "SKILL.md").read_text(encoding="utf-8")
    map_before = rig["map"].read_text(encoding="utf-8")

    second = _scaffold(rig, name="once-only")  # fresh token, same name
    out = second["output"]
    assert out["ok"] is False and out["refused"] is True
    assert out["reason"].startswith("refuses-to-overwrite:")
    # Nothing was clobbered or half-written: dir content + map are unchanged.
    assert (sd / "SKILL.md").read_text(encoding="utf-8") == before
    assert rig["map"].read_text(encoding="utf-8") == map_before
    # A registered-but-not-on-disk collision refuses too (no duplicate entry).
    shutil.rmtree(sd)
    third = _scaffold(rig, name="once-only")
    assert third["output"]["reason"].startswith("already-registered:")


# ── (d) mutate gates: confirm token + write scope, refused before any job ────

def test_mutate_gates_refuse_before_any_job_spawns(rig):
    payload = _scaffold_payload(rig, name="gated-demo")

    # No confirm token → refused; NO job was launched for a refused op.
    res = fo.run_control_op(rig["dispatch"], fo.OP_SCAFFOLD, payload=payload)
    assert res["refused"] is True and res["reason"] == "confirm-token-missing"
    assert res["job"] is None

    # A valid token but an out-of-scope write target → refused, token spent
    # on nothing, still no job, nothing scaffolded.
    token = sr.issue_confirm_token(fo.OP_SCAFFOLD)
    res = fo.run_control_op(
        rig["dispatch"], fo.OP_SCAFFOLD, payload=payload,
        confirm_token=token,
        write_targets=[str(rig["tmp"] / "elsewhere" / "x")])
    assert res["refused"] is True
    assert res["reason"].startswith("write-scope-violation:")
    assert res["job"] is None
    assert not (rig["skills_root"] / "gated-demo").exists()

    # Refusals are journaled too (host-enforced — the DR-02 audit trail).
    entries = _ops_journal_entries(rig)
    assert len(entries) == 2
    for p in entries:
        parsed = fj.parse_entry(p.read_text(encoding="utf-8"))
        assert fj.validate_entry(parsed) == []
        assert parsed["outcome_linkage"]["outcome"] == "refused"


# ── (e) gen_manifest: derive → update, validated before write ────────────────

def test_gen_manifest_derives_then_updates_via_job_runner(rig):
    sd = rig["skills_root"] / "bare"
    sd.mkdir()
    (sd / "SKILL.md").write_text("# bare protocol\n", encoding="utf-8")
    (sd / "host.py").write_text("print('{}')\n", encoding="utf-8")

    token = sr.issue_confirm_token(fo.OP_GEN_MANIFEST)
    res = fo.run_control_op(
        rig["dispatch"], fo.OP_GEN_MANIFEST,
        payload={"skill": "bare", "skills_root": str(rig["skills_root"])},
        confirm_token=token)
    assert res["ok"] is True
    out = res["output"]
    assert out["ok"] is True and out["op"] == "gen_manifest"
    assert out["updated"] is False  # derived fresh
    assert res["job"] and res["job"]["status"] == "done"

    # The written manifest is Wave-3-schema valid and derived from the dir.
    manifest = sr.load_skill_manifest(sd)
    assert sr.validate_manifest(manifest) == []
    assert manifest["host_cmd"][-1] == "{skill_dir}/host.py"
    assert "read:SKILL.md" in manifest["capabilities"]

    # Second pass UPDATES (explicit updates win; the file already existed).
    token = sr.issue_confirm_token(fo.OP_GEN_MANIFEST)
    res = fo.run_control_op(
        rig["dispatch"], fo.OP_GEN_MANIFEST,
        payload={"skill": "bare", "skills_root": str(rig["skills_root"]),
                 "updates": {"tier": "heavy"}},
        confirm_token=token)
    assert res["ok"] is True and res["output"]["updated"] is True
    assert sr.load_skill_manifest(sd)["tier"] == "heavy"


def test_gen_manifest_refuses_invalid_without_writing(rig):
    sd = rig["skills_root"] / "badtier"
    sd.mkdir()
    (sd / "host.py").write_text("print('{}')\n", encoding="utf-8")
    token = sr.issue_confirm_token(fo.OP_GEN_MANIFEST)
    res = fo.run_control_op(
        rig["dispatch"], fo.OP_GEN_MANIFEST,
        payload={"skill": "badtier", "skills_root": str(rig["skills_root"]),
                 "updates": {"tier": "hobbyist"}},  # off the tier enum
        confirm_token=token)
    out = res["output"]
    assert out["ok"] is False and out["refused"] is True
    assert "manifest-invalid" in out["reason"]
    # Refused WITHOUT writing — no manifest landed on disk.
    assert not (sd / sr.MANIFEST_FILENAME).exists()
    # An unknown skill dir refuses honestly too.
    token = sr.issue_confirm_token(fo.OP_GEN_MANIFEST)
    res = fo.run_control_op(
        rig["dispatch"], fo.OP_GEN_MANIFEST,
        payload={"skill": "no-such", "skills_root": str(rig["skills_root"])},
        confirm_token=token)
    assert res["output"]["reason"].startswith("unknown-skill:")


# ── scaffold commits on a branch (DR-02: mutations on a branch) ──────────────

def test_scaffold_commits_on_a_branch(rig):
    if not shutil.which("git"):
        pytest.skip("git not on PATH")
    import worktrees as wt
    repo = rig["tmp"] / "foundryrepo"
    repo.mkdir()
    ok, _rc, _out, err = wt._git(repo, ["init"])
    assert ok, err
    skills_root = repo / "skills"
    skills_root.mkdir()
    map_path = repo / "map.json"
    doc = {"schema": fm.MAP_SCHEMA_ID, "map_version": fm.MAP_VERSION,
           "skills": [{"ref": "skill:seed", "name": "seed",
                       "source": (skills_root / "seed").as_posix(),
                       "status": "4 - Beta", "tier": "standard",
                       "version": "1.0.0", "edges": []}]}
    (skills_root / "seed").mkdir()
    map_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    lock_path = repo / "map.lock.json"
    fm.write_lockfile(doc, path=lock_path)

    out = fo.scaffold_skill("branchy", skills_root=skills_root,
                            map_path=map_path, lock_path=lock_path, git=True)
    assert out["ok"] is True, out
    git_report = out["git"]
    assert git_report["committed"] is True
    assert git_report["branch"] == "foundry/scaffold-branchy"
    ok, _rc, head, _err = wt._git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    assert ok and head.strip() == "foundry/scaffold-branchy"
    ok, _rc, log, _err = wt._git(repo, ["log", "--oneline", "-1"])
    assert ok and "foundry.scaffold_skill: branchy" in log

    # No foundry repo → the files still stand and the report is honest, never
    # silent — AND never a hijacked commit into some stray ANCESTOR repo (a
    # temp/home ``.git`` above the skills root must not be branch-switched).
    bare_root = rig["tmp"] / "no-repo-skills"
    bare_root.mkdir()
    map2 = rig["tmp"] / "map2.json"
    map2.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    lock2 = rig["tmp"] / "map2.lock.json"
    fm.write_lockfile(doc, path=lock2)
    out = fo.scaffold_skill("orphan", skills_root=bare_root, map_path=map2,
                            lock_path=lock2, git=True)
    assert out["ok"] is True
    assert out["git"]["committed"] is False
    assert out["git"]["reason"].startswith(
        ("not-a-git-repo", "repo-not-foundry-rooted"))
    assert (bare_root / "orphan" / "SKILL.md").is_file()


# ── the runner's DEFAULT host path (payload on stdin) also carries the op ────

def test_op_manifest_runs_on_default_host_stdin_path(rig):
    payload = _scaffold_payload(rig, name="stdin-demo")
    token = sr.issue_confirm_token(fo.OP_SCAFFOLD)
    res = sr.run_op(rig["dispatch"], fo.OP_SCAFFOLD, payload=payload,
                    confirm_token=token,
                    write_targets=fo.write_targets_for(fo.OP_SCAFFOLD,
                                                       payload))
    assert res["ok"] is True
    assert res["output"]["ok"] is True
    assert (rig["skills_root"] / "stdin-demo" / "manifest.json").is_file()


# ── CLI / payload discipline (unit level, no subprocess) ─────────────────────

def test_invoke_op_refusals():
    assert fo._invoke_op("no-such-op", {})["reason"].startswith("unknown-op:")
    assert fo._invoke_op("scaffold_skill", "nope")["reason"] == \
        "payload-not-an-object"
    res = fo._invoke_op("scaffold_skill", {"name": "x", "bogus_key": 1})
    assert res["reason"].startswith("unknown-payload-key:bogus_key")
    # An invalid slug refuses before touching anything.
    res = fo._invoke_op("scaffold_skill", {"name": "Bad Name!"})
    assert res["refused"] is True
    assert res["reason"].startswith("invalid-skill-name:")
