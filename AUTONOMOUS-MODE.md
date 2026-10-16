# Autonomous mode — running the skills unattended

By default your agent asks before it acts. That is the right setting while you
are learning what these skills do.

Once you want them to actually *work* — a Foreman build that runs for an hour, a
researchPrime investigation that reads the web, a Crucible planning run with
three adversarial reviewers — the prompting becomes the bottleneck. A single
Foreman wave can touch dozens of files and run the test suite several times. If
you approve each step, the run cannot proceed while you are away, which defeats
the point.

**This is the configuration the author runs.** Below is exactly what it changes.

---

## How to turn it on

**The change goes in your own user-level config.** Not a file in this repo —
yours, under `%USERPROFILE%\.claude\`.

> **Why yours and not one we ship.** Agents deliberately restrict what a
> settings file arriving *inside a cloned repository* is allowed to grant —
> otherwise any repo you cloned could silently authorize itself to run commands
> on your machine. That restriction is correct and we are not going to work
> around it. A permission you grant in your own user-level file is unambiguous,
> and it is the only path we can promise actually works.

### Option 1 — one command (recommended)

From the package root, after reading this file:

```text
python share_agent_rules.py install --settings
```

This does two things, both to YOUR files, both reversible:

1. **Rules** — appends one clearly-fenced block to
   `%USERPROFILE%\.claude\CLAUDE.md` telling your agent to follow this
   install's `AGENTS.md` (the 10-minute status table, the background-launch
   pattern, no sub-agent shell spawns, honest degradation).
2. **Settings** — merges the block below into
   `%USERPROFILE%\.claude\settings.json`. It **never overwrites a value you
   already set** — it only fills absent keys and adds missing list entries —
   and your pre-merge file is kept at `settings.json.anchor-orig`.

Want the rules without the autonomy grant? Drop the flag:
`python share_agent_rules.py install`. Undo the rules block any time with
`python share_agent_rules.py remove`; check state with
`python share_agent_rules.py status`.

### Option 2 — by hand

Merge this into `%USERPROFILE%\.claude\settings.json` (keep any keys you
already have):

```json
{
  "permissions": {
    "defaultMode": "auto",
    "allow": [
      "Read", "Glob", "Grep",
      "Edit", "Write",
      "WebSearch", "WebFetch",
      "Bash"
    ],
    "deny": [
      "Read(**/.env)",
      "Read(**/.ssh/**)",
      "Read(**/id_rsa*)",
      "Read(**/credentials*)"
    ]
  },
  "skipAutoPermissionPrompt": true
}
```

Restart your agent session.

**Verify it took.** Open a session in this folder and ask it to run
`python doctor.py`. If it runs without asking, you are in autonomous mode.

**To undo it:** remove the `permissions` and `skipAutoPermissionPrompt` keys you
added, and restart. Nothing else in the bundle depends on them.

---

## What each capability is for

| Capability | Why the skills need it |
|---|---|
| `Bash` | Foreman runs your project's real test suite as its ground-truth gate, every wave. Crucible and Gandalf spawn their engines as Node processes. |
| `Write` / `Edit` | Foreman's whole job is writing code. Crucible writes plan documents. Every skill writes its journal. |
| `WebSearch` / `WebFetch` | researchPrime and Literature-Review are worthless without them — reading sources you did not supply is the entire skill. |
| `skipAutoPermissionPrompt` | Stops a run you started before stepping away from stalling on its first tool call. |

The `deny` list above blocks reads of `.env`, `.ssh/`, `id_rsa*`, and
`credentials*` — the places where an agent mistake leaks a secret rather than
just costing you a `git reset`. Keep it. Add to it freely; it is a plain JSON
array.

---

## Read this before you turn it on

**This is a real grant of authority on your machine.** An agent running this way
can modify and delete files, run arbitrary shell commands, and make outbound
network requests without asking. That is not a hedge — it is the literal
capability set, and it is the same one the author runs with.

1. **Scope it to a folder you can afford to lose.** Point the skills at a git
   repository with a clean working tree and a remote, so any damage is one
   `git reset --hard` away. Never at your only copy of anything.
2. **Nothing starts on its own.** The multi-agent skills (researchPrime /
   Crucible / Foreman / Gandalf) run only when you invoke them. Autonomous mode
   changes what they may do *once running* — not whether they start. Anchor's
   background auto-summaries stay off on shared installs.
3. **A long run should be talking to you.** Invoke a skill, get silence for
   twenty minutes, and something is wrong — see the 10-minute rule in
   `AGENTS.md`. Working correctly, a long run posts a status table roughly every
   ten minutes without being asked.

**No warranty.** This software is provided as-is. Enabling autonomous mode is
your decision, and the consequences on your machine are yours.

---

## Note for the two-package split

If you installed **Package A** (skills only, no Anchor dashboard), also read the
"Where the seats come from" note in `AGENTS.md` — without Anchor there is no
model-preference registry, so either create `~/.anchor/model_prefs.json` or
expect the skills to stamp `cross_model: false` and cap their confidence
accordingly. That stamp is correct behavior, not a bug.
