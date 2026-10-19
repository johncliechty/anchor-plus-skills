# Reader route is not recognized inside Markdown reports

Observed during Local Token Source research on 17 September 2026. The actual authenticated Current work pin opens `/steward/report?...` and renders the report, but the same origin-relative route inside Markdown is printed literally. Screenshot: `C:/dev/Open Source Token Source/Basic Infastructure/.ecgberht/research-hardware-models-REPORT.png` from 20:50 UTC. `steward_cockpit/static/md.js` recognizes absolute HTTP, `/artifact/` and `/api/steward/deliverable-file`, but excludes `/steward/report`.

No shared renderer change is made by this research effort. Current-work report pins remain the formatted entry points; supporting cross-links use the existing supported contained source-file route. Do not work around this with an author's loopback URL: remote clients would address themselves. A later UI fix should recognize the contained same-origin reader route and verify a real report-to-report click, using normal authentication, without changing external links or token boundaries.

Status: open UI improvement; source links adjusted within the research artifacts. No claim that the shared reader is repaired.
