"""Reconstruct the claimed gamma DGP and print residual pattern vs x."""
import numpy as np

x = np.arange(1, 11, dtype=float)
xbar = x.mean()
alpha, beta = 2.0, 0.5

# centered quadratic, then project off [1, x]
q = (x - xbar) ** 2
X = np.column_stack([np.ones_like(x), x])
q_hat = X @ np.linalg.lstsq(X, q, rcond=None)[0]
u = q - q_hat  # orthogonal to 1 and x

print("u (projected quadratic):", np.round(u, 6).tolist())
print("1'u:", float(u.sum()))
print("x'u:", float(x @ u))

rows = []
for gamma in (0.0, 0.5, 1.0, 2.0):
    eps = gamma * (x - xbar) + u
    y = alpha + beta * x + eps
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    e = y - X @ b
    Xe = X.T @ e
    rows.append(
        dict(
            gamma=gamma,
            b0=float(b[0]),
            b1=float(b[1]),
            b1_minus_beta=float(b[1] - beta),
            Xe0=float(Xe[0]),
            Xe1=float(Xe[1]),
            e=np.round(e, 8).tolist(),
            e_equals_u=bool(np.allclose(e, u)),
        )
    )

# Would a quadratic residual-vs-x be the textbook misspec picture?
# Fit e on [1, x, x^2] — R^2 should be 1 if e is exactly a quadratic in x.
e0 = np.array(rows[0]["e"])
X2 = np.column_stack([np.ones_like(x), x, x**2])
fit2 = np.linalg.lstsq(X2, e0, rcond=None)[0]
e0_hat = X2 @ fit2
r2_quad = 1 - np.sum((e0 - e0_hat) ** 2) / np.sum((e0 - e0.mean()) ** 2)

print("quadratic_R2_of_residuals:", float(r2_quad))
print("quadratic_coefs:", [float(v) for v in fit2])
print("e identical across gamma:", all(r["e"] == rows[0]["e"] for r in rows))
print("b1 - beta == gamma for all:", all(abs(r["b1_minus_beta"] - r["gamma"]) < 1e-10 for r in rows))
print("X'e ~ 0 for all:", all(abs(r["Xe0"]) < 1e-10 and abs(r["Xe1"]) < 1e-10 for r in rows))
for r in rows:
    print(
        f"gamma={r['gamma']} b1={r['b1']:.6f} b1-beta={r['b1_minus_beta']:.6f} "
        f"Xe=({r['Xe0']:.2e},{r['Xe1']:.2e}) e=u={r['e_equals_u']}"
    )
print("e at gamma=0:", rows[0]["e"])
