# AEGIS — Locked North Star & Idea Log

**Skill Path:** `<path> Foundry\skills\aegis\`  
**Date Locked:** 2026-10-27  
**Author & Convergence Authority:** John  
**Visual Brand Asset:** `/vendor/brand/aegis-icon.jpg` + Standard Anchor Mark (`/vendor/brand/anchor-tab-48.png`)

---

## 1. The Locked North Star (Exact Text)

> **AEGIS NORTH STAR (2026-10-27 — Rev 1)**
>
> **Mission:** `Aegis` (originally proposed as Sentinel, named `Aegis` to preserve clarity alongside Anchor's runtime process-health sentinel) is the portfolio's deterministic defensive software security vulnerability scanner, lossless AST/LibCST auto-remediation engine, and human-governed security verification workbench. Instead of noisy regex lint floods or unverified LLM code edits, `Aegis` combines **zero-hallucination static AST taint/sink analysis**, **minimal reversible defensive code synthesis**, **explicit human sign-off for intentional contained boundaries**, **live regression + cross-family adversarial verification**, and **a dedicated interactive Anchor AI Cockpit Security Workbench**.
>
> **Five Core Pillars + Cross-Cutting Steward Security Dialogue:**
>
> 1. **Deterministic 6-Family OWASP/CWE AST Taint & Sink Scanner (`aegis scan` — `AEG-01` through `AEG-06`):**
>    - Performs zero-LLM, deterministic Python AST and pattern/entropy inspection across six high-consequence vulnerability families:
>      - **`AEG-01` (`CWE-78` — Command & Shell Injection):** Detects `subprocess.run`, `subprocess.Popen`, `subprocess.call`, `os.system`, and `os.popen` invoked with `shell=True` or interpolated command strings.
>      - **`AEG-02` (`CWE-94` / `CWE-502` — Dynamic Code Execution & Unsafe Deserialization):** Detects `eval()`, `exec()`, `pickle.loads()`, `marshal.loads()`, and `yaml.load()` without `SafeLoader`.
>      - **`AEG-03` (`CWE-22` — Path Traversal & Unfenced File Access):** Detects dynamic path joins opened or served without canonical `.resolve().is_relative_to(base.resolve())` containment verification.
>      - **`AEG-04` (`CWE-918` — SSRF & Unvalidated URL Schemes):** Detects `urllib.request.urlopen()` or HTTP client calls on dynamic URLs without scheme allowlisting (`https://`, `http://`).
>      - **`AEG-05` (`CWE-208` / `CWE-328` — Timing Side-Channels & Weak Crypto):** Detects non-constant-time `==` comparisons on secret/token variables (`token == expected`) and `md5`/`sha1` security digests.
>      - **`AEG-06` (`CWE-798` — Hardcoded Secrets, API Keys & Personal Profile Paths):** Scans for hardcoded API keys (`sk-`, `ghp_`, `AKIA`), bearer secret literals, and personal user-profile paths (`<path><name>`).
>
> 2. **Minimal, Reversible AST/LibCST Defensive Patch Synthesis (`aegis remediate`):**
>    - Synthesizes exact, human-readable unified diffs and single-line or structural AST/LibCST replacements for every actionable finding (`shell=False` with explicit argument lists, `ast.literal_eval`, `yaml.safe_load`, `.resolve().is_relative_to(base.resolve())`, `urlparse(u).scheme in ('https', 'http')`, `hmac.compare_digest`, `hashlib.sha256`, and `os.environ.get("<KEY>", "")`).
>    - Never mutates production files silently during a scan: patches are previewed as side-by-side diffs first and applied only when explicitly invoked with `--apply` or approved inside the AI Cockpit / isolated worktree gate.
>
> 3. **Explicit False-Positive & Contained-Boundary Sign-Off Ledger (`.aegis/signed-off.json`):**
>    - Distinguishes true exploitable vulnerabilities from audited, intentionally contained system mechanisms (such as kill-on-close Job Object sandboxes, read-only test fixtures, or non-security content checksums).
>    - Records human-authored sign-off rationale, rule ID, file/line provenance, and timestamp in `.aegis/signed-off.json` so reviewed boundaries do not trigger recurring alert fatigue while remaining transparently auditable on every future scan.
>
> 4. **Live Regression Gate & Cross-Family Adversarial Security Verification (`aegis verify`):**
>    - Re-runs the target repository's ground-truth test suite (`pytest -q` / `node --test`) alongside a post-patch `aegis scan` and an independent cross-family adversarial security review (`Gandalf` / secondary model family per `~/.anchor/model_prefs.json`).
>    - Certifies that every applied remediation closes the CWE sink without introducing behavioral regressions, bypasses, or broken tests—rolling the verified state up into `AEGIS-SECURITY-REPORT.md` and `.aegis/RUN-STATE.json`.
>
> 5. **First-Class Anchor AI Cockpit Security Workbench & Foreman Fast-Gate (`/steward/aegis`):**
>    - Powers the dedicated **Aegis Security Workbench** (`aegis.html` + `/api/aegis/*`) inside Anchor AI Cockpits, giving the human 1-click scanning, CWE family filtering, inline diff inspection, 1-click remediation or sign-off, and a persistent Steward security dialogue.
>    - Serves as **Foreman's deterministic security fast-gate**, catching CWE regressions in zero LLM tokens before any multi-wave build diff reaches cross-family review.

---

## 2. John's Idea & Requirement Log (Attached to `Aegis` — 2026-10-27)

| ID | Requirement / Idea | Where It Lives in `Aegis` |
| :--- | :--- | :--- |
| **AEG-REQ-01** | **Deterministic AST security scanning (not noisy LLM guessing):** Detect concrete OWASP/CWE sinks (`CWE-78`, `CWE-94/502`, `CWE-22`, `CWE-918`, `CWE-208/328`, `CWE-798`) with exact file, line, column, snippet, and severity metadata. | `scripts/aegis_engine.py` (`RULES_CATALOG`, `scan_file`, `scan_target`) |
| **AEG-REQ-02** | **Automated defensive fix synthesis (`aegis remediate`):** Generate minimal, readable unified diffs and drop-in defensive code replacements for every detected CWE rule without clobbering surrounding formatting or comments. | `scripts/aegis_engine.py` (`_synthesize_line_fix`, `remediate_target`) |
| **AEG-REQ-03** | **Verify-after-patch gate (`aegis verify`):** Re-run the scan and execute the target's test suite (`pytest -q`) after applying fixes so no security patch silently breaks product behavior. | `scripts/aegis_engine.py` (`verify_target`) |
| **AEG-REQ-04** | **Human-in-the-loop False-Positive / Contained-Boundary Sign-Off:** Allow the operator to sign off intentional, audited patterns (with recorded rationale in `.aegis/signed-off.json`) so they are tracked separately from active findings. | `/api/aegis/signoff` + `.aegis/signed-off.json` + `aegis.html` Sign-Off ledger |
| **AEG-REQ-05** | **Dedicated Anchor AI Cockpit Security Workbench (`/steward/aegis`):** Interactive UI with CWE rule cards, severity badges, proposed diff viewer, 1-click Apply Fix / Sign Off controls, and a persistent Steward Security Dialogue pane. | `static/cockpit/aegis.html` + `anchor_gui.py` (`/steward/aegis`, `/api/aegis/scan`, `/api/aegis/remediate`, `/api/aegis/verify`) |
| **AEG-REQ-06** | **Foreman & Tidy-Idy Portfolio Composition:** Run Aegis as Foreman's zero-LLM security fast-gate during multi-wave builds and as Tidy-Idy's pre-commit secret/PII guard (`AEG-06`). | `build_all_skill_maps.py` (`PEER_SKILL_CONNECTIONS['aegis']`, `foreman`, `tidyidy`) |
| **AEG-REQ-07** | **Foundry Visual Identity (`aegis-icon.jpg`):** Bespoke Foundry-style classical indigo-and-gold shield emblem with glowing cyan AST circuit nodes and defensive lock core, wired across Foundry cards, Cockpit headers, and Poincaré maps. | `vendor/brand/aegis-icon.jpg` + `foundry_page.py` (`ICON_NAMES`, `DISPLAY_NAMES`) |
| **AEG-REQ-08** | **Full Foundry Knowledge, Process & Anvil v2 Progressive Map Coverage:** Complete `NORTH-STAR.md`, `HUMAN.md`, `SKILL.md`, `library.json`, `process-map.json`, `knowledge-map.json`, and `ANVIL-MAP.json` with zero validation issues in Foundry. | `<path> Foundry\skills\aegis\` + `<path> Foundry\Foundry page and knowledge maps\aegis\` |
