# Collaborator invite checklist

Docs-as-code checklist for inviting a collaborator to private `*-dev`.

- [ ] **private_invite** — Invite collaborator to private *-dev source of truth only
- [ ] **branch_protection_no_force_push** — Branch protection: force-push disabled on main/release
- [ ] **branch_protection_no_direct_main** — Branch protection: no direct push to main (PR-only integrate)
- [ ] **codeowners** — CODEOWNERS present and required for review on protected paths
- [ ] **pr_only** — PR-only integrate into main; no bypass for collaborators
- [ ] **uninvited_pr_misroute** — Uninvited PR misroute guidance published (public consumers)

## Misroute guidance (uninvited PR)

This repository's private *-dev source of truth does not accept unsolicited pull requests from the public. Public consumers may (1) download & use release artifacts, (2) file issues, or (3) optionally opt into sanitized friction feedback — which is NOT a code contribution and is not a PR into product main. To contribute code, request a collaborator invite first; then push only feature branches and open a PR for review.

## Branch protection policy

```
{'protected_branches': ('main', 'master', 'release'), 'allow_force_push': False, 'allow_direct_push_to_main': False, 'require_pull_request': True, 'require_codeowners_review': True}
```
