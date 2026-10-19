#!/usr/bin/env python3
"""aegis_engine.py — Deterministic AST & Pattern Security Vulnerability Scanner + Auto-Remediation Engine.

Wave 17 (`Aegis` — Defensive Security Vulnerability Scanner & Auto-Remediation Skill):
Implements 6 OWASP/CWE detection and auto-remediation rules:
  - AEG-01 (CWE-78): Command & Shell Injection (`subprocess.*(shell=True)`, `os.system`, `os.popen`)
  - AEG-02 (CWE-94 / CWE-502): Dynamic Code Execution & Unsafe Deserialization (`eval`, `exec`, `pickle.loads`, `yaml.load`)
  - AEG-03 (CWE-22): Path Traversal & Unfenced File Access
  - AEG-04 (CWE-918): SSRF & Unvalidated URL Schemes (`urlopen` without scheme check)
  - AEG-05 (CWE-208 / CWE-328): Non-Constant-Time Secret Comparison & Weak Crypto (`md5`, `sha1` on secrets)
  - AEG-06 (CWE-798): Hardcoded Secrets, API Keys & Personal User-Profile Paths
"""
from __future__ import annotations

import argparse
import ast
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Dict, List


RULES_CATALOG: Dict[str, Dict[str, str]] = {
    "AEG-01": {
        "id": "AEG-01",
        "cwe": "CWE-78",
        "title": "Command & Shell Injection",
        "severity": "HIGH",
        "remediation_hint": "Use shell=False with an explicit argument list instead of invoking a shell.",
    },
    "AEG-02": {
        "id": "AEG-02",
        "cwe": "CWE-94 / CWE-502",
        "title": "Unsafe Dynamic Execution or Deserialization",
        "severity": "CRITICAL",
        "remediation_hint": "Replace eval() with ast.literal_eval(), yaml.load() with yaml.safe_load(), and avoid untrusted pickle.loads().",
    },
    "AEG-03": {
        "id": "AEG-03",
        "cwe": "CWE-22",
        "title": "Unfenced Path Join / Traversal Sink",
        "severity": "HIGH",
        "remediation_hint": "Resolve target path and verify .resolve().is_relative_to(base.resolve()) before file I/O.",
    },
    "AEG-04": {
        "id": "AEG-04",
        "cwe": "CWE-918",
        "title": "SSRF / Unvalidated URL Scheme in Network Call",
        "severity": "MEDIUM",
        "remediation_hint": "Validate urlparse(url).scheme in ('https', 'http') before calling urlopen.",
    },
    "AEG-05": {
        "id": "AEG-05",
        "cwe": "CWE-208 / CWE-328",
        "title": "Timing Side-Channel Token Equality or Weak Hash",
        "severity": "MEDIUM",
        "remediation_hint": "Use hmac.compare_digest(a, b) for token comparison and hashlib.sha256 for security digests.",
    },
    "AEG-06": {
        "id": "AEG-06",
        "cwe": "CWE-798",
        "title": "Hardcoded Secret, Token, or Personal User-Profile Path",
        "severity": "CRITICAL",
        "remediation_hint": "Read secrets from os.environ.get(...) and avoid hardcoded credentials or personal profile paths.",
    },
}

_SKIP_DIRS = {
    ".git", "__pycache__", ".venv", "venv", "node_modules", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", ".anchor", ".ecgberht", ".anvil",
}

_SECRET_PATTERNS = [
    (re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"), "Hardcoded OpenAI/Anthropic-style API key (`sk-...`)"),
    (re.compile(r"\bgh[po]_[A-Za-z0-9]{20,}\b"), "Hardcoded GitHub personal access token (`ghp_...`/`gho_...`)"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "Hardcoded AWS Access Key ID (`AKIA...`)"),
    (
        re.compile(r"""(?i)\b(api_key|secret_key|auth_token|access_token|password)\s*=\s*["']([A-Za-z0-9_\-]{16,})["']"""),
        "Hardcoded secret literal assigned to credential variable",
    ),
]


def _iter_python_files(target: Path) -> List[Path]:
    if target.is_file():
        return [target] if target.suffix == ".py" else []
    out: List[Path] = []
    for root, dirs, files in os.walk(target):
        dirs[:] = [d for d in sorted(dirs) if d not in _SKIP_DIRS]
        for f in sorted(files):
            if f.endswith(".py"):
                out.append(Path(root) / f)
    return out


def _call_qualname(node: ast.Call) -> str:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts = [func.attr]
        cur = func.value
        while isinstance(cur, ast.Attribute):
            parts.append(cur.attr)
            cur = cur.value
        if isinstance(cur, ast.Name):
            parts.append(cur.id)
        return ".".join(reversed(parts))
    return ""


def _synthesize_line_fix(rule_id: str, line: str) -> str:
    """Produce a deterministic single-line defensive replacement where applicable."""
    if rule_id == "AEG-01":
        if "shell=True" in line:
            return line.replace("shell=True", "shell=False")
        if "os.system(" in line:
            return re.sub(r"\bos\.system\((.+)\)", r"subprocess.run(\1, shell=False, check=False)", line)
    elif rule_id == "AEG-02":
        if re.search(r"\beval\s*\(", line):
            return re.sub(r"\beval\s*\(", "ast.literal_eval(", line, count=1)
        if "yaml.load(" in line and "Loader=" not in line:
            return line.replace("yaml.load(", "yaml.safe_load(", 1)
    elif rule_id == "AEG-05":
        if "hashlib.md5(" in line:
            return line.replace("hashlib.md5(", "hashlib.sha256(", 1)
        m = re.search(r"^(\s*(?:if|return)\s+)([A-Za-z0-9_.]+)\s*==\s*([A-Za-z0-9_.]+)(\s*:?.*)$", line)
        if m:
            prefix, lhs, rhs, suffix = m.groups()
            return f"{prefix}hmac.compare_digest(str({lhs}), str({rhs})){suffix}"
    elif rule_id == "AEG-06":
        m = re.search(r"""^(\s*)([A-Za-z_][A-Za-z0-9_]*)\s*=\s*["'][^"']+["'](.*)$""", line)
        if m:
            indent, var_name, tail = m.groups()
            env_key = var_name.upper()
            return f'{indent}{var_name} = os.environ.get("{env_key}", ""){tail}'
    return line


def scan_python_source(
    source: str,
    rel_path: str = "<memory>",
    signed_off_ids: set[str] | None = None,
) -> List[Dict[str, Any]]:
    """Scan a single Python source string and return structured vulnerability findings."""
    signed = signed_off_ids or set()
    lines = source.splitlines()
    findings: List[Dict[str, Any]] = []

    def _add(rule_id: str, lineno: int, message: str) -> None:
        idx = max(1, min(lineno, len(lines))) if lines else 1
        orig_line = lines[idx - 1] if lines else ""
        fid = f"{rule_id}:{rel_path}:{idx}"
        if fid in signed:
            return
        proposed_line = _synthesize_line_fix(rule_id, orig_line)
        meta = RULES_CATALOG[rule_id]
        findings.append({
            "finding_id": fid,
            "rule_id": rule_id,
            "cwe": meta["cwe"],
            "title": meta["title"],
            "severity": meta["severity"],
            "file": rel_path,
            "line": idx,
            "message": message,
            "snippet": orig_line.strip(),
            "proposed_fix": proposed_line.strip(),
            "auto_fixable": proposed_line != orig_line,
            "remediation_hint": meta["remediation_hint"],
        })

    # 1. Regex/pattern scan for hardcoded secrets (AEG-06)
    for idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        for pat, desc in _SECRET_PATTERNS:
            if pat.search(line):
                _add("AEG-06", idx, desc)
                break

    # 2. AST structural taint/sink analysis (AEG-01 through AEG-05)
    try:
        tree = ast.parse(source, filename=rel_path)
    except SyntaxError:
        return findings

    has_containment_guard = (
        "is_relative_to" in source
        or "unsafe_path_seg" in source
        or "os.path.realpath" in source
    )
    has_scheme_guard = (
        ".scheme" in source
        or "startswith(('http://', 'https://'))" in source
        or 'startswith(("http://", "https://"))' in source
    )

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            qname = _call_qualname(node)
            lineno = getattr(node, "lineno", 1)

            # AEG-01: subprocess(..., shell=True) or os.system / os.popen
            if qname in ("os.system", "os.popen"):
                _add("AEG-01", lineno, f"`{qname}(...)` invokes a subshell directly (`CWE-78`).")
            elif qname.endswith(("subprocess.run", "subprocess.Popen", "subprocess.call", "subprocess.check_output", "run", "Popen")):
                for kw in node.keywords or []:
                    if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                        _add("AEG-01", lineno, f"`{qname}(..., shell=True)` enables shell injection (`CWE-78`).")

            # AEG-02: eval / exec / pickle.loads / yaml.load without SafeLoader
            if qname in ("eval", "exec"):
                _add("AEG-02", lineno, f"Dynamic code execution via `{qname}()` (`CWE-94`).")
            elif qname in ("pickle.loads", "pickle.load", "marshal.loads", "marshal.load"):
                _add("AEG-02", lineno, f"Untrusted deserialization via `{qname}()` (`CWE-502`).")
            elif qname == "yaml.load":
                has_loader = any(kw.arg == "Loader" for kw in (node.keywords or []))
                if not has_loader:
                    _add("AEG-02", lineno, "`yaml.load()` called without SafeLoader (`CWE-502`).")

            # AEG-03: open() directly wrapping os.path.join(...) with dynamic segment without containment guard
            if qname == "open" and node.args:
                arg0 = node.args[0]
                if isinstance(arg0, ast.Call) and _call_qualname(arg0).endswith("join") and not has_containment_guard:
                    if any(not isinstance(a, ast.Constant) for a in arg0.args[1:]):
                        _add("AEG-03", lineno, "`open(os.path.join(...))` without path containment check (`CWE-22`).")

            # AEG-04: urlopen() on non-literal URL without scheme guard
            if qname.endswith("urlopen") and node.args:
                arg0 = node.args[0]
                if not isinstance(arg0, ast.Constant) and not has_scheme_guard:
                    _add("AEG-04", lineno, f"`{qname}()` on dynamic URL without scheme allowlist (`CWE-918`).")

            # AEG-05: hashlib.md5() used in security/password/token context
            if qname in ("hashlib.md5", "md5"):
                line_txt = lines[lineno - 1].lower() if 1 <= lineno <= len(lines) else ""
                if any(k in line_txt for k in ("password", "secret", "token", "auth", "key")):
                    _add("AEG-05", lineno, "`hashlib.md5()` used on security-sensitive value (`CWE-328`).")

        # AEG-05: direct `==` comparison on secret/token identifier
        elif isinstance(node, ast.Compare) and len(node.ops) == 1 and isinstance(node.ops[0], ast.Eq):
            lineno = getattr(node, "lineno", 1)
            names_in_cmp = [
                n.id.lower()
                for n in ast.walk(node)
                if isinstance(n, ast.Name)
            ]
            if any(n in ("secret_token", "expected_token", "api_secret", "hmac_sig", "password_hash") for n in names_in_cmp):
                _add(
                    "AEG-05",
                    lineno,
                    "Direct `==` comparison on secret/token identifier is vulnerable to timing side-channels (`CWE-208`); use `hmac.compare_digest`.",
                )

    return findings


def scan_target(
    target_path: str | Path,
    signed_off_ids: List[str] | None = None,
) -> Dict[str, Any]:
    """Scan a directory or Python file and return an Aegis security report."""
    root = Path(target_path).resolve()
    files = _iter_python_files(root)
    signed = set(signed_off_ids or ())
    all_findings: List[Dict[str, Any]] = []

    for f in files:
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        try:
            rel = str(f.relative_to(root)).replace("\\", "/") if root.is_dir() else f.name
        except ValueError:
            rel = f.name
        all_findings.extend(scan_python_source(src, rel_path=rel, signed_off_ids=signed))

    by_severity = {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0}
    by_rule: Dict[str, int] = {rid: 0 for rid in RULES_CATALOG}
    for item in all_findings:
        sev = item.get("severity", "MEDIUM")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        rid = item.get("rule_id", "")
        if rid in by_rule:
            by_rule[rid] += 1

    return {
        "schema": "aegis-security-report/v1",
        "ok": True,
        "scanned_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "target": str(root),
        "files_scanned": len(files),
        "total_findings": len(all_findings),
        "auto_fixable_count": sum(1 for f in all_findings if f.get("auto_fixable")),
        "verdict": "PASS" if len(all_findings) == 0 else ("BLOCK" if by_severity["CRITICAL"] > 0 or by_severity["HIGH"] > 0 else "WARN"),
        "severity_counts": by_severity,
        "rule_counts": by_rule,
        "findings": all_findings,
    }


def remediate_target(
    target_path: str | Path,
    apply: bool = False,
    rule_filter: str = "",
) -> Dict[str, Any]:
    """Synthesize (and optionally apply) deterministic AST/line patches for auto-fixable findings."""
    root = Path(target_path).resolve()
    report = scan_target(root)
    patches: List[Dict[str, Any]] = []
    files_modified: set[str] = set()

    findings_by_file: Dict[str, List[Dict[str, Any]]] = {}
    for f in report["findings"]:
        if rule_filter and f["rule_id"] != rule_filter:
            continue
        if f.get("auto_fixable"):
            findings_by_file.setdefault(f["file"], []).append(f)

    for rel_file, items in findings_by_file.items():
        fpath = (root / rel_file) if root.is_dir() else root
        if not fpath.is_file():
            continue
        orig_text = fpath.read_text(encoding="utf-8", errors="replace")
        lines = orig_text.splitlines()
        changed = False
        for it in items:
            idx = it["line"] - 1
            if 0 <= idx < len(lines):
                old_line = lines[idx]
                new_line = _synthesize_line_fix(it["rule_id"], old_line)
                if new_line != old_line:
                    lines[idx] = new_line
                    changed = True
                    patches.append({
                        "finding_id": it["finding_id"],
                        "rule_id": it["rule_id"],
                        "file": rel_file,
                        "line": it["line"],
                        "before": old_line.strip(),
                        "after": new_line.strip(),
                        "applied": bool(apply),
                    })
        if changed:
            new_source = "\n".join(lines) + ("\n" if orig_text.endswith("\n") else "")
            if "hmac.compare_digest(" in new_source and "import hmac" not in new_source:
                new_source = "import hmac\n" + new_source
            if "ast.literal_eval(" in new_source and "import ast" not in new_source:
                new_source = "import ast\n" + new_source
            # Verify valid Python syntax before writing
            try:
                ast.parse(new_source, filename=str(fpath))
            except SyntaxError:
                continue
            if apply:
                fpath.write_text(new_source, encoding="utf-8")
                files_modified.add(rel_file)

    post_scan = scan_target(root) if apply else report
    return {
        "schema": "aegis-remediation/v1",
        "ok": True,
        "applied": bool(apply),
        "target": str(root),
        "patches_count": len(patches),
        "files_modified": sorted(files_modified),
        "patches": patches,
        "remaining_findings": post_scan["total_findings"],
        "post_verdict": post_scan["verdict"],
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Aegis — Defensive Security Vulnerability Scanner & Auto-Remediation")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scan = sub.add_parser("scan", help="Scan target for OWASP/CWE security vulnerabilities")
    p_scan.add_argument("--target", required=True, help="Target file or directory")
    p_scan.add_argument("--output", default="", help="Optional JSON output file")

    p_rem = sub.add_parser("remediate", help="Synthesize or apply defensive security patches")
    p_rem.add_argument("--target", required=True, help="Target file or directory")
    p_rem.add_argument("--apply", action="store_true", help="Write fixes in-place after AST syntax verification")
    p_rem.add_argument("--rule", default="", help="Filter by rule ID (e.g. AEG-01)")
    p_rem.add_argument("--output", default="", help="Optional JSON output file")

    p_ver = sub.add_parser("verify", help="Run post-remediation scan and optional test suite")
    p_ver.add_argument("--target", required=True, help="Target file or directory")
    p_ver.add_argument("--test-cmd", default="", help="Optional test command to run")

    args = parser.parse_args(argv)
    if args.cmd == "scan":
        out = scan_target(args.target)
        if args.output:
            Path(args.output).write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "remediate":
        out = remediate_target(args.target, apply=args.apply, rule_filter=args.rule)
        if args.output:
            Path(args.output).write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(json.dumps(out, indent=2))
        return 0
    if args.cmd == "verify":
        scan_res = scan_target(args.target)
        test_ok = True
        test_out = ""
        if args.test_cmd:
            import shlex
            proc = subprocess.run(shlex.split(args.test_cmd), capture_output=True, text=True, check=False)
            test_ok = proc.returncode == 0
            test_out = (proc.stdout or "") + (proc.stderr or "")
        res = {
            "ok": scan_res["verdict"] == "PASS" and test_ok,
            "scan": scan_res,
            "test_ok": test_ok,
            "test_output": test_out[-1000:],
        }
        print(json.dumps(res, indent=2))
        return 0 if res["ok"] else 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
