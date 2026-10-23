"""Librarian Knowledge Base & Generalized Product-Manifold Engine (Wave 21).

Implements the unified storage, hybrid retrieval, context-window routing, execution
telemetry (Piaget assimilation), and Poincare ecosystem projection engine for Skill
Foundry and Anchor.

Architecture (grounded in the Wave 21 3-Stage Study: researchPrime -> Gandalf -> Ramanujan):
  * Storage Engine: SQLite 3 in WAL mode (synchronous=NORMAL, busy_timeout=5000)
    with FTS5 virtual table (`kb_fts`) for BM25 lexical search over unstructured
    Markdown instructions, journals, and code AST symbols.
  * Generalized Product Manifold M = L^{d_H}_kappa x S^{d_S}_{tilde_kappa} x E^{d_E}:
      - Hyperbolic factor L^{d_H}_kappa (Lorentz Hyperboloid in R^{d_H+1} with
        <x, x>_L = -1/kappa, x_0 > 0) for numerically stable tree/hierarchy storage
        (avoiding the IEEE-754 float64 boundary collapse of the Poincare ball at
        rho = 55 * ln(2) ~= 38.123 rad), paired with stereographic projection to
        the 2D Poincare disk B^2_kappa for interactive fisheye display and Mobius
        gyrovector recentering.
      - Spherical factor S^{d_S} for cyclic workflows (EXECUTE -> REVIEW -> FIX ->
        RE-REVIEW) and process phase angles with zero cycle distortion.
      - Euclidean factor E^{d_E} for deterministic normalized lexical/feature facets.
  * Ecosystem Graph (`kb_nodes` + `kb_edges`): explicitly indexes Skills, Tools,
    Peer Skills (`compose | import | augment`), Knowledge Sources (`SKILL.md`,
    `HUMAN.md`, `NORTH-STAR.md`, `journal/*.md`), Repositories (`Anchor`, `trio`,
    `Skill Foundry`), Process Steps, and Code AST Symbols with SHA-256 provenance.
  * Submodular Tree-Knapsack Context Router (`query_hybrid`): combines BM25 +
    Product-Manifold geodesic proximity + outcome credit and selects tiered context
    cards (Ring 0..3) via greedy marginal-gain-per-token maximization within
    `token_budget`.

Stdlib-only Python (sqlite3, math, hashlib, json, ast, pathlib, time, re, os).
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple, Union


# ── Constants & Canonical Paths ──────────────────────────────────────────────

CODE_ROOT = Path(__file__).resolve().parent
DEFAULT_FOUNDRY_ROOT = Path(os.environ.get("FOUNDRY_ROOT") or r"C:\dev\Skill Foundry")
DEFAULT_SKILLS_ROOT = Path(os.environ.get("ANCHOR_SKILLS_ROOT") or (DEFAULT_FOUNDRY_ROOT / "skills"))
DEFAULT_TRIO_ROOT = Path(os.environ.get("FOUNDRY_TRIO_ROOT") or r"C:\dev\trio")
DEFAULT_STEWARD_ROOT = Path(
    os.environ.get("FOUNDRY_STEWARD_ROOT") or (Path.home() / ".agents" / "skills" / "ecgberht")
)
DEFAULT_CONTENT_ROOT = Path(
    os.environ.get("FOUNDRY_PAGE_CONTENT_ROOT")
    or (DEFAULT_FOUNDRY_ROOT / "Foundry page and knowledge maps")
)
DEFAULT_DB_PATH = CODE_ROOT / ".anchor_librarian_kb.sqlite3"

NODE_KINDS = (
    "skill",
    "tool",
    "peer_skill",
    "knowledge_source",
    "repository",
    "process_step",
    "code_symbol",
)

EDGE_TYPES = (
    "hierarchy",
    "invokes_tool",
    "composes_skill",
    "reads_source",
    "lives_in_repo",
    "process_flow",
)

EUCLIDEAN_DIM = 8

# Orthogonal 3D Poincare Sphere / Hyperboloid spatial axes:
#   Axis 0 (X): Substantive Domain Hierarchy (`domain_hierarchy`)
#   Axis 1 (Y): Procedural Task Execution Phase (`task_phase_axis`: INGEST -> COMPUTE -> VERIFY -> EMIT)
#   Axis 2 (Z): Resource Modality (`modality_axis`: Spec/Source vs. Tool/AST vs. Peer Skill vs. Repo)
ORTHOGONAL_AXIS_NAMES: Tuple[str, str, str] = (
    "domain_hierarchy",
    "task_phase_axis",
    "modality_axis",
)

# Task-Phase Selective Attention Weights:
# Maps active task phase tau -> (w_domain, w_phase, w_modality, w_spherical, w_euclidean)
TASK_PHASE_WEIGHTS: Dict[str, Tuple[float, float, float, float, float]] = {
    "ingest": (1.4, 1.6, 1.3, 0.4, 0.6),
    "compute": (1.0, 1.8, 1.8, 0.5, 0.7),
    "verify": (1.1, 1.9, 1.5, 0.8, 0.6),
    "emit": (1.0, 1.6, 1.4, 0.5, 0.6),
    "collaborate": (0.9, 1.4, 1.9, 0.9, 0.5),
    "balanced": (1.0, 1.0, 1.0, 0.5, 0.5),
}


# Canonical cross-skill composition & augmentation relationships across the 19 skills
CANONICAL_PEER_EDGES: Dict[str, List[Tuple[str, str, str]]] = {
    "anvil": [("gandalf", "compose", "Cross-family adversarial review for code remapping and paper-to-code validation")],
    "aegis": [
        ("gandalf", "compose", "Cross-family adversarial verification of synthesized security patches"),
        ("anvil", "augment", "Uses AST comprehension and LibCST/parso structural analysis"),
    ],
    "crucible": [("foreman", "import", "Imports Foreman durability/git/driver modules and spawns locate-plan.mjs")],
    "einstein": [("steward-lamp", "compose", "Composes with Steward for multi-session learning campaign continuity")],
    "jumper": [("gandalf", "compose", "Composes Gandalf deep-think read as Stage-1 substrate for ideation")],
    "superjump": [
        ("gandalf", "compose", "Deep bounded problem read before analogical transfer"),
        ("jumper", "augment", "Extends Jumper with inspectable transfer traces and cross-family Fit Contract judge"),
    ],
    "literaturereview": [("researchprime", "augment", "Final adversarial verification pass through researchPrime governed round")],
    "researchprime": [
        ("crucible", "import", "Phase-3 engine imports Crucible convergence machinery"),
        ("foreman", "import", "Phase-3 engine imports Foreman driver and durability machinery"),
    ],
    "tidyidy": [("gandalf", "compose", "Uses Gandalf deep-think for folder hygiene and pruning triage")],
    "steward-project": [
        ("researchprime", "compose", "Dispatches deep research for project questions"),
        ("crucible", "compose", "Dispatches planning sessions for project efforts"),
        ("foreman", "compose", "Dispatches multi-wave execution builds"),
    ],
    "steward-portfolio": [
        ("steward-project", "compose", "Coordinates project-level Steward seats across portfolio"),
        ("gandalf", "compose", "Requests portfolio-wide deep-think reviews"),
    ],
    "steward-starchart": [
        ("steward-portfolio", "compose", "Hands approved strategic initiatives to the Portfolio Steward"),
        ("researchprime", "compose", "Grounds foresight exploration in verified research"),
    ],
}


# ── Generalized Manifold Geometry (Lorentz H^d, Poincare B^d, S^d, E^d) ──────

def lorentz_inner(u: Sequence[float], v: Sequence[float]) -> float:
    """Minkowski / Lorentz inner product <u, v>_L = -u_0 * v_0 + sum_{i=1}^d u_i * v_i."""
    if len(u) != len(v) or len(u) < 2:
        raise ValueError("lorentz_inner requires equal-length vectors of dimension >= 2")
    spatial_dot = 0.0
    for idx in range(1, len(u)):
        spatial_dot += float(u[idx]) * float(v[idx])
    return -float(u[0]) * float(v[0]) + spatial_dot


def lorentz_distance(u: Sequence[float], v: Sequence[float], kappa: float = 1.0) -> float:
    """Numerically stable geodesic distance on the Lorentz Hyperboloid L^d_kappa.

    Combines the inverse-cosh Lorentz inner product formula:
        d_L(u, v) = (1 / sqrt(kappa)) * acosh(max(1.0, -kappa * <u, v>_L))
    with the chordal half-angle identity near zero separation to eliminate precision loss
    when u and v are nearly coincident.
    """
    if kappa <= 0.0:
        raise ValueError("Curvature kappa must be strictly positive")
    root_k = math.sqrt(kappa)
    prod = -kappa * lorentz_inner(u, v)
    # Near u == v, prod = 1 + O(d^2); use Lorentzian chordal norm ||u - v||_L^2
    if prod <= 1.0 + 1e-7:
        du0 = float(u[0]) - float(v[0])
        spatial_diff_sq = sum((float(u[i]) - float(v[i])) ** 2 for i in range(1, len(u)))
        lorentz_chord_sq = max(0.0, spatial_diff_sq - du0 * du0)
        if lorentz_chord_sq == 0.0:
            return 0.0
        return (2.0 / root_k) * math.asinh(0.5 * root_k * math.sqrt(lorentz_chord_sq))
    return math.acosh(prod) / root_k


def lorentz_to_poincare(x: Sequence[float], kappa: float = 1.0) -> List[float]:
    """Isometric stereographic projection Pi_{L -> B}(x) = x_{1:d} / (1 + sqrt(kappa) * x_0).

    Projects a point x = (x_0, x_1, ..., x_d) on the Lorentz hyperboloid L^d_kappa
    into the Poincare ball B^d_kappa of radius 1 / sqrt(kappa). Clamps norm strictly
    inside the boundary (1 - 1e-7) / sqrt(kappa) for safe SVG rendering.
    """
    if len(x) < 2:
        raise ValueError("Lorentz vector must have at least 2 components (x_0, x_1, ...)")
    if kappa <= 0.0:
        raise ValueError("Curvature kappa must be strictly positive")
    root_k = math.sqrt(kappa)
    denom = 1.0 + root_k * float(x[0])
    if denom <= 0.0:
        denom = 1e-12
    proj = [float(c) / denom for c in x[1:]]
    max_norm = (1.0 - 1e-7) / root_k
    norm = math.sqrt(sum(c * c for c in proj))
    if norm > max_norm and norm > 0.0:
        scale = max_norm / norm
        proj = [c * scale for c in proj]
    return proj


def poincare_to_lorentz(z: Sequence[float], kappa: float = 1.0) -> List[float]:
    """Inverse stereographic projection Pi_{B -> L}(z) from Poincare ball B^d_kappa to L^d_kappa.

    Pi_{B -> L}(z) = ( (1 + kappa ||z||^2) / (sqrt(kappa) * (1 - kappa ||z||^2)),
                       2 * z / (1 - kappa ||z||^2) )
    """
    if len(z) < 1:
        raise ValueError("Poincare vector must have at least 1 component")
    if kappa <= 0.0:
        raise ValueError("Curvature kappa must be strictly positive")
    root_k = math.sqrt(kappa)
    norm_sq = sum(float(c) * float(c) for c in z)
    k_norm_sq = kappa * norm_sq
    if k_norm_sq >= 1.0:
        # Clamp inside the open ball to prevent ZeroDivisionError
        scale = math.sqrt((1.0 - 1e-12) / k_norm_sq)
        z = [float(c) * scale for c in z]
        norm_sq = sum(c * c for c in z)
        k_norm_sq = kappa * norm_sq
    denom = max(1e-15, 1.0 - k_norm_sq)
    spatial = [2.0 * float(c) / denom for c in z]
    # Enforce exact hyperboloid constraint x_0 = sqrt(1/kappa + ||spatial||^2)
    x0 = math.sqrt((1.0 / kappa) + sum(s * s for s in spatial))
    return [x0] + spatial


def lorentz_project_subspace(
    x: Sequence[float],
    axis_indices: Sequence[int],
    kappa: float = 1.0,
    mode: str = "sheet",
) -> List[float]:
    """Project a d-dimensional Lorentz point x = (x_0, x_1, ..., x_d) in L^d_kappa
    onto a k-dimensional orthogonal subspace spanned by `axis_indices` (0-based spatial
    coordinates), returning a valid point in L^k_kappa that satisfies
    -<pi_V(x), pi_V(x)>_L = 1/kappa to machine precision.

    Modes:
      * ``"sheet"`` (default): Hyperboloid Sheet-Lift Projection
            pi_V^{sheet}(x) = ( sqrt(1/kappa + ||x_V||_2^2), x_V )
        Decouples orthogonal depths so large off-subspace coordinates ||x_perp||
        do not shrink the projected Poincare slice coordinates toward the origin.
      * ``"geodesic"``: Exact Riemannian Closest-Point Geodesic Projection onto the
        totally geodesic submanifold L^k_kappa(V):
            pi_V^{geo}(x) = (x_0, x_V) / sqrt(1 + kappa * ||x_perp||_2^2)
    """
    if len(x) < 2:
        raise ValueError("Lorentz vector must have at least 2 components (x_0, x_1, ...)")
    if not axis_indices:
        raise ValueError("axis_indices must contain at least one spatial axis index")
    if kappa <= 0.0:
        raise ValueError("Curvature kappa must be strictly positive")

    spatial_dim = len(x) - 1
    chosen: List[int] = []
    for idx in axis_indices:
        i = int(idx)
        if i < 0 or i >= spatial_dim:
            raise IndexError(f"Spatial axis index {i} out of range for d={spatial_dim}")
        chosen.append(i)

    spatial_v = [float(x[1 + i]) for i in chosen]
    if mode == "geodesic":
        chosen_set = set(chosen)
        perp_sq = sum(
            float(x[1 + j]) ** 2 for j in range(spatial_dim) if j not in chosen_set
        )
        scale = math.sqrt(1.0 + kappa * perp_sq)
        spatial_v = [s / scale for s in spatial_v]

    x0 = math.sqrt((1.0 / kappa) + sum(s * s for s in spatial_v))
    return [x0] + spatial_v


def lorentz_boost_recenter(
    x: Sequence[float],
    focus: Sequence[float],
    kappa: float = 1.0,
) -> List[float]:
    """Isometric Lorentz boost (Minkowski Householder reflection) in L^d_kappa
    that maps `focus` to the origin o = (1/sqrt(kappa), 0, ..., 0) while preserving
    all pairwise hyperbolic geodesic distances in arbitrary dimension d >= 2."""
    if len(x) != len(focus) or len(x) < 2:
        raise ValueError("lorentz_boost_recenter requires equal-length Lorentz vectors (len >= 2)")
    if kappa <= 0.0:
        raise ValueError("Curvature kappa must be strictly positive")
    root_k = math.sqrt(kappa)
    origin = [1.0 / root_k] + [0.0] * (len(x) - 1)
    # Reflection vector v = focus - origin in R^{1,d} (spacelike when focus != origin)
    v = [float(focus[0]) - origin[0]] + [float(focus[i]) for i in range(1, len(x))]
    v_norm_sq = lorentz_inner(v, v)
    if abs(v_norm_sq) < 1e-15:
        return [float(c) for c in x]
    xv = lorentz_inner(x, v)
    boosted = [float(x[i]) - (2.0 * xv / v_norm_sq) * v[i] for i in range(len(x))]
    # Re-pin x_0 to exact hyperboloid sheet
    spatial = boosted[1:]
    x0 = math.sqrt((1.0 / kappa) + sum(s * s for s in spatial))
    return [x0] + spatial



def mobius_recenter(
    z: Union[Sequence[float], Dict[str, float]],
    focus: Union[Sequence[float], Dict[str, float]],
) -> List[float]:
    """Isometric Mobius disk automorphism T_a(z) = (z - a) / (1 - conj(a) * z) on B^2_1.

    Accepts 2D sequences `[x, y]` or dicts `{'x': x, 'y': y}` / `{'poincare_x': x, 'poincare_y': y}`
    and returns `[rx, ry]` strictly inside the unit disk.
    """
    def _xy(pt: Union[Sequence[float], Dict[str, float]]) -> Tuple[float, float]:
        if isinstance(pt, dict):
            px = pt.get("x", pt.get("poincare_x", 0.0))
            py = pt.get("y", pt.get("poincare_y", 0.0))
            return float(px), float(py)
        return float(pt[0]), float(pt[1])

    zx, zy = _xy(z)
    ax, ay = _xy(focus)
    if abs(zx - ax) < 1e-15 and abs(zy - ay) < 1e-15:
        return [0.0, 0.0]
    nx = zx - ax
    ny = zy - ay
    dx = 1.0 - (ax * zx + ay * zy)
    dy = ay * zx - ax * zy
    denom = max(1e-15, dx * dx + dy * dy)
    rx = (nx * dx + ny * dy) / denom
    ry = (ny * dx - nx * dy) / denom
    r_norm = math.hypot(rx, ry)
    if r_norm >= 1.0 - 1e-7:
        scale = (1.0 - 1e-7) / r_norm
        rx *= scale
        ry *= scale
    return [rx, ry]


def spherical_distance(u: Sequence[float], v: Sequence[float], tilde_kappa: float = 1.0) -> float:
    """Geodesic arc distance on the sphere S^d_{tilde_kappa}."""
    if len(u) != len(v) or not u:
        raise ValueError("spherical_distance requires equal non-empty vectors")
    u_norm = math.sqrt(sum(float(a) * float(a) for a in u)) or 1.0
    v_norm = math.sqrt(sum(float(b) * float(b) for b in v)) or 1.0
    dot = sum((float(a) / u_norm) * (float(b) / v_norm) for a, b in zip(u, v))
    dot = max(-1.0, min(1.0, dot))
    return math.acos(dot) / math.sqrt(max(1e-12, tilde_kappa))


def euclidean_distance(u: Sequence[float], v: Sequence[float]) -> float:
    """Standard L2 distance on E^d."""
    if len(u) != len(v):
        raise ValueError("euclidean_distance requires equal-length vectors")
    return math.sqrt(sum((float(a) - float(b)) ** 2 for a, b in zip(u, v)))


def _extract_manifold_triple(
    node: Union[Dict[str, Any], Tuple[Sequence[float], Sequence[float], Sequence[float]]]
) -> Tuple[List[float], List[float], List[float]]:
    if isinstance(node, dict):
        lor = node.get("lorentz_vec")
        if isinstance(lor, str):
            lor = json.loads(lor)
        sph = node.get("spherical_vec")
        if isinstance(sph, str):
            sph = json.loads(sph)
        euc = node.get("euclidean_vec")
        if isinstance(euc, str):
            euc = json.loads(euc)
        if not lor:
            px = float(node.get("poincare_x", 0.0))
            py = float(node.get("poincare_y", 0.0))
            lor = poincare_to_lorentz([px, py])
        if not sph:
            sph = [1.0, 0.0]
        if not euc:
            euc = [0.0] * EUCLIDEAN_DIM
        return [float(x) for x in lor], [float(x) for x in sph], [float(x) for x in euc]
    if isinstance(node, (tuple, list)) and len(node) == 3:
        return [float(x) for x in node[0]], [float(x) for x in node[1]], [float(x) for x in node[2]]
    raise TypeError("Expected node dict or (lorentz_vec, spherical_vec, euclidean_vec) tuple")


def product_manifold_distance(
    node_a: Union[Dict[str, Any], Tuple[Sequence[float], Sequence[float], Sequence[float]]],
    node_b: Union[Dict[str, Any], Tuple[Sequence[float], Sequence[float], Sequence[float]]],
    weights: Tuple[float, float, float] = (1.0, 0.5, 0.5),
    kappa: float = 1.0,
    tilde_kappa: float = 1.0,
) -> float:
    """Geodesic distance on the Mixed-Curvature Product Manifold M = L^{d_H}_kappa x S^{d_S}_{tilde_kappa} x E^{d_E}:

        d_M(a, b) = sqrt( w_H * d_L(x_a, x_b)^2 + w_S * d_S(s_a, s_b)^2 + w_E * ||e_a - e_b||_2^2 )

    Satisfies all metric axioms (non-negativity, identity of indiscernibles, symmetry,
    and triangle inequality) for all w_H, w_S, w_E > 0.
    """
    w_h, w_s, w_e = float(weights[0]), float(weights[1]), float(weights[2])
    if w_h < 0.0 or w_s < 0.0 or w_e < 0.0 or (w_h + w_s + w_e) <= 0.0:
        raise ValueError("Product manifold weights must be non-negative with positive sum")
    lor_a, sph_a, euc_a = _extract_manifold_triple(node_a)
    lor_b, sph_b, euc_b = _extract_manifold_triple(node_b)
    d_h = lorentz_distance(lor_a, lor_b, kappa=kappa) if w_h > 0.0 else 0.0
    d_s = spherical_distance(sph_a, sph_b, tilde_kappa=tilde_kappa) if w_s > 0.0 else 0.0
    d_e = euclidean_distance(euc_a, euc_b) if w_e > 0.0 else 0.0
    return math.sqrt(w_h * d_h * d_h + w_s * d_s * d_s + w_e * d_e * d_e)


# ── Deterministic Feature & Coordinate Encoders ──────────────────────────────

def compute_euclidean_embedding(
    text: str,
    kind: str = "knowledge_source",
    ring: int = 1,
    dim: int = EUCLIDEAN_DIM,
) -> List[float]:
    """Compute a deterministic L2-normalized feature + lexical-hash vector in E^{dim}.

    Combines structural kind/ring priors in the first 2 coordinates with signed
    character/word token hashing across the remaining coordinates so lexically
    and structurally similar chunks lie close in E^{dim}.
    """
    vec = [0.0] * dim
    kind_idx = NODE_KINDS.index(kind) if kind in NODE_KINDS else 0
    vec[0] = (kind_idx + 1.0) / float(len(NODE_KINDS))
    vec[1] = 1.0 / (1.0 + float(max(0, ring)))

    tokens = re.findall(r"[a-z0-9_]{2,}", (text or "").lower())
    if not tokens:
        tokens = [(text or "empty").lower()]
    for tok in tokens:
        digest = hashlib.sha256(tok.encode("utf-8")).digest()
        bucket = 2 + (digest[0] % max(1, dim - 2))
        sign = 1.0 if (digest[1] & 1) == 0 else -1.0
        weight = 1.0 + (digest[2] / 255.0) * 0.5
        vec[bucket] += sign * weight

    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [round(v / norm, 8) for v in vec]


def compute_spherical_phase(
    kind: str,
    step_index: int = 0,
    total_steps: int = 1,
    node_id: str = "",
) -> List[float]:
    """Map cyclic workflow steps and node kinds onto the unit circle S^1 subset R^2."""
    if kind == "process_step" and total_steps > 0:
        angle = (2.0 * math.pi * float(step_index % max(1, total_steps))) / float(max(1, total_steps))
    else:
        kind_idx = NODE_KINDS.index(kind) if kind in NODE_KINDS else 0
        h_offset = (int(hashlib.sha256(node_id.encode("utf-8")).hexdigest()[:4], 16) / 65535.0) * 0.35
        angle = (2.0 * math.pi * (kind_idx + h_offset)) / float(len(NODE_KINDS))
    return [round(math.cos(angle), 8), round(math.sin(angle), 8)]


def _polar_to_lorentz(rho: float, theta: float, kappa: float = 1.0) -> List[float]:
    """Convert hyperbolic polar coordinates (geodesic radius rho, angle theta) to L^2_kappa."""
    root_k = math.sqrt(kappa)
    sr = math.sinh(root_k * rho) / root_k
    cr = math.cosh(root_k * rho) / root_k
    x1 = sr * math.cos(theta)
    x2 = sr * math.sin(theta)
    # Enforce exact hyperboloid sheet constraint
    x0 = math.sqrt((1.0 / kappa) + x1 * x1 + x2 * x2)
    return [round(x0, 10), round(x1, 10), round(x2, 10)]


def calibrate_tree_lorentz_coordinates(
    nodes: List[Dict[str, Any]],
    root_id: Optional[str] = None,
    kappa: float = 1.0,
) -> Dict[str, Tuple[List[float], float, float]]:
    """Assign degree-calibrated Lorentz coordinates x in L^2_kappa and projected
    2D Poincare coordinates (poincare_x, poincare_y) to a hierarchy of nodes.

    Uses Ramanujan's degree-calibrated radial schedule so high-branching rings
    expand outward onto exponentially larger hyperbolic circumferences without
    sibling crowding or float64 boundary collapse.
    """
    by_id = {str(n["node_id"]): n for n in nodes}
    children: Dict[Optional[str], List[str]] = {}
    for n in nodes:
        nid = str(n["node_id"])
        pid = n.get("parent_id")
        pid_key = str(pid) if pid and str(pid) in by_id and str(pid) != nid else None
        children.setdefault(pid_key, []).append(nid)

    for pid_key in children:
        children[pid_key].sort()

    coords: Dict[str, Tuple[List[float], float, float]] = {}

    def _place(nid: str, lo: float, hi: float, depth: int, parent_rho: float, sibling_count: int) -> None:
        theta = 0.5 * (lo + hi)
        if depth == 0:
            rho = 0.0
        else:
            # Degree-calibrated hyperbolic radial increment bounded for visual clarity in Poincare disk
            deg_step = 0.55 + 0.28 * math.log1p(max(1, sibling_count))
            rho = parent_rho + deg_step
        lor = _polar_to_lorentz(rho, theta, kappa=kappa)
        poin = lorentz_to_poincare(lor, kappa=kappa)
        coords[nid] = (lor, round(poin[0], 8), round(poin[1], 8))

        kids = children.get(nid, [])
        k_len = len(kids)
        for idx, kid_id in enumerate(kids):
            k_lo = lo + (hi - lo) * (idx / float(k_len))
            k_hi = lo + (hi - lo) * ((idx + 1) / float(k_len))
            _place(kid_id, k_lo, k_hi, depth + 1, rho, k_len)

    roots = children.get(None, [])
    if root_id and root_id in by_id:
        roots = [root_id] + [r for r in roots if r != root_id]

    if len(roots) == 1:
        _place(roots[0], -math.pi / 2.0, 1.5 * math.pi, 0, 0.0, 1)
    else:
        r_len = max(1, len(roots))
        for idx, rid in enumerate(roots):
            r_lo = -math.pi / 2.0 + (2.0 * math.pi) * (idx / float(r_len))
            r_hi = -math.pi / 2.0 + (2.0 * math.pi) * ((idx + 1) / float(r_len))
            _place(rid, r_lo, r_hi, 1, 0.65, r_len)

    # Ensure any disconnected cycle/DAG nodes also receive valid coordinates
    for n in nodes:
        nid = str(n["node_id"])
        if nid not in coords:
            ring = int(n.get("ring") or 1)
            h_angle = (int(hashlib.sha256(nid.encode("utf-8")).hexdigest()[:6], 16) / float(0xFFFFFF)) * 2.0 * math.pi
            rho = 0.85 * max(1, ring)
            lor = _polar_to_lorentz(rho, h_angle, kappa=kappa)
            poin = lorentz_to_poincare(lor, kappa=kappa)
            coords[nid] = (lor, round(poin[0], 8), round(poin[1], 8))

    return coords


def infer_node_task_phase(node: Dict[str, Any]) -> str:
    """Classify a KB node's primary procedural task phase (`ingest`, `compute`,
    `verify`, `emit`, or `collaborate`) from its kind, title, summary, and node_id."""
    kind = str(node.get("kind") or "knowledge_source").lower()
    text = f"{node.get('node_id', '')} {node.get('title', '')} {node.get('summary', '')}".lower()

    if kind == "peer_skill":
        return "collaborate"
    if any(k in text for k in ("verify", "review", "shark", "audit", "null space", "null_space", "refut", "gate", "test", "certif")):
        return "verify"
    if any(k in text for k in ("journal", "deliverable", "emit", "report", "output", "receipt", "summary", "export")):
        return "emit"
    if kind in ("tool", "code_symbol") or any(k in text for k in ("execute", "compute", "run", "ast", "engine", "parse", "script")):
        return "compute"
    if any(k in text for k in ("ingest", "intake", "north star", "north-star", "scope", "frame", "skill.md", "human.md", "onboarding")):
        return "ingest"
    if kind == "process_step":
        return "verify" if "review" in text else "compute"
    return "ingest"


def embed_node_3d_poincare(node: Dict[str, Any], kappa: float = 1.0) -> Dict[str, Any]:
    """Embed a KB node into the 3D Lorentz Hyperboloid L^3_kappa and 3D Poincare
    Sphere B^3_kappa with 3 mutually orthogonal spatial axes:
      * Axis X (`domain_hierarchy`, index 0): Substantive domain/skill hierarchy coordinate
      * Axis Y (`task_phase_axis`, index 1): Procedural stage (`ingest` -> `compute` -> `verify` -> `emit`)
      * Axis Z (`modality_axis`, index 2): Resource modality (`knowledge_source` vs. `tool`/`code_symbol` vs. `peer_skill`)

    Guarantees:
      1. Exact hyperboloid sheet constraint -x_0^2 + x_1^2 + x_2^2 + x_3^2 = -1/kappa.
      2. Strictly bounded 3D Poincare sphere coordinates ||poincare_3d||_2 < 1/sqrt(kappa).
      3. Preserves root origin placement (ring == 0 at origin -> [0.0, 0.0, 0.0]).
    """
    if kappa <= 0.0:
        raise ValueError("Curvature kappa must be strictly positive")
    root_k = math.sqrt(kappa)
    lor_2d = node.get("lorentz_vec")
    if isinstance(lor_2d, str):
        lor_2d = json.loads(lor_2d)
    if not lor_2d or len(lor_2d) < 3:
        px = float(node.get("poincare_x", 0.0))
        py = float(node.get("poincare_y", 0.0))
        lor_2d = poincare_to_lorentz([px, py], kappa=kappa)

    ring = int(node.get("ring") or 0)
    nid = str(node.get("node_id") or "")
    kind = str(node.get("kind") or "knowledge_source")
    phase = infer_node_task_phase(node)

    # If the node is a single-skill root sitting at the exact origin, keep it at the 3D origin
    spatial_2d_norm_sq = float(lor_2d[1]) ** 2 + float(lor_2d[2]) ** 2
    if ring == 0 and spatial_2d_norm_sq < 1e-12:
        lorentz_3d = [round(1.0 / root_k, 10), 0.0, 0.0, 0.0]
        poincare_3d = [0.0, 0.0, 0.0]
    else:
        # Total hyperbolic spatial radius sinh(sqrt(kappa)*rho)/sqrt(kappa) from the calibrated tree
        base_sr = math.sqrt(max(0.05, spatial_2d_norm_sq))
        digest = hashlib.sha256(nid.encode("utf-8")).digest()
        jitter = ((digest[0] / 255.0) - 0.5) * 0.14

        # Axis 0 (X): Substantive domain coordinate (preserves tree branch sign & magnitude)
        dom_dir = float(lor_2d[1]) / base_sr if base_sr > 1e-9 else math.cos(digest[1] / 40.0)

        # Axis 1 (Y): Task execution phase polarity (-1.0 ingest -> -0.25 compute -> +0.45 verify -> +0.95 emit)
        phase_polarity_map = {
            "ingest": -0.90,
            "compute": -0.25,
            "collaborate": 0.20,
            "verify": 0.55,
            "emit": 0.95,
        }
        phase_dir = phase_polarity_map.get(phase, 0.0) + jitter

        # Axis 2 (Z): Resource modality polarity (Northern hemisphere: Specs/Sources/Repos;
        # Southern hemisphere: Executable Tools & AST Code Symbols; Equator: Peer Skills)
        modality_polarity_map = {
            "knowledge_source": 0.88,
            "repository": 0.55,
            "peer_skill": 0.28,
            "skill": 0.0,
            "process_step": -0.35,
            "tool": -0.78,
            "code_symbol": -0.96,
        }
        mod_dir = modality_polarity_map.get(kind, 0.0) - 0.5 * jitter

        # Normalize (dom_dir, phase_dir, mod_dir) on S^2 and scale by base_sr
        dir_norm = math.sqrt(dom_dir * dom_dir + phase_dir * phase_dir + mod_dir * mod_dir) or 1.0
        x1 = base_sr * (dom_dir / dir_norm)
        x2 = base_sr * (phase_dir / dir_norm)
        x3 = base_sr * (mod_dir / dir_norm)
        x0 = math.sqrt((1.0 / kappa) + x1 * x1 + x2 * x2 + x3 * x3)
        lorentz_3d = [round(x0, 10), round(x1, 10), round(x2, 10), round(x3, 10)]
        p3 = lorentz_to_poincare(lorentz_3d, kappa=kappa)
        poincare_3d = [round(p3[0], 8), round(p3[1], 8), round(p3[2], 8)]

    return {
        "lorentz_3d": lorentz_3d,
        "poincare_3d": poincare_3d,
        "task_phase": phase,
        "orthogonal_axes": {
            "domain_hierarchy": poincare_3d[0],
            "task_phase_axis": poincare_3d[1],
            "modality_axis": poincare_3d[2],
        },
    }



# ── Structure-Aware Unstructured Data Chunkers (AST + Markdown) ──────────────

def _estimate_tokens(text: str) -> int:
    return max(25, min(2000, int(len(text or "") / 3.8) + 20))


def extract_python_ast_symbols(source_path: Path, max_symbols: int = 8) -> List[Dict[str, Any]]:
    """Parse a Python file with `ast.parse` and return top-level classes/functions with
    exact 1-based line ranges and SHA-256 content hashes."""
    try:
        raw_bytes = source_path.read_bytes()
        text = raw_bytes.decode("utf-8-sig", errors="replace")
        tree = ast.parse(text, filename=str(source_path))
    except (OSError, SyntaxError, ValueError):
        return []

    lines = text.splitlines()
    out: List[Dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            start = int(getattr(node, "lineno", 1))
            end = int(getattr(node, "end_lineno", start))
            start = max(1, min(start, max(1, len(lines))))
            end = max(start, min(end, max(1, len(lines))))
            excerpt = "\n".join(lines[start - 1 : end])
            digest = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
            doc = ast.get_docstring(node) or ""
            first_doc = doc.strip().splitlines()[0] if doc.strip() else ""
            kind_prefix = "class" if isinstance(node, ast.ClassDef) else "def"
            summary = first_doc or f"{kind_prefix} {node.name} (L{start}-L{end} in {source_path.name})"
            out.append({
                "name": node.name,
                "qualname": f"{source_path.stem}.{node.name}",
                "summary": summary[:280],
                "start_line": start,
                "end_line": end,
                "sha256": digest,
                "token_estimate": _estimate_tokens(excerpt),
            })
            if len(out) >= max_symbols:
                break
    return out


def extract_markdown_sections(source_path: Path, max_sections: int = 6) -> List[Dict[str, Any]]:
    """Split a Markdown file along ATX headings (`#` / `##`) with exact line spans and SHA-256 hashes."""
    try:
        text = source_path.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return []
    lines = text.splitlines()
    if not lines:
        return []

    headings: List[Tuple[int, str]] = []
    for idx, line in enumerate(lines, 1):
        m = re.match(r"^(#{1,2})\s+(.+?)\s*$", line)
        if m:
            headings.append((idx, m.group(2).strip()))

    if not headings:
        excerpt = "\n".join(lines[: min(80, len(lines))])
        return [{
            "title": source_path.name,
            "summary": " ".join(line.strip() for line in lines[:8] if line.strip())[:260] or source_path.name,
            "start_line": 1,
            "end_line": len(lines),
            "sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            "token_estimate": _estimate_tokens(excerpt),
        }]

    sections: List[Dict[str, Any]] = []
    for i, (start_line, title) in enumerate(headings[:max_sections]):
        end_line = (headings[i + 1][0] - 1) if (i + 1) < len(headings) else len(lines)
        end_line = max(start_line, end_line)
        span_lines = lines[start_line - 1 : end_line]
        excerpt = "\n".join(span_lines)
        body_preview = " ".join(
            l.strip() for l in span_lines[1:10] if l.strip() and not l.strip().startswith("#")
        )
        sections.append({
            "title": title[:120],
            "summary": (body_preview or title)[:280],
            "start_line": start_line,
            "end_line": end_line,
            "sha256": hashlib.sha256(excerpt.encode("utf-8")).hexdigest(),
            "token_estimate": _estimate_tokens(excerpt),
        })
    return sections


# ── The Librarian Knowledge Base Engine ──────────────────────────────────────

class LibrarianKB:
    """SQLite + WAL + FTS5 + Mixed-Curvature Product Manifold Knowledge Base for
    Skill Foundry and Anchor."""

    def __init__(self, db_path: Union[str, Path, None] = None) -> None:
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._fts5_enabled = True
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        conn.execute("PRAGMA busy_timeout=5000;")
        conn.execute("PRAGMA foreign_keys=ON;")
        return conn

    def _init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS kb_nodes (
                    node_id TEXT PRIMARY KEY,
                    skill_id TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source_path TEXT NOT NULL DEFAULT '',
                    start_line INTEGER NOT NULL DEFAULT 1,
                    end_line INTEGER NOT NULL DEFAULT 1,
                    sha256 TEXT NOT NULL DEFAULT '',
                    parent_id TEXT,
                    ring INTEGER NOT NULL DEFAULT 0,
                    token_estimate INTEGER NOT NULL DEFAULT 150,
                    lorentz_vec TEXT NOT NULL,
                    poincare_x REAL NOT NULL DEFAULT 0.0,
                    poincare_y REAL NOT NULL DEFAULT 0.0,
                    spherical_vec TEXT NOT NULL,
                    euclidean_vec TEXT NOT NULL,
                    usage_count INTEGER NOT NULL DEFAULT 0,
                    success_count INTEGER NOT NULL DEFAULT 0,
                    outcome_credit REAL NOT NULL DEFAULT 0.5
                );

                CREATE INDEX IF NOT EXISTS idx_kb_nodes_skill ON kb_nodes(skill_id);
                CREATE INDEX IF NOT EXISTS idx_kb_nodes_kind ON kb_nodes(kind);
                CREATE INDEX IF NOT EXISTS idx_kb_nodes_parent ON kb_nodes(parent_id);

                CREATE TABLE IF NOT EXISTS kb_edges (
                    source_id TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    edge_type TEXT NOT NULL,
                    weight REAL NOT NULL DEFAULT 1.0,
                    note TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (source_id, target_id, edge_type)
                );

                CREATE INDEX IF NOT EXISTS idx_kb_edges_source ON kb_edges(source_id);
                CREATE INDEX IF NOT EXISTS idx_kb_edges_target ON kb_edges(target_id);

                CREATE TABLE IF NOT EXISTS librarian_access_log (
                    run_id TEXT PRIMARY KEY,
                    timestamp REAL NOT NULL,
                    skill_id TEXT NOT NULL,
                    task_summary TEXT NOT NULL,
                    nodes_accessed_json TEXT NOT NULL,
                    tools_used_json TEXT NOT NULL,
                    peer_skills_json TEXT NOT NULL,
                    sources_used_json TEXT NOT NULL,
                    outcome TEXT NOT NULL,
                    tokens_loaded INTEGER NOT NULL DEFAULT 0,
                    tokens_saved INTEGER NOT NULL DEFAULT 0
                );

                CREATE INDEX IF NOT EXISTS idx_librarian_log_skill ON librarian_access_log(skill_id, timestamp DESC);
                """
            )
            try:
                conn.execute(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS kb_fts USING fts5(
                        node_id UNINDEXED,
                        skill_id,
                        kind,
                        title,
                        summary,
                        tokenize='porter unicode61'
                    );
                    """
                )
            except sqlite3.OperationalError:
                self._fts5_enabled = False

    # ── Ingestion Pipeline ───────────────────────────────────────────────────

    def _discover_skills(self, skill_catalog_or_root: Any = None) -> List[Dict[str, Any]]:
        """Resolve skill definitions from `foundry_page.catalog()`, an explicit list/dict,
        or a filesystem root directory."""
        if isinstance(skill_catalog_or_root, dict) and "skills" in skill_catalog_or_root:
            return list(skill_catalog_or_root["skills"])
        if isinstance(skill_catalog_or_root, list):
            return list(skill_catalog_or_root)
        if isinstance(skill_catalog_or_root, (str, Path)):
            root_path = Path(skill_catalog_or_root).resolve()
            if root_path.is_dir():
                skill_mds = list(root_path.glob("*/SKILL.md")) + list(root_path.glob("skills/*/SKILL.md"))
                if (root_path / "SKILL.md").is_file():
                    skill_mds.insert(0, root_path / "SKILL.md")
                discovered: List[Dict[str, Any]] = []
                seen_dirs = set()
                for smd in skill_mds:
                    sdir = smd.parent.resolve()
                    if str(sdir) in seen_dirs or sdir.name.lower() == "templates":
                        continue
                    seen_dirs.add(str(sdir))
                    sid = re.sub(r"[^a-z0-9-]", "", sdir.name.lower()) or "skill"
                    text = smd.read_text(encoding="utf-8-sig", errors="replace")
                    first_para = next(
                        (l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith(("#", "---"))),
                        f"Skill {sdir.name}",
                    )
                    discovered.append({
                        "id": sid,
                        "name": sdir.name,
                        "purpose": first_para[:240],
                        "source": str(sdir),
                    })
                if discovered:
                    return discovered
                # Treat plain code/doc directory as a synthetic skill for hermetic unit testing
                return [{
                    "id": re.sub(r"[^a-z0-9-]", "", root_path.name.lower()) or "custom-skill",
                    "name": root_path.name,
                    "purpose": f"Workspace knowledge base for {root_path.name}",
                    "source": str(root_path),
                }]

        # Default: use Anchor's canonical `foundry_page.catalog()` (all 19 skills)
        try:
            import foundry_page
            cat = foundry_page.catalog()
            if isinstance(cat, dict) and cat.get("skills"):
                return list(cat["skills"])
        except Exception:
            pass

        # Fallback filesystem scan across canonical roots
        fallback: List[Dict[str, Any]] = []
        for sdir in sorted(DEFAULT_SKILLS_ROOT.glob("*")):
            if (sdir / "SKILL.md").is_file() and sdir.name.lower() != "templates":
                sid = re.sub(r"[^a-z0-9]", "", sdir.name.lower())
                if sid in ("agydispatch", "figuredesigner"):
                    continue
                fallback.append({
                    "id": sid,
                    "name": sdir.name,
                    "purpose": f"Foundry skill {sdir.name}",
                    "source": str(sdir.resolve()),
                })
        for tname in ("crucible", "foreman", "researchPrime"):
            tdir = DEFAULT_TRIO_ROOT / tname
            if (tdir / "SKILL.md").is_file():
                fallback.append({
                    "id": tname.lower(),
                    "name": tname,
                    "purpose": f"Trio skill {tname}",
                    "source": str(tdir.resolve()),
                })
        return fallback

    def _resolve_repo_info(self, source_dir: Path) -> Tuple[str, str, str]:
        """Return `(repo_node_id, repo_title, repo_root_path)` for a skill source directory."""
        s_str = str(source_dir).replace("\\", "/").lower()
        if "/trio/" in s_str or s_str.endswith("/trio"):
            return (
                "repo:trio",
                "Trio Monorepo (researchPrime · Crucible · Foreman)",
                str(DEFAULT_TRIO_ROOT),
            )
        if "ecgberht" in s_str or "steward" in s_str:
            return (
                "repo:anchor-steward",
                "Anchor & Steward Cockpit Repository",
                str(CODE_ROOT),
            )
        if "skill foundry" in s_str:
            return (
                "repo:skill-foundry",
                "Skill Foundry Portfolio Repository",
                str(DEFAULT_FOUNDRY_ROOT),
            )
        return (
            f"repo:{re.sub(r'[^a-z0-9-]', '', source_dir.parent.name.lower()) or 'workspace'}",
            f"Repository {source_dir.parent.name or source_dir.name}",
            str(source_dir.parent if source_dir.parent.exists() else source_dir),
        )

    def ingest_skill_ecosystem(self, skill_catalog_or_root: Any = None) -> Dict[str, Any]:
        """Ingest all skills, their tools, peer skill compositions, unstructured Markdown
        knowledge sources, journals, process steps, Python AST symbols, and repositories
        into SQLite + FTS5 + Generalized Product-Manifold coordinates."""
        t0 = time.perf_counter()
        skills = self._discover_skills(skill_catalog_or_root)
        skill_by_id = {str(s["id"]): s for s in skills}

        all_nodes: Dict[str, Dict[str, Any]] = {}
        all_edges: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

        def _add_node(
            node_id: str,
            skill_id: str,
            kind: str,
            title: str,
            summary: str,
            source_path: str = "",
            start_line: int = 1,
            end_line: int = 1,
            sha256: str = "",
            parent_id: Optional[str] = None,
            ring: int = 1,
            token_estimate: Optional[int] = None,
            step_index: int = 0,
            total_steps: int = 1,
        ) -> None:
            if kind not in NODE_KINDS:
                raise ValueError(f"Unsupported node kind: {kind}")
            toks = token_estimate if token_estimate is not None else (
                150 if ring == 0 else (350 if ring == 1 else (450 if ring == 2 else 750))
            )
            euc = compute_euclidean_embedding(f"{title} {summary}", kind=kind, ring=ring)
            sph = compute_spherical_phase(kind=kind, step_index=step_index, total_steps=total_steps, node_id=node_id)
            all_nodes[node_id] = {
                "node_id": node_id,
                "skill_id": skill_id,
                "kind": kind,
                "title": title,
                "summary": summary,
                "source_path": str(source_path),
                "start_line": int(max(1, start_line)),
                "end_line": int(max(start_line, end_line)),
                "sha256": sha256 or hashlib.sha256(f"{node_id}:{title}:{summary}".encode("utf-8")).hexdigest(),
                "parent_id": parent_id,
                "ring": int(max(0, ring)),
                "token_estimate": int(toks),
                "lorentz_vec": [1.0, 0.0, 0.0],
                "poincare_x": 0.0,
                "poincare_y": 0.0,
                "spherical_vec": sph,
                "euclidean_vec": euc,
            }

        def _add_edge(source_id: str, target_id: str, edge_type: str, weight: float = 1.0, note: str = "") -> None:
            if edge_type not in EDGE_TYPES:
                raise ValueError(f"Unsupported edge_type: {edge_type}")
            if source_id == target_id:
                return
            all_edges[(source_id, target_id, edge_type)] = {
                "source_id": source_id,
                "target_id": target_id,
                "edge_type": edge_type,
                "weight": float(weight),
                "note": note,
            }

        for s in skills:
            sid = str(s["id"])
            sname = str(s.get("name") or sid)
            sdir = Path(str(s.get("source") or (DEFAULT_SKILLS_ROOT / sid)))
            skill_md = sdir / "SKILL.md"
            skill_sha = ""
            skill_lines = 1
            if skill_md.is_file():
                raw_b = skill_md.read_bytes()
                skill_sha = hashlib.sha256(raw_b).hexdigest()
                skill_lines = max(1, len(raw_b.decode("utf-8-sig", errors="replace").splitlines()))

            root_node_id = f"skill:{sid}"
            purpose = str(s.get("purpose") or f"{sname} skill in Skill Foundry")
            _add_node(
                node_id=root_node_id,
                skill_id=sid,
                kind="skill",
                title=sname,
                summary=purpose,
                source_path=str(skill_md if skill_md.is_file() else sdir),
                start_line=1,
                end_line=skill_lines,
                sha256=skill_sha,
                parent_id=None,
                ring=0,
                token_estimate=150,
            )

            # 1. Repository node (`kind='repository'`, `edge_type='lives_in_repo'`)
            repo_id_base, repo_title, repo_path = self._resolve_repo_info(sdir)
            repo_node_id = f"{sid}:{repo_id_base}"
            _add_node(
                node_id=repo_node_id,
                skill_id=sid,
                kind="repository",
                title=repo_title,
                summary=f"Canonical source repository hosting {sname} ({repo_path})",
                source_path=repo_path,
                start_line=1,
                end_line=1,
                parent_id=root_node_id,
                ring=1,
                token_estimate=220,
            )
            _add_edge(root_node_id, repo_node_id, "lives_in_repo", weight=1.0, note=repo_path)
            _add_edge(root_node_id, repo_node_id, "hierarchy", weight=1.0)

            # 2. Peer Skill nodes (`kind='peer_skill'`, `edge_type='composes_skill'`)
            peer_specs = list(CANONICAL_PEER_EDGES.get(sid, []))
            for peer_sid, rel_type, rel_note in peer_specs:
                peer_info = skill_by_id.get(peer_sid, {})
                peer_title = str(peer_info.get("name") or peer_sid)
                peer_source = str(peer_info.get("source") or (DEFAULT_SKILLS_ROOT / peer_sid))
                peer_node_id = f"{sid}:peer:{peer_sid}"
                _add_node(
                    node_id=peer_node_id,
                    skill_id=sid,
                    kind="peer_skill",
                    title=f"{peer_title} ({rel_type})",
                    summary=f"{sname} {rel_type}s peer skill {peer_title}: {rel_note}",
                    source_path=peer_source,
                    parent_id=root_node_id,
                    ring=1,
                    token_estimate=260,
                )
                _add_edge(root_node_id, peer_node_id, "composes_skill", weight=1.2, note=f"{rel_type}: {rel_note}")
                _add_edge(root_node_id, peer_node_id, "hierarchy", weight=1.0)
                if f"skill:{peer_sid}" != root_node_id:
                    _add_edge(root_node_id, f"skill:{peer_sid}", "composes_skill", weight=1.2, note=rel_type)

            # 3. Knowledge Sources (`SKILL.md`, `HUMAN.md`, `NORTH-STAR.md`, `VISION.md`, `journal/*.md`)
            for doc_name in ("SKILL.md", "HUMAN.md", "NORTH-STAR.md", "VISION.md", "LESSONS.md"):
                doc_path = sdir / doc_name
                if not doc_path.is_file():
                    continue
                raw_doc = doc_path.read_bytes()
                doc_lines = max(1, len(raw_doc.decode("utf-8-sig", errors="replace").splitlines()))
                doc_node_id = f"{sid}:source:{doc_name.lower()}"
                _add_node(
                    node_id=doc_node_id,
                    skill_id=sid,
                    kind="knowledge_source",
                    title=f"{sname} · {doc_name}",
                    summary=f"Canonical {doc_name} specification for {sname} ({doc_lines} lines)",
                    source_path=str(doc_path.resolve()),
                    start_line=1,
                    end_line=doc_lines,
                    sha256=hashlib.sha256(raw_doc).hexdigest(),
                    parent_id=root_node_id,
                    ring=1,
                    token_estimate=350,
                )
                _add_edge(root_node_id, doc_node_id, "reads_source", weight=1.0, note=doc_name)
                _add_edge(root_node_id, doc_node_id, "hierarchy", weight=1.0)

                # Extract Ring-2 Markdown sections from SKILL.md / HUMAN.md
                if doc_name in ("SKILL.md", "HUMAN.md"):
                    for sec_idx, sec in enumerate(extract_markdown_sections(doc_path, max_sections=5)):
                        sec_id = f"{doc_node_id}:sec{sec_idx}"
                        _add_node(
                            node_id=sec_id,
                            skill_id=sid,
                            kind="knowledge_source",
                            title=f"{doc_name} § {sec['title']}",
                            summary=sec["summary"],
                            source_path=str(doc_path.resolve()),
                            start_line=sec["start_line"],
                            end_line=sec["end_line"],
                            sha256=sec["sha256"],
                            parent_id=doc_node_id,
                            ring=2,
                            token_estimate=sec["token_estimate"],
                        )
                        _add_edge(doc_node_id, sec_id, "hierarchy", weight=0.9)
                        _add_edge(doc_node_id, sec_id, "reads_source", weight=0.9)

            # Ingest up to 4 most recent journal entries (`journal/*.md`)
            journal_dir = sdir / "journal"
            if journal_dir.is_dir():
                for j_path in sorted(journal_dir.glob("*.md"), reverse=True)[:4]:
                    if not j_path.is_file():
                        continue
                    j_bytes = j_path.read_bytes()
                    j_text = j_bytes.decode("utf-8-sig", errors="replace")
                    j_lines = max(1, len(j_text.splitlines()))
                    j_preview = " ".join(l.strip() for l in j_text.splitlines()[:6] if l.strip())[:240]
                    j_node_id = f"{sid}:journal:{j_path.stem}"
                    _add_node(
                        node_id=j_node_id,
                        skill_id=sid,
                        kind="knowledge_source",
                        title=f"Journal · {j_path.stem}",
                        summary=j_preview or f"Operational journal entry {j_path.name} for {sname}",
                        source_path=str(j_path.resolve()),
                        start_line=1,
                        end_line=j_lines,
                        sha256=hashlib.sha256(j_bytes).hexdigest(),
                        parent_id=root_node_id,
                        ring=1,
                        token_estimate=_estimate_tokens(j_text),
                    )
                    _add_edge(root_node_id, j_node_id, "reads_source", weight=0.85, note="journal")
                    _add_edge(root_node_id, j_node_id, "hierarchy", weight=0.85)

            # 4. Tools (`kind='tool'`, `edge_type='invokes_tool'`) & Code AST Symbols (`kind='code_symbol'`)
            tool_files: List[Path] = []
            if sdir.is_dir():
                for pattern in (
                    "*.py",
                    "*.mjs",
                    "*.js",
                    "bin/*.mjs",
                    "bin/*.js",
                    "bin/*.py",
                    "runtime/*.mjs",
                    "runtime/*.js",
                    "scripts/*.py",
                    "scripts/*.mjs",
                    "seam/*.mjs",
                ):
                    for candidate in sorted(sdir.glob(pattern)):
                        if candidate.is_file() and candidate not in tool_files:
                            tool_files.append(candidate)

            for t_path in tool_files[:10]:
                try:
                    t_bytes = t_path.read_bytes()
                except OSError:
                    continue
                t_text = t_bytes.decode("utf-8-sig", errors="replace")
                t_lines = max(1, len(t_text.splitlines()))
                rel_name = t_path.relative_to(sdir).as_posix() if t_path.is_relative_to(sdir) else t_path.name
                tool_node_id = f"{sid}:tool:{rel_name}"
                first_comment = next(
                    (
                        l.strip().lstrip("#/*\"' ")
                        for l in t_text.splitlines()[:12]
                        if l.strip() and not l.strip().startswith("#!")
                    ),
                    f"Executable tool {rel_name} for {sname}",
                )
                _add_node(
                    node_id=tool_node_id,
                    skill_id=sid,
                    kind="tool",
                    title=f"Tool · {rel_name}",
                    summary=f"{rel_name}: {first_comment[:220]}",
                    source_path=str(t_path.resolve()),
                    start_line=1,
                    end_line=t_lines,
                    sha256=hashlib.sha256(t_bytes).hexdigest(),
                    parent_id=root_node_id,
                    ring=1,
                    token_estimate=400,
                )
                _add_edge(root_node_id, tool_node_id, "invokes_tool", weight=1.1, note=rel_name)
                _add_edge(root_node_id, tool_node_id, "hierarchy", weight=1.0)
                _add_edge(tool_node_id, repo_node_id, "lives_in_repo", weight=0.8)

                # If Python tool, extract Ring-2/3 AST symbols (`def` / `class`)
                if t_path.suffix.lower() == ".py":
                    for sym in extract_python_ast_symbols(t_path, max_symbols=5):
                        sym_id = f"{tool_node_id}:ast:{sym['name']}"
                        _add_node(
                            node_id=sym_id,
                            skill_id=sid,
                            kind="code_symbol",
                            title=f"{t_path.name}::{sym['name']}",
                            summary=sym["summary"],
                            source_path=str(t_path.resolve()),
                            start_line=sym["start_line"],
                            end_line=sym["end_line"],
                            sha256=sym["sha256"],
                            parent_id=tool_node_id,
                            ring=2,
                            token_estimate=sym["token_estimate"],
                        )
                        _add_edge(tool_node_id, sym_id, "hierarchy", weight=0.95)
                        _add_edge(tool_node_id, sym_id, "invokes_tool", weight=0.9)

            # 5. Ingest declared `maps.json` (if present in `Foundry page and knowledge maps`)
            role_map_dir = {
                "steward-project": "steward-lamp",
                "steward-portfolio": "steward-cave",
                "steward-starchart": "steward-star-chart",
            }.get(sid, sid)
            maps_json_path = DEFAULT_CONTENT_ROOT / role_map_dir / "maps.json"
            if maps_json_path.is_file():
                try:
                    mdata = json.loads(maps_json_path.read_text(encoding="utf-8-sig"))
                except Exception:
                    mdata = {}
                if isinstance(mdata, dict):
                    # Ingest declared process steps (`kind='process_step'`) & transitions
                    proc = mdata.get("process") or {}
                    p_steps = proc.get("steps") if isinstance(proc, dict) else []
                    if isinstance(p_steps, list) and p_steps:
                        total_p = len(p_steps)
                        for idx_p, st in enumerate(p_steps[:12]):
                            if not isinstance(st, dict) or not st.get("id"):
                                continue
                            st_id = f"{sid}:step:{st['id']}"
                            _add_node(
                                node_id=st_id,
                                skill_id=sid,
                                kind="process_step",
                                title=str(st.get("title") or st["id"]),
                                summary=str(st.get("summary") or st.get("title") or st["id"]),
                                source_path=str(maps_json_path.resolve()),
                                start_line=1,
                                end_line=1,
                                parent_id=root_node_id,
                                ring=2,
                                token_estimate=320,
                                step_index=idx_p,
                                total_steps=total_p,
                            )
                            _add_edge(root_node_id, st_id, "hierarchy", weight=0.9)
                            _add_edge(root_node_id, st_id, "process_flow", weight=1.0)
                        for pe in (proc.get("edges") or []):
                            if isinstance(pe, dict) and pe.get("source") and pe.get("target"):
                                s_step = f"{sid}:step:{pe['source']}"
                                t_step = f"{sid}:step:{pe['target']}"
                                if s_step in all_nodes and t_step in all_nodes:
                                    _add_edge(
                                        s_step,
                                        t_step,
                                        "process_flow",
                                        weight=1.0,
                                        note=str(pe.get("label") or ""),
                                    )

        # Calibrate Lorentz & Poincare coordinates per skill tree
        by_skill: Dict[str, List[Dict[str, Any]]] = {}
        for node in all_nodes.values():
            by_skill.setdefault(node["skill_id"], []).append(node)

        for sid, s_nodes in by_skill.items():
            root_id = f"skill:{sid}" if f"skill:{sid}" in all_nodes else None
            calibrated = calibrate_tree_lorentz_coordinates(s_nodes, root_id=root_id, kappa=1.0)
            for node in s_nodes:
                nid = node["node_id"]
                if nid in calibrated:
                    lor, px, py = calibrated[nid]
                    node["lorentz_vec"] = lor
                    node["poincare_x"] = px
                    node["poincare_y"] = py

        # Persist atomically to SQLite + FTS5
        with self._connect() as conn:
            existing_usage = {
                row["node_id"]: (
                    int(row["usage_count"]),
                    int(row["success_count"]),
                    float(row["outcome_credit"]),
                )
                for row in conn.execute(
                    "SELECT node_id, usage_count, success_count, outcome_credit FROM kb_nodes"
                ).fetchall()
            }

            for nid, node in all_nodes.items():
                u_cnt, s_cnt, cred = existing_usage.get(nid, (0, 0, 0.5))
                conn.execute(
                    """
                    INSERT INTO kb_nodes (
                        node_id, skill_id, kind, title, summary, source_path,
                        start_line, end_line, sha256, parent_id, ring, token_estimate,
                        lorentz_vec, poincare_x, poincare_y, spherical_vec, euclidean_vec,
                        usage_count, success_count, outcome_credit
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(node_id) DO UPDATE SET
                        skill_id=excluded.skill_id,
                        kind=excluded.kind,
                        title=excluded.title,
                        summary=excluded.summary,
                        source_path=excluded.source_path,
                        start_line=excluded.start_line,
                        end_line=excluded.end_line,
                        sha256=excluded.sha256,
                        parent_id=excluded.parent_id,
                        ring=excluded.ring,
                        token_estimate=excluded.token_estimate,
                        lorentz_vec=excluded.lorentz_vec,
                        poincare_x=excluded.poincare_x,
                        poincare_y=excluded.poincare_y,
                        spherical_vec=excluded.spherical_vec,
                        euclidean_vec=excluded.euclidean_vec
                    """,
                    (
                        nid,
                        node["skill_id"],
                        node["kind"],
                        node["title"],
                        node["summary"],
                        node["source_path"],
                        node["start_line"],
                        node["end_line"],
                        node["sha256"],
                        node["parent_id"],
                        node["ring"],
                        node["token_estimate"],
                        json.dumps(node["lorentz_vec"]),
                        node["poincare_x"],
                        node["poincare_y"],
                        json.dumps(node["spherical_vec"]),
                        json.dumps(node["euclidean_vec"]),
                        u_cnt,
                        s_cnt,
                        cred,
                    ),
                )

            for edge in all_edges.values():
                conn.execute(
                    """
                    INSERT INTO kb_edges (source_id, target_id, edge_type, weight, note)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(source_id, target_id, edge_type) DO UPDATE SET
                        weight=excluded.weight,
                        note=excluded.note
                    """,
                    (
                        edge["source_id"],
                        edge["target_id"],
                        edge["edge_type"],
                        edge["weight"],
                        edge["note"],
                    ),
                )

            if self._fts5_enabled:
                conn.execute("DELETE FROM kb_fts;")
                conn.executemany(
                    "INSERT INTO kb_fts (node_id, skill_id, kind, title, summary) VALUES (?, ?, ?, ?, ?)",
                    [
                        (
                            n["node_id"],
                            n["skill_id"],
                            n["kind"],
                            n["title"],
                            n["summary"],
                        )
                        for n in all_nodes.values()
                    ],
                )

        elapsed_ms = (time.perf_counter() - t0) * 1000.0
        return {
            "skills_ingested": len(by_skill),
            "nodes_ingested": len(all_nodes),
            "edges_ingested": len(all_edges),
            "elapsed_ms": round(elapsed_ms, 2),
            "db_path": str(self.db_path),
        }

    # ── Hybrid FTS5 + Product-Manifold + Submodular Context Router ───────────

    def _fts_scores(
        self,
        conn: sqlite3.Connection,
        query_text: str,
        skill_id: Optional[str] = None,
        kind: Optional[str] = None,
    ) -> Dict[str, float]:
        tokens = re.findall(r"[a-zA-Z0-9_]{2,}", query_text or "")
        if not tokens or not self._fts5_enabled:
            return {}
        fts_expr = " OR ".join(f'"{t}"*' for t in tokens[:10])
        sql = "SELECT node_id, bm25(kb_fts, 1.0, 1.0, 3.0, 1.5) AS rank_score FROM kb_fts WHERE kb_fts MATCH ?"
        params: List[Any] = [fts_expr]
        if skill_id:
            sql += " AND skill_id = ?"
            params.append(skill_id)
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        sql += " ORDER BY rank_score LIMIT 120"
        try:
            rows = conn.execute(sql, params).fetchall()
        except sqlite3.OperationalError:
            return {}
        if not rows:
            return {}
        # SQLite FTS5 bm25() returns negative numbers where more negative = better match
        raw = {str(r["node_id"]): -float(r["rank_score"]) for r in rows}
        max_v = max(raw.values()) or 1.0
        min_v = min(raw.values())
        span = (max_v - min_v) if max_v > min_v else max_v
        return {nid: max(0.05, (val - min_v) / span if span > 0 else 1.0) for nid, val in raw.items()}

    def query_hybrid(
        self,
        query_text: str,
        skill_id: Optional[str] = None,
        kind: Optional[str] = None,
        token_budget: int = 1500,
        limit: int = 12,
    ) -> Dict[str, Any]:
        """Execute a Hybrid FTS5 (`BM25`) + Generalized Product-Manifold geodesic query
        and select an optimal tiered context pack within `token_budget` using greedy
        submodular marginal-gain-per-token routing."""
        t0 = time.perf_counter()
        with self._connect() as conn:
            fts_map = self._fts_scores(conn, query_text, skill_id=skill_id, kind=kind)

            sql = "SELECT * FROM kb_nodes WHERE 1=1"
            params: List[Any] = []
            if skill_id:
                sql += " AND skill_id = ?"
                params.append(skill_id)
            if kind:
                sql += " AND kind = ?"
                params.append(kind)
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

        if not rows:
            return {
                "query": query_text,
                "skill_id": skill_id,
                "token_budget": token_budget,
                "tokens_loaded": 0,
                "tokens_saved": 0,
                "full_catalog_tokens": 0,
                "results": [],
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            }

        for r in rows:
            r["lorentz_vec"] = json.loads(r["lorentz_vec"])
            r["spherical_vec"] = json.loads(r["spherical_vec"])
            r["euclidean_vec"] = json.loads(r["euclidean_vec"])

        # Construct query manifold anchor: use top FTS match's Lorentz & Spherical position
        # (or origin [1, 0, 0]) + query's Euclidean lexical embedding
        q_euc = compute_euclidean_embedding(query_text or "", kind=kind or "knowledge_source", ring=1)
        if fts_map:
            best_fts_id = max(fts_map, key=fts_map.get)
            anchor_node = next((r for r in rows if r["node_id"] == best_fts_id), rows[0])
            q_lor = anchor_node["lorentz_vec"]
            q_sph = anchor_node["spherical_vec"]
        else:
            q_lor = [1.0, 0.0, 0.0]
            q_sph = [1.0, 0.0]

        query_point = (q_lor, q_sph, q_euc)
        q_tokens = set(re.findall(r"[a-z0-9_]{2,}", (query_text or "").lower()))

        for r in rows:
            nid = r["node_id"]
            bm25_norm = fts_map.get(nid, 0.0)
            if bm25_norm == 0.0 and q_tokens:
                text_bag = f"{r['title']} {r['summary']} {r['kind']}".lower()
                hits = sum(1 for tok in q_tokens if tok in text_bag)
                bm25_norm = hits / float(len(q_tokens))

            d_prod = product_manifold_distance(query_point, r, weights=(1.0, 0.4, 0.6))
            geo_sim = math.exp(-0.65 * d_prod)
            credit = float(r.get("outcome_credit") or 0.5)
            # Ring 0 skill overview receives a structural base bonus
            ring_bonus = 0.15 if int(r["ring"]) == 0 else 0.0

            hybrid_score = 0.50 * bm25_norm + 0.35 * geo_sim + 0.15 * credit + ring_bonus
            r["bm25_score"] = round(bm25_norm, 6)
            r["manifold_distance"] = round(d_prod, 6)
            r["geodesic_similarity"] = round(geo_sim, 6)
            r["hybrid_score"] = round(hybrid_score, 6)

        # Rank candidates by hybrid score and apply Submodular Tree-Knapsack Budget Routing
        candidates = sorted(rows, key=lambda item: item["hybrid_score"], reverse=True)[: max(limit * 3, 24)]
        full_catalog_tokens = sum(int(r.get("token_estimate") or 150) for r in rows)

        selected: List[Dict[str, Any]] = []
        selected_ids: set[str] = set()
        covered_kinds: Dict[str, int] = {}
        covered_parents: set[str] = set()
        tokens_loaded = 0

        while len(selected) < limit:
            best_cand = None
            best_density = -1.0
            for cand in candidates:
                cid = cand["node_id"]
                cost = max(25, int(cand.get("token_estimate") or 150))
                if cid in selected_ids or (tokens_loaded + cost) > token_budget:
                    continue
                # Diminishing-returns submodular diversity discount for redundant kinds/siblings
                kind_count = covered_kinds.get(cand["kind"], 0)
                redundancy_discount = (0.72 ** kind_count) * (
                    0.82 if cand.get("parent_id") in covered_parents else 1.0
                )
                marginal_gain = max(1e-6, cand["hybrid_score"]) * redundancy_discount
                density = marginal_gain / (float(cost) ** 0.65)
                if density > best_density:
                    best_density = density
                    best_cand = cand
            if best_cand is None:
                break
            selected.append(best_cand)
            selected_ids.add(best_cand["node_id"])
            covered_kinds[best_cand["kind"]] = covered_kinds.get(best_cand["kind"], 0) + 1
            if best_cand.get("parent_id"):
                covered_parents.add(str(best_cand["parent_id"]))
            tokens_loaded += max(25, int(best_cand.get("token_estimate") or 150))

        selected.sort(key=lambda item: item["hybrid_score"], reverse=True)
        tokens_saved = max(0, full_catalog_tokens - tokens_loaded)

        return {
            "query": query_text,
            "skill_id": skill_id,
            "kind_filter": kind,
            "token_budget": token_budget,
            "tokens_loaded": tokens_loaded,
            "tokens_saved": tokens_saved,
            "full_catalog_tokens": full_catalog_tokens,
            "token_savings_pct": round(
                (tokens_saved / float(full_catalog_tokens)) * 100.0 if full_catalog_tokens > 0 else 0.0,
                2,
            ),
            "results": selected,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }

    def query_orthogonal_task(
        self,
        query_text: str,
        task_phase: str = "balanced",
        slice_axes: Tuple[int, int] = (0, 1),
        skill_id: Optional[str] = None,
        kind: Optional[str] = None,
        token_budget: int = 1500,
        limit: int = 12,
    ) -> Dict[str, Any]:
        """Execute a Task-Phase Selective Retrieval query over the 3D Poincare Sphere
        (B^3_1 <-> L^3_1) and Orthogonal Knowledge Subspaces:
          * Axis 0 (`domain_hierarchy`): Substantive domain hierarchy
          * Axis 1 (`task_phase_axis`): Procedural task execution stage (`ingest`, `compute`, `verify`, `emit`)
          * Axis 2 (`modality_axis`): Resource modality (`knowledge_source`, `tool`, `code_symbol`, `peer_skill`, `repository`)

        Dynamically weights the orthogonal hyperbolic subspaces via `TASK_PHASE_WEIGHTS[task_phase]`
        and returns each selected node with both its 3D Poincare sphere coordinates
        (`poincare_3d`, `lorentz_3d`) and its 2D projected slice (`poincare_slice_2d`)
        along `slice_axes`.
        """
        t0 = time.perf_counter()
        phase_key = str(task_phase or "balanced").strip().lower()
        if phase_key not in TASK_PHASE_WEIGHTS:
            raise ValueError(
                f"Unsupported task_phase '{task_phase}'. Expected one of {tuple(TASK_PHASE_WEIGHTS.keys())}"
            )
        w_dom, w_phase, w_mod, w_sph, w_euc = TASK_PHASE_WEIGHTS[phase_key]
        ax_a, ax_b = int(slice_axes[0]), int(slice_axes[1])
        if ax_a < 0 or ax_a >= 3 or ax_b < 0 or ax_b >= 3 or ax_a == ax_b:
            raise ValueError("slice_axes must be a pair of distinct axis indices in {0, 1, 2}")

        with self._connect() as conn:
            fts_map = self._fts_scores(conn, query_text, skill_id=skill_id, kind=kind)
            sql = "SELECT * FROM kb_nodes WHERE 1=1"
            params: List[Any] = []
            if skill_id:
                sql += " AND skill_id = ?"
                params.append(skill_id)
            if kind:
                sql += " AND kind = ?"
                params.append(kind)
            rows = [dict(r) for r in conn.execute(sql, params).fetchall()]

        if not rows:
            return {
                "query": query_text,
                "task_phase": phase_key,
                "phase_weights": {
                    "domain_hierarchy": w_dom,
                    "task_phase_axis": w_phase,
                    "modality_axis": w_mod,
                    "spherical": w_sph,
                    "euclidean": w_euc,
                },
                "slice_axes": [ax_a, ax_b],
                "slice_axis_names": [ORTHOGONAL_AXIS_NAMES[ax_a], ORTHOGONAL_AXIS_NAMES[ax_b]],
                "skill_id": skill_id,
                "token_budget": token_budget,
                "tokens_loaded": 0,
                "tokens_saved": 0,
                "full_catalog_tokens": 0,
                "results": [],
                "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
            }

        for r in rows:
            r["lorentz_vec"] = json.loads(r["lorentz_vec"])
            r["spherical_vec"] = json.loads(r["spherical_vec"])
            r["euclidean_vec"] = json.loads(r["euclidean_vec"])
            emb3d = embed_node_3d_poincare(r, kappa=1.0)
            r.update(emb3d)
            lor_slice = lorentz_project_subspace(r["lorentz_3d"], (ax_a, ax_b), kappa=1.0, mode="sheet")
            p_slice = lorentz_to_poincare(lor_slice, kappa=1.0)
            r["lorentz_slice_2d"] = [round(c, 8) for c in lor_slice]
            r["poincare_slice_2d"] = [round(p_slice[0], 8), round(p_slice[1], 8)]

        # Build query anchor in 3D Lorentz space + Spherical + Euclidean
        target_kind_for_phase = {
            "ingest": "knowledge_source",
            "compute": "tool",
            "verify": "process_step",
            "emit": "knowledge_source",
            "collaborate": "peer_skill",
            "balanced": kind or "knowledge_source",
        }[phase_key]
        q_euc = compute_euclidean_embedding(query_text or "", kind=kind or target_kind_for_phase, ring=1)

        # Select anchor node preferring FTS match aligned with active task phase
        if fts_map:
            best_fts_id = max(
                fts_map,
                key=lambda nid: fts_map[nid]
                + (0.25 if next((x["task_phase"] for x in rows if x["node_id"] == nid), "") == phase_key else 0.0),
            )
            anchor_node = next((r for r in rows if r["node_id"] == best_fts_id), rows[0])
        else:
            phase_matches = [r for r in rows if r["task_phase"] == phase_key]
            anchor_node = phase_matches[0] if phase_matches else rows[0]

        q_lor3 = anchor_node["lorentz_3d"]
        q_sph = anchor_node["spherical_vec"]
        q_dom_1d = lorentz_project_subspace(q_lor3, (0,), kappa=1.0, mode="sheet")

        # Anchor Axis 1 (task_phase_axis) and Axis 2 (modality_axis) on the active task_phase
        phase_modality_nodes = [
            r for r in rows if r["task_phase"] == phase_key or r["kind"] == target_kind_for_phase
        ]
        if phase_key != "balanced" and phase_modality_nodes:
            phase_anchor = max(
                phase_modality_nodes,
                key=lambda r: (1.0 if r["task_phase"] == phase_key else 0.0)
                + (1.0 if r["kind"] == target_kind_for_phase else 0.0)
                + fts_map.get(r["node_id"], 0.0),
            )
            q_phase_1d = lorentz_project_subspace(phase_anchor["lorentz_3d"], (1,), kappa=1.0, mode="sheet")
            q_mod_1d = lorentz_project_subspace(phase_anchor["lorentz_3d"], (2,), kappa=1.0, mode="sheet")
        else:
            q_phase_1d = lorentz_project_subspace(q_lor3, (1,), kappa=1.0, mode="sheet")
            q_mod_1d = lorentz_project_subspace(q_lor3, (2,), kappa=1.0, mode="sheet")

        q_tokens = set(re.findall(r"[a-z0-9_]{2,}", (query_text or "").lower()))

        for r in rows:
            nid = r["node_id"]
            bm25_norm = fts_map.get(nid, 0.0)
            if bm25_norm == 0.0 and q_tokens:
                text_bag = f"{r['title']} {r['summary']} {r['kind']}".lower()
                hits = sum(1 for tok in q_tokens if tok in text_bag)
                bm25_norm = hits / float(len(q_tokens))

            r_lor3 = r["lorentz_3d"]
            d_dom = lorentz_distance(q_dom_1d, lorentz_project_subspace(r_lor3, (0,), kappa=1.0, mode="sheet"))
            d_phase = lorentz_distance(q_phase_1d, lorentz_project_subspace(r_lor3, (1,), kappa=1.0, mode="sheet"))
            d_mod = lorentz_distance(q_mod_1d, lorentz_project_subspace(r_lor3, (2,), kappa=1.0, mode="sheet"))
            d_sph = spherical_distance(q_sph, r["spherical_vec"])
            d_euc = euclidean_distance(q_euc, r["euclidean_vec"])

            d_tau = math.sqrt(
                w_dom * d_dom * d_dom
                + w_phase * d_phase * d_phase
                + w_mod * d_mod * d_mod
                + w_sph * d_sph * d_sph
                + w_euc * d_euc * d_euc
            )
            geo_sim = math.exp(-0.45 * d_tau)
            credit = float(r.get("outcome_credit") or 0.5)

            # Task-phase & modality selective alignment bonus
            phase_alignment = 0.0
            if phase_key != "balanced":
                if r["task_phase"] == phase_key:
                    phase_alignment += 0.28
                if phase_key == "compute" and r["kind"] in ("tool", "code_symbol"):
                    phase_alignment += 0.22
                elif phase_key == "ingest" and r["kind"] == "knowledge_source" and "journal" not in nid:
                    phase_alignment += 0.34
                elif phase_key == "verify" and (r["task_phase"] == "verify" or r["kind"] == "process_step"):
                    phase_alignment += 0.22
                elif phase_key == "collaborate" and r["kind"] == "peer_skill":
                    phase_alignment += 0.30
                elif phase_key == "emit" and ("journal" in nid or r["task_phase"] == "emit"):
                    phase_alignment += 0.24

            ring_bonus = 0.10 if int(r["ring"]) == 0 else 0.0
            orthogonal_score = (
                0.42 * bm25_norm
                + 0.33 * geo_sim
                + 0.15 * credit
                + phase_alignment
                + ring_bonus
            )
            r["bm25_score"] = round(bm25_norm, 6)
            r["orthogonal_distance"] = round(d_tau, 6)
            r["geodesic_similarity"] = round(geo_sim, 6)
            r["phase_alignment_bonus"] = round(phase_alignment, 6)
            r["hybrid_score"] = round(orthogonal_score, 6)

        candidates = sorted(rows, key=lambda item: item["hybrid_score"], reverse=True)[: max(limit * 3, 24)]
        full_catalog_tokens = sum(int(r.get("token_estimate") or 150) for r in rows)

        selected: List[Dict[str, Any]] = []
        selected_ids: set[str] = set()
        covered_kinds: Dict[str, int] = {}
        covered_parents: set[str] = set()
        tokens_loaded = 0

        while len(selected) < limit:
            best_cand = None
            best_density = -1.0
            for cand in candidates:
                cid = cand["node_id"]
                cost = max(25, int(cand.get("token_estimate") or 150))
                if cid in selected_ids or (tokens_loaded + cost) > token_budget:
                    continue
                kind_count = covered_kinds.get(cand["kind"], 0)
                redundancy_discount = (0.78 ** kind_count) * (
                    0.85 if cand.get("parent_id") in covered_parents else 1.0
                )
                marginal_gain = max(1e-6, cand["hybrid_score"]) * redundancy_discount
                density = marginal_gain / (float(cost) ** 0.65)
                if density > best_density:
                    best_density = density
                    best_cand = cand
            if best_cand is None:
                break
            selected.append(best_cand)
            selected_ids.add(best_cand["node_id"])
            covered_kinds[best_cand["kind"]] = covered_kinds.get(best_cand["kind"], 0) + 1
            if best_cand.get("parent_id"):
                covered_parents.add(str(best_cand["parent_id"]))
            tokens_loaded += max(25, int(best_cand.get("token_estimate") or 150))

        selected.sort(key=lambda item: item["hybrid_score"], reverse=True)
        tokens_saved = max(0, full_catalog_tokens - tokens_loaded)

        return {
            "query": query_text,
            "task_phase": phase_key,
            "phase_weights": {
                "domain_hierarchy": w_dom,
                "task_phase_axis": w_phase,
                "modality_axis": w_mod,
                "spherical": w_sph,
                "euclidean": w_euc,
            },
            "slice_axes": [ax_a, ax_b],
            "slice_axis_names": [ORTHOGONAL_AXIS_NAMES[ax_a], ORTHOGONAL_AXIS_NAMES[ax_b]],
            "manifold": "L^3_1 (Domain x TaskPhase x Modality) x S^1_1 x E^8 -> B^3_1 & B^2_1",
            "skill_id": skill_id,
            "kind_filter": kind,
            "token_budget": token_budget,
            "tokens_loaded": tokens_loaded,
            "tokens_saved": tokens_saved,
            "full_catalog_tokens": full_catalog_tokens,
            "token_savings_pct": round(
                (tokens_saved / float(full_catalog_tokens)) * 100.0 if full_catalog_tokens > 0 else 0.0,
                2,
            ),
            "results": selected,
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 3),
        }


    # ── Execution Telemetry & Piaget Assimilation ────────────────────────────

    def log_execution(
        self,
        skill_id: str,
        task_summary: str,
        tools_used: Optional[Sequence[str]] = None,
        peer_skills: Optional[Sequence[str]] = None,
        sources_used: Optional[Sequence[str]] = None,
        outcome: str = "success",
        run_id: Optional[str] = None,
        nodes_accessed: Optional[Sequence[str]] = None,
        tokens_loaded: int = 850,
        tokens_saved: int = 4200,
    ) -> Dict[str, Any]:
        """Record a real or simulated skill execution in `librarian_access_log` and
        perform online Piaget assimilation by updating `usage_count`, `success_count`,
        and Laplace-smoothed `outcome_credit` on all accessed KB nodes."""
        rid = str(run_id or f"run-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}")
        ts = time.time()
        tools_list = [str(x) for x in (tools_used or ())]
        peers_list = [str(x) for x in (peer_skills or ())]
        sources_list = [str(x) for x in (sources_used or ())]
        accessed_set = {str(x) for x in (nodes_accessed or ())}
        accessed_set.add(f"skill:{skill_id}")

        is_success = 1 if str(outcome).lower() in ("success", "done", "pass", "verified", "ok") else 0

        with self._connect() as conn:
            # Resolve matching node IDs for tools, peer skills, and sources
            skill_rows = conn.execute(
                "SELECT node_id, kind, title, source_path FROM kb_nodes WHERE skill_id = ?",
                (skill_id,),
            ).fetchall()

            for row in skill_rows:
                nid = str(row["node_id"])
                title_low = str(row["title"]).lower()
                path_low = str(row["source_path"]).lower()
                for t_name in tools_list:
                    tl = t_name.lower()
                    if tl in nid.lower() or tl in title_low or tl in path_low:
                        accessed_set.add(nid)
                for p_name in peers_list:
                    pl = p_name.lower()
                    if pl in nid.lower() or pl in title_low:
                        accessed_set.add(nid)
                for s_name in sources_list:
                    sl = s_name.lower()
                    if sl in nid.lower() or sl in title_low or sl in path_low:
                        accessed_set.add(nid)

            accessed_list = sorted(accessed_set)

            for nid in accessed_list:
                conn.execute(
                    """
                    UPDATE kb_nodes
                    SET usage_count = usage_count + 1,
                        success_count = success_count + ?,
                        outcome_credit = CAST(success_count + ? + 1 AS REAL) / CAST(usage_count + 1 + 2 AS REAL)
                    WHERE node_id = ?
                    """,
                    (is_success, is_success, nid),
                )

            conn.execute(
                """
                INSERT INTO librarian_access_log (
                    run_id, timestamp, skill_id, task_summary,
                    nodes_accessed_json, tools_used_json, peer_skills_json, sources_used_json,
                    outcome, tokens_loaded, tokens_saved
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    timestamp=excluded.timestamp,
                    task_summary=excluded.task_summary,
                    nodes_accessed_json=excluded.nodes_accessed_json,
                    tools_used_json=excluded.tools_used_json,
                    peer_skills_json=excluded.peer_skills_json,
                    sources_used_json=excluded.sources_used_json,
                    outcome=excluded.outcome,
                    tokens_loaded=excluded.tokens_loaded,
                    tokens_saved=excluded.tokens_saved
                """,
                (
                    rid,
                    ts,
                    skill_id,
                    task_summary,
                    json.dumps(accessed_list),
                    json.dumps(tools_list),
                    json.dumps(peers_list),
                    json.dumps(sources_list),
                    outcome,
                    int(tokens_loaded),
                    int(tokens_saved),
                ),
            )

        return {
            "run_id": rid,
            "timestamp": ts,
            "skill_id": skill_id,
            "task_summary": task_summary,
            "nodes_accessed": accessed_list,
            "tools_used": tools_list,
            "peer_skills": peers_list,
            "sources_used": sources_list,
            "outcome": outcome,
            "tokens_loaded": int(tokens_loaded),
            "tokens_saved": int(tokens_saved),
        }

    def get_access_logs(self, skill_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent Librarian task access logs (newest first)."""
        with self._connect() as conn:
            if skill_id:
                rows = conn.execute(
                    "SELECT * FROM librarian_access_log WHERE skill_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (skill_id, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM librarian_access_log ORDER BY timestamp DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["nodes_accessed"] = json.loads(d.pop("nodes_accessed_json", "[]"))
            d["tools_used"] = json.loads(d.pop("tools_used_json", "[]"))
            d["peer_skills"] = json.loads(d.pop("peer_skills_json", "[]"))
            d["sources_used"] = json.loads(d.pop("sources_used_json", "[]"))
            out.append(d)
        return out

    # ── Poincare Disk Ecosystem Map Projection ───────────────────────────────

    def poincare_ecosystem_map(
        self,
        skill_id: Optional[str] = None,
        focus_node_id: Optional[str] = None,
        slice_axes: Tuple[int, int] = (0, 1),
    ) -> Dict[str, Any]:
        """Return the complete Poincare disk & 3D Poincare sphere ecosystem map
        (including Skills, Tools, Peer Skills, Knowledge Sources, Repositories,
        Process Steps, and Code Symbols), with optional isometric Mobius recentering
        at `focus_node_id` and 2D orthogonal subspace slicing along `slice_axes`."""
        ax_a, ax_b = int(slice_axes[0]), int(slice_axes[1])
        with self._connect() as conn:
            if skill_id:
                node_rows = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM kb_nodes WHERE skill_id = ? ORDER BY ring ASC, node_id ASC",
                        (skill_id,),
                    ).fetchall()
                ]
            else:
                node_rows = [
                    dict(r)
                    for r in conn.execute(
                        "SELECT * FROM kb_nodes ORDER BY ring ASC, skill_id ASC, node_id ASC"
                    ).fetchall()
                ]

            node_ids = {str(r["node_id"]) for r in node_rows}
            all_edges = [
                dict(e)
                for e in conn.execute("SELECT * FROM kb_edges").fetchall()
                if str(e["source_id"]) in node_ids and str(e["target_id"]) in node_ids
            ]
            run_count_row = conn.execute(
                "SELECT COUNT(*) AS cnt FROM librarian_access_log"
                + (" WHERE skill_id = ?" if skill_id else ""),
                ((skill_id,) if skill_id else ()),
            ).fetchone()
            logged_runs = int(run_count_row["cnt"]) if run_count_row else 0

        for r in node_rows:
            r["lorentz_vec"] = json.loads(r["lorentz_vec"])
            r["spherical_vec"] = json.loads(r["spherical_vec"])
            r["euclidean_vec"] = json.loads(r["euclidean_vec"])
            emb3d = embed_node_3d_poincare(r, kappa=1.0)
            r.update(emb3d)

        focus_xy = [0.0, 0.0]
        focus_lor3 = None
        if focus_node_id:
            focus_node = next((r for r in node_rows if r["node_id"] == focus_node_id), None)
            if focus_node is not None:
                focus_xy = [float(focus_node["poincare_x"]), float(focus_node["poincare_y"])]
                focus_lor3 = focus_node["lorentz_3d"]

        kind_counts: Dict[str, int] = {k: 0 for k in NODE_KINDS}
        projected_nodes: List[Dict[str, Any]] = []
        for r in node_rows:
            kind_counts[r["kind"]] = kind_counts.get(r["kind"], 0) + 1
            if focus_node_id:
                rx, ry = mobius_recenter([r["poincare_x"], r["poincare_y"]], focus_xy)
                lor3_centered = (
                    lorentz_boost_recenter(r["lorentz_3d"], focus_lor3, kappa=1.0)
                    if focus_lor3 is not None
                    else r["lorentz_3d"]
                )
                p3_centered = lorentz_to_poincare(lor3_centered, kappa=1.0)
            else:
                rx, ry = float(r["poincare_x"]), float(r["poincare_y"])
                lor3_centered = r["lorentz_3d"]
                p3_centered = r["poincare_3d"]

            lor_slice = lorentz_project_subspace(lor3_centered, (ax_a, ax_b), kappa=1.0, mode="sheet")
            p_slice = lorentz_to_poincare(lor_slice, kappa=1.0)
            projected_nodes.append({
                **r,
                "display_x": round(rx, 6),
                "display_y": round(ry, 6),
                "display_3d": [round(c, 6) for c in p3_centered],
                "poincare_slice_2d": [round(p_slice[0], 6), round(p_slice[1], 6)],
                "svg_x": round(300.0 + rx * 265.0, 2),
                "svg_y": round(300.0 + ry * 265.0, 2),
            })

        return {
            "schema": "foundry-librarian-ecosystem-map/v1",
            "manifold": "L^2_1 x S^1_1 x E^8 -> stereographic B^2_1 (with 3D Sphere L^3_1 -> B^3_1)",
            "orthogonal_axes": list(ORTHOGONAL_AXIS_NAMES),
            "slice_axes": [ax_a, ax_b],
            "geometry_mode": "assimilated-usage-weighted" if logged_runs > 0 else "seeded-product-manifold",
            "skill_id": skill_id,
            "focus_node_id": focus_node_id,
            "logged_runs": logged_runs,
            "kind_counts": kind_counts,
            "nodes": projected_nodes,
            "edges": all_edges,
        }

    def ensure_populated(self, seed_activity: bool = True) -> Dict[str, Any]:
        """Ensure the SQLite KB is populated with all 19 canonical skills and initial
        verified activity logs if empty."""
        with self._connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS cnt FROM kb_nodes WHERE kind = 'skill'").fetchone()
            skill_cnt = int(row["cnt"]) if row else 0
            log_row = conn.execute("SELECT COUNT(*) AS cnt FROM librarian_access_log").fetchone()
            log_cnt = int(log_row["cnt"]) if log_row else 0

        stats: Dict[str, Any] = {"skills_ingested": skill_cnt}
        if skill_cnt < 19:
            stats = self.ingest_skill_ecosystem()

        if seed_activity and log_cnt == 0:
            seed_runs = [
                (
                    "researchprime",
                    "Wave 21 Stage 1: Empirical benchmark of SQLite+FTS5 vs LanceDB/DuckDB/Kuzu & Generalized Manifold study",
                    ["run-rounds.mjs", "phase1.mjs", "governor.mjs"],
                    ["crucible", "foreman"],
                    ["SKILL.md", "HUMAN.md"],
                    "success",
                    "run-wave21-rp-study",
                    1420,
                    6850,
                ),
                (
                    "gandalf",
                    "Wave 21 Stage 2: Deep-think critique of 19 Foundry skills context routing, Piaget assimilation & pre-mortem",
                    ["gandalf-run.mjs", "scout.mjs", "live-refuter.mjs"],
                    [],
                    ["SKILL.md", "NORTH-STAR.md"],
                    "success",
                    "run-wave21-gandalf-study",
                    1180,
                    5420,
                ),
                (
                    "ramanujan",
                    "Wave 21 Stage 3: Formal proof & numerical verification of Lorentz stability, S^1 cycle isometry & submodular routing",
                    ["verify_kb_math.py"],
                    [],
                    ["SKILL.md", "HUMAN.md"],
                    "success",
                    "run-wave21-ramanujan-study",
                    960,
                    4910,
                ),
                (
                    "anvil",
                    "3-level progressive abstraction mapping & AST Null Space verification on Anchor modules",
                    [],
                    ["gandalf"],
                    ["SKILL.md", "HUMAN.md"],
                    "success",
                    "run-wave21-anvil-audit",
                    1310,
                    5900,
                ),
                (
                    "aegis",
                    "AST taint/sink security scan across 6 CWE families with cross-family patch verification",
                    [],
                    ["gandalf", "anvil"],
                    ["SKILL.md"],
                    "success",
                    "run-wave21-aegis-scan",
                    1240,
                    5100,
                ),
                (
                    "crucible",
                    "Stage 0-2 implementation plan synthesis with 3-Shark adversarial convergence",
                    ["locate-plan.mjs"],
                    ["foreman"],
                    ["SKILL.md"],
                    "success",
                    "run-wave21-crucible-plan",
                    1390,
                    6200,
                ),
                (
                    "foreman",
                    "Multi-wave autonomous EXECUTE -> REVIEW -> FIX -> RE-REVIEW orchestrator gate",
                    [],
                    [],
                    ["SKILL.md"],
                    "success",
                    "run-wave21-foreman-build",
                    1450,
                    7100,
                ),
            ]
            for sid, summary, tools, peers, sources, out_state, rid, t_load, t_save in seed_runs:
                self.log_execution(
                    skill_id=sid,
                    task_summary=summary,
                    tools_used=tools,
                    peer_skills=peers,
                    sources_used=sources,
                    outcome=out_state,
                    run_id=rid,
                    tokens_loaded=t_load,
                    tokens_saved=t_save,
                )
        return stats

