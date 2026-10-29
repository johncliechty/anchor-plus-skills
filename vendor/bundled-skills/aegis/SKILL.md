---
name: Aegis
description: Defensive software security vulnerability scanner and auto-remediation engine (Sentinel / Aegis). Performs deterministic AST taint/sink analysis across 6 CWE/OWASP families (CWE-78 shell injection, CWE-94/502 code execution & unsafe deserialization, CWE-22 path traversal, CWE-918 SSRF, CWE-208/328 timing/crypto weaknesses, and CWE-798 hardcoded secrets/PII), synthesizes minimal AST/LibCST defensive patches, verifies fixes with regression tests + cross-family adversarial review, and integrates directly into Anchor AI Cockpits.
---

<!-- ELEGANCE-LAW v2 -->
## The Elegance Law (locked by John — binding on this skill)

Canonical text: `Skill Foundry/ELEGANCE.md`. Applies to ANY agent running this
skill on ANY host. If this block and a longer procedure below disagree, this
block wins.

1. **Approvals are ≤200 words** — what changes in his world, the recommendation,
   the one thing that gets worse. The artifact stays on disk and is named, not
   pasted. An approval obtained with a longer block is VOID.
2. **Summaries are ≤150 words** — goal in one line, done / not done, ≤3 findings
   ranked by consequence, the single next decision. Never rounds, waves, seats,
   stamps, gate counts, or file inventories.
3. **Default to the lightest band, without asking.** A heavier tier requires the
   first status line to NAME its trigger: irreversible or externally visible,
   inputs unconverged, a prior failure in this exact area, or he asked for it.
4. **Needed-because line.** Any element he did not request carries one line:
   "Needed because ___; dropping it costs ___." No line, no element.
5. **Show a cut.** ONE dry round ends a review loop — never a streak. Every plan
   names something it removed; "nothing cut" is said aloud.

**THE VERIFICATION LAW** (added 2026-08-15):
6. **Verify the claim you actually made, on the surface he actually uses.**
7. **A symptom reported twice retires the first explanation.**
8. **Prefer a mechanism to an instruction.**
9. **A correction that lives only in a journal or a memory has not been made.**
<!-- /ELEGANCE-LAW -->

> **Humans:** read `HUMAN.md` first. This file is the agent/engine protocol.

# Aegis — Defensive Security Vulnerability Scanner & Auto-Remediation Engine

**Aegis** (originally proposed as Sentinel, named **Aegis** to avoid colliding with Anchor's runtime process-health sentinel) is the portfolio's deterministic security audit, lossless AST/LibCST defensive patch synthesizer, and AI Cockpit security verification skill. It scans codebases for real exploitable vulnerabilities across 6 OWASP/CWE families, synthesizes minimal, reversible defensive patches, tracks intentional human-audited boundaries in `.aegis/signed-off.json`, and verifies that every patch closes the vulnerability without breaking tests.

---

## 1. Mission & Core Architecture

Aegis follows the **Functional Core / Imperative Shell** architecture and enforces five non-negotiable invariants:
1. **Zero-Hallucination Deterministic Detection (`scan_file` / `scan_target`):** Every finding is backed by a concrete Python AST node (`ast.Call`, `ast.Compare`) or high-precision secret/PII regex match with exact `file`, `line`, `col`, `rule_id`, `cwe`, `severity`, `snippet`, and `proposed_fix`.
2. **Read-Only Scan vs. Explicit Remediation Gate (`remediate_target`):** Running `scan` or `remediate` without `--apply` never modifies files on disk; it computes exact unified diffs (`difflib.unified_diff`) for human or Steward inspection.
3. **Auditable False-Positive / Contained-Boundary Sign-Off (`.aegis/signed-off.json`):** Intentional mechanisms (e.g., contained job runners, test fixtures) are signed off with explicit human rationale and preserved across scans.
4. **Ground-Truth Regression Verification (`verify_target`):** Every applied remediation is verified by re-running the target's test suite (`pytest -q`, executed with `shell=False`) plus a post-patch `scan_target` confirming the sink is closed.
5. **Cross-Family Adversarial Security Verification:** Governed remediation waves pair the primary coding seat with an independent cross-family security reviewer (`Gandalf` / secondary model family per `~/.anchor/model_prefs.json`).

---

## 2. Six Deterministic Vulnerability Families (OWASP / CWE)

| Rule ID | CWE | Vulnerability Family | Detection Mechanism (`scripts/aegis_engine.py`) | Defensive Auto-Remediation (`_synthesize_line_fix`) |
|---|---|---|---|---|
| **`AEG-01`** | `CWE-78` | **Command & Shell Injection** | AST call inspection of `subprocess.run`, `subprocess.Popen`, `subprocess.call`, `subprocess.check_output`, `os.system`, `os.popen` with `shell=True` or interpolated command strings. | Rewrite `shell=True` to `shell=False` with explicit argument list (`shlex.split` or list literal). |
| **`AEG-02`** | `CWE-94` / `CWE-502` | **Code Execution & Unsafe Deserialization** | AST inspection of `eval()`, `exec()`, `pickle.loads()`, `marshal.loads()`, and `yaml.load()` without `SafeLoader`. | Rewrite `eval(` to `ast.literal_eval(` and `yaml.load(` to `yaml.safe_load(`. |
| **`AEG-03`** | `CWE-22` | **Path Traversal & Unfenced File Access** | Detects dynamic path joins opened or served without `.resolve().is_relative_to(root)` or traversal segment validation. | Inject canonical `.resolve().is_relative_to(base.resolve())` containment guard. |
| **`AEG-04`** | `CWE-918` | **SSRF & Unvalidated URL Schemes** | Detects `urllib.request.urlopen()` or HTTP client calls on dynamic URLs without scheme allowlisting (`https://`, `http://`). | Wrap URL in scheme allowlist guard (`urlparse(u).scheme in ("https", "http")`). |
| **`AEG-05`** | `CWE-208` / `CWE-328` | **Timing Side-Channel & Weak Crypto** | Detects direct `==` / `!=` comparison on secret/token variables (`token == expected`) or `hashlib.md5`/`hashlib.sha1` security digests. | Rewrite token equality to `hmac.compare_digest(str(a), str(b))` and weak digest to `hashlib.sha256(`. |
| **`AEG-06`** | `CWE-798` | **Hardcoded Secrets, Tokens & PII Leaks** | Pattern + entropy scan for hardcoded API keys (`sk-`, `ghp_`, `AKIA`), bearer secret literals, and personal user-profile paths (`<path><name>`). | Replace literal secret with `os.environ.get("AEGIS_REDACTED_SECRET", "")` and scrub PII paths. |

---

## 3. 5-Stage Programmatic Audit & Remediation State Machine

When invoked on a repository or inside an Anchor AI Cockpit, Aegis executes a 5-stage workflow:
- **Stage 1 — Ingest, Scope & Triage (`step-1-ingest-triage`):** Resolves target files via `_iter_python_files`, loads complexity band and `~/.anchor/model_prefs.json` seating, and reads `.aegis/signed-off.json`.
- **Stage 2 — Knowledge Base & Reference Grounding (`step-2-context-kb-load`):** Loads `RULES_CATALOG`, project security constraints, and prior lessons from `LESSONS.md` and `references/AEGIS-OWASP-CWE-REMEDIATION-REFERENCE.md`.
- **Stage 3 — Deterministic AST Scan & Patch Synthesis (`step-3-core-execution`):** Runs `scan_target` and `remediate_target` to identify all CWE sinks and synthesize minimal unified diffs (`proposed_fix`, `diff`).
- **Stage 4 — Live Test Gate & Cross-Family Adversarial Verification (`step-4-adversarial-verify`):** Runs `verify_target` (`pytest -q` with `shell=False` + post-patch re-scan) and dispatches cross-family security review (`Gandalf`) on complex structural patches.
- **Stage 5 — Deliverable Emission & Journal Receipt (`step-5-emit-journal`):** Writes the structured security report, updates `.aegis/signed-off.json` / `.aegis/RUN-STATE.json`, and records operational lessons in `journal/` when friction occurs.

---

## 4. Programmatic CLI Usage (`scripts/aegis_engine.py`)

1. **Scan a repository or file (`scan`):**
   ```bash
   python "<path> Foundry/skills/aegis/scripts/aegis_engine.py" scan --target <path> [--output <report.json>]
   ```
2. **Synthesize (and optionally apply) defensive fixes (`remediate`):**
   ```bash
   python "<path> Foundry/skills/aegis/scripts/aegis_engine.py" remediate --target <path> [--apply] [--rule AEG-01] [--output <fixes.json>]
   ```
3. **Verify zero regressions + clean re-scan (`verify`):**
   ```bash
   python "<path> Foundry/skills/aegis/scripts/aegis_engine.py" verify --target <path> [--test-cmd "pytest -q"] [--output <verify.json>]
   ```

---

## 5. Model Seating, Portfolio Composition & AI Cockpit Workbench

Per the **Universal Seating Law**, when Aegis runs inside an Anchor AI Cockpit (`/steward/aegis`) or Skill Foundry workflow:
- **Coding / Patch Synthesis Seat:** Primary coding model (`~/.anchor/model_prefs.json`, e.g., `gemini-3.1-pro` via `agy-dispatch` or configured coding seat).
- **Adversarial Security Verification Seat:** Cross-family reviewer (`claude` / `Gandalf` seat) verifies that each proposed patch eliminates the CWE sink without introducing regressions or bypasses.
- **Portfolio Composition:** Composes with **Foreman** (as the zero-LLM deterministic security fast-gate during multi-wave builds), **Anvil** (sharing AST/LibCST codemod primitives), **Tidy-Idy** (pre-commit secret/PII scanning via `AEG-06`), and **Gandalf** (adversarial security critique).
