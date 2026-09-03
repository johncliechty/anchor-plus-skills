"""Doctor, in plain words (John, 2026-09-03: "these descriptions should follow
the elegance rule and be easier to understand … there should also be a resolve
all button").

Pure, stdlib-only. Turns the health report's raw issue lines into a title, one
sentence of meaning, and a hint — the raw text stays available behind a
disclosure, never lost. Also decides what "Resolve all" should DO for a set of
issues, given a live re-probe of the endpoints the issues name:

* every issue is the self-test's own throwaway copy failing to answer AND the
  live server answers every endpoint the issues name → ``rerun``: nothing is
  wrong with Anchor; re-run the health check so the report (and the banner)
  say so;
* otherwise → ``session``: one doctor session seeded with ALL the issues.

Nothing here runs a model or touches the network; the caller probes.
"""
from __future__ import annotations

import re

KIND_SELF_TEST_UNREACHABLE = "self-test-unreachable"
KIND_CHECKS_FAILED = "checks-failed"
KIND_OTHER = "other"

_UNREACHABLE = re.compile(
    r"actively refused|timed out|transport error|WinError 10061|Connection refused",
    re.I)
_PASSED = re.compile(r"(\d+)\s*/\s*(\d+)\s+passed")
_FAILED_N = re.compile(r"(\d+)\s+failed")
_GET_PATH = re.compile(r"\bGET\s+(/[^\s:;,>]*)")
_METHOD_PATH = re.compile(r"\b(GET|POST|PUT|DELETE)\s+(/[^\s:;,>]*)")


def _first_failure(detail):
    """The first named failure in 'failures: A; B; C' — or ''."""
    m = re.search(r"failures?:\s*(.+)$", detail or "", re.I)
    if not m:
        return ""
    first = re.split(r";\s*", m.group(1).strip(), maxsplit=1)[0]
    first = re.sub(r"<urlopen error ([^>]*)>", r"\1", first)
    return first.strip()[:160]


def explain(issue, autofixes=()):
    """One raw issue row ``{component, detail}`` → plain words.

    ``autofixes`` — the report's "Auto-fixes applied" lines (e.g. "test port
    8778 busy; ran on free port 59984 instead"), which tell us the self-test
    was talking to its own throwaway copy, not the live server.
    """
    comp = str((issue or {}).get("component") or "health").strip()
    detail = str((issue or {}).get("detail") or "").strip()
    raw = "[%s] %s" % (comp, detail) if detail else "[%s]" % comp
    m = _PASSED.search(detail)
    passed, total = (int(m.group(1)), int(m.group(2))) if m else (None, None)
    nfail = None
    if passed is not None:
        nfail = total - passed
    else:
        mf = _FAILED_N.search(detail)
        if mf:
            nfail = int(mf.group(1))
    unreachable = bool(_UNREACHABLE.search(detail))
    endpointish = comp.lower().startswith("http") or "route" in comp.lower() \
        or "endpoint" in comp.lower()
    spare_port = any("free port" in str(a).lower() or "port" in str(a).lower()
                     for a in autofixes or ())

    if unreachable and endpointish:
        what = ("its throwaway test copy of Anchor" if spare_port
                else "the server it was testing")
        n = ("%d of %d" % (nfail, total) if total else
             ("%d" % nfail if nfail is not None else "some"))
        return {
            "kind": KIND_SELF_TEST_UNREACHABLE,
            "title": "The 5 AM self-test could not reach %s" % what,
            "meaning": ("%s: %s checks got no answer (connection refused or "
                        "timed out). %s"
                        % (comp, n,
                           "Your live Anchor was not the one being tested."
                           if spare_port else
                           "If Anchor answers now, this was a moment, not a fault.")),
            "hint": "Resolve all re-probes the live server now; if it answers, "
                    "the check is re-run so the banner clears.",
            "paths": sorted({p for _m, p in _METHOD_PATH.findall(detail)}),
            "raw": raw,
        }
    if nfail is not None and nfail > 0:
        first = _first_failure(detail)
        return {
            "kind": KIND_CHECKS_FAILED,
            "title": "%s: %s failed" % (
                comp, ("%d of %d checks" % (nfail, total)) if total else
                ("%d check%s" % (nfail, "" if nfail == 1 else "s"))),
            "meaning": ("First failure: %s" % first) if first else
                       "See the details for what failed.",
            "hint": "Resolve all opens one doctor session for every open issue.",
            "paths": sorted({p for _m, p in _METHOD_PATH.findall(detail)}),
            "raw": raw,
        }
    return {
        "kind": KIND_OTHER,
        "title": comp,
        "meaning": (detail[:157] + "…") if len(detail) > 160 else (detail or "(no detail)"),
        "hint": "",
        "paths": sorted({p for _m, p in _METHOD_PATH.findall(detail)}),
        "raw": raw,
    }


def explain_all(issues, autofixes=()):
    out = []
    for it in issues or ():
        try:
            out.append(explain(it, autofixes))
        except Exception:
            out.append({"kind": KIND_OTHER, "title": "health issue",
                        "meaning": str(it)[:160], "hint": "", "paths": [],
                        "raw": str(it)})
    return out


def probe_targets(explained):
    """The GET paths a live re-probe should hit, deduped, safe (GET only,
    never a write endpoint). Falls back to the two that always exist."""
    paths = set()
    for e in explained or ():
        for p in e.get("paths") or ():
            paths.add(p)
    gets = set()
    for e in explained or ():
        for m, p in _METHOD_PATH.findall(e.get("raw") or ""):
            if m == "GET":
                gets.add(p)
    targets = sorted(p for p in gets if p.startswith("/") and ".." not in p)
    return targets or ["/api/version", "/api/status"]


def decide(explained, probe):
    """What Resolve all does. ``probe`` = [{path, ok}] from the live server.

    ``rerun``  — every issue is the self-test failing to reach its target and
                 every probed path answered → re-run the health check.
    ``session`` — anything else → one doctor session seeded with all issues.
    ``nothing`` — no issues.
    """
    if not explained:
        return "nothing"
    all_unreach = all(e.get("kind") == KIND_SELF_TEST_UNREACHABLE for e in explained)
    all_answer = bool(probe) and all(bool(p.get("ok")) for p in probe)
    return "rerun" if (all_unreach and all_answer) else "session"


def resolve_all_seed(explained, probe, decision):
    """The seed for ONE doctor session covering every open issue (RESOLVE
    posture). Short on purpose — the PTY paste path mangles long seeds."""
    lines = ["ANCHOR DOCTOR - RESOLVE ALL %d OPEN ISSUES NOW" % len(explained)]
    for i, e in enumerate(explained, 1):
        lines.append("%d. %s" % (i, e.get("title") or "issue"))
        lines.append("   raw: %s" % (e.get("raw") or "")[:300])
    if probe:
        lines.append("live re-probe just now: " + "; ".join(
            "%s %s" % (p.get("path"), "answers" if p.get("ok") else
                       ("FAILS %s" % (p.get("code") or p.get("error") or "")))
            for p in probe))
    lines.append(
        "Do: take the issues in order; for each, reproduce minimally, FIX it in "
        "this folder, verify (run the relevant check), then one line of receipt. "
        "Finish by running the health check once so the report says what is "
        "true now. Ask John only for a real product decision.")
    return "\n".join(lines)
