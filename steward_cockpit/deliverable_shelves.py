"""Deliverable instruction-batch ledger, conversation-log instruction miner & Steward hierarchical curation (stdlib-only)."""
from __future__ import annotations
from datetime import datetime, timezone
import hashlib, json, os, re, time, urllib.parse
from pathlib import Path
from typing import Any
import paths
BATCHES_REL, BATCHES_SCHEMA, MAX_EXCERPT_CHARS, MAX_STORED_BATCHES = ".ecgberht/deliverable-batches.json", "anchor-deliverable-batches-v1", 160, 80
_MEM_REF_STATES: dict[str, dict[str, Any]] = {}
_DOC_BUNDLE_EXTS = frozenset({".pdf", ".pptx", ".ppt", ".docx", ".doc", ".md", ".markdown", ".html", ".htm", ".tex", ".rtf", ".odt"})
_IMAGE_EXTS, _SHEET_EXTS, _ARCHIVE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"}), frozenset({".xlsx", ".xls", ".ods"}), frozenset({".zip", ".tar", ".gz", ".7z"})
_FINAL_RE, _EARLIER_RE = re.compile(r"^(?:[\u2605\u2b50]\s*)?(?:FINAL(?:IZED)?|APPROVED|ACCEPTED|SAVED\s+DESIGN)\b", re.I), re.compile(r"^(?:EARLIER|SUPERSEDED|HISTORICAL|ARCHIVED|Supporting|Supplemental)\b", re.I)
_NOISE_RE, _RECEIPT_PATH_RE = re.compile(r"^Code job \S+ kept \(not landed\)|^Code job \d{8}-\d{6}", re.I), re.compile(r"[?&]path=([^&#\s)\"']+)")
_NUM_V_RE, _NUM_R_RE = re.compile(r"^(?P<base>.+?)(?:[\s._\-]+|\s*\()v(?P<num>\d+(?:\.\d+)?)\)?$", re.I), re.compile(r"^(?P<base>.+?)(?:[._\-]+|\s+\()r(?P<num>\d+)\)?$", re.I)
_NUM_KW_RE, _ALPHA_REV_RE = re.compile(r"^(?P<base>.+?)(?:[\s._\-]+|\s*\()(?:rev(?:ision)?|draft|refinement|round|version)[\s._\-]*(?P<num>\d+)\)?$", re.I), re.compile(r"^(?P<base>.+?)(?:[\s._\-]+|\s*\()rev(?:ision)?[\s._\-]+(?P<let>[A-Za-z])\)?$", re.I)
def remember_refinement_state(cdir: str | Path | None, state: dict[str, Any] | None) -> None:
    if str(cdir or "").strip() and isinstance(state, dict):
        if len(_MEM_REF_STATES) >= 64: _MEM_REF_STATES.pop(next(iter(_MEM_REF_STATES)), None)
        _MEM_REF_STATES[os.path.normcase(os.path.abspath(str(cdir)))] = state
def _now_iso() -> str: return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
def _norm_rel(path_val: Any) -> str: return re.sub(r"/+", "/", str(path_val or "").strip().strip("`").replace("\\", "/")).lstrip("/")
def _clip_excerpt(text: Any, limit: int = MAX_EXCERPT_CHARS) -> str:
    flat = re.sub(r"\s+", " ", str(text or "")).strip(); return flat if len(flat) <= limit else ((flat[: limit - 1].rsplit(" ", 1)[0] or flat[: limit - 1]) + "\u2026")
def _parse_ts_epoch(ts_val: Any, fallback: float | None = None) -> float | None:
    if isinstance(ts_val, (int, float)) and not isinstance(ts_val, bool) and ts_val > 0: return float(ts_val)
    if isinstance(ts_val, str) and (s := ts_val.strip()):
        try: dt = datetime.fromisoformat((s + "T12:00:00+00:00") if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else s.replace("Z", "+00:00")); return (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp()
        except ValueError: return fallback
    return fallback
def _effective_batch_epoch(b: dict[str, Any]) -> float:
    ts_ep, raw_ep = _parse_ts_epoch(b.get("ts")), _parse_ts_epoch(b.get("epoch_s"))
    if b.get("source") == "refinement_update" and ts_ep is not None: return ts_ep
    if raw_ep is not None and ts_ep is not None and raw_ep - ts_ep > 86400.0 and b.get("source") not in ("register", "steward_curated"): return ts_ep
    return raw_ep if raw_ep is not None else (ts_ep if ts_ep is not None else 0.0)
def _human_ago(ts_val: Any, now_epoch: float | None = None) -> str:
    now = float(now_epoch if now_epoch is not None else time.time())
    if isinstance(ts_val, (int, float)) and not isinstance(ts_val, bool) and ts_val > 0: secs = max(0.0, now - float(ts_val))
    elif isinstance(ts_val, str) and (s := ts_val.strip()):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s): return s
        try: dt = datetime.fromisoformat(s.replace("Z", "+00:00")); secs = max(0.0, now - (dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)).timestamp())
        except ValueError: return s[:16]
    else: return "Recently"
    return "Just now" if secs < 90 else (f"{int(secs // 60)}m ago" if secs < 3600 else (f"{int(secs // 3600)}h ago" if secs < 86400 else f"{int(secs // 86400)}d ago"))
def parse_deliverable_identity(rel_path: str) -> dict[str, Any]:
    parent, _, fname = _norm_rel(rel_path).rpartition("/"); parent_key, (stem, ext) = parent.strip().lower(), os.path.splitext(fname); ext_low = ext.lower()
    kind = "doc_bundle" if ext_low in _DOC_BUNDLE_EXTS else ("image" if ext_low in _IMAGE_EXTS else ("sheet" if ext_low in _SHEET_EXTS else ("archive" if ext_low in _ARCHIVE_EXTS else f"ext:{ext_low or 'none'}")))
    is_redline = bool(re.search(r"(?:[\s._\-]+|\()redline\)?$", stem.strip(), re.I))
    work = re.sub(r"(?:[\s._\-]+|\()redline\)?$", "", stem.strip(), flags=re.I).strip() if is_redline else stem.strip()
    work = re.sub(r"\s*\((?:v\d+\s*[\u2014\u2013\-]\s*)?(?:final|current|approved)\)\s*$", lambda m: ("(" + re.search(r"v\d+", m.group(0), re.I).group(0) + ")" if re.search(r"v\d+", m.group(0), re.I) else ""), work, flags=re.I).strip()
    work, rev_key, rev_label = re.sub(r"(?:[\s._\-]+)final$", "", work, flags=re.I).strip(), None, ""; base_raw = work
    if (m_v := _NUM_V_RE.match(work)): base_raw, rev_key, rev_label = m_v.group("base"), (1, tuple(int(x) for x in m_v.group("num").split("."))), f"v{m_v.group('num')}"
    elif (m_r := _NUM_R_RE.match(work)): base_raw, rev_key, rev_label = m_r.group("base"), (1, (int(m_r.group("num")),)), f"r{m_r.group('num')}"
    elif (m_kw := _NUM_KW_RE.match(work)): base_raw, rev_key, rev_label = m_kw.group("base"), (1, (int(m_kw.group("num")),)), f"v{m_kw.group('num')}"
    elif (m_al := _ALPHA_REV_RE.match(work)): let = m_al.group("let").upper(); base_raw, rev_key, rev_label = m_al.group("base"), (2, (ord(let) - ord("A") + 1,)), f"Rev {let}"
    bs_norm = re.sub(r"[\s._\-]+", " ", base_raw).strip().lower()
    return {"parent": parent_key, "base_stem": bs_norm, "kind_group": kind, "family_tuple": (parent_key, bs_norm, kind), "rev_key": rev_key, "rev_label": rev_label, "ext": ext_low.lstrip(".").upper() or "FILE", "is_redline": is_redline}
def resolve_readable_aliases(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _ok = lambda p: isinstance(p, str) and 0 < len(p) <= 1000 and not re.search(r"[\\:\x00-\x1f]", p) and not p.startswith("/") and all(seg and seg not in (".", "..") for seg in p.split("/"))
    aliases: dict[str, dict[str, str] | None] = {}
    for row in (r for r in (items or []) if isinstance(r, dict) and not r.get("managed") and r.get("openable")):
        rp = _norm_rel(row.get("path"))
        if not (m := (re.search(r"\breview:\s*`([^`]+)`", str(row.get("where_text") or "")) if _ok(rp) else None)): continue
        bind, owner, what = _norm_rel(m.group(1)), str(row.get("owner_step_id") or row.get("step") or "").strip(), str(row.get("what") or "").strip()
        if _ok(bind) and bind != rp and owner and what: entry = {"owner": owner, "label": what, "open_path": rp}; aliases[bind] = None if (bind in aliases and aliases[bind] != entry) else entry
    decorated, bound_open = [], set()
    for it in (x for x in (items or []) if isinstance(x, dict)):
        ip, owner = _norm_rel(it.get("path")), str(it.get("owner_step_id") or it.get("step") or it.get("step_id") or "").strip()
        if (al := aliases.get(ip)) and it.get("managed") and re.fullmatch(r"[a-f0-9]{64}", str(it.get("hash") or ""), re.I) and al["owner"] == owner and os.path.splitext(ip)[1].lower() == os.path.splitext(al["open_path"])[1].lower():
            cp = {**it, "what": al["label"], "human_title": al["label"], "open_path": al["open_path"], "suggested_filename": al["open_path"].rsplit("/", 1)[-1] or it.get("suggested_filename") or ""}
            if cp.get("is_current"): bound_open.add(al["open_path"])
            decorated.append(cp)
        else: decorated.append(dict(it))
    return [d for d in decorated if d.get("managed") or _norm_rel(d.get("path")) not in bound_open]
def read_batches_doc(cdir: str | Path) -> dict[str, Any]:
    fp, empty = Path(cdir) / BATCHES_REL, {"schema": BATCHES_SCHEMA, "batches": [], "curation": {"supersedes": {}}}
    if not fp.is_file(): return empty
    try: return d if isinstance(d := json.loads(fp.read_text(encoding="utf-8")), dict) else empty
    except (OSError, ValueError): return empty
def _dedupe_and_trim_batches(batches: list[dict[str, Any]], limit: int = MAX_STORED_BATCHES) -> list[dict[str, Any]]:
    by_id, order, anon_idx = {}, [], 0
    for raw in (x for x in (batches or []) if isinstance(x, dict)):
        b = {**raw, **({"epoch_s": round(_effective_batch_epoch(raw), 6)} if raw.get("source") == "refinement_update" else {})}
        if not (bid := str(b.get("batch_id") or "").strip()): anon_idx += 1; bid = f"_anon_{anon_idx}"
        if bid not in by_id: by_id[bid], _ = b, order.append(bid)
        else:
            prev = by_id[bid]; upd = {**prev, **b, "paths": list(dict.fromkeys([*(prev.get("paths") or []), *(b.get("paths") or [])])), "ids": list(dict.fromkeys([*(prev.get("ids") or []), *(b.get("ids") or [])]))}
            if upd.get("source") == "refinement_update": upd["epoch_s"] = round(_effective_batch_epoch(upd), 6)
            by_id[bid] = upd
    deduped = [by_id[k] for k in order]
    if len(deduped) > limit or any(x.get("source") == "refinement_update" for x in deduped):
        deduped.sort(key=lambda x: (round(_effective_batch_epoch(x), 6), int(x.get("turn_num") or 0), str(x.get("batch_id") or "")))
    return deduped[-limit:]
def _write_batches_doc_locked(cdir: str | Path, doc: dict[str, Any]) -> None:
    fp = Path(cdir) / BATCHES_REL; doc["schema"], doc["batches"] = BATCHES_SCHEMA, _dedupe_and_trim_batches(list(doc.get("batches") or []))
    payload = json.dumps(doc, indent=2, ensure_ascii=False) + "\n"
    try:
        if fp.is_file() and fp.read_text(encoding="utf-8") == payload: return
    except OSError: pass
    fp.parent.mkdir(parents=True, exist_ok=True); paths.atomic_write_text(fp, payload)
def _latest_user_turn(cdir: str | Path) -> tuple[str, str, int]:
    if not (log_fp := Path(cdir) / ".ecgberht" / "conversation-log.json").is_file(): return "", "", 0
    try: turns = (json.loads(log_fp.read_text(encoding="utf-8")) or {}).get("turns") or []
    except (OSError, ValueError): return "", "", 0
    u_idx, last_id, last_txt = 0, "", ""
    for t in (x for x in turns if isinstance(x, dict) and x.get("role") not in ("steward", "system", None) and str(x.get("text") or "").strip()):
        u_idx += 1; last_id, last_txt = str(t.get("turn_id") or f"u{u_idx}"), _clip_excerpt(t.get("text"))
    return last_id, last_txt, u_idx
def _mine_conversation_batches(cdir: str | Path | None) -> list[dict[str, Any]]:
    if not cdir or not str(cdir).strip() or not (log_fp := Path(cdir) / ".ecgberht" / "conversation-log.json").is_file(): return []
    try: turns = (json.loads(log_fp.read_text(encoding="utf-8")) or {}).get("turns") or []
    except (OSError, ValueError): return []
    u_idx, cur_u, grouped, order = 0, None, {}, []
    for t in (x for x in turns if isinstance(x, dict)):
        role, tid, txt = str(t.get("role") or ""), str(t.get("turn_id") or ""), str(t.get("text") or "").strip()
        if role not in ("steward", "system", "") and txt: u_idx += 1; cur_u = (f"conv-u{u_idx}-{tid[:24]}", u_idx, _clip_excerpt(txt), str(t.get("at") or ""))
        elif tid.startswith("receipt:") and not tid.startswith("receipt:kept:") and txt and (found := [_norm_rel(urllib.parse.unquote(rp)) for rp in _RECEIPT_PATH_RE.findall(txt)]):
            bid, t_num, exc, u_at = cur_u if cur_u else ("conv-u0", 0, "Initial deliverable baseline", str(t.get("at") or ""))
            if bid not in grouped: grouped[bid] = {"batch_id": bid, "turn_num": t_num, "instruction_excerpt": exc, "ts": str(t.get("at") or u_at), "primary": [], "supp": []}; order.append(bid)
            else: grouped[bid]["ts"] = str(t.get("at") or grouped[bid]["ts"])
            is_supp_txt = bool(re.search(r"\b(?:Supporting|Earlier|Superseded)\s*[-:]", txt, re.I))
            for fp in (f for f in found if f):
                if fp not in (bucket := grouped[bid]["supp" if (is_supp_txt or "/planning/" in f"/{fp.lower()}") else "primary"]): bucket.append(fp)
    return [{**grouped[k], "paths": grouped[k]["primary"] or grouped[k]["supp"], "source": "conversation_log"} for k in order if k != "conv-u0" and (grouped[k]["primary"] or grouped[k]["supp"])]
def record_registered_deliverable(cdir: str | Path, *, what: str, where: str, step: str = "", date: str = "", notify: bool = True, instruction: str | None = None, batch_id: str | None = None) -> None:
    root = Path(cdir)
    if not str(cdir or "").strip() or not root.exists(): return
    if not (clean_where := _norm_rel(re.sub(r"\b(?:review|run):\s*(?:`[^`]+`|\S+)", "", str(where or "")).strip())) and not what: return
    u_id, u_txt, u_num = _latest_user_turn(root); now_iso, now_ep = _now_iso(), time.time()
    with paths.WRITE_LOCK:
        doc = read_batches_doc(root); batches = list(doc.get("batches") or [])
        if batch_id: bid, excerpt = str(batch_id).strip()[:80], _clip_excerpt(instruction or u_txt or what)
        elif instruction: bid, excerpt = f"instr-{hashlib.sha1(instruction.strip().encode('utf-8')).hexdigest()[:10]}", _clip_excerpt(instruction)
        elif u_id: bid, excerpt = f"turn-{u_num}-{u_id}"[:80], u_txt
        elif batches and batches[-1].get("_open_multi"): bid, excerpt = str(batches[-1]["batch_id"]), str(batches[-1].get("instruction_excerpt") or _clip_excerpt(what))
        else: bid, excerpt = f"reg-{int(now_ep * 1000)}-{len(batches) + 1}", _clip_excerpt(what)
        if (target := next((b for b in reversed(batches) if b.get("batch_id") == bid), None)) is None:
            target = {"batch_id": bid, "turn_num": u_num or (len(batches) + 1), "instruction_excerpt": excerpt, "ts": (date if re.match(r"^\d{4}-\d{2}-\d{2}T", str(date or "")) else now_iso), "epoch_s": now_ep, "paths": [], "ids": [], "source": "register"}; batches.append(target)
        if clean_where and clean_where not in target["paths"]: target["paths"].append(clean_where)
        if step and step not in target["ids"]: target["ids"].append(str(step))
        target["_open_multi"], doc["batches"] = not bool(notify), batches; _write_batches_doc_locked(root, doc)
def discover_refinement_batches(cdir: str | Path | None, refinement_state: dict[str, Any] | None = None, *, operation: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    root = Path(cdir) if str(cdir or "").strip() else None
    if not isinstance(slices := ((refinement_state or {}).get("slices") if isinstance(refinement_state, dict) else None), dict): return []
    discovered, (_, u_txt, u_num) = [], (_latest_user_turn(root) if (root and root.is_dir()) else ("", "", 0))
    op_note, last_ev_ts = _clip_excerpt((operation or {}).get("purpose") or (operation or {}).get("note") or ""), str((refinement_state or {}).get("last_event_at") or "").strip()
    for step_id, sl in ((k, v) for k, v in slices.items() if isinstance(v, dict)):
        revs, presented = (sl.get("revisions") if isinstance(sl.get("revisions"), dict) else {}), set()
        for pres in (p for p in (sl.get("presentations") or []) if isinstance(p, dict)):
            if not (members := [m for m in (pres.get("members") or []) if isinstance(m, dict) and m.get("path")]): continue
            pid, ts_s = str(pres.get("id") or f"{step_id}-r{pres.get('round', 0)}"), str(pres.get("at") or last_ev_ts or "").strip(); presented.update(str(m["revision_id"]) for m in members if m.get("revision_id"))
            discovered.append({"batch_id": f"ref-pres-{step_id}-{pid}"[:80], "turn_num": u_num or 1, "instruction_excerpt": _clip_excerpt(pres.get("purpose") or op_note or u_txt or f"Published {step_id}"), "ts": ts_s, "epoch_s": round(_parse_ts_epoch(ts_s, 0.0) or 0.0, 6), "paths": [_norm_rel(m["path"]) for m in members], "ids": [str(m.get("product_id") or "") for m in members if m.get("product_id")], "source": "refinement_update"})
        if (unpres := [revs[rid] for rid in ((sl.get("candidate") if isinstance(sl.get("candidate"), dict) else {}).values()) if isinstance(rid, str) and rid not in presented and isinstance(revs.get(rid), dict) and revs[rid].get("path")]):
            ts_s = str(unpres[-1].get("at") or last_ev_ts or "").strip()
            discovered.append({"batch_id": f"ref-cand-{step_id}-{'-'.join(sorted(str(r.get('revision_id') or '') for r in unpres))}"[:80], "turn_num": u_num or 1, "instruction_excerpt": _clip_excerpt(op_note or u_txt or f"Candidate update for {step_id}"), "ts": ts_s, "epoch_s": round(_parse_ts_epoch(ts_s, 0.0) or 0.0, 6), "paths": [_norm_rel(r["path"]) for r in unpres], "ids": [str(r.get("product_id") or "") for r in unpres if r.get("product_id")], "source": "refinement_update"})
    return discovered
def sync_refinement_batches(cdir: str | Path, *, refinement_state: dict[str, Any] | None = None, operation: dict[str, Any] | None = None) -> None:
    root = Path(cdir) if str(cdir or "").strip() else None
    if not root or not root.is_dir() or not (discovered := discover_refinement_batches(root, refinement_state, operation=operation)): return
    remember_refinement_state(root, refinement_state)
    with paths.WRITE_LOCK:
        doc = read_batches_doc(root); existing = list(doc.get("batches") or []); by_id, merged_disc = {str(b.get("batch_id") or ""): b for b in existing if isinstance(b, dict)}, []
        for d in (x for x in discovered if x.get("paths")):
            if (prev := by_id.get(d["batch_id"])) is not None:
                merged_disc.append({**prev, **d, "turn_num": prev.get("turn_num") or d.get("turn_num") or 1, "epoch_s": round(_parse_ts_epoch(d.get("ts") or prev.get("ts"), _parse_ts_epoch(prev.get("epoch_s"), 0.0)) or 0.0, 6)})
            else:
                ts_s = d.get("ts") or (_now_iso() if operation is not None else "")
                merged_disc.append({**d, "ts": ts_s, "epoch_s": round(_parse_ts_epoch(ts_s, time.time() if operation is not None else 0.0) or 0.0, 6)})
        disc_ids = {x["batch_id"] for x in merged_disc}
        doc["batches"] = [b for b in existing if isinstance(b, dict) and str(b.get("batch_id") or "") not in disc_ids] + merged_disc; _write_batches_doc_locked(root, doc)
def update_curation(cdir: str | Path, body: dict[str, Any]) -> dict[str, Any]:
    root, b = Path(cdir), (body if isinstance(body, dict) else {})
    with paths.WRITE_LOCK:
        doc = read_batches_doc(root); cur, sup = doc.setdefault("curation", {}), dict((doc.get("curation") or {}).get("supersedes") or {})
        for k, v in (b.get("supersedes") or {}).items() if isinstance(b.get("supersedes"), dict) else ():
            sup[_norm_rel(k)] = [_norm_rel(x) for x in ([v] if isinstance(v, str) else (list(v) if isinstance(v, list) else [])) if str(x or "").strip()]
        cur["supersedes"] = sup
        for key in ("promoted_final", "demoted_archive"):
            if isinstance(b.get(key), list): cur[key] = [_norm_rel(x) for x in b[key] if str(x or "").strip()]
        if b.get("headline") is not None or b.get("summary") is not None or isinstance(b.get("final_summary"), dict):
            fs, src = dict(cur.get("final_summary") or {}), (b["final_summary"] if isinstance(b.get("final_summary"), dict) else b)
            if src.get("headline") is not None: fs["headline"] = _clip_excerpt(src.get("headline"), 200)
            if src.get("summary") is not None or src.get("narrative") is not None: fs["narrative"] = _clip_excerpt(src.get("summary") if src.get("summary") is not None else src.get("narrative"), 360)
            fs["updated_at"], cur["final_summary"] = _now_iso(), fs
        if isinstance(b.get("final_groups"), list):
            cur["final_groups"] = [{"id": str(g.get("id") or f"grp-{i+1}"), "title": _clip_excerpt(g.get("title") or "Deliverable Group", 90), "summary": _clip_excerpt(g.get("summary") or "", 180), "paths": [_norm_rel(p) for p in (g.get("paths") or []) if str(p or "").strip()]} for i, g in enumerate(b["final_groups"]) if isinstance(g, dict)]
        if isinstance(b.get("recent_paths"), list) and b["recent_paths"]:
            _, u_txt, u_num = _latest_user_turn(root); batches = list(doc.get("batches") or [])
            batches.append({"batch_id": f"curated-{int(time.time()*1000)}", "turn_num": u_num or (len(batches) + 1), "instruction_excerpt": _clip_excerpt(b.get("instruction") or u_txt or "Steward-curated presentation"), "ts": _now_iso(), "epoch_s": time.time(), "paths": [_norm_rel(p) for p in b["recent_paths"] if str(p or "").strip()], "ids": [], "source": "steward_curated"}); doc["batches"] = batches
        _write_batches_doc_locked(root, doc)
    return {"ok": True, "curation": doc.get("curation")}
def enrich_hierarchy_with_curation(deliv_hierarchy: dict[str, Any] | None, batches_doc: dict[str, Any] | None, final_bundled: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    h = dict(deliv_hierarchy) if isinstance(deliv_hierarchy, dict) else {"is_course": False, "executive_summary": {}, "categories": []}
    cur = ((batches_doc or {}).get("curation") or {}) if isinstance(batches_doc, dict) else {}
    exec_sum, fs = dict(h.get("executive_summary") or {}), (cur.get("final_summary") if isinstance(cur.get("final_summary"), dict) else {})
    if fs.get("headline"): exec_sum["headline"], exec_sum["steward_authored"] = fs["headline"], True
    if fs.get("narrative"): exec_sum["narrative"], exec_sum["steward_authored"] = fs["narrative"], True
    h["executive_summary"] = exec_sum
    if (fg := cur.get("final_groups")) and isinstance(fg, list) and final_bundled:
        by_p = {k: it for it in final_bundled if isinstance(it, dict) for k in (_norm_rel(it.get("path")).lower(), _norm_rel(it.get("open_path") or it.get("path")).lower()) if k}
        used, steward_cats = set(), []
        def _mk_cat(cid: str, title: str, summary: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
            files = [{**m, "title": m.get("human_title") or m.get("what") or m.get("path"), "filename": _norm_rel(m.get("open_path") or m.get("path")).rsplit("/", 1)[-1]} for m in rows]
            return {"id": cid, "title": title, "unit_count": 1, "final_count": 1, "review_count": 0, "units": [{"unit_key": cid, "title": title, "label": title, "status": "Final", "file_count": len(files), "ext_summary": summary, "files": files, "default_expanded": False}]}
        for idx, g in enumerate(fg):
            if (matched := [by_p[pk] for p in (g.get("paths") or []) if (pk := _norm_rel(p).lower()) in by_p and not (pk in used or used.add(pk))]):
                steward_cats.append(_mk_cat(g.get("id") or f"steward-{idx+1}", g.get("title") or "Curated Workstream", g.get("summary") or f"{len(matched)} curated", matched))
        if steward_cats:
            if (rem := [it for it in final_bundled if _norm_rel(it.get("open_path") or it.get("path")).lower() not in used and _norm_rel(it.get("path")).lower() not in used]):
                steward_cats.append(_mk_cat("additional-final", "Additional Final Deliverables", f"{len(rem)} items", rem))
            h["categories"] = steward_cats
    return h
def _bundle_format_siblings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups, order, fmt_rank = {}, [], {"PDF": 1, "HTML": 2, "DOCX": 3, "PPTX": 4, "MD": 5}
    for idx, it in enumerate(rows):
        p = _norm_rel(it.get("open_path") or it.get("path")); ident = parse_deliverable_identity(p) if p else None
        gk = ("doc", ident["parent"], ident["base_stem"], ident["rev_key"]) if (ident and ident["kind_group"] == "doc_bundle" and ident["base_stem"]) else ("single", p or idx)
        if gk not in groups: groups[gk], _ = [], order.append(gk)
        groups[gk].append((it, ident))
    bundled = []
    for gk in order:
        members = sorted(groups[gk], key=lambda pr: (1 if (pr[1] and pr[1]["is_redline"]) else 0, fmt_rank.get(pr[1]["ext"] if pr[1] else "", 9)))
        row_out, pills, seen_lbl = dict(members[0][0]), [], set()
        for m_it, m_id in members:
            if (lbl := ("Redline" if (m_id and m_id["is_redline"]) else (m_id["ext"] if m_id else "FILE"))) not in seen_lbl:
                seen_lbl.add(lbl); pills.append({"label": lbl, "path": m_it.get("open_path") or m_it.get("path") or "", "raw_path": m_it.get("path") or "", "route": m_it.get("route") or "", "hash": m_it.get("hash") or "", "product_id": m_it.get("product_id") or "", "suggested_filename": m_it.get("suggested_filename") or "", "reading": m_it.get("reading"), "download_url": m_it.get("download_url") or "", "is_redline": bool(m_id and m_id["is_redline"])})
        row_out["format_pills"], row_out["member_count"] = pills, len(members); bundled.append(row_out)
    return bundled
def compute_shelves(items: list[dict[str, Any]], batches_doc: dict[str, Any] | None = None, *, approved: list[dict[str, Any]] | None = None, conv_batches: list[dict[str, Any]] | None = None, now_epoch: float | None = None) -> dict[str, Any]:
    clean_items = [it for it in resolve_readable_aliases(list(items or [])) if isinstance(it, dict) and not _NOISE_RE.search(str(it.get("what") or ""))]
    by_path: dict[str, dict[str, Any]] = {}
    for it in clean_items:
        for pk in (_norm_rel(it.get("path")), _norm_rel(it.get("open_path")), _norm_rel(it.get("path")).lower(), _norm_rel(it.get("open_path")).lower()):
            if pk and pk not in by_path: by_path[pk] = it
    bdoc = batches_doc if isinstance(batches_doc, dict) else {}; cur = bdoc.get("curation") if isinstance(bdoc.get("curation"), dict) else {}
    raw_sup = {**(bdoc.get("supersedes") if isinstance(bdoc.get("supersedes"), dict) else {}), **(cur.get("supersedes") if isinstance(cur.get("supersedes"), dict) else {})}
    prom_set, dem_set = {_norm_rel(x).lower() for x in (cur.get("promoted_final") or bdoc.get("promoted_final") or []) if x}, {_norm_rel(x).lower() for x in (cur.get("demoted_archive") or bdoc.get("demoted_archive") or []) if x}
    def _match_batch(b: dict[str, Any]) -> list[dict[str, Any]]:
        m, seen_m = [], set()
        for p in b.get("paths") or []:
            np = _norm_rel(p)
            if (hit := (by_path.get(np) or by_path.get(np.lower()))) is not None and (hk := _norm_rel(hit.get("open_path") or hit.get("path")).lower()) not in seen_m: seen_m.add(hk); m.append(hit)
        return m or ([it for it in clean_items if str(it.get("product_id") or "") in {str(x) for x in (b.get("ids") or []) if x}] if b.get("ids") else [])
    explicit_valid = [{**b, "_matched": m} for b in (bdoc.get("batches") or []) if isinstance(b, dict) and (m := _match_batch(b))]
    conv_valid = [{**b, "_matched": m} for b in (conv_batches or []) if isinstance(b, dict) and (m := _match_batch(b))]
    exp_filtered = [b for b in explicit_valid if b.get("source") != "refinement_update"] if conv_valid else explicit_valid
    coalesced: list[dict[str, Any]] = []
    for b in (conv_valid + exp_filtered if exp_filtered else conv_valid):
        exc_norm = re.sub(r"\s+", " ", str(b.get("instruction_excerpt") or "").strip()).lower()
        if (existing := next((c for c in coalesced if exc_norm and re.sub(r"\s+", " ", str(c.get("instruction_excerpt") or "").strip()).lower() == exc_norm and (b.get("turn_num") == c.get("turn_num") or b.get("source") == "conversation_log" or c.get("source") == "conversation_log")), None)) is not None:
            seen_k = {_norm_rel(x.get("open_path") or x.get("path")).lower() for x in existing["_matched"]}
            for nx in b["_matched"]:
                if (nk := _norm_rel(nx.get("open_path") or nx.get("path")).lower()) not in seen_k: seen_k.add(nk); existing["_matched"].append(nx)
            if b.get("epoch_s") or b.get("ts"): existing["epoch_s"], existing["ts"] = b.get("epoch_s") or existing.get("epoch_s"), b.get("ts") or existing.get("ts")
            if b.get("turn_num"): existing["turn_num"] = b.get("turn_num")
        else: coalesced.append({**b, "_matched": list(b["_matched"])})
    kept_batches = list(reversed(coalesced[-2:]))
    if not kept_batches and clean_items:
        by_ds, ds_order = {}, []
        for it in (x for x in clean_items if not x.get("auto") and not _EARLIER_RE.match(str(x.get("what") or ""))):
            dk = (str(it.get("date") or "")[:10], str(it.get("step") or ""))
            if dk not in by_ds: by_ds[dk], _ = [], ds_order.append(dk)
            by_ds[dk].append(it)
        kept_batches = [{"batch_id": f"fallback-{i + 1}", "turn_num": len(ds_order) - i, "instruction_excerpt": f"Deliverables for {dk[1]}" if dk[1] else "Recent deliverable update", "ts": dk[0], "_matched": by_ds[dk]} for i, dk in enumerate(ds_order[:2])]
    recent_batches_out, recent_keys = [], set()
    for b_idx, kb in enumerate(kept_batches[:2]):
        raw_m = kb["_matched"]; recent_keys.update(_norm_rel(m_it.get("open_path") or m_it.get("path")).lower() for m_it in raw_m)
        recent_batches_out.append({"batch_id": str(kb.get("batch_id") or f"b-{b_idx}"), "rank_label": "Last Instruction" if b_idx == 0 else "Instruction Before Last", "turn_num": kb.get("turn_num"), "ago": _human_ago(_effective_batch_epoch(kb) or kb.get("ts"), now_epoch), "instruction_excerpt": _clip_excerpt(kb.get("instruction_excerpt") or ""), "file_count": len(raw_m), "items": _bundle_format_siblings(raw_m)})
    final_pool, seen_fp = [], set()
    for it in clean_items + resolve_readable_aliases(list(approved or [])):
        p_disp, p_raw = _norm_rel(it.get("open_path") or it.get("path")), _norm_rel(it.get("path"))
        pk_low = (p_disp or p_raw or str(it.get("what") or "")).lower()
        if not pk_low or pk_low in seen_fp or it.get("auto"): continue
        what_s, is_prom = str(it.get("what") or "").strip(), (pk_low in prom_set or p_raw.lower() in prom_set or str(it.get("product_id") or "").lower() in prom_set)
        if not (pk_low in dem_set or p_raw.lower() in dem_set) and not _EARLIER_RE.match(what_s) and (is_prom or it.get("tier") == "final" or it.get("final_promoted") is True or it.get("accepted") is True or it.get("accepted_current") is True or bool(_FINAL_RE.match(what_s)) or "/final deliverables/" in f"/{p_disp.lower()}" or "/finished deliverables/" in f"/{p_disp.lower()}"):
            seen_fp.add(pk_low); final_pool.append(dict(it))
    present_keys = {k for it in final_pool for k in (_norm_rel(it.get("open_path")).lower(), _norm_rel(it.get("path")).lower(), str(it.get("product_id") or "").lower()) if k}
    exp_sup_by = {_norm_rel(l_raw).lower(): _norm_rel(w_raw) for w_raw, l_list in raw_sup.items() if _norm_rel(w_raw).lower() in present_keys for l_raw in ([l_list] if isinstance(l_list, str) else (l_list if isinstance(l_list, list) else [])) if _norm_rel(l_raw).lower() and _norm_rel(l_raw).lower() != _norm_rel(w_raw).lower()}
    rev_max, rev_prev_lbl, parsed_finals = {}, {}, [(it, parse_deliverable_identity(_norm_rel(it.get("open_path") or it.get("path")))) for it in final_pool]
    for _, ident in parsed_finals:
        if (rk := ident["rev_key"]) is not None and ident["base_stem"]:
            fk = (*ident["family_tuple"], rk[0])
            if fk not in rev_max or rk[1] > rev_max[fk][0]:
                if fk in rev_max: rev_prev_lbl[fk] = rev_max[fk][1]
                rev_max[fk] = (rk[1], ident["rev_label"])
            elif rk[1] < rev_max[fk][0]: rev_prev_lbl[fk] = ident["rev_label"]
    kept_final, superseded = [], []
    for it, ident in parsed_finals:
        keys_here = [_norm_rel(it.get("open_path")).lower(), _norm_rel(it.get("path")).lower(), str(it.get("product_id") or "").lower()]
        if (exp_w := next((exp_sup_by[k] for k in keys_here if k and k in exp_sup_by), "")): superseded.append({**it, "archive_reason": "superseded", "superseded_by": exp_w}); continue
        if (rk := ident["rev_key"]) is not None and ident["base_stem"]:
            fk = (*ident["family_tuple"], rk[0]); max_nums, max_lbl = rev_max[fk]
            if rk[1] < max_nums: superseded.append({**it, "archive_reason": "superseded", "superseded_by": max_lbl, "curation_note": f"Superseded by {max_lbl}"}); continue
            if rev_prev_lbl.get(fk) and rev_prev_lbl[fk] != max_lbl: it = {**it, "curation_note": f"\u2713 Steward superseded {rev_prev_lbl[fk]} \u2192 {max_lbl} automatically"}
        if any(_norm_rel(w).lower() in keys_here for w in exp_sup_by.values()): it = {**it, "curation_note": it.get("curation_note") or "\u2713 Steward curated & archived prior revision"}
        kept_final.append(it)
    kept_keys, sup_keys = {_norm_rel(it.get("open_path") or it.get("path")).lower() for it in kept_final}, {_norm_rel(it.get("open_path") or it.get("path")).lower() for it in superseded}
    earlier_raw = list(superseded) + [{**it, "archive_reason": "earlier"} for it in clean_items if (pk := _norm_rel(it.get("open_path") or it.get("path")).lower()) and pk not in sup_keys and pk not in kept_keys and pk not in recent_keys and not it.get("auto")]
    return {"most_recent_batches": recent_batches_out, "most_recent_summary": {"batch_count": len(recent_batches_out), "file_count": sum(b["file_count"] for b in recent_batches_out)}, "final": _bundle_format_siblings(kept_final), "final_items": kept_final, "earlier": _bundle_format_siblings(earlier_raw), "earlier_items": earlier_raw}
def compute_shelves_for_campaign(cdir: str | Path, decorated_items: list[dict[str, Any]], *, approved: list[dict[str, Any]] | None = None, refinement_state: dict[str, Any] | None = None) -> dict[str, Any]:
    has_dir = bool(str(cdir or "").strip() and Path(cdir).is_dir()); bdoc = dict(read_batches_doc(cdir)) if has_dir else None
    if has_dir:
        if refinement_state is None:
            try:
                from . import steward_campaign as _sc
                ref_obj = _sc.read_refinement(str(cdir), stale_ok=True)
                refinement_state = ref_obj.get("state") if (isinstance(ref_obj, dict) and ref_obj.get("ok")) else None
            except Exception: refinement_state = None
            if refinement_state is None: refinement_state = _MEM_REF_STATES.get(os.path.normcase(os.path.abspath(str(cdir))))
        if isinstance(refinement_state, dict) and isinstance(bdoc, dict) and (disc := discover_refinement_batches(cdir, refinement_state)):
            bdoc = {**bdoc, "batches": _dedupe_and_trim_batches(list(bdoc.get("batches") or []) + disc)}
    return compute_shelves(decorated_items, bdoc, approved=approved, conv_batches=_mine_conversation_batches(cdir) if has_dir else [])
