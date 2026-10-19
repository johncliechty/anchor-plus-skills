# Aegis — Plain-English Guide for Humans

**Aegis** is your automated security auditor and fixer. Point it at any codebase or AI Cockpit project and it will:

1. **Find real security holes** across 6 categories:
   - **Shell injection (`AEG-01`):** commands that could let an attacker run arbitrary shell code.
   - **Unsafe code execution (`AEG-02`):** `eval()`, `pickle.loads()`, or unsafe `yaml.load()`.
   - **Path traversal (`AEG-03`):** file reads/writes that could escape the project folder via `../`.
   - **Unchecked URL fetches (`AEG-04`):** network calls that don't check `https://` / `http://`.
   - **Token & crypto weaknesses (`AEG-05`):** non-constant-time token checks or weak hashes.
   - **Leaked secrets & personal paths (`AEG-06`):** API keys, tokens, or `<path><name>` paths left in code.
2. **Write the exact defensive code fix** for each finding (as a minimal, readable diff).
3. **Apply & verify** the fix on command, re-running the scan and your test suite to prove the vulnerability is closed and nothing broke.
