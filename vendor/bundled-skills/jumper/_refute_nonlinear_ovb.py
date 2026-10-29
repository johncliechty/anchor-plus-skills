"""Named defeater: E[eps|X] not in col(X), z = x^2, vs pack linear z = 0.5 x + u."""
import numpy as np
import pandas as pd

x = pd.read_csv(r"<path> 588\Student Summaries\data\week01-sim.csv")["x"].to_numpy(float)
n = len(x)
X = np.column_stack([np.ones(n), x])
rng = np.random.default_rng(20260907)
nu = 4.0 * rng.standard_normal(n)
alpha, beta, gamma = 2.0, 0.6, 1.0

def ols_resid(y):
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    return b, e

def quad_r2(e):
    X2 = np.column_stack([np.ones(n), x, x**2])
    fit = X2 @ np.linalg.lstsq(X2, e, rcond=None)[0]
    sst = np.sum((e - e.mean()) ** 2)
    return float(1 - np.sum((e - fit) ** 2) / sst)

def slope_on_x(v):
    return float(np.linalg.lstsq(X, v, rcond=None)[0][1])

# World A: eps independent of x
yA = alpha + beta * x + nu
bA, eA = ols_resid(yA)
epsA = nu

# World B: pack preset z = 0.5 x + u  (E[eps|X] in col(X))
u = 3.0 * rng.standard_normal(n)
z_lin = 0.5 * x + u
epsB = gamma * z_lin + nu
yB = alpha + beta * x + epsB
bB, eB = ols_resid(yB)

# World C: named defeater z = x^2  (E[eps|X] NOT in col(X))
z_nl = x**2
epsC = gamma * z_nl + nu
yC = alpha + beta * x + epsC
bC, eC = ols_resid(yC)

# Residual of x^2 on [1,x] — the leftover the plot would show
qhat = X @ np.linalg.lstsq(X, z_nl, rcond=None)[0]
Mx2 = z_nl - qhat

corr_x_x2 = float(np.corrcoef(x, z_nl)[0, 1])

print("n", n)
print("corr(x, x^2)", round(corr_x_x2, 6))
print("Mx2_not_zero", bool(np.max(np.abs(Mx2)) > 1e-8))
print("max_abs_Mx2", float(np.max(np.abs(Mx2))))
print("--- world A exogenous ---")
print("mean_e", float(eA.mean()))
print("slope_e_on_x", slope_on_x(eA))
print("slope_eps_on_x", slope_on_x(epsA))
print("quad_R2_e", quad_r2(eA))
print("Xe", (X.T @ eA).tolist())
print("--- world B linear z=0.5x+u ---")
print("mean_e", float(eB.mean()))
print("slope_e_on_x", slope_on_x(eB))
print("slope_eps_on_x", slope_on_x(epsB))
print("quad_R2_e", quad_r2(eB))
print("b1", float(bB[1]), "bias", float(bB[1] - beta))
print("Xe", (X.T @ eB).tolist())
print("--- world C z=x^2 ---")
print("mean_e", float(eC.mean()))
print("slope_e_on_x", slope_on_x(eC))
print("slope_eps_on_x", slope_on_x(epsC))
print("quad_R2_e", quad_r2(eC))
print("quad_R2_eps", quad_r2(epsC))
print("b1", float(bC[1]), "bias", float(bC[1] - beta))
print("Xe", (X.T @ eC).tolist())
print("corr(eC, Mx2)", float(np.corrcoef(eC, Mx2)[0, 1]))
print("eC_equals_gamma_Mx2_plus_Mnu", bool(np.allclose(eC, gamma * Mx2 + eA)))
print("left_panels_flat_A_and_B", quad_r2(eA) < 0.05 and quad_r2(eB) < 0.05)
print("left_panels_identical_shape_A_vs_C", abs(quad_r2(eA) - quad_r2(eC)) < 0.05)
print("C_residual_shows_curvature", quad_r2(eC) > 0.5)
