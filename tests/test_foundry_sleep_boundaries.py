"""The propose → apply → rollback BOUNDARY of ``foundry_api`` (2026-10-10 repair).

Proven here through the real API functions on disposable git fixtures:

* manifest routing — an EXTERNAL manifest skill (the ``C:/dev/trio/foreman``
  shape: an absolute source outside the Foundry root) resolves to its OWN
  owning repository, a relative source resolves under the Foundry root, the
  tile-posted basename / the ``ref`` / the ``name`` all select the same entry,
  and an unknown or missing skill is an honest 404 (the old
  ``SKILLS_ROOT/<name>`` assumption is gone);
* isolation — every proposal gets its OWN private candidate clone detached at
  the frozen source HEAD (fresh ``.git``, no remote, no shared worktree
  metadata, only committed state), the kernel is handed the candidate for
  ``--repo`` / ``--work-repo``, and the canonical checkout's HEAD, index,
  dirty and untracked files are byte-identical through propose / apply / a
  blocked apply / rollback;
* binding — apply/rollback re-bind the proposal to its server-owned receipt:
  a tampered unit, gate or change target, a copied/unreceipted proposal, a
  path escape, a junction/symlink in the runs dir, a dirty or stale candidate
  are all REFUSED before the kernel runs, and nothing is reset;
* honesty — ``confirm: true`` is required; a kernel ``blocked`` / ``refused``
  / failed / timed-out outcome is never HTTP 200; "applied" is reported as a
  candidate branch, never an install;
* containment — the launcher runs its child inside the existing kill-on-close
  containment with no console window, and a timeout leaves no orphaned
  grandchild.

The kernel-free tests substitute ``foundry_api._run_kernel`` with a Python
stand-in that writes the kernel's exact artifact shapes (so they run wherever
git does). The ``live_kernel`` tests drive the REAL ``sleep-kernel-cli.mjs``
(node + the kernel checkout required; skipped otherwise) — still against the
disposable fixtures: never the installed Skill Foundry / trio, never :8777.
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import foundry_api as fa


def g(repo, *args, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                          text=True, check=check)


def _init_repo(path):
    path.mkdir(parents=True, exist_ok=True)
    for a in (["init", "-q"], ["config", "user.email", "t@t"], ["config", "user.name", "t"],
              ["config", "commit.gpgsign", "false"], ["config", "core.autocrlf", "false"]):
        g(path, *a)


def host_entry(entry_id, session, project):
    """Two of these with distinct sessions AND non-fixture project ids form the
    kernel's one cross-context corroborated candidate (its own test fixture)."""
    return ("---\n"
            "id: %s\n"
            "entry_schema: 1\n"
            "ts: 1783422029.1\n"
            "provenance: host-enforced:test.demoskill\n"
            "operation_kind: run\n"
            'verdict_timing: {"verdict":"promote-ready","started_ts":1,"duration_s":2}\n'
            'outcome_linkage: {"outcome":"worked","project_id":"%s","run_id":"%s",'
            '"session_id":"%s","reason":"clean"}\n'
            "---\n\nhost-emitted skeleton\n" % (entry_id, project, entry_id, session))


GATE_GREEN = ("import { test } from 'node:test';\n"
              "import assert from 'node:assert/strict';\n"
              "test('frozen gate: fixture is green', () => { assert.ok(true); });\n")

# Green at propose time, RED once the kernel appends a lesson marker to
# LESSONS.md — the honest way to make the REAL kernel block (gate regressed →
# its automatic rollback of the candidate).
GATE_RED_AFTER_LESSON = (
    "import { test } from 'node:test';\n"
    "import assert from 'node:assert/strict';\n"
    "import fs from 'node:fs';\n"
    "import path from 'node:path';\n"
    "import { fileURLToPath } from 'node:url';\n"
    "const here = path.dirname(fileURLToPath(import.meta.url));\n"
    "test('frozen gate: no sleep lesson may land', () => {\n"
    "  const lessons = fs.readFileSync(path.join(here, '..', 'LESSONS.md'), 'utf8');\n"
    "  assert.ok(!lessons.includes('<!-- sleep:'), 'a lesson landed - the gate regresses');\n"
    "});\n")


def _write_skill(repo, rel, gate=GATE_GREEN):
    d = repo / rel
    (d / "journal").mkdir(parents=True)
    (d / "test").mkdir()
    (d / "SKILL.md").write_text("---\ndescription: fixture skill\n---\n# fixture\n", encoding="utf-8")
    (d / "LESSONS.md").write_text("# Lessons\n\n(seed)\n", encoding="utf-8")
    (d / "journal" / "run-aaa.md").write_text(host_entry("run-aaa", "sess-a", "real-1"), encoding="utf-8")
    (d / "journal" / "run-bbb.md").write_text(host_entry("run-bbb", "sess-b", "real-2"), encoding="utf-8")
    (d / "test" / "gate.test.mjs").write_text(gate, encoding="utf-8")
    return d


def snapshot(repo):
    """Everything the boundary must leave alone: HEAD, branches, the index, the
    working tree's dirty + untracked state, any linked-worktree metadata, and
    the on-disk bytes of every file."""
    files = {}
    for p in sorted(repo.rglob("*")):
        if p.is_file() and ".git" not in p.parts:
            files[p.relative_to(repo).as_posix()] = p.read_bytes()
    wt_dir = repo / ".git" / "worktrees"
    return {
        "head": g(repo, "rev-parse", "HEAD").stdout.strip(),
        "branches": g(repo, "branch", "--list", "--all").stdout,
        "status": g(repo, "status", "--porcelain", "--untracked-files=all").stdout,
        "index": g(repo, "diff", "--cached").stdout,
        "worktrees": sorted(os.listdir(wt_dir)) if wt_dir.exists() else [],
        "files": files,
    }


@pytest.fixture
def rig(tmp_path, monkeypatch):
    trio = tmp_path / "trio"  # the EXTERNAL canonical repo (the C:/dev/trio shape)
    _init_repo(trio)
    _write_skill(trio, "foreman")
    _write_skill(trio, "crucible", gate=GATE_RED_AFTER_LESSON)
    (trio / "other.txt").write_text("unrelated\n", encoding="utf-8")
    g(trio, "add", "-A")
    g(trio, "commit", "-qm", "frozen")
    head = g(trio, "rev-parse", "HEAD").stdout.strip()
    # The installed checkout's WORKING STATE — never touched, never carried along.
    (trio / "other.txt").write_text("an unstaged edit\n", encoding="utf-8")
    (trio / "staged.txt").write_text("a staged file\n", encoding="utf-8")
    g(trio, "add", "staged.txt")
    (trio / "untracked.txt").write_text("an untracked file\n", encoding="utf-8")

    foundry = tmp_path / "Skill Foundry"  # the relative-source root, itself a repo
    _init_repo(foundry)
    _write_skill(foundry, "skills/gandalf")
    g(foundry, "add", "-A")
    g(foundry, "commit", "-qm", "frozen")

    manifest = {"schema": "foundry-map/v2", "map_version": 2, "skills": [
        {"ref": "skill:foreman", "name": "foreman", "source": (trio / "foreman").as_posix(), "edges": []},
        {"ref": "skill:crucible", "name": "crucible", "source": (trio / "crucible").as_posix(), "edges": []},
        {"ref": "skill:gandalf", "name": "gandalf", "source": "skills/gandalf", "edges": []},
        {"ref": "skill:research-prime", "name": "researchPrime",
         "source": (trio / "researchPrime").as_posix(), "edges": []},  # in the manifest, NOT on disk
    ]}
    map_path = tmp_path / "foundry_map_v2.json"
    map_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    monkeypatch.setattr(fa, "MANIFEST_PATH", map_path)
    monkeypatch.setattr(fa, "FOUNDRY_ROOT", str(foundry))
    monkeypatch.setattr(fa, "SKILLS_ROOT", str(foundry / "skills"))  # has NO foreman/crucible
    monkeypatch.setattr(fa, "SKILLS_REPO", str(foundry))
    monkeypatch.setattr(fa, "SLEEP_RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(fa, "SLEEP_CANDIDATES_DIR", tmp_path / "candidates")
    monkeypatch.setattr(fa, "SLEEP_RECEIPTS_DIR", tmp_path / "receipts")
    return SimpleNamespace(tmp=tmp_path, trio=trio, head=head, foundry=foundry,
                           runs=tmp_path / "runs", candidates=tmp_path / "candidates",
                           receipts=tmp_path / "receipts", before=snapshot(trio))


class FakeKernel:
    """A Python stand-in for ``sleep-kernel-cli.mjs``: writes the kernel's EXACT
    propose artifact shapes from the argv it is handed and answers apply /
    rollback with configurable kernel records, so the binding layer is
    exercised without node. Records every call."""

    def __init__(self, apply_outcome="applied", rollback_outcome="restored",
                 spawn_error=None, timed_out=False):
        self.apply_outcome, self.rollback_outcome = apply_outcome, rollback_outcome
        self.spawn_error, self.timed_out = spawn_error, timed_out
        self.calls = []
        self.n = 0

    def __call__(self, args):
        args = [str(a) for a in args]
        self.calls.append(args)
        if self.spawn_error:
            return {"status": None, "spawnError": self.spawn_error, "timedOut": False,
                    "stdout": "", "stderr": "", "contained": False}
        if self.timed_out:
            return {"status": None, "spawnError": None, "timedOut": True,
                    "stdout": "", "stderr": "", "contained": True}
        opts = {args[i]: args[i + 1] for i in range(2, len(args) - 1, 2) if args[i].startswith("--")}
        verb = args[0]
        if verb == "propose":
            return self._ok(self._propose(args[1], opts))
        if verb == "apply":
            return self._ok(self._apply(args[1], opts))
        if verb == "rollback":
            return self._ok(self._rollback(args[1], opts))
        raise AssertionError("unexpected kernel verb %r" % verb)

    @staticmethod
    def _ok(record):
        return {"status": record["exitCode"], "spawnError": None, "timedOut": False,
                "stdout": json.dumps(record), "stderr": "", "contained": True}

    def _propose(self, skill_dir, opts):
        repo, runs, corpus = opts["--repo"], opts["--runs-dir"], opts["--corpus"]
        sha = g(repo, "rev-parse", "HEAD").stdout.strip()
        skill = os.path.basename(skill_dir)
        self.n += 1
        ts = time.time_ns() // 1_000_000 + self.n
        pdir = os.path.join(runs, "%s-%d" % (skill, ts))
        slug, situation = "run-promote-ready", "run/promote-ready"
        marker = "<!-- sleep:%s -->" % slug
        unit_dir = os.path.join(pdir, "units", slug)
        os.makedirs(unit_dir, exist_ok=True)
        lessons_file = os.path.relpath(os.path.join(skill_dir, "LESSONS.md"), repo).replace(os.sep, "/")
        addition = ("- **%s** — corroborated across 2 distinct context(s) (2 genuine run(s)): "
                    "promote-ready — clean %s\n" % (situation, marker))
        paths = {key: os.path.join(unit_dir, name) for key, name in fa._UNIT_FILES}
        Path(paths["diffPath"]).write_text(
            "--- a/%s\n+++ b/%s\n@@ sleep-session append @@\n+%s\n"
            % (lessons_file, lessons_file, addition.rstrip("\n")), encoding="utf-8")
        Path(paths["changePath"]).write_text(json.dumps(
            {"file": lessons_file, "mode": "append", "content": addition, "marker": marker},
            indent=2) + "\n", encoding="utf-8")
        Path(paths["regressionPath"]).write_text("// regression test stand-in\n", encoding="utf-8")
        Path(paths["provenancePath"]).write_text(
            json.dumps({"class": "frozen_benchmark_delta"}, indent=2) + "\n", encoding="utf-8")
        test_files = fa._frozen_benchmark_files(skill_dir)
        gate = {"command": 'node --test --test-reporter=tap ' + ' '.join(json.dumps(p) for p in test_files),
                "argv": [os.path.join(os.sep + "fake", "bin", "node.exe"), "--test", "--test-reporter=tap", *test_files]}
        unit = {"slug": slug, "situation": situation, "class": "frozen_benchmark_delta",
                "marker": marker, "contexts": ["sess-a", "sess-b"], "genuineSupport": 2,
                "entryIds": ["run-aaa", "run-bbb"], "status": "proposed"}
        unit.update(paths)
        proposal = {
            "schema": fa.PROPOSAL_SCHEMA, "skill": skill, "skillDir": os.path.abspath(skill_dir),
            "corpusDir": os.path.abspath(corpus), "createdTs": ts,
            "baseline": {"repoDir": os.path.abspath(repo), "sha": sha, "gate": gate,
                         "gateBefore": {"ok": True, "pass": 1, "fail": 0, "total": 1,
                                        "status": 0, "command": gate["command"]}},
            "eval_gate": gate, "units": [unit], "refused": [],
        }
        Path(pdir, "proposal.json").write_text(json.dumps(proposal, indent=2) + "\n", encoding="utf-8")
        return {"ok": True, "verb": "propose", "outcome": "proposed", "proposalDir": pdir,
                "proposalJsonPath": os.path.join(pdir, "proposal.json"), "unitCount": 1,
                "refusedCount": 0, "proposal": proposal, "exitCode": 0}

    def _apply(self, pdir, opts):
        proposal = json.loads(Path(pdir, "proposal.json").read_text(encoding="utf-8"))
        unit = proposal["units"][0]
        base = {"verb": "apply", "slug": unit["slug"], "class": unit["class"],
                "confirm": opts.get("--confirm"), "baselineSha": proposal["baseline"]["sha"],
                "branch": "sleep/%s-%s-1" % (proposal["skill"], unit["slug"]),
                "workRepo": opts.get("--work-repo")}
        if self.apply_outcome == "applied":
            repo = opts["--work-repo"]
            change = json.loads(Path(unit["changePath"]).read_text(encoding="utf-8"))
            g(repo, "checkout", "-b", base["branch"])
            target = Path(repo, change["file"])
            target.write_text(target.read_text(encoding="utf-8") + change["content"], encoding="utf-8")
            g(repo, "add", "--", change["file"])
            g(repo, "commit", "-qm", "fixture promotion")
            rec = dict(base, ok=True, outcome="applied", promotedCommit=g(repo, "rev-parse", "HEAD").stdout.strip(), exitCode=0)
        elif self.apply_outcome == "blocked":
            rec = dict(base, ok=False, outcome="blocked", exitCode=1,
                       reason="frozen gate regressed (pass 0 / fail 1); rolled back")
        else:
            rec = dict(base, ok=False, outcome="refused", refused=True, exitCode=3,
                       reason="confirm token required (the human is the promotion authority)")
        Path(pdir, "apply-result.json").write_text(json.dumps(rec) + "\n", encoding="utf-8")
        return rec

    def _rollback(self, pdir, opts):
        proposal = json.loads(Path(pdir, "proposal.json").read_text(encoding="utf-8"))
        sha = proposal["baseline"]["sha"]
        ok = self.rollback_outcome == "restored"
        return {"ok": ok, "verb": "rollback", "outcome": self.rollback_outcome, "baselineSha": sha,
                "fromSha": sha, "restoredSha": sha if ok else "0" * 40, "exitCode": 0 if ok else 1,
                "workRepo": opts.get("--work-repo")}


def fake_kernel(monkeypatch, **kw):
    fake = FakeKernel(**kw)
    monkeypatch.setattr(fa, "_run_kernel", fake)
    return fake


def cand_of(payload):
    return Path(payload["anchor"]["candidate"]["dir"])


def _opts(call):
    return dict(zip(call[2::2], call[3::2]))


def _apply(payload, **kw):
    return fa.sleep_apply({"proposalPath": payload["proposalDir"], "confirm": True, **kw})


@pytest.mark.parametrize("verb", ["apply", "rollback"])
def test_clean_later_commit_is_preserved_without_kernel_call(rig, monkeypatch, verb):
    fake = fake_kernel(monkeypatch)
    payload, status = fa.sleep_propose({"skill": "foreman"})
    assert status == 200
    cand = cand_of(payload)
    (cand / "later.txt").write_text("valuable later work\n", encoding="utf-8")
    g(cand, "add", "later.txt")
    g(cand, "commit", "-qm", "later work")
    before, calls = snapshot(cand), len(fake.calls)
    result, status = getattr(fa, "sleep_" + verb)({"proposalPath": payload["proposalDir"], "confirm": True})
    assert status == 409 and "HEAD changed" in result["reason"]
    assert snapshot(cand) == before and len(fake.calls) == calls


def test_same_proposal_operations_are_excluded_while_other_proposal_is_free(rig, monkeypatch):
    fake = fake_kernel(monkeypatch)
    first, status = fa.sleep_propose({"skill": "foreman"})
    assert status == 200
    second, status = fa.sleep_propose({"skill": "foreman"})
    assert status == 200
    body = {"proposalPath": first["proposalDir"], "confirm": True}
    with fa._proposal_operation(body) as held:
        assert held
        count = len(fake.calls)
        for verb in (fa.sleep_apply, fa.sleep_rollback):
            result, status = verb(body)
            assert status == 409 and not result["kernelRan"]
        assert len(fake.calls) == count
        with fa._proposal_operation({"proposalPath": second["proposalDir"]}) as other:
            assert other
    with fa._proposal_operation(body) as held:
        assert held, "OS ownership released without unlinking the lock file"


def _make_link(target, link):
    """A directory junction (Windows; no privilege needed) or a symlink; None
    when the host refuses to create one."""
    try:
        if os.name == "nt":
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
        else:
            os.symlink(str(target), str(link), target_is_directory=True)
        return link
    except (OSError, AttributeError, ImportError):
        return None


def _unlink_link(link):
    """Remove the junction/symlink ITSELF (never its target) so the tmp cleanup
    cannot walk through it."""
    try:
        if os.name == "nt":
            os.rmdir(link)
        else:
            os.unlink(link)
    except OSError:
        pass


def _tmp_is_inside_a_repo(path):
    return g(path, "rev-parse", "--show-toplevel", check=False).returncode == 0


# ── manifest routing ─────────────────────────────────────────────────────────

def test_external_manifest_skill_is_routed_to_its_owning_repo_not_skills_root(rig, monkeypatch):
    fake = fake_kernel(monkeypatch)
    assert not (Path(fa.SKILLS_ROOT) / "foreman").exists(), "the old SKILLS_ROOT/<name> dir does not exist"
    payload, status = fa.sleep_propose({"skill": "foreman"})
    assert status == 200, payload
    anchor = payload["anchor"]
    assert fa._same(anchor["source"]["dir"], rig.trio / "foreman")
    assert fa._same(anchor["source"]["repo"], rig.trio)
    assert anchor["source"]["head"] == rig.head and anchor["source"]["rel"] == "foreman"
    assert anchor["installed"] is False and anchor["applyTarget"] == "candidate-branch"
    assert anchor["source"]["mutated"] is False
    cand = cand_of(payload)
    assert fa._within(cand, rig.candidates) and not fa._within(cand, rig.trio)
    [call] = fake.calls
    assert call[0] == "propose" and fa._same(call[1], cand / "foreman")
    opts = _opts(call)
    assert fa._same(opts["--corpus"], rig.trio / "foreman"), "the canonical journal is the read-only corpus"
    assert fa._same(opts["--repo"], cand), "the frozen-baseline repo handed to the kernel IS the candidate"
    assert fa._same(opts["--runs-dir"], rig.runs)
    assert fa._same(payload["proposal"]["baseline"]["repoDir"], cand)
    assert payload["proposal"]["baseline"]["sha"] == rig.head
    assert payload["proposal"]["units"][0]["diffText"].startswith("--- a/foreman/LESSONS.md")


def test_candidate_is_a_private_frozen_clone_and_the_source_stays_untouched(rig, monkeypatch):
    fake_kernel(monkeypatch)
    payload, status = fa.sleep_propose({"skill": "foreman"})
    assert status == 200, payload
    cand = cand_of(payload)
    assert g(cand, "rev-parse", "HEAD").stdout.strip() == rig.head
    assert (cand / ".git").is_dir(), "its own .git — never a gitfile into the source's metadata"
    assert g(cand, "remote").stdout.strip() == "", "no remote: nothing in the candidate can push back"
    assert g(cand, "status", "--porcelain", "--untracked-files=all").stdout == ""
    assert not (cand / "untracked.txt").exists() and not (cand / "staged.txt").exists()
    assert (cand / "other.txt").read_text(encoding="utf-8") == "unrelated\n", "only COMMITTED state rides along"
    hooks = g(cand, "config", "core.hooksPath").stdout.strip()
    assert hooks and Path(hooks).is_dir() and not os.listdir(hooks), "hooks are pinned to an empty dir"
    assert snapshot(rig.trio) == rig.before, "source HEAD / index / dirty / untracked unchanged"
    assert snapshot(rig.trio)["worktrees"] == [], "no shared worktree metadata was created"
    receipt = json.loads((rig.receipts / (payload["anchor"]["proposalId"] + ".json")).read_text(encoding="utf-8"))
    assert receipt["schema"] == fa.RECEIPT_SCHEMA and receipt["baseline_sha"] == rig.head
    assert set(receipt["artifacts"]) == {"proposal.json",
                                         *("units/run-promote-ready/%s" % n for _k, n in fa._UNIT_FILES)}
    assert fa._same(receipt["candidate"]["dir"], cand) and fa._same(receipt["source"]["repo"], rig.trio)
    assert not (Path(payload["proposalDir"]) / "receipt.json").exists(), "the receipt is not beside the artifact"


def test_relative_manifest_source_resolves_under_the_foundry_root(rig, monkeypatch):
    fake = fake_kernel(monkeypatch)
    payload, status = fa.sleep_propose({"skill": "gandalf"})
    assert status == 200, payload
    cand = cand_of(payload)
    assert fa._same(payload["anchor"]["source"]["repo"], rig.foundry)
    assert payload["anchor"]["source"]["rel"] == "skills/gandalf"
    assert fa._same(fake.calls[0][1], cand / "skills" / "gandalf")
    assert (cand / "skills" / "gandalf" / "LESSONS.md").is_file()


def test_manifest_identity_matches_name_ref_and_tile_posted_basename(rig):
    for key in ("researchPrime", "skill:research-prime", "research-prime", "RESEARCHPRIME"):
        entry, why = fa._manifest_entry_for(key)
        assert entry and entry["ref"] == "skill:research-prime", (key, why)
    assert fa._manifest_entry_for("foreman")[0]["source"].endswith("/foreman")
    assert fa._manifest_entry_for("nonesuch") == (None, "not in the Foundry manifest")


def test_unknown_and_missing_skills_are_honest_errors_without_a_candidate(rig, monkeypatch):
    fake = fake_kernel(monkeypatch)
    payload, status = fa.sleep_propose({"skill": "nonesuch"})
    assert status == 404 and "not in the Foundry manifest" in payload["error"]
    payload, status = fa.sleep_propose({"skill": "researchPrime"})
    assert status == 404 and "not found on disk" in payload["error"] and "researchPrime" in payload["error"]
    payload, status = fa.sleep_propose({"skill": "../foreman"})
    assert status == 400
    assert fake.calls == [] and not rig.candidates.exists()
    assert snapshot(rig.trio) == rig.before


def test_a_source_outside_any_git_repo_is_refused_before_cloning(rig, monkeypatch):
    fake = fake_kernel(monkeypatch)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(rig.tmp))
    loose = rig.tmp / "loose"
    _write_skill(loose, "solo")
    doc = json.loads(Path(fa.MANIFEST_PATH).read_text(encoding="utf-8"))
    doc["skills"].append({"ref": "skill:solo", "name": "solo", "source": (loose / "solo").as_posix(), "edges": []})
    Path(fa.MANIFEST_PATH).write_text(json.dumps(doc), encoding="utf-8")
    payload, status = fa.sleep_propose({"skill": "solo"})
    assert status == 409 and "not inside a git repository" in payload["error"]
    assert fake.calls == [] and not rig.candidates.exists()


def test_a_manifest_source_reached_through_a_junction_binds_to_the_real_repo(rig, monkeypatch):
    fake_kernel(monkeypatch)
    link = _make_link(rig.trio, rig.tmp / "trio-link")
    if link is None:
        pytest.skip("this host cannot create a junction/symlink in the temp dir")
    try:
        doc = json.loads(Path(fa.MANIFEST_PATH).read_text(encoding="utf-8"))
        doc["skills"].append({"ref": "skill:linked", "name": "linked",
                              "source": (link / "foreman").as_posix(), "edges": []})
        Path(fa.MANIFEST_PATH).write_text(json.dumps(doc), encoding="utf-8")
        payload, status = fa.sleep_propose({"skill": "linked"})
        assert status == 200, payload
        assert fa._same(payload["anchor"]["source"]["repo"], rig.trio)
        assert fa._same(payload["anchor"]["source"]["dir"], rig.trio / "foreman")
        assert payload["anchor"]["source"]["rel"] == "foreman"
        assert not fa._within(cand_of(payload), rig.trio)
        assert snapshot(rig.trio) == rig.before
    finally:
        _unlink_link(link)


def test_two_proposals_get_two_independent_candidates_and_receipts(rig, monkeypatch):
    fake_kernel(monkeypatch)
    a, sa = fa.sleep_propose({"skill": "foreman"})
    b, sb = fa.sleep_propose({"skill": "foreman"})
    assert sa == sb == 200
    assert a["proposalDir"] != b["proposalDir"]
    assert not fa._same(cand_of(a), cand_of(b))
    assert len(list(rig.receipts.glob("*.json"))) == 2
    assert snapshot(rig.trio) == rig.before


# ── apply / rollback: confirm, binding, honest outcomes ─────────────────────

def test_apply_requires_an_explicit_confirm_and_never_reaches_the_kernel_without_it(rig, monkeypatch):
    fake = fake_kernel(monkeypatch)
    payload, _ = fa.sleep_propose({"skill": "foreman"})
    for confirm in ({}, {"confirm": False}, {"confirm": "true"}, {"confirm": 1}):
        out, status = fa.sleep_apply({"proposalPath": payload["proposalDir"], **confirm})
        assert status == 409 and out["outcome"] == "refused" and out["kernelRan"] is False, out
    assert [c[0] for c in fake.calls] == ["propose"]


def test_apply_runs_the_kernel_on_the_candidate_only_and_reports_no_install(rig, monkeypatch):
    fake = fake_kernel(monkeypatch)
    payload, _ = fa.sleep_propose({"skill": "foreman"})
    out, status = _apply(payload, unit="run-promote-ready")
    assert status == 200 and out["outcome"] == "applied", out
    call = fake.calls[-1]
    assert call[0] == "apply" and fa._same(call[1], payload["proposalDir"])
    opts = _opts(call)
    assert fa._same(opts["--work-repo"], cand_of(payload)), "the kernel mutates the CANDIDATE only"
    assert opts["--confirm"] == fa.CONFIRM_TOKEN and opts["--unit"] == "run-promote-ready"
    assert out["anchor"]["installed"] is False and out["anchor"]["applyTarget"] == "candidate-branch"
    assert fa._same(out["anchor"]["candidate"]["dir"], cand_of(payload))
    assert out["anchor"]["kernelExit"] == 0
    assert snapshot(rig.trio) == rig.before
    out, status = _apply(payload, unit="nope")  # an unknown unit is refused before the kernel
    assert status == 409 and "HEAD changed" in out["reason"] and len(fake.calls) == 2


def test_rollback_runs_the_kernel_on_the_candidate_only(rig, monkeypatch):
    fake = fake_kernel(monkeypatch)
    payload, _ = fa.sleep_propose({"skill": "foreman"})
    out, status = fa.sleep_rollback({"proposalPath": payload["proposalDir"]})
    assert status == 200 and out["outcome"] == "restored", out
    call = fake.calls[-1]
    assert call[0] == "rollback" and fa._same(_opts(call)["--work-repo"], cand_of(payload))
    assert snapshot(rig.trio) == rig.before


@pytest.mark.parametrize("apply_outcome,status", [("blocked", 422), ("refused", 409)])
def test_a_blocked_or_refused_kernel_apply_is_never_http_200(rig, monkeypatch, apply_outcome, status):
    fake_kernel(monkeypatch, apply_outcome=apply_outcome)
    payload, _ = fa.sleep_propose({"skill": "foreman"})
    out, code = _apply(payload)
    assert code == status and out["outcome"] == apply_outcome and out["ok"] is False and out["reason"]
    assert out["anchor"]["kernelExit"] == out["exitCode"] != 0


def test_a_failed_rollback_a_spawn_error_and_a_timeout_are_500s(rig, monkeypatch):
    fake_kernel(monkeypatch, rollback_outcome="failed")
    payload, _ = fa.sleep_propose({"skill": "foreman"})
    out, code = fa.sleep_rollback({"proposalPath": payload["proposalDir"]})
    assert code == 500 and out["outcome"] == "failed" and out["error"]
    fake_kernel(monkeypatch, spawn_error="node: not found")
    out, code = _apply(payload)
    assert code == 500 and out["error"] == "node: not found" and out["outcome"] == "error"
    fake_kernel(monkeypatch, timed_out=True)
    out, code = fa.sleep_rollback({"proposalPath": payload["proposalDir"]})
    assert code == 500 and out["timedOut"] is True and "timed out" in out["error"]
    assert snapshot(rig.trio) == rig.before


# ── binding: tamper, identity, escapes, candidate state ─────────────────────

def test_tampered_artifacts_are_refused_before_the_kernel_runs(rig, monkeypatch):
    fake = fake_kernel(monkeypatch)
    payload, _ = fa.sleep_propose({"skill": "foreman"})
    pdir = Path(payload["proposalDir"])
    unit = pdir / "units" / "run-promote-ready"
    originals = {p: p.read_bytes() for p in (pdir / "proposal.json", unit / "change.json",
                                              unit / "regression.test.mjs", unit / "provenance.json")}

    def restore():
        for p, b in originals.items():
            p.write_bytes(b)

    change = json.loads(originals[unit / "change.json"])
    change["file"] = "../../outside.md"  # the change target escapes the candidate skill
    (unit / "change.json").write_text(json.dumps(change), encoding="utf-8")
    out, status = _apply(payload)
    assert status == 409 and "change.json" in out["reason"] and out["kernelRan"] is False, out
    restore()
    doc = json.loads(originals[pdir / "proposal.json"])
    doc["eval_gate"]["argv"] = ["cmd.exe", "/c", "echo pwned"]  # the frozen gate swapped for a command
    doc["baseline"]["gate"] = doc["eval_gate"]
    (pdir / "proposal.json").write_text(json.dumps(doc), encoding="utf-8")
    out, status = _apply(payload)
    assert status == 409 and "proposal.json" in out["reason"], out
    restore()
    (unit / "regression.test.mjs").write_text("process.exit(0)\n", encoding="utf-8")  # EXECUTED at apply
    out, status = _apply(payload)
    assert status == 409 and "regression.test.mjs" in out["reason"], out
    restore()
    (unit / "provenance.json").write_text(json.dumps({"class": "human_authored"}), encoding="utf-8")
    out, status = _apply(payload)
    assert status == 409 and "provenance.json" in out["reason"], out
    restore()
    doc = json.loads(originals[pdir / "proposal.json"])
    doc["baseline"]["repoDir"] = str(rig.trio)  # re-pointed at the INSTALLED repository
    (pdir / "proposal.json").write_text(json.dumps(doc), encoding="utf-8")
    out, status = _apply(payload)
    assert status == 409, out
    out, status = fa.sleep_rollback({"proposalPath": str(pdir)})
    assert status == 409, out
    restore()
    assert [c[0] for c in fake.calls] == ["propose"], "no tampered artifact reached the kernel"
    out, status = _apply(payload)
    assert status == 200, "the untouched artifact still applies"
    assert snapshot(rig.trio) == rig.before


def test_structural_validation_refuses_commands_and_paths_the_artifact_names(rig, monkeypatch):
    """Defense in depth beneath the hash check: even a byte-matching artifact must
    name only what the server recomputes itself."""
    fake_kernel(monkeypatch)
    payload, _ = fa.sleep_propose({"skill": "foreman"})
    pdir = payload["proposalDir"]
    receipt = fa._load_receipt(os.path.basename(pdir))
    expect = {"source_dir": receipt["source"]["dir"], "candidate_dir": receipt["candidate"]["dir"],
              "candidate_skill_dir": receipt["candidate"]["skill_dir"],
              "baseline_sha": receipt["baseline_sha"]}
    good = fa._read_json(os.path.join(pdir, "proposal.json"))
    assert fa._validate_artifact(good, pdir, expect) == (True, None)

    def mutated(fn):
        doc = json.loads(json.dumps(good))
        fn(doc)
        return fa._validate_artifact(doc, pdir, expect)

    ok, why = mutated(lambda d: d["eval_gate"]["argv"].__setitem__(0, "powershell.exe"))
    assert not ok and "eval_gate" in why
    ok, why = mutated(lambda d: d["eval_gate"]["argv"].__setitem__(2, str(rig.trio / "foreman" / "test")))
    assert not ok and "eval_gate" in why, "a gate run against the INSTALLED tree"
    ok, why = mutated(lambda d: d["baseline"].__setitem__("repoDir", str(rig.trio)))
    assert not ok and "repoDir" in why
    ok, why = mutated(lambda d: d["baseline"].__setitem__("sha", "0" * 40))
    assert not ok and "sha" in why
    ok, why = mutated(lambda d: d["units"][0].__setitem__("changePath", str(rig.tmp / "elsewhere" / "change.json")))
    assert not ok and "changePath" in why
    ok, why = mutated(lambda d: d["units"][0].__setitem__("slug", "../escape"))
    assert not ok and "slug" in why
    ok, why = mutated(lambda d: d.__setitem__("skillDir", str(rig.trio / "foreman")))
    assert not ok and "skillDir" in why
    ok, why = mutated(lambda d: d.__setitem__("schema", "foundry.sleep_session/proposal@2"))
    assert not ok and "schema" in why


def test_unreceipted_copied_or_escaping_proposals_are_refused(rig, monkeypatch):
    fake = fake_kernel(monkeypatch)
    payload, _ = fa.sleep_propose({"skill": "foreman"})
    pdir = Path(payload["proposalDir"])
    copy = rig.runs / "foreman-copy"  # a byte-identical COPY under another name has no receipt
    shutil.copytree(pdir, copy)
    out, status = fa.sleep_apply({"proposalPath": str(copy), "confirm": True})
    assert status == 409 and "receipt" in out["reason"]
    elsewhere = rig.tmp / "elsewhere"
    shutil.copytree(pdir, elsewhere)
    for body in ({"proposalPath": str(elsewhere)}, {"proposalPath": str(pdir / "units")},
                 {"proposalId": "../" + pdir.name}, {"proposalId": pdir.name + "/../" + pdir.name},
                 {"proposalId": ".hidden"}, {"proposalId": ""}, {}):
        out, status = fa.sleep_apply(dict(body, confirm=True))
        assert status == 400, (body, out)
        out, status = fa.sleep_rollback(body)
        assert status == 400, (body, out)
    out, status = fa.sleep_rollback({"baselineSha": rig.head})
    assert status == 400 and "baselineSha" in out["error"]
    (rig.receipts / (pdir.name + ".json")).unlink()  # the receipt gone → refused, not trusted
    out, status = fa.sleep_apply({"proposalPath": str(pdir), "confirm": True})
    assert status == 409 and "receipt" in out["reason"]
    assert [c[0] for c in fake.calls] == ["propose"]


def test_a_junction_or_symlink_in_the_runs_dir_is_never_traversed(rig, monkeypatch):
    fake = fake_kernel(monkeypatch)
    payload, _ = fa.sleep_propose({"skill": "foreman"})
    pdir = Path(payload["proposalDir"])
    link = _make_link(pdir, rig.runs / "foreman-link")
    if link is None:
        pytest.skip("this host cannot create a junction/symlink in the temp dir")
    try:
        assert fa._is_reparse_point(link)
        assert fa._resolve_proposal_dir({"proposalPath": str(link)}) is None
        assert fa._resolve_proposal_dir({"proposalId": link.name}) is None
        out, status = fa.sleep_apply({"proposalPath": str(link), "confirm": True})
        assert status == 400
        out, status = fa.sleep_rollback({"proposalId": link.name})
        assert status == 400
        assert fa._same(fa._resolve_proposal_dir({"proposalPath": str(pdir)}), pdir)
        assert fa._same(fa._resolve_proposal_dir({"proposalId": pdir.name}), pdir)
        assert [c[0] for c in fake.calls] == ["propose"]
    finally:
        _unlink_link(link)


def test_a_dirty_or_stale_candidate_is_refused_rather_than_reset(rig, monkeypatch):
    fake = fake_kernel(monkeypatch)
    payload, _ = fa.sleep_propose({"skill": "foreman"})
    cand = cand_of(payload)
    stray = cand / "someones-work.txt"
    stray.write_text("do not reset me\n", encoding="utf-8")
    for fn, body in ((fa.sleep_apply, {"confirm": True}), (fa.sleep_rollback, {})):
        out, status = fn({"proposalPath": payload["proposalDir"], **body})
        assert status == 409 and "uncommitted" in out["reason"] and "someones-work.txt" in out["reason"], out
        assert out["candidateState"]["dirty"] == ["someones-work.txt"]
        assert stray.read_text(encoding="utf-8") == "do not reset me\n", "nothing was reset"
    stray.unlink()
    g(cand, "checkout", "-q", "--orphan", "foreign")  # a history NOT descending from the frozen baseline
    g(cand, "commit", "-qm", "foreign history")
    out, status = _apply(payload)
    assert status == 409 and "HEAD changed" in out["reason"]
    out, status = fa.sleep_rollback({"proposalPath": payload["proposalDir"]})
    assert status == 409 and "HEAD changed" in out["reason"]
    fa._rmtree_force(cand)  # the candidate removed altogether
    out, status = _apply(payload)
    assert status == 409 and ("candidates root" in out["reason"] or "frozen benchmark" in out["reason"])
    assert [c[0] for c in fake.calls] == ["propose"], "no stale/dirty candidate reached the kernel"
    assert snapshot(rig.trio) == rig.before


# ── containment of the kernel launcher ───────────────────────────────────────

def _alive(pid):
    if os.name == "nt":
        import proc_probe
        return proc_probe.is_alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def test_the_kernel_launcher_is_contained_and_leaves_no_orphan_on_timeout(tmp_path):
    res = fa._run_contained([sys.executable, "-c",
                             "import sys; print('hi'); sys.stderr.write('err'); sys.exit(3)"],
                            str(tmp_path), 60)
    assert res["status"] == 3 and res["stdout"].strip() == "hi" and res["stderr"].strip() == "err"
    assert res["timedOut"] is False and res["spawnError"] is None and res["contained"] is True
    child = ("import subprocess, sys, time\n"
             "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
             "print(p.pid, flush=True)\n"
             "time.sleep(60)\n")
    started = time.monotonic()
    res = fa._run_contained([sys.executable, "-c", child], str(tmp_path), 1.5)
    assert res["timedOut"] is True and res["status"] is None
    assert time.monotonic() - started < 40
    gpid = int(res["stdout"].strip().splitlines()[0])
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and _alive(gpid):
        time.sleep(0.1)
    assert not _alive(gpid), "the grandchild outlived the launcher — an orphan subtree"
    res = fa._run_contained([str(tmp_path / "no-such-binary"), "x"], str(tmp_path), 5)
    assert res["spawnError"] and res["status"] is None and res["contained"] is False


# ── the REAL kernel (node + the kernel checkout required) ───────────────────

def _kernel_available():
    return bool(shutil.which(fa._node_cmd())) and Path(fa.KERNEL_CLI).is_file()


live_kernel = pytest.mark.skipif(
    not _kernel_available(),
    reason="node + the foundry-v2 kernel checkout (FOUNDRY_KERNEL_DIR) are needed for the live-kernel boundary tests")


@live_kernel
def test_live_kernel_propose_apply_rollback_touch_only_the_candidate(rig):
    payload, status = fa.sleep_propose({"skill": "foreman"})
    assert status == 200, payload
    cand = cand_of(payload)
    proposal = payload["proposal"]
    assert fa._same(proposal["baseline"]["repoDir"], cand) and proposal["baseline"]["sha"] == rig.head
    assert fa._same(proposal["skillDir"], cand / "foreman")
    assert fa._same(proposal["corpusDir"], rig.trio / "foreman")
    assert payload["unitCount"] >= 1, payload
    if os.name == "nt":
        assert payload["anchor"]["kernelContained"] is True
    assert proposal["baseline"]["gateBefore"]["ok"] is True, proposal["baseline"]["gateBefore"]
    unit = proposal["units"][0]
    out, status = _apply(payload, unit=unit["slug"])
    assert status == 200 and out["outcome"] == "applied", out
    promoted = out["promotedCommit"]
    assert g(cand, "cat-file", "-e", promoted + "^{commit}", check=False).returncode == 0
    assert g(rig.trio, "cat-file", "-e", promoted + "^{commit}", check=False).returncode != 0, \
        "the promotion commit exists ONLY in the candidate"
    assert out["branch"].startswith("sleep/") and out["branch"] in g(cand, "branch", "--list", "sleep/*").stdout
    assert unit["marker"] in (cand / "foreman" / "LESSONS.md").read_text(encoding="utf-8")
    assert unit["marker"] not in (rig.trio / "foreman" / "LESSONS.md").read_text(encoding="utf-8")
    assert out["anchor"]["installed"] is False and fa._same(out["anchor"]["candidate"]["dir"], cand)
    assert snapshot(rig.trio) == rig.before, "the installed checkout is untouched by apply"
    out, status = fa.sleep_rollback({"proposalPath": payload["proposalDir"]})
    assert status == 200 and out["outcome"] == "restored" and out["restoredSha"] == rig.head, out
    assert g(cand, "rev-parse", "HEAD").stdout.strip() == rig.head
    assert unit["marker"] not in (cand / "foreman" / "LESSONS.md").read_text(encoding="utf-8")
    assert snapshot(rig.trio) == rig.before


@live_kernel
def test_live_kernel_blocked_apply_is_a_failure_status_and_rolls_the_candidate_back(rig):
    payload, status = fa.sleep_propose({"skill": "crucible"})
    assert status == 200 and payload["unitCount"] >= 1, payload
    gate_before = payload["proposal"]["baseline"]["gateBefore"]
    assert gate_before.get("ok") is True, gate_before
    cand = cand_of(payload)
    original_lesson = (cand / "crucible" / "LESSONS.md").read_bytes()
    out, status = _apply(payload)
    assert status == 422 and out["outcome"] == "blocked" and out["ok"] is False, out
    assert "regress" in out["reason"] or "rolled back" in out["reason"]
    assert g(cand, "rev-parse", "HEAD").stdout.strip() == rig.head, "the kernel auto-rolled the CANDIDATE back"
    assert (cand / "crucible" / "LESSONS.md").read_bytes() == original_lesson
    assert snapshot(rig.trio) == rig.before, "the installed checkout is untouched by a blocked apply"


@live_kernel
def test_rollback_retry_recovers_after_post_kernel_receipt_failure(rig, monkeypatch):
    payload, status = fa.sleep_propose({"skill": "foreman"})
    assert status == 200, payload
    promoted, status = _apply(payload)
    assert status == 200, promoted
    cand = cand_of(payload)
    original_write = fa._paths.atomic_write_text
    failures = []
    def fail_restored_receipt_once(target, text):
        if str(target).endswith(".operation.json") and '"restored"' in text and not failures:
            failures.append(True)
            raise OSError("simulated receipt write failure after kernel checkout")
        return original_write(target, text)
    monkeypatch.setattr(fa._paths, "atomic_write_text", fail_restored_receipt_once)
    body = {"proposalPath": payload["proposalDir"]}
    result, status = fa.sleep_rollback(body)
    assert status == 500 and result["kernelRan"] is None
    assert g(cand, "rev-parse", "HEAD").stdout.strip() == rig.head
    receipt_path = fa._operation_receipt_path(Path(payload["proposalDir"]).name)
    assert json.loads(receipt_path.read_text())["outcome"] == "applied"
    result, status = fa.sleep_rollback(body)
    assert status == 200 and result["outcome"] == "restored", result
    assert json.loads(receipt_path.read_text())["outcome"] == "restored"
    assert g(cand, "rev-parse", promoted["branch"]).stdout.strip() == promoted["promotedCommit"]
    assert snapshot(rig.trio) == rig.before
