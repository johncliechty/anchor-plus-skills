"""foundry_api.py — the REAL-data API layer behind the folded-in Foundry GUI.

This is a faithful Python port of ``foundry-gui/server.mjs`` (the standalone
Node sidecar the React app used to talk to). Folding the GUI INTO Anchor means
Anchor's ``anchor_gui.py`` now serves the built React app from
``foundry-gui/dist`` AND answers the app's ``/api/*`` calls itself — no second
server, no port 8780.

Every value traces to a file on disk (the manifest, each skill's SKILL.md +
journal, the North Star doc, the sleep-run artifacts); a missing file is an
honest empty, never a crash. The three ``sleep_session`` verbs spawn the REAL
foundry-v2 kernel CLI (``sleep-kernel-cli.mjs``) headlessly and return its
genuine JSON records — nothing here fabricates a proposal.

Stdlib only (json/os/re/subprocess/pathlib/shutil) — ``node`` is invoked as an
external CLI, exactly as Anchor already shells out to ``git``/``gh``.

The three ``sleep_session`` verbs (2026-10-10 boundary repair) run the kernel
ONLY against a PRIVATE candidate clone minted per proposal from the manifest
skill's OWNING repository at its frozen HEAD; apply/rollback re-bind the
proposal to a server-owned receipt (artifact hashes + source/candidate/base
identity) before the kernel is spawned, and "applied" always means "committed
on the candidate's branch", never "installed". See the kernel section below.
"""
import hashlib
import json
import os
import re
import secrets
import shutil
import signal
import stat
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import paths as _paths
import worktrees as _wt  # the ONE sanctioned git seam (git as an external CLI)

try:  # the kill-on-close containment Anchor's ChatGPT coder + the code jobs use
    from codex_adapter import _WindowsJob
except Exception:  # pragma: no cover - fails CLOSED on Windows (see _run_contained)
    _WindowsJob = None
try:
    import proc_probe as _pp  # taskkill /T fallback + liveness probes (stdlib ctypes)
except Exception:  # pragma: no cover
    _pp = None

# ── Path config (env-overridable, same defaults as server.mjs) ───────────────
ANCHOR_DIR = _paths.ANCHOR_DIR if hasattr(_paths, "ANCHOR_DIR") else Path(__file__).resolve().parent

#: The manifest ships in the Anchor repo root (foundry-v2 Wave 5).
MANIFEST_PATH = Path(os.environ.get("FOUNDRY_MAP")
                     or (ANCHOR_DIR / "foundry_map_v2.json"))
FOUNDRY_ROOT = os.environ.get("FOUNDRY_ROOT") or "C:/dev/Skill Foundry"
NORTH_STAR_PATH = (os.environ.get("FOUNDRY_NORTH_STAR")
                   or "C:/dev/plans/2026-07-foundry-v2/NORTH-STAR.md")

#: The REAL sleep-session kernel (foundry-v2 kernel build, Wave 2).
KERNEL_DIR = (os.environ.get("FOUNDRY_KERNEL_DIR")
              or "C:/dev/skill-foundry-kernel-wt/planning/portfolio-program")
KERNEL_CLI = str(Path(KERNEL_DIR) / "src" / "sleep-kernel-cli.mjs")
SKILLS_ROOT = os.environ.get("FOUNDRY_SKILLS_ROOT") or "C:/dev/Skill Foundry/skills"
#: Legacy (server.mjs parity). Propose no longer freezes THIS repo: the frozen
#: baseline is the manifest skill's OWN owning repository, cloned into a private
#: candidate (see the kernel section). Kept so existing readers keep importing.
SKILLS_REPO = os.environ.get("FOUNDRY_SKILLS_REPO") or str(Path(SKILLS_ROOT).parent)
#: Where proposal artifacts land (one dir per run) — matches server.mjs' default.
SLEEP_RUNS_DIR = Path(os.environ.get("FOUNDRY_SLEEP_RUNS")
                      or (ANCHOR_DIR / "foundry-gui" / "sleep-runs"))
KERNEL_TIMEOUT_S = int(os.environ.get("FOUNDRY_KERNEL_TIMEOUT_MS") or "180000") / 1000.0
#: PRIVATE candidate clones — one per proposal, BESIDE the checkout (John,
#: 2026-10-08: temporary builds live under C:\dev beside Anchor, never inside
#: it) and never inside the canonical skill repository. Env-overridable.
SLEEP_CANDIDATES_DIR = Path(os.environ.get("FOUNDRY_SLEEP_CANDIDATES")
                            or (ANCHOR_DIR.parent / "Anchor-foundry-sleep-candidates"))
#: Server-owned receipts (exact artifact hashes + source/candidate/base identity)
#: — under the control-plane home (``foundry_ops``' home under the data dir),
#: never beside the proposal artifacts a request points at.
SLEEP_RECEIPTS_DIR = Path(os.environ.get("FOUNDRY_SLEEP_RECEIPTS")
                          or (_paths.data_dir() / "foundry_ops" / "sleep_receipts"))
PROPOSAL_SCHEMA = "foundry.sleep_session/proposal@1"
RECEIPT_SCHEMA = "foundry.sleep_session/receipt@1"
BINDING_SCHEMA = "foundry.sleep_session/anchor-binding@1"
#: The confirm token the kernel records in its apply artifact (the human clicked).
CONFIRM_TOKEN = "foundry-gui-user"


def _node_cmd() -> str:
    """The node executable (FOUNDRY_NODE override, else `node` on PATH)."""
    return os.environ.get("FOUNDRY_NODE") or shutil.which("node") or "node"


# ── safe fs helpers (a missing file is an honest empty, never a crash) ────────

def _read_text_safe(file_path) -> str:
    try:
        return Path(file_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return None


def _stat_safe(file_path):
    try:
        return os.stat(file_path)
    except OSError:
        return None


def _read_dir_safe(dir_path):
    try:
        return list(os.scandir(dir_path))
    except OSError:
        return []


# ── real-data extraction (ports of server.mjs) ───────────────────────────────

def _is_default_foundry_root():
    return str(FOUNDRY_ROOT).replace("\\", "/").rstrip("/").lower() == "c:/dev/skill foundry"


def _resolve_source(source):
    """Resolve a manifest ``source`` to an absolute directory."""
    if not source:
        return None
    primary = source if re.match(r"^[A-Za-z]:[\\/]", source) else os.path.join(FOUNDRY_ROOT, source)
    if os.path.isdir(primary):
        return primary
    if _is_default_foundry_root():
        leaf = Path(source.replace("\\", "/")).name
        for root in (ANCHOR_DIR.parent / "skills", ANCHOR_DIR / "vendor" / "bundled-skills"):
            cand = root / leaf
            if cand.is_dir():
                return str(cand)
    return primary


def _extract_yaml_description(frontmatter):
    """Extract the ``description:`` value from YAML frontmatter — handling both
    an INLINE scalar (``description: text``) AND a BLOCK scalar
    (``description: >-`` / ``|`` folded or literal, the value on the following
    indented lines). Returns "" when absent.

    server.mjs (and this port's first cut) only read the same line as
    ``description:``, so a block scalar yielded just the ``>-`` indicator — the
    reason crucible/foreman showed an empty North Star while inline-description
    skills (researchPrime, gandalf, …) worked.
    """
    lines = re.split(r"\r?\n", frontmatter)
    for i, line in enumerate(lines):
        m = re.match(r"^description:[ \t]*(.*)$", line)
        if not m:
            continue
        inline = m.group(1).strip()
        block = re.match(r"^([>|])[-+]?\s*$", inline)  # >, >-, >+, |, |-, |+
        if not block:
            return inline  # a plain inline scalar (or empty)
        style = block.group(1)  # '>' folded | '|' literal
        collected = []
        for cont in lines[i + 1:]:
            if cont.strip() == "":
                collected.append("")  # blank line inside the block
                continue
            if len(cont) - len(cont.lstrip()) == 0:
                break  # dedent to a new top-level key — block ended
            collected.append(cont.strip())
        while collected and collected[-1] == "":
            collected.pop()
        if style == "|":  # literal: keep line breaks
            return "\n".join(collected)
        # folded: blank line = paragraph break, otherwise space-join
        paras, para = [], []
        for c in collected:
            if c == "":
                if para:
                    paras.append(" ".join(para))
                    para = []
            else:
                para.append(c)
        if para:
            paras.append(" ".join(para))
        return "\n\n".join(paras)
    return ""


def _parse_skill_md(text):
    """Parse SKILL.md into ``{description, body}``. Frontmatter is optional."""
    if not text:
        return {"description": "", "body": ""}
    body = text
    description = ""
    fm = re.match(r"^---\r?\n([\s\S]*?)\r?\n---\r?\n?", text)
    if fm:
        body = text[len(fm.group(0)):]
        description = _extract_yaml_description(fm.group(1))
    return {"description": description, "body": body}


def _parse_human_md(text):
    """Parse HUMAN.md (people-first skill card) into one-sentence + body.

    Prefer ``**One sentence:** …`` then first non-heading line. Used for
    human-facing Foundry UI surfaces; agent SKILL.md stays the protocol source.
    """
    if not text:
        return {"oneSentence": "", "body": ""}
    body = str(text).strip()
    one = ""
    m = re.search(r"\*\*One sentence:\*\*\s*(.+?)(?:\r?\n|$)", body, re.IGNORECASE)
    if not m:
        m = re.search(r"^One sentence:\s*(.+?)(?:\r?\n|$)", body, re.IGNORECASE | re.MULTILINE)
    if m:
        one = re.sub(r"\s+", " ", m.group(1).strip())
    if not one:
        for line in re.split(r"\r?\n", body):
            t = line.strip()
            if not t or t.startswith("#"):
                continue
            one = re.sub(r"^\*\*|\*\*$", "", t).strip()
            break
    return {"oneSentence": one, "body": body}


def _extract_sections(body):
    """Top-level ``## `` section titles from the SKILL.md body."""
    if not body:
        return []
    out = []
    for line in re.split(r"\r?\n", body):
        m = re.match(r"^##\s+(.+)$", line)
        if m:
            out.append(m.group(1).strip())
    return out


def _extract_section_details(body):
    """Return ``[{title, detail}]`` for each top-level ``## `` section — the
    heading plus its markdown body (until the next ``## `` or a new ``# ``
    heading, or the end). Powers the click-to-expand Capabilities tile: each
    bullet (the title) reveals its section's real content. Long sections are
    truncated to keep the /api/skills payload sane."""
    if not body:
        return []
    sections = []
    cur = None
    for line in re.split(r"\r?\n", body):
        if re.match(r"^##\s+(.+)$", line):
            if cur is not None:
                sections.append(cur)
            cur = {"title": re.match(r"^##\s+(.+)$", line).group(1).strip(),
                   "lines": []}
        elif re.match(r"^#\s+(.+)$", line) and cur is not None:
            sections.append(cur)  # a new '# ' heading closes the ## section
            cur = None
        elif cur is not None:
            cur["lines"].append(line)
    if cur is not None:
        sections.append(cur)
    out = []
    for s in sections:
        detail = "\n".join(s["lines"]).strip()
        if len(detail) > 12000:
            detail = detail[:12000].rstrip() + "\n\n…(truncated)"
        out.append({"title": s["title"], "detail": detail})
    return out


def _first_paragraph(body):
    """First non-empty paragraph (per-skill north-star fallback)."""
    if not body:
        return ""
    for block in re.split(r"\r?\n\s*\r?\n", body):
        if block.strip():
            return block.strip()
    return ""


def _journal_events(skill_dir):
    """Real journal entries for a skill dir: files directly in
    ``<dir>/journal/*.md``, ignoring README.md, subdirectories and all-caps
    files. Each = ``{event, timestamp (mtime ms), status:'success', details}``.
    """
    journal_dir = os.path.join(skill_dir, "journal")
    events = []
    for dirent in _read_dir_safe(journal_dir):
        if not dirent.is_file():
            continue
        file_name = dirent.name
        low = file_name.lower()
        if not low.endswith(".md"):
            continue
        if low == "readme.md":
            continue
        base = re.sub(r"\.md$", "", file_name, flags=re.IGNORECASE)
        # all-caps entries (SYNTHESIS.md etc.) are not run records
        if re.search(r"[A-Z]", base) and not re.search(r"[a-z]", base):
            continue
        file_path = os.path.join(journal_dir, file_name)
        st = _stat_safe(file_path)
        if not st:
            continue
        text = _read_text_safe(file_path)
        encoding = "utf-8"
        if text is None:
            # Older Windows journal entries predate the UTF-8 convention.
            # Qualify this display decoding; never rewrite source bytes or
            # apply a legacy decoder to JSON/configuration authority.
            try:
                text = Path(file_path).read_text(encoding="cp1252")
                encoding = "windows-1252"
            except (OSError, UnicodeError):
                text, encoding = "", "unreadable"
        heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if heading:
            title = heading.group(1).strip()
        else:
            first_line = next((l for l in re.split(r"\r?\n", text) if l.strip()), None)
            title = first_line.strip() if first_line else base
        details = text
        if heading:
            details = details.replace(heading.group(0), "")
        details = details.strip()[:280]
        events.append({
            "event": title,
            "timestamp": st.st_mtime * 1000.0,
            "status": "success",
            "details": details,
            "sourceEncoding": encoding,
        })
    events.sort(key=lambda e: e["timestamp"], reverse=True)
    return events


def _load_manifest():
    """Load the manifest fresh; ``[]`` when missing/unparseable."""
    text = _read_text_safe(MANIFEST_PATH)
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []
    skills = parsed.get("skills")
    return skills if isinstance(skills, list) else []


def build_skills():
    """The full real ``/api/skills`` payload from the manifest + each skill's
    files. Human-facing ``description`` / ``northStar`` prefer HUMAN.md when
    present; SKILL.md remains agent protocol (agentDescription + sections)."""
    out = []
    for entry in _load_manifest():
        skill_dir = _resolve_source(entry.get("source"))
        skill_md = _read_text_safe(os.path.join(skill_dir, "SKILL.md")) if skill_dir else None
        human_md = _read_text_safe(os.path.join(skill_dir, "HUMAN.md")) if skill_dir else None
        parsed = _parse_skill_md(skill_md)
        agent_description, body = parsed["description"], parsed["body"]
        human = _parse_human_md(human_md)
        description = human["oneSentence"] or agent_description or _first_paragraph(body)
        north_star = (human["body"][:4000] if human["body"]
                      else (agent_description or _first_paragraph(body)))
        human_sections = _extract_sections(human["body"]) if human["body"] else []
        agent_sections = _extract_sections(body)
        human_details = _extract_section_details(human["body"]) if human["body"] else []
        agent_details = _extract_section_details(body)
        timeline = _journal_events(skill_dir) if skill_dir else []
        edges = entry.get("edges") if isinstance(entry.get("edges"), list) else []
        src = entry.get("source") or ""
        out.append({
            "ref": entry.get("ref", ""),
            "name": entry.get("name", ""),
            "source": src,
            "status": entry.get("status", ""),
            "tier": entry.get("tier", ""),
            "version": entry.get("version", ""),
            "description": description,
            "agentDescription": agent_description or "",
            "humanCard": bool(human_md),
            "humanOneSentence": human["oneSentence"] or "",
            "northStar": north_star,
            "file_path": (src + "/SKILL.md") if src else "",
            "human_path": (src + "/HUMAN.md") if (src and human_md) else "",
            "capabilities": human_sections if human_sections else agent_sections,
            "capabilitySections": human_details if human_details else agent_details,
            "dependencies": [d for d in (
                re.sub(r"^skill:", "", str(e.get("to", ""))) for e in edges) if d],
            "edges": edges,
            "timeline": timeline,
            "journalCount": len(timeline),
        })
    return out


def load_north_star():
    text = _read_text_safe(NORTH_STAR_PATH)
    if not text and str(NORTH_STAR_PATH).replace("\\", "/").lower() == "c:/dev/plans/2026-07-foundry-v2/north-star.md":
        text = _read_text_safe(ANCHOR_DIR / "vendor" / "foundry-page-maps" / "NORTH-STAR.md")
    return text.strip() if text else ("North Star file not found — expected at " + NORTH_STAR_PATH)


def _sleep_run_stats():
    """REAL sleep-run stats from the artifacts on disk (a run = a proposal.json dir)."""
    runs = 0
    last_improved = None
    for dirent in _read_dir_safe(SLEEP_RUNS_DIR):
        if not dirent.is_dir():
            continue
        run_dir = os.path.join(SLEEP_RUNS_DIR, dirent.name)
        if not _stat_safe(os.path.join(run_dir, "proposal.json")):
            continue
        runs += 1
        apply_path = os.path.join(run_dir, "apply-result.json")
        apply_stat = _stat_safe(apply_path)
        if apply_stat:
            try:
                rec = json.loads(_read_text_safe(apply_path) or "null")
                if rec and rec.get("outcome") == "applied":
                    last_improved = max(last_improved or 0, apply_stat.st_mtime * 1000.0)
            except (json.JSONDecodeError, ValueError):
                pass
    return {"runs": runs, "lastImproved": last_improved}


def build_summary():
    stats = _sleep_run_stats()
    if stats["runs"] == 0:
        return ('No sleep session has run yet — use "Run sleep session" in the '
                "Sleep & Training tile to propose one from the journal.")
    return (f"{stats['runs']} sleep-session run(s) recorded under sleep-runs/"
            + (" (at least one proposal applied on a private candidate branch — "
               "nothing installed)."
               if stats["lastImproved"] else " (no proposal applied yet)."))


def build_timeline():
    all_events = [e for s in build_skills() for e in s["timeline"]]
    all_events.sort(key=lambda e: e["timestamp"], reverse=True)
    return all_events


def build_metrics(skills=None):
    if skills is None:
        skills = build_skills()
    stats = _sleep_run_stats()
    return {
        "skills": len(skills),
        "journalEntries": sum(s["journalCount"] for s in skills),
        "sleepRuns": stats["runs"],
        "lastImproved": stats["lastImproved"],
    }


def build_agent_payload():
    skills = build_skills()
    return {
        "timestamp": 0,  # no wall-clock reads; 0 = "not from a file"
        "version": "2.0.0",
        "northStar": load_north_star(),
        "summary": build_summary(),
        "metrics": build_metrics(skills),
        "skillCount": len(skills),
    }


# ── the REAL sleep-session kernel (spawned, never simulated) ─────────────────
#
# THE BOUNDARY (2026-10-10 repair). The kernel's ``apply`` checks out a branch
# off the frozen baseline, writes the lesson, ``git add -A`` + commits, and its
# ``rollback`` is a ``git reset --hard``. Those verbs are therefore pointed ONLY
# at a PRIVATE CANDIDATE CLONE this server mints per proposal — never at the
# installed / canonical skill repository:
#
#   propose  → the manifest entry the request names → its ``source`` resolved to
#              a REAL path (junctions followed) → the owning git repo (toplevel
#              of the REAL path — a junction's lexical parent chain is never
#              walked) → that repo's HEAD, frozen → ``git clone`` into
#              <candidates>/<skill>-<nonce>, detached at that HEAD (a fresh
#              ``.git``: no shared writable metadata, no hooks, no remote, none
#              of the installed checkout's uncommitted changes) → kernel
#              ``propose <candidate>/<skill> --corpus <canonical skill> --repo
#              <candidate>`` so ``baseline.repoDir`` in the artifact IS the
#              candidate → a server-owned RECEIPT (sha256 of every kernel-written
#              input + the source/candidate/base identity) under the control-
#              plane home — never beside the artifacts a request points at.
#   apply /  → the proposal dir is re-bound to its receipt (hashes + identity),
#   rollback   structurally re-validated (the gate argv, every unit path and the
#              change target are RECOMPUTED here and compared — the artifact can
#              never introduce a command or a path of its own), the candidate is
#              checked (a private clone, HEAD descending from the frozen base,
#              clean — never reset) and only then the kernel runs with
#              ``--work-repo <candidate>``.
#
# "applied" means: committed on a branch of the CANDIDATE clone. Nothing is
# installed; improvements land through the existing code jobs / review.

def _close_job(job):
    if job is None:
        return
    try:
        job.close()
    except Exception:
        pass


def _kill_tree(proc):
    """Fallback kill when the containment cannot end the tree itself."""
    try:
        if os.name == "nt":
            if _pp is not None:
                _pp.tree_kill(proc.pid)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
    except Exception:
        pass
    try:
        proc.kill()
    except Exception:
        pass


def _drain(proc):
    try:
        out, err = proc.communicate(timeout=5)
    except Exception:
        out, err = "", ""
    return out or "", err or ""


def _run_contained(cmd, cwd, timeout):
    """Run ``cmd`` headlessly (no console window) INSIDE a kill-on-close
    containment → ``{status, spawnError, timedOut, stdout, stderr, contained}``;
    never raises.

    Windows: the existing ``codex_adapter._WindowsJob`` — the child starts
    SUSPENDED, is assigned to a verified kill-on-close Job Object, then resumed,
    so no grandchild can ever escape; a timeout terminates the whole job and the
    job handle's close reaps any straggler. A containment failure never runs the
    child uncontained (it is aborted while still suspended → an honest
    ``spawnError``). Elsewhere: a new session, killed as a group on timeout.
    """
    windows = os.name == "nt"
    job = None
    if windows:
        if _WindowsJob is None:
            return {"status": None, "timedOut": False, "stdout": "", "stderr": "",
                    "contained": False,
                    "spawnError": "kernel containment unavailable (codex_adapter._WindowsJob)"}
        try:
            job = _WindowsJob()
        except Exception as exc:
            return {"status": None, "timedOut": False, "stdout": "", "stderr": "",
                    "contained": False,
                    "spawnError": "kernel containment unavailable: %s" % exc}
    kwargs = dict(cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                  stderr=subprocess.PIPE, text=True, encoding="utf-8",
                  errors="replace")
    if windows:
        kwargs["creationflags"] = _paths.NO_WINDOW | _WindowsJob.CREATE_SUSPENDED
    else:
        kwargs["start_new_session"] = True
    try:
        proc = subprocess.Popen(cmd, **kwargs)
    except (OSError, ValueError) as exc:
        _close_job(job)
        return {"status": None, "spawnError": str(exc), "timedOut": False,
                "stdout": "", "stderr": "", "contained": False}
    if job is not None:
        try:
            if not job.assign_and_resume(proc):
                raise OSError("kernel process was not resumed")
        except Exception as exc:
            if not job.abort_suspended(proc):
                _kill_tree(proc)
            _drain(proc)
            _close_job(job)
            return {"status": None, "timedOut": False, "stdout": "", "stderr": "",
                    "contained": False,
                    "spawnError": "kernel could not be contained: %s" % exc}
    timed_out = False
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        if job is None or not job.terminate_verified(proc, timeout_seconds=10.0):
            _kill_tree(proc)
        out, err = _drain(proc)
    finally:
        if job is not None:
            try:
                job.verify_empty(timeout_seconds=2.0)
            except Exception:
                pass
            _close_job(job)  # KILL_ON_CLOSE: a descendant that outlived the kernel dies here
    return {"status": None if timed_out else proc.returncode, "spawnError": None,
            "timedOut": timed_out, "stdout": out or "", "stderr": err or "",
            "contained": True}


def _run_kernel(args):
    """Spawn ``node <KERNEL_CLI> <verb> <args…>`` headlessly inside the
    containment (:func:`_run_contained`), bounded by ``KERNEL_TIMEOUT_S`` (the
    kernel's own 180 s budget — never shorter). Never raises — returns
    ``{status, spawnError, timedOut, stdout, stderr, contained}`` so the caller
    surfaces the kernel's honest exit codes (0 ok / 3 refused / 1 blocked)."""
    return _run_contained([_node_cmd(), KERNEL_CLI, *[str(a) for a in args]],
                          KERNEL_DIR, KERNEL_TIMEOUT_S)


def _parse_kernel_json(stdout):
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


# ── path identity (real paths · junction/symlink refusal · hashes) ───────────

_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_PROPOSAL_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
#: The kernel's ``slugify`` output shape (lowercase, ``-``-joined, ≤ 60 chars).
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,59}$")
#: The per-unit artifacts the kernel writes (proposal row key → file name). The
#: regression test is EXECUTED and change.json is WRITTEN THROUGH at apply.
_UNIT_FILES = (("diffPath", "diff.patch"), ("changePath", "change.json"),
               ("regressionPath", "regression.test.mjs"),
               ("provenancePath", "provenance.json"))
_NODE_BASENAMES = ("node", "node.exe")


def _real(p) -> str:
    return os.path.realpath(str(p))


def _norm(p) -> str:
    """Canonical comparison form: the REAL path (symlinks, junctions and 8.3
    aliases resolved), case-folded."""
    return os.path.normcase(_real(p))


def _same(a, b) -> bool:
    return _norm(a) == _norm(b)


def _within(child, root) -> bool:
    c, r = _norm(child), _norm(root).rstrip(os.sep)
    return c == r or c.startswith(r + os.sep)


def _is_reparse_point(p) -> bool:
    """A symlink (any OS) or a Windows junction/reparse point — never traversed."""
    try:
        st = os.lstat(p)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _plain_child(root_real, *parts):
    """``<root_real>/<parts…>`` when every component below the root is a single
    plain name (no separators, no ``.``/``..``, no reparse point) and the
    result resolves to itself (no alias); else ``None``."""
    cur = root_real
    for part in parts:
        if (not part or part in (os.curdir, os.pardir) or os.sep in part
                or (os.altsep and os.altsep in part)):
            return None
        cur = os.path.join(cur, part)
        if _is_reparse_point(cur):
            return None
    if os.path.normcase(os.path.normpath(cur)) != _norm(cur):
        return None
    return cur


def _sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path):
    text = _read_text_safe(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _rmtree_force(path):
    """Best-effort removal of a candidate clone (git objects are read-only on
    Windows); never raises."""
    def _retry(func, p, *_exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(path, onexc=_retry)
        else:
            shutil.rmtree(path, onerror=_retry)
    except OSError:
        pass


def _git(repo, args, timeout=None):
    """``git -C <repo> <args>`` through the ONE sanctioned seam
    (``worktrees._git``) → ``(ok, rc, out, err)``; never raises. A clone of a
    large repository gets the kernel's own budget, never a shorter one."""
    return _wt._git(repo, args, timeout=timeout or KERNEL_TIMEOUT_S)


def _resolve_proposal_dir(body):
    """Resolve ``{proposalPath | proposalId}`` to the proposal dir — which MUST
    be a PLAIN direct child of SLEEP_RUNS_DIR (every proposal this server mints
    is): no nesting, no ``..``, no symlink/junction component, no alias.
    Anything else is refused (``None``)."""
    runs_root = _real(SLEEP_RUNS_DIR)
    name = None
    raw_path, raw_id = body.get("proposalPath"), body.get("proposalId")
    if isinstance(raw_path, str) and raw_path.strip():
        parent, name = os.path.split(os.path.abspath(raw_path.strip()).rstrip("\\/"))
        if not parent or not _same(parent, runs_root):
            return None
    elif isinstance(raw_id, str) and raw_id.strip():
        name = raw_id.strip()
    if not name or not _PROPOSAL_ID_RE.match(name):
        return None
    return _plain_child(runs_root, name)


# ── manifest routing → the frozen canonical source ───────────────────────────

def _manifest_entry_for(skill):
    """The manifest entry the request's ``skill`` names — matched
    case-insensitively on the entry ``name``, its ``ref`` (with or without the
    ``skill:`` prefix) or the basename of its ``source`` (what the Sleep tile
    posts). ``(entry, None)`` or ``(None, reason)``; ambiguity is refused,
    never guessed."""
    want = skill.strip().lower()
    hits = []
    for entry in _load_manifest():
        if not isinstance(entry, dict):
            continue
        ref = str(entry.get("ref") or "").lower()
        aliases = {str(entry.get("name") or "").lower(), ref,
                   re.sub(r"^skill:", "", ref)}
        src = str(entry.get("source") or "").rstrip("\\/")
        if src:
            aliases.add(re.split(r"[\\/]", src)[-1].lower())
        aliases.discard("")
        if want in aliases:
            hits.append(entry)
    if not hits:
        return None, "not in the Foundry manifest"
    if len(hits) > 1:
        exact = [e for e in hits if str(e.get("name") or "").lower() == want]
        if len(exact) != 1:
            return None, "ambiguous — names %d manifest entries" % len(hits)
        return exact[0], None
    return hits[0], None


def _bind_source(entry):
    """Resolve a manifest entry to its FROZEN canonical source: the REAL skill
    dir (junctions followed), the owning git repository (toplevel of the REAL
    path — a junction's lexical parent chain is never walked) and the repo HEAD
    to freeze. ``(source, None)`` or ``(None, (payload, status))``. Read-only."""
    label = str(entry.get("name") or entry.get("ref") or "?")
    resolved = _resolve_source(entry.get("source"))
    if not resolved:
        return None, ({"error": "manifest entry %s has no source" % label}, 404)
    if not os.path.isdir(resolved):
        return None, ({"error": "manifest source for %s not found on disk: %s"
                       % (label, resolved)}, 404)
    real = _real(resolved)
    ok, _rc, out, err = _git(real, ["rev-parse", "--show-toplevel"])
    if not ok or not out.strip():
        return None, ({"error": "manifest source for %s is not inside a git "
                       "repository (nothing to freeze): %s" % (label, real),
                       "stderr": err}, 409)
    repo = _real(out.strip())
    if not _within(real, repo):
        return None, ({"error": "manifest source for %s escapes its repository "
                       "after link resolution: %s" % (label, real)}, 409)
    ok, _rc, head, err = _git(real, ["rev-parse", "--verify", "HEAD^{commit}"])
    head = head.strip()
    if not ok or not _SHA_RE.match(head):
        return None, ({"error": "the repository of %s has no HEAD commit to "
                       "freeze: %s" % (label, repo), "stderr": err}, 409)
    rel = os.path.relpath(real, repo)
    return {
        "ref": str(entry.get("ref") or ""), "name": str(entry.get("name") or ""),
        "source": str(entry.get("source") or ""), "dir": real, "repo": repo,
        "rel": "" if rel == os.curdir else rel.replace(os.sep, "/"),
        "head": head, "basename": os.path.basename(real.rstrip("\\/")) or label,
    }, None


# ── the PRIVATE candidate clone ──────────────────────────────────────────────

def _mint_candidate(source):
    """Clone the owning repository into a PRIVATE candidate detached at the
    frozen HEAD: a fresh ``.git`` (no shared writable metadata), no templates,
    ``core.hooksPath`` pinned to an empty dir (no local OR global hook can run
    in it), no remote (nothing in it can push back), only COMMITTED state (the
    installed checkout's index / dirty / untracked files never ride along).
    ``(candidate, None)`` or ``(None, (payload, status))``; nothing is left
    behind on failure."""
    root = Path(SLEEP_CANDIDATES_DIR)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return None, ({"error": "candidates dir unavailable: %s" % exc}, 500)
    root_real = _real(root)
    cand_id = "%s-%d-%s" % (source["basename"], time.time_ns(), secrets.token_hex(4))
    cand = os.path.join(root_real, cand_id)
    no_hooks = os.path.join(cand, ".git", "anchor-no-hooks")
    steps = (
        (root_real, ["clone", "--quiet", "--no-checkout", "--template=", "--",
                     source["repo"], cand]),
        (cand, ["config", "core.hooksPath", no_hooks]),
        (cand, ["config", "user.name", "Anchor sleep candidate"]),
        (cand, ["config", "user.email", "anchor@localhost"]),
        (cand, ["config", "commit.gpgsign", "false"]),
        (cand, ["remote", "remove", "origin"]),
        (cand, ["checkout", "--quiet", "--detach", source["head"]]),
    )
    for cwd, args in steps:
        ok, _rc, _out, err = _git(cwd, args)
        if not ok:
            _rmtree_force(cand)
            return None, ({"error": "candidate clone failed at `git %s`: %s"
                           % (" ".join(args[:2]), err.strip() or "git error")}, 500)
        if args[0] == "clone":
            try:
                os.makedirs(no_hooks, exist_ok=True)
            except OSError:
                pass
    ok, _rc, head, _err = _git(cand, ["rev-parse", "--verify", "HEAD^{commit}"])
    if not ok or head.strip() != source["head"]:
        _rmtree_force(cand)
        return None, ({"error": "candidate is not at the frozen HEAD %s"
                       % source["head"]}, 500)
    skill_dir = os.path.join(cand, *source["rel"].split("/")) if source["rel"] else cand
    if not os.path.isdir(skill_dir):
        _rmtree_force(cand)
        return None, ({"error": "the skill's files are not committed in %s — "
                       "nothing frozen to propose against" % source["repo"]}, 409)
    return {"id": cand_id, "dir": cand, "skill_dir": skill_dir, "root": root_real}, None


def _candidate_state(cand_dir, baseline_sha, root_real, allowed_head=None):
    """Is the candidate still the private clone the proposal was minted against
    — a plain dir inside the candidates root owning its OWN ``.git`` dir (never
    a gitfile sharing another repository's metadata), HEAD descending from the
    frozen baseline, and CLEAN? Never resets anything; a stale or dirty
    candidate is an honest refusal."""
    state = {"ok": False, "dir": cand_dir, "head": None, "descends": False,
             "dirty": [], "reason": None}
    if (not _within(cand_dir, root_real) or _same(cand_dir, root_real)
            or _is_reparse_point(cand_dir) or not os.path.isdir(cand_dir)):
        state["reason"] = ("candidate is not a plain directory inside this "
                           "server's candidates root (removed or moved?); re-run propose")
        return state
    git_dir = os.path.join(cand_dir, ".git")
    if not os.path.isdir(git_dir) or _is_reparse_point(git_dir):
        state["reason"] = ("candidate does not own its .git (a gitfile/worktree "
                           "would share another repository's metadata)")
        return state
    ok, _rc, head, err = _git(cand_dir, ["rev-parse", "--verify", "HEAD^{commit}"])
    head = head.strip()
    if not ok or not _SHA_RE.match(head):
        state["reason"] = "candidate HEAD unreadable: %s" % (err.strip() or "git error")
        return state
    state["head"] = head
    if head not in {baseline_sha, allowed_head or baseline_sha}:
        state["reason"] = "candidate HEAD changed since the recorded operation; preserving committed work"
        return state
    ok, _rc, _out, _err = _git(cand_dir, ["cat-file", "-e", baseline_sha + "^{commit}"])
    if not ok:
        state["reason"] = "the frozen baseline %s is not in the candidate" % baseline_sha
        return state
    ok, _rc, _out, _err = _git(cand_dir, ["merge-base", "--is-ancestor", baseline_sha, head])
    state["descends"] = bool(ok)
    if not ok:
        state["reason"] = ("candidate HEAD %s does not descend from the frozen "
                           "baseline %s — a stale/foreign candidate; re-run propose"
                           % (head[:12], baseline_sha[:12]))
        return state
    ok, _rc, out, err = _git(cand_dir, ["status", "--porcelain", "--untracked-files=all", "--ignored"])
    if not ok:
        state["reason"] = "candidate status unreadable: %s" % (err.strip() or "git error")
        return state
    dirty = [line[3:].strip() for line in out.splitlines() if len(line) > 3]
    state["dirty"] = dirty
    if dirty:
        shown = ", ".join(dirty[:5]) + (" …" if len(dirty) > 5 else "")
        state["reason"] = ("candidate has %d uncommitted change(s) (%s) — refusing "
                           "to reset them; re-run propose for a fresh candidate"
                           % (len(dirty), shown))
        return state
    state["ok"] = True
    return state


# ── artifact re-validation + the server-owned receipt ────────────────────────

def _frozen_benchmark_files(skill_dir):
    """Mirror the kernel's contained, explicit test-file contract; never trust proposal argv."""
    test_dir = _plain_child(skill_dir, "test")
    if not test_dir or not os.path.isdir(test_dir):
        raise ValueError("skill has no plain test directory")
    files = []
    for current, directories, names in os.walk(test_dir, followlinks=False):
        for name in directories + names:
            if _is_reparse_point(os.path.join(current, name)):
                raise ValueError("benchmark contains a link or reparse point")
        files.extend(os.path.join(current, name) for name in names
                     if re.search(r"\.test\.(?:mjs|cjs|js)$", name)
                     and os.path.isfile(os.path.join(current, name)))
    files.sort()
    if not files:
        raise ValueError("benchmark has no test files")
    return files


def _validate_artifact(proposal, proposal_dir, expect):
    """Structural re-validation of a kernel proposal against RECOMPUTED
    expectations (``expect``: source_dir · candidate_dir · candidate_skill_dir
    · baseline_sha). Everything the kernel's ``apply`` would EXECUTE or WRITE
    THROUGH — the gate argv, each unit's artifact paths, the change target —
    must equal what this server derives itself, so the artifact can never
    introduce a command or a path. ``(True, None)`` or ``(False, reason)``."""
    if not isinstance(proposal, dict):
        return False, "proposal.json is not an object"
    if proposal.get("schema") != PROPOSAL_SCHEMA:
        return False, "unexpected proposal schema %r" % (proposal.get("schema"),)
    cand, skill_dir, src = (expect["candidate_dir"], expect["candidate_skill_dir"],
                            expect["source_dir"])
    if proposal.get("skill") != os.path.basename(skill_dir.rstrip("\\/")):
        return False, "proposal skill %r is not the candidate skill" % (proposal.get("skill"),)
    if not isinstance(proposal.get("skillDir"), str) or not _same(proposal["skillDir"], skill_dir):
        return False, "proposal skillDir is not the candidate skill dir"
    if not isinstance(proposal.get("corpusDir"), str) or not _same(proposal["corpusDir"], src):
        return False, "proposal corpusDir is not the canonical source"
    baseline = proposal.get("baseline")
    if not isinstance(baseline, dict):
        return False, "proposal has no baseline"
    if not isinstance(baseline.get("repoDir"), str) or not _same(baseline["repoDir"], cand):
        return False, ("baseline.repoDir is not the private candidate (apply/rollback "
                       "would target another repository)")
    sha = str(baseline.get("sha") or "")
    if sha != expect["baseline_sha"] or not _SHA_RE.match(sha):
        return False, "baseline.sha %r is not the frozen source HEAD" % (baseline.get("sha"),)
    gate = proposal.get("eval_gate")
    argv = gate.get("argv") if isinstance(gate, dict) else None
    try:
        expected_tests = _frozen_benchmark_files(skill_dir)
    except (OSError, ValueError) as exc:
        return False, "could not verify the frozen benchmark: %s" % exc
    if (not isinstance(argv, list) or len(argv) != 3 + len(expected_tests)
            or not all(isinstance(a, str) for a in argv)
            or os.path.basename(argv[0]).lower() not in _NODE_BASENAMES
            or argv[1:3] != ["--test", "--test-reporter=tap"]
            or not all(_same(got, want) for got, want in zip(argv[3:], expected_tests))):
        return False, "eval_gate.argv is not the complete frozen TAP benchmark"
    bgate = baseline.get("gate")
    if not isinstance(bgate, dict) or bgate.get("argv") != argv:
        return False, "baseline.gate differs from eval_gate"
    units = proposal.get("units")
    if not isinstance(units, list):
        return False, "proposal.units is not a list"
    want_file = os.path.relpath(os.path.join(skill_dir, "LESSONS.md"), cand).replace(os.sep, "/")
    seen = set()
    for unit in units:
        if not isinstance(unit, dict):
            return False, "a unit is not an object"
        slug = unit.get("slug")
        if not isinstance(slug, str) or not _SLUG_RE.match(slug) or slug in seen:
            return False, "unit slug %r is malformed or duplicated" % (slug,)
        seen.add(slug)
        if not isinstance(unit.get("class"), str):
            return False, "unit %s has no provenance class" % slug
        for key, name in _UNIT_FILES:
            want = _plain_child(proposal_dir, "units", slug, name)
            got = unit.get(key)
            if (want is None or not isinstance(got, str) or not _same(got, want)
                    or not os.path.isfile(want)):
                return False, "unit %s: %s is not the plain artifact %s" % (slug, key, name)
        change = _read_json(unit["changePath"])
        if not isinstance(change, dict):
            return False, "unit %s: change.json unreadable" % slug
        if change.get("file") != want_file:
            return False, ("unit %s: change target %r is not the candidate skill's "
                           "LESSONS.md" % (slug, change.get("file")))
        if (change.get("mode") != "append" or not isinstance(change.get("content"), str)
                or not isinstance(change.get("marker"), str)):
            return False, "unit %s: change.json is not an append of a text lesson" % slug
    if not isinstance(proposal.get("refused"), list):
        return False, "proposal.refused is not a list"
    return True, None


def _receipt_path(proposal_id):
    return Path(SLEEP_RECEIPTS_DIR) / (proposal_id + ".json")


@contextmanager
def _proposal_operation(body):
    """One writer per proposal, including separate server processes. No age expiry.

    Keep the lock file permanently so another opener cannot lock a new inode.
    The OS releases ownership on process exit; unrelated proposals stay independent.
    """
    proposal_dir = _resolve_proposal_dir(body)
    if not proposal_dir:
        yield False
        return
    Path(SLEEP_RECEIPTS_DIR).mkdir(parents=True, exist_ok=True)
    lock = _receipt_path(os.path.basename(proposal_dir)).with_suffix(".lock")
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o600)
    with os.fdopen(fd, "r+b", buffering=0) as handle:
        held = False
        try:
            if os.name == "nt":
                import msvcrt
                if not os.fstat(handle.fileno()).st_size:
                    handle.write(b"\0")
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            held = True
        except OSError:
            pass
        try:
            yield held
        finally:
            if held:
                if os.name == "nt":
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _operation_receipt_path(proposal_id):
    return _receipt_path(proposal_id).with_suffix(".operation.json")


def _artifact_hashes(proposal, proposal_dir):
    rels = ["proposal.json"]
    for unit in proposal.get("units") or []:
        for _key, name in _UNIT_FILES:
            rels.append("units/%s/%s" % (unit["slug"], name))
    return {rel: _sha256_file(os.path.join(proposal_dir, *rel.split("/"))) for rel in rels}


def _write_receipt(receipt):
    """Record the receipt ONCE (a proposal id is never re-receipted), atomically,
    under the shared write lock."""
    path = _receipt_path(receipt["proposal_id"])
    with _paths.WRITE_LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            raise FileExistsError("a receipt already exists for %s" % receipt["proposal_id"])
        _paths.atomic_write_text(path, json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return path


def _load_receipt(proposal_id):
    rec = _read_json(_receipt_path(proposal_id))
    if not isinstance(rec, dict) or rec.get("schema") != RECEIPT_SCHEMA:
        return None
    return rec


def _binding_block(receipt, **extra):
    """The honest Anchor-side metadata every response carries: WHAT was frozen,
    WHERE apply/rollback act (the private candidate), and that nothing is
    installed."""
    src = receipt.get("source") if isinstance(receipt.get("source"), dict) else {}
    cand = receipt.get("candidate") if isinstance(receipt.get("candidate"), dict) else {}
    block = {
        "schema": BINDING_SCHEMA,
        "proposalId": receipt.get("proposal_id"),
        "skill": receipt.get("skill"),
        "source": {"dir": src.get("dir"), "repo": src.get("repo"), "rel": src.get("rel"),
                   "head": src.get("head"), "mutated": False},
        "candidate": {"dir": cand.get("dir"), "baselineSha": receipt.get("baseline_sha"),
                      "privateClone": True},
        "applyTarget": "candidate-branch",
        "installed": False,
        "landing": ("apply commits on a branch of the private candidate clone only; the "
                    "installed skill repository is never modified here — improvements "
                    "land through the existing code jobs / review"),
    }
    block.update(extra)
    return block


def _refusal(verb, reason, status=409, **extra):
    """An Anchor-side refusal BEFORE the kernel runs — a valid record, never a
    fabricated kernel exit code."""
    payload = {"ok": False, "verb": verb, "outcome": "refused", "refused": True,
               "refusedBy": "anchor", "reason": reason, "error": reason,
               "kernelRan": False}
    payload.update(extra)
    return payload, status


def _bind_proposal(body, verb):
    """Re-bind a request's proposal to the server-owned receipt minted with it →
    ``(binding, None)`` or ``(None, (payload, status))``. Refuses a dir that is
    not a plain child of the runs dir, a missing receipt, ANY artifact hash
    mismatch, any structural deviation, and a stale/dirty/foreign candidate."""
    proposal_dir = _resolve_proposal_dir(body)
    if not proposal_dir:
        hint = (" (a bare baselineSha is not enough — the frozen baseline is read "
                "from the receipted proposal artifact)" if body.get("baselineSha") else "")
        return None, ({"error": "proposalId or proposalPath (a proposal minted into "
                       "the sleep-runs dir) required" + hint}, 400)
    if not os.path.isfile(os.path.join(proposal_dir, "proposal.json")):
        return None, ({"error": "no proposal.json in %s" % proposal_dir}, 404)
    proposal_id = os.path.basename(proposal_dir)
    receipt = _load_receipt(proposal_id)
    if receipt is None:
        return None, _refusal(verb, "no server-owned receipt for proposal %s — it was not "
                              "minted by this server (or predates the candidate boundary); "
                              "re-run propose" % proposal_id)
    if not _same(str(receipt.get("proposal_dir") or ""), proposal_dir):
        return None, _refusal(verb, "receipt identity mismatch for %s" % proposal_id)
    hashes = receipt.get("artifacts")
    if not isinstance(hashes, dict) or "proposal.json" not in hashes:
        return None, _refusal(verb, "receipt for %s carries no artifact hashes" % proposal_id)
    for rel, want in hashes.items():
        target = _plain_child(proposal_dir, *str(rel).split("/"))
        if target is None or not os.path.isfile(target):
            return None, _refusal(verb, "receipted artifact missing or not plain: %s" % rel)
        try:
            got = _sha256_file(target)
        except OSError:
            got = None
        if got != want:
            return None, _refusal(verb, "artifact %s differs from the receipted proposal "
                                  "(tampered or rewritten) — refusing" % rel)
    proposal = _read_json(os.path.join(proposal_dir, "proposal.json"))
    cand = receipt.get("candidate") if isinstance(receipt.get("candidate"), dict) else {}
    src = receipt.get("source") if isinstance(receipt.get("source"), dict) else {}
    expect = {"source_dir": str(src.get("dir") or ""),
              "candidate_dir": str(cand.get("dir") or ""),
              "candidate_skill_dir": str(cand.get("skill_dir") or ""),
              "baseline_sha": str(receipt.get("baseline_sha") or "")}
    if not all(expect.values()):
        return None, _refusal(verb, "receipt for %s is incomplete" % proposal_id)
    ok, reason = _validate_artifact(proposal, proposal_dir, expect)
    if not ok:
        return None, _refusal(verb, "proposal artifact failed re-validation: %s" % reason)
    allowed_head = expect["baseline_sha"]
    if verb == "rollback":
        last = _read_json(_operation_receipt_path(proposal_id)) or {}
        if last.get("outcome") == "applied" and _SHA_RE.fullmatch(str(last.get("head", ""))):
            allowed_head = last["head"]
    state = _candidate_state(expect["candidate_dir"], expect["baseline_sha"],
                             _real(SLEEP_CANDIDATES_DIR), allowed_head)
    if not state["ok"]:
        return None, _refusal(verb, state["reason"], candidateState=state,
                              anchor=_binding_block(receipt))
    return {"proposal_dir": proposal_dir, "proposal_id": proposal_id,
            "proposal": proposal, "receipt": receipt,
            "candidate_dir": expect["candidate_dir"],
            "baseline_sha": expect["baseline_sha"], "state": state}, None


def _kernel_outcome(run, verb, bound, ok_outcome):
    """Map a kernel run to ``(payload, status)`` HONESTLY: 200 only for exit 0 +
    ``ok`` + the verb's success outcome; ``refused`` → 409; ``blocked`` → 422;
    a spawn/parse failure, a timeout or any other non-zero exit → 500."""
    parsed = _parse_kernel_json(run["stdout"])
    anchor = _binding_block(bound["receipt"], kernelExit=run["status"],
                            kernelContained=bool(run.get("contained")))
    kernel_error = parsed.get("error") if isinstance(parsed, dict) else None
    if run["spawnError"] or run["timedOut"] or not isinstance(parsed, dict) or kernel_error:
        message = (kernel_error or run["spawnError"]
                   or "kernel %s exited %s%s" % (verb, run["status"],
                                                 " (timed out)" if run["timedOut"] else ""))
        return {"error": message, "stderr": run["stderr"], "ok": False, "verb": verb,
                "outcome": "error", "exitCode": run["status"],
                "timedOut": run["timedOut"], "anchor": anchor}, 500
    parsed["anchor"] = anchor
    outcome = parsed.get("outcome")
    if run["status"] == 0 and parsed.get("ok") is True and outcome == ok_outcome:
        return parsed, 200
    if outcome == "refused":
        return parsed, 409
    if outcome == "blocked":
        return parsed, 422
    parsed.setdefault("error", "kernel %s exited %s (outcome %s)"
                      % (verb, run["status"], outcome))
    return parsed, 500


# ── the three verbs ──────────────────────────────────────────────────────────

def sleep_propose(body):
    """POST /api/foundry/sleep_session/propose — kernel `propose` against a
    PRIVATE candidate clone of the manifest skill's owning repository.
    ``(payload, status_code)``; 200 ⇒ a receipted proposal whose
    ``baseline.repoDir`` IS the candidate (never the installed repo)."""
    skill = str(body.get("skill") or "gandalf").strip()
    if not _SKILL_NAME_RE.match(skill):
        return {"error": "invalid skill name: %s" % json.dumps(skill)}, 400
    entry, why = _manifest_entry_for(skill)
    if entry is None:
        return ({"error": "skill %s: %s (%s)" % (json.dumps(skill), why, MANIFEST_PATH)},
                400 if why.startswith("ambiguous") else 404)
    source, err = _bind_source(entry)
    if err:
        return err
    try:
        Path(SLEEP_RUNS_DIR).mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return {"error": "sleep-runs dir unavailable: %s" % exc}, 500
    runs_root = _real(SLEEP_RUNS_DIR)
    cand, err = _mint_candidate(source)
    if err:
        return err
    run = _run_kernel(["propose", cand["skill_dir"], "--corpus", source["dir"],
                       "--repo", cand["dir"], "--runs-dir", runs_root])
    parsed = _parse_kernel_json(run["stdout"])
    kernel_error = parsed.get("error") if isinstance(parsed, dict) else None
    if (not isinstance(parsed, dict) or kernel_error or run["status"] != 0
            or run["spawnError"]):
        _rmtree_force(cand["dir"])
        return {
            "error": kernel_error or run["spawnError"]
            or "kernel propose exited %s%s" % (run["status"],
                                               " (timed out)" if run["timedOut"] else ""),
            "stderr": run["stderr"], "exitCode": run["status"], "timedOut": run["timedOut"],
        }, 500
    raw_dir = parsed.get("proposalDir")
    proposal_dir = (_resolve_proposal_dir({"proposalPath": raw_dir})
                    if isinstance(raw_dir, str) else None)
    if not proposal_dir or not os.path.isfile(os.path.join(proposal_dir, "proposal.json")):
        _rmtree_force(cand["dir"])
        return {"error": "kernel wrote the proposal outside the sleep-runs dir: %r"
                % (raw_dir,)}, 500
    proposal = _read_json(os.path.join(proposal_dir, "proposal.json"))
    expect = {"source_dir": source["dir"], "candidate_dir": cand["dir"],
              "candidate_skill_dir": cand["skill_dir"], "baseline_sha": source["head"]}
    ok, reason = _validate_artifact(proposal, proposal_dir, expect)
    if not ok:
        _rmtree_force(cand["dir"])
        _rmtree_force(proposal_dir)
        return {"error": "kernel artifact failed validation: %s" % reason}, 500
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "proposal_id": os.path.basename(proposal_dir),
        "proposal_dir": proposal_dir,
        "created_ts": time.time(),
        "skill": {"ref": source["ref"], "name": source["name"], "source": source["source"]},
        "source": {"dir": source["dir"], "repo": source["repo"], "rel": source["rel"],
                   "head": source["head"]},
        "candidate": {"dir": cand["dir"], "skill_dir": cand["skill_dir"], "id": cand["id"]},
        "baseline_sha": source["head"],
        "artifacts": _artifact_hashes(proposal, proposal_dir),
        "confirm_token": CONFIRM_TOKEN,
    }
    try:
        _write_receipt(receipt)
    except (OSError, ValueError) as exc:
        _rmtree_force(cand["dir"])
        _rmtree_force(proposal_dir)
        return {"error": "receipt could not be recorded: %s" % exc}, 500
    # Enrich each unit with its REAL diff text (the artifact the kernel wrote).
    for unit in ((parsed.get("proposal") or {}).get("units") or []):
        diff_text = _read_text_safe(unit.get("diffPath"))
        if diff_text is not None:
            unit["diffText"] = diff_text
    parsed["anchor"] = _binding_block(receipt, kernelExit=run["status"],
                                      kernelContained=bool(run.get("contained")))
    return parsed, 200


def _sleep_apply_locked(body):
    """POST /api/foundry/sleep_session/apply — confirm-gated kernel `apply`,
    bound to the receipted proposal and run with ``--work-repo <candidate>``.
    200 ⇒ ``applied`` = committed on a branch of the PRIVATE candidate (nothing
    installed); ``refused`` → 409; ``blocked`` (the frozen gate regressed and
    the kernel auto-rolled the CANDIDATE back) → 422; spawn/parse/timeout → 500."""
    if body.get("confirm") is not True:
        return {"error": "refused: confirm must be exactly true — the human is "
                "the promotion authority", "outcome": "refused", "ok": False,
                "refused": True, "kernelRan": False}, 409
    bound, err = _bind_proposal(body, "apply")
    if err:
        return err
    args = ["apply", bound["proposal_dir"], "--confirm", CONFIRM_TOKEN,
            "--work-repo", bound["candidate_dir"]]
    unit = body.get("unit")
    if unit not in (None, ""):
        unit = str(unit)
        slugs = {u.get("slug") for u in (bound["proposal"].get("units") or [])
                 if isinstance(u, dict)}
        if not _SLUG_RE.match(unit) or unit not in slugs:
            return _refusal("apply", "no unit %r in this proposal" % unit,
                            anchor=_binding_block(bound["receipt"]))
        args += ["--unit", unit]
    run = _run_kernel(args)
    result, status = _kernel_outcome(run, "apply", bound, "applied")
    if status == 200:
        ok, _, head, _ = _git(bound["candidate_dir"], ["rev-parse", "HEAD"])
        if not ok or head.strip() != result.get("promotedCommit"):
            return _refusal("apply", "kernel success did not match candidate HEAD; preserving work", 500)
        _paths.atomic_write_text(_operation_receipt_path(bound["proposal_id"]),
                                 json.dumps({"outcome": "applied", "head": head.strip()}) + "\n")
    return result, status


def _sleep_rollback_locked(body):
    """POST /api/foundry/sleep_session/rollback — kernel `rollback` of the
    PRIVATE candidate to the frozen baseline (``--work-repo <candidate>``). A
    dirty or stale candidate is refused (409), never reset; ``restored`` → 200;
    a failed restore / spawn / timeout → 500."""
    bound, err = _bind_proposal(body, "rollback")
    if err:
        return err
    run = _run_kernel(["rollback", bound["proposal_dir"],
                       "--work-repo", bound["candidate_dir"]])
    result, status = _kernel_outcome(run, "rollback", bound, "restored")
    if status == 200:
        _paths.atomic_write_text(_operation_receipt_path(bound["proposal_id"]),
                                 json.dumps({"outcome": "restored", "head": bound["baseline_sha"]}) + "\n")
    return result, status


def _sleep_operation(body, verb, operation):
    if verb == "apply" and body.get("confirm") is not True:
        return _sleep_apply_locked(body)
    if not _resolve_proposal_dir(body):
        return {"error": "proposalId or proposalPath must name a plain proposal in the sleep-runs directory; "
                         "a bare baselineSha is not enough"}, 400
    try:
        with _proposal_operation(body) as held:
            if not held:
                return _refusal(verb, "proposal unavailable or another apply/rollback owns it")
            return operation(body)
    except OSError as exc:
        # A receipt write can fail AFTER the kernel changed its candidate.
        # Do not label that as a pre-launch refusal or invent a rolled-back state.
        return {"ok": False, "verb": verb, "outcome": "error", "kernelRan": None,
                "error": "proposal operation failed; inspect this original candidate: %s" % exc}, 500


def sleep_apply(body):
    return _sleep_operation(body, "apply", _sleep_apply_locked)


def sleep_rollback(body):
    return _sleep_operation(body, "rollback", _sleep_rollback_locked)


# ── static-file serving of the built React app (foundry-gui/dist) ────────────

DIST_DIR = (ANCHOR_DIR / "foundry-gui" / "dist").resolve()

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".svg": "image/svg+xml",
    ".json": "application/json; charset=utf-8",
    ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
    ".gif": "image/gif", ".ico": "image/x-icon", ".webp": "image/webp",
    ".woff": "font/woff", ".woff2": "font/woff2", ".ttf": "font/ttf",
    ".map": "application/json; charset=utf-8", ".txt": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
}


def resolve_dist_file(rel_path):
    """Traversal-safe resolve of a dist-relative path → (abs_path, content_type)
    or (None, None). ``rel_path`` is the URL path (e.g. "/assets/x.js" or
    "index.html"); it must stay inside DIST_DIR."""
    rel = (rel_path or "").split("?", 1)[0].lstrip("/")
    if not rel:
        rel = "index.html"
    try:
        resolved = (DIST_DIR / rel).resolve()
    except (OSError, ValueError):
        return None, None
    if resolved != DIST_DIR and DIST_DIR not in resolved.parents:
        return None, None
    if not resolved.is_file():
        return None, None
    ctype = _CONTENT_TYPES.get(resolved.suffix.lower(), "application/octet-stream")
    return resolved, ctype
