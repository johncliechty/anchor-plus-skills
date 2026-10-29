import json, struct, numpy as np
from pathlib import Path

path = Path(
    r"<path>"
    r"\607a30d783dfa663caf39e06633721c8d4cfcd7e\model.safetensors"
)
data = path.read_bytes()
header_size = struct.unpack_from("<Q", data, 0)[0]
header = json.loads(data[8 : 8 + header_size].decode("utf-8"))
base = 8 + header_size

DTYPE = {"F32": np.float32, "F16": np.float16, "BF16": np.float32}


def load(name):
    info = header[name]
    dt = DTYPE[info["dtype"]]
    start, end = info["data_offsets"]
    arr = np.frombuffer(data[base + start : base + end], dtype=dt).reshape(info["shape"])
    return arr.astype(np.float32, copy=False)


mats = {
    "c_attn": [load(f"h.{i}.attn.c_attn.weight") for i in range(12)],
    "c_proj": [load(f"h.{i}.attn.c_proj.weight") for i in range(12)],
    "mlp_fc": [load(f"h.{i}.mlp.c_fc.weight") for i in range(12)],
    "mlp_proj": [load(f"h.{i}.mlp.c_proj.weight") for i in range(12)],
}


def fro(a):
    return float(np.linalg.norm(a))


def cos(a, b):
    na, nb = fro(a), fro(b)
    return float(np.vdot(a.ravel(), b.ravel()) / (na * nb + 1e-12))


print("=== pairwise adjacent cosine (same matrix type) ===")
for k, ws in mats.items():
    cs = [cos(ws[i], ws[i + 1]) for i in range(11)]
    print(
        f"{k:8s} adj-cos mean={np.mean(cs):.4f} min={np.min(cs):.4f} "
        f"max={np.max(cs):.4f} first={cs[0]:.4f} last={cs[-1]:.4f}"
    )

print("\n=== layer norms ===")
for k, ws in mats.items():
    ns = [fro(w) for w in ws]
    print(
        f"{k:8s} ||W|| mean={np.mean(ns):.1f} rel-std={np.std(ns)/np.mean(ns):.3f} "
        f"first={ns[0]:.1f} last={ns[-1]:.1f}"
    )


def stage_eb(ws, stage_size):
    L = len(ws)
    n_stages = L // stage_size
    within_rel = []
    between_vs_global = []
    mean_cos_within = []
    W0 = sum(ws) / L
    X = np.stack([w.ravel() for w in ws])
    for g in range(n_stages):
        sl = slice(g * stage_size, (g + 1) * stage_size)
        grp = ws[sl]
        Wg = sum(grp) / stage_size
        deltas = [w - Wg for w in grp]
        within_rel.extend([fro(d) / (fro(Wg) + 1e-12) for d in deltas])
        between_vs_global.append(fro(Wg - W0) / (fro(W0) + 1e-12))
        cs = []
        for i in range(stage_size):
            for j in range(i + 1, stage_size):
                cs.append(cos(grp[i], grp[j]))
        if cs:
            mean_cos_within.append(np.mean(cs))
    stage_means = []
    within_ss = 0.0
    n_w = 0
    for g in range(n_stages):
        sl = slice(g * stage_size, (g + 1) * stage_size)
        grp = np.stack([w.ravel() for w in ws[sl]])
        mu = grp.mean(axis=0)
        stage_means.append(mu)
        within_ss += ((grp - mu) ** 2).sum()
        n_w += stage_size
    stage_means = np.stack(stage_means)
    grand = stage_means.mean(axis=0)
    between_ss = stage_size * ((stage_means - grand) ** 2).sum()
    P = X.shape[1]
    ms_w = within_ss / (n_w - n_stages) / P
    ms_b = between_ss / max(n_stages - 1, 1) / P
    tau_g = ms_w
    tau_0 = max(0.0, (ms_b - ms_w) / stage_size)
    rms0 = float(np.sqrt((grand ** 2).mean()))
    rel_tau_g = np.sqrt(tau_g) / (rms0 + 1e-12)
    rel_tau_0 = np.sqrt(tau_0) / (rms0 + 1e-12) if tau_0 > 0 else 0.0
    icc_stage = tau_0 / (tau_0 + tau_g + 1e-20)
    return {
        "n_stages": n_stages,
        "mean_rel_delta": float(np.mean(within_rel)),
        "mean_cos_within": float(np.mean(mean_cos_within)) if mean_cos_within else float("nan"),
        "mean_rel_stage_vs_global": float(np.mean(between_vs_global)),
        "rel_tau_g": float(rel_tau_g),
        "rel_tau_0": float(rel_tau_0),
        "icc_stage": float(icc_stage),
        "tau0_over_taug": float(tau_0 / (tau_g + 1e-20)),
    }


print("\n=== empirical-Bayes nested tau (align to stage mean) ===")
print("rel||delta|| ~1 and cos~0 => tau at infinity (no pooling)")
print("icc_stage = tau_0/(tau_0+tau_g); high => stages differ more than layers within")
for k, ws in mats.items():
    print(f"\n-- {k} --")
    for G in (2, 4, 8):
        r = stage_eb(ws, G)
        print(
            f"  G={G:d} stages={r['n_stages']:d}  rel||delta||={r['mean_rel_delta']:.3f}  "
            f"cos_within={r['mean_cos_within']:.4f}  rel_tau_g={r['rel_tau_g']:.3f}  "
            f"rel_tau_0={r['rel_tau_0']:.3f}  icc={r['icc_stage']:.3f}  "
            f"tau0/taug={r['tau0_over_taug']:.3f}  stage_vs_global={r['mean_rel_stage_vs_global']:.3f}"
        )

print("\n=== SVD energy of (W_l - W_g) for mlp_proj, stage size 4 ===")
ws = mats["mlp_proj"]
for g in range(3):
    grp = ws[g * 4 : (g + 1) * 4]
    Wg = sum(grp) / 4
    for j, w in enumerate(grp):
        R = w - Wg
        _, S, _ = np.linalg.svd(R, full_matrices=False)
        energy = np.cumsum(S ** 2) / (np.sum(S ** 2) + 1e-12)
        k50 = int(np.searchsorted(energy, 0.5)) + 1
        k90 = int(np.searchsorted(energy, 0.9)) + 1
        rel = fro(R) / (fro(Wg) + 1e-12)
        print(
            f"  stage{g} layer{g*4+j}: rel={rel:.3f} rank50%={k50} rank90%={k90} "
            f"of {len(S)}  top1_frac={energy[0]:.3f}"
        )

print("\n=== SVD energy of (W_l - W_g) for c_attn, stage size 4 ===")
ws = mats["c_attn"]
for g in range(3):
    grp = ws[g * 4 : (g + 1) * 4]
    Wg = sum(grp) / 4
    for j, w in enumerate(grp):
        R = w - Wg
        _, S, _ = np.linalg.svd(R, full_matrices=False)
        energy = np.cumsum(S ** 2) / (np.sum(S ** 2) + 1e-12)
        k50 = int(np.searchsorted(energy, 0.5)) + 1
        k90 = int(np.searchsorted(energy, 0.9)) + 1
        rel = fro(R) / (fro(Wg) + 1e-12)
        print(
            f"  stage{g} layer{g*4+j}: rel={rel:.3f} rank50%={k50} rank90%={k90} "
            f"of {len(S)}  top1_frac={energy[0]:.3f}"
        )

print("\n=== far-apart cosine (layer 0 vs 11, 2 vs 9) ===")
for k, ws in mats.items():
    print(f"{k:8s} 0vs11={cos(ws[0], ws[11]):.4f} 2vs9={cos(ws[2], ws[9]):.4f} 5vs6={cos(ws[5], ws[6]):.4f}")
