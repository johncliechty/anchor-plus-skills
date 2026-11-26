"""cave_processing_feed — Pure/stat-memoized read-only feed for Cave [N Processing] drawer (<300 lines, stdlib-only)."""
from __future__ import annotations
import json, math, os, threading, time
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import parse_qs, unquote, urlparse
import paths

MAX_PROCESSING_ROWS, MAX_QUERY_CHARS = 200, 512
SCRIBE_MIN_SEC_PER_DRAFT, SCRIBE_MAX_SEC_PER_DRAFT = 25, 45
_REPARSE_ATTR = 0x0400

FAILURE_STATE_TABLE: dict[str, dict[str, Any]] = {
    "dependency-missing": {"http_status": 503, "state": "unknown", "ok": False, "message": "Processing feed dependency missing (unknown — not empty)."},
    "dependency-slow-or-killed": {"http_status": 503, "state": "unknown", "ok": False, "message": "Processing feed timed out waiting on store lock/read (unknown — not empty)."},
    "dependency-returns-garbage": {"http_status": 503, "state": "unknown", "ok": False, "message": "Processing backing store returned malformed JSON or invalid schema (unknown — not empty)."},
    "backing-store-unreadable": {"http_status": 503, "state": "unknown", "ok": False, "message": "Processing backing store unreadable due to OS/permission error (unknown — not empty)."},
    "empty-but-valid": {"http_status": 200, "state": "empty", "ok": True, "message": "0 Processing — no active Cave Steward turns, Scribe drafts, or delegated cockpit runs."},
}
_MEMO_LOCK = threading.RLock()
_MEMO_CACHE: dict[str, tuple[tuple[Any, ...], dict[str, Any]]] = {}
_MEMO_STATS: dict[str, int] = {"hits": 0, "misses": 0}
_FEED_HOOKS: dict[str, Any] = {"available": True, "slow": False}

class ContainmentError(ValueError):
    """Raised when a path escapes allowed roots via `..`, absolute path, or symlink/junction."""

def set_processing_feed_hooks(*, available: bool = True, slow: bool = False) -> None:
    with _MEMO_LOCK:
        _FEED_HOOKS["available"], _FEED_HOOKS["slow"] = bool(available), bool(slow)

def get_memo_stats() -> dict[str, int]:
    with _MEMO_LOCK:
        return dict(_MEMO_STATS)

def reset_memo_cache() -> None:
    with _MEMO_LOCK:
        _MEMO_CACHE.clear()
        _MEMO_STATS["hits"] = _MEMO_STATS["misses"] = 0

def _is_reparse_or_link(p: Path) -> bool:
    try: return p.is_symlink() or bool(getattr(os.lstat(p), "st_file_attributes", 0) & _REPARSE_ATTR)
    except OSError: return False

def resolve_contained_feed_path(allowed_roots: list[Path] | tuple[Path, ...], candidate: str | os.PathLike[str], *, allow_contained_abs: bool = False) -> Path:
    raw, dec = str(candidate or ""), unquote(str(candidate or ""))
    if not raw.strip() or "\x00" in raw or "\x00" in dec:
        raise ContainmentError("Empty or NUL-containing path refused")
    for norm in (raw.replace("\\", "/"), dec.replace("\\", "/")):
        if norm.startswith("//") or ".." in norm.split("/"):
            raise ContainmentError(f"Path traversal refused: {raw}")
    cand_p = Path(dec)
    is_abs = cand_p.is_absolute() or (len(dec) >= 2 and dec[1] == ":") or dec.startswith(("/", "\\"))
    if is_abs and not allow_contained_abs:
        raise ContainmentError(f"Absolute path refused: {raw}")
    roots_real = [Path(r).resolve() for r in allowed_roots if r is not None]
    if not roots_real:
        raise ContainmentError("No allowed roots configured")
    probe = cand_p if is_abs else (roots_real[0] / cand_p)
    resolved = probe.resolve()
    matched_root = next((rr for rr in roots_real if resolved.is_relative_to(rr)), None)
    if matched_root is None:
        raise ContainmentError(f"Path escapes allowed roots: {raw}")
    tmp, walk = (probe if is_abs else (matched_root / cand_p)), []
    while True:
        walk.append(tmp)
        if tmp == matched_root or tmp.parent == tmp: break
        tmp = tmp.parent
    if any(_is_reparse_or_link(n) for n in reversed(walk)):
        raise ContainmentError(f"Symlink or junction refused: {raw}")
    return resolved

def atomic_write_json(target_path: Path | str, payload: Mapping[str, Any], *, lock_timeout_sec: float = 2.0) -> None:
    dst, data_bytes = Path(target_path), json.dumps(dict(payload), indent=2, sort_keys=True).encode("utf-8")
    with paths.WRITE_LOCK, paths.cross_process_lock(dst.with_name(dst.name + ".lock"), timeout_sec=lock_timeout_sec):
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f"{dst.name}.{os.getpid()}.{threading.get_ident()}.tmp")
        try:
            fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try: os.write(fd, data_bytes); os.fsync(fd)
            finally: os.close(fd)
            for attempt in range(25):
                try: os.replace(str(tmp), str(dst)); break
                except PermissionError:
                    if attempt == 24: raise
                    time.sleep(0.004)
        finally:
            tmp.unlink(missing_ok=True)

def format_elapsed(elapsed_sec: float | int) -> str:
    mins, rem = divmod(max(0, int(elapsed_sec)), 60)
    hrs, mins = divmod(mins, 60)
    return f"Elapsed {hrs}h {mins}m" if hrs > 0 else f"Elapsed {mins}m {rem:02d}s"

def compute_wave_eta(job: Mapping[str, Any], now: float) -> dict[str, Any]:
    total_w, comp_w = int(job.get("total_waves") or 0), int(job.get("completed_waves") or 0)
    cur_w = int(job.get("current_wave") or (comp_w + 1 if total_w > 0 else 0))
    phase = str(job.get("phase") or job.get("status") or "running").strip()[:80]
    durs = [float(d) for d in (job.get("wave_durations_sec") or ()) if isinstance(d, (int, float)) and not isinstance(d, bool) and math.isfinite(d) and d > 0]
    if not durs and isinstance(job.get("waves"), list):
        durs = [float(w["duration_sec"]) for w in job["waves"] if isinstance(w, dict) and str(w.get("status") or "").lower() in ("done", "green", "completed", "pass") and isinstance(w.get("duration_sec"), (int, float)) and w["duration_sec"] > 0]
    if durs and total_w > comp_w and comp_w >= 1:
        avg_w, rem_waves = sum(durs) / len(durs), max(1, total_w - comp_w)
        cs = job.get("current_wave_started_at")
        in_cur = max(0.0, now - float(cs)) if isinstance(cs, (int, float)) and cs > 0 else 0.0
        s = max(5, int(round(max(5.0, (avg_w - min(avg_w * 0.9, in_cur)) + (rem_waves - 1) * avg_w))))
        return {"timing_class": "wave_eta", "eta_seconds": s, "has_measured_eta": True, "eta_text": f"Est. ~{s}s left" if s < 60 else f"Est. ~{max(1, int(round(s / 60.0)))}m left"}
    return {"timing_class": "wave_eta", "eta_seconds": None, "has_measured_eta": False, "eta_text": f"Wave {cur_w}/{total_w} · {phase}" if total_w > 0 else f"Phase: {phase}"}

def compute_scribe_queue_eta(fifo_position: int) -> dict[str, Any]:
    pos = max(1, int(fifo_position))
    lo, hi = SCRIBE_MIN_SEC_PER_DRAFT * pos, SCRIBE_MAX_SEC_PER_DRAFT * pos
    return {"timing_class": "queue_range", "eta_seconds": None, "eta_min_sec": lo, "eta_max_sec": hi, "eta_text": f"Est. ~{lo}–{hi}s"}

def compute_steward_turn_eta(turn: Mapping[str, Any]) -> dict[str, Any]:
    phase = str(turn.get("phase") or turn.get("tool") or turn.get("doing") or "Processing Steward turn").strip()[:96]
    return {"timing_class": "live_phase", "eta_seconds": None, "has_measured_eta": False, "eta_text": f"Phase: {phase}"}

def derive_processing_rows(steward_turns: list[dict[str, Any]], scribe_items: list[dict[str, Any]], cockpit_jobs: list[dict[str, Any]], *, now: float, limit: int = MAX_PROCESSING_ROWS) -> tuple[list[dict[str, Any]], int, bool]:
    rows: list[dict[str, Any]] = []
    for idx, t in enumerate(steward_turns):
        st = float(t.get("started_at") or now)
        rows.append({"id": str(t.get("id") or f"steward-turn-{idx + 1}"), "group": "steward", "title": str(t.get("title") or "Cave Steward Turn")[:120], "description": str(t.get("description") or t.get("doing") or "Active Cave of Wonders Steward turn")[:200], "elapsed_sec": max(0, int(now - st)), "elapsed_text": format_elapsed(now - st), "cockpit_href": "", **compute_steward_turn_eta(t)})
    for pos, item in enumerate(scribe_items, 1):
        st = float(item.get("started_at") or item.get("queued_at") or item.get("created_at") or now)
        subj, rec = str(item.get("subject") or "Email reply").strip()[:110], str(item.get("to") or "").strip()[:70]
        rows.append({"id": str(item.get("id") or f"scribe-fifo-{pos}"), "group": "scribe", "title": f"Scribe Email Draft #{pos}", "description": f"Drafting reply on {subj}" + (f" ({rec})" if rec else ""), "elapsed_sec": max(0, int(now - st)), "elapsed_text": format_elapsed(now - st), "cockpit_href": "", **compute_scribe_queue_eta(pos)})
    for idx, j in enumerate(cockpit_jobs):
        st, href = float(j.get("started_at") or now), str(j.get("cockpit_href") or "")
        rows.append({"id": str(j.get("id") or f"cockpit-job-{idx + 1}"), "group": "cockpit", "title": str(j.get("title") or "Delegated Cockpit Run")[:120], "description": str(j.get("description") or "Running background cockpit task")[:200], "elapsed_sec": max(0, int(now - st)), "elapsed_text": format_elapsed(now - st), "cockpit_href": href if href.startswith("/") and not href.startswith("//") else "", **compute_wave_eta(j, now)})
    return rows[:limit], len(rows), len(rows) > limit

def _read_json_strict(p: Path, deadline: float) -> dict[str, Any] | None:
    if not p.exists(): return None
    if not p.is_file(): raise OSError(f"Expected file but found non-file store: {p.name}")
    for attempt in range(12):
        if time.perf_counter() > deadline: raise TimeoutError("Store read deadline exceeded")
        try:
            txt = p.read_text(encoding="utf-8")
            doc = json.loads(txt) if txt.strip() else {}
            if not isinstance(doc, dict): raise ValueError(f"Top-level JSON object required in {p.name}")
            return doc
        except PermissionError:
            if attempt == 11: raise
            time.sleep(0.003)
        except FileNotFoundError: return None
    return None

def _failure_response(key: str, detail: str = "") -> tuple[dict[str, Any], int]:
    spec = FAILURE_STATE_TABLE[key]
    msg, is_emp = (spec["message"] if not detail else f"{spec['message']} ({detail})"), spec["state"] == "empty"
    return {"ok": spec["ok"], "state": spec["state"], "failure_state": key, "count": 0 if is_emp else None, "badge_text": "0 Processing" if is_emp else "! Processing", "rows": [], "truncated": False, "message": msg, "error": "" if spec["ok"] else msg}, int(spec["http_status"])

def _resolve_roots(data_dir: Path | None) -> tuple[Path, Path, Path, list[Path]]:
    dd = Path(data_dir).resolve() if data_dir is not None else paths.data_dir().resolve()
    is_def = dd == paths.CODE_DIR.resolve()
    cave_env, cj_env, wt_env = [(os.environ.get(k) or "").strip() for k in ("ANCHOR_CAVE_DIR", "ANCHOR_CODE_JOBS_DIR", "ANCHOR_WORKTREE_BASE")]
    cave_dir = Path(cave_env).resolve() if cave_env else ((dd.parent / "Campaign") if is_def and (dd.parent / "Campaign").is_dir() else (dd / "Campaign"))
    cj_dir = Path(cj_env).resolve() if cj_env else (paths.code_jobs_dir().resolve() if is_def else (dd / "code_jobs"))
    return dd, cave_dir, cj_dir, [dd, cave_dir, cj_dir, *([Path(wt_env).resolve()] if wt_env else [])]

def _stat_sig_file(p: Path) -> tuple[str, int, int]:
    try: st = p.stat(); return (str(p), st.st_mtime_ns, st.st_size)
    except FileNotFoundError: return (str(p), -1, -1)

def _push_job(out: list[dict[str, Any]], seen: set[str], jid: str, rec: dict[str, Any], allowed: list[Path], default_lbl: str) -> None:
    if jid in seen or str(rec.get("status") or "").lower() not in ("running", "in_progress", "starting", "finishing"): return
    if rec.get("worktree") or rec.get("target_dir"):
        resolve_contained_feed_path(allowed, str(rec.get("worktree") or rec.get("target_dir")), allow_contained_abs=True)
    seen.add(jid)
    pid, lane, tw = str(rec.get("project_id") or rec.get("pid") or ""), str(rec.get("skill") or rec.get("lane") or default_lbl), int(rec.get("total_waves") or 0)
    pnm, cw = str(rec.get("project_name") or pid or default_lbl), int(rec.get("current_wave") or (int(rec.get("completed_waves") or 0) + 1 if tw else 0))
    out.append({**rec, "id": jid, "title": str(rec.get("title") or (f"{pnm} · {lane} Wave {cw}/{tw}" if tw else f"{pnm} · {rec.get('phase') or lane}")), "description": str(rec.get("description") or rec.get("doing") or rec.get("prompt_summary") or rec.get("brief") or f"Running {lane} task")[:200], "cockpit_href": f"/steward/v1?pid={pid}" if pid and "/" not in pid and ".." not in pid else ""})

def read_processing_feed(*, data_dir: Path | str | None = None, limit: Any = MAX_PROCESSING_ROWS, now: float | None = None, deadline_sec: float = 1.5) -> tuple[dict[str, Any], int]:
    if isinstance(limit, bool) or not isinstance(limit, int) or not (1 <= limit <= MAX_PROCESSING_ROWS):
        return {"ok": False, "state": "refused", "error": f"limit must be an integer in 1..{MAX_PROCESSING_ROWS}", "max_limit": MAX_PROCESSING_ROWS}, 400
    deadline, now_ts = time.perf_counter() + max(0.02, float(deadline_sec)), (time.time() if now is None else float(now))
    if not _FEED_HOOKS.get("available", True): return _failure_response("dependency-missing")
    if _FEED_HOOKS.get("slow", False): return _failure_response("dependency-slow-or-killed")
    try: dd, cave_dir, _cj_dir, allowed = _resolve_roots(Path(data_dir) if data_dir is not None else None)
    except OSError as exc: return _failure_response("backing-store-unreadable", str(exc))
    if not dd.exists() or not dd.is_dir(): return _failure_response("dependency-missing", "data_dir missing")
    sr_path, st_state_path, rnd_dir = dd / ".anchor" / "speed-racer-queue.json", dd / "steward-cockpit-state.json", dd / "rnd_jobs"
    pres_paths = [b / ".ecgberht" / n for b in (dd, cave_dir, cave_dir / "Cave of Wonders") for n in ("presence.json", "status_card.json")]
    cj_files = [dd / ".ecgberht" / "code-jobs.json", cave_dir / ".ecgberht" / "code-jobs.json"]
    try:
        rnd_entries: list[tuple[str, int, int]] = []
        if rnd_dir.exists():
            if not rnd_dir.is_dir(): return _failure_response("backing-store-unreadable", "rnd_jobs is not a directory")
            for ent in os.scandir(rnd_dir):
                if time.perf_counter() > deadline: raise TimeoutError("rnd_jobs scan deadline exceeded")
                if ent.name.endswith(".json") and not ent.name.endswith((".gate.json", ".cursor.json")):
                    st = ent.stat(follow_symlinks=False); rnd_entries.append((ent.name, st.st_mtime_ns, st.st_size))
            rnd_entries.sort(key=lambda x: (x[1], x[0]), reverse=True)
            rnd_entries = rnd_entries[:40]
        sig = (tuple(_stat_sig_file(p) for p in [sr_path, st_state_path, *pres_paths, *cj_files]), tuple(rnd_entries))
    except TimeoutError as exc: return _failure_response("dependency-slow-or-killed", str(exc))
    except OSError as exc: return _failure_response("backing-store-unreadable", str(exc))

    cache_key, raw_bundle = os.path.normcase(str(dd)), None
    with _MEMO_LOCK:
        hit = _MEMO_CACHE.get(cache_key)
        if hit is not None and hit[0] == sig:
            _MEMO_STATS["hits"] += 1; raw_bundle = hit[1]
    if raw_bundle is None:
        try:
            steward_turns: list[dict[str, Any]] = []
            for cand in pres_paths:
                doc = _read_json_strict(cand, deadline)
                if doc and not steward_turns and (doc.get("busy") is True or doc.get("in_flight") is True or doc.get("active") is True or str(doc.get("status") or doc.get("turn_status") or "").lower() in ("running", "working", "in_flight", "thinking", "active")):
                    steward_turns.append({"id": str(doc.get("turn_id") or "cave-steward-live"), "title": str(doc.get("title") or "Cave Steward Turn"), "doing": str(doc.get("doing") or doc.get("summary") or "Processing open-ended Cave Steward turn"), "phase": str(doc.get("phase") or doc.get("tool") or doc.get("doing") or "Thinking"), "started_at": float(doc.get("started_at") or doc.get("at") or now_ts)})
            for k_st, v_st in (_read_json_strict(st_state_path, deadline) or {}).items():
                if not steward_turns and isinstance(v_st, dict) and (v_st.get("busy") is True or v_st.get("in_flight") is True):
                    steward_turns.append({"id": f"steward-{Path(str(k_st)).name or 'cave'}", "title": "Cave Steward Turn", "doing": str(v_st.get("doing") or "Executing Steward turn"), "phase": str(v_st.get("phase") or v_st.get("tool") or "Running"), "started_at": float(v_st.get("turn_started_at") or v_st.get("updated_at") or now_ts)})
            sr_doc, scribe_items = _read_json_strict(sr_path, deadline), []
            if sr_doc is not None:
                q_raw = sr_doc.get("queue", [])
                if not isinstance(q_raw, list) or any(not isinstance(it, dict) for it in q_raw):
                    raise ValueError("speed-racer-queue.json queue must be a list of objects")
                scribe_items = [dict(it) for it in q_raw if str(it.get("status") or "").lower() in ("queued", "drafting", "pending", "in_flight", "running")]
            cockpit_jobs, seen_jobs = [], set()
            for name, _, _ in rnd_entries:
                rec = _read_json_strict(rnd_dir / name, deadline)
                if rec: _push_job(cockpit_jobs, seen_jobs, str(rec.get("job_id") or rec.get("id") or name[:-5]), rec, allowed, "Foreman")
            for cjf in cj_files:
                for jid, rec in (_read_json_strict(cjf, deadline) or {}).items():
                    if isinstance(rec, dict): _push_job(cockpit_jobs, seen_jobs, str(jid), rec, allowed, "Code Job")
            raw_bundle = {"steward_turns": steward_turns, "scribe_items": scribe_items, "cockpit_jobs": cockpit_jobs}
            with _MEMO_LOCK:
                _MEMO_STATS["misses"] += 1; _MEMO_CACHE[cache_key] = (sig, raw_bundle)
        except ContainmentError: raise
        except TimeoutError as exc: return _failure_response("dependency-slow-or-killed", str(exc))
        except (ValueError, json.JSONDecodeError) as exc: return _failure_response("dependency-returns-garbage", str(exc))
        except OSError as exc: return _failure_response("backing-store-unreadable", str(exc))

    rows, total, truncated = derive_processing_rows(raw_bundle["steward_turns"], raw_bundle["scribe_items"], raw_bundle["cockpit_jobs"], now=now_ts, limit=limit)
    if not rows:
        payload, code = _failure_response("empty-but-valid")
        payload["total_count"] = 0
        return payload, code
    return {"ok": True, "state": "ok", "failure_state": None, "count": len(rows), "total_count": total, "truncated": truncated, "badge_text": f"{len(rows)} Processing", "rows": rows, "message": f"{len(rows)} active task(s) processing."}, 200

def read_processing_feed_for_cave(_ctx: Mapping[str, Any] | None = None) -> dict[str, Any]:
    try: return read_processing_feed(limit=MAX_PROCESSING_ROWS)[0]
    except ContainmentError as exc: return _failure_response("dependency-returns-garbage", str(exc))[0]

def check_processing_auth(raw_path: str, headers: Mapping[str, Any] | None = None) -> bool:
    if paths.expected_token() is None: return True
    hdrs, q = headers or {}, parse_qs(urlparse(str(raw_path or "")).query)
    cands = [(q.get("token") or [None])[0], paths.token_from_authorization(hdrs.get("Authorization") or hdrs.get("authorization")), hdrs.get("X-Anchor-Token") or hdrs.get("x-anchor-token"), paths.token_from_cookie(hdrs.get("Cookie") or hdrs.get("cookie"))]
    return any(paths.auth_ok(tok) for tok in cands if tok)

def handle_processing_http_get(raw_path: str, *, headers: Mapping[str, Any] | None = None, data_dir: Path | str | None = None) -> tuple[dict[str, Any], int]:
    if not check_processing_auth(raw_path, headers=headers): return {"ok": False, "error": "unauthorized"}, 401
    parsed = urlparse(str(raw_path or ""))
    if len(parsed.query) > MAX_QUERY_CHARS or "%2e%2e" in parsed.query.lower() or "%00" in parsed.query.lower():
        return {"ok": False, "state": "refused", "error": "Invalid or unsafe query string"}, 400
    qs = parse_qs(parsed.query, keep_blank_values=True)
    dd, _cd, _cjd, allowed = _resolve_roots(Path(data_dir) if data_dir is not None else None)
    for pkey in ("scope", "dir", "effort_dir", "path"):
        if pkey in qs and qs[pkey][0]:
            try: resolve_contained_feed_path(allowed, qs[pkey][0], allow_contained_abs=False)
            except ContainmentError as exc: return {"ok": False, "state": "refused", "error": str(exc)}, 400
    limit = MAX_PROCESSING_ROWS
    if "limit" in qs:
        raw_lim = (qs["limit"][0] or "").strip()
        if not raw_lim or not raw_lim.lstrip("-").isdigit():
            return {"ok": False, "state": "refused", "error": f"limit must be an integer in 1..{MAX_PROCESSING_ROWS}"}, 400
        limit = int(raw_lim)
    try: return read_processing_feed(data_dir=dd, limit=limit)
    except ContainmentError as exc: return {"ok": False, "state": "refused", "error": str(exc)}, 400
