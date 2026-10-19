# Source notes and evidence boundaries

## Local evidence

The companion investigation is `../../docs/friction/2026-09-08-model-routing-notebook-investigation.md`. It distinguishes live probes from source findings. The old `../code-windows-2026-09-07/NORTH-STAR.md` is historical input, not the revised scope: local editor launch, arbitrary live URLs and automatic per-project lab creation are not first-release requirements after John's clarifications.

Current source seams inspected: Anchor `codex_adapter.py`, `anchor_gui.py` Doctor status/start, `steward_cockpit/steward_engine.py` constructor and transport, `steward_campaign.py` classify_route/read_deliverables, `steward_routes.py` deliverable MIME types, `static/shared.js` delivRow/openProducedFile, Trio `drivers/index.mjs` preference resolver and `drivers/grok-cli.mjs` subscription review transport. DELIVERABLES.md remains the existing sole register. No product code was modified in this review task.

## Official documentation used

- [Codex models](https://learn.chatgpt.com/docs/models): Astra is a current available product model; model availability depends on the installation/account. Ultra is a Codex mode involving maximum reasoning and automatic delegation, not a raw OpenAI API effort spelling to pass blindly to every endpoint.
- [Codex subagents](https://learn.chatgpt.com/docs/agent-configuration/subagents): per-agent and explicit spawn settings can override defaults. A global config edit alone cannot guarantee inherited model/effort throughout custom agents. Other safety and tool settings are separate.
- [Jupyter Server security](https://jupyter-server.readthedocs.io/en/latest/operators/security.html): Jupyter authenticates its own browser session; a login form can accept its token and establish a cookie. Do not put tokens in durable work-product links or disable auth because Anchor authenticated the user. Login recurs when session credentials expire/change.
- [JupyterLab URLs](https://jupyterlab.readthedocs.io/en/stable/user/urls.html): file deep links are supported. Preserve deployment base path and directory separators while encoding. Verify the requested active notebook, not any restored notebook. Avoid routine workspace reset.
- [Remote Jupyter operation](https://jupyter-server.readthedocs.io/en/stable/operators/public-server.html): remote usability requires the full HTTPS/WebSocket connection. Local Jupyter does not alone prove local kernel execution when Gateway/custom launchers are configured.
- [Jupyter Server configuration](https://jupyter-server.readthedocs.io/en/stable/api/jupyter_server.html): root_dir is not an OS security sandbox. Security inference: preserve origin/XSRF checks, trust only intended proxy headers and use a non-admin account with a minimal environment. A separate-origin top-level link does not require wildcard CORS.
- [IRkernel installation](https://github.com/IRkernel/IRkernel): R kernel registration must be visible to the account running Jupyter. A developer's per-user registration does not prove a service account can launch R.

The Jupyter documentation check was performed by a same-family supporting agent, not Grok. Grok's independent critique is captured separately with actual subscription CLI model attestation. Review approval is not execution, UI, packaging or deployment proof.
