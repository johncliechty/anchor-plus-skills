"""Per-pillar off-switch flags + the named hybrid-state matrix (rearch W3).

The re-architecture (frozen plan: ``IMPLEMENTATION-PLAN.md``, W3 — Spikes,
Pillar Flags & Process Rails) advances four pillars that each land behind an
OFF-SWITCH so any one pillar can be reverted WITHOUT reverting later waves:

======================  =====================  ======================  =========
pillar                  env var                values                  default
======================  =====================  ======================  =========
``frontend``            ``ANCHOR_FRONTEND``    ``embedded | static``   embedded
``auth``                ``ANCHOR_AUTH_MODE``   ``open | warn |         open
                                               enforce``
``journal``             ``ANCHOR_JOURNAL``     ``off | on``            off
``supervisor``          ``ANCHOR_SUPERVISOR``  ``inline | external``   inline
======================  =====================  ======================  =========

Every default is TODAY'S live behavior, so a host with none of the env vars
set is in the ``baseline`` state — the flags are rails laid ahead of the
pillars (W4+ consume ``frontend``, W8/W9 ``auth``, W12 ``journal``, W15/W16
``supervisor``). ``ANCHOR_AUTH_WARN=1`` is accepted as a compatibility alias
for ``ANCHOR_AUTH_MODE=warn`` (the W8 soak flag) when ``ANCHOR_AUTH_MODE`` is
unset.

A flag COMBINATION is supported iff it is a NAMED row of
:data:`HYBRID_STATE_MATRIX`. :func:`assert_named_state` (wired into the daily
healthcheck as ``check_pillar_state``) passes only on a named row and raises
:class:`PillarStateError` LOUDLY on an invalid flag value or an unnamed
combination — a live service can never silently run an unsupported hybrid.

The cross-pillar dependency DAG (:data:`DAG_EDGES`) and the
revert-compatibility rule (:data:`REVERT_RULE`) are the reasoned skeleton the
matrix rows must satisfy; :func:`write_matrix_doc` renders the whole thing to
the checked-in gate artifact ``planning/rearch-2026-07/PILLAR-DAG.md``
(refreshed mechanically by the W3 gate, like the W1 census artifacts). The
matrix here was the W3 initial set; it is FINALIZED in W18
(:data:`MATRIX_FINALIZED`) — every named flag combination carries a one-line
support statement, and :func:`assert_matrix_finalized` holds that invariant.

Stdlib only (``os``, ``pathlib``).
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent
DEFAULT_ARTIFACT_DIR = REPO_ROOT / "planning" / "rearch-2026-07"
MATRIX_DOC_NAME = "PILLAR-DAG.md"

# ── the four pillar flags ─────────────────────────────────────────────────────

FLAG_FRONTEND = "frontend"
FLAG_AUTH = "auth"
FLAG_JOURNAL = "journal"
FLAG_SUPERVISOR = "supervisor"

FLAG_ORDER = (FLAG_FRONTEND, FLAG_AUTH, FLAG_JOURNAL, FLAG_SUPERVISOR)

FLAG_ENV = {
    FLAG_FRONTEND: "ANCHOR_FRONTEND",
    FLAG_AUTH: "ANCHOR_AUTH_MODE",
    FLAG_JOURNAL: "ANCHOR_JOURNAL",
    FLAG_SUPERVISOR: "ANCHOR_SUPERVISOR",
}

FLAG_VALUES = {
    FLAG_FRONTEND: ("embedded", "static"),
    FLAG_AUTH: ("open", "warn", "enforce"),
    FLAG_JOURNAL: ("off", "on"),
    FLAG_SUPERVISOR: ("inline", "external"),
}

#: Every default is the PRE-MIGRATION behavior — an env with no flags set is
#: exactly today's live configuration (the ``baseline`` named state).
FLAG_DEFAULTS = {
    FLAG_FRONTEND: "embedded",
    FLAG_AUTH: "open",
    FLAG_JOURNAL: "off",
    FLAG_SUPERVISOR: "inline",
}

#: W8's log-only soak flag, honored as an alias when ANCHOR_AUTH_MODE is unset.
AUTH_WARN_ALIAS_ENV = "ANCHOR_AUTH_WARN"


class PillarStateError(RuntimeError):
    """An invalid pillar-flag value or an UNNAMED flag combination.

    Raised LOUDLY (never warned past): a live service must only ever run a
    combination that is a named row of the hybrid-state matrix.
    """


def current_flags(env=None) -> dict:
    """Resolve the four pillar flags from ``env`` (default ``os.environ``).

    Returns ``{flag: value}`` for all four pillars. Raises
    :class:`PillarStateError` on a value outside the flag's declared set —
    a typo'd flag must fail the configuration assertion, never silently fall
    back to a default.
    """
    e = os.environ if env is None else env
    flags = {}
    for flag in FLAG_ORDER:
        raw = (e.get(FLAG_ENV[flag]) or "").strip().lower()
        if not raw and flag == FLAG_AUTH:
            alias = (e.get(AUTH_WARN_ALIAS_ENV) or "").strip().lower()
            if alias in ("1", "true", "yes", "on"):
                raw = "warn"
        if not raw:
            flags[flag] = FLAG_DEFAULTS[flag]
            continue
        if raw not in FLAG_VALUES[flag]:
            raise PillarStateError(
                f"pillar flag '{flag}' ({FLAG_ENV[flag]}) has invalid value "
                f"{raw!r} — supported: {', '.join(FLAG_VALUES[flag])}"
            )
        flags[flag] = raw
    return flags


# ── cross-pillar dependency DAG + revert-compatibility rule ──────────────────

#: Each edge: ((flag, value), (required_flag, required_value), reason).
#: The four pillars are otherwise INDEPENDENT — journal emission and the
#: supervisor seam have no cross-pillar hard edges by design (D1/D2).
DAG_EDGES = (
    (
        (FLAG_AUTH, "enforce"),
        (FLAG_FRONTEND, "static"),
        "cookie-based browser navigation (W9) ships in the static frontend "
        "assets; enforcing the gated data plane against the pre-W4 embedded "
        "client would lock the browser out of page navigation",
    ),
)

REVERT_RULE = (
    "Revert-compatibility rule: every pillar reverts by FLAG ONLY — flipping "
    "a pillar's off-switch back never requires reverting a later wave's code. "
    "From each ladder state, every single-pillar revert lands in a named row "
    "of the matrix; where the DAG forbids a single-flag revert (frontend back "
    "to embedded while auth=enforce), the documented COMPOUND revert (auth to "
    "warn together with frontend to embedded) is the supported path and its "
    "landing state is likewise named. Revert states are transitional: their "
    "supported exits go back UP the ladder, not further down."
)


def dag_violations(flags) -> list:
    """The DAG edges ``flags`` violates (empty when the combination is legal)."""
    out = []
    for (flag, value), (req_flag, req_value), reason in DAG_EDGES:
        if flags.get(flag) == value and flags.get(req_flag) != req_value:
            out.append(
                f"{flag}={value} requires {req_flag}={req_value} — {reason}")
    return out


# ── the named hybrid-state matrix ─────────────────────────────────────────────

def _row(name, frontend, auth, journal, supervisor, support):
    return {
        "name": name,
        "flags": {
            FLAG_FRONTEND: frontend,
            FLAG_AUTH: auth,
            FLAG_JOURNAL: journal,
            FLAG_SUPERVISOR: supervisor,
        },
        "support": support,
    }


#: The NAMED (= supported) hybrid states. Six LADDER states (the deployment
#: sequence W4→W16 walks) + six REVERT states (the landing points the
#: revert-compatibility rule guarantees from the ladder). Any combination not
#: in this matrix is UNSUPPORTED and fails :func:`assert_named_state` loudly.
HYBRID_STATE_MATRIX = (
    # ── the ladder ──
    _row("baseline", "embedded", "open", "off", "inline",
         "Today's live configuration — every pillar at its pre-migration "
         "position; the state the effort starts from and can always return "
         "to."),
    _row("c1-static", "static", "open", "off", "inline",
         "After the W4–W6 extraction: the frontend serves from static files; "
         "auth, journal, and supervisor unchanged."),
    _row("c2-warn-soak", "static", "warn", "off", "inline",
         "The W8 soak: the gated data plane LOGS would-401 consumers without "
         "blocking anything."),
    _row("c2-enforced", "static", "enforce", "off", "inline",
         "After the W9 cutover: the data plane enforces tokens; cookie "
         "navigation carries the browser."),
    _row("c3-journaled", "static", "enforce", "on", "inline",
         "After W12–W14: journal dual-write on. Also the supervisor-revert "
         "landing state from c4-supervised."),
    _row("c4-supervised", "static", "enforce", "on", "external",
         "The target production state (W16+): all four pillars advanced."),
    # ── the revert states ──
    _row("embedded-warn-soak", "embedded", "warn", "off", "inline",
         "Frontend reverted during (or compound-reverted into) the auth "
         "soak: warn mode is observe-only, so the embedded client is "
         "supported."),
    _row("journaled-auth-reverted", "static", "warn", "on", "inline",
         "Auth reverted to warn after the journal landed (single-flag revert "
         "from c3-journaled)."),
    _row("journaled-frontend-reverted", "embedded", "warn", "on", "inline",
         "Compound frontend revert from c3-journaled (auth drops to warn "
         "with it, per the DAG)."),
    _row("supervised-journal-reverted", "static", "enforce", "off", "external",
         "Journal emission switched off under the external supervisor "
         "(single-flag revert from c4-supervised)."),
    _row("supervised-auth-reverted", "static", "warn", "on", "external",
         "Auth reverted to warn in the full production stack (single-flag "
         "revert from c4-supervised)."),
    _row("supervised-frontend-reverted", "embedded", "warn", "on", "external",
         "Compound frontend revert from c4-supervised (auth drops to warn "
         "with it, per the DAG)."),
)

#: The deployment-ladder subset, in order (used by docs + the closure test).
LADDER_STATES = ("baseline", "c1-static", "c2-warn-soak", "c2-enforced",
                 "c3-journaled", "c4-supervised")

#: rearch W18: the matrix is FINALIZED — no further named states are added by
#: the closure; every combination carries its one-line support statement. The
#: PTY-adoption follow-on (ConPTY verdict YES) names its degraded-mode state
#: within its own scheduled wave, not here (CONPTY-VERDICT-APPLICATION.md).
MATRIX_FINALIZED = True


def assert_matrix_finalized():
    """Assert the finalized-matrix invariant (rearch W18 closure).

    Every named row carries a non-empty one-line support statement, the six
    ladder states are all present, and the state names are unique. Raises
    :class:`PillarStateError` loudly on any violation. Returns the matrix.
    """
    names = [r["name"] for r in HYBRID_STATE_MATRIX]
    if len(names) != len(set(names)):
        raise PillarStateError("matrix state names are not unique")
    for row in HYBRID_STATE_MATRIX:
        support = (row.get("support") or "").strip()
        if not support:
            raise PillarStateError(
                f"named state {row['name']!r} has no support statement")
        if dag_violations(row["flags"]):
            raise PillarStateError(
                f"named state {row['name']!r} violates the DAG")
    for name in LADDER_STATES:
        if get_state(name) is None:
            raise PillarStateError(f"ladder state {name!r} missing from matrix")
    return HYBRID_STATE_MATRIX


def state_name(flags):
    """The matrix name for ``flags`` (exact match), or ``None`` when unnamed."""
    for row in HYBRID_STATE_MATRIX:
        if row["flags"] == flags:
            return row["name"]
    return None


def get_state(name):
    """The matrix row for ``name``, or ``None``."""
    for row in HYBRID_STATE_MATRIX:
        if row["name"] == name:
            return row
    return None


def _flags_str(flags):
    return " · ".join(f"{f}={flags[f]}" for f in FLAG_ORDER)


def assert_named_state(env=None) -> dict:
    """Assert the CURRENT flag combination is a named hybrid state.

    Returns the matching matrix row ``{"name", "flags", "support"}``. Raises
    :class:`PillarStateError` loudly on (a) an invalid flag value, or (b) a
    combination that matches no named row — including one the DAG forbids.
    This is the healthcheck's configuration assertion (``check_pillar_state``).
    """
    flags = current_flags(env=env)          # raises on an invalid value
    name = state_name(flags)
    if name is None:
        violations = dag_violations(flags)
        why = ("; DAG violation: " + "; ".join(violations)) if violations \
            else "; the combination is not a named row of the matrix"
        raise PillarStateError(
            f"UNNAMED hybrid state: {_flags_str(flags)}{why}. Supported "
            f"states: {', '.join(r['name'] for r in HYBRID_STATE_MATRIX)}."
        )
    row = get_state(name)
    return {"name": name, "flags": dict(flags), "support": row["support"]}


# ── the checked-in matrix/DAG doc (gate artifact) ─────────────────────────────

def render_matrix_md() -> str:
    """Render the pillar flags + DAG + named matrix as the checked-in doc."""
    lines = [
        "# Pillar flags — cross-pillar dependency DAG + named hybrid-state "
        "matrix (W3)",
        "",
        "Generated by `pillar_flags.write_matrix_doc()` — refreshed "
        "mechanically by the W3 gate, never hand-edited. The module "
        "`pillar_flags.py` is the single source of truth; this doc is its "
        "reviewable rendering. FINALIZED in W18 — every named row carries a "
        "one-line support statement (`assert_matrix_finalized`).",
        "",
        "## The four per-pillar off-switch flags",
        "",
        "| pillar | env var | values | default (today's live behavior) |",
        "|---|---|---|---|",
    ]
    for flag in FLAG_ORDER:
        values = " \\| ".join(FLAG_VALUES[flag])
        lines.append(
            f"| {flag} | `{FLAG_ENV[flag]}` | "
            f"{values} | {FLAG_DEFAULTS[flag]} |")
    lines += [
        "",
        f"`{AUTH_WARN_ALIAS_ENV}=1` is accepted as an alias for "
        f"`ANCHOR_AUTH_MODE=warn` when the mode var is unset (the W8 soak "
        f"flag).",
        "",
        "## Cross-pillar dependency DAG",
        "",
        "The four pillars are independent EXCEPT for the edges below "
        "(journal emission and the supervisor seam deliberately have no "
        "cross-pillar hard edges — D1/D2):",
        "",
    ]
    for (flag, value), (req_flag, req_value), reason in DAG_EDGES:
        lines.append(f"- **{flag}={value} → requires {req_flag}={req_value}** "
                     f"— {reason}.")
    lines += [
        "",
        f"> {REVERT_RULE}",
        "",
        "## Named hybrid-state matrix (supported combinations)",
        "",
        "The healthcheck's configuration assertion (`check_pillar_state` → "
        "`pillar_flags.assert_named_state`) passes ONLY on a named row and "
        "fails loudly on an unnamed state.",
        "",
        "| state | frontend | auth | journal | supervisor | support |",
        "|---|---|---|---|---|---|",
    ]
    for row in HYBRID_STATE_MATRIX:
        f = row["flags"]
        ladder = " (ladder)" if row["name"] in LADDER_STATES else ""
        lines.append(
            f"| **{row['name']}**{ladder} | {f[FLAG_FRONTEND]} | "
            f"{f[FLAG_AUTH]} | {f[FLAG_JOURNAL]} | {f[FLAG_SUPERVISOR]} | "
            f"{row['support']} |")
    lines.append("")
    return "\n".join(lines)


def write_matrix_doc(out_dir=None) -> Path:
    """Write ``PILLAR-DAG.md`` (skipping an unchanged rewrite); return the path."""
    out = Path(out_dir) if out_dir is not None else DEFAULT_ARTIFACT_DIR
    out.mkdir(parents=True, exist_ok=True)
    path = out / MATRIX_DOC_NAME
    text = render_matrix_md()
    try:
        if path.exists() and path.read_text(encoding="utf-8") == text:
            return path
    except OSError:
        pass
    path.write_text(text, encoding="utf-8")
    return path


def main(argv=None):  # pragma: no cover - thin CLI shim
    """CLI: print the current named state, or fail loudly on an unnamed one."""
    import json as _json
    import sys as _sys

    argv = list(_sys.argv[1:] if argv is None else argv)
    if "--write-doc" in argv:
        print(f"wrote {write_matrix_doc()}")
        return 0
    try:
        row = assert_named_state()
    except PillarStateError as e:
        print(f"UNSUPPORTED PILLAR STATE: {e}", file=_sys.stderr)
        return 1
    print(_json.dumps(row, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    import sys

    sys.exit(main())
