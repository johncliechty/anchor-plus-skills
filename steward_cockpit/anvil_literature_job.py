"""Pillar-4 Two-Tier Literature Engine (`anvil_literature_job.py`):
  - Tier 0 (`< 50 ms`, zero network): Deterministic local `.bib` / `\\cite` index (`MANUSCRIPT_CITED`).
  - Tier 1 (2-Click Outbound Privacy Consent):
      * Click 1 (`issue_literature_consent`): validates ONLY strict anchored public catalog IDs
        (`DOI:10...` / `arXiv:YYYY.NNNNN` / `PMID:digits`, refusing `..`) from `.bib` (`0` unpublished draft prose,
        equations, or titles ever leave the machine!), returns `NO_CATALOG_SEEDS` if zero catalog IDs exist,
        or mints a domain-separated single-use nonce HMAC consent token disclosing all scholarly + CLI review hosts.
      * Click 2 (`start_literature_job`): per-run owner-token single-flight reservation (`owner_id` + `cancelled` flag
        under `_LIT_LOCK`), component `os.lstat` symlink refusal, Win32 Job Object containment, HMAC-signed
        `tier1_result.json` (`lit-result|`), and defense-in-depth cross-family posture clamping.
100% Python stdlib; zero `urllib`/`socket` in Anchor Python process.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from steward_cockpit import anvil_comprehension_engine as _ace
from steward_cockpit import anvil_session as _as
from steward_cockpit import anvil_verification_guard as _avg

LITERATURE_CONSENT_SCHEMA = "anvil-literature-consent/v1"
LITERATURE_STATE_SCHEMA = "anvil-literature-state/v1"
OUTBOUND_SCHOLARLY_HOSTS: Tuple[str, ...] = (
    "api.semanticscholar.org",
    "api.openalex.org",
    "api.crossref.org",
    "export.arxiv.org",
    "eutils.ncbi.nlm.nih.gov",
)
OUTBOUND_REVIEW_SEATS: Tuple[str, ...] = ("configured-local-cli-seats (Gemini agy / Claude Code on public abstracts only)",)
OUTBOUND_HOSTS: Tuple[str, ...] = OUTBOUND_SCHOLARLY_HOSTS
ALLOWED_CLAIM_POSTURES = frozenset({"MANUSCRIPT_CITED", "QUOTE_VERIFIED", "CLAIM_SUPPORTED"})
_SAFE_SEED_RE = re.compile(r"^(?!.*\.\.)(?:DOI:10\.\d{4,9}/[-._;()/:A-Za-z0-9]{1,120}|arXiv:\d{4}\.\d{4,5}(?:v\d+)?|PMID:\d{1,10})$")
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")

_LIT_LOCK: threading.Lock = globals().setdefault("_LIT_LOCK", threading.Lock())
_LIT_PROCS: Dict[str, Dict[str, Any]] = globals().setdefault("_LIT_PROCS", {})
_INJECTED_LIT_RUNNER: Any = globals().get("_INJECTED_LIT_RUNNER")


def set_literature_runner_for_tests(fn: Any) -> None:
    global _INJECTED_LIT_RUNNER
    _INJECTED_LIT_RUNNER = fn
    globals()["_INJECTED_LIT_RUNNER"] = fn


def _lit_dir(cdir_raw: Path, scope_sha256: str, *, create_dirs: bool = False) -> Path:
    clean_sha = str(scope_sha256 or "").strip().lower()
    if not _HEX64_RE.fullmatch(clean_sha):
        raise ValueError("Invalid scope_sha256")
    return _ace._ensure_no_reparse_chain(Path(cdir_raw), (".anvil", "literature", clean_sha), create_dirs=create_dirs)


def _filter_strict_catalog_seeds(raw_seeds: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    clean: List[Dict[str, str]] = []
    seen: set[str] = set()
    for s in raw_seeds:
        sid = str(s.get("seed_id") or "").strip()
        if not sid or len(sid) > 140 or not _SAFE_SEED_RE.fullmatch(sid) or sid in seen:
            continue
        seen.add(sid)
        clean.append({
            "seed_id": sid,
            "cite_key": str(s.get("cite_key") or "")[:80],
            "year": str(s.get("year") or "")[:8],
        })
    return clean


def _extract_local_bib_bundle(cdir: Path, *, analysis_id: Optional[str] = None) -> Tuple[str, Dict[str, Any]]:
    from steward_cockpit import anvil_scoping_v6 as _as6
    sc_state, sc_code = _as.get_scoping_v2_state(cdir, analysis_id=analysis_id, require_v6=False)
    if sc_code != 200 or not sc_state.get("ok"):
        return "", {"entries": [], "catalog_seeds": [], "occurrences": []}
    rcpt = sc_state.get("receipt") or sc_state.get("locked_scope") or {}
    locked_sha = _ace._extract_locked_sha(sc_state, analysis_id)
    drifted = bool(rcpt.get("drifted"))
    sw_spec = str(rcpt.get("software_spec") or sc_state.get("software_target") or ".")
    pp_spec = str(rcpt.get("paper_spec") or sc_state.get("paper_target") or "")
    sw_dir, _ = _as6.resolve_scoping_v2_local_dir(cdir, sw_spec)
    resolved_paper, _ = _as6.resolve_scoping_v2_paper_path(cdir, sw_dir, pp_spec)
    mods = _as._load_anvil_v4_modules()
    v4_proc, alm = mods["anvil_v4_process"], mods["anvil_latex_mathml"]
    if resolved_paper is None or _ace._is_lstat_reparse(resolved_paper) or not resolved_paper.is_file():
        resolved_paper = v4_proc._pick_main_tex_file(sw_dir) or v4_proc._pick_main_tex_file(cdir)
    if resolved_paper is None or _ace._is_lstat_reparse(resolved_paper) or not resolved_paper.is_file():
        return locked_sha, {"entries": [], "catalog_seeds": [], "occurrences": [], "drifted": drifted}
    ms = alm.resolve_manuscript_bundle(resolved_paper, allowed_root=cdir)
    bib_map = ms.get("bibliography") or {}
    return locked_sha, {
        "entries": list(bib_map.values()),
        "catalog_seeds": _filter_strict_catalog_seeds(list(ms.get("catalog_seeds") or [])),
        "occurrences": list(ms.get("citations") or [])[:120],
        "drifted": drifted,
    }


def _seeds_digest(catalog_seeds: List[Dict[str, str]]) -> str:
    ids = sorted({str(s.get("seed_id") or "") for s in catalog_seeds if s.get("seed_id")})
    return hashlib.sha256(json.dumps(ids).encode("utf-8")).hexdigest()


def _sign_consent(scope_sha256: str, seeds_sha: str, issued_ts: int, nonce: str) -> str:
    msg = f"lit-consent|{scope_sha256}:{seeds_sha}:{issued_ts}:{nonce}".encode("utf-8")
    return hmac.new(_ace._cache_hmac_key(), msg, hashlib.sha256).hexdigest()


def _verify_runner_adversarial_posture(raw_adv: Any) -> Tuple[Dict[str, Any], bool]:
    """Defense-in-depth check over runner `callReceipts` before permitting `ATTESTED` / `CLAIM_SUPPORTED`."""
    adv = dict(raw_adv) if isinstance(raw_adv, Mapping) else {}
    receipts = adv.get("callReceipts") if isinstance(adv.get("callReceipts"), list) else []
    extract_fams: Set[str] = set()
    judge_fams: Set[str] = set()
    all_attested = True
    for r in receipts:
        if not isinstance(r, Mapping):
            all_attested = False
            continue
        mod_s = str(r.get("model_served") or "").strip()
        v_s = str(r.get("vendor") or "").strip().lower()
        fam = _avg.infer_vendor_family(mod_s)
        if not mod_s or not fam or (v_s and v_s != fam):
            all_attested = False
            continue
        if str(r.get("role") or "") == "extraction":
            extract_fams.add(fam)
        else:
            judge_fams.add(fam)
    cross_family_ok = bool(
        all_attested and extract_fams and judge_fams
        and all(jf not in extract_fams for jf in judge_fams)
        and adv.get("judgeSupported") is True
    )
    adv["crossFamilyVerified"] = cross_family_ok
    if cross_family_ok:
        adv["displayState"] = "ATTESTED"
    else:
        raw_ds = str(adv.get("displayState") or "NO_RECEIPT")
        adv["displayState"] = raw_ds if raw_ds in ("SEAT_UNAVAILABLE", "NO_RECEIPT") else ("SINGLE_FAMILY_CLAIMED" if receipts else "NO_RECEIPT")
        adv["judgeSupported"] = False
    return adv, cross_family_ok


def get_literature_state(cdir: str | Path, *, analysis_id: Optional[str] = None) -> Tuple[Dict[str, Any], int]:
    c_raw = Path(cdir)
    try:
        if _ace._is_lstat_reparse(c_raw):
            raise _ace.AnvilPathEscapeError("Cockpit directory is a symlink or junction.")
        c_path = c_raw.resolve()
        scope_sha, local_bib = _extract_local_bib_bundle(c_path, analysis_id=analysis_id)
    except Exception as exc:
        if type(exc).__name__ in ("AnvilLatexSecurityError", "AnvilRefusalError", "AnvilPathEscapeError"):
            return {"ok": False, "error_code": "PATH_ESCAPE_REFUSED", "cwe": "CWE-22", "message": str(exc)}, 403
        raise

    seeds = local_bib["catalog_seeds"]
    tier1_status = "NO_CATALOG_SEEDS" if not seeds else "not_requested"
    tier1_result: Dict[str, Any] = {}
    if _HEX64_RE.fullmatch(scope_sha):
        try:
            lit_d = _lit_dir(c_raw, scope_sha, create_dirs=False)
            res_f = lit_d / "tier1_result.json"
            if _ace._is_lstat_reparse(res_f):
                raise _ace.AnvilPathEscapeError("Symlink tier1_result.json refused.")
        except _ace.AnvilPathEscapeError as p_exc:
            return {"ok": False, "error_code": "PATH_ESCAPE_REFUSED", "cwe": "CWE-22", "message": str(p_exc)}, 403
        if res_f.is_file():
            p_slug = _ace._project_slug(c_path)
            try:
                loaded = json.loads(res_f.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict) or not _ace.verify_state_record("lit-result", loaded, expected_proj_slug=p_slug, expected_scope=scope_sha):
                    row = dict(_avg.COMPREHENSION_FAILURE_TABLE["backing-store-unreadable"])
                    return {"ok": False, **row}, int(row["http_status"])
                verified_adv, allow_cs = _verify_runner_adversarial_posture(loaded.get("adversarial"))
                clamped_claims: List[Dict[str, Any]] = []
                for cl in (loaded.get("claims") or []):
                    if isinstance(cl, dict):
                        cc = dict(cl)
                        if cc.get("posture") == "CLAIM_SUPPORTED" and not allow_cs:
                            cc["posture"] = "QUOTE_VERIFIED"
                        clamped_claims.append(cc)
                tier1_result = {k: v for k, v in loaded.items() if k != "_hmac"}
                tier1_result["adversarial"] = verified_adv
                tier1_result["claims"] = clamped_claims
                tier1_status = str(tier1_result.get("status") or "completed")
            except Exception:
                row = dict(_avg.COMPREHENSION_FAILURE_TABLE["backing-store-unreadable"])
                return {"ok": False, **row}, int(row["http_status"])
    return {
        "ok": True,
        "schema": LITERATURE_STATE_SCHEMA,
        "scope_sha256": scope_sha,
        "tier0_manuscript_cited": {
            "posture": "MANUSCRIPT_CITED",
            "count": len(local_bib["entries"]),
            "entries": local_bib["entries"][:80],
            "occurrences": local_bib["occurrences"],
        },
        "catalog_seeds": seeds,
        "tier1_status": tier1_status,
        "tier1_validated": tier1_result,
    }, 200


def issue_literature_consent(cdir: str | Path, body: Optional[Mapping[str, Any]] = None) -> Tuple[Dict[str, Any], int]:
    c_raw = Path(cdir)
    try:
        if _ace._is_lstat_reparse(c_raw):
            raise _ace.AnvilPathEscapeError("Cockpit directory is a symlink or junction.")
        c_path = c_raw.resolve()
        scope_sha, local_bib = _extract_local_bib_bundle(c_path, analysis_id=(body or {}).get("analysis_id"))
    except Exception as exc:
        if type(exc).__name__ in ("AnvilLatexSecurityError", "AnvilRefusalError", "AnvilPathEscapeError"):
            return {"ok": False, "error_code": "PATH_ESCAPE_REFUSED", "cwe": "CWE-22", "message": str(exc)}, 403
        raise
    if not _HEX64_RE.fullmatch(scope_sha):
        return {"ok": False, "error_code": "SCOPE_NOT_LOCKED", "message": "Lock a scope before requesting literature validation."}, 409
    if local_bib.get("drifted"):
        return {"ok": False, "error_code": "SCOPE_DRIFTED", "message": "Locked scope has drifted; re-lock before literature validation."}, 409

    seeds = local_bib["catalog_seeds"][:6]
    if not seeds:
        return {
            "ok": True, "schema": LITERATURE_CONSENT_SCHEMA, "status": "NO_CATALOG_SEEDS",
            "scope_sha256": scope_sha, "catalog_seed_ids": [], "outbound_hosts": [],
            "message": "No valid public DOI, arXiv, or PMID catalog identifiers found in .bib; zero outbound requests sent.",
        }, 200

    ts = int(time.time())
    nonce = secrets.token_hex(12)
    tok = f"{ts}.{nonce}.{_sign_consent(scope_sha, _seeds_digest(seeds), ts, nonce)}"
    return {
        "ok": True, "schema": LITERATURE_CONSENT_SCHEMA, "status": "awaiting-literature-consent",
        "scope_sha256": scope_sha, "consent_token": tok,
        "catalog_seed_ids": [s["seed_id"] for s in seeds],
        "unpublished_prose_transmitted": False,
        "outbound_hosts": list(OUTBOUND_SCHOLARLY_HOSTS),
        "review_seats_disclosed": list(OUTBOUND_REVIEW_SEATS),
        "max_snowball_depth": 1, "max_papers_extracted": 3, "adversarial_rounds": 1,
    }, 200


def _consume_consent_nonce_once(out_dir: Path, nonce: str) -> bool:
    nonce_f = out_dir / "consumed_nonces.json"
    lock_f = out_dir / "consumed_nonces.lock"
    if _ace._is_lstat_reparse(nonce_f) or _ace._is_lstat_reparse(lock_f):
        raise _ace.AnvilPathEscapeError("Symlink consumed_nonces.json or consumed_nonces.lock refused.")
    with _as.exclusive_file_lock(lock_f):
        used: List[str] = []
        if nonce_f.is_file():
            try:
                used = list(json.loads(nonce_f.read_text(encoding="utf-8")))
            except Exception:
                used = []
        if nonce in used:
            return False
        used = (used + [nonce])[-512:]
        _as._atomic_write_text(nonce_f, json.dumps(used))
        return True


def start_literature_job(cdir: str | Path, body: Optional[Mapping[str, Any]] = None) -> Tuple[Dict[str, Any], int]:
    req = dict(body or {})
    c_raw = Path(cdir)
    try:
        if _ace._is_lstat_reparse(c_raw):
            raise _ace.AnvilPathEscapeError("Cockpit directory is a symlink or junction.")
        c_path = c_raw.resolve()
        scope_sha, local_bib = _extract_local_bib_bundle(c_path, analysis_id=req.get("analysis_id"))
    except Exception as exc:
        if type(exc).__name__ in ("AnvilLatexSecurityError", "AnvilRefusalError", "AnvilPathEscapeError"):
            return {"ok": False, "error_code": "PATH_ESCAPE_REFUSED", "cwe": "CWE-22", "message": str(exc)}, 403
        raise
    if not _HEX64_RE.fullmatch(scope_sha):
        return {"ok": False, "error_code": "SCOPE_NOT_LOCKED", "message": "Scope not locked."}, 409
    if local_bib.get("drifted"):
        return {"ok": False, "error_code": "SCOPE_DRIFTED", "message": "Locked scope has drifted; re-lock before literature validation."}, 409
    if req.get("scope_sha256") and str(req["scope_sha256"]).strip().lower() != scope_sha:
        return {"ok": False, "error_code": "SCOPE_SHA_MISMATCH", "message": "Consent scope_sha256 does not match active locked scope."}, 409

    seeds = _filter_strict_catalog_seeds(local_bib["catalog_seeds"])[:6]
    if not seeds:
        return {"ok": True, "status": "NO_CATALOG_SEEDS", "claims": []}, 200

    parts = str(req.get("consent_token") or "").strip().split(".")
    if len(parts) != 3:
        return {"ok": False, "error_code": "LITERATURE_CONSENT_REQUIRED", "message": "Explicit 2-click literature privacy consent_token required."}, 403
    ts_part, nonce_part, sig_part = parts
    if not ts_part.isdigit() or len(ts_part) > 12 or not re.fullmatch(r"[0-9a-f]{24}", nonce_part) or abs(int(time.time()) - int(ts_part)) > 1800:
        return {"ok": False, "error_code": "LITERATURE_CONSENT_EXPIRED", "message": "Literature consent token expired; preview seeds again."}, 403
    if not hmac.compare_digest(sig_part, _sign_consent(scope_sha, _seeds_digest(seeds), int(ts_part), nonce_part)):
        return {"ok": False, "error_code": "LITERATURE_CONSENT_INVALID", "message": "Invalid literature consent token."}, 403

    inj = globals().get("_INJECTED_LIT_RUNNER") if os.environ.get("PYTEST_CURRENT_TEST") else None
    node_exe: Optional[str] = None
    runner_mjs: Optional[Path] = None
    if not callable(inj):
        node_exe = _ace._resolve_strict_exe(["node.exe", "node"], exclude_dir=c_path)
        cand_mjs = _as._ANCHOR_ROOT.parent / "Skill Foundry" / "skills" / "anvil" / "scripts" / "anvil_literature_runner.mjs"
        if not cand_mjs.is_file():
            cand_mjs = _as._ANCHOR_ROOT / "vendor" / "bundled-skills" / "anvil" / "scripts" / "anvil_literature_runner.mjs"
        if not node_exe or not cand_mjs.is_file():
            return {"ok": False, "error_code": "DEPENDENCY_MISSING", "message": "node.exe or anvil_literature_runner.mjs unavailable."}, 503
        runner_mjs = cand_mjs

    try:
        out_dir = _lit_dir(c_raw, scope_sha, create_dirs=True)
    except _ace.AnvilPathEscapeError as p_exc:
        return {"ok": False, "error_code": "PATH_ESCAPE_REFUSED", "cwe": "CWE-22", "message": str(p_exc)}, 403

    slot_key = f"{c_path}::{scope_sha}"
    owner_id = secrets.token_hex(8)
    with _LIT_LOCK:
        if slot_key in _LIT_PROCS:
            return {"ok": False, "error_code": "LITERATURE_JOB_IN_FLIGHT", "message": "Literature validation already running for this scope."}, 409
        _LIT_PROCS[slot_key] = {"owner": owner_id, "proc": None, "job": 0, "cancelled": False}

    res_f = out_dir / "tier1_result.json"
    p_slug = _ace._project_slug(c_path)
    tmp_d: Optional[Path] = None
    timed_out = False
    try:
        if _ace._is_lstat_reparse(res_f):
            return {"ok": False, "error_code": "PATH_ESCAPE_REFUSED", "cwe": "CWE-22", "message": "Symlink tier1_result.json refused."}, 403
        if not _consume_consent_nonce_once(out_dir, nonce_part):
            return {"ok": False, "error_code": "LITERATURE_CONSENT_REPLAYED", "message": "Consent token already used; preview seeds again."}, 403

        if callable(inj):
            raw_inj = dict(inj(scope_sha256=scope_sha, catalog_seeds=[{"seed_id": s["seed_id"]} for s in seeds]) or {})
            verified_adv_i, allow_cs_i = _verify_runner_adversarial_posture(raw_inj.get("adversarial"))
            inj_body = {
                "ok": True, "proj_slug": p_slug, "scope_sha256": scope_sha, "status": "completed",
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "candidates_found": int(raw_inj.get("candidates_found") or 0),
                "claims": [
                    {**c, "posture": ("CLAIM_SUPPORTED" if (c.get("posture") == "CLAIM_SUPPORTED" and allow_cs_i) else "QUOTE_VERIFIED")}
                    for c in (raw_inj.get("claims") or []) if isinstance(c, dict) and c.get("posture") in ("CLAIM_SUPPORTED", "QUOTE_VERIFIED")
                ],
                "rejected_quotes_count": int(raw_inj.get("rejected_quotes_count") or 0),
                "adversarial": verified_adv_i,
            }
            _as._atomic_write_text(res_f, json.dumps({**inj_body, "_hmac": _ace.sign_state_record("lit-result", inj_body)}, indent=2))
            return {**inj_body}, 200

        user_prof = os.environ.get("USERPROFILE") or ""
        claude_cands = ([str(Path(user_prof) / ".local" / "bin" / "claude.exe")] if user_prof else []) + ["claude.exe"]
        claude_exe = _ace._resolve_strict_exe(claude_cands, exclude_dir=c_path) or ""

        tmp_d = Path(tempfile.mkdtemp(prefix="anvil_lit_job_"))
        in_f, out_f = tmp_d / "input.json", tmp_d / "output.json"
        in_f.write_text(json.dumps({
            "catalog_seeds": [{"seed_id": s["seed_id"]} for s in seeds],
            "claude_exe": claude_exe, "claude_model": "opus", "adversarial_rounds": 1,
        }), encoding="utf-8")

        proc, job_handle = _ace.spawn_in_win32_job(
            [str(node_exe), str(runner_mjs), "--input", str(in_f), "--output", str(out_f)],
            cwd=tmp_d, env=_ace.build_minimal_cli_env(), has_stdin=False,
        )
        abort_spawn = False
        with _LIT_LOCK:
            cur_slot = _LIT_PROCS.get(slot_key)
            if cur_slot is None or cur_slot.get("owner") != owner_id or cur_slot.get("cancelled"):
                abort_spawn = True
            else:
                cur_slot["proc"] = proc
                cur_slot["job"] = job_handle
        if abort_spawn:
            _ace.terminate_and_close_win32_job(job_handle, terminate=True)
            proc.kill()
            proc.communicate()
            return {"ok": False, "error_code": "LITERATURE_CANCELLED", "message": "Literature job cancelled during startup."}, 499

        try:
            proc.communicate(timeout=300)
        except subprocess.TimeoutExpired:
            timed_out = True
            jh_to = 0
            with _LIT_LOCK:
                cur_to = _LIT_PROCS.get(slot_key)
                if cur_to is not None and cur_to.get("owner") == owner_id:
                    jh_to = int(cur_to.get("job") or 0)
                    cur_to["job"] = 0
            if jh_to:
                _ace.terminate_and_close_win32_job(jh_to, terminate=True)
            proc.kill()
            proc.communicate()
            return {"ok": False, "error_code": "LITERATURE_TIMEOUT", "message": "Literature snowball timed out."}, 504

        with _LIT_LOCK:
            cur_after = _LIT_PROCS.get(slot_key)
            if cur_after is None or cur_after.get("owner") != owner_id or cur_after.get("cancelled"):
                return {"ok": False, "error_code": "LITERATURE_CANCELLED", "message": "Literature job cancelled."}, 499

        if not out_f.is_file():
            return {"ok": False, "error_code": "LITERATURE_FAILED", "message": "Literature runner produced no output."}, 502
        try:
            raw_res = json.loads(out_f.read_text(encoding="utf-8"))
        except Exception:
            return {"ok": False, "error_code": "LITERATURE_MALFORMED_JSON", "message": "Literature runner returned invalid JSON."}, 502
        if not isinstance(raw_res, dict):
            return {"ok": False, "error_code": "LITERATURE_MALFORMED_JSON", "message": "Literature runner output must be an object."}, 502

        verified_adv, allow_claim_supported = _verify_runner_adversarial_posture(raw_res.get("adversarial"))
        sanitized_claims: List[Dict[str, Any]] = []
        for cl in (raw_res.get("claims") or []):
            if isinstance(cl, dict):
                posture = str(cl.get("posture") or "")
                if posture == "CLAIM_SUPPORTED":
                    cl_clean = {**cl, "posture": "CLAIM_SUPPORTED" if allow_claim_supported else "QUOTE_VERIFIED"}
                    sanitized_claims.append(cl_clean)
                elif posture == "QUOTE_VERIFIED":
                    sanitized_claims.append({**cl, "posture": "QUOTE_VERIFIED"})

        result_body = {
            "ok": bool(raw_res.get("ok")),
            "proj_slug": p_slug,
            "scope_sha256": scope_sha,
            "status": "completed" if raw_res.get("ok") else "failed",
            "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "candidates_found": int(raw_res.get("candidates_found") or 0),
            "claims": sanitized_claims,
            "rejected_quotes_count": int(raw_res.get("rejected_quotes_count") or 0),
            "adversarial": verified_adv,
        }
        _as._atomic_write_text(res_f, json.dumps({**result_body, "_hmac": _ace.sign_state_record("lit-result", result_body)}, indent=2))
        return dict(result_body), (200 if result_body["ok"] else 502)
    except _ace.AnvilPathEscapeError as p_exc:
        return {"ok": False, "error_code": "PATH_ESCAPE_REFUSED", "cwe": "CWE-22", "message": str(p_exc)}, 403
    finally:
        owned_jh = 0
        with _LIT_LOCK:
            cur_f = _LIT_PROCS.get(slot_key)
            if cur_f is not None and cur_f.get("owner") == owner_id:
                _LIT_PROCS.pop(slot_key, None)
                owned_jh = int(cur_f.get("job") or 0)
                cur_f["job"] = 0
        if owned_jh:
            _ace.terminate_and_close_win32_job(owned_jh, terminate=timed_out)
        if tmp_d is not None:
            shutil.rmtree(tmp_d, ignore_errors=True)


def cancel_literature_job(cdir: str | Path, body: Optional[Mapping[str, Any]] = None) -> Tuple[Dict[str, Any], int]:
    c_path = Path(cdir).resolve()
    scope_sha = str((body or {}).get("scope_sha256") or "").strip().lower()
    slot_key = f"{c_path}::{scope_sha}"
    jh = 0
    proc: Optional[subprocess.Popen[str]] = None
    found = False
    with _LIT_LOCK:
        cur = _LIT_PROCS.get(slot_key)
        if cur is not None:
            found = True
            cur["cancelled"] = True
            jh = int(cur.get("job") or 0)
            proc = cur.get("proc")
            cur["job"] = 0
            cur["proc"] = None
    if jh:
        _ace.terminate_and_close_win32_job(jh, terminate=True)
    if proc is not None:
        proc.kill()
    return {"ok": True, "cancelled": found, "scope_sha256": scope_sha}, 200
