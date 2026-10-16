"""foundry-v2 Wave 8 — edit_north_star op + auto-load registration.

Proves the Wave-8 done-when:
  (a) a North-Star edit round-trips PROPOSAL (a diff comes back, nothing on
      the skill is written) → explicit human CONFIRM (the runner's single-use
      token — an unapproved apply refuses BEFORE any job spawns) → APPLY as a
      branch commit with the prior version retained (history file + hash
      ledger + a ``foundry/north-star-<skill>`` git branch);
  (b) the drift gate FAILS on a direct out-of-band North-Star write (and the
      Wave-2-style source grep gate flags a rogue writer module);
  (c) auto-load registration makes a scaffolded skill appear in Anchor's
      clickable set from map.json v2 ALONE — a regenerated projection (a
      skill dropped from the map drops out; never hand-wired);
  (d) both ops are DR-01-inventory, manifest-registered ``mutate`` ops
      dispatched HEADLESSLY through job_runner on the Wave-3 generic runner
      (confirm token + write scope + auto-journal), ADDITIVE beside the
      frozen Wave-7 pair.

Hermetic like tests/test_foundry_ops_w7.py: temp ANCHOR_DATA_DIR + temp
skills root + temp map/lock artifacts + temp autoload home; the op host is
this repo's own ``foundry_ops.py`` run via ``sys.executable`` (deterministic
local code — NEVER real claude / real node / the real Skill Foundry / the
worktree map / :8777). Stdlib only.
"""
import json
import shutil
from pathlib import Path

import pytest

import foundry_autoload as fa
import foundry_decisions as fd
import foundry_map as fm
import foundry_north_star as fns
import foundry_ops as fo
import skill_runner as sr


NEW_TEXT = ("# North Star — refined\n\n"
            "- make X true for the user\n"
            "- DONE looks like genuine data, not a demo\n")


# ── Fixture: a hermetic Wave-8 control-plane rig ─────────────────────────────

@pytest.fixture
def rig(tmp_path, monkeypatch):
    """Temp data dir + skills root + seed map/lock + autoload home + the FULL
    (Wave-7 + Wave-8) control-plane dispatch."""
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
    autoload_home = tmp_path / "autoload"
    autoload_home.mkdir()
    dispatch = fo.build_full_control_dispatch(
        skills_root=skills_root, map_path=map_path, lock_path=lock_path,
        autoload_home=autoload_home)
    return {"tmp": tmp_path, "data": data_dir, "skills_root": skills_root,
            "map": map_path, "lock": lock_path, "autoload": autoload_home,
            "seed_doc": doc, "dispatch": dispatch}


def _scaffold(rig, name):
    token = sr.issue_confirm_token(fo.OP_SCAFFOLD)
    payload = {"name": name, "skills_root": str(rig["skills_root"]),
               "map_path": str(rig["map"]), "lock_path": str(rig["lock"]),
               "git": False}
    return fo.run_control_op(rig["dispatch"], fo.OP_SCAFFOLD,
                             payload=payload, confirm_token=token)


def _edit(rig, payload, *, token="issue"):
    tok = sr.issue_confirm_token(fo.OP_EDIT_NORTH_STAR) \
        if token == "issue" else token
    return fo.run_control_op(rig["dispatch"], fo.OP_EDIT_NORTH_STAR,
                             payload=payload, confirm_token=tok)


def _ops_journal_entries(rig):
    return sorted((rig["data"] / "foundry_ops" / "journal").glob("*.md"))


# ── (d) the ops are the DR-01 inventory, additive beside the W7 pair ─────────

def test_wave8_ops_trace_dr01_and_dispatch_additively(rig):
    assert fo.OP_EDIT_NORTH_STAR in fd.MUTATIVE_VERBS
    assert fo.OP_REGISTER_AUTOLOAD in fd.MUTATIVE_VERBS
    for m in (fo.edit_north_star_op_manifest(skills_root=rig["skills_root"]),
              fo.register_autoload_op_manifest(home=rig["autoload"])):
        assert m["op_kind"] == "mutate"
        assert m["write_scope"]  # an explicit, non-empty declared scope
        assert sr.validate_manifest(m) == []
    # The FULL dispatch carries the Wave-7 pair + the Wave-8 pair...
    assert set(rig["dispatch"]) == {fo.OP_SCAFFOLD, fo.OP_GEN_MANIFEST,
                                    fo.OP_EDIT_NORTH_STAR,
                                    fo.OP_REGISTER_AUTOLOAD}
    # ...ADDITIVELY: the frozen Wave-7 builder still declares exactly its pair.
    w7 = fo.control_plane_manifests(skills_root=rig["skills_root"],
                                    map_path=rig["map"],
                                    lock_path=rig["lock"])
    assert [m["skill"] for m in w7] == [fo.OP_SCAFFOLD, fo.OP_GEN_MANIFEST]


# ── (a) proposal → confirm → apply, headlessly via job_runner ────────────────

def test_north_star_round_trip_proposal_confirm_apply(rig):
    assert _scaffold(rig, "ns-demo")["ok"] is True
    sd = rig["skills_root"] / "ns-demo"
    before = (sd / "NORTH-STAR.md").read_text(encoding="utf-8")
    assert "STUB" in before
    # The scaffold seeded the hash ledger: drift-tracked from birth.
    assert (sd / "north-star-history" / "ledger.json").is_file()
    assert fns.verify_north_star(sd) == {"tracked": True, "ok": True,
                                         "reason": None}

    # PROPOSE: a diff comes back, a proposal parks, the file is untouched.
    res = _edit(rig, {"skill": "ns-demo",
                      "skills_root": str(rig["skills_root"]),
                      "mode": "propose", "new_text": NEW_TEXT})
    assert res["ok"] is True, res["reason"]
    out = res["output"]
    assert out["applied"] is False
    assert "+- make X true for the user" in out["diff"]
    pid = out["proposal_id"]
    assert (sd / "NORTH-STAR.md").read_text(encoding="utf-8") == before

    # No CONFIRM → refused BEFORE any job spawns; still unapplied.
    res = _edit(rig, {"skill": "ns-demo",
                      "skills_root": str(rig["skills_root"]),
                      "mode": "apply", "proposal_id": pid, "git": False},
                token=None)
    assert res["refused"] is True and res["reason"] == "confirm-token-missing"
    assert res["job"] is None
    assert (sd / "NORTH-STAR.md").read_text(encoding="utf-8") == before

    # CONFIRM + APPLY (headless via job_runner): the new text lands, the
    # PRIOR version is retained, and the ledger head moves with it.
    res = _edit(rig, {"skill": "ns-demo",
                      "skills_root": str(rig["skills_root"]),
                      "mode": "apply", "proposal_id": pid, "git": False})
    assert res["ok"] is True, res["reason"]
    out = res["output"]
    assert out["applied"] is True
    assert res["job"] and res["job"]["status"] == "done"
    assert (sd / "NORTH-STAR.md").read_text(encoding="utf-8") == NEW_TEXT
    prior = out["prior_retained"]
    assert prior and (sd / prior).read_text(encoding="utf-8") == before
    assert fns.verify_north_star(sd) == {"tracked": True, "ok": True,
                                         "reason": None}

    # Every dispatched op auto-journaled through the Wave-2 seam
    # (scaffold + propose + refused apply + apply).
    assert len(_ops_journal_entries(rig)) == 4


def test_apply_commits_on_branch_with_prior_retained(rig):
    if not shutil.which("git"):
        pytest.skip("git not on PATH")
    import worktrees as wt
    repo = rig["tmp"] / "foundryrepo"
    repo.mkdir()
    ok, _rc, _out, err = wt._git(repo, ["init"])
    assert ok, err
    skills_root = repo / "skills"
    skills_root.mkdir()
    (skills_root / "seed").mkdir()
    doc = {"schema": fm.MAP_SCHEMA_ID, "map_version": fm.MAP_VERSION,
           "skills": [{"ref": "skill:seed", "name": "seed",
                       "source": (skills_root / "seed").as_posix(),
                       "status": "4 - Beta", "tier": "standard",
                       "version": "1.0.0", "edges": []}]}
    map_path = repo / "map.json"
    map_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    lock_path = repo / "map.lock.json"
    fm.write_lockfile(doc, path=lock_path)
    assert fo.scaffold_skill("branchy", skills_root=skills_root,
                             map_path=map_path, lock_path=lock_path,
                             git=False)["ok"] is True
    sd = skills_root / "branchy"
    before = (sd / "NORTH-STAR.md").read_text(encoding="utf-8")

    prop = fo.edit_north_star("branchy", skills_root=skills_root,
                              mode="propose", new_text=NEW_TEXT)
    assert prop["ok"] is True, prop
    res = fo.edit_north_star("branchy", skills_root=skills_root, mode="apply",
                             proposal_id=prop["proposal_id"], git=True)
    assert res["ok"] is True, res
    git_report = res["git"]
    assert git_report["committed"] is True
    assert git_report["branch"] == "foundry/north-star-branchy"
    ok, _rc, head, _err = wt._git(repo, ["rev-parse", "--abbrev-ref", "HEAD"])
    assert ok and head.strip() == "foundry/north-star-branchy"
    ok, _rc, log, _err = wt._git(repo, ["log", "--oneline", "-1"])
    assert ok and "foundry.edit_north_star: branchy" in log
    # HISTORY PRESERVED: the prior version is a retained, COMMITTED file.
    prior = res["prior_retained"]
    assert prior and (sd / prior).read_text(encoding="utf-8") == before
    ok, _rc, tracked, _err = wt._git(
        repo, ["ls-tree", "-r", "--name-only", "HEAD"])
    assert ok and prior.split("/")[-1] in tracked

    # A SECOND edit stacks on the SAME branch (an existing branch is switched
    # to, never a failure) and retains its own prior version.
    prop2 = fo.edit_north_star("branchy", skills_root=skills_root,
                               mode="propose", new_text=NEW_TEXT + "- more\n")
    res2 = fo.edit_north_star("branchy", skills_root=skills_root,
                              mode="apply", proposal_id=prop2["proposal_id"],
                              git=True)
    assert res2["ok"] is True and res2["git"]["committed"] is True
    assert res2["git"]["branch"] == "foundry/north-star-branchy"
    priors = sorted((sd / "north-star-history").glob("NORTH-STAR-*.md"))
    assert len(priors) == 2


def test_edit_refusals_are_honest(rig):
    assert _scaffold(rig, "stale-demo")["ok"] is True
    sd = rig["skills_root"] / "stale-demo"
    root = str(rig["skills_root"])

    # Unknown skill / bad slug / missing text / bad mode / unknown proposal.
    assert fo.edit_north_star("nope", skills_root=root, mode="propose",
                              new_text="x")["reason"].startswith(
        "unknown-skill:")
    assert fo.edit_north_star("Bad Name!", skills_root=root, mode="propose",
                              new_text="x")["reason"].startswith(
        "invalid-skill-name:")
    assert fo.edit_north_star("stale-demo", skills_root=root,
                              mode="propose")["reason"] == "new-text-missing"
    assert fo.edit_north_star("stale-demo", skills_root=root, mode="sideways",
                              new_text="x")["reason"].startswith(
        "unknown-mode:")
    assert fo.edit_north_star("stale-demo", skills_root=root, mode="apply",
                              proposal_id="nsp-doesnotexist")[
        "reason"].startswith("unknown-proposal:")

    # A no-change proposal refuses (there is nothing to confirm).
    same = (sd / "NORTH-STAR.md").read_text(encoding="utf-8")
    assert fo.edit_north_star("stale-demo", skills_root=root, mode="propose",
                              new_text=same)["reason"] == "proposal-no-change"

    # STALE: the file changed between proposal and apply → refused unapplied
    # (the approval does not transfer to a state the human never saw).
    prop = fo.edit_north_star("stale-demo", skills_root=root, mode="propose",
                              new_text=NEW_TEXT)
    assert prop["ok"] is True
    (sd / "NORTH-STAR.md").write_text("out-of-band edit\n", encoding="utf-8")
    res = fo.edit_north_star("stale-demo", skills_root=root, mode="apply",
                             proposal_id=prop["proposal_id"], git=False)
    assert res["reason"] == "north-star-changed-since-proposal"
    assert (sd / "NORTH-STAR.md").read_text(
        encoding="utf-8") == "out-of-band edit\n"


# ── (b) the drift gates: out-of-band writes FAIL, by name ────────────────────

def test_drift_gate_fails_on_out_of_band_write(rig):
    assert _scaffold(rig, "guarded-demo")["ok"] is True
    sd = rig["skills_root"] / "guarded-demo"
    doc = fm.load_map(rig["map"])

    gate = fns.gate_ledger(doc, root=rig["tmp"])
    assert gate["ok"] is True, gate
    assert gate["checked"] == 2 and gate["tracked"] == 1  # gandalf untracked

    # A SANCTIONED round-trip keeps the gate green.
    prop = fo.edit_north_star("guarded-demo",
                              skills_root=str(rig["skills_root"]),
                              mode="propose", new_text=NEW_TEXT)
    assert fo.edit_north_star("guarded-demo",
                              skills_root=str(rig["skills_root"]),
                              mode="apply", proposal_id=prop["proposal_id"],
                              git=False)["ok"] is True
    assert fns.gate_ledger(doc, root=rig["tmp"])["ok"] is True

    # A DIRECT out-of-band write FAILS the gate, by name.
    (sd / "NORTH-STAR.md").write_text("silent drift\n", encoding="utf-8")
    gate = fns.gate_ledger(doc, root=rig["tmp"])
    assert gate["ok"] is False
    assert ("north-star-drift:skill:guarded-demo:out-of-band-write"
            in gate["problems"])
    # ...and a DELETED tracked North Star fails too.
    (sd / "NORTH-STAR.md").unlink()
    gate = fns.gate_ledger(doc, root=rig["tmp"])
    assert ("north-star-drift:skill:guarded-demo:north-star-deleted"
            in gate["problems"])


def test_source_grep_gate_flags_rogue_writers(tmp_path):
    # The REAL product tree is clean: the only NORTH-STAR.md writers are the
    # sanctioned modules (the mutation core + the scaffold stub writer).
    assert fns.scan_out_of_band_writers() == []
    assert fns.gate_source()["ok"] is True

    # A rogue writer module is flagged, line-accurate; a sanctioned module
    # name is allowlisted.
    rogue = ('from pathlib import Path\n'
             'Path("NORTH-STAR.md").write_text("drift", encoding="utf-8")\n')
    (tmp_path / "rogue.py").write_text(rogue, encoding="utf-8")
    (tmp_path / "foundry_ops.py").write_text(rogue, encoding="utf-8")
    offenders = fns.scan_out_of_band_writers(root=tmp_path)
    assert len(offenders) == 1 and offenders[0].startswith("rogue.py:2:")
    gate = fns.gate_source(root=tmp_path)
    assert gate["ok"] is False
    assert gate["problems"][0].startswith(
        "out-of-band-north-star-writer:rogue.py:2:")
    # run_north_star_gates composes both (the Wave-6 run_drift_gates shape).
    combined = fns.run_north_star_gates(
        {"schema": fm.MAP_SCHEMA_ID, "map_version": fm.MAP_VERSION,
         "skills": []}, source_root=tmp_path)
    assert combined["ok"] is False


# ── (c) auto-load registration from map.json v2 alone ────────────────────────

def test_autoload_registration_from_map_alone(rig):
    assert _scaffold(rig, "clicky-demo")["ok"] is True

    # Unapproved → refused before any job; the registry stays absent.
    res = fo.run_control_op(rig["dispatch"], fo.OP_REGISTER_AUTOLOAD,
                            payload={"map_path": str(rig["map"]),
                                     "home": str(rig["autoload"])})
    assert res["refused"] is True and res["job"] is None
    assert fa.clickable_skills(home=rig["autoload"]) == []

    # CONFIRM + sync (headless via job_runner): the scaffolded skill appears
    # in Anchor's clickable set from map.json v2 alone.
    token = sr.issue_confirm_token(fo.OP_REGISTER_AUTOLOAD)
    res = fo.run_control_op(rig["dispatch"], fo.OP_REGISTER_AUTOLOAD,
                            payload={"map_path": str(rig["map"]),
                                     "home": str(rig["autoload"])},
                            confirm_token=token)
    assert res["ok"] is True, res["reason"]
    assert res["job"] and res["job"]["status"] == "done"
    assert res["output"]["count"] == 2

    regs = {r["ref"]: r for r in fa.clickable_skills(home=rig["autoload"])}
    assert set(regs) == {"skill:gandalf", "skill:clicky-demo"}
    clicky = regs["skill:clicky-demo"]
    assert clicky["clickable"] is True and clicky["runnable"] is True
    assert clicky["panel"]["title"] == "Clicky Demo"
    assert clicky["version"] == "0.1.0"
    # gandalf's seed dir has no manifest → clickable, honestly not runnable.
    gandalf = regs["skill:gandalf"]
    assert gandalf["runnable"] is False
    assert gandalf["reason"] == "manifest-missing"
    assert fa.is_clickable("clicky-demo", home=rig["autoload"]) is True
    assert fa.is_clickable("no-such", home=rig["autoload"]) is False

    # A REGENERATED projection: a skill dropped from the map drops out.
    out = fa.sync_registrations(map_doc=rig["seed_doc"],
                                home=rig["autoload"])
    assert out["ok"] is True and out["count"] == 1
    assert fa.is_clickable("clicky-demo", home=rig["autoload"]) is False

    # An INVALID map refuses without touching the registry.
    out = fa.sync_registrations(map_doc={"schema": "nope"},
                                home=rig["autoload"])
    assert out["ok"] is False and out["reason"].startswith("map-invalid:")
    assert fa.is_clickable("gandalf", home=rig["autoload"]) is True
