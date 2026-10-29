"""The fence's PreToolUse guard (W1a, ChatGPT reviews of 2026-10-08): a Claude Code hook that runs BEFORE a tool, so a
refused call never happens. Stdlib only; any doubt refuses (never open on an error).

  - A fenced steward's shell (ANCHOR_FENCE_SHELL=1): the allow list admits the two hand-off tools and read-only git by
    PREFIX, and a prefix admits `git diff --output=...`, a redirection, or a quoting trick. This guard admits a command
    only when it parses under a POSITIVE grammar - words of plain characters, '...' (literal), and "..." with nothing
    the shell would expand ($, backtick, backslash) - with no operator anywhere; git takes plain words only, never an
    option that writes a file or runs a program.
  - A code job's coder (ANCHOR_FENCE_ROOT=<its worktree>): its file tools write only inside the worktree, and its shell
    never names the running Anchor (ANCHOR_FENCE_SERVED) or climbs out with `..` - the worktree is far from the running
    checkout, so reaching it needs one of those.

Protocol: the tool call arrives as JSON on stdin; exit 0 allows it, exit 2 refuses it with the reason on stderr (the
model reads it).
"""
import json
import os
import re
import sys

SHELL_TOOLS = {"Bash", "PowerShell"}
FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
BARE = re.compile(r"[A-Za-z0-9_./:@=,+%^~-]+")
GIT_ARG = re.compile(r"^(?:--output(?:=.*)?|-o.*|--output-directory.*|--ext-diff|--textconv|--exec(?:=.*)?|"
                     r"--upload-pack.*|--receive-pack.*|-c|--config-env.*|--no-index)$")
ALLOWED = (
    ("tool", re.compile(r"^python(?:\.exe)?$", re.I), re.compile(r"^(?:[A-Za-z]:/[^\"'\s]+/)?Anchor/tools/steward_(?:code_job|skill|settings)\.py$", re.I)),
    ("foundry_tool", re.compile(r"^python(?:\.exe)?$", re.I), re.compile(r"^(?:[A-Za-z]:/[^\"'\s]+/)?(?:Skill Foundry/|Anchor/vendor/)?foundry-tools/ft\.py$", re.I)),
    ("git", re.compile(r"^git$"), re.compile(r"^(?:status|log|diff|show)$")),
)


def tokens(cmd):
    """[(text, quoted)] under the positive grammar, or None when the command holds anything else (an operator, a
    redirection, an expansion, an escape, an unclosed quote)."""
    out, i, n = [], 0, len(cmd)
    while i < n:
        c = cmd[i]
        if c in " \t":
            i += 1
            continue
        if c == "'":
            j = cmd.find("'", i + 1)
            if j < 0:
                return None
            out.append((cmd[i + 1:j], True))
            i = j + 1
        elif c == '"':
            j = cmd.find('"', i + 1)
            if j < 0:
                return None
            body = cmd[i + 1:j]
            if any(x in body for x in ("$", "`")) or body.endswith("\\"):
                return None
            out.append((body, True))
            i = j + 1
        else:
            m = BARE.match(cmd, i)
            if not m:
                return None
            out.append((m.group(0), False))
            i = m.end()
        if i < n and cmd[i] not in " \t":      # a word glued to a quote ('a'"b"x) is not in the grammar
            return None
    return out


def refuse(why):
    log = os.environ.get("ANCHOR_FENCE_LOG")
    if log:     # the proof's witness that the hook itself refused (not the model declining)
        try:
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(why + "\n")
        except OSError:
            pass
    sys.stderr.write("REFUSED by the fence: %s\n" % why)
    sys.exit(2)


def inside(path, root):
    try:
        p = os.path.normcase(os.path.realpath(path))
        r = os.path.normcase(os.path.realpath(root))
        return p == r or p.startswith(r.rstrip("\\/") + os.sep)
    except Exception:
        return False


def served_spellings():
    served = os.environ.get("ANCHOR_FENCE_SERVED") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    s = served.replace("\\", "/").rstrip("/").lower()
    out = {s}
    if len(s) > 2 and s[1] == ":":
        out.add("/" + s[0] + s[2:])                       # Git Bash: /c/dev/anchor
        out.add(s[2:])                                    # /dev/anchor from a drive's root
    return out


def check_steward_shell(cmd):
    toks = tokens(cmd)
    if toks is None:
        refuse("only plain words and simple quotes run here - no operator, redirection, expansion or escape")
    if not toks:
        refuse("an empty command")
    for kind, prog, first in ALLOWED:
        if len(toks) >= 2 and not toks[0][1] and prog.match(toks[0][0]) and not toks[1][1] and first.match(toks[1][0]):
            if kind == "git":
                rest = toks[2:]
                if any(q for _, q in rest):
                    refuse("git takes plain words here")
                if any(GIT_ARG.match(w) for w, _ in rest):
                    refuse("that git option writes a file or runs a program")
            return
    refuse("only the two hand-off tools and read-only git run here")


def check_coder_shell(cmd):
    flat = cmd.replace("\\", "/").lower()
    for s in served_spellings():
        if re.search(re.escape(s) + r"(?:/|[\"'\s]|$)", flat):
            refuse("a code job works only in its own worktree - its shell never names the running Anchor (%s)" % s)
    if re.search(r"(?:^|[/\s\"'=])\.\.(?:/|[\s\"']|$)", flat):
        refuse("a code job works only in its own worktree - no `..` out of it")


def main():
    try:
        call = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        refuse("the tool call could not be read")
    tool = str(call.get("tool_name") or "")
    inp = call.get("tool_input") or {}
    root = os.environ.get("ANCHOR_FENCE_ROOT", "")
    if tool in FILE_TOOLS and root:
        cwd = str(call.get("cwd") or os.getcwd())
        raw = str(inp.get("file_path") or inp.get("notebook_path") or "")
        path = raw if os.path.isabs(raw) else os.path.join(cwd, raw)
        if not raw or not inside(path, root):
            refuse("a code job writes only inside its own worktree (%s); %s is outside" % (root, raw or "(no path)"))
    if tool in SHELL_TOOLS:
        cmd = str(inp.get("command") or "").strip()
        if os.environ.get("ANCHOR_FENCE_SHELL") == "1":
            check_steward_shell(cmd)
        if root:
            check_coder_shell(cmd)
    sys.exit(0)


if __name__ == "__main__":
    main()
