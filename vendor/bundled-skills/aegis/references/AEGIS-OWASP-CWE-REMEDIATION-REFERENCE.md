# Aegis OWASP / CWE Deterministic Remediation Reference

**Skill:** `Aegis` (`<path> Foundry\skills\aegis\`)  
**Engine:** `scripts/aegis_engine.py`

---

## 1. Rule-by-Rule AST Detection & Defensive Replacement Specification

### `AEG-01` — Command & Shell Injection (`CWE-78`)
- **Dangerous Sink:** `subprocess.run(..., shell=True)`, `subprocess.Popen(..., shell=True)`, `subprocess.call(..., shell=True)`, `os.system(cmd)`, `os.popen(cmd)`.
- **Attack Vector:** Shell metacharacters (`;`, `|`, `&&`, `` ` ``, `$()`) in interpolated arguments execute arbitrary commands.
- **Deterministic Remediation:** Replace `shell=True` with `shell=False` and pass an explicit `List[str]` argument vector (`shlex.split(cmd)` or list literal).

### `AEG-02` — Dynamic Code Execution & Unsafe Deserialization (`CWE-94` / `CWE-502`)
- **Dangerous Sink:** `eval(expr)`, `exec(code)`, `pickle.loads(blob)`, `marshal.loads(blob)`, `yaml.load(stream)` without `SafeLoader`.
- **Attack Vector:** Arbitrary Python object instantiation or code execution from untrusted payloads.
- **Deterministic Remediation:** Replace `eval(` with `ast.literal_eval(`, replace `yaml.load(` with `yaml.safe_load(`, and reject untrusted `pickle.loads` in favor of schema-validated JSON.

### `AEG-03` — Path Traversal & Unfenced File Access (`CWE-22`)
- **Dangerous Sink:** Dynamic path construction (`Path(base) / user_rel` or `os.path.join(base, user_rel)`) passed directly to `open()`, `read_text()`, `write_text()`, or static file serving without canonical containment verification.
- **Attack Vector:** `../../` segments or symlink escapes reading or overwriting files outside the allowed workspace root.
- **Deterministic Remediation:** Enforce canonical containment before file I/O:
  ```python
  resolved_target = (base_dir / rel_path).resolve()
  if not resolved_target.is_relative_to(base_dir.resolve()):
      raise ValueError("Path traversal blocked outside base directory")
  ```

### `AEG-04` — Server-Side Request Forgery & Unvalidated URL Schemes (`CWE-918`)
- **Dangerous Sink:** `urllib.request.urlopen(url)` or `urllib.request.Request(url)` where `url` is not a constant `https://` or `http://` literal and no `urlparse` scheme guard is present in the enclosing function.
- **Attack Vector:** `file:///`, `ftp://`, or internal metadata endpoint probes via user-controlled URLs.
- **Deterministic Remediation:** Validate `urllib.parse.urlparse(url).scheme in ("https", "http")` and reject private/loopback targets when fetching external resources.

### `AEG-05` — Timing Side-Channels & Weak Cryptographic Digests (`CWE-208` / `CWE-328`)
- **Dangerous Sink:** Direct `==` or `!=` equality on variables named `token`, `secret`, `api_key`, `password`, `signature`, or `hmac`; or `hashlib.md5()` / `hashlib.sha1()` on credential/security material.
- **Attack Vector:** Byte-by-byte timing oracle recovery of bearer tokens or collision attacks on weak digests.
- **Deterministic Remediation:** Rewrite secret equality to `hmac.compare_digest(str(left), str(right))` and upgrade security digests to `hashlib.sha256()`.

### `AEG-06` — Hardcoded Secrets, API Keys & Personal Profile Paths (`CWE-798`)
- **Dangerous Sink:** Source literals matching `sk-...`, `ghp_...`, `gho_...`, `AKIA...`, hardcoded credential assignments (`api_key = "..."`), or hardcoded personal profile paths (`<path><username>\...`).
- **Attack Vector:** Credential leakage in git history or broken portability across collaborator machines.
- **Deterministic Remediation:** Replace hardcoded credentials with `os.environ.get("<ENV_VAR>", "")` and replace hardcoded user profile paths with `Path.home()` or configurable environment roots.
