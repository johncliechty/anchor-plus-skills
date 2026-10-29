# Aegis

**One sentence:** Deterministic software security vulnerability scanner, lossless AST/LibCST defensive patch synthesizer, and interactive AI Cockpit security workbench covering 6 high-consequence OWASP/CWE families (`CWE-78` shell injection, `CWE-94/502` unsafe execution & deserialization, `CWE-22` path traversal, `CWE-918` SSRF, `CWE-208/328` timing/crypto weaknesses, and `CWE-798` hardcoded secrets & PII paths) with live test-suite verification and cross-family adversarial security review.

## Use this when
- You want a **deterministic, zero-hallucination security audit** (`aegis scan`) of a project or repository across 6 high-consequence OWASP/CWE families with exact file, line, column, code snippet, and severity reporting
- You want **minimal, reversible defensive code patches** (`aegis remediate`) synthesized as clean unified diffs (`shell=False`, `ast.literal_eval`, `yaml.safe_load`, `.resolve().is_relative_to(base.resolve())`, `urlparse(u).scheme in ('https', 'http')`, `hmac.compare_digest`, `hashlib.sha256`, `os.environ.get`) before anything is modified on disk
- You want to **apply fixes and prove zero regressions** (`aegis verify`) by re-running the target's ground-truth test suite (`pytest -q`) alongside a clean re-scan and cross-family adversarial review
- You want to **sign off intentional, contained system patterns** (such as sandboxed job runners or test fixtures) in an auditable `.aegis/signed-off.json` ledger so reviewed boundaries never cause recurring alert fatigue
- You are shipping a release or running a Foreman build and want to verify zero leaked API keys, tokens, or personal `<path><name>` paths (`AEG-06`)

## Do not use this when
- You are trying to comprehend general program architecture, map paper equations to software, or refactor non-security legacy modules (use Anvil)
- You want an open-ended strategic or conceptual critique of a prose plan or research document (use Gandalf)
- You are cleaning up clutter files, duplicate scratch folders, or git hygiene without a code security audit (use Tidy-Idy, which calls Aegis's `AEG-06` secret check under the hood)

## What you get
- **Deterministic 6-Family Scanner (`aegis scan`):** Zero-LLM AST taint/sink and pattern/entropy inspection across `AEG-01` (`CWE-78`), `AEG-02` (`CWE-94`/`CWE-502`), `AEG-03` (`CWE-22`), `AEG-04` (`CWE-918`), `AEG-05` (`CWE-208`/`CWE-328`), and `AEG-06` (`CWE-798`), outputting structured JSON + markdown reports
- **Lossless Defensive Patch Synthesizer (`aegis remediate`):** Exact unified diffs and drop-in replacements for every auto-fixable finding, previewed first and applied only on explicit `--apply` or AI Cockpit approval
- **Explicit Sign-Off Ledger (`.aegis/signed-off.json`):** Auditable human sign-off for intentional, contained patterns with recorded rationale and file/line provenance
- **Live Regression & Adversarial Verification Gate (`aegis verify`):** Runs `pytest` / test gates + post-patch re-scan + cross-family adversarial security review (`Gandalf` / secondary model family) to certify that fixes close the CWE sink without breaking behavior
- **Interactive AI Cockpit Security Workbench (`/steward/aegis`):** Dedicated Anchor workbench (`aegis.html`) with CWE rule filtering, side-by-side proposed diffs, 1-click Apply Fix / Sign Off buttons, and a persistent Steward Security Dialogue dock

## What it is not
- Not an offensive exploitation tool or network penetration scanner
- Not a noisy regex linter that floods you with unverified style nitpicks
- Not an autonomous code mutator that edits production files during a read-only scan without human or worktree gate authorization

## How to start (human)
1. Open the **Aegis Security Workbench** from your AI Cockpit (`Aegis` shield button or `/steward/aegis?project=<id>`) or run `python "<path> Foundry/skills/aegis/scripts/aegis_engine.py" scan --target <path>`.
2. Filter findings by CWE rule (`AEG-01` .. `AEG-06`) or severity (`CRITICAL`, `HIGH`, `MEDIUM`) and inspect the proposed unified diff for each finding.
3. Click **Apply Fix** (or run `aegis_engine.py remediate --target <path> --apply`) to apply approved defensive patches, or **Sign Off** (with a brief rationale) for intentional contained boundaries.
4. Click **Verify & Run Tests** (or run `aegis_engine.py verify --target <path> --test-cmd "pytest -q"`) to confirm `0` remaining active findings and `PASS ✓` on the test suite.

## How it works
Aegis is powered by a deterministic Python AST and pattern analysis engine (`scripts/aegis_engine.py`). Stage 1 (`scan_target` / `scan_file`) parses every Python module into an Abstract Syntax Tree, walks every `ast.Call` and `ast.Compare` node against the 6 CWE rule analyzers (`_call_qualname`, `_is_secret_name`, `_SECRET_PATTERNS`), and filters out any human-approved entries in `.aegis/signed-off.json`. Stage 2 (`remediate_target` / `_synthesize_line_fix`) synthesizes minimal line-level and AST-level defensive replacements and generates unified diffs (`difflib.unified_diff`). Stage 3 (`verify_target`) executes the repository's test suite in a contained subprocess (`shell=False`), re-scans the target to confirm the sink is closed, and invokes the cross-family adversarial security reviewer (`Gandalf` / `~/.anchor/model_prefs.json`) when running a governed remediation wave.

## Limits (honest)
- Static AST analysis inspects Python source files deterministically (`*.py`), while secret/PII scanning (`AEG-06`) covers code and configuration literals; compiled binaries or external third-party SaaS endpoints are out of scope
- Structural multi-function taint flows across dynamic plugin loaders may require human or Steward review (`auto_fixable: false`) rather than a single-line automatic replacement

## For agents / engines
Full protocol, CWE rule matrix, state-machine stages, and CLI commands live in `SKILL.md`, `NORTH-STAR.md`, `references/AEGIS-OWASP-CWE-REMEDIATION-REFERENCE.md`, and `scripts/aegis_engine.py` next to this file. Load `SKILL.md` when running the skill — this card is for people.
