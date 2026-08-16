"""share_agent_rules.py — OPT-IN install of the bundle's agent-level rules.

The v1.2.3 problem this solves: the bundle ships its run contract (AGENTS.md —
the 10-minute status table, the background-launch pattern, no sub-agent shell
spawns, honest degradation) and an autonomy profile (AUTONOMOUS-MODE.md), but a
settings/rules file that merely SITS IN A CLONED REPO cannot grant itself
authority — agents deliberately restrict that, and the restriction is correct
(cross-family verified 2026-08-15). The legitimate path is the collaborator's
OWN user-level config, written by a program they deliberately ran, with an
explicit yes.

This module is that program. One command, two independent opt-ins:

    python share_agent_rules.py install            # rules pointer only
    python share_agent_rules.py install --settings # + autonomy permissions
    python share_agent_rules.py remove             # undo both
    python share_agent_rules.py status             # what is installed

What each opt-in writes, exactly:

* RULES — appends one sentinel-fenced block to ``%USERPROFILE%/.claude/CLAUDE.md``
  telling the agent to follow THIS install's ``AGENTS.md`` when running the
  bundled skills. Idempotent (re-run replaces the block in place; a moved
  install root heals on re-run) and reversible (``remove`` deletes exactly the
  fenced block, nothing else).

* SETTINGS — merges the autonomy profile into
  ``%USERPROFILE%/.claude/settings.json``: ``permissions.defaultMode="auto"``,
  ``skipAutoPermissionPrompt=true``, the allow list the skills genuinely need
  (Bash / Edit / Write / WebSearch / WebFetch), and a deny list guarding
  secrets (.env, .ssh, id_rsa*, credentials*). NEVER overwrites an existing
  scalar the user already set; only fills absent keys and unions the lists.
  The pre-merge file is backed up once to ``settings.json.anchor-orig`` (first
  backup wins — it stays the true original across re-runs).

Money/consent posture (matches the bundle): nothing here runs unless invoked,
both writes require the explicit subcommand, and ``remove`` restores the rules
file exactly. Stdlib only.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

RULES_BEGIN = "<!-- anchor-plus-skills:agent-rules:BEGIN (managed; edit via share_agent_rules.py) -->"
RULES_END = "<!-- anchor-plus-skills:agent-rules:END -->"

#: Marker file name for the first-backup-wins settings backup.
SETTINGS_BACKUP_NAME = "settings.json.anchor-orig"


# ── locations ────────────────────────────────────────────────────────────────

def package_root() -> Path:
    """The install root — the folder this module ships in."""
    return Path(__file__).resolve().parent


def claude_home(home: Path | None = None) -> Path:
    base = Path(home) if home is not None else Path.home()
    return base / ".claude"


def user_claude_md(home: Path | None = None) -> Path:
    return claude_home(home) / "CLAUDE.md"


def user_settings_json(home: Path | None = None) -> Path:
    return claude_home(home) / "settings.json"


# ── the rules block ──────────────────────────────────────────────────────────

def rules_block(root: Path | None = None) -> str:
    """The sentinel-fenced block appended to the user's global CLAUDE.md."""
    root = Path(root) if root is not None else package_root()
    agents = root / "AGENTS.md"
    return "\n".join([
        RULES_BEGIN,
        "# Anchor bundled skills — run contract",
        "",
        "When running any skill installed from the anchor-plus-skills bundle",
        "(researchPrime, Crucible, Foreman, Gandalf, Jumper, Ramanujan,",
        "Legal-Beagle, Literature-Review, Financial-Analyst, Tidy-Idy,",
        "Zombie-Hunter, Ecgberht), follow the run contract in:",
        "",
        f"    {agents}",
        "",
        "Non-negotiables from that contract:",
        "- Long runs report the 10-minute Status table, unprompted, until done.",
        "  Launch engines in the BACKGROUND and arm the ~600s wake-up AT LAUNCH —",
        "  a blocking foreground launch cannot report and reads as a hang.",
        "- Sub-agents never spawn shells (Read/Grep/Glob only).",
        "- No silent degradation: a leg that could not run is stamped, never",
        "  quietly approximated. `cross_model:false` on a one-family host is",
        "  correct behavior, not an error.",
        RULES_END,
        "",
    ])


def install_rules(home: Path | None = None, root: Path | None = None) -> dict:
    """Append or replace the fenced rules block. Returns an honest report."""
    target = user_claude_md(home)
    target.parent.mkdir(parents=True, exist_ok=True)
    block = rules_block(root)
    prior = target.read_text(encoding="utf-8") if target.is_file() else ""
    replaced = RULES_BEGIN in prior and RULES_END in prior
    if replaced:
        head = prior.split(RULES_BEGIN, 1)[0]
        tail = prior.split(RULES_END, 1)[1].lstrip("\r\n")
        merged = head + block + tail
    else:
        sep = "" if (not prior or prior.endswith("\n\n")) else (
            "\n" if prior.endswith("\n") else "\n\n")
        merged = prior + sep + block
    target.write_text(merged, encoding="utf-8")
    return {"ok": True, "action": "replaced" if replaced else "appended",
            "path": str(target)}


def remove_rules(home: Path | None = None) -> dict:
    """Delete exactly the fenced block. Honest no-op when absent."""
    target = user_claude_md(home)
    if not target.is_file():
        return {"ok": True, "action": "absent", "path": str(target)}
    text = target.read_text(encoding="utf-8")
    if RULES_BEGIN not in text or RULES_END not in text:
        return {"ok": True, "action": "absent", "path": str(target)}
    head = text.split(RULES_BEGIN, 1)[0]
    tail = text.split(RULES_END, 1)[1].lstrip("\r\n")
    target.write_text(head.rstrip("\r\n ") + ("\n" if head.strip() else "")
                      + tail, encoding="utf-8")
    return {"ok": True, "action": "removed", "path": str(target)}


# ── the settings merge ───────────────────────────────────────────────────────

def autonomy_patch() -> dict:
    """The autonomy profile (AUTONOMOUS-MODE.md, kept in lockstep by test)."""
    return {
        "permissions": {
            "defaultMode": "auto",
            "allow": [
                "Read", "Glob", "Grep",
                "Edit", "Write",
                "WebSearch", "WebFetch",
                "Bash",
            ],
            "deny": [
                "Read(**/.env)",
                "Read(**/.ssh/**)",
                "Read(**/id_rsa*)",
                "Read(**/credentials*)",
            ],
        },
        "skipAutoPermissionPrompt": True,
    }


def merge_settings(home: Path | None = None) -> dict:
    """Merge the autonomy profile into the USER'S settings.json.

    Fill-only for scalars (an existing user value always wins), set-union for
    the allow/deny lists, first-backup-wins ``settings.json.anchor-orig``.
    Refuses (honestly, no partial write) on unparseable JSON.
    """
    path = user_settings_json(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    current: dict = {}
    if path.is_file():
        try:
            current = json.loads(path.read_text(encoding="utf-8") or "{}")
        except ValueError as exc:
            return {"ok": False, "action": "refused-unparseable",
                    "path": str(path), "error": str(exc)[:120]}
        if not isinstance(current, dict):
            return {"ok": False, "action": "refused-not-an-object",
                    "path": str(path)}
        backup = path.with_name(SETTINGS_BACKUP_NAME)
        if not backup.exists():
            backup.write_text(path.read_text(encoding="utf-8"),
                              encoding="utf-8")

    patch = autonomy_patch()
    changed: list[str] = []

    perms = current.setdefault("permissions", {})
    if not isinstance(perms, dict):
        return {"ok": False, "action": "refused-permissions-not-an-object",
                "path": str(path)}
    if "defaultMode" not in perms:
        perms["defaultMode"] = patch["permissions"]["defaultMode"]
        changed.append("permissions.defaultMode")
    for key in ("allow", "deny"):
        have = perms.get(key) or []
        if not isinstance(have, list):
            return {"ok": False, "action": f"refused-{key}-not-a-list",
                    "path": str(path)}
        added = [e for e in patch["permissions"][key] if e not in have]
        if added:
            perms[key] = have + added
            changed.append(f"permissions.{key}(+{len(added)})")
    if "skipAutoPermissionPrompt" not in current:
        current["skipAutoPermissionPrompt"] = patch["skipAutoPermissionPrompt"]
        changed.append("skipAutoPermissionPrompt")

    path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
    return {"ok": True, "action": "merged" if changed else "already-present",
            "changed": changed, "path": str(path),
            "backup": str(path.with_name(SETTINGS_BACKUP_NAME))}


def status(home: Path | None = None) -> dict:
    """Read-only: what is currently installed."""
    md = user_claude_md(home)
    rules = md.is_file() and RULES_BEGIN in md.read_text(encoding="utf-8")
    sj = user_settings_json(home)
    settings_present = False
    default_mode = None
    if sj.is_file():
        try:
            doc = json.loads(sj.read_text(encoding="utf-8") or "{}")
            perms = doc.get("permissions") or {}
            allow = perms.get("allow") or []
            default_mode = perms.get("defaultMode")
            # Present == what the merge GUARANTEES. defaultMode is deliberately
            # NOT part of this predicate: the merge is fill-only, so a user's
            # own mode (e.g. "plan") wins — demanding "auto" here would tell
            # that user the profile is absent forever. Their mode is reported
            # separately instead.
            settings_present = (
                doc.get("skipAutoPermissionPrompt") is True
                and all(e in allow
                        for e in autonomy_patch()["permissions"]["allow"]))
        except ValueError:
            pass
    return {"rules_installed": bool(rules),
            "autonomy_settings_present": settings_present,
            "default_mode": default_mode,
            "claude_md": str(md), "settings_json": str(sj)}


# ── CLI ──────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "status"
    if cmd == "install":
        rep = install_rules()
        print("rules: %s -> %s" % (rep["action"], rep["path"]))
        if "--settings" in args:
            srep = merge_settings()
            if srep["ok"]:
                print("settings: %s (%s) -> %s" % (
                    srep["action"], ", ".join(srep.get("changed") or ["nothing new"]),
                    srep["path"]))
                print("original kept at: %s" % srep.get("backup", "(no prior file)"))
            else:
                print("settings: REFUSED (%s) — nothing written" % srep["action"])
                return 1
        else:
            print("(settings untouched — add --settings for the autonomy "
                  "profile; read AUTONOMOUS-MODE.md first)")
        print("restart your agent session to pick this up")
        return 0
    if cmd == "remove":
        rep = remove_rules()
        print("rules: %s" % rep["action"])
        print("settings are NOT auto-reverted; your pre-merge original is at "
              "%s if you want it back" % SETTINGS_BACKUP_NAME)
        return 0
    if cmd == "status":
        for k, v in status().items():
            print("%s: %s" % (k, v))
        return 0
    print("usage: python share_agent_rules.py "
          "[install [--settings] | remove | status]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
