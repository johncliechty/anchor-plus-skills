"""Foundry tools in every steward's and coder's standing rules (John 2026-10-12: "Why do we use commands that take
minutes, when there are options that take just seconds?").

The tools live in Skill Foundry (`foundry-tools/`, single source, like the skills); their INDEX.json is read each
time an engine's rules are built, so a tool added there reaches every steward and job with no Anchor change. A
missing or unreadable index falls back to the one tool Anchor itself carries (the reading copy)."""
import json
import os
from pathlib import Path

DEFAULT_INDEX = Path("C:/dev/Skill Foundry/foundry-tools/INDEX.json")
MAX_TOOLS = 30
_cache = {"key": None, "rows": None}

FALLBACK = (
    "A PDF or HTML reading copy is ONE command that takes seconds - `python C:/dev/Anchor/tools/reading_copy.py "
    "<document.md> [--html]` - never write or commission a renderer. "
)


def index_path():
    return Path(os.environ.get("ANCHOR_FOUNDRY_TOOLS_INDEX") or DEFAULT_INDEX)


def _clean(value, limit):
    text = " ".join(str(value or "").split())
    return text[:limit]


def tools():
    """The indexed tools as (name, purpose, command) rows; [] when the index cannot be read."""
    p = index_path()
    try:
        st = p.stat()
        key = (str(p), st.st_mtime_ns, st.st_size)
        if _cache["key"] == key:
            return _cache["rows"]
        raw = json.loads(p.read_text(encoding="utf-8"))
        rows = []
        for t in raw.get("tools") or []:
            if not isinstance(t, dict):
                continue
            name, purpose, command = (_clean(t.get("name"), 40), _clean(t.get("purpose"), 160),
                                      _clean(t.get("command"), 220))
            if name and purpose and command:
                rows.append((name, purpose, command))
        rows = rows[:MAX_TOOLS]
        _cache.update(key=key, rows=rows)
        return rows
    except (OSError, ValueError, AttributeError, TypeError):
        return []


FOUNDRY_SKILLS_SUMMARY = (
    "FOUNDRY SKILLS (`C:/dev/Skill Foundry/skills/<name>/SKILL.md` & `C:/dev/trio/<name>/SKILL.md`) - ALWAYS check "
    "these before building custom scripts or workflows: `anvil` (programmatic code comprehension, Orange-Split, "
    "LibCST remap & paper-to-software math verification via `python -m steward_cockpit.anvil_session`), `legal-beagle` (contract/trust redlines & compliance), "
    "`financial-analyst` (penny-exact Decimal + Excel/Python deal & waterfall models), `figure-designer` "
    "(scientific/technical figures), `einstein` (course & lecture packs), `chekhov` (story memory), `ramanujan` "
    "(certified math), `literature-review` (PRISMA snowball review), `gandalf` (deep-think critique), `superjump` / "
    "`jumper` (structured ideation), `tidy-idy` (folder hygiene), `zombie-hunter` (orphan reaper), "
    "`researchPrime` / `crucible` / `foreman` (trio). "
    "TASK CHALLENGE TRIAGE & CONTEXT SIZING (Cockpit Steward Law): judge every task's challenge before acting — "
    "(1) INSTANT CHORE (<30s): run the matching `ft.py` tool (`reading-copy`, `pdf-pages`, `docx-redline`, "
    "`pptx-pdf-verify`, `chrome-open`, `cst-rewrite`) directly in-turn; "
    "(2) SMALL BOUNDED JOB (`--size small`): <=5 files, reversible, no new architecture/math decision (auto-escalates "
    "via `--size standard --escalates <id>` on miss); "
    "(3) HARD / ARCHITECTURAL / DOMAIN-SKILL WORK (`--size standard` at Frontier Max/Ultra/XHigh): route to the "
    "specialized Foundry/Trio skill (`anvil`, `foreman`, `crucible`, `researchPrime`, `gandalf`, `einstein`, "
    "`ramanujan`) with a tight, self-contained brief (<=8,000 chars: objective, exact repo-relative paths, pre-tested "
    "`--check` command, and explicit `--output` paths — never dump raw conversation transcripts). "
)


def block(steward=True):
    """The FOUNDRY TOOLS paragraph for an engine's standing rules."""
    rows = tools()
    if not rows:
        return FALLBACK + FOUNDRY_SKILLS_SUMMARY
    lines = "".join("\n  - %s: %s - `%s`" % r for r in rows)
    tail = ("When you or a job keep doing a chore by hand that no tool covers, or a job's speed line says it wrote "
            "helpers by hand, propose a tool: `python C:/dev/foundry-tools/ft.py propose <name> --why \"<what was done "
            "by hand, how long, where>\"` and tell John in one line. " if steward else
            "If a chore you needed has no tool, say so in one line of your final summary instead of building a "
            "general-purpose helper. ")
    return ("FOUNDRY TOOLS - one fast standard command per chore (seconds, not minutes). ALWAYS check and run these "
            "existing tools first; NEVER write your own custom Python helper for `.docx` inspection/redlining "
            "(`docx-redline`), `.pptx` PDF conversion (`pptx-pdf-verify`), opening HTML mockups in Chrome "
            "(`chrome-open`), Markdown-to-PDF (`reading-copy`), PDF inspection (`pdf-pages`), or AST rewriting "
            "(`cst-rewrite`):" + lines + "\n" + FOUNDRY_SKILLS_SUMMARY + tail)

