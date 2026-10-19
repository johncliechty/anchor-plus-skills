# Anchor notebook and model routing investigation — 2026-09-08

## Session intake

John reports that classroom Python/R deliverables do not consistently open as live Jupyter notebooks from the register and plan, that execution must occur on PUTER (the Anchor service host), and that Doctor/AI cockpit Steward still launch Claude/Fable after changing dashboard coding and terminal preferences to ChatGPT. He requests the latest ChatGPT model and Ultra effort wherever ChatGPT is selected in Anchor, Trio, and Foundry.

Assessment: medium complexity across service routing, persistent sessions, notebook hosting, and shared model drivers. Investigation and requested model configuration are in scope. Skill script repairs must follow a formal Foundry improvement cycle; no ad-hoc skill patches. Current preferences select coding=chatgpt, terminal=chatgpt, review=grok. This session owns this investigation only; earlier runs receive a one-shot status check.

## Evidence and decisions recorded during work

- Dashboard settings and the well-known mirror agree: default_cli=chatgpt, coding_family=chatgpt, review_family=grok, updated 2026-09-08T13:09:39Z. A missing preference write is not the current explanation.
- The 2026-09-07 code-windows planning run halted at Stage 2 shark-tank, with a reviewable draft emitted at 2026-09-08T02:41:00.879Z; HALT.json does not establish an implemented or deployed notebook feature.
- Current steward_cockpit/steward_engine.py initializes cli=claude and restricts switch targets to claude/grok/gemini. Its fallback returns to Claude. This conflicts with the selected ChatGPT family.
- Current Trio ChatGPT driver pins Heavy to gpt-5.6-sol and Standard to gpt-5.6-terra. Latest/Ultra selection needs verification against the installed subscription CLI and current official documentation before changing it.
- The notebook friction report dated 2026-09-07 documents temporary HTML launch pages, a manually started home-hosted Jupyter service, and pending cockpit routing/lifecycle improvements.
- Anchor service is running on PUTER; localhost:8777/api/version responds. No service restart or notebook execution has been performed by this session.
- Live Jupyter kernelspec probes succeeded at both 127.0.0.1:8890 and the Tailscale HTTPS :8446 endpoint; both advertise python3 and ir. The classroom host execution substrate exists today. No Jupyter/notebook scheduled startup task was found among current task names.
- First Doctor status probes returned 401 because the GET authentication path accepts Authorization rather than X-Anchor-Token. Repeating with the service's existing token in an Authorization header succeeded, without printing the token: live defaultEngine=chatgpt, Claude/Gemini disabled, ChatGPT/Grok enabled. Doctor's frontend only reads its own URL token (not dashboard localStorage); if status fails, it keeps the hardcoded Claude default and initially permissive health map. This is a specific launch-path defect, not proof the live settings endpoint ignores preferences.
- Installed codex-cli 0.153.4 reports ChatGPT subscription login and gpt-6-astra supporting ultra. Personal config is Astra/xhigh; Anchor codex_adapter.py pins Sol/ultra and ignores user config; Trio can pin Sol or Terra and chooses high for untiered/standard calls. Personal config alone cannot achieve the requested everywhere behavior.
- Initial headless tablet-sized browser probe reached a JupyterLab notebook interface through the Week 2 Python artifact launch page. The R probe initially showed existing Python tabs; this is NOT accepted as R notebook success. Tightening the diagnostic to await the exact requested filename before drawing a conclusion. No cells executed.

- A second browser run exposed a diagnostic flaw: waiting for the first visible notebook panel can time out on a restored hidden tab even when the requested R tab has appeared. Revised the check to await an attached notebook panel and the exact active tab. Prior generic JupyterLab title/panel checks are insufficient evidence of correct notebook selection.
- Additional active pin: Skill Foundry/skills/ramanujan/tools.manifest.json explicitly selects gpt-5.6-terra for its ChatGPT seat. Changing the shared driver's default would not override that explicit model argument.
- Applied the separately requested personal Codex configuration: existing gpt-6-astra kept, effort changed xhigh -> ultra, subagent defaults set to gpt-6-astra/ultra. This does not change running sessions, Anchor's isolated adapter, Trio pins, Ramanujan's manifest, or the Claude-only cockpit. No claim of universal propagation.

- Final browser probe passed for both Week 2 launch pages: the active tab was exactly week02-python.ipynb and week02-R.ipynb respectively. Screenshots were visually inspected. This was a tablet-sized Chromium browser on PUTER, not a physical iPad test; no cells were executed. R displayed a connecting status at capture, so kernel registration and notebook opening are verified, not successful fresh execution.
- The older run's Stage 2 error is `HaltError: trio seat seat_unavailable: synthesizer:direct:r1`. Its saved seating selected Claude coding and Grok review at launch. This establishes an unavailable seat and halted planning, not the underlying cause (quota versus authentication versus another provider problem). It does not establish that the later preference change was ignored by that already-started run.
- Doctor also has a backend-omitted legacy start path which selects a general engine without passing the current preferred backend. The authenticated current status result remains ChatGPT. The exact user launch request was not captured, so the source defects explain possible wrong-provider paths without claiming a reproduced incident.
- The cockpit Engine constructor receives no selected provider. Its command construction and event protocol are Claude-specific; changing a name or allowlist alone is not a valid Codex integration.
- A same-family agent reviewed the evidence for overclaims. This was reasoning review, not independent cross-family verification (`cross_model: false`). An additional documentation agent checked official Codex model and effort guidance; neither agent launched shell processes or edited files.

## Outcome

Investigation complete; repair work remains. The personal Codex configuration now selects gpt-6-astra/ultra for the main agent and subagents. No Anchor product code, Trio driver, Foundry skill, teaching file, or running service was changed. Existing sessions and explicit/isolated model pins are not affected by that configuration change.

The general notebook feature was not completed by the earlier planning run. The existing classroom launch-page workaround opens the correct notebooks, served by PUTER; startup persistence and fresh Python/R execution remain unverified. The model-routing failures are real integration gaps, not evidence that selecting ChatGPT failed to save.

Next: [bounded repair proposal](2026-09-08-model-routing-notebook-repair-proposal.md). Skill changes must pass the formal Foundry improvement cycle. An asynchronous question offered implementation or diagnosis-only scope; no answer was received during this investigation, so the broader repair was not launched.

## Skill usage and evidence artifacts

- Used openai-docs for model/effort verification and personal Codex configuration. Official references: [Codex models](https://learn.chatgpt.com/docs/models), [subagent configuration](https://learn.chatgpt.com/docs/agent-configuration/subagents), [configuration precedence](https://learn.chatgpt.com/docs/config-file/config-basic). The installed CLI catalog independently advertised gpt-6-astra with ultra.
- Reproducible read-only browser diagnostic: check-notebook-launches-2026-09-08.py. Screenshot artifacts: 2026-09-08-week02-python.png and 2026-09-08-week02-R.png. No model turns or notebook cells were run by that diagnostic.
- Machine session/usage record: journal/runs/2026-09-08-model-routing-notebook-investigation.json.
