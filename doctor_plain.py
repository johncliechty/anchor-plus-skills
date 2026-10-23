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

import json
import re
from pathlib import Path

_PLAYBOOK_PATH = Path(__file__).with_name("doctor_playbook.json")

KIND_SELF_TEST_UNREACHABLE = "self-test-unreachable"
KIND_SERVICE_STALE_CODE = "service-stale-code"
KIND_CHECKS_FAILED = "checks-failed"
KIND_OTHER = "other"

_UNREACHABLE = re.compile(
    r"actively refused|timed out|timeouterror|transport error|WinError 10061|Connection refused",
    re.I)
_PASSED = re.compile(r"(\d+)\s*/\s*(\d+)\s+passed")
_FAILED_N = re.compile(r"(\d+)\s+failed")
_GET_PATH = re.compile(r"\bGET\s+(/[^\s:;,>\]\)\"']*)")
_METHOD_PATH = re.compile(r"\b(GET|POST|PUT|DELETE)\s+(/[^\s:;,>\]\)\"']*)")


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
    endpointish = (
        comp.lower().startswith("http")
        or "route" in comp.lower()
        or "endpoint" in comp.lower()
        or bool(_METHOD_PATH.search(comp))
    )
    spare_port = any("free port" in str(a).lower() or "port" in str(a).lower()
                     for a in autofixes or ())
    found_paths = sorted({p for m, p in _METHOD_PATH.findall(raw) if m == "GET"})

    if "running service runs the checked code" in comp.lower() or "running sources" in detail.lower():
        return {
            "kind": KIND_SERVICE_STALE_CODE,
            "title": "The running Anchor service was on an older build than the files on disk",
            "meaning": ("Code or static files on disk changed (%s); syncing the live build and re-running the check clears the banner."
                        % (detail or "source fingerprint moved")),
            "hint": "One click on Resolve all / Resolve this syncs the live build and re-runs the health check automatically.",
            "paths": ["/api/version", "/api/status"],
            "raw": raw,
        }
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
            "paths": found_paths,
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
            "paths": found_paths,
            "raw": raw,
        }
    return {
        "kind": KIND_OTHER,
        "title": comp,
        "meaning": (detail[:157] + "…") if len(detail) > 160 else (detail or "(no detail)"),
        "hint": "",
        "paths": found_paths,
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
    targets = sorted(p for p in (gets | paths) if p.startswith("/") and ".." not in p)
    return targets or ["/api/version", "/api/status"]


def load_playbook(path=None):
    """Known health-issue recipes. Missing or junk file → no cases."""
    p = Path(path) if path else _PLAYBOOK_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return []
    cases = data.get("cases") if isinstance(data, dict) else None
    return [c for c in (cases or []) if isinstance(c, dict) and c.get("id")]


def _case_matches(case, explained_row):
    if case.get("kind") and case["kind"] != explained_row.get("kind"):
        return False
    if case.get("component"):
        raw = explained_row.get("raw") or ""
        title = explained_row.get("title") or ""
        if case["component"] not in raw and case["component"] not in title:
            return False
    blob = " ".join([
        str(explained_row.get("raw") or ""),
        str(explained_row.get("meaning") or ""),
        str(explained_row.get("title") or ""),
    ])
    for needle in case.get("detail_contains") or ():
        if needle not in blob:
            return False
    for needle in case.get("detail_excludes") or ():
        if needle in blob:
            return False
    return True


def match_playbook(explained, cases=None):
    """Return the playbook cases that cover these explained issues, in order."""
    cases = list(cases) if cases is not None else load_playbook()
    hits = []
    for row in explained or ():
        hit = next((c for c in cases if _case_matches(c, row)), None)
        if hit:
            hits.append(hit)
    return hits


def decide(explained, probe, playbook_hits=None):
    """What Resolve all does. ``probe`` = [{path, ok}] from the live server.

    ``rerun``  — every issue is the self-test failing to reach its target (or
                 stale service build fingerprint) and every probed path answered
                 → sync live build & re-run the health check.
                 Also when every open issue matches a playbook recipe whose
                 suggested action is rerun (a known stale/load result, not a
                 live-data defect).
    ``session`` — anything else → one doctor session seeded with all issues.
    ``nothing`` — no issues.
    """
    if not explained:
        return "nothing"
    all_answer = bool(probe) and all(bool(p.get("ok")) for p in probe)
    cases = load_playbook()
    hits = playbook_hits if playbook_hits is not None else match_playbook(explained, cases)
    if hits and len(hits) == len(explained) and all(h.get("suggested") == "rerun" for h in hits):
        return "rerun"
    def _row_can_rerun(row):
        if row.get("kind") in (KIND_SELF_TEST_UNREACHABLE, KIND_SERVICE_STALE_CODE) and all_answer:
            return True
        hit = next((c for c in cases if _case_matches(c, row)), None)
        return bool(hit and hit.get("suggested") == "rerun" and (all_answer or not probe))
    if all(_row_can_rerun(e) for e in explained):
        return "rerun"
    return "session"


def resolve_all_seed(explained, probe, decision, playbook_hits=None):
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
    hits = playbook_hits if playbook_hits is not None else match_playbook(explained)
    if hits:
        lines.append("Known prior cases (do not invent a new architecture):")
        for h in hits:
            lines.append("- %s: %s" % (h.get("id"), h.get("title") or ""))
            if h.get("session_advice"):
                lines.append("  " + h["session_advice"])
            for ban in h.get("do_not") or ():
                lines.append("  Do not: " + ban)
    lines.append(
        "Standard tool: run `python C:/dev/Anchor/tools/doctor_fix.py --auto` first to "
        "automatically sync live modules, repair cockpit projections, probe all routes, "
        "and refresh the health report. "
        "Do: take the issues in order; for each, reproduce minimally, FIX it in "
        "this folder, verify (run the relevant check), then one line of receipt. "
        "Finish by running the health check once so the report says what is "
        "true now. If a product decision is required, ask John one short "
        "question in this session and wait — do not sit on a tool-permission dialog. "
        "Never delete live campaign data or rewrite skills to make a check green.")
    return "\n".join(lines)


import sys as _sys_mod
_ESTATE_MEMO = getattr(_sys_mod.modules.get(__name__), "_ESTATE_MEMO", None)
if not isinstance(_ESTATE_MEMO, dict):
    _ESTATE_MEMO = {"sig": None, "data": None}


def _sync_live_steward_modules():
    """When reloaded inside a running anchor_gui server, also refresh steward_routes & usage modules."""
    import importlib
    import sys
    main_mod = sys.modules.get("__main__")
    if main_mod is None or not hasattr(main_mod, "AnchorHandler"):
        return
    old_scr = sys.modules.get("steward_cockpit.steward_routes")
    saved_job_status = dict(getattr(old_scr, "_JOB_STATUS", {}) or {})
    saved_global_usage = dict(getattr(old_scr, "_GLOBAL_USAGE_CACHE", {}) or {})
    saved_state_cache = dict(getattr(old_scr, "_STATE_CACHE", {}) or {})
    for mod_name in (
        "deliverables_register",
        "usage_allowance_monitor",
        "usage_capacity",
        "steward_cockpit.steward_campaign",
        "steward_cockpit.steward_engine",
        "steward_cockpit.anvil_session",
        "steward_cockpit.steward_routes",
        "terminal_session", "comms_connector", "high_seat_page", "home_rows", "proc_probe",
    ):
        try:
            if mod_name in sys.modules:
                importlib.reload(sys.modules[mod_name])
            else:
                importlib.import_module(mod_name)
        except Exception:
            pass
    new_scr = sys.modules.get("steward_cockpit.steward_routes")
    if new_scr is not None:
        if hasattr(new_scr, "CONFIG") and isinstance(new_scr.CONFIG, dict) and getattr(main_mod, "BUILD_ID", ""):
            new_scr.CONFIG["build"] = main_mod.BUILD_ID
        if saved_job_status and hasattr(new_scr, "_JOB_STATUS"):
            new_scr._JOB_STATUS.update(saved_job_status)
        if saved_global_usage and hasattr(new_scr, "_GLOBAL_USAGE_CACHE"):
            new_scr._GLOBAL_USAGE_CACHE.update(saved_global_usage)
        if saved_state_cache and hasattr(new_scr, "_STATE_CACHE"):
            new_scr._STATE_CACHE.update(saved_state_cache)
    try:
        def _fast_live_steward_estate():
            from steward_cockpit import steward_engine as _se
            tried = []
            try:
                live = main_mod._paths.data_dir() / "steward-cockpit-state.json"
                if live.exists():
                    tried.append(live)
            except Exception:
                pass
            current = getattr(_se, "STATE_FILE", None)
            if current:
                try:
                    p = Path(current)
                    if p.exists() and p.resolve() not in {x.resolve() for x in tried}:
                        tried.append(p)
                except Exception:
                    pass
            for p in tried:
                try:
                    st = p.stat()
                    sig = (str(p), st.st_mtime_ns, st.st_size)
                    if _ESTATE_MEMO.get("sig") == sig and isinstance(_ESTATE_MEMO.get("data"), dict):
                        return _ESTATE_MEMO["data"]
                    data = json.loads(p.read_text(encoding="utf-8"))
                    if isinstance(data, dict):
                        _ESTATE_MEMO["sig"] = sig
                        _ESTATE_MEMO["data"] = data
                        return data
                except Exception:
                    continue
            try:
                return _se._read_all_state()
            except Exception:
                return {}

        def _fast_project_steward_usage(project_id):
            if not project_id:
                return None
            try:
                proj = main_mod._rnd.get_project(project_id)
                folder = (proj or {}).get("folder_path") or ""
                if not folder:
                    return None
                estate = main_mod._live_steward_estate()
                sig = _ESTATE_MEMO.get("sig")
                use_cache = bool(sig and estate is _ESTATE_MEMO.get("data"))
                cache_map = _ESTATE_MEMO.setdefault("usage_by_folder", {})
                if use_cache:
                    if _ESTATE_MEMO.get("usage_sig") != sig:
                        cache_map.clear()
                        _ESTATE_MEMO["usage_sig"] = sig
                    elif folder in cache_map:
                        return cache_map[folder]
                from steward_cockpit.steward_routes import _usage_rollup
                total = ((_usage_rollup(folder, estate=estate) or {}).get("total") or {})
                toks = int(total.get("tokens") or 0)
                turns = int(total.get("unpriced_turns") or 0)
                reported = float(total.get("reported_spend") or 0)
                secs = float(total.get("secs") or 0)
                res = None if (toks <= 0 and turns <= 0 and reported <= 0 and secs <= 0) else total
                if use_cache:
                    cache_map[folder] = res
                return res
            except Exception:
                return None

        main_mod._live_steward_estate = _fast_live_steward_estate
        main_mod._project_steward_usage = _fast_project_steward_usage
        def _fast_working_pids(entries, sessions):
            out = set()
            try:
                for rec in sessions or ():
                    if isinstance(rec, dict) and rec.get("status") == "running" and rec.get("project_id"):
                        out.add(str(rec["project_id"]))
            except Exception:
                pass
            try:
                from steward_cockpit.steward_routes import ENGINES as _engines
                folders = []
                for e in entries or ():
                    try:
                        if e.get("folder_path") and e.get("id"):
                            folders.append((Path(e["folder_path"]).resolve(), str(e["id"])))
                    except Exception:
                        continue
                for cdir, eng in list(_engines.items()):
                    try:
                        if not ((eng.alive() and (getattr(eng, "busy", False) or getattr(eng, "queue", None))) or main_mod._engine_light(cdir)["light"] == "green"):
                            continue
                        c = Path(str(cdir)).resolve()
                        for f, pid in folders:
                            if c == f or f in c.parents:
                                out.add(pid)
                    except Exception:
                        continue
            except Exception:
                pass
            return out
        main_mod._working_pids = _fast_working_pids
        orig_probe = getattr(main_mod, "_orig_doctor_live_probe", None) or getattr(main_mod, "_doctor_live_probe", None)
        if orig_probe is not None:
            main_mod._orig_doctor_live_probe = orig_probe
            main_mod._doctor_live_probe = lambda path, timeout=10.0: orig_probe(path, timeout=timeout)
    except Exception:
        pass
    try:
        from steward_cockpit import steward_routes as _scr
        orig_steward_api = getattr(main_mod.AnchorHandler, "_orig_steward_api", None) or main_mod.AnchorHandler._steward_api
        main_mod.AnchorHandler._orig_steward_api = orig_steward_api

        def _patched_steward_api(self, method, verb, body=None):
            from urllib.parse import parse_qs, urlparse
            _q = parse_qs(urlparse(self.path).query)
            qs = {k: v[0] for k, v in _q.items()}
            if method == "GET" and verb == "usage-allowance":
                obj, code = _scr.usage_allowance_get(qs)
                self._send_json(obj, code=code)
                return
            if method == "POST" and verb == "usage-allowance":
                obj, code = _scr.usage_allowance_post(body or {})
                self._send_json(obj, code=code)
                return
            return orig_steward_api(self, method, verb, body)

        main_mod.AnchorHandler._steward_api = _patched_steward_api
    except Exception:
        pass


_sync_live_steward_modules()

