# Draft tester email (v1.1.3 out-of-the-box test) — paste-ready

Subject: Can you spare 15 minutes to test Anchor v1.1.3?

Hi [name],

The last Anchor drop I sent around was genuinely broken — the package was
missing files, and your error reports are what got it fixed. I've rebuilt
the whole distribution pipeline and v1.1.3 has passed an automated
"stranger install" test suite. Before I invite more people, I'd love for
you to be an early tester: pull it fresh and tell me whether it works out
of the box on your machine.

You'll need: Windows 10/11 and git. No GitHub account, no admin rights,
about 15 minutes. In a terminal:

    cd C:\dev                (create the folder if needed)
    git clone https://github.com/johncliechty/anchor-plus-skills.git
    cd anchor-plus-skills
    .\onboard.cmd
    python launch_anchor_dashboard.py

Notes:
- Need git? winget install --id Git.Git
- onboard.cmd installs Python if you don't have it, walks a short
  dialogue, installs the Claude Code skills, and sets up the dashboard.
- The launcher should open http://localhost:8777 in your browser — a local
  dashboard; nothing leaves your machine, and nothing spends your Claude
  subscription without an explicit action by you.

"It works" looks like: the dashboard opens, you can add a task and
register a project, and Claude Code can see the new skills
(check that %USERPROFILE%\.claude\skills\crucible has a SKILL.md in it).
If you have the Claude Code CLI + Node.js installed, "Open terminal"
inside a project should give you a live session too — but that part is
optional for this test.

What I need back from you (either way — success reports count!):

1. Did it work out of the box? What OS / what did you already have
   installed (Python? git? Claude CLI)?
2. If ANYTHING broke, was confusing, or just felt off, run these in the
   package folder and paste me the output:

       python doctor.py
       python anchor.py journal "what hurt" --severity problem --body "what you did + any error text"
       python anchor.py friction-report

   That friction-report loop is literally how the last round of bugs got
   found and fixed, so even small annoyances are gold.

Later updates will just be `git pull` — your data stays untouched.

One ask: all rights reserved — the repo is publicly visible for easy
cloning, but please don't redistribute or reuse the code.

Thank you! This kind of ground-truth testing is exactly what the project
needs right now.

John
