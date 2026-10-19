# Entanglement Census

This document lists every personal/machine entanglement hit in the repository, classified as `strip`, `parameterize`, or `refactor`.

## Hits

### absolute_path
- `C:\dev\Anchor\.agents\skills.json` (line 3): `    { "path": "C:\\dev\\trio" },` -> **parameterize**
- `C:\dev\Anchor\.agents\skills.json` (line 4): `    { "path": "C:\\dev\\Skill Foundry\\skills" }` -> **parameterize**
- `C:\dev\Anchor\.anchor\projects\227eb089706140388b829776d87e57c8\planning\summaries\dir_planning_rnd-v1\summary.md` (line 9): `C:\dev\Anchor` -> **strip**

### username_email
- `C:\dev\Anchor\.anchor\projects\227eb089706140388b829776d87e57c8\research\01-report.md` (line 13): `Anchor is a single-user... for J.C. Liechty (john.liechty@gmail.com)` -> **parameterize**
- `C:\dev\Anchor\.anchor\projects\f69f6d66171f4dbd95c8c45db6846d97\build\summaries\build_dir_planning_rnd-v1\summary.md` (line 33): `hard-coded the real email literal john.liechty@gmail.com` -> **strip**

### machine_name
- `C:\dev\Anchor\.agents\AGENTS.md` (line 10): `hostname PUTER, also referred to as gwl-server` -> **strip**

### hardcoded_model
- `C:\dev\Anchor\.anchor\projects\f69f6d66171f4dbd95c8c45db6846d97\build\summaries\build_dir_planning_zombie-hunter-safe-to-arm-2026-07-05\summary.md` (line 20): `claude:claude-opus-4-8; review on gemini-cli:gemini-3.1-pro` -> **parameterize**
