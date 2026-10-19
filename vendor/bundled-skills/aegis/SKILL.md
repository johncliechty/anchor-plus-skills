---
name: aegis
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

**Aegis** (originally proposed as Sentinel, named **Aegis** to avoid colliding with Anchor's runtime process-health sentinel) is the portfolio's deterministic security audit and auto-remediation skill. It scans codebases for real exploitable vulnerabilities, synthesizes minimal, reversible defensive patches, and verifies that every patch closes the vulnerability without breaking tests.

## 1. Six Deterministic Vulnerability Families (OWASP / CWE)

| Rule ID | CWE | Vulnerability Family | Detection Mechanism | Defensive Auto-Remediation |
|---|---|---|---|---|
| **`AEG-01`** | `CWE-78` | **Command & Shell Injection** | AST call inspection of `subprocess.run`, `subprocess.Popen`, `subprocess.call`, `os.system`, `os.popen` with `shell=True` or interpolated command strings. | Rewrite to `shell=False` with explicit argument list (`shlex.split` or list literal). |
| **`AEG-02`** | `CWE-94` / `CWE-502` | **Code Execution & Unsafe Deserialization** | AST inspection of `eval()`, `exec()`, `pickle.loads()`, `marshal.loads()`, and `yaml.load()` without `SafeLoader`. | Rewrite `eval()` to `ast.literal_eval()` and `yaml.load(...)` to `yaml.safe_load(...)`. |
| **`AEG-03`** | `CWE-22` | **Path Traversal & Unfenced File Access** | Detects dynamic path joins opened or served without `.resolve().is_relative_to(root)` or traversal segment validation. | Inject canonical `.resolve().is_relative_to(base.resolve())` containment guard. |
| **`AEG-04`** | `CWE-918` | **SSRF & Unvalidated URL Schemes** | Detects `urllib.request.urlopen()` or HTTP client calls on dynamic URLs without scheme allowlisting (`https://`, `http://`). | Wrap URL in scheme allowlist guard (`urlparse(u).scheme in ("https", "http")`). |
| **`AEG-05`** | `CWE-208` / `CWE-328` | **Timing Side-Channel & Weak Crypto** | Detects direct `==` comparison on secret/token variables (`token == expected`) or `md5`/`sha1` password/secret hashing. | Rewrite token equality to `hmac.compare_digest(str(a), str(b))` and weak digest to `hashlib.sha256`. |
| **`AEG-06`** | `CWE-798` | **Hardcoded Secrets, Tokens & PII Leaks** | Pattern + entropy scan for hardcoded API keys (`sk-`, `ghp_`, `AKIA`), JWTs, bearer secret literals, and personal user-profile paths. | Replace literal secret with `os.environ.get("<KEY_NAME>", "")` and scrub PII paths. |

## 2. How to Run (Operator Manual)

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
   python "<path> Foundry/skills/aegis/scripts/aegis_engine.py" verify --target <path> [--test-cmd "pytest -q"]
   ```

## 3. Model Seating & Cross-Family Adversarial Security Review
Per the **Universal Seating Law**, when Aegis runs inside an Anchor AI Cockpit or Skill Foundry workflow:
- **Coding / Patch Synthesis Seat:** `gemini-4-argon · high` (`gemini` CLI via `agy-dispatch`)
- **Adversarial Security Verification Seat:** `claude-fable-5-1 · max` (`claude` CLI) verifies that each proposed patch eliminates the CWE sink without introducing regressions or bypasses.
