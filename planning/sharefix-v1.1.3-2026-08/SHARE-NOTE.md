# Share note — paste-ready message for collaborators (v1.1.3, clone edition)

> Subject: Anchor v1.1.3 — fixed install, please give it a try
>
> Hi — thanks for your patience with the last drop; the install was genuinely
> broken (missing modules in the package) and your error reports are what got
> it fixed. v1.1.3 is a recovery release that has been through an automated
> "stranger install" test suite.
>
> On Windows (you just need git — no GitHub account required):
>
> ```
> cd C:\dev                (create the folder if needed)
> git clone https://github.com/johncliechty/anchor-plus-skills.git
> cd anchor-plus-skills
> .\onboard.cmd
> python launch_anchor_dashboard.py
> ```
>
> - Need git? `winget install --id Git.Git`
> - `onboard.cmd` installs Python via winget if you don't have it, walks a
>   short dialogue, installs 13 Claude Code skills, and sets up the local
>   dashboard (http://localhost:8777 — nothing leaves your machine).
> - After a reboot, just run the launcher again (no auto-start yet).
> - **Upgrades later are just `git pull`** — your data stays untouched.
>
> **For the AI features** (in-dashboard terminals, research/plan/build
> sessions) you also need the Claude Code CLI + your subscription
> (`npm install -g @anthropic-ai/claude-code`) plus Node.js. The dashboard
> works without them — AI features just report unavailable. Nothing spends
> your Claude subscription without an explicit action by you.
>
> **If ANYTHING is broken or annoying** — this is the important part —
> please take 30 seconds in the package folder:
> ```
> python doctor.py
> python anchor.py journal "what hurt" --severity problem --body "what you did + any error text"
> python anchor.py friction-report
> ```
> and send me the friction-report output. That exact loop is how the last
> round of bugs got found and fixed.
>
> Full instructions are in `USER-ONBOARD.md` in the repo. All rights
> reserved — please don't redistribute.

## Notes for John (not part of the message)

- **Repo is PUBLIC as of 2026-08-03** (John's call — low-touch sharing, no
  invites needed). All-rights-reserved, no LICENSE file = default copyright;
  visible but not licensed for reuse. To go private again:
  `gh repo edit johncliechty/anchor-plus-skills --visibility private --accept-visibility-change-consequences`
- **Republish after any fix**: `python tools/publish_share_repo.py`
  (rebuilds nothing itself — run the clean-ship builder first; it syncs the
  built B tree into the published repo, commits, tags, pushes). Collaborators
  then just `git pull`.
- Zips remain at `C:\dev\Anchor-ship\` as a no-github fallback
  (`Anchor-plus-skills-v1.1.3.zip` 9.7 MB · `Skills-only-v1.1.3.zip` 3.6 MB
  · SHA256SUMS.txt).
- This drop goes out BEFORE the Windows-Sandbox VM check (reboot pending,
  John traveling — accepted 2026-08-02). Evidence: build sandbox 10/10, pull
  dry run 7/7, clean-profile 8/8, element audit 14/14 — all against the
  final artifact. Untested residue: a foreign Windows image + the
  winget/python.org bootstrap on a python-less box; both degrade with honest
  printed instructions.
- After the reboot: `python C:\dev\Anchor-ship\vm-sandbox\host_run.py`, then
  resolve friction `2026-08-02-05` and widen the invite list.
