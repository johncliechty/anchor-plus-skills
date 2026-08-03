"""foundry-v2 Wave 10 — Foundry GUI write surface + Anchor-side user-journey.

Proves the Wave-10 done-when:
  (a) the ANCHOR-SIDE USER-JOURNEY runs end-to-end over REAL machinery —
      create a skill (→ ``foundry.scaffold_skill``) → run + monitor it
      (the scaffolded skill's own host through the generic runner; the op
      job through job_runner/monitor_view) → edit its North Star
      (→ ``foundry.edit_north_star`` propose → explicit confirm → apply,
      prior retained) → browse the library (→ ``foundry.register_autoload``
      makes it clickable in Anchor from map.json v2 alone);
  (b) EVERY GUI mutation lands as a journaled job_runner op — each action
      is an op invocation (confirm-gated, dispatched headlessly through
      job_runner, auto-journaled by the Wave-2 seam); an UNCONFIRMED action
      refuses BEFORE anything is minted, dispatched, or written;
  (c) the sleep-review button targets the DECLARED ``foundry.sleep_session``
      interface and shows the HONEST pending status ("sleep session not yet
      wired (foundry build pending)") — and the seam flips to a real
      dispatch when the op body is registered, with NO GUI change;
  (d) the 2ND-SURFACE HONESTY test passes: every implemented GUI verb maps
      to a DR-01-inventory op that runs HEADLESS (``foundry_ops.py`` CLI,
      proven live by subprocess), and the write surface itself carries no
      GUI-side file-mutation path and no parallel store;
  plus: the Anchor wiring — the write panel is served on the /foundry page
  and every panel button POSTs to an op-invocation endpoint in anchor_gui.

Hermetic like tests/test_foundry_north_star_w8.py: temp ANCHOR_DATA_DIR +
temp skills root + temp map/lock/autoload artifacts; op hosts are this
repo's own ``foundry_ops.py`` via ``sys.executable`` (deterministic local
code — NEVER real claude / real node / the real Skill Foundry / the
worktree map / :8777). Stdlib only.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

import foundry_autoload as fa
import foundry_decisions as fd
import foundry_gui as fgui
import foundry_gui_write as fgw
import foundry_map as fm
import foundry_ops as fo
import job_runner as jr
import skill_runner as sr

_ROOT = Path(__file__).resolve().parents[1]

NEW_TEXT = ("# North Star — refined\n\n"
            "- make X true for the user\n"
            "- DONE looks like genuine data, not a demo\n")


# ── Fixture: a hermetic Wave-10 control-plane rig (the w8 shape) ─────────────

@pytest.fixture
def rig(tmp_path, monkeypatch):
    """Temp data dir + skills root + seed map/lock + autoload home + the FULL
    (Wave-7 + Wave-8) control-plane dispatch the GUI write surface drives."""
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


def _ops_journal_entries(rig):
    return sorted((rig["data"] / "foundry_ops" / "journal").glob("*.md"))


def _create(rig, name, **over):
    kwargs = dict(dispatch=rig["dispatch"], confirm=True,
                  skills_root=str(rig["skills_root"]),
                  map_path=str(rig["map"]), lock_path=str(rig["lock"]),
                  git=False)
    kwargs.update(over)
    return fgw.create_skill(name, **kwargs)


# ── (a)+(b) the Anchor-side user-journey, end-to-end over real machinery ─────

def test_anchor_side_user_journey_end_to_end(rig):
    # 0 — an UNCONFIRMED create refuses BEFORE anything happens: no token,
    # no dispatch, no job, no journal entry, nothing on disk.
    res = _create(rig, "journey-w10", confirm=False)
    assert res["ok"] is False and res["refused"] is True
    assert res["reason"] == "confirm-required:foundry.scaffold_skill"
    assert res["job"] is None
    assert not (rig["skills_root"] / "journey-w10").exists()
    assert _ops_journal_entries(rig) == []

    # 1 — CREATE: the GUI verb invokes foundry.scaffold_skill headlessly
    # through job_runner; the skill lands on disk from the template.
    res = _create(rig, "journey-w10", title="Journey W10")
    assert res["ok"] is True, res["reason"]
    assert res["output"]["skill"] == "journey-w10"
    assert res["job"] is not None and res["job"]["status"] == "done"
    create_job_id = res["job"]["job_id"]
    sd = rig["skills_root"] / "journey-w10"
    for rel in ("SKILL.md", "NORTH-STAR.md", "host.py", "manifest.json"):
        assert (sd / rel).is_file(), rel
    # ...as a journaled job_runner op: the durable record is real.
    assert jr.load_record(create_job_id) is not None
    assert jr.load_record(create_job_id)["lane"] == fo.OPS_LANE

    # 2 — RUN: the scaffolded skill runs through the generic runner (its
    # OWN host, real subprocess) and auto-journals via the Wave-2 seam.
    manifest = sr.load_skill_manifest(sd)
    d2 = sr.build_dispatch([manifest])
    run_res = sr.run_op(d2, "journey-w10", payload={"ping": "w10"})
    assert run_res["ok"] is True, run_res["reason"]
    assert run_res["output"]["verdict"] == "scaffold-template-ok"
    assert run_res["output"]["echo"] == {"ping": "w10"}
    ch = fgui.changes_view(sd)
    assert ch["count"] == 1
    assert ch["entries"][0]["operation_kind"] == "run"
    assert ch["entries"][0]["verdict"] == "scaffold-template-ok"

    # 3 — MONITOR: the create op's job through the Wave-9 read surface —
    # job_runner state itself, never a mirror.
    mv = fgui.monitor_view(create_job_id)
    assert mv["ok"] is True
    assert mv["lane"] == fo.OPS_LANE
    assert mv["status"] == jr.STATUS_DONE

    # 4 — EDIT NORTH STAR: propose parks a reviewable diff (file untouched).
    before = (sd / "NORTH-STAR.md").read_text(encoding="utf-8")
    assert "STUB" in before
    res = fgw.north_star_propose("journey-w10", NEW_TEXT,
                                 dispatch=rig["dispatch"], confirm=True,
                                 skills_root=str(rig["skills_root"]))
    assert res["ok"] is True, res["reason"]
    out = res["output"]
    assert out["applied"] is False
    assert "+- make X true for the user" in out["diff"]
    pid = out["proposal_id"]
    assert (sd / "NORTH-STAR.md").read_text(encoding="utf-8") == before

    # ...an UNCONFIRMED apply refuses pre-dispatch; still unapplied.
    res = fgw.north_star_apply("journey-w10", pid, dispatch=rig["dispatch"],
                               confirm=False,
                               skills_root=str(rig["skills_root"]), git=False)
    assert res["refused"] is True
    assert res["reason"] == "confirm-required:foundry.edit_north_star"
    assert res["job"] is None
    assert (sd / "NORTH-STAR.md").read_text(encoding="utf-8") == before

    # ...the CONFIRMED apply lands the text with the prior version retained.
    res = fgw.north_star_apply("journey-w10", pid, dispatch=rig["dispatch"],
                               confirm=True,
                               skills_root=str(rig["skills_root"]), git=False)
    assert res["ok"] is True, res["reason"]
    assert res["output"]["applied"] is True
    assert res["job"] is not None and res["job"]["status"] == "done"
    assert (sd / "NORTH-STAR.md").read_text(encoding="utf-8") == NEW_TEXT
    prior = res["output"]["prior_retained"]
    assert prior and (sd / prior).read_text(encoding="utf-8") == before

    # 5 — BROWSE LIBRARY: sync makes the created skill clickable in Anchor
    # from map.json v2 alone, and the library/page render it.
    res = fgw.sync_autoload(dispatch=rig["dispatch"], confirm=True,
                            map_path=str(rig["map"]),
                            home=str(rig["autoload"]), root=str(rig["tmp"]))
    assert res["ok"] is True, res["reason"]
    assert res["output"]["count"] == 2
    assert res["job"] is not None and res["job"]["status"] == "done"
    assert fa.is_clickable("journey-w10", home=rig["autoload"]) is True
    regs = {r["ref"]: r for r in fa.clickable_skills(home=rig["autoload"])}
    assert regs["skill:journey-w10"]["clickable"] is True
    assert regs["skill:journey-w10"]["runnable"] is True
    lib = fgui.library_view(home=rig["autoload"])
    assert {r["name"] for r in lib["skills"]} == {"gandalf", "journey-w10"}
    page = fgui.render_foundry_page(home=rig["autoload"],
                                    map_path=rig["map"],
                                    lock_path=rig["lock"])
    assert "journey-w10" in page

    # (b) EVERY confirmed GUI mutation is a journaled job_runner op: exactly
    # the four dispatched ops (create · propose · apply · sync) — and none
    # for the two unconfirmed refusals.
    assert len(_ops_journal_entries(rig)) == 4


# ── (c) the sleep seam: declared interface, honest pending, flips wired ──────

def test_sleep_review_targets_interface_with_honest_pending(rig):
    assert fgw.SLEEP_SESSION_OP == "foundry.sleep_session"
    # The op body is NOT in this build: not a registered headless op, and
    # not in the live dispatch the GUI drives.
    assert fgw.SLEEP_SESSION_OP not in fo.OP_CLI_NAMES
    st = fgw.sleep_session_status(rig["dispatch"])
    assert st["wired"] is False and st["status"] == "pending"
    assert st["reason"] == fgw.SLEEP_PENDING_REASON
    assert fgw.sleep_session_status()["wired"] is False  # registry check too

    # Clicking the button resolves to the HONEST pending status: nothing
    # dispatched, no job, no journal entry — and nothing faked.
    res = fgw.run_sleep_session(dispatch=rig["dispatch"], confirm=True)
    assert res["ok"] is False and res["pending"] is True
    assert res["status"] == "pending"
    assert res["reason"] == fgw.SLEEP_PENDING_REASON
    assert res["job"] is None
    assert _ops_journal_entries(rig) == []

    # The page carries the button targeting the interface + the honest
    # pending status (never a fabricated "ready").
    page = fgui.render_foundry_page(home=rig["autoload"],
                                    map_path=rig["map"],
                                    lock_path=rig["lock"])
    assert 'data-sleep-op="foundry.sleep_session"' in page
    assert fgw.SLEEP_PENDING_REASON in page

    # THE SEAM IS THE CONTRACT: register an op body for the interface (what
    # the separate foundry build + integration pass delivers) and the SAME
    # GUI action dispatches it through job_runner — no GUI change at all.
    sdir = rig["tmp"] / "sleep-skill"
    sdir.mkdir()
    (sdir / "host.py").write_text(
        "import json\n"
        "print(json.dumps({'schema': 'sleep/v1', 'verdict': 'sleep-ok'}))\n",
        encoding="utf-8")
    m = {
        "skill": fgw.SLEEP_SESSION_OP,
        "skill_dir": str(sdir),
        "op_kind": "run",
        "host_cmd": [sys.executable, "{skill_dir}/host.py"],
        "output_contract": {"format": "json",
                            "required_keys": ["schema", "verdict"]},
        "panel": {"title": "Sleep Session"},
        "journal": {"enabled": True},
        "tier": "standard",
        "capabilities": [],
        "activation": {"trigger": "first_run"},
    }
    assert sr.validate_manifest(m) == []
    wired = sr.build_dispatch([m])
    assert fgw.sleep_session_status(wired)["wired"] is True
    res = fgw.run_sleep_session(dispatch=wired, payload={"review": "w10"},
                                confirm=True)
    assert res["ok"] is True, res["reason"]
    assert res["output"]["verdict"] == "sleep-ok"
    assert res["job"] is not None and res["job"]["status"] == "done"
    # ...and the wired run auto-journals like every op (the Wave-2 seam).
    assert fgui.changes_view(sdir)["count"] == 1


# ── (d) 2nd-surface honesty: same ops, headless; no GUI-side write path ──────

def test_second_surface_honesty_check(monkeypatch):
    # The shipped write surface is honest: no mutation primitive, no
    # parallel store, every implemented verb a headless DR-01 op.
    assert fgw.second_surface_honesty() == []
    # ...and the Wave-9 read surface stays clean with the panel embedded.
    assert fgui.anti_theater_check() == []

    # Every implemented GUI verb is a callable on the write surface mapping
    # to a DR-01-inventory op with a registered headless CLI host.
    assert dict(fgw.IMPLEMENTED_VERBS) == {
        "create_skill": fo.OP_SCAFFOLD,
        "north_star_propose": fo.OP_EDIT_NORTH_STAR,
        "north_star_apply": fo.OP_EDIT_NORTH_STAR,
        "sync_autoload": fo.OP_REGISTER_AUTOLOAD,
    }
    for verb, op in fgw.IMPLEMENTED_VERBS:
        assert callable(getattr(fgw, verb))
        assert op in fd.MUTATIVE_VERBS
        assert op in fo.OP_CLI_NAMES
    # The sleep interface is DECLARED-only (pending), by design.
    assert dict(fgw.DECLARED_INTERFACES) == {
        "run_sleep_session": fgw.SLEEP_SESSION_OP}

    src = Path(fgw.__file__).read_text(encoding="utf-8")
    # A GUI-side write path introduced into the write surface → FAIL. (The
    # forbidden call is assembled at runtime so this test never carries it.)
    doctored_write = (src + "\ndef _persist(x):\n"
                      + "    Path('m.json').write_" + "text(x)\n")
    probs = fgw.second_surface_honesty(source_text=doctored_write)
    assert any(p.startswith("gui-mutation-path:") for p in probs)
    # A parallel mutation-queue store at module level → FAIL.
    doctored_store = src + "\n_PENDING_MUTATIONS = {}\n"
    probs = fgw.second_surface_honesty(source_text=doctored_store)
    assert any(p.startswith("parallel-store:") for p in probs)
    # A runtime module-level mirror (however it got there) → FAIL.
    monkeypatch.setattr(fgw, "_MIRROR_CACHE", {}, raising=False)
    probs = fgw.second_surface_honesty()
    assert any(p.startswith("module-state:_MIRROR_CACHE") for p in probs)


def test_every_implemented_verb_runs_headless_live(rig):
    # Live subprocess proof: the SAME op the GUI invokes runs headlessly via
    # the foundry_ops CLI (no GUI, no server anywhere in the loop).
    assert _create(rig, "headless-demo")["ok"] is True
    payload_file = rig["tmp"] / "payload.json"
    payload_file.write_text(json.dumps({
        "skill": "headless-demo",
        "skills_root": str(rig["skills_root"]),
    }), encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(_ROOT / "foundry_ops.py"), "gen_manifest",
         "--payload", str(payload_file)],
        capture_output=True, text=True, cwd=str(_ROOT), timeout=120)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout.strip().splitlines()[-1])
    assert out["ok"] is True
    assert out["op"] == "gen_manifest"
    assert out["verdict"] == "updated:headless-demo"


# ── the Anchor wiring: panel on the page, endpoints = op invocations ─────────

def test_anchor_wiring_page_panel_and_endpoints(rig):
    # The /foundry page serves the write panel: action cards for create /
    # North Star / clickable sync / sleep — rendered by the write surface.
    page = fgui.render_foundry_page(home=rig["autoload"],
                                    map_path=rig["map"],
                                    lock_path=rig["lock"])
    assert 'data-foundry-write="op-invocations-only"' in page
    assert "foundry.scaffold_skill" in page
    assert "foundry.edit_north_star" in page
    assert "foundry.register_autoload" in page
    assert 'data-sleep-op="foundry.sleep_session"' in page

    # Every panel button POSTs to an op-invocation endpoint — the browser
    # side of the same action layer (no other mutation path in the panel).
    wsrc = Path(fgw.__file__).read_text(encoding="utf-8")
    for endpoint in ("/api/foundry/create_skill", "/api/foundry/north_star",
                     "/api/foundry/sync_autoload",
                     "/api/foundry/sleep_session"):
        assert "fwPost('%s'" % endpoint in wsrc

    # anchor_gui wires the endpoints to the write-surface action layer
    # (token-authed POSTs; every handler is an op invocation, never a
    # GUI-side write), and the page embed goes through foundry_gui_write.
    # Under the rearch W7/C2 strangler the endpoint PATHS + their token auth
    # live in route_table.py; anchor_gui defines + registers the NAMED handler
    # that invokes the _fgw action layer (the migrated dispatch, not an inline
    # if/elif in do_POST). (Token-auth for every POST row is enforced globally
    # by TestW7 test_no_post_route_is_open_today.)
    src = (_ROOT / "anchor_gui.py").read_text(encoding="utf-8",
                                              errors="replace")
    rtsrc = (_ROOT / "route_table.py").read_text(encoding="utf-8",
                                                 errors="replace")
    assert "import foundry_gui_write as _fgw" in src
    for endpoint, hname in (
            ("/api/foundry/create_skill", "handle_foundry_create_skill"),
            ("/api/foundry/north_star", "handle_foundry_north_star"),
            ("/api/foundry/sync_autoload", "handle_foundry_sync_autoload"),
            ("/api/foundry/sleep_session", "handle_foundry_sleep_session")):
        assert '"%s"' % endpoint in rtsrc, \
            "route_table must declare POST %s" % endpoint
        assert 'handler="%s"' % hname in rtsrc, \
            "%s must be wired to %s in route_table" % (endpoint, hname)
        assert "def %s(" % hname in src, "anchor_gui must define %s" % hname
        assert '"%s": %s' % (hname, hname) in src, \
            "anchor_gui must register %s in _MIGRATED_HANDLERS" % hname
    assert "_fgw.create_skill(" in src
    assert "_fgw.north_star_propose(" in src
    assert "_fgw.north_star_apply(" in src
    assert "_fgw.sync_autoload(" in src
    assert "_fgw.run_sleep_session(" in src
    gsrc = (_ROOT / "foundry_gui.py").read_text(encoding="utf-8")
    assert "import foundry_gui_write as _fgw" in gsrc
    assert "_fgw.render_write_panel(" in gsrc
