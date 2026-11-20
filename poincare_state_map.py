#!/usr/bin/env python3
"""Dual-Poincaré Deep-Memory State Maps (poincare_state_map.py — stdlib only).

Implements the MERA-Poincaré architecture for rapid deep-memory context assembly
(1M -> 1B -> 1T tokens) across AI Cockpits, Gandalf reports, Cave of Wonders,
and Star Chart:
1. Parent-Relative Log-Polar / Lorentz-Stabilized Sarkar Combinatorial Layout
   (deterministic O(N) linear time, zero SGD, immune to IEEE-754 float64 r=39
   Cartesian horizon underflow).
2. Two-Timescale (Time, Importance) Survival + Popularity-Similarity Radial
   Importance Promotion r_eff(u) = r_tree(u) * (1 - alpha * I_u^2) so locked
   decisions, North Stars, and accepted deliverables never decay or starve across
   sibling waves, while superseded/dismissed items undergo centrifugal Boneyard
   recession (bi-temporal validity [valid_from, valid_until)).
3. MERA-Poincaré 2-Resolution Ancestor-Closed Marginal-Density Knapsack parser
   with 12-token Horizon Breadcrumbs for logarithmic RLM zoom.
4. Transversal Poincaré Section Checkpointing (Sigma) + Interactive 2D Möbius
   Gyrovector-Zoomable Poincaré Disk HTML Viewer.
"""
from __future__ import annotations

import argparse
import hashlib
import html as _html
import json
import math
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "poincare-state-map/v1"
DEFAULT_TAU = 1.35
DEFAULT_ALPHA_PROMOTE = 0.55
BONEYARD_RADIAL_OFFSET = 2.65
DISK_PROJECTION_SCALE = 3.10


def _est_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, (len(text) + 3) // 4)


def _truncate_clean(text: str, max_chars: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(s) <= max_chars:
        return s
    return s[: max(1, max_chars - 1)].rstrip() + "…"


def _parse_iso_age_hours(ts_val: Any, now_epoch: float) -> float:
    if ts_val is None or ts_val == "":
        return 24.0
    if isinstance(ts_val, (int, float)):
        val = float(ts_val)
        if val > 1e12:
            val /= 1000.0
        return max(0.01, (now_epoch - val) / 3600.0)
    raw = str(ts_val).strip()
    if not raw:
        return 24.0
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0.01, (now_epoch - dt.timestamp()) / 3600.0)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(raw[: len(fmt) + 2].strip(), fmt).replace(tzinfo=timezone.utc)
            return max(0.01, (now_epoch - dt.timestamp()) / 3600.0)
        except ValueError:
            continue
    return 24.0


# ── 1. Exact Log-Polar Hyperbolic & Möbius Geometry ─────────────────────────


def _log_sinh(val: float) -> float:
    if val < 1e-15:
        return -40.0
    if val < 20.0:
        return math.log(max(1e-300, math.sinh(val)))
    return val - math.log(2.0) + math.log1p(-math.exp(-2.0 * val))


def hyperbolic_distance_logpolar(r1: float, th1: float, r2: float, th2: float) -> float:
    """Exact hyperbolic geodesic distance in log-polar coordinates (r, theta),
    numerically stable in IEEE-754 float64 past r = 600 (>10^260 leaves)."""
    ang = abs(th1 - th2) % (2.0 * math.pi)
    if ang > math.pi:
        ang = 2.0 * math.pi - ang
    sin_half = abs(math.sin(ang / 2.0))
    dr = abs(r1 - r2)
    if sin_half < 1e-15 or r1 < 1e-12 or r2 < 1e-12:
        return dr
    log_term2 = 0.5 * (_log_sinh(r1) + _log_sinh(r2)) + math.log(sin_half)
    if dr < 20.0 and log_term2 > 20.0:
        return 2.0 * (math.log(2.0) + log_term2)
    s_diff = math.sinh(dr / 2.0) if dr < 40.0 else 0.5 * math.exp(dr / 2.0)
    term2 = math.exp(min(300.0, log_term2))
    return 2.0 * math.asinh(math.hypot(s_diff, term2))


def project_to_poincare_disk(r_eff: float, theta: float, scale: float = DISK_PROJECTION_SCALE) -> tuple[float, float]:
    """Stereographic/radial projection to the open unit disk |z| < 1 strictly for
    focus neighborhoods and interactive 2D visualization."""
    rho = math.tanh(min(max(0.0, r_eff), 28.0) / max(0.5, scale))
    rho = min(0.965, rho)
    return round(rho * math.cos(theta), 6), round(rho * math.sin(theta), 6)


def mobius_translate_point(zx: float, zy: float, fx: float, fy: float) -> tuple[float, float]:
    """Exact isometric Möbius gyrovector translation T_{-f}(z) = (z - f) / (1 - conj(f)*z)
    mapping focus f = (fx, fy) to the origin (0, 0) in O(1) operations."""
    nr = zx - fx
    ni = zy - fy
    dr = 1.0 - (fx * zx + fy * zy)
    di = -(fx * zy - fy * zx)
    denom = dr * dr + di * di
    if denom < 1e-30:
        return 0.0, 0.0
    ox = (nr * dr + ni * di) / denom
    oy = (ni * dr - nr * di) / denom
    mag = math.hypot(ox, oy)
    if mag >= 0.995:
        ox *= 0.995 / mag
        oy *= 0.995 / mag
    return round(ox, 6), round(oy, 6)


def sarkar_combinatorial_layout(
    nodes: list[dict[str, Any]],
    *,
    tau: float = DEFAULT_TAU,
    alpha_promote: float = DEFAULT_ALPHA_PROMOTE,
    now_epoch: float | None = None,
) -> list[dict[str, Any]]:
    """Deterministic O(N) linear-time Sarkar combinatorial hyperbolic layout +
    two-timescale (time, importance) survival + Radial Importance Promotion +
    bi-temporal Boneyard recession."""
    if not nodes:
        return []
    now_ts = now_epoch if now_epoch is not None else time.time()
    id_to_idx = {str(nd["id"]): i for i, nd in enumerate(nodes)}
    n = len(nodes)
    children: list[list[int]] = [[] for _ in range(n)]
    roots: list[int] = []
    for i, nd in enumerate(nodes):
        pid = str(nd.get("parent_id") or "")
        if pid and pid in id_to_idx and id_to_idx[pid] != i:
            children[id_to_idx[pid]].append(i)
        else:
            roots.append(i)
    if not roots:
        roots = [0]

    # Iterative DFS order + subtree leaf weight
    order: list[int] = []
    depths = [0] * n
    stack = [(r_i, 0) for r_i in reversed(roots)]
    visited = [False] * n
    while stack:
        u, d_val = stack.pop()
        if visited[u]:
            continue
        visited[u] = True
        depths[u] = d_val
        order.append(u)
        for ch in reversed(children[u]):
            if not visited[ch]:
                stack.append((ch, d_val + 1))
    for i in range(n):
        if not visited[i]:
            order.append(i)

    weight = [1.0] * n
    for u in reversed(order):
        if children[u]:
            weight[u] = sum(weight[ch] for ch in children[u]) + 0.25

    r_tree = [0.0] * n
    theta = [0.0] * n
    wedge_lo = [0.0] * n
    wedge_hi = [2.0 * math.pi] * n

    if len(roots) > 1:
        tot_rw = sum(weight[r_i] for r_i in roots)
        cur_ang = 0.0
        for r_i in roots:
            span = 2.0 * math.pi * (weight[r_i] / max(1e-9, tot_rw))
            wedge_lo[r_i] = cur_ang
            wedge_hi[r_i] = cur_ang + span
            theta[r_i] = cur_ang + 0.5 * span
            r_tree[r_i] = 0.35
            cur_ang += span

    for u in order:
        ch_list = children[u]
        if not ch_list:
            continue
        lo = wedge_lo[u]
        span = wedge_hi[u] - lo
        tot_w = sum(weight[ch] for ch in ch_list)
        cur = lo
        for ch in ch_list:
            w_span = span * (weight[ch] / max(1e-9, tot_w))
            wedge_lo[ch] = cur
            wedge_hi[ch] = cur + w_span
            theta[ch] = cur + 0.5 * w_span
            r_tree[ch] = r_tree[u] + tau
            cur += w_span

    lambda_fast = math.log(2.0) / 16.0
    lambda_slow = math.log(2.0) / 720.0

    enriched: list[dict[str, Any]] = []
    for i, nd in enumerate(nodes):
        out = dict(nd)
        imp = max(0.05, min(1.0, float(out.get("importance") or 0.5)))
        age_h = float(out.get("age_hours")) if out.get("age_hours") is not None else _parse_iso_age_hours(out.get("created_at"), now_ts)
        superseded = bool(out.get("valid_until") or out.get("lifecycle_state") in ("superseded", "refuted", "archived", "dismissed"))
        surv = imp * (0.35 * math.exp(-lambda_fast * age_h) + 0.65 * math.exp(-lambda_slow * (1.0 - imp) * age_h))
        if superseded:
            r_eff = max(3.6, r_tree[i] + BONEYARD_RADIAL_OFFSET)
            surv *= 0.15
        elif depths[i] == 0 and len(roots) == 1:
            r_eff = 0.0
        else:
            r_eff = max(0.18, r_tree[i] * (1.0 - alpha_promote * (imp * imp)))

        sum_txt = _truncate_clean(str(out.get("summary") or out.get("title") or ""), 240)
        full_txt = str(out.get("full_text") or sum_txt).strip()
        zx, zy = project_to_poincare_disk(r_eff, theta[i])

        out["depth"] = depths[i]
        out["importance"] = round(imp, 4)
        out["age_hours"] = round(age_h, 2)
        out["survival"] = round(surv, 5)
        out["superseded"] = superseded
        out["r_tree"] = round(r_tree[i], 4)
        out["r_eff"] = round(r_eff, 4)
        out["theta"] = round(theta[i], 6)
        out["disk_x"] = zx
        out["disk_y"] = zy
        out["summary"] = sum_txt
        out["full_text"] = full_txt
        out["summary_tokens"] = max(8, _est_tokens(sum_txt))
        out["full_tokens"] = max(out["summary_tokens"], int(out.get("raw_tokens") or _est_tokens(full_txt)))
        enriched.append(out)
    return enriched


# ── 2. MERA-Poincaré 2-Resolution Ancestor-Closed Knapsack Parser ───────────

_STOP_WORDS = frozenset({
    "the", "and", "for", "with", "what", "how", "this", "that", "from", "into",
    "please", "can", "you", "have", "are", "was", "were", "will", "would", "should",
    "about", "just", "like", "also", "then", "when", "where", "which", "make", "need",
})

# In-process RAM cache keyed by resolved effort_dir -> (section_fingerprint, map_doc, inverted_index)
_RAM_MAP_CACHE: dict[str, tuple[str, dict[str, Any], dict[str, list[int]]]] = {}


def _build_inverted_index(nodes: list[dict[str, Any]]) -> dict[str, list[int]]:
    """Build an in-memory inverted token index (`O(N)` once per section crossing)
    so per-turn Focus Anchor lookup runs in `O(k)` sub-millisecond time."""
    inv: dict[str, list[int]] = {}
    for idx, nd in enumerate(nodes):
        if nd.get("superseded"):
            continue
        hay = f"{nd.get('title') or ''} {nd.get('summary') or ''} {nd.get('source_ref') or ''}".lower()
        seen_toks = set()
        for tok in re.findall(r"[a-z0-9]{3,}", hay):
            if tok not in _STOP_WORDS and tok not in seen_toks:
                seen_toks.add(tok)
                inv.setdefault(tok, []).append(idx)
    return inv


def resolve_focus_node_id(
    nodes: list[dict[str, Any]],
    *,
    focus_id: str | None = None,
    query: str = "",
    inverted_index: dict[str, list[int]] | None = None,
) -> str:
    if not nodes:
        return ""
    by_id = {str(nd["id"]): nd for nd in nodes}
    if focus_id and str(focus_id) in by_id:
        return str(focus_id)
    q_tokens = [tok for tok in re.findall(r"[a-z0-9]{3,}", str(query or "").lower()) if tok not in _STOP_WORDS]
    if q_tokens:
        if inverted_index is not None:
            cand_hits: dict[int, int] = {}
            for tok in q_tokens:
                for idx in inverted_index.get(tok, ()):
                    cand_hits[idx] = cand_hits.get(idx, 0) + 1
            if cand_hits:
                best_idx = max(
                    cand_hits.keys(),
                    key=lambda idx: cand_hits[idx] * 2.0 + float(nodes[idx].get("survival") or 0.5),
                )
                return str(nodes[best_idx]["id"])
        else:
            best_id = ""
            best_score = -1.0
            for nd in nodes:
                if nd.get("superseded"):
                    continue
                hay = f"{nd.get('title') or ''} {nd.get('summary') or ''} {nd.get('full_text') or ''}".lower()
                hits = sum(1 for tok in q_tokens if tok in hay)
                if hits > 0:
                    sc = hits * 2.0 + float(nd.get("survival") or 0.5)
                    if sc > best_score:
                        best_score = sc
                        best_id = str(nd["id"])
            if best_id:
                return best_id
    # Default: active wave/step if marked, else root
    active_cand = [nd for nd in nodes if not nd.get("superseded") and str(nd.get("lifecycle_state") or "") == "active" and nd.get("kind") in ("wave", "cockpit", "cave_list_item")]
    if active_cand:
        active_cand.sort(key=lambda x: -float(x.get("survival") or 0.0))
        return str(active_cand[0]["id"])
    return str(nodes[0]["id"])


def parse_deep_memory_window(
    map_doc: dict[str, Any],
    *,
    focus_id: str | None = None,
    query: str = "",
    budget_tokens: int = 16_384,
    inverted_index: dict[str, list[int]] | None = None,
) -> dict[str, Any]:
    """Assemble a token-budgeted deep-memory context window in sub-5ms using
    Möbius/log-polar focus distance + I^2.5 2-resolution ancestor-closed knapsack
    + 12-token Horizon Breadcrumbs."""
    t0 = time.perf_counter()
    nodes: list[dict[str, Any]] = list(map_doc.get("nodes") or [])
    if not nodes:
        return {
            "ok": True,
            "focus_node_id": "",
            "budget_tokens": budget_tokens,
            "used_tokens": 0,
            "corpus_raw_tokens": 0,
            "compression_ratio": 1.0,
            "parse_ms": 0.0,
            "selected_nodes": [],
            "horizon_breadcrumbs": [],
            "formatted_capsule": "",
        }

    budget = max(256, int(budget_tokens))
    by_id = {str(nd["id"]): i for i, nd in enumerate(nodes)}
    f_id = resolve_focus_node_id(nodes, focus_id=focus_id, query=query)
    f_idx = by_id.get(f_id, 0)
    fq = nodes[f_idx]
    rq = float(fq.get("r_eff") or 0.0)
    thq = float(fq.get("theta") or 0.0)

    def _ancestors(idx: int) -> list[int]:
        chain = []
        cur = idx
        seen = set()
        while cur is not None and cur not in seen:
            seen.add(cur)
            chain.append(cur)
            pid = str(nodes[cur].get("parent_id") or "")
            cur = by_id.get(pid) if pid in by_id else None
        return chain

    spine_indices = _ancestors(f_idx)
    sel_mode: dict[int, int] = {}  # 1 = summary, 2 = full
    used = 0
    for anc_i in reversed(spine_indices):
        cost_s = int(nodes[anc_i].get("summary_tokens") or 16)
        if used + cost_s <= budget:
            sel_mode[anc_i] = 1
            used += cost_s
    # Möbius Origin Invariant: the Focus Node f_idx sits at d_H = 0 (Word-for-Word Zone)
    if f_idx in sel_mode and not nodes[f_idx].get("superseded"):
        f_sum = max(8, int(nodes[f_idx].get("summary_tokens") or 16))
        f_full = max(f_sum, int(nodes[f_idx].get("full_tokens") or f_sum))
        if used + (f_full - f_sum) <= budget:
            sel_mode[f_idx] = 2
            used += (f_full - f_sum)

    q_tokens = [tok for tok in re.findall(r"[a-z0-9]{3,}", str(query or "").lower()) if tok not in _STOP_WORDS]
    q_hits_map: dict[int, int] = {}
    if q_tokens and inverted_index is not None:
        for tok in q_tokens:
            for idx_hit in inverted_index.get(tok, ()):
                q_hits_map[idx_hit] = q_hits_map.get(idx_hit, 0) + 1
    marginal_items: list[tuple[float, int, int, int]] = []
    unselected_candidates: list[tuple[float, int]] = []

    for i, nd in enumerate(nodes):
        if nd.get("superseded"):
            continue
        imp = float(nd.get("importance") or 0.5)
        surv = float(nd.get("survival") or imp)
        if imp < 0.20 and i not in sel_mode:
            continue
        dh = hyperbolic_distance_logpolar(rq, thq, float(nd.get("r_eff") or 0.0), float(nd.get("theta") or 0.0))
        q_boost = 1.0
        if q_tokens:
            if inverted_index is not None:
                hits = q_hits_map.get(i, 0)
            else:
                hay = f"{nd.get('title') or ''} {nd.get('summary') or ''}".lower()
                hits = sum(1 for tok in q_tokens if tok in hay)
            if hits:
                q_boost += 0.65 * hits
        u_info = (imp ** 2.5) * surv * math.exp(-0.28 * dh) * q_boost
        unselected_candidates.append((u_info, i))
        c_sum = max(8, int(nd.get("summary_tokens") or 16))
        c_full = max(c_sum, int(nd.get("full_tokens") or c_sum))
        if i not in sel_mode:
            marginal_items.append(((0.55 * u_info) / c_sum, i, 1, c_sum))
        delta_full = c_full - c_sum
        if delta_full > 0:
            marginal_items.append(((0.45 * u_info) / delta_full, i, 2, delta_full))
        elif i in sel_mode:
            sel_mode[i] = 2

    marginal_items.sort(key=lambda x: x[0], reverse=True)
    for _dens, idx_u, target_m, d_tok in marginal_items:
        if target_m == 1 and idx_u not in sel_mode:
            missing_anc = [a for a in _ancestors(idx_u) if a not in sel_mode]
            anc_cost = sum(int(nodes[a].get("summary_tokens") or 16) for a in missing_anc)
            if used + anc_cost + d_tok <= budget:
                for a in reversed(missing_anc):
                    sel_mode[a] = 1
                sel_mode[idx_u] = 1 if int(nodes[idx_u].get("full_tokens") or d_tok) > d_tok else 2
                used += anc_cost + d_tok
        elif target_m == 2 and sel_mode.get(idx_u, 0) == 1:
            if used + d_tok <= budget:
                sel_mode[idx_u] = 2
                used += d_tok

    # Collect top-8 Horizon Breadcrumbs (~12 tokens each) for unselected peripheral branches
    unselected_candidates.sort(key=lambda x: x[0], reverse=True)
    breadcrumbs: list[dict[str, Any]] = []
    for _u_sc, idx_b in unselected_candidates:
        if idx_b in sel_mode:
            continue
        nd_b = nodes[idx_b]
        if nd_b.get("kind") in ("tool_chatter",) and len(breadcrumbs) >= 4:
            continue
        breadcrumbs.append({
            "id": nd_b["id"],
            "kind": nd_b.get("kind") or "node",
            "title": _truncate_clean(str(nd_b.get("title") or nd_b.get("summary") or ""), 64),
            "r_eff": nd_b.get("r_eff"),
            "source_ref": nd_b.get("source_ref") or "",
        })
        if len(breadcrumbs) >= 8:
            break

    selected_out: list[dict[str, Any]] = []
    for idx_s in sorted(sel_mode.keys(), key=lambda k: (nodes[k].get("depth", 0), float(nodes[k].get("r_eff") or 0.0))):
        nd_s = nodes[idx_s]
        mode_s = sel_mode[idx_s]
        selected_out.append({
            "id": nd_s["id"],
            "kind": nd_s.get("kind") or "node",
            "title": nd_s.get("title") or "",
            "resolution": "verbatim" if mode_s == 2 else "summary",
            "tokens": int(nd_s.get("full_tokens") if mode_s == 2 else nd_s.get("summary_tokens")),
            "r_eff": nd_s.get("r_eff"),
            "importance": nd_s.get("importance"),
            "text": nd_s.get("full_text") if mode_s == 2 else nd_s.get("summary"),
            "source_ref": nd_s.get("source_ref") or "",
        })

    corpus_raw = max(1, sum(int(nd.get("full_tokens") or 16) for nd in nodes))
    dt_ms = round((time.perf_counter() - t0) * 1000.0, 3)

    lines = [
        f"[POINCARÉ DEEP-MEMORY STATE CAPSULE · focus='{fq.get('title') or f_id}' · {used}/{budget} tok · {round(corpus_raw / max(1, used), 1)}x compression · {dt_ms}ms]"
    ]
    for item in selected_out[:28]:
        tag = "FULL" if item["resolution"] == "verbatim" else "SUM"
        ref = f" ({item['source_ref']})" if item["source_ref"] else ""
        lines.append(f"- [{tag} · {item['kind']}{ref}] {item['title']}: {_truncate_clean(item['text'], 360 if mode_s == 2 else 180)}")
    if breadcrumbs:
        bc_str = " | ".join(f"{b['title']} ({b['source_ref'] or b['id']})" for b in breadcrumbs[:6])
        lines.append(f"- [HORIZON BREADCRUMBS — zoom on demand]: {bc_str}")

    return {
        "ok": True,
        "focus_node_id": f_id,
        "focus_title": fq.get("title") or f_id,
        "budget_tokens": budget,
        "used_tokens": used,
        "corpus_raw_tokens": corpus_raw,
        "compression_ratio": round(corpus_raw / max(1, used), 2),
        "parse_ms": dt_ms,
        "selected_nodes": selected_out,
        "horizon_breadcrumbs": breadcrumbs,
        "formatted_capsule": "\n".join(lines),
    }


def mobius_recenter_map(map_doc: dict[str, Any], focus_id: str) -> dict[str, Any]:
    """Return a copy of `map_doc` with every node's `(disk_x, disk_y)` isometrically
    translated via Möbius gyrovector addition so `focus_id` sits at `(0, 0)`."""
    nodes = [dict(nd) for nd in (map_doc.get("nodes") or [])]
    target = next((nd for nd in nodes if str(nd.get("id")) == str(focus_id)), None)
    if target is None:
        return dict(map_doc, nodes=nodes)
    fx = float(target.get("disk_x") or 0.0)
    fy = float(target.get("disk_y") or 0.0)
    for nd in nodes:
        nx, ny = mobius_translate_point(float(nd.get("disk_x") or 0.0), float(nd.get("disk_y") or 0.0), fx, fy)
        nd["disk_x"] = nx
        nd["disk_y"] = ny
    out = dict(map_doc)
    out["nodes"] = nodes
    out["recentered_on"] = str(focus_id)
    return out


# ── 3. Cockpit, Fleet & Gandalf Map Builders (Transversal Section Sigma) ────


def _section_fingerprint(files: list[Path]) -> str:
    h = hashlib.sha256()
    for p in files:
        try:
            st = p.stat()
            h.update(f"{p.name}:{st.st_size}:{st.st_mtime_ns}|".encode("utf-8"))
        except OSError:
            h.update(f"{p.name}:missing|".encode("utf-8"))
    return h.hexdigest()[:24]


def _extract_markdown_section(md_text: str, heading: str) -> str:
    pat = re.compile(rf"^##+\s+{re.escape(heading)}\b[^\n]*\n(.*?)(?=^##+\s+|\Z)", re.I | re.M | re.S)
    m = pat.search(md_text or "")
    return m.group(1).strip() if m else ""


def build_cockpit_poincare_map(
    effort_dir: str | Path,
    *,
    persist: bool = True,
    force: bool = False,
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """Build or load `.ecgberht/poincare-state.json` for an AI Cockpit at transversal
    Poincaré section crossings (Sigma), ingesting North Star, Waves, Deliverables
    (with bi-temporal Boneyard recession on dismissed/superseded revisions), and
    Dialogue history with zero LLM calls."""
    t_start = time.perf_counter()
    cdir = Path(effort_dir)
    ecg_dir = cdir / ".ecgberht"
    out_file = ecg_dir / "poincare-state.json"
    watched = [
        cdir / "ECGBERHT.md",
        cdir / "roadmap.json",
        cdir / "strip.json",
        cdir / "DELIVERABLES.md",
        ecg_dir / "dismissed-deliverables.json",
        ecg_dir / "conversation-log.json",
    ]
    fp = _section_fingerprint(watched)
    cache_key = str(cdir.resolve()) if cdir.exists() else str(cdir)
    if not force and now_epoch is None:
        ram_hit = _RAM_MAP_CACHE.get(cache_key)
        if ram_hit is not None and ram_hit[0] == fp:
            doc_ram = dict(ram_hit[1])
            doc_ram["from_ram_cache"] = True
            doc_ram["from_section_cache"] = True
            return doc_ram
        if out_file.is_file():
            try:
                cached = json.loads(out_file.read_text(encoding="utf-8"))
                if isinstance(cached, dict) and cached.get("section_fingerprint") == fp and cached.get("schema") == SCHEMA_VERSION:
                    cached["from_section_cache"] = True
                    if len(_RAM_MAP_CACHE) >= 64:
                        _RAM_MAP_CACHE.pop(next(iter(_RAM_MAP_CACHE)), None)
                    _RAM_MAP_CACHE[cache_key] = (fp, cached, _build_inverted_index(cached.get("nodes") or []))
                    return cached
            except Exception:
                pass

    now_ts = now_epoch if now_epoch is not None else time.time()
    effort_name = cdir.name or "AI Cockpit"
    ecg_md = (cdir / "ECGBERHT.md").read_text(encoding="utf-8", errors="replace") if (cdir / "ECGBERHT.md").is_file() else ""
    north_star = _extract_markdown_section(ecg_md, "North star") or _extract_markdown_section(ecg_md, "Goal")
    human_wait = _extract_markdown_section(ecg_md, "Human wait")

    rm_data: dict[str, Any] = {}
    if (cdir / "roadmap.json").is_file():
        try:
            rm_data = json.loads((cdir / "roadmap.json").read_text(encoding="utf-8", errors="replace"))
        except Exception:
            rm_data = {}
    strip_data: dict[str, Any] = {}
    if (cdir / "strip.json").is_file():
        try:
            strip_data = json.loads((cdir / "strip.json").read_text(encoding="utf-8", errors="replace"))
        except Exception:
            strip_data = {}

    if not north_star:
        north_star = str(rm_data.get("goal") or (strip_data.get("strip") or strip_data).get("goal") or f"Campaign objective for {effort_name}")

    raw_nodes: list[dict[str, Any]] = []
    root_id = "ns-root"
    raw_nodes.append({
        "id": root_id,
        "parent_id": "",
        "kind": "north_star",
        "title": f"North Star — {effort_name}",
        "summary": _truncate_clean(north_star, 220),
        "full_text": _truncate_clean(north_star + (f" | Waiting on: {human_wait}" if human_wait else ""), 900),
        "importance": 1.0,
        "age_hours": 1.0,
        "lifecycle_state": "active",
        "source_ref": "ECGBERHT.md",
    })

    cur_step_id = str((strip_data.get("strip") or strip_data).get("current_step_id") or "").strip()
    steps = rm_data.get("roadmap_projection") if isinstance(rm_data.get("roadmap_projection"), list) else (
        rm_data.get("steps") if isinstance(rm_data.get("steps"), list) else []
    )
    wave_ids: list[str] = []
    active_wave_id = root_id
    for idx_w, st_obj in enumerate(steps):
        if not isinstance(st_obj, dict):
            continue
        wid = f"wave-{st_obj.get('id') or (idx_w + 1)}"
        wave_ids.append(wid)
        st_status = str(st_obj.get("status") or "pending").lower()
        is_cur = (str(st_obj.get("id") or "") == cur_step_id) or st_status == "active"
        if is_cur:
            active_wave_id = wid
        w_imp = 0.94 if is_cur else (0.82 if st_status == "done" else 0.72)
        w_name = str(st_obj.get("name") or st_obj.get("title") or f"Wave {idx_w + 1}")
        done_when = str(st_obj.get("done_when") or "")
        raw_nodes.append({
            "id": wid,
            "parent_id": root_id,
            "kind": "wave",
            "title": w_name,
            "summary": _truncate_clean(f"[{st_status.upper()}] {w_name}" + (f" — {done_when}" if done_when else ""), 220),
            "full_text": _truncate_clean(f"Wave: {w_name}\nStatus: {st_status}\nDone when: {done_when}", 700),
            "importance": w_imp,
            "age_hours": 2.0 if is_cur else (24.0 * (idx_w + 1)),
            "lifecycle_state": "active" if is_cur else st_status,
            "source_ref": f"roadmap.json#{st_obj.get('id') or (idx_w + 1)}",
        })
        for idx_sub, sub in enumerate(st_obj.get("substeps") or []):
            if not isinstance(sub, dict):
                continue
            raw_nodes.append({
                "id": f"{wid}-sub-{idx_sub + 1}",
                "parent_id": wid,
                "kind": "decision",
                "title": _truncate_clean(str(sub.get("text") or f"Substep {idx_sub + 1}"), 90),
                "summary": _truncate_clean(f"{'✓' if sub.get('done') else '○'} {sub.get('text') or ''}", 200),
                "full_text": str(sub.get("text") or ""),
                "importance": 0.76 if not sub.get("done") else 0.64,
                "age_hours": 4.0 if is_cur else 36.0,
                "lifecycle_state": "done" if sub.get("done") else "active",
                "source_ref": "roadmap.json",
            })

    # Deliverables (active/accepted promoted inward; dismissed/superseded pushed to Boneyard ring)
    dismissed_paths: dict[str, str] = {}
    if (ecg_dir / "dismissed-deliverables.json").is_file():
        try:
            dd = json.loads((ecg_dir / "dismissed-deliverables.json").read_text(encoding="utf-8", errors="replace"))
            items_dd = dd.get("items") if isinstance(dd, dict) else (dd if isinstance(dd, list) else [])
            if isinstance(items_dd, dict):
                for k_p, v_p in items_dd.items():
                    disp = str((v_p or {}).get("disposition") or "dismissed") if isinstance(v_p, dict) else "dismissed"
                    dismissed_paths[str(k_p)] = disp
            elif isinstance(items_dd, list):
                for it_d in items_dd:
                    if isinstance(it_d, dict) and it_d.get("path"):
                        dismissed_paths[str(it_d["path"])] = str(it_d.get("disposition") or "dismissed")
        except Exception:
            pass

    if (cdir / "DELIVERABLES.md").is_file():
        deliv_txt = (cdir / "DELIVERABLES.md").read_text(encoding="utf-8", errors="replace")
        d_idx = 0
        for ln in deliv_txt.splitlines():
            s = ln.strip()
            if not s.startswith("|") or "---" in s or "What" in s and "Where" in s:
                continue
            cols = [c.strip() for c in s.strip("|").split("|")]
            if len(cols) < 2:
                continue
            what_lbl, where_raw = cols[0], cols[1].strip("` ")
            date_lbl = cols[2] if len(cols) >= 3 else ""
            step_col = cols[3] if len(cols) >= 4 else ""
            d_idx += 1
            disp = dismissed_paths.get(where_raw, "")
            is_superseded = disp in ("dismissed", "superseded") or "supporting" in what_lbl.lower() and d_idx > 8
            parent_w = active_wave_id
            if step_col.isdigit() and 1 <= int(step_col) <= len(wave_ids):
                parent_w = wave_ids[int(step_col) - 1]
            # Estimate raw tokens of target file if text/md
            raw_tok_est = 180
            target_f = cdir / where_raw
            if target_f.is_file():
                try:
                    sz = target_f.stat().st_size
                    raw_tok_est = min(25_000, max(64, sz // 4))
                except OSError:
                    pass
            raw_nodes.append({
                "id": f"deliv-{d_idx}",
                "parent_id": parent_w,
                "kind": "deliverable",
                "title": _truncate_clean(what_lbl, 96),
                "summary": _truncate_clean(f"Deliverable: {what_lbl} ({where_raw})", 220),
                "full_text": f"Deliverable: {what_lbl}\nPath: {where_raw}\nDate: {date_lbl}\nDisposition: {disp or 'current'}",
                "raw_tokens": raw_tok_est,
                "importance": 0.42 if is_superseded else (0.95 if d_idx <= 4 else 0.84),
                "created_at": date_lbl,
                "valid_until": "superseded" if disp in ("dismissed", "superseded") else None,
                "lifecycle_state": "superseded" if disp in ("dismissed", "superseded") else (disp or "accepted"),
                "source_ref": where_raw,
            })

    # Conversation turns (.ecgberht/conversation-log.json)
    turns_list: list[dict[str, Any]] = []
    if (ecg_dir / "conversation-log.json").is_file():
        try:
            cdoc = json.loads((ecg_dir / "conversation-log.json").read_text(encoding="utf-8", errors="replace"))
            turns_list = cdoc.get("turns") if isinstance(cdoc, dict) else (cdoc if isinstance(cdoc, list) else [])
        except Exception:
            turns_list = []

    total_turns = len(turns_list or [])
    recent_cutoff = max(0, total_turns - 8)
    for t_i, turn in enumerate(turns_list or []):
        if not isinstance(turn, dict):
            continue
        role = str(turn.get("role") or "steward").lower()
        txt = str(turn.get("text") or "").strip()
        if not txt:
            continue
        tid_raw = str(turn.get("turn_id") or f"t-{t_i + 1}")
        is_receipt = tid_raw.startswith("receipt:")
        is_recent = t_i >= recent_cutoff
        is_decision = role == "john" and (len(txt) >= 40 or txt.lower() in ("yes", "approve", "1", "2", "3"))
        if is_receipt:
            imp_t = 0.45
            k_lbl = "turn"
        elif is_decision:
            imp_t = 0.90 if is_recent else 0.80
            k_lbl = "decision"
        elif role == "john":
            imp_t = 0.84 if is_recent else 0.68
            k_lbl = "turn"
        else:
            imp_t = 0.78 if is_recent else 0.48
            k_lbl = "turn"

        # Distribute historical turns across waves proportionally if multiple waves exist
        if wave_ids:
            w_slot = min(len(wave_ids) - 1, (t_i * len(wave_ids)) // max(1, total_turns))
            p_turn = active_wave_id if is_recent else wave_ids[w_slot]
        else:
            p_turn = root_id

        speaker = "John" if role == "john" else "Steward"
        raw_nodes.append({
            "id": f"turn-{t_i + 1}",
            "parent_id": p_turn,
            "kind": k_lbl,
            "title": f"{speaker} #{t_i + 1}: {_truncate_clean(txt, 62)}",
            "summary": f"{speaker}: {_truncate_clean(txt, 190)}",
            "full_text": f"{speaker} ({turn.get('at') or ''}):\n{_truncate_clean(txt, 1400)}",
            "raw_tokens": _est_tokens(txt),
            "importance": imp_t,
            "created_at": turn.get("at"),
            "lifecycle_state": "active" if is_recent else "done",
            "source_ref": f".ecgberht/conversation-log.json#turn-{t_i + 1}",
        })

    laid_out = sarkar_combinatorial_layout(raw_nodes, now_epoch=now_ts)
    build_ms = round((time.perf_counter() - t_start) * 1000.0, 3)

    # Poincaré Return-Map displacement check across last 3 turns (loop / stall detector)
    turn_nodes = [nd for nd in laid_out if str(nd["id"]).startswith("turn-")]
    return_map_disp = None
    thrash_detected = False
    if len(turn_nodes) >= 3:
        a_nd, b_nd = turn_nodes[-2], turn_nodes[-1]
        return_map_disp = round(
            hyperbolic_distance_logpolar(a_nd["r_eff"], a_nd["theta"], b_nd["r_eff"], b_nd["theta"]),
            4,
        )
        # Identical repeated short questions with zero file/deliverable progress
        if a_nd.get("summary") == b_nd.get("summary"):
            thrash_detected = True

    doc = {
        "schema": SCHEMA_VERSION,
        "scope": "cockpit",
        "title": f"{effort_name} — Poincaré State Map",
        "effort_dir": str(cdir),
        "section_fingerprint": fp,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_ms": build_ms,
        "node_count": len(laid_out),
        "active_node_count": sum(1 for x in laid_out if not x.get("superseded")),
        "boneyard_node_count": sum(1 for x in laid_out if x.get("superseded")),
        "corpus_raw_tokens": sum(int(x.get("full_tokens") or 0) for x in laid_out),
        "default_focus_id": active_wave_id,
        "return_map": {
            "last_step_displacement_h": return_map_disp,
            "thrash_detected": thrash_detected,
        },
        "nodes": laid_out,
    }
    if now_epoch is None:
        if len(_RAM_MAP_CACHE) >= 64:
            _RAM_MAP_CACHE.pop(next(iter(_RAM_MAP_CACHE)), None)
        _RAM_MAP_CACHE[cache_key] = (fp, doc, _build_inverted_index(laid_out))
    if persist and cdir.is_dir():
        try:
            ecg_dir.mkdir(parents=True, exist_ok=True)
            tmp = out_file.with_name(f"poincare-state.json.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, out_file)
        except OSError:
            pass
    return doc


def build_fleet_poincare_atlas(*, persist: bool = True, now_epoch: float | None = None) -> dict[str, Any]:
    """Build the fleet-wide Poincaré Atlas unifying Star Chart Goals, Cave of Wonders
    ('The List' active items + Things Done Boneyard), and all active AI Cockpits."""
    t_start = time.perf_counter()
    import paths as _paths
    import rnd_registry as _rnd

    now_ts = now_epoch if now_epoch is not None else time.time()
    raw_nodes: list[dict[str, Any]] = [
        {
            "id": "fleet-origin",
            "parent_id": "",
            "kind": "north_star",
            "title": "Anchor Fleet Origin — Star Chart · Cave of Wonders · AI Cockpits",
            "summary": "Unified hyperbolic state atlas across Star Chart Goals, Cave of Wonders Daily Command Spine, and active AI Cockpits.",
            "full_text": "Anchor Fleet Origin: click any Goal, List Item, or AI Cockpit node to Möbius-recenter the Poincaré disk and inspect its deep-memory context pack.",
            "importance": 1.0,
            "age_hours": 0.5,
            "lifecycle_state": "active",
            "source_ref": "/high-seat",
            "href": "/high-seat",
        }
    ]

    # 1. Star Chart Sector
    raw_nodes.append({
        "id": "sector-starchart",
        "parent_id": "fleet-origin",
        "kind": "star_chart_goal",
        "title": "Star Chart — Campaign Goals & Initiatives",
        "summary": "Quadrant II long-horizon Goals & Initiatives driving deep value creation.",
        "importance": 0.96,
        "age_hours": 2.0,
        "lifecycle_state": "active",
        "source_ref": "/?view=starchart",
        "href": "/?view=starchart",
    })
    camp_rm = _paths.CODE_DIR.parent / "Campaign" / "roadmap.json"
    if camp_rm.is_file():
        try:
            crm = json.loads(camp_rm.read_text(encoding="utf-8", errors="replace"))
            c_steps = crm.get("roadmap_projection") or crm.get("steps") or []
            for idx_g, g in enumerate(c_steps[:20]):
                if not isinstance(g, dict):
                    continue
                gnm = str(g.get("name") or g.get("title") or f"Goal {idx_g + 1}")
                gst = str(g.get("status") or "active").lower()
                raw_nodes.append({
                    "id": f"goal-{idx_g + 1}",
                    "parent_id": "sector-starchart",
                    "kind": "star_chart_goal",
                    "title": _truncate_clean(gnm, 84),
                    "summary": _truncate_clean(f"[{gst.upper()}] {gnm} — {g.get('done_when') or ''}", 200),
                    "importance": 0.90 if gst == "active" else 0.72,
                    "age_hours": 12.0 * (idx_g + 1),
                    "lifecycle_state": gst,
                    "source_ref": "Campaign/roadmap.json",
                    "href": "/?view=starchart",
                })
        except Exception:
            pass

    # 2. Cave of Wonders — The List Sector
    raw_nodes.append({
        "id": "sector-cave-list",
        "parent_id": "fleet-origin",
        "kind": "cave_list_item",
        "title": "Cave of Wonders — The List (Daily Command Spine)",
        "summary": "Active priority #1–#5 items, connected AI Cockpits, and Things Done archive.",
        "importance": 0.97,
        "age_hours": 1.0,
        "lifecycle_state": "active",
        "source_ref": "/high-seat",
        "href": "/high-seat",
    })
    wl_path = _paths.data_dir() / ".anchor" / "working-list-spine.json"
    if not wl_path.is_file():
        wl_path = _paths.CODE_DIR / ".anchor" / "working-list-spine.json"
    if wl_path.is_file():
        try:
            wld = json.loads(wl_path.read_text(encoding="utf-8", errors="replace"))
            for idx_t, t in enumerate((wld.get("tiles") or [])[:30]):
                if not isinstance(t, dict):
                    continue
                is_arch = bool(t.get("archived"))
                prio = int(t.get("priority") or 3)
                steps_t = [s for s in (t.get("steps") or []) if isinstance(s, dict)]
                done_n = sum(1 for s in steps_t if s.get("done"))
                imp_l = 0.35 if is_arch else max(0.60, 1.02 - 0.09 * prio)
                raw_nodes.append({
                    "id": f"wl-{t.get('id') or idx_t}",
                    "parent_id": "sector-cave-list",
                    "kind": "cave_list_item",
                    "title": f"#{prio} {_truncate_clean(str(t.get('title') or 'List Item'), 72)}",
                    "summary": f"Priority #{prio} ({t.get('category') or 'Business'}) · {done_n}/{len(steps_t)} steps done" + (" [Things Done]" if is_arch else ""),
                    "full_text": str(t.get("brainstormNotes") or t.get("title") or ""),
                    "importance": imp_l,
                    "age_hours": 96.0 if is_arch else (4.0 * prio),
                    "valid_until": "archived" if is_arch else None,
                    "lifecycle_state": "archived" if is_arch else "active",
                    "source_ref": ".anchor/working-list-spine.json",
                    "href": str(t.get("cockpitHref") or "/high-seat"),
                })
        except Exception:
            pass

    # 3. Active AI Cockpits Sector (grouped by domain/group)
    raw_nodes.append({
        "id": "sector-cockpits",
        "parent_id": "fleet-origin",
        "kind": "cockpit",
        "title": "Active AI Cockpits & Research Campaigns",
        "summary": "All active R&D projects and Steward AI Cockpits across Mathematics, Academic, Commercial, and Writing.",
        "importance": 0.96,
        "age_hours": 1.0,
        "lifecycle_state": "active",
        "source_ref": "/",
        "href": "/",
    })
    groups_seen: dict[str, str] = {}
    for proj in _rnd.list_projects(include_archived=False, include_future=False, include_retired=False):
        fp = Path(str(proj.get("folder_path") or ""))
        if not fp.is_dir():
            continue
        grp = str(proj.get("group") or "Projects").strip() or "Projects"
        if grp not in groups_seen:
            gid = f"grp-{re.sub(r'[^a-z0-9]+', '-', grp.lower()).strip('-') or 'gen'}"
            groups_seen[grp] = gid
            raw_nodes.append({
                "id": gid,
                "parent_id": "sector-cockpits",
                "kind": "wave",
                "title": f"Domain: {grp}",
                "summary": f"Active projects & AI Cockpits in {grp}",
                "importance": 0.86,
                "age_hours": 6.0,
                "lifecycle_state": "active",
                "source_ref": grp,
            })
        pid = str(proj.get("id") or "")
        p_prio = int(proj.get("priority") or 2)
        p_node_id = f"proj-{pid[:10]}"
        # Check if root or sub-efforts have ECGBERHT.md
        sub_efforts: list[tuple[str, Path]] = []
        if (fp / "ECGBERHT.md").is_file():
            sub_efforts.append(("", fp))
        try:
            for child in sorted(fp.iterdir()):
                if child.is_dir() and not child.name.startswith(".") and (child / "ECGBERHT.md").is_file():
                    sub_efforts.append((child.name, child))
        except OSError:
            pass

        href_proj = f"/steward/v1?pid={pid}" if (fp / "ECGBERHT.md").is_file() else f"/project/{pid}"
        raw_nodes.append({
            "id": p_node_id,
            "parent_id": groups_seen[grp],
            "kind": "cockpit",
            "title": str(proj.get("name") or fp.name),
            "summary": _truncate_clean(str(proj.get("blurb") or f"P{p_prio} project at {fp.name}"), 200),
            "importance": 0.92 if p_prio == 1 else 0.78,
            "age_hours": 8.0 * p_prio,
            "lifecycle_state": "active",
            "source_ref": fp.name,
            "href": href_proj,
            "poincare_href": f"/steward-static/poincare.html?pid={pid}" if sub_efforts else "",
        })
        for rel_nm, edir in sub_efforts[:6]:
            if not rel_nm:
                continue
            raw_nodes.append({
                "id": f"{p_node_id}-{re.sub(r'[^a-z0-9]+', '-', rel_nm.lower()).strip('-')}",
                "parent_id": p_node_id,
                "kind": "cockpit",
                "title": f"{proj.get('name')} :: {rel_nm}",
                "summary": f"AI Cockpit effort '{rel_nm}' in {proj.get('name')}",
                "importance": 0.90 if p_prio == 1 else 0.76,
                "age_hours": 6.0,
                "lifecycle_state": "active",
                "source_ref": f"{fp.name}/{rel_nm}",
                "href": f"/steward/v1?pid={pid}&dir={rel_nm.replace(' ', '+')}",
                "poincare_href": f"/steward-static/poincare.html?pid={pid}&dir={rel_nm.replace(' ', '+')}",
            })

    laid_out = sarkar_combinatorial_layout(raw_nodes, now_epoch=now_ts)
    build_ms = round((time.perf_counter() - t_start) * 1000.0, 3)
    doc = {
        "schema": SCHEMA_VERSION,
        "scope": "fleet",
        "title": "Anchor Fleet Poincaré Atlas (Star Chart · Cave of Wonders · AI Cockpits)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_ms": build_ms,
        "node_count": len(laid_out),
        "active_node_count": sum(1 for x in laid_out if not x.get("superseded")),
        "boneyard_node_count": sum(1 for x in laid_out if x.get("superseded")),
        "corpus_raw_tokens": sum(int(x.get("full_tokens") or 0) for x in laid_out),
        "default_focus_id": "fleet-origin",
        "nodes": laid_out,
    }
    if persist:
        try:
            out_p = _paths.CODE_DIR / ".anchor" / "fleet-poincare-atlas.json"
            out_p.parent.mkdir(parents=True, exist_ok=True)
            tmp = out_p.with_name(f"fleet-poincare-atlas.json.{os.getpid()}.tmp")
            tmp.write_text(json.dumps(doc, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            os.replace(tmp, out_p)
        except OSError:
            pass
    return doc


def build_gandalf_poincare_map(
    graded_doc: dict[str, Any],
    *,
    title: str = "Gandalf Knowledge & Risk Poincaré Map",
    now_epoch: float | None = None,
) -> dict[str, Any]:
    """Deterministically transform a graded Gandalf `advisor-output` JSON into a
    Poincaré Knowledge & Risk Map (central verdict at origin, diagnose/situate/
    anticipate/elevation sectors radially promoted by severity & value, refuted
    `kill_log` items on the outer Boneyard horocycle)."""
    t_start = time.perf_counter()
    now_ts = now_epoch if now_epoch is not None else time.time()
    verdict = str(graded_doc.get("verdict") or "Executive Assessment")
    reasoning = str(graded_doc.get("reasoning") or "")

    raw_nodes: list[dict[str, Any]] = [
        {
            "id": "gandalf-origin",
            "parent_id": "",
            "kind": "north_star",
            "title": f"Central Verdict: {_truncate_clean(verdict, 80)}",
            "summary": _truncate_clean(verdict, 230),
            "full_text": _truncate_clean(f"Verdict: {verdict}\n\n{reasoning}", 1500),
            "importance": 1.0,
            "age_hours": 0.5,
            "lifecycle_state": "active",
            "source_ref": "verdict",
        }
    ]
    sectors = [
        ("sec-diagnose", "Diagnosis & Structural Traps", 0.94),
        ("sec-situate", "Best-in-Class Landscape (Situate)", 0.90),
        ("sec-elevate", "High-Value Forward Elevations", 0.93),
        ("sec-anticipate", "Coming Problems (Premortem)", 0.88),
        ("sec-boneyard", "Refuted / Rejected Hypotheses", 0.45),
    ]
    for sid, stitle, simp in sectors:
        raw_nodes.append({
            "id": sid,
            "parent_id": "gandalf-origin",
            "kind": "wave",
            "title": stitle,
            "summary": stitle,
            "importance": simp,
            "age_hours": 1.0,
            "lifecycle_state": "active",
        })

    sev_imp = {"critical": 0.97, "major": 0.89, "minor": 0.72}
    for idx_f, f in enumerate(graded_doc.get("findings") or []):
        if not isinstance(f, dict):
            continue
        k = str(f.get("kind") or "diagnose").lower()
        p_sec = "sec-situate" if k == "situate" else ("sec-anticipate" if k == "anticipate" else "sec-diagnose")
        imp = sev_imp.get(str(f.get("severity") or "").lower(), 0.84)
        fv = str(f.get("verdict") or "")
        fr = str(f.get("reasoning") or "")
        extra = ""
        if k == "anticipate" and f.get("future_state_condition"):
            extra = f"\nFuture condition: {f.get('future_state_condition')}\nEnabling assumption: {f.get('enabling_assumption') or ''}"
        raw_nodes.append({
            "id": f"finding-{idx_f + 1}",
            "parent_id": p_sec,
            "kind": f"gandalf_{k}",
            "title": _truncate_clean(fv or fr, 84),
            "summary": _truncate_clean(f"[{f.get('rung') or 'CHECKED'}] {fv}", 220),
            "full_text": _truncate_clean(f"Verdict: {fv}\n\nReasoning: {fr}{extra}", 1200),
            "importance": imp,
            "age_hours": 1.5,
            "lifecycle_state": "active",
            "source_ref": str(f.get("rung") or k),
        })

    val_imp = {"high": 0.95, "medium": 0.82, "low": 0.65}
    for idx_e, el in enumerate(graded_doc.get("elevations") or []):
        if not isinstance(el, dict):
            continue
        ev = str(el.get("verdict") or "")
        er = str(el.get("reasoning") or "")
        defeater = str(el.get("what_would_refute_it") or "")
        raw_nodes.append({
            "id": f"elevation-{idx_e + 1}",
            "parent_id": "sec-elevate",
            "kind": "gandalf_elevation",
            "title": _truncate_clean(ev or er, 84),
            "summary": _truncate_clean(f"[{el.get('tier') or 'ELEVATION'}] {ev}", 220),
            "full_text": _truncate_clean(f"Recommendation: {ev}\n\nReasoning: {er}\n\nNamed Defeater: {defeater}", 1200),
            "importance": val_imp.get(str(el.get("value_if_true") or "").lower(), 0.85),
            "age_hours": 1.0,
            "lifecycle_state": "active",
            "source_ref": str(el.get("tier") or "elevation"),
        })

    kill_log = graded_doc.get("kill_log") if isinstance(graded_doc.get("kill_log"), dict) else {}
    k_items = list(kill_log.get("elevations") or []) + list(kill_log.get("findings") or [])
    for idx_k, ki in enumerate(k_items):
        if not isinstance(ki, dict):
            continue
        kv = str(ki.get("verdict") or ki.get("reasoning") or f"Rejected Hypothesis {idx_k + 1}")
        raw_nodes.append({
            "id": f"killed-{idx_k + 1}",
            "parent_id": "sec-boneyard",
            "kind": "boneyard",
            "title": f"[REFUTED] {_truncate_clean(kv, 74)}",
            "summary": _truncate_clean(f"Refuted: {kv}", 200),
            "full_text": _truncate_clean(json.dumps(ki, ensure_ascii=False), 900),
            "importance": 0.30,
            "age_hours": 48.0,
            "valid_until": "refuted",
            "lifecycle_state": "refuted",
            "source_ref": "kill_log",
        })

    laid_out = sarkar_combinatorial_layout(raw_nodes, now_epoch=now_ts)
    return {
        "schema": SCHEMA_VERSION,
        "scope": "gandalf",
        "title": title,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "build_ms": round((time.perf_counter() - t_start) * 1000.0, 3),
        "node_count": len(laid_out),
        "active_node_count": sum(1 for x in laid_out if not x.get("superseded")),
        "boneyard_node_count": sum(1 for x in laid_out if x.get("superseded")),
        "corpus_raw_tokens": sum(int(x.get("full_tokens") or 0) for x in laid_out),
        "default_focus_id": "gandalf-origin",
        "nodes": laid_out,
    }


# ── 4. Interactive 2D Möbius-Zoomable Poincaré Disk HTML Viewer ─────────────


def render_poincare_viewer_html(
    map_doc: dict[str, Any],
    *,
    cockpit_options: list[dict[str, str]] | None = None,
    initial_budget: int = 16_384,
) -> str:
    """Render a standalone, interactive 2D Poincaré Disk State Observatory page
    with real-time client-side Möbius gyrovector re-centering, true hyperbolic
    geodesic arcs, and live MERA-Poincaré context-window inspection."""
    title_esc = _html.escape(str(map_doc.get("title") or "Poincaré Deep-Memory State Map"))
    initial_pack = parse_deep_memory_window(map_doc, budget_tokens=initial_budget)
    payload_json = json.dumps(map_doc, ensure_ascii=False).replace("</", "<\\/")
    pack_json = json.dumps(initial_pack, ensure_ascii=False).replace("</", "<\\/")

    opts_html = ['<option value="/steward-static/poincare.html?mode=fleet">🌌 Fleet Atlas (Star Chart + Cave + All Cockpits)</option>']
    cur_dir = str(map_doc.get("effort_dir") or "")
    for opt in (cockpit_options or []):
        href_o = _html.escape(str(opt.get("href") or ""))
        lbl_o = _html.escape(str(opt.get("label") or ""))
        sel_attr = " selected" if opt.get("effort_dir") and str(opt.get("effort_dir")) == cur_dir else ""
        opts_html.append(f'<option value="{href_o}"{sel_attr}>🛸 {lbl_o}</option>')

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title_esc} — Anchor Poincaré Observatory</title>
<style>
  :root {{
    --bg: #070b14;
    --panel: #0f172a;
    --border: #1e293b;
    --ink: #f1f5f9;
    --muted: #94a3b8;
    --sky: #38bdf8;
    --emerald: #10b981;
    --amber: #f59e0b;
    --purple: #a78bfa;
    --rose: #fb7185;
    --mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--ink);
    font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    font-size: 13.5px; line-height: 1.5;
  }}
  .top-bar {{
    display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap;
    padding: 12px 20px; background: #0b1120; border-bottom: 1px solid var(--border);
  }}
  .top-title {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }}
  .top-title h1 {{ margin: 0; font-size: 16px; font-weight: 800; letter-spacing: -0.01em; color: #f8fafc; }}
  .badge {{
    display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px; border-radius: 999px;
    font-size: 11px; font-weight: 700; font-family: var(--mono);
    background: rgba(56,189,248,0.13); color: #7dd3fc; border: 1px solid rgba(56,189,248,0.35);
  }}
  .badge.emerald {{ background: rgba(16,185,129,0.14); color: #6ee7b7; border-color: rgba(16,185,129,0.38); }}
  .controls {{ display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }}
  select, input[type="search"], button, a.nav-btn {{
    padding: 6px 10px; border-radius: 7px; border: 1px solid #334155;
    background: #0f172a; color: #f1f5f9; font-size: 12.5px; font-weight: 600;
    text-decoration: none; cursor: pointer;
  }}
  button:hover, a.nav-btn:hover {{ border-color: var(--sky); color: #7dd3fc; }}
  button.primary {{ background: rgba(16,185,129,0.16); border-color: rgba(16,185,129,0.5); color: #6ee7b7; }}
  .layout {{
    display: grid; grid-template-columns: minmax(480px, 660px) 1fr; gap: 18px;
    padding: 18px 20px; max-width: 1640px; margin: 0 auto; align-items: start;
  }}
  @media (max-width: 1100px) {{ .layout {{ grid-template-columns: 1fr; }} }}
  .card {{
    background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 14px 16px;
  }}
  .disk-wrap {{ display: flex; flex-direction: column; align-items: center; gap: 10px; }}
  svg#poincareDiskSvg {{
    width: 100%; max-width: 620px; height: auto; aspect-ratio: 1 / 1;
    border-radius: 50%; background: radial-gradient(circle at 50% 50%, #111c33 0%, #09101f 68%, #050811 100%);
    box-shadow: 0 0 0 1px rgba(56,189,248,0.28), 0 18px 42px rgba(0,0,0,0.55);
    user-select: none;
  }}
  .legend {{
    display: flex; flex-wrap: wrap; gap: 10px; justify-content: center; font-size: 11.5px; color: var(--muted);
  }}
  .legend span {{ display: inline-flex; align-items: center; gap: 5px; }}
  .dot {{ width: 9px; height: 9px; border-radius: 50%; display: inline-block; }}
  .inspector-col {{ display: flex; flex-direction: column; gap: 14px; }}
  .node-card-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; flex-wrap: wrap; }}
  .node-card-head h2 {{ margin: 0; font-size: 15.5px; color: #f8fafc; }}
  .meta-grid {{
    display: grid; grid-template-columns: repeat(auto-fit, minmax(125px, 1fr)); gap: 8px; margin: 10px 0;
  }}
  .meta-cell {{
    padding: 7px 9px; border-radius: 8px; background: #080e1a; border: 1px solid #1e293b;
  }}
  .meta-cell .k {{ font-size: 10.5px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
  .meta-cell .v {{ font-size: 13px; font-weight: 700; font-family: var(--mono); color: #e2e8f0; margin-top: 2px; }}
  .node-full-box {{
    padding: 10px 12px; border-radius: 8px; background: #070c16; border: 1px solid #1e293b;
    font-size: 12.5px; color: #cbd5e1; white-space: pre-wrap; max-height: 180px; overflow-y: auto;
  }}
  .pack-list {{ display: flex; flex-direction: column; gap: 6px; max-height: 360px; overflow-y: auto; margin-top: 8px; }}
  .pack-row {{
    padding: 7px 10px; border-radius: 7px; background: #080e1a; border: 1px solid #1e293b;
    display: flex; flex-direction: column; gap: 3px; cursor: pointer;
  }}
  .pack-row:hover {{ border-color: rgba(56,189,248,0.5); }}
  .pack-row-top {{ display: flex; align-items: center; justify-content: space-between; gap: 8px; }}
  .bc-strip {{ display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }}
  .bc-chip {{
    padding: 3px 8px; border-radius: 6px; font-size: 11.5px; background: rgba(167,139,250,0.12);
    border: 1px solid rgba(167,139,250,0.35); color: #ddd6fe; cursor: pointer;
  }}
  .bc-chip:hover {{ background: rgba(167,139,250,0.24); }}
</style>
</head>
<body>
<header class="top-bar">
  <div class="top-title">
    <h1>&#129517; {title_esc}</h1>
    <span class="badge" id="pmStatsBadge">{len(map_doc.get("nodes") or [])} nodes &middot; {map_doc.get("corpus_raw_tokens", 0):,} raw tok &middot; build {map_doc.get("build_ms", 0)}ms</span>
    <span class="badge emerald" id="pmFocusBadge">Origin: { _html.escape(str(initial_pack.get("focus_title") or "Root")) }</span>
  </div>
  <div class="controls">
    <select id="pmScopeSelect" title="Switch Poincaré State Map Scope">
      {"".join(opts_html)}
    </select>
    <input type="search" id="pmQueryInput" placeholder="Focus / query deep memory..." style="min-width:200px">
    <select id="pmBudgetSelect" title="Active Context Window Token Budget">
      <option value="4096">Budget: 4K tok</option>
      <option value="8192">Budget: 8K tok</option>
      <option value="16384" selected>Budget: 16K tok</option>
      <option value="32768">Budget: 32K tok</option>
      <option value="65536">Budget: 64K tok</option>
    </select>
    <button type="button" class="primary" id="pmResetOriginBtn" title="Möbius-translate root North Star back to (0, 0)">&#8634; Reset Origin (0,0)</button>
    <a class="nav-btn" href="/high-seat">&#8592; Cave of Wonders</a>
    <a class="nav-btn" href="/?view=starchart">&#127775; Star Chart</a>
  </div>
</header>

<main class="layout">
  <section class="card disk-wrap">
    <div style="font-size:12px;color:#94a3b8;text-align:center">
      <b>Click any node</b> to execute an isometric <b>M&ouml;bius gyrovector translation</b> <code>T<sub>-a</sub>(z) = (z - a)/(1 - &overline;a&middot;z)</code>, bringing that branch to full center resolution.
    </div>
    <svg id="poincareDiskSvg" viewBox="-1.06 -1.06 2.12 2.12" aria-label="Interactive 2D Poincaré Disk State Map"></svg>
    <div class="legend">
      <span><i class="dot" style="background:#f59e0b"></i> North Star / Origin</span>
      <span><i class="dot" style="background:#a78bfa"></i> Star Chart Goal / Situate</span>
      <span><i class="dot" style="background:#38bdf8"></i> AI Cockpit / Wave</span>
      <span><i class="dot" style="background:#10b981"></i> Deliverable / Elevation</span>
      <span><i class="dot" style="background:#fb7185"></i> Decision / Critical Constraint</span>
      <span><i class="dot" style="background:#64748b"></i> Outer Boneyard / Superseded</span>
    </div>
  </section>

  <section class="inspector-col">
    <div class="card" id="pmNodeInspector">
      <div class="node-card-head">
        <div>
          <span class="badge" id="pmSelKind">north_star</span>
          <h2 id="pmSelTitle" style="margin-top:5px">Select any node on the Poincaré Disk</h2>
        </div>
        <div id="pmSelLinks" style="display:flex;gap:6px;flex-wrap:wrap"></div>
      </div>
      <div class="meta-grid">
        <div class="meta-cell"><div class="k">Effective Radius r_eff</div><div class="v" id="pmSelReff">0.00</div></div>
        <div class="meta-cell"><div class="k">Importance I(u)</div><div class="v" id="pmSelImp">1.00</div></div>
        <div class="meta-cell"><div class="k">Survival &psi;(u, t)</div><div class="v" id="pmSelSurv">1.00</div></div>
        <div class="meta-cell"><div class="k">Tokens (Sum / Full)</div><div class="v" id="pmSelTok">32 / 256</div></div>
      </div>
      <div class="node-full-box" id="pmSelBody"></div>
    </div>

    <div class="card">
      <div class="node-card-head">
        <div>
          <h2 style="margin:0;font-size:14.5px">&#9889; MERA-Poincar&eacute; Deep-Memory Context Window</h2>
          <div style="font-size:11.5px;color:#94a3b8;margin-top:2px" id="pmPackStats"></div>
        </div>
      </div>
      <div class="pack-list" id="pmPackList"></div>
      <div style="margin-top:10px;padding-top:8px;border-top:1px solid #1e293b">
        <div style="font-size:11px;font-weight:700;color:#c4b5fd;text-transform:uppercase;letter-spacing:.04em">
          &#128301; 12-Token Horizon Breadcrumbs (Click to M&ouml;bius-Zoom Peripheral Subtree)
        </div>
        <div class="bc-strip" id="pmBreadcrumbs"></div>
      </div>
    </div>
  </section>
</main>

<script>
(function() {{
  const MAP = {payload_json};
  let curPack = {pack_json};
  const baseNodes = (MAP.nodes || []).map(n => Object.assign({{}}, n));
  const byId = {{}};
  baseNodes.forEach(n => {{ byId[String(n.id)] = n; }});

  // Current display coordinates in unit disk
  let dispCoords = {{}};
  baseNodes.forEach(n => {{ dispCoords[n.id] = [Number(n.disk_x || 0), Number(n.disk_y || 0)]; }});
  let selectedId = String(MAP.default_focus_id || (baseNodes[0] && baseNodes[0].id) || '');

  const COLORS = {{
    north_star: '#f59e0b',
    star_chart_goal: '#a78bfa',
    gandalf_situate: '#a78bfa',
    cave_list_item: '#38bdf8',
    cockpit: '#38bdf8',
    wave: '#0ea5e9',
    deliverable: '#10b981',
    gandalf_elevation: '#10b981',
    decision: '#fb7185',
    gandalf_diagnose: '#fb7185',
    gandalf_anticipate: '#f97316',
    turn: '#94a3b8',
    boneyard: '#475569'
  }};

  function mobiusTranslate(zx, zy, fx, fy) {{
    const nr = zx - fx, ni = zy - fy;
    const dr = 1.0 - (fx * zx + fy * zy);
    const di = -(fx * zy - fy * zx);
    const den = dr * dr + di * di;
    if (den < 1e-12) return [0, 0];
    let ox = (nr * dr + ni * di) / den;
    let oy = (ni * dr - nr * di) / den;
    const m = Math.hypot(ox, oy);
    if (m > 0.975) {{ ox *= 0.975 / m; oy *= 0.975 / m; }}
    return [ox, oy];
  }}

  function geodesicPathD(x1, y1, x2, y2) {{
    const cross = x1 * y2 - y1 * x2;
    const dSeg = Math.hypot(x2 - x1, y2 - y1);
    if (Math.abs(cross) < 1e-3 || dSeg < 0.03) {{
      return `M ${{x1.toFixed(4)}} ${{y1.toFixed(4)}} L ${{x2.toFixed(4)}} ${{y2.toFixed(4)}}`;
    }}
    // Circle orthogonal to unit disk passing through p1 and p2:
    // Center C satisfies 2*(x1*Cx + y1*Cy) = x1^2 + y1^2 + 1 and 2*(x2*Cx + y2*Cy) = x2^2 + y2^2 + 1
    const r1sq = 0.5 * (x1 * x1 + y1 * y1 + 1.0);
    const r2sq = 0.5 * (x2 * x2 + y2 * y2 + 1.0);
    const cx = (r1sq * y2 - r2sq * y1) / cross;
    const cy = (x1 * r2sq - x2 * r1sq) / cross;
    const R = Math.sqrt(Math.max(0.0001, cx * cx + cy * cy - 1.0));
    if (!isFinite(R) || R > 25.0) {{
      return `M ${{x1.toFixed(4)}} ${{y1.toFixed(4)}} L ${{x2.toFixed(4)}} ${{y2.toFixed(4)}}`;
    }}
    const sweep = cross > 0 ? 0 : 1;
    return `M ${{x1.toFixed(4)}} ${{y1.toFixed(4)}} A ${{R.toFixed(4)}} ${{R.toFixed(4)}} 0 0 ${{sweep}} ${{x2.toFixed(4)}} ${{y2.toFixed(4)}}`;
  }}

  function clientParsePack(focusId, queryStr, budgetTok) {{
    const t0 = performance.now();
    const fq = byId[focusId] || baseNodes[0];
    if (!fq) return curPack;
    const rq = Number(fq.r_eff || 0), thq = Number(fq.theta || 0);
    const qToks = String(queryStr || '').toLowerCase().match(/[a-z0-9]{{3,}}/g) || [];

    function hypDist(r1, t1, r2, t2) {{
      let ang = Math.abs(t1 - t2) % (2 * Math.PI);
      if (ang > Math.PI) ang = 2 * Math.PI - ang;
      const sd = Math.sinh(Math.abs(r1 - r2) / 2);
      const sa = Math.sqrt(Math.max(0, Math.sinh(r1) * Math.sinh(r2))) * Math.abs(Math.sin(ang / 2));
      return 2 * Math.asinh(Math.hypot(sd, sa));
    }}

    function ancestors(id) {{
      const out = [];
      let cur = byId[id];
      const seen = new Set();
      while (cur && !seen.has(cur.id)) {{
        seen.add(cur.id);
        out.push(cur);
        cur = cur.parent_id ? byId[cur.parent_id] : null;
      }}
      return out;
    }}

    const sel = {{}};
    let used = 0;
    ancestors(fq.id).reverse().forEach(a => {{
      const cs = Number(a.summary_tokens || 16);
      if (used + cs <= budgetTok) {{ sel[a.id] = 1; used += cs; }}
    }});

    const items = [];
    const cands = [];
    baseNodes.forEach(nd => {{
      if (nd.superseded) return;
      const imp = Number(nd.importance || 0.5);
      if (imp < 0.20 && !sel[nd.id]) return;
      const dh = hypDist(rq, thq, Number(nd.r_eff || 0), Number(nd.theta || 0));
      let qb = 1.0;
      if (qToks.length) {{
        const hay = ((nd.title || '') + ' ' + (nd.summary || '')).toLowerCase();
        qToks.forEach(t => {{ if (hay.includes(t)) qb += 0.65; }});
      }}
      const u = Math.pow(imp, 2.5) * Number(nd.survival || imp) * Math.exp(-0.28 * dh) * qb;
      cands.push([u, nd]);
      const cs = Math.max(8, Number(nd.summary_tokens || 16));
      const cf = Math.max(cs, Number(nd.full_tokens || cs));
      if (!sel[nd.id]) items.push([(0.55 * u) / cs, nd, 1, cs]);
      if (cf > cs) items.push([(0.45 * u) / (cf - cs), nd, 2, cf - cs]);
      else if (sel[nd.id]) sel[nd.id] = 2;
    }});
    items.sort((a, b) => b[0] - a[0]);
    items.forEach(([_, nd, tm, dt]) => {{
      if (tm === 1 && !sel[nd.id]) {{
        const miss = ancestors(nd.id).filter(a => !sel[a.id]);
        const ac = miss.reduce((s, a) => s + Number(a.summary_tokens || 16), 0);
        if (used + ac + dt <= budgetTok) {{
          miss.reverse().forEach(a => {{ sel[a.id] = 1; }});
          sel[nd.id] = Number(nd.full_tokens || dt) > dt ? 1 : 2;
          used += ac + dt;
        }}
      }} else if (tm === 2 && sel[nd.id] === 1) {{
        if (used + dt <= budgetTok) {{ sel[nd.id] = 2; used += dt; }}
      }}
    }});

    cands.sort((a, b) => b[0] - a[0]);
    const bcs = [];
    for (const [_, nd] of cands) {{
      if (!sel[nd.id]) {{
        bcs.push({{ id: nd.id, title: nd.title || nd.id, source_ref: nd.source_ref || '' }});
        if (bcs.length >= 8) break;
      }}
    }}
    const selectedNodes = Object.keys(sel).map(k => {{
      const nd = byId[k];
      const m = sel[k];
      return {{
        id: nd.id, kind: nd.kind, title: nd.title,
        resolution: m === 2 ? 'verbatim' : 'summary',
        tokens: m === 2 ? nd.full_tokens : nd.summary_tokens,
        r_eff: nd.r_eff, text: m === 2 ? nd.full_text : nd.summary,
        source_ref: nd.source_ref || ''
      }};
    }});
    const rawTot = Math.max(1, Number(MAP.corpus_raw_tokens || 1));
    return {{
      focus_node_id: fq.id, focus_title: fq.title,
      budget_tokens: budgetTok, used_tokens: used, corpus_raw_tokens: rawTot,
      compression_ratio: (rawTot / Math.max(1, used)).toFixed(1),
      parse_ms: (performance.now() - t0).toFixed(2),
      selected_nodes: selectedNodes, horizon_breadcrumbs: bcs
    }};
  }}

  function renderDisk() {{
    const svg = document.getElementById('poincareDiskSvg');
    const parts = [];
    // Outer unit boundary + geodesic horizon shells
    parts.push('<circle cx="0" cy="0" r="1.0" fill="none" stroke="#334155" stroke-width="0.008"/>');
    [0.32, 0.62, 0.84, 0.93].forEach((r, idx) => {{
      const dash = idx === 3 ? '0.02,0.02' : '0.012,0.016';
      const col = idx === 3 ? 'rgba(251,113,133,0.28)' : 'rgba(56,189,248,0.16)';
      parts.push(`<circle cx="0" cy="0" r="${{r}}" fill="none" stroke="${{col}}" stroke-width="0.004" stroke-dasharray="${{dash}}"/>`);
    }});

    const selSet = new Set((curPack.selected_nodes || []).map(x => String(x.id)));

    // Geodesic parent-child arcs
    baseNodes.forEach(nd => {{
      if (!nd.parent_id || !dispCoords[nd.parent_id] || !dispCoords[nd.id]) return;
      const [x1, y1] = dispCoords[nd.parent_id];
      const [x2, y2] = dispCoords[nd.id];
      const inPack = selSet.has(String(nd.id)) && selSet.has(String(nd.parent_id));
      const stroke = nd.superseded ? 'rgba(100,116,139,0.22)' : (inPack ? 'rgba(56,189,248,0.58)' : 'rgba(148,163,184,0.20)');
      const sw = inPack ? '0.0065' : '0.0032';
      parts.push(`<path d="${{geodesicPathD(x1, y1, x2, y2)}}" fill="none" stroke="${{stroke}}" stroke-width="${{sw}}"/>`);
    }});

    // Nodes (drawn back-to-front so center/selected sit cleanly on top)
    const sorted = baseNodes.slice().sort((a, b) => {{
      const da = Math.hypot(...(dispCoords[a.id] || [0, 0]));
      const db = Math.hypot(...(dispCoords[b.id] || [0, 0]));
      return db - da;
    }});

    sorted.forEach(nd => {{
      const [x, y] = dispCoords[nd.id] || [0, 0];
      const r2 = Math.min(0.96, x * x + y * y);
      const conformal = Math.pow(1.0 - r2, 0.52);
      const baseR = 0.016 + 0.030 * Number(nd.importance || 0.5);
      const rad = Math.max(0.009, baseR * conformal);
      const col = nd.superseded ? COLORS.boneyard : (COLORS[nd.kind] || '#38bdf8');
      const isSel = String(nd.id) === String(selectedId);
      const ring = isSel ? `<circle cx="${{x.toFixed(4)}}" cy="${{y.toFixed(4)}}" r="${{(rad + 0.016).toFixed(4)}}" fill="none" stroke="#f8fafc" stroke-width="0.006"/>` : '';
      const escTitle = String(nd.title || nd.id).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');
      let lbl = '';
      if (Math.sqrt(r2) < 0.56 || isSel) {{
        const shortLbl = escTitle.length > 28 ? escTitle.slice(0, 27) + '…' : escTitle;
        lbl = `<text x="${{x.toFixed(4)}}" y="${{(y - rad - 0.012).toFixed(4)}}" text-anchor="middle" fill="#e2e8f0" font-size="0.036" font-weight="600" pointer-events="none">${{shortLbl}}</text>`;
      }}
      parts.push(
        `<g class="pm-node" data-node-id="${{nd.id}}" style="cursor:pointer">` +
          ring +
          `<circle cx="${{x.toFixed(4)}}" cy="${{y.toFixed(4)}}" r="${{rad.toFixed(4)}}" fill="${{col}}" fill-opacity="${{nd.superseded ? '0.52' : '0.92'}}" stroke="#0f172a" stroke-width="0.004">` +
            `<title>${{escTitle}} (r_eff=${{nd.r_eff}}, I=${{nd.importance}})</title>` +
          `</circle>` +
          lbl +
        `</g>`
      );
    }});

    svg.innerHTML = parts.join('');
  }}

  function renderInspector() {{
    const nd = byId[selectedId] || baseNodes[0];
    if (!nd) return;
    document.getElementById('pmFocusBadge').textContent = 'Focus: ' + String(nd.title || nd.id).slice(0, 42);
    document.getElementById('pmSelKind').textContent = (nd.superseded ? 'boneyard / superseded · ' : '') + (nd.kind || 'node');
    document.getElementById('pmSelTitle').textContent = nd.title || nd.id;
    document.getElementById('pmSelReff').textContent = Number(nd.r_eff || 0).toFixed(3);
    document.getElementById('pmSelImp').textContent = Number(nd.importance || 0).toFixed(2);
    document.getElementById('pmSelSurv').textContent = Number(nd.survival || 0).toFixed(3);
    document.getElementById('pmSelTok').textContent = `${{nd.summary_tokens || 0}} / ${{nd.full_tokens || 0}}`;
    document.getElementById('pmSelBody').textContent = nd.full_text || nd.summary || '';

    const linksBox = document.getElementById('pmSelLinks');
    const links = [];
    if (nd.poincare_href) {{
      links.push(`<a class="nav-btn" href="${{nd.poincare_href}}">&#129517; Open Cockpit Map</a>`);
    }}
    if (nd.href) {{
      links.push(`<a class="nav-btn" href="${{nd.href}}" target="_blank" rel="noopener">&#8599; Open Surface</a>`);
    }}
    linksBox.innerHTML = links.join('');

    document.getElementById('pmPackStats').textContent =
      `Used ${{curPack.used_tokens.toLocaleString()}} / ${{curPack.budget_tokens.toLocaleString()}} tok · ${{curPack.compression_ratio}}x compression · parsed in ${{curPack.parse_ms}} ms (${{(curPack.selected_nodes || []).length}} nodes)`;

    const packList = document.getElementById('pmPackList');
    packList.innerHTML = (curPack.selected_nodes || []).map(it => {{
      const pillCol = it.resolution === 'verbatim' ? 'emerald' : '';
      const escT = String(it.title || it.id).replace(/&/g, '&amp;').replace(/</g, '&lt;');
      const escB = String(it.text || '').slice(0, 170).replace(/&/g, '&amp;').replace(/</g, '&lt;');
      return (
        `<div class="pack-row" data-zoom-id="${{it.id}}">` +
          `<div class="pack-row-top">` +
            `<b style="font-size:12.5px;color:#f1f5f9">${{escT}}</b>` +
            `<span class="badge ${{pillCol}}">${{it.resolution.toUpperCase()}} &middot; ${{it.tokens}} tok</span>` +
          `</div>` +
          `<div style="font-size:11.5px;color:#94a3b8">${{escB}}</div>` +
        `</div>`
      );
    }}).join('');

    const bcHost = document.getElementById('pmBreadcrumbs');
    const bcs = curPack.horizon_breadcrumbs || [];
    bcHost.innerHTML = bcs.length
      ? bcs.map(b => `<button type="button" class="bc-chip" data-zoom-id="${{b.id}}">&#128301; ${{String(b.title || b.id).slice(0, 44).replace(/&/g, '&amp;').replace(/</g, '&lt;')}}</button>`).join('')
      : '<span style="font-size:11.5px;color:#64748b">Entire active campaign fits inside current token budget.</span>';
  }}

  function animateMobiusFocus(targetId) {{
    const target = byId[targetId];
    if (!target) return;
    selectedId = String(targetId);
    const [fx, fy] = dispCoords[targetId] || [0, 0];
    const startCoords = Object.assign({{}}, dispCoords);
    const endCoords = {{}};
    baseNodes.forEach(nd => {{
      const [sx, sy] = startCoords[nd.id] || [0, 0];
      endCoords[nd.id] = mobiusTranslate(sx, sy, fx, fy);
    }});
    const budget = parseInt(document.getElementById('pmBudgetSelect').value || '16384', 10);
    const q = document.getElementById('pmQueryInput').value || '';
    curPack = clientParsePack(selectedId, q, budget);

    const dur = 260;
    const tStart = performance.now();
    function frame(now) {{
      const t = Math.min(1, (now - tStart) / dur);
      const ease = 1 - Math.pow(1 - t, 3);
      baseNodes.forEach(nd => {{
        const [sx, sy] = startCoords[nd.id];
        const [ex, ey] = endCoords[nd.id];
        dispCoords[nd.id] = [sx + (ex - sx) * ease, sy + (ey - sy) * ease];
      }});
      renderDisk();
      if (t < 1) requestAnimationFrame(frame);
      else renderInspector();
    }}
    requestAnimationFrame(frame);
  }}

  document.getElementById('poincareDiskSvg').addEventListener('click', e => {{
    const g = e.target.closest('[data-node-id]');
    if (g) animateMobiusFocus(g.getAttribute('data-node-id'));
  }});
  document.addEventListener('click', e => {{
    const z = e.target.closest('[data-zoom-id]');
    if (z) animateMobiusFocus(z.getAttribute('data-zoom-id'));
  }});
  document.getElementById('pmResetOriginBtn').addEventListener('click', () => {{
    baseNodes.forEach(n => {{ dispCoords[n.id] = [Number(n.disk_x || 0), Number(n.disk_y || 0)]; }});
    selectedId = String((baseNodes[0] && baseNodes[0].id) || '');
    const budget = parseInt(document.getElementById('pmBudgetSelect').value || '16384', 10);
    curPack = clientParsePack(selectedId, document.getElementById('pmQueryInput').value || '', budget);
    renderDisk();
    renderInspector();
  }});
  document.getElementById('pmBudgetSelect').addEventListener('change', () => {{
    const budget = parseInt(document.getElementById('pmBudgetSelect').value || '16384', 10);
    curPack = clientParsePack(selectedId, document.getElementById('pmQueryInput').value || '', budget);
    renderDisk();
    renderInspector();
  }});
  document.getElementById('pmQueryInput').addEventListener('input', e => {{
    const q = e.target.value || '';
    const budget = parseInt(document.getElementById('pmBudgetSelect').value || '16384', 10);
    curPack = clientParsePack(selectedId, q, budget);
    renderDisk();
    renderInspector();
  }});
  document.getElementById('pmScopeSelect').addEventListener('change', e => {{
    if (e.target.value) window.location.href = e.target.value;
  }});

  renderDisk();
  renderInspector();
}})();
</script>
</body>
</html>
"""


def fast_turn_recall_capsule(
    effort_dir: str | Path,
    *,
    query: str = "",
    budget_tokens: int = 900,
) -> str:
    """Sub-millisecond live per-turn Poincaré context rewrite for active AI Cockpits:
    checks the 6-file section fingerprint (`~0.06 ms`), hits `_RAM_MAP_CACHE` (or rebuilds
    if a file changed), locates the Focus Anchor `a` via the inverted token index, and
    returns a compact Möbius-focused recall capsule + 12-token Horizon Signposts."""
    cdir = Path(effort_dir)
    if not cdir.is_dir() or not (cdir / "ECGBERHT.md").is_file():
        return ""
    mdoc = build_cockpit_poincare_map(cdir, persist=True)
    nodes = mdoc.get("nodes") or []
    if len(nodes) <= 2:
        return ""
    cache_key = str(cdir.resolve())
    ram_entry = _RAM_MAP_CACHE.get(cache_key)
    inv_idx = ram_entry[2] if ram_entry is not None else None
    focus_id = resolve_focus_node_id(nodes, query=query, inverted_index=inv_idx)
    pack = parse_deep_memory_window(mdoc, focus_id=focus_id, query=query, budget_tokens=budget_tokens, inverted_index=inv_idx)
    return str(pack.get("formatted_capsule") or "").strip()


def resolve_contained_effort_dir(project_root: str | Path | None, subdir: str = "") -> Path | None:
    """Resolve an optional effort subdirectory strictly contained inside `project_root`."""
    if not project_root:
        return None
    try:
        base = Path(project_root).resolve()
    except OSError:
        return None
    if not base.is_dir():
        return None
    rel = str(subdir or "").strip().strip("/\\")
    if not rel:
        return base
    if ".." in Path(rel).parts:
        return None
    try:
        cand = (base / rel).resolve()
        cand.relative_to(base)
    except (OSError, ValueError):
        return None
    return cand if cand.is_dir() else None


def handle_poincare_api_get(project_root: str | Path | None, qs: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Serve `GET /api/steward/poincare` for fleet-wide or per-cockpit state maps."""
    mode = str(qs.get("mode") or "").strip().lower()
    force = str(qs.get("force") or "") in ("1", "true", "yes")
    try:
        budget = max(512, min(262_144, int(qs.get("budget") or 16_384)))
    except (TypeError, ValueError):
        budget = 16_384
    focus_id = str(qs.get("focus_id") or "").strip() or None
    query = str(qs.get("query") or "").strip()

    if mode == "fleet" or not project_root:
        mdoc = build_fleet_poincare_atlas(persist=True)
    else:
        edir = resolve_contained_effort_dir(project_root, str(qs.get("dir") or ""))
        if edir is None:
            return {"ok": False, "error": "invalid effort directory"}, 400
        mdoc = build_cockpit_poincare_map(edir, persist=True, force=force)

    if focus_id:
        mdoc = mobius_recenter_map(mdoc, focus_id)
    pack = parse_deep_memory_window(mdoc, focus_id=focus_id, query=query, budget_tokens=budget)
    return {"ok": True, "map": mdoc, "window": pack}, 200


def handle_poincare_api_post(project_root: str | Path | None, body: dict[str, Any]) -> tuple[dict[str, Any], int]:
    """Serve `POST /api/steward/poincare` (`recenter`, `parse`, or `rebuild`)."""
    action = str(body.get("action") or "parse").strip().lower()
    mode = str(body.get("mode") or "").strip().lower()
    try:
        budget = max(512, min(262_144, int(body.get("budget") or 16_384)))
    except (TypeError, ValueError):
        budget = 16_384
    focus_id = str(body.get("focus_id") or "").strip() or None
    query = str(body.get("query") or "").strip()

    if mode == "fleet" or not project_root:
        mdoc = build_fleet_poincare_atlas(persist=True)
    else:
        edir = resolve_contained_effort_dir(project_root, str(body.get("dir") or ""))
        if edir is None:
            return {"ok": False, "error": "invalid effort directory"}, 400
        mdoc = build_cockpit_poincare_map(edir, persist=True, force=(action == "rebuild"))

    if focus_id and action in ("recenter", "parse"):
        mdoc = mobius_recenter_map(mdoc, focus_id)
    pack = parse_deep_memory_window(mdoc, focus_id=focus_id, query=query, budget_tokens=budget)
    return {"ok": True, "action": action, "map": mdoc, "window": pack}, 200


def render_poincare_route_html(project_root: str | Path | None, qs: dict[str, Any]) -> str:
    """Serve `GET /poincare-map` HTML Observatory for Fleet Atlas or a specific AI Cockpit."""
    mode = str(qs.get("mode") or "").strip().lower()
    try:
        budget = max(512, min(262_144, int(qs.get("budget") or 16_384)))
    except (TypeError, ValueError):
        budget = 16_384
    if mode != "fleet" and project_root:
        edir = resolve_contained_effort_dir(project_root, str(qs.get("dir") or ""))
        if edir is not None:
            mdoc = build_cockpit_poincare_map(edir, persist=True)
            return render_poincare_viewer_html(mdoc, cockpit_options=list_cockpit_viewer_options(), initial_budget=budget)
    mdoc = build_fleet_poincare_atlas(persist=True)
    return render_poincare_viewer_html(mdoc, cockpit_options=list_cockpit_viewer_options(), initial_budget=budget)


def list_cockpit_viewer_options() -> list[dict[str, str]]:
    """List active AI Cockpits for the `/poincare-map` scope selector dropdown."""
    import rnd_registry as _rnd
    opts: list[dict[str, str]] = []
    for proj in _rnd.list_projects(include_archived=False, include_future=False, include_retired=False):
        fp = Path(str(proj.get("folder_path") or ""))
        if not fp.is_dir():
            continue
        pid = str(proj.get("id") or "")
        pnm = str(proj.get("name") or fp.name)
        if (fp / "ECGBERHT.md").is_file():
            opts.append({"label": pnm, "href": f"/steward-static/poincare.html?pid={pid}", "effort_dir": str(fp)})
        try:
            for ch in sorted(fp.iterdir()):
                if ch.is_dir() and not ch.name.startswith(".") and (ch / "ECGBERHT.md").is_file():
                    opts.append({
                        "label": f"{pnm} :: {ch.name}",
                        "href": f"/steward-static/poincare.html?pid={pid}&dir={ch.name.replace(' ', '+')}",
                        "effort_dir": str(ch),
                    })
        except OSError:
            pass
    return opts


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Anchor Dual-Poincaré Deep-Memory State Map CLI")
    parser.add_argument("--cockpit", help="Path to an AI Cockpit effort directory")
    parser.add_argument("--fleet", action="store_true", help="Build fleet-wide Star Chart + Cave + Cockpit Atlas")
    parser.add_argument("--gandalf", help="Path to a graded Gandalf read.json file")
    parser.add_argument("--query", default="", help="Focus query for MERA-Poincaré context window assembly")
    parser.add_argument("--zoom", default="", help="Focus/zoom onto a specific node_id and print its verbatim subtree")
    parser.add_argument("--budget", type=int, default=16_384, help="Token budget for parsed context window")
    parser.add_argument("--html-out", help="Optional path to write standalone interactive HTML viewer")
    parser.add_argument("--capsule-only", action="store_true", help="Print formatted context capsule text only")
    args = parser.parse_args(argv)

    if args.gandalf:
        gdoc = json.loads(Path(args.gandalf).read_text(encoding="utf-8"))
        mdoc = build_gandalf_poincare_map(gdoc)
    elif args.cockpit:
        mdoc = build_cockpit_poincare_map(args.cockpit, persist=True, force=True)
    else:
        mdoc = build_fleet_poincare_atlas(persist=True)

    if args.html_out:
        out_h = Path(args.html_out)
        out_h.parent.mkdir(parents=True, exist_ok=True)
        out_h.write_text(render_poincare_viewer_html(mdoc, initial_budget=args.budget), encoding="utf-8")

    pack = parse_deep_memory_window(mdoc, focus_id=(args.zoom or None), query=args.query, budget_tokens=args.budget)
    if args.capsule_only:
        sys.stdout.write(pack["formatted_capsule"] + "\n")
    else:
        sys.stdout.write(json.dumps({"map_summary": {k: mdoc.get(k) for k in ("title", "scope", "node_count", "active_node_count", "boneyard_node_count", "corpus_raw_tokens", "build_ms")}, "window": pack}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
