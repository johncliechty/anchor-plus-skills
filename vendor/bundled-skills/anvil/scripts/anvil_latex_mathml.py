"""Bounded multi-file LaTeX tree resolver, billion-laughs-safe macro expander,
.aux label resolver, .bib / \\bibitem citation indexer, and safe MathML Core converter.
100% Python stdlib; zero shell/subprocess execution; zero outbound network I/O.
"""
from __future__ import annotations

import ctypes
import html
import os
import re
import stat
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

if os.name == "nt":
    import msvcrt

MAX_MACRO_COUNT = 2000
MAX_MACRO_BODY_CHARS = 4096
MAX_MACRO_DEPTH = 32
MAX_MACRO_OUTPUT_RATIO = 8
MAX_MACRO_OUTPUT_BYTES = 2_097_152
MAX_MACRO_WALL_MS = 250.0
MAX_BIB_BYTES = 2_097_152
MAX_EQUATION_INPUT_CHARS = 16_384
MAX_CONVERTED_MATHML_CHARS = 65_536
MAX_TEX_FILES = 64
MAX_TEX_INCLUDE_DEPTH = 16
MAX_TOTAL_TEX_BYTES = 8_388_608

_CMD_MATCH_RE = re.compile(r"\\([A-Za-z]+|.)")
_DELIM_MATCH_RE = re.compile(r"\\([{}|A-Za-z]+)")
_NUM_MATCH_RE = re.compile(r"\d+(?:\.\d+)?")

_GREEK_ENTITIES: Dict[str, str] = {
    "alpha": "&#x03B1;", "beta": "&#x03B2;", "gamma": "&#x03B3;", "delta": "&#x03B4;",
    "epsilon": "&#x03F5;", "varepsilon": "&#x03B5;", "zeta": "&#x03B6;", "eta": "&#x03B7;",
    "theta": "&#x03B8;", "vartheta": "&#x03D1;", "iota": "&#x03B9;", "kappa": "&#x03BA;",
    "lambda": "&#x03BB;", "mu": "&#x03BC;", "nu": "&#x03BD;", "xi": "&#x03BE;",
    "pi": "&#x03C0;", "rho": "&#x03C1;", "sigma": "&#x03C3;", "tau": "&#x03C4;",
    "upsilon": "&#x03C5;", "phi": "&#x03D5;", "varphi": "&#x03C6;", "chi": "&#x03C7;",
    "psi": "&#x03C8;", "omega": "&#x03C9;", "Gamma": "&#x0393;", "Delta": "&#x0394;",
    "Theta": "&#x0398;", "Lambda": "&#x039B;", "Xi": "&#x039E;", "Pi": "&#x03A0;",
    "Sigma": "&#x03A3;", "Upsilon": "&#x03A5;", "Phi": "&#x03A6;", "Psi": "&#x03A8;",
    "Omega": "&#x03A9;", "ell": "&#x2113;", "partial": "&#x2202;", "nabla": "&#x2207;",
    "infty": "&#x221E;", "forall": "&#x2200;", "exists": "&#x2203;",
}
_OP_ENTITIES: Dict[str, str] = {
    "sum": "&#x2211;", "prod": "&#x220F;", "int": "&#x222B;", "in": "&#x2208;",
    "notin": "&#x2209;", "subset": "&#x2282;", "subseteq": "&#x2286;", "cdot": "&#x22C5;",
    "cdots": "&#x22EF;", "ldots": "&#x2026;", "dots": "&#x2026;", "times": "&#x00D7;",
    "otimes": "&#x2297;", "oplus": "&#x2295;", "leq": "&#x2264;", "le": "&#x2264;",
    "geq": "&#x2265;", "ge": "&#x2265;", "neq": "&#x2260;", "ne": "&#x2260;",
    "approx": "&#x2248;", "sim": "&#x223C;", "equiv": "&#x2261;", "propto": "&#x221D;",
    "to": "&#x2192;", "rightarrow": "&#x2192;", "leftarrow": "&#x2190;",
    "Rightarrow": "&#x21D2;", "mapsto": "&#x21A6;", "pm": "&#x00B1;", "mid": "|",
}
_FONT_WRAPPERS = {
    "bm", "boldsymbol", "mathbf", "mathcal", "mathbb", "mathrm", "mathsf", "mathtt",
    "textit", "textbf", "textrm", "text", "operatorname", "hat", "widehat", "tilde",
    "widetilde", "bar", "overline", "underline", "vec", "dot",
}
_STD_FUNCS = {
    "exp", "log", "ln", "sin", "cos", "tan", "tanh", "min", "max", "sup", "inf",
    "arg", "argmin", "argmax", "det", "logdet", "diag", "tr", "Pr", "Cov", "Var", "softmax",
}


class AnvilLatexSecurityError(ValueError):
    """Raised when a LaTeX child reference attempts UNC, drive, symlink, or root escape."""

    def __init__(self, code: str, message: str, *, candidate: str = "") -> None:
        super().__init__(message)
        self.error_code = code
        self.candidate = candidate


def _is_reparse_or_symlink(p: Path) -> bool:
    try:
        st = os.lstat(p)
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = int(getattr(st, "st_file_attributes", 0) or 0)
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _is_within_boundary(cand: Path, bound_res: Path) -> bool:
    try:
        c_norm = os.path.normcase(os.path.abspath(os.fspath(cand)))
        b_norm = os.path.normcase(os.path.abspath(os.fspath(bound_res)))
        return os.path.commonpath([c_norm, b_norm]) == b_norm
    except ValueError:
        return False


def _read_contained_bytes(fp: Path, boundary: Path, max_bytes: int = 8_388_608) -> bytes:
    """Open file without pre-resolving symlinks and verify final OS handle path stays strictly inside `boundary`."""
    bound_res = boundary.resolve()
    fp_abs = Path(os.path.abspath(os.fspath(fp)))
    if not _is_within_boundary(fp_abs, bound_res):
        raise AnvilLatexSecurityError("PATH_ESCAPE_REFUSED", "Target escapes allowed root.", candidate=fp.name)
    rel_parts = Path(os.path.relpath(os.fspath(fp_abs), os.fspath(bound_res))).parts
    cur = bound_res
    for part in rel_parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise AnvilLatexSecurityError("PATH_ESCAPE_REFUSED", "Parent traversal refused.", candidate=part)
        cur = cur / part
        if _is_reparse_or_symlink(cur):
            raise AnvilLatexSecurityError("PATH_ESCAPE_REFUSED", "Symlink or junction refused.", candidate=part)
    open_flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
    raw_fd = os.open(os.fspath(fp_abs), open_flags)
    with os.fdopen(raw_fd, "rb") as fh:
        if os.name == "nt":
            handle = msvcrt.get_osfhandle(fh.fileno())
            buf = ctypes.create_unicode_buffer(2048)
            n = ctypes.windll.kernel32.GetFinalPathNameByHandleW(handle, buf, 2048, 0)
            if n <= 0 or n >= 2048:
                raise AnvilLatexSecurityError("PATH_ESCAPE_REFUSED", "Unable to attest file handle path.", candidate=fp.name)
            raw_final = buf.value
            if raw_final.startswith("\\\\?\\UNC\\"):
                raise AnvilLatexSecurityError("PATH_ESCAPE_REFUSED", "UNC handle target refused.", candidate=fp.name)
            if raw_final.startswith("\\\\?\\"):
                raw_final = raw_final[4:]
            if not _is_within_boundary(Path(raw_final), bound_res):
                raise AnvilLatexSecurityError("PATH_ESCAPE_REFUSED", "Post-open handle escaped boundary.", candidate=fp.name)
        data = fh.read(max_bytes + 1)
    if len(data) > max_bytes:
        return data[:max_bytes]
    return data


def _strip_tex_comments(text: str) -> str:
    out_lines: List[str] = []
    for ln in text.splitlines():
        i = 0
        n = len(ln)
        while i < n:
            if ln[i] == "%":
                bs = 0
                j = i - 1
                while j >= 0 and ln[j] == "\\":
                    bs += 1
                    j -= 1
                if bs % 2 == 0:
                    ln = ln[:i]
                    break
            i += 1
        out_lines.append(ln)
    return "\n".join(out_lines)


def _extract_braced_strict(s: str, open_idx: int, *, max_scan_chars: int = 65536) -> Tuple[str, int, bool]:
    if open_idx >= len(s) or s[open_idx] != "{":
        return "", open_idx, False
    depth = 0
    i = open_idx
    limit = min(len(s), open_idx + max(2, int(max_scan_chars)) + 2)
    while i < limit:
        ch = s[i]
        if ch == "\\":
            i += 2
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return s[open_idx + 1 : i], i + 1, True
        i += 1
    return "", limit, False


def _extract_braced(s: str, open_idx: int, *, max_scan_chars: int = 65536) -> Tuple[str, int]:
    body, nxt, closed = _extract_braced_strict(s, open_idx, max_scan_chars=max_scan_chars)
    if closed:
        return body, nxt
    end_fb = min(len(s), open_idx + max_scan_chars)
    return s[open_idx + 1 : end_fb], end_fb


def validate_safe_latex_ref(raw_ref: str) -> str:
    ref = (raw_ref or "").strip().strip('"').strip("'")
    if not ref or "\x00" in ref:
        return ""
    if ":" in ref or ref.startswith(("\\\\", "//", "/", "\\")):
        raise AnvilLatexSecurityError(
            "PATH_ESCAPE_REFUSED",
            f"Rooted, drive-qualified, or UNC LaTeX reference refused: {ref!r}",
            candidate=ref,
        )
    norm_slash = ref.replace("\\", "/")
    if norm_slash.startswith("/"):
        raise AnvilLatexSecurityError("PATH_ESCAPE_REFUSED", f"Rooted reference refused: {ref!r}", candidate=ref)
    return norm_slash


def _resolve_child_candidate(
    raw_ref: str,
    cur_dir: Path,
    paper_root: Path,
    allowed_root: Path,
    suffixes: Sequence[str],
) -> Optional[Path]:
    clean_ref = validate_safe_latex_ref(raw_ref)
    if not clean_ref:
        return None
    if any(pt.startswith(".") or pt.lower() in {"node_modules", "__pycache__"} for pt in Path(clean_ref).parts if pt not in (".", "..")):
        raise AnvilLatexSecurityError("PATH_ESCAPE_REFUSED", f"Dot-directory or internal reference refused: {clean_ref!r}", candidate=clean_ref)
    bound_res = allowed_root.resolve()
    escaped = False
    for base_d in (cur_dir, paper_root):
        for suf in suffixes:
            cand = Path(os.path.abspath(os.path.normpath(str(base_d / f"{clean_ref}{suf}"))))
            if not _is_within_boundary(cand, bound_res):
                escaped = True
                continue
            rel_pts = Path(os.path.relpath(os.fspath(cand), os.fspath(bound_res))).parts
            cur = bound_res
            for pt in rel_pts:
                if pt in ("", "."):
                    continue
                cur = cur / pt
                if _is_reparse_or_symlink(cur):
                    raise AnvilLatexSecurityError("PATH_ESCAPE_REFUSED", f"Symlink/junction child refused: {clean_ref!r}", candidate=clean_ref)
            if cand.is_file():
                return cand
    if escaped:
        raise AnvilLatexSecurityError("PATH_ESCAPE_REFUSED", f"Child path escapes workspace root: {clean_ref!r}", candidate=clean_ref)
    return None


def parse_macros_from_tex(
    clean_tex: str,
    macro_table: Optional[Dict[str, Dict[str, Any]]] = None,
    *,
    wall_budget_ms: float = MAX_MACRO_WALL_MS,
) -> Dict[str, Dict[str, Any]]:
    tbl: Dict[str, Dict[str, Any]] = dict(macro_table) if macro_table else {}
    t0 = time.perf_counter()
    cmd_re = re.compile(r"\\(newcommand|renewcommand|providecommand|DeclareMathOperator)\*?\s*(?:\{\\([A-Za-z@]+)\}|\\([A-Za-z@]+))")
    for m in cmd_re.finditer(clean_tex):
        if len(tbl) >= MAX_MACRO_COUNT or (time.perf_counter() - t0) * 1000.0 > wall_budget_ms:
            break
        kind = m.group(1)
        name = m.group(2) or m.group(3)
        pos = m.end()
        while pos < len(clean_tex) and clean_tex[pos].isspace():
            pos += 1
        nargs = 0
        opt_default: Optional[str] = None
        if kind != "DeclareMathOperator" and pos < len(clean_tex) and clean_tex[pos] == "[":
            end_b = clean_tex.find("]", pos + 1, pos + 16)
            if end_b != -1 and clean_tex[pos + 1 : end_b].strip().isdigit():
                nargs = min(9, int(clean_tex[pos + 1 : end_b].strip()))
                pos = end_b + 1
                while pos < len(clean_tex) and clean_tex[pos].isspace():
                    pos += 1
                if pos < len(clean_tex) and clean_tex[pos] == "[":
                    end_opt = clean_tex.find("]", pos + 1, pos + 512)
                    if end_opt != -1:
                        opt_default = clean_tex[pos + 1 : end_opt]
                        pos = end_opt + 1
        while pos < len(clean_tex) and clean_tex[pos].isspace():
            pos += 1
        if pos < len(clean_tex) and clean_tex[pos] == "{":
            body, _, closed = _extract_braced_strict(clean_tex, pos, max_scan_chars=MAX_MACRO_BODY_CHARS)
            if not closed or len(body) > MAX_MACRO_BODY_CHARS:
                continue
            if kind == "DeclareMathOperator":
                body = f"\\operatorname{{{body}}}"
            if re.search(rf"\\{re.escape(name)}(?![A-Za-z@])", body) is None:
                tbl[name] = {"nargs": nargs, "opt_default": opt_default, "body": body}
    def_re = re.compile(r"\\def\\([A-Za-z@]+)\s*\{")
    for dm in def_re.finditer(clean_tex):
        if len(tbl) >= MAX_MACRO_COUNT or (time.perf_counter() - t0) * 1000.0 > wall_budget_ms:
            break
        dname = dm.group(1)
        body, _, closed = _extract_braced_strict(clean_tex, dm.end() - 1, max_scan_chars=MAX_MACRO_BODY_CHARS)
        if not closed or len(body) > MAX_MACRO_BODY_CHARS:
            continue
        if dname not in tbl and re.search(rf"\\{re.escape(dname)}(?![A-Za-z@])", body) is None:
            tbl[dname] = {"nargs": 0, "opt_default": None, "body": body}
    return tbl


def expand_latex_macros_bounded(
    expr: str,
    macro_table: Dict[str, Dict[str, Any]],
    *,
    max_depth: int = MAX_MACRO_DEPTH,
    max_output_ratio: int = MAX_MACRO_OUTPUT_RATIO,
    max_output_bytes: int = MAX_MACRO_OUTPUT_BYTES,
    wall_budget_ms: float = MAX_MACRO_WALL_MS,
) -> Tuple[str, Dict[str, Any]]:
    """Expand user LaTeX macros safely; halts in <= wall_budget_ms and pre-checks single-pass #k size."""
    if not expr or not macro_table:
        return expr, {"macro_expansion_capped": False, "depth_used": 0}
    try:
        orig_bytes = max(256, len(expr.encode("utf-8", errors="replace")))
        byte_cap = min(int(max_output_bytes), orig_bytes * max(1, int(max_output_ratio)))
        t0 = time.perf_counter()
        cur = expr
        capped_reason = ""
        depth_used = 0
        tok_re = re.compile(r"\\([A-Za-z@]+)")
        arg_tok_re = re.compile(r"##|#([1-9])")

        for depth in range(1, max(1, int(max_depth)) + 1):
            if (time.perf_counter() - t0) * 1000.0 > wall_budget_ms:
                capped_reason = "wall_budget_exceeded"
                break
            changed = False
            pieces: List[str] = []
            out_bytes = 0
            pos = 0
            n = len(cur)
            while pos < n:
                if (time.perf_counter() - t0) * 1000.0 > wall_budget_ms:
                    capped_reason = "wall_budget_exceeded"
                    break
                m = tok_re.search(cur, pos)
                if not m:
                    rem = cur[pos:]
                    out_bytes += len(rem.encode("utf-8", errors="replace"))
                    if out_bytes > byte_cap:
                        capped_reason = "output_cap_exceeded"
                        break
                    pieces.append(rem)
                    break
                prefix = cur[pos : m.start()]
                pieces.append(prefix)
                out_bytes += len(prefix.encode("utf-8", errors="replace"))
                if out_bytes > byte_cap:
                    capped_reason = "output_cap_exceeded"
                    break
                mname = m.group(1)
                spec = macro_table.get(mname)
                if spec is None:
                    raw_m = m.group(0)
                    pieces.append(raw_m)
                    out_bytes += len(raw_m.encode("utf-8", errors="replace"))
                    pos = m.end()
                    continue
                changed = True
                arg_pos = m.end()
                nargs = int(spec.get("nargs") or 0)
                args_vals: List[str] = []
                if spec.get("opt_default") is not None and nargs >= 1:
                    ws = arg_pos
                    while ws < n and cur[ws].isspace():
                        ws += 1
                    if ws < n and cur[ws] == "[":
                        eb = cur.find("]", ws + 1, ws + MAX_MACRO_BODY_CHARS)
                        if eb != -1:
                            args_vals.append(cur[ws + 1 : eb])
                            arg_pos = eb + 1
                        else:
                            args_vals.append(str(spec["opt_default"]))
                    else:
                        args_vals.append(str(spec["opt_default"]))
                while len(args_vals) < nargs:
                    while arg_pos < n and cur[arg_pos].isspace():
                        arg_pos += 1
                    if arg_pos < n and cur[arg_pos] == "{":
                        aval, arg_pos, ok_br = _extract_braced_strict(cur, arg_pos, max_scan_chars=byte_cap)
                        if not ok_br:
                            capped_reason = "output_cap_exceeded"
                            break
                        args_vals.append(aval)
                    elif arg_pos < n:
                        args_vals.append(cur[arg_pos])
                        arg_pos += 1
                    else:
                        args_vals.append("")
                if capped_reason:
                    break
                raw_body = str(spec.get("body") or "")
                proj_bytes = len(raw_body.encode("utf-8", errors="replace"))
                arg_byte_lens = [len(av.encode("utf-8", errors="replace")) for av in args_vals]
                for am in arg_tok_re.finditer(raw_body):
                    if am.group(0) == "##":
                        proj_bytes -= 1
                    else:
                        idx_a = int(am.group(1))
                        if 1 <= idx_a <= len(arg_byte_lens):
                            proj_bytes += arg_byte_lens[idx_a - 1] - 2
                if out_bytes + max(0, proj_bytes) > byte_cap:
                    capped_reason = "output_cap_exceeded"
                    break
                repl = arg_tok_re.sub(
                    lambda am: "#" if am.group(0) == "##" else (args_vals[int(am.group(1)) - 1] if int(am.group(1)) <= len(args_vals) else am.group(0)),
                    raw_body,
                )
                out_bytes += len(repl.encode("utf-8", errors="replace"))
                if out_bytes > byte_cap:
                    capped_reason = "output_cap_exceeded"
                    break
                pieces.append(repl)
                pos = arg_pos
            if capped_reason:
                break
            nxt = "".join(pieces)
            if not changed or nxt == cur:
                cur = nxt
                break
            cur = nxt
            depth_used = depth
        else:
            if any(m.group(1) in macro_table for m in tok_re.finditer(cur)):
                capped_reason = "max_depth_exceeded"

        if capped_reason:
            return expr, {"macro_expansion_capped": True, "reason": capped_reason, "depth_used": depth_used, "badge": "MACRO_EXPANSION_CAPPED"}
        return cur, {"macro_expansion_capped": False, "depth_used": depth_used}
    except (MemoryError, RecursionError):
        return expr, {"macro_expansion_capped": True, "reason": "memory_or_recursion_cap", "depth_used": 0, "badge": "MACRO_EXPANSION_CAPPED"}


def parse_aux_labels(aux_paths: Sequence[Path], allowed_root: Path) -> Dict[str, str]:
    labels: Dict[str, str] = {}
    lbl_re = re.compile(r"\\newlabel\{([^{}]+)\}\{\{([^{}]*)\}")
    for ap in aux_paths:
        if _is_reparse_or_symlink(ap) or not ap.is_file():
            continue
        try:
            txt = _read_contained_bytes(ap, allowed_root, max_bytes=1_048_576).decode("utf-8", errors="replace")
        except (OSError, AnvilLatexSecurityError):
            continue
        for m in lbl_re.finditer(txt):
            k, num = m.group(1).strip(), m.group(2).strip()
            if k and num:
                labels[k] = num
    return labels


def _parse_bib_content_linear(raw_bib: str, *, wall_budget_ms: float = 200.0, max_entries: int = 256) -> Dict[str, Dict[str, Any]]:
    entries: Dict[str, Dict[str, Any]] = {}
    hdr_re = re.compile(r"@([A-Za-z]+)\s*\{\s*([^,\s{}]+)\s*,")
    t0 = time.perf_counter()
    pos = 0
    n = len(raw_bib)
    while pos < n and len(entries) < max_entries:
        if (time.perf_counter() - t0) * 1000.0 > wall_budget_ms:
            break
        hm = hdr_re.search(raw_bib, pos)
        if not hm:
            break
        etype = hm.group(1).lower()
        ckey = hm.group(2).strip()
        open_brace = raw_bib.find("{", hm.start())
        body, next_pos = _extract_braced(raw_bib, open_brace, max_scan_chars=16_384)
        pos = max(next_pos, hm.end())
        if etype in ("comment", "preamble", "string"):
            continue
        inner = body[body.find(",") + 1 :] if "," in body else ""
        fields: Dict[str, str] = {}
        fpos = 0
        in_len = len(inner)
        while fpos < in_len:
            if (time.perf_counter() - t0) * 1000.0 > wall_budget_ms:
                break
            while fpos < in_len and (inner[fpos].isspace() or inner[fpos] == ","):
                fpos += 1
            if fpos >= in_len:
                break
            id_start = fpos
            while fpos < in_len and (inner[fpos].isalnum() or inner[fpos] in "_-"):
                fpos += 1
            if fpos == id_start:
                nxt_c = inner.find(",", fpos + 1)
                if nxt_c == -1:
                    break
                fpos = nxt_c + 1
                continue
            fname = inner[id_start:fpos].lower()
            while fpos < in_len and inner[fpos].isspace():
                fpos += 1
            if fpos >= in_len or inner[fpos] != "=":
                nxt_c = inner.find(",", fpos)
                if nxt_c == -1:
                    break
                fpos = nxt_c + 1
                continue
            vpos = fpos + 1
            while vpos < in_len and inner[vpos].isspace():
                vpos += 1
            if vpos >= in_len:
                break
            if inner[vpos] == "{":
                fval, fpos = _extract_braced(inner, vpos, max_scan_chars=8_192)
            elif inner[vpos] == '"':
                end_q = inner.find('"', vpos + 1)
                while end_q > 0 and inner[end_q - 1] == "\\":
                    end_q = inner.find('"', end_q + 1)
                if end_q == -1:
                    fval, fpos = inner[vpos + 1 :], in_len
                else:
                    fval, fpos = inner[vpos + 1 : end_q], end_q + 1
            else:
                end_c = inner.find(",", vpos)
                if end_c == -1:
                    fval, fpos = inner[vpos:].strip(), in_len
                else:
                    fval, fpos = inner[vpos:end_c].strip(), end_c + 1
            clean_v = re.sub(r"\s+", " ", fval.replace("{", "").replace("}", "")).strip()
            fields[fname] = clean_v

        doi = fields.get("doi", "").strip()
        doi = re.sub(r"^https?://(?:dx\.)?doi\.org/", "", doi, flags=re.IGNORECASE).strip()
        eprint = fields.get("eprint", "") or fields.get("arxiv", "")
        if not eprint and "arxiv.org/abs/" in fields.get("url", "").lower():
            eprint = fields["url"].split("arxiv.org/abs/", 1)[1].split("?")[0].strip("/")
        eprint = re.sub(r"^arxiv:", "", eprint, flags=re.IGNORECASE).strip()
        pmid = fields.get("pmid", "").strip()
        year_m = re.search(r"\b(19|20)\d{2}\b", fields.get("year", ""))
        entries[ckey] = {
            "cite_key": ckey,
            "entry_type": etype,
            "title": fields.get("title", ckey),
            "author": fields.get("author", ""),
            "year": int(year_m.group(0)) if year_m else None,
            "venue": fields.get("journal") or fields.get("booktitle") or fields.get("publisher") or "",
            "doi": doi,
            "arxiv": eprint,
            "pmid": pmid,
            "posture": "MANUSCRIPT_CITED",
        }
    return entries


def normalize_latex_math_symbols(expr: str, macro_table: Optional[Dict[str, Dict[str, Any]]] = None) -> List[str]:
    expanded = expand_latex_macros_bounded(expr, macro_table or {})[0] if macro_table else expr
    s = re.sub(r"\\(?:bm|boldsymbol|mathbf|mathcal|mathbb|mathrm|hat|widehat|tilde|widetilde|bar|vec)\s*\{([^{}]*)\}", r" \1 ", expanded)
    bs_cmds = re.findall(r"\\([A-Za-z]+)", s)
    plain = re.sub(r"\\[A-Za-z]+", " ", s)
    ident_words = re.findall(r"[A-Za-z][A-Za-z0-9_]*", plain)
    keep: List[str] = []
    skip = _FONT_WRAPPERS | {"left", "right", "big", "Big", "bigg", "Bigg", "frac", "dfrac", "tfrac", "begin", "end", "quad", "qquad"}
    for tok in bs_cmds + ident_words:
        low = tok.strip("_").lower()
        if low and low not in skip and low not in keep:
            keep.append(low)
    return keep


def _convert_tex_tokens_to_mathml(s: str, depth: int = 0) -> Tuple[str, bool]:
    if depth > 14 or len(s) > MAX_EQUATION_INPUT_CHARS:
        return f"<mtext>{html.escape(s[:600])}</mtext>", False
    out: List[str] = []
    out_chars = 0
    i = 0
    n = len(s)
    ok_all = True

    def _read_unit(pos: int, u_depth: int) -> Tuple[str, int, bool]:
        if u_depth > 14 or out_chars > MAX_CONVERTED_MATHML_CHARS:
            return f"<mtext>{html.escape(s[pos : min(n, pos + 120)])}</mtext>", n, False
        while pos < n and s[pos].isspace():
            pos += 1
        if pos >= n:
            return "<mrow></mrow>", pos, True
        if s[pos] == "{":
            grp, npos = _extract_braced(s, pos, max_scan_chars=MAX_EQUATION_INPUT_CHARS)
            inner_ml, ok_u = _convert_tex_tokens_to_mathml(grp, u_depth + 1)
            return f"<mrow>{inner_ml}</mrow>", npos, ok_u
        if s[pos] == "\\":
            cm = _CMD_MATCH_RE.match(s, pos)
            if not cm:
                return f"<mo>{html.escape(s[pos])}</mo>", pos + 1, True
            cname = cm.group(1)
            npos = cm.end()
            if cname in ("frac", "dfrac", "tfrac"):
                num_ml, npos, ok1 = _read_unit(npos, u_depth + 1)
                den_ml, npos, ok2 = _read_unit(npos, u_depth + 1)
                return f"<mfrac>{num_ml}{den_ml}</mfrac>", npos, (ok1 and ok2)
            if cname == "sqrt":
                ws = npos
                while ws < n and s[ws].isspace():
                    ws += 1
                if ws < n and s[ws] == "[":
                    eb = s.find("]", ws + 1, min(n, ws + 256))
                    if eb != -1:
                        deg_ml, ok_d = _convert_tex_tokens_to_mathml(s[ws + 1 : eb], u_depth + 1)
                        rad_ml, npos, ok_r = _read_unit(eb + 1, u_depth + 1)
                        return f"<mroot>{rad_ml}<mrow>{deg_ml}</mrow></mroot>", npos, (ok_d and ok_r)
                rad_ml, npos, ok_r = _read_unit(npos, u_depth + 1)
                return f"<msqrt>{rad_ml}</msqrt>", npos, ok_r
            if cname in _FONT_WRAPPERS:
                if cname in ("text", "textrm", "textbf", "textit") and npos < n and s[npos] == "{":
                    raw_t, end_t = _extract_braced(s, npos, max_scan_chars=MAX_EQUATION_INPUT_CHARS)
                    return f"<mtext>{html.escape(raw_t)}</mtext>", end_t, True
                u_ml, npos, ok_w = _read_unit(npos, u_depth + 1)
                if cname in ("hat", "widehat"):
                    return f"<mover>{u_ml}<mo>^</mo></mover>", npos, ok_w
                if cname in ("tilde", "widetilde"):
                    return f"<mover>{u_ml}<mo>~</mo></mover>", npos, ok_w
                if cname in ("bar", "overline"):
                    return f"<mover>{u_ml}<mo>&#x00AF;</mo></mover>", npos, ok_w
                return u_ml, npos, ok_w
            if cname in ("left", "right", "big", "Big", "bigg", "Bigg"):
                while npos < n and s[npos].isspace():
                    npos += 1
                if npos < n:
                    if s[npos] == "\\":
                        dm = _DELIM_MATCH_RE.match(s, npos)
                        if dm:
                            dval = dm.group(1)
                            disp = {"{": "{", "}": "}", "|": "&#x2016;", "langle": "&#x27E8;", "rangle": "&#x27E9;"}.get(dval, html.escape(dval))
                            return f"<mo>{disp}</mo>", dm.end(), True
                    dch = s[npos]
                    return ("<mrow></mrow>" if dch == "." else f"<mo>{html.escape(dch)}</mo>"), npos + 1, True
                return "<mrow></mrow>", npos, True
            if cname in _GREEK_ENTITIES:
                return f"<mi>{_GREEK_ENTITIES[cname]}</mi>", npos, True
            if cname in _OP_ENTITIES:
                return f"<mo>{_OP_ENTITIES[cname]}</mo>", npos, True
            if cname in _STD_FUNCS:
                return f"<mi mathvariant=\"normal\">{html.escape(cname)}</mi>", npos, True
            if cname in ("quad", "qquad", ",", ";", ":", "!"):
                return '<mspace width="0.28em"/>', npos, True
            if cname in ("{", "}", "|", "%", "_"):
                return f"<mo>{html.escape(cname)}</mo>", npos, True
            return f"<mi>{html.escape(cname)}</mi>", npos, False
        if s[pos].isdigit():
            nm = _NUM_MATCH_RE.match(s, pos)
            tok_n = nm.group(0) if nm else s[pos]
            return f"<mn>{html.escape(tok_n)}</mn>", pos + len(tok_n), True
        if s[pos].isalpha():
            return f"<mi>{html.escape(s[pos])}</mi>", pos + 1, True
        return f"<mo>{html.escape(s[pos])}</mo>", pos + 1, True

    while i < n:
        if out_chars > MAX_CONVERTED_MATHML_CHARS:
            ok_all = False
            break
        if s[i].isspace():
            i += 1
            continue
        if s[i] in ("&",):
            out.append('<mspace width="0.4em"/>')
            out_chars += 24
            i += 1
            continue
        if s.startswith("\\\\", i):
            out.append('<mspace linebreak="newline"/>')
            out_chars += 29
            i += 2
            continue
        base_ml, i, ok_b = _read_unit(i, depth)
        ok_all = ok_all and ok_b
        sub_ml: Optional[str] = None
        sup_ml: Optional[str] = None
        for _ in range(2):
            while i < n and s[i].isspace():
                i += 1
            if i < n and s[i] == "_" and sub_ml is None:
                sub_ml, i, ok_s = _read_unit(i + 1, depth + 1)
                ok_all = ok_all and ok_s
            elif i < n and s[i] == "^" and sup_ml is None:
                sup_ml, i, ok_p = _read_unit(i + 1, depth + 1)
                ok_all = ok_all and ok_p
            else:
                break
        if sub_ml is not None and sup_ml is not None:
            seg = f"<msubsup>{base_ml}{sub_ml}{sup_ml}</msubsup>"
        elif sub_ml is not None:
            seg = f"<msub>{base_ml}{sub_ml}</msub>"
        elif sup_ml is not None:
            seg = f"<msup>{base_ml}{sup_ml}</msup>"
        else:
            seg = base_ml
        out.append(seg)
        out_chars += len(seg)
    return "".join(out), ok_all


def latex_to_mathml_safe(raw_latex: str, macro_table: Optional[Dict[str, Dict[str, Any]]] = None, *, display_block: bool = True) -> Dict[str, Any]:
    disp_attr = "block" if display_block else "inline"
    raw_s = raw_latex or ""
    if len(raw_s) > MAX_EQUATION_INPUT_CHARS:
        safe_cap = html.escape(raw_s[:600])
        return {
            "mathml": f'<math xmlns="http://www.w3.org/1998/Math/MathML" display="{disp_attr}"><mtext>{safe_cap}</mtext></math>',
            "mode": "RAW_TEX",
            "raw_latex": raw_s[:MAX_EQUATION_INPUT_CHARS],
            "expanded_latex": raw_s[:MAX_EQUATION_INPUT_CHARS],
            "normalized_symbols": normalize_latex_math_symbols(raw_s[:4096]),
        }
    clean = re.sub(r"\\(?:label|tag|nonumber|notag)\s*(?:\{[^{}]*\})?", "", raw_s).strip()
    clean = re.sub(r"\\begin\{(?:aligned|split|array)\}(?:\{[^{}]*\})?|\\end\{(?:aligned|split|array)\}", "", clean).strip()
    expanded, meta = expand_latex_macros_bounded(clean, macro_table or {})
    norm_syms = normalize_latex_math_symbols(expanded[:MAX_EQUATION_INPUT_CHARS])
    if meta.get("macro_expansion_capped") or len(expanded) > MAX_EQUATION_INPUT_CHARS:
        safe_txt = html.escape(clean[:600])
        capped_mode = "MACRO_EXPANSION_CAPPED" if meta.get("macro_expansion_capped") else "RAW_TEX"
        res_c: Dict[str, Any] = {
            "mathml": f'<math xmlns="http://www.w3.org/1998/Math/MathML" display="{disp_attr}"><mtext>{safe_txt}</mtext></math>',
            "mode": capped_mode,
            "raw_latex": clean,
            "expanded_latex": clean,
            "normalized_symbols": norm_syms,
        }
        if meta.get("macro_expansion_capped"):
            res_c["badge"] = "MACRO_EXPANSION_CAPPED"
        return res_c
    try:
        body_ml, full_ok = _convert_tex_tokens_to_mathml(expanded, 0)
    except (RecursionError, MemoryError):
        body_ml, full_ok = f"<mtext>{html.escape(clean[:600])}</mtext>", False
    mode = "MATHML_CORE" if full_ok else "RAW_TEX"
    return {
        "mathml": f'<math xmlns="http://www.w3.org/1998/Math/MathML" display="{disp_attr}"><mrow>{body_ml}</mrow></math>',
        "mode": mode,
        "raw_latex": clean,
        "expanded_latex": expanded,
        "normalized_symbols": norm_syms,
    }


def resolve_manuscript_bundle(entry_tex: Path, *, allowed_root: Optional[Path] = None, strict_include_refusal: bool = False) -> Dict[str, Any]:
    """Walk multi-file LaTeX manuscript (`\\input`/`\\include`/`\\subfile`), resolve macros, `.aux` labels,
    equations (with MathML Core), table/figure inputs, and `.bib`/`\\bibitem` catalog citations.
    """
    entry_abs = Path(os.path.abspath(os.fspath(entry_tex)))
    if _is_reparse_or_symlink(entry_abs) or _is_reparse_or_symlink(entry_abs.parent):
        raise AnvilLatexSecurityError("PATH_ESCAPE_REFUSED", "Symlink or junction entry manuscript refused.", candidate=entry_abs.name)
    paper_root = entry_abs.parent.resolve()
    bound_res = allowed_root.resolve() if allowed_root is not None else paper_root
    if not _is_within_boundary(entry_abs, bound_res):
        raise AnvilLatexSecurityError("PATH_ESCAPE_REFUSED", "Entry manuscript escapes allowed root.", candidate=entry_abs.name)
    entry_res = entry_abs
    visited: List[Path] = []
    seen_norm: Set[str] = set()
    total_tex_bytes = 0
    refused_refs: List[str] = []
    macros: Dict[str, Dict[str, Any]] = {}
    bib_files: List[Path] = []
    aux_files: List[Path] = []
    cite_occurrences: List[Dict[str, Any]] = []
    referenced_artifacts: List[str] = []
    inc_re = re.compile(r"\\(?:input|include|subfile)\s*\{([^{}]+)\}")
    bib_re = re.compile(r"\\(?:bibliography|addbibresource)\s*\{([^{}]+)\}")
    gfx_re = re.compile(r"\\includegraphics(?:\[[^\[\]]*\])?\s*\{([^{}]+)\}")
    cite_re = re.compile(r"\\(?:cite|citet|citep|citealp|citeauthor|parencite|textcite)\*?(?:\[[^\[\]]*\])*\s*\{([^{}]+)\}")
    sec_re = re.compile(r"\\(section|subsection|appendix)\*?\s*\{")
    bibitem_re = re.compile(r"\\bibitem(?:\[[^\[\]]*\])?\s*\{([^{}]+)\}\s*(.+)")

    inline_bib: Dict[str, Dict[str, Any]] = {}
    file_texts: Dict[Path, str] = {}
    t_bundle_start = time.perf_counter()

    def _walk(tf: Path, cur_sec: str, inc_depth: int = 0) -> str:
        nonlocal total_tex_bytes
        tf_key = os.path.normcase(os.path.abspath(os.fspath(tf)))
        if (
            tf_key in seen_norm
            or len(visited) >= MAX_TEX_FILES
            or inc_depth > MAX_TEX_INCLUDE_DEPTH
            or total_tex_bytes >= MAX_TOTAL_TEX_BYTES
            or (time.perf_counter() - t_bundle_start) > 2.0
        ):
            return cur_sec
        rem_b = max(65_536, MAX_TOTAL_TEX_BYTES - total_tex_bytes)
        raw_b = _read_contained_bytes(tf, bound_res, max_bytes=rem_b)
        total_tex_bytes += len(raw_b)
        seen_norm.add(tf_key)
        visited.append(tf)
        aux_cand = tf.with_suffix(".aux")
        if aux_cand not in aux_files and not _is_reparse_or_symlink(aux_cand) and aux_cand.is_file():
            aux_files.append(aux_cand)
        if tf.suffix.lower() not in (".tex", ".md", ".sty", ".cls"):
            return cur_sec
        clean_txt = _strip_tex_comments(raw_b.decode("utf-8", errors="replace"))
        file_texts[tf] = clean_txt
        macros.update(parse_macros_from_tex(clean_txt, macros))
        sec = cur_sec
        for ln in clean_txt.splitlines():
            sm = sec_re.search(ln)
            if sm:
                st, _ = _extract_braced(ln, sm.end() - 1)
                if st.strip():
                    sec = re.sub(r"\\[A-Za-z]+\s*", "", st).replace("{", "").replace("}", "").strip()
            for bm in bib_re.finditer(ln):
                for part_b in bm.group(1).split(","):
                    try:
                        bf = _resolve_child_candidate(part_b.strip(), tf.parent, paper_root, bound_res, ("", ".bib"))
                        if bf is not None and bf not in bib_files:
                            bib_files.append(bf)
                    except AnvilLatexSecurityError:
                        refused_refs.append(part_b.strip()[:120])
            for gm in gfx_re.finditer(ln):
                try:
                    gref = validate_safe_latex_ref(gm.group(1))
                    if gref and gref not in referenced_artifacts:
                        referenced_artifacts.append(gref)
                except AnvilLatexSecurityError:
                    refused_refs.append(gm.group(1).strip()[:120])
            for cm in cite_re.finditer(ln):
                for ck in cm.group(1).split(","):
                    cks = ck.strip()
                    if cks:
                        cite_occurrences.append({"cite_key": cks, "section": sec, "file": tf.name})
            bim = bibitem_re.search(ln)
            if bim:
                bkey = bim.group(1).strip()
                btxt = re.sub(r"\\[A-Za-z]+", "", bim.group(2)).replace("{", "").replace("}", "").strip()
                inline_bib[bkey] = {"cite_key": bkey, "entry_type": "bibitem", "title": btxt[:200], "author": "", "year": None, "venue": "", "doi": "", "arxiv": "", "pmid": "", "posture": "MANUSCRIPT_CITED"}
            for im in inc_re.finditer(ln):
                raw_r = im.group(1).strip()
                if re.search(r"\\[A-Za-z@]+", raw_r) and not raw_r.startswith(("\\\\", "//")):
                    raw_r, _ = expand_latex_macros_bounded(raw_r, macros, max_depth=4)
                    if re.search(r"\\[A-Za-z@]+", raw_r):
                        refused_refs.append(raw_r[:120])
                        continue
                try:
                    norm_r = validate_safe_latex_ref(raw_r)
                    if norm_r and any(tok in norm_r.lower() for tok in ("table", "tab", "fig")):
                        if norm_r not in referenced_artifacts:
                            referenced_artifacts.append(norm_r)
                    cf = _resolve_child_candidate(raw_r, tf.parent, paper_root, bound_res, ("", ".tex"))
                except AnvilLatexSecurityError:
                    if strict_include_refusal:
                        raise
                    refused_refs.append(raw_r[:120])
                    continue
                if cf is not None:
                    sec = _walk(cf, sec, inc_depth + 1)
        return sec

    _walk(entry_res, "Main", 0)
    if not bib_files:
        for cand_b in sorted(paper_root.glob("*.bib"))[:16]:
            if not _is_reparse_or_symlink(cand_b) and _is_within_boundary(cand_b, bound_res):
                bib_files.append(cand_b.resolve())
    bib_entries: Dict[str, Dict[str, Any]] = dict(inline_bib)
    for bf in bib_files[:16]:
        raw_bib_b = _read_contained_bytes(bf, bound_res, max_bytes=MAX_BIB_BYTES)
        bib_entries.update(_parse_bib_content_linear(raw_bib_b.decode("utf-8", errors="replace")))
    aux_labels = parse_aux_labels(aux_files, bound_res)
    catalog_seeds: List[Dict[str, str]] = []
    seen_seeds: Set[str] = set()
    for ckey, meta in bib_entries.items():
        seed_id = f"DOI:{meta['doi']}" if meta.get("doi") else (f"arXiv:{meta['arxiv']}" if meta.get("arxiv") else (f"PMID:{meta['pmid']}" if meta.get("pmid") else ""))
        if seed_id and seed_id not in seen_seeds:
            seen_seeds.add(seed_id)
            catalog_seeds.append({"seed_id": seed_id, "cite_key": ckey, "title": str(meta.get("title") or ckey), "year": str(meta.get("year") or "")})
    return {
        "files": visited,
        "bib_files": bib_files,
        "macros": macros,
        "aux_labels": aux_labels,
        "bibliography": bib_entries,
        "citations": cite_occurrences,
        "catalog_seeds": catalog_seeds,
        "referenced_artifacts": referenced_artifacts,
        "refused_refs": refused_refs,
    }
