# Doctor loses visible progress when switching app tiles — 3 October 2026

John's original request is Cave turn `009cedae-66b4-487e-9092-4ce06a51483c`: Doctor appears to stop or restart when he leaves its page in the new desktop app; diagnose why it is not diagnosing and resolving the displayed issues.

The actually served app and Doctor pages reproduce the loss: the app removes the inactive iframe, and returning creates a fresh Doctor page without its session identity, terminal attachment or healthcheck polling state. One simulated session launch, no extra launch on return. The WS/SSE disconnect paths end their streams, without killing the PTY. A completed or live server-owned run must not be inferred from an empty rebuilt display.

The observed actual healthcheck completed with exit 0; October 3 report says 32 correctness checks passed, zero issues, one non-blocking home-render timing warning. Live status is yellow/Warnings, not a correctness failure. The earlier model-session history has not been reconstructed; no paid repair execution or historical termination cause is established.

Recommendation for a separately authorized repair: reconstruct Doctor's server-owned state on return and reconnect only to the exact existing session, retaining model and Diagnose/Resolve permission mode. Recovery must not silently create a paid session. Preserve the existing inactive-frame policy. Opening while a known stale finding persists can otherwise request a further health re-run after a previous run finishes; show the run identity and result before treating that as fresh work.

Real-use acceptance: start one controlled Doctor run; switch to Cave and another tile; return during the run and after completion; verify the same session/run identity, output and truthful state, with no duplicate launch or permission-mode change. Repeat for Diagnose and Resolve, existing healthchecks, completed runs and no prior run. Finally verify inside the actual desktop Anchor window. Preserve all current sessions before any required activation.

Evidence: `C:/dev/Campaign/Cave of Wonders/doctor-diagnosis/REPORT-v1.html`, navigation/delivery receipts and inspected screenshots beside it. The actual desktop capture confirms WebView2 Anchor with Cave in front, not Doctor navigation. Report opens from the real Cave Deliverables bar and remains after reload. No production repair or restart has been implemented. The initial capture-principal and report-table verification failures were corrected in investigation tooling only and journaled locally.
