"""Skill Foundry v2 — Waves 7+8: the Phase-6 control-plane ops.

DR-01's contract is "mutations are runs, not endpoints": Anchor's execution
API stays read/execute, and every mutation the Foundry needs ships as a
manifest-registered ``mutate`` op on the Wave-3 generic runner, dispatched
through ``job_runner`` — therefore confirm-token-gated, write-scoped, and
auto-journaled, with NO new server, DB, or store. This module delivers the
Phase-6 ops of that inventory (the keys come FROM
``foundry_decisions.MUTATIVE_VERBS`` — the DR-01 decision stays on the
consumption path):

* **``foundry.scaffold_skill``** — create a new skill on disk from a template
  (SKILL.md · runner manifest · journal dir · per-skill North-Star stub · a
  minimal runnable host), register it in map.json v2 (and regenerate the
  Wave-5 lockfile so the Wave-6 drift gates stay green), and commit the
  scaffold on a dedicated git branch (DR-02: mutations apply on a branch,
  never straight to main). Idempotent: a re-run for an existing skill REFUSES
  to overwrite — it never clobbers, never half-writes.
* **``foundry.gen_manifest``** — derive (or update) a skill's runner manifest,
  validated against the Wave-3 schema (``skill_runner.validate_manifest``)
  BEFORE anything is written; an invalid result refuses without touching disk.
* **``foundry.edit_north_star``** (Wave 8) — the ONLY sanctioned per-skill
  North-Star mutation path: proposal-diff → explicit human confirm token →
  apply as a branch commit with the prior version retained. The core (and
  the out-of-band drift gates) lives in ``foundry_north_star``; this module
  is the confirm-gated dispatch surface.
* **``foundry.register_autoload``** (Wave 8) — regenerate Anchor's CLICKABLE
  skill set from map.json v2 alone (``foundry_autoload``): a skill added to
  the map appears, a skill dropped disappears — never hand-wired.

The Wave-7 registry builders (``control_plane_manifests`` /
``build_control_dispatch``) stay frozen to their original pair; the Wave-8
ops are ADDITIVE via ``full_control_plane_manifests`` /
``build_full_control_dispatch``.

Execution shape — both directions of the same manifest:

* The op manifests declare ``op_kind: mutate`` with an explicit
  ``write_scope``; the runner's gates (single-use confirm token, in-scope
  write targets, pre-flight probe) and its Wave-2 auto-journal seam apply
  UNCHANGED via ``skill_runner.run_op``.
* The op HOST is this module itself run headlessly
  (``python foundry_ops.py <op> [--payload <file>]`` — payload JSON on stdin
  on the runner's default host path, or as a payload file when dispatched
  through ``job_runner``), printing ONE JSON result object.
* :func:`run_control_op` is the DR-01 dispatch path: the op subprocess is
  launched through ``job_runner`` (a server-owned job with a durable log,
  reconciliation, and cancel tree-kill) via the Wave-7 ``command=`` seam —
  headless, no GUI anywhere in the loop.

Journal discipline: this module NEVER writes a journal entry itself — the
runner journals every dispatched op (done, failed, refused) through
``foundry_journal``, and the op journals land under the control-plane home
(:func:`ops_home`). The scaffold only creates a new skill's EMPTY journal
structure; entry writing stays exclusively in the Wave-2 seam.

Stdlib only (Anchor's no-dep rule) + the product seams ``paths`` /
``foundry_decisions`` / ``foundry_journal`` / ``foundry_map`` /
``skill_runner`` (and, lazily, ``job_runner`` / ``worktrees`` /
``foundry_skills``).
"""

import inspect
import json
import os
import re
import shutil
import sys
import uuid
from pathlib import Path

import paths as _paths
import foundry_autoload as _fa
import foundry_decisions as _fd
import foundry_journal as _fj
import foundry_map as _fm
import foundry_north_star as _fns
import skill_runner as _sr


# ── Constants / seams ────────────────────────────────────────────────────────

_THIS_FILE = Path(__file__).resolve()

#: The DR-01 op names (the registry keys). They MUST exist in
#: ``foundry_decisions.MUTATIVE_VERBS`` — the manifest builders read the
#: decision record, so a renamed/dropped verb breaks loudly here.
OP_SCAFFOLD = "foundry.scaffold_skill"
OP_GEN_MANIFEST = "foundry.gen_manifest"
OP_EDIT_NORTH_STAR = "foundry.edit_north_star"
OP_REGISTER_AUTOLOAD = "foundry.register_autoload"

#: op registry key → the CLI subcommand its host_cmd runs.
OP_CLI_NAMES = {OP_SCAFFOLD: "scaffold_skill",
                OP_GEN_MANIFEST: "gen_manifest",
                OP_EDIT_NORTH_STAR: "edit_north_star",
                OP_REGISTER_AUTOLOAD: "register_autoload"}

#: The job_runner lane control-plane op jobs run under (free-form label — the
#: ops go through the plain ``launch`` path; the Wave-11 concurrency budget
#: lands in the generic runner, not here).
OPS_LANE = "foundry-op"

#: Skill-name discipline for scaffolded skills (a slug that survives refs,
#: dir names, and branch names unchanged).
_SLUG_RE = re.compile(r"^[a-z][a-z0-9-]{0,63}$")

#: The dedicated branch a scaffold commits on (DR-02 compensating control:
#: mutations apply on a branch, never straight to main).
SCAFFOLD_BRANCH_PREFIX = "foundry/scaffold-"

#: The dedicated branch a North-Star apply commits on (same DR-02 control;
#: repeat edits of one skill stack commits on the same branch).
NORTH_STAR_BRANCH_PREFIX = "foundry/north-star-"

#: New scaffolds enter the map at the bottom of the PyPI status ladder.
DEFAULT_SCAFFOLD_STATUS = "1 - Planning"
DEFAULT_SCAFFOLD_VERSION = "0.1.0"

#: Per-op host timeout (deterministic local work — generous, never a model).
OP_TIMEOUT_S = 180.0

#: The empty journal structure scaffolded into a new skill. The NAME comes
#: from the Wave-2 seam so the two can never drift; creating the empty dir is
#: scaffold structure — entry WRITING stays exclusively in foundry_journal.
_SKILL_JOURNAL_SUBDIR = _fj.JOURNAL_DIRNAME

#: Wave-1 anti-drift convention: the control plane traces to the North Star.
TRACES_TO_NORTH_STAR = (_fd.NS_GUI_DRIVES_REAL_MACHINERY,
                        _fd.NS_MANIFEST_RUNNER)


def _default_skills_root() -> Path:
    """The canonical skills root (single source: the Wave-4 registry seam)."""
    import foundry_skills as _fs
    return _fs._skills_root()


def ops_home() -> Path:
    """The control-plane home dir (under the data dir, never the repo).

    This is the op manifests' ``skill_dir``: the runner's pre-flight probes
    it and the Wave-2 seam journals every dispatched op into
    ``<ops_home>/journal/``.
    """
    home = _paths.data_dir() / "foundry_ops"
    home.mkdir(parents=True, exist_ok=True)
    return home


def _ns_proposals_home() -> Path:
    """Where ``foundry.edit_north_star`` parks its proposals (under the
    control-plane home — the propose leg's declared write target)."""
    home = ops_home() / _fns.PROPOSALS_DIRNAME
    home.mkdir(parents=True, exist_ok=True)
    return home


def _refusal(op, reason) -> dict:
    """An op-level refusal — a VALID result (the host exits 0), never a crash;
    the runner journals it and the caller reads the honest reason."""
    return {"ok": False, "op": str(op), "refused": True,
            "reason": str(reason), "verdict": "refused:" + str(reason)[:120]}


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(str(tmp), str(path))


# ── Manifest derivation (shared by both ops) ─────────────────────────────────

def _guess_host_cmd(skill_dir: Path, python_exe: str):
    """Derive a host command from what the skill dir actually contains.

    ``{skill_dir}`` placeholders resolve at dispatch time (the Wave-3
    contract), so a derived manifest survives a dir move. ``None`` when no
    known entrypoint exists — the caller must supply ``host_cmd`` explicitly.
    """
    if (skill_dir / "host.py").is_file():
        return [python_exe, "{skill_dir}/host.py"]
    if (skill_dir / "index.js").is_file():
        return ["node", "{skill_dir}/index.js"]
    if (skill_dir / "agent_interface.py").is_file():
        return [python_exe, "{skill_dir}/agent_interface.py"]
    return None


def _derive_manifest_data(name, skill_dir: Path, *, host_cmd=None,
                          tier="standard", python_exe=None,
                          output_contract=None) -> dict:
    """The derived (default) Wave-3 manifest for one skill dir — pure data."""
    py = str(python_exe or sys.executable)
    cmd = host_cmd or _guess_host_cmd(skill_dir, py)
    caps = []
    if isinstance(cmd, str):
        parts = _sr._split_cmd(cmd)
    else:
        parts = [str(a) for a in (cmd or ())]
    if parts:
        caps.append("exec:" + parts[0])
    if (skill_dir / "SKILL.md").is_file():
        caps.append("read:SKILL.md")
    return {
        "skill": str(name),
        "skill_dir": str(skill_dir),
        "op_kind": "run",
        "host_cmd": cmd,
        "output_contract": dict(output_contract or {"format": "json"}),
        "panel": {"title": str(name).replace("-", " ").title()},
        "journal": {"enabled": True},
        "tier": tier,
        "capabilities": caps,
        "activation": {"trigger": "first_run"},
    }


def _write_manifest(skill_dir: Path, manifest: dict) -> Path:
    target = skill_dir / _sr.MANIFEST_FILENAME
    manifest_text = json.dumps(manifest, indent=2, ensure_ascii=False) + "\n"
    _atomic_write(target, manifest_text)
    try:
        import foundry_integrity
        foundry_integrity.update_manifest_entry(skill_dir.name, _sr.MANIFEST_FILENAME, manifest_text)
    except Exception as e:
        import logging
        logging.getLogger("foundry_ops").warning("failed to update integrity manifest entry: %s", e)
    return target


# ── The scaffold template ────────────────────────────────────────────────────

_SKILL_MD_TEMPLATE = """\
# {title}

{description}

## Protocol

1. Read the payload (one JSON object on stdin).
2. Do the work this skill declares.
3. Print ONE JSON object: {{"schema": "{name}/v1", "verdict": "..."}}.

> Scaffolded by `foundry.scaffold_skill`. Journaling is HOST-ENFORCED by the
> generic runner — capture is a by-product of every run, never author action.
"""

_NORTH_STAR_TEMPLATE = """\
# North Star — {name}

> STUB — scaffolded by `foundry.scaffold_skill`. Refine it via
> `foundry.edit_north_star`, the ONLY sanctioned mutation path for this file
> (out-of-band edits are caught by the drift gate).

- What must this skill make TRUE for its user? (fill in 3-5 locked clauses)
- What does DONE look like on genuine data, not a demo?
"""

_HOST_TEMPLATE = """\
\"\"\"{name} — scaffolded host (replace with the real skill host).

Reads one JSON payload on stdin, answers with ONE JSON object on stdout —
exactly the output contract the scaffolded manifest declares.
\"\"\"
import json
import sys

raw = sys.stdin.read()
payload = json.loads(raw) if raw.strip() else None
print(json.dumps({{
    "schema": "{name}/v1",
    "skill": "{name}",
    "verdict": "scaffold-template-ok",
    "echo": payload,
}}, ensure_ascii=False))
"""


# ── Git (best-effort, honestly reported — never a silent skip) ───────────────

_GIT_IDENT = ("-c", "user.name=Anchor Foundry",
              "-c", "user.email=foundry@example.com")


def _git_commit_on_branch(skills_root: Path, paths_to_add, *, branch,
                          message) -> dict:
    """Commit ``paths_to_add`` on a dedicated branch → an honest report dict.

    ``{"committed": bool, "branch": str|None, "reason": str|None}``. Only
    paths inside the enclosing repo are staged (the map may live in a
    different tree); no repo at all degrades honestly — the files stand, the
    result says why nothing was committed. Uses the ONE sanctioned git seam
    (``worktrees._git`` — git as an external CLI, never a dep). An already-
    existing branch is switched to, not a failure — repeat mutations of the
    same subject stack commits on the same branch.

    SAFETY: git's toplevel discovery walks UP arbitrarily far, so a stray
    ancestor ``.git`` (a temp dir, a home dir) could hijack the commit — and
    the branch switch — into a repo that is not the foundry at all. The
    discovered toplevel is therefore accepted ONLY when it is the skills
    root itself or its immediate parent (the ``<foundry>/skills`` layout);
    anything farther refuses BEFORE any branch is touched.
    """
    import worktrees as _wt
    ok, _rc, out, err = _wt._git(skills_root, ["rev-parse", "--show-toplevel"])
    if not ok:
        return {"committed": False, "branch": None,
                "reason": "not-a-git-repo:" + (err or "").strip()[:160]}
    top = Path(out.strip())
    root_resolved = Path(skills_root).resolve()
    top_norm = os.path.normcase(str(top.resolve()))
    if top_norm not in (os.path.normcase(str(root_resolved)),
                        os.path.normcase(str(root_resolved.parent))):
        return {"committed": False, "branch": None,
                "reason": "repo-not-foundry-rooted:" + top.as_posix()}
    branch = str(branch)
    ok, _rc, _out, err = _wt._git(top, ["checkout", "-b", branch])
    if not ok:
        ok, _rc, _out, err2 = _wt._git(top, ["checkout", branch])
        if not ok:
            return {"committed": False, "branch": branch,
                    "reason": "branch-failed:"
                    + (err or err2 or "").strip()[:160]}
    inside = []
    for p in paths_to_add:
        try:
            resolved = os.path.normcase(str(Path(p).resolve()))
        except OSError:
            continue
        if resolved == top_norm or resolved.startswith(
                top_norm.rstrip("\\/") + os.sep):
            inside.append(str(p))
    if not inside:
        return {"committed": False, "branch": branch,
                "reason": "nothing-inside-repo"}
    ok, _rc, _out, err = _wt._git(top, ["add", "--"] + inside)
    if not ok:
        return {"committed": False, "branch": branch,
                "reason": "add-failed:" + (err or "").strip()[:160]}
    ok, _rc, _out, err = _wt._git(
        top, list(_GIT_IDENT) + ["commit", "-m", str(message)])
    if not ok:
        return {"committed": False, "branch": branch,
                "reason": "commit-failed:" + (err or "").strip()[:160]}
    return {"committed": True, "branch": branch, "reason": None}


def _git_commit_scaffold(skills_root: Path, paths_to_add, name) -> dict:
    """The Wave-7 scaffold commit (branch + message preserved verbatim)."""
    return _git_commit_on_branch(
        skills_root, paths_to_add,
        branch=SCAFFOLD_BRANCH_PREFIX + str(name),
        message="foundry.scaffold_skill: %s (template + manifest + map v2)"
        % name)


# ── Op 1: foundry.scaffold_skill ─────────────────────────────────────────────

def scaffold_skill(name, *, skills_root=None, map_path=None, lock_path=None,
                   title=None, description=None, tier="standard",
                   status=DEFAULT_SCAFFOLD_STATUS,
                   version=DEFAULT_SCAFFOLD_VERSION, host_cmd=None,
                   python_exe=None, git=True) -> dict:
    """Create a new skill on disk from the template + register it in map v2.

    The op body (runs headlessly under the runner/job_runner dispatch; also
    callable directly). Order of operations keeps every failure clean:
    validate first (name, collision, manifest, map), write the skill dir,
    then the map + lockfile (rolled back together on failure), then the
    best-effort branch commit. A skill that already exists — on disk OR in
    the map — is REFUSED, never overwritten.
    """
    op = "scaffold_skill"
    name = str(name or "")
    if not _SLUG_RE.match(name):
        return _refusal(op, "invalid-skill-name:%r" % name)
    root = Path(skills_root) if skills_root else _default_skills_root()
    mp = Path(map_path) if map_path else _fm.MAP_FILE
    lp = Path(lock_path) if lock_path else _fm.LOCK_FILE
    skill_dir = root / name
    if skill_dir.exists():
        return _refusal(op, "refuses-to-overwrite:%s" % skill_dir.as_posix())
    try:
        prev_map_text = mp.read_text(encoding="utf-8")
        doc = json.loads(prev_map_text)
    except (OSError, ValueError) as exc:
        return _refusal(op, "map-unreadable:%s" % exc)
    ref = "skill:" + name
    skills = doc.get("skills") if isinstance(doc, dict) else None
    if not isinstance(skills, list):
        return _refusal(op, "map-malformed:skills-missing")
    for entry in skills:
        if isinstance(entry, dict) and (entry.get("ref") == ref
                                        or entry.get("name") == name):
            return _refusal(op, "already-registered:%s" % ref)

    # Build + validate the manifest BEFORE anything touches disk.
    py = str(python_exe or sys.executable)
    manifest = _derive_manifest_data(
        name, skill_dir,
        host_cmd=host_cmd or [py, "{skill_dir}/host.py"],
        tier=tier, python_exe=py,
        output_contract={"format": "json",
                         "required_keys": ["schema", "verdict"]})
    # The template guarantees SKILL.md; declare the read capability up front.
    if "read:SKILL.md" not in manifest["capabilities"]:
        manifest["capabilities"].append("read:SKILL.md")
    problems = _sr.validate_manifest(manifest)
    if problems:
        return _refusal(op, "manifest-invalid:" + "; ".join(problems))

    # Validate the WOULD-BE map before creating anything (no partial state).
    new_doc = dict(doc)
    new_doc["skills"] = sorted(
        skills + [{"ref": ref, "name": name, "source": skill_dir.as_posix(),
                   "status": status, "tier": tier, "version": version,
                   "edges": [],
                   "note": "scaffolded by foundry.scaffold_skill"}],
        key=lambda s: str(s.get("ref") or ""))
    map_problems = _fm.validate_map(new_doc)
    if map_problems:
        return _refusal(op, "map-would-be-invalid:" + "; ".join(map_problems))

    # Write the skill dir from the template.
    created = []
    try:
        skill_dir.mkdir(parents=True)
        display = title or name.replace("-", " ").title()
        blurb = description or ("Scaffolded skill — fill in what %s makes "
                                "true for its user." % name)
        _atomic_write(skill_dir / "SKILL.md", _SKILL_MD_TEMPLATE.format(
            title=display, description=blurb, name=name))
        created.append("SKILL.md")
        _atomic_write(skill_dir / "NORTH-STAR.md",
                      _NORTH_STAR_TEMPLATE.format(name=name))
        created.append("NORTH-STAR.md")
        # Seed the Wave-8 hash ledger: the North Star is drift-tracked from
        # birth, so the ONLY way it changes cleanly is foundry.edit_north_star.
        _fns.record_version(skill_dir, action=_fns.ACTION_SCAFFOLD)
        created.append(_fns.HISTORY_DIRNAME + "/" + _fns.LEDGER_FILENAME)
        _atomic_write(skill_dir / "host.py", _HOST_TEMPLATE.format(name=name))
        created.append("host.py")
        _write_manifest(skill_dir, manifest)
        created.append(_sr.MANIFEST_FILENAME)
        jdir = skill_dir / _SKILL_JOURNAL_SUBDIR
        jdir.mkdir(parents=True, exist_ok=True)
        (jdir / ".gitkeep").write_text("", encoding="utf-8")
        created.append(_SKILL_JOURNAL_SUBDIR + "/.gitkeep")
        
        # Wave 10: register the new skill in the integrity manifest
        try:
            import foundry_integrity
            foundry_integrity.register_skill(name)
        except Exception as e:
            pass
    except OSError as exc:
        shutil.rmtree(skill_dir, ignore_errors=True)
        return _refusal(op, "scaffold-io-failed:%s" % exc)

    # Register in the map + regenerate the lockfile (rolled back as a pair).
    try:
        _atomic_write(mp, json.dumps(new_doc, indent=2,
                                     ensure_ascii=False) + "\n")
        _fm.write_lockfile(new_doc, path=lp)
    except (OSError, ValueError) as exc:
        try:
            _atomic_write(mp, prev_map_text)
        except OSError:
            pass
        shutil.rmtree(skill_dir, ignore_errors=True)
        return _refusal(op, "map-register-failed:%s" % exc)

    git_report = {"committed": False, "branch": None, "reason": "git-disabled"}
    if git:
        git_report = _git_commit_scaffold(root, [skill_dir, mp, lp], name)

    return {
        "ok": True,
        "op": op,
        "skill": name,
        "ref": ref,
        "skill_dir": skill_dir.as_posix(),
        "created": created,
        "map_registered": True,
        "lock_regenerated": True,
        "git": git_report,
        "verdict": "scaffolded:%s" % name,
    }


# ── Op 2: foundry.gen_manifest ───────────────────────────────────────────────

def gen_manifest(skill, *, skills_root=None, host_cmd=None, python_exe=None,
                 updates=None) -> dict:
    """Derive or update a skill's runner manifest — validated before write.

    Merge order (weakest first): derived defaults from the dir's real
    contents → the existing on-disk manifest (an author's manifest is
    preserved, never blown away) → the caller's explicit ``updates``. The
    result must pass ``skill_runner.validate_manifest`` or the op refuses
    WITHOUT writing — a broken manifest never lands on disk.
    """
    op = "gen_manifest"
    skill = str(skill or "")
    root = Path(skills_root) if skills_root else _default_skills_root()
    skill_dir = root / skill
    if not skill or not skill_dir.is_dir():
        return _refusal(op, "unknown-skill:%s" % (skill or "?"))

    existed = (skill_dir / _sr.MANIFEST_FILENAME).is_file()
    existing = None
    if existed:
        try:
            existing = _sr.load_skill_manifest(skill_dir)
        except ValueError:
            existing = None  # broken manifest → honest fresh derivation

    manifest = _derive_manifest_data(
        skill, skill_dir,
        host_cmd=host_cmd or (existing or {}).get("host_cmd"),
        tier=(existing or {}).get("tier") or "standard",
        python_exe=python_exe)
    if existing:
        manifest.update(existing)
    manifest["skill"] = skill
    manifest["skill_dir"] = str(skill_dir)  # always re-pointed at the real dir
    if host_cmd:
        manifest["host_cmd"] = host_cmd
    if updates:
        if not isinstance(updates, dict):
            return _refusal(op, "updates-not-an-object")
        manifest.update(updates)
    if not manifest.get("host_cmd"):
        return _refusal(op, "host-cmd-underivable:%s" % skill)

    problems = _sr.validate_manifest(manifest)
    if problems:
        return _refusal(op, "manifest-invalid:" + "; ".join(problems))

    try:
        target = _write_manifest(skill_dir, manifest)
    except OSError as exc:
        return _refusal(op, "manifest-write-failed:%s" % exc)

    return {
        "ok": True,
        "op": op,
        "skill": skill,
        "updated": existed,
        "manifest_path": target.as_posix(),
        "manifest": manifest,
        "verdict": ("updated:%s" if existed else "derived:%s") % skill,
    }


# ── Op 3: foundry.edit_north_star (Wave 8) ───────────────────────────────────

def edit_north_star(skill, *, skills_root=None, mode="propose", new_text=None,
                    proposal_id=None, git=True) -> dict:
    """The ONLY sanctioned per-skill North-Star mutation path.

    Two legs of one round-trip (both dispatched as the same confirm-gated
    ``mutate`` op; the core lives in ``foundry_north_star``):

    * ``mode="propose"`` — compute the unified diff of the current
      ``NORTH-STAR.md`` against ``new_text`` and PARK it as a proposal;
      nothing on the skill is written. The human reads the returned diff.
    * ``mode="apply"`` — apply a parked ``proposal_id``: refused when the
      file changed since the proposal (a stale approval is no approval);
      the prior version is RETAINED in ``north-star-history/`` + the hash
      ledger, and the change is committed on a dedicated git branch
      (``foundry/north-star-<skill>`` — DR-02: mutations on a branch).
    """
    op = "edit_north_star"
    skill = str(skill or "")
    if not _SLUG_RE.match(skill):
        return _refusal(op, "invalid-skill-name:%r" % skill)
    root = Path(skills_root) if skills_root else _default_skills_root()
    skill_dir = root / skill
    if not skill_dir.is_dir():
        return _refusal(op, "unknown-skill:%s" % skill)
    mode = str(mode or "propose")

    if mode == "propose":
        if not (isinstance(new_text, str) and new_text.strip()):
            return _refusal(op, "new-text-missing")
        res = _fns.propose_edit(skill, skill_dir, new_text,
                                proposals_home=_ns_proposals_home())
        if not res.get("ok"):
            return _refusal(op, res.get("reason"))
        return {
            "ok": True,
            "op": op,
            "mode": "propose",
            "skill": skill,
            "applied": False,
            "proposal_id": res["proposal_id"],
            "diff": res["diff"],
            "base_sha256": res["base_sha256"],
            "verdict": "north-star-proposed:%s" % skill,
        }

    if mode == "apply":
        proposal = _fns.load_proposal(proposal_id,
                                      proposals_home=_ns_proposals_home())
        if proposal is None:
            return _refusal(op, "unknown-proposal:%s" % (proposal_id or "?"))
        if proposal.get("skill") != skill:
            return _refusal(op, "proposal-skill-mismatch:%s"
                            % proposal.get("skill"))
        res = _fns.apply_edit(skill_dir, proposal)
        if not res.get("ok"):
            return _refusal(op, res.get("reason"))
        git_report = {"committed": False, "branch": None,
                      "reason": "git-disabled"}
        if git:
            git_report = _git_commit_on_branch(
                root,
                [skill_dir / _fns.NORTH_STAR_FILENAME,
                 _fns.history_dir(skill_dir)],
                branch=NORTH_STAR_BRANCH_PREFIX + skill,
                message="foundry.edit_north_star: %s (proposal %s)"
                % (skill, proposal.get("proposal_id")))
        return {
            "ok": True,
            "op": op,
            "mode": "apply",
            "skill": skill,
            "applied": True,
            "proposal_id": proposal.get("proposal_id"),
            "sha256": res["sha256"],
            "prior_retained": res["prior_retained"],
            "history_entry": res["entry"],
            "git": git_report,
            "verdict": "north-star-applied:%s" % skill,
        }

    return _refusal(op, "unknown-mode:%s" % mode)


# ── Op 4: foundry.register_autoload (Wave 8) ─────────────────────────────────

def register_autoload(*, map_path=None, home=None, root=None) -> dict:
    """Regenerate Anchor's clickable skill set from map.json v2 alone.

    The op body — a thin dispatch over ``foundry_autoload.sync_registrations``
    (the projection is rebuilt whole from the graph each run; an unreadable
    or invalid map refuses without touching the registry)."""
    op = "register_autoload"
    res = _fa.sync_registrations(map_path=map_path, home=home, root=root)
    if not res.get("ok"):
        return _refusal(op, res.get("reason"))
    return {
        "ok": True,
        "op": op,
        "count": res["count"],
        "registered": res["registered"],
        "runnable": res["runnable"],
        "registry_path": res["path"],
        "verdict": "autoload-registered:%d" % res["count"],
    }


#: CLI subcommand → op implementation.
_OP_IMPLS = {"scaffold_skill": scaffold_skill, "gen_manifest": gen_manifest,
             "edit_north_star": edit_north_star,
             "register_autoload": register_autoload}


# ── The op manifests (manifest-registered mutate ops) ────────────────────────

def _op_manifest(op_name, write_scope, *, python_exe=None, **over) -> dict:
    """One control-plane op manifest, built FROM the DR-01 decision record.

    A verb missing from ``MUTATIVE_VERBS`` or declared non-confirm-gated is a
    decision drift and breaks loudly — the inventory is the single source.
    """
    verb = _fd.MUTATIVE_VERBS.get(op_name)
    if not isinstance(verb, dict):
        raise ValueError("op %r not in the DR-01 mutative-verb inventory"
                         % op_name)
    if not verb.get("confirm_gated"):
        raise ValueError("op %r must be confirm-gated per DR-01" % op_name)
    cli_name = OP_CLI_NAMES[op_name]
    py = str(python_exe or sys.executable)
    m = {
        "skill": op_name,
        "skill_dir": str(ops_home()),
        "op_kind": _sr.OP_MUTATE,
        "host_cmd": [py, str(_THIS_FILE), cli_name],
        "output_contract": {"format": "json", "required_keys": ["ok", "op"]},
        "panel": {"title": "Foundry — " + cli_name.replace("_", " "),
                  "summary": verb.get("summary")},
        "journal": {"enabled": True,
                    "provenance": _sr.PROVENANCE_PREFIX
                    + "anchor.foundry_ops:" + cli_name},
        "tier": "standard",
        "capabilities": ["exec:" + py],
        "activation": {"trigger": "first_run"},
        "write_scope": [str(s) for s in write_scope],
        "timeout_s": OP_TIMEOUT_S,
    }
    m.update(over)
    return m


def scaffold_op_manifest(skills_root=None, map_path=None, lock_path=None,
                         **over) -> dict:
    root = Path(skills_root) if skills_root else _default_skills_root()
    mp = Path(map_path) if map_path else _fm.MAP_FILE
    lp = Path(lock_path) if lock_path else _fm.LOCK_FILE
    return _op_manifest(OP_SCAFFOLD, [root, mp, lp], **over)


def gen_manifest_op_manifest(skills_root=None, **over) -> dict:
    root = Path(skills_root) if skills_root else _default_skills_root()
    return _op_manifest(OP_GEN_MANIFEST, [root], **over)


def edit_north_star_op_manifest(skills_root=None, **over) -> dict:
    """The Wave-8 North-Star op manifest. Write scope: the skills root (the
    apply leg) + the proposals home (the propose leg parks there)."""
    root = Path(skills_root) if skills_root else _default_skills_root()
    return _op_manifest(OP_EDIT_NORTH_STAR, [root, _ns_proposals_home()],
                        **over)


def register_autoload_op_manifest(home=None, **over) -> dict:
    """The Wave-8 autoload op manifest. Write scope: the registration home
    under the Anchor data dir (the DR-01 "Anchor skill-registration state")."""
    h = Path(home) if home else _fa.autoload_home()
    return _op_manifest(OP_REGISTER_AUTOLOAD, [h], **over)


def control_plane_manifests(skills_root=None, map_path=None,
                            lock_path=None) -> list:
    """The Wave-7 op registry — pure data (declare-then-resolve). Frozen to
    its original pair; the full Phase-6 set is
    :func:`full_control_plane_manifests`."""
    return [
        scaffold_op_manifest(skills_root=skills_root, map_path=map_path,
                             lock_path=lock_path),
        gen_manifest_op_manifest(skills_root=skills_root),
    ]


def full_control_plane_manifests(skills_root=None, map_path=None,
                                 lock_path=None, autoload_home=None) -> list:
    """The FULL Phase-6 op registry: the Wave-7 pair + the Wave-8 pair."""
    return control_plane_manifests(
        skills_root=skills_root, map_path=map_path, lock_path=lock_path) + [
        edit_north_star_op_manifest(skills_root=skills_root),
        register_autoload_op_manifest(home=autoload_home),
    ]


def build_control_dispatch(skills_root=None, map_path=None,
                           lock_path=None) -> dict:
    """Declare-then-resolve the Wave-7 control-plane ops into a dispatch."""
    return _sr.build_dispatch(control_plane_manifests(
        skills_root=skills_root, map_path=map_path, lock_path=lock_path))


def build_full_control_dispatch(skills_root=None, map_path=None,
                                lock_path=None, autoload_home=None) -> dict:
    """Declare-then-resolve ALL Phase-6 ops (Waves 7+8) into a dispatch."""
    return _sr.build_dispatch(full_control_plane_manifests(
        skills_root=skills_root, map_path=map_path, lock_path=lock_path,
        autoload_home=autoload_home))


def write_targets_for(op, payload, *, skills_root=None, map_path=None,
                      lock_path=None) -> list:
    """The honest write-target list for one op invocation.

    Derived from where the mutation will actually land (the payload's seams,
    else the same defaults the manifests declare), so the runner's
    write-scope gate checks the REAL destinations — never a rubber stamp.
    """
    p = payload if isinstance(payload, dict) else {}
    root = Path(p.get("skills_root") or skills_root or _default_skills_root())
    if op == OP_SCAFFOLD:
        mp = Path(p.get("map_path") or map_path or _fm.MAP_FILE)
        lp = Path(p.get("lock_path") or lock_path or _fm.LOCK_FILE)
        return [str(root / str(p.get("name") or "")), str(mp), str(lp)]
    if op == OP_GEN_MANIFEST:
        return [str(root / str(p.get("skill") or "") / _sr.MANIFEST_FILENAME)]
    if op == OP_EDIT_NORTH_STAR:
        if str(p.get("mode") or "propose") == "apply":
            return [str(root / str(p.get("skill") or ""))]
        return [str(_ns_proposals_home())]
    if op == OP_REGISTER_AUTOLOAD:
        home = Path(p.get("home")) if p.get("home") else _fa.autoload_home()
        return [str(home / _fa.REGISTRY_FILENAME)]
    raise ValueError("unknown-control-op:%s" % op)


# ── Dispatch through job_runner (headless — the DR-01 execution path) ────────

def _job_runner_executor(entry, payload):
    """Run one op host as a server-owned ``job_runner`` job.

    Mounted on the runner's injectable executor seam, so every ``run_op``
    gate (activation, pre-flight, confirm token, write scope) has ALREADY
    passed before a job spawns. The payload rides as a file argument (the op
    job's stdin is DEVNULL); the durable job log carries the op's JSON
    result, which the runner's output contract then parses. Raises
    ``ValueError`` with the honest reason on a failed/cancelled/timed-out
    job — ``run_op`` records it as a failed (and journaled) op.
    """
    import job_runner as _jr
    home = Path(entry["skill_dir"])
    pdir = home / "payloads"
    pdir.mkdir(parents=True, exist_ok=True)
    pfile = pdir / ("payload-%s.json" % uuid.uuid4().hex)
    pfile.write_text(json.dumps(payload or {}, indent=2, ensure_ascii=False,
                                default=str), encoding="utf-8")
    argv = list(entry["argv"]) + ["--payload", str(pfile)]
    rec = _jr.launch(OPS_LANE, cwd=str(home), command=argv)
    entry["last_job"] = {"job_id": rec["job_id"], "lane": rec["lane"],
                         "log_path": rec["log_path"],
                         "status": rec["status"]}
    final = _jr.wait(rec["job_id"], timeout=_sr._timeout_for(entry)) or {}
    status = final.get("status")
    entry["last_job"]["status"] = status
    if status == _jr.STATUS_RUNNING:
        _jr.cancel(rec["job_id"])
        raise ValueError("op-job-timeout")
    try:
        pfile.unlink()
    except OSError:
        pass
    try:
        log_text = Path(final.get("log_path") or rec["log_path"]).read_text(
            encoding="utf-8", errors="replace")
    except OSError:
        log_text = ""
    if status != _jr.STATUS_DONE:
        tail = log_text.strip().splitlines()
        raise ValueError("op-job-%s%s" % (
            status, (":" + tail[-1][:200]) if tail else ""))
    return log_text


def run_control_op(dispatch, op, *, payload=None, confirm_token=None,
                   write_targets=None) -> dict:
    """Dispatch ONE control-plane mutate op — headlessly, via job_runner.

    The Wave-7 entry point: delegates to ``skill_runner.run_op`` with the
    job_runner-backed executor, so the mutate gates (single-use confirm
    token + declared write scope) and the Wave-2 auto-journal seam apply
    unchanged. ``write_targets`` defaults to the HONEST destinations derived
    from the payload (:func:`write_targets_for`). The result additionally
    carries ``job`` — the job_runner record projection for the op run
    (``None`` when the op was refused before any job spawned).
    """
    name = str(op)
    entry = dispatch.get(name)
    if entry is not None:
        entry.pop("last_job", None)
    if write_targets is None and name in OP_CLI_NAMES:
        write_targets = write_targets_for(name, payload or {})
    res = _sr.run_op(dispatch, name, payload=payload,
                     confirm_token=confirm_token,
                     write_targets=write_targets,
                     executor=_job_runner_executor)
    res["job"] = (entry or {}).get("last_job")
    return res


# ── The headless CLI (the op manifests' host) ────────────────────────────────

def _invoke_op(cli_name, payload) -> dict:
    """Run one op implementation against a payload dict — never raises."""
    fn = _OP_IMPLS.get(str(cli_name))
    if fn is None:
        return _refusal(str(cli_name), "unknown-op:%s" % cli_name)
    if not isinstance(payload, dict):
        return _refusal(cli_name, "payload-not-an-object")
    params = inspect.signature(fn).parameters
    unknown = sorted(k for k in payload if k not in params)
    if unknown:
        return _refusal(cli_name, "unknown-payload-key:" + ",".join(unknown))
    try:
        return fn(**payload)
    except Exception as exc:  # a crash is an honest failed result, not silence
        return {"ok": False, "op": str(cli_name), "refused": False,
                "reason": "op-crashed:%s: %s" % (type(exc).__name__, exc),
                "verdict": "failed:op-crashed"}


def main(argv=None) -> int:
    """``python foundry_ops.py <op> [--payload <file>]`` — the headless host.

    Payload: the ``--payload`` file when given (the job_runner dispatch
    path — the op job's stdin is DEVNULL), else stdin (the runner's default
    host path writes the payload there as JSON). Prints ONE JSON result
    object and exits 0 — op-level refusals and crashes are valid results the
    caller (and the journal) read by ``ok``/``reason``.
    """
    import argparse
    parser = argparse.ArgumentParser(prog="foundry_ops")
    parser.add_argument("op")
    parser.add_argument("--payload", default=None)
    args, _extra = parser.parse_known_args(argv)
    try:
        if args.payload:
            raw = Path(args.payload).read_text(encoding="utf-8")
        else:
            raw = sys.stdin.read()
    except OSError as exc:
        result = _refusal(args.op, "payload-unreadable:%s" % exc)
    else:
        try:
            payload = json.loads(raw) if raw.strip() else {}
        except ValueError as exc:
            result = _refusal(args.op, "payload-unparseable:%s" % exc)
        else:
            result = _invoke_op(args.op, payload)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
