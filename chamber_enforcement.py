"""Steward-chamber W3 enforcement infrastructure (Phase-0, steward-chamber plan).

This module is the OWNER FILE for ``chamber/routes-inventory.json`` (the
BOTH-TREE living routes inventory) and ships the acceptance infrastructure
every later chamber surface depends on:

* the **scripted-login auth fixture** — a real authenticated session minted
  through the server's own ``POST /api/auth/login`` (token → HttpOnly cookie),
  never a header spoof (``scripted_login`` / ``AuthedSession``);
* the **F6 assertion set** for state-changing surfaces — token required,
  POST-only, CSRF-class forged-request refusal — with the threat model SPLIT
  by caller class (browser vs bridge/CLI; the bridge/CLI class is asserted
  NON-exempt: a forged non-browser caller cannot skip the token check);
* the **living routes inventory** loaders + the CI **diff guard** that fails
  when a state-changing route or bridge verb exists in code without an
  inventory row (or an inventory row goes stale) — both trees, both
  directions (``diff_inventory_vs_code``);
* the **auth-ON coverage rule** — a mechanical scanner failing any
  new-surface test file that is not tagged for its auth posture
  (``scan_new_surface_tests``).

Anchor's law: stdlib only. HTTP probes ride ``http.client`` on loopback; the
Ecgberht sibling is resolved via the ``ECGBERHT_ROOT`` env else the sibling
checkout beside this tree — never an absolute host path.

Why this exists (the plan's words): the chamber shipped broken TWICE with
auth off, because virtually every test ran tokenless. The F6 set is designed
to be provably RED on an auth-off server (each assertion FAILS when the route
is reachable without a token) and green auth-on — see
``tests/test_chamber_red_to_green_w3.py``.
"""

from __future__ import annotations

import http.client
import json
import os
import re
from pathlib import Path

SCHEMA_VERSION = 1

ANCHOR_ROOT = Path(__file__).resolve().parent
CHAMBER_DIR = ANCHOR_ROOT / "chamber"
ROUTES_INVENTORY_PATH = CHAMBER_DIR / "routes-inventory.json"

# ── Caller classes (the F6 threat-model split, recorded in the artifact) ─────
CALLER_CLASS_BROWSER = "browser"
CALLER_CLASS_BRIDGE_CLI = "bridge-cli"

#: The marker key a dispatch-shim server answers with once a POST has PASSED
#: the auth middleware (see tests/chamber_harness.py). The F6 probes use it to
#: distinguish "auth admitted the request" from "auth refused it" WITHOUT ever
#: executing a real mutating handler.
DISPATCH_MARKER_KEY = "chamber_w3_dispatch_marker"

#: New-surface test namespace (the auth-ON coverage rule's scope). Declared
#: here AND in the inventory artifact; every chamber-build wave (W6-W11) lands
#: its surface tests under this glob so the rule binds them mechanically.
NEW_SURFACE_TEST_GLOB = "test_chamber_*.py"

#: The sanctioned auth-posture tags. A new-surface test file must carry
#: exactly one, in its header (first ~4000 chars — docstring territory):
#:   ``AUTH-ON: enforced``      — the file exercises HTTP surfaces and runs
#:                                them with ANCHOR_TOKEN set (a real session);
#:   ``AUTH-ON: not-a-surface`` — the file exercises no HTTP surface at all
#:                                (pure module/artifact tests) and must not
#:                                boot or probe a server.
AUTH_TAG_RE = re.compile(r"AUTH-ON:\s*(enforced|not-a-surface)")

#: Tokens whose presence marks a file as touching the HTTP surface. Used to
#: keep the ``not-a-surface`` tag honest (a tagged-out file that boots a
#: server is a violation).
_SURFACE_TOKENS = ("make_server", "HTTPConnection", "http.client",
                   "serve_forever", "boot_server", "scripted_login")


# ═════════════════════════════════════════════════════════════════════════════
# Sibling resolution (same law as scripts/run-all-tests.mjs + wire-homing.json)
# ═════════════════════════════════════════════════════════════════════════════

def ecgberht_root() -> Path:
    """The Ecgberht engine root: ``ECGBERHT_ROOT`` env override, else the
    sibling checkout beside this Anchor tree. Never a host-absolute literal."""
    env = os.environ.get("ECGBERHT_ROOT", "").strip()
    if env:
        return Path(env)
    return ANCHOR_ROOT.parent / "Ecgberht"


# ═════════════════════════════════════════════════════════════════════════════
# Inventory: load / validate
# ═════════════════════════════════════════════════════════════════════════════

def load_routes_inventory(path: Path | None = None) -> dict:
    """Load the living routes inventory artifact (raises on missing file)."""
    p = Path(path) if path else ROUTES_INVENTORY_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def validate_routes_inventory(inv: dict) -> list:
    """Structural validation. Returns a list of problem strings (empty == ok).

    The living-registry law (plan): versioned machine-readable data with a
    schema_version and a NAMED owner file, carrying the caller-class threat
    split, plus one row per state-changing Anchor route and per Ecgberht
    bridge verb.
    """
    problems = []
    if not isinstance(inv, dict):
        return ["inventory is not a JSON object"]
    if inv.get("schema_version") != SCHEMA_VERSION:
        problems.append("schema_version missing or != %d" % SCHEMA_VERSION)
    if not inv.get("owner_file"):
        problems.append("owner_file missing (living-registry law)")
    tm = inv.get("threat_model")
    if not isinstance(tm, dict):
        problems.append("threat_model missing (caller-class split, F6)")
    else:
        for cls in (CALLER_CLASS_BROWSER, CALLER_CLASS_BRIDGE_CLI):
            if cls not in tm:
                problems.append("threat_model missing caller class %r" % cls)
    if not isinstance(inv.get("coverage_rule"), dict):
        problems.append("coverage_rule missing (auth-ON tag rule record)")

    rows = inv.get("anchor_routes")
    if not isinstance(rows, list) or not rows:
        problems.append("anchor_routes missing/empty")
    else:
        for i, row in enumerate(rows):
            for key in ("method", "pattern", "match", "auth"):
                if not row.get(key):
                    problems.append("anchor_routes[%d] missing %r" % (i, key))
            if row.get("method") == "POST" and row.get("auth") == "open":
                # An open mutator would be a reviewed-allowlist event; the
                # inventory refuses to carry one silently.
                problems.append(
                    "anchor_routes[%d] (%s) declares an OPEN mutator — "
                    "requires explicit review, not an inventory row"
                    % (i, row.get("pattern")))

    bridges = inv.get("ecgberht_bridges")
    if not isinstance(bridges, dict):
        problems.append("ecgberht_bridges missing")
    else:
        for name in ("seal-chamber-bridge", "commission-run-bridge"):
            b = bridges.get(name)
            if not isinstance(b, dict) or not isinstance(b.get("verbs"), list):
                problems.append("ecgberht_bridges[%r] missing verbs" % name)
                continue
            for j, verb in enumerate(b["verbs"]):
                for key in ("verb", "symbol", "caller_class"):
                    if not verb.get(key):
                        problems.append(
                            "ecgberht_bridges[%r].verbs[%d] missing %r"
                            % (name, j, key))
                if verb.get("caller_class") != CALLER_CLASS_BRIDGE_CLI:
                    problems.append(
                        "ecgberht_bridges[%r].verbs[%d] (%s): bridge verbs "
                        "are the bridge-cli caller class by definition"
                        % (name, j, verb.get("verb")))
                if "state_changing" not in verb:
                    problems.append(
                        "ecgberht_bridges[%r].verbs[%d] (%s) missing "
                        "state_changing flag" % (name, j, verb.get("verb")))
    return problems


# ═════════════════════════════════════════════════════════════════════════════
# Code truth: Anchor route table + Ecgberht bridge sources
# ═════════════════════════════════════════════════════════════════════════════

def anchor_state_changing_routes() -> list:
    """Every state-changing (POST) route Anchor serves, from the declarative
    route table (the single source of truth for the HTTP surface)."""
    import route_table
    rows = []
    for r in route_table.ROUTES:
        if r.method == "POST":
            rows.append({
                "method": r.method,
                "pattern": r.pattern,
                "match": r.match,
                "auth": r.auth,
                "handler": r.handler,
                "migrated": bool(r.migrated),
            })
    return rows


_SEAL_VERB_RE = re.compile(
    r"export\s+(?:async\s+)?function\s+(build(\w+)Payload)")
_COMMISSION_MODES_RE = re.compile(
    r"BRIDGE_MODES\s*=\s*Object\.freeze\(\s*\[([^\]]*)\]")


def _kebab(camel: str) -> str:
    return re.sub(r"(?<!^)(?=[A-Z])", "-", camel).lower()


def scan_seal_chamber_verbs(root: Path | None = None) -> list:
    """The seal-chamber bridge's verb surface, scanned from source: one verb
    per exported ``build<Verb>Payload`` builder. Returns
    ``[{verb, symbol}, ...]`` sorted by verb. Raises if the bridge is absent
    (the both-tree contract requires the sibling)."""
    root = root or ecgberht_root()
    src = (root / "scripts" / "seal-chamber-bridge.mjs").read_text(
        encoding="utf-8", errors="replace")
    out = []
    for symbol, camel in _SEAL_VERB_RE.findall(src):
        out.append({"verb": _kebab(camel), "symbol": symbol})
    return sorted(out, key=lambda v: v["verb"])


def scan_commission_bridge_modes(root: Path | None = None) -> list:
    """The commission-run bridge's frozen mode list, scanned from source."""
    root = root or ecgberht_root()
    src = (root / "scripts" / "commission-run-bridge.mjs").read_text(
        encoding="utf-8", errors="replace")
    m = _COMMISSION_MODES_RE.search(src)
    if not m:
        raise AssertionError(
            "commission-run-bridge.mjs: BRIDGE_MODES freeze list not found "
            "(the diff guard's scan anchor moved — update the inventory "
            "owner module)")
    pairs = re.findall(r"'([^']+)'|\"([^\"]+)\"", m.group(1))
    return sorted(a or b for a, b in pairs)


def diff_inventory_vs_code(inv: dict | None = None,
                           root: Path | None = None) -> dict:
    """The living-registry CI diff guard, both trees and BOTH directions.

    Returns a dict of four lists (all empty == green):
      * ``routes_missing_from_inventory`` — a POST route exists in
        ``route_table`` with no inventory row (a new mutator merged without
        its row: the guard the plan demands);
      * ``routes_stale_in_inventory``     — an inventory row's route no longer
        exists in code (living registry, never a Phase-0 snapshot);
      * ``verbs_missing_from_inventory``  — a bridge verb/mode exists in the
        Ecgberht source without an inventory row;
      * ``verbs_stale_in_inventory``      — an inventory verb row's symbol/mode
        vanished from the bridge source.
    """
    inv = inv if inv is not None else load_routes_inventory()
    code_routes = {(r["method"], r["pattern"])
                   for r in anchor_state_changing_routes()}
    inv_routes = {(row.get("method"), row.get("pattern"))
                  for row in inv.get("anchor_routes", [])}

    seal_code = {v["verb"] for v in scan_seal_chamber_verbs(root)}
    comm_code = set(scan_commission_bridge_modes(root))
    bridges = inv.get("ecgberht_bridges", {})
    seal_inv = {v.get("verb") for v in
                bridges.get("seal-chamber-bridge", {}).get("verbs", [])}
    comm_inv = {v.get("verb") for v in
                bridges.get("commission-run-bridge", {}).get("verbs", [])}

    return {
        "routes_missing_from_inventory": sorted(
            "%s %s" % rp for rp in code_routes - inv_routes),
        "routes_stale_in_inventory": sorted(
            "%s %s" % rp for rp in inv_routes - code_routes),
        "verbs_missing_from_inventory": sorted(
            ["seal-chamber-bridge:%s" % v for v in seal_code - seal_inv] +
            ["commission-run-bridge:%s" % v for v in comm_code - comm_inv]),
        "verbs_stale_in_inventory": sorted(
            ["seal-chamber-bridge:%s" % v for v in seal_inv - seal_code] +
            ["commission-run-bridge:%s" % v for v in comm_inv - comm_code]),
    }


def diff_guard_problems(inv: dict | None = None,
                        root: Path | None = None) -> list:
    """Flatten :func:`diff_inventory_vs_code` into failure strings."""
    diff = diff_inventory_vs_code(inv, root)
    problems = []
    for kind, items in sorted(diff.items()):
        for item in items:
            problems.append("%s: %s" % (kind, item))
    return problems


# ═════════════════════════════════════════════════════════════════════════════
# Auth-ON coverage rule (new-surface tests must declare their auth posture)
# ═════════════════════════════════════════════════════════════════════════════

def scan_new_surface_tests(tests_dir: Path | None = None) -> list:
    """Scan the new-surface test namespace for auth-ON tag violations.

    Returns ``[{file, problem}, ...]`` (empty == green). Mechanically:

    * every ``tests/test_chamber_*.py`` file MUST carry an ``AUTH-ON:`` tag
      (``enforced`` | ``not-a-surface``) in its header;
    * an ``enforced`` file must actually reference the auth-ON machinery
      (``ANCHOR_TOKEN`` or the chamber harness) — the tag cannot be a label
      over a tokenless test;
    * a ``not-a-surface`` file must NOT touch the HTTP surface at all.
    """
    tests_dir = Path(tests_dir) if tests_dir else ANCHOR_ROOT / "tests"
    violations = []
    for f in sorted(tests_dir.glob(NEW_SURFACE_TEST_GLOB)):
        text = f.read_text(encoding="utf-8", errors="replace")
        m = AUTH_TAG_RE.search(text[:4000])
        if not m:
            violations.append({
                "file": f.name,
                "problem": "new-surface test lacks the AUTH-ON tag "
                           "(AUTH-ON: enforced | AUTH-ON: not-a-surface)"})
            continue
        posture = m.group(1)
        if posture == "enforced":
            if ("ANCHOR_TOKEN" not in text and "chamber_harness" not in text):
                violations.append({
                    "file": f.name,
                    "problem": "tagged AUTH-ON: enforced but never references "
                               "ANCHOR_TOKEN or the chamber harness — the tag "
                               "is a label over a tokenless test"})
        else:  # not-a-surface
            hits = [tok for tok in _SURFACE_TOKENS if tok in text]
            if hits:
                violations.append({
                    "file": f.name,
                    "problem": "tagged AUTH-ON: not-a-surface but touches the "
                               "HTTP surface (%s)" % ", ".join(sorted(hits))})
    return violations


# ═════════════════════════════════════════════════════════════════════════════
# The successor-hydrate abort ban (chamber-m1 W1)
# ═════════════════════════════════════════════════════════════════════════════

#: Routes whose page-side settle is part of what a chamber PAINT test proves.
#: For twelve waves ``tests/test_chamber_first_paint_w6.py`` aborted the
#: chamber hydrate route in the browser — and that abort is exactly how the
#: mount's post-hydrate ``_ecgSealDropSlice()`` defect stayed green while the
#: painted M1 surface was being deleted on every real open. A paint test that
#: silences a successor-hydrate route is not testing the surface John sees.
HYDRATE_ROUTES = ("/api/ecgberht/chamber",)

#: Characters of context scanned after each browser route-interception
#: registration (generous enough for a multi-line handler lambda).
_ABORT_SCAN_WINDOW = 400


def scan_chamber_paint_aborts(tests_dir: Path | None = None) -> list:
    """The abort-ban CI rule (chamber-m1 W1). Returns ``[{file, problem}]``
    (empty == green).

    Mechanically: in every ``tests/test_chamber_*.py`` file, each browser
    route-interception registration (a ``.route(`` call — Playwright page or
    context) is scanned in a bounded window; a registration that targets a
    successor-hydrate route (:data:`HYDRATE_ROUTES`) AND aborts it fails BY
    NAME. Fulfil/continue interceptions and aborts of unrelated routes are
    not the defect and pass untouched.
    """
    tests_dir = Path(tests_dir) if tests_dir else ANCHOR_ROOT / "tests"
    # Needles assembled by concatenation (the same convention the auth-ON
    # coverage suite uses) so a scanned test file quoting this rule's DOCS
    # is never confused with a live interception in this module's own text.
    reg = "." + "route("
    kill = "abort"
    violations = []
    for f in sorted(tests_dir.glob(NEW_SURFACE_TEST_GLOB)):
        text = f.read_text(encoding="utf-8", errors="replace")
        start = 0
        while True:
            i = text.find(reg, start)
            if i < 0:
                break
            window = text[i:i + _ABORT_SCAN_WINDOW]
            hit = next((r for r in HYDRATE_ROUTES if r in window), None)
            if hit is not None and kill in window:
                violations.append({
                    "file": f.name,
                    "problem": "chamber paint test aborts the successor-"
                               "hydrate route %s — the abort that kept the "
                               "slice-delete defect green for twelve waves; "
                               "let the hydrate run and assert M1 survives "
                               "it" % hit})
                break  # one named violation per file is enough
            start = i + len(reg)
    return violations


# ═════════════════════════════════════════════════════════════════════════════
# HTTP probe plumbing (stdlib; loopback only)
# ═════════════════════════════════════════════════════════════════════════════

def _split_base(base: str):
    hostport = base.split("//", 1)[-1]
    host, _, port = hostport.partition(":")
    return host, int(port or 80)


def request(base: str, method: str, path: str, headers: dict | None = None,
            body: bytes | str | None = None, timeout: float = 30.0):
    """One HTTP request → ``(status, headers_dict, body_bytes)``."""
    host, port = _split_base(base)
    conn = http.client.HTTPConnection(host, port, timeout=timeout)
    try:
        payload = body.encode("utf-8") if isinstance(body, str) else body
        conn.request(method, path, body=payload, headers=headers or {})
        resp = conn.getresponse()
        data = resp.read()
        hdrs = {k.lower(): v for k, v in resp.getheaders()}
        return resp.status, hdrs, data
    finally:
        conn.close()


def probe_path_for_row(row: dict) -> str:
    """The concrete request path used to probe an inventory row (prefix rows
    get a deterministic probe suffix)."""
    pattern = row["pattern"]
    if row.get("match") == "prefix":
        return pattern.rstrip("/") + "/w3probe"
    return pattern


# ═════════════════════════════════════════════════════════════════════════════
# Scripted login → a REAL authenticated session (never a header spoof)
# ═════════════════════════════════════════════════════════════════════════════

class AuthedSession:
    """A real authenticated session against a running Anchor server.

    Minted by :func:`scripted_login` through the server's own
    ``POST /api/auth/login`` — the cookie in ``self.cookie`` came out of a
    ``Set-Cookie`` the server issued, exactly as a browser would hold it.
    """

    def __init__(self, base: str, token: str, cookie: str):
        self.base = base
        self.token = token
        self.cookie = cookie  # "anchor_auth=<token>" (name=value, no attrs)

    # Browser-shaped calls -----------------------------------------------
    def get(self, path: str, *, cookie_only: bool = True,
            extra_headers: dict | None = None):
        """GET as the browser does — the HttpOnly cookie authenticates."""
        headers = dict(extra_headers or {})
        if cookie_only:
            headers["Cookie"] = self.cookie
        return request(self.base, "GET", path, headers)

    def post(self, path: str, payload: dict | None = None,
             *, send_token_header: bool = True, send_cookie: bool = True,
             extra_headers: dict | None = None):
        """POST as the dashboard does — X-Anchor-Token header + cookie."""
        headers = {"Content-Type": "application/json"}
        headers.update(extra_headers or {})
        if send_token_header:
            headers["X-Anchor-Token"] = self.token
        if send_cookie:
            headers["Cookie"] = self.cookie
        return request(self.base, "POST", path,
                       headers, json.dumps(payload or {}))


def scripted_login(base: str, token: str) -> AuthedSession:
    """Perform the scripted login and return the real authenticated session.

    Walks the same path the browser walks: ``POST /api/auth/login`` carrying
    the shared-secret token → the server answers ``Set-Cookie`` with the
    HttpOnly auth cookie. Raises ``AssertionError`` (with the observed
    response) if the login is refused or no cookie is issued — a fixture that
    silently degrades to auth-off is exactly the failure mode W3 exists to
    kill.
    """
    status, headers, body = request(
        base, "POST", "/api/auth/login",
        {"Content-Type": "application/json", "X-Anchor-Token": token},
        json.dumps({"token": token}))
    if status != 200:
        raise AssertionError(
            "scripted login refused: POST /api/auth/login -> %d %r"
            % (status, body[:200]))
    set_cookie = headers.get("set-cookie", "")
    if "anchor_auth=" not in set_cookie:
        raise AssertionError(
            "scripted login issued no auth cookie (Set-Cookie: %r). With "
            "ANCHOR_TOKEN unset the server answers auth:disabled — the "
            "fixture requires a REAL auth-on session." % set_cookie)
    cookie_pair = set_cookie.split(";", 1)[0].strip()
    return AuthedSession(base, token, cookie_pair)


# ═════════════════════════════════════════════════════════════════════════════
# F6 assertion set (each leg raises AssertionError naming route + leg)
# ═════════════════════════════════════════════════════════════════════════════

def _fail(route_path: str, leg: str, detail: str):
    raise AssertionError("F6[%s] %s: %s" % (leg, route_path, detail))


def f6_assert_token_required(base: str, route_path: str):
    """Browser + bridge/CLI classes alike: a tokenless POST must be refused
    with 401 BEFORE any handler substance. On an auth-off server this leg
    FAILS (the request reaches dispatch) — that failure is the W3 red proof."""
    status, _, body = request(
        base, "POST", route_path,
        {"Content-Type": "application/json"}, "{}")
    if status != 401:
        _fail(route_path, "token-required",
              "tokenless POST answered %d (%r) — the route is reachable "
              "without a token" % (status, body[:120]))


def f6_assert_csrf_forged_refused(base: str, route_path: str,
                                  cookie: str | None = None):
    """Browser caller class: a CSRF-class forged cross-origin request must be
    refused. The forgery is browser-shaped: hostile Origin/Referer, a
    no-preflight content type, the victim's auth COOKIE riding along (the
    browser attaches cookies automatically; SameSite is a browser courtesy the
    server must not depend on) — and, being cross-site, NO token header. The
    server must 401: the explicit token header is the CSRF defense."""
    headers = {
        "Content-Type": "text/plain",
        "Origin": "https://forged.invalid",
        "Referer": "https://forged.invalid/attack.html",
    }
    if cookie:
        headers["Cookie"] = cookie
    status, _, body = request(base, "POST", route_path, headers, "{}")
    if status != 401:
        _fail(route_path, "csrf-forged-refused",
              "forged cross-origin POST (cookie-riding, no token header) "
              "answered %d (%r) — CSRF-class request was not refused"
              % (status, body[:120]))


def f6_assert_bridge_cli_not_exempt(base: str, route_path: str):
    """Bridge/CLI caller class: a NON-browser caller (no Origin/Referer — a
    curl, a bridge script, a forged agent) without a token must STILL be
    refused. Asserts the caller-class split has no exemption hole: auth is
    class-independent."""
    status, _, body = request(
        base, "POST", route_path,
        {"Content-Type": "application/json",
         "User-Agent": "anchor-bridge-cli-probe/1.0"}, "{}")
    if status != 401:
        _fail(route_path, "bridge-cli-not-exempt",
              "non-browser (bridge/CLI-class) tokenless POST answered %d "
              "(%r) — the non-browser class must NOT be exempt from auth"
              % (status, body[:120]))


def f6_assert_post_only(base: str, route_path: str,
                        marker_key: str = DISPATCH_MARKER_KEY):
    """The mutator must not be invocable via GET. On a dispatch-shim server a
    GET that reached the POST arm would answer the dispatch marker; any
    response is acceptable EXCEPT the marker (a GET twin may legitimately
    serve a read surface at the same path)."""
    status, _, body = request(base, "GET", route_path, {})
    if marker_key.encode("ascii") in body:
        _fail(route_path, "post-only",
              "GET reached the POST dispatch arm (status %d)" % status)


def f6_assert_token_admits(base: str, route_path: str, token: str,
                           marker_key: str = DISPATCH_MARKER_KEY):
    """The 401 must be the token's doing, not a blanket deny: the same POST
    WITH the token must pass the auth middleware. Requires the dispatch-shim
    server (the marker proves auth admitted the request; no real handler
    runs)."""
    status, _, body = request(
        base, "POST", route_path,
        {"Content-Type": "application/json", "X-Anchor-Token": token}, "{}")
    if status != 200 or marker_key.encode("ascii") not in body:
        _fail(route_path, "token-admits",
              "tokened POST did not reach dispatch (status %d, %r) — the "
              "refusal legs may be a blanket deny" % (status, body[:120]))


def f6_route_green(base: str, route_row: dict, token: str,
                   cookie: str | None = None,
                   marker_key: str = DISPATCH_MARKER_KEY,
                   check_admit: bool = True):
    """The full F6 set for one inventory row against an auth-ON server."""
    path = probe_path_for_row(route_row)
    f6_assert_token_required(base, path)
    f6_assert_csrf_forged_refused(base, path, cookie)
    f6_assert_bridge_cli_not_exempt(base, path)
    f6_assert_post_only(base, path, marker_key)
    if check_admit:
        f6_assert_token_admits(base, path, token, marker_key)
