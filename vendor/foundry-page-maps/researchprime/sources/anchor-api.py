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
"""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import paths as _paths

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
#: The git repo whose HEAD is the FROZEN baseline (apply branches off it).
SKILLS_REPO = os.environ.get("FOUNDRY_SKILLS_REPO") or str(Path(SKILLS_ROOT).parent)
#: Where proposal artifacts land (one dir per run) — matches server.mjs' default.
SLEEP_RUNS_DIR = Path(os.environ.get("FOUNDRY_SLEEP_RUNS")
                      or (ANCHOR_DIR / "foundry-gui" / "sleep-runs"))
KERNEL_TIMEOUT_S = int(os.environ.get("FOUNDRY_KERNEL_TIMEOUT_MS") or "180000") / 1000.0


def _node_cmd() -> str:
    """The node executable (FOUNDRY_NODE override, else `node` on PATH)."""
    return os.environ.get("FOUNDRY_NODE") or shutil.which("node") or "node"


# ── safe fs helpers (a missing file is an honest empty, never a crash) ────────

def _read_text_safe(file_path) -> str:
    try:
        return Path(file_path).read_text(encoding="utf-8")
    except OSError:
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

def _resolve_source(source):
    """Resolve a manifest ``source`` to an absolute directory."""
    if not source:
        return None
    if re.match(r"^[A-Za-z]:[\\/]", source):
        return source
    return os.path.join(FOUNDRY_ROOT, source)


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
        text = _read_text_safe(file_path) or ""
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
            + (" (at least one proposal applied on a branch)."
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

def _run_kernel(args):
    """Spawn ``node <KERNEL_CLI> <verb> <args…>`` headlessly. Never raises —
    returns ``{status, spawnError, timedOut, stdout, stderr}`` so the caller can
    surface the kernel's honest exit codes (0 ok / 3 refused / 1 blocked)."""
    try:
        proc = subprocess.run(
            [_node_cmd(), KERNEL_CLI, *args],
            cwd=KERNEL_DIR,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=KERNEL_TIMEOUT_S,
        )
        return {"status": proc.returncode, "spawnError": None,
                "timedOut": False, "stdout": proc.stdout or "",
                "stderr": proc.stderr or ""}
    except subprocess.TimeoutExpired as exc:
        return {"status": None, "spawnError": None, "timedOut": True,
                "stdout": exc.stdout or "", "stderr": exc.stderr or ""}
    except (OSError, ValueError) as exc:
        return {"status": None, "spawnError": str(exc), "timedOut": False,
                "stdout": "", "stderr": ""}


def _parse_kernel_json(stdout):
    text = (stdout or "").strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _resolve_proposal_dir(body):
    """Resolve the proposal dir from ``{proposalPath | proposalId}``; the result
    MUST live inside SLEEP_RUNS_DIR (every proposal this server mints does) — a
    path outside it is refused (None)."""
    candidate = None
    if isinstance(body.get("proposalPath"), str) and body["proposalPath"].strip():
        candidate = os.path.abspath(body["proposalPath"].strip())
    elif isinstance(body.get("proposalId"), str) and body["proposalId"].strip():
        candidate = os.path.join(str(SLEEP_RUNS_DIR),
                                 os.path.basename(body["proposalId"].strip()))
    if not candidate:
        return None
    runs_root = os.path.abspath(str(SLEEP_RUNS_DIR))
    normalized = os.path.abspath(candidate)
    if normalized != runs_root and not normalized.startswith(runs_root + os.sep):
        return None
    return normalized


_SKILL_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def sleep_propose(body):
    """POST /api/foundry/sleep_session/propose — spawn the kernel `propose`.
    Returns ``(payload, status_code)``."""
    skill = str(body.get("skill") or "gandalf").strip()
    if not _SKILL_NAME_RE.match(skill):
        return {"error": f"invalid skill name: {json.dumps(skill)}"}, 400
    skill_dir = os.path.join(SKILLS_ROOT, skill)
    if not (_stat_safe(skill_dir) and os.path.isdir(skill_dir)):
        return {"error": f"skill directory not found: {skill_dir}"}, 404
    os.makedirs(SLEEP_RUNS_DIR, exist_ok=True)
    run = _run_kernel(["propose", skill_dir, "--repo", SKILLS_REPO,
                       "--runs-dir", str(SLEEP_RUNS_DIR)])
    parsed = _parse_kernel_json(run["stdout"])
    if not parsed or parsed.get("error") or run["status"] != 0 or run["spawnError"]:
        return {
            "error": (parsed and parsed.get("error")) or run["spawnError"]
            or f"kernel propose exited {run['status']}"
            + (" (timed out)" if run["timedOut"] else ""),
            "stderr": run["stderr"],
        }, 500
    # Enrich each unit with its REAL diff text (the artifact the kernel wrote).
    for unit in ((parsed.get("proposal") or {}).get("units") or []):
        diff_text = _read_text_safe(unit.get("diffPath"))
        if diff_text is not None:
            unit["diffText"] = diff_text
    return parsed, 200


def sleep_apply(body):
    """POST /api/foundry/sleep_session/apply — confirm-gated kernel `apply`."""
    if body.get("confirm") is not True:
        return {"error": "refused: confirm must be exactly true — the human is "
                "the promotion authority", "outcome": "refused"}, 409
    proposal_dir = _resolve_proposal_dir(body)
    if not proposal_dir:
        return {"error": "proposalId or proposalPath (inside the sleep-runs dir) required"}, 400
    if not _stat_safe(os.path.join(proposal_dir, "proposal.json")):
        return {"error": f"no proposal.json in {proposal_dir}"}, 404
    args = ["apply", proposal_dir, "--confirm", "foundry-gui-user"]
    if body.get("unit"):
        args += ["--unit", str(body["unit"])]
    run = _run_kernel(args)
    parsed = _parse_kernel_json(run["stdout"])
    if not parsed or parsed.get("error") or run["spawnError"]:
        return {
            "error": (parsed and parsed.get("error")) or run["spawnError"]
            or f"kernel apply exited {run['status']}"
            + (" (timed out)" if run["timedOut"] else ""),
            "stderr": run["stderr"],
        }, 500
    return parsed, (409 if parsed.get("outcome") == "refused" else 200)


def sleep_rollback(body):
    """POST /api/foundry/sleep_session/rollback — kernel `rollback`."""
    proposal_dir = _resolve_proposal_dir(body)
    if not proposal_dir:
        hint = (" (a bare baselineSha is not enough — the kernel reads the "
                "frozen baseline from the proposal artifact)"
                if body.get("baselineSha") else "")
        return {"error": "proposalId or proposalPath (inside the sleep-runs "
                f"dir) required{hint}"}, 400
    if not _stat_safe(os.path.join(proposal_dir, "proposal.json")):
        return {"error": f"no proposal.json in {proposal_dir}"}, 404
    run = _run_kernel(["rollback", proposal_dir])
    parsed = _parse_kernel_json(run["stdout"])
    if not parsed or parsed.get("error") or run["spawnError"]:
        return {
            "error": (parsed and parsed.get("error")) or run["spawnError"]
            or f"kernel rollback exited {run['status']}"
            + (" (timed out)" if run["timedOut"] else ""),
            "stderr": run["stderr"],
        }, 500
    return parsed, 200


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
