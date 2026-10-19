# Paste-ready collaborator note — v1.2.4

> Send after the v1.2.4 tag is published to `anchor-plus-skills` (until then
> the clone URL serves v1.1.3 and the rules command below does not exist).

---

Subject: Anchor + the skill suite, v1.2.4 — 15 minutes to a working install

Hi [name],

Here's the current drop of my R&D dashboard plus the full Claude Code skill
suite — 14 skills now, including the research/plan/build trio and the
Ecgberht project steward. You'll need Windows 10/11 and git; no GitHub
account, no admin rights, about 15 minutes. In a terminal:

    cd C:\dev                (create the folder if needed)
    git clone https://github.com/johncliechty/anchor-plus-skills.git
    cd anchor-plus-skills
    .\onboard.cmd
    python launch_anchor_dashboard.py

That's a working install: onboard gets Python if you don't have it, walks a
short dialogue, registers the skills for Claude Code, and the launcher opens
the dashboard at http://localhost:8777. Everything is local — nothing leaves
your machine, and nothing spends your Claude subscription without an explicit
action by you.

**One more optional command, and I recommend it.** The skills are built to
run long jobs unattended — an hour-long build that reports a status table
every ten minutes instead of stalling on permission prompts. To get that
behavior (it's how I run them), first read `AUTONOMOUS-MODE.md` in the folder
you just cloned — it says exactly what this grants — then:

    python share_agent_rules.py install --settings

It writes to your own Claude config only, never overwrites a setting you
already made, keeps a backup, and `python share_agent_rules.py remove`
undoes it.

If anything breaks: `python doctor.py` (free, no AI calls) and send me what
it prints. Upgrading later: `git pull`, then re-run `.\onboard.cmd` once (idempotent;
registers any new skills the release added).

**Just want the skills, not the dashboard?** Same clone, same onboard — then
stop. Skip the launcher line entirely: onboard has already registered all 14
skills for Claude Code (check `%USERPROFILE%\.claude\skills`), and the
dashboard never runs unless you start it. The optional rules command applies
either way, and is what makes long skill runs report the 10-minute status
table instead of stalling on prompts.

— John
