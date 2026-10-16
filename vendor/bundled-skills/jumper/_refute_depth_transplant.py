"""Depth-transplant: GELU atom calibrated at depth 4, frozen at depth 40.

Pass = calibration-in-company of the FROZEN atom:
  half-split agreement on active hidden units, held-out corr(pred, planted)>TAU,
  shuffled-label corr < TAU/2.
"""
import json
import numpy as np

D = 64
H = 64
N = 256
N_SEEDS = 30
DEPTH_CAL = 4
DEPTH_TX = 40
N_SUB = 8
SUB_DIM = D // N_SUB
TAU = 0.35
ACTIVE_TAU = 0.15


def gelu(z):
    return 0.5 * z * (1.0 + np.tanh(np.sqrt(2.0 / np.pi) * (z + 0.044715 * z ** 3)))


def rmsnorm(x):
    rms = np.sqrt(np.mean(x * x, axis=-1, keepdims=True) + 1e-8)
    return x / rms


def corr(a, b):
    a = a - a.mean()
    b = b - b.mean()
    return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))


def active_set(h):
    m = np.mean(np.abs(h), axis=0)
    return m > (ACTIVE_TAU * (np.mean(m) + 1e-12))


def jaccard(a, b):
    a = np.asarray(a, dtype=bool)
    b = np.asarray(b, dtype=bool)
    u = np.sum(a | b)
    if u == 0:
        return 1.0
    return float(np.sum(a & b) / u)


def make_batch(rng):
    s = rng.standard_normal(N)
    v = np.zeros(D)
    v[:SUB_DIM] = rng.standard_normal(SUB_DIM)
    v /= np.linalg.norm(v) + 1e-12
    x = s[:, None] * v[None, :] + 0.25 * rng.standard_normal((N, D))
    return x, s, v


def make_atom(rng):
    w1 = rng.standard_normal((D, H)) / np.sqrt(D)
    w2 = rng.standard_normal((H, 1)) / np.sqrt(H)
    return w1, w2


def apply_atom(xin, w1, w2):
    pre = xin @ w1
    hid = gelu(pre)
    y = (hid @ w2)[:, 0]
    return y, hid, pre


def other_write(x, rng, interface, exclusive, layer):
    w = rng.standard_normal((D, D)) / np.sqrt(D)
    if interface:
        h = np.tanh(rmsnorm(x) @ w)
        gain = 0.5
        delta = gain * h
        if exclusive:
            out = np.zeros_like(x)
            axis = (layer % (N_SUB - 1)) + 1
            sl = slice(axis * SUB_DIM, (axis + 1) * SUB_DIM)
            out[:, sl] = delta[:, sl]
            return out
        return delta
    return 0.55 * np.tanh(x @ w)


def fit_readout(pred, hid, s):
    X = np.column_stack([np.ones(N), pred, hid])
    beta = np.linalg.lstsq(X, s, rcond=None)[0]
    return beta


def predict(pred, hid, beta):
    X = np.column_stack([np.ones(len(pred)), pred, hid])
    return X @ beta


def eval_company(xin, s, w1, w2, beta, act_ref, rng):
    y, hid, pre = apply_atom(xin, w1, w2)
    hat = predict(y, hid, beta)
    idx = np.arange(N)
    rng.shuffle(idx)
    a, b = idx[: N // 2], idx[N // 2 :]
    act_a = active_set(hid[a])
    act_b = active_set(hid[b])
    act_all = active_set(hid)
    half = jaccard(act_a, act_b) >= 0.7
    struct = jaccard(act_all, act_ref) >= 0.7
    c_all = corr(hat, s)
    s_shuf = s.copy()
    rng.shuffle(s_shuf)
    c_noise = corr(hat, s_shuf)
    pred_ok = abs(c_all) > TAU
    noise_ok = abs(c_noise) < TAU / 2
    return dict(
        pass_=bool(half and struct and pred_ok and noise_ok),
        half=bool(half),
        struct=bool(struct),
        pred_ok=bool(pred_ok),
        noise_ok=bool(noise_ok),
        corr=c_all,
        jaccard_ref=float(jaccard(act_all, act_ref)),
        rms=float(np.sqrt(np.mean(xin * xin))),
        pre_std=float(np.std(pre)),
        frac_pos=float(np.mean(pre > 0)),
    )


def run_seed(seed, interface, exclusive):
    rng = np.random.default_rng(seed)
    x, s, v = make_batch(rng)
    w1, w2 = make_atom(rng)
    xs = [x.copy()]
    for layer in range(DEPTH_TX):
        x = x + other_write(x, rng, interface, exclusive, layer)
        xs.append(x.copy())

    def ain(z):
        return rmsnorm(z) if interface else z

    in4 = ain(xs[DEPTH_CAL])
    in40 = ain(xs[DEPTH_TX])
    y4, hid4, pre4 = apply_atom(in4, w1, w2)
    beta = fit_readout(y4, hid4, s)
    act_ref = active_set(hid4)
    r4 = eval_company(in4, s, w1, w2, beta, act_ref, np.random.default_rng(seed + 1000))
    r40 = eval_company(in40, s, w1, w2, beta, act_ref, np.random.default_rng(seed + 2000))
    return dict(pass4=r4["pass_"], pass40=r40["pass_"], corr4=r4["corr"], corr40=r40["corr"],
                j4=r4["jaccard_ref"], j40=r40["jaccard_ref"], rms4=r4["rms"], rms40=r40["rms"],
                pre4=r4["pre_std"], pre40=r40["pre_std"], fp4=r4["frac_pos"], fp40=r40["frac_pos"])


def summarize(interface, exclusive):
    rows = [run_seed(s, interface, exclusive) for s in range(N_SEEDS)]
    def m(k):
        return float(np.mean([r[k] for r in rows]))
    return dict(
        interface=interface,
        exclusive_write=exclusive,
        pass_rate_depth4=m("pass4"),
        pass_rate_depth40=m("pass40"),
        mean_corr4=m("corr4"),
        mean_corr40=m("corr40"),
        mean_jaccard40=m("j40"),
        mean_rms4=m("rms4"),
        mean_rms40=m("rms40"),
        mean_pre_std4=m("pre4"),
        mean_pre_std40=m("pre40"),
        mean_frac_pos4=m("fp4"),
        mean_frac_pos40=m("fp40"),
        n_seeds=N_SEEDS,
    )


conds = {
    "no_interface": summarize(False, False),
    "interface_overlap_write": summarize(True, False),
    "interface_exclusive_write": summarize(True, True),
}
p_off = conds["no_interface"]["pass_rate_depth40"]
p_on = conds["interface_exclusive_write"]["pass_rate_depth40"]
equal = abs(p_off - p_on) < 0.15
both_fail = p_off < 0.3 and p_on < 0.3
both_pass = p_off > 0.7 and p_on > 0.7
out = dict(
    conditions=conds,
    named_pair_pass_depth40={"no_interface": p_off, "full_interface": p_on},
    equal_pass_rates=bool(equal),
    both_fail=bool(both_fail),
    both_pass=bool(both_pass),
    defeater_lands=bool(equal and (both_fail or both_pass)),
)
print(json.dumps(out, indent=2))
