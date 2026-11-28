#!/usr/bin/env python3
"""Anvil v6 Pure-Core Paper Table Replication, 6-Class Error Taxonomy,
Receipt-Earned Ramanujan Honesty-Law Rungs, and 3-Leg Refactoring Gate.

Pure functional core: zero filesystem or network I/O, zero process spawning,
and zero unsafe serialization or dynamic code primitives.
"""
from __future__ import annotations

import hashlib
import html
import math
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

REPLICATION_AUDIT_SCHEMA = "anvil-replication-audit/v2"
ERROR_CLASSES: Tuple[str, ...] = (
    "EXACT_REPLICATION",
    "STOCHASTIC_SEED_MC_VARIANCE",
    "FLOAT_REDUCTION_TOLERANCE",
    "CACHED_PRECOMPUTED_BASELINE",
    "PIPELINE_DEPENDENCY_MISSING",
    "SPECIFICATION_FORMULA_MISMATCH",
)
HONESTY_RUNGS: Tuple[str, ...] = ("OBSERVED", "CACHED_BASELINE", "CORROBORATED", "CLAIMED", "REFUTED")
REFACTOR_GATE_VERDICTS: Tuple[str, ...] = ("APPROVED", "BLOCKED", "NOT_VETTED_CLAIMED")

_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_NUM_TOKEN_RE = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_WIN_USER_PATH_RE = re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+[^\\/\s\"'`<>|]+(?:[\\/]+[^\s\"'`<>|]*)?", re.IGNORECASE)
_POSIX_USER_PATH_RE = re.compile(r"/(?:Users|home)/[^/\s\"'`<>|]+(?:/[^\s\"'`<>|]*)?")
_SECRET_KV_RE = re.compile(
    r"""(?i)(["']?\b(?:anchor_token|api[_-]?key|secret(?:[_-]?key)?|access[_-]?token|auth[_-]?token|client[_-]?secret|private[_-]?key|password|passwd|token)\b["']?\s*[:=]\s*)(["']?)(?!\[REDACTED\])([^\s"',;`}]{4,})\2"""
)
_BEARER_TOKEN_RE = re.compile(r"(?i)\b(Bearer)\s+[A-Za-z0-9._\-+/=]{8,}")
_RAW_SECRET_PREFIX_RE = re.compile(
    r"\b(?:sk-[A-Za-z0-9_\-]{12,}|gh[pousr]_[A-Za-z0-9]{16,}|AIza[0-9A-Za-z_\-]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9\-]{8,}|glpat-[A-Za-z0-9_\-]{12,})\b"
)


def esc_html(val: Any) -> str:
    """Escape arbitrary untrusted string values for safe HTML text/attribute rendering."""
    return html.escape(str("" if val is None else val), quote=True)


def scrub_host_paths_and_secrets(text: Any, *, repo_root: str = "", cockpit_root: str = "") -> str:
    """Scrub host user paths, repository/cockpit absolute roots (case-insensitively), and credential tokens."""
    out = str("" if text is None else text)
    if not out:
        return ""
    for raw_root, tag in ((repo_root, "<repo>"), (cockpit_root, "<cockpit>")):
        clean_r = str(raw_root or "").strip().rstrip("\\/")
        if len(clean_r) >= 4:
            seen_vars: List[str] = []
            for variant in (clean_r, clean_r.replace("\\", "/"), clean_r.replace("/", "\\")):
                if variant and variant.lower() not in {v.lower() for v in seen_vars}:
                    seen_vars.append(variant)
                    out = re.compile(re.escape(variant), re.IGNORECASE).sub(lambda _m, t=tag: t, out)
    out = _WIN_USER_PATH_RE.sub("<host>/redacted-path", out)
    out = _POSIX_USER_PATH_RE.sub("<host>/redacted-path", out)
    out = _SECRET_KV_RE.sub(r"\1\2[REDACTED]\2", out)
    out = _BEARER_TOKEN_RE.sub(r"\1 [REDACTED]", out)
    return _RAW_SECRET_PREFIX_RE.sub("[REDACTED]", out)


def _clean_latex_text(raw: str) -> str:
    txt = re.sub(r"(?<!\\)%[^\n]*", "", raw or "").replace("$-$", "-").replace("$+$", "+").replace("\\pm", "±")
    txt = re.sub(r"\\(?:textbf|textit|textrm|texttt|emph|mathrm|mathbf)\s*\{([^{}]*)\}", r"\1", txt)
    txt = re.sub(r"\\[A-Za-z]+\*?", " ", txt).replace("{", " ").replace("}", " ").replace("$", "")
    return " ".join(txt.split()).strip()


def _normalize_metric_key(raw_key: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", _clean_latex_text(raw_key).lower()).strip("_") or "metric"


def _extract_first_float(cell_text: str) -> Optional[float]:
    cleaned = _clean_latex_text(cell_text).replace(",", "")
    if not cleaned or (cleaned.startswith("(") and cleaned.endswith(")")):
        return None
    m = _NUM_TOKEN_RE.search(cleaned)
    if not m:
        return None
    try:
        val = float(m.group(0))
        return val if math.isfinite(val) else None
    except ValueError:
        return None


def _safe_finite_float(raw_val: Any) -> Optional[float]:
    if isinstance(raw_val, bool) or raw_val is None:
        return None
    try:
        f = float(raw_val)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _infer_decimal_places(cell_text: str) -> Optional[int]:
    cleaned = _clean_latex_text(cell_text).replace(",", "")
    m = _NUM_TOKEN_RE.search(cleaned)
    if not m:
        return None
    tok = m.group(0)
    if "e" in tok.lower() or "." not in tok:
        return None
    return len(tok.split(".", 1)[1])


def _parse_latex_tabular_rows(tabular_body: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    cleaned = re.sub(r"\\(?:toprule|midrule|bottomrule|hline|cline\{[^{}]*\})", " ", tabular_body)
    raw_rows = [r.strip() for r in cleaned.split("\\\\") if r.strip()]
    headers: List[str] = []
    cells: List[Dict[str, Any]] = []
    metrics: Dict[str, Any] = {}
    for r_idx, row_str in enumerate(raw_rows):
        cols = [_clean_latex_text(c) for c in row_str.split("&")]
        if len(cols) < 2:
            continue
        if r_idx == 0 and all(_extract_first_float(c) is None for c in cols[1:]):
            headers = cols
            continue
        row_lbl = cols[0] or f"row_{r_idx + 1}"
        row_slug = _normalize_metric_key(row_lbl)
        for c_offset, raw_c in enumerate(cols[1:], start=1):
            val = _extract_first_float(raw_c)
            if val is None:
                continue
            col_lbl = headers[c_offset] if c_offset < len(headers) and headers[c_offset] else f"col_{c_offset}"
            mkey = row_slug if len(cols) == 2 else f"{row_slug}_{_normalize_metric_key(col_lbl)}"
            dec = _infer_decimal_places(raw_c)
            cells.append({"row_label": row_lbl, "col_label": col_lbl, "metric_key": mkey, "raw_value": raw_c, "numeric_value": val, "decimals": dec})
            metrics.setdefault(mkey, val)
    return cells, metrics


def _parse_markdown_pipe_tables(text: str, src_name: str, *, start_seq: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    lines = text.splitlines()
    idx, seq, last_heading = 0, start_seq, ""
    while idx < len(lines):
        ln = lines[idx].strip()
        if ln.startswith("#"):
            last_heading = ln.lstrip("#").strip()
            idx += 1
            continue
        if ln.startswith("|") and ln.endswith("|") and idx + 1 < len(lines) and lines[idx + 1].strip().startswith("|") and "-" in lines[idx + 1]:
            headers = [c.strip() for c in ln.strip("|").split("|")]
            idx += 2
            cells, metrics = [], {}
            while idx < len(lines) and lines[idx].strip().startswith("|"):
                cols = [c.strip() for c in lines[idx].strip().strip("|").split("|")]
                if len(cols) >= 2:
                    row_lbl = cols[0] or "row"
                    row_slug = _normalize_metric_key(row_lbl)
                    for c_i, raw_c in enumerate(cols[1:], start=1):
                        val = _extract_first_float(raw_c)
                        if val is not None:
                            col_lbl = headers[c_i] if c_i < len(headers) and headers[c_i] else f"col_{c_i}"
                            mkey = row_slug if len(cols) == 2 else f"{row_slug}_{_normalize_metric_key(col_lbl)}"
                            dec = _infer_decimal_places(raw_c)
                            cells.append({"row_label": row_lbl, "col_label": col_lbl, "metric_key": mkey, "raw_value": raw_c, "numeric_value": val, "decimals": dec})
                            metrics.setdefault(mkey, val)
                idx += 1
            if cells:
                seq += 1
                out.append({"table_id": f"tab:md_{seq}", "number": str(seq), "caption": last_heading or f"Markdown Table {seq}", "source_file": src_name, "cells": cells, "metrics": metrics})
            continue
        idx += 1
    return out


def parse_published_tables(tex_or_md_sources: Mapping[str, str]) -> List[Dict[str, Any]]:
    """Extract published Table metadata and numeric metric cells from LaTeX or Markdown sources."""
    tables: List[Dict[str, Any]] = []
    if not isinstance(tex_or_md_sources, Mapping):
        return tables
    table_seq = 0
    tex_table_re = re.compile(r"\\begin\{table\*?\}(.*?)\\end\{table\*?\}", re.DOTALL)
    tabular_re = re.compile(r"\\begin\{tabular\*?\}(?:\{[^{}]*\})?(?:\[[^\]]*\])?\{[^{}]*\}(.*?)\\end\{tabular\*?\}", re.DOTALL)
    caption_re = re.compile(r"\\caption(?:\[[^\]]*\])?\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", re.DOTALL)
    label_re = re.compile(r"\\label\s*\{\s*([^}\s]+)\s*\}")
    for src_name in sorted(tex_or_md_sources.keys()):
        no_comments = re.sub(r"(?<!\\)%[^\n]*", "", str(tex_or_md_sources[src_name] or ""))
        matched_spans: List[Tuple[int, int]] = []
        for tmatch in tex_table_re.finditer(no_comments):
            table_seq += 1
            matched_spans.append(tmatch.span())
            block = tmatch.group(1)
            cap_m, lbl_m, tab_m = caption_re.search(block), label_re.search(block), tabular_re.search(block)
            cells, metrics = _parse_latex_tabular_rows(tab_m.group(1) if tab_m else block)
            tables.append({
                "table_id": lbl_m.group(1).strip() if lbl_m else f"tab:table_{table_seq}",
                "number": str(table_seq),
                "caption": _clean_latex_text(cap_m.group(1)) if cap_m else f"Table {table_seq}",
                "source_file": str(src_name),
                "cells": cells,
                "metrics": metrics,
            })
        for smatch in tabular_re.finditer(no_comments):
            s_start, s_end = smatch.span()
            if any(a <= s_start and s_end <= b for a, b in matched_spans):
                continue
            table_seq += 1
            stem_slug = re.sub(r"[^a-z0-9_]+", "_", str(src_name).rsplit("/", 1)[-1].rsplit(".", 1)[0].lower()).strip("_")
            cells, metrics = _parse_latex_tabular_rows(smatch.group(1))
            tables.append({
                "table_id": f"tab:{stem_slug or f'table_{table_seq}'}",
                "number": str(table_seq),
                "caption": f"Table {table_seq} ({src_name})",
                "source_file": str(src_name),
                "cells": cells,
                "metrics": metrics,
            })
        tables.extend(_parse_markdown_pipe_tables(no_comments, str(src_name), start_seq=table_seq))
        table_seq = len(tables)
    return tables


def classify_error(
    published: Optional[float] = None,
    replicated: Optional[float] = None,
    *,
    abs_tol: float = 1e-6,
    float_tol: float = 1e-3,
    pub_decimals: Optional[int] = None,
    mc_se: Optional[float] = None,
    mc_sigma: float = 3.0,
    seed_span: Optional[Sequence[float]] = None,
    has_unseeded_rng: bool = False,
    used_cached_baseline: bool = False,
    missing_dependency: str = "",
    exit_code: int = 0,
    runtime_error: str = "",
    formula_mismatch: bool = False,
) -> str:
    """Deterministically classify a table/metric replication outcome into the 6-class taxonomy."""
    if missing_dependency or int(exit_code) != 0 or bool(str(runtime_error or "").strip()):
        return "PIPELINE_DEPENDENCY_MISSING"
    if used_cached_baseline:
        return "CACHED_PRECOMPUTED_BASELINE"
    pub_f, rep_f = _safe_finite_float(published), _safe_finite_float(replicated)
    if pub_f is None or rep_f is None:
        return "SPECIFICATION_FORMULA_MISMATCH"
    delta = abs(rep_f - pub_f)
    scale = max(abs(pub_f), abs(rep_f), 1e-12)
    eff_abs_tol = min(float(abs_tol), 0.005 * scale) if scale < 1e-3 else float(abs_tol)
    if delta <= eff_abs_tol and not formula_mismatch:
        return "EXACT_REPLICATION"
    if formula_mismatch:
        return "SPECIFICATION_FORMULA_MISMATCH"
    rel_float_tol = min(float(float_tol), max(eff_abs_tol, 0.05 * scale))
    eff_float_tol = max(rel_float_tol, 0.5 * (10.0 ** (-int(pub_decimals)))) if (pub_decimals is not None and 0 <= int(pub_decimals) <= 12) else rel_float_tol
    if delta <= eff_float_tol and not has_unseeded_rng:
        return "FLOAT_REDUCTION_TOLERANCE"
    if seed_span is not None and len(seed_span) >= 2:
        parsed_span = [_safe_finite_float(x) for x in seed_span]
        valid_span = [x for x in parsed_span if x is not None]
        if len(valid_span) >= 2:
            lo, hi = min(valid_span), max(valid_span)
            if (lo - eff_float_tol) <= pub_f <= (hi + eff_float_tol):
                return "STOCHASTIC_SEED_MC_VARIANCE"
    mc_se_f = _safe_finite_float(mc_se)
    max_allowed_se = max(0.25 * abs(pub_f), 0.05)
    if mc_se_f is not None and 0.0 < mc_se_f <= max_allowed_se and delta <= float(mc_sigma) * mc_se_f:
        return "STOCHASTIC_SEED_MC_VARIANCE"
    if has_unseeded_rng:
        return "STOCHASTIC_SEED_MC_VARIANCE"
    return "SPECIFICATION_FORMULA_MISMATCH"


def compare_metrics(
    published: Mapping[str, Any],
    replicated: Optional[Mapping[str, Any]],
    tolerances: Optional[Mapping[str, float]] = None,
    *,
    published_decimals: Optional[Mapping[str, Optional[int]]] = None,
    exit_code: int = 0,
    missing_dependency: str = "",
    runtime_error: str = "",
    used_cached_baseline: bool = False,
    has_unseeded_rng: bool = False,
    formula_mismatch: bool = False,
) -> Dict[str, Any]:
    """Compare published table metrics against live replicated outputs using the 6-class taxonomy."""
    tols = dict(tolerances or {})
    abs_tol, float_tol, mc_sigma = float(tols.get("abs_tol", 1e-6)), float(tols.get("float_tol", 1e-3)), float(tols.get("mc_sigma", 3.0))
    dec_map = dict(published_decimals or {})
    rep_map = dict(replicated or {}) if isinstance(replicated, Mapping) else {}
    norm_rep: Dict[str, Any] = {}
    for k, v in rep_map.items():
        norm_rep[str(k)] = v
        norm_rep.setdefault(_normalize_metric_key(str(k)), v)

    cell_results: List[Dict[str, Any]] = []
    matched_count = discrepancy_count = finite_contradictions = unprinted_cells = stochastic_matches = 0
    class_counts: Dict[str, int] = {}
    for raw_k, pub_entry in (published or {}).items():
        mkey = str(raw_k)
        pub_val = _safe_finite_float(pub_entry.get("value")) if isinstance(pub_entry, Mapping) else _safe_finite_float(pub_entry)
        if pub_val is None:
            continue
        p_dec = pub_entry.get("decimals") if isinstance(pub_entry, Mapping) and pub_entry.get("decimals") is not None else dec_map.get(mkey)
        pub_mc_se = _safe_finite_float(pub_entry.get("mc_se")) if isinstance(pub_entry, Mapping) else None
        mc_se_val = pub_mc_se
        rep_entry = norm_rep.get(mkey, norm_rep.get(_normalize_metric_key(mkey)))
        rep_val: Optional[float] = None
        seed_span: Optional[Sequence[float]] = None
        malformed_rep = False
        cell_cached, cell_unseeded, cell_formula = used_cached_baseline, has_unseeded_rng, formula_mismatch
        if isinstance(rep_entry, Mapping):
            if "value" in rep_entry and rep_entry.get("value") is not None:
                rep_val = _safe_finite_float(rep_entry.get("value"))
                if rep_val is None:
                    malformed_rep = True
            if isinstance(rep_entry.get("seed_span"), (list, tuple)):
                parsed_sp = [_safe_finite_float(x) for x in rep_entry["seed_span"]]
                seed_span = [x for x in parsed_sp if x is not None]
            cell_cached = bool(cell_cached or rep_entry.get("used_cached_baseline"))
            cell_unseeded = bool(cell_unseeded or rep_entry.get("has_unseeded_rng"))
            cell_formula = bool(cell_formula or rep_entry.get("formula_mismatch"))
        elif rep_entry is not None:
            rep_val = _safe_finite_float(rep_entry)
            if rep_val is None:
                malformed_rep = True

        if rep_val is None and not malformed_rep and int(exit_code) == 0 and not missing_dependency and not runtime_error and not cell_cached:
            err_cls = "PIPELINE_DEPENDENCY_MISSING"
            unprinted_cells += 1
        else:
            err_cls = classify_error(
                pub_val, rep_val, abs_tol=abs_tol, float_tol=float_tol, pub_decimals=p_dec if isinstance(p_dec, int) else None,
                mc_se=mc_se_val, mc_sigma=mc_sigma, seed_span=seed_span, has_unseeded_rng=cell_unseeded, used_cached_baseline=cell_cached,
                missing_dependency=missing_dependency, exit_code=exit_code, runtime_error=runtime_error, formula_mismatch=cell_formula,
            )
        delta = (rep_val - pub_val) if rep_val is not None else None
        is_stoch_match = err_cls == "STOCHASTIC_SEED_MC_VARIANCE" and not cell_unseeded and mc_se_val is not None
        is_match = err_cls in {"EXACT_REPLICATION", "FLOAT_REDUCTION_TOLERANCE"} or is_stoch_match
        if is_stoch_match:
            stochastic_matches += 1
        if rep_val is not None and not is_match and err_cls == "SPECIFICATION_FORMULA_MISMATCH":
            finite_contradictions += 1
        matched_count += int(is_match)
        discrepancy_count += int(not is_match)
        class_counts[err_cls] = class_counts.get(err_cls, 0) + 1
        cell_results.append({
            "metric_key": mkey, "published": pub_val, "replicated": rep_val,
            "delta": round(delta, 8) if delta is not None else None, "error_class": err_cls, "matched": is_match,
        })

    severity_rank = {
        "PIPELINE_DEPENDENCY_MISSING": 5, "SPECIFICATION_FORMULA_MISMATCH": 4, "STOCHASTIC_SEED_MC_VARIANCE": 3,
        "CACHED_PRECOMPUTED_BASELINE": 2, "FLOAT_REDUCTION_TOLERANCE": 1, "EXACT_REPLICATION": 0,
    }
    dominant = (
        max(class_counts.keys(), key=lambda c: (severity_rank.get(c, 0), class_counts[c]))
        if class_counts else ("PIPELINE_DEPENDENCY_MISSING" if (int(exit_code) != 0 or missing_dependency) else "EXACT_REPLICATION")
    )
    return {
        "total_cells": len(cell_results), "matched_cells": matched_count, "discrepancy_cells": discrepancy_count,
        "finite_contradiction_cells": finite_contradictions, "unprinted_cells": unprinted_cells,
        "stochastic_matched_cells": stochastic_matches,
        "dominant_error_class": dominant, "error_class_counts": class_counts, "cells": cell_results,
    }


def _rung_dict(rung: str, proposed: str, *, downgraded: bool, reason: str = "", inline_ref: str = "", verified: bool = False) -> Dict[str, Any]:
    return {
        "rung": rung, "proposed_rung": proposed, "downgraded": downgraded,
        "downgrade_reason": reason, "inline_ref": inline_ref, "receipt_verified": verified,
    }


def assign_rung(claim: Mapping[str, Any], receipts: Optional[Mapping[str, Any]], scope_sha256: str = "") -> Dict[str, Any]:
    """Assign an earned Ramanujan Honesty-Law rung strictly from verified runner receipts."""
    expected_sha = str(scope_sha256 or claim.get("scope_sha256") or "").strip().lower()
    proposed = str(claim.get("proposed_rung") or claim.get("rung") or "CLAIMED").strip().upper()
    citation_key = str(claim.get("receipt_id") or claim.get("citation") or claim.get("table_id") or claim.get("script") or "").strip()

    pool: Dict[str, Any] = {}
    if isinstance(receipts, Mapping):
        for k, v in receipts.items():
            if k == "runs" and isinstance(v, Mapping):
                for rk, rv in v.items():
                    pool[str(rk)] = rv
            elif isinstance(v, Mapping):
                pool[str(k)] = v
                if v.get("script"):
                    pool.setdefault(str(v["script"]), v)
                if v.get("table_id"):
                    pool.setdefault(str(v["table_id"]), v)

    matched_rec = pool.get(citation_key) if citation_key else None
    if not _HEX64_RE.fullmatch(expected_sha):
        return _rung_dict("CLAIMED", proposed, downgraded=(proposed != "CLAIMED"), reason="invalid_or_missing_scope_sha256")
    if not isinstance(matched_rec, Mapping):
        return _rung_dict("CLAIMED", proposed, downgraded=(proposed != "CLAIMED"), reason="missing_or_forged_receipt")
    if str(matched_rec.get("scope_sha256") or "").strip().lower() != expected_sha:
        return _rung_dict("CLAIMED", proposed, downgraded=(proposed != "CLAIMED"), reason="stale_scope_sha256_mismatch")
    if matched_rec.get("executed") is False or matched_rec.get("ran") is False:
        return _rung_dict("CLAIMED", proposed, downgraded=(proposed != "CLAIMED"), reason="receipt_not_executed")

    raw_ec = matched_rec.get("exit_code", 1)
    exit_code = int(raw_ec) if isinstance(raw_ec, (int, float)) and not isinstance(raw_ec, bool) else 1
    script_lbl = str(matched_rec.get("script") or citation_key or "runner").rsplit("/", 1)[-1]
    summary_val = str(matched_rec.get("output_summary") or matched_rec.get("metric_summary") or "exit=0").strip()[:80]
    inline_ref = f"({script_lbl}: {summary_val})"

    if bool(matched_rec.get("contradicts_claim") or matched_rec.get("refuted")) and exit_code == 0:
        return _rung_dict("REFUTED", proposed, downgraded=(proposed == "OBSERVED"), reason=("contradicted_by_replicated_metrics" if proposed == "OBSERVED" else ""), inline_ref=inline_ref, verified=True)
    if exit_code != 0:
        return _rung_dict("CLAIMED", proposed, downgraded=(proposed != "CLAIMED"), reason=f"nonzero_exit_code_{exit_code}")
    if bool(matched_rec.get("used_cached_baseline") or matched_rec.get("cached")) or matched_rec.get("error_class") == "CACHED_PRECOMPUTED_BASELINE":
        return _rung_dict("CACHED_BASELINE", proposed, downgraded=(proposed == "OBSERVED"), reason=("cached_precomputed_baseline" if proposed == "OBSERVED" else ""), inline_ref=inline_ref, verified=True)
    if matched_rec.get("comparison_unverified") is True:
        return _rung_dict("CLAIMED", proposed, downgraded=(proposed == "OBSERVED"), reason="no_published_metrics_compared", inline_ref="", verified=False)
    if proposed == "CORROBORATED" or bool(matched_rec.get("corroborated_only")):
        return _rung_dict("CORROBORATED", proposed, downgraded=False, inline_ref=inline_ref, verified=True)
    if proposed == "CLAIMED":
        return _rung_dict("CLAIMED", proposed, downgraded=False, inline_ref="", verified=False)
    return _rung_dict("OBSERVED", proposed, downgraded=False, inline_ref=inline_ref, verified=True)


def decide_refactor_gate(
    candidate: Mapping[str, Any],
    xval_receipt: Optional[Mapping[str, Any]],
    ramanujan_verdict: Optional[Mapping[str, Any]],
    phase_b_receipt: Optional[Mapping[str, Any]],
    scope_sha256: str = "",
    *,
    require_diff_bound_legs: bool = False,
) -> Dict[str, Any]:
    """Evaluate the 3-leg adversarial & mathematical refactoring gate (APPROVED / BLOCKED / NOT_VETTED_CLAIMED)."""
    expected_sha = str(scope_sha256 or candidate.get("scope_sha256") or "").strip().lower()
    cand_id = str(candidate.get("id") or candidate.get("candidate_id") or "").strip()
    cand_diff = str(candidate.get("diff") or "")
    actual_diff_sha = hashlib.sha256(cand_diff.encode("utf-8")).hexdigest() if cand_diff.strip() else ""
    block_reasons: List[str] = []

    if isinstance(ramanujan_verdict, Mapping):
        rv_status = str(ramanujan_verdict.get("verdict") or "").strip().upper()
        if (
            bool(ramanujan_verdict.get("wrong_side"))
            or str(ramanujan_verdict.get("target_side") or "").lower() in {"paper", "manuscript", "prose"}
            or rv_status in {"BLOCKED", "REJECTED", "WRONG_SIDE", "ZERO_IMPACT", "DEGRADES_FIT"}
            or ramanujan_verdict.get("code_defect_confirmed") is False
        ):
            block_reasons.append(str(ramanujan_verdict.get("reason") or "Ramanujan blocked wrong-side or zero-impact code edit."))
    if isinstance(xval_receipt, Mapping) and str(xval_receipt.get("verdict") or "").strip().upper() in {"BLOCKED", "REJECT", "REJECTED"}:
        block_reasons.append(str(xval_receipt.get("reason") or "Cross-family adversarial review rejected edit."))
    if isinstance(phase_b_receipt, Mapping):
        pb_status = str(phase_b_receipt.get("verdict") or "").strip().upper()
        if bool(phase_b_receipt.get("regression_detected") or phase_b_receipt.get("metric_degraded") or phase_b_receipt.get("zero_impact")) or pb_status in {"BLOCKED", "REJECTED", "REGRESSION"}:
            block_reasons.append(str(phase_b_receipt.get("reason") or "Phase-B scratch replay detected regression or zero impact."))
    if block_reasons:
        return {"verdict": "BLOCKED", "label": "Blocked by Adversarial Review", "bucket": "rejected", "reasons": block_reasons, "missing_legs": []}

    missing_legs: List[str] = []
    if not _HEX64_RE.fullmatch(expected_sha):
        missing_legs.append("valid_scope_sha256")

    leg1_ok = False
    if isinstance(xval_receipt, Mapping) and str(xval_receipt.get("scope_sha256") or "").lower() == expected_sha:
        fams = set(str(f).strip().lower() for f in (xval_receipt.get("families") or []) if str(f).strip()) if isinstance(xval_receipt.get("families"), (list, tuple, set)) else set()
        for fk in ("orchestrator_family", "validator_family", "seat1_family", "seat2_family"):
            if xval_receipt.get(fk):
                fams.add(str(xval_receipt[fk]).strip().lower())
        xv_cmap = xval_receipt.get("candidate_diff_sha256") if isinstance(xval_receipt.get("candidate_diff_sha256"), Mapping) else {}
        xv_dsha = str(xv_cmap.get(cand_id) or xval_receipt.get("diff_sha256") or "").strip().lower()
        xv_diff_ok = (bool(actual_diff_sha) and xv_dsha == actual_diff_sha) if (require_diff_bound_legs or xv_dsha) else True
        if xv_diff_ok and bool(xval_receipt.get("cross_family_attested", len(fams) >= 2)) and len(fams) >= 2 and str(xval_receipt.get("verdict") or "").strip().upper() in {"PASS", "APPROVED"}:
            leg1_ok = True
    if not leg1_ok:
        missing_legs.append("attested_2family_xval_receipt")

    ram_dsha = str(ramanujan_verdict.get("diff_sha256") or "").strip().lower() if isinstance(ramanujan_verdict, Mapping) else ""
    ram_diff_ok = (bool(actual_diff_sha) and ram_dsha == actual_diff_sha) if (require_diff_bound_legs or ram_dsha) else True
    leg2_ok = bool(
        isinstance(ramanujan_verdict, Mapping)
        and str(ramanujan_verdict.get("scope_sha256") or "").lower() == expected_sha
        and ram_diff_ok
        and bool(ramanujan_verdict.get("code_defect_confirmed"))
        and not bool(ramanujan_verdict.get("wrong_side"))
        and str(ramanujan_verdict.get("verdict") or "").strip().upper() in {"PASS", "APPROVED", "CODE_DEFECT_CONFIRMED"}
    )
    if not leg2_ok:
        missing_legs.append("ramanujan_code_defect_verdict")

    claimed_diff_sha = str(candidate.get("diff_sha256") or "").strip().lower()
    pb_diff_sha = str(phase_b_receipt.get("diff_sha256") or "").strip().lower() if isinstance(phase_b_receipt, Mapping) else ""
    diff_sha_verified = bool(
        actual_diff_sha
        and _HEX64_RE.fullmatch(actual_diff_sha)
        and (not claimed_diff_sha or claimed_diff_sha == actual_diff_sha)
        and pb_diff_sha == actual_diff_sha
    )
    raw_pb_ec = phase_b_receipt.get("exit_code", 1) if isinstance(phase_b_receipt, Mapping) else 1
    pb_ec = int(raw_pb_ec) if isinstance(raw_pb_ec, (int, float)) and not isinstance(raw_pb_ec, bool) else 1
    leg3_ok = bool(
        isinstance(phase_b_receipt, Mapping)
        and str(phase_b_receipt.get("scope_sha256") or "").lower() == expected_sha
        and diff_sha_verified
        and pb_ec == 0
        and bool(phase_b_receipt.get("metric_improved_or_preserved", False))
        and int(phase_b_receipt.get("regressions", 0)) == 0
        and not bool(phase_b_receipt.get("regression_detected"))
    )
    if not leg3_ok:
        missing_legs.append("phase_b_scratch_replay_receipt")

    if not missing_legs:
        return {
            "verdict": "APPROVED", "label": "Survived Adversarial Review", "bucket": "approved",
            "reasons": ["All 3 legs verified (2-family xval + Ramanujan code-defect check + scratch table replay)."], "missing_legs": [],
        }
    return {
        "verdict": "NOT_VETTED_CLAIMED", "label": "Not Vetted (Claimed)", "bucket": "not_vetted",
        "reasons": [f"Missing or unverified gate legs: {', '.join(missing_legs)}"], "missing_legs": missing_legs,
    }


def build_replication_report_bundle(
    *,
    scope_sha256: str,
    repo_name: str,
    paper_title: str = "",
    published_tables: Optional[Sequence[Mapping[str, Any]]] = None,
    replicator_cards: Optional[Sequence[Mapping[str, Any]]] = None,
    phase_a_receipts: Optional[Mapping[str, Any]] = None,
    claims: Optional[Sequence[Mapping[str, Any]]] = None,
    refactor_candidates: Optional[Sequence[Mapping[str, Any]]] = None,
    xval_receipt: Optional[Mapping[str, Any]] = None,
    ramanujan_verdicts: Optional[Mapping[str, Mapping[str, Any]]] = None,
    phase_b_receipts: Optional[Mapping[str, Mapping[str, Any]]] = None,
    repo_root: str = "",
    cockpit_root: str = "",
    require_diff_bound_legs: bool = False,
    trusted_claims_baseline: bool = True,
) -> Dict[str, Any]:
    """Assemble a 100% receipt-grounded Replication, Ramanujan & Vetted Refactoring Report v2 bundle."""
    clean_sha = str(scope_sha256 or "").strip().lower()
    short_sha = clean_sha[:8] if clean_sha else "unlocked"
    scrub = lambda s: scrub_host_paths_and_secrets(s, repo_root=repo_root, cockpit_root=cockpit_root)
    safe_repo = scrub(repo_name or "Repository")
    safe_paper = scrub(paper_title or safe_repo)

    receipts_map = dict(phase_a_receipts or {})
    has_runs = len(receipts_map) > 0
    ram_map, pb_map = dict(ramanujan_verdicts or {}), dict(phase_b_receipts or {})
    approved_fixes, rejected_fixes, not_vetted_fixes = [], [], []
    fix_by_target: Dict[str, Dict[str, Any]] = {}

    for idx, raw_cand in enumerate(refactor_candidates or [], start=1):
        if not isinstance(raw_cand, Mapping):
            continue
        raw_id_str = str(raw_cand.get("id") or f"fix-cand-{idx}").strip()
        cand_id = re.sub(r"[^a-z0-9_-]+", "-", raw_id_str.lower()).strip("-") or f"fix-cand-{idx}"
        # Leg 1, Leg 2, and Leg 3 derive strictly from authoritative top-level maps, never candidate-embedded dicts
        cand_xv = xval_receipt if isinstance(xval_receipt, Mapping) else None
        raw_rv = ram_map.get(cand_id) if cand_id in ram_map else ram_map.get(raw_id_str)
        raw_pb = pb_map.get(cand_id) if cand_id in pb_map else pb_map.get(raw_id_str)
        cand_rv = raw_rv if isinstance(raw_rv, Mapping) else None
        cand_pb = raw_pb if isinstance(raw_pb, Mapping) else None
        gate_res = decide_refactor_gate(raw_cand, cand_xv, cand_rv, cand_pb, scope_sha256=clean_sha, require_diff_bound_legs=require_diff_bound_legs)
        raw_diff_str = str(raw_cand.get("diff") or "")
        diff_txt = scrub(raw_diff_str)
        item_fx = {
            "id": cand_id, "title": scrub(raw_cand.get("title") or f"Candidate Refactoring #{idx}"),
            "where": scrub(raw_cand.get("where") or raw_cand.get("file") or "<repo>"),
            "summary": scrub(raw_cand.get("summary") or raw_cand.get("wrong") or ""),
            "diff": diff_txt, "diff_sha256": hashlib.sha256(raw_diff_str.encode("utf-8")).hexdigest() if raw_diff_str.strip() else "",
            "gate_verdict": gate_res["verdict"], "gate_label": gate_res["label"],
            "reasons": [scrub(r) for r in gate_res["reasons"]], "missing_legs": list(gate_res["missing_legs"]),
        }
        for tgt in (raw_cand.get("table_id"), raw_cand.get("target_ref"), raw_cand.get("id")):
            if tgt:
                fix_by_target.setdefault(str(tgt), item_fx)
        (approved_fixes if gate_res["verdict"] == "APPROVED" else (rejected_fixes if gate_res["verdict"] == "BLOCKED" else not_vetted_fixes)).append(item_fx)

    matrix_rows: List[Dict[str, Any]] = []
    rung_counts: Dict[str, int] = {r: 0 for r in HONESTY_RUNGS}
    total_cells = matched_cells = stochastic_total_matches = 0
    using_client_claims = bool(claims) and bool(trusted_claims_baseline)
    source_items: List[Mapping[str, Any]] = list(claims) if using_client_claims else (list(published_tables or []) or list(replicator_cards or []))
    if not source_items:
        source_items = [{"table_id": "scope_overview", "caption": f"Scoped Estimator & Manuscript Alignment ({safe_paper})", "metrics": {}}]

    for r_idx, item in enumerate(source_items, start=1):
        tid = str(item.get("table_id") or item.get("artifact_ref") or item.get("id") or f"item_{r_idx}")
        paper_desc = scrub(item.get("paper_summary") or item.get("caption") or item.get("title") or tid)
        code_ref = scrub(item.get("code_ref") or item.get("script") or item.get("source_file") or "Scoped module")
        # Never resolve arbitrary client `claims` by fallback `script` name to unrelated table receipts
        rec = (
            receipts_map.get(tid)
            if using_client_claims
            else (receipts_map.get(tid) or (receipts_map.get(str(item.get("script") or "")) if item.get("script") else None))
        )

        if not has_runs:
            rep_status, err_cls, discrepancy = "not yet run", "NOT_YET_RUN", False
            rung_info = assign_rung({"proposed_rung": "CLAIMED", "receipt_id": tid}, {}, scope_sha256=clean_sha)
        elif not isinstance(rec, Mapping):
            if isinstance(item.get("metrics"), Mapping):
                total_cells += sum(1 for pv in item["metrics"].values() if _safe_finite_float(pv.get("value") if isinstance(pv, Mapping) else pv) is not None)
            rep_status, err_cls = "unexecuted / missing receipt", "PIPELINE_DEPENDENCY_MISSING"
            rung_info = assign_rung({"proposed_rung": item.get("proposed_rung") or "CLAIMED", "receipt_id": tid}, {}, scope_sha256=clean_sha)
            discrepancy = True
        else:
            raw_ec = rec.get("exit_code", 1)
            rec_exit = int(raw_ec) if isinstance(raw_ec, (int, float)) and not isinstance(raw_ec, bool) else 1
            pub_metrics = item.get("metrics") if isinstance(item.get("metrics"), Mapping) else {}
            rep_metrics = rec.get("metrics") if isinstance(rec.get("metrics"), Mapping) else {}
            if isinstance(rep_metrics.get(tid), Mapping):
                rep_metrics = dict(rep_metrics[tid])

            rec_for_rung = dict(rec)
            rec_for_rung["exit_code"] = rec_exit
            if pub_metrics:
                pub_decs = {str(c.get("metric_key")): c.get("decimals") for c in (item.get("cells") or []) if isinstance(c, Mapping) and c.get("metric_key")}
                cmp_res = compare_metrics(
                    pub_metrics, rep_metrics, published_decimals=pub_decs, exit_code=rec_exit,
                    missing_dependency=str(rec.get("missing_module") or ""), runtime_error=str(rec.get("runtime_error") or ""),
                    used_cached_baseline=bool(rec.get("used_cached_baseline")), has_unseeded_rng=bool(rec.get("has_unseeded_rng")),
                    formula_mismatch=bool(rec.get("formula_mismatch")),
                )
                total_cells += cmp_res["total_cells"]
                matched_cells += cmp_res["matched_cells"]
                stochastic_total_matches += int(cmp_res.get("stochastic_matched_cells", 0))
                err_cls = cmp_res["dominant_error_class"]
                rep_status = f"{cmp_res['matched_cells']}/{cmp_res['total_cells']} cells matched · {err_cls}"
                discrepancy = cmp_res["discrepancy_cells"] > 0
                if cmp_res["total_cells"] <= 0:
                    err_cls = "EXECUTED_UNCOMPARED"
                    rep_status = f"0 numeric cells compared · {err_cls}"
                    discrepancy = True
                    rec_for_rung["comparison_unverified"] = True
                    eff_proposed = str(item.get("proposed_rung") or "CLAIMED")
                elif err_cls == "CACHED_PRECOMPUTED_BASELINE" or bool(rec.get("used_cached_baseline")):
                    rec_for_rung["used_cached_baseline"] = True
                    eff_proposed = str(item.get("proposed_rung") or "CACHED_BASELINE")
                elif rec_exit == 0 and int(cmp_res.get("finite_contradiction_cells", 0)) > 0:
                    rec_for_rung["contradicts_claim"] = True
                    eff_proposed = str(item.get("proposed_rung") or "REFUTED")
                elif rec_exit == 0 and cmp_res["matched_cells"] < cmp_res["total_cells"]:
                    rec_for_rung["comparison_unverified"] = True
                    eff_proposed = str(item.get("proposed_rung") or "CLAIMED")
                else:
                    if int(cmp_res.get("stochastic_matched_cells", 0)) > 0:
                        rec_for_rung["corroborated_only"] = True
                    eff_proposed = str(item.get("proposed_rung") or ("OBSERVED" if rec_exit == 0 else "CLAIMED"))
            else:
                miss_dep_s = str(rec.get("missing_module") or "")
                err_cls = (
                    "PIPELINE_DEPENDENCY_MISSING" if (miss_dep_s or rec_exit != 0)
                    else ("CACHED_PRECOMPUTED_BASELINE" if bool(rec.get("used_cached_baseline")) else "EXECUTED_UNCOMPARED")
                )
                rep_status = scrub(rec.get("output_summary") or f"exit={rec_exit} · {err_cls}")
                discrepancy = True
                rec_for_rung["comparison_unverified"] = True
                eff_proposed = str(item.get("proposed_rung") or "CLAIMED")

            rung_info = assign_rung(
                {"proposed_rung": eff_proposed, "receipt_id": tid},
                {tid: rec_for_rung}, scope_sha256=clean_sha,
            )
            if rung_info["rung"] == "REFUTED":
                discrepancy = True

        earned_rung = rung_info["rung"]
        rung_counts[earned_rung] = rung_counts.get(earned_rung, 0) + 1
        linked_fix = fix_by_target.get(tid) or (fix_by_target.get(str(item.get("jump_fix_id") or "")) if item.get("jump_fix_id") else None)
        if linked_fix is not None:
            discrepancy = True
        jump_lbl = (
            f"Jump to Approved Fix ({linked_fix['id']}) ↓" if linked_fix and linked_fix["gate_verdict"] == "APPROVED"
            else (f"See Why Adversarial Gate Blocked Edit ({linked_fix['id']}) ↓" if linked_fix and linked_fix["gate_verdict"] == "BLOCKED" else (f"Inspect Candidate ({linked_fix['id']}) ↓" if linked_fix else ""))
        )
        matrix_rows.append({
            "row_id": tid, "flag": bool(discrepancy), "paper_cell": paper_desc, "code_cell": code_ref,
            "replication_status": rep_status, "error_class": err_cls, "ramanujan_rung": earned_rung,
            "inline_ref": scrub(rung_info["inline_ref"]),
            "ramanujan_note": scrub(item.get("ramanujan_note") or ("Pending consented table run in isolated scratch." if not has_runs else f"Receipt-verified rung {earned_rung}.")),
            "downgraded": bool(rung_info["downgraded"]), "jump_id": linked_fix["id"] if linked_fix else "", "jump_label": jump_lbl,
        })

    summary_paragraphs = (
        [
            f"Fixed scope {short_sha} is locked for {safe_paper} ({len(matrix_rows)} table/claim row(s) mapped). Live replication is not yet run — confirm operator consent to run table scripts inside an isolated scratch copy.",
            "Every unverified row is stamped CLAIMED (not yet run) under Ramanujan's Honesty Law; OBSERVED rungs mint strictly from verified zero-exit runner receipts matching the locked 64-hex scope_sha256.",
        ] if not has_runs else [
            f"Completed replication audit on fixed scope {short_sha} for {safe_paper}: {matched_cells}/{total_cells} published metric cell(s) matched across {len(receipts_map)} runner receipt(s).",
            f"Ramanujan Honesty-Law ledger: {rung_counts['OBSERVED']} OBSERVED, {rung_counts['CACHED_BASELINE']} CACHED_BASELINE, {rung_counts['CORROBORATED']} CORROBORATED, {rung_counts['CLAIMED']} CLAIMED, {rung_counts['REFUTED']} REFUTED.",
            f"3-leg Refactoring Gate triaged {len(approved_fixes) + len(rejected_fixes) + len(not_vetted_fixes)} candidate issue(s): {len(approved_fixes)} APPROVED, {len(rejected_fixes)} BLOCKED (wrong-side or regressive), {len(not_vetted_fixes)} Not Vetted (Claimed).",
        ]
    )
    badges = [
        {"cls": "p-green" if has_runs and matched_cells == total_cells and total_cells > 0 and stochastic_total_matches == 0 else "p-amber", "icon": "/vendor/brand/anvil-icon.jpg", "text": "Replication: not yet run" if not has_runs else f"Replicated: {matched_cells}/{total_cells} Metric Cells Match"},
        {"cls": "p-ram", "icon": "/vendor/brand/ramanujan-icon.jpg", "text": f"Ramanujan: {rung_counts['OBSERVED']} OBSERVED · {rung_counts['CLAIMED']} CLAIMED" + (f" · {rung_counts['REFUTED']} REFUTED" if rung_counts["REFUTED"] else "")},
        {"cls": "p-ram", "icon": "/vendor/brand/gandalf-icon.jpg", "text": f"3-Leg Gate: {len(approved_fixes)} Approved · {len(rejected_fixes)} Blocked · {len(not_vetted_fixes)} Not Vetted"},
    ]
    return {
        "ok": True, "schema": REPLICATION_AUDIT_SCHEMA, "execution_state": "completed" if has_runs else "not_yet_run",
        "status_kind": "healthy" if has_runs else "empty-but-valid", "http_status": 200, "scope_sha256": clean_sha,
        "top_title": f"Replication, Ramanujan & Refactoring Report · {safe_repo} (Scope #{short_sha})",
        "doc_title": f"Replication, Ramanujan Math & Vetted Refactoring: {safe_paper}",
        "badges": badges, "summary_paragraphs": summary_paragraphs, "matrix": matrix_rows,
        "discrepancy_count": sum(1 for r in matrix_rows if r["flag"]), "rung_counts": rung_counts,
        "approved_fixes": approved_fixes, "rejected_fixes": rejected_fixes, "not_vetted_fixes": not_vetted_fixes,
    }


def render_deliverables_markdown(report_bundle: Mapping[str, Any], *, repo_root: str = "", cockpit_root: str = "") -> str:
    """Render a path- and secret-scrubbed Markdown dossier suitable for cockpit DELIVERABLES export."""
    scrub = lambda s: scrub_host_paths_and_secrets(s, repo_root=repo_root, cockpit_root=cockpit_root)
    lines: List[str] = [
        f"# {scrub(report_bundle.get('doc_title') or 'Replication & Ramanujan Report')}", "",
        f"- **Locked Scope SHA-256:** `{report_bundle.get('scope_sha256', '')}`",
        f"- **Run State:** `{report_bundle.get('execution_state', 'not_yet_run')}`", "",
        "## 1. Summary", "",
    ]
    for para in report_bundle.get("summary_paragraphs") or []:
        lines.extend([scrub(para), ""])
    lines.extend([
        "## 2. Paper ↔ Software ↔ Live Replication ↔ Ramanujan Matrix", "",
        "| Paper Section / Table | Software Implementation | Live Replication & Error Class | Ramanujan Rung |",
        "| :--- | :--- | :--- | :--- |",
    ])
    for r in report_bundle.get("matrix") or []:
        ref_s = f" `{r['inline_ref']}`" if r.get("inline_ref") else ""
        p_c, c_c = scrub(r.get("paper_cell") or "").replace("|", "\\|"), scrub(r.get("code_cell") or "").replace("|", "\\|")
        rep_c = scrub(r.get("replication_status") or "not yet run").replace("|", "\\|")
        ram_c = scrub(f"**{r.get('ramanujan_rung', 'CLAIMED')}**{ref_s} — {r.get('ramanujan_note', '')}").replace("|", "\\|")
        lines.append(f"| {p_c} | `{c_c}` | {rep_c} | {ram_c} |")
    lines.extend(["", "## 3. Adversarially Vetted Code Issues & Refactoring Gate", ""])
    for heading, key in (("Approved Surgical Code Refactorings", "approved_fixes"), ("Blocked / Wrong-Side Candidate Edits", "rejected_fixes"), ("Not Vetted (Claimed)", "not_vetted_fixes")):
        lines.append(f"### {heading}")
        items = list(report_bundle.get(key) or [])
        lines.extend([f"- **{fx['title']}** (`{fx['where']}`) — *{fx['gate_label']}*: {'; '.join(fx.get('reasons') or [])}" for fx in items] or ["- None."])
        lines.append("")
    return scrub("\n".join(lines).strip() + "\n")


__all__ = [
    "REPLICATION_AUDIT_SCHEMA", "ERROR_CLASSES", "HONESTY_RUNGS", "REFACTOR_GATE_VERDICTS",
    "esc_html", "scrub_host_paths_and_secrets", "parse_published_tables", "classify_error",
    "compare_metrics", "assign_rung", "decide_refactor_gate", "build_replication_report_bundle", "render_deliverables_markdown",
]
